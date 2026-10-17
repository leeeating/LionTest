# 訂單的身分：撞號、重複、主鍵

回到：[README.md](README.md)｜問題總表：[issues.md](issues.md)

**結論**：同一個 order_id 出現多列有三種情況，性質不同。
- **base 內的 40 組重複（V7）是同一筆重複送出**：所有欄位相同（下單時間換算成同一時刻後相同），只差 `updated_at` 幾秒，確定是錯誤值。
- **增量檔裡內容一致的同 id 多列**分兩種：同檔 45 組除 `updated_at` 外每一欄都相同（連狀態也相同，是同狀態重送，不是狀態更新）；day1→day2 的 25 組只有狀態與 `updated_at` 不同（day1 cancelled、day2 paid），符合官方說的「狀態更新事件」。資料裡同一張單、狀態有變的實例只有這 25 組。
- **增量檔與 base 撞號（每天約 600 列，J2）與增量同檔撞號（6 組，J3）**：會員、金額、下單時間全都不同，各欄和 base 的吻合率等於隨機巧合。使用者判斷當 noise（題目刻意埋進資料的錯誤值）處理，見 [ADR-03](../../../decisions/ADR-03-order-id-collision-as-noise.md)；前提是同一張單哪些欄位不可變（J4），它也決定 order_id 能不能單獨當主鍵（J1）。

<a id="v7"></a>
## V7｜orders_base 同 order_id 兩列（40 組，多 40 列）〔確定的錯誤值〕

- 違反：`PRIMARY KEY (order_id)`（base 是全量，一張單應一列）。
- 影響：40 個 order_id 各 2 列（base 多出 40 列，`extra_rows 40`）。
  <sub>證據：剖析輸出搜尋 `S6.orders_pk`</sub>
- 為什麼確定是重複送出：40 組的會員、金額、下單時刻、狀態、其他欄位**全部相同**（輸出：`same member/amount/created instant` 40 組、`status_changed 0`、`other_cols_changed 0`），只差 `updated_at` 2～29 秒。其中 8 組的下單時間字串不同，但換算後是同一時刻（`created_same_instant_diff_format 8`），就是 [V5](order-time.md#v5) 的格式差異。
  <sub>證據：剖析輸出搜尋 `S6.orders_dup_groups`、`S6.base_dup_gap`</sub>
- 〔使用者判斷〕成因與上游改善：使用者依經驗判斷是網路波動造成的重複寫入（原話：「v7根據我的經驗是網路波動導致的重複寫入 可以重寫入端或是schena的unique index改善」）。上游改善有兩條路：寫入端加冪等鍵（重送時同一個 request id 不再寫入），或在 schema 加 unique index。unique index 要建在哪個欄位取決於 [J1](#j1)：上游若是「一張單一列」的訂單表，`order_id` 唯一即可；若是狀態事件表，`order_id` 唯一會擋掉合法的事件，而 `(order_id, updated_at)` 唯一擋不住 V7（每列 `updated_at` 都不同）。本次管線仍須處理已重複寫入的這批資料，這與上游改善是兩件事。
- 偵測查詢（節錄）：
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
  <sub>證據：剖析輸出搜尋 `S6.orders_dup_groups`</sub>
- 範例：`ORD00000984`（updated_at `07:02:52` / `07:03:06`）、`ORD00012637`（+08:00 / Z）、`ORD00013776`（+08:00 / slash）。
  <sub>證據：剖析輸出搜尋 `S6.base_dup_examples`</sub>

<a id="j1"></a>
## J1｜orders 的主鍵：`order_id` 還是 `order_id + 版本`〔待使用者判斷〕

- 支持 `order_id`（一張單一列，增量為狀態更新）：
  - 官方 README 說「增量檔中同一 order_id 可能出現多次（狀態更新事件），以 updated_at 區分新舊」。
  - 內容一致的同 id 多列：增量檔裡同一張訂單在同一檔出現多次的有 51 組，其中 45 組的會員、金額、下單時間、產品都沒變；逐欄再查，這 45 組的狀態與其他欄位也都相同，只有 `updated_at` 不同（同狀態重送）。跨檔 day1→day2 的 25 個 id 只有狀態與 `updated_at` 不同。所以能直接支持「增量是狀態更新」的實例只有這 25 組。
  - 會員相同的列依 `updated_at` 排序時，狀態沒有倒退：只有 paid→cancelled 25 與同狀態重送（`same_member true`）。這 25 筆就是 day1→day2 的 25 個 id，依檔案順序會變成相反方向，見 [L4](order-time.md#l4)。
  <sub>證據：剖析輸出搜尋 `S8.inc_dup_consistent`、`S8.inc_vs_inc`、`S8.dup_group_col_diff`、`S8.dup_group_col_diff_clean`、`S8.status_transitions`</sub>
- 支持需要版本（或 order_id 不可靠）：base 自己就有 40 組重複（V7）；增量檔有約 600 列/天的 id 與 base 相同但內容完全不同（J2）。若這些是合法的「同 id 不同單」，order_id 單獨就不是唯一鍵。

<a id="j2"></a>
## J2｜增量檔與 base 同 order_id 的列（每天約 600 列）：noise 還是合法更新〔使用者判斷：noise〕

- 數量：day1 603 列 / 597 id、day2 602 / 599、day3 603 / 598。計算時 base 先每個 id 取一列，避免 V7 的重複讓列數翻倍。
  <sub>證據：剖析輸出搜尋 `S8.inc_vs_base_cols`</sub>
- 支持「是另一張單（撞號或上游錯配），不是更新」：
  - **各欄和 base 相同的機率，等於隨便抽兩張單碰巧相同的機率**，等於兩列之間沒有任何關聯。和 base 相同的列數：會員 0、下單時刻 0、金額 0（三檔皆是）；產品 3 / 1 / 1（≈ 1/300 的隨機巧合）；通路 157 / 160 / 131（≈ 603 × 0.25）；幣別 312 / 309 / 299（≈ 603 × 0.505）。≈ 後面的數字是隨機相同的期望值。
    <sub>證據：剖析輸出搜尋 `S8.inc_vs_base_cols`、`S8.inc_vs_base_expected`</sub>
  - **終態會互換，不像同一張單的狀態演進**：這些列的狀態只有 cancelled 或 completed，而且與 base 比會出現終態互換（例如 day1 completed→cancelled 68、cancelled→completed 40）。
  - 對照組（依 updated_at 排相鄰兩列）：
    - 會員不同的轉移有終態後再變：cancelled→completed 122、completed→cancelled 238、completed→created 1（`same_member false`）。
    - 會員相同的轉移沒有倒退：只有 paid→cancelled 25 與同狀態重送（`same_member true`）。
    <sub>證據：剖析輸出搜尋 `S8.inc_vs_base_status`、`S8.status_transitions`</sub>
  - 範例：`ORD00005192` base 是 `M007765 P00240 USD 10230.87 paid 下單 05-06`，day1 是 `M005173 P00040 USD 6927.0 completed 下單 05-04`。
    <sub>證據：剖析輸出搜尋 `S8.inc_vs_base_examples`</sub>
- 支持「是合法更新」：官方語意允許同 id 多次出現；這些列的 `updated_at` 幾乎都比 base 新（day1 593/603、day2 600/602、day3 603/603，`inc_newer_than_base`）；下單日落在 base 期間（05-01～06-30，`older_and_id_in_base`），像是舊訂單的後續事件。
  <sub>證據：剖析輸出搜尋 `S8.inc_vs_base_cols`、`S5.inc_created_vs_batch`</sub>
- 跨增量檔的撞號也已含在上述數字裡：day1→day3 5 組、day2→day3 1 組的 id 都在 base（`id_in_base true`），會員、金額、下單時間都不同（`same_member_amount_created 0`），所以兩端的增量列都已計入各檔與 base 重疊的 603 / 602 / 603 列。相對地，不在 base 的 day1→day2 25 組（`id_in_base false`）三欄全同，是同一張單，但到達順序與發生順序相反，見 [L4](order-time.md#l4)。
  <sub>證據：剖析輸出搜尋 `S8.inc_vs_inc`</sub>
- 要使用者判斷：同一張單的 member_id、order_created_at、amount 能不能變（J4）；若不能，這些列就是 noise。
- 與既有筆記的數字：E11（[`part_b/evidence.md`](../../../part_b/evidence.md) 的證據編號，各增量檔與 base 重疊的 order_id）記 day2 與 base 重疊 602 列 / 599 id，本次 602 / 599，一致。注意：若不先把 base 每 id 取一列，直接 join 會因 V7 的重複得到 603 列（第一次執行就是如此，已修正查詢）。
  <sub>證據：剖析輸出搜尋 `S8.inc_vs_base_cols`</sub>
- **值得質疑 Q5（「隨機吻合」論證）**：我用 base 的通路／幣別分布算期望值（0.25、0.505），實際吻合率（約 0.22～0.27、0.50～0.52）接近期望值。這證明兩列「統計上無關」，但不能排除「上游真的允許整張單被改寫」這種極端業務規則。

- **精確的隨機期望對照**（2026-10-17 補）：期望值 = 兩邊各自的值分布不變、隨機配對時碰巧相同的列數。
  | 欄位 | day1 實際／期望 | day2 實際／期望 | day3 實際／期望 |
  |---|---|---|---|
  | 會員 | 0／0.1 | 0／0.1 | 0／0.1 |
  | 金額 | 0／0.0 | 0／0.0 | 0／0.0 |
  | 下單時間 | 0／0.0 | 0／0.0 | 0／0.0 |
  | 幣別 | 312／308.2 | 309／310.2 | 299／291.3 |
  | 通路 | 157／150.9 | 160／151.0 | 131／150.9 |
  | 狀態 | 118／115.7 | 129／124.9 | 108／119.0 |

  幣別、通路、狀態都落在隨機期望附近（day3 的通路、狀態略低於期望），沒有任何一欄高於隨機；若是同一張單，這些欄位應該幾乎全部相同。
  <sub>證據：`python3 -I LionDEExam/submission/part_a/profiling/collision_expected_match.py LionDEExam/candidate_package/dataset`（repo 根目錄執行）</sub>
- **〔使用者判斷〕當 noise（撞號）處理**：使用者決定「把撞號當 noise 處理」，理由原話：「先假設訂單狀態不能被改寫」；使用者確認原意是**訂單內容（會員、下單時間、金額）不能被改寫，狀態可以變**。所以這些欄位全不同的列是另一張單用了同一個 order_id。見 ADR-03。官方 README 說增量檔含「舊訂單的狀態更新事件」，這個判斷與官方說法不同，理由見 ADR-03。

<a id="j3"></a>
## J3｜增量檔「同檔同 order_id」但會員、金額、下單時間都不同（6 組；原列為 V11）〔待使用者判斷〕

原本放在「確定的 noise」，但它是不是 noise 取決於尚未定案的 J4，所以移到待判斷。它與 J2 是同一種現象（id 在 base、內容互不相關），差別只在兩列落在同一個增量檔。拆開判斷還是與 J2 合併判斷，由使用者決定。
- 違反：`PRIMARY KEY (order_id)` 加上「同一張單的 member_id、order_created_at 不可變」（J4）。
- 影響：day1 3 組、day2 1 組、day3 2 組，共 12 列；6 個 id 全部也存在於 base（`id_in_base true`）。
  <sub>證據：剖析輸出搜尋 `S6.orders_dup_groups`、`S6.inc_dup_collision_examples`</sub>
- 這 6 組與 J2 的「增量列 vs base 列」是同一種現象（同 id 但內容像另一張單），只是兩列剛好落在同一個增量檔。若 J4 成立（這些欄位不可變），它就是 noise。
- 偵測查詢：
  ```sql
  WITH g AS (SELECT src, order_id FROM orders_t WHERE src <> 'base' GROUP BY src, order_id
             HAVING count(*) > 1 AND (count(DISTINCT member_id) > 1 OR count(DISTINCT amount) > 1 OR count(DISTINCT co_ts) > 1))
  SELECT o.src, o.order_id, o.member_id, o.amount, o.order_status, o.order_created_at, o.updated_at,
    o.order_id IN (SELECT order_id FROM orders_base) AS id_in_base
  FROM orders_t o JOIN g ON o.src = g.src AND o.order_id = g.order_id ORDER BY o.src, o.order_id, o.updated_at
  ```
- 範例：`ORD00036457`（day1：M002150 200659.0 completed / M000272 18042.46 cancelled）、`ORD00043894`（day2）、`ORD00083916`（day3）。
  <sub>證據：剖析輸出搜尋 `S6.inc_dup_collision_examples`</sub>

<a id="j4"></a>
## J4｜哪些欄位在原系統不可修改〔使用者判斷：會員、下單時間、金額不可改，見 ADR-03〕

- 資料支持「不可變」的欄位：
  - orders：會員、下單時間、產品、金額（member_id、order_created_at、product_id、amount），在三類內容一致的組裡都沒變：增量同檔 45 組、day1→day2 25 組、base 重複 40 組。只有 J2、J3 的撞號列會改（增量同檔 51 組中的另外 6 組，這四欄都不同）。
    <sub>證據：剖析輸出搜尋 `S8.dup_group_col_diff`、`S8.dup_group_col_diff_clean`</sub>
  - members：姓名（member_name，0 人變過）、註冊日（register_date，0 人變過）、生日（birth_date，變過的 19 人都是與 1900-01-01 互換：14 人 1900 → 真實、5 人 真實 → 1900；沒有真實日期改成另一個真實日期）。細節見 [members.md](members.md#v10)。
  <sub>證據：剖析輸出搜尋 `S9.attr_change`、`S9.birth_change_direction`</sub>
- 推不出來的：通路、幣別、數量、折扣、出發日（channel、currency、quantity、coupon_discount、departure_date）在上述三類組裡也都沒變（有差異的組數皆 0；base 40 組另見 `other_cols_changed 0`）。但 45 組與 40 組都是同狀態重送，真正有狀態變化的只有 day1→day2 的 25 組；旅遊業務上「改出發日」「加人數」是可能的，樣本太少不足以排除。
  <sub>證據：剖析輸出搜尋 `S8.dup_group_col_diff`、`S8.dup_group_col_diff_clean`、`S6.orders_dup_groups`</sub>
- 逐欄差異的輸出摘要（有差異的組數／總組數；`updated_at` 在每類都是全部組有差異）：

  | 類別 | 會員 | 產品 | 通路 | 狀態 | 數量 | 幣別 | 金額 | 折扣 | 下單時間 | 出發日 | updated_at |
  |---|---|---|---|---|---|---|---|---|---|---|---|
  | (a) 增量同檔同 id，51 組 | 6 | 6 | 5 | 3 | 6 | 4 | 6 | 5 | 6 | 6 | 51 |
  | (a') 其中四欄一致的 45 組 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 45 |
  | (b) day1→day2、不在 base，25 組 | 0 | 0 | 0 | 25 | 0 | 0 | 0 | 0 | 0 | 0 | 25 |
  | (c) base 同 id，40 組 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 40 |

  <sub>證據：剖析輸出搜尋 `S8.dup_group_col_diff`、`S8.dup_group_col_diff_clean`</sub>
