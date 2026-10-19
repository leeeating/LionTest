# 表格式：Delta 與 Iceberg 在 Parquet 上加了什麼
Parquet 只是一堆資料檔。Delta、Iceberg 這類「表格式」（table format）在旁邊多存一份 metadata 紀錄，讓這堆檔案有了交易、MERGE、time travel 這些資料庫的能力。

## 白話版
Parquet 像一疊散裝的紙。表格式在旁邊加了一本「異動紀錄本」：每次寫入都記下「這次加了哪幾張紙、作廢哪幾張紙」。讀表時先翻紀錄本，就知道現在有效的是哪些紙；翻回舊的那一頁，就能看到以前的樣子。

## 兩者比較
以下依 AI 既有知識整理，標「未證實」的部分沒有查官方文件確認。

| 功能 | Delta | Iceberg | 本專案用在哪 |
|---|---|---|---|
| 交易（ACID） | ✅ | ✅ | 中途停止時不留半套資料 |
| MERGE | ✅ | ✅（Spark SQL `MERGE INTO`） | fact_order 依 order_id upsert |
| time travel | ✅ 版本號或時間點 | ✅ snapshot id 或時間點 | ADR-05 重跑比對基準 |
| commit 上貼標籤 | ✅ `userMetadata` | ✅ snapshot summary 的自訂屬性（未證實） | 稽核每次寫入是哪一批 |
| CHECK 約束 | ✅ | ❌ 只有必填欄位，沒有 CHECK（未證實） | 關鍵欄位的最後防線 |

**Iceberg 的優勢**
1. **引擎與廠商中立**：最初由 Netflix 為「多種引擎共用同一份資料」而設計；Spark、Trino、Flink、Snowflake、AWS Athena 都直接支援。
2. **隱藏分區**：建表時宣告「依 `days(order_created_at)` 分區」，查詢直接用原欄位過濾，就會跳過不需要的檔案。Delta 傳統做法要另建一欄當分區，查詢時也要記得用那一欄。
3. **分區方式可以改**：資料變大後從按月改成按天，舊資料不必重寫。Delta 傳統上要整表重寫，後來推出 liquid clustering 處理這個問題（未證實細節）。

**Delta 的優勢**：和 Spark、Databricks、Fabric 整合最深，Fabric 預設就用 Delta。

## 什麼時候選哪個
| 情境 | 選 |
|---|---|
| 主要在 Databricks 或 Fabric 上，只用 Spark | Delta |
| 多種引擎、多雲、不想被單一廠商綁住 | Iceberg |

不論選哪個，**業務規則都要自己寫**：狀態機、撞號判斷、隔離表、SCD2、對帳，任何表格式都不會內建。

## 最小可跑範例
看 Delta 的「異動紀錄本」長什麼樣。用的是 learning `2-incremental-etl/delta-time-travel.md` 範例建出來的表，不需要啟動 Spark（2026-10-19 實跑）：

```bash
ls /tmp/tt_demo/orders/_delta_log/
python3 -c "
import json
for l in open('/tmp/tt_demo/orders/_delta_log/00000000000000000002.json'):
    d=json.loads(l); k=list(d)[0]
    if k=='commitInfo': print(k, {x:d[k].get(x) for x in ('operation','userMetadata')})
    elif k in('add','remove'): print(k, d[k]['path'][:40])
    else: print(k)
"
```

實際輸出：
```
00000000000000000000.crc
00000000000000000000.json
00000000000000000001.crc
00000000000000000001.json
00000000000000000002.crc
00000000000000000002.json
00000000000000000003.checkpoint.parquet
00000000000000000003.json
_last_checkpoint
_staged_commits
commitInfo {'operation': 'MERGE', 'userMetadata': 'batch:day1'}
add part-00000-17f17e9a-880d-40df-9362-a8fbe
remove part-00000-f287a889-0e5a-4963-8148-5ed8a
```

每個版本一個 JSON 檔。版本 2 這一次的 MERGE 記了三件事：操作與標籤（`commitInfo`）、新增哪個資料檔（`add`）、作廢哪個資料檔（`remove`）。被 `remove` 的檔案還留在磁碟上，所以 time travel 讀得回來；`VACUUM` 才會真的刪掉它。

Iceberg 的範例未執行：本專案沒有安裝 Iceberg。

## 常見的坑
- **以為表格式會幫你做資料品質**：它只保證「寫入是完整的一次交易」，不管內容對不對。內容要靠合約、隔離表，以及 Delta 的 CHECK。
- **換格式時忘了功能差異**：Delta 換成 Iceberg 時，CHECK 這道防線要改回在程式裡做。
- **舊版本會被清掉**：`remove` 的檔案在 `VACUUM` 之後就消失，time travel 也就讀不到了（見 [[delta-time-travel]]）。

## 本專案出處
- 使用者問：「我可以理解delta是DE常用的格式 所以很常用delta去實現功能是嗎」「iceberg也是同樣公能嗎」「哪這樣iceberg的優勢在哪」
- ADR-01 選 Delta：正式環境在 Fabric。
- ADR-05 time travel、process-log「Delta CHECK 約束：只加在關鍵欄位，當最後一道防線」。

## 官方文件
未證實：這次沒有打開 Delta Lake 與 Apache Iceberg 的官方文件核對。之後要引用時，查 Iceberg 文件的 "Partitioning"（hidden partitioning、partition evolution）與 "Spark Writes"（MERGE INTO），以及 Delta Lake 文件的 "Constraints"。

## 相關
- [[delta-time-travel]]
- [[data-lake-vs-warehouse]]
- [[microsoft-fabric]]
