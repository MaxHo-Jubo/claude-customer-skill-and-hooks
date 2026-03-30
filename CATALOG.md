# 快速查詢目錄

> 所有自訂 skill、hook、script 的一頁式參考。
> 上次更新：2026-03-29（spec-design v3.1.1、啟用 code-simplifier plugin）

---

## Skills

### 開發流程類

#### `/jira` — Jira Issue 管理（v1.1.0）

- **位置**：`~/.claude/skills/jira/SKILL.md`
- **用法**：`/jira`、`/jira fetch`、`/jira branch {ISSUE_ID}`
- **功能**：
  - 自動從 git branch 名稱識別 Jira issue
  - 抓取 issue 詳情（含 issuelinks，最多追蹤 2 層）
  - 建立開發筆記 `.claude/{ISSUE_ID}.md` 與原始資料 `.claude/{ISSUE_ID}-Jira.md`
  - 管理 branch 建立
- **依賴**：Atlassian MCP、`JIRA_CLOUD_ID`、`JIRA_USERNAME`（設定於 `~/.claude/CLAUDE.md`）
- **連動**：完成 fetch 或 branch 建立後，提示使用者呼叫 `/linus-requirements-analysis`

#### `/linus-requirements-analysis` — Linus Style 需求分析（v1.0.0）

- **位置**：`~/.claude/skills/linus-requirements-analysis/SKILL.md`
- **用法**：`/linus-requirements-analysis`、`/linus-requirements-analysis {需求描述}`
- **功能**：6 步結構化需求審查
  1. 這是真問題嗎？（法規/真實痛點/想像中的問題）
  2. Show me the case（要求具體案例，不憑空分析）
  3. 資料結構先行（先定義 data model）
  4. 有更簡單的方案嗎？（現有功能組合、改設定、最小改動量）
  5. 會破壞什麼？（資料相容性、其他模組影響、向後相容）
  6. 不要過度泛化（先解決眼前案例）
- **輸出**：【核心判斷】→【關鍵洞察】→【資料結構影響】→【方案】→【風險】→【不做的事】
- **Jira 回寫**：分析完成後可選擇將結論寫入 Jira issue comment
- **依賴**：Atlassian MCP（回寫時）

#### `/jira-acceptance` — Jira 需求驗收（v1.0.0）

- **位置**：`~/.claude/skills/jira-acceptance/SKILL.md`
- **用法**：`/jira-acceptance`、`/jira-acceptance {ISSUE_KEY}`
- **功能**：
  - 從 Jira 取得需求描述（summary、description、subtasks、acceptance criteria）
  - 分析 `git diff` 的實際改動
  - 逐條判定：✅ 已實作 / ⚠️ 部分實作 / ❌ 未實作
  - 產出結構化驗收報告
- **依賴**：Atlassian MCP、git repository

#### `/weekly-review` — 每週工作回顧（v1.2.0）

- **位置**：`~/.claude/skills/weekly-review/SKILL.md`
- **用法**：`/weekly-review`、`/weekly-review --days 14`
- **功能**（8 步驟）：
  1. Git 工作摘要（按專案分組）
  2. 觀察記錄回顧（claude-mem timeline/search）
  3. Auto Memory 變動掃描
  4. 週報彙整與模式提取（含 Skill/Subagent/MCP Server 建議；MCP Server 建議判斷依據：ERRORS.jsonl 中跨 skill 的重複 API call pattern、觀察記錄中「每次都要重新查」的模式）
  5. 記憶整理（過期/重複/升級建議，需使用者確認）
  6. Skill 錯誤 Pattern 分析（Subagent A，與 STEP 08 平行）— 執行 `summarize_errors.py`，提取高頻 pattern（≥3 次）
  7. Skill 修補建議（依賴 STEP 06）— 讀取 SKILL.md，產出 before/after 建議，不自動修改
  8. Amendment 成效追蹤（Subagent B，與 STEP 06 平行）— 比對 `AMENDMENTS.md` 修補前後錯誤頻率
- **快捷觸發**：「整理記憶」→ 只執行 STEP 05；「review skill errors」→ 直接執行 STEP 06~08
- **依賴**：git、claude-mem MCP、auto memory、`post_tool_error.py` hook（ERRORS.jsonl）、`summarize_errors.py`

#### `/sync-my-claude-setting` — 同步本機 Claude 設定到 Repo（v1.1.0）

- **位置**：`~/.claude/skills/sync-my-claude-setting/SKILL.md`
- **用法**：`/sync-my-claude-setting`
- **功能**：
  1. Diff — 細緻比對 `~/.claude/` 與 repo 的差異（檔案用 `diff -u`，目錄用 `diff -rq` 再逐一展開）
  2. Copy — 從本機複製到 Repo（檔案用 `cp`，目錄用 `rsync -av --delete` mirror 模式）；CLAUDE.md 複製前以 `sed` 移除 `<conn>` 區段（含個人連線資訊），再儲存為日期後綴版本
  3. Generate Docs — 自動掃描 skills/hooks/scripts/plugins，重新產生 `README.md` 與 `CATALOG.md`
  4. Commit & Push — 根據差異報告產生 commit message 並推送
- **同步清單**：`settings.json`、`mcp-servers.json`、`CLAUDE.md`（日期後綴 `CLAUDE.md.YYYYMMDD`，移除 `<conn>` 區段後儲存，自動清理舊備份）、`skills/`、`hooks/`、`scripts/`、`rules/`、`statusline-command.sh`
- **MCP Server 同步**：支援 MCP Server 設定同步（過濾 env 敏感資料），新增 restore 反向同步模式（從 repo 還原到本機）
- **安全規則**：`CLAUDE.md` 的 `<conn>` 區段包含個人連線資訊（Jira cloud-id、username、專案路徑），同步時強制移除，禁止出現在 repo
- **依賴**：git、rsync、sed
- **注意**：`~/.claude/` 永遠是 source of truth，repo 只是備份與版本追蹤；`settings.local.json` 不同步

#### `/spec-design` — 需求探索到設計 Spec + 實作計畫（v3.1.1）

- **位置**：`~/.claude/skills/spec-design/SKILL.md`
- **用法**：
  - `/spec-design` — 互動式需求探索
  - `/spec-design <需求描述>` — 帶初始需求直接開始
- **流程**：
  - Phase 0: openspec explore 自由探索問題空間（可跳過）
  - Phase 1-4: superpowers:brainstorming 結構化收斂
  - Phase 5: openspec CLI 建立 change，動態取 template 填入 artifact（proposal + specs + design + tasks）
  - Phase 6-7: 4-agent spec review + 迭代修正
  - Phase 8: plan mode 互動式規劃，產出 plan.md
  - Phase 9: 4-agent plan review + 迭代修正
  - Phase 10: 使用者最終確認
- **輸出**：`openspec/changes/<name>/`（含 proposal.md、specs/、design.md、tasks.md、plan.md）
- **依賴**：superpowers plugin（必要）、`@fission-ai/openspec` CLI（必要）
- **不適用於**：讀原始碼產 spec（用 spec-module）、重構既有程式碼、寫測試、bug fix

#### `/plan-and-execute` — 自動執行 openspec plan（v2.0.0）

- **位置**：`~/.claude/skills/plan-and-execute/SKILL.md`
- **用法**：
  - `/plan-and-execute <change-name>` — 指定 openspec change 自動執行
  - `/plan-and-execute` — 無參數時列出有 plan.md 的 change
  - `/plan-and-execute --resume <change-name>` — 從上次中斷處繼續
  - `/plan-and-execute --wave <N> <change-name>` — 只執行指定 Wave
  - `/loop 0 /plan-and-execute --resume <change-name>` — 全自動分批（推薦）
- **功能**：
  - 純自動 executor，讀取 plan.md 逐 Wave 執行 TDD
  - 先寫測試（RED）→ 派 subagent 實作（GREEN）→ review → commit
  - 同步更新 openspec tasks.md checkbox
  - context 不足時自動停止，用 `--resume` 跨 session 繼續
  - 最終調用 `test-module` 和 `spec-to-e2e-test` 做驗證
- **輸出**：完成的程式碼 + `openspec/changes/<name>/report.md`
- **依賴**：superpowers plugin（必要）、`@fission-ai/openspec` CLI（必要）、test-module skill、spec-to-e2e-test skill
- **不適用於**：簡單 bug fix 或單檔修改

---

### 程式碼品質類

#### `/spec-module <path>` — 模組 Spec 產生（v1.0.0）

- **位置**：`~/.claude/skills/spec-module/SKILL.md`
- **用法**：
  - `/spec-module <module-path>` — 快速模式，掃描結構產出概覽 spec
  - `/spec-module <path> --full` — 強制完整掃描，透過 `routes/index.js` 的 `CONTROLLER_ROUTING_MAPPING` 找出所有相關 controller，確保 API 列表 100% 完整
  - `/spec-module <path> --verify` — 驗證已存在 spec 的完整性，比對原始碼找出遺漏並補上
  - `/spec-module <path> --commit` — 完成後自動 commit（可與 `--full` / `--verify` 組合）
- **功能**：
  - 使用 Explore subagent 完整掃描模組
  - 產出結構化 spec：規模、入口架構、檔案一覽、品質觀察
  - 偵測 framework pattern、dead code
  - `--full`：讀取路由映射表，逐一掃描所有相關 controller 的 route 定義，附帶完整性驗證 section
  - `--verify`：三級優先序對應 spec 與原始碼（路由映射表 > Spec 內部標註 > 檔名推斷），找出遺漏 API 並補完，支援批次驗證整個目錄
- **輸出**：`spec/<module-name>/index.md` 或 `spec/<module-name>.md`

#### `/test-module <path>` — 批量測試產生（v2.0.0）

- **位置**：`~/.claude/skills/test-module/SKILL.md`
- **用法**：`/test-module <file-or-dir>`、`/test-module lib/services/session_service.dart`
- **功能**（5 階段）：
  - Phase 1：偵察與撰寫（偵測測試框架、分類函式、AAA pattern、Mock/斷言/邊界原則）
  - Phase 2：平行 Review（4 個 subagent — 覆蓋率 / Mock 正確性 / 斷言精確度 / 邊界案例）
  - Phase 3：迭代修正（🔴=0 且覆蓋率 ≥80% 才算通過）
  - Phase 4：執行驗證（失敗分類：測試寫錯→改測試、程式碼 bug→獨立 commit）
  - Phase 5：最終報告（`test/reports/<模組名>_report.md`）
- **框架無關**：Jest、Vitest、Mocha、flutter_test、pytest、go test 等
- **依賴**：依專案測試框架而定

#### `/spec-to-e2e-test <spec>` — Spec 轉 E2E 測試（v1.2.0）

- **位置**：`~/.claude/skills/spec-to-e2e-test/SKILL.md`
- **用法**：`/spec-to-e2e-test <spec路徑或模組名>`、`--with <其他spec>`、`--scan`
- **功能**（6 階段）：
  - Phase -1：跨模組依賴掃描（首次或批次作業時必做，產出 `DEPENDENCY_MAP.md`）
  - Phase 0：Spec 定位與偵察（讀取 spec、探索 UI 程式碼、產出 Widget/Element Finder 參考表）
  - Phase 1：撰寫測試（CRUD 合併流程、Finder 優先序、斷言強度、穩定性原則）
  - Phase 2：平行 Review（4 個 subagent — Spec 覆蓋率 / 語法正確性 / 測試品質 / 穩定性）
  - Phase 3：迭代修正（🔴=0 才算通過）
  - Phase 4：執行測試（失敗分類處理，spec 是 source of truth）
  - Phase 5：最終報告（`integration_test/reports/<模組名>_report.md`）
- **框架支援**：Flutter integration_test（完整）、React Testing Library / Playwright / Cypress（對照表）
- **依賴**：依專案 E2E 框架而定

#### `/explore-report <dir>` — 探索報告（v1.0.0）

- **位置**：`~/.claude/skills/explore-report/SKILL.md`
- **用法**：`/explore-report <directory>`、`--to-spec`
- **功能**：
  - 探索目錄結構並強制產出結構化報告
  - 報告含：規模、目錄結構、關鍵發現、架構模式、品質觀察
  - `--to-spec`：將探索報告轉換為正式 spec
- **輸出**：`spec/.exploration-log.md`（append 模式）

#### `/method-refactor <method>` — 方法重構（v1.0.0）

- **位置**：`~/.claude/skills/method-refactor/SKILL.md`
- **用法**：`/method-refactor <method-name or file:line>`
- **功能**：7 項順序檢查
  1. 常數掃描（抽取 magic number/string）
  2. 型別常數化（`as const`）
  3. 邏輯扁平化（early return、減少巢狀）
  4. Promise → async/await 轉換
  5. 重複碼提取
  6. 冗餘移除（含 NOTE 註解清理）
  7. 測試驗證（跑 test + lint + tsc）
- **輸出**：每項檢查的 ✅/⏭️/❌ 狀態表

#### `/health` — 設定健康度稽核（v1.5.0）

- **位置**：`~/.claude/skills/health/SKILL.md`
- **用法**：`/health`
- **功能**：六層架構健康度稽核
  - Step 0：評估專案 tier（Simple / Standard / Complex）
  - Step 1：單一 bash 區塊收集所有資料（CLAUDE.md、rules、skills、hooks、MCP、conversation files）
  - Step 2：啟動兩個平行診斷 subagent
    - Agent 1 — Context + Security Audit（context layer、skill security/quality/provenance）
    - Agent 2 — Control + Behavior Audit（hooks、allowedTools、cache hygiene、三層防禦一致性、行為 pattern）
  - Step 3：彙整報告（🔴 Critical / 🟡 Structural / 🟢 Incremental）
- **特性**：`disable-model-invocation: true`（不會被自動觸發，僅手動執行）
- **依賴**：無外部依賴

---

### 文字品質類

#### `/humanizer-zh-tw` — 去除 AI 寫作痕跡

- **位置**：`~/.claude/skills/humanizer-zh-tw/SKILL.md`
- **用法**：`/humanizer-zh-tw`（提供需要人性化處理的文字）
- **功能**：
  - 辨識並修復 AI 生成文字的常見模式：誇大的象徵意義、宣傳性語言、以 -ing 結尾的膚淺分析、模糊的歸因、破折號過度使用、三段式法則、AI 詞彙、否定式排比、過多的連接性短語
  - 5 條核心原則：刪除填充短語、打破公式結構、變化節奏、信任讀者、刪除金句
  - 注入真實個性（有觀點、變化節奏、承認複雜性、適當使用第一人稱、允許混亂）
  - 品質評分系統（直接性/節奏/信任度/真實性/精煉度，滿分 50）
- **來源**：op7418/humanizer-zh 的分支，翻譯自 blader/humanizer，參考 hardikpandya/stop-slop
- **依賴**：無（純文字編輯）

#### `/ai-md` — CLAUDE.md AI-native 轉換（v4.0.0）

- **位置**：`~/.claude/skills/ai-md/SKILL.md`
- **用法**：`/ai-md`、「蒸餾」、「distill my CLAUDE.md」、「rewrite my MD for AI」
- **功能**：
  - 將 human-written CLAUDE.md 轉為 AI-native 結構化格式
  - 經 5 輪、4 模型（GPT-5.3、Gemini 2.5 Pro、Grok-4、Claude Opus 4.6）實戰測試
  - Structured-label 格式使 Codex compliance 從 6/8 提升至 8/8
  - 同樣規則、更少 token、更高精確度
- **依賴**：無

---

#### agent-browser — 瀏覽器自動化

- **位置**：`~/.claude/skills/agent-browser/SKILL.md`
- **功能**：瀏覽器自動化 CLI，支援網頁導航、表單填寫、按鈕點擊、截圖、資料擷取、測試 Web App

---

### GitNexus 知識圖譜類

> 這四個 skill 沒有 slash command，透過 GitNexus API 自動啟用。
> 需要先執行 `npx gitnexus analyze` 建立索引。

#### gitnexus-exploring — 程式碼導航

- **位置**：`~/.claude/skills/gitnexus-exploring/SKILL.md`
- **功能**：用知識圖譜理解不熟悉的 codebase、追蹤執行流程與元件關係
- **API**：`gitnexus_query()`、`gitnexus_context()`

#### gitnexus-debugging — 呼叫鏈除錯

- **位置**：`~/.claude/skills/gitnexus-debugging/SKILL.md`
- **功能**：從錯誤訊息追蹤呼叫鏈，找到 root cause
- **API**：`gitnexus_query()`、`gitnexus_context()`、`gitnexus_cypher()`

#### gitnexus-impact-analysis — 影響分析

- **位置**：`~/.claude/skills/gitnexus-impact-analysis/SKILL.md`
- **功能**：修改前分析 blast radius（d=1 必壞、d=2 可能受影響、d=3 需測試）
- **API**：`gitnexus_impact()`、`gitnexus_detect_changes()`

#### gitnexus-refactoring — 安全重構

- **位置**：`~/.claude/skills/gitnexus-refactoring/SKILL.md`
- **功能**：規劃 rename、extract、split 等重構，用依賴圖確保安全
- **API**：`gitnexus_rename()`、`gitnexus_impact()`、`gitnexus_detect_changes()`

---

## Hooks

### SessionStart

| 腳本 | 用途 |
|------|------|
| `detect-jira-issue.sh` | 從 git branch 名稱偵測 Jira issue 編號，注入 session context |
| `context-mode/sessionstart.mjs` | context-mode 初始化 |

### UserPromptSubmit

| 腳本 | 用途 |
|------|------|
| `skill-activation-hook.cjs` | 分析使用者輸入，檢查是否觸發特定 skill |

### PreToolUse

| Matcher | 腳本 | 用途 |
|---------|------|------|
| `Grep\|Glob\|Bash` | `gitnexus-hook.cjs` | 攔截搜尋操作，用 GitNexus 圖譜提供額外上下文 |
| `Bash\|WebFetch\|Read\|Grep\|Agent\|Task\|ctx_*` | `context-mode/pretooluse.mjs` | context-mode 子代理路由 |

### PostToolUse

| Matcher | 腳本 | 用途 |
|---------|------|------|
| `Write\|Edit` | `spec-section-validator.cjs` | 驗證寫入的 spec 文件區段格式是否正確 |
| `Write\|Edit` | `inventory-drift-detector.cjs` | 偵測 inventory 索引是否需要更新 |
| `Write\|Edit` | `skill-version-check.cjs` | SKILL.md 被編輯時，若 version 未更新則提醒進版號 |
| `Bash` | `post-commit-review.cjs` | git commit 後提醒 Claude 執行 POST-COMMIT-REVIEW 規則（步驟 2 用 /pr-review-toolkit:review-pr） |
| —（catch-all） | `post_tool_error.py` | 所有 tool 失敗時自動記錄 JSONL 到 `~/.claude/.learnings/ERRORS.jsonl` |

> **HOOK-OUTPUT 限制**：PostToolUse 的 stdout 不注入 AI context，Claude 看不到。`systemMessage` JSON 僅顯示給使用者。需靠 CLAUDE.md 規則驅動 Claude 行為 + hook systemMessage 作為使用者端安全網。

> **hook-error-wrapper**：所有 hook（除 `post_tool_error.py` 和 Notification）皆透過 `hook-error-wrapper.sh` 包裝執行，失敗時自動記錄到 `ERRORS.jsonl`。

### PreCompact

| 腳本 | 用途 |
|------|------|
| `pre-compact-snapshot.cjs` | Context 壓縮前提醒存重要決策/糾正到 auto memory |

### Notification

| Matcher | 腳本 | 用途 |
|---------|------|------|
| `*` | (inline printf) | 終端機通知 |

---

## Scripts（輔助工具）

| 腳本 | 用途 |
|------|------|
| `hook-error-wrapper.sh` | 包裝 hook 命令，失敗時記錄到 `ERRORS.jsonl`（所有 hook 的外層 wrapper） |
| `detect-jira-issue.sh` | 從 git branch 解析 Jira issue key |
| `generate-spec-mapping.cjs` | 產生 `spec/file-mapping.json`（源碼↔spec 對照表） |
| `spec-section-validator.cjs` | 驗證 spec 必要區段是否存在 |
| `inventory-drift-detector.cjs` | 偵測 `memory/inventory.md` 與實際 skill/hook 的差異 |
| `skill-activation-hook.cjs` | 分析輸入文字判斷是否要啟動 skill |
| `skill-version-check.cjs` | PostToolUse hook — SKILL.md 被編輯時偵測 version 是否更新，未更新則提醒 |
| `post-commit-review.cjs` | PostToolUse hook — git commit 後提醒 Claude 執行 review 流程（步驟 2 改用 /pr-review-toolkit:review-pr） |
| `pre-compact-snapshot.cjs` | PreCompact hook — 壓縮前提醒存記憶 |
| `summarize_errors.py` | 讀取 `~/.claude/.learnings/ERRORS.jsonl`，按 skill/tool/pattern 分組統計錯誤，支援 `--days N`、`--min-count N` |
| `pr-watcher.sh` | 定期輪詢 GitHub PR，有新/更新的 PR 時發 macOS 通知，點擊觸發 review |
| `review-pr.sh` | 本機手動觸發 PR review，結果貼到 PR comment |
| `sync-obsidian-vault.sh` | 同步 auto memory 目錄到 Obsidian vault（symlink） |
| `add-obsidian-tags.cjs` | 為 auto memory markdown 檔案補上 Obsidian tags |

---

## Agents

| Agent | 模型 | 版本 | 用途 |
|-------|------|------|------|
| pr-reviewer | sonnet | 1.0.0 | Code review agent — 逐條比對 CODE-REVIEW-RULE.md 並產出結構化報告 |

### pr-reviewer — Code Review Agent（v1.0.0）

- **位置**：`~/.claude/agents/pr-reviewer.md`
- **模型**：sonnet
- **工具**：Read、Grep、Glob、Bash、Agent
- **模式**：
  - **Lite（預設）**：單 agent 逐條比對 CODE-REVIEW-RULE.md（17 條規則）+ Haiku 信心評分 → 分類（CRITICAL/MINOR/INFO）+ 品質評分（30 分制）
  - **Full**：指定 PR 時啟用，5 個平行 Sonnet agent（規則合規 / Shallow Bug Scan / Git Blame 歷史 / PR Comments / Code Comments）+ Haiku 信心評分
- **觸發方式**：POST-COMMIT-REVIEW 自動觸發（lite）或手動指定 PR（full）
- **檔案過濾**：排除 `*.md`、`*.json`、`*.yml`、`*.yaml`
- **依賴**：CODE-REVIEW-RULE.md（repo 根目錄或 `~/.claude/`）、gh CLI（full 模式）
- **說明文件**：`agents/README-pr-reviewer.md`（設計文件，非 agent）

---

## Plugins & MCP Servers

> 完整說明見 [`plugins/README.md`](plugins/README.md)

### 啟用的 Plugins（15）

| Plugin | 來源 | 用途 |
|--------|------|------|
| code-review | claude-plugins-official | PR 自動化 code review |
| atlassian | claude-plugins-official | Jira & Confluence 整合 |
| frontend-design | claude-plugins-official | 前端設計輔助 |
| claude-md-management | claude-plugins-official | CLAUDE.md 維護工具 |
| typescript-lsp | claude-plugins-official | TypeScript/JS Language Server |
| gopls-lsp | claude-plugins-official | Go Language Server |
| jdtls-lsp | claude-plugins-official | Java Language Server |
| context7 | claude-plugins-official | 即時查詢函式庫最新文件 |
| claude-mem | thedotmack | 跨 session 持久記憶系統 |
| context-mode | claude-context-mode | 節省 98% context window，沙盒執行 |
| document-skills | anthropic-agent-skills | 文件處理套件（pdf、xlsx、docx、pptx、skill-creator…） |
| superpowers | claude-plugins-official | 進階工作流程（brainstorming、plan、code review…） |
| claude-hud | claude-hud | StatusLine HUD 概念參考（jarrodwatts/claude-hud） |
| pr-review-toolkit | claude-plugins-official | PR Code Review 工具套件（/pr-review-toolkit:review-pr） |

### 停用的 Plugins（2）

| Plugin | 來源 | 理由 |
|--------|------|------|
| github | claude-plugins-official | 用 gh CLI 替代 |
| everything-claude-code | everything-claude-code | hooks 開銷大，有用功能已被其他工具覆蓋 |

### MCP Servers

> 設定檔：[`mcp-servers.json`](mcp-servers.json)

#### 獨立設定的 MCP Servers（1 個）

| Server | 類型 | 用途 |
|--------|------|------|
| pr-watcher | stdio | PR 監控 MCP Server（`npx tsx pr-watcher-MCP/src/server.ts`） |

> **已移除的 MCP Servers（2026-03-27）：**
> 以下 server 從 `mcp-servers.json` 移除，但本機仍有對應工具：
>
> | Server | 移除原因 | 本機現況 |
> |--------|---------|---------|
> | context7 | 改走 plugin 通道（`context7@claude-plugins-official`） | plugin 啟用中，不需獨立 MCP 設定 |
> | gitlab | 不再使用 | — |
> | gitnexus | 改走 PreToolUse hook（`gitnexus-hook.cjs`）呼叫 CLI | npm 全域安裝 `gitnexus@1.2.8`，hook + 4 個 skills 仍在運作 |
>
> 其他電腦同步時無需重新加入這些 MCP Server。

#### Plugins 自動註冊的 MCP Servers

| Server | 來源 Plugin | 用途 |
|--------|------------|------|
| context7 | context7@claude-plugins-official | 取得最新函式庫文件與範例程式碼 |
| context-mode | context-mode@claude-context-mode | 沙盒執行 + FTS5 知識庫 |
| mcp-search | claude-mem@thedotmack | 持久記憶語意搜尋 |
| atlassian | atlassian@claude-plugins-official | Jira/Confluence CRUD |
| typescript-lsp | typescript-lsp@claude-plugins-official | TS/JS 型別檢查與導航 |

---

## StatusLine 自訂狀態列

- **位置**：`~/.claude/statusline-command.sh`
- **來源**：合併自 [sd0xdev/sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow)（佈局）+ [@kamranahmedse/claude-statusline](https://github.com/kamranahmedse/claude-statusline)（rate limits）+ [jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud)（概念參考：transcript 解析）
- **設定**：`~/.claude/settings.json` → `statusLine.command`
- **顯示**：
  - 第一行：目錄 (branch*) │ Model │ ctx:N% │ ⏱ session │ thinking
  - 第二行：session name │ 工具統計（前 5 名×次數）│ agent 數量 │ todo 進度 │ config counts
  - 第三～五行：current / weekly / extra usage 進度條（需 OAuth）
- **快取**：rate limit 60 秒、transcript 3 秒、config 120 秒
- **詳細說明**：[`statusline/README.md`](statusline/README.md)

---

## 持續學習系統

> Homunculus 觀察系統已於 2026-03-13 移除（運行 10 天，0 產出）。
> 改用以下機制：

- **LEARNING 規則**（CLAUDE.md）：被糾正時存 feedback memory、發現偏好時存 user memory
- **PreCompact hook**：context 壓縮前提醒存重要決策
- **`/weekly-review` skill**：每週整理記憶、清理過期資訊、提取模式
- **Obsidian 整合**：symlink vault 瀏覽所有專案的 auto memory

---

## Rules（編碼規則）

> 規則分為 **common**（語言無關）與 **語言特定**（目前有 TypeScript）兩層。語言特定規則繼承 common 並補充框架細節。

### common/

| 規則檔 | 重點規則 |
|--------|---------|
| `coding-style.md` | IMMUTABILITY、FILE-ORG、ERROR-HANDLING、INPUT-VALIDATION、MAGIC-NUMBER、NULL-SAFETY、COMMENT-ACCURACY |
| `security.md` | SECRET-MGMT、LOG-SAFETY、SECURITY-INCIDENT；pre-commit checklist 9 項 |
| `testing.md` | 80% coverage、TDD（RED→GREEN→IMPROVE）、unit/integration/e2e |
| `git-workflow.md` | commit format、PR workflow |
| `performance.md` | model selection（haiku/sonnet/opus）、context window 管理、thinking 設定 |
| `patterns.md` | skeleton project、repository pattern、API response envelope |
| `hooks.md` | hook types（Pre/Post/Stop）、HOOK-OUTPUT（PostToolUse stdout 不注入 AI context）、auto-accept、TodoWrite |
| `agents.md` | agent registry（planner/architect/tdd-guide/code-reviewer…）、parallel execution |

### typescript/

| 規則檔 | 重點規則 |
|--------|---------|
| `coding-style.md` | IMMUTABILITY（spread）、ERROR-HANDLING（async/await）、INPUT-VALIDATION（Zod）、CONSOLE-LOG、REACT（re-render/useEffect cleanup）、REACT-NATIVE（FlatList/StyleSheet.create） |
| `testing.md` | E2E: Playwright |
| `patterns.md` | ApiResponse\<T\>、useDebounce hook、Repository\<T\> |
| `hooks.md` | PostToolUse: prettier/tsc/console-log-warn；Stop: console-log-audit |
| `security.md` | SECRET-MGMT: process.env + startup validation |

---

## 依賴關係圖

```
jira ←── jira-acceptance（取得需求資料）
  │
  ├── linus-requirements-analysis（需求分析，可回寫 Jira comment）
  │
  └── spec-module（--commit flag）
         ↑                ↓
      explore-report    spec-to-e2e-test（從 spec 產出 E2E 測試）
      （--to-spec flag）

gitnexus-hook ──→ gitnexus-exploring
                  gitnexus-debugging
                  gitnexus-impact-analysis
                  gitnexus-refactoring

spec-design ──→ plan-and-execute（openspec change + plan.md → 自動執行）
  spec-design:
    Phase 0: openspec explore（自由探索）
    Phase 1-4: superpowers:brainstorming（結構化收斂）
    Phase 5: openspec CLI → change artifacts（proposal + specs + design + tasks）
    Phase 6-7: 4-agent spec review
    Phase 8-9: plan mode → plan.md → 4-agent plan review
  plan-and-execute:
    讀取 plan.md → TDD 分 Wave 實作（subagent）
    支援 --resume / --wave / /loop 分批執行
    plan-and-execute ──→ test-module + spec-to-e2e-test（最終驗證）

auto memory ──→ weekly-review（整理 + skill 錯誤分析）
               Obsidian vault（瀏覽）

~/.claude/ ──→ sync-my-claude-setting（同步到 repo）

health（獨立稽核，無外部依賴）

post-commit-review hook ──→ CLAUDE.md POST-COMMIT-REVIEW 規則（驅動 Claude）
  STEP 1: /simplify → amend commit（有修改時）
  STEP 2: /pr-review-toolkit:review-pr（不含 simplify 面向）→ 自動修正 80+ issue
  STEP 3: osascript macOS 通知
post_tool_error hook ──→ ERRORS.jsonl ──→ weekly-review STEP 06-08（錯誤分析）

pr-reviewer agent ──→ CODE-REVIEW-RULE.md（規則來源）
  lite: POST-COMMIT-REVIEW 自動觸發
  full: 手動指定 PR → 5 平行 Sonnet agents + Haiku 信心評分
```
