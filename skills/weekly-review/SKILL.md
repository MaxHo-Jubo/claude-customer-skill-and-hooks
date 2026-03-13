---
name: weekly-review
description: "每週工作回顧與記憶整理。彙整一週 commit、觀察記錄、auto memory，產出結構化週報，清理過期記憶，提取反覆模式為 skill。當使用者提到 /weekly-review、想回顧工作、說「整理記憶」、「週報」、「回顧一下這週做了什麼」時使用此 skill。"
---

# Weekly Review — 週回顧與記憶整理

每週執行一次，回顧工作成果、整理記憶系統、提取可複用的模式。

## 使用方式

- `/weekly-review` — 完整五步驟回顧
- `/weekly-review --days 14` — 指定回顧天數（預設 7 天）
- 使用者說「整理記憶」— 只執行步驟 5（記憶整理）

## 執行步驟

### STEP 01: Git 工作摘要

收集指定天數內所有專案的 commit 紀錄，按專案分組。

```bash
# 對每個已知專案目錄執行
git log --since="7 days ago" --oneline --no-merges
```

輸出格式：

```
## 工作摘要（{起始日} ~ {結束日}）

### {專案名稱}
- {commit 類型}: {描述} (x 個 commit)
- ...

### 統計
- 總 commit 數: N
- 涉及專案: N 個
- 主要工作類型: feat/fix/refactor 佔比
```

### STEP 02: 觀察記錄回顧

使用 claude-mem 的 `timeline` 和 `search` 工具，撈出指定天數內的觀察記錄。

- 呼叫 `mcp__plugin_claude-mem_mcp-search__timeline` 取得時間線
- 呼叫 `mcp__plugin_claude-mem_mcp-search__search` 搜尋關鍵決策、糾正、偏好

輸出格式：

```
## 觀察記錄摘要

### 關鍵決策
- {日期}: {決策內容}

### 使用者糾正
- {日期}: {糾正內容}

### 值得注意的模式
- {模式描述}
```

### STEP 03: Auto Memory 變動

掃描 auto memory 目錄，列出指定天數內新增或更新的記憶檔案。

```bash
find ~/.claude/projects/*/memory/ -name "*.md" -mtime -{days} -type f 2>/dev/null
```

輸出格式：

```
## Auto Memory 變動

### 新增/更新
| 檔案 | 類型 | 摘要 |
|------|------|------|

### 統計
- 總記憶數: N
- 本週新增: N
- 本週更新: N
```

### STEP 04: 週報彙整與模式提取

綜合前三步結果，產出結構化週報：

```
## 週報（{起始日} ~ {結束日}）

### 做了什麼
- {按重要性排列的工作項目}

### 學到什麼
- {從糾正和決策中提取的學習}

### 反覆出現的模式
- {出現 2+ 次的工作流程或行為模式}

### 建議提取為 Skill
- {反覆執行的流程} → 建議建立 `/skill-name`
  - 觸發條件: ...
  - 核心步驟: ...
```

**輸出週報後，等待使用者確認再進入步驟 5。**

### STEP 05: 記憶整理

整理 auto memory、claude-mem 觀察記錄、各專案 tasks/lessons.md，清理過期資訊。

#### 5.1 掃描所有記憶來源

- auto memory 各 type（user/feedback/project/reference）的數量與內容摘要
- 各專案 `tasks/lessons.md` 的內容
- claude-mem 中的觀察記錄

#### 5.2 標記待處理項目

| 狀態 | 條件 | 動作 |
|------|------|------|
| 過期 | project memory 超過 30 天未更新 | 建議刪除或更新 |
| 重複 | 多個 feedback/user memory 說同一件事 | 建議合併 |
| 升級 | 同一 feedback 出現 3+ 次 | 建議寫進 CLAUDE.md 成為硬規則 |
| 已內化 | feedback 內容已存在於 CLAUDE.md | 建議刪除 memory |
| 過時 | lessons.md 中的教訓已被 feedback memory 覆蓋 | 建議清理 |

#### 5.3 提出整理方案

列出建議的刪除/合併/升級清單，格式：

```
## 記憶整理建議

### 建議刪除（過期/已內化）
- [ ] {檔案}: {理由}

### 建議合併（重複）
- [ ] {檔案A} + {檔案B} → {合併後名稱}: {理由}

### 建議升級為 CLAUDE.md 規則
- [ ] {feedback 內容} → 建議加到 {CLAUDE.md 的哪個 section}

### 建議清理 lessons.md
- [ ] {專案}: {過時的教訓}
```

**等待使用者逐項確認後才執行。絕不自動刪除任何記憶。**

## 注意事項

- 週報和整理建議都需要使用者確認後才執行變更
- 步驟 4 產出週報後暫停，使用者確認後才進入步驟 5
- 步驟 5 每個刪除/合併/升級動作都需要個別確認
- 如果使用者只說「整理記憶」，直接跳到步驟 5
