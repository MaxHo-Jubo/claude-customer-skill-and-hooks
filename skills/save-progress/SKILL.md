---
name: save-progress
description: 手動存檔當前工作進度，寫成可交接給新 session 的交接紀錄（有 Jira 票寫進 Jira 開發筆記、沒有就依 branch 名稱另存），檢查 Teams 上有無未同步到 Jira 的討論，並把未存的記憶寫入磁碟，適合在 session 結束前、預感 rate limit、或長時間離開前使用
version: 1.2.0
---

# Save Progress — 手動存檔工作進度

依序執行以下步驟，每步完成後標記 ✅：

## STEP 01: 決定交接紀錄寫到哪

1. `{CLAUDE_DIR}` = 主要工作目錄（primary working directory）的**絕對路徑** + `/.claude/`，與 `~/.claude/skills/jira/SKILL.md` 同一套規則；禁止用相對路徑 `.claude/`（git 操作會改變 cwd）。目錄不存在就建立
2. 取得 branch 與 Jira 編號：
   ```bash
   git -C "<主要工作目錄>" branch --show-current
   git -C "<主要工作目錄>" branch --show-current | grep -oE '[A-Z]+-[0-9]+' | head -1
   ```
3. 依下表決定目標（由上往下取第一個成立的）：

   | 條件 | 目標檔 | 寫法 |
   |---|---|---|
   | branch 含 Jira 編號 | `{CLAUDE_DIR}/{ISSUE_ID}.md`（`/jira` 直接讀得到） | 只替換檔案中的 `## 交接紀錄` 段落（從該標題到下一個 `## ` 或檔尾），不動其他段落；沒有這段就加在檔尾。檔案不存在 → 先依 jira skill 的「開發筆記模板」建立，再加這段 |
   | 有 branch、但沒有 Jira 編號 | `{CLAUDE_DIR}/handoff-{branch}.md`，`{branch}` 中的 `/` 換成 `-`（例：`chore/sync-setting` → `handoff-chore-sync-setting.md`） | 整檔覆寫 |
   | 不是 git repo，或 detached HEAD（branch 為空） | `{CLAUDE_DIR}/handoff-{主要工作目錄的資料夾名稱}.md` | 整檔覆寫，並在 STEP 05 回報時說明走了 fallback |

   `handoff-{branch}.md` 的命名規則同時被 `~/.claude/skills/jira/SKILL.md` 步驟 3 引用來讀檔，改這裡要一起改那裡。

   **不碰 `tasks/todo.md`**（那是 GATE-2 的計畫檔，含已確認的 checkbox）。

## STEP 02: 收集事實並寫交接紀錄

1. 收集事實，**用指令觀測，不要憑記憶**：
   - `git -C "<主要工作目錄>" status --short` 與 `git -C "<主要工作目錄>" diff --stat HEAD` → 未 commit 的修改
   - `git -C "<主要工作目錄>" log --oneline -10` → 本次 session 的 commit（只列本 session 做的）
   - 呼叫 `TaskList` 取得任務狀態；沒有這個工具或沒有任務 → 回顧本次 session 對話整理
2. 依下方格式寫入 STEP 01 決定的目標。沒有內容的項目寫「無」，不要刪掉標題；沒跑過驗證就寫「未驗證」，不可寫成 pass：

   ```markdown
   ## 交接紀錄

   > 更新於 YYYY-MM-DD HH:mm｜branch：`{branch 或「無」}`

   ### 目標
   - 一句話說明這段工作要達成什麼

   ### 架構決策（完整保留，不摘要）
   - 決策：…｜理由：…｜否決的方案與原因：…

   ### 已修改檔案與關鍵變更
   - `path/to/file` — 改了什麼、為什麼（已 commit 標 commit hash，未 commit 標「未 commit」）

   ### 驗證狀態
   - `執行的指令` → pass / fail（附關鍵輸出末幾行）
   - 未驗證：…（缺什麼、怎麼驗）

   ### 任務狀態
   - [ ] [任務] — 進行中，blockers：…
   - [ ] [任務] — 待處理
   - [x] [任務] — 已完成

   ### 未完成 TODO 與 rollback 備註
   - …

   ### 下一步
   - 新 session 接手後第一件該做的事

   ### 待使用者回答
   - …
   ```

## STEP 03: Teams 討論同步檢查（僅 branch 含 Jira 編號時）

1. branch 沒有 Jira 編號 → 跳過，STEP 05 回報「Teams 同步：跳過（無 Jira 編號）」
2. 有 → 照 `~/.claude/skills/jira/SKILL.md`「Teams 同步流程」跑 T1～T4（流程只定義在那裡，不在此複製）
3. 有 `SINCE` 之後的新訊息 → 顯示草稿，問使用者要不要貼到 Jira；確認才進 T5，不確認就跳過
4. 本步驟失敗（M365 未授權、搜尋錯誤）不影響已寫好的交接紀錄，照 T4 錯誤出口記下原因，STEP 05 一併回報，然後繼續 STEP 04

## STEP 04: 保存未存的記憶

檢查本次 session 中是否有以下資訊尚未存到 auto memory：

- 使用者的糾正或偏好（→ feedback memory）
- 重要的架構決策或技術選擇（→ project memory）
- 本次 session 發現的關鍵資訊（→ reference memory）

有就存，沒有就跳過。

## On Error

任何步驟執行失敗時，將錯誤資訊以 JSON 格式 append 到 `~/.claude/.learnings/ERRORS.jsonl`：
```json
{"timestamp":"ISO8601","skill":"save-progress","step":"STEP XX","error":"錯誤描述","context":"觸發情境"}
```

## STEP 05: 回報

用一句話告知存檔結果，**附上交接紀錄的絕對路徑**，例如：
- 「已存檔到 `/…/.claude/<TICKET>.md` 的交接紀錄：3 個進行中任務 + 1 筆 feedback memory」
- 「已存檔到 `/…/.claude/handoff-chore-sync-setting.md`（無 Jira 編號，依 branch 命名）」
- 「已存檔到 `/…/.claude/handoff-<資料夾名>.md`（非 git repo／detached HEAD，走 fallback）」

另起一行回報 STEP 03 結果：已貼留言（附 commentId）／使用者略過／已同步到最新／無命中／跳過（無 Jira 編號）／失敗（附原因），用 T4 的對應措辭。
