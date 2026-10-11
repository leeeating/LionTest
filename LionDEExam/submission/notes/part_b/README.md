# Part B 筆記：buggy_pipeline.py

回到入口：[../README.md](../README.md)｜正式報告：[../../part_b/code-review.md](../../part_b/code-review.md)

**這支程式在做什麼**：每天跑一次的訂單 ETL。它讀當天的增量訂單 CSV，整理成事實表 `fact_order` 給 BI 和 AI 應用查詢，同時用 SCD2 維護會員維度表 `dim_member`。

**流程**：讀 CSV → 訂單去重 → 換算台幣 → 更新會員維度 → join 會員和產品 → 寫入事實表。只有「更新會員維度」和「寫入事實表」兩步會改到既有資料。

**結論**：不可部署。

**在資料流中的位置**：讀寫哪些 OneLake 路徑、各步驟碰到哪些表，見 [pipeline-context.md](pipeline-context.md)。

## 問題清單

| # | 嚴重度 | 問題 | 細節 |
|---|---|---|---|
| 1 | P2 | CSV 不指定 schema，全部欄位是字串 | 報告 4.1 |
| 2 | P0 | 去重保留任意一筆，不是最新狀態 | [dedup.md](dedup.md)、報告 4.2 |
| 3 | P1 | `filter(F.col("amount") > 0)` 靜默丟掉 0 元和負數訂單 | 報告 4.2 |
| 4 | P0 | 匯率 inner join 丟掉全部 TWD 訂單（約 2/3） | 報告 4.3 |
| 5 | P2 | Python UDF 做乘法，null 被當成 0 | 報告 4.3 |
| 6 | P0 | SCD2 實作錯誤：整張 dim_member 被覆寫成只剩變更會員、沒關舊版、新會員進不來、null 比較 | [scd2.md](scd2.md)、報告 4.4 |
| 7 | P0 | 事實表 join 原始會員快照，會一對多放大 | 報告 4.5 |
| 8 | P1 | 產品 inner join 靜默丟單 | 報告 4.5 |
| 9 | P0 | 事實表用 append：重跑會重複，跨日訂單更新也會重複 | 報告 4.6 |
| 10 | P1 | 「驗證」沒有斷言，還把整張表 collect 到 driver | 報告 4.6 |
| 11 | P1 | dim 和 fact 寫入不是原子操作；batch_date 預設 "day1" | 報告 4.7 |
