# Process Log

全專案的事件時間軸，依時間由舊到新。紀錄分三層：git commit 記檔案改了什麼，本檔記整個專案中**有意義的事件**（資料發現、方向決策、AI 出錯被抓到、範圍取捨、使用者定案），報告是最終結果文件。技術細節與數字見各事件「依據」的 commit 與 `../part_b/evidence.md`；Part B 改成本格式之前的逐步紀錄全文保存在 commit `34a4cdd` 的 `ai-collab/process-log-part-b.md`。格式見 `README.md`「process-log.md 事件格式」。

## 2026-10-09｜Part B｜使用者選擇先讓 AI 產審查報告初稿，再審閱質疑
- 經過：AI 原本請使用者自己先讀 `buggy_pipeline.py`；使用者回覆「你應該先產出一份報告我在檢查」，改由 AI 先讀程式碼、量化影響、寫初稿，預定由使用者逐條審閱並質疑。這正是使用者定義的「你先看」（使用者 2026-10-10 事後澄清：「我先看不代表是我要從0到1 而是先看ai的初稿在從中質疑ai」）。
- 誰：使用者決定。
- 依據：session 3b7e0f96；commit `34a4cdd`（舊紀錄 B-01 步驟 0～2）。

## 2026-10-09｜Part B｜用 dataset 量化 buggy_pipeline.py 的問題影響
- 經過：題目不允許執行原管線，AI 改用 Python 直接讀 `candidate_package/dataset/` 量化每個問題。最關鍵的發現是 fx_rates 沒有 TWD，day1 有三分之二的訂單對不到匯率，以及會員多快照讓 join 一對多膨脹；這些數字讓審查報告的嚴重度有資料依據。
- 誰：AI 查詢，執行結果。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`）；`part_b/evidence.md` E1。

## 2026-10-10｜Part B｜建立 dataset 資料字典；AI 三處錯誤被抓到
- 經過：使用者請 AI 先為 dataset 寫文件，並從 AI 提的選項中選定範圍：只寫資料字典＋Part B 已驗證的事實，完整品質檢核留給 Part A；跟決策有關的發現是 order_id 在 base 就有重複、members 的 (member_id, extract_date) 有重複。使用者審閱初稿時問「增量檔是不是訂單的 log」，要求把觀察另記一份檔案。AI 錯誤一：統計 `amount` 時把字串拿來比大小，得到沒有意義的最小、最大值。AI 錯誤二：審查報告把 `amount_twd - coupon_discount` 誤判為可能幣別不一致，但官方 README 已寫明 `coupon_discount` 是 TWD，AI 寫初稿前沒讀 README。AI 錯誤三：把增量檔 `updated_at` 範圍寫成「批次日起 3 天內」，重查後發現有晚 4 天的、也有早於批次日的。
- 誰：使用者從 AI 提的選項中選定範圍，並提出增量檔問題；三處錯誤皆由 AI 自查發現（寫字典讀 README、依使用者要求重新查詢時）。
- 依據：session 3b7e0f96；commit `b7fe219`（`notes/dataset/`）、`ad16fe7`；`part_b/evidence.md` E9；`candidate_package/README.md`「欄位說明」。

## 2026-10-10｜Part B｜使用者要求：筆記分層多檔，繳交報告改成論文式
- 經過：AI 原本把理解筆記塞在同一檔、審查報告是條列清單；使用者審閱後要求兩者分開：筆記分層多檔，繳交報告是給閱卷者的結構化文件（類似小論文），並選定大綱。同時要求關聯圖改 mermaid、報告先說明這支程式的用途。審閱時使用者也質疑「為什麼可以直接去重」並問「SCD2 是什麼」，AI 的解釋整理成 `notes/part_b/dedup.md`、`scd2.md`。
- 誰：使用者審閱初稿時提出並決定文件結構。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`、`notes/part_b/`）、`b7fe219`（`notes/README.md`、`notes/dataset/`）。

## 2026-10-10｜Part B｜四輪 fresh-context 驗收抓到 AI 初稿的錯誤
- 經過：第一輪抓到 7 個問題（4 個主要、3 個次要），最嚴重的是 AI 把「每次執行都把整張 dim 換成當天有變更的會員、第二次跑幾乎清空」低估成「表會越縮越小」。第二輪抓到 5 個問題，最嚴重的是 #3、#5 對 order_id 的判準互相矛盾，order_id 能否當唯一鍵因此留給 Part A 以 ADR 定案。第三輪抓到 4 個問題，最嚴重的是 SCD2 修法沒寫初始載入；AI 派工時預期「ANSI 模式只有少數值會報錯」，實跑 pyspark 4.2 推翻，ANSI 開啟（Spark 4 預設）時整條管線會失敗。第四輪抓到 2 處內部矛盾，最嚴重的是同分隔離規則與「0 張對不到」的說法衝突。
- 誰：驗收 agent 發現；ANSI 的錯誤預期由執行結果推翻；AI 依查詢輸出修正。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`、`notes/part_b/`）、`b7fe219`（`notes/dataset/`）、`4f8651c`（pyspark 4.2＋delta-spark）；`part_b/evidence.md` E1～E7。

## 2026-10-10｜Part B｜使用者要求：報告加入 linter、問題總表放最前
- 經過：使用者要求報告加入靜態分析；ruff 只抓到 12 個問題中 1 個的跡象，說明這類邏輯錯誤靠 linter 抓不到。使用者另要求問題總表移到報告最前面。
- 誰：使用者提出。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md` 4.6 節、問題總表）；`part_b/evidence.md` E8。

## 2026-10-10｜全專案｜建立文件系統：筆記分層、報告論文式、三層紀錄、不引用行號
- 經過：使用者在 Part B 過程中陸續提出文件系統的概念（筆記分層、報告論文式、紀錄分三層、文件不引用行號），起因之一是使用者重新排版 `buggy_pipeline.py` 後行號全部錯位，AI 改成函式名＋可搜尋片段，過程中也發現 AI 先前引用的幾處「程式碼片段」並非原文（例如把 `orders["currency"] == fx["currency"]` 寫成 `orders.currency == fx.currency`），一併改回原文。AI 把這些概念寫成規則，落到 CLAUDE.md、`ai-collab/README.md`、三個專案 skill 與 memory；skill 仍用舊制度是驗收 agent 發現的。舊的逐步紀錄依新制度濃縮成本檔，查詢證據搬到 `part_b/evidence.md`。
- 誰：使用者提出概念並核可改動計畫；規則原文由 AI 撰寫；memory 在核可前已寫入；「不引用行號」進 CLAUDE.md 是 AI 依使用者先前的要求自行加入。
- 依據：session 3b7e0f96；行號改寫：commit `ad16fe7`；規則、`ai-collab/prompts/doc-system.md`、`ai-collab/memory/`、skills：commit `400e7c8`；時間軸與 evidence.md：commit `a124320`；舊檔全文：commit `34a4cdd`。

## 2026-10-10｜Part B｜〔進行中〕Part B 報告待使用者定稿；#12 嚴重度暫不處理
- 經過：審查報告經四輪驗收仍是 AI 初稿，待使用者逐條確認並用自己的話定稿；#12 的嚴重度（目前 P2）暫不處理。`notes/dataset/` 也還沒獨立驗收、還沒經使用者定稿。〔待使用者確認〕
- 誰：使用者決定（#12 嚴重度暫不處理）。
- 依據：session 3b7e0f96；`part_b/code-review.md`。
