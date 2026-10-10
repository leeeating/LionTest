# 為什麼不能直接去重

回到入口：[README.md](README.md)

## 一句話

**要去重沒錯，錯在方法**：同一張訂單有多列時，要留 `updated_at` 最新的那一列，`dropDuplicates` 卻是隨便留一列。

## 例子

增量檔記的是**事件**，不是訂單。一張單從下單、付款到完成，每變一次狀態就多一列（官方 README：「同一 `order_id` 可能出現多次，以 `updated_at` 區分新舊」）。事實表要的是每張單的最新狀態，所以一個 order_id 只能留一列。

白話版：同一張訂單有兩張單據，一張寫「已付款」，一張寫「已取消」。正確做法是看日期，留最新的那張；`dropDuplicates` 則是閉著眼睛隨便抽一張。

**Python 類比**：`dropDuplicates(["order_id"])` 就像 `{r["order_id"]: r for r in rows}`，留下哪一列取決於讀進來的順序。Spark 是分散式的，順序每次都可能不同，所以同樣的輸入重跑，結果可能不一樣。

## 這份程式的問題

`clean_orders`：
- `dropDuplicates(["order_id"])` 放在按時間排序的 window **前面**。到 window 那一步，每個 order_id 只剩一列，排序已經沒作用。
- window 用 `orderBy(F.col("order_created_at").desc())`（下單時間）排序。照官方語意，同一張單的多次更新下單時間都一樣，應該用 `updated_at`。

資料佐證：day1 有 18 個 order_id 重複，`updated_at` 都不同。其中 15 組除了 `updated_at` 以外完全相同，狀態也一樣。例如 `ORD00005192` 兩列都是 completed，`updated_at` 只差 26 秒，`dropDuplicates` 留哪一列不確定。

**更深的坑**：18 組裡有 3 組（`ORD00036457`、`ORD00047034`、`ORD00076774`）連下單時間、會員、金額都不同。例如 `ORD00036457` 一列是 M002150 的 completed 訂單，另一列是 M000272 的 cancelled 訂單。官方 README 定義同一 order_id 以 `updated_at` 區分新舊；若照此語意，取最新那一列即可，但同一張單的更新不應該改掉下單時間和會員，所以這是**與官方語意不符的現象，需向上游確認**。同樣的現象也出現在報告 #3 的 603 列：day1 和 base 同 order_id 的列，這三欄沒有一列跟 base 相同（例如 `ORD00005192` 在 base 是 05-06、M007765、10230.87，在 day1 是 05-04、M005173、6927）。order_id 是否可作為唯一鍵，留待 Part A 以 ADR 定案；確認之前，這種列先送隔離表。

## 建議修法

拿掉 `dropDuplicates`，只用 window 按 `updated_at` 由新到舊排序，每個 order_id 取第一筆；關鍵欄位對不上的重複列另外隔離。程式碼見報告 4.2。
