"""Delta 寫入共用函式。"""

from __future__ import annotations

import re
from collections.abc import Mapping
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


# Delta 把 CHECK 約束存在表屬性 delta.constraints.<小寫名稱>
_CONSTRAINT_PROPERTY_PREFIX = "delta.constraints."


def same_constraint_expr(a: str, b: str) -> bool:
    """兩個 CHECK 條件式是否相同。Delta 存的是重新排版過的文字（例如
    `x IN ('a', 'b')` 存成 `x IN ( 'a' , 'b' )`），所以去掉空白再比。"""
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


def table_check_constraints(spark: SparkSession, path: str | Path) -> dict[str, str]:
    """path 這張 Delta 表目前的 CHECK 約束：{名稱（小寫）: 條件式}。"""
    props = DeltaTable.forPath(spark, str(path)).detail().first()["properties"]
    return {
        k[len(_CONSTRAINT_PROPERTY_PREFIX) :]: v
        for k, v in (props or {}).items()
        if k.startswith(_CONSTRAINT_PROPERTY_PREFIX)
    }


def ensure_check_constraints(
    spark: SparkSession, path: str | Path, constraints: Mapping[str, str]
) -> None:
    """讓 path 這張 Delta 表恰好帶有 constraints 裡的 CHECK 約束（名稱 → 條件式）。

    - 缺的就 ALTER TABLE ADD CONSTRAINT；已存在且條件相同（same_constraint_expr）就不動，
      所以重跑冪等（ADD 同名約束會報錯，不能每次都加）。
    - 同名但條件不同（程式改了規則）：先 DROP 再 ADD，以程式為準。DROP 之前先查既有資料
      符不符合新條件（條件為 NULL 也算不符合），有不符合的列就丟 ValueError、不 DROP：
      否則 DROP 成功、ADD 因既有資料違規而失敗時，表會留在「沒有這條約束」的狀態。
      檢查和 DROP、ADD 不是同一個交易，檢查之後才寫進來的資料仍可能讓 ADD 失敗。
    - 不在 constraints 裡的約束不動（可能是別人手動加的）。
    """
    current = table_check_constraints(spark, path)
    table = f"delta.`{path}`"
    for name, expr in constraints.items():
        key = name.lower()
        if key in current and same_constraint_expr(current[key], expr):
            continue
        if key in current:
            bad = (
                spark.read.format("delta")
                .load(str(path))
                .filter(f"NOT coalesce(({expr}), false)")
                .limit(1)
                .count()
            )
            if bad:
                raise ValueError(
                    f"{path} 有資料不符合約束 {name} 的新條件（{expr}），"
                    f"不替換既有約束（{current[key]}）"
                )
            spark.sql(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        spark.sql(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr})")


def merge_upsert(
    spark: SparkSession,
    df: DataFrame,
    path: str | Path,
    keys: list[str],
    *,
    update_condition: str | None = None,
    commit_marker: str | None = None,
    check_constraints: Mapping[str, str] | None = None,
) -> None:
    """以 keys MERGE 進 path 的 Delta 表（Type 1 覆寫）；表不存在就直接建立。

    - update_condition：命中既有列時，只有條件成立才覆寫（例如 fact_order 的
      "s.updated_at > t.updated_at"，舊事件不會蓋掉新狀態）。None 表示一律覆寫。
      目標表用別名 t、來源用 s。
    - commit_marker：寫進這次 commit 的 userMetadata（Delta history 查得到），
      fact_order 用它在 Delta history 標出哪一批寫了哪個版本（稽核用）。
      來源是空的 MERGE 不會產生 commit，也就沒有標記。
    - check_constraints：Delta CHECK 約束（名稱 → 條件式）。表不存在時先建一張空表、
      加上約束，再寫入資料，所以第一筆資料就受約束檢查；表已存在時補上缺的約束
      （ensure_check_constraints）。違反約束時整個 MERGE 失敗，什麼都不寫。

    同一份輸入重跑：每列都命中既有列並以相同值更新，筆數與內容不變（冪等）。
    注意：重跑時既有列仍會被「重寫」，Delta history 的 operationMetrics 會顯示
    numTargetRowsUpdated 等於筆數，這只代表列被重寫，不代表內容改變；
    要判斷內容是否改變，請比對表內容或 checksum。
    """
    path = str(path)
    with _commit_metadata(spark, commit_marker):
        exists = DeltaTable.isDeltaTable(spark, path)
        if not exists and not check_constraints:
            df.write.format("delta").save(path)
            return
        if not exists:
            # 建表時就帶約束：先建空表（同 schema）、加約束，再走下面的 MERGE
            df.limit(0).write.format("delta").save(path)
        if check_constraints:
            ensure_check_constraints(spark, path, check_constraints)
        cond = " AND ".join(f"t.{k} = s.{k}" for k in keys)
        (
            DeltaTable.forPath(spark, path)
            .alias("t")
            .merge(df.alias("s"), cond)
            .whenMatchedUpdateAll(condition=update_condition)
            .whenNotMatchedInsertAll()
            .execute()
        )
