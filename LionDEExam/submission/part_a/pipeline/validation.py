"""把原始字串轉成合約型別，違規列分出來隔離（列層級問題，已定案）。

cast_to_contract 是唯一的轉型入口：dim_product 現在用，T5 的隔離表也會重用。

判斷違規只看「原始字串」，不看 Spark 轉型後的值，因為 Spark 的 try_cast 很寬鬆：
實測 try_cast('100.456' AS DECIMAL(18,2)) 得到 100.46（四捨五入）、
try_cast('1e2' AS DECIMAL(18,2)) 得到 100.00、try_cast(' 3' AS INT) 得到 3、
try_cast('2026-06-25T14:02:16+08:00' AS DATE) 得到 2026-06-25。這些都會讓髒值悄悄通過，
所以每種型別先用字串格式規則把關，通過後才轉型。
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DataType,
    DateType,
    DecimalType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from pipeline.contracts import ALLOWED_VALUES_KEY, POSITIVE_KEY, SOURCE_ERROR_COL
from pipeline.timeparse import (
    FORMAT_METADATA_KEY,
    SOURCE_TIMESTAMP,
    SOURCE_TIMESTAMP_FORMATS,
    parse_source_timestamp,
)

REJECT_REASONS_COL = "reject_reasons"

# 所有規則結尾一律用 \z（字串真正的結尾），不用 $：Java regex 的 $ 也會吻合
# 「結尾換行符之前」的位置，"3\n" 會被當成合法整數。

# 整數：可有正負號，不允許空白、小數點、科學記號
_INT_PATTERN = r"^[+-]?[0-9]+\z"
# 十進位數：可有正負號與小數點；不接受科學記號（1e2）、千分位、空白
_DECIMAL_PATTERN = r"^[+-]?[0-9]+(\.[0-9]+)?\z"
# 日期：只接受 yyyy-MM-dd（Spark 的 cast 會接受後面帶時間的字串，必須擋掉）
_DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\z"


def strict_date(raw: Column) -> Column:
    """原始字串依合約的日期規則轉成 DateType；不是 yyyy-MM-dd 或日期不存在時回傳 NULL。

    和 cast_to_contract 判斷 DateType 欄位用同一條規則。合約以外需要先看日期的地方
    （例如 dim_member 依 extract_date 過濾）用這個函式，不要用 try_cast：
    try_cast 會接受 "2026-07-15 junk" 這類值。
    """
    return F.when(raw.rlike(_DATE_PATTERN), raw.try_cast(DateType()))


def _reason(cond: Column, text: str) -> Column:
    """條件成立時回傳原因字串，否則 NULL。"""
    return F.when(cond, F.lit(text))


def _is_blank(raw: Column) -> Column:
    """NULL、空字串、或只有空白字元。"""
    return raw.isNull() | raw.rlike(r"^\s*\z")


def _format_reasons(raw: Column, field: StructField) -> list[Column]:
    """原始值非空時，依合約型別檢查格式，回傳可能的違規原因（不成立的是 NULL）。

    必填欄位只有空白時已經記為「必填空值」，這裡不再重複記型別不符。
    """
    name, dtype = field.name, field.dataType
    present = raw.isNotNull()
    if not field.nullable:
        present = present & ~_is_blank(raw)
    casted = raw.try_cast(dtype)
    type_error = f"{name}:型別不符（應為 {dtype.simpleString()}）"

    if isinstance(dtype, StringType):
        allowed = field.metadata.get(ALLOWED_VALUES_KEY)
        if allowed is not None:
            # 完全比對：大小寫、前後空白不同都算違規，不替上游猜
            return [
                _reason(
                    present & ~raw.isin(*allowed),
                    f"{name}:值不在允許範圍（{'、'.join(allowed)}）",
                )
            ]
        if field.metadata.get(FORMAT_METADATA_KEY) == SOURCE_TIMESTAMP:
            # 與 parse_source_timestamp 共用同一份格式定義；解析不了就不能算下單日／比新舊
            fmts = "、".join(SOURCE_TIMESTAMP_FORMATS)
            return [
                _reason(
                    present & parse_source_timestamp(raw).isNull(),
                    f"{name}:時間格式無法解析（應為 {fmts}）",
                )
            ]
        return []
    if isinstance(dtype, (IntegerType, LongType)):
        # 格式對但超出範圍（溢位）時 try_cast 為 NULL，一併算型別不符
        bad = ~raw.rlike(_INT_PATTERN) | casted.isNull()
        return [_reason(present & bad, type_error)]
    if isinstance(dtype, DecimalType):
        well_formed = raw.rlike(_DECIMAL_PATTERN)
        frac_digits = F.length(F.regexp_extract(raw, r"\.([0-9]+)\z", 1))
        int_digits = F.length(
            F.regexp_replace(F.regexp_extract(raw, r"^[+-]?([0-9]+)", 1), r"^0+", "")
        )
        return [
            _reason(present & ~well_formed, type_error),
            _reason(
                present & well_formed & (frac_digits > dtype.scale),
                f"{name}:小數位超過 {dtype.scale} 位",
            ),
            _reason(
                present & well_formed & (int_digits > dtype.precision - dtype.scale),
                f"{name}:整數位超過 {dtype.precision - dtype.scale} 位",
            ),
            *(
                [_reason(present & well_formed & (casted <= 0), f"{name}:必須大於 0")]
                if field.metadata.get(POSITIVE_KEY)
                else []
            ),
        ]
    if isinstance(dtype, DateType):
        # 格式不對，或格式對但日期不存在（例如 2026-02-30）時為 NULL
        return [_reason(present & strict_date(raw).isNull(), type_error)]
    # 合約之後若加入其他型別：至少保證「原值非空、轉型後變 NULL」算違規
    return [_reason(present & casted.isNull(), type_error)]


def _cast(raw: Column, dtype: DataType) -> Column:
    return raw if isinstance(dtype, StringType) else raw.try_cast(dtype)


def cast_to_contract(
    df: DataFrame, schema: StructType, *, passthrough: tuple[str, ...] = ()
) -> tuple[DataFrame, DataFrame]:
    """把原始字串 DataFrame 依合約轉型，回傳 (valid_df, rejected_df)。

    - df：來源讀取介面回傳的 DataFrame（合約欄位全為字串，可帶 SOURCE_ERROR_COL）。
    - valid_df：沒有任何違規的列，欄名、欄序、型別與合約相同
      （nullability 一律為可空，必填欄位實際上不會有 NULL）；passthrough 指定的欄位
      原樣附在合約欄位之後（例如 fact_order 用來保留整列原始字串，之後隔離時寫回原值）。
    - rejected_df：有違規的列，保留所有原始字串欄位（含 SOURCE_ERROR_COL），
      加上 reject_reasons（ARRAY<STRING>，一列多個原因時全部列出，格式「欄名:原因」）。
    - 違規種類：欄位數不符、必填空值（含只有空白）、型別不符、小數位超過 scale、
      整數位超過、時間字串無法解析（合約 metadata 標記 source_timestamp 的欄位）、
      值不在允許範圍（合約 metadata 標記 allowed_values 的欄位）、
      數值不大於 0（合約 metadata 標記 positive 的欄位）。
    - 兩者用同一個條件（reject_reasons 是否為空）切開，互斥且涵蓋所有列，
      所以 valid 筆數＋rejected 筆數＝輸入筆數。
    """
    missing = [f.name for f in schema.fields if f.name not in df.columns]
    if missing:
        raise ValueError(f"輸入缺少合約欄位：{missing}")

    reasons: list[Column] = []
    if SOURCE_ERROR_COL in df.columns:
        reasons.append(
            _reason(F.col(SOURCE_ERROR_COL).isNotNull(), "列格式錯誤:欄位數與表頭不符")
        )
    for field in schema.fields:
        raw = F.col(field.name)
        if not field.nullable:
            # 空字串與只有空白都算空值（例如 product_id=" "）
            reasons.append(_reason(_is_blank(raw), f"{field.name}:必填空值"))
        reasons.extend(_format_reasons(raw, field))

    checked = df.withColumn(
        REJECT_REASONS_COL,
        F.filter(F.array(*reasons), lambda r: r.isNotNull()),
    )
    is_valid = F.size(REJECT_REASONS_COL) == 0

    valid = checked.filter(is_valid).select(
        [_cast(F.col(f.name), f.dataType).alias(f.name) for f in schema.fields]
        + [F.col(c) for c in passthrough]
    )
    rejected = checked.filter(~is_valid)
    return valid, rejected
