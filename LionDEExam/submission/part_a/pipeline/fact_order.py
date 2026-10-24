"""fact_order：訂單事實表＋隔離表＋對帳，以「一批」為單位處理。

規則（使用者已定案）：
- 粒度：一張訂單一列、存最新狀態，以 order_id MERGE（ADR-04）。
- 同一 order_id 除了 updated_at 以外全部相同（V7）：取 updated_at 最新的一列，
  其餘以 duplicate 進隔離表。下單時間比較解析後的時刻，不比較原始字串（V7 有 8 組格式不同）。
- 同一 order_id 但會員、下單時間、金額任一不同（撞號）：整組進隔離表，不寫 fact（ADR-03）。
  同批內互相比較（find_batch_collisions），也和既有 fact 比較（find_existing_collisions）。
- 狀態：新舊以 updated_at 判斷（J6），狀態機檢查見 order_status_check；
  fact 只在 updated_at 較新時覆寫（MERGE 條件 s.updated_at > t.updated_at）。
- 金額：存 amount、currency（原值）、amount_twd。amount_twd 用台北下單日當天的匯率；
  TWD、NTD 固定 1（匯率表沒有 TWD，不能 inner join）。非 TWD／NTD 找不到當天匯率 → 隔離，
  不拿前一天的匯率代替。
- 產品清單有 rejected 列 → 整批停（ReferenceDataError），在寫任何表之前檢查。
- product_id 不在清單、會員對不到版本 → -1，對帳另列筆數。
- 隔離表：一張 Delta 表，每列帶 batch_id、原始字串、reject_category、reject_reasons；
  以 replaceWhere 清掉同一 batch_id 再寫，重跑冪等。略過的列（late_event）也存在這裡。
- 對帳：輸入列數＝寫進 fact＋隔離＋略過，用 count() 計算（build_spark() 的設定下才準）。

一批的處理順序（每一步淘汰的列都帶著原因進隔離表，所以各類別互斥、加總等於輸入）：
  ① 合約轉型（cast_to_contract）→ ② 同批撞號 → ③ 完全重複去重（duplicate）
  → ④ 與既有 fact 撞號 → ⑤ 狀態機（order_status_check）→ ⑥ 匯率
  → ⑦ 品質規則（A-3，目前沒有規則）→ ⑧ 對維度 → 寫入

純轉換在 transform_order_batch（不寫 Delta，測試直接驗 DataFrame）；
load_order_batch 負責參考資料檢查、維度寫入、對帳與寫入；run_all 用批次紀錄依序跑完
base → day1 → day2 → day3。
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, StringType

from pipeline.batch_log import BatchCounts, BatchRun, pin_fact_version, run_once
from pipeline.categories import SKIP_CATEGORIES, Category
from pipeline.contracts import (
    COUPON_UNKNOWN,
    FX_RATES_SCHEMA,
    ORDER_CURRENCIES,
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
from pipeline.order_status_check import (
    STATE_CATEGORY_COL,
    STATE_REASON_COL,
    STATE_SKIPPED_COL,
    StateCategory,
    classify_status_events,
)
from pipeline.sources import INCREMENTAL_DAYS, SourceReader
from pipeline.timeparse import parse_source_timestamp
from pipeline.validation import REJECT_REASONS_COL, cast_to_contract

# base 的批次代號與 as_of。會員快照截止在 06-30；base 訂單的下單日都在 06-30 以前，
# 但狀態最晚更新到 07-03（2,265 列的 updated_at 落在 07-01～07-03，L2）。
# as_of 只決定會員快照看到哪一天，會員依下單日對版本，所以用 06-30 不會偷看到之後的快照。
BASE_BATCH_ID = "base"
BASE_AS_OF = dt.date(2026, 6, 30)

# 增量批次：一個檔案＝一批；as_of 是檔案對應的業務日（day1＝07-01）
INCREMENTAL_AS_OF = {
    1: dt.date(2026, 7, 1),
    2: dt.date(2026, 7, 2),
    3: dt.date(2026, 7, 3),
}


def incremental_batch_id(day: int) -> str:
    return f"day{day}"


# 匯率固定為 1 的幣別：TWD 本身，以及 base 裡當作 TWD 別名的 NTD（V4）
TWD_PEGGED_CURRENCIES = ("TWD", "NTD")
assert set(TWD_PEGGED_CURRENCIES) <= set(ORDER_CURRENCIES)

# fact 只在來源列的 updated_at 較新時覆寫：亂序、重跑都不會讓狀態倒退
FACT_UPDATE_CONDITION = "s.updated_at > t.updated_at"

# 撞號判斷用的「不可變欄位」（ADR-03、J4）：同一張單這三欄不會變
IMMUTABLE_COLUMNS = ("member_id", "order_created_at", "amount")

# amount（18,2）× 匯率（18,6）的乘積精度是 37 位；四捨五入到 2 位後用 38 位存，避免溢位
AMOUNT_TWD_TYPE = DecimalType(38, 2)

BATCH_ID_COL = "batch_id"
REJECT_CATEGORY_COL = "reject_category"
_RAW = "_raw"
_BATCH_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


# Category 只定義在 pipeline.categories；從這裡 import 也拿得到同一個類別


def _commit_marker(batch_id: str) -> str:
    """fact 每次 MERGE 的 userMetadata：Delta history 看得出哪一批寫了哪個版本（稽核用）。"""
    return f"batch:{batch_id}"


# V3：coupon_discount＝-1.0（contracts.COUPON_UNKNOWN）代表「未知」，轉成 NULL，
# 訂單照常寫入（使用者定：「-1 代表未知，轉 NULL 不要猜」）。合約只放行 -1.00 這個負數，
# 其他負數在 ① 合約層隔離。
_COUPON_NULLED = "_coupon_nulled"

# 金額人工確認清單（amount_review）：照原樣寫入 fact，另列清單給人工逐筆判斷。兩種原因：
# - V2：疑似多乘 1,000（使用者定）。比值＝amount_twd ÷（產品定價 base_price_twd × 數量）；
#   正常列落在 0.84～1.29，疑似 ×1000 的列約 1,000。門檻 100 取兩者之間，離兩邊都很遠。
# - 折扣大於金額：coupon_discount > amount_twd，net_amount_twd 為負（使用者定 B：
#   「太大的可能是全額折抵」，所以不隔離）。〔防護性設計：本資料 0 筆〕
# 同一列兩種原因都中時只列一列，review_reasons 依上面的順序列出全部原因。
AMOUNT_REVIEW_RATIO = Decimal(100)
REVIEW_REASON_RATIO = (
    f"amount_ratio:金額比值超過 {AMOUNT_REVIEW_RATIO}（疑似多乘 1,000）"
)
REVIEW_REASON_COUPON = "coupon_discount:折扣大於 amount_twd（net_amount_twd 為負）"
REVIEW_REASONS_COL = "review_reasons"
AMOUNT_REVIEW_COLUMNS = (
    BATCH_ID_COL,
    "order_id",
    "product_id",
    "quantity",
    "currency",
    "amount",
    "fx_rate",
    "amount_twd",
    "base_price_twd",
    "amount_ratio",
    "coupon_discount",
    "net_amount_twd",
    REVIEW_REASONS_COL,
)


REASON_DUPLICATE = (
    "重複：和時間上相鄰的下一列除 updated_at 外全同，保留 updated_at 最新一列"
)
REASON_COLLISION = "撞號：同批同 order_id 的會員、下單時間或金額不同，整組隔離"
REASON_COLLISION_EXISTING = "撞號：與既有 fact 同 order_id，但會員、下單時間或金額不同"

# A-3 品質規則的掛載點：每條規則是一個函式，收這批的 as_of（例如「completed 但出發日未到」
# 要拿出發日和 as_of 比），回傳一個原因字串的 Column：作用在「已換算金額、尚未對維度」的
# 候選列上（可用 orders 合約欄位，order_created_at、updated_at 已是 timestamp，另有
# fx_rate、amount_twd），不違規時為 NULL。A-3 定案後目前沒有需要隔離的品質規則：
# 負數金額在合約擋下（V1）、coupon -1.0 轉 NULL（V3）、疑似 ×1000 另列清單（V2）、
# completed 但出發日未到只記錄（L10）。
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
    # 折扣後金額（J10：amount 是折扣前；coupon 是台幣）；coupon 為 NULL 時也是 NULL
    "net_amount_twd",
    "order_created_at",
    "updated_at",
    BATCH_ID_COL,
)

QUARANTINE_COLUMNS = (
    BATCH_ID_COL,
    *[f.name for f in ORDERS_SCHEMA.fields],
    SOURCE_ERROR_COL,
    REJECT_CATEGORY_COL,
    REJECT_REASONS_COL,
)


class ReferenceDataError(ValueError):
    """參考資料（產品清單、匯率表）有問題：整批停下，fact 與隔離表都不寫入。"""


class ReconciliationError(RuntimeError):
    """輸入≠寫入＋隔離＋略過：程式有漏洞，寫入前就停下。"""


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

    @property
    def batch_log(self) -> Path:
        return self.root / "batch_log"

    @property
    def batch_force_log(self) -> Path:
        return self.root / "batch_log_force"

    @property
    def batch_start(self) -> Path:
        return self.root / "batch_start"

    @property
    def amount_review(self) -> Path:
        return self.root / "amount_review"


@dataclass(frozen=True)
class BatchReconciliation(BatchCounts):
    """一批的對帳結果：BatchCounts 的數字（說明見 batch_log.BatchCounts）＋batch_id。

    fact_rows 是狀態機接受、送進 MERGE 的列；MERGE 只在 updated_at 較新時覆寫，
    所以正常情況下全部生效（狀態機已保證比 fact 新）。
    """

    batch_id: str


@dataclass(frozen=True)
class BatchTransform:
    """transform_order_batch 的結果（都還沒寫入）。

    - valid：通過合約的列（已轉型），給 dim_date 擴充日期範圍。
    - fact：要 MERGE 進 fact 的列，FACT_ORDER_COLUMNS 再加兩個計數用的旗標欄
      STATE_SKIPPED_COL（跳過中間狀態）、_coupon_nulled（coupon -1.0 轉成 NULL），寫入前拿掉。
    - quarantine：隔離表的列（含略過的 late_event），QUARANTINE_COLUMNS。
    - amount_review：fact 中金額比值超過 AMOUNT_REVIEW_RATIO 的列（V2 人工確認清單），
      AMOUNT_REVIEW_COLUMNS。
    """

    valid: DataFrame
    fact: DataFrame
    quarantine: DataFrame
    amount_review: DataFrame


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

    orders 同一 order_id 可以有多列（狀態機之前）；回傳的 order_id 已去重，
    呼叫端用 left_semi／left_anti 取整組。兩邊欄位型別相同（timestamp、Decimal）。
    """
    o, f = orders.alias("o"), fact.alias("f")
    same = _all(
        [F.col(f"o.{c}").eqNullSafe(F.col(f"f.{c}")) for c in IMMUTABLE_COLUMNS]
    )
    return (
        o.join(f, F.col("o.order_id") == F.col("f.order_id"))
        .filter(~same)
        .select(F.col("o.order_id").alias("order_id"))
        .distinct()
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
    """完全重複（V7）：只有「時間上相鄰」且除 updated_at 外全同的列才算重複。

    使用者定（「中間如果有出現其他狀態 不能當作延遲」）：同一張單依 updated_at 排序，
    兩列之間夾著其他內容的列，就不算重複，要交給狀態機（例如 cancelled → paid → cancelled，
    第一個 cancelled 不能刪，否則往回走會被蓋掉）。

    做法：同一張單、同一個 updated_at 的列算一組。
    - 一組裡只有一種內容（純組）：組內只留排序最後一列；如果下一組（時間上的下一個
      updated_at）也是純組、內容相同，這一組整組都算重複，保留最新的那組。
    - 一組裡有多種內容（同一秒不同內容）：整組都不去重，交給狀態機判斷同一秒衝突。
    同一組內的先後依原始字串排序，只為了結果確定（重跑選同一列）。
    """
    content = F.struct(*[c for c in orders.columns if c not in ("updated_at", _RAW)])
    df = orders.withColumn("_content", content)
    # 每張單、每個 updated_at 一組：是否只有一種內容，以及下一組（時間上的下一個）的內容
    groups = df.groupBy("order_id", "updated_at").agg(
        (F.size(F.collect_set("_content")) == 1).alias("_pure"),
        F.min("_content").alias("_group_content"),
    )
    by_order = Window.partitionBy("order_id").orderBy("updated_at")
    groups = groups.withColumns(
        {
            "_next_pure": F.lead("_pure").over(by_order),
            "_next_content": F.lead("_group_content").over(by_order),
        }
    )
    same_as_next_group = F.coalesce(
        F.col("_next_pure") & (F.col("_next_content") == F.col("_group_content")),
        F.lit(False),
    )
    df = df.join(
        groups.select(
            "order_id",
            "updated_at",
            "_pure",
            same_as_next_group.alias("_same_as_next"),
        ),
        ["order_id", "updated_at"],
    ).withColumn(
        "_last_in_ts",
        F.row_number().over(
            Window.partitionBy("order_id", "updated_at").orderBy(F.col(_RAW).desc())
        )
        == 1,
    )
    is_dup = F.col("_pure") & (~F.col("_last_in_ts") | F.col("_same_as_next"))
    df = df.withColumn("_is_dup", is_dup)
    helpers = ["_content", "_pure", "_same_as_next", "_last_in_ts", "_is_dup"]
    kept = df.filter(~F.col("_is_dup")).drop(*helpers)
    dup = _quarantine_rows(
        df.filter(F.col("_is_dup")), Category.DUPLICATE, F.lit(REASON_DUPLICATE)
    )
    return kept, dup


def _clean_coupon(orders: DataFrame) -> DataFrame:
    """V3：coupon_discount＝-1.0 轉成 NULL，並標記 _coupon_nulled（對帳計數用）。"""
    unknown = F.coalesce(F.col("coupon_discount") == COUPON_UNKNOWN, F.lit(False))
    return orders.withColumns(
        {
            _COUPON_NULLED: unknown,
            "coupon_discount": F.when(~unknown, F.col("coupon_discount")),
        }
    )


def _amount_review(fact: DataFrame, dim_product: DataFrame) -> DataFrame:
    """金額人工確認清單：fact 列中命中任一原因的列，每張單一列，review_reasons 列出全部原因。

    - V2：比值 amount_twd ÷（base_price_twd × quantity）超過 AMOUNT_REVIEW_RATIO。
      產品落到 -1（沒有定價）或定價、數量不是正數時算不出比值，不算命中。
    - coupon_discount > amount_twd（net 為負）。coupon 為 NULL 時不算命中。
      〔防護性設計：本資料 0 筆〕
    """
    prices = dim_product.select("product_sk", "base_price_twd")
    denom = F.col("base_price_twd") * F.col("quantity")
    ratio = F.when(denom > 0, F.col("amount_twd") / denom)
    reasons = F.filter(
        F.array(
            _reason_if(
                F.col("amount_ratio") > F.lit(AMOUNT_REVIEW_RATIO), REVIEW_REASON_RATIO
            ),
            _reason_if(
                F.col("coupon_discount") > F.col("amount_twd"), REVIEW_REASON_COUPON
            ),
        ),
        lambda r: r.isNotNull(),
    )
    return (
        fact.join(prices, "product_sk", "left")
        .withColumn("amount_ratio", F.round(ratio, 2).cast(DecimalType(38, 2)))
        .withColumn(REVIEW_REASONS_COL, reasons)
        .filter(F.size(REVIEW_REASONS_COL) > 0)
        .select(*AMOUNT_REVIEW_COLUMNS)
    )


def _reason_if(cond: Column, text: str) -> Column:
    """條件成立時回傳原因字串；不成立或條件為 NULL 時回傳 NULL。"""
    return F.when(cond, F.lit(text))


def _apply_state_machine(
    orders: DataFrame, fact: DataFrame | None
) -> tuple[DataFrame, DataFrame]:
    """狀態機：接受的列（每張單最多一列，帶 STATE_SKIPPED_COL）往下走，其餘進隔離表。"""
    state = (
        None if fact is None else fact.select("order_id", "order_status", "updated_at")
    )
    classified = classify_status_events(orders, state, tiebreak=[_RAW])
    cat = F.col(STATE_CATEGORY_COL)
    ok = classified.filter(cat == StateCategory.ACCEPTED).drop(
        STATE_CATEGORY_COL, STATE_REASON_COL
    )
    bad = classified.filter(cat != StateCategory.ACCEPTED).select(
        F.col(f"{_RAW}.*"),
        cat.alias(REJECT_CATEGORY_COL),
        F.array(STATE_REASON_COL).alias(REJECT_REASONS_COL),
    )
    return ok, bad


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


# ---------------------------------------------------------------- 純轉換


def transform_order_batch(
    orders: DataFrame,
    *,
    batch_id: str,
    as_of: dt.date,
    fx: DataFrame,
    dim_product: DataFrame,
    dim_member: DataFrame,
    existing: DataFrame | None,
) -> BatchTransform:
    """一批訂單的所有轉換步驟（①～⑧），不寫 Delta、不觸發計算。

    - orders：原始字串訂單（source.orders_base() 等）。
    - fx：已通過合約的匯率表；dim_product、dim_member：整張維度表。
    - existing：這批之前的 fact（None 表示還沒有 fact）。撞號與狀態機都和它比。
    """
    # ① 合約轉型；原始字串收進 _raw 一路帶著
    valid, rejected = cast_to_contract(
        _with_raw(orders), ORDERS_SCHEMA, passthrough=(_RAW,)
    )
    q_contract = rejected.select(
        F.col(f"{_RAW}.*"),
        F.lit(Category.CONTRACT).alias(REJECT_CATEGORY_COL),
        REJECT_REASONS_COL,
    )
    typed = valid.withColumns(
        {
            "order_created_at": parse_source_timestamp(F.col("order_created_at")),
            "updated_at": parse_source_timestamp(F.col("updated_at")),
        }
    ).withColumn("_order_date", F.to_date("order_created_at"))
    typed = _clean_coupon(typed)  # V3：清理規則，不隔離

    ok, q_collision = _split_collisions(typed)  # ②
    ok, q_dedupe = _dedupe(ok)  # ③
    ok, q_existing = _split_existing_collisions(ok, existing)  # ④
    ok, q_state = _apply_state_machine(ok, existing)  # ⑤
    ok, q_fx = _convert_currency(ok, fx)  # ⑥
    ok, q_quality = _apply_quality_rules(ok, as_of)  # ⑦

    # ⑧ 對維度
    ok = resolve_product_sk(ok, dim_product)
    ok = resolve_member_sk(ok, dim_member, "_order_date")
    fact = ok.withColumns(
        {
            "order_date_sk": date_sk(F.col("_order_date")),
            # 出發日空值時 sk 也是 NULL：沒有出發日（例如票券），不是「未知的日期」
            "departure_date_sk": date_sk(F.col("departure_date")),
            "net_amount_twd": (F.col("amount_twd") - F.col("coupon_discount")).cast(
                AMOUNT_TWD_TYPE
            ),
            BATCH_ID_COL: F.lit(batch_id),
        }
    ).select(*FACT_ORDER_COLUMNS, STATE_SKIPPED_COL, _COUPON_NULLED)

    quarantine = (
        q_contract.unionByName(q_collision)
        .unionByName(q_dedupe)
        .unionByName(q_existing)
        .unionByName(q_state)
        .unionByName(q_fx)
        .unionByName(q_quality)
        .withColumn(BATCH_ID_COL, F.lit(batch_id))
        .select(*QUARANTINE_COLUMNS)
    )
    return BatchTransform(
        valid=valid,
        fact=fact,
        quarantine=quarantine,
        amount_review=_amount_review(fact, dim_product),
    )


# ---------------------------------------------------------------- 入口


def _fact_before_batch(
    spark: SparkSession, paths: WarehousePaths, batch_id: str
) -> DataFrame | None:
    """這批「開始之前」的 fact 快照；狀態機與撞號都和它比。

    第一次跑時就是目前的 fact，並把目前版本記在 batch_start（batch_log.pin_fact_version）。
    當掉後重跑、強制重跑時，fact 可能已經包含這批的結果，若直接拿來比，這批每列都會變成
    晚到事件，分類和第一次不同；所以改用記下的版本做 time travel。
    這批寫進 fact 的列是 0 時 Delta 不會產生 commit，所以版本要在開始時記，
    不能事後從 history 找。
    """
    path = str(paths.fact_order)
    current = (
        DeltaTable.forPath(spark, path).history(1).first()["version"]
        if DeltaTable.isDeltaTable(spark, path)
        else -1
    )
    version = pin_fact_version(spark, paths.batch_start, batch_id, current)
    if version < 0:
        return None
    return (
        spark.read.format("delta").option("versionAsOf", version).load(path)
    ).localCheckpoint()


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
      不偷看之後的快照。dim_date 只依這批訂單擴充（和既有範圍取聯集）。
    - 產品清單有違規列或 product_id 重複、匯率表有違規列或同日同幣別重複
      → ReferenceDataError，在寫任何表之前停下。
    - 對帳不平 → ReconciliationError，同樣在寫 fact、隔離表之前停下。
    - 不檢查批次順序、不寫批次紀錄；正式執行請用 run_all（或 batch_log.run_once 包住）。
    """
    if not _BATCH_ID_PATTERN.fullmatch(batch_id):
        raise ValueError(f"batch_id 只能用英數、底線、連字號：{batch_id!r}")

    # ---- 參考資料：先檢查，有問題整批停
    products, rejected_products = cast_to_contract(source.products(), PRODUCTS_SCHEMA)
    _check_reference("products", rejected_products)
    fx, rejected_fx = cast_to_contract(source.fx_rates(), FX_RATES_SCHEMA)
    _check_reference("fx_rates", rejected_fx)
    _check_fx_unique(fx)

    # ---- 維度：dim_member 只看到 as_of 為止
    try:
        dim_product = write_dim_product(spark, products, paths.dim_product)
    except DuplicateKeyError as e:
        # 統一成 ReferenceDataError：呼叫端只需要處理一種參考資料錯誤。
        # build_dim_product 在 MERGE 之前就檢查，所以丟出時任何表都還沒寫入
        raise ReferenceDataError(f"products 不能使用，整批停下：{e}") from e
    member = write_dim_member(spark, source.members(), paths.dim_member, through=as_of)

    existing = _fact_before_batch(spark, paths, batch_id)
    t = transform_order_batch(
        orders,
        batch_id=batch_id,
        as_of=as_of,
        fx=fx,
        dim_product=dim_product,
        dim_member=member.table,
        existing=existing,
    )
    # dim_date 只依這批訂單擴充：逐日處理時不偷看之後的增量
    write_dim_date(spark, t.valid, paths.dim_date)
    fact = t.fact.localCheckpoint()
    quarantine = t.quarantine.localCheckpoint()
    review = t.amount_review.localCheckpoint()

    # ---- 對帳：寫入前先確認守恆
    input_rows = orders.count()
    fact_rows = fact.count()
    q_all = quarantine.count()
    if input_rows != fact_rows + q_all:
        raise ReconciliationError(
            f"批次 {batch_id}：輸入 {input_rows} ≠ fact {fact_rows} ＋ 隔離與略過 {q_all}"
        )
    by_cat = {
        r[REJECT_CATEGORY_COL]: r["count"]
        for r in quarantine.groupBy(REJECT_CATEGORY_COL).count().collect()
    }
    skipped = sum(n for c, n in by_cat.items() if c in SKIP_CATEGORIES)
    quarantined_by_category = {
        c: n for c, n in by_cat.items() if c not in SKIP_CATEGORIES
    }
    stats = fact.agg(
        F.sum((F.col("product_sk") == UNKNOWN_PRODUCT_SK).cast("int")).alias("p"),
        F.sum((F.col("member_sk") == UNKNOWN_MEMBER_SK).cast("int")).alias("m"),
        F.sum(F.col(STATE_SKIPPED_COL).cast("int")).alias("skip"),
        F.sum(F.col(_COUPON_NULLED).cast("int")).alias("coupon"),
    ).first()

    # ---- 寫入：隔離表（replaceWhere）→ fact（MERGE，order_id 已唯一，只在較新時覆寫）
    _write_quarantine(spark, quarantine, paths.quarantine, batch_id)
    _write_quarantine(spark, review, paths.amount_review, batch_id)
    merge_upsert(
        spark,
        fact.drop(STATE_SKIPPED_COL, _COUPON_NULLED),
        paths.fact_order,
        keys=["order_id"],
        update_condition=FACT_UPDATE_CONDITION,
        commit_marker=_commit_marker(batch_id),
    )

    table = spark.read.format("delta").load(str(paths.fact_order))
    return BatchReconciliation(
        batch_id=batch_id,
        input_rows=input_rows,
        fact_rows=fact_rows,
        quarantined_rows=q_all - skipped,
        skipped_rows=skipped,
        quarantined_by_category=quarantined_by_category,
        skipped_intermediate_rows=stats["skip"] or 0,
        coupon_nulled_rows=stats["coupon"] or 0,
        amount_review_rows=review.count(),
        amount_twd_sum=_sum(fact, "amount_twd"),
        net_amount_twd_sum=_sum(fact, "net_amount_twd"),
        unknown_product_rows=stats["p"] or 0,
        unknown_member_rows=stats["m"] or 0,
        fact_table_rows=table.count(),
        fact_table_amount_twd_sum=_sum(table, "amount_twd"),
        fact_table_net_amount_twd_sum=_sum(table, "net_amount_twd"),
        member_rejected_rows=member.stats["rejected_rows"],
    )


def load_base(
    spark: SparkSession, source: SourceReader, paths: WarehousePaths
) -> BatchReconciliation:
    """初始載入：orders_base 當一批（batch_id='base'、as_of=2026-06-30）。不寫批次紀錄。"""
    return load_order_batch(
        spark,
        source,
        batch_id=BASE_BATCH_ID,
        orders=source.orders_base(),
        as_of=BASE_AS_OF,
        paths=paths,
    )


def load_incremental(
    spark: SparkSession, source: SourceReader, day: int, paths: WarehousePaths
) -> BatchReconciliation:
    """第 day 天的增量檔當一批（batch_id='day{day}'、as_of＝INCREMENTAL_AS_OF）。不寫批次紀錄。"""
    if day not in INCREMENTAL_AS_OF:
        raise ValueError(f"沒有第 {day} 天的增量檔，可用：{tuple(INCREMENTAL_AS_OF)}")
    return load_order_batch(
        spark,
        source,
        batch_id=incremental_batch_id(day),
        orders=source.orders_incremental(day),
        as_of=INCREMENTAL_AS_OF[day],
        paths=paths,
    )


def run_batch(
    spark: SparkSession,
    source: SourceReader,
    paths: WarehousePaths,
    day: int | None,
    *,
    force: bool = False,
) -> BatchRun:
    """用批次紀錄包住一批（day=None 是 base）：依序檢查、已完成就跳過、最後寫紀錄。"""
    if day is None:
        batch_id, as_of = BASE_BATCH_ID, BASE_AS_OF

        def run() -> BatchReconciliation:
            return load_base(spark, source, paths)
    else:
        batch_id, as_of = incremental_batch_id(day), INCREMENTAL_AS_OF[day]

        def run() -> BatchReconciliation:
            return load_incremental(spark, source, day, paths)

    return run_once(
        spark,
        paths.batch_log,
        batch_id=batch_id,
        as_of=as_of,
        source_checksum=source.orders_checksum(day),
        reference_checksums=source.reference_checksums(),
        force_log_path=paths.batch_force_log,
        run=run,
        force=force,
    )


def run_all(
    spark: SparkSession,
    source: SourceReader,
    paths: WarehousePaths,
    *,
    days: tuple[int, ...] = INCREMENTAL_DAYS,
) -> list[BatchRun]:
    """依序跑 base → day1 → day2 → day3；已完成的批次跳過（回傳既有紀錄）。"""
    return [run_batch(spark, source, paths, d) for d in (None, *days)]
