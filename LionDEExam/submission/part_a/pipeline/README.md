# pipeline｜Part A 管線程式

Part A 的管線程式碼。本檔說明各模組負責什麼、對外提供哪些函式，以及寫新的表時要注意的事。設計理由見上一層的 `part_a/README.md`。

> 施工中：目前有 T3（共用設定、來源讀取、dim_product、dim_date）、T4（dim_member）、T5（fact_order 初始載入、隔離表、對帳）的內容。增量處理（T6）完成後會補上。

## 模組一覽
| 模組 | 負責 | 主要對外介面 |
|---|---|---|
| `session.py` | 建立 SparkSession | `build_spark()`、`SESSION_TIMEZONE` |
| `contracts.py` | 各來源的 schema 合約（唯一一份） | `ORDERS_SCHEMA`、`MEMBERS_SCHEMA`、`PRODUCTS_SCHEMA`、`FX_RATES_SCHEMA`、`to_raw_schema()` |
| `sources.py` | 讀取來源、檔案層級檢查 | `SourceReader`（介面）、`CsvSource`（CSV 實作）、`SourceFileError` |
| `validation.py` | 轉成合約型別、分出違規列 | `cast_to_contract()`、`strict_date()`、`REJECT_REASONS_COL` |
| `delta_io.py` | 寫入 Delta 表 | `merge_upsert()` |
| `timeparse.py` | 來源時間字串的格式定義與解析（validation 與 dims 共用） | `SOURCE_TIMESTAMP_FORMATS`、`parse_source_timestamp()` |
| `dim_member.py` | 會員維度（SCD Type 2） | `write_dim_member()`、`build_dim_member()`、`resolve_member_sk()`、`UNKNOWN_MEMBER_SK` |
| `dims.py` | 維度表 | `write_dim_product()`、`write_dim_date()`、`all_orders()`、`resolve_product_sk()`、`date_sk()` |
| `fact_order.py` | 一批訂單的處理入口：維度更新、fact_order、隔離表、對帳 | `load_order_batch()`、`load_base()`、`WarehousePaths`、`BatchReconciliation`、`find_batch_collisions()`、`find_existing_collisions()`、`ReferenceDataError` |

模組間的 import：`contracts` 用 `timeparse`；`sources` 用 `contracts`；`validation` 用 `contracts`、`timeparse`；`dims` 用 `contracts`、`sources`、`delta_io`、`timeparse`；`dim_member` 用 `contracts`、`validation`、`delta_io`；`fact_order` 用 `contracts`、`validation`、`delta_io`、`timeparse`、`dims`、`dim_member`、`sources`。`session`、`delta_io`、`timeparse` 不依賴其他模組。

## 用法
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

# 一般用法：一批一次呼叫，維度、fact_order、隔離表、對帳都在裡面
from pipeline.fact_order import WarehousePaths, load_base

rec = load_base(spark, source, WarehousePaths("/tmp/liontest/wh"))
assert rec.balanced  # 輸入＝fact＋隔離
```
輸出路徑由呼叫端決定，模組內不寫死。

## 各模組

### session.py
`build_spark()` 啟用 Delta，並固定以下設定：

| 設定 | 值 | 原因 |
|---|---|---|
| `spark.sql.session.timeZone` | `Asia/Taipei` | 下單日、匯率日都依賴時區，不固定的話，不同機器可能算出不同的日期 |
| `spark.sql.shuffle.partitions` | 4 | 本機資料量小，用預設的 200 會產生大量空分區 |
| `spark.sql.csv.parser.columnPruning.enabled` | `false` | 開著時，`count()` 這類只需要部分欄位的查詢不會檢查每列的欄位數，`_source_error` 不會被填值，欄位數不符的列（少欄、多欄、結尾多逗號、引號內換行、引號不成對）會被算成 valid，筆數守恆就失真。實測關掉後 `count()` 和 `collect()` 結果一致 |

### contracts.py
每個來源的欄名、型別、是否必填都寫成 `StructType` 常數，是全專案唯一一份合約；讀取用的全字串 schema 由 `to_raw_schema()` 從合約自動產生，不另外手寫。

- **必填欄位用 `nullable=False` 標示**：空值時這一列無法被正確處理或歸屬的欄位才設為必填（例如 orders 的 order_id、member_id、product_id、amount、updated_at；members 的 register_date、extract_date；fx_rates 全部）。理由寫在各欄旁邊。目前資料中沒有任何空值，必填清單是依語意決定。

- **金額用 `DecimalType(18, 2)`，匯率用 `DecimalType(18, 6)`**：對帳和 checksum 需要精確的值，用 double 會有浮點誤差。
- **格式不一致的欄位讀成字串**：例如 `order_created_at` 混用三種時間格式，先保留原樣，再用 `parse_source_timestamp()` 解析。

### sources.py
`SourceReader` 是來源介面，每個來源表對應一個方法：`orders_base()`、`orders_incremental(day)`、`members()`、`products()`、`fx_rates()`。現在只有 CSV 實作 `CsvSource`；之後換成從 SQL DB 讀，只要新增一個實作同一組方法的類別（ADR-02）。

讀取方法回傳的 DataFrame 中，合約欄位**全部是原始字串**，另外多一欄 `_source_error`。讀取層不轉型，所以型別錯的值不會在讀取時被轉成 NULL 或被四捨五入。

違規分兩層處理（已定案）：

| 層級 | 情況 | 處理 |
|---|---|---|
| 檔案 | 檔案不存在、表頭欄名或順序與合約不符、沒有資料列 | 呼叫讀取方法時立即丟 `SourceFileError`（`kind` 為 `missing`／`header`／`empty`），整批停下，不寫入任何東西 |
| 列 | 欄位數與表頭不符 | 該列原文放在 `_source_error`，由 `cast_to_contract()` 分到 rejected |

**注意：** 不要只查 `_source_error` 一欄（例如 `raw.filter("_source_error IS NOT NULL").count()`）。Spark 不允許只引用 corrupt record 欄位的 CSV 查詢，會丟 `UNSUPPORTED_FEATURE.QUERY_ONLY_CORRUPT_RECORD_COLUMN`。統計格式錯誤的列，請從 `cast_to_contract()` 的 rejected 計算（例如篩 `reject_reasons` 含「列格式錯誤」的列）。

檔案層級的檢查用 `spark.read.text(...).take()` 立即讀出檔案開頭來比對。列層級的欄位數檢查依賴 `build_spark()` 關掉 CSV column pruning（見 session.py 一節）；自己建 SparkSession 時要記得加這個設定，否則 `count()` 會把壞列算成 valid。

### validation.py
`cast_to_contract(df, schema, *, passthrough=())` 回傳 `(valid_df, rejected_df)`，是唯一的轉型入口，fact_order 的隔離表也用它。

- **valid_df**：沒有違規的列，欄名、欄序、型別與合約相同。
- **rejected_df**：有違規的列，保留所有原始字串欄位（含 `_source_error`），加上 `reject_reasons`（字串陣列，一列有多個原因時全部列出，格式「欄名:原因」）。
- **筆數守恆**：兩者用同一個條件切開，valid 筆數＋rejected 筆數＝輸入筆數，之後對帳「輸入＝寫入＋隔離」靠這一點。
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

時間格式規則和 `parse_source_timestamp()` 共用 `timeparse.SOURCE_TIMESTAMP_FORMATS` 這一份定義，所以進得了 valid 的列，下單時間一定解析得出來，dim_date 的範圍和 fact 的 date_sk 不會因為 NULL 而悄悄漏掉。`updated_at` 目前資料全是 `+08:00` 格式，比照辦理是因為增量判斷新舊靠它，解析不了就無法比較。

不靠 Spark 的 `try_cast` 判斷，因為它很寬鬆，實測：`100.456` 轉 `DECIMAL(18,2)` 得到 `100.46`、`1e2` 得到 `100.00`、`' 3'` 轉 INT 得到 `3`、`2026-06-25T14:02:16+08:00` 轉 DATE 得到 `2026-06-25`，全部不報錯。

### delta_io.py
`merge_upsert(spark, df, path, keys)`：依 `keys` 把 `df` MERGE 進 `path` 的 Delta 表。比對到的列整列覆寫，沒比對到的新增；表不存在時直接建立。同一份輸入重跑，結果不變。

**注意：重跑時既有列仍會被重寫，只是值相同。** Delta history 的 operationMetrics 會顯示 `numTargetRowsUpdated` 等於筆數，這只代表列被重寫，不代表內容改變；要判斷內容是否改變，請比對表內容或 checksum。

**注意：呼叫前，`df` 的 `keys` 必須唯一。** 來源同一個 key 有多列，而目標表還沒有這個 key 時，Delta 會把多列全部插入，不會報錯（Part B 的 E12）。

### dims.py
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

### dim_member.py
**規則**（已定案，見 process-log「dim_member SCD2 規則」）
- 依 extract_date 由舊到新處理。會員沒出現在某一批就沿用前一版；內容沒變不開新版。
- `member_level`、`city` 是 Type 2，值變就開新版；`member_name`、`birth_date` 是 Type 1，覆寫該會員所有版本。
- 同一會員、同一 extract_date 有多列（V8）時取較高等級：一般 < 銀卡 < 金卡 < 白金。等級不在這四個值內（含 NULL）的列進 rejected，不猜排序；`register_date` 晚於 `extract_date` 的列也進 rejected。
- `city = 'N/A'`、`birth_date = 1900-01-01` 轉成 NULL，而且不蓋掉已知的真實值：city 從真實值變 N/A 不算變動。city 從 NULL 變成真實值**算變動、開新版本**，不回填舊版本（回填等於斷言「他以前也住這裡」）。
- 版本區間：第一版 `valid_from = register_date`；之後各版是觀察到變動那一批的 extract_date。`valid_to` 不含當天（等於下一版的 `valid_from`），目前版本是 `9999-12-31`，另有 `is_current`。
- 代理鍵 `member_sk = xxhash64(member_id, valid_from)`，重跑、換輸入順序都不變。另有一列「未知會員」（`UNKNOWN_MEMBER_ID = "UNKNOWN"`、`UNKNOWN_MEMBER_SK = -1`）：`valid_from = 1900-01-01`、`valid_to = 9999-12-31`、`is_current = true`，`register_date` 與等級、城市、生日等屬性都是 NULL。`resolve_member_sk` 不靠這列的區間去對，而是對不到任何版本時直接給 -1。

**對外函式**
- `write_dim_member(spark, members, path, *, through)`：`members` 是 `source.members()` 的**原始字串** DataFrame（轉型在函式內做）。只處理 `extract_date <= through` 的快照，以 `member_sk` MERGE。回傳 `DimMemberWrite`：
  - `table`：寫入後讀回的**整張表**，可以直接給 `resolve_member_sk`。
  - `rejected`：違規列，形狀同 `cast_to_contract` 的 rejected（原始字串＋`reject_reasons`）。fact_order 目前只計數（`BatchReconciliation.member_rejected_rows`），不寫進訂單隔離表，因為欄位不同；本題資料 0 列。
  - `stats`：`input_rows`（through 以內的列數，等於 valid＋rejected）、`rows_after_through`、`rejected_rows`、`same_day_conflicts`、`city_placeholder_rows`、`birth_placeholder_rows`、`stale_rows_skipped` 等。
- `through` 是必填的關鍵字參數，比照 `all_orders` 的 `days`：逐日處理時忘了過濾，就會偷看到之後的快照。extract_date 不符合合約日期規則的列（例如 `2026/04/30`、`2026-07-15 junk`）不會被這個過濾吃掉，會在本批進 rejected；過濾用 `strict_date()` 判斷，不用 try_cast。
- `build_dim_member(spark, members, *, through, existing=None)`：只計算、不寫入。回傳的 `changes` 只有「這批受影響的會員的所有版本＋未知會員列」，**不能拿去 resolve**（從頭建時才等於整張表）。

**`resolve_member_sk(fact_df, dim_df, date_col)`**
- 依 `member_id` 與下單日對到當時有效的版本：`valid_from <= 下單日 < valid_to`。版本區間不重疊，所以每張單最多對到一版，fact 列數不變。
- 對不到的（member_id 不存在或為 NULL、下單日早於 register_date）落到 -1。
- **`dim_df` 必須是整張 dim_member**（`write_dim_member` 回傳的 `table`，或直接讀 Delta）。只給部分會員時，其他會員的訂單會靜默落到 -1，fact 列數不變，對帳抓不到。
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

### fact_order.py
**規則**（已定案，見 process-log 與 ADR-03、ADR-04）
- 粒度：一張訂單一列、存最新狀態，以 `order_id` MERGE。
- 同一 order_id 除了 `updated_at` 以外全部相同（V7）：保留 `updated_at` 最新的一列，其餘進隔離表。下單時間比較**解析後的時刻**，不比較字串（V7 有 8 組格式不同、時刻相同）。
- 撞號：同一 order_id，會員、下單時間、金額任一不同（`IMMUTABLE_COLUMNS`），整組進隔離表，不寫 fact。
- 金額：存 `amount`、`currency`（原值）、`amount_twd`。`amount_twd` 用**台北下單日**當天的匯率；TWD、NTD 固定 1（`TWD_PEGGED_CURRENCIES`），匯率表用 left join，所以沒有匯率列的 TWD 不會遺失（`buggy_pipeline.py` 用 inner join 弄丟了 TWD）。其他幣別找不到當天匯率就進隔離表，不用前一天的匯率代替。
- 產品清單有違規列或 `product_id` 重複、匯率表有違規列或同日同幣別重複：丟 `ReferenceDataError`，在寫任何表之前停下，fact、隔離表、維度都不寫。product_id 重複原本是 dim_product 的 `DuplicateKeyError`，在這裡統一轉成 `ReferenceDataError`（原例外保留在 `__cause__`），T6 的批次紀錄只需要處理一種參考資料錯誤。
- product_id 不在清單、會員對不到版本：sk 落到 -1，對帳另列筆數。
- 負數金額、疑似 ×1000、coupon -1.0、completed 但出發日未到：目前照原樣寫進 fact（A-3 再決定）。規則的掛載點是 `ORDER_QUALITY_RULES`，目前是空的。每條規則的型別是 `Callable[[dt.date], Column]`：收這批的 `as_of`（例如「completed 但出發日未到」要拿出發日和 as_of 比），回傳原因字串，不違規時為 NULL；命中的列以 `quality` 類別進隔離表，一列命中多條時原因全部列出。

**一批的處理順序**（`load_order_batch`）
```
參考資料檢查（products、fx_rates）→ 有問題整批停
 ① cast_to_contract           → 隔離：contract
 ② 同批撞號                    → 隔離：collision（整組）
 ③ 去重（保留 updated_at 最新） → 隔離：duplicate（除 updated_at 外全同）／superseded（較舊的狀態更新）
 ④ 與既有 fact 撞號            → 隔離：collision_existing
 ⑤ 換算 amount_twd             → 隔離：fx_missing
 ⑥ 品質規則（A-3，目前沒有）     → 隔離：quality
 ⑦ 對維度（product_sk、member_sk、date_sk）
對帳（輸入＝fact＋隔離，不平就丟 ReconciliationError、不寫入）→ 寫隔離表 → MERGE fact
```
每一步淘汰的列都帶著類別（`reject_category`）與原因進隔離表，所以各類別互斥，加總等於輸入。維度（dim_product、dim_member、dim_date）在 ① cast_to_contract 之後、② 同批撞號之前寫入；dim_date 用 ① 的合格列擴充，所以被 ②～⑥ 隔離的訂單的日期也會在 dim_date 裡。

**對外函式**
- `load_order_batch(spark, source, *, batch_id, orders, as_of, paths)`：處理一批，回傳 `BatchReconciliation`。
  - `orders`：這批的原始字串訂單，例如 `source.orders_base()`、`source.orders_incremental(1)`。
  - `batch_id`：寫進 fact 與隔離表；隔離表依它 replaceWhere。只接受英數、底線、連字號（它會被拼進 replaceWhere 的條件）。
  - `as_of`：這批的業務日期，當 `write_dim_member` 的 `through`，會員快照只看到這天為止。dim_date 只依這批訂單擴充。
  - `paths`：`WarehousePaths(root)`，各表在 root 底下（`fact_order`、`quarantine_order`、`dim_product`、`dim_member`、`dim_date`）。
- `load_base(spark, source, paths)`：`batch_id="base"`、`as_of=2026-06-30`。
- `find_batch_collisions(orders)`、`find_existing_collisions(orders, fact)`：回傳撞號的 order_id。輸入的 `order_created_at` 要是解析後的 timestamp、`amount` 是 Decimal。T6 處理增量時用後者比對「增量列 vs 既有 fact」。

**fact_order 欄位**

| 欄位 | 型別 | 說明 |
|---|---|---|
| `order_id` | STRING | 自然鍵、MERGE key |
| `member_id`、`product_id` | STRING | 來源的自然鍵；撞號比對要用 member_id，也保留對不到維度時的原值 |
| `member_sk` | BIGINT | 依台北下單日對到當時有效的版本；對不到 -1 |
| `product_sk` | BIGINT | 對不到 -1 |
| `order_date_sk` | INT | 台北下單日，yyyymmdd |
| `departure_date_sk` | INT | 出發日，yyyymmdd；出發日空值時為 NULL（沒有出發日，不是未知的日期；base 實際 0 列） |
| `order_status`、`channel` | STRING | 原值 |
| `quantity` | INT | |
| `currency` | STRING | 原值（NTD 不改成 TWD，可追溯） |
| `amount` | DECIMAL(18,2) | 原幣別金額 |
| `fx_rate` | DECIMAL(18,6) | 換算用的匯率；TWD、NTD 為 1 |
| `amount_twd` | DECIMAL(38,2) | `round(amount × fx_rate, 2)`，四捨五入（HALF_UP）；用 38 位是因為乘積精度 37 位，避免溢位 |
| `coupon_discount` | DECIMAL(18,2) | 原值，未換算（coupon 的幣別待使用者確認） |
| `order_created_at`、`updated_at` | TIMESTAMP | 解析後的時刻 |
| `batch_id` | STRING | 最後寫入這一列的批次 |

**隔離表 `quarantine_order`**
- 欄位：`batch_id`、orders 的 12 個欄位（**原始字串**）、`_source_error`、`reject_category`、`reject_reasons`（ARRAY<STRING>）。
- `reject_category`：`contract`、`collision`、`duplicate`、`superseded`、`collision_existing`、`fx_missing`、`quality`。
- 寫入：`replaceWhere batch_id = '<batch_id>'`，先清掉同一批的舊資料再寫，重跑不會變兩份，其他批不受影響。

**`BatchReconciliation`**
- `input_rows`、`fact_rows`、`quarantined_rows`、`quarantined_by_category`：這批的對帳，`balanced` 是 `input_rows == fact_rows + quarantined_rows`。
- `amount_twd_sum`、`unknown_product_rows`、`unknown_member_rows`：這批寫進 fact 的列。
- `fact_table_rows`、`fact_table_amount_twd_sum`：寫入後整張 fact，給 T6 的冪等證明。
- `member_rejected_rows`：dim_member 的違規列數（會員快照，不在訂單對帳內）。
- 筆數都用 `count()` 計算，只在 `build_spark()` 的設定下才準（見 session.py 一節）。

**T6 尚未加入**：只在 `updated_at` 較新時才覆寫、狀態機檢查、批次紀錄與依序執行。

## 測試
```bash
uv run pytest LionDEExam/submission/part_a/tests -q
```
- Delta 輸出寫到 pytest 的 `tmp_path`，不會寫進 repo。
- 時間相關的測試會先在 Spark 內用 `date_format` 轉成字串再比對。PySpark 把 timestamp collect 回 Python 時，會轉成執行機器的本地時區；Docker 容器內是 UTC，直接比對 timestamp 會讓測試失敗。
