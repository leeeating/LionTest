"""dim_date 的測試。"""

from __future__ import annotations

import datetime as dt
import itertools

import pytest
from pipeline.contracts import ORDERS_SCHEMA
from pipeline.dims import (
    all_orders,
    build_dim_date,
    order_dates,
    write_dim_date,
)
from pipeline.sources import INCREMENTAL_DAYS
from pipeline.timeparse import parse_source_timestamp
from pipeline.validation import cast_to_contract
from pyspark.sql import functions as F


def _valid(raw):
    valid, _ = cast_to_contract(raw, ORDERS_SCHEMA)
    return valid


@pytest.fixture(scope="module")
def orders(source):
    """base＋三天增量，全部通過合約轉型的訂單。"""
    return _valid(all_orders(source, INCREMENTAL_DAYS))


def _load(spark, path):
    return spark.read.format("delta").load(str(path))


def _assert_contiguous(rows):
    dates = sorted(r.date for r in rows)
    for prev, cur in itertools.pairwise(dates):
        assert cur - prev == dt.timedelta(days=1)


def test_dim_date_sk_unique_and_contiguous(orders):
    rows = build_dim_date(orders).collect()
    sks = [r.date_sk for r in rows]
    assert len(sks) == len(set(sks))
    _assert_contiguous(rows)
    # date_sk 就是 yyyymmdd
    assert all(r.date_sk == int(r.date.strftime("%Y%m%d")) for r in rows)


def test_dim_date_covers_all_order_and_departure_dates(orders):
    dim = build_dim_date(orders).select("date")
    needed = order_dates(orders)
    # 所有下單時間都解析得出日期（三種格式都吃得下），否則範圍會漏
    assert needed.filter("order_date IS NULL").count() == 0
    all_needed = (
        needed.select(F.col("order_date").alias("date"))
        .union(needed.select(F.col("departure_date").alias("date")))
        .distinct()
    )
    assert all_needed.join(dim, "date", "left_anti").count() == 0


def test_dim_date_range_is_known_fixed_range(orders):
    # 寫死的期望值（2026-10-18 對 candidate_package 實查）：
    # 最早是 base 的下單日 2026-05-01（台北時間），最晚是 day3 的出發日 2026-10-30
    row = build_dim_date(orders).agg(F.min("date"), F.max("date")).first()
    assert (row[0], row[1]) == (dt.date(2026, 5, 1), dt.date(2026, 10, 30))


def test_dim_date_attributes(orders):
    row = build_dim_date(orders).filter("date = DATE'2026-07-04'").first()
    # 2026-07-04 是星期六
    assert (row.year, row.quarter, row.month, row.day) == (2026, 3, 7, 4)
    assert row.day_of_week == 6  # ISO：週一＝1、週日＝7
    assert row.is_weekend is True


def test_dim_date_rerun_is_idempotent(spark, orders, tmp_path):
    path = tmp_path / "dim_date"
    first = sorted(write_dim_date(spark, orders, path).collect())
    second = sorted(write_dim_date(spark, orders, path).collect())
    assert first == second


def test_dim_date_incremental_merge_only_adds_new_dates(spark, source, tmp_path):
    path = tmp_path / "dim_date"
    # 只處理 base 時，不能看到增量的日期（base 最晚出發日是 2026-10-27）
    base_rows = sorted(
        write_dim_date(spark, _valid(all_orders(source, days=())), path).collect()
    )
    assert max(r.date for r in base_rows) == dt.date(2026, 10, 27)

    # 只傳 day1 增量 MERGE（day1 最晚出發日是 2026-10-28）
    after = sorted(
        write_dim_date(spark, _valid(source.orders_incremental(1)), path).collect()
    )
    after_by_sk = {r.date_sk: r for r in after}
    assert len(after_by_sk) == len(after)  # date_sk 不重複
    assert all(after_by_sk[r.date_sk] == r for r in base_rows)  # 既有列不變
    assert set(after_by_sk) - {r.date_sk for r in base_rows} == {20261028}
    _assert_contiguous(after)


def test_dim_date_incremental_merge_fills_gap_to_new_range(spark, source, tmp_path):
    # 新一批的日期與既有範圍不相鄰時，中間的日期也要補上，不能留缺日
    path = tmp_path / "dim_date"
    write_dim_date(spark, _valid(all_orders(source, days=())), path)
    far = spark.createDataFrame(
        [("2026-11-05T10:00:00+08:00", dt.date(2026, 11, 10))],
        "order_created_at STRING, departure_date DATE",
    )
    after = write_dim_date(spark, far, path).collect()
    _assert_contiguous(after)
    dates = [r.date for r in after]
    assert (min(dates), max(dates)) == (dt.date(2026, 5, 1), dt.date(2026, 11, 10))


# 期望值寫死，不經過 order_dates()，避免用同一份實作驗證自己
@pytest.mark.parametrize(
    ("raw", "expected_ts", "expected_date"),
    [
        # +08:00：台北時間原樣
        (
            "2026-06-25T14:02:16+08:00",
            "2026-06-25 14:02:16",
            dt.date(2026, 6, 25),
        ),
        # Z（UTC）跨日：UTC 18:02 = 台北隔天 02:02
        (
            "2026-06-25T18:02:16Z",
            "2026-06-26 02:02:16",
            dt.date(2026, 6, 26),
        ),
        # Z（UTC）不跨日
        (
            "2026-06-25T01:00:00Z",
            "2026-06-25 09:00:00",
            dt.date(2026, 6, 25),
        ),
        # YYYY/MM/DD 已定案：無時區標記視為台北時間（見 process-log）
        (
            "2026/06/22 04:47:19",
            "2026-06-22 04:47:19",
            dt.date(2026, 6, 22),
        ),
        # 無法解析的格式回傳 NULL，不丟錯
        ("22-06-2026", None, None),
    ],
)
def test_dim_date_parse_source_timestamp_formats(
    spark, raw, expected_ts, expected_date
):
    # 在 Spark 內以 session timezone（Asia/Taipei）格式化成字串再比對；
    # 不直接 collect timestamp，因為 PySpark 會轉成執行機器的本地時區（Docker 內是 UTC）
    row = (
        spark.createDataFrame([(raw,)], "raw STRING")
        .select(parse_source_timestamp(F.col("raw")).alias("t"))
        .select(
            F.date_format("t", "yyyy-MM-dd HH:mm:ss").alias("ts"),
            F.to_date("t").alias("d"),
        )
        .first()
    )
    assert (row.ts, row.d) == (expected_ts, expected_date)
