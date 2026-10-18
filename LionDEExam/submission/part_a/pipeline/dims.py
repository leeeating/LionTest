"""維度表：dim_product（Type 1）與 dim_date。"""

from __future__ import annotations

from functools import reduce
from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType, StringType

from pipeline.contracts import PRODUCTS_SCHEMA
from pipeline.delta_io import merge_upsert
from pipeline.sources import SourceReader
from pipeline.timeparse import parse_source_timestamp

# ---------------------------------------------------------------- dim_product

# 未知產品：fact 的 product_id 不在主檔時對應到這一列。
# sk 用 -1：xxhash64 的輸出是 64 位元雜湊，與 -1 撞號的機率可忽略，且一眼可辨識。
UNKNOWN_PRODUCT_ID = "UNKNOWN"
UNKNOWN_PRODUCT_SK = -1
UNKNOWN_PRODUCT_NAME = "未知產品"


def product_sk(product_id: Column) -> Column:
    """由自然鍵算代理鍵：xxhash64 是確定性函式，重跑、換分區、換機器結果都相同。

    只用來建 dim_product。fact 端不要直接呼叫：主檔外的 product_id 會算出懸空外鍵，
    而且 xxhash64(NULL) 是 42 不是 NULL。fact 取 sk 一律用 resolve_product_sk。
    """
    return F.xxhash64(product_id)


def resolve_product_sk(fact_df: DataFrame, dim_df: DataFrame) -> DataFrame:
    """替 fact_df 補上 product_sk：以 product_id left join dim_product。

    對不到主檔的 product_id（含 NULL）一律落到未知產品 UNKNOWN_PRODUCT_SK。
    fact_df 的列數不變（dim_df 的 product_id 唯一）。
    """
    dim = dim_df.select(
        F.col("product_id").alias("_dim_product_id"),
        F.col("product_sk").alias("_dim_product_sk"),
    )
    return (
        fact_df.join(dim, fact_df["product_id"] == dim["_dim_product_id"], "left")
        .withColumn(
            "product_sk",
            F.coalesce(
                F.col("_dim_product_sk"), F.lit(UNKNOWN_PRODUCT_SK).cast("bigint")
            ),
        )
        .drop("_dim_product_id", "_dim_product_sk")
    )


class DuplicateKeyError(ValueError):
    """主檔的自然鍵重複：沒有可靠的規則決定留哪一列，整批停下。"""


def _assert_unique(df: DataFrame, key: str) -> None:
    dup = df.groupBy(key).count().filter("count > 1").orderBy(key).limit(5).collect()
    if dup:
        ids = [r[key] for r in dup]
        raise DuplicateKeyError(f"{key} 重複（最多列 5 個）：{ids}")


def build_dim_product(spark: SparkSession, products: DataFrame) -> DataFrame:
    """由「已通過合約轉型」的產品主檔建 dim_product（Type 1）。

    products 是 cast_to_contract(source.products(), PRODUCTS_SCHEMA) 的 valid_df；
    rejected 列的隔離與計數由呼叫端處理。product_id 重複時丟 DuplicateKeyError：
    主檔沒有 updated_at 之類的欄位能判斷哪一列較新，任選一列會讓結果依讀取順序而變。
    主檔出現保留字 UNKNOWN_PRODUCT_ID 也丟 DuplicateKeyError，因為會和未知產品列撞鍵。
    """
    _assert_unique(products, "product_id")
    reserved = products.filter(F.col("product_id") == UNKNOWN_PRODUCT_ID).limit(1)
    if reserved.count():
        raise DuplicateKeyError(
            f"主檔的 product_id 使用了保留字 {UNKNOWN_PRODUCT_ID}，會和「未知產品」列撞自然鍵"
        )
    rows = products.select(
        product_sk(F.col("product_id")).alias("product_sk"),
        "product_id",
        "product_name",
        "product_type",
        "destination_country",
        "destination_city",
        "trip_days",
        "base_price_twd",
        # Y/N 以外的值轉成 NULL 而不是 False，之後能被品質檢查抓到
        F.when(F.col("is_active") == "Y", True)
        .when(F.col("is_active") == "N", False)
        .cast(BooleanType())
        .alias("is_active"),
    )
    types = {f.name: f.dataType for f in PRODUCTS_SCHEMA.fields}
    unknown = spark.createDataFrame(
        [(UNKNOWN_PRODUCT_SK, UNKNOWN_PRODUCT_ID, UNKNOWN_PRODUCT_NAME)],
        "product_sk BIGINT, product_id STRING, product_name STRING",
    ).select(
        "product_sk",
        "product_id",
        "product_name",
        F.lit(None).cast(StringType()).alias("product_type"),
        F.lit(None).cast(StringType()).alias("destination_country"),
        F.lit(None).cast(StringType()).alias("destination_city"),
        F.lit(None).cast(types["trip_days"]).alias("trip_days"),
        F.lit(None).cast(types["base_price_twd"]).alias("base_price_twd"),
        F.lit(None).cast(BooleanType()).alias("is_active"),
    )
    return rows.unionByName(unknown)


def write_dim_product(
    spark: SparkSession, products: DataFrame, path: str | Path
) -> DataFrame:
    """建 dim_product 並以 product_id MERGE 寫入 Delta；回傳寫入後的表內容。"""
    merge_upsert(spark, build_dim_product(spark, products), path, keys=["product_id"])
    return spark.read.format("delta").load(str(path))


# ------------------------------------------------------------------- dim_date


def date_sk(col: Column) -> Column:
    """日期代理鍵：yyyymmdd 整數。dim_date 與之後的 fact 共用，確保兩邊算法一致。

    col 必須是 DateType；若傳入 timestamp，結果取決於 session timezone（Asia/Taipei）。
    """
    return F.date_format(col, "yyyyMMdd").cast("int")


def all_orders(source: SourceReader, days: tuple[int, ...]) -> DataFrame:
    """orders_base 加上指定天數的增量，回傳原始字串（未轉型）。

    days 沒有預設值，呼叫端必須明確指定：逐日處理時漏傳會讓前面的步驟看到之後的資料。
    全部三天傳 sources.INCREMENTAL_DAYS；只處理 base 傳 ()。

    給 dim_date 之前要先經過 cast_to_contract(..., ORDERS_SCHEMA) 取 valid_df。

    逐日處理時由呼叫端決定要看到哪幾天，例如只處理 base 時傳 days=()。
    """
    frames = [source.orders_base()] + [source.orders_incremental(d) for d in days]
    return reduce(DataFrame.unionByName, frames)


def order_dates(orders: DataFrame) -> DataFrame:
    """訂單的台北下單日與出發日，dim_date 的範圍由此決定。

    orders 必須是已依 ORDERS_SCHEMA 轉型的 DataFrame（departure_date 為 DateType）。
    """
    return orders.select(
        F.to_date(parse_source_timestamp(F.col("order_created_at"))).alias(
            "order_date"
        ),
        F.col("departure_date"),
    )


def _date_bounds(orders: DataFrame) -> DataFrame:
    """回傳單列 (lo, hi)：下單日與出發日合起來的最早、最晚日期。"""
    return order_dates(orders).agg(
        F.least(F.min("order_date"), F.min("departure_date")).alias("lo"),
        F.greatest(F.max("order_date"), F.max("departure_date")).alias("hi"),
    )


def _dates_between(bounds: DataFrame) -> DataFrame:
    d = F.col("date")
    return bounds.select(F.explode(F.sequence("lo", "hi")).alias("date")).select(
        date_sk(d).alias("date_sk"),
        d,
        F.year(d).alias("year"),
        F.quarter(d).alias("quarter"),
        F.month(d).alias("month"),
        F.dayofmonth(d).alias("day"),
        # ISO 週日序：週一＝1 … 週日＝7（Spark 的 weekday 是週一＝0）
        (F.weekday(d) + 1).alias("day_of_week"),
        (F.weekday(d) >= 5).alias("is_weekend"),
    )


def build_dim_date(orders: DataFrame) -> DataFrame:
    """由呼叫端傳入的訂單算出連續日期範圍，每天一列。"""
    return _dates_between(_date_bounds(orders))


def write_dim_date(
    spark: SparkSession, orders: DataFrame, path: str | Path
) -> DataFrame:
    """以傳入的訂單擴充 dim_date，並以 date_sk MERGE 寫入 Delta；回傳寫入後的表內容。

    - 範圍取「既有表的範圍」與「這批訂單的範圍」的聯集，所以只傳某一天的增量時，
      既有日期不會被刪，新舊範圍之間也不會留下缺日。
    - MERGE 只會補上新日期；既有日期列重算的值相同，內容不變。
    """
    path = str(path)
    bounds = _date_bounds(orders)
    if DeltaTable.isDeltaTable(spark, path):
        existing = (
            spark.read.format("delta")
            .load(path)
            .agg(F.min("date").alias("lo"), F.max("date").alias("hi"))
        )
        bounds = bounds.unionByName(existing).agg(
            F.min("lo").alias("lo"), F.max("hi").alias("hi")
        )
    merge_upsert(spark, _dates_between(bounds), path, keys=["date_sk"])
    return spark.read.format("delta").load(path)
