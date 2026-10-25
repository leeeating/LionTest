# pipeline｜Part A 管線程式

Part A 的管線程式碼。本檔說明各模組負責什麼、對外提供哪些函式，以及寫新的表時要注意的事。設計理由見上一層的 `part_a/README.md`。

涵蓋 T3（共用設定、來源讀取、dim_product、dim_date）、T4（dim_member）、T5（fact_order 初始載入、隔離表、對帳）、T6（狀態機、增量處理、批次紀錄、命令列入口）。

## 目錄

- [1. 模組一覽](#1-模組一覽)
- [2. 用法](#2-用法)
- [3. 各模組](#3-各模組)
  - [3.1 session.py](#31-sessionpy)
  - [3.2 contracts.py](#32-contractspy)
  - [3.3 sources.py](#33-sourcespy)
  - [3.4 validation.py](#34-validationpy)
  - [3.5 delta_io.py](#35-delta_iopy)
  - [3.6 dims.py](#36-dimspy)
  - [3.7 dim_member.py](#37-dim_memberpy)
  - [3.8 order_status.py](#38-order_statuspy)
  - [3.9 order_status_check.py](#39-order_status_checkpy)
  - [3.10 categories.py](#310-categoriespy)
  - [3.11 batch_log.py](#311-batch_logpy)
  - [3.12 fact_order.py](#312-fact_orderpy)
  - [3.13 run.py](#313-runpy)
- [4. 測試](#4-測試)

## 1. 模組一覽
| 模組 | 負責 | 主要對外介面 |
|---|---|---|
| `session.py` | 建立 SparkSession | `build_spark()`、`SESSION_TIMEZONE` |
| `contracts.py` | 各來源的 schema 合約（唯一一份） | `ORDERS_SCHEMA`、`MEMBERS_SCHEMA`、`PRODUCTS_SCHEMA`、`FX_RATES_SCHEMA`、`to_raw_schema()`、`ORDER_CURRENCIES`、`ALLOWED_VALUES_KEY` |
| `sources.py` | 讀取來源、檔案層級檢查、來源指紋 | `SourceReader`（介面）、`CsvSource`（CSV 實作）、`SourceFileError`、`file_sha256()` |
| `validation.py` | 轉成合約型別、分出違規列 | `cast_to_contract()`、`strict_date()`、`REJECT_REASONS_COL` |
| `delta_io.py` | 寫入 Delta 表、CHECK 約束 | `merge_upsert()`、`ensure_check_constraints()`、`table_check_constraints()` |
| `timeparse.py` | 來源時間字串的格式定義與解析（validation 與 dims 共用） | `SOURCE_TIMESTAMP_FORMATS`、`parse_source_timestamp()` |
| `dim_member.py` | 會員維度（SCD Type 2）、會員隔離表 | `write_dim_member()`、`build_dim_member()`、`write_member_quarantine()`、`resolve_member_sk()`、`member_missing_reason()` |
| `dims.py` | 維度表 | `write_dim_product()`、`write_dim_date()`、`all_orders()`、`resolve_product_sk()`、`date_sk()` |
| `order_status.py` | 訂單狀態機的 domain 定義：狀態值、合法一步轉移、可達性 | `STATUSES`、`TRANSITIONS`、`REACHABLE`、`reachable()`、`skips_intermediate()` |
| `order_status_check.py` | 一批事件的狀態機分類（純 DataFrame 轉換） | `classify_status_events()`、`split_by_disposition()`、`StateCategory` |
| `categories.py` | 隔離表分類（`reject_category`）的唯一一份定義 | `Category`、`SKIP_CATEGORIES`、`QUARANTINE_CATEGORIES` |
| `batch_log.py` | 批次紀錄：依序執行、已完成就跳過、訂單來源被改過就報錯、參考資料變了只警告、force 留紀錄；記下每批開始前的 fact 版本 | `run_once()`、`pin_fact_version()`、`record_forced()`、`forced_runs()`、`BatchCounts`、`BatchRecord`、`BATCH_ORDER`、`BatchOrderError`、`SourceChangedError` |
| `fact_order.py` | 一批訂單的處理入口：維度更新、fact_order、隔離表、對帳；依序跑完全部批次 | `transform_order_batch()`、`load_order_batch()`、`load_base()`、`load_incremental()`、`run_batch()`、`run_all()`、`WarehousePaths`、`BatchReconciliation`、`find_batch_collisions()`、`find_existing_collisions()`、`ReferenceDataError` |
| `run.py` | 命令列入口（`python -m pipeline.run`） | `main()` |

模組間的 import：`contracts` 用 `timeparse`、`order_status`；`sources` 用 `contracts`；`validation` 用 `contracts`、`timeparse`；`dims` 用 `contracts`、`sources`、`delta_io`、`timeparse`；`dim_member` 用 `contracts`、`validation`、`delta_io`；`order_status_check` 用 `order_status`、`categories`；`fact_order` 用 `batch_log`、`categories`、`contracts`、`validation`、`delta_io`、`timeparse`、`dims`、`dim_member`、`order_status`、`order_status_check`、`sources`；`run` 用 `fact_order`、`batch_log`、`session`、`sources`。`session`、`delta_io`、`timeparse`、`order_status`、`categories`、`batch_log` 不依賴其他模組。

## 2. 用法
```python
from pipeline.contracts import ORDERS_SCHEMA, PRODUCTS_SCHEMA
from pipeline.dims import all_orders, write_dim_date, write_dim_product
from pipeline.session import build_spark
from pipeline.sources import CsvSource
from pipeline.validation import cast_to_contract

spark = build_spark()
source = CsvSource(
    spark
)  # 預設讀 candidate_package/dataset；檔案層級問題在呼叫讀取方法（例如 source.products()）時才報錯

# 先轉成合約型別；rejected 是違規列（訂單的隔離表由 fact_order 寫入）
products, rejected_products = cast_to_contract(source.products(), PRODUCTS_SCHEMA)
write_dim_product(spark, products, "/tmp/liontest/dim_product")

# dim_date 由呼叫端決定要看哪些訂單；逐日處理時一批一批 MERGE
base, _ = cast_to_contract(all_orders(source, days=()), ORDERS_SCHEMA)  # days 必填
write_dim_date(spark, base, "/tmp/liontest/dim_date")  # 只有 base
day1, _ = cast_to_contract(source.orders_incremental(1), ORDERS_SCHEMA)
write_dim_date(spark, day1, "/tmp/liontest/dim_date")  # 補上 day1 的新日期

# 一般用法：run_all 依序跑 base → day1 → day2 → day3，每批用批次紀錄包住
from pipeline.fact_order import WarehousePaths, run_all

for run in run_all(spark, source, WarehousePaths("/tmp/liontest/wh")):
    assert run.record.counts.balanced  # 輸入＝寫入＋隔離＋略過
```
命令列（印出每批對帳）：在 `part_a/` 底下執行 `uv run python -m pipeline.run --out /tmp/liontest/wh`；資料目錄用 `--data-dir` 或環境變數 `LIONTEST_DATA_DIR`，輸出目錄也可以用 `LIONTEST_OUT`。`--force` 會強制重跑已完成的批次。
輸出路徑由呼叫端決定，模組內不寫死。

## 3. 各模組

### 3.1 session.py
`build_spark()` 啟用 Delta，並固定以下設定：

| 設定 | 值 | 原因 |
|---|---|---|
| `spark.sql.session.timeZone` | `Asia/Taipei` | 下單日、匯率日都依賴時區，不固定的話，不同機器可能算出不同的日期 |
| `spark.sql.shuffle.partitions` | 4 | 本機資料量小，用預設的 200 會產生大量空分區 |
| `spark.sql.csv.parser.columnPruning.enabled` | `false` | 開著時，`count()` 這類只需要部分欄位的查詢不會檢查每列的欄位數，`_source_error` 不會被填值，欄位數不符的列（少欄、多欄、結尾多逗號、引號內換行、引號不成對）會被算成 valid，筆數守恆就失真。實測關掉後 `count()` 和 `collect()` 結果一致 |
| `spark.driver.memory` | `2g` | local 模式的 driver 也負責計算；預設 1g 時，全套測試在同一個 session 連跑多次十萬列的完整流程會 `Java heap space`（2026-10-19 實測） |
| `spark.driver.host`、`spark.driver.bindAddress` | `localhost`、`127.0.0.1` | 不設時 driver 用區網 IP 宣告位址；task 結果較大（例如 collect 十萬列）時要透過這個位址傳回，斷網或換網路時 IP 消失就失敗（T6 驗收推測的 flaky 原因，未重現斷網）。Docker 用 `--network none` 時要加 `--hostname localhost` 也是同一件事 |

### 3.2 contracts.py
每個來源的欄名、型別、是否必填都寫成 `StructType` 常數，是全專案唯一一份合約；讀取用的全字串 schema 由 `to_raw_schema()` 從合約自動產生，不另外手寫。

- **必填欄位用 `nullable=False` 標示**：空值時這一列無法被正確處理或歸屬的欄位才設為必填（例如 orders 的 order_id、member_id、product_id、amount、updated_at；members 的 register_date、extract_date；fx_rates 全部）。理由寫在各欄旁邊。目前資料中沒有任何空值，必填清單是依語意決定。

- **金額用 `DecimalType(18, 2)`，匯率用 `DecimalType(18, 6)`**：對帳和 checksum 需要精確的值，用 double 會有浮點誤差。
- **格式不一致的欄位讀成字串**：例如 `order_created_at` 混用三種時間格式，先保留原樣，再用 `parse_source_timestamp()` 解析。
- **允許值放在欄位 metadata（`ALLOWED_VALUES_KEY`）**：`order_status` 只能是 created、paid、cancelled、completed，清單直接引用 `order_status.STATUSES`（和狀態機同一份）；`currency` 只能是 `ORDER_CURRENCIES`＝TWD、NTD、USD、JPY（2026-10-18 以 duckdb 查四個訂單檔：base 四種都有，三天增量只有 TWD、USD、JPY）。NTD 是 base 裡 TWD 的別名（V4，200 列），保留並以匯率 1 換算。比對是完全比對，大小寫、前後空白不同都算違規。新幣別要先確認匯率表有提供再加進來；沒加之前整列以合約違規隔離，不會變成「找不到匯率」。〔防護性設計：本資料 0 筆〕
- **金額必須大於 0 放在欄位 metadata（`POSITIVE_KEY`）**：`amount` 不大於 0 的列以「amount:必須大於 0」進 rejected（V1，使用者定：「負數在合約層就該擋下」；base 50 列）。`coupon_discount` 沒有這個標記：-1.0 是清理規則（轉 NULL），不是合約違規。
- **coupon 不可為 -1 以外的負數，放在欄位 metadata（`NON_NEGATIVE_EXCEPT_KEY`）**：`coupon_discount` 小於 0 且不是 `COUPON_UNKNOWN`（-1.00）的列，以「coupon_discount:必須大於或等於 0（-1.00 除外）」進 rejected（使用者定 B：「負數 coupon 沒有合理解釋」）。-1 以 Decimal 比較，`-1`、`-1.0`、`-1.00` 都放行。〔防護性設計：本資料 0 筆〕

### 3.3 sources.py
`SourceReader` 是來源介面，每個來源表對應一個方法：`orders_base()`、`orders_incremental(day)`、`members()`、`products()`、`fx_rates()`。現在只有 CSV 實作 `CsvSource`；之後換成從 SQL DB 讀，只要新增一個實作同一組方法的類別（ADR-02）。

另有 `orders_checksum(day)`：一批訂單來源的指紋（`day=None` 是 base），批次紀錄用它偵測已完成的批次來源被改過。`reference_checksums()`：參考資料（`members`、`products`、`fx_rates`，檔名見 `REFERENCE_FILES`）各自的指紋，批次紀錄記下、重跑時不同只警告。`CsvSource` 都用檔案的 sha256（`file_sha256()`）實作，並公開 `dataset_dir` 與 `orders_path(day)`。

讀取方法回傳的 DataFrame 中，合約欄位**全部是原始字串**，另外多一欄 `_source_error`。讀取層不轉型，所以型別錯的值不會在讀取時被轉成 NULL 或被四捨五入。

違規分兩層處理（已定案）：

| 層級 | 情況 | 處理 |
|---|---|---|
| 檔案 | 檔案不存在、表頭欄名或順序與合約不符、沒有資料列 | 呼叫讀取方法時立即丟 `SourceFileError`（`kind` 為 `missing`／`header`／`empty`），整批停下，不寫入任何東西 |
| 列 | 欄位數與表頭不符 | 該列原文放在 `_source_error`，由 `cast_to_contract()` 分到 rejected |

**注意：** 不要只查 `_source_error` 一欄（例如 `raw.filter("_source_error IS NOT NULL").count()`）。Spark 不允許只引用 corrupt record 欄位的 CSV 查詢，會丟 `UNSUPPORTED_FEATURE.QUERY_ONLY_CORRUPT_RECORD_COLUMN`。統計格式錯誤的列，請從 `cast_to_contract()` 的 rejected 計算（例如篩 `reject_reasons` 含「列格式錯誤」的列）。

檔案層級的檢查用 `spark.read.text(...).take()` 立即讀出檔案開頭來比對。列層級的欄位數檢查依賴 `build_spark()` 關掉 CSV column pruning（見 session.py 一節）；自己建 SparkSession 時要記得加這個設定，否則 `count()` 會把壞列算成 valid。

### 3.4 validation.py
`cast_to_contract(df, schema, *, passthrough=())` 回傳 `(valid_df, rejected_df)`，是唯一的轉型入口，fact_order 的隔離表也用它。

- **valid_df**：沒有違規的列，欄名、欄序、型別與合約相同。
- **rejected_df**：有違規的列，保留所有原始字串欄位（含 `_source_error`），加上 `reject_reasons`（字串陣列，一列有多個原因時全部列出，格式「欄名:原因」）。
- **筆數守恆**：兩者用同一個條件切開，valid 筆數＋rejected 筆數＝輸入筆數，之後對帳「輸入＝寫入＋隔離」靠這一點。
- **每列的錯誤只算一次**：先算出每列的 `reject_reasons`，做一次 `localCheckpoint(eager=False)`（第一個用到的 action 才計算並存起來），valid 與 rejected 都從存好的結果依陣列是否為空切開。不這樣做時兩者是兩條獨立的查詢，每個 action 都從輸入重跑全部 regex／try_cast 檢查。函式本身不呼叫 action、不計算檢查結果；但建立 checkpoint 時要先產生輸入的 RDD，輸入的查詢含 shuffle（join、groupBy 等）時，AQE 會在這時先執行 shuffle 階段的 job（管線傳進來的是剛讀的 CSV，沒有 shuffle）。存起來的資料在 valid、rejected 不再被引用後由 Spark 的 ContextCleaner 回收，沒有另外的釋放介面。
- **`passthrough`**（關鍵字參數，預設空）：指定的欄位原樣附在 valid 的合約欄位之後。fact_order 用它把整列原始字串（`_raw`）帶到後面的步驟，之後任何一步隔離時都能寫回上游送來的原值，而不是轉型後的值（例如 `122549.0` 轉 Decimal 再轉回字串會變成 `122549.00`）。

`strict_date(col)`：原始字串依合約的日期規則（`yyyy-MM-dd` 且日期存在）轉成 DateType，不符合時為 NULL。cast_to_contract 判斷日期欄位用的就是它；合約以外需要先看日期的地方（例如 dim_member 依 extract_date 過濾）也用它，不要用 try_cast，因為 try_cast 會把 `"2026-07-15 junk"` 當成 07-15。

列層級違規（判斷只看原始字串，不看 Spark 轉型後的值）：

| 違規 | 原因字串範例 |
|---|---|
| 欄位數與表頭不符 | `列格式錯誤:欄位數與表頭不符` |
| 必填欄位空值（含空字串、只有空白字元） | `member_id:必填空值` |
| 型別不符：整數只接受 `[+-]數字`；Decimal 只接受一般十進位寫法，不接受科學記號（`1e2`）、千分位、空白；日期只接受 `yyyy-MM-dd` 且日期要存在 | `quantity:型別不符（應為 int）` |
| Decimal 小數位超過合約 scale | `amount:小數位超過 2 位` |
| Decimal 整數位超過 precision − scale | `amount:整數位超過 16 位` |
| 時間字串無法解析：合約 metadata 標記 `source_timestamp` 的欄位（`order_created_at`、`updated_at`），必須能被 `parse_source_timestamp()` 解析 | `order_created_at:時間格式無法解析（應為 …）` |
| 值不在允許範圍：合約 metadata 標記 `allowed_values` 的欄位（`order_status`、`currency`） | `currency:值不在允許範圍（TWD、NTD、USD、JPY）` |
| 數值不大於 0：合約 metadata 標記 `positive` 的欄位（`amount`）；格式已經錯的值只記型別不符 | `amount:必須大於 0` |
| 數值小於 0 且不是例外值：合約 metadata 標記 `non_negative_except` 的欄位（`coupon_discount`，例外值 -1.00）；格式已經錯的值只記型別不符〔防護性設計：本資料 0 筆〕 | `coupon_discount:必須大於或等於 0（-1.00 除外）` |

時間格式規則和 `parse_source_timestamp()` 共用 `timeparse.SOURCE_TIMESTAMP_FORMATS` 這一份定義，所以進得了 valid 的列，下單時間一定解析得出來，dim_date 的範圍和 fact 的 date_sk 不會因為 NULL 而悄悄漏掉。`updated_at` 目前資料全是 `+08:00` 格式，比照辦理是因為增量判斷新舊靠它，解析不了就無法比較。

不靠 Spark 的 `try_cast` 判斷，因為它很寬鬆，實測：`100.456` 轉 `DECIMAL(18,2)` 得到 `100.46`、`1e2` 得到 `100.00`、`' 3'` 轉 INT 得到 `3`、`2026-06-25T14:02:16+08:00` 轉 DATE 得到 `2026-06-25`，全部不報錯。

### 3.5 delta_io.py
`merge_upsert(spark, df, path, keys, *, update_condition=None, commit_marker=None, check_constraints=None)`：依 `keys` 把 `df` MERGE 進 `path` 的 Delta 表。比對到的列整列覆寫，沒比對到的新增；表不存在時直接建立。同一份輸入重跑，結果不變。
- `update_condition`：比對到時只有條件成立才覆寫（目標表別名 `t`、來源 `s`）。fact_order 用 `s.updated_at > t.updated_at`，舊事件不會蓋掉新狀態。
- `commit_marker`：寫進這次 commit 的 `userMetadata`（Delta history 查得到），fact_order 用它標出哪一批寫了哪個版本，只作稽核。注意：來源是空的 MERGE 不會產生 commit，也就沒有標記，所以不能拿標記來找「某批之前的版本」（見 batch_log.py 的 `pin_fact_version`）。
- `check_constraints`：Delta CHECK 約束（名稱 → 條件式）。表不存在時先用 `df` 的 schema 建一張空表、加上約束，再 MERGE，所以第一筆資料就受檢查；表已存在時補上缺的約束。違反約束時整個 MERGE 失敗，什麼都不寫。fact_order 傳 `FACT_CHECK_CONSTRAINTS`（見 fact_order.py 一節）。

`ensure_check_constraints(spark, path, constraints)`：讓表帶有這些約束。缺的用 `ALTER TABLE ... ADD CONSTRAINT` 加；已存在且條件相同就不動，所以重跑冪等（同名約束 ADD 第二次會報錯）。同名但條件不同（程式改了規則）時先 DROP 再 ADD，以程式為準；DROP 之前先查既有資料符不符合新條件（NULL 也算不符合），有不符合的列就丟 `ValueError`、不 DROP，避免「DROP 成功、ADD 因既有資料違規失敗」讓表暫時沒有約束。檢查和 DROP、ADD 不在同一個交易裡，檢查之後才寫入的資料仍可能讓 ADD 失敗。不在清單裡的約束不動。條件是否相同用 `same_constraint_expr()` 去掉空白再比，因為 Delta 存的是重新排版過的文字（`x IN ('a', 'b')` 存成 `x IN ( 'a' , 'b' )`，2026-10-24 實測）。`table_check_constraints(spark, path)` 讀出表目前的約束（表屬性 `delta.constraints.<名稱>`）。

**注意：重跑時既有列仍會被重寫，只是值相同。** Delta history 的 operationMetrics 會顯示 `numTargetRowsUpdated` 等於筆數，這只代表列被重寫，不代表內容改變；要判斷內容是否改變，請比對表內容或 checksum。

**注意：呼叫前，`df` 的 `keys` 必須唯一。** 來源同一個 key 有多列，而目標表還沒有這個 key 時，Delta 會把多列全部插入，不會報錯（Part B 的 E12）。

### 3.6 dims.py
**dim_product**
- `write_dim_product(spark, products, path)`：`products` 是 `cast_to_contract(source.products(), PRODUCTS_SCHEMA)` 的 valid_df。建表並以 `product_id` MERGE。主檔的每個產品一列，另外加一列「未知產品」（`UNKNOWN_PRODUCT_ID = "UNKNOWN"`、`UNKNOWN_PRODUCT_SK = -1`）。
- 主檔的 `product_id` 重複時丟 `DuplicateKeyError`，整批停下：主檔沒有更新時間之類的欄位可以判斷哪一列較新，任選一列會讓結果隨讀取順序改變。經由 `fact_order.load_order_batch()` 呼叫時，會轉成 `ReferenceDataError`（見 fact_order.py 一節）。
- `product_sk()`：用 `xxhash64(product_id)` 算代理鍵，不受輸入順序影響，重跑結果相同。
- `resolve_product_sk(fact_df, dim_df)`：**事實表要取 product_sk 時用這個函式，不要直接呼叫 `product_sk()`。** 它會用 product_id 去 join dim_product；對不到主檔的 product_id 和 NULL 都會落到 -1。直接 hash 會產生在 dim_product 裡找不到的 sk，而且 `xxhash64(NULL)` 的結果是 42，不是 NULL。

**dim_date**
- `write_dim_date(spark, orders, path)`：以呼叫端傳入的訂單 DataFrame（已依 `ORDERS_SCHEMA` 轉型的 valid_df） 擴充日期維度，並以 `date_sk`（yyyymmdd 整數）MERGE。範圍取「既有表的範圍」和「這批訂單的下單日、出發日範圍」的聯集，所以只傳某一天的增量時，既有日期不會被刪，新舊範圍之間也不會留下缺日；既有日期列重算的值相同，內容不變。
- `build_dim_date(orders)`：只計算、不寫入，回傳傳入訂單涵蓋的連續日期。
- `all_orders(source, days)`：orders_base 加上指定天數的增量（原始字串，尚未轉型）。`days` 沒有預設值，必須明確傳入，避免逐日處理時漏傳而看到之後的資料；全部三天傳 `INCREMENTAL_DAYS`，只處理 base 傳 `days=()`。
- `date_sk(col)`：日期轉 yyyymmdd 整數。dim_date 和之後的 fact 都用這個函式，確保兩邊算法一致。

**時間解析**
- `timeparse.parse_source_timestamp(col)`：把三種格式的時間字串（`order_created_at`、`updated_at`）解析成 timestamp；無法解析的值得到 NULL。通過 `cast_to_contract()` 的列不會有這種值。

| 格式 | 解讀 |
|---|---|
| `+08:00` | 照標記 |
| 結尾 `Z` | UTC，換算成台北時間 |
| `YYYY/MM/DD HH:MM:SS` | 沒有時區標記，視為台北時間（已定案，見 process-log） |

### 3.7 dim_member.py
**規則**（已定案，見 process-log「dim_member SCD2 規則」）
- 依 extract_date 由舊到新處理。會員沒出現在某一批就沿用前一版；內容沒變不開新版。
- `member_level`、`city` 是 Type 2，值變就開新版；`member_name`、`birth_date` 是 Type 1，覆寫該會員所有版本。
- 同一會員、同一 extract_date 有多列（V8）時取較高等級：一般 < 銀卡 < 金卡 < 白金。等級不在這四個值內（含 NULL）的列進 rejected，不猜排序；`register_date` 晚於 `extract_date` 的列也進 rejected。
- `city = 'N/A'`、`birth_date = 1900-01-01` 轉成 NULL，而且不蓋掉已知的真實值：city 從真實值變 N/A 不算變動。city 從 NULL 變成真實值**算變動、開新版本**，不回填舊版本（回填等於斷言「他以前也住這裡」）。
- 版本區間：第一版 `valid_from = register_date`；之後各版是觀察到變動那一批的 extract_date。`valid_to` 不含當天（等於下一版的 `valid_from`），目前版本是 `9999-12-31`，另有 `is_current`。
- 代理鍵 `member_sk = xxhash64(member_id, valid_from)`，重跑、換輸入順序都不變。
- **沒有「未知會員」列**（和 dim_product 的 -1 不同）：訂單對不到會員版本時整列進訂單隔離表（`member_missing`），fact 永遠不會指向未知會員，保留這一列只會讓人以為 fact 裡有未知會員的訂單（使用者定：「在訂單重要度之後是會員資料 如果有未知會員資料在做客戶分析是一件困難的事 所以要有錯誤提醒修正data pipline」）。用舊版程式建好的 dim_member 還留著 -1 那列（MERGE 不刪列），要重建倉儲。

**對外函式**
- `write_dim_member(spark, members, path, *, through, quarantine_path=None)`：`members` 是 `source.members()` 的**原始字串** DataFrame（轉型在函式內做）。只處理 `extract_date <= through` 的快照，以 `member_sk` MERGE；`quarantine_path` 有給時，違規列寫進會員隔離表（fact_order 一律給）。回傳 `DimMemberWrite`：
  - `table`：寫入後讀回的**整張表**，可以直接給 `resolve_member_sk`。
  - `rejected`：違規列，形狀同 `cast_to_contract` 的 rejected（原始字串＋`reject_reasons`），筆數也記在對帳的 `member_rejected_rows`。本題資料 0 列。
  - `stats`：`input_rows`（through 以內的列數，等於 valid＋rejected）、`rows_after_through`、`rejected_rows`、`same_day_conflicts`、`city_placeholder_rows`、`birth_placeholder_rows`、`stale_rows_skipped` 等。
- `through` 是必填的關鍵字參數，比照 `all_orders` 的 `days`：逐日處理時忘了過濾，就會偷看到之後的快照。extract_date 不符合合約日期規則的列（例如 `2026/04/30`、`2026-07-15 junk`）不會被這個過濾吃掉，會在本批進 rejected；過濾用 `strict_date()` 判斷，不用 try_cast。
- `build_dim_member(spark, members, *, through, existing=None)`：只計算、不寫入。回傳的 `changes` 只有「這批受影響的會員的所有版本」，**不能拿去 resolve**（從頭建時才等於整張表）。
- **壞列不蓋掉上一個好版本**：違規列不參與建版本，該會員沿用前一版；之後的好快照照常開新版（有測試）。會員第一次出現就是壞列時，他不會有任何版本，他的訂單在 fact_order 進訂單隔離表（`member_missing`，有測試證明這個連鎖）。〔防護性設計：本資料 0 筆〕

**會員隔離表 `quarantine_member`**（使用者定 B：另開會員隔離表，和訂單隔離表分開，「根據DE的慣例」）〔防護性設計：本資料 0 筆〕
- 欄位（`MEMBER_QUARANTINE_COLUMNS`）：members 的 7 個欄位（**原始字串**）、`_source_error`、`reject_reasons`（ARRAY<STRING>）。
- 識別用原始的 `extract_date`（快照日），不加 `batch_id`：members.csv 是累積的整份快照，每一批都會重讀到同樣的壞列。用 batch_id 分區，同一列會在每批各出現一次；加一欄「最後寫入的批次」，強制重跑舊批次時內容就會改變，不冪等。
- 寫入（`write_member_quarantine`）：這次處理的快照（`extract_date <= through`，含解析不了的）出現過哪些 `extract_date` 原值，就以 `replaceWhere extract_date IN (...)` 先清掉這些快照的舊隔離列再寫入（`extract_date` 是 NULL 的壞列另加 `OR extract_date IS NULL`）。所以同一份快照不論被哪一批重讀幾次都只留一份；上游在同一個 extract_date 內修好壞列後重跑，舊的隔離列也會被清掉。限制：上游修的是 extract_date 本身、或整份快照從 members.csv 消失時，舊值不會再被讀到，它的隔離列會留在表裡（見 `part_a/README.md`「已知限制」）。through 之後的快照不在範圍內，強制重跑較早的批次不會刪掉較晚快照的隔離列。

**`resolve_member_sk(fact_df, dim_df, date_col)`**
- 依 `member_id` 與下單日對到當時有效的版本：`valid_from <= 下單日 < valid_to`。版本區間不重疊，所以每張單最多對到一版，fact 列數不變。
- 對不到的（member_id 不存在或為 NULL、下單日早於第一版的 valid_from）`member_sk` 為 NULL，不落 -1；fact_order 把這些列分到訂單隔離表（`member_missing`）。〔防護性設計：本資料 0 筆〕
- **`dim_df` 必須是整張 dim_member**（`write_dim_member` 回傳的 `table`，或直接讀 Delta）。只給部分會員時，其他會員的訂單會對不到而被隔離，看起來像上游的問題。

`member_missing_reason(unresolved, dim_df, date_col)`：替對不到版本的列加上原因欄 `_member_reason`，分兩種，讓看隔離表的人知道該查快照還是查下單時間：「member_id:會員 X 不在 dim_member（會員快照沒有這位會員，或他的快照列都違規）」、「member_id:下單日 D 早於會員 X 第一個版本的 valid_from V」。〔防護性設計：本資料 0 筆〕
- `date_col` 必須是 DateType 的台北下單日，先用 `F.to_date(parse_source_timestamp(F.col("order_created_at")))` 算出來（session timezone 是 Asia/Taipei）。

**逐批處理**
```python
for day in [date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30)]:
    res = write_dim_member(spark, source.members(), path, through=day)
```
每次都可以傳整份 members.csv，函式只會處理 through 以內、而且還沒處理過的快照。一批一批餵、一次餵到某一天，結果相同（有測試）。

**`last_seen_extract_date` 的作用與副作用**
- 每位會員記錄「已處理到哪一批快照」。快照列的 `extract_date` 小於或等於這個值時直接跳過，所以重跑不會多開版本，重送舊檔也不會把會員「改回去」。
- 副作用：判斷是**以會員為單位**。某一批遲到（例如 04-30、06-30 處理完才送來 05-31），這批只會套用到「06-30 沒出現」的會員，這些會員的結果和依序處理相同；06-30 有出現的會員，05-31 那一列會被跳過，中間那段歷史就遺失了（例如 05-31 升金卡、06-30 又降回一般，表裡看不到金卡那一版）。要避免，得在批次層級確保依序處理（T6 的批次紀錄）。

### 3.8 order_status.py
訂單狀態機的 domain 定義，回傳 Spark 運算式，不用 Python UDF。

- `STATUSES`：created、paid、cancelled、completed。也是合約中 `order_status` 允許值的唯一來源。
- `TRANSITIONS`：合法的一步轉移，是唯一一份規則：created→paid、created→cancelled、paid→cancelled、paid→completed（假設流程單向：取消後不能恢復、completed 之後不能取消，見 `notes/part_a/order-state-machine.md`）。
- `REACHABLE`：由 `TRANSITIONS` 推導的自反遞移閉包（走 0 步以上能到），不另外手寫。自我轉移 X→X 算可達，也就是 no-op：同狀態重送不算不合法。
- `SKIPS`：可達、但不是一步轉移也不是自我轉移，也就是跳過中間狀態。依目前規則只有 created→completed。
- `reachable(from_col, to_col)`、`skips_intermediate(from_col, to_col)`、`is_known_status(col)`：遇到未知值或 NULL 一律回傳 False，不回傳 NULL。

### 3.9 order_status_check.py
`classify_status_events(events, fact_state, *, tiebreak=None)`：替一批事件的每一列加上 `state_category`、`state_reason`、`state_skipped`。輸入是經過格式、撞號、去重處理的事件，以及既有 fact 的 `(order_id, order_status, updated_at)`；第一批沒有 fact 時傳 None。規則已定案，見 process-log「狀態機檢查採 C」「狀態檢查一律用可達性」「同一秒內出現不同狀態」「不合法轉移之後的事件一起隔離」：

| 情況 | 分類 | 去向 |
|---|---|---|
| `updated_at` ≤ fact 的 `updated_at`（晚到事件），舊狀態走得到 fact 現況 | `late_event` | 略過：不寫 fact，隔離表留紀錄 |
| 晚到事件，舊狀態走不到 fact 現況 | `late_event_conflict` | 隔離 |
| 比 fact 新的事件，依 `updated_at` 排序，同狀態的連續列合併成一段，逐段用**可達性**比（第一段的起點是 fact 現況；新訂單不限） | 合法時，最後一列為 `accepted`（寫進 fact），其餘為 `superseded` | 寫入／隔離 |
| 往回走（例如 cancelled→paid） | `illegal_transition` | 隔離 |
| 同一 order_id、同一 `updated_at`、狀態不同 | `ambiguous_order`（全部列） | 隔離 |
| 鏈上第一個不合法或同一秒衝突之後的事件 | `after_illegal` | 隔離；fact 停在最後一個合法狀態 |

- 逐段比用可達性，不用一步轉移表：無法確定上游送的是事件還是快照，快照之間的中間狀態可能沒拍到。跳過中間狀態（created→completed）算合法，`state_skipped` 標 True，只計數、不隔離。新訂單的第一個狀態沒有前一個觀察，不標記。
- 同一秒衝突之前的合法事件照常寫入，衝突的列和之後的列隔離。
- `tiebreak`：`updated_at` 相同、狀態也相同時，決定哪一列算最後一列，只是為了讓重跑結果確定。fact_order 傳原始字串 `_raw`。
- 未知狀態值已在合約擋下。萬一繞過合約，未知值走不到也走不出任何狀態，在鏈上會歸 `illegal_transition`，晚到時歸 `late_event_conflict`，不會寫進 fact。
- `split_by_disposition(classified)`：依去向拆成 accepted／quarantined／skipped 三份。

### 3.10 categories.py
隔離表 `reject_category` 的唯一一份定義（`Category`），fact_order 與狀態機共用。`SKIP_CATEGORIES`＝{`late_event`}：存在隔離表、但不是錯誤，對帳時和隔離分開計數（使用者定：狀況外的事件統一留紀錄）。其餘都在 `QUARANTINE_CATEGORIES`。

### 3.11 batch_log.py
一張 Delta 表（`WarehousePaths.batch_log`），每批完成時**最後**寫一列，欄位和 `BATCH_LOG_SCHEMA` 一致：
- `batch_id`、`as_of`、`completed_at`（UTC）
- `source_sha256`：這批訂單檔的 checksum
- `reference_sha256`（MAP<STRING,STRING>）：參考資料 `members`、`products`、`fx_rates` 各自的 checksum（使用者定 C）
- `BatchCounts` 的所有對帳數字：`input_rows`、`fact_rows`、`skipped_rows`、`quarantined_rows`、`quarantined_by_category`、`skipped_intermediate_rows`、`coupon_nulled_rows`、`amount_review_rows`、`amount_twd_sum`、`net_amount_twd_sum`、`unknown_product_rows`、`unknown_member_rows`、`fact_table_rows`、`fact_table_amount_twd_sum`、`fact_table_net_amount_twd_sum`、`member_rejected_rows`（各欄意義見 fact_order.py 一節的 `BatchReconciliation`）

`run_once(spark, log_path, *, batch_id, as_of, source_checksum, run, reference_checksums=None, force_log_path=None, force=False)`：
1. 已完成、訂單檔 checksum 相同 → 不執行，回傳既有紀錄（`BatchRun.skipped=True`）。參考資料 checksum 和紀錄不同時只發警告（`logging` 的 WARNING，列出哪個檔從哪個 checksum 變成哪個），照常跳過（使用者定 C）。參考資料是整份快照、每批都讀同一份檔，之後的批次本來就會讀到新版本；只有訂單檔代表「這一批」本身。
2. 已完成、訂單檔 checksum 不同 → `SourceChangedError`，代表來源檔被改過，不默默跳過。
3. 前面的批次沒完成 → `BatchOrderError`，在呼叫 `run` 之前丟出，什麼都還沒寫。順序是 `BATCH_ORDER`＝base → day1 → day2 → day3。原因：dim_member 用 `last_seen_extract_date` 擋重送，判斷以會員為單位，順序亂掉會遺失中間那段會員歷史（見 dim_member.py 一節）。
4. 呼叫 `run()`，最後寫完成紀錄。`run` 中途丟例外時不寫紀錄，下次重跑整批。
5. `force=True`：已完成也照跑一次並覆寫紀錄，給冪等證明用。**force 不比對 checksum**：來源被改過時，會用新內容覆寫這批的結果。覆寫既有紀錄時，**呼叫 `run` 之前**先在**強制重跑紀錄**追加一列 `started`（`record_forced`），寫完新的完成紀錄後再追加 `completed`，事後看得出這批被 force 過、覆寫了什麼（使用者定 C：「要避免訂單狀態可以被隨意修改 如果要修改需要使用 force 來紀錄」）。`run` 中途丟例外時不寫完成紀錄，但 `started` 已經留下：fact 可能已被新內容改寫（例如 MERGE 之後當掉），即使之後把來源檔改回、一般重跑被跳過，仍查得到這次 force（T6 follow-up 驗收找到的漏洞）。

強制重跑紀錄：一張只增不改的 Delta 表（`WarehousePaths.batch_force_log`＝`batch_log_force`；直接呼叫 `run_once` 沒給 `force_log_path` 時是 `<log_path>_force`），建立時設表屬性 `delta.appendOnly=true`，UPDATE、DELETE 會被 Delta 拒絕，「只增不改」由表本身保證。每次 force 兩列（`started`、`completed`，同一個 `forced_at`）；只有 `started` 代表那次 force 沒有完成。欄位（`BATCH_FORCE_LOG_SCHEMA`）：`batch_id`、`forced_at`（這次 force 開始的時間）、`status`、`logged_at`、`previous_completed_at`、`previous_source_sha256`、`new_source_sha256`、`source_changed`、`previous_reference_sha256`、`new_reference_sha256`。`forced_runs(spark, force_log_path, batch_id)` 依時間列出某批的紀錄（同一次 force 的 started 排在 completed 前）。完成紀錄（`batch_log`）仍是每批一列、存最新一次的結果；另存一張表而不是在 `batch_log` 加欄位，是因為同一批可能被 force 多次，欄位只留得住最後一次。第一次執行就帶 `--force`（沒有既有紀錄可覆寫）不寫強制重跑紀錄。

**為什麼冪等要靠批次紀錄，不能只靠 fact**：重跑同一批時，fact 已經是這批的結果，這批每列都會變成晚到事件，分類和第一次不同。所以已完成的批次直接跳過。當掉後重跑、強制重跑時，則由 fact_order 拿「這批開始之前」的 fact 來比對（見下一段與 fact_order.py 一節）。

`pin_fact_version(spark, start_path, batch_id, current_version)`：一張 Delta 表（`WarehousePaths.batch_start`），每批一列 `batch_id`、`fact_version_before`、`started_at`。第一次呼叫時記下傳入的目前版本（fact 還不存在時是 -1），之後都回傳記下的值。fact_order 在寫任何 fact、隔離表之前呼叫它，所以當掉也不會漏記。不從 Delta history 找 commit 標記，是因為這批寫進 fact 的列為 0 時 MERGE 不產生 commit（T6 驗收找到的漏洞）。

### 3.12 fact_order.py
**規則**（已定案，見 process-log 與 ADR-03、ADR-04）
- 粒度：一張訂單一列、存最新狀態，以 `order_id` MERGE。
- 新舊以 `updated_at` 判斷（J6）。fact 只在 `updated_at` 較新時覆寫：MERGE 條件是 `FACT_UPDATE_CONDITION`＝`s.updated_at > t.updated_at`，是狀態機之外的第二道防線。
- 完全重複（V7）：同一 order_id 依 `updated_at` 排序，**時間上相鄰**、除了 `updated_at` 以外全部相同的列才算重複，保留 `updated_at` 最新的一列，其餘以 `duplicate` 進隔離表（使用者定：「中間如果有出現其他狀態 不能當作延遲」）。做法：同一張單、同一個 `updated_at` 的列算一組；只有一種內容的組才去重，組內留一列，下一組內容相同時整組算重複；同一秒有多種內容的組不去重，交給狀態機判斷同一秒衝突。下單時間比較**解析後的時刻**，不比較字串（V7 有 8 組格式不同、時刻相同）。中間夾著其他內容的相同列、內容不同的同 order_id 列，都交給狀態機處理。
- 撞號：同一 order_id，會員、下單時間、金額任一不同（`IMMUTABLE_COLUMNS`），整組進隔離表，不寫 fact。
- 金額：存 `amount`（折扣前，J10）、`currency`（原值）、`amount_twd`、`net_amount_twd`（＝`amount_twd − coupon_discount`，coupon 是台幣）。`amount_twd` 用**台北下單日**當天的匯率。TWD、NTD 固定 1（`TWD_PEGGED_CURRENCIES`），匯率表用 left join，所以沒有匯率列的 TWD 不會遺失（`buggy_pipeline.py` 用 inner join 弄丟了 TWD）。其他幣別找不到當天匯率就進隔離表，不用前一天的匯率代替。
- 產品清單有違規列或 `product_id` 重複、匯率表有違規列或同日同幣別重複：丟 `ReferenceDataError`，在寫任何表之前停下，fact、隔離表、維度、批次紀錄都不寫。product_id 重複原本是 dim_product 的 `DuplicateKeyError`，這裡統一轉成 `ReferenceDataError`，原例外保留在 `__cause__`。
- product_id 不在清單：`product_sk` 落到 -1，訂單照寫，對帳另列筆數（V6，使用者理由：商品會隨時間下架消失，盡量保留訂單）。
- 會員對不到下單日當時的版本：整列以 `member_missing` 進隔離表，不落 -1，對帳的 `unknown_member_rows` 記筆數。和 V6 刻意不同：會員是客戶分析的主體，對不到代表管線或上游有錯，要用隔離表提醒修正。〔防護性設計：本資料 0 筆〕
- fact_order 建表時帶 Delta CHECK 約束（`FACT_CHECK_CONSTRAINTS`），擋繞過管線的寫入，見下方「Delta CHECK 約束」。
- A-3 定案：負數金額在合約擋下（`contract`，「amount:必須大於 0」）；coupon＝-1.0（`contracts.COUPON_UNKNOWN`）代表未知，在 ① 之後轉成 NULL、照常寫入，筆數記在對帳 `coupon_nulled_rows`；coupon 是 -1 以外的負數在合約擋下（「coupon_discount:必須大於或等於 0（-1.00 除外）」）〔防護性設計：本資料 0 筆〕；疑似多乘 1,000、coupon 大於 amount_twd（net 為負）都照原樣寫入，另列金額人工確認清單（見下方 `amount_review`）；completed 但出發日未到只記錄。品質規則的掛載點是 `ORDER_QUALITY_RULES`，目前是空的。每條規則的型別是 `Callable[[dt.date], Column]`：收這批的 `as_of`，回傳原因字串，不違規時為 NULL。命中的列以 `quality` 類別進隔離表，一列命中多條時原因全部列出。

**一批的處理順序**（`transform_order_batch`，純轉換）
```
參考資料檢查（products、fx_rates）→ 有問題整批停
寫 dim_product、dim_member（as_of 為止）
 ① cast_to_contract           → 隔離：contract（含值不在允許範圍、金額不大於 0）
    coupon -1.0 轉 NULL         （清理，不隔離；計數 coupon_nulled_rows）
 ② 同批撞號                    → 隔離：collision（整組）
 ③ 完全重複去重                 → 隔離：duplicate（時間上相鄰、除 updated_at 外全同，保留最新）
 ④ 與既有 fact 撞號            → 隔離：collision_existing（整組）
 ⑤ 狀態機                      → 略過：late_event；隔離：superseded、late_event_conflict、
                                  illegal_transition、ambiguous_order、after_illegal
 ⑥ 換算 amount_twd             → 隔離：fx_missing
 ⑦ 品質規則（A-3，目前沒有）     → 隔離：quality
 ⑧ 對維度（product_sk、member_sk、date_sk）→ 隔離：member_missing（會員對不到版本）
    算 net_amount_twd
    金額人工確認清單：寫入列中比值 > 100 或 coupon > amount_twd 的列（不隔離）
寫 dim_date（① 的合格列）
記下這批開始前的 fact 版本（batch_start，只在第一次記）
寫 dim_member 時順便寫會員隔離表（replaceWhere 快照日）
對帳（輸入＝寫入＋隔離＋略過，不平就丟 ReconciliationError、不寫入）→ 寫隔離表 → 寫金額人工確認清單 → MERGE fact（建表時先加 CHECK 約束）
```
每一步淘汰的列都帶著類別（`reject_category`）與原因進隔離表，所以各類別互斥，加總等於輸入。dim_date 用 ① 的合格列擴充，所以被 ②～⑧ 隔離的訂單的日期也會在 dim_date 裡。

**和哪一版的 fact 比**：④ 撞號與 ⑤ 狀態機都和「這批開始之前」的 fact 比（`_fact_before_batch`）。第一次跑時記下當時 fact 的版本（`batch_log.pin_fact_version`）；當掉後重跑、強制重跑時沿用記下的版本，用 time travel 讀出來。這樣重跑的分類和第一次相同，隔離表與金額人工確認清單的 replaceWhere 也會寫回相同內容。限制：對 fact 執行 VACUUM 後舊版本的檔案被刪，重跑會報錯；超過 Delta log 保存期限（預設 30 天）後舊版本也讀不到。

**對外函式**
- `transform_order_batch(orders, *, batch_id, as_of, fx, dim_product, dim_member, existing)`：①～⑧ 的純轉換，不寫 Delta、不觸發計算，回傳 `BatchTransform(valid, fact, quarantine)`；`fact` 多帶一欄 `state_skipped`。測試直接驗它。
- `load_order_batch(spark, source, *, batch_id, orders, as_of, paths)`：處理一批（參考資料檢查、寫維度、轉換、對帳、寫入），回傳 `BatchReconciliation`。不檢查批次順序、不寫批次紀錄。
  - `batch_id`：寫進 fact 與隔離表；隔離表依它 replaceWhere。只接受英數、底線、連字號，因為它會被拼進 replaceWhere 的條件。
  - `as_of`：這批的業務日期，當 `write_dim_member` 的 `through`，會員快照只看到這天為止。dim_date 只依這批訂單擴充（和既有範圍取聯集），不偷看之後的增量。
  - `paths`：`WarehousePaths(root)`，各表放在 root 底下：`fact_order`、`quarantine_order`、`quarantine_member`（`member_quarantine`）、`amount_review`、`dim_product`、`dim_member`、`dim_date`、`batch_log`、`batch_log_force`（`batch_force_log`）、`batch_start`。
- `load_base(spark, source, paths)`：`batch_id="base"`、`as_of=2026-06-30`。
- `load_incremental(spark, source, day, paths)`：`batch_id="day{day}"`、`as_of=INCREMENTAL_AS_OF[day]`（07-01～07-03）。
- `run_batch(spark, source, paths, day, *, force=False)`：用 `batch_log.run_once` 包住一批（`day=None` 是 base）。
- `run_all(spark, source, paths)`：依序 base → day1 → day2 → day3，已完成的批次跳過。
- `amount_totals(spark, paths)`：跑 `AMOUNT_EXCLUDING_REVIEW_SQL`，回傳 `AmountTotals(amount_twd_total, amount_twd_excluding_review, review_orders)`：fact 的 amount_twd 總和（所有狀態含 cancelled、折扣前）、排除金額人工確認清單上的訂單後的總和、fact 中在清單上的訂單數。這不是營收的定義（是否含取消單、折扣前或後由下游語意層決定，見 Part C）；說明見 `part_a/README.md`「排除待確認清單後的金額總和」。
- `find_batch_collisions(orders)`、`find_existing_collisions(orders, fact)`：回傳撞號的 order_id，後者已去重，呼叫端用 left_semi 取整組。輸入的 `order_created_at` 要是解析後的 timestamp，`amount` 是 Decimal。

**fact_order 欄位**

| 欄位 | 型別 | 說明 |
|---|---|---|
| `order_id` | STRING | 自然鍵、MERGE key |
| `member_id`、`product_id` | STRING | 來源的自然鍵；撞號比對要用 member_id，也保留對不到維度時的原值 |
| `member_sk` | BIGINT | 依台北下單日對到當時有效的版本；一定對得到（對不到的訂單進隔離表，CHECK `member_sk IS NOT NULL`） |
| `product_sk` | BIGINT | 對不到 -1 |
| `order_date_sk` | INT | 台北下單日，yyyymmdd |
| `departure_date_sk` | INT | 出發日，yyyymmdd；出發日空值時為 NULL（沒有出發日，不是未知的日期；實際 0 列） |
| `order_status`、`channel` | STRING | 原值 |
| `quantity` | INT | |
| `currency` | STRING | 原值（NTD 不改成 TWD，可追溯） |
| `amount` | DECIMAL(18,2) | 原幣別金額 |
| `fx_rate` | DECIMAL(18,6) | 換算用的匯率；TWD、NTD 為 1 |
| `amount_twd` | DECIMAL(38,2) | `round(amount × fx_rate, 2)`，四捨五入（HALF_UP）；用 38 位是因為乘積精度 37 位，避免溢位 |
| `coupon_discount` | DECIMAL(18,2) | 台幣折扣（已定案）；來源 -1.0 代表未知，轉成 NULL（V3） |
| `net_amount_twd` | DECIMAL(38,2) | 折扣後金額 `amount_twd − coupon_discount`（J10：amount 是折扣前）；coupon 為 NULL 時也是 NULL |
| `order_created_at`、`updated_at` | TIMESTAMP | 解析後的時刻 |
| `batch_id` | STRING | 最後寫入這一列的批次 |

跳過中間狀態不存成 fact 欄位，只在對帳與批次紀錄計數（使用者定：不影響下游分析的情況下先記 log，不過度設計）。

**Delta CHECK 約束**（`FACT_CHECK_CONSTRAINTS`，使用者定 B：只加在關鍵欄位，「Delta CHECK 是最後一道防線，擋得住繞過管線的寫入」）〔防護性設計：本資料 0 筆〕

| 約束名稱 | 條件 | 對應的管線規則 |
|---|---|---|
| `order_id_not_null` | `order_id IS NOT NULL` | MERGE 的鍵；NULL 的 order_id 每次 MERGE 都對不到，會一直重複插入 |
| `amount_positive` | `amount > 0` | V1，合約層 |
| `coupon_discount_non_negative` | `coupon_discount IS NULL OR coupon_discount >= 0` | V3（-1.0 轉 NULL）＋合約擋其他負數；`net_amount_twd` 依賴它 |
| `order_status_valid` | `order_status IN (...)`，由 `order_status.STATUSES` 產生 | 合約允許值 |
| `currency_valid` | `currency IN (...)`，由 `contracts.ORDER_CURRENCIES` 產生 | 合約允許值 |
| `member_sk_not_null` | `member_sk IS NOT NULL` | ⑧ 會員對不到進隔離表 |

- 管線本身已在合約層與 ⑧ 擋下這些值，走管線的寫入永遠不會觸發；約束存在表本身，擋的是 notebook 直接寫入、手動 `UPDATE` 這類繞過管線的寫入。違反時 Delta 丟 `DeltaInvariantViolationException`（訊息含約束名稱），整次寫入不生效。
- 只加在 fact_order。維度表由管線從參考資料重算，隔離表、金額人工確認清單本來就是放「有問題的列」，都不加。
- 值域不寫死：約束文字由 `STATUSES`、`ORDER_CURRENCIES` 產生，改允許值時約束跟著改（`ensure_check_constraints` 會 DROP 再 ADD；DROP 之前先查既有資料，有不符合新條件的列就丟 `ValueError`、不 DROP，舊約束保留。檢查和 DROP／ADD 不在同一個交易裡）。

**隔離表 `quarantine_order`**
- 欄位：`batch_id`、orders 的 12 個欄位（**原始字串**）、`_source_error`、`reject_category`、`reject_reasons`（ARRAY<STRING>）。
- `reject_category`：`contract`、`collision`、`duplicate`、`collision_existing`、`superseded`、`late_event`（略過）、`late_event_conflict`、`illegal_transition`、`ambiguous_order`、`after_illegal`、`fx_missing`、`quality`、`member_missing`。
- 寫入：`replaceWhere batch_id = '<batch_id>'`，先清掉同一批的舊資料再寫，重跑不會變兩份，其他批不受影響。

**金額人工確認清單 `amount_review`**（使用者定：疑似多乘 1,000、折扣大於金額都照原樣寫入，另列清單逐筆判斷）
- 一張 Delta 表，欄位：`batch_id`、`order_id`、`product_id`、`quantity`、`currency`、`amount`、`fx_rate`、`amount_twd`、`base_price_twd`、`amount_ratio`、`coupon_discount`、`net_amount_twd`、`review_reasons`（ARRAY<STRING>）。
- 內容：這批寫進 fact 的列中，命中下面任一原因的列，**每張單一列**；兩種都命中時 `review_reasons` 依下面的順序列出兩個原因（不拆成兩列，清單筆數＝要人看的訂單數）。
  - V2（`REVIEW_REASON_RATIO`）：`amount_ratio`＝`amount_twd ÷（base_price_twd × quantity）`（四捨五入到 2 位）大於 `AMOUNT_REVIEW_RATIO`＝100。正常列的比值落在 0.84～1.29，疑似多乘 1,000 的約 1,000，門檻取兩者之間。產品落到 -1 時沒有定價，算不出比值，不算命中（`amount_ratio` 為 NULL）。
  - 折扣大於金額（`REVIEW_REASON_COUPON`）：`coupon_discount > amount_twd`，`net_amount_twd` 為負（使用者定 B：「太大的可能是全額折抵」，所以不隔離）。coupon 為 NULL 時不算命中。〔防護性設計：本資料 0 筆〕
- 寫入：和隔離表一樣依 batch_id replaceWhere。本資料 base 40 列、增量 0 列。
- 清單只標記、不改 fact：fact 的 `amount_twd` 總和包含這些列。下游在人工確認前排除清單上的訂單（使用者定 B1），查詢是 `AMOUNT_EXCLUDING_REVIEW_SQL`（見 `part_a/README.md`「排除待確認清單後的金額總和」）。

**`BatchReconciliation`**（`batch_log.BatchCounts` 加上 `batch_id`）
- `input_rows`＝`fact_rows`＋`quarantined_rows`＋`skipped_rows`（`balanced`）。`quarantined_by_category` 不含略過的類別。
- `skipped_intermediate_rows`：寫進 fact 的列中，跳過中間狀態的筆數（只算寫進 fact 的列；狀態機的 `state_skipped` 也只會標在 accepted 的列）。
- `coupon_nulled_rows`：寫進 fact 的列中，coupon -1.0 轉成 NULL 的筆數。
- `amount_review_rows`：這批列進金額人工確認清單（`amount_review`）的筆數（每張單算一次）。
- `amount_twd_sum`、`net_amount_twd_sum`、`unknown_product_rows`：這批寫進 fact 的列（net 總和不計 NULL）。
- `unknown_member_rows`：這批因會員對不到版本進隔離表（`member_missing`）的筆數，已含在 `quarantined_rows` 內。〔防護性設計：本資料 0 筆〕
- `fact_table_rows`、`fact_table_amount_twd_sum`、`fact_table_net_amount_twd_sum`：寫入後整張 fact。
- `member_rejected_rows`：dim_member 這次的違規列數（會員快照，寫進會員隔離表，不在訂單對帳內）。members.csv 每批都整份重讀，所以同一列壞列每批都會算到。
- 筆數都用 `count()` 計算，只在 `build_spark()` 的設定下才準（見 session.py 一節）。

### 3.13 run.py
`python -m pipeline.run [--data-dir 目錄] [--out 目錄] [--force]`：依序跑 base → day3，每批印出對帳，最後印出 fact 的 amount_twd 總和與排除金額人工確認清單後的總和（`fact_order.amount_totals()`）。參數沒給時讀環境變數 `LIONTEST_DATA_DIR`、`LIONTEST_OUT`。Docker 的 CMD 就是這條指令（見 `part_a/README.md`「怎麼跑」）。

## 4. 測試
```bash
uv run pytest LionDEExam/submission/part_a/tests -q -m "not slow"   # 開發中：只跑快的
uv run pytest LionDEExam/submission/part_a/tests -q                  # 交付前：全套
TZ=UTC uv run pytest LionDEExam/submission/part_a/tests -q           # 交付前：模擬 Docker 時區
```
- 測試策略：轉換邏輯（格式、撞號、去重、狀態機、換匯、品質規則）呼叫 `transform_order_batch()`、`classify_status_events()` 只驗 DataFrame；會寫 Delta 或跑真實資料完整流程的測試標 `slow`（`pyproject.toml` 註冊）。
- 真實資料：base 的期望值在 `test_fact_order.py`、增量在 `test_fact_order_incremental.py`，都用純 Python csv 依定案規則獨立計算，不呼叫被測的實作。
- Delta 輸出寫到 pytest 的 `tmp_path`，不會寫進 repo。
- 時間相關的測試會先在 Spark 內用 `date_format` 轉成字串再比對。PySpark 把 timestamp collect 回 Python 時，會轉成執行機器的本地時區；Docker 容器內是 UTC，直接比對 timestamp 會讓測試失敗。
