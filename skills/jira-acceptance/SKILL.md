---
name: jira-acceptance
description: "Jira 需求驗收工具。比對 Jira issue 需求描述與當前程式碼改動（git diff），逐條判斷需求是否已實作，產出結構化驗收報告。當使用者提到 /jira-acceptance、想驗收需求、說「檢查這個 issue 做完了沒」、「驗收」、「需求比對」、想確認程式碼改動是否符合 Jira 需求時使用此 skill。即使使用者只說「看看做完了沒」或「diff 跟 issue 對得上嗎」也應觸發。"
---

# Jira 需求驗收

比對 Jira issue 的需求描述與當前 git diff，逐條判斷每項需求的實作狀態，產出結構化驗收報告。

## 使用方式

- `/jira-acceptance` — 自動從 branch 名稱取得 issue key
- `/jira-acceptance ERPD-7777` — 手動指定 issue key

## 執行流程

### 步驟 1: 取得 Jira Issue Key

依優先順序嘗試：

1. **引數傳入**：使用者直接傳入 issue key（如 `ERPD-7777`）
2. **Branch 名稱解析**：從當前 git branch 自動擷取

```bash
git branch --show-current | grep -oE '[A-Z]+-[0-9]+' | head -1
```

如果兩者都取不到，詢問使用者提供 issue key。

### 步驟 2: 抓取 Jira Issue 需求

使用 Atlassian MCP 工具 `getJiraIssue`，帶入以下參數：

- `cloudId`: 從使用者的 CLAUDE.md 讀取 `JIRA_CLOUD_ID`
- `issueIdOrKey`: 步驟 1 取得的 key
- `fields`: `["summary", "description", "issuelinks", "subtasks", "acceptance criteria"]`

抓取後提取：
- **標題**（summary）
- **描述**（description）— 這是需求的主要來源
- **子任務**（subtasks）— 每個子任務可能代表一項獨立需求
- **驗收條件**（acceptance criteria，如果 Jira 有設定此欄位）

如果 description 為空，沿著 issuelinks 追蹤最多 2 層，蒐集關聯 issue 的描述（邏輯同 jira skill 的「關聯 Issue 需求追蹤」）。

### 步驟 3: 解析需求項目

從 Jira 內容中拆解出獨立的需求項目。解析策略：

1. **結構化清單**：如果描述中有編號清單或 bullet points，每個項目就是一條需求
2. **子任務**：每個子任務的 summary 作為一條需求
3. **驗收條件**：如果有 acceptance criteria 欄位，每條作為需求
4. **段落式描述**：如果描述是連續文字，按語意拆分為獨立需求項目

每條需求應精簡為一句話，保留核心意圖，去除冗餘修飾。

### 步驟 4: 取得程式碼改動

執行以下指令取得完整的程式碼改動：

```bash
git diff
git diff --cached
git status --short
```

三者合併分析：
- `git diff` + `git diff --cached` = staged + unstaged 的修改
- `git status --short` = 找出 untracked 新檔案（`??` 開頭的行）

對每個 untracked 新檔案，用 Read 工具讀取其完整內容，視為「新增檔案」納入改動分析。新檔案往往包含關鍵的新功能實作（如新元件、新模組），忽略它們會導致嚴重的誤判。

如果 diff 和 untracked 都沒有改動，改為比對 branch 與 base branch 的差異：

```bash
git merge-base HEAD master
git diff $(git merge-base HEAD master)..HEAD
```

這個 fallback 機制確保即使所有改動都已 commit，仍能進行驗收。

### 步驟 5: 逐條比對需求與改動

對每條需求，分析 git diff 中的改動：

1. 閱讀需求描述，理解其核心意圖
2. 在 diff 中搜尋與該需求相關的程式碼改動
3. 判定狀態：
   - **✅ 已實作**：改動明確覆蓋了該需求的完整意圖
   - **⚠️ 部分實作**：有相關改動但未完全覆蓋，或實作與需求有偏差
   - **❌ 未實作**：diff 中找不到與該需求相關的改動

4. 記錄證據：列出對應的檔案路徑和行號範圍

判定原則：

- 寧可標「部分實作」也不要錯標「已實作」— 漏掉未完成的需求比誤報完成更危險
- 如果需求描述模糊到無法從程式碼判斷，標「⚠️ 部分實作」並在備註說明原因
- 考慮隱含需求：例如「新增欄位」通常隱含前後端都要改、資料庫 migration 等

### 步驟 6: 產出驗收報告

使用以下固定格式輸出報告：

```markdown
## Jira 需求驗收報告

**Issue**: {ISSUE_KEY} - {issue 標題}
**Branch**: {當前 branch 名稱}
**比對範圍**: {uncommitted changes / branch diff from master}

### 需求項目

| # | 需求描述 | 狀態 | 對應改動 |
|---|---------|------|---------|
| 1 | {需求內容} | ✅ 已實作 | `src/foo.ts:10-25` |
| 2 | {需求內容} | ⚠️ 部分實作 | `src/bar.ts:5-8` |
| 3 | {需求內容} | ❌ 未實作 | - |

### 總結

- ✅ 已實作: X/Y
- ⚠️ 部分實作: X/Y
- ❌ 未實作: X/Y

### 備註

- {對部分實作或未實作項目的補充說明}
- {任何 diff 中發現但不在需求列表中的額外改動}
```

## 重要原則

1. **保守判定**：不確定時偏向「部分實作」而非「已實作」
2. **證據導向**：每個判定都必須有 diff 中的具體行號作為依據
3. **額外改動提示**：如果 diff 中有明顯不屬於任何需求的改動，在備註中指出
4. **繁體中文輸出**：報告全程使用繁體中文

## 錯誤處理

- **無 issue key**：詢問使用者提供
- **Jira API 錯誤**：顯示錯誤訊息，建議檢查 MCP 設定
- **無 diff 內容**：提示「沒有偵測到程式碼改動，無法進行驗收」
- **需求為空**：提示「Jira issue 無需求描述，無法進行驗收」
