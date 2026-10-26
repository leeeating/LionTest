# 即時方案的計費方式（Part C Q4 用）

- 查詢日期：2026-10-26
- 範圍：只查 learn.microsoft.com（Microsoft Fabric 與 Azure Cost Management 文件）與 azure.microsoft.com 的 Fabric 價格頁。比較對象：
  - 方案 A：Eventstream → Eventhouse（KQL）→ Real-Time Dashboard
  - 方案 B：Spark Structured Streaming（Spark Job Definition，每分鐘一批）寫 Lakehouse，Power BI 讀
- 標「推論」的列是由官方原文組合出來的判斷，官方沒有直接這樣寫。

## 目錄
- [1. Fabric 整體怎麼計費](#1-fabric-整體怎麼計費)
  - [1.1 capacity 與 CU](#11-capacity-與-cu)
  - [1.2 pay-as-you-go 與 reservation](#12-pay-as-you-go-與-reservation)
  - [1.3 儲存另計](#13-儲存另計)
- [2. Eventhouse／KQL database](#2-eventhousekql-database)
  - [2.1 運算：Eventhouse UpTime](#21-運算eventhouse-uptime)
  - [2.2 閒置暫停與 Capacity Planner（舊稱 Always-on）](#22-閒置暫停與-capacity-planner舊稱-always-on)
  - [2.3 儲存：hot cache 與一般儲存](#23-儲存hot-cache-與一般儲存)
- [3. Eventstream](#3-eventstream)
- [4. Real-Time Dashboard](#4-real-time-dashboard)
- [5. Spark Job Definition 長時間串流](#5-spark-job-definition-長時間串流)
  - [5.1 CU 換算與計費時段](#51-cu-換算與計費時段)
  - [5.2 24 小時常駐的串流作業](#52-24-小時常駐的串流作業)
  - [5.3 Autoscale billing（on-demand billing）for Spark](#53-autoscale-billingon-demand-billingfor-spark)
  - [5.4 Power BI 讀 Lakehouse（方案 B 的讀取端）](#54-power-bi-讀-lakehouse方案-b-的讀取端)
- [6. 官方比較與試算工具](#6-官方比較與試算工具)
- [7. 白話結論](#7-白話結論)

## 1. Fabric 整體怎麼計費

### 1.1 capacity 與 CU

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-1 | Fabric 以 capacity（F SKU）計費，SKU 的數字就是 CU 數，例如 F2 = 2 CU、F64 = 64 CU | https://learn.microsoft.com/en-us/fabric/enterprise/licenses | "Capacity units (CUs) measure the compute power for each SKU."（表格列出 F2 = 2 … F64 = 64） |
| COST-2 | 同一個 capacity 的 CU 由所有工作負載（Eventhouse、Spark、Power BI…）共用 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/real-time-intelligence-consumption | "you're entitled to a set of Capacity Units (CUs) that are shared across all Fabric workloads" |
| COST-3 | capacity 模式是「依 SKU 付固定費用」；用超過不會多收錢，而是被 throttle | https://learn.microsoft.com/en-us/fabric/data-engineering/spark-best-practices-capacity-planning | "If you overuse the capacity you're not charged more, instead you're throttled." |
| COST-4 | 對照表：capacity 模式＝固定費用、工作負載共用；Spark 的 on-demand billing＝用多少付多少 | https://learn.microsoft.com/en-us/fabric/data-engineering/autoscale-billing-for-spark-overview | "Fixed cost per capacity tier"（Capacity model 的 Billing 欄） |
| COST-5 | 背景作業（如 Spark）的耗用會攤平（smoothing）到 24 小時；KQL、SQL 等互動查詢攤平到 10 分鐘，所以 SKU 可依平均量而非尖峰量買 | https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/fabric-capacity | "Smoothing spreads background process like Spark jobs and semantic model refreshes over a 24-hour interval." |

### 1.2 pay-as-you-go 與 reservation

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-6 | F SKU 透過 Azure 購買，pay-as-you-go 按秒計費、無承諾，最低一分鐘；可選一年 reservation 省錢 | https://learn.microsoft.com/en-us/fabric/enterprise/licenses | "Azure bills you per second with no commitment, with the option of a yearly capacity reservation to save costs." |
| COST-7 | capacity 可以暫停與恢復，暫停時省錢（暫停期間該 capacity 上的工作負載都停） | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/monitor-capacity-consumption | "When your capacity isn't operational, pause it to save costs for your organization." |
| COST-8 | reservation 期限一年或三年，以 CU 為單位購買（每次 1 CU 遞增） | https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/fabric-capacity | "committing to a reservation for your Fabric capacity usage for a duration of one or three years" |
| COST-9 | reservation 折扣按小時套用，沒用完的小時不能遞延 | https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/fabric-capacity | "The Fabric capacity reservation discount is applied to CUs on an hourly basis. … It doesn't carry over." |
| COST-10 | reservation 只涵蓋 capacity，不涵蓋儲存與網路 | https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/fabric-capacity | "A reservation doesn't cover storage or networking charges" |
| COST-11 | reservation 約比 pay-as-you-go 便宜 40%；平均使用率高於 75% 才划算 | https://learn.microsoft.com/en-us/fabric/data-engineering/spark-best-practices-capacity-planning | "RI offers about a 40% discount compared to pay-as-you-go capacity." |

### 1.3 儲存另計

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-12 | OneLake 儲存按 GB pay-as-you-go 另計，不耗用 CU | https://learn.microsoft.com/en-us/fabric/onelake/onelake-consumption | "OneLake storage is billed at a pay-as-you-go rate per GB of data used and doesn't consume Fabric Capacity Units (CUs)." |
| COST-13 | 讀寫 OneLake 的交易（transactions）會耗用 CU；例如 hot tier 寫入每 4 MB、每 10,000 次 1,626 CU 秒 | https://learn.microsoft.com/en-us/fabric/onelake/onelake-consumption | "Requests to OneLake, such as reading or writing data, consume Fabric Capacity Units." |
| COST-14 | capacity 暫停時，已存的資料仍照每 GB 計費 | https://learn.microsoft.com/en-us/fabric/onelake/onelake-consumption | "When a capacity is paused, the data stored continues to be billed using the pay-as-you-go rate per GB." |
| COST-15 | 官方價格頁的單價（F SKU 每小時、OneLake 每 GB 每月、OneLake cache 每 GB 每月）以 JavaScript 載入，抓取時全部顯示為 "$-"，**未取得實際數字** | https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/ | 頁面上列有 "OneLake cache/month" 等項目，但價格欄都是 "$-" |

## 2. Eventhouse／KQL database

### 2.1 運算：Eventhouse UpTime

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-16 | Eventhouse 耗用 CU 的唯一運算項目是 Eventhouse UpTime | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/real-time-intelligence-consumption | "The amount of capacity that used by a KQL database is based on the **Eventhouse UpTime** operation." |
| COST-17 | UpTime＝「活躍的秒數 × 使用的 virtual cores」，大小由 autoscale 決定；例：4 vCore 活躍 30 秒＝120 CU 秒 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/real-time-intelligence-consumption | "a database using 4 virtual cores that is active for 30 seconds will use 120 seconds of Capacity Units" |
| COST-18 | 在 Fabric operations 清單裡，KQL Database 與 KQL Queryset 只列一個 operation：Eventhouse UpTime，類型為 Background | https://learn.microsoft.com/en-us/fabric/enterprise/fabric-operations | "Eventhouse UpTime \| Measure of the time that Eventhouse is Active" |
| COST-19 | 影響運算大小的因素：查詢量、CPU 重的功能（Materialized Views、Update Policies）、hot cache 大小（autoscale 會讓 cache 放得進 SSD） | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/pricing-cost-drivers | "Autoscale adjusts the compute size to ensure cached data fits within the available SSD space." |

### 2.2 閒置暫停與 Capacity Planner（舊稱 Always-on）

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-20 | 預設情況下，Eventhouse 不用時會自動暫停（suspend），恢復時有幾秒延遲 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/eventhouse | "Your eventhouse is designed to optimize cost by suspending the service when not in use. When reactivating the service, you might encounter a latency of a few seconds." |
| COST-21 | 開啟 Capacity Planner mode（舊稱 Always-on）後不會因閒置而暫停，UpTime 為 100%，但不再收 OneLake Cache Storage 費用 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/eventhouse-smart-capacity-control | "The eventhouse is always active, so you get 100% Eventhouse UpTime without extra premium storage costs." |
| COST-22 | Capacity Planner 未自訂排程時，最低容量是 2 CU；可依每週 60 分鐘區塊設定不同最低值，autoscale 仍可往上擴 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/eventhouse-smart-capacity-control | "If no minimum is defined for a time block, the default minimum capacity is 2 CUs (25 GB of premium storage size)." |
| COST-23 | 設了最低容量的時段，UpTime 至少按最低值累計（即「沒查詢也在耗用」） | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/real-time-intelligence-consumption | "When a minimum is set for a time window, Eventhouse UpTime reflects at least the scheduled baseline for the duration of that window." |
| COST-24 | 持續寫入資料的 Eventhouse，UpTime 會是 100%；官方建議很活躍的 Eventhouse 開 Always-on（以免同時付運算與 hot cache 儲存） | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/pricing-cost-drivers | "Because the cluster is continuously ingesting data the UpTime for the cluster is going to be 100%." |
| COST-25 | 對照情境：只在 2 小時內有活動的 Eventhouse，那天只用了 23 CU 小時；平時只付儲存 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/pricing-cost-drivers | "the customer continues to pay for the storage cost but only has to pay for compute capacity when they run more queries or ingest more data" |

### 2.3 儲存：hot cache 與一般儲存

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-26 | Eventhouse 儲存與 CU 分開計費，分兩層：OneLake Cache Storage（premium，由 cache policy 決定）與 OneLake Standard Storage（由 retention policy 決定） | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/real-time-intelligence-consumption | "Storage is billed separately from your Fabric or Power BI Premium Capacity units." |
| COST-27 | cache 層類似 ADLS premium tier；standard 層類似 ADLS hot tier | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/real-time-intelligence-consumption | "This storage tier is comparable to the Azure ADLS (Azure Data Lake Storage) premium tier." |
| COST-28 | 資料保留越久，儲存成本越高，按 OneLake Storage 價格計 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/pricing-cost-drivers | "The longer the data is retained, the higher the cost, based on Fabric OneLake Storage pricing." |

## 3. Eventstream

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-29 | Eventstream 有五種計費 operation：Per Hour 固定費 0.222 CU 小時／小時；Data Traffic 每 GB 0.342 CU 小時；Processor 每小時起跳 0.778 CU 小時並依流量 autoscale；Connectors 每 vCore 小時 0.611 CU 小時；Custom Stream Connector 每 vCore 小時 2.2607 CU 小時 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/monitor-capacity-consumption | "Eventstream Per Hour … Flat charge … 0.222 capacity unit (CU) hours" |
| COST-30 | 依「有沒有資料在流」計費：連續兩小時沒有資料進出就不收這幾項 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/monitor-capacity-consumption | "If no data flows in or out for more than two hours, these operations don't incur charges." |
| COST-31 | Processor 的耗用與事件吞吐量、處理邏輯複雜度、輸入 partition 數相關；Event throughput 設 Low 時從三分之一基本費率起跳 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/monitor-capacity-consumption | "the CU consumption rate of the eventstream processor is correlated to the throughput of event traffic" |
| COST-32 | 保留超過 1 天的事件，按 OneLake 儲存另計 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/monitor-capacity-consumption | "When you set the retention setting for more than one day (that is, 24 hours), you incur charges according to OneLake storage." |
| COST-33 | Eventstream 可在最小的 F SKU 上運作，但下游目的地（如 Eventhouse）可能需要更多 CU | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/monitor-capacity-consumption | "Microsoft Fabric eventstreams can operate with the smallest *F* capacity." |

## 4. Real-Time Dashboard

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-34 | Dashboard 的每個 tile 都是用 KQL 查詢向資料來源（Eventhouse／KQL database）取資料 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-real-time-create | "Dashboard tiles use Kusto Query Language (KQL) queries to fetch data and generate visuals." |
| COST-35 | Live refresh 會在新資料寫入時自動更新畫面，可設定 refresh rate limit | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-real-time-create | "Live refresh is a feature that updates dashboard visuals when new data is ingested into the underlying source" |
| COST-36 | **推論**：Fabric operations 清單沒有 Real-Time Dashboard 自己的計費項目；KQL 相關只有 Eventhouse UpTime。因此 dashboard 的查詢應該是讓 Eventhouse 保持活躍、併入 Eventhouse UpTime 計算。官方未直接寫「dashboard 查詢耗用 Eventhouse CU」這句話 | https://learn.microsoft.com/en-us/fabric/enterprise/fabric-operations | "The Real-Time Intelligence experience contains operations for Operations agent, Anomaly Detector, Azure and Fabric events, digital twin builder (preview), Eventstream, and KQL Database and KQL Queryset." |

## 5. Spark Job Definition 長時間串流

### 5.1 CU 換算與計費時段

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-37 | Spark 的換算：1 CU = 2 Spark vCores | https://learn.microsoft.com/en-us/fabric/data-engineering/billing-capacity-management-for-spark | "For Spark in Fabric, each capacity unit (CU) maps to two Spark vCores." |
| COST-38 | Spark Job Definition 的執行記在 "Spark Memory Optimized Capacity Usage CU"，類型 Background | https://learn.microsoft.com/en-us/fabric/enterprise/fabric-operations | "Spark job run \| Spark batch job runs initiated by user submission \| Spark Job Definition \| Spark Memory Optimized Capacity Usage CU \| Background" |
| COST-39 | 計費只算 session 活躍期間；pool 閒置不算，叢集配置與初始化時間也不算 | https://learn.microsoft.com/en-us/fabric/data-engineering/billing-capacity-management-for-spark | "Billing applies only when Spark compute is actively used." |

### 5.2 24 小時常駐的串流作業

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-40 | 正式環境的連續串流，官方建議用 Spark Job Definition；開 retry policy 後作業會一直跑到手動停止 | https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-streaming-data | "With a retry policy enabled, your streaming job continues running until you explicitly stop it." |
| COST-41 | 用 trigger 把事件累積成每分鐘一批再寫，可減少小檔案 | https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-streaming-data | "Setting a trigger interval accumulates data over a time period and writes it in fewer, larger operations." |
| COST-42 | **推論**：COST-39＋COST-40 → 串流作業的 session 一直活躍，所以 24 小時都在耗用 Spark CU，即使某分鐘沒有新資料。官方未寫出「串流作業閒置時是否少收」 | https://learn.microsoft.com/en-us/fabric/data-engineering/billing-capacity-management-for-spark | "you're billed only while the notebook session is active" |
| COST-43 | Spark 寫入 Lakehouse 屬 OneLake 寫入交易，另外耗用 CU；且自 2026-10-15 起，部分過去沒計入的 Spark OneLake 操作會開始計入 | https://learn.microsoft.com/en-us/fabric/onelake/onelake-consumption | "Beginning October 15, 2026, Fabric will correct this reporting so that these operations are included in OneLake CU consumption." |

### 5.3 Autoscale billing（on-demand billing）for Spark

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-44 | 開啟後 Spark 不再吃 capacity 的 CU，改用獨立 serverless 資源、另外按用量計費 | https://learn.microsoft.com/en-us/fabric/data-engineering/autoscale-billing-for-spark-overview | "When you enable it, Spark jobs no longer consume compute from your Fabric capacity." |
| COST-45 | 費率仍是 Spark 的 0.5 CU 小時，只對執行中的作業計費、無閒置成本；可設最大 CU 上限 | https://learn.microsoft.com/en-us/fabric/data-engineering/billing-capacity-management-for-spark | "There is no idle compute cost, and only active job compute usage is billed." |
| COST-46 | 按 capacity 開啟，不會和 capacity 互相借用（Spark 不足時不會改用 capacity 的 CU） | https://learn.microsoft.com/en-us/fabric/data-engineering/autoscale-billing-for-spark-overview | "On-demand billing is **opt-in per capacity** and **does not burst from or fall back to** Fabric capacity." |

### 5.4 Power BI 讀 Lakehouse（方案 B 的讀取端）

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-47 | 透過 Lakehouse 的 SQL analytics endpoint 查詢，記在 Data Warehouse 的 CU | https://learn.microsoft.com/en-us/fabric/enterprise/fabric-operations | "SQL Endpoint Query \| Compute charge for all user generated and system generated T-SQL statements within the SQL analytics endpoint of a Lakehouse." |
| COST-48 | Power BI 報表的互動查詢記在 "Power BI Capacity Usage CU"（Interactive） | https://learn.microsoft.com/en-us/fabric/enterprise/fabric-operations | "Interactive query \| Queries initiated by an on-demand data request." |

## 6. 官方比較與試算工具

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| COST-49 | 官方有 Fabric SKU Estimator（preview），支援 Real-time intelligence 與 Data engineering（Spark），輸出建議的 SKU | https://learn.microsoft.com/en-us/fabric/enterprise/fabric-sku-estimator | "The Fabric SKU Estimator is a web-based calculator that recommends the appropriate capacity for your workloads based on your inputs." |
| COST-50 | Eventhouse 成本文件用 "cost per GB ingested" 指標，金額用抽象的 Sample Cost Units（SCU）表示，不是實際幣別 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/pricing-cost-drivers | "cost per GB is expressed in Sample Cost Units (SCUs), where each SCU represents a generic cost unit" |
| COST-51 | 未查到：官方沒有「即時情境下 Eventhouse 和 Spark Structured Streaming 哪個比較省」的比較文件。搜過：Eventhouse consumption、pricing-cost-drivers、Spark billing、Spark capacity planning、Fabric operations、SKU Estimator 頁面 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/pricing-cost-drivers | "This complexity makes it hard to compare pricing across products." |

## 7. 白話結論

1. **Eventhouse 要錢，分兩筆收。** 運算吃 capacity 的 CU（Eventhouse UpTime＝活躍秒數 × vCore 數，COST-16、COST-17）；儲存另外按 GB 收，分 hot cache 和一般儲存兩層（COST-26）。Eventstream 也另外吃 CU，有資料在流就收（COST-29、COST-30）。Real-Time Dashboard 沒有自己的計費項目，它的查詢應該是併在 Eventhouse UpTime 裡（推論，COST-36）。
2. **買 F SKU 的模式下，「耗用 CU」不等於「帳單變多」。** capacity 是按 SKU 付固定費用（pay-as-you-go 按秒，或 reservation 打折），用超過會被 throttle，不會多收錢（COST-3、COST-6）。所以 A、B 的差別主要在「要買多大的 SKU」，加上另計的儲存費。例外：Spark 開 autoscale billing 後，Spark 改成按實際用量另外收錢（COST-44）。
3. **A 和 B 在「資料一直進來」時都會整天耗用。** A：持續寫入的 Eventhouse，UpTime 是 100%（COST-24）；Eventstream 只要兩小時內有資料就持續收 Per Hour 與 Processor 的費用（COST-30）。B：開了 retry 的串流作業會一直跑到手動停止，session 活躍期間都計費（COST-40、推論 COST-42）；每分鐘寫 Lakehouse 還有 OneLake 寫入交易（COST-43）。
4. **兩者唯一的「省錢開關」不同。** A 的 Eventhouse 在沒寫入也沒查詢時會自動暫停、不耗運算（COST-20），但資料持續進來時用不到這個好處；若開 Always-on（Capacity Planner），閒置也照算最低值（預設 2 CU），但免收 hot cache 費（COST-21～COST-23）。B 可開 autoscale billing，讓 Spark 不佔 capacity、只為執行時間付費，但常駐串流本來就一直在執行（COST-45）。
5. **未查到或不確定：**
   - 實際價格（每 CU 小時、OneLake 每 GB 每月、cache 每 GB 每月）：價格頁抓取時顯示 "$-"，**本文不寫任何金額**（COST-15）。要數字請用 SKU Estimator 或 Azure pricing calculator 當場查。
   - 官方沒有 A vs B 哪個比較省的比較或試算（COST-51）。
   - Dashboard 查詢如何計入 Eventhouse 是推論（COST-36）。
   - Eventhouse 的類型兩份文件說法不一：Fabric operations 標為 Background（COST-18），reservation 文件則把 KQL 查詢歸為 interactive、攤平 10 分鐘（COST-5）。這會影響 smoothing 怎麼算，但不影響「有沒有在耗用」的結論。
