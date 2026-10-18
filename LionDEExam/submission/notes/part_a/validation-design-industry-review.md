# 讀取驗證層設計：業界評估

使用者擔心 Part A 的讀取驗證層「只是自己的想法，沒有經過驗證」，所以請一個研究 agent 站在資深資料工程師的角度獨立評估，並附來源。本檔整理它的結論。

> 來源連結由研究 agent 查證，主對話沒有逐一打開核對。標「未證實」的是 agent 自己標註的推測。

## 被評估的設計
1. schema 合約只有一份（`contracts.py`），讀取用的 schema 由它自動產生
2. 全部欄位先讀成字串，再由 `cast_to_contract()` 用嚴格 regex 檢查、`try_cast` 轉型
3. 違規分兩層：檔案層級整批停；列層級進隔離表（帶原始字串與原因）
4. 參考資料（產品清單、匯率表）壞一列就整批停
5. 保證「valid＋rejected＝輸入」
6. 值域規則（order_status、currency 允許的值）是否放進合約層

## 總評
**有依據，主體是常見做法，不是反模式。** 「bronze 存字串 → silver 轉型驗證 → 壞列進隔離表 → 對帳」是 Databricks 官方寫明的建議，源頭可追到 Kimball 的 ETL screens 加 error event table。不算主流的只有兩點：**驗證引擎自己寫**、**沒有獨立持久化的 bronze 層**。這兩點是設計取捨，不是錯誤，但要能說出理由。

## 業界對照
| 業界做法 | 和本設計的關係 | 來源 |
|---|---|---|
| Medallion：bronze 存字串、silver 轉型驗證、隔離壞列 | 相同；差在官方的 bronze 會落地成表，本設計讀取當下就驗證 | Databricks 官方原文："Databricks recommends storing most fields as string, VARIANT, or binary to protect against unexpected schema changes"（https://docs.databricks.com/aws/en/lakehouse/medallion） |
| Data Contracts（Andrew Jones、PayPal 模板 → Bitol ODCS） | 精神一致（schema 只有一份）；業界合約是語言中立的 YAML 加跨團隊協議，本設計是程式內常數，比較準確的說法是「合約驅動驗證」 | https://github.com/bitol-io/open-data-contract-standard |
| Great Expectations、Soda、dbt tests | 都把格式、enum、not null 寫成宣告式規則，但主要產生通過率報表，**不會原生把壞列分流到隔離表** | https://docs.getdbt.com/reference/resource-properties/data-tests 、https://docs.soda.io/soda-cl/validity-metrics.html |
| Databricks DLT／Lakeflow expectations（warn／drop／fail） | 對應兩層處理的分工；quarantine 沒有內建。**只有 Databricks 有，Fabric 沒有** | https://docs.databricks.com/aws/en/ldp/expectations |
| Fabric Materialized Lake Views 的 `CHECK ... ON MISMATCH DROP\|FAIL` | 只能丟棄或失敗，沒有隔離表，也不記錄原因 | https://learn.microsoft.com/en-ca/Fabric/data-engineering/materialized-lake-views/data-quality |
| Delta CHECK constraints | 寫入時強制，違規就整筆交易失敗、不分流；適合當最後一道保險 | https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-alter-table-add-constraint |
| Spark CSV 的 PERMISSIVE 與 `_corrupt_record` | 官方明寫欄位數多或少不算 corrupt，判定也會受 column pruning 影響，並建議關掉 `enforceSchema` → **本設計關掉 pruning、自己檢查欄位數，有官方依據** | https://spark.apache.org/docs/latest/sql-data-sources-csv.html |
| Kimball 的 data quality screens＋error event fact table | 隔離表加對帳的源頭 | https://www.kimballgroup.com/?p=19414 |

## 共識與自己加的
| 設計 | 評價 |
|---|---|
| 合約集中、讀取 schema 由合約產生 | 共識 |
| 全部先讀成字串 | 共識（Databricks 官方原文）；實測發現「轉型時會悄悄改值」，正好佐證這個做法 |
| 兩層違規處理 | 共識（對應 expect_or_fail 與 drop／quarantine） |
| valid＋rejected＝輸入 | 共識；多數團隊只做筆數對帳，逐列保證算加分 |
| 參考資料壞一列就整批停 | 有爭議，但站得住：參考資料錯了會汙染下游所有列，符合使用 fail 的條件。反方意見是一筆冷門產品壞掉就擋住整天的資料；常見的折衷是只對關鍵欄位 fail，或沿用上一版參考資料並發出警示（agent 依實務推測，無官方出處） |
| 自寫驗證引擎 | 少見；主流是先用現成工具，工具做不到的部分才自己寫 |
| 用 regex 檢查小數位數 | 少見但有理由；開了 ANSI mode 是否仍會四捨五入，**未證實** |

## 風險與批評
- **效能**：慢 9～49 倍，主要來自 valid 與 rejected 各算一次，加上 regex 檢查；Spark 的固定開銷也會把小資料量下的倍數放大。先把每列的錯誤算成一個陣列欄、persist 後再拆分，估計可以省掉約一半時間（**未實測**）。數千萬列的每日批次多花幾分鐘，業界普遍接受，因為正確性優先於延遲。
- **維護與覆蓋率**：自寫引擎沒有社群幫忙踩坑，每加一種型別都要自己補 regex 和測試。這是最常被批評的一點。
- **重複造輪子**：Fabric 沒有 DLT，MLV constraints 也不支援隔離表，所以自寫在 Fabric 上比在 Databricks 上更站得住，這點值得寫進 ADR。
- **來源換成 SQL DB 後**：上游已經有型別，「先讀字串」的理由大部分消失，regex 層會變成多餘的成本。合約層要能依來源切換驗證策略。
- **沒有 bronze 落地**：重跑完全依賴原始 CSV 還在；CSV 被覆蓋或刪掉，就無法 replay，也無法稽核合格列的原值。

## 值域規則放哪
- **業界主流把 enum 放在合約或 schema 層**，屬於 validity 維度：ODCS 的 `validValues`、dbt 的 `accepted_values`（和 `not_null` 寫在同一份 schema）、Soda 的 `valid values`、Delta CHECK 的 `IN (...)`。
- **狀態機只管轉移合不合法**，因為那要跨列或跨時間比對，屬於業務規則層。
- **代價**：上游新增一個狀態值時，當天那些列會全部進隔離表，所以要做合約版本管理，或對隔離量設警戒門檻。
- 〔使用者判斷〕採用合約層，理由：「值域是 schema 的一部分」。

## 最值得改的三件事（尚未決定是否採用）
1. **補一層持久化的 bronze**：原樣存成全字串 Delta，帶 batch_id、檔名、匯入時間，驗證改從 bronze 讀。代價是多一份儲存；換來可以 replay、可以稽核，也最貼近官方 medallion 慣例。
2. **錯誤只算一次再拆分**：用一個 `_errors` 陣列欄，算一次並 persist。代價是小幅重構；預期能解決大部分效能差距（未實測）。
3. **合約格式對齊 ODCS／datacontract YAML，執行器保留自寫**：代價是多一個依賴，YAML 和程式常數要同步；好處是面談時可以說「規格用標準格式，執行器因為 Fabric 沒有 DLT 而自寫」。

不建議改用 DLT，因為正式環境在 Fabric，用不到。

## 限制
PayPal、GoCardless 的內部實作細節只查到二手來源；Fabric Runtime 的 ANSI 預設值沒有查證。
