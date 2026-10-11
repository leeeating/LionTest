# buggy_pipeline.py 已部署到 prod：資料怎麼復原

正式報告：[code-review.md](code-review.md)｜證據：[evidence.md](evidence.md)

問題編號（#1～#11）見報告的「問題總表」。

**前提**：這支程式的 PR 已合併，在 prod 跑過幾個批次，ANSI 關閉（Fabric 的 Spark 3.x runtime，見 #1）。若 ANSI 開啟，每一批都會在 `write_fact` 報錯，但 `update_dim_member` 已先寫入，結果是 fact 乾淨、只有 dim 被 #6 覆寫，只需修 dim。

**結論：現有的表不能就地修補。要從乾淨的起點、用修正後的程式重新寫入新表，對帳後再切換。** 乾淨的起點有兩種：

| 起點 | 做法 | 前提 |
|---|---|---|
| A. 退回 bug 之前的版本 | 用 `versionAsOf` 讀出乾淨版本、寫成獨立的新表，再重播增量 | 重播用的 landing 增量檔還在；有乾淨版本（fact 若是這支程式第一次 append 時才建立，版本 0 就已有錯；dim 這支程式建不出來，一定是別人建的）；舊資料檔與交易紀錄都還在保留期內；新程式需要的欄位（fact 的 `updated_at`、dim 的 `valid_to`、`is_current`）要先補上並回填，否則「`updated_at` 比較新才更新」的條件比不出結果，更新會被靜默略過（類似 `evidence.md` E10 [6]；[6] 測的是時間相同，欄位為 null 的情況依 SQL 語意推論，未實測） |
| B. 從原始檔重建 | dim 用 `members.csv` 的歷次快照依 `extract_date` 回填（#6 (c) 的初始載入，做法見[附錄「SCD2 初始載入」](appendix.md#scd2-初始載入)），fact 從 `orders_base` 起依序重播 | landing 的原始檔都還在 |

A 的好處是保留 bug 上線前 fact 已有的歷史：這支程式從沒讀過 `orders_base`，那些歷史從哪裡來沒有交代，B 只能從 `orders_base` 近似。#3、#4、#8 丟掉的訂單兩條路都一樣，只能靠重播增量補回；RESTORE 或 CLONE 只會退掉錯的資料，不會補回沒寫的資料。28 位同分會員不論哪條路，都要上游確認後才能補齊（#6）。

**步驟**：
1. 停止排程，暫停 VACUUM，並調高保留期，保住舊版本。
2. 用 `DESCRIBE HISTORY` 找出 bug 跑了哪些批次、最後一個乾淨版本。
3. 先建 dim，驗證後再建 fact：修正後的 fact 要用 point-in-time join 對 dim 的有效區間（#7 (c)），dim 沒先好，訂單會對不到版本。
4. 對帳：新表的筆數、金額要和原始檔對得上（輸入 = 輸出 + 隔離，#10），通過後才取代正式表。
5. 通知下游哪些日期的數字有誤，重新發佈。

**回不去的部分（單向門）**：
- **超過保留期**：VACUUM 會刪掉超過保留期的舊資料檔（Delta 規格預設 7 天，[PROTOCOL](https://github.com/delta-io/delta/blob/master/PROTOCOL.md)），之後交易紀錄還列得出舊版本，但 time travel 與 RESTORE 都會失敗（`evidence.md` E10 [3]）。交易紀錄本身也會在寫 checkpoint 時自動清掉超過保留期的部分（預設 30 天，[Delta 文件](https://docs.delta.io/latest/delta-batch.html)），所以就算沒跑 VACUUM，也不是永遠退得回去。開源 Delta 不會自動 VACUUM；Fabric 是否排程了表格維護，要查 workspace 設定（未查證）。超過保留期就只剩 B。
- **landing 原始檔被刪除或覆寫**：丟掉的訂單補不回來。`members.csv`、`products.csv`、`fx_rates.csv` 的檔名沒有日期，若 prod 每天覆寫，重播只能用現在的主檔近似當時的狀態。
- **下游已經用掉的數字**：表修好也收不回。

所以修正後的版本除了報告 5.2 的修改，還要做到：landing 原始檔不可修改、不可刪除（主檔按日保存）；保留期長於「發現錯誤所需的時間」；寫入後的斷言（#10）不通過就停止排程並告警，不讓錯誤流到下游。
