# A-3 品質報告的第二輪獨立驗收

- 日期：2026-10-27
- 驗收者：fresh-context 驗收 agent（沒看過撰寫過程，也沒讀 process-log 的施工細節）
- 審查對象：`LionDEExam/submission/part_a/data-quality-report.md`（HEAD 版本，包含 451d585 定稿和之後 025fda4 的書面語改寫）
- 對照基準：`LionDEExam/submission/notes/part_a/a3-review-findings.md`（第一輪，結論「有條件過」）

## 結論：**過**（附 3 個低嚴重度建議，不影響數字正確性）

- **第一輪的 finding 全部處理了**：12 條裡 11 條已修，1 條部分修（內部事件標題「T6」還留在附錄 D 的「出處」欄，屬於可讀性問題）。
- **獨立重算了 21 組關鍵數字，全部吻合**（含百分比、筆數、金額，取到小數 2 位）。第一輪指出的「高估」基準問題，現在是 39.00%，基準是除以 1,000 修正後的金額，算法正確。
- **沒有找到結論超出證據的中高風險問題**。下方第 3 節列了 3 個低嚴重度的措辭和範圍問題。
- 臨時腳本放在 repo 外，沒有進 repo。做法是用 DuckDB 1.5.6 直接查 `LionDEExam/candidate_package/dataset/` 的 CSV，執行方式是 `.venv/bin/python -I`。我沒有使用報告附的 `profiling/data_quality_queries.py`，view 都自己寫（定義見第 2 節開頭）。

---

## 1. 第一輪 finding 逐條核對

| # | 第一輪 finding | 狀態 | 現版報告中可搜尋的片段 |
|---|---|---|---|
| M1 | L10 缺少反向證據（paid／created 的出發日已過） | **已修** | 正文 2.3「出發日已過、卻還是已付款的有 9,234 張，還是已建立的有 3,053 張」；附錄 B `[Q-L10.reverse]`；附錄 C「C-3 的基準說明」 |
| M2 | L3 有 5 張訂單在出發日過後才付款 | **已修**（寫在附錄，正文表格沒寫） | 附錄 F「其中 5 張是出發日已過才付款」；附錄 B `[Q-L3.paid_after_departure]` |
| M3 | V5 Z 格式跨日的筆數沒有量化 | **已修** | 正文 3.2「其中 1,003 筆若直接讀字面日期會差一天」；`[Q-V5.z_date_shift]` |
| M4 | 會員等級變動的模式與 V8 規則 | **已修** | 附錄 F「取較低等級時，跨快照的等級變動是 405 次都升一級；取較高時是 404 次升一級、1 次降級」；`[Q-MEM.level_moves]`、`[Q-V8.later_snapshot]` |
| M5 | L6 的增量筆數混入撞號列 | **已修** | 附錄 C 的 C-25「fact 4,267／163／154／163（原始 4,270／184／182／195）」；正文改成「計入報表 4,747 張」；`[Q-POST.l6]` |
| 數字 | L11 185 vs 186 | **已修** | 正文 3.4「05-31 有 95 筆、06-30 有 91 筆」；附錄 A「L11 從 185 更正為 186」 |
| 數字 | L1 措辭讓人以為 L4＝6 列 | **已修** | 附錄 F「day2 有 6 列早於批次日，是“較晚送到的舊事件”的一部分」 |
| 分類 | L3 不該放在「可能合法」 | **已修** | 附錄 C 的 C-11 管線步驟改成「⑧ 對維度（當新單寫入）」；附錄 D 的 C-11 是「使用者定案」，附原話「訂單屬於下單那天，晚到只是傳遞延遲」 |
| 查詢 | `Q-L11.identical` 用中文字串排序 | **已修** | `[Q-L11.identical]` 標題「同日兩列先照 V8 取較高等級」 |
| 查詢 | `Q-L6.inactive` 沒有排除撞號列 | **已修** | 新增 `[Q-POST.l6]`（以寫進 fact 的列為準） |
| 可讀性 1 | 內部編號和施工術語沒有定義 | **部分修** | 正文已經沒有 T4／T5／T6、工作檔、規則卡；編號 V／L／J／N 在附錄 C 開頭有定義。但附錄 D 的「出處」欄還有「T6 第二階段前的四個細節」（4 處），附錄 D 也有「ADR-03」 |
| 可讀性 2 | 篇幅長，過程細節混在主文 | **已修** | 正文縮成第 1～8 節（約 190 行），J2 對帳拆解移到附錄 A「J2 的對帳拆解」，細節都放在附錄 C～G |
| 可讀性 3 | 「待使用者決定」這類未完成標記，以及 L4 驗證錯誤 | **已修** | 全文 grep「待使用者」「審閱提示」「定稿前刪除」「〔待」都是 0；`[P-L4.after_day3]` 的輸出是 `cancelled｜day1｜25` |

另外檢查了正文與附錄所有內部錨點，以及連到 `business-assumptions.md` 的錨點，全部對得到標題（依 GitHub slug 規則比對）。

---

## 2. 獨立重算

共用的 view，全部自己寫，沒有沿用報告的 SQL：

```sql
SET TimeZone='Asia/Taipei';
-- raw：四個訂單檔 union all，加上 src（base/day1/day2/day3），所有欄位讀成字串
CREATE TABLE o AS SELECT *,
  CASE WHEN order_created_at LIKE '%Z' OR order_created_at LIKE '%+%' THEN order_created_at::timestamptz
       ELSE (order_created_at||'+08:00')::timestamptz END co_ts,          -- 無時區標記當台北
  updated_at::timestamptz upd_ts, amount::double amt, quantity::int qty, departure_date::date dep
FROM raw;
-- co_date / upd_date ＝ 換算成台北時間後的日期
CREATE TABLE o2 AS SELECT o.*,
  CASE WHEN o.currency IN ('TWD','NTD') THEN 1.0 ELSE fx.rate_to_twd::decimal(38,8) END rate,
  p.base_price_twd::double price, p.is_active
FROM o LEFT JOIN fx ON fx.currency=o.currency AND fx.rate_date::date=o.co_date
       LEFT JOIN prod p ON p.product_id=o.product_id;
-- amount_twd = round(amount::decimal(38,4) * rate, 2)（DECIMAL 的 round 是四捨五入）
-- ratio = amt*rate/(price*qty)
CREATE TABLE base1 AS SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY order_id ORDER BY upd_ts DESC) rn
  FROM o2 WHERE src='base' AND amt>0) WHERE rn=1;                         -- base 進 fact 的列
-- j3：增量同一個檔裡，同一個 order_id 有不同的 (member_id, amount, order_created_at)
-- incn：增量中 order_id 不在 base、也不在 j3 的列
-- fact：base1 ∪ incn 每個 id 取 updated_at 最新的一列
```

註：第一次重算時，換匯先用 double 再 round，結果有幾分錢的誤差（base 總額差 0.23 元），因為浮點數乘法再四捨五入會偏差。改用 DECIMAL 後，數字完全吻合。報告寫的「HALF_UP 到小數 2 位」做法是對的。

### R1 列數
```sql
select src,count(*) from raw group by 1 order by 1
```
輸出：`base 100040｜day1 4615｜day2 4700｜day3 4615`。和報告第 4 節的「收到」欄吻合。

### R2 V1 負數金額（正文 2.4：50 張、約 -1,239 萬台幣）
```sql
select count(*), count(distinct order_id), sum(amt) raw_amt, sum(amount_twd) twd,
       count(*) filter (where currency in ('USD','JPY')) foreign_n
from o2 where src='base' and amt<0
```
輸出：`(50, 50, -13531206.85, -12389441.87, 21)`。**吻合**。報告寫的是台幣換算後的金額；原幣別直接加總是 -13,531,206.85，因為有 21 筆是外幣，不能直接加總，報告的做法正確。

### R3 V2 金額多 1,000 倍（正文 1、2.1、附錄 C-1）
```sql
select count(*) filter (where ratio>100) n_v2,
 sum(amount_twd) filter (where ratio>100) v2_amt,
 sum(amount_twd) base_fact_total,
 round(100*sum(amount_twd) filter (where ratio>100)/sum(amount_twd),2) pct_share,
 sum(case when ratio>100 then round(amount_twd/1000,2) else amount_twd end) corrected_total,
 round(100*(sum(amount_twd)/sum(case when ratio>100 then round(amount_twd/1000,2) else amount_twd end)-1),2) pct_over,
 sum(amount_twd) filter (where ratio<=100 or ratio is null) excl_total,
 count(*) base_fact_rows,
 min(ratio) filter (where ratio<=100), max(ratio) filter (where ratio<=100)
from base1
```
輸出：`(40, 10102491689.70, 35969473520.09, 28.09, 25877084322.08, 39.0, 25866981830.39, 99950, 0.8378, 1.2839)`

| 報告寫的 | 重算 | 結果 |
|---|---|---|
| 40 張 | 40 | 吻合 |
| 佔 base 計入報表金額 28.09% | 28.09 | 吻合 |
| 照原樣 35,969,473,520.09 | 35,969,473,520.09 | 吻合 |
| 除以 1,000 後 25,877,084,322.08 | 25,877,084,322.08 | 吻合 |
| **高估約 39.00%**（基準＝修正後金額） | 35,969,473,520.09 ÷ 25,877,084,322.08 − 1 ＝ 39.00% | **吻合，基準正確** |
| 直接排除後 25,866,981,830.39，差 10,102,491.69 | 25,866,981,830.39；兩者差 10,102,491.69 | 吻合 |
| 正常比值約 0.84～1.28 | 0.8378～1.2839 | 吻合 |
| 計入報表 99,950 | 99,950 | 吻合 |

範例 ORD00016881（R18）：`base｜TWD｜249563000.0｜qty 2｜price 101000｜ratio 1235.46｜paid`。正文 2.1 的描述吻合，除以 1,000 後的比值 1.235 落在正常範圍內。

### R4 L10 出發前就標成已完成（正文 2.3）
```sql
select count(*) filter (where order_status='completed') completed,
 count(*) filter (where order_status='completed' and dep>upd_date) before_dep,
 min(dep-upd_date) filter (where order_status='completed'), max(dep-upd_date) filter (where order_status='completed'),
 sum(amount_twd) filter (where order_status='completed' and dep>upd_date) amt,
 count(*) filter (where order_status='completed' and dep<date '2026-07-01') dep_passed_0701
from base1
```
輸出：`(28578, 28578, 4, 119, 10324629272.48, 6147)`。**吻合**：28,578 張、相差 4～119 天、10,324,629,272.48 台幣、以 07-01 為基準出發日已過的 6,147 張。

### R5 L10 反向證據（正文 2.3：paid 9,234、created 3,053）
```sql
with b as (select * from (select *, row_number() over(partition by order_id order by upd_ts desc) rn
                          from o2 where src='base') where rn=1)
select order_status, count(*), count(*) filter (where dep<date '2026-07-01') dep_passed,
       round(100.0*count(*) filter (where dep<date '2026-07-01')/count(*),1) pct,
       count(*) filter (where dep<=upd_date) dep_le_upd
from b group by 1 order by 1
```
輸出：
```
cancelled 14241 3056 21.5 0
completed 28596 6149 21.5 0
created   14282 3053 21.4 0
paid      42881 9234 21.5 0
```
**吻合**。四種狀態「出發日已過」的比例都約 21.5%，支持正文「狀態和出發日在資料裡沒有關聯」的說法。

### R6 J2 撞號：會員、金額、下單時間三項都相同的列（正文 2.2：1,808 筆中 0 筆）
```sql
select src, count(*) n,
  count(*) filter (where exists (select 1 from o2 x where x.src='base' and x.order_id=i.order_id
     and x.member_id=i.member_id and x.amount=i.amount and x.co_ts=i.co_ts)) same3
from o2 i where src<>'base' and order_id in (select distinct order_id from o2 where src='base')
group by 1 order by 1
```
輸出：`day1 603 0｜day2 602 0｜day3 603 0`。**吻合**（合計 1,808 筆，三項都相同的是 0 筆）。

### R7 J2 若照官方說法當成更新（正文 2.2：1,776／763／118／12.73%→13.31%）
```sql
-- j2last：增量中 order_id 在 base 的列，每 id 取 updated_at 最新一列
with chg as (select f.order_id, f.member_id m0, f.order_status s0, j.member_id m1, j.order_status s1
             from fact f join j2last j using(order_id) where j.upd_ts>f.upd_ts)
select count(*) overwritten, count(*) filter (where m0<>m1) member_changed,
 count(*) filter (where s0<>'cancelled' and s1='cancelled') to_cancel,
 count(*) filter (where s0='cancelled' and s1<>'cancelled') from_cancel,
 round(100.0*((select count(*) from fact where order_status='cancelled')
   + count(*) filter (where s0<>'cancelled' and s1='cancelled')
   - count(*) filter (where s0='cancelled' and s1<>'cancelled'))/(select count(*) from fact),2) new_cancel_rate
from chg
```
- j2last **含**同一個檔內的撞號列（J3）：`(1776, 1776, 763, 118, 13.31)`，**吻合**。
- j2last **排除** J3：`(1770, 1770, 761, 118, 13.30)`。

報告的口徑是「照官方說法，全部當成更新」，J3 也包含在內，所以 1,776 符合這個情境的定義。差異來自 J3 的 6 個 id（都在 base），不算錯。

### R8 J2 若擋下的其實是真的新訂單（正文 2.2：1,800 張、1,788 個編號、468,895,127.27、未取消 238,270,742.17）
```sql
with x as (select * from o2 where src<>'base' and order_id in (select order_id from bids)),
 g as (select * from (select *, row_number() over(partition by order_id, member_id, order_created_at, amount
                                                   order by upd_ts desc) rn from x) where rn=1)
select count(*), (select count(*) from x), count(distinct order_id), sum(amount_twd),
       sum(amount_twd) filter (where order_status<>'cancelled'), count(*) filter (where ratio>100)
from g
```
輸出：`(1800, 1808, 1788, 468895127.27, 238270742.17, 0)`。**吻合**，包括「沒有金額多 1,000 倍的情況」。佔比 468,895,127.27 ÷ 39,086,896,780.27 ＝ 1.20%，÷ 28,984,405,090.57 ＝ 1.62%，**吻合**。

### R9 三天後的總數與取消率（正文 1、2.2、第 4 節）
```sql
select count(*), count(distinct order_id), sum(amount_twd) gross,
 sum(amount_twd - case when coupon_discount::double < 0 then null else coupon_discount::decimal(18,2) end) net,
 sum(amount_twd) filter (where not coalesce(ratio>100,false)) excl_v2,
 round(100.0*count(*) filter (where order_status='cancelled')/count(*),2) cancel_rate,
 count(*) filter (where coupon_discount::double<0) coupon_neg1
from fact
```
輸出：`(112010, 112010, 39086896780.27, 38895390049.43, 28984405090.57, 12.73, 299)`。**全部吻合**：112,010 張、折扣前 39,086,896,780.27、折扣後 38,895,390,049.43、排除人工確認清單後 28,984,405,090.57、取消率 12.73%、coupon -1 計入報表的 299 筆。

### R10 J3 同一個檔內的撞號（正文 3.3：6 組 12 筆）
```sql
select src, count(*) ids, sum(n) n_rows from (select j.src,j.order_id,count(*) n from j3 j join o2 using(src,order_id) group by 1,2) group by 1 order by 1
```
輸出：`day1 3 6｜day2 1 2｜day3 2 4`。**吻合**（附錄 C 的 C-14 寫「0／6／2／4 列（3／1／2 組）」）。

### R11 L4 送到順序和發生順序相反（正文 2.5：25 張、6,154,857.49）
```sql
with ev as (select *, row_number() over(partition by order_id order by upd_ts desc) r_time,
                       row_number() over(partition by order_id order by src desc, upd_ts desc) r_arrival from incn)
select count(distinct a.order_id), sum(a.amount_twd), list(distinct a.order_status||'->'||b.order_status)
from ev a join ev b on a.order_id=b.order_id and a.r_time=1 and b.r_arrival=1 and a.src<b.src
```
輸出：`(25, 6154857.49, ['cancelled->paid'])`。**吻合**。

### R12 L3 晚到的 6 月訂單（正文 3.2：60 張、約 1,132 萬；附錄 F：5 張出發後才付款）
```sql
-- 晚到新單：day2 送來、order_id 不在 base 也不在 day1、下單日早於 07-02，每 id 取最新一列
select count(*), sum(amount_twd), min(co_date), max(co_date), list(distinct order_status) from l
```
輸出：`(60, 11320587.24, 2026-06-10, 2026-06-23, ['paid'])`。用另一條查詢算「出發日早於 updated_at 且 paid」，得到 `day2 60 張｜5 列`。**吻合**。

### R13 6 月金額在各批之後的變化（正文 3.2 下方段落）
```sql
-- 每批依序重建 fact（base1 ∪ 截至該批的 incn），再取下單日在 6 月的訂單
select count(*), sum(amount_twd), sum(amount_twd) filter (where not coalesce(ratio>100,false))
from f where co_date between date '2026-06-01' and date '2026-06-30'
```
| 截至 | 張數 | 金額 | 排除人工確認清單 |
|---|---|---|---|
| base | 49,349 | 16,076,860,250.35 | 12,821,411,318.82 |
| day1 | 49,349 | 16,076,860,250.35 | 12,821,411,318.82 |
| day2 | 49,409 | 16,088,180,837.59 | 12,832,731,906.06 |
| day3 | 49,409 | 16,088,180,837.59 | 12,832,731,906.06 |

**全部吻合**。

### R14 其他抽查
| 報告寫的 | 查詢 | 輸出 | 結果 |
|---|---|---|---|
| NTD 200 張、54,561,733 台幣（3.5） | `select count(*), sum(amount_twd) from base1 where currency='NTD'` | `(200, 54561733.00)` | 吻合 |
| Z 格式字面日期差一天 1,003 筆（3.2） | `select count(*) from o2 where order_created_at like '%Z' and substr(order_created_at,1,10)::date <> co_date` | `1003` | 吻合 |
| 下單時間格式：6,002 筆不是 +08:00 | 依結尾分類 | `Z 3001｜none 3001｜+08:00 107968` | 吻合 |
| 總檔有 7 月的更新時間 2,265 筆（3.2） | `select count(*) filter (where upd_date>=date '2026-07-01'), max(upd_ts) from o2 where src='base'` | `(2265, 2026-07-03 17:20:05+08)` | 吻合 |
| ORD00002319 負數、沒有正數原單（2.4） | 查這個 id 在四個檔的所有列 | 只有 `base｜TWD｜-216020.0｜qty 3｜price 63000｜completed` 一列 | 吻合 |
| 會員：同日等級矛盾 30 位、city N/A 70 人、1900-01-01 80 人（3.4） | `group by member_id, extract_date having count(distinct member_level)>1`；`count(distinct member_id)` | `(30, 70, 80)` | 吻合 |
| 785 筆美元訂單的折扣大於金額（3.1） | `select src, count(*) filter (where currency='USD' and coupon_discount::double > amt) from o2 group by 1` | `base 785｜day1 28｜day2 34｜day3 31` | 數字吻合 base，但正文沒寫範圍，見問題 2 |

此外確認了管線程式從 9f9d415 之後沒有改動：`git diff --stat 9f9d415 HEAD -- LionDEExam/submission/part_a/` 只有 README.md、data-quality-report.md、model.md、overview.html、profiling 腳本有變動。所以附錄 B 的 `P-` 段（在 9f9d415 跑的）仍然代表現行的管線。

---

## 3. 結論是否超出證據

整體來看，正文的量化宣稱都有附錄查詢支撐，推測性的說法也多半有「可能」「資料看不出來」這類限定。以下依嚴重度排列，全部是**低**嚴重度。

### 問題 1（低）2.2 的標題用斷言，正文內容卻有保留
- 位置：正文標題「2.2 每天約 600 筆“舊訂單的更新”，其實是另一張訂單撞了號」；同節「照官方說法處理會讓上千張訂單算錯會員」。
- 情境：證據（1,808 筆中，會員、金額、下單時間三項都相同的是 0 筆）**強烈支持**「不是單純的狀態更新」，但同一節「這代表什麼」也承認「資料分辨不出上游是不是允許整張訂單被改寫」。如果上游真的允許整張改寫，「算錯會員」就不成立。標題與影響段落用斷言，面談時可能被追問「怎麼確定是另一張單」。
- 建議：標題或影響段落加一個限定，例如「判定為撞號」，或寫成「若是撞號，照官方說法處理會讓…」，讓斷言的強度和「這代表什麼」一致。

### 問題 2（低）3.1 把「折扣沒有幣別」列為問題，但官方欄位說明已經寫了 TWD；785 筆也沒寫範圍
- 位置：正文 3.1 表格「折扣欄位本身沒有幣別｜全部訂單｜一律當台幣：官方欄位說明寫折扣是台幣…若當成訂單本身的幣別，785 筆美元訂單的折扣會比金額還大」。
- 情境：(a) `candidate_package/README.md` 寫的是「`coupon_discount`（TWD）」，所以「本身沒有幣別」這個描述不準確。它比較像「欄位說明之外的資料佐證」，不是品質問題，而附錄 C 卻把它算進「27 個實際發生的問題」（C-8）。閱卷者對照 README 後，可能認為這是灌水，或是誤讀。(b) 785 只算 base；四個檔合計是 878（day1 28、day2 34、day3 31），正文沒寫範圍。
- 建議：問題描述改成「折扣幣別只寫在欄位說明，資料列本身不帶幣別」，或把這一項移到「已檢查、沒有問題」；785 補上「5～6 月總檔」。

### 問題 3（低，屬於資訊）C-1 的判斷理由在 025fda4 改寫後，語意和附錄 D 的原話不完全對應
- 位置：正文 2.1「判斷理由：這 40 張已經被前面的檢查標記出來，所以應該人工審查之後再進入下游」；附錄 D 的 C-1 原話「因為已經有前面指標進入隔離我認為就應該人工審查後在進入下流」。
- 情境：451d585 版的轉述是「前面已經有其他問題的資料先擋下來等人處理，這 40 張也應該…」，意思是一致性論證。現版的意思是「這 40 張已被檢查標記」。兩種讀法都說得通，但面談時被問到理由，兩個版本講的不是同一件事。依專案規則，定案理由要由使用者確認。
- 建議：使用者確認現版轉述是自己要表達的意思即可。若是，附錄 D 不用改。

### 其他（未達中等信心，不列為問題）
- 附錄 D「出處」欄的「T6 第二階段前的四個細節」「ADR-03」是 process-log 的事件標題，是為了可追溯而保留，不影響正文理解。要改的話，可以在附錄 D 開頭加一句「出處欄是 process-log 的事件標題，原樣引用」。

---

## 4. 檢查範圍

- 正文第 1～8 節逐句讀過；附錄 A、C、D、E 讀過；附錄 B 抽讀 `[Q-J2.impact]`、`[Q-POST.l4_final]`、`[P-L4.after_day3]`、`[P-ALL.amount_excluding_review]`；附錄 F 用 grep 抽查第一輪 finding 相關的段落。
- 沒有重算的：L8（398 人）、L9（434／376）、L11（95／91）、V7（40 組）、N1（15 組）、L6（4,747）、L12。第一輪已經獨立重算過這些數字，而且本輪沒有發現相關的程式或資料變動。
