# Process Log｜Part B

## B-01｜buggy_pipeline.py 審查報告
- Part：B
- Session：3b7e0f96，2026-10-09
- 產出檔：`submission/part_b/code-review.md`

### 0. 你先看
使用者沒有先讀程式碼。AI 先依專案規則請使用者自己讀，並提供一套通用讀法（未讀檔，只列四個檢查問題：重跑會怎樣、哪些列會消失、數字對不對、SCD2 完不完整）。使用者回覆「你應該先產出一份報告我在檢查」，決定改由 AI 先產初稿，使用者負責檢查。

### 1. 拆解
- AI：讀程式碼、用資料查詢量化每個問題的影響、寫初稿。
- 使用者：逐條檢查初稿、決定採用與否、改寫結論。

### 2. 委派
> 你應該先產出一份報告我在檢查（使用者原話）

AI 在主對話直接讀檔並撰寫，沒有派 subagent。

### 3. 驗證
- 程式本身不執行（題目要求不執行原管線）。撰寫初稿時用系統 python3 檢查，沒有 pyspark（當時 `ModuleNotFoundError: No module named 'pyspark'`）；第三輪修正時另在 `.venv`（pyspark 4.2＋delta-spark）用小資料驗證關鍵語意，見下方「第三輪驗收的重算與 pyspark 語意驗證（B-01.7）」。`python3 -m py_compile` → 語法 OK。
- 「業務影響」的筆數用 Python 標準庫 csv 直接讀 `candidate_package/dataset/` 算出，主要輸出：
  - fx_rates 幣別只有 `['JPY', 'USD']`；day1 對不到匯率的筆數 3069，正好等於 TWD 筆數 3069（4615 筆中）→ 第 1 點
  - day1 有 597 個 order_id 已經存在於 orders_base，其中 485 筆狀態有變（603 列）；day2 有 25 筆在 day1 出現過 → 第 3 點
  - members 8991 列、8000 人，989 人有多筆快照；day1 因一對多多出 571 列 → 第 4 點
  - day1 有 18 個重複 order_id，`updated_at` 18 組都不同，其中 3 組的 `order_created_at`、`amount` 也不同；ORD00036457 同時有 completed 和 cancelled → 第 5 點
  - 多快照會員中 `member_level` 有變的 434 人、`city` 有變的 376 人 → 第 6 點
  - orders_base `amount<=0` 有 50 筆，三個增量檔都是 0 筆 → 第 7 點
- 獨立審查：fresh-context 驗收 agent 已跑三輪（都是「有條件過」），修正見步驟 4 的 B-01.4、B-01.5、B-01.7。〔進行中〕使用者尚未檢查定稿。

#### 查詢程式碼
B-01.4 修正時重寫的重算腳本，涵蓋報告 #1、#3～#7 的主要數字。dataset 是 UTF-8 BOM，用 `encoding="utf-8-sig"` 讀；腳本放在 dataset 以外的目錄，以 `python3 -I partb_queries.py candidate_package/dataset` 執行。

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

上面輸出的「撞號」是腳本當時的標籤，B-01.5 已改為「與官方語意不符的現象，需向上游確認」，數字不變。

#### 第二輪驗收的重算腳本（B-01.5）
重算 #2、#3、#4 的新數字，並查 #3 的 603 列與 base 的三欄比對。以 `python3 -I recheck.py candidate_package/dataset` 執行。

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

#### 第三輪驗收的重算與 pyspark 語意驗證（B-01.7）
腳本放在 dataset 以外的暫存目錄（`/tmp/partb_r3/`），2026-10-10 執行。原管線不執行，pyspark 只跑自建小資料（以及 day1 檔案的單一 filter）。

**(a) 重算 #6 初始載入、#12 金額最小值、#3 order_date 範圍**：`python3 -I recheck3.py candidate_package/dataset`

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

**(b) orders_base 與第一版 valid_from 的比較**：`python3 -I base_check.py candidate_package/dataset`

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

**(c) 三項語意（#5 dropDuplicates＋window、#2 replaceWhere 清表、#12 隱式轉型的 explain）**：在 `LionTest/` 執行 `uv run python /tmp/partb_r3/spark_semantics.py 2>/dev/null`（Spark log 走 stderr，故丟掉）

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

**(d) ANSI 逐值測試與 day1 實際檔案**：`uv run python /tmp/partb_r3/ansi_each.py LionDEExam/candidate_package/dataset 2>/dev/null`。另以 `s.conf.get('spark.sql.ansi.enabled')` 確認 pyspark 4.2 預設為 `true`；三個增量檔不含小數點的 `amount` 列數都是 0（day1 4615、day2 4700、day3 4615 列）。

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

**(e) ruff 靜態分析（4.6）**：`buggy_pipeline.py` 已由使用者從原始 zip 還原（179 行）。專案沒有 ruff 設定檔，用預設規則。

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

### 4. 修正
- B-01.1｜初稿第 9 點寫「`amount_twd - coupon_discount` 可能幣別不一致，待確認」→ 錯。`candidate_package/README.md` 已明寫 `coupon_discount（TWD）`，相減是對的；AI 寫初稿時沒先讀 README。發現者：AI 自查（寫 B-02 讀 README 時發現）。修正：刪除該點，後面各點的編號往前遞補（共 12 點）。證據：README「欄位說明」段。
- B-01.2｜初稿一開始就列問題，沒說明這支程式的用途 → 使用者要求 code review 先說明檔案的用處。發現者：使用者。修正：在結論前加一節「這支程式在做什麼」，內容是用途、mermaid 流程圖，以及 6 個步驟各自讀什麼、寫什麼的對照表（附各步驟對應的函式）。
- B-01.3｜報告原本是依嚴重度排列的 12 點條列清單 → 使用者說明繳交報告應是「完整的有結構的文件，類似小論文」，並選擇論文式七節大綱。發現者：使用者。修正：改寫為 摘要／背景／方法／發現（依主題分 4.1～4.5，每小節先論述共同成因再逐項 (a)(b)(c)）／修正建議（含優先順序）／結論／附錄問題總表（原編號 → 小節對照）。內容與數字沿用前一版。
- B-01.4｜獨立審查找出以下內容錯誤與漏報。發現者：驗收 agent（fresh-context 審查）。修正如下，數字都以步驟 3「查詢程式碼」的輸出重算：
  - #5 舉例：原本用 `ORD00036457`（completed 與 cancelled）當「狀態更新、可能留錯列」的例子 → 錯，它是 3 組撞號之一（另兩組 ORD00047034、ORD00076774），兩列的 `order_created_at`、`member_id`、`amount` 都不同，和後文「3 組撞號」自相矛盾。重查其餘 15 組正常重複，全部只有 `updated_at` 不同、狀態相同，沒有狀態不同的例子。改成用 `ORD00005192`（兩列都是 completed，`updated_at` 差 26 秒）說明「保留哪列不確定」；撞號改用 ORD00036457 等 3 組舉例。同步修 `notes/part_b/dedup.md`。
  - #2 影響：原本寫「之後每天執行，表只會越縮越小」→ 錯。每次執行是把整張 dim 換成當天有變更的會員；同一份 members 第二次跑時 `changed` 為空，dim 被清成 0 列，沒有變更的那天也一樣。「8,000 人」改標為假設 dim 初始已有全部會員。
  - #4 影響：原本寫「`member_level` 會隨機取到新版或舊版」→ 錯，一對多 join 不是擇一，而是每個快照各產生一列，同時帶著不同的 `member_level`。
  - #6 漏報：原本沒寫 `members` 的 (member_id, extract_date) 有 30 組重複，其中 28 組落在該會員最新的 `extract_date`、兩列 `member_level` 都不同，而 `update_dim_member` 中 `Window.partitionBy("member_id").orderBy(F.col("extract_date").desc())` 的 `row_number` 只依 `extract_date` 排序，同分會任意挑一列。補進 (a)(b)，(c) 加上同分處理（送隔離表；次排序鍵為替代方案），修正程式碼加上同分偵測。
  - #3 單位混用：原本寫「597 個 order_id，其中 485 筆狀態有變」→ 597 是 order_id 數、485 是列數。改成「597 個 order_id（603 列）中 485 列狀態和 base 不同」（485 列涉及 480 個 order_id）。同步修 `notes/dataset/dictionary.md`。
  - #3 修正前提：原本第 5 節寫「#3 與 #5 一起修（MERGE 需要先正確去重）」→ 不完整，Delta MERGE 來源同一個 key 有多列會報錯，#4 的一對多 join 也會造成重複。改成「#3 需要 #4 和 #5 先修好」，#3 (c) 的附註同步補上。
  - #6 null 比較：原本只寫 `!=` 遇 null 會漏掉變更 → 補註 dataset 的 city 沒有空值，缺值用字串 `N/A`（71 筆），這是程式碼層面的風險，且 `N/A` 本身會被當成「變更」。#10 (a) 補上「第一次執行時 dim_member 不存在，`update_dim_member` 開頭的 `dim = spark.read.format("delta").load(f"{LAKEHOUSE}/dim/dim_member")` 會直接失敗，程式沒有初始化步驟」，(c) 補建立空表。
- B-01.5｜第二輪獨立審查找出 4 點錯誤，外加一處 #3 與 #5 的矛盾。發現者：驗收 agent（fresh-context 第二輪）。修正如下，新數字見步驟 3「第二輪驗收的重算腳本」的輸出：
  - #4／#6 point-in-time join 邊界日重複配對：原本 #4 (c) 寫 `order_date BETWEEN valid_from AND valid_to`（兩端都包含），而 #6 的程式碼把舊版的 `valid_to` 和新版的 `valid_from` 都設成 `extract_date`，快照日當天的訂單會同時對到新舊兩版 → 錯。統一改成半開區間 `valid_from <= order_date < valid_to`，#4 (c) 文字、#6 程式碼註解、`notes/part_b/scd2.md` 一致。
  - #2「第二次跑會清成 0 列」說得太絕對：有 28 位會員在最新的 `extract_date` 有兩筆快照（同分），`row_number` 每次跑都可能挑到不同的列，可能再被判定為有變更 → 改成「幾乎清空」並寫明原因，與 #6 (b)「同樣的輸入重跑可能寫進不同的等級」一致。輸出：`[#2] 最新 extract_date 同分會員=28`。
  - #4「多出 571 列」沒有註明前提：571 是用 day1 原始 4,615 列（尚未去重、TWD 未丟）算的 → 補上前提，並附另兩種情境的重算：#1、#5 已修（4,597 列）多出 569 列；照現行管線順序（`dropDuplicates` 後再被匯率 inner join 丟掉 TWD，進入 join 的 1,536～1,538 列）多出 182～183 列。同步修 `notes/dataset/dictionary.md`。
  - #3 兩件事混在一起寫：原本寫 485 列狀態不同「金額重複計算，狀態統計也錯」，讀起來像只有 485 列重複計算 → 改成分開寫：append 下 603 列的金額**全部**重複計算；其中 485 列狀態和 base 不同，只額外影響狀態統計。
  - #3 與 #5 的 order_id 語意矛盾：#5 以「`order_created_at`、`member_id`、`amount` 不同就可能是撞號」為判準，但重算發現 day1 和 base 同 order_id 的 603 列，這三欄沒有一列和 base 相同（輸出：`三欄全同=0; 單欄相同列數={'order_created_at': 0, 'member_id': 0, 'amount': 0}`，例 `ORD00005192` base 是 05-06、M007765、10230.87，day1 是 05-04、M005173、6927），照同一判準 #3 的 603 列全部都該算撞號，和 #3「既有訂單的更新」互相矛盾 → #3、#5 都改成有條件的寫法（「官方 README 定義同一 order_id 以 `updated_at` 區分新舊；若照此語意，則……」），「三欄不一致」從「可能撞號」改成「與官方語意不符的現象，需向上游確認」，寫明同時出現在 #5 的 3 組與 #3 的 603 列，order_id 是否可作為唯一鍵留待 Part A 以 ADR 定案；結論補一句「不論哪種解讀，#1、#2、#4 都成立」，不可部署不變。另外 #3 原本寫「新列會依 `order_created_at` 落到舊的分區」→ 錯，新列的 `order_created_at` 和 base 不同，`order_date` 相同的只有 9 列（輸出：`order_date 與 base 相同的列=9`），改成「不一定落在原本那一列的分區」。同步修 `notes/part_b/dedup.md`、`notes/dataset/incremental.md`、`notes/dataset/dictionary.md`。
- B-01.6｜報告與筆記用行號（`L42`、`L86-118` 等）引用程式碼 → 使用者重新排版了 `buggy_pipeline.py`，行號全部錯位；使用者要求文件不再依賴行號。發現者：使用者。修正：所有行號改成「函式名稱＋可用 Ctrl+F 搜尋的程式碼片段」，片段從排版後的 `buggy_pipeline.py` 原樣複製；附錄總表「位置」欄改為「函式／片段」；刪除「179 行」這類行數描述；本紀錄 B-01.2、B-01.4 的行號同樣改成函式名稱。另外改掉幾處原本不是原文的引用（例如 `orders.currency == fx.currency` 改為原文 `orders["currency"] == fx["currency"]`、`replaceWhere "member_id IS NOT NULL"` 改為 `"replaceWhere", "member_id IS NOT NULL"`、`amount > 0` 改為 `filter(F.col("amount") > 0)`）。驗證：`grep -nE "\bL[0-9]+"` 在報告與筆記無結果；反引號片段逐一 `grep -cF` 檢查，搜不到的只剩檔案路徑、資料值、pipeline 沒有的欄位名與修正建議的程式碼。後續：使用者要求把 `buggy_pipeline.py` 從原始 zip 還原（179 行），還原後片段逐一重新 `grep -F`，都仍搜得到（見 B-01.7）。
- B-01.7｜第三輪獨立審查找出 4 個問題。發現者：驗收 agent（fresh-context 第三輪）。修正如下，新數字見步驟 3「第三輪驗收的重算與 pyspark 語意驗證」的輸出：
  - #6 修法會丟歷史：原本 #6 (c) 的 MERGE 每次只拿每位會員最新的 `extract_date`，沒寫初始載入；dim 從空表開始時，04-30、05-31 的舊快照永遠進不了 dim，和 #6 (b)「434 人等級變過」是 SCD2 該保存的歷史互相矛盾；搭配 #4 的半開區間 join，day1 去重後 4,597 張中有 49 張（48 位會員）`order_date` 早於該會員最新 `extract_date`，`member_level` 會變成 null（AI 重算確認 49）→ #6 (c) 新增「初始載入」：依 `extract_date` 由舊到新逐批 MERGE，或一次性回填全部快照，再接每日增量；列出第一版 `valid_from` 的三個選擇（第一筆 `extract_date`／`register_date`／很早的固定日期）與取捨，並附目前資料的檢查（三者在 day1、base 都是 0 張對不到）。#4 (c) 補「前提是 dim 已回填歷史」，#10 (c) 的「建立空表再走 MERGE」改成先回填。同步修 `notes/part_b/scd2.md`。
  - #12 沒寫隱式轉型的具體後果：原本只寫「格式一變會被靜默轉成 null」→ 補上 `filter(F.col("amount") > 0)` 的實際行為：ANSI 關閉時是 `cast(amount as int) > 0`，0.5 被截成 0 濾掉、`1,200` 轉 null 濾掉；ANSI 開啟（Spark 4 預設）時是 `cast(amount as bigint) > 0`，報 `CAST_INVALID_INPUT`。派工時預期「ANSI 開啟只有 0.5 這類值會報錯」，AI 實跑發現帶小數點的字串（包括 `100.0`）全部報錯，day1 實際檔案也報錯，所以「增量金額最小值 83.24，目前不影響數字」只在 ANSI 關閉時成立，報告照實寫。#7 (a) 補一句指向 #12 (b)；附錄 #12 描述同步。
  - 方法一節環境描述過時：原本寫「本機沒有 pyspark 與 delta（`ModuleNotFoundError`）」→ 改成題目要求不執行原管線，另在 `.venv`（pyspark 4.2＋delta-spark）用小資料驗證三項語意：`dropDuplicates` 之後套 window 沒有作用、`"replaceWhere", "member_id IS NOT NULL"` 搭配 overwrite 會清表（只寫 1 列 → 剩 1 列；寫 0 列 → 剩 0 列）、隱式轉型。步驟 3 的環境描述同步改。
  - #3「重跑一次，該日營收翻倍」→ 錯，day1 的 `order_created_at` 從 05-01 到 07-01（62 個 `order_date`），一個批次不是一天。改成「該批次的訂單金額翻倍（分散在多個 `order_date` 分區）」；結論的「重跑同一天，該天的資料」同步改成「同一個批次」。
  - 另外新增 4.6「靜態分析（linter）」，這一節是使用者要求的：附 ruff 指令與輸出原文；F841（`main()` 的 `dim_member = update_dim_member(members)` 沒被使用）對應 #4，UP009、I001 只是風格；結論是 linter 只抓到 12 個問題中 1 個的跡象。第 3 節方法加上 ruff，第 5 節加「CI 跑 ruff、F841 這類警告當錯誤」。
- B-01.8｜問題總表原本放在文末附錄 → 使用者要求放到最前面。發現者：使用者。修正：總表移到標題下、摘要之前，改名「問題總表」並附一行嚴重度定義；第 3 節「總表見附錄」改為「總表見文首」。
- B-01.9｜第四輪獨立審查找出 2 處內部矛盾。發現者：驗收 agent（fresh-context 第四輪）。修正如下：
  - 報告 #6 (c)「初始載入」與 #4 (c) 原本寫「逐批 MERGE 後 day1 去重後 0 張對不到」「照初始載入回填，就不會對不到」→ 錯：與同一節的同分隔離規則（`ambiguous`，本批不更新）互相矛盾。最新快照同分的 28 位會員都只有一個 `extract_date`，被隔離後永遠進不了 dim，所以 day1 去重後仍有 17 張訂單對不到任何版本。改成「不含被隔離的 28 位同分會員：day1 有 17 張對不到，要靠 #6 的隔離告警處理」；`notes/part_b/scd2.md`「目前資料 0 張」同步修改。AI 用 `python3 -I`（`encoding="utf-8-sig"`）重算確認，輸出：`ties 28 distinct extract_date count dist {1: 28}`、`day1 dedup 4597`、`orders of tie members 17`、`non-tie unmatched after stepwise MERGE 0`。
  - `notes/part_b/scd2.md` 王小明例子，故事寫「6 月升金卡」，表格金卡 `valid_from` 卻是 2026-05-31，依半開區間 5/31 的訂單會對到金卡，與「查 5 月的訂單得到銀卡」矛盾 → 故事改為「4/30 的快照是銀卡，5/31 的快照已經是金卡」，查詢例子改為 5/15 的訂單得銀卡、5/31 的訂單落在金卡那一列；SCD1 的說明同步改成 5/15。
- 〔進行中〕

### 5. 定案
〔待使用者撰寫〕

## B-02｜Dataset 資料字典
- Part：B（Part A 也會引用）
- Session：3b7e0f96，2026-10-10
- 產出檔：`submission/notes/dataset/`（README.md、dictionary.md、incremental.md）、`submission/notes/part_b/`（README.md、scd2.md、dedup.md）、`submission/notes/README.md`

### 0. 你先看
使用者沒有先看資料，直接請 AI「先針對 dataset 寫文件」。

### 1. 拆解
AI 提出兩個方向問題，使用者選了建議選項：
- 範圍：只寫資料字典，加上 Part B 已驗證的事實；完整的品質檢核留給 A-3，避免提前做掉 Part A。
- 位置：放 `submission/dataset-notes.md`，給各 Part 共用。

### 2. 委派
> 先針對dataset寫文件（使用者原話）

AI 在主對話用 Python csv 統計，沒有派 subagent。

### 3. 驗證
- 逐欄統計筆數、空值、值域，以及 key 是否唯一。主要輸出：所有檔案都有 BOM；空值 0；orders_base 有 100,040 列、100,000 個 order_id；base 的 currency 含 NTD 200 筆；base 的 `order_created_at` 有三種格式（+08:00 有 94,038 筆、`/` 有 3,001 筆、Z 有 3,001 筆）；base 有 120 筆 product_id 不在主檔；members 的 (member_id, extract_date) 重複 30 組；fx (rate_date, currency) 唯一。
- AI 自查：第一次統計 amount 用字串比大小（例如輸出 `min=100129.0 max=99863.0`），結果沒有意義。改成轉成 float 重算，文件中的數字都是重算後的值。
- 〔進行中〕尚未做獨立審查，也還沒經過使用者檢查。

### 4. 修正
- B-02.1｜AI 原本的關聯圖用 ASCII 畫 → 使用者要求改成 mermaid。發現者：使用者。修正：改成 mermaid `erDiagram`，在關係線上標出 join key 和兩個陷阱（會員多快照、TWD 沒有匯率）。
- B-02.2｜AI 原本寫「增量檔的 `updated_at` 落在批次日當天到其後 3 天內」→ 錯。day1 最晚到 07-05（批次日後 4 天），day2 有 6 列早於批次日。發現者：AI 自查（使用者要求記錄觀察時重新查詢）。修正：改寫成逐日分布表。證據：day1 `updated_at` 日期分布 {07-01: 1325, 07-02: 1428, 07-03: 1415, 07-04: 442, 07-05: 5}，晚於批次日 3,290 筆。
- B-02.3｜使用者問「增量檔是不是訂單的 log」，討論後要求把觀察記下來。新增一小節「增量檔的性質」：每列是完整快照、出現次數分布、疑似撞號、`updated_at` 約 70% 晚於批次日（原因不明，待 A-3）。發現者：使用者提問，AI 查詢。
- B-02.4｜觀察原本寫在 `dataset-notes.md` 內 → 使用者要求另開一份檔案。修正：把「增量檔的性質」整節移到 `submission/dataset-observations.md`，原處只留一行連結。
- B-02.5｜AI 把理解過程的筆記塞在同一檔（dataset-notes.md、dataset-observations.md），報告又是條列清單 → 使用者說明兩種文件要分開：理解問題的筆記分層多檔（先迅速了解一件事 → 問題 → 建議解法），繳交報告是小論文。發現者：使用者。修正：照使用者選的結構建立 `submission/notes/`（入口 README → dataset/、part_b/ 各自 README → 細節檔），把本 session 解釋過的 SCD2、去重整理成 `notes/part_b/scd2.md`、`dedup.md`；刪除舊的兩個檔案。
- 〔進行中〕

### 5. 定案
〔待使用者撰寫〕
