# 觀念筆記

這裡是我在做這份 take-home 的討論中選出、**可以帶到其他專案**的 SWE 觀念筆記，例如套件／工具的用法、SQL 寫法與模式。一個觀念一份，約一頁。這裡不是繳交物的結論。

**放這裡還是 `notes/`**：換一個專案照樣能用的技能放這裡；只跟這份資料、這支程式有關的放 `../notes/`。

## DE 觀念地圖（bottom-up）

只收**實際碰過**的觀念，往上歸類。分類借用 DE 生命週期的說法（Reis & Housley《Fundamentals of Data Engineering》的 lifecycle 與 undercurrents），「題目」欄標出雄獅這份 take-home 考到的地方。

圖例：📄 已有筆記｜○ 本專案碰過、還沒寫筆記（之後照 concept-note 流程挑來寫）

### 0. 儲存與架構（Storage）
| 觀念 | 狀態 | 本專案在哪碰到 | 題目 |
|---|---|---|---|
| Data lake、warehouse、lakehouse：資料存成什麼形式 | 📄 [data-lake-vs-warehouse.md](data-lake-vs-warehouse.md) | `buggy_pipeline.py` 的 `LAKEHOUSE`、`format("delta")` | B、C |

### 1. 資料建模（Transformation／Data architecture）
| 觀念 | 狀態 | 本專案在哪碰到 | 題目 |
|---|---|---|---|
| SCD：維度歷史怎麼保存（Type 0～4、6） | 📄 [scd.md](scd.md) | Part B #2、#6 `update_dim_member` | A-1 指定 SCD2、B |
| point-in-time join：對到「當時」的維度版本 | 📄 [point-in-time-join.md](point-in-time-join.md) | Part B #4、#6 | A-1、B |
| join 一對多膨脹：join 前先確認 key 唯一 | ○ | Part B #4 `converted.join(members, "member_id", "left")` | A-1、A-2、B |
| 事實表粒度：一列代表什麼（事件 vs 訂單） | ○ | `notes/dataset/dictionary.md` 總覽表的「粒度」欄 | A-1 |

### 2. 增量與冪等 ETL（Ingestion／Transformation）
| 觀念 | 狀態 | 本專案在哪碰到 | 題目 |
|---|---|---|---|
| MERGE 冪等寫入：重跑結果不變 | 📄 [merge-idempotent-write.md](merge-idempotent-write.md) | Part B #3 `write_fact` 的 `mode("append")` | A-2、B |
| 取每組最新一筆：事件型增量去重 | 📄 [latest-row-per-group.md](latest-row-per-group.md) | Part B #5 `clean_orders` | A-2、B |
| 晚到資料（late-arriving）：本該在前一批出現的資料晚到 | ○ | `notes/dataset/incremental.md`：day2 有 6 列 `updated_at` 早於批次日 | A-2 |
| 增量檔的時間欄位與批次日不一致（約 70% `updated_at` 晚於批次日，原因未證實） | ○ | `notes/dataset/incremental.md` 的 `updated_at` 分布 | A-2 |

### 3. 資料品質（Data management）
| 觀念 | 狀態 | 本專案在哪碰到 | 題目 |
|---|---|---|---|
| 隔離表：不合格資料不靜默丟掉 | ○ | Part B #1、#7、#8 的 inner join 與 filter | A-3、B |
| 筆數對帳與斷言：輸入 = 輸出 + 隔離 | ○ | Part B #9 只 print 不驗證 | A-2、A-3、B |
| 資料剖析（profiling）：先量值域、重複、孤兒 key | ○ | `notes/dataset/dictionary.md` | A-3 |

### 4. SQL 與查詢陷阱
| 觀念 | 狀態 | 本專案在哪碰到 | 題目 |
|---|---|---|---|
| LEFT JOIN 後用 WHERE 過濾右表，會變成 INNER | ○ | [point-in-time-join.md](point-in-time-join.md) 的 ASOF 空窗 | A |
| 型別：數字存成字串時的比較與排序 | ○ | AI 統計 amount 時把字串拿來比大小 | A-3 |
| NULL 語意：`!=` 遇 NULL、null-safe 比較 `<=>`、把缺值當 0 | ○ | Part B #6 `eqNullSafe`、#11 `to_twd` 回傳 0.0 | A-3、B |

### 5. 分散式計算與效能（Spark）
| 觀念 | 狀態 | 本專案在哪碰到 | 題目 |
|---|---|---|---|
| Spark ANSI 模式與隱式轉型 | ○ | Part B #12，pyspark 4.2 實跑 | B |
| collect 到 driver、Python UDF vs 內建函式 | ○ | Part B #9、#11 | B、D（三選一模組） |

### 6. 工程實務（Software engineering／DataOps／Orchestration）
| 觀念 | 狀態 | 本專案在哪碰到 | 題目 |
|---|---|---|---|
| uv：鎖定版本、可重現的 Python 環境 | ○ | `pyproject.toml`、`uv.lock`；pandas<3 與 PySpark 相容 | 交付要求：30 分鐘內重現（`candidate_package/README.md`） |
| linter 與 CI：ruff 抓得到什麼、抓不到什麼 | ○ | Part B 4.6 | B（素材自稱「已通過語法檢查」） |
| 明確 schema：CSV 不給型別的風險、BOM | ○ | Part B #12；`notes/dataset/dictionary.md` | A、B |
| 重跑與失敗處理：批次參數必填、步驟冪等、批次狀態 | ○ | Part B #10 `def main(batch_date: str = "day1"):` | A-2、B |

### 題目會考、還沒碰到
星型模型與維度鍵設計（A-1）、資料品質報告的寫法（A-3）、架構取捨與語意層（C）、以及三選一模組各自的主題：效能瓶頸分析（D）、LLM-as-judge 評分（E）、特徵洩漏（F）。做到時再補進上面的分類。

## 怎麼新增

在討論中問 AI「哪些觀念適合記錄？」。AI 會列出 3～5 個選項，我選了之後，AI 寫一份筆記到這裡，並把地圖中對應的 ○ 改成 📄（新觀念就加進合適的分類）。規則見 `.claude/skills/concept-note/SKILL.md`。
