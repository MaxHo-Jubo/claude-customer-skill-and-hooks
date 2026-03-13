# API Spec: caseController.js

> **FeaturePath**: 個案管理-基本資料-個案資訊-個案管理
> **檔案路徑**: `backend/controllers/caseController.js`
> **負責人**: Hilbert Huang, AndyH Lai
> **Base Path**: `/case`
> **所有端點皆為 POST 方法**

---

## 端點總覽

| # | 端點 | 說明 |
|---|------|------|
| 1 | `POST /case/create` | 手動新增個案 |
| 2 | `POST /case/updateBasic` | 更新個案基本資料 |
| 3 | `POST /case/updateContact` | 更新個案緊急連絡人 |
| 4 | `POST /case/updateContract` | 更新照顧計畫 |
| 5 | `POST /case/profile` | 查詢個案詳細資料 |
| 6 | `POST /case/delete` | 刪除個案（軟刪除） |
| 7 | `POST /case/transformService` | 將個案服務項目更新為新支付項目 |
| 8 | `POST /case/updateServiceTime` | 更新服務項目的建議時間 |
| 9 | `POST /case/autoJudgeAA11` | 自動判定 AA11 認證 |
| 10 | `POST /case/multiUpdateCase` | 批次編輯個案資訊 |
| 11 | `POST /case/exportExcel` | 匯出個案資料範本 |
| 12 | `POST /case/importExcel` | 根據匯入報表更新個案資料 |

---

## 1. POST /case/create

**說明**：手動新增個案。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| data | Object | 是 | 個案基本資料，結構見 CaseModel |

- 個案類別 (`caseType`) 決定案號前綴：居服 `CA`、日照 `DC`、喘息 `RB`、專A `EA`，未指定預設為居服。
- 若登入角色為據點 (`LocationType.LOCATION`)，會自動帶入 `businessLocationId`。
- 建立時會透過地址取得經緯度，並計算與機構的距離。

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 新增結果 |

**錯誤情境**:
- 資料庫語法錯誤或執行回傳錯誤
- 輸入參數缺漏或格式錯誤
- 案主找不到

---

## 2. POST /case/updateBasic

**說明**：更新個案基本資料。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| startDate | Date | 否 | 服務開始日期 |
| endDate | Date | 否 | 服務結束日期 |
| contact | Object | 否 | 緊急連絡人資訊 |
| (其他欄位) | - | - | 依 CaseBean `updateBasic` binding 定義 |

**驗證邏輯**:
- `endDate` 不得早於 `startDate`
- 個案狀態為已結案時，`closedDate` 必須與 `endDate` 一致，否則回傳 `ERROR_37019`
- 更新時會移除 `caseType` 欄位（不允許變更個案類別）

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 更新結果 |

---

## 3. POST /case/updateContact

**說明**：更新個案緊急連絡人資訊。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| (其他欄位) | - | - | 依 CaseBean `updateContact` binding 定義 |

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 更新結果 |

---

## 4. POST /case/updateContract

**說明**：更新照顧計畫。更新時會將原有照顧計畫存入歷史紀錄（PlanModel），並更新個案的核定項目及計畫生效日。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| (照顧計畫資訊) | Object | 是 | 目前照顧計畫資訊，依 CaseBean `updateContract` binding 定義 |

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 執行結果 |

**錯誤情境**:
- 資料庫語法錯誤或執行回傳錯誤
- 輸入參數缺漏或格式錯誤
- 照顧計畫的生效日（排班起始日）不得早於或等於上一份照顧計畫的生效日
- 找不到此個案資料

---

## 5. POST /case/profile

**說明**：查詢個案詳細資料，包含是否有進行中的 StatCode G 認證及其起迄日期。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |

- 會自動帶入 `askPlanIntroduction = 1` 和 `askGroup = 1`

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 查詢結果 |
| data | Object | 個案詳細資料 |
| data.hasOngoingStatCodeG | Boolean | 是否有進行中的 StatCode G |
| data.statCodeGStartDate | String | StatCode G 開始月份 (YYYY-MM) |
| data.statCodeGEndDate | String | StatCode G 結束月份 (YYYY-MM) |

---

## 6. POST /case/delete

**說明**：刪除個案（軟刪除，將 `valid` 設為 `false`）。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| deleteList | String | 是 | 要刪除的個案 ID |

**驗證邏輯**:
- 個案必須屬於當前登入使用者的機構
- 若該個案仍有有效服務紀錄，則無法刪除（回傳提示訊息，需先調整班表）

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 刪除結果 |

---

## 7. POST /case/transformService

**說明**：將個案的服務項目更新為新支付項目（serviceVersion 2）。流程為：查詢舊項目 → 對應新支付項目 → 舊照顧計畫存入歷史 → 更新個案。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| caseId | String | 是 | 個案 ID |
| planStartDate | Date | 是 | 新照顧計畫生效日 |

**驗證邏輯**:
- 新計畫生效日不得早於或等於上一份照顧計畫的生效日
- BA02 項目會依機構設定的 `serviceItemBA02Unit` 決定對應版本

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 執行結果 |

---

## 8. POST /case/updateServiceTime

**說明**：更新服務項目的個人化建議時間，並記錄異動 log。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| serviceTimeRequired | Object | 是 | 個人化服務時間（key: 服務項目代碼, value: 時間分鐘數） |
| serviceTimeRequiredSettingAndMemo | Object | 否 | 個人化服務時間設定和備註（key: 服務項目代碼, value: `{ fixedTime: Boolean, memo: String }`） |

**異動紀錄**：系統會自動比對新舊資料，記錄新增/刪除/修改的項目時間。

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 執行結果 |

---

## 9. POST /case/autoJudgeAA11

**說明**：自動判定 AA11 認證。根據個案及案主資訊，檢查是否符合 AA11 認證條件。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| companyId | String | 是 | 公司 ID |

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 執行結果 |
| data | Object | AA11 判定結果 |

---

## 10. POST /case/multiUpdateCase

**說明**：批次編輯多個個案的主責居服員、主責督導、副督導。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| caseId | Array\|String | 是 | 個案 ID（單筆或多筆） |
| companyId | String | 是 | 公司 ID |
| masterHomeservicerId | String | 否 | 主責居服員 ID |
| supervisorId | String | 否 | 主責督導 ID |
| subSupervisorId | String | 否 | 副督導 ID |

- 至少需提供一個更新欄位（masterHomeservicerId / supervisorId / subSupervisorId），否則直接回傳成功。

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 執行結果 |

**錯誤情境**:
- `ERROR_37015`：批次更新失敗

---

## 11. POST /case/exportExcel

**說明**：匯出個案資料範本為 Excel 檔案。

**請求參數** (`req.body`):

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| caseType | String | 是 | 個案類別（僅支援居服、日照） |

**驗證邏輯**:
- 個案類別僅支援居服和日照，其他類別回傳 `ERROR_37022`

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 執行結果 |
| data | Object | 匯出檔案資訊 |

---

## 12. POST /case/importExcel

**說明**：根據匯入的 Excel 報表批次更新個案的衛福部案號（MOHWCode）。

**請求參數**:

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| req.files.file | File | 是 | 匯入的 Excel 檔案（透過 express-fileupload） |

**處理邏輯**:
- 讀取 Excel 中的個案資料
- 依 `code`（系統 ID）和 `companyId` 查找個案並更新 `MOHWCode`
- 找不到的個案會收集到回傳結果中

**回應**:

| 欄位 | 型別 | 說明 |
|------|------|------|
| success | Boolean | 執行結果 |
| data | Array | 找不到對應個案的資料列表 |

---

## 共用說明

### 認證與授權
- 所有端點皆需通過 session 驗證（`req.session.user`）
- 操作範圍限定於登入使用者所屬的機構（`companyId`）

### 回應格式
所有端點統一使用 BaseController 提供的回應格式：
- **成功**: `{ success: true, data: ... }`
- **失敗**: `{ success: false, errors: ... }`

### 異動紀錄
更新類操作（updateBasic、updateContract、updateServiceTime、delete）會透過 `SystemLogService` 記錄異動歷程。
