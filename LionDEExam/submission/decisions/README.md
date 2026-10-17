# 決策紀錄（ADR）

每份 ADR 記錄一個有取捨的設計決策。三個條件都成立才寫：**難回頭**、**沒脈絡會覺得奇怪**、**有真的替代方案**。

- 檔名：`ADR-NN-<主題>.md`，編號跨 Part 共用、連續、不重用。
- 背景、選項、後果由 AI 起草並附資料證據；**決定與理由由我本人撰寫**。
- 狀態為「已定案」的 ADR 才代表最終決定。決策被推翻時開新 ADR 取代舊的，舊檔保留並改狀態為「被 ADR-NN 取代」。
- 每份 ADR 連回 `../ai-collab/process-log.md` 中對應的事件（事件標題）。

## 範本
```markdown
# ADR-NN｜<決策標題>
- 狀態：草稿／已定案／被 ADR-NN 取代
- Part：
- 關聯：<process-log.md 事件標題>

## 背景
## 選項
| 選項 | 好處 | 代價 |
|---|---|---|
## 決定〔使用者撰寫〕
## 理由〔使用者撰寫〕
## 後果
```

## 索引
| ADR | 標題 | Part | 狀態 |
|---|---|---|---|
| [ADR-01](ADR-01-execution-engine.md) | Part A 執行引擎：PySpark＋Delta | A | 草稿 |
| [ADR-02](ADR-02-source-abstraction-schema-contract.md) | 管線以抽象來源設計，品質規則寫成 schema 合約 | A | 草稿 |
