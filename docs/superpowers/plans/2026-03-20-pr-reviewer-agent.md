# pr-reviewer Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `~/.claude/agents/pr-reviewer.md`，逐條比對 CODE-REVIEW-RULE.md 並產出結構化 review 報告，支援 lite/full 兩種模式。

**Architecture:** 單一 agent markdown 檔案，透過 prompt 參數切換模式。Lite 模式單 agent 比對 + Haiku 信心評分；Full 模式 5 平行 Sonnet agent + Haiku 信心評分。規範來源為外部檔案 CODE-REVIEW-RULE.md（讀檔不嵌入）。

**Tech Stack:** Claude Code agent system（`.claude/agents/*.md`）、jq（diff 解析）、gh CLI（Full 模式 PR 操作）

**Spec:** `docs/superpowers/specs/2026-03-20-pr-reviewer-agent-design.md`

---

## File Structure

| 動作 | 路徑 | 職責 |
|------|------|------|
| Create | `~/.claude/agents/pr-reviewer.md` | Agent 定義（frontmatter + 完整 prompt） |
| Create | `~/.claude/agents/README-pr-reviewer.md` | Spec 文件副本，作為 agent 說明文件 |

---

### Task 1: 建立 agents 目錄與 agent 骨架

**Files:**
- Create: `~/.claude/agents/pr-reviewer.md`

- [ ] **Step 1: 建立目錄**

```bash
mkdir -p ~/.claude/agents
```

- [ ] **Step 2: 寫入 agent frontmatter + 基礎結構**

建立 `~/.claude/agents/pr-reviewer.md`，內容包含：

```markdown
---
name: pr-reviewer
description: >
  Code review agent — 逐條比對 CODE-REVIEW-RULE.md 並產出結構化報告。
  預設 lite 模式（單 agent + Haiku 信心評分），可切換 full 模式（5 平行 agent，移植自 CI workflow）。
  觸發方式：POST-COMMIT-REVIEW 自動觸發（lite）或手動指定 PR（full）。
tools: ["Read", "Grep", "Glob", "Bash", "Agent"]
model: sonnet
---
```

加上以下 sections 的 placeholder：
- 模式判斷邏輯
- CODE-REVIEW-RULE.md 載入
- Lite 模式流程
- Full 模式流程
- 信心評分指引
- 品質評分指引
- 輸出格式
- 邊界情況處理
- 語言規則

- [ ] **Step 3: 驗證 agent 可被 Claude Code 發現**

```bash
# 在任意 repo 目錄下啟動 claude，確認 pr-reviewer 出現在可用 agent 列表
```

- [ ] **Step 4: Commit**

```bash
cd ~/Documents/projects/claude-customer-skill-and-hooks
git add docs/superpowers/specs/2026-03-20-pr-reviewer-agent-design.md
git add docs/superpowers/plans/2026-03-20-pr-reviewer-agent.md
git commit -m "docs: 新增 pr-reviewer agent spec 與 implementation plan"
```

---

### Task 2: 撰寫模式判斷與 CODE-REVIEW-RULE.md 載入邏輯

**Files:**
- Modify: `~/.claude/agents/pr-reviewer.md`

- [ ] **Step 1: 撰寫模式判斷區段**

agent prompt 開頭的模式判斷邏輯：

```markdown
## 模式判斷

1. 解析使用者 prompt，判斷模式：
   - 包含 `mode: full` + PR 資訊（number 或 URL）→ Full 模式
   - 其他所有情況 → Lite 模式（預設）
2. 確認當前目錄是 git repo（`git rev-parse --is-inside-work-tree`），否則報錯終止
```

- [ ] **Step 2: 撰寫 CODE-REVIEW-RULE.md 載入邏輯**

```markdown
## 載入規範文件

依序尋找 CODE-REVIEW-RULE.md：
1. 當前 repo 根目錄（`git rev-parse --show-toplevel`）的 CODE-REVIEW-RULE.md
2. ~/.claude/CODE-REVIEW-RULE.md（全域 fallback）

找不到 → 輸出錯誤訊息並終止：「找不到 CODE-REVIEW-RULE.md，請確認檔案位置」

找到後用 Read tool 讀取完整內容，作為後續比對的規範來源。
```

- [ ] **Step 3: 撰寫檔案過濾規則**

```markdown
## 檔案過濾

從 diff 中排除以下檔案類型，不進行 review：
- *.md（Markdown）
- *.json（JSON config）
- *.yml / *.yaml（YAML config）

若過濾後無剩餘檔案 → 輸出「無需 review 的程式碼改動」並提前退出。
```

---

### Task 3: 撰寫 Lite 模式完整流程

**Files:**
- Modify: `~/.claude/agents/pr-reviewer.md`

- [ ] **Step 1: 撰寫 Lite 模式 diff 取得**

```markdown
## Lite 模式

### STEP 01: 取得 diff

執行 `git diff-tree --no-commit-id -r -p HEAD` 取得最近一次 commit 的 diff。
套用檔案過濾規則，排除非程式碼檔案。
```

- [ ] **Step 2: 撰寫 Lite 模式逐條比對邏輯**

```markdown
### STEP 02: 逐條比對 CODE-REVIEW-RULE.md

讀取 CODE-REVIEW-RULE.md 的每一條規則，對 diff 逐一檢查：

對每條規則：
1. 理解規則要求（例如「if 語句必須有大括號」）
2. 掃描 diff 中所有新增/修改的行
3. 判斷是否有違反
4. 若違反：記錄 issue（問題描述 + 違反的規則 + 檔案路徑:行號）

規則清單（必須全部檢查，不可跳過）：
- if 語句大括號
- 不可變性（禁止 mutation）
- 禁止 console.log
- 禁止 Magic Number
- 安全性（hardcoded secrets、log 敏感資料）
- 錯誤處理（async/await + try-catch、null safety）
- 變數與常數註解
- 函式與方法註解（JSDoc）
- STEP 格式註解
- 註解正確性（邏輯與註解一致、無錯字）
- 全域變數修改搜尋使用點
- React 規則（memo/useCallback/useMemo、useEffect cleanup）
- React Native 規則（FlatList、StyleSheet.create）
```

- [ ] **Step 3: 撰寫 Haiku 信心評分 dispatch 邏輯**

```markdown
### STEP 03: 信心評分

對每個找到的 issue，啟動一個 Haiku agent 進行信心評分：

Haiku agent prompt：
「你是 code review 信心評分員。根據以下資訊，評估這個 issue 是真問題還是 false positive，給出 0-100 的信心分數。

量尺：
- 0: 完全不可信，false positive 或既有問題
- 1-39: 低信心，可能是 false positive
- 40-59: 中等信心，可能是真問題但也可能是 nitpick
- 60-79: 高信心，很可能是真問題
- 80-89: 非常高信心，已驗證的真問題
- 90-100: 確定，確認的真問題

以下情況應給低分：
- 既有問題（非本次 diff 引入）
- Linter/typechecker/compiler 會抓的
- 一般品質意見（除非規則文件明確要求）
- 明顯有意為之的功能變更
- 非修改行的問題

輸入：
- diff context: {相關 diff 片段}
- issue 描述: {issue 內容}
- 違反規則: {CODE-REVIEW-RULE.md 相關條目}

只回傳一個 JSON: {"score": <0-100>, "reason": "<一句話說明>"}」

Haiku agent 失敗時 fallback：該 issue 歸入 INFO，附註「信心評分失敗」。
```

- [ ] **Step 4: 撰寫分類與品質評分**

```markdown
### STEP 04: 分類

根據信心分數分類：
- ≥90 → CRITICAL
- 80-89 → MINOR
- <80 → INFO

### STEP 05: 品質評分

對 diff 整體進行 6 項品質評分（每項 1-5，滿分 30）：
1. Magic Number — 未經解釋的數字常數
2. 邏輯與註解一致性 — 程式邏輯與註解是否相符
3. 函式註解 — JSDoc 完整度
4. 變數/常數/props/state 註解 — 用途說明
5. 註解錯字 — 有無錯字
6. 系統穩定性 — crash 風險

分數意義：5=完美 4=不錯 3=還可以 2=不好 1=拒絕接受
```

---

### Task 4: 撰寫 Full 模式完整流程

**Files:**
- Modify: `~/.claude/agents/pr-reviewer.md`

- [ ] **Step 1: 撰寫 Full 模式前置步驟**

```markdown
## Full 模式

### STEP 01: 解析 PR 資訊

從使用者 prompt 取得 PR number 或 URL，統一用以下方式取得 PR number：
`gh pr view <input> --json number --jq '.number'`

失敗 → 報錯終止：「無法取得 PR 資訊，請確認 PR number 或 URL」

### STEP 02: 檢查 PR 狀態（前置）

啟動 Haiku agent 執行：
`gh pr view <PR_NUMBER> --json state,mergedAt,isDraft`

- mergedAt 非 null → 「PR 已 merge，跳過 review」→ 終止
- state 為 CLOSED → 「PR 已關閉，跳過 review」→ 終止
- isDraft 為 true → 「PR 為 draft，跳過 review」→ 終止

### STEP 03: 產出 Change Summary

啟動 Haiku agent 讀取 PR diff（`gh pr diff <PR_NUMBER>`），回傳：
- PR 目的摘要（1-2 句）
- 主要修改的檔案與模組
- 改動類型（feat/fix/refactor/etc.）

此 summary 作為後續 5 個 Sonnet agent 的共享上下文。
```

- [ ] **Step 2: 撰寫 5 平行 Sonnet agent 定義**

```markdown
### STEP 04: 平行 Review（5 Sonnet agents）

同時啟動 5 個 Sonnet agent，每個 agent 都接收：change summary + PR diff + 檔案過濾規則。

**Agent #1: CODE-REVIEW-RULE.md 逐條合規**
與 Lite 模式 STEP 02 相同邏輯，逐條比對規則文件。
回傳：issues list（問題描述 + 違反規則 + 檔案:行號）

**Agent #2: Shallow Bug Scan**
只看 diff 內容，不讀額外上下文。聚焦大型 bug：
- 邏輯錯誤
- null/undefined 未處理
- race condition
- 安全漏洞
避免小問題和 nitpick。忽略可能的 false positive。
回傳：issues list

**Agent #3: Git Blame Historical Context**
讀取被修改檔案的 git blame 和歷史（`git log --follow -p`），
找出歷史上下文可能揭露的 bug。
回傳：issues list

**Agent #4: Previous PR Comments**
查找修改檔案的過去 PR（`gh pr list --state merged --search`），
檢查過去 PR 的留言是否也適用於當前 PR。
回傳：issues list

**Agent #5: Code Comments Compliance**
讀取被修改檔案中的程式碼註解，
確認 PR 的改動是否符合註解中的指引和約定。
回傳：issues list
```

- [ ] **Step 3: 撰寫 Full 模式後置步驟**

```markdown
### STEP 05: 信心評分

合併 5 個 agent 的所有 issues，去重後對每個 issue 啟動 Haiku agent 評分。
（評分邏輯同 Lite 模式 STEP 03）

5 個 agent 其中一個失敗 → 仍輸出 partial result，附註哪個面向失敗。

### STEP 06: 分類與品質評分

同 Lite 模式 STEP 04 + STEP 05。

### STEP 07: 確認 PR 狀態（後置）

啟動 Haiku agent 再次確認：
`gh pr view <PR_NUMBER> --json state,mergedAt`

- 已 merge 或 close → 「PR 在 review 期間已關閉/merge，跳過輸出」→ 終止
- 仍 OPEN → 繼續輸出報告
```

---

### Task 5: 撰寫輸出格式與語言規則

**Files:**
- Modify: `~/.claude/agents/pr-reviewer.md`

- [ ] **Step 1: 撰寫輸出格式模板**

完整的結構化輸出模板，包含：
- Code Review Results（CRITICAL / MINOR / INFO 三個區塊）
- 每個 issue 帶：問題描述 + 原因 + 信心分數 + 檔案:行號
- Quality Score 表格（6 項 + 總分）
- 若該分類無問題顯示「無」

- [ ] **Step 2: 撰寫語言規則**

```markdown
## 語言規則

- 內部運算（agent 之間溝通、工具呼叫）用英文
- 所有最終輸出用繁體中文
- 檔案路徑、code identifier、技術術語維持英文
```

---

### Task 6: 組裝完整 agent 檔案並驗證

**Files:**
- Modify: `~/.claude/agents/pr-reviewer.md`

- [ ] **Step 1: 組裝所有區段為完整 agent markdown**

將 Task 2-5 撰寫的所有區段組裝成一個完整的 `pr-reviewer.md`。
確認結構完整：frontmatter → 模式判斷 → 載入規範 → 檔案過濾 → Lite 流程 → Full 流程 → 信心評分 → 品質評分 → 輸出格式 → 邊界情況 → 語言規則。

- [ ] **Step 2: Lite 模式驗證**

在有 CODE-REVIEW-RULE.md 的 repo 目錄下，commit 一個測試改動後手動呼叫：
「使用 pr-reviewer agent，review 最近一次 commit」

確認：
- 能讀到 CODE-REVIEW-RULE.md
- 逐條比對有結果
- Haiku 信心評分有回傳
- 輸出格式正確（CRITICAL/MINOR/INFO + Quality Score）
- 語言為繁體中文

- [ ] **Step 3: Full 模式驗證**（如果有可用的 PR）

「使用 pr-reviewer agent，mode: full，review PR #<number>」

確認：
- PR 狀態檢查正常
- Change summary 產出
- 5 平行 agent 都有回傳
- 信心評分正常
- 後置 PR 狀態確認正常
- 輸出格式正確

- [ ] **Step 4: 邊界情況驗證**

測試至少一個邊界情況：
- 在無 CODE-REVIEW-RULE.md 的目錄執行 → 應報錯終止
- 空 diff（只改 .md 檔）→ 應輸出「無需 review」

---

### Task 7: 建立 README 並 commit

**Files:**
- Create: `~/.claude/agents/README-pr-reviewer.md`

- [ ] **Step 1: 複製 spec 為 README**

將 `docs/superpowers/specs/2026-03-20-pr-reviewer-agent-design.md` 複製為 `~/.claude/agents/README-pr-reviewer.md`。

- [ ] **Step 2: Commit agent 與 README**

注意：`~/.claude/agents/` 不在 git repo 裡，不需要 commit。
但需要用 `/sync-my-claude-setting` 將本機設定同步到 repo 備份。

- [ ] **Step 3: 更新 project memory**

更新 `project_compliance_checker_plan.md`，標記 pr-reviewer agent 已建立，CI workflow 退役計畫進入下一階段。
