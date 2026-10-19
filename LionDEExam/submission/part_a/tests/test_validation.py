"""cast_to_contract（列層級違規 → rejected）的測試。

每種違規各一條，期望的原因字串寫死。用 orders 合約，因為它同時有必填欄、整數、Decimal、日期。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pipeline.contracts import ORDERS_SCHEMA, SOURCE_ERROR_COL, to_raw_schema
from pipeline.timeparse import parse_source_timestamp
from pipeline.validation import REJECT_REASONS_COL, cast_to_contract
from pyspark.sql import functions as F

GOOD = {
    "order_id": "ORD1",
    "member_id": "M1",
    "product_id": "P00001",
    "channel": "app",
    "order_status": "paid",
    "quantity": "3",
    "currency": "USD",
    "amount": "15452.42",
    "coupon_discount": "950.0",
    "order_created_at": "2026/06/22 04:47:19",
    "departure_date": "2026-07-08",
    "updated_at": "2026-06-25T23:14:16+08:00",
    SOURCE_ERROR_COL: None,
}


def _raw(spark, *overrides):
    rows = [{**GOOD, "order_id": f"ORD{i}", **o} for i, o in enumerate(overrides)]
    schema = to_raw_schema(ORDERS_SCHEMA)
    return spark.createDataFrame(
        [tuple(r[c] for c in schema.fieldNames()) for r in rows], schema
    )


def _reasons(spark, **override):
    valid, rejected = cast_to_contract(_raw(spark, override), ORDERS_SCHEMA)
    rows = rejected.collect()
    assert valid.count() + len(rows) == 1
    return rows[0][REJECT_REASONS_COL] if rows else []


def test_valid_row_is_cast_to_contract_types(spark):
    valid, rejected = cast_to_contract(_raw(spark, {}), ORDERS_SCHEMA)
    assert rejected.count() == 0
    row = valid.first()
    assert (row.quantity, row.amount, row.departure_date) == (
        3,
        Decimal("15452.42"),
        dt.date(2026, 7, 8),
    )
    # 合約是 StringType 的欄位原樣保留（時間格式留給 silver 層）
    assert row.order_created_at == "2026/06/22 04:47:19"
    # 欄名、欄序、型別與合約相同（nullability 不比，見 cast_to_contract docstring）
    assert [(f.name, f.dataType) for f in valid.schema] == [
        (f.name, f.dataType) for f in ORDERS_SCHEMA
    ]


def test_type_error_is_rejected(spark):
    assert _reasons(spark, quantity="abc") == ["quantity:型別不符（應為 int）"]


def test_decimal_scale_overflow_is_rejected_not_rounded(spark):
    # Spark 的 try_cast 會把 100.456 四捨五入成 100.46，這裡必須擋下
    assert _reasons(spark, amount="100.456") == ["amount:小數位超過 2 位"]


def test_required_null_is_rejected(spark):
    assert _reasons(spark, member_id=None) == ["member_id:必填空值"]


def test_optional_null_is_valid(spark):
    assert (
        _reasons(spark, coupon_discount=None, departure_date=None, channel=None) == []
    )


def test_scientific_notation_is_rejected(spark):
    # 1e2 算違規：上游 DB 匯出的金額應是一般十進位字串，出現科學記號代表中間經過浮點數
    # 轉換，可能已經失真；Spark 會把它轉成 100.00，不擋就看不出來
    assert _reasons(spark, amount="1e2") == ["amount:型別不符（應為 decimal(18,2)）"]


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        # Spark 會把帶時間的字串 cast 成日期，必須擋下
        (
            {"departure_date": "2026-07-08T00:00:00"},
            ["departure_date:型別不符（應為 date）"],
        ),
        ({"departure_date": "2026/07/08"}, ["departure_date:型別不符（應為 date）"]),
        # 格式對但日期不存在
        ({"departure_date": "2026-02-30"}, ["departure_date:型別不符（應為 date）"]),
        # Spark 會 trim 空白、會接受 3.0 以外的寬鬆寫法；整數只接受純數字
        ({"quantity": " 3"}, ["quantity:型別不符（應為 int）"]),
        ({"quantity": "3.0"}, ["quantity:型別不符（應為 int）"]),
        ({"quantity": "99999999999"}, ["quantity:型別不符（應為 int）"]),
        ({"amount": "1,000.00"}, ["amount:型別不符（應為 decimal(18,2)）"]),
        ({"amount": "12345678901234567.0"}, ["amount:整數位超過 16 位"]),
        # 正號、整數寫法是合法格式；負數格式合法，但違反「必須大於 0」（V1）
        ({"amount": "-3087159.0"}, ["amount:必須大於 0"]),
        ({"amount": "+5"}, []),
        ({"coupon_discount": "-1.0"}, []),
    ],
)
def test_format_edge_cases(spark, override, expected):
    assert _reasons(spark, **override) == expected


def test_multiple_reasons_are_all_listed(spark):
    got = _reasons(spark, quantity="abc", amount="1.234", member_id=None, order_id=None)
    assert sorted(got) == sorted(
        [
            "order_id:必填空值",
            "member_id:必填空值",
            "quantity:型別不符（應為 int）",
            "amount:小數位超過 2 位",
        ]
    )


def test_source_error_row_is_rejected(spark):
    assert _reasons(spark, **{SOURCE_ERROR_COL: "P2,a,b"}) == [
        "列格式錯誤:欄位數與表頭不符"
    ]


def test_row_count_is_conserved_and_raw_values_kept(spark):
    raw = _raw(
        spark,
        {},
        {"quantity": "abc"},
        {},
        {"amount": "100.456", "member_id": None},
        {"departure_date": None},
    )
    valid, rejected = cast_to_contract(raw, ORDERS_SCHEMA)
    assert valid.count() == 3
    assert rejected.count() == 2
    assert valid.count() + rejected.count() == raw.count()
    # rejected 保留所有原始字串欄位（含 _source_error），再加上原因欄
    assert rejected.columns == raw.columns + [REJECT_REASONS_COL]
    bad = {r.order_id: r for r in rejected.collect()}
    assert bad["ORD1"].quantity == "abc"
    assert bad["ORD3"].amount == "100.456"


def test_missing_contract_column_raises(spark):
    with pytest.raises(ValueError, match="缺少合約欄位"):
        cast_to_contract(_raw(spark, {}).drop("amount"), ORDERS_SCHEMA)


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t"])
def test_required_blank_string_is_rejected(spark, blank):
    # 只有空白的必填字串欄位視為空值，且不重複記型別不符
    assert _reasons(spark, product_id=blank) == ["product_id:必填空值"]


def test_required_blank_non_string_reports_only_null(spark):
    assert _reasons(spark, quantity=" ") == ["quantity:必填空值"]


def test_optional_blank_non_string_is_type_error(spark):
    # 可空欄位的空白不是「沒填」，而是寫了一個不合法的值；不能悄悄變成 NULL
    assert _reasons(spark, coupon_discount=" ") == [
        "coupon_discount:型別不符（應為 decimal(18,2)）"
    ]


_TS_REASON = ":時間格式無法解析（應為 yyyy-MM-dd'T'HH:mm:ssXXX、yyyy/MM/dd HH:mm:ss）"


@pytest.mark.parametrize(
    "value",
    [
        "2026-06-25T14:02:16+08:00",
        "2026-06-25T06:02:16Z",
        "2026/06/22 04:47:19",
    ],
)
@pytest.mark.parametrize("column", ["order_created_at", "updated_at"])
def test_source_timestamp_accepted_formats(spark, column, value):
    assert _reasons(spark, **{column: value}) == []


@pytest.mark.parametrize(
    "value",
    [
        "2026-06-25 14:02:16",  # 少 T 也沒時區
        "2026-06-25T14:02:16",  # 沒有時區標記的 ISO（不在三種格式內）
        "2026/06/22",  # 只有日期
        "22/06/2026 04:47:19",
        "2026-06-25T14:02:16.123+08:00",  # 帶毫秒
        "2026-13-01T00:00:00+08:00",  # 月份不存在
        "not a time",
    ],
)
@pytest.mark.parametrize("column", ["order_created_at", "updated_at"])
def test_unparseable_source_timestamp_is_rejected(spark, column, value):
    assert _reasons(spark, **{column: value}) == [column + _TS_REASON]


def test_unparseable_timestamp_never_reaches_valid(spark):
    # valid 裡的下單時間一定解析得出來，dim_date 的範圍與 fact 的 date_sk 不會悄悄漏掉
    raw = _raw(spark, {}, {"order_created_at": "garbage"}, {"updated_at": "x"})
    valid, rejected = cast_to_contract(raw, ORDERS_SCHEMA)
    assert valid.count() == 1
    assert rejected.count() == 2
    assert (
        valid.filter(parse_source_timestamp(F.col("order_created_at")).isNull()).count()
        == 0
    )


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        # Java regex 的 $ 會吻合結尾換行之前的位置；結尾帶換行的值必須進 rejected
        ({"quantity": "3\n"}, ["quantity:型別不符（應為 int）"]),
        ({"amount": "10.00\n"}, ["amount:型別不符（應為 decimal(18,2)）"]),
        ({"departure_date": "2026-07-01\n"}, ["departure_date:型別不符（應為 date）"]),
        ({"quantity": "3\r\n"}, ["quantity:型別不符（應為 int）"]),
        (
            {"order_created_at": "2026-06-25T14:02:16+08:00\n"},
            ["order_created_at" + _TS_REASON],
        ),
        (
            {"order_created_at": "2026/06/22 04:47:19\n"},
            ["order_created_at" + _TS_REASON],
        ),
        ({"updated_at": "2026-06-25T06:02:16Z\n"}, ["updated_at" + _TS_REASON]),
    ],
)
def test_trailing_newline_is_rejected(spark, override, expected):
    assert _reasons(spark, **override) == expected


STATUS_ALLOWED = "order_status:值不在允許範圍（created、paid、cancelled、completed）"
CURRENCY_ALLOWED = "currency:值不在允許範圍（TWD、NTD、USD、JPY）"


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"order_status": "PAID"}, [STATUS_ALLOWED]),  # 大小寫不同
        ({"order_status": "paid "}, [STATUS_ALLOWED]),  # 結尾空白
        ({"order_status": "refunded"}, [STATUS_ALLOWED]),
        ({"currency": "EUR"}, [CURRENCY_ALLOWED]),
        ({"currency": "usd"}, [CURRENCY_ALLOWED]),
        ({"currency": "NTD"}, []),  # NTD 是 base 裡 TWD 的別名（V4），保留
        ({"order_status": "completed", "currency": "TWD"}, []),
        # 空值只記「必填空值」，不重複記「值不在允許範圍」
        ({"order_status": ""}, ["order_status:必填空值"]),
    ],
)
def test_allowed_values_are_enforced(spark, override, expected):
    assert _reasons(spark, **override) == expected


def test_order_status_allowed_values_share_state_machine_source():
    # 合約的允許值直接引用狀態機的 STATUSES，不是另一份清單
    from pipeline.contracts import ALLOWED_VALUES_KEY
    from pipeline.order_status import STATUSES

    meta = ORDERS_SCHEMA["order_status"].metadata[ALLOWED_VALUES_KEY]
    assert meta == list(STATUSES)


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"amount": "-5.00"}, ["amount:必須大於 0"]),  # V1：base 有 50 列負數
        ({"amount": "0"}, ["amount:必須大於 0"]),
        ({"amount": "-0.00"}, ["amount:必須大於 0"]),
        ({"amount": "0.01"}, []),
        # 格式已經錯的值只記型別不符，不重複記「必須大於 0」
        ({"amount": "-1e2"}, ["amount:型別不符（應為 decimal(18,2)）"]),
        # coupon 沒有標記 positive：-1.0 是清理規則（轉 NULL），不是合約違規
        ({"coupon_discount": "-1.0"}, []),
    ],
)
def test_positive_amount_is_enforced(spark, override, expected):
    assert _reasons(spark, **override) == expected
