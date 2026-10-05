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


---

# #3 用 mod `tool.call` 的 `context` 取代失效的 PostToolUse 提醒 — 2026-10-05

**目標**：Write/Edit 後要提醒 model 的檢查，改經由 mod `tool.call` 回傳的 `context`（只有 model 看得到、同一回合送達），取代目前送不到 model 的 PostToolUse stdout。

## 現況（已查證）

| hook | 輸出方式 | model 看得到？ | 依據 |
|---|---|---|---|
| `scripts/inventory-drift-detector.ts` | `console.log` + exit 0 | ❌，而且**整支空轉** | 讀的是 `CLAUDE_TOOL_NAME`／`CLAUDE_TOOL_INPUT` 環境變數，在 2.1.289 執行檔中 0 筆（對照組 `CLAUDE_PROJECT_DIR` 33 筆）→ STEP 01 必定 exit 0 |
| `scripts/spec-section-validator.ts` 空骨架警告（當時的 STEP 06） | `console.log` + exit 0 | ❌ | rules/common/hooks.md：PostToolUse exit 0 的 plain stdout 只進 debug log |
| `scripts/spec-section-validator.ts` 缺 section（當時的 STEP 08） | `decision:block` + exit 2 | ✅ | 2026-08-14 實測 |
| `scripts/skill-version-check.ts` | `systemMessage` | ✅（下一回合，user 也看得到） | rules/common/hooks.md |

- `context` 欄位語意：`claude-code.d.ts:12161`，「What the model reads after the tool's result and the user never sees… One reminder, as a PostToolUse hook's is」
- 載入方式：沿用 ctx-handoff，`settings.json` 的 `env.CLAUDE_CODE_PLUGIN_DIRS` 加第二個路徑（以 `:` 分隔），只能用 user settings，不能用專案 settings
- 範圍外的附帶發現：`Notification` hook 用的 `$CLAUDE_NOTIFICATION_MESSAGE` 同樣是 0 筆，通知內文很可能一直是空的 → 另開一項處理，不併進本計畫

## Phase 0：探針（決策閘門，沒通過就不做 Phase 1）

- [x] P0.1 確認 inventory-drift 空轉：用真實 stdin JSON（Write skills/ 底下的檔案）實際跑一次 → 預期沒有輸出；再補上 `CLAUDE_TOOL_NAME`／`CLAUDE_TOOL_INPUT` 環境變數跑一次 → 預期有輸出（對照組，證明是輸入來源的問題，不是邏輯問題）
- [x] P0.2 寫 probe mod（放在 dev-mods 熱重載資料夾）：`tool.call` 攔 Write，`await next(e)` 之後回傳 `{ ...r, context: ['PROBE-<亂數>'] }`，驗證三件事：
  - [x] model 在**同一回合**讀得到這段字串（請 model 複述亂數）→ U3MUL5／WMZ03K（下一項 user 已確認與狀態列一致）
  - [x] transcript 裡 user 看不到這段字串 → user 確認只出現在狀態列；nonce WMZ03K 與狀態列一致
  - [x] 既有的 settings.json PostToolUse hook 照常執行（兩者並存不互相干擾）→ spec-section-validator block reason 與 context 同時送達
- [x] P0.3 `claude -p` 下 mod 有沒有載入（用 `CLAUDE_CODE_PLUGIN_DIRS` 載入時）→ 只記錄結果；這些提醒是品質提示，不是強制閘門，沒載入可以接受

**P0 結果（2026-10-05）**
- P0.1：只給真實 stdin → 沒有輸出、exit 0；補環境變數（對照組）→ 有輸出 → 確認問題在輸入來源。**新發現**：修好之後每次 Edit 會吐出 12 行以上「未記錄的 skill」（claude.ai 同步下來的 anthropic-skills），Phase 1 要先處理這些雜訊
- P0.2：互動模式下 context 在同一回合送達，跟 PostToolUse block 並存
- P0.3：`claude -p --plugin-dir` 下 haiku 複述出 `NONCE=Q1NF28`；對照組（沒載入 mod）回 `NONE` → headless 也能載入，也能送達。注意：`--allowedTools` 是 variadic 參數，prompt 要從 stdin 送

**閘門**：P0.2 第一項沒通過（症狀類似 #24788）→ 放棄 mod，改走「方案 B：腳本改讀 stdin，改輸出 `systemMessage`」，到這裡結束。

## 決策點（P0 通過後問 user）

- [x] D1 spec-section-validator（user 選 (a) 只搬空骨架警告） 要不要整支搬進 mod？
  - (a) 只搬空骨架警告，缺 section 的 block 留在 shell：block 已經實測可用，但同一支腳本的邏輯會分散在兩個地方
  - (b) 整支搬過去，block 改成 `context` 提醒：邏輯集中在一處，但失去 exit 2 的強制感
- [ ] D2 skill-version-check：維持 `systemMessage`（user 也要看到進版提醒），預設不搬

## Phase 1：實作（mod 是薄轉接層，邏輯留在既有腳本）

- [x] 1.1 `inventory-drift-detector.ts` 改成從 stdin 讀 hook JSON（`tool_name`、`tool_input.file_path`），保留現有掃描邏輯；~~新增 `--format=text` 輸出模式~~（未採用，見實作紀錄）；`findSkillFiles` 排除 `~/.claude/skills/synced/`（claude.ai 同步的 skill，是 P0.1 雜訊的來源）
- [x] 1.2 spec-section-validator 依 D1 結果調整輸出
- [x] 1.3 新建 mod（已移到 ~/.claude/mods/tool-reminders，dev-mods 副本已刪除） `~/.claude/mods/tool-reminders/`（plugin.json / hooks.json / register.ts）：
  - `tool.call` 只攔 Write/Edit，`await next(e)` 拿到結果；`isError` 或 `deny` 直接回傳原結果
  - 用 `$.process.run(['bun', script, ...args], { stdin })` 呼叫腳本（`--format=text` 未採用），stdout 不是空的就放進 `context`
  - 腳本 exit ≠ 0 或逾時 → `$.ui.log` 加 toast，**不得靜默**；原本的 tool 結果照常回傳（提醒失敗不能影響 Write 本身）
- [x] 1.4 settings.json：`CLAUDE_CODE_PLUGIN_DIRS` 加入新 mod 路徑；移除 inventory-drift 的 PostToolUse 項目（它本來就空轉，移除不會造成 regression）；spec-section-validator 依 D1 處理

**Phase 1 實作紀錄**
- 1.1 實際做法和計畫有出入：沒有加 `--format=text`（輸出本來就是純文字）；額外移除了 skill-rules.json 比對（STEP 06/07.02）——這個檔案已經沒有任何讀取端，25 行全是雜訊；`findSkillFiles` 同時排除 `skills/synced/` 和 `node_modules`（playwright-core 附帶的 trace/skill SKILL.md 造成重複項目）；stdin 不是合法 JSON 時改成 exit 1。修改後實測輸出 1 筆真的 drift（r15-r18-migrate 沒有記錄在 inventory）
- 1.2 `--warn-only`：只輸出空骨架警告、不做 block；預設模式拿掉空骨架那行 console.log（原本就送不到 model）
- 1.3 mod 的 `CHECKS` 資料表 + `$.process.run` 平行執行；失敗時寫 transcript log、跳 toast，並在 context 告知 model「結果未知」

## Phase 2：驗證

- [x] 2.1 `register.test.ts`（`claude plugin test`，review 後 10 個）：有 drift 附 context＋argv/stdin/逾時｜無輸出不附 context＋Edit tool_name｜保留下層 context｜工具出錯不跑｜工具被 deny 不跑｜非 Write/Edit 不跑｜exit≠0 走失敗出口且原結果不變｜stderr 空改帶 stdout｜子程序拋錯｜HOME 未設定。路徑篩選在腳本內，由 `scripts/reminder-scripts.test.ts`（10 個，spawn 真腳本）涵蓋
- [x] 2.2 mutation probe：故意讓腳本永遠沒有輸出 → 第一個測試要變紅
- [x] 2.3 `claude plugin validate` + `tsc -p`（tsc 抓到 3 個 noUncheckedIndexedAccess，已修）
- [x] 2.4 實機（spec-skeleton：寫入空骨架 spec 時送達；inventory-drift：改 settings.json 時送達「[Hook 變更]」；新的 `claude -p` session 經 CLAUDE_CODE_PLUGIN_DIRS 載入並送達；debug log 確認 ctx-handoff 與 tool-reminders 都已載入）：真的 Edit 一個 SKILL.md，請 model 在同一回合複述收到的 drift 提醒

## Phase 3：收尾

- [x] 3.1 更新 inventory.md 的 Hooks 區塊、CATALOG.md、README.md 變更紀錄（inventory 另補 Mods 區段、r15-r18-migrate、skill-activation 列改 Jev 版）
- [ ] 3.2 `/sync-my-claude-setting` → commit → commit-review

## 風險／回滾

- function hooks API 還在 early access：改版之後 mod 可能載入失敗。這組提醒沒有強制力，失敗的代價是退回現狀（現狀本來就看不到），可以接受
- 回滾：從 `CLAUDE_CODE_PLUGIN_DIRS` 拿掉 mod 路徑，再用 git 還原 settings.json 的 hook 項目
