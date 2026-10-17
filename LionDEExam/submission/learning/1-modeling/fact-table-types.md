# 事實表的三種型態：交易事件、定期快照、累積快照
Kimball 把事實表分成三種基本形狀，差在**一列代表什麼（粒度）**和**寫進去之後還會不會改**；同一個業務流程可以存成任何一種，選哪種取決於你要回答什麼問題。

## 白話版
拿一張會變狀態的訂單（created → paid → completed，或 created → cancelled）來看：

| 型態 | 一列代表 | 怎麼更新 | Python 類比 |
|---|---|---|---|
| 交易事件（transaction） | 一個事件：「O1 在 07-01 10:05 付款」 | 只新增 | `events.append(e)`，像 log |
| 定期快照（periodic snapshot） | 一個時段結束時的狀態：「07-02 結束時 O1 是 paid」 | 每期新增一整批，不改舊期 | 每天 `snapshots[day] = copy(state)` |
| 累積快照（accumulating snapshot） | 一個流程實例的一生：「O1 何時建立、何時付款、何時完成」 | **原地更新**同一列，填上新里程碑 | `orders["O1"].paid_ts = ...`，像 dict 覆寫 |

度量能不能加總（[star-schema.md](star-schema.md)「度量」）也跟著型態走：
- **交易事件**：度量要跟事件的粒度一致才能加總。訂單金額放在每個狀態事件上，`SUM` 就會重複算（見範例的坑）。
- **定期快照**：度量常是「當時的狀態量」（餘額、未結訂單金額），跨會員可加總、**跨時間不能加總**（semi-additive）。
- **累積快照**：一張單一列，金額可直接加總；里程碑之間的時間差（付款花了幾小時）是這種表的招牌度量。

## 什麼時候用、什麼時候不要用
- **交易事件**：要問「發生了幾次、何時發生」「狀態怎麼轉移」「重算任一時點」。最細、最不會遺失資訊，其他兩種都能從它算出來。**不要**直接拿它回答「目前有多少張單是 paid」，要先取每張單最新一筆。
- **定期快照**：要問「每天／每月底的水位」（未結訂單數、庫存、餘額）、做趨勢圖。**不要**用在事件稀疏且只在乎事件本身時，每期都存一份會很佔空間。
- **累積快照**：流程有**明確、固定的里程碑**，要問「卡在哪一關」「各階段耗時」。**不要**用在里程碑不固定、會來回跳的流程（例如 paid → cancelled → paid），一列裝不下來回。也因為會 UPDATE，它最不適合只能 append 的儲存，且舊狀態會被覆蓋。

**本專案 Part A 要決定 fact 的粒度，這三種是候選形狀**；選哪一種由使用者依要回答的問題決定，本筆記不替它下結論。

## 最小可跑範例
存成 `/tmp/fact_types.py`，在 `LionTest/` 執行 `uv run python -I /tmp/fact_types.py`（DuckDB 1.5.6）：

```python
import duckdb
con = duckdb.connect()
# 原料：O1 走完 created -> paid -> completed，O2 created -> cancelled
con.sql("""CREATE TABLE events AS SELECT * FROM (VALUES
 ('O1','created',  TIMESTAMP '2026-07-01 10:00', 3000),
 ('O1','paid',     TIMESTAMP '2026-07-01 10:05', 3000),
 ('O1','completed',TIMESTAMP '2026-07-03 09:00', 3000),
 ('O2','created',  TIMESTAMP '2026-07-02 11:00', 500),
 ('O2','cancelled',TIMESTAMP '2026-07-02 18:00', 500)
) t(order_id, status, event_ts, amount)""")
def show(title, q):
    print(title)
    for r in con.sql(q).fetchall():
        print("  ", r)

show("1. 交易事件：一列一個狀態事件（只新增）",
     "SELECT order_id, status, strftime(event_ts, '%m-%d %H:%M'), amount FROM events ORDER BY order_id, event_ts")

# 定期快照：每天結束時，每張已存在的單一列（每天 INSERT 一批，舊的不改）
con.sql("""CREATE TABLE fact_daily AS
WITH days AS (SELECT d::DATE AS snap_date FROM range(DATE '2026-07-01', DATE '2026-07-04', INTERVAL 1 DAY) r(d))
SELECT d.snap_date, e.order_id, arg_max(e.status, e.event_ts) AS status_eod, any_value(e.amount) AS amount
FROM days d JOIN events e ON e.event_ts < d.snap_date + INTERVAL 1 DAY
GROUP BY ALL""")
show("2. 定期快照：一列 = 一張單在某天結束時的狀態",
     "SELECT strftime(snap_date, '%m-%d'), order_id, status_eod, amount FROM fact_daily ORDER BY 1, 2")

# 累積快照：一張單一列、每個里程碑一欄，狀態推進時 UPDATE 同一列
con.sql("""CREATE TABLE fact_acc (order_id VARCHAR PRIMARY KEY, amount INT,
  created_ts TIMESTAMP, paid_ts TIMESTAMP, completed_ts TIMESTAMP, cancelled_ts TIMESTAMP)""")
for oid, st, ts, amt in con.sql("SELECT * FROM events ORDER BY event_ts").fetchall():
    if st == 'created':
        con.execute("INSERT INTO fact_acc (order_id, amount, created_ts) VALUES (?, ?, ?)", [oid, amt, ts])
    else:
        con.execute(f"UPDATE fact_acc SET {st}_ts = ? WHERE order_id = ?", [ts, oid])
show("3. 累積快照：(order_id, amount, created, paid, completed, cancelled, hrs_to_complete)",
     """SELECT order_id, amount, strftime(created_ts, '%m-%d %H:%M'), strftime(paid_ts, '%m-%d %H:%M'),
        strftime(completed_ts, '%m-%d %H:%M'), strftime(cancelled_ts, '%m-%d %H:%M'),
        date_diff('hour', created_ts, completed_ts) FROM fact_acc ORDER BY order_id""")

show("坑：直接 SUM(amount)，(交易事件全部, 只取 created, 定期快照跨日, 定期快照 07-03 未取消, 累積快照未取消)",
     """SELECT (SELECT sum(amount) FROM events),
        (SELECT sum(amount) FROM events WHERE status = 'created'),
        (SELECT sum(amount) FROM fact_daily),
        (SELECT sum(amount) FROM fact_daily WHERE snap_date = DATE '2026-07-03' AND status_eod <> 'cancelled'),
        (SELECT sum(amount) FROM fact_acc WHERE cancelled_ts IS NULL)""")
```

實際輸出（2026-10-17 本機執行）：

```
1. 交易事件：一列一個狀態事件（只新增）
   ('O1', 'created', '07-01 10:00', 3000)
   ('O1', 'paid', '07-01 10:05', 3000)
   ('O1', 'completed', '07-03 09:00', 3000)
   ('O2', 'created', '07-02 11:00', 500)
   ('O2', 'cancelled', '07-02 18:00', 500)
2. 定期快照：一列 = 一張單在某天結束時的狀態
   ('07-01', 'O1', 'paid', 3000)
   ('07-02', 'O1', 'paid', 3000)
   ('07-02', 'O2', 'cancelled', 500)
   ('07-03', 'O1', 'completed', 3000)
   ('07-03', 'O2', 'cancelled', 500)
3. 累積快照：(order_id, amount, created, paid, completed, cancelled, hrs_to_complete)
   ('O1', 3000, '07-01 10:00', '07-01 10:05', '07-03 09:00', None, 47)
   ('O2', 500, '07-02 11:00', None, None, '07-02 18:00', None)
坑：直接 SUM(amount)，(交易事件全部, 只取 created, 定期快照跨日, 定期快照 07-03 未取消, 累積快照未取消)
   (10000, 3500, 10000, 3000, 3000)
```

同一份原料，三種形狀：交易事件一列一事件、定期快照一列一「單×天」（O2 07-02 才出現）、累積快照一列一單。最後一行：交易事件全部加總把 O1 的 3,000 算了三次（10000）；只取 `created` 事件才是下單金額（3500）；定期快照跨日加總也是 10000，同樣沒意義，只能看單一天（3000）；累積快照一張單一列，可直接加總（3000）。

## 常見的坑
- **粒度混用**：同一張 fact 裡有的列是「一張單」、有的列是「一個事件」，`SUM`、`COUNT` 全錯。先寫下「一列代表什麼」再建表（[star-schema.md](star-schema.md)「粒度」）。
- **度量掛錯粒度**：訂單金額掛在每個狀態事件上，加總會重複；要嘛只在 `created` 事件放金額，要嘛只用累積快照加總。
- **定期快照跨時間加總**：把每天的未結金額加起來沒有意義（上例定期快照跨日加總得 10000）。
- **累積快照被當成歷史**：它只留每個里程碑「最後一次」的時間；狀態來回跳（paid → cancelled → paid）時，前面的轉移會被覆蓋，要歷史就保留交易事件表。
- **累積快照的 UPDATE 也要冪等**：以業務生效時間為準時，晚到的舊事件（見 [time-varying-attributes.md](time-varying-attributes.md)「兩種時間」）不能蓋掉較新的里程碑。

## 本專案出處
- 官方 README：「增量檔中同一 order_id 可能出現多次（狀態更新事件），以 updated_at 區分新舊」，原料本身就是交易事件形狀；彙整見 `part_a/source-schema-inference.md`「支持 `order_id`（一張單一列，增量為狀態更新）」。
- `part_a/source-schema-inference.md` L4：day1 cancelled、day2 paid 的 25 個 id：照到達順序與照 `updated_at` 更新會得到相反的最終狀態，以哪個為準見 J6（待使用者決定）。

## 官方文件
- Kimball Group（已讀）：[Transaction Fact Tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/transaction-fact-table/)：一列是「某時某地的一個量測事件」，只在有事件時才有列。
- Kimball Group（已讀）：[Periodic Snapshot Fact Tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/periodic-snapshot-fact-table/)：「粒度是期間，不是個別交易」；沒有活動的期間也常插一列，度量填 0 或 null。
- Kimball Group（已讀）：[Accumulating Snapshot Fact Tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/accumulating-snapshot-fact-table/)：每個關鍵里程碑一個日期外鍵；流程推進時「回頭更新」同一列，這是它和另兩種的分野；常帶 lag 度量與里程碑計數。
- Kimball Group（已讀）：[Additive, Semi-Additive, Non-Additive Facts](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/additive-semi-additive-non-additive-fact/)：餘額是 semi-additive 的典型例子，除了時間以外都能加總。
- 未證實：「累積快照不適合會來回跳的流程」「累積快照的 UPDATE 要防晚到事件」是依其「每里程碑一欄、原地更新」的定義推得，Kimball 頁面未明寫。
