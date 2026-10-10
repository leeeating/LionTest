# 文件系統的規則 prompt

這份檔案收錄 AI 把使用者的文件系統概念寫成的規則文字（prompt）。概念來自使用者，使用者核可的是改動計畫，規則原文由 AI 撰寫。兩份 memory 在核可前就已寫入；「不引用行號」寫進 CLAUDE.md，是 AI 依使用者先前的要求自行加入的。事件經過見 `process-log.md`「建立文件系統」。

這些規則有四個落點：

| 落點 | 作用 | 是否在 repo |
|---|---|---|
| 專案 `CLAUDE.md`「紀錄規則」 | 每個 session 開場都會載入，規定 AI 怎麼記錄 | 是 |
| `ai-collab/README.md`「事件格式」 | process-log 的格式規格 | 是 |
| AI 的 memory 檔 | 跨 session 提醒 AI 使用者的文件偏好 | 否（本機），全文照錄於 [`ai-collab/memory/`](../memory/README.md) |
| 專案 skill（`adr`、`review-two-axis`、`to-questionnaire`） | 三個 skill 的紀錄步驟改成「在 `process-log.md` 記一個事件」，不寫行號 | 是，生效位置 `.claude/skills/`；副本見 [`skills/`](skills/README.md) |

以下內容照錄自 2026-10-10 撰寫當時的版本，之後若有修改，以 git 歷史為準。

## 1. 專案 CLAUDE.md「紀錄規則」

#### 紀錄規則
三層紀錄，粒度由細到粗，各管各的：
| 層 | 記什麼 | 位置 |
|---|---|---|
| git commit | 檔案改了什麼；commit 訊息末行寫 `Session: <session id 前 8 碼>` | git log |
| process-log | 整個專案**有意義的事件**（分析資料的發現、方向決策、AI 出錯被抓到、範圍取捨），時間軸 | `ai-collab/process-log.md`（全專案一份） |
| 報告 | 給閱卷者的結果文件 | 各 Part 繳交物、`ai-collab/ai-collab-report.md` |

最底層是完整對話（`ai-collab/transcripts/`），三層都可追溯到它。
- 事件格式見 `ai-collab/README.md`。六步驟是工作方法，不是紀錄格式；不用每個交付物寫滿六節。
- **AI 每記一個事件就在回覆最後一行寫「已記錄事件：<標題>」**，使用者可當場否決。
- **據實記錄發現者**：使用者、執行結果、驗收 agent、AI 自查，照實寫，不互相灌功。
- **附證據**：commit、session、檔案路徑、指令與輸出摘要。沒有證據的事件不算數。
- **AI 的錯誤不美化**：寫清楚原本產出什麼、錯在哪。這是報告核心素材。
- **資料品質結論必須附實際執行的查詢與輸出**（放在 commit 的檔案或事件依據中），不能憑欄位名或常識推論。
- **文件不引用程式碼行號**：寫「函式名＋可搜尋的程式碼片段」。

## 2. ai-collab/README.md「事件格式」

#### process-log.md 事件格式
全專案一份，依時間由舊到新。只記**有意義的事件**：分析資料的發現、方向決策、AI 出錯被抓到、範圍取捨、使用者定案。檔案層級的細節交給 git。

```
## YYYY-MM-DD｜<Part 或「全專案」>｜<一句話標題>
- 經過：<發生什麼；AI 出錯時寫原本產出什麼、錯在哪>
- 誰：<決定者／發現者：使用者、AI、驗收 agent、執行結果>
- 依據：<commit hash；session id 前 8 碼；檔案路徑；指令與輸出摘要>
```

使用者定案的事件，「經過」寫使用者自己的話；有 ADR 時只寫「見 ADR-NN」。AI 起草、待使用者改寫的內容標 `〔待使用者確認〕`。

#### 一頁報告的素材來源
| 報告要回答 | 從 process-log 找 |
|---|---|
| 如何把任務拆解給 AI（附關鍵 prompt） | 使用者決定分工、委派的事件 |
| AI 在哪裡出錯或不足，如何發現並糾正 | 「誰」是驗收 agent、使用者、執行結果、AI 自查的錯誤事件 |
| 哪些部分刻意不用 AI 或不採納建議，為什麼 | 使用者定案、否決 AI 建議的事件 |

## 3. memory

跟文件系統有關的 memory 是 `feedback-layered-docs` 和 `feedback-no-line-numbers`，全文見 [`ai-collab/memory/`](../memory/README.md)。
