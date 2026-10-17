# syntax=docker/dockerfile:1
# Part A 執行環境：Python 3.12 + Java 17 + PySpark + Delta（相依版本以 uv.lock 為準）
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
# 不留 uv 下載快取（否則 image 多約 2GB）
ENV UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

# 先只裝相依套件，原始碼變動時這層可以重用快取
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 建置時先下載 Delta 的 jar，執行時不需要連網
RUN python - <<'EOF'
from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession
builder = (SparkSession.builder.master("local[1]")
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"))
spark = configure_spark_with_delta_pip(builder).getOrCreate()
spark.range(1).write.format("delta").save("/tmp/delta_warmup")
spark.stop()
EOF

COPY LionDEExam ./LionDEExam

# Part A 管線完成後，改成跑完整條管線的那一條指令
CMD ["bash"]
