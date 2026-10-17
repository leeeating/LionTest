# ETL、ELT 與 medallion 三層
ETL 是先清理再載入，ELT 是先原樣載入、再在目標系統裡轉換；medallion 把 ELT 的過程分成 bronze（原樣）、silver（清理過）、gold（給報表）三層。

## 白話版
**脈絡**：營運 DB 像餐廳的點單本，一直被寫入，不適合拿來算報表；資料倉像整理好的營業報表；ETL／ELT 是打烊後整理帳的人。實務上常是「營運 SQL DB → 每天匯出成檔案（CSV 常是這樣來的）→ 管線讀檔整理 → 倉」。

- **ETL（Extract, Transform, Load）**：整理的人把點單本抄出來，**在自己桌上**清理好，只把乾淨的結果放進報表。原始點單沒留在倉裡。
- **ELT（Extract, Load, Transform）**：先把點單**原樣影印一份放進倉裡**，再用倉本身的運算力整理。微軟的定義：兩者「solely」差在轉換在哪裡發生，ELT 是在目標資料儲存裡轉換。

用 Python 想像：

```python
# ETL：只留結果
warehouse["orders"] = clean(extract())
# ELT：原料也留著，規則改了可以重算
warehouse["bronze"] = extract()
warehouse["silver"] = clean_v2(warehouse["bronze"])   # 不用再回營運 DB 抓
```

**medallion 三層各放什麼**
| 層 | 放什麼 | 本專案對應 |
|---|---|---|
| bronze | 原樣資料，欄位多存成字串，加上來源檔名等 metadata；只 append | 四個訂單 CSV 原樣、加 `src`／`batch_date` |
| silver | 轉型、統一代碼、去重、處理遲到／亂序資料；不合格的列隔離；仍是一列一筆明細 | 清理後的訂單、隔離表 |
| gold | 依業務建模與彙總：星型模型、報表用的彙總表 | `fact_order`、`dim_member` 等 |

**為什麼 ELT 好用**：(1) 規則改了（例如發現 `NTD` 要對應成 `TWD`），從 bronze 重算 silver 就好，不必請營運 DB 重新匯出；(2) 被隔離的列在 silver 裡記著原值、原因和來源檔，回頭查得到「這筆是哪天哪個檔來的」。

**ETL 不是「把所有 join 預先做完」**：星型模型預先做的是清理、**難的 join**（例如對到下單當時的會員版本，存成代理鍵，見 [time-varying-attributes.md](../1-modeling/time-varying-attributes.md)）、算好的數字（例如換算成 TWD 的金額）。查詢時仍要做一層 fact→dim 的簡單等值 join（見 [star-schema.md](../1-modeling/star-schema.md)）。全部 join 成一張寬表的叫 OBT（One Big Table），是另一種設計選擇。

## 什麼時候用、什麼時候不要用
- **ELT＋medallion**：目標是 lakehouse 或可彈性擴充的 warehouse、需要保留原始資料以便重算與稽核。這是 Fabric／Databricks 的預設思路。
- **ETL**：目標系統運算力有限、或法規要求敏感資料不能原樣落地（要先遮蔽再載入）。
- **不要硬套三層**：Databricks 文件說 medallion 是建議做法，不是規定；資料很少、只有一個用途時，層數可以少。

## 最小可跑範例
DuckDB 做極小的 bronze → silver（含隔離）→ gold。在 repo 根目錄執行 `uv run python -I /tmp/medallion.py`：

```python
import duckdb

con = duckdb.connect()  # in-memory，重跑不殘留

# bronze：營運 DB 匯出的檔案原樣落地，全部是字串，外加來源與載入批次
con.sql("""
CREATE TABLE bronze_orders AS
SELECT *, 'export_2026-06-10.csv' AS _src_file FROM (VALUES
  ('O1', 'TWD', '3000',  '2026-06-10'),
  ('O2', 'USD', '120.5', '2026/06/10'),   -- 日期格式不一致
  ('O2', 'USD', '120.5', '2026/06/10'),   -- 重複匯出
  ('O3', 'NTD', '2000',  '2026-06-10'),   -- NTD 是 TWD 的別名
  ('O4', 'TWD', '-500',  '2026-06-10'),   -- 負數金額
  ('O5', 'JPY', 'abc',   '2026-06-10')    -- 金額不是數字
) t(order_id, currency, amount, order_date)
""")

# silver：轉型、統一代碼、去重；不合格的列不丟掉，放進隔離表並記原因
con.sql("""
CREATE TABLE typed AS
SELECT DISTINCT
  order_id,
  CASE currency WHEN 'NTD' THEN 'TWD' ELSE currency END AS currency,
  TRY_CAST(amount AS DECIMAL(14,2)) AS amount,
  COALESCE(TRY_STRPTIME(order_date, '%Y-%m-%d'), TRY_STRPTIME(order_date, '%Y/%m/%d'))::DATE AS order_date,
  amount AS amount_raw, _src_file
FROM bronze_orders
""")
con.sql("""CREATE TABLE quarantine AS
  SELECT *, CASE WHEN amount IS NULL THEN 'amount_not_number' ELSE 'amount_not_positive' END AS reason
  FROM typed WHERE amount IS NULL OR amount <= 0""")
con.sql("CREATE TABLE silver_orders AS SELECT * EXCLUDE (amount_raw) FROM typed WHERE amount > 0")

# gold：給報表用的彙總
con.sql("""CREATE TABLE gold_daily AS
  SELECT order_date, currency, count(*) AS orders, sum(amount) AS amount
  FROM silver_orders GROUP BY ALL ORDER BY ALL""")

for t in ["bronze_orders", "silver_orders", "quarantine", "gold_daily"]:
    print(t, con.sql(f"SELECT count(*) FROM {t}").fetchone()[0])
print(con.sql("SELECT order_id, amount_raw, reason, _src_file FROM quarantine ORDER BY order_id").fetchall())
print(con.sql("SELECT * FROM gold_daily").fetchall())
```

實際輸出（duckdb 1.5.6），exit code 0：

```
bronze_orders 6
silver_orders 3
quarantine 2
gold_daily 2
[('O4', '-500', 'amount_not_positive', 'export_2026-06-10.csv'), ('O5', 'abc', 'amount_not_number', 'export_2026-06-10.csv')]
[(datetime.date(2026, 6, 10), 'TWD', 2, Decimal('5000.00')), (datetime.date(2026, 6, 10), 'USD', 1, Decimal('120.50'))]
```

- 6 → 3＋2：1 筆是重複被去掉，2 筆被隔離，隔離表留著原值與來源檔。
- gold 的 TWD 是 2 筆 5,000：`NTD` 的 2,000 已併進 TWD。若 bronze 時就把 `NTD` 列丟了，之後發現這條規則也救不回來。
- 示範用 `DISTINCT` 去重是因為重複列完全相同；真實資料同一 key 的多列內容可能不同，要依規則取一筆，見 [latest-row-per-group.md](../2-incremental-etl/latest-row-per-group.md)。

## 常見的坑
- **在 bronze 就轉型或過濾**：轉型失敗的列消失或變 NULL，之後查不到原值。本專案的剖析一律全字串讀入、用 `try_cast` 轉型，就是為了看見轉不過的列。
- **隔離＝刪除**：隔離表要記原因與來源，否則 A-3 的品質報告數不出筆數。
- **以為 schema 約束能取代 silver 的清理**：約束只能擋，不能修（例如多乘 1,000 的金額仍大於 0），見 ADR-02。

## 本專案出處
- `decisions/ADR-02-source-abstraction-schema-contract.md`：營運 SQL DB → CSV 匯出的脈絡、「約束只能擋不能修」、先隔離再寫入有約束的表；process-log 事件「管線以抽象來源設計，品質規則寫成 schema 合約」。
- `part_a/source-schema-inference.md`：view `orders_all`（四檔 union，加 `src`、`batch_date`）就是 bronze 的形狀；推測的上游 `CREATE TABLE orders` 說明 CSV 來自營運 DB。

## 官方文件
- ETL vs ELT、何時選哪個（Azure Architecture Center）：https://learn.microsoft.com/en-us/azure/architecture/data-guide/relational-data/etl
- medallion 三層、bronze 存字串與來源 metadata、可重算與稽核、silver 隔離不合格資料（Azure Databricks）：https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion
- 未證實：OBT 的定義是一般用語，未讀官方文件；Fabric 自己的 medallion 頁面未讀。
