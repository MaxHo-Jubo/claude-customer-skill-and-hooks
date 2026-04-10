---
name: weekly-review
description: "每週工作回顧與記憶整理。彙整 commit、觀察記錄、auto memory，產出週報並清理過期記憶。當使用者提到 /weekly-review、「週報」、「整理記憶」、「回顧這週」時觸發。"
version: 1.3.0
---

# Weekly Review — 週回顧與記憶整理

每週執行一次，回顧工作成果、整理記憶系統、提取可複用的模式、分析 skill 錯誤並驅動改善。

## 前置依賴

- **PostToolUse hook**: `~/.claude/hooks/post_tool_error.py` — 自動記錄所有 tool 失敗到 `~/.claude/.learnings/ERRORS.jsonl`
- **摘要腳本**: `~/.claude/scripts/summarize_errors.py` — 錯誤統計報告
- 安裝方式見 `skill-error-tracker/setup_skill_error_tracker.sh`

## 使用方式

- `/weekly-review` — 完整八步驟回顧
- `/weekly-review --days 14` — 指定回顧天數（預設 7 天）
- 使用者說「整理記憶」— 只執行步驟 5（記憶整理）
- 使用者說「review skill errors」— 只執行步驟 6~8（錯誤分析循環）

## 執行步驟

### STEP 01: Git 工作摘要

收集指定天數內所有專案的 commit 紀錄，按專案分組。

```bash
# 對每個已知專案目錄執行，只抓使用者自己的 commit
# 必須用 --all 掃所有 branch，否則 feature branch 上的 commit 會遺漏
git log --all --since="7 days ago" --oneline --no-merges --author="$(git config user.name)"
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
STEP 01~04: 主 agent 順序執行（週報產出）
  ↓ 使用者確認
STEP 05: 主 agent 執行（記憶整理）
  ↓ 使用者確認
STEP 06 (Subagent A) ←→ STEP 08 (Subagent B)  ← 平行
  ↓ 等 A 完成
STEP 07 (Subagent C, 可多個) ← 每個 skill 一個 subagent，平行
  ↓ 全部完成
主 agent 彙整結果，等待使用者逐項確認修補
```

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
