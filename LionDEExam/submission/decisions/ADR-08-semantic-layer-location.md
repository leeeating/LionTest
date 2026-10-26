# ADR-08｜語意層：指標口徑放 gold 實體表，semantic model 建在表上
- 狀態：已定案（2026-10-26，使用者指示 AI 代改：「你幫我」）
- Part：C
- 關聯：process-log 事件待使用者確認後由主 session 建立；素材見 `notes/part_c/tentative-decisions.md`「Q6」「Q7」

## 背景
「語意層」是指「營收」「取消率」這類業務名詞，對應到哪張表、哪個欄位、怎麼算的權威定義。Power BI 報表和 Text-to-SQL 問數都要用它，兩邊算出不同數字就沒人相信。

Part A 已經找到會被問錯的定義（`part-a-evidence.md`）：
- 營收的 `amount` 是**折扣前**；折扣後是 `net_amount_twd`；coupon -1 轉 NULL，NULL 不計入 net 總和（E8）
- 40 張疑似金額 ×1000 的訂單佔 5～6 月營收 28.09%，照原樣寫入、另列 `amount_review`（E9）。營收要不要排除它們，是一個要寫死的定義。Part A 只定了「40 張留在 fact，人工確認前不計入下游的金額指標」（`business-assumptions.md` 3.7）；營收的完整定義（含不含已取消、折扣前或後）由 Part C 決定（process-log「營收的定義不在 Part A 決定，移到 Part C 語意層」）
- 28,578 張訂單在最後一次更新（標成已完成的當下）時出發日還沒到；原報告警告不要誤讀成「到現在都還沒出團」。「已完成」不等於「已出團」（E11）
- 下單日是台北日（E10）；會員等級是月快照精度（E12）

Fabric 的事實改變了規劃階段的前提（規劃原本建議「欄位定義放 gold、彙總量值放 semantic model」，並註明要先查 data agent 能否讀 semantic model）：
- data agent 可以讀 semantic model（F7-2），但查 semantic model 時**忽略 agent 層 instructions**（F6-6），也**不支援 example queries**（F6-8），只看 model 的 metadata 與 Prep data for AI
- Prep data for AI（AI instructions、verified answers）目前是 **Preview**（F6-3）
- data agent 查 Lakehouse／Warehouse 時，可用 agent instructions（上限 15,000 字元，F7-6）與每個來源最多 100 組 example queries（F7-7）
- SQL endpoint 可以建 view（F4-1），但 Direct Lake 要讀實體表：經 SQL endpoint 的 Direct Lake 遇到沒有實體化的 SQL view 會退回 DirectQuery（F5-5）；直接讀 OneLake 的 Direct Lake 讀的是 Delta 檔，view 不是 Delta 檔（推論）
- data agent 目前不支援非英文（F7-8）；Q7 使用者選自建問數服務（2026-10-26），自建的話只能接 SQL，不能直接用 semantic model 的 DAX 量值，口徑放 gold 表的效益更大

## 選項
| 選項 | 好處 | 代價 |
|---|---|---|
| A. 定義全放 Power BI semantic model（DAX 量值＋描述＋Prep for AI） | 報表與 Copilot 共用；Power BI 團隊熟悉 | 問數若走 SQL（自建或 data agent 接 Lakehouse）就讀不到 DAX 量值，定義要再寫一份；Prep for AI 是 Preview；example queries 用不了 |
| B. 定義全放 gold（實體表，連彙總都先算好） | 一份定義，報表與問數都讀同一張表；data agent 接 Lakehouse 時 instructions 與 example queries 都能用；自建問數也能直接用 | 時間智慧、動態切片這類 DAX 擅長的計算要先算好或在 SQL 重做；彙總表的維度組合會越長越多 |
| C. 指標的**口徑**（用哪個金額欄、帶哪些旗標、用哪個日期）放 gold 實體表 `gold_order_metrics`（每張單一列，由管線寫出；Q3 定案後放在 Warehouse，ADR-06），semantic model 的量值只做加總與切片 | 口徑只有一份；semantic model 保留 DAX 的切片能力，且 Direct Lake 讀實體表不會退回 DirectQuery；兩條路算出的數字一致 | 每日批次多寫一張表；要守住「semantic model 量值不能自己加篩選條件」這條紀律，需要檢查機制（例如回歸測試比對兩邊數字） |

## 決定〔使用者撰寫〕
C：指標口徑放 gold 實體表 `gold_order_metrics`，semantic model 只做加總與切片。（使用者 2026-10-26 採用 AI 的建議；狀態已於 2026-10-26 改為已定案）

（先前 AI 暫定）〔AI 原草稿，已被上方定案取代〕AI 暫定：C。

## 理由〔使用者撰寫〕
使用者原話：「C照你的建議」；補充理由：「就照你的決策 我這裡沒有太多的業務知識 只能選一個作通用的」。

說明：這是採用 AI 的建議，使用者以「業務知識不足時選通用做法」為理由。AI 建議的依據見下方草稿。

（AI 的理由草稿，保留）〔AI 原草稿，已被上方定案取代〕AI 暫定的理由草稿：Part A 找到的是資料品質問題（金額疑似 ×1000、折扣前後混用、completed 不等於出團），但「怎麼算」是口徑選擇，不是加總問題。口徑放在報表與問數都讀同一張實體表的地方，只有一份；data agent 查 semantic model 時用不了 instructions 與 example queries，口徑放那裡對問數幫助有限。

## 後果
- 選 C：
  - 每日批次在 gold 之後多寫一張 `gold_order_metrics`（每張單一列，帶 `gross_amount_twd`、`net_amount_twd`、`is_amount_suspect`、`order_date_taipei`、`has_departed`）。表名與欄位描述就是 Text-to-SQL 的元資料
  - 「營收」沒有指定折扣前後時兩個都給（使用者 2026-10-26：「兩個都給」）：`gold_order_metrics` 同時帶 `gross_amount_twd` 與 `net_amount_twd`，指標定義檔把「營收」定義成兩個量值，問數與報表都同時呈現
  - 疑似 ×1000 的單：Part A 定了人工確認前不計入下游的金額指標（`business-assumptions.md` 3.7）。`is_amount_suspect` 對應 `amount_review` 清單，金額指標排除 `is_amount_suspect` 為真的列，fact 與 `gold_order_metrics` 仍保留這 40 張
  - 營收不含已取消的訂單（使用者 2026-10-26：「不算」）：`gold_order_metrics` 帶 `order_status`，營收的指標定義排除 `cancelled`
  - 欄位描述的來源是 Part A 的 `model.md` 欄位表與 `contracts.py` 的值域（E16），要建一份機器可讀的指標定義檔，同時產生表欄位描述與 semantic model 的描述，避免兩份手寫
  - 要有回歸測試：同一題用 SQL 查 `gold_order_metrics` 與用 semantic model 的 DAX 算，數字要相同
  - Q7 已選自建（只能讀 SQL），口徑必須在 gold 表上，C 的效益成立
- 選 A：自建問數或 data agent 接 Lakehouse 時，口徑要另外寫進 instructions，變成兩份
- 選 B：Power BI 報表改讀預先算好的彙總表，DAX 量值只剩簡單加總
- 審查紀錄：第一版選項 B、C 寫的是「gold SQL view」，第 1 輪審查指出 Direct Lake 遇到 SQL view 會退回 DirectQuery（F5-5），改成實體表（`notes/part_c/review-round1.md` S1）
