# 有時效性的屬性：怎麼記錄、怎麼查「當時」的值
會員等級、匯率、產品價格這類值**只在某段時間有效**；要能回答「5/15 那時是什麼」，就得把時間一起存下來，查詢時用 point-in-time（as-of）join 對到當時的版本。

## 白話版
王小明 4/30 是銀卡、5/31 升金卡。5/15 的訂單要答「銀卡」，不是現在的金卡。只存目前值（`member["M001"] = "金卡"`，dict 覆寫）就答不出來。

**三種記錄方式**（Python 類比：都是把 dict 換成「帶時間的 list」）：

| 方式 | 一列代表 | 例子 | 查「當時」 |
|---|---|---|---|
| 定期快照 | 某個時點看到的全貌，沒變也抄一份 | `members.csv` 每月一份、每日匯率表 | 取「快照日 ≤ t 的最新一份」（as-of） |
| 變更紀錄 | 一次變更（「5/31 改成金卡」） | 價格異動 log、CDC 事件 | 取「變更時間 ≤ t 的最新一筆」（as-of） |
| 有效期間 | 一個值與它的有效區間 `valid_from`～`valid_to` | SCD2 維度（見 [scd.md](scd.md)） | 區間判斷 `valid_from <= t < valid_to` |

前兩種是原料、寫入簡單；第三種是把「每個值有效到何時」事先算好，下游查詢最簡單。三者可以互相轉換：快照或變更紀錄依時間排序後，用 `lead()` 取下一筆的時間當 `valid_to`，就得到有效期間（[scd.md](scd.md)「快照不是也能查『當時』嗎」有範例）。

**兩種時間**：每筆變更其實有兩個時間：
- **業務生效時間**（event time / valid time）：這件事在真實世界何時發生，例：`updated_at`。
- **系統收到時間**（arrival / system time）：資料何時進到我們手上，例：哪一天的增量檔。

兩者順序不一定相同（晚到的舊事件）。「最新的值」要先決定照哪一種時間排序，否則會選錯版本。

## 什麼時候用、什麼時候不要用
- **用**：事實要帶「當時」的屬性（等級、價格、匯率、所屬部門），或要能重現過去某天的報表。
- **不要用**：分析就是要「現在」的屬性，或屬性不會變；只存目前值、普通 join 即可。
- 選記錄方式：來源只給定期全量 → 先存快照；來源給異動事件 → 存變更紀錄；下游多、查詢多 → 再整理成有效期間。
- 事實表可以在寫入時就存版本的 surrogate key（Kimball 的做法，見 [star-schema.md](star-schema.md)「維度鍵」），之後查詢是等值 join，不必每次比對時間。

## 最小可跑範例
存成 `/tmp/time_varying.py`，在 `LionTest/` 執行 `uv run python -I /tmp/time_varying.py`（DuckDB 1.5.6）：

```python
import duckdb
con = duckdb.connect()
# ---- 1. 有效期間（SCD2）＋ point-in-time join ----
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
 "A. BETWEEN": "f.order_date BETWEEN d.valid_from AND d.valid_to",
 "B. 半開區間": "f.order_date >= d.valid_from AND f.order_date < d.valid_to",
}
for name, cond in queries.items():
    print("--", name, con.sql(f"""SELECT f.order_id, d.level FROM fact f LEFT JOIN dim d
      ON f.member_id = d.member_id AND {cond} ORDER BY 1, 2""").fetchall())
print("-- C. ASOF", con.sql("""SELECT f.order_id, d.level FROM fact f ASOF LEFT JOIN dim d
  ON f.member_id = d.member_id AND f.order_date >= d.valid_from ORDER BY 1""").fetchall())

# ---- 2. ASOF 遇到版本空窗（銀卡 4/30–5/10，金卡 5/31 起；O1 在空窗內）----
con.sql("""CREATE TABLE dim_gap AS SELECT * FROM (VALUES
 ('M001','銀卡',DATE '2026-04-30',DATE '2026-05-10'),
 ('M001','金卡',DATE '2026-05-31',DATE '9999-12-31')) t(member_id,level,valid_from,valid_to)""")
o1 = "(SELECT * FROM fact WHERE order_id = 'O1')"
print("-- 空窗 ASOF       ", con.sql(f"""SELECT f.order_id, d.level, d.valid_to FROM {o1} f ASOF LEFT JOIN dim_gap d
  ON f.member_id = d.member_id AND f.order_date >= d.valid_from""").fetchall())
print("-- 空窗 半開區間   ", con.sql(f"""SELECT f.order_id, d.level FROM {o1} f LEFT JOIN dim_gap d
  ON f.member_id = d.member_id AND f.order_date >= d.valid_from AND f.order_date < d.valid_to""").fetchall())
print("-- 空窗 ASOF+WHERE ", con.sql(f"""SELECT f.order_id, d.level FROM {o1} f ASOF LEFT JOIN dim_gap d
  ON f.member_id = d.member_id AND f.order_date >= d.valid_from WHERE f.order_date < d.valid_to""").fetchall())
print("-- 空窗 ASOF+CASE  ", con.sql(f"""SELECT f.order_id, CASE WHEN f.order_date < d.valid_to THEN d.level END
  FROM {o1} f ASOF LEFT JOIN dim_gap d ON f.member_id = d.member_id AND f.order_date >= d.valid_from""").fetchall())

# ---- 3. 兩種時間：業務生效時間（updated_at）vs 系統收到時間（批次檔）----
con.sql("""CREATE TABLE status_events AS SELECT * FROM (VALUES
 ('ORD1','cancelled', TIMESTAMP '2026-07-04 18:08:26', 'day1'),
 ('ORD1','paid',      TIMESTAMP '2026-07-03 12:08:26', 'day2')   -- 晚到的舊事件
) t(order_id, status, updated_at, batch)""")
print("-- 照檔案順序取最後一筆:", con.sql("SELECT order_id, arg_max(status, batch) FROM status_events GROUP BY 1").fetchall())
print("-- 照 updated_at 取最新:", con.sql("SELECT order_id, arg_max(status, updated_at) FROM status_events GROUP BY 1").fetchall())
```

實際輸出（2026-10-17 本機執行）：

```
-- A. BETWEEN [('O1', '銀卡'), ('O2', '金卡'), ('O2', '銀卡'), ('O3', None)]
-- B. 半開區間 [('O1', '銀卡'), ('O2', '金卡'), ('O3', None)]
-- C. ASOF [('O1', '銀卡'), ('O2', '金卡'), ('O3', None)]
-- 空窗 ASOF        [('O1', '銀卡', datetime.date(2026, 5, 10))]
-- 空窗 半開區間    [('O1', None)]
-- 空窗 ASOF+WHERE  []
-- 空窗 ASOF+CASE   [('O1', None)]
-- 照檔案順序取最後一筆: [('ORD1', 'paid')]
-- 照 updated_at 取最新: [('ORD1', 'cancelled')]
```

- **第 1 段（point-in-time join）**：A 的 O2 在邊界日 5/31 變兩列，金額會被加總兩次；B 半開區間、C ASOF 每筆訂單一列。O3 早於第一版，三種都是 NULL（見「坑」）。
- **第 2 段（ASOF 的取捨）**：ASOF 寫法短、保證每列最多一個匹配，但它只看 `valid_from`，不看 `valid_to`；版本中間有空窗時會對到已過期的版本（銀卡，`valid_to=5/10`）。ASOF 不能加第二個不等式（`AND order_date < valid_to` 會報 `Binder Error: Multiple ASOF JOIN inequalities`，本次實測）。要保留訂單就用 `CASE WHEN f.order_date < d.valid_to THEN d.level END`，或改用半開區間 join；`WHERE order_date < valid_to` 會把對不到的訂單整列丟掉（`LEFT` 變成 `INNER`）。
- **第 3 段（兩種時間）**：同一張單兩筆狀態，照檔案順序最新是 `paid`，照 `updated_at` 最新是 `cancelled`，答案相反。

## 常見的坑
- **只存目前值**：SCD1 或直接覆寫，歷史就沒了，事後補不回來。
- **直接 join 原始快照，一對多膨脹**：本專案 989 人有多筆快照，join 後同一訂單每個快照一列，且帶著不同等級。要嘛做 as-of（只取 ≤ t 的最新一份），要嘛先整理成有效期間。
- **BETWEEN 邊界日重複配對**：如上例 O2。用 `>= valid_from AND < valid_to`，並用 `COUNT(*)` 對照 join 前後列數。
- **混用兩種時間**：用檔案順序（收到時間）判斷新舊，晚到的舊事件會蓋掉較新的值；反之用 `updated_at` 時，要確認它在來源裡可信。這是業務定義，要寫清楚採用哪一種。
- **沒回填歷史，舊事實對不到**：維度從空表只吃最新快照，只會有一版，早於其 `valid_from` 的訂單全是 NULL（本專案 day1 去重後 4,597 張中 49 張）。要依快照日由舊到新逐批載入，或一次性回填。
- **第一版 `valid_from` 怎麼定**（業務定義，要確認）：第一筆快照日、`register_date`（推定）、`1900-01-01`（一定對得到但看不出推定範圍），取捨見 [scd.md](scd.md)。
- **`valid_to` 用 NULL 代表目前版本**時，`< valid_to` 會 NULL 比較失敗；本專案用 `9999-12-31`。

## 本專案出處
- `members.csv` 是定期快照（`extract_date` 不同），是有效期間的原料，見 [scd.md](scd.md)「本專案」。
- `part_b/code-review.md` #7：`build_fact` 中的 `converted.join(members, "member_id", "left")` 直接 join 原始快照，改 join `dim_member` 並用半開區間。
- `part_b/appendix.md`「SCD2 初始載入」（報告 #6 (c) 的補充）：回填歷史與第一版 `valid_from`。
- 兩種時間：`part_a/source-schema-inference.md` 的 L4、J6。增量檔 day1→day2 有 25 個 order_id，day2 送來的 `paid` 其 `updated_at` 比 day1 的 `cancelled` 舊（例 `ORD00100020`：day1 cancelled 07-04T18:08:26、day2 paid 07-03T12:08:26）；照檔案順序與照 `updated_at` 得到相反的最終狀態。採用哪一種是 J6 待使用者決定的解讀。範例第 3 段即以此為原型。

## 官方文件
- DuckDB ASOF JOIN（已讀）：https://duckdb.org/docs/current/guides/sql_features/asof_join.html 。每個左列最多配一個右列：同鍵中時間 ≤ 左列的最近一筆；`ASOF JOIN` 丟掉無匹配列，`ASOF LEFT JOIN` 補 NULL；`USING` 寫法時不等式必須是 `>=` 且放最後。
- Kimball Group, Type 2（先前已讀）：https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/ 。Type 2 新增一列、配新 surrogate key，並建議加 row effective date、row expiration date、current row indicator。
- Kimball Group, Periodic Snapshot Fact Tables（已讀）：https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/periodic-snapshot-fact-table/ 。「粒度是期間」，對應上表的「定期快照」。
- 未證實：「三種記錄方式」的分類、「業務生效時間 vs 系統收到時間」（bitemporal 的 valid time / transaction time）的說法是通用業界整理，這次沒讀到官方定義頁；Kimball 未明講「半開區間」，半開是本專案採用的慣例。
