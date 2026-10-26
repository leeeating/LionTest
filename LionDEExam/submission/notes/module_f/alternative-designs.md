# 模組 F：標籤延遲的替代設計

〔AI 研究，待使用者確認〕回答「除了修正設計（`fix-design-draft.md`）之外，這類模型還有哪些設計方法」。取捨一律用方法機制說明，不用題目資料集的數字當論據。每個結論附來源（見附錄 A）；沒有來源直接支持的推測標「未證實」並寫依據。

## 目錄
1. [問題重述：我們的設計在付什麼代價](#1-問題重述我們的設計在付什麼代價)
2. [固定觀察窗標籤](#2-固定觀察窗標籤)
3. [存活分析](#3-存活分析)
4. [快照式預測](#4-快照式預測)
5. [延遲回饋建模](#5-延遲回饋建模)
6. [其他做法](#6-其他做法)
7. [比較表與建議](#7-比較表與建議)
8. [值得質疑的地方](#8-值得質疑的地方)
- [附錄 A：來源清單](#附錄-a來源清單)

## 1. 問題重述：我們的設計在付什麼代價
- **我們的設計**：標籤＝出發前是否取消；只用「整批都已出發」的訂單訓練與評估；切分以模擬部署日 D 為界，中間留至少「最長下單到出發天數」的空檔。
- **兩個代價**：
  1. **資料變舊**：最新的一段訂單（最長可達最長提前天數）永遠還不能用，取消行為若在變（concept drift），模型會慢半拍。
  2. **丟掉部分資訊**：還沒出發的訂單裡，「已經取消」的那些其實結果已經確定，「還沒取消、已撐了 X 天」也是資訊，我們全部捨棄。
- **這個問題在文獻裡的名字**：廣告領域叫 delayed feedback，並明確把它框成「**標籤準確度 vs. 資料新鮮度**」的取捨（ES-DFM 論文原話：「there is a trade-off between waiting for more accurate labels and utilizing fresh data」）〔A6〕。統計領域則是 **右設限（right censoring）**：只知道「到目前為止還沒發生」〔A1〕。
- **我們的情境比廣告簡單的一點**：取消有硬截止（出發日），過了就確定是 0。廣告轉換沒有這種截止，所以廣告方法花很多力氣在「這個負樣本到底是不是真的負」；我們只在出發前有這個不確定。這點會影響第 5 節方法的適用性（推論，依據是兩者標籤定義的差異）。

## 2. 固定觀察窗標籤
**ELI5**：不等到出發日，改問「下單後 N 天內有沒有取消」。N 天一到，答案就確定。

**怎麼處理延遲**：把標籤延遲從「下單到出發天數（每筆不同、最長很長）」換成固定的 N 天。廣告業的 conversion window 就是這個做法：Google Ads 只記錄互動後 N 天內的轉換（預設 30 天），窗外的轉換不計〔A10〕。

**相比我們的設計**
- 好處：標籤延遲固定且可以選短，資料新鮮很多；切分的空檔只要 N 天。
- 代價：
  - **問的問題變了**。業務真正要的是「最後會不會取消」，這個標籤只回答「前 N 天會不會取消」，N 天後才取消的訂單被標成 0。如果取消集中在接近出發日（例如免費取消期限前），N 小時會漏掉大部分取消（未證實：取消時間分布要實際查資料才知道，這裡只是說明機制）。
  - **提前天數短於 N 的訂單**，觀察窗還沒滿就出發了，它的標籤其實是「出發前取消」，和其他訂單不同義，要另外處理（剔除或另設定義）。
- 補救：可以用多個窗（7、30、90 天）各訓練一個模型，但這等於在手工逼近第 3 節的存活曲線。

**適用情境**：業務問題本身就是「短期內」的（例如「這週要不要打電話挽留」），或結果大多在下單後很快發生。旅遊訂單若多數取消發生在接近出發日，這個方法和業務問題對不上。

## 3. 存活分析
**ELI5**：不再問「會不會取消」（是非題），改問「取消會在什麼時候發生」。還沒出發的訂單不丟掉，而是記成「到今天為止還沒取消」，模型照樣從它學到東西。

**怎麼處理延遲**：把還沒出發、也還沒取消的訂單當成**右設限**資料。lifelines 文件說明，設限個體「我們只知道它目前的存活時間」，若直接丟掉它們只留有發生事件的，會嚴重低估真正的存活時間；把設限時間當成事件時間也一樣有偏〔A1〕。scikit-survival 把它定義成「訓練資料有一部分只能被部分觀察到」的迴歸問題〔A2〕。對應到我們：直接丟掉未出發訂單（我們的做法）不會偏，因為我們是整批丟；但「只留未出發訂單裡已取消的」就會偏（見 6.4 的反例）。

**在我們情境怎麼設定（AI 設計，未證實可行，需要取消發生時間欄位）**
- 時間軸用「距出發還有幾天」倒數。事件＝取消；出發日過了沒取消＝走完全程、沒有事件。
- 每筆訂單從「下單時的提前天數」進入觀察，這是**延遲進入（left truncation）**，lifelines `CoxPHFitter.fit` 的 `entry_col` 參數就是用來處理它〔A3〕。
- 還沒出發的訂單：觀察到今天、沒取消，記為設限。
- 預測「這筆最後會不會取消」＝1 減去「撐到出發日」的機率；對已經撐了一段時間的訂單，lifelines 的 `predict_survival_function(..., conditional_after=...)` 可以算「已經存活這麼久之後」的條件機率〔A3〕。
- 也可以用**離散時間存活分析**：把每筆訂單拆成「每一段時間一列」（person-period），每列標「這段內有沒有取消」，用普通的 logistic regression 或 GBDT 訓練；Singer & Willett 證明這樣的最大概似估計可以直接用標準 logistic regression 軟體擬合〔A5〕。這對熟 sklearn 的人最好上手。

**相比我們的設計**
- 好處：
  - 未出發訂單也能用，資料比較新，也比較多。
  - 一次得到整條取消機率曲線，可以回答「出發前 30 天內取消的機率」這種問題。
- 代價：
  - **需要取消發生的時間**，不只是「有沒有取消」。
  - **設限要和風險無關**（non-informative censoring）：設限的原因是「日曆還沒走到」，這通常和個別訂單的取消風險無關，所以假設大致成立；但如果取消行為隨時間在變，近期訂單（設限比例高）和舊訂單的風險本來就不同，這時設限和風險有關（未證實：這是存活分析教科書的標準假設，本次查的 lifelines、scikit-survival 頁面沒有直接寫出這條，依據是設限機制的推論）。
  - **評估要換指標**：一般的 AUC 不能直接處理設限。scikit-survival 提供 `cumulative_dynamic_auc`（時間相依 AUC，評估「到時間 t 前是否發生」的區分能力）、Uno 的 IPCW C-index（設限多時比 Harrell C-index 不偏）、time-dependent Brier score〔A4〕。
  - **時間點正確的規則依然要守**：Cox 的時變共變數版本（`CoxTimeVaryingFitter`）文件明說預測「不簡單」，因為未來的共變數值未知〔A3b〕。特徵仍要照我們的第 3 節原則，只用預測時已知的值。
  - **時間切分依然要做**：存活分析解的是「標籤沒成熟」，不是「拿未來評估過去」。D 之前訓練、D 之後評估的原則不變，只是空檔可以縮短（訓練段尾端的訂單以設限身分進來）。

**適用情境**：提前天數長、取消行為會漂移、有取消時間戳。這是學術上處理「結果還沒揭曉」最標準的框架。

## 4. 快照式預測
**ELI5**：一筆訂單不是只在下單時預測一次，而是在「出發前 90 天、60 天、30 天、7 天」各拍一張快照，每張快照用當時已知的資訊預測「從現在到出發會不會取消」。

**文獻上的名字**：統計領域的 **landmarking**（van Houwelingen 2007）：在選定的時間點（landmark），只取當時仍在風險中的個體，預測之後一段固定期間內的結果〔A7〕。

**怎麼處理延遲**：快照本身不縮短標籤延遲（「出發前會不會取消」還是要等到出發）。但它有兩個效果：
- 越接近出發的快照，標籤越快成熟（出發前 7 天的快照只要等 7 天），所以「近出發」的模型可以用很新的資料。
- 和第 3 節的離散時間存活分析是同一件事的兩種說法：快照標籤若改成「到下一張快照前會不會取消」，就是 person-period 資料〔A5〕〔A7〕（推論：兩者資料形狀相同，差別只在標籤是「到出發前」還是「到下一段前」）。

**相比我們的設計**
- 好處：
  - **貼近實際用法**：上線時特徵表每天更新，同一筆訂單每天都會被重新評分；訓練資料若只有「下單當下」那一列，模型沒看過「出發前 10 天、還沒取消」的樣子（推論）。
  - 可以用動態特徵：距出發天數、下單後是否改過單、會員最近是否取消別的單。
- 代價：
  - 資料量乘上快照數；同一筆訂單的多列高度相關，切分必須按訂單分組（或照時間切），不然又會洩漏。
  - 每張快照都要時間點正確的特徵，特徵表要能回溯「當時」的值。這正好是我們第 1 節原則 4（特徵函式吃「現在時間」參數）已經具備的能力。
  - 評估要按快照分層看，否則近出發的簡單快照會拉高整體分數（推論）。

**適用情境**：業務需要在訂單生命週期中多次介入（例如出發前分階段挽留、超賣決策）。

## 5. 延遲回饋建模
**ELI5**：廣告點擊後的轉換可能晚幾週才出現。這類方法讓模型一邊用「還沒轉換」的新資料訓練，一邊估計「這些暫時的 0 裡有多少之後會變 1」，再把偏差修掉。

**代表做法**
- **DFM（Chapelle 2014）**：同時學兩個模型，一個預測「最終會不會轉換」，一個預測「轉換要多久」（假設延遲是指數分布），還沒轉換的樣本依「已經過了多久」貢獻概似〔A8〕〔A6〕。本質上是一種存活分析（cure model 形式）（推論，依據是它的概似結構）。
- **Fake negative 加權（Ktena 等 2019，Twitter）**：每個樣本一進來先當負樣本訓練，之後轉換了再複製一份當正樣本；用重要性加權或事後校正 p = b / (1 − b) 把偏差修回來〔A9〕。
- **Feedback shift 重要性加權（Yasui 等 2020）**：把「訓練時標籤分布和上線不同」當成分布偏移，用 importance weighting 校正〔A11〕。
- **ES-DFM（Yang 等 2021，阿里巴巴）**：等一段「經過時間」才給標籤，再用兩個輔助分類器估重要性權重，在準確度與新鮮度之間取平衡〔A6〕。

**相比我們的設計**
- 好處：資料最新，適合持續訓練（continuous training）。
- 代價：
  - 為「每秒大量樣本的串流」設計，要串流訓練管線、輔助模型、加權邏輯，工程成本高；Ktena 等論文專門討論了各方法在正式環境的工程成本〔A9〕。
  - 大部分方法假設「晚到的正樣本終究會被看到」，並用延遲分布或輔助模型猜還沒到的部分，猜錯就有偏差。
  - **我們的情境有硬截止**（出發日），負樣本會被確定；廣告方法最大的難處（負樣本永遠無法確定）在我們這裡不存在。直接用第 3 節的存活分析更簡單、假設更少（推論，依據同第 1 節最後一點）。

**適用情境**：每天新樣本量大、行為漂移快、可以接受複雜訓練管線的團隊。每天凌晨批次更新的旅遊訂單模型，用它屬於殺雞用牛刀（推論）。

## 6. 其他做法
### 6.1 線上學習（online learning）
**ELI5**：模型不定期整批重訓，而是每來一筆有標籤的資料就小幅更新一次。

- 代表：Google 的 FTRL-Proximal 用於廣告點擊預測〔A12〕；概念漂移的調適策略見 Gama 等的綜述〔A13〕。
- **它不解決標籤延遲**：線上學習只決定「拿到標籤後多快更新」，標籤本身還是要等出發日；要提早用資料仍得搭配第 5 節的加權方法。
- 適用：漂移快、資料量大。對每天批次更新的系統，定期重訓（我們的滑動視窗）已經涵蓋大部分好處（推論）。

### 6.2 用部分成熟的資料加權
**ELI5**：還沒出發的訂單也拿來用，但依「它的標籤有多可靠」給權重。

- 第 5 節的重要性加權〔A9〕〔A11〕〔A6〕就是這一類；存活分析評估時的 IPCW（依設限機率反向加權）也是同樣的想法〔A4〕。
- 另一個相近的框架是 **PU learning**（只有正樣本和未標記樣本）：Elkan & Noto 證明，若有標記的正樣本是隨機選的，用「正 vs. 未標記」訓練出的機率只和真實機率差一個常數倍〔A14〕。未出發訂單中「已取消＝確定的正」「未取消＝未標記」，形狀很像，但「哪些取消已被觀察到」取決於提前天數與經過時間，不是隨機的，前提不成立（推論）。

### 6.3 遷移校正（re-calibration）
- 用舊資料（成熟）訓練排序能力，再用近期部分資料只校正機率水準。這是業界常見做法，但本次沒找到權威來源描述它在標籤延遲下的性質（未證實）。

### 6.4 反例：只保留未出發訂單中已取消的
- 一個實際上線的飯店取消預測系統（Antonio 等 2019）每天用「全部在帳訂單」重訓，剔除未到店也未取消的訂單，但**未來入住日的已取消訂單仍保留**；論文自己承認這讓未來日期的樣本只有取消，類別嚴重失衡〔A15〕。
- 這正是第 3 節 lifelines 文件說的「只留發生事件的個體」型偏差〔A1〕：近期訂單在訓練資料中會被高估取消率。我們的設計整批等待出發，避開了這個坑；若要改用未出發訂單，應該用存活分析的設限方式，而不是這樣挑樣本。
- 該系統另外有兩個值得參考的設計：依訂單新舊加權（較新的權重較高），以及 challenger 要在最近七天平均勝過 champion 才換上線〔A15〕。

## 7. 比較表與建議
| 方法 | 能用未出發訂單 | 標籤延遲 | 回答的問題 | 額外需求 | 工程複雜度 | 適合我們嗎 |
|---|---|---|---|---|---|---|
| 我們的設計（等整批出發） | 不能 | 最長提前天數 | 出發前會不會取消 | 無 | 低 | 基準 |
| 固定觀察窗 | 部分（滿 N 天的） | N 天 | 下單後 N 天內會不會取消（和業務問題不同） | 短提前天數訂單另行處理 | 低 | 只在業務問題本身是短期時 |
| 存活分析（含離散時間版） | 能（當設限） | 不必等，設限即可用 | 何時取消、出發前取消機率 | 取消時間戳、設限無資訊假設、換評估指標 | 中 | **最直接的替代** |
| 快照式／landmarking | 能（近出發快照很快成熟） | 依快照到出發的距離 | 從這個時間點到出發會不會取消 | 每張快照時間點正確的特徵、按訂單分組切分 | 中 | 業務要多次評分時 |
| 延遲回饋建模 | 能 | 幾乎沒有 | 最終會不會取消 | 串流管線、延遲分布或輔助模型 | 高 | 不適合每日批次 |
| 線上學習 | 不能（單獨用時） | 不變 | 同基準 | 增量訓練框架 | 中到高 | 不解決延遲 |
| PU／部分成熟加權 | 能 | 幾乎沒有 | 同基準 | 前提（隨機標記）在這裡不成立 | 中 | 不建議 |

**建議在報告「修正設計」提一句：存活分析（離散時間版）。**〔待使用者確認〕
- **它直接回應我們設計自己寫出的代價**（未出發訂單不能用、資料偏舊），而且是處理「結果還沒揭曉」最標準、有成熟套件（lifelines、scikit-survival）的框架〔A1〕〔A2〕〔A4〕。
- **它和我們的設計相容**：時間點正確的特徵、按時間切分都照用，只是標籤從是非題換成「到某時為止取消了沒」。面談被追問時，可以說清楚「改了什麼、沒改什麼」。
- **離散時間版只要 logistic regression**〔A5〕，不用換工具鏈，也自然接到快照式預測。
- 不建議提延遲回饋建模：它的核心難題（負樣本永遠無法確認）在有出發日截止的情境不存在，提了反而要解釋為什麼不用。
- 參考句型（草稿）：「若要用上尚未出發的訂單、讓模型更即時，可改用存活分析，把尚未出發的訂單當作右設限資料；代價是需要取消時間戳，且評估要改用時間相依 AUC 等設限感知指標。」

## 8. 值得質疑的地方
- **「取消只在出發前發生」是使用者定案**，存活分析的時間軸設定建立在它上面；若有出發後的取消或退款紀錄，時間軸要重想。
- **取消時間欄位**：本研究沒查資料集是否有可靠的取消時間戳；沒有的話，存活分析與快照式都無法做。
- **設限無資訊假設**在概念漂移下可能不成立（第 3 節），這也是我們「等整批出發」設計反而比較保守、比較穩的理由之一。
- **第 1 節「我們的情境比廣告簡單」** 是 AI 的推論，沒有文獻直接比較這兩種情境。
- 第 6.3 的遷移校正沒有找到權威來源。

## 附錄 A：來源清單
- 〔A1〕lifelines 文件，Introduction to survival analysis，「Censoring」一節：https://lifelines.readthedocs.io/en/latest/Survival%20Analysis%20intro.html
- 〔A2〕scikit-survival 文件，Introduction to Survival Analysis：https://scikit-survival.readthedocs.io/en/stable/user_guide/00-introduction.html
- 〔A3〕lifelines 文件，CoxPHFitter（`entry_col`、`conditional_after`）：https://lifelines.readthedocs.io/en/latest/fitters/regression/CoxPHFitter.html
- 〔A3b〕lifelines 文件，Time varying survival regression：https://lifelines.readthedocs.io/en/latest/Time%20varying%20survival%20regression.html
- 〔A4〕scikit-survival 文件，Evaluating Survival Models（Uno IPCW C-index、`cumulative_dynamic_auc`、Brier score）：https://scikit-survival.readthedocs.io/en/stable/user_guide/evaluating-survival-models.html
- 〔A5〕Singer, J. D. & Willett, J. B. (1993). It's About Time: Using Discrete-Time Survival Analysis to Study Duration and the Timing of Events. *Journal of Educational and Behavioral Statistics* 18(2), 155–195. https://ideas.repec.org/a/sae/jedbes/v18y1993i2p155-195.html
- 〔A6〕Yang, J.-Q. et al. (2021). Capturing Delayed Feedback in Conversion Rate Prediction via Elapsed-Time Sampling (ES-DFM). AAAI 2021. https://arxiv.org/abs/2012.03245
- 〔A7〕van Houwelingen, H. C. (2007). Dynamic Prediction by Landmarking in Event History Analysis. *Scandinavian Journal of Statistics* 34, 70–85. 方法概述見 https://link.springer.com/article/10.1007/s10985-008-9099-8
- 〔A8〕Chapelle, O. (2014). Modeling Delayed Feedback in Display Advertising. KDD 2014. https://doi.org/10.1145/2623330.2623634 （本次未能取得全文；內容依摘要與 〔A6〕 的轉述）
- 〔A9〕Ktena, S. I. et al. (2019). Addressing Delayed Feedback for Continuous Training with Neural Networks in CTR prediction. RecSys 2019. https://arxiv.org/abs/1907.06558
- 〔A10〕Google Ads 說明，About conversion windows：https://support.google.com/google-ads/answer/3123169?hl=en
- 〔A11〕Yasui, S. et al. (2020). A Feedback Shift Correction in Predicting Conversion Rates under Delayed Feedback. WWW 2020. https://arxiv.org/abs/2002.02068
- 〔A12〕McMahan, H. B. et al. (2013). Ad Click Prediction: a View from the Trenches. KDD 2013. https://research.google/pubs/ad-click-prediction-a-view-from-the-trenches/
- 〔A13〕Gama, J. et al. (2014). A Survey on Concept Drift Adaptation. *ACM Computing Surveys* 46(4). https://doi.org/10.1145/2523813
- 〔A14〕Elkan, C. & Noto, K. (2008). Learning Classifiers from Only Positive and Unlabeled Data. KDD 2008. https://members.cbio.mines-paristech.fr/~jvert/svn/bibli/local/Elkan2008Learning.pdf
- 〔A15〕Antonio, N., de Almeida, A. & Nunes, L. (2019). An Automated Machine Learning Based Decision Support System to Predict Hotel Booking Cancellations. *Data Science Journal* 18(1). https://doi.org/10.5334/dsj-2019-032
