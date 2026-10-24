"""命令列入口：依序跑完 base → day1 → day2 → day3，印出每批的對帳結果。

    python -m pipeline.run --data-dir <資料目錄> --out <輸出目錄>

參數沒給時讀環境變數 LIONTEST_DATA_DIR、LIONTEST_OUT；都沒有時資料目錄用
repo 內的 candidate_package/dataset，輸出目錄必須指定。
已完成的批次（批次紀錄裡有）會跳過，印出既有紀錄；--force 會強制重跑每一批。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pipeline.batch_log import BatchRun
from pipeline.fact_order import WarehousePaths, run_batch
from pipeline.session import build_spark
from pipeline.sources import DEFAULT_DATASET_DIR, INCREMENTAL_DAYS, CsvSource


def format_run(run: BatchRun) -> str:
    r, c = run.record, run.record.counts
    cats = ", ".join(f"{k}={v}" for k, v in sorted(c.quarantined_by_category.items()))
    status = "已完成過，跳過（以下為既有紀錄）" if run.skipped else "完成"
    return "\n".join(
        [
            f"[{r.batch_id}] as_of={r.as_of} {status}",
            (
                f"  輸入 {c.input_rows:,} ＝ 寫入 {c.fact_rows:,} ＋ 隔離 "
                f"{c.quarantined_rows:,} ＋ 略過 {c.skipped_rows:,}"
                f"（{'平衡' if c.balanced else '不平衡'}）"
            ),
            f"  隔離分類：{cats or '無'}",
            (
                f"  跳過中間狀態 {c.skipped_intermediate_rows:,}；product -1："
                f"{c.unknown_product_rows:,}；member -1：{c.unknown_member_rows:,}"
            ),
            (
                f"  coupon -1.0 轉 NULL {c.coupon_nulled_rows:,}；"
                f"金額人工確認清單 {c.amount_review_rows:,}"
            ),
            (
                f"  本批 amount_twd 總和 {c.amount_twd_sum:,}；"
                f"net_amount_twd 總和 {c.net_amount_twd_sum:,}"
            ),
            (
                f"  fact 全表 {c.fact_table_rows:,} 列，amount_twd 總和 "
                f"{c.fact_table_amount_twd_sum:,}；net_amount_twd 總和 "
                f"{c.fact_table_net_amount_twd_sum:,}"
            ),
            f"  來源 sha256 {r.source_sha256[:16]}…",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Part A 管線：base → day1～3")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("LIONTEST_DATA_DIR", str(DEFAULT_DATASET_DIR)),
        help="來源 CSV 目錄（預設讀環境變數 LIONTEST_DATA_DIR）",
    )
    parser.add_argument(
        "--out",
        default=os.environ.get("LIONTEST_OUT"),
        help="Delta 表輸出目錄（預設讀環境變數 LIONTEST_OUT）",
    )
    parser.add_argument("--force", action="store_true", help="已完成的批次也重跑")
    args = parser.parse_args(argv)
    if not args.out:
        parser.error("請用 --out 或環境變數 LIONTEST_OUT 指定輸出目錄")

    spark = build_spark(app_name="liontest-part-a")
    spark.sparkContext.setLogLevel("ERROR")
    try:
        source = CsvSource(spark, Path(args.data_dir))
        paths = WarehousePaths(args.out)
        print(f"資料目錄 {args.data_dir} → 輸出 {paths.root}")
        for day in (None, *INCREMENTAL_DAYS):
            print(format_run(run_batch(spark, source, paths, day, force=args.force)))
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
