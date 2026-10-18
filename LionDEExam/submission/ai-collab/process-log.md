# Process Log

這份紀錄記**使用者的思考過程**：當時質疑什麼、為什麼這樣決定、方向怎麼轉變。時間軸不求嚴謹，AI 做了哪些改動交給 git commit，完整對話在 `transcripts/`，最終結果在各 Part 報告。本檔依工作內容分成幾個部分，每部分內大致依時間排列，不同部分在時間上可能交錯。Part B 改成事件格式之前的逐步紀錄全文保存在 commit `34a4cdd` 的 `ai-collab/process-log-part-b.md`；格式見 `README.md`「process-log.md 事件格式」。

## 第一部分：建立文件系統

建立這個系統的動機，用使用者的話說：「我們目前花了一些時間建立建系統來框住整了ai的產出」。目的是讓每份產出都能追溯、使用者比 AI 更懂每個結論，附帶把學到的內化成 DE 能力。文件依用途分四種：

| 用途 | 給誰 | 文件 |
|---|---|---|
| 結果 | 閱卷者 | 各 Part 報告（論文式）、一頁 AI 協作報告 |
| 理解 | 使用者 | `notes/` 放這一題的資料與程式；`learning/` 放可帶走的 DE 觀念地圖與筆記。換專案用不到的放 notes，用得到的放 learning |
| 紀錄 | 追溯 | process-log 記使用者的思考過程，git commit 記檔案改動並帶 `Session:`，transcripts 是完整對話，粒度由粗到細 |
| 規則來源 | AI 與閱卷者 | CLAUDE.md、`prompts/`（規則、skills 副本）、`memory/` |

運作方式是 AI 先出初稿 → 使用者審閱質疑 → 拆解委派 → fresh-context 驗收 → 修正 → 使用者定案。追溯路徑是報告 → 事件 → commit → 對話。文件不引用行號、結論附執行證據、AI 的錯誤照實記。

### 2026-10-10｜全專案｜筆記要分層，報告要像小論文

審閱 Part B 初稿時，使用者發現 AI 把理解筆記全塞在同一個檔、報告寫成條列清單。他把兩種文件分開想。理解問題的筆記應該「先讓人針對一件事情迅速了解，再慢慢讓人了解目前遇到的問題，以及建議的解決方式。好的文件系統不會把所有內容放在同一個檔案中」；繳交的報告則是「完整的有結構的文件，類似小論文」。大綱由他從 AI 的提案中選定。

- 依據：commit `ad16fe7`、`b7fe219`

### 2026-10-10｜全專案｜文件不該依賴行號

使用者把 `buggy_pipeline.py` 重新排版（一行拆兩行）之後，報告裡的行號全部錯位，連驗收 agent 都以為是報告寫錯。他的結論是：「文件應該要對行號不依賴，使用其他方式來紀錄變動性很高的行號。」AI 之後改用「函式名＋可搜尋片段」，並自行把這條寫進 CLAUDE.md。

- 依據：commit `ad16fe7`、`400e7c8`

### 2026-10-10｜全專案｜紀錄分三層，process-log 改成時間軸

原本的 process-log 照六步驟逐節記，越寫越長。使用者提出把紀錄拆成三層，各管各的：git commit 記檔案改了什麼、process-log 只記有意義的事件、報告是給閱卷者的結果。他核可了改動計畫，規則原文由 AI 撰寫，收進 `prompts/doc-system.md`；AI 在使用者核可前就先寫入了 memory。AI 改規則時漏了三個 skill 沒同步，它們原本還在用舊的 `<P>-NN`、六步驟紀錄，由驗收 agent 抓到。

- 依據：commit `400e7c8`、`a124320`、`231e284`；`memory/feedback-keep-it-simple.md`

### 2026-10-10｜全專案｜「你先看」是先看 AI 的初稿，不是自己從零做

CLAUDE.md 原本把步驟 0 寫成「交給 AI 前，使用者先自己看資料」。使用者澄清自己的意思：「我先看不代表是我要從0到1 而是先看ai的初稿在從中質疑ai」。他的工作方式是讓 AI 先把初稿做出來，自己的價值放在審閱與質疑上；這其實在 Part B 一開始就是這樣做的（見第二部分第一個事件）。規則因此改成 AI 出初稿後主動列出值得質疑的地方，process-log 也同時精簡成只記發生什麼、為什麼重要。

- 依據：commit `560d3d1`

### 2026-10-10｜全專案｜想把觀念內化成自己的能力：teach 改成 concept-note

使用者想藉這個專案把觀念內化成自己的 SWE 能力，先請 AI 參考 Matt Pocock 的 teach skill。看過 AI 改寫出來的 teach（mission、課綱、學習紀錄、測驗的多 session 流程）之後，他發現那不是自己要的，描述了更輕的方式：在討論中問 AI 哪些觀念值得記，AI 給選項，他選了之後寫一份簡短筆記，偏向套件用法、SQL 這類能帶到其他專案的技能。學習內容放進 repo 的 `learning/`、用 Markdown，也是他決定的。

- 依據：commit `8b09ff9`、`33ba9d5`

### 2026-10-10｜全專案｜筆記該放 notes 還是 learning：看換專案用不用得到

寫了 4 份觀念筆記（SCD 名詞、取每組最新一筆、MERGE 冪等寫入、point-in-time join）之後，SCD 的內容同時出現在 `notes/` 和 `learning/`。歸位的規則是使用者同意的：換專案就用不到的（這一題的錯誤）放 notes，換專案還用得到的（通用概念）放 learning。

- 依據：commit `4d91ce3`、`c4144d6`

### 2026-10-10｜全專案｜learning 改成 bottom-up 的 DE 觀念地圖

learning 從一份份筆記改成一張觀念地圖。AI 提了幾種做法，使用者選「題目＋業界通用」的範圍，並決定「先以 bottom up 為主」：只收本專案真的碰過的觀念，再借《Fundamentals of Data Engineering》的分類掛上去，而不是先畫一張完整地圖再回頭填。驗收時抓到 AI 把晚到資料的定義寫錯：原本寫成更新時間晚於或早於批次日都算晚到資料。

- 依據：commit `c802584`；session 3b7e0f96

### 2026-10-10｜全專案｜先把文件系統記下來，再進入 Part B

使用者判斷文件系統已經建立得差不多，想先把這段過程記成 process-log 的第一部分，之後才正式進入 Part B，所以整份 process-log 重寫，兩部分都保留。改寫途中他在同一則訊息說「因此我們在工作時 要有意識提醒我更新文建」和「timeline可以不用那麼嚴謹 主要是紀錄我的思考過程」：CLAUDE.md 因此新增「AI 主動提醒更新文件」這條規則，紀錄的重心也從 AI 做了什麼，轉成他當時怎麼想。

- 依據：commit `1f35442`

## 第二部分：Part B 程式碼審查

目前停在兩步：AI 產出審查報告初稿；使用者為 dataset 寫文件，用來理解並質疑報告。報告的修改細節（四輪驗收、linter、格式調整）記在 git，這裡不展開。

### 2026-10-09｜Part B｜先讓 AI 產初稿，我再來檢查

AI 原本請使用者自己先讀 `buggy_pipeline.py`。使用者回：「你應該先產出一份報告我在檢查」，選擇讓 AI 先讀程式碼、用資料量化影響、寫初稿，自己負責審閱並質疑。初稿之後經過四輪 fresh-context 驗收修正，每輪都抓到 AI 的錯（例如低估 dim 表會被清空、ANSI 影響被實跑推翻）。

- 依據：commit `ad16fe7`、`34a4cdd`；`part_b/evidence.md`

### 2026-10-10｜Part B｜為 dataset 寫文件，用來理解報告

為了看懂報告，使用者請 AI 先為 dataset 寫文件，範圍從 AI 的選項中選定（只寫資料字典，品質檢核留給 Part A）。審閱時提出的理解問題（增量檔是不是 log、為什麼不能直接去重、SCD2 是什麼），答案整理在 `notes/` 和 `learning/`。過程中 AI 自查出錯：把字串型的 `amount` 拿來比大小、沒讀 README 就誤判 `coupon_discount` 的幣別。

- 依據：commit `b7fe219`、`c4144d6`

### 2026-10-10｜Part B｜審閱前先補 DE 基礎：從「MERGE 能不能復原」問到 lakehouse 是什麼

開始審閱時，使用者先要求問題總表「先簡述問題不列出片段」，接著借單向門／雙向門的概念，問修正後的 MERGE 是否能完整復原。AI 的回答用到 Delta 表、time travel、VACUUM，他發現自己缺背景，於是一路往下問：dim 和 fact 是不是新的資料集、Delta 表是什麼、為什麼資料是檔案，並要求「把我當作DE小白重新說明」、「我需要最基礎的理解」。答案整理成兩份 learning 筆記（data lake／warehouse／lakehouse、星型模型）。他用自己的話確認理解，例如「lakehose可以理解成lake + changelog是嗎」、「B就是把sql db的資料搬進warehose是嗎」；AI 回答時修正了細節（Delta 的 log 記的是檔案不是逐列變更；目的地是 lakehouse，來源是不是 SQL DB 只是推測），後一個問題的資料流圖由他要求補進報告 2.1 節。

驗收 agent 這段抓到 AI 多處錯誤，例如：把 Snowflake、BigQuery 當成「儲存與運算綁在一起」的例子；流程圖說明寫「程式只讀 landing 的 CSV」，漏了它會讀回既有的 dim 表；星型筆記把 order_id 的官方語意寫成定論，而報告刻意留給 Part A 的 ADR；把星系寫成星型的替代選項；說 Delta 並行寫入衝突時會自動重試，實際上有衝突會丟例外。MERGE 可復原性的質疑帶出「#2 補上 VACUUM 前提」與「第 5 節補原始檔保留」兩個修改提案，尚待使用者決定。

- 依據：commit `2afc5cb`、`83ccac2`、`4a14b0f`、`8dc5453`、`87f3788`

### 2026-10-10｜Part B｜prod 復原：「delta不是有版控的檔案嗎」讓修法改成 RESTORE 優先

使用者要報告說明「這個pipline pr被接受後如何在prod 復原資料錯誤的問題」，5.3 因此改寫成 prod 復原。AI 的版本把 fact 寫成「修補不可行，只能從原始檔重建」，只有 dim 提到 RESTORE。使用者問「delta不是有版控的檔案嗎」，指出 fact 一樣是 Delta 表、一樣能退版。AI 因此把修法改成 RESTORE 回 bug 之前的乾淨版本再重播增量優先，退不回去才從原始檔重建；RESTORE 還有一個從零重建做不到的好處：程式從沒讀過 `orders_base`，bug 上線前 fact 裡已有的歷史只有 RESTORE 保得住。RESTORE、VACUUM 的行為用本機 delta-spark 實測（E10），先前提的「#2 補 VACUUM 前提」也一併寫進報告。

驗收 agent 這段抓到 AI 的推論寫成定論：「bug 上線一週內沒發現就退不回去」只在有排程 VACUUM 時成立（開源 Delta 不會自動 VACUUM）；復原步驟沒寫清楚 dim 要先於 fact 修好；表格漏了 #6；沒交代 ANSI 開啟時 prod 的狀態不同（dim 已被覆寫、fact 根本沒寫入）。

- 依據：commit `fbf92f4`；`part_b/evidence.md` E10

### 2026-10-11｜Part B｜報告改版：主檔只講問題與修法，照程式流程排

使用者認為「code reivew應該要拆成多分檔案 主軸要是讓對方理解code的問題 以及怎麼修改 其他讓我理解的內容拆成其他檔案」。AI 提出拆法：方法與 linter 進附錄、prod 復原獨立一份、資料流背景移到 notes，使用者同意。之後他再問「還可以在簡化嗎」，接著提出「SCD2 實作可以寫成一個問題吧 如果都要一起修」，以及「我想大改成用流程順序來說明」。中間 AI 把「放在一起」理解成三種可能，回頭確認，他的答案是「11個問題放在同一個 但其他輔助個分出去」。第 4 節因此照 `main()` 的 6 個步驟重排，舊 #2、#6 合併成新 #6，編號改成 #1～#11；evidence 的腳本輸出保留舊編號，文首加對照表。照流程排的理由（使用者原話）：「照流程符合閱讀code的思考邏輯」。

驗收 agent 抓到 AI 自己建議的簡化刪過頭：#6 刪掉「dataset 的 city 沒有 null、缺值用 `N/A`」的旁註後，讀者會以為現有資料真的會因為 null 漏掉變更，於是補回一句短的限定。

- 依據：commit `4118132`

### 2026-10-11｜Part B｜用 show-me 改成「圖＋diff」，驗收實跑才發現修法照貼跑不起來

使用者問 AI「你有嘗試使用show me來說明嗎」，接著要求「使用show me的想法說明 問題跟寫文件」。AI 先改 #4 當樣本，使用者看過後說「照這個格式改全部」：每條改成一兩句說明加一張示意圖，修正改成對照原碼的 diff。

驗收 agent 把全部 diff 套到程式副本、用 day1 實跑，三輪才通過。抓到的錯誤：
- AI 自己寫的 #4 樣本沒刪掉原本的 UDF 那行，left join 後 TWD 的匯率是 null，UDF 報 `TypeError`；縮排也和原碼不同。
- #5 改成內建乘法後，沒有 schema 時金額是字串，ANSI 開啟下直接報型別錯誤。修法是兩邊都明確 cast 成 decimal（E12）。
- #6 的 diff 照貼會出現 NameError；#10 的對帳和 #4、#8 的隔離對不上（隔離列沒有從主流程拿掉）；第一次執行時 fact 表不存在，MERGE 會失敗；MERGE 要用的 `updated_at` 沒進 fact。

同一段時間，使用者要求「在多跑一個mypy」。結果是 11 個問題 mypy 一個都抓不到。AI 寫「函式都沒有型別標註，所以 mypy 沒看」，驗收 agent 指出 `load_sources`、`main` 有參數標註，mypy 有檢查，只是型別上全都是 `DataFrame`。

- 依據：commit `4118132`；`part_b/evidence.md` E8、E12

### 2026-10-11｜Part B｜實測推翻舊版報告的兩個技術說法

上面的改寫過程中，有兩個從舊版報告就存在的錯誤被實測推翻：
- **`mode("FAILFAST")`**：舊版 #12（現在的 #1）寫 `spark.read....mode("FAILFAST")`，但 DataFrameReader 沒有 `mode` 方法（`hasattr` 為 False），正確寫法是 `.option("mode", "FAILFAST")`。由改寫的 subagent 發現，驗收 agent 確認。
- **「MERGE 的來源若同一個 key 有多列會直接報錯」**：驗收 agent 用 delta-spark 實測，只有對到 target 既有列時才報 `DELTA_MULTIPLE_SOURCE_ROW_MATCHING_TARGET_ROW_IN_MERGE`；target 沒有的 key 在來源重複，會**靜默插入多列**，風險比原本寫的更大。報告 #9、5.1 和 `learning/merge-idempotent-write.md` 都已更正。

- 依據：commit `4118132`；`part_b/evidence.md` E12

### 2026-10-11｜Part B｜「負數？？」：base 的負數金額不是退款

使用者要求看 amount 的分布，AI 整理時寫「base 有 50 筆負數」，報告 #3 (b) 也寫「退款不會沖銷營收」，把負數當成退款。使用者看到筆記後問「負數？？」。AI 實際查了這 50 列：狀態以 paid、completed 為主，同 order_id 沒有對應的正數原單，取絕對值後是正常金額，官方 README 也沒有退款狀態。結論是「負數 = 退款」沒有依據，比較像正負號錯誤（未查證），留給 A-3。同一次整理也發現 base 有 40 筆極端大值，除以 1,000 後全部回到正常範圍，疑似多乘了 1,000（未查證），一併留給 A-3。#3 的改寫方向由使用者決定：「不要以退款為方向說明 可以朝向 為什麼出現負數 如果schema有限制大於零 需要開卡debug為什麼會出現」。#3 因此改成：`amount > 0` 是資料契約，違反就隔離、告警、開卡追上游，不再用退款舉例。

- 依據：`part_b/evidence.md` E9（負數調查）；commit `4118132`

### 2026-10-11｜Part B｜閱讀版 HTML 與資深 DE 角色審查

使用者認為報告「基本上沒問題了」，要求「用一個DE的agent review一次 並在主agent產生html」。HTML 的方向經過幾次修正：AI 先用 pandoc 把 Markdown 原文直接轉成 HTML，使用者說明要的是「排版好看能看完整敘事的html」、「我不要直接原文轉html」；AI 改成問題卡片版後，他認為「html的敘事性要更好一點 不能直接照md般」；AI 改寫成依資料流逐站敘事的版本，他又指出「ai口吻太強」，最後改成平實的審查口吻定稿（「就這樣吧」）。AI 把產生 HTML 的腳本放進 `part_b/`，使用者問「怎麼有py」，腳本移出繳交物。

錯誤與修正：AI 寫敘事時把「66.5% 的訂單」寫成「營收少掉三分之二」，自查改回訂單筆數（營收比例沒算過）。驗收 agent 抓到 README 把閱讀版說成「逐字取自報告」（實際是精簡改寫），以及精簡時漏掉的限定：#7 的 571 列是上限（182～571）、#2 的 3 組不一致重複要先隔離、#5 的缺值當 0。README 宣稱「修正 diff 實跑過」，但實跑只在 /tmp，驗收 agent 指出繳交物裡沒有依據，因此補成 `evidence.md` E13。

資深 DE 角色審查（面試官視角）的結論是報告水準在多數候選人之上，但指出站不住的判斷（#5 的 null 當 0 在原程式走不到、#2 依自訂定義應為 P1）、漏抓（跨批次亂序、時區）與修法停在示意（#6 SCD2）。如何處理尚待使用者決定。

- 依據：commit `7aee71b`；`part_b/evidence.md` E13

### 2026-10-11｜Part B｜整理 DE 審查結果：漏抓的項目列為之後改善，小檔問題改看 prod 資料量

使用者問「怎麼理解審查結果」。AI 把資深 DE 角色審查的意見分成三類：A 報告寫錯（例如 #5 的 null 當 0 在原程式走不到）、B 判斷和自訂標準不一致（例如 #2 依定義應為 P1）、C 報告沒寫到（跨批次亂序、時區、分區小檔、隔離表沒寫出、Fabric 部署面）。使用者決定「C幫我整理一份文件標記成之後改善」，整理成 `part_b/future-improvements.md`，每項標明哪些數字是審查 agent 自己實測、尚未重跑。

使用者質疑 F3（依 `order_date` 分區產生小檔）：「可能只是demo的數量 prod可能不是這樣」。審查 agent 的結論是從題目資料一天約 4.6k 列推出來的；檔案小不小取決於每個分區每次寫入的量，demo 資料判斷不了。F3 因此改成「待取得 prod 資料量再評估」，並區分出與資料量無關的部分（每批碰到幾個分區，取決於舊訂單更新分散在幾個日期）。之後使用者要求「A也紀錄好了」，A 類（#5 的缺值當 0 在原程式走不到）以 A1 列入同一份文件，待驗證後修正；B 類使用者決定「B先不管」，暫不處理。

- 依據：commit `0ff4d83`；`part_b/future-improvements.md`

### 2026-10-11｜Part B｜定稿：以對話中的逐項審閱為定稿依據

AI 提議另做一份逐條確認清單讓使用者勾選定稿，使用者認為不需要：「我已經在對話中review產出了 不用再有確認清單」。Part B 的定稿依據就是本部分各事件記錄的審閱過程（質疑 merge 後能否復原、RESTORE、負數金額、照流程重排、show-me 改寫、406＋28、閱讀版 HTML 等）。資深 DE 角色審查指出、尚未處理的項目列在 `part_b/future-improvements.md`（A1、F1～F5）；B 類判斷不一致的項目使用者決定暫不處理。原 #12（現 #1）的嚴重度維持 P2。

- 依據：commit `61dbb3f`

## 第三部分：Part A 資料倉建置

範圍：題目 Part A（A-1 模型設計、A-2 增量與冪等、A-3 資料品質）。開工前先依派工草稿 `.claude/work/part-a-prompt.md` 的「需要使用者決定的事」逐題對齊。

### 2026-10-14｜Part A｜Part A 執行引擎選 PySpark＋Delta

AI 建議 DuckDB（閱卷者不需要 Java 就能跑、資料量小），使用者選 PySpark＋Delta：「是給生產環境的 也查過雄獅旅遊的規模」，並要求把三個選項都寫進 ADR。AI 的 ADR 初稿在 B 的代價寫「資料量用不到分散式運算」，使用者指出「csv是demo資料 不能當作prod的資料量」；ADR 改為標明這只是 demo 資料量。見 ADR-01。

- 依據：commit `49b89db`；ADR-01

### 2026-10-14｜Part A｜管線以抽象來源設計，品質規則寫成 schema 合約

對齊時使用者提出「這個pipline應該要可遷移」，也想「從sql db schema解決一些資料品質的問題」：題目給 CSV，但現實中的源頭是營運 SQL DB。AI 列了兩個方向：來源抽成介面（CSV 與 SQL 兩種實作回傳同一個 schema）並把品質規則寫成 Delta 表上的約束；或真的用 docker-compose 架 Postgres、CSV 灌進去再用 JDBC 讀。AI 也提醒 schema 只能擋、不能修（例如多乘 1,000 的金額仍然大於 0）。使用者選前者：「也不用真的架db 這提應該要讓我以抽象設計的方式解決」。見 ADR-02。

- 依據：commit `49b89db`；ADR-02

### 2026-10-14｜Part A｜AI 的 schema 推測只當輔助，規劃由使用者自己做

AI 派 agent 從 CSV 推測原始 SQL schema，產出違反清單與 8 個待判斷問題（J1～J8），並提議借用逆向工程工具 REA「從觀察反推、附證據與信心」的概念，把 noise 對成「出題者想考的能力」清單。使用者決定：「我想推測只當作輔助就好 我要自己規劃」。

- 依據：commit `1a3ce9f`；`notes/part_a/schema-inference/`

### 2026-10-14｜Part A｜schema 推測報告三輪驗收抓到的錯

AI 派 agent 用 PySpark 逐檔逐欄剖析 CSV、推測原始 schema（`notes/part_a/schema-inference/`），再派 fresh-context agent 用純 Python 獨立重算驗收，三輪才通過。驗收 agent 抓到的錯：
- 報告寫會員生日「只會從 1900-01-01 補成真實日期」，實際 19 人中有 5 人是真實日期被改成 1900；照原說法設計 SCD2 會被誤導。
- 證明「`Z` 結尾是 UTC」的測試方向用反（加 8 小時只能否證另一種格式），改以 base 重複列中不同格式字串解析為同一時刻為證據。
- 報告把 day1→day2 的 25 個 order_id 寫成「正常的狀態更新」，實際是 day1 cancelled、day2 送來較舊的 paid；照檔案順序取最新會把已取消的訂單改回已付款。
- 一條前提尚未由使用者判斷的違反被列為「確定的 noise」，移回需判斷。

同一份剖析也發現 AI 先前寫的 `notes/dataset/dictionary.md` 把產品價格範圍算成 10,000～99,000，是字串比大小的錯誤，正確是 3,000～199,000。這是 AI 第二次犯同類錯（第一次是 Part B 統計 amount，見 `part_b/evidence.md` E9 的「AI 自查」）。之後使用者問「dictionary.md 那個錯」，原意是問錯在哪，AI 誤解成要修正，直接改了 dictionary.md 並 commit（`83c58df`，經獨立重算確認數字正確）；使用者看過說明後決定保留。

- 依據：commit `1a3ce9f`；`notes/part_a/schema-inference/`、`part_a/profiling/profile_sources.py`

### 2026-10-17｜Part A｜逐欄比對推翻「45 組是乾淨的狀態更新」

使用者認為 schema 推測報告「是一個不錯的觀察 但呈現方式不便於理解」，要求拆成分層筆記（`notes/part_a/schema-inference/`），之後又指出句中的證據標籤「這種描述比較難懂」，改成段末證據行。改寫過程中，驗收 agent 抓到「只改狀態」這個說法沒有證據：原報告寫增量同檔重複的 45 組是「乾淨的狀態更新」，但當時的查詢只檢查會員、金額、下單時間、產品四欄一致，沒查狀態。AI 先改措辭兩次仍被驗收退回（其中一次是 AI 在派工範例裡自己寫了「只有狀態在變」），依「同一修法連錯兩次就停」改成補查詢：逐欄比對三類重複組。結果 45 組連狀態都相同，只差 `updated_at`，是同狀態重送；資料裡同一張單、狀態真的有變的只有 day1→day2 的 25 組（就是 cancelled 被改回 paid 的那 25 組）。驗收 agent 以純 Python 獨立重算，數字一致。這個錯從原報告就存在，前三輪驗收都沒抓到。

- 依據：commit `7328fc0`；`notes/part_a/schema-inference/order-identity.md` J1、J4

### 2026-10-17｜Part A｜V7 base 重複列：使用者判斷是網路波動造成的重複寫入

使用者看到 base 的 40 組重複只差 `updated_at` 2～29 秒，判斷：「v7根據我的經驗是網路波動導致的重複寫入 可以重寫入端或是schena的unique index改善」。AI 補充 unique index 建在哪取決於 J1（上游是一張單一列，還是狀態事件表），而 `(order_id, updated_at)` 唯一擋不住 V7；寫入端冪等鍵是網路重送的根本解法。上游改善與本次管線的去重是兩件事，A-3 可以分開寫。J1 尚未決定。

- 依據：commit `7328fc0`；`notes/part_a/schema-inference/order-identity.md` V7

### 2026-10-17｜Part A｜不能用 demo 的變動量推論 prod 的狀態歷程

討論 fact_order 的三種型態時，AI 把「demo 裡同一張單狀態真的有變的只有 25 組，狀態歷程很薄」列為選型態的相關事實。使用者指出：「你不能用demo來假設變動性不大啊」。這和 ADR-01 被指正的「demo 資料量不代表 prod」是同一類錯：demo 是合成資料，官方 README 也說增量檔「含新訂單與舊訂單的狀態更新事件」，正式環境的訂單本來就會經歷 created→paid→completed 等多次狀態變化。設計要以業務流程為準，demo 的分布只能當作資料品質的線索。

- 依據：commit `a06b335`；`notes/part_a/order-state-machine.md`

### 2026-10-17｜Part A｜假設訂單流程單向：取消後不能恢復

討論 fact_order 的三種型態時，AI 說明累積快照能回答大部分問題，前提是每個里程碑對一張單只發生一次；若允許取消後恢復，`paid_at` 這類欄位會被覆蓋。使用者決定：「那先簡單假設不能恢復」。這個假設也讓唯一鍵 `(order_id, status)` 在上游事件表的情境下成立（同一狀態不會出現兩次）。

- 依據：commit `a06b335`；`notes/part_a/order-state-machine.md`

### 2026-10-17｜Part A｜假設 completed 是出團完成，與 base 資料衝突

畫訂單狀態機時，AI 列出待決定的問題之一：completed 是「出團完成」還是「交易完成」。使用者決定：「completed先假設成出團完成」。AI 指出這與資料衝突：base 的 completed 全部在出發日之前（`notes/part_a/schema-inference/order-time.md` 的 L10、J8），照此假設這些列都不合理。要當成資料品質問題處理，還是修正假設，尚未決定。

- 依據：commit `19df745`；`notes/part_a/order-state-machine.md`

### 2026-10-17｜Part A｜completed 維持出團完成，28,612 列當資料品質問題

AI 算出 base 的 completed 有 28,612 列（base 的 28.6%）出發日都還沒到，並提出兩條路：維持「出團完成」把這些列當資料品質問題，或改成「交易完成」讓資料合理；AI 也提到「近三成都錯，比較像語意不同」是推論。使用者先問「你不是說有時區問題」，AI 用時區正確解析重算：`updated_at` 全是 `+08:00`，出發日比更新日晚 4～119 天，時區最多只差 1 天，排除時區。使用者決定維持假設、當資料品質問題處理：「先把狀態規則定下來 之後比較好處理」。怎麼處理這些列尚未決定。

- 依據：commit `4f23333`；`notes/part_a/order-state-machine.md`

### 2026-10-17｜Part A｜假設 completed 後不能取消

使用者問狀態機裡「只出現在撞號列，不能當證據」是什麼意思。AI 說明資料裡的 completed → cancelled 都是同一個 order_id 但會員、金額、下單時間全不同的兩列（撞號），不是同一張單的狀態歷程；同一張單真正的狀態變化只有那 25 組 paid → cancelled，所以這條轉移只能靠業務判斷。使用者決定：「先假設completed後不能取消」。

- 依據：commit `e227828`；`notes/part_a/order-state-machine.md`

### 2026-10-17｜Part A｜增量檔與 base 撞號的列當 noise 處理

使用者問「只出現在撞號列，不能當證據」與「剛好等於隨機抽樣的期望值，兩邊統計上無關」是什麼意思。AI 說明撞號列各欄和 base 相同的程度，等於兩疊不相干的訂單隨機配對，並重算了精確的期望值對照（幣別、通路、狀態都落在隨機期望附近，會員、金額、下單時間相同 0 列）。使用者決定「把撞號當 noise 處理」，理由是「先假設訂單狀態不能被改寫」。AI 起草時把這句解讀成「會員、下單時間、金額不可改」並寫成使用者的前提，被驗收 agent 指出是擴寫（照字面「狀態不能改」會與 paid → cancelled 衝突）；AI 改成請使用者確認，使用者確認原意是訂單內容不能被改寫、狀態可以變。這與官方 README「增量含舊訂單的狀態更新」的說法不同。見 ADR-03。

- 依據：commit `3eb7f7a`；ADR-03

### 2026-10-17｜Part A｜狀態機定案：created 不能直接跳到 completed

狀態機最後一題「有沒有 created → completed 的直接跳轉（例如現場付款的票券）」，使用者決定：「我先假設不行」。至此狀態機的規則都以使用者的假設定下：單向不可恢復、completed 是出團完成、completed 後不能取消、completed 必須先經過 paid。合法轉移只剩 created → paid、created → cancelled、paid → cancelled、paid → completed。

- 依據：commit `802eeb6`；`notes/part_a/order-state-machine.md`

### 2026-10-17｜Part A｜fact_order 粒度參考模組 E：一張訂單一列

使用者先指出選事實表型態「還是要照業務邏輯看吧」。AI 找到題目內的業務需求線索：模組 E 的問數題都以訂單為單位（營收、取消率、狀態比例），模組 E 的迷你資料倉 fact_order 是一張訂單一列、存目前狀態。使用者也問「我在part a用的心力是不是有點多」，AI 估計 Part A 已花約 8～10 小時（題目建議 4～5 小時），A-1、A-2 程式碼仍是 0，建議剩下的決策加速、文件不再反覆打磨。使用者決定：「模組E是常見的業務情境 所以可以參考e來設計fact」。見 ADR-04。

- 依據：commit `e1dcd82`；ADR-04

### 2026-10-17｜Part A｜增量新舊以 updated_at 判斷

使用者問「照檔案順序是什麼意思」，AI 用 L4 那 25 組的例子（day1 cancelled、day2 送來 `updated_at` 較舊的 paid）說明：照檔案順序最新狀態是 paid，照 `updated_at` 是 cancelled。使用者決定：「照 updated_at，符合狀態機單向假設」。

- 依據：commit `7847045`；`notes/part_a/schema-inference/order-time.md` J6

### 2026-10-17｜Part A｜金額：原幣別與換算 TWD 都存

AI 列出金額處理的四個子題與建議：原幣別金額與換算後 TWD 都存、匯率用下單日（台北日期；fx 涵蓋 04-28～07-03，每天都有 USD、JPY）、TWD 匯率固定為 1（fx 沒有 TWD，Part B 的 inner join 因此丟掉 TWD 訂單）、NTD（200 筆）當成 TWD（金額比值與 TWD 幾乎相同，V4）。使用者接受，理由：「原幣別保留可追溯，換算 TWD 讓營收能直接加總」。負數金額與疑似多乘 1,000 的列留到 A-3 一起決定。

- 依據：commit `fb9736a`；`notes/part_a/schema-inference/order-amount.md` V4

### 2026-10-17｜Part A｜dim_member 同日矛盾的 30 位取較高等級

AI 查到同日矛盾的 30 位會員全部發生在第一次快照（04-30），都沒有更早的版本，建議等級標「未知」。使用者決定取較高的等級（一般 < 銀卡 < 金卡 < 白金），理由：「使用等級高的 不要影響會員權益」。AI 提醒 dim_member 是分析用、不發放權益；使用者修正理由為「假設會員系統也是同樣的行為才選擇的行為」，即假設上游會員系統遇到同日矛盾也取較高等級，資料倉與之一致。

- 依據：commit `355733d`；`notes/part_a/schema-inference/members.md` V8、J7

### 2026-10-17｜Part A｜dim_member SCD2 規則

AI 先用一位會員的三次快照示範 SCD2 版本表；使用者問「member只有一個怎麼是快照」，AI 說明 `members.csv` 用 `extract_date` 分成三批（04-30 全量 8,030 列、05-31 459 列、06-30 502 列），使用者理解為「增量都在同一個檔」。AI 補充與訂單增量的差別：會員增量放的是完整樣子、不一定有變，沒出現不代表刪除。使用者接受三項建議：第一版 `valid_from` 用 `register_date`；等級、城市用 SCD2，姓名、生日直接覆寫（Type 1）；city `N/A`、生日 1900-01-01 轉 NULL，且不能蓋掉已知的真實生日。理由：「新會員訂單要對得到版本，更正不算歷史，假值不能蓋真值」。

- 依據：commit `355733d`；`notes/part_a/schema-inference/members.md` V8、J7、J9

### 2026-10-17｜Part A｜fact_order 存代理鍵 member_sk

使用者問「sk跟id有什麼差」，AI 用 M003364（5 月底金卡升白金）說明：`member_id` 指人、`member_sk` 指某段時間的版本；fact 只存 id 時每個查詢都要加日期區間條件，忘了就會一張單對到多列、營收重複計算。使用者決定存 `member_sk`：「寫入時就對好版本，查詢不會重複算」。

- 依據：僅 process-log 記錄，實作時寫入 fact_order

### 2026-10-18｜Part A｜無時區標記的下單時間當台北時間

T3 實作 agent 暫時把 `YYYY/MM/DD HH:MM:SS`（base 3,001 筆）當台北時間解析，AI 請使用者定案。使用者先問「通常沒寫+8的話 代表UTC是嗎」，AI 說明沒有時區標記只代表沒記下來，要看寫入端的設定，並引用 T1 的兩項證據：3 組重複列與 `+08:00` 那列的時、分、秒相同；當 UTC 解析會有 384 筆更新時間早於下單時間。使用者決定：「台北 因為重複列跟時間先後都對得上」。

- 依據：僅 process-log 記錄，實作在 T3 的 `parse_order_created_at()`；證據見 `notes/part_a/schema-inference/order-time.md` 時區語意一段

### 2026-10-18｜Part A｜型別違規：檔案層級整批停、列層級進隔離表

T3 第二輪驗收發現 FAILFAST 和 ADR-02「先隔離並計數」衝突：只要一列型別不合，整批讀取就失敗。第三輪驗收又發現兩種不會報錯的情況：Decimal 小數位數超過會被四捨五入，空字串會被讀成 NULL。AI 列出 A（只隔離那一列）與 B（整批拒收），並建議 A。使用者問「不是已經有先設定db schema嗎」「有contract為什麼還有這題」，AI 說明 contract 只規定什麼算合格，沒規定碰到不合格怎麼辦；真的 DB 在寫入時就擋掉了，CSV 則沒有。AI 原本說 A 要維護兩份合約，這是錯的：讀取用的全字串版本可以從同一份 contract 自動產生。使用者提出折衷：「可以在一開始就跑一些基礎檢查 如過中途有其他失敗在略過這行」，也就是檔案不存在、表頭不符、空檔就整批停；型別、小數位數、必填空值這類列層級的問題，進隔離表並計數。理由：「pipline中應該要有data cleaning」。使用者另外提出「pipline也要考慮中途停止的問題」，待討論。

- 依據：僅 process-log 記錄，實作在 T3 讀取層與 T5 隔離表

### 2026-10-18｜Part A｜Kafka 不放進 Part A，移到 Part C

使用者提出「我想要嘗試加入kafaka」，目的是「想處理重送」。AI 說明 Kafka 預設是至少送到一次，消費端本來就會收到重複；它的冪等 producer 只去除 producer 自己重試造成的重複，應用程式層重送的訊息照樣傳下去。真正處理重送的是上游在事件建立時產生的唯一鍵（outbox），以及管線以 order_id MERGE、只有 updated_at 較新才覆寫的冪等寫入。另外提到題目輸入是批次檔、多起 broker 會增加重現風險、Part A 已超時。使用者決定：「同意 kafka放part c」。

- 依據：僅 process-log 記錄；Part C 素材記在其工作檔

### 2026-10-18｜Part A｜中途停止：冪等步驟＋批次紀錄

使用者提出「pipline也要考慮中途停止的問題」，並問「delta已經確保寫入異常的問題是嗎」。AI 說明 Delta 只保證單一張表的單次寫入不會寫一半，跨表不保證：例如 fact_order 寫入成功、隔離表還沒寫就當掉，對帳就對不上。AI 列出三個選項：A 冪等步驟＋批次紀錄、B 每次從 base 全部重建、C 失敗時用 RESTORE 回滾，建議 A。使用者確認一個批次就是一個檔案（base、day1～3），決定選 A，理由：「批次可以節省過去已經成功的事件執行時間 可以避免時間導致的停止問題 如果每次都在一個小時的時間點失敗 這樣重新執行也可從第二個小時開始」。

- 依據：僅 process-log 記錄，實作在 T6

### 2026-10-18｜Part A｜產品清單有壞列就整批停

T3 第四輪驗收 agent 發現：產品清單（products.csv）只要有一列的描述欄位壞掉（例如 `trip_days='abc'`），這一列就會被隔離，該產品的所有訂單都會落到「未知產品」（-1），營收被算進未知，而且沒有任何警示。AI 列出兩個選項：A 產品清單有壞列就整批停；B 照常跑，對帳時另外列出落到 -1 的筆數。使用者先問「主檔是指什麼」「不是order是主要嗎」，AI 說明主檔是 master data（被交易共用的基本資料），不是指最重要的資料，之後改稱「產品清單」。使用者再問「這個時候order已經紀錄了嗎」，AI 說明每一批先寫維度表、再寫訂單，選 A 時訂單還沒寫入，修好清單後重跑即可。使用者決定選 A，理由是「晚一點進來比錯的資料好」。

- 依據：僅記在 process-log，實作在 T5／T6

### 2026-10-18｜Part A｜dim_member：城市從 NULL 變成真實值時開新版本

T4 實作 agent 自行決定：city 從 NULL（原為 `N/A`）變成真實值時，開新版本，不回填舊版本；真實資料只有 M002261 一位會員因此多一個版本。AI 請使用者確認，說明這和之前定的「假值不蓋真值」方向相反（之前定的是真實值 → `N/A`），並列出回填的風險：會員可能是後來才搬過去的，資料無法分辨。使用者決定維持舊版本為 NULL：「不是使用null就好」。

- 依據：僅 process-log 記錄，實作在 T4 `pipeline/dim_member.py`

### 2026-10-18｜Part A｜T3 經過 5 輪獨立驗收

T3 由實作 agent 寫，每一輪都派一個沒看過實作過程的驗收 agent 檢查。前 5 輪結論都是「有條件過」，第 5 輪修正後做了一次針對性驗收，結果是「通過」。驗收 agent 抓到的 AI 實作錯誤包括：同義反覆的測試（兩次）、product_sk 的說明會引導 T5 產生懸空外鍵、dim_date 偷看未來的增量，以及第 4 輪的高嚴重度問題：Spark 讀 CSV 時的 column pruning 讓 `count()` 漏算欄位數錯誤的壞列，對帳會失真。另有三項不是 bug，而是規格沒定，交給使用者決定（型別違規、產品清單壞列、無時區標記的時間）。使用者要求記錄下來之後 review。

- 依據：`notes/part_a/t3-review-findings.md`

### 2026-10-18｜Part A｜AI 對讀取層效能的判斷錯誤：實測慢 9～49 倍

使用者問「這部份會導致效能下降嗎」（讀取層改成全字串＋`cast_to_contract`）。AI 沒有實測，只依原理回答「影響應該不大」，理由是沒有多讀一次資料、只多了 CPU 運算，並推測關掉 column pruning 是主要成本。使用者要求實測。效能 agent 把 orders_base 放大到 200 萬列實測（8 核本機，其他 agent 同時在跑，有些干擾）：舊讀法 count 0.64 秒、全欄聚合 3.55 秒；新讀法兩者都約 31 秒，分別慢約 49 倍、9 倍。慢的原因是 `cast_to_contract` 本身，關掉 column pruning 的影響在雜訊範圍內。AI 原本的兩個判斷都錯：「影響不大」錯，「pruning 是主要成本」也錯。對 Part A 的 10 萬列約 2 秒，可以忽略；數千萬列以上會是瓶頸（線性外推，未實測）。

- 依據：實測腳本與輸出在 `/tmp/perf/`（未進 repo）；結果記在工作檔 T3 節

### 2026-10-18｜Part A｜dim_member：新版本從觀察到變動的快照日開始

快照每月一次，只看得到兩次快照不同，看不到會員實際是哪一天變動的。AI 用 M003364 說明：04-30 是金卡，05-31 變成白金，5/15 的訂單算哪個等級，取決於白金版本從 05-31（快照日）還是 05-01（上次快照隔天）開始算，兩種都可能算錯。使用者先指出：「這個問題不要應該要從member中改善嗎 應該紀錄update time嗎」。AI 同意根本解法在上游，並列出三種做法：加 `updated_at`、建等級異動紀錄表、CDC。這些建議放進 A-3 與 Part C；這份作業手上只有快照，仍然要定一個規則。使用者決定用 05-31：「只記錄確定知道的事」。

- 依據：僅 process-log 記錄，實作在 T4 `pipeline/dim_member.py`

### 2026-10-18｜Part A｜完全相同的重複列：取 updated_at 最新一列

T5 開工前要先定一條規則：base 裡同一個 order_id 有多列（V7），以及增量檔裡同狀態的重送，這兩種情況怎麼去重。AI 提出的規則是「除了 updated_at 以外全部相同，就取 updated_at 最新的一列」，並說明這條規則不處理撞號列：會員、下單時間、金額只要有一欄不同，就照 ADR-03 進隔離表。使用者決定採用，理由：「網路重送造成的重複，留最新一列就好」（呼應先前對 V7 的判斷）。

- 依據：僅 process-log 記錄，實作在 T5／T6

### 2026-10-18｜Part A｜測試減少 Delta 寫入

使用者嫌 subagent 跑太久（T5 全套測試約 7 分鐘、本機與 UTC 各跑一次），問「測試怎麼會需要啟動pyspark 不能mock掉嗎」。AI 說明不能 mock：T3～T5 抓到的錯幾乎都是 Spark／Delta 本身的行為，例如 column pruning 讓 count() 漏算、轉型時悄悄四捨五入、Java regex 的 `$`、MERGE 的 E12、collect 時的時區換算，mock 掉就測不到。真正慢的是每條合成測試都走完整流程、寫 5 張 Delta 表（約 17 秒）。使用者再問「那寫入delta的邏輯有需要測試嗎」，AI 回答需要，但只限冪等、隔離表重跑、E12、updated_at 不倒退、當掉重跑這幾類，每類 1～2 條。使用者決定：「那就減少delta的使用」。轉換邏輯改成單獨測 DataFrame，從 T6 開始執行，T5 的合成測試一併改寫。

- 依據：僅 process-log 記錄；策略寫在工作檔
