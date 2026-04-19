# Health Audit TODO — 2026-03-17

來源：`/health` 審計結果 + 使用者回應

---

## 已完成

- [x] **#1 settings.local.json 加入 .gitignore** — 防止未來 secret 洩漏
- [x] **#3 POST-COMMIT-REVIEW hook 加回** — 方案 D：CLAUDE.md（意圖層）+ PostToolUse hook systemMessage（使用者提示層）雙層並存
- [x] **#4 on-correction memory save** — 結論：語意層面規則 hook 無法強制，維持 CLAUDE.md 宣告 + `/weekly-review` 定期補救
- [x] **#5 Compact Instructions 加入 CLAUDE.md** — `<compact>` 區段定義壓縮保留優先序，搭配 PreCompact hook + LEARNING.on-compact 三層齊全

## 使用者自行調整
- [x] **#7 sync-my-claude-setting 補 frontmatter + 優化 description** — 補 name/version/description，description 加入觸發條件與 restore 說明
- [x] **#9 skill descriptions 精簡** — 9 個自建 skill 精簡完成（commit-spec 移除），平均縮減 30-50%
- [x] **#11 MEMORY.md 記憶歸檔** — 新增 3 筆專案記憶 + hook 輸出限制寫入 rules/common/hooks.md（共 6 筆→按類型分類索引）
- [x] **#13 自建 skill 加 version 號** — 10 個自建 skill 加入 `version: 1.0.0`（含 sync-my-claude-setting 補 frontmatter）

## 暫不處理（有明確理由）

- **#2 CLAUDE.md 重複** — repo 用途為備份/同步設定，重複是必然
- **#6 allowedTools 清理（45 條）** — 暫不調整
- **#8 ai-md skill 體積（2698w）** — 不處理
- **#10 TS rules 全域安裝** — 幾乎所有專案都用 TS，不需調整
- **#12 全域 MCP servers** — atlassian/claude-mem/context-mode/context7 全部需要

## 行為觀察備註

- Glob 回傳空結果未交叉驗證 → 已存 `feedback_cross_verify_tool_results.md`
- sync STEP 03 被跳過 → 已存 `feedback_sync_step03_no_skip.md`
- 記憶系統運作正常，糾正後有正確歸檔

---

# Token 使用量追蹤工具 — 2026-04-17

> **完工：2026-04-19**
> - **A（statusline 顯示 turn/total 兩排 + cost）** — 實作於 `statusline/statusline-command.sh`
> - **C（/token-analyze skill）** — `~/.claude/skills/token-analyze/`（含 `scripts/build-report.sh` + `evals/evals.json`）
> - **驗證**：3 組 with-skill agent eval 通過；Skill 已修 3 個改善點（input 小是正常、切段三訊號、參數解析規則）
> - **產出樣本**：`tasks/token-analysis-20260419-133350.md`

**緣起**：想分析不同情境下 token 消耗差異（例如看複雜 bug 時讀的程式碼多、token 用得多），作為調整用法的參考。

## 關鍵發現（已驗證）

- **transcript JSONL 每個 assistant turn 有完整 `message.usage`**（subagent 初判錯誤，已用實際檔案驗證）
- 路徑：`~/.claude/projects/<project-escaped-path>/<session-uuid>.jsonl`
- 欄位：`input_tokens / cache_creation_input_tokens / cache_read_input_tokens / output_tokens`
- 同 turn 的 `tool_use` name 在 `message.content[]` → 可直接對應「這 turn 用了哪些工具、花多少 token」
- 實際驗證樣本：單 turn `cc=107595 cr=0 out=866` → 下一 turn `cc=2311 cr=107595`（cache hit）

## 三種 input token 的意義（重要，避免分析誤判）

| 欄位 | 意義 | 收費比例 |
|---|---|---|
| `input_tokens` | 這 turn 純新寫、沒進快取的輸入 | 100%（基準） |
| `cache_creation_input_tokens` | 這 turn 第一次寫入快取的內容（新讀的檔案） | 125% |
| `cache_read_input_tokens` | 從快取重讀的內容（CLAUDE.md、歷史對話、之前讀過的檔案） | 10% |

**分析陷阱**：
- 把三者加總當「這 turn 看了多少」會錯，因為 `cr` 是歷史被重數 N 次
- 「讀複雜 bug → token 多」對應的是 **`cache_creation_input_tokens`**，不是總輸入
- 成本粗估：`cr×0.1 + cc×1.25 + in×1.0 + out×5.0`（Opus 比例）

## 四種方案評估

| 方案 | 粒度 | 即時性 | 工作量 | 能答「讀多少碼→多少 token」 |
|---|---|---|---|---|
| A. statusline 顯示累計 token | session | 即時 | 小（改 statusline jq） | ❌ 只看總量 |
| B. Stop hook 產 session 報表 | turn | session 結束 | 小 | ✅ 但價值有限（噪音多） |
| C. 獨立分析 slash command | turn/tool | 隨時 | 中 | ✅✅ 最精確，可 join tool_result 長度 |
| D. Console usage dashboard | 日 | 延遲數小時 | 0 | ❌ per-session 看不到 |

## 推薦組合

**A + C**：
- **A** statusline 即時顯示「本 session 累計 in/out/cache」→ 體感校準
- **C** 寫 `/token-analyze` skill，離線跑，輸出每 turn 的 token × 工具 × tool_result 長度 → 分析「讀 N 行 → M token」散布圖

**B 為何不推薦**：每次 session 結束自動跑報表，不看就是噪音；需要時再跑 C 更實用。

## 決策結果（已執行）

- [x] A + C 一起做
- [x] C 輸出純 markdown，每 turn 單獨計算（不累計）
- [x] 分開計算 session cost（Opus 4.x：in $15/M、cc $18.75/M、cr $1.50/M、out $75/M）
- [x] statusline A 顯示：input、cache_create、cache_read、累計 $（兩排：turn + total）

## 保留上下文（下 session 參考）

- 本 session transcript 範例：`~/.claude/projects/-Users-maxhero-Documents-projects-claude-customer-skill-and-hooks/aa73e55f-e3da-4ebb-bee1-ec4eee62140e.jsonl`
- 已驗證的 jq 查詢（可直接拿來用）：
  ```
  jq -r 'select(.type == "assistant") |
    "\(.timestamp[11:19]) in=\(.message.usage.input_tokens) cc=\(.message.usage.cache_creation_input_tokens) cr=\(.message.usage.cache_read_input_tokens) out=\(.message.usage.output_tokens) tools=\([.message.content[]? | select(.type == "tool_use") | .name])"' "$FILE"
  ```
- statusline 腳本位置：`statusline/statusline-command.sh`（有 3s TTL 快取機制可參考）

