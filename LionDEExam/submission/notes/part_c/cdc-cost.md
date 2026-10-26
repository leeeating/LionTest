# SQL Server CDC 的成本（Part C Q10 用）
- 查詢日期：2026-10-26；查詢者：研究 subagent
- 範圍：只查 learn.microsoft.com（SQL Server、Microsoft Fabric、SQL Server 支援文章）。每列附 URL 與英文原文短引；官方沒寫的放在第 6 節「未查到或不確定」
- 用途：判斷「開 CDC 記錄會員表每次變動」是否站得住，以及設計文件要寫的代價與緩解
- 注意：效能數字唯一來源是 SQL Server 2008 時代的官方 best practices 白皮書（已封存），現行文件沒有量化數字，引用時要標明年代

## 目錄
- [1. 前提條件](#1-前提條件)
- [2. 運作方式](#2-運作方式)
- [3. 成本](#3-成本)
  - [3.1 儲存](#31-儲存)
  - [3.2 效能](#32-效能)
  - [3.3 Transaction log](#33-transaction-log)
  - [3.4 維運：schema 變更與監控](#34-維運schema-變更與監控)
  - [3.5 高可用與還原](#35-高可用與還原)
- [4. 和 Fabric 的關係](#4-和-fabric-的關係)
  - [4.1 Mirroring](#41-mirroring)
  - [4.2 Eventstream](#42-eventstream)
- [5. CDC 記的時間](#5-cdc-記的時間)
- [6. 白話結論](#6-白話結論)

## 1. 前提條件

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-1 | SQL Server 2022 的 edition 表：CDC 只有 Enterprise、Standard 支援；Web、Express 不支援（Developer／Evaluation 等同 Enterprise）。2016–2019 的 edition 表本次沒逐頁查 | https://learn.microsoft.com/en-us/sql/sql-server/editions-and-components-of-sql-server-2022 | "Change data capture \| Yes \| Yes \| No \| No \| No" |
| CDC-2 | 還原或附加帶 CDC 的資料庫到 Standard、Enterprise 以外的 edition 會被擋，官方明寫 CDC 需要 Standard 或 Enterprise | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/change-data-capture-and-other-sql-server-features | "change data capture requires SQL Server Standard, Enterprise, or SQL Managed Instance editions" |
| CDC-3 | 需要 SQL Server Agent 在執行；Express 沒有 SQL Server Agent | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "both instances of the capture logic require SQL Server Agent to be running for the process to execute" |
| CDC-4 | SQL Server Agent 的 edition 支援：Enterprise、Standard、Web 有，Express 沒有 | https://learn.microsoft.com/en-us/sql/sql-server/editions-and-components-of-sql-server-2022 | "SQL Server Agent \| Yes \| Yes \| Yes \| No \| No" |
| CDC-5 | 對資料庫啟用／停用 CDC 需要 sysadmin | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/enable-and-disable-change-data-capture-sql-server | "The `sysadmin` permissions are required to enable or disable change data capture" |
| CDC-6 | 資料庫啟用後，db_owner 就能對個別資料表建立 capture instance | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/enable-and-disable-change-data-capture-sql-server | "members of the **db\_owner** fixed database role can create a capture instance for individual source tables" |
| CDC-7 | 資料庫裡不能已經有名為 cdc 的 schema 或 user | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/enable-and-disable-change-data-capture-sql-server | "Change data capture requires exclusive use of the **cdc** schema and **cdc** user." |
| CDC-8 | Database Engine 或 Agent 服務帳號是 NETWORK SERVICE 時 CDC 無法正常運作 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "Change data capture can't function properly when the Database Engine service or the SQL Server Agent service is running under the NETWORK SERVICE account." |

## 2. 運作方式

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-9 | 變更來源是 transaction log；capture process 讀 log，把變更寫進對應的 change table | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "The source of change data for change data capture is the SQL Server transaction log." |
| CDC-10 | 每張表啟用後產生一個 capture instance＝一張 change table（`cdc.<schema>_<table>_CT`）＋查詢函式；一張表最多兩個 capture instance | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "The maximum number of capture instances that can be concurrently associated with a single source table is two." |
| CDC-11 | insert／delete 各寫一列；update 寫兩列（更新前、更新後） | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "An update operation requires one-row entry to identify the column values before the update, and a second row entry to identify the column values after the update." |
| CDC-12 | capture 用的是 `sp_replcmds`，和 transactional replication 的 log reader 同一套邏輯 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "The logic for change data capture process is embedded in the stored procedure sp_replcmds" |
| CDC-13 | 預設 capture job 持續執行，每輪最多 1000 筆交易、輪與輪之間等 5 秒 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "processing a maximum of 1000 transactions per scan cycle with a wait of 5 seconds between cycles" |
| CDC-14 | 預設 cleanup job 每天凌晨 2 點跑，保留 4320 分鐘（3 天），每次 delete 最多 5000 列 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "It retains change table entries for 4320 minutes or 3 days" |
| CDC-15 | 同一個資料庫只有一個 cleanup job，所有 capture instance 共用同一個保留期 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/administer-and-monitor-change-data-capture-sql-server | "A single cleanup job handles cleanup for all database change tables and applies the same retention value to all defined capture instances." |
| CDC-16 | 從 commit 到出現在 change table 之間有延遲 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "there's a built-in latency between the time that a change is committed to a source table and the time that the change appears within its associated change table" |
| CDC-17 | 查詢的 LSN 範圍超出 validity interval（已被清掉或還沒 capture）就會失敗或缺資料 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "there could be missing change data due to aggressive cleanup" |

## 3. 成本
分五個面向：儲存、效能、transaction log、維運、高可用與還原。

### 3.1 儲存

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-18 | change table 不定期清理會無限長大，靠 retention cleanup 控制 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "Data that is deposited in change tables grow unmanageably if you don't periodically and systematically prune the data." |
| CDC-19 | 建議把 change table 放在和來源表分開的 filegroup | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/enable-and-disable-change-data-capture-sql-server | "it's recommended that change tables be placed in a filegroup separate from source tables" |
| CDC-20 | 那個 filegroup 滿了，capture 會停（error 1105），視 cleanup 設定可能遺失變更 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/enable-and-disable-change-data-capture-sql-server | "If the filegroup runs out of space, it stops capturing changes until space is available" |
| CDC-21 | 可以只 capture 部分欄位（`@captured_column_list`），官方舉的理由就是隱私或效能 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/enable-and-disable-change-data-capture-sql-server | "If only a subset of columns needs to be tracked, such as for privacy or performance reasons, use the *@captured\_column\_list* parameter" |
| CDC-22 | 〔2008 白皮書〕每列 change data 另外多至少 37 bytes metadata；`cdc.lsn_time_mapping` 也可能長得很大 | https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008/dd266396(v=sql.100) | "the change table contains at least 37 bytes ... of additional data for each row of change data" |

### 3.2 效能

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-23 | 〔2008 白皮書〕CDC 非同步讀 log，對 DML 的影響遠小於 trigger；也不用改應用程式 | https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008/dd266396(v=sql.100) | "Because the log reader job works asynchronously, DML transactions are far less impacted than with synchronous solutions like triggers." |
| CDC-24 | 〔2008 白皮書〕在 I/O 足夠的系統上，ISV 工作負載的執行時間影響低於 10% | https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008/dd266396(v=sql.100) | "change data capture has a very low impact (below 10% change in workload run time) on the application workload" |
| CDC-25 | 〔2008 白皮書〕同一測試中 log 磁碟負擔明顯增加：queue length 變 3 倍、log 寫入量到 250% | https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008/dd266396(v=sql.100) | "the number of log bytes written grew to 250% of normal" |
| CDC-26 | 〔2008 白皮書〕合成測試：INSERT 工作負載吞吐下降 3%–14%，UPDATE 下降 10%–17%；CPU 增加很小 | https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008/dd266396(v=sql.100) | "between 3% and 14% for the INSERT workload and between 10% and 17% for the UPDATE workload" |
| CDC-27 | 〔2008 白皮書〕建議：只 capture 需要的欄位；不需要 net changes 就關掉 | https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008/dd266396(v=sql.100) | "Always limit the list of columns captured by change data capture to only the columns you really need to track" |
| CDC-28 | 〔2008 白皮書〕一張表同時有兩個 capture instance，要寫的變更量加倍，可能明顯影響效能 | https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008/dd266396(v=sql.100) | "having two capture instances active on one table means that twice as much change data needs to be written" |
| CDC-29 | 現行文件：尖峰時段可以先停 capture job、離峰再開，不會遺失變更 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "A reasonable strategy to prevent log scanning from adding load during periods of peak demand is to stop the capture job and restart it when demand is reduced." |
| CDC-30 | 現行文件：吞吐上限＝(maxtrans × maxscans) ÷ polling interval；可用 `sp_cdc_change_job` 調整 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/administer-and-monitor-change-data-capture-sql-server | "(`maxtrans` \* `maxscans`) divided by a nonzero polling interval will put an upper bound on the average number of transactions" |

### 3.3 Transaction log

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-31 | 就算是 simple recovery，CDC 沒把變更收走之前 log 不能截斷；capture 沒跑時 CHECKPOINT 也截不掉 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "even if the recovery mode is set to simple recovery the log truncation point will not advance until all the changes that are marked for capture have been gathered" |
| CDC-32 | 長交易加上 capture 延遲會讓 log 持續長大，`log_reuse_wait_desc` 顯示 `REPLICATION`；到上限後寫入會失敗 | https://learn.microsoft.com/en-us/troubleshoot/sql/database-engine/replication/monitor-long-running-transactions-and-log-growth | "Once the transaction log size reaches the max defined limit, writes to the database fail." |
| CDC-33 | 原因：capture 延遲會擋住 log 截斷，以免遺失變更 | https://learn.microsoft.com/en-us/troubleshoot/sql/database-engine/replication/monitor-long-running-transactions-and-log-growth | "capture job latency holds up log truncation to ensure changes can be captured" |
| CDC-34 | 啟用 CDC 會關掉 ADR 的 aggressive log truncation；SQL Server 2019 不支援 CDC＋ADR 同開，2022 CU18 起才支援 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/known-issues-and-errors-change-data-capture | "When you enable CDC, the aggressive log truncation feature of ADR is disabled." |
| CDC-35 | 〔2008 白皮書〕開 CDC 後，原本 minimally logged 的操作會變成 fully logged；log 檔可能長到原本的 200–300% | https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008/dd266396(v=sql.100) | "the log file size can grow to 200-300% of the original size, in some cases even more" |
| CDC-36 | Fabric Mirroring 文件同樣提醒：長交易會讓 source 的 log 比平常更滿，需要監控 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server | "Long-running transactions might result in the transaction log filling up more than usual." |

### 3.4 維運：schema 變更與監控

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-37 | 加欄位：既有 capture instance 會忽略新欄位（change table 結構固定）；刪欄位：之後填 NULL | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "ignoring any new columns not identified for capture when the source table was enabled" |
| CDC-38 | 要拿到新欄位，就另建第二個 capture instance 平行跑，轉移完再刪舊的 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "it's possible to create a second capture instance for the table that reflects the new column structure" |
| CDC-39 | DDL 變更會記在 `cdc.ddl_history`，可用 `sys.sp_cdc_get_ddl_history` 查 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "The capture process also posts any detected changes to the column structure of tracked tables to the cdc.ddl\_history table." |
| CDC-40 | 改欄位型別或縮小長度可能讓 capture 報錯（2628、8115 等），官方修法是先消化 change table 再停用、重新啟用 CDC | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/known-issues-and-errors-change-data-capture | "you should first consume the change data in the affected change tables. After that, you need to disable and then reenable CDC" |
| CDC-41 | SQL Server 2025 之前，開了 CDC 就不支援 online DDL（ALTER TABLE online）；online index 操作也不支援 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/known-issues-and-errors-change-data-capture | "Online index operations are unsupported when change data capture is enabled on a database." |
| CDC-42 | 監控用兩個 DMV：`sys.dm_cdc_log_scan_sessions`（latency、throughput）與 `sys.dm_cdc_errors` | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/administer-and-monitor-change-data-capture-sql-server | "SQL Server includes two dynamic management views to help you monitor change data capture" |
| CDC-43 | 套 CU／SP 重啟時可能進 Script Upgrade mode 升級 CDC 內部表，耗時或造成大量 log | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/administer-and-monitor-change-data-capture-sql-server | "this step might take some time or cause high transaction log usage for enabled CDC databases" |
| CDC-44 | 不要手動改 CDC metadata（cdc schema、change table、cdc user），否則要停用再重新啟用 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/known-issues-and-errors-change-data-capture | "you shouldn't manually modify any CDC metadata" |

### 3.5 高可用與還原

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-45 | Always On AG 下，failover 後要在新 primary 跑 `sp_cdc_add_job` 建 capture／cleanup job，舊 primary 的 job 要停用 | https://learn.microsoft.com/en-us/sql/database-engine/availability-groups/windows/replicate-track-change-data-capture-always-on-availability | "the stored procedure **sp\_cdc\_add\_job** must be run at the new primary to create the local capture job" |
| CDC-46 | AG 下 CDC 和 log reader 同樣受限：預設要等所有 secondary harden 才處理 log | https://learn.microsoft.com/en-us/sql/database-engine/availability-groups/windows/replicate-track-change-data-capture-always-on-availability | "CDC uses the log reader agent and has the same limitations as described in the Log reader agent modifications section" |
| CDC-47 | 建議在 secondary 上讀 change data，減輕 primary 負擔 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/change-data-capture-and-other-sql-server-features | "change enumeration should be done on the secondary replica to reduce disk load on the primary" |
| CDC-48 | 還原到同一台同名：CDC 保留；還原到別台：預設 CDC 被停用、metadata 刪除，要加 `KEEP_CDC` | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/change-data-capture-and-other-sql-server-features | "If a database is restored to another server, by default change data capture is disabled and all related metadata is deleted." |

## 4. 和 Fabric 的關係

### 4.1 Mirroring

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-49 | Mirroring for SQL Server 2016–2022 用的就是 CDC；2025 改用 change feed | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server | "Mirroring for SQL Server 2016 - 2022 uses the Change Data Capture (CDC) feature." |
| CDC-50 | 自家機房（on-premises）的 SQL Server 支援 Mirroring，透過 on-premises data gateway 連線 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server | "SQL Server instances hosted on on-premises, SQL Server on Azure VM, SQL Server on non-Azure clouds support Fabric Mirroring." |
| CDC-51 | 2016–2022：CDC 會由 Mirroring 自動對每張要鏡像的表啟用；若已啟用就直接沿用 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server-tutorial | "Mirroring uses CDC if it's already enabled for the database and tables to mirror." |
| CDC-52 | 2016–2022：Mirroring 依賴 SQL Server Agent 的 CDC job；Agent 停太久、超過 retention 就會出錯 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server-troubleshoot | "This error occurs if SQL Server Agent is not running, resulting in the changes on the sources exceeding the default retention interval." |
| CDC-53 | 2016–2022：鏡像中的表做 DDL，Mirroring 會失敗，要停用再啟用該表 CDC，之後整表重新 snapshot | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server-limitations | "In SQL Server 2016-2022, when there's a DDL change, mirroring fails" |
| CDC-54 | 2016–2022：沒有 primary key 的表不能鏡像 | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server-limitations | "When mirroring SQL Server 2016-2022, you can't mirror a table if it doesn't have a primary key." |
| CDC-55 | SQL Server 2025：來源資料庫已開 CDC 就不能用 Mirroring（和 2016–2022 相反） | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server-limitations | "You can't mirror a database in a SQL Server 2025 instance if Change Data Capture (CDC) is enabled on the source database." |
| CDC-56 | Mirroring 的產出是把變更 merge 進目標 Delta table（現況副本），不是變更歷史 | https://learn.microsoft.com/en-us/fabric/mirroring/overview | "Fabric immediately merges incoming changes into the target delta table." |
| CDC-57 | 鏡像 Delta 表的舊版本靠 time travel，但預設 retention 只有 1 天（2025 年 6 月中以後建立的） | https://learn.microsoft.com/en-us/fabric/mirroring/overview | "the default retention is one day" |
| CDC-58 | 要在 Fabric 端拿到逐列變更，可開 Delta change data feed（Preview、付費 extended capability），所有 mirroring 來源都適用 | https://learn.microsoft.com/en-us/fabric/mirroring/extended-capabilities-delta-change-data-feed | "Is available for all mirroring sources, including open mirroring partners." |
| CDC-59 | CDF 是付費功能，依實際處理變更的 compute 計費，另外會多 `_change_data` 檔 | https://learn.microsoft.com/en-us/fabric/mirroring/extended-capabilities | "You're billed only for the incremental compute used when CDF processes real changes." |
| CDC-60 | 2016–2022：admin 要 sysadmin 才能設 CDC，之後維護 CDC 也要 sysadmin | https://learn.microsoft.com/en-us/fabric/mirroring/sql-server-limitations | "Any future CDC maintenance requires membership in the sysadmin server role." |

### 4.2 Eventstream

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-61 | Eventstream 的 SQL Server CDC 連接器名稱是「SQL Server on VM DB (CDC)」，列出的支援服務是 Azure VM、Amazon RDS、Google Cloud SQL，沒有列 on-premises | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-source-sql-server-change-data-capture | "Currently, SQL Server on VM DB (CDC) is supported from the following services where the databases can be accessed publicly" |
| CDC-62 | 同頁前提：資料庫要能公開存取；在受保護網路的話，用 Eventstream connector 的 virtual network injection | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-source-sql-server-change-data-capture | "Your SQL Server on VM database must be configured to allow public access." |
| CDC-63 | virtual network injection 指南的支援清單包含「SQL Server on VM CDC」，並說 on-premises 來源要先用 VPN 或 ExpressRoute 接到 Azure VNet（指南是通用說法，沒有點名 on-prem SQL Server） | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/streaming-connector-private-network-support-guide | "For non-Azure source or on-premises scenario, you need to use a **VPN connection** or **Azure ExpressRoute connection**" |
| CDC-64 | 這個連接器同樣需要先在來源資料庫跑 `sys.sp_cdc_enable_db`，等於也是用 SQL Server CDC | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-source-sql-server-change-data-capture | "Enable CDC in your SQL Server on VM database by running the stored procedure `sys.sp_cdc_enable_db`." |
| CDC-65 | 另一條路：Eventstream 的 Mirrored Database Change Feed 連接器（Preview），讀的是鏡像資料庫的 change feed；文件列的型別沒有點名 SQL Server，但寫「支援所有 mirrored database 類型」 | https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/add-source-mirrored-database-change-feed | "This connector supports all mirrored database types available in Fabric Mirroring" |

## 5. CDC 記的時間

| # | 說法 | 出處 URL | 原文短引 |
|---|---|---|---|
| CDC-66 | change table 本身沒有時間欄；`__$start_lsn` 是這筆變更的 commit LSN | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server | "The column \_\_$start\_lsn identifies the commit log sequence number (LSN) that was assigned to the change." |
| CDC-67 | LSN 對時間存在 `cdc.lsn_time_mapping`：`tran_begin_time` 是交易開始時間、`tran_end_time` 是交易結束時間 | https://learn.microsoft.com/en-us/sql/relational-databases/system-tables/cdc-lsn-time-mapping-transact-sql | "This table is used to map between log sequence number (LSN) commit values and the time the transaction committed." |
| CDC-68 | `sys.fn_cdc_map_lsn_to_time` 回傳 `tran_end_time`，官方描述就是「變更 commit 的時間」 | https://learn.microsoft.com/en-us/sql/relational-databases/system-functions/sys-fn-cdc-map-lsn-to-time-transact-sql | "This function can be used to determine the time that a change was committed based upon the **\_\_$start\_lsn** value" |
| CDC-69 | 型別是 `datetime`（不是 `datetimeoffset`），官方頁沒有說明時區 | https://learn.microsoft.com/en-us/sql/relational-databases/system-functions/sys-fn-cdc-map-lsn-to-time-transact-sql | "Return Type **datetime**" |
| CDC-70 | cleanup 也是用 commit time 計算保留期，所以 3 天是「commit 後 3 天」 | https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/administer-and-monitor-change-data-capture-sql-server | "The specified number of minutes is subtracted from the maximum `tran_end_time` value" |

官方只說這是 commit 時間，沒有提到「業務生效日」。所以「commit 時間不等於業務生效日」是我們的推論：如果客服補登、批次調整等級，或等級規則是「次月生效」，commit 時間就會和業務上的生效日不同。

## 6. 白話結論
- **前提不難滿足，但要確認 edition**：Standard 或 Enterprise 才能開，而且 SQL Server Agent 要一直跑。開的人要有 sysadmin（CDC-1、CDC-3、CDC-5）。
- **對寫入效能的影響小**：CDC 是事後非同步讀 log，不是 trigger。官方唯一的量測（2008 年）是工作負載變慢不到 10%，UPDATE 最多慢 17%。會員表變動頻率遠低於訂單，影響應該更小，但這是推論（CDC-24、CDC-26）。
- **真正的風險是 transaction log**：capture job 停了，或有長交易，log 就截不掉、一直長大，最後整個營運 DB 寫入失敗，連訂單也寫不進去。緩解做法：監控 `log_reuse_wait_desc` 和 `sys.dm_cdc_log_scan_sessions` 的 latency，Agent 設成自動啟動，log 磁碟留足空間（CDC-31、CDC-32、CDC-42）。
- **儲存可控**：change table 預設只留 3 天，自動清理。緩解做法：只 capture 會員 ID、等級等需要的欄位，放在獨立的 filegroup（CDC-14、CDC-19、CDC-21）。
- **維運成本主要在 schema 變更**：加欄位不會壞，只是不會被收進來；改型別可能要停用再啟用 CDC。2016–2022 的 Mirroring 只要遇到 DDL 就會失敗，要重開 CDC 並整表重新 snapshot。上游改表時，要先通知資料團隊（CDC-37、CDC-40、CDC-53）。
- **如果已經為 Mirroring 開了 CDC，加開會員表的邊際成本很低**：Mirroring 本來就靠 CDC，會沿用已啟用的 CDC。但 Mirroring 在 Fabric 端只產出「現況」表。要保留變動歷史，有兩條路：開付費的 Delta change data feed（Preview），或在 retention 3 天內自己定期把 change table 抽出來落地（CDC-51、CDC-56、CDC-58、CDC-15）。
- **CDC 的時間是 commit 時間，不是業務生效日**：它能回答「系統什麼時候改了等級」。如果業務規則是次月生效，或者有補登，還是要另外定義生效日（CDC-68）。
- **未查到或不確定**：
  - 現行 learn 文件沒有任何 CDC 效能量化數字，第 3.2 節的數字全部來自 2008 年白皮書。
  - capture job 的預設 maxtrans 有兩個版本：現行文件寫 1000，2008 白皮書寫 500。
  - 2016、2017、2019 的 edition 表沒有逐頁查。
  - 官方沒寫 Mirroring 能不能把 `cdc.*_CT` change table 本身也鏡像到 Fabric。
  - 官方沒寫 Mirroring 會不會改 cleanup retention。
  - 官方沒寫 Delta CDF 的變更資料會保留多久（是否也受 1 天 retention 影響）。
  - Eventstream 的「SQL Server on VM CDC」連接器能不能經 VPN 接 on-prem SQL Server，官方沒有點名，只有通用指南暗示可行。
  - Mirrored Database Change Feed 連接器的型別清單沒有點名 SQL Server。
  - `tran_end_time` 的時區，官方沒寫。
  - 搜過的關鍵字：`SQL Server change data capture performance impact capture job log scan overhead`、`Fabric eventstream "Mirrored Database Change Feed" source SQL Server`；讀過的頁面就是上表列出的 URL。
