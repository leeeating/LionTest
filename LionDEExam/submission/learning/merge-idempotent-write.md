# SQL：用 MERGE 做冪等寫入（upsert）
**append 是「再加一列」，MERGE 是「依 key 更新或新增」；重跑 append 會翻倍，重跑 MERGE 結果不變。**

## 白話版
- append 像 `list.append(row)`：呼叫兩次就有兩份。
- MERGE 像 `d[key] = value`：key 已存在就覆蓋，不存在就新增，呼叫幾次結果都一樣（冪等，idempotent）。
- 差別在於「有沒有業務 key」：MERGE 必須用 key（如 `order_id`）判斷「這列是不是已經有了」。

## 什麼時候用、什麼時候不要用
- **用**：資料管線要能安全重跑、來源會更新既有列（訂單狀態變更）、事實表 / 維度表的每日增量。
- **不要用**：純事件 log（每筆都是新事實，沒有「更新」）；沒有可靠唯一 key 的資料（MERGE 會誤合併，要先釐清 key）。

## 最小可跑範例
環境：duckdb 1.5.6，**本版支援 `MERGE INTO`**。同一批資料各寫兩次，MERGE 加上 `updated_at` 判斷新舊：

```python
import duckdb
c = duckdb.connect()
c.execute("create table app(order_id varchar, amount int, updated_at int)")
c.execute("create table mrg(order_id varchar primary key, amount int, updated_at int)")
MERGE = """merge into mrg using (select * from {b}) s on mrg.order_id = s.order_id
  when matched and s.updated_at > mrg.updated_at
    then update set amount = s.amount, updated_at = s.updated_at
  when not matched then insert values (s.order_id, s.amount, s.updated_at)"""
batch = "(values ('A',100,1),('B',200,1)) t(order_id,amount,updated_at)"
for _ in range(2):
    c.execute(f"insert into app select * from {batch}")   # append
    c.execute(MERGE.format(b=batch))                      # merge
print("append x2:", c.sql("select order_id, count(*) n, sum(amount) s from app group by 1 order by 1").fetchall())
print("merge  x2:", c.sql("select * from mrg order by 1").fetchall())
for b in ["(values ('A',150,2)) t(order_id,amount,updated_at)",   # 新版
          "(values ('A',999,0)) t(order_id,amount,updated_at)"]:  # 晚到的舊版
    c.execute(MERGE.format(b=b))
print("after newer+stale:", c.sql("select * from mrg order by 1").fetchall())
```

實際輸出（`uv run python`）：
```
append x2: [('A', 2, 200), ('B', 2, 400)]      # 每個 key 兩列，金額翻倍
merge  x2: [('A', 100, 1), ('B', 200, 1)]      # 跟跑一次一樣
after newer+stale: [('A', 150, 2), ('B', 200, 1)]  # 先來 updated_at=2 的新版，再來 updated_at=0 的舊版：舊版被忽略
```

Delta Lake 版（pyspark 4.2＋delta-spark，已實際執行）：
```python
(DeltaTable.forPath(spark, path).alias("t").merge(df.alias("s"), "t.order_id = s.order_id")
  .whenMatchedUpdateAll(condition="s.updated_at > t.updated_at")
  .whenNotMatchedInsertAll().execute())
```
```
delta merge x2: [('A', 100, 1), ('B', 200, 1)]
dup source error: [DELTA_MULTIPLE_SOURCE_ROW_MATCHING_TARGET_ROW_IN_MERGE] Cannot perform Merge as multiple source rows matched and attempted to modify the same ...
```
（第二行是來源有 `('A',300,5)`、`('A',400,6)` 兩列同 key 時的結果。）

## 常見的坑
1. **用 append 寫事實表**：重跑同一批，該批金額翻倍；跨日的訂單更新會和舊列並存（本專案 #3）。
2. **來源同 key 有多列**：Delta MERGE 直接報錯（見上面輸出）；**DuckDB 1.5.6 實測不報錯，留下哪一列不保證**：目標 `('A',1,1)`、來源 `('A',300,5)`、`('A',400,6)`，matched 時結果是 `[('A', 300, 5)]`（留下比較舊的那列）；matched 時把來源列順序反過來（400 在前），結果變成 `[('A', 400, 6)]`，即取來源的第一列，所以留下哪列取決於來源順序；not matched 且目標表沒有 PK 時，兩列都被 insert：`[('A', 300, 5), ('A', 400, 6)]`；not matched 且目標表有 PRIMARY KEY（如上面的 `mrg`）時報 `Constraint Error: PRIMARY KEY or UNIQUE constraint violation: duplicate key "A"`。三種結果不同，都不是你要的，所以來源一律先去重。先用 `row_number() over (partition by key order by updated_at desc)` 取最新一列再 MERGE（本專案 #4 join 放大、#5 去重不確定）。`dropDuplicates` 不保證留哪一列，不能當去重。
3. **沒判斷新舊**：晚到的舊資料會蓋掉新資料。`when matched and s.updated_at > t.updated_at` 才更新（上面「newer+stale」輸出）。
4. **key 不可靠**：本專案 day1 增量與 base 的 603 列 `order_id` 相同但 `member_id`、`amount` 都不同，若它們其實是不同訂單，MERGE 會把兩張合成一張（是否為同一張，報告立場是「與官方語意不符，需向上游確認」），所以 key 要先確認。

## 本專案出處
- `part_b/code-review.md`：`write_fact` 中的 `mode("append")`（#3）；`build_fact` 中的 `converted.join(members, "member_id", "left")`（#4）；`clean_orders` 中的 `dropDuplicates(["order_id"])`（#5）；修正建議「所有寫入改成以業務 key 做 MERGE」。

## 官方文件
- DuckDB MERGE INTO（已讀）：https://duckdb.org/docs/current/sql/statements/merge_into.html 。頁面未說明來源重複 key 的行為（以上方「常見的坑」第 2 點的 1.5.6 實測為準），也未說明哪版開始支援（未證實，本篇只確認 1.5.6 可用）。
- Delta Lake merge（已讀）：https://docs.delta.io/latest/delta-update.html 。文件說明多個來源列匹配同一目標列會 ambiguous，需先對來源去重。
