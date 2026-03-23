# Max的 Claude Code 自訂 Skills & Hooks 管理

集中管理本機上所有 Claude Code 自訂 skill、hook 與 script 的索引文件。

## Remote Repositories

| Remote | URL |
|--------|-----|
| origin (GitHub) | https://github.com/MaxHo-Jubo/claude-customer-skill-and-hooks.git |
| gitlab | https://gitlab.webotopia.work/maxhero/claude-customer-skill-and-hooks.git |

## 目錄結構

```
.
├── README.md              # 本文件 — 總覽與快速查詢
├── skills/                # 自訂 skill 原始檔（symlink 或複本）
├── hooks/                 # Hook 腳本
├── scripts/               # 輔助 scripts
├── agents/                # 自訂 agent 定義檔
│   ├── pr-reviewer.md     # Code review agent（lite/full 雙模式）
│   └── README-pr-reviewer.md  # pr-reviewer 設計文件（非 agent）
├── statusline/            # 自訂狀態列腳本
│   ├── statusline-command.sh
│   └── README.md
├── claude-mem-customize-TC/ # claude-mem 繁體中文化客製（修改檔、patch、翻譯對照表）
├── rules/                 # 編碼規則（common + 語言特定）
│   ├── common/            # 語言無關規則
│   └── typescript/        # TypeScript/React/RN 特定規則
├── plugins/               # 插件與 MCP 伺服器索引
│   └── README.md
├── docs/
│   ├── skills.md          # Skills 完整參考手冊
│   ├── hooks.md           # Hooks 完整參考手冊
│   └── scripts.md         # Scripts 完整參考手冊
└── CATALOG.md             # 快速查詢表（一頁看完全部）
```

## 快速查詢

詳細資訊請見 [CATALOG.md](CATALOG.md)。

---

## Skills 一覽（20 個，含 plugin 提供）

### 自訂 Skills（有 slash command）

| Skill | 指令 | 版本 | 用途 |
|-------|------|------|------|
| jira | `/jira` | 1.1.0 | Jira Issue 管理，自動從 branch 識別 issue |
| linus-requirements-analysis | `/linus-requirements-analysis` | 1.0.0 | Linus Style 需求分析，6 步結構化審查 + Jira 回寫 |
| jira-acceptance | `/jira-acceptance` | 1.0.0 | 比對 Jira 需求與 git diff，驗收實作完成度 |
| spec-module | `/spec-module <path>` | 1.0.0 | 探索模組並產出結構化 spec 文件 |
| test-module | `/test-module <path>` | 2.0.0 | 掃描可測試函式，產出單元測試，經 4 輪平行 review 迭代驗證（框架無關） |
| spec-to-e2e-test | `/spec-to-e2e-test <spec>` | 1.2.0 | 從 spec 文件產出 E2E 整合測試，經 4 輪平行 review 迭代驗證 |
| explore-report | `/explore-report <dir>` | 1.0.0 | 探索目錄並強制產出結構化報告 |
| method-refactor | `/method-refactor <method>` | 1.0.0 | 7 項檢查結構化優化重構方法 |
| weekly-review | `/weekly-review` | 1.1.1 | 每週工作回顧、記憶整理，整合 skill 錯誤 pattern 分析與修補建議（8 步） |
| sync-my-claude-setting | `/sync-my-claude-setting` | 1.1.0 | 同步本機 Claude 設定到 Repo |
| humanizer-zh-tw | `/humanizer-zh-tw` | — | 去除文字中的 AI 生成痕跡，使其更自然 |
| ai-md | `/ai-md` | 4.0.0 | 將 CLAUDE.md 轉為 AI-native 結構化格式 |
| health | `/health` | 1.5.0 | 六層架構健康度稽核（CLAUDE.md/rules/skills/hooks/subagents/verifiers） |

### 無 slash command 的 Skills

| Skill | 用途 |
|-------|------|
| gitnexus-exploring | 用 GitNexus 知識圖譜導航不熟悉的程式碼 |
| gitnexus-debugging | 用 GitNexus 追蹤呼叫鏈除錯 |
| gitnexus-impact-analysis | 用 GitNexus 分析修改的影響範圍 |
| gitnexus-refactoring | 用 GitNexus 規劃安全的重構 |
| document-skills | 文件技能（由 plugin 提供） |

## Hooks 一覽

| Hook 類型 | 觸發時機 | Matcher | 腳本 | 用途 |
|-----------|----------|---------|------|------|
| SessionStart | 啟動 session | — | `detect-jira-issue.sh` | 自動偵測 branch 的 Jira issue |
| UserPromptSubmit | 使用者送出訊息 | — | `skill-activation-hook.cjs` | 檢查是否需要啟動 skill |
| PreToolUse | 工具執行前 | Grep\|Glob\|Bash | `gitnexus-hook.cjs` | 用 GitNexus 圖譜豐富搜尋上下文 |
| PostToolUse | 寫入/編輯後 | Write\|Edit | `spec-section-validator.cjs` | 驗證 spec 區段格式 |
| PostToolUse | 寫入/編輯後 | Write\|Edit | `inventory-drift-detector.cjs` | 偵測 inventory 漂移 |
| PostToolUse | 寫入/編輯後 | Write\|Edit | `skill-version-check.cjs` | SKILL.md 被編輯時提醒進版號 |
| PostToolUse | git commit 後 | Bash | `post-commit-review.cjs` | 提醒 Claude 執行 POST-COMMIT-REVIEW 規則（步驟 2 用 /pr-review-toolkit:review-pr） |
| PostToolUse | 所有工具（catch-all） | —（空 matcher） | `post_tool_error.py` | tool 失敗時自動記錄 JSONL 至 `~/.claude/.learnings/ERRORS.jsonl` |
| PreCompact | Context 壓縮前 | — | `pre-compact-snapshot.cjs` | 提醒存重要決策/糾正到 auto memory |
| Notification | 通知 | * | (inline printf) | 終端機通知 |

## Agents 一覽

| Agent | 模型 | 版本 | 用途 |
|-------|------|------|------|
| pr-reviewer | sonnet | 1.0.0 | Code review agent — 逐條比對 CODE-REVIEW-RULE.md 並產出結構化報告。預設 lite 模式（單 agent + Haiku 信心評分），可切換 full 模式（5 平行 agent） |

- **位置**：`~/.claude/agents/pr-reviewer.md`
- **觸發方式**：POST-COMMIT-REVIEW 自動觸發（lite）或手動指定 PR（full）
- **工具**：Read、Grep、Glob、Bash、Agent
- **說明文件**：`agents/README-pr-reviewer.md`（設計文件，非 agent）

## Plugins & MCP Servers

詳見 [`plugins/README.md`](plugins/README.md)。

| 分類 | 數量 | 說明 |
|------|------|------|
| Plugins（啟用） | 14 | code-review、atlassian、frontend-design、claude-md-management、typescript-lsp、gopls-lsp、jdtls-lsp、context7、claude-mem、context-mode、document-skills、superpowers、claude-hud、pr-review-toolkit |
| Plugins（停用） | 3 | code-simplifier、github、everything-claude-code |
| MCP Servers | 3 | context7、gitlab、gitnexus（獨立於 plugins 的 MCP Server 設定） |

## MCP Servers 一覽

### 獨立設定的 MCP Servers（`mcp-servers.json`）

| Server | 類型 | 用途 |
|--------|------|------|
| context7 | stdio | 即時查詢第三方套件文件（`@upstash/context7-mcp`） |
| gitlab | http | GitLab MCP 整合（`gitlab.webotopia.work`） |
| gitnexus | stdio | 程式碼知識圖譜 MCP（`gitnexus mcp`） |

### Plugins 自動註冊的 MCP Servers

| Server | 來源 Plugin | 用途 |
|--------|------------|------|
| context7 | context7@claude-plugins-official | 即時查詢第三方套件文件，避免使用過時 API |
| context-mode | context-mode@claude-context-mode | 沙盒執行 + FTS5 知識庫 |
| mcp-search | claude-mem@thedotmack | 持久記憶語意搜尋 |
| atlassian | atlassian@claude-plugins-official | Jira/Confluence CRUD |
| typescript-lsp | typescript-lsp@claude-plugins-official | TS/JS 型別檢查與導航 |

## Rules（編碼規則）

分為 `common/`（語言無關）與 `typescript/`（TS/React/RN 特定）兩層，語言特定規則繼承 common。

| 層級 | 檔案數 | 涵蓋範圍 |
|------|--------|---------|
| common | 8 | coding-style、security、testing、git-workflow、performance、patterns、hooks、agents |
| typescript | 5 | coding-style（含 REACT/REACT-NATIVE）、testing（Playwright）、patterns、hooks、security |

重點規則：
- **coding-style**: IMMUTABILITY、MAGIC-NUMBER、NULL-SAFETY、COMMENT-ACCURACY
- **security**: SECRET-MGMT、LOG-SAFETY；pre-commit checklist 9 項
- **typescript/coding-style**: REACT（re-render/useEffect cleanup）、REACT-NATIVE（FlatList/StyleSheet.create）
- **hooks**: HOOK-OUTPUT（PostToolUse stdout 不注入 AI context，需靠 CLAUDE.md 規則驅動）

詳見 [CATALOG.md](CATALOG.md) 的 Rules 區段或 [`rules/README.md`](rules/README.md)。

## StatusLine 自訂狀態列

合併自三個開源方案，詳見 [`statusline/README.md`](statusline/README.md)：

| 來源 | 貢獻 |
|------|------|
| [sd0xdev/sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow) | 佈局：目錄、git、model、context%、session、thinking |
| [@kamranahmedse/claude-statusline](https://github.com/kamranahmedse/claude-statusline) | OAuth rate limits 進度條（5h / 7d / extra） |
| [jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud) | 概念參考：transcript 解析（工具統計、agent 狀態、todo 進度、config counts、session name） |

## GitNexus — 程式碼知識圖譜

[GitNexus](https://github.com/abhigyanpatwari/GitNexus)（v1.2.8）是圖譜驅動的程式碼智慧工具，為 AI agent 提供 codebase 的結構化索引與查詢能力。

- **安裝**：`npm install -g gitnexus`
- **建立索引**：在專案目錄執行 `npx gitnexus analyze`，產生 `.gitnexus/` 索引
- **整合方式**：透過 PreToolUse hook（`gitnexus-hook.cjs`）在 Grep/Glob/Bash 執行前自動注入圖譜上下文
- **搭配的 Skills**：

| Skill | 用途 |
|-------|------|
| gitnexus-exploring | 用知識圖譜導航不熟悉的 codebase，追蹤執行流程 |
| gitnexus-debugging | 從錯誤訊息追蹤呼叫鏈，定位 root cause |
| gitnexus-impact-analysis | 修改前分析 blast radius（d=1 必壞 / d=2 可能 / d=3 需測試） |
| gitnexus-refactoring | 用依賴圖規劃安全的 rename、extract、split 重構 |

## claude-mem 繁體中文化

詳見 [`claude-mem-customize-TC/README.md`](claude-mem-customize-TC/README.md)。

claude-mem 插件的 UI 輸出預設英文，此資料夾保存繁體中文化的改動：
- **修改後的完整檔案**（可直接覆蓋 plugin cache）
- **Patch 檔**（基於 10.3.1 版本的 diff）
- **翻譯對照表**（插件更新後 patch 失效時，依此表手動替換）

> 插件更新會覆蓋 cache，翻譯對照表是最可靠的重新套用方式。

## 檔案位置

| 類別 | 路徑 |
|------|------|
| Skills | `~/.claude/skills/` |
| Agents | `~/.claude/agents/` |
| Rules | `~/.claude/rules/`（common + typescript） |
| Hooks 設定 | `~/.claude/settings.json` → `hooks` |
| Hook 腳本 | `~/.claude/hooks/`（含 `gitnexus/gitnexus-hook.cjs`） |
| 輔助 Scripts | `~/.claude/scripts/` |
| StatusLine | `~/.claude/statusline-command.sh` |
| MCP Servers 設定 | `~/.claude/mcp-servers.json`（3 個獨立 server） |
| 持續學習 | CLAUDE.md `LEARNING` 規則 + auto memory + claude-mem |

## 變更紀錄

### 2026-03-23: test-module v2.0.0、新增 spec-to-e2e-test、MCP Servers 同步、agents 同步

**Skills 版本號更新：**
- `test-module` 1.0.0 → 2.0.0（major 升級：框架無關、4 輪平行 review 迭代、結構化報告產出）

**Skills 新增：**
- `spec-to-e2e-test`（v1.2.0）— 從 spec 文件產出 E2E 整合測試，經 4 輪平行 review 迭代驗證。主要支援 Flutter integration_test，對照表涵蓋 React Testing Library、Playwright、Cypress

**MCP Servers 更新：**
- `mcp-servers.json` 從空物件更新為 3 個 server：context7（stdio）、gitlab（http）、gitnexus（stdio）

**Agents 同步：**
- `agents/` 目錄內容與本機同步（pr-reviewer.md、README-pr-reviewer.md）

### 2026-03-20: weekly-review v1.1.1、新增 PR 監控腳本、CLAUDE.md 規則補強

**Skills 版本號更新：**
- `weekly-review` 1.1.0 → 1.1.1（git log 新增 `--author` 篩選，只抓使用者自己的 commit）

**Scripts 新增：**
- `pr-watcher.sh` — 定期輪詢 GitHub PR，有新/更新的 PR 時發 macOS 通知，點擊觸發 review
- `review-pr.sh` — 本機手動觸發 PR review，結果貼到 PR comment

**CLAUDE.md 規則補強：**
- GATE-1 新增 `bugfix-scope`（bugfix 優先最小化改動，不順便重構）
- LEARNING 新增 `fix-root-cause`（問題根因在 skill/規則/設定時，修 skill 本身而非存 feedback memory）

### 2026-03-20: 新增 Agents 區段、pr-reviewer agent、版本號更新

**新增 Agents 區段：**
- README.md 與 CATALOG.md 新增 Agents 區段
- 目錄結構新增 `agents/` 目錄說明
- 檔案位置表新增 Agents 路徑
- 依賴關係圖新增 pr-reviewer agent

**新增 Agent：**
- `pr-reviewer`（v1.0.0）— Code review agent，逐條比對 CODE-REVIEW-RULE.md 產出結構化報告。預設 lite 模式（單 agent + Haiku 信心評分），可切換 full 模式（5 平行 Sonnet agent）

**Skills 版本號更新：**
- `weekly-review` 1.0.0 → 1.1.0
- `sync-my-claude-setting` 1.0.0 → 1.1.0

### 2026-03-19: POST-COMMIT-REVIEW 步驟 2 改用 pr-review-toolkit、skill-version-check hook、jira v1.1.0、AGENT_TEAMS env

**POST-COMMIT-REVIEW 更新（CLAUDE.md）：**
- 步驟 2 改用 `/pr-review-toolkit:review-pr`（不含 simplify 面向），取代舊的 code-review plugin

**新增 Hook：**
- `skill-version-check.cjs`（PostToolUse Write|Edit matcher）— SKILL.md 被編輯時，若內容有改動但 version 行未更新，提醒使用者進版號

**Skills 更新：**
- `jira` 進版 1.1.0 — 路徑解析改用絕對路徑，修正不同工作目錄下的路徑問題

**settings.json 更新：**
- `env` 新增 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`（啟用 Agent Teams 實驗功能）
- `enabledPlugins` 新增 `pr-review-toolkit@claude-plugins-official: true`（啟用 plugin 數量 13→14）
- `effortLevel` 改為 `medium`

**Scripts 更新：**
- `post-commit-review.cjs` 提醒文字更新，說明步驟 2 改用 `/pr-review-toolkit:review-pr`

### 2026-03-17: health audit 精簡、commit-spec 移除、health skill 新增、hooks.md HOOK-OUTPUT、post-commit-review hook 恢復、version 號批量加入

**Skills 變更：**
- 新增 `health` skill（v1.5.0）— 六層架構健康度稽核（CLAUDE.md/rules/skills/hooks/subagents/verifiers），含 project tier 判定、parallel subagent 診斷、security scan
- 移除 `commit-spec` skill — 功能已整合至其他流程
- 各 skill description 精簡化，移除冗長觸發條件描述
- 批量加入 `version` frontmatter 至缺少版本號的 skills

**Hooks 變更：**
- 恢復 `post-commit-review.cjs` 的 PostToolUse Bash matcher hook（搭配 CLAUDE.md POST-COMMIT-REVIEW 規則使用）

**Rules 變更：**
- `rules/common/hooks.md` 新增 HOOK-OUTPUT 規則：明確記錄 PostToolUse stdout 不注入 AI context、systemMessage 僅顯示給使用者的行為限制

**文件更新：**
- README.md 與 CATALOG.md 全面更新以反映最新狀態

### 2026-03-16: 新增 MCP Server 同步功能

- 新增 MCP Server 同步功能，sync skill 支援反向同步 (restore)

### 2026-03-16: sync skill 安全規則、weekly-review MCP Server 建議、CLAUDE.md 歷史清除重建

**skills/sync-my-claude-setting/SKILL.md 更新：**
- STEP 02 改為複製 CLAUDE.md 前先以 `sed '/<conn /,/<\/conn>/d'` 移除 `<conn>` 區段，再儲存日期後綴版本
- 新增安全規則說明：`<conn>` 區段含個人連線資訊（Jira cloud-id、username、專案路徑），禁止出現在 repo

**skills/weekly-review/SKILL.md 更新：**
- STEP 04 模式提取新增 MCP Server 建議的判斷依據說明：基於 ERRORS.jsonl 中跨 skill 的重複 API call pattern，以及觀察記錄中「每次都要重新查」的模式

**CLAUDE.md.20260316 更新：**
- 重新建立（先前用 `git filter-repo` 清除了歷史中包含 `<conn>` 個人資訊的版本）

### 2026-03-16: PostToolUse catch-all hook、skill 錯誤追蹤整合至 weekly-review

**settings.json 更新：**
- 新增 PostToolUse catch-all hook（matcher 為空字串）：`python3 ~/.claude/hooks/post_tool_error.py`
- 所有 tool 失敗自動記錄到 `~/.claude/.learnings/ERRORS.jsonl`（JSONL 格式，含 ts/skill/tool/exit_code/cmd/error/task_hint）

**新增檔案：**
- `hooks/post_tool_error.py` — PostToolUse hook，tool 失敗（exit_code 非 0）時寫入 JSONL 記錄；錯誤截斷 500 字元，從不中斷 Claude Code
- `scripts/summarize_errors.py` — 錯誤摘要報告腳本，讀取 `ERRORS.jsonl`，按 skill/tool/pattern 分組統計，支援 `--days N`、`--min-count N` 參數

**skills/weekly-review/SKILL.md 更新：**
- 整合原 `skill-error-tracker` 功能，新增 STEP 06~08（共 8 步驟）
- STEP 06（Subagent A，與 STEP 08 平行）：執行 `summarize_errors.py`，提取錯誤分佈與高頻 pattern（≥3 次），分類為 missing-dependency / wrong-trigger / broken-instruction / environment-drift
- STEP 07（依賴 STEP 06，可多個 Subagent 平行）：讀取高頻失敗 skill 的 SKILL.md，產出 before/after 修補建議，不自動修改，等使用者確認
- STEP 08（Subagent B，與 STEP 06 平行）：讀取 `~/.claude/.learnings/AMENDMENTS.md`，追蹤修補前後錯誤頻率變化，判定成效（✅ Fixed / ⚠️ Partial / ❌ Reverted）
- 新增快捷觸發：使用者說「review skill errors」→ 直接跳到步驟 6~8

### 2026-03-16: StatusLine 第二行、claude-hud plugin、POST-COMMIT-REVIEW 規則化

**StatusLine 更新：**
- `statusline-command.sh`：新增第二行顯示（透過 transcript 解析）— session name、工具統計（前 5 名×次數）、agent 數量、todo 進度、config counts（CLAUDE.md/rules/hooks 數量）
- 新增三層快取機制：rate limit 60 秒、transcript 3 秒、config 120 秒
- 來源新增 [jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud) 概念參考
- `statusline/README.md`：已更新（加入第二行說明、快取表格、資料來源表）

**Plugins 更新：**
- 新增 `claude-hud@claude-hud` plugin（啟用），啟用 plugin 數量 12→13

**CLAUDE.md 更新：**
- 新增 `POST-COMMIT-REVIEW` rhythm 區段（trigger → skip-when → mandatory 3 步驟：/simplify → code review → macOS 通知）

**settings.json 更新：**
- `permissions.allow` 新增 `Bash(osascript -e 'display notification*)` 避免通知步驟每次詢問
- `hooks` 區段：移除 PostToolUse Bash matcher 的 `post-commit-review.cjs`（改為 CLAUDE.md 規則）

**Scripts 更新：**
- `post-commit-review.cjs`：更新為 systemMessage 提醒模式（hook stdout 無法注入 AI context，改由 CLAUDE.md 規則驅動）

### 2026-03-16: Rules 強化、CODE-REVIEW 量化評分、CLAUDE.md Linus 工程哲學

**Rules 更新：**
- `rules/common/coding-style.md`: 新增 MAGIC-NUMBER（禁止未解釋數字常數）、NULL-SAFETY（空值存取防護）、COMMENT-ACCURACY（註解與邏輯一致）規則；checklist 新增 3 項（no magic numbers、null guarded、comments match logic）
- `rules/common/security.md`: 新增 LOG-SAFETY 規則（禁止 log 印出敏感資料）；checklist 新增 1 項（logs don't contain sensitive data）
- `rules/typescript/coding-style.md`: 新增 REACT（re-render 優化、useEffect cleanup）、REACT-NATIVE（FlatList 強制、StyleSheet.create 靜態樣式）規則

**CLAUDE.md 更新：**
- CODE-REVIEW-OUTPUT: 新增 scoring 30 分量化評分（Magic Number / 邏輯與註解一致性 / 函式註解 / 變數常數註解 / 註解錯字 / 系統穩定性，各 1-5 分）；format 新增【量化評分】欄位
- PERSONA: 新增 show-code、ownership、uncertainty、confidence、cite-source
- CORE-PRINCIPLES: 新增 data-struct-first、no-gratuitous-abstraction，擴充 taste（pointer-to-pointer 範例）、simplicity
- GATE-1: 新增 Show me the case、不要過度泛化
- CODE-REVIEW-OUTPUT: 新增 taste-check、size-check（大 PR 建議本機 review）
- CODE-STYLE: 新增 naming

**新增項目：**
- `linus-requirements-analysis` skill — 6 步結構化需求分析（真假問題→案例→資料結構→簡化→破壞性→不泛化）+ Jira comment 回寫
- `/jira` skill 結尾提示使用者呼叫 `/linus-requirements-analysis`

**更新項目：**
- `sync-my-claude-setting` skill — CLAUDE.md 改用日期後綴備份（`CLAUDE.md.YYYYMMDD`），自動清理舊備份

**已完成的待辦事項（TODO.md 已刪除）：**
- Linus 工程哲學 7 項全部補入 CLAUDE.md
- Linus Style 需求分析做成獨立 skill
- Good Taste 加入 coding rule 和 code review rule
- 對話原則 3 項（不確定就說、信心自評、數據附來源）
- Code Review 大 PR 偵測

### 2026-03-16: post-commit-review 從 hook 改為 CLAUDE.md 規則

**變更原因：**
- PostToolUse hook 的 stdout 無法注入 AI context（設計限制），導致 hook 有觸發、有輸出，但 AI 收不到指令
- 改為寫入 `~/.claude/CLAUDE.md` 的 `POST-COMMIT-REVIEW` 規則，每次都在 AI context 中

**變更內容：**
- `~/.claude/settings.json`：移除 PostToolUse Bash matcher 的 `post-commit-review.cjs` hook
- `~/.claude/CLAUDE.md`：新增 `POST-COMMIT-REVIEW` 規則（trigger → skip-when → mandatory 3 步驟）
- `post-commit-review.cjs`：保留檔案但不再被 hook 引用，僅供參考
- `~/.claude/settings.json`：permissions.allow 新增 `Bash(osascript -e 'display notification*)` 避免通知步驟每次詢問

**同步設定時注意：**
- 新機器需在 `settings.json` 的 `permissions.allow` 加入 `"Bash(osascript -e 'display notification*)"`
- hook 區段不再需要 post-commit-review 的 Bash matcher

### 2026-03-14: 新增 post-commit-review hook、同步 scripts（已被 2026-03-16 取代）

**新增項目（已移除）：**
- `post-commit-review.cjs` hook — git commit 後自動依序執行 /simplify → /code-review
  - /simplify 有變更則 amend commit，無變更跳過
  - /code-review 自動修正 80+ 分 issue（不 commit），列出所有 issue
  - 完成後發終端機通知
  - 例外：命令包含 `push` 時跳過（commit and push 場景）
  - 利用本機 repo 上下文（git blame、完整檔案、目錄 CLAUDE.md）提升 review 精確度

**Scripts 更新：**
- `generate-spec-mapping.cjs` 同步本機版本，新增後端專案支援（`detectProjectType()`）與 blockquote 標頭路徑提取（`extractHeaderPaths()`）

### 2026-03-13: 新增 skills、移除 Homunculus 殘留、scripts 更新

**新增項目：**
- `sync-my-claude-setting` skill — 同步本機 Claude 設定到 Repo
- `humanizer-zh-tw` skill — 去除文字中的 AI 生成痕跡，使其更自然
- Notification hook — 終端機通知（inline printf）

**移除項目：**
- `observe-wrapper.sh`（Homunculus 殘留）

**Scripts 更新：**
- `add-obsidian-tags.cjs` 和 `sync-obsidian-vault.sh` 新增專案映射

**過往移除（參考）：**
- `observe-wrapper.sh` (PreToolUse + PostToolUse hooks) — 每次工具調用前後各跑一次 shell
- `analyze-on-stop.sh` (Stop hook) — session 結束時呼叫 Haiku 分析觀察記錄
- `spec-drift-detector.cjs` (PostToolUse hook) — spec 漂移偵測（已由公司遠端 Mac 每週自動執行並產出 PR）

**替代方案：**
在 CLAUDE.md 新增 `LEARNING` 規則，利用既有的 auto memory（feedback/user type）+ claude-mem 實現跨 session 學習。被糾正時主動存 feedback memory，發現偏好時存 user memory，session 開始時讀取相關記憶。語意層級的學習比工具序列分析有效得多。
