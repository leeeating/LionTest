# Part C 第一版的製作過程

- Session：`491f7702`（Part C session；開工指示由 Part A 主 session `85463d71` 寫在 `.claude/work/part-c-kickoff.md`）
- 日期：2026-10-19
- 情境：使用者不在場（去運動），指示 AI「先做出一版並利用其他 agent 來 review，做時要紀錄中間過程、要紀錄 ADR」。所以本檔所有方向選擇都是 **〔AI 暫定，待使用者確認〕**，不是使用者的決定
- 用途：使用者回來後逐題確認或推翻；確認後由主 session 整理成 `ai-collab/process-log.md` 的事件（本 session 不寫 process-log，避免和主 session 同時寫檔衝突）

## 目錄
- [1. 時間軸](#1-時間軸)
  - [1.1 開工：讀規劃與規則](#11-開工讀規劃與規則)
  - [1.2 並行開兩條線：Fabric 查證＋Part A 證據](#12-並行開兩條線fabric-查證part-a-證據)
  - [1.3 Part A 證據回來](#13-part-a-證據回來)
  - [1.4 Fabric 查證回來（C2）](#14-fabric-查證回來c2)
  - [1.5 暫定 Q1～Q10、起草 ADR-06～08](#15-暫定-q1q10起草-adr-0608)
  - [1.6 寫設計文件第一版與架構圖 v2](#16-寫設計文件第一版與架構圖-v2)
  - [1.7 派三個 fresh-context 審查（opus）](#17-派三個-fresh-context-審查opus)
  - [1.8 第 1 輪審查結果與修正](#18-第-1-輪審查結果與修正)
  - [1.9 第 2 輪驗收與再修正](#19-第-2-輪驗收與再修正)
  - [1.10 第 3 輪驗收，收尾](#110-第-3-輪驗收收尾)
  - [1.11 加目錄（2026-10-24，使用者新規則）](#111-加目錄2026-10-24使用者新規則)
  - [1.12 章節標題編號（2026-10-24，使用者新規則）](#112-章節標題編號2026-10-24使用者新規則)
  - [1.13 主 session 通知：×1000 口徑已定案、共用業務假設檔（2026-10-24）](#113-主-session-通知1000-口徑已定案共用業務假設檔2026-10-24)
  - [1.14 三條路線的白話說明（2026-10-24）](#114-三條路線的白話說明2026-10-24)
  - [1.15 README 第 3 節的三條路線由使用者自己寫（2026-10-24）](#115-readme-第-3-節的三條路線由使用者自己寫2026-10-24)
  - [1.16 Q1 定案：outbox＋Kafka（2026-10-26）](#116-q1-定案outboxkafka2026-10-26)
  - [1.17 Q10 選 CDC，待成本分析（2026-10-26）](#117-q10-選-cdc待成本分析2026-10-26)
  - [1.18 Q2 定案：補 bronze，訂單事件也落地（2026-10-26）](#118-q2-定案補-bronze訂單事件也落地2026-10-26)
  - [1.19 Q10 改定案：不開 CDC，每日 bronze 比對（2026-10-26）](#119-q10-改定案不開-cdc每日-bronze-比對2026-10-26)
  - [1.20 Q3 選 B：gold 放 Warehouse（2026-10-26）](#120-q3-選-bgold-放-warehouse2026-10-26)
  - [1.21 Q4 討論中：即時方案的計費（2026-10-26）](#121-q4-討論中即時方案的計費2026-10-26)
  - [1.22 Q5 採用 AI 建議：標初估＋取最新＋每日對帳（2026-10-26）](#122-q5-採用-ai-建議標初估取最新每日對帳2026-10-26)
  - [1.23 Q6 討論中（2026-10-26）](#123-q6-討論中2026-10-26)
  - [1.24 Q7 定案：自建問數服務（2026-10-26）](#124-q7-定案自建問數服務2026-10-26)
  - [1.25 Q8 採用 AI 建議：表層級權限、服務帳號（2026-10-26）](#125-q8-採用-ai-建議表層級權限服務帳號2026-10-26)
  - [1.26 Q9 採用 AI 建議：陷阱題 100%、一般題 90%（2026-10-26）](#126-q9-採用-ai-建議陷阱題-100一般題-902026-10-26)
  - [1.27 補處理主 session 留下的待辦（2026-10-26）](#127-補處理主-session-留下的待辦2026-10-26)
  - [1.28 ADR-06～08 改為已定案（2026-10-26）](#128-adr-0608-改為已定案2026-10-26)
  - [1.29 收尾（2026-10-26）](#129-收尾2026-10-26)

## 1. 時間軸

### 1.1 開工：讀規劃與規則
- 讀了 `.claude/work/part-c-kickoff.md`、`.claude/work/part-c.md`（opus 規劃的骨架、Q1～Q10、任務卡 C1～C6）、題目 Part C、`adr` skill、`decisions/README.md`、`learning/0-storage/microsoft-fabric.md`
- 發現：`microsoft-fabric.md` 的「官方文件」節寫著「未證實：依 AI 的既有知識整理」，所以 Part C 的 Fabric 說法目前**沒有任何一條有官方出處**。照規劃，先做 C2 查證，沒有官方連結的說法不能當論據
- 確認本 session id 是 `491f7702`：`ls -t` 最新的 jsonl 有兩個候選（主 session 也在寫），用 grep 本 session 第一句使用者訊息確認是哪一個

### 1.2 並行開兩條線：Fabric 查證＋Part A 證據
- 派研究 subagent（general-purpose、opus）只查 learn.microsoft.com，寫 `fabric-facts.md`（C2）。10 個題目：Eventstream、Eventhouse、Real-Time Dashboard、SQL endpoint vs Warehouse、Direct Lake、semantic model、data agent、OneLake 權限、Mirroring、Spark Structured Streaming
- 派 Explore subagent（sonnet）從 Part A 繳交物撈出可引用的證據（規模、撞號、晚到、指標定義、隔離表、合約），每條附出處。為什麼不自己讀：要翻 10 個以上的檔，依全域規則交給 subagent，主對話只收結論
- 等待時先畫 `architecture-v1.md`：**查證前**的直覺版，依規劃的建議選項，並列出 5 個要靠查證回答的疑點。留下這版是為了之後能說清楚「查證改了什麼」

### 1.3 Part A 證據回來
- Explore 回報整理成 `part-a-evidence.md`（E1～E21），設計文件以編號引用
- 值得注意的兩點：
  - `part_a/model.md` 還是 base 後的舊數字，引用要用 README 與 data-quality-report 的最新數字。這是給主 session 的提醒，本 session 不改 part_a
  - Part A **沒有 bronze 層**（ADR-04 後果），而 Q2 正好在問正式環境要不要補；**分鐘級即時**在 Part A 完全沒有證據，即時鏈路是全新設計，論據只能靠 Fabric 文件與撞號、晚到的數字

### 1.4 Fabric 查證回來（C2）
- 研究 agent 寫出 `fabric-facts.md`：85 條（F1-1～F10-5），`grep -c "https://learn.microsoft.com"` 為 87，另列 8 條「未查到或文件矛盾」
- **主 session 抽查**：F7-8 寫「不支援非英文」，但原文欄只引了 25 列那句，沒有這句的原文。用 WebFetch 重開 concept-data-agent 頁，找到 "The Fabric data agent doesn't currently support non-English languages."，補進 F7-8。這是研究 agent 的小疏漏（說法對、證據沒附齊），發現者：AI 自查
- 查證**改變了 v1 的三個地方**：
  1. **問數的語言**：data agent 官方不支援非英文（F7-8）。雄獅的使用者會用中文問，Q7「直接用 data agent」不再是理所當然的建議
  2. **語意層放 semantic model 的效果打折**：data agent 查 semantic model 時會忽略 agent 層 instructions，也不支援 example queries（F6-6、F6-8），能用的 Prep data for AI 還是 Preview（F6-3）。v1 把 semantic model 當問數的主要入口，要改
  3. **即時鏈路要自己去重**：Eventstream 是 at-least-once、沒有去重運算子（F1-11、未查到第 6 條），Eventhouse 的 `arg_max` materialized view 是官方列的用例（F2-8）。v1 的疑點 5 有了具體做法
- 也確認了 v1 疑點：Eventstream 可直接接 Kafka 或用 custom endpoint 的 Kafka 協定（F1-1、F1-9）；Eventhouse 透過 OneLake availability 給批次那邊用，但延遲最少 5 分鐘、預設最多 3 小時（F2-2），所以**分鐘級儀表板必須直查 Eventhouse**，不能繞去 Direct Lake；data agent 以提問者自己的身分查詢（F7-4）
- 回填 `learning/0-storage/microsoft-fabric.md` 的「官方文件」節（開工指示允許的唯一 learning 改動）

### 1.5 暫定 Q1～Q10、起草 ADR-06～08
- 寫 `tentative-decisions.md`：十題各列選項、取捨、暫定答案，全部標〔AI 暫定，待使用者確認〕
- 和規劃（`.claude/work/part-c.md`）不同的地方，都是查證造成的：
  - **Q6 理由換了**：規劃建議 C 的前提是「欄位定義放 gold、量值放 semantic model」，並要求先查 data agent 能否讀 semantic model。查證結果是「讀得到，但讀 semantic model 時 instructions 和 example queries 都用不了」（F6-6、F6-8），所以 C 的重點改成「**口徑**放 gold view」，semantic model 只做加總與切片
  - **Q7 從 A 改成 C（先 POC）**：規劃建議直接用 data agent；查證發現官方不支援非英文（F7-8），改成「用黃金問題集對 data agent 做中文 POC，過門檻才用」。並建議使用者考慮為 Q7 補 ADR（規劃原本說不寫）
  - **Q4 仍暫定 A**，但照規劃的提醒在 ADR-07 寫明「使用者不熟 KQL 時選 B 是正當取捨」
- ADR 編號：掃描 `decisions/` 最大號是 ADR-05，所以從 06 開始。三份狀態都是「草稿」，「決定」「理由」兩節只寫標〔待使用者確認〕的 AI 草稿
- 更新 `decisions/README.md` 索引，加 ADR-06～08。**發現但沒改**：索引中 ADR-05 寫「草稿」，但 ADR-05 檔案本身已是「已定案」。ADR-01～05 不在本 session 可改範圍，留給使用者或主 session

### 1.6 寫設計文件第一版與架構圖 v2
- 寫 `part_c/README.md`，照規劃的 0～8 節骨架。每個 `##` 都有歸屬標註：第 6 節標〔使用者判斷〕（素材是使用者在 Part A 討論時提出的，引用 `.claude/work/part-c.md` 的原始素材），其餘都標〔AI 產出〕，因為使用者還沒改過任何一節。方向判斷都另外標〔AI 暫定，待使用者確認〕
- 第 4 節配套：四類各三項，每項寫「建什麼＋擋哪種錯＋連回 Part A 哪條證據」（規劃風險 3：每類最多三項）
- 第 8 節「分工總述」照規劃要由使用者寫 3～5 句，第一版只放素材與〔待使用者撰寫〕
- 架構圖存成 `architecture-v2.md`，並列出和 v1 的 6 個差別，每個差別都對到一條查證或 Part A 證據
- **驗證圖能 render**：用 `npx -p @mermaid-js/mermaid-cli mmdc` 把 v1、v2 轉成 SVG，兩張都成功，SVG 中沒有 "Syntax error"

### 1.7 派三個 fresh-context 審查（opus）
- 照開工指示派兩組審查，都只給目的與素材，不給製作過程：
  - **review-two-axis**：Spec 軸（題目 Part C 四個要求有沒有漏，並抽查 F、E 引用與原文是否一致）與 Standards 軸（CLAUDE.md 規則、歸屬標註名實相符、ADR 沒有替使用者定案、F 引用沒有誇大）各一個 agent
  - **面試官冷讀**：只准讀 `part_c/README.md` 一個檔，回報讀不懂的地方、最想追問的 3 題、看起來超出作者能解釋範圍的說法、篇幅

### 1.8 第 1 輪審查結果與修正
- 三份審查：Spec 軸「有條件過」、Standards 軸「有條件過」、面試官冷讀約 4～5 分（滿分 10）。逐條與處置寫在 `review-round1.md`
- **AI 的錯（發現者：驗收 agent）**：
  1. **設計錯誤（Spec S1）**：第一版讓 semantic model 用 Direct Lake 讀 gold 的 SQL view。查證清單 F5-5 明寫「semantic model 引用沒有實體化的 SQL view 時，Direct Lake 會退回 DirectQuery」，AI 寫設計時沒回頭對照，只挑了支持論點的條目。改成 Spark 寫出實體表 `gold_order_metrics`
  2. **權限矛盾（Spec S2）**：同一句要「view 上的 RLS」又要「SQL endpoint 用 User identity 模式」，這兩者在官方文件是互斥的兩種模式（F8-8）。改成報表與問數共用 OneLake security 一套規則
  3. **替使用者定了口徑（Standards T3）**：寫「淨營收要排除疑似 ×1000 的單」，但 Part A 是照原樣寫入、沒有定過要不要排除。改成表上帶旗標，預設排不排除標〔待使用者確認〕
  4. **證據轉述扭曲（Standards T5）**：E11 寫「completed 但出發日未到」，原報告明說基準是「標成已完成的當下」並警告不要誤讀成到現在都沒出團。這是 Explore agent 轉述的錯，主 session 沒有逐條核對所以沒抓到
- **面試官最大的扣分 AI 修不了**：全文判斷都是 AI 暫定。要使用者確認並用自己的話改寫後才會改變
- 其他修正：加「名詞」節（面試官看不懂撞號、×1000、outbox 等）；關鍵論據寫出原意不只給編號；使用者素材複製到 `user-material.md`（原本引用不進 git 的施工檔）；3.2 改成從需求推論並加入 Mirroring 選項；第 6 節 AI 延伸的句子另標〔AI 補充〕；fabric-facts「對設計的影響」加註哪些建議沒採用
- **沒採用的建議**：Spec S3 建議刪掉第 6 節（題外），但規劃骨架把它列為加分項，而且是唯一的使用者素材，留給使用者決定
- 中間產物：`readme-draft-v1.md`（審查前快照）、`architecture-v3.md`（與 v2 的差別）。v3 用 mmdc 轉 SVG 成功

### 1.9 第 2 輪驗收與再修正
- 派 fresh-context agent（opus）驗證第 1 輪的修正，結論「有條件過」，另抓到 5 條（`review-round1.md`「第 2 輪」R1～R5）
- **AI 修正時又犯的錯（發現者：驗收 agent）**：
  - R1：S1 改了 README 與 ADR-08，漏改 ADR-06 後果裡的「view」。改設計時只改了被點名的檔，沒有 grep 全部引用處
  - R3：修 T3「替使用者定口徑」時，把「營收預設折扣前」寫成「Part A 已定案的 J10」，但 J10 只定了欄位，沒定指標預設。**修一個替使用者定案的錯，又引入一個新的**
  - R4：權限統一後說得太滿，忽略了查證清單裡的 F5-8
- 全部依建議修正。這幾條是小範圍文字修改，送第 3 輪驗收確認

### 1.10 第 3 輪驗收，收尾
- 第 3 輪（fresh-context opus）：R1、R2、R3、R5 修好；R4 漏了兩處（職責表、第 8 節）仍寫成定論，已改。最後這兩行沒有再派驗收，在 `review-round1.md` 註明
- 同一類錯出現三次：AI 修正一處說法時，沒有 grep 同一說法的其他出現處（S1→R1、R4 的兩處殘留）。之後改設計時，先 grep 關鍵詞再改
- 更新 `.claude/work/part-c.md`：最上面列出使用者回來要確認的 13 件事（依相依性），「目前進度」寫到這裡
- 沒做的事：沒寫 `ai-collab/process-log.md`（開工指示：等使用者確認後由主 session 整理）；沒 commit；沒動 `part_a/`、ADR-01～05；沒啟動 Spark

### 1.11 加目錄（2026-10-24，使用者新規則）
- 使用者規則：說明文件開頭都要有目錄（TOC），列到 `###`，錨點照 GitHub slug 規則，並用腳本檢查
- 範圍：`part_c/README.md` 與 `notes/part_c/` 下超過 80 行的檔：`fabric-facts.md`（172 行）、`process.md`（81 行）、`readme-draft-v1.md`（172 行）。其餘 7 個檔都在 80 行以下，不加
- 做法：寫 `.claude/tools/md_toc.py`（`add` 在第一個 `##` 前插入目錄；`check` 檢查每個連結都對得到標題、每個 `##`／`###` 都列進目錄、順序一致）。`readme-draft-v1.md` 是審查前快照，目錄放在快照分隔線 `---` 之前，不插進快照內容
- 驗證：
  - `md_toc.py check` 4 個檔全過（56 個連結）
  - 產生和檢查用的是同一套 slug 實作，等於自己驗自己，所以另外用 GitHub 實際使用的 `github-slugger` 套件重算錨點核對，56 個連結全部對得到
  - 和加目錄前的備份 `diff`：4 個檔原有行的刪除或改動都是 0，只有新增
- 本筆寫完後，`process.md` 多了這個 `###` 標題，目錄重新產生一次並再跑檢查
- 獨立驗收（fresh-context opus，不用作者的腳本，自己依 GitHub 規則重寫 slug 計算）：**過**。4 個檔的連結全對、順序與縮排一致；80 行以下的 7 個檔沒有被加；`readme-draft-v1.md` 的目錄在快照分隔線之前；和備份 diff 只有新增

### 1.12 章節標題編號（2026-10-24，使用者新規則）
- 使用者規則：說明文件的章節標題要編號（`## 1. …`、`### 1.1 …`），目錄本身不編號，附錄用字母（`A`、`A.1`）。套用到 `part_c/README.md` 與上一步加了目錄的三份 notes
- **README 的編號整體位移**：原本的「名詞」節沒有編號、其餘從 0 起算，規則要從 1 起算。照原順序重新編號，不搬動章節（「名詞」放在最前面，是第 1 輪審查 I3 為了讓讀者先看懂術語而加的）。對照：

  | 原編號 | 新編號 |
  |---|---|
  | 名詞 | 1 |
  | 0 前提與假設 | 2 |
  | 1 架構圖 | 3 |
  | 2 元件與分層職責 | 4 |
  | 3 關鍵取捨（3.1～3.3） | 5（5.1～5.3） |
  | 4 Text-to-SQL 配套（4.1～4.4） | 6（6.1～6.4） |
  | 5 從 Part A 延續 | 7 |
  | 6 給上游的改善建議 | 8 |
  | 7 未驗證事項與限制 | 9 |
  | 8 AI 與使用者分工總述 | 10 |

- **跟著改的引用**：README 內文 12 處節號引用（「第 N 節」與「（3.2）」「見 4.3」這類）；`architecture-v3.md` 標題（指向 README 目前版本）；`.claude/work/part-c.md` 待確認清單的第 11、13 項。**刻意不改的**：`review-round1.md` 與本檔前面各步的節號，那是寫下當時的版本編號，查證時用上表對照
- **其他三份**：`fabric-facts.md` 改成 `## 1. F1 Eventstream`…`## 10. F10 …`、`## 11. 未查到或文件矛盾`、`## 12. 對設計的影響`，保留 F 編號，因為全部文件都用 F1-11 這類編號引用；`process.md` 改成 `## 1. 時間軸`、`### 1.1`～`### 1.12`；`readme-draft-v1.md` 是審查前快照，快照內編號與節號引用一起加 1，並在快照說明加一行註記這次改動
- 做法：一次性替換腳本，逐處印出改前改後並人工核對，只改標題行與節號引用。`.claude/tools/md_toc.py` 擴充兩項檢查：`check` 現在也檢查內文的錨點連結（不只目錄）；加 `--numbering` 檢查編號（`##` 從 1 連續、附錄從 A 連續且排在數字之後、`###` 的前綴等於所屬 `##` 的編號）
- 驗證：
  - 4 份文件的目錄重新產生，`md_toc.py check --numbering` 全過
  - `github-slugger` 重算錨點全部對得到
  - 4 份文件沒有指向其他檔案的 Markdown 連結（路徑都寫在行內程式碼裡），內文錨點連結 0 個
  - 和改編號前的備份 diff：README 被改的非標題、非目錄行正好是那 12 處節號引用，快照是 8 處，另外兩份只改了標題與目錄
- 獨立驗收（fresh-context opus，自己寫檢查、不用 `md_toc.py`）：**過**。4 份的編號、目錄錨點都對；README 12 處與快照 8 處節號引用逐一確認指到正確內容，沒有誤改金額、F／E 編號、日期；`architecture-v3.md` 與工作檔第 11、13 項的節號正確

### 1.13 主 session 通知：×1000 口徑已定案、共用業務假設檔（2026-10-24）
- 主 session 轉達兩件事（不是本 session 使用者直接輸入）：
  1. **Q6 附帶的口徑已在 Part A 定案**：`ai-collab/process-log.md`「V2 的 40 張：留在 fact，正式營收在人工確認前排除」（2026-10-24）。40 張留在 fact，正式營收排除 `amount_review` 清單上的訂單（使用者選 B1）
  2. 主 session 正在建 `submission/business-assumptions.md`（跨 Part 共用的業務假設）。完成後，Part C 的名詞與口徑定義要改成連到那份；**現在先不動**
- 處理第 1 件：先 grep process-log 確認該事件存在、內容和通知一致，才改文件
  - `part_c/README.md`：「名詞」的疑似 ×1000 那列補上定案；6.1 `gold_order_metrics` 那列改成引用定案，`is_amount_suspect` 改成對應 `amount_review` 清單。「營收預設用折扣前還是折扣後」**仍待確認**，因為這次定案只涵蓋 40 張
  - `ADR-08`：背景與後果改成引用定案（ADR 本身仍是草稿，決定與理由不動）
  - `.claude/work/part-c.md` 待確認清單第 6 項：拿掉這個附帶問題，只留折扣前後
- 驗證：grep「要不要排除」只剩 ADR-08 背景裡描述「這是要寫死的定義」的那句，後面已接上定案；目錄與編號重新檢查。這次是小範圍文字修改，沒有另派驗收
- 待辦：`business-assumptions.md` 完成後，把 README「名詞」與 6.1 的口徑定義改成連過去

### 1.14 三條路線的白話說明（2026-10-24）
- 使用者說自己是 Fabric 與資料工程架構新手，問「架構圖要看懂嗎」。AI 回答要能走查三條路線，使用者要求「三條路線對應的說明」
- 寫 `three-paths.md`：每條路線一張簡化圖＋逐步表（發生什麼、為什麼需要），用餐廳比喻；附走查自問題與附錄 A 名詞表
- 驗證：三張 Mermaid 圖用 mmdc 轉 SVG 成功；目錄、編號 `md_toc.py check --numbering` 與 `github-slugger` 都過
- Read-back（fresh-context opus 扮新手，只讀這份）：「有條件過」，6 題都答得出、事實對得上。依回報修正：
  - 補名詞表（撞號、晚到、Kafka、Eventhouse 等，新手看不懂）
  - 說清楚 Q1～Q10 在哪、哪幾題和三條路有關
  - 「AI 暫定」改成「寫這份設計的 AI 暫定」，避免和問數的 AI 混淆
  - 「時間最新」補上是看 `updated_at`
  - 日報路線補 L3 的 60 張晚到新單（原本只寫了 L4 的 25 張）
  - 即時路線補 `arg_max` 的限制（時間相同或時鐘不準）
- 修正後沒有再派驗收

### 1.15 README 第 3 節的三條路線由使用者自己寫（2026-10-24）
- 使用者問「三條路線的說明不是應該寫進 README 嗎」。AI 列兩個做法：A 使用者讀完 `three-paths.md` 後用自己的話寫三段，AI 只整理格式；B AI 先寫精簡版，使用者再改。AI 建議 A，理由是規劃（任務卡 C4）本來就要使用者寫走查，且可補面試官冷讀最大的扣分點（全篇都是 AI 判斷）
- **使用者選 A**。待使用者寫完後，第 3 節拆成 3.1 日報、3.2 即時、3.3 問數，標註改〔AI 產出，使用者修改〕
- **隨後改成 B**：使用者說「這個你決定就好」「因為這個架構主要是你設計的」。AI 把 README 第 3 節的三行走查改寫成 3.1 日報、3.2 即時、3.3 問數三小節，每節一張「步驟／為什麼需要」表，並連到 `three-paths.md` 當初學者版。第 3 節標註**維持〔AI 產出〕**，因為內容是 AI 寫的、使用者沒改
- 驗證：目錄與編號 `md_toc.py check --numbering` 與 `github-slugger` 都過；新段落引用的節號（5.3、6.4、第 9 節）都指到對的章節
- 使用者看過改寫後的第 3 節：「我看過初步沒問題」。沒有修改內容，標註仍維持〔AI 產出〕
- 驗收（fresh-context opus，對照架構圖與 F／E 證據）：「有條件過」。三張表都對得到圖、E4～E6 正確、節號正確。抓到 AI 的 4 處問題，都已修：
  - 「寫入後幾秒就能查（F2-10、F3-1）」說超過原文，兩條都沒有「幾秒」 → 改成 F2-10 的原意「直接查 view 會拿到最新結果」
  - 「有新資料就更新」漏引 F3-2 → 補上
  - 「看報表看不到的，問數也問不到」比 6.3、第 9 節的「報表端未查證」說得更確定 → 限縮成「權限跟著提問者本人」
  - 問數只寫查 `gold_order_metrics`，但 6.3 也授權維度表、例句「各通路」需要維度表 → 表格補維度表，架構圖加 `GOLD -->|維度表| QA`，存成 `architecture-v4.md`（mmdc 轉檔成功），v3 標「被 v4 取代」
- 修正後沒有再派驗收

### 1.16 Q1 定案：outbox＋Kafka（2026-10-26）
- 使用者要求依「資料流」順序逐題確認（產生 → 進場 → 處理 → 交付 → 把關），從第 1 站 Q1 開始
- 使用者先問三個選項怎麼實現、A 的下游有哪些。AI 用 Python 示意說明 outbox＋relay、Mirroring 的設定步驟、直接送的兩步失敗情境
- **AI 的錯（發現者：AI 自查）**：說明 A 時寫「每筆都帶 `event_id`，下游靠它去重」，但設計裡的去重靠的是「每張單只留 `updated_at` 最新的一列」，沒有用到 `event_id`。下一則回覆更正
- **使用者定案：A**。原話：「我選A在不知道真實的業務場景下，我傾向設計高可擴展的系統 而且A也可以做到B的事情，最後C的不確定性太高，出錯的場景比較多」
- 更新：`tentative-decisions.md` Q1 改標使用者定案；README 第 2 節「來源系統」那列補上使用者判斷，該節標註改〔AI 產出，使用者修改〕；工作檔清單第 1 項標已定案
- 待主 session 整理成 process-log 定案事件（不寫 ADR，Q1 原本就判定不寫）

### 1.17 Q10 選 CDC，待成本分析（2026-10-26）
- AI 說明 Q10 四個選項：A 會員表加 `updated_at`、B 等級異動紀錄表（AI 原暫定）、C 資料庫 CDC、D 會員服務也用 outbox（AI 補充，順著 Q1 的選擇）。使用者問「上游程式是指哪些」，AI 說明是營運系統的後端服務，屬於別的團隊，改它要跨團隊排程
- **使用者選 C**。原話：「C 在功能獨立性下，這個方法的改動最小 不過要分析開CDC的成本」
- 使用者主動要求成本分析：派研究 agent（opus）只查 learn.microsoft.com，寫 `cdc-cost.md`（版本與權限前提、儲存、效能、transaction log、schema 變更、和 Fabric Mirroring 的關係、CDC 記的時間是 commit 時間還是生效日）
- AI 提醒的限制：CDC 記的是資料庫修改時間，不一定是業務生效日
- 狀態：選擇已記在 `tentative-decisions.md` Q10，看完成本分析後再確認是否維持
- 使用者追問「那不就是要取決於後端的設計嗎」（指生效日）。AI 列出後端四種寫法：只有「提前改欄位又沒存生效日」拿不到生效日，其餘三種 CDC 都拿得到。結論：生效日取決於後端，設計要寫成前提，並列為向後端確認的事項（尚未寫進文件，等使用者同意）
- 成本分析回來：`cdc-cost.md`，70 條官方說法（CDC-1～CDC-70），`grep -c` 為 70，md_toc 檢查 OK。主 session 抽查 CDC-14（保留 3 天）、CDC-31～33（log 截不掉）、CDC-49、CDC-55（2025 開了 CDC 就不能 Mirroring），原文與說法一致
- 最大代價：capture job 停了或遇到長交易，營運 DB 的 transaction log 截不掉、一直長大，到上限後寫入失敗，會連累訂單。效能影響的數字只有 2008 年白皮書（變慢不到 10%），現行文件沒有數字
- 對設計的影響：change table 預設只留 3 天，Mirroring 在 Fabric 只產出現況表，所以要在 3 天內把會員表的 change table 抽出來落地到 bronze（日批每天跑，在期限內）
- 使用者追問 CDC 和訂閱事件的差異、還有沒有其他方法。AI 補了四種（每天快照、temporal table、trigger、Change Tracking，**都是一般知識、未查官方文件**），並說明這題只影響 README 第 8 節，選錯好改
- **使用者：「這提可以跳過吧」**。處理：維持先前選的 C（理由仍是原話「功能獨立性下改動最小」），不再細究。README 第 8 節改寫：標〔使用者判斷〕選 CDC，〔AI 補充〕CDC 的代價（log 截不掉、變更只留 3 天）、commit 時間不等於生效日、替代方案「每天快照」

### 1.18 Q2 定案：補 bronze，訂單事件也落地（2026-10-26）
- AI 說明 Q2，並指出和 Q10 的關聯（CDC 變更只留 3 天，沒有 bronze 就無處落地）。使用者問「通常 DE 會怎麼解」、medallion 有沒有學習筆記（有：`learning/0-storage/etl-elt-medallion.md`）、Kafka 長期保留重播是什麼設計、bronze 和 Kafka 怎麼取捨。AI 說明業界常見分工：Kafka 留短負責送與短期重播，事件另外落地到 bronze 長期保存（一般知識，未查官方文件）
- **使用者定案：A**。原話：「A 補bronze，事件也落地，因為上游不保證能重給」
- 更新：README 第 2 節該列標〔使用者判斷〕；架構圖加 `ES -->|事件落地| BRONZE`，MSSQL 到 bronze 的標籤加「含會員 CDC 變更」，存成 `architecture-v5.md`；3.2 與第 4 節的 Eventstream、bronze 兩列跟著改；`tentative-decisions.md` Q2、工作檔第 2 項標已定案
- `three-paths.md` 即時路線第 3 步同步補上「事件另存一份到 bronze」

### 1.19 Q10 改定案：不開 CDC，每日 bronze 比對（2026-10-26）
- Q2 定案補 bronze 後，**使用者自己發現**：「CDC不就可以拿掉」。AI 確認：日批每天把會員表原樣抽進 bronze，等於每天一份會員快照，比對前後兩天就知道哪天變動，上游與 DBA 都不用動；代價是一天內變動兩次只看得到最後一次
- **使用者定案（推翻 1.17 的 C）**。原話：「有了每日 bronze，精確到天就夠，不用承擔 CDC 的風險」
- 使用者要求另派 agent 查雄獅的會員升等規則，檢驗「精確到天就夠」的前提：派研究 agent（opus），寫 `lion-member-tier-rules.md`，查證中
- 更新：README 第 8 節「會員變動時間」改寫（〔使用者判斷〕每日 bronze 比對；〔AI 補充〕曾考慮 CDC 與否決原因、連到 `cdc-cost.md`）；第 4 節 bronze 那列；架構圖標籤改「含會員表」，存成 `architecture-v6.md`；`tentative-decisions.md` Q10 保留先前選 C 的紀錄；工作檔第 10 項。`cdc-cost.md` 保留，當作否決 CDC 的依據
- 雄獅會員規則查證回來（`lion-member-tier-rules.md`，研究 agent 用官方會員條款、等級總覽、雄獅幣 FAQ 三頁）：**「精確到天」成立**，官方 FAQ「升等後，會員等級效期將自當天起重新計算一年」，規則全以日為單位。主 session 抽查原文句存在
- 附帶發現寫進 README 第 8 節：續等時等級不變、只有效期變，比對要連效期欄位。不確定處（條款寫「次日起」、FAQ 寫「當天起」差一天；升等日＝歸戶日是推論）留在查證檔

### 1.20 Q3 選 B：gold 放 Warehouse（2026-10-26）
- 使用者問「Part A 哪裡寫 gold」。AI 查程式：Part A 沒有名為 gold 的層，`fact_order`、`dim_member`、`dim_product`、`dim_date` 都經共用函式 `merge_upsert`（`delta_io.py`）以 Delta MERGE 寫入，呼叫點是 `load_order_batch`、`write_dim_member`、`write_dim_product`、`write_dim_date`
- **使用者選 B**。原話：「B 對下游營運來說只需要學sql」，並要求記錄改動範圍：「要改的主要是 merge_upsert 這一個函式的四個呼叫點，改成用 T-SQL 寫入 Warehouse」（這句是 AI 前一則的估計，使用者採用）
- 記錄：ADR-06「決定」「理由」寫入使用者原話（狀態仍是草稿，由使用者改成已定案）；後果補 B 的改動範圍與兩個未查證事項（time travel 重跑能否沿用、Spark 怎麼寫進 Warehouse）
- **AI 提出疑點，等使用者回應**：Lakehouse 的 SQL endpoint 也讓下游用 SQL 讀（F4-1）；B 的差別在「gold 由誰、用什麼維護」。README 第 3、4、5.1 節與架構圖暫不改
- 使用者問「gold 的資料被更新會影響我們 pipeline 嗎」。AI 說明會：狀態機以 fact 現況比對新資料（`_fact_before_batch`）、MERGE 會蓋掉手動修正、對帳抓不到手動刪除、重算會抹掉修改；業界做法是 gold 只讓管線寫、下游唯讀，下游另建衍生表（一般知識）
- **使用者維持 B**。原話：「維持B，下游用SQL建自己的衍生表」
- 更新：ADR-06 改名 `ADR-06-gold-in-warehouse.md`、標題改為「bronze／silver 用 Lakehouse，gold 放 Warehouse」，理由補原話，後果補「gold 對下游唯讀」「權限要重新設計」；索引同步。README：架構圖拆出 Warehouse 子圖（gold、`gold_order_metrics`、下游衍生表），silver 到 gold 用 T-SQL MERGE；3.1、第 4 節、5.1（判斷改標〔使用者判斷〕，第 5 節標註改〔AI 產出，使用者修改〕）、第 7 節、第 9 節；6.3 加註「gold 改放 Warehouse 後要重新設計，待 Q8」。ADR-08、`three-paths.md` 同步
- **連帶影響**：原本的權限設計建立在 Lakehouse 的 OneLake security 上，Warehouse 的 SQL 列權限只在 SQL 連線時生效（F8-10），所以 Q8 要重新決定
- 驗收（fresh-context opus）：「有條件過」。Mermaid 能 render、目錄檢查 OK、沒有指向舊 ADR-06 檔名的連結、ADR-06 是草稿。抓到 AI 的 7 處問題，都已修：
  - 6.2 的已知限制還寫「會員等級是月快照」，和 Q10 矛盾 → 改成精確到天
  - 寫「前一天的資料」，但 Q10 要每天抽**整張**會員表 → 3.1、第 4 節、`three-paths.md` 註明
  - 第 4 節權限列、第 9 節仍以 OneLake security 管 gold → 補「待 Q8 重新設計」
  - 「四張表的 MERGE 要錯開」說超過 F4-5（衝突發生在**同一張表**的並行交易）→ README、ADR-06 改正
  - **歸屬灌功**：5.1 把「手動修改會讓狀態機誤判」這段 AI 提出的理由標成〔使用者判斷〕→ 拆成〔使用者判斷〕＋〔AI 補充〕
  - ADR-06 選項 B 的好處寫「分析師能直接維護 gold」，和「gold 下游唯讀」矛盾 → 改正
  - 第 5 節開頭、`tentative-decisions.md`、`three-paths.md` 的狀態說明還寫「全部 AI 暫定」→ 更新為已定案 Q1、Q2、Q3、Q10
- 修正後沒有再派驗收

### 1.21 Q4 討論中：即時方案的計費（2026-10-26）
- 使用者要求更了解 Q4。AI 用同一個情境（訂單取消＋Kafka 重送）走 A（Eventhouse 的 `arg_max` materialized view）與 B（Spark Structured Streaming 每分鐘一批）兩條路，附 KQL 與 PySpark 示意，比較延遲、要學的、規則份數、要顧的程式
- 使用者問「Eventhouse 要錢嗎」。派研究 agent（opus）只查官方文件與價格頁，寫 `realtime-cost.md`（51 條，COST-1～COST-51）。研究 agent 回報寫完後檔案被改過；主 session 重跑檢查：`grep -c "https://"` 51、md_toc 檢查 OK，並抽查 COST-3、COST-24、COST-30 原文
- 結論：Fabric 依 capacity（F SKU）付固定費用，所有工具共用 CU，用超過是被限速、不會多收；Eventhouse 另收儲存費。資料一直進來時，A（Eventhouse UpTime 100%）和 B（常駐串流作業）都整天耗用 CU；差別在要買多大的 SKU。官方沒有 A vs B 的成本比較，價格頁抓不到實際金額
- **使用者定案：A（Eventhouse）**。原話：「多學 KQL，換到省心和秒級」。這句沿用 AI 前一則提出的對比框架，由使用者選定；ADR-07 理由同時附上使用者先前自己說的「我認為重要的是思考方式不是sql or kql」
- 更新：ADR-07 決定與理由（狀態仍是草稿）；README 5.2 判斷改標〔使用者判斷〕，原本的比較改標〔AI 補充〕，第 5 節開頭改「5.1、5.2 已定案」；`tentative-decisions.md`、`three-paths.md`、工作檔同步

### 1.22 Q5 採用 AI 建議：標初估＋取最新＋每日對帳（2026-10-26）
- AI 說明 Q5：即時層只做「每張單只留最新狀態」，做不到撞號（每天約 600 筆，會讓兩張單合併成一張）、疑似 ×1000 金額、晚到新單歸日；選項 A 標初估＋每日對帳、B 即時也多做清理、C 只放不受影響的指標
- 使用者問「訂單事件的準即時儀表板」怎麼理解。AI 說明用途是營運即時發現趨勢與異常，分鐘級即可。**AI 順帶提醒**：題目只要分鐘級，Q4 理由寫的「秒級」超出需求，面試可能被問
- **使用者：「根據你的建議 我直接使用」**。記為「採用 AI 建議」，不是使用者自己的判斷；依專案規則，相關內容標〔AI 產出，使用者修改〕，不標〔使用者判斷〕
- Q4 的理由沒有改；使用者若也要採用 AI 提的說法（「秒級不是需求，主因是省心」），另外確認

### 1.23 Q6 討論中（2026-10-26）
- AI 說明 Q6：規則寫在 semantic model（A）、全部寫進 gold 表（B）、口徑寫進 `gold_order_metrics`、Power BI 只做加總（C，AI 暫定），附 F5-5（Direct Lake 要讀實體表）、F6-6／F6-8（data agent 查 semantic model 時忽略 instructions、不支援範例問答）；另有子題「營收預設折扣前或折扣後」
- 使用者：「C照你的建議」。Q6 會寫進 ADR-08，依專案規則（`CLAUDE.md`「定案不接受只回照建議」）請使用者補一句自己的理由，尚未定案
- 使用者補充：「就照你的決策 我這裡沒有太多的業務知識 只能選一個作通用的」。記為**採用 AI 建議**，理由是使用者的原話（業務知識不足時選通用做法）。ADR-08 決定與理由寫入原話（狀態仍是草稿）；README 5.3 判斷標〔AI 產出，使用者修改〕，不標〔使用者判斷〕；第 5 節開頭改「5.3 由作者採用 AI 的建議」
- 子題「營收預設折扣前或折扣後」尚未決定
- 子題「營收預設折扣前或折扣後」：AI 列折扣前、折扣後，並提出業務知識不足時的通用做法「兩個都給」。**使用者：「兩個都給」**。更新 README 6.1 指標表那列與易混名詞表、ADR-08 後果、`tentative-decisions.md`、工作檔

### 1.24 Q7 定案：自建問數服務（2026-10-26）
- AI 說明 Q7：A Fabric data agent（設定式、以提問者身分查詢，但不支援非英文、最多 25 列、不能換模型）、B 自建（LLM＋指標定義檔＋SQL 執行器，附 Python 示意）、C 先用中文黃金問題集 POC data agent 再決定（AI 原暫定）。AI 建議為 Q7 補 ADR
- **使用者定案：B**。原話：「B 因為我偏好自己作」
- 更新：README 架構圖問數方塊改「自建問數服務」，存成 `architecture-v8.md`；3.3、第 4 節、6.3（唯讀與列數改由 SQL 執行器負責；身分傳遞待 Q8）、6.4（評估改自建程式）、6.4 之後的「問數工具本身」標〔使用者判斷〕＋〔AI 補充〕、第 9 節；ADR-08 背景與後果（自建只能讀 SQL，口徑放 gold 表的效益成立）；`three-paths.md`、`tentative-decisions.md`、工作檔
- AI 建議補 ADR，**使用者：「不要」**。Q7 只記在 process-log 定案事件

### 1.25 Q8 採用 AI 建議：表層級權限、服務帳號（2026-10-26）
- AI 說明 Q8 兩題：(1) 能看哪些表：只開 gold 指標表、維度表與 `dq_batch_summary`，後者由管線寫一份進 Warehouse；(2) 用誰的身分：A 提問者本人身分（精確，但自建服務的做法未查證，報表還要另設 semantic model 列權限）、B 服務帳號＋只做表層級（簡單）、C 服務帳號＋程式自己過濾（危險）。關鍵問題是雄獅需不需要列層級權限，題目沒說。AI 建議 B，並把 A 寫成升級路徑
- **使用者：「先照建議沒問題」**。記為採用 AI 建議，標〔AI 產出，使用者修改〕
- 更新：README 6.3 整節改寫（原本是 gold 在 Lakehouse、data agent 以提問者身分的設計）；架構圖 `dq_batch_summary` 移進 Warehouse、權限方塊與提問者方塊改寫，存成 `architecture-v9.md`；3.3、第 4 節、第 9 節；ADR-06 後果註明已處理；`three-paths.md`、`tentative-decisions.md`、工作檔
- 驗收（fresh-context opus，Q5～Q8 這輪）：「有條件過」。Mermaid 能 render、圖上元件都在職責表。抓到 7 處，都已修：
  - 第 10 節還寫「改成以 OneLake security 為目標」，和 Q8 矛盾 → 改成 Q8 現況
  - README 開頭還寫「所有方向選擇仍是 AI 暫定」，第 10 節還寫「確認或推翻各題」→ 更新為定案／採用建議清單
  - **歸屬灌功兩處**：「兩個都給」標成〔使用者判斷〕，但那是 AI 提的通用做法 → 改〔AI 產出，使用者修改〕；5.2 的〔使用者判斷〕裡混了 AI 整理的「成本不是決定因素」→ 移到〔AI 補充〕
  - 第 3、4、6 節已承載使用者的定案或採用建議，`##` 仍標〔AI 產出〕→ 改〔AI 產出，使用者修改〕
  - ADR-07 還寫「data agent 可以接 KQL database」，和 Q7 自建矛盾 → 改正
  - `three-paths.md` 還寫「Q4 等你決定」→ 改成被否決的替代方案
- 修正後沒有再派驗收

### 1.26 Q9 採用 AI 建議：陷阱題 100%、一般題 90%（2026-10-26）
- AI 說明 Q9（黃金問題集怎麼考、三個機制：上線門檻、回歸測試、上線後抽查），使用者要求 ELI5，AI 用「新店員上班前考試」說明。使用者再問題目要求 3（Text-to-SQL 配套）怎麼理解，AI 對照 README 第 6 節四類各建了什麼、合格與不合格寫法的差別
- AI 提醒：使用者選模組 F 不是 E，評估機制不用做太深
- **使用者：「OK 照你的建議」**。記為採用 AI 建議；及格線是 AI 提的起點，不是查證來的標準，README 6.4 照實標註
- **Q1～Q10 全部處理完**：作者定案 Q1～Q4、Q7、Q10、營收「兩個都給」；採用 AI 建議 Q5、Q6、Q8、Q9

### 1.27 補處理主 session 留下的待辦（2026-10-26）
- **AI 的錯（發現者：AI 自查）**：主 session 在 2026-10-24 把三件事直接寫進 `.claude/work/part-c.md`（當時以為本 session 已結束），本 session 之後讀工作檔只看了前半段，直到 Q9 結束更新清單時才看到。期間 1.13 節照通知寫了「正式營收排除…（Part A 已定案）」，但 Part A 後來改口：只定「40 張人工確認前不計入下游金額指標」，**營收的定義屬於 Part C**（process-log「營收的定義不在 Part A 決定，移到 Part C 語意層」）
- 處理：README「名詞」與 6.1、ADR-08 背景與後果改成上述說法並引用 `business-assumptions.md` 3.7；README「名詞」開頭加一句連到 `business-assumptions.md`；工作檔註明已處理
- 新增待確認：**營收含不含已取消的訂單**（Q6 子題；折扣前後已定案「兩個都給」）
- 1.13 節是當時的紀錄，不改寫，以本節為準
- AI 列出「已取消算不算營收」三個選項（不算、算、兩個都給），沒有給建議。**使用者定案：「不算」**。更新 README 6.1（`gold_order_metrics` 加 `order_status`，營收不含已取消）與易混名詞表、ADR-08 後果、`tentative-decisions.md`、工作檔
- 營收的定義至此完整：不含已取消、折扣前後兩個都給、人工確認前排除 `amount_review` 清單上的 40 張。`business-assumptions.md` 是主 session 維護的檔，本 session 不改，交由主 session 決定要不要補一條

### 1.28 ADR-06～08 改為已定案（2026-10-26）
- AI 列出收尾事項，第 1 項是「把 ADR-06～08 狀態改成已定案」。使用者：「你幫我」
- **偏離書面規則，照實記錄**：`CLAUDE.md` 與 adr skill 寫「狀態只有使用者能改成已定案，AI 不得修改」。這次是使用者明確指示 AI 代改，AI 照做，並在三份 ADR 的狀態欄寫明「使用者指示 AI 代改」
- 更新：ADR-06、07、08 狀態改「已定案」；`decisions/README.md` 索引同步；ADR 內「狀態仍是草稿」的句子改成已定案；README 第 10 節待辦移除這項；工作檔同步
- 沒動：索引裡 ADR-05 仍寫「草稿」、但 ADR-05 檔案本身是「已定案」，這是 Part A 的檔，留給主 session
- 第 8 節「給上游的改善建議」要不要留：第 1 輪 Spec 審查認為是 Part A 範圍；AI 建議留（兩段都和 Part C 架構直接相關，且是〔使用者判斷〕最多的一節）。**使用者：「流」**（AI 理解為「留」的錯字）→ 保留
- C2 驗收條件「使用者親自點開兩個連結核對」：使用者開 F7-8（concept-data-agent 頁 Limitations），回報「有看到」「doesn't currently support non-English languages」這句。F2-2 待核對

### 1.29 收尾（2026-10-26）
- 使用者：「你幫我收尾」。剩下的兩件原本要使用者親自做，AI 代做並照實記錄：
  - **F2-2 連結核對由 AI 做，不是使用者**：AI 用 WebFetch 開 event-house-onelake-availability 頁，確認表格原文「Up to 3 hours, or until files of sufficient size (typically 200-256 MB) are created | 5 minutes to 3 hours」。C2 驗收條件「使用者親自點開兩個連結」只完成一個（F7-8）
  - **README 第 10 節由 AI 依紀錄撰寫**，標〔AI 產出〕並寫明是作者指示、尚未改寫。原素材清單裡「作者已定案：營收兩個都給」是錯的（那是採用 AI 建議），撰寫時改正
- 交接主 session 的清單寫進 `.claude/work/part-c.md`「交接」
- 最終驗收（fresh-context opus，整份 Part C）：**有條件過**。Spec 四項都完成；md_toc OK、Mermaid 能 render、沒有程式碼行號；抽查 6 個 F 編號、3 個〔使用者判斷〕都對得上。抓到 4 處，處置：
  - 5.3 的事實仍以 data agent 為主，和 Q7 自建脫節 → 主要論據改成「自建問數只能讀 SQL、讀不到 DAX」，data agent 降為背景
  - 5.2〔使用者判斷〕的句子是 AI 提的框架，README 沒揭露 → 補註來源
  - ADR-06 同一行先寫「Q8 已處理」又寫「待 Q8」→ 刪掉過時字句；三份已定案 ADR 裡舊草稿的〔待使用者確認〕標記改成〔AI 原草稿，已被上方定案取代〕
  - ADR-06～08「關聯」欄連不到 process-log 事件 → **未修**，process-log 由主 session 寫，已在工作檔交接清單第 2 項
- 修正後沒有再派驗收
