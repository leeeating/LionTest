# 模組 F：修正設計初稿

〔待使用者確認〕AI 依使用者在 T2、T3 的定案寫出的初稿（定案見 process-log「第四部分：進階模組 F」）。題目要求「虛擬碼＋文字說明，說明正確的特徵計算原則與資料切分方式」，不必完整實作。

## 目錄
1. [四條原則](#1-四條原則)
2. [標籤定義](#2-標籤定義)
3. [特徵計算](#3-特徵計算)
4. [資料切分與評估](#4-資料切分與評估)
5. [虛擬碼](#5-虛擬碼)
6. [主因與修法對照](#6-主因與修法對照)
7. [值得質疑的地方](#7-值得質疑的地方)
- [附錄 A：查詢與輸出](#附錄-a查詢與輸出)

## 1. 四條原則
1. **時間點正確（point-in-time）**：每筆訂單的特徵，只能用「這筆下單那一刻已經知道的事」。這條涵蓋排除自己的標籤，也涵蓋不用未來的訂單。
2. **標籤要等結果確定**：還沒到出發日的訂單，結果不確定，不拿來訓練或評估。
3. **離線模擬上線**：用過去訓練、用未來評估。上線時特徵表每天凌晨批次更新一次，所以特徵統計（取消率、訂單數）一律以每筆訂單「下單當天 00:00」為 as_of 計算，和上線看到的一樣；模型參數與標準化參數只從訓練集學。模型要模擬「在某天 D 部署」：只用 D 之前結果都已確定的訂單訓練，評估 D 之後才下的單。
4. **訓練與上線用同一支特徵函式**：函式吃一個「現在時間」參數，訓練時傳歷史時間點，上線時傳當下時間，避免兩邊各寫一套而算法不一致。

## 2. 標籤定義
- **標籤**：訂單在出發日之前被取消就是 1，出發日過了沒被取消就是 0。這依使用者定案：取消只會發生在出發前。
- **只用結果確定的訂單**：判斷時間點 `t` 時，只有 `departure_date < t` 的訂單有確定的標籤。
- **代價（機制）**：標籤要等到出發日才確定，所以標籤的延遲等於「下單到出發」的天數，最新的一段訂單永遠還不能用來訓練。正式環境的歷史資料長達數年，這個延遲只是讓訓練資料晚一段時間，不影響可行性。
- **這份資料上的量級（只當佐證）**：只有兩個月的資料，下單到出發中位數 63 天，以 07-01 為準只有 21,501 筆（約 21%）出發日已過（附錄 A-1）。這是合成資料期間太短造成的，不能拿來評估設計好壞。
- **這份資料的限制**：這 21,501 筆裡有 9,234 筆「已付款」、3,054 筆「已建立」，出發日已過卻沒走到完成（附錄 A-1，和 Part A 的發現一致）。依定義它們沒被取消，標 0，但狀態語意可疑，要在報告寫明。

## 3. 特徵計算
| 原特徵 | 問題（診斷報告編號） | 修正 |
|---|---|---|
| `member_cancel_rate` | 含自己的標籤、用到未來（2.2） | 只算這位會員在 `t` 之前、且結果已確定的訂單 |
| `product_cancel_rate` | 同上（2.2）；120 個不在產品清單的編號（D2） | 同上；不在產品清單的編號視為未知產品，不算它自己的取消率、直接用整體取消率；逐層平滑時跳過「會員 × 產品類型」層；並回報上游 |
| `member_product_cancel_rate` | 幾乎等於標籤（2.1）；上線時只有約 3～4% 查得到（D1，這份資料的量級） | **保留，改正定義**（使用者定案）：只算這位會員在 `t` 之前、結果已確定的同產品訂單，做下面的平滑，並附歷史筆數。歷史太少時逐層向較粗的分組靠攏：會員 × 產品 → 會員 × 產品類型 → 會員 → 整體（以上一層的取消率當平滑先驗） 。歷史很少時，這個特徵會接近會員層的取消率，和 `member_cancel_rate` 相近；靠 `member_product_hist_n` 讓模型區分「真的有同產品歷史」和「只是退回會員層」 |
| `member_order_cnt` | 數到未來的訂單（2.2） | 只數 `t` 之前下的單；這個不用等結果確定 |
| `amount`、`quantity`、`coupon_discount`、`days_to_departure` | 下單當下就知道，沒有洩漏 | 不變。另外的資料品質問題（幣別、時區）不在本題範圍 |

**樣本少的取消率要平滑**：歷史只有 1、2 筆時，取消率只會是 0、0.5、1 這種極端值。改成向整體取消率靠攏：

```
平滑取消率 = (取消筆數 + k × 整體取消率) / (歷史筆數 + k)
```

`k` 是「要幾筆歷史才相信它」，屬於可調參數，本設計不指定數值（虛擬碼的 k = 10 僅示意）。歷史是 0 筆時，值等於整體取消率，而不是 `fillna(0)` 的 0（0 的意思是「從不取消」，反而是很強的訊號）。另外加一個「歷史筆數」特徵，讓模型知道這個取消率有多可靠。

## 4. 資料切分與評估
- **按下單時間切成整批（cohort），中間留空檔**：取代 `train_test_split` 的隨機切。選一個模擬部署日 D：訓練集是 D 之前某段下單區間、而且在 D 之前全部出發的訂單；評估集是 D 之後下的單。訓練段結束到 D 之間要留空檔，至少是最長的下單到出發天數；不留空檔的話，訓練集裡會有評估集下單之後才確定的結果，模型等於學到了評估期間的事（例如同一段時間的颱風取消潮），離線分數偏高（第二次獨立驗收發現）。
- **整批全部出發後才使用**：一段區間要等到裡面的訂單**全部**出發，才拿來訓練或評估。不能用「出發日早於切點」篩選：越靠近切點下的單，只剩下單到出發天數很短的能留下，訓練與評估都會偏向短天期訂單，和上線要預測的分布不同，而 `days_to_departure` 本身就是特徵（獨立驗收 agent 發現）。註：計算歷史特徵時仍用「出發日早於 as_of」篩選，這不矛盾：上線時同樣只看得到已出發的歷史，訓練與上線的篩法一致，不會造成落差；不能這樣篩的是「要訓練或評估哪些訂單」。代價是要等最長的下單到出發天數，模型用的資料比較舊。
- **特徵以每筆的下單日計算**：評估集訂單的特徵，用同一支函式、以它下單當天 00:00 為 as_of 計算，只會用到前一天以前已確定的結果；模型與 scaler 只從訓練集學。
- **標準化**：`scaler.fit` 只用訓練集，評估集只 `transform`。
- **滑動視窗**：上面的「部署日 D」往後滑多次，每次都是「訓練一段、空檔、評估一段」，看結果穩不穩，也模擬定期重新訓練。每個視窗都套用「整批全部出發後才使用」。訓練資料用固定長度或從最早累積皆可，依資料量決定。

## 5. 虛擬碼

```python
def build_features(orders, as_of):
    """回傳 as_of 這一刻、每筆訂單可用的特徵。訓練與上線共用。
    orders 已依 order_id 去重，並 join 產品清單取得 product_type（不在清單的為 NULL）。
    as_of 一律是某天 00:00：特徵表每天凌晨批次產出一次。"""
    orders = dedup(orders, key="order_id")                     # 重複送來的同一筆只留一列
    past = orders[orders.created_at < as_of]                    # 只看前一天以前下的單
    settled = past[past.departure_date < as_of.date()]          # 出發日整天過完才算結果確定
    known = settled[settled.product_type.notna()]               # 不在產品清單的編號不算自己的取消率
    prior = global_rate(settled)
    member_hist = settled.groupby("member_id").agg(n=("label", "size"), cancels=("label", "sum"))
    product_hist = known.groupby("product_id").agg(n=("label", "size"), cancels=("label", "sum"))
    return {
        "member_cancel_rate": smooth(member_hist, k=10, prior=prior),
        "member_hist_n": member_hist.n,
        "product_cancel_rate": smooth(product_hist, k=10, prior=prior),   # 未知產品查不到 → 先驗
        "product_hist_n": product_hist.n,
        # 逐層平滑：每一層以上一層（較粗分組）的平滑取消率當先驗，最粗一層的先驗是整體取消率；
        # 歷史 0 筆時值等於先驗，所以不需要另設「退回」門檻。
        # product_type 是 NULL（未知產品）時跳過「會員 × 產品類型」這層，直接用會員層當先驗。
        "member_product_cancel_rate": smooth_hierarchical(settled, k=10, prior=prior,
            levels=[["member_id"], ["member_id", "product_type"], ["member_id", "product_id"]]),
        "member_product_hist_n": settled.groupby(["member_id", "product_id"]).size(),
        "member_order_cnt": past.groupby("member_id").size(),  # 訂單數不用等結果確定
    }

def features_for(order, orders):
    f = build_features(orders, as_of=floor_to_day(order.created_at))  # 和上線一樣只看到前一天的批次
    return lookup(f, order) | order_own_fields(order)           # 查不到時：取消率用先驗、歷史筆數與訂單數為 0

# 訓練與評估：滑動視窗，每個視窗模擬「在 D 這天部署模型」
def cohort(orders, start, end):
    return orders[(orders.created_at >= start) & (orders.created_at < end)]

for train_start, train_end, D, test_end in windows:
    train = cohort(orders, train_start, train_end)
    assert train.departure_date.max() < D                       # 訓練段在部署日前全部出發、結果都已確定
    test  = cohort(orders, D, test_end)                         # 部署日之後才下的單
    assert test.departure_date.max() < NOW                      # 評估段也要全部出發才能評
    X_tr = [features_for(o, orders) for o in train]
    X_te = [features_for(o, orders) for o in test]
    scaler.fit(X_tr); model.fit(scaler.transform(X_tr), train.label)
    evaluate(model, scaler.transform(X_te), test.label)
# train_end 到 D 之間的空檔，就是等訓練段全部出發的時間（至少是最長的下單到出發天數）。
# 例：最長提前 120 天時，(01-01, 02-01, 06-01, 07-01)、(02-01, 03-01, 07-01, 08-01)……

# 上線（特徵表每天凌晨更新）
x = features_for(new_order, orders)                             # as_of = 今天 00:00
```

註：`features_for` 逐筆算是為了清楚表達原則；實作時可用依時間排序後的累計計數（cumulative sum）一次算完，結果相同。

## 6. 主因與修法對照
| 診斷 | 修法在哪 |
|---|---|
| 2.1 `member_product_cancel_rate` 幾乎等於標籤 | 第 3 節：保留，改成時間點正確的定義＋平滑＋逐層退回 |
| 2.2 三個特徵用到未來資料、含自己的標籤 | 第 1 節原則 1；第 5 節 `created_at < as_of` 與 `departure_date < as_of.date()` |
| 2.3A 先算特徵、後切分 | 第 1 節原則 3、第 4 節：特徵以每筆的下單時間計算，模型與 scaler 只從訓練集學 |
| 2.3B 隨機切 | 第 4 節：按下單時間切成整批，訓練段和評估段之間留空檔，整批全部出發後才使用，滑動視窗多次評估 |
| 3.1 Scaler 切分前 fit | 第 4 節：只 fit 訓練集 |
| D1 上線時特徵幾乎是空的 | 第 3 節：平滑、逐層退回、附歷史筆數，不用 `fillna(0)` |
| D2 不在產品清單的編號 | 第 3 節、第 5 節：不算自己的取消率，直接用整體取消率；另外回報上游 |
| 3.2 重複列 | 第 5 節：先依 `order_id` 去重，避免同一筆訂單被重複計數 |
| 4.1 標籤未成熟 | 第 2 節：只用出發日已過的訂單 |

## 7. 值得質疑的地方
- ~~標籤要等出發日~~：使用者定案維持「出發日已過才算結果確定」，不改預測目標，理由見 process-log。
- ~~拿掉 `member_product_cancel_rate`~~：使用者定案保留、改正定義，理由見 process-log。
- ~~平滑的 k 怎麼選~~：使用者定案報告只提出平滑設計，k 不寫死（虛擬碼的 k = 10 僅示意）。
- ~~「結果已確定」用出發日判斷的限制~~：使用者同意在報告寫明：這份資料的狀態和出發日沒有關聯（第 2 節）；正式環境若有取消時間欄位，已取消的單可改用「取消時間 < as_of」提早算進歷史；但未取消的單仍要等出發日過了才確定，兩邊算進歷史的時間不對稱，會讓歷史取消率偏高，要一併處理。本資料沒有取消時間欄位，只有 `updated_at`（最後一次更新時間），未查證它能否當取消時間。
- **替代方案：存活分析（使用者同意簡單提到）**：本設計要等訂單出發才有標籤，還沒出發的訂單完全不能用。存活分析（例如離散時間版，本質上仍是 logistic regression）把還沒出發的訂單當成「到今天為止還沒取消」的設限資料一起訓練，特徵與時間切分原則照用；前提是要有每張訂單的取消時間，本資料沒有，所以列為正式環境的升級方向。細節與來源見 `alternative-designs.md`。

## 附錄 A：查詢與輸出
用專案 `.venv/bin/python -I`，在 `candidate_package/dataset/` 執行。

**A-1 出發日已過的訂單有多少**
```python
import pandas as pd
b=pd.read_csv("orders_base.csv")
c=pd.to_datetime(b.order_created_at,format="mixed",utc=True).dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
d=pd.to_datetime(b.departure_date)
print("departure range",d.min().date(),d.max().date())
print("lead days median",(d-c.dt.normalize()).dt.days.median())
for cut in ["2026-06-01","2026-06-16","2026-07-01"]:
    m=d<cut
    print(cut,"orders departed before:",m.sum(),"created in", c[m].min().date(),"~",c[m].max().date())
m=d<"2026-07-01"
print(b[m].order_status.value_counts().to_dict())
```
```
departure range 2026-05-08 2026-10-27
lead days median 63.0
2026-06-01 orders departed before: 4331 created in 2026-05-01 ~ 2026-05-24
2026-06-16 orders departed before: 11197 created in 2026-05-01 ~ 2026-06-08
2026-07-01 orders departed before: 21501 created in 2026-05-01 ~ 2026-06-23
{'paid': 9234, 'completed': 6156, 'cancelled': 3057, 'created': 3054}
```
