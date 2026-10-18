"""來源 schema 合約（ADR-02）：全專案唯一一份。

每個來源表的欄名、型別、是否必填都寫在這裡，不靠 inferSchema。
不論來源是 CSV 還是之後的 SQL DB，都用同一份合約。

合約怎麼被使用（違規處理方式已由使用者定案）：
- 讀取：來源實作一律用 to_raw_schema() 產生的「同欄名、全部 StringType」schema 讀入，
  原始值一個字元都不改，型別錯的值也不會在讀取時變成 NULL。
- 檔案層級問題（檔案不存在、表頭不符、沒有資料列）：讀取時整批報錯，不寫入任何東西。
- 列層級問題（型別轉不過、Decimal 小數位超過 scale、必填欄位空值或只有空白、
  欄位數不符、時間字串無法解析）：
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

from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from pipeline.timeparse import FORMAT_METADATA_KEY, SOURCE_TIMESTAMP

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
        # 狀態機判斷需要
        StructField("order_status", StringType(), False),
        StructField("quantity", IntegerType(), False),
        # currency 有 NTD 等非標準值，本來就是字串，對應規則在 silver 層；
        # 空值時無法換算 TWD
        StructField("currency", StringType(), False),
        StructField("amount", AMOUNT_TYPE, False),
        # 「沒有折扣」也可能以空值表示，不強制
        StructField("coupon_discount", AMOUNT_TYPE, True),
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
