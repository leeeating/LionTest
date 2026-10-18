"""fact_order：訂單事實表＋隔離表＋對帳，以「一批」為單位處理。

規則（使用者已定案）：
- 粒度：一張訂單一列、存最新狀態，以 order_id MERGE（ADR-04）。
- 同一 order_id 除了 updated_at 以外全部相同（V7）：取 updated_at 最新的一列，
  其餘進隔離表。下單時間比較解析後的時刻，不比較原始字串（V7 有 8 組格式不同）。
- 同一 order_id 但會員、下單時間、金額任一不同（撞號）：整組進隔離表，不寫 fact（ADR-03）。
  同批內互相比較（find_batch_collisions），也和既有 fact 比較（find_existing_collisions）。
- 金額：存 amount、currency（原值）、amount_twd。amount_twd 用台北下單日當天的匯率；
  TWD、NTD 固定 1（匯率表沒有 TWD，不能 inner join）。非 TWD／NTD 找不到當天匯率 → 隔離，
  不拿前一天的匯率代替。
- 產品清單有 rejected 列 → 整批停（ReferenceDataError），在寫任何表之前檢查。
- product_id 不在清單、會員對不到版本 → -1，對帳另列筆數。
- 隔離表：一張 Delta 表，每列帶 batch_id、原始字串、reject_category、reject_reasons；
  以 replaceWhere 清掉同一 batch_id 再寫，重跑冪等。
- 對帳：輸入列數＝寫進 fact 的列數＋隔離列數，用 count() 計算（build_spark() 的設定下才準）。

一批的處理順序（每一步淘汰的列都帶著原因進隔離表，所以各類別互斥、加總等於輸入）：
  ① 合約轉型（cast_to_contract）→ ② 同批撞號 → ③ 去重（保留 updated_at 最新）
  → ④ 與既有 fact 撞號 → ⑤ 匯率 → ⑥ 品質規則（A-3，目前沒有規則）→ ⑦ 對維度 → 寫入
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, StringType

from pipeline.contracts import (
    FX_RATES_SCHEMA,
    ORDERS_SCHEMA,
    PRODUCTS_SCHEMA,
    SOURCE_ERROR_COL,
)
from pipeline.delta_io import merge_upsert
from pipeline.dim_member import UNKNOWN_MEMBER_SK, resolve_member_sk, write_dim_member
from pipeline.dims import (
    UNKNOWN_PRODUCT_SK,
    DuplicateKeyError,
    date_sk,
    resolve_product_sk,
    write_dim_date,
    write_dim_product,
)
from pipeline.sources import SourceReader
from pipeline.timeparse import parse_source_timestamp
from pipeline.validation import REJECT_REASONS_COL, cast_to_contract

# base 的批次代號與 as_of。會員快照截止在 06-30；base 訂單的下單日都在 06-30 以前，
# 但狀態最晚更新到 07-03（2,265 列的 updated_at 落在 07-01～07-03，L2）。
# as_of 只決定會員快照看到哪一天，會員依下單日對版本，所以用 06-30 不會偷看到之後的快照。
BASE_BATCH_ID = "base"
BASE_AS_OF = dt.date(2026, 6, 30)

# 匯率固定為 1 的幣別：TWD 本身，以及 base 裡當作 TWD 別名的 NTD（V4）
TWD_PEGGED_CURRENCIES = ("TWD", "NTD")

# 撞號判斷用的「不可變欄位」（ADR-03、J4）：同一張單這三欄不會變
IMMUTABLE_COLUMNS = ("member_id", "order_created_at", "amount")

# amount（18,2）× 匯率（18,6）的乘積精度是 37 位；四捨五入到 2 位後用 38 位存，避免溢位
AMOUNT_TWD_TYPE = DecimalType(38, 2)

BATCH_ID_COL = "batch_id"
REJECT_CATEGORY_COL = "reject_category"
_RAW = "_raw"
_BATCH_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


class Category:
    """隔離原因的類別（reject_category 欄），各類別互斥。"""

    CONTRACT = "contract"  # cast_to_contract 的列層級違規
    COLLISION = "collision"  # 同批同 order_id、不可變欄位不同，整組隔離
    DUPLICATE = "duplicate"  # 與保留的那列除 updated_at 外全同（V7）
    SUPERSEDED = "superseded"  # 同批有較新的狀態更新（內容不同但不是撞號）
    COLLISION_EXISTING = "collision_existing"  # 與既有 fact 撞號
    FX_MISSING = "fx_missing"  # 下單日找不到匯率
    QUALITY = "quality"  # A-3 品質規則（目前沒有規則）


REASON_DUPLICATE = "重複，保留 updated_at 最新一列"
REASON_SUPERSEDED = "同批有較新的狀態更新，保留 updated_at 最新一列"
REASON_COLLISION = "撞號：同批同 order_id 的會員、下單時間或金額不同，整組隔離"
REASON_COLLISION_EXISTING = "撞號：與既有 fact 同 order_id，但會員、下單時間或金額不同"

# A-3 品質規則的掛載點：每條規則是一個函式，收這批的 as_of（例如「completed 但出發日未到」
# 要拿出發日和 as_of 比），回傳一個原因字串的 Column：作用在「已換算金額、尚未對維度」的
# 候選列上（可用 orders 合約欄位，order_created_at、updated_at 已是 timestamp，另有
# fx_rate、amount_twd），不違規時為 NULL。規則由使用者在 A-3 決定，目前刻意留空：
# 負數金額、疑似 ×1000、coupon -1.0、completed 但出發日未到，現在都照原樣寫進 fact。
QualityRule = Callable[[dt.date], Column]
ORDER_QUALITY_RULES: tuple[QualityRule, ...] = ()

FACT_ORDER_COLUMNS = (
    "order_id",
    "member_id",
    "member_sk",
    "product_id",
    "product_sk",
    "order_date_sk",
    "departure_date_sk",
    "order_status",
    "channel",
    "quantity",
    "currency",
    "amount",
    "fx_rate",
    "amount_twd",
    "coupon_discount",
    "order_created_at",
    "updated_at",
    BATCH_ID_COL,
)


class ReferenceDataError(ValueError):
    """參考資料（產品清單、匯率表）有問題：整批停下，fact 與隔離表都不寫入。"""


class ReconciliationError(RuntimeError):
    """輸入≠寫入＋隔離：程式有漏洞，寫入前就停下。"""


@dataclass(frozen=True)
class WarehousePaths:
    """一個倉儲的各表路徑，都放在 root 底下。"""

    root: Path

    def __init__(self, root: str | Path):
        object.__setattr__(self, "root", Path(root))

    @property
    def fact_order(self) -> Path:
        return self.root / "fact_order"

    @property
    def quarantine(self) -> Path:
        return self.root / "quarantine_order"

    @property
    def dim_product(self) -> Path:
        return self.root / "dim_product"

    @property
    def dim_member(self) -> Path:
        return self.root / "dim_member"

    @property
    def dim_date(self) -> Path:
        return self.root / "dim_date"


@dataclass(frozen=True)
class BatchReconciliation:
    """一批的對帳結果；T6 的冪等證明拿這些數字比對。

    - input_rows：這批來源訂單的列數。
    - fact_rows、amount_twd_sum、unknown_*_rows：這批寫進（MERGE 進）fact 的列。
    - quarantined_rows、quarantined_by_category：這批進隔離表的列。
    - fact_table_rows、fact_table_amount_twd_sum：寫入後整張 fact 的列數與 checksum。
    - member_rejected_rows：dim_member 這次的違規列數（會員快照，不在訂單對帳內）。
    """

    batch_id: str
    input_rows: int
    fact_rows: int
    quarantined_rows: int
    quarantined_by_category: dict[str, int] = field(hash=False)
    amount_twd_sum: Decimal
    unknown_product_rows: int
    unknown_member_rows: int
    fact_table_rows: int
    fact_table_amount_twd_sum: Decimal
    member_rejected_rows: int

    @property
    def balanced(self) -> bool:
        return self.input_rows == self.fact_rows + self.quarantined_rows


# ------------------------------------------------------------ 撞號（可重用）


def _all(conds: list[Column]) -> Column:
    out = conds[0]
    for c in conds[1:]:
        out = out & c
    return out


def find_batch_collisions(orders: DataFrame) -> DataFrame:
    """同一批內撞號的 order_id（單欄 DataFrame）：同 id 的列，不可變欄位的組合不只一種。

    orders 的 order_created_at 必須是解析後的 timestamp、amount 是 Decimal，
    所以格式不同但同一時刻的下單時間不算不同。
    """
    return (
        orders.groupBy("order_id")
        .agg(F.count_distinct(*IMMUTABLE_COLUMNS).alias("_n"))
        .filter("_n > 1")
        .select("order_id")
    )


def find_existing_collisions(orders: DataFrame, fact: DataFrame) -> DataFrame:
    """和既有 fact 撞號的 order_id（單欄 DataFrame）：id 相同，但不可變欄位任一不同。

    orders 的 order_id 須已唯一（去重之後）；兩邊欄位型別相同（timestamp、Decimal）。
    T6 處理增量時用同一個函式比對「增量列 vs 既有 fact」。
    """
    o, f = orders.alias("o"), fact.alias("f")
    same = _all(
        [F.col(f"o.{c}").eqNullSafe(F.col(f"f.{c}")) for c in IMMUTABLE_COLUMNS]
    )
    return (
        o.join(f, F.col("o.order_id") == F.col("f.order_id"))
        .filter(~same)
        .select(F.col("o.order_id").alias("order_id"))
    )


# ---------------------------------------------------------------- 各步驟


def _quarantine_rows(df: DataFrame, category: str, reason: Column) -> DataFrame:
    """把淘汰的列轉成隔離表的形狀：原始字串＋類別＋原因（ARRAY<STRING>）。"""
    return df.select(
        F.col(f"{_RAW}.*"),
        F.lit(category).alias(REJECT_CATEGORY_COL),
        F.array(reason).alias(REJECT_REASONS_COL),
    )


def _with_raw(orders: DataFrame) -> DataFrame:
    """把整列原始字串收進 _raw，之後任何一步隔離時都能寫回上游送來的原值。"""
    cols = [F.col(f.name) for f in ORDERS_SCHEMA.fields]
    err = (
        F.col(SOURCE_ERROR_COL)
        if SOURCE_ERROR_COL in orders.columns
        else F.lit(None).cast(StringType())
    )
    return orders.withColumn(_RAW, F.struct(*cols, err.alias(SOURCE_ERROR_COL)))


def _split_collisions(orders: DataFrame) -> tuple[DataFrame, DataFrame]:
    ids = find_batch_collisions(orders)
    bad = orders.join(ids, "order_id", "left_semi")
    ok = orders.join(ids, "order_id", "left_anti")
    return ok, _quarantine_rows(bad, Category.COLLISION, F.lit(REASON_COLLISION))


def _dedupe(orders: DataFrame) -> tuple[DataFrame, DataFrame]:
    """每個 order_id 保留 updated_at 最新的一列。

    updated_at 相同時依原始字串排序，只為了結果確定（重跑選同一列）。
    被淘汰的列和保留列「除 updated_at 外全同」就是重複（V7），否則是較舊的狀態更新。
    """
    content = F.struct(*[c for c in orders.columns if c not in ("updated_at", _RAW)])
    w = Window.partitionBy("order_id").orderBy(
        F.col("updated_at").desc(), F.col(_RAW).desc()
    )
    ranked = orders.withColumns(
        {
            "_rn": F.row_number().over(w),
            "_same_as_kept": content.eqNullSafe(F.first(content).over(w)),
        }
    )
    kept = ranked.filter("_rn = 1").drop("_rn", "_same_as_kept")
    dropped = ranked.filter("_rn > 1")
    dup = _quarantine_rows(
        dropped.filter("_same_as_kept"), Category.DUPLICATE, F.lit(REASON_DUPLICATE)
    )
    old = _quarantine_rows(
        dropped.filter("NOT _same_as_kept"),
        Category.SUPERSEDED,
        F.lit(REASON_SUPERSEDED),
    )
    return kept, dup.unionByName(old)


def _split_existing_collisions(
    orders: DataFrame, fact: DataFrame | None
) -> tuple[DataFrame, DataFrame]:
    if fact is None:
        return orders, _quarantine_rows(
            orders.limit(0),
            Category.COLLISION_EXISTING,
            F.lit(REASON_COLLISION_EXISTING),
        )
    ids = find_existing_collisions(orders, fact)
    bad = orders.join(ids, "order_id", "left_semi")
    ok = orders.join(ids, "order_id", "left_anti")
    return ok, _quarantine_rows(
        bad, Category.COLLISION_EXISTING, F.lit(REASON_COLLISION_EXISTING)
    )


def _convert_currency(orders: DataFrame, fx: DataFrame) -> tuple[DataFrame, DataFrame]:
    """依台北下單日換算 amount_twd；TWD、NTD 固定 1，用 left join，不會弄丟沒有匯率的列。"""
    rates = fx.select(
        F.col("rate_date").alias("_rate_date"),
        F.col("currency").alias("_rate_currency"),
        F.col("rate_to_twd").alias("_rate"),
    )
    joined = orders.join(
        rates,
        (orders["_order_date"] == rates["_rate_date"])
        & (orders["currency"] == rates["_rate_currency"]),
        "left",
    ).withColumn(
        "fx_rate",
        F.when(
            F.col("currency").isin(*TWD_PEGGED_CURRENCIES),
            F.lit(1).cast(FX_RATES_SCHEMA["rate_to_twd"].dataType),
        ).otherwise(F.col("_rate")),
    )
    joined = joined.drop("_rate_date", "_rate_currency", "_rate")
    ok = joined.filter(F.col("fx_rate").isNotNull()).withColumn(
        "amount_twd",
        F.round(F.col("amount") * F.col("fx_rate"), 2).cast(AMOUNT_TWD_TYPE),
    )
    reason = F.concat(
        F.lit("currency:下單日 "),
        F.date_format("_order_date", "yyyy-MM-dd"),
        F.lit(" 找不到 "),
        F.col("currency"),
        F.lit(" 對 TWD 的匯率"),
    )
    bad = _quarantine_rows(
        joined.filter(F.col("fx_rate").isNull()), Category.FX_MISSING, reason
    )
    return ok, bad


def _apply_quality_rules(
    orders: DataFrame, as_of: dt.date
) -> tuple[DataFrame, DataFrame]:
    """A-3 品質規則的掛載點；ORDER_QUALITY_RULES 為空時全部放行。

    一列命中多條規則時，原因全部列出；隔離列帶原始字串（_raw）。
    """
    if not ORDER_QUALITY_RULES:
        return orders, _quarantine_rows(
            orders.limit(0), Category.QUALITY, F.lit(None).cast(StringType())
        )
    reasons = F.filter(
        F.array(*[rule(as_of) for rule in ORDER_QUALITY_RULES]), lambda r: r.isNotNull()
    )
    checked = orders.withColumn("_q", reasons)
    ok = checked.filter(F.size("_q") == 0).drop("_q")
    bad = checked.filter(F.size("_q") > 0).select(
        F.col(f"{_RAW}.*"),
        F.lit(Category.QUALITY).alias(REJECT_CATEGORY_COL),
        F.col("_q").alias(REJECT_REASONS_COL),
    )
    return ok, bad


def _check_reference(name: str, rejected: DataFrame) -> None:
    sample = rejected.limit(3).collect()
    if sample:
        n = rejected.count()
        reasons = [r[REJECT_REASONS_COL] for r in sample]
        raise ReferenceDataError(
            f"{name} 有 {n} 列違反合約，整批停下（前 3 列原因：{reasons}）"
        )


def _check_fx_unique(fx: DataFrame) -> None:
    dup = (
        fx.groupBy("rate_date", "currency")
        .count()
        .filter("count > 1")
        .limit(3)
        .collect()
    )
    if dup:
        keys = [(str(r.rate_date), r.currency) for r in dup]
        raise ReferenceDataError(
            f"fx_rates 同一天同幣別有多個匯率，無法決定用哪一個，整批停下：{keys}"
        )


def _write_quarantine(
    spark: SparkSession, rows: DataFrame, path: Path, batch_id: str
) -> None:
    """清掉同一 batch_id 的舊資料再寫入（replaceWhere），重跑同一批不會變兩份。"""
    rows.write.format("delta").mode("overwrite").option(
        "replaceWhere", f"{BATCH_ID_COL} = '{batch_id}'"
    ).save(str(path))


def _sum(df: DataFrame, col: str) -> Decimal:
    v = df.agg(F.sum(col)).first()[0]
    return v if v is not None else Decimal("0.00")


# ---------------------------------------------------------------- 入口


def load_order_batch(
    spark: SparkSession,
    source: SourceReader,
    *,
    batch_id: str,
    orders: DataFrame,
    as_of: dt.date,
    paths: WarehousePaths,
) -> BatchReconciliation:
    """處理一批訂單：更新維度、寫 fact_order 與隔離表，回傳對帳結果。

    - orders：這一批的原始字串訂單（例如 source.orders_base()、source.orders_incremental(1)）。
    - batch_id：寫進 fact 與隔離表；隔離表依它 replaceWhere。只接受英數、底線、連字號。
    - as_of：這批的業務日期，會員快照只看到這天為止（write_dim_member 的 through），
      不偷看之後的快照。dim_date 只依這批訂單擴充。
    - 產品清單有違規列或 product_id 重複、匯率表有違規列或同日同幣別重複
      → ReferenceDataError，在寫任何表之前停下。
    - 對帳不平 → ReconciliationError，同樣在寫 fact、隔離表之前停下。

    T6 尚未加入：只在 updated_at 較新時才覆寫既有訂單、狀態機檢查、批次紀錄。
    """
    if not _BATCH_ID_PATTERN.fullmatch(batch_id):
        raise ValueError(f"batch_id 只能用英數、底線、連字號：{batch_id!r}")

    # ---- 參考資料：先檢查，有問題整批停
    products, rejected_products = cast_to_contract(source.products(), PRODUCTS_SCHEMA)
    _check_reference("products", rejected_products)
    fx, rejected_fx = cast_to_contract(source.fx_rates(), FX_RATES_SCHEMA)
    _check_reference("fx_rates", rejected_fx)
    _check_fx_unique(fx)

    # ---- ① 合約轉型；原始字串收進 _raw 一路帶著
    valid, rejected = cast_to_contract(
        _with_raw(orders), ORDERS_SCHEMA, passthrough=(_RAW,)
    )
    q_contract = rejected.select(
        F.col(f"{_RAW}.*"),
        F.lit(Category.CONTRACT).alias(REJECT_CATEGORY_COL),
        REJECT_REASONS_COL,
    )

    # ---- 維度：dim_date 只依這批訂單擴充，dim_member 只看到 as_of 為止
    try:
        dim_product = write_dim_product(spark, products, paths.dim_product)
    except DuplicateKeyError as e:
        # 統一成 ReferenceDataError：呼叫端（T6 的批次紀錄）只需要處理一種參考資料錯誤。
        # build_dim_product 在 MERGE 之前就檢查，所以丟出時任何表都還沒寫入
        raise ReferenceDataError(f"products 不能使用，整批停下：{e}") from e
    member = write_dim_member(spark, source.members(), paths.dim_member, through=as_of)
    write_dim_date(spark, valid, paths.dim_date)

    typed = valid.withColumns(
        {
            "order_created_at": parse_source_timestamp(F.col("order_created_at")),
            "updated_at": parse_source_timestamp(F.col("updated_at")),
        }
    ).withColumn("_order_date", F.to_date("order_created_at"))

    existing = None
    if DeltaTable.isDeltaTable(spark, str(paths.fact_order)):
        # 物化：MERGE 的目標就是這張表，避免寫入途中重讀
        existing = (
            spark.read.format("delta").load(str(paths.fact_order)).localCheckpoint()
        )

    # ---- ②～⑥
    ok, q_collision = _split_collisions(typed)
    ok, q_dedupe = _dedupe(ok)
    ok, q_existing = _split_existing_collisions(ok, existing)
    ok, q_fx = _convert_currency(ok, fx)
    ok, q_quality = _apply_quality_rules(ok, as_of)

    # ---- ⑦ 對維度
    ok = resolve_product_sk(ok, dim_product)
    ok = resolve_member_sk(ok, member.table, "_order_date")
    fact = (
        ok.withColumns(
            {
                "order_date_sk": date_sk(F.col("_order_date")),
                # 出發日空值時 sk 也是 NULL：沒有出發日（例如票券），不是「未知的日期」
                "departure_date_sk": date_sk(F.col("departure_date")),
                BATCH_ID_COL: F.lit(batch_id),
            }
        )
        .select(*FACT_ORDER_COLUMNS)
        .localCheckpoint()
    )

    quarantine = (
        q_contract.unionByName(q_collision)
        .unionByName(q_dedupe)
        .unionByName(q_existing)
        .unionByName(q_fx)
        .unionByName(q_quality)
        .select(
            F.lit(batch_id).alias(BATCH_ID_COL),
            *[F.col(f.name) for f in ORDERS_SCHEMA.fields],
            SOURCE_ERROR_COL,
            REJECT_CATEGORY_COL,
            REJECT_REASONS_COL,
        )
        .localCheckpoint()
    )

    # ---- 對帳：寫入前先確認守恆
    input_rows = orders.count()
    fact_rows = fact.count()
    q_rows = quarantine.count()
    if input_rows != fact_rows + q_rows:
        raise ReconciliationError(
            f"批次 {batch_id}：輸入 {input_rows} ≠ fact {fact_rows} ＋ 隔離 {q_rows}"
        )
    by_cat = {
        r[REJECT_CATEGORY_COL]: r["count"]
        for r in quarantine.groupBy(REJECT_CATEGORY_COL).count().collect()
    }
    unknown = fact.agg(
        F.sum((F.col("product_sk") == UNKNOWN_PRODUCT_SK).cast("int")).alias("p"),
        F.sum((F.col("member_sk") == UNKNOWN_MEMBER_SK).cast("int")).alias("m"),
    ).first()

    # ---- 寫入：隔離表（replaceWhere）→ fact（MERGE，order_id 已唯一）
    _write_quarantine(spark, quarantine, paths.quarantine, batch_id)
    merge_upsert(spark, fact, paths.fact_order, keys=["order_id"])

    table = spark.read.format("delta").load(str(paths.fact_order))
    return BatchReconciliation(
        batch_id=batch_id,
        input_rows=input_rows,
        fact_rows=fact_rows,
        quarantined_rows=q_rows,
        quarantined_by_category=by_cat,
        amount_twd_sum=_sum(fact, "amount_twd"),
        unknown_product_rows=unknown["p"] or 0,
        unknown_member_rows=unknown["m"] or 0,
        fact_table_rows=table.count(),
        fact_table_amount_twd_sum=_sum(table, "amount_twd"),
        member_rejected_rows=member.stats["rejected_rows"],
    )


def load_base(
    spark: SparkSession, source: SourceReader, paths: WarehousePaths
) -> BatchReconciliation:
    """初始載入：orders_base 當一批（batch_id='base'、as_of=2026-06-30）。"""
    return load_order_batch(
        spark,
        source,
        batch_id=BASE_BATCH_ID,
        orders=source.orders_base(),
        as_of=BASE_AS_OF,
        paths=paths,
    )
