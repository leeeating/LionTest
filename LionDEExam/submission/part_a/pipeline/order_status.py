"""訂單狀態機的 domain 定義：合法的一步轉移、可達性、是否跳過中間狀態。

規則來源：notes/part_a/order-state-machine.md（使用者假設訂單流程單向：取消後不能恢復、
completed 之後不能取消）與 process-log「狀態檢查一律用可達性，不用一步轉移表」。

- 唯一一份規則是 TRANSITIONS（一步轉移）。可達性 REACHABLE 由它推導（自反遞移閉包），
  不另外手寫，改規則只要改 TRANSITIONS。
- 對外提供回傳 Spark Column 的函式（reachable、skips_intermediate、is_known_status），
  在 JVM 內計算，不用 Python UDF。

自我轉移（X → X）：視為可達（走 0 步），也就是 no-op。同一狀態連續出現是重送或快照
重拍，不是狀態改變，所以不算不合法，也不算跳過中間狀態。

STATUSES 是 order_status 允許值的唯一一份定義：contracts.ORDERS_SCHEMA 直接引用它，
不在 4 種之內的列（拼錯、大小寫不同）在 cast_to_contract 就以「值不在允許範圍」隔離。
這裡的函式對未知值或 NULL 一律回傳 False（不可達、不是跳過），不回傳 NULL，
所以萬一有未知值繞過合約，狀態機也會把它當成不合法，不會悄悄寫進 fact。
"""

from __future__ import annotations

from functools import reduce

from pyspark.sql import Column
from pyspark.sql import functions as F

CREATED = "created"
PAID = "paid"
CANCELLED = "cancelled"
COMPLETED = "completed"

STATUSES: tuple[str, ...] = (CREATED, PAID, CANCELLED, COMPLETED)

# 合法的一步轉移（唯一一份規則）
TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (CREATED, PAID),
        (CREATED, CANCELLED),
        (PAID, CANCELLED),
        (PAID, COMPLETED),
    }
)


def _closure(
    statuses: tuple[str, ...], steps: frozenset[tuple[str, str]]
) -> frozenset[tuple[str, str]]:
    """自反遞移閉包：from 走 0 步以上能到 to。"""
    reach = {(s, s) for s in statuses} | set(steps)
    changed = True
    while changed:
        changed = False
        for a, b in list(reach):
            for c, d in list(reach):
                if b == c and (a, d) not in reach:
                    reach.add((a, d))
                    changed = True
    return frozenset(reach)


# 可達（含自我轉移）
REACHABLE: frozenset[tuple[str, str]] = _closure(STATUSES, TRANSITIONS)

# 可達、但不是一步轉移、也不是自我轉移：中間至少一個狀態沒有被觀察到
SKIPS: frozenset[tuple[str, str]] = frozenset(
    (a, b) for a, b in REACHABLE if a != b and (a, b) not in TRANSITIONS
)


def _pair_in(
    from_col: Column, to_col: Column, pairs: frozenset[tuple[str, str]]
) -> Column:
    """(from, to) 是否在 pairs 裡；任一邊是 NULL 或未知值時為 False（不是 NULL）。"""
    conds = [(from_col == a) & (to_col == b) for a, b in sorted(pairs)]
    if not conds:
        return F.lit(False)
    return F.coalesce(reduce(lambda x, y: x | y, conds), F.lit(False))


def is_known_status(col: Column) -> Column:
    """狀態值是否在 STATUSES 之內；NULL 為 False。"""
    return F.coalesce(col.isin(*STATUSES), F.lit(False))


def reachable(from_col: Column, to_col: Column) -> Column:
    """from 能否走到 to（0 步以上，含 X → X）。"""
    return _pair_in(from_col, to_col, REACHABLE)


def skips_intermediate(from_col: Column, to_col: Column) -> Column:
    """是否跳過中間狀態：可達，但不是一步轉移也不是自我轉移（例如 created → completed）。"""
    return _pair_in(from_col, to_col, SKIPS)
