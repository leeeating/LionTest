# 專案 skill

這裡收錄本專案使用的 Claude Code skill。skill 是預先寫好的指示：使用者說出觸發語，或任務符合 skill 的描述時，AI 就照裡面的步驟執行。

**實際生效的位置**是 repo 根目錄的 `.claude/skills/`，因為 Claude Code 只從那裡載入 skill。本資料夾是它的副本，目的是讓閱卷者在 `prompts/` 底下，就能一起看到所有規範 AI 行為的 prompt。

| skill | 用途 | 使用時機（六步驟） |
|---|---|---|
| [`adr/`](adr/SKILL.md) | 起草 ADR，只寫背景、選項、後果；決定與理由留給使用者 | 定案 |
| [`review-two-axis/`](review-two-axis/SKILL.md) | 從 Spec、Standards 兩軸，各派一個 fresh-context subagent 審查 | 驗證 |
| [`to-questionnaire/`](to-questionnaire/SKILL.md) | 把題目的模糊處，或 AI 無法替使用者回答的決策，整理成問卷，交給使用者或面試方填寫；只在使用者明確呼叫時使用 | 拆解 |
| [`teach/`](teach/SKILL.md) | 從本專案萃取觀念，用短課、對話測驗與學習紀錄幫使用者內化成 SWE 能力，內容寫到 `submission/learning/`；只在使用者明確呼叫時使用 | 不屬於六步驟（使用者學習用） |

- **來源**：四個 skill 都改寫自 mattpocock/skills（MIT 授權，見 `LICENSE-mattpocock-skills`）。
- **2026-10-10 的修改**：三個 skill 的紀錄步驟改成「在 `process-log.md` 記一個事件」，並且不寫行號（見 process-log「建立文件系統」）。
- **同步方式**：修改一律改 `.claude/skills/`，打包繳交前再複製一份到這裡。用 `diff -r .claude/skills LionDEExam/submission/ai-collab/prompts/skills` 確認兩邊一致（只會多出本 README）。
