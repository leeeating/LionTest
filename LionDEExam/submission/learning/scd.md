# SCD（Slowly Changing Dimension）名詞總覽：Type 0～4 與 6
SCD（**緩慢變化維度**）是「維度表裡的屬性改了，要怎麼處理舊值」的一組做法；Type 只是編號，差在**舊值保不保留、保在哪**。本篇涵蓋 Type 0、1、2、3、4、6；Type 5（Type 4 mini-dimension 加上指向目前 mini 列的 Type 1 參照，[Kimball](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-5/)）與 Type 7（Type 1／Type 2 兩種視角共用一張維度，[Kimball](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-7/)）本篇未涵蓋。

## 白話版
會員王小明 4/30 是銀卡，5/31 升金卡。5/15 的訂單要答「銀卡」還是「金卡」？看你選哪個 Type：

- **Type 0**：永遠是第一次的銀卡，不管後來怎樣。
- **Type 1**：`member["M001"] = "金卡"`（dict 覆寫），舊值消失，5/15 的訂單也變金卡。
- **Type 2**：`versions.append(...)`（list append），銀卡、金卡各一列、各有有效期間，5/15 答銀卡。
- **Type 3**：多一欄 `previous_level`，只記「上一個」值，再早的就沒了。

Type 2 怎麼 join 事實見 [point-in-time-join.md](point-in-time-join.md)；本題程式的 SCD2 錯在哪見 [這份程式的 SCD2 錯在哪](../notes/part_b/scd2.md)。

## Type 2 細節（沿用王小明的例子）
兩版都留，各自標有效期間：

| member_id | 等級 | valid_from | valid_to | is_current |
|---|---|---|---|---|
| M001 | 銀卡 | 2026-04-30 | 2026-05-31 | false |
| M001 | 金卡 | 2026-05-31 | 9999-12-31 | true |

查 5/15 的訂單，找「5/15 落在哪一列的區間內」得到銀卡；5/31 的訂單落在金卡那列。區間是**半開**的（`valid_from <= order_date < valid_to`），所以舊版 `valid_to` 與新版 `valid_from` 同一天，那天的訂單也只會對到一版。

**每次更新做三件事**：
1. **關舊版**：目前版本的 `valid_to` 填上日期，`is_current` 改 false。
2. **加新版**：插入新列，`valid_to` 寫 9999-12-31（代表「到現在都有效」）。
3. **沒變就不動**：屬性沒變的會員不要多產生版本。

**陷阱：初始載入只拿最新快照，歷史就沒了。** 「只取每人最新一筆」只適合 dim 已有歷史後的每日增量。dim 從空表開始時，若直接拿最新快照跑，每人只建出最新那一版，舊版永遠進不來，退化成 Type 1；再搭配半開區間 join，早於那唯一一版 `valid_from` 的事實會對不到任何版本（屬性變 null）。類比：list 初始化時只 append 了最後一筆。

**初始載入的做法**（二選一，之後再接每日增量）：
- 依快照日由舊到新逐批跑同一段 MERGE（04-30 → 05-31 → 06-30）：最單純，屬性沒變的批次自然不會多一版。
- 一次性從全部快照算出每版的 `valid_from`、`valid_to`：要自己合併「相鄰兩筆屬性相同」的快照，也要先處理同日同分。

**第一版的 `valid_from` 定在哪**（業務定義，要跟業務確認）：
- 第一筆快照的日期：只記實際看到的；早於它的事實會對不到。
- `register_date`：從註冊起就有一版；但註冊時的屬性是推定，不是觀測到的。
- 很早的固定日期（如 1900-01-01）：一定對得到；同樣是推定，而且看不出哪段是推定。

## 名詞表
| 名詞 | 說明 |
|---|---|
| Dimension／Fact | 維度表描述「誰、什麼」（會員、產品），變化慢；事實表記錄「發生了什麼」（訂單），一直新增。 |
| Type 0 | 屬性永不改變，事實永遠歸在原始值。**用**：出生日期、首次註冊管道這類本來就不該變的值。 |
| Type 1 | 直接覆蓋舊值，不留歷史。**用**：更正錯字，或只在乎目前值。 |
| Type 2 | 新增一列保留舊版，配新的 surrogate key。**用**：需要「當時」的屬性（會員等級、所屬部門）。 |
| Type 3 | 加新欄位存舊值，主欄位覆蓋成新值。**用**：只需比較「新舊兩個值」，例如組織改制前後對照。 |
| Type 4 | 把變動快的屬性拆到另一張 mini-dimension（有自己的 key），事實表同時帶主維度與 mini 兩個 key。mini 的每一列通常是一種屬性組合（常為分級後的值）。**用**：屬性變很頻繁，放同一張表 Type 2 會暴增列數。 |
| Type 6 | Type 2 加上每列都內嵌「目前值」（Type 1 覆蓋），可用「當時」或「現在」分組。**用**：同一份報表兩種看法都要。 |
| natural key（business key）| 業務上本來就有的識別碼，例如 `member_id`；Type 2 下會重複出現多列。 |
| surrogate key | 倉儲自己產生、無業務意義的代理鍵；Type 2 每個版本一個，事實表可存它來鎖定版本。 |
| `valid_from`／`valid_to`／`is_current` | Type 2 的有效期間欄位：版本從何時起、到何時止（目前版本常填 `9999-12-31`）、是否為最新一版。 |
| 半開區間 | `valid_from <= t < valid_to`，含起不含迄，邊界日只會落在一版，不會重複配對。 |
| point-in-time join | 讓每筆事實對到它發生「當時」的維度版本，見 [point-in-time-join.md](point-in-time-join.md)。 |
| snapshot（快照）| 每次整批抄一份來源的當下全貌（如每月一份名冊）；它是 SCD2 的**原料**，不是 SCD2 本身。 |

## 比較表
| Type | 保留歷史？ | 表怎麼長大 | 查「當時」的值 |
|---|---|---|---|
| 0 | 只有原始值 | 不長 | 簡單（永遠是原始值） |
| 1 | 否 | 不長，原地覆蓋 | 做不到 |
| 2 | 完整 | 每次變更多一列 | 要 point-in-time join，中等 |
| 3 | 只有上一版 | 不長，多一欄 | 只能答新／舊兩種 |
| 4 | 部分：歷史靠事實表上的 mini key 保留；期間內沒有事實發生的變更不會被記到 | 主表不長；mini 表只在出現新屬性組合時才長 | 看事實列帶的 mini key，簡單，但只對有事實的時點成立 |
| 6 | 完整＋目前值 | 同 Type 2，更新時要改整組舊列 | 兩種都簡單，但寫入較複雜 |

## 本專案出處
`members.csv` 是多次快照（`extract_date` 不同），是做 Type 2 的原料；`buggy_pipeline` 的 `update_dim_member` 自稱 SCD2 卻做錯，見 [這份程式的 SCD2 錯在哪](../notes/part_b/scd2.md)。

## 官方文件
- 已讀（Kimball Group, Dimensional Modeling Techniques）：[Type 0](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-0/)、[Type 1](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-1/)、[Type 2](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/)、[Type 3](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-3/)、[Type 4](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-4/)、[Type 6](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-6/)。
- Kimball 定義對照：Type 0 值永不變；Type 1 覆蓋；Type 2 新增列、配新 surrogate key，加 effective／expiration／current indicator 三欄；Type 3 加新欄位存舊值；Type 4 拆成 mini-dimension；Type 6 是 Type 2 內嵌 Type 1 目前值；Type 5、7 的定義見開頭連結（已讀）。
- 未證實：Type 4 的「mini 每列是一種屬性組合、新組合才長、無事實的變更不被記錄」，Kimball type-4 頁沒寫（頁面只說明拆出變動快的屬性、mini 有自己的主鍵、兩個 key 都放進事實表），此為依 mini-dimension 設計的業界理解。
- 未證實：Type 2 初始載入的兩種做法（依快照日逐批 MERGE、一次性回填）與第一版 `valid_from` 的選項，是通用實務，未對照官方文件。
- 未證實：各 Type 的「什麼時候用」是依各定義推得的使用情境，非 Kimball 原文；natural key、snapshot、`is_current` 的命名與 `9999-12-31` 填法、半開區間，這次沒讀到 Kimball 對應的定義頁（SCD 總覽頁回 404），為通用業界慣例。
