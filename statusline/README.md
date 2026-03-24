# StatusLine 自訂狀態列

合併自兩個開源 statusline 方案，並加入 transcript 解析功能（參考 [claude-hud](https://github.com/jarrodwatts/claude-hud)）：

| 來源 | 貢獻 |
|------|------|
| [sd0xdev/sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow) (`--skill statusline-config`) | 整體佈局：目錄、git branch、model、context window 剩餘%、session 時長、thinking 狀態 |
| [@kamranahmedse/claude-statusline](https://github.com/kamranahmedse/claude-statusline) | OAuth rate limits 顯示：5 小時 / 7 天用量進度條、extra usage 費用追蹤 |
| [jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud) | 概念參考：工具統計、agent 狀態、todo 進度、config counts、session name |

## 顯示內容

**第一行** — 工作環境資訊：

```
~/projects/myapp (main*) │ Claude Opus 4.6 │ ctx:73% │ ⏱ 12m │ ◐ thinking
```

- 目錄路徑（黃色）
- Git branch + dirty 標記（綠色/紅色）
- 模型名稱（青色）
- Context window 剩餘百分比（藍→黃→紅，依使用量變色）
- Session 持續時間
- Thinking 開關狀態

**第二行** — Session 與工具追蹤（透過 transcript 解析）：

```
my-session │ ◐ Edit×5 Read×12 Bash×3 │ ⚡2 agents │ ☑ 3/7 │ 2md 14rules 6hooks
```

- Session name（紫色，從 transcript 第一行取得）
- 工具使用統計（前 5 名，附次數）
- 活躍 agent 數量
- Todo 完成進度
- Config counts（載入的 CLAUDE.md、rules、hooks 數量）

**第三～五行** — Rate limits（從 statusline JSON stdin 原生取得，2.1.80+）：

```
current ● ● ● ○ ○ ○ ○ ○ ○ ○  30% ⟳ 5:42pm
weekly  ● ● ○ ○ ○ ○ ○ ○ ○ ○  20% ⟳ mar 15, 3:00am
extra   ○ ○ ○ ○ ○ ○ ○ ○ ○ ○  $0.00/$50.00 ⟳ apr 1
```

- 5 小時滾動用量（current）
- 7 天滾動用量（weekly）
- Extra usage 月度費用（如有啟用）
- 進度條顏色：綠(<50%) → 橘(50-69%) → 黃(70-89%) → 紅(90%+)
- 原生資料不可用時 fallback 至舊 cache 並標記 `(stale)`

## 安裝

1. 複製腳本到 `~/.claude/`：

```bash
cp statusline-command.sh ~/.claude/statusline-command.sh
chmod +x ~/.claude/statusline-command.sh
```

2. 在 `~/.claude/settings.json` 加入設定：

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh"
  }
}
```

## 依賴

- `jq` — JSON 解析
- `git` — branch / dirty 狀態偵測

## 快取

| 快取檔案 | 刷新頻率 | 用途 |
|----------|---------|------|
| `/tmp/claude/statusline-usage-cache.json` | 每次更新（有原生資料時覆寫） | Rate limit 資料 |
| `/tmp/claude/statusline-transcript.json` | 3 秒 | Transcript 解析（工具/agent/todo） |
| `/tmp/claude/statusline-config.json` | 120 秒 | Config counts（CLAUDE.md/rules/hooks） |

## 資料來源

| 資料 | 來源 |
|------|------|
| 模型、context window、cwd、session | statusline JSON stdin |
| transcript_path | statusline JSON stdin |
| 工具統計、agent、todo、session name | transcript `.jsonl` 檔案解析 |
| config counts | 直接掃描檔案系統 |
| rate limits | statusline JSON stdin `rate_limits` 欄位（2.1.80+ 原生支援） |
