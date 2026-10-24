"""fact_order 初始載入（base）、隔離表、對帳的測試。

期望值的來源都不呼叫被測的實作：
- base 的對帳數字：用純 Python csv 依定案規則獨立計算（tests/reference_model.py）。
- 匯率換算：從 fx_rates.csv 查出當天匯率後手算、寫死（列在各測試的註解裡）。
- 撞號、找不到匯率、格式違規、品質規則、狀態機：用合成資料呼叫 transform_order_batch，
  只驗 DataFrame，不寫 Delta（測試策略）。
- 寫入行為（冪等、replaceWhere、不倒退、當掉重跑、整批停）：走完整流程，寫 Delta 的標 slow。
增量（day1～3）的真實資料測試在 test_fact_order_incremental.py。
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
import reference_model as ref
from delta.tables import DeltaTable
from pipeline import fact_order
from pipeline.contracts import (
    FX_RATES_SCHEMA,
    ORDERS_SCHEMA,
    PRODUCTS_SCHEMA,
    to_raw_schema,
)
from pipeline.delta_io import merge_upsert
from pipeline.dim_member import UNKNOWN_MEMBER_SK, build_dim_member
from pipeline.dims import UNKNOWN_PRODUCT_SK, DuplicateKeyError, build_dim_product
from pipeline.fact_order import (
    BASE_AS_OF,
    BASE_BATCH_ID,
    FACT_UPDATE_CONDITION,
    Category,
    ReferenceDataError,
    WarehousePaths,
    load_base,
    load_order_batch,
    run_all,
    run_batch,
    transform_order_batch,
)
from pipeline.order_status_check import STATE_SKIPPED_COL
from pipeline.sources import DEFAULT_DATASET_DIR, CsvSource
from pipeline.validation import cast_to_contract
from pyspark.sql import functions as F

# ------------------------------------------------------------------ 獨立計算


def _csv(name):
    with open(DEFAULT_DATASET_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _expected_base():
    counts = ref.reference()[0]["base"]
    return {
        "counts": counts,
        "input": counts["input_rows"],
        "fact": counts["fact_rows"],
        "categories": counts["quarantined_by_category"],
        "amount_twd_sum": counts["amount_twd_sum"],
        "unknown_product": counts["unknown_product_rows"],
        "unknown_member": counts["unknown_member_rows"],
    }


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="module")
def expected():
    return _expected_base()


@pytest.fixture(scope="module")
def base_run(spark, source, tmp_path_factory):
    paths = WarehousePaths(tmp_path_factory.mktemp("wh_base"))
    rec = load_base(spark, source, paths)
    return paths, rec


def _fact(spark, paths):
    return spark.read.format("delta").load(str(paths.fact_order))


def _quarantine(spark, paths, batch_id=BASE_BATCH_ID):
    q = spark.read.format("delta").load(str(paths.quarantine))
    return q.filter(F.col("batch_id") == batch_id)


def _fact_row(spark, paths, order_id):
    """取單張訂單；時間欄在 Spark 內先轉成台北時間字串（collect 會轉成本機時區）。"""
    fmt = "yyyy-MM-dd HH:mm:ss"
    rows = (
        _fact(spark, paths)
        .filter(F.col("order_id") == order_id)
        .withColumns(
            {
                "updated_at_text": F.date_format("updated_at", fmt),
                "order_created_at_text": F.date_format("order_created_at", fmt),
            }
        )
        .collect()
    )
    assert len(rows) == 1
    return rows[0]


# ------------------------------------------------------------------ base


@pytest.mark.slow
def test_fact_order_twd_and_ntd_orders_are_not_lost(spark, base_run):
    paths, _ = base_run
    fact = _fact(spark, paths)
    # fx_rates.csv 沒有 TWD、NTD：inner join 匯率表會把它們全部弄丟（buggy_pipeline 的錯）
    for order_id, currency, amount in [
        ("ORD00062509", "TWD", Decimal("122549.00")),
        ("ORD00036189", "TWD", Decimal("8854.00")),
        ("ORD00078735", "NTD", Decimal("32238.00")),
        ("ORD00067010", "NTD", Decimal("81089.00")),
    ]:
        r = _fact_row(spark, paths, order_id)
        assert (r.currency, r.amount, r.amount_twd) == (currency, amount, amount)
    # base 去重後每個 TWD、NTD 的 order_id 都在 fact（base 沒有撞號，見對帳測試）；
    # 金額不大於 0 的列在合約就隔離（V1），不算在內
    raw_ids = {
        r["order_id"]
        for r in _csv("orders_base.csv")
        if r["currency"] in ("TWD", "NTD") and Decimal(r["amount"]) > 0
    }
    got = {
        r.order_id
        for r in fact.filter(F.col("currency").isin("TWD", "NTD"))
        .select("order_id")
        .collect()
    }
    assert got == raw_ids
    assert (
        fact.filter(
            F.col("currency").isin("TWD", "NTD")
            & (F.col("amount_twd") != F.col("amount"))
        ).count()
        == 0
    )


@pytest.mark.slow
def test_fact_order_fx_conversion_uses_taipei_order_date(spark, base_run):
    paths, _ = base_run
    # ORD00059263：USD 231.34，下單 2026-05-21T17:12:49Z ＝ 台北 05-22 01:12，
    # fx_rates 05-22 USD 31.258 → 231.34 × 31.258 = 7231.22572 → 7231.23
    # （若誤用 UTC 日期 05-21 的 31.375，會得到 7258.29）
    r = _fact_row(spark, paths, "ORD00059263")
    assert (r.currency, r.fx_rate, r.amount_twd) == (
        "USD",
        Decimal("31.258000"),
        Decimal("7231.23"),
    )
    assert r.order_date_sk == 20260522
    # ORD00017727：JPY 417712，下單 2026-06-10T20:51:55Z ＝ 台北 06-11，
    # fx_rates 06-11 JPY 0.20711 → 417712 × 0.20711 = 86512.33232 → 86512.33
    r = _fact_row(spark, paths, "ORD00017727")
    assert (r.currency, r.fx_rate, r.amount_twd) == (
        "JPY",
        Decimal("0.207110"),
        Decimal("86512.33"),
    )
    assert r.order_date_sk == 20260611


@pytest.mark.slow
def test_fact_order_base_reconciliation(spark, base_run, expected):
    paths, rec = base_run
    fact, q = _fact(spark, paths), _quarantine(spark, paths)
    # 回傳的對帳數字等於獨立計算
    assert rec.input_rows == expected["input"] == 100040
    assert rec.fact_rows == expected["fact"]
    assert rec.quarantined_rows == sum(expected["categories"].values())
    assert rec.quarantined_by_category == expected["categories"]
    assert rec.amount_twd_sum == expected["amount_twd_sum"]
    assert rec.balanced
    # 實際寫入的表：count() 與 collect() 兩種數法都要對上
    assert fact.count() == len(fact.collect()) == expected["fact"]
    assert q.count() == len(q.collect()) == rec.quarantined_rows
    assert fact.count() + q.count() == expected["input"]
    assert fact.agg(F.sum("amount_twd")).first()[0] == expected["amount_twd_sum"]
    assert rec.fact_table_rows == expected["fact"]
    assert rec.fact_table_amount_twd_sum == expected["amount_twd_sum"]
    # 其他對帳欄位（coupon 轉 NULL、V2 清單、net_amount_twd 等）也等於獨立計算
    got = {k: getattr(rec, k) for k in expected["counts"]}
    assert got == expected["counts"]
    # fact 的 order_id 唯一
    assert fact.select("order_id").distinct().count() == fact.count()


@pytest.mark.slow
def test_fact_order_base_has_v7_duplicates_and_no_collisions(base_run, expected):
    _, rec = base_run
    # V7：40 組完全相同的重複，多出 40 列；V1：50 列負數金額在合約擋下；
    # base 內部沒有撞號、沒有找不到匯率
    assert expected["categories"] == {"contract": 50, "duplicate": 40}
    assert rec.quarantined_by_category == {
        Category.CONTRACT: 50,
        Category.DUPLICATE: 40,
    }


@pytest.mark.slow
def test_fact_order_base_negative_amounts_quarantined_by_contract(spark, base_run):
    # V1：base 的 50 列負數金額（合計 -12,389,441.87 TWD，見 process-log）全部隔離，不進 fact
    paths, _ = base_run
    negative = {
        r["order_id"] for r in _csv("orders_base.csv") if Decimal(r["amount"]) <= 0
    }
    assert len(negative) == 50
    q = _quarantine(spark, paths).filter(F.col("reject_category") == "contract")
    rows = q.collect()
    assert {r.order_id for r in rows} == negative
    assert {tuple(r.reject_reasons) for r in rows} == {("amount:必須大於 0",)}
    fact = _fact(spark, paths)
    assert fact.filter(F.col("amount") <= 0).count() == 0
    assert fact.filter(F.col("order_id").isin(*negative)).count() == 0


@pytest.mark.slow
def test_fact_order_base_coupon_net_and_amount_review(spark, base_run, expected):
    paths, rec = base_run
    fact = _fact(spark, paths)
    # V3：coupon -1.0 轉 NULL（base 300 列，其中 1 列被去重或合約淘汰，寫進 fact 的是 299）
    assert rec.coupon_nulled_rows == expected["counts"]["coupon_nulled_rows"] == 299
    assert fact.filter(F.col("coupon_discount") < 0).count() == 0
    # J10：net_amount_twd ＝ amount_twd − coupon；coupon 為 NULL 時 net 也是 NULL
    bad = fact.filter(
        ~F.col("net_amount_twd").eqNullSafe(
            F.col("amount_twd") - F.col("coupon_discount")
        )
    )
    assert bad.count() == 0
    assert (
        fact.filter(
            F.col("coupon_discount").isNull() & F.col("net_amount_twd").isNotNull()
        ).count()
        == 0
    )
    # V2：比值超過 100 的列在清單裡，fact 照原樣保留
    review = spark.read.format("delta").load(str(paths.amount_review))
    assert rec.amount_review_rows == review.count() == 40
    assert review.filter(F.col("amount_ratio") <= 100).count() == 0
    ids = [r.order_id for r in review.collect()]
    assert fact.filter(F.col("order_id").isin(*ids)).count() == 40


@pytest.mark.slow
def test_fact_order_v7_keeps_latest_updated_at(spark, base_run):
    paths, _ = base_run
    # ORD00000984：updated_at 07:02:52 / 07:03:06，保留 07:03:06
    r = _fact_row(spark, paths, "ORD00000984")
    assert r.updated_at_text == "2026-05-12 07:03:06"
    # ORD00012637：+08:00（updated 09:27:51）與 Z（updated 09:28:10）同一時刻，保留 Z 那列
    r = _fact_row(spark, paths, "ORD00012637")
    assert r.updated_at_text == "2026-06-15 09:28:10"
    assert r.order_created_at_text == "2026-06-14 19:17:51"

    q = _quarantine(spark, paths).filter(
        F.col("order_id").isin("ORD00000984", "ORD00012637")
    )
    got = sorted(
        (
            r.order_id,
            r.updated_at,
            r.order_created_at,
            r.amount,
            r.reject_category,
            r.reject_reasons,
        )
        for r in q.collect()
    )
    assert got == [
        (
            "ORD00000984",
            "2026-05-12T07:02:52+08:00",
            "2026-05-12T03:23:52+08:00",
            "152295.0",
            "duplicate",
            [fact_order.REASON_DUPLICATE],
        ),
        (
            "ORD00012637",
            "2026-06-15T09:27:51+08:00",
            "2026-06-14T19:17:51+08:00",
            "86020.0",
            "duplicate",
            [fact_order.REASON_DUPLICATE],
        ),
    ]


@pytest.mark.slow
def test_fact_order_unknown_product_falls_to_minus_one(spark, base_run, expected):
    paths, rec = base_run
    fact = _fact(spark, paths)
    unknown = fact.filter(F.col("product_sk") == UNKNOWN_PRODUCT_SK)
    # V6：主檔外的 120 個 product_id（全部 P9xxxx）
    assert expected["unknown_product"] == 120
    assert rec.unknown_product_rows == unknown.count() == 120
    assert unknown.filter(~F.col("product_id").startswith("P9")).count() == 0
    assert unknown.select("product_id").distinct().count() == 120
    assert (
        rec.unknown_member_rows
        == fact.filter(F.col("member_sk") == UNKNOWN_MEMBER_SK).count()
        == expected["unknown_member"]
    )


@pytest.mark.slow
def test_fact_order_date_keys_exist_in_dim_date(spark, base_run):
    paths, _ = base_run
    fact, dim_date = (
        _fact(spark, paths),
        spark.read.format("delta").load(str(paths.dim_date)),
    )
    for col in ("order_date_sk", "departure_date_sk"):
        orphans = fact.filter(F.col(col).isNotNull()).join(
            dim_date, F.col(col) == dim_date.date_sk, "left_anti"
        )
        assert orphans.count() == 0
    # dim_date 只看到 base，不偷看增量：base 下單日 05-01～06-30、出發日 05-08～10-27
    # （純 Python 讀 orders_base.csv 查得）；三天增量都進來後才會到 10-30
    lo, hi = dim_date.agg(F.min("date"), F.max("date")).first()
    assert (lo, hi) == (dt.date(2026, 5, 1), dt.date(2026, 10, 27))


@pytest.mark.slow
def test_fact_order_base_is_idempotent(spark, source, base_run):
    paths, rec1 = base_run
    fact1 = sorted(_fact(spark, paths).collect())
    q1 = sorted(_quarantine(spark, paths).collect())
    rec2 = load_base(spark, source, paths)
    assert rec2 == rec1
    assert sorted(_fact(spark, paths).collect()) == fact1
    q_all = spark.read.format("delta").load(str(paths.quarantine))
    assert q_all.count() == len(q1)  # 沒有因為重跑變成兩份
    assert sorted(_quarantine(spark, paths).collect()) == q1


# ------------------------------------------------------------------ 合成資料

PRODUCTS_HEADER = "product_id,product_name,product_type,destination_country,destination_city,trip_days,base_price_twd,is_active"
MEMBERS_HEADER = (
    "member_id,member_name,member_level,city,birth_date,register_date,extract_date"
)


FX_ROWS = ["2026-05-01,USD,30.5", "2026-05-01,JPY,0.2"]
AS_OF = dt.date(2026, 4, 30)


def _mini_dataset(dir_path: Path, products_rows=None, fx_rows=None):
    products_rows = products_rows or [
        "P00001,東京5日,團體旅遊,日本,東京,5,50000,Y",
        "P00002,紐約3日,訂房,美國,紐約,3,30000,Y",
    ]
    files = {
        "products.csv": [PRODUCTS_HEADER, *products_rows],
        "fx_rates.csv": [
            "rate_date,currency,rate_to_twd",
            *(fx_rows or FX_ROWS),
        ],
        "members.csv": [
            MEMBERS_HEADER,
            "M1,王小明,一般,台北市,1990-01-01,2020-01-01,2026-04-30",
            "M2,李小華,金卡,高雄市,1985-05-05,2021-02-02,2026-04-30",
        ],
    }
    for name, lines in files.items():
        (dir_path / name).write_text("﻿" + "\n".join(lines) + "\n", encoding="utf-8")
    return dir_path


def _order(
    order_id,
    member="M1",
    currency="TWD",
    amount="1000.0",
    created="2026-05-01T10:00:00+08:00",
    updated="2026-05-01T11:00:00+08:00",
    status="paid",
):
    return (
        order_id,
        member,
        "P00001",
        "app",
        status,
        "1",
        currency,
        amount,
        "0.0",
        created,
        "2026-06-01",
        updated,
        None,
    )


def _orders_df(spark, rows):
    return spark.createDataFrame(rows, to_raw_schema(ORDERS_SCHEMA))


def _upd(hh, mm=0):
    return f"2026-05-01T{hh:02d}:{mm:02d}:00+08:00"


@pytest.fixture
def mini_src(spark, tmp_path):
    ds = tmp_path / "ds"
    ds.mkdir()
    return CsvSource(spark, _mini_dataset(ds))


@pytest.fixture
def mini(mini_src, tmp_path):
    return mini_src, WarehousePaths(tmp_path / "wh")


def _transform(spark, src, rows, *, existing=None, batch_id="t1"):
    """只做轉換（transform_order_batch），不寫 Delta；回傳 (fact 列, 隔離列)。"""
    products, _ = cast_to_contract(src.products(), PRODUCTS_SCHEMA)
    fx, _ = cast_to_contract(src.fx_rates(), FX_RATES_SCHEMA)
    t = transform_order_batch(
        _orders_df(spark, rows),
        batch_id=batch_id,
        as_of=AS_OF,
        fx=fx,
        dim_product=build_dim_product(spark, products),
        dim_member=build_dim_member(spark, src.members(), through=AS_OF).changes,
        existing=existing,
    )
    return t


def _q(t):
    return {
        (r.order_id, r.updated_at): (r.reject_category, r.reject_reasons)
        for r in t.quarantine.collect()
    }


def _cats(t):
    return dict(collections.Counter(r.reject_category for r in t.quarantine.collect()))


def test_fact_order_collision_within_batch_quarantines_whole_group(spark, mini_src):
    rows = [
        # O1：同一 order_id，會員不同 → 撞號，兩列都隔離
        _order("O1", member="M1", updated="2026-05-01T11:00:00+08:00"),
        _order("O1", member="M2", updated="2026-05-01T12:00:00+08:00"),
        # O2：下單時間字串格式不同但同一時刻、只差 updated_at → 重複，不是撞號
        _order(
            "O2",
            created="2026-05-01T10:00:00+08:00",
            updated="2026-05-01T11:00:00+08:00",
        ),
        _order(
            "O2", created="2026-05-01T02:00:00Z", updated="2026-05-01T11:00:05+08:00"
        ),
        # O3：金額不同 → 撞號
        _order("O3", amount="1000.0"),
        _order("O3", amount="2000.0", updated="2026-05-01T12:00:00+08:00"),
        _order("O4"),
    ]
    t = _transform(spark, mini_src, rows)
    q = {
        (r.order_id, r.member_id, r.amount): (r.reject_category, r.reject_reasons)
        for r in t.quarantine.collect()
    }
    collision = (
        Category.COLLISION,
        ["撞號：同批同 order_id 的會員、下單時間或金額不同，整組隔離"],
    )
    assert q == {
        ("O1", "M1", "1000.0"): collision,
        ("O1", "M2", "1000.0"): collision,
        ("O3", "M1", "1000.0"): collision,
        ("O3", "M1", "2000.0"): collision,
        ("O2", "M1", "1000.0"): (
            Category.DUPLICATE,
            [fact_order.REASON_DUPLICATE],
        ),
    }
    assert sorted(r.order_id for r in t.fact.collect()) == ["O2", "O4"]
    assert t.fact.count() + t.quarantine.count() == len(rows)


def test_fact_order_collision_with_existing_fact_is_quarantined(spark, mini_src):
    # 撞號判斷可重用：第二批的 O1 與既有 fact 的 O1 會員不同 → 整組隔離
    first = _transform(spark, mini_src, [_order("O1", member="M1")])
    existing = first.fact.drop(STATE_SKIPPED_COL)
    t = _transform(
        spark,
        mini_src,
        [
            _order("O1", member="M2", updated=_upd(12)),
            _order("O1", member="M2", updated=_upd(13), status="completed"),
        ],
        existing=existing,
        batch_id="t2",
    )
    assert t.fact.count() == 0
    assert _cats(t) == {Category.COLLISION_EXISTING: 2}
    assert {tuple(r.reject_reasons) for r in t.quarantine.collect()} == {
        ("撞號：與既有 fact 同 order_id，但會員、下單時間或金額不同",)
    }


def test_fact_order_missing_fx_rate_is_quarantined(spark, mini_src):
    rows = [
        _order("O1", currency="USD", amount="10.0"),  # 05-01 有 USD 30.5 → 305.00
        _order(
            "O2", currency="USD", amount="10.0", created="2026-05-02T10:00:00+08:00"
        ),  # 05-02 沒有匯率
        _order("O3", currency="EUR", amount="10.0"),  # 不在允許的幣別：合約就擋下
        _order("O4", currency="NTD", amount="10.0"),  # NTD 固定 1
        # O5：UTC 04-30 18:00 ＝ 台北 05-01 02:00 → 用 05-01 的匯率
        _order("O5", currency="JPY", amount="1000.0", created="2026-04-30T18:00:00Z"),
    ]
    t = _transform(spark, mini_src, rows)
    q = {
        r.order_id: (r.reject_category, r.reject_reasons)
        for r in t.quarantine.collect()
    }
    assert q == {
        "O2": (
            Category.FX_MISSING,
            ["currency:下單日 2026-05-02 找不到 USD 對 TWD 的匯率"],
        ),
        "O3": (
            Category.CONTRACT,
            ["currency:值不在允許範圍（TWD、NTD、USD、JPY）"],
        ),
    }
    got = {r.order_id: r.amount_twd for r in t.fact.collect()}
    assert got == {
        "O1": Decimal("305.00"),
        "O4": Decimal("10.00"),
        "O5": Decimal("200.00"),
    }


def test_fact_order_contract_violation_is_quarantined_with_raw_values(spark, mini_src):
    rows = [_order("O1", amount="1e2"), _order("O2"), _order("O3", status="PAID")]
    t = _transform(spark, mini_src, rows)
    q = {r.order_id: r for r in t.quarantine.collect()}
    assert (q["O1"].amount, q["O1"].reject_category) == ("1e2", Category.CONTRACT)
    assert q["O1"].reject_reasons == ["amount:型別不符（應為 decimal(18,2)）"]
    assert (q["O3"].order_status, q["O3"].reject_reasons) == (
        "PAID",
        ["order_status:值不在允許範圍（created、paid、cancelled、completed）"],
    )
    assert [r.order_id for r in t.fact.collect()] == ["O2"]
    assert all(r.batch_id == "t1" for r in t.quarantine.collect())


def test_fact_order_quality_rules_quarantine_with_raw_values(
    spark, mini_src, monkeypatch
):
    # A-3 的掛載點：塞兩條規則，其中一條要用 as_of
    def huge_amount(as_of):
        return F.when(F.col("amount") > 1_000_000, F.lit("amount:過大"))

    def completed_before_departure(as_of):
        return F.when(
            (F.col("order_status") == "completed")
            & (F.col("departure_date") > F.lit(as_of)),
            F.concat(F.lit("order_status:completed 但出發日晚於 "), F.lit(str(as_of))),
        )

    monkeypatch.setattr(
        fact_order,
        "ORDER_QUALITY_RULES",
        (huge_amount, completed_before_departure),
    )
    rows = [
        _order("O1", amount="5000000.0"),
        _order("O2", status="completed"),  # 出發日 2026-06-01 > as_of 2026-04-30
        _order("O3", amount="7500000.50", status="completed"),  # 兩條都命中
        _order("O4"),
    ]
    t = _transform(spark, mini_src, rows)
    q = {
        r.order_id: (r.amount, r.reject_category, r.reject_reasons)
        for r in t.quarantine.collect()
    }
    late = "order_status:completed 但出發日晚於 2026-04-30"
    assert q == {
        "O1": ("5000000.0", Category.QUALITY, ["amount:過大"]),
        "O2": ("1000.0", Category.QUALITY, [late]),
        "O3": ("7500000.50", Category.QUALITY, ["amount:過大", late]),
    }
    assert [r.order_id for r in t.fact.collect()] == ["O4"]


def test_fact_order_state_machine_runs_inside_transform(spark, mini_src):
    # 既有 fact：O1 paid、O2 cancelled、O3 created、O5 created（都在 11:00）
    first = _transform(
        spark,
        mini_src,
        [
            _order("O1", status="paid"),
            _order("O2", status="cancelled"),
            _order("O3", status="created"),
            _order("O5", status="created"),
        ],
    )
    existing = first.fact.drop(STATE_SKIPPED_COL)
    rows = [
        _order("O1", status="created", updated=_upd(10, 30)),  # 晚到、走得到 paid
        _order("O2", status="paid", updated=_upd(12)),  # cancelled → paid：往回走
        _order("O3", status="paid", updated=_upd(12)),  # created → paid → completed
        _order("O3", status="completed", updated=_upd(13)),
        _order("O4", status="completed", updated=_upd(12)),  # 新訂單：不標跳過
        _order("O5", status="completed", updated=_upd(12)),  # created → completed：跳過
    ]
    t = _transform(spark, mini_src, rows, existing=existing, batch_id="t2")
    q = {
        (r.order_id, r.order_status): r.reject_category for r in t.quarantine.collect()
    }
    assert q == {
        ("O1", "created"): Category.LATE_EVENT,
        ("O2", "paid"): Category.ILLEGAL_TRANSITION,
        ("O3", "paid"): Category.SUPERSEDED,
    }
    got = {r.order_id: (r.order_status, r[STATE_SKIPPED_COL]) for r in t.fact.collect()}
    assert got == {
        "O3": ("completed", False),
        "O4": ("completed", False),
        "O5": ("completed", True),
    }


def _existing(spark, src, rows):
    """用第一批的轉換結果當既有 fact（不寫 Delta）。"""
    first = _transform(spark, src, rows)
    return first.fact.drop(STATE_SKIPPED_COL, "_coupon_nulled")


def _by_upd(t):
    """{(狀態, updated_at 時:分): 分類}；寫進 fact 的列記為 "fact"。"""
    out = {
        (r.order_status, r.updated_at[11:16]): r.reject_category
        for r in t.quarantine.collect()
    }
    for r in t.fact.withColumn("u", F.date_format("updated_at", "HH:mm")).collect():
        out[(r.order_status, r.u)] = "fact"
    return out


def test_fact_order_dedupe_does_not_hide_illegal_transition_a8(spark, mini_src):
    # A8：fact created；同批 cancelled@08 → paid@09 → cancelled@10。
    # 兩個 cancelled 中間夾著 paid，不算重複（使用者定：只有時間上相鄰才算）。
    # 鏈：created→cancelled 合法；cancelled→paid 往回走；之後的 cancelled 一起隔離
    existing = _existing(
        spark, mini_src, [_order("O1", status="created", updated=_upd(7))]
    )
    rows = [
        _order("O1", status="cancelled", updated=_upd(8)),
        _order("O1", status="paid", updated=_upd(9)),
        _order("O1", status="cancelled", updated=_upd(10)),
    ]
    t = _transform(spark, mini_src, rows, existing=existing, batch_id="t2")
    assert _by_upd(t) == {
        ("cancelled", "08:00"): "fact",
        ("paid", "09:00"): Category.ILLEGAL_TRANSITION,
        ("cancelled", "10:00"): Category.AFTER_ILLEGAL,
    }


def test_fact_order_dedupe_does_not_hide_same_second_conflict_a4(spark, mini_src):
    # A4：fact created；同批 paid@10、cancelled@12、completed@12、completed@13。
    # 12:00 有兩種狀態，completed@12 不能被當成 completed@13 的重複刪掉。
    # 12:00 是斷點：兩列 ambiguous_order；completed@13 在斷點之後 → after_illegal；
    # 斷點之前的 paid 照常寫入（使用者定：同一秒衝突之前的合法事件照寫）
    existing = _existing(
        spark, mini_src, [_order("O1", status="created", updated=_upd(9))]
    )
    rows = [
        _order("O1", status="paid", updated=_upd(10)),
        _order("O1", status="cancelled", updated=_upd(12)),
        _order("O1", status="completed", updated=_upd(12)),
        _order("O1", status="completed", updated=_upd(13)),
    ]
    t = _transform(spark, mini_src, rows, existing=existing, batch_id="t2")
    assert _by_upd(t) == {
        ("paid", "10:00"): "fact",
        ("cancelled", "12:00"): Category.AMBIGUOUS_ORDER,
        ("completed", "12:00"): Category.AMBIGUOUS_ORDER,
        ("completed", "13:00"): Category.AFTER_ILLEGAL,
    }


def test_fact_order_dedupe_only_adjacent_identical_rows(spark, mini_src):
    # 去重與狀態機的交互：
    # O1 paid@09、paid@10（相鄰全同）→ 09 重複；paid@10 寫入
    # O2 paid@09、paid@09（同一秒全同）→ 一列重複；另一列寫入
    # O3 paid@09、completed@10、paid@11（不相鄰）→ 不去重；paid@11 往回走
    # O4 paid@09、paid@10 但 channel 不同 → 內容不同不算重複；交給狀態機（superseded）
    rows = [
        _order("O1", updated=_upd(9)),
        _order("O1", updated=_upd(10)),
        _order("O2", updated=_upd(9)),
        _order("O2", updated=_upd(9)),
        _order("O3", updated=_upd(9)),
        _order("O3", status="completed", updated=_upd(10)),
        _order("O3", updated=_upd(11)),
        _order("O4", updated=_upd(9)),
        _order("O4", updated=_upd(10))[:3]
        + ("web",)
        + _order("O4")[4:11]
        + (_upd(10), None),
    ]
    t = _transform(spark, mini_src, rows)
    q = sorted(
        (r.order_id, r.updated_at[11:16], r.reject_category)
        for r in t.quarantine.collect()
    )
    assert q == [
        ("O1", "09:00", Category.DUPLICATE),
        ("O2", "09:00", Category.DUPLICATE),
        ("O3", "09:00", Category.SUPERSEDED),
        ("O3", "11:00", Category.ILLEGAL_TRANSITION),
        ("O4", "09:00", Category.SUPERSEDED),
    ]
    fact = {r.order_id: (r.order_status, r.channel) for r in t.fact.collect()}
    assert fact == {
        "O1": ("paid", "app"),
        "O2": ("paid", "app"),
        "O3": ("completed", "app"),
        "O4": ("paid", "web"),
    }
    assert t.fact.count() + t.quarantine.count() == len(rows)


def _with_coupon(row, coupon):
    return row[:8] + (coupon,) + row[9:]


def test_fact_order_coupon_minus_one_becomes_null_and_net_amount(spark, mini_src):
    # V3：coupon -1.0 轉 NULL，訂單照常寫入；J10：net＝amount_twd − coupon（coupon 是台幣）
    rows = [
        _with_coupon(_order("O1", amount="1000.0"), "-1.0"),
        _with_coupon(_order("O2", amount="1000.0"), "950.0"),
        _with_coupon(_order("O3", amount="1000.0"), "0.0"),
        _with_coupon(_order("O4", amount="1000.0"), None),
        # USD 10 × 30.5 ＝ 305.00；coupon 50（台幣）→ net 255.00
        _with_coupon(_order("O5", currency="USD", amount="10.0"), "50.0"),
    ]
    t = _transform(spark, mini_src, rows)
    got = {
        r.order_id: (r.coupon_discount, r.net_amount_twd, r._coupon_nulled)
        for r in t.fact.collect()
    }
    assert got == {
        "O1": (None, None, True),
        "O2": (Decimal("950.00"), Decimal("50.00"), False),
        "O3": (Decimal("0.00"), Decimal("1000.00"), False),
        "O4": (None, None, False),
        "O5": (Decimal("50.00"), Decimal("255.00"), False),
    }
    assert t.quarantine.count() == 0
    # 隔離表保留原始字串：-1.0 的列若被隔離，看得到上游送的是 -1.0
    bad = _with_coupon(_order("O6", amount="-3.0"), "-1.0")
    q = _transform(spark, mini_src, [bad]).quarantine.collect()
    assert [(r.coupon_discount, r.reject_reasons) for r in q] == [
        ("-1.0", ["amount:必須大於 0"])
    ]


def test_fact_order_amount_review_lists_ratio_over_100(spark, mini_src):
    # V2：比值 amount_twd ÷（定價 × 數量）> 100 的列另列清單，fact 照原樣寫入。
    # P00001 定價 50,000、數量 1
    rows = [
        _order("O1", amount="50000.0"),  # 比值 1
        _order("O2", amount="50000000.0"),  # 比值 1,000 → 清單
        _order("O3", amount="5000000.0"),  # 比值 100：不超過，不列
        _order("O4", currency="USD", amount="200000.0"),  # 200000×30.5/50000 ＝ 122
    ]
    t = _transform(spark, mini_src, rows)
    got = {
        r.order_id: (r.amount_twd, r.base_price_twd, r.amount_ratio, r.batch_id)
        for r in t.amount_review.collect()
    }
    assert got == {
        "O2": (Decimal("50000000.00"), Decimal("50000.00"), Decimal("1000.00"), "t1"),
        "O4": (Decimal("6100000.00"), Decimal("50000.00"), Decimal("122.00"), "t1"),
    }
    assert t.fact.count() == 4


def test_fact_order_amount_review_lists_coupon_over_amount(spark, mini_src):
    # 使用者定 B：coupon > amount_twd（net 為負）照常寫入 fact，另列進 amount_review。
    # 〔防護性設計：本資料 0 筆〕P00001 定價 50,000、數量 1
    rows = [
        _with_coupon(_order("O1", amount="1000.0"), "1000.0"),  # 相等：net 0，不列
        _with_coupon(_order("O2", amount="1000.0"), "1500.0"),  # net -500 → 清單
        # USD 10 × 30.5 ＝ 305.00 < coupon 400（台幣）→ net -95 → 清單
        _with_coupon(_order("O3", currency="USD", amount="10.0"), "400.0"),
        _with_coupon(_order("O4", amount="1000.0"), "-1.0"),  # coupon 未知（NULL）
        # 兩種原因都中：比值 1,000 且 coupon 更大 → 一列，原因依序都列出
        _with_coupon(_order("O5", amount="50000000.0"), "60000000.0"),
    ]
    t = _transform(spark, mini_src, rows)
    got = {
        r.order_id: (r.coupon_discount, r.net_amount_twd, r.review_reasons)
        for r in t.amount_review.collect()
    }
    assert got == {
        "O2": (
            Decimal("1500.00"),
            Decimal("-500.00"),
            [fact_order.REVIEW_REASON_COUPON],
        ),
        "O3": (Decimal("400.00"), Decimal("-95.00"), [fact_order.REVIEW_REASON_COUPON]),
        "O5": (
            Decimal("60000000.00"),
            Decimal("-10000000.00"),
            [fact_order.REVIEW_REASON_RATIO, fact_order.REVIEW_REASON_COUPON],
        ),
    }
    # fact 照原樣寫入（net 為負也寫），沒有任何列被隔離
    assert t.fact.count() == 5
    assert t.quarantine.count() == 0


def test_fact_order_negative_coupon_is_quarantined_by_contract(spark, mini_src):
    # 使用者定 B：-1 以外的負數 coupon 在合約層隔離，原始字串保留（防護性設計，本資料 0 筆）
    rows = [
        _with_coupon(_order("O1"), "-5.0"),
        _with_coupon(_order("O2"), "-1.0"),
    ]
    t = _transform(spark, mini_src, rows)
    q = [
        (r.order_id, r.coupon_discount, r.reject_category, r.reject_reasons)
        for r in t.quarantine.collect()
    ]
    assert q == [
        (
            "O1",
            "-5.0",
            Category.CONTRACT,
            ["coupon_discount:必須大於或等於 0（-1.00 除外）"],
        )
    ]
    assert [r.order_id for r in t.fact.collect()] == ["O2"]


@pytest.mark.parametrize(
    ("dataset", "match", "cause"),
    [
        # 產品清單有違規列（trip_days 不是整數）
        (
            {"products_rows": ["P00001,東京5日,團體旅遊,日本,東京,abc,50000,Y"]},
            "products",
            None,
        ),
        # 產品清單 product_id 重複：DuplicateKeyError 統一轉成 ReferenceDataError
        (
            {
                "products_rows": [
                    "P00001,東京5日,團體旅遊,日本,東京,5,50000,Y",
                    "P00001,東京6日,團體旅遊,日本,東京,6,60000,Y",
                ]
            },
            "products",
            DuplicateKeyError,
        ),
        # 匯率表同日同幣別有兩個匯率：不知道用哪一個，join 還會讓 fact 列數膨脹
        ({"fx_rows": [*FX_ROWS, "2026-05-01,USD,31.0"]}, "fx_rates", None),
    ],
    ids=["product_rejected", "product_duplicate", "fx_duplicate"],
)
def test_fact_order_bad_reference_data_stops_whole_batch(
    spark, tmp_path, dataset, match, cause
):
    ds = tmp_path / "ds"
    ds.mkdir()
    _mini_dataset(ds, **dataset)
    paths = WarehousePaths(tmp_path / "wh")
    with pytest.raises(ReferenceDataError, match=match) as exc:
        load_order_batch(
            spark,
            CsvSource(spark, ds),
            batch_id="t1",
            orders=_orders_df(spark, [_order("O1", currency="USD", amount="10.0")]),
            as_of=AS_OF,
            paths=paths,
        )
    if cause is None:
        assert exc.value.__cause__ is None
    else:
        assert isinstance(exc.value.__cause__, cause)
    # 任何表都沒有寫入（含維度與批次紀錄）
    for table in (
        paths.fact_order,
        paths.quarantine,
        paths.dim_product,
        paths.dim_member,
        paths.dim_date,
        paths.batch_log,
    ):
        assert not DeltaTable.isDeltaTable(spark, str(table)), table


def test_fact_order_invalid_batch_id_is_rejected(spark, mini):
    src, paths = mini
    with pytest.raises(ValueError, match="batch_id"):
        load_order_batch(
            spark,
            src,
            batch_id="x' OR '1'='1",
            orders=_orders_df(spark, [_order("O1")]),
            as_of=AS_OF,
            paths=paths,
        )


def test_base_as_of_is_last_base_day():
    assert BASE_AS_OF == dt.date(2026, 6, 30)


# ------------------------------------------------------------------ 寫入行為（slow）


def _run(spark, mini, rows, batch_id="t1"):
    src, paths = mini
    return load_order_batch(
        spark,
        src,
        batch_id=batch_id,
        orders=_orders_df(spark, rows),
        as_of=AS_OF,
        paths=paths,
    )


@pytest.mark.slow
def test_fact_order_rerun_same_batch_replaces_quarantine(spark, mini):
    # 同一 batch_id 重跑：隔離表先清掉舊的再寫，不會變兩份；其他 batch 不受影響
    _run(spark, mini, [_order("O1", amount="1e2")], batch_id="t1")
    _run(spark, mini, [_order("O9", amount="x")], batch_id="t2")
    _run(spark, mini, [_order("O1", amount="1e2")], batch_id="t1")
    _, paths = mini
    q = spark.read.format("delta").load(str(paths.quarantine))
    assert sorted((r.batch_id, r.order_id) for r in q.collect()) == [
        ("t1", "O1"),
        ("t2", "O9"),
    ]


@pytest.mark.slow
def test_merge_upsert_clears_commit_marker_after_failure(spark, tmp_path):
    # MERGE 丟例外時，userMetadata 也要清掉，否則之後別的 commit 會被標成這一批
    path = tmp_path / "t"
    schema = "order_id string, v int"
    spark.createDataFrame([("O1", 1)], schema).write.format("delta").save(str(path))
    # 這版 Delta 的錯誤訊息找不到 error class 模板，只看得到類別名稱
    with pytest.raises(Exception, match="DELTA_MERGE_UNRESOLVED|no_such_key"):
        merge_upsert(
            spark,
            spark.createDataFrame([("O1", 2)], schema),
            path,
            keys=["no_such_key"],
            commit_marker="batch:boom",
        )
    conf = "spark.databricks.delta.commitInfo.userMetadata"
    assert spark.conf.get(conf, None) is None


@pytest.mark.slow
def test_fact_order_merge_never_regresses_updated_at(spark, tmp_path):
    # MERGE 條件本身（狀態機之外的第二道防線）：較舊的列不覆寫，較新的才覆寫
    path = tmp_path / "fact"
    schema = "order_id string, order_status string, updated_at timestamp"
    t = dt.datetime
    spark.createDataFrame(
        [("O1", "completed", t(2026, 7, 1, 12))], schema
    ).write.format("delta").save(str(path))

    def merge(rows):
        merge_upsert(
            spark,
            spark.createDataFrame(rows, schema),
            path,
            keys=["order_id"],
            update_condition=FACT_UPDATE_CONDITION,
        )
        return {
            r.order_id: r.order_status
            for r in spark.read.format("delta").load(str(path)).collect()
        }

    # 較舊（11:00）與同一秒（12:00）都不覆寫；新的 O2 照常插入
    assert merge(
        [("O1", "paid", t(2026, 7, 1, 11)), ("O2", "paid", t(2026, 7, 1, 9))]
    ) == {"O1": "completed", "O2": "paid"}
    assert merge([("O1", "cancelled", t(2026, 7, 1, 12))]) == {
        "O1": "completed",
        "O2": "paid",
    }
    assert merge([("O1", "cancelled", t(2026, 7, 1, 13))]) == {
        "O1": "cancelled",
        "O2": "paid",
    }


@pytest.mark.slow
def test_fact_order_rerun_after_crash_gives_same_result(spark, mini):
    # t2 寫完 fact 之後當掉（批次紀錄沒寫）→ 重跑 t2。fact 已經是 t2 的結果，
    # 若直接拿來比，t2 每列都會變成晚到事件；重跑要拿「t2 第一次寫入之前」的 fact 比。
    _, paths = mini
    _run(spark, mini, [_order("O1", status="created")], batch_id="t1")
    t2_rows = [
        _order("O1", status="paid", updated=_upd(12)),
        _order("O1", status="completed", updated=_upd(13)),
        _order("O2", status="paid", updated=_upd(12)),
    ]
    first = _run(spark, mini, t2_rows, batch_id="t2")
    fact1 = sorted(_fact(spark, paths).collect())
    q1 = sorted(_quarantine(spark, paths, "t2").collect())
    second = _run(spark, mini, t2_rows, batch_id="t2")
    assert second == first
    assert first.quarantined_by_category == {Category.SUPERSEDED: 1}
    assert first.skipped_rows == 0 and first.balanced
    assert sorted(_fact(spark, paths).collect()) == fact1
    assert sorted(_quarantine(spark, paths, "t2").collect()) == q1
    assert _fact_row(spark, paths, "O1").order_status == "completed"
    # E12：fact 的 order_id 仍唯一
    fact = _fact(spark, paths)
    assert fact.select("order_id").distinct().count() == fact.count() == 2


@pytest.mark.slow
def test_fact_order_force_rerun_after_zero_row_batch_keeps_classification(
    spark, tmp_path
):
    # T6 驗收找到的漏洞（force_hole）：base B paid；day2 只有 B created（往回走，寫進 fact
    # 0 列，MERGE 不產生 commit）；day3 B completed。之後 force 重跑 day2，
    # 必須和第一次一樣是 illegal_transition，不能拿 day3 之後的 fact 比成 late_event。
    data = tmp_path / "data"
    data.mkdir()
    _mini_dataset(data)
    header = ",".join(ORDERS_SCHEMA.fieldNames())

    def write(name, status, upd):
        row = _order("B", status=status, updated=upd)[:12]
        line = ",".join("" if v is None else v for v in row)
        (data / name).write_text(header + "\n" + line + "\n", encoding="utf-8")

    write("orders_base.csv", "paid", "2026-05-01T10:00:00+08:00")
    write("orders_incremental_day1.csv", "paid", "2026-05-01T10:00:00+08:00")
    write("orders_incremental_day2.csv", "created", "2026-05-02T10:00:00+08:00")
    write("orders_incremental_day3.csv", "completed", "2026-05-03T10:00:00+08:00")
    src, paths = CsvSource(spark, data), WarehousePaths(tmp_path / "wh")
    runs = {r.record.batch_id: r.record.counts for r in run_all(spark, src, paths)}
    assert runs["day2"].quarantined_by_category == {Category.ILLEGAL_TRANSITION: 1}
    assert runs["day2"].fact_rows == 0
    again = run_batch(spark, src, paths, 2, force=True).record.counts
    assert again.counts() == runs["day2"].counts()
    q = _quarantine(spark, paths, "day2").collect()
    assert [r.reject_category for r in q] == [Category.ILLEGAL_TRANSITION]
    assert _fact_row(spark, paths, "B").order_status == "completed"
