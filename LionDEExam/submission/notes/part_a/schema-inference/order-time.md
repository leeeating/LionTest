# 訂單的時間：時區、格式、晚到與亂序

回到：[README.md](README.md)｜問題總表：[issues.md](issues.md)

**結論**：
- **下單時間的格式問題（V5）可還原**：base 有 3,001 筆 `Z`（是 UTC）、3,001 筆無標記（是台北時間），其餘都是 `+08:00`；照字面解析可還原同一時刻；取前 10 碼會錯日。
- **檔名日期不等於資料時間**：增量檔約 70% 的 `updated_at` 晚於批次日（L1）；base 自稱 05-01～06-30，卻有 2,265 列 `updated_at` 在 07-01～07-03（L2）；day2 夾著 60 張 06 月下單的晚到新單（L3）。
- **到達順序與發生順序會相反**：day1→day2 的 25 個 id，照檔案順序與照 `updated_at` 會得到相反的最終狀態（L4）。以哪個為準是 J6，**待使用者判斷**。
- completed 的訂單出發日都還沒到（L10），completed 的語意待使用者判斷（J8）。

<a id="v5"></a>
## V5｜orders_base.order_created_at 格式不一致（6,002 筆）〔確定的錯誤值〕

- 違反：欄位應為單一格式的 TIMESTAMPTZ。
- 影響：base 有 3,001 筆是結尾為 `Z` 的格式（`iso_Z`）、3,001 筆是沒有時區標記的 `YYYY/MM/DD HH:MM:SS`（`slash_no_tz`）；其餘 94,038 筆與增量檔全部是 `+08:00`。
  <sub>證據：剖析輸出搜尋 `S2.co_fmt`</sub>
- 時區語意的驗證，兩種格式分開論證：
  - **Z 是 UTC**：
    - 主證據：base 的重複列（[V7](order-identity.md#v7)）。8 組重複中，兩列的下單時間字串一列是 `+08:00`、另一列是 Z（5 組）或無標記（3 組）；照字面解析（Z = UTC）後 8 組全部是同一時刻、相差 0 小時（`same_instant_as_parsed true`、`diff_hours 0.0`），例如 `ORD00012637` 的 `2026-06-14T19:17:51+08:00` 與 `2026-06-14T11:17:51Z`。
      <sub>證據：剖析輸出搜尋 `S5.z_evidence`</sub>
    - 替代假設不成立：若 Z 其實是誤標的台北時間，這 5 組會相差 8 小時，但實際相差 0 小時。
    - 輔證：Z 格式的最小值 `2026-04-30T17:04:32Z` 換成台北是 `2026-05-01 01:04:32`；Z 格式有 13 筆字面日期早於 05-01，照 UTC 解讀後 0 筆早於 05-01，與官方期間「05-01 起」相符（`raw_date_before_0501 13`、`before_0501_as_parsed 0`）。
      <sub>證據：剖析輸出搜尋 `S5.z_min`</sub>
  - **無標記的是台北時間**：上述 3 組重複列的字串與 `+08:00` 那列只差格式（如 `ORD00013776` 的 `2026/05/24 19:26:43` 與 `2026-05-24T19:26:43+08:00`）。另以「更新時間（全為 +08:00）不應早於下單時間」檢查：照台北時間解析時違反 0 筆；若無標記時間其實是 UTC（等於台北時間再加 8 小時），會有 384 筆違反。所以無標記不是 UTC。
    <sub>證據：剖析輸出搜尋 `S5.z_evidence`、`S5.tz_check`</sub>
  - 同一個檢查中 Z 那一列（加 8 小時後 374 筆違反）**不能**當 Z 的證據：它檢驗的是「Z 的值比照字面再晚 8 小時」，但 Z 的替代假設是「Z 其實是台北時間誤標」，那應該是比照字面早 8 小時，這種方向的移動只會讓下單時間更早，`updated_at >= 下單時間` 永遠驗不出來。
    <sub>證據：剖析輸出搜尋 `S5.tz_check`</sub>
  - 結論：值本身可還原，問題只在格式。
- 偵測查詢：
  ```sql
  SELECT src, co_fmt, count(*) AS n, min(order_created_at) AS example_min, max(order_created_at) AS example_max
  FROM orders_t GROUP BY src, co_fmt ORDER BY src, co_fmt
  ```
  `co_fmt` 在 view `orders_t` 以 regex 分類（`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$`、`...Z$`、`^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$`）。
  <sub>證據：剖析輸出搜尋 `S2.co_fmt`</sub>
- 範例：`2026-04-30T17:04:32Z`（= 台北 05-01 01:04:32）、`2026/05/01 01:02:46`、`2026/05/24 19:26:43`。
  <sub>證據：剖析輸出搜尋 `S2.co_fmt`、`S6.base_dup_examples`</sub>
- 注意：若用 `to_date(order_created_at)` 直接取前 10 碼，Z 格式會讓台北 08:00 前下單的訂單落到前一天，`2026-04-30T17:04:32Z` 就是例子（base 官方期間從 05-01 起）。
- **值得質疑 Q3（時區證據樣本小）**：「Z 是 UTC」主要靠 5 組重複列，加上 13 筆 Z 字面日期早於 05-01 的輔證；「無標記是台北時間」靠 3 組重複列與 `updated_at >= order_created_at` 這條假設。若這條假設不成立，無標記格式的證據就只剩 3 組重複列。
  <sub>證據：剖析輸出搜尋 `S5.z_evidence`</sub>

<a id="l1"></a>
## L1｜增量檔 `updated_at` 的日期晚於批次日〔可能合法〕

- 影響：day1 3,290、day2 3,257、day3 3,263；最晚到批次日 +4 天（day1 有 5 列）。
- 為什麼可能合法：檔名的「day」可能是下單批次而非更新批次；比例約 70%，是系統性的，不像少數髒資料。

<sub>證據：剖析輸出搜尋 `S5.inc_upd_after_batch_total`、`S5.inc_upd_vs_batch`</sub>

<a id="l2"></a>
## L2｜base 有 `updated_at` 落在 07-01～07-03 的列〔可能合法〕〔新發現〕

- 影響：base（官方 05-01～06-30）有 2,265 列（07-01 1,308 + 07-02 759 + 07-03 198；狀態分布 293 + 667 + 332 + 973 也合計 2,265）；base `updated_at` 最大 2026-07-03 17:20:05。
  <sub>證據：剖析輸出搜尋 `S5.base_upd_after_period`、`S5.ranges`</sub>
- 為什麼可能合法：「05-01～06-30」可能指下單期間，base 實際萃取時點在 07-03 之後。
- 連帶：增量列的 `updated_at` 比 base 同 id 列還舊的 12 列（day1 10、day2 2），對應的 base 列全部都是 07-01 之後更新的。
  <sub>證據：剖析輸出搜尋 `S8.inc_vs_base_upd_not_newer_cnt`</sub>

<a id="l3"></a>
## L3｜day2 有晚到的新訂單〔可能合法〕〔新發現〕

- 影響：day2 有 60 張下單日在 06-10～06-23、但 base 沒有的新 order_id，60 列，id `ORD00112001`～`ORD00112060`，編號在 day3 新單（ORD00108001～112000）之後。
- 為什麼可能合法：晚到的訂單（上游補送）。order_id 編號與下單時間不單調，代表 order_id 不能拿來推時間。

<sub>證據：剖析輸出搜尋 `S5.inc_created_vs_batch`（`older_and_id_never_seen`）、`S5.id_vs_time`、`S5.late_new_examples`</sub>

<a id="l4"></a>
## L4｜day2 送來的是較舊的事件（25 個 id）〔可能合法〕〔新發現〕

- 現象：day2 有 25 張 07-01 新單再出現，但 day2 送來的是**較舊**的事件：25 組全是 day1 `cancelled`、day2 `paid`，且 day2 的 `updated_at` 都比 day1 早（例 `ORD00100020` day1 cancelled 07-04T18:08:26、day2 paid 07-03T12:08:26）；其中 6 列 day2 的 `updated_at` 還早於 day2 批次日。
- 影響：25 個 id 跨 day1/day2，會員、金額、下單時間三欄全一致；沒有任何一組是後到的檔比較新（`later_file_newer 0`；輸出 `cancelled / paid / later_file_older / 25`）。
- 為什麼可能合法：同一張單、內容一致，是同一訂單的狀態事件；只是到達順序與發生順序相反（晚到的舊事件）。照 `updated_at` 排序是 paid → cancelled，照檔案順序則是 cancelled → paid。以哪個為準見 J6。

<sub>證據：剖析輸出搜尋 `S8.inc_vs_inc`、`S8.inc_vs_inc_status_order`、`S8.inc_vs_inc_status_examples`、`S5.inc_upd_before_batch`（`id_in_day1 true`）</sub>

<a id="j6"></a>
## J6｜base 的萃取時點與增量的切分基準〔待使用者判斷〕

L1、L2 顯示 base 與增量檔的 `updated_at` 都會超出檔名日期。增量切分要以「檔案」為準還是以 `updated_at` 為準、base 是否已含 07-01～07-03 的更新，需要使用者決定解讀（影響「以 updated_at 判斷新舊」的可靠度：12 列增量列比 base 同 id 列還舊）。另一個直接受影響的例子是 [L4](#l4)：25 個 id 依兩種基準會得到不同的最終狀態。

<a id="l10"></a>
## L10｜`completed` 的訂單出發日都還沒到〔可能合法〕

- 影響：base completed 28,612 列中 28,612 列的出發日晚於最後更新日。
- 為什麼可能合法：completed 可能是「付款／訂位完成」而不是「已出團」；增量檔中與 base 撞號的 completed 列才有出發日已過的情形。

<sub>證據：剖析輸出搜尋 `S5.status_vs_departure`</sub>

<a id="j8"></a>
## J8｜completed 的業務語意〔待使用者判斷〕

L10：completed 都發生在出發前。這影響「已完成營收」等指標的定義，屬業務問題。
