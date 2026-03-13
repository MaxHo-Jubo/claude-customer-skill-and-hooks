# Backend Spec API 完整性驗證報告

> 驗證日期：2026-03-11
> 驗證範圍：`backend/spec/controllers/*.md`（共 26 份 spec）
> 驗證方法：比對 spec 中記載的 API 端點數量 vs 原始碼中 `router.route()` 註冊的路由數量

---

## 方法論

1. 掃描 `backend/spec/controllers/` 下所有 `.md` 檔案
2. 依據 `routes/index.js` 的路由映射規則（`CONTROLLER_ROUTING_MAPPING`），建立每份 spec 對應的 controller 檔案清單
3. 對每個 controller 檔案，用 `grep` 計算 `.route(` 出現次數（即實際註冊的路由數）
4. 對每份 spec，用 `grep` 計算記載了 HTTP 方法（POST/GET/PUT/PATCH/DELETE）的表格行或標題行數量
5. 比對兩者差異

### 重要限制

- **模式化路由**：部分 controller（如 `caseformController.js` 104 條、`formreportController.js` 82 條、`companyformController.js` 36 條、`employeeformController.js` 30 條）使用 factory pattern 為多種表單類型各生成一組相同結構的路由。spec 中以 `{type}` 標記此類模式化路由，僅列出一組樣板，不逐一展開。此為合理的文件撰寫策略。
- **Spec 精讀狀態不一**：部分 spec 為「精讀完成」、部分為「skeleton」，skeleton 版本的 API 覆蓋率本就預期較低。

---

## 總覽

| 指標 | 數值 |
|------|------|
| Spec 總數 | 26 |
| 完全匹配（含模式化路由的合理簡化） | 6 |
| 原始碼路由多於 spec（有未記載路由） | 10 |
| Spec 記載多於原始碼（可能有重複或跨 spec 記載） | 3 |
| 無直接路由（工具/基底/報表子目錄） | 7 |

---

## 逐 Spec 比對結果

### 完全匹配

| Spec 檔案 | Spec API 數 | 原始碼路由數 | 對應 Controllers |
|-----------|------------|------------|-----------------|
| `account.md` | 26 | 26 | accountController(20) + closeAccountController(3) + roleMenuController(3) |
| `shift.md` | 52 | 52 | shiftController(20) + shiftRecordController(13) + shiftPunchController(6) + shiftPeriodController(3) + shiftInfo(2) + scheduleController(5) + scheduleTemplateController(3) |
| `contactBook.md` | 30 | 30 | contactBookController(30) |
| `fee.md` | 17 | 17 | chargeController(7) + accountingNoticeController(1) + receiptManageController(7) + salaryController(2) |
| `myDataController.md` | 2 | 2 | myAPIController(2) |
| `management.md` | 2 | 2 | management/report/serviceRecord/summary(1) + management/report/daycareRecord/DC_WorkRecord_Monthly_CH(1) |

### 原始碼路由多於 Spec（有未記載路由）

| Spec 檔案 | Spec API 數 | 原始碼路由數 | 差異 | Spec 狀態 | 說明 |
|-----------|------------|------------|------|----------|------|
| `case.md` | 42 | 142 | +100 | 精讀完成 | **主因**：`caseformController.js` 有 104 條模式化路由，spec 以 `{type}` 模式記載 7 條樣板（代表 16 種表單類型 x 6-7 條），spec 自述「路由總數 ~139」，實際覆蓋率合格 |
| `form.md` | 40 | 124 | +84 | 精讀完成 | **主因**：`formreportController.js` 有 82 條模式化路由，spec 以 `{type}` 模式記載 2 條樣板（代表 27 種報表類型 x 3 條），spec 自述「路由總數 ~124」，實際覆蓋率合格 |
| `employee.md` | 26 | 87 | +61 | skeleton | **缺漏**：僅記載 `employeeController.js`(26) 路由，未記載 employeeLeave(16)、employeeformController(30)、employeeDayCare(5)、employeeShare(5)、employeeRecordController(5) 的 API 端點，spec 自述「路由總數 26」 |
| `company.md` | 46 | 76 | +30 | skeleton | **缺漏**：未完整記載 `companyformController.js`(36) 的模式化路由端點 |
| `system.md` | 167 | 189 | +22 | skeleton | 涵蓋 34 個 controller，有 22 條路由未記載 |
| `dayCare.md` | 6 | 21 | +15 | 精讀完成 | **缺漏**：`daycaseController.js`(10) + `expertAcaseController.js`(11) = 21 條，spec 僅記載 6 條 |
| `dayCaseController.md` | 181 | 191 | +10 | skeleton | 19 個 dayCaseController 子目錄 controller 中有 10 條路由未記載 |
| `report.md` | 18 | 28 | +10 | skeleton | `reportController.js`(14) + `reportSalaryController.js`(2) + `statCodeDCController.js`(6) + `statCodeGController.js`(6) = 28，spec 僅記載 18 條 |
| `customer.md` | 46 | 58 | +12 | 精讀完成 | 8 個 controller 共 58 條路由，spec 記載 46 條，有 12 條未記載 |
| `serviceRecord.md` | 13 | 14 | +1 | skeleton | 差異極小，可能遺漏 `importController.js`(1) |

### Spec 記載多於原始碼

| Spec 檔案 | Spec API 數 | 原始碼路由數 | 差異 | 說明 |
|-----------|------------|------------|------|------|
| `message.md` | 45 | 15 | -30 | **跨 spec 重複**：message.md 的 scope 包含 contactBookController.js(30 條)，而 contactBook.md 也完整記載了同一批路由。扣除重複後 messageController(14) + remindController(1) = 15，匹配。 |
| `feeApply.md` | 23 | 22 | -1 | 差異極小（1 條），可能 spec 記載了已廢棄或尚未實作的端點 |
| `base.md` | 2 | 0 | -2 | base 目錄為基底類別，不直接暴露路由，spec 中記載的可能是方法而非路由 |

### 無直接路由（工具/基底/報表子目錄）

| Spec 檔案 | 說明 |
|-----------|------|
| `index.md` | 總覽文件，不記載 API 端點 |
| `formUtils.md` | 表單工具函式，無路由 |
| `batchFormReport.md` | 批次表單報表，由 formreportController 觸發 |
| `caseFormReport.md` | 個案表單報表，由 caseformController 觸發 |
| `companyFormReport.md` | 機構表單報表，由 companyformController 觸發 |
| `employeeFormReport.md` | 員工表單報表，由 employeeformController 觸發 |
| `formReport.md` | 通用表單報表，由 formController 觸發 |

---

## 關鍵發現

### 1. 模式化路由的文件策略（合理）

`case.md` 和 `form.md` 面對大量模式化路由（caseformController 104 條、formreportController 82 條），採用 `{type}` 樣板標記法，避免重複文件。兩份 spec 均在總覽中自述正確的路由總數（~139、~124），這是合理的文件撰寫策略。

### 2. Skeleton Spec 覆蓋率不足（需改進）

以下 skeleton spec 缺漏明顯：

| Spec | 缺漏路由數 | 主要缺漏來源 |
|------|-----------|-------------|
| `employee.md` | 61 | employeeLeave(16)、employeeformController(30)、employeeDayCare(5)、employeeShare(5)、employeeRecordController(5) 完全未記載 |
| `company.md` | 30 | companyformController(36) 模式化路由未展開 |
| `system.md` | 22 | 34 個 controller 中零散遺漏 |
| `dayCaseController.md` | 10 | 19 個子 controller 中零散遺漏 |
| `report.md` | 10 | statCodeDCController(6) 和 statCodeGController(6) 部分未記載 |

### 3. 跨 Spec 重複記載（需修正）

`message.md` 將 `contactBookController.js`（30 條路由）納入 scope，但 `contactBook.md` 也完整記載了同一批路由。建議：
- **方案 A**：`message.md` 移除 contactBookController 相關內容，僅保留 messageController + remindController
- **方案 B**：`contactBook.md` 改為引用 `message.md` 的聯絡簿段落，避免維護兩份

### 4. 精讀完成但仍有缺漏（需注意）

- `dayCare.md`（精讀完成）：僅記載 6/21 條路由，缺漏率 71%
- `customer.md`（精讀完成）：缺漏 12 條路由，缺漏率 21%

---

## 統計摘要

| 指標 | 數值 |
|------|------|
| Spec 記載 API 總數 | 762 |
| 原始碼路由總數（含模式化展開） | 1,097 |
| 模式化路由佔原始碼比例 | ~23%（caseform 104 + formreport 82 + companyform 36 + employeeform 30 = 252） |
| 扣除模式化路由後原始碼路由數 | ~845 |
| 扣除跨 spec 重複後 Spec 記載數 | ~732 |
| 實際覆蓋率（扣除模式化 + 重複） | ~87% |
| 完全匹配的 Spec 數 | 6/26（23%） |
| 有實質缺漏的 Spec 數 | 7/26（27%） |

---

## 建議優先處理順序

1. **`employee.md`** — 缺漏 61 條，最嚴重，需補齊 5 個子 controller 的 API 端點
2. **`company.md`** — 缺漏 30 條，需補齊 companyformController 模式化路由
3. **`system.md`** — 缺漏 22 條，需逐一比對 34 個 controller
4. **`dayCare.md`** — 標記「精讀完成」但缺漏率 71%，需重新審視
5. **`customer.md`** — 標記「精讀完成」但缺漏 12 條
6. **`message.md`** — 修正跨 spec 重複問題
7. **`dayCaseController.md`** / **`report.md`** — 各缺漏 10 條
