# SQL：point-in-time join
用半開區間 `valid_from <= t < valid_to`，讓每筆事實對到它發生「當時」的維度版本（SCD2）；**邊界日只會對到一版，不會重複**。

## 白話版
王小明 4/30 是銀卡、5/31 升金卡。5/15 的訂單要答「銀卡」，不是現在的金卡。
Python 類比：維度是一個按 `valid_from` 排序的版本 list，point-in-time join 就是對每筆訂單用 `bisect` 找「最後一個 `valid_from <= 訂單日` 的版本」。
區間要半開：舊版 `valid_to` 和新版 `valid_from` 是同一天（5/31），兩端都含的話，5/31 的訂單兩版都命中。

## 什麼時候用、什麼時候不要用
- **用**：事實要帶「當時」的屬性（等級、價格、所屬部門），維度有 SCD2 的有效期間欄位。
- **不要用**：維度只有目前版本（SCD1），或分析就是要「現在」的屬性，普通 join 即可。
- 更好的做法是事實表只存 `member_sk`（surrogate key），等級從維度查，寫入時就定下版本（Kimball 的做法）。

## 最小可跑範例
在 `LionTest/` 把下面存成 `pit.py`，執行 `uv run python pit.py`（DuckDB，資料用 `VALUES`）：

```python
import duckdb
con = duckdb.connect()
con.sql("""
CREATE TABLE dim AS SELECT * FROM (VALUES
 ('M001','銀卡',DATE '2026-04-30',DATE '2026-05-31'),
 ('M001','金卡',DATE '2026-05-31',DATE '9999-12-31')) t(member_id,level,valid_from,valid_to);
CREATE TABLE fact AS SELECT * FROM (VALUES
 ('O1','M001',DATE '2026-05-15'),
 ('O2','M001',DATE '2026-05-31'),   -- 邊界日
 ('O3','M001',DATE '2026-04-01')) t(order_id,member_id,order_date);  -- 早於第一版
""")
queries = {
 "A. BETWEEN": """SELECT f.order_id, f.order_date, d.level FROM fact f LEFT JOIN dim d
   ON f.member_id = d.member_id AND f.order_date BETWEEN d.valid_from AND d.valid_to
   ORDER BY 1, 3""",
 "B. 半開區間": """SELECT f.order_id, f.order_date, d.level FROM fact f LEFT JOIN dim d
   ON f.member_id = d.member_id AND f.order_date >= d.valid_from AND f.order_date < d.valid_to
   ORDER BY 1, 3""",
 "C. ASOF": """SELECT f.order_id, f.order_date, d.level FROM fact f ASOF LEFT JOIN dim d
   ON f.member_id = d.member_id AND f.order_date >= d.valid_from
   ORDER BY 1, 3""",
}
for name, q in queries.items():
    print("--", name)
    con.sql(q).show()
```

實際輸出（2026-10 本機執行）：

```
-- A. BETWEEN                    -- B. 半開區間               -- C. ASOF
O1 2026-05-15 銀卡               O1 2026-05-15 銀卡           O1 2026-05-15 銀卡
O2 2026-05-31 金卡               O2 2026-05-31 金卡           O2 2026-05-31 金卡
O2 2026-05-31 銀卡  <- 重複      O3 2026-04-01 NULL           O3 2026-04-01 NULL
O3 2026-04-01 NULL
```

A 的 O2 變兩列，金額會被加總兩次；B、C 每筆訂單一列。O3 早於第一版所以是 NULL（見下方「坑」）。
**ASOF 取捨**：寫法短、保證每列最多一個匹配；但它只看 `valid_from`，不看 `valid_to`。ASOF 不能加第二個不等式（`AND order_date < valid_to` 會報 `Binder Error: Multiple ASOF JOIN inequalities`），維度版本中間有空窗時會對到已過期的舊版。實測（銀卡 4/30–5/10、金卡 5/31 起，O1 在 5/15 的空窗）：

```
ASOF LEFT JOIN            -> O1 2026-05-15 銀卡 valid_to=2026-05-10   (對到已過期版本)
半開區間 LEFT JOIN        -> O1 2026-05-15 NULL
ASOF + WHERE order_date < valid_to -> 0 rows   (O1 整列被丟掉，等於變 INNER)
ASOF + CASE WHEN order_date < valid_to THEN level END -> O1 2026-05-15 NULL
```

空窗要另外過濾：想保留訂單就用 `CASE WHEN f.order_date < d.valid_to THEN d.level END`，或直接改用半開區間 join；`WHERE order_date < valid_to` 會把對不到的訂單整列丟掉，只在要丟時用。

## 常見的坑
- **直接 join 原始快照，一對多膨脹**：989 人有多筆快照，join 後同一訂單每個快照一列，且帶著不同等級。要 join 的是有區間的維度，不是快照。
- **BETWEEN 邊界日重複配對**：如上例 O2。用 `>= valid_from AND < valid_to`，並用 `COUNT(*)` 對照 join 前後列數。
- **沒回填歷史，舊訂單對不到**：dim 從空表只吃最新快照，只會有一版，早於其 `valid_from` 的訂單全是 NULL（day1 去重後 4,597 張中 49 張）。要依 `extract_date` 由舊到新逐批載入，或一次性回填。
- **第一版 `valid_from` 怎麼定**（業務定義，要確認）：第一筆快照日（只記觀測，早於它的訂單對不到）、`register_date`（推定）、`1900-01-01`（一定對得到但看不出推定範圍）。
- **`valid_to` 用 NULL 代表目前版本**時，`< valid_to` 會 NULL 比較失敗；本專案用 `9999-12-31`。

## 本專案出處
- `part_b/code-review.md` #4：`build_fact` 中的 `converted.join(members, "member_id", "left")`，改 join `dim_member` 並用半開區間。
- `part_b/code-review.md` #6 (c)「初始載入」：回填歷史與第一版 `valid_from`。
- `notes/part_b/scd2.md`：王小明例子與「第一版的 `valid_from` 定在哪」。

## 官方文件
- DuckDB ASOF JOIN（已讀）：https://duckdb.org/docs/current/guides/sql_features/asof_join.html 。內容：每個左列配對最近的較早右列；`INNER ASOF` 丟掉無匹配列，`LEFT ASOF` 補 NULL；範例只用 `>=`。
- Kimball Group, Type 2（已讀）：https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/ 。Type 2 新增一列、配新 surrogate key，並建議加 row effective date、row expiration date、current row indicator。
- Kimball 未明講「半開區間」；半開是本專案採用的慣例，來源非官方。
