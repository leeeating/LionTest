# coupon_discount 的幣別

**結論〔使用者判斷〕：coupon_discount 是台幣（TWD），不跟著訂單的幣別。** 使用者原話：「coupon 當 TWD，三種幣別面額一樣」。

## 為什麼要判斷
〔2026-10-24 更正〕原本這裡寫「官方 README 沒有說明 coupon_discount 的幣別」，這是錯的：`candidate_package/README.md` 的欄位說明寫著 “`coupon_discount`（TWD）”。整理業務假設文件的 agent 比對官方 README 時發現。使用者的結論（coupon 是 TWD）和官方說明一致，下面的資料證據仍然成立，現在是佐證官方說明，而不是唯一依據。

當時以為官方沒有說明 coupon_discount 的幣別。fact_order 存的是原值，沒有換算。如果之後要算「折扣後的台幣營收」，就要先知道 coupon 能不能直接拿台幣去減，還是要先換匯。

## 證據
**1. 三種幣別的面額完全一樣**

| 幣別 | 筆數 | 不同值的個數 | 最小 | 最大 | 正數平均 | 訂單金額中位數 | coupon 大於訂單金額的筆數 |
|---|---|---|---|---|---|---|---|
| JPY | 11,022 | 21 | -1.0 | 950.0 | 495.1 | 972,503.5 | 4 |
| NTD | 200 | 20 | 0.0 | 950.0 | 494.4 | 222,540.5 | 0 |
| TWD | 66,690 | 21 | -1.0 | 950.0 | 499.8 | 202,872.0 | 29 |
| USD | 22,128 | 21 | -1.0 | 950.0 | 499.7 | 6,445.2 | 785 |

每種幣別的值都是 0～950，以 50 為一級，共 20 種；另外 TWD、USD、JPY 還有 `-1.0`（V3）。各級的筆數也大致平均。USD 和 JPY 的匯率差了約 150 倍，coupon 如果用訂單幣別計價，各幣別的面額不可能剛好相同。

**2. 當成訂單幣別會出現不合理的結果**
- USD 訂單有 785 筆的 coupon 大於訂單金額。如果 coupon 的單位是 USD，折扣就比售價還高。
- JPY 訂單如果 coupon 的單位是日圓，500 日圓約等於 100 台幣，相對於中位數 97 萬日圓的訂單幾乎沒有折扣效果。
- 當成台幣則合理：500 台幣約等於 16 USD，對中位數 6,445 USD 的訂單來說是小額折扣。

## 限制
- 這是合成資料。三種幣別分布一樣，也可能只是產生資料時沒有考慮幣別。不過不論原因是哪一種，「當成台幣」都比「當成訂單幣別」合理。
- amount 是折扣前還是折扣後（J10）還沒決定，這會影響 coupon 要不要再扣一次。

## 查詢與輸出
2026-10-18 在 repo 根目錄執行（`uv run python -I -`，DuckDB 直接讀 CSV，全部欄位讀成字串）：

```python
import duckdb
d = 'LionDEExam/candidate_package/dataset/orders_base.csv'
con = duckdb.connect()
con.execute(f"create view o as select * from read_csv('{d}', all_varchar=true)")
print(con.sql("""select currency, count(*) n,
 count(distinct coupon_discount) n_vals,
 min(try_cast(coupon_discount as double)) mn, max(try_cast(coupon_discount as double)) mx,
 round(avg(try_cast(coupon_discount as double)) filter (where try_cast(coupon_discount as double)>0),1) avg_pos,
 round(median(try_cast(amount as double)),1) med_amt,
 sum(case when try_cast(coupon_discount as double) > try_cast(amount as double) then 1 else 0 end) coupon_gt_amt
 from o group by 1 order by 1"""))
print(con.sql("""select currency, coupon_discount, count(*) n from o group by 1,2 order by 1, n desc"""))
```

第一段的輸出就是上方的表格。第二段（節錄）：JPY 的 20 種面額各約 487～590 筆、`-1.0` 有 39 筆；NTD 的 20 種面額各 5～14 筆；TWD 的 20 種面額各約 3,277～3,408 筆。

注意：base 包含 V7 的 40 列重複，所以這裡的筆數（例如 TWD 66,690）比 fact 中的筆數（TWD 66,661）多。
