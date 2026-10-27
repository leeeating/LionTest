# 模組 F 盲審：訂單取消預測特徵管線診斷

〔獨立盲審，未看過其他審查〕

審查對象：`candidate_package/module_F/churn_training_pipeline.py`，資料 `candidate_package/dataset/`。
執行環境：專案 `.venv` 的 Python（pandas、numpy），沒有 scikit-learn，所以邏輯迴歸與 AUC 用 numpy 自寫等價版（見附錄 A）。

## 目錄

- [0. 結論摘要](#0-結論摘要)
- [1. 主因：目標編碼把自己的標籤算進特徵](#1-主因目標編碼把自己的標籤算進特徵)
  - [1.1 member_product_cancel_rate 幾乎等於標籤本身](#11-member_product_cancel_rate-幾乎等於標籤本身)
  - [1.2 member_cancel_rate 與 product_cancel_rate 也含自己的標籤](#12-member_cancel_rate-與-product_cancel_rate-也含自己的標籤)
  - [1.3 編碼在切分前用全資料計算（test 標籤流進 train 特徵）](#13-編碼在切分前用全資料計算test-標籤流進-train-特徵)
  - [1.4 上線時這些特徵大多缺值，補 0 後分布完全不同](#14-上線時這些特徵大多缺值補-0-後分布完全不同)
- [2. 標籤本身的問題](#2-標籤本身的問題)
  - [2.1 標籤是「快照當下的狀態」，不是「最終是否取消」](#21-標籤是快照當下的狀態不是最終是否取消)
  - [2.2 只讀 orders_base，忽略增量檔的狀態更新](#22-只讀-orders_base忽略增量檔的狀態更新)
  - [2.3 base 檔裡混入截止日之後的更新](#23-base-檔裡混入截止日之後的更新)
- [3. 切分與前處理](#3-切分與前處理)
  - [3.1 隨機切分而非時間切分](#31-隨機切分而非時間切分)
  - [3.2 StandardScaler 在切分前 fit](#32-standardscaler-在切分前-fit)
  - [3.3 member_order_cnt 用到未來訂單](#33-member_order_cnt-用到未來訂單)
- [4. 資料品質問題](#4-資料品質問題)
  - [4.1 重複的 order_id](#41-重複的-order_id)
  - [4.2 order_created_at 三種格式、時區處理不一致](#42-order_created_at-三種格式時區處理不一致)
  - [4.3 amount 混幣別、有負數與極端值](#43-amount-混幣別有負數與極端值)
  - [4.4 不存在於產品主檔的 product_id](#44-不存在於產品主檔的-product_id)
  - [4.5 members.csv 是多版本快照（管線目前沒用，但文件聲稱有用）](#45-memberscsv-是多版本快照管線目前沒用但文件聲稱有用)
- [5. 根本觀察：合法特徵幾乎沒有訊號](#5-根本觀察合法特徵幾乎沒有訊號)
- [6. 問題總表](#6-問題總表)
- [附錄 A. 共用程式碼](#附錄-a-共用程式碼)

## 0. 結論摘要

- **離線 AUC 虛高的幾乎全部來源是 `member_product_cancel_rate`**：97.9% 的（會員, 產品）組合只有 1 筆訂單，這個特徵在 98.99% 的列上**就等於標籤**，單一特徵 AUC 0.9999。拿掉它，AUC 掉到 0.7275；再拿掉另外兩個目標編碼，剩 0.5082。
- **改成時間點正確的特徵＋時間切分後，test AUC 是 0.4969**。也就是說，這份資料裡用合法特徵根本預測不了取消；上線 0.55 不是模型壞掉，是離線 0.9 從頭到尾都是洩漏造成的假象。
- 次要問題：標籤是快照狀態而非最終結果（三天內就有 768 筆從非取消翻成取消）、只讀 base 檔、隨機切分、`member_order_cnt` 用到未來、重複訂單、時區與幣別不一致。這些在本資料上對 AUC 的影響小，但在真實資料上都會造成離線／上線不一致。

## 1. 主因：目標編碼把自己的標籤算進特徵

`build_features` 有三個 target encoding，都是 `df.groupby(...).agg(..._cancel_rate=("label", "mean"))` 再 merge 回同一個 `df`。每一列的特徵都包含**它自己的 label**，而且是用全資料（含 test）算的。

**查詢 q5**

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
df=load_orders(); f,cols=build_features(df)
print("== 單一特徵 AUC（全資料，管線原樣）")
for c in cols: print(f"  {c:28s} {auc(f.label,f[c].fillna(0)):.4f}")
mo=f.groupby("member_id").size()
print("members",len(mo),"orders/member describe"); print(mo.describe().round(2).to_string())
pc=f.groupby(["member_id","product_id"]).size()
print("member-product pairs",len(pc),"share of pairs with 1 order",round((pc==1).mean(),4))
print("rows whose (member,product) pair has 1 order",round(f.groupby(["member_id","product_id"]).order_id.transform("size").eq(1).mean(),4))
print("member_product_cancel_rate == label share",round((f.member_product_cancel_rate==f.label).mean(),4))
print("member_product_cancel_rate in (0,1) share",round(((f.member_product_cancel_rate>0)&(f.member_product_cancel_rate<1)).mean(),4))
print("orders/product describe"); print(f.groupby("product_id").size().describe().round(1).to_string())
```

輸出：

```text
== 單一特徵 AUC（全資料，管線原樣）
  member_order_cnt             0.4983
  member_cancel_rate           0.7263
  member_product_cancel_rate   0.9999
  product_cancel_rate          0.5480
  amount                       0.5015
  quantity                     0.4992
  coupon_discount              0.5047
  days_to_departure            0.4981
members 8000 orders/member describe
count    8000.00
mean       12.50
std         3.53
min         2.00
25%        10.00
50%        12.00
75%        15.00
max        27.00
member-product pairs 97952 share of pairs with 1 order 0.979
rows whose (member,product) pair has 1 order 0.9585
member_product_cancel_rate == label share 0.9899
member_product_cancel_rate in (0,1) share 0.0101
orders/product describe
count    420.0
mean     238.2
std      150.9
min        1.0
25%        1.0
50%      324.0
75%      341.0
max      383.0
```

### 1.1 member_product_cancel_rate 幾乎等於標籤本身

- **機制**：程式碼片段 `mp_stats = df.groupby(["member_id", "product_id"]).agg(member_product_cancel_rate=("label", "mean"))`。查詢顯示 97.9% 的組合只有 1 筆訂單（覆蓋 95.85% 的列），這時「組合的平均取消率」＝「這筆自己的 label」。98.99% 的列上特徵值完全等於標籤，只有 1.01% 落在 0 和 1 之間。模型係數 +6.50，遠大於其他特徵（< 0.1），等於模型學會「抄答案」。DS 說「這個特徵重要性最高」正是洩漏的症狀。
- **上線為什麼失效**：預測時這筆訂單還沒結果，自己的 label 不存在。即使用歷史資料算，上線的新訂單絕大多數是會員第一次買這個產品，查不到歷史（見 1.4，覆蓋率只有 2%）。
- **嚴重度**：主因。
- **驗證**：單一特徵 AUC（q5）、重現管線與消融（q6）、留一法與時間切分（q7）。

**查詢 q6**

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
df=load_orders(); f,cols=build_features(df)
X=f[cols].fillna(0).values.astype(float); y=f.label.values
mu,sd=X.mean(0),X.std(0); Xs=(X-mu)/sd   # 管線：先對全資料 fit scaler
tr,te=split(len(f))
w=fit_logreg(Xs[tr],y[tr])
print("== 重現原管線（numpy 版 LogisticRegression，隨機切 25%）")
print(f"Train AUC={auc(y[tr],predict(w,Xs[tr])):.4f}  Test AUC={auc(y[te],predict(w,Xs[te])):.4f}")
for c,v in sorted(zip(cols,w[1:]),key=lambda t:-abs(t[1])): print(f"  {c:28s} {v:+.4f}")
print("== 拿掉 member_product_cancel_rate")
k=[i for i,c in enumerate(cols) if c!="member_product_cancel_rate"]
w2=fit_logreg(Xs[tr][:,k],y[tr]); print(f"Test AUC={auc(y[te],predict(w2,Xs[te][:,k])):.4f}")
print("== 只用不含標籤的特徵（amount, quantity, coupon, days_to_departure, member_order_cnt）")
k=[cols.index(c) for c in ["amount","quantity","coupon_discount","days_to_departure","member_order_cnt"]]
w3=fit_logreg(Xs[tr][:,k],y[tr]); print(f"Test AUC={auc(y[te],predict(w3,Xs[te][:,k])):.4f}")
print("== scaler 只 fit train（其他照舊）")
mu2,sd2=X[tr].mean(0),X[tr].std(0); w4=fit_logreg((X[tr]-mu2)/sd2,y[tr]); print(f"Test AUC={auc(y[te],predict(w4,(X[te]-mu2)/sd2)):.4f}")
```

輸出：

```text
== 重現原管線（numpy 版 LogisticRegression，隨機切 25%）
Train AUC=0.9999  Test AUC=0.9999
  member_product_cancel_rate   +6.4986
  days_to_departure            +0.0818
  member_order_cnt             +0.0771
  quantity                     +0.0359
  product_cancel_rate          +0.0165
  amount                       +0.0130
  member_cancel_rate           -0.0098
  coupon_discount              -0.0055
== 拿掉 member_product_cancel_rate
Test AUC=0.7275
== 只用不含標籤的特徵（amount, quantity, coupon, days_to_departure, member_order_cnt）
Test AUC=0.5082
== scaler 只 fit train（其他照舊）
Test AUC=0.9999
```

留一法（從編碼裡扣掉自己那筆）與時間切分（只用 5 月訂單的統計去編 6 月訂單）後，三個編碼的 AUC 全部回到 0.49～0.50：

**查詢 q7**

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
df=load_orders().drop_duplicates("order_id")
df=df.sort_values("created_ts").reset_index(drop=True)
y=df.label.values
print("== 留一法（排除自己這筆）目標編碼的單一特徵 AUC")
for keys,name in [(["member_id"],"member"),(["member_id","product_id"],"member×product"),(["product_id"],"product")]:
    g=df.groupby(keys).label; s=g.transform("sum"); n=g.transform("size")
    loo=((s-df.label)/(n-1)).where(n>1)   # 沒有其他訂單 → NaN
    print(f"  {name:16s} LOO AUC(有值者)={auc(y[loo.notna()],loo[loo.notna()]):.4f}  有值比例={loo.notna().mean():.4f}")
print("== 時間點正確（只用該訂單建立前的訂單）的會員取消率")
g=df.groupby("member_id").label
prior_cnt=g.cumcount(); prior_sum=g.cumsum()-df.label
pit=(prior_sum/prior_cnt).where(prior_cnt>0)
print(f"  member point-in-time AUC={auc(y[pit.notna()],pit[pit.notna()]):.4f} 有值比例={pit.notna().mean():.4f}")
print("== 時間切分：train=5 月建立、test=6 月建立；編碼只用 train")
tw=df.created_ts.dt.tz_convert("Asia/Taipei")
trm=tw<pd.Timestamp("2026-06-01",tz="Asia/Taipei"); tr=df[trm].copy(); te=df[~trm].copy()
prior=tr.label.mean()
for keys,c in [(["member_id"],"member_cancel_rate"),(["member_id","product_id"],"member_product_cancel_rate"),(["product_id"],"product_cancel_rate")]:
    st=tr.groupby(keys).label.mean().rename(c).reset_index()
    te=te.merge(st,on=keys,how="left"); 
    print(f"  test {c:28s} 覆蓋率={te[c].notna().mean():.4f} AUC(缺值補 train 平均)={auc(te.label,te[c].fillna(prior)):.4f}")
print("train n",len(tr),"test n",len(te))
```

輸出：

```text
== 留一法（排除自己這筆）目標編碼的單一特徵 AUC
  member           LOO AUC(有值者)=0.5021  有值比例=1.0000
  member×product   LOO AUC(有值者)=0.4901  有值比例=0.0407
  product          LOO AUC(有值者)=0.5039  有值比例=0.9988
== 時間點正確（只用該訂單建立前的訂單）的會員取消率
  member point-in-time AUC=0.5028 有值比例=0.9200
== 時間切分：train=5 月建立、test=6 月建立；編碼只用 train
  test member_cancel_rate           覆蓋率=0.9990 AUC(缺值補 train 平均)=0.5021
  test member_product_cancel_rate   覆蓋率=0.0203 AUC(缺值補 train 平均)=0.4985
  test product_cancel_rate          覆蓋率=0.9988 AUC(缺值補 train 平均)=0.5044
train n 50600 test n 49400
```

### 1.2 member_cancel_rate 與 product_cancel_rate 也含自己的標籤

- **機制**：同樣是含自己的平均。會員平均 12.5 筆訂單，自己那筆佔 1/12，足以把 AUC 拉到 0.7263（留一法後 0.5021）。產品平均 238 筆，影響較小，但仍從 0.5039 拉到 0.5480；另外 120 個產品只有 1 筆訂單（見 4.4），在那些列上 `product_cancel_rate` 就是 label。
- **上線為什麼失效**：上線算不到自己的 label，這部分訊號消失。
- **嚴重度**：主因（member_cancel_rate 單獨就能撐出 0.73，是拿掉 1.1 之後剩下的洩漏來源）；product_cancel_rate 次要。
- **驗證**：q5、q7；產品單筆的部分見 q8。

### 1.3 編碼在切分前用全資料計算（test 標籤流進 train 特徵）

- **機制**：`build_features` 在 `train` 的 `train_test_split` 之前執行，所以 test 列的 label 參與了 train 列的特徵計算，反之亦然。即使改成留一法，只要統計是在切分前用全資料算，test 的資訊仍會進到訓練特徵。
- **上線為什麼失效**：上線時只有過去的資料可用，「未來／同期的標籤」不存在。
- **嚴重度**：主因的一部分（與 1.1、1.2 是同一個錯誤的不同面向：編碼範圍錯＋時間錯）。正確做法是時間切分後只用 train 期間、且早於該筆訂單建立時間的資料計算。
- **驗證**：q7 的時間切分版本（編碼只用 5 月資料）三個編碼 AUC 0.4985～0.5044。

### 1.4 上線時這些特徵大多缺值，補 0 後分布完全不同

- **機制**：離線時每列都有三個編碼值（因為自己就在群組裡）。`train` 裡的 `df[feature_cols].fillna(0)` 從沒被觸發過。
- **上線為什麼失效**：q7 顯示用歷史統計時，6 月訂單只有 2.03% 查得到（會員, 產品）的歷史；其餘缺值，若沿用 `fillna(0)` 會被當成「取消率 0」。模型最大的係數就壓在這個特徵上，上線分數幾乎全由一個常數決定。這是 training-serving skew，跟洩漏一起出現。
- **嚴重度**：主因的一部分（解釋上線為什麼接近亂猜）。
- **驗證**：q7 的覆蓋率輸出。上線實際的補值方式看不到線上程式碼，**未驗證**；這裡是根據訓練管線的 `fillna(0)` 推論。

## 2. 標籤本身的問題

### 2.1 標籤是「快照當下的狀態」，不是「最終是否取消」

- **機制**：`load_orders` 的 `df["label"] = (df["order_status"] == "cancelled").astype(int)` 直接取 base 檔的當前狀態。快照時 14,286 筆是 `created`、42,894 筆是 `paid`，這些訂單還沒走完生命週期，之後可能被取消，卻一律被標成 0。標籤沒有定義觀察窗（例如「建立後 N 天內或出發前取消」）。
- **上線為什麼失效**：上線評估用的是之後真正觀察到的結果，和訓練標籤定義不同；越接近快照日建立的訂單，被誤標為 0 的機率越高。
- **嚴重度**：次要（本資料中錯標比例約 0.9%，見 2.2；但在真實資料這是會系統性偏差的問題）。
- **驗證**：q1 狀態分布；q4 依建立週看取消率，最後一週（06-29 起）取消率 0.128 低於其他週的 0.137～0.146，符合「最近的訂單還來不及被取消」的右設限現象，但只有一週、樣本 3,292，**證據偏弱**。另外 q4 顯示 22,456 筆 `completed` 的出發日在 07-01 之後，「出發前就完成」的狀態語意不清，狀態本身可信度存疑（合成資料，未深究）。

**查詢 q4**

```python
import pandas as pd, numpy as np
D="LionDEExam/candidate_package/dataset/"
raw=pd.read_csv(D+"orders_base.csv")
c=pd.to_datetime(raw.order_created_at,format="mixed",utc=True)
u=pd.to_datetime(raw.updated_at,format="mixed",utc=True)
dep=pd.to_datetime(raw.departure_date)
print("created range",c.min(),c.max()); print("updated range",u.min(),u.max()); print("departure range",dep.min(),dep.max())
snap=pd.Timestamp("2026-07-01")
raw["dep_past"]=dep<snap
print("== status x departure already passed (as of 2026-07-01)")
print(pd.crosstab(raw.order_status,raw.dep_past))
raw["wk"]=c.dt.tz_convert("Asia/Taipei").dt.to_period("W").astype(str)
t=raw.assign(l=raw.order_status=="cancelled").groupby("wk").agg(n=("l","size"),cancel_rate=("l","mean"),created_share=("order_status",lambda s:(s=="created").mean()))
print("== by created week"); print(t.round(3).to_string())
inc=pd.concat([pd.read_csv(D+f"orders_incremental_day{i}.csv").assign(day=i) for i in (1,2,3)])
print("inc rows",len(inc),"unique ids",inc.order_id.nunique())
base_ids=set(raw.order_id)
old=inc[inc.order_id.isin(base_ids)]
print("inc rows on base orders",len(old),"distinct base orders updated",old.order_id.nunique())
u2=pd.to_datetime(old.updated_at,format="mixed",utc=True)
last=old.assign(u=u2).sort_values("u").groupby("order_id").tail(1)[["order_id","order_status"]]
m=raw.drop_duplicates("order_id")[["order_id","order_status"]].merge(last,on="order_id",suffixes=("_base","_latest"))
print("== base status -> latest incremental status"); print(pd.crosstab(m.order_status_base,m.order_status_latest))
print("inc status counts"); print(inc.order_status.value_counts())
```

輸出：

```text
created range 2026-04-30 16:01:46+00:00 2026-06-30 23:50:30+00:00
updated range 2026-04-30 17:49:27+00:00 2026-07-03 09:20:05+00:00
departure range 2026-05-08 00:00:00 2026-10-27 00:00:00
== status x departure already passed (as of 2026-07-01)
dep_past      False  True 
order_status              
cancelled     11191   3057
completed     22456   6156
created       11232   3054
paid          33660   9234
== by created week
                           n  cancel_rate  created_share
wk                                                      
2026-04-27/2026-05-03   4869        0.137          0.143
2026-05-04/2026-05-10  11491        0.139          0.143
2026-05-11/2026-05-17  11417        0.146          0.144
2026-05-18/2026-05-24  11485        0.143          0.145
2026-05-25/2026-05-31  11355        0.142          0.143
2026-06-01/2026-06-07  11481        0.141          0.142
2026-06-08/2026-06-14  11570        0.146          0.140
2026-06-15/2026-06-21  11532        0.145          0.141
2026-06-22/2026-06-28  11548        0.145          0.144
2026-06-29/2026-07-05   3292        0.128          0.144
inc rows 13930 unique ids 13848
inc rows on base orders 1808 distinct base orders updated 1788
== base status -> latest incremental status
order_status_latest  cancelled  completed
order_status_base                        
cancelled                  109        118
completed                  235        241
created                    147        147
paid                       386        405
inc status counts
order_status
paid         8081
created      4016
completed     923
cancelled     910
Name: count, dtype: int64
```

### 2.2 只讀 orders_base，忽略增量檔的狀態更新

- **機制**：`load_orders` 只讀 `orders_base.csv`。三天增量檔裡有 1,808 筆事件更新了 1,788 張 base 訂單。依最後一筆事件，created/paid/completed → cancelled 共 768 筆（147＋386＋235），cancelled → completed 118 筆。這些 label 在訓練資料裡是錯的。
- **上線為什麼失效**：標籤雜訊，且方向偏向低估取消。
- **嚴重度**：次要（約 0.9% 的列）。
- **驗證**：q4 的轉移交叉表。注意 `completed → cancelled`、`cancelled → completed` 這類轉移本身也是資料異常，代表狀態不是單調前進的。

### 2.3 base 檔裡混入截止日之後的更新

- **機制**：base 檔應是 05-01～06-30，但 2,265 列的 `updated_at` 在 2026-07-01（台北）之後。也就是說 base 的狀態已經反映了 7 月的事件，而 `order_created_at` 最晚到 06-30。若以 06-30 為訓練截止，這些列的 label 用到了截止日後的資訊。
- **上線為什麼失效**：離線資料偷看了「比預測時間點更晚」的狀態；量很小，但代表 base 不是一個乾淨的時間點快照。
- **嚴重度**：可忽略（量小）；記錄下來是因為修正設計時要以 `updated_at` 做時間點重建。
- **驗證**：q10。

## 3. 切分與前處理

### 3.1 隨機切分而非時間切分

- **機制**：`train_test_split(X, y, test_size=0.25, random_state=7)` 隨機切。同一會員、同一產品、同一時期的訂單同時在 train 和 test，配合第 1 節的編碼，等於讓 test 看到自己。上線則是「用過去預測未來」。
- **上線為什麼失效**：離線評估沒有模擬時間往前走，任何隨時間漂移的特徵或標籤都不會在離線被看到。
- **嚴重度**：次要（在本資料上，單獨換成時間切分不會改變結論，因為主要洩漏來自編碼；但它是讓洩漏「看起來有效」的評估設計缺陷）。
- **驗證**：q7、q9（時間切分版本）。

### 3.2 StandardScaler 在切分前 fit

- **機制**：`scaler.fit_transform(X)` 在 `train_test_split` 之前，test 的平均與標準差進了前處理。
- **上線為什麼失效**：理論上 test 分布資訊外洩；邏輯迴歸下這只是線性縮放，對 AUC 幾乎沒影響。
- **嚴重度**：可忽略（但應修正，是常見的洩漏樣式）。
- **驗證**：q6 最後一段，scaler 只 fit train 後 test AUC 仍是 0.9999，差異在小數第 4 位以下。

### 3.3 member_order_cnt 用到未來訂單

- **機制**：`member_order_cnt=("order_id", "count")` 數的是會員在整個 05-01～06-30 的訂單數，包括這筆之後才下的單；而且重複的 order_id 會被重複計數（`count` 不是 `nunique`）。
- **上線為什麼失效**：上線只看得到過去的訂單數，數值系統性偏小（5 月初的訂單離線看到約 12 筆，上線只有 0～幾筆），分布不同。
- **嚴重度**：次要。本資料中它的 AUC 是 0.4983，沒有帶來虛高，但會造成 training-serving skew。
- **驗證**：q5（AUC）。分布偏移的量沒有單獨量化。

## 4. 資料品質問題

### 4.1 重複的 order_id

- **機制**：base 有 100,040 列、100,000 個 order_id，40 個 order_id 各出現 2 次。兩列的 `updated_at` 差 2～29 秒，其餘欄位都相同（8 個 id 的 `order_created_at` 字串不同，推測是同一時間的不同格式，未逐筆確認），像是同一事件重送。隨機切分下有 13 對同時落在 train 與 test，等於 test 裡有和 train 完全一樣的樣本；同時它們讓 `member_order_cnt` 與各編碼被重複計數。
- **上線為什麼失效**：重複樣本讓離線記憶效果被當成泛化能力。
- **嚴重度**：可忽略（40／100,040）。
- **驗證**：q2、q10、q12。

**查詢 q2**

```python
import pandas as pd, numpy as np, re
D="LionDEExam/candidate_package/dataset/"
raw=pd.read_csv(D+"orders_base.csv")
dup=raw[raw.order_id.duplicated(keep=False)].sort_values("order_id")
print("dup rows",len(dup),"dup ids",dup.order_id.nunique())
print("fully identical rows",raw.duplicated().sum())
print(dup.head(6).to_string())
# same order_id different status?
g=dup.groupby("order_id").order_status.nunique(); print("ids w/ differing status",(g>1).sum())
print(dup.order_status.value_counts())
# created_at formats
def fmt(s):
    s=str(s)
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$",s): return "iso+08"
    if re.match(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$",s): return "slash_naive"
    return "other:"+re.sub(r"\d","9",s)
print(raw.order_created_at.map(fmt).value_counts())
print(raw.updated_at.map(fmt).value_counts())
print(raw.departure_date.map(lambda s: re.sub(r"\d","9",str(s))).value_counts())
```

輸出：

```text
dup rows 80 dup ids 40
fully identical rows 0
          order_id member_id product_id channel order_status  quantity currency     amount  coupon_discount           order_created_at departure_date                 updated_at
6726   ORD00000984   M004461     P00152      電銷    completed         4      TWD  152295.00            100.0  2026-05-12T03:23:52+08:00     2026-05-27  2026-05-12T07:03:06+08:00
52880  ORD00000984   M004461     P00152      電銷    completed         4      TWD  152295.00            100.0  2026-05-12T03:23:52+08:00     2026-05-27  2026-05-12T07:02:52+08:00
91816  ORD00007259   M001589     P00035     web         paid         3      USD   16902.73            700.0  2026-05-27T04:18:47+08:00     2026-08-16  2026-05-27T12:48:47+08:00
80221  ORD00007259   M001589     P00035     web         paid         3      USD   16902.73            700.0  2026-05-27T04:18:47+08:00     2026-08-16  2026-05-27T12:49:05+08:00
3277   ORD00008372   M000161     P00117     web    cancelled         1      TWD  160364.00              0.0  2026-05-25T13:35:03+08:00     2026-08-21  2026-05-26T16:33:03+08:00
76610  ORD00008372   M000161     P00117     web    cancelled         1      TWD  160364.00              0.0  2026-05-25T13:35:03+08:00     2026-08-21  2026-05-26T16:33:29+08:00
ids w/ differing status 0
order_status
completed    32
paid         26
cancelled    14
created       8
Name: count, dtype: int64
order_created_at
iso+08                        94038
slash_naive                    3001
other:9999-99-99T99:99:99Z     3001
Name: count, dtype: int64
updated_at
iso+08    100040
Name: count, dtype: int64
departure_date
9999-99-99    100040
Name: count, dtype: int64
```

**查詢 q12**

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
raw=pd.read_csv(D+"orders_base.csv")
dup=raw[raw.order_id.duplicated(keep=False)]
diffcols={c:(dup.groupby("order_id")[c].nunique()>1).sum() for c in raw.columns if c!="order_id"}
print("每欄在重複 order_id 內有差異的 id 數:",diffcols)
u=pd.to_datetime(dup.updated_at,utc=True); gap=u.groupby(dup.order_id).agg(lambda s:(s.max()-s.min()).total_seconds())
print("updated_at 差距秒數 describe"); print(gap.describe().round(1).to_string())
```

輸出：

```text
每欄在重複 order_id 內有差異的 id 數: {'member_id': np.int64(0), 'product_id': np.int64(0), 'channel': np.int64(0), 'order_status': np.int64(0), 'quantity': np.int64(0), 'currency': np.int64(0), 'amount': np.int64(0), 'coupon_discount': np.int64(0), 'order_created_at': np.int64(8), 'departure_date': np.int64(0), 'updated_at': np.int64(40)}
updated_at 差距秒數 describe
count    40.0
mean     15.2
std       8.2
min       2.0
25%       9.2
50%      16.0
75%      20.0
max      29.0
```

### 4.2 order_created_at 三種格式、時區處理不一致

- **機制**：94,038 列是 `+08:00`、3,001 列是結尾 `Z`、3,001 列是 `2026/06/22 04:47:19` 這種無時區格式。`pd.to_datetime(..., format="mixed", utc=True)` 會把無時區格式當成 UTC，但它實際上是台北時間：這組的 `updated_at - created` 平均少 8 小時，且 12.8% 出現「建立晚於更新」（其他兩組 0%）。另外 `days_to_departure` 用 `df["departure"].dt.tz_localize("UTC")`，把出發日當 UTC 午夜（台北 08:00），對 `+08:00` 的列造成 8 小時偏移，32,335 列的天數和「台北時區一致處理」的結果差 1 天。
- **上線為什麼失效**：上線若以正確時區計算 `days_to_departure`，數值與訓練不一致（training-serving skew）。
- **嚴重度**：可忽略（`days_to_departure` 本身 AUC 0.4981，沒訊號）。
- **驗證**：q2（格式分布）、q3（各格式的時間差）、q10（天數差異筆數）。

**查詢 q3**

```python
import pandas as pd, numpy as np, re
D="LionDEExam/candidate_package/dataset/"
raw=pd.read_csv(D+"orders_base.csv")
raw["fmt"]=np.where(raw.order_created_at.str.contains("/"),"slash_naive",np.where(raw.order_created_at.str.endswith("Z"),"Z","iso+08"))
c=pd.to_datetime(raw.order_created_at,format="mixed",utc=True)
u=pd.to_datetime(raw.updated_at,format="mixed",utc=True)
raw["gap_h"]=(u-c).dt.total_seconds()/3600
print("== updated-created gap hours by created format")
print(raw.groupby("fmt").gap_h.describe().round(2).to_string())
print("created>updated by fmt:",raw.assign(neg=raw.gap_h<0).groupby("fmt").neg.mean().round(4).to_dict())
print("== coupon_discount by status")
print(raw.groupby("order_status").coupon_discount.agg(["mean","median",lambda s:(s==0).mean()]).round(3).to_string())
print("== amount/quantity by status")
print(raw.groupby("order_status")[["amount","quantity"]].agg(["mean","median"]).round(1).to_string())
print("== cancel rate by created format"); print(raw.assign(l=raw.order_status=="cancelled").groupby("fmt").l.mean().round(4))
print("== gap hours by status"); print(raw.groupby("order_status").gap_h.describe().round(1).to_string())
```

輸出：

```text
== updated-created gap hours by created format
               count   mean    std   min    25%    50%    75%    max
fmt                                                                 
Z             3001.0  33.18  19.44  0.02  15.97  32.75  50.30  66.65
iso+08       94038.0  33.39  19.23  0.02  16.73  33.45  50.07  66.65
slash_naive   3001.0  25.36  19.50 -7.97   8.52  25.65  42.00  58.65
created>updated by fmt: {'Z': 0.0, 'iso+08': 0.0, 'slash_naive': 0.128}
== coupon_discount by status
                 mean  median  <lambda_0>
order_status                             
cancelled     477.180   500.0       0.048
completed     472.449   450.0       0.049
created       475.700   450.0       0.047
paid          471.319   450.0       0.051
== amount/quantity by status
                amount           quantity       
                  mean    median     mean median
order_status                                    
cancelled     350666.7  159498.0      2.5    2.0
completed     458618.4  154564.0      2.5    2.0
created       349655.1  156247.5      2.5    2.0
paid          532719.7  158843.5      2.5    3.0
== cancel rate by created format
fmt
Z              0.1300
iso+08         0.1429
slash_naive    0.1393
Name: l, dtype: float64
== gap hours by status
                count  mean   std  min   25%   50%   75%   max
order_status                                                  
cancelled     14248.0  33.2  19.3 -7.9  16.7  33.1  49.9  66.6
completed     28612.0  33.1  19.2 -8.0  16.3  33.2  49.8  66.6
created       14286.0  33.0  19.3 -7.8  16.2  32.7  49.7  66.6
paid          42894.0  33.2  19.3 -8.0  16.6  33.3  50.0  66.6
```

### 4.3 amount 混幣別、有負數與極端值

- **機制**：`amount` 是原幣別，直接當特徵，JPY 中位數 972,503、USD 6,445、TWD 202,873，數值大小主要反映幣別而非訂單價值；另有 `NTD`（應與 TWD 同義）、負數 50 筆、超過該幣別 99 分位 10 倍的極端值 39 筆（JPY 最大 3.7e9），`coupon_discount` 有 300 筆負數。這些點會主導 `StandardScaler` 的標準差。
- **上線為什麼失效**：若上線端把金額換成 TWD 或做了清洗，與訓練分布不一致。
- **嚴重度**：可忽略（對虛高無貢獻：異常列的取消率與整體相近，不是洩漏；`amount` AUC 0.5015）。
- **驗證**：q10（幣別分布）、q11（異常值與標籤關係）。

**查詢 q11**

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
df=load_orders()
df["neg"]=df.amount<0
q=df.groupby("currency").amount.transform(lambda s:s.quantile(.99)*10); df["huge"]=df.amount>q
print(df.groupby("order_status")[["neg","huge"]].sum().to_string())
print("label rate | neg",round(df.label[df.neg].mean(),4),"| huge",round(df.label[df.huge].mean(),4),"| all",round(df.label.mean(),4))
print("coupon<0",(df.coupon_discount<0).sum(),"coupon null",pd.to_numeric(df.coupon_discount,errors='coerce').isna().sum(),"quantity<=0",(df.quantity<=0).sum())
print("departure < created date",(df.departure.dt.tz_localize("Asia/Taipei")<df.created_ts).sum())
```

輸出：

```text
              neg  huge
order_status           
cancelled       7     4
completed      18     9
created         6     7
paid           19    19
label rate | neg 0.14 | huge 0.1026 | all 0.1424
coupon<0 300 coupon null 0 quantity<=0 0
departure < created date 0
```

### 4.4 不存在於產品主檔的 product_id

- **機制**：訂單裡有 420 個 product_id，其中 120 個（如 `P91064`）不在 `products.csv`，每個都只有 1 筆訂單。這 120 列的 `product_cancel_rate` 100% 等於 label。
- **上線為什麼失效**：同 1.2，上線查不到這種孤兒產品的歷史。
- **嚴重度**：次要（併入 1.2）。
- **驗證**：q8。

### 4.5 members.csv 是多版本快照（管線目前沒用，但文件聲稱有用）

- **機制**：模組 docstring 寫「資料：../dataset/orders_base.csv 與 members.csv」，但程式碼沒有讀 members.csv。members.csv 有 8,991 列、8,000 個會員；989 個會員有多筆快照（extract_date 04-30、05-31、06-30），其中 434 人等級變過、367 人城市變過；04-30 那天就有 8,030 列，代表同一天也有重複。直接 `merge(on="member_id")` 會把 100,040 列放大成 112,456 列；若取最新快照（06-30）的等級當 5 月訂單的特徵，就是用到未來資訊。
- **上線為什麼失效**：若 DS 下一版加入會員特徵而沒做 as-of join，會出現新的洩漏與重複樣本。目前管線未使用，所以對現在的 0.9 沒貢獻。
- **嚴重度**：可忽略（對現況）；是潛在風險，也是文件與程式不一致。
- **驗證**：q8。會員等級與取消率看不出關係（0.140～0.148）。

**查詢 q8**

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
df=load_orders()
P=pd.read_csv(D+"products.csv"); M=pd.read_csv(D+"members.csv")
pc=df.groupby("product_id").size()
print("products.csv rows",len(P),"unique",P.product_id.nunique(),"| order product_ids",len(pc),"not in products.csv",(~pc.index.isin(P.product_id)).sum())
small=pc[pc<=5]; print("products with <=5 orders",len(small),"rows in them",small.sum(),"their ids sample",list(small.index[:5]))
print("singleton products in products.csv?",small.index.isin(P.product_id).sum())
f,cols=build_features(df)
s=f.product_id.map(pc)==1
print("rows with singleton product: product_cancel_rate==label share",(f.loc[s,"product_cancel_rate"]==f.loc[s,"label"]).mean(), "n",s.sum())
print("product_cancel_rate AUC excl singleton products",round(auc(f.label[~s],f.product_cancel_rate[~s]),4))
print("== members.csv")
print("rows",len(M),"unique member",M.member_id.nunique(),"extract_date values",M.extract_date.value_counts().sort_index().to_dict())
mm=M.groupby("member_id").agg(n=("extract_date","size"),lv=("member_level","nunique"),city=("city","nunique"))
print("members with >1 snapshot",(mm.n>1).sum(),"of which level changed",((mm.n>1)&(mm.lv>1)).sum(),"city changed",((mm.n>1)&(mm.city>1)).sum())
om=set(df.member_id); print("order members",len(om),"not in members.csv",len(om-set(M.member_id)))
print("register_date > extract_date",(pd.to_datetime(M.register_date,errors='coerce')>pd.to_datetime(M.extract_date,errors='coerce')).sum())
# naive join would fan out
j=df.merge(M,on="member_id",how="left"); print("orders rows",len(df),"after naive join with members",len(j))
print("== cancel rate by channel / currency / member_level(latest snapshot)")
print(df.groupby("channel").label.mean().round(4).to_dict()); print(df.groupby("currency").label.mean().round(4).to_dict())
lat=M.sort_values("extract_date").groupby("member_id").tail(1)
print(df.merge(lat,on="member_id").groupby("member_level").label.mean().round(4).to_dict())
print(df.merge(P,on="product_id").groupby("product_type").label.mean().round(4).to_dict())
```

輸出：

```text
products.csv rows 300 unique 300 | order product_ids 420 not in products.csv 120
products with <=5 orders 120 rows in them 120 their ids sample ['P91064', 'P91071', 'P91118', 'P91133', 'P91216']
singleton products in products.csv? 0
rows with singleton product: product_cancel_rate==label share 1.0 n 120
product_cancel_rate AUC excl singleton products 0.547
== members.csv
rows 8991 unique member 8000 extract_date values {'2026-04-30': 8030, '2026-05-31': 459, '2026-06-30': 502}
members with >1 snapshot 989 of which level changed 434 city changed 367
order members 8000 not in members.csv 0
register_date > extract_date 0
orders rows 100040 after naive join with members 112456
== cancel rate by channel / currency / member_level(latest snapshot)
{'app': 0.1425, 'web': 0.1444, '門市': 0.1448, '電銷': 0.1379}
{'JPY': 0.1423, 'NTD': 0.155, 'TWD': 0.1429, 'USD': 0.1408}
{'一般': 0.1412, '白金': 0.1476, '金卡': 0.1406, '銀卡': 0.14}
{'團體旅遊': 0.1419, '機票': 0.1415, '票券': 0.1402, '自由行': 0.1449, '訂房': 0.1438}
```

## 5. 根本觀察：合法特徵幾乎沒有訊號

把所有特徵改成「只用該訂單建立時間之前的資料」計算，5 月訓練、6 月測試：

**查詢 q9**

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
df=load_orders().drop_duplicates("order_id").sort_values("created_ts").reset_index(drop=True)
# 時間點正確特徵：只看建立時間之前的訂單（注意：仍用最終狀態當過去訂單的標籤，屬寬鬆上界）
g=df.groupby("member_id")
df["member_order_cnt"]=g.cumcount()
df["member_cancel_rate"]=((g.label.cumsum()-df.label)/df.member_order_cnt).fillna(-1)
gp=df.groupby("product_id"); n=gp.cumcount()
df["product_cancel_rate"]=((gp.label.cumsum()-df.label)/n).fillna(-1)
gm=df.groupby(["member_id","product_id"]); n=gm.cumcount()
df["member_product_cancel_rate"]=((gm.label.cumsum()-df.label)/n).fillna(-1)
df["days_to_departure"]=(df.departure.dt.tz_localize("Asia/Taipei")-df.created_ts).dt.days
df["coupon_discount"]=pd.to_numeric(df.coupon_discount,errors="coerce").fillna(0)
cols=["member_order_cnt","member_cancel_rate","member_product_cancel_rate","product_cancel_rate","amount","quantity","coupon_discount","days_to_departure"]
tw=df.created_ts.dt.tz_convert("Asia/Taipei"); trm=(tw<pd.Timestamp("2026-06-01",tz="Asia/Taipei")).values
X=df[cols].values.astype(float); y=df.label.values
mu,sd=X[trm].mean(0),X[trm].std(0); Xs=(X-mu)/sd
w=fit_logreg(Xs[trm],y[trm])
print(f"時間切分＋時間點正確特徵：Train AUC={auc(y[trm],predict(w,Xs[trm])):.4f}  Test AUC={auc(y[~trm],predict(w,Xs[~trm])):.4f}")
```

輸出：

```text
時間切分＋時間點正確特徵：Train AUC=0.5140  Test AUC=0.4969
```

再加上 q8 的類別分層：通路、幣別、會員等級、產品類型的取消率都在 0.137～0.155 之間，q5 裡 amount、quantity、coupon、days_to_departure 的 AUC 都在 0.498～0.505。

- **意義**：這份（合成）資料的取消標籤和所有可在下單時取得的特徵幾乎獨立。離線 0.9+ 完全是洩漏，**誠實的離線評估本來就該得到約 0.5**，和上線的 0.55 一致。修正後不要期待把 AUC 救回 0.9；修正的價值在於讓離線指標說真話。
- **限制**：時間點版本的過去訂單仍用「快照最終狀態」當 label（過去訂單在當下可能還沒取消），這是寬鬆上界；即使如此也只有 0.4969。上線 0.55 與 0.50 的差距原因**未驗證**（可能是上線樣本差異或隨機波動）。

## 6. 問題總表

| # | 問題 | 嚴重度 | 驗證 |
|---|---|---|---|
| 1.1 | member_product_cancel_rate 含自身標籤，98.99% 列等於 label | 主因 | 已驗證（q5、q6、q7） |
| 1.2 | member_cancel_rate／product_cancel_rate 含自身標籤 | 主因／次要 | 已驗證（q5、q7） |
| 1.3 | 目標編碼在切分前用全資料計算 | 主因（與 1.1、1.2 同源） | 已驗證（q7） |
| 1.4 | 上線時編碼大多缺值，fillna(0) 造成分布錯位 | 主因的一部分 | 覆蓋率已驗證（q7）；線上補值方式未驗證 |
| 2.1 | 標籤是快照狀態，未完結訂單被標 0，無觀察窗 | 次要 | 已驗證（q1、q4），右設限證據偏弱 |
| 2.2 | 只讀 base，忽略增量檔的取消事件（768 筆 0→1、118 筆 1→0） | 次要 | 已驗證（q4） |
| 2.3 | base 含 07-01 之後的更新（2,265 列） | 可忽略 | 已驗證（q10） |
| 3.1 | 隨機切分而非時間切分 | 次要 | 已驗證（q7、q9） |
| 3.2 | Scaler 在切分前 fit | 可忽略 | 已驗證（q6） |
| 3.3 | member_order_cnt 數到未來訂單、重複計數 | 次要 | AUC 已驗證（q5）；分布偏移未量化 |
| 4.1 | 40 個重複 order_id，13 對跨 train/test | 可忽略 | 已驗證（q2、q10、q12） |
| 4.2 | 三種時間格式，無時區格式被當 UTC；departure 當 UTC 午夜 | 可忽略 | 已驗證（q2、q3、q10） |
| 4.3 | amount 混幣別（含 NTD）、負數、極端值；coupon 負數 | 可忽略 | 已驗證（q10、q11） |
| 4.4 | 120 個孤兒 product_id 各 1 筆，product_cancel_rate＝label | 次要（併 1.2） | 已驗證（q8） |
| 4.5 | members.csv 多版本快照，未用但 docstring 宣稱有用；naive join 會放大列數、取到未來 | 可忽略（潛在風險） | 已驗證（q8） |
| 5 | 合法特徵幾乎無訊號，誠實 AUC ≈ 0.50 | 背景事實 | 已驗證（q9、q8、q5） |

## 附錄 A. 共用程式碼

所有查詢都用 `.venv/bin/python -I -W ignore qN.py` 執行，並 import 以下 `common.py`。`load_orders`、`build_features` 逐行照抄原管線；`fit_logreg` 用 Newton 法、L2 懲罰 1.0，對應 sklearn `LogisticRegression` 預設 `C=1.0`；`auc` 用 Mann-Whitney 秩和，等同 `roc_auc_score`。隨機切分用 `np.random.RandomState(7).permutation`，和 sklearn 的切法不保證逐列相同，所以重現的 0.9999 和 DS 回報的「0.9 以上」數字不同但方向一致。

```python
import pandas as pd, numpy as np
D="LionDEExam/candidate_package/dataset/"
def load_orders():  # 與 churn_training_pipeline.load_orders 相同
    df = pd.read_csv(D+"orders_base.csv")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["created_ts"] = pd.to_datetime(df["order_created_at"], format="mixed", errors="coerce", utc=True)
    df["departure"] = pd.to_datetime(df["departure_date"], errors="coerce")
    df = df.dropna(subset=["amount", "created_ts", "departure"])
    df["label"] = (df["order_status"] == "cancelled").astype(int)
    return df
def build_features(df):  # 與 churn_training_pipeline.build_features 相同
    member_stats = df.groupby("member_id").agg(member_order_cnt=("order_id","count"), member_cancel_rate=("label","mean")).reset_index()
    df = df.merge(member_stats, on="member_id", how="left")
    mp = df.groupby(["member_id","product_id"]).agg(member_product_cancel_rate=("label","mean")).reset_index()
    df = df.merge(mp, on=["member_id","product_id"], how="left")
    ps = df.groupby("product_id").agg(product_cancel_rate=("label","mean")).reset_index()
    df = df.merge(ps, on="product_id", how="left")
    df["days_to_departure"] = (df["departure"].dt.tz_localize("UTC") - df["created_ts"]).dt.days
    df["coupon_discount"] = pd.to_numeric(df["coupon_discount"], errors="coerce").fillna(0)
    cols = ["member_order_cnt","member_cancel_rate","member_product_cancel_rate","product_cancel_rate","amount","quantity","coupon_discount","days_to_departure"]
    return df, cols
def auc(y, s):  # Mann-Whitney，等同 sklearn roc_auc_score（含 tie 平均秩）
    y=np.asarray(y); r=pd.Series(np.asarray(s,dtype=float)).rank().values
    n1=y.sum(); n0=len(y)-n1
    return (r[y==1].sum()-n1*(n1+1)/2)/(n1*n0)
def fit_logreg(X, y, iters=50, l2=1.0):  # Newton/IRLS，L2 對應 sklearn C=1.0
    X=np.c_[np.ones(len(X)),X]; w=np.zeros(X.shape[1])
    for _ in range(iters):
        p=1/(1+np.exp(-X@w)); g=X.T@(p-y)+l2*np.r_[0,w[1:]]
        H=(X*(p*(1-p))[:,None]).T@X+l2*np.diag(np.r_[0,np.ones(len(w)-1)])
        w-=np.linalg.solve(H,g)
    return w
def predict(w,X): return 1/(1+np.exp(-(np.c_[np.ones(len(X)),X]@w)))
def split(n, test_size=0.25, seed=7):
    idx=np.random.RandomState(seed).permutation(n); k=int(np.ceil(n*test_size))
    return idx[k:], idx[:k]
```

其餘查詢：

**查詢 q1**

```python
import pandas as pd, numpy as np, sys
D="LionDEExam/candidate_package/dataset/"
raw=pd.read_csv(D+"orders_base.csv")
print("rows",len(raw),"unique order_id",raw.order_id.nunique())
print(raw.order_status.value_counts(dropna=False))
# replicate load_orders
df=raw.copy()
df["amount"]=pd.to_numeric(df["amount"],errors="coerce")
df["created_ts"]=pd.to_datetime(df["order_created_at"],format="mixed",errors="coerce",utc=True)
df["departure"]=pd.to_datetime(df["departure_date"],errors="coerce")
print("null amount",df.amount.isna().sum(),"null created",df.created_ts.isna().sum(),"null dep",df.departure.isna().sum())
drop=df[df[["amount","created_ts","departure"]].isna().any(axis=1)]
print("dropped rows",len(drop)); print(drop.order_status.value_counts())
print("raw amount non-numeric samples",raw.loc[pd.to_numeric(raw.amount,errors='coerce').isna(),"amount"].value_counts(dropna=False).head())
df=df.dropna(subset=["amount","created_ts","departure"])
df["label"]=(df.order_status=="cancelled").astype(int)
print("after dropna",len(df),"cancel rate",round(df.label.mean(),4))
```

輸出：

```text
rows 100040 unique order_id 100000
order_status
paid         42894
completed    28612
created      14286
cancelled    14248
Name: count, dtype: int64
null amount 0 null created 0 null dep 0
dropped rows 0
Series([], Name: count, dtype: int64)
raw amount non-numeric samples Series([], Name: count, dtype: int64)
after dropna 100040 cancel rate 0.1424
```

**查詢 q10**

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
raw=pd.read_csv(D+"orders_base.csv")
u=pd.to_datetime(raw.updated_at,utc=True).dt.tz_convert("Asia/Taipei")
c=pd.to_datetime(raw.order_created_at,format="mixed",utc=True)
cut=pd.Timestamp("2026-07-01",tz="Asia/Taipei")
print("base rows updated_at >= 2026-07-01 (台北)",(u>=cut).sum())
print("dup order_id rows",raw.order_id.duplicated().sum())
print("== amount by currency"); print(raw.groupby("currency").amount.describe(percentiles=[.5,.99]).round(1).to_string())
# 隨機切分下重複訂單同時落在 train/test 的數量
df=load_orders(); tr,te=split(len(df)); s=pd.Series("tr",index=range(len(df))); s.iloc[te]="te"
d=df.reset_index(drop=True).assign(part=s.values); x=d[d.order_id.duplicated(keep=False)].groupby("order_id").part.nunique()
print("duplicate order pairs split across train/test",(x>1).sum(),"of",len(x))
# slash 格式 naive 時間被當 UTC：days_to_departure 改變幾筆
naive=raw.order_created_at.str.contains("/")
c_ok=c.where(~naive, pd.to_datetime(raw.order_created_at.where(naive),format="%Y/%m/%d %H:%M:%S").dt.tz_localize("Asia/Taipei").dt.tz_convert("UTC"))
dep=pd.to_datetime(raw.departure_date)
d1=(dep.dt.tz_localize("UTC")-c).dt.days; d2=(dep.dt.tz_localize("Asia/Taipei")-c_ok).dt.days
print("days_to_departure 原管線 vs 台北時區修正後 不同的筆數",(d1!=d2).sum(),"/",len(raw))
print("其中 slash 格式",(naive&(d1!=d2)).sum())
```

輸出：

```text
base rows updated_at >= 2026-07-01 (台北) 2265
dup order_id rows 40
== amount by currency
            count       mean         std        min       50%        99%           max
currency                                                                              
JPY       11022.0  2001373.2  45668870.9 -3087159.0  972503.5  4074452.0  3.738074e+09
NTD         200.0   272808.7    211471.7     2798.0  222540.5   858701.3  9.161420e+05
TWD       66690.0   353922.0   6313437.2  -594452.0  202872.0   837559.4  7.367100e+08
USD       22128.0    11170.8    190113.5   -27292.7    6445.2    26257.5  1.807485e+07
duplicate order pairs split across train/test 13 of 40
days_to_departure 原管線 vs 台北時區修正後 不同的筆數 32335 / 100040
其中 slash 格式 0
```
