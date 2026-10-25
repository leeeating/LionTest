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

---

## 後續修改的驗收（2026-10-19，commit b975543 之後）
T6 通過後，又做了四件事：`cast_to_contract` 效能重構、net 變負數規則、checksum 涵蓋參考資料（含 force 留紀錄）、上一輪的低嚴重度問題。由同一位實作 agent 完成，再交給兩位沒看過實作的驗收 agent，各驗一輪。

| 輪 | 結論 | 最嚴重的問題 | 後續 |
|---|---|---|---|
| 1 | 有條件過 | force 紀錄寫在 `run()` 之後：force 重跑到 MERGE 之後當掉，fact 已被改寫卻沒有任何紀錄，牴觸使用者理由「如果要修改需要使用force來紀錄」 | 改成 run() 之前先寫 `started`、完成後寫 `completed`；紀錄表設 `delta.appendOnly` |
| 2 | **過** | 無（2 項低嚴重度） | 268 passed、冪等證明「全部相同」、ruff 全過 |

**第 1 輪確認正確的部分**
- 只算一次：在輸入掛計數 UDF，舊版每個 action 都重算 100,040 次，新版只有第一個 action 算。
- valid＋rejected＝100,040，用 `_raw` 與原始輸入雙向 exceptAll，差集都是 0。
- coupon：-1、-1.0、-1.00 都放行；coupon 大於 amount_twd 才列入清單，相等不列；兩種原因同時命中只列一列。
- 效能實測（3 次）：`cast_to_contract` 單獨 2.2～2.8 倍快；整個 base 批次快 20～30%（每輪舊版先跑，可能有暖機偏差）。實作者原本回報「整條管線量不出差異」，是在機器 swap 4～6GB 時量的。

**第 1 輪的低嚴重度（已修）**：`batch_log_force` 改用 `delta.appendOnly`；冪等證明表頭改名；`cast_to_contract` 文件改精確說法（輸入有 shuffle 時 AQE 會先跑 job）；README 補「schema 變動後需重建倉儲」。

**第 2 輪實測**：MERGE 之後當掉、run() 一開始就失敗，都會留下 `started`；同一批 force 多次可用 `forced_at` 配對；DELETE、UPDATE、overwrite、MERGE 改值都被 appendOnly 拒絕；`started` 寫入失敗時 run() 不會執行，狀態一致。把 started 移回 run() 之後，新測試會失敗。

**第 2 輪留下的低嚴重度（未處理）**
| 問題 | 會造成什麼 | 建議 |
|---|---|---|
| force 當掉後，把來源改回再一般重跑，仍回 skipped，不會提示 | fact 和 batch_log 不一致，只有主動查 `forced_runs` 才看得到沒配對的 started | 跳過時發現沒配對的 started 就發 WARNING，或 README 註明要再 force 一次 |
| 「只有 started 代表沒完成」不完全精確 | 先寫 batch_log 再追加 completed，追加失敗時會誤判成沒完成（偏保守） | 改文件說明，或不處理 |

## 值得 review 的模式（後續修改）
4. **實作者的效能宣稱被驗收者推翻，方向相反**：實作者說「量不出差異」，驗收者重量得到快 20～30%。量測環境（swap）會讓結論完全不同，量的宣稱一定要寫明條件。
5. **驗收者拿使用者的原話檢查實作**：force 紀錄的問題不是程式錯，而是沒做到使用者定案時的理由。

## 會員隔離、Delta CHECK、排除清單後總和的驗收（2026-10-24～25）
使用者補定三項（會員對不到進隔離表、會員快照違規列另開隔離表、Delta CHECK）與 V2 的 B1 口徑後，由實作 agent 完成，兩位沒看過實作的驗收 agent 各驗一輪。

| 輪 | 結論 | 最嚴重的問題 | 後續 |
|---|---|---|---|
| 1 | 有條件過（無高中嚴重度） | 會員隔離表在上游改了 extract_date 本身時舊列清不掉，docstring 寫過頭；CHECK 先 DROP 再 ADD，ADD 失敗時有空窗；後續狀態事件理論上可能被誤隔離成 member_missing | 1、3 改文件；2 改成 DROP 前先查違規列 |
| 2 | 有條件過（只剩文件） | `pipeline/README.md` 對 CHECK 替換的敘述沒跟上新行為 | 主對話修正一句 |

**確認正確的部分**
- 第 1 輪：276 passed；用最終程式碼重跑冪等證明「全部相同」（第一次跑到一半機器休眠、JVM 被系統殺掉，`caffeinate -i` 重跑）；DuckDB 獨立重算 39,086,896,780.27／28,984,405,090.57／差額 10,102,491,689.70 吻合；壞列不蓋掉上一個好版本；直接 SQL `UPDATE` 寫違規值被 CHECK 拒絕。改壞 4 項（拿掉 member_missing、隔離表改 append、約束每次 ADD、拿掉 DISTINCT）都被測試抓到。
- 第 2 輪：主對話特別請驗收者查「DROP 前檢查把 NULL 算成違規，會不會誤擋合法的 NULL」。實驗確認不會：`coupon_discount IS NULL OR >= 0` 遇到 NULL 照常替換；NULL 的判定和 Delta 自己 ADD CONSTRAINT 一致；正常重跑時約束文字比對相同，不會進入檢查與 DROP。

**營收用詞**：使用者決定 Part A 不定義營收（process-log「營收的定義不在 Part A 決定，移到 Part C 語意層」）。`REVENUE_SQL`／`revenue()` 改名為 `AMOUNT_EXCLUDING_REVIEW_SQL`／`amount_totals()`，文件照實描述範圍（所有狀態、折扣前）。A-3 報告與 `data_quality_queries.py` 的「營收」用詞留到 A-3 收尾一起改。

**實作者自己做的決定（驗收認為合理）**：拿掉 dim_member 的 -1 列；新類別 `member_missing` 放在對維度那一步；`unknown_member_rows` 改語意保留；會員隔離表以快照日 replaceWhere；CHECK 只加在 fact_order 6 條。
