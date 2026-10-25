"""真實資料的增量處理：base → day1 → day2 → day3（run_all），全部標 slow。

期望值由 reference_model.reference() 用純 Python csv 依定案規則獨立計算，
不呼叫被測的實作（規則清單見 reference_model 的說明）。
"""

from __future__ import annotations

import pytest
import reference_model as ref
from pipeline.batch_log import BatchOrderError
from pipeline.fact_order import (
    AmountTotals,
    WarehousePaths,
    amount_totals,
    run_all,
    run_batch,
)
from pyspark.sql import functions as F

pytestmark = pytest.mark.slow

TPE = ref.TPE
FILES = ref.FILES
_csv = ref.read_csv
_ts = ref.ts
_identity = ref.identity


@pytest.fixture(scope="module")
def reference():
    return ref.reference()


@pytest.fixture(scope="module")
def full_run(spark, source, tmp_path_factory):
    paths = WarehousePaths(tmp_path_factory.mktemp("wh_all"))
    runs = run_all(spark, source, paths)
    return paths, {r.record.batch_id: r for r in runs}


def test_incremental_reconciliation_matches_reference(full_run, reference):
    _, runs = full_run
    expected, _ = reference
    for batch, _name in FILES:
        run = runs[batch]
        assert run.skipped is False
        c = run.record.counts
        got = {k: getattr(c, k) for k in expected[batch]}
        assert got == expected[batch], batch
        assert c.balanced


def test_incremental_fact_table_matches_reference(spark, full_run, reference):
    paths, _ = full_run
    _, ref_fact = reference
    fact = spark.read.format("delta").load(str(paths.fact_order))
    rows = fact.select(
        "order_id",
        "order_status",
        "amount_twd",
        "net_amount_twd",
        F.date_format("updated_at", "yyyy-MM-dd HH:mm:ss").alias("u"),
    ).collect()
    got = {
        r.order_id: (r.order_status, r.amount_twd, r.net_amount_twd, r.u) for r in rows
    }
    exp = {
        oid: (
            r["order_status"],
            twd,
            net,
            _ts(r["updated_at"]).astimezone(TPE).strftime("%Y-%m-%d %H:%M:%S"),
        )
        for oid, (r, twd, net) in ref_fact.items()
    }
    assert got == exp
    # E12：order_id 唯一
    assert len(rows) == fact.select("order_id").distinct().count()


def test_incremental_amount_totals_exclude_amount_review(spark, full_run, reference):
    # V2（使用者定 B1）：fact 保留清單上的訂單，排除清單後的總和不含它們
    paths, _ = full_run
    expected, _ = reference
    got = amount_totals(spark, paths)
    assert got == AmountTotals(**expected["amount_totals"])
    assert got.review_orders == 40
    assert got.amount_twd_excluding_review < got.amount_twd_total


def test_incremental_l4_late_paid_does_not_revert_cancelled(spark, full_run):
    # L4：day1 送 cancelled，day2 送 updated_at 較舊的 paid（同一張單，不是撞號）
    paths, runs = full_run
    d1 = {r["order_id"]: r for r in _csv("orders_incremental_day1.csv")}
    l4 = {
        r["order_id"]
        for r in _csv("orders_incremental_day2.csv")
        if r["order_id"] in d1
        and _identity(r) == _identity(d1[r["order_id"]])
        and d1[r["order_id"]]["order_status"] == "cancelled"
        and r["order_status"] == "paid"
        and _ts(r["updated_at"]) < _ts(d1[r["order_id"]]["updated_at"])
    }
    assert len(l4) == 25
    assert runs["day2"].record.counts.skipped_rows == 25
    fact = spark.read.format("delta").load(str(paths.fact_order))
    statuses = {
        r.order_status
        for r in fact.filter(F.col("order_id").isin(*l4))
        .select("order_status")
        .collect()
    }
    assert statuses == {"cancelled"}
    q = spark.read.format("delta").load(str(paths.quarantine))
    late = q.filter(
        (F.col("batch_id") == "day2") & (F.col("reject_category") == "late_event")
    )
    assert {r.order_id for r in late.select("order_id").collect()} == l4


def test_incremental_base_rows_overlapping_increments_do_not_regress(spark, full_run):
    # base 有 updated_at 落在 07-01～07-03 的列；和增量同 order_id 的，fact 必須還是 base 那列
    paths, _ = full_run
    base = {}
    for r in _csv("orders_base.csv"):
        old = base.get(r["order_id"])
        if old is None or _ts(r["updated_at"]) > _ts(old["updated_at"]):
            base[r["order_id"]] = r
    inc_ids = {
        r["order_id"]
        for _b, name in FILES[1:]
        for r in _csv(name)
        if r["order_id"] in base
    }
    assert inc_ids  # 確實有重疊
    fact = spark.read.format("delta").load(str(paths.fact_order))
    got = {
        r.order_id: (r.order_status, r.u, r.batch_id)
        for r in fact.filter(F.col("order_id").isin(*inc_ids))
        .select(
            "order_id",
            "order_status",
            "batch_id",
            F.date_format("updated_at", "yyyy-MM-dd HH:mm:ss").alias("u"),
        )
        .collect()
    }
    assert got == {
        oid: (
            base[oid]["order_status"],
            _ts(base[oid]["updated_at"]).astimezone(TPE).strftime("%Y-%m-%d %H:%M:%S"),
            "base",
        )
        for oid in inc_ids
    }


def test_incremental_run_all_again_skips_every_batch(spark, source, full_run):
    paths, runs = full_run
    again = run_all(spark, source, paths)
    assert [r.skipped for r in again] == [True] * 4
    assert [r.record for r in again] == [runs[b].record for b, _ in FILES]


def test_incremental_refuses_out_of_order_batch(spark, source, tmp_path):
    paths = WarehousePaths(tmp_path / "wh")
    with pytest.raises(BatchOrderError, match="'base' 尚未完成"):
        run_batch(spark, source, paths, 2)
    with pytest.raises(BatchOrderError):
        run_batch(spark, source, paths, 1)
    # 什麼都沒寫
    assert not (tmp_path / "wh").exists() or not any((tmp_path / "wh").iterdir())
