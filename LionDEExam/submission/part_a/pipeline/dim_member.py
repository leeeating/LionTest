"""dim_member：會員維度（SCD Type 2）。

規則（使用者已定案，見 process-log「dim_member SCD2 規則」）：
- 依 extract_date 由舊到新處理；某位會員沒出現在某一批，沿用前一版；內容沒變不開新版。
- member_level、city 是 Type 2（值變就開新版）；member_name、birth_date 是 Type 1
  （覆寫該會員所有版本，更正不算歷史）。
- 第一版 valid_from＝register_date（訂單可能早於第一次快照）。
- 同日矛盾（同 member_id、同 extract_date 多列）取較高等級：一般 < 銀卡 < 金卡 < 白金。
- city 'N/A'、birth_date 1900-01-01 轉 NULL，而且不蓋掉已知的真實值。
- member_sk＝xxhash64(member_id, valid_from)，重跑穩定。

本模組自己決定的部分（理由寫在各常數與函式旁）：
- 第二版以後的 valid_from＝觀察到變動那一批的 extract_date。
- valid_to 不含當天（＝下一版的 valid_from），目前版本是 9999-12-31；另有 is_current。
- city 從 NULL 變成真實值：當成變動，開新版本（不回填舊版本）。
- 寫入：以 member_sk MERGE；狀態存在表裡，可以一批一批餵（見 write_dim_member）。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StringType

from pipeline.contracts import MEMBERS_SCHEMA, SOURCE_ERROR_COL
from pipeline.delta_io import merge_upsert
from pipeline.validation import REJECT_REASONS_COL, cast_to_contract, strict_date

# 等級由低到高。資料裡實際出現的值只有這四個（members.csv 8,991 列已查過）；
# 清單外的值（含 NULL）進 rejected，不猜它的排序。
LEVEL_ORDER = ("一般", "銀卡", "金卡", "白金")

CITY_PLACEHOLDER = "N/A"
BIRTH_PLACEHOLDER = dt.date(1900, 1, 1)

# 目前版本的 valid_to。用固定的遠未來日期而不是 NULL：
# fact 對版本時可以統一寫成 valid_from <= d < valid_to，不必特判 NULL。
CURRENT_VALID_TO = dt.date(9999, 12, 31)

# 未知會員：fact 的 member_id 對不到任何版本時落到這一列（比照 dim_product 的 -1）。
UNKNOWN_MEMBER_ID = "UNKNOWN"
UNKNOWN_MEMBER_SK = -1
UNKNOWN_MEMBER_NAME = "未知會員"

DIM_MEMBER_COLUMNS = (
    "member_sk",
    "member_id",
    "member_name",
    "member_level",
    "city",
    "birth_date",
    "register_date",
    "valid_from",
    "valid_to",
    "is_current",
    # 這位會員已處理到哪一批快照；用來擋掉重送的舊快照（見 _fresh_snapshots）
    "last_seen_extract_date",
)


@dataclass
class DimMemberBuild:
    """build_dim_member 的結果（只計算、未寫入）。

    - changes：要 MERGE 進 dim_member 的列，只有「受這批影響的會員的所有版本＋未知會員列」；
      表原本不存在時才等於整張表。**不能拿去 resolve_member_sk**：
      沒出現在這批的會員不在裡面，對應時會全部落到 -1。
    - rejected：違規列，形狀同 cast_to_contract 的 rejected_df（原始字串＋reject_reasons），
      隔離表的寫入由呼叫端（T5）處理。
    - stats：計數，給對帳與報告用。
    """

    changes: DataFrame
    rejected: DataFrame
    stats: dict[str, int]


@dataclass
class DimMemberWrite:
    """write_dim_member 的結果。

    - table：寫入後從 Delta 讀回的**整張** dim_member，可以直接給 resolve_member_sk。
    - rejected、stats：同 DimMemberBuild。
    """

    table: DataFrame
    rejected: DataFrame
    stats: dict[str, int]


def member_sk(member_id: Column, valid_from: Column) -> Column:
    """版本代理鍵：同一個 (member_id, valid_from) 不論重跑幾次、輸入順序如何都相同。"""
    return F.xxhash64(member_id, valid_from)


def _level_rank(level: Column) -> Column:
    pairs = [
        x for i, name in enumerate(LEVEL_ORDER, 1) for x in (F.lit(name), F.lit(i))
    ]
    return F.element_at(F.create_map(*pairs), level)


def _extra_checks(valid: DataFrame) -> tuple[DataFrame, DataFrame]:
    """合約以外、dim_member 特有的列層級檢查；回傳 (ok, rejected)。

    - member_level 不在 LEVEL_ORDER：沒有排序就無法處理同日矛盾，也不該猜。
    - register_date 晚於 extract_date：第一版會從快照之後才開始，版本區間會倒置。
    rejected 轉回原始字串形狀，和 cast_to_contract 的 rejected 可以直接 union。
    合約只接受 yyyy-MM-dd 的日期，所以日期轉回字串會和原文相同。
    """
    reasons = F.filter(
        F.array(
            F.when(
                _level_rank(F.col("member_level")).isNull(),
                F.lit("member_level:不在等級清單（" + "/".join(LEVEL_ORDER) + "）"),
            ),
            F.when(
                F.col("register_date") > F.col("extract_date"),
                F.lit("register_date:晚於 extract_date"),
            ),
        ),
        lambda r: r.isNotNull(),
    )
    checked = valid.withColumn(REJECT_REASONS_COL, reasons)
    ok = checked.filter(F.size(REJECT_REASONS_COL) == 0).drop(REJECT_REASONS_COL)
    bad = checked.filter(F.size(REJECT_REASONS_COL) > 0).select(
        *[
            F.col(f.name).cast(StringType()).alias(f.name)
            for f in MEMBERS_SCHEMA.fields
        ],
        F.lit(None).cast(StringType()).alias(SOURCE_ERROR_COL),
        REJECT_REASONS_COL,
    )
    return ok, bad


def _normalize(ok: DataFrame) -> DataFrame:
    """假值轉 NULL，並解決同日矛盾，讓 (member_id, extract_date) 唯一。

    同日多列時取等級最高的一列；等級相同時再依其他欄位排序，只是為了結果確定，
    實際資料中同日兩列除了等級以外完全相同。
    """
    clean = ok.withColumn(
        "city",
        F.when(F.col("city") == CITY_PLACEHOLDER, None).otherwise(F.col("city")),
    ).withColumn(
        "birth_date",
        F.when(F.col("birth_date") == F.lit(BIRTH_PLACEHOLDER), None).otherwise(
            F.col("birth_date")
        ),
    )
    w = Window.partitionBy("member_id", "extract_date").orderBy(
        _level_rank(F.col("member_level")).desc(),
        F.col("member_name").asc_nulls_last(),
        F.col("city").asc_nulls_last(),
        F.col("birth_date").asc_nulls_last(),
        F.col("register_date").asc_nulls_last(),
    )
    return clean.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")


def _snapshot_obs(snapshots: DataFrame) -> DataFrame:
    return snapshots.select(
        "member_id",
        F.col("extract_date").alias("obs_date"),
        "member_level",
        "city",
        "member_name",
        "birth_date",
        "register_date",
        F.col("extract_date").alias("obs_seen"),
    )


def _fresh_snapshots(snapshots: DataFrame, existing: DataFrame | None) -> DataFrame:
    """丟掉 extract_date ≤ 該會員 last_seen_extract_date 的快照列。

    那些快照已經處理過（重跑），或比已處理的還舊（重送舊檔）；
    不能讓舊快照把會員「改回去」，也不能讓重跑多開版本。
    """
    if existing is None:
        return snapshots
    seen = existing.filter(f"is_current AND member_sk <> {UNKNOWN_MEMBER_SK}").select(
        "member_id", F.col("last_seen_extract_date").alias("_seen")
    )
    return (
        snapshots.join(seen, "member_id", "left")
        .filter(F.col("_seen").isNull() | (F.col("extract_date") > F.col("_seen")))
        .drop("_seen")
    )


def _observations(fresh: DataFrame, existing: DataFrame | None) -> DataFrame:
    """把「表裡已有的版本」和「這批新快照」攤成同一條時間軸上的觀察值。

    - 既有版本各算一筆觀察（日期＝valid_from），Type 1 欄位帶表裡的值。
    - 只回傳這批有新快照的會員；其他會員的版本不必重算。
    """
    snap_obs = _snapshot_obs(fresh)
    if existing is None:
        return snap_obs
    old_obs = existing.filter(F.col("member_sk") != UNKNOWN_MEMBER_SK).join(
        fresh.select("member_id").distinct(), "member_id", "left_semi"
    )
    old_obs = old_obs.select(
        "member_id",
        F.col("valid_from").alias("obs_date"),
        "member_level",
        "city",
        "member_name",
        "birth_date",
        "register_date",
        F.col("last_seen_extract_date").alias("obs_seen"),
    )
    return old_obs.unionByName(snap_obs)


def _versions(obs: DataFrame) -> DataFrame:
    """由觀察值算出 SCD2 版本。"""
    by_member = Window.partitionBy("member_id")
    ordered = by_member.orderBy("obs_date")
    upto_now = ordered.rowsBetween(Window.unboundedPreceding, Window.currentRow)
    whole = ordered.rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing)

    obs = obs.withColumns(
        {
            # city 的 NULL 是「不知道」，不蓋掉之前已知的值
            "city": F.last("city", ignorenulls=True).over(upto_now),
            "_rn": F.row_number().over(ordered),
        }
    )
    changed = (F.col("_rn") == 1) | ~(
        F.col("member_level").eqNullSafe(F.lag("member_level").over(ordered))
        & F.col("city").eqNullSafe(F.lag("city").over(ordered))
    )
    obs = obs.withColumns(
        {
            "_changed": changed,
            # Type 1：取最新的已知值，覆寫所有版本；NULL（含假值）不蓋真值
            "member_name": F.last("member_name", ignorenulls=True).over(whole),
            "birth_date": F.last("birth_date", ignorenulls=True).over(whole),
            # 第一版的 valid_from 用第一次看到的 register_date，之後不再變動，
            # 否則 sk 會跟著變
            "register_date": F.first("register_date", ignorenulls=True).over(whole),
            "last_seen_extract_date": F.max("obs_seen").over(by_member),
        }
    )
    versions = obs.filter("_changed").withColumn(
        "valid_from",
        F.when(F.col("_rn") == 1, F.col("register_date")).otherwise(F.col("obs_date")),
    )
    next_from = F.lead("valid_from").over(by_member.orderBy("valid_from"))
    return versions.withColumns(
        {
            "valid_to": F.coalesce(next_from, F.lit(CURRENT_VALID_TO)),
            "is_current": next_from.isNull(),
            "member_sk": member_sk(F.col("member_id"), F.col("valid_from")),
        }
    ).select(*DIM_MEMBER_COLUMNS)


def _unknown_row(spark: SparkSession) -> DataFrame:
    return spark.createDataFrame(
        [
            (
                UNKNOWN_MEMBER_SK,
                UNKNOWN_MEMBER_ID,
                UNKNOWN_MEMBER_NAME,
                None,
                None,
                None,
                None,
                dt.date(1900, 1, 1),
                CURRENT_VALID_TO,
                True,
                None,
            )
        ],
        "member_sk BIGINT, member_id STRING, member_name STRING, member_level STRING,"
        " city STRING, birth_date DATE, register_date DATE, valid_from DATE,"
        " valid_to DATE, is_current BOOLEAN, last_seen_extract_date DATE",
    )


def _not_after(members: DataFrame, through: dt.date) -> DataFrame:
    """只留 extract_date <= through 的原始列。

    extract_date 不符合合約日期規則的列也留下，讓 cast_to_contract 把它分到 rejected，
    否則壞列會被這個過濾靜默吃掉，筆數就不守恆。判斷用合約的嚴格規則（strict_date），
    不用 try_cast：try_cast 會把 "2026-07-15 junk" 當成 07-15，壞列就被算成
    「through 之後」，要等到之後的批次才被發現。
    """
    parsed = strict_date(F.col("extract_date"))
    return members.filter(F.coalesce(parsed <= F.lit(through), F.lit(True)))


def build_dim_member(
    spark: SparkSession,
    members: DataFrame,
    *,
    through: dt.date,
    existing: DataFrame | None = None,
) -> DimMemberBuild:
    """由原始會員快照算出要 MERGE 進 dim_member 的列（不寫入）。

    - members：source.members() 的原始字串 DataFrame，可以含一批或多批 extract_date。
    - through：必填，只處理 extract_date <= through 的快照。比照 dims.all_orders 的
      days 必傳：逐日處理時忘了過濾，就會偷看到之後的快照，所以不給預設值。
    - existing：目前的 dim_member 表；None 表示從頭建。
    """
    all_rows = members
    members = _not_after(members, through)
    valid, rejected_cast = cast_to_contract(members, MEMBERS_SCHEMA)
    ok, rejected_extra = _extra_checks(valid)
    rejected = rejected_cast.unionByName(rejected_extra, allowMissingColumns=True)
    snapshots = _normalize(ok)
    fresh = _fresh_snapshots(snapshots, existing)
    table = _versions(_observations(fresh, existing)).unionByName(_unknown_row(spark))

    raw_ok = ok.agg(
        F.count(F.lit(1)).alias("n"),
        F.count_distinct("member_id", "extract_date").alias("n_keys"),
        F.sum((F.col("city") == CITY_PLACEHOLDER).cast("int")).alias("city_ph"),
        F.sum((F.col("birth_date") == F.lit(BIRTH_PLACEHOLDER)).cast("int")).alias(
            "birth_ph"
        ),
    ).first()
    conflicts = (
        ok.groupBy("member_id", "extract_date").count().filter("count > 1").count()
    )
    n_snap = snapshots.count()
    stats = {
        # input_rows＝through 以內的列；valid＋rejected＝input_rows
        "input_rows": members.count(),
        "rows_after_through": all_rows.count() - members.count(),
        "rejected_rows": rejected.count(),
        "same_day_conflicts": conflicts,
        "same_day_rows_dropped": raw_ok["n"] - raw_ok["n_keys"],
        "city_placeholder_rows": raw_ok["city_ph"] or 0,
        "birth_placeholder_rows": raw_ok["birth_ph"] or 0,
        "snapshot_rows": n_snap,
        "stale_rows_skipped": n_snap - fresh.count(),
    }
    return DimMemberBuild(changes=table, rejected=rejected, stats=stats)


def write_dim_member(
    spark: SparkSession, members: DataFrame, path: str | Path, *, through: dt.date
) -> DimMemberWrite:
    """把 extract_date <= through 的會員快照併入 dim_member，以 member_sk MERGE。

    回傳的 table 是寫入後讀回的整張表（不是只有這批的變動），可以直接拿去 resolve_member_sk。

    - 狀態存在表裡：表中每位會員的版本加上 last_seen_extract_date，
      就足以接著處理下一批，不需要重讀舊快照。所以「04-30 一批、05-31 一批」分兩次餵，
      和「到 05-31 的資料一次餵」結果相同。
    - 冪等：重送已處理過或更舊的快照列會被跳過，表內容不變。
    - 已存在的版本不會被刪：新快照只會在既有版本之後追加版本、更新 valid_to、
      is_current 與 Type 1 欄位，所以 MERGE（無 delete）就夠了。
    """
    path = str(path)
    existing = None
    if DeltaTable.isDeltaTable(spark, path):
        # 讀成快照並物化：來源與 MERGE 目標是同一張表，避免 MERGE 中途重讀
        existing = spark.read.format("delta").load(path).localCheckpoint()
    result = build_dim_member(spark, members, through=through, existing=existing)
    merge_upsert(spark, result.changes.localCheckpoint(), path, keys=["member_sk"])
    return DimMemberWrite(
        table=spark.read.format("delta").load(path),
        rejected=result.rejected,
        stats=result.stats,
    )


def resolve_member_sk(
    fact_df: DataFrame, dim_df: DataFrame, date_col: str
) -> DataFrame:
    """替 fact_df 補上 member_sk：依 member_id 與 date_col 對到當時有效的版本。

    - dim_df：**必須是整張 dim_member**（例如 write_dim_member 回傳的 table，
      或 spark.read.format("delta").load(path)）。若只給部分會員，其他會員的訂單會
      靜默落到 -1，而 fact 列數不變，對帳抓不到。
    - date_col：fact_df 中 DateType 的欄位，應為台北時間的下單日
      （session timezone 是 Asia/Taipei，用
      to_date(parse_source_timestamp(order_created_at)) 先算出來）。
    - 版本區間是 valid_from <= 日期 < valid_to，互不重疊，所以每張單最多對到一版，
      fact_df 的列數不變。
    - 對不到的（member_id 不存在或為 NULL、下單日早於 register_date）一律為 -1。
    """
    dim = dim_df.filter(F.col("member_sk") != UNKNOWN_MEMBER_SK).select(
        F.col("member_id").alias("_dim_member_id"),
        F.col("valid_from").alias("_dim_valid_from"),
        F.col("valid_to").alias("_dim_valid_to"),
        F.col("member_sk").alias("_dim_member_sk"),
    )
    d = fact_df[date_col]
    cond = (
        (fact_df["member_id"] == dim["_dim_member_id"])
        & (d >= dim["_dim_valid_from"])
        & (d < dim["_dim_valid_to"])
    )
    return (
        fact_df.join(dim, cond, "left")
        .withColumn(
            "member_sk",
            F.coalesce(
                F.col("_dim_member_sk"), F.lit(UNKNOWN_MEMBER_SK).cast("bigint")
            ),
        )
        .drop("_dim_member_id", "_dim_valid_from", "_dim_valid_to", "_dim_member_sk")
    )
