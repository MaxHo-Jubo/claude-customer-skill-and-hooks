---
name: commit-review
description: "Commit 後分級 review chain（Tier 0~3）。被動由 post-commit hook 指派，也可手動 /commit-review [target] 對任意 commit 補跑。當使用者提到 /commit-review、「跑 review」、「補跑 review」、「review 這個 commit」、「push 前 review」時觸發。不適用於：PR 級完整審查（用 /pr-review-toolkit:review-pr）、需求驗收（用 /jira-acceptance）。"
version: 1.0.0
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
3. pr-reviewer agent（lite 模式）。
4. 修 CRITICAL 問題 → `git commit --amend`（不另開新 commit）。
5. Blast radius（§4）。
6. §7 通知。

**Tier 3 大改動** — Tier 2 全部，外加：
1. `/pr-review-toolkit:review-pr code comments errors tests types`。
2. 修 Critical / Important（不另 commit，amend 或留 uncommitted）。
3. Blast radius（§4）。
4. §7 通知。

### 4. Blast radius（Tier 2/3 必跑）
依 commit-review-policy.md「Blast Radius 分析」節執行：codebase-memory-mcp 對本次改動 symbol 跑 `trace_path`(inbound)。資訊性輸出、不自動改；揭露遺漏 caller 回報 user；project 未索引 → 標「impact 未取得」跳過；注意「方法當 callback 參照傳遞」盲區，callers 回空需 grep 補查。

### 5. 解鎖 marker（有 pending-review marker 時）
review 完成、Critical 處理完後，若該 repo 仍有 marker：
`bun ~/.claude/scripts/clear-pending-review.ts`
- 被動模式 Tier 2/3：pr-reviewer 完成時 SubagentStop hook 通常已自動清，本步為安全網。
- 手動模式：SubagentStop 同樣會在 review agent 完成時觸發清除；若未觸發（未 spawn review agent），此步手動補清。
- clear 腳本 idempotent，無 marker 也安全。

### 6. Feedback memory（Tier 2/3）
review 發現的問題若是**本次自己寫出來的壞習慣**（非既有代碼）→ 依 `~/.claude/harness/knowledge-protocol.md` §2 存 feedback memory。

### 7. 通知（所有 Tier 必跑）
`osascript -e 'display notification "commit 與 review 完成" with title "commit review（Tier N）"'`

## 禁止事項（引 policy）
- 不得為了少跑步驟而故意拆 commit 規避分級。
- Tier 判定有疑義時就近向上取嚴。
- review 修出的改動一律 amend 或留 uncommitted，不自行開新 commit。
