# T6 驗收發現的問題

T6（增量載入、狀態機、批次紀錄、冪等證明）由實作 agent 寫，再交給**沒看過實作過程的驗收 agent** 獨立檢查。共做了 1 輪完整驗收；修正後，連同 A-3 定案的實作，再做 1 次針對性驗收。第 1 輪的完整原始清單見 `t6-review-round1.md`。本檔整理所有發現，供使用者 review。

- 發現者：沒有另外註明的，都是驗收 agent。
- 怎麼確認修好：針對性驗收者自己把實作改壞，確認新測試會失敗，再還原。

## 總覽
| 輪 | 結論 | 最嚴重的問題 | 後續 |
|---|---|---|---|
| 1 | 有條件過 | 去重放在狀態機之前，會把往回走的轉移蓋掉（A4、A8）；MERGE 0 列時沒有標記，force 重跑會拿錯比對基準 | 修 6 項；去重規則請使用者定案 |
| 針對性（含 A-3 定案實作） | **有條件過**（沒有高、中嚴重度的問題） | net 可能變負數，程式沒處理、文件沒寫 | 3 項低嚴重度，待處理 |

## 第 1 輪先確認正確的部分
- 驗收 agent 只用 csv 和 Decimal，獨立重算三天的數字，和實作完全一致（base 100,040＝100,000＋40；day2 4,700＝4,060＋615＋略過 25；fact 112,060 列）。
- 6 種當掉時點（寫隔離表前、MERGE 前、MERGE 後、MERGE 0 列之後等）重跑，fact、隔離表、三張維度表的整表 hash 都和沒當掉時相同。
- `VACUUM` 之後 force 重跑會直接報錯，不會悄悄算錯。
- 合成邊界案例：跳過中間狀態、往回走、晚到事件、新訂單、大寫狀態值、未知幣別、批次順序錯誤、來源檔被改，都照規則處理。
- 查證 T5 驗收者的「狀態倒退」說法是錯的：增量和 base 同 order_id 的 1,808 列全是撞號，同身分 0 列（見 process-log「T6 驗收：T5 驗收者的『狀態倒退』說法是錯的」）。

## 第 1 輪
| 嚴重度 | 問題 | 會造成什麼 | 修法 |
|---|---|---|---|
| 中 | 去重（③）放在狀態機之前，而且不管兩列在時間上是否相鄰。A8：fact 是 created，同批送來 cancelled@08、paid@09、cancelled@10，cancelled@08 被當成重複刪掉 | 往回走的 cancelled→paid 被蓋掉，fact 變成 cancelled@10。A4 的同一秒衝突也被同樣蓋掉。本資料 0 筆 | 使用者定案「只有時間上相鄰的相同列才算重複」，理由：「中間如果有出現其他狀態 不能當作延遲」。`_dedupe` 改成以 (order_id, updated_at) 分組，只有相鄰兩組內容相同才去重；加 A8、A4 測試 |
| 中 | 該批 MERGE 0 列時不會產生 commit，沒有 `batch:<id>` 標記；force 重跑時 `version_before_marker` 回傳目前版本 | 實例：base B paid；day2 只有 B created（不合法）；day3 B completed。force 重跑 day2 時，原本的 `illegal_transition` 變成 `late_event`，隔離表與批次紀錄被改寫（fact 不受影響） | 實作者實測「寫一個帶標記的空 commit」不可行（Delta 不會產生 commit），改成每批開始前把 fact 版本記進 `batch_start` 表（`pin_fact_version`），刪掉 `version_before_marker`。ADR-05 的實作段落已更新 |
| 中低 | Spark driver 綁的是區網 IP，例如 `spark.driver.host=192.168.50.8` | 斷網時 IP 消失，收集十萬列的測試會失敗（推測，和「只有 orders_base 失敗」「Docker 需要 --hostname localhost」一致） | `build_spark` 設 `spark.driver.host=localhost`、`bindAddress=127.0.0.1` |
| 低 | 冪等證明只模擬一個當掉時點（寫完 fact 之後），也沒有比對維度表 | 「當掉後重跑相同」的證據不完整 | `idempotency_proof.py` 加「MERGE 前當掉」情境，並比對 dim_member、dim_product、dim_date 的 hash |
| 低 | README 沒寫 time travel 的保存期限，也沒寫 `--force` 不比對 checksum | 營運者不知道 `VACUUM` 之後就無法重跑 | 兩份 README 的「已知限制」補上 |
| 低 | `skipped_intermediate_rows` 文件寫「只算寫進 fact 的列」，程式也算了 superseded 的列（`cat.isin(ACCEPTED, SUPERSEDED) & _sm_skip`） | 對帳數字和文件定義不一致 | 程式改成只算 ACCEPTED |

## 針對性驗收（第 1 輪修正＋A-3 定案實作後）
結論：**有條件過**。驗收 agent 實測確認：
- **獨立重算一致**（純 Python csv＋Decimal，不 import pipeline）：

  | 批次 | 輸入 | 寫入 | 隔離 | 略過 | coupon 轉 NULL | V2 清單 | 本批 amount_twd | 本批 net |
  |---|---|---|---|---|---|---|---|---|
  | base | 100,040 | 99,950 | 90（contract 50 全是 amount≤0、duplicate 40） | 0 | 299 | 40 | 35,969,473,520.09 | 35,783,693,189.25 |
  | day1 | 4,615 | 4,000 | 615 | 0 | 0 | 0 | 1,056,883,370.88 | 1,055,002,970.88 |
  | day2 | 4,700 | 4,060 | 615 | 25 | 0 | 0 | 1,039,558,224.11 | 1,037,651,074.11 |
  | day3 | 4,615 | 4,000 | 615 | 0 | 0 | 0 | 1,020,981,665.19 | 1,019,042,815.19 |

  fact 全表 112,010 列，amount_twd 39,086,896,780.27，net 38,895,390,049.43。base 原始資料有 300 列 coupon 是 -1.0，寫進 fact 的 299 列，另 1 列落在隔離表。
- A8、A4、同一秒兩種內容、batch_start 的四種情境（中途當掉、force、MERGE 0 列、batch_start 寫了但後續失敗）都照規則處理。
- `delta_io.py` 的 `_commit_metadata` 把 unset 放在 `finally`，MERGE 失敗也會清掉標籤（主對話先前列的待查項）。
- valid＋rejected＝輸入在 V1 之後仍成立；隔離表保留 coupon 的原始字串 `-1.0`。
- 測試：not slow 226 passed；挑出的 10 條相關 slow 測試 passed；ruff 全過。
- 冪等證明：第一次 JVM 原生崩潰（macOS crash report 記錄 EXC_BAD_ACCESS/SIGKILL，當天另有兩次同類崩潰，判斷是環境問題）；照原樣重跑，結論「全部相同」，hash 和 README 一致。

改壞 4 種寫法，測試都抓得到：去重改回舊規則、coupon 不轉 NULL、V1 的 `<= 0` 改成 `< 0`、`pin_fact_version` 改成每次回傳目前版本。

| 嚴重度 | 問題 | 會造成什麼 | 修法 |
|---|---|---|---|
| 低 | coupon 大於 amount_twd 時 net 會變負數；-1 以外的負 coupon 會讓 net 大於 amount_twd。程式沒有處理，文件也沒寫（`"net_amount_twd": (F.col("amount_twd") - F.col("coupon_discount"))`） | 本資料 0 筆；之後的增量只要出現，就會悄悄寫進 fact | 待使用者定規則，至少寫進 README「已知限制」 |
| 低 | `pipeline/README.md`「批次紀錄」段落漏了 `coupon_nulled_rows`、`amount_review_rows`、`net_amount_twd_sum`、`fact_table_net_amount_twd_sum` | 文件和 `BATCH_LOG_SCHEMA` 不一致 | 補上欄名 |
| 低 | `pin_fact_version`、`_commit_metadata` 失敗時 unset，這兩件事只靠 slow 整合測試間接覆蓋，unset 完全沒有測試 | 之後重構時，fast 測試抓不到退化 | 加兩條小測試 |

## 實作者自己加或自己決定、待使用者確認的
- `spark.driver.memory=2g`：1g 時全套測試出現 Java heap space
- V2 清單門檻 100：比值正常是 0.84～1.29，疑似多乘 1,000 的約 1,000，取中間值；比值四捨五入到 2 位，產品落到 -1 的不列入
- coupon 轉 NULL 的計數只算寫進 fact 的列
- 品質規則測試的範例從「負數金額」改成「金額過大」，因為負數現在由合約擋下

---

## 值得 review 的模式
1. **單元測試都過，交互作用卻錯**：去重和狀態機各自都對，但去重先執行，就把狀態機要看的證據刪掉了。第 1 輪的突變測試也證實，當時沒有任何測試覆蓋這兩步的交互。這類問題要靠合成的反例（A4、A8）才抓得到。
2. **修法先實測再採用**：「寫空 commit 補標記」聽起來可行，實作者實測發現 Delta 不會產生 commit，才改成另記版本號。ADR 定案後實作仍然可能調整，這次決定本身沒變，只改了機制。
3. **驗收者也會被環境干擾**：冪等證明第一次是 JVM 崩潰，驗收者查了 crash report，判斷是環境問題後照原樣重跑，沒有把它當成程式 bug。
