# ADR-07｜即時鏈路：Eventstream → Eventhouse → Real-Time Dashboard
- 狀態：已定案（2026-10-26，使用者指示 AI 代改：「你幫我」）
- Part：C
- 關聯：process-log「Q4 即時鏈路用 Eventhouse」「業務知識不足的題目採用 AI 建議」（Q5）；素材見 `notes/part_c/tentative-decisions.md`「Q4」「Q5」

## 背景
題目要求「訂單事件的準即時儀表板（分鐘級）」。Part A 只有每日批次，**即時鏈路在 Part A 沒有任何證據**（`part-a-evidence.md` E21），是全新設計。

要先知道的白話版：
- **Eventstream**：Fabric 裡收事件的管子，從 Kafka 等來源收進來，送到目的地
- **Eventhouse／KQL database**：專門存「一直進來的事件」的資料庫，查詢語言是 KQL（不是 SQL），寫進來幾秒內就能查
- **Real-Time Dashboard**：直接查 Eventhouse 的儀表板，有新資料進來就自動更新

Part A 的資料品質問題在即時鏈路也會出現：
- 撞號：增量檔中 order_id 已在 base 的列每天 602～603 筆（E4）
- 晚到：L4 有 25 張單是先送 cancelled、隔天才送較舊的 paid（E5）

Fabric 的事實：
- Eventstream 傳遞保證是 at-least-once（F1-11），內建轉換沒有去重運算子（fabric-facts 未查到第 6 條），所以同一事件送兩次是正常情況，要在下游處理
- Eventhouse 的 materialized view 可用 `arg_max(updated_at, *) by order_id` 取每張單最新一列（F2-8）；直接查 view 永遠是最新結果（F2-10）
- Real-Time Dashboard 直接用 KQL 查 Eventhouse，偵測到新資料就更新（F3-1、F3-2）；文件沒給最小更新間隔（未查到第 5 條）
- Eventhouse 的資料可透過 OneLake availability 以 Delta 給其他引擎讀，但延遲最少 5 分鐘、預設最多 3 小時（F2-2）
- Eventstream 也能直接寫 Lakehouse Delta 表（F1-7）
- Spark Structured Streaming 正式環境要用 Spark Job Definition＋retry，retry 有 90 天壽命上限，到期要手動重啟（F10-1～F10-3）

## 選項
| 選項 | 好處 | 代價 |
|---|---|---|
| A. Eventstream → Eventhouse（KQL）→ Real-Time Dashboard | 官方為即時場景設計的組合；寫入到可查是秒級；去重取最新有官方用例（F2-8）；不用寫程式維運串流作業 | 團隊要學 KQL；取最新、擋重送的規則要用 KQL 再寫一次，和 Part A 的 PySpark 規則是兩份，可能不一致 |
| B. Spark Structured Streaming（或每分鐘微批次）寫 Lakehouse，報表走 Direct Lake | 規則可以重用 Part A 的 PySpark 程式，只有一份；全部資料在同一個 Lakehouse | 要自己維運長時間執行的串流作業（retry 90 天上限，F10-3）；小檔案問題要調 trigger（F10-4）；Direct Lake 的 framing 與 Power BI 刷新能否穩定做到分鐘級沒有查證 |
| C. Eventstream 直接寫 Lakehouse Delta，報表走 Direct Lake | 不用寫程式；資料只在 Lakehouse | Eventstream 沒有去重，重送與晚到的舊狀態直接落表，要另外排程清理；分鐘級是否做得到同 B，沒有查證 |
| D. MSSQL Mirroring 複寫成 Delta 表，報表走 Direct Lake | 不用改上游、不用 Kafka；變更最快每 15 秒發布（F9-5） | 產出是資料表不是事件；接 Direct Lake 後的端到端延遲沒查證；自家機房 SQL Server 防火牆後要 gateway（F9-3） |

## 決定〔使用者撰寫〕
A：Eventstream → Eventhouse（KQL）→ Real-Time Dashboard。（使用者 2026-10-26 在對話中選定；狀態已於 2026-10-26 改為已定案）

（先前 AI 暫定）〔AI 原草稿，已被上方定案取代〕AI 暫定：A。規劃階段原本說「這題 AI 不給單一建議，看使用者對 KQL 的把握」；使用者不在場，為了畫第一版架構圖先暫定 A。**使用者若不熟 KQL、不想在面談被追問 KQL，選 B 是正當取捨**。

## 理由〔使用者撰寫〕
使用者原話：「多學 KQL，換到省心和秒級」（這句沿用 AI 前一則提出的對比框架「多學 KQL，換到省心和秒級／不學新的，換到要自己顧常駐程式」，由使用者選定）。討論中使用者也說過：「我認為重要的是思考方式不是sql or kql」。

背景（AI 整理，供使用者改寫）：使用者不熟 KQL；兩方案在 Fabric 都吃同一份 capacity、資料持續進來時都整天耗用，成本不是決定因素（`notes/part_c/realtime-cost.md`）；B 要自己顧常駐串流作業（retry 90 天上限，F10-3），分鐘級沒查證。

（先前 AI 暫定的理由草稿，保留對照）〔AI 原草稿，已被上方定案取代〕AI 暫定的理由草稿：分鐘級是硬需求。B、C 在寫入當下不處理重送與晚到，要另外清理；D（Mirroring）直接複寫來源表，本來就是最新狀態、也沒有重送問題，和 A 的真正差別是 D 接 Direct Lake 後的端到端延遲沒有查證，而 A 的儀表板直接查 Eventhouse、寫入後就能查（F2-10、F3-1）。代價是規則要寫兩份，用「即時標初估、以日報為準、每天對帳」控制（Q5）。

## 後果
- 選 A：
  - Eventhouse 建一張原始事件表（只 append）與一個 `arg_max(updated_at, *) by order_id` 的 materialized view，儀表板查 view，不查原始表
  - 即時層**不處理撞號**（要比對歷史訂單，屬於日批的工作），儀表板標「初估，以次日日報為準」；每天對帳即時與日報的訂單數、金額
  - 晚到的舊狀態（L4 那種）被 `arg_max` 自然忽略，因為它的 updated_at 比較舊。但同一張單兩個事件的 updated_at 相同、或上游時鐘偏差時，取到的不一定是真的最新狀態；對策是上游給事件帶遞增版本號，改用版本號取最新（A-3 建議「狀態帶版本號」，E18）
  - Eventhouse 的保留期設短（例如 30 天），長期資料以 Lakehouse 為準（F2-4：預設保留 3,650 天）
  - 問數服務若要回答「今天到目前為止」的問題，自建問數服務可以另外連 Eventhouse 查 KQL（Q7 已選自建；未設計），但第一版不開，問數只回答日批資料
- 選 B：Part A 的 `transform_order_batch` 要改成可串流呼叫；要建串流作業的監控與重啟流程
- 選 C：要另外排程把重送與舊狀態清掉，等於在 Lakehouse 再做一次 B 的工作
- 選 D：不用 outbox 與 Kafka，上游不用改程式；要實測 Mirroring＋Direct Lake 的端到端延遲是否在分鐘級；自家機房 SQL Server 要 gateway（F9-3）；儀表板看的是「表的現況」而不是事件，狀態變化的歷程看不到
