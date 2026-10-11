# Part B：`buggy_pipeline.py` 程式碼審查

題目要求：審查一支「由 AI Coding Agent 生成、宣稱已通過測試」的 PySpark 訂單管線，逐項說明 (a) 問題 (b) 業務影響 (c) 修正，最後判斷能不能部署、要求 AI 或工程師怎麼改。

**結論：不可部署。** 找到 11 個問題，其中 5 個 P0（#2、#4、#6、#7、#9）。第一次執行就會丟掉約三分之二的訂單（day1 的 TWD 訂單 3,069 / 4,615 筆），把會員維度表覆寫到只剩有變更的會員，事實表重跑就重複。

## 閱讀順序

| 順序 | 檔案 | 內容 |
|---|---|---|
| 0 | [code-review-overview.html](code-review-overview.html) | **閱讀版**（瀏覽器開啟）。同一份主報告的一頁式精簡版：結論、依步驟排列的問題卡片（diff 可展開）、共同成因、修正順序。標題、示意圖與修正 diff 取自 `code-review.md`，說明文字是精簡改寫，以 Markdown 正本為準 |
| 1 | [code-review.md](code-review.md) | **主報告**。問題總表、照 `main()` 執行順序排列的 11 個問題（每條附示意圖與對照原碼的修正 diff）、修正順序、結論 |
| 2 | [appendix.md](appendix.md) | 審查方法、ruff 與 mypy 的輸出、SCD2 初始載入的做法 |
| 3 | [prod-recovery.md](prod-recovery.md) | 若這支程式已合併並在 prod 跑過，資料怎麼復原 |
| — | [evidence.md](evidence.md) | 報告主要數字與語意判斷的查詢腳本全文與輸出（E1～E13），可自行重跑 |
| — | [future-improvements.md](future-improvements.md) | 〔之後改善〕主報告尚未涵蓋的問題（跨批次亂序、時區、小檔、隔離表寫出、Fabric 部署面）與待修正項目（#5 缺值當 0 在原程式走不到），尚未驗證 |

## 證據怎麼來的

- **不執行原管線**（題目要求）。報告中的筆數是用 Python 標準庫 `csv` 直接讀 `candidate_package/dataset/` 算出「這段邏輯跑下去會影響幾筆」。
- **Spark／Delta 的語意**用本機 pyspark 4.2＋delta-spark 以小資料實測，例如 `dropDuplicates` 後的 window、`replaceWhere` 清表、MERGE 來源重複列。
- **修正 diff 實跑過**：把報告的修正套到程式副本，用 day1 真實資料在全新的本機 lakehouse 跑兩次，fact 都是 4,597 列、`amount_twd` 沒有 null、重跑筆數不變。標「示意」的兩段（#6 的 MERGE 兩步、#11 的 `initial_load_dim_member`）用驗證用的補實作代替。腳本與輸出見 `evidence.md` E13。
- 每個證據的位置，見 `evidence.md` 開頭的「問題編號索引」；問題編號曾經重排，腳本輸出原文保留舊編號，對照表也在同一處。

## 相關文件

- 理解題目時的筆記：[`../notes/part_b/`](../notes/part_b/README.md)（含程式在 OneLake 資料流中的位置）、資料字典 [`../notes/dataset/dictionary.md`](../notes/dataset/dictionary.md)
- 討論中整理的觀念筆記：[`../learning/`](../learning/README.md)（SCD、point-in-time join、MERGE 冪等寫入、取每組最新一筆等）
- 審查過程中 AI 錯在哪、誰發現、怎麼改：[`../ai-collab/process-log.md`](../ai-collab/process-log.md) 的 Part B 事件
