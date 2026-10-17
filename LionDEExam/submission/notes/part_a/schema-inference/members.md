# 會員快照

回到：[README.md](README.md)｜問題總表：[issues.md](issues.md)

**結論**：
- members.csv 是會員表的每日萃取，主鍵應是 `(member_id, extract_date)`；但 04-30 有 30 組同日兩列、只差 member_level（V8），哪一列對資料推不出來。
- `city = 'N/A'`（V9）與 `birth_date = 1900-01-01`（V10）是「未知」的哨兵值，不是錯誤值；其中 5 人的真實生日在後來的快照被 1900-01-01 蓋掉（J9），是清空還是同步錯誤待使用者判斷。
- 其餘是可能合法的狀況：未成年註冊（L8）、等級與縣市變化（L9）、後續快照出現沒有變化的列（L11）。

<a id="v8"></a>
## V8｜members 同一 member_id、同一 extract_date 兩列（30 組）〔確定的錯誤值〕

- 違反：快照的 `PRIMARY KEY (member_id, extract_date)`。
- 影響：30 組（多 30 列），全在 2026-04-30；每組只有 member_level 不同，其他欄位相同（[S6.members_same_day_dup] `level_differs 30`、其餘 0）。
- 偵測查詢（[S6.members_pk]）：
  ```sql
  SELECT count(*) AS n_rows, count(DISTINCT member_id) AS n_members,
    count(DISTINCT member_id, extract_date) AS n_member_dates,
    count(*) - count(DISTINCT member_id, extract_date) AS extra_rows
  FROM members
  ```
- 範例（[S6.members_same_day_examples]）：`M000096 2026-04-30 金卡 / 銀卡`、`M000296 2026-04-30 白金 / 金卡`。
- 哪一列是對的，資料推不出來（同日、沒有時間戳）。

<a id="v9"></a>
## V9｜members.city = 'N/A'（71 列）〔未知值的哨兵〕

- 違反：city 的值域（10 個縣市）；推測原值為 NULL。
- 影響：71 列、70 位會員；各快照日 66 / 3 / 2（[S9.birth_1900] `city_na`）；其中 9 位在其他快照有真實縣市（[S9.city_na_change]）。
- 偵測查詢（[S1.members]，每欄套同一模板）：
  ```sql
  SELECT 'city' AS col, count(*) AS n_rows, sum(CASE WHEN `city` IS NULL THEN 1 ELSE 0 END) AS n_null_or_empty,
    sum(CASE WHEN trim(`city`) IN ('N/A','NA','n/a','null','NULL','None','none','-','?','UNKNOWN','unknown','#N/A','NaN','nan') THEN 1 ELSE 0 END) AS n_placeholder,
    sum(CASE WHEN `city` <> trim(`city`) THEN 1 ELSE 0 END) AS n_untrimmed, count(DISTINCT `city`) AS n_distinct FROM members
  ```
  其他 6 個檔、所有欄位的空值、佔位字、前後空白都是 0（[S1.*]）。

<a id="v10"></a>
## V10｜members.birth_date = 1900-01-01（81 列）〔未知值的哨兵〕

- 違反：birth_date 的合理範圍；推測是「未知」的預設值。
- 影響：81 列（各快照日 76 / 2 / 3，[S9.birth_1900]）。1900 以外最早 1960-01-03（[S9.birth_dist]），中間沒有任何值。
- 補強證據〔新發現〕：19 位會員的 birth_date 在快照間變過，每一次變化都有一端是 1900-01-01（[S9.birth_change_detail] 19 人、1900 列 19 列），沒有「真實日期 → 另一個真實日期」。**方向有兩種**（[S9.birth_change_direction]，依 extract_date 排序相鄰兩列）：
  - `1900 -> real` 14 人：後來的快照補上了真實生日（例 M000552、M000708、M001372）。
  - `real -> 1900` 5 人：**原本的真實生日在後來的快照被 1900-01-01 覆寫**（例 M001647、M001931、M003842）。這是另一種品質問題：不只是「不知道」，而是已知值被哨兵值蓋掉。是上游清空欄位、還是匯出時把某種狀態寫成 1900，資料推不出來，列入 J9。
  - 兩個方向都說明 1900-01-01 是哨兵值，不是真實生日。
- 偵測查詢（[S9.birth_1900]）：
  ```sql
  SELECT extract_date, count(*) AS n_rows, sum(CASE WHEN birth_date = '1900-01-01' THEN 1 ELSE 0 END) AS birth_1900,
    sum(CASE WHEN city = 'N/A' THEN 1 ELSE 0 END) AS city_na,
    sum(CASE WHEN birth_date = '1900-01-01' AND city = 'N/A' THEN 1 ELSE 0 END) AS both
  FROM members GROUP BY extract_date ORDER BY extract_date
  ```
- 範例：1900 → 真實（[S9.birth_change_examples]）`M000552 1900-01-01 (04-30) → 1981-07-25 (06-30)`、`M000708 1900-01-01 (04-30) → 1996-11-05 (05-31)`；真實 → 1900（[S9.birth_real_to_1900_examples]）`M004004 1994-10-13 (04-30) → 1900-01-01 (05-31)`、`M001647 1961-07-15 (04-30) → 1900-01-01 (06-30)`、`M003842 1999-09-01 (04-30) → 1900-01-01 (05-31)`。
- 偵測查詢（[S9.birth_change_direction]）：
  ```sql
  WITH s AS (SELECT member_id, extract_date, birth_date,
      lag(birth_date) OVER (PARTITION BY member_id ORDER BY extract_date, member_level) AS prev_birth
    FROM members)
  SELECT CASE WHEN prev_birth = '1900-01-01' THEN '1900 -> real'
              WHEN birth_date = '1900-01-01' THEN 'real -> 1900'
              ELSE 'real -> other real' END AS direction,
    count(DISTINCT member_id) AS n_members, count(*) AS n_transitions,
    slice(array_sort(collect_set(member_id)), 1, 3) AS example_members
  FROM s WHERE prev_birth IS NOT NULL AND prev_birth <> birth_date GROUP BY 1 ORDER BY 1
  ```
- **值得質疑 Q7（分組的界線是我畫的）**：V3（coupon -1）、V9（N/A）、V10（1900）已改放「未知值的哨兵」一組，和 V1、V2 這種錯誤值分開；但 V10 中「真實 → 1900」那 5 人可能是真正的資料損毀，也可能是上游刻意清空，兩種解讀見 J9。

<a id="j7"></a>
## J7｜members 的 N/A、1900-01-01、同日兩列〔待使用者判斷〕

是否視為 NULL／未知；同日兩列（V8）資料沒有可判斷先後的欄位，要用什麼規則挑一列，或兩列都保留並標記。

<a id="j9"></a>
## J9｜birth_date 的真實值被 1900-01-01 覆寫（5 人）〔待使用者判斷〕

V10 中 5 位會員是「真實日期 → 1900-01-01」（[S9.birth_change_direction]）。可能的解讀：上游刪除或清空了生日（例如會員要求移除個資），匯出時以 1900 表示；或上游同步錯誤把已知值蓋掉。前者代表「最新值就是未知」，後者代表「最新值是錯的、前一次才是對的」。資料裡沒有能區分兩者的欄位。

<a id="l8"></a>
## L8｜會員註冊時未滿 18 歲（排除 1900-01-01）〔可能合法〕

- 影響：455 列；最小 11.5 歲。
- 證據：[S9.dates_logic]。
- 為什麼可能合法：家庭成員或未成年帳號。

<a id="l9"></a>
## L9｜會員 member_level、city 在快照間改變〔可能合法〕

- 影響：level 434 人（含 V8 同日矛盾）、city 376 人。
- 證據：[S9.attr_change]。
- 為什麼可能合法：SCD2 本來就要處理的正常變化。
- 與既有筆記：`dictionary.md` 記跨快照日 406 人＋同日矛盾 28 人 = 434；本次 434（[S9.attr_change]），一致；本次的 434 是「任一列等級不同」，沒有拆開跨日與同日。

<a id="l11"></a>
## L11｜後續快照中有屬性與前次完全相同的列〔可能合法〕〔新發現〕

- 影響：05-31 94 列、06-30 91 列。
- 證據：[S9.snapshot_pattern]。
- 為什麼可能合法：萃取規則未知。
- 與既有筆記：`dictionary.md` 推測後續快照「看起來像有變更才出現」（未證實）；這 185 列反駁了「只有變更才出現」。
