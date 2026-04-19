---
name: token-analyze
description: 分析 Claude Code session 的 token 使用量，產出 markdown 報表（含 session 工作摘要、per-turn 明細、Top 5 燒錢 turn）。用於檢視「哪段工作 / 哪些工具 / 哪些檔案讀寫」最耗 token，作為調整使用習慣的依據。當使用者說 /token-analyze、「分析 token」、「token 用量」、「這個 session 花了多少」、「哪個 turn 最貴」、「token 報表」、想做 session 成本回顧、想找出燒 token 的工作模式時觸發。可選參數：自訂檔名、指定其他 session uuid。
version: 1.0.0
user_invocable: true
---

# Token Analyze — Session Token 使用量分析

從 transcript JSONL 重建每個 assistant turn 的 token usage、工具呼叫、檔案存取，產出純 markdown 報表，幫助回答「這段 session 哪段工作最耗 token」。

## 為什麼要這個 skill

Claude Code 沒有內建 per-session token 統計（dashboard 只有日級）。但 transcript JSONL 每個 assistant turn 都有完整 `message.usage`：`input_tokens` / `cache_creation_input_tokens` / `cache_read_input_tokens` / `output_tokens`，可離線重建。

關鍵洞察：**「讀複雜 bug → token 多」對應的是 `cache_creation_input_tokens`（新讀的檔案），不是總輸入。** `cache_read` 看起來大但只算 10% 費用，`cache_creation` 才是 125% 的真正增量成本。

## 參數解析

使用者可選傳入：
- `<filename>`：自訂輸出檔名（不含路徑，預設 `token-analysis-<YYYYMMDD-HHMMSS>.md`）
- `<session-uuid>`：分析其他 session（預設當前 session）

## 步驟

依序執行，每步完成後標記 ✅。

### STEP 01: 解析參數 + 找 transcript

#### 1a. 解析參數

使用者可能傳：`/token-analyze`、`/token-analyze my.md`、`/token-analyze <uuid>`、`/token-analyze my.md <uuid>`。

判別規則（簡單明確）：
- 含 `-` 且長度 36 字元的字串 → 當作 `<session-uuid>`
- 其他字串（含 `.md` 或無延伸名）→ 當作 `<filename>`
- 多個 token 順序不重要，按上面規則分類

例：
- `/token-analyze` → 兩個都用預設
- `/token-analyze report.md` → filename=`report.md`
- `/token-analyze aa73e55f-e3da-4ebb-bee1-ec4eee62140e` → uuid=...
- `/token-analyze trial.md aa73e55f-...` → 兩個都採用

#### 1b. 找 transcript

1. **當前 session**（沒給 uuid）：從環境讀 `transcript_path`（statusline 通常從 stdin 拿，但 skill 內部沒有 stdin）。改成：列出當前專案的 jsonl，挑最新一個（mtime 最新）：
   ```bash
   ESCAPED_CWD=$(echo "$PWD" | sed 's|/|-|g')
   PROJECT_DIR="$HOME/.claude/projects/${ESCAPED_CWD}"
   TRANSCRIPT=$(ls -t "$PROJECT_DIR"/*.jsonl 2>/dev/null | head -1)
   ```
2. **指定 session-uuid**：直接拼 `$PROJECT_DIR/<uuid>.jsonl`，找不到就跨專案找：`find ~/.claude/projects -name "<uuid>.jsonl"`。
3. 找不到 → 直接報錯停下來，不要瞎猜。

### STEP 02: 跑 jq 重建 per-turn 資料

> ⚠️ **正常 session 的「總 input」可能很小（< 200）— 不是 jq 壞了。** Opus 的快取機制讓絕大多數輸入進 `cache_creation` / `cache_read`，純 `input_tokens` 只剩極少數無法快取的部分。錢主要花在 cc 與 cr，不是 input。

每個 assistant turn 的 JSONL 物件結構：
- `.timestamp`：ISO 8601
- `.message.usage`：四個 token 欄位
- `.message.content[]`：array，內含 `tool_use` 物件（`.name` / `.input`）

跑這段 jq 把每 turn 攤平成 JSON array（**工具名要去前綴**：`mcp__<plugin>__<server>__<tool>` → `<tool>`，用 split `__` 取最後段最簡單，不要用 regex 因 plugin/server 名可能含底線）：
```bash
jq -s '[.[] | select(.type == "assistant") | {
  ts: .timestamp,
  in: (.message.usage.input_tokens // 0),
  cc: (.message.usage.cache_creation_input_tokens // 0),
  cr: (.message.usage.cache_read_input_tokens // 0),
  out: (.message.usage.output_tokens // 0),
  tools: [.message.content[]? | select(.type == "tool_use") |
          .name | if startswith("mcp__") then split("__") | .[-1] else . end],
  files: [.message.content[]? | select(.type == "tool_use") |
          (.input.file_path // .input.path // .input.notebook_path // empty)]
}]' "$TRANSCRIPT" > /tmp/token-analyze-turns.json
```

### STEP 03: 計算成本（Opus 4.x 定價）

每 turn 與 session 累計都算。USD per 1M tokens：
- input: $15
- cache_creation: $18.75（input × 1.25）
- cache_read: $1.50（input × 0.10）
- output: $75

公式：`cost = (in*15 + cc*18.75 + cr*1.5 + out*75) / 1_000_000`

### STEP 04: 歸納 session 工作摘要

**這是這個 skill 的核心價值** — 不是只給數字，是給「哪段工作燒 token」。

讀 `/tmp/token-analyze-turns.json`，自己判斷：

1. **切段邊界**（用這三個訊號擇一或合併判斷，不要硬切時間）：
   - **cc 跳幅**：連續幾個 turn 的 cc 都很小（< 5k），突然跳到 > 20k → 新工作開始（讀新檔/換主題）
   - **工具序列轉換**：從 Read/Grep 切到 Edit/Write、或 Bash 連發 → 從探索進入實作
   - **檔案主題變化**：讀寫的檔名從 `tasks/*.md` 切到 `src/*.ts` → 從計畫進入 coding
2. **段數**：3-8 段，少於 3 段資訊不夠，多於 8 段太碎
3. **每段歸納一句話**：時間範圍 + 主要工具 + 主要檔案/工作主題
4. **特別標註高成本段**：哪段累積 cc 最高（用 cc 不用 cr，cr 是重複算）

舉例（這是給你看的範例，不是要你照抄）：
```
- 14:01–14:15：探索 statusline 機制（Read statusline-command.sh × 3、Grep × 5），cc 累計 80k
- 14:15–14:35：實作 token 追蹤（Edit × 8、Bash 跑測試 × 12），cc 累計 320k ← 最燒
- 14:35–14:50：寫 skill + eval（Write SKILL.md、Skill skill-creator）
```

### STEP 05: 拼 markdown 表格

**用 bundled script** `scripts/build-report.sh`（同目錄下）一次拼好骨架：

```bash
bash "$SKILL_DIR/scripts/build-report.sh" "$OUT_PATH" "$SESSION_UUID" "$TRANSCRIPT"
```

該 script 會：
- 讀 `/tmp/token-analyze-turns.json`（STEP 02 寫入的）
- 算 Summary、cost、Top 5、Per-turn 表格
- 寫到 `$OUT_PATH`，但 `## Session 工作摘要` 留 `__SUMMARY_PLACEHOLDER__`，等 STEP 04 的歸納填回

**填回摘要**：用 Edit 工具替換 `__SUMMARY_PLACEHOLDER__`。

完整輸出格式（**最終結構**）：

```markdown
# Token Analysis — <session-uuid 前 8 碼>
> 生成時間：YYYY-MM-DD HH:MM
> Transcript: <transcript 完整路徑>
> 總 turn 數：<N>

## Session 工作摘要

<從 STEP 04 歸納的 3-8 段，每段一行>

> ※ 摘要從 turn 時間段 + 主要工具 + 主要檔名歸納，幫助判斷哪段工作 token 量較大。

## Summary

| 欄位 | 值 |
|---|---|
| 總 turn 數 | <N> |
| 總 input | <格式化，如 12.3k> |
| 總 cache_create | <格式化> |
| 總 cache_read | <格式化> |
| 總 output | <格式化> |
| **總成本** | **$XX.XX** |

### 三種 input token 的意義（提醒）

- `input_tokens`：純新寫、沒進快取的輸入（100% 計費）
- `cache_creation_input_tokens`：第一次寫入快取的內容，**新讀檔案的真正成本**（125%）
- `cache_read_input_tokens`：從快取重讀（10%）

## Per-turn 明細

| # | 時間 | in | cc | cr | out | cost | 工具 |
|---|---|---|---|---|---|---|---|
| 1 | HH:MM:SS | 234 | 18k | 0 | 156 | $0.35 | Read, Grep |
| 2 | HH:MM:SS | 12 | 2.3k | 18k | 89 | $0.07 | Edit |
...

## Top 5 燒錢 turn

| # | 時間 | cost | 工具 | 主要檔案 |
|---|---|---|---|---|
| 7 | HH:MM:SS | $2.80 | Agent×2, Read×5 | statusline-command.sh, todo.md |
...
```

### 格式化規則

- token 數字：< 1000 顯示原值；1000-999999 顯示 `12.3k`；≥ 1000000 顯示 `1.2m`
- cost：保留 2 位小數，加 `$` 前綴
- 工具：去掉 `mcp__<plugin>__<server>__` 前綴；同 turn 同工具用 `工具×N` 顯示
- 檔案：取 basename，多檔用 `,` 串接，超過 3 個用 `, ...` 截斷
- Top 5：依 cost 降序

### STEP 06: 寫入檔案

1. 解析參數：
   - 有 `<filename>` 用之；否則 `token-analysis-$(date +%Y%m%d-%H%M%S).md`
   - 一律寫到 `<PWD>/tasks/<filename>`，沒有 `tasks/` 就建
2. 寫檔
3. 回報絕對路徑給使用者

### STEP 07: 回報

簡短回報：
- 報表路徑（絕對路徑）
- 一行 summary：`<N> turn / 總成本 $XX.XX / 最貴 turn $X.XX`
- 一行 hint：`想看其他 session 跑 /token-analyze <session-uuid>`

## 邊界情況

- **transcript 找不到** → 報錯，列出搜尋過的路徑，不繼續
- **空 session（0 turn）** → 寫一個只有 header 的報表並提醒
- **transcript 很大（> 10MB）** → STEP 02 jq 可能慢，先告知使用者「分析中…」
- **未來模型改價** → 改 STEP 03 的數字並更新 SKILL.md 註解

## 不做

- ❌ 跨 session 累計（這次只做單 session，月報另開）
- ❌ 圖表（純 markdown 表格）
- ❌ 自動上傳/分享（只寫本地檔案）
