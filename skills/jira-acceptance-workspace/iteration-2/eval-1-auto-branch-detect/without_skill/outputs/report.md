# CMD-276 驗收報告

## Jira 需求摘要

**票號**: CMD-276
**標題**: 115年彰化照管-系統優化-派案清單查詢改為分頁查詢-FE
**指派**: Alex Cheng
**狀態**: 審核中

### 需求內容

1. 將派案頁面清單改為**分頁形式查詢**
2. 查詢條件分為「**未派案**」、「**已派案（尚未開始服務）**」
3. 提供搜尋表單進行條件搜尋

---

## Branch 資訊

- **Branch**: `CMD-276/feat/alex_cheng/派案分頁查詢`
- **基於**: `main`

## 變更檔案清單

| 檔案 | 說明 |
|------|------|
| `web/pages/CaseAssign/components/AssignSearchForm.jsx` | 新增派案搜尋表單元件 |
| `web/reducers/caseAssignReducer.js` | Reducer 加入 `caseTotal`、`isFetchingCaseList` 狀態 |
| `web/actioncreators/caseAssignActionCreator.js` | Action creator 加入 `limit`/`skip` 分頁參數 |
| `web/enums/CaseAssignEnum.js` | 新增派案狀態列舉（未派案/已派案） |
| `public/locales/zh_TW/case.json` | i18n 翻譯：派案狀態、照專等欄位 |

---

## 逐項驗收

### 1. 派案清單改為分頁查詢

| 檢查項目 | 結果 | 說明 |
|----------|------|------|
| API 呼叫帶分頁參數 | ✅ 通過 | `fetchCaseAssignCaseList` 預設帶 `limit: 50, skip: 0` |
| Reducer 儲存總筆數 | ✅ 通過 | `caseTotal` 欄位從 `action.data.total` 取值 |
| 載入狀態管理 | ✅ 通過 | `isFetchingCaseList` 在 REQUEST/SUCCESS/FAILURE 正確切換 |
| 前端分頁元件 | ⚠️ 未見 | 搜尋表單已完成，但**未看到分頁 UI 元件**（如 Pagination 元件）來切換頁碼 |

### 2. 查詢條件：未派案 / 已派案（尚未開始服務）

| 檢查項目 | 結果 | 說明 |
|----------|------|------|
| Enum 定義 | ✅ 通過 | `CaseAssignEnum` 定義 `UNASSIGNED (value: '1')` 和 `ASSIGNED (value: '2')` |
| 搜尋表單下拉選項 | ✅ 通過 | `AssignSearchForm` 中有 select 下拉，選項對應未派案/已派案 |
| i18n 翻譯 | ✅ 通過 | `case.json` 中 `caseAssignStatus.unassigned` = "未派案"，`assigned` = "已派案（尚未開始服務）" |
| 預設查詢條件 | ✅ 通過 | `defaultValues.type` 預設為 `CaseAssignEnum.UNASSIGNED.value`（未派案） |

### 3. 搜尋表單欄位

| 欄位 | 結果 | 說明 |
|------|------|------|
| 派案狀態 | ✅ 通過 | 下拉選單 |
| 個案編號 (caseCode) | ✅ 通過 | 文字輸入 |
| 姓名 (name) | ✅ 通過 | 文字輸入 |
| 身分證字號 (personalId) | ✅ 通過 | 文字輸入 |
| 年齡 (age) | ✅ 通過 | 數字輸入（min=0, step=1） |
| 服務地址區域 (serviceAddress_regionId) | ✅ 通過 | AddressSelector 元件 |
| 照專姓名 (caretakerName) | ✅ 通過 | 文字輸入 |
| 搜尋按鈕 | ✅ 通過 | 送出表單，搜尋中時 disabled |
| 清除按鈕 | ✅ 通過 | 重設表單為預設值 |

---

## 總結

### 已完成項目
- ✅ 搜尋表單完整實作，包含所有查詢條件欄位
- ✅ 未派案/已派案（尚未開始服務）查詢條件正確實作
- ✅ API 層已支援分頁參數（limit/skip）
- ✅ Reducer 正確儲存分頁所需的 total 與載入狀態
- ✅ i18n 翻譯完整

### 待確認 / 潛在問題

| # | 嚴重度 | 問題 |
|---|--------|------|
| 1 | 🔴 高 | **缺少分頁 UI 元件**：Reducer 已有 `caseTotal` 但在本次變更中未看到 Pagination 元件或頁碼切換邏輯。需求明確要求「改為分頁形式查詢」，僅有 API 支援 limit/skip 不夠，前端需要有分頁控制項讓使用者操作。 |
| 2 | 🟡 中 | **缺少派案清單頁面主元件**：只看到 `AssignSearchForm` 搜尋表單元件，但未看到整合搜尋 + 清單 + 分頁的主頁面元件（如 `CaseAssignPage` 或 `CaseAssignList`）。可能在其他未修改的既有檔案中，但需要確認整合是否完成。 |
| 3 | 🟡 中 | **limit 預設 50 是否符合規格**：`fetchCaseAssignCaseList` 預設 `limit: 50`，需確認這個每頁筆數是否符合需求規格或 UI 設計。 |

### 驗收結論

**部分通過** — 搜尋表單與後端串接的分頁機制已完成，但**前端分頁 UI 元件**（讓使用者切換頁碼）在本次提交的程式碼中未見到，這是需求的核心功能之一，建議補上後再提交審核。
