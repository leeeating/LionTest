# DuckDB vs Spark：怎麼選分析引擎
DuckDB 是跑在你程式裡的單機分析資料庫，Spark 是要起 JVM、由一個 driver 分工給多個 executor 的分散式引擎；先問「資料一台機器吃不吃得下」，再看正式平台用什麼。

## 白話版
- **DuckDB 像單人計算機**：`pip install duckdb` 就能用，沒有 server，引擎就在你的 Python process 裡（官方：「completely embedded within a host process」）。可以想成 **SQLite 的分析版**：SQLite 擅長一筆一筆讀寫，DuckDB 擅長整欄掃描、加總。
- **Spark 像有工頭分工的工廠**：driver（工頭）把工作切成 task，發給 executor（工人）平行做。開工前要先把工廠開起來（啟動 JVM、建 SparkSession），這個固定成本不管資料多小都要付。本機 `local[*]` 模式是工頭和工人都在同一台電腦，寫法和上叢集一樣。

**跟直接連 SQL DB 有什麼不同**：連 SQL Server 是 server 模式，C# 用 `SqlConnection` 把 SQL 送到另一個 process（通常在另一台機器）去算，結果再傳回來；DuckDB 是 in-process，`duckdb.sql(...)` 就像在程式裡呼叫一個函式庫直接算，沒有連線、帳密、網路。代價是它不是多人共用的服務：同一個 `.duckdb` 檔，同一時間要嘛只有一個 process 讀寫，要嘛多個 process 都唯讀開啟，兩者不能並存（官方 concurrency 頁）；一個 process 以讀寫模式開著時，另一個 process 用 `read_only=True` 開會失敗：`IO Error: Could not set lock on file ... Conflicting lock is held`。

**資料在雲端時 DuckDB 怎麼用**：不用先下載整個檔。DuckDB 可以直接 `SELECT ... FROM 's3://bucket/orders/*.parquet'`（Azure 用 azure extension），Parquet 是按欄存，它只抓查詢用到的欄位（projection pushdown），並用檔案內的統計跳過不相關的區段（filter pushdown）。但**計算仍在你這台機器**：資料是從雲端拉過來算的，不是雲端幫你算。Spark 叢集則是把運算放到靠近資料的多台機器上。

## 什麼時候用、什麼時候不要用
| 問題 | 傾向 DuckDB | 傾向 Spark |
|---|---|---|
| 資料量 | 單機記憶體／磁碟處理得了（GB 到數百 GB 級，視機器而定） | 單機吃不下、要水平擴充 |
| 正式平台 | 沒有指定平台，或是本機分析、CI | Fabric、Databricks 的運算引擎就是 Spark，寫法可直接搬上去 |
| 啟動成本 | 幾乎為零，適合短任務、pytest | 每次啟動幾秒，測試要共用 session |
| 多人並行寫入 | 單一 process 寫入 | 搭配 Delta：多個 job 同時寫同一張表，靠 transaction log 偵測衝突（見 [data-lake-vs-warehouse.md](data-lake-vs-warehouse.md)「Delta 是什麼」） |
| 本機開發測試 | 只要 Python 套件 | 要裝 Java |

**常見組合**：正式環境用 Spark，本機探索資料、寫一次性的檢查查詢用 DuckDB。

## 最小可跑範例
同一個查詢（`orders_base.csv` 依 currency 計數），量含啟動在內的總耗時。在 repo 根目錄執行 `uv run python -I /tmp/engine_compare.py`：

```python
import time

CSV = "LionDEExam/candidate_package/dataset/orders_base.csv"

# --- DuckDB：in-process，import 完就能查 ---
t0 = time.perf_counter()
import duckdb
rows = duckdb.sql(f"""
    SELECT currency, count(*) AS n
    FROM read_csv('{CSV}', all_varchar = true)
    GROUP BY currency ORDER BY currency
""").fetchall()
print("duckdb", rows, f"{time.perf_counter() - t0:.2f}s")

# --- PySpark：先起 JVM 與 SparkSession，再查 ---
t0 = time.perf_counter()
from pyspark.sql import SparkSession
spark = SparkSession.builder.master("local[*]").getOrCreate()
spark.sparkContext.setLogLevel("ERROR")
t_start = time.perf_counter() - t0
df = spark.read.option("header", True).csv(CSV)  # 預設全部讀成字串
df.createOrReplaceTempView("orders")
rows = spark.sql("SELECT currency, count(*) AS n FROM orders GROUP BY currency ORDER BY currency").collect()
print("spark ", [(r.currency, r.n) for r in rows], f"{time.perf_counter() - t0:.2f}s（其中啟動 {t_start:.2f}s）")
print("first column names:", duckdb.sql(f"SELECT * FROM read_csv('{CSV}') LIMIT 0").columns[0].encode(), df.columns[0].encode())
spark.stop()
```

實際輸出（duckdb 1.5.6、pyspark 4.2.0、Java 21，macOS 本機；stderr 的 Spark 啟動訊息略去），exit code 0：

```
duckdb [('JPY', 11022), ('NTD', 200), ('TWD', 66690), ('USD', 22128)] 0.34s
spark  [('JPY', 11022), ('NTD', 200), ('TWD', 66690), ('USD', 22128)] 6.48s（其中啟動 4.03s）
first column names: b'order_id' b'order_id'
```

- 結果一樣，耗時差約 19 倍，大部分是 Spark 的啟動成本。這是 10 萬列的 demo 資料，**不能拿來推論 prod 資料量下誰快**。耗時每次跑會有差異。
- 最後一行用 `.encode()` 檢查第一個欄名：CSV 開頭有 UTF-8 BOM，兩個引擎這次都自動略過了，欄名是乾淨的 `order_id`。如果換工具讀到 `'﻿order_id'`，`SELECT order_id` 就會找不到欄位。

## 常見的坑
- **拿 demo 資料量選引擎**：ADR-01 初稿寫「資料量用不到分散式運算」，使用者指出 CSV 是 demo 資料、不代表 prod，改成依正式平台與規模判斷。
- **以為 DuckDB 讀雲端檔就是雲端運算**：只是少傳資料，運算與記憶體仍在本機。
- **Spark 測試每個 test 各起一個 session**：啟動成本乘上測試數量，要用 session 層級的 fixture 共用。
- **讓引擎猜型別**：兩邊都用全字串讀入（DuckDB `all_varchar = true`、Spark 預設 `inferSchema=false`），轉型自己做，才看得到髒資料（例如上面的 `NTD`）。

## 本專案出處
- `decisions/ADR-01-execution-engine.md`：三個選項（DuckDB、PySpark＋Delta、pandas）的取捨；process-log 事件「Part A 執行引擎選 PySpark＋Delta」。
- `part_a/profiling/profile_sources.py`：用 PySpark 全字串讀 CSV（`.option("mode", "FAILFAST")`）；`part_a/source-schema-inference.md` 記錄 Spark 讀 CSV 時 BOM 已自動略過。

## 官方文件
- DuckDB 是 in-process、沒有 server：https://duckdb.org/why_duckdb
- DuckDB 單一 process 讀寫、多 process 唯讀：https://duckdb.org/docs/current/connect/concurrency.html
- Parquet 的 projection／filter pushdown、讀 HTTPS 上的檔：https://duckdb.org/docs/current/data/parquet/overview.html
- 讀 S3（httpfs、secrets、partial reading）：https://duckdb.org/docs/current/core_extensions/httpfs/s3api.html
- Spark 的 driver、cluster manager、executor：https://spark.apache.org/docs/latest/cluster-overview.html
- Fabric lakehouse 用 Delta Lake、以 Spark 與 SQL 分析：https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-overview
- 未證實：DuckDB 讀 Azure（azure extension）的用法、「GB 到數百 GB」的單機上限（一般經驗，非官方數字）。
