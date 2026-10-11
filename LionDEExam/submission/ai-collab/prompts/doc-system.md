# 文件系統的規則 prompt

這份檔案收錄 AI 把使用者的文件系統概念寫成的規則文字（prompt）。概念來自使用者，使用者核可的是改動計畫，規則原文由 AI 撰寫。兩份 memory 在核可前就已寫入；「不引用行號」寫進 CLAUDE.md，是 AI 依使用者先前的要求自行加入的。事件經過見 `process-log.md`「建立文件系統」。

這些規則有四個落點：

| 落點 | 作用 | 是否在 repo |
|---|---|---|
| 專案 `CLAUDE.md`「紀錄規則」 | 每個 session 開場都會載入，規定 AI 怎麼記錄 | 是 |
| `ai-collab/README.md`「事件格式」 | process-log 的格式規格 | 是 |
| AI 的 memory 檔 | 跨 session 提醒 AI 使用者的文件偏好 | 否（本機），全文照錄於 [`ai-collab/memory/`](../memory/README.md) |
| 專案 skill（`adr`、`review-two-axis`、`to-questionnaire`） | 三個 skill 的紀錄步驟改成「在 `process-log.md` 記一個事件」，不寫行號 | 是，生效位置 `.claude/skills/`；副本見 [`skills/`](skills/README.md) |

以下內容照錄自 2026-10-10 的版本（同日因「process-log 改記使用者思考過程」重新同步），之後若有修改，以 git 歷史為準。

## 1. 專案 CLAUDE.md「紀錄規則」

#### 紀錄規則
三層紀錄，粒度由細到粗，各管各的：
| 層 | 記什麼 | 位置 |
|---|---|---|
| git commit | 檔案改了什麼；commit 訊息末行寫 `Session: <session id 前 8 碼>` | git log |
| process-log | **使用者的思考過程**：質疑了什麼、為什麼這樣決定、方向怎麼轉；不求嚴謹，時間軸 | `ai-collab/process-log.md`（全專案一份） |
| 報告 | 給閱卷者的結果文件 | 各 Part 繳交物、`ai-collab/ai-collab-report.md` |

最底層是完整對話（`ai-collab/transcripts/`），三層都可追溯到它。
> 〔2026-10-11 註〕此為照錄的舊版；完整對話已改為繳交時另附去識別化的 session jsonl 壓縮檔，現行規則見 repo 根目錄 `CLAUDE.md`。
- 事件格式見 `ai-collab/README.md`。六步驟是工作方法，不是紀錄格式；不用每個交付物寫滿六節。
- **AI 每記一個事件就在回覆最後一行寫「已記錄事件：<標題>」**，使用者可當場否決。
- **AI 要主動提醒使用者更新文件**：一個方向定案、一段討論告一段落、使用者說出判斷理由、或發現值得記的觀念時，在回覆最後一行提醒要更新哪一份（process-log、notes、learning、報告），附一句建議內容，由使用者決定記不記。
- **據實記錄發現者**：使用者、執行結果、驗收 agent、AI 自查，照實寫，不互相灌功。
- **附依據**：事件至少寫 commit hash；精確的證據（查詢與輸出）放在繳交物或 `evidence.md`，不在 process-log 裡求完整。
- **AI 的錯誤不美化**：寫清楚原本產出什麼、錯在哪。這是報告核心素材。
- **資料品質結論必須附實際執行的查詢與輸出**（放在 commit 的檔案或事件依據中），不能憑欄位名或常識推論。
- **文件不引用程式碼行號**：寫「函式名＋可搜尋的程式碼片段」。

## 2. ai-collab/README.md「事件格式」

#### process-log.md 事件格式
全專案一份。**記使用者的思考過程，不求嚴謹**：他當時質疑什麼、為什麼這樣決定、方向怎麼轉變，能引用使用者原話就引用。AI 做了哪些改動交給 git；AI 的錯誤仍要記，一句話帶過，但要寫出原本產出什麼、錯在哪。

**依部分分節**：依工作內容分成幾個部分（`## 第一部分：…`），每部分開頭一段說明範圍，事件用 `###`，部分內大致依時間排列；不同部分在時間上可以交錯。

```
### YYYY-MM-DD｜<Part 或「全專案」>｜<一句話標題>

<一到兩段：使用者怎麼想、怎麼決定；以讀得順為準，不限句數>

- 依據：<commit hash>
```

依據寫 commit hash 就夠了，還沒 commit 的寫 `〔待 commit〕`。有 ADR 時只寫「見 ADR-NN」。AI 起草、待使用者改寫的內容標 `〔待使用者確認〕`。

**什麼算事件**：方向轉折、使用者定案、AI 出錯被抓到。使用者的質疑只有在**改變了報告或決策**、或**抓到 AI 的錯**時才單獨記成事件；只是為了理解的提問，在相關事件裡一句帶過，答案放 `notes/` 或 `learning/`。

#### 一頁報告的素材來源
| 報告要回答 | 從 process-log 找 |
|---|---|
| 如何把任務拆解給 AI（附關鍵 prompt） | 使用者決定分工、委派的事件 |
| AI 在哪裡出錯或不足，如何發現並糾正 | 記到 AI 錯誤的事件（驗收 agent、使用者、執行結果、AI 自查發現） |
| 哪些部分刻意不用 AI 或不採納建議，為什麼 | 使用者定案、否決 AI 建議的事件 |

## 3. memory

跟文件系統有關的 memory 是 `feedback-layered-docs` 和 `feedback-no-line-numbers`，全文見 [`ai-collab/memory/`](../memory/README.md)。
