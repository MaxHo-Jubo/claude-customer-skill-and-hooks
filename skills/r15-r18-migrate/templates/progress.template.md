<!-- 狀態檔：${MIGRATION_STATE_DIR}/<entry>-progress.md；只供 skill resume 使用，不是狀態真值（真值在 queue.json） -->
# <entry> 遷移進度

entry: `<entry>` | branch: `<JIRA-KEY>/refactor/<BRANCH_USER>/<entry>` | attempt: `<n>` | started_at: `<YYYY-MM-DDTHH:MM:SS+08:00>`

> 勾選規則：一個 Phase（Phase 2 為一個步驟）完整做完才勾，做到一半不勾。resume 時從第一個未勾的項目往下做。

## Phase 0 輸入契約

- [ ] 讀到 `queue.json` 的本 entry 與 `limits`
- [ ] 必要欄位齊全（`r15_paths` / `r18_dir` / `route` / `feature_flag.key` / `shared_deps` / `jira` / `branch`）
- [ ] 檔數與總行數在 `limits` 內
- [ ] git 狀態檢查通過（分支相符、髒檔全在本 entry 路徑內）

## Phase 1 合約抽取

- [ ] 分群完成（元件檔 / action+reducer 檔 / 第三方 API 掃描，每群 ≤ 4 檔）
- [ ] subagent 平行回收完畢，四張表齊全且每列都有 `路徑:行號`
- [ ] 主流程核對 action 對應（URL / method / data 形狀逐一比對）
- [ ] 主流程核對 success 副作用（reducer 表每個 SUCCESS 分支的欄位變化都在表內）
- [ ] 產出 `<entry>-contract.md`

## Phase 2 遷移實作

- [ ] 步驟 1 Redux 層（action / entity / saga / reducer，命名沿用 R15、機制照 R18 樣板）
- [ ] 步驟 2 元件層（複製到 `r18_dir` 並套第三方 API 對照，不轉 hooks、不改名、不重構）
- [ ] 步驟 3 路由與開關（`featureControlledRoutes` / `companyDefault.js` 三處 / R18 route guard / 子頁 tab / sidebar）
- [ ] 步驟 4 註解與命名（原註解逐字照搬；所有新增或修改的檔補 `Modified` 一行）
- [ ] 步驟 5 建置（watcher 檢查 → vite build → eslint 只跑變更檔只修 error）
- [ ] 步驟 6 無對照項目盤點（對照表查無且 R18 無先例者已標進合約表 ⚠，無殘留未決項）

## Phase 3 等價性驗證

- [ ] (a) 差異測試已產生並執行（結果已記錄，含失敗與預期不同的列）
- [ ] (b) 靜態比對逐條標記（含三個 MUST-CHECK 與 feature flag 三層一致性）
- [ ] (c) 合約表回填 `R18 對應` 與 `等價 ✅/⚠️/❌`
- [ ] (d) 頁面 E2E 已執行，或已列入 `unverified_items`

## Phase 4 收尾

- [ ] 逐行讀 diff（無測試殘留、無敏感內容、無非本 entry 範圍的改動）
- [ ] `git add` 僅限本 entry 路徑與允許的共用註冊檔
- [ ] commit 完成（hash: `<commit>`）
- [ ] 產出 `<entry>-report.md`
- [ ] 輸出結構化結果 JSON 與 `STATUS:` fallback 行

## 失敗紀錄

<!-- blocked／error 時追加一列，與結構化輸出的 failed_at 一致；resume 不讀本段，只給人與 runner diagnose 看 -->

| attempt | 階段（Phase／步驟） | blocked_reason | 原因（一句） | 相關檔 |
|---|---|---|---|---|
