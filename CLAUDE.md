# LionDEExam：雄獅資訊資料工程師 Take-Home

題目全文：`LionDEExam/01_考題卷_資料工程師TakeHome.md`。題目要求繳交**完整 AI 協作紀錄**與**一頁 AI 協作報告**，「產出遠超出紀錄所能解釋的範圍」會重大扣分；之後還有面談追問。所以每個產出都要能追溯來源，而且**使用者必須比 AI 更了解每個結論**。

一律從 `LionTest/` 啟動 Claude Code：規則與 transcript 收集都以這個目錄為準。

## 目錄
```
LionTest/                              git repo 根目錄
├── CLAUDE.md                          本檔
└── LionDEExam/
    ├── 01_考題卷_資料工程師TakeHome.md  題目（唯讀）
    ├── candidate_package/             原始素材（唯讀）
    └── submission/                    所有繳交物，一律 Markdown；圖解可附自包含 HTML 當輔助
        ├── README.md                  交付索引
        ├── part_a/  part_b/  part_c/  module_f/
        ├── notes/                     理解問題時的筆記（分層、多檔）
        ├── learning/                  討論中選出的可遷移觀念筆記
        ├── decisions/                 ADR，說明見其 README.md
        └── ai-collab/                 協作紀錄，說明見其 README.md
```
`.claude/skills/` 是專案 skill（進 git）；`.claude/` 其餘內容（施工文件、`redact.local.json` 遮蔽清單）不進 git。

## 協作流程（每個任務都走這六步）
| 步驟 | 誰主導 | 內容 |
|---|---|---|
| 0. 你先看 | 使用者 | AI 先出初稿，使用者審閱並質疑：哪裡不懂、哪裡可疑、哪裡不同意。質疑的結果決定後續怎麼拆解與委派 |
| 1. 拆解 | 使用者＋AI | 任務切成哪些子任務、哪些交給 AI、哪些自己做 |
| 2. 委派 | AI | 給 AI 的關鍵 prompt |
| 3. 驗證 | AI | 用什麼方法檢查 AI 產出（查詢、checksum、獨立審查） |
| 4. 修正 | AI | AI 錯在哪、誰發現、怎麼改 |
| 5. 定案 | 使用者 | 使用者用自己的話寫下採用什麼、為什麼 |

- 步驟 4 的錯誤與步驟 5 的定案，都是 process-log 的事件素材。
- **AI 產出初稿後，主動列出值得質疑的地方**（假設、未證實的推論、可能的替代解讀），給使用者當審閱的起點。題目刻意埋了要親自檢視才發現的問題，使用者的質疑是抓到它們的關鍵。
- **AI 給推理過程，不只給結論**：怎麼查到的、為什麼算問題、有哪些選項、各自代價。新概念先給白話版，用 Python 或 C# 類比。
- **AI 不替使用者定案**：步驟 5 只列選項與取捨，草稿標 `〔待使用者確認〕`，由使用者改寫定稿。

## 與全域 workflow.md 的分工
執行骨架照 `~/.claude/rules/workflow.md`（分 S／M／L、對齊、工作檔、切塊、小步驗、除錯）。以下兩點以本檔為準：
- **定案不接受只回「照建議」**：凡是會寫進 process-log 定案事件或 ADR 的選擇，不論在哪個階段問，都要請使用者用自己的話寫一句理由；其餘問題可以照建議。
- **工作檔只放施工狀態**：`.claude/work/<part>.md` 只放任務卡、進度、未決問題；**決策與過程寫 process-log**，工作檔的「決策」欄只寫「見 process-log」。

## 紀錄規則
三層紀錄，粒度由細到粗，各管各的：
| 層 | 記什麼 | 位置 |
|---|---|---|
| git commit | 檔案改了什麼；commit 訊息末行寫 `Session: <session id 前 8 碼>` | git log |
| process-log | **使用者的思考過程**：質疑了什麼、為什麼這樣決定、方向怎麼轉；不求嚴謹，時間軸 | `ai-collab/process-log.md`（全專案一份） |
| 報告 | 給閱卷者的結果文件 | 各 Part 繳交物、`ai-collab/ai-collab-report.md` |

最底層是完整對話（繳交時另附去識別化的 session jsonl 壓縮檔），三層都可追溯到它。
- 事件格式見 `ai-collab/README.md`。六步驟是工作方法，不是紀錄格式；不用每個交付物寫滿六節。
- **AI 每記一個事件就在回覆最後一行寫「已記錄事件：<標題>」**，使用者可當場否決。
- **AI 要主動提醒使用者更新文件**：一個方向定案、一段討論告一段落、使用者說出判斷理由、或發現值得記的觀念時，在回覆最後一行提醒要更新哪一份（process-log、notes、learning、報告），附一句建議內容，由使用者決定記不記。
- **據實記錄發現者**：使用者、執行結果、驗收 agent、AI 自查，照實寫，不互相灌功。
- **附依據**：事件至少寫 commit hash；精確的證據（查詢與輸出）放在繳交物或 `evidence.md`，不在 process-log 裡求完整。
- **AI 的錯誤不美化**：寫清楚原本產出什麼、錯在哪。這是報告核心素材。
- **資料品質結論必須附實際執行的查詢與輸出**（放在 commit 的檔案或事件依據中），不能憑欄位名或常識推論。
- **文件不引用程式碼行號**：寫「函式名＋可搜尋的程式碼片段」。

## 決策紀錄（ADR）
- **進入解題（Part A 起）才寫 ADR**；環境與流程建置階段不寫。
- 有取捨的決策寫 ADR，**三條件都成立才寫**：難回頭、沒脈絡會覺得奇怪、有真的替代方案。用 `adr` skill。
- AI 只寫背景（附資料證據）、選項、後果；**決定與理由由使用者撰寫**，狀態只有使用者能改成「已定案」。
- process-log 的定案事件只寫一行連到 ADR，理由不重複寫。

## Skills
- 專案 skill 在 `.claude/skills/`：`adr`、`review-two-axis`（步驟 3 驗證）、`to-questionnaire`，皆改寫自 mattpocock/skills（MIT）；`concept-note`（討論中挑選可遷移觀念寫成筆記）為本專案自寫。對齊訪談用全域 workflow.md 的「對齊」，不另設 skill。
- 專案中新建立的 skill 一律放 `.claude/skills/`、進 git，並在 process-log 記一個事件說明為什麼建。

## 歸屬標註
Part C 設計文件**每一節**標註 `〔AI 產出〕`、`〔AI 產出，使用者修改〕` 或 `〔使用者判斷〕`（題目要求）。其他 Part 不逐節標註，靠 process-log 與 git 追溯。

## Session 開始與收尾
- 收尾：取得本 session id（`ls -t ~/.claude/projects/*-OpenSource-LionTest/*.jsonl | head -1` 的檔名），確認本 session 的事件依據都寫了它。不另外匯出對話。
- 完整對話以**去識別化的原始 session jsonl 壓縮檔**繳交（含 `<session id>/subagents/`、`<session id>/tool-results/`），等最後測試完成、打包繳交前才做，遮蔽後逐行驗證 JSON 仍有效。
