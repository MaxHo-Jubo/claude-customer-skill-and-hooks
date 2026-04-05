# spec-design Skill 測試分析：`/spec-design 新增使用者匯出 CSV 功能`

## 測試情境

使用者輸入：`/spec-design 新增使用者匯出 CSV 功能`

這是一個帶有明確需求描述的直接觸發，不是無參數的 `/spec-design`。

---

## 問題 1：從哪個 Phase 開始？為什麼？

**答：從 Phase 1（Brainstorming）開始，跳過 Phase 0。**

根據 SKILL.md Phase 0 的「跳過條件」：

> 跳過條件：使用者帶著明確需求直接來（如 `/spec-design 新增使用者匯出功能`），可跳過 Phase 0 直接進 Phase 1。

使用者的輸入 `/spec-design 新增使用者匯出 CSV 功能` 與文件中的範例 `/spec-design 新增使用者匯出功能` 幾乎完全一致，屬於「帶著明確需求直接來」的情況。需求描述已包含：

- **動作**：匯出
- **對象**：使用者資料
- **格式**：CSV

這三個關鍵資訊足以作為 brainstorming 的輸入上下文，不需要先用 openspec explore 自由探索問題空間。

---

## 問題 2：是否跳過 Phase 0？為什麼？

**答：是，跳過 Phase 0。**

理由：

1. **符合跳過條件**：需求描述明確，不是模糊的「我想改善匯出體驗」或「資料匯出有問題」，而是具體的「新增使用者匯出 CSV 功能」。
2. **Phase 0 的定位是 thinking partner**：適用於問題空間不明確、需要挑戰假設、重新定義問題的情境。本需求不需要重新定義問題。
3. **brainstorming 已內建需求釐清**：Phase 1-4 的 brainstorming 流程包含「需求釐清（互動式對話）」，細節問題（匯出哪些欄位？權限控制？檔案大小限制？）會在 brainstorming 階段自然處理。

**但有一個例外情境值得注意**：如果這個專案的 codebase 已經有匯出相關功能（例如匯出 PDF），Phase 0 的「讀 codebase 了解現有架構」會很有價值。不過 skill 的跳過條件是基於需求明確度判斷，不是基於 codebase 複雜度，所以仍然跳過。Brainstorming 的「專案 context 探索」會補上這個缺口。

---

## 問題 3：第一個動作是什麼？

**答：調用 `superpowers:brainstorming` skill。**

具體步驟：

1. **使用 Skill tool 調用 `superpowers:brainstorming`**，將使用者的需求描述「新增使用者匯出 CSV 功能」作為初始上下文傳入。

2. Brainstorming skill 會接手執行以下工作（Phase 1-4）：
   - **專案 context 探索**：讀取 codebase 了解現有架構、技術棧、相關模組
   - **需求釐清**：透過互動式對話確認細節，例如：
     - 匯出哪些欄位？全部還是可選？
     - 誰有權限匯出？角色限制？
     - 資料量多大？需要非同步處理嗎？
     - 匯出觸發方式？按鈕位置？
     - CSV 編碼？BOM？分隔符號？
   - **方案比較與推薦**：比較不同實作方案（前端生成 vs 後端生成、同步 vs 非同步、串流 vs 一次性等）
   - **設計呈現與確認**：將確認的設計決策整理給使用者確認

3. Brainstorming 結束後，取得已確認的設計內容，進入 Phase 5（撰寫 openspec）。

**注意**：根據 CLAUDE.md 的 GATE-1 需求確認規則，在調用 brainstorming 之前，理論上應該先用一句話重述需求請使用者確認。但由於 brainstorming skill 本身就包含需求釐清的互動式對話，且使用者已經明確給出需求描述，這兩個流程會自然合併。實務上，brainstorming 的第一步就是確認需求理解是否正確。

---

## 完整流程預覽（不執行）

如果完整跑完，流程如下：

| Phase | 動作 | 互動 |
|-------|------|------|
| ~~0~~ | ~~跳過~~ | - |
| 1-4 | 調用 `superpowers:brainstorming` | 與使用者互動釐清需求 |
| 5.1 | 檢查專案是否有 `openspec/` 目錄 | 無 → 執行 `openspec init` |
| 5.2 | `openspec new change "user-csv-export"` | 無 |
| 5.3 | `openspec status --change "user-csv-export" --json` | 無 |
| 5.4 | 依序填入 artifacts（proposal → specs → design → tasks） | 無 |
| 5.5 | `openspec validate --changes` | 無 |
| 5.6 | 詢問使用者是否 commit | 需確認 |
| 6 | 4 個 Opus subagent 平行 review | 無 |
| 7 | 修正 🔴 問題，重跑 review（最多 3 輪） | 無 |
| 8 | Plan mode 互動式規劃，產出 plan.md | 與使用者互動 |
| 9 | 4 個 Opus subagent 平行 plan review + 迭代 | 無 |
| 10 | 使用者選擇下一步（A/B/C） | 需確認 |

---

## 關鍵判斷摘要

| 問題 | 結論 | 依據 |
|------|------|------|
| 起始 Phase | Phase 1（Brainstorming） | 需求明確，符合 Phase 0 跳過條件 |
| 是否跳過 Phase 0 | 是 | SKILL.md 明文規定：帶明確需求 → 跳過 |
| 第一個動作 | 調用 `superpowers:brainstorming` | Phase 1-4 由 brainstorming skill 執行 |
