# Part B 證據：查詢腳本與輸出

本檔收錄 `code-review.md`（Part B 審查報告）、`appendix.md`、`prod-recovery.md`與 `notes/` 引用的筆數、Spark 語意驗證的**查詢腳本全文與輸出原文**，閱卷者可自行重跑核對。內容從舊版協作紀錄（commit `34a4cdd` 的 `ai-collab/process-log-part-b.md` 步驟 3）原樣搬來，數字未改動；各輪驗收如何用到這些輸出，見 `../ai-collab/process-log.md`。

**執行方式**：題目要求不執行原管線（`buggy_pipeline.py`），以下只讀 `candidate_package/dataset/` 的 CSV，或用自建小資料驗證 Spark 語意。
- 純資料查詢：Python 標準庫 `csv`，以 `encoding="utf-8-sig"` 讀（dataset 是 UTF-8 BOM）。把腳本存到 dataset **以外**的目錄，用 `python3 -I <腳本> <dataset 目錄>` 執行（`-I` 是隔離模式，不從腳本目錄或目前目錄載入模組）。在 `LionDEExam/` 下 dataset 目錄是 `candidate_package/dataset`，在 `LionTest/` 下是 `LionDEExam/candidate_package/dataset`。
- pyspark 語意驗證：在 `LionTest/` 用專案 `.venv`（pyspark 4.2＋delta-spark）執行 `uv run python <腳本> ... 2>/dev/null`（Spark log 走 stderr，故丟掉）。

## 舊編號與新編號對照

報告的問題編號曾經改過：原本依嚴重度排序（#1～#12），現在依程式執行順序排序（#1～#11），SCD2 的兩個問題（舊 #2、#6）合併成新 #6。**本檔的腳本與輸出原文保留當時的舊編號**（例如輸出裡的 `[#7]`、`#5 組`），說明文字與下方索引用新編號。

| 舊編號 | 新編號 | 問題 |
|---|---|---|
| #1 | #4 | 匯率 inner join 丟掉 TWD |
| #2 | #6 | SCD2 寫入清表（與舊 #6 合併） |
| #3 | #9 | append 重複、跨日更新 |
| #4 | #7 | 一對多 join 放大 |
| #5 | #2 | 去重保留任意一筆 |
| #6 | #6 | SCD2 邏輯不完整（與舊 #2 合併） |
| #7 | #3 | 非正數金額過濾 |
| #8 | #8 | 產品 inner join 丟單 |
| #9 | #10 | 驗證沒有斷言、collect 到 driver |
| #10 | #11 | 執行順序與失敗處理 |
| #11 | #5 | Python UDF 做乘法 |
| #12 | #1 | CSV 不指定 schema、隱式轉型 |

## 問題編號索引

| 報告問題（新編號，`code-review.md`「問題總表」） | 證據（反引號內是腳本輸出的標籤，為舊編號） |
|---|---|
| #1 CSV 不指定 schema、隱式轉型 | E3 `[#12]`；E5 `[3]`；E6 |
| #2 去重保留任意一筆 | E1 `[#5]`；E2 `#5 組`；E5 `[1]` |
| #3 非正數金額過濾 | E1 `[#7]` |
| #4 匯率 inner join 丟掉 TWD | E1 `[#1]` |
| #6 SCD2 實作錯誤（replaceWhere 清表、屬性變化、同分、初始載入） | E1 `[#6]`；E2 `[#2]`；E3 `[#6]`；E4；E5 `[2]`；E7 |
| #7 一對多 join 放大 | E1 `[#4]`；E2 `[#4]`；E7 |
| #9 append 重複、跨日更新 | E1 `[#3]`；E2 `[#3]`、`#5 組`；E3 `[#3]` |
| `appendix.md`「靜態分析（ruff、mypy）」 | E8 |
| `notes/dataset/` 資料字典、增量檔觀察 | E9 |
| #9（各增量檔與 base 重疊）、#1（金額例子） | E11 |
| `prod-recovery.md`（prod 資料怎麼復原） | E10（引用 [2]、[3]；其餘情境為修正後 MERGE 的行為驗證） |
| #9、5.1（MERGE 來源同 key 多列）、#1（`enforceSchema`）、#4（換算乘法的型別） | E12 |

## E1｜主要數字重算（#2～#4、#6、#7、#9）

第一輪驗收修正時重寫的重算腳本，涵蓋報告 #2～#4、#6、#7、#9 的主要數字（輸出標籤為舊編號，見文首對照表）。dataset 是 UTF-8 BOM，用 `encoding="utf-8-sig"` 讀；腳本放在 dataset 以外的目錄，以 `python3 -I partb_queries.py candidate_package/dataset` 執行。

```python
"""重算 Part B 審查報告（code-review.md）的主要數字。用法：python3 -I partb_queries.py <dataset 目錄>"""
import csv, sys
from collections import Counter, defaultdict

D = sys.argv[1]
def load(name):
    with open(f"{D}/{name}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

fx, mem, base = load("fx_rates"), load("members"), load("orders_base")
d1, d2 = load("orders_incremental_day1"), load("orders_incremental_day2")

# #1 匯率 inner join
fx_cur = sorted({r["currency"] for r in fx})
twd = sum(r["currency"] == "TWD" for r in d1)
no_fx = sum(r["currency"] not in fx_cur for r in d1)
print(f"[#1] fx 幣別={fx_cur}; day1 列數={len(d1)}, TWD={twd}, 對不到匯率={no_fx}")

# #3 增量檔裡的既有訂單
base_status = defaultdict(set)
for r in base:
    base_status[r["order_id"]].add(r["order_status"])
in_base_rows = [r for r in d1 if r["order_id"] in base_status]
in_base_ids = {r["order_id"] for r in in_base_rows}
changed_rows = [r for r in in_base_rows if r["order_status"] not in base_status[r["order_id"]]]
print(f"[#3] day1 已存在於 base：{len(in_base_ids)} 個 order_id、{len(in_base_rows)} 列；"
      f"狀態與 base 不同的列={len(changed_rows)}（涉及 {len({r['order_id'] for r in changed_rows})} 個 order_id）")
d1_ids = {r["order_id"] for r in d1}
print(f"[#3] day2 order_id 在 day1 出現過：{len({r['order_id'] for r in d2} & d1_ids)} 個")

# #4 members 多快照、一對多 join
snaps = defaultdict(list)
for r in mem:
    snaps[r["member_id"]].append(r)
multi = {m for m, v in snaps.items() if len(v) > 1}
print(f"[#4] members 列數={len(mem)}, 會員數={len(snaps)}, 多快照會員={len(multi)}, "
      f"快照數分布={dict(Counter(len(v) for v in snaps.values()))}")
d1_multi = [r for r in d1 if r["member_id"] in multi]
extra = sum(len(snaps[r["member_id"]]) - 1 for r in d1 if r["member_id"] in snaps)
print(f"[#4] day1 屬於多快照會員的訂單={len(d1_multi)}, join 後多出 {extra} 列")

# #5 day1 同 order_id 重複
grp = defaultdict(list)
for r in d1:
    grp[r["order_id"]].append(r)
dups = {k: v for k, v in grp.items() if len(v) > 1}
upd_all_diff = sum(len({r["updated_at"] for r in v}) == len(v) for v in dups.values())
KEY = ("order_created_at", "member_id", "amount")
collide = {k: v for k, v in dups.items() if len({tuple(r[c] for c in KEY) for r in v}) > 1}
normal = {k: v for k, v in dups.items() if k not in collide}
print(f"[#5] day1 重複 order_id={len(dups)}, updated_at 全不同={upd_all_diff}, "
      f"撞號（{'/'.join(KEY)} 不同）={len(collide)}, 正常重複={len(normal)}")
for k, v in sorted(collide.items()):
    print("   撞號", k, [(r["order_created_at"], r["member_id"], r["amount"], r["order_status"]) for r in v])
for k, v in sorted(normal.items()):
    v = sorted(v, key=lambda r: r["updated_at"])
    diff_cols = [c for c in v[0] if len({r[c] for r in v}) > 1]
    print("   正常", k, "不同欄位=", diff_cols, [(r["updated_at"], r["order_status"]) for r in v])

# #6 會員屬性變化
lvl = sum(len({r["member_level"] for r in snaps[m]}) > 1 for m in multi)
city = sum(len({r["city"] for r in snaps[m]}) > 1 for m in multi)
print(f"[#6] 多快照會員中 member_level 變過={lvl}, city 變過={city}")
md = defaultdict(list)
for r in mem:
    md[(r["member_id"], r["extract_date"])].append(r)
mdup = {k: v for k, v in md.items() if len(v) > 1}
latest = {m: max(r["extract_date"] for r in v) for m, v in snaps.items()}
at_latest = [k for k in mdup if k[1] == latest[k[0]]]
attr_diff = [k for k in at_latest
             if len({r["member_level"] for r in mdup[k]}) > 1 or len({r["city"] for r in mdup[k]}) > 1]
lvl_diff = sum(len({r["member_level"] for r in mdup[k]}) > 1 for k in at_latest)
city_diff = sum(len({r["city"] for r in mdup[k]}) > 1 for k in at_latest)
print(f"[#6] (member_id, extract_date) 重複={len(mdup)}（每組列數 {dict(Counter(len(v) for v in mdup.values()))}）, "
      f"落在該會員最新 extract_date={len(at_latest)}, 其中 level 或 city 不同={len(attr_diff)}"
      f"（level 不同 {lvl_diff}、city 不同 {city_diff}）")
ex = sorted(at_latest)[0]
print("   例", ex, [(r["member_level"], r["city"]) for r in mdup[ex]])
print(f"[#6] city 空字串={sum(r['city'].strip() == '' for r in mem)}, city='N/A'={sum(r['city'] == 'N/A' for r in mem)}")

# #7 非正數金額
for name, rows in [("base", base), ("day1", d1), ("day2", d2), ("day3", load("orders_incremental_day3"))]:
    print(f"[#7] {name} amount<=0：{sum(float(r['amount']) <= 0 for r in rows)}")
```

輸出（2026-10-10 執行）：

```
[#1] fx 幣別=['JPY', 'USD']; day1 列數=4615, TWD=3069, 對不到匯率=3069
[#3] day1 已存在於 base：597 個 order_id、603 列；狀態與 base 不同的列=485（涉及 480 個 order_id）
[#3] day2 order_id 在 day1 出現過：25 個
[#4] members 列數=8991, 會員數=8000, 多快照會員=989, 快照數分布={2: 987, 1: 7011, 3: 2}
[#4] day1 屬於多快照會員的訂單=570, join 後多出 571 列
[#5] day1 重複 order_id=18, updated_at 全不同=18, 撞號（order_created_at/member_id/amount 不同）=3, 正常重複=15
   撞號 ORD00036457 [('2026-05-26T04:27:52+08:00', 'M002150', '200659.0', 'completed'), ('2026-06-21T16:53:45+08:00', 'M000272', '18042.46', 'cancelled')]
   撞號 ORD00047034 [('2026-05-29T06:52:52+08:00', 'M003354', '118403.0', 'completed'), ('2026-06-28T18:18:05+08:00', 'M003348', '281690.0', 'completed')]
   撞號 ORD00076774 [('2026-06-20T02:11:50+08:00', 'M002915', '568351.0', 'completed'), ('2026-06-07T11:39:56+08:00', 'M002166', '5861.06', 'completed')]
   正常 ORD00005192 不同欄位= ['updated_at'] [('2026-07-01T22:37:32+08:00', 'completed'), ('2026-07-01T22:37:58+08:00', 'completed')]
   正常 ORD00037592 不同欄位= ['updated_at'] [('2026-07-01T20:57:01+08:00', 'cancelled'), ('2026-07-01T20:57:12+08:00', 'cancelled')]
   正常 ORD00072464 不同欄位= ['updated_at'] [('2026-07-01T01:41:09+08:00', 'completed'), ('2026-07-01T01:41:22+08:00', 'completed')]
   正常 ORD00100190 不同欄位= ['updated_at'] [('2026-07-03T19:02:31+08:00', 'created'), ('2026-07-03T19:02:36+08:00', 'created')]
   正常 ORD00100599 不同欄位= ['updated_at'] [('2026-07-02T20:51:03+08:00', 'paid'), ('2026-07-02T20:51:09+08:00', 'paid')]
   正常 ORD00100719 不同欄位= ['updated_at'] [('2026-07-01T07:35:33+08:00', 'created'), ('2026-07-01T07:35:39+08:00', 'created')]
   正常 ORD00101036 不同欄位= ['updated_at'] [('2026-07-02T10:40:38+08:00', 'paid'), ('2026-07-02T10:40:43+08:00', 'paid')]
   正常 ORD00101153 不同欄位= ['updated_at'] [('2026-07-02T02:20:17+08:00', 'paid'), ('2026-07-02T02:20:38+08:00', 'paid')]
   正常 ORD00101789 不同欄位= ['updated_at'] [('2026-07-02T21:59:06+08:00', 'created'), ('2026-07-02T21:59:09+08:00', 'created')]
   正常 ORD00101955 不同欄位= ['updated_at'] [('2026-07-03T17:40:07+08:00', 'paid'), ('2026-07-03T17:40:36+08:00', 'paid')]
   正常 ORD00102084 不同欄位= ['updated_at'] [('2026-07-01T08:33:37+08:00', 'created'), ('2026-07-01T08:33:42+08:00', 'created')]
   正常 ORD00102367 不同欄位= ['updated_at'] [('2026-07-01T23:32:03+08:00', 'paid'), ('2026-07-01T23:32:21+08:00', 'paid')]
   正常 ORD00102395 不同欄位= ['updated_at'] [('2026-07-01T20:45:14+08:00', 'paid'), ('2026-07-01T20:45:20+08:00', 'paid')]
   正常 ORD00102998 不同欄位= ['updated_at'] [('2026-07-03T09:25:04+08:00', 'paid'), ('2026-07-03T09:25:06+08:00', 'paid')]
   正常 ORD00103229 不同欄位= ['updated_at'] [('2026-07-03T10:42:29+08:00', 'paid'), ('2026-07-03T10:42:48+08:00', 'paid')]
[#6] 多快照會員中 member_level 變過=434, city 變過=376
[#6] (member_id, extract_date) 重複=30（每組列數 {2: 30}）, 落在該會員最新 extract_date=28, 其中 level 或 city 不同=28（level 不同 28、city 不同 0）
   例 ('M000096', '2026-04-30') [('金卡', '台北市'), ('銀卡', '台北市')]
[#6] city 空字串=0, city='N/A'=71
[#7] base amount<=0：50
[#7] day1 amount<=0：0
[#7] day2 amount<=0：0
[#7] day3 amount<=0：0
```

上面輸出的「撞號」是腳本當時的標籤，第二輪驗收後已改為「與官方語意不符的現象，需向上游確認」，數字不變。

## E2｜第二輪驗收重算（#2、#6、#7、#9）

重算 #6、#7、#9 的新數字，並查 #9 的 603 列與 base 的三欄比對。以 `python3 -I recheck.py candidate_package/dataset` 執行。

```python
"""第二輪驗收重算：#3 三欄比對、#4 現行管線順序下的放大列數、#2 同分會員。用法：python3 -I recheck.py <dataset 目錄>"""
import csv, sys
from collections import Counter, defaultdict
D = sys.argv[1]
def load(n):
    with open(f"{D}/{n}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
fx, mem, base, d1 = load("fx_rates"), load("members"), load("orders_base"), load("orders_incremental_day1")
KEY = ("order_created_at", "member_id", "amount")
b = defaultdict(list)
for r in base: b[r["order_id"]].append(r)
rows = [r for r in d1 if r["order_id"] in b]
all3 = sum(any(all(r[c] == x[c] for c in KEY) for x in b[r["order_id"]]) for r in rows)
any1 = {c: sum(any(r[c] == x[c] for x in b[r["order_id"]]) for r in rows) for c in KEY}
print(f"[#3] day1 在 base 的列={len(rows)}; 三欄全同={all3}; 單欄相同列數={any1}")
same_part = sum(any(r["order_created_at"][:10] == x["order_created_at"][:10] for x in b[r["order_id"]]) for r in rows)
print(f"[#3] order_created_at 前 10 碼（order_date）與 base 相同的列={same_part}")
ex = "ORD00005192"
print("   例 base", [(x["order_created_at"], x["member_id"], x["amount"], x["order_status"]) for x in b[ex]])
print("   例 day1", [(r["order_created_at"], r["member_id"], r["amount"], r["order_status"]) for r in d1 if r["order_id"] == ex])
# #5 撞號 3 組是否也在 base
for k in ("ORD00036457", "ORD00047034", "ORD00076774"):
    print("   #5 組", k, "在 base:", k in b)
# #4 現行管線順序：dropDuplicates(任一列) -> amount>0 -> fx inner join(currency+order_date) -> members left join
snaps = Counter(r["member_id"] for r in mem)
fxkey = {(r["currency"], r["rate_date"]) for r in fx}
g = defaultdict(list)
for r in d1: g[r["order_id"]].append(r)
# 18 組重複各留哪一列不確定，取上下界
dk = [k for k, v in g.items() if len(v) > 1]
single = [v[0] for k, v in g.items() if len(v) == 1]
def ok(r): return float(r["amount"]) > 0 and (r["currency"], r["order_created_at"][:10]) in fxkey
base_rows = [r for r in single if ok(r)]
base_extra = sum(snaps[r["member_id"]] - 1 for r in base_rows)
opts = []
for k in dk:
    opts.append([(int(ok(r)), snaps[r["member_id"]] - 1 if ok(r) else 0) for r in g[k]])
n_lo = len(base_rows) + sum(min(k for k, _ in o) for o in opts); n_hi = len(base_rows) + sum(max(k for k, _ in o) for o in opts)
e_lo = base_extra + sum(min(e for _, e in o) for o in opts); e_hi = base_extra + sum(max(e for _, e in o) for o in opts)
print(f"[#4] 現行順序（dropDuplicates 任留一列 → amount>0 → 匯率 inner join）：進入 members join 的列={n_lo}~{n_hi}，join 後多出 {e_lo}~{e_hi} 列")
print(f"[#4] 原始增量（不去重、不丟 TWD）多出 {sum(snaps[r['member_id']] - 1 for r in d1)}")
# #2 同分會員
md = defaultdict(list)
for r in mem: md[(r["member_id"], r["extract_date"])].append(r)
latest = defaultdict(str)
for r in mem: latest[r["member_id"]] = max(latest[r["member_id"]], r["extract_date"])
tie = [k for k, v in md.items() if len(v) > 1 and k[1] == latest[k[0]]]
print(f"[#2] 最新 extract_date 同分會員={len(tie)}")
# #4 假設 #1、#5 已修（TWD 保留、每個 order_id 留 updated_at 最新一列）
lat = [max(v, key=lambda r: r["updated_at"]) for v in g.values()]
print(f"[#4] #1、#5 已修：進入 members join 的列={len(lat)}，join 後多出 {sum(snaps[r['member_id']] - 1 for r in lat)} 列")
```

輸出（2026-10-10 執行）：

```
[#3] day1 在 base 的列=603; 三欄全同=0; 單欄相同列數={'order_created_at': 0, 'member_id': 0, 'amount': 0}
[#3] order_created_at 前 10 碼（order_date）與 base 相同的列=9
   例 base [('2026-05-06T19:07:47+08:00', 'M007765', '10230.87', 'paid')]
   例 day1 [('2026-05-04T08:52:43+08:00', 'M005173', '6927.0', 'completed'), ('2026-05-04T08:52:43+08:00', 'M005173', '6927.0', 'completed')]
   #5 組 ORD00036457 在 base: True
   #5 組 ORD00047034 在 base: True
   #5 組 ORD00076774 在 base: True
[#4] 現行順序（dropDuplicates 任留一列 → amount>0 → 匯率 inner join）：進入 members join 的列=1536~1538，join 後多出 182~183 列
[#4] 原始增量（不去重、不丟 TWD）多出 571
[#2] 最新 extract_date 同分會員=28
[#4] #1、#5 已修：進入 members join 的列=4597，join 後多出 569 列
```

## E3｜第三輪驗收重算（#6 初始載入、#1 金額最小值、#9 order_date 範圍）

腳本放在 dataset 以外的暫存目錄（`/tmp/partb_r3/`），2026-10-10 執行。

執行：`python3 -I recheck3.py candidate_package/dataset`

```python
"""第三輪驗收重算：#6 初始載入（只用最新快照時丟失的歷史）、#12 金額最小值、#3 day1 order_date 範圍。
用法：python3 -I recheck3.py <dataset 目錄>"""
import csv, sys
from collections import Counter, defaultdict
D = sys.argv[1]
def load(n):
    with open(f"{D}/{n}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
mem = load("members")
inc = {d: load(f"orders_incremental_{d}") for d in ("day1", "day2", "day3")}
d1 = inc["day1"]
print("[#6] members extract_date 分布:", dict(sorted(Counter(r["extract_date"] for r in mem).items())))
latest = defaultdict(str); earliest = {}
for r in mem:
    m = r["member_id"]; latest[m] = max(latest[m], r["extract_date"])
    earliest[m] = min(earliest.get(m, "9999"), r["extract_date"])
reg = {r["member_id"]: r["register_date"] for r in mem}
# #1、#5 已修：每個 order_id 留 updated_at 最新一列
g = defaultdict(list)
for r in d1: g[r["order_id"]].append(r)
lat = [max(v, key=lambda r: r["updated_at"]) for v in g.values()]
od = lambda r: r["order_created_at"][:10]
early = [r for r in lat if r["member_id"] in latest and od(r) < latest[r["member_id"]]]
print(f"[#6] day1 去重後={len(lat)}；order_date 早於該會員最新 extract_date={len(early)}"
      f"（涉及 {len({r['member_id'] for r in early})} 位會員）")
print("   order_date 分布:", dict(sorted(Counter(od(r) for r in early).items())),
      " 會員最新 extract_date 分布:", dict(Counter(latest[r['member_id']] for r in early)))
early2 = [r for r in lat if r["member_id"] in earliest and od(r) < earliest[r["member_id"]]]
print(f"[#6] 逐批回填全部快照、第一版 valid_from=最早 extract_date：仍對不到={len(early2)}")
nomem = sum(r["member_id"] not in latest for r in lat)
print(f"[#6] day1 去重後 member_id 不在 members={nomem}")
print(f"[#6] register_date 晚於最早 extract_date 的會員={sum(reg[m] > earliest[m] for m in earliest)}")
early3 = [r for r in lat if r["member_id"] in reg and od(r) < reg[r["member_id"]]]
print(f"[#6] 第一版 valid_from=register_date：order_date 早於 register_date 的訂單={len(early3)}")
print(f"[#6] register_date 範圍={min(reg.values())}~{max(reg.values())}")
# #12 增量金額最小值
for d, rows in inc.items():
    print(f"[#12] {d} amount 最小值={min(float(r['amount']) for r in rows)}；非純數字={sum(not r['amount'].replace('.','',1).isdigit() for r in rows)}")
# #3 day1 order_date 範圍
ods = [od(r) for r in d1]
print(f"[#3] day1 order_created_at 日期範圍={min(ods)}~{max(ods)}，相異 order_date 數={len(set(ods))}")
```

輸出（order_date 分布中段省略）：

```
[#6] members extract_date 分布: {'2026-04-30': 8030, '2026-05-31': 459, '2026-06-30': 502}
[#6] day1 去重後=4597；order_date 早於該會員最新 extract_date=49（涉及 48 位會員）
   order_date 分布: {'2026-05-01': 1, '2026-05-02': 1, '2026-05-06': 3, ...（略，最晚 '2026-06-28': 2）}  會員最新 extract_date 分布: {'2026-06-30': 33, '2026-05-31': 16}
[#6] 逐批回填全部快照、第一版 valid_from=最早 extract_date：仍對不到=0
[#6] day1 去重後 member_id 不在 members=0
[#6] register_date 晚於最早 extract_date 的會員=0
[#6] 第一版 valid_from=register_date：order_date 早於 register_date 的訂單=0
[#6] register_date 範圍=2015-01-01~2025-12-13
[#12] day1 amount 最小值=94.17；非純數字=0
[#12] day2 amount 最小值=86.4；非純數字=0
[#12] day3 amount 最小值=83.24；非純數字=0
[#3] day1 order_created_at 日期範圍=2026-05-01~2026-07-01，相異 order_date 數=62
```

## E4｜orders_base 與第一版 valid_from 的比較（#6）

執行：`python3 -I base_check.py candidate_package/dataset`

```python
"""orders_base 的 order_created_at 前 10 碼（管線 order_date 的衍生方式）與 members 最早 extract_date、register_date 的比較。用法：python3 -I base_check.py <dataset 目錄>"""
import csv, sys
D = sys.argv[1]
def load(n):
    with open(f"{D}/{n}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
mem, base = load("members"), load("orders_base")
earliest, reg = {}, {}
for r in mem:
    m = r["member_id"]; earliest[m] = min(earliest.get(m, "9999"), r["extract_date"]); reg[m] = r["register_date"]
iso = [r for r in base if r["order_created_at"][4] == "-"]
od = lambda r: r["order_created_at"][:10]
print(f"[#6] base 列={len(base)}，ISO 日期格式={len(iso)}，order_date 範圍={min(map(od, iso))}~{max(map(od, iso))}")
known = [r for r in iso if r["member_id"] in earliest]
print(f"[#6] base（ISO）order_date 早於會員最早 extract_date={sum(od(r) < earliest[r['member_id']] for r in known)} / {len(known)}")
print(f"[#6] base（ISO）order_date 早於會員 register_date={sum(od(r) < reg[r['member_id']] for r in known)}")
```

```
[#6] base 列=100040，ISO 日期格式=97039，order_date 範圍=2026-04-30~2026-06-30
[#6] base（ISO）order_date 早於會員最早 extract_date=0 / 97039
[#6] base（ISO）order_date 早於會員 register_date=0
```

## E5｜pyspark 語意驗證：#2 dropDuplicates＋window、#6 replaceWhere 清表、#1 隱式轉型的 explain

原管線不執行，pyspark 只跑自建小資料。

執行：在 `LionTest/` 執行 `uv run python /tmp/partb_r3/spark_semantics.py 2>/dev/null`（Spark log 走 stderr，故丟掉）

```python
"""用小資料驗證 buggy_pipeline.py 的三個語意（不執行原管線）。用法：uv run python spark_semantics.py"""
import shutil, tempfile
import pyspark
from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession, Window, functions as F

b = (SparkSession.builder.master("local[1]").appName("partb_semantics")
     .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
     .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
     .config("spark.ui.enabled", "false"))
spark = configure_spark_with_delta_pip(b).getOrCreate()
spark.sparkContext.setLogLevel("OFF")
print("pyspark", pyspark.__version__)

# (1) clean_orders：dropDuplicates 之後再套 window，row_number 只會對到一列
orders = spark.createDataFrame(
    [("O1", "2026-07-01T10:00:00", "2026-07-01T10:00:00", "paid"),
     ("O1", "2026-07-01T10:00:00", "2026-07-02T09:00:00", "completed"),
     ("O2", "2026-07-01T11:00:00", "2026-07-01T11:00:00", "created")],
    "order_id string, order_created_at string, updated_at string, order_status string")
deduped = orders.dropDuplicates(["order_id"])
w = Window.partitionBy("order_id").orderBy(F.col("order_created_at").desc())
ranked = deduped.withColumn("rn", F.row_number().over(w))
print("[1] 原始列數", orders.count(), "dropDuplicates 後", deduped.count(),
      "rn 值分布", sorted(r.rn for r in ranked.collect()),
      "filter(rn==1) 後", ranked.filter(F.col("rn") == 1).count())

# (2) update_dim_member：overwrite + replaceWhere "member_id IS NOT NULL" 會清表
path = tempfile.mkdtemp() + "/dim_member"
dim = spark.createDataFrame([(f"M{i:03d}", "銀卡", "台北市") for i in range(1, 6)],
                            "member_id string, member_level string, city string")
dim.write.format("delta").save(path)
print("[2] 寫入前 dim 列數", spark.read.format("delta").load(path).count())
updated = spark.createDataFrame([("M001", "金卡", "台北市")], "member_id string, member_level string, city string")
updated.write.format("delta").mode("overwrite").option("replaceWhere", "member_id IS NOT NULL").save(path)
print("[2] 只寫 1 列變更後 dim 列數", spark.read.format("delta").load(path).count(),
      [tuple(r) for r in spark.read.format("delta").load(path).collect()])
empty = updated.limit(0)
empty.write.format("delta").mode("overwrite").option("replaceWhere", "member_id IS NOT NULL").save(path)
print("[2] changed 為空時 dim 列數", spark.read.format("delta").load(path).count())
shutil.rmtree(path.rsplit("/", 1)[0])

# (3) clean_orders：字串欄位 F.col("amount") > 0 的隱式轉型
amt = spark.createDataFrame([("A", "0.5"), ("B", "100.0"), ("C", "1,200")], "id string, amount string")
for ansi in ("false", "true"):
    spark.conf.set("spark.sql.ansi.enabled", ansi)
    q = amt.filter(F.col("amount") > 0)
    print(f"[3] spark.sql.ansi.enabled={ansi}")
    q.explain()
    try:
        print("    結果", [tuple(r) for r in q.collect()])
    except Exception as e:
        print("    錯誤", str(e).splitlines()[0][:160])
spark.stop()
```

```
pyspark 4.2.0
[1] 原始列數 3 dropDuplicates 後 2 rn 值分布 [1, 1] filter(rn==1) 後 2
[2] 寫入前 dim 列數 5
[2] 只寫 1 列變更後 dim 列數 1 [('M001', '金卡', '台北市')]
[2] changed 為空時 dim 列數 0
[3] spark.sql.ansi.enabled=false
== Physical Plan ==
*(1) Filter (isnotnull(amount#3415) AND (cast(amount#3415 as int) > 0))
+- *(1) Scan ExistingRDD[id#3414,amount#3415]

    結果 [('B', '100.0')]
[3] spark.sql.ansi.enabled=true
== Physical Plan ==
*(1) Filter (isnotnull(amount#3415) AND (cast(amount#3415 as bigint) > 0))
+- *(1) Scan ExistingRDD[id#3414,amount#3415]

    錯誤 [CAST_INVALID_INPUT] The value '0.5' of the type "STRING" cannot be cast to "BIGINT" because it is malformed. Correct the value as per the syntax, or change its
```

## E6｜ANSI 逐值測試與 day1 實際檔案（#1）

執行：`uv run python /tmp/partb_r3/ansi_each.py LionDEExam/candidate_package/dataset 2>/dev/null`。另以 `s.conf.get('spark.sql.ansi.enabled')` 確認 pyspark 4.2 預設為 `true`；三個增量檔不含小數點的 `amount` 列數都是 0（day1 4615、day2 4700、day3 4615 列）。

```python
"""ANSI 開啟時，逐一測試字串金額在 F.col("amount") > 0 下會不會報錯；並用 day1 實際資料跑一次。用法：uv run python ansi_each.py <dataset 目錄>"""
import sys
from pyspark.sql import SparkSession, functions as F
spark = SparkSession.builder.master("local[1]").config("spark.ui.enabled", "false").getOrCreate()
spark.sparkContext.setLogLevel("OFF")
for ansi in ("false", "true"):
    spark.conf.set("spark.sql.ansi.enabled", ansi)
    for v in ("100", "100.0", "83.24", "0.5", "1,200"):
        df = spark.createDataFrame([(v,)], "amount string").filter(F.col("amount") > 0)
        try:
            print(f"ansi={ansi} amount={v!r}: 保留列數 {df.count()}")
        except Exception as e:
            print(f"ansi={ansi} amount={v!r}: 錯誤 {str(e).split(']')[0]}]")
    d1 = spark.read.option("header", True).csv(f"{sys.argv[1]}/orders_incremental_day1.csv")
    try:
        print(f"ansi={ansi} day1 原始 {d1.count()} 列，filter(F.col(\"amount\") > 0) 後 {d1.filter(F.col('amount') > 0).count()} 列")
    except Exception as e:
        print(f"ansi={ansi} day1: 錯誤 {str(e).split(']')[0]}]")
spark.stop()
```

```
ansi=false amount='100': 保留列數 1
ansi=false amount='100.0': 保留列數 1
ansi=false amount='83.24': 保留列數 1
ansi=false amount='0.5': 保留列數 0
ansi=false amount='1,200': 保留列數 0
ansi=false day1 原始 4615 列，filter(F.col("amount") > 0) 後 4615 列
ansi=true amount='100': 保留列數 1
ansi=true amount='100.0': 錯誤 [CAST_INVALID_INPUT]
ansi=true amount='83.24': 錯誤 [CAST_INVALID_INPUT]
ansi=true amount='0.5': 錯誤 [CAST_INVALID_INPUT]
ansi=true amount='1,200': 錯誤 [CAST_INVALID_INPUT]
ansi=true day1: 錯誤 [CAST_INVALID_INPUT]
```

發現：ANSI 開啟時不只 `0.5`，`100.0`、`83.24` 這類帶小數點的字串都無法轉成 bigint，day1 實際檔案也報錯；派工時的預期是「只有 0.5 會出事、目前不影響數字」，實測後改寫成「ANSI 關閉時不影響現在的數字，ANSI 開啟時整條管線失敗」。

## E7｜同分隔離後仍對不到的訂單（#6、#7）

第四輪驗收後重算（`python3 -I`，`encoding="utf-8-sig"`）。舊紀錄只保留輸出，沒有保留腳本全文：

```
ties 28 distinct extract_date count dist {1: 28}
day1 dedup 4597
orders of tie members 17
non-tie unmatched after stepwise MERGE 0
```

意義：最新快照同分的 28 位會員都只有一個 `extract_date`，被同分隔離後進不了 dim，day1 去重後有 17 張訂單對不到任何版本；其餘會員逐批 MERGE 後 0 張對不到。


## E8｜ruff、mypy 靜態分析（appendix.md）

`buggy_pipeline.py` 已由使用者從原始 zip 還原（179 行）。專案沒有 ruff 設定檔，用預設規則。

```
$ uv run ruff --version
ruff 0.17.0
$ uv run ruff check --output-format concise LionDEExam/candidate_package/buggy_pipeline.py
LionDEExam/candidate_package/buggy_pipeline.py:1:1: UP009 [*] UTF-8 encoding declaration is unnecessary
LionDEExam/candidate_package/buggy_pipeline.py:14:1: I001 [*] Import block is un-sorted or un-formatted
LionDEExam/candidate_package/buggy_pipeline.py:172:5: F841 Local variable `dim_member` is assigned to but never used
Found 3 errors.
[*] 2 fixable with `--fix` (1 unsafe fix available with `--fix --unsafe-fixes`).
```

mypy 用 `uv run --with mypy` 臨時安裝（不改 `pyproject.toml`），專案沒有 mypy 設定檔；pyspark 4.2 自帶型別資訊。

```
$ uv run --with mypy mypy --version
mypy 2.4.0 (compiled: yes)
$ uv run --with mypy mypy LionDEExam/candidate_package/buggy_pipeline.py
Success: no issues found in 1 source file
$ uv run --with mypy mypy --check-untyped-defs LionDEExam/candidate_package/buggy_pipeline.py
LionDEExam/candidate_package/buggy_pipeline.py:159: error: Need type annotation for "counts" (hint: "counts: dict[<type>, <type>] = ...")  [var-annotated]
Found 1 error in 1 file (checked 1 source file)
$ uv run --with mypy mypy --strict LionDEExam/candidate_package/buggy_pipeline.py
LionDEExam/candidate_package/buggy_pipeline.py:25: error: Function is missing a return type annotation  [no-untyped-def]
LionDEExam/candidate_package/buggy_pipeline.py:39: error: Function is missing a type annotation  [no-untyped-def]
LionDEExam/candidate_package/buggy_pipeline.py:64: error: Function is missing a type annotation  [no-untyped-def]
LionDEExam/candidate_package/buggy_pipeline.py:67: error: Function is missing a type annotation  [no-untyped-def]
LionDEExam/candidate_package/buggy_pipeline.py:86: error: Function is missing a type annotation  [no-untyped-def]
LionDEExam/candidate_package/buggy_pipeline.py:124: error: Function is missing a type annotation  [no-untyped-def]
LionDEExam/candidate_package/buggy_pipeline.py:151: error: Function is missing a type annotation  [no-untyped-def]
LionDEExam/candidate_package/buggy_pipeline.py:159: error: Need type annotation for "counts" (hint: "counts: dict[<type>, <type>] = ...")  [var-annotated]
LionDEExam/candidate_package/buggy_pipeline.py:168: error: Function is missing a return type annotation  [no-untyped-def]
LionDEExam/candidate_package/buggy_pipeline.py:170: error: Call to untyped function "clean_orders" in typed context  [no-untyped-call]
LionDEExam/candidate_package/buggy_pipeline.py:171: error: Call to untyped function "convert_currency" in typed context  [no-untyped-call]
LionDEExam/candidate_package/buggy_pipeline.py:172: error: Call to untyped function "update_dim_member" in typed context  [no-untyped-call]
LionDEExam/candidate_package/buggy_pipeline.py:173: error: Call to untyped function "build_fact" in typed context  [no-untyped-call]
LionDEExam/candidate_package/buggy_pipeline.py:174: error: Call to untyped function "write_fact" in typed context  [no-untyped-call]
Found 14 errors in 1 file (checked 1 source file)
```

## E9｜資料字典的統計（`notes/dataset/`）

舊紀錄只保留輸出摘要，沒有保留腳本全文：

- 逐欄統計筆數、空值、值域，以及 key 是否唯一。主要輸出：所有檔案都有 BOM；空值 0；orders_base 有 100,040 列、100,000 個 order_id；base 的 currency 含 NTD 200 筆；base 的 `order_created_at` 有三種格式（+08:00 有 94,038 筆、`/` 有 3,001 筆、Z 有 3,001 筆）；base 有 120 筆 product_id 不在主檔；members 的 (member_id, extract_date) 重複 30 組；fx (rate_date, currency) 唯一。
- AI 自查：第一次統計 amount 用字串比大小（例如輸出 `min=100129.0 max=99863.0`），結果沒有意義。改成轉成 float 重算，文件中的數字都是重算後的值。
- 增量檔 `updated_at`（`notes/dataset/incremental.md`）：day1 `updated_at` 日期分布 {07-01: 1325, 07-02: 1428, 07-03: 1415, 07-04: 442, 07-05: 5}，晚於批次日 3,290 筆；day1 最晚到 07-05（批次日後 4 天），day2 有 6 列早於批次日。

- amount 依幣別的分布與 base 極端值（2026-10-11 補，`notes/dataset/dictionary.md`「amount 分布」）：腳本存成 `amt.py`，以 `python3 -I amt.py candidate_package/dataset` 執行（在 `LionDEExam/` 下）。

```python
import csv, sys, statistics, glob, os, re
d = sys.argv[1]
for f in ["orders_base.csv","orders_incremental_day1.csv","orders_incremental_day2.csv","orders_incremental_day3.csv"]:
    rows = list(csv.DictReader(open(os.path.join(d,f), encoding="utf-8-sig")))
    bad = {}; by = {}
    for r in rows:
        a = r["amount"]; c = r["currency"]
        try: v = float(a)
        except ValueError:
            bad[a] = bad.get(a,0)+1; continue
        by.setdefault(c, []).append(v)
    print(f"== {f}  rows={len(rows)}  無法轉數字={sum(bad.values())} {dict(list(bad.items())[:5])}")
    for c, vs in sorted(by.items()):
        vs.sort(); n=len(vs)
        q = lambda p: vs[min(n-1,int(p*n))]
        neg=sum(v<0 for v in vs); zero=sum(v==0 for v in vs)
        print(f"  {c:4} n={n:6} min={vs[0]:>10} p25={q(.25):>9} p50={q(.5):>9} p75={q(.75):>9} p99={q(.99):>10} max={vs[-1]:>10}  <0={neg} =0={zero}")
rows = list(csv.DictReader(open(os.path.join(d, "orders_base.csv"), encoding="utf-8-sig")))
p99 = {"TWD": 837563, "JPY": 4075948, "USD": 26263.67, "NTD": 864376}  # 上面 base 的 p99
out = [(r["currency"], float(r["amount"])) for r in rows if float(r["amount"]) > 2 * p99[r["currency"]]]
print("base 超過該幣別 p99 兩倍:", len(out), {c: sum(x[0] == c for x in out) for c in p99})
print(sorted(out, key=lambda x: -x[1])[:5])
print("1000 的倍數:", sum(v % 1000 == 0 for _, v in out), "/", len(out))
print("除以 1000 後 <= 該幣別 p99 的 1.2 倍:", sum(v / 1000 <= p99[c] * 1.2 for c, v in out), "/", len(out))
```

輸出：

```
== orders_base.csv  rows=100040  無法轉數字=0 {}
  JPY  n= 11022 min=-3087159.0 p25= 465189.0 p50= 972567.0 p75=1861932.0 p99= 4075948.0 max=3738074000.0  <0=4 =0=0
  NTD  n=   200 min=    2798.0 p25= 106874.0 p50= 222601.0 p75= 408388.0 p99=  864376.0 max=  916142.0  <0=0 =0=0
  TWD  n= 66690 min= -594452.0 p25=  95622.0 p50= 202880.0 p75= 383857.0 p99=  837563.0 max=736710000.0  <0=29 =0=0
  USD  n= 22128 min=  -27292.7 p25=  3027.64 p50=  6445.57 p75= 12084.64 p99=  26263.67 max=18074850.0  <0=17 =0=0
== orders_incremental_day1.csv  rows=4615  無法轉數字=0 {}
  JPY  n=   524 min=   33438.0 p25= 433011.0 p50=1013210.0 p75=1973066.0 p99= 4322152.0 max= 4804065.0  <0=0 =0=0
  TWD  n=  3069 min=    2762.0 p25=  99837.0 p50= 211208.0 p75= 390220.0 p99=  833597.0 max=  975967.0  <0=0 =0=0
  USD  n=  1022 min=     94.17 p25=  2993.88 p50=  6319.19 p75= 11946.64 p99=  25584.57 max=  29016.05  <0=0 =0=0
== orders_incremental_day2.csv  rows=4700  無法轉數字=0 {}
  JPY  n=   531 min=   12479.0 p25= 510401.0 p50=1062865.0 p75=1963982.0 p99= 3827568.0 max= 4489437.0  <0=0 =0=0
  TWD  n=  3150 min=    2893.0 p25=  95583.0 p50= 198991.0 p75= 388861.0 p99=  819236.0 max=  974801.0  <0=0 =0=0
  USD  n=  1019 min=      86.4 p25=  2851.13 p50=  6217.23 p75= 11807.82 p99=  26091.03 max=  29571.52  <0=0 =0=0
== orders_incremental_day3.csv  rows=4615  無法轉數字=0 {}
  JPY  n=   521 min=   12897.0 p25= 428930.0 p50= 912853.0 p75=1880873.0 p99= 4088927.0 max= 4456237.0  <0=0 =0=0
  TWD  n=  3141 min=    2911.0 p25=  90574.0 p50= 195336.0 p75= 381218.0 p99=  831614.0 max=  938991.0  <0=0 =0=0
  USD  n=   953 min=     83.24 p25=  3337.31 p50=  6799.42 p75= 12179.09 p99=  26323.13 max=  30769.42  <0=0 =0=0
base 超過該幣別 p99 兩倍: 40 {'TWD': 27, 'JPY': 4, 'USD': 9, 'NTD': 0}
[('JPY', 3738074000.0), ('JPY', 2308721000.0), ('JPY', 1903148000.0), ('TWD', 736710000.0), ('TWD', 622448000.0)]
1000 的倍數: 31 / 40
除以 1000 後 <= 該幣別 p99 的 1.2 倍: 40 / 40
```

- base 負數金額的調查（2026-10-11 補，`notes/dataset/dictionary.md`「amount 分布」）：檢查 50 筆負數從何而來（狀態、是否有對應原單、取絕對值後的量級）。腳本存成 `neg.py`，以 `python3 -I neg.py candidate_package/dataset` 執行（在 `LionDEExam/` 下）。

```python
import csv, sys, os, collections
rows = list(csv.DictReader(open(os.path.join(sys.argv[1], "orders_base.csv"), encoding="utf-8-sig")))
neg = [r for r in rows if float(r["amount"]) < 0]
print("負數列:", len(neg), collections.Counter(r["currency"] for r in neg))
print("負數列 order_status:", collections.Counter(r["order_status"] for r in neg))
print("全體 order_status:", collections.Counter(r["order_status"] for r in rows))
ids = {r["order_id"] for r in neg}
print("負數列的 order_id 在 base 另有正數列:", sum(1 for r in rows if r["order_id"] in ids and float(r["amount"]) > 0))
print("負數列 coupon_discount 為負:", sum(float(r["coupon_discount"]) < 0 for r in neg))
by = collections.defaultdict(list)
for r in rows:
    v = float(r["amount"])
    if v > 0: by[r["currency"]].append(v)
for c in ("TWD", "USD", "JPY"):
    pos = sorted(by[c]); a = sorted(-float(r["amount"]) for r in neg if r["currency"] == c)
    within = sum(pos[0] <= x <= pos[int(.99 * len(pos))] for x in a)
    print(f"{c}: 取絕對值後落在正數列 min~p99 內 {within}/{len(a)}")
for r in neg[:3]:
    print({k: r[k] for k in ("order_id", "currency", "amount", "order_status", "quantity", "coupon_discount")})
```

輸出：

```
負數列: 50 Counter({'TWD': 29, 'USD': 17, 'JPY': 4})
負數列 order_status: Counter({'paid': 19, 'completed': 18, 'cancelled': 7, 'created': 6})
全體 order_status: Counter({'paid': 42894, 'completed': 28612, 'created': 14286, 'cancelled': 14248})
負數列的 order_id 在 base 另有正數列: 0
負數列 coupon_discount 為負: 1
TWD: 取絕對值後落在正數列 min~p99 內 29/29
USD: 取絕對值後落在正數列 min~p99 內 16/17
JPY: 取絕對值後落在正數列 min~p99 內 4/4
{'order_id': 'ORD00034533', 'currency': 'TWD', 'amount': '-89782.0', 'order_status': 'paid', 'quantity': '1', 'coupon_discount': '200.0'}
{'order_id': 'ORD00031409', 'currency': 'TWD', 'amount': '-331736.0', 'order_status': 'completed', 'quantity': '2', 'coupon_discount': '400.0'}
{'order_id': 'ORD00018643', 'currency': 'USD', 'amount': '-17089.38', 'order_status': 'completed', 'quantity': '3', 'coupon_discount': '250.0'}
```

## E10｜Delta 寫入後的錯誤處理：重跑、RESTORE、VACUUM、並行衝突（prod-recovery.md）

驗證報告建議的 fact 寫法（以 `order_id` MERGE，`whenMatchedUpdateAll(condition="s.updated_at > t.updated_at")`＋`whenNotMatchedInsertAll`）寫入之後，出錯時能不能復原。不讀 dataset，只用自建的幾列小資料（`order_id`、`order_status`、`updated_at`），Delta 表寫在 `/tmp` 下的暫存目錄，跑完刪除。

執行：在 `LionTest/` 執行 `uv run python -u /tmp/partb_e10/delta_recovery.py 2>/dev/null`（`-u` 讓 Python 輸出不緩衝，`Deleted 7 files ...` 那行是 Delta 的 VACUUM 自己印到 stdout 的，加 `-u` 後才會出現在正確位置）。五個情境在同一支腳本，輸出以 `[1]`～`[5]` 對應。

```python
"""E10：Delta MERGE 之後的錯誤處理（冪等重跑、RESTORE、VACUUM、並行衝突、中途失敗）。用法：uv run python delta_recovery.py"""
import shutil, tempfile, threading
from datetime import datetime as dt
import pyspark, delta
from delta import configure_spark_with_delta_pip
from delta.tables import DeltaTable
from pyspark.sql import SparkSession, functions as F

b = (SparkSession.builder.master("local[4]").appName("partb_e10")
     .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
     .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
     .config("spark.ui.enabled", "false"))
spark = configure_spark_with_delta_pip(b).getOrCreate()
spark.sparkContext.setLogLevel("OFF")
print("pyspark", pyspark.__version__, "delta-spark", delta.__version__ if hasattr(delta, "__version__") else "?")

SCHEMA = "order_id string, order_status string, updated_at timestamp"
ROOT = tempfile.mkdtemp(dir="/tmp", prefix="e10_")

def batch(rows):
    return spark.createDataFrame([(o, s, dt.fromisoformat(u)) for o, s, u in rows], SCHEMA)

def merge(path, src):
    """報告建議的寫法：以 order_id MERGE，只在來源 updated_at 較新時更新。"""
    (DeltaTable.forPath(spark, path).alias("t")
     .merge(src.alias("s"), "t.order_id = s.order_id")
     .whenMatchedUpdateAll(condition="s.updated_at > t.updated_at")
     .whenNotMatchedInsertAll()
     .execute())

def show(tag, path, version=None):
    r = spark.read.format("delta")
    if version is not None:
        r = r.option("versionAsOf", version)
    rows = [(x.order_id, x.order_status, str(x.updated_at)) for x in r.load(path).orderBy("order_id").collect()]
    print(f"  {tag}: {rows}")

def history(path):
    h = DeltaTable.forPath(spark, path).history().orderBy("version").collect()
    for x in h:
        m = x.operationMetrics or {}
        keys = ["numTargetRowsInserted", "numTargetRowsUpdated", "numTargetRowsCopied", "numOutputRows"]
        print(f"  v{x.version} {x.operation}", {k: m[k] for k in keys if k in m})

def latest(path):
    return DeltaTable.forPath(spark, path).history(1).collect()[0].version

def err(e):
    j = getattr(e, "java_exception", None)  # Py4JJavaError：往下找最底層的 Java 例外
    if j is not None:
        while j.getCause() is not None:
            j = j.getCause()
        return f"{type(e).__name__} <- {j.getClass().getName()}: {str(j.getMessage()).splitlines()[0][:200]}"
    return f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"

# ---------- (1) 冪等與重播順序 ----------
print("[1] 冪等與重播順序")
p1 = f"{ROOT}/fact1"
batch([("O1", "created", "2026-07-01 10:00:00"),
       ("O2", "created", "2026-07-01 11:00:00")]).write.format("delta").save(p1)
show("v0 建表", p1)
b1 = batch([("O1", "paid", "2026-07-02 09:00:00"),
            ("O3", "created", "2026-07-02 10:00:00")])
merge(p1, b1); show(f"套用 batch1 後 (v{latest(p1)})", p1)
merge(p1, b1); show(f"同一批 batch1 再跑一次後 (v{latest(p1)})", p1)
old = batch([("O1", "created", "2026-07-01 10:30:00")])
merge(p1, old); show(f"套用 updated_at 較舊的批次後 (v{latest(p1)})", p1)
history(p1)

# ---------- (2) 錯誤寫入後 RESTORE ----------
print("[2] 錯誤寫入後 RESTORE")
p2 = f"{ROOT}/fact2"
batch([("O1", "paid", "2026-07-02 09:00:00"),
       ("O2", "created", "2026-07-01 11:00:00")]).write.format("delta").save(p2)
good_v = latest(p2); show(f"錯誤之前 (v{good_v})", p2)
bad = batch([("O1", "cancelled", "2026-07-03 09:00:00"),      # 邏輯錯：O1 其實是 completed
             ("O2", "cancelled", "2026-07-03 09:00:00")])     # 邏輯錯：O2 其實是 paid
merge(p2, bad); show(f"套用錯誤批次後 (v{latest(p2)})", p2)
nxt = batch([("O3", "created", "2026-07-04 08:00:00")])       # 錯誤之後的正確批次
merge(p2, nxt); show(f"再套用正確的新批次後 (v{latest(p2)})", p2)
spark.sql(f"RESTORE TABLE delta.`{p2}` TO VERSION AS OF {good_v}").show(truncate=False)
show(f"RESTORE TO VERSION AS OF {good_v} 後 (v{latest(p2)})", p2)
fix = batch([("O1", "completed", "2026-07-03 09:00:00"),      # 修正後重跑錯誤那一批
             ("O2", "paid", "2026-07-03 09:00:00")])
merge(p2, fix); merge(p2, nxt)
show(f"重跑修正批次＋重播正確批次後 (v{latest(p2)})", p2)
history(p2)

# ---------- (3) VACUUM 是單向門 ----------
print("[3] VACUUM")
try:
    spark.sql(f"VACUUM delta.`{p2}` RETAIN 0 HOURS")
    print("  未關閉檢查直接 RETAIN 0 HOURS：沒有被擋")
except Exception as e:
    print("  未關閉檢查直接 RETAIN 0 HOURS：", err(e))
show("VACUUM 前讀 versionAsOf 1（錯誤批次那版）", p2, version=1)
spark.conf.set("spark.databricks.delta.retentionDurationCheck.enabled", "false")
spark.sql(f"VACUUM delta.`{p2}` RETAIN 0 HOURS").show(truncate=False)
show(f"VACUUM 後讀目前版本 (v{latest(p2)})", p2)
for v in (0, 1):
    try:
        show(f"VACUUM 後讀 versionAsOf {v}", p2, version=v)
    except Exception as e:
        print(f"  VACUUM 後讀 versionAsOf {v}：", err(e))
try:
    spark.sql(f"RESTORE TABLE delta.`{p2}` TO VERSION AS OF 0")
    print("  VACUUM 後 RESTORE 到 v0：成功"); show("RESTORE 後", p2)
except Exception as e:
    print("  VACUUM 後 RESTORE 到 v0：", err(e))
print("  VACUUM 後 DESCRIBE HISTORY："); history(p2)
spark.conf.set("spark.databricks.delta.retentionDurationCheck.enabled", "true")

# ---------- (4) 並行衝突 ----------
print("[4] 兩個 thread 同時 MERGE 同一批 order_id")
for attempt in range(1, 6):
    p4 = f"{ROOT}/fact4_{attempt}"
    batch([(f"O{i}", "created", "2026-07-01 10:00:00") for i in range(1, 6)]).write.format("delta").save(p4)
    srcA = batch([(f"O{i}", "paid", "2026-07-02 09:00:00") for i in range(1, 6)])
    srcB = batch([(f"O{i}", "cancelled", "2026-07-02 10:00:00") for i in range(1, 6)])
    barrier, res = threading.Barrier(2), {}
    def run(name, src):
        barrier.wait()
        try:
            merge(p4, src); res[name] = "成功"
        except Exception as e:
            res[name] = err(e)
    ts = [threading.Thread(target=run, args=("A", srcA)), threading.Thread(target=run, args=("B", srcB))]
    [t.start() for t in ts]; [t.join() for t in ts]
    print(f"  第 {attempt} 次: A={res['A']} | B={res['B']} | 最新版本 v{latest(p4)}")
    show("    表內容", p4)
    if any(v != "成功" for v in res.values()):
        break

# ---------- (5) MERGE 中途失敗 ----------
print("[5] MERGE 來源在執行中拋例外")
p5 = f"{ROOT}/fact5"
batch([("O1", "created", "2026-07-01 10:00:00"),
       ("O2", "created", "2026-07-01 11:00:00")]).write.format("delta").save(p5)
v_before = latest(p5); show(f"MERGE 前 (v{v_before})", p5)
@F.udf("string")
def boom(order_id, status):
    if order_id == "O3":
        raise ValueError("模擬第 3 列處理失敗")
    return status
src5 = batch([("O1", "paid", "2026-07-02 09:00:00"),
              ("O2", "paid", "2026-07-02 09:00:00"),
              ("O3", "created", "2026-07-02 10:00:00")]).withColumn("order_status", boom("order_id", "order_status"))
try:
    merge(p5, src5); print("  MERGE 成功（未預期）")
except Exception as e:
    print("  MERGE 例外：", type(e).__name__)
    print("  訊息含 ValueError：", "模擬第 3 列處理失敗" in str(e))
show(f"例外後 (最新版本 v{latest(p5)})", p5)
history(p5)

shutil.rmtree(ROOT)
spark.stop()
```

```
pyspark 4.2.0 delta-spark 4.4.1
[1] 冪等與重播順序
  v0 建表: [('O1', 'created', '2026-07-01 10:00:00'), ('O2', 'created', '2026-07-01 11:00:00')]
  套用 batch1 後 (v1): [('O1', 'paid', '2026-07-02 09:00:00'), ('O2', 'created', '2026-07-01 11:00:00'), ('O3', 'created', '2026-07-02 10:00:00')]
  同一批 batch1 再跑一次後 (v2): [('O1', 'paid', '2026-07-02 09:00:00'), ('O2', 'created', '2026-07-01 11:00:00'), ('O3', 'created', '2026-07-02 10:00:00')]
  套用 updated_at 較舊的批次後 (v3): [('O1', 'paid', '2026-07-02 09:00:00'), ('O2', 'created', '2026-07-01 11:00:00'), ('O3', 'created', '2026-07-02 10:00:00')]
  v0 WRITE {'numOutputRows': '2'}
  v1 MERGE {'numTargetRowsInserted': '1', 'numTargetRowsUpdated': '1', 'numTargetRowsCopied': '0', 'numOutputRows': '2'}
  v2 MERGE {'numTargetRowsInserted': '0', 'numTargetRowsUpdated': '0', 'numTargetRowsCopied': '2', 'numOutputRows': '2'}
  v3 MERGE {'numTargetRowsInserted': '0', 'numTargetRowsUpdated': '0', 'numTargetRowsCopied': '2', 'numOutputRows': '2'}
[2] 錯誤寫入後 RESTORE
  錯誤之前 (v0): [('O1', 'paid', '2026-07-02 09:00:00'), ('O2', 'created', '2026-07-01 11:00:00')]
  套用錯誤批次後 (v1): [('O1', 'cancelled', '2026-07-03 09:00:00'), ('O2', 'cancelled', '2026-07-03 09:00:00')]
  再套用正確的新批次後 (v2): [('O1', 'cancelled', '2026-07-03 09:00:00'), ('O2', 'cancelled', '2026-07-03 09:00:00'), ('O3', 'created', '2026-07-04 08:00:00')]
+------------------------+--------------------------+-----------------+------------------+------------------+-------------------+
|table_size_after_restore|num_of_files_after_restore|num_removed_files|num_restored_files|removed_files_size|restored_files_size|
+------------------------+--------------------------+-----------------+------------------+------------------+-------------------+
|2079                    |2                         |2                |2                 |2147              |2079               |
+------------------------+--------------------------+-----------------+------------------+------------------+-------------------+

  RESTORE TO VERSION AS OF 0 後 (v3): [('O1', 'paid', '2026-07-02 09:00:00'), ('O2', 'created', '2026-07-01 11:00:00')]
  重跑修正批次＋重播正確批次後 (v5): [('O1', 'completed', '2026-07-03 09:00:00'), ('O2', 'paid', '2026-07-03 09:00:00'), ('O3', 'created', '2026-07-04 08:00:00')]
  v0 WRITE {'numOutputRows': '2'}
  v1 MERGE {'numTargetRowsInserted': '0', 'numTargetRowsUpdated': '2', 'numTargetRowsCopied': '0', 'numOutputRows': '2'}
  v2 MERGE {'numTargetRowsInserted': '1', 'numTargetRowsUpdated': '0', 'numTargetRowsCopied': '0', 'numOutputRows': '1'}
  v3 RESTORE {}
  v4 MERGE {'numTargetRowsInserted': '0', 'numTargetRowsUpdated': '2', 'numTargetRowsCopied': '0', 'numOutputRows': '2'}
  v5 MERGE {'numTargetRowsInserted': '1', 'numTargetRowsUpdated': '0', 'numTargetRowsCopied': '0', 'numOutputRows': '1'}
[3] VACUUM
  未關閉檢查直接 RETAIN 0 HOURS： IllegalArgumentException: [DELTA_VACUUM_RETENTION_PERIOD_TOO_SHORT] The specified VACUUM retention period is too low and may corrupt this Delta table if any writes are in progress.
  VACUUM 前讀 versionAsOf 1（錯誤批次那版）: [('O1', 'cancelled', '2026-07-03 09:00:00'), ('O2', 'cancelled', '2026-07-03 09:00:00')]
Deleted 7 files and directories in a total of 1 directories.
+----------------------------+
|path                        |
+----------------------------+
|file:/tmp/e10_beq8hggc/fact2|
+----------------------------+

  VACUUM 後讀目前版本 (v7): [('O1', 'completed', '2026-07-03 09:00:00'), ('O2', 'paid', '2026-07-03 09:00:00'), ('O3', 'created', '2026-07-04 08:00:00')]
  VACUUM 後讀 versionAsOf 0： Py4JJavaError <- java.io.FileNotFoundException: File file:/tmp/e10_beq8hggc/fact2/part-00003-1519e43c-e0e2-48bc-93d0-79c10afd8960-c000.snappy.parquet does not exist
  VACUUM 後讀 versionAsOf 1： Py4JJavaError <- java.io.FileNotFoundException: File file:/tmp/e10_beq8hggc/fact2/part-00000-1c7dc372-24f1-4114-be91-08285800b618-c000.snappy.parquet does not exist
  VACUUM 後 RESTORE 到 v0： IllegalArgumentException: Not all files from version 0 are available in file system.
  VACUUM 後 DESCRIBE HISTORY：
  v0 WRITE {'numOutputRows': '2'}
  v1 MERGE {'numTargetRowsInserted': '0', 'numTargetRowsUpdated': '2', 'numTargetRowsCopied': '0', 'numOutputRows': '2'}
  v2 MERGE {'numTargetRowsInserted': '1', 'numTargetRowsUpdated': '0', 'numTargetRowsCopied': '0', 'numOutputRows': '1'}
  v3 RESTORE {}
  v4 MERGE {'numTargetRowsInserted': '0', 'numTargetRowsUpdated': '2', 'numTargetRowsCopied': '0', 'numOutputRows': '2'}
  v5 MERGE {'numTargetRowsInserted': '1', 'numTargetRowsUpdated': '0', 'numTargetRowsCopied': '0', 'numOutputRows': '1'}
  v6 VACUUM START {}
  v7 VACUUM END {}
[4] 兩個 thread 同時 MERGE 同一批 order_id
  第 1 次: A=ConcurrentAppendException: [DELTA_CONCURRENT_APPEND.WITHOUT_HINT] Transaction conflict detected. a concurrent MERGE added data to table delta.`file:/tmp/e10_beq8hggc/fact4_1` committed at version 1. The concurrent operation mod | B=成功 | 最新版本 v1
      表內容: [('O1', 'cancelled', '2026-07-02 10:00:00'), ('O2', 'cancelled', '2026-07-02 10:00:00'), ('O3', 'cancelled', '2026-07-02 10:00:00'), ('O4', 'cancelled', '2026-07-02 10:00:00'), ('O5', 'cancelled', '2026-07-02 10:00:00')]
[5] MERGE 來源在執行中拋例外
  MERGE 前 (v0): [('O1', 'created', '2026-07-01 10:00:00'), ('O2', 'created', '2026-07-01 11:00:00')]
  MERGE 例外： PythonException
  訊息含 ValueError： True
  例外後 (最新版本 v0): [('O1', 'created', '2026-07-01 10:00:00'), ('O2', 'created', '2026-07-01 11:00:00')]
  v0 WRITE {'numOutputRows': '2'}
```

各情境結論（只寫輸出能支持的內容）：

- `[1]` 冪等與重播順序：同一批 batch1 再跑一次，表內容不變，但**版本號仍前進**（v1 → v2），`DESCRIBE HISTORY` 記為 MERGE、`numTargetRowsUpdated` 0、`numTargetRowsCopied` 2，也就是條件不成立時不改值，但檔案仍被重寫一次。套用 `updated_at` 較舊的批次（O1 `created`、07-01 10:30）後 O1 仍是 `paid`，狀態沒有倒退（v3 同樣 0 更新、2 copied）。
- `[2]` RESTORE：`RESTORE TABLE ... TO VERSION AS OF 0` 把錯誤批次（v1，O1、O2 寫成 `cancelled`）退回，但錯誤之後那個正確批次（v2 新增的 O3）**也一起消失**；RESTORE 本身成為新版本 v3，不是刪掉 v1、v2。之後重跑修正批次與重播 O3 那批（v4、v5），內容才正確。
- `[3]` VACUUM：未關閉檢查直接 `RETAIN 0 HOURS` 被擋，例外為 `IllegalArgumentException: [DELTA_VACUUM_RETENTION_PERIOD_TOO_SHORT]`。關閉 `spark.databricks.delta.retentionDurationCheck.enabled` 後 VACUUM 刪了 7 個檔案；目前版本仍可讀，但 `versionAsOf 0`、`versionAsOf 1` 讀取失敗（最底層例外 `java.io.FileNotFoundException`，parquet 檔不存在），`RESTORE ... TO VERSION AS OF 0` 失敗（`IllegalArgumentException: Not all files from version 0 are available in file system.`）。`DESCRIBE HISTORY` 仍列出 v0～v5，並多了 v6 `VACUUM START`、v7 `VACUUM END`：歷史紀錄還在，舊版本的資料檔已經沒了。
- `[4]` 並行衝突：兩個 thread 以 `threading.Barrier` 同時起跑，對同一批 O1～O5 做 MERGE，第 1 次就重現：一個成功、另一個得到 `ConcurrentAppendException`（`[DELTA_CONCURRENT_APPEND.WITHOUT_HINT]`），表只前進到 v1，內容是成功那一方的值。失敗的一方沒有寫入任何東西，需要由呼叫端重試。哪一方勝出不固定：收錄的這次是 B 勝；先前兩次試跑（輸出未收錄）分別是 B 勝、A 勝。
- `[5]` MERGE 中途失敗：來源的 UDF 對 O3 拋 `ValueError`，MERGE 拋出 `PythonException`（訊息含該 ValueError），之後最新版本仍是 v0、內容不變，`DESCRIBE HISTORY` 只有 v0 WRITE，沒有留下半個版本。

### `[6]` 錯誤寫入後不先 RESTORE、直接重跑修正批次

另一支小腳本，同樣的 MERGE 條件。O1 先寫入 `pending`（T1），錯誤批次把它寫成 `cancelled`（T2），之後不 RESTORE，直接套用修正批次 `paid`：`[6a]` 的修正批次 `updated_at` 同為 T2（同一筆來源資料修正後重送），`[6b]` 對照組用 T3（> T2）。

執行：在 `LionTest/` 執行 `uv run python -u /tmp/partb_e10/rerun_without_restore.py 2>/dev/null`

```python
"""E10 [6]：錯誤寫入後不先 RESTORE、直接重跑修正批次。用法：uv run python rerun_without_restore.py"""
import shutil, tempfile
from datetime import datetime as dt
from delta import configure_spark_with_delta_pip
from delta.tables import DeltaTable
from pyspark.sql import SparkSession

b = (SparkSession.builder.master("local[2]").appName("partb_e10_6")
     .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
     .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
     .config("spark.ui.enabled", "false"))
spark = configure_spark_with_delta_pip(b).getOrCreate()
spark.sparkContext.setLogLevel("OFF")

SCHEMA = "order_id string, order_status string, updated_at timestamp"
ROOT = tempfile.mkdtemp(dir="/tmp", prefix="e10_6_")
T1, T2, T3 = "2026-07-01 10:00:00", "2026-07-02 09:00:00", "2026-07-03 09:00:00"

def batch(rows):
    return spark.createDataFrame([(o, s, dt.fromisoformat(u)) for o, s, u in rows], SCHEMA)

def merge(path, src):
    (DeltaTable.forPath(spark, path).alias("t")
     .merge(src.alias("s"), "t.order_id = s.order_id")
     .whenMatchedUpdateAll(condition="s.updated_at > t.updated_at")
     .whenNotMatchedInsertAll()
     .execute())

def show(tag, path):
    rows = [(x.order_id, x.order_status, str(x.updated_at)) for x in spark.read.format("delta").load(path).collect()]
    m = DeltaTable.forPath(spark, path).history(1).collect()[0]
    upd = (m.operationMetrics or {}).get("numTargetRowsUpdated", "-")
    print(f"  {tag} (v{m.version} {m.operation}, numTargetRowsUpdated={upd}): {rows}")

for label, fix_ts in (("[6a] 修正批次 updated_at = T2（與錯誤批次相同）", T2),
                      ("[6b] 對照：修正批次 updated_at = T3（> T2）", T3)):
    print(label)
    p = f"{ROOT}/fact_{fix_ts[8:10]}"
    batch([("O1", "pending", T1)]).write.format("delta").save(p)
    show("v0 寫入", p)
    merge(p, batch([("O1", "cancelled", T2)]))       # 錯誤批次：O1 狀態寫錯
    show("套用錯誤批次後", p)
    merge(p, batch([("O1", "paid", fix_ts)]))        # 修正批次：同一筆修正後重送，不先 RESTORE
    show("直接套用修正批次後", p)

shutil.rmtree(ROOT)
spark.stop()
```

```
[6a] 修正批次 updated_at = T2（與錯誤批次相同）
  v0 寫入 (v0 WRITE, numTargetRowsUpdated=-): [('O1', 'pending', '2026-07-01 10:00:00')]
  套用錯誤批次後 (v1 MERGE, numTargetRowsUpdated=1): [('O1', 'cancelled', '2026-07-02 09:00:00')]
  直接套用修正批次後 (v2 MERGE, numTargetRowsUpdated=0): [('O1', 'cancelled', '2026-07-02 09:00:00')]
[6b] 對照：修正批次 updated_at = T3（> T2）
  v0 寫入 (v0 WRITE, numTargetRowsUpdated=-): [('O1', 'pending', '2026-07-01 10:00:00')]
  套用錯誤批次後 (v1 MERGE, numTargetRowsUpdated=1): [('O1', 'cancelled', '2026-07-02 09:00:00')]
  直接套用修正批次後 (v2 MERGE, numTargetRowsUpdated=1): [('O1', 'paid', '2026-07-03 09:00:00')]
```

- `[6]` 結論：修正批次的 `updated_at` 與錯誤批次相同（T2）時，`s.updated_at > t.updated_at` 不成立，MERGE 仍提交了 v2，但 `numTargetRowsUpdated=0`，**O1 最後仍是錯誤的 `cancelled`**。對照組修正批次用 T3 時，`numTargetRowsUpdated=1`，O1 被覆蓋成 `paid`。

## E11｜各增量檔與 orders_base 重疊的 order_id（#9）

補上 #9 (b)「day2、day3 各約 600 筆」的依據，以及 #1 (b) 的金額例子 `13100.0`（見本節末）。執行：`python3 -I q.py LionDEExam/candidate_package/dataset`（在 `LionTest/`）。

```python
import csv, sys
d=sys.argv[1]
ids=lambda f:[r["order_id"] for r in csv.DictReader(open(f"{d}/{f}",encoding="utf-8-sig"))]
base=set(ids("orders_base.csv"))
for day in ("day1","day2","day3"):
    rows=ids(f"orders_incremental_{day}.csv")
    print(day, "rows_in_base=", sum(i in base for i in rows), "distinct=", len({i for i in rows if i in base}))
```

輸出：

```
day1 rows_in_base= 603 distinct= 597
day2 rows_in_base= 602 distinct= 599
day3 rows_in_base= 603 distinct= 598
```

`13100.0` 的出處（在 `LionTest/` 執行，截前 80 字元）：

```
$ grep -n "13100.0" LionDEExam/candidate_package/dataset/orders_incremental_day1.csv | head -1 | cut -c1-80
2:ORD00102010,M002283,P00096,app,created,2,TWD,13100.0,500.0,2026-07-01T05:51:32
```

## E12｜Delta MERGE 來源同 key 多列、CSV `enforceSchema`、換算乘法的型別（#9、#1、#4）

驗收時發現報告原本寫「MERGE 來源同一個 `order_id` 有多列會直接報錯」不完整，用小資料重測；同一支腳本也測 #1 (c) 的 `enforceSchema` 與 #4 (c) 乘法的型別。執行：在 `LionTest/` 用 `uv run python /tmp/partb_e12/e12.py LionDEExam/candidate_package/dataset 2>/dev/null`（pyspark 4.2.0、delta-spark 4.4.1，預設 ANSI 開啟）。

```python
"""E12：(1) Delta MERGE 來源同 key 多列的行為；(2) header＋自訂 schema 時 enforceSchema 的行為；(3) #4 換算乘法的型別。用法：uv run python e12.py <dataset 目錄>"""
import shutil, sys, tempfile, delta, pyspark
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import StructType, StructField, StringType, DecimalType
from delta import configure_spark_with_delta_pip
from delta.tables import DeltaTable
spark = configure_spark_with_delta_pip(SparkSession.builder.master("local[1]").config("spark.ui.enabled", "false")
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")).getOrCreate()
spark.sparkContext.setLogLevel("OFF")
print("pyspark", pyspark.__version__, "delta-spark", __import__("importlib.metadata").metadata.version("delta-spark"), "ansi", spark.conf.get("spark.sql.ansi.enabled"))

# (1) MERGE：target 有 O1；來源 O1 兩列（對到既有列）、O9 兩列（target 沒有）
sch = "order_id string, order_status string, updated_at string, amount_twd int"
def run(label, src_rows):
    path = tempfile.mkdtemp() + "/fact"
    spark.createDataFrame([("O1", "paid", "T1", 500)], sch).write.format("delta").save(path)
    src = spark.createDataFrame(src_rows, sch)
    try:
        (DeltaTable.forPath(spark, path).alias("t").merge(src.alias("s"), "t.order_id = s.order_id")
            .whenMatchedUpdateAll(condition="s.updated_at > t.updated_at")
            .whenNotMatchedInsertAll().execute())
        print(f"[1] {label}: 成功", sorted(tuple(r) for r in spark.read.format("delta").load(path).collect()))
    except Exception as e:
        print(f"[1] {label}: 錯誤", str(e).splitlines()[0][:110])
    shutil.rmtree(path.rsplit("/", 1)[0])
run("來源 O1 兩列（target 已有 O1）", [("O1", "completed", "T2", 500), ("O1", "completed", "T3", 500)])
run("來源 O9 兩列（target 沒有 O9）", [("O9", "paid", "T2", 100), ("O9", "paid", "T3", 100)])

# (2) enforceSchema：day1 實際檔（UTF-8 BOM 表頭），以及欄位順序對調的小檔
d = sys.argv[1]
names = ["order_id", "member_id", "product_id", "channel", "order_status", "quantity", "currency",
         "amount", "coupon_discount", "order_created_at", "departure_date", "updated_at"]
schema = StructType([StructField(n, DecimalType(18, 2) if n in ("amount", "coupon_discount") else StringType()) for n in names])
for enforce in ("true", "false"):
    try:
        df = (spark.read.option("header", True).option("mode", "FAILFAST").option("enforceSchema", enforce)
              .schema(schema).csv(f"{d}/orders_incremental_day1.csv"))
        print(f"[2] day1 enforceSchema={enforce}: 列數", df.count(), "第一列", tuple(df.first())[:8])
    except Exception as e:
        print(f"[2] day1 enforceSchema={enforce}: 錯誤", str(e).splitlines()[0][:140])
tmp = tempfile.mkdtemp()
with open(f"{tmp}/swap.csv", "w", encoding="utf-8-sig") as f:   # 表頭把 amount 與 coupon_discount 對調
    f.write("order_id,coupon_discount,amount\nO1,500.0,13100.0\n")
s3 = StructType([StructField("order_id", StringType()), StructField("amount", DecimalType(18, 2)),
                 StructField("coupon_discount", DecimalType(18, 2))])
for enforce in ("true", "false"):
    try:
        df = spark.read.option("header", True).option("mode", "FAILFAST").option("enforceSchema", enforce).schema(s3).csv(f"{tmp}/swap.csv")
        print(f"[2] 欄位對調 enforceSchema={enforce}:", [r.asDict() for r in df.collect()])
    except Exception as e:
        msg = next((l for l in str(e).splitlines() if "header" in l.lower()), str(e).splitlines()[0])
        print(f"[2] 欄位對調 enforceSchema={enforce}: 錯誤", msg.strip()[:160])
shutil.rmtree(tmp)

# (3) #4 乘法：無 schema 時 amount、rate_to_twd 都是字串
r = spark.createDataFrame([("TWD", "100.0", None), ("USD", "100.0", "31.403")], "currency string, amount string, rate_to_twd string")
cases = {
    "字串 * 字串": F.col("amount") * F.col("rate_to_twd"),
    "decimal * double": F.col("amount").cast("decimal(18,2)") * F.col("rate_to_twd").cast("double"),
    "when(lit(1)).otherwise(字串)": F.col("amount").cast("decimal(18,2)") * F.when(F.col("currency") == "TWD", F.lit(1)).otherwise(F.col("rate_to_twd")),
    "兩邊都先 cast decimal": F.col("amount").cast("decimal(18,2)") * F.when(F.col("currency") == "TWD", F.lit(1).cast("decimal(18,6)")).otherwise(F.col("rate_to_twd").cast("decimal(18,6)")),
}
for label, expr in cases.items():
    try:
        x = r.select(expr.alias("t"))
        print(f"[3] {label}: 型別 {x.schema[0].dataType.simpleString()} 值 {[row[0] for row in x.collect()]}")
    except Exception as e:
        print(f"[3] {label}: 錯誤", str(e).splitlines()[0][:110])
spark.stop()
```

輸出：

```
pyspark 4.2.0 delta-spark 4.4.1 ansi true
[1] 來源 O1 兩列（target 已有 O1）: 錯誤 [DELTA_MULTIPLE_SOURCE_ROW_MATCHING_TARGET_ROW_IN_MERGE] Cannot perform Merge as multiple source rows matched 
[1] 來源 O9 兩列（target 沒有 O9）: 成功 [('O1', 'paid', 'T1', 500), ('O9', 'paid', 'T2', 100), ('O9', 'paid', 'T3', 100)]
[2] day1 enforceSchema=true: 列數 4615 第一列 ('ORD00102010', 'M002283', 'P00096', 'app', 'created', '2', 'TWD', Decimal('13100.00'))
[2] day1 enforceSchema=false: 列數 4615 第一列 ('ORD00102010', 'M002283', 'P00096', 'app', 'created', '2', 'TWD', Decimal('13100.00'))
[2] 欄位對調 enforceSchema=true: [{'order_id': 'O1', 'amount': Decimal('500.00'), 'coupon_discount': Decimal('13100.00')}]
[2] 欄位對調 enforceSchema=false: 錯誤 Caused by: org.apache.spark.SparkIllegalArgumentException: CSV header does not conform to the schema.
[3] 字串 * 字串: 錯誤 [DATATYPE_MISMATCH.BINARY_OP_WRONG_TYPE] Cannot resolve "(amount * rate_to_twd)" due to data type mismatch: th
[3] decimal * double: 型別 double 值 [None, 3140.2999999999997]
[3] when(lit(1)).otherwise(字串): 錯誤 [CAST_INVALID_INPUT] The value '31.403' of the type "STRING" cannot be cast to "BIGINT" because it is malforme
[3] 兩邊都先 cast decimal: 型別 decimal(37,8) 值 [Decimal('100.00000000'), Decimal('3140.30000000')]
```

- `[1]` 結論：來源同 key 多列且對到目標既有列時報 `DELTA_MULTIPLE_SOURCE_ROW_MATCHING_TARGET_ROW_IN_MERGE`；目標沒有的 key 則**不報錯**，兩列都被 insert（O9 變成兩列）。所以 MERGE 前一定要先讓來源每個 key 只剩一列。
- `[2]` 結論：day1 實際檔（表頭含 UTF-8 BOM）在 `enforceSchema` 為 true 或 false 時都能正常讀取，列數 4615。表頭欄位對調時，`enforceSchema=true` 照位置套 schema，`amount` 和 `coupon_discount` 靜默互換；`enforceSchema=false` 報 `CSV header does not conform to the schema`。
- `[3]` 結論：ANSI 開啟時字串相乘報 `DATATYPE_MISMATCH`；decimal 乘 double 結果是 double；`when(F.lit(1))` 配字串匯率會被轉成 bigint 而報 `CAST_INVALID_INPUT`；兩邊都先 cast 成 decimal 才得到 decimal 結果，TWD（匯率 null）也正確算出 100。
