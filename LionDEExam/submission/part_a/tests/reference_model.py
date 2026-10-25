"""測試用的獨立參考實作：用純 Python csv＋Decimal 依定案規則重算每批的對帳數字。

不 import pipeline 的任何東西，所以和被測的 Spark 實作互相獨立；
test_fact_order.py（base）與 test_fact_order_incremental.py（base → day3）共用。

依序：合約（金額必須大於 0，V1；coupon 不可為 -1 以外的負數）→ coupon -1.0 轉 NULL（V3）
→ 同批撞號（ADR-03）
→ 完全重複（只算時間上相鄰的相同列）→ 與既有 fact 撞號 → 狀態機（晚到用可達性、
逐段用可達性、同一秒不同狀態、不合法之後一起隔離）→ 匯率 → 會員對不到版本隔離
→ product -1、net_amount_twd、
金額人工確認清單（比值 > 100，或 coupon > amount_twd；同一列只算一次）。
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

TPE = dt.timezone(dt.timedelta(hours=8))
CENT = Decimal("0.01")
DATASET_DIR = (
    Path(__file__).resolve().parents[2].parent / "candidate_package" / "dataset"
)
FILES = [
    ("base", "orders_base.csv"),
    ("day1", "orders_incremental_day1.csv"),
    ("day2", "orders_incremental_day2.csv"),
    ("day3", "orders_incremental_day3.csv"),
]
# 可達（含自己）：依 notes/part_a/order-state-machine.md 手寫
REACH = {
    ("created", "created"),
    ("created", "paid"),
    ("created", "cancelled"),
    ("created", "completed"),
    ("paid", "paid"),
    ("paid", "cancelled"),
    ("paid", "completed"),
    ("cancelled", "cancelled"),
    ("completed", "completed"),
}
SKIP = {("created", "completed")}
REVIEW_RATIO = Decimal(100)


def read_csv(name):
    with open(DATASET_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def ts(s):
    """三種來源時間格式：+08:00、Z（UTC）、無時區（台北）。"""
    if "/" in s:
        return dt.datetime.strptime(s, "%Y/%m/%d %H:%M:%S").replace(tzinfo=TPE)
    return dt.datetime.fromisoformat(s)


def identity(r):
    return (r["member_id"], ts(r["order_created_at"]), Decimal(r["amount"]))


def content(r):
    """除了 updated_at 以外的內容；下單時間比較換算後的時刻，不比較字串。"""
    return tuple(
        ts(v) if k == "order_created_at" else v
        for k, v in r.items()
        if k != "updated_at"
    )


def _raw_key(r):
    return tuple(r.values())


def dedupe_adjacent(rows):
    """回傳 (保留的列, 重複列數)。同一個 updated_at 算一組；只有一種內容的組才去重：
    組內留最後一列，下一組內容相同（也是純組）時整組算重複。"""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[ts(r["updated_at"])].append(r)
    ordered = [sorted(groups[k], key=_raw_key) for k in sorted(groups)]
    kept, dups = [], 0
    for i, g in enumerate(ordered):
        contents = {content(r) for r in g}
        if len(contents) > 1:
            kept.extend(g)
            continue
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        if nxt and {content(r) for r in nxt} == contents:
            dups += len(g)
            continue
        dups += len(g) - 1
        kept.append(g[-1])
    return kept, dups


def chain(rows, fact_status):
    """比 fact 新的事件：回傳 ({id(row): 分類}, 接受的列, 是否跳過中間狀態)。"""
    out, legal = {}, []
    by_ts = collections.defaultdict(list)
    for r in rows:
        by_ts[ts(r["updated_at"])].append(r)
    cur, seg_from, broken = None, None, False
    for t in sorted(by_ts):
        grp = by_ts[t]
        statuses = {r["order_status"] for r in grp}
        if broken:
            out.update({id(r): "after_illegal" for r in grp})
            continue
        if len(statuses) > 1:
            out.update({id(r): "ambiguous_order" for r in grp})
            broken = True
            continue
        (s,) = statuses
        if s != cur:
            seg_from = cur if cur is not None else fact_status
            cur = s
        if seg_from is not None and (seg_from, s) not in REACH:
            out.update({id(r): "illegal_transition" for r in grp})
            broken = True
            continue
        legal.extend((t, _raw_key(r), r, (seg_from, s) in SKIP) for r in grp)
    if not legal:
        return out, None, False
    legal.sort(key=lambda x: (x[0], x[1]))
    *older, (_, _, kept, skip) = legal
    out.update({id(r): "superseded" for _, _, r, _ in older})
    return out, kept, skip


def reference():
    """回傳 ({batch_id: 對帳數字, "amount_totals": 金額總和兩個數字}, 最後的 fact {order_id: (列, amount_twd, net)})。"""
    fx = {
        (r["rate_date"], r["currency"]): Decimal(r["rate_to_twd"])
        for r in read_csv("fx_rates.csv")
    }
    products = {r["product_id"]: r for r in read_csv("products.csv")}
    register = {}
    for m in read_csv("members.csv"):
        register[m["member_id"]] = min(
            register.get(m["member_id"], "9999"), m["register_date"]
        )
    fact = {}
    result = {}
    review_ids = set()  # 曾列進金額人工確認清單的 order_id（任一批）
    for batch, name in FILES:
        rows = read_csv(name)
        cats = collections.Counter()
        valid = []
        for r in rows:
            c = r["coupon_discount"]
            bad_coupon = c not in ("", None) and Decimal(c) < 0 and Decimal(c) != -1
            if Decimal(r["amount"]) <= 0 or bad_coupon:
                cats["contract"] += 1
                continue
            valid.append(r)
        accepted = []
        groups = collections.defaultdict(list)
        for r in valid:
            groups[r["order_id"]].append(r)
        for oid, rs in groups.items():
            if len({identity(r) for r in rs}) > 1:
                cats["collision"] += len(rs)
                continue
            rs, dups = dedupe_adjacent(rs)
            cats["duplicate"] += dups
            f = fact.get(oid)
            if f and identity(f[0]) != identity(rs[0]):
                cats["collision_existing"] += len(rs)
                continue
            f_status = f[0]["order_status"] if f else None
            f_ts = ts(f[0]["updated_at"]) if f else None
            newer = []
            for r in rs:
                if f and ts(r["updated_at"]) <= f_ts:
                    ok = (r["order_status"], f_status) in REACH
                    cats["late_event" if ok else "late_event_conflict"] += 1
                else:
                    newer.append(r)
            out, kept, skip = chain(newer, f_status)
            cats.update(out.values())
            if kept is not None:
                accepted.append((kept, skip))
        n = collections.Counter()
        total = net_total = Decimal(0)
        for r, skip in accepted:
            day = ts(r["order_created_at"]).astimezone(TPE).date().isoformat()
            rate = (
                Decimal(1)
                if r["currency"] in ("TWD", "NTD")
                else fx.get((day, r["currency"]))
            )
            if rate is None:
                cats["fx_missing"] += 1
                continue
            twd = (Decimal(r["amount"]) * rate).quantize(CENT, ROUND_HALF_UP)
            coupon = r["coupon_discount"]
            nulled = coupon not in ("", None) and Decimal(coupon) == Decimal(-1)
            if nulled:  # V3：-1.0 代表未知，轉 NULL
                coupon = None
            net = twd - Decimal(coupon) if coupon not in ("", None) else None
            reg = register.get(r["member_id"])
            if reg is None or day < reg:  # 會員對不到版本：進隔離表，不落 -1
                cats["member_missing"] += 1
                continue
            fact[r["order_id"]] = (r, twd, net)
            n["fact"] += 1
            total += twd
            net_total += net or 0
            p = products.get(r["product_id"])
            n["unknown_p"] += p is None
            n["skip"] += skip
            n["coupon"] += nulled
            review = net is not None and net < 0
            if p is not None and p["base_price_twd"]:
                denom = Decimal(p["base_price_twd"]) * int(r["quantity"])
                if denom > 0 and (twd / denom).quantize(CENT) > REVIEW_RATIO:
                    review = True
            n["review"] += review
            if review:
                review_ids.add(r["order_id"])
        skipped = cats.pop("late_event", 0)
        result[batch] = {
            "input_rows": len(rows),
            "fact_rows": n["fact"],
            "quarantined_rows": sum(cats.values()),
            "skipped_rows": skipped,
            "quarantined_by_category": {k: v for k, v in cats.items() if v},
            "skipped_intermediate_rows": n["skip"],
            "coupon_nulled_rows": n["coupon"],
            "amount_review_rows": n["review"],
            "amount_twd_sum": total,
            "net_amount_twd_sum": net_total,
            "unknown_product_rows": n["unknown_p"],
            "unknown_member_rows": cats.get("member_missing", 0),
            "fact_table_rows": len(fact),
            "fact_table_amount_twd_sum": sum(t for _, t, _ in fact.values()),
            "fact_table_net_amount_twd_sum": sum(
                x for _, _, x in fact.values() if x is not None
            ),
        }
    # V2（B1）：fact 的 amount_twd 總和（所有狀態、折扣前），以及排除曾列進清單的訂單後的總和
    result["amount_totals"] = {
        "amount_twd_total": sum(t for _, t, _ in fact.values()),
        "amount_twd_excluding_review": sum(
            t for oid, (_, t, _) in fact.items() if oid not in review_ids
        ),
        "review_orders": sum(oid in review_ids for oid in fact),
    }
    return result, fact
