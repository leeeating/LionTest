"""一批訂單事件的狀態機分類（純 DataFrame 轉換，不寫 Delta）。

規則（使用者已定案，見 process-log「狀態機檢查採 C」「狀態檢查一律用可達性」
「同一秒內出現不同狀態」「不合法轉移之後的事件一起隔離」）：

狀態值不在 4 種之內的列，合約（contracts.ORDERS_SCHEMA 的允許值）已在 cast_to_contract
擋下，不會進到這裡。萬一繞過合約，這裡的防護是：未知值走不到也走不出任何狀態，
晚到時歸 late_event_conflict，在鏈上歸 illegal_transition（新訂單的第一列也一樣）。

1. 晚到事件：updated_at ≤ 既有 fact 的 updated_at，不進轉移鏈，只做可達性檢查：
   - 這個舊狀態走得到 fact 現況 → late_event，略過（不寫 fact；隔離表留紀錄，對帳算「略過」）
   - 走不到 → late_event_conflict，隔離
2. 比 fact 新的事件（或 fact 沒有這張單）組成轉移鏈：依 updated_at 排序，
   同狀態的連續列合併成一段，逐段用可達性比對；第一段的起點是 fact 現況，
   沒有 fact 時不限（新訂單的第一個狀態從 created 都走得到）。
   - 跳過中間狀態（例如 created → completed）合法，STATE_SKIPPED_COL 標 True，不隔離
   - 往回走（例如 cancelled → paid）→ illegal_transition，隔離
3. 同一 order_id、同一 updated_at、狀態不同 → 這些列全部 ambiguous_order，隔離。
4. 鏈上第一個不合法點（illegal_transition 或 ambiguous_order）之後的事件
   → after_illegal，隔離；fact 停在最後一個合法狀態。
5. 鏈上合法的列：最後一列 accepted（寫進 fact，每張單最多一列），其餘 superseded（隔離）。

每列恰好一個分類（STATE_CATEGORY_COL），各分類互斥，數量相加等於輸入。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from pipeline.categories import QUARANTINE_CATEGORIES, SKIP_CATEGORIES, Category
from pipeline.order_status import is_known_status, reachable, skips_intermediate

STATE_CATEGORY_COL = "state_category"
STATE_REASON_COL = "state_reason"
STATE_SKIPPED_COL = "state_skipped"

_KEY_COLS = ("order_id", "order_status", "updated_at")


class StateCategory(Category):
    """狀態機的分類：沿用 categories.Category（唯一一份），只多一個「寫進 fact」。"""

    ACCEPTED = "accepted"  # 寫進 fact：這張單本批最後一個合法事件


# 每個分類的去向（SKIP、QUARANTINE 也涵蓋 fact_order 其他步驟的分類）
WRITE_CATEGORIES = frozenset({StateCategory.ACCEPTED})
__all__ = [
    "QUARANTINE_CATEGORIES",
    "SKIP_CATEGORIES",
    "WRITE_CATEGORIES",
    "StateCategory",
    "classify_status_events",
    "split_by_disposition",
]

REASON_SUPERSEDED = "同批有較新的狀態更新，保留 updated_at 最新一列"
REASON_AFTER_ILLEGAL = "同一張單在本批較早的事件不合法或無法排序，之後的事件一併隔離"

_FACT_STATUS = "_sm_fact_status"
_FACT_UPDATED_AT = "_sm_fact_updated_at"
_ORDER = "_sm_order"


class StatusSplit(NamedTuple):
    accepted: DataFrame  # 寫進 fact
    quarantined: DataFrame  # 進隔離表
    skipped: DataFrame  # 略過（晚到但合理）


def classify_status_events(
    events: DataFrame,
    fact_state: DataFrame | None,
    *,
    tiebreak: Sequence[str] | None = None,
) -> DataFrame:
    """替每列事件加上 STATE_CATEGORY_COL、STATE_REASON_COL、STATE_SKIPPED_COL。

    - events：這批經過格式、撞號、重送處理後的事件；至少要有 order_id、
      order_status（字串）、updated_at（timestamp）。其他欄位原樣保留。
    - fact_state：既有 fact 的 (order_id, order_status, updated_at)，order_id 唯一；
      第一批沒有 fact 時傳 None。
    - tiebreak：updated_at 相同（且狀態相同）時決定哪一列算「最後」的欄位，
      只為了重跑結果確定。預設用 events 除了三個 key 以外的所有欄位
      （和 fact_order._dedupe 一樣，取排序最大的那列）。
    - STATE_SKIPPED_COL：只有 accepted（寫進 fact）的列可能為 True：這列相對於前一個
      觀察到的狀態跳過了中間狀態。新訂單的第一個狀態沒有前一個觀察，一律 False。
    """
    missing = [c for c in _KEY_COLS if c not in events.columns]
    if missing:
        raise ValueError(f"events 缺少欄位：{missing}")
    if tiebreak is None:
        tiebreak = [c for c in events.columns if c not in _KEY_COLS]
    order_key = F.struct(*[F.col(c) for c in tiebreak]) if tiebreak else F.lit(0)

    status = F.col("order_status")
    upd = F.col("updated_at")

    if fact_state is None:
        df = events.withColumns(
            {
                _FACT_STATUS: F.lit(None).cast("string"),
                _FACT_UPDATED_AT: F.lit(None).cast("timestamp"),
            }
        )
    else:
        f = fact_state.select(
            "order_id",
            F.col("order_status").alias(_FACT_STATUS),
            F.col("updated_at").alias(_FACT_UPDATED_AT),
        )
        df = events.join(f, "order_id", "left")
    fact_status = F.col(_FACT_STATUS)

    known = is_known_status(status)
    late = F.col(_FACT_UPDATED_AT).isNotNull() & (upd <= F.col(_FACT_UPDATED_AT))
    in_chain = ~late
    df = df.withColumns(
        {
            "_sm_late": late,
            "_sm_in_chain": in_chain,
            _ORDER: order_key,
        }
    )

    # ---- 轉移鏈：只在鏈上的列之間開窗（partition 加上 _sm_in_chain，其他列不互相干擾）
    part = ["order_id", "_sm_in_chain"]
    w = Window.partitionBy(*part).orderBy(upd, F.col(_ORDER))
    w_all = Window.partitionBy(*part)
    w_same_ts = Window.partitionBy(*part, "updated_at")

    df = df.withColumns(
        {
            "_sm_lag": F.lag(status).over(w),
            "_sm_ambiguous": F.size(F.collect_set(status).over(w_same_ts)) > 1,
            "_sm_ts_statuses": F.array_join(
                F.array_sort(F.collect_set(status).over(w_same_ts)), ", "
            ),
        }
    )
    # 同狀態連續列合併成一段：狀態和上一列不同時開新段
    new_seg = F.col("_sm_lag").isNull() | (F.col("_sm_lag") != status)
    df = df.withColumn(
        "_sm_seg",
        F.sum(new_seg.cast("int")).over(
            w.rowsBetween(Window.unboundedPreceding, Window.currentRow)
        ),
    )
    # 每段的起點：上一段的狀態；第一段是 fact 現況（新訂單為 NULL）
    seg_prev = F.max(F.when(new_seg, F.col("_sm_lag"))).over(
        Window.partitionBy(*part, "_sm_seg")
    )
    df = df.withColumn("_sm_from", F.coalesce(seg_prev, fact_status))
    from_ = F.col("_sm_from")
    legal = known & (from_.isNull() | reachable(from_, status))
    df = df.withColumns(
        {
            "_sm_legal": legal,
            "_sm_skip": from_.isNotNull() & skips_intermediate(from_, status),
        }
    )
    # 第一個斷點：不合法或無法排序的列中最早的 updated_at
    is_break = F.col("_sm_ambiguous") | ~F.col("_sm_legal")
    df = df.withColumn("_sm_break_ts", F.min(F.when(is_break, upd)).over(w_all))
    brk = F.col("_sm_break_ts")
    before_break = brk.isNull() | (upd < brk)
    # 斷點之前的合法列，依時間由新到舊排，第一列寫進 fact
    df = df.withColumn("_sm_bb", before_break)
    w_desc = Window.partitionBy(*part, "_sm_bb").orderBy(
        upd.desc(), F.col(_ORDER).desc()
    )
    df = df.withColumn("_sm_rank", F.row_number().over(w_desc))

    category = (
        F.when(
            F.col("_sm_late") & reachable(status, fact_status),
            F.lit(StateCategory.LATE_EVENT),
        )
        .when(F.col("_sm_late"), F.lit(StateCategory.LATE_EVENT_CONFLICT))
        .when(upd > brk, F.lit(StateCategory.AFTER_ILLEGAL))
        .when(F.col("_sm_ambiguous"), F.lit(StateCategory.AMBIGUOUS_ORDER))
        .when(~F.col("_sm_legal"), F.lit(StateCategory.ILLEGAL_TRANSITION))
        .when(F.col("_sm_rank") == 1, F.lit(StateCategory.ACCEPTED))
        .otherwise(F.lit(StateCategory.SUPERSEDED))
    )
    cat = F.col(STATE_CATEGORY_COL)
    reason = (
        F.when(
            cat == StateCategory.LATE_EVENT,
            F.concat(
                F.lit("晚到事件：updated_at 不比 fact 新，"),
                status,
                F.lit(" 走得到 fact 現況 "),
                fact_status,
                F.lit("，略過"),
            ),
        )
        .when(
            cat == StateCategory.LATE_EVENT_CONFLICT,
            F.concat(
                F.lit("晚到且矛盾：updated_at 不比 fact 新，但 "),
                status,
                F.lit(" 走不到 fact 現況 "),
                fact_status,
            ),
        )
        .when(cat == StateCategory.AFTER_ILLEGAL, F.lit(REASON_AFTER_ILLEGAL))
        .when(
            cat == StateCategory.AMBIGUOUS_ORDER,
            F.concat(
                F.lit("同一 order_id 同一 updated_at 有多種狀態（"),
                F.col("_sm_ts_statuses"),
                F.lit("），無法排出先後"),
            ),
        )
        .when(
            cat == StateCategory.ILLEGAL_TRANSITION,
            F.concat(
                F.lit("不合法的狀態轉移："),
                F.coalesce(from_, F.lit("（新訂單）")),
                F.lit(" → "),
                F.coalesce(status, F.lit("NULL")),
            ),
        )
        .when(cat == StateCategory.SUPERSEDED, F.lit(REASON_SUPERSEDED))
    )
    # 只標寫進 fact 的列：要統計的是「跳過中間狀態的訂單數」，superseded 的列不寫入
    skipped = (cat == StateCategory.ACCEPTED) & F.col("_sm_skip")
    df = df.withColumn(STATE_CATEGORY_COL, category)
    df = df.withColumns(
        {STATE_REASON_COL: reason, STATE_SKIPPED_COL: F.coalesce(skipped, F.lit(False))}
    )
    return df.select(
        *events.columns, STATE_CATEGORY_COL, STATE_REASON_COL, STATE_SKIPPED_COL
    )


def split_by_disposition(classified: DataFrame) -> StatusSplit:
    """依分類的去向拆成三份：寫進 fact、隔離、略過。"""
    cat = F.col(STATE_CATEGORY_COL)
    return StatusSplit(
        accepted=classified.filter(cat.isin(*WRITE_CATEGORIES)),
        quarantined=classified.filter(cat.isin(*QUARANTINE_CATEGORIES)),
        skipped=classified.filter(cat.isin(*SKIP_CATEGORIES)),
    )
