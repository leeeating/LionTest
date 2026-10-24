"""冪等證明：同一批跑兩次、以及中途當掉後重跑，結果都和只跑一次相同。

    uv run python LionDEExam/submission/part_a/profiling/idempotency_proof.py [--out 目錄]

做兩個實驗，最後印出 Markdown 表格（貼進 part_a/README.md「冪等證明」）：

1. 強制重跑：倉儲 A 依序跑 base → day1 → day2 → day3，記下結果；接著把 day1、day2、day3
   各用 force=True 再跑一次（實際執行，不被批次紀錄跳過），每次都和第一次的結果比。
2. 中途當掉：倉儲 B 跑 base → day2 後處理 day3，連續當掉兩次再完成：
   第一次在「隔離表已寫、MERGE fact 之前」當掉，第二次在「MERGE fact 之後、
   寫批次紀錄之前」當掉，第三次正常完成；每個時點都和倉儲 A（沒當掉）比。

比對的內容（不看 Delta operationMetrics：MERGE 重寫同值也會算 updated）：
fact 筆數、amount_twd 與 net_amount_twd 總和、以下各表的整表內容 hash：fact、隔離表、
金額人工確認清單（amount_review）、dim_member、dim_product、dim_date；
以及該批的對帳數字（BatchCounts，不含完成時間與寫入當下的整表數字 fact_table_*）。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import fact_order
from pipeline.batch_log import BatchCounts, completed_batch, run_once
from pipeline.fact_order import (
    INCREMENTAL_AS_OF,
    WarehousePaths,
    incremental_batch_id,
    load_incremental,
    run_all,
    run_batch,
)
from pipeline.session import build_spark
from pipeline.sources import DEFAULT_DATASET_DIR, CsvSource
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F


@dataclass(frozen=True)
class Snapshot:
    fact_rows: int
    amount_twd_sum: str
    net_amount_twd_sum: str
    fact_hash: str
    quarantine_rows: int
    quarantine_hash: str
    review_hash: str
    dims_hash: str  # dim_member、dim_product、dim_date 各自 hash 前 8 碼，以 / 串接

    def cells(self, short) -> str:
        return (
            f"{self.fact_rows:,} | {self.amount_twd_sum} | {self.net_amount_twd_sum} | "
            f"{short(self.fact_hash)} | {self.quarantine_rows:,} | "
            f"{short(self.quarantine_hash)} | {short(self.review_hash)} | {self.dims_hash}"
        )


HEADER = (
    "| 時點 | fact 筆數 | amount_twd 總和 | net_amount_twd 總和 | fact hash | 隔離表筆數 "
    "| 隔離表 hash | 金額人工確認清單 hash | 維度表 hash（member/product/date） | {last} |"
)
RULE = "|---|---|---|---|---|---|---|---|---|---|"


def table_hash(df: DataFrame) -> str:
    """整表內容的 sha256：每列轉成 JSON（欄位依名稱排序）取 sha256，排序後再整體 sha256。

    與列的順序、檔案切法無關；任何一列任何一欄不同，hash 就不同。
    """
    cols = sorted(df.columns)
    rows = df.select(F.sha2(F.to_json(F.struct(*cols)), 256).alias("h")).collect()
    h = hashlib.sha256()
    for r in sorted(r.h for r in rows):
        h.update(r.encode())
    return h.hexdigest()


def snapshot(spark: SparkSession, paths: WarehousePaths) -> Snapshot:
    def load(p):
        return spark.read.format("delta").load(str(p))

    fact, q = load(paths.fact_order), load(paths.quarantine)
    sums = fact.agg(F.sum("amount_twd"), F.sum("net_amount_twd")).first()
    dims = "/".join(
        table_hash(load(p))[:8]
        for p in (paths.dim_member, paths.dim_product, paths.dim_date)
    )
    return Snapshot(
        fact_rows=fact.count(),
        amount_twd_sum=str(sums[0]),
        net_amount_twd_sum=str(sums[1]),
        fact_hash=table_hash(fact),
        quarantine_rows=q.count(),
        quarantine_hash=table_hash(q),
        review_hash=table_hash(load(paths.amount_review)),
        dims_hash=dims,
    )


def batch_scoped(c: BatchCounts) -> BatchCounts:
    """只留「這批本身」的數字。fact_table_* 是寫入當下的整表數字：
    在 day3 之後重跑 day1，整表本來就比第一次跑 day1 時大，不能拿來比。"""
    return replace(
        c,
        fact_table_rows=0,
        fact_table_amount_twd_sum=0,
        fact_table_net_amount_twd_sum=0,
    )


def counts(spark, paths, batch_id) -> BatchCounts:
    return batch_scoped(completed_batch(spark, paths.batch_log, batch_id).counts)


class SimulatedCrash(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="倉儲輸出目錄（預設暫存目錄）")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATASET_DIR))
    args = parser.parse_args()
    root = Path(args.out or tempfile.mkdtemp(prefix="idempotency_"))

    spark = build_spark(app_name="idempotency-proof")
    spark.sparkContext.setLogLevel("ERROR")
    source = CsvSource(spark, args.data_dir)
    lines: list[str] = []
    ok = True

    def short(h: str) -> str:
        return h[:12]

    # ---- 實驗 1：強制重跑
    a = WarehousePaths(root / "A")
    run_all(spark, source, a)
    first = snapshot(spark, a)
    first_counts = {d: counts(spark, a, incremental_batch_id(d)) for d in (1, 2, 3)}
    lines += [
        "**實驗 1：每個增量檔強制重跑一次（force=True，實際執行）**",
        "",
        HEADER.format(last="該批對帳數字與第一次相同"),
        RULE,
        f"| 第一次跑完 base→day3 | {first.cells(short)} | — |",
    ]
    for d in (1, 2, 3):
        run = run_batch(spark, source, a, d, force=True)
        assert run.skipped is False
        snap = snapshot(spark, a)
        same_counts = batch_scoped(run.record.counts) == first_counts[d]
        ok &= snap == first and same_counts
        lines.append(
            f"| 重跑 {incremental_batch_id(d)} 之後 | {snap.cells(short)} | "
            f"{'是' if same_counts else '否'} |"
        )
    lines.append("")

    # ---- 實驗 2：day3 先在 MERGE 前當掉、再在 MERGE 後當掉，第三次完成
    b = WarehousePaths(root / "B")
    for day in (None, 1, 2):
        run_batch(spark, source, b, day)
    before = snapshot(spark, b)
    real_merge = fact_order.merge_upsert

    def merge_then_maybe_crash(spark_, df, path, keys, **kw):
        if Path(path) == b.fact_order:
            raise SimulatedCrash("模擬：隔離表已寫、MERGE fact 之前當掉")
        return real_merge(spark_, df, path, keys, **kw)

    def crash_after_merge():
        load_incremental(spark, source, 3, b)  # fact、隔離表都已寫入
        raise SimulatedCrash("模擬：MERGE 之後、寫批次紀錄之前當掉")

    def run_day3(run):
        try:
            run_once(
                spark,
                b.batch_log,
                batch_id="day3",
                as_of=INCREMENTAL_AS_OF[3],
                source_checksum=source.orders_checksum(3),
                reference_checksums=source.reference_checksums(),
                force_log_path=b.batch_force_log,
                run=run,
            )
        except SimulatedCrash:
            pass

    fact_order.merge_upsert = merge_then_maybe_crash
    try:
        run_day3(lambda: load_incremental(spark, source, 3, b))
    finally:
        fact_order.merge_upsert = real_merge
    crash1 = snapshot(spark, b)
    no_record1 = completed_batch(spark, b.batch_log, "day3") is None
    fact_untouched = (crash1.fact_rows, crash1.fact_hash) == (
        before.fact_rows,
        before.fact_hash,
    )
    run_day3(crash_after_merge)
    crash2 = snapshot(spark, b)
    no_record2 = completed_batch(spark, b.batch_log, "day3") is None
    rerun = run_batch(spark, source, b, 3)
    after = snapshot(spark, b)
    same_counts = batch_scoped(rerun.record.counts) == first_counts[3]
    ok &= (
        no_record1
        and no_record2
        and fact_untouched
        and rerun.skipped is False
        and after == first
        and same_counts
    )
    lines += [
        "**實驗 2：day3 在 MERGE 前當掉、重跑又在 MERGE 後當掉，第三次完成**",
        "",
        HEADER.format(last="day3 對帳數字與沒當掉時相同"),
        RULE,
        f"| 當掉前（base→day2 跑完） | {before.cells(short)} | — |",
        (
            f"| 第一次：MERGE 前當掉（批次紀錄：{'無' if no_record1 else '有'}；"
            f"fact {'未變' if fact_untouched else '已變'}） | {crash1.cells(short)} | — |"
        ),
        (
            f"| 第二次：MERGE 後當掉（批次紀錄：{'無' if no_record2 else '有'}） | "
            f"{crash2.cells(short)} | — |"
        ),
        f"| 第三次：重跑完成 | {after.cells(short)} | {'是' if same_counts else '否'} |",
        f"| 對照：倉儲 A 沒當掉 | {first.cells(short)} | — |",
        "",
        f"結論：{'全部相同' if ok else '有不同，見上表'}（hash 只顯示前 12 碼，維度表前 8 碼）",
    ]
    print("\n".join(lines))
    spark.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
