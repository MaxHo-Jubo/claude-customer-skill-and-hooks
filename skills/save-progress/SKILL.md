---
name: save-progress
description: 手動存檔當前工作進度，將 task list 狀態和未存的記憶寫入磁碟，適合在 session 結束前、預感 rate limit、或長時間離開前使用
user_invocable: true
---

# Save Progress — 手動存檔工作進度

依序執行以下步驟，每步完成後標記 ✅：

## STEP 01: Dump Task List

1. 呼叫 `TaskList` 取得當前所有任務
2. **有任務**：將完整狀態寫入 `tasks/todo.md`，格式：
   ```markdown
   # Task Progress Snapshot
   > 自動存檔於 YYYY-MM-DD HH:mm

   ## 進行中
   - [ ] [任務主題] — 狀態：in_progress，描述：...，blockers：...

   ## 待處理
   - [ ] [任務主題] — 狀態：pending，描述：...

   ## 已完成
   - [x] [任務主題]
   ```
3. **無任務**：回顧本次 session 對話，將工作摘要寫入 `tasks/todo.md`，格式：
   ```markdown
   # Session Progress Snapshot
   > 自動存檔於 YYYY-MM-DD HH:mm

   ## 本次 session 完成的工作
   - [簡述做了什麼]

   ## 未完成 / 後續待處理
   - [若有的話]
   ```

## STEP 02: 保存未存的記憶

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

## STEP 03: 回報

用一句話告知存檔結果，例如：
- 「已存檔：3 個進行中任務 + 1 筆 feedback memory」
- 「無需存檔，目前沒有進行中的任務或未存的記憶」
