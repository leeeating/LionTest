# ADR-05｜重跑時以「這批寫入前」的 fact 版本為比對基準
- 狀態：已定案
- Part：A
- 關聯：process-log「中途停止：冪等步驟＋批次紀錄」「狀態機檢查採 C：晚到事件分開處理」「T6 驗收：T5 驗收者的『狀態倒退』說法是錯的」；learning `2-incremental-etl/delta-time-travel.md`

## 背景
A-2 要求「同一個增量檔重複執行兩次，事實表結果必須一致」。另外，使用者定了「中途停止採冪等步驟＋批次紀錄」：寫到一半當掉時，要能整批重跑，而且結果和沒當掉時相同。

問題出在狀態機。每一列的分類要拿「既有 fact 的現況」來比：
- updated_at 比 fact 新：逐段檢查轉移，合法的寫入
- updated_at 不比 fact 新：晚到事件，可達的歸「略過」（仍寫進隔離表），不可達的歸 `late_event_conflict`

同一批**第二次**執行時，fact 已經包含這批第一次寫入的結果。若直接拿目前的 fact 比，這批原本「寫入」的列，updated_at 都不再比 fact 新，會全部被分成晚到事件：
- fact 本身不會壞（MERGE 只在 updated_at 較新時覆寫）
- 但隔離表會多出一批「略過」列，對帳的分類也和第一次不同，冪等證明就不成立

以 L4 為例（day1 cancelled、day2 送來較舊的 paid）：day2 第一次執行時，paid 正確地歸「略過」。若 day1 在 day2 之後被重跑，day1 那列 cancelled 會變成和 fact「同時間」，因而被判為晚到事件，和第一次的「寫入」不同。

## 選項
| 選項 | 做法 | 好處 | 代價 |
|---|---|---|---|
| A. time travel 讀「這批寫入前」的 fact 版本 | 每批第一次開始、還沒寫任何表之前，把當下 fact 的版本號記進 `batch_start` 表；重跑時沿用這個版本號，用 time travel 讀回來比對 | 重跑的分類、隔離表、對帳和第一次完全相同（冪等證明表的 hash 相同）；只多存每批一列版本號，不複製資料 | 依賴 Delta 保留舊版本：`VACUUM` 之後讀不到，會直接報錯 |
| B. 只保證 fact 一致，隔離與對帳的分類允許和第一次不同 | 重跑時直接拿目前的 fact 比 | 最簡單，沒有額外機制 | 「同一個檔跑兩次結果一致」只對 fact 成立；隔離表和對帳每跑一次就變一次，無法用整表 hash 證明冪等，也很難向閱卷者解釋 |
| C. 重跑前先 `RESTORE` 各表到這批之前的版本 | 把 fact、隔離表、維度表都退回去，再正常重跑 | 狀態最乾淨，等同沒跑過 | 要協調多張表一起退回，`RESTORE` 本身也可能失敗；如果這批之後的批次已經寫入，退回會連後面的批次一起抹掉 |
| D. 每批開始前，把 fact 的 `(order_id, 狀態, updated_at)` 另存一份快照表 | 重跑時讀快照表比對 | 不依賴 Delta 的版本保存期限 | 每批多存一份接近整表大小的資料；多一張表要維護與清理 |

## 決定〔使用者撰寫〕
A：time travel 讀「這批寫入前」的 fact 版本。

## 理由〔使用者撰寫〕
為了讓冪等成立，並且可以保證只改動到修改後的資料列。

## 後果
- **實作位置**：`batch_log.py` 的 `pin_fact_version` 與 `batch_start` 表；`fact_order.py` 的 `_fact_before_batch` 用它讀回開始前的 fact。`merge_upsert` 的 `commit_marker` 仍會在 commit 上標 `batch:<id>`，只用於稽核，不再用來找版本。
- **冪等證明**：`profiling/idempotency_proof.py` 比對第一次與重跑後的 fact、隔離表的整表 hash，以及每批的對帳數字。README「冪等證明」附有結果表。
- **營運限制要寫進 README**：
  - 重跑只適用於 Delta 仍保留舊版本的期間；執行 `VACUUM` 前要確認不需要重跑。
  - `--force` 會覆寫批次紀錄，不比對 checksum（依 process-log「checksum 涵蓋參考資料」的定案，之後會改成留下強制重跑的紀錄，待實作）。
- **定案後的實作調整（2026-10-19）**：原本的做法是「找這批第一個 commit 標記，讀它的前一版」。T6 驗收發現，該批 MERGE 0 列時不會產生 commit，也就找不到標記，force 重跑會讀到錯誤的版本。實作者實測「寫一個帶標記的空 commit」也行不通：對已存在的表做空的 append，Delta 不會產生 commit。最後改成開始前先把版本號記進 `batch_start` 表。決定本身（用 time travel 讀這批寫入前的版本）不變，只改了「怎麼知道是哪個版本」。
- **Fabric 相容**：Fabric Lakehouse 的表也是 Delta，同樣支援 time travel（未實測，依 Delta 格式推論）。
