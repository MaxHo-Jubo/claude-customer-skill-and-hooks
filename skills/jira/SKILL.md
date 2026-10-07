---
name: jira
description: "Jira Issue 管理工具。從 branch 自動識別 issue、抓詳情、建開發筆記、管理 branch、把 Teams 討論結論同步成 Jira 留言。當使用者提到 /jira、「看一下 issue」、「建 branch」、想從 Jira 抓資料、「同步 Teams 留言到 Jira」時觸發。"
version: 1.3.0
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

1. 讀取使用者的 `~/.claude/CLAUDE.md`（全域）或專案 `.claude/CLAUDE.md`，尋找 Jira 設定。兩種格式等價：`## Jira 設定` 表格，或 `<conn>` 區塊內的 `JIRA:`（`cloud-id` = `JIRA_CLOUD_ID`、`username` = `JIRA_USERNAME`、`branch-prefix` = `BRANCH_PREFIX_MAP`）
2. 兩種格式都找不到時：
   - 詢問使用者的 `JIRA_CLOUD_ID`（提示：可從 Atlassian 管理後台取得，或用 `getAccessibleAtlassianResources` MCP 工具查詢）
   - 詢問使用者的 `JIRA_USERNAME`（提示：通常是 branch 名稱中 `feat/xxx/` 的 xxx 部分）
   - 把要新增到 `~/.claude/CLAUDE.md` 的段落先給使用者看，同意後再寫入，格式如下：

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

- `/jira` - 顯示當前 issue 資訊
- `/jira fetch` - 從 Jira API 抓取 issue 詳情並建立文件
- `/jira branch {ISSUE_ID}` - 根據 issue 建立 branch 並列出待辦事項
- `/jira teams [ISSUE_ID]` - 把 Teams 上追蹤這張票的討論結論整理成草稿，確認後貼到 Jira 留言（不帶 ID 則取當前 branch 的 issue）

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
   - **branch 沒有 Jira 編號時**：改讀 save-progress 依 branch 命名的交接紀錄 `{CLAUDE_DIR}/handoff-{branch}.md`（`{branch}` 中的 `/` 換成 `-`，命名規則以 `~/.claude/skills/save-progress/SKILL.md` STEP 01 為準）
     - 檔案存在 → 顯示內容，並標明「無 Jira 編號，顯示 branch 交接紀錄」
     - 檔案不存在 → 提示可用 `/save-progress` 建立交接紀錄，或用 `/jira branch {ISSUE_ID}` 開票 branch
     - branch 為空（detached HEAD／非 git repo）→ 照「錯誤處理」的無 issue ID 處理

4. **如果是 `/jira fetch`**：
   - 使用 Atlassian MCP 工具抓取 issue 詳情：
     1. 用 `getJiraIssue`（含 `issuelinks` 欄位）取得 issue（使用設定中的 `JIRA_CLOUD_ID`）
     2. 從回傳結果提取：標題、描述、類型、優先順序、狀態、指派人、子任務、相關連結
     3. **關聯追蹤**：若 description 為空，執行「關聯 Issue 需求追蹤」流程（見下方）
   - 將結果格式化寫入 `{CLAUDE_DIR}/{ISSUE_ID}-Jira.md`（包含追蹤鏈與需求來源）
   - 如果 `{CLAUDE_DIR}/{ISSUE_ID}.md` 不存在，建立開發筆記模板
   - **附上 Teams 討論（唯讀）**：跑「Teams 同步流程」T1～T4，但**不進 T5、不寫 Jira**。把討論串清單與新訊息摘要寫進 `{ISSUE_ID}-Jira.md` 的 `## Teams 討論` 段（整段替換）；有 SINCE 之後的新訊息 → 提示「Teams 有 M 則未同步的討論，要跑 `/jira teams` 貼到 Jira 嗎？」。T1 失敗時該段寫「Teams 未檢查：{原因}」，不擋 fetch 其餘步驟

5. **如果是 `/jira branch {ISSUE_ID}`**：
   - 見下方「Branch 建立流程」

6. **如果是 `/jira teams [ISSUE_ID]`**：
   - 不帶 ID → 用步驟 1 的 branch issue ID；都沒有 → 照「錯誤處理」的無 issue ID 處理
   - 跑完整「Teams 同步流程」T1～T5

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
- `{ISSUE_ID}-Jira.md`：儲存從 Jira 抓到的原始資訊，並比照 `/jira fetch` 附上 `## Teams 討論` 段（唯讀，T1～T4）
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

## Teams 同步流程

把 Teams 上追蹤這張票的討論結論整理成 Jira 留言。一律**草稿＋使用者確認**，不全自動貼：目前讀取管道有三種失真（遺漏／截斷／串錯，見本節「已知限制」），內容必須有人把關。

本節被四處引用，改這裡等於改全部：
- `/jira teams`：T1～T5 完整流程
- `/jira fetch`・`/jira branch`：T1～T4 唯讀，結果寫進 `{ISSUE_ID}-Jira.md`
- `save-progress` skill：T1～T4，有新訊息才進 T5
- `jira-release-sync` skill：只跑 T1～T3 計新訊息數，使用者指定的票才進 T4～T5

M365 工具名稱前綴為 `mcp__claude_ai_Microsoft_365__`，多為 deferred tool，呼叫前先用 ToolSearch `select:` 載入。

### 常數

| 名稱 | 值 | 用途 |
|------|----|------|
| `SYNC_TITLE` | `【Teams 討論結論同步】` | 留言第一行標題，同時是 T2「上次同步點」的判斷依據；改字要一起改 T2 |
| `SIGNATURE` | `由 Claude Code skill 整理` | 留言最後一行（2026-10-07 使用者定案；作者欄已是本人帳號，不另署名） |

### T1 前置檢查

1. 呼叫 `get_granted_scopes`。工具不存在或回傳授權錯誤 → 停下，提示使用者執行 `/mcp` 選「claude.ai Microsoft 365」授權。**不可當作「Teams 沒有討論」繼續**
2. 只允許讀取類工具：`get_granted_scopes`、`chat_message_search`、`read_resource`（補齊授權後加 `teams_list_teams`、`teams_list_channel_messages`）。**禁止**呼叫 `teams_send_*`、`teams_reply_*`、`teams_create_chat` 等寫入工具
3. 記下 grantedScopes 是否含 `Team.ReadBasic.All`，決定 T3.3 走哪條路

### T2 決定上次同步點

1. `executeRead(name="listJiraIssueComments", cloudId, inputs={issueIdOrKey, orderBy: "-created"})`（`cloudId` 是頂層參數，不放 `inputs`）
2. 第一則 body 以 `SYNC_TITLE` 開頭的留言，其 `created` = `SINCE`；沒有 → `SINCE` = issue `created`
3. 另記 `ISSUE_CREATED` = issue `created`（T3.1 用）

### T3 搜尋 Teams 討論

1. **找討論串**：`chat_message_search(query=<ISSUE_ID 的數字部分>, afterDateTime=<ISSUE_CREATED 日期>, offset=0)`，有 `nextOffset` 就翻頁
   - 不可搜 `"<PROJ>-1234"` 這種完整 key：KQL 對連字號斷詞，實測 0 筆；搜數字 `1234` 才命中
   - 用完整 `ISSUE_ID` 字串比對 `subject`／`summary`，去掉只是數字碰巧相同的訊息
   - 0 筆時工具回傳**空輸出**（不是錯誤）；錯誤一律是帶 `code` 的 JSON，兩者分開處理
   - 依 `chatId` 分組，每組是一個討論串
   - 起點用 `ISSUE_CREATED` 而非 `SINCE`：root 貼文常早於上次同步點，用 `SINCE` 會找不到串
2. **讀 root 全文**：`read_resource("teams:///chats/{percent-encoded chatId}/messages/{id}")`
   - channel 訊息的 `uri`（`teams:///teams/{teamId}/...`）實測回 NOT_FOUND：搜尋結果裡的 teamId 不是 group id。改用 chats 路徑
   - 回 400「is a reply」→ 該則是回覆，錯誤訊息裡的 `/messages({rootId})/replies(...)` 帶有 root id，改讀 root
3. **收回覆**：
   - **有 `Team.ReadBasic.All`**：`teams_list_teams` 取 group id → `teams_list_channel_messages(teamId, channelId, parentMessageId=rootId)` 取完整回覆。**此路徑尚未實測**，第一次走到時驗證並更新本段
   - **沒有（2026-10-07 現況）**：用關鍵字補搜。從 issue summary 抽 2～4 個詞（機構名、功能名、症狀詞）以 `OR` 組成 query，`afterDateTime=SINCE`，只留 `chatId` 等於該串的結果，再依主題排除同 channel 的其他討論串。回覆只拿得到搜尋 `summary`（約 500 字，可能截斷）；`read_resource` 讀不到 reply 全文（`.../replies/{id}` 會被忽略並回傳 root）
4. `createdDateTime > SINCE` 的訊息才算新訊息；root 早於 `SINCE` 時只當背景，不再寫入

### T4 產出草稿與結果回報

草稿格式（`■` 段沒有內容就省略）：

```
【Teams 討論結論同步】(來源：{channel 或 chat 名稱}「{root subject}」，{YYYY-MM-DD})

■ 結論
…
■ 決策
…
■ 後續
…

由 Claude Code skill 整理
```

- 只寫結論、決策、後續，不逐字搬對話；要給客戶的話術可獨立一段
- 草稿下方另附**給使用者看、不進留言**的來源清單：每則訊息的發話者、時間、`全文`／`摘要（可能截斷）`；走關鍵字路徑時加註「未命中關鍵字的回覆可能遺漏」
- 結果分四種，各自明講、不可混用：

| 情況 | 回報 |
|------|------|
| N 個討論串、`SINCE` 後 M 則新訊息（M > 0） | 出草稿 |
| N 個討論串、`SINCE` 後 0 則 | 「已同步到最新（上次同步：{SINCE}）」 |
| 0 個討論串 | 「Teams 搜尋 `{數字}` 無命中（範圍 {ISSUE_CREATED} 起）」，提醒可能是對話沒寫票號 |
| T1 授權失敗／搜尋 API 錯誤 | 錯誤原文，**不得**歸到上面三種 |

### T5 確認後寫入

1. 使用者明確確認前，**不得**呼叫 `addOrEditJiraIssueComment`
2. 確認後：`addOrEditJiraIssueComment(cloudId, issueIdOrKey, commentBody=<草稿>)`，回報 commentId
3. 要修改已貼的留言 → 帶 `commentId` 編輯，`commentBody` 須是完整內文（編輯會整則覆蓋）

### 已知限制（2026-10-07 以一張 LVB 票實測）

| 現象 | 影響 |
|------|------|
| tenant 未授權 `Team.ReadBasic.All`（`teams_list_teams` 回 403） | 列不出討論串回覆 → **遺漏** |
| 回覆只有搜尋摘要 | 長回覆 → **截斷** |
| 搜尋結果沒有 `replyToId` | 同 channel 其他討論串混入 → **串錯** |

請 IT 對 Claude M365 connector 補 `Team.ReadBasic.All` admin consent 後，T3.3 改走完整路徑並重新實測。

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

- **Branch 名稱無 issue ID**：`/jira`（無參數）先走步驟 3 的 branch 交接紀錄；其餘情況提示使用者手動輸入 issue ID，或用 `/jira branch {ISSUE_ID}` 直接指定
- **Jira API 錯誤**：顯示錯誤訊息，建議使用者檢查網路連線或 Atlassian MCP 設定
- **`{CLAUDE_DIR}` 目錄不存在**：自動建立
- **Microsoft 365 connector 未授權或 API 錯誤**：照「Teams 同步流程」T1／T4 的錯誤出口回報原文；`/jira fetch`・`/jira branch` 不因此中斷

## 注意事項

- `/jira fetch` 和 `/jira branch` 都使用 Atlassian MCP 工具抓取 issue，不依賴 jira CLI
- 確保 `{CLAUDE_DIR}` 目錄存在（如不存在則建立）
- branch 建立前會從 master 拉最新程式碼
- 完成 fetch 或 branch 建立後，提示使用者：「是否使用 /linus-requirements-analysis 分析需求？」
