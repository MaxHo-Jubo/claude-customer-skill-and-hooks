## Jira 需求驗收報告

**Issue**: CMD-276 - 115年彰化照管-系統優化-派案清單查詢改為分頁查詢-FE
**Branch**: CMD-276/feat/alex_cheng/派案分頁查詢
**比對範圍**: uncommitted changes

### 需求項目

| # | 需求描述 | 狀態 | 對應改動 |
|---|---------|------|---------|
| 1 | 派案頁面清單改為分頁形式查詢 | ✅ 已實作 | `web/actioncreators/caseAssignActionCreator.js:13` — `fetchCaseAssignCaseList` 參數改為帶 `limit`/`skip` 的分頁參數；`web/reducers/caseAssignReducer.js:12-13` — 新增 `caseTotal`、`isFetchingCaseList` state；`web/reducers/caseAssignReducer.js:19-27` — 處理 REQUEST/SUCCESS/FAILURE，回寫 `list` 與 `total` |
| 2 | 查詢條件分為「未派案」、「已派案(尚未開始服務)」 | ✅ 已實作 | `web/enums/CaseAssignEnum.js:7-8` — 定義 `UNASSIGNED`(value='1') 與 `ASSIGNED`(value='2')；`web/pages/CaseAssign/components/AssignSearchForm.jsx:31-34` — 下拉選單渲染兩個選項；`public/locales/zh_TW/case.json:11-14` — i18n 翻譯 `unassigned`="未派案"、`assigned`="已派案（尚未開始服務）" |
| 3 | 新增搜尋表單 UI 供使用者輸入查詢條件 | ✅ 已實作 | `web/pages/CaseAssign/components/AssignSearchForm.jsx:1-54` — 新增完整搜尋表單元件，包含派案狀態、個案編號、姓名、身分證、年齡、區域、照專等欄位，以及搜尋/清除按鈕 |
| 4 | 自動派案與批量退回後保留當前搜尋條件重新查詢 | ✅ 已實作 | `web/actioncreators/caseAssignActionCreator.js:21-27` — `submitAutoAssign` 與 `removeAssign` 新增 `searchData` 參數；`web/actioncreators/caseAssignActionCreator.js:32-36,44-48` — `gotSubmitAutoAssign.success` 與 `gotRemoveAssign.success` 從 `request.searchData` 取回搜尋條件傳入 `fetchCaseAssignCaseList` |
| 5 | 載入狀態管理（分頁查詢期間顯示 loading） | ✅ 已實作 | `web/reducers/caseAssignReducer.js:13` — 新增 `isFetchingCaseList` state；`web/reducers/caseAssignReducer.js:19-27` — REQUEST 設 true、SUCCESS/FAILURE 設 false |

### 總結

- ✅ 已實作: 5/5
- ⚠️ 部分實作: 0/5
- ❌ 未實作: 0/5

### 備註

- 搜尋表單（`AssignSearchForm.jsx`）預設 `type` 為 `CaseAssignEnum.UNASSIGNED.value`（即 '1'，未派案），與 `fetchCaseAssignCaseList` 的預設參數 `{ type: '1', limit: 50, skip: 0 }` 一致，邏輯連貫。
- `fetchCaseAssignCaseList` 原本只帶 `type` 參數（硬編碼 `type=2`），現改為接收完整的 data 物件（含 `type`、`limit`、`skip` 等），正確支援分頁與多條件查詢。
- 由於 Jira 描述中附帶的截圖無法直接檢視（blob URL），搜尋表單的欄位佈局是否完全符合截圖中的 UI 設計無法從程式碼層面確認，建議人工比對 UI。
- diff 中未發現不屬於需求範圍的額外改動，所有變更皆圍繞派案分頁查詢功能。
