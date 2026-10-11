# buggy_pipeline.py 審查報告附錄

正式報告：[code-review.md](code-review.md)｜證據：[evidence.md](evidence.md)

問題編號（#1～#11）見報告的「問題總表」。

## 方法

1. **靜態閱讀**：逐函式追資料流，對每個寫入、filter、join 檢查四件事：重跑會怎樣、哪些列會消失或變多、數字算得對不對、SCD2 是否完整。
2. **用真實資料量化影響**：題目要求不執行原管線，所以 `buggy_pipeline.py` 本身沒有執行，只用 `python3 -m py_compile` 確認語法正確。「業務影響」中的筆數，是用 Python 標準庫 `csv` 直接讀 `candidate_package/dataset/` 算出「如果這段邏輯跑下去會影響幾筆」。
3. **靜態分析**：用 ruff 0.17.0（預設規則，專案沒有 ruff 設定檔）與 mypy 2.4.0 檢查 `buggy_pipeline.py`，看工具能自動抓到哪些問題，結果見下方「靜態分析（ruff、mypy）」。
4. **用小資料驗證關鍵語意**：撰寫期間另外在本機 `.venv`（pyspark 4.2＋delta-spark）用自建的小資料驗證關鍵語意：`dropDuplicates` 之後再套 window 沒有作用（#2）、`"replaceWhere", "member_id IS NOT NULL"` 搭配 overwrite 會清表（#6）、字串金額和整數比較的隱式轉型（#1）（E5、E6）；Delta 的重跑、RESTORE、VACUUM、並行衝突（E10）；MERGE 來源同 key 多列、`enforceSchema`、換算乘法的型別（E12）。以上查詢、腳本與輸出見 [evidence.md](evidence.md)；資料結構見 `notes/dataset/`。
5. **嚴重度**：分 P0～P2，定義見報告「問題總表」。

## 靜態分析（ruff、mypy）

程式自稱已通過語法檢查；以下檢查 linter（ruff）與型別檢查器（mypy）能抓到報告第 4 節 11 個問題中的多少個。

**指令與輸出**（在 repo 根目錄執行，ruff 0.17.0，預設規則）：

```
$ uv run ruff check --output-format concise LionDEExam/candidate_package/buggy_pipeline.py
LionDEExam/candidate_package/buggy_pipeline.py:1:1: UP009 [*] UTF-8 encoding declaration is unnecessary
LionDEExam/candidate_package/buggy_pipeline.py:14:1: I001 [*] Import block is un-sorted or un-formatted
LionDEExam/candidate_package/buggy_pipeline.py:172:5: F841 Local variable `dim_member` is assigned to but never used
Found 3 errors.
[*] 2 fixable with `--fix` (1 unsafe fix available with `--fix --unsafe-fixes`).
```

| 規則 | 位置（函式／片段） | 意義 | 影響 |
|---|---|---|---|
| UP009 | 檔案開頭 `# -*- coding: utf-8 -*-` | Python 3 預設就是 UTF-8，編碼宣告多餘 | 只是風格，不影響正確性 |
| I001 | 檔案開頭的 import 區塊 `from pyspark.sql import SparkSession, functions as F, Window` | import 沒有排序 | 只是風格，不影響正確性 |
| F841 | `main()`：`dim_member = update_dim_member(members)` | 變數被指派但從未使用 | 正好是 #7 的跡象 |

**F841 對應 #7**：維度表算出來了（`dim_member`），事實表卻沒用它，`build_fact(converted, members, products)` 傳進去的是原始的 members 快照。linter 抓得到「變數沒用到」這個症狀，抓不到背後的業務錯誤：它不知道 `members` 有多個快照、join 會一對多放大金額，也不知道事實表該用 point-in-time join 取當時的等級。

**再用型別檢查器 mypy 跑一次**（mypy 2.4.0，以 `uv run --with mypy` 臨時安裝，不改專案依賴；pyspark 4.2 自帶型別資訊）：

```
$ uv run --with mypy mypy LionDEExam/candidate_package/buggy_pipeline.py
Success: no issues found in 1 source file
$ uv run --with mypy mypy --check-untyped-defs LionDEExam/candidate_package/buggy_pipeline.py
LionDEExam/candidate_package/buggy_pipeline.py:159: error: Need type annotation for "counts" (hint: "counts: dict[<type>, <type>] = ...")  [var-annotated]
Found 1 error in 1 file (checked 1 source file)
$ uv run --with mypy mypy --strict LionDEExam/candidate_package/buggy_pipeline.py
（14 個錯誤：13 個是函式或呼叫缺型別標註〔no-untyped-def、no-untyped-call〕，另 1 個同上的 counts，完整輸出見 evidence.md E8）
```

| 模式 | 結果 | 意義 |
|---|---|---|
| 預設 | 0 個 | mypy 預設**不檢查完全沒標註的函式內容**。8 個函式（含 `convert_currency` 裡的 UDF `to_twd`）中只有 `load_sources`、`main` 有參數標註，其餘 6 個它沒看；有看的 `load_sources`（#1 所在）也是 0 個，因為 `csv()` 回傳的就是 `DataFrame` |
| `--check-untyped-defs` | 1 個 | 要求標註 `write_fact` 裡驗證用的 `counts = {}`；不是 bug，旁邊的 `collect()`（#10）它抓不到 |
| `--strict` | 14 個 | 全部是「缺型別標註」，沒有一個對應第 4 節的問題 |

**為什麼型別檢查抓不到**：PySpark 的型別只到 `DataFrame` 這一層，欄位名稱和欄位型別是執行時才知道的字串。`join` 用 inner 還是 left、`mode("append")` 還是 MERGE、`amount` 是字串還是數字（#1），在型別上都一樣是 `DataFrame`。

**結論**：ruff 只抓到 11 個問題中 1 個的跡象（#7），mypy 一個都沒抓到；其餘 10 個（丟單、重複寫入、SCD2 覆寫、隱式轉型等）都是語意層面的錯，語法與型別都合法。所以 AI 宣稱的「通過語法檢查」不能代表程式正確。

## SCD2 初始載入

補充報告 #6 (c) 的「初始載入」。

報告 #6 (c) 的寫法每次只拿每位會員最新的 `extract_date` 去 MERGE，適用於 dim 已有歷史之後的每日增量。dim 從空表開始時，若直接拿現在的 `members` 跑，每位會員只會建出最新的一版，2026-04-30、05-31 的舊快照永遠進不了 dim，#6 (b) 的 406 位跨快照日等級變過的會員，舊等級就丟了，等於退化成 SCD1。搭配 #7 的半開區間 join，`order_date` 早於該會員唯一一版 `valid_from` 的訂單對不到任何版本，`member_level` 變成 null：實測 day1 去重後（每個 order_id 留 `updated_at` 最新一列）4,597 張中有 49 張（48 位會員，`order_date` 落在 05-01～06-28），因為這些會員的最新 `extract_date` 是 05-31（16 張）或 06-30（33 張）。做法二選一，之後再接每日增量（只處理比 dim 已載入的最新 `extract_date` 更新的快照）：
- **依 `extract_date` 由舊到新逐批 MERGE**（04-30 → 05-31 → 06-30）：沿用同一段邏輯，屬性沒變的批次自然不產生新版本，最單純。
- **一次性回填全部快照**：用 window 依 `extract_date` 排序，以下一筆快照的 `extract_date` 當這一版的 `valid_to`；但要自己合併相鄰且屬性相同的快照（否則沒變也多一版），同日同分也要先處理。

新會員第一版的 `valid_from` 有三個選擇，選哪個屬於業務定義，需要確認：
- **第一筆快照的 `extract_date`**：只記錄實際觀測到的狀態；代價是早於第一筆快照的訂單對不到任何版本。目前資料除同分會員外沒有這種訂單（逐批 MERGE 後，不含被隔離的 28 位同分會員：day1 去重後有 17 張對不到，要靠 #6 的隔離告警處理，其餘 0 張；`orders_base` 日期為 ISO 格式的 97,039 列也是 0 列早於該會員最早的 `extract_date`）。
- **`register_date`**：會員從註冊起就有一版；代價是把第一筆快照的等級往前套到註冊日，這是推定，不是觀測。目前資料沒有會員的 `register_date` 晚於最早的 `extract_date`，day1、base 也沒有訂單早於 `register_date`。
- **很早的固定日期（例如 1900-01-01）**：保證每張訂單都對得到一版；代價同樣是推定，而且看不出哪些區間是推定的。

證據：`evidence.md` E3、E4、E7。
