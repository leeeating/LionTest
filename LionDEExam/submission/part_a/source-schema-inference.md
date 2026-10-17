# 來源 schema 推測與違反清單（A-3 初稿素材）

〔AI 產出，待使用者審閱〕本文件只做**剖析與推測**，不含任何處理決策（修正、隔離、丟棄）。處理決策由使用者在 A-3 定稿時決定。

## 怎麼產生的

- 腳本：`LionDEExam/submission/part_a/profiling/profile_sources.py`（PySpark 4.2.0）。在 repo 根目錄執行：
  `uv run python -I LionDEExam/submission/part_a/profiling/profile_sources.py`
- **所有欄位以字串讀入**（`inferSchema=false`），型別轉換一律用 `try_cast`、`try_to_timestamp`、`try_to_date`，轉不過的算「無法轉換」，不讓 Spark 報錯也不悄悄變 NULL。
- **`spark.sql.session.timeZone = Asia/Taipei`**：沒有時區標記的時間字串（`2026/05/24 19:26:43`）會被解讀成台北時間；有標記的（`+08:00`、`Z`）照標記換算。這個設定只影響「沒有標記」的那 3,001 筆；它是否正確，見 V5 的驗證。
- 每段檢查以 `[Sx.名稱]` 標籤印出 SQL 原文與輸出。本文每個數字都附標籤，可在 stdout 用標籤搜尋到原始輸出。
- 查詢建立在三個 view 上（定義也印在 stdout）：`orders_all`（四個訂單檔 union，加 `src`、`batch_date`）、`orders_t`（解析後欄位：`co_ts`、`upd_ts`、`dep_dt`、`amount_d`、`qty_i`、`coupon_d`、`co_fmt`）、`orders_ratio`（加上產品定價與同日匯率，見 V1）。
- Spark 讀 CSV 時 BOM 已自動略過：`[S0]` 印出的第一欄名稱是 `'order_id'`，沒有多一個看不見的字元；七個檔都有 BOM（`BOM=True`），讀到的列數＝檔案行數−1。

---

## 1. 推測的原始 schema

推測對象是「上游營運 DB」：訂單表一張單一列（目前狀態），會員表一人一列（快照檔 = 會員表在某天的萃取），產品、匯率是主檔。**每個約束旁的依據是「多數值」**，違反者列在第 2 節。

### 1.1 orders（營運 DB 的訂單表）

```sql
CREATE TABLE orders (
  order_id         CHAR(11)      NOT NULL,             -- [S2.orders_fmt] 全部符合 ^ORD\d{8}$（0 筆不符）
  member_id        CHAR(7)       NOT NULL
                   REFERENCES members(member_id),       -- [S7.fk] 四檔 member_missing 皆 0
  product_id       CHAR(6)       NOT NULL
                   REFERENCES products(product_id),     -- [S7.fk] 只有 base 120 筆對不到（V6）
  channel          VARCHAR(4)    NOT NULL
                   CHECK (channel IN ('app','web','門市','電銷')),            -- [S3.channel] 只有這 4 值
  order_status     VARCHAR(10)   NOT NULL
                   CHECK (order_status IN ('created','paid','completed','cancelled')), -- [S3.order_status]、官方 README
  quantity         SMALLINT      NOT NULL CHECK (quantity BETWEEN 1 AND 4),  -- [S3.quantity] 只有 1~4，四值各約 1/4（見「值得質疑」Q4）
  currency         CHAR(3)       NOT NULL
                   CHECK (currency IN ('TWD','USD','JPY')),                 -- [S3.currency] 增量檔只有這 3 值；base 另有 NTD 200 筆（V4）
  amount           DECIMAL(14,2) NOT NULL CHECK (amount > 0),              -- [S4.amount_dist] base 100,040 列中負數只有 50（n_neg），0 元 0 筆；增量檔 n_neg、n_zero 皆 0
  coupon_discount  DECIMAL(5,0)  NOT NULL
                   CHECK (coupon_discount BETWEEN 0 AND 950 AND coupon_discount % 50 = 0), -- [S3.coupon] 增量檔 0~950、皆為 50 的倍數；base 只有 -1.0 例外（V3）
  order_created_at TIMESTAMPTZ   NOT NULL,             -- [S2.co_fmt] 增量檔全為 ISO +08:00；base 另有兩種格式（V5）
  departure_date   DATE          NOT NULL,             -- [S5.ranges] 四檔 dep_before_order_date 皆 0；出發距下單 7~119 天
  updated_at       TIMESTAMPTZ   NOT NULL,             -- [S2.upd_fmt] 全為 ISO +08:00
  PRIMARY KEY (order_id),                              -- [S6.orders_pk] base 100,040 列 / 100,000 id（V7）；見「需判斷」J1
  CHECK (updated_at >= order_created_at)               -- [S5.ranges] 四檔 upd_before_created 皆 0
);
-- 推測的隱含業務規則（非 DDL 能表達）：
--   amount × 下單日匯率 ≈ products.base_price_twd × quantity × [0.84, 1.29]
--   依據 [S4.ratio_dist]：13 個「來源檔×幣別」組合的 min_r～max_r 都落在 0.8378～1.2839；
--   [S4.ratio_buckets] 落在 [0.8, 1.3] 以外的列只有負數 50、約 ×1000 共 40、缺產品 120。
--   TWD、JPY 的 amount 是整數，USD 到小數 2 位（[S2.amount_decimals]；JPY 例外見 L5）。
--   TWD 不在 fx_rates，推測原系統以 1 計（[S7.currency_not_in_fx]，見 L12）。
```

### 1.2 members（營運 DB 的會員表）與 members.csv（快照萃取）

```sql
CREATE TABLE members (
  member_id     CHAR(7)      NOT NULL PRIMARY KEY,   -- [S2.members_fmt] 全部符合 ^M\d{6}$；8,000 位
  member_name   VARCHAR(10)  NOT NULL,               -- [S9.attr_change] 989 位多快照會員中 name_changed = 0
  member_level  VARCHAR(4)   NOT NULL
                CHECK (member_level IN ('一般','銀卡','金卡','白金')),  -- [S3.members_cat]
  city          VARCHAR(4)   NULL,                   -- [S3.members_cat] 10 個縣市 + 'N/A' 71 筆；推測原值為 NULL、匯出時寫成 'N/A'（V9）
  birth_date    DATE         NULL,                   -- [S9.birth_dist] 1900-01-01 以外最早 1960-01-03；1900-01-01 推測為「未知」的預設值（V10）
  register_date DATE         NOT NULL,               -- [S9.attr_change] register_changed = 0；[S9.dates_logic] register_before_birth = 0
  CHECK (register_date > birth_date)                 -- [S9.dates_logic] 0 筆違反
);
-- members.csv 是上表的每日萃取：
--   PRIMARY KEY (member_id, extract_date)           -- [S6.members_pk] 8,991 列 / 8,961 組，多 30 列（V8）
--   不可變欄位（推測）：member_name、register_date；birth_date 除了與 1900-01-01 互換之外沒有變過
--     （14 人 1900 → 真實、5 人 真實 → 1900，[S9.birth_change_direction]；V10、J9）
--   可變欄位：member_level（434 人變過）、city（376 人變過）[S9.attr_change]
```

### 1.3 products

```sql
CREATE TABLE products (
  product_id          CHAR(6)     NOT NULL PRIMARY KEY,   -- [S6.products_pk] 300 列 / 300 id；P00001~P00300
  product_name        VARCHAR(20) NOT NULL,               -- 不唯一：44 個名稱被多個 id 共用（L7）
  product_type        VARCHAR(4)  NOT NULL
                      CHECK (product_type IN ('團體旅遊','機票','票券','自由行','訂房')), -- [S3.products_cat]
  destination_country VARCHAR(4)  NOT NULL,
  destination_city    VARCHAR(4)  NOT NULL,
  trip_days           SMALLINT    NOT NULL CHECK (trip_days BETWEEN 1 AND 11),    -- [S2.products_fmt] 1~11
  base_price_twd      INT         NOT NULL
                      CHECK (base_price_twd BETWEEN 3000 AND 199000 AND base_price_twd % 1000 = 0), -- [S2.products_fmt]
  is_active           CHAR(1)     NOT NULL CHECK (is_active IN ('Y','N')),         -- [S3.products_cat] Y 287、N 13
  CHECK (product_name = destination_city || trip_days || '日' || product_type)     -- [S2.products_fmt] name_not_city_days_type = 0
);
```

products 沒有發現違反。

### 1.4 fx_rates

```sql
CREATE TABLE fx_rates (
  rate_date   DATE          NOT NULL,                 -- [S6.fx_pk] 每幣別 67 天、span_days = 67（連續）
  currency    CHAR(3)       NOT NULL CHECK (currency IN ('USD','JPY')),   -- [S2.fx_fmt] 沒有 TWD
  rate_to_twd DECIMAL(10,5) NOT NULL CHECK (rate_to_twd > 0),            -- [S2.fx_fmt] USD 30.939~31.58、JPY 0.20331~0.21094
  PRIMARY KEY (rate_date, currency)
);
```

fx_rates 沒有發現違反：日變動最大 USD 0.504%、JPY 1.094%（[S10.fx_daily_change]）；訂單下單日 05-01～07-03 都在匯率涵蓋範圍 04-28～07-03 內（[S10.fx_coverage]），USD/JPY 訂單 `fx_date_missing` 四檔皆 0（[S7.fk]）。

---

## 2. 違反清單

分組原則：**確定的錯誤值** = 違反的約束有強證據（多數值幾乎 100% 遵守、或違反值本身不合理），而且值本身是錯的；**未知值的哨兵** = 上游用特定值表示「不知道」（-1、N/A、1900-01-01），違反值域但不是錯誤的值，處理方式應與錯誤值分開考慮；**可能是合法業務狀況** = 只違反我推的「常態」，但業務上說得通。三組都不含處理建議。前提尚未定案的撞號問題（原 V11）移到第 3 節 J2、J3。

### 2.1 確定的錯誤值

#### V1｜orders_base.amount 為負數（50 筆）
- 違反：`CHECK (amount > 0)`。
- 影響：base 50 筆（TWD 29、USD 17、JPY 4）；增量檔 0 筆。[S4.amount_dist] `n_neg`
- 為什麼確定：負號拿掉後與正常列完全一樣——50 筆的 |ratio| 全落在正常區間 [0.8, 1.3]（[S4.ratio_buckets] `negative, |ratio| in normal range` TWD 29 + USD 17 + JPY 4）；同 order_id 沒有任何正數列（[S4.neg_status] `same_id_has_positive_row` 全 0，不是「原單＋沖銷單」）；狀態分布 cancelled 7、completed 18、created 6、paid 19，不集中在某種狀態。
- 偵測查詢（[S4.ratio_buckets] 節錄；完整見 stdout）：
  ```sql
  SELECT src, currency,
    CASE WHEN ratio IS NULL THEN 'no_ratio(缺產品或匯率)'
         WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative, |ratio| in normal range'
         WHEN ratio < 0 THEN 'negative, other'
         WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
         WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about x1000 (ratio/1000 in normal range)'
         ELSE 'other_outlier' END AS bucket,
    count(*) AS n
  FROM orders_ratio GROUP BY 1, 2, 3 HAVING bucket <> 'normal' ORDER BY src, currency, bucket
  ```
  其中 `orders_ratio.ratio = amount × 同日匯率（TWD/NTD 以 1） ÷ (base_price_twd × quantity)`。
- 範例（[S4.neg_examples]）：`ORD00000900 cancelled TWD -172833.0 qty 1 base_price 170000 ratio -1.0167`；`ORD00002319 completed TWD -216020.0 qty 3 base_price 63000 ratio -1.143`；`ORD00002817 completed TWD -26515.0 ratio -0.8838`。
- 連帶：coupon_discount（TWD）> 訂單台幣金額的 50 列，全部就是這 50 筆負數（[S4.coupon_vs_amount] `50 / of_which_negative_amount 50`），不是獨立問題。

#### V2｜orders_base.amount 約多乘 1,000（40 筆）
- 違反：隱含規則「amount 換算台幣 ≈ 定價 × 數量 × [0.84, 1.29]」。
- 影響：base 40 筆（TWD 27、USD 9、JPY 4）。[S4.ratio_buckets] `about x1000`
- 為什麼確定：40 筆的 ratio ÷ 1000 全部回到正常區間；TWD、JPY 的 31 筆都是 1000 的倍數，USD 9 筆都是 10 的倍數但不是 1000 的倍數——符合「小數 2 位的 USD 金額 × 1000」（[S4.x1000_mult]）。極端值例：`ORD00095841 JPY 3738074000.0 qty 4 base_price 190000 ratio 1007.4 → ÷1000 = 1.0074`（[S4.x1000_examples]）。
- 偵測查詢：同 V1（[S4.ratio_buckets]）。
- 範例（[S4.x1000_examples]）：`ORD00095841 JPY 3738074000.0`、`ORD00084134 JPY 2308721000.0`、`ORD00060205 JPY 1903148000.0`。
- 與既有筆記的差異：既有筆記用「超過該幣別 p99 兩倍」判斷，同樣得到 40 筆；本次改用定價比值，40 筆與正常列之間沒有灰色地帶（[S4.ratio_buckets] 沒有任何 `other_outlier`）。

#### V4｜orders_base.currency = 'NTD'（200 筆）
- 違反：`CHECK (currency IN ('TWD','USD','JPY'))`（NTD 不是 ISO 4217 代碼，增量檔沒有）。也不在 fx_rates（[S7.currency_not_in_fx] base NTD 200）。
- 為什麼確定是 TWD 的別名：以 1:1 換算時，NTD 的 ratio 分布與 TWD 幾乎相同（[S4.ntd] NTD p01 0.8537 / p50 1.0347 / p99 1.2406；TWD 0.8541 / 1.0506 / 1.246），NTD 都是整數金額（[S2.amount_decimals]）。若 NTD 是別的幣別，ratio 會整體偏移。NTD 分散在四個 channel（[S4.ntd_examples]）。
- 偵測查詢（[S3.currency]）：`SELECT src, currency, count(*) AS n FROM orders_t GROUP BY src, currency ORDER BY src, currency`
- 範例（[S4.ntd_examples] 各 channel 最小 id）：`ORD00000163`（app）、`ORD00000677`（web）、`ORD00001883`（門市）。

#### V5｜orders_base.order_created_at 格式不一致（6,002 筆）
- 違反：欄位應為單一格式的 TIMESTAMPTZ。
- 影響：base `iso_Z` 3,001 筆、`slash_no_tz`（`YYYY/MM/DD HH:MM:SS`）3,001 筆；其餘 94,038 筆與增量檔全部是 `+08:00`（[S2.co_fmt]）。
- 時區語意的驗證，兩種格式分開論證：
  - **Z 是 UTC**：主證據是 base 的重複列（V7）。8 組重複中，兩列的下單時間字串一列是 `+08:00`、另一列是 Z（5 組）或無標記（3 組）；照字面解析（Z = UTC）後 8 組全部是同一時刻、相差 0 小時（[S5.z_evidence] `same_instant_as_parsed true`、`diff_hours 0.0`），例如 `ORD00012637` 的 `2026-06-14T19:17:51+08:00` 與 `2026-06-14T11:17:51Z`。若 Z 其實是誤標的台北時間，這 5 組會相差 8 小時。輔證：Z 格式的最小值 `2026-04-30T17:04:32Z` 換成台北是 `2026-05-01 01:04:32`；Z 格式有 13 筆字面日期早於 05-01，照 UTC 解讀後 0 筆早於 05-01，與官方期間「05-01 起」相符（[S5.z_min] `raw_date_before_0501 13`、`before_0501_as_parsed 0`）。
  - **無標記的是台北時間**：上述 3 組重複列的字串與 `+08:00` 那列只差格式（如 `ORD00013776` 的 `2026/05/24 19:26:43` 與 `2026-05-24T19:26:43+08:00`，[S5.z_evidence]）。另以「updated_at（全為 +08:00）不應早於下單時間」檢查（[S5.tz_check]）：照台北時間解析時違反 0 筆；若無標記時間其實是 UTC（等於台北時間再加 8 小時），會有 384 筆違反。所以無標記不是 UTC。
  - [S5.tz_check] 中 Z 那一列（加 8 小時後 374 筆違反）**不能**當 Z 的證據：它檢驗的是「Z 的值比照字面再晚 8 小時」，但 Z 的替代假設是「Z 其實是台北時間誤標」，那應該是比照字面早 8 小時，這種方向的移動只會讓下單時間更早，`updated_at >= 下單時間` 永遠驗不出來。
  - 結論：值本身可還原，問題只在格式。
- 偵測查詢（[S2.co_fmt]）：
  ```sql
  SELECT src, co_fmt, count(*) AS n, min(order_created_at) AS example_min, max(order_created_at) AS example_max
  FROM orders_t GROUP BY src, co_fmt ORDER BY src, co_fmt
  ```
  `co_fmt` 在 view `orders_t` 以 regex 分類（`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$`、`...Z$`、`^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$`）。
- 範例：`2026-04-30T17:04:32Z`（= 台北 05-01 01:04:32）、`2026/05/01 01:02:46`、`2026/05/24 19:26:43`（[S2.co_fmt]、[S6.base_dup_examples]）。
- 注意：若用 `to_date(order_created_at)` 直接取前 10 碼，Z 格式會讓台北 08:00 前下單的訂單落到前一天，`2026-04-30T17:04:32Z` 就是例子（base 官方期間從 05-01 起）。

#### V6｜orders_base.product_id 不在產品主檔（120 筆）
- 違反：`REFERENCES products(product_id)`。
- 影響：base 120 列、120 個不同 id，全部 `P9xxxx`（P91064～P99990），主檔是 P00001～P00300；四種狀態都有；增量檔 0 筆（[S7.fk]、[S7.unknown_products]）。這 120 列也是 [S4.ratio_buckets] 的 `no_ratio`（TWD 76 + USD 23 + JPY 21 = 120）。
- 偵測查詢（[S7.unknown_products]）：
  ```sql
  SELECT count(*) AS n_rows, count(DISTINCT product_id) AS n_ids, min(product_id) AS id_min, max(product_id) AS id_max,
    sum(CASE WHEN product_id RLIKE '^P0\\d{4}$' THEN 1 ELSE 0 END) AS looks_like_P0xxxx,
    collect_set(order_status) AS statuses
  FROM orders_t o WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id = o.product_id)
  ```
- 範例（[S7.unknown_products_examples]）：`ORD00003151 P95718 TWD 210244.0`、`ORD00004247 P93453 USD 833.48`、`ORD00004396 P98236 JPY 433408.0`。

#### V7｜orders_base 同 order_id 兩列（40 組，多 40 列）
- 違反：`PRIMARY KEY (order_id)`（base 是全量，一張單應一列）。
- 影響：40 個 order_id 各 2 列（[S6.orders_pk] base extra_rows 40）。
- 為什麼確定是重複送出：40 組的 member、amount、下單時刻、狀態、其他欄位**全部相同**（[S6.orders_dup_groups] base：`same member/amount/created instant` 40 組、`status_changed 0`、`other_cols_changed 0`），只差 `updated_at` 2～29 秒（[S6.base_dup_gap]）；其中 8 組的 order_created_at 字串不同但是同一時刻（`created_same_instant_diff_format 8`，即 V5 的格式差異）。
- 偵測查詢（[S6.orders_dup_groups] 節錄）：
  ```sql
  WITH g AS (
    SELECT src, order_id, count(*) AS c, count(DISTINCT updated_at) AS d_upd,
      count(DISTINCT order_created_at) AS d_co_raw, count(DISTINCT co_ts) AS d_co_instant,
      count(DISTINCT member_id) AS d_mem, count(DISTINCT amount) AS d_amt, count(DISTINCT order_status) AS d_status,
      count(DISTINCT concat_ws('|', product_id, channel, quantity, currency, coupon_discount, departure_date)) AS d_other
    FROM orders_t GROUP BY src, order_id HAVING count(*) > 1)
  SELECT src, c AS rows_per_id,
    CASE WHEN d_mem = 1 AND d_amt = 1 AND d_co_instant = 1 THEN 'same member/amount/created instant'
         ELSE 'member/amount/created differ' END AS kind,
    count(*) AS n_groups, ... FROM g GROUP BY 1, 2, 3
  ```
- 範例（[S6.base_dup_examples]）：`ORD00000984`（updated_at `07:02:52` / `07:03:06`）、`ORD00012637`（+08:00 / Z）、`ORD00013776`（+08:00 / slash）。

#### V8｜members 同一 member_id、同一 extract_date 兩列（30 組）
- 違反：快照的 `PRIMARY KEY (member_id, extract_date)`。
- 影響：30 組（多 30 列），全在 2026-04-30；每組只有 member_level 不同，其他欄位相同（[S6.members_same_day_dup] `level_differs 30`、其餘 0）。
- 偵測查詢（[S6.members_pk]）：
  ```sql
  SELECT count(*) AS n_rows, count(DISTINCT member_id) AS n_members,
    count(DISTINCT member_id, extract_date) AS n_member_dates,
    count(*) - count(DISTINCT member_id, extract_date) AS extra_rows
  FROM members
  ```
- 範例（[S6.members_same_day_examples]）：`M000096 2026-04-30 金卡 / 銀卡`、`M000296 2026-04-30 白金 / 金卡`。
- 哪一列是對的，資料推不出來（同日、沒有時間戳）。

### 2.2 未知值的哨兵

#### V3｜orders_base.coupon_discount = -1.0（300 筆）〔新發現〕
- 違反：`CHECK (coupon_discount BETWEEN 0 AND 950 AND coupon_discount % 50 = 0)`。
- 影響：base 300 筆；增量檔 0 筆。負值只有 `-1.0` 一種（[S3.coupon] `negative_values [-1.0]`、`n_not_multiple_of_50 300`）。
- 為什麼確定：其餘列（增量檔全部、base 其他列）都是 0～950 的 50 倍數，`n_not_multiple_of_50` 只有 base 的 300；`-1` 是常見的「未知／未填」哨兵值。狀態、幣別分布散開（[S3.coupon_neg_profile]），與負數金額只重疊 1 列、與 ×1000 只重疊 1 列（[S4.overlap_anomalies]）。**它代表「沒有折扣」還是「折扣未知」推不出來**，見 J5。
- 偵測查詢（[S3.coupon]）：
  ```sql
  SELECT src, count(DISTINCT coupon_discount) AS n_distinct, min(coupon_d) AS min_v, max(coupon_d) AS max_v,
    sum(CASE WHEN coupon_d < 0 THEN 1 ELSE 0 END) AS n_negative,
    sum(CASE WHEN coupon_d = 0 THEN 1 ELSE 0 END) AS n_zero,
    sum(CASE WHEN coupon_d % 50 <> 0 THEN 1 ELSE 0 END) AS n_not_multiple_of_50,
    collect_set(CASE WHEN coupon_d < 0 THEN coupon_discount END) AS negative_values
  FROM orders_t GROUP BY src ORDER BY src
  ```
- 範例（[S3.coupon_neg_examples]）：`ORD00000203 paid TWD 149425.0 -1.0`、`ORD00000392 completed TWD 28478.0 -1.0`、`ORD00000576 completed TWD 38366.0 -1.0`。

#### V9｜members.city = 'N/A'（71 列）
- 違反：city 的值域（10 個縣市）；推測原值為 NULL。
- 影響：71 列、70 位會員；各快照日 66 / 3 / 2（[S9.birth_1900] `city_na`）；其中 9 位在其他快照有真實縣市（[S9.city_na_change]）。
- 偵測查詢（[S1.members]，每欄套同一模板）：
  ```sql
  SELECT 'city' AS col, count(*) AS n_rows, sum(CASE WHEN `city` IS NULL THEN 1 ELSE 0 END) AS n_null_or_empty,
    sum(CASE WHEN trim(`city`) IN ('N/A','NA','n/a','null','NULL','None','none','-','?','UNKNOWN','unknown','#N/A','NaN','nan') THEN 1 ELSE 0 END) AS n_placeholder,
    sum(CASE WHEN `city` <> trim(`city`) THEN 1 ELSE 0 END) AS n_untrimmed, count(DISTINCT `city`) AS n_distinct FROM members
  ```
  其他 6 個檔、所有欄位的空值、佔位字、前後空白都是 0（[S1.*]）。

#### V10｜members.birth_date = 1900-01-01（81 列）
- 違反：birth_date 的合理範圍；推測是「未知」的預設值。
- 影響：81 列（各快照日 76 / 2 / 3，[S9.birth_1900]）。1900 以外最早 1960-01-03（[S9.birth_dist]），中間沒有任何值。
- 補強證據〔新發現〕：19 位會員的 birth_date 在快照間變過，每一次變化都有一端是 1900-01-01（[S9.birth_change_detail] 19 人、1900 列 19 列），沒有「真實日期 → 另一個真實日期」。**方向有兩種**（[S9.birth_change_direction]，依 extract_date 排序相鄰兩列）：
  - `1900 -> real` 14 人：後來的快照補上了真實生日（例 M000552、M000708、M001372）。
  - `real -> 1900` 5 人：**原本的真實生日在後來的快照被 1900-01-01 覆寫**（例 M001647、M001931、M003842）。這是另一種品質問題：不只是「不知道」，而是已知值被哨兵值蓋掉。是上游清空欄位、還是匯出時把某種狀態寫成 1900，資料推不出來，列入 J9。
  - 兩個方向都說明 1900-01-01 是哨兵值，不是真實生日。
- 偵測查詢（[S9.birth_1900]）：
  ```sql
  SELECT extract_date, count(*) AS n_rows, sum(CASE WHEN birth_date = '1900-01-01' THEN 1 ELSE 0 END) AS birth_1900,
    sum(CASE WHEN city = 'N/A' THEN 1 ELSE 0 END) AS city_na,
    sum(CASE WHEN birth_date = '1900-01-01' AND city = 'N/A' THEN 1 ELSE 0 END) AS both
  FROM members GROUP BY extract_date ORDER BY extract_date
  ```
- 範例：1900 → 真實（[S9.birth_change_examples]）`M000552 1900-01-01 (04-30) → 1981-07-25 (06-30)`、`M000708 1900-01-01 (04-30) → 1996-11-05 (05-31)`；真實 → 1900（[S9.birth_real_to_1900_examples]）`M004004 1994-10-13 (04-30) → 1900-01-01 (05-31)`、`M001647 1961-07-15 (04-30) → 1900-01-01 (06-30)`、`M003842 1999-09-01 (04-30) → 1900-01-01 (05-31)`。
- 偵測查詢（[S9.birth_change_direction]）：
  ```sql
  WITH s AS (SELECT member_id, extract_date, birth_date,
      lag(birth_date) OVER (PARTITION BY member_id ORDER BY extract_date, member_level) AS prev_birth
    FROM members)
  SELECT CASE WHEN prev_birth = '1900-01-01' THEN '1900 -> real'
              WHEN birth_date = '1900-01-01' THEN 'real -> 1900'
              ELSE 'real -> other real' END AS direction,
    count(DISTINCT member_id) AS n_members, count(*) AS n_transitions,
    slice(array_sort(collect_set(member_id)), 1, 3) AS example_members
  FROM s WHERE prev_birth IS NOT NULL AND prev_birth <> birth_date GROUP BY 1 ORDER BY 1
  ```

### 2.3 可能是合法業務狀況

| # | 現象 | 影響筆數 | 證據標籤 | 為什麼可能合法 |
|---|---|---|---|---|
| L1 | 增量檔 `updated_at` 的日期晚於批次日 | day1 3,290、day2 3,257、day3 3,263；最晚到批次日 +4 天（day1 有 5 列） | [S5.inc_upd_after_batch_total]、[S5.inc_upd_vs_batch] | 檔名的「day」可能是下單批次而非更新批次；比例約 70%，是系統性的，不像少數髒資料 |
| L2 | base（官方 05-01～06-30）有 `updated_at` 落在 07-01～07-03 的列〔新發現〕 | 2,265 列（07-01 1,308 + 07-02 759 + 07-03 198；狀態分布 293 + 667 + 332 + 973 也合計 2,265）；base `updated_at` 最大 2026-07-03 17:20:05 | [S5.base_upd_after_period]、[S5.ranges] | 「05-01～06-30」可能指下單期間，base 實際萃取時點在 07-03 之後。連帶：增量列的 `updated_at` 比 base 同 id 列還舊的 12 列（day1 10、day2 2），對應的 base 列全部都是 07-01 之後更新的（[S8.inc_vs_base_upd_not_newer_cnt]） |
| L3 | day2 有 60 張下單日在 06-10～06-23、但 base 沒有的新 order_id〔新發現〕 | 60 列，id `ORD00112001`～`ORD00112060`，編號在 day3 新單（ORD00108001～112000）之後 | [S5.inc_created_vs_batch] `older_and_id_never_seen`、[S5.id_vs_time]、[S5.late_new_examples] | 晚到的訂單（上游補送）。order_id 編號與下單時間不單調，代表 order_id 不能拿來推時間 |
| L4 | day2 有 25 張 07-01 新單再出現，但 day2 送來的是**較舊**的事件：25 組全是 day1 `cancelled`、day2 `paid`，且 day2 的 `updated_at` 都比 day1 早（例 `ORD00100020` day1 cancelled 07-04T18:08:26、day2 paid 07-03T12:08:26）；其中 6 列 day2 的 `updated_at` 還早於 day2 批次日 | 25 個 id 跨 day1/day2，member/amount/created 三欄全一致；`later_file_newer 0` | [S8.inc_vs_inc]、[S8.inc_vs_inc_status_order]（`cancelled / paid / later_file_older / 25`）、[S8.inc_vs_inc_status_examples]、[S5.inc_upd_before_batch] `id_in_day1 true` | 同一張單、內容一致，是同一訂單的狀態事件；只是到達順序與發生順序相反（晚到的舊事件）。照 `updated_at` 排序是 paid → cancelled，照檔案順序則是 cancelled → paid。以哪個為準見 J6 |
| L5 | base 中 JPY 金額帶非零小數 | 80 列（其餘 10,942 列 JPY 都是整數；增量檔 JPY 全整數） | [S2.amount_decimals]、[S2.jpy_fraction_examples] | 80 列的 ratio 都在正常區間（[S4.ratio_buckets] 沒有列出它們），金額量級正確；DB 欄位若是 DECIMAL(14,2) 就存得下。也可能是上游換算誤差。範例 `ORD00004243 JPY 1829614.9`、`ORD00004874 JPY 313363.86` |
| L6 | 訂單的產品 `is_active = 'N'` | base 4,270、day1 184、day2 182、day3 195 | [S7.fk] `product_inactive` | is_active 是主檔目前狀態，下架前成立的訂單合理；增量檔也有這種列（未區分新單與舊單），需確認 is_active 的語意 |
| L7 | 同一 product_name 對應多個 product_id，定價不同 | 44 個名稱（253 個名稱 / 300 個 id） | [S6.products_pk]、[S6.products_dup_name_examples]（`P00098` / `P00262` 都叫「伊斯坦堡1日票券」，定價 144000 / 197000） | 不同供應商或檔期的同名產品 |
| L8 | 會員註冊時未滿 18 歲（排除 1900-01-01） | 455 列；最小 11.5 歲 | [S9.dates_logic] | 家庭成員或未成年帳號 |
| L9 | 會員 member_level、city 在快照間改變 | level 434 人（含 V8 同日矛盾）、city 376 人 | [S9.attr_change] | SCD2 本來就要處理的正常變化 |
| L10 | `completed` 的訂單出發日都還沒到 | base completed 28,612 列中 28,612 列 departure_date 晚於 updated_at 的日期 | [S5.status_vs_departure] | completed 可能是「付款／訂位完成」而不是「已出團」；增量檔中與 base 撞號的 completed 列才有出發日已過的情形 |
| L11 | 後續快照（05-31、06-30）中有屬性與前次完全相同的列〔新發現〕 | 05-31 94 列、06-30 91 列 | [S9.snapshot_pattern] | 既有筆記推測「有變更才出現」，這 185 列反駁了「只有變更才出現」；萃取規則未知 |
| L12 | TWD 不在 fx_rates | base TWD 66,690 + NTD 200 = 66,890；增量檔 3,069 / 3,150 / 3,141 | [S7.fk] `currency_not_in_fx`、[S7.currency_not_in_fx] | 本幣匯率恆為 1，主檔不列是常見設計；不是資料錯誤，但 join 時會漏掉 |

---

## 3. 推不出來、需要使用者判斷的事

### J1｜orders 的主鍵：`order_id` 還是 `order_id + 版本`
- 支持 `order_id`（一張單一列，增量為狀態更新）：官方 README「增量檔中同一 order_id 可能出現多次（狀態更新事件），以 updated_at 區分新舊」；乾淨的同 id 多列確實只改狀態——增量檔同檔重複 51 組中 45 組 member/amount/created/product 四欄一致（[S8.inc_dup_consistent]），跨檔 day1→day2 的 25 個 id 三欄全同（[S8.inc_vs_inc]），且這些「同會員」的轉移**依 `updated_at` 排序**時沒有倒退（[S8.status_transitions] `same_member true` 只有 paid→cancelled 25 與同狀態重送；那 25 筆 paid→cancelled 正是 day1→day2 的 25 個 id，若改依檔案順序就變成 cancelled→paid，見 L4、J6）。
- 支持需要版本（或 order_id 不可靠）：base 自己就有 40 組重複（V7）；增量檔有約 600 列/天的 id 與 base 相同但內容完全不同（J2）。若這些是合法的「同 id 不同單」，order_id 單獨就不是唯一鍵。

### J2｜增量檔與 base 同 order_id 的列（每天約 600 列）：noise 還是合法更新
- 數量：day1 603 列 / 597 id、day2 602 / 599、day3 603 / 598（[S8.inc_vs_base_cols]；base 先每 id 取一列，避免 V7 的重複讓列數翻倍）。
- 支持「是另一張單（撞號或上游錯配），不是更新」：
  - 與 base 相同的列數：member 0、下單時刻 0、amount 0（三檔皆是）；product 3 / 1 / 1（≈ 1/300 的隨機巧合）；channel 157 / 160 / 131（≈ 603 × 0.25）；currency 312 / 309 / 299（≈ 603 × 0.505，[S8.inc_vs_base_expected] 算出隨機相同的期望值）。**各欄與 base 的吻合率等於隨機抽樣的期望**，等於兩列之間沒有任何關聯。
  - 這些列的狀態只有 cancelled 或 completed（[S8.inc_vs_base_status]），而且出現 completed → cancelled、cancelled → completed 這類終態互換（例如 day1 completed→cancelled 68、cancelled→completed 40）。[S8.status_transitions] 依 updated_at 排相鄰兩列時，會員不同（`same_member false`）的轉移包含 cancelled→completed 122、completed→cancelled 238、completed→created 1 等終態後再變的情形；會員相同（`same_member true`）的轉移只有 paid→cancelled 25 與同狀態重送，沒有倒退。
  - 範例（[S8.inc_vs_base_examples]）：`ORD00005192` base 是 `M007765 P00240 USD 10230.87 paid 下單 05-06`，day1 是 `M005173 P00040 USD 6927.0 completed 下單 05-04`。
- 支持「是合法更新」：官方語意允許同 id 多次出現；這些列 `updated_at` 幾乎都比 base 新（day1 593/603、day2 600/602、day3 603/603，[S8.inc_vs_base_cols] `inc_newer_than_base`）；下單日落在 base 期間（05-01～06-30，[S5.inc_created_vs_batch] `older_and_id_in_base`），像是舊訂單的後續事件。
- 跨增量檔的撞號也已含在上述數字裡：[S8.inc_vs_inc] 中 `id_in_base true` 的 day1→day3 5 組、day2→day3 1 組，`same_member_amount_created 0`（會員、金額、下單時間都不同）；這 6 個 id 都在 base，所以兩端的增量列都已計入各檔與 base 重疊的 603 / 602 / 603 列。相對地，`id_in_base false` 的 day1→day2 25 組三欄全同，是同一張單；但這 25 組不是「後到的較新」：`later_file_newer 0`，25 組全是 day1 cancelled、day2 paid，day2 的 `updated_at` 較舊（[S8.inc_vs_inc_status_order]）。也就是說，「以檔案順序判斷新舊」與「以 updated_at 判斷新舊」在這 25 組會得到相反的最終狀態（L4、J6）。
- 要使用者判斷：同一張單的 member_id、order_created_at、amount 能不能變（J4）；若不能，這些列就是 noise。

### J3｜增量檔「同檔同 order_id」但會員、金額、下單時間都不同（6 組；原列為 V11）
原本放在「確定的 noise」，但它是不是 noise 取決於尚未定案的 J4，所以移到這裡。它與 J2 是同一種現象（id 在 base、內容互不相關），差別只在兩列落在同一個增量檔。拆開判斷還是與 J2 合併判斷，由使用者決定。
- 違反：`PRIMARY KEY (order_id)` 加上「同一張單的 member_id、order_created_at 不可變」（J4）。
- 影響：day1 3 組、day2 1 組、day3 2 組，共 12 列；6 個 id 全部也存在於 base（[S6.orders_dup_groups]、[S6.inc_dup_collision_examples] `id_in_base true`）。
- 這 6 組與 J2 的「增量列 vs base 列」是同一種現象（同 id 但內容像另一張單），只是兩列剛好落在同一個增量檔。若 J4 成立（這些欄位不可變），它就是 noise。
- 偵測查詢（[S6.inc_dup_collision_examples]）：
  ```sql
  WITH g AS (SELECT src, order_id FROM orders_t WHERE src <> 'base' GROUP BY src, order_id
             HAVING count(*) > 1 AND (count(DISTINCT member_id) > 1 OR count(DISTINCT amount) > 1 OR count(DISTINCT co_ts) > 1))
  SELECT o.src, o.order_id, o.member_id, o.amount, o.order_status, o.order_created_at, o.updated_at,
    o.order_id IN (SELECT order_id FROM orders_base) AS id_in_base
  FROM orders_t o JOIN g ON o.src = g.src AND o.order_id = g.order_id ORDER BY o.src, o.order_id, o.updated_at
  ```
- 範例：`ORD00036457`（day1：M002150 200659.0 completed / M000272 18042.46 cancelled）、`ORD00043894`（day2）、`ORD00083916`（day3）。


### J4｜哪些欄位在原系統不可修改
- 資料支持「不可變」的欄位：
  - orders：member_id、order_created_at、product_id、amount——在所有「乾淨」的更新裡都沒變（同檔 45 組、跨檔 25 組、base 重複 40 組）。只有 J2、J3 的撞號列會改。
  - members：member_name（0 人變過）、register_date（0 人變過）、birth_date（變過的 19 人都是與 1900-01-01 互換：14 人 1900 → 真實、5 人 真實 → 1900；沒有真實日期改成另一個真實日期）（[S9.attr_change]、[S9.birth_change_direction]）。
- 推不出來的：currency、quantity、coupon_discount、departure_date 在乾淨更新裡也都沒變（[S6.orders_dup_groups] `other_cols_changed` 在 same 組皆 0），但旅遊業務上「改出發日」「加人數」是可能的，資料樣本太少（45 + 25 組）不足以排除。

### J5｜coupon_discount = -1.0 代表什麼
「沒有用折扣」（等同 0）還是「折扣金額未知」。資料裡 0 本身就有 4,942 列（[S3.coupon] base `n_zero`），所以 -1 不是「沒有折扣」的唯一表示法；這點傾向「未知」，但無法證實。

### J6｜base 的萃取時點與增量的切分基準
L1、L2 顯示 base 與增量檔的 `updated_at` 都會超出檔名日期。增量切分要以「檔案」為準還是以 `updated_at` 為準、base 是否已含 07-01～07-03 的更新，需要使用者決定解讀（影響「以 updated_at 判斷新舊」的可靠度：12 列增量列比 base 同 id 列還舊）。另一個直接受影響的例子是 L4：day1→day2 的 25 個 id，依檔案順序最後一筆是 day2 的 paid，依 `updated_at` 最新一筆是 day1 的 cancelled（[S8.inc_vs_inc_status_order] `later_file_older 25`）；兩種基準會得到不同的最終狀態。

### J7｜members 的 N/A、1900-01-01、同日兩列
是否視為 NULL／未知；同日兩列（V8）資料沒有可判斷先後的欄位，要用什麼規則挑一列，或兩列都保留並標記。

### J8｜completed 的業務語意
L10：completed 都發生在出發前。這影響「已完成營收」等指標的定義，屬業務問題。

### J9｜birth_date 的真實值被 1900-01-01 覆寫（5 人）
V10 中 5 位會員是「真實日期 → 1900-01-01」（[S9.birth_change_direction]）。可能的解讀：上游刪除或清空了生日（例如會員要求移除個資），匯出時以 1900 表示；或上游同步錯誤把已知值蓋掉。前者代表「最新值就是未知」，後者代表「最新值是錯的、前一次才是對的」。資料裡沒有能區分兩者的欄位。

### J10｜amount 是折扣前還是折扣後
目前無法從資料確認。比值檢查（[S4.coupon_vs_ratio]、[S4.ratio_edges]）：
- 若 amount 是折扣後，折扣高的訂單 ratio 應該偏低；實際上 coupon 500～950 組的平均 ratio 1.0504，反而略高於 coupon=0 組的 1.0488。
- TWD/NTD 中 coupon = 0 與 coupon = 950 兩組的 ratio 上下界幾乎相同（0.85～1.2498 vs 0.85～1.2499）。若 amount 是「定價區間 − 950」，950 組的下界應該被往下推。
- 但 coupon 平均只佔 amount 的 0.3%～0.9%（`avg_coupon_pct_of_amount`），比 ratio 本身的散布（0.85～1.25）小一個量級，所以**這個檢查的鑑別力很弱**：資料傾向「amount 與 coupon 各自獨立產生（像折扣前）」，但不能排除折扣後。需要向上游確認或由使用者判斷。

```sql
SELECT CASE WHEN coupon_d < 0 THEN 'coupon=-1' WHEN coupon_d = 0 THEN 'coupon=0'
            WHEN coupon_d <= 450 THEN 'coupon 50~450' ELSE 'coupon 500~950' END AS coupon_bucket,
  count(*) AS n, round(avg(ratio), 4) AS avg_ratio, round(percentile_approx(ratio, 0.5), 4) AS p50_ratio,
  round(avg((amount_d * fx + coupon_d) / (bp * qty_i)), 4) AS avg_ratio_if_add_back_coupon,
  round(avg(coupon_d / (amount_d * fx)) * 100, 3) AS avg_coupon_pct_of_amount
FROM orders_ratio WHERE ratio BETWEEN 0.8 AND 1.3 GROUP BY 1 ORDER BY 1
```

---

## 4. 值得質疑的地方（我自己的推論裡最弱的）

- **Q1 金額比值模型是從資料反推的**：「amount ≈ 定價 × 數量 × [0.84, 1.29]」只是觀察到的分布，不是官方規則。它讓 V1、V2 看起來非常乾淨，但如果真實系統允許整單折價或加購，這條規則就太嚴。另外，ratio 用的是**下單日**的匯率；若原系統用付款日匯率，USD/JPY 的比值會小幅偏移（匯率日變動 < 1.1%，影響不大）。
- **Q2 ×1000 的 USD 9 筆不是 1000 的倍數**：我把它解釋成「2 位小數的 USD × 1000」，這是推論；也可能是「把 TWD 金額誤標成 USD」之類的別種錯誤。不過 TWD 誤標 USD 的話 ratio 會約 ×31，不是 ×1000，所以目前證據支持 ×1000。
- **Q3 V5 的時區證據樣本小**：「Z 是 UTC」主要靠 5 組重複列（[S5.z_evidence]），加上 13 筆 Z 字面日期早於 05-01 的輔證；「無標記是台北時間」靠 3 組重複列與 `updated_at >= order_created_at` 這條假設。若這條假設不成立，無標記格式的證據就只剩 3 組重複列。
- **Q4 CHECK 範圍是「觀察到的範圍」**：quantity 1～4、trip_days 1～11、coupon 0～950、出發前 7～119 天，四檔都 100% 遵守，看起來是合成資料的產生規則，不一定是原系統的 CHECK。寫成 DDL 是為了說明「這是目前的值域」，不代表超出範圍的未來資料一定是錯。
- **Q5 J2 的「隨機吻合」論證**：我用 base 的 channel／currency 分布算期望值（0.25、0.505），實際吻合率（約 0.22～0.27、0.50～0.52）接近期望值。這證明兩列「統計上無關」，但不能排除「上游真的允許整張單被改寫」這種極端業務規則。
- **Q6 `percentile_approx` 是近似值**：S4 的 p25／p50／p75／p99 與既有筆記（Python 精確分位數）有小差異（見第 5 節），不影響任何違反的判定（判定都用精確的比較條件，不靠分位數）。
- **Q7 分組的界線是我畫的**：V3（coupon -1）、V9（N/A）、V10（1900）已改放「未知值的哨兵」一組，和 V1、V2 這種錯誤值分開；但 V10 中「真實 → 1900」那 5 人可能是真正的資料損毀，也可能是上游刻意清空，兩種解讀見 J9。

---

## 5. 與既有筆記的數字差異

| 項目 | 既有筆記 | 本次（Spark） | 原因 |
|---|---|---|---|
| products.base_price_twd 範圍 | `notes/dataset/dictionary.md`：10,000 ~ 99,000 | 3,000 ~ 199,000（[S2.products_fmt] `price_min` / `price_max`） | 既有筆記用**字串**比大小。同一查詢的 `price_min_as_string = 10000`、`price_max_as_string = 99000` 重現了舊數字。與 E9 記錄過的 amount 字串比較錯誤是同一類 |
| base amount 分位數 | `dictionary.md`「amount 分布」：如 TWD p50 202,880、p99 837,563 | TWD p50 202,826、p99 836,821（[S4.amount_dist]） | 本次用 Spark `percentile_approx`（近似），既有用 Python 排序後取索引。min、max、負數筆數完全一致 |
| day2 與 base 重疊列數 | E11：602 列 / 599 id | 602 / 599（[S8.inc_vs_base_cols]） | 一致。注意：若不先把 base 每 id 取一列，直接 join 會因 V7 的重複得到 603 列（第一次執行就是如此，已修正查詢） |
| 等級變過的會員 | `dictionary.md`：跨快照日 406 人＋同日矛盾 28 人 = 434 | 434（[S9.attr_change]） | 一致；本次的 434 是「任一列等級不同」，沒有拆開跨日與同日 |
| members 後續快照 | `dictionary.md`：「看起來像有變更才出現」（未證實） | 05-31 有 94 列、06-30 有 91 列與前次快照完全相同（[S9.snapshot_pattern]） | 新查詢反駁了這個推測 |

其餘與既有筆記一致：七檔 BOM、base 100,040 列 / 100,000 id、增量列數與 id 數、日期格式各 3,001、NTD 200、fx 只有 USD/JPY、負數 50（29/17/4）、疑似 ×1000 40（27/9/4，31 筆為 1000 倍數）、product_id 不在主檔 120、city N/A 71、同日重複 30 組、birth 1900 81 列、增量檔 `updated_at` 晚於批次日 3,290 / 3,257 / 3,263、day2 6 列早於批次日、同檔重複 18 / 16 / 17 組。

## 6. 新發現（既有筆記沒有的）

1. V3：base `coupon_discount = -1.0` 300 筆（哨兵值）。
2. V10 補強與 J9：birth_date 變過的 19 位會員都是與 1900-01-01 互換，14 人 1900 → 真實、5 人 真實 → 1900（真實值被哨兵值覆寫）。
3. L2：base 有 2,265 列（1,308 + 759 + 198） `updated_at` 在 07-01～07-03，base 不是 06-30 截止的快照；增量列比 base 舊的 12 列都源於此。
4. L3：day2 有 60 張 06-10～06-23 下單、base 沒有的晚到新單（ORD00112001～112060）。
5. L4：day1→day2 再出現的 25 個 id，day2 送來的都是較舊的事件（day1 cancelled、day2 paid，day2 `updated_at` 較舊），其中 6 列 `updated_at` 早於 day2 批次日。
6. J2 補強：增量與 base 撞號列的各欄吻合率等於隨機期望值；這些列的狀態只有 cancelled／completed。
7. V1、V2 補強：以「定價 × 數量 × 匯率」比值，負數與 ×1000 都能與正常列完全分開，沒有灰色地帶。
8. L11：會員後續快照有 185 列與前次完全相同。
9. L5：base 有 80 筆 JPY 金額帶小數。
10. L7：44 個產品名稱被多個 product_id 共用。
11. 第 5 節：既有筆記 base_price_twd 範圍是字串比較的錯誤值。
12. J10：amount 與 coupon 在比值上看不出關聯，折扣前／後無法由資料確認。
