# Process Log

全專案的事件時間軸，依時間由舊到新。紀錄分三層：git commit 記檔案改了什麼，本檔記整個專案中**有意義的事件**（資料發現、方向決策、AI 出錯被抓到、範圍取捨、使用者定案），報告是最終結果文件。檔案層級的細節見 git；Part B 改成本格式之前的逐步紀錄全文保存在 commit `34a4cdd` 的 `ai-collab/process-log-part-b.md`。查詢腳本與輸出原文見 `../part_b/evidence.md`。同一天內的事件順序依 session 訊息時間戳與舊紀錄順序。格式見 `README.md`「process-log.md 事件格式」。

## 2026-10-09｜Part B｜使用者決定先讓 AI 產審查報告初稿，跳過「你先看」
- 經過：AI 依專案規則請使用者先自己讀 `buggy_pipeline.py`，並給了四個檢查問題（重跑會怎樣、哪些列會消失、數字對不對、SCD2 完不完整）。使用者回覆「你應該先產出一份報告我在檢查」，改成 AI 先讀程式碼、用資料量化影響、寫初稿，使用者負責逐條檢查與定稿。AI 在主對話直接讀檔撰寫，沒有派 subagent。
- 誰：使用者決定。
- 依據：session 3b7e0f96；commit `34a4cdd`（舊紀錄 B-01 步驟 0～2）。

## 2026-10-09｜Part B｜用 dataset 量化 buggy_pipeline.py 的問題影響
- 經過：題目要求不執行原管線，AI 改用 Python `csv` 直接讀 `candidate_package/dataset/` 算出每個問題的影響。關鍵發現：fx_rates 只有 JPY、USD，day1 4,615 筆中 3,069 筆 TWD 全部對不到匯率（#1）；day1 有 597 個 order_id（603 列）已存在於 orders_base（#3）；members 8,991 列、8,000 人，989 人有多筆快照，day1 一對多 join 多出 571 列（#4）；day1 有 18 個重複 order_id，其中 3 組連 `order_created_at`、`member_id`、`amount` 都不同（#5）；多快照會員中 `member_level` 變過 434 人（#6）；orders_base 有 50 筆 `amount<=0`（#7）。
- 誰：AI 查詢，執行結果。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`）；`part_b/evidence.md` E1。

## 2026-10-10｜Part B｜建立 dataset 資料字典；AI 第一次統計 amount 用字串比大小
- 經過：使用者沒有先看資料，直接請 AI「先針對dataset寫文件」；AI 提兩個方向問題，使用者選建議選項（範圍只寫資料字典＋Part B 已驗證的事實，完整品質檢核留給 Part A；放在各 Part 共用的位置）。統計時 AI 第一次把 `amount` 當字串比大小，輸出 `min=100129.0 max=99863.0`，結果沒有意義；改成轉 float 重算，文件中的數字都是重算後的值。其他發現：所有檔案都有 BOM；orders_base 100,040 列、100,000 個 order_id；base 的 currency 含 NTD 200 筆；base 的 `order_created_at` 有三種格式；base 有 120 筆 product_id 不在主檔；members 的 (member_id, extract_date) 重複 30 組。
- 誰：使用者決定範圍與位置；字串比大小的錯誤由 AI 自查發現。
- 依據：session 3b7e0f96；commit `b7fe219`（`notes/dataset/dictionary.md`）；`part_b/evidence.md` E9。

## 2026-10-10｜Part B｜AI 錯誤：審查報告把折價券相減誤判為幣別不一致
- 經過：審查報告初稿第 9 點寫「`amount_twd - coupon_discount` 可能幣別不一致，待確認」。這是錯的：`candidate_package/README.md` 欄位說明已明寫 `coupon_discount（TWD）`，相減是對的。AI 寫初稿時沒有先讀 README。修正：刪除該點，後面編號往前遞補，共 12 點。
- 誰：AI 自查（寫資料字典讀 README 時發現）。
- 依據：session 3b7e0f96；commit `ad16fe7`；`candidate_package/README.md`「欄位說明」。

## 2026-10-10｜Part B｜使用者要求：關聯圖改 mermaid、報告先說明程式用途
- 經過：AI 的資料關聯圖原本用 ASCII 畫，使用者要求改成 mermaid，改為 `erDiagram` 並在關係線標出 join key 與兩個陷阱（會員多快照、TWD 沒有匯率）。審查報告初稿一開始就列問題，沒說明這支程式在做什麼，使用者要求先說明用途；報告加一節「這支程式在做什麼」，含 mermaid 流程圖與 6 個步驟的讀寫對照表。
- 誰：使用者提出。
- 依據：session 3b7e0f96；commit `b7fe219`（`notes/dataset/`）、`ad16fe7`（`part_b/code-review.md` 2.1 節）。

## 2026-10-10｜Part B｜AI 錯誤：增量檔 updated_at 範圍寫錯
- 經過：AI 原本寫「增量檔的 `updated_at` 落在批次日當天到其後 3 天內」。重新查詢後發現錯誤：day1 最晚到 07-05（批次日後 4 天），day2 有 6 列早於批次日。改寫成逐日分布表。同一段時間，使用者問「增量檔是不是訂單的 log」，討論後要求把觀察記下來並另開一份檔案，新增「增量檔的性質」（每列是完整快照、出現次數分布、`updated_at` 約 70% 晚於批次日，原因不明，待 Part A 確認）。
- 誰：AI 自查（使用者要求記錄觀察時重新查詢）；記錄觀察與另開檔案是使用者要求。
- 依據：session 3b7e0f96；commit `b7fe219`（`notes/dataset/incremental.md`）；`part_b/evidence.md` E9（day1 `updated_at` 分布 {07-01: 1325, 07-02: 1428, 07-03: 1415, 07-04: 442, 07-05: 5}，晚於批次日 3,290 筆）。

## 2026-10-10｜Part B｜使用者要求：筆記分層多檔，繳交報告改成論文式
- 經過：AI 把理解過程的筆記塞在同一檔（`dataset-notes.md`、`dataset-observations.md`），審查報告又是依嚴重度排列的 12 點條列清單。使用者說明兩種文件要分開：理解問題的筆記分層多檔（先迅速了解一件事 → 問題 → 建議解法），繳交報告是「完整的有結構的文件，類似小論文」，並選了七節大綱。修正：建立 `notes/`（入口 README → dataset/、part_b/ → 細節檔），把解釋過的 SCD2、去重整理成 `notes/part_b/scd2.md`、`dedup.md`，刪除舊的兩個檔案；報告改寫為摘要／背景／方法／發現（4.1～4.5）／修正建議／結論／附錄問題總表，數字沿用。
- 誰：使用者決定文件結構。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`、`notes/part_b/`）、`b7fe219`（`notes/README.md`）。

## 2026-10-10｜Part B｜第一輪驗收：撞號例子自相矛盾、dim 會被清成 0 列、一對多 join 不是隨機、同分快照漏報
- 經過：fresh-context 驗收 agent 審查報告，結論「有條件過」，抓到 AI 初稿的錯誤：(1) #5 用 `ORD00036457`（completed 與 cancelled）當「狀態更新、可能留錯列」的例子，但它是 3 組撞號之一，兩列的 `order_created_at`、`member_id`、`amount` 都不同，與後文「3 組撞號」自相矛盾；其餘 15 組正常重複只有 `updated_at` 不同，改用 `ORD00005192` 舉例。(2) #2 寫「之後每天執行，表只會越縮越小」，實際上每次執行把整張 dim 換成當天有變更的會員，第二次跑 `changed` 為空，dim 會被清成 0 列。(3) #4 寫「`member_level` 會隨機取到新版或舊版」，實際上一對多 join 是每個快照各產生一列，不是擇一。(4) #6 漏報 members 的 (member_id, extract_date) 有 30 組重複，其中 28 組落在最新 `extract_date` 且 `member_level` 不同，`row_number` 同分會任意挑一列。另修：#3 把 order_id 數與列數混用（597 是 order_id 數、485 是列數）；#3 修正前提補上需要 #4、#5 先修；#10 補上第一次執行 dim_member 不存在會直接失敗。
- 誰：驗收 agent 發現；AI 依查詢輸出修正。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`、`notes/part_b/dedup.md`）、`b7fe219`（`notes/dataset/dictionary.md`）；`part_b/evidence.md` E1。

## 2026-10-10｜Part B｜第二輪驗收：#3/#5 對 order_id 判準矛盾、邊界日重複配對
- 經過：第二輪 fresh-context 驗收抓到：(1) #5 以「三欄不同就可能是撞號」為判準，但重算發現 day1 與 base 同 order_id 的 603 列，`order_created_at`、`member_id`、`amount` 沒有一列和 base 相同，照同一判準 #3 的 603 列全都該算撞號，和 #3「既有訂單的更新」互相矛盾。改成有條件的寫法（照官方 README 以 `updated_at` 區分新舊；三欄不一致改為「與官方語意不符的現象，需向上游確認」），order_id 能否當唯一鍵留給 Part A 以 ADR 定案。同時發現 #3 原本寫「新列會落到舊的分區」也錯，`order_date` 相同的只有 9 列。(2) #4 寫 `order_date BETWEEN valid_from AND valid_to`（兩端都包含），而 #6 把舊版 `valid_to` 與新版 `valid_from` 都設成 `extract_date`，快照日當天的訂單會同時對到新舊兩版；統一改成半開區間。(3) #2「清成 0 列」說得太絕對，28 位同分會員可能被重新判定為變更，改成「幾乎清空」。(4) #4 的「多出 571 列」沒註明是用未去重、未丟 TWD 的原始 4,615 列算的，補上另兩種情境（569 列、182～183 列）。(5) #3 的金額重複與狀態統計分開寫。
- 誰：驗收 agent 發現；AI 重算並修正。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`、`notes/part_b/`）、`b7fe219`（`notes/dataset/`）；`part_b/evidence.md` E2（`三欄全同=0`、`order_date 與 base 相同的列=9`、`最新 extract_date 同分會員=28`）。

## 2026-10-10｜Part B｜使用者還原 buggy_pipeline.py，程式碼引用改成函式名＋片段
- 經過：使用者重新排版 `buggy_pipeline.py` 後，報告與筆記裡的行號（`L42`、`L86-118` 等）全部錯位。依使用者「文件不依賴行號」的要求（落成的規則見事件「建立文件系統」），AI 把所有行號改成「函式名稱＋可用 Ctrl+F 搜尋的程式碼片段」，附錄總表「位置」欄改為「函式／片段」，並改掉幾處原本不是原文的引用（例如 `orders.currency == fx.currency` 改為原文 `orders["currency"] == fx["currency"]`）。之後使用者把 `buggy_pipeline.py` 從原始 zip 還原（179 行），還原後片段逐一重新 `grep -F`，都仍搜得到。
- 誰：使用者排版並還原檔案；AI 改寫引用。
- 依據：session 3b7e0f96；commit `ad16fe7`；`grep -nE "\bL[0-9]+"` 在報告與筆記無結果。

## 2026-10-10｜Part B｜第三輪驗收：SCD2 初始載入、ANSI 模式在 Spark 4 會讓管線掛掉
- 經過：第三輪 fresh-context 驗收抓到：(1) #6 修法的 MERGE 每次只拿最新 `extract_date`，沒寫初始載入；dim 從空表開始時舊快照永遠進不了 dim，和「434 人等級變過是 SCD2 該保存的歷史」矛盾，day1 去重後 4,597 張有 49 張（48 位會員）`member_level` 會變成 null。補「初始載入」與第一版 `valid_from` 的三個選擇。(2) #12 只寫「格式一變會被靜默轉成 null」，沒寫隱式轉型的具體後果。派工時預期「ANSI 開啟只有 0.5 這類值會報錯」；AI 用 pyspark 4.2 實跑發現 ANSI 開啟（Spark 4 預設）時 `100.0`、`83.24` 這類帶小數點的字串全部報 `CAST_INVALID_INPUT`，day1 實際檔案也報錯，改寫成「ANSI 關閉時不影響現在的數字，ANSI 開啟時整條管線失敗」。(3) 方法一節還寫「本機沒有 pyspark」，已過時，改為在 `.venv` 用小資料驗證三項語意。(4) #3「重跑一次該日營收翻倍」錯，day1 涵蓋 62 個 `order_date`，一個批次不是一天。
- 誰：驗收 agent 發現 (1)(3)(4) 與 (2) 的缺漏；「只有 0.5 會報錯」是 AI 派工時的預期，被執行結果推翻。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`、`notes/part_b/scd2.md`）、`4f8651c`（pyspark 4.2＋delta-spark）；`part_b/evidence.md` E3～E6（`ansi=true amount='100.0': 錯誤 [CAST_INVALID_INPUT]`、`ansi=true day1: 錯誤 [CAST_INVALID_INPUT]`）。

## 2026-10-10｜Part B｜使用者要求：報告加入 linter、問題總表放最前
- 經過：使用者要求報告加入靜態分析，新增 4.6 節，附 ruff 指令與輸出原文：F841（`main()` 的 `dim_member = update_dim_member(members)` 沒被使用）對應 #4，UP009、I001 只是風格；結論是 linter 只抓到 12 個問題中 1 個的跡象，第 5 節加「CI 跑 ruff」。使用者另要求問題總表從文末附錄移到最前面，改名「問題總表」並附嚴重度定義。
- 誰：使用者提出。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md` 4.6 節、問題總表）；`part_b/evidence.md` E8（`Found 3 errors.`）。

## 2026-10-10｜Part B｜第四輪驗收：同分隔離與「0 張對不到」矛盾
- 經過：第四輪 fresh-context 驗收抓到兩處內部矛盾：(1) #6、#4 寫「照初始載入回填，day1 去重後 0 張對不到」，但同一節的同分隔離規則會讓 28 位同分會員（都只有一個 `extract_date`）永遠進不了 dim，day1 仍有 17 張訂單對不到任何版本；改成「不含被隔離的 28 位同分會員」並交給隔離告警處理。(2) `notes/part_b/scd2.md` 王小明例子，故事寫「6 月升金卡」，表格金卡 `valid_from` 卻是 2026-05-31，與「查 5 月的訂單得到銀卡」矛盾；故事與查詢例子改寫一致。
- 誰：驗收 agent 發現；AI 重算確認。
- 依據：session 3b7e0f96；commit `ad16fe7`（`part_b/code-review.md`、`notes/part_b/scd2.md`）；`part_b/evidence.md` E7（`orders of tie members 17`）。

## 2026-10-10｜全專案｜建立文件系統：筆記分層、報告論文式、三層紀錄
- 經過：使用者在 Part B 過程中陸續提出文件系統的概念：理解問題的筆記分層多檔（先迅速了解一件事 → 問題 → 建議解法），繳交報告是給閱卷者的結果文件（類似小論文）；紀錄分三層粒度，git commit 記檔案改了什麼、process-log 記全專案有意義的事件、報告是結果；文件不引用程式碼行號，改用函式名＋可搜尋的片段。
  AI 把這些概念寫成給 AI 的規則 prompt，全文見 `prompts/doc-system.md`；3 份 memory（含 keep-it-simple）依使用者要求另外記錄，之後使用者要求升級成資料夾，照錄原始檔於 `ai-collab/memory/`。落點是專案 CLAUDE.md 的「紀錄規則」、`ai-collab/README.md` 的「事件格式」、三個專案 skill（`adr`、`review-two-axis`、`to-questionnaire` 的紀錄步驟改成記事件、不寫行號；由驗收 agent 發現它們仍用舊制度後修正），以及 AI 的 memory 檔 feedback-layered-docs、feedback-no-line-numbers（不在 repo 內）。
  依新制度，原本每個交付物照六步驟寫滿一節的 `process-log-part-b.md`（約 500 行）濃縮成本檔的事件；舊檔步驟 3 的查詢腳本與輸出搬到 `part_b/evidence.md`（作為報告證據，數字不改），舊檔刪除，全文保留在 commit `34a4cdd`。
- 誰：使用者核可改動計畫；規則原文由 AI 撰寫；memory 在核可前已寫入；『不引用行號』進 CLAUDE.md 是 AI 依使用者先前的要求自行加入。
- 依據：session 3b7e0f96；CLAUDE.md、ai-collab/README.md、`ai-collab/prompts/doc-system.md`、`ai-collab/memory/`、`.claude/skills/*/SKILL.md`：commit `400e7c8`；時間軸與 evidence.md：commit `a124320`；舊檔全文：commit `34a4cdd`。

## 2026-10-10｜Part B｜〔進行中〕Part B 報告待使用者定稿；#12 嚴重度暫不處理
- 經過：審查報告經四輪 fresh-context 驗收，仍是 AI 初稿（標 `〔AI 初稿，待使用者逐條確認、改寫〕`），待使用者逐條確認並用自己的話定稿。#12 的嚴重度（目前 P2）暫不處理。`notes/dataset/` 也還沒獨立驗收、還沒經使用者定稿。〔待使用者確認〕
- 誰：使用者決定（#12 嚴重度暫不處理）。
- 依據：session 3b7e0f96；`part_b/code-review.md`。
