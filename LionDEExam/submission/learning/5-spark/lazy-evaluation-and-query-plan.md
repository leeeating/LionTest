# Lazy evaluation 與查詢計畫（explain）
Spark 的 DataFrame 操作分兩種：transformation 只是把步驟記進計畫，action 才真的執行。執行前 Catalyst 會改寫整份計畫（例如把 filter 推到讀檔），用 `explain()` 可以看到它最後決定怎麼跑。

## 白話版
- **跟 C# LINQ 的 `IQueryable` 一樣**：`db.Orders.Where(o => o.Amount > 900).Select(...)` 不會查資料庫，只是組出一棵運算式樹；呼叫 `.ToList()`、`.Count()` 時，EF 才把整棵樹翻成一句 SQL 送出去。Spark 的 `filter`、`select`、`join`、`groupBy` 就是 `Where`、`Select`；`count()`、`collect()`、`show()`、`write` 就是 `.ToList()`。Python 類比是 generator：`(x for x in rows if x > 900)` 建好不會跑，`list(...)` 才跑。
- **為什麼要延遲**：等看到整條鏈再決定怎麼跑，才能整體最佳化。Catalyst 的四個階段：Parsed（照你寫的）→ Analyzed（對上欄位與型別）→ Optimized（改寫，例如 filter 往下推、只讀需要的欄位）→ Physical（選實際演算法，例如 BroadcastHashJoin 或 SortMergeJoin）。
- **PySpark 的 Python 只是遙控器**：你寫的 Python 只是在 JVM 裡組計畫，真正處理資料的是 JVM。內建函式（`F.col("a") * F.col("b")`）整段在 JVM 跑；**Python UDF** 則要把每批資料序列化送到另一個 Python worker 程序算完再送回來，而且 Catalyst 看不懂 UDF 裡面在做什麼，沒辦法最佳化它。所以**能用內建函式就不要寫 UDF**。

## 什麼時候用、什麼時候不要用
- **`explain()` 的時機**：效能可疑、想確認 filter 有沒有推下去、join 用了哪種策略、有沒有多餘的 shuffle（`Exchange`）、隱式轉型（`cast(...)`）出現在哪裡時。預設只印物理計畫；`explain(True)`（或 `mode="extended"`）印四個階段；`mode="formatted"` 把物理計畫拆成編號節點加細節，長計畫比較好讀。
- **讀計畫的方向**：由下往上讀，最下面是讀資料（`FileScan`、`Scan`），往上一層層處理。重點看：`PushedFilters`（推到讀檔的條件）、`PartitionFilters`（略過的資料夾）、`ReadSchema`（實際讀哪些欄）、`Exchange`（shuffle）、`BatchEvalPython`／`ArrowEvalPython`（Python UDF）。
- **UDF 什麼時候可以用**：內建函式真的做不到的邏輯（呼叫外部函式庫、複雜的字串解析）。需要時優先用 pandas UDF（`@pandas_udf`），一次處理一整批而不是一列。

## 最小可跑範例
PySpark 4.2.0，local 模式，先寫一份 200 萬列的 parquet。在 repo 根目錄執行 `uv run python -I /tmp/spark_notes/lazy_demo.py 2>/dev/null`（exit code 0）：

```python
import os, shutil, tempfile, time
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import DoubleType

spark = (SparkSession.builder.master("local[2]")
         .config("spark.sql.adaptive.enabled", "false")
         .getOrCreate())
spark.sparkContext.setLogLevel("ERROR")

path = os.path.join(tempfile.mkdtemp(), "orders")
spark.range(2_000_000).select(
    F.col("id").alias("order_id"),
    (F.col("id") % 1000 + 0.5).alias("amount"),
    F.lit(31.5).alias("rate"),
).write.parquet(path)

print("== [1] transformation 只是建計畫，不跑 ==")
t = time.perf_counter()
df = spark.read.parquet(path).filter(F.col("amount") > 900).select("order_id", "amount")
print(f"建好 df 花 {time.perf_counter() - t:.3f} 秒，型別 {type(df).__name__}")
t = time.perf_counter()
n = df.count()                      # action：這時才真的讀檔、過濾
print(f"count() = {n}，花 {time.perf_counter() - t:.3f} 秒")

print("== [2] explain(True)：Catalyst 把 filter 推到讀檔（PushedFilters） ==")
df.explain(True)

print("== [3] Python UDF vs 內建函式 ==")
src = spark.read.parquet(path)
to_twd = F.udf(lambda a, r: a * r, DoubleType())
udf_df = src.select((to_twd("amount", "rate")).alias("twd"))
builtin_df = src.select((F.col("amount") * F.col("rate")).alias("twd"))
udf_df.explain()
builtin_df.explain()
for name, d in [("Python UDF", udf_df), ("內建乘法", builtin_df)]:
    d.agg(F.sum("twd")).collect()   # 先暖身一次
    t = time.perf_counter()
    s = d.agg(F.sum("twd")).collect()[0][0]
    print(f"{name}: sum={s:.1f}，花 {time.perf_counter() - t:.3f} 秒")

shutil.rmtree(os.path.dirname(path))
spark.stop()
```

實際輸出（節錄；`[2]` 的四段計畫完整保留，`FileScan` 行省略暫存路徑；秒數每次執行會不同）：

```
== [1] transformation 只是建計畫，不跑 ==
建好 df 花 0.105 秒，型別 DataFrame
count() = 200000，花 0.319 秒
== [2] explain(True)：Catalyst 把 filter 推到讀檔（PushedFilters） ==
== Parsed Logical Plan ==
'Project ['order_id, 'amount]
+- Filter (amount#5 > cast(900 as double))
   +- Relation [order_id#4L,amount#5,rate#6] parquet

== Analyzed Logical Plan ==
order_id: bigint, amount: double
Project [order_id#4L, amount#5]
+- Filter (amount#5 > cast(900 as double))
   +- Relation [order_id#4L,amount#5,rate#6] parquet

== Optimized Logical Plan ==
Project [order_id#4L, amount#5]
+- Filter (isnotnull(amount#5) AND (amount#5 > 900.0))
   +- Relation [order_id#4L,amount#5,rate#6] parquet

== Physical Plan ==
*(1) Filter (isnotnull(amount#5) AND (amount#5 > 900.0))
+- *(1) ColumnarToRow
   +- FileScan parquet [order_id#4L,amount#5] Batched: true, DataFilters: [isnotnull(amount#5), (amount#5 > 900.0)], Format: Parquet, Location: InMemoryFileIndex(1 paths)[...], PartitionFilters: [], PushedFilters: [IsNotNull(amount), GreaterThan(amount,900.0)], ReadSchema: struct<order_id:bigint,amount:double>

== [3] Python UDF vs 內建函式 ==
== Physical Plan ==
*(2) Project [pythonUDF0#21 AS twd#18]
+- BatchEvalPython [<lambda>(amount#15, rate#16)#17], [pythonUDF0#21]
   +- *(1) ColumnarToRow
      +- FileScan parquet [amount#15,rate#16] ...

== Physical Plan ==
*(1) Project [(amount#15 * rate#16) AS twd#20]
+- *(1) ColumnarToRow
   +- FileScan parquet [amount#15,rate#16] ...

Python UDF: sum=31500000000.0，花 0.601 秒
內建乘法: sum=31500000000.0，花 0.073 秒
```

怎麼讀：
- **[1]** 建 df 的 0.1 秒是讀 parquet footer 拿 schema，沒有掃資料；`count()` 才真的讀 200 萬列、過濾出 20 萬列。
- **[2]** 從 Analyzed 到 Optimized，Catalyst 把 `900` 先算成 `900.0`、補上 `isnotnull`；Physical 的 `FileScan` 出現 `PushedFilters: [IsNotNull(amount), GreaterThan(amount,900.0)]`，表示條件交給 parquet reader，可以用 row group 的統計跳過整段；`ReadSchema` 只有兩欄，`rate` 沒被讀（column pruning）。
- **[3]** UDF 版多了一個 `BatchEvalPython` 節點，計算被切成兩個 codegen 區段 `*(1)`、`*(2)`；內建版整段在同一個 `*(1)` 裡。同樣結果，本機實測 UDF 慢約 8 倍（一次量測，非嚴謹 benchmark）。

## 常見的坑
- **以為寫了就跑了**：transformation 的錯（例如型別轉不過）要到 action 才爆出來，錯誤訊息的位置可能離真正寫錯的那行很遠。
- **同一個 df 做多次 action 就重算多次**：上面範例每次 `count()`、`collect()` 都從讀檔重新開始。要重複用時考慮 `cache()`，用完 `unpersist()`。
- **`collect()` 把整個結果搬回 driver**：driver 是一台機器的一個程序，資料大就 OOM。驗證用 `count()`、`agg()` 在叢集算完只拿回一個數字。
- **隱式轉型藏在計畫裡**：字串欄位跟數字比較時，計畫會出現 `cast(amount as int)`，結果取決於 `spark.sql.ansi.enabled`。不看 `explain()` 很難發現。
- **UDF 擋住最佳化**：Catalyst 不知道 UDF 的語意，UDF 結果上的 filter 推不下去；pickled UDF 的型別處理還會在不符時默默回 `None`（官方文件稱 type coercion 有限制）。

## 本專案出處
- Part B #1（`load_sources`，`part_b/code-review.md`「CSV 不指定 schema，金額比較靠隱式轉型」）：用 `explain()` 看到 `filter(F.col("amount") > 0)` 的計畫是 `cast(amount#... as int) > 0`，證據在 `part_b/evidence.md` 的「E5｜pyspark 語意驗證：…#1 隱式轉型的 explain」。
- Part B #5（`convert_currency`）：`to_twd_udf = F.udf(to_twd, DoubleType())` 只做一個乘法，修法是改用內建運算；`part_b/future-improvements.md` 的 A1 另記了 UDF 裡 `if amount is None: return 0.0` 其實執行不到。
- Part B #10（`write_fact`）：`spark.read.format("delta").load(f"{LAKEHOUSE}/fact/fact_order").collect()` 把整張事實表搬進 driver 再用 Python 迴圈計數。
- ADR-01（`decisions/ADR-01-execution-engine.md`）：選 PySpark＋Delta 的代價之一是「local 模式每次啟動 SparkSession 要幾秒」，因為要先啟動 JVM，Python 才有東西可以遙控；所以 pytest 共用一個 session 層級的 SparkSession fixture。

## 官方文件
實際讀過：
- RDD Programming Guide（transformation 是 lazy、action 才觸發計算）：https://spark.apache.org/docs/latest/rdd-programming-guide.html#rdd-operations
- EXPLAIN 語法（預設只印物理計畫；EXTENDED、CODEGEN、COST、FORMATTED 各印什麼）：https://spark.apache.org/docs/latest/sql-ref-syntax-qry-explain.html
- Parquet Files（`spark.sql.parquet.filterPushdown` 預設 true）：https://spark.apache.org/docs/latest/sql-data-sources-parquet.html
- Apache Arrow in PySpark（Arrow 用來在 JVM 與 Python 程序間傳資料、pandas UDF、pickled UDF 的型別限制、Spark 4.2 起一般 Python UDF 預設開 Arrow 最佳化）：https://spark.apache.org/docs/latest/api/python/tutorial/sql/arrow_pandas.html

未證實：
- Catalyst 四階段的名稱是照 `explain(True)` 的實際輸出寫的；這次沒有讀 Catalyst 的設計文件。
- 「Catalyst 無法最佳化 UDF、UDF 上的 filter 推不下去」是一般說法，官方頁面沒有這句，這次也沒有實測。
- 官方文件說 Spark 4.2 起 Python UDF 預設開 Arrow（本機 `spark.sql.execution.pythonUDF.arrow.enabled` 也是 `true`），但範例的計畫顯示 `BatchEvalPython` 而不是 `ArrowEvalPython`。原因沒有查證。
