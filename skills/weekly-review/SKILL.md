---
name: weekly-review
description: "每週工作回顧與記憶整理。彙整 commit、Jira 活動、觀察記錄、auto memory，產出週報並清理過期記憶。當使用者提到 /weekly-review、「週報」、「整理記憶」、「回顧這週」時觸發。"
version: 1.8.0
context: fork
---

# Weekly Review — 週回顧與記憶整理

每週執行一次，回顧工作成果、整理記憶系統、提取可複用的模式、分析 skill 錯誤並驅動改善。

## 前置依賴

- **PostToolUse hook**: `~/.claude/hooks/post_tool_error.py` — 自動記錄所有 tool 失敗到 `~/.claude/.learnings/ERRORS.jsonl`
- **摘要腳本**: `~/.claude/scripts/summarize_errors.py` — 錯誤統計報告
- 安裝方式見 `skill-error-tracker/setup_skill_error_tracker.sh`

## 使用方式

- `/weekly-review` — 完整回顧（會先檢查 Atlassian MCP 連線）
- `/weekly-review --days 14` — 指定回顧天數（預設 7 天）
- `/weekly-review --skip-jira` — 跳過 STEP 00 與 STEP 01.5（不需 Jira 整合）
- 使用者說「整理記憶」— 只執行步驟 5（記憶整理），不檢查 MCP
- 使用者說「review skill errors」— 只執行步驟 6~8（錯誤分析循環），不檢查 MCP

## Busboy 紀律（執行所有步驟時遵守）

餐廳的 busboy 只巡桌歸碗盤，不煮菜、不點餐。本 skill 在彙整/歸檔/整理時套用相同紀律：

- **只歸位，不發明章節**：週報、修補建議、記憶整理都必須對齊現有 schema。禁止產出「決議 / 風險 / 結論 / 深度反思 / 啟示」這類看似專業但會爆炸的新段落
- **只填既有欄位**：輸出格式已在各 STEP 定義，多一個欄位都不行。缺資料就留空或寫「無」，不要自動補湊
- **不做創意判斷**：不對使用者的工作內容下價值判斷（「這個決策很棒」「這個錯誤很嚴重」），只陳述事實
- **不重組輸入**：commit/memory/observation 原本的分類就是分類，不二次歸類

違反紀律的徵兆：輸出變長、出現 schema 沒定義的 heading、開始講「我發現」「值得注意的是」。看到就停下。

## 每週觀察項目

近期對工作環境/設定做的調整，需連續數週觀察成效。執行 STEP 04 時走一遍本清單，逐項在週報「每週觀察項目現況」回報；項目穩定後可從本清單移除或內化為固定設定。

### big-read-guard hook（2026-05-20 加入）
- **內容**：PreToolUse hook（`~/.claude/hooks/big-read-guard.sh`），整檔 Read ≥ 800 行的檔案時 deny 一次並提示先用 smart_outline；每個檔案每 session 只攔一次，重送同一 Read 即放行。
- **觀察重點**：觸發是否過於頻繁（吵）、門檻 800 是否需調高、是否真的減少「整檔 dump 大檔」的情形。
- **調整點**：`big-read-guard.sh` 的 `THRESHOLD`。
- **狀態**：觀察中。

## 執行步驟

### STEP 00: 前置檢查 — Atlassian MCP 連線（只在完整流程執行）

本 skill 的 STEP 01.5 依賴 Atlassian MCP。進入 STEP 01 之前先驗證連線與認證。

**何時檢查：**

| 觸發情境 | 執行 STEP 00？ |
|---------|--------------|
| `/weekly-review` / `--days N` | ✅ 檢查 |
| `/weekly-review --skip-jira` | ❌ 跳過 |
| 「整理記憶」（只 STEP 05） | ❌ 跳過 |
| 「review skill errors」（只 STEP 06~08） | ❌ 跳過 |

**檢查方式：**

呼叫 Atlassian MCP 的最小查詢（例如以 JQL `assignee = currentUser()` 限 1 筆進行 issue search），觀察回應：

- 呼叫成功、回傳 JSON → 通過，繼續 STEP 01
- 呼叫失敗、401 Unauthorized、OAuth expired、token invalid、MCP tool 不存在 → 進入「未通過處理」

**未通過處理：**

顯示以下訊息，然後**立即結束 skill，不執行任何後續步驟**：

```
❌ Atlassian MCP 未連線或 OAuth 已過期

weekly-review 需要 Atlassian MCP 來撈本週 Jira 活動（STEP 01.5）。請先處理：

1. 檢查 atlassian plugin 是否啟用
   - `/plugin` → 確認 atlassian 為 enabled
2. 重新 OAuth 認證
   - `/mcp` → 找到 atlassian 條目 → 重新登入
3. 認證完成後，重新執行 /weekly-review

逃生閥（若暫時不需要 Jira 整合）：
- /weekly-review --skip-jira  → 跳過 STEP 01.5
- 「整理記憶」                  → 只跑 STEP 05（記憶整理）
- 「review skill errors」       → 只跑 STEP 06~08（錯誤分析）
```

**紀律：**

- 不嘗試自動認證或重試
- 不 degrade 為「跳過 Jira 繼續跑」（使用者明確要求擋下）
- 認證問題屬於 session-level 環境問題，由使用者處理

### STEP 01: Git 工作摘要（透過 multi-repo-commit-scanner subagent 平行掃描）

收集指定天數內所有專案的 commit 紀錄，按專案分組。**用 `multi-repo-commit-scanner` agent 平行掃 8 個 repo，主 agent 等聚合**（取代過去逐 repo 序列跑 `git log`）。

**呼叫方式：**

```
Agent(
  description: "Scan commits for weekly-review",
  subagent_type: "multi-repo-commit-scanner",
  prompt: """
    repos:
      - /Users/maxhero/Documents/Compal/luna-web/frontend
      - /Users/maxhero/Documents/Compal/luna-web/backend
      - /Users/maxhero/Documents/Compal/luna-RN-HomeCareStaff/HomeCareStaffRN
      - /Users/maxhero/Documents/Compal/luna-RN-DayCareStaff/DayCareStaff
      - /Users/maxhero/Documents/erpv3_web_frontend
      - /Users/maxhero/Documents/erpv3_web_backend
      - /Users/maxhero/Documents/projects/claude-customer-skill-and-hooks
    days: 7
    parallel: 8
  """
)
```

> **規則仍然成立**：`--all` 必開（feature branch commit 不可漏）、`--no-merges`、按 `git config user.name` 過濾。這些規則固化在 agent 內，主 agent 不需重複指定。

**Subagent 回傳結構**（JSON）：

```json
{
  "repos": [
    { "repo": "...", "name": "frontend", "total": 17, "by_type": {...},
      "jira_ids": ["ERPD-11870"], "commits": [...] }
  ],
  "summary": {
    "total_repos": 8,
    "total_commits": 68,
    "all_jira_ids": ["ERPD-11870", "LVB-7963", ...],
    "by_type_aggregate": {"feat": 25, "fix": 28, ...}
  }
}
```

**主 agent 後續處理：**

1. 解析 JSON 組裝成下方輸出格式
2. `summary.all_jira_ids` 直接餵給 STEP 01.5（免再 regex 提取）
3. 任一 repo 有 `error` 欄位 → 在週報「統計」段落附註提示

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

### STEP 01.5: Jira 週活動

> 前置：STEP 00 已通過（MCP 可用、OAuth 有效）。`--skip-jira` 模式下本步驟整段跳過。執行中若發生非預期錯誤（超時、rate limit），回報使用者並詢問是否繼續，不自動 degrade。

從 STEP 01 的 commit message 提取 Jira ID（符合 `\[([A-Z]+-\d+)\]` 的前綴，如 `[ERPD-7777]`、`[LVB-7866]`），並執行兩組查詢補齊事實：

**查詢 A：commit 涉及的 ticket 當前狀態**

對每個出現在本週 commit 的 Jira ID，用 atlassian MCP 查詢當前 status/summary，確認是否已關閉。

**查詢 B：assigned 給我且未完成的 ticket**

JQL：`assignee = currentUser() AND status != Done AND updated >= -{days}d`

（`{days}` 為本 skill 回顧天數，預設 7）

**查詢 C：無 commit 但本週有狀態變更**

JQL：`assignee = currentUser() AND status CHANGED DURING (-{days}d, now())`

從結果中剔除已在查詢 A 出現過的 ticket，只保留「沒對應 commit」的活動（例如只改狀態、只留 comment）。

輸出格式：

```
## Jira 週活動

### 本週 commit 涉及的 Ticket
| ID | Summary | Status | Commit 數 |
|----|---------|--------|----------|

### 我 assigned 但未完成
| ID | Summary | Status | Priority | 最後更新 |
|----|---------|--------|---------|---------|

### 無 commit 但本週有狀態變更
| ID | Summary | Status 變化 |
|----|---------|------------|
```

**Busboy 紀律**：
- 不對 ticket 下評論（「這個很重要」「這個應該優先」）
- 不推測 ticket 之間的關係
- ticket 查不到（權限/ID 錯）→ 標 `(查無資料)` 不要省略那一列
- 無資料的區段輸出「（無）」不要刪除標題

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

綜合 STEP 01 / 01.5 / 02 / 03 結果，並走一遍上方「每週觀察項目」清單，產出結構化週報：

```
## 週報（{起始日} ~ {結束日}）

### 做了什麼
- {按重要性排列的工作項目；每項若對應 Jira ticket 標註 ID}

### Jira 狀態對齊
- 本週 commit 涉及 {N} 個 ticket，已關閉 {M} 個
- 我 assigned 未完成 {K} 個（P0: {x}、P1: {y}、其他: {z}）
- 無 commit 但狀態變更 {J} 個

### 學到什麼
- {從糾正和決策中提取的學習}

### 反覆出現的模式
- {出現 2+ 次的工作流程或行為模式}

### 每週觀察項目現況
- {逐項：項目名 → 本週觀察到的現況/數據 → 建議（繼續觀察 / 調整 / 移除）；清單為空則寫「無」}

### 建議提取為 Skill / Subagent / MCP Server
- {反覆執行的流程} → 依據判斷標準建議最適合的形式：

| 判斷條件 | 建議形式 |
|---------|---------|
| 需要使用者互動/確認的多步驟流程 | **Skill** |
| 獨立可平行、結果回傳即可的子任務 | **Subagent** |
| 多個 skill 重複呼叫同一外部 API/服務 | **MCP Server** |
| 需要跨 session 持久化狀態（DB/cache/索引） | **MCP Server** |
| 提供通用能力（tool library）而非特定流程 | **MCP Server** |

- **Skill**：觸發條件、核心步驟、互動點
- **Subagent**：任務描述、輸入/輸出格式、適合平行的場景、建議放在哪個 skill 內呼叫
- **MCP Server**：共用的 API/服務名稱、哪些 skill 會用到、需要的持久化狀態、建議提供的 tools 清單
  - MCP 建議的判斷依據：ERRORS.jsonl 中跨 skill 的重複 API call pattern、觀察記錄中「每次都要重新查」的模式
  - 定位為「可能適合 MCP」的提示，附理由，由使用者最終決定
```

**週報歸檔：** 將週報寫入 Obsidian vault 歸檔，檔名格式 `{起始日}_{結束日}.md`，路徑為 `~/Documents/obsidian-claude-vault/weekly-reviews/`。加上 frontmatter：

```yaml
---
tags: [weekly-review, {涉及的專案名稱}]
date: {結束日}
period: {起始日} ~ {結束日}
---
```

**同步記憶檔到 Obsidian vault：**

```bash
SCRIPT=~/.claude/scripts/sync-memories-to-obsidian.sh
if [ -f "$SCRIPT" ]; then
  [ -x "$SCRIPT" ] || chmod +x "$SCRIPT"
  bash "$SCRIPT"
else
  echo "(sync-memories-to-obsidian.sh 不存在，跳過 vault 同步)"
fi
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

**輸出整理建議後，等待使用者確認再進入步驟 6。**

---

### STEP 06: Skill 錯誤 Pattern 分析（Subagent A — 與 STEP 08 平行）

> 此步驟與 STEP 08 同時啟動，各用一個 subagent 平行執行。

**Subagent A 任務：**

1. 執行 `python3 ~/.claude/scripts/summarize_errors.py --days {days} --log ~/.claude/.learnings/ERRORS.jsonl`
2. 解析輸出，提取：
   - 各 skill 錯誤數量與佔比
   - 各 tool 錯誤數量
   - 出現 ≥3 次的 recurring pattern
   - 最近 5 筆錯誤
3. 如果 `ERRORS.jsonl` 不存在或為空，回報「無錯誤記錄」並跳過 STEP 07

輸出格式：

```
## 錯誤摘要（{起始日} ~ {結束日}）

### 按 Context 分佈
| Context | 錯誤數 | 佔比 |
|---------|--------|------|

Context 格式：skill:{name} / hook:{name} / {file-path} / unknown

### 高頻 Pattern（≥3 次）
| Pattern | 次數 | 影響 Context | 分類 |
|---------|------|-------------|------|

分類: missing-dependency / wrong-trigger / broken-instruction / environment-drift

### 最近 5 筆錯誤
- {timestamp} [{context}] {tool}: {error first line}
```

---

### STEP 07: 修補建議（依賴 STEP 06 結果）

> 等 STEP 06 完成後執行。若有多個目標需修補，可對每個各開一個 subagent 平行產出建議。

**對每個高頻失敗的 context（≥3 次錯誤）：**

1. 根據 context 類型讀取對應檔案：
   - `skill:{name}` → 讀取 `~/.claude/skills/{name}/SKILL.md`
   - `hook:{name}` → 讀取 `~/.claude/hooks/{name}.*` 或 `~/.claude/scripts/{name}.*`（hook 沒有 SKILL.md，直接讀腳本原始碼）
   - 其他 → 讀取 context 路徑對應的檔案
2. 結合 STEP 06 的錯誤 pattern 分析
3. 判斷 root cause 分類：
   - **missing-dependency**: 缺少二進位工具或套件 → 加 prerequisite check
   - **wrong-trigger**: skill description 太廣，被錯誤觸發 → 收緊 description，加 negative example
   - **broken-instruction**: SKILL.md 中的步驟已過時 → 修正指令語法或參數
   - **environment-drift**: 外部 API/格式變更 → 更新對應步驟
   - **add-fallback**: 步驟偶爾失敗 → 加替代方案
   - **reorder-steps**: 前置條件未滿足就執行 → 調整步驟順序

4. 產出修補建議：

```
### 修補建議：{skill-name}

**Root Cause:** {一句話說明為何失敗}
**Amendment Type:** {分類}
**建議修改：**

--- BEFORE ---
{原文片段}
--- AFTER ---
{修改後片段}

**預期效果：** {修改後應消除哪些錯誤 pattern}
```

5. **不自動修改任何 SKILL.md** — 列出所有建議後等待使用者逐項確認

---

### STEP 08: Amendment 成效追蹤（Subagent B — 與 STEP 06 平行）

> 此步驟與 STEP 06 同時啟動。

**Subagent B 任務：**

1. 讀取 `~/.claude/.learnings/AMENDMENTS.md`
2. 找出所有 Outcome 欄位為空或標記為待追蹤的 amendment
3. 對每筆待追蹤的 amendment：
   - 從 `ERRORS.jsonl` 搜尋該 skill 在 amendment 日期之後的錯誤
   - 比對修補前後的錯誤頻率
   - 判定成效：✅ Fixed / ⚠️ Partial / ❌ Reverted

輸出格式：

```
## Amendment 成效追蹤

### 已追蹤
| 日期 | Skill | 修改摘要 | 修補前錯誤數 | 修補後錯誤數 | 判定 |
|------|-------|---------|------------|------------|------|

### 待追蹤（不足一週或執行次數不足）
| 日期 | Skill | 修改摘要 | 距今天數 | 修補後錯誤數 |
|------|-------|---------|---------|------------|

### 建議回滾
- {skill}: {理由}
```

4. 提出建議後等待使用者確認，才更新 `AMENDMENTS.md` 的 Outcome 欄位

---

## Subagent 執行策略

```
STEP 01 (Subagent: multi-repo-commit-scanner) ← 內部 8 repo 平行掃 git log
  ↓ 主 agent 等聚合 JSON
STEP 01.5 ~ 04: 主 agent 順序執行（Jira / observation / auto memory / 週報產出）
  ↓ 使用者確認
STEP 05: 主 agent 執行（記憶整理）
  ↓ 使用者確認
STEP 06 (Subagent A) ←→ STEP 08 (Subagent B)  ← 平行
  ↓ 等 A 完成
STEP 07 (Subagent C, 可多個) ← 每個 skill 一個 subagent，平行
  ↓ 全部完成
主 agent 彙整結果，等待使用者逐項確認修補
```

**Subagent 一覽**：

| Subagent | 用於 | 平行度 |
|----------|------|--------|
| `multi-repo-commit-scanner` | STEP 01 | 8 repo 同時掃（agent 內部） |
| Subagent A（錯誤分析） | STEP 06 | 與 B 平行 |
| Subagent B（amendment 追蹤） | STEP 08 | 與 A 平行 |
| Subagent C（修補建議，N 個） | STEP 07 | 每個 skill 一個，平行 |

## 注意事項

- 週報和整理建議都需要使用者確認後才執行變更
- 步驟 4 產出週報後暫停，使用者確認後才進入步驟 5
- 步驟 5 每個刪除/合併/升級動作都需要個別確認
- 步驟 5 完成後暫停，使用者確認後才進入步驟 6~8
- 步驟 7 的修補建議需要使用者逐項確認才執行
- 步驟 8 的成效判定需要使用者確認才更新 AMENDMENTS.md
- 如果使用者只說「整理記憶」，直接跳到步驟 5
- 如果使用者只說「review skill errors」，直接跳到步驟 6~8
- `ERRORS.jsonl` 不存在或為空時，步驟 6~8 全部跳過並告知使用者
