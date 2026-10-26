# ADR-06｜bronze／silver 用 Lakehouse，gold 放 Warehouse
- 狀態：已定案（2026-10-26，使用者指示 AI 代改：「你幫我」）
- Part：C
- 關聯：process-log「Q3 gold 放 Warehouse」；素材見 `notes/part_c/tentative-decisions.md`「Q3」、`notes/part_c/process.md`

## 背景
題目 Part C 要在 Microsoft Fabric 上同時支撐每日 Power BI 報表、分鐘級即時儀表板、Text-to-SQL 問數。批次層（bronze／silver／gold）要放在 Lakehouse 還是 Warehouse，會決定寫入用哪個引擎、Part A 的程式能不能直接沿用。

Part A 的事實（`notes/part_c/part-a-evidence.md`）：
- 管線是 PySpark＋Delta，選它的理由就是「正式環境在 Fabric，用 Spark＋Delta 之後不用重寫」（ADR-01）
- 冪等靠「每批以 batch_id replaceWhere 寫隔離表＋MERGE 寫 fact＋重跑時 time travel 讀這批寫入前的 fact 版本」（ADR-05，`batch_log.py` 的 `pin_fact_version`），不靠多表交易
- 每批寫入前先對帳「輸入＝寫進 fact＋隔離＋略過」，不平就報錯，不寫入（E15）

Fabric 的事實（`notes/part_c/fabric-facts.md`）：
- Lakehouse 的 SQL analytics endpoint 是唯讀，T-SQL 只能建 view、函式、管權限，不能改資料（F4-1）；寫入要用 Spark
- Warehouse 支援完整 T-SQL DDL／DML 與多表 ACID 交易（F4-2、F4-4），但鎖是表層級，兩個交易改同一張表的不同列也會衝突，要 retry（F4-5）
- 兩者底層都存成 Delta（F4-3），Direct Lake 兩者都能接（F5-2）
- Lakehouse 寫入後同步到 SQL endpoint 有延遲，正常 1 分鐘內（F4-6）

## 選項
| 選項 | 好處 | 代價 |
|---|---|---|
| A. 全 Lakehouse（Spark 寫入，SQL endpoint 給查詢） | Part A 程式、冪等機制、time travel 重跑直接沿用；一種寫入引擎 | 不能用 T-SQL 寫入；SQL endpoint 同步有延遲（F4-6），批次剛寫完的幾秒到幾分鐘內查到的可能是舊的；Delta time travel 在 Fabric 上未實測（ADR-05 後果） |
| B. bronze／silver 用 Lakehouse，gold 放 Warehouse | gold 可以用 T-SQL 寫入與多表交易；下游營運人員能在 Warehouse 用 SQL 建自己的衍生表（讀 gold、不改 gold） | 兩套寫入引擎；Part A 的 MERGE 要改寫成 T-SQL；ADR-05 的重跑機制要重新設計；表層級鎖（F4-5）讓同一張表的並行批次要錯開 |
| C. 全 Warehouse | 一律 T-SQL，權限與交易語意一致 | Part A 的 PySpark 管線全部重寫，等於否定 ADR-01 的理由；撞號、狀態機這類逐列判斷用 T-SQL 寫較難測試 |

## 決定〔使用者撰寫〕
B：bronze／silver 用 Lakehouse，gold 放 Warehouse。（使用者 2026-10-26 在對話中選定；狀態已於 2026-10-26 改為已定案）

（先前 AI 暫定：A 全 Lakehouse）

## 理由〔使用者撰寫〕
使用者原話：「B 對下游營運來說只需要學sql」

補充（同日，回應 AI 疑點後）：「維持B，下游用SQL建自己的衍生表」。AI 指出兩點後使用者維持 B：(1) Lakehouse 的 SQL endpoint 也能讓下游用 SQL 讀（F4-1）；(2) 下游手動改 gold 會破壞管線（狀態機以 fact 現況比對、MERGE 會蓋掉手動修正、重算會抹掉修改），所以 gold 對下游唯讀，B 的價值是下游能在 Warehouse 用 SQL 建自己的衍生表

（先前 AI 暫定的理由草稿，保留對照）〔AI 原草稿，已被上方定案取代〕AI 暫定的理由草稿（使用者要改寫成自己的話）：Warehouse 的主要優勢是多表交易，但 Part A 的正確性不靠多表交易，而是每批冪等寫入加 time travel 重跑；換 Warehouse 要重寫已經驗證過的管線，換不到需要的東西。

## 後果
- 選 A：
  - `part_a/pipeline/` 的程式搬上 Fabric Notebook 或 Spark Job Definition，主要改路徑與表名（`learning/0-storage/microsoft-fabric.md`「最小範例」）
  - 問數與報表都透過 SQL endpoint 或 Direct Lake 讀，口徑寫成實體表 `gold_order_metrics`（不用 SQL view，因為 Direct Lake 遇到 view 會退回 DirectQuery，F5-5），見 ADR-08
  - 每日批次寫完後，semantic model 要等寫完再 refresh（F5-4：可關掉自動 framing，改由管線最後一步觸發），避免報表看到半套資料
  - 要在 Fabric 上實測 time travel 與 VACUUM 保留期（ADR-05 標「未實測」）
- 選 B（使用者 2026-10-26 選定）：
  - **改動範圍**（使用者要求記錄）：要改的主要是 `merge_upsert` 這一個函式的四個呼叫點（`load_order_batch` 寫 `fact_order`、`write_dim_member`、`write_dim_product`、`write_dim_date`），改成用 T-SQL 寫入 Warehouse。這是 AI 讀程式後的估計，未實作驗證
  - **未查證**：ADR-05 的重跑靠 `_fact_before_batch` 用 Delta time travel 讀「這批寫入前」的 fact；改到 Warehouse 後這個做法能否沿用，沒有查官方文件
  - **未查證**：Spark 管線怎麼把資料寫進 Warehouse（直接寫，或先寫 Lakehouse 暫存表再用 T-SQL MERGE 進 Warehouse），沒有查官方文件
  - Warehouse 是表層級鎖（F4-5），同一張表的並行寫入會衝突，同一張表的批次要錯開或加重試
  - Part C 新增的 `gold_order_metrics` 也放 Warehouse
  - **gold 對下游唯讀**：只有管線寫 gold；下游在 Warehouse 另建自己的衍生表，讀 gold、不改 gold。資料要修正就回上游或寫成管線規則（例如 `amount_review`）
  - **權限要重新設計**（Q8 已處理：先只做表層級，問數用服務帳號，見 README 6.3）：原本的權限設計（README 6.3）建立在 Lakehouse 的 OneLake security 上；Warehouse 的 SQL 列權限只在 SQL 連線時生效（F8-10），Direct Lake on OneLake 不套用 SQL 列權限（F5-7）
- 選 C：要重寫 ADR-05 的重跑機制，Part A 的冪等證明（`profiling/idempotency_proof.py`）不能沿用
