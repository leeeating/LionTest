# 模組 F：特徵管線除錯報告

診斷對象：`candidate_package/module_F/churn_training_pipeline.py`（訂單取消預測的特徵與訓練管線）。

## 目錄
0. [模組選擇說明](#0-模組選擇說明)
1. [摘要](#1-摘要)
2. [背景](#2-背景)
   - 2.1 [題目與管線](#21-題目與管線)
   - 2.2 [名詞](#22-名詞)
   - 2.3 [數字的適用範圍](#23-數字的適用範圍)
3. [診斷報告](#3-診斷報告)
   - 3.1 [member_product_cancel_rate 含自己的標籤](#31-member_product_cancel_rate-含自己的標籤)
   - 3.2 [其餘三個歷史特徵用到未來資料](#32-其餘三個歷史特徵用到未來資料)
   - 3.3 [先算特徵、後切分](#33-先算特徵後切分)
   - 3.4 [隨機切分，不是按時間切分](#34-隨機切分不是按時間切分)
   - 3.5 [上線時查不到歷史的特徵被補成 0](#35-上線時查不到歷史的特徵被補成-0)
   - 3.6 [不在產品清單的產品編號](#36-不在產品清單的產品編號)
   - 3.7 [次要問題](#37-次要問題)
4. [修正設計](#4-修正設計)
   - 4.1 [四條原則](#41-四條原則)
   - 4.2 [標籤定義](#42-標籤定義)
   - 4.3 [特徵計算](#43-特徵計算)
   - 4.4 [資料切分與評估](#44-資料切分與評估)
   - 4.5 [虛擬碼](#45-虛擬碼)
   - 4.6 [問題與修法對照](#46-問題與修法對照)
   - 4.7 [已知限制與升級方向](#47-已知限制與升級方向)
5. [防再犯機制](#5-防再犯機制)
   - 5.1 [防線一：答案打亂測試](#51-防線一答案打亂測試)
   - 5.2 [防線二：影子測試與上線監控](#52-防線二影子測試與上線監控)
   - 5.3 [擋得住哪一類問題](#53-擋得住哪一類問題)
6. [驗證方法與限制](#6-驗證方法與限制)
- [附錄 A：執行環境與共用程式碼](#附錄-a執行環境與共用程式碼)
- [附錄 B：會員與產品組數、會員訂單數、重複列](#附錄-b會員與產品組數會員訂單數重複列)
- [附錄 C：單一特徵 AUC 與特徵等於標籤的比例](#附錄-c單一特徵-auc-與特徵等於標籤的比例)
- [附錄 D：重現原管線與移除特徵](#附錄-d重現原管線與移除特徵)
- [附錄 E：排除自己、只用之前下的單、按時間切分後的特徵與覆蓋率](#附錄-e排除自己只用之前下的單按時間切分後的特徵與覆蓋率)
- [附錄 F：不在產品清單的產品編號](#附錄-f不在產品清單的產品編號)
- [附錄 G：出發日已過的訂單](#附錄-g出發日已過的訂單)

## 0. 模組選擇說明

選擇 F，是因為我認為它比較接近 MLE 的工作，而我碩士就是在做設計與改善 ML 模型。若要排序，第二個會選 D，因為可以接觸到更多軟體上的技術。E 排在最後，因為我認為它的評判可以用最近推出的決策模型 Jev 來幫忙，相關技術也可能在 agent 的發展中被弱化。

## 1. 摘要

離線 AUC 虛高的主因是特徵本身含有答案：三個取消率特徵用整段期間、連同這筆訂單自己的標籤一起計算，其中 `member_product_cancel_rate` 按會員與產品組合分組，組內筆數越少越接近標籤，只有一筆時就等於標籤。在這份資料上，95.9% 的列所在的組合只有一筆訂單，98.99% 的列上這個特徵等於標籤（附錄 B、C），僅作佐證。評估方式也錯了：先用全部資料算特徵、再隨機切分，測試集的標籤與未來的訂單都混進了特徵。上線時這些資訊都不存在，查不到歷史的特徵被補成 0，這是離線時每一列都查得到值、從沒被補過的值，模型因此失效。修正設計以「時間點正確」為核心：歷史特徵只用下單當天之前的訂單計算，其中取消率只用結果已確定的訂單，標籤等出發日過了才算確定，評估改成按下單時間整批切分並留空檔。防再犯在 CI 加「答案打亂測試」擋住特徵含答案，上線前後用影子測試與監控當最後防線。

## 2. 背景

### 2.1 題目與管線

DS 團隊的訂單取消預測模型，離線測試 AUC 0.9 以上，上線兩週只剩約 0.55，業務端已停用。DS 確認演算法與超參數沒有問題，請資料工程師診斷特徵管線。

管線依序執行三個函式：

1. `load_orders`：讀 `orders_base.csv`，丟掉金額、下單時間、出發日解析失敗的列；標籤是 `df["label"] = (df["order_status"] == "cancelled").astype(int)`。
2. `build_features`：算 8 個特徵。四個來自統計：`member_order_cnt`、`member_cancel_rate`、`member_product_cancel_rate`、`product_cancel_rate`；四個是訂單本身的欄位：`amount`、`quantity`、`coupon_discount`、`days_to_departure`。
3. `train`：`StandardScaler` 標準化後，`train_test_split` 隨機切 75% 訓練、25% 測試，訓練 `LogisticRegression`，印出 AUC 與係數。

### 2.2 名詞

- **AUC**：隨機挑一張取消的單和一張沒取消的單，模型給取消那張較高分的機率。0.5 等於亂猜。
- **資料洩漏（data leakage）**：訓練或評估時，特徵含有預測當下不可能知道的資訊，例如結果本身，或預測時間點之後才發生的事。
- **target encoding**：把類別欄位（會員、產品）換成這個類別的標籤平均值，例如產品取消率。計算時若含這筆自己的標籤，或用到未來的資料，就會洩漏。
- **時間點正確（point-in-time）**：每筆訂單的特徵只用「下單那一刻已經知道的事」計算。

### 2.3 數字的適用範圍

題目的資料是合成資料，只有兩個月。本報告的結論分兩類：

- **機制結論**：特徵含自己的標籤、用到未來資料、先算特徵後切分、隨機切而非按時間切。這些從程式碼就能證明，換資料也成立，是本報告的主軸。
- **量級結論**：各特徵的 AUC、覆蓋率、筆數比例。這些只對這份資料成立，報告中只當佐證，一律標明「在這份資料上」。

AUC 數字來自另一份獨立審查：環境沒有 scikit-learn，改用 numpy 自寫的邏輯迴歸（Newton 法、L2 懲罰 1.0，對應 `LogisticRegression` 預設 `C=1.0`）與 AUC（Mann-Whitney 秩和），**未用 scikit-learn**，隨機切分也和 `train_test_split` 不保證逐列相同（附錄 A）。

## 3. 診斷報告

| # | 問題 | 定位 |
|---|---|---|
| 3.1 | `member_product_cancel_rate` 含自己的標籤，組內筆數越少越接近標籤 | 主因 |
| 3.2 | `member_cancel_rate`、`product_cancel_rate`、`member_order_cnt` 用到未來資料 | 主因 |
| 3.3 | 先算特徵、後切分 | 主因（評估方式） |
| 3.4 | 隨機切分，不是按時間切分 | 主因（評估方式） |
| 3.5 | 上線時查不到歷史的特徵被補成 0 | 主因（上線端） |
| 3.6 | 只有一筆訂單的產品，產品取消率等於標籤（在這份資料上的實例：不在產品清單的編號） | 主因（機制同 3.1；上游資料問題） |
| 3.7 | `StandardScaler` 在切分前 fit；重複列 | 次要 |

3.1、3.2 是特徵定義錯；3.3、3.4 是評估方式錯，就算特徵改對，評估方式不改，離線分數仍會高估。

### 3.1 member_product_cancel_rate 含自己的標籤

- **洩漏機制**：`build_features` 裡 `df.groupby(["member_id", "product_id"]).agg(member_product_cancel_rate=("label", "mean"))` 用全部資料計算，含這筆自己的標籤。一組會員與產品只有一筆訂單時，這組的取消率就是這筆自己的標籤。
- **為什麼離線準**：在這份資料上，97,952 組會員與產品中有 95,891 組只有一筆，佔全部列的 95.9%（附錄 B）；98.99% 的列上特徵值完全等於標籤（附錄 C）。模型等於在抄答案，這也解釋了 DS 看到的「重要性最高」。
- **為什麼上線失效**：新訂單還沒有結果，自己的標籤不存在；同一組會員與產品第一次出現時查不到歷史，特徵被補成 0（見 3.5）。在這份資料上，以 5 月訂單的歷史計算時，6 月訂單只有 2.03% 查得到這個特徵（附錄 E），僅作佐證。
- **怎麼驗證**：機制由程式碼證明。在這份資料上，以自寫模型重現原管線 Test AUC 0.9999，係數 +6.4986，其他特徵都小於 0.1；拿掉這個特徵後降到 0.7275（附錄 D）。

### 3.2 其餘三個歷史特徵用到未來資料

- **洩漏機制**：`build_features` 的 `member_stats = df.groupby("member_id").agg(member_order_cnt=("order_id", "count"), member_cancel_rate=("label", "mean"))` 和 `prod_stats = df.groupby("product_id").agg(product_cancel_rate=("label", "mean"))` 都用整段期間計算，包含這筆訂單之後才發生的訂單。兩個取消率另外含自己的標籤。`member_order_cnt` 不含標籤，但數到了下單之後的訂單，同樣違反「只能用下單之前的資料」。
- **為什麼離線準**：自己的標籤是會員取消率分子的一部分，會員的訂單越少，自己那筆佔的比重越大。在這份資料上，會員訂單數中位數 12，自己的標籤約佔會員取消率的 1/12（附錄 B），僅作佐證。同樣在這份資料上，`member_cancel_rate` 單一特徵 AUC 0.7263，排除自己那筆後是 0.5021；`product_cancel_rate` 是 0.5480，排除自己後是 0.5039（附錄 C、E）。
- **為什麼上線失效**：上線時只有過去的資料，取消率少了自己的標籤與未來的結果；`member_order_cnt` 只數得到過去的訂單，數值比離線偏小，分布和訓練時不同。
- **怎麼驗證**：機制由程式碼證明，數字見上。`member_order_cnt` 不含標籤，洩漏的是未來訂單的筆數而不是答案，所以歸在和取消率同一類的「用到未來資料」，但不會直接抄到標籤；在這份資料上單一特徵 AUC 0.4983（附錄 C），僅作佐證。

### 3.3 先算特徵、後切分

- **洩漏機制**：主程式先呼叫 `build_features(orders)`，再在 `train` 裡呼叫 `train_test_split`。取消率是用全部資料的標籤算的，測試集的標籤已經混進訓練集的特徵，反之亦然。
- **為什麼離線準**：測試集不再是「模型沒看過的資料」，評估的是模型能不能認出已經寫進特徵的答案。
- **為什麼上線失效**：上線時沒有同期或未來的標籤可以混進特徵。
- **怎麼驗證**：機制由呼叫順序證明。在這份資料上，取消率只用 5 月訂單計算、套到 6 月訂單時，三個取消率的單一特徵 AUC 都回到 0.4985～0.5044（附錄 E）。

### 3.4 隨機切分，不是按時間切分

- **洩漏機制**：`train_test_split(X, y, test_size=0.25, random_state=7)` 不看時間。就算 3.3 修好、取消率只用訓練集計算，測試集裡 5/10 的訂單仍會拿到訓練集裡同一會員 6/20 訂單的結果，等於用未來的標籤預測過去（look-ahead）。
- **為什麼離線準**：模型在評估時看得到評估時間點之後的資訊；資料若有時間趨勢，隨機切會把未來的趨勢帶進訓練。
- **為什麼上線失效**：上線永遠是用過去預測未來，拿不到這些資訊。
- **怎麼驗證**：機制由程式碼證明。這份資料無法量出它的影響：在這份資料上，下單當下就拿得到的特徵單一特徵 AUC 都在 0.498～0.505（附錄 C），沒有訊號可以被高估。正式資料若有時間趨勢，隨機切仍會高估，所以列為主因。

### 3.5 上線時查不到歷史的特徵被補成 0

- **洩漏機制**：離線時每一列都查得到三個取消率，因為自己就在分組裡，所以 `train` 裡的 `df[feature_cols].fillna(0)` 實際上從沒作用。上線時新訂單的會員與產品組合若沒有歷史，特徵是空值，照訓練管線的寫法會被補成 0，意思變成「從不取消」。
- **為什麼離線準**：離線看不到這個落差，特徵分布和上線完全不同（training-serving skew）。
- **為什麼上線失效**：權重最大的特徵在離線時從沒被補過 0；上線時查不到歷史的訂單都拿到同一個 0，模型會把它們一律當成「不會取消」，這個特徵失去鑑別力，卻仍主導分數。
- **怎麼驗證**：機制由程式碼證明。在這份資料上，以 5 月訂單的歷史計算時，6 月訂單只有 2.03% 查得到會員與產品的取消率（附錄 E），僅作佐證。上線實際的補值方式看不到線上程式碼，是根據訓練管線的 `fillna(0)` 推論。

### 3.6 不在產品清單的產品編號

- **洩漏機制**：只有一筆訂單的產品，`product_cancel_rate` 只由自己一筆算出，等於自己的標籤；不在產品清單的編號特別容易如此，而且是上游資料問題。在這份資料上，訂單中有 120 個 `product_id` 不在 `products.csv`，每個只有一筆訂單（附錄 F），是這個機制的實例。
- **為什麼離線準**：產品只有自己一筆訂單時，產品取消率就是自己的標籤。在這份資料上，這 120 列的產品取消率 100% 等於標籤（附錄 F）。
- **為什麼上線失效**：上線查不到這些編號的歷史，特徵是空值。
- **怎麼驗證**：附錄 F 的查詢。列為主因的理由是機制和 3.1 相同（特徵由自己的標籤算出），並且是上游資料問題，需要回報；在這份資料上只有 120 列，這個數字僅作佐證。

### 3.7 次要問題

- **`StandardScaler` 在切分前 fit**：`train` 裡 `scaler.fit_transform(X)` 在 `train_test_split` 之前，測試集的平均與標準差混進訓練。和 3.3 原則相同，但漏的是數值尺度、不含標籤。在這份資料上，改成只 fit 訓練集後 Test AUC 仍是 0.9999（附錄 D）。修法：訓練集 `fit_transform`，測試集只 `transform`。
- **重複列**：同一 `order_id` 重複出現時，可能一筆在訓練集、一筆在測試集。列為次要的理由是機制：重複列不含別筆的 label，時間切分加嚴格小於（4.5 的 `created_at < as_of`）之後不會造成洩漏，只會讓計數重複；修法是先依 `order_id` 去重。在這份資料上，有 40 組重複、共 80 列，多出 40 列（約 0.04%），標籤都一致（附錄 B），僅作佐證。

其他檢查過的資料品質問題不屬於離線虛高的原因，細節見 `notes/module_f/blind-review-diff.md`。

## 4. 修正設計

### 4.1 四條原則

1. **時間點正確**：每筆訂單的特徵，只能用下單那一刻已經知道的事。涵蓋排除自己的標籤，也涵蓋不用未來的訂單。
2. **標籤要等結果確定**：還沒到出發日的訂單結果不確定，不拿來訓練或評估。
3. **離線模擬上線**：用過去訓練、用未來評估。as_of = 下單當下已完成的最新一次每日批次的日界線（台北時間 00:00）；訓練用同一條規則。模型參數與標準化參數只從訓練集學。
4. **訓練與上線用同一支特徵函式**：函式吃一個「現在時間」參數，訓練時傳歷史時間點，上線時傳當下時間，避免兩邊各寫一套而算法不一致。

### 4.2 標籤定義

- **標籤**：訂單在出發日之前被取消就是 1，出發日過了沒被取消就是 0。取消只會發生在出發前。
- **為什麼**：`order_status` 是資料擷取當下的狀態，「還沒取消」不等於「不會取消」，近期才下的單結果還不確定。判斷時間點 `t` 時，只有 `departure_date < t` 的訂單有確定的標籤。
- **代價**：標籤的延遲等於下單到出發的天數，最新一段訂單永遠還不能用來訓練。正式環境有數年歷史，這只是讓訓練資料晚一段時間，不影響可行性。在這份資料上，下單到出發中位數 63 天，以 07-01 為準只有 21,501 筆出發日已過（附錄 G），這是資料期間只有兩個月造成的，不能拿來評估設計好壞。
- **這份資料的限制**：這 21,501 筆中有 9,234 筆「已付款」、3,054 筆「已建立」，出發日已過卻沒走到完成（附錄 G）。依定義它們沒被取消、標 0，但狀態語意可疑。

### 4.3 特徵計算

| 原特徵 | 問題 | 修正 |
|---|---|---|
| `member_cancel_rate` | 含自己的標籤、用到未來（3.2） | 只算這位會員在 `t` 之前、結果已確定的訂單 |
| `product_cancel_rate` | 同上（3.2）；不在產品清單的編號（3.6） | 同上；不在產品清單的編號視為未知產品，不算它自己的取消率、直接用整體取消率，並回報上游 |
| `member_product_cancel_rate` | 含自己的標籤，組內筆數越少越接近標籤（3.1）；上線時查不到歷史就被補成 0（3.5） | **保留，改正定義**：只算這位會員在 `t` 之前、結果已確定的同產品訂單，加平滑並附歷史筆數。歷史太少時逐層向較粗的分組靠攏：會員 × 產品 → 會員 × 產品類型 → 會員 → 整體，以上一層的取消率當平滑先驗 |
| `member_order_cnt` | 數到未來的訂單（3.2） | 只數 `t` 之前下的單；不用等結果確定 |
| `amount`、`quantity`、`coupon_discount`、`days_to_departure` | 下單當下就知道 | 不變；`days_to_departure` 以台北時間（Asia/Taipei）的日期計算，和日界線一致 |

保留 `member_product_cancel_rate` 的理由：會員對同一產品的取消傾向在業務上是合理的訊號，錯的是管線的算法，不是特徵本身。

**樣本少的取消率要平滑**：歷史只有一兩筆時，取消率只會是 0、0.5、1 這種極端值，改成向先驗靠攏：

```
平滑取消率 = (取消筆數 + k × 先驗取消率) / (歷史筆數 + k)
```

`k` 是「要幾筆歷史才相信它」，屬於可調參數，本設計不指定數值（虛擬碼的 k = 10 僅示意）。歷史是 0 筆時值等於先驗，而不是 `fillna(0)` 的 0（0 的意思是「從不取消」，反而是很強的訊號）。另外附「歷史筆數」特徵，讓模型區分「真的有同產品歷史」和「只是退回較粗的分組」。

### 4.4 資料切分與評估

- **按下單時間切成整批，模擬在 D 這天部署**：取代隨機切分。訓練集是 D 之前某段下單區間、而且在 D 之前全部出發的訂單；評估集是 D 之後下的單。
- **訓練段和 D 之間留空檔**：空檔至少是最長的下單到出發天數。不留空檔的話，訓練集裡會有評估期間才確定的結果（例如同一段時間的取消潮），模型等於學到評估期間的事。
- **整批全部出發後才使用**：一段區間要等裡面的訂單全部出發，才拿來訓練或評估。不能用「出發日早於切點」篩選樣本：越靠近切點下的單，只剩短天期的能留下，訓練與評估都會偏向短天期訂單，而 `days_to_departure` 本身就是特徵。計算歷史特徵時仍用「出發日早於 as_of」篩選，因為上線時同樣只看得到已出發的歷史，兩邊一致。
- **特徵以每筆的下單日計算**：用同一支函式、以下單當下已完成的最新一次每日批次的日界線（台北時間 00:00）為 as_of，和上線相同；模型與 scaler 只從訓練集學，評估集只 `transform`。
- **滑動視窗**：D 往後滑多次，每次都是「訓練一段、空檔、評估一段」，看結果穩不穩，也模擬定期重新訓練。

### 4.5 虛擬碼

```python
TPE = ZoneInfo("Asia/Taipei")                                   # 日界線一律用台北時間

def build_features(orders, as_of):
    """回傳 as_of 這一刻、每筆訂單可用的特徵。訓練與上線共用。
    orders 已依 order_id 去重，並 join 產品清單取得 product_type（不在清單的為 NULL）。
    as_of 一律是某次每日批次的日界線（台北時間 Asia/Taipei 00:00）：特徵表每日批次以台北時間 00:00 為日界線，
    虛擬碼假設批次在日界線當下就完成（floor_to_day）；實務上若批次較晚完成，改用「下單當下最新完成批次的日界線」，訓練與上線用同一規則。
    訓練和上線必須用同一條日界線。"""
    orders = dedup(orders, key="order_id")                     # 重複送來的同一筆只留一列
    past = orders[orders.created_at < as_of]                    # 只看前一天以前下的單
    settled = past[past.departure_date < as_of.astimezone(TPE).date()]  # 出發日（台北日期）整天過完才算結果確定
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
    f = build_features(orders, as_of=floor_to_day(order.created_at, tz=TPE))  # as_of = 下單當下已完成的最新一次每日批次的日界線（台北時間 00:00）；訓練用同一條規則
    return lookup(f, order) | order_own_fields(order)           # 查不到時：取消率用先驗、歷史筆數與訂單數為 0
                                                                # days_to_departure 以台北時間的日期相減

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
x = features_for(new_order, orders)                             # as_of = 下單當下已完成的最新一次每日批次的日界線（台北時間 00:00）；訓練用同一條規則
```

`features_for` 逐筆計算是為了清楚表達原則；實作時可用依時間排序後的累計計數一次算完，結果相同。

### 4.6 問題與修法對照

| 診斷 | 修法 |
|---|---|
| 3.1 `member_product_cancel_rate` 含自己的標籤 | 4.3：保留，改成時間點正確的定義＋平滑＋逐層退回 |
| 3.2 三個特徵用到未來資料 | 4.1 原則 1；4.5 的 `created_at < as_of` 與 `departure_date < as_of.astimezone(TPE).date()` |
| 3.3 先算特徵、後切分 | 4.1 原則 3、4.4：特徵以每筆的下單日計算，模型與 scaler 只從訓練集學 |
| 3.4 隨機切分 | 4.4：按下單時間整批切分、留空檔、整批出發後才用、滑動視窗 |
| 3.5 上線時查不到歷史的特徵被補成 0 | 4.3：平滑、逐層退回、附歷史筆數，不用 `fillna(0)` |
| 3.6 不在產品清單的編號 | 4.3、4.5：不算自己的取消率，直接用整體取消率；回報上游 |
| 3.7 Scaler 切分前 fit | 4.4：只 fit 訓練集 |
| 3.7 重複列 | 4.5：先依 `order_id` 去重 |

### 4.7 已知限制與升級方向

- **用出發日判斷結果確定**：這份資料沒有取消時間欄位，只有最後狀態。正式環境若有取消時間，已取消的單可以用「取消時間 < as_of」提早算進歷史；但未取消的單仍要等出發日過了才確定，兩邊算進歷史的時間不對稱，會讓歷史取消率偏高，要一併處理。
- **升級方向：存活分析**：本設計要等訂單出發才有標籤。存活分析（例如離散時間版，本質上仍是 logistic regression）可以把還沒出發的訂單當成「到今天為止還沒取消」的設限資料一起訓練，特徵與時間切分原則照用；前提是要有每張訂單的取消時間，本資料沒有，所以列為正式環境的升級方向。

## 5. 防再犯機制

兩道防線：

- **防線一：答案打亂測試**，放在 CI，每次修改特徵管線都自動跑，沒通過就不能合併。專門擋「特徵含有自己的答案」。
- **防線二：影子測試與上線監控**，放在上線前後，是最後一道防線，擋「離線和上線對不上」。

### 5.1 防線一：答案打亂測試

**原理**：把標籤隨機打亂，訂單和答案之間的真實關係就被破壞，正常的特徵預測不了，AUC 應該接近 0.5。如果打亂後 AUC 仍明顯高於 0.5，代表有特徵是用這筆訂單自己的標籤算出來的：打亂後的標籤跟著被算進特徵，特徵照樣猜中。

```python
def test_label_shuffle(orders, pipeline, seeds=range(5)):
    aucs = []
    for seed in seeds:
        shuffled = orders.copy()
        shuffled["label"] = rng(seed).permutation(shuffled["label"])   # 打亂答案
        aucs.append(pipeline.build_train_evaluate(shuffled))           # 特徵、切分、訓練、評估整條重跑
    assert not significantly_above(aucs, 0.5), f"打亂 label 後 AUC 仍偏高：{aucs}，特徵可能含有答案"
```

- **門檻**：檢定打亂後 AUC 的平均是否顯著高於 0.5，不用固定的寬鬆值。
- **成本**：每次 CI 多跑幾次完整流程，資料用固定的抽樣以控制時間。
- **限制**：自己的標籤在特徵裡佔比越小，訊號越弱，越難測出。

### 5.2 防線二：影子測試與上線監控

**影子測試**：新模型接上真實訂單，只預測、不採用，業務照舊。取消的答案要到出發日才揭曉，所以分兩種指標：

- **先行指標（預測當下就有）**：比較線上算出的特徵和離線訓練時的分布、缺值率。例如某個特徵上線時的缺值率和離線不同（本次的 3.5），這裡馬上看得到。
- **結果指標（出發後才有）**：只用出發日已過的訂單計算線上 AUC，避免提早出現的取消單讓結果偏掉，再和離線比較。

**放行**：先行指標沒有異常，結果指標也接近離線，才正式採用。**上線後**持續看這兩種指標，異常就告警或退回舊模型。業務若會依預測去挽留客人，要保留一組不介入的對照組來算結果指標，否則介入本身會改變取消結果。

### 5.3 擋得住哪一類問題

| 問題類型 | 本次的例子 | 防線一 | 防線二 |
|---|---|---|---|
| 特徵含自己的答案 | 3.1、3.2 的取消率 | 擋得住 | 擋得住 |
| 偷看未來 | 3.2 用到別筆訂單的未來結果、3.4 隨機切 | 擋不住：打亂後別筆的答案也亂了 | 擋得住：特徵分布有差就由先行指標發現，否則等結果指標 |
| 訓練與上線算法不一致（和標籤無關） | 訓練和上線各寫一套程式、時區處理不同 | 擋不住 | 擋得住：先行指標 |

3.5 是 3.1 在上線端的症狀，源頭是同一個特徵含自己的答案，所以防線一會透過 3.1 擋下，防線二的先行指標也看得到。

**接受的代價**：偷看未來的問題 CI 擋不到；分布上看不出差異的（例如只有隨機切），要等結果指標，也就是要等訂單出發。

## 6. 驗證方法與限制

**驗證方法**

| 方法 | 用在哪裡 |
|---|---|
| 讀程式碼 | 所有機制結論：特徵怎麼算、呼叫順序、切分方式、補值方式 |
| 資料查詢（pandas） | 組合筆數、特徵等於標籤的比例、覆蓋率、不在產品清單的編號、重複列（附錄 B、C、E、F、G） |
| 自寫模型重現與移除特徵 | numpy 自寫邏輯迴歸與 AUC，未用 scikit-learn；重現原管線、移除特徵、排除自己、按時間切分（附錄 A、C、D、E） |
| 修正設計檢查 | 由獨立審查逐行確認虛擬碼中沒有任何特徵用到下單之後的資訊 |

**限制**

- **沒有用 scikit-learn 實跑**，也沒有做逐一修正每個問題的完整消融實驗；題目允許純閱讀程式碼作答，本報告的主軸是機制結論。AUC 全部來自自寫模型，切分和 `train_test_split` 不保證逐列相同，所以重現的 0.9999 和 DS 回報的「0.9 以上」數字不同、方向一致。
- **數字只對這份合成資料成立**。在這份資料上，下單當下就拿得到的特徵幾乎沒有訊號，所以 3.4 的影響量不出來；這不代表正式資料也是如此，也不能用來推論正式環境的模型水準。
- **上線端的補值方式是推論**：看不到線上程式碼，3.5 是根據訓練管線的 `fillna(0)` 推論。
- **標籤的限制**：沒有取消時間欄位；出發日已過卻仍是「已付款」「已建立」的訂單依定義標 0（4.2、4.7）。

## 附錄 A：執行環境與共用程式碼

附錄 C～F 用專案 `.venv` 的 Python（pandas、numpy），以 `.venv/bin/python -I -W ignore qN.py` 執行，並 import 以下 `common.py`。`load_orders`、`build_features` 照抄原管線；`fit_logreg` 用 Newton 法、L2 懲罰 1.0，對應 scikit-learn `LogisticRegression` 預設 `C=1.0`；`auc` 用 Mann-Whitney 秩和，等同 `roc_auc_score`。隨機切分用 `np.random.RandomState(7).permutation`，和 scikit-learn 的切法不保證逐列相同。

```python
import pandas as pd, numpy as np
D="/Users/liyiting/Documents/OpenSource/LionTest/LionDEExam/candidate_package/dataset/"
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

## 附錄 B：會員與產品組數、會員訂單數、重複列

用專案 `.venv/bin/python -I`，在 `candidate_package/dataset/` 執行。

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

## 附錄 C：單一特徵 AUC 與特徵等於標籤的比例

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

## 附錄 D：重現原管線與移除特徵

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

## 附錄 E：排除自己、只用之前下的單、按時間切分後的特徵與覆蓋率

本附錄三段輸出都沒有過濾出發日已過，和 4.2 的標籤定義不一致，只當佐證，不是修正設計的完整定義。查詢與輸出原樣保留。

- **第一段（留一法）**：佐證取消率排除自己這筆之後，特徵就失去訊號（3.1、3.2）。
- **第二段（只用之前的單）**：輸出標成「時間點正確」，實際上只用之前下的單、排除自己；佐證會員取消率不再含自己的標籤與未來訂單後，訊號跟著消失（3.2）。
- **第三段（5 月到 6 月）**：佐證按時間切分、取消率只用 5 月計算時，三個取消率的訊號消失，並看會員與產品取消率在 6 月訂單上的覆蓋率（3.3、3.5）。

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

## 附錄 F：不在產品清單的產品編號

只保留與產品編號有關的查詢與輸出（3.6）；其他檢查項目的部分已刪除，保留的輸出未改動。

```python
import sys; sys.path.insert(0,"/tmp/mf")
from common import *
df=load_orders()
P=pd.read_csv(D+"products.csv")
pc=df.groupby("product_id").size()
print("products.csv rows",len(P),"unique",P.product_id.nunique(),"| order product_ids",len(pc),"not in products.csv",(~pc.index.isin(P.product_id)).sum())
small=pc[pc<=5]; print("products with <=5 orders",len(small),"rows in them",small.sum(),"their ids sample",list(small.index[:5]))
print("singleton products in products.csv?",small.index.isin(P.product_id).sum())
f,cols=build_features(df)
s=f.product_id.map(pc)==1
print("rows with singleton product: product_cancel_rate==label share",(f.loc[s,"product_cancel_rate"]==f.loc[s,"label"]).mean(), "n",s.sum())
print("product_cancel_rate AUC excl singleton products",round(auc(f.label[~s],f.product_cancel_rate[~s]),4))
```

```text
products.csv rows 300 unique 300 | order product_ids 420 not in products.csv 120
products with <=5 orders 120 rows in them 120 their ids sample ['P91064', 'P91071', 'P91118', 'P91133', 'P91216']
singleton products in products.csv? 0
rows with singleton product: product_cancel_rate==label share 1.0 n 120
product_cancel_rate AUC excl singleton products 0.547
```

## 附錄 G：出發日已過的訂單

用專案 `.venv/bin/python -I`，在 `candidate_package/dataset/` 執行。

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
