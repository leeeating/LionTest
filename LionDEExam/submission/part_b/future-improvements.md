# Part B 之後改善：審查報告尚未涵蓋的問題

〔之後改善〕本檔列出主報告 [code-review.md](code-review.md) 目前**沒有寫到**的問題，來源是資深資料工程師角色的審查 agent（面試官視角）在 2026-10-11 的閱卷意見。這些項目**尚未寫進主報告，也尚未經過獨立驗證**；標「審查 agent 實測」的數字來自該 agent 的回報，引用前要先重跑確認。

| # | 項目 | 涉及函式 | 為什麼重要 | 狀態 |
|---|---|---|---|---|
| F1 | 跨批次亂序 | `clean_orders`、`write_fact` | 晚到的舊版本會讓訂單狀態倒退 | 待驗證後補進 #9 |
| F2 | 時區 | `clean_orders` | 修正時若轉成 timestamp，34% 訂單的日期會錯 | 待驗證後補成獨立一條或補進 #1 |
| F3 | 依 `order_date` 分區產生小檔 | `write_fact` | 是否成立取決於 prod 的資料量，demo 資料不足以判斷 | 待取得 prod 資料量再評估 |
| F4 | 隔離表沒有真的寫出去 | #3、#4、#8、#10 的修正 | 「不再靜默丟資料」目前只到計數 | 待補修正程式 |
| F5 | Fabric／OneLake 部署面 | 常數 `LAKEHOUSE` | 表的位置不對，下游 BI 看不到 | 主報告目前列為範圍外 |

## F1 跨批次亂序

**問題**：增量檔的 `updated_at` 不只落在批次日，後一天的檔案還會送來同一張訂單**比較舊**的版本。

```text
示意（審查 agent 回報的例子，尚未重跑）
day1 檔：ORD00100020  cancelled  updated_at 07-04
day2 檔：ORD00100020  paid       updated_at 07-03   ← 較舊的版本晚一天送到
```

- 審查 agent 實測：day1 與 day2 有 25 個共同的 `order_id`，25 筆都是 day2 送來較舊的版本。`notes/dataset/incremental.md` 已記錄 day1 的 `updated_at` 最晚到 07-05、day2 有 6 列早於批次日（`evidence.md` E9）。
- **影響**：原程式用 append，新舊兩列並存。若改成沒有條件的 MERGE，或用 #9 (c) 提到的「受影響分區 `replaceWhere` 整區重算」，已取消的訂單會被改回 paid。
- **報告目前的狀態**：#9 的修正 `whenMatchedUpdateAll(condition="s.updated_at > t.updated_at")` 剛好擋住了這件事，但報告沒有拿出資料說明為什麼需要這個條件；`replaceWhere` 替代方案在這份資料上不安全。
- **之後要做**：重跑「day1 與 day2 共同 order_id 的新舊比較」並收進 evidence；在 #9 補這個證據；刪掉 `replaceWhere` 替代方案或註明前提；討論批次截止點（batch_date 是 day1，`updated_at` 卻到 07-05）與同一個 `updated_at` 的更正重送（`evidence.md` E10 [6] 已實測：時間相同時更新會被略過）。

## F2 時區

**問題**：`order_created_at` 帶 `+08:00` 時區。原程式用字串 `substring` 取日期，剛好取到台灣當地日期；但若修正時把它轉成 timestamp，再在 UTC 的 session timezone 下取 `to_date`，日期會往前一天。

```text
示意（審查 agent 回報，尚未重跑）
2026-07-01T07:30:00+08:00
  session timezone = UTC          → to_date = 2026-06-30
  session timezone = Asia/Taipei  → to_date = 2026-07-01
```

- 審查 agent 實測：day1 有 1,580 / 4,615 筆（34%）的下單時間在當地 08:00 前，這些的 `order_date` 與對匯率的日期都會錯。`orders_base` 另有 3,001 筆是 `Z`（UTC）格式（`notes/dataset/dictionary.md`、`evidence.md` E9 已記錄三種格式）。
- **報告目前的狀態**：#1 的 schema 修正把 `order_created_at` 留成字串，並註明時區另案處理。題目有點名時區。
- **之後要做**：重跑 08:00 前的筆數；決定寫成獨立一條或併進 #1；修法是明確設定 session timezone，或先轉成當地時間再取日期，並處理 `Z` 格式。

## F3 依 `order_date` 分區產生小檔

**問題**：`write_fact` 用 `partitionBy("order_date")`。一個增量批次因為包含舊訂單的更新，會碰到很多日期分區。

- 審查 agent 實測：day1 寫入後有 62 個分區、62 個檔；day2 用報告的 MERGE 寫入後總檔數變成 125（`numTargetFilesAdded=63`）。每天約 4.6k 列卻新增約 63 個小檔。
- **但這可能只是 demo 的資料量**（使用者指出）：題目的增量檔一天約 4.6k 列，prod 的量可能大很多。檔案「小不小」看的是每個分區每次寫入的資料量，量大時每個檔自然變大，日期分區就不一定是問題。
- **跟資料量無關的部分**：一個批次會碰到幾個分區，取決於這批有多少「舊訂單的更新」分散在不同日期，而不是總量。所以「每批寫入的檔案數 ≈ 被碰到的分區數」這個結構在 prod 一樣成立，只是每個檔的大小會不同。
- **之後要做**：先取得 prod 的每日訂單量與跨日更新比例，估算每個分區每次寫入的大小，再決定要不要改分區策略。若確定太小，選項有：改用較粗的分區（例如月）、不分區改用 liquid clustering，或定期 `OPTIMIZE`；Fabric 上另需了解 V-Order 與 optimize write（未查證）。

## F4 隔離表沒有真的寫出去

**問題**：修正程式用模組層級的 `QUARANTINE` dict 收集被隔離的列（#3、#4、#8），但只拿來 `count()` 做對帳（#10），**沒有任何一行把它們寫進隔離表**；三種隔離的欄位結構也不同，不能直接合成一張表。#2 說的「主要欄位不一致的重複列先送隔離」也沒有對應的修正程式。

- **影響**：5.2 的「不再靜默丟資料：說得出丟到哪」目前只做到「說得出丟了多少」。
- **之後要做**：設計隔離表結構（原始列內容、隔離原因、批次日、時間），在寫入 fact 前一起寫出；把全域 dict 改成函式回傳值，方便測試；`persist` 後再 count，避免每次都重算整條 lineage。

## F5 Fabric／OneLake 部署面

**問題**（審查 agent 依 Microsoft Learn 的 OneLake 路徑格式判斷，**未實測、未查證**）：

- 程式的 `LAKEHOUSE` 常數路徑最後一段是 `dw`，沒有 `<item>.Lakehouse` 這類 item 類型。若實際指向 Warehouse，Spark 不能寫入。
- Delta 表若不放在 Lakehouse 的 `Tables/` 底下，不會註冊成 Lakehouse 表，SQL analytics endpoint 與 Power BI Direct Lake 看不到。這和程式 docstring 說的「供下游 BI 與 AI 應用查詢」相衝突。
- **報告目前的狀態**：主報告 2.2 明確把 Fabric 部署設定排除在範圍外。
- **之後要做**：查 Microsoft Learn 的 OneLake 路徑與 Lakehouse 表註冊規則並附來源；決定在主報告加一段「範圍外但需確認的部署風險」，或留到 Part C 架構設計處理。

## 不在本檔的項目

審查 agent 另外指出的「報告寫錯或判斷不一致」（例如 #5 的 null 當 0 在原程式走不到、#2 依自訂定義應為 P1）與「修法品質」（例如 #6 改用單一 MERGE），屬於修改主報告既有內容，不列在這裡。
