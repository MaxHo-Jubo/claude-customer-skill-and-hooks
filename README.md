# Max的  Claude Code 自訂 Skills & Hooks 管理

集中管理本機上所有 Claude Code 自訂 skill、hook 與 script 的索引文件。

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

## Skills 一覽

| Skill | 指令 | 用途 |
|-------|------|------|
| jira | `/jira` | Jira Issue 管理，自動從 branch 識別 issue |
| jira-acceptance | `/jira-acceptance` | 比對 Jira 需求與 git diff，驗收實作完成度 |
| commit-spec | `/commit-spec` | 快速 commit spec/ 目錄改動 |
| spec-module | `/spec-module <path>` | 探索模組並產出結構化 spec 文件 |
| test-module | `/test-module <path>` | 掃描可測試函式，產出單元測試 |
| explore-report | `/explore-report <dir>` | 探索目錄並強制產出結構化報告 |
| method-refactor | `/method-refactor <method>` | 7 項檢查結構化優化重構方法 |
| gitnexus-exploring | — | 用 GitNexus 知識圖譜導航不熟悉的程式碼 |
| gitnexus-debugging | — | 用 GitNexus 追蹤呼叫鏈除錯 |
| gitnexus-impact-analysis | — | 用 GitNexus 分析修改的影響範圍 |
| gitnexus-refactoring | — | 用 GitNexus 規劃安全的重構 |

## Hooks 一覽

| Hook 類型 | 觸發時機 | 腳本 | 用途 |
|-----------|----------|------|------|
| SessionStart | 啟動 session | `detect-jira-issue.sh` | 自動偵測 branch 的 Jira issue |
| UserPromptSubmit | 使用者送出訊息 | `skill-activation-hook.cjs` | 檢查是否需要啟動 skill |
| PreToolUse | 工具執行前 | `gitnexus-hook.cjs` | 用 GitNexus 圖譜豐富搜尋上下文 |
| PreToolUse | 工具執行前 | `observe-wrapper.sh pre` | 持續學習觀察記錄 |
| PostToolUse (Write/Edit) | 寫入/編輯後 | `spec-section-validator.cjs` | 驗證 spec 區段格式 |
| PostToolUse (Write/Edit) | 寫入/編輯後 | `inventory-drift-detector.cjs` | 偵測 inventory 漂移 |
| PostToolUse (*) | 任何工具後 | `observe-wrapper.sh post` | 持續學習觀察記錄 |
| Stop | Session 結束 | `analyze-on-stop.sh` | 分析觀察結果，產生學習 instinct |

## Plugins & MCP Servers

詳見 [`plugins/README.md`](plugins/README.md)。

| 分類 | 數量 | 說明 |
|------|------|------|
| Plugins（啟用） | 10 | code-review、atlassian、claude-md-management、typescript-lsp、context7、everything-claude-code、claude-mem、context-mode、example-skills、document-skills |
| Plugins（停用） | 3 | code-simplifier、frontend-design、github |
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

## 檔案位置

| 類別 | 路徑 |
|------|------|
| Skills | `~/.claude/skills/` |
| Hooks 設定 | `~/.claude/settings.json` → `hooks` |
| Hook 腳本 | `~/.claude/hooks/` |
| 輔助 Scripts | `~/.claude/scripts/` |
| StatusLine | `~/.claude/statusline-command.sh` |
| 持續學習系統 | `~/.claude/homunculus/` |
