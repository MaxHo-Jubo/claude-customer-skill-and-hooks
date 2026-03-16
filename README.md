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
├── statusline/            # 自訂狀態列腳本
│   ├── statusline-command.sh
│   └── README.md
├── claude-mem-customize-TC/ # claude-mem 繁體中文化客製（修改檔、patch、翻譯對照表）
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

## Skills 一覽（17 個）

### 自訂 Skills（有 slash command）

| Skill | 指令 | 用途 |
|-------|------|------|
| jira | `/jira` | Jira Issue 管理，自動從 branch 識別 issue |
| linus-requirements-analysis | `/linus-requirements-analysis` | Linus Style 需求分析，6 步結構化審查 + Jira 回寫 |
| jira-acceptance | `/jira-acceptance` | 比對 Jira 需求與 git diff，驗收實作完成度 |
| commit-spec | `/commit-spec` | 快速 commit spec/ 目錄改動 |
| spec-module | `/spec-module <path>` | 探索模組並產出結構化 spec 文件 |
| test-module | `/test-module <path>` | 掃描可測試函式，產出單元測試 |
| explore-report | `/explore-report <dir>` | 探索目錄並強制產出結構化報告 |
| method-refactor | `/method-refactor <method>` | 7 項檢查結構化優化重構方法 |
| weekly-review | `/weekly-review` | 每週工作回顧與記憶整理 |
| sync-my-claude-setting | `/sync-my-claude-setting` | 同步本機 Claude 設定到 Repo |
| humanizer-zh-tw | `/humanizer-zh-tw` | 去除文字中的 AI 生成痕跡，使其更自然 |
| ai-md | `/ai-md` | 將 CLAUDE.md 轉為 AI-native 結構化格式 |

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
| PostToolUse | git commit 後 | Bash | `post-commit-review.cjs` | 自動執行 /simplify + /code-review（利用本機 repo 上下文） |
| PreCompact | Context 壓縮前 | — | `pre-compact-snapshot.cjs` | 提醒存重要決策/糾正到 auto memory |
| Notification | 通知 | * | (inline printf) | 終端機通知 |

## Plugins & MCP Servers

詳見 [`plugins/README.md`](plugins/README.md)。

| 分類 | 數量 | 說明 |
|------|------|------|
| Plugins（啟用） | 12 | code-review、atlassian、frontend-design、claude-md-management、typescript-lsp、gopls-lsp、jdtls-lsp、context7、claude-mem、context-mode、document-skills、superpowers |
| Plugins（停用） | 3 | code-simplifier、github、everything-claude-code |
| MCP Servers | 5 | context7、context-mode、mcp-search、atlassian、typescript-lsp |

## StatusLine 自訂狀態列

合併自兩個開源方案，詳見 [`statusline/README.md`](statusline/README.md)：

| 來源 | 貢獻 |
|------|------|
| [sd0xdev/sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow) | 佈局：目錄、git、model、context%、session、thinking |
| [@kamranahmedse/claude-statusline](https://github.com/kamranahmedse/claude-statusline) | OAuth rate limits 進度條（5h / 7d / extra） |

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
| Hooks 設定 | `~/.claude/settings.json` → `hooks` |
| Hook 腳本 | `~/.claude/hooks/` |
| 輔助 Scripts | `~/.claude/scripts/` |
| StatusLine | `~/.claude/statusline-command.sh` |
| 持續學習 | CLAUDE.md `LEARNING` 規則 + auto memory + claude-mem |

## 變更紀錄

### 2026-03-16: CLAUDE.md Linus 工程哲學、需求分析 skill、對話原則

**CLAUDE.md 更新：**
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

### 2026-03-14: 新增 post-commit-review hook、同步 scripts

**新增項目：**
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
