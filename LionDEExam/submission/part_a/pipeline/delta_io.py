"""Delta 寫入共用函式。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession

_USER_METADATA_CONF = "spark.databricks.delta.commitInfo.userMetadata"


@contextmanager
def _commit_metadata(spark: SparkSession, marker: str | None):
    """這段期間的 Delta commit 都帶上 userMetadata＝marker（寫進 table history）。"""
    if marker is None:
        yield
        return
    spark.conf.set(_USER_METADATA_CONF, marker)
    try:
        yield
    finally:
        spark.conf.unset(_USER_METADATA_CONF)


def merge_upsert(
    spark: SparkSession,
    df: DataFrame,
    path: str | Path,
    keys: list[str],
    *,
    update_condition: str | None = None,
    commit_marker: str | None = None,
) -> None:
    """以 keys MERGE 進 path 的 Delta 表（Type 1 覆寫）；表不存在就直接建立。

    - update_condition：命中既有列時，只有條件成立才覆寫（例如 fact_order 的
      "s.updated_at > t.updated_at"，舊事件不會蓋掉新狀態）。None 表示一律覆寫。
      目標表用別名 t、來源用 s。
    - commit_marker：寫進這次 commit 的 userMetadata（Delta history 查得到），
      fact_order 用它在 Delta history 標出哪一批寫了哪個版本（稽核用）。
      來源是空的 MERGE 不會產生 commit，也就沒有標記。

    同一份輸入重跑：每列都命中既有列並以相同值更新，筆數與內容不變（冪等）。
    注意：重跑時既有列仍會被「重寫」，Delta history 的 operationMetrics 會顯示
    numTargetRowsUpdated 等於筆數，這只代表列被重寫，不代表內容改變；
    要判斷內容是否改變，請比對表內容或 checksum。
    """
    path = str(path)
    with _commit_metadata(spark, commit_marker):
        if not DeltaTable.isDeltaTable(spark, path):
            df.write.format("delta").save(path)
            return
        cond = " AND ".join(f"t.{k} = s.{k}" for k in keys)
        (
            DeltaTable.forPath(spark, path)
            .alias("t")
            .merge(df.alias("s"), cond)
            .whenMatchedUpdateAll(condition=update_condition)
            .whenNotMatchedInsertAll()
            .execute()
        )
