# caseController.js — API Spec

> **FeaturePath:** 個案管理-基本資料-個案資訊-個案管理
> **原始碼:** `backend/controllers/caseController.js`
> **Accountable:** Hilbert Huang, AndyH Lai

## 規模

| 項目 | 數值 |
|------|------|
| 總行數 | 1,884 |
| 檔案數 | 1（單一 controller） |
| Route 數量 | 12 |
| 語言 | JavaScript（ES6 import，util.inherits 繼承） |

## 入口架構

- 繼承 `BaseController`（透過 `util.inherits`）
- 建構式 `CaseControl()` 內以 `this.methodName = function(req, res, next) {...}` 定義所有方法
- 底部 `module.exports = function(router) {...}` 註冊所有 route
- 參數驗證透過 `CaseBean.bind(req, actionName, flag)` 統一處理

## 依賴一覽

| 類別 | 依賴 |
|------|------|
| Bean | `CaseBean`, `PlanBean`, `StatCodeQbe`, `CaseQbe`, `ServiceItemQbe`, `ServiceRecordQbe`, `CaseUpdateReq`, `StatCodeQuotaCodeValueObject` |
| Model | `CaseModel`, `CustomerModel`, `ServiceRecordModel`, `EmployeeModel`, `NameModel`, `PersonalIdModel`, `CloseAccountSettingModel`, `FormModel`, `FormResultModel`, `ServiceItemModel`, `PlanModel`, `CompanyModel` |
| Service | `CaseService`, `ShiftService`, `DayCaseScheduleService`, `GoogleMapService`, `PlanService`, `ServiceItemService`, `CodeGS`, `ServiceRecordService`, `SystemLogService` |
| Type | `CaseType`, `CaseStatusType`, `GenderType`, `FeeCategoryType`, `LivingSituationType`, `DisabilityType`, `LocationType`, `CityType`, `LongTermCareLevelType`, `ServiceItemBA02UnitType`, `PlanType` 等 |

## API 端點

所有端點皆為 **POST** 方法，掛載於 `/case` 路由前綴下。

### 1. POST `/case/create`

| 項目 | 說明 |
|------|------|
| 方法 | `create` |
| 行號 | L165–L1047（含 async.waterfall） |
| Bean 驗證 | `CaseBean.bind(req, 'create', true)` |
| 說明 | 手動新增個案 |
| 必填參數 | `customerId`, `caseType`, `bodyCategory`, `feeCategory`, `livingSituation`, `disability`, `registeredAddress_city`, `registeredAddress_postalCode`, `serviceAddress_postalCode` |
| 業務邏輯 | 取得地址經緯度 → 計算與機構距離 → 建立個案 → 產生個案代碼 → 建立照顧計畫 → 系統日誌 |
| 回傳 | `{ success: true }` 或錯誤訊息 |

### 2. POST `/case/updateBasic`

| 項目 | 說明 |
|------|------|
| 方法 | `updateBasic` |
| 行號 | L1049–L1072 |
| Bean 驗證 | `CaseBean.bind(req, 'updateBasic', true)` |
| 說明 | 更新個案基本資料 |
| 必填參數 | `_id`, `customerId`, `caseType`, `bodyCategory`, `feeCategory`, `livingSituation`, `disability`, `registeredAddress_city`, `status`, `registeredAddress_postalCode`, `serviceAddress_postalCode` |
| 業務邏輯 | 驗證結束日不早於開始日 → 檢查個案是否已結案（結案日不一致則報錯）→ 更新聯絡人 → 刪除 `caseType` 避免被覆蓋 → 呼叫 `this.update` |
| 回傳 | 更新結果 |

### 3. POST `/case/updateContact`

| 項目 | 說明 |
|------|------|
| 方法 | `updateContact` |
| 行號 | L1277–L1284 |
| Bean 驗證 | `CaseBean.bind(req, 'updateContact', true)` |
| 說明 | 更新個案緊急聯絡人 |
| 必填參數 | `_id` |
| 業務邏輯 | 驗證參數 → 呼叫 `this.update` |
| 回傳 | 更新結果 |

### 4. POST `/case/updateContract`

| 項目 | 說明 |
|------|------|
| 方法 | `updateContract` |
| 行號 | L1090–L1264 |
| Bean 驗證 | `CaseBean.bind(req, 'updateContract', true)` |
| 說明 | 更新照顧計畫 |
| 必填參數 | `_id` |
| 其他參數 | `planStartDate`, `approveItems[]`, `bundledRatio`, `overdueFee`, `updateContract`（boolean，是否為更新模式）, `isHaveDrainageTubeScald`, `isDownAndUpStairsNeedHelp`, `adlMove`, `feeCategory`, `longTermCareLevel`, `otherServiceItems`, `priceType`, `workerCare`, `signSupervisor`, `planMemo` |
| 業務邏輯 | 查詢服務項目 → 計算照顧計畫是否超出補助上限 → 判斷是否為更新現有計畫（`updateContract=true`）或建立新計畫 → 新計畫需驗證生效日不早於前一份 → 寫入歷史紀錄 → 更新照顧計畫 |
| 錯誤 | `ERROR_37019`（結案日不一致）、生效日不得早於上一份計畫生效日 |
| 回傳 | 更新結果 |

### 5. POST `/case/profile`

| 項目 | 說明 |
|------|------|
| 方法 | `profile` |
| 行號 | L1287–L1348 |
| Bean 驗證 | `CaseBean.bind(req, 'profile', false)` |
| 說明 | 查詢單一個案完整資料 |
| 必填參數 | `_id`（caseId） |
| 業務邏輯 | 自動注入 `askPlanIntroduction=1`, `askGroup=1` → 透過 `CaseService.query` 查詢 → 額外查詢是否有進行中的 G 碼統計（`StatCodeG`） → 附加 `hasOngoingStatCodeG`, `statCodeGStartDate`, `statCodeGEndDate` |
| 回傳 | 個案完整資料物件，含 G 碼統計狀態 |

### 6. POST `/case/delete`

| 項目 | 說明 |
|------|------|
| 方法 | `delete` |
| 行號 | L1351–L1398 |
| Bean 驗證 | `CaseBean.bind(req, null, false)` |
| 說明 | 刪除個案（軟刪除） |
| 必填參數 | `deleteList`（個案 ID） |
| 業務邏輯 | 查詢個案是否存在 → 檢查是否仍有服務紀錄（有則拒絕刪除）→ 軟刪除（設 `valid=false`、記錄刪除者與時間、importId 加時間戳避免重複）→ 系統日誌 |
| 錯誤 | 該個案仍有服務記錄時回傳錯誤提示 |
| 回傳 | `{}` |

### 7. POST `/case/transformService`

| 項目 | 說明 |
|------|------|
| 方法 | `transformService` |
| 行號 | L1477–L1622 |
| Bean 驗證 | `CaseBean.bind(req, 'transformService', true)` |
| 說明 | 將個案的服務項目更新為新支付項目（107 年 11 月新制） |
| 必填參數 | `caseId` |
| 其他參數 | `planStartDate` |
| 業務邏輯 | 查詢個案現有服務項目 → 查詢新支付制度對應項目 → 轉換（含 BA02 特殊處理）→ 原有計畫寫入歷史 → 更新個案的 `approveItems`、`planStartDate`、`service10711Flag=true` |
| 錯誤 | 生效日不得早於上一份計畫生效日 |
| 回傳 | `{ success: true }` |

### 8. POST `/case/updateServiceTime`

| 項目 | 說明 |
|------|------|
| 方法 | `updateServiceTime` |
| 行號 | L1635–L1688 |
| Bean 驗證 | `CaseBean.bind(req, 'updateServiceTime', true)` |
| 說明 | 更新服務項目的個人化建議時間 |
| 必填參數 | `_id`（caseId） |
| 其他參數 | `serviceTimeRequired`（Object，key=服務項目代碼、value=時間分鐘數）, `serviceTimeRequiredSettingAndMemo`（Object，key=服務項目代碼、value=`{fixedTime, memo}`） |
| 業務邏輯 | 更新 DB → 比對新舊值產生異動紀錄（新增/刪除/修改項目時間） |
| 回傳 | `{}` |

### 9. POST `/case/autoJudgeAA11`

| 項目 | 說明 |
|------|------|
| 方法 | `autoJudgeAA11` |
| 行號 | L1697–L1712 |
| Bean 驗證 | `CaseBean.bind(req, 'autoJudgeAA11', true)` |
| 說明 | 自動判定 AA11 認證資格 |
| 必填參數 | `_id`（caseId）, `companyId` |
| 業務邏輯 | 取得個案資訊 → 透過 `CaseService.checkAA11ByCondition` 檢查條件 |
| 回傳 | AA11 判定結果物件 |

### 10. POST `/case/multiUpdateCase`

| 項目 | 說明 |
|------|------|
| 方法 | `multiUpdateCase` |
| 行號 | L1723–L1767 |
| Bean 驗證 | `CaseBean.bind(req, 'multiUpdateCase', false)` |
| 說明 | 批次編輯個案資訊（主責居服員、督導等） |
| 必填參數 | `caseId`（Array 或 String）, `companyId` |
| 選填參數 | `masterHomeservicerId`（主責居服員）, `supervisorId`（主責督導）, `subSupervisorId`（副督導） |
| 業務邏輯 | 組裝更新物件（僅包含有傳入的欄位）→ 若無需更新直接回傳 → `CaseModel.updateMany` 批次更新 |
| 錯誤 | `ERROR_37015` |
| 回傳 | `{}` |

### 11. POST `/case/exportExcel`

| 項目 | 說明 |
|------|------|
| 方法 | `exportExcel` |
| 行號 | L1777–L1825 |
| Bean 驗證 | 無特定 bean 驗證（直接從 `req.body` 取值） |
| 說明 | 匯出個案資料範本（Excel） |
| 必填參數 | `caseType`（僅支援居服/日照） |
| 業務邏輯 | 驗證個案類別 → 查詢個案資料 → 提取 `customCode`, `MOHWCode`, `name`, `personalId`, `code` → 寫入 Excel 範本 |
| 錯誤 | `ERROR_37022`（不支援的個案類別） |
| 回傳 | Excel 輸出結果 |

### 12. POST `/case/importExcel`

| 項目 | 說明 |
|------|------|
| 方法 | `importExcel` |
| 行號 | L1835–L1865 |
| Bean 驗證 | 無特定 bean 驗證（從 `req.files.file` 取檔案） |
| 說明 | 根據匯入報表更新個案衛福部案號 |
| 必填參數 | `req.files.file`（上傳的 Excel 檔案） |
| 業務邏輯 | 讀取匯入報表 → 逐一更新個案的 `MOHWCode` → 找不到的個案收集到陣列回傳 |
| 回傳 | 未找到的個案清單（Array） |

## 品質觀察

1. **混合非同步模式：** 同時使用 `async.waterfall`（callback 風格）和 `async/await`，風格不一致
2. **`console.log` 殘留：** L1182 有 `console.log` 未移除
3. **`console.error` 殘留：** L1437 有 `console.error`
4. **過長的 create 方法：** `create` 方法橫跨約 880 行（L165–L1047），遠超建議的 50 行上限
5. **util.inherits：** 使用 `util.inherits` 而非 ES6 `class extends`，屬於舊式寫法
6. **Bean 驗證不一致：** `exportExcel` 和 `importExcel` 未透過 `CaseBean` 驗證，直接取 `req.body` / `req.files`
7. **軟刪除的 importId 處理：** `delete` 方法中以 `importId_timestamp` 避免唯一索引衝突，屬於 workaround

## 完整性驗證

| 項目 | 數值 |
|------|------|
| 驗證日期 | 2026-03-11 |
| 原始碼 route 總數 | 12 |
| Spec 列出數量 | 12 |
| 完整度 | **100%** |

### Route 對照表

| # | Route 路徑 | HTTP Method | Controller Method | Spec 是否涵蓋 |
|---|-----------|-------------|-------------------|--------------|
| 1 | `/create` | POST | `create` | V |
| 2 | `/updateBasic` | POST | `updateBasic` | V |
| 3 | `/updateContact` | POST | `updateContact` | V |
| 4 | `/updateContract` | POST | `updateContract` | V |
| 5 | `/profile` | POST | `profile` | V |
| 6 | `/delete` | POST | `delete` | V |
| 7 | `/transformService` | POST | `transformService` | V |
| 8 | `/updateServiceTime` | POST | `updateServiceTime` | V |
| 9 | `/autoJudgeAA11` | POST | `autoJudgeAA11` | V |
| 10 | `/multiUpdateCase` | POST | `multiUpdateCase` | V |
| 11 | `/exportExcel` | POST | `exportExcel` | V |
| 12 | `/importExcel` | POST | `importExcel` | V |
