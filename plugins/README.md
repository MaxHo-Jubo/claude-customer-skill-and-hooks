# Plugins & MCP Servers

目前安裝的 Claude Code 插件與 MCP 伺服器清單。

## Plugins（18 個安裝，13 個啟用）

### claude-plugins-official（Anthropic 官方）

| Plugin | 狀態 | 用途 |
|--------|------|------|
| code-simplifier | ✅ 啟用 | 程式碼簡化 agent，保留功能前提下提升清晰度與一致性 |
| code-review | ✅ 啟用 | PR 自動化 code review，使用多個專業 agent 協作 |
| atlassian | ✅ 啟用 | Jira & Confluence 整合，issue 查詢、建立、編輯、搜尋 |
| frontend-design | ✅ 啟用 | 前端 UI 設計指引與產生 |
| claude-md-management | ✅ 啟用 | CLAUDE.md 維護工具，審計與改善專案指令檔 |
| typescript-lsp | ✅ 啟用 | TypeScript/JavaScript Language Server，增強程式碼智慧 |
| context7 | ✅ 啟用 | Upstash Context7 MCP，即時查詢最新函式庫文件 |
| gopls-lsp | ✅ 啟用 | Go Language Server，Go 程式碼智慧與導航 |
| jdtls-lsp | ✅ 啟用 | Java Language Server，Java 程式碼智慧與導航 |
| pr-review-toolkit | ✅ 啟用 | PR 審查工具組，多個專業 review agent（silent-failure、type-design、test-analyzer 等）|
| playwright | ✅ 啟用 | Playwright 瀏覽器自動化 MCP，E2E 測試與網頁操作 |
| github | ❌ 停用 | GitHub 操作（改用 `gh` CLI） |
| superpowers | ❌ 停用 | superpowers 工作流程擴充套件 |

### claude-hud（claude-hud）

| Plugin | 狀態 | 用途 |
|--------|------|------|
| claude-hud | ✅ 啟用 | statusline HUD，顯示 session 資訊與狀態 |

### thedotmack（claude-mem，v13.9.3）

- **作者**：Alex Newman
- **來源**：https://github.com/thedotmack/claude-mem
- **授權**：AGPL-3.0
- **狀態**：✅ 啟用
- **說明**：跨 session 的持久記憶系統，context 壓縮與語意搜尋
- **Skills**：`/mem-search`、`/make-plan`、`/do` 等

### everything-claude-code（v1.2.0）

- **作者**：Affaan Mustafa
- **來源**：https://github.com/affaan-m/everything-claude-code
- **狀態**：❌ 停用
- **說明**：超過 10 個月密集使用累積的完整配置集，包含 agents、skills、hooks、rules（下列為其安裝內容參考，目前未啟用）

**提供的 Agents（13 個）**：

| Agent | 用途 |
|-------|------|
| planner | 複雜功能的實作規劃 |
| architect | 系統架構設計與技術決策 |
| tdd-guide | 測試驅動開發流程引導 |
| code-reviewer | 程式碼品質審查 |
| security-reviewer | 安全漏洞偵測 |
| build-error-resolver | 建置錯誤修復 |
| e2e-runner | Playwright E2E 測試 |
| refactor-cleaner | 死碼清理與合併 |
| doc-updater | 文件更新 |
| database-reviewer | PostgreSQL 查詢與 schema 審查 |
| go-build-resolver | Go 建置錯誤修復 |
| go-reviewer | Go 程式碼審查 |
| python-reviewer | Python 程式碼審查 |

**提供的 Skills（20+ 個）**：涵蓋 frontend-patterns、backend-patterns、golang-patterns、python-patterns、postgres-patterns、django-*、springboot-*、coding-standards、continuous-learning 等

### context-mode（claude-context-mode，v0.9.16）— 已移除

- **作者**：Mert Koseoğlu
- **狀態**：🗑️ 已移除（2026-07-16 停用 → 2026-07-17 刪除 plugin cache 釋放 63M → 2026-07-20 從 `settings.json` 移除條目）
- **說明**：節省 98% context window 的 MCP 插件。支援 11 種語言的沙盒執行、FTS5 知識庫與 BM25 排序、意圖驅動搜尋
- **移除原因**：與 `codebase-memory-mcp` 職責重疊，實際未使用；保留條目只是死設定

### anthropic-agent-skills（Anthropic 官方範例）

| Plugin | 狀態 | 用途 |
|--------|------|------|
| document-skills | ❌ 停用 | 文件處理套件：Excel、Word、PowerPoint、PDF 操作 |

---

## MCP Servers

目前運行中（來自啟用的插件）的 MCP 伺服器：

| MCP Server | 來源 Plugin | 傳輸方式 | 用途 |
|------------|-------------|----------|------|
| context7 | claude-plugins-official | — | 即時查詢函式庫最新文件與程式碼範例 |
| mcp-search | thedotmack/claude-mem | stdio | 跨 session 持久記憶，語意搜尋與觀察記錄 |
| atlassian | claude-plugins-official | — | Jira issue CRUD、Confluence 頁面管理、JQL/CQL 搜尋 |
| typescript-lsp | claude-plugins-official | — | TypeScript/JS 語言伺服器，提供型別檢查與程式碼導航 |
| playwright | claude-plugins-official | stdio | 瀏覽器自動化，E2E 測試與網頁操作 |

> `context-mode` 已完全移除（cache 已刪、`settings.json` 條目已清），其 MCP server 不再運行；`codebase-memory-mcp` 為 user-scope MCP（定義於 `~/.claude.json`，非插件，見 `mcp-servers.json`）。

---

## 設定檔位置

| 檔案 | 說明 |
|------|------|
| `~/.claude/settings.json` → `enabledPlugins` | 插件啟用/停用開關 |
| `~/.claude/plugins/marketplaces/*/plugin.json` | 各插件 manifest |
| `~/.claude/plugins/marketplaces/*/.mcp.json` | MCP server 定義 |
| `~/.claude/plugins/cache/` | 插件快取（版本化） |

## 安裝方式

Plugins 透過 Claude Code 內建的 plugin marketplace 安裝：

```bash
# 在 Claude Code 中使用
/install-plugin <plugin-name>

# 或直接在 settings.json 的 enabledPlugins 中啟用/停用
```
