# Spec 驗證報告：backend/spec/controllers/employee.md

> 驗證日期：2026-03-11
> 比對方式：spec 文件 vs 原始碼 route 定義

---

## 總結

| 項目 | Spec 記載 | 實際原始碼 | 差異 |
|------|-----------|------------|------|
| 路由總數 | 26 | 52（`/employee/*` 前綴） + 5（`/employeeRecord/*`） + 30（`/employeeform/*`） = 87 | 見下方分析 |
| Controllers | 6 | 6（employeeController, employeeDayCare, employeeLeave, employeeShare, employeeRecordController, employeeformController） | 一致 |

### 結論：Spec 的 API 端點列表嚴重不完整

Spec 僅列出 `employeeController.js` 的 26 條路由，完全遺漏了其他 5 個 controller 的所有路由（共 61 條）。雖然 spec 在「核心功能」段落以文字描述了請假、拆帳、日照打卡等功能，但 **API 端點表格** 中完全沒有列出這些路由。

---

## 詳細比對

### 1. employeeController.js — 26 條路由（前綴 `/employee/`）

Spec 列出 26 條，實際原始碼也是 26 條。**完全一致。**

| Spec 路由 | 原始碼 | 狀態 |
|-----------|--------|------|
| `/employee/list` | `router.route('/list').post(...)` | OK |
| `/employee/profile` | `router.route('/profile').post(...)` | OK |
| `/employee/create` | `router.route('/create').post(...)` | OK |
| `/employee/update` | `router.route('/update').post(...)` | OK |
| `/employee/delete` | `router.route('/delete').post(...)` | OK |
| `/employee/query` | `router.route('/query').post(...)` | OK |
| `/employee/getMasterSupervisorList` | `router.route('/getMasterSupervisorList').post(...)` | OK |
| `/employee/recommend` | `router.route('/recommend').post(...)` | OK |
| `/employee/recommendFast` | `router.route('/recommendFast').post(...)` | OK |
| `/employee/getAvailableList` | `router.route('/getAvailableList').post(...)` | OK |
| `/employee/additionalSetting/query` | `router.route('/additionalSetting/query').post(...)` | OK |
| `/employee/additionalSetting/update` | `router.route('/additionalSetting/update').post(...)` | OK |
| `/employee/salary/update` | `router.route('/salary/update').post(...)` | OK |
| `/employee/attendance/list` | `router.route('/attendance/list').post(...)` | OK |
| `/employee/attendance/update` | `router.route('/attendance/update').post(...)` | OK |
| `/employee/attendance/delete` | `router.route('/attendance/delete').post(...)` | OK |
| `/employee/agreedPrivacyPolicyHistory` | `router.route('/agreedPrivacyPolicyHistory').post(...)` | OK |
| `/employee/agreedFeatureTermsOfUse` | `router.route('/agreedFeatureTermsOfUse').post(...)` | OK |
| `/employee/multiUpdateEmployee` | `router.route('/multiUpdateEmployee').post(...)` | OK |
| `/employee/changeEmployeeSupervisor` | `router.route('/changeEmployeeSupervisor').post(...)` | OK |
| `/employee/changeCaseDriverAndDaycaregiver` | `router.route('/changeCaseDriverAndDaycaregiver').post(...)` | OK |
| `/employee/calendar/list` | `router.route('/calendar/list').post(...)` | OK |
| `/employee/calendar/update` | `router.route('/calendar/update').post(...)` | OK |
| `/employee/calendar/delete` | `router.route('/calendar/delete').post(...)` | OK |
| `/employee/shiftSetting/list` | `router.route('/shiftSetting/list').post(...)` | OK |
| `/employee/shiftSetting/update` | `router.route('/shiftSetting/update').post(...)` | OK |

---

### 2. employeeDayCare.js — 5 條路由（前綴 `/employee/`，透過 CONTROLLER_ROUTING_MAPPING 映射）

**Spec 完全遺漏。** Spec 在核心功能段落提到日照打卡功能，但 API 端點表格中沒有列出。

| 遺漏的路由 | 說明 |
|-----------|------|
| POST `/employee/shift/dayCare/profile` | 查詢日照照服員上下班打卡時間 |
| POST `/employee/shift/dayCare/list` | 日照照服員排班列表 |
| POST `/employee/shift/dayCare/update` | 更新日照照服員上下班打卡時間 |
| POST `/employee/shift/dayCare/delete` | 刪除日照照服員上下班打卡時間 |
| POST `/employee/shift/dayCare/calculate` | 統計日照照服員打卡人數 |

---

### 3. employeeLeave.js — 16 條路由（前綴 `/employee/`，透過 CONTROLLER_ROUTING_MAPPING 映射）

**Spec 完全遺漏。** Spec 在核心功能段落提到請假管理功能，但 API 端點表格中沒有列出。

| 遺漏的路由 | 說明 |
|-----------|------|
| POST `/employee/leave/list` | 請假列表 |
| POST `/employee/leave/create` | 建立請假 |
| POST `/employee/leave/cancel` | 銷假 |
| POST `/employee/leave/update` | 更新請假 |
| POST `/employee/leave/delete` | 刪除請假 |
| POST `/employee/leave/count` | 請假統計 |
| POST `/employee/leave/records` | 請假紀錄（V3） |
| POST `/employee/leave/countRecord` | 請假紀錄統計 |
| POST `/employee/leave/dayCare/list` | 日照請假列表 |
| POST `/employee/leave/dayCare/upsert` | 日照請假新增/更新 |
| POST `/employee/leave/dayCare/listEmployee` | 查詢有請假紀錄之照服員 |
| POST `/employee/leave/dayCare/listLeaveDurationSchedule` | 請假區間排班 |
| POST `/employee/leave/dayCare/getSubDriverHasShuttle` | 代理司機排班查詢 |
| POST `/employee/leaveManager/list` | 請假管理列表 |
| POST `/employee/leaveManager/listLeaveDurationShift` | 請假區間班表 |
| POST `/employee/leave/multiReview` | 批次審核請假 |

---

### 4. employeeShare.js — 5 條路由（前綴 `/employee/`，透過 CONTROLLER_ROUTING_MAPPING 映射）

**Spec 完全遺漏。** Spec 在核心功能段落提到拆帳功能，但 API 端點表格中沒有列出。

| 遺漏的路由 | 說明 |
|-----------|------|
| POST `/employee/share/query` | 查詢拆帳設定 |
| POST `/employee/share/create` | 建立拆帳設定 |
| POST `/employee/share/update` | 更新拆帳設定 |
| POST `/employee/share/delete` | 刪除拆帳設定 |
| POST `/employee/share/switch` | 切換拆帳設定 |

---

### 5. employeeRecordController.js — 5 條路由（前綴 `/employeeRecord/`）

**Spec 完全遺漏。** Spec 在核心功能段落提到員工紀錄功能，也在主要檔案和服務方法中描述了 `employeeRecordController.js` 和 `EmployeeRecordService`，但 API 端點表格中沒有列出。

| 遺漏的路由 | 說明 |
|-----------|------|
| POST `/employeeRecord/create` | 建立員工紀錄 |
| POST `/employeeRecord/query` | 查詢員工紀錄 |
| POST `/employeeRecord/update` | 更新員工紀錄 |
| POST `/employeeRecord/delete` | 刪除員工紀錄 |
| POST `/employeeRecord/statistics` | 員工紀錄統計（足跡查詢） |

**注意**：此 controller 的 API 前綴是 `/employeeRecord/` 而非 `/employee/`，spec 中記載的 API 路徑前綴為 `/employee/*` 並不涵蓋這些路由。

---

### 6. employeeformController.js — 30 條路由（前綴 `/employeeform/`）

**Spec 完全遺漏。** 這些是員工表單相關的 CRUD 路由，有獨立的 API 前綴 `/employeeform/`。

5 個表單類型 x 6 個操作（create/list/detail/update/report/remove）= 30 條路由：

| 表單類型 | 路由前綴 |
|---------|---------|
| 職前訓練 (pretrain) | `/employeeform/pretrain/*` |
| 督導職前訓練 (superpretrain) | `/employeeform/superpretrain/*` |
| 考核 (assessment) | `/employeeform/assessment/*` |
| 個督 (supervise) | `/employeeform/supervise/*` |
| 資深個督 (seniorSupervise) | `/employeeform/seniorSupervise/*` |

**注意**：spec 的「主要檔案」表格有列出 `employeeformController.js`，但 API 端點和路由前綴未記載。此 controller 的 API 前綴是 `/employeeform/`。

---

## Spec 其他項目驗證

### 總覽數據

| Spec 記載 | 驗證結果 |
|-----------|---------|
| 檔案數 60 | glob 搜尋找到 55+ 個 employee 相關檔案，大致合理（含 config/json 等） |
| 程式碼總行數 25,588 | 未逐一計算，無法確認 |
| 路由總數 26 | **錯誤** — 僅計入 employeeController.js，實際 `/employee/*` 前綴下有 52 條，加上 `/employeeRecord/*` 和 `/employeeform/*` 共 87 條 |
| API 路徑前綴 `/employee/*` | **不完整** — 還有 `/employeeRecord/*` 和 `/employeeform/*` |
| 核心 Service 2 | 一致（EmployeeService, EmployeeRecordService） |
| 核心 Model 2 | 一致（Employee, EmployeeLeave） |
| Controllers 6 | 數量一致，但 spec 未列出全部 controller 的路由 |

### 核心功能描述

Spec 的「核心功能」段落以文字方式描述了請假代班、日照打卡、拆帳、員工紀錄等功能，描述內容與原始碼大致吻合。問題在於 **API 端點表格未將這些功能的路由列出**。

### 業務邏輯與 Service 方法

Spec 中的 EmployeeService 和 EmployeeRecordService 方法清單看起來覆蓋了主要方法，與原始碼大致一致。

---

## 問題嚴重度分類

### CRITICAL（必須修正）

1. **API 端點表格嚴重不完整**：僅列出 26/87 條路由（29.9%），遺漏 61 條
2. **路由總數錯誤**：spec 寫 26，實際至少 87
3. **API 路徑前綴不完整**：遺漏 `/employeeRecord/*` 和 `/employeeform/*`

### HIGH（應該修正）

4. **遺漏請假管理路由（16 條）**：這是核心功能，spec 有文字描述但沒列路由
5. **遺漏日照打卡路由（5 條）**：同上
6. **遺漏拆帳路由（5 條）**：同上
7. **遺漏員工紀錄路由（5 條）**：同上
8. **遺漏員工表單路由（30 條）**：有獨立 spec（employeeFormReport.md）但那個 spec 是報表產出，不是 CRUD API。employeeformController 的 30 條 CRUD 路由在任何 spec 中都沒有被列為 API 端點

### MEDIUM（建議修正）

9. **Spec 聲明的範圍模糊**：spec 標題是「員工管理 (Employee)」，但實際涵蓋了 6 個 controller。應明確定義 spec 的覆蓋範圍——是只涵蓋 employeeController.js，還是所有 employee 相關 controller？

---

## 建議

1. 在 API 端點段落新增以下分類：
   - 請假管理（16 條）
   - 日照打卡（5 條）
   - 拆帳管理（5 條）
   - 員工紀錄（5 條，注意前綴是 `/employeeRecord/`）
   - 員工表單（30 條，注意前綴是 `/employeeform/`）
2. 更新總覽表的路由總數和 API 路徑前綴
3. 考慮是否將 `/employeeRecord/*` 和 `/employeeform/*` 拆為獨立 spec，因為它們有不同的 API 前綴
