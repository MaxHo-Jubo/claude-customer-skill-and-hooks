---
name: upgrade-to-status
description: "將專案升級為 status.md 架構，在 tasks/status.md 建立共識文件（Milestone / 北極星 / Insight / Current / Next）。從現有 tasks/todo.md、tasks/lessons.md、README、git log 推斷初值，讓使用者確認後寫入。適用 side project，不適用已有 Jira 流程的公司專案。當使用者提到 /upgrade-to-status、「升級到 status.md」、「建立 status.md」、「這個專案弄 status」時觸發。"
version: 1.1.0
context: fork
---

# Upgrade to Status — 建立專案 status.md

把專案升級為「status.md 共識文件」架構。靈感來自多專案管理的 busboy 策略，適合 side project 需要記錄 milestone、北極星指標、insight 的情境。

## 適用場景

- ✅ Side project（自己的 repo）
- ✅ 專案沒有 Jira 或類似追蹤系統
- ✅ 想要一份「開 VSCode 就看到當前狀態」的共識文件
- ❌ 公司專案（已有 Jira + tasks/todo.md 流程，不需要）
- ❌ 純工具 repo（設定檔、dotfile 類）

## Busboy 紀律

- **只用本 skill 定義的 6 個區段**：Milestone / 北極星 / Insight / Current / Next / Frozen。禁止發明 Risk、決議、深度反思等段落
- **推斷不到就留空**：寫「待填」不要亂湊。北極星指標尤其必須使用者自己想，AI 不幫忙瞎猜
- **不覆蓋**：status.md 已存在就只做檢查，不寫入

## status.md Schema

```markdown
---
last_updated: {YYYY-MM-DD}
milestone: {current milestone label}
---

# {專案名} — Status

> 共識文件。session 開場讀這份，結束時用 `/daily-review` 或手動 busboy 回填。

## Milestone
{ dev / alpha / beta / 上線 / 維護 }

## 北極星指標
- **指標**: { 例：月營收 / DAU / 付費轉換率 }
- **當前**: { 數字 }
- **目標**: { 數字 }
- **更新頻率**: { weekly / monthly }

## Insight
<!-- 架構決策、技術洞察、domain knowledge。只記「為什麼」，不記「做了什麼」（做了什麼看 git log） -->
- { insight 1 }

## Current
<!-- 當前正在做的事。checkbox 格式 -->
- [ ] { task }

## Next
<!-- 超越當前 session 的下一步。不是 checkbox，是「下一個要處理的主題」 -->
- { 主題 }

## Frozen
<!-- 暫時不做但不想忘記。從 Next 搬進來，解凍時搬回去 -->
- { 凍結項目 }
```

## 執行步驟

### STEP 01: 確認專案根目錄

```bash
git rev-parse --show-toplevel 2>/dev/null
```

- 不在 git repo 內 → 詢問使用者專案根目錄
- 使用者目前位置不是根目錄 → 提示切換

### STEP 02: 檢查已存在的 status.md

```bash
test -f tasks/status.md && echo "EXISTS" || echo "NONE"
```

- EXISTS → 讀取現有內容，列出哪些區段已填、哪些為空，詢問使用者要「補全」還是「結束」
  - 使用者選「補全」→ 對**空欄位**套用 STEP 03-04 推斷流程（已填欄位保持不動），然後走 STEP 05 寫回檔案
  - 使用者選「結束」→ 跳出 skill，不做任何變更
- NONE → 進入 STEP 03

### STEP 03: 讀取現有資訊推斷初值

依序檢查並讀取：

| 來源 | 用途 |
|------|------|
| `tasks/todo.md` | 未勾選項目 → Current 區段候選 |
| `tasks/lessons.md` | 教訓/決策 → Insight 區段候選 |
| `README.md` | 專案描述、milestone 線索 |
| `package.json` / `pyproject.toml` / `go.mod` | 專案名 |
| `git log --oneline -n 20` | 近期工作主題 |

**推斷紀律**：
- 推斷到的值標註 `[auto-inferred]`，讓使用者一眼看出需要校對
- 北極星指標**永遠留空**，不推斷
- Milestone 採嚴格規則（只認結構化標示，禁止敘述文字推斷）：
  - ✅ 認：README frontmatter 有 `stage: beta` / `status: alpha` / `phase: maintenance` 這類 YAML 欄位
  - ✅ 認：`package.json` version 含 `-alpha` / `-beta` / `-rc` pre-release tag；CHANGELOG 明確版本標記
  - ❌ 不認：README 敘述文字（例如「目前 alpha 階段」「正在 beta 測試中」）。此類一律留空
  - 理由：敘述文字會漂移（今天 alpha、下週 alpha-ish），無一致性；結構化欄位是作者刻意留下的狀態宣告

### STEP 04: 產出初稿

用 STEP 03 推斷值填入 schema，用 heredoc 顯示完整初稿給使用者。格式：

```
## 即將寫入 tasks/status.md

{完整 schema 內容}

---
【需要你決定】
- 北極星指標是什麼？（必填）
- Milestone 標籤：{推斷值 or 留空}
- Current 從 todo.md 搬 N 項過來，要全搬還是挑？
- 是否要保留 tasks/todo.md？（可併入 Current、可獨立、可刪除）
```

**等待使用者回覆後才寫入。**

### STEP 05: 寫入 tasks/status.md

- 用 Write tool 寫入（不存在才寫）
- frontmatter 的 `last_updated` 設今天
- 提醒使用者：「tasks/status.md 已建立。下一步：git add 進版本控制」

### STEP 06: 決定與 todo.md 的關係

根據使用者在 STEP 04 的回覆：

| 使用者選擇 | 動作 |
|----------|------|
| 併入 Current 段 | todo.md 未勾項搬進 status.md，建議刪除 todo.md |
| 獨立並存 | 不動 todo.md，status.md 的 Current 只放本週重點 |
| 刪除 todo.md | 搬完後 `rm tasks/todo.md` |

**刪除動作需使用者明確確認。**

### STEP 07: 後續建議

輸出一次性提示：

```
## 後續使用

- 每次 session 開場：讀 tasks/status.md 對齊上下文
- Session 結束：手動更新 Insight / Current 進度
- 定期檢視：/daily-review 或 /weekly-review
- status.md 要跟 code 一起 commit（source of truth 跟專案同命運）
```

## 注意事項

- 本 skill **不自動把 status.md 同步到任何地方**（無主控板、無 cloud）
- 本 skill **不修改 daily-review / weekly-review skill**。這兩個 skill 目前仍讀 todo.md，未來若需要讀 status.md 再單獨處理
- 重跑本 skill **不會覆蓋現有 status.md**，只做補全檢查
- 公司專案跑這個 skill 前先想清楚：你真的需要嗎？Jira + todo.md + lessons.md 已覆蓋大部分場景
