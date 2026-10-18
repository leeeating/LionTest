"""來源時間字串的格式定義與解析：validation 的格式規則與 dims 的解析共用這一份。"""

from __future__ import annotations

from pyspark.sql import Column
from pyspark.sql import functions as F

# 來源時間字串接受的格式，依序嘗試。只有這些，不多不少：
# - `2026-06-25T14:02:16+08:00`、`2026-06-25T06:02:16Z`：XXX 吃 ±hh:mm 與 Z，照字串裡的時區換算
# - `2026/06/22 04:47:19`：沒有時區標記，依 session timezone（Asia/Taipei）解讀
#   （已定案：無時區標記視為台北時間，見 process-log）
SOURCE_TIMESTAMP_FORMATS = (
    "yyyy-MM-dd'T'HH:mm:ssXXX",
    "yyyy/MM/dd HH:mm:ss",
)

# 合約欄位 metadata 用這個標記要求「必須能被 parse_source_timestamp 解析」
FORMAT_METADATA_KEY = "format"
SOURCE_TIMESTAMP = "source_timestamp"


def parse_source_timestamp(col: Column) -> Column:
    """把來源時間字串解析成 timestamp；不符合 SOURCE_TIMESTAMP_FORMATS 的回傳 NULL。"""
    return F.coalesce(
        *[F.try_to_timestamp(col, F.lit(fmt)) for fmt in SOURCE_TIMESTAMP_FORMATS]
    )
