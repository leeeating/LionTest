# Dataset 資料字典（欄位層級）

回到入口：[README.md](README.md)

對象：`candidate_package/dataset/` 的 7 個 CSV。

**範圍**：這份只寫結構面，包括筆數、欄位、key、表之間的關聯、值域。值域照實際觀察列出，**不在這裡判斷是不是品質問題**，品質檢核由 Part A 的 A-3 負責。最後一節只列 Part B 已經用查詢驗證過的事實。

**數字怎麼來的**：用 Python 標準庫 `csv` 讀檔（編碼 `utf-8-sig`）統計，查詢與輸出見 `../../ai-collab/process-log-part-b.md` B-02。官方欄位說明在 `candidate_package/README.md`，本文標「官方」的地方就是引用那份。

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

以下每一項都附查詢輸出，在 `../../ai-collab/process-log-part-b.md` B-01 步驟 3。

| 事實 | 數字 | 對應報告問題編號（`part_b/code-review.md`「問題總表」） |
|---|---|---|
| fx 沒有 TWD | day1 有 3,069 筆 TWD 訂單（共 4,615 筆）查不到匯率 | #1 |
| 增量檔有和 base 同 order_id 的列 | day1 有 597 個 order_id（603 列）已經存在於 base，其中 485 列狀態和 base 不同；603 列的 `order_created_at`、`member_id`、`amount` 都和 base 不同（與官方語意不符，待上游確認） | #3 |
| 會員有多筆快照 | 989 人有 2 到 3 筆；以 day1 原始 4,615 列計算，一對多 join 後多出 571 列（其他前提見報告 #4） | #4 |
| 增量檔內同一個 order_id 重複 | day1 有 18 組，`updated_at` 都不同，其中 3 組連 `order_created_at`、`member_id`、`amount` 也不同（與官方語意不符，待上游確認） | #5 |
| 會員屬性真的會變 | 多快照會員中，等級變過的 434 人、縣市變過的 376 人 | #6 |
| 非正數金額 | base 有 50 筆 `amount <= 0`，增量檔是 0 筆 | #7 |
