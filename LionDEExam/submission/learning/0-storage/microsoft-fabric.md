# Microsoft Fabric：一站式資料分析平台
Fabric 是微軟的 SaaS 資料平台，把儲存、ETL、Spark 運算、SQL 查詢、Power BI 報表放在同一個網頁服務裡，共用同一份儲存（OneLake）和同一套權限，不用自己架伺服器。

## 白話版
以前做資料平台，要分別買儲存（Data Lake）、ETL 工具（Data Factory）、運算引擎（Synapse／Spark）、報表（Power BI），再自己把它們接起來。Fabric 把這些包成一個產品，資料只存一份，每個工具都直接讀它。

## 主要元件
| 元件 | 做什麼 | 對應本專案 |
|---|---|---|
| **OneLake** | 整個組織共用的一個資料湖，表格一律存成 Delta 格式 | Part A 寫出的 Delta 表 |
| **Lakehouse** | 一組 Delta 表，加上用來跑 PySpark 的 Notebook | `part_a/pipeline/` 的程式與 fact、dim 表 |
| **Data Factory（Pipeline）** | 排程、搬資料，例如每天把營運 DB 的資料拉進來 | 「每天處理一個增量檔」的排程 |
| **Warehouse** | 用 T-SQL 操作的資料倉 | 本專案沒用到 |
| **Real-Time Intelligence** | 即時串流（Eventstream）與即時查詢 | Part C 的分鐘級儀表板 |
| **Power BI** | 報表與儀表板，可以直接讀 Lakehouse 的 Delta 表 | Part C 的每日 BI 報表 |

## 實際使用的流程
1. 在網頁上建一個 **Workspace**（工作區）
2. 在裡面建一個 **Lakehouse**
3. 用 **Data Factory** 把營運 DB 的資料搬進來，或直接上傳檔案
4. 開一個 **Notebook**，用 PySpark 清理、建模，結果寫成 Delta 表
5. Lakehouse 會自動提供 **SQL endpoint**，可以直接用 SQL 查這些表
6. **Power BI** 直接連這些表做報表

計費依購買的運算容量（capacity），不是按每次使用計費。

## 什麼時候用、什麼時候不要用
- **適合**：公司已經用 Microsoft 365、Power BI，想把資料平台集中在一個產品裡；團隊不想自己維運 Spark 叢集
- **要考慮**：綁定微軟生態系；按容量計費，用量小時不一定划算；本機無法完整重現，開發和測試要另外規劃（本專案就是在本機用 PySpark＋Delta 模擬 Lakehouse 那一層）

## 最小範例（未執行，Fabric Notebook 的寫法示意）
```python
# Fabric Notebook 內已有 spark session；Lakehouse 的表用名稱存取
df = spark.read.format("csv").option("header", True).load("Files/orders_base.csv")
df.write.format("delta").mode("overwrite").saveAsTable("fact_order")
spark.sql("SELECT order_status, count(*) FROM fact_order GROUP BY order_status").show()
```
本專案的本機程式改用路徑（`spark.read.format("delta").load(path)`）存取 Delta 表；搬到 Fabric 時，主要差別在路徑與表名，運算邏輯不用改。

## 常見的坑
- **本機和 Fabric 不同**：本機要自己設定 Delta extension 與時區（本專案的 `build_spark()`）；Fabric Notebook 已經預先設定好，但時區等設定仍要明確指定，不能假設和本機相同
- **引擎選錯會重寫**：選 DuckDB 或 pandas 在本機開發，搬上 Fabric 時要重寫成 Spark（ADR-01 的考量）

## 本專案出處
- 題目 Part C：「公司決定將平台建置於 Microsoft Fabric」
- `decisions/ADR-01-*.md`：Part A 執行引擎選 PySpark＋Delta
- Part B 的 `buggy_pipeline.py` 假設在 Fabric Lakehouse 執行

## 官方文件
未證實：本筆記依 AI 的既有知識整理，這次沒有實際打開官方文件核對。之後要引用時，先查 Microsoft Learn 的 Fabric 文件（learn.microsoft.com/fabric）。
