"""Delta 寫入共用函式。"""

from __future__ import annotations

from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession


def merge_upsert(
    spark: SparkSession, df: DataFrame, path: str | Path, keys: list[str]
) -> None:
    """以 keys MERGE 進 path 的 Delta 表（Type 1 覆寫）；表不存在就直接建立。

    同一份輸入重跑：每列都命中既有列並以相同值更新，筆數與內容不變（冪等）。
    注意：重跑時既有列仍會被「重寫」，Delta history 的 operationMetrics 會顯示
    numTargetRowsUpdated 等於筆數，這只代表列被重寫，不代表內容改變；
    要判斷內容是否改變，請比對表內容或 checksum。
    """
    path = str(path)
    if not DeltaTable.isDeltaTable(spark, path):
        df.write.format("delta").save(path)
        return
    cond = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    (
        DeltaTable.forPath(spark, path)
        .alias("t")
        .merge(df.alias("s"), cond)
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .execute()
    )
