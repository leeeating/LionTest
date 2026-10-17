"""增量檔與 base 撞號的列：各欄「實際相同的列數」對照「隨機配對的期望列數」。

用法（repo 根目錄）：python3 -I LionDEExam/submission/part_a/profiling/collision_expected_match.py LionDEExam/candidate_package/dataset
期望值 = Σ_k P_增量(k) × P_base(k) × n，即兩邊各自的值分布不變、隨機配對時碰巧相同的列數。
"""
import csv
import sys
from collections import Counter

d = sys.argv[1]


def load(name):
    with open(f"{d}/{name}", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


base = {}
for r in load("orders_base.csv"):
    base.setdefault(r["order_id"], r)  # base 每個 id 取一列，避免 V7 的重複列

for day in ("day1", "day2", "day3"):
    inc = [r for r in load(f"orders_incremental_{day}.csv") if r["order_id"] in base]
    n = len(inc)
    print(f"[{day}] 與 base 撞號 {n} 列")
    for col in ("member_id", "amount", "order_created_at", "currency", "channel", "order_status"):
        obs = sum(r[col] == base[r["order_id"]][col] for r in inc)
        p_inc = Counter(r[col] for r in inc)
        p_base = Counter(base[r["order_id"]][col] for r in inc)
        exp = sum(p_inc[k] * p_base[k] for k in p_inc) / n
        print(f"  {col:17s} 實際相同 {obs:4d}   隨機配對的期望 {exp:7.1f}")
