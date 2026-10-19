"""order_status_check：一批事件的狀態機分類（只驗 DataFrame，不寫 Delta）。

每張單用不同的 order_id 代表一種情境；期望分類手寫、寫死。
時間都是同一天（台北），只看時分。
"""

from __future__ import annotations

import collections
import datetime as dt

import pytest
from pipeline.order_status_check import (
    QUARANTINE_CATEGORIES,
    SKIP_CATEGORIES,
    STATE_CATEGORY_COL,
    STATE_REASON_COL,
    STATE_SKIPPED_COL,
    WRITE_CATEGORIES,
    StateCategory,
    classify_status_events,
    split_by_disposition,
)

C = StateCategory


def t(hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime(2026, 7, 1, hh, mm)


# 既有 fact：(order_id, order_status, updated_at)
FACT = [
    ("L4", "cancelled", t(10)),  # L4 的形狀：fact 已是 cancelled
    ("LATE_CONFLICT", "paid", t(10)),
    ("CHAIN", "created", t(8)),
    ("SKIP", "created", t(8)),
    ("BACK", "cancelled", t(8)),
    ("AFTER", "paid", t(8)),
    ("AMBIG", "created", t(8)),
    ("SAME", "created", t(8)),
    ("SKIPSEG", "created", t(8)),
    ("BADSTATUS", "paid", t(8)),
]

# 事件：(order_id, order_status, updated_at, note)；note 是本測試用的列代號
EVENTS = [
    # 晚到且可達：較舊的 paid 走得到 cancelled；與 fact 同一秒也算晚到
    ("L4", "paid", t(9), "l4_paid"),
    ("L4", "cancelled", t(10), "l4_same_ts"),
    # 晚到且矛盾：較舊的 cancelled 走不到 paid
    ("LATE_CONFLICT", "cancelled", t(9), "lc"),
    # 合法逐段：created → paid → cancelled
    ("CHAIN", "paid", t(9), "chain_paid"),
    ("CHAIN", "cancelled", t(10), "chain_cancelled"),
    # 跳過中間狀態：created → completed
    ("SKIP", "completed", t(9), "skip"),
    # 往回走：cancelled → paid
    ("BACK", "paid", t(9), "back"),
    # 不合法之後：paid → cancelled（合法）→ paid（往回）→ completed（單看 paid→completed
    # 會合法，但鏈已斷，一起隔離）
    ("AFTER", "cancelled", t(9), "after_ok"),
    ("AFTER", "paid", t(10), "after_bad"),
    ("AFTER", "completed", t(11), "after_next"),
    # 同一秒不同狀態：兩列都隔離，fact 不更新
    ("AMBIG", "paid", t(9), "ambig_paid"),
    ("AMBIG", "cancelled", t(9), "ambig_cancelled"),
    # 新訂單（沒有 fact）：第一個狀態不限，也不標跳過
    ("NEW1", "completed", t(9), "new1"),
    ("NEW2", "paid", t(9), "new2_paid"),
    ("NEW2", "completed", t(10), "new2_completed"),
    # 新訂單：合法 → 同一秒不同狀態 → 之後的事件
    ("NEWAMB", "created", t(9), "na_created"),
    ("NEWAMB", "paid", t(10), "na_paid"),
    ("NEWAMB", "completed", t(11), "na_completed"),
    ("NEWAMB", "cancelled", t(11), "na_cancelled"),
    ("NEWAMB", "paid", t(12), "na_after"),
    # 同狀態連續列：合併成一段，取最後一列；同一秒同狀態用 tiebreak（note 較大）決定
    ("SAME", "paid", t(9), "same_a"),
    ("SAME", "paid", t(10), "same_b"),
    ("SAME", "paid", t(11), "same_c1"),
    ("SAME", "paid", t(11), "same_c2"),
    # 同狀態連續列的第二列：起點仍是上一段（created），所以也是跳過中間狀態；
    # 跳過標記只打在寫進 fact 的列（superseded 的列不標）
    ("SKIPSEG", "completed", t(9), "skipseg_1"),
    ("SKIPSEG", "completed", t(10), "skipseg_2"),
    # 狀態值不在 4 種之內（合約已擋；這裡驗證萬一繞過合約時的防護）
    ("BADSTATUS", "PAID", t(9), "bad_status"),
    ("BADSTATUS", "completed", t(10), "bad_status_next"),
]

# note → (分類, 是否跳過中間狀態)
EXPECTED = {
    "l4_paid": (C.LATE_EVENT, False),
    "l4_same_ts": (C.LATE_EVENT, False),
    "lc": (C.LATE_EVENT_CONFLICT, False),
    "chain_paid": (C.SUPERSEDED, False),
    "chain_cancelled": (C.ACCEPTED, False),
    "skip": (C.ACCEPTED, True),
    "back": (C.ILLEGAL_TRANSITION, False),
    "after_ok": (C.ACCEPTED, False),
    "after_bad": (C.ILLEGAL_TRANSITION, False),
    "after_next": (C.AFTER_ILLEGAL, False),
    "ambig_paid": (C.AMBIGUOUS_ORDER, False),
    "ambig_cancelled": (C.AMBIGUOUS_ORDER, False),
    "new1": (C.ACCEPTED, False),
    "new2_paid": (C.SUPERSEDED, False),
    "new2_completed": (C.ACCEPTED, False),
    "na_created": (C.SUPERSEDED, False),
    "na_paid": (C.ACCEPTED, False),
    "na_completed": (C.AMBIGUOUS_ORDER, False),
    "na_cancelled": (C.AMBIGUOUS_ORDER, False),
    "na_after": (C.AFTER_ILLEGAL, False),
    "same_a": (C.SUPERSEDED, False),
    "same_b": (C.SUPERSEDED, False),
    "same_c1": (C.SUPERSEDED, False),
    "same_c2": (C.ACCEPTED, False),
    "skipseg_1": (C.SUPERSEDED, False),
    "skipseg_2": (C.ACCEPTED, True),
    # 未知狀態走不到任何狀態：不合法，之後的事件一起隔離
    "bad_status": (C.ILLEGAL_TRANSITION, False),
    "bad_status_next": (C.AFTER_ILLEGAL, False),
}

EVENT_SCHEMA = "order_id string, order_status string, updated_at timestamp, note string"
FACT_SCHEMA = "order_id string, order_status string, updated_at timestamp"


@pytest.fixture(scope="module")
def classified(spark):
    events = spark.createDataFrame(EVENTS, EVENT_SCHEMA)
    fact = spark.createDataFrame(FACT, FACT_SCHEMA)
    rows = classify_status_events(events, fact).collect()
    return rows


@pytest.fixture(scope="module")
def by_note(classified):
    return {r.note: r for r in classified}


@pytest.mark.parametrize(("note", "expected"), sorted(EXPECTED.items()))
def test_order_status_check_category(by_note, note, expected):
    r = by_note[note]
    assert (r[STATE_CATEGORY_COL], r[STATE_SKIPPED_COL]) == expected


def test_order_status_check_conservation(classified):
    # 每列恰好一個分類（不重複、不遺漏），數量相加等於輸入
    assert len(classified) == len(EVENTS)
    assert sorted(r.note for r in classified) == sorted(e[3] for e in EVENTS)
    assert all(r[STATE_CATEGORY_COL] is not None for r in classified)
    counts = collections.Counter(r[STATE_CATEGORY_COL] for r in classified)
    assert sum(counts.values()) == len(EVENTS)
    # 三種去向互斥且涵蓋所有分類
    assert not (WRITE_CATEGORIES & QUARANTINE_CATEGORIES)
    assert not (WRITE_CATEGORIES & SKIP_CATEGORIES)
    assert not (SKIP_CATEGORIES & QUARANTINE_CATEGORIES)
    assert set(counts) <= WRITE_CATEGORIES | QUARANTINE_CATEGORIES | SKIP_CATEGORIES


def test_order_status_check_at_most_one_accepted_per_order(classified):
    accepted = collections.Counter(
        r.order_id for r in classified if r[STATE_CATEGORY_COL] == C.ACCEPTED
    )
    assert all(n == 1 for n in accepted.values())
    # 沒有任何列寫進 fact 的單：晚到、往回走、同一秒不同狀態
    assert set(accepted) == {
        "CHAIN",
        "SKIP",
        "AFTER",
        "NEW1",
        "NEW2",
        "NEWAMB",
        "SAME",
        "SKIPSEG",
    }


def test_order_status_check_reasons(by_note):
    assert by_note["chain_cancelled"][STATE_REASON_COL] is None
    assert by_note["back"][STATE_REASON_COL] == "不合法的狀態轉移：cancelled → paid"
    assert "cancelled, paid" in by_note["ambig_paid"][STATE_REASON_COL]
    assert "走得到 fact 現況 cancelled" in by_note["l4_paid"][STATE_REASON_COL]
    # 除了寫進 fact 的列，每列都有原因
    for note, (cat, _) in EXPECTED.items():
        if cat != C.ACCEPTED:
            assert by_note[note][STATE_REASON_COL], note


def test_order_status_check_split(spark):
    events = spark.createDataFrame(EVENTS, EVENT_SCHEMA)
    fact = spark.createDataFrame(FACT, FACT_SCHEMA)
    split = split_by_disposition(classify_status_events(events, fact))
    expected = collections.Counter(cat for cat, _ in EXPECTED.values())
    n_write = expected[C.ACCEPTED]
    n_skip = expected[C.LATE_EVENT]
    assert split.accepted.count() == n_write == 8
    assert split.skipped.count() == n_skip == 2
    assert split.quarantined.count() == len(EVENTS) - n_write - n_skip


def test_order_status_check_no_fact_first_batch(spark):
    # 第一批沒有 fact：全部是新訂單，沒有晚到事件
    events = spark.createDataFrame(
        [
            ("A", "created", t(9), "a1"),
            ("A", "completed", t(10), "a2"),
            ("B", "cancelled", t(9), "b1"),
            ("B", "paid", t(10), "b2"),
        ],
        EVENT_SCHEMA,
    )
    got = {
        r.note: (r[STATE_CATEGORY_COL], r[STATE_SKIPPED_COL])
        for r in classify_status_events(events, None).collect()
    }
    assert got == {
        "a1": (C.SUPERSEDED, False),
        "a2": (C.ACCEPTED, True),
        "b1": (C.ACCEPTED, False),
        "b2": (C.ILLEGAL_TRANSITION, False),
    }


def test_order_status_check_unknown_status_on_new_order_is_illegal(spark):
    # 新訂單的第一個狀態不限，但必須是 4 種之一；晚到的未知狀態也走不到 fact 現況
    events = spark.createDataFrame(
        [("N", "PAID", t(9), "n1"), ("F", "Paid", t(7), "f1")], EVENT_SCHEMA
    )
    fact = spark.createDataFrame([("F", "paid", t(8))], FACT_SCHEMA)
    got = {
        r.note: r[STATE_CATEGORY_COL]
        for r in classify_status_events(events, fact).collect()
    }
    assert got == {"n1": C.ILLEGAL_TRANSITION, "f1": C.LATE_EVENT_CONFLICT}


def test_order_status_check_rerun_same_batch_all_late(spark):
    # 同一批重跑：fact 已是這批的結果，所以這批每列都變成晚到事件。
    # 分類和第一次不同（這就是為什麼冪等要靠批次紀錄跳過，不能只靠 fact）
    events = spark.createDataFrame(
        [("X", "paid", t(9), "x1"), ("X", "completed", t(10), "x2")], EVENT_SCHEMA
    )
    fact = spark.createDataFrame([("X", "completed", t(10))], FACT_SCHEMA)
    got = {
        r.note: r[STATE_CATEGORY_COL]
        for r in classify_status_events(events, fact).collect()
    }
    assert got == {"x1": C.LATE_EVENT, "x2": C.LATE_EVENT}
