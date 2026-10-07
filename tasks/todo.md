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

---

# #2 補上「工具呼叫被擋下」的記錄盲區 — 2026-10-05（原計畫用 mod，P0 後改為 guard 自己記錄）

**目標**：補上 `ERRORS.jsonl` 目前記錄不到的那類工具失敗：工具呼叫被擋下、根本沒執行的情況。

## 現況（已查證）與範圍修正

最早提 #2 的理由是「`post_tool_error.py` 掛錯事件空轉一個月」，但這在 2026-09-14 已經修好，改掛 `PostToolUseFailure` 並經實測確認。所以 #2 的價值比當初說的**窄**，要重新界定：

| 失敗類型 | 現在記錄得到嗎 | 依據 |
|---|---|---|
| 工具執行後失敗（Bash exit≠0、Read 檔案不存在、MCP 錯誤） | ✅ `post_tool_error.py`（ERRORS.jsonl 已累積 Bash 347 筆、Read 19 筆、MCP 數十筆） | `post_tool_error.py` 檔頭，2026-09-14 實測 |
| 同一個錯誤重複發生 | ✅ `repeat-failure-detector.ts`，達門檻時用 additionalContext 注入提示 | 檔頭；已知限制：平行失敗會搶寫 state 檔，可能少算一次 |
| **被權限擋下**（auto mode 分類器拒絕、user 拒絕） | ❌ 兩種事件都不觸發 | `post_tool_error.py` 檔頭：「Permission/sandbox-blocked calls fire neither event」 |
| **被 PreToolUse hook 擋下**（commit-gate-guard、big-read-guard、r15-syntax-guard） | ❓ 待確認 | — |

- `permissions.defaultMode` 是 `auto`、`deny` 規則是空的，所以「被權限擋下」幾乎都來自 auto mode 分類器或 user 拒絕。這類資料正好可以回答「哪些指令常被擋、值不值得加進 allowlist」（`/fewer-permission-prompts`），以及 guard hook 實際擋了多少次
- **不在範圍內**：把 `post_tool_error.py`／`repeat-failure-detector.ts` 改寫進 mod。這兩支已經能用；改寫只能消掉 state 檔的搶寫問題，卻得把 Jev client（帶 API key 的 HTTP 呼叫）搬進 mod，成本大於收益

## Phase 0：探針（決策閘門）

在 dev-mods 寫 probe mod：`tool.call` 攔所有工具，`await next(e)` 後用 `$.fs.write` 把 `{ tool, deny?, isError?, text 前 200 字 }` 附加到 scratchpad 的 jsonl；同時記下 ERRORS.jsonl 的行數，用來對照 `PostToolUseFailure` 有沒有觸發。

- [x] P0.1 對照組：Bash `exit 3` → 預期 probe 記到 `isError`，ERRORS.jsonl 也 +1（兩邊都看得到，所以 mod **不該**重複記這一類）
- [x] P0.2 PreToolUse hook 擋下：用 Read 整檔讀一個 ≥800 行的檔案，觸發 big-read-guard deny → probe 看到的是 `deny`、`isError` 還是什麼都沒看到？ERRORS.jsonl 有沒有 +1？
- [x] P0.3 auto mode 分類器拒絕：需要你配合。我送一個會被分類器擋的指令（例如寫到 repo 外的系統路徑），記錄 probe 看到什麼
- [x] P0.4 user 拒絕：需要你配合。在權限提示時按拒絕，記錄 probe 看到什麼

**P0 進度（2026-10-05）**
- P0.1：探針看到 `isError: true`；ERRORS.jsonl 477 → 478 → 兩邊都記錄得到，mod 不該重複記
- P0.2：探針看到 `isError: true`，text 是 `PreToolUse:Read hook error: …`（**不是** `deny`）；ERRORS.jsonl 維持 478 → `PostToolUseFailure` 沒觸發，**盲區確認存在，且 mod 看得到**。但在 `tool.call` 層只能靠 text 前綴和一般失敗區分，太脆弱
- 新發現（`claude-code.d.ts`）：(1) plugin 可以掛 `classic.PreToolUse`，`await next(e)` 拿到結構化的 `allow/ask/deny` 決策，不必解析 text；(2) 有原生的 `PermissionDenied` hook 事件（輸入含 `tool_name`、`tool_input`、`reason`），**settings.json 的 shell hook 就能掛**——如果它涵蓋 auto 分類器／user 拒絕，P0.3／P0.4 這兩類根本不需要 mod。觸發範圍型別文件沒寫，需實測
- 探針已擴充：加掛 `classic.PreToolUse`（記 deny）與 `classic.PermissionDenied`

**閘門**：
- P0.2～P0.4 都看不到（hook 在權限檢查之前或之外就被略過）→ mod 補不了這個盲區，#2 **放棄**，記錄結論後結束
- 看得到，但跟 P0.1 一樣也觸發 `PostToolUseFailure` → 本來就記錄得到，盲區不存在，#2 **放棄**
- 看得到，而且 `PostToolUseFailure` 沒觸發 → 進 Phase 1，只補看得到的那幾類

**P0.3／P0.4 結果（2026-10-05）**
- P0.3：在指令無害的前提下觸發不了 auto 分類器拒絕（`sudo -n true`、`curl … | bash -n` 都被放行）。不往真正危險的指令升級，**未驗證**
- P0.4（暫切 default 模式由 user 拒絕）：探針看到 `isError: true`，text 為引擎字串「The user doesn't want to proceed with this tool use…」；ERRORS.jsonl 沒有這兩筆 → 盲區確認存在。`classic.PermissionDenied` 沒觸發（0 筆）
- `classic.PreToolUse`：debug log 寫 `denial-probe: classic.PreToolUse bypassed by cc-plugin-sec-default (tier user)`，user 層 mod 拿不到結構化決策

**結論**：mod 只能靠比對引擎文字辨識「被擋下」，引擎改字就會靜默停止記錄、而且自己無從得知。user 決定（2026-10-05）：**不做 mod，改由三支 guard 在擋下時自己記錄**；user 拒絕這類不記（auto 模式下很少出現權限提示）。探針 mod 與紀錄檔已刪除

## 決策點

- [x] D1 寫到哪？（user 選 (a) 另開 DENIALS.jsonl，2026-10-05）(a) 另開 `~/.claude/.learnings/DENIALS.jsonl`：現有 ERRORS 讀取端完全不受影響，但目前沒有任何讀取端，要另外決定誰讀（例如 weekly-review 加一段統計）；(b) 寫進 ERRORS.jsonl 並加 `kind: "denied"`：weekly-review 現成就會讀到，但 `summarize_errors.py` 要改成把 denied 分開統計，否則 big-read-guard 的減速丘會灌大 Read 的錯誤數

## Phase 1：實作

- [x] 1.1 新增 `scripts/log-denial.ts`：唯一定義紀錄格式的地方。CLI：stdin 為 `{ guard, tool_name, tool_input, reason, session_id, cwd }`，附加一行到 D1 選定的檔案（**實作與計畫不同**：函式放在 `scripts/lib/denial-log.ts`；欄位最終為 `{ ts, kind, guard, tool, target, cwd_name, session, reason }`，沒有 `context`，review 後 `repo` 改名 `cwd_name`）。寫入失敗 → stderr + exit 1。另 export `logDenial()` 給 TS guard 直接 import
- [x] 1.2 `commit-gate-guard.ts`、`r15-syntax-guard.ts`：在送出 deny 的那一步之前呼叫 `logDenial()`。記錄失敗**不能**影響 deny 本身：catch 後寫 stderr，deny 照常送出（guard 是強制機制，紀錄只是附帶）
- [x] 1.3 `big-read-guard.sh`：在 STEP 09 deny 前呼叫 `bun ~/.claude/scripts/log-denial.ts`，同樣不影響 deny；不在 bash 裡另寫一份格式
- [x] 1.4 依 D1：(a) 在 weekly-review 加一段 DENIALS 統計（guard × 次數、同 guard × cwd × target ≥3 次）；(b) `summarize_errors.py` 把 `kind: denied` 分開統計

## Phase 2：驗證

- [x] 2.1 `log-denial` 單元測試：寫入假 HOME、欄位正確、寫入失敗時 exit 1
- [x] 2.2 三支 guard 的回歸測試：餵會被擋的 stdin → deny 輸出跟改動前**一字不差**，並多一筆紀錄；把紀錄檔設成不可寫 → deny 照常送出（記錄失敗不影響強制力）
- [x] 2.3 mutation probe：拿掉 logDenial 呼叫 → 測試要紅
- [x] 2.4 實機：觸發 big-read-guard（整檔 Read 一個 ≥800 行的檔），確認紀錄出現在 D1 選定的檔案，讀取端（weekly-review 統計或 summarize_errors）讀得出來

**Phase 1～2 實作紀錄（2026-10-05）**
- 格式只定義在 `scripts/lib/denial-log.ts`（`logDenial` 寫入失敗會拋錯、`tryLogDenial` 失敗時回傳附註）；bash guard 走 `scripts/log-denial.ts` CLI，路徑以腳本所在目錄推導（不依賴 HOME，測試的假 HOME 下也找得到）
- 記錄失敗不靜默也不削弱 guard：deny 照常送出，原因後面加「（附註：擋下紀錄寫入失敗：…）」，讓 model 看得到
- 測試：`hooks/denial-guards.test.ts`（2 個，三支 guard 各跑：正常擋下＋紀錄檔唯讀）、`scripts/lib/denial-log.test.ts`（3 個）；舊版 guard 跑新測試 2/2 紅，三支 guard 各拿掉記錄呼叫皆紅。踩坑：只把目錄設成唯讀擋不住對既有檔案的 append，要鎖檔案本身
- 新舊版比對：r15-syntax-guard、big-read-guard 正常擋下時的 deny 輸出一字不差（commit-gate-guard 需要 repo＋marker，由回歸測試涵蓋）
- 1.4：weekly-review 1.8.0 → 1.9.0（黃區，user 看過 diff 後同意；備份 `SKILL.md.bak-20261005`）；jq 統計先用已知資料驗過（7 天外排除、null repo 顯示 `-`）
- 2.4 實機：本 session Read `jira-test-report/SKILL.md`（857 行）被擋 → DENIALS.jsonl 一筆、欄位正確，weekly-review 的統計指令讀得出來

## Phase 3：收尾

- [x] 3.1 更新 inventory.md、CATALOG.md、README.md（hooks 表的三支 guard 補上「擋下時記錄」）
- [ ] 3.2 `/sync-my-claude-setting` → commit → commit-review

## 風險／回滾

- 最大風險是記錄邏輯害 guard 失效：由 1.2／1.3 的「catch 後照常 deny」加上 2.2 的不可寫測試把關
- 回滾：把三支 guard 的 logDenial 呼叫拿掉即可，紀錄檔可以直接刪

---

# #1 pending-review 狀態 band（唯讀 mod）— 2026-10-05

**目標**：在輸入框上方顯示目前有效的 pending-review marker（repo、Tier、commit、引擎、應跑面向數、已過多久、是否為本 session），讓 Stop 閘門擋下時 user 看得到卡在哪。

**範圍（沿用稍早結論）**：只讀不寫。上鎖、擋 commit、Stop 閘門、commit-review skill 全部不動；mod 沒載入只是看不到 band，閘門照常運作。

## 設計

- marker「有效」的定義只在 `scripts/lib/review-marker.ts`。新增唯讀 CLI `scripts/list-pending-review.ts`：用 `readMarkerRaw` 與 `MARKER_MAX_AGE_MS` 列出未逾期 marker 的 JSON。**不得呼叫 `readValidMarker`**：它會就地刪除逾期 marker 並寫 audit log，顯示用的讀取不能有副作用
- mod `review-band`：在 `session.start`、`turn.complete`、Bash 的 `tool.call` 結束後刷新（commit 與解鎖都走 Bash）；marker 目錄沒有 `.json` 時不 spawn。結果存在 `$.state` atom，由 `ui.render` 的 `AbovePrompt` 讀出；沒有 marker 就 `next(e)` 不佔位
- 讀取失敗不靜默：band 顯示「pending-review 狀態讀取失敗：<原因>」

## 步驟

- [x] 1 `scripts/list-pending-review.ts` + 測試（假 HOME：有效、逾期、壞檔、非 marker 檔、目錄不存在；確認逾期 marker 跑完後**仍在**，也就是沒有副作用）
- [x] 2 mod `review-band`（dev-mods 熱重載）+ `claude plugin test`（沒 marker 不畫、有 marker 的內容、本 session 標記、讀取失敗顯示、Bash 以外的工具不刷新）+ mutation probe + tsc
  - 紀錄：CLI 測試 4 個（含「逾期 marker 跑完仍在」）；mod 測試 6 個、mutation 7 項皆紅、tsc 0。測試坑：plugin 不畫時，測試裡要有模擬引擎的 `ui.render` 接手，而且必須回傳元素（回 `null` 不算接手）；`find({ key })` 找不到 Text，要用文字查
- [x] 3 實機（user 確認 band 出現、格式可以；暫時 marker 指向假 repo＋假 session，不觸發閘門，驗完已刪）：建一顆暫時 marker → band 出現；刪掉 → band 消失（第 1 輪呈現 70-80%，格式依 user 截圖回饋調整）
- [x] 4 移到 `~/.claude/mods/review-band`、加進 `CLAUDE_CODE_PLUGIN_DIRS`（已完成：新 `claude -p` session 的 debug log 顯示 ctx-handoff／tool-reminders／review-band 三個都 loaded；dev-mods 副本已刪；首次 tsc 因 extends 解析失敗誤輸出的 register.js／register.test.js 已刪）；文件與 #2 的 Phase 3 一起收尾（inventory／CATALOG／README → sync → commit → commit-review，見下方 #2／#1 共同收尾）

---

# #3 Teams 討論 → Jira 結論同步（jira skill 擴充）— 2026-10-07

**目標**：Teams 上追蹤 Jira 票的討論結論，在既有工作流的固定時間點產草稿、user 確認後貼到 Jira，避免結論只留在 Teams。

**PoC 已驗（<TICKET>，comment <commentId>）**：搜尋→讀 root→產草稿→貼 Jira 走通。

## 已知限制與 gotcha（PoC 實測，寫進 skill）

- 搜尋 `"<TICKET>"` 0 筆、`<數字>` 才命中（KQL 連字號斷詞）→ 搜數字，再用完整 key 過濾
- tenant 未授權 `Team.ReadBasic.All`：`teams_list_teams` 403；搜尋結果裡的 teamId 拿去 `teams_list_channel_messages` 回 404 → **列不出討論串回覆**
- root 可讀全文：`read_resource("teams:///chats/{channel thread id}/messages/{rootId}")`；reply 走此路由回 400、加 `/replies/{id}` 會被忽略並回 root → **reply 只拿得到搜尋摘要（約 500 字，會截斷）**
- 搜尋結果無 `replyToId` → 同 channel 其他討論串會混入
- 三種失真（遺漏／截斷／串錯）→ 一律「草稿＋人工確認」，禁止全自動貼
- M365 connector 有 write-gated 寫入工具（`teams_send_*`），skill 限定只用讀取類

## 設計

- **同步流程只定義一次**：寫在 `jira/SKILL.md` 的「Teams 同步流程」章節；三個觸發點引用章節，不複製步驟（EXTRACT-SHARED-HELPER）
- **同步狀態存在 Jira 本身**：最後一則以標題 `【Teams 討論結論同步】` 開頭的留言時間 = 上次同步點；沒有就用 issue 建立時間。不建本機狀態檔（標題是同步點哨兵，改字要一起改偵測邏輯）
- 署名固定為 `由 Claude Code skill 整理`（2026-10-07 user 定案；作者欄已是本人帳號，不另署名；署名為各 skill 共用格式，不當哨兵）
- 找串：seed 搜尋範圍從 issue 建立時間起（root 可能早於上次同步點）；新訊息才用同步點過濾
- 草稿格式：結論／決策／待辦＋來源清單（發話者、時間、全文 or 摘要）＋「可能遺漏」提示＋署名
- 0 筆時明講「找到 N 個討論串、同步點後 0 則新訊息」；搜尋/授權失敗另走錯誤出口，不可混成「沒有新討論」
- user 確認前不呼叫任何 Jira 寫入工具

## 步驟

- [x] 1 `jira/SKILL.md`：新增子指令 `/jira teams [ISSUE_ID]` + 「Teams 同步流程」章節（前置檢查 → 同步點 → 搜串 → 草稿 → 確認後寫入）+ gotcha 段；version 1.2.0 → 1.3.0
- [x] 2 `jira/SKILL.md` 觸發點 A：`/jira fetch`・`/jira branch` 跑流程的唯讀部分，把 Teams 討論摘要寫進 `{ISSUE_ID}-Jira.md` 的「Teams 討論」段；有同步點後新內容 → 提示跑 `/jira teams`
- [x] 3 `save-progress/SKILL.md` 觸發點 B：有 Jira 編號時檢查同步點後的新討論，有就產草稿問要不要貼；插在 STEP 02 後（新 STEP 03，原 03/04 往後 +1）；version 1.1.0 → 1.2.0
- [x] 4 `jira-release-sync/SKILL.md` 觸發點 C：STEP 03 對每筆候選查「同步點後新 Teams 訊息數」，STEP 04 表格加一欄；user 指定的才產草稿（不對全部候選逐一產草稿，控制呼叫量）；version 1.5.0 → 1.6.0
- [x] 5 驗證（a、c 已過；b 擱置——2026-10-07 user 決定等實際使用遇到問題再調整；d 未驗）：(a) `/jira teams <TICKET>` 應偵測 <commentId> 為同步點並回報新訊息數（已知答案對照組）(b) 另找一張有 Teams 討論、未同步的票跑完整流程 (c) 故意給不存在的票號 → 應回報「0 個討論串」而非錯誤 (d) 撤授權情境以 `get_granted_scopes` 失敗路徑檢查訊息
- [ ] 6 `/sync-my-claude-setting` → commit → commit-review

## 待決（不阻擋開工）

- 是否請 IT 對 Claude M365 connector 補 `Team.ReadBasic.All` admin consent（補了可讀完整討論串，三種失真消失；skill 屆時改用 `teams_list_channel_messages(parentMessageId)`）
