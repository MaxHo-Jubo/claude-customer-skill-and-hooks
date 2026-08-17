---
name: commit-review
description: "Commit 後分級 review chain（Tier 0~3）。被動由 post-commit hook 指派，也可手動 /commit-review [target] 對任意 commit 補跑。當使用者提到 /commit-review、「跑 review」、「補跑 review」、「review 這個 commit」、「push 前 review」時觸發。不適用於：PR 級完整審查（用 /pr-reviewer <PR>）、需求驗收（用 /jira-acceptance）。"
version: 1.2.0
last_modified: 2026-08-19
---

# Commit Review

commit 後依風險分級（Tier 0~3）執行對應深度的 review chain。這是整套 pending-review 機制的**執行層**——分級判定與強制閘門由 hook 負責，本 skill 只負責「跑對應 Tier 的步驟」。

- **判準權威**：`~/.claude/harness/commit-review-policy.md`（分級判定表、免跑條件、Blast Radius 節、禁止事項）。本 skill 不重複判定表，只定義每個 Tier 的執行步驟。
- **強制力**：由 `commit-gate-guard.ts`（PreToolUse deny）提供，skill 無法取代。

## 觸發模式

### 被動（hook 指派）
commit 後 PostToolUse hook 已機械算好 Tier，透過 systemMessage 指派：
`Skill(commit-review) args: "tier=N target=HEAD"`
此模式 **tier 已知，直接採用不重算**（判定單一來源，與 hook 同一份 lib/tier.ts）。

### 手動（使用者主動）
- `/commit-review` — 對 HEAD 跑
- `/commit-review HEAD~3` — 對指定 commit 跑
- `/commit-review <hash>` — 對指定 commit 跑

用途：marker 逾期補跑、想重跑、push 前主動 review、對舊 commit 補 review。手動模式 args 不含 tier → 自己算（見下 §1）。

## 執行步驟

### 1. 決定 target 與 tier
- 解析 args：`tier=N`（被動帶入）、`target=<ref>`（預設 HEAD）。
- **args 含 tier** → 直接用（被動模式，不重算）。
- **args 不含 tier** → 手動模式，執行 `bun ~/.claude/scripts/compute-tier.ts <target>`，讀取輸出的 `TIER=N`。
  - **exit code 非 0 → 停止並回報使用者**（通常是 ref 打錯），不得逕自採用任何 TIER 值。
- target 解析不出 → fallback HEAD。

### 2. 免跑條件（任一成立 → 只跑 §7 通知）
對照 commit-review-policy.md 免跑條件：commit and push 的一部分 / 空 commit / commit 失敗 / amend 既有 commit 且新增 diff < 10 行。

### 3. 依 Tier 分派（往下只跑對應 Tier 那節）

**Tier 0 純文件** — 只跑 §7 通知。

**Tier 1 小改動（不 spawn agent）**
1. eslint：被動模式 systemMessage 已附結果，依結果修正即可；手動模式自跑 `npx eslint <本次變更的 JS/TS 檔>`。
2. 自查 `~/.claude/harness/judgment-matrix.md` §2 對應任務型態的 DoD checklist。
3. §7 通知。

**Tier 2 標準**
1. eslint（同上規則）。
2. `/simplify`（對本次變更）。
3. pr-reviewer **agent**（lite 模式）：`Agent(subagent_type: "pr-reviewer")`，不帶 `name` 參數（帶了結果不回流）。
   注意：同名的 `/pr-reviewer` **skill** 是 PR full review，本步驟不要用它。
4. 依 §3.1 確認 lite agent 結果已回流（沒回流不得往下走，也不得自己重做後當作跑過）。
5. 修 CRITICAL 問題 → `git commit --amend`（不另開新 commit）。
6. Blast radius（§4）。
7. §7 通知。

**Tier 3 大改動** — Tier 2 全部（eslint / `/simplify` / pr-reviewer lite / 修 CRITICAL），外加下列五面向平行 review。

> **不得改用 `/pr-review-toolkit:review-pr` 委派**（2026-08-17 起）。該 command 有自己的 "Determine Applicable Reviews" 篩選（`commands/review-pr.md:36-43`），**傳五個 aspect 參數不等於跑五個面向**，決定權在被委派方；且該 command 的 workflow 明定用於 commit **之前**，預設 scope 是 `git diff`（未 commit 變更），在 commit 後跑會是空的。
>
> 實測主證據：claude-mem observation 13128 記錄 Tier 3 新架構首次執行**只 spawn 3 個 agent**（缺 code-reviewer / pr-test-analyzer / type-design-analyzer，其中 code-reviewer 還是該 command 標記 Always applicable 的）。
>
> 佐證（**不足以單獨成立**）：SubagentStop debug log 五面向完成次數為 15/14/13/11/10。該 log 78% 的 `agent_type` 為空且無 session_id，無法把任一行歸屬到某一輪 Tier 3，故落差同樣可能只是「部分 stop 記成空」——它支持縮水的存在，但證明不了哪一輪缺哪個面向。
>
> 故改為本節逐一明列、由本 skill 直接 spawn。

1. **五個面向 agent 放在同一則訊息內平行發出**，全部**不得帶 `name` 參數**（帶 `name` 的 agent 結果不會自動回流，實測對照表見 `~/.claude/agents/pr-reviewer.md` §Agent 執行約定）。需要區分用途用 `description`：

   | subagent_type | description |
   |---|---|
   | `pr-review-toolkit:code-reviewer` | `"code review"` |
   | `pr-review-toolkit:silent-failure-hunter` | `"silent failure"` |
   | `pr-review-toolkit:comment-analyzer` | `"comments"` |
   | `pr-review-toolkit:pr-test-analyzer` | `"tests"` |
   | `pr-review-toolkit:type-design-analyzer` | `"types"` |

   每個 prompt 必含四項，缺一該面向等於審錯目標：

   - repo 絕對路徑
   - **審查目標**：明寫 `git diff-tree --no-commit-id -r -p <target>`，要求 agent 自己執行取得 diff。**必須帶上實際的 target ref**——commit 已完成、工作目錄乾淨，這些 agent 的預設 scope（`git diff`）會是空的
   - 本次 commit message 與一句話改動摘要
   - 回報格式：issues list，每則含「問題描述 + `檔案:行號` + 嚴重度」；引用超過 20 行的程式碼改寫成 `路徑:起-迄行號`

2. 依 §3.1 收齊五個面向結果（未收齊不得往下走）。
3. 修 Critical / Important（不另 commit，amend 或留 uncommitted）。
4. Blast radius（§4）。
5. §7 通知。

### 3.1 平行 agent 的失效處理（Tier 2/3 皆適用）

**收齊全部子 agent 結果之前，禁止宣告 review 完成、禁止清 marker、禁止進入下一步。** 未收齊就結束該輪繼續等 task-notification。

下列三種都算該面向失敗，**不可當成空結果放過**：

- agent 回報錯誤
- agent 回傳 `null`（被使用者跳過，或重試後仍終止）
- 結果始終沒回流（等不到該面向的 task-notification）

失敗時的處理：

- **禁止自己重做該面向的分析後照常輸出。** 那會把機制失效偽裝成正常結果，使用者無從得知這輪 review 實際上少跑了幾個面向。
- 必須在報告**最開頭**（不是結尾附註）標明：「Tier `<N>` 降級：`<未回傳數>`/`<該 Tier 應跑數>` 個面向未回傳（列出面向名稱），本次未達該 Tier 的取樣覆蓋率」。應跑數：Tier 2 為 1（lite），Tier 3 為 6（lite + 五面向）。
- 已回來的面向照常處理，不因此丟棄。
- **降級時不得清 marker**（見 §5），改為回報使用者，由其決定補跑或手動解鎖。

理由：面向靜默消失與「該面向沒發現問題」在輸出上完全無法區分，這正是 `~/.claude/CLAUDE.md` core-principles 的 `verify-the-observer` 所指的盲區——PR 1134 的兩個 CRITICAL（`.then()` 缺 `.catch()` 造成連線洩漏與需重啟 App）在 commit 層是 Tier 3 卻未被攔下，兩天後才由 PR full review 抓出。

### 4. Blast radius（Tier 2/3 必跑）
依 commit-review-policy.md「Blast Radius 分析」節執行：codebase-memory-mcp 對本次改動 symbol 跑 `trace_path`(inbound)。資訊性輸出、不自動改；揭露遺漏 caller 回報 user；project 未索引 → 標「impact 未取得」跳過；注意「方法當 callback 參照傳遞」盲區，callers 回空需 grep 補查。

### 5. 解鎖 marker（有 pending-review marker 時）

**本步是唯一的自動解鎖路徑**（2026-08-17 起）。SubagentStop hook 已停止清除 marker——舊行為是「任一 `agent_type` 含 `review` 的子 agent 完成就清」，Tier 3 並行 6 個 agent 時第一個回來的就解除閘門，其餘面向與 Critical 修復形同虛設；full review 的面向 agent（`pr-1134-full-review` 等）也命中該 pattern 誤清。詳見 `hooks/subagent-review-clear.ts` 檔頭。

清除前置條件（**兩項都滿足**才可執行）：

1. 該 Tier 的所有面向 agent 結果**已收齊**（§3.1；Tier 1 無子 agent，此條自動成立）
2. review 發現的 Critical 已處理完（amend 或留 uncommitted）

滿足後執行（**必須帶 `--aspects-done=N`**，N = 實際收齊的面向數）：

```bash
bun ~/.claude/scripts/clear-pending-review.ts --aspects-done=<N>
```

自 2026-08-19 起這兩個前置條件**由腳本機械檢查**，不再只是本節的文字約定：marker 帶有
`expectedAspects`（Tier 2 = 1、Tier 3 = 6），`N < expectedAspects` 時腳本 exit 1 拒絕解鎖並印出缺口。
每次成功解鎖都追加一行到 `~/.claude/state/pending-review/unlock-audit.log`，可事後對帳。

改動理由：此前腳本無條件 `unlink`，整套閘門是「上鎖機械、解鎖靠自覺」——而 commit-gate-guard 與
stop-review-guard 的攔阻訊息還直接把解鎖指令印給模型，等於在最想結束回合的時刻遞上鑰匙。
N 仍是自報（腳本無從驗證 agent 真的跑過），但把靜默省略換成顯式、留痕的斷言。

- **§3.1 判定為降級（有面向沒回傳）時不得清**：先向使用者回報未回傳的面向名稱，取得同意後才用
  `--force "<理由>"` 放行（會在 audit log 標記 `FORCE=`）。不得為了通過檢查而虛報 N。
- clear 腳本 idempotent，無 marker 也安全。
- 防 brick 由既有三層負責，不需為此放寬上述條件：marker 逾 4 小時自動清除（`commit-gate-guard.ts`）、Stop hook per-session 有界計數（`MAX_STOP_BLOCKS=3`）、手動執行上述腳本（權威解鎖方式）。

### 6. Feedback memory（Tier 2/3）
review 發現的問題若是**本次自己寫出來的壞習慣**（非既有代碼）→ 依 `~/.claude/harness/knowledge-protocol.md` §2 存 feedback memory。

### 7. 通知（所有 Tier 必跑）
`osascript -e 'display notification "commit 與 review 完成" with title "commit review（Tier N）"'`

## 禁止事項（引 policy）
- 不得為了少跑步驟而故意拆 commit 規避分級。
- Tier 判定有疑義時就近向上取嚴。
- review 修出的改動一律 amend 或留 uncommitted，不自行開新 commit。
