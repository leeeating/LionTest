"""batch_log：強制依序、已完成就跳過、來源檔被改過時丟例外。

run 用假的函式代替（只回傳對帳數字、記錄被呼叫幾次），只寫批次紀錄這一張 Delta 表。
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

import pytest
from pipeline.batch_log import (
    BatchCounts,
    BatchOrderError,
    BatchRecord,
    SourceChangedError,
    _warn_reference_changed,
    completed_batch,
    forced_runs,
    pin_fact_version,
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


REFS = {"members": "m1", "products": "p1", "fx_rates": "f1"}


def _run(spark, log, files, batch_id, fake, force=False, refs=None, now=FIXED_NOW):
    return run_once(
        spark,
        log,
        batch_id=batch_id,
        as_of=AS_OF[batch_id],
        source_checksum=file_sha256([files[batch_id]]),
        reference_checksums=refs,
        run=fake,
        force=force,
        now=lambda: now,
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


def test_batch_log_reference_change_only_warns(caplog):
    # 使用者定 C：參考資料 checksum 不同只警告；相同時不出聲
    done = BatchRecord("base", AS_OF["base"], FIXED_NOW, "x", counts(), dict(REFS))
    with caplog.at_level(logging.WARNING, logger="pipeline.batch_log"):
        assert _warn_reference_changed(done, REFS) == []
    assert caplog.records == []
    with caplog.at_level(logging.WARNING, logger="pipeline.batch_log"):
        changed = _warn_reference_changed(done, {**REFS, "products": "p2"})
    assert changed == ["products"]
    assert "products（p1 → p2）" in caplog.text


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


@pytest.mark.slow
def test_batch_log_reference_change_warns_but_skips(spark, tmp_path, files, caplog):
    # 使用者定 C：參考資料變了只警告、照常跳過；訂單檔變了仍然丟例外
    log = tmp_path / "log"
    first = _run(spark, log, files, "base", FakeRun(counts()), refs=REFS)
    assert first.record.reference_sha256 == REFS
    fake = FakeRun(counts())
    new_refs = {**REFS, "fx_rates": "f2", "members": "m2"}
    with caplog.at_level(logging.WARNING, logger="pipeline.batch_log"):
        again = _run(spark, log, files, "base", fake, refs=new_refs)
    assert again.skipped is True and fake.calls == 0
    assert "fx_rates（f1 → f2）" in caplog.text and "members（m1 → m2）" in caplog.text
    assert "products" not in caplog.text
    # 紀錄不被改寫：仍是第一次的參考資料 checksum
    assert completed_batch(spark, log, "base").reference_sha256 == REFS

    files["base"].write_text("order_id\nbase-1\nbase-2\n", encoding="utf-8")
    with pytest.raises(SourceChangedError, match="來源檔被改過"):
        _run(spark, log, files, "base", FakeRun(counts()), refs=REFS)


@pytest.mark.slow
def test_batch_log_force_leaves_history(spark, tmp_path, files):
    # 使用者定 C：force 覆寫完成紀錄時，強制重跑紀錄留下舊／新 checksum，只增不改
    log = tmp_path / "log"
    force_log = tmp_path / "log_force"  # 沒指定 force_log_path 時的預設位置
    old_sha = file_sha256([files["base"]])
    _run(spark, log, files, "base", FakeRun(counts(10)), refs=REFS)
    assert forced_runs(spark, force_log, "base") == []

    files["base"].write_text("order_id\nbase-1\nbase-2\n", encoding="utf-8")
    new_sha = file_sha256([files["base"]])
    new_refs = {**REFS, "products": "p2"}
    # 兩次 force 的時間不同，forced_runs 依時間排序才有確定的先後
    for minutes in (1, 2):
        _run(
            spark,
            log,
            files,
            "base",
            FakeRun(counts(20)),
            force=True,
            refs=new_refs,
            now=FIXED_NOW + dt.timedelta(minutes=minutes),
        )

    runs = forced_runs(spark, force_log, "base")
    # 每次 force 兩列：run 之前的 started、完成後的 completed
    assert [r["status"] for r in runs] == ["started", "completed"] * 2
    assert runs[0] == {
        "batch_id": "base",
        # 時間欄讀回來是 session 時區的 naive datetime，不比值，只比先後
        "forced_at": runs[0]["forced_at"],
        "status": "started",
        "logged_at": runs[0]["logged_at"],
        "previous_completed_at": runs[0]["previous_completed_at"],
        "previous_source_sha256": old_sha,
        "new_source_sha256": new_sha,
        "source_changed": True,
        "previous_reference_sha256": REFS,
        "new_reference_sha256": new_refs,
    }
    assert {k: v for k, v in runs[1].items() if k not in ("status",)} == {
        k: v for k, v in runs[0].items() if k not in ("status",)
    }
    assert runs[0]["forced_at"] < runs[2]["forced_at"]
    # 第二次 force：被覆寫的是第一次 force 的結果，訂單檔沒再變
    assert (runs[2]["previous_source_sha256"], runs[2]["source_changed"]) == (
        new_sha,
        False,
    )
    assert runs[2]["previous_reference_sha256"] == new_refs
    # 表本身只增不改：Delta 拒絕 DELETE
    from delta.tables import DeltaTable

    props = DeltaTable.forPath(spark, str(force_log)).detail().first().properties
    assert props.get("delta.appendOnly") == "true"
    with pytest.raises(Exception, match="(?i)append"):
        DeltaTable.forPath(spark, str(force_log)).delete("batch_id = 'base'")
    # 完成紀錄仍只有一列，是最新一次的結果
    rec = completed_batch(spark, log, "base")
    assert (rec.source_sha256, rec.reference_sha256) == (new_sha, new_refs)


@pytest.mark.slow
def test_pin_fact_version_returns_first_value(spark, tmp_path):
    # 同一個 batch_id 第二次呼叫回傳第一次記下的版本，不被新的 current_version 蓋掉
    start = tmp_path / "batch_start"
    assert pin_fact_version(spark, start, "day1", 3) == 3
    assert pin_fact_version(spark, start, "day1", 7) == 3
    # 其他批次各自記錄
    assert pin_fact_version(spark, start, "day2", 7) == 7
    assert spark.read.format("delta").load(str(start)).count() == 2


@pytest.mark.slow
def test_batch_log_force_started_is_kept_when_run_fails(spark, tmp_path, files):
    # 驗收找到的漏洞：force 重跑在 run 中途當掉時（fact 可能已被新內容改寫），
    # 強制重跑紀錄也要留下痕跡；完成紀錄維持舊的
    log = tmp_path / "log"
    force_log = tmp_path / "log_force"
    old_sha = file_sha256([files["base"]])
    _run(spark, log, files, "base", FakeRun(counts(10)), refs=REFS)
    files["base"].write_text("order_id\nbase-1\nbase-2\n", encoding="utf-8")
    new_sha = file_sha256([files["base"]])

    with pytest.raises(RuntimeError, match="boom"):
        _run(
            spark,
            log,
            files,
            "base",
            FakeRun(RuntimeError("boom")),
            force=True,
            refs=REFS,
        )
    runs = forced_runs(spark, force_log, "base")
    assert [
        (r["status"], r["previous_source_sha256"], r["new_source_sha256"]) for r in runs
    ] == [("started", old_sha, new_sha)]
    assert completed_batch(spark, log, "base").source_sha256 == old_sha
