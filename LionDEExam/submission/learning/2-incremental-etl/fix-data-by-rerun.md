# 修正資料：改源頭或改規則再重跑，不直接改倉儲
倉儲裡的資料是「來源＋規則」算出來的結果。資料錯了，要修的是來源或規則，再重跑管線；直接下 SQL 改結果，下次重跑就會被蓋回去。

## 白話版
倉儲就像照食譜做出來的菜。菜太鹹時，可以換食材（上游送更正），或改食譜（改規則再重跑）。直接往盤子裡加水只能應急，下次照食譜做出來還是一樣鹹。

和 OLTP 的差別：OLTP 的資料表本身就是正本，下 `UPDATE` 改的就是事實。倉儲的表只是衍生物，正本在來源檔。

## 什麼時候用哪一種
| 做法 | 什麼時候用 | 代價 |
|---|---|---|
| 1. **上游送更正** | 來源資料錯了，例如金額打錯 | 要等上游；管線不用改，更正以新的一批送進來，MERGE 依 updated_at 覆寫 |
| 2. **改規則再重跑**（backfill） | 規則錯了，例如去重邏輯有 bug | 受影響的批次都要重跑，前提是管線冪等，而且舊的來源檔還在 |
| 3. **直接下 SQL 改倉儲** | 緊急止血，等不及前兩種 | 倉儲和來源對不上，對帳失效；之後一定要補上 1 或 2，否則重跑就被蓋回去。改了要留紀錄 |

隔離表裡的列也是一樣：修好來源後重新送進管線，不要手動搬進 fact。

## 最小可跑範例
在 repo 根目錄執行：`uv run python -I /tmp/fix_demo/demo.py`（2026-10-19 實跑，用 DuckDB，不需要啟動 Spark）

```python
import duckdb

con = duckdb.connect()
# 來源檔（原始資料）：ORD002 金額打錯，多了一個 0
con.execute("CREATE TABLE src AS SELECT * FROM (VALUES ('ORD001', 100), ('ORD002', 2000)) t(order_id, amount)")

def rebuild():
    """管線：依來源與規則整張重建 fact（這裡的規則只有一條：amount > 0）。"""
    con.execute("CREATE OR REPLACE TABLE fact AS SELECT * FROM src WHERE amount > 0")

def show(title):
    print(f"== {title}")
    print(con.sql("SELECT * FROM fact ORDER BY order_id").fetchall())

rebuild()
show("第一次跑管線")

# 做法 3：直接下 SQL 改倉儲
con.execute("UPDATE fact SET amount = 200 WHERE order_id = 'ORD002'")
show("直接 UPDATE fact 之後")

rebuild()
show("重跑管線之後（直接改的被蓋回去）")

# 做法 1：改源頭（上游送更正），再重跑
con.execute("UPDATE src SET amount = 200 WHERE order_id = 'ORD002'")
rebuild()
show("改來源再重跑之後")

rebuild()
show("再重跑一次（結果不變）")
```

實際輸出：
```
== 第一次跑管線
[('ORD001', 100), ('ORD002', 2000)]
== 直接 UPDATE fact 之後
[('ORD001', 100), ('ORD002', 200)]
== 重跑管線之後（直接改的被蓋回去）
[('ORD001', 100), ('ORD002', 2000)]
== 改來源再重跑之後
[('ORD001', 100), ('ORD002', 200)]
== 再重跑一次（結果不變）
[('ORD001', 100), ('ORD002', 200)]
```

## 常見的坑
- **直接改完忘了補源頭**：表面上修好了，等下一次 backfill 或重建，錯誤又跑回來，而且沒人知道為什麼。
- **重跑的前提是冪等**：同一批跑兩次結果要相同，才敢放心重跑。本專案用 MERGE 條件、批次紀錄與 time travel 比對基準來保證（ADR-05）。
- **來源檔不能被偷改**：要修正就送新的一批，或用 `--force` 明確重跑並留下紀錄；否則同一個檔跑兩次結果不同，也看不出原因（process-log「checksum 涵蓋參考資料」）。
- **舊版本有保存期限**：本專案重跑舊批次時要讀 Delta 的舊版本，`VACUUM` 之後就無法重跑（見 [[delta-time-travel]]）。

## 本專案出處
- 使用者問：「在oltp中如果有資料錯誤可以下sql改資料 那在de中怎麼去修正 重跑一次？」
- 做法 1：增量批次的 MERGE 只在 `s.updated_at > t.updated_at` 時覆寫（`fact_order.py`）。
- 做法 2：`python -m pipeline.run` 的 `--force`、`batch_log.py` 的 `run_once`。
- 做法 3：Delta 支援 `UPDATE`、`DELETE`，本專案沒有使用。

## 官方文件
未證實：本筆記依 AI 既有知識整理，範例以上方實跑確認行為；沒有在這次打開官方文件核對。相關主題可查 Delta Lake 文件的 "Table deletes, updates, and merges"。

## 相關
- [[merge-idempotent-write]]
- [[delta-time-travel]]
