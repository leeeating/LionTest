"""SparkSession 共用設定與來源讀取介面（ADR-02）的測試。

檔案層級問題（不存在、表頭不符、沒有資料列）要在讀取時整批報錯；
列層級問題不在這裡處理，見 test_validation.py。
"""

from __future__ import annotations

import csv

import pytest
from pipeline import contracts
from pipeline.sources import (
    DEFAULT_DATASET_DIR,
    CsvSource,
    SourceFileError,
    SourceReader,
)
from pipeline.validation import REJECT_REASONS_COL, cast_to_contract

PRODUCTS_HEADER = (
    "product_id,product_name,product_type,destination_country,"
    "destination_city,trip_days,base_price_twd,is_active"
)


def _write_products(dir_path, text, bom=True):
    (dir_path / "products.csv").write_text(("﻿" if bom else "") + text, encoding="utf-8")


def test_session_timezone_is_taipei(spark):
    assert spark.conf.get("spark.sql.session.timeZone") == "Asia/Taipei"


def test_session_disables_csv_column_pruning(spark):
    # 開著時 count() 不檢查欄位數，壞列會被算成 valid（見 counted_as_rejected 測試）
    assert spark.conf.get("spark.sql.csv.parser.columnPruning.enabled") == "false"


def test_session_binds_driver_to_localhost(spark):
    # 不綁的話 driver 用區網 IP，斷網時大的 task 結果傳不回來
    assert spark.conf.get("spark.driver.host") == "localhost"
    assert spark.conf.get("spark.driver.bindAddress") == "127.0.0.1"


def test_session_driver_memory_is_2g(spark):
    # 預設 1g 時全套測試會 OOM；設定要在 JVM 啟動前生效，所以直接看 JVM 的最大 heap
    assert spark.conf.get("spark.driver.memory") == "2g"
    max_mb = spark._jvm.java.lang.Runtime.getRuntime().maxMemory() // 2**20
    assert max_mb > 1024


def test_session_has_delta_enabled(spark):
    assert "DeltaSparkSessionExtension" in spark.conf.get("spark.sql.extensions")


def test_csv_source_satisfies_protocol(source):
    assert isinstance(source, SourceReader)


def test_dim_product_source_schema_is_all_string_contract(source):
    # 讀取層回傳合約自動產生的全字串 schema（外加 _source_error），不手寫第二份
    df = source.products()
    assert df.schema == contracts.to_raw_schema(contracts.PRODUCTS_SCHEMA)
    assert df.columns[:-1] == contracts.PRODUCTS_SCHEMA.fieldNames()


def test_dim_product_source_first_column_has_no_bom(source):
    first = source.products().columns[0]
    assert first == "product_id"
    assert "﻿" not in first


def test_dim_product_source_row_count_matches_file(source):
    # 檔案行數（扣表頭）＝讀到的列數，沒有列被悄悄丟掉
    with open(DEFAULT_DATASET_DIR / "products.csv", encoding="utf-8-sig") as f:
        expected = sum(1 for _ in csv.reader(f)) - 1
    assert source.products().count() == expected


@pytest.mark.parametrize(
    ("method", "args", "schema"),
    [
        ("orders_base", (), contracts.ORDERS_SCHEMA),
        ("orders_incremental", (1,), contracts.ORDERS_SCHEMA),
        ("orders_incremental", (2,), contracts.ORDERS_SCHEMA),
        ("orders_incremental", (3,), contracts.ORDERS_SCHEMA),
        ("members", (), contracts.MEMBERS_SCHEMA),
        ("products", (), contracts.PRODUCTS_SCHEMA),
        ("fx_rates", (), contracts.FX_RATES_SCHEMA),
    ],
)
def test_all_sources_follow_contract_and_conserve_rows(source, method, args, schema):
    raw = getattr(source, method)(*args)
    assert raw.schema == contracts.to_raw_schema(schema)
    valid, rejected = cast_to_contract(raw, schema)
    n_raw = len(raw.collect())
    n_valid, n_rej = len(valid.collect()), len(rejected.collect())
    # 筆數守恆：輸入＝valid＋rejected。count() 與 collect() 兩種都要成立，
    # 因為 CSV 的 count() 走的執行路徑可能不同（column pruning）
    assert n_valid + n_rej == n_raw
    assert (valid.count(), rejected.count(), raw.count()) == (n_valid, n_rej, n_raw)
    # 2026-10-19 實查：只有 orders_base 的 50 列負數金額違反合約（V1，使用者定在合約層擋下）；
    # 其他已知的品質問題（NTD、N/A、coupon -1.0）都在合約之外
    expected_rejected = 50 if method == "orders_base" else 0
    assert n_rej == expected_rejected
    if n_rej:
        reasons = {tuple(r[REJECT_REASONS_COL]) for r in rejected.collect()}
        assert reasons == {("amount:必須大於 0",)}


def test_dirty_timestamp_kept_as_raw_string(source):
    # order_created_at 混有 YYYY/MM/DD 與 Z 結尾，讀取層必須原樣保留
    raw = {r[0] for r in source.orders_base().selectExpr("order_created_at").collect()}
    assert any("/" in v for v in raw)
    assert any(v.endswith("Z") for v in raw)


def test_incremental_day_out_of_range_rejected(spark):
    with pytest.raises(ValueError):
        CsvSource(spark, DEFAULT_DATASET_DIR).orders_incremental(4)


# ------------------------------------------------------------ 檔案層級：整批報錯


def test_dim_product_source_missing_file_raises(spark, tmp_path):
    with pytest.raises(SourceFileError) as e:
        CsvSource(spark, tmp_path).products()
    assert e.value.kind == "missing"


@pytest.mark.parametrize(
    "header",
    [
        PRODUCTS_HEADER.replace("product_id", "prod_id"),  # 欄名不符
        PRODUCTS_HEADER.replace("trip_days,base_price_twd", "base_price_twd,trip_days"),
        PRODUCTS_HEADER + ",extra_col",  # 多一欄
    ],
)
def test_dim_product_source_header_mismatch_raises(spark, tmp_path, header):
    _write_products(tmp_path, header + "\nP1,a,b,c,d,2,100,Y\n")
    with pytest.raises(SourceFileError) as e:
        CsvSource(spark, tmp_path).products()
    assert e.value.kind == "header"


@pytest.mark.parametrize("text", [PRODUCTS_HEADER + "\n", PRODUCTS_HEADER + "\n\n", ""])
def test_dim_product_source_no_data_rows_raises(spark, tmp_path, text):
    _write_products(tmp_path, text, bom=bool(text))
    with pytest.raises(SourceFileError) as e:
        CsvSource(spark, tmp_path).products()
    assert e.value.kind == "empty"


def test_dim_product_source_reads_bom_file_with_correct_header(spark, tmp_path):
    # 對照組：正確表頭＋BOM 可以正常讀，證明表頭測試失敗的原因是表頭不符而非 BOM
    _write_products(tmp_path, PRODUCTS_HEADER + "\nP1,a,b,c,d,2,100,Y\n")
    row = CsvSource(spark, tmp_path).products().first()
    # 讀取層不轉型：trip_days 仍是字串
    assert (row.product_id, row.trip_days, row.is_active) == ("P1", "2", "Y")


def test_dim_product_source_wrong_column_count_row_is_rejected(spark, tmp_path):
    # 欄位數與表頭不符是列層級問題：該列進 rejected，其他列照常
    _write_products(
        tmp_path,
        PRODUCTS_HEADER
        + "\nP1,a,b,c,d,2,100,Y\nP2,a,b,c,d,2,100\nP3,a,b,c,d,2,100,Y,多的\n",
    )
    raw = CsvSource(spark, tmp_path).products()
    valid, rejected = cast_to_contract(raw, contracts.PRODUCTS_SCHEMA)
    assert [r.product_id for r in valid.collect()] == ["P1"]
    got = {r.product_id: r[REJECT_REASONS_COL] for r in rejected.collect()}
    assert got == {
        "P2": ["列格式錯誤:欄位數與表頭不符"],
        "P3": ["列格式錯誤:欄位數與表頭不符"],
    }


@pytest.mark.parametrize(
    "bad_line",
    [
        "P2,a,b,c,d,2,100",  # 少一欄
        "P2,a,b,c,d,2,100,Y,多的",  # 多一欄
        "P2,a,b,c,d,2,100,Y,",  # 結尾多逗號
        'P2,"a\nb",b,c,d,2,100,Y',  # 引號內換行（單行模式下被切成兩列）
        'P2,"a,b,c,d,2,100,Y',  # 引號不成對
    ],
)
def test_dim_product_source_wrong_column_count_counted_as_rejected(
    spark, tmp_path, bad_line
):
    # count() 不能把欄位數不符的列算成 valid，否則「輸入＝寫入＋隔離」的對帳會失真
    _write_products(
        tmp_path, PRODUCTS_HEADER + "\nP1,a,b,c,d,2,100,Y\n" + bad_line + "\n"
    )
    raw = CsvSource(spark, tmp_path).products()
    valid, rejected = cast_to_contract(raw, contracts.PRODUCTS_SCHEMA)
    assert valid.count() == 1
    assert rejected.count() >= 1
    assert valid.count() + rejected.count() == raw.count()
    assert (valid.count(), rejected.count()) == (
        len(valid.collect()),
        len(rejected.collect()),
    )
