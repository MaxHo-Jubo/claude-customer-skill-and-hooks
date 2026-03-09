# StatusLine 自訂狀態列

合併自兩個開源 statusline 方案：

| 來源 | 貢獻 |
|------|------|
| [sd0xdev/sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow) (`--skill statusline-config`) | 整體佈局：目錄、git branch、model、context window 剩餘%、session 時長、thinking 狀態 |
| [@kamranahmedse/claude-statusline](https://github.com/kamranahmedse/claude-statusline) | OAuth rate limits 顯示：5 小時 / 7 天用量進度條、extra usage 費用追蹤 |

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

**第二～四行** — Rate limits（需 OAuth 登入）：

```
current ● ● ● ○ ○ ○ ○ ○ ○ ○  30% ⟳ 5:42pm
weekly  ● ● ○ ○ ○ ○ ○ ○ ○ ○  20% ⟳ mar 15, 3:00am
extra   ○ ○ ○ ○ ○ ○ ○ ○ ○ ○  $0.00/$50.00 ⟳ apr 1
```

- 5 小時滾動用量（current）
- 7 天滾動用量（weekly）
- Extra usage 月度費用（如有啟用）
- 進度條顏色：綠(<50%) → 橘(50-69%) → 黃(70-89%) → 紅(90%+)

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
- `curl` — 取得 rate limit 資料（可選，沒有的話只顯示第一行）
- `git` — branch / dirty 狀態偵測
- macOS `security` 或 `~/.claude/.credentials.json` — OAuth token 取得

## 快取

Rate limit 資料快取於 `/tmp/claude/statusline-usage-cache.json`，每 60 秒刷新一次，避免過度呼叫 API。
