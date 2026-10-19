"""batch_log：強制依序、已完成就跳過、來源檔被改過時丟例外。

run 用假的函式代替（只回傳對帳數字、記錄被呼叫幾次），只寫批次紀錄這一張 Delta 表。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pipeline.batch_log import (
    BatchCounts,
    BatchOrderError,
    BatchRecord,
    SourceChangedError,
    completed_batch,
    record_completed,
    run_once,
)
from pipeline.sources import file_sha256

AS_OF = {
    "base": dt.date(2026, 6, 30),
    "day1": dt.date(2026, 7, 1),
    "day2": dt.date(2026, 7, 2),
    "day3": dt.date(2026, 7, 3),
}
FIXED_NOW = dt.datetime(2026, 10, 18, 1, 2, 3, tzinfo=dt.UTC)


def counts(n: int = 10, **kw) -> BatchCounts:
    values = {
        "input_rows": n,
        "fact_rows": n - 3,
        "quarantined_rows": 2,
        "skipped_rows": 1,
        "quarantined_by_category": {"superseded": 1, "illegal_transition": 1},
        "skipped_intermediate_rows": 1,
        "coupon_nulled_rows": 2,
        "amount_review_rows": 1,
        "amount_twd_sum": Decimal("1234.56"),
        "net_amount_twd_sum": Decimal("1200.00"),
        "unknown_product_rows": 0,
        "unknown_member_rows": 1,
        "fact_table_rows": 100 + n,
        "fact_table_amount_twd_sum": Decimal("99999.99"),
        "fact_table_net_amount_twd_sum": Decimal("99000.00"),
        "member_rejected_rows": 0,
    }
    values.update(kw)
    return BatchCounts(**values)


class FakeRun:
    def __init__(self, result: BatchCounts | Exception):
        self.calls = 0
        self.result = result

    def __call__(self) -> BatchCounts:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def files(tmp_path):
    out = {}
    for b in AS_OF:
        p = tmp_path / "src" / f"{b}.csv"
        p.parent.mkdir(exist_ok=True)
        p.write_text(f"order_id\n{b}-1\n", encoding="utf-8")
        out[b] = p
    return out


def _run(spark, log, files, batch_id, fake, force=False):
    return run_once(
        spark,
        log,
        batch_id=batch_id,
        as_of=AS_OF[batch_id],
        source_checksum=file_sha256([files[batch_id]]),
        run=fake,
        force=force,
        now=lambda: FIXED_NOW,
    )


# ------------------------------------------------------------ 不寫 Delta


def test_batch_log_sha256_changes_with_content(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(b"x\n1\n")
    h1 = file_sha256([p])
    # 對照 `shasum -a 256` 無法直接比（前面加了檔名與長度），改驗「內容變就變、不變就不變」
    assert file_sha256([p]) == h1
    p.write_bytes(b"x\n2\n")
    assert file_sha256([p]) != h1


def test_batch_log_record_rejects_unbalanced(spark, tmp_path):
    bad = counts(10, fact_rows=5, quarantined_rows=4, skipped_rows=0)
    assert not bad.balanced
    rec = BatchRecord("base", AS_OF["base"], FIXED_NOW, "x", bad)
    with pytest.raises(ValueError, match="對帳不平"):
        record_completed(spark, tmp_path / "log", rec)
    assert completed_batch(spark, tmp_path / "log", "base") is None


def test_batch_log_unknown_batch_id(spark, tmp_path, files):
    with pytest.raises(ValueError, match="未知的批次"):
        run_once(
            spark,
            tmp_path / "log",
            batch_id="day9",
            as_of=dt.date(2026, 7, 9),
            source_checksum="x",
            run=FakeRun(counts()),
        )


# ------------------------------------------------------------ 寫 Delta


@pytest.mark.slow
def test_batch_log_enforces_order(spark, tmp_path, files):
    log = tmp_path / "log"
    # base 還沒跑，不能跑 day1；run 不會被呼叫，也不會寫紀錄
    fake = FakeRun(counts())
    with pytest.raises(BatchOrderError, match="'base' 尚未完成"):
        _run(spark, log, files, "day1", fake)
    assert fake.calls == 0
    assert completed_batch(spark, log, "day1") is None

    _run(spark, log, files, "base", FakeRun(counts()))
    # 跳過 day1 直接跑 day2 也不行
    fake2 = FakeRun(counts())
    with pytest.raises(BatchOrderError, match="'day1' 尚未完成"):
        _run(spark, log, files, "day2", fake2)
    assert fake2.calls == 0

    _run(spark, log, files, "day1", FakeRun(counts()))
    assert _run(spark, log, files, "day2", FakeRun(counts())).skipped is False


@pytest.mark.slow
def test_batch_log_completed_batch_is_skipped(spark, tmp_path, files):
    log = tmp_path / "log"
    first = _run(spark, log, files, "base", FakeRun(counts(10)))
    assert first.skipped is False
    assert first.record.counts == counts(10)
    assert first.record.as_of == AS_OF["base"]

    # 再跑一次：直接跳過、run 不被呼叫、回傳既有紀錄（即使這次 run 會回傳不同數字）
    again = FakeRun(counts(20))
    second = _run(spark, log, files, "base", again)
    assert again.calls == 0
    assert second.skipped is True
    assert second.record == first.record

    import pyspark.sql.functions as F

    rows = spark.read.format("delta").load(str(log)).filter(F.col("batch_id") == "base")
    assert rows.count() == 1


@pytest.mark.slow
def test_batch_log_changed_source_raises(spark, tmp_path, files):
    log = tmp_path / "log"
    _run(spark, log, files, "base", FakeRun(counts()))
    files["base"].write_text("order_id\nbase-1\nbase-2\n", encoding="utf-8")
    fake = FakeRun(counts())
    with pytest.raises(SourceChangedError, match="來源檔被改過"):
        _run(spark, log, files, "base", fake)
    assert fake.calls == 0


@pytest.mark.slow
def test_batch_log_failed_run_leaves_no_record(spark, tmp_path, files):
    # run 中途當掉：不寫紀錄，下次重跑整批
    log = tmp_path / "log"
    with pytest.raises(RuntimeError, match="boom"):
        _run(spark, log, files, "base", FakeRun(RuntimeError("boom")))
    assert completed_batch(spark, log, "base") is None
    fake = FakeRun(counts())
    assert _run(spark, log, files, "base", fake).skipped is False
    assert fake.calls == 1


@pytest.mark.slow
def test_batch_log_force_reruns_and_replaces_record(spark, tmp_path, files):
    log = tmp_path / "log"
    _run(spark, log, files, "base", FakeRun(counts(10)))
    fake = FakeRun(counts(20))
    run = _run(spark, log, files, "base", fake, force=True)
    assert fake.calls == 1 and run.skipped is False
    assert completed_batch(spark, log, "base").counts == counts(20)
    assert spark.read.format("delta").load(str(log)).count() == 1
