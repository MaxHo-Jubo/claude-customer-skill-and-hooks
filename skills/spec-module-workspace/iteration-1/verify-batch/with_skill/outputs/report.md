# Spec 批次驗證報告

> 驗證日期：2026-03-11
> 目標目錄：`backend/spec/controllers/`
> Spec 檔案數：25（排除 index.md）

---

## 批次驗證摘要

```
✅ account.md         — 26/26   (100%)
⚠️ base.md            — N/A     (工具類模組，無 HTTP 路由)
✅ batchFormReport.md  — N/A     (報表產生器，非路由控制器)
❌ case.md             — 42/142  (30%)  — 缺 100 個 API（caseformController 104 條路由僅概述未逐一列出）
✅ caseFormReport.md   — N/A     (報表產生器函式庫，無路由)
❌ company.md          — 46/76   (61%)  — 缺 30 個 API（companyformController 36 條路由未列出）
✅ companyFormReport.md — N/A    (報表產生器函式庫，無路由)
✅ contactBook.md      — 30/30   (100%)
⚠️ customer.md         — 46/58   (79%)  — 缺 12 個 API（vitalSignsRecord/bodyMeasurement/vaccine/breathing/mealRecord/medicalComment 部分未列出）
⚠️ dayCare.md          — 6/212   (3%)   — 概覽型 spec，詳細 API 列於 dayCaseController.md（設計如此，非遺漏）
⚠️ dayCaseController.md — 181/191 (95%) — 缺 10 個 API（punchRecordController 實際 25 條 vs spec 列 15-16 條等差異）
❌ employee.md         — 26/87   (30%)  — 缺 61 個 API（僅列 employeeController 路由，未列 employeeDayCare/Share/Leave/form/Record）
✅ employeeFormReport.md — N/A   (報表產生器函式庫，無路由)
✅ fee.md              — 17/17   (100%)
⚠️ feeApply.md         — 23/24   (96%)  — 缺 1 個 API（feedbackController 有 2 條，spec 列 23 條 vs 實際 24 條）
❌ form.md             — 40/124  (32%)  — 缺 84 個 API（formreportController 82 條路由在 report.md 描述，formController spec 僅列 39+1 條）
✅ formReport.md       — N/A     (報表產生器函式庫，無路由)
✅ formUtils.md        — N/A     (工具函式庫，無路由)
✅ management.md       — 2/2     (100%)
✅ message.md          — 45/45   (100%)
✅ myDataController.md — 2/2     (100%)
⚠️ report.md           — 18/99   (18%)  — spec 聲稱 63 條但僅逐一列出 18 條；formreportController 49 條以概述方式帶過
✅ serviceRecord.md    — 13/13   (100%)
✅ shift.md            — 52/52   (100%)
⚠️ system.md           — 167/~174 (96%) — 缺 ~7 個 API（部分新增路由未更新至 spec）
```

---

## 詳細比對表

### 路由型 Spec（有 HTTP API 路由的模組）

| Spec 檔案 | Spec 列出 | 原始碼路由數 | 完整度 | 備註 |
|-----------|----------|------------|--------|------|
| account.md | 26 | 26 | 100% | accountController(20) + closeAccountController(3) + roleMenuController(3) |
| case.md | 42 | 142 | 30% | caseformController 有 104 條路由，spec 僅概述「~101 路由」未逐一列出 |
| company.md | 46 | 76 | 61% | companyformController 36 條路由未列入 API 端點表格 |
| contactBook.md | 30 | 30 | 100% | contactBookController 完整覆蓋 |
| customer.md | 46 | 58 | 79% | 缺 vitalSignsRecordController(5)、bodyMeasurementStandard(2)、vaccineRecord(6) 部分未展開 |
| dayCare.md | 6 | 212 | 3% | 設計為概覽 spec，詳細 API 在 dayCaseController.md |
| dayCaseController.md | 181 | 191 | 95% | 各子 controller 路由數與實際有小幅差異（如 punchRecord: spec 16 vs 實際 25） |
| employee.md | 26 | 87 | 30% | 僅列 employeeController 的 26 條，缺 employeeDayCare(5)、employeeShare(5)、employeeLeave(16)、employeeformController(30)、employeeRecordController(5) |
| fee.md | 17 | 17 | 100% | chargeController(7) + receiptManageController(7) + accountingNoticeController(1) + salaryController(2) |
| feeApply.md | 23 | 24 | 96% | feeApplyController(22) + feedbackController(2)，差 1 條 |
| form.md | 40 | 124 | 32% | formController(39) + formToccController(3) = 42 已列；formreportController(82) 歸入 report.md |
| management.md | 2 | 2 | 100% | 2 條 deep-path 路由 |
| message.md | 45 | 45 | 100% | messageController(14) + contactBookController(30) + remindController(1) |
| myDataController.md | 2 | 2 | 100% | myAPIController(2) |
| report.md | 18 | 99 | 18% | 聲稱 63 條，實際列出 18 條；formreportController 49 條以「16 種 × 3 + 1」概述 |
| serviceRecord.md | 13 | 13 | 100% | 4 個 controller 完整覆蓋 |
| shift.md | 52 | 52 | 100% | 7 個 controller 完整覆蓋 |
| system.md | 167 | ~174 | 96% | 33 個雜項 controller，有少量新增路由未更新 |

### 非路由型 Spec（函式庫/工具類，不含 HTTP 路由）

| Spec 檔案 | 類型 | 說明 |
|-----------|------|------|
| base.md | 工具類 | BaseController / BaseControllerClass / BaseFormController — 不掛路由 |
| batchFormReport.md | 報表產生器 | 28 個批次報表處理函式，由上層 controller 呼叫 |
| caseFormReport.md | 報表產生器 | 個案表單報表函式庫 |
| companyFormReport.md | 報表產生器 | 機構表單報表函式庫 |
| employeeFormReport.md | 報表產生器 | 員工表單報表函式庫 |
| formReport.md | 報表產生器 | 通用表單報表函式庫（21 個報表產生器） |
| formUtils.md | 工具函式 | 報表共用工具（日期格式、映射函式等） |

---

## 交叉覆蓋問題

以下 controller 被多個 spec 引用，可能造成重複計算或遺漏：

| Controller | 被引用的 Spec | 說明 |
|-----------|--------------|------|
| `formreportController.js` (82 routes) | form.md（提及）、report.md（詳述） | 路由歸屬不明確，form.md 列出概覽，report.md 詳述 |
| `contactBookController.js` (30 routes) | message.md（完整列出）、contactBook.md（完整列出） | 兩份 spec 都完整列出，屬重複覆蓋 |
| `caseReport.js` (1 route) | case.md、report.md | 透過 routing mapping 掛載於 `/case`，兩邊都有提及 |
| `daycaseController.js` + `expertAcaseController.js` | dayCare.md（概覽）、dayCaseController.md（部分） | dayCare.md 涵蓋根目錄 controller，dayCaseController.md 涵蓋子目錄 |

---

## 統計總結

| 指標 | 數值 |
|------|------|
| 路由型 Spec | 18 個 |
| 非路由型 Spec | 7 個 |
| 完整覆蓋 (100%) | 9 個（account、contactBook、fee、management、message、myDataController、serviceRecord、shift、dayCare 概覽設計） |
| 高覆蓋 (90%+) | 3 個（dayCaseController 95%、feeApply 96%、system 96%） |
| 中覆蓋 (50-89%) | 2 個（customer 79%、company 61%） |
| 低覆蓋 (<50%) | 4 個（case 30%、employee 30%、form 32%、report 18%） |

### 低覆蓋主因分析

1. **case.md (30%)**：`caseformController.js` 有 104 條路由（16 種個案表單 × CRUD），spec 僅概述未逐一列出
2. **employee.md (30%)**：spec 只列了 `employeeController.js` 的 26 條路由，缺 5 個子 controller 共 61 條路由
3. **form.md (32%)**：`formreportController.js` 的 82 條路由被歸入 `report.md` 而非 `form.md`，導致 form.md 僅列 42 條
4. **report.md (18%)**：spec 聲稱 63 條路由但僅逐一列出 18 條，其中 formreportController 49 條以概述方式（16 種 × 3 + 1）帶過
