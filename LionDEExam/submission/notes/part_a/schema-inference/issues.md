# 問題總表

回到：[README.md](README.md)

noise＝題目刻意埋進資料的錯誤值。編號沿用原報告（V＝違反、L＝可能合法、J＝待使用者判斷），其他文件與 process-log 都用這些編號引用。表依細節檔主題分組，不依編號排序。V11 已改列為 J3。

**類型**：
- **確定的錯誤值**：違反的約束有強證據（多數值幾乎 100% 遵守、或違反值本身不合理），而且值本身是錯的。例外：V5 是格式錯、值正確（照字面解析可還原同一時刻）。
- **未知值的哨兵**：上游用特定值表示「不知道」（-1、N/A、1900-01-01），違反值域但不是錯誤的值，處理方式應與錯誤值分開考慮。
- **可能合法的業務狀況**：只違反推出來的「常態」，但業務上說得通。
- **待使用者判斷**：資料推不出來。

所有類型都不含處理建議。

## 訂單的身分：撞號、重複、主鍵 → [order-identity.md](order-identity.md)

| # | 一句話 | 影響筆數 | 類型 | 細節 |
|---|---|---|---|---|
| V7 | base 同 order_id 兩列，內容完全相同，只差 `updated_at` 幾秒 | 40 組（多 40 列） | 確定的錯誤值 | [V7](order-identity.md#v7) |
| J1 | orders 主鍵是 `order_id` 還是 `order_id + 版本` | — | 待使用者判斷 | [J1](order-identity.md#j1) |
| J2 | 增量檔與 base 同 id 但內容像另一張單：noise 還是合法更新 | day1 603 / day2 602 / day3 603 列 | 使用者判斷：noise（ADR-03） | [J2](order-identity.md#j2) |
| J3 | 增量檔同檔同 id，但會員、金額、下單時間都不同（原 V11） | 6 組、12 列 | 待使用者判斷 | [J3](order-identity.md#j3) |
| J4 | 哪些欄位在原系統不可修改 | — | 待使用者判斷 | [J4](order-identity.md#j4) |

## 訂單的時間：時區、格式、晚到與亂序 → [order-time.md](order-time.md)

| # | 一句話 | 影響筆數 | 類型 | 細節 |
|---|---|---|---|---|
| V5 | base 下單時間有 Z（UTC）與無標記（台北）兩種非標準格式 | 6,002 筆 | 確定的錯誤值（格式錯、值正確） | [V5](order-time.md#v5) |
| L1 | 增量檔 `updated_at` 晚於批次日 | 3,290 / 3,257 / 3,263 | 可能合法 | [L1](order-time.md#l1) |
| L2 | base 有 `updated_at` 落在 07-01～07-03 的列 | 2,265 列 | 可能合法 | [L2](order-time.md#l2) |
| L3 | day2 有 base 沒有的晚到新單 | 60 列 | 可能合法 | [L3](order-time.md#l3) |
| L4 | day1→day2 再出現的 id，day2 送來的是較舊事件 | 25 個 id | 可能合法 | [L4](order-time.md#l4) |
| J6 | 新舊以檔案順序還是 `updated_at` 為準、base 萃取時點 | — | 待使用者判斷 | [J6](order-time.md#j6) |
| L10 | completed 的訂單出發日都還沒到 | 28,612 列 | 可能合法 | [L10](order-time.md#l10) |
| J8 | completed 的業務語意 | — | 待使用者判斷 | [J8](order-time.md#j8) |

## 訂單的金額、幣別與參照 → [order-amount.md](order-amount.md)

| # | 一句話 | 影響筆數 | 類型 | 細節 |
|---|---|---|---|---|
| V1 | base amount 為負數 | 50 筆 | 確定的錯誤值 | [V1](order-amount.md#v1) |
| V2 | base amount 約多乘 1,000 | 40 筆 | 確定的錯誤值 | [V2](order-amount.md#v2) |
| V4 | base currency = 'NTD'（TWD 的別名） | 200 筆 | 確定的錯誤值 | [V4](order-amount.md#v4) |
| V3 | base coupon_discount = -1.0 | 300 筆 | 未知值的哨兵 | [V3](order-amount.md#v3) |
| J5 | coupon -1.0 代表「沒有折扣」還是「折扣未知」 | — | 待使用者判斷 | [J5](order-amount.md#j5) |
| J10 | amount 是折扣前還是折扣後 | — | 待使用者判斷 | [J10](order-amount.md#j10) |
| L5 | base JPY 金額帶非零小數 | 80 列 | 可能合法 | [L5](order-amount.md#l5) |
| V6 | base product_id 不在產品主檔 | 120 筆 | 確定的錯誤值 | [V6](order-amount.md#v6) |
| L6 | 訂單的產品 `is_active = 'N'` | base 4,270、day1 184、day2 182、day3 195 | 可能合法 | [L6](order-amount.md#l6) |
| L7 | 同一 product_name 對應多個 product_id | 44 個名稱 | 可能合法 | [L7](order-amount.md#l7) |
| L12 | TWD 不在 fx_rates | base 66,890；增量 3,069 / 3,150 / 3,141 | 可能合法 | [L12](order-amount.md#l12) |

## 會員快照 → [members.md](members.md)

| # | 一句話 | 影響筆數 | 類型 | 細節 |
|---|---|---|---|---|
| V8 | 同一會員同一 extract_date 兩列，只差 member_level | 30 組 | 確定的錯誤值 | [V8](members.md#v8) |
| V9 | city = 'N/A' | 71 列 | 未知值的哨兵 | [V9](members.md#v9) |
| V10 | birth_date = 1900-01-01 | 81 列 | 未知值的哨兵 | [V10](members.md#v10) |
| J7 | N/A、1900、同日兩列要不要視為未知、怎麼挑 | — | 待使用者判斷 | [J7](members.md#j7) |
| J9 | 真實生日被 1900-01-01 覆寫 | 5 人 | 待使用者判斷 | [J9](members.md#j9) |
| L8 | 註冊時未滿 18 歲 | 455 列 | 可能合法 | [L8](members.md#l8) |
| L9 | member_level、city 在快照間改變 | level 434 人、city 376 人 | 可能合法 | [L9](members.md#l9) |
| L11 | 後續快照有與前次完全相同的列 | 185 列 | 可能合法 | [L11](members.md#l11) |

products 與 fx_rates 沒有發現違反，見 [schema.md](schema.md)。
