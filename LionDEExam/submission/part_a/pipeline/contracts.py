"""來源 schema 合約（ADR-02）：全專案唯一一份。

每個來源表的欄名、型別、是否必填都寫在這裡，不靠 inferSchema。
不論來源是 CSV 還是之後的 SQL DB，都用同一份合約。

合約怎麼被使用（違規處理方式已由使用者定案）：
- 讀取：來源實作一律用 to_raw_schema() 產生的「同欄名、全部 StringType」schema 讀入，
  原始值一個字元都不改，型別錯的值也不會在讀取時變成 NULL。
- 檔案層級問題（檔案不存在、表頭不符、沒有資料列）：讀取時整批報錯，不寫入任何東西。
- 列層級問題（型別轉不過、Decimal 小數位超過 scale、必填欄位空值或只有空白、
  欄位數不符、時間字串無法解析、值不在允許範圍、金額不大於 0、
  coupon 是 -1.00 以外的負數）：
  validation.cast_to_contract() 把該列分到 rejected 並記下原因，其他列照常處理。

型別原則：
- 有格式髒值、要等 silver 層解析的欄位（例如 order_created_at 混三種時間格式）合約就是
  StringType，轉型這一步不檢查它的格式。
- 金額用 DecimalType，避免浮點誤差影響對帳與 checksum。

必填（nullable=False）原則：欄位空值時，這一列無法被正確處理或歸屬，就設為必填。
目前資料中所有欄位都沒有空值（2026-10-18 以 duckdb 實查），所以必填清單是依語意決定，
理由寫在各欄旁邊。
"""

from __future__ import annotations

from decimal import Decimal

from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from pipeline.order_status import STATUSES
from pipeline.timeparse import FORMAT_METADATA_KEY, SOURCE_TIMESTAMP

# 欄位 metadata：值必須在這份清單內（大小寫、空白都要完全相同），否則列進 rejected，
# 原因「值不在允許範圍」。由 validation.cast_to_contract 檢查。
ALLOWED_VALUES_KEY = "allowed_values"

# 欄位 metadata：數值必須大於 0（ADR-02 舉的 CHECK (amount > 0)），否則列進 rejected，
# 原因「必須大於 0」。由 validation.cast_to_contract 檢查。
POSITIVE_KEY = "positive"

# 欄位 metadata：數值必須大於或等於 0，但清單裡的特殊值（字串寫的 Decimal）除外，
# 否則列進 rejected，原因「必須大於或等於 0」。由 validation.cast_to_contract 檢查。
NON_NEGATIVE_EXCEPT_KEY = "non_negative_except"

# V3：coupon_discount＝-1.00 代表「未知」（資料裡另有 0.0 代表沒有折扣）；合約放行，
# 由 fact_order._clean_coupon 轉成 NULL（使用者定：「-1 代表未知，轉 NULL 不要猜」）
COUPON_UNKNOWN = Decimal("-1.00")

# 訂單幣別的允許值（2026-10-18 以 duckdb 查四個訂單檔：base 有 TWD、NTD、USD、JPY，
# 三天增量只有 TWD、USD、JPY）。NTD 是 base 裡 TWD 的別名（V4，200 列），保留並以匯率 1 換算。
# 新幣別要先確認匯率表有提供，再加進來；沒加之前整列隔離，不會悄悄變成找不到匯率。
ORDER_CURRENCIES: tuple[str, ...] = ("TWD", "NTD", "USD", "JPY")

# 原幣別金額：最大整數位 10 位（含疑似 ×1000 的值），小數最多 2 位
AMOUNT_TYPE = DecimalType(18, 2)
# 匯率：JPY 有 5 位小數
RATE_TYPE = DecimalType(18, 6)

# 欄位 metadata：值必須能被 timeparse.parse_source_timestamp 解析（三種格式），否則列進 rejected
SOURCE_TIMESTAMP_META = {FORMAT_METADATA_KEY: SOURCE_TIMESTAMP}

# 讀取層附加的欄位：CSV 某列的欄位數和表頭不符時，這一欄放該列原文，否則為 NULL。
# 其他來源實作（例如 SQL DB）沒有這種問題，這一欄一律回傳 NULL。
SOURCE_ERROR_COL = "_source_error"

ORDERS_SCHEMA = StructType(
    [
        # 自然鍵：MERGE 與去重都靠它
        StructField("order_id", StringType(), False),
        # fact 的外鍵：空值無法對到會員與商品
        StructField("member_id", StringType(), False),
        StructField("product_id", StringType(), False),
        # 描述性欄位，空值不影響金額與歸屬
        StructField("channel", StringType(), True),
        # 狀態機判斷需要；允許值和狀態機共用 order_status.STATUSES（唯一一份）
        StructField(
            "order_status", StringType(), False, {ALLOWED_VALUES_KEY: list(STATUSES)}
        ),
        StructField("quantity", IntegerType(), False),
        # currency 有 NTD 等非標準值，本來就是字串，對應規則在 silver 層；
        # 空值時無法換算 TWD
        StructField(
            "currency",
            StringType(),
            False,
            {ALLOWED_VALUES_KEY: list(ORDER_CURRENCIES)},
        ),
        # 必須大於 0（使用者定 V1：「負數在合約層就該擋下」；base 有 50 列負數）
        StructField("amount", AMOUNT_TYPE, False, {POSITIVE_KEY: True}),
        # 「沒有折扣」也可能以空值表示，不強制。
        # -1.00 以外的負數擋下（使用者定 B：「負數 coupon 沒有合理解釋」）
        # 〔防護性設計：本資料 0 筆〕
        StructField(
            "coupon_discount",
            AMOUNT_TYPE,
            True,
            {NON_NEGATIVE_EXCEPT_KEY: [str(COUPON_UNKNOWN)]},
        ),
        # 混有 ISO+08:00、Z 結尾（UTC）、YYYY/MM/DD HH:MM:SS（無時區）三種格式 → 保留字串；
        # 決定下單日與匯率日，必填；且必須是三種可解析格式之一，否則下單日會變 NULL
        StructField("order_created_at", StringType(), False, SOURCE_TIMESTAMP_META),
        # 票券、訂房等商品不一定有出發日，不強制
        StructField("departure_date", DateType(), True),
        # 目前全是 ISO+08:00，但與 order_created_at 同一個上游、同一類欄位，
        # 時區解析統一放 silver 層；增量判斷新舊靠它，必填且必須可解析，
        # 否則同一 order_id 的新舊無法比較
        StructField("updated_at", StringType(), False, SOURCE_TIMESTAMP_META),
    ]
)

MEMBERS_SCHEMA = StructType(
    [
        StructField("member_id", StringType(), False),
        StructField("member_name", StringType(), True),
        StructField("member_level", StringType(), True),
        # 缺值以字串 'N/A' 表示，轉 NULL 是 silver 層的事
        StructField("city", StringType(), True),
        # 有 1900-01-01 假值，但格式合法，讀成 DateType 不會遺失資訊
        StructField("birth_date", DateType(), True),
        # SCD2 的 valid_from 用它，必填
        StructField("register_date", DateType(), False),
        # 決定快照新舊順序，必填
        StructField("extract_date", DateType(), False),
    ]
)

PRODUCTS_SCHEMA = StructType(
    [
        # 自然鍵；其餘是描述欄位，空值不影響 fact 對應
        StructField("product_id", StringType(), False),
        StructField("product_name", StringType(), True),
        StructField("product_type", StringType(), True),
        StructField("destination_country", StringType(), True),
        StructField("destination_city", StringType(), True),
        StructField("trip_days", IntegerType(), True),
        StructField("base_price_twd", AMOUNT_TYPE, True),
        # 原值 Y/N；讀取層保留原樣，dim_product 再轉布林
        StructField("is_active", StringType(), True),
    ]
)

# 匯率三欄缺任何一欄都無法用來換算
FX_RATES_SCHEMA = StructType(
    [
        StructField("rate_date", DateType(), False),
        StructField("currency", StringType(), False),
        StructField("rate_to_twd", RATE_TYPE, False),
    ]
)


def to_string_schema(schema: StructType) -> StructType:
    """由合約自動產生「同欄名、全部 StringType、可為空」的 schema，不手寫第二份。"""
    return StructType([StructField(f.name, StringType(), True) for f in schema.fields])


def to_raw_schema(schema: StructType) -> StructType:
    """來源讀取介面回傳的 schema：全字串的合約欄位，加上 SOURCE_ERROR_COL。"""
    return StructType(
        to_string_schema(schema).fields
        + [StructField(SOURCE_ERROR_COL, StringType(), True)]
    )


def required_columns(schema: StructType) -> list[str]:
    return [f.name for f in schema.fields if not f.nullable]
