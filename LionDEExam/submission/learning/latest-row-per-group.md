# SQL：取每組最新一筆
用 `ROW_NUMBER() OVER (PARTITION BY 組 ORDER BY 時間 DESC)` 幫每組排名，只留第 1 名。

## 白話版
像 Python 先 `sorted(rows, key=時間, reverse=True)`，再 `groupby(組)` 取每組第一個。`PARTITION BY` 是 groupby，`ORDER BY ... DESC` 是組內排序，`rn = 1` 是取第一個。`GROUP BY` + `MAX()` 只能拿到最大值，拿不到「那一整列」，所以要用 window function。

## 什麼時候用、什麼時候不要用
- 用：事件表（每變一次狀態多一列），要每個 key 的最新狀態；去重時要指定留哪一列。
- 不要用：只要最大值本身（`GROUP BY` + `MAX` 較簡單）；或同一 key 的多列本來就不該被丟掉，這時該先隔離而不是去重（見下方「撞號」）。

## 最小可跑範例
DuckDB，inline 資料，整段可直接貼進 `uv run python`（本次實際執行）。A1 有 3 筆事件，B2 有 2 筆，C3 的兩筆 `updated_at` 相同（刻意製造同分）。

```python
import duckdb
con = duckdb.connect()
con.execute("""
create table ev as select * from (values
  ('A1','created',  timestamp '2026-05-01 10:00', timestamp '2026-05-01 10:00'),
  ('A1','paid',     timestamp '2026-05-01 10:00', timestamp '2026-05-02 09:00'),
  ('A1','completed',timestamp '2026-05-01 10:00', timestamp '2026-05-03 18:00'),
  ('B2','created',  timestamp '2026-05-02 08:00', timestamp '2026-05-02 08:00'),
  ('B2','cancelled',timestamp '2026-05-02 08:00', timestamp '2026-05-02 08:30'),
  ('C3','paid',     timestamp '2026-05-03 12:00', timestamp '2026-05-04 00:00'),
  ('C3','completed',timestamp '2026-05-03 12:00', timestamp '2026-05-04 00:00')
) t(order_id, status, order_created_at, updated_at)""")

# 寫法 1：子查詢（PostgreSQL、Spark 等通用）
print(con.sql("""select order_id, status, updated_at from (
  select *, row_number() over (partition by order_id order by updated_at desc) rn from ev
) where rn = 1 order by order_id""").fetchall())

# 寫法 2：DuckDB 的 QUALIFY（不需要子查詢）
print(con.sql("""select order_id, status, updated_at from ev
qualify row_number() over (partition by order_id order by updated_at desc) = 1
order by order_id""").fetchall())
```
兩種寫法輸出相同：
```
A1 completed 2026-05-03 18:00
B2 cancelled 2026-05-02 08:30
C3 paid      2026-05-04 00:00   <- 同分，這個結果不可靠，見下
```
`QUALIFY` 對 window function 的作用，就像 `HAVING` 對 aggregate：window 在 `WHERE` 之後才算，所以 `WHERE` 不能直接濾 `rn`。

## 常見的坑
1. **先 `dropDuplicates` 再排序，等於沒排序**：`clean_orders` 中的 `dropDuplicates(["order_id"])` 放在 window 前面，每個 order_id 只剩任意一列，後面的排序沒有作用。去重本身就是 `rn = 1`，不需要先 drop。
2. **排序欄位選錯**：原程式用 `order_created_at`，但同一張單的多次更新下單時間相同，應該用 `updated_at`。同一份資料用 `order_created_at` 排序，A1 變成 `created`（舊狀態，因為三列同分，只是剛好被挑到）；用 `updated_at` 才是 `completed`。
3. **同分時結果不穩定**：C3 兩列 `updated_at` 相同，把輸入順序用 `order by random()` 洗牌後重跑 5 次，結果是 `paid, paid, paid, completed, paid`，同樣 SQL 會變。DuckDB 與 PostgreSQL 文件都沒有保證同分時的編號順序（兩頁都沒明講，只是沒承諾）。解法是加**有業務意義**的次排序鍵，例如把 status 對應成先後順序：
   ```sql
   order by updated_at desc,
     case status when 'created' then 1 when 'paid' then 2
                 when 'completed' then 3 when 'cancelled' then 3 end desc
   ```
   completed 與 cancelled 同為 3，同時出現時仍會同分；這是終態衝突，應送隔離，不靠排序決定。（實跑：同一 `updated_at` 放這兩列，洗牌 20 次，結果在兩者之間跳動。）
   同樣洗牌 5 次，C3 每次都是 `completed`。**原則：次排序鍵要有業務意義，不能只是為了讓結果固定。** 反例：`status desc` 也會讓結果固定，但是依字母序固定選到 `paid`，業務上 `completed` 才是較新的狀態，固定了卻選錯。另一個選擇是用來源檔序號（如讀檔時的 row number）當次排序鍵；若無法判斷先後，就把同分列隔離、人工確認。
4. **「撞號」不能直接去重**：同一 order_id 的列若下單時間、會員、金額都不同，可能是不同訂單用了同一個號碼，取最新一筆會悄悄丟掉另一張單。要先確認 key 是否唯一，對不上的列送隔離表。

## 本專案出處
- `clean_orders` 中的 `dropDuplicates(["order_id"])` 與 `orderBy(F.col("order_created_at").desc())`
- `part_b/code-review.md` 的 #5「去重保留的是任意一筆，不是最新狀態」；證據在 `part_b/evidence.md`
- `notes/part_b/dedup.md`「為什麼不能直接去重」

## 官方文件
- DuckDB window functions（已讀）：https://duckdb.org/docs/current/sql/functions/window_functions.html（`row_number` 從 1 起算；`ORDER BY` 缺少時結果 not well-defined；未明講同分如何編號）
- DuckDB QUALIFY（已讀）：https://duckdb.org/docs/current/sql/query_syntax/qualify.html（濾 window 結果，免子查詢；位置在 WINDOW 之後、ORDER BY 之前；完整 evaluation order 該頁未寫，上述 WHERE 先於 window 的說法來自 window functions 頁）
- PostgreSQL window functions（已讀）：https://www.postgresql.org/docs/current/functions-window.html（`row_number()` 的定義；未明講同分編號順序）
