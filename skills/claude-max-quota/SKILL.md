# claude-max-quota

Claude Max 多帳號額度管理。查額度、切帳號、設定 statusline。

使用時機：
1. 說「cq」「額度」「quota」「剩多少」「帳號額度」
2. 說「換帳號」「切帳號」「switch account」
3. 說「設定多帳號」「setup multi account」「幫我設定額度顯示」
4. 問「哪個帳號最空」「用哪個帳號」

## cq（查額度）

跑 `bash ~/.claude/scripts/check-quota.sh` 拿到數據後，用這個格式列給 tkman 看：

| 帳號 | 週額度 | 週恢復 | 5h 額度 | 5h 恢復 | 狀態 |
|------|--------|--------|---------|---------|------|
| c1 xxx@xxx | X% | MM/DD HH:MM | X% | MM/DD HH:MM | 🟢/🟡/🔴 |

狀態判斷：
- 🟢 全滿（0-30%）
- 🟡 已用（31-69%）
- 🔴 快滿（70%+）

最後加一行建議：下次開新 session 用哪個帳號（最空的那個）。

重要：不能只跑腳本，必須列表格給 tkman 看。他不看終端機的 raw output。

## 幫新用戶設定多帳號

如果有人說「幫我設定多帳號」，流程：

### Step 1: 建目錄 + 登入
每個帳號跑一次：
```bash
mkdir -p ~/.claude-max-N
CLAUDE_CONFIG_DIR=~/.claude-max-N claude auth login
```
瀏覽器登入不同 Max 帳號。

### Step 2: 設定別名
在 ~/.zshrc 加：
```bash
alias cN="CLAUDE_CONFIG_DIR=~/.claude-max-N claude"
alias cq="bash ~/.claude/scripts/check-quota.sh"
```

### Step 3: 設定 statusline
在 ~/.claude/settings.json 加：
```json
"statusLine": {
    "type": "command",
    "command": "~/.claude/scripts/quota-statusline.sh"
}
```

### Step 4: 查額度的原理
check-quota.sh 內部會：
1. 從 Mac 鑰匙圈安全讀取 OAuth token（不印出、不記錄）
2. 呼叫 Anthropic 額度 API 取得使用量
3. 回傳 five_hour（5 小時 session）和 seven_day（週額度）的使用百分比和重置時間

注意：OAuth token 是敏感資訊，不應印到終端或寫入 log。
check-quota.sh 已做好安全處理，token 只在記憶體中使用。
