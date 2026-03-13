## Jira 需求驗收報告

**Issue**: CMD-276 - 115年彰化照管-系統優化-派案清單查詢改為分頁查詢-FE
**Branch**: CMD-276/feat/alex_cheng/派案分頁查詢
**比對範圍**: branch diff from master + uncommitted changes

### 需求項目

| # | 需求描述 | 狀態 | 對應改動 |
|---|---------|------|---------|
| 1 | 派案頁面清單改為分頁形式查詢 | ⚠️ 部分實作 | `web/actioncreators/caseAssignActionCreator.js:19-22`（API 改為帶入 limit/skip 參數）、`web/reducers/caseAssignReducer.js:16-17,24-30`（新增 caseTotal、isFetchingCaseList state，解析分頁回應） |
| 2 | 查詢條件分為「未派案」、「已派案(尚未開始服務)」 | ⚠️ 部分實作 | `public/locales/zh_TW/case.json:7-12`（新增 i18n 翻譯 caseAssignStatus.unassigned / assigned） |
| 3 | 搜尋介面改動（依照 Jira 附圖的搜尋列設計） | ⚠️ 部分實作 | `public/locales/zh_TW/case.json:13`（新增 caretaker: "照專" 翻譯） |

### 總結

- ✅ 已實作: 0/3
- ⚠️ 部分實作: 3/3
- ❌ 未實作: 0/3

### 備註

- **需求 1 — 分頁查詢**：後端資料層（action creator + reducer）已完成改動，API 呼叫支援 `limit`/`skip` 參數，reducer 也能處理分頁回應格式（`list` + `total`）。但**缺少前端 UI 分頁元件**（如分頁器、頁碼切換、每頁筆數選擇等），目前 diff 中沒有任何 React 元件或頁面層級的改動。
- **需求 2 — 查詢條件切換**：i18n 翻譯已加入「未派案」與「已派案（尚未開始服務）」的文字，但**缺少對應的 UI 元件**（tab 切換或 dropdown），也沒看到查詢條件的 state 管理和事件處理邏輯。`fetchCaseAssignCaseList` 的預設 type 從 `2` 改為 `'1'`，但沒有看到 UI 層如何讓使用者切換 type。
- **需求 3 — 搜尋介面**：僅新增「照專」翻譯，**缺少搜尋列的 UI 實作**（Jira 附圖顯示有搜尋條件列，但 diff 中沒有相關元件）。
- **額外觀察**：`submitAutoAssign` 和 `removeAssign` 改為帶入 `searchData` 以便操作後保持查詢狀態重新載入，這是正確的做法，但這也暗示前端應有管理 `searchData` 的邏輯，目前未見。
- **整體評估**：資料層（Redux action + reducer）的分頁改動已到位，但前端 UI 層（頁面元件、分頁器、查詢條件切換、搜尋列）完全缺失。建議補上頁面層級的改動。
