# 模組 F：AI 第一輪審查初稿

〔待使用者確認〕本檔是 AI 讀 `candidate_package/module_F/churn_training_pipeline.py` 加上 3 個資料查詢後寫的初稿，使用者還沒判斷。AUC 沒有實測（專案 `.venv` 沒有 scikit-learn），所以影響大小都是從資料推算，不是模型輸出。

## 目錄
1. [背景：模組 F 是什麼](#1-背景模組-f-是什麼)
2. [主因：特徵直接含有答案](#2-主因特徵直接含有答案)
3. [次要問題](#3-次要問題)
4. [懷疑過但資料不支持](#4-懷疑過但資料不支持)
5. [待使用者判斷](#5-待使用者判斷)
- [附錄 A：查詢與輸出](#附錄-a查詢與輸出)

## 1. 背景：模組 F 是什麼

**1.1 題目要什麼**

DS 團隊做了一個「預測訂單會不會被取消」的模型，使用和 Part A 相同的資料集。題目只寫「離線 AUC 好得驚人，上線兩週後幾乎等於亂猜」；具體數字在程式檔頭的說明：離線測試 AUC 0.9 以上，上線只剩約 0.55，業務端已經停用。DS 確認模型演算法和超參數沒問題，懷疑是資料的問題，請資料工程師診斷**特徵管線**。要交三樣東西：

| 繳交物 | 內容 |
|---|---|
| 診斷報告 | 找出**所有**讓離線指標虛高的問題，逐一說明為什麼離線準、上線失效，以及怎麼驗證 |
| 修正設計 | 正確的特徵計算原則與資料切分方式，虛擬碼＋文字即可 |
| 防再犯機制 | 工程流程上加什麼，讓這類問題進不了生產 |

另外要用 3～5 句說明為什麼選 F、不選 D 和 E。執行程式是選配，純讀程式碼作答也可以。

**1.2 這條管線在做什麼**

`candidate_package/module_F/churn_training_pipeline.py`，約 100 行，三個函式依序執行：

1. `load_orders`：讀 `orders_base.csv`（5～6 月訂單），丟掉金額、下單時間、出發日解析失敗的列，標籤 `label` 是「`order_status == "cancelled"` 就是 1，否則 0」。檔頭說明提到 `members.csv`，但程式實際沒有讀它。
2. `build_features`：算 8 個特徵。
   - 4 個從「歷史」統計來的：會員的訂單數 `member_order_cnt`、會員的取消率 `member_cancel_rate`、會員對這個產品的取消率 `member_product_cancel_rate`、產品的取消率 `product_cancel_rate`。
   - 4 個訂單本身的欄位：金額 `amount`、人數 `quantity`、折扣 `coupon_discount`、下單到出發的天數 `days_to_departure`。
3. `train`：標準化後，隨機切 75% 訓練、25% 測試，訓練 logistic regression，印出訓練與測試的 AUC 和各特徵的係數。

**1.3 名詞**

- **AUC**：從資料隨機挑一張取消的單和一張沒取消的單，模型給取消那張較高分的機率。0.5 等於亂猜，1 是完全分得開。
- **離線／上線**：離線是用已經知道結果的歷史資料評估；上線是對剛成立、還不知道結果的訂單做預測。
- **資料洩漏（data leakage）**：訓練或評估時，特徵裡含有「預測當下不可能知道」的資訊，例如結果本身，或預測時間點之後才發生的事。離線看起來很準，上線拿不到那些資訊就失效。
- **target encoding**：把類別欄位（會員、產品）換成「這個類別的標籤平均值」，例如產品取消率。算的時候若含有要預測的那筆自己的標籤，或用到未來的資料，就會洩漏。

## 2. 主因：特徵直接含有答案

**2.1 `member_product_cancel_rate` 幾乎等於標籤**
- 程式：`build_features` 裡 `df.groupby(["member_id", "product_id"]).agg(member_product_cancel_rate=("label", "mean"))`，用全部資料、含這筆自己的標籤。
- 資料：97,952 組會員×產品裡，95,891 組只有 1 列，佔全部列的 95.9%。只有 1 列時，這個特徵就等於自己的標籤（附錄 A-1）。
- 離線為什麼準：96% 的列，特徵就是答案；這也解釋了 DS 看到的「重要性最高」。
- 上線為什麼失效：新訂單沒有標籤，而且這組會員×產品幾乎都是第一次出現，特徵是 NaN，被 `fillna(0)` 填成 0。

**2.2 `member_cancel_rate`、`product_cancel_rate`、`member_order_cnt`：用到未來資料**
- 三個特徵都用整段期間算，包含這筆訂單之後才發生的訂單。上線時只有過去的資料。
- `member_cancel_rate`、`product_cancel_rate` 另外還含自己的標籤：會員訂單數中位數 12，自己的標籤約佔會員取消率的 1/12（附錄 A-1）。
- `member_order_cnt` 不含標籤，但同樣違反「只能用下單之前的資料」：離線時數的是會員整段期間的訂單數，上線時只數得到過去的訂單，數值會偏小。它對 AUC 虛高的貢獻可能比兩個取消率小，要等 ablation 實測。（初稿原本把它放在次要問題、寫成「比較像分布不一致」，使用者判斷它算洩漏、應和 2.2 同類，移到這裡。）

**2.3 評估方式：先算特徵、再隨機切分**

2.1、2.2 是特徵本身的定義錯了；2.3 是評估方式錯了。就算特徵定義改對，評估方式不改，離線分數還是會高估。2.3 包含兩個獨立的問題：

- **2.3A 順序錯：先算特徵，後切分**。`build_features` 用全部 10 萬筆的 label 算取消率，`train` 裡的 `train_test_split` 才切出 25% 測試集，所以測試集的 label 已經混進訓練用的特徵。修法：先切分，取消率只用訓練集的 label 算。
- **2.3B 隨機切，不是按時間切**。`train_test_split(X, y, test_size=0.25, random_state=7)` 不看時間。就算 2.3A 修好，隨機切仍會讓「測試集裡 5/10 的訂單」用到「訓練集裡同一會員 6/20 訂單」的結果，等於用未來預測過去。上線永遠是用過去預測未來，所以應改成按時間切（例如 5/1～6/15 訓練、6/16～6/30 測試），特徵只用切分點之前的資料計算。

## 3. 次要問題

- **3.1 `StandardScaler` 在切分前 fit**：`scaler.fit_transform(X)` 在 `train_test_split` 之前，測試集特徵的平均與標準差混進了訓練。和 2.3A 原則相同（從資料學出來的東西只能從訓練集學），但漏的只是數值尺度、不含 label，所以影響小。修法：訓練集 `fit_transform`，測試集只 `transform`。
- **3.2 重複列**：同一 `order_id` 有 40 組重複（80 列），標籤都一致（附錄 A-1），可能一筆在訓練集、一筆在測試集；佔 0.04%，影響可忽略。

## 4. 懷疑過但資料不支持

- **4.1 標籤未成熟（label maturity）**：`order_status` 大部分是 06-30 前的狀態，另有 2,265 列的 `updated_at` 在 07-01～07-03（獨立盲審發現、主對話重跑確認，見 `blind-review-diff.md` D4），所以 base 檔不是乾淨的單一時間點快照。月底下的單可能還沒來得及取消。原則上是真問題，但依下單週分組，取消率在 0.137～0.146 之間，只有最後一週（只含 6/29、6/30）是 0.128（附錄 A-2）。和 Part A「狀態和時間沒有關聯」一致。使用者定案：不放進診斷報告，放進修正設計的標籤定義（取消只會發生在出發前，所以只用出發日已過、結果已確定的訂單訓練），見 process-log。
- **4.2 Part A 的資料品質問題**（金額 ×1000、負數金額、USD 未換匯、時區混用）：讓特徵變髒，但不會讓離線 AUC 虛高。

## 5. 待使用者判斷
- 「所有問題」找齊了沒？還沒有獨立盲審比對。
- 主因排序是推算的；要證明需要 ablation（一次修一個，看 AUC 掉多少），要先裝 scikit-learn。

## 附錄 A：查詢與輸出

用專案 `.venv/bin/python -I`，在 `candidate_package/dataset/` 執行。

**A-1 會員×產品組數、會員訂單數、重複列**
```python
import pandas as pd
df=pd.read_csv("orders_base.csv")
df["label"]=(df.order_status=="cancelled").astype(int)
print("rows",len(df),"orders",df.order_id.nunique(),"cancel_rate",round(df.label.mean(),3))
mp=df.groupby(["member_id","product_id"]).size()
print("member×product pairs",len(mp),"1-row pairs",(mp==1).sum(),"share of rows in 1-row pairs",round(mp[mp==1].sum()/len(df),3))
m=df.groupby("member_id").size()
print("members",len(m),"median orders/member",m.median(),"members with 1 order",(m==1).sum())
dup=df[df.order_id.duplicated(keep=False)]
print("dup order_id rows",len(dup),"groups with differing label",(dup.groupby("order_id").label.nunique()>1).sum())
```
```
rows 100040 orders 100000 cancel_rate 0.142
member×product pairs 97952 1-row pairs 95891 share of rows in 1-row pairs 0.959
members 8000 median orders/member 12.0 members with 1 order 0
dup order_id rows 80 groups with differing label 0
```

**A-2 依下單週（台北時間）的狀態比例**
```python
df["c"]=pd.to_datetime(df.order_created_at,format="mixed",utc=True).dt.tz_convert("Asia/Taipei")
df["wk"]=df.c.dt.to_period("W").astype(str)
print(pd.crosstab(df.wk,df.order_status,normalize="index").round(3))
```
```
wk                     cancelled  completed  created   paid
2026-04-27/2026-05-03      0.137      0.298    0.143  0.422
2026-05-04/2026-05-10      0.139      0.285    0.143  0.433
2026-05-11/2026-05-17      0.146      0.282    0.144  0.428
2026-05-18/2026-05-24      0.143      0.283    0.145  0.430
2026-05-25/2026-05-31      0.142      0.287    0.143  0.428
2026-06-01/2026-06-07      0.141      0.292    0.142  0.425
2026-06-08/2026-06-14      0.146      0.285    0.140  0.429
2026-06-15/2026-06-21      0.145      0.285    0.141  0.429
2026-06-22/2026-06-28      0.145      0.280    0.144  0.431
2026-06-29/2026-07-05      0.128      0.300    0.144  0.427
```
