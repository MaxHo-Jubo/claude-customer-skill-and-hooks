# 快速查詢目錄

> 所有自訂 skill、hook、script 的一頁式參考。

---

## Skills

### 開發流程類

#### `/jira` — Jira Issue 管理

- **位置**：`~/.claude/skills/jira/SKILL.md`
- **用法**：`/jira`、`/jira fetch`、`/jira branch {ISSUE_ID}`
- **功能**：
  - 自動從 git branch 名稱識別 Jira issue
  - 抓取 issue 詳情（含 issuelinks，最多追蹤 2 層）
  - 建立開發筆記 `.claude/{ISSUE_ID}.md` 與原始資料 `.claude/{ISSUE_ID}-Jira.md`
  - 管理 branch 建立
- **依賴**：Atlassian MCP、`JIRA_CLOUD_ID`、`JIRA_USERNAME`（設定於 `~/.claude/CLAUDE.md`）

#### `/jira-acceptance` — Jira 需求驗收

- **位置**：`~/.claude/skills/jira-acceptance/SKILL.md`
- **用法**：`/jira-acceptance`、`/jira-acceptance {ISSUE_KEY}`
- **功能**：
  - 從 Jira 取得需求描述（summary、description、subtasks、acceptance criteria）
  - 分析 `git diff` 的實際改動
  - 逐條判定：✅ 已實作 / ⚠️ 部分實作 / ❌ 未實作
  - 產出結構化驗收報告
- **依賴**：Atlassian MCP、git repository

#### `/commit-spec` — 提交 Spec 文件

- **位置**：`~/.claude/skills/commit-spec/SKILL.md`
- **用法**：`/commit-spec`、`/commit-spec <description>`
- **功能**：
  - 專門 commit `spec/` 目錄的改動
  - 自動分析新增/修改/刪除的 spec 檔案
  - 依 CLAUDE.md 規則產生 commit message（含 Jira 編號、專案標識）
- **依賴**：git、CLAUDE.md commit 規則

---

### 程式碼品質類

#### `/spec-module <path>` — 模組 Spec 產生

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

#### `/test-module <path>` — 批量測試產生

- **位置**：`~/.claude/skills/test-module/SKILL.md`
- **用法**：`/test-module <file-or-dir>`、`--plan-only`、`--phase <N>`
- **功能**：
  - Phase 0：偵察（偵測測試框架、分類函式）
  - Phase 1：撰寫測試（每函式至少 3 個 case：正常/邊界/錯誤）
  - Phase 2：覆蓋率驗證（目標 80%+ branch coverage）
  - Phase 3：提交
- **依賴**：jest / vitest / mocha（依專案而定）

#### `/explore-report <dir>` — 探索報告

- **位置**：`~/.claude/skills/explore-report/SKILL.md`
- **用法**：`/explore-report <directory>`、`--to-spec`
- **功能**：
  - 探索目錄結構並強制產出結構化報告
  - 報告含：規模、目錄結構、關鍵發現、架構模式、品質觀察
  - `--to-spec`：將探索報告轉換為正式 spec
- **輸出**：`spec/.exploration-log.md`（append 模式）

#### `/method-refactor <method>` — 方法重構

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
| `~/.claude/scripts/detect-jira-issue.sh` | 從 git branch 名稱偵測 Jira issue 編號，注入 session context |

### UserPromptSubmit

| 腳本 | 用途 |
|------|------|
| `~/.claude/scripts/skill-activation-hook.cjs` | 分析使用者輸入，檢查是否觸發特定 skill |

### PreToolUse

| Matcher | 腳本 | 用途 |
|---------|------|------|
| `Grep\|Glob\|Bash` | `~/.claude/hooks/gitnexus/gitnexus-hook.cjs` | 攔截搜尋操作，用 GitNexus 圖譜提供額外上下文 |
| `*` | `~/.claude/scripts/observe-wrapper.sh pre` | 持續學習系統 — 記錄工具使用前的觀察 |

### PostToolUse

| Matcher | 腳本 | 用途 |
|---------|------|------|
| `Bash` | `~/.claude/scripts/spec-drift-detector.cjs` | 偵測 git commit 後 spec 與源碼是否有漂移 |
| `Write\|Edit` | `~/.claude/scripts/spec-section-validator.cjs` | 驗證寫入的 spec 文件區段格式是否正確 |
| `Write\|Edit` | `~/.claude/scripts/inventory-drift-detector.cjs` | 偵測 inventory 索引是否需要更新 |
| `*` | `~/.claude/scripts/observe-wrapper.sh post` | 持續學習系統 — 記錄工具使用後的觀察 |

### Stop

| 腳本 | 用途 |
|------|------|
| `~/.claude/homunculus/hooks/analyze-on-stop.sh` | Session 結束時分析所有觀察，透過 Haiku 產生新的學習 instinct |

---

## Scripts（輔助工具）

| 腳本 | 用途 |
|------|------|
| `detect-jira-issue.sh` | 從 git branch 解析 Jira issue key |
| `generate-spec-mapping.cjs` | 產生 `spec/file-mapping.json`（源碼↔spec 對照表） |
| `spec-drift-detector.cjs` | 比對 file-mapping，偵測 spec 漂移 |
| `spec-section-validator.cjs` | 驗證 spec 必要區段是否存在 |
| `inventory-drift-detector.cjs` | 偵測 `memory/inventory.md` 與實際 skill/hook 的差異 |
| `skill-activation-hook.cjs` | 分析輸入文字判斷是否要啟動 skill |
| `observe-wrapper.sh` | 持續學習觀察包裝器（pre/post 模式） |

---

## Plugins & MCP Servers

> 完整說明見 [`plugins/README.md`](plugins/README.md)

### 啟用的 Plugins

| Plugin | 來源 | 用途 |
|--------|------|------|
| code-review | claude-plugins-official | PR 自動化 code review |
| atlassian | claude-plugins-official | Jira & Confluence 整合 |
| claude-md-management | claude-plugins-official | CLAUDE.md 維護工具 |
| typescript-lsp | claude-plugins-official | TypeScript/JS Language Server |
| context7 | claude-plugins-official | 即時查詢函式庫最新文件 |
| everything-claude-code | everything-claude-code | 13 agents + 20 skills + hooks + rules 完整配置集 |
| claude-mem | thedotmack | 跨 session 持久記憶系統 |
| context-mode | claude-context-mode | 節省 98% context window，沙盒執行 |
| example-skills | anthropic-agent-skills | 範例 skills（pdf、xlsx、docx、pptx、skill-creator…） |
| document-skills | anthropic-agent-skills | 文件處理套件 |

### MCP Servers

| Server | 用途 |
|--------|------|
| context7 | 函式庫文件即時查詢 |
| context-mode | 沙盒執行 + FTS5 知識庫 |
| mcp-search | 持久記憶語意搜尋 |
| atlassian | Jira/Confluence CRUD |
| typescript-lsp | TS/JS 型別檢查與導航 |

---

## StatusLine 自訂狀態列

- **位置**：`~/.claude/statusline-command.sh`
- **來源**：合併自 [sd0xdev/sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow)（佈局）+ [@kamranahmedse/claude-statusline](https://github.com/kamranahmedse/claude-statusline)（rate limits）
- **設定**：`~/.claude/settings.json` → `statusLine.command`
- **顯示**：
  - 第一行：目錄 (branch*) │ Model │ ctx:N% │ ⏱ session │ thinking
  - 第二～四行：current / weekly / extra usage 進度條（需 OAuth）
- **詳細說明**：[`statusline/README.md`](statusline/README.md)

---

## 持續學習系統（Homunculus）

- **位置**：`~/.claude/homunculus/`
- **機制**：
  1. 每次工具使用時 `observe-wrapper.sh` 記錄觀察到 `observations.jsonl`
  2. Session 結束時 `analyze-on-stop.sh` 分析觀察
  3. 透過 Haiku 模型歸納出 instinct（行為模式）
  4. Instinct 存於 `~/.claude/homunculus/instincts/`
  5. 高信心 instinct 可透過 `/evolve` 升級為 skill 或 agent

---

## 依賴關係圖

```
jira ←── jira-acceptance（取得需求資料）
  │
  └── commit-spec ←── spec-module（--commit flag）
                         ↑
              explore-report（--to-spec flag）

gitnexus-hook ──→ gitnexus-exploring
                  gitnexus-debugging
                  gitnexus-impact-analysis
                  gitnexus-refactoring

observe-wrapper ──→ homunculus/analyze-on-stop
                    └──→ instincts ──→ /evolve → skills
```
