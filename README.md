# 雄獅資訊資料工程師 Take-Home

這是雄獅資訊資料工程師 take-home 的作答 repo。題目以旅遊訂單資料為素材，分成四部分：Part A 資料倉建置、Part B 審查 AI 產出的程式碼、Part C 架構設計，以及一個進階模組。全程與 AI（Claude Code）協作，每一份產出都可以從協作紀錄追溯來源。

**閱卷從 [`LionDEExam/submission/README.md`](LionDEExam/submission/README.md) 開始。**

## 各題進度

| Part | 內容 | 繳交物 | 狀態 |
|---|---|---|---|
| A | 星型模型、增量 ETL、資料品質報告 | `LionDEExam/submission/part_a/` | 未開始 |
| B | `buggy_pipeline.py` 程式碼審查 | [`part_b/code-review.md`](LionDEExam/submission/part_b/code-review.md) | 初稿，待使用者定稿 |
| C | 架構設計 | `LionDEExam/submission/part_c/` | 未開始 |
| 進階模組 | D／E／F 三選一 | `LionDEExam/submission/module_x/` | 未選定 |

## 快速開始

需要 [uv](https://docs.astral.sh/uv/)，跑 PySpark 另外需要 Java 17 以上。

```bash
uv sync                      # 依 uv.lock 建立 .venv（Python 3.12）
uv run python <script.py>    # 用專案環境執行
uv run ruff check <path>     # lint
```

| 套件 | 用途 |
|---|---|
| duckdb、pandas | Part A 候選引擎（用哪一個，會在 Part A 以 ADR 定案） |
| pyspark、delta-spark | 本機驗證 Part B 審查中的 Spark／Delta 語意 |
| pytest、ruff | 測試（目前尚無測試，Part A 起加入）、lint |

pandas 固定在 3.0 以下，因為 PySpark 4.2 還沒完全支援 pandas 3。

## 題目與資料（不收錄）

題目卷和 `candidate_package/`（資料集、`buggy_pipeline.py`）是面試素材，不公開，已經用 `.gitignore` 排除。只有拿到題目的應試者或閱卷者能重現結果，做法是把原始壓縮檔解壓到下面的位置：

```
LionDEExam/01_考題卷_資料工程師TakeHome.md
LionDEExam/candidate_package/
```

繳交物裡提到的 `candidate_package/...` 路徑，都是指這個位置。

## 目錄

```
LionTest/
├── README.md                 本檔
├── CLAUDE.md                 給 AI 的專案規則（協作流程、紀錄規則）
├── pyproject.toml, uv.lock   Python 環境
├── .claude/skills/           專案用的 AI skills
└── LionDEExam/
    └── submission/           所有繳交物
        ├── README.md         繳交物索引
        ├── part_a/ part_b/ part_c/ module_x/
        ├── notes/            理解問題時的筆記（資料字典、概念說明）
        ├── decisions/        設計決策（ADR）
        └── ai-collab/        AI 協作紀錄（流程紀錄、完整對話、一頁報告）
```

## AI 協作怎麼記錄

每一項任務都依六個步驟進行：使用者先看 → 拆解 → 委派 → 驗證 → 修正 → 使用者定案。過程記在 `LionDEExam/submission/ai-collab/process-log-*.md`，包括 AI 在哪裡出錯、是誰發現的、怎麼修正的。完整對話紀錄在 `ai-collab/transcripts/`。
