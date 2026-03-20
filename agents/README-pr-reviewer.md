# pr-reviewer Agent 設計文件

## 概述

將 `luna_web/.github/workflows/claude-code-review.yml` 的 review 邏輯移植到本機 agent，取代 CI workflow。

- **檔案位置**：`~/.claude/agents/pr-reviewer.md`
- **規範來源**：`CODE-REVIEW-RULE.md`（讀檔，不嵌入 prompt）
- **預設模式**：輕量版（lite）

## 兩種模式

### Lite（預設）

用途：POST-COMMIT-REVIEW，每次 commit 自動觸發。與 pr-review-toolkit 並行互補。

```
單 Sonnet agent 逐條比對 CODE-REVIEW-RULE.md
  → 每個 issue 各啟一個 Haiku agent 做信心評分（0-100）
  → CRITICAL(≥90) / MINOR(80-89) / INFO(<80) 分類
  → 6 項品質評分（滿分 30）
  → 輸出結構化報告
```

- diff 來源：`git diff-tree --no-commit-id -r -p HEAD`（處理 merge commit）
- token 消耗：低（1 Sonnet + N Haiku）
- 檔案過濾：跳過 `*.md`、`*.json`、`*.yml` 的改動

### Full

用途：PR review，手動觸發。單獨執行，不與 pr-review-toolkit 並行。

```
前置步驟：
  → Haiku agent 檢查 PR 狀態（merged/closed/draft → 中止）
  → Haiku agent 產出 PR change summary（供後續 agent 共享）

5 平行 Sonnet agent（共享 change summary）：
  #1 CODE-REVIEW-RULE.md 逐條合規
  #2 shallow bug scan（只看 diff，不讀額外上下文）
  #3 git blame historical context
  #4 previous PR comments（查同檔案的舊 PR 留言）
  #5 code comments compliance（改動是否符合檔案內既有註解指引）

後置步驟：
  → 每個 issue 各啟一個 Haiku agent 做信心評分（0-100）
  → CRITICAL(≥90) / MINOR(80-89) / INFO(<80) 分類
  → 6 項品質評分（滿分 30）
  → Haiku agent 確認 PR 仍為 OPEN（已 merge/close → 跳過輸出）
  → 輸出結構化報告
```

- diff 來源：`gh pr diff <PR_NUMBER>`（PR 輸入統一用 `gh pr view <input> --json number` 取 PR number）
- token 消耗：高（2 前置 Haiku + 5 Sonnet + N Haiku + 1 後置 Haiku）
- 檔案過濾：跳過 `*.md`、`*.json`、`*.yml` 的改動

## 模式切換

呼叫 agent 時在 prompt 中指定：

- 不帶參數或帶 `mode: lite` → 輕量版
- 帶 `mode: full` + PR 資訊（PR number 或 URL）→ 完整版

## Agent 設定

```yaml
---
name: pr-reviewer
description: Code review agent — 逐條比對 CODE-REVIEW-RULE.md 並產出結構化報告。預設 lite 模式（單 agent + Haiku 信心評分），可切換 full 模式（5 平行 agent，移植自 CI workflow）。
tools: ["Read", "Grep", "Glob", "Bash", "Agent"]
model: sonnet
---
```

## 信心評分機制

每個 issue 獨立啟一個 Haiku agent 評分。

Haiku agent 輸入：diff context + issue 描述 + CODE-REVIEW-RULE.md 相關條目。

Haiku agent 評分量尺（連續 0-100）：

| 分數區間 | 語意 |
|----------|------|
| 0 | 完全不可信，false positive 或既有問題 |
| 1-39 | 低信心，可能是 false positive |
| 40-59 | 中等信心，可能是真問題但也可能是 nitpick |
| 60-79 | 高信心，很可能是真問題 |
| 80-89 | 非常高信心，已驗證的真問題 |
| 90-100 | 確定，確認的真問題 |

分類閾值：

| 分數區間 | 分類 | 意義 |
|----------|------|------|
| ≥90 | CRITICAL | 必須修正 |
| 80-89 | MINOR | 建議修正 |
| <80 | INFO | 僅供參考 |

Haiku agent 評分失敗時 fallback：該 issue 歸入 INFO 類別，附註「信心評分失敗」。

### False Positive 過濾（同 CI workflow）

以下不計為 issue：
- 既有問題（非本次 diff 引入）
- Linter / typechecker / compiler 會抓的
- 一般品質意見（除非 CODE-REVIEW-RULE.md 明確要求）
- 明顯有意為之的功能變更
- 非修改行的問題

## 品質評分

6 項，每項 1-5 分，滿分 30：

| 項目 | 檢查重點 |
|------|----------|
| Magic Number | 未經解釋的數字常數 |
| 邏輯與註解一致性 | 程式邏輯與註解是否相符 |
| 函式註解 | JSDoc 完整度 |
| 變數/常數/props/state 註解 | 用途說明 |
| 註解錯字 | 有無錯字 |
| 系統穩定性 | crash 風險 |

分數意義：5=完美 4=不錯 3=還可以 2=不好 1=拒絕接受

## 輸出格式

```markdown
### Code Review Results

**嚴重 CRITICAL**（必須修正）

1. <問題描述>（原因：CODE-REVIEW-RULE.md 規定「<規則摘要>」/ 因 <上下文> 導致的 bug）（信心：XX/100）
   <檔案路徑:行號>

**次要 MINOR**（建議修正）

1. <問題描述>（原因：<說明>）（信心：XX/100）
   <檔案路徑:行號>

**參考 INFO**（僅供參考）

1. <問題描述>（原因：<說明>）（信心：XX/100）
   <檔案路徑:行號>

若該分類無問題，顯示「無」。

### Quality Score

| 項目 | 分數 |
|------|------|
| Magic Number | X/5 |
| 邏輯與註解一致性 | X/5 |
| 函式註解 | X/5 |
| 變數/常數/props/state 註解 | X/5 |
| 註解錯字 | X/5 |
| 系統穩定性 | X/5 |
| **總分** | **XX/30** |
```

## 邊界情況處理

| 情況 | 行為 |
|------|------|
| CODE-REVIEW-RULE.md 找不到 | 報錯並終止 |
| diff 為空（只改 .md/.json/.yml 或 no-op commit） | 輸出「無需 review 的程式碼改動」並提前退出 |
| Haiku 評分 agent 失敗/timeout | 該 issue 歸入 INFO，附註「信心評分失敗」 |
| Full 模式 5 個 Sonnet agent 其中一個失敗 | 仍輸出 partial result，附註哪個面向失敗 |
| Full 模式 PR 不存在或無權限 | 報錯並終止 |
| 非 git repo 目錄 | 報錯並終止 |

## CODE-REVIEW-RULE.md 位置解析

agent 啟動時依序找：
1. 當前 repo 根目錄的 `CODE-REVIEW-RULE.md`
2. `~/.claude/CODE-REVIEW-RULE.md`（全域 fallback）

找不到則報錯並終止。

## 與 CLAUDE.md 的關係

本 agent 不檢查 CLAUDE.md 合規（目前尚未完全導入 CLAUDE.md 到各專案）。規範來源僅為 CODE-REVIEW-RULE.md。未來若各專案完成 CLAUDE.md 導入，可考慮加入 CLAUDE.md 合規面向。

## 與 POST-COMMIT-REVIEW 流程的整合

```
eslint（hook command）
  → /simplify
  → pr-reviewer agent（lite 模式）  ← 新增
  → pr-review-toolkit（品質/bug/設計）
  → 通知
```

pr-reviewer 與 pr-review-toolkit 並行互補：
- pr-reviewer：公司規範逐條合規 + 結構化評分
- pr-review-toolkit：通用品質/bug/設計（AI 判斷優先）

## 與 CI workflow 的關係

此 agent 完成後，`claude-code-review.yml` 預計退役。Full 模式覆蓋 CI workflow 的核心功能（5 平行 agent + 信心評分 + 品質評分），差異：
- 不檢查 CLAUDE.md（刻意，見上方說明）
- 不處理 `@claude` 留言觸發（本機不需要）
- 不處理 Auto-sync PR 排除（本機不需要）
- 結果輸出到 terminal，post PR comment 由未來的 `review-pr.sh` 負責

## 語言規則

- agent 內部運算用英文
- 所有輸出用繁體中文
- 檔案路徑、code identifier 維持英文
