# 訂單的身分：撞號、重複、主鍵

回到：[README.md](README.md)｜問題總表：[issues.md](issues.md)

**結論**：同一個 order_id 出現多列有三種情況，性質不同。
- **base 內的 40 組重複（V7）是同一筆重複送出**：所有欄位相同，只差 `updated_at` 幾秒，確定是錯誤值。
- **乾淨的狀態更新**（增量同檔 45 組、day1→day2 的 25 組）：會員、金額、下單時間都不變，只改狀態，符合官方說的「狀態更新事件」。
- **增量檔與 base 撞號（每天約 600 列，J2）與增量同檔撞號（6 組，J3）**：會員、金額、下單時間全都不同，各欄和 base 的吻合率等於隨機巧合。是不是 noise 取決於「同一張單哪些欄位不可變」（J4），**待使用者判斷**；它也決定 order_id 能不能單獨當主鍵（J1）。

<a id="v7"></a>
## V7｜orders_base 同 order_id 兩列（40 組，多 40 列）〔確定的錯誤值〕

- 違反：`PRIMARY KEY (order_id)`（base 是全量，一張單應一列）。
- 影響：40 個 order_id 各 2 列（[S6.orders_pk] base extra_rows 40）。
- 為什麼確定是重複送出：40 組的 member、amount、下單時刻、狀態、其他欄位**全部相同**（[S6.orders_dup_groups] base：`same member/amount/created instant` 40 組、`status_changed 0`、`other_cols_changed 0`），只差 `updated_at` 2～29 秒（[S6.base_dup_gap]）；其中 8 組的 order_created_at 字串不同但是同一時刻（`created_same_instant_diff_format 8`，即 [V5](order-time.md#v5) 的格式差異）。
- 偵測查詢（[S6.orders_dup_groups] 節錄）：
  ```sql
  WITH g AS (
    SELECT src, order_id, count(*) AS c, count(DISTINCT updated_at) AS d_upd,
      count(DISTINCT order_created_at) AS d_co_raw, count(DISTINCT co_ts) AS d_co_instant,
      count(DISTINCT member_id) AS d_mem, count(DISTINCT amount) AS d_amt, count(DISTINCT order_status) AS d_status,
      count(DISTINCT concat_ws('|', product_id, channel, quantity, currency, coupon_discount, departure_date)) AS d_other
    FROM orders_t GROUP BY src, order_id HAVING count(*) > 1)
  SELECT src, c AS rows_per_id,
    CASE WHEN d_mem = 1 AND d_amt = 1 AND d_co_instant = 1 THEN 'same member/amount/created instant'
         ELSE 'member/amount/created differ' END AS kind,
    count(*) AS n_groups, ... FROM g GROUP BY 1, 2, 3
  ```
- 範例（[S6.base_dup_examples]）：`ORD00000984`（updated_at `07:02:52` / `07:03:06`）、`ORD00012637`（+08:00 / Z）、`ORD00013776`（+08:00 / slash）。

<a id="j1"></a>
## J1｜orders 的主鍵：`order_id` 還是 `order_id + 版本`〔待使用者判斷〕

- 支持 `order_id`（一張單一列，增量為狀態更新）：官方 README「增量檔中同一 order_id 可能出現多次（狀態更新事件），以 updated_at 區分新舊」；乾淨的同 id 多列確實只改狀態——增量檔同檔重複 51 組中 45 組 member/amount/created/product 四欄一致（[S8.inc_dup_consistent]），跨檔 day1→day2 的 25 個 id 三欄全同（[S8.inc_vs_inc]），且這些「同會員」的轉移**依 `updated_at` 排序**時沒有倒退（[S8.status_transitions] `same_member true` 只有 paid→cancelled 25 與同狀態重送；這 25 筆就是 day1→day2 的 25 個 id，依檔案順序會變成相反方向，見 [L4](order-time.md#l4)）。
- 支持需要版本（或 order_id 不可靠）：base 自己就有 40 組重複（V7）；增量檔有約 600 列/天的 id 與 base 相同但內容完全不同（J2）。若這些是合法的「同 id 不同單」，order_id 單獨就不是唯一鍵。

<a id="j2"></a>
## J2｜增量檔與 base 同 order_id 的列（每天約 600 列）：noise 還是合法更新〔待使用者判斷〕

- 數量：day1 603 列 / 597 id、day2 602 / 599、day3 603 / 598（[S8.inc_vs_base_cols]；base 先每 id 取一列，避免 V7 的重複讓列數翻倍）。
- 支持「是另一張單（撞號或上游錯配），不是更新」：
  - 與 base 相同的列數：member 0、下單時刻 0、amount 0（三檔皆是）；product 3 / 1 / 1（≈ 1/300 的隨機巧合）；channel 157 / 160 / 131（≈ 603 × 0.25）；currency 312 / 309 / 299（≈ 603 × 0.505，[S8.inc_vs_base_expected] 算出隨機相同的期望值）。**各欄與 base 的吻合率等於隨機抽樣的期望**，等於兩列之間沒有任何關聯。
  - **終態會互換，不像同一張單的狀態演進**：這些列的狀態只有 cancelled 或 completed（[S8.inc_vs_base_status]），而且與 base 比會出現終態互換（例如 day1 completed→cancelled 68、cancelled→completed 40）。對照組：依 updated_at 排相鄰兩列時，會員相同的轉移沒有倒退，會員不同的才有終態後再變（[S8.status_transitions]：`same_member false` 含 cancelled→completed 122、completed→cancelled 238、completed→created 1；`same_member true` 只有 paid→cancelled 25 與同狀態重送）。
  - 範例（[S8.inc_vs_base_examples]）：`ORD00005192` base 是 `M007765 P00240 USD 10230.87 paid 下單 05-06`，day1 是 `M005173 P00040 USD 6927.0 completed 下單 05-04`。
- 支持「是合法更新」：官方語意允許同 id 多次出現；這些列 `updated_at` 幾乎都比 base 新（day1 593/603、day2 600/602、day3 603/603，[S8.inc_vs_base_cols] `inc_newer_than_base`）；下單日落在 base 期間（05-01～06-30，[S5.inc_created_vs_batch] `older_and_id_in_base`），像是舊訂單的後續事件。
- 跨增量檔的撞號也已含在上述數字裡：[S8.inc_vs_inc] 中 `id_in_base true` 的 day1→day3 5 組、day2→day3 1 組，`same_member_amount_created 0`（會員、金額、下單時間都不同）；這 6 個 id 都在 base，所以兩端的增量列都已計入各檔與 base 重疊的 603 / 602 / 603 列。相對地，`id_in_base false` 的 day1→day2 25 組三欄全同，是同一張單，但到達順序與發生順序相反，見 [L4](order-time.md#l4)。
- 要使用者判斷：同一張單的 member_id、order_created_at、amount 能不能變（J4）；若不能，這些列就是 noise。
- 與既有筆記的數字：E11（[`part_b/evidence.md`](../../../part_b/evidence.md) 的證據編號，各增量檔與 base 重疊的 order_id）記 day2 與 base 重疊 602 列 / 599 id，本次 602 / 599（[S8.inc_vs_base_cols]），一致。注意：若不先把 base 每 id 取一列，直接 join 會因 V7 的重複得到 603 列（第一次執行就是如此，已修正查詢）。
- **值得質疑 Q5（「隨機吻合」論證）**：我用 base 的 channel／currency 分布算期望值（0.25、0.505），實際吻合率（約 0.22～0.27、0.50～0.52）接近期望值。這證明兩列「統計上無關」，但不能排除「上游真的允許整張單被改寫」這種極端業務規則。

<a id="j3"></a>
## J3｜增量檔「同檔同 order_id」但會員、金額、下單時間都不同（6 組；原列為 V11）〔待使用者判斷〕

原本放在「確定的 noise」，但它是不是 noise 取決於尚未定案的 J4，所以移到待判斷。它與 J2 是同一種現象（id 在 base、內容互不相關），差別只在兩列落在同一個增量檔。拆開判斷還是與 J2 合併判斷，由使用者決定。
- 違反：`PRIMARY KEY (order_id)` 加上「同一張單的 member_id、order_created_at 不可變」（J4）。
- 影響：day1 3 組、day2 1 組、day3 2 組，共 12 列；6 個 id 全部也存在於 base（[S6.orders_dup_groups]、[S6.inc_dup_collision_examples] `id_in_base true`）。
- 這 6 組與 J2 的「增量列 vs base 列」是同一種現象（同 id 但內容像另一張單），只是兩列剛好落在同一個增量檔。若 J4 成立（這些欄位不可變），它就是 noise。
- 偵測查詢（[S6.inc_dup_collision_examples]）：
  ```sql
  WITH g AS (SELECT src, order_id FROM orders_t WHERE src <> 'base' GROUP BY src, order_id
             HAVING count(*) > 1 AND (count(DISTINCT member_id) > 1 OR count(DISTINCT amount) > 1 OR count(DISTINCT co_ts) > 1))
  SELECT o.src, o.order_id, o.member_id, o.amount, o.order_status, o.order_created_at, o.updated_at,
    o.order_id IN (SELECT order_id FROM orders_base) AS id_in_base
  FROM orders_t o JOIN g ON o.src = g.src AND o.order_id = g.order_id ORDER BY o.src, o.order_id, o.updated_at
  ```
- 範例：`ORD00036457`（day1：M002150 200659.0 completed / M000272 18042.46 cancelled）、`ORD00043894`（day2）、`ORD00083916`（day3）。

<a id="j4"></a>
## J4｜哪些欄位在原系統不可修改〔待使用者判斷〕

- 資料支持「不可變」的欄位：
  - orders：member_id、order_created_at、product_id、amount——在所有「乾淨」的更新裡都沒變（同檔 45 組、跨檔 25 組、base 重複 40 組）。只有 J2、J3 的撞號列會改。
  - members：member_name（0 人變過）、register_date（0 人變過）、birth_date（變過的 19 人都是與 1900-01-01 互換：14 人 1900 → 真實、5 人 真實 → 1900；沒有真實日期改成另一個真實日期）（[S9.attr_change]、[S9.birth_change_direction]；細節見 [members.md](members.md#v10)）。
- 推不出來的：currency、quantity、coupon_discount、departure_date 在乾淨更新裡也都沒變（[S6.orders_dup_groups] `other_cols_changed` 在 same 組皆 0），但旅遊業務上「改出發日」「加人數」是可能的，資料樣本太少（45 + 25 組）不足以排除。
