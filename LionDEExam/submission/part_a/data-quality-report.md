# A-3 資料品質檢核報告

## 目錄

- [1. 結論](#1-結論)
- [2. 最重要的 5 個問題](#2-最重要的-5-個問題)
- [3. 其他問題](#3-其他問題)
- [4. 三天處理結果](#4-三天處理結果)
- [5. 為正式環境預先準備的處理](#5-為正式環境預先準備的處理)
- [6. 已檢查、沒有問題的項目](#6-已檢查沒有問題的項目)
- [7. 資料本身的限制](#7-資料本身的限制)
- [8. 給上游的建議](#8-給上游的建議)
- [附錄 A：查詢腳本與重跑](#附錄-a查詢腳本與重跑)
- [附錄 B：查詢與輸出](#附錄-b查詢與輸出)
- [附錄 C：問題對照表](#附錄-c問題對照表)
- [附錄 D：決策與原話對照](#附錄-d決策與原話對照)
- [附錄 E：防護性設計清單](#附錄-e防護性設計清單)
- [附錄 F：管線步驟細節](#附錄-f管線步驟細節)
- [附錄 G：名詞表](#附錄-g名詞表)

## 1. 結論

**這份訂單資料可以用來算訂單金額和取消率；其中 40 張金額多了 1,000 倍的訂單照原樣保留在資料裡，但在人工確認之前不計入下游的金額指標。** 這 40 張只佔 5～6 月訂單的 0.04%，卻佔這兩個月訂單金額的 28%。三天後全部訂單的金額總和（折扣前、含所有狀態）是 39,086,896,780.27 台幣，排除這 40 張後是 28,984,405,090.57 台幣，差額 10,102,491,689.70 台幣。另一個風險在每日更新檔：官方說它帶來舊訂單的狀態更新，實際上每天約 600 筆判定為另一張訂單用了同一個編號；若是撞號，照官方說法處理會讓上千張訂單算錯會員、取消率也跟著算錯。這兩類都已處理：金額異常的訂單列進人工確認清單、確認前不計入金額指標，撞號的資料先擋下、不覆蓋原本的訂單；其餘問題也都有處理方式或已記錄，細節如下。

營收怎麼算（要不要含已取消的訂單、用折扣前或折扣後的金額）由後續的報表與指標定義決定，本報告不定義營收，提到金額時一律寫明範圍。

**判斷理由**：這份報告由我撰寫，這套資料處理流程也由我設計。每個問題的“判斷理由”，是我決定處理方式時的理由；正文整理成書面語，逐字紀錄與出處見[附錄 D](#附錄-d決策與原話對照)。

**範圍**：5～6 月的訂單總檔（約 10 萬張），加上 7/1、7/2、7/3 三天的每日更新檔；另有會員資料（04-30、05-31、06-30 三次匯出）、產品清單、匯率表。每個數字都實際查過資料，查詢與輸出在附錄。處理規則依據的業務假設，完整清單見[業務假設](../business-assumptions.md)。

**名詞**：訂單狀態有四種：已建立（created）、已付款（paid）、已完成（completed）、已取消（cancelled）。“計入報表”指寫進給下游報表使用的訂單資料，訂單金額、取消率等指標都從這裡算；“待查清單”指先擋下、不計入報表，保留原樣等人處理；“人工確認清單”指照原樣計入報表資料、但要人看過的訂單，確認之前不計入下游的金額指標。

## 2. 最重要的 5 個問題

**挑選標準是會讓訂單金額、取消率、客戶分析錯多少。** 前兩個影響的規模最大，第 3 個讓“已出團”這類指標不成立，第 4、5 個金額較小，但會直接算錯金額與取消率。

### 2.1 有 40 張訂單的金額多了 1,000 倍

例如訂單 ORD00016881：一個定價 101,000 台幣的行程，買 2 人，金額卻是 249,563,000 台幣（約 2.5 億）。除以 1,000 是 249,563，才是這個行程合理的價位。

**影響**：這 40 張只佔 5～6 月訂單的 0.04%，卻佔 5～6 月總檔計入報表金額（折扣前、含所有狀態）的 **28.09%**。和除以 1,000 修正後的金額（25,877,084,322.08 台幣）相比，照原樣加總的 35,969,473,520.09 台幣會高估約 39.00%（約四成）。

**怎麼處理**：抓得出來，但算不出正確金額，所以不自動修改。抓法是看金額和定價的比例：金額 ÷（定價 × 人數）超過 100 倍就列出來，正常訂單都在約 0.84～1.28 倍之間。原本正確的金額是多少，資料無法自動判斷。所以金額照原樣保留在報表資料裡，另外列進人工確認清單等人確認。判斷理由：金額問題無法用一套規則系統性處理，要逐筆判斷；而且在資料進入處理流程之前，無法有效判斷出問題。

**人工確認之前，這 40 張不計入下游的金額指標。** 判斷理由：前面已經有其他問題的資料進入隔離、等人處理，這 40 張也應該一致處理，人工審查之後再進入下游。三天後的金額總和（折扣前、含所有狀態）排除前是 39,086,896,780.27 台幣，排除後是 28,984,405,090.57 台幣。（查詢見[附錄 C-1](#附錄-c問題對照表)）

**如果真的是多乘了 1,000，修正後大約多少**：這是假設 40 張全部除以 1,000 的估計，實際要等人工確認。5～6 月總檔計入報表的金額（折扣前、含所有狀態）照原樣是 35,969,473,520.09 台幣；40 張除以 1,000 後是 25,877,084,322.08 台幣（5 月 13,052,417,554.32、6 月 12,824,666,767.76）。和直接排除這 40 張的 25,866,981,830.39 只差 10,102,491.69 台幣（約 1,010 萬），所以確認之前先排除，對 5～6 月的金額影響很小。（查詢見[附錄 C-1](#附錄-c問題對照表)）

### 2.2 每天約 600 筆“舊訂單的更新”，判定為另一張訂單撞了號

例如訂單 ORD00005192：5～6 月總檔裡是會員 M007765、10,230.87 美元、已付款；7/1 的更新檔送來同一個編號，卻是會員 M005173、6,927 美元、已完成，下單時間也不同。題目說明每日更新檔除了新訂單，也包含舊訂單的狀態更新；但三天共 1,808 筆和舊訂單對照，會員、金額、下單時間三項都相同的是 0 筆。

**影響**：如果照官方說法當成更新，1,776 張舊訂單會換成別的會員，客戶分析整批算錯人。其中 763 張會變成已取消、118 張已取消的又變回有效。取消率（已取消 ÷ 三天後全部 112,010 張訂單）會從 12.73% 變成 13.31%。

**如果擋下的其實是真的新訂單，少算多少金額**：這 1,808 筆去掉重複送來的，是 1,800 張訂單（同一個編號但會員、金額不同的算兩張；不重複的編號是 1,788 個，其中 12 個編號各帶兩張），金額合計 468,895,127.27 台幣（折扣前、含所有狀態），約佔三天後全部訂單金額總和 39,086,896,780.27 台幣的 1.20%；若以排除待確認清單後的總額 28,984,405,090.57 台幣為分母，約佔 1.62%；其中未取消的 238,270,742.17 台幣。這 1,800 張沒有金額多 1,000 倍的情況。（查詢見[附錄 C-2](#附錄-c問題對照表)）

**怎麼處理**：判定為撞號，先擋下，存到待查清單，不覆蓋原本的訂單。判斷理由：把撞號當成雜訊處理；訂單的基本資訊不能被修改（業務假設 [2.1](../business-assumptions.md#21-訂單的基本資訊不能被修改)）。

**這代表什麼**：更新檔裡和舊訂單同編號的資料全部是撞號，所以三天的更新檔實際上只帶來新訂單，沒有任何一筆舊訂單的狀態更新生效。資料分辨不出上游是不是允許整張訂單被改寫，訂單編號怎麼產生要向上游確認；擋下的資料都保留原樣，規則改變時可以重新處理。（查詢見[附錄 C-2](#附錄-c問題對照表)）

### 2.3 28,578 張訂單在出發前就被標成“已完成”

例如訂單 ORD00000006：狀態是已完成，最後一次更新在 05-17，出發日卻是 07-07，還要 51 天才出團。

**基準是“標成已完成的當下”**。資料只記錄最後一次更新的時間，那時狀態已經是已完成，所以標上已完成的時間不會晚於它。5～6 月總檔計入報表的已完成訂單共 28,578 張，全部是在最後一次更新時出發日還沒到，相差 4～119 天。

**不要誤讀成“這些訂單到現在都還沒出團”**。以 07-01 為基準，這 28,578 張裡有 6,147 張的出發日已經過了，只是它們同樣是在出發前就標成已完成。反過來看，同樣以 07-01 為基準，出發日已過、卻還是已付款的有 9,234 張，還是已建立的有 3,053 張。也就是說，狀態和出發日在資料裡沒有關聯。

**影響**：如果把已完成當成“已出團”去算出團金額或完成率，數字都不成立。這 28,578 張計入報表的金額是 10,324,629,272.48 台幣。

**怎麼處理**：照原樣計入報表，只在本報告記錄。我先假設已完成代表出團完成（業務假設 [1.4](../business-assumptions.md#14-completed-代表出團完成)），定案理由是先把狀態規則定下來，之後比較好處理。看報表時要知道：本資料的已完成不代表已出團。（查詢見[附錄 C-3](#附錄-c問題對照表)）

### 2.4 50 張訂單的金額是負數

例如訂單 ORD00002319：狀態已完成，定價 63,000 的行程買 3 人，金額寫成 -216,020 台幣。拿掉負號就是正常價位；同一個編號也沒有正數的原單，所以不是“原單＋退款沖銷”。

**影響**：50 張合計約 -1,239 萬台幣，混進金額加總會少算。訂單狀態也沒有“退款”這一種，負數金額解釋不了。

**怎麼處理**：資料一進來就檢查，不合格的不收。這 50 張先擋下，存到待查清單，不計入報表。判斷理由：負數金額在資料一進來檢查時就該擋下（業務假設 [3.4](../business-assumptions.md#34-訂單金額一定是正數負數不是退款)）。（查詢見[附錄 C-4](#附錄-c問題對照表)）

### 2.5 25 張已取消的訂單，隔天又收到一筆較早的“已付款”

例如訂單 ORD00100020：7/1 的更新檔送來已取消（發生在 07-04 18:08），7/2 的更新檔才送來已付款（發生在 07-03 12:08）。送到的順序和發生的順序相反。

**影響**：如果照送到的順序處理，這 25 張會從已取消變回已付款，6,154,857.49 台幣會被當成有效訂單，取消率也跟著算錯。

**怎麼處理**：以資料裡記錄的更新時間判斷新舊，較舊的那筆不採用（原樣留存備查，不算在擋下待查的筆數裡），訂單維持已取消。判斷理由：照更新時間判斷，符合“訂單狀態只會往前走”的假設（業務假設 [1.1](../business-assumptions.md#11-訂單流程單向取消後不能恢復)）；晚到的舊事件不該當成狀態改變。（查詢見[附錄 C-5](#附錄-c問題對照表)）

## 3. 其他問題

**其餘問題依業務主題分成五組，大多不影響金額總數，但用報表時要知道。** “只記錄”指照原樣計入報表、只在本報告說明，因為我判斷有些問題記錄下來就好，不需要特別處理。

### 3.1 金額與折扣

| 問題 | 影響多少 | 怎麼處理 | 查詢 |
|---|---|---|---|
| 折扣欄寫 -1，代表“不知道折扣多少” | 300 筆，計入報表 299 筆 | 折扣改成空白、訂單照常計入，不猜折扣值；這些訂單沒有折扣後金額（業務假設 [3.5](../business-assumptions.md#35-coupon-等於--1-代表未知)） | [附錄 C-6](#附錄-c問題對照表) |
| 金額是折扣前還是折扣後，資料看不出來 | 全部訂單 | 定義為折扣前，報表另外提供折扣後金額；我的設計傾向把所有金額都記錄下來（業務假設 [3.1](../business-assumptions.md#31-amount-是折扣前金額)） | [附錄 C-7](#附錄-c問題對照表) |
| 折扣固定台幣，和訂單幣別不一致 | 全部訂單 | 一律當台幣：官方欄位說明寫折扣是台幣，資料也吻合，四種幣別的折扣面額都一樣（0～950、每 50 一級）；若當成訂單本身的幣別，785 筆美元訂單（5～6 月總檔）的折扣會比金額還大（業務假設 [3.8](../business-assumptions.md#38-對照coupon-是-twd)） | [附錄 C-8](#附錄-c問題對照表) |
| 日圓金額帶小數 | 80 筆 | 只記錄；金額大小正常 | [附錄 C-9](#附錄-c問題對照表) |

### 3.2 訂單狀態與時間

| 問題 | 影響多少 | 怎麼處理 | 查詢 |
|---|---|---|---|
| 下單時間有三種寫法（台北時間、國際標準時間、沒標時區） | 6,002 筆不是帶台北時區的標準寫法；其中 1,003 筆若直接讀字面日期會差一天 | 統一換算成台北時間；沒標時區的當台北時間，因為和重複送來的資料、時間先後都對得上（業務假設 [4.1](../business-assumptions.md#41-沒有時區標記的時間是台北時間)） | [附錄 C-10](#附錄-c問題對照表) |
| 6 月的訂單 7/2 才送到 | 60 張，約 1,132 萬台幣 | 照下單日算進 6 月；判斷理由是訂單屬於下單那天，晚到只是傳遞延遲（業務假設 [4.2](../business-assumptions.md#42-晚到的訂單屬於下單那天)）。所以 **6 月的訂單金額在 7/2 之後還會變** | [附錄 C-11](#附錄-c問題對照表) |
| 每日更新檔的資料時間晚於檔名日期 | 每天約七成，最多晚 4 天 | 只記錄；判斷新舊只看資料裡的時間，不看檔名 | [附錄 C-12](#附錄-c問題對照表) |
| 5～6 月總檔裡有 7 月的更新時間 | 2,265 筆 | 只記錄；代表總檔實際是 7/3 之後才匯出 | [附錄 C-13](#附錄-c問題對照表) |

**6 月的金額之後會變多少**：下單日在 6 月的訂單，5～6 月總檔處理完是 49,349 張、16,076,860,250.35 台幣（折扣前、含所有狀態）；7/1 沒有變；7/2 多了晚到的 60 張、11,320,587.24 台幣，變成 49,409 張、16,088,180,837.59 台幣，約增加 0.07%；7/3 沒有變。排除人工確認清單上的訂單後，是從 12,821,411,318.82 變成 12,832,731,906.06。三天裡舊訂單的狀態更新都是撞號、沒有生效，所以 6 月金額的變動全部來自晚到的新訂單。這只是三天的資料，之後還會不會有 6 月的訂單晚到，資料看不出來。（查詢見[附錄 C-11](#附錄-c問題對照表)）

### 3.3 訂單編號與重複資料

| 問題 | 影響多少 | 怎麼處理 | 查詢 |
|---|---|---|---|
| 同一天的更新檔裡，兩張不同訂單用了同一個編號 | 三天共 6 組 12 筆 | 兩筆都先擋下，因為分不出哪一張才是原本的單 | [附錄 C-14](#附錄-c問題對照表) |
| 同一筆訂單被送了兩次，只差幾秒 | 5～6 月總檔 40 組 | 留最新一筆；我判斷這是網路波動造成的重複寫入（業務假設 [2.2](../business-assumptions.md#22-只差幾秒的相同列是網路重送)） | [附錄 C-15](#附錄-c問題對照表) |
| 每日更新檔裡同一筆重送 | 每天 15 組 | 同上，留最新一筆 | [附錄 C-16](#附錄-c問題對照表) |

### 3.4 會員資料

| 問題 | 影響多少 | 怎麼處理 | 查詢 |
|---|---|---|---|
| 同一位會員同一天有兩筆、等級不同 | 30 位 | 取較高等級；我假設會員系統也是這樣運作（業務假設 [5.1](../business-assumptions.md#51-會員系統遇到同日兩筆會取較高等級)） | [附錄 C-17](#附錄-c問題對照表) |
| 城市寫 N/A | 70 人 | 當成空白，不蓋掉已知的真實城市（業務假設 [5.3](../business-assumptions.md#53-na-與-1900-01-01-代表未知假值不能蓋真值)） | [附錄 C-18](#附錄-c問題對照表) |
| 生日寫 1900-01-01（代表不知道） | 80 人 | 當成空白，不蓋掉已知的真實生日（業務假設 [5.3](../business-assumptions.md#53-na-與-1900-01-01-代表未知假值不能蓋真值)） | [附錄 C-19](#附錄-c問題對照表) |
| 真實生日後來被 1900-01-01 蓋掉 | 5 人 | 保留真實生日 | [附錄 C-20](#附錄-c問題對照表) |
| 等級、城市在三次匯出之間改變 | 等級 434 人、城市 376 人 | 保留會員等級的歷史變化，訂單對到下單當時的等級；新等級從看到變化的那次匯出日起算，判斷理由是只記錄確定知道的事（業務假設 [5.2](../business-assumptions.md#52-新版本從觀察到變動的快照日開始)） | [附錄 C-21](#附錄-c問題對照表) |
| 後一次匯出和前一次完全一樣 | 05-31 有 95 筆、06-30 有 91 筆 | 不另存一份歷史（理由是 AI 提出的說法，我採用） | [附錄 C-22](#附錄-c問題對照表) |
| 註冊時未滿 18 歲 | 398 人 | 只記錄；可能是家庭成員或未成年帳號 | [附錄 C-23](#附錄-c問題對照表) |

### 3.5 產品與匯率

| 問題 | 影響多少 | 怎麼處理 | 查詢 |
|---|---|---|---|
| 訂單的產品不在產品清單 | 120 張 | 照常計入，產品記為“未知產品”，保留原本的產品編號；判斷理由是訂單是分析的中心，商品可能隨時間消失，要保留訂單（業務假設 [6.1](../business-assumptions.md#61-商品會隨時間下架消失訂單仍要保留)） | [附錄 C-24](#附錄-c問題對照表) |
| 訂單的產品已下架 | 計入報表 4,747 張 | 只記錄；產品清單只有“目前是否上架”，判斷不了下單時是否已下架 | [附錄 C-25](#附錄-c問題對照表) |
| 同一個產品名稱對應多個產品編號 | 44 個名稱 | 只記錄；用名稱分組統計時要注意 | [附錄 C-26](#附錄-c問題對照表) |
| 幣別寫成 NTD（不是標準代碼） | 200 張，54,561,733 台幣 | 當成台幣計算，原本寫的幣別保留（AI 的建議，我採用；業務假設 [3.2](../business-assumptions.md#32-ntd-就是-twd)） | [附錄 C-27](#附錄-c問題對照表) |

匯率表本來就不列台幣，這是常見設計，**不是錯誤，不算在問題裡**。處理時台幣匯率固定為 1，不會因為對不到匯率而漏掉台幣訂單。（查詢見[附錄 C-28](#附錄-c問題對照表)）

## 4. 三天處理結果

**每一批收到的資料，都等於“計入報表”“擋下待查”“不採用”三者相加，一筆不漏。** 四批都核對過，數字也用另一套查詢獨立重算，結果相同。

| 批次 | 收到 | 計入報表 | 擋下待查 | 不採用 |
|---|---|---|---|---|
| 5～6 月總檔 | 100,040 | 99,950 | 90（負數金額 50、重複 40） | 0 |
| 7/1 更新檔 | 4,615 | 4,000 | 615 | 0 |
| 7/2 更新檔 | 4,700 | 4,060 | 615 | 25（較晚送到的舊事件） |
| 7/3 更新檔 | 4,615 | 4,000 | 615 | 0 |

三天後報表共 112,010 張訂單，折扣前台幣金額合計 39,086,896,780.27，折扣後合計 38,895,390,049.43（都含所有狀態）。人工確認清單上金額多了 1,000 倍的 40 張排除後，折扣前合計 28,984,405,090.57，差額 10,102,491,689.70；人工確認之前，下游的金額指標以排除後為準。（查詢見[附錄 C 的對帳說明](#附錄-c問題對照表)）

## 5. 為正式環境預先準備的處理

**本資料沒有發生、但正式環境可能遇到的狀況，也預先寫好了處理方式。** 例如：產品清單或匯率表有壞資料時整批暫停、什麼都不寫，判斷理由是晚一點進來比錯的資料好，而匯率影響訂單金額、程度較大；訂單狀態往回走（已取消又變已付款）時先擋下；下單當天找不到匯率時先擋下，不拿前一天的代替；訂單對不到會員時先擋下，判斷理由是有未知會員時客戶分析很難做，要有錯誤提醒來修正處理流程（業務假設 [5.5](../business-assumptions.md#55-每張訂單都要對得到會員)）；會員資料本身有壞資料時另外存一份待查清單，不蓋掉這位會員上一次的正確資料。另外在資料表本身加一道最後的檢查，連繞過處理流程直接寫入的資料都擋得住。

這些處理都已經寫進程式，完整清單見[附錄 E](#附錄-e防護性設計清單)。

## 6. 已檢查、沒有問題的項目

**以下檢查都做了，結果都是 0。** 必填欄位空白、格式錯誤；狀態、通路、人數的值不在允許範圍；出發日早於下單日；訂單的會員不在會員資料裡、下單日早於註冊日；產品編號重複、定價不是正數；匯率缺日或重複。（查詢見[附錄 F](#附錄-f管線步驟細節)的“已檢查但沒有問題的項目”）

## 7. 資料本身的限制

**以下是資料本身看不到、處理流程也補不了的事。**

- **會員資料每月只匯出一次**，看不到實際的變動日。變動日到匯出日之間的訂單會對到舊等級。我認為根本解法在上游：會員資料要記錄更新時間。
- **訂單狀態只看得到被送來的那幾次**，中間的狀態可能沒有被送來。
- **時間只到秒**：同一張訂單同一秒出現兩種狀態時，排不出先後。
- **訂單編號不能推時間，也不保證唯一**。
- **金額異常靠金額和定價的比例抓**：沒有定價的 120 張無法檢查；這是從資料反推的規則，如果實際業務允許整單折價或加購，規則就太嚴。

## 8. 給上游的建議

**大部分問題的根本解法在上游系統。** 優先的幾項：

- 會員資料加上變動時間，或另建等級異動紀錄。
- 確認訂單編號怎麼產生、會不會重用；確認更新檔到底是不是舊訂單的更新。
- 寫入端防止同一筆重送。
- 不知道的值用空白，不用 -1、N/A、1900-01-01 這類代號。
- 時間一律帶時區；幣別用國際標準代碼。
- 金額多 1,000 倍的 40 張，請上游查來源（例如單位換算）。

完整建議與每項對應的問題見[附錄 F](#附錄-f管線步驟細節)的“上游改善建議”。

---

## 附錄 A：查詢腳本與重跑

- 腳本：`LionDEExam/submission/part_a/profiling/data_quality_queries.py`
- 重跑（在 repo 根目錄 `LionTest/`）：
  ```bash
  caffeinate -i uv run python -I LionDEExam/submission/part_a/profiling/data_quality_queries.py --skip-pipeline  # 只跑 DuckDB（Q-），約 3 分鐘
  caffeinate -i uv run python -I LionDEExam/submission/part_a/profiling/data_quality_queries.py                  # 再加管線驗證（P-），需要 Spark
  ```
- 輸出格式：每段印 `===== [標籤] 說明`、SQL 原文、`OUTPUT:` 和結果。
- **偵測**（`Q-`）用 DuckDB 直接查 CSV，所有欄位先讀成字串，看得到上游送來的原值。共用的 view 定義在腳本的 `VIEWS`：
  - `orders_all`：四個訂單檔 union，加上 `src`、`batch_date`。
  - `orders_t`：加上換算後的欄位：`co_ts`、`upd_ts`（timestamptz）、`co_date`、`upd_date`（台北日期）、`dep_dt`、`amount_d`、`qty_i`、`coupon_d`，以及下單時間的格式分類 `co_fmt`。
  - `base1`：base 每個 order_id 取 `updated_at` 最新的一列，和管線的去重相同。
  - `orders_ratio`：加上產品定價、下單日匯率和金額比值。
  - `fact_sim`：照管線的規則重算寫進 fact 的列（`Q-POST` 使用）。base 去掉金額不大於 0 的列（V1）、每 id 取最新一列；增量只取 id 不在 base 的列，每 id 取最新一列，因為和 base 同 id 的列全部是撞號（`[Q-J2.overlap]`）。`[Q-POST.totals]` 的各批筆數、amount_twd、net、coupon 轉 NULL、V2 清單、未知產品筆數，都和管線實跑的對帳完全相同。
- **管線驗證**（`P-`）呼叫 `load_base` 與 `load_incremental`（day1～day3），寫到 `/tmp/liontest_a3/wh`（每次重跑前清空），再用 Spark SQL 查 fact、訂單隔離表、會員隔離表、dim_member，讀回 fact 的 Delta CHECK 約束，最後跑排除人工確認清單前後的金額總和（`AMOUNT_EXCLUDING_REVIEW_SQL`）。輸出收在[附錄 B](#附錄-b查詢與輸出)最後，是 2026-10-26 對 HEAD 9f9d415 的管線完整執行一次的結果（含 `Q-` 段）。dim_member 已經沒有“未知會員”（-1）列，所以 `P-MEM.*` 不再排除 `member_sk = -1`；`member_sk` 是 `xxhash64(member_id, valid_from)`，本來就可能是負數，檢查“未知會員”列要比 `= -1`，不能比 `< 0`。各批對帳數字和 part_a/README.md“三天實跑的對帳”、`[Q-POST.totals]` 相同。
- **J2 的對帳拆解**：`collision_existing` 比 J2 的列數少，是因為管線先處理同一批內的撞號與去重，再和既有 fact 比對。day1 的 603 = 594（`collision_existing`）+ 6（J3 的 6 列，id 都在 base，先以 `collision` 隔離）+ 3（N1 重送組裡 id 在 base 的 3 組，各有 1 列先以 `duplicate` 隔離）。day2：598 + 2 + 2 = 602；day3：596 + 4 + 3 = 603。重送組 id 在 base 的組數見 `[Q-INC.samefile]` 的 `groups_id_in_base`。
- **和 `notes/part_a/schema-inference/` 的差異**：NTD、TWD 比值的分位數（V4），本報告用 DuckDB `quantile_cont`（精確），notes 用 Spark `percentile_approx`（近似），p50 在小數第 3 位有差異（NTD 1.0353 對 1.0347）。L9 的城市變動 376 人含 `N/A`，排除後是 367 人，notes 只列 376。L11 從 185 更正為 186：舊查詢用中文字串排序同一天的兩列等級，不是業務順序；改成先照 V8 取較高等級再比較。其餘數字一致。

## 附錄 B：查詢與輸出

以下是報告引用的每個 `Q-` 查詢的 SQL 原文與輸出，2026-10-19 執行 `--skip-pipeline` 的原樣結果；`[Q-V9.na_before_real]`、`[Q-J2.blocked_amount]`、`[Q-V2.div1000_estimate]`、`[Q-L3.june_change]` 是 2026-10-26 新增（最後三段接在 `Q-` 的最後）。2026-10-26 完整執行一次（含 `P-` 段），`Q-` 的輸出和 2026-10-19 相同。管線驗證（`P-`）的 SQL 與輸出接在 `Q-` 之後。

### [Q-000.rows] 全部：檔案列數、BOM 是否被略過

```sql
SELECT src, count(*) AS n_rows, count(DISTINCT order_id) AS n_ids FROM orders_all GROUP BY src ORDER BY src
```

| src | n_rows | n_ids |
|---|---|---|
| base | 100040 | 100000 |
| day1 | 4615 | 4597 |
| day2 | 4700 | 4684 |
| day3 | 4615 | 4598 |

### [Q-001.contract] 全部：列層級合約違規（空值、型別、時間格式）

```sql
SELECT src,
  sum(CASE WHEN order_id IS NULL OR trim(order_id) = '' OR member_id IS NULL OR trim(member_id) = ''
            OR product_id IS NULL OR trim(product_id) = '' OR amount IS NULL OR updated_at IS NULL THEN 1 ELSE 0 END) AS required_blank,
  sum(CASE WHEN NOT regexp_full_match(quantity, '[+-]?\d+') THEN 1 ELSE 0 END) AS qty_not_int,
  sum(CASE WHEN NOT regexp_full_match(amount, '[+-]?\d+(\.\d{1,2})?') THEN 1 ELSE 0 END) AS amount_bad_or_gt2dp,
  sum(CASE WHEN NOT regexp_full_match(coupon_discount, '[+-]?\d+(\.\d{1,2})?') THEN 1 ELSE 0 END) AS coupon_bad,
  sum(CASE WHEN co_ts IS NULL THEN 1 ELSE 0 END) AS created_unparseable,
  sum(CASE WHEN upd_ts IS NULL THEN 1 ELSE 0 END) AS updated_unparseable,
  sum(CASE WHEN departure_date IS NOT NULL AND dep_dt IS NULL THEN 1 ELSE 0 END) AS departure_bad
FROM orders_t GROUP BY src ORDER BY src
```

| src | required_blank | qty_not_int | amount_bad_or_gt2dp | coupon_bad | created_unparseable | updated_unparseable | departure_bad |
|---|---|---|---|---|---|---|---|
| base | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| day1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| day2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| day3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

### [Q-002.domains] 全部：狀態、通路、幣別的值域

```sql
SELECT src, list_sort(list(DISTINCT order_status)) AS statuses, list_sort(list(DISTINCT channel)) AS channels,
  list_sort(list(DISTINCT currency)) AS currencies, min(qty_i) AS qty_min, max(qty_i) AS qty_max
FROM orders_t GROUP BY src ORDER BY src
```

| src | statuses | channels | currencies | qty_min | qty_max |
|---|---|---|---|---|---|
| base | ['cancelled', 'completed', 'created', 'paid'] | ['app', 'web', '門市', '電銷'] | ['JPY', 'NTD', 'TWD', 'USD'] | 1 | 4 |
| day1 | ['cancelled', 'completed', 'created', 'paid'] | ['app', 'web', '門市', '電銷'] | ['JPY', 'TWD', 'USD'] | 1 | 4 |
| day2 | ['cancelled', 'completed', 'created', 'paid'] | ['app', 'web', '門市', '電銷'] | ['JPY', 'TWD', 'USD'] | 1 | 4 |
| day3 | ['cancelled', 'completed', 'created', 'paid'] | ['app', 'web', '門市', '電銷'] | ['JPY', 'TWD', 'USD'] | 1 | 4 |

### [Q-V7.groups] V7：base 同 order_id 多列

```sql
WITH g AS (
  SELECT order_id, count(*) AS c,
    count(DISTINCT member_id) AS d_mem, count(DISTINCT amount) AS d_amt, count(DISTINCT co_ts) AS d_co_instant,
    count(DISTINCT order_created_at) AS d_co_raw, count(DISTINCT order_status) AS d_status,
    count(DISTINCT concat_ws('|', product_id, channel, quantity, currency, coupon_discount, departure_date)) AS d_other,
    date_diff('second', min(upd_ts), max(upd_ts)) AS gap_s
  FROM orders_t WHERE src = 'base' GROUP BY order_id HAVING count(*) > 1)
SELECT count(*) AS n_groups, sum(c) - count(*) AS extra_rows,
  sum(CASE WHEN d_mem = 1 AND d_amt = 1 AND d_co_instant = 1 AND d_status = 1 AND d_other = 1 THEN 1 ELSE 0 END) AS identical_except_updated_at,
  sum(CASE WHEN d_co_raw > 1 THEN 1 ELSE 0 END) AS created_same_instant_diff_format,
  min(gap_s) AS gap_s_min, max(gap_s) AS gap_s_max
FROM g
```

| n_groups | extra_rows | identical_except_updated_at | created_same_instant_diff_format | gap_s_min | gap_s_max |
|---|---|---|---|---|---|
| 40 | 40 | 40 | 8 | 2 | 29 |

### [Q-V7.examples] V7：範例

```sql
SELECT order_id, order_created_at, order_status, amount, updated_at FROM orders_t
WHERE src = 'base' AND order_id IN ('ORD00000984', 'ORD00012637', 'ORD00013776') ORDER BY order_id, upd_ts
```

| order_id | order_created_at | order_status | amount | updated_at |
|---|---|---|---|---|
| ORD00000984 | 2026-05-12T03:23:52+08:00 | completed | 152295.0 | 2026-05-12T07:02:52+08:00 |
| ORD00000984 | 2026-05-12T03:23:52+08:00 | completed | 152295.0 | 2026-05-12T07:03:06+08:00 |
| ORD00012637 | 2026-06-14T19:17:51+08:00 | completed | 86020.0 | 2026-06-15T09:27:51+08:00 |
| ORD00012637 | 2026-06-14T11:17:51Z | completed | 86020.0 | 2026-06-15T09:28:10+08:00 |
| ORD00013776 | 2026-05-24T19:26:43+08:00 | cancelled | 187978.0 | 2026-05-27T04:28:43+08:00 |
| ORD00013776 | 2026/05/24 19:26:43 | cancelled | 187978.0 | 2026-05-27T04:28:59+08:00 |

### [Q-INC.samefile] J3 與同狀態重送：增量同檔同 order_id 多列的分類

```sql
WITH g AS (
  SELECT src, order_id, count(*) AS c,
    count(DISTINCT member_id) AS d_mem, count(DISTINCT amount) AS d_amt, count(DISTINCT co_ts) AS d_co,
    count(DISTINCT order_status) AS d_status,
    count(DISTINCT concat_ws('|', product_id, channel, quantity, currency, coupon_discount, departure_date)) AS d_other,
    bool_or(order_id IN (SELECT order_id FROM base1)) AS id_in_base
  FROM orders_t WHERE src <> 'base' GROUP BY src, order_id HAVING count(*) > 1)
SELECT src,
  CASE WHEN d_mem > 1 OR d_amt > 1 OR d_co > 1 THEN 'collision(J3)'
       WHEN d_status = 1 AND d_other = 1 THEN 'resend_identical_except_updated_at'
       ELSE 'status_or_other_changed' END AS kind,
  count(*) AS n_groups, sum(c) AS n_rows, sum(CASE WHEN id_in_base THEN 1 ELSE 0 END) AS groups_id_in_base
FROM g GROUP BY ALL ORDER BY src, kind
```

| src | kind | n_groups | n_rows | groups_id_in_base |
|---|---|---|---|---|
| day1 | collision(J3) | 3 | 6 | 3 |
| day1 | resend_identical_except_updated_at | 15 | 30 | 3 |
| day2 | collision(J3) | 1 | 2 | 1 |
| day2 | resend_identical_except_updated_at | 15 | 30 | 2 |
| day3 | collision(J3) | 2 | 4 | 2 |
| day3 | resend_identical_except_updated_at | 15 | 30 | 3 |

### [Q-J2.overlap] J2：增量列與 base 同 order_id（base 先每 id 取一列）

```sql
SELECT i.src, count(*) AS rows_overlap, count(DISTINCT i.order_id) AS ids_overlap,
  sum(CASE WHEN i.member_id = b.member_id THEN 1 ELSE 0 END) AS same_member,
  sum(CASE WHEN i.amount_d = b.amount_d THEN 1 ELSE 0 END) AS same_amount,
  sum(CASE WHEN i.co_ts = b.co_ts THEN 1 ELSE 0 END) AS same_created,
  sum(CASE WHEN i.member_id = b.member_id AND i.amount_d = b.amount_d AND i.co_ts = b.co_ts THEN 1 ELSE 0 END) AS all_three_same,
  sum(CASE WHEN i.upd_ts > b.upd_ts THEN 1 ELSE 0 END) AS inc_newer_than_base,
  list_sort(list(DISTINCT i.order_status)) AS inc_statuses
FROM orders_t i JOIN base1 b USING (order_id) WHERE i.src <> 'base' GROUP BY i.src ORDER BY i.src
```

| src | rows_overlap | ids_overlap | same_member | same_amount | same_created | all_three_same | inc_newer_than_base | inc_statuses |
|---|---|---|---|---|---|---|---|---|
| day1 | 603 | 597 | 0 | 0 | 0 | 0 | 593 | ['cancelled', 'completed'] |
| day2 | 602 | 599 | 0 | 0 | 0 | 0 | 600 | ['cancelled', 'completed'] |
| day3 | 603 | 598 | 0 | 0 | 0 | 0 | 603 | ['cancelled', 'completed'] |

### [Q-J2.example] J2：範例

```sql
SELECT src, order_id, member_id, product_id, currency, amount, order_status, order_created_at FROM orders_t
WHERE order_id = 'ORD00005192' ORDER BY src
```

| src | order_id | member_id | product_id | currency | amount | order_status | order_created_at |
|---|---|---|---|---|---|---|---|
| base | ORD00005192 | M007765 | P00240 | USD | 10230.87 | paid | 2026-05-06T19:07:47+08:00 |
| day1 | ORD00005192 | M005173 | P00040 | USD | 6927.0 | completed | 2026-05-04T08:52:43+08:00 |
| day1 | ORD00005192 | M005173 | P00040 | USD | 6927.0 | completed | 2026-05-04T08:52:43+08:00 |

### [Q-L4.cross_day] L4：跨增量檔同 order_id（不在 base）的狀態與先後

```sql
WITH x AS (
  SELECT a.src AS src_a, b.src AS src_b, a.order_id, a.order_status AS status_a, b.order_status AS status_b,
    a.member_id = b.member_id AND a.amount_d = b.amount_d AND a.co_ts = b.co_ts AS same_order,
    CASE WHEN b.upd_ts > a.upd_ts THEN 'later_file_newer' ELSE 'later_file_older' END AS order_vs_file,
    a.order_id IN (SELECT order_id FROM base1) AS id_in_base
  FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src < b.src
  WHERE a.src <> 'base' AND b.src <> 'base')
SELECT src_a, src_b, id_in_base, same_order, status_a, status_b, order_vs_file, count(*) AS n
FROM x GROUP BY ALL ORDER BY ALL
```

| src_a | src_b | id_in_base | same_order | status_a | status_b | order_vs_file | n |
|---|---|---|---|---|---|---|---|
| day1 | day2 | False | True | cancelled | paid | later_file_older | 25 |
| day1 | day3 | True | False | cancelled | cancelled | later_file_newer | 2 |
| day1 | day3 | True | False | cancelled | completed | later_file_newer | 1 |
| day1 | day3 | True | False | completed | cancelled | later_file_newer | 1 |
| day1 | day3 | True | False | completed | completed | later_file_newer | 1 |
| day2 | day3 | True | False | cancelled | completed | later_file_newer | 1 |

### [Q-L4.example] L4：範例

```sql
SELECT src, order_id, order_status, updated_at FROM orders_t WHERE order_id = 'ORD00100020' ORDER BY src
```

| src | order_id | order_status | updated_at |
|---|---|---|---|
| day1 | ORD00100020 | cancelled | 2026-07-04T18:08:26+08:00 |
| day2 | ORD00100020 | paid | 2026-07-03T12:08:26+08:00 |

### [Q-L4.day2_upd_dates] L4：day2 那 25 列較舊事件的 updated_at（台北日期）分布

```sql
SELECT b.upd_date, count(*) AS n
FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src = 'day1' AND b.src = 'day2'
WHERE a.order_id NOT IN (SELECT order_id FROM base1) AND b.upd_ts < a.upd_ts
GROUP BY ROLLUP (b.upd_date) ORDER BY 1 NULLS LAST
```

| upd_date | n |
|---|---|
| 2026-07-01 | 6 |
| 2026-07-02 | 7 |
| 2026-07-03 | 8 |
| 2026-07-04 | 4 |
| NULL | 25 |

### [Q-V5.formats] V5：下單時間格式

```sql
SELECT src, co_fmt, count(*) AS n, min(order_created_at) AS example_min, max(order_created_at) AS example_max
FROM orders_t GROUP BY src, co_fmt ORDER BY src, co_fmt
```

| src | co_fmt | n | example_min | example_max |
|---|---|---|---|---|
| base | iso_Z | 3001 | 2026-04-30T17:04:32Z | 2026-06-30T14:55:11Z |
| base | plus0800 | 94038 | 2026-05-01T00:01:46+08:00 | 2026-06-30T23:58:39+08:00 |
| base | slash_no_tz | 3001 | 2026/05/01 01:02:46 | 2026/06/30 23:50:30 |
| day1 | plus0800 | 4615 | 2026-05-01T00:21:17+08:00 | 2026-07-01T23:58:41+08:00 |
| day2 | plus0800 | 4700 | 2026-05-01T00:19:21+08:00 | 2026-07-02T23:58:27+08:00 |
| day3 | plus0800 | 4615 | 2026-05-01T03:23:51+08:00 | 2026-07-03T23:58:03+08:00 |

### [Q-V5.tz_evidence_dup] V5：V7 重複組中格式不同的兩列，解析後是否同一時刻

```sql
WITH p AS (
  SELECT a.order_id, a.co_fmt AS fmt_a, b.co_fmt AS fmt_b, a.order_created_at AS raw_a, b.order_created_at AS raw_b,
    date_diff('second', a.co_ts, b.co_ts) / 3600.0 AS diff_hours
  FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id AND a.src = 'base' AND b.src = 'base'
   AND a.co_fmt = 'plus0800' AND b.co_fmt <> 'plus0800')
SELECT fmt_b, count(*) AS n_groups, min(diff_hours) AS min_diff_h, max(diff_hours) AS max_diff_h, min(raw_a) AS ex_a, min(raw_b) AS ex_b
FROM p GROUP BY fmt_b ORDER BY fmt_b
```

| fmt_b | n_groups | min_diff_h | max_diff_h | ex_a | ex_b |
|---|---|---|---|---|---|
| iso_Z | 5 | 0.0 | 0.0 | 2026-05-21T17:12:03+08:00 | 2026-05-21T09:12:03Z |
| slash_no_tz | 3 | 0.0 | 0.0 | 2026-05-10T09:16:10+08:00 | 2026/05/10 09:16:10 |

### [Q-V5.tz_evidence_order] V5：無標記格式若當 UTC，會有幾筆 updated_at 早於下單時間

```sql
SELECT co_fmt,
  sum(CASE WHEN upd_ts < co_ts THEN 1 ELSE 0 END) AS upd_before_created_as_taipei,
  sum(CASE WHEN co_fmt = 'slash_no_tz' AND upd_ts < co_ts + INTERVAL 8 HOUR THEN 1 ELSE 0 END) AS upd_before_created_if_utc
FROM orders_t WHERE src = 'base' GROUP BY co_fmt ORDER BY co_fmt
```

| co_fmt | upd_before_created_as_taipei | upd_before_created_if_utc |
|---|---|---|
| iso_Z | 0 | 0 |
| plus0800 | 0 | 0 |
| slash_no_tz | 0 | 384 |

### [Q-V5.z_before_0501] V5：Z 格式字面日期早於 05-01、照 UTC 換算後早於 05-01

```sql
SELECT sum(CASE WHEN left(order_created_at, 10) < '2026-05-01' THEN 1 ELSE 0 END) AS raw_date_before_0501,
  sum(CASE WHEN co_date < DATE '2026-05-01' THEN 1 ELSE 0 END) AS taipei_date_before_0501
FROM orders_t WHERE src = 'base' AND co_fmt = 'iso_Z'
```

| raw_date_before_0501 | taipei_date_before_0501 |
|---|---|
| 13 | 0 |

### [Q-V5.z_date_shift] V5：Z 格式若直接取字串前 10 碼當日期，和台北日期不同的列數

```sql
SELECT count(*) AS z_rows,
  sum(CASE WHEN left(order_created_at, 10) <> strftime(co_date, '%Y-%m-%d') THEN 1 ELSE 0 END) AS raw_date_differs_from_taipei_date
FROM orders_t WHERE src = 'base' AND co_fmt = 'iso_Z'
```

| z_rows | raw_date_differs_from_taipei_date |
|---|---|
| 3001 | 1003 |

### [Q-L1.upd_after_batch] L1：增量 updated_at（台北日期）相對批次日

```sql
SELECT src, count(*) AS n,
  sum(CASE WHEN upd_date > batch_date THEN 1 ELSE 0 END) AS upd_after_batch,
  sum(CASE WHEN upd_date < batch_date THEN 1 ELSE 0 END) AS upd_before_batch,
  max(upd_date - batch_date) AS max_days_after
FROM orders_t WHERE src <> 'base' GROUP BY src ORDER BY src
```

| src | n | upd_after_batch | upd_before_batch | max_days_after |
|---|---|---|---|---|
| day1 | 4615 | 3290 | 0 | 4 |
| day2 | 4700 | 3257 | 6 | 3 |
| day3 | 4615 | 3263 | 0 | 3 |

### [Q-L2.base_upd_after_period] L2：base 的 updated_at 落在 07-01 以後

```sql
SELECT upd_date, count(*) AS n FROM orders_t WHERE src = 'base' AND upd_date >= DATE '2026-07-01'
GROUP BY ALL UNION ALL SELECT NULL, count(*) FROM orders_t WHERE src = 'base' AND upd_date >= DATE '2026-07-01' ORDER BY 1 NULLS LAST
```

| upd_date | n |
|---|---|
| 2026-07-01 | 1308 |
| 2026-07-02 | 759 |
| 2026-07-03 | 198 |
| NULL | 2265 |

### [Q-L3.late_new_orders] L3：增量中不在 base、也不在更早增量檔，但下單日早於批次日的新單

```sql
SELECT o.src, count(*) AS n_rows, min(o.order_id) AS id_min, max(o.order_id) AS id_max, min(o.co_date) AS co_min, max(o.co_date) AS co_max
FROM orders_t o
WHERE o.src <> 'base' AND o.co_date < o.batch_date
  AND o.order_id NOT IN (SELECT order_id FROM base1)
  AND NOT EXISTS (SELECT 1 FROM orders_t e WHERE e.order_id = o.order_id AND e.src <> 'base' AND e.src < o.src)
GROUP BY o.src ORDER BY o.src
```

| src | n_rows | id_min | id_max | co_min | co_max |
|---|---|---|---|---|---|
| day2 | 60 | ORD00112001 | ORD00112060 | 2026-06-10 | 2026-06-23 |

### [Q-L3.detail] L3：60 張晚到新單的狀態、updated_at、是否在其他檔出現、出發日已過才付款

```sql
WITH l3 AS (
  SELECT * FROM orders_t o
  WHERE o.src = 'day2' AND o.co_date < o.batch_date AND o.order_id NOT IN (SELECT order_id FROM base1)
    AND NOT EXISTS (SELECT 1 FROM orders_t e WHERE e.order_id = o.order_id AND e.src <> 'base' AND e.src < o.src))
SELECT count(*) AS n_rows, count(DISTINCT order_id) AS n_ids, list_sort(list(DISTINCT order_status)) AS statuses,
  min(upd_date) AS upd_min, max(upd_date) AS upd_max,
  (SELECT count(*) FROM orders_t x WHERE x.order_id IN (SELECT order_id FROM l3) AND x.src <> 'day2') AS rows_in_other_files,
  sum(CASE WHEN dep_dt < upd_date THEN 1 ELSE 0 END) AS paid_after_departure
FROM l3
```

| n_rows | n_ids | statuses | upd_min | upd_max | rows_in_other_files | paid_after_departure |
|---|---|---|---|---|---|---|
| 60 | 60 | ['paid'] | 2026-07-02 | 2026-07-02 | 0 | 5 |

### [Q-L3.paid_after_departure] L3：出發日已過才付款的列

```sql
SELECT order_id, order_status, co_date, upd_date, dep_dt FROM orders_t o
WHERE o.src = 'day2' AND o.co_date < o.batch_date AND o.order_id NOT IN (SELECT order_id FROM base1)
  AND dep_dt < upd_date ORDER BY order_id
```

| order_id | order_status | co_date | upd_date | dep_dt |
|---|---|---|---|---|
| ORD00112030 | paid | 2026-06-21 | 2026-07-02 | 2026-06-28 |
| ORD00112039 | paid | 2026-06-13 | 2026-07-02 | 2026-06-30 |
| ORD00112043 | paid | 2026-06-23 | 2026-07-02 | 2026-06-30 |
| ORD00112047 | paid | 2026-06-17 | 2026-07-02 | 2026-06-30 |
| ORD00112053 | paid | 2026-06-11 | 2026-07-02 | 2026-06-29 |

### [Q-L10.completed_before_departure] L10：completed 但出發日晚於 updated_at（台北日期）

```sql
SELECT src, sum(CASE WHEN order_status = 'completed' THEN 1 ELSE 0 END) AS completed_rows,
  sum(CASE WHEN order_status = 'completed' AND dep_dt > upd_date THEN 1 ELSE 0 END) AS completed_departure_not_reached,
  min(CASE WHEN order_status = 'completed' THEN dep_dt - upd_date END) AS min_days_to_departure,
  max(CASE WHEN order_status = 'completed' THEN dep_dt - upd_date END) AS max_days_to_departure
FROM orders_t GROUP BY src ORDER BY src
```

| src | completed_rows | completed_departure_not_reached | min_days_to_departure | max_days_to_departure |
|---|---|---|---|---|
| base | 28612 | 28612 | 4 | 119 |
| day1 | 321 | 255 | -49 | 112 |
| day2 | 313 | 232 | -44 | 115 |
| day3 | 289 | 220 | -55 | 109 |

### [Q-L10.incremental_split] L10：增量檔的 completed 是否都是與 base 撞號的列

```sql
SELECT src, order_id IN (SELECT order_id FROM base1) AS id_in_base, count(*) AS completed_rows,
  sum(CASE WHEN dep_dt > upd_date THEN 1 ELSE 0 END) AS departure_not_reached
FROM orders_t WHERE src <> 'base' AND order_status = 'completed' GROUP BY ALL ORDER BY ALL
```

| src | id_in_base | completed_rows | departure_not_reached |
|---|---|---|---|
| day1 | True | 321 | 255 |
| day2 | True | 313 | 232 |
| day3 | True | 289 | 220 |

### [Q-L10.after_dedupe] L10：base 每 id 取 updated_at 最新一列後（＝進 fact 的列）

```sql
SELECT count(*) AS fact_candidate_rows,
  sum(CASE WHEN order_status = 'completed' AND dep_dt > upd_date THEN 1 ELSE 0 END) AS completed_departure_not_reached
FROM base1
```

| fact_candidate_rows | completed_departure_not_reached |
|---|---|
| 100000 | 28596 |

### [Q-L10.reverse] L10 反向證據：base 每 id 一列，各狀態中出發日早於 07-01 的筆數與比例；出發日不晚於最後更新日的筆數

```sql
SELECT order_status, count(*) AS n,
  sum(CASE WHEN dep_dt < DATE '2026-07-01' THEN 1 ELSE 0 END) AS departure_before_0701,
  round(100.0 * sum(CASE WHEN dep_dt < DATE '2026-07-01' THEN 1 ELSE 0 END) / count(*), 1) AS pct,
  sum(CASE WHEN dep_dt <= upd_date THEN 1 ELSE 0 END) AS departure_on_or_before_last_update
FROM base1 GROUP BY order_status ORDER BY order_status
```

| order_status | n | departure_before_0701 | pct | departure_on_or_before_last_update |
|---|---|---|---|---|
| cancelled | 14241 | 3056 | 21.5 | 0 |
| completed | 28596 | 6149 | 21.5 | 0 |
| created | 14282 | 3053 | 21.4 | 0 |
| paid | 42881 | 9234 | 21.5 | 0 |

### [Q-NEW.departure_before_order] 新檢查：出發日早於下單日、updated_at 早於下單時間

```sql
SELECT src, sum(CASE WHEN dep_dt < co_date THEN 1 ELSE 0 END) AS departure_before_order_date,
  sum(CASE WHEN upd_ts < co_ts THEN 1 ELSE 0 END) AS updated_before_created,
  min(dep_dt - co_date) AS min_days_order_to_departure
FROM orders_t GROUP BY src ORDER BY src
```

| src | departure_before_order_date | updated_before_created | min_days_order_to_departure |
|---|---|---|---|
| base | 0 | 0 | 7 |
| day1 | 0 | 0 | 7 |
| day2 | 0 | 0 | 7 |
| day3 | 0 | 0 | 7 |

### [Q-AMT.ratio_buckets] V1、V2、V6：金額比值分組（只列非 normal）

```sql
SELECT src, currency, CASE WHEN ratio IS NULL THEN 'no_ratio'
         WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative_abs_normal'
         WHEN ratio < 0 THEN 'negative_other'
         WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
         WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about_x1000'
         ELSE 'other_outlier' END AS bucket, count(*) AS n
FROM orders_ratio GROUP BY 1, 2, 3 HAVING bucket <> 'normal' ORDER BY src, bucket, currency
```

| src | currency | bucket | n |
|---|---|---|---|
| base | JPY | about_x1000 | 4 |
| base | TWD | about_x1000 | 27 |
| base | USD | about_x1000 | 9 |
| base | JPY | negative_abs_normal | 4 |
| base | TWD | negative_abs_normal | 29 |
| base | USD | negative_abs_normal | 17 |
| base | JPY | no_ratio | 21 |
| base | TWD | no_ratio | 76 |
| base | USD | no_ratio | 23 |

### [Q-AMT.ratio_range] 比值規則：正常列的比值範圍（依來源×幣別）

```sql
SELECT src, currency, count(*) AS n, round(min(ratio), 4) AS min_r, round(max(ratio), 4) AS max_r
FROM orders_ratio WHERE CASE WHEN ratio IS NULL THEN 'no_ratio'
         WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative_abs_normal'
         WHEN ratio < 0 THEN 'negative_other'
         WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
         WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about_x1000'
         ELSE 'other_outlier' END = 'normal' GROUP BY ALL ORDER BY src, currency
```

| src | currency | n | min_r | max_r |
|---|---|---|---|---|
| base | JPY | 10993 | 0.8449 | 1.2839 |
| base | NTD | 200 | 0.8512 | 1.2448 |
| base | TWD | 66558 | 0.85 | 1.25 |
| base | USD | 22079 | 0.8378 | 1.2489 |
| day1 | JPY | 524 | 0.8462 | 1.2613 |
| day1 | TWD | 3069 | 0.8501 | 1.2498 |
| day1 | USD | 1022 | 0.8398 | 1.2398 |
| day2 | JPY | 531 | 0.8462 | 1.2681 |
| day2 | TWD | 3150 | 0.8501 | 1.2499 |
| day2 | USD | 1019 | 0.8426 | 1.2383 |
| day3 | JPY | 521 | 0.8472 | 1.2678 |
| day3 | TWD | 3141 | 0.8501 | 1.25 |
| day3 | USD | 953 | 0.8406 | 1.2464 |

### [Q-V1.negative] V1：負數金額

```sql
SELECT src, currency, count(*) AS n_negative,
  sum(CASE WHEN EXISTS (SELECT 1 FROM orders_t p WHERE p.order_id = o.order_id AND p.amount_d > 0) THEN 1 ELSE 0 END) AS same_id_has_positive_row,
  list_sort(list(DISTINCT order_status)) AS statuses
FROM orders_t o WHERE amount_d < 0 GROUP BY ALL ORDER BY src, currency
```

| src | currency | n_negative | same_id_has_positive_row | statuses |
|---|---|---|---|---|
| base | JPY | 4 | 0 | ['completed', 'paid'] |
| base | TWD | 29 | 0 | ['cancelled', 'completed', 'created', 'paid'] |
| base | USD | 17 | 0 | ['cancelled', 'completed', 'created', 'paid'] |

### [Q-V1.examples] V1：範例

```sql
SELECT order_id, order_status, currency, amount, quantity, bp, round(ratio, 4) AS ratio FROM orders_ratio
WHERE src = 'base' AND amount_d < 0 ORDER BY order_id LIMIT 3
```

| order_id | order_status | currency | amount | quantity | bp | ratio |
|---|---|---|---|---|---|---|
| ORD00000900 | cancelled | TWD | -172833.0 | 1 | 170000.00 | -1.0167 |
| ORD00002319 | completed | TWD | -216020.0 | 3 | 63000.00 | -1.143 |
| ORD00002817 | completed | TWD | -26515.0 | 1 | 30000.00 | -0.8838 |

### [Q-V2.x1000_detail] V2：疑似 ×1000 是否為 1000 的倍數

```sql
SELECT currency, count(*) AS n, sum(CASE WHEN amount_d % 1000 = 0 THEN 1 ELSE 0 END) AS multiple_of_1000,
  sum(CASE WHEN amount_d % 10 = 0 THEN 1 ELSE 0 END) AS multiple_of_10,
  round(min(ratio / 1000), 4) AS min_ratio_div1000, round(max(ratio / 1000), 4) AS max_ratio_div1000
FROM orders_ratio WHERE CASE WHEN ratio IS NULL THEN 'no_ratio'
         WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative_abs_normal'
         WHEN ratio < 0 THEN 'negative_other'
         WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
         WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about_x1000'
         ELSE 'other_outlier' END = 'about_x1000' GROUP BY currency ORDER BY currency
```

| currency | n | multiple_of_1000 | multiple_of_10 | min_ratio_div1000 | max_ratio_div1000 |
|---|---|---|---|---|---|
| JPY | 4 | 4 | 4 | 0.8787 | 1.2125 |
| TWD | 27 | 27 | 27 | 0.8529 | 1.2355 |
| USD | 9 | 0 | 9 | 0.9456 | 1.2343 |

### [Q-V2.examples] V2：範例

```sql
SELECT order_id, currency, amount, quantity, bp, round(ratio, 1) AS ratio FROM orders_ratio
WHERE CASE WHEN ratio IS NULL THEN 'no_ratio'
         WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative_abs_normal'
         WHEN ratio < 0 THEN 'negative_other'
         WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
         WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about_x1000'
         ELSE 'other_outlier' END = 'about_x1000' ORDER BY ratio DESC LIMIT 3
```

| order_id | currency | amount | quantity | bp | ratio |
|---|---|---|---|---|---|
| ORD00016881 | TWD | 249563000.0 | 2 | 101000.00 | 1235.5 |
| ORD00047453 | USD | 16334860.0 | 3 | 138000.00 | 1234.3 |
| ORD00024429 | JPY | 276390000.0 | 2 | 24000.00 | 1212.5 |

### [Q-V3.coupon] V3：coupon_discount 值域

```sql
SELECT src, count(DISTINCT coupon_discount) AS n_distinct, min(coupon_d) AS min_v, max(coupon_d) AS max_v,
  sum(CASE WHEN coupon_d < 0 THEN 1 ELSE 0 END) AS n_negative,
  sum(CASE WHEN coupon_d = 0 THEN 1 ELSE 0 END) AS n_zero,
  sum(CASE WHEN coupon_d % 50 <> 0 THEN 1 ELSE 0 END) AS n_not_multiple_of_50,
  list_sort(list(DISTINCT coupon_discount) FILTER (WHERE coupon_d < 0)) AS negative_values
FROM orders_t GROUP BY src ORDER BY src
```

| src | n_distinct | min_v | max_v | n_negative | n_zero | n_not_multiple_of_50 | negative_values |
|---|---|---|---|---|---|---|---|
| base | 21 | -1.00 | 950.00 | 300 | 4942 | 300 | ['-1.0'] |
| day1 | 20 | 0.00 | 950.00 | 0 | 236 | 0 | NULL |
| day2 | 20 | 0.00 | 950.00 | 0 | 256 | 0 | NULL |
| day3 | 20 | 0.00 | 950.00 | 0 | 238 | 0 | NULL |

### [Q-AMT.overlap] V1、V2、V3、V6 互相重疊的列數（base）

```sql
WITH f AS (
  SELECT amount_d < 0 AS neg, CASE WHEN ratio IS NULL THEN 'no_ratio'
         WHEN ratio < 0 AND abs(ratio) BETWEEN 0.8 AND 1.3 THEN 'negative_abs_normal'
         WHEN ratio < 0 THEN 'negative_other'
         WHEN ratio BETWEEN 0.8 AND 1.3 THEN 'normal'
         WHEN ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'about_x1000'
         ELSE 'other_outlier' END = 'about_x1000' AS x1000, coupon_d < 0 AS coupon_neg,
    product_id NOT IN (SELECT product_id FROM products) AS unknown_product
  FROM orders_ratio WHERE src = 'base')
SELECT sum(CASE WHEN neg AND coupon_neg THEN 1 ELSE 0 END) AS neg_and_coupon,
  sum(CASE WHEN x1000 AND coupon_neg THEN 1 ELSE 0 END) AS x1000_and_coupon,
  sum(CASE WHEN unknown_product AND coupon_neg THEN 1 ELSE 0 END) AS unknown_product_and_coupon,
  sum(CASE WHEN neg AND unknown_product THEN 1 ELSE 0 END) AS neg_and_unknown_product
FROM f
```

| neg_and_coupon | x1000_and_coupon | unknown_product_and_coupon | neg_and_unknown_product |
|---|---|---|---|
| 1 | 1 | 0 | 0 |

### [Q-V4.ntd] V4：幣別分布與 NTD 比值（1:1 換算）對照 TWD

```sql
SELECT src, currency, count(*) AS n,
  round(quantile_cont(ratio, 0.01), 4) AS p01, round(quantile_cont(ratio, 0.5), 4) AS p50, round(quantile_cont(ratio, 0.99), 4) AS p99,
  sum(CASE WHEN amount_d % 1 <> 0 THEN 1 ELSE 0 END) AS with_fraction
FROM orders_ratio WHERE ratio > 0 AND ratio < 2 OR currency = 'NTD' GROUP BY ALL ORDER BY src, currency
```

| src | currency | n | p01 | p50 | p99 | with_fraction |
|---|---|---|---|---|---|---|
| base | JPY | 10993 | 0.8604 | 1.0603 | 1.2666 | 80 |
| base | NTD | 200 | 0.8537 | 1.0353 | 1.2406 | 0 |
| base | TWD | 66558 | 0.8541 | 1.0506 | 1.2461 | 0 |
| base | USD | 22079 | 0.8477 | 1.0411 | 1.2379 | 21872 |
| day1 | JPY | 524 | 0.8518 | 1.0449 | 1.2416 | 0 |
| day1 | TWD | 3069 | 0.8538 | 1.0572 | 1.2461 | 0 |
| day1 | USD | 1022 | 0.8433 | 1.0403 | 1.2298 | 1008 |
| day2 | JPY | 531 | 0.8506 | 1.0415 | 1.2407 | 0 |
| day2 | TWD | 3150 | 0.857 | 1.0519 | 1.2453 | 0 |
| day2 | USD | 1019 | 0.8463 | 1.0394 | 1.2334 | 1012 |
| day3 | JPY | 521 | 0.8513 | 1.0518 | 1.2445 | 0 |
| day3 | TWD | 3141 | 0.8535 | 1.0514 | 1.2459 | 0 |
| day3 | USD | 953 | 0.8429 | 1.0366 | 1.2341 | 942 |

### [Q-L5.jpy_fraction] L5：JPY 帶非零小數

```sql
SELECT src, count(*) AS jpy_rows, sum(CASE WHEN amount_d % 1 <> 0 THEN 1 ELSE 0 END) AS jpy_with_fraction
FROM orders_t WHERE currency = 'JPY' GROUP BY src ORDER BY src
```

| src | jpy_rows | jpy_with_fraction |
|---|---|---|
| base | 11022 | 80 |
| day1 | 524 | 0 |
| day2 | 531 | 0 |
| day3 | 521 | 0 |

### [Q-V6.unknown_product] V6：product_id 不在產品清單

```sql
SELECT src, count(*) AS n_rows, count(DISTINCT product_id) AS n_ids, min(product_id) AS id_min, max(product_id) AS id_max,
  list_sort(list(DISTINCT order_status)) AS statuses
FROM orders_t o WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id = o.product_id)
GROUP BY src ORDER BY src
```

| src | n_rows | n_ids | id_min | id_max | statuses |
|---|---|---|---|---|---|
| base | 120 | 120 | P91064 | P99990 | ['cancelled', 'completed', 'created', 'paid'] |

### [Q-L6.inactive] L6：訂單的產品 is_active = 'N'

```sql
SELECT o.src, count(*) AS n_rows,
  count(*) FILTER (WHERE o.order_id NOT IN (SELECT order_id FROM base1)) AS rows_id_not_in_base,
  count(DISTINCT o.order_id) FILTER (WHERE o.order_id NOT IN (SELECT order_id FROM base1)) AS ids_not_in_base
FROM orders_t o JOIN products p USING (product_id) WHERE p.is_active = 'N'
GROUP BY o.src ORDER BY o.src
```

| src | n_rows | rows_id_not_in_base | ids_not_in_base |
|---|---|---|---|
| base | 4270 | 0 | 0 |
| day1 | 184 | 164 | 163 |
| day2 | 182 | 154 | 154 |
| day3 | 195 | 163 | 163 |

### [Q-L7.dup_name] L7：同名不同 product_id

```sql
SELECT count(*) AS n_products, count(DISTINCT product_name) AS n_names,
  (SELECT count(*) FROM (SELECT product_name FROM products GROUP BY 1 HAVING count(*) > 1)) AS names_with_multiple_ids,
  count(*) - count(DISTINCT product_id) AS dup_product_id,
  sum(CASE WHEN bp IS NULL OR bp <= 0 THEN 1 ELSE 0 END) AS bad_price,
  list_sort(list(DISTINCT is_active)) AS is_active_values
FROM products
```

| n_products | n_names | names_with_multiple_ids | dup_product_id | bad_price | is_active_values |
|---|---|---|---|---|---|
| 300 | 253 | 44 | 0 | 0 | ['N', 'Y'] |

### [Q-FX.coverage] L12 與找不到匯率：幣別不在匯率表、USD/JPY 下單日（台北）沒有匯率

```sql
SELECT o.src,
  sum(CASE WHEN o.currency NOT IN (SELECT DISTINCT currency FROM fx) THEN 1 ELSE 0 END) AS currency_not_in_fx,
  sum(CASE WHEN o.currency = 'TWD' THEN 1 ELSE 0 END) AS twd, sum(CASE WHEN o.currency = 'NTD' THEN 1 ELSE 0 END) AS ntd,
  sum(CASE WHEN o.currency IN (SELECT DISTINCT currency FROM fx) AND f.rate IS NULL THEN 1 ELSE 0 END) AS fx_missing_on_order_date
FROM orders_t o LEFT JOIN fx f ON f.rate_date = o.co_date AND f.currency = o.currency GROUP BY o.src ORDER BY o.src
```

| src | currency_not_in_fx | twd | ntd | fx_missing_on_order_date |
|---|---|---|---|---|
| base | 66890 | 66690 | 200 | 0 |
| day1 | 3069 | 3069 | 0 | 0 |
| day2 | 3150 | 3150 | 0 | 0 |
| day3 | 3141 | 3141 | 0 | 0 |

### [Q-FX.table] 匯率表本身：範圍、缺日、同日同幣別重複、非正值

```sql
SELECT min(rate_date) AS d_min, max(rate_date) AS d_max, count(*) AS n_rows,
  count(DISTINCT rate_date) AS n_dates, (max(rate_date) - min(rate_date) + 1) AS n_calendar_days,
  count(*) - count(DISTINCT (rate_date, currency)) AS dup_date_currency,
  sum(CASE WHEN rate IS NULL OR rate <= 0 THEN 1 ELSE 0 END) AS bad_rate,
  list_sort(list(DISTINCT currency)) AS currencies
FROM fx
```

| d_min | d_max | n_rows | n_dates | n_calendar_days | dup_date_currency | bad_rate | currencies |
|---|---|---|---|---|---|---|---|
| 2026-04-28 | 2026-07-03 | 134 | 67 | 67 | 0 | 0 | ['JPY', 'USD'] |

### [Q-ORD.member_ref] 新檢查：訂單的 member_id 不在會員快照、下單日早於註冊日

```sql
WITH m AS (SELECT member_id, min(TRY_CAST(register_date AS DATE)) AS reg FROM members GROUP BY member_id)
SELECT o.src, sum(CASE WHEN m.member_id IS NULL THEN 1 ELSE 0 END) AS member_not_found,
  sum(CASE WHEN o.co_date < m.reg THEN 1 ELSE 0 END) AS order_before_register
FROM orders_t o LEFT JOIN m USING (member_id) GROUP BY o.src ORDER BY o.src
```

| src | member_not_found | order_before_register |
|---|---|---|
| base | 0 | 0 |
| day1 | 0 | 0 |
| day2 | 0 | 0 |
| day3 | 0 | 0 |

### [Q-MEM.rows] 會員：各快照列數

```sql
SELECT extract_date, count(*) AS n_rows, count(DISTINCT member_id) AS n_members FROM members GROUP BY 1 ORDER BY 1
```

| extract_date | n_rows | n_members |
|---|---|---|
| 2026-04-30 | 8030 | 8000 |
| 2026-05-31 | 459 | 459 |
| 2026-06-30 | 502 | 502 |

### [Q-V8.same_day] V8：同一會員同一 extract_date 多列

```sql
WITH g AS (
  SELECT member_id, extract_date, count(*) AS c, count(DISTINCT member_level) AS d_level,
    count(DISTINCT concat_ws('|', member_name, city, birth_date, register_date)) AS d_other
  FROM members GROUP BY 1, 2 HAVING count(*) > 1)
SELECT extract_date, count(*) AS n_groups, sum(c) - count(*) AS extra_rows,
  sum(CASE WHEN d_level > 1 THEN 1 ELSE 0 END) AS level_differs, sum(CASE WHEN d_other > 1 THEN 1 ELSE 0 END) AS other_differs
FROM g GROUP BY 1 ORDER BY 1
```

| extract_date | n_groups | extra_rows | level_differs | other_differs |
|---|---|---|---|---|
| 2026-04-30 | 30 | 30 | 30 | 0 |

### [Q-V9V10.placeholders] V9、V10：city = 'N/A'、birth_date = 1900-01-01（各快照）

```sql
SELECT extract_date, count(*) AS n_rows,
  sum(CASE WHEN city = 'N/A' THEN 1 ELSE 0 END) AS city_na,
  sum(CASE WHEN birth_date = '1900-01-01' THEN 1 ELSE 0 END) AS birth_1900
FROM members GROUP BY ROLLUP (extract_date) ORDER BY extract_date NULLS LAST
```

| extract_date | n_rows | city_na | birth_1900 |
|---|---|---|---|
| 2026-04-30 | 8030 | 66 | 76 |
| 2026-05-31 | 459 | 3 | 2 |
| 2026-06-30 | 502 | 2 | 3 |
| NULL | 8991 | 71 | 81 |

### [Q-V9.members] V9：city N/A 涉及的會員數、其中在其他快照有真實縣市的人數

```sql
SELECT count(DISTINCT member_id) AS members_with_na,
  count(DISTINCT CASE WHEN member_id IN (SELECT member_id FROM members WHERE city <> 'N/A') THEN member_id END) AS also_has_real_city
FROM members WHERE city = 'N/A'
```

| members_with_na | also_has_real_city |
|---|---|
| 70 | 9 |

### [Q-V9.na_before_real] V9：city N/A 的會員分成從來沒有真實縣市、第一次出現 N/A 早於第一次出現真實縣市（dim_member 會先有一個城市為空值的版本）

```sql
WITH f AS (
  SELECT member_id, bool_or(city <> 'N/A') AS has_real,
    min(extract_date) FILTER (WHERE city = 'N/A') AS first_na,
    min(extract_date) FILTER (WHERE city <> 'N/A') AS first_real
  FROM members GROUP BY member_id HAVING bool_or(city = 'N/A'))
SELECT count(*) AS members_with_na,
  count(*) FILTER (WHERE NOT has_real) AS never_real_city,
  count(*) FILTER (WHERE has_real AND first_na < first_real) AS na_before_first_real,
  count(*) FILTER (WHERE NOT has_real) + count(*) FILTER (WHERE has_real AND first_na < first_real) AS expected_members_with_null_city_version
FROM f
```

| members_with_na | never_real_city | na_before_first_real | expected_members_with_null_city_version |
|---|---|---|---|
| 70 | 61 | 4 | 65 |

### [Q-V10.birth_min] V10：1900 以外最早的生日、生日曾為 1900 的會員數

```sql
SELECT min(birth_date) FILTER (WHERE birth_date <> '1900-01-01') AS min_real_birth,
  count(DISTINCT member_id) FILTER (WHERE birth_date = '1900-01-01') AS members_with_1900,
  count(DISTINCT member_id) FILTER (WHERE birth_date = '1900-01-01'
    AND member_id NOT IN (SELECT member_id FROM members WHERE birth_date <> '1900-01-01')) AS members_never_real_birth,
  count(DISTINCT member_id) FILTER (WHERE city = 'N/A'
    AND member_id NOT IN (SELECT member_id FROM members WHERE city <> 'N/A')) AS members_never_real_city
FROM members
```

| min_real_birth | members_with_1900 | members_never_real_birth | members_never_real_city |
|---|---|---|---|
| 1960-01-03 | 80 | 61 | 61 |

### [Q-J9.birth_direction] J9：生日在快照間變動的方向（同一快照日兩列時依等級高低排序，結果不受影響）

```sql
WITH s AS (SELECT member_id, extract_date, birth_date,
    lag(birth_date) OVER (PARTITION BY member_id ORDER BY extract_date, CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END) AS prev_birth
  FROM members)
SELECT CASE WHEN prev_birth = '1900-01-01' THEN '1900 -> real' WHEN birth_date = '1900-01-01' THEN 'real -> 1900'
            ELSE 'real -> other real' END AS direction,
  count(DISTINCT member_id) AS n_members, list_sort(list(DISTINCT member_id))[1:3] AS examples
FROM s WHERE prev_birth IS NOT NULL AND prev_birth <> birth_date GROUP BY 1 ORDER BY 1
```

| direction | n_members | examples |
|---|---|---|
| 1900 -> real | 14 | ['M000552', 'M000708', 'M001372'] |
| real -> 1900 | 5 | ['M001647', 'M001931', 'M003842'] |

### [Q-L8.under18] L8：註冊時未滿 18 歲（排除 1900-01-01）

```sql
SELECT count(*) AS n_rows, count(DISTINCT member_id) AS n_members,
  round(min(date_diff('day', TRY_CAST(birth_date AS DATE), TRY_CAST(register_date AS DATE)) / 365.25), 1) AS min_age_at_register
FROM members WHERE birth_date <> '1900-01-01'
  AND TRY_CAST(birth_date AS DATE) + INTERVAL 18 YEAR > TRY_CAST(register_date AS DATE)
```

| n_rows | n_members | min_age_at_register |
|---|---|---|
| 455 | 398 | 11.5 |

### [Q-L9.changes] L9：等級、縣市在快照間變過的會員數

```sql
SELECT (SELECT count(*) FROM (SELECT member_id FROM members GROUP BY 1 HAVING count(DISTINCT member_level) > 1)) AS level_changed_members,
  (SELECT count(*) FROM (SELECT member_id FROM members GROUP BY 1 HAVING count(DISTINCT city) > 1)) AS city_changed_members_incl_na,
  (SELECT count(*) FROM (SELECT member_id FROM members WHERE city <> 'N/A' GROUP BY 1 HAVING count(DISTINCT city) > 1)) AS city_changed_members_excl_na,
  (SELECT count(*) FROM (SELECT member_id FROM members GROUP BY 1 HAVING count(DISTINCT member_name) > 1)) AS name_changed,
  (SELECT count(*) FROM (SELECT member_id FROM members GROUP BY 1 HAVING count(DISTINCT register_date) > 1)) AS register_changed
```

| level_changed_members | city_changed_members_incl_na | city_changed_members_excl_na | name_changed | register_changed |
|---|---|---|---|---|
| 434 | 376 | 367 | 0 | 0 |

### [Q-L11.identical] L11：後續快照與該會員前一次快照屬性完全相同的列（同日兩列先照 V8 取較高等級）

```sql
WITH m1 AS (SELECT *, CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END AS rk FROM members
  QUALIFY row_number() OVER (PARTITION BY member_id, extract_date ORDER BY CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END DESC) = 1),
s AS (SELECT *, lag(concat_ws('|', member_name, member_level, city, birth_date, register_date))
    OVER (PARTITION BY member_id ORDER BY extract_date) AS prev_attrs
  FROM m1)
SELECT extract_date, count(*) AS identical_to_previous
FROM s WHERE prev_attrs = concat_ws('|', member_name, member_level, city, birth_date, register_date)
GROUP BY ROLLUP (extract_date) ORDER BY 1 NULLS LAST
```

| extract_date | identical_to_previous |
|---|---|
| 2026-05-31 | 95 |
| 2026-06-30 | 91 |
| NULL | 186 |

### [Q-MEM.level_moves] L9、V8：會員等級在相鄰快照間的變動方向（同日兩列分別取較高、較低等級）

```sql
WITH m AS (SELECT *, CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END AS rk FROM members),
hi AS (SELECT 'v8_take_higher' AS rule, * FROM m
  QUALIFY row_number() OVER (PARTITION BY member_id, extract_date ORDER BY rk DESC) = 1),
lo AS (SELECT 'v8_take_lower' AS rule, * FROM m
  QUALIFY row_number() OVER (PARTITION BY member_id, extract_date ORDER BY rk ASC) = 1),
s AS (SELECT *, lag(rk) OVER (PARTITION BY rule, member_id ORDER BY extract_date) AS prev_rk
  FROM (SELECT * FROM hi UNION ALL SELECT * FROM lo))
SELECT rule, count(*) FILTER (WHERE rk - prev_rk = 1) AS up_one_level,
  count(*) FILTER (WHERE rk - prev_rk > 1) AS up_more_levels,
  count(*) FILTER (WHERE rk < prev_rk) AS down
FROM s WHERE prev_rk IS NOT NULL GROUP BY rule ORDER BY rule
```

| rule | up_one_level | up_more_levels | down |
|---|---|---|---|
| v8_take_higher | 404 | 0 | 1 |
| v8_take_lower | 405 | 0 | 0 |

### [Q-V8.later_snapshot] V8：同日矛盾的 30 位中，之後的快照又出現的會員，後來的等級等於較高還是較低者

```sql
WITH v8 AS (SELECT member_id, max(CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END) AS hi, min(CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END) AS lo
  FROM members GROUP BY member_id, extract_date HAVING count(*) > 1)
SELECT v8.member_id, v8.hi, v8.lo, m.extract_date, CASE m.member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END AS later_rk
FROM v8 JOIN members m ON m.member_id = v8.member_id AND m.extract_date > '2026-04-30' ORDER BY 1
```

| member_id | hi | lo | extract_date | later_rk |
|---|---|---|---|---|
| M000356 | 3 | 2 | 2026-05-31 | 2 |
| M002198 | 3 | 2 | 2026-05-31 | 3 |

### [Q-MEM.register_after_extract] 新檢查：register_date 晚於 extract_date、等級值域

```sql
SELECT sum(CASE WHEN TRY_CAST(register_date AS DATE) > TRY_CAST(extract_date AS DATE) THEN 1 ELSE 0 END) AS register_after_extract,
  list_sort(list(DISTINCT member_level)) AS levels, list_sort(list(DISTINCT extract_date)) AS extract_dates
FROM members
```

| register_after_extract | levels | extract_dates |
|---|---|---|
| 0 | ['一般', '白金', '金卡', '銀卡'] | ['2026-04-30', '2026-05-31', '2026-06-30'] |

### [Q-N3.coupon_by_currency] N3：base 各幣別的 coupon 面額分布（與 notes coupon-currency.md 同一查詢）

```sql
SELECT currency, count(*) AS n, count(DISTINCT coupon_discount) AS n_vals,
  min(TRY_CAST(coupon_discount AS DOUBLE)) AS mn, max(TRY_CAST(coupon_discount AS DOUBLE)) AS mx,
  round(avg(TRY_CAST(coupon_discount AS DOUBLE)) FILTER (WHERE TRY_CAST(coupon_discount AS DOUBLE) > 0), 1) AS avg_pos,
  round(median(TRY_CAST(amount AS DOUBLE)), 1) AS med_amt,
  sum(CASE WHEN TRY_CAST(coupon_discount AS DOUBLE) > TRY_CAST(amount AS DOUBLE) THEN 1 ELSE 0 END) AS coupon_gt_amt
FROM orders_t WHERE src = 'base' GROUP BY currency ORDER BY currency
```

| currency | n | n_vals | mn | mx | avg_pos | med_amt | coupon_gt_amt |
|---|---|---|---|---|---|---|---|
| JPY | 11022 | 21 | -1.0 | 950.0 | 495.1 | 972503.5 | 4 |
| NTD | 200 | 20 | 0.0 | 950.0 | 494.4 | 222540.5 | 0 |
| TWD | 66690 | 21 | -1.0 | 950.0 | 499.8 | 202872.0 | 29 |
| USD | 22128 | 21 | -1.0 | 950.0 | 499.7 | 6445.2 | 785 |

### [Q-DOM.status_currency] 值域：四個訂單檔 order_status、currency 各值的筆數（原始字串，區分大小寫與空白）

```sql
SELECT src, 'order_status' AS col, order_status AS raw_value, count(*) AS n,
  order_status IN ('created', 'paid', 'cancelled', 'completed') AS in_contract
FROM orders_all GROUP BY ALL
UNION ALL
SELECT src, 'currency', currency, count(*), currency IN ('TWD', 'NTD', 'USD', 'JPY')
FROM orders_all GROUP BY ALL
ORDER BY src, col, raw_value
```

| src | col | raw_value | n | in_contract |
|---|---|---|---|---|
| base | currency | JPY | 11022 | True |
| base | currency | NTD | 200 | True |
| base | currency | TWD | 66690 | True |
| base | currency | USD | 22128 | True |
| base | order_status | cancelled | 14248 | True |
| base | order_status | completed | 28612 | True |
| base | order_status | created | 14286 | True |
| base | order_status | paid | 42894 | True |
| day1 | currency | JPY | 524 | True |
| day1 | currency | TWD | 3069 | True |
| day1 | currency | USD | 1022 | True |
| day1 | order_status | cancelled | 307 | True |
| day1 | order_status | completed | 321 | True |
| day1 | order_status | created | 1361 | True |
| day1 | order_status | paid | 2626 | True |
| day2 | currency | JPY | 531 | True |
| day2 | currency | TWD | 3150 | True |
| day2 | currency | USD | 1019 | True |
| day2 | order_status | cancelled | 289 | True |
| day2 | order_status | completed | 313 | True |
| day2 | order_status | created | 1384 | True |
| day2 | order_status | paid | 2714 | True |
| day3 | currency | JPY | 521 | True |
| day3 | currency | TWD | 3141 | True |
| day3 | currency | USD | 953 | True |
| day3 | order_status | cancelled | 314 | True |
| day3 | order_status | completed | 289 | True |
| day3 | order_status | created | 1271 | True |
| day3 | order_status | paid | 2741 | True |

### [Q-SM.chain] 防護性設計：同一張單依 updated_at 排序後的相鄰狀態（走不到、跳過中間狀態）

```sql
WITH t AS (SELECT DISTINCT order_id, member_id, amount_d, co_ts, upd_ts, order_status FROM orders_t),
s AS (SELECT *, lag(order_status) OVER (PARTITION BY order_id, member_id, amount_d, co_ts ORDER BY upd_ts) AS prev_status FROM t)
SELECT count(*) FILTER (WHERE prev_status IS NOT NULL) AS adjacent_pairs,
  count(*) FILTER (WHERE prev_status IS NOT NULL AND prev_status <> order_status) AS status_changed,
  count(*) FILTER (WHERE prev_status IS NOT NULL AND NOT (prev_status = order_status OR prev_status = 'created'
    OR (prev_status = 'paid' AND order_status IN ('cancelled', 'completed')))) AS not_reachable,
  count(*) FILTER (WHERE prev_status = 'created' AND order_status = 'completed') AS skipped_intermediate
FROM s
```

| adjacent_pairs | status_changed | not_reachable | skipped_intermediate |
|---|---|---|---|
| 110 | 25 | 0 | 0 |

### [Q-SM.same_second] 防護性設計：同一張單、同一個 updated_at 出現不同狀態

```sql
SELECT count(*) AS n_groups FROM (
  SELECT order_id, member_id, amount_d, co_ts, upd_ts FROM orders_t
  GROUP BY ALL HAVING count(DISTINCT order_status) > 1)
```

| n_groups |
|---|
| 0 |

### [Q-MEM.both_0531_0630] 防護性設計：同時出現在 05-31 與 06-30 快照的會員（遲到快照會遺失歷史的對象）

```sql
SELECT count(*) AS n_members FROM (
  SELECT member_id FROM members WHERE extract_date IN ('2026-05-31', '2026-06-30')
  GROUP BY member_id HAVING count(DISTINCT extract_date) = 2)
```

| n_members |
|---|
| 0 |

### [Q-POST.totals] 重算的 fact 和管線實跑對帳比對：各批寫入筆數、amount_twd、net、coupon 轉 NULL、V2 清單

```sql
SELECT wbatch, count(*) AS fact_rows, sum(amount_twd) AS amount_twd_sum,
  sum(amount_twd - coupon_clean) AS net_amount_twd_sum,
  sum(CASE WHEN coupon_d = -1 THEN 1 ELSE 0 END) AS coupon_nulled_rows,
  sum(CASE WHEN round(amount_twd / (bp * qty_i), 2) > 100 THEN 1 ELSE 0 END) AS amount_review_rows,
  sum(CASE WHEN bp IS NULL THEN 1 ELSE 0 END) AS unknown_product_rows
FROM fact_sim GROUP BY ROLLUP (wbatch) ORDER BY wbatch NULLS LAST
```

| wbatch | fact_rows | amount_twd_sum | net_amount_twd_sum | coupon_nulled_rows | amount_review_rows | unknown_product_rows |
|---|---|---|---|---|---|---|
| base | 99950 | 35969473520.09 | 35783693189.25 | 299 | 40 | 120 |
| day1 | 4000 | 1056883370.88 | 1055002970.88 | 0 | 0 | 0 |
| day2 | 4060 | 1039558224.11 | 1037651074.11 | 0 | 0 | 0 |
| day3 | 4000 | 1020981665.19 | 1019042815.19 | 0 | 0 | 0 |
| NULL | 112010 | 39086896780.27 | 38895390049.43 | 299 | 40 | 120 |

### [Q-POST.v2_share] V2：清單 40 列佔 base 寫入 fact 的 amount_twd 比例（以及佔三天後全表的比例）

```sql
SELECT count(*) FILTER (WHERE round(amount_twd / (bp * qty_i), 2) > 100) AS v2_rows,
  sum(amount_twd) FILTER (WHERE round(amount_twd / (bp * qty_i), 2) > 100) AS v2_amount_twd,
  sum(amount_twd) FILTER (WHERE wbatch = 'base') AS base_amount_twd,
  round(100 * sum(amount_twd) FILTER (WHERE round(amount_twd / (bp * qty_i), 2) > 100)
        / sum(amount_twd) FILTER (WHERE wbatch = 'base'), 2) AS pct_of_base,
  round(100 * sum(amount_twd) FILTER (WHERE round(amount_twd / (bp * qty_i), 2) > 100) / sum(amount_twd), 2) AS pct_of_fact_after_day3
FROM fact_sim
```

| v2_rows | v2_amount_twd | base_amount_twd | pct_of_base | pct_of_fact_after_day3 |
|---|---|---|---|---|
| 40 | 10102491689.70 | 35969473520.09 | 28.09 | 25.85 |

### [Q-POST.v1_overlap] V1：被合約擋下的 50 列裡，同時是 V3（coupon -1）、V7 重複、completed 且出發日未到的列數

```sql
SELECT count(*) AS v1_rows,
  sum(CASE WHEN coupon_d = -1 THEN 1 ELSE 0 END) AS also_coupon_minus1,
  sum(CASE WHEN order_id IN (SELECT order_id FROM orders_t WHERE src = 'base' GROUP BY 1 HAVING count(*) > 1) THEN 1 ELSE 0 END) AS also_v7_group,
  sum(CASE WHEN order_status = 'completed' AND dep_dt > upd_date THEN 1 ELSE 0 END) AS also_l10,
  sum(amount_d * CASE WHEN currency IN ('TWD','NTD') THEN 1 ELSE fx_rate END) AS amount_twd_unrounded
FROM orders_ratio WHERE src = 'base' AND amount_d <= 0
```

| v1_rows | also_coupon_minus1 | also_v7_group | also_l10 | amount_twd_unrounded |
|---|---|---|---|---|
| 50 | 1 | 0 | 18 | -12389441.85379000 |

### [Q-POST.l10] L10：寫進 fact 的 completed 中，出發日晚於最後更新日的列數與金額

```sql
SELECT count(*) FILTER (WHERE order_status = 'completed') AS completed_rows,
  count(*) FILTER (WHERE order_status = 'completed' AND dep_dt > upd_date) AS completed_departure_not_reached,
  sum(amount_twd) FILTER (WHERE order_status = 'completed' AND dep_dt > upd_date) AS amount_twd
FROM fact_sim
```

| completed_rows | completed_departure_not_reached | amount_twd |
|---|---|---|
| 28578 | 28578 | 10324629272.48 |

### [Q-POST.currency] V4、L12：base 寫進 fact 的幣別分布

```sql
SELECT currency, count(*) AS n, sum(CASE WHEN fx_rate = 1 THEN 1 ELSE 0 END) AS fx_rate_1, sum(amount_twd) AS amount_twd_sum
FROM fact_sim WHERE wbatch = 'base' GROUP BY ROLLUP (currency) ORDER BY currency NULLS LAST
```

| currency | n | fx_rate_1 | amount_twd_sum |
|---|---|---|---|
| JPY | 11017 | 0 | 4576607489.88 |
| NTD | 200 | 200 | 54561733.00 |
| TWD | 66632 | 66632 | 23602667357.00 |
| USD | 22101 | 0 | 7735636940.21 |
| NULL | 99950 | 66832 | 35969473520.09 |

### [Q-POST.l6] L6：寫進 fact 的列中，產品已下架的筆數

```sql
SELECT wbatch, count(*) AS n FROM fact_sim WHERE is_active = 'N' GROUP BY ROLLUP (wbatch) ORDER BY wbatch NULLS LAST
```

| wbatch | n |
|---|---|
| base | 4267 |
| day1 | 163 |
| day2 | 154 |
| day3 | 163 |
| NULL | 4747 |

### [Q-POST.net_guard] net 變負數的防護：-1 以外的負 coupon（原始檔）、coupon 大於 amount_twd、net < 0（fact）

```sql
SELECT (SELECT count(*) FROM orders_t WHERE coupon_d < 0 AND coupon_d <> -1) AS negative_coupon_not_minus1,
  count(*) FILTER (WHERE coupon_clean > amount_twd) AS coupon_gt_amount_twd,
  count(*) FILTER (WHERE amount_twd - coupon_clean < 0) AS net_negative,
  min(amount_twd) AS min_amount_twd, max(coupon_clean) AS max_coupon
FROM fact_sim
```

| negative_coupon_not_minus1 | coupon_gt_amount_twd | net_negative | min_amount_twd | max_coupon |
|---|---|---|---|---|
| 0 | 0 | 0 | 2520.07 | 950.00 |

### [Q-POST.l4_final] L4：25 張單在三天後的 fact 狀態（取 updated_at 最新一列）

```sql
SELECT order_status, wbatch AS written_by_batch, count(*) AS n FROM fact_sim
WHERE order_id IN (SELECT a.order_id FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id
                   AND a.src = 'day1' AND b.src = 'day2' WHERE a.order_id NOT IN (SELECT order_id FROM base1))
GROUP BY ALL ORDER BY ALL
```

| order_status | written_by_batch | n |
|---|---|---|
| cancelled | day1 | 25 |

### [Q-L10.example] L10：範例（base 寫進 fact 的 completed，出發日晚於最後更新日）

```sql
SELECT order_id, order_status, currency, amount, updated_at, departure_date, dep_dt - upd_date AS days_to_departure
FROM base1 WHERE order_status = 'completed' AND dep_dt > upd_date AND amount_d > 0 ORDER BY order_id LIMIT 3
```

| order_id | order_status | currency | amount | updated_at | departure_date | days_to_departure |
|---|---|---|---|---|---|---|
| ORD00000005 | completed | TWD | 59125.0 | 2026-06-27T08:40:38+08:00 | 2026-07-16 | 19 |
| ORD00000006 | completed | TWD | 739328.0 | 2026-05-17T13:10:21+08:00 | 2026-07-07 | 51 |
| ORD00000009 | completed | USD | 2344.76 | 2026-06-23T08:56:57+08:00 | 2026-10-11 | 110 |

### [Q-J2.impact] J2：如果照官方 README 把撞號列當成狀態更新（updated_at 較新才覆寫），fact 會怎麼變

```sql
WITH j AS (SELECT * FROM orders_t WHERE src <> 'base' AND order_id IN (SELECT order_id FROM base1)
           QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY upd_ts DESC) = 1),
hit AS (SELECT f.order_id, f.member_id AS fact_member, j.member_id AS inc_member,
          f.order_status AS fact_status, j.order_status AS inc_status
        FROM fact_sim f JOIN j USING (order_id) WHERE j.upd_ts > f.upd_ts)
SELECT count(*) AS orders_overwritten,
  sum(CASE WHEN fact_member <> inc_member THEN 1 ELSE 0 END) AS member_changed,
  sum(CASE WHEN fact_status <> inc_status THEN 1 ELSE 0 END) AS status_changed,
  sum(CASE WHEN fact_status <> 'cancelled' AND inc_status = 'cancelled' THEN 1 ELSE 0 END) AS become_cancelled,
  sum(CASE WHEN fact_status = 'cancelled' AND inc_status <> 'cancelled' THEN 1 ELSE 0 END) AS cancelled_reverted,
  (SELECT count(*) FROM fact_sim) AS fact_rows,
  (SELECT count(*) FROM fact_sim WHERE order_status = 'cancelled') AS fact_cancelled,
  round(100.0 * (SELECT count(*) FROM fact_sim WHERE order_status = 'cancelled') / (SELECT count(*) FROM fact_sim), 2) AS cancel_rate_pct,
  round(100.0 * ((SELECT count(*) FROM fact_sim WHERE order_status = 'cancelled')
                 + sum(CASE WHEN fact_status <> 'cancelled' AND inc_status = 'cancelled' THEN 1 ELSE 0 END)
                 - sum(CASE WHEN fact_status = 'cancelled' AND inc_status <> 'cancelled' THEN 1 ELSE 0 END))
        / (SELECT count(*) FROM fact_sim), 2) AS cancel_rate_pct_if_overwritten
FROM hit
```

| orders_overwritten | member_changed | status_changed | become_cancelled | cancelled_reverted | fact_rows | fact_cancelled | cancel_rate_pct | cancel_rate_pct_if_overwritten |
|---|---|---|---|---|---|---|---|---|
| 1776 | 1776 | 1429 | 763 | 118 | 112010 | 14259 | 12.73 | 13.31 |

### [Q-J3.example] J3：範例（增量同一檔內，同一個 order_id 兩列的會員、金額、下單時間都不同）

```sql
SELECT src, order_id, member_id, amount, order_created_at, order_status FROM orders_t
WHERE src <> 'base' AND (src, order_id) IN (
  SELECT src, order_id FROM orders_t WHERE src <> 'base' GROUP BY ALL HAVING count(DISTINCT member_id) > 1)
ORDER BY src, order_id LIMIT 2
```

| src | order_id | member_id | amount | order_created_at | order_status |
|---|---|---|---|---|---|
| day1 | ORD00036457 | M002150 | 200659.0 | 2026-05-26T04:27:52+08:00 | completed |
| day1 | ORD00036457 | M000272 | 18042.46 | 2026-06-21T16:53:45+08:00 | cancelled |

### [Q-L4.impact] L4：25 張單在 fact 的金額；若照到達順序處理，這 25 張會從 cancelled 回到 paid

```sql
SELECT count(*) AS orders, sum(amount_twd) AS amount_twd_sum,
  list_sort(list(DISTINCT order_status)) AS fact_status_now
FROM fact_sim
WHERE order_id IN (SELECT a.order_id FROM orders_t a JOIN orders_t b ON a.order_id = b.order_id
                   AND a.src = 'day1' AND b.src = 'day2' WHERE a.order_id NOT IN (SELECT order_id FROM base1))
```

| orders | amount_twd_sum | fact_status_now |
|---|---|---|
| 25 | 6154857.49 | ['cancelled'] |

### [Q-L3.example] L3：範例與金額（day2 送來、下單日在 6 月、不在 base 也不在 day1 的新單）

```sql
SELECT order_id, order_created_at, order_status, updated_at, currency, amount,
  count(*) OVER () AS n_orders, sum(amount_twd) OVER () AS amount_twd_sum
FROM fact_sim WHERE wbatch = 'day2' AND co_date < DATE '2026-07-01'
ORDER BY order_id LIMIT 2
```

| order_id | order_created_at | order_status | updated_at | currency | amount | n_orders | amount_twd_sum |
|---|---|---|---|---|---|---|---|
| ORD00112001 | 2026-06-15T09:33:20+08:00 | paid | 2026-07-02T18:13:34+08:00 | TWD | 54355.0 | 60 | 11320587.24 |
| ORD00112002 | 2026-06-17T13:26:27+08:00 | paid | 2026-07-02T03:33:19+08:00 | TWD | 112245.0 | 60 | 11320587.24 |

### [Q-V5.example] V5：範例（Z 格式的下單時間，字串前 10 碼的日期和台北日期不同）

```sql
SELECT order_id, order_created_at, substr(order_created_at, 1, 10) AS literal_date, co_date AS taipei_date
FROM orders_t WHERE src = 'base' AND co_fmt = 'iso_Z' AND co_date <> CAST(substr(order_created_at, 1, 10) AS DATE)
ORDER BY order_id LIMIT 2
```

| order_id | order_created_at | literal_date | taipei_date |
|---|---|---|---|
| ORD00000245 | 2026-05-14T23:06:27Z | 2026-05-14 | 2026-05-15 |
| ORD00000351 | 2026-05-29T21:18:48Z | 2026-05-29 | 2026-05-30 |

### [Q-V8.example] V8：範例（同一會員、同一個 extract_date 兩列，等級不同）

```sql
SELECT member_id, extract_date, member_level, city FROM members
WHERE (member_id, extract_date) IN (SELECT member_id, extract_date FROM members GROUP BY ALL HAVING count(*) > 1)
ORDER BY member_id, member_level LIMIT 2
```

| member_id | extract_date | member_level | city |
|---|---|---|---|
| M000096 | 2026-04-30 | 金卡 | 台北市 |
| M000096 | 2026-04-30 | 銀卡 | 台北市 |

### [Q-L7.example] L7：範例（同一個產品名稱對應兩個 product_id）

```sql
SELECT product_id, product_name, base_price_twd FROM products
WHERE product_name = (SELECT product_name FROM products WHERE product_id = 'P00098') ORDER BY product_id
```

| product_id | product_name | base_price_twd |
|---|---|---|
| P00098 | 伊斯坦堡1日票券 | 144000 |
| P00262 | 伊斯坦堡1日票券 | 197000 |

### [Q-J9.example] J9：範例（真實生日在後來的快照變成 1900-01-01）

```sql
SELECT member_id, extract_date, birth_date FROM members WHERE member_id = 'M001647' ORDER BY extract_date
```

| member_id | extract_date | birth_date |
|---|---|---|
| M001647 | 2026-04-30 | 1961-07-15 |
| M001647 | 2026-06-30 | 1900-01-01 |

### [Q-L10.vs_0701] L10 基準：completed 是在出發前標上的（出發日晚於最後更新日），和以 07-01 為基準出發日已過，是兩件事

```sql
SELECT 'base_one_row_per_id' AS scope, count(*) AS completed_rows,
  count(*) FILTER (WHERE dep_dt > upd_date) AS marked_completed_before_departure,
  count(*) FILTER (WHERE dep_dt < DATE '2026-07-01') AS departure_before_0701,
  count(*) FILTER (WHERE dep_dt < DATE '2026-07-01' AND dep_dt > upd_date) AS before_0701_and_marked_before_departure
FROM base1 WHERE order_status = 'completed'
UNION ALL
SELECT 'fact_after_day3', count(*),
  count(*) FILTER (WHERE dep_dt > upd_date),
  count(*) FILTER (WHERE dep_dt < DATE '2026-07-01'),
  count(*) FILTER (WHERE dep_dt < DATE '2026-07-01' AND dep_dt > upd_date)
FROM fact_sim WHERE order_status = 'completed'
```

| scope | completed_rows | marked_completed_before_departure | departure_before_0701 | before_0701_and_marked_before_departure |
|---|---|---|---|---|
| base_one_row_per_id | 28596 | 28596 | 6149 | 6149 |
| fact_after_day3 | 28578 | 28578 | 6147 | 6147 |

### [Q-J2.blocked_amount] J2：與 base 撞號而擋下的增量列，若其實是另一張真訂單，金額有多少（同編號＋會員＋下單時間＋金額算一張，重送取最新一列）

```sql
WITH j AS (
  SELECT o.*, round(o.amount_d * CASE WHEN o.currency IN ('TWD','NTD') THEN 1 ELSE f.rate END, 2) AS amount_twd,
    o.amount_d * CASE WHEN o.currency IN ('TWD','NTD') THEN 1 ELSE f.rate END / (p.bp * o.qty_i) AS ratio
  FROM orders_t o
  LEFT JOIN fx f ON f.rate_date = o.co_date AND f.currency = o.currency
  LEFT JOIN products p ON p.product_id = o.product_id
  WHERE o.src <> 'base' AND o.order_id IN (SELECT order_id FROM base1)),
k AS (SELECT * FROM j QUALIFY row_number() OVER (PARTITION BY order_id, member_id, co_ts, amount_d ORDER BY upd_ts DESC) = 1)
SELECT (SELECT count(*) FROM j) AS blocked_rows, count(*) AS orders_if_real,
  sum(amount_twd) AS amount_twd_sum,
  sum(amount_twd) FILTER (WHERE order_status <> 'cancelled') AS amount_twd_not_cancelled,
  count(*) FILTER (WHERE ratio > 100) AS ratio_over_100,
  (SELECT sum(amount_twd) FROM fact_sim) AS fact_amount_twd_sum,
  round(100 * sum(amount_twd) / (SELECT sum(amount_twd) FROM fact_sim), 2) AS pct_of_fact
FROM k
```

| blocked_rows | orders_if_real | amount_twd_sum | amount_twd_not_cancelled | ratio_over_100 | fact_amount_twd_sum | pct_of_fact |
|---|---|---|---|---|---|---|
| 1808 | 1800 | 468895127.27 | 238270742.17 | 0 | 39086896780.27 | 1.2 |

### [Q-V2.div1000_estimate] V2：base 寫進 fact 的金額，若人工確認清單上的 40 張真的是多乘 1,000、除以 1,000 後各月約多少（估計，不是確認結果）

```sql
WITH f AS (SELECT *, coalesce(round(amount_twd / (bp * qty_i), 2) > 100, false) AS in_review
           FROM fact_sim WHERE wbatch = 'base')
SELECT strftime(co_date, '%Y-%m') AS order_month,
  count(*) FILTER (WHERE in_review) AS review_orders,
  sum(amount_twd) AS amount_twd_as_is,
  sum(amount_twd) FILTER (WHERE NOT in_review) AS amount_twd_excluding_review,
  sum(CASE WHEN in_review THEN CAST(round(amount_twd / 1000, 2) AS DECIMAL(38,2)) ELSE amount_twd END) AS amount_twd_if_div1000
FROM f GROUP BY ROLLUP (order_month) ORDER BY order_month NULLS LAST
```

| order_month | review_orders | amount_twd_as_is | amount_twd_excluding_review | amount_twd_if_div1000 |
|---|---|---|---|---|
| 2026-05 | 26 | 19892613269.74 | 13045570511.57 | 13052417554.32 |
| 2026-06 | 14 | 16076860250.35 | 12821411318.82 | 12824666767.76 |
| NULL | 40 | 35969473520.09 | 25866981830.39 | 25877084322.08 |

### [Q-L3.june_change] L3：下單日在 6 月的訂單，每批處理完後的筆數與金額（折扣前、含所有狀態），看 07-02 之後變了多少

```sql
WITH j AS (SELECT *, coalesce(round(amount_twd / (bp * qty_i), 2) > 100, false) AS in_review,
             CASE wbatch WHEN 'base' THEN 0 WHEN 'day1' THEN 1 WHEN 'day2' THEN 2 ELSE 3 END AS k
           FROM fact_sim WHERE co_date BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'),
b AS (SELECT * FROM (VALUES ('base', 0), ('day1', 1), ('day2', 2), ('day3', 3)) t(after_batch, k))
SELECT b.after_batch, count(j.order_id) AS june_orders, sum(j.amount_twd) AS june_amount_twd,
  sum(j.amount_twd) FILTER (WHERE NOT j.in_review) AS june_amount_twd_excluding_review
FROM b LEFT JOIN j ON j.k <= b.k GROUP BY b.after_batch, b.k ORDER BY b.k
```

| after_batch | june_orders | june_amount_twd | june_amount_twd_excluding_review |
|---|---|---|---|
| base | 49349 | 16076860250.35 | 12821411318.82 |
| day1 | 49349 | 16076860250.35 | 12821411318.82 |
| day2 | 49409 | 16088180837.59 | 12832731906.06 |
| day3 | 49409 | 16088180837.59 | 12832731906.06 |

---

### 管線驗證（P-）：2026-10-26 完整執行的輸出

以下是 `P-` 段的 SQL 與輸出（對帳類的標籤印的是 `load_base`／`load_incremental` 回傳的對帳物件，沒有 SQL）。執行指令見[附錄 A](#附錄-a查詢腳本與重跑)。

### [P-BASE.reconciliation] load_base 的對帳

| 項目 | 值 |
|---|---|
| `input_rows` | 100040 |
| `fact_rows` | 99950 |
| `quarantined_rows` | 90 |
| `quarantined_by_category` | {'contract': 50, 'duplicate': 40} |
| `skipped_rows` | 0 |
| `coupon_nulled_rows` | 299 |
| `amount_review_rows` | 40 |
| `amount_twd_sum` | 35969473520.09 |
| `net_amount_twd_sum` | 35783693189.25 |
| `unknown_product_rows` | 120 |
| `unknown_member_rows` | 0 |
| `member_rejected_rows` | 0 |
| `balanced` | True |

### [P-BASE.fact_issue_rows] base 寫入 fact 後，各問題在 fact 裡剩幾列

```sql
SELECT count(*) AS fact_rows,
  sum(CASE WHEN amount < 0 THEN 1 ELSE 0 END) AS v1_negative,
  sum(CASE WHEN ratio > 1.3 AND ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 1 ELSE 0 END) AS v2_about_x1000,
  sum(CASE WHEN coupon_discount < 0 THEN 1 ELSE 0 END) AS v3_coupon_negative_left,
  sum(CASE WHEN coupon_discount IS NULL THEN 1 ELSE 0 END) AS v3_coupon_null,
  sum(CASE WHEN currency = 'NTD' THEN 1 ELSE 0 END) AS v4_ntd_rows,
  sum(CASE WHEN currency = 'NTD' AND fx_rate = 1 THEN 1 ELSE 0 END) AS v4_ntd_fx_1,
  sum(CASE WHEN product_sk = -1 THEN 1 ELSE 0 END) AS v6_product_sk_minus1,
  sum(CASE WHEN member_sk IS NULL THEN 1 ELSE 0 END) AS member_sk_null,
  sum(CASE WHEN order_status = 'completed' AND departure_date_sk > CAST(date_format(updated_at, 'yyyyMMdd') AS INT) THEN 1 ELSE 0 END) AS l10_completed_departure_not_reached,
  sum(CASE WHEN currency IN ('TWD','NTD') THEN 1 ELSE 0 END) AS twd_ntd_rows_kept,
  count(DISTINCT order_id) AS distinct_order_id
FROM fact_ratio
```

| fact_rows | v1_negative | v2_about_x1000 | v3_coupon_negative_left | v3_coupon_null | v4_ntd_rows | v4_ntd_fx_1 | v6_product_sk_minus1 | member_sk_null | l10_completed_departure_not_reached | twd_ntd_rows_kept | distinct_order_id |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 99950 | 0 | 40 | 0 | 299 | 200 | 200 | 120 | 0 | 28578 | 66832 | 99950 |

### [P-BASE.amount_impact] V1、V2 在 fact 的列數、amount_twd 總和與佔全表 amount_twd 的比例（V1 已由合約擋下，應為 0 列）

```sql
SELECT
  CASE WHEN amount < 0 THEN 'v1_negative'
       WHEN ratio > 1.3 AND ratio / 1000 BETWEEN 0.8 AND 1.3 THEN 'v2_about_x1000'
       ELSE 'other' END AS grp,
  count(*) AS n, sum(amount_twd) AS amount_twd_sum,
  round(100 * sum(amount_twd) / (SELECT sum(amount_twd) FROM fact_order), 2) AS pct_of_total
FROM fact_ratio GROUP BY 1 ORDER BY 1
```

| grp | n | amount_twd_sum | pct_of_total |
|---|---|---|---|
| other | 99910 | 25866981830.39 | 71.91 |
| v2_about_x1000 | 40 | 10102491689.70 | 28.09 |

### [P-BASE.l10_impact] L10：completed 且出發日未到的列佔 completed 的比例與金額

```sql
SELECT sum(CASE WHEN order_status = 'completed' THEN 1 ELSE 0 END) AS completed_rows,
  sum(CASE WHEN order_status = 'completed' AND departure_date_sk > CAST(date_format(updated_at, 'yyyyMMdd') AS INT) THEN 1 ELSE 0 END) AS not_reached,
  sum(CASE WHEN order_status = 'completed' AND departure_date_sk > CAST(date_format(updated_at, 'yyyyMMdd') AS INT) THEN amount_twd END) AS not_reached_amount_twd
FROM fact_order
```

| completed_rows | not_reached | not_reached_amount_twd |
|---|---|---|
| 28578 | 28578 | 10324629272.48 |

### [P-BASE.fact_currency] fact 的幣別分布

```sql
SELECT currency, count(*) AS n, sum(amount_twd) AS amount_twd_sum FROM fact_order GROUP BY currency ORDER BY currency
```

| currency | n | amount_twd_sum |
|---|---|---|
| JPY | 11017 | 4576607489.88 |
| NTD | 200 | 54561733.00 |
| TWD | 66632 | 23602667357.00 |
| USD | 22101 | 7735636940.21 |

### [P-BASE.v5_dates] V5：fact 的台北下單日範圍（Z 與無標記格式換算後）

```sql
SELECT min(order_date_sk) AS min_order_date_sk, max(order_date_sk) AS max_order_date_sk,
  sum(CASE WHEN order_date_sk < 20260501 THEN 1 ELSE 0 END) AS before_0501 FROM fact_order
```

| min_order_date_sk | max_order_date_sk | before_0501 |
|---|---|---|
| 20260501 | 20260630 | 0 |

### [P-BASE.v7_quarantine] V7：隔離表中 base 的 duplicate 列，與 fact 保留列的 updated_at 比較

```sql
SELECT q.reject_category, count(*) AS n,
  sum(CASE WHEN f.updated_at > to_timestamp(q.updated_at) THEN 1 ELSE 0 END) AS kept_row_is_newer
FROM quarantine_order q LEFT JOIN fact_order f USING (order_id) WHERE q.batch_id = 'base' GROUP BY q.reject_category
```

| reject_category | n | kept_row_is_newer |
|---|---|---|
| duplicate | 40 | 40 |
| contract | 50 | 0 |

### [P-MEM.v8_same_day] V8：同日矛盾的 30 位，dim_member 第一版的等級是否為較高者

```sql
WITH r AS (SELECT member_id, extract_date, member_level,
    CASE member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END AS rk
  FROM members_raw),
c AS (SELECT member_id, max(rk) AS max_rk FROM r GROUP BY member_id, extract_date HAVING count(*) > 1),
first AS (SELECT * FROM dim_member
  QUALIFY row_number() OVER (PARTITION BY member_id ORDER BY valid_from) = 1)
SELECT count(*) AS conflict_members,
  sum(CASE WHEN CASE f.member_level WHEN '一般' THEN 1 WHEN '銀卡' THEN 2 WHEN '金卡' THEN 3 WHEN '白金' THEN 4 END = c.max_rk THEN 1 ELSE 0 END) AS first_version_is_higher_level
FROM c JOIN first f USING (member_id)
```

| conflict_members | first_version_is_higher_level |
|---|---|
| 30 | 30 |

### [P-MEM.v9_v10_placeholders] V9、V10、J9：dim_member 中的哨兵值與被覆寫的真實生日

```sql
SELECT count(*) AS dim_rows,
  count(DISTINCT member_id) AS members,
  sum(CASE WHEN city = 'N/A' THEN 1 ELSE 0 END) AS city_na_left,
  sum(CASE WHEN city IS NULL THEN 1 ELSE 0 END) AS city_null_rows,
  count(DISTINCT CASE WHEN city IS NULL THEN member_id END) AS city_null_members,
  sum(CASE WHEN birth_date = DATE '1900-01-01' THEN 1 ELSE 0 END) AS birth_1900_left,
  count(DISTINCT CASE WHEN birth_date IS NULL THEN member_id END) AS birth_null_members,
  count(DISTINCT CASE WHEN member_id IN ('M001647', 'M001931', 'M003842') AND birth_date IS NOT NULL THEN member_id END) AS j9_examples_keep_real_birth
FROM dim_member
```

| dim_rows | members | city_na_left | city_null_rows | city_null_members | birth_1900_left | birth_null_members | j9_examples_keep_real_birth |
|---|---|---|---|---|---|---|---|
| 8772 | 8000 | 0 | 65 | 65 | 0 | 61 | 3 |

### [P-MEM.j9_all] J9：真實生日 → 1900 的 5 位，dim_member 的生日

```sql
WITH s AS (SELECT member_id, birth_date,
    lag(birth_date) OVER (PARTITION BY member_id ORDER BY extract_date, member_level) AS prev_birth FROM members_raw),
j9 AS (SELECT DISTINCT member_id, prev_birth FROM s WHERE birth_date = '1900-01-01' AND prev_birth <> '1900-01-01')
SELECT j9.member_id, j9.prev_birth AS real_birth_in_source, max(d.birth_date) AS dim_birth
FROM j9 JOIN dim_member d USING (member_id) GROUP BY ALL ORDER BY 1
```

| member_id | real_birth_in_source | dim_birth |
|---|---|---|
| M001647 | 1961-07-15 | 1961-07-15 |
| M001931 | 1992-03-26 | 1992-03-26 |
| M003842 | 1999-09-01 | 1999-09-01 |
| M004004 | 1994-10-13 | 1994-10-13 |
| M006636 | 1992-11-06 | 1992-11-06 |

### [P-MEM.versions] L9、L11：dim_member 版本數（內容沒變不開版）；沒有「未知會員」列（member_sk = -1 或 member_id 為 NULL 應為 0；member_sk 是 xxhash64，本來就可能是負數）

```sql
SELECT count(*) AS versions, count(DISTINCT member_id) AS members,
  count(*) - count(DISTINCT member_id) AS extra_versions,
  sum(CASE WHEN is_current THEN 1 ELSE 0 END) AS current_rows,
  sum(CASE WHEN member_sk = -1 OR member_id IS NULL THEN 1 ELSE 0 END) AS unknown_member_rows
FROM dim_member
```

| versions | members | extra_versions | current_rows | unknown_member_rows |
|---|---|---|---|---|
| 8772 | 8000 | 772 | 8000 | 0 |

### [P-MEM.quarantine] 會員隔離表（快照違規列）與訂單隔離表的 member_missing（訂單對不到會員版本）列數

```sql
SELECT (SELECT count(*) FROM quarantine_member) AS member_quarantine_rows,
  (SELECT count(*) FROM quarantine_order WHERE reject_category = 'member_missing') AS order_member_missing_rows
```

| member_quarantine_rows | order_member_missing_rows |
|---|---|
| 0 | 0 |

### [P-FACT.check_constraints] fact_order 的 Delta CHECK 約束（建表時加上）

| constraint | expression |
|---|---|
| amount_positive | amount > 0 |
| coupon_discount_non_negative | coupon_discount IS NULL OR coupon_discount >= 0 |
| currency_valid | currency IN ( 'TWD' , 'NTD' , 'USD' , 'JPY' ) |
| member_sk_not_null | member_sk IS NOT NULL |
| order_id_not_null | order_id IS NOT NULL |
| order_status_valid | order_status IN ( 'created' , 'paid' , 'cancelled' , 'completed' ) |

### [P-DAY1.reconciliation] load_incremental day1

| 項目 | 值 |
|---|---|
| `input_rows` | 4615 |
| `fact_rows` | 4000 |
| `quarantined_rows` | 615 |
| `quarantined_by_category` | {'collision': 6, 'duplicate': 15, 'collision_existing': 594} |
| `skipped_rows` | 0 |
| `amount_review_rows` | 0 |
| `amount_twd_sum` | 1056883370.88 |
| `unknown_product_rows` | 0 |
| `unknown_member_rows` | 0 |
| `member_rejected_rows` | 0 |
| `fact_table_rows` | 103950 |
| `fact_table_amount_twd_sum` | 37026356890.97 |
| `balanced` | True |

### [P-DAY2.reconciliation] load_incremental day2

| 項目 | 值 |
|---|---|
| `input_rows` | 4700 |
| `fact_rows` | 4060 |
| `quarantined_rows` | 615 |
| `quarantined_by_category` | {'collision': 2, 'duplicate': 15, 'collision_existing': 598} |
| `skipped_rows` | 25 |
| `amount_review_rows` | 0 |
| `amount_twd_sum` | 1039558224.11 |
| `unknown_product_rows` | 0 |
| `unknown_member_rows` | 0 |
| `member_rejected_rows` | 0 |
| `fact_table_rows` | 108010 |
| `fact_table_amount_twd_sum` | 38065915115.08 |
| `balanced` | True |

### [P-DAY3.reconciliation] load_incremental day3

| 項目 | 值 |
|---|---|
| `input_rows` | 4615 |
| `fact_rows` | 4000 |
| `quarantined_rows` | 615 |
| `quarantined_by_category` | {'collision': 4, 'duplicate': 15, 'collision_existing': 596} |
| `skipped_rows` | 0 |
| `amount_review_rows` | 0 |
| `amount_twd_sum` | 1020981665.19 |
| `unknown_product_rows` | 0 |
| `unknown_member_rows` | 0 |
| `member_rejected_rows` | 0 |
| `fact_table_rows` | 112010 |
| `fact_table_amount_twd_sum` | 39086896780.27 |
| `balanced` | True |

### [P-L4.after_day3] L4 的 25 個 id 跑完 day1～day3 後在 fact 的狀態（預期 25 列 cancelled）

```sql
SELECT order_status, batch_id, count(*) AS n FROM delta.`/tmp/liontest_a3/wh/fact_order`
WHERE order_id IN ('ORD00102886', 'ORD00102183', 'ORD00102726', 'ORD00100117', 'ORD00103317', 'ORD00102113', 'ORD00100596', 'ORD00100020', 'ORD00102385', 'ORD00100123', 'ORD00102024', 'ORD00102817', 'ORD00100619', 'ORD00101579', 'ORD00100670', 'ORD00101750', 'ORD00100934', 'ORD00103847', 'ORD00103606', 'ORD00103740', 'ORD00101215', 'ORD00100797', 'ORD00100164', 'ORD00102401', 'ORD00102853') GROUP BY ALL ORDER BY ALL
```

| order_status | batch_id | n |
|---|---|---|
| cancelled | day1 | 25 |

### [P-ALL.amount_excluding_review] 三天後：fact 的 amount_twd 總和（所有狀態、折扣前），與排除金額人工確認清單上訂單後的總和（不是營收的定義，營收由下游語意層決定）

```sql
SELECT
  SUM(f.amount_twd) AS amount_twd_total,
  SUM(CASE WHEN r.order_id IS NULL THEN f.amount_twd END) AS amount_twd_excluding_review,
  COUNT(r.order_id) AS review_orders
FROM delta.`/tmp/liontest_a3/wh/fact_order` AS f
LEFT JOIN (SELECT DISTINCT order_id FROM delta.`/tmp/liontest_a3/wh/amount_review`) AS r
  ON f.order_id = r.order_id
```

| amount_twd_total | amount_twd_excluding_review | review_orders |
|---|---|---|
| 39086896780.27 | 28984405090.57 | 40 |

## 附錄 C：問題對照表

**正文的每個問題，在這裡對到編號、管線步驟、筆數與查詢。** 查詢標籤的 SQL 與輸出見[附錄 B](#附錄-b查詢與輸出)；各步驟的細節見[附錄 F](#附錄-f管線步驟細節)；正文用語和技術用語的對照見[附錄 G](#附錄-g名詞表)。

- **筆數**：依序是 base／day1／day2／day3（base＝正文的“5～6 月總檔”，day1～day3＝“7/1～7/3 更新檔”）。會員的筆數依序是 04-30／05-31／06-30 三份快照。
- **編號**：V＝違反約束（資料一定錯），L＝可能合法（不一定是錯），J＝需要判斷語意，N＝撰寫本報告時新增，只當索引用。
- **問題總數**：29 個編號＝**27 個實際發生的問題**（C-1～C-27）＋ 1 個已檢查、不是錯誤（C-28，L12：本幣不列在匯率表是常見設計）＋ 1 個防護性設計（C-29，N2，本資料 0 筆）。
- **對帳**：正文“三天處理結果”的數字來自管線實跑（part_a/README.md“三天實跑的對帳”）；DuckDB 照同樣規則重算的 `[Q-POST.totals]` 完全相同。正文“計入報表”＝寫進 fact；“擋下待查”＝隔離表；“不採用”＝略過（類別 `late_event`，列仍留在隔離表，但對帳時單獨計數）。正文的“排除人工確認清單後的金額總和”是 fact 所有狀態、折扣前 `amount_twd` 的總和，扣掉 `amount_review` 上的訂單：`[P-ALL.amount_excluding_review]`（管線實跑，查詢是 `fact_order.py` 的 `AMOUNT_EXCLUDING_REVIEW_SQL`）和 part_a/README.md 4.8 相同；差額 10,102,491,689.70 也等於 `[Q-POST.v2_share]` 的 `v2_amount_twd`。這不是營收的定義，營收的定義由下游語意層決定。

| 對照 | 正文的問題 | 編號 | 管線步驟 | 筆數（base／day1／day2／day3） | 查詢標籤 |
|---|---|---|---|---|---|
| C-1 | 金額多了 1,000 倍 | V2 | ⑧ 對維度（列人工確認清單 `amount_review`） | 40／0／0／0 | `Q-V2.examples`、`Q-V2.x1000_detail`、`Q-AMT.ratio_range`、`Q-AMT.ratio_buckets`、`Q-POST.v2_share`、`Q-V2.div1000_estimate` |
| C-2 | 每天約 600 筆撞號 | J2 | ④ 與既有 fact 撞號 | 偵測 —／603／602／603；隔離 0／594／598／596 | `Q-J2.example`、`Q-J2.overlap`、`Q-J2.impact`、`Q-J2.blocked_amount` |
| C-3 | 在出發前就標成已完成 | L10 | 只記錄、管線不處理 | fact 28,578／0／0／0（增量原始 321／313／289 全是撞號列） | `Q-L10.example`、`Q-L10.completed_before_departure`、`Q-L10.after_dedupe`、`Q-L10.reverse`、`Q-L10.vs_0701`、`Q-L10.incremental_split`、`Q-POST.l10` |
| C-4 | 金額是負數 | V1 | ① 讀取與合約 | 50／0／0／0 | `Q-V1.examples`、`Q-V1.negative`、`Q-POST.v1_overlap` |
| C-5 | 已取消又收到較早的已付款 | L4 | ⑤ 狀態機 | 略過 0／0／25／0 | `Q-L4.example`、`Q-L4.cross_day`、`Q-L4.day2_upd_dates`、`Q-L4.impact`、`Q-POST.l4_final` |
| C-6 | 折扣寫 -1 | V3 | ① 讀取與合約（轉 NULL） | 300／0／0／0（fact 299） | `Q-V3.coupon`、`Q-AMT.overlap`、`Q-POST.totals` |
| C-7 | 金額是折扣前還是後 | J10 | ⑧ 算淨額（`net_amount_twd`） | 全部訂單 | `Q-N3.coupon_by_currency` |
| C-8 | 折扣固定台幣，和訂單幣別不一致 | N3 | ⑧ 算淨額 | 全部訂單 | `Q-N3.coupon_by_currency` |
| C-9 | 日圓金額帶小數 | L5 | 只記錄 | 80／0／0／0 | `Q-L5.jpy_fraction` |
| C-10 | 下單時間三種寫法 | V5 | ① 讀取與合約 | 3,001＋3,001／0／0／0（字面日期差一天 1,003） | `Q-V5.example`、`Q-V5.formats`、`Q-V5.z_date_shift`、`Q-V5.tz_evidence_dup`、`Q-V5.tz_evidence_order`、`Q-V5.z_before_0501` |
| C-11 | 6 月訂單 7/2 才送到 | L3 | ⑧ 對維度（當新單寫入） | 0／0／60／0 | `Q-L3.example`、`Q-L3.late_new_orders`、`Q-L3.detail`、`Q-L3.paid_after_departure`、`Q-L3.june_change` |
| C-12 | 更新時間晚於檔名日期 | L1 | 只記錄 | —／3,290／3,257／3,263 | `Q-L1.upd_after_batch` |
| C-13 | 總檔有 7 月的更新時間 | L2 | 只記錄 | 2,265／—／—／— | `Q-L2.base_upd_after_period` |
| C-14 | 同一天的檔裡兩張單同編號 | J3 | ② 同批撞號 | 0／6／2／4 列（3／1／2 組） | `Q-J3.example`、`Q-INC.samefile` |
| C-15 | 同一筆送兩次 | V7 | ③ 完全重複去重 | 40 組（多 40 列）／0／0／0 | `Q-V7.groups`、`Q-V7.examples`、`Q-V5.tz_evidence_dup` |
| C-16 | 更新檔同一筆重送 | N1 | ③ 完全重複去重 | 0／15／15／15 組 | `Q-INC.samefile` |
| C-17 | 會員同一天兩筆、等級不同 | V8 | 前置 C 會員維度 | 30 位／0／0（快照） | `Q-V8.example`、`Q-V8.same_day`、`Q-MEM.level_moves`、`Q-V8.later_snapshot` |
| C-18 | 城市寫 N/A | V9 | 前置 C 會員維度 | 66／3／2 列（70 人） | `Q-V9V10.placeholders`、`Q-V9.members`、`Q-V9.na_before_real`、`P-MEM.v9_v10_placeholders` |
| C-19 | 生日寫 1900-01-01 | V10 | 前置 C 會員維度 | 76／2／3 列（80 人） | `Q-V9V10.placeholders`、`Q-V10.birth_min` |
| C-20 | 真實生日被蓋掉 | J9 | 前置 C 會員維度 | 5 人 | `Q-J9.example`、`Q-J9.birth_direction` |
| C-21 | 等級、城市改變 | L9 | 前置 C 會員維度（SCD2 開新版本） | 等級 434 人、城市 376 人（排除 N/A 367 人） | `Q-L9.changes`、`Q-MEM.level_moves` |
| C-22 | 後一次匯出和前一次相同 | L11 | 前置 C 會員維度（不開新版本） | 0／95／91 列 | `Q-L11.identical` |
| C-23 | 註冊時未滿 18 歲 | L8 | 只記錄 | 455 列（398 人） | `Q-L8.under18` |
| C-24 | 產品不在產品清單 | V6 | ⑧ 對維度（`product_sk` = -1） | 120／0／0／0 | `Q-V6.unknown_product`、`Q-AMT.ratio_buckets` |
| C-25 | 產品已下架 | L6 | 只記錄 | fact 4,267／163／154／163（原始 4,270／184／182／195） | `Q-L6.inactive`、`Q-POST.l6` |
| C-26 | 同名不同產品編號 | L7 | 只記錄 | 44 個名稱 | `Q-L7.example`、`Q-L7.dup_name` |
| C-27 | 幣別寫成 NTD | V4 | ⑥ 換匯 | 200／0／0／0 | `Q-V4.ntd`、`Q-POST.currency` |
| C-28 | 匯率表不列台幣（不是錯誤） | L12 | ⑥ 換匯（left join，TWD 匯率 1） | TWD＋NTD 訂單 66,890／3,069／3,150／3,141 列 | `Q-FX.coverage`、`Q-POST.currency` |
| C-29 | 下單當天找不到匯率（防護性設計） | N2 | ⑥ 換匯（隔離類別 `fx_missing`） | 0／0／0／0 | `Q-FX.coverage` |

**C-3 的基準說明**：`[Q-L10.vs_0701]` 把兩件事分開算。“標成 completed 時出發日還沒到”看的是出發日是否晚於最後更新日（台北日期）：base 每個編號一列時 28,596 張全部如此，寫進 fact 的 28,578 張也全部如此。“以 07-01 為基準出發日已過”是另一件事：base 每個編號一列時是 6,149 張，寫進 fact 的是 6,147 張，差的 2 張是被合約擋下的負數金額訂單。正文的反向證據（paid 9,234、created 3,053）出自 `[Q-L10.reverse]`，基準日同樣是 07-01，範圍是 base 每個編號取最新一列。

## 附錄 D：決策與原話對照

**正文的“判斷理由”是白話轉述，這裡放逐字原話與出處。** 本附錄的“使用者”＝我（本報告作者），也就是正文裡的“我”。原話都出自 `ai-collab/process-log.md`；“出處”是 process-log 的事件標題。決策來源分四種，照實標示：

- **使用者定案**：使用者自己提出理由（選項可能是 AI 列的、AI 也可能給過建議）。
- **AI 建議、使用者採用**：做法由 AI 提出，使用者接受。理由文字是誰寫的，在該列註明。
- **AI 說明慣例、使用者採用**：AI 先說明業界慣例，使用者以“依慣例”採用。
- **官方說明**：官方 `candidate_package/README.md` 已經寫明，使用者另外用資料確認。
- **實作慣例**：沒有使用者定案。

**本資料實際發生的問題**

| 對照 | 決策 | 決策來源 | 原話（逐字） | 出處 |
|---|---|---|---|---|
| C-1 | 金額照原樣寫入，列人工確認清單 | 使用者定案 | 「沒辦法系統性的處理 金額問題我判斷成case by case」；「因為沒辦法在pipline前有效判斷出問題」 | A-3：哪些品質問題要處理、哪些只記錄；V2 疑似多乘 1,000：照原樣寫入，另列清單 |
| C-1 | 人工確認前，清單上的訂單不計入下游的金額指標；訂單仍留在 fact（B1，不改成進隔離表） | 使用者定案（AI 列 A 照算、B 確認前排除、C 兩個數字都給三個選項，建議 C；使用者選 B，再從 AI 列的 B1、B2 選 B1） | 「因為已經有前面指標進入隔離我認為就應該人工審查後在進入下流」 | V2 的 40 張：留在 fact，正式營收在人工確認前排除（業務假設 [3.7](../business-assumptions.md#37-人工確認前待確認訂單不計入下游的金額指標)） |
| C-2、C-14 | 撞號進隔離表，不覆寫 | 使用者定案 | 「把撞號當 noise 處理」；ADR-03：「訂單的基本資訊不能被修改」 | 增量檔與 base 撞號的列當 noise 處理；ADR-01～04 定稿 |
| C-3 | completed 維持出團完成的假設，只記錄 | 使用者定案 | 「completed先假設成出團完成」；「先把狀態規則定下來 之後比較好處理」 | 假設 completed 是出團完成，與 base 資料衝突；completed 維持出團完成，28,612 列當資料品質問題 |
| C-4 | 負數金額在合約層擋下 | 使用者定案（AI 建議過同一選項） | 「負數在合約層就該擋下」 | V1 負數金額：合約層擋下進隔離表 |
| C-5 | 以 updated_at 判斷新舊；晚到的舊事件略過、留在隔離表 | 使用者定案 | 「照 updated_at，符合狀態機單向假設」；「晚到事件不該當成狀態轉移」；「我傾向統一紀錄狀況外的事件」 | 增量新舊以 updated_at 判斷；狀態機檢查採 C：晚到事件分開處理；晚到事件也留在隔離表，類別標為略過 |
| C-6 | coupon -1 轉 NULL | 使用者定案（AI 建議過同一選項） | 「-1 代表未知，轉 NULL 不要猜」 | V3 coupon -1.0：轉 NULL，訂單照常寫入 |
| C-7 | amount 定義為折扣前，另加淨額 | 使用者定案 | 「可以定義好業務邏輯處理」；「那折扣前」；「我的設計傾向紀錄所有金額」 | J10：amount 定義為折扣前，fact 加 net_amount_twd |
| C-8 | coupon 當台幣 | **官方說明**：官方 `candidate_package/README.md` 的欄位說明寫 “`coupon_discount`（TWD）”；使用者另外用資料確認，結論相同 | 使用者的資料確認：「coupon 當 TWD，三種幣別面額一樣」 | coupon_discount 當台幣；共用業務假設文件；AI 誤稱官方沒寫 coupon 幣別（業務假設 [3.8](../business-assumptions.md#38-對照coupon-是-twd)） |
| C-3、C-9、C-12、C-13、C-23、C-25、C-26 | 只記錄、管線不處理 | 使用者定案 | 「有些問題可以只記錄下來 不需要特別處理」 | A-3：哪些品質問題要處理、哪些只記錄 |
| C-10 | 無時區標記的下單時間當台北時間 | 使用者定案 | 「台北 因為重複列跟時間先後都對得上」 | 無時區標記的下單時間當台北時間 |
| C-11 | 晚到新單當新單寫入，下單日照原始資料 | 使用者定案 | 「訂單屬於下單那天，晚到只是傳遞延遲」 | A-3 剩下四題：N2、L3、V6、L11 |
| C-15、C-16 | 完全重複取 updated_at 最新一列 | 使用者定案（規則由 AI 提出） | 「網路重送造成的重複，留最新一列就好」；成因：「v7根據我的經驗是網路波動導致的重複寫入 可以重寫入端或是schena的unique index改善」 | 完全相同的重複列：取 updated_at 最新一列；V7 base 重複列：使用者判斷是網路波動造成的重複寫入 |
| C-17 | 同日兩列取較高等級 | 使用者定案 | 「假設會員系統也是同樣的行為才選擇的行為」 | dim_member 同日矛盾的 30 位取較高等級 |
| C-18、C-19、C-20 | 假值轉 NULL，不蓋真值；城市從 NULL 變真實值時開新版本 | 使用者定案（接受 AI 的三項建議，理由是自己的） | 「新會員訂單要對得到版本，更正不算歷史，假值不能蓋真值」；「不是使用null就好」 | dim_member SCD2 規則；dim_member：城市從 NULL 變成真實值時開新版本 |
| C-21 | 新版本從觀察到變動的快照日開始 | 使用者定案 | 「只記錄確定知道的事」 | dim_member：新版本從觀察到變動的快照日開始 |
| C-22 | 快照沒變就不開新版本 | AI 建議、使用者採用（理由文字由 AI 撰寫，使用者照這段回覆當作理由） | 「SCD2 追蹤的是狀態的變化，不是觀察的次數。用 Type 2 欄位比對變化，沒變就不開版本。這樣維度的粒度正確，重送快照時也保持冪等，這跟 dbt snapshot 的 check 策略相同。」 | A-3 剩下四題：N2、L3、V6、L11 |
| C-24 | 未知產品保留訂單，`product_sk` = -1 | 使用者定案 | 「我認為訂單是主要的事實表 也是分析資料的中心思考分方式 而商品可能經過時間迭代 有消失的可能 因此以進客能保留訂單的方式處理」；改善方案：「可以是未知商品就幫忙創一筆」、「先維持 這是之後的改善方案」 | A-3 剩下四題：N2、L3、V6、L11 |
| C-27、C-28 | NTD 當 TWD、原幣別保留；TWD 匯率固定 1 | AI 建議、使用者採用（理由是使用者的話；這句講的是“原幣別與台幣兩種金額都存”，不是針對 NTD） | 「原幣別保留可追溯，換算 TWD 讓營收能直接加總」 | 金額：原幣別與換算 TWD 都存 |
| 全部金額 | 台幣金額四捨五入（HALF_UP 到小數 2 位） | 實作慣例 | 無 | 無 |
| 資料限制 1 | 根本解法在上游（會員記錄更新時間） | 使用者提出 | 「這個問題不要應該要從member中改善嗎 應該紀錄update time嗎」 | dim_member：新版本從觀察到變動的快照日開始 |
| 本報告用詞 | Part A 不定義營收；金額一律照實寫範圍（例如“折扣前、含所有狀態”），營收的定義移到下游語意層（Part C） | AI 建議、使用者採用（使用者先質疑為什麼 Part A 要決定營收口徑，AI 承認是自己把指標定義帶進 Part A） | 「為什麼part a需要決策 營收要不要算已取消的訂單、用折扣前還是折扣後」；「照這樣改」 | 營收的定義不在 Part A 決定，移到 Part C 語意層 |
| 本報告結構 | 正文寫給主管、技術內容放附錄 | 使用者提出，AI 給分層做法，使用者採用 | 「這份是要交給主管看的應該要減少技術性名詞」 | A-3 正文寫給主管看，技術內容移到附錄 |

**防護性設計（本資料 0 筆）**

| 對照 | 決策 | 決策來源 | 原話（逐字） | 出處 |
|---|---|---|---|---|
| E-1 | 已完成的批次訂單檔被改過就停，要用 force 重跑並留紀錄 | 使用者定案 | 「要避免訂單狀態可以被隨意修改 如果要修改需要使用force來紀錄」 | checksum 涵蓋參考資料：訂單檔不同就擋，參考資料不同只警告 |
| E-4 | 產品清單有壞列就整批停 | 使用者定案 | 「晚一點進來比錯的資料好」 | 產品清單有壞列就整批停 |
| E-5 | 匯率表壞一列就整批停 | 使用者定案（原本是實作者自行延伸，AI 建議整批停，使用者 2026-10-19 補定） | 「匯率影響的是訂單金額 這個程度比較大 需要事先停止」 | 匯率表壞一列就整批停 |
| E-6 | 會員快照依序處理，靠批次紀錄 | 使用者定案 | 「批次可以節省過去已經成功的事件執行時間 可以避免時間導致的停止問題 如果每次都在一個小時的時間點失敗 這樣重新執行也可從第二個小時開始」 | 中途停止：冪等步驟＋批次紀錄 |
| E-7 | 會員快照違規列另開會員隔離表 | **AI 說明慣例、使用者採用**：使用者問 DE 角度怎麼處理，AI 說明 Databricks quarantine 與 Kimball error event table 兩種業界做法、主檔壞列不蓋好版本的慣例，AI 建議另開會員隔離表；使用者以這句採用 | 「根據DE的慣例」 | 會員快照的違規列：另開會員隔離表 |
| E-8、E-9 | 檔案層級整批停、列層級進隔離表 | 使用者定案 | 「pipline中應該要有data cleaning」 | 型別違規：檔案層級整批停、列層級進隔離表 |
| E-10 | 值域放合約層 | 使用者定案（研究 agent 先做業界評估） | 「值域是 schema 的一部分」 | T6 第二階段前的四個細節；讀取驗證層經業界評估 |
| E-11 | 中間夾其他狀態不算重複 | 使用者定案 | 「中間如果有出現其他狀態 不能當作延遲」 | 重複只算時間上相鄰的相同列 |
| E-12 | 同批多個新狀態寫最後一個，和重送分開記 | 使用者定案 | 「重送和狀態更新成因不同要分開記」 | T6 第二階段前的四個細節；讀取驗證層經業界評估 |
| E-13、E-14 | 往回走、晚到走不到都進隔離表 | 使用者定案 | 「晚到事件不該當成狀態轉移」 | 狀態機檢查採 C：晚到事件分開處理 |
| E-15 | 不合法之後的事件一起隔離；防護性設計要標記 | 使用者定案 | 「鏈斷掉後面的資料就不可信」；「防護性的設計幫我標記」 | 不合法轉移之後的事件一起隔離；防護性設計要標記 |
| E-16 | 同一秒不同狀態全部隔離，之前的合法事件照寫 | 使用者定案 | 「資料不足時不要讓管線自己猜」；「斷點之前的資料沒有問題」 | 同一秒內出現不同狀態：兩列都進隔離表；T6 第二階段前的四個細節；讀取驗證層經業界評估 |
| E-17 | 跳過中間狀態合法照寫，只計數 | 使用者定案 | 「在沒辦法確定是事件驅動還是快照的情況下 逐段也用可達性」；「在不影響下游分析的情況下 先設計成紀錄log 不要過度設計」 | 狀態檢查一律用可達性，不用一步轉移表；T6 第二階段前的四個細節；讀取驗證層經業界評估 |
| E-18 | 找不到匯率進隔離表，不用前一天的 | 使用者定案 | 「資料不足時不要讓管線自己猜」 | A-3 剩下四題：N2、L3、V6、L11 |
| E-19 | 負 coupon 擋下、太大的 coupon 列清單 | 使用者定案（AI 建議過同一選項） | 「負數coupon沒有合理解釋，太大的可能是全額折抵」 | net 變負數：負的 coupon 在合約擋下，太大的 coupon 只列清單 |
| E-20 | 會員對不到版本進隔離表 | 使用者定案（AI 原本建議落 -1，使用者沒有採用） | 「在訂單重要度之後是會員資料 如果有未知會員資料在做客戶分析是一件困難的事 所以要有錯誤提醒修正data pipline」 | 會員對不到版本：進隔離表，不落 -1 |
| E-21 | Delta CHECK 只加在關鍵欄位 | 使用者定案（AI 建議過同一選項） | 「Delta CHECK 是最後一道防線，擋得住繞過管線的寫入」 | Delta CHECK 約束：只加在關鍵欄位，當最後一道防線 |

## 附錄 E：防護性設計清單

**本資料 0 筆、為正式環境預先做的處理共 17＋3 項。** 17 項和資料內容有關（狀態與幣別的值域是同一條規則，算一項；淨額變負數分兩段處理，算一項）；前置 A 的 3 項和重跑、參考資料版本有關，不是資料內容的問題，另外列。收尾的 Delta CHECK 重複既有的合約規則，不是新的問題類別，兩者都不算，列在最後。“0 筆”的證據有兩種：管線三天實跑（part_a/README.md“每種狀況的處理”，四批各分類都是 0），以及 DuckDB 直接查 CSV 的預檢。

| 對照 | 步驟 | 情況 | 處理 | 0 筆的證據 | 實作 |
|---|---|---|---|---|---|
| E-1 | 前置 A（重跑） | 已跑完的批次，訂單檔後來被改過 | 停下報錯；要重跑必須用 force | 四批都是第一次執行 | 已完成（b975543） |
| E-2 | 前置 A（重跑） | 已跑完的批次，參考資料和當時不同 | 只警告，照常跳過 | 同上 | 已完成（92b8d85） |
| E-3 | 前置 A（重跑） | 強制重跑 | 先追加一筆紀錄（批次、時間、新舊檔案指紋），只增不改 | 沒有強制重跑 | 已完成（92b8d85） |
| E-4 | 前置 B | 產品清單有壞列，或同一個產品編號出現兩次 | 整批停 | 四批都沒有停；`[Q-L7.dup_name]` 0 | 已完成（b975543 以前） |
| E-5 | 前置 B | 匯率表有壞列，或同一天同一幣別有兩個匯率 | 整批停 | 四批都沒有停；`[Q-FX.table]` 0 | 已完成（b975543 以前） |
| E-6 | 前置 C | 會員快照晚到（05-31 比 06-30 晚送） | 批次紀錄強制依序處理 | 四批依序完成；`[Q-MEM.both_0531_0630]` 0 位 | 已完成（b975543 以前） |
| E-7 | 前置 C | 會員快照有壞列（等級不在清單、註冊日晚於快照日） | 另開會員隔離表；壞列不蓋掉上一個好版本 | `[Q-MEM.register_after_extract]` 0；`[P-MEM.quarantine]` 會員隔離表 0 列 | 已完成（9f9d415） |
| E-8 | ① | 檔案不存在、表頭不對、空檔 | 整批停 | 7 個檔都讀得到（`[Q-000.rows]`） | 已完成（b975543 以前） |
| E-9 | ① | 單列格式不對 | 進隔離表 | 負數金額以外 0 列；`[Q-001.contract]` 0 | 已完成（b975543 以前） |
| E-10 | ① | 狀態、幣別不在允許值 | 進隔離表 | 0；`[Q-DOM.status_currency]` | 已完成（b975543 以前） |
| E-11 | ③ | 相同的列中間夾著其他狀態 | 不算重複，交給狀態機 | 0 | 已完成（b975543 以前） |
| E-12 | ⑤ | 同一批裡有好幾個比 fact 新的合法狀態 | 寫最後一個，較早的進隔離表（`superseded`） | 0 | 已完成（b975543 以前） |
| E-13 | ⑤ | 狀態往回走 | 進隔離表，fact 不更新 | 0；`[Q-SM.chain]` 的 `not_reachable` | 已完成（b975543 以前） |
| E-14 | ⑤ | 晚到，而且舊狀態走不到現在的狀態 | 進隔離表 | 同上 | 已完成（b975543 以前） |
| E-15 | ⑤ | 不合法之後，同一批的其他事件 | 一起進隔離表 | 同上 | 已完成（b975543 以前） |
| E-16 | ⑤ | 同一張單、同一秒、不同狀態 | 這些列全部進隔離表 | 0；`[Q-SM.same_second]` | 已完成（b975543 以前） |
| E-17 | ⑤ | 跳過中間狀態（created → completed） | 合法，照寫，只在對帳計數 | 0；`[Q-SM.chain]` 的 `skipped_intermediate` | 已完成（b975543 以前） |
| E-18 | ⑥ | 下單那天找不到匯率（N2） | 進隔離表，不拿前一天的匯率 | 0；`[Q-FX.coverage]` | 已完成（b975543 以前） |
| E-19 | ① ＋ ⑧ | 淨額變負數 | -1 以外的負 coupon 在合約擋下；coupon 大於台幣金額照寫、列進人工確認清單 | `[Q-POST.net_guard]` 全 0；人工確認清單四批只有多 1,000 倍的 40 張（`[P-BASE.reconciliation]`、`[P-DAY1.reconciliation]`～`[P-DAY3.reconciliation]` 的 `amount_review_rows`） | 已完成（92b8d85） |
| E-20 | ⑧ | 訂單對不到會員版本 | 進訂單隔離表（類別 `member_missing`）；dim_member 沒有“未知會員”列 | 四批 `member_missing` 都是 0（`[P-MEM.quarantine]`、各批對帳的 `unknown_member_rows`）；`[Q-ORD.member_ref]` 0 | 已完成（9f9d415；b975543 原本是落 -1、照寫） |
| E-21 | 收尾 | 繞過管線直接寫表 | Delta CHECK 只加在關鍵欄位，fact_order 共 6 條：`order_id IS NOT NULL`、`amount > 0`、coupon 是 NULL 或不小於 0、`order_status` 與 `currency` 在允許值內、`member_sk IS NOT NULL` | 不適用；約束本身見 `[P-FACT.check_constraints]` | 已完成（9f9d415） |

E-1～E-3 是前置 A 的 3 項，E-4～E-20 是 17 項，E-21 不算進兩者。

**實作狀態**：21 項都已實作，決策都記在 process-log。“實作”欄的括號是實作這一項的 commit（b975543 以前的分批實作不逐一列）。

---

## 附錄 F：管線步驟細節

**本附錄依管線步驟說明每個問題在哪一步被處理、擋下多少列。** 〔細節〕裡的編號對照見附錄 C。

### F.1 管線流程

**每一批訂單都依序走過 3 個前置步驟和 8 個處理步驟；哪一步擋下的列，就帶著那一步的原因進隔離表。** 所以各步不重複計算，加總等於輸入。

```
每一批（base、day1、day2、day3）
 前置 A  批次紀錄檢查                      已完成就跳過；訂單檔被改過 → 停；參考資料被改過 → 警告；強制重跑留紀錄
 前置 B  參考資料檢查（產品清單、匯率表）    有壞列或重複 → 整批停，什麼都不寫
 前置 C  寫維度：產品、會員                 V8、V9、V10、J9、L9、L11；會員快照違規列、快照晚到
 ── 訂單 ──────────────────────────────────────────────
 ①  讀取與合約                            V1、V5、V3（轉 NULL）；檔案、格式、值域
 ②  同批撞號                              J3
 ③  完全重複去重                           V7、N1；中間夾著其他狀態的相同列
 ④  與既有 fact 撞號                       J2
 ⑤  狀態機                                L4；同批多個新狀態、往回走、同一秒衝突等
 ⑥  換匯（× 匯率表）                       V4、L12；找不到匯率（N2）
 ⑦  品質規則                              目前沒有規則
 ⑧  對維度（× 產品、會員）、算淨額           V6、V2、L3、J10、N3；淨額變負數、會員對不到版本
 ─────────────────────────────────────────────────────
 收尾  對帳 → 寫隔離表 → 寫人工確認清單 → 寫進 fact（只在更新時間較新時覆寫）
```

**每一步擋下了什麼**（筆數依序是 base／day1／day2／day3）

| 步驟 | 擋下幾列 | 影響最大的問題 |
|---|---|---|
| 前置 A 批次紀錄 | 0（四批都是第一次執行） | — |
| 前置 B 參考資料 | 0（沒有整批停） | — |
| 前置 C 會員維度 | 0；修正同一天兩列的 30 位、假值轉 NULL | 5 人的真實生日後來被 1900-01-01 蓋掉，保留真實值 |
| ① 讀取與合約 | 50／0／0／0 | **金額是負數**，合計約 -1,239 萬 TWD；下單時間有三種寫法，非標準寫法 6,002 列 |
| ② 同批撞號 | 0／6／2／4 | 增量同一個檔裡，兩張不同的單用了同一個編號 |
| ③ 去重 | 40／15／15／15 | 同一列送了兩次，只差更新時間 |
| ④ 與既有 fact 撞號 | 0／594／598／596 | **增量列和 base 撞號**，和官方說明不同 |
| ⑤ 狀態機 | 略過 0／0／25／0 | 較晚送到的舊事件，fact 維持 cancelled |
| ⑥ 換匯 | 0 | 幣別寫成 NTD 200 列；匯率表沒有 TWD |
| ⑦ 品質規則 | 0（目前沒有規則） | — |
| ⑧ 對維度、算淨額 | 0；對到“未知產品” 120、人工確認清單 40 | **金額大了 1,000 倍**，40 列佔 base 寫進 fact 的 `amount_twd`（折扣前、所有狀態）**28.09%**，人工確認前不計入下游的金額指標 |
| [只記錄、管線不處理的](#f15-只記錄管線不處理的) | 0 | **completed 但出發日還沒到**，寫進 fact 28,578 列 |

只記錄、管線不處理的問題不屬於任何一步，集中在[“只記錄、管線不處理的”一節](#f15-只記錄管線不處理的)。

〔細節：入口是 `run.py`，依序跑 base → day1 → day2 → day3；每批走 `fact_order.py` 的 `run_batch` → `load_order_batch` → `transform_order_batch`。被擋下的原因記在隔離表的 `reject_category`。前置 A 是 `run_once`；② 到 ⑧ 的編號對照：J3、V7／N1、J2、L4、V4／L12／N2、V6／V2／L3／J10／N3；只記錄的是 L1、L2、L5、L6、L7、L8、L10〕

### F.2 怎麼讀這份報告

**本附錄依管線步驟寫，給技術審閱者。** 每一步一節：先講本資料實際發生的問題，再列為正式環境預先做的防護；問題編號、查詢標籤、程式名稱都收在每段最後的〔細節〕。名詞見[附錄 G](#附錄-g名詞表)，正文問題和編號的對照見[附錄 C](#附錄-c問題對照表)。

- **筆數**：依序是 base／day1／day2／day3。會員的三份快照都在 base 那一批處理（base 處理到 06-30 為止），所以會員的筆數改列 04-30／05-31／06-30 三份快照。
- **日期與時間**：`+08:00` 照標記；結尾 `Z` 是 UTC；`YYYY/MM/DD HH:MM:SS`（沒有時區標記）當台北時間。文中的“日期”都是台北日期。
- **使用者理由**：引用使用者在 `ai-collab/process-log.md` 的原話，〔細節〕裡的“出處”是 process-log 的事件標題。ADR-01～05 放在 `decisions/`。以下幾項的理由不是使用者自己提出的決定，各節照實標明：
  - 幣別 NTD、匯率表沒有 TWD：使用者接受 AI 提出的建議。
  - 會員快照沒變就不開新版本：理由是 AI 撰寫、使用者採用的一段說法。
  - 台幣金額的四捨五入（HALF_UP 到小數 2 位）是實作慣例，沒有使用者定案。
- **實作狀態**：各節列的處理都已寫進管線（HEAD 9f9d415），各項的 commit 見[附錄 E](#附錄-e防護性設計清單)。
- **防護性設計**：本資料沒有發生、為正式環境預先做的處理，一律標〔防護性設計：本資料 0 筆〕。使用者要求這樣區分：「防護性的設計幫我標記」（「不合法轉移之後的事件一起隔離；防護性設計要標記」）。“0 筆”有兩種證據：
  - **管線實跑**：三天實跑的對帳（part_a/README.md“每種狀況的處理”，2026-10-19），四批各分類都是 0。
  - **DuckDB 預檢**：不經過管線，直接查 CSV。
  - 附錄 E 的 17 項是和資料內容有關的防護，各步驟的防護表合計就是這 17 項（狀態與幣別的值域檢查是同一條規則，算一項；淨額變負數分兩段處理，算一項）。前置 A 的 3 項和重跑、參考資料版本有關，不是資料內容的問題，不算進 17 項，但同樣標示。收尾的 Delta CHECK 是既有合約規則的第二道防線，不是新的問題類別，也不算進。
  - 管線三天實跑的數字和 DuckDB 預檢一致，沒有任何一項防護需要移到“實際發生的問題”。

---

### F.3 前置 A：批次紀錄檢查

**本資料四批都是第一次執行，這一步沒有擋下任何東西。** 它的作用是防止重跑出錯：每一批在讀任何資料之前，先查這批是不是已經跑過、檔案有沒有被改過。

**〔防護性設計：本資料 0 筆〕**（重跑、參考資料版本，不算進 17 項）

| 情況 | 處理 | 管線三天實跑 | 使用者理由 |
|---|---|---|---|
| 已經跑完的批次，訂單檔後來被改過 | 停下來報錯，不默默跳過；要重跑必須明確指定強制重跑 | 四批都是第一次執行 | 「要避免訂單狀態可以被隨意修改 如果要修改需要使用force來紀錄」 |
| 已經跑完的批次，參考資料（會員、產品、匯率）和當時不同 | 只發警告，照常跳過；參考資料是整份快照，之後的批次本來就會讀到新版本 | 四批都是第一次執行 | 同上 |
| 強制重跑 | 開始前先追加一筆“開始”紀錄、完成後再追加一筆“完成”（哪一批、什麼時候、新舊檔案指紋），紀錄只增不改；中途當掉也看得出這批被強制重跑過 | 沒有強制重跑 | 同上 |

批次紀錄也強制 base → day1 → day2 → day3 依序處理，會員快照晚到的防護靠它，見前置 C。

〔細節：`batch_log.py` 的 `run_once`；檔案指紋是 sha256，訂單檔不同丟 `SourceChangedError`，強制重跑用 `--force`，順序不對丟 `BatchOrderError`。參考資料 checksum 不同時發 `logging` 的 WARNING；強制重跑紀錄是 `record_forced` 寫的 `batch_log_force`（表屬性 `delta.appendOnly=true`，每次 force 兩列：`started`、`completed`）。出處：「checksum 涵蓋參考資料：訂單檔不同就擋，參考資料不同只警告」。訂單檔的 checksum 在 commit b975543 實作，參考資料 checksum 與強制重跑紀錄在 commit 92b8d85 實作〕

---

### F.4 前置 B：參考資料檢查（產品清單、匯率表）

**產品清單或匯率表只要有一列壞掉，整批就停下來，什麼都不寫。** 本資料沒有發生。產品名稱重複只記錄，見[“只記錄、管線不處理的”一節](#f15-只記錄管線不處理的)。

**〔防護性設計：本資料 0 筆〕**

| 表.欄位 | 問題 | 處理 | 管線三天實跑 | DuckDB 預檢 | 使用者理由 |
|---|---|---|---|---|---|
| `products` | 有壞列，或同一個產品編號出現兩次 | 整批停 | 四批都沒有停 | 0（`[Q-L7.dup_name]`） | 「晚一點進來比錯的資料好」 |
| `fx_rates` | 有壞列，或同一天同一幣別有兩個匯率 | 整批停，和產品清單共用檢查 | 四批都沒有停 | 0（`[Q-FX.table]`） | 「匯率影響的是訂單金額 這個程度比較大 需要事先停止」 |

〔細節：`load_order_batch` 在寫任何表之前檢查，停下時丟 `ReferenceDataError`。出處：「產品清單有壞列就整批停」；「匯率表壞一列就整批停」。匯率表這條原本是實作者自行延伸，使用者在 2026-10-19 補定〕

---

### F.5 前置 C：會員維度（dim_member，SCD Type 2）

**會員資料有三種假值和一種矛盾：同一天兩列等級不同、城市寫 N/A、生日寫 1900-01-01，還有真實生日被假值蓋掉。** 這些都在寫會員表時修正，訂單照常對得到會員。

會員資料是 04-30、05-31、06-30 三份快照（8,030／459／502 列），都在 base 那一批處理。04-30 是全部會員，後兩份只有部分會員，放的是會員當時的完整樣子，不一定有變動。處理完是 8,000 位會員、8,772 個版本（管線實跑，part_a/README.md“dim_member”、`[P-MEM.versions]`）；dim_member 沒有“未知會員”列。

**實際發生的問題**（筆數：04-30／05-31／06-30）

| 表.欄位 | 問題 | 筆數 | 處理 | 使用者理由 |
|---|---|---|---|---|
| `members.member_level` | 同一位會員同一天有兩列，等級不同 | 30 位／0／0 | 取較高等級（一般 < 銀卡 < 金卡 < 白金） | 「假設會員系統也是同樣的行為才選擇的行為」 |
| `members.city` | 城市寫 `N/A` | 66／3／2 列（70 人） | 轉成空值（NULL），不蓋掉已知的真實城市；從空值變成真實城市時開新版本 | 「新會員訂單要對得到版本，更正不算歷史，假值不能蓋真值」；「不是使用null就好」 |
| `members.birth_date` | 生日寫 1900-01-01 | 76／2／3 列（80 人） | 轉成空值，不蓋掉真實生日；生日只留最新值、不開版本（Type 1） | 同上一列 |
| `members.birth_date` | 真實生日後來被 1900-01-01 蓋掉 | 5 人 | 保留真實生日 | 同上一列 |
| `members.member_level`、`city` | 等級、城市在快照之間改變 | 等級 434 人、城市 376 人 | 開新版本，從看到變動的那份快照日開始 | 「只記錄確定知道的事」 |
| `members` 全欄 | 後一份快照和前一次完全相同 | 0／95／91 列 | 不開新版本 | AI 撰寫、使用者採用的說法，見下 |

- **同一天兩列**：例如會員 M000096 在 04-30 同時有銀卡和金卡兩列，城市都是台北市。沒有時間戳，資料推不出哪一列對，所以照使用者的假設取較高等級。補充證據各半：取較低等級時，跨快照的等級變動是 405 次都升一級；取較高時是 404 次升一級、1 次降級；30 位裡只有 2 位出現在後來的快照，一位等於較低值、一位等於較高值。處理後 30／30 位的第一個版本都是較高等級。〔細節：V8｜`[Q-V8.example]`、`[Q-V8.same_day]`、`[Q-MEM.level_moves]`、`[Q-V8.later_snapshot]`、`[P-MEM.v8_same_day]`｜出處「dim_member 同日矛盾的 30 位取較高等級」〕
- **城市 N/A**：70 人中 61 位從來沒有真實城市，9 位在其他快照有。處理後 `N/A` 剩 0 列；城市為空值的版本有 65 列、65 位會員，就是從來沒有真實城市的 61 位，加上第一次出現時是 N/A、之後才出現真實城市的 4 位（空值那段是他們的第一個版本）。〔細節：V9｜`[Q-V9V10.placeholders]`、`[Q-V9.members]`、`[Q-V9.na_before_real]`、`[P-MEM.v9_v10_placeholders]`〕
- **生日 1900-01-01**：1900 以外最早的生日是 1960-01-03，中間沒有任何值，所以 1900-01-01 是“未知”的代號。處理後 1900-01-01 剩 0 列，生日為空值的 61 人就是從來沒有真實生日的人。〔細節：V10｜`[Q-V10.birth_min]`、`[P-MEM.v9_v10_placeholders]`〕
- **真實生日被蓋掉**：例如會員 M001647 在 04-30 的生日是 1961-07-15，06-30 變成 1900-01-01。生日變過的 19 人中，14 人是 1900 → 真實，5 人是真實 → 1900。處理後 5 人都是原本的真實日期。〔細節：J9｜`[Q-J9.example]`、`[Q-J9.birth_direction]`、`[P-MEM.j9_all]`｜V9、V10、J9 出處「dim_member SCD2 規則」、「dim_member：城市從 NULL 變成真實值時開新版本」〕
- **等級、城市改變**：城市 376 人含 N/A，排除後是 367 人；姓名、註冊日沒有任何人變過。〔細節：L9｜`[Q-L9.changes]`｜出處「dim_member：新版本從觀察到變動的快照日開始」〕
- **快照沒變**：同一天兩列的會員先照上面的規則取較高等級，再和前一次比較。版本數 8,772，沒有因為這 186 列而增加。理由全文：「SCD2 追蹤的是狀態的變化，不是觀察的次數。用 Type 2 欄位比對變化，沒變就不開版本。這樣維度的粒度正確，重送快照時也保持冪等，這跟 dbt snapshot 的 check 策略相同。」〔細節：L11｜`[Q-L11.identical]`、`[P-MEM.versions]`｜出處「A-3 剩下四題：N2、L3、V6、L11」〕

**〔防護性設計：本資料 0 筆〕**

| 表.欄位 | 問題 | 處理 | 管線三天實跑 | DuckDB 預檢 | 使用者理由 |
|---|---|---|---|---|---|
| `members.extract_date` | 會員快照晚到（05-31 比 06-30 晚送） | 前置 A 的批次紀錄強制依序處理 | 四批依序完成 | 同時出現在 05-31 與 06-30 的會員 0 位（`[Q-MEM.both_0531_0630]`） | 「批次可以節省過去已經成功的事件執行時間 可以避免時間導致的停止問題 如果每次都在一個小時的時間點失敗 這樣重新執行也可從第二個小時開始」 |
| `members.member_level`、`register_date` | 快照裡有壞列（等級不在清單、註冊日晚於快照日） | 另開會員隔離表（原始字串＋原因）；壞列不參與建版本，不蓋掉上一個好版本 | 0 列（`[P-MEM.quarantine]`；base 對帳 `member_rejected_rows` 0） | 0（`[Q-MEM.register_after_extract]`） | 「根據DE的慣例」 |

會員第一次出現就是壞列時，他的訂單會對不到會員版本，依 ⑧ 的規則進訂單隔離表。

〔細節：`write_dim_member` 只處理快照日不晚於這批處理日（`as_of`）的快照，base 的 `as_of` 是 06-30。會員隔離表是 `quarantine_member`，由 `write_member_quarantine` 以快照日 replaceWhere 寫入，同一份快照重讀幾次都只留一份（commit 9f9d415）。出處：「中途停止：冪等步驟＋批次紀錄」；「會員快照的違規列：另開會員隔離表」〕

---

### F.6 ① 讀取與合約

**讀進來的第一步就擋下了 50 張負數金額的訂單；另外有兩個欄位要先翻譯才能用：折扣寫 -1.0、下單時間有三種寫法。**

四個訂單檔的欄位相同：`order_id, member_id, product_id, channel, order_status, quantity, currency, amount, coupon_discount, order_created_at, departure_date, updated_at`。base 100,040 列、100,000 個訂單編號；day1 4,615 列、day2 4,700 列、day3 4,615 列（`[Q-000.rows]`）。這一步把字串轉成規定的型別，不符合規定的列進隔離表。

**實際發生的問題**

| 表.欄位 | 問題 | 筆數 | 處理 | 使用者理由 |
|---|---|---|---|---|
| `orders.amount` | 金額是負數 | 50／0／0／0 | 規定“金額大於 0”，不符合就進隔離表 | 「負數在合約層就該擋下」 |
| `orders.coupon_discount` | 折扣寫 -1.0 | 300／0／0／0（寫進 fact 299） | 轉成空值，訂單照常寫入；隔離表保留原始字串 | 「-1 代表未知，轉 NULL 不要猜」 |
| `orders.order_created_at` | 下單時間有三種寫法 | 3,001＋3,001／0／0／0 | 結尾 `Z` 的當 UTC，沒有時區標記的當台北時間 | 「台北 因為重複列跟時間先後都對得上」 |

- **負數金額**：例子與影響見正文“最重要的 5 個問題”第 4 個。四種狀態都有；50 列是 TWD 29、USD 17、JPY 4，合計約 -1,239 萬 TWD。其中 1 列同時是折扣 -1.0，18 列同時是“completed 但出發日還沒到”。〔細節：V1｜`[Q-V1.negative]`、`[Q-V1.examples]`、`[Q-POST.v1_overlap]`｜比值的定義見 ⑧｜出處「V1 負數金額：合約層擋下進隔離表」〕
- **折扣 -1.0**：其他列的折扣都是 0～950 之間 50 的倍數，base 有 4,942 列是 0，所以 -1 不是“沒有折扣”，而是“不知道”的代號。1 列同時是負數金額（已隔離，所以 fact 是 299），1 列同時是金額大 1,000 倍。轉成空值的列，折扣後金額也是空值。〔細節：V3｜`[Q-V3.coupon]`、`[Q-AMT.overlap]`、`[Q-POST.totals]`｜出處「V3 coupon -1.0：轉 NULL，訂單照常寫入」〕
- **三種時間寫法**：例如訂單 ORD00000245 的下單時間是 `2026-05-14T23:06:27Z`，換成台北時間已經是 05-15；如果直接取字串前 10 碼，會記成 05-14。這樣錯一天的有 1,003 列。增量檔全部是 `+08:00`。沒有時區標記的當台北時間，證據有三：同一張單送兩次、寫法不同的 8 組，換算後相差 0 小時；如果當 UTC，會有 384 列的更新時間早於下單時間，當台北時間是 0 列；`Z` 寫法字面日期早於 05-01 的 13 列，照 UTC 換算後是 0 列。〔細節：V5｜`[Q-V5.example]`、`[Q-V5.formats]`、`[Q-V5.z_date_shift]`、`[Q-V5.tz_evidence_dup]`、`[Q-V5.tz_evidence_order]`、`[Q-V5.z_before_0501]`｜寫法定義在 `timeparse.py` 的 `SOURCE_TIMESTAMP_FORMATS` 一處，檢查和解析共用｜出處「無時區標記的下單時間當台北時間」〕

**〔防護性設計：本資料 0 筆〕**

| 表.欄位 | 問題 | 處理 | 管線三天實跑 | DuckDB 預檢 | 使用者理由 |
|---|---|---|---|---|---|
| 7 個檔 | 檔案不存在、表頭不對、空檔 | 整批停（參考資料在前置 B 讀取時就檢查） | 四批都讀取成功 | 7 個檔都讀得到（`[Q-000.rows]`） | 「pipline中應該要有data cleaning」 |
| `orders` 全欄 | 單列格式不對：型別、小數位、必填欄位空白、時間寫法、欄位數 | 進隔離表 | 負數金額以外 0 列 | 0（`[Q-001.contract]`） | 同上 |
| `orders.order_status`、`currency` | 狀態不是 4 種允許值；幣別不是 TWD、NTD、USD、JPY（大小寫、空白不同也算） | 進隔離表 | 0 | 0（`[Q-DOM.status_currency]`） | 「值域是 schema 的一部分」 |

-1 以外的負數折扣也在這一步擋下，它是“淨額變負數”防護的一部分，列在 ⑧。

〔細節：`cast_to_contract`，隔離類別 `contract`。出處：「型別違規：檔案層級整批停、列層級進隔離表」；值域「T6 第二階段前的四個細節；讀取驗證層經業界評估」〕

---

### F.7 ② 同批撞號

**增量檔同一個檔裡，有 6 個訂單編號各出現兩列，兩列是完全不同的兩張單。** 例如 day1 的 ORD00036457：一列是會員 M002150、200,659.0、completed；另一列是會員 M000272、18,042.46、cancelled，下單時間差了將近一個月。

| 表.欄位 | 問題 | 筆數 | 處理 | 使用者理由 |
|---|---|---|---|---|
| `orders.order_id` | 增量同一個檔裡，兩張不同的單用了同一個編號 | 0／3 組 6 列／1 組 2 列／2 組 4 列 | 兩列都進隔離表，都不寫入，因為分不出哪一張才是原本的單 | 同 ④ |

這 6 個編號也都在 base 出現過，和 ④ 是同一種現象，只是兩列剛好落在同一個檔。管線隔離 6／2／4 列，和偵測一致。

〔細節：J3｜判斷“不同的單”看會員、下單時間、金額任一不同（`IMMUTABLE_COLUMNS`），隔離類別 `collision`｜`[Q-J3.example]`、`[Q-INC.samefile]` 的 `collision(J3)`〕

---

### F.8 ③ 完全重複去重

**同一列被送了兩次，只差更新時間幾秒，保留最新的一列。** 例如 ORD00000984 在 base 出現兩次，內容完全一樣，更新時間差 14 秒（07:02:52 和 07:03:06）。

| 表.欄位 | 問題 | 筆數 | 處理 | 使用者理由 |
|---|---|---|---|---|
| `orders` 全欄 | base 裡同一列送了兩次 | 40 組（多 40 列）／0／0／0 | 留最新一列，另一列進隔離表 | 「網路重送造成的重複，留最新一列就好」；成因：「v7根據我的經驗是網路波動導致的重複寫入 可以重寫入端或是schena的unique index改善」 |
| `orders` 全欄 | 增量同一個檔裡，連狀態都相同的重送 | 0／15 組／15 組／15 組 | 同上一列 | 同上一列 |

- **base 的重複**：40 組各兩列，只差更新時間 2～29 秒。其中 8 組的下單時間寫法不同、換算後是同一時刻，例如 ORD00012637 一列寫 `2026-06-14T19:17:51+08:00`、另一列寫 `2026-06-14T11:17:51Z`。如果直接比字串，會被誤判成撞號。〔細節：V7｜`[Q-V7.groups]`、`[Q-V7.examples]`｜出處「完全相同的重複列：取 updated_at 最新一列」；成因「V7 base 重複列：使用者判斷是網路波動造成的重複寫入」〕
- **增量的重送**：連狀態也相同，是重送，不是狀態更新；增量同一個檔裡沒有任何一組是“同一張單、狀態改變”。〔細節：N1｜`[Q-INC.samefile]` 的 `resend_identical_except_updated_at`〕

**〔防護性設計：本資料 0 筆〕**

| 表.欄位 | 問題 | 處理 | 管線三天實跑 | DuckDB 預檢 | 使用者理由 |
|---|---|---|---|---|---|
| `orders` 全欄 | 相同的列中間夾著其他狀態（如 cancelled → paid → cancelled） | 不算重複，交給 ⑤ 狀態機 | 0 | — | 「中間如果有出現其他狀態 不能當作延遲」 |

〔細節：同一編號依更新時間排序，**時間上相鄰**、除了更新時間以外全部相同才算重複；下單時間比的是換算後的時刻。隔離類別 `duplicate`。出處：「重複只算時間上相鄰的相同列」。本資料兩種重複都是相鄰的〕

---

### F.9 ④ 與既有 fact 撞號

**增量檔每天約 600 列和 base 用了同一個編號，但內容是另一張單，一律進隔離表，不覆寫既有訂單。** 例子與影響見正文“最重要的 5 個問題”第 2 個。

| 表.欄位 | 問題 | 筆數 | 處理 | 使用者理由 |
|---|---|---|---|---|
| `orders.order_id` | 增量列和之前已寫入的訂單同編號、內容不同 | 偵測 —／603／602／603 列；隔離 0／594／598／596 列 | 判為撞號，進隔離表，不寫進 fact | 「把撞號當 noise 處理」；ADR-03：「訂單的基本資訊不能被修改」 |

- **為什麼判成撞號**：官方 README 說增量檔“含舊訂單的狀態更新事件”，但這些列和 base 同編號那列相比，會員、金額、下單時間相同的列數都是 0；幣別、通路、狀態相同的比例，等於兩疊不相干的訂單隨機配對的期望值。
- **偵測和隔離筆數為什麼不同**：② 和 ③ 先處理了一部分。day1 的 603 = 594 + 6（同檔撞號）+ 3（重送組裡編號在 base 的）。
- **限制**：資料排除不了“上游允許整張單被改寫”這種業務規則；隔離表保留原始列，規則改變時可以重新處理。增量檔裡更新時間比 base 舊的 12 列也都在撞號列裡，不會把 base 的狀態蓋回去。

〔細節：J2｜和“這批開始之前”的 fact 比（ADR-05），會員、下單時間、金額任一不同就是撞號，隔離類別 `collision_existing`｜`[Q-J2.overlap]`、`[Q-J2.example]`、`[Q-J2.impact]`｜對帳拆解見附錄 A｜出處「增量檔與 base 撞號的列當 noise 處理」；「ADR-01～04 定稿」〕

---

### F.10 ⑤ 狀態機

**訂單狀態只能往前走（created → paid → completed，或中途 cancelled）；本資料唯一的問題是 25 個較晚送到的舊事件，管線略過它們。** 例子與影響見正文“最重要的 5 個問題”第 5 個。

| 表.欄位 | 問題 | 筆數 | 處理 | 使用者理由 |
|---|---|---|---|---|
| `orders.order_status`、`updated_at` | 較晚送到的舊事件：day1 送來 cancelled，day2 又送來更新時間較早的 paid | 0／0／25／0 | 以更新時間判斷新舊；舊狀態本來就走得到現在的狀態，所以略過，留在隔離表，fact 維持 cancelled | 「照 updated_at，符合狀態機單向假設」；「晚到事件不該當成狀態轉移」；「我傾向統一紀錄狀況外的事件」 |

兩列的會員、金額、下單時間都相同，是同一張單，只是送到的順序和發生的順序相反。day2 這 25 列的更新時間在 07-01～07-04（6／7／8／4 列）。三天後 25 張都是 cancelled。

〔細節：L4｜範例的原始更新時間是 day1 `2026-07-04T18:08:26+08:00`、day2 `2026-07-03T12:08:26+08:00`｜隔離類別 `late_event`｜`[Q-L4.cross_day]`、`[Q-L4.example]`、`[Q-L4.day2_upd_dates]`、`[Q-L4.impact]`、`[Q-POST.l4_final]`｜出處「增量新舊以 updated_at 判斷」；「狀態機檢查採 C：晚到事件分開處理」；「晚到事件也留在隔離表，類別標為略過」〕

**〔防護性設計：本資料 0 筆〕**

| 表.欄位 | 問題 | 處理 | 管線三天實跑 | DuckDB 預檢 | 使用者理由 |
|---|---|---|---|---|---|
| `orders.order_status` | 同一批裡有好幾個比 fact 新的合法狀態 | 寫最後一個，較早的進隔離表；和 ③ 的重送分開記 | 0 | — | 「重送和狀態更新成因不同要分開記」 |
| `orders.order_status` | 狀態往回走（如 cancelled → paid） | 進隔離表，fact 不更新 | 0 | 0（`[Q-SM.chain]` 的 `not_reachable`） | 「晚到事件不該當成狀態轉移」 |
| `orders.order_status` | 晚到，而且舊狀態走不到現在的狀態 | 進隔離表 | 0 | 同上 | 同上 |
| `orders.order_status` | 不合法之後，同一批的其他事件 | 一起進隔離表，fact 停在最後一個合法狀態 | 0 | 同上 | 「鏈斷掉後面的資料就不可信」 |
| `orders.order_status`、`updated_at` | 同一張單、同一秒、不同狀態 | 這些列全部進隔離表，之前的合法事件照寫 | 0 | 0（`[Q-SM.same_second]`） | 「資料不足時不要讓管線自己猜」；「斷點之前的資料沒有問題」 |
| `orders.order_status` | 跳過中間狀態（如 created → completed） | 合法，照寫，只在對帳計數 | 0 | 0（`[Q-SM.chain]` 的 `skipped_intermediate`） | 「在沒辦法確定是事件驅動還是快照的情況下 逐段也用可達性」；「在不影響下游分析的情況下 先設計成紀錄log 不要過度設計」 |

“同批多個新狀態”的 0 筆來自管線實跑（part_a/README.md“每種狀況的處理”）；本資料增量同一個檔裡沒有“同一張單、狀態改變”的組，所以不會出現。預檢的“同一張單”定義為編號、會員、金額、下單時刻都相同，所以撞號不會被算成狀態變化：相鄰列共 110 組，就是 base 重複 40 組、增量重送 45 組加晚到事件 25 組；狀態真的有變的 25 組就是晚到事件（照更新時間是 paid → cancelled，合法）。

〔細節：判斷用**可達性**：從現在的狀態走 0 步以上到得了就算合法；合法的一步只有 created→paid、created→cancelled、paid→cancelled、paid→completed。和“這批開始之前”的 fact 現況比。隔離類別依表格由上而下：`superseded`、`illegal_transition`、`late_event_conflict`、`after_illegal`、`ambiguous_order`。出處：同批多個新狀態、同一秒的第二句、跳過中間狀態的第二句「T6 第二階段前的四個細節；讀取驗證層經業界評估」；往回走、晚到走不到「狀態機檢查採 C：晚到事件分開處理」；不合法之後「不合法轉移之後的事件一起隔離；防護性設計要標記」；同一秒「同一秒內出現不同狀態：兩列都進隔離表」；跳過中間狀態「狀態檢查一律用可達性，不用一步轉移表」〕

---

### F.11 ⑥ 換匯（× fx_rates）

**所有金額都換成台幣，換匯時要處理兩件事：有 200 列幣別寫成 NTD（問題），匯率表裡沒有 TWD（本幣不列是常見設計，不是錯誤，不算進實際問題，見附錄 C）。** 兩個都不擋，照常換算。

| 表.欄位 | 問題 | 筆數 | 處理 | 使用者理由 |
|---|---|---|---|---|
| `orders.currency` | 幣別寫成 `NTD` | 200／0／0／0 | 當 TWD，匯率 1，幣別欄保留原值 `NTD` | 使用者接受 AI 的建議：「原幣別保留可追溯，換算 TWD 讓營收能直接加總」 |
| `fx_rates.currency` | 匯率表沒有 TWD（不是錯誤，不算進實際問題） | 66,890／3,069／3,150／3,141 列 TWD＋NTD 訂單 | TWD 匯率固定 1；匯率表對不到也不丟掉訂單 | 同上一列（同一次決定） |

- **NTD**：`NTD` 不是國際標準的幣別代碼，增量檔沒有，也不在匯率表；用 1:1 換算時，金額和定價的比例和 TWD 幾乎相同（中位數 1.0353 對 1.0506），所以是 TWD 的別名。fact 有 200 列 NTD，台幣金額合計 54,561,733.00。〔細節：V4｜`[Q-V4.ntd]`、`[Q-POST.currency]`｜出處「金額：原幣別與換算 TWD 都存」〕
- **匯率表沒有 TWD**：本幣不列在匯率表是常見設計，不是錯誤；但如果換匯時只保留對得到匯率的訂單，TWD 訂單會整批消失，這正是 Part B 那支管線的錯誤之一。base 的 66,890 是 TWD 66,690＋NTD 200。base 寫進 fact 的幣別：TWD 66,632、USD 22,101、JPY 11,017、NTD 200，共 99,950 列。〔細節：L12｜“只保留對得到的”是 inner join，管線用 left join｜`[Q-FX.coverage]`、`[Q-POST.currency]`〕

**〔防護性設計：本資料 0 筆〕**

| 表.欄位 | 問題 | 處理 | 管線三天實跑 | DuckDB 預檢 | 使用者理由 |
|---|---|---|---|---|---|
| `orders.order_created_at` × `fx_rates` | 下單那天找不到匯率 | 進隔離表，不拿前一天的匯率代替 | 0 | 0（`[Q-FX.coverage]`） | 「資料不足時不要讓管線自己猜」 |

〔細節：台幣金額 `amount_twd = round(amount × 台北下單日的匯率, 2)`（HALF_UP，實作慣例，不是使用者定案）。找不到匯率是 N2，隔離類別 `fx_missing`，出處「A-3 剩下四題：N2、L3、V6、L11」〕

---

### F.12 ⑦ 品質規則

**這一步目前沒有規則，四批都沒有擋下任何列。** A-3 定案的規則都放在其他步驟：負數金額在 ①，金額大 1,000 倍不擋、在 ⑧ 列清單。

〔細節：掛載點 `ORDER_QUALITY_RULES`，隔離類別 `quality`〕

---

### F.13 ⑧ 對維度、算淨額、列人工確認清單

**這一步把訂單對到產品和會員，算出折扣後金額，並把金額大 1,000 倍的 40 張列進人工確認清單。** 本資料有 5 個問題在這裡處理，都不擋訂單。

**怎麼抓出金額異常：看金額和定價的比例。** 比例＝台幣金額 ÷（產品定價 × 人數），正常的訂單全部落在 0.8378～1.2839。落在 0.8～1.3 之外的只有三種：負數的 50 列、約 1,000 倍的 40 列、沒有定價可比的 120 列，都只在 base。這是從資料反推的規則，不是官方規則：如果真實系統允許整單折價或加購，規則就太嚴；沒有定價的 120 列也無法檢查。〔細節：`[Q-AMT.ratio_range]`、`[Q-AMT.ratio_buckets]`〕

| 表.欄位 | 問題 | 筆數 | 處理 | 使用者理由 |
|---|---|---|---|---|
| `orders.amount` | 金額大了約 1,000 倍 | 40／0／0／0 | 照原樣寫入，列進人工確認清單；**人工確認前不計入下游的金額指標** | 「沒辦法系統性的處理 金額問題我判斷成case by case」；「因為沒辦法在pipline前有效判斷出問題」 |
| `orders.product_id` × `products` | 訂單的產品不在產品清單 | 120／0／0／0 | 照常寫入，產品對到“未知產品”，保留原始產品編號 | 見下 |
| `orders.order_created_at` | 6 月的訂單晚到 7 月才送來 | 0／0／60／0 | 當新單寫入，下單日照原始資料。**6 月的訂單金額在 07-02 之後仍會變動** | 「訂單屬於下單那天，晚到只是傳遞延遲」 |
| `orders.amount` | 金額是折扣前還是折扣後，資料看不出來 | 全部訂單 | 定義為折扣前，fact 另加折扣後金額 | 「可以定義好業務邏輯處理」；「那折扣前」；「我的設計傾向紀錄所有金額」 |
| `orders.coupon_discount` | 折扣固定台幣，和訂單幣別不一致 | 全部訂單 | 當台幣，不跟著訂單幣別換匯 | 官方說明：“`coupon_discount`（TWD）”；使用者另以資料確認：「coupon 當 TWD，三種幣別面額一樣」 |

- **大 1,000 倍**：例子與影響見正文“最重要的 5 個問題”第 1 個。比例除以 1,000 後回到 0.85～1.24；TWD、JPY 的 31 列是 1,000 的倍數，USD 的 9 列是 10 的倍數（小數 2 位 × 1,000）。40 列台幣金額合計 10,102,491,689.70，**佔 base 寫進 fact 的 35,969,473,520.09 的 28.09%**，三天後佔全表 25.85%。使用者定案 B1：這 40 列留在 fact，人工確認前下游的金額指標排除清單上的訂單，理由「因為已經有前面指標進入隔離我認為就應該人工審查後在進入下流」。三天後 fact 的 `amount_twd` 總和（所有狀態、折扣前）39,086,896,780.27，排除清單後 28,984,405,090.57，差額 10,102,491,689.70。營收的定義（含不含取消單、折扣前或後）由下游語意層決定，不在這裡定。這 40 列都在 05-01～06-30，人工確認後 5～6 月的金額總和會改變。〔細節：V2｜清單是 `amount_review`，比例大於 100 的列進清單；排除查詢是 `fact_order.py` 的 `AMOUNT_EXCLUDING_REVIEW_SQL`（清單先 `DISTINCT order_id` 再 left join 排除）｜`[Q-V2.x1000_detail]`、`[Q-V2.examples]`、`[Q-POST.v2_share]`、`[P-ALL.amount_excluding_review]`｜出處「A-3：哪些品質問題要處理、哪些只記錄」、「V2 疑似多乘 1,000：照原樣寫入，另列清單」、「V2 的 40 張：留在 fact，正式營收在人工確認前排除」｜業務假設 [3.7](../business-assumptions.md#37-人工確認前待確認訂單不計入下游的金額指標)〕
- **未知產品**：120 個不同的產品編號，都是 `P9xxxx`（P91064～P99990），四種狀態都有。理由全文：「我認為訂單是主要的事實表 也是分析資料的中心思考分方式 而商品可能經過時間迭代 有消失的可能 因此以進客能保留訂單的方式處理」。改善建議“為每個未知編號建一筆佔位產品”由使用者提出：「可以是未知商品就幫忙創一筆」，目前決定「先維持 這是之後的改善方案」。〔細節：V6｜`product_sk` 落 -1；佔位產品是 inferred member 模式｜`[Q-V6.unknown_product]`｜出處「A-3 剩下四題：N2、L3、V6、L11」〕
- **6 月訂單晚到**：例如 ORD00112001，下單時間 06-15，day2 才送來，狀態 paid、更新時間 07-02。60 張都不在 base、也不在更早的增量檔，下單日在 06-10～06-23，更新時間都是 07-02、狀態全是 paid，合計台幣 11,320,587.24；其中 5 張是出發日已過才付款。訂單編號比 day3 的新單還大，不能用編號推時間。日期表每批依訂單擴充，6 月的日期已經存在。〔細節：L3｜`[Q-L3.example]`、`[Q-L3.late_new_orders]`、`[Q-L3.detail]`、`[Q-L3.paid_after_departure]`｜出處同上〕
- **折扣前還是折扣後**：折扣最多 950 台幣，訂單金額中位數約 20 萬台幣，用比例分辨不出來。折扣是空值時，折扣後金額也是空值。〔細節：J10｜折扣後金額是 `net_amount_twd`｜`[Q-N3.coupon_by_currency]`｜出處「A-3：哪些品質問題要處理、哪些只記錄」、「J10：amount 定義為折扣前，fact 加 net_amount_twd」〕
- **折扣的幣別**：四種幣別的折扣面額都是 0～950、每 50 一級；如果當成訂單幣別，USD 訂單有 785 列（5～6 月總檔）的折扣大於訂單金額。官方 `candidate_package/README.md` 的欄位說明本來就寫 coupon 是台幣，以上是資料佐證。〔細節：N3｜`[Q-N3.coupon_by_currency]`｜推論細節見 `notes/part_a/schema-inference/coupon-currency.md`（該筆記原本誤寫官方沒有說明幣別，已加更正）｜出處「coupon_discount 當台幣」、「共用業務假設文件；AI 誤稱官方沒寫 coupon 幣別」〕

**〔防護性設計：本資料 0 筆〕**

| 表.欄位 | 問題 | 處理 | 管線三天實跑 | DuckDB 預檢 | 使用者理由 |
|---|---|---|---|---|---|
| `orders.coupon_discount` × `amount` | 折扣後金額變成負數 | -1 以外的負數折扣在 ① 擋下；折扣大於台幣金額照寫，列進人工確認清單（`review_reasons` 記原因） | 四批人工確認清單只有多 1,000 倍的 40 張（各批對帳的 `amount_review_rows`） | 0（`[Q-POST.net_guard]`） | 「負數coupon沒有合理解釋，太大的可能是全額折抵」 |
| `orders.member_id` × `members` | 訂單對不到會員版本（會員不在快照，或下單日早於最早的版本） | 進訂單隔離表（類別 `member_missing`），不對到“未知會員”；dim_member 沒有“未知會員”列 | 四批 `member_missing` 都是 0（`[P-MEM.quarantine]`；各批對帳的 `unknown_member_rows`） | 0（`[Q-ORD.member_ref]`） | 「在訂單重要度之後是會員資料 如果有未知會員資料在做客戶分析是一件困難的事 所以要有錯誤提醒修正data pipline」 |

- 淨額：-1 以外的負數折扣、折扣大於台幣金額、折扣後金額小於 0 都是 0 列；fact 最小的台幣金額是 2,520.07，最大的折扣是 950。
- 會員和產品處理不同的原因：產品可能隨時間下架消失，所以未知產品保留訂單；會員是客戶分析的主體，對不到就代表管線或上游有錯，要用隔離表提醒修正。

〔細節：對 `product_sk`、`member_sk`、`date_sk`，`net_amount_twd = amount_twd − coupon_discount`；“未知產品”的代理鍵是 -1。會員沒有“未知”列：對不到版本時 `member_sk` 是 NULL，`_split_member_missing` 把這些列以 `member_missing` 分到訂單隔離表，原因（會員不在 dim_member，或下單日早於第一個版本）由 `member_missing_reason` 寫明；對帳的 `unknown_member_rows` 就是這個類別的筆數（commit 9f9d415；b975543 原本是落 -1、照寫）。出處：「net 變負數：負的 coupon 在合約擋下，太大的 coupon 只列清單」；「會員對不到版本：進隔離表，不落 -1」〕

---

### F.14 收尾：對帳與寫入

**寫入之前先對帳：輸入必須等於寫進 fact＋隔離＋略過，不平就整批不寫。** 四批對帳都平衡，見正文“三天處理結果”。寫進 fact 時，只有更新時間比 fact 裡較新的列才會覆寫，這是狀態機之外的第二道防線。

- **Delta CHECK 約束**：在表本身加上檢查，只加在關鍵欄位，連繞過管線直接寫表都擋得住。fact_order 建表時加上 6 條（`FACT_CHECK_CONSTRAINTS`：`order_id_not_null`、`amount_positive`、`coupon_discount_non_negative`、`order_status_valid`、`currency_valid`、`member_sk_not_null`），實跑後讀回的約束見 `[P-FACT.check_constraints]`（commit 9f9d415）。使用者理由：「Delta CHECK 是最後一道防線，擋得住繞過管線的寫入」（「Delta CHECK 約束：只加在關鍵欄位，當最後一道防線」）。它重複既有的合約規則，不是新的問題類別，所以不算進防護項目。

〔細節：順序是寫 dim_date（① 的合格列）→ 記下這批開始前的 fact 版本（`batch_start`，ADR-05）→ 對帳（不平丟 `ReconciliationError`）→ 寫隔離表 → 寫 `amount_review` → MERGE fact（條件 `s.updated_at > t.updated_at`）〕

---

### F.15 只記錄、管線不處理的

**這 7 個問題照原樣寫入，不影響管線的正確性，但用報表時要知道。** 使用者的定案：「有些問題可以只記錄下來 不需要特別處理」（「A-3：哪些品質問題要處理、哪些只記錄」）。

| 表.欄位 | 問題 | 筆數 | 為什麼不處理、要注意什麼 |
|---|---|---|---|
| `orders.order_status` | completed 但出發日還沒到 | base 寫進 fact **28,578** 列，金額 10,324,629,272.48 TWD；增量 0／321／313／289 列全是撞號、不進 fact | 維持“出團完成”的假設，記成品質問題；報表用 completed 時，要知道它在本資料不代表已出團 |
| `orders.updated_at` | 增量的更新時間晚於檔名日期 | —／3,290／3,257／3,263 | 管線不用檔名日期判斷新舊，只看更新時間，不影響正確性 |
| `orders.updated_at` | base 有 7 月的更新時間 | 2,265／—／—／— | base 實際是 07-03 之後才匯出的；這些列都沒有被增量改動（增量裡同編號的列全是撞號） |
| `orders.amount` | 日圓金額帶小數 | 80／0／0／0 | 量級正確，存得下 |
| `orders.product_id` × `products.is_active` | 訂單的產品已下架 | 寫進 fact 4,267／163／154／163 | 產品清單只有“目前是否上架”，沒有下架日期，判斷不了下單時是否已下架 |
| `products.product_name` | 同一個產品名稱對應多個產品編號 | 44 個名稱 | 產品表以編號為鍵，不受影響；用名稱分組要注意 |
| `members.birth_date`、`register_date` | 註冊時未滿 18 歲 | 455 列（398 人） | 可能是家庭成員或未成年帳號 |

- **completed 但出發日還沒到**：例子與影響見正文“最重要的 5 個問題”第 3 個。使用者假設「completed先假設成出團完成」（「假設 completed 是出團完成，與 base 資料衝突」），定案理由「先把狀態規則定下來 之後比較好處理」（「completed 維持出團完成，28,612 列當資料品質問題」）。不是時區造成：出發日比最後更新日晚 4～119 天。base 28,612 列 → 每個編號一列 28,596 → 扣掉負數金額擋下的 18 列 → fact 28,578。〔細節：L10｜`[Q-L10.completed_before_departure]`、`[Q-L10.after_dedupe]`、`[Q-POST.v1_overlap]`、`[Q-POST.l10]`；增量見 `[Q-L10.incremental_split]`〕
- **反向證據**：四種狀態裡出發日已過的比例都約 21.5%，而且每一種狀態的最後更新都早於出發日。照“出團完成”的假設，9,234 張 paid、3,053 張 created 早該出團。狀態和出發日在資料裡沒有關聯。〔細節：`[Q-L10.reverse]`，base 每個編號取最新一列〕

  | 狀態 | 張數 | 出發日早於 07-01 | 比例 | 出發日不晚於最後更新日 |
  |---|---|---|---|---|
  | paid | 42,881 | **9,234** | 21.5% | 0 |
  | created | 14,282 | **3,053** | 21.4% | 0 |
  | cancelled | 14,241 | 3,056 | 21.5% | 0 |
  | completed | 28,596 | 6,149 | 21.5% | 0 |

- **更新時間晚於檔名日期**：約七成增量列晚於批次日，最多晚 4 天；day2 有 6 列早於批次日，是“較晚送到的舊事件”的一部分。〔細節：L1｜`[Q-L1.upd_after_batch]`〕
- **base 有 7 月的更新時間**：07-01 1,308、07-02 759、07-03 198 列。〔細節：L2｜`[Q-L2.base_upd_after_period]`〕
- **日圓帶小數**：base 的 JPY 共 11,022 列。〔細節：L5｜金額型別是 `DECIMAL(18,2)`｜`[Q-L5.jpy_fraction]`〕
- **產品已下架**：原始列數 4,270／184／182／195；增量裡編號在 base 的是撞號列。〔細節：L6｜`[Q-L6.inactive]`、`[Q-POST.l6]`〕
- **同名不同編號**：300 個產品編號只有 253 個名稱，例如 `P00098`、`P00262` 都叫“伊斯坦堡1日票券”。〔細節：L7｜`[Q-L7.example]`、`[Q-L7.dup_name]`〕
- **未滿 18 歲**：排除 1900-01-01 後，最小 11.5 歲。〔細節：L8｜`[Q-L8.under18]`〕

---

### F.16 已檢查但沒有問題的項目

**下面這些檢查都做了，結果是 0。**

| 表.欄位 | 檢查 | 查詢 | 結果 |
|---|---|---|---|
| `orders` 全欄位 | 單列格式：必填欄位空白、人數不是整數、金額或折扣超過 2 位小數、時間解析不了、出發日不是日期 | `[Q-001.contract]` | 四個訂單檔全部 0 |
| `orders.order_status`、`channel`、`currency`、`quantity` | 狀態、通路、幣別的允許值；人數範圍 | `[Q-002.domains]` | 狀態 4 種、通路 4 種、人數 1～4；幣別只有 base 多一個 NTD |
| `orders.departure_date`、`updated_at` × `order_created_at` | 出發日早於下單日；更新時間早於下單時間 | `[Q-NEW.departure_before_order]` | 全部 0；下單到出發最少 7 天 |
| 跨表 `orders.member_id` × `members` | 訂單的會員不在會員快照；下單日早於註冊日 | `[Q-ORD.member_ref]` | 全部 0 |
| `members.register_date`、`member_level` | 會員註冊日晚於快照日；等級允許值 | `[Q-MEM.register_after_extract]` | 0；等級只有一般、銀卡、金卡、白金 |
| `products.product_id`、`base_price_twd` | 產品編號重複、定價不是正數 | `[Q-L7.dup_name]` | 0 |
| `fx_rates` | 匯率缺日、重複、不是正數 | `[Q-FX.table]` | 04-28～07-03 每天都有 USD、JPY，0 |

7 個檔開頭都有 UTF-8 BOM（看不見的編碼標記），讀取時已經略過。

---

### F.17 資料限制

**以下是資料本身看不到、管線也補不了的事。**

1. **會員只有每月快照，看不到實際的變動日**（前置 C）。新版本從快照日開始，所以從實際變動日到快照日之間的訂單會對到舊等級。使用者指出根本解法在上游：「這個問題不要應該要從member中改善嗎 應該紀錄update time嗎」（「dim_member：新版本從觀察到變動的快照日開始」）。
2. **同一天兩列沒有先後**：只能靠規則挑，無法驗證。
3. **會員快照必須依序處理**：如果 05-31 比 06-30 晚送到，兩份都有的會員，05-31 那一版會被跳過。管線靠批次紀錄強制依序處理；本資料沒有同時出現在兩份的會員。
4. **檔名日期不等於資料時間**，base 的實際匯出時點不明。新舊只能信更新時間；如果上游的更新時間本身有錯，管線無從發現。
5. **訂單編號不能推時間**，也不保證唯一。撞號和“上游允許整張單被改寫”在資料上無法區分（ADR-03）。
6. **金額異常的偵測依賴反推的比例規則**（⑧）：沒有定價的 120 列無法檢查；折扣前後只能靠業務定義。
7. **假值的語意不明**：折扣 -1、生日 1900-01-01 代表“沒有”還是“不知道”，要問上游。目前一律當“不知道”。
8. **分辨不出上游送的是事件還是快照**：base 一定是快照；增量檔是否每變一次就送一筆，資料無法確定。如果是快照，created → completed 可能只是中間的 paid 沒拍到，所以狀態檢查只看“走不走得到”（⑤）。
9. **更新時間只精確到秒**：同一張單同一秒出現不同狀態時，排不出先後（⑤）。

〔細節：1 對應 L9，2 對應 V8，4 對應 L1、L2，5 對應 L3、J2、J3，6 對應 V6、J10〕

### F.18 上游改善建議

**大部分問題的根本解法在上游系統，下表列出每個問題該請上游改什麼。**

| 表.欄位 | 問題 | 建議 | 說明 |
|---|---|---|---|
| `members` | 會員只有快照（V8、L9、資料限制 1） | 會員表加更新時間；或建等級異動紀錄表，每次異動一列；或直接取資料庫的變更事件（CDC，change data capture） | 拿到實際變動日，訂單就能對到正確的等級版本 |
| `orders` 跨欄位 | 同一列送兩次（V7、N1） | 寫入端加冪等鍵（每次請求一個 id），重送時不再寫入 | 使用者判斷成因是網路波動；這是根本解法 |
| `orders` 跨欄位 | 同一列送兩次（V7） | 訂單表加唯一索引（unique index） | 建在哪個欄位，取決於上游是“一張單一列”（訂單編號唯一）還是狀態事件表；事件表上 `(order_id, updated_at)` 唯一擋不住，因為每列的更新時間都不同 |
| `orders.order_id` | 撞號（J2、J3） | 確認訂單編號的產生方式（會不會重用、是否跨系統） | ADR-03 |
| `members.member_level` | 同一天兩列（V8） | 會員快照的 `(member_id, extract_date)` 加唯一約束 | |
| `orders.order_created_at` | 三種時間寫法（V5） | 時間欄位統一成帶時區的 ISO 8601 | |
| `orders.currency`、`fx_rates.currency` | NTD、匯率表沒有 TWD（V4、L12） | 幣別用 ISO 4217 代碼並加 CHECK；匯率表的文件寫明本幣不列 | |
| `orders.amount` | 負數、大 1,000 倍（V1、V2） | `CHECK (amount > 0)` 擋負數；1,000 倍要請上游查來源（像是單位換算） | 資料庫規則只擋得住負數，擋不住 1,000 倍（ADR-02） |
| `orders.coupon_discount`、`members.city`、`members.birth_date` | 假值（V3、V9、V10） | 未知的值用 NULL，不用 -1、`N/A`、1900-01-01 | |
| `orders.product_id` × `products` | 未知產品（V6） | 訂單的產品編號加外鍵參照產品表；資料倉端可為未知編號建佔位產品（inferred member） | |
| `orders.updated_at` | 檔名日期不等於資料時間（L1、L2） | 增量檔附上匯出時點（watermark），或檔名改用匯出時間 | |
| `orders.amount`、`coupon_discount` | 折扣前後、折扣幣別（J10、N3） | 欄位定義文件寫明 amount 是否已扣折扣；加 `coupon_currency` 欄位或寫明折扣的幣別 | |
| `orders.order_status`、`updated_at` | 事件或快照、更新時間只到秒（資料限制 8、9） | 每張單帶版本號（每次狀態變更 +1），用 outbox 或 CDC 依交易順序送出；上游強制狀態機 | 管線就能分辨“中間狀態沒拍到”和“真的跳過”，同一秒的多個狀態也排得出先後 |

---

## 附錄 G：名詞表

**正文用業務語言，附錄用技術用語，兩者對照如下。**

| 正文用語 | 技術用語 | 說明 |
|---|---|---|
| 5～6 月總檔 | base（`orders_base.csv`） | 05-01～06-30 的全量匯出 |
| 7/1、7/2、7/3 更新檔 | day1～day3（`orders_incremental_day1～3.csv`） | 每日增量檔 |
| 會員資料的三次匯出 | 會員快照（`members.csv` 的 `extract_date`） | 04-30 全部會員，後兩份只有部分會員 |
| 計入報表 | 寫進 fact（`fact_order`），動作是 MERGE（有就更新、沒有就新增） | 最後給分析用的訂單表，一張訂單一列 |
| 擋下、存到待查清單 | 進隔離表（quarantine） | 保留原始內容和被擋的原因（`reject_category`），不寫進 fact，之後可以重新處理 |
| 人工確認清單 | `amount_review` | 照常寫進 fact、但要人看過的訂單 |
| 不採用 | 略過（`late_event`） | 較晚送到的舊事件；列仍寫進隔離表，對帳時單獨計數 |
| 資料一進來就檢查，不合格的不收 | 合約層（`cast_to_contract`） | 每個欄位該是什麼型別、什麼值的規定；讀取時不符合就擋下 |
| 保留會員等級的歷史變化 | SCD Type 2（`dim_member`） | 會員資料每變一次就多存一個版本，訂單對到下單當時的那個版本 |
| 不另存一份歷史 | 不開新版本 | 快照和前一次相同時 |
| 未知產品 | `product_sk` = -1 | 代理鍵 -1 代表“未知” |
| 訂單對不到會員時先擋下 | 訂單隔離表的 `member_missing` | 會員沒有“未知”列，對不到版本的訂單整列擋下 |
| 會員資料的待查清單 | 會員隔離表 `quarantine_member` | 會員快照的違規列，不蓋掉上一個好版本 |
| 撞號 | `collision`（同批）、`collision_existing`（與既有 fact） | 兩張不同的訂單（會員、金額、下單時間不同）用了同一個訂單編號 |
| 折扣後金額 | `net_amount_twd = amount_twd − coupon_discount` | 折扣是 NULL 時也是 NULL |
| 資料表本身最後一道檢查 | Delta CHECK 約束 | 存在表本身，繞過管線的寫入也擋得住 |
| 為正式環境預先準備的處理 | 防護性設計 | 本資料沒有發生，為正式環境預先寫好的處理 |
| 狀態只會往前走 | 狀態機單向假設、可達性 | 合法的一步只有 created→paid、created→cancelled、paid→cancelled、paid→completed |

**編號與標籤**：V＝違反約束（資料一定錯），L＝可能合法（不一定是錯），J＝需要判斷語意的問題，N＝撰寫本報告時新增的項目，只當索引用。`[Q-xxx]` 是用 DuckDB 直接查 CSV 的偵測查詢，不經過管線，避免“用管線驗證管線”；`Q-POST` 開頭的也用 DuckDB，照管線的規則重算寫進 fact 之後的結果；`[P-xxx]` 是呼叫管線（PySpark＋Delta）後查表的驗證。所有查詢都在 `profiling/data_quality_queries.py`，重跑方式見[附錄 A](#附錄-a查詢腳本與重跑)；`Q-` 的輸出是 2026-10-19 實際執行的結果，原樣收在附錄 B。同批多個新狀態時較早的被取代，類別叫 `superseded`。
