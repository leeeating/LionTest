# ADR-04｜fact_order 粒度：一張訂單一列，存最新狀態
- 狀態：草稿
- Part：A
- 關聯：fact_order 粒度參考模組 E：一張訂單一列（[process-log](../ai-collab/process-log.md)）；[訂單狀態機](../notes/part_a/order-state-machine.md)；[learning：事實表三種型態](../learning/1-modeling/fact-table-types.md)

## 背景
題目 A-1 要求說明 fact_order 的粒度。事實表常見三種型態：交易事件（一次狀態變化一列）、定期快照（某天某張訂單一列）、累積快照（一張訂單一列，各里程碑時間各一欄）。

業務需求的線索：
- 模組 E 的問數題（`candidate_package/module_E/questions.json`）是這個訂單域的典型業務問題，例如「2026 年 5 月的總營收」「哪個目的地國家的訂單取消率最高」「各會員等級的平均訂單金額」「全部訂單中狀態為 completed 的比例」。這些都以訂單為單位，沒有問「付款到出團花幾天」或「某天結束時有幾張未付款」。
- 模組 E 附的迷你資料倉 `module_E/warehouse/fact_order.csv` 欄位為 `order_id,member_sk,member_id,product_sk,date_key,order_status,quantity,amount_twd,coupon_discount_twd`，20,000 列、20,000 個 order_id：一張訂單一列，存目前狀態，沒有各狀態的時間欄位。
- Part C 情境：每日 BI 報表、分鐘級即時儀表板、Text-to-SQL 問數。

資料限制：base 每張訂單只有一個狀態（全量匯出時的狀態），沒有之前狀態的時間；所以若做累積快照，base 訂單的 `paid_at` 等欄位大多無法填。

狀態規則（`notes/part_a/order-state-machine.md`，使用者假設）：單向、completed 後不能取消、completed 必須先經過 paid；每個狀態對一張單最多出現一次。

## 選項
| 選項 | 好處 | 代價 |
|---|---|---|
| A. 一張訂單一列，存最新狀態（模組 E 的形狀） | 營收、訂單數、取消率直接加總；以 `order_id` MERGE，冪等好證明；與模組 E、Text-to-SQL 情境一致 | 看不到狀態歷程與各步驟的時間；歷程只能從 bronze 的原始事件查 |
| B. 累積快照：一張訂單一列，加 `paid_at`、`completed_at`、`cancelled_at` | 同 A，另可回答流程時長與時間點狀態 | base 訂單沒有歷史狀態時間，這些欄位大多是空的；UPDATE 要處理晚到的舊事件（L4 的 25 組） |
| C. 交易事件：一次狀態變化一列 | 保留完整歷程 | 算營收要先取每張單最新一列，業務問題（模組 E）都要多一步，容易重複計算 |

## 決定〔使用者撰寫〕
〔待使用者確認〕使用者原話：「模組E是常見的業務情境 所以可以參考e來設計fact」。

## 理由〔使用者撰寫〕
〔待使用者確認〕

## 後果
- fact_order 的唯一鍵是 `order_id`，增量以 `order_id` MERGE（來源先依 `order_id` 去重，見 ADR-01 後果）。
- 增量同一張單的多列，要決定以哪一列為「最新」（J6：檔案順序或 `updated_at`）。
- 撞號列不寫入（ADR-03），進隔離表。
- 狀態歷程保留在 bronze 原始事件，fact 不保存。
