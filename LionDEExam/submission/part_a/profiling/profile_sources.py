"""Part A：來源資料剖析（A-3 資料品質檢核的素材）。

用法（在 repo 根目錄 LionTest/）：
    uv run python -I LionDEExam/submission/part_a/profiling/profile_sources.py

原則：
- 所有欄位以字串讀入（不 inferSchema），才看得到原始值；型別轉換一律用 try_cast / try_to_timestamp，
  轉不過的算成「無法轉換」而不是讓 Spark 報錯或悄悄變 null。
- spark.sql.session.timeZone 固定為 Asia/Taipei：沒有時區標記的時間字串（`YYYY/MM/DD HH:MM:SS`）
  會被解讀成台北時間；有標記（+08:00、Z）的照標記換算。
- 每段檢查都是 Spark SQL，查詢原文與輸出一起印到 stdout，報告直接引用。
- 本腳本只剖析，不修改任何資料。
"""

from __future__ import annotations

import os
import sys

from pyspark.sql import SparkSession

REPO = os.getcwd()
DATA = os.path.join(REPO, "LionDEExam", "candidate_package", "dataset")
FILES = {
    "orders_base": "orders_base.csv",
    "orders_day1": "orders_incremental_day1.csv",
    "orders_day2": "orders_incremental_day2.csv",
    "orders_day3": "orders_incremental_day3.csv",
    "members": "members.csv",
    "products": "products.csv",
    "fx_rates": "fx_rates.csv",
}

spark = (
    SparkSession.builder.master("local[*]")
    .appName("profile_sources")
    .config("spark.ui.enabled", "false")
    .config("spark.ui.showConsoleProgress", "false")
    .config("spark.sql.session.timeZone", "Asia/Taipei")
    .config("spark.sql.shuffle.partitions", "8")
    .config("spark.sql.warehouse.dir", "/tmp/profile_sources_warehouse")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("ERROR")


def q(tag: str, title: str, sql: str, n: int = 60) -> None:
    """印出查詢標籤、說明、SQL 原文與結果。"""
    print(f"\n### [{tag}] {title}")
    print("```sql")
    print(sql.strip())
    print("```")
    df = spark.sql(sql)
    print(df._jdf.showString(n, 0, False))
    sys.stdout.flush()


def make_view(sql: str) -> None:
    """建立 temp view，並印出定義（後續查詢都建立在這些 view 上）。"""
    print("\n```sql")
    print(sql.strip())
    print("```")
    spark.sql(sql)


def section(name: str) -> None:
    print("\n" + "=" * 100)
    print(f"## {name}")
    print("=" * 100)


# ---------------------------------------------------------------------------------------------
section("S0 環境與讀檔")
print("pyspark", spark.version, "| session.timeZone =", spark.conf.get("spark.sql.session.timeZone"),
      "| ansi =", spark.conf.get("spark.sql.ansi.enabled"))

for view, fname in FILES.items():
    path = os.path.join(DATA, fname)
    with open(path, "rb") as fh:
        head = fh.read(3)
        fh.seek(0)
        lines = sum(1 for _ in fh)
    df = (spark.read.option("header", "true").option("inferSchema", "false")
          .option("mode", "FAILFAST").option("encoding", "UTF-8").csv(path))
    df.createOrReplaceTempView(view)
    print(f"[S0] {fname}: BOM={head == bytes.fromhex('efbbbf')} 檔案行數(含表頭)={lines} "
          f"Spark 讀到列數={df.count()} 欄位={df.columns} 第一欄名稱 repr={df.columns[0]!r}")

# 所有訂單檔合併成一個 view，src 標示來源檔、batch_date 是檔名對應的批次日（base 用 NULL）
make_view("""
CREATE OR REPLACE TEMP VIEW orders_all AS
SELECT 'base' AS src, CAST(NULL AS DATE) AS batch_date, * FROM orders_base
UNION ALL SELECT 'day1', DATE'2026-07-01', * FROM orders_day1
UNION ALL SELECT 'day2', DATE'2026-07-02', * FROM orders_day2
UNION ALL SELECT 'day3', DATE'2026-07-03', * FROM orders_day3
""")

# 型別化的 view：只做「解析」，不做任何修正。三種時間格式各自解析。
make_view("""
CREATE OR REPLACE TEMP VIEW orders_t AS
SELECT o.*,
  CASE WHEN order_created_at RLIKE '^\\\\d{4}-\\\\d{2}-\\\\d{2}T\\\\d{2}:\\\\d{2}:\\\\d{2}\\\\+08:00$' THEN 'iso_+08:00'
       WHEN order_created_at RLIKE '^\\\\d{4}-\\\\d{2}-\\\\d{2}T\\\\d{2}:\\\\d{2}:\\\\d{2}Z$'        THEN 'iso_Z'
       WHEN order_created_at RLIKE '^\\\\d{4}/\\\\d{2}/\\\\d{2} \\\\d{2}:\\\\d{2}:\\\\d{2}$'          THEN 'slash_no_tz'
       ELSE 'other' END AS co_fmt,
  coalesce(try_to_timestamp(order_created_at, "yyyy-MM-dd'T'HH:mm:ssXXX"),
           try_to_timestamp(order_created_at, 'yyyy/MM/dd HH:mm:ss')) AS co_ts,
  try_to_timestamp(updated_at, "yyyy-MM-dd'T'HH:mm:ssXXX") AS upd_ts,
  try_to_date(departure_date, 'yyyy-MM-dd') AS dep_dt,
  try_cast(amount AS DOUBLE) AS amount_d,
  try_cast(quantity AS INT) AS qty_i,
  try_cast(coupon_discount AS DOUBLE) AS coupon_d
FROM orders_all o
""")
spark.sql("CACHE TABLE orders_t")

# ---------------------------------------------------------------------------------------------
section("S1 空值／空字串／佔位字／前後空白（逐檔逐欄）")
PLACEHOLDERS = "('N/A','NA','n/a','null','NULL','None','none','-','?','UNKNOWN','unknown','#N/A','NaN','nan')"
for view in FILES:
    cols = spark.table(view).columns
    parts = []
    for c in cols:
        parts.append(
            f"SELECT '{c}' AS col, count(*) AS n_rows, "
            f"sum(CASE WHEN `{c}` IS NULL THEN 1 ELSE 0 END) AS n_null_or_empty, "
            f"sum(CASE WHEN trim(`{c}`) IN {PLACEHOLDERS} THEN 1 ELSE 0 END) AS n_placeholder, "
            f"sum(CASE WHEN `{c}` <> trim(`{c}`) THEN 1 ELSE 0 END) AS n_untrimmed, "
            f"count(DISTINCT `{c}`) AS n_distinct FROM {view}"
        )
    q(f"S1.{view}", f"{view}：每欄空值（CSV 空欄讀成 NULL）、佔位字、前後空白、相異值數",
      "\nUNION ALL\n".join(parts), n=20)

# ---------------------------------------------------------------------------------------------
section("S2 格式與型別可轉換性")
q("S2.orders_fmt", "訂單各欄位格式（regex）與轉型失敗筆數，依來源檔", r"""
SELECT src, count(*) AS n,
  sum(CASE WHEN order_id   RLIKE '^ORD\\d{8}$' THEN 0 ELSE 1 END) AS bad_order_id,
  sum(CASE WHEN member_id  RLIKE '^M\\d{6}$'   THEN 0 ELSE 1 END) AS bad_member_id,
  sum(CASE WHEN product_id RLIKE '^P\\d{5}$'   THEN 0 ELSE 1 END) AS bad_product_id,
  sum(CASE WHEN qty_i IS NULL THEN 1 ELSE 0 END) AS qty_not_int,
  sum(CASE WHEN amount_d IS NULL THEN 1 ELSE 0 END) AS amount_not_num,
  sum(CASE WHEN coupon_d IS NULL THEN 1 ELSE 0 END) AS coupon_not_num,
  sum(CASE WHEN co_ts IS NULL THEN 1 ELSE 0 END) AS created_unparsable,
  sum(CASE WHEN upd_ts IS NULL THEN 1 ELSE 0 END) AS updated_unparsable,
  sum(CASE WHEN dep_dt IS NULL THEN 1 ELSE 0 END) AS departure_unparsable
FROM orders_t GROUP BY src ORDER BY src
""")
q("S2.co_fmt", "order_created_at 的格式種類（依來源檔）", """
SELECT src, co_fmt, count(*) AS n, min(order_created_at) AS example_min, max(order_created_at) AS example_max
FROM orders_t GROUP BY src, co_fmt ORDER BY src, co_fmt
""")
q("S2.upd_fmt", "updated_at／departure_date 的格式種類", r"""
SELECT src,
  sum(CASE WHEN updated_at RLIKE '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\+08:00$' THEN 1 ELSE 0 END) AS upd_iso_0800,
  sum(CASE WHEN updated_at RLIKE '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\+08:00$' THEN 0 ELSE 1 END) AS upd_other,
  sum(CASE WHEN departure_date RLIKE '^\\d{4}-\\d{2}-\\d{2}$' THEN 0 ELSE 1 END) AS dep_not_yyyy_mm_dd
FROM orders_t GROUP BY src ORDER BY src
""")
q("S2.amount_decimals", "amount 的小數位數（依幣別）：JPY/TWD 通常沒有小數", r"""
SELECT src, currency,
  sum(CASE WHEN amount RLIKE '\\.0$' OR amount NOT LIKE '%.%' THEN 1 ELSE 0 END) AS integer_valued,
  sum(CASE WHEN amount RLIKE '\\.\\d*[1-9]\\d*$' THEN 1 ELSE 0 END) AS has_fraction,
  max(length(regexp_extract(amount, '\\.(\\d+)$', 1))) AS max_decimal_digits
FROM orders_t GROUP BY src, currency ORDER BY src, currency
""")
q("S2.jpy_fraction_examples", "base 中 JPY 帶非零小數的範例", r"""
SELECT order_id, currency, amount, quantity, product_id, order_created_at
FROM orders_t WHERE src='base' AND currency='JPY' AND amount RLIKE '\\.\\d*[1-9]\\d*$'
ORDER BY order_id LIMIT 3
""")
q("S2.members_fmt", "members 欄位格式", r"""
SELECT count(*) AS n,
  sum(CASE WHEN member_id RLIKE '^M\\d{6}$' THEN 0 ELSE 1 END) AS bad_member_id,
  sum(CASE WHEN try_to_date(birth_date,'yyyy-MM-dd') IS NULL THEN 1 ELSE 0 END) AS birth_unparsable,
  sum(CASE WHEN try_to_date(register_date,'yyyy-MM-dd') IS NULL THEN 1 ELSE 0 END) AS register_unparsable,
  sum(CASE WHEN try_to_date(extract_date,'yyyy-MM-dd') IS NULL THEN 1 ELSE 0 END) AS extract_unparsable
FROM members
""")
q("S2.products_fmt", "products 欄位格式與數值範圍", r"""
SELECT count(*) AS n,
  sum(CASE WHEN product_id RLIKE '^P\\d{5}$' THEN 0 ELSE 1 END) AS bad_product_id,
  sum(CASE WHEN try_cast(trip_days AS INT) IS NULL THEN 1 ELSE 0 END) AS trip_days_not_int,
  sum(CASE WHEN try_cast(base_price_twd AS INT) IS NULL THEN 1 ELSE 0 END) AS price_not_int,
  min(try_cast(base_price_twd AS INT)) AS price_min, max(try_cast(base_price_twd AS INT)) AS price_max,
  min(base_price_twd) AS price_min_as_string, max(base_price_twd) AS price_max_as_string,
  sum(CASE WHEN try_cast(base_price_twd AS INT) % 1000 <> 0 THEN 1 ELSE 0 END) AS price_not_multiple_of_1000,
  min(try_cast(trip_days AS INT)) AS trip_min, max(try_cast(trip_days AS INT)) AS trip_max,
  sum(CASE WHEN product_name = concat(destination_city, trip_days, '日', product_type) THEN 0 ELSE 1 END)
    AS name_not_city_days_type
FROM products
""")
q("S2.fx_fmt", "fx_rates 欄位格式與範圍", """
SELECT currency, count(*) AS n, min(rate_date) AS d_min, max(rate_date) AS d_max,
  sum(CASE WHEN try_to_date(rate_date,'yyyy-MM-dd') IS NULL THEN 1 ELSE 0 END) AS date_unparsable,
  sum(CASE WHEN try_cast(rate_to_twd AS DOUBLE) IS NULL THEN 1 ELSE 0 END) AS rate_not_num,
  min(try_cast(rate_to_twd AS DOUBLE)) AS rate_min, max(try_cast(rate_to_twd AS DOUBLE)) AS rate_max
FROM fx_rates GROUP BY currency ORDER BY currency
""")

# ---------------------------------------------------------------------------------------------
section("S3 類別欄位的值域")
for col in ["channel", "order_status", "currency", "quantity"]:
    q(f"S3.{col}", f"orders.{col} 值域（依來源檔）",
      f"SELECT src, {col}, count(*) AS n FROM orders_t GROUP BY src, {col} ORDER BY src, {col}")
q("S3.coupon", "coupon_discount 值域（依來源檔）：相異值、負數、非 50 的倍數", """
SELECT src, count(DISTINCT coupon_discount) AS n_distinct, min(coupon_d) AS min_v, max(coupon_d) AS max_v,
  sum(CASE WHEN coupon_d < 0 THEN 1 ELSE 0 END) AS n_negative,
  sum(CASE WHEN coupon_d = 0 THEN 1 ELSE 0 END) AS n_zero,
  sum(CASE WHEN coupon_d % 50 <> 0 THEN 1 ELSE 0 END) AS n_not_multiple_of_50,
  collect_set(CASE WHEN coupon_d < 0 THEN coupon_discount END) AS negative_values
FROM orders_t GROUP BY src ORDER BY src
""")
q("S3.coupon_neg_profile", "coupon_discount 為負的列：狀態、幣別、是否同時有其他異常", """
SELECT order_status, currency, count(*) AS n,
  sum(CASE WHEN amount_d < 0 THEN 1 ELSE 0 END) AS also_negative_amount
FROM orders_t WHERE coupon_d < 0 GROUP BY order_status, currency ORDER BY order_status, currency
""")
q("S3.coupon_neg_examples", "coupon_discount 為負的範例", """
SELECT order_id, order_status, currency, amount, coupon_discount, order_created_at
FROM orders_t WHERE coupon_d < 0 ORDER BY order_id LIMIT 3
""")
q("S3.members_cat", "members 類別欄位值域", """
SELECT 'member_level' AS col, member_level AS v, count(*) AS n FROM members GROUP BY member_level
UNION ALL SELECT 'city', city, count(*) FROM members GROUP BY city
UNION ALL SELECT 'extract_date', extract_date, count(*) FROM members GROUP BY extract_date
ORDER BY col, v
""")
q("S3.products_cat", "products 類別欄位值域", """
SELECT 'product_type' AS col, product_type AS v, count(*) AS n FROM products GROUP BY product_type
UNION ALL SELECT 'destination', concat(destination_country, '/', destination_city), count(*) FROM products
  GROUP BY destination_country, destination_city
UNION ALL SELECT 'is_active', is_active, count(*) FROM products GROUP BY is_active
ORDER BY col, v
""")

# ---------------------------------------------------------------------------------------------
section("S4 金額值域與分布")
q("S4.amount_dist", "amount 依來源檔×幣別的分布（percentile_approx）", """
SELECT src, currency, count(*) AS n, min(amount_d) AS min_v,
  percentile_approx(amount_d, 0.25) AS p25, percentile_approx(amount_d, 0.5) AS p50,
  percentile_approx(amount_d, 0.75) AS p75, percentile_approx(amount_d, 0.99) AS p99, max(amount_d) AS max_v,
  sum(CASE WHEN amount_d < 0 THEN 1 ELSE 0 END) AS n_neg, sum(CASE WHEN amount_d = 0 THEN 1 ELSE 0 END) AS n_zero
FROM orders_t GROUP BY src, currency ORDER BY src, currency
""")

# 金額模型：amount × 匯率 ≈ base_price_twd × quantity × (0.85～1.25)。
# 這裡用「同日匯率」換算；TWD 與 NTD 用 1（NTD 是否等同 TWD 本身就是要驗證的假設，見 S4.ntd）。
make_view("""
CREATE OR REPLACE TEMP VIEW orders_ratio AS
SELECT o.*, p.base_price_twd, try_cast(p.base_price_twd AS DOUBLE) AS bp,
  CASE WHEN o.currency IN ('TWD','NTD') THEN 1.0 ELSE try_cast(f.rate_to_twd AS DOUBLE) END AS fx,
  o.amount_d * CASE WHEN o.currency IN ('TWD','NTD') THEN 1.0 ELSE try_cast(f.rate_to_twd AS DOUBLE) END
    / (try_cast(p.base_price_twd AS DOUBLE) * o.qty_i) AS ratio
FROM orders_t o
LEFT JOIN products p ON o.product_id = p.product_id
LEFT JOIN fx_rates f ON f.currency = o.currency AND f.rate_date = date_format(o.co_ts, 'yyyy-MM-dd')
""")
spark.sql("CACHE TABLE orders_ratio")
q("S4.ratio_dist", "金額比值 ratio = amount×同日匯率 ÷ (base_price_twd×quantity) 的分布（只看 amount>0 且有產品、有匯率）", """
SELECT src, currency, count(*) AS n,
  round(min(ratio), 4) AS min_r, round(percentile_approx(ratio, 0.001), 4) AS p001,
  round(percentile_approx(ratio, 0.5), 4) AS p50, round(percentile_approx(ratio, 0.999), 4) AS p999,
  round(max(ratio), 4) AS max_r
FROM orders_ratio WHERE amount_d > 0 AND ratio IS NOT NULL AND ratio BETWEEN 0 AND 10
GROUP BY src, currency ORDER BY src, currency
""")
q("S4.ratio_buckets", "比值落點分組：正常區間 [0.8, 1.3] 以外的列", """
SELECT src, currency,
  CASE WHEN ratio IS NULL THEN 'no_ratio(缺產品或匯率)'
       WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative, |ratio| in normal range'
       WHEN ratio < 0 THEN 'negative, other'
       WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
       WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about x1000 (ratio/1000 in normal range)'
       ELSE 'other_outlier' END AS bucket,
  count(*) AS n
FROM orders_ratio GROUP BY 1, 2, 3 HAVING bucket <> 'normal' ORDER BY src, currency, bucket
""")
q("S4.neg_examples", "負數金額範例（與正常列只差負號：|ratio| 在正常區間）", """
SELECT order_id, order_status, currency, amount, quantity, base_price_twd, round(ratio, 4) AS ratio
FROM orders_ratio WHERE amount_d < 0 ORDER BY order_id LIMIT 3
""")
q("S4.neg_status", "負數金額的 order_status 分布、同 order_id 是否另有正數列", """
SELECT o.order_status, count(*) AS n,
  sum(CASE WHEN EXISTS (SELECT 1 FROM orders_t x WHERE x.order_id = o.order_id AND x.amount_d > 0) THEN 1 ELSE 0 END)
    AS same_id_has_positive_row
FROM orders_t o WHERE o.amount_d < 0 GROUP BY o.order_status ORDER BY o.order_status
""")
q("S4.x1000_examples", "疑似 ×1000 的範例", """
SELECT order_id, currency, amount, quantity, base_price_twd, round(ratio, 1) AS ratio, round(ratio/1000, 4) AS ratio_div_1000
FROM orders_ratio WHERE ratio > 100 ORDER BY amount_d DESC LIMIT 3
""")
q("S4.x1000_mult", "疑似 ×1000 的列中，amount 是 1000 的倍數者", """
SELECT currency, count(*) AS n, sum(CASE WHEN amount_d % 1000 = 0 THEN 1 ELSE 0 END) AS multiple_of_1000,
  sum(CASE WHEN amount_d % 10 = 0 THEN 1 ELSE 0 END) AS multiple_of_10
FROM orders_ratio WHERE ratio > 100 GROUP BY currency ORDER BY currency
""")
q("S4.ntd", "NTD 與 TWD 比較：若 NTD 只是 TWD 的別名，ratio（以 1:1 換算）應與 TWD 相同", """
SELECT currency, count(*) AS n, round(percentile_approx(ratio, 0.01), 4) AS p01,
  round(percentile_approx(ratio, 0.5), 4) AS p50, round(percentile_approx(ratio, 0.99), 4) AS p99
FROM orders_ratio WHERE src='base' AND currency IN ('TWD','NTD') AND amount_d > 0 AND ratio < 10
GROUP BY currency ORDER BY currency
""")
q("S4.ntd_examples", "NTD 範例與其他屬性分布（channel）", """
SELECT channel, count(*) AS n, min(order_id) AS example_id FROM orders_t WHERE currency='NTD' GROUP BY channel ORDER BY channel
""")
q("S4.coupon_vs_amount", "coupon_discount（TWD）> 訂單台幣金額的列", """
SELECT src, count(*) AS n_coupon_gt_amount_twd,
  sum(CASE WHEN amount_d < 0 THEN 1 ELSE 0 END) AS of_which_negative_amount
FROM orders_ratio WHERE coupon_d > amount_d * fx GROUP BY src ORDER BY src
""")
q("S4.coupon_vs_ratio", "amount 是折扣前還是折扣後：依 coupon 分組看 ratio，並比較 (amount_twd + coupon) 的 ratio（只看正常列）", """
SELECT CASE WHEN coupon_d < 0 THEN 'coupon=-1' WHEN coupon_d = 0 THEN 'coupon=0'
            WHEN coupon_d <= 450 THEN 'coupon 50~450' ELSE 'coupon 500~950' END AS coupon_bucket,
  count(*) AS n, round(avg(ratio), 4) AS avg_ratio, round(percentile_approx(ratio, 0.5), 4) AS p50_ratio,
  round(avg((amount_d * fx + coupon_d) / (bp * qty_i)), 4) AS avg_ratio_if_add_back_coupon,
  round(avg(coupon_d / (amount_d * fx)) * 100, 3) AS avg_coupon_pct_of_amount
FROM orders_ratio WHERE ratio BETWEEN 0.8 AND 1.3 GROUP BY 1 ORDER BY 1
""")
q("S4.ratio_edges", "ratio 的上下界是否因 coupon 而移動：coupon=0 與 coupon=950 兩組的 min/max（若 amount 為折扣後，950 組下界應略低）", """
SELECT coupon_d, count(*) AS n, round(min(ratio), 4) AS min_r, round(max(ratio), 4) AS max_r
FROM orders_ratio WHERE ratio BETWEEN 0.8 AND 1.3 AND currency IN ('TWD','NTD') AND coupon_d IN (0, 950)
GROUP BY coupon_d ORDER BY coupon_d
""")
q("S4.overlap_anomalies", "base 各金額／折扣異常是否重疊在同一列", """
SELECT
  sum(CASE WHEN amount_d < 0 AND coupon_d < 0 THEN 1 ELSE 0 END) AS neg_amount_and_neg_coupon,
  sum(CASE WHEN ratio > 100 AND coupon_d < 0 THEN 1 ELSE 0 END) AS x1000_and_neg_coupon,
  sum(CASE WHEN currency = 'NTD' AND (amount_d < 0 OR ratio > 100) THEN 1 ELSE 0 END) AS ntd_and_amount_anomaly,
  sum(CASE WHEN co_fmt <> 'iso_+08:00' AND (amount_d < 0 OR ratio > 100) THEN 1 ELSE 0 END) AS odd_datefmt_and_amount_anomaly,
  sum(CASE WHEN bp IS NULL AND (amount_d < 0) THEN 1 ELSE 0 END) AS unknown_product_and_neg
FROM orders_ratio WHERE src='base'
""")

# ---------------------------------------------------------------------------------------------
section("S5 時間：格式的時區語意、合理性")
q("S5.tz_check", "時區解讀驗證：updated_at（全為 +08:00）不應早於 order_created_at。比較不同解讀下違反筆數", """
SELECT co_fmt, count(*) AS n,
  sum(CASE WHEN upd_ts < co_ts THEN 1 ELSE 0 END) AS violations_as_parsed,
  sum(CASE WHEN upd_ts < co_ts + INTERVAL 8 HOURS THEN 1 ELSE 0 END) AS violations_if_shifted_plus_8h,
  round(min((unix_timestamp(upd_ts) - unix_timestamp(co_ts)) / 3600.0), 3) AS min_gap_hours
FROM orders_t GROUP BY co_fmt ORDER BY co_fmt
""")
q("S5.z_evidence", "Z 格式是 UTC 的證據：(1) base 重複組中兩列下單字串格式不同時，照字面解析是否同一時刻；(2) Z 格式的最小值換成台北時間是否落在官方期間 05-01 起", """
WITH g AS (SELECT order_id FROM orders_t WHERE src = 'base' GROUP BY order_id
           HAVING count(*) > 1 AND count(DISTINCT order_created_at) > 1)
SELECT a.order_id, a.order_created_at AS created_a, b.order_created_at AS created_b, a.co_fmt AS fmt_a, b.co_fmt AS fmt_b,
  a.co_ts = b.co_ts AS same_instant_as_parsed,
  (unix_timestamp(a.co_ts) - unix_timestamp(b.co_ts)) / 3600 AS diff_hours
FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src = 'base' AND b.src = 'base'
WHERE a.order_id IN (SELECT order_id FROM g) AND a.co_fmt = 'iso_+08:00' AND b.co_fmt <> 'iso_+08:00'
ORDER BY b.co_fmt, a.order_id
""")
q("S5.z_min", "Z 格式的最早／最晚值與其台北時間（session.timeZone = Asia/Taipei）", """
SELECT co_fmt, min(order_created_at) AS raw_min, min(co_ts) AS taipei_min, max(order_created_at) AS raw_max, max(co_ts) AS taipei_max,
  sum(CASE WHEN co_ts < TIMESTAMP'2026-05-01 00:00:00' THEN 1 ELSE 0 END) AS before_0501_as_parsed,
  sum(CASE WHEN substr(order_created_at, 1, 10) < '2026-05-01' THEN 1 ELSE 0 END) AS raw_date_before_0501
FROM orders_t WHERE src = 'base' GROUP BY co_fmt ORDER BY co_fmt
""")
q("S5.ranges", "各來源檔的時間範圍與合理性", """
SELECT src, count(*) AS n, min(co_ts) AS co_min, max(co_ts) AS co_max, min(upd_ts) AS upd_min, max(upd_ts) AS upd_max,
  min(dep_dt) AS dep_min, max(dep_dt) AS dep_max,
  sum(CASE WHEN upd_ts < co_ts THEN 1 ELSE 0 END) AS upd_before_created,
  sum(CASE WHEN dep_dt < to_date(co_ts) THEN 1 ELSE 0 END) AS dep_before_order_date,
  min(datediff(dep_dt, to_date(co_ts))) AS lead_days_min, max(datediff(dep_dt, to_date(co_ts))) AS lead_days_max
FROM orders_t GROUP BY src ORDER BY src
""")
q("S5.base_upd_after_period", "base（官方：2026-05-01～06-30）中 updated_at 晚於 06-30 的列", """
SELECT to_date(upd_ts) AS upd_date, count(*) AS n FROM orders_t
WHERE src='base' AND to_date(upd_ts) > DATE'2026-06-30' GROUP BY 1 ORDER BY 1
""")
q("S5.base_upd_after_period_status", "上一項的 order_status 分布", """
SELECT order_status, count(*) AS n FROM orders_t
WHERE src='base' AND to_date(upd_ts) > DATE'2026-06-30' GROUP BY 1 ORDER BY 1
""")
q("S5.inc_upd_vs_batch", "增量檔 updated_at 日期相對批次日的分布", """
SELECT src, datediff(to_date(upd_ts), batch_date) AS upd_minus_batch_days, count(*) AS n
FROM orders_t WHERE src <> 'base' GROUP BY 1, 2 ORDER BY 1, 2
""")
q("S5.inc_upd_after_batch_total", "增量檔 updated_at 晚於批次日（日期）的列數", """
SELECT src, count(*) AS n, sum(CASE WHEN to_date(upd_ts) > batch_date THEN 1 ELSE 0 END) AS upd_after_batch,
  sum(CASE WHEN to_date(upd_ts) < batch_date THEN 1 ELSE 0 END) AS upd_before_batch
FROM orders_t WHERE src <> 'base' GROUP BY src ORDER BY src
""")
q("S5.inc_upd_before_batch", "增量檔 updated_at 早於批次日的列（晚到資料）", """
SELECT src, order_id, order_status, order_created_at, updated_at,
  order_id IN (SELECT order_id FROM orders_day1) AS id_in_day1
FROM orders_t WHERE src <> 'base' AND to_date(upd_ts) < batch_date ORDER BY src, order_id
""")
q("S5.inc_created_vs_batch", "增量檔 order_created_at 相對批次日：當天新單 vs 舊單；舊單是否在 base", """
SELECT src,
  CASE WHEN to_date(co_ts) = batch_date THEN 'created_on_batch_date'
       WHEN to_date(co_ts) < batch_date AND order_id IN (SELECT order_id FROM orders_base) THEN 'older_and_id_in_base'
       WHEN to_date(co_ts) < batch_date AND order_id IN (SELECT order_id FROM orders_t WHERE src <> 'base' AND to_date(co_ts) = batch_date)
            THEN 'older_and_id_seen_as_new_in_earlier_inc'
       WHEN to_date(co_ts) < batch_date THEN 'older_and_id_never_seen'
       ELSE 'created_after_batch_date' END AS kind,
  count(*) AS n, min(order_id) AS id_min, max(order_id) AS id_max,
  min(to_date(co_ts)) AS created_min, max(to_date(co_ts)) AS created_max
FROM orders_t WHERE src <> 'base' GROUP BY 1, 2 ORDER BY 1, 2
""")
q("S5.late_new_examples", "day2 中下單日在 base 期間、但 base 沒有這個 order_id 的範例", """
SELECT order_id, member_id, order_status, order_created_at, updated_at FROM orders_t
WHERE src='day2' AND to_date(co_ts) < DATE'2026-07-01' AND order_id NOT IN (SELECT order_id FROM orders_base)
ORDER BY order_id LIMIT 3
""")
q("S5.id_vs_time", "order_id 編號與下單日是否單調：各來源檔中 base 沒有的 order_id，依 2000 號分段", """
SELECT src, floor((cast(substr(order_id, 4) AS INT) - 1) / 2000) AS id_block, count(*) AS n,
  min(order_id) AS id_min, max(order_id) AS id_max, min(to_date(co_ts)) AS created_min, max(to_date(co_ts)) AS created_max
FROM orders_t WHERE src <> 'base' AND order_id NOT IN (SELECT order_id FROM orders_base)
GROUP BY 1, 2 ORDER BY 1, 2
""")
q("S5.status_vs_departure", "order_status 與 departure_date：completed 是否都在出發日之後", """
SELECT src, order_status, count(*) AS n,
  sum(CASE WHEN dep_dt > to_date(upd_ts) THEN 1 ELSE 0 END) AS departure_after_updated_date
FROM orders_t GROUP BY 1, 2 ORDER BY 1, 2
""")

# ---------------------------------------------------------------------------------------------
section("S6 唯一性")
q("S6.orders_pk", "order_id 在各檔是否唯一", """
SELECT src, count(*) AS n_rows, count(DISTINCT order_id) AS n_ids,
  count(*) - count(DISTINCT order_id) AS extra_rows FROM orders_t GROUP BY src ORDER BY src
""")
q("S6.orders_dup_groups", "各檔內同 order_id 多列：組數，以及除 updated_at 外各欄是否一致", """
WITH g AS (
  SELECT src, order_id, count(*) AS c,
    count(DISTINCT updated_at) AS d_upd,
    count(DISTINCT order_created_at) AS d_co_raw,
    count(DISTINCT co_ts) AS d_co_instant,
    count(DISTINCT member_id) AS d_mem, count(DISTINCT amount) AS d_amt,
    count(DISTINCT order_status) AS d_status,
    count(DISTINCT concat_ws('|', product_id, channel, quantity, currency, coupon_discount, departure_date)) AS d_other
  FROM orders_t GROUP BY src, order_id HAVING count(*) > 1)
SELECT src, c AS rows_per_id,
  CASE WHEN d_mem = 1 AND d_amt = 1 AND d_co_instant = 1 THEN 'same member/amount/created instant'
       ELSE 'member/amount/created differ' END AS kind,
  count(*) AS n_groups, sum(CASE WHEN d_upd = c THEN 1 ELSE 0 END) AS upd_all_distinct,
  sum(CASE WHEN d_co_raw > d_co_instant THEN 1 ELSE 0 END) AS created_same_instant_diff_format,
  sum(CASE WHEN d_status > 1 THEN 1 ELSE 0 END) AS status_changed,
  sum(CASE WHEN d_other > 1 THEN 1 ELSE 0 END) AS other_cols_changed
FROM g GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
""")
q("S6.base_dup_gap", "base 重複組：兩列 updated_at 相差秒數", """
WITH g AS (SELECT order_id, max(upd_ts) AS mx, min(upd_ts) AS mn FROM orders_t WHERE src='base'
           GROUP BY order_id HAVING count(*) > 1)
SELECT count(*) AS n_groups, min(unix_timestamp(mx) - unix_timestamp(mn)) AS min_gap_s,
  max(unix_timestamp(mx) - unix_timestamp(mn)) AS max_gap_s FROM g
""")
q("S6.base_dup_examples", "base 重複組範例（含 created 格式不同但同一時刻者）", """
SELECT order_id, member_id, order_status, amount, order_created_at, updated_at FROM orders_t
WHERE src='base' AND order_id IN ('ORD00000984', 'ORD00012637', 'ORD00013776') ORDER BY order_id, updated_at
""")
q("S6.inc_dup_collision_examples", "增量檔內同 order_id、但 member/amount/created 不同（撞號）的組", """
WITH g AS (SELECT src, order_id FROM orders_t WHERE src <> 'base' GROUP BY src, order_id
           HAVING count(*) > 1 AND (count(DISTINCT member_id) > 1 OR count(DISTINCT amount) > 1 OR count(DISTINCT co_ts) > 1))
SELECT o.src, o.order_id, o.member_id, o.amount, o.order_status, o.order_created_at, o.updated_at,
  o.order_id IN (SELECT order_id FROM orders_base) AS id_in_base
FROM orders_t o JOIN g ON o.src = g.src AND o.order_id = g.order_id ORDER BY o.src, o.order_id, o.updated_at
""")
q("S6.members_pk", "members：(member_id, extract_date) 是否唯一", """
SELECT count(*) AS n_rows, count(DISTINCT member_id) AS n_members,
  count(DISTINCT member_id, extract_date) AS n_member_dates,
  count(*) - count(DISTINCT member_id, extract_date) AS extra_rows
FROM members
""")
q("S6.members_same_day_dup", "同一 member_id、同一 extract_date 多列：哪些欄位不同", """
WITH g AS (SELECT member_id, extract_date, count(*) AS c,
    count(DISTINCT member_level) AS d_level, count(DISTINCT city) AS d_city,
    count(DISTINCT member_name) AS d_name, count(DISTINCT birth_date) AS d_birth, count(DISTINCT register_date) AS d_reg
  FROM members GROUP BY member_id, extract_date HAVING count(*) > 1)
SELECT extract_date, c AS rows_per_key, count(*) AS n_groups,
  sum(CASE WHEN d_level > 1 THEN 1 ELSE 0 END) AS level_differs, sum(CASE WHEN d_city > 1 THEN 1 ELSE 0 END) AS city_differs,
  sum(CASE WHEN d_name > 1 THEN 1 ELSE 0 END) AS name_differs, sum(CASE WHEN d_birth > 1 THEN 1 ELSE 0 END) AS birth_differs,
  sum(CASE WHEN d_reg > 1 THEN 1 ELSE 0 END) AS register_differs
FROM g GROUP BY 1, 2 ORDER BY 1, 2
""")
q("S6.members_same_day_examples", "同日重複快照範例", """
SELECT m.* FROM members m JOIN (SELECT member_id, extract_date FROM members GROUP BY 1, 2 HAVING count(*) > 1) d
  ON m.member_id = d.member_id AND m.extract_date = d.extract_date
ORDER BY m.member_id, m.member_level LIMIT 4
""")
q("S6.products_pk", "products：product_id、product_name 是否唯一", """
SELECT count(*) AS n_rows, count(DISTINCT product_id) AS n_ids, count(DISTINCT product_name) AS n_names,
  (SELECT count(*) FROM (SELECT product_name FROM products GROUP BY 1 HAVING count(*) > 1)) AS names_used_by_multiple_ids
FROM products
""")
q("S6.products_dup_name_examples", "同名不同 product_id 的範例：其他欄位是否相同", """
SELECT p.* FROM products p JOIN (SELECT product_name FROM products GROUP BY 1 HAVING count(*) > 1) d
  ON p.product_name = d.product_name ORDER BY p.product_name, p.product_id LIMIT 4
""")
q("S6.fx_pk", "fx_rates：(rate_date, currency) 是否唯一、日期是否連續", """
SELECT currency, count(*) AS n, count(DISTINCT rate_date) AS n_dates,
  datediff(max(to_date(rate_date)), min(to_date(rate_date))) + 1 AS span_days
FROM fx_rates GROUP BY currency ORDER BY currency
""")

# ---------------------------------------------------------------------------------------------
section("S7 參照完整性")
q("S7.fk", "orders → products / members / fx（幣別、幣別＋下單日）", """
SELECT o.src, count(*) AS n,
  sum(CASE WHEN p.product_id IS NULL THEN 1 ELSE 0 END) AS product_missing,
  sum(CASE WHEN p.is_active = 'N' THEN 1 ELSE 0 END) AS product_inactive,
  sum(CASE WHEN o.member_id NOT IN (SELECT member_id FROM members) THEN 1 ELSE 0 END) AS member_missing,
  sum(CASE WHEN o.currency NOT IN (SELECT currency FROM fx_rates) THEN 1 ELSE 0 END) AS currency_not_in_fx,
  sum(CASE WHEN o.currency IN (SELECT currency FROM fx_rates) AND NOT EXISTS (
        SELECT 1 FROM fx_rates f WHERE f.currency = o.currency AND f.rate_date = date_format(o.co_ts, 'yyyy-MM-dd'))
      THEN 1 ELSE 0 END) AS fx_date_missing
FROM orders_t o LEFT JOIN products p ON o.product_id = p.product_id GROUP BY o.src ORDER BY o.src
""")
q("S7.currency_not_in_fx", "幣別不在 fx 的分布", """
SELECT src, currency, count(*) AS n FROM orders_t WHERE currency NOT IN (SELECT currency FROM fx_rates)
GROUP BY 1, 2 ORDER BY 1, 2
""")
q("S7.unknown_products", "不在主檔的 product_id：形態與數量", r"""
SELECT count(*) AS n_rows, count(DISTINCT product_id) AS n_ids, min(product_id) AS id_min, max(product_id) AS id_max,
  sum(CASE WHEN product_id RLIKE '^P0\\d{4}$' THEN 1 ELSE 0 END) AS looks_like_P0xxxx,
  collect_set(order_status) AS statuses
FROM orders_t o WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id = o.product_id)
""")
q("S7.unknown_products_examples", "不在主檔的 product_id 範例", """
SELECT order_id, product_id, currency, amount, quantity, order_status FROM orders_t o
WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id = o.product_id) ORDER BY order_id LIMIT 3
""")
q("S7.member_snapshot_coverage", "下單時點是否已有會員快照（下單日 >= 最早 extract_date 2026-04-30）、會員註冊日是否晚於下單", """
SELECT o.src, count(*) AS n,
  sum(CASE WHEN to_date(o.co_ts) < m.first_extract THEN 1 ELSE 0 END) AS order_before_first_snapshot,
  sum(CASE WHEN to_date(o.co_ts) < m.min_register THEN 1 ELSE 0 END) AS order_before_member_register
FROM orders_t o JOIN (SELECT member_id, min(to_date(extract_date)) AS first_extract, min(to_date(register_date)) AS min_register
                      FROM members GROUP BY member_id) m ON o.member_id = m.member_id
GROUP BY o.src ORDER BY o.src
""")

# ---------------------------------------------------------------------------------------------
section("S8 跨檔一致性：增量 vs base、增量 vs 增量")
# base 有 40 個 order_id 各兩列（S6），直接 join 會讓列數翻倍；比對時 base 每個 order_id 只取 updated_at 最新的一列。
make_view("""
CREATE OR REPLACE TEMP VIEW base_one AS
SELECT * FROM (SELECT o.*, row_number() OVER (PARTITION BY order_id ORDER BY upd_ts DESC) AS rn
               FROM orders_t o WHERE src = 'base') WHERE rn = 1
""")
q("S8.inc_vs_base_cols", "增量檔與 base 同 order_id 的列：逐欄與 base 相同的列數", """
SELECT i.src, count(*) AS n_rows, count(DISTINCT i.order_id) AS n_ids,
  sum(CASE WHEN i.member_id = b.member_id THEN 1 ELSE 0 END) AS same_member,
  sum(CASE WHEN i.co_ts = b.co_ts THEN 1 ELSE 0 END) AS same_created_instant,
  sum(CASE WHEN to_date(i.co_ts) = to_date(b.co_ts) THEN 1 ELSE 0 END) AS same_created_date,
  sum(CASE WHEN i.amount = b.amount THEN 1 ELSE 0 END) AS same_amount,
  sum(CASE WHEN i.product_id = b.product_id THEN 1 ELSE 0 END) AS same_product,
  sum(CASE WHEN i.currency = b.currency THEN 1 ELSE 0 END) AS same_currency,
  sum(CASE WHEN i.channel = b.channel THEN 1 ELSE 0 END) AS same_channel,
  sum(CASE WHEN i.quantity = b.quantity THEN 1 ELSE 0 END) AS same_quantity,
  sum(CASE WHEN i.departure_date = b.departure_date THEN 1 ELSE 0 END) AS same_departure,
  sum(CASE WHEN i.order_status = b.order_status THEN 1 ELSE 0 END) AS same_status,
  sum(CASE WHEN i.upd_ts > b.upd_ts THEN 1 ELSE 0 END) AS inc_newer_than_base
FROM orders_t i JOIN base_one b ON i.order_id = b.order_id
WHERE i.src <> 'base' GROUP BY i.src ORDER BY i.src
""")
q("S8.inc_vs_base_expected", "對照組：若欄位隨機獨立，同 channel 的機率約 1/4、同 quantity 約 1/4、同 currency 約 0.67²+0.22²+0.11²", """
SELECT 'base 內 channel 各值佔比平方和' AS metric, round(sum(p * p), 3) AS v FROM (
  SELECT count(*) / (SELECT count(*) FROM orders_base) AS p FROM orders_base GROUP BY channel)
UNION ALL SELECT 'base 內 currency 各值佔比平方和', round(sum(p * p), 3) FROM (
  SELECT count(*) / (SELECT count(*) FROM orders_base) AS p FROM orders_base GROUP BY currency)
""")
q("S8.inc_vs_base_status", "增量檔與 base 同 order_id：增量列的狀態分布（及 base 狀態→增量狀態）", """
SELECT i.src, b.order_status AS base_status, i.order_status AS inc_status, count(*) AS n
FROM orders_t i JOIN (SELECT DISTINCT order_id, order_status FROM orders_t WHERE src='base') b ON i.order_id = b.order_id
WHERE i.src <> 'base' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
""")
q("S8.inc_vs_base_examples", "增量 vs base 同 order_id 範例", """
SELECT src, order_id, member_id, product_id, amount, currency, order_status, order_created_at, updated_at
FROM orders_t WHERE order_id IN ('ORD00005192') ORDER BY upd_ts
""")
q("S8.inc_vs_base_upd_not_newer_cnt", "增量列 updated_at 不晚於 base 同 id 列（base 取最新一列）的筆數，以及該 base 列 updated_at 是否已在 07-01 之後", """
SELECT i.src, count(*) AS n, sum(CASE WHEN to_date(b.upd_ts) > DATE'2026-06-30' THEN 1 ELSE 0 END) AS base_upd_after_0630
FROM orders_t i JOIN base_one b ON i.order_id = b.order_id
WHERE i.src <> 'base' AND i.upd_ts <= b.upd_ts GROUP BY i.src ORDER BY i.src
""")
q("S8.inc_vs_base_upd_not_newer", "增量列 updated_at 不晚於 base 同 id 列的範例", """
SELECT i.src, i.order_id, b.updated_at AS base_updated_at, i.updated_at AS inc_updated_at, b.order_status AS base_status, i.order_status AS inc_status
FROM orders_t i JOIN base_one b ON i.order_id = b.order_id
WHERE i.src <> 'base' AND i.upd_ts <= b.upd_ts ORDER BY i.src, i.order_id LIMIT 3
""")
q("S8.inc_vs_inc", "跨增量檔同 order_id：是否在 base、member/amount/created 是否一致", """
SELECT a.src AS src_a, b.src AS src_b, (a.order_id IN (SELECT order_id FROM orders_base)) AS id_in_base,
  count(*) AS n_pairs, count(DISTINCT a.order_id) AS n_ids,
  sum(CASE WHEN a.member_id = b.member_id AND a.amount = b.amount AND a.co_ts = b.co_ts THEN 1 ELSE 0 END) AS same_member_amount_created,
  sum(CASE WHEN b.upd_ts > a.upd_ts THEN 1 ELSE 0 END) AS later_file_newer
FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src < b.src
WHERE a.src <> 'base' AND b.src <> 'base' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
""")
q("S8.inc_vs_inc_status_order", "跨增量檔、不在 base 的 order_id（day1→day2）：兩端的狀態對，以及後一個檔案的 updated_at 是否較新", """
SELECT a.src AS src_a, b.src AS src_b, a.order_status AS status_in_earlier_file, b.order_status AS status_in_later_file,
  CASE WHEN b.upd_ts > a.upd_ts THEN 'later_file_newer' WHEN b.upd_ts < a.upd_ts THEN 'later_file_older' ELSE 'same' END AS upd_order,
  count(*) AS n_pairs, min(a.order_id) AS example_id
FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src < b.src
WHERE a.src <> 'base' AND b.src <> 'base' AND a.order_id NOT IN (SELECT order_id FROM orders_base)
GROUP BY 1, 2, 3, 4, 5 ORDER BY 1, 2, 3, 4, 5
""")
q("S8.inc_vs_inc_status_examples", "上一項的範例", """
SELECT src, order_id, order_status, updated_at FROM orders_t
WHERE order_id IN (SELECT a.order_id FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id
                   WHERE a.src = 'day1' AND b.src = 'day2' AND a.order_id NOT IN (SELECT order_id FROM orders_base))
ORDER BY order_id, src LIMIT 6
""")
q("S8.inc_dup_consistent", "增量檔內同 order_id、四欄（member/amount/created/product）一致的組數（跨三檔合計）", """
WITH g AS (SELECT src, order_id, count(*) AS c,
    count(DISTINCT member_id) AS dm, count(DISTINCT amount) AS da, count(DISTINCT co_ts) AS dc, count(DISTINCT product_id) AS dp
  FROM orders_t WHERE src <> 'base' GROUP BY src, order_id HAVING count(*) > 1)
SELECT count(*) AS n_groups, sum(CASE WHEN dm = 1 AND da = 1 AND dc = 1 AND dp = 1 THEN 1 ELSE 0 END) AS four_cols_same
FROM g
""")
q("S8.status_transitions", "狀態轉移（依 updated_at 排序的相鄰兩列，所有來源合併）：倒退或終態後再變的轉移", """
WITH s AS (SELECT src, order_id, order_status, upd_ts, member_id,
    lag(order_status) OVER (PARTITION BY order_id ORDER BY upd_ts, src) AS prev_status,
    lag(member_id) OVER (PARTITION BY order_id ORDER BY upd_ts, src) AS prev_member
  FROM orders_t)
SELECT prev_status, order_status, (member_id = prev_member) AS same_member, count(*) AS n
FROM s WHERE prev_status IS NOT NULL GROUP BY 1, 2, 3 ORDER BY 3 DESC, 1, 2
""")

# ---------------------------------------------------------------------------------------------
section("S9 members 細項")
q("S9.birth_1900", "birth_date = 1900-01-01（疑似預設值）分布，及之後快照是否改成真實日期", """
SELECT extract_date, count(*) AS n_rows, sum(CASE WHEN birth_date = '1900-01-01' THEN 1 ELSE 0 END) AS birth_1900,
  sum(CASE WHEN city = 'N/A' THEN 1 ELSE 0 END) AS city_na,
  sum(CASE WHEN birth_date = '1900-01-01' AND city = 'N/A' THEN 1 ELSE 0 END) AS both
FROM members GROUP BY extract_date ORDER BY extract_date
""")
q("S9.birth_dist", "birth_date 年份分布的極端（1900 以外的最早／最晚）", """
SELECT min(CASE WHEN birth_date <> '1900-01-01' THEN birth_date END) AS earliest_real, max(birth_date) AS latest,
  count(DISTINCT birth_date) AS n_distinct
FROM members
""")
q("S9.attr_change", "多快照會員：哪些屬性在快照間變過（不可變屬性變動 = 可疑）", """
WITH s AS (SELECT member_id, count(*) AS c, count(DISTINCT member_name) AS dn, count(DISTINCT birth_date) AS db,
    count(DISTINCT register_date) AS dr, count(DISTINCT member_level) AS dl, count(DISTINCT city) AS dc
  FROM members GROUP BY member_id HAVING count(*) > 1)
SELECT count(*) AS multi_snapshot_members, sum(CASE WHEN dn > 1 THEN 1 ELSE 0 END) AS name_changed,
  sum(CASE WHEN db > 1 THEN 1 ELSE 0 END) AS birth_changed, sum(CASE WHEN dr > 1 THEN 1 ELSE 0 END) AS register_changed,
  sum(CASE WHEN dl > 1 THEN 1 ELSE 0 END) AS level_changed, sum(CASE WHEN dc > 1 THEN 1 ELSE 0 END) AS city_changed
FROM s
""")
q("S9.birth_change_detail", "birth_date 變過的會員：涉及 1900-01-01 的列數，以及其中位於該會員最早快照的列數（方向見 S9.birth_change_direction）", """
WITH x AS (SELECT member_id FROM members GROUP BY member_id HAVING count(DISTINCT birth_date) > 1)
SELECT count(DISTINCT member_id) AS n_members,
  sum(CASE WHEN birth_date = '1900-01-01' THEN 1 ELSE 0 END) AS rows_1900,
  sum(CASE WHEN birth_date = '1900-01-01' AND extract_date = (SELECT min(extract_date) FROM members m2 WHERE m2.member_id = m.member_id)
      THEN 1 ELSE 0 END) AS rows_1900_in_earliest_snapshot
FROM members m WHERE member_id IN (SELECT member_id FROM x)
""")
q("S9.birth_change_examples", "birth_date 變動範例", """
SELECT member_id, birth_date, city, extract_date FROM members
WHERE member_id IN ('M000552', 'M000708') ORDER BY member_id, extract_date
""")
q("S9.birth_change_direction", "birth_date 變動的方向：依 extract_date 排序相鄰兩列，1900 → 真實日期 vs 真實日期 → 1900", """
WITH s AS (SELECT member_id, extract_date, birth_date,
    lag(birth_date) OVER (PARTITION BY member_id ORDER BY extract_date, member_level) AS prev_birth
  FROM members)
SELECT CASE WHEN prev_birth = '1900-01-01' THEN '1900 -> real'
            WHEN birth_date = '1900-01-01' THEN 'real -> 1900'
            ELSE 'real -> other real' END AS direction,
  count(DISTINCT member_id) AS n_members, count(*) AS n_transitions,
  slice(array_sort(collect_set(member_id)), 1, 3) AS example_members
FROM s WHERE prev_birth IS NOT NULL AND prev_birth <> birth_date GROUP BY 1 ORDER BY 1
""")
q("S9.birth_real_to_1900_examples", "真實日期 → 1900 的範例", """
SELECT member_id, birth_date, city, member_level, extract_date FROM members
WHERE member_id IN ('M001647', 'M003842', 'M004004') ORDER BY member_id, extract_date
""")
q("S9.city_na_change", "city = N/A 的會員在其他快照是否有真實縣市", """
WITH x AS (SELECT DISTINCT member_id FROM members WHERE city = 'N/A')
SELECT (SELECT count(*) FROM members WHERE city = 'N/A') AS rows_with_na, count(*) AS members_with_na,
  sum(CASE WHEN member_id IN (SELECT member_id FROM members WHERE city <> 'N/A') THEN 1 ELSE 0 END) AS also_have_real_city
FROM x
""")
q("S9.dates_logic", "members 日期邏輯：註冊早於出生、註冊晚於快照日、註冊時年齡", """
SELECT count(*) AS n,
  sum(CASE WHEN to_date(register_date) < to_date(birth_date) THEN 1 ELSE 0 END) AS register_before_birth,
  sum(CASE WHEN to_date(register_date) > to_date(extract_date) THEN 1 ELSE 0 END) AS register_after_extract,
  sum(CASE WHEN birth_date <> '1900-01-01' AND months_between(to_date(register_date), to_date(birth_date)) / 12 < 18 THEN 1 ELSE 0 END)
    AS under18_at_register_excl_1900,
  round(min(CASE WHEN birth_date <> '1900-01-01' THEN months_between(to_date(register_date), to_date(birth_date)) / 12 END), 1)
    AS min_age_at_register
FROM members
""")
q("S9.snapshot_pattern", "後續快照（05-31、06-30）的列：與前一次快照相比是否有任何屬性變化", """
WITH s AS (SELECT m.*, lag(concat_ws('|', member_name, member_level, city, birth_date, register_date))
      OVER (PARTITION BY member_id ORDER BY extract_date, member_level) AS prev_attrs,
    lag(extract_date) OVER (PARTITION BY member_id ORDER BY extract_date, member_level) AS prev_extract
  FROM members m)
SELECT extract_date, count(*) AS n_rows,
  sum(CASE WHEN prev_attrs IS NULL THEN 1 ELSE 0 END) AS first_snapshot_of_member,
  sum(CASE WHEN prev_attrs IS NOT NULL AND prev_extract <> extract_date
            AND prev_attrs = concat_ws('|', member_name, member_level, city, birth_date, register_date) THEN 1 ELSE 0 END)
    AS unchanged_vs_previous_snapshot
FROM s GROUP BY extract_date ORDER BY extract_date
""")

# ---------------------------------------------------------------------------------------------
section("S10 fx 涵蓋")
q("S10.fx_coverage", "需要換匯的訂單（USD/JPY）其下單日都有匯率；匯率日期是否涵蓋 order_created_at 的範圍", """
SELECT (SELECT min(rate_date) FROM fx_rates) AS fx_min, (SELECT max(rate_date) FROM fx_rates) AS fx_max,
  min(to_date(co_ts)) AS order_date_min, max(to_date(co_ts)) AS order_date_max
FROM orders_t WHERE currency IN ('USD','JPY')
""")
q("S10.fx_daily_change", "匯率日變動幅度（偵測異常跳動）", """
WITH f AS (SELECT currency, to_date(rate_date) AS d, try_cast(rate_to_twd AS DOUBLE) AS r,
    lag(try_cast(rate_to_twd AS DOUBLE)) OVER (PARTITION BY currency ORDER BY rate_date) AS prev_r FROM fx_rates)
SELECT currency, round(max(abs(r / prev_r - 1)) * 100, 3) AS max_daily_change_pct,
  round(percentile_approx(abs(r / prev_r - 1), 0.5) * 100, 3) AS median_daily_change_pct
FROM f WHERE prev_r IS NOT NULL GROUP BY currency ORDER BY currency
""")

print("\n[DONE] profile_sources.py 完成")
spark.stop()
