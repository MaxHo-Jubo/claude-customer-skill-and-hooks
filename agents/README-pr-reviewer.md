# pr-reviewer 架構說明

逐條比對 `CODE-REVIEW-RULE.md` 的 code review 機制，取代 `luna_web/.github/workflows/claude-code-review.yml`。

**v2.0.0（2026-08-13）起拆為兩個入口**，判定標準共用同一份規範檔。

## 三個檔案的分工

| 檔案 | 角色 | 觸發 |
|------|------|------|
| `~/.claude/skills/pr-reviewer/references/review-spec.md` | **判定標準唯一出處**：17 條規則、慣例優先原則、信心評分 prompt、分類閾值、品質評分、輸出格式、語言規則 | 兩個入口都 Read 它 |
| `~/.claude/skills/pr-reviewer/SKILL.md` | **full 模式**：PR 5 面向平行 review + 信心評分 + 自動 post 到 GitHub PR | `/pr-reviewer`、`Skill(pr-reviewer)`、`scripts/review-pr.sh <PR>` |
| `~/.claude/agents/pr-reviewer.md` | **lite 模式**：對 HEAD commit 單 agent 逐條合規審查 | commit-review skill 的 Tier 2/3 chain |

**改判定標準只改 `review-spec.md`**。SKILL.md 與 agent 只寫各自的執行步驟，不複製規則內容。

## 為什麼 full 是 skill、lite 是 agent

**full → skill**：需要 fan-out 5 個面向再收斂。v1.x 把它包在 subagent 內、由該 subagent 再 spawn 子 agent，形成巢狀 orchestrator，結果全押在 task-notification 跨兩層回流。三次實測三種結果：

| 日期 | 案例 | 子 agent 參數 | 結果 |
|------|------|--------------|------|
| 2026-08-07 | PR 10953 | 不帶 name | 5 個全回流，耗時 22 分鐘 |
| 2026-08-06 | PR 10949 | 不帶 name | 結果沒回到 pr-reviewer，繞道 team-lead 轉述 |
| 2026-08-13 | PR 10983 | 帶 name | 全數落空，parent 自行重做五個面向後照常輸出 |

改由主 session 直接 orchestrate（巢狀深度 2→1），走最可靠的回流路徑，且每個 STEP 有進度回報。詳見 SKILL.md 文末。

**lite → 留在 agent**：commit 後自動觸發需要 context 隔離（不污染主 session）。

> 2026-08-17 修正：原本第二個理由是「`subagent-review-clear.ts` 依賴 agent 型別含 `review` 自動清 pending-review marker」——該 hook 已停止清除職責（Tier 3 並行時第一個完成的 agent 就會提前解鎖閘門），marker 改由 commit-review skill §5 顯式清除。**context 隔離是 lite 留在 agent 的唯一理由。**

## full 模式流程

```
STEP 01  解析 PR + 狀態檢查（Bash，不 spawn agent）
STEP 02  gh pr diff 落檔，5 個 agent 共讀一份
STEP 03  change summary（主 session 自己讀 diff）
STEP 04  5 個面向 agent（同一則訊息、不帶 name）
           #1 CODE-REVIEW-RULE.md 逐條合規
           #2 shallow bug scan（只看 diff）
           #3 git blame historical context
           #4 previous PR comments
           #5 code comments compliance
STEP 05  去重 + 批次信心評分（Haiku，3-5 issue/agent）
STEP 06  分類（≥90 CRITICAL / 80-89 MINOR / <80 INFO）+ 品質評分
STEP 07  確認 PR 仍 OPEN（Bash）
STEP 08  terminal 輸出 + post 到 GitHub（summary review + inline Suggested Change）
STEP 09  清理 diff 暫存檔
```

v1.x 的 STEP 02/03/07 各 spawn 一個 Haiku agent，v2.0.0 改為直接跑 Bash，省掉 3 輪 agent 往返。

## lite 模式流程

```
STEP 01  git diff-tree HEAD 取 diff + 檔案過濾
STEP 02  逐條比對 17 條規則（強制套用慣例優先原則）
STEP 03  信心評分（Haiku 批次，不帶 name）
STEP 04  分類
STEP 05  品質評分
STEP 06  輸出報告（不產 inline comment、不 post GitHub）
```

## 兩個入口共通的硬規則

1. **Agent call 一律不得帶 `name`** — 帶了結果不回流，`SendMessage` 索取只拿得到「已排入佇列」確認。用 `description` 區分用途。
2. **平行 = 同一則訊息內發多個 Agent call**，發完該輪立即結束等 notification，收齊前禁止產出報告。
3. **拿不到結果必須 fail loud** — 禁止自己補做該面向後當它成功，必須在報告**開頭**標明降級 N/5。

## 與其他 review 工具的關係

| 工具 | 定位 |
|------|------|
| pr-reviewer（本檔） | 公司規範逐條合規 + 結構化評分 |
| `/pr-review-toolkit:review-pr` | 通用品質/bug/設計（AI 判斷優先） |
| `/code-review` | Claude Code 內建，correctness + 簡化建議 |

pr-reviewer 與 pr-review-toolkit 並行互補，commit-review skill 的 Tier 3 兩者都跑。

## 已知限制

- 不檢查 CLAUDE.md 合規（刻意；各專案尚未完全導入 CLAUDE.md）。規範來源僅 CODE-REVIEW-RULE.md。
- 不處理 `@claude` 留言觸發、不處理 Auto-sync PR 排除（本機不需要）。
- `review-pr.sh` 走 `claude -p` 非互動模式並用 `~/.claude-review` 隔離帳號省額度。**該路徑下子 agent 結果能否回流尚未實測**；v2 已加 watchdog 逾時與進度心跳，失敗時會揭露完整 log 而非靜默。互動 session 直接 `/pr-reviewer <PR>` 是已驗證可靠的路徑。
