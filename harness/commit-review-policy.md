# Commit 後審查分級制（POST-COMMIT-REVIEW v2） | status: DONE

> 取代舊版「每次 commit 強制六步」規則（舊版全文見 `~/.claude/CLAUDE.md.bak-20260703`）。
> 設計依據：舊制與 diff 大小無關，改 3 行也跑 6~10 個 agent（M4 機器診斷實測，見 repo `max-m4pro-setting` 分支 harness-diagnosis.md §3）。
> 讀者：主對話模型。觸發時機：用 Bash 成功執行 `git commit` 之後。
> 建立：Fable 5，2026-07-03（M4 機器）；本機化：Sonnet 5，2026-07-03（Tier 2/3 加入 blast radius 步驟）。維護權限：黃區。

## 免跑條件（任一成立 → 只執行通知步驟）

- commit 指令本身包含 push，或 user 說「commit and push」
- 空 commit / commit 失敗
- amend 既有 commit 且新增 diff < 10 行

## 分級判定（機械執行，不憑感覺）

先跑：`git diff --numstat --no-renames <ref>~1 <ref>`（預設 `<ref>` = HEAD）取得檔案清單與增刪行數，再依下表由上而下取**第一個**命中的 Tier：

| Tier | 判準（由上而下先命中先用） | 執行步驟 |
|------|--------------------------|---------|
| **0 純文件** | 全部檔案皆為 `.md .html .txt .png .jpg .jpeg .svg .csv`（文件/圖片/資料） | 只發通知 |
| **3 敏感路徑** | 動到公共 API / 共用 lib / 資料模型（`models/`、`lib/`、`shared/`、`routes/middlewares/`、`base{controller,bean,model}`）——**不論改動大小，須先於尺寸判定** | commit-review skill |
| **1 小改動** | 程式碼變更 ≤ 50 行 且 ≤ 2 個程式碼檔 | commit-review skill（不 spawn agent） |
| **2 標準** | 程式碼變更 ≤ 300 行 且 ≤ 5 個程式碼檔 | commit-review skill |
| **3 大改動** | 超過 Tier 2 門檻 | commit-review skill |

- 「程式碼檔」= 非 Tier 0 副檔名清單的檔案。副檔名比對用 basename 的最後一段，`CLAUDE.md.20260720` 這類日期後綴備份仍視為文件。
- **敏感路徑先於尺寸**：對 `models/user.js` 改 3 行若先命中 Tier 1，就會漏掉高 blast radius 的 review，故此列必須排在 Tier 1/2 之前。實作（`scripts/lib/tier.ts`）即依此順序。
- **rename 用 `--no-renames`**：git 預設把 rename 輸出成 `old => new` 或 `dir/{a => b}/x.ts` 合併形式，敏感路徑 regex 會漏判「把檔案搬進 `lib/`」這種高風險操作；`--no-renames` 拆成 delete + add 兩列即可正確命中。
- **執行步驟權威定義在 commit-review skill**（`skills/commit-review/SKILL.md`）：eslint / `/simplify` / pr-reviewer / review-pr / blast radius / 通知 / feedback memory 各 Tier 的完整鏈在該 skill；本表僅保留分級判準，兩者勿重複。
- **手動補跑**：`/commit-review [target]`（預設 HEAD，可帶 `HEAD~3` / `<hash>`）——用於 marker 逾期、想重跑、push 前主動 review。

## 自動強制機制（pending-review 閘門，2026-07-16 建立）

> 沿革：舊版只靠 PostToolUse 印 systemMessage「提醒」跑 review，無強制力——主 agent 收到提醒後可以無視、直接開下一個 commit（ERPD-11970 b4eee29e0e 即如此，Tier 2/3 的 review 被整段跳過）。現改為 hook 機械判定 + 硬性 deny 的 fail-closed 閘門，不再依賴自覺。

Tier 判定與閘門由三個 hook 自動執行，主 agent **不需**再自己讀本表憑感覺分級：

1. **PostToolUse（`scripts/post-commit-review.ts`）**：git commit 成功後用 `git diff --numstat` 機械算 Tier（敏感路徑判定先於尺寸判定；判定邏輯抽在 `scripts/lib/tier.ts`）。Tier 2/3 寫一個 marker 檔到 `~/.claude/state/pending-review/<repo>.json`，並以 systemMessage 指派主 agent 執行 commit-review skill 跑對應 chain（hook 不再列舉步驟）。
2. **PreToolUse Bash（`hooks/commit-gate-guard.ts`）**：該 repo 有未清 marker 時，**deny 新的 git commit**，強制先完成 review。放行 `--amend` / `push` / commit message 含 `[skip-review]`；marker 逾 4 小時自動清除放行（避免 brick）。
3. **SubagentStop（`hooks/subagent-review-clear.ts`）**：review 類子 agent（`agent_type` 含 review）完成時自動清除 marker。**手動 `bun ~/.claude/scripts/clear-pending-review.ts` 仍是權威解鎖方式。**

三個 hook 共用 `scripts/lib/review-marker.ts`（marker 路徑、`git -C`/`cd` 跨 repo 目標解析、`isGitCommitCommand` 指令偵測）；Tier 判定共用 `scripts/lib/tier.ts`，與 commit-review skill 手動模式（`scripts/compute-tier.ts`）同一份，確保被動／手動判定不分歧。所有 hook 失敗一律 fail-open，不因自身錯誤誤擋正常 commit。手動解鎖：`bun ~/.claude/scripts/clear-pending-review.ts`。

## Blast Radius 分析（Tier 2/3 必跑；資訊性輸出，不自動修改）

用 codebase-memory-mcp 對本次 commit 修改的 symbol 執行影響面分析：

1. `git diff HEAD~1` 抓改動函式清單
2. 逐一 `trace_path`(direction: inbound, risk_labels: true) 查詢 caller 與影響面
3. project 未索引（`list_projects` 確認）→ 標註「impact 未取得」並跳過，不硬跑
4. 揭露遺漏 caller / 影響面時回報給 user，由人工決定是否補 commit
5. **盲區警告**：`trace_path` 對「方法當 callback 參照傳遞」（React class method 綁定後當 prop 傳出、Redux dispatch 等間接呼叫）抓不到——callers 回空不能當「無人呼叫」結論，此類 case 需用 grep 補查（model-dispatch.md §6 graph-first 規則）

## 範例

- 「docs: 補進度報告 HTML」改 2 個 .html → **Tier 0**，只通知。
- 「fix: debounce 門檻 50→80ms」改 1 檔 3 行 → **Tier 1**，eslint（無設定跳過）＋自查 bugfix DoD＋通知。
- 「feat: 班表頁新增請假狀態篩選」改 3 檔 180 行 → **Tier 2**。
- 「refactor: ApiResponse envelope 改版」動共用 lib → **Tier 3**（就算只有 80 行，資料模型 = 公共 API 判準命中）。

## 禁止事項

- 不得為了少跑步驟而故意拆 commit 規避分級（一個邏輯變更拆成 10 個 Tier 1 commit = 違規）。
- Tier 判定有疑義時就近**向上**取嚴（寧可多跑一級）。
- pr-reviewer / review-pr 修出來的改動一律 amend 或留 uncommitted，不得自行開新 commit。
