"""order_status：一步轉移表、可達性、跳過中間狀態。

期望值依 notes/part_a/order-state-machine.md 手寫，不從 TRANSITIONS 推導，
這樣推導（閉包）寫錯時測試才抓得到。
"""

from __future__ import annotations

import itertools

import pytest
from pipeline import order_status as os_
from pyspark.sql import functions as F

S = ("created", "paid", "cancelled", "completed")

# (from, to) → (可達, 跳過中間狀態)；寫死
EXPECTED = {
    ("created", "created"): (True, False),
    ("created", "paid"): (True, False),
    ("created", "cancelled"): (True, False),
    ("created", "completed"): (True, True),
    ("paid", "created"): (False, False),
    ("paid", "paid"): (True, False),
    ("paid", "cancelled"): (True, False),
    ("paid", "completed"): (True, False),
    ("cancelled", "created"): (False, False),
    ("cancelled", "paid"): (False, False),
    ("cancelled", "cancelled"): (True, False),
    ("cancelled", "completed"): (False, False),
    ("completed", "created"): (False, False),
    ("completed", "paid"): (False, False),
    ("completed", "cancelled"): (False, False),
    ("completed", "completed"): (True, False),
}


@pytest.fixture(scope="module")
def evaluated(spark):
    """16 種組合＋未知值、NULL，一次算完：{(from, to): (reachable, skips)}。"""
    pairs = list(itertools.product(S, S)) + [
        ("created", "PAID"),
        ("Paid", "completed"),
        (None, "paid"),
        ("paid", None),
    ]
    df = spark.createDataFrame(pairs, "f string, t string")
    rows = df.select(
        "f",
        "t",
        os_.reachable(F.col("f"), F.col("t")).alias("r"),
        os_.skips_intermediate(F.col("f"), F.col("t")).alias("s"),
    ).collect()
    return {(r.f, r.t): (r.r, r.s) for r in rows}


@pytest.mark.parametrize(("pair", "expected"), sorted(EXPECTED.items()))
def test_order_status_reachable_and_skip(evaluated, pair, expected):
    assert evaluated[pair] == expected


@pytest.mark.parametrize(
    "pair", [("created", "PAID"), ("Paid", "completed"), (None, "paid"), ("paid", None)]
)
def test_order_status_unknown_or_null_is_false_not_null(evaluated, pair):
    # 未知值與 NULL 一律 False（不是 NULL），呼叫端 filter 時不會悄悄漏掉
    assert evaluated[pair] == (False, False)


def test_order_status_python_sets_match_table():
    assert os_.REACHABLE == {p for p, (r, _) in EXPECTED.items() if r}
    assert os_.SKIPS == {p for p, (_, s) in EXPECTED.items() if s}


def test_order_status_is_known_status(spark):
    df = spark.createDataFrame(
        [
            ("created",),
            ("paid",),
            ("cancelled",),
            ("completed",),
            ("PAID",),
            ("",),
            (None,),
        ],
        "s string",
    )
    got = [r.k for r in df.select(os_.is_known_status(F.col("s")).alias("k")).collect()]
    assert got == [True, True, True, True, False, False, False]
