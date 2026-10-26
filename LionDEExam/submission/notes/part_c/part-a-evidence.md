# Part A 證據摘錄（Part C 論據用）

- 來源：2026-10-19 Explore subagent（sonnet）讀 Part A 繳交物整理，每條附出處；主 session 未逐條重開核對，引用前以出處原文為準
- 注意：`part_a/model.md` 與部分 notes 仍是 base 後的舊數字（fact 100,000 列）。最新數字以 `part_a/README.md` 與 `part_a/data-quality-report.md` 為準（三天後 fact 112,010 列）

| # | 事實 | 出處（可搜尋原文） |
|---|---|---|
| E1 | 7 個 CSV：orders_base、day1～3、members、products、fx_rates | `notes/dataset/README.md`「有 7 個 CSV」 |
| E2 | base 100,040 列；增量每天約 4,600～4,700 列（4,615／4,700／4,615） | `part_a/README.md` 對帳表 |
| E3 | demo 資料不代表正式環境的量 | ADR-01「不代表 prod 的資料量」 |
| E4 | 撞號：增量中 order_id 已在 base 的列每天 602～603 筆；當 noise 隔離 | ADR-03「day1 603 列、day2 602 列、day3 603 列」 |
| E5 | 晚到事件 L4：25 張單 day1 cancelled、day2 送來較舊的 paid，略過、fact 不變 | `part_a/README.md`「L4 的 25 張單」 |
| E6 | 晚到新單 L3：60 張 6 月新單 7/2 才送到，約 1,132 萬台幣；6 月營收在 7/2 之後還會變 | `data-quality-report.md`「6 月的訂單 7/2 才送到」 |
| E7 | fact_order 一張訂單一列存最新狀態；沒有 bronze 層，歷程只在原始增量檔 | ADR-04「後果」 |
| E8 | 營收 `amount` 是折扣前；`net_amount_twd = amount_twd − coupon_discount`；coupon -1 轉 NULL | `part_a/README.md`「折扣前，J10」 |
| E9 | 40 張疑似金額 ×1000，佔 5～6 月營收 28.09%、訂單 0.04%；照原樣寫入，另列 `amount_review` | `data-quality-report.md`「28.09%」 |
| E10 | 時區固定 Asia/Taipei；6,002 筆非標準時間寫法，1,003 筆直接讀字面日期會差一天 | `data-quality-report.md`「6,002 筆」 |
| E11 | 28,578 張訂單在最後一次更新（標成已完成的當下）時出發日還沒到（10,324,629,272.48 TWD）；原報告警告「不要誤讀成這些訂單到現在都還沒出團」，以 07-01 為基準其中 6,147 張出發日已過。「已完成」不等於「已出團」（第 1 輪審查 T5 更正了原本的轉述） | `data-quality-report.md`「基準是“標成已完成的當下”」 |
| E12 | 會員只有月快照（04-30、05-31、06-30），SCD2 valid_from 取快照日不是實際變動日 | `part_a/model.md`「看不到會員實際變動日」 |
| E13 | 幣別換算用台北下單日當天匯率；找不到匯率進隔離表；NTD 200 張當 TWD | `part_a/model.md`「## 5. 金額」 |
| E14 | 隔離表 `quarantine_order`：batch_id、原始字串、`reject_category`、`reject_reasons` | `part_a/model.md` |
| E15 | 每批對帳「輸入＝寫進 fact＋隔離＋略過」，不平就在寫入前報錯；業務版「計入報表＋擋下待查＋不採用」 | `part_a/README.md`、`data-quality-report.md` |
| E16 | schema 合約 `contracts.py`：欄名、型別、nullable、值域（allowed_values 等）；沒有逐欄業務描述，業務說明在 `model.md` 欄位表 | `part_a/pipeline/contracts.py` 的 `ORDERS_SCHEMA` |
| E17 | 現有表：fact_order、dim_member（SCD2）、dim_product、dim_date＋quarantine_order、amount_review、batch_log、batch_start | `part_a/README.md` |
| E18 | A-3 給上游建議：會員變動時間或異動紀錄（CDC）、冪等鍵與唯一索引、未知值用 NULL、時間帶時區、狀態帶版本號用 outbox 或 CDC | `data-quality-report.md`「## 給上游的建議」 |
| E19 | ADR-01：選 PySpark＋Delta，因為正式環境在 Fabric 不用重寫；Part A 表結構可直接當 Part C 的 Lakehouse 層 | ADR-01「後果」 |
| E20 | ADR-05：重跑用 Delta time travel，VACUUM 後讀不到；Fabric 相容未實測 | ADR-05「Fabric 相容」 |
| E21 | 「分鐘級即時」在 Part A 沒有任何證據，即時鏈路的設計全部是新的 | Explore 搜過 `即時`、`streaming`、`Eventstream` 皆無 |
