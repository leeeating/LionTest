"""來源讀取介面（ADR-02 選項 A）。

SourceReader 是管線唯一依賴的讀取介面；換源頭（例如營運 SQL DB 經 JDBC）只要新增一個
實作，回傳與 contracts 同欄名的原始字串 DataFrame，下游程式不用改。目前只有 CsvSource。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Protocol, runtime_checkable

from pyspark.errors import AnalysisException
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

from pipeline import contracts

# 預設資料目錄：repo 內的 candidate_package/dataset（由本檔位置推回去，不依賴工作目錄）
DEFAULT_DATASET_DIR = (
    Path(__file__).resolve().parents[2].parent / "candidate_package" / "dataset"
)

INCREMENTAL_DAYS = (1, 2, 3)


class SourceFileError(Exception):
    """檔案層級問題：整批停下，不寫入任何東西（已定案）。

    kind 是 "missing"（檔案不存在）、"header"（表頭與合約不符）、"empty"（沒有資料列）之一。
    """

    def __init__(self, path: str, kind: str, detail: str):
        super().__init__(f"來源檔 {path} 不能使用（{kind}）：{detail}")
        self.path = path
        self.kind = kind


@runtime_checkable
class SourceReader(Protocol):
    """每個來源表一個方法，回傳 contracts.to_raw_schema(該表合約) 的 DataFrame。

    - 所有合約欄位都是原始字串，不做任何清理或轉型；轉型與隔離交給
      validation.cast_to_contract()。
    - 檔案（或資料表）層級的問題在呼叫方法時就丟 SourceFileError。
    """

    def orders_base(self) -> DataFrame: ...

    def orders_incremental(self, day: int) -> DataFrame: ...

    def members(self) -> DataFrame: ...

    def products(self) -> DataFrame: ...

    def fx_rates(self) -> DataFrame: ...


class CsvSource:
    """從 candidate_package 的 CSV 匯出檔讀取。

    - 用合約自動產生的全字串 schema 讀（contracts.to_raw_schema），不 inferSchema，
      所以型別錯的值不會在讀取時被轉成 NULL 或四捨五入，原樣交給 cast_to_contract 判斷。
    - 每次呼叫讀取方法時，先立即檢查三件檔案層級的事，沒過就丟 SourceFileError：
      檔案存在、第一行表頭（去掉 UTF-8 BOM 後）的欄名與順序和合約完全相同、至少有一列資料。
      這些檢查用 spark.read.text(...).take() 立即讀出檔案開頭來比對。
    - 欄位數和表頭不符的列，原文放在 SOURCE_ERROR_COL（PERMISSIVE 模式的
      columnNameOfCorruptRecord），之後由 cast_to_contract 分到 rejected。
      這要靠 build_spark() 關掉 spark.sql.csv.parser.columnPruning.enabled：開著時
      count() 這類只需部分欄位的查詢不檢查欄位數，壞列會被算成 valid。
    """

    def __init__(
        self, spark: SparkSession, dataset_dir: str | Path = DEFAULT_DATASET_DIR
    ):
        self._spark = spark
        self._dir = Path(dataset_dir)

    def _check_file(self, path: str, schema: StructType) -> None:
        try:
            lines = self._spark.read.text(path).filter(F.trim("value") != "")
        except AnalysisException as e:
            if "PATH_NOT_FOUND" in str(e):
                raise SourceFileError(path, "missing", "檔案不存在") from e
            raise
        head = [r.value for r in lines.take(2)]
        if not head:
            raise SourceFileError(path, "empty", "檔案是空的，連表頭都沒有")
        header = next(csv.reader([head[0].lstrip("\ufeff")]))
        expected = schema.fieldNames()
        if header != expected:
            raise SourceFileError(
                path, "header", f"表頭 {header} 與合約 {expected} 不符"
            )
        if len(head) < 2:
            raise SourceFileError(path, "empty", "只有表頭，沒有資料列")

    def _read(self, filename: str, schema: StructType) -> DataFrame:
        path = str(self._dir / filename)
        self._check_file(path, schema)
        return (
            self._spark.read.format("csv")
            .option("header", True)
            .option("encoding", "UTF-8")
            .option("mode", "PERMISSIVE")
            .option("columnNameOfCorruptRecord", contracts.SOURCE_ERROR_COL)
            .schema(contracts.to_raw_schema(schema))
            .load(path)
        )

    def orders_base(self) -> DataFrame:
        return self._read("orders_base.csv", contracts.ORDERS_SCHEMA)

    def orders_incremental(self, day: int) -> DataFrame:
        if day not in INCREMENTAL_DAYS:
            raise ValueError(f"沒有第 {day} 天的增量檔，可用：{INCREMENTAL_DAYS}")
        return self._read(f"orders_incremental_day{day}.csv", contracts.ORDERS_SCHEMA)

    def members(self) -> DataFrame:
        return self._read("members.csv", contracts.MEMBERS_SCHEMA)

    def products(self) -> DataFrame:
        return self._read("products.csv", contracts.PRODUCTS_SCHEMA)

    def fx_rates(self) -> DataFrame:
        return self._read("fx_rates.csv", contracts.FX_RATES_SCHEMA)
