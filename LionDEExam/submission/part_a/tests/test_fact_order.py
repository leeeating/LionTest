"""fact_order 初始載入（base）、隔離表、對帳的測試。

期望值的來源都不呼叫被測的實作：
- base 的對帳數字：用純 Python csv 依定案規則獨立計算（_expected_base）。
- 匯率換算：從 fx_rates.csv 查出當天匯率後手算、寫死（列在各測試的註解裡）。
- 撞號、找不到匯率、產品清單壞列：用合成資料。
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from delta.tables import DeltaTable
from pipeline import fact_order
from pipeline.contracts import ORDERS_SCHEMA, to_raw_schema
from pipeline.dim_member import UNKNOWN_MEMBER_SK
from pipeline.dims import UNKNOWN_PRODUCT_SK
from pipeline.fact_order import (
    BASE_AS_OF,
    BASE_BATCH_ID,
    Category,
    ReferenceDataError,
    WarehousePaths,
    load_base,
    load_order_batch,
)
from pipeline.sources import DEFAULT_DATASET_DIR, CsvSource
from pyspark.sql import functions as F

TPE = dt.timezone(dt.timedelta(hours=8))
CENT = Decimal("0.01")

# ------------------------------------------------------------------ 獨立計算


def _csv(name):
    with open(DEFAULT_DATASET_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _ts(s: str) -> dt.datetime:
    """三種來源時間格式：+08:00、Z（UTC）、無時區（台北）。"""
    if "/" in s:
        return dt.datetime.strptime(s, "%Y/%m/%d %H:%M:%S").replace(tzinfo=TPE)
    return dt.datetime.fromisoformat(s)


def _content(r):
    """除了 updated_at 以外的內容；下單時間比較換算後的時刻，不比較字串。"""
    return tuple(
        _ts(v) if k == "order_created_at" else v
        for k, v in r.items()
        if k != "updated_at"
    )


def _identity(r):
    return (r["member_id"], _ts(r["order_created_at"]), Decimal(r["amount"]))


def _expected_base():
    rows = _csv("orders_base.csv")
    fx = {
        (r["rate_date"], r["currency"]): Decimal(r["rate_to_twd"])
        for r in _csv("fx_rates.csv")
    }
    products = {r["product_id"] for r in _csv("products.csv")}
    register = {}
    for m in _csv("members.csv"):
        register[m["member_id"]] = min(
            register.get(m["member_id"], "9999"), m["register_date"]
        )

    groups = collections.defaultdict(list)
    for r in rows:
        groups[r["order_id"]].append(r)

    kept, cats = [], collections.Counter()
    for rs in groups.values():
        if len({_identity(r) for r in rs}) > 1:
            cats["collision"] += len(rs)
            continue
        rs = sorted(rs, key=lambda r: _ts(r["updated_at"]), reverse=True)
        for r in rs[1:]:
            cats["duplicate" if _content(r) == _content(rs[0]) else "superseded"] += 1
        kept.append(rs[0])

    fact, total = [], Decimal(0)
    unknown_product = unknown_member = 0
    for r in kept:
        day = _ts(r["order_created_at"]).astimezone(TPE).date().isoformat()
        rate = (
            Decimal(1)
            if r["currency"] in ("TWD", "NTD")
            else fx.get((day, r["currency"]))
        )
        if rate is None:
            cats["fx_missing"] += 1
            continue
        total += (Decimal(r["amount"]) * rate).quantize(CENT, ROUND_HALF_UP)
        unknown_product += r["product_id"] not in products
        reg = register.get(r["member_id"])
        unknown_member += reg is None or day < reg
        fact.append(r)
    return {
        "input": len(rows),
        "fact": len(fact),
        "categories": dict(cats),
        "amount_twd_sum": total,
        "unknown_product": unknown_product,
        "unknown_member": unknown_member,
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
    # base 去重後每個 TWD、NTD 的 order_id 都在 fact（base 沒有撞號，見對帳測試）
    raw_ids = {
        r["order_id"]
        for r in _csv("orders_base.csv")
        if r["currency"] in ("TWD", "NTD")
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
    # fact 的 order_id 唯一
    assert fact.select("order_id").distinct().count() == fact.count()


def test_fact_order_base_has_v7_duplicates_and_no_collisions(base_run, expected):
    _, rec = base_run
    # V7：40 組完全相同的重複，多出 40 列；base 內部沒有撞號、沒有找不到匯率
    assert expected["categories"] == {"duplicate": 40}
    assert rec.quarantined_by_category == {Category.DUPLICATE: 40}


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
            ["重複，保留 updated_at 最新一列"],
        ),
        (
            "ORD00012637",
            "2026-06-15T09:27:51+08:00",
            "2026-06-14T19:17:51+08:00",
            "86020.0",
            "duplicate",
            ["重複，保留 updated_at 最新一列"],
        ),
    ]


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


@pytest.fixture
def mini(spark, tmp_path):
    ds = tmp_path / "ds"
    ds.mkdir()
    return CsvSource(spark, _mini_dataset(ds)), WarehousePaths(tmp_path / "wh")


def _run(spark, mini, rows, batch_id="t1"):
    src, paths = mini
    return load_order_batch(
        spark,
        src,
        batch_id=batch_id,
        orders=_orders_df(spark, rows),
        as_of=dt.date(2026, 4, 30),
        paths=paths,
    )


def test_fact_order_collision_within_batch_quarantines_whole_group(spark, mini):
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
    rec = _run(spark, mini, rows)
    _, paths = mini
    q = {
        (r.order_id, r.member_id, r.amount): (r.reject_category, r.reject_reasons)
        for r in _quarantine(spark, paths, "t1").collect()
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
            ["重複，保留 updated_at 最新一列"],
        ),
    }
    assert sorted(r.order_id for r in _fact(spark, paths).collect()) == ["O2", "O4"]
    assert rec.quarantined_by_category == {Category.COLLISION: 4, Category.DUPLICATE: 1}
    assert rec.input_rows == 7 and rec.fact_rows == 2 and rec.balanced


def test_fact_order_collision_with_existing_fact_is_quarantined(spark, mini):
    # 撞號判斷可重用：第二批的 O1 與 fact 既有的 O1 會員不同 → 隔離，fact 保留第一批的值
    _run(spark, mini, [_order("O1", member="M1")], batch_id="t1")
    rec = _run(
        spark,
        mini,
        [_order("O1", member="M2", updated="2026-05-02T09:00:00+08:00")],
        batch_id="t2",
    )
    _, paths = mini
    assert rec.quarantined_by_category == {Category.COLLISION_EXISTING: 1}
    assert _fact_row(spark, paths, "O1").member_id == "M1"
    [r] = _quarantine(spark, paths, "t2").collect()
    assert r.reject_reasons == [
        "撞號：與既有 fact 同 order_id，但會員、下單時間或金額不同"
    ]


def test_fact_order_missing_fx_rate_is_quarantined(spark, mini):
    rows = [
        _order("O1", currency="USD", amount="10.0"),  # 05-01 有 USD 30.5 → 305.00
        _order(
            "O2", currency="USD", amount="10.0", created="2026-05-02T10:00:00+08:00"
        ),  # 05-02 沒有匯率
        _order("O3", currency="EUR", amount="10.0"),  # 匯率表沒有 EUR
        _order("O4", currency="NTD", amount="10.0"),  # NTD 固定 1
        # O5：UTC 04-30 18:00 ＝ 台北 05-01 02:00 → 用 05-01 的匯率
        _order("O5", currency="JPY", amount="1000.0", created="2026-04-30T18:00:00Z"),
    ]
    rec = _run(spark, mini, rows)
    _, paths = mini
    q = {
        r.order_id: (r.reject_category, r.reject_reasons)
        for r in _quarantine(spark, paths, "t1").collect()
    }
    assert q == {
        "O2": (
            Category.FX_MISSING,
            ["currency:下單日 2026-05-02 找不到 USD 對 TWD 的匯率"],
        ),
        "O3": (
            Category.FX_MISSING,
            ["currency:下單日 2026-05-01 找不到 EUR 對 TWD 的匯率"],
        ),
    }
    got = {r.order_id: r.amount_twd for r in _fact(spark, paths).collect()}
    assert got == {
        "O1": Decimal("305.00"),
        "O4": Decimal("10.00"),
        "O5": Decimal("200.00"),
    }
    assert rec.balanced and rec.amount_twd_sum == Decimal("515.00")


def test_fact_order_contract_violation_is_quarantined_with_raw_values(spark, mini):
    rows = [_order("O1", amount="1e2"), _order("O2")]
    rec = _run(spark, mini, rows)
    _, paths = mini
    [r] = _quarantine(spark, paths, "t1").collect()
    assert (r.order_id, r.amount, r.reject_category) == ("O1", "1e2", Category.CONTRACT)
    assert r.reject_reasons == ["amount:型別不符（應為 decimal(18,2)）"]
    assert rec.input_rows == 2 and rec.fact_rows == 1 and rec.balanced


@pytest.mark.parametrize(
    ("dataset", "match"),
    [
        # 產品清單有違規列（trip_days 不是整數）
        (
            {"products_rows": ["P00001,東京5日,團體旅遊,日本,東京,abc,50000,Y"]},
            "products",
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
        ),
        # 匯率表同日同幣別有兩個匯率：不知道用哪一個，join 還會讓 fact 列數膨脹
        ({"fx_rows": [*FX_ROWS, "2026-05-01,USD,31.0"]}, "fx_rates"),
    ],
    ids=["product_rejected", "product_duplicate", "fx_duplicate"],
)
def test_fact_order_bad_reference_data_stops_whole_batch(
    spark, tmp_path, dataset, match
):
    ds = tmp_path / "ds"
    ds.mkdir()
    _mini_dataset(ds, **dataset)
    paths = WarehousePaths(tmp_path / "wh")
    with pytest.raises(ReferenceDataError, match=match):
        load_order_batch(
            spark,
            CsvSource(spark, ds),
            batch_id="t1",
            orders=_orders_df(spark, [_order("O1", currency="USD", amount="10.0")]),
            as_of=dt.date(2026, 4, 30),
            paths=paths,
        )
    for table in (paths.fact_order, paths.quarantine, paths.dim_product):
        assert not DeltaTable.isDeltaTable(spark, str(table))


def test_fact_order_quality_rules_quarantine_with_raw_values(spark, mini, monkeypatch):
    # A-3 的掛載點：塞兩條規則，其中一條要用 as_of
    def negative_amount(as_of):
        return F.when(F.col("amount") < 0, F.lit("amount:負數"))

    def completed_before_departure(as_of):
        return F.when(
            (F.col("order_status") == "completed")
            & (F.col("departure_date") > F.lit(as_of)),
            F.concat(F.lit("order_status:completed 但出發日晚於 "), F.lit(str(as_of))),
        )

    monkeypatch.setattr(
        fact_order,
        "ORDER_QUALITY_RULES",
        (negative_amount, completed_before_departure),
    )
    rows = [
        _order("O1", amount="-5.0"),
        _order("O2", status="completed"),  # 出發日 2026-06-01 > as_of 2026-04-30
        _order("O3", amount="-7.50", status="completed"),  # 兩條都命中
        _order("O4"),
    ]
    rec = _run(spark, mini, rows)
    _, paths = mini
    q = {
        r.order_id: (r.amount, r.reject_category, r.reject_reasons)
        for r in _quarantine(spark, paths, "t1").collect()
    }
    late = "order_status:completed 但出發日晚於 2026-04-30"
    assert q == {
        "O1": ("-5.0", Category.QUALITY, ["amount:負數"]),
        "O2": ("1000.0", Category.QUALITY, [late]),
        "O3": ("-7.50", Category.QUALITY, ["amount:負數", late]),
    }
    assert [r.order_id for r in _fact(spark, paths).collect()] == ["O4"]
    assert rec.quarantined_by_category == {Category.QUALITY: 3}
    assert rec.input_rows == 4 and rec.fact_rows == 1 and rec.balanced


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


def test_fact_order_invalid_batch_id_is_rejected(spark, mini):
    with pytest.raises(ValueError, match="batch_id"):
        _run(spark, mini, [_order("O1")], batch_id="x' OR '1'='1")


def test_base_as_of_is_last_base_day():
    assert BASE_AS_OF == dt.date(2026, 6, 30)
