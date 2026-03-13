# 個案管理 Controller Spec

> FeaturePath: 個案管理-基本資料-個案資訊
> 原始碼根目錄: `backend/controllers/`

## 規模

| 檔案 | 行數 | 路由前綴 | 用途 |
|------|------|----------|------|
| `caseController.js` | 1884 | `/case` | 個案 CRUD、照顧計畫、匯出匯入 |
| `caseQuery.js` | 596 | `/case` | 個案列表查詢、分類、來源管理 |
| `caseQRcode.js` | 167 | `/case` | 個案二維條碼 |
| `caseStatus.js` | 1194 | `/case` | 個案狀態（結案/暫停/恢復）管理 |
| `caseContract.js` | 173 | `/case` | 合約 PDF 產製 |
| `caseReport.js` | 499 | `/case` | 個案報表（核銷清冊） |
| `caseHtml.js` | 2116 | `/case` | HTML 匯入個案/照顧計畫 |
| `caseChartsController.js` | 46 | `/caseCharts` | 個案資源圖列表 |
| `caseformController.js` | 830 | `/caseform` | 評鑑表單（開案/訪視/環評/照顧等） |
| **合計** | **7505** | | |

## 入口架構

所有 controller 檔案透過 `routes/index.js` 動態載入並掛載路由。路由前綴的對應邏輯：

1. 預設規則：檔名去掉 `Controller` 後綴作為路由前綴（如 `caseController.js` → `/case`）
2. `CONTROLLER_ROUTING_MAPPING` 覆蓋：`caseQuery`/`caseQRcode`/`caseStatus`/`caseContract`/`caseReport`/`caseHtml` 皆映射到 `/case`
3. `caseChartsController.js` → `/caseCharts`（預設規則）
4. `caseformController.js` → `/caseform`（預設規則）

所有 controller 繼承 `BaseController`（或 `BaseControllerClass`），統一使用 `this.success()` / `this.fail()` 回傳結果。參數驗證透過 `CaseBean.bind(req, action, required)` 執行。

## API 端點

### `/case` 路由群組

#### caseController.js（個案核心 CRUD）

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 1 | `/case/create` | POST | `create` | 手動新增個案。依 `caseType` 區分居服(CA)/日照(DC)/喘息(RB)/專A(EA)。自動取得地址經緯度、計算與機構距離、檢查客製案號重複 |
| 2 | `/case/updateBasic` | POST | `updateBasic` | 更新個案基本資料。驗證服務結束日不早於開始日、已結案個案不允許修改結束日 |
| 3 | `/case/updateContact` | POST | `updateContact` | 更新個案緊急聯絡人 |
| 4 | `/case/updateContract` | POST | `updateContract` | 更新照顧計畫。驗證生效日不早於上一份、查詢服務項目費用、處理 G 碼/B 碼額度 |
| 5 | `/case/profile` | POST | `profile` | 取得個案詳細資料。包含照顧計畫、G 碼狀態碼、服務項目等完整資訊 |
| 6 | `/case/delete` | POST | `delete` | 刪除個案（邏輯刪除） |
| 7 | `/case/transformService` | POST | `transformService` | 將個案的服務項目更新為新支付項目 |
| 8 | `/case/updateServiceTime` | POST | `updateServiceTime` | 更新服務項目的建議時間。參數：`_id`、`serviceTimeRequired`（個人化服務時間）、`serviceTimeRequiredSettingAndMemo`（設定和備註）、`caseId` |
| 9 | `/case/autoJudgeAA11` | POST | `autoJudgeAA11` | 自動判定 AA11 認證。參數：`_id`（caseId） |
| 10 | `/case/multiUpdateCase` | POST | `multiUpdateCase` | 批次編輯個案資訊。參數：`caseId`（Array/String）、`companyId`、`masterHomeservicerId`、`supervisorId`、`subSupervisorId` |
| 11 | `/case/exportExcel` | POST | `exportExcel` | 匯出個案資料範本（xlsx）。參數：`caseType`（居服/日照） |
| 12 | `/case/importExcel` | POST | `importExcel` | 根據匯入報表更新個案衛福部案號。參數：`req.files.file`（xlsx 檔案） |

#### caseQuery.js（個案列表查詢）

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 13 | `/case/query` | POST | `list` | 查詢個案列表 |
| 14 | `/case/queryForMobile` | POST | `listForMobile` | 查詢個案列表（APP 版本）。額外回傳生理量測、聯絡簿、日照服務紀錄 |
| 15 | `/case/names` | POST | `names` | 取得個案姓名列表 |
| 16 | `/case/getCategoryList` | POST | `getCategoryList` | 取得個案分類列表。參數：`caseType` |
| 17 | `/case/updateCategory` | POST | `updateCategory` | 批次更新個案分類。參數：`category`（Array）。新增不存在的、刪除不在列表中的 |
| 18 | `/case/createCategory` | POST | `createCategory` | 新增單一個案分類。參數：`category`（String）。重複時回傳 ERROR_37030 |
| 19 | `/case/source/create` | POST | `createCaseSource` | 新增單一個案來源。參數：`source`（String）。重複時回傳 ERROR_37031 |
| 20 | `/case/source/update` | POST | `updateCaseSource` | 批次更新個案來源清單。參數：`sources`（Array）。自動新增/移除差異項 |
| 21 | `/case/source/query` | POST | `getCaseSource` | 取得個案來源清單 |
| 22 | `/case/contract/caseList` | POST | `caseContractList` | 取得個案合約列表（v3 iframe 串接用）。參數：`companyId`、`service`（Array，居服/日照）、`status` |

#### caseQRcode.js（個案二維條碼）

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 23 | `/case/qrcode/create` | POST | `createQRCode` | 新增個案二維條碼。參數：`caseId`。設定 7 天過期時間 |
| 24 | `/case/qrcode/continue` | POST | `continueQRCode` | 延展個案二維條碼。參數：`qrId`。延展 7 天 |
| 25 | `/case/qrcode/list` | POST | `listQRCode` | 查詢個案二維條碼列表。參數：`caseId` |

#### caseStatus.js（個案狀態管理）

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 26 | `/case/checkClosure` | POST | `checkClosure` | 取得結案日期後已簽退的服務紀錄數量。參數：`caseId`、`caseType`、`closedDate` |
| 27 | `/case/updateClosure` | POST | `updateClosure` | 設定個案狀態（結案/暫停/恢復服務）。參數：`_id`、`caseType`、`status`（CLOSED/PENDING/SERVICE）、`pendingDate`/`closedDate`、`pendingMemo`/`closedMemo`、`closedReason`、`deleteShift` |
| 28 | `/case/updateClosureHistory` | POST | `updateClosureHistory` | 修改個案狀態歷史紀錄。參數：`_id`、`status`、`date`、`memo`、`closedReason`、`index`（歷史紀錄編號）、`type`（'0'=刪除, '1'=更新） |
| 29 | `/case/deleteShiftsOfClosureCase` | POST | `deleteShiftsOfClosureCase` | 個案結案刪除排班。參數：`caseId`、`companyId`、`closedDate` |
| 30 | `/case/deleteShiftsOfPendingCase` | POST | `deleteShiftsOfPendingCase` | 個案暫停刪除排班。參數：`caseId`、`companyId`、`pendingDate` |
| 31 | `/case/leaveShiftsOfPendingCase` | POST | `leaveShiftsOfPendingCase` | 個案暫停案主請假。參數：`caseId`、`companyId`、`pendingStartDate`、`pendingEndDate`。最多 6 個月 |

#### caseContract.js（合約 PDF）

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 32 | `/case/contract/producePdf` | POST | `producePdfContract` | 生成合約 PDF 檔。參數：`caseId`。僅 compal/yahui 機構可用。從個案及案主資料填入合約範本 |

#### caseReport.js（個案報表）

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 33 | `/case/getCaseSummary` | POST | `getCaseSummary` | 取得個案服務執行項目次數及金額。參數：`year`、`month`、`enableSeqOrder`、`caseId`、`selectedStartDate`、`selectedEndDate`、`reportType`（WriteOffList/WriteOffGCodeList）。支援多維度篩選（督導、員工、個案） |

#### caseHtml.js（HTML 匯入）

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 34 | `/case/uploadCase` | POST | `uploadCase` | 透過 HTML 匯入個案資料（解析）。參數：`req.files.file`（HTML 檔）、`caseName`。解析後回傳資料供前端確認 |
| 35 | `/case/uploadRefresh` | POST | `uploadRefresh` | 透過 HTML 匯入個案照顧計畫（解析）。參數：`req.files.file`（HTML 檔）、`caseName` |
| 36 | `/case/import` | POST | `import` | 依 HTML 內容新增個案。參數：`basicInfo`、`evaluation`、`takeCarePlan`、`isAutoJudgeAA11`、`startDate`、`ignoreDuplicate` |
| 37 | `/case/refresh` | POST | `refresh` | 依 HTML 內容更新個案照顧計畫。參數：`caseId`、照顧計畫相關欄位 |

### `/caseCharts` 路由群組

#### caseChartsController.js（個案資源圖）

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 38 | `/caseCharts/list` | POST | `list` | 列出個案資源圖列表。參數：`caseId`。透過 v3 API 代理呼叫 `/main/app/api/v1/caseCharts` |

### `/caseform` 路由群組

#### caseformController.js（評鑑表單）

以下表單類型共用一致的 CRUD 介面（create/list/detail/update/report/remove），部分類型額外支援 upload：

| 表單類型 | 路由前綴 | 說明 |
|---------|---------|------|
| `open` | `/caseform/open` | 開案表單（額外支援 upload） |
| `visit` | `/caseform/visit` | 訪視表單 |
| `environmentAssessment` | `/caseform/environmentAssessment` | 環境評估表單 |
| `needs` | `/caseform/needs` | 需求評估表單 |
| `care` | `/caseform/care` | 照顧表單 |
| `mind` | `/caseform/mind` | 心智表單 |
| `mood` | `/caseform/mood` | 情緒表單 |
| `change` | `/caseform/change` | 異動表單 |
| `audit` | `/caseform/audit` | 稽核表單 |
| `schedule` | `/caseform/schedule` | 排程表單 |
| `inventory` | `/caseform/inventory` | 盤點表單 |
| `referral` | `/caseform/referral` | 轉介表單（額外支援 upload） |
| `discuss` | `/caseform/discuss` | 討論表單（額外支援 upload） |
| `close` | `/caseform/close` | 結案表單 |
| `plan` | `/caseform/plan` | 照顧計畫表單（額外支援 updateReviewStatus） |
| `record` | `/caseform/record` | 紀錄表單 |
| `report` | `/caseform/report` | 報表（create/list/download/remove） |

各表單 CRUD 路由明細：

| # | 路由 | Method | Handler | 說明 |
|---|------|--------|---------|------|
| 39 | `/caseform/open/create` | POST | `caseFormOpen.create` | 新增開案表單 |
| 40 | `/caseform/open/list` | POST | `caseFormOpen.list` | 開案表單列表 |
| 41 | `/caseform/open/detail` | POST | `caseFormOpen.detail` | 開案表單詳情 |
| 42 | `/caseform/open/update` | POST | `caseFormOpen.update` | 更新開案表單 |
| 43 | `/caseform/open/report` | POST | `caseFormOpen.report` | 開案表單報表 |
| 44 | `/caseform/open/remove` | POST | `caseFormOpen.remove` | 刪除開案表單 |
| 45 | `/caseform/open/upload` | POST | `caseFormOpen.uploadImage` | 上傳開案表單圖片 |
| 46 | `/caseform/visit/create` | POST | `caseFormVisit.create` | 新增訪視表單 |
| 47 | `/caseform/visit/list` | POST | `caseFormVisit.list` | 訪視表單列表 |
| 48 | `/caseform/visit/detail` | POST | `caseFormVisit.detail` | 訪視表單詳情 |
| 49 | `/caseform/visit/update` | POST | `caseFormVisit.update` | 更新訪視表單 |
| 50 | `/caseform/visit/report` | POST | `caseFormVisit.report` | 訪視表單報表 |
| 51 | `/caseform/visit/remove` | POST | `caseFormVisit.remove` | 刪除訪視表單 |
| 52 | `/caseform/environmentAssessment/create` | POST | `create` | 新增環境評估表單 |
| 53 | `/caseform/environmentAssessment/list` | POST | `list` | 環境評估表單列表 |
| 54 | `/caseform/environmentAssessment/detail` | POST | `detail` | 環境評估表單詳情 |
| 55 | `/caseform/environmentAssessment/update` | POST | `update` | 更新環境評估表單 |
| 56 | `/caseform/environmentAssessment/report` | POST | `report` | 環境評估表單報表 |
| 57 | `/caseform/environmentAssessment/remove` | POST | `remove` | 刪除環境評估表單 |
| 58 | `/caseform/needs/create` | POST | `create` | 新增需求評估表單 |
| 59 | `/caseform/needs/list` | POST | `list` | 需求評估表單列表 |
| 60 | `/caseform/needs/detail` | POST | `detail` | 需求評估表單詳情 |
| 61 | `/caseform/needs/update` | POST | `update` | 更新需求評估表單 |
| 62 | `/caseform/needs/report` | POST | `report` | 需求評估表單報表 |
| 63 | `/caseform/needs/remove` | POST | `remove` | 刪除需求評估表單 |
| 64 | `/caseform/care/create` | POST | `create` | 新增照顧表單 |
| 65 | `/caseform/care/list` | POST | `list` | 照顧表單列表 |
| 66 | `/caseform/care/detail` | POST | `detail` | 照顧表單詳情 |
| 67 | `/caseform/care/update` | POST | `update` | 更新照顧表單 |
| 68 | `/caseform/care/report` | POST | `report` | 照顧表單報表 |
| 69 | `/caseform/care/remove` | POST | `remove` | 刪除照顧表單 |
| 70 | `/caseform/mind/create` | POST | `create` | 新增心智表單 |
| 71 | `/caseform/mind/list` | POST | `list` | 心智表單列表 |
| 72 | `/caseform/mind/detail` | POST | `detail` | 心智表單詳情 |
| 73 | `/caseform/mind/update` | POST | `update` | 更新心智表單 |
| 74 | `/caseform/mind/report` | POST | `report` | 心智表單報表 |
| 75 | `/caseform/mind/remove` | POST | `remove` | 刪除心智表單 |
| 76 | `/caseform/mood/create` | POST | `create` | 新增情緒表單 |
| 77 | `/caseform/mood/list` | POST | `list` | 情緒表單列表 |
| 78 | `/caseform/mood/detail` | POST | `detail` | 情緒表單詳情 |
| 79 | `/caseform/mood/update` | POST | `update` | 更新情緒表單 |
| 80 | `/caseform/mood/report` | POST | `report` | 情緒表單報表 |
| 81 | `/caseform/mood/remove` | POST | `remove` | 刪除情緒表單 |
| 82 | `/caseform/change/create` | POST | `create` | 新增異動表單 |
| 83 | `/caseform/change/list` | POST | `list` | 異動表單列表 |
| 84 | `/caseform/change/detail` | POST | `detail` | 異動表單詳情 |
| 85 | `/caseform/change/update` | POST | `update` | 更新異動表單 |
| 86 | `/caseform/change/report` | POST | `report` | 異動表單報表 |
| 87 | `/caseform/change/remove` | POST | `remove` | 刪除異動表單 |
| 88 | `/caseform/audit/create` | POST | `create` | 新增稽核表單 |
| 89 | `/caseform/audit/list` | POST | `list` | 稽核表單列表 |
| 90 | `/caseform/audit/detail` | POST | `detail` | 稽核表單詳情 |
| 91 | `/caseform/audit/update` | POST | `update` | 更新稽核表單 |
| 92 | `/caseform/audit/report` | POST | `report` | 稽核表單報表 |
| 93 | `/caseform/audit/remove` | POST | `remove` | 刪除稽核表單 |
| 94 | `/caseform/schedule/create` | POST | `create` | 新增排程表單 |
| 95 | `/caseform/schedule/list` | POST | `list` | 排程表單列表 |
| 96 | `/caseform/schedule/detail` | POST | `detail` | 排程表單詳情 |
| 97 | `/caseform/schedule/update` | POST | `update` | 更新排程表單 |
| 98 | `/caseform/schedule/report` | POST | `report` | 排程表單報表 |
| 99 | `/caseform/schedule/remove` | POST | `remove` | 刪除排程表單 |
| 100 | `/caseform/inventory/create` | POST | `create` | 新增盤點表單 |
| 101 | `/caseform/inventory/list` | POST | `list` | 盤點表單列表 |
| 102 | `/caseform/inventory/detail` | POST | `detail` | 盤點表單詳情 |
| 103 | `/caseform/inventory/update` | POST | `update` | 更新盤點表單 |
| 104 | `/caseform/inventory/report` | POST | `report` | 盤點表單報表 |
| 105 | `/caseform/inventory/remove` | POST | `remove` | 刪除盤點表單 |
| 106 | `/caseform/referral/create` | POST | `createReferral` | 新增轉介表單 |
| 107 | `/caseform/referral/list` | POST | `list` | 轉介表單列表 |
| 108 | `/caseform/referral/detail` | POST | `detail` | 轉介表單詳情 |
| 109 | `/caseform/referral/update` | POST | `update` | 更新轉介表單 |
| 110 | `/caseform/referral/report` | POST | `report` | 轉介表單報表 |
| 111 | `/caseform/referral/remove` | POST | `remove` | 刪除轉介表單 |
| 112 | `/caseform/referral/upload` | POST | `uploadImage` | 上傳轉介表單圖片 |
| 113 | `/caseform/discuss/create` | POST | `createDiscuss` | 新增討論表單 |
| 114 | `/caseform/discuss/list` | POST | `list` | 討論表單列表 |
| 115 | `/caseform/discuss/detail` | POST | `detail` | 討論表單詳情 |
| 116 | `/caseform/discuss/update` | POST | `update` | 更新討論表單 |
| 117 | `/caseform/discuss/report` | POST | `report` | 討論表單報表 |
| 118 | `/caseform/discuss/remove` | POST | `remove` | 刪除討論表單 |
| 119 | `/caseform/discuss/upload` | POST | `uploadImage` | 上傳討論表單圖片 |
| 120 | `/caseform/close/create` | POST | `create` | 新增結案表單 |
| 121 | `/caseform/close/list` | POST | `list` | 結案表單列表 |
| 122 | `/caseform/close/detail` | POST | `detail` | 結案表單詳情 |
| 123 | `/caseform/close/update` | POST | `update` | 更新結案表單 |
| 124 | `/caseform/close/report` | POST | `report` | 結案表單報表 |
| 125 | `/caseform/close/remove` | POST | `remove` | 刪除結案表單 |
| 126 | `/caseform/plan/create` | POST | `create` | 新增照顧計畫表單 |
| 127 | `/caseform/plan/list` | POST | `list` | 照顧計畫表單列表 |
| 128 | `/caseform/plan/detail` | POST | `detail` | 照顧計畫表單詳情 |
| 129 | `/caseform/plan/update` | POST | `update` | 更新照顧計畫表單 |
| 130 | `/caseform/plan/report` | POST | `report` | 照顧計畫表單報表 |
| 131 | `/caseform/plan/remove` | POST | `remove` | 刪除照顧計畫表單 |
| 132 | `/caseform/plan/updateReviewStatus` | POST | `updateReviewStatus` | 更新照顧計畫審查狀態 |
| 133 | `/caseform/record/create` | POST | `create` | 新增紀錄表單 |
| 134 | `/caseform/record/list` | POST | `list` | 紀錄表單列表 |
| 135 | `/caseform/record/detail` | POST | `detail` | 紀錄表單詳情 |
| 136 | `/caseform/record/update` | POST | `update` | 更新紀錄表單 |
| 137 | `/caseform/record/report` | POST | `reportRecord` | 紀錄表單報表 |
| 138 | `/caseform/record/remove` | POST | `remove` | 刪除紀錄表單 |
| 139 | `/caseform/report/create` | POST | `caseReportControl.create` | 新增報表 |
| 140 | `/caseform/report/list` | POST | `caseReportControl.list` | 報表列表 |
| 141 | `/caseform/report/download` | POST | `caseReportControl.download` | 下載報表 |
| 142 | `/caseform/report/remove` | POST | `caseReportControl.remove` | 刪除報表 |

## 資料模型

主要使用的 Model：

| Model | 用途 |
|-------|------|
| `CaseModel` | 個案主資料 |
| `CustomerModel` | 案主資料 |
| `CaseCategoryModel` | 個案分類 |
| `CaseSourceModel` | 個案來源 |
| `CaseQRCodeModel` | 個案二維條碼 |
| `NameModel` | 姓名加密儲存 |
| `PersonalIdModel` | 身份證加密儲存 |
| `ServiceItemModel` | 服務項目 |
| `ServiceRecordModel` | 服務紀錄 |
| `PlanModel` | 照顧計畫 |
| `EmployeeModel` | 員工資料 |
| `CompanyModel` | 機構資料 |
| `FormModel` / `FormResultModel` | 評鑑表單及結果 |
| `CloseAccountSettingModel` | 關帳設定 |

## 中介層

所有 `/case` 路由經過以下 middleware（定義於 `routes/index.js`）：

1. `auth` — 身份驗證
2. `RequestRewriter.rewrite` — 請求改寫
3. `saveSimpleLogForRequest` — 簡易請求日誌
4. `checkAccountIsClosed` — 關帳檢核
5. `rule` — 權限規則

## 業務邏輯摘要

### 個案類別（CaseType）
- `01` — 居家服務（HOMECARE）
- `02` — 日照服務（DAYCARE）
- `03` — 喘息服務（RESTBED）
- `04` — 專 A 服務（EXPERTA）

### 個案狀態流轉（CaseStatusType）
- `SERVICE` — 服務中
- `PENDING` — 暫停（可設定案主請假、保留日）
- `CLOSED` — 結案（需設定結案原因、結案日期）
- 狀態歷史紀錄存於 `statusHistory` 陣列，支援編輯/刪除歷史紀錄

### HTML 匯入流程
1. `uploadCase` / `uploadRefresh` — 上傳 HTML 檔案並解析，回傳解析結果供前端預覽
2. `import` / `refresh` — 前端確認後，依解析內容新增個案或更新照顧計畫

### 評鑑表單（caseform）
- 16 種表單類型，各自獨立的 Controller class（繼承 `BaseFormController`）
- 統一的 CRUD 介面：create / list / detail / update / report / remove
- 部分表單支援圖片上傳（open、referral、discuss）
- plan 表單額外支援 `updateReviewStatus`
- report 群組提供報表的 create / list / download / remove

## 品質觀察

1. **`caseController.js` 過大**（1884 行）：核心 CRUD 仍混合在單一檔案中，雖已拆出 Query/Status/Contract/Report/Html，但 create 方法本身超過 500 行的 waterfall callback
2. **混用程式風格**：`caseController.js` 使用舊式 `function` + `this` binding 風格，較新的檔案（caseQuery/caseStatus）使用 class + arrow function
3. **全部 API 都用 POST**：即使是查詢操作（query/list/names）也使用 POST method，不符合 RESTful 慣例
4. **`caseHtml.js` 過大**（2116 行）：HTML 解析和個案建立邏輯高度耦合
5. **`caseformController.js` 重複模式**：16 種表單類型的 route 註冊高度重複，可考慮抽象為迴圈產生

## 完整性驗證

- 驗證日期：2026-03-11
- 原始碼 route 總數：
  - `caseController.js`: 12 routes
  - `caseQuery.js`: 10 routes
  - `caseQRcode.js`: 3 routes
  - `caseStatus.js`: 6 routes
  - `caseContract.js`: 1 route
  - `caseReport.js`: 1 route
  - `caseHtml.js`: 4 routes
  - `caseChartsController.js`: 1 route
  - `caseformController.js`: 104 routes
  - **原始碼 route 總數: 142**
- Spec 列出數量：142
- 完整度：100%
