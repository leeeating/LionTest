---
name: feedback-no-line-numbers
description: 繳交文件不引用程式碼行號，改用函式名＋可搜尋的程式碼片段
metadata:
  node_type: memory
  type: feedback
  originSessionId: 3b7e0f96-b41d-4782-9c93-92bc39e533d5
  modified: 2026-10-10T08:02:12.985Z
---

使用者 2026-10-10 說：「文件應該要對行號不依賴，使用其他方式來紀錄變動性很高的行號。」

**Why:** 使用者重排了 `buggy_pipeline.py`（一行拆兩行），報告裡的 `Lxx` 全部錯位，驗收 agent 以為是報告寫錯。

**How to apply:** submission 下的文件引用程式碼時，寫「`函式名()` 中的 `可 Ctrl+F 搜到且唯一的片段`」，不寫行號。對話回覆裡的 `檔案:行號`（給使用者點擊用）不受此限。相關：[[feedback-layered-docs]]。
