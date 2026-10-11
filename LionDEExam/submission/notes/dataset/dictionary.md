# Dataset 資料字典（欄位層級）

回到入口：[README.md](README.md)

對象：`candidate_package/dataset/` 的 7 個 CSV。

**範圍**：這份只寫結構面，包括筆數、欄位、key、表之間的關聯、值域。值域照實際觀察列出，**不在這裡判斷是不是品質問題**，品質檢核由 Part A 的 A-3 負責。最後一節只列 Part B 已經用查詢驗證過的事實。

**數字怎麼來的**：用 Python 標準庫 `csv` 讀檔（編碼 `utf-8-sig`）統計，查詢與輸出見 `../../part_b/evidence.md` E9。官方欄位說明在 `candidate_package/README.md`，本文標「官方」的地方就是引用那份。

## 總覽

| 檔案 | 筆數 | 內容 | 粒度（一列代表什麼） |
|---|---|---|---|
| orders_base.csv | 100,040 | 訂單初始全量（官方：2026-05-01 ~ 06-30） | 一張訂單（理論上）；實測 order_id 有 100,000 種 |
| orders_incremental_day1.csv | 4,615 | 2026-07-01 增量 | 一個訂單事件（新單或狀態更新）；4,597 種 order_id |
| orders_incremental_day2.csv | 4,700 | 2026-07-02 增量 | 同上；4,684 種 order_id |
| orders_incremental_day3.csv | 4,615 | 2026-07-03 增量 | 同上；4,598 種 order_id |
| members.csv | 8,991 | 會員快照 | 一位會員在某個 extract_date 的快照；8,000 位會員 |
| products.csv | 300 | 產品主檔 | 一個產品；product_id 唯一 |
| fx_rates.csv | 134 | 每日匯率（對 TWD） | 一天 × 一種幣別；(rate_date, currency) 唯一 |

- 所有檔案開頭都有 **UTF-8 BOM**（`EF BB BF`）。讀檔工具如果不會自動略過，第一個欄位名稱前面會多出一個看不見的字元。
- 所有欄位都沒有空值（空字串筆數為 0）。

## 欄位

### orders_*.csv（base 與 3 個增量檔欄位相同）

| 欄位 | 官方說明 | 觀察到的值 |
|---|---|---|
| order_id | | `ORD` ＋ 8 位數字 |
| member_id | | `M` ＋ 6 位數字 |
| product_id | | `P` ＋ 5 位數字 |
| channel | | app、web、門市、電銷 |
| order_status | created / paid / completed / cancelled | 同官方 |
| quantity | | 1 ~ 4 |
| currency | | 增量檔：TWD、USD、JPY；base 另外有 NTD（200 筆） |
| amount | 原幣別金額 | 增量檔 83.24 ~ 4,804,065；base −3,087,159 ~ 3,738,074,000 |
| coupon_discount | **TWD** | 增量檔 0 ~ 950；base −1 ~ 950 |
| order_created_at | | 增量檔都是 `YYYY-MM-DDTHH:MM:SS+08:00`；base 另外有 `YYYY/MM/DD HH:MM:SS`（3,001 筆）和 `...Z`（3,001 筆） |
| departure_date | | 2026-05-08 ~ 2026-10-30 |
| updated_at | | 都是 `+08:00` 格式；增量檔的範圍見 [incremental.md](incremental.md) |

- 官方：增量檔中同一個 `order_id` 可能出現多次（狀態更新事件），以 `updated_at` 區分新舊。
- 增量檔的 `order_created_at` 最早到 2026-05-01，代表增量檔裡包含舊訂單的更新事件，不只有當天的新訂單。

增量檔的性質（是否為 log、`updated_at` 分布等）見 [incremental.md](incremental.md)。


#### amount 分布（依幣別）

查詢與輸出見 `part_b/evidence.md` E9。

| 檔案 | 幣別 | 筆數 | p25 | 中位數 | p75 | 最小 | 最大 |
|---|---|---|---|---|---|---|---|
| day1 | TWD | 3,069 | 99,837 | 211,208 | 390,220 | 2,762 | 975,967 |
| day1 | JPY | 524 | 433,011 | 1,013,210 | 1,973,066 | 33,438 | 4,804,065 |
| day1 | USD | 1,022 | 2,993.88 | 6,319.19 | 11,946.64 | 94.17 | 29,016.05 |
| base | TWD | 66,690 | 95,622 | 202,880 | 383,857 | −594,452 | 736,710,000 |
| base | JPY | 11,022 | 465,189 | 972,567 | 1,861,932 | −3,087,159 | 3,738,074,000 |
| base | USD | 22,128 | 3,027.64 | 6,445.57 | 12,084.64 | −27,292.7 | 18,074,850 |
| base | NTD | 200 | 106,874 | 222,601 | 408,388 | 2,798 | 916,142 |

- **增量檔乾淨**：day1～day3 沒有負數、0 或轉不成數字的值，分布幾乎相同（day2、day3 見 E9 輸出）。
- **換成台幣後量級一致**：day1 的 USD 中位數 × 31.118、JPY 中位數 × 0.20378（`fx_rates.csv` 2026-07-01 的匯率），都落在台幣 20 萬上下，和 TWD 中位數相近。
- **base 有 50 筆負數**（TWD 29、USD 17、JPY 4），沒有 0 元；這是 Part B #3 的依據。**看起來是資料錯誤，要開卡追上游**（調查見 E9）：
  - `order_status` 是 paid 19、completed 18、cancelled 7、created 6，比例和全體相近；官方 README 的狀態只有 created／paid／completed／cancelled，沒有退款或沖銷狀態，也沒說 amount 可以為負。
  - 同一個 `order_id` 在 base 沒有任何正數列，不是「原單＋沖銷單」的形態。
  - 取絕對值後，TWD 29/29、JPY 4/4、USD 16/17 落在該幣別正數列的 min～p99 之間，也就是正常訂單的金額只差一個負號。
  - 推測是正負號錯誤（未查證），和 40 筆疑似 ×1,000 一樣留給 A-3，並向上游確認負數的業務意義。
- **base 有 40 筆極端大值**（超過該幣別 p99 的兩倍：TWD 27、USD 9、JPY 4）。其中 31 筆是 1,000 的倍數，40 筆除以 1,000 後都不超過該幣別 p99 的 1.2 倍（回到正常範圍），**疑似多乘了 1,000，原因未查證**，要在 A-3 資料品質報告處理並向上游確認。
- **NTD 200 筆**的分布和 TWD 相近，是否等同 TWD 留給 A-3 檢核。
- 原管線只讀增量檔，base 的負數與極端值不影響 Part B 結論。

### members.csv

| 欄位 | 官方說明 | 觀察到的值 |
|---|---|---|
| member_id | | M000001 ~ M008000 |
| member_name | | 620 種 |
| member_level | 一般 / 銀卡 / 金卡 / 白金 | 同官方 |
| city | | 10 個縣市，另有 `N/A`（71 筆） |
| birth_date | | 1900-01-01 ~ 2003-10-17；1900-01-01 有 81 筆 |
| register_date | | 2015-01-01 ~ 2025-12-13 |
| extract_date | 快照萃取日 | 2026-04-30（8,030 筆）、05-31（459 筆）、06-30（502 筆） |

- 2026-04-30 那次快照涵蓋所有會員，之後兩次只有少數會員。看起來像「有變更才出現」，但這是推測，**未證實**。
- (member_id, extract_date) 不唯一，有 30 組重複。

### products.csv

| 欄位 | 觀察到的值 |
|---|---|
| product_id | P00001 ~ P00300，唯一 |
| product_type | 團體旅遊、機票、票券、自由行、訂房 |
| destination_country | 台灣、土耳其、日本、法國、泰國、美國、義大利、越南、韓國 |
| trip_days | 1 ~ 11 |
| base_price_twd | 10,000 ~ 99,000 |
| is_active | Y（287 筆）、N（13 筆） |

- base 有 120 筆訂單的 product_id（例如 P91064）不在產品主檔裡。增量檔的 product_id 全部都對得到。

### fx_rates.csv

| 欄位 | 觀察到的值 |
|---|---|
| rate_date | 2026-04-28 ~ 2026-07-03，連續 67 天 |
| currency | USD、JPY（**沒有 TWD**） |
| rate_to_twd | USD 30.939 ~ 31.58；JPY 0.20331 ~ 0.21094 |

## Part B 已經驗證的事實

以下每一項都附查詢輸出，在 `../../part_b/evidence.md`（依報告問題編號索引）。

| 事實 | 數字 | 對應報告問題編號（`part_b/code-review.md`「問題總表」） |
|---|---|---|
| fx 沒有 TWD | day1 有 3,069 筆 TWD 訂單（共 4,615 筆）查不到匯率 | #4 |
| 增量檔有和 base 同 order_id 的列 | day1 有 597 個 order_id（603 列）已經存在於 base，其中 485 列狀態和 base 不同；603 列的 `order_created_at`、`member_id`、`amount` 都和 base 不同（與官方語意不符，待上游確認） | #9 |
| 會員有多筆快照 | 989 人有 2 到 3 筆；以 day1 原始 4,615 列計算，一對多 join 後多出 571 列（其他前提見報告 #7） | #7 |
| 增量檔內同一個 order_id 重複 | day1 有 18 組，`updated_at` 都不同，其中 3 組連 `order_created_at`、`member_id`、`amount` 也不同（與官方語意不符，待上游確認） | #2 |
| 會員屬性真的會變 | 多快照會員中，跨快照日等級變過的 406 人（另 28 人是同日兩列等級矛盾，合計 434）、縣市變過的 376 人（無同日矛盾） | #6 |
| 非正數金額 | base 有 50 筆 `amount <= 0`，增量檔是 0 筆 | #3 |
