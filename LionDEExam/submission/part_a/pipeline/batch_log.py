"""批次紀錄：一張 Delta 表，每批處理完成時「最後」寫一列。

用途（process-log「中途停止：冪等步驟＋批次紀錄」、T6）：
- 有紀錄＝這批的 fact、隔離表都已寫完。重跑時有紀錄就跳過，回傳既有紀錄；
  所以「重跑時所有事件都變成晚到事件、分類跟第一次不同」不會發生。
- 中途當掉（紀錄還沒寫）：重跑整批。fact 的 MERGE 只在 updated_at 較新時覆寫、
  隔離表依 batch_id replaceWhere，狀態機比對的是「這批開始之前」的 fact 版本
  （第一次開始時記在 batch_start，見 pin_fact_version），所以重跑結果相同。
- 強制重跑（force=True）：已完成也照跑一次，覆寫完成紀錄；冪等證明用。
  force 不比對來源 checksum：來源被改過時，強制重跑會用新內容覆寫這批的結果。
- 強制依序：前一批沒完成就拒絕跑下一批（BatchOrderError）。原因：dim_member 用
  last_seen_extract_date 擋重送，判斷以會員為單位；舊快照晚於新快照處理時，
  兩批都出現的會員，舊快照那一版會被跳過，中間那段歷史遺失。
- 來源檔被改過：已完成的批次，checksum 和紀錄不同時丟 SourceChangedError，
  不默默跳過（跳過會讓倉儲和來源不一致，而且沒人知道）。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from decimal import Decimal
from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    LongType,
    MapType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# 批次的處理順序：base → day1 → day2 → day3
BATCH_ORDER: tuple[str, ...] = ("base", "day1", "day2", "day3")

_CHECKSUM_TYPE = DecimalType(38, 2)

BATCH_LOG_SCHEMA = StructType(
    [
        StructField("batch_id", StringType(), False),
        StructField("as_of", DateType(), False),
        StructField("completed_at", TimestampType(), False),
        StructField("source_sha256", StringType(), False),
        StructField("input_rows", LongType(), False),
        StructField("fact_rows", LongType(), False),
        StructField("skipped_rows", LongType(), False),
        StructField("quarantined_rows", LongType(), False),
        StructField(
            "quarantined_by_category", MapType(StringType(), LongType()), False
        ),
        StructField("skipped_intermediate_rows", LongType(), False),
        StructField("coupon_nulled_rows", LongType(), False),
        StructField("amount_review_rows", LongType(), False),
        StructField("amount_twd_sum", _CHECKSUM_TYPE, False),
        StructField("net_amount_twd_sum", _CHECKSUM_TYPE, False),
        StructField("unknown_product_rows", LongType(), False),
        StructField("unknown_member_rows", LongType(), False),
        StructField("fact_table_rows", LongType(), False),
        StructField("fact_table_amount_twd_sum", _CHECKSUM_TYPE, False),
        StructField("fact_table_net_amount_twd_sum", _CHECKSUM_TYPE, False),
        StructField("member_rejected_rows", LongType(), False),
    ]
)


class BatchOrderError(RuntimeError):
    """前一批還沒完成，拒絕處理這一批。"""


class SourceChangedError(RuntimeError):
    """已完成的批次，來源檔的 checksum 和紀錄不同：來源檔被改過。"""


@dataclass(frozen=True)
class BatchCounts:
    """一批的對帳數字。input_rows＝fact_rows＋quarantined_rows＋skipped_rows。

    - fact_rows、amount_twd_sum、unknown_*_rows：這批寫進（MERGE 進）fact 的列；
      unknown_* 是 product_sk、member_sk 落到 -1 的筆數。
    - quarantined_rows、quarantined_by_category：需要人看的隔離列（依 reject_category）。
    - skipped_rows：略過的列（late_event：晚到但走得到 fact 現況）。這些列也存在隔離表，
      但不是錯誤，所以和 quarantined 分開計數。
    - skipped_intermediate_rows：寫進 fact 的列中，相對於前一個觀察到的狀態
      跳過中間狀態的筆數（例如 created → completed），只記錄、不隔離。
    - coupon_nulled_rows：寫進 fact 的列中，coupon_discount＝-1.0 轉成 NULL 的筆數（V3）。
    - amount_review_rows：寫進 fact 的列中，列進 V2 人工確認清單（amount_review）的筆數。
    - net_amount_twd_sum：這批寫進 fact 的折扣後金額總和（coupon 為 NULL 的列不計）。
    - fact_table_*：寫入後整張 fact 的列數與 checksum。
    - member_rejected_rows：dim_member 這次的違規列數（會員快照，不在訂單對帳內）。
    """

    input_rows: int
    fact_rows: int
    quarantined_rows: int
    skipped_rows: int
    quarantined_by_category: dict[str, int] = field(hash=False)
    skipped_intermediate_rows: int
    coupon_nulled_rows: int
    amount_review_rows: int
    amount_twd_sum: Decimal
    net_amount_twd_sum: Decimal
    unknown_product_rows: int
    unknown_member_rows: int
    fact_table_rows: int
    fact_table_amount_twd_sum: Decimal
    fact_table_net_amount_twd_sum: Decimal
    member_rejected_rows: int

    @property
    def balanced(self) -> bool:
        return self.input_rows == (
            self.fact_rows + self.quarantined_rows + self.skipped_rows
        )

    def counts(self) -> BatchCounts:
        """只取 BatchCounts 的欄位（子類別多帶的欄位，例如 batch_id，不要）。"""
        return BatchCounts(
            **{f.name: getattr(self, f.name) for f in fields(BatchCounts)}
        )


@dataclass(frozen=True)
class BatchRecord:
    batch_id: str
    as_of: dt.date
    completed_at: dt.datetime
    source_sha256: str
    counts: BatchCounts


@dataclass(frozen=True)
class BatchRun:
    """run_once 的結果：skipped=True 表示這批先前已完成，record 是既有紀錄。"""

    record: BatchRecord
    skipped: bool


def _check_batch_id(batch_id: str, order: Sequence[str]) -> int:
    if batch_id not in order:
        raise ValueError(f"未知的批次 {batch_id!r}，可用：{tuple(order)}")
    return list(order).index(batch_id)


def completed_batch(
    spark: SparkSession, log_path: str | Path, batch_id: str
) -> BatchRecord | None:
    """這批的完成紀錄；沒有完成（或紀錄表還不存在）時回傳 None。"""
    log_path = str(log_path)
    if not DeltaTable.isDeltaTable(spark, log_path):
        return None
    rows = (
        spark.read.format("delta")
        .load(log_path)
        .filter(F.col("batch_id") == batch_id)
        .collect()
    )
    if not rows:
        return None
    if len(rows) > 1:  # record_completed 用 MERGE 寫，正常不會發生
        raise RuntimeError(f"批次紀錄中 {batch_id!r} 有 {len(rows)} 列")
    r = rows[0]
    return BatchRecord(
        batch_id=r.batch_id,
        as_of=r.as_of,
        completed_at=r.completed_at,
        source_sha256=r.source_sha256,
        counts=BatchCounts(
            **{
                f.name: (
                    dict(r[f.name])
                    if f.name == "quarantined_by_category"
                    else r[f.name]
                )
                for f in fields(BatchCounts)
            }
        ),
    )


def require_previous_completed(
    spark: SparkSession,
    log_path: str | Path,
    batch_id: str,
    order: Sequence[str] = BATCH_ORDER,
) -> None:
    """前面每一批都要已完成，否則丟 BatchOrderError。"""
    idx = _check_batch_id(batch_id, order)
    for prev in order[:idx]:
        if completed_batch(spark, log_path, prev) is None:
            raise BatchOrderError(
                f"批次 {batch_id!r} 之前的 {prev!r} 尚未完成，拒絕執行；"
                f"批次必須依序處理：{' → '.join(order)}"
            )


def record_completed(
    spark: SparkSession,
    log_path: str | Path,
    record: BatchRecord,
    *,
    replace: bool = False,
) -> None:
    """寫入完成紀錄（以 batch_id MERGE）；這是一批的最後一步。

    replace=False 時只插入、不覆寫既有紀錄；強制重跑（replace=True）時覆寫。
    """
    c = record.counts
    if not c.balanced:
        raise ValueError(
            f"批次 {record.batch_id!r} 對帳不平：輸入 {c.input_rows} ≠ "
            f"fact {c.fact_rows} ＋ 隔離 {c.quarantined_rows} ＋ 略過 {c.skipped_rows}"
        )
    values = {
        "batch_id": record.batch_id,
        "as_of": record.as_of,
        "completed_at": record.completed_at,
        "source_sha256": record.source_sha256,
        **{f.name: getattr(c, f.name) for f in fields(BatchCounts)},
    }
    values["quarantined_by_category"] = dict(c.quarantined_by_category)
    row = tuple(values[f.name] for f in BATCH_LOG_SCHEMA.fields)
    df = spark.createDataFrame([row], BATCH_LOG_SCHEMA)
    log_path = str(log_path)
    if not DeltaTable.isDeltaTable(spark, log_path):
        df.write.format("delta").save(log_path)
        return
    merge = (
        DeltaTable.forPath(spark, log_path)
        .alias("t")
        .merge(df.alias("s"), "t.batch_id = s.batch_id")
    )
    if replace:
        merge = merge.whenMatchedUpdateAll()
    merge.whenNotMatchedInsertAll().execute()


def run_once(
    spark: SparkSession,
    log_path: str | Path,
    *,
    batch_id: str,
    as_of: dt.date,
    source_checksum: str,
    run: Callable[[], BatchCounts],
    order: Sequence[str] = BATCH_ORDER,
    force: bool = False,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> BatchRun:
    """一批最多處理一次。

    1. 已完成：checksum 相同 → 跳過，回傳既有紀錄；不同 → SourceChangedError。
       force=True 時不跳過也不比對 checksum，照常執行並覆寫紀錄（冪等證明用）。
    2. 前一批沒完成 → BatchOrderError（在呼叫 run 之前，什麼都還沒寫）。
    3. 呼叫 run()（寫維度、fact、隔離表，回傳對帳數字），最後寫完成紀錄。
       run 中途丟例外時不寫紀錄，下次重跑整批。
    """
    _check_batch_id(batch_id, order)
    done = completed_batch(spark, log_path, batch_id)
    if done is not None and not force:
        if done.source_sha256 != source_checksum:
            raise SourceChangedError(
                f"批次 {batch_id!r} 已在 {done.completed_at} 完成，但來源檔 checksum "
                f"從 {done.source_sha256} 變成 {source_checksum}：來源檔被改過，拒絕跳過"
            )
        return BatchRun(record=done, skipped=True)
    require_previous_completed(spark, log_path, batch_id, order)
    counts = run()
    record = BatchRecord(
        batch_id=batch_id,
        as_of=as_of,
        completed_at=now(),
        source_sha256=source_checksum,
        counts=counts.counts(),
    )
    record_completed(spark, log_path, record, replace=force)
    return BatchRun(record=completed_batch(spark, log_path, batch_id), skipped=False)


# ---------------------------------------------------------------- 批次開始前的 fact 版本

BATCH_START_SCHEMA = StructType(
    [
        StructField("batch_id", StringType(), False),
        # 這批第一次開始時 fact 的 Delta 版本；-1 表示當時 fact 還不存在
        StructField("fact_version_before", LongType(), False),
        StructField("started_at", TimestampType(), False),
    ]
)


def pin_fact_version(
    spark: SparkSession,
    start_path: str | Path,
    batch_id: str,
    current_version: int,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> int:
    """這批「開始之前」的 fact 版本：第一次呼叫時記下 current_version，之後都回傳記下的值。

    當掉後重跑、強制重跑時，fact 可能已經有這批的結果；拿記下的版本做 time travel，
    分類才會和第一次相同。寫在任何 fact、隔離表寫入之前，所以當掉也不會漏記。
    不從 Delta history 找 commit 標記，是因為寫進 fact 的列為 0 時 MERGE 不產生 commit。
    """
    start_path = str(start_path)
    if DeltaTable.isDeltaTable(spark, start_path):
        rows = (
            spark.read.format("delta")
            .load(start_path)
            .filter(F.col("batch_id") == batch_id)
            .collect()
        )
        if rows:
            return rows[0]["fact_version_before"]
    df = spark.createDataFrame([(batch_id, current_version, now())], BATCH_START_SCHEMA)
    if not DeltaTable.isDeltaTable(spark, start_path):
        df.write.format("delta").save(start_path)
    else:
        (
            DeltaTable.forPath(spark, start_path)
            .alias("t")
            .merge(df.alias("s"), "t.batch_id = s.batch_id")
            .whenNotMatchedInsertAll()
            .execute()
        )
    return current_version
