"""dim_member（SCD Type 2）的測試。

期望值有兩種來源，都不呼叫被測的實作：
- 「多快照不放大」的版本數：用純 Python csv 依定案規則獨立計算（_expected_versions）。
- 個別會員：直接看 members.csv 原始列後寫死（列在各測試的註解裡）。
"""

from __future__ import annotations

import csv
import datetime as dt
import itertools
from collections import defaultdict

import pytest
from pipeline.contracts import MEMBERS_SCHEMA, to_raw_schema
from pipeline.dim_member import (
    CURRENT_VALID_TO,
    UNKNOWN_MEMBER_ID,
    UNKNOWN_MEMBER_SK,
    build_dim_member,
    resolve_member_sk,
    write_dim_member,
)
from pipeline.sources import DEFAULT_DATASET_DIR
from pyspark.sql import functions as F

D = dt.date.fromisoformat
SNAPSHOTS = ("2026-04-30", "2026-05-31", "2026-06-30")
LAST = D("2026-06-30")
LEVEL_RANK = {"一般": 1, "銀卡": 2, "金卡": 3, "白金": 4}


# ------------------------------------------------------------------ helpers


def _raw_rows():
    with open(DEFAULT_DATASET_DIR / "members.csv", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _expected_versions(through: str = "2026-06-30") -> dict[str, int]:
    """純 Python 獨立計算：每位會員應有的版本數（變動次數＋1）。

    規則：同日取較高等級；city 'N/A' 當未知，不蓋掉已知值（沿用前值）；
    比較 (member_level, 沿用後的 city)，與前一個快照不同才算變動；
    NULL → 真實 city 算變動（實作的決定，見 dim_member 模組說明）。
    """
    by_day: dict[tuple[str, str], dict] = {}
    for r in _raw_rows():
        if r["extract_date"] > through:
            continue
        key = (r["member_id"], r["extract_date"])
        old = by_day.get(key)
        if (
            old is None
            or LEVEL_RANK[r["member_level"]] > LEVEL_RANK[old["member_level"]]
        ):
            by_day[key] = r
    per_member: dict[str, list[dict]] = defaultdict(list)
    for (mid, _), r in by_day.items():
        per_member[mid].append(r)
    expected = {}
    for mid, rows in per_member.items():
        rows.sort(key=lambda r: r["extract_date"])
        versions, prev, city = 0, None, None
        for r in rows:
            if r["city"] != "N/A":
                city = r["city"]
            state = (r["member_level"], city)
            if state != prev:
                versions += 1
            prev = state
        expected[mid] = versions
    return expected


def _raw_df(spark, rows):
    """以全字串 schema 建原始 DataFrame（和 CsvSource.members() 同形狀）。"""
    # 尾端補 None：to_raw_schema 多一欄 SOURCE_ERROR_COL（合成列都是格式正確的列）
    return spark.createDataFrame(
        [(*r, None) for r in rows], to_raw_schema(MEMBERS_SCHEMA)
    )


def _real_members(source, through: str | None = None, only: str | None = None):
    df = source.members()
    if through is not None:
        df = df.filter(df.extract_date <= through)
    if only is not None:
        df = df.filter(df.extract_date == only)
    return df


def _versions(df, member_id):
    return sorted(
        df.filter(df.member_id == member_id).collect(), key=lambda r: r.valid_from
    )


def _table_rows(spark, path):
    return sorted(spark.read.format("delta").load(str(path)).collect())


@pytest.fixture(scope="module")
def full_dim(spark, source):
    """三批全部處理完的 dim_member（從頭建，changes 就是整張表；不寫 Delta）。"""
    return build_dim_member(spark, source.members(), through=LAST).changes.cache()


# -------------------------------------------------------------------- tests


def test_dim_member_versions_not_inflated_by_snapshots(full_dim):
    expected = _expected_versions()
    got = {
        r.member_id: r["count"]
        for r in full_dim.filter(full_dim.member_sk != UNKNOWN_MEMBER_SK)
        .groupBy("member_id")
        .count()
        .collect()
    }
    assert got == expected
    total = sum(expected.values())
    assert total != 8991  # 原始列數；版本數若等於它，代表每列都開了版本
    assert full_dim.count() == total + 1  # ＋未知會員


def test_dim_member_sk_unique_and_one_current_per_member(full_dim):
    assert full_dim.select("member_sk").distinct().count() == full_dim.count()
    real = full_dim.filter(full_dim.member_sk != UNKNOWN_MEMBER_SK)
    cur = real.filter("is_current").groupBy("member_id").count()
    assert cur.filter("count <> 1").count() == 0
    assert cur.count() == real.select("member_id").distinct().count()


def test_dim_member_versions_are_contiguous(full_dim):
    # 每個版本的 valid_to 等於下一版的 valid_from；最後一版 valid_to = 9999-12-31
    for mid in ("M004004", "M004914", "M000343"):
        vs = _versions(full_dim, mid)
        for a, b in itertools.pairwise(vs):
            assert a.valid_to == b.valid_from
            assert not a.is_current
        assert vs[-1].valid_to == CURRENT_VALID_TO and vs[-1].is_current


def test_dim_member_same_day_conflict_takes_higher_level(full_dim):
    # members.csv：M000096 04-30 有「金卡」「銀卡」兩列；M000296 有「白金」「金卡」
    assert [v.member_level for v in _versions(full_dim, "M000096")] == ["金卡"]
    assert [v.member_level for v in _versions(full_dim, "M000296")] == ["白金"]


def test_dim_member_same_day_conflict_count(spark, source):
    assert (
        build_dim_member(spark, source.members(), through=LAST).stats[
            "same_day_conflicts"
        ]
        == 30
    )


def test_dim_member_birth_placeholder_never_overwrites_real(full_dim):
    # M003842：1999-09-01（04-30）→ 1900-01-01（05-31，等級 銀卡→金卡）
    vs = _versions(full_dim, "M003842")
    assert [v.member_level for v in vs] == ["銀卡", "金卡"]
    assert {v.birth_date for v in vs} == {D("1999-09-01")}
    # M001647：1961-07-15（04-30）→ 1900-01-01（06-30）
    assert {v.birth_date for v in _versions(full_dim, "M001647")} == {D("1961-07-15")}
    # M000552：1900-01-01（04-30）→ 1981-07-25（06-30）：Type 1 補到所有版本
    vs = _versions(full_dim, "M000552")
    assert [v.city for v in vs] == ["新北市", "台南市"]
    assert {v.birth_date for v in vs} == {D("1981-07-25")}


def test_dim_member_city_placeholder_is_not_a_change(full_dim):
    # M001682：白金/新竹市（04-30）→ 白金/N/A（05-31）：不開新版本，沿用新竹市
    vs = _versions(full_dim, "M001682")
    assert [(v.member_level, v.city) for v in vs] == [("白金", "新竹市")]
    # M002473：銀卡/台北市 → 金卡/N/A（06-30）：等級變了開新版，city 沿用台北市
    vs = _versions(full_dim, "M002473")
    assert [(v.member_level, v.city) for v in vs] == [
        ("銀卡", "台北市"),
        ("金卡", "台北市"),
    ]


def test_dim_member_null_city_to_real_opens_new_version(full_dim):
    # M002261：白金/N/A（04-30）→ 白金/台中市（06-30）：只有 city 從未知變已知
    vs = _versions(full_dim, "M002261")
    assert [(v.city, v.valid_from) for v in vs] == [
        (None, D("2015-04-12")),
        ("台中市", D("2026-06-30")),
    ]


def test_dim_member_first_version_starts_at_register_date(full_dim):
    # M004004 register 2025-06-22；第二版（城市 高雄市→台南市）從觀察到的 05-31 起
    vs = _versions(full_dim, "M004004")
    assert [(v.valid_from, v.city) for v in vs] == [
        (D("2025-06-22"), "高雄市"),
        (D("2026-05-31"), "台南市"),
    ]


def _member(mid, level, city, birth, reg, extract, name="測試"):
    return (mid, name, level, city, birth, reg, extract)


def test_dim_member_new_member_in_later_snapshot_starts_at_register_date(spark):
    # 真實資料裡沒有「04-30 之後才第一次出現」的會員，用合成資料
    rows = [
        _member("A1", "一般", "台北市", "1990-01-01", "2020-01-01", "2026-04-30"),
        _member("A1", "一般", "台北市", "1990-01-01", "2020-01-01", "2026-05-31"),
        _member("B1", "銀卡", "高雄市", "1985-05-05", "2026-05-10", "2026-05-31"),
        _member("C1", "金卡", "N/A", "1900-01-01", "2026-06-02", "2026-06-30"),
    ]
    dim = build_dim_member(spark, _raw_df(spark, rows), through=LAST).changes
    assert [(v.valid_from, v.member_level) for v in _versions(dim, "B1")] == [
        (D("2026-05-10"), "銀卡")
    ]
    c1 = _versions(dim, "C1")
    assert [(v.valid_from, v.city, v.birth_date) for v in c1] == [
        (D("2026-06-02"), None, None)
    ]
    assert len(_versions(dim, "A1")) == 1  # 05-31 內容沒變，不開新版


def test_dim_member_resolve_sk_by_order_date(spark, full_dim):
    m4004 = {v.valid_from: v.member_sk for v in _versions(full_dim, "M004004")}
    fact = spark.createDataFrame(
        [
            ("O1", "M004004", D("2025-06-22")),  # 註冊當天 → 第一版
            ("O2", "M004004", D("2026-05-30")),  # 第二版生效前一天 → 第一版
            ("O3", "M004004", D("2026-05-31")),  # 第二版生效當天 → 第二版
            ("O4", "M004004", D("2026-07-02")),  # 目前版本
            ("O5", "M004004", D("2025-06-21")),  # 早於註冊日 → 未知
            ("O6", "M999999", D("2026-05-01")),  # 會員不存在 → 未知
            ("O7", None, D("2026-05-01")),  # member_id NULL → 未知
        ],
        "order_id STRING, member_id STRING, order_date DATE",
    )
    out = resolve_member_sk(fact, full_dim, "order_date")
    got = {r.order_id: r.member_sk for r in out.collect()}
    assert got == {
        "O1": m4004[D("2025-06-22")],
        "O2": m4004[D("2025-06-22")],
        "O3": m4004[D("2026-05-31")],
        "O4": m4004[D("2026-05-31")],
        "O5": UNKNOWN_MEMBER_SK,
        "O6": UNKNOWN_MEMBER_SK,
        "O7": UNKNOWN_MEMBER_SK,
    }
    assert out.count() == fact.count()
    assert out.columns == fact.columns + ["member_sk"]


def test_dim_member_resolve_sk_keeps_fact_row_count_on_real_dim(spark, full_dim):
    # 只驗證「列數不變、沒有落到 -1」：訂單日期由 dim 自己的 valid_from 與 valid_to－1
    # 產生（每個版本的兩端各一張單），所以不寫死 sk；sk 的正確值由
    # test_dim_member_resolve_sk_by_order_date 與 golden 測試負責
    fact = (
        full_dim.filter(full_dim.member_sk != UNKNOWN_MEMBER_SK)
        .selectExpr(
            "member_id", "explode(array(valid_from, valid_to - 1)) AS order_date"
        )
        .filter("order_date < DATE'9999-01-01'")
        .selectExpr("uuid() AS order_id", "member_id", "order_date")
        .cache()
    )
    out = resolve_member_sk(fact, full_dim, "order_date")
    assert out.count() == fact.count()
    assert out.filter(f"member_sk = {UNKNOWN_MEMBER_SK}").count() == 0


# SELECT xxhash64('M004004', DATE'2025-06-22')，在獨立的 Spark session 實算後寫死
M004004_FIRST_SK = 4262623627679752394


def test_dim_member_sk_golden_and_order_independent(spark, source, full_dim):
    first = _versions(full_dim, "M004004")[0]
    assert first.member_sk == M004004_FIRST_SK
    shuffled = source.members().orderBy(F.rand(7)).repartition(7)
    again = build_dim_member(spark, shuffled, through=LAST).changes
    a = {(r.member_id, r.valid_from): r.member_sk for r in full_dim.collect()}
    b = {(r.member_id, r.valid_from): r.member_sk for r in again.collect()}
    assert a == b


def test_dim_member_rerun_is_idempotent(spark, source, tmp_path):
    path = tmp_path / "dim_member"
    write_dim_member(spark, source.members(), path, through=LAST)
    first = _table_rows(spark, path)
    write_dim_member(spark, source.members(), path, through=LAST)
    assert _table_rows(spark, path) == first


def test_dim_member_incremental_equals_all_at_once(spark, source, tmp_path):
    # 逐批餵（04-30 → 05-31）＝ 一次餵到 05-31；不能偷看 06-30
    step, once = tmp_path / "step", tmp_path / "once"
    may31 = D("2026-05-31")
    write_dim_member(
        spark, _real_members(source, only="2026-04-30"), step, through=may31
    )
    write_dim_member(
        spark, _real_members(source, only="2026-05-31"), step, through=may31
    )
    write_dim_member(
        spark, _real_members(source, through="2026-05-31"), once, through=may31
    )
    assert _table_rows(spark, step) == _table_rows(spark, once)
    assert sum(_expected_versions("2026-05-31").values()) + 1 == len(
        _table_rows(spark, step)
    )


def test_dim_member_incremental_three_steps_equals_full(
    spark, source, tmp_path, full_dim
):
    step = tmp_path / "step"
    for day in SNAPSHOTS:
        write_dim_member(spark, _real_members(source, only=day), step, through=D(day))
    assert _table_rows(spark, step) == sorted(full_dim.collect())


def test_dim_member_replaying_older_snapshot_changes_nothing(spark, source, tmp_path):
    # 處理完 06-30 後重送 05-31：舊快照不能把會員「改回去」
    path = tmp_path / "dim_member"
    write_dim_member(spark, source.members(), path, through=LAST)
    before = _table_rows(spark, path)
    res = write_dim_member(
        spark, _real_members(source, only="2026-05-31"), path, through=LAST
    )
    assert _table_rows(spark, path) == before
    assert res.stats["stale_rows_skipped"] == 459


def test_dim_member_placeholder_and_reject_stats(spark, source):
    stats = build_dim_member(spark, source.members(), through=LAST).stats
    assert stats["input_rows"] == 8991
    assert stats["rejected_rows"] == 0
    assert stats["city_placeholder_rows"] == 71
    assert stats["birth_placeholder_rows"] == 81


def test_dim_member_unknown_level_is_rejected_not_guessed(spark):
    rows = [
        _member("A1", "鑽石", "台北市", "1990-01-01", "2020-01-01", "2026-04-30"),
        _member("A2", "一般", "台北市", "1990-01-01", "2020-01-01", "2026-04-30"),
        _member("A3", "一般", "台北市", "1990-01-01", "2026-05-01", "2026-04-30"),
        _member("A4", "一般", "台北市", "1990-02-30", "2020-01-01", "2026-04-30"),
    ]
    res = build_dim_member(spark, _raw_df(spark, rows), through=LAST)
    rejected = {r.member_id: r.reject_reasons for r in res.rejected.collect()}
    assert set(rejected) == {"A1", "A3", "A4"}
    assert any(s.startswith("member_level:") for s in rejected["A1"])
    assert any(s.startswith("register_date:") for s in rejected["A3"])
    assert res.changes.filter("member_id IN ('A1','A3','A4')").count() == 0
    assert res.stats["input_rows"] == 4 and res.stats["rejected_rows"] == 3


def test_dim_member_write_returns_full_table_for_resolve(spark, source, tmp_path):
    # 逐批處理到 06-30 後，回傳的 table 必須是整張表；
    # 若只回傳這批受影響的會員，06-30 沒出現的會員會在 resolve 時全部落到 -1
    path = tmp_path / "dim_member"
    for day in SNAPSHOTS:
        res = write_dim_member(
            spark, _real_members(source, only=day), path, through=D(day)
        )
    expected_total = sum(_expected_versions().values()) + 1
    assert res.table.count() == expected_total
    fact = (
        source.members()
        .select("member_id")
        .distinct()
        .withColumn("order_date", F.lit(D("2026-07-01")))
    )
    out = resolve_member_sk(fact, res.table, "order_date")
    assert out.count() == 8000
    assert out.filter(f"member_sk = {UNKNOWN_MEMBER_SK}").count() == 0


def test_dim_member_through_excludes_future_snapshots(spark, source, tmp_path):
    # 傳入全部三批、through=05-31：必須和「只傳到 05-31 的資料」結果相同
    may31 = D("2026-05-31")
    all_in, cut = tmp_path / "all_in", tmp_path / "cut"
    res = write_dim_member(spark, source.members(), all_in, through=may31)
    write_dim_member(
        spark, _real_members(source, through="2026-05-31"), cut, through=may31
    )
    assert _table_rows(spark, all_in) == _table_rows(spark, cut)
    assert res.stats["rows_after_through"] == 502
    agg = (
        res.table.filter(f"member_sk <> {UNKNOWN_MEMBER_SK}")
        .agg(
            F.max("valid_from").alias("vf"),
            F.max("last_seen_extract_date").alias("seen"),
        )
        .first()
    )
    assert agg.vf <= may31 and agg.seen == may31


def test_dim_member_through_keeps_unparseable_extract_date_as_rejected(spark):
    # extract_date 解析不了的列不能被 through 的過濾吃掉，要進 rejected
    rows = [
        _member("A1", "一般", "台北市", "1990-01-01", "2020-01-01", "2026-04-30"),
        _member("A2", "一般", "台北市", "1990-01-01", "2020-01-01", "2026/04/30"),
        _member("A3", "一般", "台北市", "1990-01-01", "2020-01-01", "2026-05-31"),
    ]
    res = build_dim_member(spark, _raw_df(spark, rows), through=D("2026-04-30"))
    assert [r.member_id for r in res.rejected.collect()] == ["A2"]
    assert res.stats["input_rows"] == 2 and res.stats["rows_after_through"] == 1
    assert {r.member_id for r in res.changes.collect()} == {"A1", UNKNOWN_MEMBER_ID}


def test_dim_member_more_than_two_versions(spark):
    rows = [
        # X：一般 → 金卡 → 一般：3 版
        _member("X1", "一般", "台北市", "1990-01-01", "2020-01-01", "2026-04-30"),
        _member("X1", "金卡", "台北市", "1990-01-01", "2020-01-01", "2026-05-31"),
        _member("X1", "一般", "台北市", "1990-01-01", "2020-01-01", "2026-06-30"),
        # Y：台北市 → N/A → 高雄市：N/A 不算變動，2 版
        _member("Y1", "銀卡", "台北市", "1990-01-01", "2021-03-03", "2026-04-30"),
        _member("Y1", "銀卡", "N/A", "1990-01-01", "2021-03-03", "2026-05-31"),
        _member("Y1", "銀卡", "高雄市", "1990-01-01", "2021-03-03", "2026-06-30"),
    ]
    dim = build_dim_member(spark, _raw_df(spark, rows), through=LAST).changes
    x = [
        (v.member_level, v.valid_from, v.valid_to, v.is_current)
        for v in _versions(dim, "X1")
    ]
    assert x == [
        ("一般", D("2020-01-01"), D("2026-05-31"), False),
        ("金卡", D("2026-05-31"), D("2026-06-30"), False),
        ("一般", D("2026-06-30"), CURRENT_VALID_TO, True),
    ]
    y = [(v.city, v.valid_from, v.valid_to) for v in _versions(dim, "Y1")]
    assert y == [
        ("台北市", D("2021-03-03"), D("2026-06-30")),
        ("高雄市", D("2026-06-30"), CURRENT_VALID_TO),
    ]
