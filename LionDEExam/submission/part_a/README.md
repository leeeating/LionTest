# Part A｜旅遊訂單資料倉

用 PySpark＋Delta 建立星型模型（fact_order、dim_member、dim_product、dim_date），先載入 `orders_base`，再依序處理三個每日增量檔，重跑結果必須一致。

> 本檔、模型說明（`model.md`）與資料品質報告（`data-quality-report.md`）的數字，都是 base → day3 四批跑完的結果；各段輸出以該段標示的執行日期與 commit 為準（§7 冪等證明已於 2026-10-25 以 9f9d415 重跑確認，結論與各表 hash 不變）。

## 目錄

- [1. 進度](#1-進度)
- [2. 怎麼跑](#2-怎麼跑)
  - [2.1 本機](#21-本機)
  - [2.2 Docker](#22-docker)
- [3. 檔案結構](#3-檔案結構)
- [4. 設計重點](#4-設計重點)
  - [4.1 來源讀取：介面＋schema 合約](#41-來源讀取介面schema-合約)
  - [4.2 時區](#42-時區)
  - [4.3 dim_product](#43-dim_product)
  - [4.4 dim_date](#44-dim_date)
  - [4.5 dim_member](#45-dim_member)
  - [4.6 fact_order、隔離表、對帳](#46-fact_order隔離表對帳)
  - [4.7 Delta CHECK 約束](#47-delta-check-約束)
  - [4.8 排除待確認清單後的金額總和](#48-排除待確認清單後的金額總和)
- [5. 星型模型](#5-星型模型)
- [6. 增量處理策略](#6-增量處理策略)
  - [6.1 執行方式](#61-執行方式)
  - [6.2 每種狀況的處理](#62-每種狀況的處理)
  - [6.3 三天實跑的對帳](#63-三天實跑的對帳)
  - [6.4 中途當掉與重跑](#64-中途當掉與重跑)
  - [6.5 隔離後的人工處理](#65-隔離後的人工處理)
- [7. 冪等證明](#7-冪等證明)
- [8. 資料品質報告](#8-資料品質報告)
- [9. 已知限制](#9-已知限制)
- [10. 相關決策](#10-相關決策)

## 1. 進度
| 項目 | 狀態 |
|---|---|
| 環境（Docker） | 完成 |
| 共用設定、來源讀取、dim_date、dim_product（T3） | 完成（獨立驗收通過） |
| dim_member SCD2（T4） | 完成（獨立驗收通過） |
| fact_order 初始載入、隔離表、對帳（T5） | 完成（獨立驗收通過） |
| 增量處理與冪等證明（T6） | 完成（獨立驗收通過，見 `notes/part_a/t6-review-findings.md`） |
| 文件（T7） | 本檔、`model.md`、`data-quality-report.md` 已更新到四批跑完的現況；資料品質報告的修正待重新獨立驗收 |

## 2. 怎麼跑

### 2.1 本機
需要 Java 17 與 [uv](https://docs.astral.sh/uv/)。在 repo 根目錄：

```bash
uv sync
# 依序跑 base → day1 → day2 → day3，印出每批對帳；已完成的批次會跳過
cd LionDEExam/submission/part_a
uv run python -m pipeline.run --out /tmp/liontest/wh
# 資料目錄預設是 repo 內的 candidate_package/dataset，可用 --data-dir 或 LIONTEST_DATA_DIR 指定
```

測試（在 repo 根目錄）：
```bash
uv run pytest LionDEExam/submission/part_a/tests -q -m "not slow"   # 只跑快的
uv run pytest LionDEExam/submission/part_a/tests -q                  # 全套
```

冪等證明（約 5 分鐘）：
```bash
uv run python LionDEExam/submission/part_a/profiling/idempotency_proof.py
```

### 2.2 Docker
```bash
docker build -t liontest-parta .
docker run --rm --network none --hostname localhost liontest-parta
```
image 建置時已經下載好 Delta 的 jar，執行時不需要連網（用 `--network none` 時要加 `--hostname localhost`）。CMD 是 `python -m pipeline.run`。資料目錄與輸出目錄用環境變數指定，預設是 image 內的 `/app/LionDEExam/candidate_package/dataset` 與 `/app/warehouse`。要把結果留在本機，就掛載目錄，例如：

```bash
docker run --rm --network none --hostname localhost \
  -v "$PWD/out:/out" -e LIONTEST_OUT=/out liontest-parta
```

## 3. 檔案結構
```
part_a/
├── pipeline/          管線程式
│   ├── session.py     SparkSession 共用設定（Delta、時區 Asia/Taipei）
│   ├── contracts.py   各來源的 schema 合約（StructType 常數，唯一一份）
│   ├── sources.py     來源讀取介面與 CSV 實作（檔案層級檢查）
│   ├── validation.py  轉成合約型別、分出違規列（列層級檢查）
│   ├── timeparse.py   來源時間字串的格式定義與解析
│   ├── delta_io.py    Delta 表的 MERGE 寫入、CHECK 約束
│   ├── dim_member.py  dim_member（SCD Type 2）、會員隔離表
│   ├── dims.py        dim_product、dim_date
│   ├── order_status.py        訂單狀態機的規則（合法轉移、可達性）
│   ├── order_status_check.py  一批事件的狀態機分類
│   ├── categories.py  隔離表的分類（唯一一份）
│   ├── batch_log.py   批次紀錄（依序、已完成就跳過）
│   ├── fact_order.py  一批訂單的處理入口：fact_order、隔離表、對帳；run_all
│   └── run.py         命令列入口
├── tests/             pytest
└── profiling/         來源資料剖析腳本、品質查詢、冪等證明腳本
```

## 4. 設計重點

### 4.1 來源讀取：介面＋schema 合約
來源抽成介面 `SourceReader`，目前只實作 `CsvSource`；源頭日後換成 SQL DB，只需要換這一層（ADR-02）。

- 每個來源的欄名、型別、是否必填都寫成常數（合約），不用 Spark 自動推斷型別。
- 讀取時所有欄位一律先讀成原始字串，再由 `cast_to_contract()` 依合約轉型。格式不一致、要等後面步驟解析的欄位（例如 `order_created_at` 混用三種時間格式），合約本身就是字串。
- 違規分兩層處理（已定案）：
  - **檔案層級**（檔案不存在、表頭與合約不符、沒有資料列）：讀取時整批停下並報錯，不寫入任何東西。
  - **列層級**（型別轉不過、Decimal 小數位超過合約位數、必填欄位空值或只有空白、欄位數不符、下單時間或更新時間不是三種可解析格式之一、值不在允許範圍、金額不大於 0）：該列分到 rejected 並記下原因，其他列照常處理。rejected 不是丟掉，筆數守恆「輸入＝valid＋rejected」，之後用來對帳。
- 判斷違規只看原始字串，不靠 Spark 的轉型結果：Spark 會把 `100.456` 四捨五入成 `100.46`、把 `1e2` 轉成 `100.00`，都不報錯。科學記號算違規，因為上游 DB 匯出的金額應是一般十進位寫法，出現科學記號代表中間經過浮點數轉換。
- **允許值**：`order_status` 只能是 4 種狀態（清單和狀態機共用同一份），`currency` 只能是 TWD、NTD、USD、JPY（實查四個訂單檔得到；NTD 是 TWD 的別名，保留並以匯率 1 換算）。大小寫、空白不同都算違規。〔防護性設計：本資料 0 筆〕
- **金額必須大於 0**（V1，使用者定：「負數在合約層就該擋下」）：base 有 50 列負數金額，以「amount:必須大於 0」隔離，不進 fact。
- **coupon 不可為 -1 以外的負數**（使用者定 B：「負數 coupon 沒有合理解釋」）：以「coupon_discount:必須大於或等於 0（-1.00 除外）」隔離；-1 代表未知，照 V3 轉 NULL。〔防護性設計：本資料 0 筆〕
- 目前資料以這份合約檢查，只有上述 50 列被分到 rejected；其他已知的品質問題（NTD、N/A、coupon -1.0 等）在合約之外，由後面的步驟處理。

### 4.2 時區
SparkSession 固定 `spark.sql.session.timeZone=Asia/Taipei`。下單時間有三種格式，解析規則如下（`parse_source_timestamp()`）：

| 格式 | 解讀 |
|---|---|
| `+08:00` | 照標記 |
| 結尾 `Z` | UTC，換算成台北時間 |
| `YYYY/MM/DD HH:MM:SS`，沒有時區標記 | 台北時間 |

推論的證據見 `notes/part_a/schema-inference/order-time.md`。

### 4.3 dim_product
- Type 1：主檔只有一份，不保留歷史。
- 代理鍵 `product_sk` 用 product_id 的 hash 計算，重跑結果不變。
- 主檔的 product_id 重複時整批停下報錯，不任選一列。
- 另外加一列「未知產品」（`product_sk = -1`），訂單的 product_id 在主檔中找不到時對應到這列。

### 4.4 dim_date
`date_sk` 用 yyyymmdd 格式的整數。日期範圍不寫死，從呼叫端傳入的訂單算出，涵蓋其中所有下單日和出發日（base＋三天增量全部處理完是 2026-05-01～2026-10-30）。逐日處理時，每一批只補上新出現的日期，既有日期不變。

### 4.5 dim_member
會員資料是三批快照（04-30 全量、05-31、06-30），後兩批放的是會員當時的完整樣子，不一定有變動。

- **SCD Type 2**：等級、縣市改變就開新版本；姓名、生日是更正，直接覆寫所有版本。
- **第一版從 register_date 開始**：訂單可能早於第一次快照，也要對得到版本。之後的版本從觀察到變動的那一批 extract_date 開始，因為實際變動日落在兩次快照之間，資料推不出來。
- **同日兩列取較高等級**（30 位會員）。
- **假值不蓋真值**：`N/A`、`1900-01-01` 轉成 NULL，不會蓋掉之前已知的縣市或生日。
- **代理鍵用 hash(member_id, valid_from)**，重跑穩定；fact 依台北下單日對到當時有效的版本。
- **對不到會員版本的訂單進隔離表，不落 -1**（使用者定：「在訂單重要度之後是會員資料 如果有未知會員資料在做客戶分析是一件困難的事 所以要有錯誤提醒修正data pipline」）。所以 dim_member 沒有「未知會員」列；和產品不同（V6：產品對不到落 -1、訂單照寫，因為商品會隨時間下架消失）。〔防護性設計：本資料 0 筆〕
- **快照的違規列進會員隔離表** `quarantine_member`（等級不在清單、註冊日晚於快照日、格式錯誤等；使用者定：另開一張，和訂單隔離表分開，「根據DE的慣例」）：保留原始字串與原因，以快照日（`extract_date`）replaceWhere，每批重讀同一份 members.csv 也只留一份。壞列不參與建版本，不會蓋掉該會員上一個好版本；會員第一次出現就是壞列時沒有任何版本，他的訂單會依上一條進訂單隔離表。〔防護性設計：本資料 0 筆〕
- 三批處理完是 8,000 位會員、8,772 個版本（772 人有 2 個版本）。

### 4.6 fact_order、隔離表、對帳
- **一批一次呼叫**：`load_order_batch()` 依序更新維度、寫 fact_order 與隔離表、回傳對帳結果。base 是第一批（`load_base()`），每日增量用同一個函式逐日呼叫（`load_incremental()`），`run_all()` 用批次紀錄依序跑完。轉換步驟集中在 `transform_order_batch()`，不寫 Delta，測試直接驗它。
- **一張訂單一列、存最新狀態**，以 order_id MERGE（ADR-04）。
- **重複列（V7）**：同一 order_id 依 updated_at 排序，**時間上相鄰**而且除了 updated_at 以外全同的列才算重複，保留 updated_at 最新的一列，其餘以 `duplicate` 進隔離表。中間夾著其他內容的相同列不算重複（使用者定：「中間如果有出現其他狀態 不能當作延遲」），和內容不同的同 order_id 列一起交給狀態機（見「增量處理策略」）。下單時間比較換算後的時刻，所以格式不同（`Z`、`+08:00`、無時區）但同一時刻的 8 組仍算重複。
- **撞號**：同一 order_id 但會員、下單時間、金額任一不同，整組進隔離表（ADR-03）。同批內、以及和既有 fact 比較都適用。
- **金額**：存原幣別 `amount`（折扣前，J10）、原始 `currency`、`amount_twd`、`net_amount_twd`（＝`amount_twd − coupon_discount`，coupon 是台幣；coupon 為 NULL 時 net 也是 NULL）。`amount_twd` 用台北下單日當天的匯率；TWD、NTD 固定 1，匯率表用 left join，TWD 訂單不會因為匯率表沒有 TWD 而遺失（Part B 審查的 `buggy_pipeline.py` 用 inner join 弄丟了全部 TWD 訂單）。其他幣別找不到當天匯率就進隔離表，不拿前一天的匯率代替。
- **參考資料有問題就整批停**：產品清單有違規列或 product_id 重複、匯率表有違規列或同日同幣別重複時，在寫任何表之前報錯（一律是 `ReferenceDataError`）。
- **產品對不到落 -1**：product_id 不在清單時 `product_sk`＝-1，訂單照寫，對帳另列筆數（V6）。
- **會員對不到版本進隔離表**（`member_missing`）：會員不在快照、或下單日早於他的第一個版本時，整列進隔離表，原因分這兩種寫明；不落 -1。〔防護性設計：本資料 0 筆〕
- **隔離表**：一張 Delta 表，每列有 batch_id、上游送來的原始字串、隔離類別與原因；以 replaceWhere 清掉同一批再寫，重跑不會變兩份。略過的晚到事件（`late_event`）也留在這裡，對帳時和隔離分開算。
- **對帳**：每批證明「輸入＝寫進 fact＋隔離＋略過」，另附 amount_twd 與 net_amount_twd 總和（checksum）、product 落到 -1 的筆數、會員對不到而隔離的筆數、會員快照違規列數、跳過中間狀態的筆數、coupon 轉 NULL 的筆數、金額人工確認清單筆數；不平就在寫入前報錯。
- **截止日**：會員快照截止在 06-30；base 訂單的下單日都在 06-30 以前，但狀態最晚更新到 07-03（2,265 列的 updated_at 落在 07-01～07-03）。會員依下單日對版本，所以 base 的 as_of 用 06-30。dim_date 只依這批訂單擴充，base 跑完是 05-01～10-27。
- **A-3 品質問題的處理**（使用者定案，見 process-log）：
  - V1 負數金額：合約擋下，進隔離表（`contract`）。
  - V3 coupon -1.0：代表「未知」，轉成 NULL，訂單照常寫入；轉了幾筆記在對帳（`coupon_nulled_rows`）。
  - V2 疑似多乘 1,000：照原樣寫入 fact，另外列進人工確認清單 `amount_review`（Delta 表，依 batch_id replaceWhere）。判斷用比值 `amount_twd ÷（產品定價 × 數量）`：正常列落在 0.84～1.29，比值大於 100 的列入清單。fact 的 amount_twd 總和包含這些列（這 40 列約佔 base 金額總和的 28%，見資料品質報告），所以下游在人工確認前要排除清單上的訂單（見「排除待確認清單後的金額總和」）。產品落到 -1 時沒有定價，算不出比值，不列入。
  - coupon 大於 amount_twd（net_amount_twd 為負）：照原樣寫入 fact，同樣列進 `amount_review`（使用者定 B：「太大的可能是全額折抵」）。清單每張單一列，`review_reasons` 記命中的原因，兩種都中時兩個都列。〔防護性設計：本資料 0 筆〕
  - coupon 為 -1 以外的負數：合約擋下，進隔離表（`contract`）。〔防護性設計：本資料 0 筆〕
  - completed 但出發日未到等：只記錄，照原樣寫入。
  - 品質規則的掛載點 `ORDER_QUALITY_RULES` 保留，目前沒有規則。

base 實跑結果（四批的完整對帳見「增量處理策略」）：

| 項目 | 筆數 |
|---|---|
| 輸入 | 100,040 |
| 寫進 fact | 99,950 |
| 隔離：金額不大於 0（V1，合約） | 50 |
| 隔離：重複（V7） | 40 |
| 隔離：撞號、找不到匯率、其他合約違規 | 0 |
| coupon -1.0 轉 NULL（V3，寫進 fact 的列） | 299 |
| V2 人工確認清單 | 40 |
| product_sk＝-1 | 120 |
| 隔離：會員對不到版本（`member_missing`） | 0 |
| 會員快照違規列（會員隔離表） | 0 |
| amount_twd 總和 | 35,969,473,520.09 |
| net_amount_twd 總和（coupon 為 NULL 的列不計） | 35,783,693,189.25 |

### 4.7 Delta CHECK 約束
fact_order 建表時加上 Delta CHECK 約束，只加在關鍵欄位，當最後一道防線（使用者定：「Delta CHECK 是最後一道防線，擋得住繞過管線的寫入」）。〔防護性設計：本資料 0 筆〕

| 約束 | 條件 |
|---|---|
| `order_id_not_null` | `order_id IS NOT NULL` |
| `amount_positive` | `amount > 0` |
| `coupon_discount_non_negative` | `coupon_discount IS NULL OR coupon_discount >= 0` |
| `order_status_valid` | `order_status IN (...)`，由狀態清單 `order_status.STATUSES` 產生 |
| `currency_valid` | `currency IN (...)`，由幣別清單 `contracts.ORDER_CURRENCIES` 產生 |
| `member_sk_not_null` | `member_sk IS NOT NULL` |

- 管線本身在合約層和對維度時已經擋下這些值，正常寫入不會觸發；約束存在表本身，擋的是 notebook 直接寫入、手動 `UPDATE` 這類繞過管線的寫入，違反時整次寫入失敗。
- 建表時先建空表、加約束，再寫入第一批資料；重跑時約束已存在且條件相同就不動，所以冪等。
- 只加在 fact_order：維度表由管線從參考資料重算，隔離表與金額人工確認清單本來就放有問題的列。
- 測試：繞過管線直接 append 一列違規資料到 fact，六個約束各自擋下（`test_fact_check_constraints_reject_writes_that_bypass_pipeline`）。

### 4.8 排除待確認清單後的金額總和
金額人工確認清單 `amount_review` 上的訂單仍寫在 fact（V2 照原樣寫入）；使用者定 B1：下游在人工確認前排除清單上的訂單（不論原因是疑似多乘 1,000 或折扣大於金額），理由：「因為已經有前面指標進入隔離我認為就應該人工審查後在進入下流」。管線提供一段查詢，算出排除清單前後的 `amount_twd` 總和。

- **範圍**：fact 所有訂單狀態（含 cancelled）、折扣前的 `amount_twd`。只照實描述這兩個數字怎麼算，不是「營收」的定義。
- **營收的定義**（是否含取消單、用折扣前或折扣後）由下游語意層決定，見 Part C。
- 清單依批次 replaceWhere，同一張單可能出現在不只一批的清單，所以先 `DISTINCT order_id` 再排除。
- 不另建表或 view：一段查詢就算得出來；`run.py` 結束時會印出這兩個數字（`fact_order.amount_totals()`，跑的是同一段 SQL `AMOUNT_EXCLUDING_REVIEW_SQL`）。

查詢（Spark SQL 讀 Delta；`<out>` 換成 `--out` 指定的輸出目錄）：

```sql
SELECT
  SUM(f.amount_twd) AS amount_twd_total,
  SUM(CASE WHEN r.order_id IS NULL THEN f.amount_twd END) AS amount_twd_excluding_review,
  COUNT(r.order_id) AS review_orders
FROM delta.`<out>/fact_order` AS f
LEFT JOIN (SELECT DISTINCT order_id FROM delta.`<out>/amount_review`) AS r
  ON f.order_id = r.order_id
```

執行方式（在 repo 根目錄）：

```bash
PYTHONPATH=LionDEExam/submission/part_a uv run python -c "
from pipeline.fact_order import AMOUNT_EXCLUDING_REVIEW_SQL
from pipeline.session import build_spark
spark = build_spark(app_name='amount-totals')
spark.sql(AMOUNT_EXCLUDING_REVIEW_SQL.format(fact_order='<out>/fact_order', amount_review='<out>/amount_review')).show(truncate=False)
"
```

三天跑完（base → day3）的結果（`python -m pipeline.run` 實跑，2026-10-24；上面的查詢讀同一個倉儲結果相同）：

| 項目 | 金額（TWD） |
|---|---|
| fact 全表 amount_twd 總和（所有狀態、折扣前） | 39,086,896,780.27 |
| 排除待確認清單上 40 張後的總和 | 28,984,405,090.57 |
| 差額（清單上訂單的 amount_twd） | 10,102,491,689.70 |

## 5. 星型模型
見 [`model.md`](model.md)：模型圖、各表粒度與欄位、dim_member SCD2 規則、fact 怎麼接維度、金額換算、已知限制。數字是 base → day3 四批跑完的結果；欄位與 SCD2 的例子另有註明量測時點。

## 6. 增量處理策略

### 6.1 執行方式
- **一個檔案＝一批**，依序處理 base → day1 → day2 → day3（`run_all()`、`python -m pipeline.run`）。每批的 `as_of` 依序是 06-30、07-01、07-02、07-03：會員快照只看到 as_of 為止，dim_date 只依當批訂單擴充，不偷看之後的檔案。
- **批次紀錄**（`batch_log`）在每批**最後**寫一列，內容是對帳數字、這批訂單檔的 sha256，以及參考資料（members、products、fx_rates）各自的 sha256：
  - 已完成的批次再跑：直接跳過，回傳既有紀錄。
  - 前一批沒完成：拒絕執行（`BatchOrderError`）。會員維度靠 `last_seen_extract_date` 擋重送，順序亂掉會遺失中間那段會員歷史（見「已知限制」）。
  - 已完成的批次訂單檔被改過（sha256 不同）：丟 `SourceChangedError`，不默默跳過。〔防護性設計：本資料 0 筆〕
  - 已完成的批次參考資料和當時不同：只發警告（logging），照常跳過；參考資料是整份快照，之後的批次本來就會讀到新版本（使用者定 C）。〔防護性設計：本資料 0 筆〕
  - `--force` 強制重跑覆寫既有紀錄時，呼叫處理之前先在強制重跑紀錄 `batch_log_force` 追加一列 `started`，完成後再追加 `completed`（表設 `delta.appendOnly`，只增不改）：哪一批、什麼時候、舊／新訂單檔與參考資料的 sha256。中途當掉時只有 `started`，fact 就算已被改寫也看得出這批被 force 過（使用者定 C：「要避免訂單狀態可以被隨意修改 如果要修改需要使用 force 來紀錄」）。
- **新舊以 `updated_at` 判斷**（J6）：fact 的 MERGE 只在 `s.updated_at > t.updated_at` 時覆寫，亂序送來的舊事件不會讓狀態倒退。

### 6.2 每種狀況的處理
一張單在一批裡可能有多列。依序經過下面各關，每一列只會落在一個分類；「略過」的列也留在隔離表，但對帳時和「隔離」分開計數。

| 狀況 | 處理 | 分類 | base | day1 | day2 | day3 |
|---|---|---|---|---|---|---|
| 金額不大於 0（V1） | 隔離 | `contract` | 50 | 0 | 0 | 0 |
| 其他格式違規、狀態或幣別不在允許值 | 隔離〔防護性設計：本資料 0 筆〕 | `contract` | 0 | 0 | 0 | 0 |
| coupon 為 -1 以外的負數 | 隔離〔防護性設計：本資料 0 筆〕 | `contract` | 0 | 0 | 0 | 0 |
| 同批同 order_id，但會員、下單時間或金額不同（撞號，ADR-03） | 整組隔離 | `collision` | 0 | 6 | 2 | 4 |
| 時間上相鄰、除 `updated_at` 外完全相同（V7、同狀態重送） | 保留最新一列，其餘隔離 | `duplicate` | 40 | 15 | 15 | 15 |
| 相同的列中間夾著其他內容（例如 cancelled → paid → cancelled） | 不算重複，交給狀態機〔防護性設計：本資料 0 筆〕 | （依狀態機分類） | 0 | 0 | 0 | 0 |
| 和既有 fact 同 order_id，但會員、下單時間或金額不同 | 整組隔離 | `collision_existing` | 0 | 594 | 598 | 596 |
| 晚到事件（`updated_at` ≤ fact），舊狀態走得到 fact 現況（L4：fact 已是 cancelled，收到較舊的 paid） | 略過，fact 不變 | `late_event` | 0 | 0 | 25 | 0 |
| 晚到事件，舊狀態走不到 fact 現況 | 隔離〔防護性設計：本資料 0 筆〕 | `late_event_conflict` | 0 | 0 | 0 | 0 |
| 同批有多個比 fact 新的合法狀態 | 寫最後一個，較早的隔離〔防護性設計：本資料 0 筆〕 | `superseded` | 0 | 0 | 0 | 0 |
| 跳過中間狀態（例如 created → completed） | 合法，照寫，只計數〔防護性設計：本資料 0 筆〕 | （寫入，計數 `skipped_intermediate_rows`） | 0 | 0 | 0 | 0 |
| 往回走（例如 cancelled → paid、completed → paid） | 隔離，fact 不更新〔防護性設計：本資料 0 筆〕 | `illegal_transition` | 0 | 0 | 0 | 0 |
| 同一 order_id、同一秒、狀態不同 | 這些列全部隔離；之前的合法事件照寫〔防護性設計：本資料 0 筆〕 | `ambiguous_order` | 0 | 0 | 0 | 0 |
| 第一個不合法或同一秒衝突之後的同批事件 | 一起隔離，fact 停在最後一個合法狀態〔防護性設計：本資料 0 筆〕 | `after_illegal` | 0 | 0 | 0 | 0 |
| 下單日找不到匯率 | 隔離，不拿前一天代替〔防護性設計：本資料 0 筆〕 | `fx_missing` | 0 | 0 | 0 | 0 |
| A-3 品質規則 | 目前沒有規則 | `quality` | 0 | 0 | 0 | 0 |
| 會員對不到下單日當時的版本（不在快照，或下單日早於第一版） | 隔離，不落 -1〔防護性設計：本資料 0 筆〕 | `member_missing` | 0 | 0 | 0 | 0 |
| coupon＝-1.0（V3，代表未知） | 轉 NULL，照常寫入，只計數 | （寫入，計數 `coupon_nulled_rows`） | 299 | 0 | 0 | 0 |
| 金額比值 > 100（V2，疑似多乘 1,000） | 照常寫入，另列人工確認清單 `amount_review` | （寫入，計數 `amount_review_rows`） | 40 | 0 | 0 | 0 |
| coupon > amount_twd（net 為負） | 照常寫入，另列人工確認清單 `amount_review`〔防護性設計：本資料 0 筆〕 | （寫入，計數 `amount_review_rows`） | 0 | 0 | 0 | 0 |

狀態機的判斷全部用**可達性**（這個狀態能不能經過 0 步以上走到那個狀態），不用一步轉移表。原因是無法確定上游送的是事件還是快照，兩次快照之間的中間狀態可能沒拍到。合法的一步轉移只有 created→paid、created→cancelled、paid→cancelled、paid→completed（假設流程單向，見 `notes/part_a/order-state-machine.md`）。

### 6.3 三天實跑的對帳
`python -m pipeline.run` 的輸出（2026-10-19；2026-10-24 改成會員對不到進隔離表後重跑，數字相同）：

| 批次 | 輸入 | 寫進 fact | 隔離 | 略過 | 跳過中間狀態 | coupon 轉 NULL | 金額人工確認清單 | product -1 | 會員對不到（隔離） | 本批 amount_twd | 本批 net_amount_twd |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base | 100,040 | 99,950 | 90 | 0 | 0 | 299 | 40 | 120 | 0 | 35,969,473,520.09 | 35,783,693,189.25 |
| day1 | 4,615 | 4,000 | 615 | 0 | 0 | 0 | 0 | 0 | 0 | 1,056,883,370.88 | 1,055,002,970.88 |
| day2 | 4,700 | 4,060 | 615 | 25 | 0 | 0 | 0 | 0 | 0 | 1,039,558,224.11 | 1,037,651,074.11 |
| day3 | 4,615 | 4,000 | 615 | 0 | 0 | 0 | 0 | 0 | 0 | 1,020,981,665.19 | 1,019,042,815.19 |

寫入後的 fact 全表：

| 批次之後 | 列數 | amount_twd 總和 | net_amount_twd 總和 |
|---|---|---|---|
| base | 99,950 | 35,969,473,520.09 | 35,783,693,189.25 |
| day1 | 103,950 | 37,026,356,890.97 | 36,838,696,160.13 |
| day2 | 108,010 | 38,065,915,115.08 | 37,876,347,234.24 |
| day3 | 112,010 | 39,086,896,780.27 | 38,895,390,049.43 |

- 每批都平衡：輸入＝寫進 fact＋隔離＋略過。
- 三天寫進 fact 的 12,060 列都是新訂單，fact 全表每批正好增加同樣的筆數。增量檔裡和 base 同 order_id 的列，會員、下單時間或金額都不同，全部以撞號隔離；所以 base 中 `updated_at` 落在 07-01～07-03 的列，沒有被增量的舊事件改回去。
- L4 的 25 張單：day1 寫入 cancelled，day2 送來較舊的 paid，被判為晚到事件並略過，fact 最後仍是 cancelled。
- net_amount_twd 總和比 amount_twd 少的部分是 coupon 折扣；coupon 為 NULL（原本是 -1.0）的列 net 也是 NULL，不計入總和。
- 以上數字由 `tests/test_fact_order_incremental.py` 用純 Python 依同樣規則獨立計算（`tests/reference_model.py`）比對，結果一致。

### 6.4 中途當掉與重跑
- 寫入順序：維度 → 隔離表（replaceWhere 同一批）→ fact（MERGE）→ 批次紀錄。任何一步當掉，批次紀錄都不會寫，下次重跑整批。
- 重跑時，fact 可能已經寫入這批的結果。如果直接拿來比，這批每列都會變成晚到事件，分類和第一次不同。所以撞號和狀態機都和「這批開始之前」的 fact 比：每批第一次開始、還沒寫任何 fact 或隔離表之前，先把當時 fact 的 Delta 版本記在 `batch_start` 表；重跑（當掉後或 `--force`）時沿用記下的版本，用 time travel 讀出來。
- 為什麼不從 Delta history 找這批的 commit：這批寫進 fact 的列是 0 時（例如整批都不合法），MERGE 不會產生 commit，history 裡就沒有這批的痕跡（T6 驗收找到的漏洞）。
- 每次 MERGE fact 仍會在 commit 的 `userMetadata` 標上 `batch:<batch_id>`，只作為稽核，看得出哪一批寫了哪個版本。

### 6.5 隔離後的人工處理
管線只負責第一步（列出問題），後面兩步是營運流程：

1. **列出問題**：隔離表保留上游送來的原始字串、分類與原因；每批的對帳數字有各分類的筆數，也寫進批次紀錄。正式環境應在 `illegal_transition`、`ambiguous_order`、`late_event_conflict`、`collision*` 出現時告警。
2. **查上游**：依 order_id 回上游系統確認實際狀態。
3. **修正**：建議由上游重送一筆 `updated_at` 較新的正確事件，管線照常處理；上游無法重送時，另建人工修正表，由管線在處理增量時套用。人工修正表目前沒有實作。

## 7. 冪等證明
「同一批跑兩次結果相同」不能只看 Delta history 的 operationMetrics：MERGE 重寫同樣的值也會算成 updated。所以直接比內容：fact 筆數、amount_twd 與 net_amount_twd 總和，以及 fact、隔離表、金額人工確認清單（amount_review）、會員隔離表（quarantine_member）、dim_member、dim_product、dim_date 七張表的整表內容 hash，再加上該批的對帳數字。整表 hash 的算法是每列轉成 JSON 取 sha256，排序後再整體取 sha256，與列順序、檔案切法無關。

腳本：`profiling/idempotency_proof.py`。兩個實驗：

1. **強制重跑**：跑完 base → day3 後，每個增量檔用 `force=True` 再實際跑一次（不被批次紀錄跳過），和第一次的結果比。對帳數字不比「寫入當下的整表欄位」（`fact_table_*`）：在 day3 之後重跑 day1，整表本來就比第一次跑 day1 時大。
2. **中途當掉**：另一個倉儲跑完 base → day2，接著處理 day3：第一次在隔離表已寫、MERGE fact 之前當掉；重跑又在 MERGE fact 之後、寫批次紀錄之前當掉；第三次正常完成。每個時點都確認沒有 day3 的批次紀錄，最後和沒當掉的倉儲比。

輸出（本機，2026-10-24；2026-10-25 以 HEAD 9f9d415 重跑，結論「全部相同」、各表 hash 與下列一致）：

**實驗 1：每個增量檔強制重跑一次（force=True，實際執行）**

| 時點 | fact 筆數 | amount_twd 總和 | net_amount_twd 總和 | fact hash | 隔離表筆數 | 隔離表 hash | 金額人工確認清單 hash | 會員隔離表 hash | 維度表 hash（member/product/date） | 該批對帳數字與第一次相同 |
|---|---|---|---|---|---|---|---|---|---|---|
| 第一次跑完 base→day3 | 112,010 | 39086896780.27 | 38895390049.43 | 6c54abe0bd61 | 1,960 | 507b615cb601 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/5114d583 | — |
| 重跑 day1 之後 | 112,010 | 39086896780.27 | 38895390049.43 | 6c54abe0bd61 | 1,960 | 507b615cb601 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/5114d583 | 是 |
| 重跑 day2 之後 | 112,010 | 39086896780.27 | 38895390049.43 | 6c54abe0bd61 | 1,960 | 507b615cb601 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/5114d583 | 是 |
| 重跑 day3 之後 | 112,010 | 39086896780.27 | 38895390049.43 | 6c54abe0bd61 | 1,960 | 507b615cb601 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/5114d583 | 是 |

**實驗 2：day3 在 MERGE 前當掉、重跑又在 MERGE 後當掉，第三次完成**

| 時點 | fact 筆數 | amount_twd 總和 | net_amount_twd 總和 | fact hash | 隔離表筆數 | 隔離表 hash | 金額人工確認清單 hash | 會員隔離表 hash | 維度表 hash（member/product/date） | day3 對帳數字與沒當掉時相同 |
|---|---|---|---|---|---|---|---|---|---|---|
| 當掉前（base→day2 跑完） | 108,010 | 38065915115.08 | 37876347234.24 | a672a4260958 | 1,345 | 62e321926a03 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/bc81004b | — |
| 第一次：MERGE 前當掉（批次紀錄：無；fact 未變） | 108,010 | 38065915115.08 | 37876347234.24 | a672a4260958 | 1,960 | 507b615cb601 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/5114d583 | — |
| 第二次：MERGE 後當掉（批次紀錄：無） | 112,010 | 39086896780.27 | 38895390049.43 | 6c54abe0bd61 | 1,960 | 507b615cb601 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/5114d583 | — |
| 第三次：重跑完成 | 112,010 | 39086896780.27 | 38895390049.43 | 6c54abe0bd61 | 1,960 | 507b615cb601 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/5114d583 | 是 |
| 對照：倉儲 A 沒當掉 | 112,010 | 39086896780.27 | 38895390049.43 | 6c54abe0bd61 | 1,960 | 507b615cb601 | bc8770de6dd1 | e3b0c44298fc | 765611be/461e56f0/5114d583 | — |

結論：全部相同（hash 只顯示前 12 碼，維度表前 8 碼）

會員隔離表的 hash `e3b0c44298fc` 是空表的 sha256（本資料 0 筆違規列）；dim_member 的 hash 和 2026-10-19 那次不同，是因為拿掉了未知會員列。

平常的重跑則由批次紀錄直接跳過，不會重新執行（`tests/test_fact_order_incremental.py` 的 `test_incremental_run_all_again_skips_every_batch`）。

## 8. 資料品質報告
見 [`data-quality-report.md`](data-quality-report.md)：每個問題的描述、影響筆數、偵測查詢與輸出、處理決策與理由。查詢腳本在 `profiling/data_quality_queries.py`。

## 9. 已知限制
- **schema 變動後需重建倉儲**：沒有做 schema 遷移。例如批次紀錄新增 `reference_sha256`、金額人工確認清單新增三欄之後，用舊版程式建好的倉儲不能直接接著跑（MERGE、replaceWhere 會因 schema 不符失敗），要刪掉輸出目錄重跑。拿掉「未知會員」列之後也一樣：舊倉儲的 dim_member 還留著 -1 那列（MERGE 不刪列），要重建。
- **會員隔離表清不掉「改了快照日」的舊列**〔防護性設計：本資料 0 筆〕：會員隔離表以這次讀到的 `extract_date` replaceWhere。上游修的是 `extract_date` 本身（例如 `2026-13-40` 改成 `2026-04-30`），或整份快照從 members.csv 消失時，舊值不會再被讀到，它的隔離列會留在表裡，要人工刪。不影響 dim_member。
- **既有訂單的後續事件可能被隔離成 `member_missing`**〔防護性設計：本資料 0 筆〕：會員對版本用的是「這批」讀到的 dim_member。訂單第一次寫進 fact 時對得到會員，之後如果 dim_member 變了（例如會員快照被上游改掉、倉儲重建時少了某位會員），同一張訂單後續的狀態事件會對不到會員而進隔離表，fact 停在舊狀態。
- **會員快照必須依日期順序處理**：dim_member 用 `last_seen_extract_date` 擋掉重送的舊快照，判斷以會員為單位。如果 05-31 的快照比 06-30 晚送到，兩批都出現的會員，05-31 那一版會被跳過，中間那段歷史會遺失（例如 05-31 升金卡、06-30 降回一般，表裡看不到金卡那一版）。管線靠批次紀錄強制依序處理來避免：前一批沒完成就拒絕跑下一批（`BatchOrderError`）。本題資料沒有同時出現在 05-31 與 06-30 的會員，所以目前的結果不受影響。

- **重跑依賴 Delta time travel，有保存期限**：當掉後重跑、`--force` 重跑都要讀「這批開始之前」的 fact 版本。對 fact 執行 VACUUM 後，舊版本的資料檔被刪掉，這時重跑會直接報錯（不會默默算錯）；超過 Delta log 的保存期限（`delta.logRetentionDuration`，預設 30 天）後，舊版本也讀不到。正式環境要讓重跑的時間窗短於保存期限，或在 VACUUM 前確認沒有待重跑的批次。
- **`--force` 不比對來源 checksum**：一般重跑時，已完成的批次來源被改過會報錯；`--force` 則直接用目前的來源檔重跑並覆寫這批的結果，不檢查來源是否被改過。只在確定要重算時使用。覆寫會留在強制重跑紀錄 `batch_log_force`（舊／新 sha256；中途當掉也有 `started` 那一列），但被覆寫前的對帳數字不另存，要看舊數字得用 Delta time travel 讀 `batch_log` 的舊版本。
- **讀取層比 Spark 直接轉型慢**：為了不讓髒值被悄悄改掉，所有欄位先讀成字串，再由 `cast_to_contract()` 逐列檢查，時間花在 regex 檢查與轉型。改之前合格、隔離兩邊各算一次：實測 200 萬列（8 核本機，量測時有其他程式同時執行），直接轉型的讀法 `count()` 0.64 秒、讀全部欄位 3.55 秒，當時的讀法兩者都約 31 秒。commit 92b8d85 改成每列的違規原因只算一次（`localCheckpoint`）再拆成合格與隔離：`cast_to_contract` 單獨實測快 2.2～2.8 倍，整個 base 批次快 20～30%（3 次，見 `notes/part_a/t6-review-findings.md`）；200 萬列沒有在改之後重量。仍比直接轉型慢，本題 10 萬列影響可以忽略；正式環境到數千萬列時可能是瓶頸（未實測）。合併 regex 是另一個可行的優化方向，目前沒做，效果也未驗證。

## 10. 相關決策
- `decisions/ADR-01`～`ADR-04`（皆已定案）：
  - ADR-01 執行引擎選 PySpark＋Delta
  - ADR-02 讀取來源抽成介面，品質規則寫成 schema 合約
  - ADR-03 增量檔與 base 撞號的列當 noise，進隔離表
  - ADR-04 fact_order 一張訂單一列，存最新狀態
- 決策過程：`ai-collab/process-log.md` 第三部分
