# Claude Code 多帳號配置

## 原理

Claude Code 透過 `CLAUDE_CONFIG_DIR` 環境變數決定設定目錄位置（預設 `~/.claude`）。
指定不同目錄即可隔離帳號認證，同時用 symlink 共享其餘設定，達到「一套設定、多帳號切換」。

## 帳號配置

| 帳號 | 設定目錄 | 啟動方式 |
|---|---|---|
| max（主帳號） | `~/.claude` | `claude`（預設） |
| jubo-team | `~/.claude-max-2` | `c-jubo`（alias） |

### Shell Alias

```bash
# ~/.zshrc
alias c-jubo="CLAUDE_CONFIG_DIR=~/.claude-max-2 claude"
```

## Symlink 共享架構

`~/.claude-max-2` 中絕大多數檔案/目錄都是指向 `~/.claude/` 的 symlink，僅保留帳號專屬資料為獨立檔案。

### 獨立檔案（不共享）

| 檔案 | 用途 | 不共享原因 |
|---|---|---|
| `.claude.json` | 帳號 OAuth 認證憑證 | 各帳號有獨立 token |
| `mcp-needs-auth-cache.json` | MCP OAuth 認證快取 | 各帳號 MCP token 獨立，共享會互相覆蓋 |
| `policy-limits.json` | 帳號速率限制資訊 | 各帳號方案配額不同 |

### 共享項目（symlink → `~/.claude/`）

涵蓋所有設定與工具資料：

- **核心設定**：`settings.json`、`settings.local.json`、`CLAUDE.md`、`CODE-REVIEW-RULE.md`、`.claude.json` 以外的 config
- **功能目錄**：agents、commands、hooks、plugins、rules、skills、scripts
- **狀態資料**：cache、sessions、history.jsonl、file-history、todos、tasks、plans
- **工具資料**：context-mode、homunculus、pr-watcher、quota-accounts.json
- **statusline**：statusline-command.sh、statusline-usage-cache.json、stats-cache.json
- **其他**：backups、debug、downloads、memory、paste-cache、shell-snapshots、statsig、teams、telemetry、usage-data、weekly-reviews、.learnings、ide

## Statusline 帳號顯示

`statusline-command.sh` 會根據 `CLAUDE_CONFIG_DIR` 判斷當前帳號並顯示在狀態列：

```bash
account_name="max"
if [ -n "$CLAUDE_CONFIG_DIR" ] && [ "$CLAUDE_CONFIG_DIR" != "$HOME/.claude" ]; then
    case "$CLAUDE_CONFIG_DIR" in
        *claude-max-2*) account_name="jubo-team" ;;
        *) account_name=$(basename "$CLAUDE_CONFIG_DIR") ;;
    esac
fi
```

## 變更紀錄

| 日期 | 變更 |
|---|---|
| 2026-04-01 | 建立 symlink 共享架構（42 個 symlink） |
| 2026-04-01 | `memory/` 從獨立目錄改為 symlink 共享 |
| 2026-04-01 | statusline 新增帳號名稱顯示 |
| 2026-04-01 | statusline cache 路徑從 `/tmp/claude/` 改回 `$HOME/.claude/` |
| 2026-04-01 | statusline jq index 修正 `-1` offset |
