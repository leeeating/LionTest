# 帳本模式（ledger）：只新增、錯了用沖銷
帳本表只 INSERT、從不 UPDATE／DELETE；記錯了就加一筆**沖銷分錄（reversal）**抵掉原分錄，再加一筆正確的；**餘額＝把分錄加總**，不是讀某一欄。

## 白話版
像銀行存摺：印錯一行，行員不會拿立可白塗掉，而是在下面再印一行「沖正 -5000」、再印一行正確的「+500」。存摺上的餘額是一路加下來的。
- Python 類比：狀態不是 `balance = 500`（覆寫），而是 `entries.append(+5000); entries.append(-5000); entries.append(+500)`，要餘額就 `sum(entries)`。
- C# 類比：分錄是 immutable record，`with` 也不用，只能 `Add` 新的一筆。

**double-entry（複式記帳）**：會計上每筆交易至少記兩邊（借、貸），兩邊金額相等，加總永遠為 0，用來自我檢查。資料工程借用的主要是「只新增＋沖銷」，不一定要做到借貸兩邊。

**跟其他觀念的關係**：
- **事實表**：帳本就是一張交易事件 fact（[fact-table-types.md](fact-table-types.md)），只是多了「更正也用新列表達」這條紀律。
- **event sourcing**：同一個想法用在應用程式狀態上，把所有變更存成事件序列，狀態由重播事件得出；Martin Fowler 直接把帳戶列為 event sourcing 的例子。

## 什麼時候用、什麼時候不要用
- **用**：金額、點數、庫存這類要能**稽核**（誰在何時改了什麼）和**重算任一時點**的數字；上游會送更正、退款，而且「改之前是多少」本身有意義。
- **好處**：
  - 可稽核：錯誤與更正都留在表上。
  - 可重算：加總到某天為止，就是那天的帳。
  - 冪等寫入容易：每筆分錄有自然鍵（例：`order_id`＋`entry_seq`），重跑同一批用 `INSERT ... ON CONFLICT DO NOTHING` 就不會重複入帳（對照 [merge-idempotent-write.md](../2-incremental-etl/merge-idempotent-write.md)）。
- **代價**：查「目前狀態」要加總；量大時要另建快照或彙總表（例如每日餘額，即定期快照）。表只會變大。
- **不要用**：描述性屬性（會員地址、產品名稱）只要目前值或用 SCD 處理即可（[scd.md](scd.md)），硬做成帳本只是讓查詢變難。

## 最小可跑範例
存成 `/tmp/ledger.py`，在 `LionTest/` 執行 `uv run python -I /tmp/ledger.py`（DuckDB 1.5.6）：

```python
import duckdb
con = duckdb.connect()
# 帳本：只 INSERT。自然鍵 (order_id, entry_seq) 當 PK，重跑同一批不會重複入帳
con.sql("""CREATE TABLE ledger (
  order_id VARCHAR, entry_seq INT, posted_on DATE, entry_type VARCHAR, amount INT, reverses_seq INT,
  PRIMARY KEY (order_id, entry_seq))""")

def post(rows):
    con.executemany("INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", rows)

day1 = [('O1', 1, '2026-07-01', 'sale', 3000, None),
        ('O2', 1, '2026-07-01', 'sale', 5000, None)]      # O2 金額打錯，應為 500
post(day1)
post(day1)                                                 # 同一批重跑
print("rows after posting day1 twice:", con.sql("SELECT count(*) FROM ledger").fetchone()[0])

day2 = [('O2', 2, '2026-07-02', 'reversal', -5000, 1),     # 沖銷錯誤分錄（不 UPDATE 原列）
        ('O2', 3, '2026-07-02', 'sale', 500, None),        # 再記一筆正確的
        ('O1', 2, '2026-07-02', 'refund', -3000, 1)]       # 真的退款：獨立一筆負向分錄
post(day2)

print("-- 帳本全貌（錯誤與更正都留著，可稽核）")
con.sql("SELECT * FROM ledger ORDER BY order_id, entry_seq").show()

print("-- 目前淨額 = 加總；也可重算任一天結束時的帳")
con.sql("""SELECT order_id,
  sum(amount) FILTER (WHERE posted_on <= DATE '2026-07-01') AS net_as_of_0701,
  sum(amount) AS net_now
FROM ledger GROUP BY 1 ORDER BY 1""").show()
```

實際輸出（2026-10-17 本機執行）：

```
rows after posting day1 twice: 2
-- 帳本全貌（錯誤與更正都留著，可稽核）
┌──────────┬───────────┬────────────┬────────────┬────────┬──────────────┐
│ order_id │ entry_seq │ posted_on  │ entry_type │ amount │ reverses_seq │
│ varchar  │   int32   │    date    │  varchar   │ int32  │    int32     │
├──────────┼───────────┼────────────┼────────────┼────────┼──────────────┤
│ O1       │         1 │ 2026-07-01 │ sale       │   3000 │         NULL │
│ O1       │         2 │ 2026-07-02 │ refund     │  -3000 │            1 │
│ O2       │         1 │ 2026-07-01 │ sale       │   5000 │         NULL │
│ O2       │         2 │ 2026-07-02 │ reversal   │  -5000 │            1 │
│ O2       │         3 │ 2026-07-02 │ sale       │    500 │         NULL │
└──────────┴───────────┴────────────┴────────────┴────────┴──────────────┘

-- 目前淨額 = 加總；也可重算任一天結束時的帳
┌──────────┬────────────────┬─────────┐
│ order_id │ net_as_of_0701 │ net_now │
│ varchar  │     int128     │ int128  │
├──────────┼────────────────┼─────────┤
│ O1       │           3000 │       0 │
│ O2       │           5000 │     500 │
└──────────┴────────────────┴─────────┘
```

重點：
- day1 送兩次，表裡仍只有 2 列（PK 是自然鍵，冪等）。
- O2 記錯的 5000 沒被改掉，由 `reversal -5000` 抵銷、再記 `sale 500`；淨額 500。
- O1 的退款是**獨立一筆負向分錄**（`refund -3000`），原本的 `sale` 仍是 +3000。
- `net_as_of_0701` 可重算 07-01 當天的帳（O2 當時是錯的 5000），UPDATE 式的表做不到。

## 常見的坑
- **把負數塞進原交易的金額欄當作退款**：原交易的金額被改成負數，就分不出「原本賣了多少」和「退了多少」，也無法稽核。帳本模式下退款是另一筆分錄、另一個 `entry_type`，原交易金額照樣是正數，所以「交易金額 `> 0`」可以當資料契約檢查。
- **沖銷沒指回原分錄**：沒有 `reverses_seq` 這類欄位，之後分不清哪筆沖哪筆，也可能重複沖銷。
- **分錄序號不穩定**：序號若在每次重跑時重新產生（例如用 `row_number()` 對不穩定排序編號），重跑會產生新鍵，冪等就失效。序號要來自來源，或由穩定的排序決定。
- **直接 SUM 所有分錄當營收**：退款、沖銷都是負數，要依 `entry_type` 分開看「銷售」和「淨額」。

## 本專案出處
- process-log 事件「「負數？？」：base 的負數金額不是退款」：base 有 50 筆負數金額，使用者判斷不是退款，「`amount > 0` 是資料契約」，違反就隔離、告警、開卡追上游（依據 `part_b/evidence.md` E9）。對照帳本模式：真正的退款會是一筆獨立的沖銷分錄，不會以負數的訂單金額出現，所以這 50 筆負數更像資料錯誤。
- 本專案的訂單來源不是帳本（增量檔是狀態事件，用 `updated_at` 區分新舊），這份筆記是對照用的設計模式。

## 官方文件
- Martin Fowler, Event Sourcing（已讀）：https://martinfowler.com/eaaDev/EventSourcing.html 。定義「把應用狀態的所有變更存成事件序列」；帳戶的分錄是「改變帳戶值的所有事件的 log」，帳戶本身就是 event sourcing 的例子；狀態可丟掉再重播事件重建；用差額記錄的事件最容易反轉。
- Martin Fowler, Reversal Adjustment（已讀）：https://martinfowler.com/eaaDev/ReversalAdjustment.html 。更正不改原分錄，而是新增兩筆：一筆同金額反號的沖銷、一筆正確的分錄；沖銷掛在原分錄上；適用於分錄不可變的情況。
- 未證實：double-entry 的說明是會計通識，這次沒讀官方會計準則；「冪等寫入用自然鍵＋分錄序號」與 `ON CONFLICT DO NOTHING` 的用法是本範例實測結果，非上述文章內容。
