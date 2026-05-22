<!--
================================================================================
jira-test-report skill — progress.md 範本（v2.5.1+）
================================================================================
用法：
  1. skill 在 step 0.5 / 跑測試前 建檔 .claude/{ISSUE_KEY}-progress.md
  2. 把下方範本內容複製過去，並依 issue 替換 placeholder：
     - ERPD-XXXX → 實際 issue key
     - Mode      → script 或 interactive
     - Variant   → r18 / r15 / 留空（無雙環境比對時）
     - 時間戳記  → 實際開工 / 更新時間
     - Phase A step 條目 → 從測試步驟清單抽出，全部 `[ ]` 未勾
  3. 每跑完一個 step → Edit progress.md 對應條目改 `[x]` + 填 status / screenshot / run at
  4. Phase B 每張 upload 完 → 改 `[x]` + 記 attachment id
  5. Phase C comment 發完 → 改 `[x]`

resume 邏輯：
  - 啟動帶 `--resume` → 讀本檔，Phase A/B/C 跳過已 `[x]` 的 step
  - 互動模式：主 context 直接 Edit；腳本模式：cjs 內 step.cjs::createStepRunner 自動寫
================================================================================
-->

## Test Run Progress — ERPD-XXXX

Mode: script  (or interactive)
Variant: r18
Started: 2026-05-08 14:00
Last update: 2026-05-08 14:45

### Phase A: 跑測試
- [x] 01 page-loaded
  - Status: PASS
  - Screenshot: .claude/ERPD-XXXX-temp/r18/01-page-loaded.png
  - Run at: 2026-05-08 14:23
- [x] 02 click-add
  - Status: PASS
  - Screenshot: .claude/ERPD-XXXX-temp/r18/02-click-add.png
  - Run at: 2026-05-08 14:24
- [ ] 03 fill-form   ← 下次 --resume 從這裡接
- [ ] 04 submit
- [ ] 05 verify

### Phase B: Jira 截圖上傳
- [x] 01-page-loaded.png → attachment id 12345
- [x] 02-click-add.png → attachment id 12346
- [ ] 03-fill-form.png    （尚未跑到，暫不 upload）

### Phase C: Jira inline comment
- [ ] comment posted    （所有 step 跑完才發）
