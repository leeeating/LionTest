# 架構圖 v4（2026-10-24；2026-10-26 起被 v5 取代）

- 狀態：中間產物存檔；正本在 `part_c/README.md`。所有選擇仍是〔AI 暫定，待使用者確認〕
- 和 v3（`architecture-v3.md`）的差別：加一條 `GOLD -->|維度表| QA`。驗收 agent 指出 6.3 授權問數讀維度表、例句「各通路」也要用到維度表，但 v3 圖上只有指標表連到問數服務

```mermaid
flowchart LR
  subgraph SRC[營運系統]
    APP[訂單服務] -->|同一個 DB 交易| OUTBOX[(outbox 表)]
    MSSQL[(MSSQL<br/>訂單／會員／產品)]
  end

  OUTBOX -->|relay| KAFKA[[Kafka]]

  subgraph RT[即時鏈路：分鐘級]
    KAFKA -->|Kafka 來源| ES[Eventstream]
    ES --> RAW[(Eventhouse<br/>order_event 原始表)]
    RAW --> MV[(materialized view<br/>arg_max by order_id)]
    MV --> RTD[Real-Time Dashboard<br/>標「初估」]
  end

  subgraph LH[批次鏈路：Lakehouse，每日]
    MSSQL -->|Data Factory 每日抽取| BRONZE[(bronze<br/>原樣落地)]
    BRONZE -->|Spark：Part A 管線| SILVER[(silver<br/>quarantine_order／batch_log)]
    SILVER --> GOLD[(gold<br/>fact_order／dim_*)]
    GOLD -->|Spark 寫出| METRICS[(gold_order_metrics<br/>指標口徑實體表)]
    SILVER --> DQ[(dq_batch_summary<br/>收到／計入／擋下／不採用)]
  end

  METRICS -->|Direct Lake on OneLake| SM[Power BI semantic model]
  SM --> PBI[每日 BI 報表]

  METRICS --> QA[問數服務<br/>data agent 或自建，待 POC]
  GOLD -->|維度表| QA
  DQ --> QA
  META[[指標定義檔<br/>＋欄位描述]] -.產生.-> METRICS
  META -.產生.-> SM
  META -.instructions／RAG.-> QA
  GQ[[黃金問題集]] -.上線門檻.-> QA
  QA --> USER[提問者<br/>以本人身分查詢]
  SEC[[OneLake security<br/>表與列權限]] -.-> METRICS

  MV -.每日對帳.-> GOLD
```
