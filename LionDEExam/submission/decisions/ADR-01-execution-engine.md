# ADR-01｜Part A 執行引擎：PySpark＋Delta
- 狀態：草稿
- Part：A
- 關聯：Part A 執行引擎選 PySpark＋Delta

## 背景
Part A 要從 CSV 建出星型模型（`fact_order`、`dim_member` SCD2、`dim_product`、`dim_date`），依序處理三個每日增量檔，而且管線必須冪等。讀檔、去重、upsert、SCD2、A-3 檢核查詢，全部要寫在同一個引擎上，所以這是 Part A 第一個要定的決策，做到一半再換引擎等於重寫。

題目的限制與情境：
- 「環境需求」：「任何熟悉的本地環境即可：**pandas / PySpark / DuckDB / SQL（任一）**，不需要雲端帳號。」引擎不限。
- Part C：「公司決定將平台建置於 **Microsoft Fabric**」。Fabric Lakehouse 的運算引擎是 Spark，表格格式是 Delta。
- Part B 的 `buggy_pipeline.py` 是 PySpark，「假設在 Fabric Lakehouse 環境運行」。
- `candidate_package/README.md`「提醒」：「你的繳交物需附說明文件（README；Word 或 Markdown 皆可），讓閱卷者能在 30 分鐘內重現結果。」

題目資料量（`wc -l candidate_package/dataset/*`，含標題列）。這是 demo 資料，不代表 prod 的資料量：

```
     135 candidate_package/dataset/fx_rates.csv
    8992 candidate_package/dataset/members.csv
  100041 candidate_package/dataset/orders_base.csv
    4616 candidate_package/dataset/orders_incremental_day1.csv
    4701 candidate_package/dataset/orders_incremental_day2.csv
    4616 candidate_package/dataset/orders_incremental_day3.csv
     301 candidate_package/dataset/products.csv
  123402 total
```

雄獅公開的營運規模（研究 agent 查證，主對話未逐一打開來源核對）：

| 項目 | 數值 | 年度 | 來源 |
|---|---|---|---|
| 參團人次 | 963,794（出境 625,546＋國旅 338,248）；2023 年 918,729 | 2024 | 113 年度年報「最近二年度銷售量值表」，[年報 PDF](https://static.liontravel.com/ConsoleAPData/PublicationStatic/Investors/liontravel/c297f17c9e8042f68672679aa1a67f1c.pdf)（年度由內文推定） |
| 合併營收 | 28,326,933 仟元 | 2024 | 同上，致股東報告書 |
| 合併營收 | 300.28 億元 | 2025 | [自由時報](https://ec.ltn.com.tw/article/breakingnews/5304917) |
| 數據相關計畫 | 「數據治理、數據中台建置」 | 2025 營業計畫 | 年報致股東報告書；未提及任何雲端廠商名稱 |

這些數字的限制：參團人次不等於訂單筆數（一張訂單可能有多位旅客）；團體旅遊以外的票務、訂房等業務沒有人次數字；會員數、線上訂單占比沒查到。

本機環境：`pyproject.toml` 已列 `delta-spark>=4.4.1`、`duckdb>=1.5.6`、`pandas<3`、`pyspark>=4.2.0`；`java -version` 為 21.0.4。

## 選項
| 選項 | 好處 | 代價 |
|---|---|---|
| A. DuckDB（SQL 為主，Python 串流程） | 只要 Python 套件就能跑，不需要 Java；單機處理 demo 的約 11 萬列訂單很快；支援 `MERGE`、`QUALIFY`，A-3 的檢核查詢可以原樣貼進報告 | 和 Fabric（Spark＋Delta）是不同引擎，搬上正式環境時 SQL 方言、寫入語意都要重寫或重新驗證；面談會被問「上 Fabric 要改什麼」 |
| B. PySpark＋Delta | 和 Fabric Lakehouse 同一套引擎與表格格式，`MERGE INTO`、Delta 時光回溯（time travel）、`RESTORE` 的寫法可以直接沿用；Part B 已實測過的 Delta 行為（E12）可以接續使用 | 閱卷者本機要有 Java 才能執行；local 模式每次啟動 SparkSession 要幾秒，pytest 比較慢；以 demo 資料量來看用不到分散式運算，多了 session timezone、分區等設定要顧 |
| C. pandas | 使用者最熟；不需要 Java | 沒有 `MERGE`，冪等 upsert 和 SCD2 都要手寫合併邏輯，容易出錯；檢核邏輯不是 SQL，報告較難閱讀；和 Fabric 的距離比 A 更遠 |

## 決定〔使用者撰寫〕
〔待使用者確認〕選 B：PySpark＋Delta。

## 理由〔使用者撰寫〕
〔待使用者確認〕使用者在對話中的原話：「是給生產環境的 也查過雄獅旅遊的規模」、「csv是demo資料 不能當作prod的資料量」。

〔請補上：查到的規模是什麼〕

## 後果
- **閱卷者執行成本**：README 要寫清楚前置需求（Java 版本、`uv sync`）與一條指令跑完整條管線；沒有 Java 的閱卷者要先安裝 Java，會吃掉「30 分鐘內重現」的時間，這是接受的代價。
- **時區要明確設定**：Part B 的 F2 指出轉 timestamp 時 session timezone 會影響 `order_date`。管線要固定 `spark.sql.session.timeZone`，並有測試覆蓋。
- **MERGE 前來源必須先去重**：Part B E12 實測，來源同一個 key 有多列時，若對不到 target 既有列，Delta `MERGE` 會**靜默插入多列**。每次 `MERGE` 前都要在來源端先依 key 取一筆，並有測試覆蓋。
- **冪等證明可用 Delta 自身功能**：除了重跑前後的筆數與金額 checksum，還可以附 `DESCRIBE HISTORY` 作為輔助證據。
- **測試成本**：pytest 用 session 層級的 SparkSession fixture 共用一個 session，避免每個測試各自啟動。
- **Part C 接得上**：Part A 的表結構和寫入方式可以直接作為 Part C Fabric 架構的 Lakehouse 層。
