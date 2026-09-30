# cup-build-test Changelog

版本號採 [Semver](https://semver.org/lang/zh-TW/)。MAJOR=破壞既有 cjs / API 行為、MINOR=新增 helper 或階段步驟、PATCH=修 bug 或文件更新。

### v1.3.0 — 2026-07-01（GitNexus 淘汰，改用 codebase-memory-mcp）

**變更**：

- `--with-gitnexus` 旗標更名為 `--with-graph`，階段 0/1 所有 `mcp__gitnexus__*` 工具呼叫改用對應的 `mcp__codebase-memory-mcp__*` 工具：
  - `list_repos` → `list_projects`（project 名由 cwd 絕對路徑推導，見階段 0）
  - `query(goal, query)` → `search_graph(query)`（BM25 全文搜尋）
  - `context(name)` → `trace_path(function_name, direction=both)`（callers+callees 合看）
  - `impact(target, direction)` → `trace_path(function_name, direction=inbound, risk_labels=true)`
  - `cypher(query)` → `query_graph(query)`（Cypher 語法對應改變：`IMPORTS` 是直接 edge type，非 GitNexus 的 `CodeRelation {type: 'IMPORTS'}` 屬性寫法；File 節點路徑欄位是 `file_path`）
- 移除 staleness 檢查（「N 天視為 stale」提醒）：codebase-memory-mcp 有 auto-sync，不像 GitNexus 需手動 `analyze` 才更新
- 新增已知盲區警告：`trace_path` 對「方法當 callback 參照傳遞」（React method 綁定後當 prop 傳出）與 `dispatch(actionCreator(...))` 這類間接呼叫抓不到 caller，callers 空陣列不能當「無人呼叫」的結論，需搭配 grep 補查

**淘汰原因**：2026-07-01 跟 codebase-memory-mcp 實測對照後決議淘汰 GitNexus——luna_web 索引落後 83 天/361 commit（手動索引無 auto-sync）、該次 session GitNexus MCP 連線失敗、且用真實案例（`startCsmsFetchingGuard` callback 參照傳遞）測試發現兩者對間接呼叫有共同盲區、能力打平不是誰更強。詳見 CLAUDE.md TOOL-USAGE:graph-first 與 POST-COMMIT-REVIEW STEP 5。

### v1.2.0 — 2026-05-19（斷言截圖三合一規範，與 jira-test-report v2.4.0 對齊）

**變更**：

- 新增 **階段 3.5 斷言截圖三合一規範**（強制）：每個 step 必須同時具備
  1. 程式邏輯斷言（throw new Error 含實測 vs 預期對比）
  2. 真實頁面操作或視覺變更（DOM 至少一處可截圖識別的變化）
  3. 斷言結論可視化（evidence overlay 注入右上角）
- 純資料比對 step（截圖前後雷同）視為 anti-pattern，強制用 (a) 強制 native 元素展開（如 `<select>.size = N`）/ (b) 逐項真實 UI 互動 / (c) DOM highlight + 標號 之一補回頁面證據
- 引入 `_helpers/evidence.cjs`（與 luna_web/e2e/release-tests/_helpers/ 同步）匯出 `injectEvidence` / `clearEvidence` / `expandSelectAsListbox`，cjs 直接 require 使用
- 提供 5 點 self-check 清單

**設計動機**：LVB-7963 release-e2e 實戰發現 A3.2~A3.4 三步截圖雷同（純對 JS 陣列做 includes / 順序比對），非工程 stakeholder 看 Jira inline comment 與 GitHub Actions artifact 無法判讀斷言依據。三合一規範強制每個斷言 step 都同時驗證程式邏輯與 UI 行為，截圖內可見斷言結論。與 jira-test-report skill v2.4.0 同步，兩條軌道對齊。

### v1.1.0 — 2026-05-14（CUP-179 實戰新增）

**新增**：

- `helpers/modal.cjs` 新增 `ensureCleanState(page, options?)` — mutation step 入口防禦性 cleanup。解決連跑時前 case modal 殘留導致 React/Redux state 不同步，下次 dispatch show 不重 render 的問題（CUP-179 C2.1 / F3 連跑撞牆而抽出）
- `helpers/modal.cjs` 新增 `DEFAULT_APP_MODAL_SEL` — 排除公告 modal 的 `.modal.in`/`.modal.show` 統一 selector
- `helpers/confirmDialog.cjs`（新檔）提供 `confirmYes(page, opts?)` / `confirmNo(page, opts?)` 與 `DEFAULT_YES_BUTTON_TEXTS` / `DEFAULT_NO_BUTTON_TEXTS` — 統一處理「是/否」「確認/取消」二次確認對話 modal，預設 strategy=last 抓 DOM 後出現的最新 modal
- 階段 6 步驟 11：自動產 verification report — 從 `_results.json` 比對 R15 baseline / R18 local / Staging，產出對照表 markdown 寫到 `.claude/CUP-XX-verification-report.md`
- `templates/test-cjs-template.cjs` 加 mutation step 範例（含 `ensureCleanState` + `confirmYes` 用法）
- `helpers/stubs.d.ts` 補 `Locator.last()` 型別定義
- SKILL.md「失敗處理」表新增 2 條（單跑 PASS / 全跑 FAIL、二次確認對話）
- 命名慣例表加 `.claude/CUP-*-verification-report.md`
- 產物 git 政策段加 `.claude/CUP-*-verification-report.md`

**helpers/ 版本**：0.1.0 → 0.2.0

**實戰學到的坑**（驅動本版本演進）：

- 連跑時 case 順序污染（前面 case 留下 modal 殘留導致新 modal 開不起來）
- R18 點儲存後跳「改動此日期...」二次確認對話，cjs 原本沒處理
- 刪除確認對話按鈕是「是/否」非「確認/確定」
- F3 兩 row 生效日恰好相同無法驗 modal remount → 改用整 modal 簽名比對
- R15 ExpandTable sub-tr 與主 row 交錯，`nth(1)` 抓到沒按鈕的 sub-tr

### v1.0.0 — 2026-05-13（CUP-180 實戰固化）

**初版抽出**：

- 6 階段流程定型（commit 反推 → test-plan → cjs → R15 baseline → 修正 → 重產）
- `helpers/` user-level Playwright 架構（取代失敗的 `npx -p playwright@latest` 動態取得）
- `progress.md` cross-session resume 機制 + `--resume` 旗標
- `helpers/modal.cjs` 公告 modal 集中管理（`DEFAULT_ANNOUNCEMENT_SELECTORS` / `dismissAnnouncement` / `waitAndDismissOnEntry`）
- `helpers/step.cjs` 工廠模式（`createStepRunner` 含 ONLY/RESUME_FROM filter + 自動截圖 + progress.md 寫入）
- `helpers/browser.cjs` 多層 Playwright module 解析 fallback
- `helpers/bundle.cjs` R15/R18 bundle 偵測與 assertVariant
- `helpers/report.cjs` _results.json 寫入 + summary 印出
- env var safety guard（如 `ENABLE_TOGGLE_TEST` 不可在正式環境帶）
- Console errors unique pattern 分析（去 React lifecycle warning noise）
- subagent verbosity 限制（階段 1 反推節省 token）
- CASE_ID dynamic ENTRY_PATH 機制
- `mutationStep()` wrapper — VARIANT=r15 自動 SKIP

**首發案例**：CUP-80（手工建檔），CUP-180 (機械化 + helper 抽出來源)
