---
name: daily-review
description: "今日工作回顧。彙整當日 commit、auto memory 變動、各專案未勾 todo，輸出 digest 並提出明日 1-3 個焦點候選。weekly-review 的輕量版，不做記憶整理、不跑 error 分析、不歸檔 Obsidian。當使用者提到 /daily-review、「今日回顧」、「今天做了什麼」、「daily digest」、「明日焦點」時觸發。"
version: 1.0.1
context: fork
---

# Daily Review — 今日回顧與明日焦點

每日執行一次（通常在 session 結束前或隔日開工前），產出當日 digest 並列出明日該專注的事。

## 與 weekly-review 的分工

| 項目 | daily-review | weekly-review |
|------|-------------|--------------|
| 頻率 | 每日 | 每週 |
| commit 範圍 | 1 天 | 7 天 |
| 記憶整理 | ❌ 不做 | ✅ STEP 05 |
| Obsidian 歸檔 | ❌ 不做 | ✅ STEP 04 |
| Error 分析 | ❌ 不做 | ✅ STEP 06-08 |
| 輸出長度 | 短（< 50 行） | 長（完整週報） |

daily-review 只負責「digest + 明日焦點」。需要深度整理時才跑 weekly-review。

## Busboy 紀律

套用 weekly-review 的 busboy 紀律：

- **只歸位，不發明章節**：對齊本 skill 定義的 output schema，禁止產出「深度反思 / 今日亮點 / 啟示」這類新段落
- **只填既有欄位**：缺資料就寫「無」，不要自動補湊
- **不做價值判斷**：不評論工作內容好壞，只陳述事實

違反紀律的徵兆：輸出變長、開始講「值得注意的是」。看到就停下。

## 使用方式

- `/daily-review` — 預設回顧今天（00:00 起）
- `/daily-review --yesterday` — 回顧昨天整天

## 執行步驟

### STEP 01: 今日 Commit

對 PROJECT-MAP 定義的每個專案目錄執行：

```bash
git log --all --since="midnight" --until="now" --oneline --no-merges --author="$(git config user.name)"
```

（`--yesterday` 參數時改為 `--since="yesterday 00:00" --until="yesterday 23:59"`）

**Caveat**：`--author="$(git config user.name)"` 只抓本機 git user 的 commit。若專案有多人協作且你想看團隊全部活動，改用 `--all`（不加 author 參數）。fixture 測試環境下 commit 的 author 可能不是本機 user，需放寬過濾。

輸出格式：

```
## 今日 Commit（{日期}）

### {專案名稱}
- {hash} {commit message}

### 無 commit 的專案
- {專案名稱}
```

### STEP 02: 今日 Auto Memory 變動

```bash
find ~/.claude/projects/*/memory/ -name "*.md" -mtime -1 -type f 2>/dev/null
```

輸出格式：

```
## 今日 Memory 變動

| 檔案 | 類型 | 變動 |
|------|------|------|
| feedback_xxx.md | feedback | 新增/更新 |
```

若無變動，輸出「今日無 memory 變動」。

### STEP 03: 未完成 Todo 掃描

掃描各專案的 `tasks/todo.md`，找出未勾選的 checkbox（`- [ ]`）。

```bash
for project in {PROJECT-MAP 路徑}; do
  [ -f "$project/tasks/todo.md" ] && grep -H "^- \[ \]" "$project/tasks/todo.md"
done
```

輸出格式：

```
## 未完成 Todo

### {專案名稱}
- [ ] {todo 內容}
```

若所有 todo.md 都乾淨，輸出「各專案 todo.md 無未完成項目」。

### STEP 04: 明日焦點候選

根據 STEP 01-03 的輸出，從未完成 todo + 今日未收尾的 commit 主題中，挑出 1-3 個**候選焦點**。

輸出格式：

```
## 明日焦點候選

1. {專案名}: {焦點描述} — 來源: {todo.md / 今日 commit 延續}
2. ...
```

**紀律**：
- 最多 3 個，寧少勿多
- 只從已有資訊挑，不自己發明新任務
- 用「候選」不是「決定」，讓使用者自己選

### STEP 05: 輸出完整 digest

組裝 STEP 01-04 為單一 digest（直接顯示給使用者，不寫入檔案）：

```
# Daily Review — {日期}

{STEP 01 輸出}

{STEP 02 輸出}

{STEP 03 輸出}

{STEP 04 輸出}
```

## 注意事項

- 本 skill 只讀不寫，**不修改任何檔案**（包括 memory、todo.md、Obsidian）
- 不呼叫 claude-mem（那是 weekly-review STEP 02 的工作）
- 不跑 error 分析（那是 weekly-review STEP 06-08 的工作）
- 若需要深度整理或修補建議，請使用 `/weekly-review`
- 輸出保持簡短，全部內容應能一頁顯示
