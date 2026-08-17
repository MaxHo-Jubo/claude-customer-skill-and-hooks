---
name: pr-reviewer
description: "PR full review — 5 個面向平行審查 + 信心評分 + 自動 post 到 GitHub PR（summary review + inline Suggested Change）。逐條比對 CODE-REVIEW-RULE.md。當使用者提到 /pr-reviewer、「review 這個 PR」、「full review」、「審 PR 1234」、想對某個 PR 做完整審查並貼回 GitHub 時觸發。不適用於：commit 後的分級 review（用 /commit-review，內部走 lite agent）、通用品質審查（用 /pr-review-toolkit:review-pr）。"
version: 2.0.0
last_modified: 2026-08-13
---

# pr-reviewer（full 模式）

對指定 PR 做 5 面向平行 review，結果 post 回 GitHub PR。

**規範來源**：`~/.claude/skills/pr-reviewer/references/review-spec.md`（判定標準、信心評分、輸出格式的唯一出處，與 lite agent 共用）。開工前先 Read 它。

## 執行拓撲（v2.0.0 起；改動原因見文末）

本流程由**主 session 直接 orchestrate**，不再包一層 pr-reviewer subagent。

```
主 session（你）
  ├─ STEP 01/02/03/07  直接跑 Bash，不 spawn agent
  └─ STEP 04           同一則訊息 spawn 5 個 agent（depth 0→1）
     STEP 05           同一則訊息 spawn 1-2 個批次評分 agent
```

### 兩條硬規則（違反則結果拿不回來）

1. **所有 Agent call 一律不得帶 `name` 參數。** 帶 `name` 的 agent 結果不會自動回流，`SendMessage` 索取只拿得到「已排入佇列」確認。需要區分用途用 `description`（如 `description: "rules compliance"`）。
2. **平行 = 多個 Agent call 放在同一則訊息內。** 發完該輪立即結束，等 task-notification 逐一送回結果；未收齊就再次結束該輪繼續等。**收齊全部子 agent 結果之前，禁止產出報告。**

### 失效時必須 fail loud

若最終仍有子 agent 結果沒回來：

- **禁止自己重做該面向的分析後照常輸出報告。** 那會把機制失效偽裝成正常結果，使用者無從得知這份 review 實際上是單 agent 跑出來的。
- 必須在報告**最開頭**（不是結尾附註）標明：「Full 模式降級：N/5 個面向未回傳（列出面向名稱），以下結論不具備 5 路交叉驗證」。
- 已回來的面向照常處理，不因此丟棄。

### 進度回報（強制）

每個 STEP 開始前印一行進度給使用者，例如 `▶ STEP 04：spawn 5 個面向 agent（預計 3-6 分鐘）`。
整套流程通常需 5-15 分鐘，沉默等待會被誤判為當機——**不得整段靜默執行**。

## STEP 01: 解析 PR 並前置檢查

一次 Bash 取齊，不要為此 spawn agent：

```bash
gh pr view <input> --json number,state,mergedAt,isDraft,title,url
```

失敗 → 輸出錯誤並終止：「無法取得 PR 資訊，請確認 PR number 或 URL」

判斷：

- `mergedAt` 非 null → 輸出「PR 已 merge，跳過 review」→ 終止
- `state` 為 `CLOSED` → 輸出「PR 已關閉，跳過 review」→ 終止
- `isDraft` 為 `true` → 輸出「PR 為 draft，跳過 review」→ 終止

注意：`state: "OPEN"` + `mergeStateStatus: "BLOCKED"` 代表仍開放等待審核，不是關閉。

同時確認在 git repo 內（`git rev-parse --is-inside-work-tree`），否則終止：「不在 git repo 內，無法執行 review」。

## STEP 02: 取 diff 並落檔

diff 直接塞進 5 個子 agent 的 prompt 會重複佔用 context，落檔改傳路徑：

```bash
DIFF_FILE=$(mktemp -t pr-diff-XXXXXX.diff)
gh pr diff <PR_NUMBER> > "$DIFF_FILE"
wc -l "$DIFF_FILE"
```

套用 `references/review-spec.md` 的檔案過濾規則（排除 `*.md`、`*.json`、`*.yml`、`*.yaml`）。
若過濾後無剩餘程式碼檔案 → 輸出「無需 review 的程式碼改動」並提前退出。

記下 `$DIFF_FILE` 路徑，STEP 04 的 5 個 agent 都讀這一份。

## STEP 03: 產出 Change Summary

自己讀 `$DIFF_FILE`（必要時只讀檔案清單與關鍵 hunk）產出：

- PR 目的摘要（1-2 句）
- 主要修改的檔案與模組
- 改動類型（feat/fix/refactor/etc.）

此 summary 作為 STEP 04 的共享上下文，寫進每個子 agent 的 prompt。

## STEP 04: 平行 Review（5 個 agent，同一則訊息）

在**同一則訊息**內發出 5 個 Agent call，**都不帶 `name`**。每個 prompt 都必須含：

- repo 絕對路徑
- `$DIFF_FILE` 絕對路徑（要求 agent 自己 Read）
- STEP 03 的 change summary
- 檔案過濾規則
- **回報格式限制**：issues list，每則含「問題描述 + 違反規則 + `檔案:行號` + 慣例統計（grep 指令與比例）」；引用超過 20 行的程式碼一律改寫成 `路徑:起-迄行號`，禁止貼大段程式碼

**Agent #1: CODE-REVIEW-RULE.md 逐條合規**（`description: "rules compliance"`）
讀取 `references/review-spec.md` 全部 17 條規則，對 diff 逐一檢查。
**強制套用「慣例優先原則」**：風格類規則必須先執行 grep 慣例統計，與主流慣例一致的不記錄；規則 9/10/11 命中全新建立的檔案時套用「新增檔案例外」，跳過慣例檢查、違反即記錄。

**Agent #2: Shallow Bug Scan**（`description: "shallow bug scan"`）
只看 diff 內容，不讀額外上下文。聚焦大型 bug：邏輯錯誤、null/undefined 未處理、race condition、安全漏洞、記憶體洩漏。
避免小問題和 nitpick，忽略可能的 false positive。

**Agent #3: Git Blame Historical Context**（`description: "git history"`）
讀取被修改檔案的 git blame 與歷史（`git log --follow -p -- <file>`），在歷史上下文中找出可能的 bug（例如某函式原本有特定邏輯但被移除了）。

**Agent #4: Previous PR Comments**（`description: "previous PR comments"`）
查找修改檔案的過去 PR（`gh pr list --state merged --search "<filename>"`），檢查過去 PR 的留言是否也適用於當前 PR。

**Agent #5: Code Comments Compliance**（`description: "code comments"`）
讀取被修改檔案中的既有程式碼註解（TODO、FIXME、HACK、特定指引），確認 PR 改動是否符合這些註解中的指引與約定。

發完這 5 個 call 後**該輪立即結束**，等 task-notification 送回結果。

失敗處理（三種都要當成失敗，不可當空結果放過）：

- agent 回報錯誤 → 記為該面向失敗
- agent 回傳 `null`（被使用者跳過，或重試後仍終止）→ 記為該面向失敗
- **結果始終沒回流**（等不到該面向的 task-notification）→ 記為該面向失敗

三種都繼續處理其他 agent 的結果，並依「失效時必須 fail loud」在報告最開頭標明降級。禁止把失敗的面向當成「該面向沒有 issue」計入結論，也禁止自己補做該面向後當作它成功了。

## STEP 05: 去重與信心評分

合併 5 個 agent 的所有 issues，去除重複（同檔案同行號同性質視為重複，保留描述最完整者）。

依 `references/review-spec.md` §信心評分 啟動 Haiku agent 評分：

- 每個 agent 批次評 3-5 個 issue，多個 agent 放同一則訊息平行發出
- 同樣**不得帶 `name`**
- issue 少於 3 個時單次評完即可

## STEP 06: 分類與品質評分

依 `references/review-spec.md`：分類（≥90 CRITICAL / 80-89 MINOR / <80 INFO）+ 6 項品質評分（滿分 30）。

## STEP 07: 確認 PR 狀態（後置）

直接跑 Bash，不 spawn agent：

```bash
gh pr view <PR_NUMBER> --json state,mergedAt
```

- 已 merge 或 close → 輸出「PR 在 review 期間已關閉/merge，跳過輸出」→ 終止
- 仍 OPEN → 繼續

## STEP 08: 輸出報告 + 自動 Post 到 PR

必須同時做兩件事：terminal 結構化輸出 + post 到 GitHub PR。**禁止省略 post 步驟**，除非 STEP 07 已判定 PR 非 OPEN。

### Sub-step A: Terminal 輸出

按 `references/review-spec.md` §輸出格式 印出完整報告（品味評分 → Code Review Results → Quality Score → 結論 → INLINE_REVIEW_COMMENTS JSON）。

### Sub-step B: 取得 repo owner / name

```bash
gh repo view --json owner,name --jq '.owner.login + "/" + .name'
```

失敗 → 報錯：「無法取得 repo 資訊，無法 post 到 PR」，但仍保留 terminal 輸出。

### Sub-step C: 組 review body

review body 為單一 markdown 字串，依序拼接（用空行分隔）：

1. `## 品味評分` 區段（含表格）
2. `## Code Review Results` 三層（CRITICAL / MINOR / INFO）— 此處只列**沒有對應 inline comment** 的 issue（如架構建議、缺測試），有對應 inline comment 的 issue 移交給 inline comment 顯示，避免重複
3. `## Quality Score` 表格（必填，禁省略）
4. `## 結論` — 完整總評含品味分析 + merge 建議

無 issue（CRITICAL/MINOR/INFO 都空）時，Code Review Results 區段顯示「✅ 無發現問題」。

### Sub-step D: 決定 review event

- CRITICAL 數量 > 0 → `event=REQUEST_CHANGES`
- CRITICAL = 0 且 MINOR > 0 → `event=COMMENT`
- CRITICAL = 0 且 MINOR = 0（只有 INFO 或全清）→ `event=COMMENT`（不自動 APPROVE，由人決定）

### Sub-step E: Post review + inline comments

把 Sub-step A 產出的 INLINE_REVIEW_COMMENTS JSON 轉成 GitHub Review API 格式，與 review body 一起 post：

```bash
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/reviews \
  --method POST \
  --input - <<'EOF'
{
  "event": "<REQUEST_CHANGES | COMMENT>",
  "body": "<review body markdown>",
  "comments": [
    {
      "path": "src/foo.js",
      "line": 134,
      "start_line": 132,
      "side": "RIGHT",
      "body": "🔴 Critical — ...\n\n```suggestion\n...\n```"
    }
  ]
}
EOF
```

注意事項：

- `start_line` 只在多行建議時放；單行省略此欄位
- 行號必須落在 PR diff 的 hunk 範圍內，否則 GitHub API 會 422 reject
- 無 inline comments 時，`comments` 給空 array `[]`，仍要 post review body
- 多行 body 用 JSON 字串 escape（換行為 `\n`）；用 here-doc 餵 stdin 避免 shell escape 問題

post 成功 → terminal 印「✅ Review 已 post 到 PR #<NUMBER>」+ review URL（從 API response 取 `html_url`）。

post 失敗 → terminal 印「❌ Post 到 PR 失敗：<error>」並保留完整 terminal 輸出，不要 retry。常見失敗：

- 422：行號不在 diff hunk 範圍內 → 印出哪幾個 inline comment 行號超出範圍
- 403：沒有 review 權限 → 提示使用者檢查 `gh auth status`
- 404：PR 不存在 → 不該發生（STEP 01 已查過）

## STEP 09: 清理

刪除 STEP 02 的 `$DIFF_FILE`。

## 邊界情況

| 情況 | 行為 |
|------|------|
| CODE-REVIEW-RULE.md 找不到 | 報錯並終止 |
| diff 為空（只改 .md/.json/.yml 或 no-op commit） | 輸出「無需 review 的程式碼改動」並提前退出 |
| Haiku 評分 agent 失敗/timeout | 該 issue 歸入 INFO，附註「信心評分失敗」 |
| 5 個面向 agent 其中一個失敗或沒回流 | 輸出 partial result，報告**開頭**標明降級 N/5 |
| PR 不存在或無權限 | 報錯並終止 |
| 非 git repo 目錄 | 報錯並終止 |

## 為什麼是 skill 而不是 agent（v2.0.0 改動理由）

v1.x 把整套流程包在 `pr-reviewer` subagent 內，由該 subagent 再 spawn 5 個子 agent——**巢狀 orchestrator**，結果全押在 task-notification 能否跨兩層回流。三次實測三種結果：

| 日期 | 案例 | 子 agent 參數 | 結果 |
|------|------|--------------|------|
| 2026-08-07 | PR 10953 | 不帶 name | 5 個全回流，耗時 22 分鐘 |
| 2026-08-06 | PR 10949 | 不帶 name | 結果沒回到 pr-reviewer，繞道 team-lead 轉述 |
| 2026-08-13 | PR 10983 | 帶 name | 全數落空，parent 自行重做五個面向後照常輸出 |

且 `agent-apr-reviewer-*.meta.json` 顯示 pr-reviewer 自己是帶 `name` 被 spawn 的（`taskKind: in_process_teammate`）——最外層那次呼叫同樣拿不到結果。v1.3.0 花一整節要求一個不存在的參數（`run_in_background`），v1.4.0 改成花一整節要求模型「該輪主動結束什麼都別做」，兩版都是拿 prompt 約定去管非確定性的 harness 路由。

v2.0.0 改拓撲而非再加約定：主 session 直接 orchestrate，巢狀深度 2→1，走的是最常用也最可靠的回流路徑；前置/後置的 PR 狀態查詢與 change summary 從 3 個 Haiku agent 改為直接跑 Bash，砍掉 3 輪 agent 往返；每個 STEP 印進度，使用者不再面對整段靜默。

lite 模式仍留在 `~/.claude/agents/pr-reviewer.md`：commit 後自動觸發需要 context 隔離，且 SubagentStop hook 依賴 agent 型別自動清 pending-review marker。
