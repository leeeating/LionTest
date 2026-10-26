# 模組 F：初稿與獨立盲審的差異

〔待使用者確認〕比對兩份審查：`ai-review-draft.md`（初稿，使用者已逐條判斷）和 `blind-review.md`（fresh-context opus agent，只看題目、程式碼、資料，沒看過初稿與討論）。盲審沒有 scikit-learn，用 numpy 自寫邏輯迴歸與 AUC，原管線重現出 Test AUC 0.9999；正式數字以 T4 用 scikit-learn 實測為準。

## 目錄
0. [結論的適用範圍](#0-結論的適用範圍)
1. [兩份一致的結論](#1-兩份一致的結論)
2. [盲審有、初稿沒有](#2-盲審有初稿沒有)
3. [盲審的錯誤](#3-盲審的錯誤)
4. [盲審和初稿的定位不同](#4-盲審和初稿的定位不同)
5. [待使用者判斷](#5-待使用者判斷)
- [附錄 A：主對話抽查的查詢與輸出](#附錄-a主對話抽查的查詢與輸出)

## 0. 結論的適用範圍
所有數字都來自題目給的合成資料（`orders_base.csv`）。分兩類看：
- **機制結論，換資料也成立**：特徵含自己的標籤、用到未來資料、先算特徵後切分、隨機切而非按時間切。這些從程式碼就能判斷，資料只是佐證。
- **量級結論，只對這份資料成立**：各特徵的 AUC、消融鏈的數字、「`member_order_cnt` 沒造成虛高」「StandardScaler 影響可忽略」「隨機切或時間切都約 0.5」。換成正式資料，大小可能不同。

## 1. 兩份一致的結論
- **主因相同**：三個取消率特徵把自己的標籤算進去，`member_product_cancel_rate` 最嚴重。盲審的數字：97.9% 的會員×產品組合只有 1 筆（初稿算的是 95,891 / 97,952 組，同一件事）；98.99% 的列上特徵等於 label（多筆組合裡標籤全相同的也算進去）。
- **2.3A／2.3B、3.1、3.2 重複列、4.1 標籤未成熟**：兩份都有找到。
- **盲審量化了初稿只推算的部分**（自寫模型，待 T4 確認）：
  - 只留一個特徵時的 AUC：`member_product_cancel_rate` 0.9999、`member_cancel_rate` 0.7263、`product_cancel_rate` 0.548。
  - 消融鏈 0.9999 → 0.7275 → 0.5082 → 0.4969。
  - 只用下單當下拿得到的特徵，在這份合成資料上 AUC 約 0.50。這只說明**這份資料**的合法特徵幾乎沒有訊號（各維度取消率都在 0.137～0.155），不能推論成「正式環境的真實水準就是 0.5」；正式資料的合法特徵可能有訊號。

## 2. 盲審有、初稿沒有
| # | 發現 | 盲審評的嚴重度 | 主對話抽查 |
|---|---|---|---|
| D1 | 上線時用歷史資料，只有 2.03% 的新訂單查得到會員×產品的取消率，其餘被 `fillna(0)` 補成 0 | 主因的一部分 | **量級相近**：以 06-16 切分，之後的 24,712 筆新訂單只有 3.05% 在之前出現過同一組會員×產品；增量檔 12,122 筆新訂單（排除和 base 同編號的撞號）只有 4.29% 在 base 出現過。盲審的 2.03% 是不同算法。屬量級結論，正式資料的回購率可能更高 |
| D2 | 120 個不在 `products.csv` 的 product_id，各只有 1 筆，這些列上 `product_cancel_rate` 就是 label | 次要 | **確認**：120 個編號、120 列、每個編號最多 1 列 |
| D3 | `days_to_departure` 時區錯：沒標時區的下單時間被當 UTC、出發日被當 UTC 午夜，32,335 列差 1 天 | 可忽略 | 未抽查 |
| D4 | base 檔有 2,265 列 `updated_at` 在 07-01 之後，不是乾淨的 06-30 快照 | 可忽略 | **確認 2,265 列，最晚 07-03 17:20（台北）** |
| D5 | `members.csv` 是多版本快照；程式沒讀它，但如果以後直接 join，列數會膨脹，取最新版本也會用到未來資訊 | 潛在風險 | 未抽查 |
| D6 | `member_order_cnt` 只留它時 AUC 0.498，沒有造成虛高 | 次要 | 未抽查 |

D4 影響初稿 4.1 的前提：初稿寫「`order_status` 是 06-30 當時的狀態」，實際上有一部分列是 07-01～07-03 的狀態。

## 3. 盲審的錯誤
盲審說「只讀 base 檔、忽略增量檔，三天內有 768 筆從非取消變成取消、118 筆從取消變成 completed，約 0.9% 的標籤是錯的」。**這是錯的**：Part A 已經查證，增量檔裡和 base 同編號的資料全部是撞號（另一張訂單用了同一個編號），不是狀態更新。主對話抽查：增量檔和 base 同編號的有 1,809 列，會員和產品都相同的是 **0 列**。盲審照題目的官方說法，把撞號當成了狀態更新，正好掉進題目埋的陷阱。

## 4. 盲審和初稿的定位不同
- **3.1 StandardScaler**：初稿寫「影響小」；盲審實測修正後 AUC 不變，評為可忽略。兩份一致，盲審有數字。
- **2.3B 隨機切分**：盲審評為次要，理由是虛高主要來自 target encoding。初稿把它列為主因，使用者判斷同意。差別在「造成這次虛高」和「評估方式錯了」是兩件事：在這份合成資料上，修好特徵後，隨機切或時間切的 AUC 都約 0.5，但這是因為合法特徵本來就沒有訊號；正式資料若有時間趨勢，隨機切仍會高估。
- **`member_order_cnt`**：使用者判斷它算洩漏（違反只用下單之前的資料）；盲審量到它在本資料沒有造成虛高。兩者不衝突：原則上是洩漏，實際影響小。

## 5. 待使用者判斷
- ~~D1～D6 哪些要進診斷報告~~：使用者定案只收 D1、D2，理由見 process-log。
- ~~2.3B 寫成主因或次要~~：使用者定案維持主因，理由見 process-log。
- ~~D4 修正 4.1 的「06-30 快照」說法~~：已改（事實修正）。

## 附錄 A：主對話抽查的查詢與輸出

用專案 `.venv/bin/python -I`，在 `candidate_package/dataset/` 執行（D1、D2 抽查；D4 與撞號抽查見 process-log 對應事件的 session 紀錄）。

```python
import pandas as pd
b=pd.read_csv("orders_base.csv"); p=pd.read_csv("products.csv")
orph=b[~b.product_id.isin(p.product_id)]
print("orphan product_ids:",orph.product_id.nunique(),"rows:",len(orph),"max rows per id:",orph.product_id.value_counts().max())
b["c"]=pd.to_datetime(b.order_created_at,format="mixed",utc=True)
cut=pd.Timestamp("2026-06-16",tz="Asia/Taipei")
hist=b[b.c<cut]; new=b[b.c>=cut]
hk=set(zip(hist.member_id,hist.product_id))
print("cut 06-16: new orders",len(new),"pair seen in history:",round(sum(k in hk for k in zip(new.member_id,new.product_id))/len(new)*100,2),"%")
bk=set(zip(b.member_id,b.product_id))
inc=pd.concat([pd.read_csv(f"orders_incremental_day{i}.csv") for i in (1,2,3)])
inc=inc[~inc.order_id.isin(b.order_id)]
print("incremental new orders",len(inc),"pair seen in base:",round(sum(k in bk for k in zip(inc.member_id,inc.product_id))/len(inc)*100,2),"%")
```
```
orphan product_ids: 120 rows: 120 max rows per id: 1
cut 06-16: new orders 24712 pair seen in history: 3.05 %
incremental new orders 12122 pair seen in base: 4.29 %
```
