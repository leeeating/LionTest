# AI 的 memory

Claude Code 會在每個 session 開場自動載入 memory，用來跨 session 記住使用者的偏好。memory 存放在本機 `~/.claude/projects/<專案>/memory/`，不在 repo 裡，所以本資料夾照錄原始檔（含 frontmatter），閱卷者才看得到 AI 依據哪些長期指示工作。

- 每一份 memory 都來自使用者的指示，由 AI 寫成檔案。
- 照錄的是 2026-10-10 的版本。之後 memory 若有修改，這裡不會自動同步。

## 檔案

| 檔案 | 主題 | 寫入 |
|---|---|---|
| [`feedback-keep-it-simple.md`](feedback-keep-it-simple.md) | 規則與流程先給最小可用版 | 2026-10-09，環境建置 session |
| [`feedback-layered-docs.md`](feedback-layered-docs.md) | 文件系統：筆記分層、報告是結果文件 | 2026-10-10，session 3b7e0f96 |
| [`feedback-no-line-numbers.md`](feedback-no-line-numbers.md) | 文件系統：不引用行號 | 2026-10-10，session 3b7e0f96 |

更新方式：打包繳交前，從 `~/.claude/projects/<本專案>/memory/` 重新複製 `feedback-*.md`，再更新本表與下方索引。

## 索引（MEMORY.md）

```
- [Keep it simple](feedback-keep-it-simple.md) — 規則／流程先給最小可用版，挑出問題先想能不能刪
- [Layered docs](feedback-layered-docs.md) — 筆記分層多檔；繳交報告是單一份論文式文件
- [No line numbers](feedback-no-line-numbers.md) — 繳交文件用函式名＋程式碼片段，不寫行號
```
