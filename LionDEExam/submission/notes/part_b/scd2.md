# 這份程式的 SCD2 錯在哪

回到入口：[README.md](README.md)。SCD2 概念（三件事、初始載入、第一版 `valid_from`）看 [../../learning/1-modeling/scd.md](../../learning/1-modeling/scd.md)，本檔只講這一題。

## 這份程式的問題

`update_dim_member` 自稱 SCD2，但三件事都沒做對：
- 沒有 `valid_to`、`is_current`，舊版沒有被關閉。
- 寫入時用 overwrite 加 `"replaceWhere", "member_id IS NOT NULL"`，等於整張表覆寫，只剩有變更的會員，連 SCD1 都不如。
- 用 `dim.alias("d").join(latest_snap.alias("s"), "member_id")`（inner join）偵測變更，dim 裡還沒有的新會員永遠進不來；`!=` 遇到 null 會漏掉變更。

資料佐證：`members.csv` 有 989 人有多筆快照，其中跨快照日等級變過的 406 人（另有 28 人是同日兩列等級矛盾，合計 434 人有兩種以上等級）、376 人縣市變過。這些就是 SCD2 該保存的歷史。

## 建議修法（針對 `update_dim_member`）

用 Delta MERGE 分兩段：先把有變更的會員的目前版本關閉（設定 `valid_to`、`is_current=false`），再插入新版本和新會員。比較時用 null-safe 的 `eqNullSafe`。完整寫法見報告 4.4。

**這份程式特有的陷阱：只拿最新快照。** 上面的 MERGE 每次只拿每位會員最新的 `extract_date`。dim 從空表開始時直接拿現在的 `members.csv` 跑，04-30、05-31 的舊版進不來，上面那 406 人的舊等級就丟了。再搭配半開區間 join，早於唯一一版 `valid_from` 的訂單對不到任何版本，等級變成 null：day1 去重後 4,597 張中有 49 張是這樣。初始載入的做法見 learning（依快照日由舊到新回填）。

**第一版 `valid_from` 取第一筆快照日的後果（本題資料）**：目前資料不含被隔離的 28 位同分會員時，day1 有 17 張對不到，要靠 #6 的隔離告警處理，其餘 0 張。其他選項（`register_date`、很早的固定日期）的取捨見 learning。

細節與數字見[附錄「SCD2 初始載入」](../../part_b/appendix.md#scd2-初始載入)（報告 #6 (c) 的補充）。
