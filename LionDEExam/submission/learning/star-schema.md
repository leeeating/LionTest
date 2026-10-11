# 星型模型（star schema）
把分析用的資料拆成兩種表：中間一張記錄「發生了什麼事」的事實表（fact），旁邊圍著幾張描述「是誰、是什麼、什麼時候」的維度表（dimension）。畫出來像星星。

## 白話版
- **fact 像一疊收據**：一列一筆事件，主要是數字（金額、數量），加上幾個鍵指向維度。表會一直長大，以新增為主。
- **dim 像通訊錄**：一列一個對象（會員、產品、日期），內容是拿來分組、篩選的描述（等級、城市、產品類別）。列數相對少，會被更新。
- **查詢的固定套路**：從 fact 取數字加總，join dim 拿分組條件，`GROUP BY` 維度欄位。

```
            dim_date
               │
dim_member ── fact_order ── dim_product
```

用 Python 想像：fact 是一個 list of dict，每筆只放 `{"member_sk": 2, "date_key": 20260610, "amount_twd": 3000}`；dim 是 dict，`dim_member[2] == {"member_id": "M001", "level": "金卡"}`。報表就是「掃 list、查 dict、分組加總」。

命名慣例 `fact_`、`dim_` 來自 Kimball 的維度建模，不是語法規定；用意是看名字就知道這張表該拿來加總還是拿來分組。

## 設計時要決定的四件事
1. **粒度（grain）：fact 的一列代表什麼。** 這是第一個要定、也最重要的決定，其他設計都跟著它走。例如「一列一張訂單」和「一列一次訂單狀態變更」，數字的加總方式完全不同。粒度定了，就不能在同一張 fact 混不同粒度的列。
2. **度量（measure）：fact 裡放哪些數字、能不能加總。** 金額、數量可以跨任何維度加總（additive）；餘額、庫存這類可以跨會員、產品加總，但不能跨時間加總（semi-additive，把每天的餘額加起來沒有意義）；單價、比率完全不能直接加總（non-additive）。多幣別的金額要先統一成同一種幣別，否則 `SUM` 沒有意義。
3. **維度鍵：fact 用什麼鍵指向 dim。**
   - **自然鍵（natural key）**：來源系統本來的編號，例如 `member_id`。
   - **代理鍵（surrogate key）**：倉儲自己產生的流水號，例如 `member_sk`。dim 用 SCD2 保留歷史時，同一個 `member_id` 會有多列，要指到「某一個版本」，最簡單、最常見的做法是代理鍵：單一欄位、跟來源系統的編號脫鉤。fact 寫入時就存當時版本的代理鍵，查詢時直接 join，不必再比對時間區間。替代做法是 fact 只存自然鍵，查詢時用 `(member_id, valid_from)` 這類複合鍵依時間區間對版本，見 [point-in-time-join.md](point-in-time-join.md)。
   - **日期維度**常用 `20260610` 這種整數當鍵，一天一列、事先產生好，放月份、星期、是否假日等欄位。
4. **退化維度（degenerate dimension）**：像 `order_id` 這種只有編號、沒有其他描述可放的鍵，直接留在 fact 裡，不另開維度表。

## 什麼時候用、什麼時候不要用
- **用**：給 BI 報表、分析查詢的資料倉儲（warehouse 或 lakehouse 的整理層）。查詢套路固定、好懂、join 少。
- **不要用**：應用程式日常讀寫的 OLTP 資料庫。那裡要的是正規化、避免重複，星型模型刻意把描述複製到維度裡（例如城市名直接放在 dim_member），是為了查得快、好懂，代價是寫入時要多處理。

## 其他形狀與建模方法
真正跟星型二選一的是雪花：

| 形狀 | 長相 | 優點 | 代價 |
|---|---|---|---|
| 星型（star） | dim 只有一層，描述直接放在 dim 裡 | join 少、好懂、查詢快 | 描述重複存放（每位會員都存一次城市名） |
| 雪花（snowflake） | dim 再往外拆，例如 `dim_product` → `dim_category` | 描述不重複，改一處就好 | join 變多，難懂、查詢可能較慢 |

預設選星型。Kimball 明確建議避免雪花：攤平的 dim 和雪花裝的資訊一樣，雪花只是更難懂、可能更慢。

**星系（galaxy／fact constellation）不是替代選項，是星型的延伸**：fact 不只一張時（例如 `fact_order` 和 `fact_payment`），多個星型共用同一批 dim（`dim_member`、`dim_date`），讓不同主題的數字能用同一套維度比較。被共用的 dim 叫 conformed dimension，欄位名稱與值的定義要各方一致。

不是形狀、而是另一套方法：
- **Inmon 3NF**：先建高度正規化的企業資料倉儲，再從它切出星型給各部門用（Kimball 則是直接建星型）。
- **Data Vault**：拆成 hub（業務鍵）、link（關係）、satellite（屬性與歷史），擅長整合多個來源、保留完整歷史；給報表查之前通常還要再轉成星型。
- **OBT（One Big Table）**：把 fact 和 dim join 成一張寬表，BI 直接查；columnar 儲存讓這種做法變得可行。常疊在星型之上，當作給 BI 的最後一層，不一定取代星型。限制是一張 OBT 只能有一種粒度，維度屬性變了也要回頭改寫所有相關列。

## 最小可跑範例
DuckDB，一張 fact、兩張 dim；`dim_member` 用 SCD2，M001 在 6/1 從普卡升金卡（`uv run python demo.py`）：

```python
import duckdb

con = duckdb.connect()
# 維度：會員（SCD2，同一個 member_id 有兩個版本，各有自己的代理鍵 member_sk）
con.sql("""CREATE TABLE dim_member AS SELECT * FROM (VALUES
  (1, 'M001', '普卡', DATE '2026-01-01', DATE '2026-06-01'),
  (2, 'M001', '金卡', DATE '2026-06-01', DATE '9999-12-31'),
  (3, 'M002', '普卡', DATE '2026-01-01', DATE '9999-12-31')
) t(member_sk, member_id, member_level, valid_from, valid_to)""")
# 維度：日期（一天一列，事先產生）
con.sql("""CREATE TABLE dim_date AS
  SELECT CAST(strftime(d, '%Y%m%d') AS INT) AS date_key, d AS full_date, month(d) AS month
  FROM range(DATE '2026-05-01', DATE '2026-07-01', INTERVAL 1 DAY) r(d)""")
# 事實：一列一張訂單，只放鍵和數字；member_sk 是寫入時就對好的「當時版本」
con.sql("""CREATE TABLE fact_order AS SELECT * FROM (VALUES
  ('O1', 1, 20260515, 1000),
  ('O2', 2, 20260610, 3000),
  ('O3', 3, 20260611, 500)
) t(order_id, member_sk, date_key, amount_twd)""")

print(con.sql("""
  SELECT d.month, m.member_level, SUM(f.amount_twd) AS revenue
  FROM fact_order f
  JOIN dim_member m USING (member_sk)
  JOIN dim_date d USING (date_key)
  GROUP BY ALL ORDER BY ALL
""").fetchall())
```

實際輸出（duckdb 1.5.6）：

```
[(5, '普卡', 1000), (6, '普卡', 500), (6, '金卡', 3000)]
```

M001 的 5 月訂單算在普卡、6 月訂單算在金卡：因為 fact 存的是代理鍵，歷史等級被保留下來。如果 fact 只存 `member_id` 再 join「目前」的會員資料，5 月那筆也會被算成金卡。

## 常見的坑
- **fact join 到沒有唯一鍵的表，一列變多列**：Part B #7，`build_fact` join 的是原始 members 快照（同一會員多列），不是 `dim_member` 的單一版本，訂單和金額被放大。
- **粒度沒講清楚**：若照官方語意（增量檔裡同一個 `order_id` 是同一張訂單的狀態更新），fact 要「一列一張訂單」，寫入前就得去重並以 `order_id` upsert，MERGE 是常見做法（Part B #2、#9）。但實測增量和 base 同 `order_id` 的列，連 `member_id`、`amount` 都不同，`order_id` 能不能當唯一鍵是 Part A 待定的 ADR。
- **金額沒統一幣別就加總**：資料裡同時有 TWD、USD、JPY，`orders_base` 另有 `NTD`（200 筆，要怎麼對應是 A-3 要檢核的事，見 `notes/dataset/dictionary.md`）；換算邏輯見 Part B 的 `convert_currency`。

## 本專案出處
- 題目 A-1：設計 `fact_order`、`dim_member`（SCD2）、`dim_product`、`dim_date`，並說明粒度、金額處理、維度鍵設計。這三項是 Part A 要由我決定、寫 ADR 的地方，本筆記只講觀念。
- `buggy_pipeline.py`：寫出 `dim/dim_member`、`fact/fact_order`，`build_fact()` 的 `converted.join(members, "member_id", "left")`。
- 相關筆記：[scd.md](scd.md)（維度歷史）、[point-in-time-join.md](point-in-time-join.md)（fact 只存自然鍵時，怎麼對到當時的版本）。

## 官方文件
未證實：這次沒有讀原始文獻，內容是 Kimball 維度建模的一般說法；「其他形狀與建模方法」中 Inmon、Data Vault、OBT 同樣是一般知識。

Kimball Group（驗收 agent 查證過）：
- 雪花維度與「避免雪花」的建議：https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/snowflake-dimension/
- conformed dimension：https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/conformed-dimension/可對照 Kimball & Ross《The Data Warehouse Toolkit》（粒度、代理鍵、退化維度的出處），以及 Kimball Group 網站的 Dimensional Modeling Techniques 列表。
