"""Part A｜A-3 資料品質檢核報告的查詢腳本（可重跑）。

用法（在 repo 根目錄 LionTest/）：
    uv run python LionDEExam/submission/part_a/profiling/data_quality_queries.py
    uv run python LionDEExam/submission/part_a/profiling/data_quality_queries.py --skip-pipeline   # 只跑偵測查詢（DuckDB，約 3 分鐘）

兩段：
1. 偵測（DuckDB 直接查 CSV）：每個問題一個標籤 [Q-xxx]，印出 SQL 原文與輸出。
   - 所有欄位以字串讀入（all_varchar），才看得到原始值；數值轉換用 TRY_CAST。
   - 時間：`+08:00` 照標記、結尾 `Z` 當 UTC、`YYYY/MM/DD HH:MM:SS` 當台北時間（與管線的
     timeparse.parse_source_timestamp 同一套規則）；「日期」一律指台北日期。
   - [Q-POST.xxx]：用 DuckDB 照管線的規則重算「寫進 fact 之後」的結果（view `fact_sim`），
     不啟動 Spark。重算的總數要和管線實跑（part_a/README.md「三天實跑的對帳」）完全相同，
     見 [Q-POST.totals]；相同才拿它算各問題在 fact 裡的筆數與金額。
2. 處理後的驗證（呼叫 Part A 管線，PySpark＋Delta）：[P-xxx] 標籤。
   - 把 base 跑進 /tmp/liontest_a3/wh（每次重跑前清空），印對帳數字，再查 fact、訂單隔離表、
     會員隔離表、dim_member 裡各問題剩幾列，以及 fact 的 Delta CHECK 約束。
   - 接著依序跑 day1～day3（load_incremental），印各批對帳與隔離類別，最後看 L4 的 25 張單在
     fact 的狀態，以及排除金額人工確認清單前後的 amount_twd 總和（AMOUNT_EXCLUDING_REVIEW_SQL）。
   - dim_member 沒有「未知會員」（-1）列：訂單對不到會員版本時整列進訂單隔離表（member_missing）。

本腳本只讀 candidate_package，只寫 /tmp。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "LionDEExam" / "candidate_package" / "dataset"
PART_A = REPO / "LionDEExam" / "submission" / "part_a"
WAREHOUSE = Path("/tmp/liontest_a3/wh")

FILES = {
    "base": ("orders_base.csv", None),
    "day1": ("orders_incremental_day1.csv", "2026-07-01"),
    "day2": ("orders_incremental_day2.csv", "2026-07-02"),
    "day3": ("orders_incremental_day3.csv", "2026-07-03"),
}


def csv(name: str) -> str:
    return f"read_csv('{DATA / name}', all_varchar=true, header=true)"


# ---------------------------------------------------------------- 共用 view

TS_NORM = """CASE
      WHEN regexp_full_match({c}, '\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\+08:00') THEN {c}
      WHEN regexp_full_match({c}, '\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}Z') THEN replace({c}, 'Z', '+00:00')
      WHEN regexp_full_match({c}, '\\d{{4}}/\\d{{2}}/\\d{{2}} \\d{{2}}:\\d{{2}}:\\d{{2}}') THEN replace({c}, '/', '-') || '+08:00'
    END"""

VIEWS = {
    "orders_all": " UNION ALL ".join(
        f"SELECT '{src}' AS src, {('NULL' if bd is None else repr(bd))}::DATE AS batch_date, * FROM {csv(fn)}"
        for src, (fn, bd) in FILES.items()
    ),
    "orders_t": f"""
    SELECT *,
      CASE WHEN regexp_full_match(order_created_at, '.*\\+08:00') THEN 'plus0800'
           WHEN regexp_full_match(order_created_at, '.*Z') THEN 'iso_Z'
           WHEN regexp_full_match(order_created_at, '\\d{{4}}/\\d{{2}}/\\d{{2}} .*') THEN 'slash_no_tz'
           ELSE 'other' END AS co_fmt,
      CAST(({TS_NORM.format(c="order_created_at")}) AS TIMESTAMPTZ) AS co_ts,
      CAST(({TS_NORM.format(c="updated_at")}) AS TIMESTAMPTZ) AS upd_ts,
      CAST(timezone('Asia/Taipei', CAST(({TS_NORM.format(c="order_created_at")}) AS TIMESTAMPTZ)) AS DATE) AS co_date,
      CAST(timezone('Asia/Taipei', CAST(({TS_NORM.format(c="updated_at")}) AS TIMESTAMPTZ)) AS DATE) AS upd_date,
      TRY_CAST(departure_date AS DATE) AS dep_dt,
      TRY_CAST(amount AS DECIMAL(18,2)) AS amount_d,
      TRY_CAST(quantity AS INTEGER) AS qty_i,
      TRY_CAST(coupon_discount AS DECIMAL(18,2)) AS coupon_d
    FROM orders_all""",
    "products": f"SELECT *, TRY_CAST(base_price_twd AS DECIMAL(18,2)) AS bp FROM {csv('products.csv')}",
    "fx": f"SELECT TRY_CAST(rate_date AS DATE) AS rate_date, currency, TRY_CAST(rate_to_twd AS DECIMAL(18,6)) AS rate FROM {csv('fx_rates.csv')}",
    "members": f"SELECT * FROM {csv('members.csv')}",
    # base 每個 order_id 取一列（V7 的重複不會讓比對列數翻倍）；取 updated_at 最新那列，與管線去重一致
    "base1": """
    SELECT * FROM orders_t WHERE src = 'base'
    QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY upd_ts DESC, updated_at DESC) = 1""",
    # 金額比值：amount × 下單日（台北）匯率 ÷ (定價 × 數量)；TWD、NTD 匯率 1
    "orders_ratio": """
    SELECT o.*, p.bp,
      CASE WHEN o.currency IN ('TWD','NTD') THEN 1 ELSE f.rate END AS fx_rate,
      o.amount_d * (CASE WHEN o.currency IN ('TWD','NTD') THEN 1 ELSE f.rate END) / (p.bp * o.qty_i) AS ratio
    FROM orders_t o
    LEFT JOIN products p ON o.product_id = p.product_id
    LEFT JOIN fx f ON f.rate_date = o.co_date AND f.currency = o.currency""",
    # 照管線規則重算的 fact（不經 Spark）。本資料可以這樣簡化，是因為：
    # - base：V1（金額不大於 0）由合約擋下；V7 重複每 id 取 updated_at 最新一列。
    # - 增量：與 base 同 order_id 的列全部是撞號（[Q-J2.overlap] all_three_same = 0），整組隔離；
    #   不在 base 的 id 取 updated_at 最新一列（N1 重送去重、L4 晚到的舊事件不覆寫）。
    # - 防護性規則（值域、狀態機、找不到匯率）本資料 0 筆，不影響結果。
    # amount_twd＝round(amount × 下單日匯率, 2)；coupon -1.0 轉 NULL（V3）。
    # 是否真的等於管線結果，用 [Q-POST.totals] 和管線實跑的對帳數字比對。
    "fact_sim": """
    WITH b AS (SELECT 'base' AS wbatch, * EXCLUDE (src) FROM base1 WHERE amount_d > 0),
    n AS (SELECT src AS wbatch, * EXCLUDE (src) FROM orders_t
          WHERE src <> 'base' AND order_id NOT IN (SELECT order_id FROM base1)
          QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY upd_ts DESC) = 1),
    u AS (SELECT * FROM b UNION ALL BY NAME SELECT * FROM n)
    SELECT u.*, p.bp, p.is_active,
      CASE WHEN u.currency IN ('TWD','NTD') THEN 1 ELSE f.rate END AS fx_rate,
      round(u.amount_d * (CASE WHEN u.currency IN ('TWD','NTD') THEN 1 ELSE f.rate END), 2) AS amount_twd,
      CASE WHEN u.coupon_d = -1 THEN NULL ELSE u.coupon_d END AS coupon_clean
    FROM u LEFT JOIN products p USING (product_id)
    LEFT JOIN fx f ON f.rate_date = u.co_date AND f.currency = u.currency""",
}

# 會員等級的業務順序（中文字串不能直接排序）
LEVEL_RANK = "CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END"

RATIO_BUCKET = """CASE WHEN ratio IS NULL THEN 'no_ratio'
         WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative_abs_normal'
         WHEN ratio < 0 THEN 'negative_other'
         WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
         WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about_x1000'
         ELSE 'other_outlier' END"""

# ---------------------------------------------------------------- 偵測查詢
# (標籤, 對應問題, SQL)

QUERIES: list[tuple[str, str, str]] = [
    # ---- 0. 讀取與合約
    (
        "Q-000.rows",
        "全部：檔案列數、BOM 是否被略過",
        """
SELECT src, count(*) AS n_rows, count(DISTINCT order_id) AS n_ids FROM orders_all GROUP BY src ORDER BY src""",
    ),
    (
        "Q-001.contract",
        "全部：列層級合約違規（空值、型別、時間格式）",
        """
SELECT src,
  sum(CASE WHEN order_id IS NULL OR trim(order_id) = '' OR member_id IS NULL OR trim(member_id) = ''
            OR product_id IS NULL OR trim(product_id) = '' OR amount IS NULL OR updated_at IS NULL THEN 1 ELSE 0 END) AS required_blank,
  sum(CASE WHEN NOT regexp_full_match(quantity, '[+-]?\\d+') THEN 1 ELSE 0 END) AS qty_not_int,
  sum(CASE WHEN NOT regexp_full_match(amount, '[+-]?\\d+(\\.\\d{1,2})?') THEN 1 ELSE 0 END) AS amount_bad_or_gt2dp,
  sum(CASE WHEN NOT regexp_full_match(coupon_discount, '[+-]?\\d+(\\.\\d{1,2})?') THEN 1 ELSE 0 END) AS coupon_bad,
  sum(CASE WHEN co_ts IS NULL THEN 1 ELSE 0 END) AS created_unparseable,
  sum(CASE WHEN upd_ts IS NULL THEN 1 ELSE 0 END) AS updated_unparseable,
  sum(CASE WHEN departure_date IS NOT NULL AND dep_dt IS NULL THEN 1 ELSE 0 END) AS departure_bad
FROM orders_t GROUP BY src ORDER BY src""",
    ),
    (
        "Q-002.domains",
        "全部：狀態、通路、幣別的值域",
        """
SELECT src, list_sort(list(DISTINCT order_status)) AS statuses, list_sort(list(DISTINCT channel)) AS channels,
  list_sort(list(DISTINCT currency)) AS currencies, min(qty_i) AS qty_min, max(qty_i) AS qty_max
FROM orders_t GROUP BY src ORDER BY src""",
    ),
    # ---- 訂單身分
    (
        "Q-V7.groups",
        "V7：base 同 order_id 多列",
        """
WITH g AS (
  SELECT order_id, count(*) AS c,
    count(DISTINCT member_id) AS d_mem, count(DISTINCT amount) AS d_amt, count(DISTINCT co_ts) AS d_co_instant,
    count(DISTINCT order_created_at) AS d_co_raw, count(DISTINCT order_status) AS d_status,
    count(DISTINCT concat_ws('|', product_id, channel, quantity, currency, coupon_discount, departure_date)) AS d_other,
    date_diff('second', min(upd_ts), max(upd_ts)) AS gap_s
  FROM orders_t WHERE src = 'base' GROUP BY order_id HAVING count(*) > 1)
SELECT count(*) AS n_groups, sum(c) - count(*) AS extra_rows,
  sum(CASE WHEN d_mem = 1 AND d_amt = 1 AND d_co_instant = 1 AND d_status = 1 AND d_other = 1 THEN 1 ELSE 0 END) AS identical_except_updated_at,
  sum(CASE WHEN d_co_raw > 1 THEN 1 ELSE 0 END) AS created_same_instant_diff_format,
  min(gap_s) AS gap_s_min, max(gap_s) AS gap_s_max
FROM g""",
    ),
    (
        "Q-V7.examples",
        "V7：範例",
        """
SELECT order_id, order_created_at, order_status, amount, updated_at FROM orders_t
WHERE src = 'base' AND order_id IN ('ORD00000984', 'ORD00012637', 'ORD00013776') ORDER BY order_id, upd_ts""",
    ),
    (
        "Q-INC.samefile",
        "J3 與同狀態重送：增量同檔同 order_id 多列的分類",
        """
WITH g AS (
  SELECT src, order_id, count(*) AS c,
    count(DISTINCT member_id) AS d_mem, count(DISTINCT amount) AS d_amt, count(DISTINCT co_ts) AS d_co,
    count(DISTINCT order_status) AS d_status,
    count(DISTINCT concat_ws('|', product_id, channel, quantity, currency, coupon_discount, departure_date)) AS d_other,
    bool_or(order_id IN (SELECT order_id FROM base1)) AS id_in_base
  FROM orders_t WHERE src <> 'base' GROUP BY src, order_id HAVING count(*) > 1)
SELECT src,
  CASE WHEN d_mem > 1 OR d_amt > 1 OR d_co > 1 THEN 'collision(J3)'
       WHEN d_status = 1 AND d_other = 1 THEN 'resend_identical_except_updated_at'
       ELSE 'status_or_other_changed' END AS kind,
  count(*) AS n_groups, sum(c) AS n_rows, sum(CASE WHEN id_in_base THEN 1 ELSE 0 END) AS groups_id_in_base
FROM g GROUP BY ALL ORDER BY src, kind""",
    ),
    (
        "Q-J2.overlap",
        "J2：增量列與 base 同 order_id（base 先每 id 取一列）",
        """
SELECT i.src, count(*) AS rows_overlap, count(DISTINCT i.order_id) AS ids_overlap,
  sum(CASE WHEN i.member_id = b.member_id THEN 1 ELSE 0 END) AS same_member,
  sum(CASE WHEN i.amount_d = b.amount_d THEN 1 ELSE 0 END) AS same_amount,
  sum(CASE WHEN i.co_ts = b.co_ts THEN 1 ELSE 0 END) AS same_created,
  sum(CASE WHEN i.member_id = b.member_id AND i.amount_d = b.amount_d AND i.co_ts = b.co_ts THEN 1 ELSE 0 END) AS all_three_same,
  sum(CASE WHEN i.upd_ts > b.upd_ts THEN 1 ELSE 0 END) AS inc_newer_than_base,
  list_sort(list(DISTINCT i.order_status)) AS inc_statuses
FROM orders_t i JOIN base1 b USING (order_id) WHERE i.src <> 'base' GROUP BY i.src ORDER BY i.src""",
    ),
    (
        "Q-J2.example",
        "J2：範例",
        """
SELECT src, order_id, member_id, product_id, currency, amount, order_status, order_created_at FROM orders_t
WHERE order_id = 'ORD00005192' ORDER BY src""",
    ),
    (
        "Q-L4.cross_day",
        "L4：跨增量檔同 order_id（不在 base）的狀態與先後",
        """
WITH x AS (
  SELECT a.src AS src_a, b.src AS src_b, a.order_id, a.order_status AS status_a, b.order_status AS status_b,
    a.member_id = b.member_id AND a.amount_d = b.amount_d AND a.co_ts = b.co_ts AS same_order,
    CASE WHEN b.upd_ts > a.upd_ts THEN 'later_file_newer' ELSE 'later_file_older' END AS order_vs_file,
    a.order_id IN (SELECT order_id FROM base1) AS id_in_base
  FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src < b.src
  WHERE a.src <> 'base' AND b.src <> 'base')
SELECT src_a, src_b, id_in_base, same_order, status_a, status_b, order_vs_file, count(*) AS n
FROM x GROUP BY ALL ORDER BY ALL""",
    ),
    (
        "Q-L4.example",
        "L4：範例",
        """
SELECT src, order_id, order_status, updated_at FROM orders_t WHERE order_id = 'ORD00100020' ORDER BY src""",
    ),
    (
        "Q-L4.day2_upd_dates",
        "L4：day2 那 25 列較舊事件的 updated_at（台北日期）分布",
        """
SELECT b.upd_date, count(*) AS n
FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src = 'day1' AND b.src = 'day2'
WHERE a.order_id NOT IN (SELECT order_id FROM base1) AND b.upd_ts < a.upd_ts
GROUP BY ROLLUP (b.upd_date) ORDER BY 1 NULLS LAST""",
    ),
    # ---- 時間
    (
        "Q-V5.formats",
        "V5：下單時間格式",
        """
SELECT src, co_fmt, count(*) AS n, min(order_created_at) AS example_min, max(order_created_at) AS example_max
FROM orders_t GROUP BY src, co_fmt ORDER BY src, co_fmt""",
    ),
    (
        "Q-V5.tz_evidence_dup",
        "V5：V7 重複組中格式不同的兩列，解析後是否同一時刻",
        """
WITH p AS (
  SELECT a.order_id, a.co_fmt AS fmt_a, b.co_fmt AS fmt_b, a.order_created_at AS raw_a, b.order_created_at AS raw_b,
    date_diff('second', a.co_ts, b.co_ts) / 3600.0 AS diff_hours
  FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src = 'base' AND b.src = 'base'
   AND a.co_fmt = 'plus0800' AND b.co_fmt <> 'plus0800')
SELECT fmt_b, count(*) AS n_groups, min(diff_hours) AS min_diff_h, max(diff_hours) AS max_diff_h, min(raw_a) AS ex_a, min(raw_b) AS ex_b
FROM p GROUP BY fmt_b ORDER BY fmt_b""",
    ),
    (
        "Q-V5.tz_evidence_order",
        "V5：無標記格式若當 UTC，會有幾筆 updated_at 早於下單時間",
        """
SELECT co_fmt,
  sum(CASE WHEN upd_ts < co_ts THEN 1 ELSE 0 END) AS upd_before_created_as_taipei,
  sum(CASE WHEN co_fmt = 'slash_no_tz' AND upd_ts < co_ts + INTERVAL 8 HOUR THEN 1 ELSE 0 END) AS upd_before_created_if_utc
FROM orders_t WHERE src = 'base' GROUP BY co_fmt ORDER BY co_fmt""",
    ),
    (
        "Q-V5.z_before_0501",
        "V5：Z 格式字面日期早於 05-01、照 UTC 換算後早於 05-01",
        """
SELECT sum(CASE WHEN left(order_created_at, 10) < '2026-05-01' THEN 1 ELSE 0 END) AS raw_date_before_0501,
  sum(CASE WHEN co_date < DATE '2026-05-01' THEN 1 ELSE 0 END) AS taipei_date_before_0501
FROM orders_t WHERE src = 'base' AND co_fmt = 'iso_Z'""",
    ),
    (
        "Q-V5.z_date_shift",
        "V5：Z 格式若直接取字串前 10 碼當日期，和台北日期不同的列數",
        """
SELECT count(*) AS z_rows,
  sum(CASE WHEN left(order_created_at, 10) <> strftime(co_date, '%Y-%m-%d') THEN 1 ELSE 0 END) AS raw_date_differs_from_taipei_date
FROM orders_t WHERE src = 'base' AND co_fmt = 'iso_Z'""",
    ),
    (
        "Q-L1.upd_after_batch",
        "L1：增量 updated_at（台北日期）相對批次日",
        """
SELECT src, count(*) AS n,
  sum(CASE WHEN upd_date > batch_date THEN 1 ELSE 0 END) AS upd_after_batch,
  sum(CASE WHEN upd_date < batch_date THEN 1 ELSE 0 END) AS upd_before_batch,
  max(upd_date - batch_date) AS max_days_after
FROM orders_t WHERE src <> 'base' GROUP BY src ORDER BY src""",
    ),
    (
        "Q-L2.base_upd_after_period",
        "L2：base 的 updated_at 落在 07-01 以後",
        """
SELECT upd_date, count(*) AS n FROM orders_t WHERE src = 'base' AND upd_date >= DATE '2026-07-01'
GROUP BY ALL UNION ALL SELECT NULL, count(*) FROM orders_t WHERE src = 'base' AND upd_date >= DATE '2026-07-01' ORDER BY 1 NULLS LAST""",
    ),
    (
        "Q-L3.late_new_orders",
        "L3：增量中不在 base、也不在更早增量檔，但下單日早於批次日的新單",
        """
SELECT o.src, count(*) AS n_rows, min(o.order_id) AS id_min, max(o.order_id) AS id_max, min(o.co_date) AS co_min, max(o.co_date) AS co_max
FROM orders_t o
WHERE o.src <> 'base' AND o.co_date < o.batch_date
  AND o.order_id NOT IN (SELECT order_id FROM base1)
  AND NOT EXISTS (SELECT 1 FROM orders_t e WHERE e.order_id = o.order_id AND e.src <> 'base' AND e.src < o.src)
GROUP BY o.src ORDER BY o.src""",
    ),
    (
        "Q-L3.detail",
        "L3：60 張晚到新單的狀態、updated_at、是否在其他檔出現、出發日已過才付款",
        """
WITH l3 AS (
  SELECT * FROM orders_t o
  WHERE o.src = 'day2' AND o.co_date < o.batch_date AND o.order_id NOT IN (SELECT order_id FROM base1)
    AND NOT EXISTS (SELECT 1 FROM orders_t e WHERE e.order_id = o.order_id AND e.src <> 'base' AND e.src < o.src))
SELECT count(*) AS n_rows, count(DISTINCT order_id) AS n_ids, list_sort(list(DISTINCT order_status)) AS statuses,
  min(upd_date) AS upd_min, max(upd_date) AS upd_max,
  (SELECT count(*) FROM orders_t x WHERE x.order_id IN (SELECT order_id FROM l3) AND x.src <> 'day2') AS rows_in_other_files,
  sum(CASE WHEN dep_dt < upd_date THEN 1 ELSE 0 END) AS paid_after_departure
FROM l3""",
    ),
    (
        "Q-L3.paid_after_departure",
        "L3：出發日已過才付款的列",
        """
SELECT order_id, order_status, co_date, upd_date, dep_dt FROM orders_t o
WHERE o.src = 'day2' AND o.co_date < o.batch_date AND o.order_id NOT IN (SELECT order_id FROM base1)
  AND dep_dt < upd_date ORDER BY order_id""",
    ),
    (
        "Q-L10.completed_before_departure",
        "L10：completed 但出發日晚於 updated_at（台北日期）",
        """
SELECT src, sum(CASE WHEN order_status = 'completed' THEN 1 ELSE 0 END) AS completed_rows,
  sum(CASE WHEN order_status = 'completed' AND dep_dt > upd_date THEN 1 ELSE 0 END) AS completed_departure_not_reached,
  min(CASE WHEN order_status = 'completed' THEN dep_dt - upd_date END) AS min_days_to_departure,
  max(CASE WHEN order_status = 'completed' THEN dep_dt - upd_date END) AS max_days_to_departure
FROM orders_t GROUP BY src ORDER BY src""",
    ),
    (
        "Q-L10.incremental_split",
        "L10：增量檔的 completed 是否都是與 base 撞號的列",
        """
SELECT src, order_id IN (SELECT order_id FROM base1) AS id_in_base, count(*) AS completed_rows,
  sum(CASE WHEN dep_dt > upd_date THEN 1 ELSE 0 END) AS departure_not_reached
FROM orders_t WHERE src <> 'base' AND order_status = 'completed' GROUP BY ALL ORDER BY ALL""",
    ),
    (
        "Q-L10.after_dedupe",
        "L10：base 每 id 取 updated_at 最新一列後（＝進 fact 的列）",
        """
SELECT count(*) AS fact_candidate_rows,
  sum(CASE WHEN order_status = 'completed' AND dep_dt > upd_date THEN 1 ELSE 0 END) AS completed_departure_not_reached
FROM base1""",
    ),
    (
        "Q-L10.reverse",
        "L10 反向證據：base 每 id 一列，各狀態中出發日早於 07-01 的筆數與比例；出發日不晚於最後更新日的筆數",
        """
SELECT order_status, count(*) AS n,
  sum(CASE WHEN dep_dt < DATE '2026-07-01' THEN 1 ELSE 0 END) AS departure_before_0701,
  round(100.0 * sum(CASE WHEN dep_dt < DATE '2026-07-01' THEN 1 ELSE 0 END) / count(*), 1) AS pct,
  sum(CASE WHEN dep_dt <= upd_date THEN 1 ELSE 0 END) AS departure_on_or_before_last_update
FROM base1 GROUP BY order_status ORDER BY order_status""",
    ),
    (
        "Q-L10.vs_0701",
        "L10 基準：completed 是在出發前標上的（出發日晚於最後更新日），和以 07-01 為基準出發日已過，是兩件事",
        """
SELECT 'base_one_row_per_id' AS scope, count(*) AS completed_rows,
  count(*) FILTER (WHERE dep_dt > upd_date) AS marked_completed_before_departure,
  count(*) FILTER (WHERE dep_dt < DATE '2026-07-01') AS departure_before_0701,
  count(*) FILTER (WHERE dep_dt < DATE '2026-07-01' AND dep_dt > upd_date) AS before_0701_and_marked_before_departure
FROM base1 WHERE order_status = 'completed'
UNION ALL
SELECT 'fact_after_day3', count(*),
  count(*) FILTER (WHERE dep_dt > upd_date),
  count(*) FILTER (WHERE dep_dt < DATE '2026-07-01'),
  count(*) FILTER (WHERE dep_dt < DATE '2026-07-01' AND dep_dt > upd_date)
FROM fact_sim WHERE order_status = 'completed'""",
    ),
    (
        "Q-NEW.departure_before_order",
        "新檢查：出發日早於下單日、updated_at 早於下單時間",
        """
SELECT src, sum(CASE WHEN dep_dt < co_date THEN 1 ELSE 0 END) AS departure_before_order_date,
  sum(CASE WHEN upd_ts < co_ts THEN 1 ELSE 0 END) AS updated_before_created,
  min(dep_dt - co_date) AS min_days_order_to_departure
FROM orders_t GROUP BY src ORDER BY src""",
    ),
    # ---- 金額
    (
        "Q-AMT.ratio_buckets",
        "V1、V2、V6：金額比值分組（只列非 normal）",
        f"""
SELECT src, currency, {RATIO_BUCKET} AS bucket, count(*) AS n
FROM orders_ratio GROUP BY 1, 2, 3 HAVING bucket <> 'normal' ORDER BY src, bucket, currency""",
    ),
    (
        "Q-AMT.ratio_range",
        "比值規則：正常列的比值範圍（依來源×幣別）",
        f"""
SELECT src, currency, count(*) AS n, round(min(ratio), 4) AS min_r, round(max(ratio), 4) AS max_r
FROM orders_ratio WHERE {RATIO_BUCKET} = 'normal' GROUP BY ALL ORDER BY src, currency""",
    ),
    (
        "Q-V1.negative",
        "V1：負數金額",
        """
SELECT src, currency, count(*) AS n_negative,
  sum(CASE WHEN EXISTS (SELECT 1 FROM orders_t p WHERE p.order_id = o.order_id AND p.amount_d > 0) THEN 1 ELSE 0 END) AS same_id_has_positive_row,
  list_sort(list(DISTINCT order_status)) AS statuses
FROM orders_t o WHERE amount_d < 0 GROUP BY ALL ORDER BY src, currency""",
    ),
    (
        "Q-V1.examples",
        "V1：範例",
        """
SELECT order_id, order_status, currency, amount, quantity, bp, round(ratio, 4) AS ratio FROM orders_ratio
WHERE src = 'base' AND amount_d < 0 ORDER BY order_id LIMIT 3""",
    ),
    (
        "Q-V2.x1000_detail",
        "V2：疑似 ×1000 是否為 1000 的倍數",
        f"""
SELECT currency, count(*) AS n, sum(CASE WHEN amount_d % 1000 = 0 THEN 1 ELSE 0 END) AS multiple_of_1000,
  sum(CASE WHEN amount_d % 10 = 0 THEN 1 ELSE 0 END) AS multiple_of_10,
  round(min(ratio / 1000), 4) AS min_ratio_div1000, round(max(ratio / 1000), 4) AS max_ratio_div1000
FROM orders_ratio WHERE {RATIO_BUCKET} = 'about_x1000' GROUP BY currency ORDER BY currency""",
    ),
    (
        "Q-V2.examples",
        "V2：範例",
        f"""
SELECT order_id, currency, amount, quantity, bp, round(ratio, 1) AS ratio FROM orders_ratio
WHERE {RATIO_BUCKET} = 'about_x1000' ORDER BY ratio DESC LIMIT 3""",
    ),
    (
        "Q-V3.coupon",
        "V3：coupon_discount 值域",
        """
SELECT src, count(DISTINCT coupon_discount) AS n_distinct, min(coupon_d) AS min_v, max(coupon_d) AS max_v,
  sum(CASE WHEN coupon_d < 0 THEN 1 ELSE 0 END) AS n_negative,
  sum(CASE WHEN coupon_d = 0 THEN 1 ELSE 0 END) AS n_zero,
  sum(CASE WHEN coupon_d % 50 <> 0 THEN 1 ELSE 0 END) AS n_not_multiple_of_50,
  list_sort(list(DISTINCT coupon_discount) FILTER (WHERE coupon_d < 0)) AS negative_values
FROM orders_t GROUP BY src ORDER BY src""",
    ),
    (
        "Q-AMT.overlap",
        "V1、V2、V3、V6 互相重疊的列數（base）",
        f"""
WITH f AS (
  SELECT amount_d < 0 AS neg, {RATIO_BUCKET} = 'about_x1000' AS x1000, coupon_d < 0 AS coupon_neg,
    product_id NOT IN (SELECT product_id FROM products) AS unknown_product
  FROM orders_ratio WHERE src = 'base')
SELECT sum(CASE WHEN neg AND coupon_neg THEN 1 ELSE 0 END) AS neg_and_coupon,
  sum(CASE WHEN x1000 AND coupon_neg THEN 1 ELSE 0 END) AS x1000_and_coupon,
  sum(CASE WHEN unknown_product AND coupon_neg THEN 1 ELSE 0 END) AS unknown_product_and_coupon,
  sum(CASE WHEN neg AND unknown_product THEN 1 ELSE 0 END) AS neg_and_unknown_product
FROM f""",
    ),
    (
        "Q-V4.ntd",
        "V4：幣別分布與 NTD 比值（1:1 換算）對照 TWD",
        """
SELECT src, currency, count(*) AS n,
  round(quantile_cont(ratio, 0.01), 4) AS p01, round(quantile_cont(ratio, 0.5), 4) AS p50, round(quantile_cont(ratio, 0.99), 4) AS p99,
  sum(CASE WHEN amount_d % 1 <> 0 THEN 1 ELSE 0 END) AS with_fraction
FROM orders_ratio WHERE ratio > 0 AND ratio < 2 OR currency = 'NTD' GROUP BY ALL ORDER BY src, currency""",
    ),
    (
        "Q-L5.jpy_fraction",
        "L5：JPY 帶非零小數",
        """
SELECT src, count(*) AS jpy_rows, sum(CASE WHEN amount_d % 1 <> 0 THEN 1 ELSE 0 END) AS jpy_with_fraction
FROM orders_t WHERE currency = 'JPY' GROUP BY src ORDER BY src""",
    ),
    (
        "Q-V6.unknown_product",
        "V6：product_id 不在產品清單",
        """
SELECT src, count(*) AS n_rows, count(DISTINCT product_id) AS n_ids, min(product_id) AS id_min, max(product_id) AS id_max,
  list_sort(list(DISTINCT order_status)) AS statuses
FROM orders_t o WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id = o.product_id)
GROUP BY src ORDER BY src""",
    ),
    (
        "Q-L6.inactive",
        "L6：訂單的產品 is_active = 'N'",
        """
SELECT o.src, count(*) AS n_rows,
  count(*) FILTER (WHERE o.order_id NOT IN (SELECT order_id FROM base1)) AS rows_id_not_in_base,
  count(DISTINCT o.order_id) FILTER (WHERE o.order_id NOT IN (SELECT order_id FROM base1)) AS ids_not_in_base
FROM orders_t o JOIN products p USING (product_id) WHERE p.is_active = 'N'
GROUP BY o.src ORDER BY o.src""",
    ),
    (
        "Q-L7.dup_name",
        "L7：同名不同 product_id",
        """
SELECT count(*) AS n_products, count(DISTINCT product_name) AS n_names,
  (SELECT count(*) FROM (SELECT product_name FROM products GROUP BY 1 HAVING count(*) > 1)) AS names_with_multiple_ids,
  count(*) - count(DISTINCT product_id) AS dup_product_id,
  sum(CASE WHEN bp IS NULL OR bp <= 0 THEN 1 ELSE 0 END) AS bad_price,
  list_sort(list(DISTINCT is_active)) AS is_active_values
FROM products""",
    ),
    (
        "Q-FX.coverage",
        "L12 與找不到匯率：幣別不在匯率表、USD/JPY 下單日（台北）沒有匯率",
        """
SELECT o.src,
  sum(CASE WHEN o.currency NOT IN (SELECT DISTINCT currency FROM fx) THEN 1 ELSE 0 END) AS currency_not_in_fx,
  sum(CASE WHEN o.currency = 'TWD' THEN 1 ELSE 0 END) AS twd, sum(CASE WHEN o.currency = 'NTD' THEN 1 ELSE 0 END) AS ntd,
  sum(CASE WHEN o.currency IN (SELECT DISTINCT currency FROM fx) AND f.rate IS NULL THEN 1 ELSE 0 END) AS fx_missing_on_order_date
FROM orders_t o LEFT JOIN fx f ON f.rate_date = o.co_date AND f.currency = o.currency GROUP BY o.src ORDER BY o.src""",
    ),
    (
        "Q-FX.table",
        "匯率表本身：範圍、缺日、同日同幣別重複、非正值",
        """
SELECT min(rate_date) AS d_min, max(rate_date) AS d_max, count(*) AS n_rows,
  count(DISTINCT rate_date) AS n_dates, (max(rate_date) - min(rate_date) + 1) AS n_calendar_days,
  count(*) - count(DISTINCT (rate_date, currency)) AS dup_date_currency,
  sum(CASE WHEN rate IS NULL OR rate <= 0 THEN 1 ELSE 0 END) AS bad_rate,
  list_sort(list(DISTINCT currency)) AS currencies
FROM fx""",
    ),
    (
        "Q-ORD.member_ref",
        "新檢查：訂單的 member_id 不在會員快照、下單日早於註冊日",
        """
WITH m AS (SELECT member_id, min(TRY_CAST(register_date AS DATE)) AS reg FROM members GROUP BY member_id)
SELECT o.src, sum(CASE WHEN m.member_id IS NULL THEN 1 ELSE 0 END) AS member_not_found,
  sum(CASE WHEN o.co_date < m.reg THEN 1 ELSE 0 END) AS order_before_register
FROM orders_t o LEFT JOIN m USING (member_id) GROUP BY o.src ORDER BY o.src""",
    ),
    # ---- 會員
    (
        "Q-MEM.rows",
        "會員：各快照列數",
        """
SELECT extract_date, count(*) AS n_rows, count(DISTINCT member_id) AS n_members FROM members GROUP BY 1 ORDER BY 1""",
    ),
    (
        "Q-V8.same_day",
        "V8：同一會員同一 extract_date 多列",
        """
WITH g AS (
  SELECT member_id, extract_date, count(*) AS c, count(DISTINCT member_level) AS d_level,
    count(DISTINCT concat_ws('|', member_name, city, birth_date, register_date)) AS d_other
  FROM members GROUP BY 1, 2 HAVING count(*) > 1)
SELECT extract_date, count(*) AS n_groups, sum(c) - count(*) AS extra_rows,
  sum(CASE WHEN d_level > 1 THEN 1 ELSE 0 END) AS level_differs, sum(CASE WHEN d_other > 1 THEN 1 ELSE 0 END) AS other_differs
FROM g GROUP BY 1 ORDER BY 1""",
    ),
    (
        "Q-V9V10.placeholders",
        "V9、V10：city = 'N/A'、birth_date = 1900-01-01（各快照）",
        """
SELECT extract_date, count(*) AS n_rows,
  sum(CASE WHEN city = 'N/A' THEN 1 ELSE 0 END) AS city_na,
  sum(CASE WHEN birth_date = '1900-01-01' THEN 1 ELSE 0 END) AS birth_1900
FROM members GROUP BY ROLLUP (extract_date) ORDER BY extract_date NULLS LAST""",
    ),
    (
        "Q-V9.members",
        "V9：city N/A 涉及的會員數、其中在其他快照有真實縣市的人數",
        """
SELECT count(DISTINCT member_id) AS members_with_na,
  count(DISTINCT CASE WHEN member_id IN (SELECT member_id FROM members WHERE city <> 'N/A') THEN member_id END) AS also_has_real_city
FROM members WHERE city = 'N/A'""",
    ),
    (
        "Q-V9.na_before_real",
        "V9：city N/A 的會員分成從來沒有真實縣市、第一次出現 N/A 早於第一次出現真實縣市（dim_member 會先有一個城市為空值的版本）",
        """
WITH f AS (
  SELECT member_id, bool_or(city <> 'N/A') AS has_real,
    min(extract_date) FILTER (WHERE city = 'N/A') AS first_na,
    min(extract_date) FILTER (WHERE city <> 'N/A') AS first_real
  FROM members GROUP BY member_id HAVING bool_or(city = 'N/A'))
SELECT count(*) AS members_with_na,
  count(*) FILTER (WHERE NOT has_real) AS never_real_city,
  count(*) FILTER (WHERE has_real AND first_na < first_real) AS na_before_first_real,
  count(*) FILTER (WHERE NOT has_real) + count(*) FILTER (WHERE has_real AND first_na < first_real) AS expected_members_with_null_city_version
FROM f""",
    ),
    (
        "Q-V10.birth_min",
        "V10：1900 以外最早的生日、生日曾為 1900 的會員數",
        """
SELECT min(birth_date) FILTER (WHERE birth_date <> '1900-01-01') AS min_real_birth,
  count(DISTINCT member_id) FILTER (WHERE birth_date = '1900-01-01') AS members_with_1900,
  count(DISTINCT member_id) FILTER (WHERE birth_date = '1900-01-01'
    AND member_id NOT IN (SELECT member_id FROM members WHERE birth_date <> '1900-01-01')) AS members_never_real_birth,
  count(DISTINCT member_id) FILTER (WHERE city = 'N/A'
    AND member_id NOT IN (SELECT member_id FROM members WHERE city <> 'N/A')) AS members_never_real_city
FROM members""",
    ),
    (
        "Q-J9.birth_direction",
        "J9：生日在快照間變動的方向（同一快照日兩列時依等級高低排序，結果不受影響）",
        f"""
WITH s AS (SELECT member_id, extract_date, birth_date,
    lag(birth_date) OVER (PARTITION BY member_id ORDER BY extract_date, {LEVEL_RANK}) AS prev_birth
  FROM members)
SELECT CASE WHEN prev_birth = '1900-01-01' THEN '1900 -> real' WHEN birth_date = '1900-01-01' THEN 'real -> 1900'
            ELSE 'real -> other real' END AS direction,
  count(DISTINCT member_id) AS n_members, list_sort(list(DISTINCT member_id))[1:3] AS examples
FROM s WHERE prev_birth IS NOT NULL AND prev_birth <> birth_date GROUP BY 1 ORDER BY 1""",
    ),
    (
        "Q-L8.under18",
        "L8：註冊時未滿 18 歲（排除 1900-01-01）",
        """
SELECT count(*) AS n_rows, count(DISTINCT member_id) AS n_members,
  round(min(date_diff('day', TRY_CAST(birth_date AS DATE), TRY_CAST(register_date AS DATE)) / 365.25), 1) AS min_age_at_register
FROM members WHERE birth_date <> '1900-01-01'
  AND TRY_CAST(birth_date AS DATE) + INTERVAL 18 YEAR > TRY_CAST(register_date AS DATE)""",
    ),
    (
        "Q-L9.changes",
        "L9：等級、縣市在快照間變過的會員數",
        """
SELECT (SELECT count(*) FROM (SELECT member_id FROM members GROUP BY 1 HAVING count(DISTINCT member_level) > 1)) AS level_changed_members,
  (SELECT count(*) FROM (SELECT member_id FROM members GROUP BY 1 HAVING count(DISTINCT city) > 1)) AS city_changed_members_incl_na,
  (SELECT count(*) FROM (SELECT member_id FROM members WHERE city <> 'N/A' GROUP BY 1 HAVING count(DISTINCT city) > 1)) AS city_changed_members_excl_na,
  (SELECT count(*) FROM (SELECT member_id FROM members GROUP BY 1 HAVING count(DISTINCT member_name) > 1)) AS name_changed,
  (SELECT count(*) FROM (SELECT member_id FROM members GROUP BY 1 HAVING count(DISTINCT register_date) > 1)) AS register_changed""",
    ),
    (
        "Q-L11.identical",
        "L11：後續快照與該會員前一次快照屬性完全相同的列（同日兩列先照 V8 取較高等級）",
        f"""
WITH m1 AS (SELECT *, {LEVEL_RANK} AS rk FROM members
  QUALIFY row_number() OVER (PARTITION BY member_id, extract_date ORDER BY {LEVEL_RANK} DESC) = 1),
s AS (SELECT *, lag(concat_ws('|', member_name, member_level, city, birth_date, register_date))
    OVER (PARTITION BY member_id ORDER BY extract_date) AS prev_attrs
  FROM m1)
SELECT extract_date, count(*) AS identical_to_previous
FROM s WHERE prev_attrs = concat_ws('|', member_name, member_level, city, birth_date, register_date)
GROUP BY ROLLUP (extract_date) ORDER BY 1 NULLS LAST""",
    ),
    (
        "Q-MEM.level_moves",
        "L9、V8：會員等級在相鄰快照間的變動方向（同日兩列分別取較高、較低等級）",
        f"""
WITH m AS (SELECT *, {LEVEL_RANK} AS rk FROM members),
hi AS (SELECT 'v8_take_higher' AS rule, * FROM m
  QUALIFY row_number() OVER (PARTITION BY member_id, extract_date ORDER BY rk DESC) = 1),
lo AS (SELECT 'v8_take_lower' AS rule, * FROM m
  QUALIFY row_number() OVER (PARTITION BY member_id, extract_date ORDER BY rk ASC) = 1),
s AS (SELECT *, lag(rk) OVER (PARTITION BY rule, member_id ORDER BY extract_date) AS prev_rk
  FROM (SELECT * FROM hi UNION ALL SELECT * FROM lo))
SELECT rule, count(*) FILTER (WHERE rk - prev_rk = 1) AS up_one_level,
  count(*) FILTER (WHERE rk - prev_rk > 1) AS up_more_levels,
  count(*) FILTER (WHERE rk < prev_rk) AS down
FROM s WHERE prev_rk IS NOT NULL GROUP BY rule ORDER BY rule""",
    ),
    (
        "Q-V8.later_snapshot",
        "V8：同日矛盾的 30 位中，之後的快照又出現的會員，後來的等級等於較高還是較低者",
        f"""
WITH v8 AS (SELECT member_id, max({LEVEL_RANK}) AS hi, min({LEVEL_RANK}) AS lo
  FROM members GROUP BY member_id, extract_date HAVING count(*) > 1)
SELECT v8.member_id, v8.hi, v8.lo, m.extract_date, {LEVEL_RANK.replace("member_level", "m.member_level")} AS later_rk
FROM v8 JOIN members m ON m.member_id = v8.member_id AND m.extract_date > '2026-04-30' ORDER BY 1""",
    ),
    (
        "Q-MEM.register_after_extract",
        "新檢查：register_date 晚於 extract_date、等級值域",
        """
SELECT sum(CASE WHEN TRY_CAST(register_date AS DATE) > TRY_CAST(extract_date AS DATE) THEN 1 ELSE 0 END) AS register_after_extract,
  list_sort(list(DISTINCT member_level)) AS levels, list_sort(list(DISTINCT extract_date)) AS extract_dates
FROM members""",
    ),
    # ---- 補充（2026-10-18）：coupon 幣別、合約層值域
    (
        "Q-N3.coupon_by_currency",
        "N3：base 各幣別的 coupon 面額分布（與 notes coupon-currency.md 同一查詢）",
        """
SELECT currency, count(*) AS n, count(DISTINCT coupon_discount) AS n_vals,
  min(TRY_CAST(coupon_discount AS DOUBLE)) AS mn, max(TRY_CAST(coupon_discount AS DOUBLE)) AS mx,
  round(avg(TRY_CAST(coupon_discount AS DOUBLE)) FILTER (WHERE TRY_CAST(coupon_discount AS DOUBLE) > 0), 1) AS avg_pos,
  round(median(TRY_CAST(amount AS DOUBLE)), 1) AS med_amt,
  sum(CASE WHEN TRY_CAST(coupon_discount AS DOUBLE) > TRY_CAST(amount AS DOUBLE) THEN 1 ELSE 0 END) AS coupon_gt_amt
FROM orders_t WHERE src = 'base' GROUP BY currency ORDER BY currency""",
    ),
    (
        "Q-DOM.status_currency",
        "值域：四個訂單檔 order_status、currency 各值的筆數（原始字串，區分大小寫與空白）",
        """
SELECT src, 'order_status' AS col, order_status AS raw_value, count(*) AS n,
  order_status IN ('created', 'paid', 'cancelled', 'completed') AS in_contract
FROM orders_all GROUP BY ALL
UNION ALL
SELECT src, 'currency', currency, count(*), currency IN ('TWD', 'NTD', 'USD', 'JPY')
FROM orders_all GROUP BY ALL
ORDER BY src, col, raw_value""",
    ),
    # 狀態機的防護規則在原始資料上的預檢（不經管線）。「同一張單」＝order_id、會員、金額、下單時刻都相同，
    # 撞號（J2、J3）因此不會被當成同一張單的狀態變化。可達性與 pipeline/order_status.py 的 REACHABLE 相同：
    # X→X、created→任何狀態、paid→cancelled／completed。
    (
        "Q-SM.chain",
        "防護性設計：同一張單依 updated_at 排序後的相鄰狀態（走不到、跳過中間狀態）",
        """
WITH t AS (SELECT DISTINCT order_id, member_id, amount_d, co_ts, upd_ts, order_status FROM orders_t),
s AS (SELECT *, lag(order_status) OVER (PARTITION BY order_id, member_id, amount_d, co_ts ORDER BY upd_ts) AS prev_status FROM t)
SELECT count(*) FILTER (WHERE prev_status IS NOT NULL) AS adjacent_pairs,
  count(*) FILTER (WHERE prev_status IS NOT NULL AND prev_status <> order_status) AS status_changed,
  count(*) FILTER (WHERE prev_status IS NOT NULL AND NOT (prev_status = order_status OR prev_status = 'created'
    OR (prev_status = 'paid' AND order_status IN ('cancelled', 'completed')))) AS not_reachable,
  count(*) FILTER (WHERE prev_status = 'created' AND order_status = 'completed') AS skipped_intermediate
FROM s""",
    ),
    (
        "Q-SM.same_second",
        "防護性設計：同一張單、同一個 updated_at 出現不同狀態",
        """
SELECT count(*) AS n_groups FROM (
  SELECT order_id, member_id, amount_d, co_ts, upd_ts FROM orders_t
  GROUP BY ALL HAVING count(DISTINCT order_status) > 1)""",
    ),
    (
        "Q-MEM.both_0531_0630",
        "防護性設計：同時出現在 05-31 與 06-30 快照的會員（遲到快照會遺失歷史的對象）",
        """
SELECT count(*) AS n_members FROM (
  SELECT member_id FROM members WHERE extract_date IN ('2026-05-31', '2026-06-30')
  GROUP BY member_id HAVING count(DISTINCT extract_date) = 2)""",
    ),
    # ---- 寫進 fact 之後（DuckDB 照管線規則重算，view fact_sim；不啟動 Spark）
    (
        "Q-POST.totals",
        "重算的 fact 和管線實跑對帳比對：各批寫入筆數、amount_twd、net、coupon 轉 NULL、V2 清單",
        """
SELECT wbatch, count(*) AS fact_rows, sum(amount_twd) AS amount_twd_sum,
  sum(amount_twd - coupon_clean) AS net_amount_twd_sum,
  sum(CASE WHEN coupon_d = -1 THEN 1 ELSE 0 END) AS coupon_nulled_rows,
  sum(CASE WHEN round(amount_twd / (bp * qty_i), 2) > 100 THEN 1 ELSE 0 END) AS amount_review_rows,
  sum(CASE WHEN bp IS NULL THEN 1 ELSE 0 END) AS unknown_product_rows
FROM fact_sim GROUP BY ROLLUP (wbatch) ORDER BY wbatch NULLS LAST""",
    ),
    (
        "Q-POST.v2_share",
        "V2：清單 40 列佔 base 寫入 fact 的 amount_twd 比例（以及佔三天後全表的比例）",
        """
SELECT count(*) FILTER (WHERE round(amount_twd / (bp * qty_i), 2) > 100) AS v2_rows,
  sum(amount_twd) FILTER (WHERE round(amount_twd / (bp * qty_i), 2) > 100) AS v2_amount_twd,
  sum(amount_twd) FILTER (WHERE wbatch = 'base') AS base_amount_twd,
  round(100 * sum(amount_twd) FILTER (WHERE round(amount_twd / (bp * qty_i), 2) > 100)
        / sum(amount_twd) FILTER (WHERE wbatch = 'base'), 2) AS pct_of_base,
  round(100 * sum(amount_twd) FILTER (WHERE round(amount_twd / (bp * qty_i), 2) > 100) / sum(amount_twd), 2) AS pct_of_fact_after_day3
FROM fact_sim""",
    ),
    (
        "Q-POST.v1_overlap",
        "V1：被合約擋下的 50 列裡，同時是 V3（coupon -1）、V7 重複、completed 且出發日未到的列數",
        """
SELECT count(*) AS v1_rows,
  sum(CASE WHEN coupon_d = -1 THEN 1 ELSE 0 END) AS also_coupon_minus1,
  sum(CASE WHEN order_id IN (SELECT order_id FROM orders_t WHERE src = 'base' GROUP BY 1 HAVING count(*) > 1) THEN 1 ELSE 0 END) AS also_v7_group,
  sum(CASE WHEN order_status = 'completed' AND dep_dt > upd_date THEN 1 ELSE 0 END) AS also_l10,
  sum(amount_d * CASE WHEN currency IN ('TWD','NTD') THEN 1 ELSE fx_rate END) AS amount_twd_unrounded
FROM orders_ratio WHERE src = 'base' AND amount_d <= 0""",
    ),
    (
        "Q-POST.l10",
        "L10：寫進 fact 的 completed 中，出發日晚於最後更新日的列數與金額",
        """
SELECT count(*) FILTER (WHERE order_status = 'completed') AS completed_rows,
  count(*) FILTER (WHERE order_status = 'completed' AND dep_dt > upd_date) AS completed_departure_not_reached,
  sum(amount_twd) FILTER (WHERE order_status = 'completed' AND dep_dt > upd_date) AS amount_twd
FROM fact_sim""",
    ),
    (
        "Q-POST.currency",
        "V4、L12：base 寫進 fact 的幣別分布",
        """
SELECT currency, count(*) AS n, sum(CASE WHEN fx_rate = 1 THEN 1 ELSE 0 END) AS fx_rate_1, sum(amount_twd) AS amount_twd_sum
FROM fact_sim WHERE wbatch = 'base' GROUP BY ROLLUP (currency) ORDER BY currency NULLS LAST""",
    ),
    (
        "Q-POST.l6",
        "L6：寫進 fact 的列中，產品已下架的筆數",
        """
SELECT wbatch, count(*) AS n FROM fact_sim WHERE is_active = 'N' GROUP BY ROLLUP (wbatch) ORDER BY wbatch NULLS LAST""",
    ),
    (
        "Q-POST.net_guard",
        "net 變負數的防護：-1 以外的負 coupon（原始檔）、coupon 大於 amount_twd、net < 0（fact）",
        """
SELECT (SELECT count(*) FROM orders_t WHERE coupon_d < 0 AND coupon_d <> -1) AS negative_coupon_not_minus1,
  count(*) FILTER (WHERE coupon_clean > amount_twd) AS coupon_gt_amount_twd,
  count(*) FILTER (WHERE amount_twd - coupon_clean < 0) AS net_negative,
  min(amount_twd) AS min_amount_twd, max(coupon_clean) AS max_coupon
FROM fact_sim""",
    ),
    (
        "Q-POST.l4_final",
        "L4：25 張單在三天後的 fact 狀態（取 updated_at 最新一列）",
        """
SELECT order_status, wbatch AS written_by_batch, count(*) AS n FROM fact_sim
WHERE order_id IN (SELECT a.order_id FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id
                   AND a.src = 'day1' AND b.src = 'day2' WHERE a.order_id NOT IN (SELECT order_id FROM base1))
GROUP BY ALL ORDER BY ALL""",
    ),
    # ---- 報告正文的真實例子與影響（2026-10-19 改寫文字時新增）
    (
        "Q-L10.example",
        "L10：範例（base 寫進 fact 的 completed，出發日晚於最後更新日）",
        """
SELECT order_id, order_status, currency, amount, updated_at, departure_date, dep_dt - upd_date AS days_to_departure
FROM base1 WHERE order_status = 'completed' AND dep_dt > upd_date AND amount_d > 0 ORDER BY order_id LIMIT 3""",
    ),
    (
        "Q-J2.impact",
        "J2：如果照官方 README 把撞號列當成狀態更新（updated_at 較新才覆寫），fact 會怎麼變",
        """
WITH j AS (SELECT * FROM orders_t WHERE src <> 'base' AND order_id IN (SELECT order_id FROM base1)
           QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY upd_ts DESC) = 1),
hit AS (SELECT f.order_id, f.member_id AS fact_member, j.member_id AS inc_member,
          f.order_status AS fact_status, j.order_status AS inc_status
        FROM fact_sim f JOIN j USING (order_id) WHERE j.upd_ts > f.upd_ts)
SELECT count(*) AS orders_overwritten,
  sum(CASE WHEN fact_member <> inc_member THEN 1 ELSE 0 END) AS member_changed,
  sum(CASE WHEN fact_status <> inc_status THEN 1 ELSE 0 END) AS status_changed,
  sum(CASE WHEN fact_status <> 'cancelled' AND inc_status = 'cancelled' THEN 1 ELSE 0 END) AS become_cancelled,
  sum(CASE WHEN fact_status = 'cancelled' AND inc_status <> 'cancelled' THEN 1 ELSE 0 END) AS cancelled_reverted,
  (SELECT count(*) FROM fact_sim) AS fact_rows,
  (SELECT count(*) FROM fact_sim WHERE order_status = 'cancelled') AS fact_cancelled,
  round(100.0 * (SELECT count(*) FROM fact_sim WHERE order_status = 'cancelled') / (SELECT count(*) FROM fact_sim), 2) AS cancel_rate_pct,
  round(100.0 * ((SELECT count(*) FROM fact_sim WHERE order_status = 'cancelled')
                 + sum(CASE WHEN fact_status <> 'cancelled' AND inc_status = 'cancelled' THEN 1 ELSE 0 END)
                 - sum(CASE WHEN fact_status = 'cancelled' AND inc_status <> 'cancelled' THEN 1 ELSE 0 END))
        / (SELECT count(*) FROM fact_sim), 2) AS cancel_rate_pct_if_overwritten
FROM hit""",
    ),
    (
        "Q-J3.example",
        "J3：範例（增量同一檔內，同一個 order_id 兩列的會員、金額、下單時間都不同）",
        """
SELECT src, order_id, member_id, amount, order_created_at, order_status FROM orders_t
WHERE src <> 'base' AND (src, order_id) IN (
  SELECT src, order_id FROM orders_t WHERE src <> 'base' GROUP BY ALL HAVING count(DISTINCT member_id) > 1)
ORDER BY src, order_id LIMIT 2""",
    ),
    (
        "Q-L4.impact",
        "L4：25 張單在 fact 的金額；若照到達順序處理，這 25 張會從 cancelled 回到 paid",
        """
SELECT count(*) AS orders, sum(amount_twd) AS amount_twd_sum,
  list_sort(list(DISTINCT order_status)) AS fact_status_now
FROM fact_sim
WHERE order_id IN (SELECT a.order_id FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id
                   AND a.src = 'day1' AND b.src = 'day2' WHERE a.order_id NOT IN (SELECT order_id FROM base1))""",
    ),
    (
        "Q-L3.example",
        "L3：範例與金額（day2 送來、下單日在 6 月、不在 base 也不在 day1 的新單）",
        """
SELECT order_id, order_created_at, order_status, updated_at, currency, amount,
  count(*) OVER () AS n_orders, sum(amount_twd) OVER () AS amount_twd_sum
FROM fact_sim WHERE wbatch = 'day2' AND co_date < DATE '2026-07-01'
ORDER BY order_id LIMIT 2""",
    ),
    (
        "Q-V5.example",
        "V5：範例（Z 格式的下單時間，字串前 10 碼的日期和台北日期不同）",
        """
SELECT order_id, order_created_at, substr(order_created_at, 1, 10) AS literal_date, co_date AS taipei_date
FROM orders_t WHERE src = 'base' AND co_fmt = 'iso_Z' AND co_date <> CAST(substr(order_created_at, 1, 10) AS DATE)
ORDER BY order_id LIMIT 2""",
    ),
    (
        "Q-V8.example",
        "V8：範例（同一會員、同一個 extract_date 兩列，等級不同）",
        """
SELECT member_id, extract_date, member_level, city FROM members
WHERE (member_id, extract_date) IN (SELECT member_id, extract_date FROM members GROUP BY ALL HAVING count(*) > 1)
ORDER BY member_id, member_level LIMIT 2""",
    ),
    (
        "Q-L7.example",
        "L7：範例（同一個產品名稱對應兩個 product_id）",
        """
SELECT product_id, product_name, base_price_twd FROM products
WHERE product_name = (SELECT product_name FROM products WHERE product_id = 'P00098') ORDER BY product_id""",
    ),
    (
        "Q-J9.example",
        "J9：範例（真實生日在後來的快照變成 1900-01-01）",
        """
SELECT member_id, extract_date, birth_date FROM members WHERE member_id = 'M001647' ORDER BY extract_date""",
    ),
    # ---- 主管會追問、資料算得出來的部分（2026-10-26 新增）
    (
        "Q-J2.blocked_amount",
        "J2：與 base 撞號而擋下的增量列，若其實是另一張真訂單，金額有多少（同編號＋會員＋下單時間＋金額算一張，重送取最新一列）",
        """
WITH j AS (
  SELECT o.*, round(o.amount_d * CASE WHEN o.currency IN ('TWD','NTD') THEN 1 ELSE f.rate END, 2) AS amount_twd,
    o.amount_d * CASE WHEN o.currency IN ('TWD','NTD') THEN 1 ELSE f.rate END / (p.bp * o.qty_i) AS ratio
  FROM orders_t o
  LEFT JOIN fx f ON f.rate_date = o.co_date AND f.currency = o.currency
  LEFT JOIN products p ON p.product_id = o.product_id
  WHERE o.src <> 'base' AND o.order_id IN (SELECT order_id FROM base1)),
k AS (SELECT * FROM j QUALIFY row_number() OVER (PARTITION BY order_id, member_id, co_ts, amount_d ORDER BY upd_ts DESC) = 1)
SELECT (SELECT count(*) FROM j) AS blocked_rows, count(*) AS orders_if_real,
  sum(amount_twd) AS amount_twd_sum,
  sum(amount_twd) FILTER (WHERE order_status <> 'cancelled') AS amount_twd_not_cancelled,
  count(*) FILTER (WHERE ratio > 100) AS ratio_over_100,
  (SELECT sum(amount_twd) FROM fact_sim) AS fact_amount_twd_sum,
  round(100 * sum(amount_twd) / (SELECT sum(amount_twd) FROM fact_sim), 2) AS pct_of_fact
FROM k""",
    ),
    (
        "Q-V2.div1000_estimate",
        "V2：base 寫進 fact 的金額，若人工確認清單上的 40 張真的是多乘 1,000、除以 1,000 後各月約多少（估計，不是確認結果）",
        """
WITH f AS (SELECT *, coalesce(round(amount_twd / (bp * qty_i), 2) > 100, false) AS in_review
           FROM fact_sim WHERE wbatch = 'base')
SELECT strftime(co_date, '%Y-%m') AS order_month,
  count(*) FILTER (WHERE in_review) AS review_orders,
  sum(amount_twd) AS amount_twd_as_is,
  sum(amount_twd) FILTER (WHERE NOT in_review) AS amount_twd_excluding_review,
  sum(CASE WHEN in_review THEN CAST(round(amount_twd / 1000, 2) AS DECIMAL(38,2)) ELSE amount_twd END) AS amount_twd_if_div1000
FROM f GROUP BY ROLLUP (order_month) ORDER BY order_month NULLS LAST""",
    ),
    (
        "Q-L3.june_change",
        "L3：下單日在 6 月的訂單，每批處理完後的筆數與金額（折扣前、含所有狀態），看 07-02 之後變了多少",
        """
WITH j AS (SELECT *, coalesce(round(amount_twd / (bp * qty_i), 2) > 100, false) AS in_review,
             CASE wbatch WHEN 'base' THEN 0 WHEN 'day1' THEN 1 WHEN 'day2' THEN 2 ELSE 3 END AS k
           FROM fact_sim WHERE co_date BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'),
b AS (SELECT * FROM (VALUES ('base', 0), ('day1', 1), ('day2', 2), ('day3', 3)) t(after_batch, k))
SELECT b.after_batch, count(j.order_id) AS june_orders, sum(j.amount_twd) AS june_amount_twd,
  sum(j.amount_twd) FILTER (WHERE NOT j.in_review) AS june_amount_twd_excluding_review
FROM b LEFT JOIN j ON j.k <= b.k GROUP BY b.after_batch, b.k ORDER BY b.k""",
    ),
]


def print_result(
    con: duckdb.DuckDBPyConnection, label: str, issue: str, sql: str
) -> None:
    print(f"\n===== [{label}] {issue}")
    print("SQL:" + sql)
    rel = con.sql(sql)
    cols = rel.columns
    rows = rel.fetchall()
    print("OUTPUT:")
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join("NULL" if v is None else str(v) for v in r))


def run_detection() -> None:
    con = duckdb.connect()
    con.sql("SET TimeZone = 'Asia/Taipei'")
    for name, sql in VIEWS.items():
        con.sql(f"CREATE OR REPLACE VIEW {name} AS {sql}")
    print("# 偵測（DuckDB，直接查 CSV）")
    for label, issue, sql in QUERIES:
        print_result(con, label, issue, sql)


# ---------------------------------------------------------------- 管線驗證


def run_pipeline() -> None:
    sys.path.insert(0, str(PART_A))
    from pipeline.delta_io import table_check_constraints
    from pipeline.fact_order import (
        AMOUNT_EXCLUDING_REVIEW_SQL,
        WarehousePaths,
        load_base,
        load_incremental,
    )
    from pipeline.session import build_spark
    from pipeline.sources import CsvSource
    from pyspark.sql import functions as F

    print("\n\n# 處理後的驗證（Part A 管線，PySpark＋Delta）")
    if WAREHOUSE.exists():
        shutil.rmtree(WAREHOUSE)
    spark = build_spark()
    spark.sparkContext.setLogLevel("ERROR")
    source = CsvSource(spark)
    paths = WarehousePaths(WAREHOUSE)

    rec = load_base(spark, source, paths)
    print("\n===== [P-BASE.reconciliation] load_base 的對帳")
    for k in (
        "input_rows",
        "fact_rows",
        "quarantined_rows",
        "quarantined_by_category",
        "skipped_rows",
        "coupon_nulled_rows",
        "amount_review_rows",
        "amount_twd_sum",
        "net_amount_twd_sum",
        "unknown_product_rows",
        "unknown_member_rows",
        "member_rejected_rows",
    ):
        print(f"{k} = {getattr(rec, k)}")
    print(f"balanced = {rec.balanced}")

    fact = spark.read.format("delta").load(str(paths.fact_order))
    products = (
        spark.read.option("header", True)
        .csv(str(DATA / "products.csv"))
        .select("product_id", F.col("base_price_twd").cast("decimal(18,2)").alias("bp"))
    )
    f = fact.join(products, "product_id", "left").withColumn(
        "ratio", F.col("amount_twd") / (F.col("bp") * F.col("quantity"))
    )
    fact.createOrReplaceTempView("fact_order")
    f.createOrReplaceTempView("fact_ratio")
    spark.read.format("delta").load(str(paths.quarantine)).createOrReplaceTempView(
        "quarantine_order"
    )
    spark.read.format("delta").load(str(paths.dim_member)).createOrReplaceTempView(
        "dim_member"
    )
    spark.read.format("delta").load(
        str(paths.member_quarantine)
    ).createOrReplaceTempView("quarantine_member")
    spark.read.option("header", True).csv(
        str(DATA / "members.csv")
    ).createOrReplaceTempView("members_raw")

    checks = [
        (
            "P-BASE.fact_issue_rows",
            "base 寫入 fact 後，各問題在 fact 裡剩幾列",
            """
SELECT count(*) AS fact_rows,
  sum(CASE WHEN amount < 0 THEN 1 ELSE 0 END) AS v1_negative,
  sum(CASE WHEN ratio > 1.3 AND ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 1 ELSE 0 END) AS v2_about_x1000,
  sum(CASE WHEN coupon_discount < 0 THEN 1 ELSE 0 END) AS v3_coupon_negative_left,
  sum(CASE WHEN coupon_discount IS NULL THEN 1 ELSE 0 END) AS v3_coupon_null,
  sum(CASE WHEN currency = 'NTD' THEN 1 ELSE 0 END) AS v4_ntd_rows,
  sum(CASE WHEN currency = 'NTD' AND fx_rate = 1 THEN 1 ELSE 0 END) AS v4_ntd_fx_1,
  sum(CASE WHEN product_sk = -1 THEN 1 ELSE 0 END) AS v6_product_sk_minus1,
  sum(CASE WHEN member_sk IS NULL THEN 1 ELSE 0 END) AS member_sk_null,
  sum(CASE WHEN order_status = 'completed' AND departure_date_sk > CAST(date_format(updated_at, 'yyyyMMdd') AS INT) THEN 1 ELSE 0 END) AS l10_completed_departure_not_reached,
  sum(CASE WHEN currency IN ('TWD','NTD') THEN 1 ELSE 0 END) AS twd_ntd_rows_kept,
  count(DISTINCT order_id) AS distinct_order_id
FROM fact_ratio""",
        ),
        (
            "P-BASE.amount_impact",
            "V1、V2 在 fact 的列數、amount_twd 總和與佔全表 amount_twd 的比例（V1 已由合約擋下，應為 0 列）",
            """
SELECT
  CASE WHEN amount < 0 THEN 'v1_negative'
       WHEN ratio > 1.3 AND ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'v2_about_x1000'
       ELSE 'other' END AS grp,
  count(*) AS n, sum(amount_twd) AS amount_twd_sum,
  round(100 * sum(amount_twd) / (SELECT sum(amount_twd) FROM fact_order), 2) AS pct_of_total
FROM fact_ratio GROUP BY 1 ORDER BY 1""",
        ),
        (
            "P-BASE.l10_impact",
            "L10：completed 且出發日未到的列佔 completed 的比例與金額",
            """
SELECT sum(CASE WHEN order_status = 'completed' THEN 1 ELSE 0 END) AS completed_rows,
  sum(CASE WHEN order_status = 'completed' AND departure_date_sk > CAST(date_format(updated_at, 'yyyyMMdd') AS INT) THEN 1 ELSE 0 END) AS not_reached,
  sum(CASE WHEN order_status = 'completed' AND departure_date_sk > CAST(date_format(updated_at, 'yyyyMMdd') AS INT) THEN amount_twd END) AS not_reached_amount_twd
FROM fact_order""",
        ),
        (
            "P-BASE.fact_currency",
            "fact 的幣別分布",
            """
SELECT currency, count(*) AS n, sum(amount_twd) AS amount_twd_sum FROM fact_order GROUP BY currency ORDER BY currency""",
        ),
        (
            "P-BASE.v5_dates",
            "V5：fact 的台北下單日範圍（Z 與無標記格式換算後）",
            """
SELECT min(order_date_sk) AS min_order_date_sk, max(order_date_sk) AS max_order_date_sk,
  sum(CASE WHEN order_date_sk < 20260501 THEN 1 ELSE 0 END) AS before_0501 FROM fact_order""",
        ),
        (
            "P-BASE.v7_quarantine",
            "V7：隔離表中 base 的 duplicate 列，與 fact 保留列的 updated_at 比較",
            """
SELECT q.reject_category, count(*) AS n,
  sum(CASE WHEN f.updated_at > to_timestamp(q.updated_at) THEN 1 ELSE 0 END) AS kept_row_is_newer
FROM quarantine_order q LEFT JOIN fact_order f USING (order_id) WHERE q.batch_id = 'base' GROUP BY q.reject_category""",
        ),
        (
            "P-MEM.v8_same_day",
            "V8：同日矛盾的 30 位，dim_member 第一版的等級是否為較高者",
            """
WITH r AS (SELECT member_id, extract_date, member_level,
    CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END AS rk
  FROM members_raw),
c AS (SELECT member_id, max(rk) AS max_rk FROM r GROUP BY member_id, extract_date HAVING count(*) > 1),
first AS (SELECT * FROM dim_member
  QUALIFY row_number() OVER (PARTITION BY member_id ORDER BY valid_from) = 1)
SELECT count(*) AS conflict_members,
  sum(CASE WHEN CASE f.member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END = c.max_rk THEN 1 ELSE 0 END) AS first_version_is_higher_level
FROM c JOIN first f USING (member_id)""",
        ),
        (
            "P-MEM.v9_v10_placeholders",
            "V9、V10、J9：dim_member 中的哨兵值與被覆寫的真實生日",
            """
SELECT count(*) AS dim_rows,
  count(DISTINCT member_id) AS members,
  sum(CASE WHEN city = 'N/A' THEN 1 ELSE 0 END) AS city_na_left,
  sum(CASE WHEN city IS NULL THEN 1 ELSE 0 END) AS city_null_rows,
  count(DISTINCT CASE WHEN city IS NULL THEN member_id END) AS city_null_members,
  sum(CASE WHEN birth_date = DATE '1900-01-01' THEN 1 ELSE 0 END) AS birth_1900_left,
  count(DISTINCT CASE WHEN birth_date IS NULL THEN member_id END) AS birth_null_members,
  count(DISTINCT CASE WHEN member_id IN ('M001647', 'M001931', 'M003842') AND birth_date IS NOT NULL THEN member_id END) AS j9_examples_keep_real_birth
FROM dim_member""",
        ),
        (
            "P-MEM.j9_all",
            "J9：真實生日 → 1900 的 5 位，dim_member 的生日",
            """
WITH s AS (SELECT member_id, birth_date,
    lag(birth_date) OVER (PARTITION BY member_id ORDER BY extract_date, member_level) AS prev_birth FROM members_raw),
j9 AS (SELECT DISTINCT member_id, prev_birth FROM s WHERE birth_date = '1900-01-01' AND prev_birth <> '1900-01-01')
SELECT j9.member_id, j9.prev_birth AS real_birth_in_source, max(d.birth_date) AS dim_birth
FROM j9 JOIN dim_member d USING (member_id) GROUP BY ALL ORDER BY 1""",
        ),
        (
            "P-MEM.versions",
            "L9、L11：dim_member 版本數（內容沒變不開版）；沒有「未知會員」列（member_sk = -1 或 member_id 為 NULL 應為 0；member_sk 是 xxhash64，本來就可能是負數）",
            """
SELECT count(*) AS versions, count(DISTINCT member_id) AS members,
  count(*) - count(DISTINCT member_id) AS extra_versions,
  sum(CASE WHEN is_current THEN 1 ELSE 0 END) AS current_rows,
  sum(CASE WHEN member_sk = -1 OR member_id IS NULL THEN 1 ELSE 0 END) AS unknown_member_rows
FROM dim_member""",
        ),
        (
            "P-MEM.quarantine",
            "會員隔離表（快照違規列）與訂單隔離表的 member_missing（訂單對不到會員版本）列數",
            """
SELECT (SELECT count(*) FROM quarantine_member) AS member_quarantine_rows,
  (SELECT count(*) FROM quarantine_order WHERE reject_category = 'member_missing') AS order_member_missing_rows""",
        ),
    ]
    for label, issue, sql in checks:
        print(f"\n===== [{label}] {issue}")
        print("SQL:" + sql)
        df = spark.sql(sql)
        print("OUTPUT:")
        print(" | ".join(df.columns))
        for r in df.collect():
            print(" | ".join("NULL" if v is None else str(v) for v in r))

    print(
        "\n===== [P-FACT.check_constraints] fact_order 的 Delta CHECK 約束（建表時加上）"
    )
    print("OUTPUT:")
    for name, expr in sorted(table_check_constraints(spark, paths.fact_order).items()):
        print(f"{name} | {expr}")

    # ---- 增量：依序跑 day1～day3，印對帳與隔離類別
    for day in (1, 2, 3):
        r = load_incremental(spark, source, day, paths)
        print(
            f"\n===== [P-DAY{day}.reconciliation] load_incremental day{day}"
        )
        for k in (
            "input_rows",
            "fact_rows",
            "quarantined_rows",
            "quarantined_by_category",
            "skipped_rows",
            "amount_review_rows",
            "amount_twd_sum",
            "unknown_product_rows",
            "unknown_member_rows",
            "member_rejected_rows",
            "fact_table_rows",
            "fact_table_amount_twd_sum",
        ):
            print(f"{k} = {getattr(r, k)}")
        print(f"balanced = {r.balanced}")

    l4_ids = [
        r.order_id
        for r in spark.read.option("header", True)
        .csv(str(DATA / "orders_incremental_day2.csv"))
        .join(
            spark.read.option("header", True)
            .csv(str(DATA / "orders_incremental_day1.csv"))
            .select("order_id"),
            "order_id",
            "left_semi",
        )
        .join(
            spark.read.option("header", True)
            .csv(str(DATA / "orders_base.csv"))
            .select("order_id"),
            "order_id",
            "left_anti",
        )
        .select("order_id")
        .distinct()
        .collect()
    ]
    sql = f"""
SELECT order_status, batch_id, count(*) AS n FROM delta.`{paths.fact_order}`
WHERE order_id IN ({", ".join(repr(i) for i in l4_ids)}) GROUP BY ALL ORDER BY ALL"""
    print(
        "\n===== [P-L4.after_day3] L4 的 25 個 id 跑完 day1～day3 後在 fact 的狀態（預期 25 列 cancelled）"
    )
    print("SQL:" + sql)
    print("OUTPUT:")
    for r in spark.sql(sql).collect():
        print(" | ".join(str(v) for v in r))

    sql = AMOUNT_EXCLUDING_REVIEW_SQL.format(
        fact_order=paths.fact_order, amount_review=paths.amount_review
    )
    print(
        "\n===== [P-ALL.amount_excluding_review] 三天後：fact 的 amount_twd 總和（所有狀態、折扣前），"
        "與排除金額人工確認清單上訂單後的總和（不是營收的定義，營收由下游語意層決定）"
    )
    print("SQL:" + sql)
    df = spark.sql(sql)
    print("OUTPUT:")
    print(" | ".join(df.columns))
    for r in df.collect():
        print(" | ".join("NULL" if v is None else str(v) for v in r))
    spark.stop()


if __name__ == "__main__":
    os.chdir(REPO)
    run_detection()
    if "--skip-pipeline" not in sys.argv:
        run_pipeline()
