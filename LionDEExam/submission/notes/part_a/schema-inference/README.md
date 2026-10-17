# Part A：從 CSV 推測原始 schema

回到入口：[../../README.md](../../README.md)｜問題總表：[issues.md](issues.md)

〔AI 產出，待使用者審閱〕這組筆記只做**剖析與推測**，不含任何處理決策（修正、隔離、丟棄）。處理決策由使用者在 A-3（題目 Part A 的資料品質報告）定稿時決定。

## 做了什麼（30 秒版）

把 7 個 CSV 當成「上游營運 DB 匯出來的東西」，反推原本的資料表長什麼樣：訂單表一張單一列（目前狀態），會員表一人一列（members.csv 是它在某天的萃取），產品、匯率是主檔。

推法很單純：**多數值＝原始定義，違反者＝noise 候選**（noise＝題目刻意埋進資料的錯誤值）。例如 99.9% 的 amount 都是正數，就推原表有 `CHECK (amount > 0)`，那 50 筆負數就列為違反。違反再分三類：確定的錯誤值、未知值的哨兵（-1、N/A、1900-01-01）、可能合法的業務狀況；資料推不出來的列為「待使用者判斷」。

## 最重要的 3 個發現

1. **base 訂單的錯誤金額能和正常列完全分開**：用「金額換算台幣 ÷（定價 × 數量）」這個比值，正常列都落在 0.84～1.29；負數 50 筆、約多乘 1,000 的 40 筆、缺產品 120 筆都在區間外，沒有灰色地帶。詳見 [order-amount.md](order-amount.md)。
2. **增量檔每天約 600 列和 base 撞號，但內容和 base 統計上無關**：會員、下單時刻、金額 0 筆相同，其餘欄位吻合率等於隨機期望值。它們是「同一張單的更新」還是「另一張單」，決定 order_id 能不能當主鍵，是最大的待判斷事項（J1～J4）。詳見 [order-identity.md](order-identity.md)。
3. **時間欄位不能直接信**：base 下單時間有三種格式（Z 是 UTC、無標記是台北時間）；base 含 07-01～07-03 的更新；day1→day2 有 25 個 id 照檔案順序與照 `updated_at` 會得到相反的最終狀態（L4、J6）。詳見 [order-time.md](order-time.md)。

## 各檔導覽

| 檔案 | 一句話 |
|---|---|
| [issues.md](issues.md) | 所有問題一行一項：筆數、類型、連到細節 |
| [schema.md](schema.md) | 推測的原始 DDL，每個約束附推測依據 |
| [order-identity.md](order-identity.md) | 訂單撞號、重複、主鍵、哪些欄位不可變 |
| [order-time.md](order-time.md) | 時區與日期格式、晚到與亂序、萃取時點、completed 語意 |
| [order-amount.md](order-amount.md) | 金額比值規則、負數、×1000、NTD、coupon −1、折扣前後、產品與匯率參照 |
| [members.md](members.md) | 會員同日重複、N/A、1900 生日、快照規則 |

## 怎麼重跑

- 腳本：`LionDEExam/submission/part_a/profiling/profile_sources.py`（PySpark 4.2.0）。在 repo 根目錄執行：
  `uv run python -I LionDEExam/submission/part_a/profiling/profile_sources.py`
- 每段檢查以 `[Sx.名稱]` 形式的標籤印出 SQL 原文與輸出。每段末尾的「證據」是剖析腳本輸出中的搜尋標籤，可用來找到該數字的原始查詢與結果。
- **所有欄位以字串讀入**（`inferSchema=false`），型別轉換一律用 `try_cast`、`try_to_timestamp`、`try_to_date`，轉不過的算「無法轉換」，不讓 Spark 報錯也不悄悄變 NULL。
- 查詢建立在三個 view 上（定義也印在 stdout）：`orders_all`（四個訂單檔 union，加 `src`、`batch_date`）、`orders_t`（解析後欄位：`co_ts`、`upd_ts`、`dep_dt`、`amount_d`、`qty_i`、`coupon_d`、`co_fmt`）、`orders_ratio`（加上產品定價與同日匯率，見 [order-amount.md](order-amount.md)）。
- Spark 讀 CSV 時 BOM 已自動略過：標籤 `S0` 印出的第一欄名稱是 `'order_id'`，沒有多一個看不見的字元；七個檔都有 BOM（`BOM=True`），讀到的列數＝檔案行數−1。

## 時區設定

腳本設 **`spark.sql.session.timeZone = Asia/Taipei`**：沒有時區標記的時間字串（`2026/05/24 19:26:43`）會被解讀成台北時間；有標記的（`+08:00`、`Z`）照標記換算。這個設定只影響「沒有標記」的那 3,001 筆；它是否正確，見 [order-time.md 的 V5](order-time.md#v5)。

## 與既有筆記（`notes/dataset/`）的關係

數字差異逐項寫在相關問題底下（產品定價範圍在 [schema.md](schema.md)、金額分位數在 [order-amount.md](order-amount.md)、day2 重疊列數在 [order-identity.md](order-identity.md)、會員等級與快照在 [members.md](members.md)）。

其餘與既有筆記一致：七檔 BOM、base 100,040 列 / 100,000 id、增量列數與 id 數、日期格式各 3,001、NTD 200、fx 只有 USD/JPY、負數 50（29/17/4）、疑似 ×1000 40（27/9/4，31 筆為 1000 倍數）、product_id 不在主檔 120、city N/A 71、同日重複 30 組、birth 1900 81 列、增量檔 `updated_at` 晚於批次日 3,290 / 3,257 / 3,263、day2 6 列早於批次日、同檔重複 18 / 16 / 17 組。

**新發現（既有筆記沒有的）**：V3（coupon -1.0 300 筆）、V10 補強與 J9（birth_date 變過的 19 人都和 1900-01-01 互換，14 人 1900 → 真實、5 人 真實 → 1900）、L2（base 有 2,265 列 `updated_at` 在 07-01～07-03）、L3（day2 60 張晚到新單）、L4（day1→day2 的 25 個 id 是較舊事件晚到）、J2 補強（撞號列吻合率等於隨機期望、狀態只有 cancelled／completed）、V1 與 V2 補強（比值把負數與 ×1000 完全分開）、L11（會員後續快照 185 列與前次完全相同）、L5（80 筆 JPY 帶小數）、L7（44 個產品名稱被多個 id 共用）、既有筆記的 base_price_twd 範圍是字串比較的錯誤值（已更正）、J10（折扣前／後無法由資料確認）。

## 推論裡最弱的地方

每一點寫在對應問題底下，標 `值得質疑 Qn`：Q1 比值模型、Q2 ×1000 的 USD、Q6 近似分位數在 [order-amount.md](order-amount.md)；Q3 時區證據樣本在 [order-time.md](order-time.md)；Q4 CHECK 範圍在 [schema.md](schema.md)；Q5 隨機吻合論證在 [order-identity.md](order-identity.md)；Q7 分組界線在 [members.md](members.md)。
