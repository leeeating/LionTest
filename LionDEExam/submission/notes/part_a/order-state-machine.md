# 訂單狀態機（候選版）

官方 README 定義 `order_status` 有 4 個值：created、paid、completed、cancelled。本檔畫出這 4 個狀態之間可能的轉移，標明哪些有資料證據、哪些要靠業務判斷。**還沒定案**：下方「待決定」三題（第 1 題就是 ⑤）由使用者判斷。

## 前提假設〔使用者判斷〕
**訂單流程單向：取消後不能恢復。** 使用者原話：「那先簡單假設不能恢復」（process-log「假設訂單流程單向：取消後不能恢復」）。題目沒有說明這條業務規則，是本專案的假設。若業務允許恢復，fact_order 的型態與上游唯一鍵都要重新考慮（見 [`learning/1-modeling/fact-table-types.md`](../../learning/1-modeling/fact-table-types.md)）。

## 狀態圖

```
                ┌──────────┐
                │ created  │
                └────┬─────┘
             ①      │       ②
        ┌────────────┼────────────┐
        ▼                         ▼
   ┌─────────┐               ┌───────────┐
   │  paid   │──────③──────▶│ cancelled │
   └────┬────┘               └───────────┘
        │ ④                       ▲
        ▼                         ┊ ⑤ ?
   ┌───────────┐                  ┊
   │ completed │┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘
   └───────────┘
```

實線是候選的合法轉移，虛線 ⑤ 待決定。依單向假設，**不存在**的轉移：cancelled → 任何狀態、completed → paid、paid → created。

## 每條轉移的證據

「同一張單」指同一個 `order_id`，且會員、金額、下單時間都相同；會員不同的同 id 列是撞號，不算同一張單（見 [schema-inference/order-identity.md](schema-inference/order-identity.md) 的 J2）。

| 轉移 | 業務意思 | 資料證據 |
|---|---|---|
| ① created → paid | 付款 | 沒有直接證據 |
| ② created → cancelled | 未付款就取消 | 沒有直接證據 |
| ③ paid → cancelled | 付款後取消 | **有**：day1→day2 的 25 組，照 `updated_at` 排序是 paid → cancelled（見 [schema-inference/order-time.md](schema-inference/order-time.md#l4) 的 L4） |
| ④ paid → completed | 完成 | 沒有直接證據 |
| ⑤ completed → cancelled | 完成後取消？ | 只出現在撞號列，不能當證據 |

**為什麼大部分轉移沒有證據：** demo 資料裡，同一張單狀態真的有變的只有那 25 組；其餘重複列都是同狀態重送（見 [schema-inference/order-identity.md](schema-inference/order-identity.md#j1) 的 J1）。demo 是合成資料，不能據此推論正式環境的狀態變化很少（process-log「不能用 demo 的變動量推論 prod 的狀態歷程」）。轉移要以業務流程為準。

**單向假設對那 25 組的影響：** 照檔案到達順序，這 25 組是 cancelled → paid；在單向假設下這個順序不可能發生，照 `updated_at` 的 paid → cancelled 才合理。以哪個為準仍是 J6，待使用者判斷。

## 待決定
1. ⑤ completed → cancelled 存在嗎？例如出團後才申請取消退款。
2. 有沒有 created → completed 的直接跳轉？例如現場付款的票券。
3. ~~`completed` 是指「出團完成」還是「交易完成」？~~ 〔使用者判斷〕先假設是**出團完成**（原話：「completed先假設成出團完成」）。**與資料衝突，待處理**：base 的 completed 全部在出發日之前（增量檔中只有與 base 撞號的 completed 列才有出發日已過的情形）（見 [schema-inference/order-time.md](schema-inference/order-time.md) 的 J8），照這個假設，completed 應該在出發日之後才出現，但 base 的 completed 共 28,612 列（base 100,040 列的 28.6%），出發日全部晚於 `updated_at` 的日期，這些列在此假設下都不合理。要把它們當成資料品質問題，還是回頭修正假設，待使用者判斷。
