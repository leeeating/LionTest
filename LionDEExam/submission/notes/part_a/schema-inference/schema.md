# 推測的原始 schema

回到：[README.md](README.md)｜問題總表：[issues.md](issues.md)

**結論**：推測對象是「上游營運 DB」：訂單表一張單一列（目前狀態），會員表一人一列（快照檔 = 會員表在某天的萃取），產品、匯率是主檔。**每個約束旁的依據是「多數值」**，違反者列在 [issues.md](issues.md)。products 與 fx_rates 沒有發現違反。

## orders（營運 DB 的訂單表）

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
  quantity         SMALLINT      NOT NULL CHECK (quantity BETWEEN 1 AND 4),  -- [S3.quantity] 只有 1~4，四值各約 1/4（見下方 Q4）
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

## members（營運 DB 的會員表）與 members.csv（快照萃取）

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

## products

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

**與既有筆記的差異（已更正）**：`notes/dataset/dictionary.md` 原本寫 base_price_twd 範圍 10,000 ~ 99,000；本次（Spark）是 3,000 ~ 199,000（[S2.products_fmt] `price_min` / `price_max`）。原因是既有筆記用**字串**比大小，同一查詢的 `price_min_as_string = 10000`、`price_max_as_string = 99000` 重現了舊數字，與 E9（[`part_b/evidence.md`](../../../part_b/evidence.md) 的證據編號，資料字典的統計）記錄過的 amount 字串比較錯誤是同一類。**已更正**：[dictionary.md](../../dataset/dictionary.md) 已於 commit `83c58df` 改為 3,000～199,000。

## fx_rates

```sql
CREATE TABLE fx_rates (
  rate_date   DATE          NOT NULL,                 -- [S6.fx_pk] 每幣別 67 天、span_days = 67（連續）
  currency    CHAR(3)       NOT NULL CHECK (currency IN ('USD','JPY')),   -- [S2.fx_fmt] 沒有 TWD
  rate_to_twd DECIMAL(10,5) NOT NULL CHECK (rate_to_twd > 0),            -- [S2.fx_fmt] USD 30.939~31.58、JPY 0.20331~0.21094
  PRIMARY KEY (rate_date, currency)
);
```

fx_rates 沒有發現違反：日變動最大 USD 0.504%、JPY 1.094%（[S10.fx_daily_change]）；訂單下單日 05-01～07-03 都在匯率涵蓋範圍 04-28～07-03 內（[S10.fx_coverage]），USD/JPY 訂單 `fx_date_missing` 四檔皆 0（[S7.fk]）。

## 值得質疑 Q4：CHECK 範圍是「觀察到的範圍」

quantity 1～4、trip_days 1～11、coupon 0～950、出發前 7～119 天，四檔都 100% 遵守，看起來是合成資料的產生規則，不一定是原系統的 CHECK。寫成 DDL 是為了說明「這是目前的值域」，不代表超出範圍的未來資料一定是錯。
