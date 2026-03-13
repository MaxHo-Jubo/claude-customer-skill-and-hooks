# API Spec: caseController.js

> **FeaturePath:** 個案管理-基本資料-個案資訊-個案管理
> **檔案路徑:** `backend/controllers/caseController.js`
> **Accountable:** Hilbert Huang, AndyH Lai
> **Base Path:** `/case`
> **所有路由方法:** POST

---

## 目錄

1. [POST /case/create — 手動新增個案](#1-post-casecreate--手動新增個案)
2. [POST /case/updateBasic — 更新個案基本資料](#2-post-caseupdatebasic--更新個案基本資料)
3. [POST /case/updateContact — 更新個案緊急連絡人](#3-post-caseupdatecontact--更新個案緊急連絡人)
4. [POST /case/updateContract — 更新照顧計畫](#4-post-caseupdatecontract--更新照顧計畫)
5. [POST /case/profile — 查詢個案詳細資料](#5-post-caseprofile--查詢個案詳細資料)
6. [POST /case/delete — 刪除個案](#6-post-casedelete--刪除個案)
7. [POST /case/transformService — 將個案服務項目轉換為新支付項目](#7-post-casetransformservice--將個案服務項目轉換為新支付項目)
8. [POST /case/updateServiceTime — 更新服務項目建議時間](#8-post-caseupdateservicetime--更新服務項目建議時間)
9. [POST /case/autoJudgeAA11 — 自動判定AA11認證](#9-post-caseautojudgeaa11--自動判定aa11認證)
10. [POST /case/multiUpdateCase — 批次編輯個案資訊](#10-post-casemultiupdatecase--批次編輯個案資訊)
11. [POST /case/exportExcel — 匯出個案資料範本](#11-post-caseexportexcel--匯出個案資料範本)
12. [POST /case/importExcel — 匯入報表更新個案資料](#12-post-caseimportexcel--匯入報表更新個案資料)

---

## 1. POST /case/create — 手動新增個案

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| data | Object | 是 | 個案基本資料，見 CaseModel schema |
| caseType | String | 否 | 個案類別（預設 HOMECARE）。可選：HOMECARE / DAYCARE / RESTBED / EXPERTA |
| systemLogId | String | 否 | 系統日誌 ID |

### 業務邏輯

1. 綁定 CaseBean 並驗證輸入參數
2. 依 `caseType` 決定案號前綴：CA（居服）、DC（日照）、RB（喘息床）、EA（專A）
3. 若使用者角色為據點，自動帶入 `businessLocationId`
4. 透過 Google Geocoder API 將服務地址轉為經緯度
5. 計算個案與機構之間的距離（公里數）
6. 設定開案日為今日、服務結束日為隔年 12/31
7. 取得該機構最新案號（自動遞增）
8. 客製化：宜蘭舒活居服（companyCode: `suhoyl`）新增個案時，預設繳費方式為「個案自繳」
9. 儲存個案資料至 DB
10. 若機構支援 QR Code 打卡，自動呼叫 `/case/qrcode/create` 建立 QR Code
11. 寫入系統日誌

### 回應

- **成功:** `{ success: true, data: <新增的個案物件> }`
- **失敗:**
  - 資料庫語法錯誤或執行回傳錯誤
  - 輸入參數缺漏或格式錯誤
  - 案主找不到

---

## 2. POST /case/updateBasic — 更新個案基本資料

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| startDate | Date | 否 | 服務開始日期 |
| endDate | Date | 否 | 服務結束日期 |
| contact | Object | 否 | 聯絡人資料 |
| *(其他 CaseBean updateBasic 欄位)* | - | - | 依 CaseBean.bind('updateBasic') 定義 |

### 業務邏輯

1. 綁定 CaseBean（模式: `updateBasic`）並驗證
2. 若 `endDate < startDate`，回傳錯誤「服務結束日期不得早於服務開始日期」
3. 若個案已結案且 endDate 與結案日不同，回傳錯誤（ERROR_37019）
4. 若有聯絡人資料且聯絡人缺少 companyId，自動補上
5. 刪除 `caseType` 防止異動到個案類別
6. 呼叫內部 `update()` 方法執行更新（含完整更新流程）

### 內部 update() 流程

1. 檢查客製案號是否重複
2. 若狀態為「結案/轉介/暫停」，檢查結案日後排班是否已關帳鎖定
3. 清除結案日、暫停後的排班、打卡、服務紀錄
   - 日照：刪除排班或設為請假
   - 居服：刪除排班；暫停時若暫停日後有服務紀錄則擋住（ERROR_37009）
4. 讀取舊個案資料
5. 若服務地址有變更，重新取得經緯度並計算與機構距離
6. 讀取新案主/聯絡人/督導員/副督導員/社工/據點資料
7. 更新個案資料至 DB（不異動 caseType）
8. 處理月計畫（刪除/產生當月最優照顧計畫）
9. 更新喘息額度設定（StatCodeG）：含補助額度、服務項目、補助次數
10. 處理個案狀態變更：
    - 暫停：將暫停期間排班設為案主請假
    - 恢復服務：日照恢復排班 / 居服取消請假
11. 寫入系統日誌（差異比對）

### 回應

- **成功:** `{ success: true, data: <更新後個案物件> }`
- **失敗:** 資料庫錯誤 / 參數錯誤 / 案號重複 / 關帳鎖定

---

## 3. POST /case/updateContact — 更新個案緊急連絡人

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| contacts | Array | 是 | 聯絡人清單 |

### 業務邏輯

1. 綁定 CaseBean（模式: `updateContact`）並驗證
2. 呼叫內部 `update()` 方法執行更新

### 回應

- **成功:** `{ success: true, data: <更新後個案物件> }`
- **失敗:** 參數錯誤 / 資料庫錯誤

---

## 4. POST /case/updateContract — 更新照顧計畫

**FeaturePath:** 個案管理-基本資料-個案資訊-更新照顧計畫

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| planStartDate | Date | 是 | 照顧計畫生效日（排班起始日） |
| approveItems | Array | 是 | 核定服務項目清單（含 serviceCode, amount, itemType） |
| bundledRatio | Object | 否 | B/C 碼額度 |
| overdueFee | String | 否 | 超額自費（預設 '0'） |
| updateContract | Boolean | 否 | true=更新現有計畫；false/未帶=新增歷史紀錄後更新 |
| isHaveDrainageTubeScald | Boolean | 否 | 是否有燒燙傷管線 |
| isDownAndUpStairsNeedHelp | Boolean | 否 | 上下樓梯是否需要幫忙 |
| adlMove | String | 否 | 移動困難程度 |
| statCodeGStartDate | Date | 否 | 喘息額度起始年月 |
| statCodeGEndDate | Date | 否 | 喘息額度結束年月 |

### 業務邏輯

1. 綁定 CaseBean（模式: `updateContract`）並驗證
2. 查詢服務項目詳細資料（依 planStartDate 判斷 serviceVersion 1 或 2）
3. 計算照顧計畫費用（B/C 碼、G 碼、S 碼），過濾不存在的服務項目
4. 若非更新模式（`updateContract !== true`）：
   - 驗證新生效日不得早於或等於上一份照顧計畫的生效日
   - 將舊照顧計畫寫入歷史紀錄（PlanModel）
5. 若為更新模式：
   - 檢查先前歷史紀錄的生效日
   - 更新先前紀錄的 planEndDate
6. 呼叫內部 `update()` 方法更新個案資料

### 回應

- **成功:** `{ success: true, data: <更新後個案物件> }`
- **失敗:**
  - 資料庫語法錯誤或執行回傳錯誤
  - 輸入參數缺漏或格式錯誤
  - 照顧計畫的生效日不得早於或等於上一份照顧計畫的生效日
  - 找不到此個案資料

---

## 5. POST /case/profile — 查詢個案詳細資料

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| caseId | String | 是 | 個案 ID |
| *(其他 CaseBean profile 欄位)* | - | - | 依 CaseBean.bind('profile') 定義 |

### 業務邏輯

1. 自動設定 `askPlanIntroduction = 1`, `askGroup = 1`
2. 綁定 CaseBean（模式: `profile`）並驗證
3. 透過 CaseService.query 查詢個案資料（含關聯資料）
4. 查詢該個案當前是否有進行中的喘息額度設定（StatCodeG）
5. 若有：附加 `hasOngoingStatCodeG = true` 及起迄年月
6. 若無：附加 `hasOngoingStatCodeG = false`

### 回應

- **成功:** `{ success: true, data: <個案詳細資料物件，含 hasOngoingStatCodeG / statCodeGStartDate / statCodeGEndDate> }`
- **失敗:** 資料庫錯誤

---

## 6. POST /case/delete — 刪除個案

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| deleteList | String | 是 | 要刪除的個案 ID |

### 業務邏輯

1. 依 caseId + companyId 查詢個案
2. 檢查該個案是否仍有服務紀錄（ServiceRecord）
   - 若有：回傳錯誤「該個案在 YYYY年M月 仍有服務記錄，請調整班表後再執行刪除」
3. 軟刪除（設 `valid = false`）並記錄刪除者、刪除時間
4. 修改 importId 加上時間戳以避免唯一索引衝突
5. 寫入系統日誌

### 回應

- **成功:** `{ success: true, data: {} }`
- **失敗:** 資料庫錯誤 / 仍有服務紀錄

---

## 7. POST /case/transformService — 將個案服務項目轉換為新支付項目

**FeaturePath:** 個案管理-基本資料-個案資訊-將個案的服務項目更新為新支付項目

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| caseId | String | 是 | 個案 ID |
| planStartDate | Date | 是 | 新照顧計畫生效日 |

### 業務邏輯

1. 綁定 CaseBean（模式: `transformService`）並驗證
2. 查詢個案現有服務項目（舊有項目，serviceVersion 1）
3. 查詢對應的新支付項目（serviceVersion 2）
4. 將舊項目對應到新項目（含 BA02 特殊處理：依機構設定選擇 BA02__10711 / BA02__10711(2) / BA02__10711(3)）
5. 驗證新生效日不得早於或等於上一份照顧計畫的生效日
6. 將舊照顧計畫寫入歷史紀錄（PlanModel）
7. 更新個案的 `approveItems`、`planStartDate`，設定 `service10711Flag = true`，延長 `endDate` 至隔年年底

### 回應

- **成功:** `{ success: true }`
- **失敗:** 參數錯誤 / 資料庫錯誤 / 生效日驗證失敗 / 查無個案（ERROR_37014）

---

## 8. POST /case/updateServiceTime — 更新服務項目建議時間

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| serviceTimeRequired | Object | 是 | 個人化服務時間（key: serviceCode, value: 分鐘數） |
| serviceTimeRequiredSettingAndMemo | Object | 否 | 個人化服務時間設定與備註（key: serviceCode, value: `{ fixedTime: Boolean, memo: String }`） |

### 業務邏輯

1. 綁定 CaseBean（模式: `updateServiceTime`）並驗證
2. 依 caseId + companyId 查詢並更新 `serviceTimeRequired` 及 `serviceTimeRequiredSettingAndMemo`
3. 比對舊值與新值，產生異動紀錄：
   - 刪除的項目時間
   - 新增的項目時間
   - 修改的項目時間（含分鐘數、備註、綁定服務時間變更）
4. 寫入差異日誌（logForDifferences）

### 回應

- **成功:** `{ success: true, data: {} }`
- **失敗:** 參數錯誤 / 資料庫錯誤

---

## 9. POST /case/autoJudgeAA11 — 自動判定AA11認證

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| _id | String | 是 | 個案 ID |
| companyId | String | 是 | 機構 ID |

### 業務邏輯

1. 綁定 CaseBean（模式: `autoJudgeAA11`）並驗證
2. 透過 CaseService.getCaseInfomation 取得個案完整資料
3. 透過 CaseService.checkAA11ByCondition 依個案及案主條件自動判定 AA11 認證結果

### 回應

- **成功:** `{ success: true, data: <AA11 判定結果> }`
- **失敗:** 參數錯誤 / 資料庫錯誤

---

## 10. POST /case/multiUpdateCase — 批次編輯個案資訊

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| caseId | String / Array | 是 | 個案 ID（單一或多個） |
| companyId | String | 是 | 機構 ID |
| masterHomeservicerId | String | 否 | 主責居服員 ID |
| supervisorId | String | 否 | 主責督導 ID |
| subSupervisorId | String | 否 | 副督導 ID |

### 業務邏輯

1. 綁定 CaseBean（模式: `multiUpdateCase`）並驗證
2. 從 `masterHomeservicerId`、`supervisorId`、`subSupervisorId` 中取有傳入的欄位組成更新物件
3. 若無任何欄位需更新，直接回傳成功
4. 使用 `CaseModel.updateMany` 批次更新符合條件的個案

### 回應

- **成功:** `{ success: true, data: {} }`
- **失敗:** ERROR_37015（批次更新失敗）

---

## 11. POST /case/exportExcel — 匯出個案資料範本

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數 (req.body)

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| caseType | String | 是 | 個案類別（僅支援 HOMECARE / DAYCARE） |
| *(CaseService.query 所需參數)* | - | - | 用於篩選匯出的個案 |

### 業務邏輯

1. 檢查 caseType，僅支援居服與日照（其他回傳 ERROR_37022）
2. 透過 CaseService.query 取得個案資料
3. 萃取所需欄位：customCode（案號）、MOHWCode（衛福部案號）、name（姓名）、personalId（身分證字號）、code（系統 ID）
4. 讀取空白範本檔（`input_xlsxfile`），將個案資料寫入
5. 輸出至 `output_xlsxfile/{companyId}/` 目錄，檔名格式為 `{居服|日照}個案資料範本.xlsx`

### 回應

- **成功:** `{ success: true, data: <匯出檔案資訊> }`
- **失敗:** 參數錯誤 / 不支援的個案類別 / 匯出失敗

---

## 12. POST /case/importExcel — 匯入報表更新個案資料

**FeaturePath:** 個案管理-基本資料-個案資訊-個案管理

### 參數

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| req.files.file | File (multipart) | 是 | 匯入的 Excel 報表檔案 |

### 業務邏輯

1. 透過 CaseService.readImportExcel 讀取匯入報表
2. 逐筆依 `code`（系統 ID）+ `companyId` 查詢並更新個案的 `MOHWCode`（衛福部案號）
3. 若找不到對應個案，記錄到 `caseNotFound` 陣列

### 回應

- **成功:** `{ success: true, data: <未找到的個案清單（陣列）> }`
- **失敗:** 讀取檔案失敗 / 資料庫錯誤

---

## 共用內部方法（非 API 端點）

### getGeocoder(req, caseBean, callback)

從服務地址查詢 GPS 座標。呼叫內部 `/geocoder/line` API，將地址轉為經緯度。若 `byCoordinate = true` 則跳過。

### update(req, res, caseBean)

個案更新的核心方法，被 `updateBasic`、`updateContact`、`updateContract` 共用。詳見 updateBasic 的「內部 update() 流程」。

### updateContactWithCompanyId(contact, req)

若聯絡人缺少 companyId，自動補上當前使用者的 companyId。

### uploadFile(res, caseBean, actionType)

上傳檔案：產生 UUID 檔名 → 搬移至對應資料夾 → 更新 DB → 刪除舊檔。

### removeFile(res, caseBean, actionType)

移除檔案：從檔案系統刪除 → 更新 DB 將欄位設為 null。

---

## 路由註冊

```js
// backend/controllers/caseController.js (line 1870-1884)
module.exports = function (router) {
  const caseControl = new CaseControl();
  router.route('/create').post(caseControl.create.bind(caseControl));
  router.route('/updateBasic').post(caseControl.updateBasic.bind(caseControl));
  router.route('/updateContact').post(caseControl.updateContact.bind(caseControl));
  router.route('/updateContract').post(caseControl.updateContract.bind(caseControl));
  router.route('/profile').post(caseControl.profile.bind(caseControl));
  router.route('/delete').post(caseControl.delete.bind(caseControl));
  router.route('/transformService').post(caseControl.transformService.bind(caseControl));
  router.route('/updateServiceTime').post(caseControl.updateServiceTime.bind(caseControl));
  router.route('/autoJudgeAA11').post(caseControl.autoJudgeAA11.bind(caseControl));
  router.route('/multiUpdateCase').post(caseControl.multiUpdateCase.bind(caseControl));
  router.route('/exportExcel').post(caseControl.exportExcel.bind(caseControl));
  router.route('/importExcel').post(caseControl.importExcel.bind(caseControl));
};
```

**路由掛載方式：** `routes/index.js` 自動掃描 `controllers/` 目錄，將 `caseController.js` 的檔名去掉 `Controller` 後綴得到 `case`，掛載為 `app.use('/case', router)`。

---

## 依賴

### Models
CaseModel, CustomerModel, ServiceRecordModel, EmployeeModel, NameModel, PersonalIdModel, CloseAccountSettingModel, FormModel, FormResultModel, ServiceItemModel, PlanModel, CompanyModel

### Services
SystemLogService, CaseService, ShiftService, DayCaseScheduleService, GoogleMapService, PlanService, ServiceItemService, CodeGS, ServiceRecordService

### Type Enums
CaseType, CaseStatusType, GenderType, HandicapType, FeeCategoryType, LivingSituationType, LivingPartnerType, DisabilityType, DisabilityProveType, LocationType, CityType, BodySituationType, LongTermCareLevelType, ShiftActionMultiType, ServiceItemBA02UnitType, PlanType, ServiceCodeTypeEnum, PaymentMethodType, AboriginalRace, AboriginalType, MotherTongueType, BodySituationSystemType
