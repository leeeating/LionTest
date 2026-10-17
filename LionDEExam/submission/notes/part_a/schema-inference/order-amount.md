# 訂單的金額、幣別與參照

回到：[README.md](README.md)｜問題總表：[issues.md](issues.md)

**結論**：
- 一條從資料反推的比值規則「金額換算台幣 ≈ 定價 × 數量 × [0.84, 1.29]」能把 base 的錯誤金額和正常列完全分開：負數 50（V1）、約多乘 1,000 的 40（V2）、產品不在主檔的 120（V6），沒有灰色地帶。
- base 的 NTD 200 筆是 TWD 的別名（V4）；coupon_discount = -1.0 的 300 筆是「未知」的哨兵值（V3），代表「沒有折扣」還是「折扣未知」待使用者判斷（J5）。
- amount 是折扣前還是折扣後，資料推不出來（J10）。
- 其餘是可能合法的狀況：JPY 帶小數（L5）、訂到已下架產品（L6）、同名不同產品（L7）、TWD 不在匯率表（L12）。

<a id="ratio"></a>
## 比值規則（V1、V2、V6 的共同工具）

- 規則（推測的隱含業務規則，非 DDL 能表達）：金額 × 下單日匯率 ≈ 產品定價 × 數量 × [0.84, 1.29]（amount、products.base_price_twd、quantity）。
- 0.84～1.29 是觀察到的範圍，[0.8, 1.3] 是偵測用的寬鬆門檻。
- 依據：13 個「來源檔×幣別」組合的比值最小～最大值（min_r～max_r）都落在 0.8378～1.2839；落在 [0.8, 1.3] 以外的列只有負數 50、約 ×1000 共 40、缺產品 120。
  <sub>證據：剖析輸出搜尋 `S4.ratio_dist`、`S4.ratio_buckets`</sub>
- 比值的算法：`orders_ratio.ratio = amount × 同日匯率（TWD/NTD 以 1） ÷ (base_price_twd × quantity)`。
- 偵測查詢（節錄；完整見 stdout）：
  ```sql
  SELECT src, currency,
    CASE WHEN ratio IS NULL THEN 'no_ratio(缺產品或匯率)'
         WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative, |ratio| in normal range'
         WHEN ratio < 0 THEN 'negative, other'
         WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
         WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about x1000 (ratio/1000 in normal range)'
         ELSE 'other_outlier' END AS bucket,
    count(*) AS n
  FROM orders_ratio GROUP BY 1, 2, 3 HAVING bucket <> 'normal' ORDER BY src, currency, bucket
  ```
  <sub>證據：剖析輸出搜尋 `S4.ratio_buckets`</sub>
- **值得質疑 Q1（比值模型是從資料反推的）**：「amount ≈ 定價 × 數量 × [0.84, 1.29]」只是觀察到的分布，不是官方規則。它讓 V1、V2 看起來非常乾淨，但如果真實系統允許整單折價或加購，這條規則就太嚴。另外，比值用的是**下單日**的匯率；若原系統用付款日匯率，USD/JPY 的比值會小幅偏移（匯率日變動 < 1.1%，影響不大）。
- **值得質疑 Q6（`percentile_approx` 是近似值）**：本次的 p25／p50／p75／p99 與既有筆記（Python 精確分位數）有小差異（見下一點），不影響任何違反的判定（判定都用精確的比較條件，不靠分位數）。
- 與既有筆記的數字差異：`dictionary.md`「amount 分布」記 base TWD p50 202,880、p99 837,563；本次 TWD p50 202,826、p99 836,821。本次用 Spark `percentile_approx`（近似），既有用 Python 排序後取索引。最小值、最大值、負數筆數完全一致。
  <sub>證據：剖析輸出搜尋 `S4.amount_dist`</sub>

<a id="v1"></a>
## V1｜orders_base.amount 為負數（50 筆）〔確定的錯誤值〕

- 違反：`CHECK (amount > 0)`。
- 影響：base 50 筆（TWD 29、USD 17、JPY 4）；增量檔 0 筆。
  <sub>證據：剖析輸出搜尋 `S4.amount_dist`（`n_neg`）</sub>
- 為什麼確定：
  - 負號拿掉後與正常列完全一樣：50 筆的比值絕對值全落在正常區間 [0.8, 1.3]（TWD 29 + USD 17 + JPY 4）。
  - 不是「原單＋沖銷單」：同一個 order_id 沒有任何正數列（`same_id_has_positive_row` 全 0）。
  - 狀態分布 cancelled 7、completed 18、created 6、paid 19，不集中在某種狀態。
  <sub>證據：剖析輸出搜尋 `S4.ratio_buckets`（`negative, |ratio| in normal range`）、`S4.neg_status`</sub>
- 偵測查詢：見上方 [比值規則](#ratio) 的查詢。
- 範例：`ORD00000900 cancelled TWD -172833.0 qty 1 base_price 170000 ratio -1.0167`；`ORD00002319 completed TWD -216020.0 qty 3 base_price 63000 ratio -1.143`；`ORD00002817 completed TWD -26515.0 ratio -0.8838`。
  <sub>證據：剖析輸出搜尋 `S4.neg_examples`</sub>
- 連帶：折扣大於訂單台幣金額的 50 列，全部就是這 50 筆負數（`50 / of_which_negative_amount 50`），不是獨立問題。
  <sub>證據：剖析輸出搜尋 `S4.coupon_vs_amount`</sub>

<a id="v2"></a>
## V2｜orders_base.amount 約多乘 1,000（40 筆）〔確定的錯誤值〕

- 違反：隱含規則「amount 換算台幣 ≈ 定價 × 數量 × [0.84, 1.29]」。
- 影響：base 40 筆（TWD 27、USD 9、JPY 4）。
  <sub>證據：剖析輸出搜尋 `S4.ratio_buckets`（`about x1000`）</sub>
- 為什麼確定：40 筆的比值除以 1000 全部回到正常區間；TWD、JPY 的 31 筆都是 1000 的倍數，USD 9 筆都是 10 的倍數但不是 1000 的倍數，符合「小數 2 位的 USD 金額 × 1000」。極端值例：`ORD00095841 JPY 3738074000.0 qty 4 base_price 190000 ratio 1007.4 → ÷1000 = 1.0074`。
  <sub>證據：剖析輸出搜尋 `S4.x1000_mult`、`S4.x1000_examples`</sub>
- 偵測查詢：同 V1。
- 範例：`ORD00095841 JPY 3738074000.0`、`ORD00084134 JPY 2308721000.0`、`ORD00060205 JPY 1903148000.0`。
  <sub>證據：剖析輸出搜尋 `S4.x1000_examples`</sub>
- 與既有筆記的差異：既有筆記用「超過該幣別 p99 兩倍」判斷，同樣得到 40 筆；本次改用定價比值，40 筆與正常列之間沒有灰色地帶（沒有任何 `other_outlier`）。
  <sub>證據：剖析輸出搜尋 `S4.ratio_buckets`</sub>
- **值得質疑 Q2（×1000 的 USD 9 筆不是 1000 的倍數）**：我把它解釋成「2 位小數的 USD × 1000」，這是推論；也可能是「把 TWD 金額誤標成 USD」之類的別種錯誤。不過 TWD 誤標 USD 的話比值會約 ×31，不是 ×1000，所以目前證據支持 ×1000。

<a id="v4"></a>
## V4｜orders_base.currency = 'NTD'（200 筆）〔確定的錯誤值〕

- 〔使用者判斷〕NTD 當成 TWD（匯率 1）。金額處理整體決定見 process-log「金額：原幣別與換算 TWD 都存」。

- 違反：`CHECK (currency IN ('TWD','USD','JPY'))`（NTD 不是 ISO 4217 代碼，增量檔沒有）。也不在匯率表（base NTD 200）。
  <sub>證據：剖析輸出搜尋 `S7.currency_not_in_fx`</sub>
- 為什麼確定是 TWD 的別名：以 1:1 換算時，NTD 的比值分布與 TWD 幾乎相同（NTD p01 0.8537 / p50 1.0347 / p99 1.2406；TWD 0.8541 / 1.0506 / 1.246），NTD 都是整數金額。若 NTD 是別的幣別，比值會整體偏移。NTD 分散在四個通路。
  <sub>證據：剖析輸出搜尋 `S4.ntd`、`S2.amount_decimals`、`S4.ntd_examples`</sub>
- 偵測查詢：`SELECT src, currency, count(*) AS n FROM orders_t GROUP BY src, currency ORDER BY src, currency`
  <sub>證據：剖析輸出搜尋 `S3.currency`</sub>
- 範例（各通路最小 id）：`ORD00000163`（app）、`ORD00000677`（web）、`ORD00001883`（門市）。
  <sub>證據：剖析輸出搜尋 `S4.ntd_examples`</sub>

<a id="v3"></a>
## V3｜orders_base.coupon_discount = -1.0（300 筆）〔未知值的哨兵〕〔新發現〕

- 違反：`CHECK (coupon_discount BETWEEN 0 AND 950 AND coupon_discount % 50 = 0)`。
- 影響：base 300 筆；增量檔 0 筆。負值只有 `-1.0` 一種（`negative_values [-1.0]`、`n_not_multiple_of_50 300`）。
  <sub>證據：剖析輸出搜尋 `S3.coupon`</sub>
- 為什麼確定：
  - 其餘列（增量檔全部、base 其他列）都是 0～950 的 50 倍數，不是 50 倍數的只有 base 這 300 筆；`-1` 是常見的「未知／未填」哨兵值。
  - 狀態、幣別分布散開；與負數金額只重疊 1 列、與 ×1000 只重疊 1 列。
  - **它代表「沒有折扣」還是「折扣未知」推不出來**，見 J5。
  <sub>證據：剖析輸出搜尋 `S3.coupon`、`S3.coupon_neg_profile`、`S4.overlap_anomalies`</sub>
- 偵測查詢：
  ```sql
  SELECT src, count(DISTINCT coupon_discount) AS n_distinct, min(coupon_d) AS min_v, max(coupon_d) AS max_v,
    sum(CASE WHEN coupon_d < 0 THEN 1 ELSE 0 END) AS n_negative,
    sum(CASE WHEN coupon_d = 0 THEN 1 ELSE 0 END) AS n_zero,
    sum(CASE WHEN coupon_d % 50 <> 0 THEN 1 ELSE 0 END) AS n_not_multiple_of_50,
    collect_set(CASE WHEN coupon_d < 0 THEN coupon_discount END) AS negative_values
  FROM orders_t GROUP BY src ORDER BY src
  ```
  <sub>證據：剖析輸出搜尋 `S3.coupon`</sub>
- 範例：`ORD00000203 paid TWD 149425.0 -1.0`、`ORD00000392 completed TWD 28478.0 -1.0`、`ORD00000576 completed TWD 38366.0 -1.0`。
  <sub>證據：剖析輸出搜尋 `S3.coupon_neg_examples`</sub>

<a id="j5"></a>
## J5｜coupon_discount = -1.0 代表什麼〔待使用者判斷〕

「沒有用折扣」（等同 0）還是「折扣金額未知」。資料裡 0 本身就有 4,942 列（base `n_zero`），所以 -1 不是「沒有折扣」的唯一表示法；這點傾向「未知」，但無法證實。

<sub>證據：剖析輸出搜尋 `S3.coupon`</sub>

<a id="j10"></a>
## J10｜amount 是折扣前還是折扣後〔待使用者判斷〕

目前無法從資料確認。用比值檢查：
- 若金額是折扣後，折扣高的訂單比值應該偏低；實際上折扣 500～950 組的平均比值 1.0504，反而略高於沒有折扣組的 1.0488。
- TWD/NTD 中折扣 = 0 與折扣 = 950 兩組的比值上下界幾乎相同（0.85～1.2498 vs 0.85～1.2499）。若金額是「定價區間 − 950」，950 組的下界應該被往下推。
- 但折扣平均只佔金額的 0.3%～0.9%（`avg_coupon_pct_of_amount`），比比值本身的散布（0.85～1.25）小一個量級，所以**這個檢查的鑑別力很弱**：資料傾向「金額與折扣各自獨立產生（像折扣前）」，但不能排除折扣後。需要向上游確認或由使用者判斷。

<sub>證據：剖析輸出搜尋 `S4.coupon_vs_ratio`、`S4.ratio_edges`</sub>

```sql
SELECT CASE WHEN coupon_d < 0 THEN 'coupon=-1' WHEN coupon_d = 0 THEN 'coupon=0'
            WHEN coupon_d <= 450 THEN 'coupon 50~450' ELSE 'coupon 500~950' END AS coupon_bucket,
  count(*) AS n, round(avg(ratio), 4) AS avg_ratio, round(percentile_approx(ratio, 0.5), 4) AS p50_ratio,
  round(avg((amount_d * fx + coupon_d) / (bp * qty_i)), 4) AS avg_ratio_if_add_back_coupon,
  round(avg(coupon_d / (amount_d * fx)) * 100, 3) AS avg_coupon_pct_of_amount
FROM orders_ratio WHERE ratio BETWEEN 0.8 AND 1.3 GROUP BY 1 ORDER BY 1
```

<a id="l5"></a>
## L5｜base 中 JPY 金額帶非零小數〔可能合法〕〔新發現〕

- 影響：80 列（其餘 10,942 列 JPY 都是整數；增量檔 JPY 全整數）。
- 為什麼可能合法：80 列的比值都在正常區間（比值檢查沒有列出它們），金額量級正確；DB 欄位若是 DECIMAL(14,2) 就存得下。也可能是上游換算誤差。範例 `ORD00004243 JPY 1829614.9`、`ORD00004874 JPY 313363.86`。

<sub>證據：剖析輸出搜尋 `S2.amount_decimals`、`S2.jpy_fraction_examples`、`S4.ratio_buckets`</sub>

<a id="v6"></a>
## V6｜orders_base.product_id 不在產品主檔（120 筆）〔確定的錯誤值〕

- 違反：`REFERENCES products(product_id)`。
- 影響：base 120 列、120 個不同 id，全部 `P9xxxx`（P91064～P99990），主檔是 P00001～P00300；四種狀態都有；增量檔 0 筆。這 120 列也就是比值檢查中算不出比值的列（`no_ratio`：TWD 76 + USD 23 + JPY 21 = 120）。
  <sub>證據：剖析輸出搜尋 `S7.fk`、`S7.unknown_products`、`S4.ratio_buckets`</sub>
- 偵測查詢：
  ```sql
  SELECT count(*) AS n_rows, count(DISTINCT product_id) AS n_ids, min(product_id) AS id_min, max(product_id) AS id_max,
    sum(CASE WHEN product_id RLIKE '^P0\\d{4}$' THEN 1 ELSE 0 END) AS looks_like_P0xxxx,
    collect_set(order_status) AS statuses
  FROM orders_t o WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id = o.product_id)
  ```
  <sub>證據：剖析輸出搜尋 `S7.unknown_products`</sub>
- 範例：`ORD00003151 P95718 TWD 210244.0`、`ORD00004247 P93453 USD 833.48`、`ORD00004396 P98236 JPY 433408.0`。
  <sub>證據：剖析輸出搜尋 `S7.unknown_products_examples`</sub>

<a id="l6"></a>
## L6｜訂單的產品 `is_active = 'N'`〔可能合法〕

- 影響：base 4,270、day1 184、day2 182、day3 195。
- 為什麼可能合法：is_active 是主檔目前狀態，下架前成立的訂單合理；增量檔也有這種列（未區分新單與舊單），需確認 is_active 的語意。

<sub>證據：剖析輸出搜尋 `S7.fk`（`product_inactive`）</sub>

<a id="l7"></a>
## L7｜同一 product_name 對應多個 product_id，定價不同〔可能合法〕〔新發現〕

- 影響：44 個名稱（253 個名稱 / 300 個 id）。例：`P00098` / `P00262` 都叫「伊斯坦堡1日票券」，定價 144000 / 197000。
- 為什麼可能合法：不同供應商或檔期的同名產品。

<sub>證據：剖析輸出搜尋 `S6.products_pk`、`S6.products_dup_name_examples`</sub>

<a id="l12"></a>
## L12｜TWD 不在 fx_rates〔可能合法〕

- 影響：base TWD 66,690 + NTD 200 = 66,890；增量檔 3,069 / 3,150 / 3,141。
- 為什麼可能合法：本幣匯率恆為 1，主檔不列是常見設計；不是資料錯誤，但 join 時會漏掉。

<sub>證據：剖析輸出搜尋 `S7.fk`（`currency_not_in_fx`）、`S7.currency_not_in_fx`</sub>
