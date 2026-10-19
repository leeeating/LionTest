# Delta time travel：讀回表的舊版本
Delta 每次寫入都會產生一個新版本（0、1、2…）。time travel 就是指定版本號或時間點，讀回當時的整張表；`RESTORE` 則能把表退回某個版本。

## 白話版
就像記帳本每一頁都留著不撕掉。想知道「昨天記帳之前長什麼樣」，翻回那一頁就好，不用自己另外備份。

## 什麼時候用、什麼時候不要用
- **適合**：
  - 重跑某一批時，要和「這批寫入之前」的狀態比對（本專案的冪等重跑）
  - 查錯：比對兩個版本差在哪裡
  - 誤寫之後回復：用 `RESTORE`
  - 稽核：查某個時間點的報表數字
- **不適合**：
  - 長期保存歷史。`VACUUM` 預設會刪掉 7 天前不再被引用的資料檔，之後那些版本就讀不到；版本紀錄（`_delta_log`）預設也只保留 30 天
  - 需要長期歷史時，要用 SCD2、bronze 原始層或備份，不要依賴 time travel

## 最小可跑範例
在 repo 根目錄執行：`PYTHONPATH=LionDEExam/submission/part_a uv run python /tmp/tt_demo/demo.py`（2026-10-19 實跑）

```python
import shutil
from delta.tables import DeltaTable
from pipeline.session import build_spark

spark = build_spark()
path = "/tmp/tt_demo/orders"
shutil.rmtree(path, ignore_errors=True)

# 版本 0：建立
spark.createDataFrame([("ORD001", "paid")], "order_id string, status string") \
    .write.format("delta").save(path)

# 版本 1：MERGE（沒有標記）
src = spark.createDataFrame([("ORD001", "cancelled"), ("ORD002", "created")], "order_id string, status string")
(DeltaTable.forPath(spark, path).alias("t")
    .merge(src.alias("s"), "t.order_id = s.order_id")
    .whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())

# 版本 2：MERGE，commit 帶上標記 batch:day1
spark.conf.set("spark.databricks.delta.commitInfo.userMetadata", "batch:day1")
src2 = spark.createDataFrame([("ORD002", "paid")], "order_id string, status string")
(DeltaTable.forPath(spark, path).alias("t")
    .merge(src2.alias("s"), "t.order_id = s.order_id")
    .whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())
spark.conf.unset("spark.databricks.delta.commitInfo.userMetadata")

DeltaTable.forPath(spark, path).history().select("version", "operation", "userMetadata").orderBy("version").show()
spark.read.format("delta").load(path).orderBy("order_id").show()                              # 目前
spark.read.format("delta").option("versionAsOf", 0).load(path).orderBy("order_id").show()     # 版本 0
spark.sql(f"SELECT * FROM delta.`{path}` VERSION AS OF 1 ORDER BY order_id").show()            # SQL 寫法
spark.sql(f"RESTORE TABLE delta.`{path}` TO VERSION AS OF 1")                                  # 整張表退回
```

實際輸出（已刪掉 Spark 的啟動訊息與表格框線）：
```
== history
|version|operation|userMetadata|
|      0|    WRITE|        NULL|
|      1|    MERGE|        NULL|
|      2|    MERGE|  batch:day1|

== 目前
|  ORD001|cancelled|
|  ORD002|     paid|

== versionAsOf 0
|  ORD001|  paid|

== SQL VERSION AS OF 1
|  ORD001|cancelled|
|  ORD002|  created|

== RESTORE TO VERSION 1 之後
|  ORD001|cancelled|
|  ORD002|  created|
```

除了指定版本號，也可以用時間點讀取：`option("timestampAsOf", "2026-10-19 10:04:00")`（範例沒有實跑這一種）。

## 常見的坑
- **舊版本會消失**：`VACUUM` 之後就讀不到被清掉的版本，所以 time travel 只適合「最近幾天內」的重跑或查錯。
- **標記要自己加**：`userMetadata` 預設是空的。想知道某個版本是哪一批寫的，寫入前就要先設好 `spark.databricks.delta.commitInfo.userMetadata`，寫完記得 `unset`，否則下一次寫入也會帶上同一個標記。
- **MERGE 0 列不會產生版本**：沒有資料要寫時不會 commit，也就沒有標記可找（T6 實作者指出的限制）。
- **時間點有時區問題**：`timestampAsOf` 會依 session timezone 解讀，本專案固定 Asia/Taipei。

## 本專案出處
- T6：同一批重跑或當掉後重跑時，先在 fact_order 的版本紀錄裡找到這批的第一個 `batch:<id>` 標記，讀它的前一版來比對，讓重跑的分類與對帳和第一次完全相同。冪等證明見 `part_a/README.md` 的「冪等證明」。
- 函式：`delta_io.py` 的 `version_before_marker`、`merge_upsert` 的 `commit_marker` 參數。
- 待使用者決定：這個重跑機制要不要寫成 ADR（工作檔 T6 節）。

## 官方文件
未證實：本筆記依 AI 既有知識整理，並以上方實跑確認語法與行為；保留期限的預設值（VACUUM 7 天、log 30 天）沒有在這次打開官方文件核對。之後要引用時，查 Delta Lake 文件的 "Table batch reads and writes"（time travel）與 "Remove files no longer referenced by a Delta table"（VACUUM）。
