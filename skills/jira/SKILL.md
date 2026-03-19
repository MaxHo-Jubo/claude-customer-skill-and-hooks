---
name: jira
description: "Jira Issue 管理工具。從 branch 自動識別 issue、抓詳情、建開發筆記、管理 branch。當使用者提到 /jira、「看一下 issue」、「建 branch」、想從 Jira 抓資料時觸發。"
version: 1.1.0
---

# Jira Issue 管理

從當前 Git branch 名稱自動識別 Jira issue，並管理相關文件。

## 設定（首次使用會自動引導）

此 skill 需要以下設定值。這些值不存放在 skill 本身，而是存放在使用者自己的 CLAUDE.md 中，確保每個人有各自的設定。

### 必要設定

| 設定項 | 說明 | 範例 |
|--------|------|------|
| `JIRA_CLOUD_ID` | Atlassian Cloud ID（UUID 格式） | `c7b686ea-9df3-46c7-a982-3f0175a96e59` |
| `JIRA_USERNAME` | Git branch 中使用的名稱 | `max_ho` |

### 選填設定

| 設定項 | 說明 | 預設值 |
|--------|------|--------|
| `BRANCH_PREFIX_MAP` | Issue 前綴與 branch 類型的對應 | 見下方預設表 |

### 首次使用流程

第一次使用 `/jira` 相關指令時：

1. 讀取使用者的 `~/.claude/CLAUDE.md`（全域）或專案 `.claude/CLAUDE.md`，尋找 `## Jira 設定` section
2. 若找不到設定：
   - 詢問使用者的 `JIRA_CLOUD_ID`（提示：可從 Atlassian 管理後台取得，或用 `getAccessibleAtlassianResources` MCP 工具查詢）
   - 詢問使用者的 `JIRA_USERNAME`（提示：通常是 branch 名稱中 `feat/xxx/` 的 xxx 部分）
   - 將設定寫入使用者的 `~/.claude/CLAUDE.md`，格式如下：

```markdown
## Jira 設定

| 設定項 | 值 |
|--------|-----|
| JIRA_CLOUD_ID | {使用者提供的值} |
| JIRA_USERNAME | {使用者提供的值} |
| BRANCH_PREFIX_MAP | ERPD=feat, LVB=fix |
```

3. 後續使用時直接從 CLAUDE.md 讀取，不再詢問

### Branch 前綴對應表（預設）

| 前綴 | 類型 | Branch 格式 |
|------|------|-------------|
| `ERPD` | 開發（feat） | `{ISSUE_ID}/feat/{JIRA_USERNAME}/{簡短說明}` |
| `LVB` | 修正（fix） | `{ISSUE_ID}/fix/{JIRA_USERNAME}/{簡短說明}` |

使用者可在 CLAUDE.md 的 `BRANCH_PREFIX_MAP` 中自訂更多前綴對應，格式：`PREFIX=type`，逗號分隔。

## 使用方式

- `/jira` - 顯示當前 issue 資訊（等同舊版 `/jira show`）
- `/jira fetch` - 從 Jira API 抓取 issue 詳情並建立文件
- `/jira branch {ISSUE_ID}` - 根據 issue 建立 branch 並列出待辦事項

## 執行步驟

0. **解析文件存放路徑**：使用主要工作目錄（primary working directory）的絕對路徑作為基底，組合 `.claude/` 作為文件目錄。例如主要工作目錄為 `/Users/maxhero/Documents/Compal/luna_web/frontend`，則文件目錄為 `/Users/maxhero/Documents/Compal/luna_web/frontend/.claude/`。後續步驟中的 `{CLAUDE_DIR}` 皆指此絕對路徑。**禁止使用相對路徑 `.claude/`**，因為 git 操作會改變 cwd。

1. 先執行以下指令取得當前 branch 的 Jira issue ID：
```bash
git branch --show-current | grep -oE '[A-Z]+-[0-9]+' | head -1
```

2. 根據取得的 ISSUE_ID，檢查 `{CLAUDE_DIR}` 下是否存在對應文件：
   - `{CLAUDE_DIR}/{ISSUE_ID}.md` - Issue 開發筆記
   - `{CLAUDE_DIR}/{ISSUE_ID}-Jira.md` - Jira 原始資訊

3. **如果是 `/jira`（無參數）**：
   - 讀取並顯示已存在的 issue 文件內容
   - 如果文件不存在，提示用戶可以用 `/jira fetch` 建立

4. **如果是 `/jira fetch`**：
   - 使用 Atlassian MCP 工具抓取 issue 詳情：
     1. 用 `getJiraIssue`（含 `issuelinks` 欄位）取得 issue（使用設定中的 `JIRA_CLOUD_ID`）
     2. 從回傳結果提取：標題、描述、類型、優先順序、狀態、指派人、子任務、相關連結
     3. **關聯追蹤**：若 description 為空，執行「關聯 Issue 需求追蹤」流程（見下方）
   - 將結果格式化寫入 `{CLAUDE_DIR}/{ISSUE_ID}-Jira.md`（包含追蹤鏈與需求來源）
   - 如果 `{CLAUDE_DIR}/{ISSUE_ID}.md` 不存在，建立開發筆記模板

5. **如果是 `/jira branch {ISSUE_ID}`**：
   - 見下方「Branch 建立流程」

## 關聯 Issue 需求追蹤

當 issue 的 description 為空時，自動沿著 `issuelinks` 追蹤關聯 issue，最多 2 層，蒐集所有找到的需求描述並加以整理。

這樣做的原因是需求資訊經常分散在多個關聯 issue 中，單一 issue 不一定包含完整的需求描述。全部蒐集後再整理，才能拼湊出完整的需求全貌。

### 追蹤邏輯

1. 取得當前 issue 的 `issuelinks`（需在 `getJiraIssue` 時帶 `fields: ["issuelinks", "description", "summary"]`）
2. 若 description 為空且有 issuelinks：
   - 對每個關聯 issue 呼叫 `getJiraIssue` 取得 description、summary 和 issuelinks
   - **蒐集所有找到的 description**，不論第一層是否已找到，都繼續追蹤第二層
   - 記錄每筆 description 的來源 issue ID 和關聯路徑
3. 最多追蹤 2 層（原始 issue 不算），避免無限遞迴
4. 追蹤時記錄完整鏈路，例如：`ERPD-11760 --clones--> ERPD-11759 --relates to--> LWM-2378`

### 結果整理

追蹤完成後，將蒐集到的所有 description 進行整理：

1. **去重**：移除重複或高度相似的描述內容
2. **分類**：依來源 issue 的類型或關聯性質分組
3. **彙整**：將分散的描述合併為一份結構化的需求摘要，包含：
   - 核心需求（從所有描述中提煉的主要目標）
   - 補充細節（各 issue 中的額外要求或限制）
   - 來源標註（每段內容標明出處 issue ID）

在 Jira 文件中記錄：
- **需求來源**: 所有有 description 的 issue ID（附連結）
- **追蹤鏈**: 完整的關聯路徑
- **需求彙整**: 整理後的需求摘要
- **原始描述**: 各 issue 的原始 description（折疊區塊，供參考）

開發筆記的「問題描述」填入整理後的需求摘要。

若追蹤 2 層後完全無 description，標註「無詳細需求描述，請手動補充」。

## Branch 建立流程

當使用者執行 `/jira branch {ISSUE_ID}` 時，依序執行以下步驟：

### 步驟 1: 抓取 Issue 詳情

使用 `getJiraIssue`（含 `issuelinks`, `description`, `summary`, `subtasks` 欄位）抓取 issue 資訊。

若 description 為空，執行「關聯 Issue 需求追蹤」流程，蒐集並整理需求。

最終需取得：
- 標題（Summary）
- 描述（Description，可能來自關聯 issue 整理）
- 類型（Issue Type）
- 優先順序（Priority）
- 子任務（Sub-tasks）
- 相關連結（Links）
- 需求來源與追蹤鏈（若有追蹤）

### 步驟 2: 判斷 Branch 類型

根據 ISSUE_ID 的前綴和設定中的 `BRANCH_PREFIX_MAP` 決定 branch 命名。

- `{簡短說明}` 從 issue 標題提取，轉為簡短中文描述（去除冗餘詞彙）
- 若無法判斷前綴，詢問使用者要用 feat 還是 fix

### 步驟 3: 建立 Branch

1. 先確認當前工作目錄是否乾淨（`git status`），如果有未提交的變更則警告使用者
2. 從最新的 master 建立 branch：
   ```bash
   git checkout master && git pull origin master && git checkout -b {branch_name}
   ```
3. 顯示建立成功的訊息

### 步驟 4: 建立開發筆記

在 `{CLAUDE_DIR}` 下建立 `{ISSUE_ID}.md` 和 `{ISSUE_ID}-Jira.md`：
- `{ISSUE_ID}-Jira.md`：儲存從 Jira 抓到的原始資訊
- `{ISSUE_ID}.md`：使用開發筆記模板，自動填入問題描述

### 步驟 5: 列出待辦事項

根據 issue 內容分析並列出需要做的事情，格式如下：

```markdown
## 待辦事項 — {ISSUE_ID}

**Branch**: `{branch_name}`
**類型**: feat / fix
**標題**: {issue 標題}

### 需要做的事情

- [ ] 項目 1（從 issue 描述 / 子任務提取）
- [ ] 項目 2
- [ ] ...

### 影響範圍

- 相關檔案或模組（如果能從 issue 描述判斷）

### 注意事項

- 來自 issue 描述中的特殊要求或限制
```

將這份待辦事項同時：
1. 顯示在終端給使用者看
2. 寫入 `{CLAUDE_DIR}/{ISSUE_ID}.md` 的對應 section

## 開發筆記模板

當需要建立 `{CLAUDE_DIR}/{ISSUE_ID}.md` 時，使用以下模板：

```markdown
# {ISSUE_ID}

## 問題描述

[從 Jira 摘要填入]

## 分析

[待填入]

## 解決方案

[待填入]

## 修改檔案

[待填入]

## 測試步驟

[待填入]
```

## 錯誤處理

- **Branch 名稱無 issue ID**：提示使用者手動輸入 issue ID，或用 `/jira branch {ISSUE_ID}` 直接指定
- **Jira API 錯誤**：顯示錯誤訊息，建議使用者檢查網路連線或 Atlassian MCP 設定
- **`{CLAUDE_DIR}` 目錄不存在**：自動建立

## 注意事項

- `/jira fetch` 和 `/jira branch` 都使用 Atlassian MCP 工具抓取 issue，不依賴 jira CLI
- 確保 `{CLAUDE_DIR}` 目錄存在（如不存在則建立）
- branch 建立前會從 master 拉最新程式碼
- 完成 fetch 或 branch 建立後，提示使用者：「是否使用 /linus-requirements-analysis 分析需求？」
