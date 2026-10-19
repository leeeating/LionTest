# T6 驗收發現的問題（第 1 輪原始清單）

T6 由驗收 agent 獨立檢查。它沒看過實作過程，結論是「有條件過」。下面原樣保留它的完整清單；用到的臨時腳本放在當時的 /tmp/t6rev/，沒有進 repo。修正與後續驗收的經過，T6 完成後再補成和 T3～T5 相同格式的 review 文件。

---

# T6 獨立驗收（詳細清單）

## 1. 指令輸出
- `uv run pytest LionDEExam/submission/part_a/tests -q` → 235 passed in 1093.23s
- `TZ=UTC uv run pytest ... -q` → 235 passed in 1978.83s（機器同時跑 Docker／突變測試，負載高）
- `uv run ruff check LionDEExam/submission/part_a` → All checks passed!
- `idempotency_proof.py` → exit 0，6 分鐘；fact 112,060／39074507338.40／ff205ce196fc，隔離 1,910／4ea27a4ad713，實驗 1、2 全部「是」，結論「全部相同」，和 README 表格逐字一致
- flaky 測試 `test_all_sources_follow_contract_and_conserve_rows`：連跑 3 次 7 passed（15.6s／16.3s／17.3s）

## 2. 純 Python 獨立重算（/tmp/t6rev/recompute.py，csv＋Decimal，不 import pipeline）
| 批次 | 輸入 | 寫入 | 隔離 | 略過 | 本批 amount_twd |
|---|---|---|---|---|---|
| base | 100,040 | 100,000 | 40（duplicate 40） | 0 | 35,957,084,078.22 |
| day1 | 4,615 | 4,000 | 615（collision 6、collision_existing 594、duplicate 15） | 0 | 1,056,883,370.88 |
| day2 | 4,700 | 4,060 | 615（collision 2、collision_existing 598、duplicate 15） | 25 | 1,039,558,224.11 |
| day3 | 4,615 | 4,000 | 615（collision 4、collision_existing 596、duplicate 15） | 0 | 1,020,981,665.19 |
fact 112,060 列，amount_twd 39,074,507,338.40；狀態 paid 50,918／completed 28,596／created 18,280／cancelled 14,266。
L4：day2 有 25 列和 day1 同身分、updated_at 較舊（cancelled→收到 paid），最後 25 張全是 cancelled。全部與實作宣稱一致。

## 3. T5 驗收者 vs T6 實作者（/tmp/t6rev/q3b.py）
- base updated_at 落在 07-01～07-03：2,265 列（T5 說法正確）
- 其中 order_id 也出現在增量：47 張、47 列；其中 12 列增量比 base 那列舊（T5 說法正確）
- 但這 47 列和 base 同身分（member、下單時刻、amount 全同）的列數：0
- 擴大到全部：增量和 base 同 order_id 的 1,808 列，三欄「全部」不同 1,808 列、同身分 0 列
- 結論：T6 對。T5 只用 order_id 比對，把「不同訂單撞號」當成同一張單的狀態更新。例：ORD00058963 day1 completed M007192 237376.0 vs base paid M002193 5016.24。舊版無條件 MERGE 的確會用另一張單蓋掉 base 那列，但現在這些列在 ④ 以 collision_existing 隔離，從不進 MERGE；MERGE 的 updated_at 條件是第二道防線。
- 1,808 列 vs collision_existing 1,788 列：差的 20 列在 ②／③ 已被淘汰（同批撞號或 duplicate）。

## 4. 冪等與當掉重跑（/tmp/t6rev/crash.py，合成資料，比 fact、隔離、dim_member、dim_date、dim_product 整表 hash＋各批對帳）
| 情境 | 結果 |
|---|---|
| day1 寫隔離表之前當掉 | SAME |
| day1 寫完 dim_date 後當掉 | SAME |
| day1 隔離表寫完、MERGE 之前當掉 | SAME |
| day1 MERGE 之後、批次紀錄之前當掉 | SAME |
| day2（MERGE 0 列、沒有 commit）之後當掉 | SAME |
| day1 先在 MERGE 後當、重跑又在 MERGE 前當、第三次完成 | SAME |
| VACUUM(0) 之後 force 重跑 day1 | 大聲失敗（fileNotExistError），不會默默算錯 |
fact history：`[(0,WRITE,batch:base),(1,MERGE,batch:day1),(2,MERGE,batch:day3)]`：證實 MERGE 0 列時不產生 commit、沒有標記。
漏洞（/tmp/t6rev/force_hole.py 實證）：該批第一次跑 MERGE 0 列 → 沒有標記 → force 重跑時 version_before_marker 回傳「目前版本」，和之後批次寫過的 fact 比。
  例：base B paid；day2 只有 B created（不合法）；day3 B completed。第一次 day2 = illegal_transition 1；day3 後 force day2 = late_event 1（略過），隔離表與批次紀錄被改寫。fact 不受影響。

## 5. 合成邊界（/tmp/t6rev/syn_run.py，走 run_batch 完整流程）
| 情境 | 期望 | 實際 |
|---|---|---|
| A1 fact created，增量 completed（跳過中間） | 寫入、計數 | OK（skipped_intermediate 計入） |
| A2 fact paid；cancelled→paid→completed | cancelled 寫入，paid illegal，completed after_illegal | OK |
| A3 fact completed；晚到 paid | late_event 略過、仍在隔離表 | OK |
| A3 晚到 cancelled | late_event_conflict | OK |
| A5 新訂單第一狀態 completed | 寫入、不標跳過 | OK |
| A6 新訂單 created→completed | created superseded，completed 寫入並計數 | OK |
| A7 `PAID`、A9 `EUR` | contract | OK |
| day2 在 day1 之前跑 | BatchOrderError | OK |
| 已完成的 day1 來源檔被改 | SourceChangedError | OK |
| day2 cancelled 之後送 paid | illegal_transition | OK |
| **A4** fact created；paid@10、cancelled@12、completed@12、completed@13 | paid 寫入；12:00 兩列 ambiguous_order；13:00 after_illegal；fact=paid | **錯**：completed@12 被 ③ 當 duplicate 拿掉 → 沒偵測到同秒衝突；fact=cancelled@12，paid superseded，completed@13 illegal |
| **A8** fact created；cancelled@08、paid@09、cancelled@10 | cancelled@08 寫入；paid illegal；cancelled@10 after_illegal | **錯**：cancelled@08 被當 duplicate → 鏈變成 paid→cancelled 合法；fact=cancelled@10，往回走沒被抓到 |
真實資料：四個檔「同一張單在同批中同狀態不相鄰重複」都是 0（/tmp/t6rev/dupcheck.py），所以三天數字不受影響。

## 6. 突變測試（/tmp/m1～m3 副本）
| 突變 | 結果 |
|---|---|
| FACT_UPDATE_CONDITION = None | 快速測試 213 全過；slow 的 test_fact_order_merge_never_regresses_updated_at 失敗 → 抓到（只有這一條 slow 測試守住） |
| REACHABLE 改成一步轉移＋自反 | test_fact_order_state_machine_runs_inside_transform 失敗 → 抓到 |
| late_event 不寫進隔離表 | 同上失敗 → 抓到 |
缺的測試：③去重與⑤狀態機交互（A4、A8 這類）沒有任何測試。

## 7. Docker
build 成功；`docker run --rm --network none --hostname localhost liontest-parta` exit 0，四批數字與本機完全相同（fact 112,060／39,074,507,338.40）。

## 8. flaky 判斷
測試本身沒有外部依賴（只讀 repo 內 CSV），連跑 3 次全過。build_spark 沒設 driver host，實測 `spark.driver.host=192.168.50.8`（LAN IP）。orders_base 是唯一 collect 十萬列的來源，task 結果超過 1MB 時 Spark 透過 BlockManager 走網路位址回傳 driver；斷網時 LAN IP 消失就會失敗。這是推測（未重現斷網），但和「只有 orders_base 失敗」「Docker 需要 --hostname localhost」一致。

## 9. README／CLAUDE.md
- 三天數字、冪等表格、怎麼跑、Docker 指令與實跑一致；防護性設計都有標。
- 「冪等證明（約 5 分鐘）」：實測 6 分鐘（高負載），可接受。
- 冪等證明只當在一個時點（寫完 fact 之後），也沒有比維度表。
- skipped_intermediate_rows 文件寫「寫進 fact 的列中」，程式碼也計入 superseded 的列（`skipped = cat.isin(ACCEPTED, SUPERSEDED) & _sm_skip`）。
- 沒看到違反 CLAUDE.md：文件沒有行號，沒有 commit。
