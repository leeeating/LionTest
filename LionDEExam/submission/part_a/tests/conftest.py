"""Part A 測試共用 fixture。

- Spark session 整個測試只建一次（session scope），啟動 JVM 很慢。
- Delta 輸出一律寫到 pytest 的 tmp_path，不寫進 repo。
"""

from __future__ import annotations

import pytest
from pipeline.session import build_spark
from pipeline.sources import DEFAULT_DATASET_DIR, CsvSource


@pytest.fixture(scope="session")
def spark():
    session = build_spark(app_name="liontest-part-a-tests")
    yield session
    session.stop()


@pytest.fixture(scope="session")
def source(spark):
    return CsvSource(spark, DEFAULT_DATASET_DIR)
