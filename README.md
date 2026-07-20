# Max的 Claude Code 自訂 Skills & Hooks 管理

集中管理本機上所有 Claude Code 自訂 skill、hook 與 script 的索引文件。

## Remote Repositories

| Remote | URL |
|--------|-----|
| origin (GitHub) | https://github.com/MaxHo-Jubo/claude-customer-skill-and-hooks.git |
| gitlab | https://gitlab.webotopia.work/maxhero/claude-customer-skill-and-hooks.git |

## 前置條件

| 工具 | 安裝方式 | 用途 |
|------|---------|------|
| [Bun](https://bun.sh/) | `curl -fsSL https://bun.sh/install \| bash` | Hook/Script 的 TypeScript runtime（取代 Node.js） |
| `@fission-ai/openspec` | `npm install -g @fission-ai/openspec` | spec-design / plan-and-execute 的 CLI 工具 |

> **Bun 與 Node.js 並存**：Bun 僅用於 Claude Code 的 hook/script（`.ts`），專案本身的 build/dev 仍走 Node.js，兩者互不干擾。

## 目錄結構

```
.
├── README.md              # 本文件 — 總覽與快速查詢
├── skills/                # 自訂 skill 原始檔（symlink 或複本）
├── hooks/                 # Hook 腳本（含 hook-error-wrapper.sh）
├── scripts/               # 輔助 scripts
├── agents/                # 自訂 agent 定義檔
│   ├── pr-reviewer.md     # Code review agent（lite/full 雙模式）
│   ├── multi-repo-commit-scanner.md  # 多 repo 平行 commit 掃描器（weekly-review STEP 01）
│   └── README-pr-reviewer.md  # pr-reviewer 設計文件（非 agent）
├── statusline/            # 自訂狀態列腳本
│   ├── statusline-command.sh
│   └── README.md
├── claude-mem-customize-TC/ # claude-mem 繁體中文化客製（apply-tc.sh 套用腳本、patch、翻譯對照表）
├── harness/               # 開發 Harness 制度檔（6 通用檔隨 sync 同步；harness-diagnosis.md 與 handover-letter.md 為機器專屬檔不同步，現存為 M4 機器快照）
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

## Skills 一覽（26 個自訂 skill）

### 自訂 Skills（有 slash command）

| Skill | 指令 | 版本 | 用途 |
|-------|------|------|------|
| jira | `/jira` | 1.1.0 | Jira Issue 管理，自動從 branch 識別 issue |
| linus-requirements-analysis | `/linus-requirements-analysis` | 1.0.0 | Linus Style 需求分析，6 步結構化審查 + Jira 回寫 |
| jira-acceptance | `/jira-acceptance` | 1.0.0 | 比對 Jira 需求與 git diff，驗收實作完成度 |
| jira-test-report | `/jira-test-report` | 2.5.5 | 對 Jira issue 跑 Playwright E2E 測試，自動截圖 inline 上傳到 issue comment；v2.4.0 落實「斷言截圖三合一規範」；v2.5.x 大規模結構重整：SKILL.md -42%（1415→821 行），抽出 `docs/`（troubleshooting/wiki-markup/comment-template）與 `templates/`（env.local.example/progress.template/skeleton.cjs），新增 `CHANGELOG.md`；v2.5.5 套 AI.MD v4：5 個 prose 重災區轉 structured labels（共 29 個 label blocks），token -220（-1.9%） |
| spec-module | `/spec-module <path>` | 1.0.0 | 探索模組並產出結構化 spec 文件 |
| test-module | `/test-module <path>` | 2.0.0 | 掃描可測試函式，產出單元測試，經 4 輪平行 review 迭代驗證（框架無關） |
| spec-to-e2e-test | `/spec-to-e2e-test <spec>` | 1.2.0 | 從 spec 文件產出 E2E 整合測試，經 4 輪平行 review 迭代驗證 |
| explore-report | `/explore-report <dir>` | 1.1.0 | 探索目錄並強制產出結構化報告 |
| commit-review | `/commit-review [target]` | 1.0.0 | Commit 後分級 review chain 的**執行層**（Tier 0~3）；被動由 `post-commit-review.ts` hook 以 `tier=N target=HEAD` 指派，也可手動對任意 commit（`HEAD~3` / `<hash>`）補跑。判準權威在 `harness/commit-review-policy.md`，強制力由 `commit-gate-guard.ts` 提供 |
| method-refactor | `/method-refactor <method>` | 1.0.0 | 7 項檢查結構化優化重構方法 |
| weekly-review | `/weekly-review` | 1.8.0 | 每週工作回顧、記憶整理，整合 skill 錯誤 pattern 分析與修補建議（8 步）；v1.8.0 STEP 01 改用 `multi-repo-commit-scanner` agent 平行掃描（8 repo / 9 entry，luna_web 用 pathspec 拆 FE/BE） |
| daily-review | `/daily-review` | 1.0.1 | 今日工作回顧（weekly-review 輕量版）；彙整 commit、auto memory 變動、各專案未勾 todo |
| sync-my-claude-setting | `/sync-my-claude-setting` | 1.6.0 | 同步本機 Claude 設定到 Repo（v1.6.0 push 移到 review 之後，六步驟；v1.5.0 修補三個結構性缺陷；v1.4.0 納入 `harness/` 同步並雙向排除機器專屬檔；v1.3.0 排除 `settings.json` 的 `model` 欄位；v1.2.0 新增 source 標註） |
| neat-freak | `/sync` `/neat`、「整理一下」 | — | 跨平台知識庫潔癖級整理（agent memory + CLAUDE.md + docs/ 三層同步），來源：[KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills/tree/main/neat-freak) |
| humanizer-zh-tw | `/humanizer-zh-tw` | — | 去除文字中的 AI 生成痕跡，使其更自然，來源：[op7418/humanizer-zh](https://github.com/op7418/humanizer-zh)（fork 自 blader/humanizer） |
| ai-md | `/ai-md` | 4.0.0 | 將 CLAUDE.md 轉為 AI-native 結構化格式 |
| spec-design | `/spec-design` | 3.2.0 | 從需求到設計 spec + 實作計畫：openspec explore → brainstorming → openspec artifacts → 4-agent review → plan mode → 4-agent plan review |
| plan-and-execute | `/plan-and-execute` | 2.1.0 | 自動執行 openspec plan：讀取 plan.md → TDD 分 Wave 實作 → 驗證。支援 `--resume`/`--wave`/`/loop` 分批執行 |
| upgrade-to-status | `/upgrade-to-status` | 1.1.0 | 將專案升級為 status.md 架構（Milestone / 北極星 / Insight / Current / Next） |
| health | `/health` | 1.5.0 | 六層架構健康度稽核（CLAUDE.md/rules/skills/hooks/subagents/verifiers） |
| claude-max-quota | `/claude-max-quota` | 1.0.0 | 多帳號 Claude Max 額度查詢與管理（cq 查額度、帳號切換建議） |
| save-progress | `/save-progress` | 1.0.0 | 手動存檔工作進度（dump TaskList + session 摘要 + 未存 memory） |
| r15-r18-verify | `/r15-r18-verify` | 1.4.0 | R15→R18 頁面遷移功能等價性驗證，逐層比對 Redux、元件行為、錯誤處理 |
| cup-build-test | `/cup-build-test` | 1.3.0 | CUP 項目從 commit 反推測試項目 → 產雙用途 spec → Playwright 腳本 → 正式環境半自動驗證 → 修正重產（6 階段）；v1.2.0 加入「斷言截圖三合一規範」+ evidence helper（純資料 step 必須補 UI 證據） |
| token-analyze | `/token-analyze [filename] [uuid]` | 1.0.0 | 分析 session token 使用量，產出 markdown 報表（Session 摘要 + Summary + Top 5 + Per-turn） |
| translate-claude-code-releases | `/translate-claude-code-releases [version]` | 1.0.0 | 翻譯 Claude Code GitHub releases 更新內容為繁體中文；帶版本號翻該版起到最新，不帶則從上次記錄版本續翻；`fetch-range.sh` 抓 release 範圍 + sonnet subagent 翻譯，`last-version.txt` 記錄進度 |

> **載入狀態**：`ai-md` / `daily-review` / `humanizer-zh-tw` / `upgrade-to-status` 設為 `user-invocable-only`（不主動推薦，只在使用者輸入 slash command 時觸發）。詳見 [CATALOG.md](CATALOG.md) Skill 載入狀態總覽。

## Hooks 一覽

| Hook 類型 | 觸發時機 | Matcher | 腳本 | 用途 |
|-----------|----------|---------|------|------|
| SessionStart | 啟動 session | — | `detect-jira-issue.sh` | 自動偵測 branch 的 Jira issue |
| UserPromptSubmit | 使用者送出訊息 | — | `skill-activation-hook.ts` | 檢查是否需要啟動 skill |
| PreToolUse | 工具執行前 | Write\|Edit\|MultiEdit | `r15-syntax-guard.ts` | 擋下 luna_web `react_15/` 內 `?.` 與 `??`（babel 6 不支援） |
| PreToolUse | 工具執行前 | Read | `big-read-guard.sh` | 大檔（行數 ≥ 門檻）整檔 Read（無 offset/limit）時 deny 一次，提示改用 smart_outline；同檔每 session 只擋一次 |
| PreToolUse | 工具執行前 | Bash | `commit-gate-guard.ts` | pending-review 閘門：該 repo 有 Tier 2/3 commit 的 review 尚未完成（存在 marker）時，deny 開新 commit；放行 `--amend`/`push`/commit message 含 `[skip-review]`；marker 逾 4 小時自動清除放行 |
| PostToolUse | 寫入/編輯後 | Write\|Edit | `spec-section-validator.ts` | 驗證 spec 區段格式 |
| PostToolUse | 寫入/編輯後 | Write\|Edit | `inventory-drift-detector.ts` | 偵測 inventory 漂移 |
| PostToolUse | 寫入/編輯後 | Write\|Edit | `skill-version-check.ts` | SKILL.md 被編輯時提醒進版號 |
| PostToolUse | git commit 後 | Bash | `post-commit-review.ts` | `git diff --numstat` 機械判定 Tier（0~3，邏輯抽在 `scripts/lib/tier.ts`），Tier 2/3 寫入 pending-review marker 供 `commit-gate-guard.ts` 閘門使用，並以 systemMessage 指派 `commit-review` skill 執行對應 chain（hook 本身不再列舉步驟） |
| PostToolUse | 所有工具（catch-all） | —（空 matcher） | `post_tool_error.py` | tool 失敗時自動記錄 JSONL 至 `~/.claude/.learnings/ERRORS.jsonl` |
| PreCompact | Context 壓縮前 | — | `pre-compact-snapshot.ts` | 提醒存重要決策/糾正到 auto memory + dump TaskList 到 tasks/todo.md |
| SubagentStop | 子 agent 結束 | —（依 `agent_type` 判定） | `subagent-review-clear.ts` | review 類子 agent（`agent_type` 含 review）完成時自動清除該 repo 的 pending-review marker（便利層，手動 `clear-pending-review.ts` 仍為權威解鎖） |
| Notification | 通知 | * | (inline printf) | 終端機通知 |

> **hook-error-wrapper**：所有 hook（除 `post_tool_error.py` 和 Notification）皆透過 `hook-error-wrapper.sh` 包裝執行，失敗時自動記錄到 `ERRORS.jsonl`。

## Agents 一覽

| Agent | 模型 | 版本 | 用途 |
|-------|------|------|------|
| pr-reviewer | sonnet | 1.3.0 | Code review agent — 逐條比對 CODE-REVIEW-RULE.md 並產出結構化報告。預設 lite 模式（單 agent + Haiku 信心評分），可切換 full 模式（5 平行 agent）；v1.3.0 新增「新增檔案例外」（規則 9/10/11 命中全新建立檔案時跳過慣例檢查、直接依規則字面判定）+ 規則 9 擴充涵蓋 React hook 變數與 interface/type 成員；v1.2.0 新增「慣例優先原則」+ full 模式自動 post review 到 GitHub PR |
| multi-repo-commit-scanner | haiku | 1.1.0 | 多 repo 平行 commit 掃描器 — 輸入 repo 清單 + 天數，內部用 Bash 背景作業同時掃 N 個 repo 的 git log，輸出每 repo commits、提取的 Jira IDs 與統計；v1.1.0 支援 `path`/`label`/`pathspec` 物件形式，可將 monorepo 依子目錄拆成多個 bucket（如 luna_web 拆 FE/BE）。用於 weekly-review STEP 01 |

- **pr-reviewer 位置**：`~/.claude/agents/pr-reviewer.md`；觸發：`commit-review` skill 的 Tier 2/3 chain 自動呼叫 (lite) 或手動指定 PR (full)；工具：Read/Grep/Glob/Bash/Agent；v1.2.0 起 full 模式自動 post review 到 GitHub PR（依 CRITICAL 數量決定 REQUEST_CHANGES/COMMENT，不自動 APPROVE）；說明文件：`agents/README-pr-reviewer.md`
- **multi-repo-commit-scanner 位置**：`~/.claude/agents/multi-repo-commit-scanner.md`；觸發：weekly-review STEP 01 自動呼叫；工具：Bash/Read；平行度預設 8；v1.1.0 起 repo 可用物件形式帶 `pathspec` 拆 monorepo 子目錄（橫跨子目錄的 full-stack commit 各 bucket 皆計入，不去重）

## Plugins & MCP Servers

詳見 [`plugins/README.md`](plugins/README.md)。

| 分類 | 數量 | 說明 |
|------|------|------|
| Plugins（啟用） | 13 | code-simplifier、code-review、atlassian、frontend-design、claude-md-management、typescript-lsp、gopls-lsp、jdtls-lsp、context7、claude-hud、pr-review-toolkit、claude-mem、playwright |
| Plugins（停用） | 4 | github、everything-claude-code、document-skills、superpowers |
| MCP Servers | 2 | pr-watcher、codebase-memory-mcp（獨立於 plugins 的 MCP Server 設定） |

## MCP Servers 一覽

### 獨立設定的 MCP Servers（`mcp-servers.json`）

| Server | 類型 | 用途 |
|--------|------|------|
| pr-watcher | stdio | PR 監控 MCP Server（`npx tsx pr-watcher-MCP/src/server.ts`） |
| codebase-memory-mcp | stdio | 程式碼知識圖譜／語意搜尋 MCP Server（取代 GitNexus）；提供 `search_graph`/`search_code`/`trace_path`/`index_repository` 等工具 |

> **已移除的 MCP Servers（2026-03-27）：**
> 以下 server 從 `mcp-servers.json` 移除，但本機仍有對應工具：
>
> | Server | 移除原因 | 本機現況 |
> |--------|---------|---------|
> | context7 | 改走 plugin 通道（`context7@claude-plugins-official`） | plugin 啟用中，不需獨立 MCP 設定 |
> | gitlab | 不再使用 | — |
>
> 其他電腦同步時無需重新加入這些 MCP Server。

### Plugins 自動註冊的 MCP Servers

| Server | 來源 Plugin | 用途 |
|--------|------------|------|
| context7 | context7@claude-plugins-official | 即時查詢第三方套件文件，避免使用過時 API |
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

> **2026-05-20 新增**：Live agent sessions 區塊 — 透過 `claude agents --json`（v2.1.145+）統計同帳號下其他 session 的 busy/idle 數量並顯示於 LINE 3，3 秒快取；舊版 CLI 不存在時安靜略過。

## claude-mem 繁體中文化（11.0.0）

詳見 [`claude-mem-customize-TC/README.md`](claude-mem-customize-TC/README.md)。

claude-mem 插件的 UI 輸出預設英文，此資料夾保存繁體中文化的改動：
- **修改後的完整檔案**（可直接覆蓋 plugin cache + marketplaces 兩個路徑）
- **Patch 檔**（基於 11.0.0 版本的 diff，更新後可能失效）
- **翻譯對照表**（插件更新後 patch 失效時，依此表手動替換）

> 插件更新會覆蓋 cache，翻譯對照表是最可靠的重新套用方式。

### Stop hook 效能注意事項

claude-mem 的 Stop hook（`worker-service.cjs hook claude-code summarize`）在每次 Claude 回覆完後同步執行。已知問題（[thedotmack/claude-mem#1601](https://github.com/thedotmack/claude-mem/issues/1601)）：
- daemon 長時間運行後 Stop hook 會從 ~32s 劣化到 ~2min
- **處置**：重啟 daemon 即可恢復（`kill $(lsof -t -i :37777) && nohup ~/.bun/bin/bun ~/.claude/plugins/marketplaces/thedotmack/plugin/scripts/worker-service.cjs --daemon &>/dev/null &`）
- **套用繁中化時**：需同時覆蓋 `cache/` 和 `marketplaces/` 兩個路徑下的檔案

## 檔案位置

| 類別 | 路徑 |
|------|------|
| Skills | `~/.claude/skills/` |
| Agents | `~/.claude/agents/` |
| Rules | `~/.claude/rules/`（common + typescript） |
| Hooks 設定 | `~/.claude/settings.json` → `hooks` |
| Hook 腳本 | `~/.claude/hooks/`（含 `hook-error-wrapper.sh`） |
| 輔助 Scripts | `~/.claude/scripts/`（`.ts`，由 Bun 執行） |
| StatusLine | `~/.claude/statusline-command.sh` |
| MCP Servers 設定 | `~/.claude/mcp-servers.json`（2 個獨立 server：pr-watcher、codebase-memory-mcp） |
| 持續學習 | CLAUDE.md `LEARNING` 規則 + auto memory + claude-mem |

## Opus 4.7 遷移文件

社群流傳「Opus 4.7 RLHF 已內建紀律，4.6 時代的 CLAUDE.md 規則可以砍」— 經查證部分屬實、部分需保留。三份文件記錄完整驗證與調整建議：

| 文件 | 用途 |
|------|------|
| [docs/opus-4.7-claude-md-migration-verification.md](docs/opus-4.7-claude-md-migration-verification.md) | v1 驗證報告（初步判斷：🔴 不要全信） |
| [docs/opus-4.7-claude-md-migration-verification-v2.md](docs/opus-4.7-claude-md-migration-verification-v2.md) | v2 驗證報告（更深入比對 Anthropic 官方文件，信心 8/10） |
| [docs/opus-4.7-claude-md-adjustments.md](docs/opus-4.7-claude-md-adjustments.md) | 基於 v2 的逐項增/減/留建議（信心 7/10，建議實驗性逐項調整） |

**已套用調整**（記錄於 CLAUDE.md）：
- 移除 `no-sycophancy` 規則（4.7 已 RLHF 內建）
- 精簡 `GATE-1` 為 5 步（移除自問環節）
- tone 改為「直接/犀利/零廢話」（移除字數上限）
- 新增 `SUBAGENT-USAGE`、`TOOL-USAGE` 區段（4.7 預設較少 spawn / call tool，需明確指示）

## 變更紀錄

### 2026-07-20: commit-review skill 抽取 — 執行步驟從 hook/policy 收斂到 skill

- **起因**：Tier 對應的 review chain（eslint → `/simplify` → pr-reviewer → review-pr → blast radius → 通知）同時寫在 `post-commit-review.ts` 的 systemMessage 字串、`harness/commit-review-policy.md` 的表格兩處，改一邊另一邊就過時；且沒有手動補跑管道（marker 逾 4 小時自動清除後 review 就永遠不會跑）
- 新增 `skills/commit-review/`（v1.0.0）：review chain 的**唯一執行層**。被動模式吃 hook 算好的 `tier=N`（不重算，判定單一來源）；手動模式 `/commit-review [target]` 自己算 tier，可對 `HEAD~3` / `<hash>` 補跑
- 新增 `scripts/lib/tier.ts`：Tier 判定邏輯從 `post-commit-review.ts` 抽出成共用模組（Tier 0 副檔名清單、Tier 1/2 行數與檔數門檻、敏感路徑 regex 全部移入）
- 新增 `scripts/compute-tier.ts`：CLI 包裝，供 skill 手動模式呼叫，與 hook 共用同一份 `lib/tier.ts`，確保被動／手動判定不分歧
- `scripts/post-commit-review.ts`：移除本地 `computeTier` 與 6 個常數改 import lib；`buildMessage` 從列舉步驟改為指派 `Skill(commit-review) args: "tier=N target=HEAD"`
- **同 commit 的 review 修掉 4 個既有缺陷**（皆實測復現，非推論）：
  1. **CRITICAL** — `post-commit-review.ts` 的 `repoRoot ? computeTier(repoRoot) : 0`（f256e18 引入）在 repo 解析失敗時降級為 Tier 0，使用者收到「Tier 0 純文件，只需通知，無需 review」這句未經證實的斷言，而 marker 同時因缺 `repoRoot` 寫不進去 → 閘門靜默失效。改為 `number | null`，判定前提不成立時如實回報「Tier 判定失敗、閘門未上鎖」，讓「判不出來」在型別上無法偽裝成任何 Tier
  2. **rename 漏判** — `git diff --numstat` 預設把 rename 併成 `old => new` / `dir/{a => b}/x.ts` 單列，敏感路徑 regex 比對不到。實測「把檔案搬進 `lib/`」被判成 Tier 1；加 `--no-renames` 拆成 delete + add 兩列後正確判 Tier 3
  3. **自家同步產物誤判** — `endsWith('.md')` 對 `CLAUDE.md.20260720` 為 false，sync skill 每次產生的日期後綴備份都被算成「程式碼檔」而虛增 Tier；比對前先剝 `NUMERIC_SUFFIX_REGEX`
  4. **eslint 錯誤分類** — 無 `eslint.config.*` 時（exit 2）報成「❌ eslint 發現問題」，會讓 Claude 去修不存在的 lint 錯誤（本 repo 實測踩到）；改為只有 exit 1 才視為 lint 問題，其餘歸環境問題。順帶修 `changedFiles.join(' ')` 未 quote
- `scripts/compute-tier.ts`：ref 無效時原本 exit 0 並輸出 `TIER=3 FILES=0 LINES=0` 這組自相矛盾的值，skill 會對不存在的 commit 跑完整 chain；改為 `--verify <ref>^{commit}` 驗證後 exit 1，SKILL.md 補「非 0 exit 即停止」
- `harness/commit-review-policy.md`：判定表把「敏感路徑」獨立成先於尺寸判定的一列（原表順序與實作相反，照字面執行會把 `models/user.js` 改 3 行判成 Tier 1）；修正取檔案清單的指令（原寫 `git show --stat`，實作用 `git diff --numstat`）；Tier 0 副檔名補回 `.jpeg`
- `harness/commit-review-policy.md`：Tier 表的「執行步驟」欄收斂為「commit-review skill」，保留分級判準；新增手動補跑說明
- `skills/skill-rules.json`：註冊 commit-review 觸發規則（`enforcement: suggest`、`priority: high`）
- `agents/pr-reviewer.md` v1.2.0 → **v1.3.0**：新增「新增檔案例外」— 規則 9/10/11（變數/hook/interface 註解、函式 JSDoc、STEP 註解）命中本次 diff 全新建立的檔案時，跳過慣例檢查、直接依規則字面判定。起因是實測 `luna_web/frontend/react_18/src` 全庫 STEP 註解採用率僅 4.6%（48/1046 檔），慣例比對會把「大多數舊檔沒寫」誤判為主流而豁免新檔案（ERPD-11971 2026-07-15 首次 commit 即是實例）；規則 9 同時擴充涵蓋 React hook 變數與 interface/type 成員
- `CLAUDE.md` 對應新增 `new-file-comment-rule`，`comments` 條目擴充 hook 變數與 interface 成員
- `settings.json`：移除已停用的 `context-mode@claude-context-mode` plugin 條目（cache 已於 2026-07-17 刪除，釋放 63M）

### 2026-07-16: pending-review 閘門機制 — commit-gate-guard + subagent-review-clear + Tier 機械判定

- **起因**：舊制 `post-commit-review.ts` 只靠 systemMessage 提醒「應執行 review」，無強制力，主 agent 可以無視提醒直接開下一個 commit（ERPD-11970 b4eee29e0e 即如此，Tier 2/3 的 review 被整段跳過）。改為 hook 機械判定 + 硬性 deny 的 fail-closed 閘門，不再依賴自覺
- 新增 `hooks/commit-gate-guard.ts`（PreToolUse `Bash` matcher）：該 repo 有未清的 pending-review marker 時，deny 開新 `git commit`；放行 `--amend`/`push`/commit message 含 `[skip-review]`；marker 逾 4 小時自動清除放行，避免永久 brick
- 新增 `hooks/subagent-review-clear.ts`（SubagentStop hook）：review 類子 agent（`agent_type` 含 review，如 pr-reviewer、pr-review-toolkit:code-reviewer）完成時自動清除該 repo 的 marker（便利層，手動 clear 仍為權威解鎖）
- 新增 `scripts/clear-pending-review.ts`：手動清除 marker、解鎖該 repo 的 commit 閘門（Tier 2/3 review 完成後執行）
- 新增 `scripts/lib/review-marker.ts`：三個 hook/script 共用 lib（marker 路徑推導、`git -C`/`cd` 跨 repo 目標解析、`isGitCommitCommand` 指令偵測）
- `scripts/post-commit-review.ts` 大改：從純 systemMessage 提醒，改為用 `git diff --numstat` 機械判定 Tier（Tier 0 純文件/圖片、Tier 1 ≤50 行且≤2 檔、Tier 2 ≤300 行且≤5 檔、Tier 3 動到敏感路徑 `models/lib/shared` 或超過門檻），Tier 2/3 寫入 pending-review marker
- `harness/commit-review-policy.md` 新增「自動強制機制」段落記錄三個 hook 的協作關係
- `settings.json`：`context-mode@claude-context-mode` 由 `true` 改為 `false`（停用）；移除 serena / context-mode 相關 MCP 工具的 `permissions.allow` 條目（已不再使用）

### 2026-07-03: 本機採用 harness 制度 — CLAUDE.md 路由中心版 + 六檔本機化

- `~/.claude/CLAUDE.md` 重寫為 v2 路由中心版（240 行 → 路由 + 按需讀取；舊版備份 `CLAUDE.md.bak-20260703`），新增 `<priority>` 指令優先權仲裁與 `<harness>` 路由段；`<conn>`、hard-won 規則（no-fallback-after-root-cause、dont-blindly-mirror）、完整 commit-msg 規則保留
- `~/.claude/harness/` 六檔本機化（源自 M4 分支 Fable 5 版）：model-dispatch 新增 §6 本機工具鏈守則（graph-first/upstream-trace/verify-vcs-state/cross-verify，自 TOOL-USAGE 移入）；judgment-matrix 案例換本機實例（claude-mem 中文化三修、isValidLocation fail-open、trace_path 盲區），硬體條款移除；commit-review-policy Tier 2/3 加 blast radius 步驟（取代 POST-COMMIT-REVIEW 強制六步）
- `rules/common/coding-style.md` 新增 hard-won 細則段（write-preserve-comments/global-mutation/extract-shared-helper/STEP 重排）；`rules/common/agents.md` 移除（AGENT-MAP 指向 7 個不存在的 agent，職責由 model-dispatch 接手）；rules 各檔死 agent 引用改指實際資源（Plan / general-purpose / pr-review-toolkit:code-reviewer / security-review skill）
- `sync-my-claude-setting` v1.4.0：`harness/` 納入同步清單，`harness-diagnosis.md` 與 `handover-letter.md` 為機器專屬檔雙向排除（repo 現存兩檔為 M4 快照，維持原樣）
- 驗證：fresh-context read-back agent 6/6 ALL-PASS（引用路徑逐一存在、11 條 hard-won 規則落點確認、conn 完整、無 M4 殘留）

### 2026-07-03: 從 max-m4pro-setting 分支搬回 harness/、apply-tc.sh、translation-mapping 完整結構

- 新增 `harness/` 目錄（8 個制度檔：model-dispatch、judgment-matrix、delegation-templates、commit-review-policy、knowledge-protocol、harness-diagnosis、handover-letter、README）— 源自 M4 Pro 機器分支，Fable 5 建立的工作流制度中心
- 新增 `claude-mem-customize-TC/files/apply-tc.sh` — 中文化一鍵套用腳本（冪等可重跑），函式名已更新為 13.9.3 實測值（worker `fh/ph`、context-generator `H/X`）
- `translation-mapping.md` 採用分支的完整結構（補 v13 新字串：索引標頭說明、Timeline 工具、knowledge-agent 報告、多 session 標題），內嵌 sed 清單改為指向 apply-tc.sh 單一資料來源
- 本機 13.9.3 兩路徑已補套用 v13 新字串與 context-generator Terminal 標籤（早上首輪 patch 用舊對照表，漏了這些）

### 2026-07-03: sync-my-claude-setting v1.3.0 — 排除 settings.json 的 model 欄位

- `settings.json` 的 `model` 欄位改為本機/repo 各自獨立、雙向排除：正向同步（本機 → repo）複製時保留 repo 原本的 `model` 值；反向 restore（repo → 本機）還原時保留本機原本的 `model` 值
- STEP 01/STEP R1 的 diff 比對改用 `jq 'del(.model)'` 排除該欄位，避免每次同步都因為機器/任務彈性切換的 model 設定而產生假差異
- 起因：本機為了不同任務彈性切換 `model`（如 `opus[1m]` ↔ `sonnet`），不該被同步覆蓋或還原

### 2026-07-01: GitNexus 全面淘汰 → codebase-memory-mcp + pr-reviewer v1.2.0

**GitNexus 移除（已決議淘汰）：**
- 刪除 4 個 skill：`gitnexus-exploring`、`gitnexus-debugging`、`gitnexus-impact-analysis`、`gitnexus-refactoring`
- 刪除 `hooks/gitnexus/`（`gitnexus-hook.cjs`、`gitnexus-hook.ts`）
- `settings.json`：移除 PreToolUse `Grep|Glob|Bash` matcher 對應的 gitnexus hook 註冊
- `mcp-servers.json`：移除 `gitnexus` server
- 移除 README/CATALOG 的獨立「GitNexus — 程式碼知識圖譜」說明區段

**新增 `codebase-memory-mcp` MCP Server（取代 GitNexus）：**
- `mcp-servers.json` 新增 stdio server（`/Users/maxhero/.local/bin/codebase-memory-mcp`）
- 提供 `search_graph`/`search_code`/`trace_path`/`index_repository` 等工具，語意搜尋與呼叫鏈分析用途取代 GitNexus
- CLAUDE.md `TOOL-USAGE` 新增 `graph-first` 規則：已索引專案優先用 `search_graph`/`trace_path` 取代 Grep/手動追呼叫鏈；`trace_path` 對「方法當 callback 傳遞」（React method 綁定當 prop、Redux dispatch）會漏，需 grep 交叉驗證
- CLAUDE.md `POST-COMMIT-REVIEW` 步驟 5 改用 `codebase-memory-mcp` 的 `trace_path` 做 blast radius 分析（原為 `/gitnexus-impact-analysis`）

**`agents/pr-reviewer.md` v1.0.0 → v1.2.0：**
- 新增「慣例優先原則」：風格類規則（Magic Number / 變數常數註解 / 函式註解 / STEP 格式 / 部分註解正確性）須先 grep 統計既有慣例（抽樣 3-5 檔）再判定是否標 issue，主流慣例（>50%）一致則不標；安全性、null safety crash、if 大括號、不可變性等非風格類規則不適用此豁免
- Full 模式：從只輸出 terminal 改為自動 post review 到 GitHub PR（依 CRITICAL 數量決定 REQUEST_CHANGES/COMMENT，不自動 APPROVE），同時保留 terminal 結構化輸出供 debug
- `agents/README-pr-reviewer.md` 同步更新

**CLAUDE.md CORE-PRINCIPLES 新增：**
- `dont-blindly-mirror`：鏡像既有結構/需求參數到新情境前，先驗證來源是否本身是壞做法、新情境是否真對等
- `write-preserve-comments`：Write 整檔重寫必須保留原註解，commit 前 grep 比對數量
- `verify-vcs-state`：斷言 PR/commit 已在目標分支前，須驗 origin ancestry

**`skills/cup-build-test/SKILL.md` v1.2.0 → v1.3.0（已修復上述一致性問題）：**
- `--with-gitnexus` 旗標更名 `--with-graph`，階段 0/1 全部 `mcp__gitnexus__*` 呼叫改用對應的 `mcp__codebase-memory-mcp__*` 工具（`list_repos`→`list_projects`、`query`→`search_graph`、`context`→`trace_path(direction=both)`、`impact`→`trace_path(direction=inbound)`、`cypher`→`query_graph`）
- 移除 staleness 檢查（codebase-memory-mcp 有 auto-sync，不需要）
- 新增「callback 參照傳遞 / dispatch 間接呼叫」已知盲區警告，避免對呼叫鏈覆蓋率有錯誤信心

**清理殘留（全機器範圍）：**
- `~/.claude/skills/skill-rules.json`：移除 4 個已刪除 gitnexus skill 的規則條目
- `~/.claude/projects/-Users-maxhero/memory/inventory.md`：移除 PLUGIN-INDEX 與 hook 清單裡的 gitnexus 條目
- 5 個業務 repo（`luna_RN_HomeCareStaff`/`luna_RN_DayCareStaff`/`care_mgt`/`vip_cs_frontend`/`vip_cs_backend`）的 `CLAUDE.md`：內容 100% 為 GitNexus 自動產生，已清空
- 7 個業務 repo 的 `.gitnexus/` 快取目錄、中央索引 `~/.gitnexus`、Cursor 編輯器的 4 個 gitnexus skill 全數刪除

### 2026-05-31: multi-repo-commit-scanner v1.1.0（pathspec 拆分）+ 修正 weekly-review repo 路徑漂移 + 新增 translate skill 文件

**`agents/multi-repo-commit-scanner.md` v1.0.0 → v1.1.0：**
- `scan_one` 新增 `label`/`pathspec` 兩參數；輸入 `repos` 支援物件形式 `{path, label, pathspec}`
- `pathspec` 非空時 `git log` append `-- <pathspec>`，把同一個 monorepo 依子目錄拆成多個 bucket（如 luna_web 的 `frontend/` 與 `backend/`）
- 橫跨多子目錄的 full-stack commit 會同時計入各 bucket（不去重，與既有 `--all` 重複行為一致）

**`skills/weekly-review/SKILL.md` STEP 01 repo 清單修正：**
- 修正 6 個漂移路徑：命名 kebab→snake（`luna-web`→`luna_web`）、erpv3 補回 `Compal/` 中間層、RN 移除多餘內層、luna_web 不再誤當兩個獨立 repo
- luna_web 改用 pathspec 拆 FE/BE 兩 bucket（單一 git repo，列兩條路徑會重複計算）
- 補回遺漏的 `luna_RN_FamilyMember`（家屬App）與新增 `erpv3_web_frontend_sidea`，共 9 entry（8 實體 repo），`parallel` 8→9

**文件：** README/CATALOG 補登 `translate-claude-code-releases` skill（v1.0.0，上 session 新增但未登錄）

### 2026-05-22: weekly-review v1.8.0 + multi-repo-commit-scanner agent

**新 agent：`agents/multi-repo-commit-scanner.md`（v1.0.0，model: haiku）**
- 輸入：repo 清單 + days（選填 author / parallel）
- 內部用 Bash `&` 背景 job + `wait -n` 平行掃多 repo 的 git log，並用 jq 聚合
- 輸出：每 repo commits + 提取的 Jira IDs（regex `\[([A-Z]+-[0-9]+)\]`）+ 按 type 統計
- 故障隔離：任一 repo 失敗寫 `error` 欄位、不中斷其他

**weekly-review v1.7.0 → v1.8.0：**
- STEP 01 改為呼叫 `multi-repo-commit-scanner` agent，由其內部平行 8 repo 同時掃，取代過去主 agent 逐 repo 序列跑 `git log`
- `summary.all_jira_ids` 直餵 STEP 01.5，免再 regex 提取
- Subagent 執行策略圖更新，新增 subagent 一覽表

**CLAUDE.md 新增 3 條規則：**
- `CORE-PRINCIPLES.no-fallback-after-root-cause`：治本同 PR 不再加防護性 fallback（silent fallback 比 crash 更糟）
- `TOOL-USAGE.upstream-trace`：斷言「沒有 X 防線」前先追呼叫鏈上游
- `CODE-STYLE.extract-shared-helper`：同概念判斷出現 2+ 檔案立刻抽 helper

### 2026-05-22: jira-test-report v2.5.5 — AI.MD v4 結構化（剩餘 prose 段落）

**SKILL.md 細部優化（v2.5.5，PATCH）：**
- 5 個 prose 重災區套 AI.MD v4（attention splitting / zero-inference labels / semantic anchoring）：S8.1-S8.5 publish 流程、進度紀錄機制、模式 1 步驟 5、步驟 0.5 進度檔偵測、步驟 6/7 共用後段
- 共 29 個 structured label blocks（v2.4.7 既有 + v2.5.5 新增）
- **行數**：821 → 865（+44，「一規則一行」必然展開）
- **Token**：~11733 → ~11513（**-220，-1.9%**）— 短英文 label + 刪 prose 冗餘抵銷行數增長
- anchor 保護：所有 H3 步驟標題（S3/S3.5/S3.6）與 H4 子標題（S8.1-S8.5）保留，cjs/snippets 跨段引用不受影響

### 2026-05-22: jira-test-report v2.5.4 — SKILL.md 大規模拆分重整

**jira-test-report 結構重整（v2.5.0 ~ v2.5.4）：**
- SKILL.md 1415 → 821 行（**-42% 瘦身**），抽出「字典型」內容到專屬目錄
- 新增 `docs/` 目錄：`troubleshooting.md`（11 symptom 完整診斷）、`wiki-markup.md`（Jira Wiki 語法）、`comment-template.md`
- 新增 `templates/` 目錄：`env.local.example`、`progress.template.md`、`skeleton.cjs`、`snippets/`
- 新增 `CHANGELOG.md`：從 v2.5.0 起維護版本歷程

### 2026-05-22: CLAUDE.md POST-COMMIT-REVIEW 更新 — 因應 v2.1.147 /simplify 改名

**CLAUDE.md 規則更新：**
- POST-COMMIT-REVIEW 步驟 2：`/simplify` 已於 Claude Code v2.1.147 改名為 `/code-review`（僅報告 correctness bug，不再整理程式碼），改用 `code-simplifier:code-simplifier` agent（原行為的直接替代）
- 步驟 4 備註文字更新（移除「不跑 simplify 面向」說明，不再需要）
- on-self-fix trigger 對應更新為 `code-simplifier/review`

### 2026-05-20: statusline live agent sessions + big-read-guard hook + orgGuard helper

**StatusLine 更新：**
- `statusline-command.sh`：LINE 3 新增 Live agent sessions 區塊 — 透過 `claude agents --json`（v2.1.145+）統計同帳號下其他 session 的 busy/idle 數量；busy 用黃色 ⚙、idle 用淡色 ⏸；排除當前 session；3 秒快取（`/tmp/claude/statusline-agents.json`）；舊版 CLI 不存在時安靜略過

**Hooks 新增：**
- `hooks/big-read-guard.sh` — PreToolUse Read matcher：當目標檔行數 ≥ 門檻、且未指定 `offset/limit` 時 deny 一次並提示改用 `smart_outline`；同檔每 session 只擋一次（重送即放行，等於一個減速丘）；fail-open 失敗不阻斷

**Skills helpers 新增：**
- `cup-build-test` / `jira-test-report` 共用 `helpers/orgGuard.cjs` — 機構切換（`switchOrg` / `currentOrg` / `ensureOrg`）；跑特定 case 前切換至非預設機構，跑完於 finally 切回；預設機構為 `compal`（仁寶長照機構）

**Skills 版本號更新：**
- `weekly-review` v1.2.0 → **v1.7.0**：累計多輪內容微調（步驟細化、輸出格式）

### 2026-05-19: 斷言截圖三合一規範 + loginInContext + evidence helper

**Skills 版本號更新：**
- `cup-build-test` v1.1.0 → **v1.2.0**：加入「斷言截圖三合一規範」（每 step 必須同時具備：程式斷言 throw / 真實 UI 操作或視覺變更 / evidence overlay 注入結論）；純資料比對 step 視為 anti-pattern，必須補 UI 證據
- `jira-test-report` v2.2.0 → **v2.4.0**：對齊三合一規範；`.env.local` 完整範例補上 Atlassian API token + 業務 fixture 變數對照

**Helpers 重構：**
- `helpers/login.cjs` 新增 `loginInContext(context, opts)` 主流程 — cookies 直接進 BrowserContext jar，**保留 host-only cookies**（解 luna staging 的 `token` cookie 被 `storageState` 序列化漏帶問題）；舊 `authStateFromApi` 標記 deprecated
- `helpers/browser.cjs` 改接 `loginInContext`：開空 context → 呼叫 login → cookies 進 jar；移除 storageState 中介步驟
- `helpers/evidence.cjs` 新增 — 封裝 `injectEvidence` / `clearEvidence` / `expandSelectAsListbox`，cjs require 即用
- `helpers/env.cjs` / `step.cjs` / `types.d.ts` / `package.json` 跟著對齊；兩個 skill 的 helpers 鏡像同步

**Rules：**
- `rules/typescript/testing.md` 新增 `screenshot-evidence-rule` — 全域強制三合一規範，列出三種 UI 證據展開技巧（`select.size=N` 展開 / 逐一 selectOption / DOM highlight）

### 2026-05-18: Release E2E workflow + 兩個 skill 改 API 登入

**Skills 更新：**
- `cup-build-test` v1.0.0 → **v1.1.0**：階段 4b 移除 Playwright MCP 互動式登入，改用 `.env.local` + `helpers/login.cjs::authStateFromApi`；階段 6 新增步驟 12「publish 到 release-tests」
- `jira-test-report` v2.1.0 → **v2.2.0**：步驟 4 同步改寫；新增步驟 8 publish 到 release-tests；移除 `.playwright-auth/auth.json` 依賴

**Helpers 新增：**
- `helpers/login.cjs` — `authStateFromApi` + `loginParamsFromEnv`（local + CI 統一 API 登入）
- `helpers/browser.cjs::launchBrowser` 改接 `{ login }` 主流程
- `helpers/env.cjs` 加 `login` 物件、`types.d.ts` 加 `LoginParams` type
- `scripts/diagnose-auth.cjs` — 比對 API 登入 vs 手動 storageState 等價性
- `scripts/test-api-login-navigate.cjs` — 驗證 API 登入能進受保護頁、偵測彈窗
- `scripts/sync-helpers.sh` — 加 release-tests/_helpers optional mirror
- `helpers/modal.cjs` v0.2.0 → **v0.3.0**：抽 `runDismissPass` inner helper；`waitAndDismissOnEntry` 加 `retries` / `retryTimeout` 多輪重試（解 LVB-7963 實戰 `.latest-release-rote-modal` r18 mount 比首輪 timeout 晚 + React re-mount 兩種情境）

**業務 repo（luna_web）配套**（此 repo 之外）：
- `e2e/release-tests/` 目錄 + vendor `_helpers/` + README
- `.github/workflows/release-e2e.yml` — workflow_dispatch 觸發、平行跑、pinned issue 報告

### 2026-05-14: 新增 daily-review、jira-test-report skill；更新 skill 與規則

**Skills 新增/更新：**
- 新增 `daily-review` skill（v1.0.1）— 每日工作回顧（weekly-review 輕量版）
- 新增 `jira-test-report` skill（v2.1.0）— Jira issue 跑 Playwright E2E 並 inline 上傳截圖
- `cup-build-test`、`plan-and-execute`、`spec-design`、`spec-module`、`sync-my-claude-setting`、`weekly-review`、`upgrade-to-status` 文字精修

**Settings 變更：**
- `enabledPlugins`：移除 `playwright` 之外的列表整理；新增 `skillOverrides`（`ai-md`/`daily-review`/`humanizer-zh-tw`/`upgrade-to-status` 設為 `user-invocable-only`）
- `PostToolUse` catch-all：`post_tool_error.py` 從 `hook-error-wrapper` 包裝改為直接 `python3` 呼叫

**Rules 與 CLAUDE.md：**
- `rules/common/coding-style.md` 與 `rules/typescript/coding-style.md` 微調（FILE-ORG、COMMENT-ACCURACY 等規則措辭）
- CLAUDE.md PERSONA 新增 `reporting-style`；CORE-PRINCIPLES 將 `no-gratuitous-abstraction` 整併為 `abstraction`，`no-lazy` 改為 `root-cause`；CODE-STYLE 加入 `file-edit-tool` 條目

**Hooks 與 Scripts：**
- 新增 `hooks/gitnexus/gitnexus-hook.cjs`（與 `.ts` 並存）
- `scripts/review-pr.sh`、`scripts/pre-compact-snapshot.ts`、`scripts/spec-section-validator.ts` 更新

### 2026-04-19 (晚): 新增 r15-syntax-guard PreToolUse hook

- 新增 `hooks/r15-syntax-guard.ts`：擋下 luna_web `react_15/` 目錄下 `.js/.jsx/.ts/.tsx` 含 `?.` 或 `??` 的寫入（babel 6 + preset-es2015/stage-0 不支援 ES2020 語法，build 會炸）
- settings.json `PreToolUse` 加入 `Write|Edit|MultiEdit` matcher 註冊此 hook
- 將既有 `feedback_r15_no_optional_chaining.md` 從被動 memory 升級為強制 hook，避免再次寫到 review 階段才被攔截
- 偵測會先剝除字串/註解避免誤判；違規時回傳 `permissionDecision: deny` 並附正確寫法範例

### 2026-04-19: 新增 token-analyze skill、statusline 加入 token 雙排顯示

- 新增 `token-analyze` skill（v1.0.0）：分析 session token 使用量、自動歸納工作摘要、Top 5 燒錢 turn
  - 包含 `scripts/build-report.sh` bundled helper、`evals/evals.json` 5 項測試案例
  - 經 3 組 with-skill agent eval 驗證（標準執行 / 自訂檔名 / 自然語觸發）
- `statusline-command.sh`：新增 `turn` 與 `total` 雙排 token 顯示（in / cache_create / cache_read / 累計成本 $）
  - 利用既有 3s TTL cache 機制避免每次重算
  - cost 顏色分級（綠 <$1 / 黃 $1-3 / 紅 >$3，Opus 4.x 定價）
- 新增 `scripts/sync-memories-to-obsidian.sh`：批次同步多專案 auto memory 到 Obsidian vault
- settings.json：新增 `effortLevel: "xhigh"`
- 新增 `docs/opus-4.7-claude-md-*` 三份遷移驗證/建議文件（v1 報告、v2 報告、調整建議）

### 2026-04-10: 新增 r15-r18-verify skill、gitnexus MCP Server 回歸、settings 更新

- 新增 `r15-r18-verify` skill（R15→R18 頁面遷移功能等價性驗證）
- gitnexus 重新加入 `mcp-servers.json` 作為 MCP Server（`gitnexus mcp`）
- `weekly-review` skill 更新
- settings.json 移除 `model` 欄位、新增 `alwaysThinkingEnabled: false`
- CLAUDE.md 更新：tone 詳述、POST-COMMIT-REVIEW 區段、compact 區段

### 2026-04-05: claude-mem 11.0.0 繁中化、Stop hook 效能記錄

- claude-mem 繁中化 patch 更新至 11.0.0（files/ + patches/）
- 記錄 Stop hook 效能劣化問題與處置方式（[thedotmack/claude-mem#1601](https://github.com/thedotmack/claude-mem/issues/1601)）
- README 新增 Stop hook 效能注意事項區段

### 2026-04-02: Insights Review — 新增 save-progress skill、PreCompact hook 強化

- 新增 `save-progress` skill（手動存檔 TaskList 狀態 / session 摘要 + 未存 memory）
- 更新 `pre-compact-snapshot.ts`：新增提醒 dump TaskList 到 `tasks/todo.md`
- 產出 Insights 繁體中文報告（`report-zh-TW.html`）
- 新增 memory：Atlassian MCP 認證截止日（2026/6/30）、每月 insights 排程

### 2026-04-02: 週回顧同步 — 多帳號管理、CLAUDE.md 更新

- 新增 `claude-max-quota` skill（多帳號額度查詢與管理）
- 新增 `scripts/check-quota.sh`（多帳號額度查詢腳本，Bash + Python 混合架構）
- CLAUDE.md 新增 `featurepath-rule` 與完整路徑 example
- CLAUDE.md 移除 `POST-COMMIT-REVIEW`、`compact` 區段（已移至全域 CLAUDE.md）
- CLAUDE.md 移除 `skill-version`（已由 hook 處理）
- settings.json 新增 `model: "opus[1m]"`
- Hooks 表格更新 `.cjs` → `.ts`（反映 2026-03-30 遷移）

### 2026-03-30: Hook/Script 全面遷移至 TypeScript + Bun

**Scripts 遷移（`.cjs` → `.ts`）：**
- 8 個 scripts 從 CommonJS 轉為 TypeScript ESM：skill-activation-hook、post-commit-review、spec-section-validator、inventory-drift-detector、skill-version-check、pre-compact-snapshot、add-obsidian-tags、generate-spec-mapping
- 1 個 hook 腳本轉換：`hooks/gitnexus/gitnexus-hook.cjs` → `.ts`

**Runtime 切換：**
- settings.json 所有 hook command 從 `node ... .cjs` 改為 `bun ... .ts`
- Bun 原生支援 TypeScript，零編譯、冷啟動更快

**新增前置條件：**
- Bun runtime 安裝（`curl -fsSL https://bun.sh/install | bash`）

### 2026-03-29: spec-design v3.1.1、啟用 code-simplifier plugin

**Skills 版本號更新：**
- `spec-design` 3.1.0 → 3.1.1（patch 修正）

**Plugins 更新：**
- `code-simplifier` 從停用改為啟用

### 2026-03-28: spec-design v3.1.0、plan-and-execute v2.0.0，整合 openspec 工作流

**Skills 版本號更新：**
- `spec-design` 1.2.0 → 3.1.0（major 升級）
- `plan-and-execute` 1.1.0 → 2.0.0（major 升級）

**spec-design 變更：**
- 移除原生流程與雙路徑偵測，superpowers 為必要前提
- 新增 Phase 0：openspec explore 自由探索問題空間（可跳過）
- Phase 5 改用 `@fission-ai/openspec` CLI 建立 change，動態取 template 填入 artifact（取代硬編碼格式）
- 新增 Phase 8-9：plan mode 互動式規劃 + 4-agent plan review
- plan.md 持久化至 `openspec/changes/<name>/plan.md`

**plan-and-execute 變更：**
- 改為純自動 executor，移除互動式規劃與 plan review（已移至 spec-design）
- 輸入源改為 openspec change 目錄的 plan.md
- 新增 `--resume`（跨 session 繼續）、`--wave <N>`（只跑指定 Wave）執行模式
- 支援 `/loop` + `--resume` 全自動分批執行（推薦大功能使用）
- 同步更新 openspec tasks.md checkbox

**本機 MCP Servers 清理：**
- 移除 context7（改走 plugin 通道）、gitlab（不再使用）、gitnexus（改走 PreToolUse hook CLI）

**新增前置條件：**
- `@fission-ai/openspec` CLI 全域安裝（`npm install -g @fission-ai/openspec`）
- 專案需執行 `openspec init --tools claude` 初始化

### 2026-03-27: weekly-review v1.2.0、hook-error-wrapper、MCP Server 路徑修正

**Skills 版本號更新：**
- `weekly-review` 1.1.1 → 1.2.0

**Hooks 更新：**
- 新增 `hook-error-wrapper.sh` — 所有 hook 透過此 wrapper 執行，失敗時自動記錄到 `ERRORS.jsonl`

**MCP Servers 更新：**
- pr-watcher 命令從 `tsx` 改為 `npx tsx`（完整路徑）

### 2026-03-27: 新增 plan-and-execute、spec-design、agent-browser，context-mode hooks，MCP Servers 更新，claude-mem 10.6.2 中文化

**Skills 新增：**
- `plan-and-execute`（v1.1.0）— 從 Spec 到實作完成的結構化流程
- `spec-design`（v1.2.0）— 從需求到設計 spec 的結構化流程
- `agent-browser` — 瀏覽器自動化 CLI（由 plugin 提供）

**Hooks 新增：**
- context-mode SessionStart hook（session 初始化）
- context-mode PreToolUse hook（子代理路由）

**MCP Servers 更新：**
- 移除 context7（改走 plugin 通道）、gitlab、gitnexus（改走 PreToolUse hook CLI）
- 新增 pr-watcher（stdio，`tsx pr-watcher-MCP/src/server.ts`）

**settings.json 更新：**
- `effortLevel` medium → high
- 新增 `autoDreamEnabled: true`

**claude-mem 繁體中文化：**
- 更新至 11.0.0 版本，重新套用翻譯對照表

**statusline 更新：**
- todo 追蹤重寫，支援 TaskCreate/TaskUpdate（除了 TodoWrite）

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
