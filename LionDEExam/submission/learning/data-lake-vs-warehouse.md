# Data lake、data warehouse、lakehouse
資料存在哪裡、用什麼形式存：warehouse 把資料放進專門給分析用的資料庫，lake 把資料當開放格式的檔案放在便宜的雲端儲存，lakehouse 是在 lake 的檔案上補回資料庫的能力。

## 白話版
- **Data warehouse（資料倉儲）像私人廚房**：食材（資料）收進這個廚房自己的櫃子（產品專有的格式），只有這個廚房的廚師（查詢引擎）能用。寫進去之前要先定好格式（schema），進來的資料乾淨、好查。它是**專門給分析／報表用的資料庫**：資料從各個業務系統整理後匯入，跟應用程式日常讀寫用的資料庫（OLTP，例如訂單系統背後的 MySQL）不是同一個東西。例：Snowflake、BigQuery、Amazon Redshift。
- **Data lake（資料湖）像公共倉庫**：資料以檔案（CSV、Parquet）放在雲端儲存（AWS S3、Azure Blob／ADLS Gen2、OneLake），什麼格式都能先丟進來。誰要用就自己帶引擎來讀，Spark、DuckDB 讀的都是同一批檔案。代價是檔案沒有 `UPDATE`，寫到一半壞掉也不能回滾。
- **Lakehouse**：lake 的檔案加上一本「記帳本」（Delta Lake、Iceberg 這類表格式）。資料檔只新增不修改，記帳本記錄每次寫入後哪些檔案算數，於是有了 `UPDATE`／`MERGE`、寫入失敗不會壞、可以回到舊版本（time travel）。

**最根本的差別**：資料是鎖在單一產品的專有格式裡（warehouse），還是以開放格式的檔案存放、任何引擎都能讀（lake、lakehouse）。「儲存與運算分開」不是分界線，雲端 warehouse 也做得到。

用 Python 想像 lakehouse 的記帳本：

```python
log = [
    {"version": 0, "add": ["a.parquet"]},
    {"version": 1, "add": ["b.parquet"], "remove": ["a.parquet"]},  # 更新＝寫新檔＋標記舊檔作廢
]
# 讀最新版只讀 b.parquet；time travel 到 version 0 就讀 a.parquet（舊檔其實還在）
```

所以可以把 lakehouse 記成「lake ＋ 記錄哪些檔案算數的交易紀錄」。注意它和一般說的 changelog 不同：

| | 記什麼 | 例子 |
|---|---|---|
| Delta 的 transaction log | 每個版本由**哪些檔案**組成（add／remove），以及 schema 等 metadata | `_delta_log/` 裡的 JSON |
| 一般的 changelog（CDC） | **每一列**的變更，例如某張訂單從 pending 改成 completed | CDC 工具讀取的 MySQL binlog（ROW 格式） |

改一列資料時，Delta 預設會重寫那一列所在的整個檔案，再在記帳本上用新檔換掉舊檔；開啟 deletion vectors 時，改成另外記一份「哪些列作廢」的標記，不重寫原檔。Delta 另有選用的 Change Data Feed 可以輸出逐列變更，但那是額外功能，不是記帳本本身的內容。

| | Warehouse | Lake | Lakehouse |
|---|---|---|---|
| 資料形式 | 資料庫內部格式 | 檔案 | 檔案＋交易紀錄 |
| 什麼時候定 schema | 寫入前 | 讀取時 | 寫入時檢查（可設定允許 schema 演進） |
| 能不能 `UPDATE` | 能 | 不能，只能重寫檔案 | 能 |
| 換引擎 | 不行，綁定該產品 | 可以 | 可以 |
| 成本 | 依產品而定（雲端 warehouse 多半也把儲存與運算分開計費） | 儲存便宜，運算用時才開 | 同 lake |

**雲端儲存本身不等於 lake**：Azure Blob、AWS S3 是放檔案的物件儲存，是 lake 的地基；照「原始資料以開放格式檔案集中存放、各引擎來讀」的方式使用，才叫 data lake。Azure 的三個名字：

| 名字 | 是什麼 |
|---|---|
| Azure Blob Storage | 基本的物件儲存；資料夾是假的，只是檔名裡有 `/` |
| ADLS Gen2（Azure Data Lake Storage） | Blob 加上真正的資料夾（hierarchical namespace）：改資料夾名稱一步完成、可對資料夾設權限；做 lake 建議用它 |
| OneLake | Microsoft Fabric 的儲存層，建在 Azure Data Lake Storage 上、相容 ADLS Gen2 的 API；名字叫 lake，本質仍是儲存，加上 Fabric 的權限治理與多引擎共用。路徑開頭 `abfss://` 是 ADLS Gen2 的路徑寫法（ABFS driver 的 URI scheme，s＝走 TLS 加密） |

來源見文末「官方文件」。

**warehouse 常見的產品**：多半按欄存（columnar）、擅長大量加總的 OLAP 資料庫；MySQL、PostgreSQL、MongoDB 這類給應用程式日常讀寫的 OLTP 資料庫不屬於這裡。

| 類型 | 產品 |
|---|---|
| 雲端 warehouse | Snowflake、BigQuery（Google）、Redshift（AWS） |
| Microsoft | Fabric Warehouse、Azure Synapse |
| 自架／開源 | ClickHouse、StarRocks、Apache Doris |
| 傳統地端 | Teradata（傳統列存，後來加入 columnar 選項）、Vertica |
| 單機 | DuckDB：不是 warehouse 服務，而是單機的 OLAP 引擎，查法和 warehouse 一樣 |

產品清單是一般知識，未逐一查官方文件。

## Delta 是什麼
**Delta 不是要啟動的軟體，是一套表格式（table format）規格，加上照規格讀寫的函式庫。** 像 JSON：JSON 是格式，Python 用 `json` 模組、C# 用 `System.Text.Json` 讀寫，中間沒有 server；MySQL 則是要先啟動 server，所有讀寫都經過它。

| 層 | 是什麼 | 例子 |
|---|---|---|
| 規格 | 規定資料夾裡的檔案與記帳本怎麼寫 | Delta 的 `PROTOCOL.md` |
| 函式庫 | 照規格實作讀寫 | `delta-spark`（Spark 用，本專案 `pyproject.toml` 有裝）、`deltalake`（delta-rs）、DuckDB 的 delta extension（能不能寫入未證實） |
| 資料 | 儲存空間裡的檔案 | `fact/fact_order/` 資料夾 |

查詢、`MERGE` 這些運算是 Spark、DuckDB 在做，Delta 函式庫讓它們照規格讀寫檔案。同類的表格式還有 Apache Iceberg、Apache Hudi。

**Delta 表 ＝ 普通 Parquet 資料檔 ＋ Delta 定義的 metadata（`_delta_log/`）**：Parquet 管「資料長什麼樣」，Delta 管「哪些資料算數、怎麼安全地改」。`_delta_log/` 記的是：每個版本由哪些檔案組成、schema、檔案的 min／max 統計（預設只收前幾十個欄位，查詢時用來跳過不相關的檔案）、每次寫入的操作紀錄。規格除了 metadata 長相，還規定怎麼寫才安全：先寫資料檔、最後寫出下一號 log 檔才算數，所以寫到一半當機，讀的人看不到半成品；兩個程式同時寫入時，只有一個能寫出下一號 log 檔，另一個檢查有沒有衝突，沒衝突（例如單純 append）就自動重試，有衝突（例如兩個 MERGE 改到同一批資料）就丟例外，要由 pipeline 自己處理。也因此 lakehouse 的檔案不能手動刪改，log 會以為檔案還在。


### VACUUM：把沒人用的舊檔真的刪掉
**VACUUM 是 Delta 的清垃圾指令。** Delta 不改 Parquet 檔，每次更新、刪除、覆寫都是寫新檔，再在 log 記「這個版本改用新檔、舊檔標記移除」。舊檔還在磁碟上，所以 time travel 讀得到舊版本；VACUUM 把「目前版本沒在用、而且被標記移除超過保留期」的檔案實體刪掉。

```text
v0：用 a.parquet
v1：overwrite → 加入 b.parquet，標記移除 a.parquet（a 的檔案還在）
VACUUM（保留 7 天）→ a 被標記移除已超過 7 天 → 實體刪除
```

```python
# 概念等價
for f in files_on_disk:
    if f not in current_version_files and f.removed_at < now - retention:
        os.remove(f)
```

- **預設保留 7 天**（PROTOCOL.md），不會碰目前版本在用的檔。
- **log 不會被它刪**：`DESCRIBE HISTORY` 仍列得出舊版本，但資料檔沒了，`versionAsOf` 與 `RESTORE` 都會失敗（Part B `evidence.md` E10 [3] 實測）。
- **不會自動執行**：開源 Delta 要有人下指令或排程；Fabric 是否排程了表格維護要查 workspace 設定（未查證）。
- **保留期太短會被擋**：低於保留期門檻（例如 0 小時）會報 `DELTA_VACUUM_RETENTION_PERIOD_TOO_SHORT`，要關掉檢查才能跑。原因是進行中的寫入（還沒 commit 的檔）可能被刪掉而讓表損壞，正在讀舊版本的查詢也可能失敗（錯誤訊息見 E10 [3]）。
- **取捨**：保留期越長，能退回的時間越長，舊檔佔的儲存也越多。
- **跟 log 保留期是兩回事**：log 本身也會在寫 checkpoint 時清掉超過保留期（`delta.logRetentionDuration`，預設 30 天，[Delta 文件](https://docs.delta.io/latest/delta-batch.html)）的部分。

Part B 的 prod 復原第一步就是「暫停 VACUUM、調高保留期」：#6 覆寫掉的 dim 能不能用 time travel 救回，取決於舊檔還在不在（`part_b/prod-recovery.md`）。

## lakehouse 和 OLTP 的存法差異
| | OLTP（例如 MySQL） | Lakehouse（Delta） |
|---|---|---|
| 怎麼存 | 按列存，一筆資料放一起 | Parquet 按欄存，同一欄的值放一起 |
| 怎麼改 | 直接改那一列（in-place） | 檔案不改，寫新檔再在記帳本上換掉舊檔 |
| 怎麼找資料 | 索引（B-tree），直接找到某一筆 | 沒有傳統索引；靠分區（例如 `partitionBy("order_date")`）和檔案的 min／max 統計跳過不相關的檔案。Z-order、liquid clustering 是重排資料讓 min／max 更好用，不是索引 |
| 寫入節奏 | 一秒很多筆小交易 | 通常是批次大量寫入（本專案一天一批）；也支援 streaming |
| 約束 | 主鍵、唯一鍵、外鍵由資料庫擋 | 不強制主鍵、唯一鍵，重複資料照樣寫得進去；`NOT NULL`、`CHECK` 約束會擋 |
| 版本 | 只有目前狀態 | 每張表各自有版本，每次寫入前進一版；不同表之間的寫入不是同一個交易 |

最後兩列跟 Part B 直接相關：`order_id` 不會被表擋下重複，所以 #9 的 append 會默默寫出重複訂單，去重和 MERGE 要由 pipeline 自己負責；一次執行會讓 `dim_member` 和 `fact_order` 各前進一版，兩者不會一起成功或一起失敗（#11）。

## 什麼時候用、什麼時候不要用
- **Warehouse**：資料量中等、主要給 BI 報表查、團隊熟 SQL、想要少維運。
- **Lake**：原始資料先落地保存（不知道之後要怎麼用）、非結構化資料（log、圖片）。只當原料區，不直接給報表查。
- **Lakehouse**：要在 lake 上做每日增量更新（MERGE）、需要可回溯版本。
- 實務上常混用：原始檔進 lake 的 landing 區，整理後寫成 lakehouse 的表，再給 BI 查。

## 最小可跑範例
DuckDB 一支程式示範兩種存法（`uv run python demo.py`）：

```python
import duckdb

# 資料湖：資料就是一個檔案，查詢引擎直接讀檔
duckdb.sql("COPY (SELECT * FROM (VALUES ('O1', 100), ('O2', 250)) t(order_id, amount)) TO 'orders.parquet'")
print(duckdb.sql("SELECT sum(amount) AS total FROM 'orders.parquet'").fetchall())

# 資料倉儲：資料在資料庫裡，先定義 schema 才能寫
con = duckdb.connect()  # 示範用 in-memory 資料庫，重跑不會殘留
con.sql("CREATE TABLE orders (order_id VARCHAR PRIMARY KEY, amount INTEGER)")
con.sql("INSERT INTO orders SELECT * FROM 'orders.parquet'")
con.sql("UPDATE orders SET amount = 300 WHERE order_id = 'O2'")
print(con.sql("SELECT * FROM orders ORDER BY order_id").fetchall())
try:
    con.sql("INSERT INTO orders VALUES ('O3', 'abc')")
except Exception as e:
    print(type(e).__name__)
```

實際輸出（duckdb 1.5.6）：

```
[(350,)]
[('O1', 100), ('O2', 300)]
ConversionException
```

- 第一行：沒有建任何表，直接對 `orders.parquet` 這個檔案下 SQL。
- 第二行：資料庫裡的表可以 `UPDATE`。
- 第三行：schema 寫死 `amount INTEGER`，型別不對的資料寫不進去；lake 沒有人強制每個新檔都符合同一個 schema（CSV 甚至沒有型別）。這裡示範的是「寫入前定 schema vs 讀取時才定」，lakehouse 也能擋，所以這不是 lake 和 warehouse 的根本差別。

Delta 的記帳本沒有在本機實跑（需要 Spark＋Java），上面的 Python 只是示意。

## 常見的坑
- **把 lake 當成 warehouse 用**：CSV 不定 schema，所有欄位都是字串，金額比大小靠隱式轉型（Part B #1）。
- **以為 lakehouse 的舊版本永遠都在**：VACUUM 會真正刪掉作廢超過保留期的舊檔，刪了就不能 time travel；就算沒跑 VACUUM，記帳本本身超過保留期被清掉，舊版本也一樣回不去（Part B #6 的 dim 被覆寫，只在保留期內、VACUUM 之前救得回來）。VACUUM 的預設保留期是 7 天（PROTOCOL.md）；log 的預設保留期是 30 天（`delta.logRetentionDuration`，[Delta 文件](https://docs.delta.io/latest/delta-batch.html)）。
- **lake 裡的原始檔被覆蓋或刪掉**：之後表寫壞了就沒有原料可以重做。

## 本專案出處
- `buggy_pipeline.py` 的 `LAKEHOUSE = "abfss://` 開頭的路徑：指向 Microsoft Fabric（OneLake）的 lakehouse。
- `load_sources()` 從 `landing/` 讀 CSV（lake 的原料區）；`update_dim_member()`、`write_fact()` 寫 `format("delta")`（lakehouse 的表）。
- 題目 Part C 考 Lakehouse vs Warehouse 的架構取捨。

## 官方文件
lake／warehouse／lakehouse 的分類是一般定義，未讀官方文件，可對照 Reis & Housley《Fundamentals of Data Engineering》的 storage 章節。

Delta（驗收 agent 查證過）：
- transaction log 的 action（add、remove、metaData、cdc 等）：https://github.com/delta-io/delta/blob/master/PROTOCOL.md
- deletion vectors：https://docs.delta.io/latest/delta-deletion-vectors.html
- 約束只支援 `NOT NULL`、`CHECK`（沒有主鍵、唯一鍵）：https://docs.delta.io/latest/delta-constraints.html
- 並行寫入的衝突與例外：https://docs.delta.io/latest/concurrency-control.html
- min／max 統計、Z-order、liquid clustering：https://docs.delta.io/latest/optimizations-oss.html
- 兩階段寫入（先寫資料檔、再寫 log）與 VACUUM 預設 7 天：同上 PROTOCOL.md

Azure 儲存（驗收 agent 查證過）：
- Blob 的虛擬資料夾與 hierarchical namespace（原子目錄操作）：https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-namespace
- ADLS Gen2 的 ACL：https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-access-control
- OneLake 建在 Azure Data Lake Storage 上：https://learn.microsoft.com/en-us/fabric/onelake/onelake-overview
- `abfss://`（ABFS driver）：https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-abfs-driver
