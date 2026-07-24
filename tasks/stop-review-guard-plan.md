# stop-review-guard 設計研究 — pending-review 閘門補洞 — 2026-07-22

> 狀態：**可行性已實測驗證（2026-07-24）、未實作**。本文件記錄 2026-07-22 兩次 review
> 未觸發的根因分析、官方文件查證結果、建議設計與 2026-07-24 headless 實測結果。

## 背景：兩次未觸發的事故

同日兩次 Tier 2/3 commit 後，review 未被執行。過程：PostToolUse hook 正常寫入
marker、印出 systemMessage 指派 `Skill(commit-review)`，但主 agent 讀完後選擇先做
別的事（回答問題、純文字彙整），機制沒有任何東西逼它回頭。

**根因**：現有三個掛載點全部掛在「工具呼叫」的生命週期上——

| 掛載點 | 檔案 | 職責 |
|--------|------|------|
| PostToolUse (Bash) | `scripts/post-commit-review.ts` | 偵測 commit → 算 Tier → 寫 marker → systemMessage 指派（軟） |
| PreToolUse (Bash) | `hooks/commit-gate-guard.ts` | marker 存在時 deny「下一個 git commit」（硬，但只攔 commit） |
| SubagentStop | `hooks/subagent-review-clear.ts` | review 類 agent 完成自動清 marker |

而漏掉的兩次都發生在「**回合結束**」這個生命週期點：commit 後模型只打字回覆、
或做非 git-commit 的事，PreToolUse 閘門根本不被觸發檢查。

## 洞的本質：生命週期覆蓋分析

一個回合只有兩種結束方式：

1. **呼叫工具繼續** → 危險動作（新 commit）已被 commit-gate-guard 擋住。
2. **結束回合**（含純文字回覆）→ 目前無人看守。**這就是洞。**

結論：補上「回合結束」掛載點即閉合覆蓋，不需要動工具層。Claude Code 的
**Stop hook** 正是這個掛載點，且支援 `decision: "block"` 硬強制。

「純文字繞過任何 hook 架構都攔不住」的初判是錯的——PreToolUse/PostToolUse
攔不住沒錯，但 hook 架構還有 Stop 事件。

## 已查證事實（claude-code-guide 查官方文件，2026-07-22）

出處：<https://code.claude.com/docs/en/hooks> § Stop Hook

1. **`{"decision": "block", "reason": "..."}` 效果**：turn 不完成、agentic loop 繼續、
   模型獲得另一個回合，`reason` 注入給模型作為上下文。exit code 2 + stderr 行為等價。
   這是指令級強制注入，與 systemMessage 軟提醒不同量級。
2. **stdin 欄位**：`session_id` / `transcript_path` / `cwd` / `permission_mode` /
   `hook_event_name` / `last_assistant_message` / `stop_hook_active`。
   `stop_hook_active=true` 表示本 turn 已被 Stop hook 擋過一次。
3. **Esc 中斷是否觸發 Stop**：文件未載明，**待官方澄清**（實作時實測）。
4. **防循環**：官方無最佳實踐，僅提供 `stop_hook_active` 訊號。常見寫法
   「true 就放行」會讓閘門退化成每回合只擋一次。
5. **Stop 與 SubagentStop 分離**：subagent 完成觸發 SubagentStop，不會誤觸主
   agent 的 Stop hook。既有 `subagent-review-clear.ts` 不受影響。
6. **command type hook 可用**：agent/prompt type 仍壞（#34601 #39814 #39184，
   見 memory `reference_hook_types_status`），本方案只用 command type，不受影響。

## 否決方案：擴大 PreToolUse 攔所有工具

原始提案：marker 存在時 deny 下一個任意工具呼叫（不限 git commit）。否決理由：

1. **自鎖**：commit-review skill 的 chain 本身需要 Bash（eslint、compute-tier、
   clear script、osascript）、Skill（/simplify）、Agent（pr-reviewer）、Edit（修
   Critical）、MCP（trace_path）——全攔等於把 review 流程自己鎖死。要解就得養一台
   in-progress 狀態機（Skill 呼叫轉狀態、完成清除、逾時回收），多出一整類新邊界情況。
2. **拿不到 repo 上下文**：Read 任意檔案沒有 repo 訊號，只能退回 cwd 猜測，
   比現在 `resolveRepoRootFromCommand`（git -C / cd 解析）精確度更差。
3. **仍然堵不住純文字回覆**——真正漏掉的那個路徑它根本管不到。

品味判準：消除邊界情況 > 增加條件判斷。Stop gate 讓「哪些工具該放行」這整類
判斷直接消失。

## 建議方案：`hooks/stop-review-guard.ts`（掛 Stop 事件）

```
┌ 既有（不動）──────────────────────────────────────────┐
│ post-commit-review.ts   寫 marker（新增 sessionId 欄位）   │
│ commit-gate-guard.ts    PreToolUse deny 新 commit          │
│ subagent-review-clear   review agent 完成自動清 marker     │
└──────────────────────────────────────────────────────┘
                 ▼ marker 未清 && 回合要結束
┌ 新增 ────────────────────────────────────────────────┐
│ stop-review-guard.ts    Stop event：decision:block         │
│                         reason = 指派 Skill(commit-review) │
└──────────────────────────────────────────────────────┘
```

### 比對邏輯

掃 `MARKER_DIR`，只認同時滿足：

- 未逾期（沿用 `MARKER_MAX_AGE_MS` 4 小時）
- `marker.sessionId === 本次 session_id` **或** `marker.repoRoot === resolveRepoRoot(cwd)`

sessionId 是必要的：marker 是機器全域狀態（`~/.claude/state/pending-review/`），
兩個 session 開在不同 repo 時，A 的鎖不該擋 B 的回合結束。repoRoot 比對補兩個情境：
新 session 開在同 repo（跨 session 接手）、`git -C` 跨 repo commit（session cwd ≠
marker repo）。

需要 `post-commit-review.ts` 寫 marker 時多存 `sessionId`（PostToolUse stdin 就有
`session_id`），`ReviewMarker` interface 同步加欄位。

### block 輸出

```json
{"decision": "block", "reason": "🔒 pending-review 未完成：執行 Skill(commit-review) args: \"tier=N target=<hash>\"，完成後 bun ~/.claude/scripts/clear-pending-review.ts 解鎖。"}
```

把指派直接寫進強制注入的 reason，不再靠 systemMessage 自覺。

### 防循環：有界計數，不用 stop_hook_active 當唯一訊號

marker 新增 `stopBlockCount`：`< 3` 才 block、每次 block +1，達上限放行並印大聲
警告（systemMessage）。有界強制、絕不 brick；4 小時逾期照舊。上限是防 brick 的
保險絲，不是洞——每次 block 的 reason 是指令級注入，實務上第一次就會照做。

### 既有清鎖機制不動

SubagentStop 自動清、skill §5 手動清——marker 一清，Stop gate 自然放行。

## 候選方案：PreToolUse additionalContext 廣播提醒（可與 Stop gate 並行，2026-07-23 補充）

不同於前面已否決的「PreToolUse **deny** 攔所有工具」——這個候選只用
**additionalContext**（非 deny），marker 存在時下一次呼叫任意工具（matcher `*`，
不限 git commit）就注入提醒，**不阻擋工具執行**。因為不是 deny，review chain
本身要用的 Bash/Edit/Agent/MCP 完全不受影響，不會有否決方案的自鎖問題。

### 動機（本次事故的直接檢討）

癥結：PostToolUse 的 systemMessage 被當成背景資訊處理，優先權輸給「立刻回覆
使用者」；而 PreToolUse 的 additionalContext 依 `rules/common/hooks.md`
（HOOK-OUTPUT 節）「即時注入」——是當下立刻看到，不是下一輪才看到。約束力從
「等某次想 commit 才被動擋下」變成「下一步無論做什麼都先撞到提醒」，去掉可以
無視、逕自回覆使用者的空間。

### 與否決方案、與 Stop gate 的差異

| | 否決：PreToolUse deny 全工具 | 候選：PreToolUse additionalContext 全工具 | 建議：Stop gate |
|---|---|---|---|
| 語意 | 阻擋執行 | 不阻擋，只注入提醒 | 阻擋回合結束 |
| 自鎖風險 | 有（review chain 自己要用工具） | 無（不擋執行，chain 照跑） | 無 |
| 觸發面 | 任意工具呼叫前 | 任意工具呼叫前 | 回合結束前 |
| 對純文字回覆的效果 | 不適用（沒工具呼叫可攔） | **不適用**（沒工具呼叫，additionalContext 不會注入）——殘餘縫隙與原分析相同 | 涵蓋（回合結束才觸發，純文字回覆也算回合結束） |
| 強制力量級 | 硬（deny） | 軟（提醒，模型仍可能無視） | 硬（block，reason 指令級注入） |

### 誠實評估

- **好處**：比現行 PostToolUse systemMessage 好——注入時機提前到「下一步之前」
  而非「下一輪開頭」，觸發面從「只在想 commit 時」擴大到「任何工具呼叫前」。實作
  成本低，且因為是 additionalContext 不是 deny，不會有否決方案的自鎖問題。
- **局限**：本質仍是「軟提醒」，模型仍可能在看到提醒後選擇無視、繼續呼叫該工具，
  只是被無視的難度提高（更即時、更頻繁）。且**完全不解決純文字回合結束的原始
  缺口**：模型那一輪若不呼叫任何工具，PreToolUse 根本不會被觸發，這點和最初分析
  「純文字繞過 PreToolUse/PostToolUse 攔不住」完全一致，不能單獨當作 Stop gate
  的替代品。
- **定位**：可與 Stop gate **疊加、非互斥**。additionalContext 廣播提醒負責
  「盡量在模型選擇無視之前就洗掉這個念頭」（提早介入、降低真的走到需要 Stop
  gate 硬擋的頻率）；Stop gate 負責「萬一還是被無視，回合結束前一定攔下來」
  （保底）。是否兩者都做、或先做哪個，留待實作時評估投入產出比再拍板。

### 若要實作這個候選，待驗證項目

- [ ] additionalContext 在「同一輪連續多次工具呼叫」情境下是否每次都注入、
      或只注入一次（若每次都注入，需評估洗版程度，是否要比照 stopBlockCount
      做有界計數或降頻）
- [ ] matcher `*` 是否真的涵蓋 Skill / MCP 工具呼叫——claude-code-guide 查證
      文件時提到「Agent 呼叫觸發 `SubagentStart` 而非 `PreToolUse`」，需確認
      Skill 呼叫是否算同類別、是否被此 matcher 涵蓋
- [ ] 與 `commit-gate-guard.ts`（既有 PreToolUse Bash matcher，deny git commit）
      的執行順序與輸出疊加是否互相干擾

## 殘餘縫隙（誠實列）

| 縫隙 | 評估 |
|------|------|
| Esc 中斷可能不觸發 Stop | 使用者主動中斷屬可接受；marker 還在磁碟上，下一次回合結束照樣被擋 |
| 直接關 session | SessionEnd 擋不了任何東西；但 marker 持久化 + repoRoot 比對讓同 repo 新 session 仍被 Stop gate 與 commit gate 管住。可選：SessionStart hook 加 marker 檢查注入提醒（軟層，錦上添花） |
| 連續無視三次 block 就過 | 理論上存在；量級上 reason 注入遠強於 systemMessage，保險絲取捨為防 brick |
| hook 內層 catch-all 吞錯後 exit 0，hook-error-wrapper 的 ERRORS.jsonl 永遠記不到（2026-07-24 review 發現） | 內部真 bug（如 readdir EACCES、邏輯 TypeError）會讓閘門靜默失效、零痕跡——與本計畫要防的盲區同款。修法（catch 改 stderr + exit 1；非 2 的非零 exit 對 Stop/PreToolUse 均 non-blocking，fail-open 不變）涉及四個閘門 hook 的錯誤處理公約，留待另案統一，不單改一檔製造家族不一致。resolveRepoRoot 靜默回 null 的無診斷問題同屬此案 |
| skill spawn 的 headless session 被 repoRoot 比對攔到後自我遞歸指派 | per-session 計數已隔離額度（ReviewMarker 註解明載此設計）；此路徑尚無 E2E 實測，待觀察實際行為再決定是否需要豁免規則 |

## 替代激進方案（留作 Stop gate 實測仍漏時的下一步）

把模型從迴圈拿掉：PostToolUse hook 背景 spawn
`claude -p "/commit-review tier=N target=<hash>"` headless 跑 review、寫報告檔，
marker 改成「Critical 處理完」才清。資料結構層解法，徹底消滅「模型會不會照做」
整類問題。代價：另燒 quota、結果要接回主 session、Critical 修復終究要主 agent
動手。**現在上是過度設計，先上 Stop gate。**

## 實作時待驗證清單（2026-07-24 headless 實測，方法見下節）

- [x] Stop hook stdin 實際 payload dump — 計畫所列欄位全部存在且同名；另有文件未列的
      `prompt_id` / `last_assistant_message` / `background_tasks` / `session_crons`
- [x] `decision: block` 後 reason 實際注入位置與模型遵從度 — reason 以 **user role 訊息**
      注入 transcript（前綴 `Stop hook feedback:`），指令級；haiku 第一次就遵從
- [ ] Esc 中斷是否觸發 Stop（headless 無法測，需互動 session 實測；非阻斷項——marker
      持久化，下一次回合結束照樣被擋）
- [x] `stop_hook_active` 第二次停止實際值 — 第一次 `false`、被 block 後第二次 `true`，
      語意如文件所述；stopBlockCount 有界計數設計成立，`stop_hook_active` 可當輔助訊號
- [x] claude-mem Stop hook 並存 — 實測即在 claude-mem plugin 全域啟用（其 hooks.json 掛
      Stop）狀態下執行，我方 block 正常生效；事件內所有 hook 並行、任一 block 即 block，
      方向單一無互斥

## 可行性實測結果（2026-07-24）

**方法**：臨時 settings（`--settings`）掛測試 Stop hook（dump stdin + 第一次
`decision:block`、reason 要求輸出指定 token、第二次放行），`claude -p --model haiku`
headless 跑一輪純文字回覆。

**結論：可行性成立**。純文字回合結束（正是漏掉的路徑）確實觸發 Stop hook；block 後
agentic loop 續跑、模型照 reason 行動後才真正結束。`-p` headless 模式也會觸發 Stop。

**實測連帶發現的實作注意事項**：

1. **marker 掃描要過濾 `.json`** — `MARKER_DIR` 裡實際躺著 `subagent-stop-debug.log`，
   直接 readdir 全掃會 JSON.parse 炸掉（有 fail-open 也該避免誤觸）。
2. **settings hook `timeout` 欄位單位是秒**（官方文件），claude-mem 與
   everything-claude-code 皆用 `10`。本 repo settings.json 既有的 3000/5000/60000 疑為
   毫秒誤植（等於實質無 timeout），屬另案清理；新 Stop hook 直接用 `5`。
3. **效能短路順序** — Stop hook 每個 session 每次回合結束都跑；必須先檢查
   `MARKER_DIR` 是否有 `.json` marker、沒有就立即 exit 0，之後才准 spawn
   `git rev-parse`（resolveRepoRoot）。
4. **stopBlockCount 保險絲會被其他 session 吃掉** — 計數存在 marker（機器全域），
   同 repo 的其他 session（尤其 skills spawn 的 headless `claude -p`）repoRoot 命中
   也會被 block 並 +1，可能把 3 次額度耗光讓主 session 免審通過。實作時二選一：
   (a) 計數改 per-session map（`stopBlockCounts: Record<sessionId, number>`）、
   (b) 接受——headless 端有工具能力，被 block 後照 reason 跑完 review 清 marker
   也算閉環。實作時拍板。

## 任務清單（2026-07-24 實作完成）

- [x] **#1 `scripts/lib/review-marker.ts`** — `ReviewMarker` 加 `sessionId?: string` 欄位；計數欄位依上節第 4 點拍板採方案 (a)：`stopBlockCounts?: Record<string, number>`（per-session map，非計畫原列的全域 `stopBlockCount`）
- [x] **#2 `scripts/post-commit-review.ts`** — `writeMarker()` 寫入 `sessionId`（來自 stdin `session_id`；缺漏時略去欄位，stop gate 退回 repoRoot 比對）
- [x] **#3 `hooks/stop-review-guard.ts`** — 新 hook 本體（sessionId 優先/repoRoot 補位比對 + block 輸出 + per-session 計數遞增 + plan mode 放行 + 逾期清除；一律 fail-open）
- [x] **#4 `settings.json`** — 掛 `Stop` 事件（command type，走 hook-error-wrapper.sh；timeout 實際用 `10` 秒，與計畫的 `5` 不同——與既有 hook 條目一致，單位確為秒）
- [x] **#5 驗證** — 合成 stdin 全路徑測試 11/11 通過（含誤掛防呆、plan mode、壞檔容錯）；headless E2E 實測純文字回合被 block 至 max turns，transcript 確認模型第一次注入即遵從並執行 commit-review
- [x] **#6 sync repo → `~/.claude/`** — 四檔部署完成，diff 驗證一致（`~/.claude-max-2` hooks 為 symlink，兩帳號同時生效）
- [x] **#7 文件** — `harness/commit-review-policy.md` 閘門清單補 Stop gate（第 3 層，SubagentStop 改列第 4）；`CATALOG.md` 新增 Stop 段登記 + review-marker 消費端更新；`README.md` hooks 表 + 變更紀錄補 2026-07-24 條目

## 明確不做（防過度設計）

- 不擴大 PreToolUse 攔所有工具（否決理由見上）
- 不做 in-progress 狀態機
- 不做 headless review spawn（留作下一步觀察項）
- 不動 commit-gate-guard.ts / subagent-review-clear.ts（正交，剛修好）
