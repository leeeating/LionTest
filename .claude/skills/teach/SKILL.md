---
name: teach
description: 從本專案（資料工程師 take-home）萃取觀念，以短課、測驗與學習紀錄，幫使用者把它們內化成可遷移的軟體工程能力；學習內容寫到 LionDEExam/submission/learning/。僅在使用者明確呼叫 /teach 時使用。
disable-model-invocation: true
argument-hint: "想學哪個觀念？留空則從專案萃取候選觀念或接續上次進度"
---

改寫自 mattpocock/skills 的 skills/productivity/teach/（SKILL.md 與 MISSION-、LEARNING-RECORD-、RESOURCES-FORMAT.md，commit 49dd158；MIT License, Copyright (c) 2026 Matt Pocock，見 `../LICENSE-mattpocock-skills`）

# Teach：把專案裡的觀念內化成自己的能力

原版是「學一個新主題、教材來自外部資源」。本版的差異：**觀念從本專案萃取**（做題時真的碰到的事件、AI 錯誤、決策），**正式解釋再對照外部一手資源**。用途是讓使用者把做題時碰到的觀念學到真的懂，並能遷移到其他專案；要學到什麼程度，由使用者寫的 `MISSION.md` 決定。

這是跨多個 session 的狀態型任務，狀態全部存在學習資料夾裡，不靠對話記憶。

## 學習資料夾：`LionDEExam/submission/learning/`

| 檔案 | 內容 | 何時建立 |
|---|---|---|
| `README.md` | 資料夾說明（已存在） | — |
| `MISSION.md` | 為什麼學、學會的樣子；**使用者用自己的話寫** | 第一次執行 |
| `CONCEPTS.md` | 候選觀念清單與狀態，相當於課綱 | 第一次執行 |
| `RESOURCES.md` | 一手資源清單 | 第一次需要引用時 |
| `lessons/NNNN-<slug>.md` | 課程，一課一個觀念 | 每課 |
| `records/NNNN-<slug>.md` | 學習紀錄，證明使用者真的懂了才寫 | 有證據時 |

格式全部在 [FORMATS.md](FORMATS.md)。檔案與目錄用到才建立，不預先產生空檔。

## 每次執行的流程

1. **讀狀態**：讀 `MISSION.md`（含「教學偏好」）、`CONCEPTS.md`、`records/`。不存在就走「第一次執行」。
2. **決定這一課**：使用者在 argument 指定了就教那個；沒指定就從 `CONCEPTS.md` 挑一個**剛好有點難**的（「前置」欄的觀念都已內化、本身還沒有），符合條件的有好幾個時，優先選跟 `MISSION.md` 最相關的；說明為什麼選它，請使用者確認。
3. **查一手資源**：見「知識來源」。
4. **寫課程**到 `lessons/`，回報路徑。
5. **測驗**：在對話中直接問使用者，依回答給回饋。
6. **寫學習紀錄**：只有在第 5 步拿到證據時才寫，並更新 `CONCEPTS.md` 狀態。

## 第一次執行

1. **萃取候選觀念**：讀本專案素材，列出 5～10 個候選觀念。素材：
   - `LionDEExam/submission/ai-collab/process-log.md`（事件、AI 錯誤、決策）
   - `LionDEExam/submission/part_b/code-review.md`、`part_b/evidence.md`
   - `LionDEExam/submission/notes/`
   - `LionDEExam/submission/decisions/`
   - 之後各 Part 新增的繳交物
   每個候選附「在本專案哪裡出現」（檔案＋可搜尋片段或事件標題）、「為什麼對 SWE 重要」（離開資料工程也用得到的理由）與前置觀念。觀念要能遷移，例如冪等性、SCD2、join 前的唯一鍵檢查，不要只是某個 API 的用法。
2. **問 mission**：把候選清單給使用者看，問他為什麼想學、學會的樣子是什麼。答得模糊就追問，直到具體到可檢驗：有期限、有情境、能驗證學會與否。**由使用者用自己的話寫**，AI 只整理格式，不代寫。
3. **依 mission 挑觀念**：請使用者對照 mission 挑要學的觀念與順序，寫進 `CONCEPTS.md`。
4. **mission 與觀念都確定後，詢問使用者是否當場開第一課**；要就接「每次執行的流程」第 2 步，不要就結束。mission 沒定之前不開課。

## 知識來源：專案先、一手資源後

- **觀念的出處是本專案**：每課開頭說明它在專案哪裡出現、當時發生什麼事。引用程式碼一律用「函式名＋可搜尋片段」，**不寫行號**。
- **正式解釋要引用一手資源**：官方文件（Spark、Delta Lake、DuckDB、Python）、規格、經典文章或書。**不能只靠模型記憶**：先用 context7 或 WebFetch 實際讀到出處，再寫進課程並附連結。找不到出處的說法標「未證實」並說明推測依據。用過的資源記進 `RESOURCES.md`。
- **能實跑就實跑**：觀念能用 `uv run python` 或 duckdb 小範例驗證時，附指令與實際輸出，不寫想像的輸出。

## 課程寫法

- **用繁體中文，技術名詞保留英文。**
- **每課短小，只教一件事**，幾分鐘讀完，給使用者一個具體的收穫。
- **先白話（ELI5），再用 Python 或 C# 類比當錨點**；細節、邊界情況等使用者追問再給。
- 每課推薦**一個**最值得讀的一手資源。
- 課末提醒：不懂的地方直接在對話裡問。

## 測驗與回饋

學習要的是**長期記得**（storage strength），不是當下讀得順（fluency）。讀得順會讓人誤以為學會了。所以：

- **提取練習**（retrieval practice）：要使用者憑記憶回答，不是重讀。
- **間隔**（spacing）：新課開頭先抽問一兩題舊課的觀念。
- **適度困難**（desirable difficulty）：題目要求解釋「為什麼」或遷移到專案以外的情境，不只問定義。
- 課程內的練習題答案用 `<details>` 折疊；**真正的測驗在對話中直接問**，依回答即時回饋。
- 選擇題各選項長度相近、正解位置輪換，不用格式或順序洩漏答案。

## 學習紀錄：涵蓋不等於學會

**只有使用者證明真的懂了才寫**：在對話中用自己的話正確解釋、答對遷移題，或指出 AI 的錯。讀過課程、打開過 `<details>` 都不算。另外兩種情況也要寫：使用者說明自己原本就會（記下程度），或修正了一個誤解（價值最高，能預測之後會卡在哪）。格式見 [FORMATS.md](FORMATS.md)。

## 與專案規則的關係

- 學習是使用者自己的事，**一般不記 process-log**。例外：學習過程中發現繳交物有錯或要改決策，照 `ai-collab/README.md` 記一個事件。
- 課程是 AI 產出、為使用者學習服務，不是繳交物的結論；不要把課程內容當成 ADR 的理由來源，ADR 的理由仍由使用者撰寫。

## 刻意不做

- **不做 HTML 課程、`assets/` 元件庫**：使用者決定改用 Markdown，Markdown 不需要共用樣式與 widget。
- **不做 `reference/` 速查文件**：每課已經短小，學習紀錄就是壓縮後的精華；需要速查時再加。
- **不做 `GLOSSARY.md`**：專案的 `notes/` 已經有概念說明，另開一份會重複。
- **不做 `NOTES.md`**：上課中途使用者說出的教學偏好，記在 `MISSION.md` 的「教學偏好」一節，少一個檔案；不寫進全域 CLAUDE.md，那是使用者的私人檔案。
- **不做社群推薦（Wisdom）**：本 skill 的用途是內化專案裡的觀念，不需要外部社群；使用者的 mission 需要時再加。
