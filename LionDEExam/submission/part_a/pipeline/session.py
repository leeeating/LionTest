"""SparkSession 共用設定。

所有管線步驟與測試都從 build_spark 取得 session，確保：
- 啟用 Delta（configure_spark_with_delta_pip 會把對應版本的 delta jar 加進 classpath）。
- spark.sql.session.timeZone 固定 Asia/Taipei：沒有時區標記的時間字串一律解讀成台北時間，
  「下單日」等日期切分也以台北時間為準，不受執行機器的時區影響。
- 關掉 CSV parser 的 column pruning，讓 count() 與 collect() 對壞列的判斷一致。
- local 模式＋少量 shuffle partitions：資料量約十萬列，預設 200 個 partition 只會增加排程開銷。
"""

from __future__ import annotations

from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession

SESSION_TIMEZONE = "Asia/Taipei"


def build_spark(
    app_name: str = "liontest-part-a",
    master: str = "local[*]",
    shuffle_partitions: int = 4,
) -> SparkSession:
    builder = (
        SparkSession.builder.appName(app_name)
        .master(master)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.session.timeZone", SESSION_TIMEZONE)
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        # 關掉 CSV parser 的 column pruning：開著時，只需要部分欄位的查詢（例如 count()）
        # 不會檢查每列的欄位數，_source_error 不會被填值，欄位數不符的列會被算成 valid，
        # 筆數守恆「輸入＝valid＋rejected」就失真。本機資料量小，關掉的效能代價可忽略。
        .config("spark.sql.csv.parser.columnPruning.enabled", "false")
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
