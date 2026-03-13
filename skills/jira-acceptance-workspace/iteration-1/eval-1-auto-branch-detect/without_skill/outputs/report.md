# CMD-276 驗收報告

## Jira 資訊

| 欄位 | 內容 |
|------|------|
| **Issue Key** | CMD-276 |
| **標題** | 115年彰化照管-系統優化-派案清單查詢改為分頁查詢-FE |
| **狀態** | 審核中 |
| **負責人** | Alex Cheng |
| **Branch** | `CMD-276/feat/alex_cheng/派案分頁查詢` |

## Jira 需求摘要

1. **派案頁面清單改為分頁形式查詢**
2. **查詢條件分為「未派案」、「已派案（尚未開始服務）」**
3. **搜尋條件 UI**（從需求截圖描述，需有搜尋欄位進行查詢）

## 變更檔案清單

| 檔案 | 說明 |
|------|------|
| `web/pages/CaseAssign/components/AssignSearchForm.jsx` | 派案搜尋表單元件（新增） |
| `web/reducers/caseAssignReducer.js` | Redux reducer，管理派案清單狀態 |
| `web/actioncreators/caseAssignActionCreator.js` | Redux action creator，含 API 呼叫邏輯 |
| `web/enums/CaseAssignEnum.js` | 派案狀態列舉（未派案/已派案） |
| `public/locales/zh_TW/case.json` | 繁體中文 i18n 翻譯檔 |

## 逐項驗收

### 需求 1：派案清單改為分頁查詢

| 檢查項目 | 結果 | 說明 |
|----------|------|------|
| API 支援分頁參數 | ✅ 通過 | `fetchCaseAssignCaseList` 預設帶 `limit: 50, skip: 0` 分頁參數 |
| Reducer 儲存總筆數 | ✅ 通過 | `initState` 含 `caseTotal: 0`，SUCCESS 時寫入 `action.data.total` |
| Loading 狀態管理 | ✅ 通過 | `isFetchingCaseList` 在 REQUEST/SUCCESS/FAILURE 三態正確切換 |
| 搜尋按鈕 disabled 狀態 | ✅ 通過 | `isSearching` prop 控制搜尋按鈕 disabled |
| 分頁 UI 元件 | ⚠️ 未確認 | 未見分頁 UI 元件（Pagination），可能在父層頁面實作，但本次變更檔案中未包含 |

### 需求 2：查詢條件分為「未派案」、「已派案（尚未開始服務）」

| 檢查項目 | 結果 | 說明 |
|----------|------|------|
| 列舉定義 | ✅ 通過 | `CaseAssignEnum` 定義 `UNASSIGNED (value: '1')` 和 `ASSIGNED (value: '2')` |
| 下拉選單 UI | ✅ 通過 | `AssignSearchForm` 有 type 下拉選單，選項為「未派案」和「已派案（尚未開始服務）」 |
| i18n 翻譯 | ✅ 通過 | `case.json` 含 `caseAssignStatus.unassigned: "未派案"` 和 `caseAssignStatus.assigned: "已派案（尚未開始服務）"` |
| 預設查詢條件 | ✅ 通過 | `defaultValues.type` 預設為 `CaseAssignEnum.UNASSIGNED.value`（未派案） |

### 需求 3：搜尋條件 UI

| 檢查項目 | 結果 | 說明 |
|----------|------|------|
| 派案狀態 | ✅ 通過 | 下拉選單 |
| 個案編號 | ✅ 通過 | 文字輸入 (`caseCode`) |
| 姓名 | ✅ 通過 | 文字輸入 (`name`) |
| 身分證字號 | ✅ 通過 | 文字輸入 (`personalId`) |
| 年齡 | ✅ 通過 | 數字輸入 (`age`，含 min=0, step=1) |
| 服務地址（區域） | ✅ 通過 | `AddressSelector` 元件，以縣市 ID 為 parent 選取區域 |
| 照專姓名 | ✅ 通過 | 文字輸入 (`caretakerName`) |
| 搜尋按鈕 | ✅ 通過 | 有搜尋與清除按鈕 |
| 清除按鈕 | ✅ 通過 | `onReset` 重設所有欄位為預設值 |

## 疑慮與建議

### ⚠️ 潛在缺漏

1. **分頁 UI 元件缺失**：Reducer 已有 `caseTotal` 支援分頁計算，Action Creator 也有 `limit`/`skip` 參數，但本次變更中**未看到 Pagination 分頁元件**的實作。需確認是否在父層頁面（如 `CaseAssignPage` 或類似檔案）中已實作分頁 UI，或是尚未完成。

2. **頁碼切換邏輯**：未見切換頁碼時重新呼叫 `fetchCaseAssignCaseList` 並帶入新 `skip` 值的邏輯。

3. **Reducer 裁剪**：`caseAssignReducer.js` 只保留了 `FETCH_CASE_ASSIGN_CASE_LIST` 的 case，其他 action（`SUBMIT_AUTO_ASSIGN`、`SWITCH_AUTO_ASSIGN_MODAL`、`SWITCH_CASE_ASSIGN_CARETAKER_MODAL` 等）雖有 import 但未在 switch 中處理，這些可能在原始碼中存在但本次提交被移除或尚未加入。

## 總結

| 項目 | 狀態 |
|------|------|
| 核心需求覆蓋率 | **約 80%** |
| 查詢條件（未派案/已派案） | ✅ 完成 |
| 搜尋表單 UI | ✅ 完成 |
| API 分頁參數 | ✅ 完成 |
| 分頁 UI 呈現 | ⚠️ 待確認 |

**結論**：查詢條件與搜尋表單的需求已完成。分頁查詢的後端串接（limit/skip 參數、total 回傳）已到位，但**分頁 UI 元件（換頁按鈕）在本次變更中未見**，需要 Alex 確認是否在其他檔案中實作或尚未完成。
