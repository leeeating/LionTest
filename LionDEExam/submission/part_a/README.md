# Part A｜旅遊訂單資料倉

用 PySpark＋Delta 建立星型模型（fact_order、dim_member、dim_product、dim_date），先載入 `orders_base`，再依序處理三個每日增量檔，重跑結果必須一致。

> 施工中：標「待 T6～T7」的章節還沒完成。

## 進度
| 項目 | 狀態 |
|---|---|
| 環境（Docker） | 完成 |
| 共用設定、來源讀取、dim_date、dim_product（T3） | 完成（獨立驗收通過） |
| dim_member SCD2（T4） | 完成（獨立驗收通過） |
| fact_order 初始載入、隔離表、對帳（T5） | 完成（獨立驗收通過） |
| 增量處理與冪等證明（T6） | 進行中 |
| 文件（T7） | 本檔撰寫中 |

## 怎麼跑

### 本機
需要 Java 17 與 [uv](https://docs.astral.sh/uv/)。在 repo 根目錄：

```bash
uv sync
uv run pytest LionDEExam/submission/part_a/tests -q
```

### Docker
```bash
docker build -t liontest-parta .
```
image 建置時已經下載好 Delta 的 jar，執行時不需要連網。容器內的完整管線指令待 T6 完成後補上。

## 目錄
```
part_a/
├── pipeline/          管線程式
│   ├── session.py     SparkSession 共用設定（Delta、時區 Asia/Taipei）
│   ├── contracts.py   各來源的 schema 合約（StructType 常數，唯一一份）
│   ├── sources.py     來源讀取介面與 CSV 實作（檔案層級檢查）
│   ├── validation.py  轉成合約型別、分出違規列（列層級檢查）
│   ├── timeparse.py   來源時間字串的格式定義與解析
│   ├── delta_io.py    Delta 表的 MERGE 寫入
│   ├── dim_member.py  dim_member（SCD Type 2）
│   ├── dims.py        dim_product、dim_date
│   └── fact_order.py  一批訂單的處理入口：fact_order、隔離表、對帳
├── tests/             pytest
└── profiling/         來源資料剖析腳本（推測 schema 時使用）
```

## 設計重點

### 來源讀取：介面＋schema 合約
來源抽成介面 `SourceReader`，目前只實作 `CsvSource`；源頭日後換成 SQL DB，只需要換這一層（ADR-02）。

- 每個來源的欄名、型別、是否必填都寫成常數（合約），不用 Spark 自動推斷型別。
- 讀取時所有欄位一律先讀成原始字串，再由 `cast_to_contract()` 依合約轉型。格式不一致、要等後面步驟解析的欄位（例如 `order_created_at` 混用三種時間格式），合約本身就是字串。
- 違規分兩層處理（已定案）：
  - **檔案層級**（檔案不存在、表頭與合約不符、沒有資料列）：讀取時整批停下並報錯，不寫入任何東西。
  - **列層級**（型別轉不過、Decimal 小數位超過合約位數、必填欄位空值或只有空白、欄位數不符、下單時間或更新時間不是三種可解析格式之一）：該列分到 rejected 並記下原因，其他列照常處理。rejected 不是丟掉，筆數守恆「輸入＝valid＋rejected」，之後用來對帳。
- 判斷違規只看原始字串，不靠 Spark 的轉型結果：Spark 會把 `100.456` 四捨五入成 `100.46`、把 `1e2` 轉成 `100.00`，都不報錯。科學記號算違規，因為上游 DB 匯出的金額應是一般十進位寫法，出現科學記號代表中間經過浮點數轉換。
- 目前資料以這份合約檢查，沒有任何列被分到 rejected；已知的品質問題（負數金額、NTD、N/A 等）都在合約之外，交給後面的清理步驟。

### 時區
SparkSession 固定 `spark.sql.session.timeZone=Asia/Taipei`。下單時間有三種格式，解析規則如下（`parse_source_timestamp()`）：

| 格式 | 解讀 |
|---|---|
| `+08:00` | 照標記 |
| 結尾 `Z` | UTC，換算成台北時間 |
| `YYYY/MM/DD HH:MM:SS`，沒有時區標記 | 台北時間 |

推論的證據見 `notes/part_a/schema-inference/order-time.md`。

### dim_product
- Type 1：主檔只有一份，不保留歷史。
- 代理鍵 `product_sk` 用 product_id 的 hash 計算，重跑結果不變。
- 主檔的 product_id 重複時整批停下報錯，不任選一列。
- 另外加一列「未知產品」（`product_sk = -1`），訂單的 product_id 在主檔中找不到時對應到這列。

### dim_date
`date_sk` 用 yyyymmdd 格式的整數。日期範圍不寫死，從呼叫端傳入的訂單算出，涵蓋其中所有下單日和出發日（base＋三天增量全部處理完是 2026-05-01～2026-10-30）。逐日處理時，每一批只補上新出現的日期，既有日期不變。

### dim_member
會員資料是三批快照（04-30 全量、05-31、06-30），後兩批放的是會員當時的完整樣子，不一定有變動。

- **SCD Type 2**：等級、縣市改變就開新版本；姓名、生日是更正，直接覆寫所有版本。
- **第一版從 register_date 開始**：訂單可能早於第一次快照，也要對得到版本。之後的版本從觀察到變動的那一批 extract_date 開始，因為實際變動日落在兩次快照之間，資料推不出來。
- **同日兩列取較高等級**（30 位會員）。
- **假值不蓋真值**：`N/A`、`1900-01-01` 轉成 NULL，不會蓋掉之前已知的縣市或生日。
- **代理鍵用 hash(member_id, valid_from)**，重跑穩定；fact 依台北下單日對到當時有效的版本，對不到的落到「未知會員」（-1）。未知會員列的 `valid_from` 是 1900-01-01、`register_date` 是 NULL，fact 對不到任何版本時直接給 -1，不靠這列的區間。
- 三批處理完是 8,000 位會員、8,772 個版本（772 人有 2 個版本），另加 1 列未知會員。

### fact_order、隔離表、對帳
- **一批一次呼叫**：`load_order_batch()` 依序更新維度、寫 fact_order 與隔離表、回傳對帳結果。base 是第一批（`load_base()`），T6 的每日增量用同一個函式逐日呼叫。
- **一張訂單一列、存最新狀態**，以 order_id MERGE（ADR-04）。
- **重複列（V7）**：同一 order_id 除了 updated_at 以外全同，保留 updated_at 最新的一列，其餘進隔離表。下單時間比較換算後的時刻，所以格式不同（`Z`、`+08:00`、無時區）但同一時刻的 8 組仍算重複。
- **撞號**：同一 order_id 但會員、下單時間、金額任一不同，整組進隔離表（ADR-03）。同批內、以及和既有 fact 比較都適用。
- **金額**：存原幣別 `amount`、原始 `currency`、`amount_twd`。`amount_twd` 用台北下單日當天的匯率；TWD、NTD 固定 1，匯率表用 left join，TWD 訂單不會因為匯率表沒有 TWD 而遺失（Part B 審查的 `buggy_pipeline.py` 用 inner join 弄丟了全部 TWD 訂單）。其他幣別找不到當天匯率就進隔離表，不拿前一天的匯率代替。
- **參考資料有問題就整批停**：產品清單有違規列或 product_id 重複、匯率表有違規列或同日同幣別重複時，在寫任何表之前報錯（一律是 `ReferenceDataError`）。
- **對不到維度落 -1**：product_id 不在清單、會員對不到版本時 sk＝-1，對帳另列筆數。
- **隔離表**：一張 Delta 表，每列有 batch_id、上游送來的原始字串、隔離類別與原因；以 replaceWhere 清掉同一批再寫，重跑不會變兩份。
- **對帳**：每批證明「輸入＝寫進 fact＋隔離」，另附 amount_twd 總和（checksum）與落到 -1 的筆數；不平就在寫入前報錯。
- **截止日**：會員快照截止在 06-30；base 訂單的下單日都在 06-30 以前，但狀態最晚更新到 07-03（2,265 列的 updated_at 落在 07-01～07-03）。會員依下單日對版本，所以 base 的 as_of 用 06-30。dim_date 只依這批訂單擴充，base 跑完是 05-01～10-27。
- **品質問題暫不處理**：負數金額、疑似 ×1000、coupon -1.0、completed 但出發日未到，目前照原樣寫進 fact，A-3 再決定；規則有固定的掛載點（`ORDER_QUALITY_RULES`）。

base 實跑結果：

| 項目 | 筆數 |
|---|---|
| 輸入 | 100,040 |
| 寫進 fact | 100,000 |
| 隔離：重複（V7） | 40 |
| 隔離：撞號、找不到匯率、合約違規 | 0 |
| product_sk＝-1 | 120 |
| member_sk＝-1 | 0 |
| amount_twd 總和 | 35,957,084,078.22 |

## 星型模型
見 [`model.md`](model.md)：模型圖、各表粒度與欄位、dim_member SCD2 規則、fact 怎麼接維度、金額換算、已知限制。數字是 base 載入後量的，三個增量檔處理完後會更新。

## 增量處理策略
待 T6。

## 冪等證明
待 T6。

## 資料品質報告
見 [`data-quality-report.md`](data-quality-report.md)（撰寫中）：每個問題的描述、影響筆數、偵測查詢與輸出、處理決策與理由。查詢腳本在 `profiling/data_quality_queries.py`。

## 已知限制
- **會員快照必須依日期順序處理**：dim_member 用 `last_seen_extract_date` 擋掉重送的舊快照，判斷以會員為單位。如果 05-31 的快照比 06-30 晚送到，兩批都出現的會員，05-31 那一版會被跳過，中間那段歷史會遺失（例如 05-31 升金卡、06-30 降回一般，表裡看不到金卡那一版）。管線靠批次紀錄強制依序處理來避免（T6）。本題資料沒有同時出現在 05-31 與 06-30 的會員，所以目前的結果不受影響。

- **讀取層比 Spark 直接轉型慢**：為了不讓髒值被悄悄改掉，所有欄位先讀成字串，再由 `cast_to_contract()` 逐列檢查。實測 200 萬列（8 核本機，量測時有其他程式同時執行）：直接轉型的讀法 `count()` 0.64 秒、讀全部欄位 3.55 秒；目前的讀法兩者都約 31 秒。時間花在 regex 檢查與轉型，而且合格、隔離兩邊各算一次。本題 10 萬列約多 2 秒，可以忽略；正式環境到數千萬列時會是瓶頸（線性外推，未實測）。可行的優化方向是檢查只算一次並 persist、合併 regex，目前沒做，效果也未驗證。

## 相關決策
- `decisions/ADR-01`～`ADR-04`（皆已定案）：
  - ADR-01 執行引擎選 PySpark＋Delta
  - ADR-02 讀取來源抽成介面，品質規則寫成 schema 合約
  - ADR-03 增量檔與 base 撞號的列當 noise，進隔離表
  - ADR-04 fact_order 一張訂單一列，存最新狀態
- 決策過程：`ai-collab/process-log.md` 第三部分
