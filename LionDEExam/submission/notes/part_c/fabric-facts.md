# Fabric 事實查證（Part C 用）
- 查詢日期：2026-10-19；查詢者：研究 subagent（opus）；範圍：learn.microsoft.com（少數狀態引用 blog.fabric.microsoft.com，已標明）
- 用法：Part C 設計文件只能引用本檔有 URL 的說法
- 狀態欄規則：頁面明寫 Preview 就寫 Preview；頁面明寫 generally available 就寫 GA；頁面沒標示寫「未標示」（不等於 GA，見最後一節）
- 每節標題後附該節主要頁面的 ms.date（文件版本日）

## 目錄
- [1. F1 Eventstream](#1-f1-eventstream)
- [2. F2 Eventhouse／KQL database](#2-f2-eventhousekql-database)
- [3. F3 Real-Time Dashboard](#3-f3-real-time-dashboard)
- [4. F4 Lakehouse SQL analytics endpoint vs Warehouse](#4-f4-lakehouse-sql-analytics-endpoint-vs-warehouse)
- [5. F5 Direct Lake](#5-f5-direct-lake)
- [6. F6 Power BI semantic model（RLS、Prep data for AI）](#6-f6-power-bi-semantic-modelrlsprep-data-for-ai)
- [7. F7 Fabric data agent](#7-f7-fabric-data-agent)
- [8. F8 OneLake 權限](#8-f8-onelake-權限)
- [9. F9 Mirroring for SQL Server](#9-f9-mirroring-for-sql-server)
- [10. F10 Fabric Spark Structured Streaming](#10-f10-fabric-spark-structured-streaming)
- [11. 未查到或文件矛盾](#11-未查到或文件矛盾)
- [12. 對設計的影響](#12-對設計的影響)

## 1. F1 Eventstream
主要頁面：sources（ms.date 2026-03-19）、overview（ms.date 2026-09-02）、custom endpoint（ms.date 2026-05-18）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F1-1 | 來源包含 Azure Event Hubs、Apache Kafka、Confluent Cloud for Apache Kafka、Amazon MSK、Google Pub/Sub、Kinesis 等串流平台 | 未標示（表中這幾項無 preview 字樣） | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-manage-eventstream-sources | "Confluent Cloud for Apache Kafka ... By integrating Confluent Cloud for Apache Kafka as a source within your eventstream" |
| F1-2 | CDC 來源包含 Azure SQL Database CDC、Azure SQL Managed Instance CDC、SQL Server on VM DB CDC、PostgreSQL、MySQL、Cosmos DB、MongoDB；Oracle CDC 為 Preview | CDC 連接器未標示；Oracle CDC Preview | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-manage-eventstream-sources | "SQL Server on Virtual Machine (VM) Database (DB) CDC ... capture a snapshot of the current data in a SQL Server database on a VM" |
| F1-3 | CDC 來源的 SQL Server 連接器名稱是「SQL Server on VM」，清單上沒有一般 on-prem SQL Server CDC 連接器；另有 Mirrored Database Change Feed 來源（Preview） | Mirrored DB Change Feed：Preview | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-manage-eventstream-sources | "Mirrored Database Change Feed (preview) ... ingest real-time change events from a Fabric Mirrored Database" |
| F1-4 | DeltaFlow 把原始 CDC 事件（Debezium JSON）轉成貼近來源表結構的表格格式，並自動建立／維護目的地表 | Preview | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/overview | "DeltaFlow is a capability within Fabric Eventstreams that transforms raw Change Data Capture (CDC) events ... into analytics-ready streaming data." |
| F1-5 | 目的地：Custom endpoint、Eventhouse、Lakehouse、Derived stream、Activator、Spark Notebook（Preview） | Spark Notebook：Preview；其餘未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-manage-eventstream-destinations | "Spark Notebook (Preview) ... This feature is currently in Preview." |
| F1-6 | Eventhouse 目的地有兩種模式：Direct ingestion 與 Event processing before ingestion | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-manage-eventstream-destinations | "You can choose between two ingestion modes: Direct ingestion and Event processing before ingestion." |
| F1-7 | Lakehouse 目的地把事件轉成 Delta Lake 格式寫入 lakehouse 表 | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-manage-eventstream-destinations | "Real-time events are converted into Delta Lake format and then stored in the designated lakehouse tables." |
| F1-8 | 內建 no-code 轉換：Filter、Manage fields、Aggregate、Group by（時間窗）、Union、Expand、Join；另有 SQL operator（Preview）。官方轉換清單沒有獨立的「dedup」運算子 | no-code 轉換未標示；SQL operator Preview | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/overview | "Group by: Use this transformation to calculate aggregations across all events within a certain time window." |
| F1-9 | Custom endpoint 提供 Event Hub、AMQP、Kafka 三種協定的連線資訊，Kafka client 可直接送事件 | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-source-custom-app | "The Details pane has three protocol tabs: Event Hub, AMQP, and Kafka." |
| F1-10 | Eventstream 底層是自動建立的 Event Hubs namespace，因此提供 Kafka endpoint | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/overview | "When you create an eventstream, an event hub namespace is automatically created for you." |
| F1-11 | 限制：單則訊息最大 1 MB、事件資料最長保留 90 天、傳遞保證為 at-least-once | 不適用 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/overview | "Event delivery guarantees | At least once" |

## 2. F2 Eventhouse／KQL database
主要頁面：OneLake availability（ms.date 2026-05-18）、data policies（ms.date 2026-03-22）、materialized views（ms.date 2024-08-11，updated 2026-08-11）、update policy（ms.date 2026-09-06）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F2-1 | OneLake availability 把 KQL 資料以 Delta Lake 格式的邏輯副本暴露給其他 Fabric 引擎（Direct Lake、Warehouse、Lakehouse、Notebook） | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-house-onelake-availability | "you can query the data in your KQL database in Delta Lake format through other Fabric engines such as Direct Lake mode in Power BI, Warehouse, Lakehouse, Notebooks" |
| F2-2 | OneLake 寫入有延遲：預設最多 3 小時或累積到約 200–256 MB；可用 `TargetLatencyInMinutes` 調到 5 分鐘～3 小時 | 不適用 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-house-onelake-availability | "Up to 3 hours, or until files of sufficient size (typically 200-256 MB) are created | 5 minutes to 3 hours" |
| F2-3 | 開啟 OneLake availability 期間不能改表名、改欄位型別、套 RLS、delete/truncate/purge | 不適用 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-house-onelake-availability | "Apply row-level security to tables. Delete, truncate, or purge data." |
| F2-4 | KQL DB 的 retention policy 也套用到 OneLake 副本；預設保留 3,650 天，最短 1 天、最長 36,500 天 | 不適用 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/data-policies | "The default data retention policy is 3,650 days, with a maximum of 36,500 days." |
| F2-5 | Caching policy 控制哪些資料放在本地 SSD（hot cache），期間必須 ≤ retention | 不適用 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/data-policies | "The caching policy controls which data gets cached and stored on the local SSD." |
| F2-6 | Update policy：資料寫入來源表時自動跑查詢、把轉換結果寫進目標表；正式環境建議 `IsTransactional: true` | 不適用 | https://learn.microsoft.com/en-us/kusto/management/update-policy?view=microsoft-fabric | "In production systems, set IsTransactional:true to ensure that the target table doesn't lose data in transient failures." |
| F2-7 | Update policy 每個 ingestion batch 各自執行，因此只能在同一批內聚合；跨批聚合要用 materialized view | 不適用 | https://learn.microsoft.com/en-us/kusto/management/materialized-views/materialized-view-use-cases?view=microsoft-fabric | "Update policies run separately for each ingestion batch, and therefore can only perform aggregations within the same ingestion batch." |
| F2-8 | Materialized view 用 `arg_max(Timestamp, *) by key` 取每個 entity 最新一列（官方列為「Update data」用例） | 不適用 | https://learn.microsoft.com/en-us/kusto/management/materialized-views/materialized-view-use-cases?view=microsoft-fabric | "Update data by returning the last record per entity using arg_max() (aggregation function)." |
| F2-9 | 去重用 `take_any(*) by EventId`，可設 lookback（如 6h）只跟回看窗內的紀錄比對 | 不適用 | https://learn.microsoft.com/en-us/kusto/management/materialized-views/materialized-view-use-cases?view=microsoft-fabric | "Records are deduplicated against only records ingested 6 hours before current records." |
| F2-10 | 直接查 materialized view 永遠是最新結果（已物化部分 + 尚未物化的 delta）；`materialized_view()` 只查已物化部分，較快但可能不新 | 不適用 | https://learn.microsoft.com/en-us/kusto/management/materialized-views/materialized-view-overview?view=microsoft-fabric | "The query combines the materialized part of the view with the records in the source table, which haven't yet been materialized (the delta part)" |
| F2-11 | `arg_max` view 在每次物化要更新的列只占來源表一小部分時效能最好 | 不適用 | https://learn.microsoft.com/en-us/kusto/management/materialized-views/materialized-view-overview?view=microsoft-fabric | "A materialized view works best if the number of records being updated (for example, in arg_max view) is a small subset of the source table." |

## 3. F3 Real-Time Dashboard
主要頁面：create（ms.date 2026-10-04）、live refresh（ms.date 2026-08-27）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F3-1 | 資料來源可為 Eventhouse/KQL Database、Ontology、Azure Data Explorer、Azure Monitor（App Insights / Log Analytics）；tile 用 KQL 查詢 | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-real-time-create | "Dashboard tiles use Kusto Query Language (KQL) queries to fetch data and generate visuals." |
| F3-2 | Live refresh：偵測到新資料 ingest 才更新 visual（以 `ingestion_time()` 為基礎的輕量背景查詢），新 dashboard 預設開啟 | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-live-refresh | "Live refresh uses a single lightweight background query per visual based on the ingestion_time() function." |
| F3-3 | Live refresh 可設「Refresh rate limit」（兩次更新最小間隔）與「Fallback refresh interval」（不支援偵測的 visual 用固定間隔）；文件沒給數字下限 | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-live-refresh | "Refresh rate limit: Sets a minimum time interval between refreshes to prevent excessive updates during high-frequency data ingestion." |
| F3-4 | 檢視者看得到每個 visual 的最後更新時間，可暫停 live refresh | 未標示 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-live-refresh | "Each visual displays its last refresh timestamp, so you can quickly assess how current the data is." |

## 4. F4 Lakehouse SQL analytics endpoint vs Warehouse
主要頁面：data-warehousing（ms.date 2025-09-09）、SQL endpoint performance（ms.date 2026-08-07）、transactions（ms.date 2026-06-03）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F4-1 | SQL analytics endpoint 的 T-SQL 只能定義與查詢物件，不能修改資料（唯讀）；可建 view、TVF、stored procedure、管權限 | GA（產品本體，頁面未標 preview） | https://learn.microsoft.com/en-us/fabric/data-warehouse/data-warehousing | "With the SQL analytics endpoint, T-SQL commands can define and query data objects but not manipulate or modify the data." |
| F4-2 | Warehouse 支援完整 DDL/DML 與多表 ACID transaction；資料存成 Delta table | 未標示 | https://learn.microsoft.com/en-us/fabric/data-warehouse/data-warehousing | "full multi-table ACID transaction support" |
| F4-3 | Warehouse 與所有 Fabric 資料一樣存成 Delta（Parquet + transaction log） | 不適用 | https://learn.microsoft.com/en-us/fabric/data-warehouse/data-warehousing | "Fabric Data Warehouse data, like all Fabric data, is stored in Delta tables" |
| F4-4 | Warehouse 可用 BEGIN/COMMIT/ROLLBACK 把多表 insert 綁成一個交易；強制 snapshot isolation；鎖是表層級 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-warehouse/transactions | "you could commit inserts to multiples tables, or, none of the tables if an error arises." |
| F4-5 | 表層級鎖 → 兩個交易改同一表的不同列也可能 write-write conflict（Error 24556/24706），需 retry | 不適用 | https://learn.microsoft.com/en-us/fabric/data-warehouse/transactions | "If two transactions attempt to modify different rows in the same table, they can still conflict." |
| F4-6 | Lakehouse 到 SQL endpoint 有 metadata 同步延遲：正常 < 1 分鐘，可能幾秒到數分鐘；15 分鐘無查詢後背景同步停止；可手動或用 REST API 觸發 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-engineering/sql-analytics-endpoint-performance | "Under normal operating conditions, the lag between a lakehouse and SQL analytics endpoint is less than one minute." |

## 5. F5 Direct Lake
主要頁面：overview（ms.date 2026-09-02，updated 2026-10-14）、how it works（ms.date 2025-09-22）、develop（ms.date 2026-09-02）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F5-1 | Direct Lake 有兩種：on OneLake（可多來源、不 fallback）與 on SQL（單一來源，經 SQL endpoint，可 fallback 到 DirectQuery） | 兩者頁面皆未標 Preview（見最後一節） | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview | "Direct Lake on OneLake doesn't fall back to DirectQuery mode via the SQL analytics endpoint of the data source." |
| F5-2 | 支援來源：Lakehouse、Warehouse、SQL database、Mirrored database、Snowflake 等；KQL database 只支援 on OneLake（需開 OneLake availability） | 不適用 | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview | "For a KQL database, turn on OneLake availability to make its data available in Delta Lake format." |
| F5-3 | Framing：refresh 只更新 metadata、指向最新 Parquet 檔，通常幾秒；查詢看到的是「最近一次成功 framing」時的 Delta 狀態 | 不適用 | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-how-it-works | "Direct Lake tables are queried to return data based on the state of the Delta table at the point of the most recent successful framing operation." |
| F5-4 | 「Keep your Direct Lake data up to date」預設開啟，偵測到 Delta 變動就自動 framing；ETL 未完成前可關掉改手動／排程／API refresh | 不適用 | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-how-it-works | "you might need to allow completion of data preparation jobs or an extract, transform, and load (ETL) process before exposing any new data" |
| F5-5 | Fallback（僅 on SQL）條件：SQL endpoint 上有 RLS/OLS/DDM、表是非物化 SQL view、超過 guardrail、未 framing | 不適用 | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-how-it-works | "The semantic model doesn't reference any tables based on unmaterialized SQL views." |
| F5-6 | Direct Lake on OneLake 官方建議作為新模型的預設選項 | 未標示 | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-how-it-works | "For new semantic models, it's the recommended Direct Lake option." |
| F5-7 | Direct Lake on OneLake 不套用 SQL endpoint 的 RLS（直接讀 OneLake 檔，依 OneLake security） | 不適用 | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview | "When Direct Lake on OneLake is employed, queries will succeed, and SQL based RLS is not applied." |
| F5-8 | Semantic model RLS 在兩種 Direct Lake 都支援，但強烈建議用 fixed identity cloud connection | 不適用 | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview | "Yes – but it's strongly recommended to use a fixed identity cloud connection" |
| F5-9 | Guardrail 依 SKU：例 F64 每表 5,000 parquet 檔、15 億列；超過時 on OneLake refresh 失敗、on SQL 改 fallback | 不適用 | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview | "Direct Lake on OneLake: Similar to Import mode, refresh fails and the model cannot be queried until the Delta tables are optimized" |
| F5-10 | 引用 Direct Lake 欄位的 calculated columns/tables 為 Preview | Preview | https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-develop | "You need modeling features like calculated columns or calculated tables that reference Direct Lake tables (preview)." |

## 6. F6 Power BI semantic model（RLS、Prep data for AI）
主要頁面：RLS（ms.date 2026-05-13）、Prep data for AI（ms.date 2026-05-26）、semantic model best practices for data agent（ms.date 2026-01-21）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F6-1 | Semantic model RLS 以 DAX filter 定義在 role，只對 Viewer 生效，Admin/Member/Contributor 不受限 | GA（頁面未標 preview） | https://learn.microsoft.com/en-us/fabric/security/service-admin-row-level-security | "RLS only restricts data access for users with Viewer permissions. It doesn't apply to workspace Admin, Member, or Contributor roles." |
| F6-2 | Service principal 不能加進 RLS role；以 SP 為最終身分的 app 不套用 RLS（嵌入要用 EffectiveIdentity） | 不適用 | https://learn.microsoft.com/en-us/fabric/security/service-admin-row-level-security | "Service principals can't be added to an RLS role. Accordingly, RLS isn't applied for apps using a service principal as the final effective identity." |
| F6-3 | Prep data for AI 包含 AI data schema、verified answers、AI instructions，存在 semantic model 上 | Preview（頁面標題標 Preview） | https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai | "prepare a semantic model by using AI data schemas, verified answers, and AI instructions" |
| F6-4 | 使用 Prep data for AI 必須在 semantic model 啟用 Q&A | Preview | https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai | "You must enable Power BI Q&A on your semantic model." |
| F6-5 | Data agent 的 DAX 生成工具會用 Prep for AI 設定；Power BI Copilot 也用同一套 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/semantic-model-best-practices | "Power BI Copilot also uses Prep for AI configurations, so investing time in setting these up benefits both Copilot and data agent responses." |
| F6-6 | 查 semantic model 時，data agent 層級的 instructions 會被忽略，只看 model metadata 與 Prep for AI | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/semantic-model-best-practices | "The DAX generation tool ignores any instructions you add at the data agent level for DAX query generation." |
| F6-7 | 官方建議為表、欄、量值寫 description，幫 LLM 理解物件用途 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/semantic-model-best-practices | "Add descriptions to tables, columns, and measures to help the LLM understand the purpose of each object included in the AI data schema." |
| F6-8 | Data agent 不支援 semantic model 的 data source instructions／descriptions，也不支援 example queries | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/semantic-model-best-practices | "unlike other data sources, data agent doesn't support data source instructions or descriptions for semantic models." |

## 7. F7 Fabric data agent
主要頁面：concept（ms.date 2026-05-11）、how-to create（ms.date 2026-05-20）、evaluate（ms.date 2026-09-01）、Copilot Studio（ms.date 2026-05-12）、Foundry（ms.date 2026-10-14）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F7-1 | Data agent 本體宣稱 GA（另一頁有矛盾，見最後一節） | GA（concept 頁） | https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent | "Data agent in Microsoft Fabric is a generally available feature" |
| F7-2 | 支援來源：lakehouse、warehouse、Power BI semantic model、KQL database、ontology、Microsoft Graph；每個 agent 最多 5 個來源 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent | "you can add up to five data sources ... in any combination (up to five total)." |
| F7-3 | 可只勾選部分表給 AI 用（Explorer 勾選框） | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent | "use the checkboxes to make individual elements available or unavailable to the AI" |
| F7-4 | 以提問者自己的 Entra ID 身分與權限讀 schema、執行 SQL/DAX/KQL | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent | "Data access runs under your Microsoft Entra ID user identity and your workspace/data permissions." |
| F7-5 | 只產生唯讀查詢，不做寫入 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent | "The Fabric data agent only generates SQL, DAX, and KQL \"read\" queries." |
| F7-6 | Agent instructions 上限 15,000 字元，用於來源路由與名詞定義 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent | "you can write up to 15,000 characters in plain English-language text" |
| F7-7 | Example queries（few-shot）支援 lakehouse/warehouse/KQL，每個來源最多 100 組；必須通過語法與 schema 驗證才會被採用 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent | "Users can provide up to 100 example queries per data source in their Data Agent." |
| F7-8 | 回應最多 25 列 × 25 欄；不支援非英文；不能換 LLM | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent | "responses are capped at a maximum of 25 rows and 25 columns."；"The Fabric data agent doesn't currently support non-English languages."（主 session 2026-10-19 用 WebFetch 重開頁面補上這句原文，研究 agent 原本只引了 25 列那句） |
| F7-9 | 透過 data agent 查 semantic model 只需要 model 的 Read 權限，不需要 workspace 角色或 Build；RLS/CLS 仍套用 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent | "Row-Level Security (RLS) and Column-Level Security (CLS) still apply." |
| F7-10 | 可被 Copilot Studio 當 connected agent 使用；可選 User authentication 或 Agent author authentication | Preview | https://learn.microsoft.com/en-us/fabric/data-science/data-agent-microsoft-copilot-studio | "If you select User authentication as the authentication, you need to ensure that users have access to the Fabric data agent and its underlying data sources." |
| F7-11 | 可被 Microsoft Foundry agent 當工具使用，以 identity passthrough（OBO）用終端使用者身分查詢；此整合 2026-11-06 起停止支援，改用 Fabric IQ | Preview（且即將退役） | https://learn.microsoft.com/en-us/fabric/data-science/data-agent-foundry | "Starting November 6, 2026, it won't be supported." |
| F7-12 | Python SDK 的 `evaluate_data_agent` 可用 question/expected_answer 的 ground truth 自動評估，可自訂 `critic_prompt` | Preview | https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent | "By using the Fabric SDK for evaluation, you can programmatically test how well your data agent responds to natural language questions." |
| F7-13 | 支援 Git integration 與 deployment pipelines（dev→test→prod） | 不適用 | https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent | "Use Fabric deployment pipelines to promote data agents from development to test and production workspaces." |

## 8. F8 OneLake 權限
主要頁面：security overview（ms.date 2026-09-01）、data access control model（ms.date 2026-08-28）、SQL endpoint OneLake security（ms.date 2026-07-22）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F8-1 | 權限分兩層：control plane（workspace roles、item permissions）與 data plane（OneLake security） | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/get-started-security | "Data plane permissions: Govern what data you can see or change. For OneLake, this plane is OneLake security." |
| F8-2 | Workspace 角色：Admin/Member/Contributor 可讀寫 OneLake 資料；Viewer 預設讀不到 OneLake 資料，要靠 OneLake security role 授權 | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/get-started-security | "You can give Viewers access to data by using OneLake security roles." |
| F8-3 | 只有 Admin、Member 能編輯 OneLake security；Contributor 不能 | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/get-started-security | "Fabric users in the Admin or Member workspace roles can create OneLake security roles" |
| F8-4 | Item 共享可給 Read/ReadData/ReadAll/Write 等 item 權限，不必加入 workspace | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/get-started-security | "By using the sharing feature, you can give a user direct access to an item." |
| F8-5 | OneLake security role 可設表／資料夾，以及 RLS、CLS；deny-by-default，只有 Grant 型角色；多角色間取聯集 | 頁面未標 Preview（見最後一節） | https://learn.microsoft.com/en-us/fabric/onelake/security/data-access-control-model | "OneLake security uses a deny-by-default model" |
| F8-6 | OneLake security role 對 Admin/Member/Contributor 無效（他們本來就有寫入權） | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/data-access-control-model | "Default roles apply only to Viewers, because Admin, Member, and Contributor roles have elevated access through the Write permission." |
| F8-7 | 角色定義變更約 5 分鐘生效；群組成員變更約 1 小時，部分引擎再加 1 小時 | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/data-access-control-model | "Changes to role definitions take about 5 minutes to apply." |
| F8-8 | SQL endpoint 有兩種模式：User identity（表權限由 OneLake security 管，不能 GRANT 表）與 Delegated（用 SQL GRANT/RLS/CLS/DDM，以 item owner 身分讀 OneLake）；新 endpoint 預設 Delegated | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/sql-analytics-endpoint-onelake-security | "Newly created SQL analytics endpoints start in delegated identity access mode by default." |
| F8-9 | Delegated 模式下 OneLake security 規則不會套用到 SQL endpoint 查詢 | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/sql-analytics-endpoint-onelake-security | "any security rules defined in OneLake ... will not apply when the same data is queried through the SQL analytics endpoint." |
| F8-10 | Warehouse 用 SQL 定義的 RLS/CLS 只在 TDS 端點生效；從 shortcut 讀可能看到全部資料 | 不適用 | https://learn.microsoft.com/en-us/fabric/onelake/security/sql-analytics-endpoint-onelake-security | "users accessing the data through a shortcut might see the full warehouse data, regardless of SQL security policies configured in the producer warehouse." |

## 9. F9 Mirroring for SQL Server
主要頁面：mirroring/sql-server（ms.date 2025-11-05，updated 2026-07-06）、mirroring overview（ms.date 2026-08-28）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F9-1 | 支援 SQL Server 2016–2022（Windows Standard/Enterprise/Developer；部分 Linux 版）與 SQL Server 2025（僅 on-prem，不支援 Azure VM 與 Linux，需 Azure Arc） | Learn 頁未標 Preview；GA 公告見最後一節 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server | "Fabric Mirroring for SQL Server 2025 requires connection to Azure Arc including the Azure Extension for SQL Server." |
| F9-2 | 2016–2022 用 CDC；2025 用 Fabric mirroring change feed | 不適用 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server | "Mirroring for SQL Server 2016 - 2022 uses the Change Data Capture (CDC) feature." |
| F9-3 | 在防火牆後要用 on-premises data gateway 或 VNet data gateway | 不適用 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server | "Set up an on-premises data gateway or virtual network data gateway to mirror the data." |
| F9-4 | 產出：OneLake 中的 Delta table + 唯讀的 SQL analytics endpoint | 不適用 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server | "Users have access to familiar T-SQL commands that can define and query data objects but not manipulate the data from the SQL analytics endpoint, as it's a read-only copy." |
| F9-5 | 變更最快每 15 秒發布一次；延遲受量、頻率、網路、gateway 資源影響 | 不適用 | https://learn.microsoft.com/en-us/fabric/mirroring/overview | "Changes can be published as fast as every 15 seconds." |
| F9-6 | 長交易會拖住來源端 transaction log 截斷，需監控 log | 不適用 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server | "Long-running transactions might result in the transaction log filling up more than usual." |
| F9-7 | 複寫用的 compute 免費、mirroring 儲存按 CU 數給免費額度（每 CU 1 TB）；查詢照常計費 | 不適用 | https://learn.microsoft.com/en-us/fabric/mirroring/overview | "Background Fabric compute used to replicate your data into Fabric OneLake is free and doesn't consume capacity." |

## 10. F10 Fabric Spark Structured Streaming
主要頁面：lakehouse-streaming-data（ms.date 2026-02-24）、get-started-streaming（ms.date 2025-07-20）

| # | 說法 | 狀態 | 出處 URL | 原文關鍵句 |
|---|---|---|---|---|
| F10-1 | 正式環境的連續串流作業建議用 Spark Job Definition，不用 notebook | 不適用 | https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-streaming-data | "for production workloads that need to run continuously, use Spark job definitions instead." |
| F10-2 | Retry policy 可設最多重試次數（可無限）與間隔，job 意外停止時自動重啟 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-streaming-data | "Configure the retry policy on a Spark job definition to specify how many times to restart the job (up to infinite retries)" |
| F10-3 | Retry policy 有 90 天壽命上限，之後 job 終止，需手動重啟 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-engineering/get-started-streaming | "There is a lifetime limit of 90 days for the retry policy setup." |
| F10-4 | 建議用 trigger interval（如 1 分鐘）把事件批次寫入，以減少小檔案 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-streaming-data | "Larger batches produce bigger Delta files and reduce small-file overhead." |
| F10-5 | 官方 quickstart 示範 Spark Job Definition 用 Structured Streaming 寫 lakehouse Delta 表，再從 SQL endpoint 查 | 不適用 | https://learn.microsoft.com/en-us/fabric/data-engineering/get-started-streaming | "create a Spark job definition that contains Python code with Spark Structured Streaming to land data in a lakehouse" |

## 11. 未查到或文件矛盾
1. **Data agent 是 GA 還是 Preview（矛盾）**：concept 頁（ms.date 2026-05-11）寫 "Data agent in Microsoft Fabric is a generally available feature"；但「Release Status of AI and Copilot in Fabric」頁（https://learn.microsoft.com/en-us/fabric/fundamentals/copilot-ai-feature-state ，ms.date 2026-06-19）在 Data Science 列把「Data agent, AI functions, AI services」合併標為 Preview。合併列可能是因為 AI functions 還是 Preview；面試時建議講成「本體 GA（concept 頁），周邊整合（Copilot Studio、Foundry、評估 SDK）仍 Preview」。
2. **Direct Lake on OneLake 的狀態**：目前 Learn 的 overview／how it works／develop 三頁都沒有 Preview 標記，還寫明「recommended Direct Lake option」；但 Learn 上沒找到明確的 GA 宣告句。一則 Power BI 部落格（https://powerbi.microsoft.com/en-us/blog/deep-dive-into-direct-lake-on-onelake-and-creating-direct-lake-semantic-models-in-power-bi-desktop/ ，非 Learn 文件，沒開啟驗證）早期描述它是 public preview。結論：只能說「Learn 現行文件未標 Preview」，不能說「GA」。
3. **OneLake security（含 RLS/CLS）的狀態**：Learn 現行頁面沒標 Preview（只有 third-party authorized engines 標 Preview）。GA 公告見官方部落格 https://blog.fabric.microsoft.com/en-us/blog/fabcon-and-sqlcon-2026-whats-new-in-microsoft-onelake （非 Learn 文件；WebFetch 回 403 沒開成，內容只來自搜尋摘要：「will be generally available in the coming weeks」），沒有確切 GA 日期。
4. **Mirroring for SQL Server 的 GA**：Learn 的 sql-server 頁沒寫狀態；overview 的來源表中 SQL Server 沒有 "(preview)" 字樣（其他 preview 來源都有標）。GA 公告：https://blog.fabric.microsoft.com/en-us/blog/mirroring-for-sql-server-in-microsoft-fabric-generally-available/ （非 Learn 文件；403 沒開成，依搜尋摘要寫 2016–2022 與 2025 皆 GA，Fabric November 2025 Feature Summary 也列為 GA）。「需要 on-prem data gateway」在 Learn 的寫法是「behind firewall」時才需要，沒寫成無條件必需。
5. **Real-Time Dashboard auto refresh 最小間隔／continuous 模式**：現行文件改成 Live refresh（偵測 ingest），沒有給 Refresh rate limit 的數字下限，也沒有「continuous」字樣。匯出 JSON 範例中的 `"minInterval": "5m"` 只是範例值，不能當規格引用。搜過：dashboard-real-time-create、dashboard-live-refresh、站內搜尋 "auto refresh minimum time interval continuous"。
6. **Eventstream 內建 dedup 運算子**：overview 的轉換清單（Filter、Manage fields、Aggregate、Group by、Union、Expand、Join、SQL operator preview）裡沒有 dedup。去重要在 Eventhouse 用 materialized view（F2-9）或 SQL operator 自己寫（後者沒有查到範例，屬於推測）。
7. **Spark Job Definition retry 專頁**：`https://learn.microsoft.com/en-us/fabric/data-engineering/spark-job-definition-retry` 回 404，改用 get-started-streaming 與 lakehouse-streaming-data 兩頁。
8. **Eventstream 的 SQL Server CDC 只列「SQL Server on VM」**：on-prem SQL Server 能否透過這個連接器加 gateway 接入，本次沒有查證。

## 12. 對設計的影響
> 主 session 註（2026-10-19）：以下是研究 agent 依事實提出的建議，Part C 沒有全採。第 2 條（問數優先接 semantic model）與 ADR-08 方向不同；第 6 條（gold 選 Warehouse）與 ADR-06 方向不同。採用與否見 `tentative-decisions.md` 與 ADR-06、ADR-08。

1. **權限可以沿用，不必另建一套**：data agent 用提問者自己的 Entra 身分查詢（F7-4），對 semantic model 時 RLS/CLS 照樣套用（F7-9）。所以 Text-to-SQL 服務的資料權限可以直接靠 semantic model RLS 或 OneLake security，不需要在 agent 層另做過濾。前提是使用者是 Viewer 或只有 item 共享權限（F6-1、F8-6），否則 RLS 不生效。
2. **問數服務優先接 semantic model，業務語意寫在 Prep for AI，不寫在 agent**：DAX 工具會忽略 agent 層 instructions（F6-6），semantic model 也不支援 example queries（F6-8）。名詞定義、指標口徑要寫在 Prep for AI 與欄位 description（F6-5、F6-7），Copilot 也能共用。代價是 Prep data for AI 仍是 Preview（F6-3）。
3. **準即時路徑以 Eventhouse 為核心，不走 OneLake/Direct Lake**：OneLake availability 預設延遲最多 3 小時，最低也要 5 分鐘（F2-2）；Real-Time Dashboard 直接查 KQL，並以 live refresh 偵測新資料（F3-1、F3-2）。所以「分鐘級」儀表板應該直查 Eventhouse，批次報表才從 OneLake 走 Direct Lake。
4. **訂單事件的去重／取最新狀態放在 Eventhouse materialized view**：Eventstream 沒有 dedup 運算子（未查到 #6），而且傳遞保證是 at-least-once（F1-11），重複事件必然會出現。用 `arg_max(...) by order_id` 的 materialized view 取最新狀態（F2-8），或用 `take_any` 加 lookback 去重（F2-9）。update policy 只能在同一批內聚合，不適合拿來去重（F2-7）。
5. **批次報表用 Direct Lake on OneLake，並且 ETL 完成後才 framing**：on OneLake 不會 fallback，也是官方推薦（F5-1、F5-6）；但 SQL endpoint 的 RLS 不會套用（F5-7），權限要放在 OneLake security 或 semantic model RLS。每日批次寫入期間可以關掉自動更新，ETL 完成後再 refresh，避免使用者看到半套資料（F5-4）。
6. **需要多表原子寫入的 gold 層選 Warehouse，不選 Lakehouse SQL endpoint**：SQL endpoint 唯讀（F4-1），Warehouse 支援多表交易（F4-4）。但 Warehouse 是表層級鎖，並行 MERGE 同一張表會衝突（F4-5），排程要錯開，並加上 retry。
7. **來源若是 SQL Server，Mirroring 是低維運的批次來源**：可以用 CDC/change feed 持續複寫成 Delta（F9-2、F9-4），防火牆後需要 gateway（F9-3）。它是「近即時複寫」，不是事件流；訂單事件的分鐘級需求仍應走 Eventstream。
8. **用 Spark Streaming 自寫 Lakehouse 時，要自己扛維運**：要用 Spark Job Definition 並設 retry，但 retry 只有 90 天壽命（F10-1、F10-3），還要調 trigger 避免小檔案（F10-4）。相較之下，Eventstream 的 Lakehouse 目的地是 no-code（F1-7）。除非需要複雜狀態運算，否則不建議自寫。
