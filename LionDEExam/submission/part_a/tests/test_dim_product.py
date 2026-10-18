"""dim_product（Type 1）的測試。"""

from __future__ import annotations

import pytest
from pipeline.contracts import PRODUCTS_SCHEMA
from pipeline.dims import (
    UNKNOWN_PRODUCT_ID,
    UNKNOWN_PRODUCT_SK,
    DuplicateKeyError,
    build_dim_product,
    resolve_product_sk,
    write_dim_product,
)
from pipeline.sources import DEFAULT_DATASET_DIR, CsvSource
from pipeline.validation import cast_to_contract

# xxhash64("P00001")，由 Spark 4.2 實算後寫死
P00001_SK = 3295984988433592048


def _valid(src):
    """依合約轉型；真實主檔不該有違規列。"""
    valid, rejected = cast_to_contract(src.products(), PRODUCTS_SCHEMA)
    assert rejected.count() == 0
    return valid


def _products_lines():
    """回傳原始 products.csv 的表頭與資料列（去掉 BOM）。"""
    lines = (
        (DEFAULT_DATASET_DIR / "products.csv")
        .read_text(encoding="utf-8-sig")
        .splitlines()
    )
    return lines[0], lines[1:]


def _write_products(dir_path, header, rows):
    text = "\ufeff" + "\n".join([header, *rows]) + "\n"
    (dir_path / "products.csv").write_text(text, encoding="utf-8")


def _sk_map(df):
    return {r.product_id: r.product_sk for r in df.collect()}


def _rows(spark, path):
    return sorted(spark.read.format("delta").load(str(path)).collect())


def test_dim_product_row_count_is_distinct_products_plus_unknown(
    spark, source, tmp_path
):
    path = tmp_path / "dim_product"
    write_dim_product(spark, _valid(source), path)
    expected = source.products().select("product_id").distinct().count() + 1
    assert spark.read.format("delta").load(str(path)).count() == expected


def test_dim_product_sk_unique_and_not_null(spark, source):
    df = build_dim_product(spark, _valid(source))
    assert df.filter("product_sk IS NULL").count() == 0
    assert df.select("product_sk").distinct().count() == df.count()


def test_dim_product_has_identifiable_unknown_row(spark, source):
    df = build_dim_product(spark, _valid(source))
    unknown = df.filter(df.product_id == UNKNOWN_PRODUCT_ID).collect()
    assert len(unknown) == 1
    assert unknown[0]["product_sk"] == UNKNOWN_PRODUCT_SK


def test_dim_product_types_converted(spark, source):
    types = dict(build_dim_product(spark, _valid(source)).dtypes)
    assert types["product_sk"] == "bigint"
    assert types["trip_days"] == "int"
    assert types["base_price_twd"].startswith("decimal")
    assert types["is_active"] == "boolean"


def test_dim_product_is_active_maps_y_n_without_loss(spark, source):
    df = build_dim_product(spark, _valid(source)).filter(
        f"product_id <> '{UNKNOWN_PRODUCT_ID}'"
    )
    raw = source.products()
    assert df.filter("is_active IS NULL").count() == 0
    assert df.filter("is_active").count() == raw.filter("is_active = 'Y'").count()


def test_dim_product_rerun_is_idempotent(spark, source, tmp_path):
    path = tmp_path / "dim_product"
    write_dim_product(spark, _valid(source), path)
    first = _rows(spark, path)
    write_dim_product(spark, _valid(source), path)
    second = _rows(spark, path)
    assert first == second


def test_dim_product_sk_independent_of_input_order_and_subset(spark, source, tmp_path):
    # 輸入打亂順序並只取一半重建，同一 product_id 的 sk 必須不變；
    # 若 sk 用 row_number／monotonically_increasing_id，這裡會對不上
    full = _sk_map(build_dim_product(spark, _valid(source)))
    header, rows = _products_lines()
    _write_products(tmp_path, header, list(reversed(rows))[::2])
    partial = _sk_map(build_dim_product(spark, _valid(CsvSource(spark, tmp_path))))
    assert len(partial) == len(rows[::2]) + 1
    assert all(full[pid] == sk for pid, sk in partial.items())


def test_dim_product_sk_golden_value(spark, source):
    # 固定已知值：xxhash64('P00001')（seed 42）。換演算法或改成序號都會讓這裡失敗
    assert _sk_map(build_dim_product(spark, _valid(source)))["P00001"] == P00001_SK


def test_dim_product_type1_update_overwrites_attributes(spark, tmp_path):
    header, rows = _products_lines()
    src_dir, out = tmp_path / "src", tmp_path / "dim_product"
    src_dir.mkdir()
    _write_products(src_dir, header, rows)
    before = {
        r.product_id: r
        for r in write_dim_product(
            spark, _valid(CsvSource(spark, src_dir)), out
        ).collect()
    }

    # 第二版主檔：只改 P00001 的 product_name
    changed = [
        r.replace("洛杉磯2日訂房", "洛杉磯2日訂房（改版）", 1)
        if r.startswith("P00001,")
        else r
        for r in rows
    ]
    assert changed != rows
    _write_products(src_dir, header, changed)
    after = {
        r.product_id: r
        for r in write_dim_product(
            spark, _valid(CsvSource(spark, src_dir)), out
        ).collect()
    }

    assert len(after) == len(before)
    assert after["P00001"].product_name == "洛杉磯2日訂房（改版）"
    assert after["P00001"].product_sk == before["P00001"].product_sk
    assert after["P00002"] == before["P00002"]


def test_dim_product_resolve_sk_falls_back_to_unknown(spark, source):
    dim = build_dim_product(spark, _valid(source))
    fact = spark.createDataFrame(
        [("O1", "P00001"), ("O2", "P99999"), ("O3", None)],
        "order_id STRING, product_id STRING",
    )
    got = {r.order_id: r.product_sk for r in resolve_product_sk(fact, dim).collect()}
    assert got == {"O1": P00001_SK, "O2": UNKNOWN_PRODUCT_SK, "O3": UNKNOWN_PRODUCT_SK}


def test_dim_product_duplicate_product_id_raises(spark, tmp_path):
    # 主檔重複的自然鍵沒有可靠的取捨規則，整批停下而不是任選一列
    header, rows = _products_lines()
    _write_products(tmp_path, header, rows + [rows[0].replace("洛杉磯", "舊金山", 1)])
    with pytest.raises(DuplicateKeyError, match="P00001"):
        build_dim_product(spark, _valid(CsvSource(spark, tmp_path)))


def test_dim_product_master_using_reserved_unknown_id_raises(spark, tmp_path):
    # 主檔若真的有 product_id = UNKNOWN，會和「未知產品」列撞自然鍵，MERGE 結果不可預期
    header, rows = _products_lines()
    _write_products(
        tmp_path, header, rows + [f"{UNKNOWN_PRODUCT_ID},x,團體旅遊,日本,東京,3,1000,Y"]
    )
    with pytest.raises(DuplicateKeyError, match=UNKNOWN_PRODUCT_ID):
        build_dim_product(spark, _valid(CsvSource(spark, tmp_path)))
