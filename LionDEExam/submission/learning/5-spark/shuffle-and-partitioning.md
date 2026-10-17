# Shuffle 與分區（partitioning）
Shuffle 是 Spark 把資料**依 key 重新分堆、跨 executor 搬家**的步驟，是分散式查詢最貴的一段；GROUP BY、JOIN、ORDER BY、window 都會觸發。「分區」這個詞在 Spark 有三層意思，只有「計算中的分區」跟 shuffle 直接相關。

## 白話版
- **Shuffle 像郵差重新分信**：每個 executor 手上一袋信（一個計算分區），信是亂的。要「依會員加總」，就得讓同一位會員的信全部到同一個人手上。於是每個人先把手上的信依區號分小堆、**寫到磁碟**，再由下一階段的人**透過網路**去各處把屬於自己區的那堆拿回來。慢就慢在這兩步：寫磁碟＋網路交換（官方文件說的 disk I/O、serialization、network I/O）。
- **在計畫裡怎麼認**：`explain()` 的物理計畫出現 `Exchange` 就是 shuffle；`hashpartitioning(key, n)` 是依 key 雜湊分成 n 堆（GROUP BY、JOIN、window），`rangepartitioning` 是依範圍分堆（ORDER BY）。
- **Broadcast join 是不分信的捷徑**：一邊是小表（例如會員等級對照表）時，直接影印一份給每個 executor，大表原地不動逐列查，大表就不用 shuffle。類比 Python：與其把兩個大 list 都依 key 排序再合併，不如把小的那份做成 `dict`，發給每個 worker。

**三層「分區」不是同一件事**：

| 層 | 是什麼 | 影響什麼 | 比喻 |
|---|---|---|---|
| 目錄分區 `write.partitionBy("order_date")` | 寫檔時依欄位值分資料夾 `order_date=2026-07-01/` | **讀多少資料**：篩選條件用到分區欄位時，整個資料夾可以不讀（`PartitionFilters`） | 信依日期裝不同袋子 |
| Parquet row group | 一個 parquet 檔內部的分段，每段記錄各欄的 min/max | **檔案內跳過多少**：`PushedFilters` 拿 min/max 判斷整段可不可以跳過 | 袋子裡再用橡皮筋綁成幾疊，每疊貼著號碼範圍 |
| 計算中的分區 | 執行時記憶體中的資料切塊，一塊一個 task | **平行度與 shuffle**：shuffle 後的塊數由 `spark.sql.shuffle.partitions` 決定（預設 200） | 每個郵差手上那一袋 |

關鍵：**目錄分區只決定讀哪些袋子，不會讓 GROUP BY 免掉 shuffle**。即使只讀了 `order_date=2026-07-01` 一個資料夾，要依 `member_id` 加總，還是得把同一位會員的列分到同一堆（範例 [5]）。

## 什麼時候用、什麼時候不要用
- **broadcast join**：一邊明顯小（預設門檻 `spark.sql.autoBroadcastJoinThreshold` = 10 MB）時用；Spark 不知道表大小時（例如剛 `createDataFrame` 出來的）可以用 `F.broadcast(df)` 提示。兩邊都大就不要硬 broadcast，會把 driver 和 executor 記憶體塞爆。
- **目錄分區**：查詢幾乎都帶某個低基數欄位的篩選（日期、地區），且每個分區的資料量夠大時用。基數高的欄位（`member_id`、`order_id`）不要拿來 `partitionBy`。
- **避免不必要的 shuffle**：能先 filter、先選欄位再 join／group 就先做；同一個 key 連續做幾件事，盡量合在同一次 shuffle 後。

## 最小可跑範例
PySpark 4.2.0，local 模式。為了計畫好讀，關掉 AQE、把 shuffle 分區數設成 4。在 repo 根目錄執行 `uv run python -I /tmp/spark_notes/shuffle_demo.py 2>/dev/null`（exit code 0）：

```python
import glob, os, shutil, tempfile
from pyspark.sql import SparkSession, functions as F

spark = (SparkSession.builder.master("local[2]")
         .config("spark.sql.shuffle.partitions", "4")
         .config("spark.sql.adaptive.enabled", "false")   # 關掉 AQE，計畫比較好讀
         .getOrCreate())
spark.sparkContext.setLogLevel("ERROR")

orders = spark.createDataFrame(
    [(f"O{i}", f"M{i % 3}", ["2026-07-01", "2026-07-02"][i % 2], 100.0 * i) for i in range(1, 9)],
    "order_id string, member_id string, order_date string, amount double")
members = spark.createDataFrame([("M0", "普卡"), ("M1", "金卡"), ("M2", "普卡")],
                                "member_id string, level string")

print("== [1] GROUP BY：計畫裡的 Exchange hashpartitioning 就是 shuffle ==")
orders.groupBy("member_id").agg(F.sum("amount")).explain()

print("== [2] JOIN（預設）：Spark 不知道記憶體 DataFrame 多大，走 SortMergeJoin，兩邊都 Exchange ==")
orders.join(members, "member_id").explain()

print("== [3] JOIN 加 broadcast hint：小表複製到每個 executor，大表不 shuffle ==")
orders.join(F.broadcast(members), "member_id").explain()

print("== [3b] ORDER BY 與 window 也會 shuffle ==")
from pyspark.sql import Window
orders.orderBy("amount").explain()
orders.withColumn("rn", F.row_number().over(Window.partitionBy("order_id").orderBy("amount"))).explain()

print("== [4] 目錄分區：partitionBy 依 order_date 分資料夾 ==")
path = os.path.join(tempfile.mkdtemp(), "fact_order")
orders.write.partitionBy("order_date").parquet(path)
for d in sorted(os.listdir(path)):
    if d.startswith("order_date="):
        print(d, len(glob.glob(os.path.join(path, d, "*.parquet"))), "個 parquet 檔")

print("== [5] 依分區欄位篩選：PartitionFilters 只讀一個資料夾，但 GROUP BY 仍有 Exchange ==")
spark.read.parquet(path).filter("order_date = '2026-07-01'").groupBy("member_id").agg(F.sum("amount")).explain()

print("== [6] skew：一個 key 佔大多數，shuffle 後落在同一個分區 ==")
skewed = spark.range(1000).withColumn("member_id", F.when(F.col("id") < 900, "M_HOT").otherwise(F.concat(F.lit("M"), F.col("id") % 50)))
sizes = skewed.repartition(4, "member_id").groupBy(F.spark_partition_id().alias("pid")).count().orderBy("pid").collect()
print([(r.pid, r["count"]) for r in sizes])

shutil.rmtree(os.path.dirname(path))
spark.stop()
```

實際輸出（節錄關鍵行；`#數字` 是欄位內部編號，每次執行可能不同）：

```
== [1] GROUP BY ==
*(2) HashAggregate(keys=[member_id#1], functions=[sum(amount#3)])
+- Exchange hashpartitioning(member_id#1, 4), ENSURE_REQUIREMENTS, [plan_id=17]
   +- *(1) HashAggregate(keys=[member_id#1], functions=[partial_sum(amount#3)])

== [2] JOIN（預設）==
+- *(5) SortMergeJoin [member_id#1], [member_id#4], Inner
   :  +- Exchange hashpartitioning(member_id#1, 4), ENSURE_REQUIREMENTS, [plan_id=61]
      +- Exchange hashpartitioning(member_id#4, 4), ENSURE_REQUIREMENTS, [plan_id=67]

== [3] JOIN 加 broadcast hint ==
+- *(2) BroadcastHashJoin [member_id#1], [member_id#4], Inner, BuildRight, false, false
   :  +- *(2) Scan ExistingRDD[order_id#0,member_id#1,order_date#2,amount#3]
   +- BroadcastExchange HashedRelationBroadcastMode(List(input[0, string, false]),false), [plan_id=116]

== [3b] ORDER BY 與 window ==
+- Exchange rangepartitioning(amount#3 ASC NULLS FIRST, 4), ENSURE_REQUIREMENTS, [plan_id=137]
   +- Exchange hashpartitioning(order_id#0, 4), ENSURE_REQUIREMENTS, [plan_id=157]

== [4] 目錄分區 ==
order_date=2026-07-01 2 個 parquet 檔
order_date=2026-07-02 2 個 parquet 檔

== [5] 依分區欄位篩選 ==
+- Exchange hashpartitioning(member_id#17, 4), ENSURE_REQUIREMENTS, [plan_id=195]
   FileScan parquet [...] PartitionFilters: [isnotnull(order_date#19), (order_date#19 = 2026-07-01)], PushedFilters: [], ...

== [6] skew ==
[(0, 40), (1, 14), (2, 920), (3, 26)]
```

怎麼讀：
- **[1]** GROUP BY 分兩段：先在各分區做 `partial_sum`（郵差先把手上同一人的信加總，少寄一點），再 `Exchange`，再做最終 `sum`。
- **[2] vs [3]**：同一個 join，沒提示時兩邊都 `Exchange`；加 `F.broadcast` 後變成 `BroadcastHashJoin`，大表那邊直接 `Scan`，沒有 `Exchange`。
- **[4]** 8 列資料寫出 4 個檔：檔案數 ≈ 寫入的 task 數 × 每個 task 碰到的分區數（這裡 2 × 2）。這就是小檔問題的來源。
- **[5]** `PartitionFilters` 讓 Spark 只讀一個資料夾，但上面照樣有 `Exchange`：目錄分區省的是讀取，不是 shuffle。
- **[6]** 1000 列裡 900 列是 `M_HOT`，shuffle 後分區 2 拿到 920 列、其他只有幾十列。整個 stage 要等最慢的那個 task，其他 executor 都在空等。

## 常見的坑
分區選不好的三種後果：
1. **小檔太多**：每次寫入都碰到很多分區，每個分區各寫一個小檔。讀的時候光列檔、開檔、讀 metadata 就花掉大半時間。對策：較粗的分區（例如月）、寫入前 `repartition` 分區欄位、Delta 定期 `OPTIMIZE`。
2. **Skew**：某個 key 或某個分區特別大（範例 [6]）。AQE 開著時 Spark 會自動拆開 sort-merge join 的傾斜分區（`spark.sql.adaptive.skewJoin.enabled`）；GROUP BY 的傾斜要自己處理，例如先加隨機後綴（salting）做部分加總再合併。
3. **查詢條件用不到分區**：依 `order_date` 分區，但報表都用 `member_id` 或 `updated_at` 篩，`PartitionFilters` 永遠是空的，分區只帶來小檔、沒帶來好處。用 `explain()` 看 `PartitionFilters` 有沒有值來確認。

其他：
- **local 模式的 `spark.sql.shuffle.partitions` 預設 200**，小資料一個 GROUP BY 就開 200 個 task；AQE（Spark 3.2 起預設開）會在 shuffle 後自動合併小分區。
- **在篩選欄位外面包函式**（例如 `to_date(order_date) = ...`）可能讓 `PartitionFilters` 失效；以 `explain()` 實際看為準。

## 本專案出處
- `part_b/future-improvements.md` 的「F3 依 `order_date` 分區產生小檔」：`write_fact` 用 `partitionBy("order_date")`，審查 agent 實測 day1 寫入 62 個分區、62 個檔，day2 MERGE 後 `numTargetFilesAdded=63`。增量批次包含舊訂單的更新，所以「每批寫入的檔案數 ≈ 被碰到的分區數」，跟總量無關；小不小要看 prod 每個分區每次寫入的量（process-log 事件「整理 DE 審查結果：漏抓的項目列為之後改善，小檔問題改看 prod 資料量」）。
- `buggy_pipeline.py`／`part_b/code-review.md`：`Window.partitionBy("order_id").orderBy(...)` 的去重、`converted.join(members, "member_id", "left")` 都是會 shuffle 的操作；這裡的 `Window.partitionBy` 是計算中的分區，跟寫檔的 `partitionBy` 同名不同義。

## 官方文件
實際讀過：
- RDD Programming Guide 的 Shuffle operations（哪些操作會 shuffle、為什麼貴：disk I/O、serialization、network I/O、磁碟上的中間檔）：https://spark.apache.org/docs/latest/rdd-programming-guide.html#shuffle-operations
- SQL Performance Tuning（`autoBroadcastJoinThreshold` 10 MB、join hints、`spark.sql.shuffle.partitions` 200、AQE 合併分區與 skew join）：https://spark.apache.org/docs/latest/sql-performance-tuning.html
- Parquet Files 的 Partition Discovery（`key=value` 目錄結構）與 `spark.sql.parquet.filterPushdown`：https://spark.apache.org/docs/latest/sql-data-sources-parquet.html

未證實：
- 「row group 記錄 min/max、`PushedFilters` 用它跳過整段」是 Parquet 格式的一般說法，上述 Spark 頁面沒有寫到 row group 細節，這次也沒有實測（環境沒有 pyarrow 可看 metadata）。
- 「包函式會讓 `PartitionFilters` 失效」是一般經驗，這次沒有實測。
- salting 是社群常見做法，非官方文件內容。
