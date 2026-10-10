# 觀念筆記

這裡是我在做這份 take-home 的討論中選出、**可以帶到其他專案**的 SWE 觀念筆記，例如套件／工具的用法、SQL 寫法與模式。一個觀念一份，約一頁。這裡不是繳交物的結論。

**放這裡還是 `notes/`**：換一個專案照樣能用的技能放這裡；只跟這份資料、這支程式有關的放 `../notes/`。

## 索引

| 觀念 | 檔案 | 類別 | 本專案出處 |
|---|---|---|---|
| SCD（Slowly Changing Dimension）名詞說明：Type 0～4 與 6、key、有效期間 | [scd.md](scd.md) | 資料建模 | Part B #2、#6：`update_dim_member`；`members.csv` 多次快照 |
| SQL：取每組最新一筆（`ROW_NUMBER`／`QUALIFY`） | [latest-row-per-group.md](latest-row-per-group.md) | SQL | Part B #5：`clean_orders` 中的 `dropDuplicates(["order_id"])` |
| SQL：MERGE 做冪等寫入（upsert） | [merge-idempotent-write.md](merge-idempotent-write.md) | SQL、Delta Lake | Part B #3：`write_fact` 中的 `mode("append")` |
| SQL：point-in-time join（半開區間、`ASOF JOIN`） | [point-in-time-join.md](point-in-time-join.md) | SQL、資料建模 | Part B #4、#6：`build_fact` 中的 `converted.join(members, "member_id", "left")` |

## 怎麼新增

在討論中問 AI「哪些觀念適合記錄？」。AI 會列出 3～5 個選項，我選了之後，AI 寫一份筆記到這裡並更新上表。規則見 `.claude/skills/concept-note/SKILL.md`。
