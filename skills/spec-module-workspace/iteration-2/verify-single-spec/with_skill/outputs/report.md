# 驗證報告 — backend/spec/controllers/employee.md

> 驗證日期：2026-03-11

## 1. Controller 對應關係

透過 `routes/index.js` 的 `CONTROLLER_ROUTING_MAPPING` 建立完整對應：

### 路由前綴 `/employee`（4 個 Controller）

| Controller 檔案 | 路由映射方式 | 說明 |
|-----------------|-------------|------|
| `controllers/employeeController.js` | 預設（`fname.replace('Controller','')` → `employee`） | 主要 API controller |
| `controllers/employeeDayCare.js` | 映射表 `employeeDayCare: 'employee'` | 照服員管理（日照打卡） |
| `controllers/employeeShare.js` | 映射表 `employeeShare: 'employee'` | 員工拆帳 |
| `controllers/employeeLeave.js` | 映射表 `employeeLeave: 'employee'` | 員工請假 |

### 路由前綴非 `/employee`（2 個 Controller，獨立路由）

| Controller 檔案 | 實際路由前綴 | 說明 |
|-----------------|-------------|------|
| `controllers/employeeformController.js` | `/employeeform` | 員工表單管理（不在映射表，走預設邏輯） |
| `controllers/employeeRecordController.js` | `/employeeRecord` | 員工紀錄管理（不在映射表，走預設邏輯） |

---

## 2. 原始碼完整 Route 清單

### `/employee` 前綴（共 52 條 route）

#### employeeController.js — 26 條

| # | 方法 | 路徑 | Controller Method |
|---|------|------|-------------------|
| 1 | POST | `/employee/list` | `ctr.list` |
| 2 | POST | `/employee/profile` | `ctr.profile` |
| 3 | POST | `/employee/create` | `ctr.create` |
| 4 | POST | `/employee/update` | `ctr.update` |
| 5 | POST | `/employee/delete` | `ctr.delete` |
| 6 | POST | `/employee/query` | `ctr.query` |
| 7 | POST | `/employee/getMasterSupervisorList` | `ctr.getMasterSupervisorList` |
| 8 | POST | `/employee/recommend` | `ctr.recommend` |
| 9 | POST | `/employee/recommendFast` | `ctr.recommendFast` |
| 10 | POST | `/employee/getAvailableList` | `ctr.getAvailableList` |
| 11 | POST | `/employee/additionalSetting/query` | `ctr.additionalSettingQuery` |
| 12 | POST | `/employee/additionalSetting/update` | `ctr.additionalSettingUpdate` |
| 13 | POST | `/employee/salary/update` | `ctr.updateSalary` |
| 14 | POST | `/employee/attendance/list` | `ctr.listEmployeeAttendance` |
| 15 | POST | `/employee/attendance/update` | `ctr.updateEmployeeAttendance` |
| 16 | POST | `/employee/attendance/delete` | `ctr.deleteEmployeeAttendance` |
| 17 | POST | `/employee/agreedPrivacyPolicyHistory` | `ctr.agreedPrivacyPolicyHistory` |
| 18 | POST | `/employee/agreedFeatureTermsOfUse` | `ctr.agreedFeatureTermsOfUse` |
| 19 | POST | `/employee/multiUpdateEmployee` | `ctr.multiUpdateEmployee` |
| 20 | POST | `/employee/changeEmployeeSupervisor` | `ctr.changeEmployeeSupervisor` |
| 21 | POST | `/employee/changeCaseDriverAndDaycaregiver` | `ctr.changeCaseDriverAndDaycaregiver` |
| 22 | POST | `/employee/calendar/list` | `ctr.listEmployeeCalendar` |
| 23 | POST | `/employee/calendar/update` | `ctr.updateEmployeeCalendar` |
| 24 | POST | `/employee/calendar/delete` | `ctr.deleteEmployeeCalendar` |
| 25 | POST | `/employee/shiftSetting/list` | `ctr.listShiftSetting` |
| 26 | POST | `/employee/shiftSetting/update` | `ctr.updateShiftSetting` |

#### employeeDayCare.js — 5 條

| # | 方法 | 路徑 | Controller Method |
|---|------|------|-------------------|
| 27 | POST | `/employee/shift/dayCare/profile` | `ctr.profileEmployeeShiftDayCare` |
| 28 | POST | `/employee/shift/dayCare/list` | `ctr.listEmployeeShiftDayCare` |
| 29 | POST | `/employee/shift/dayCare/update` | `ctr.updateEmployeeShiftDayCare` |
| 30 | POST | `/employee/shift/dayCare/delete` | `ctr.deleteEmployeeShiftDayCare` |
| 31 | POST | `/employee/shift/dayCare/calculate` | `ctr.calculateEmployeeShiftDayCare` |

#### employeeShare.js — 5 條

| # | 方法 | 路徑 | Controller Method |
|---|------|------|-------------------|
| 32 | POST | `/employee/share/query` | `ctr.shareQuery` |
| 33 | POST | `/employee/share/create` | `ctr.shareCreate` |
| 34 | POST | `/employee/share/update` | `ctr.shareUpdate` |
| 35 | POST | `/employee/share/delete` | `ctr.shareDelete` |
| 36 | POST | `/employee/share/switch` | `ctr.shareSwitch` |

#### employeeLeave.js — 16 條

| # | 方法 | 路徑 | Controller Method |
|---|------|------|-------------------|
| 37 | POST | `/employee/leave/list` | `ctr.leaveList` |
| 38 | POST | `/employee/leave/create` | `ctr.leaveCreate` |
| 39 | POST | `/employee/leave/cancel` | `ctr.leaveCancel` |
| 40 | POST | `/employee/leave/update` | `ctr.leaveUpdate` |
| 41 | POST | `/employee/leave/delete` | `ctr.leaveDelete` |
| 42 | POST | `/employee/leave/count` | `ctr.leaveCount` |
| 43 | POST | `/employee/leave/records` | `ctr.leaveRecordsV3` |
| 44 | POST | `/employee/leave/countRecord` | `ctr.leaveRecordCount` |
| 45 | POST | `/employee/leave/dayCare/list` | `ctr.listLeaveDayCare` |
| 46 | POST | `/employee/leave/dayCare/upsert` | `ctr.upsertLeaveDayCare` |
| 47 | POST | `/employee/leave/dayCare/listEmployee` | `ctr.listLeaveEmployee` |
| 48 | POST | `/employee/leave/dayCare/listLeaveDurationSchedule` | `ctr.listLeaveDurationSchedule` |
| 49 | POST | `/employee/leave/dayCare/getSubDriverHasShuttle` | `ctr.getSubDriverHasShuttle` |
| 50 | POST | `/employee/leaveManager/list` | `ctr.leaveList` |
| 51 | POST | `/employee/leaveManager/listLeaveDurationShift` | `ctr.listLeaveDurationShift` |
| 52 | POST | `/employee/leave/multiReview` | `ctr.leaveMultiReview` |

### `/employeeform` 前綴（共 30 條 route）— 獨立路由，不在 `/employee` 下

| # | 方法 | 路徑 | Controller Method |
|---|------|------|-------------------|
| 1 | POST | `/employeeform/pretrain/create` | `employeeFormPreTrain.create` |
| 2 | POST | `/employeeform/pretrain/list` | `employeeFormPreTrain.list` |
| 3 | POST | `/employeeform/pretrain/detail` | `employeeFormPreTrain.detail` |
| 4 | POST | `/employeeform/pretrain/update` | `employeeFormPreTrain.update` |
| 5 | POST | `/employeeform/pretrain/report` | `employeeFormPreTrain.report` |
| 6 | POST | `/employeeform/pretrain/remove` | `employeeFormPreTrain.remove` |
| 7 | POST | `/employeeform/superpretrain/create` | `employeeFormSuperPretrain.create` |
| 8 | POST | `/employeeform/superpretrain/list` | `employeeFormSuperPretrain.list` |
| 9 | POST | `/employeeform/superpretrain/detail` | `employeeFormSuperPretrain.detail` |
| 10 | POST | `/employeeform/superpretrain/update` | `employeeFormSuperPretrain.update` |
| 11 | POST | `/employeeform/superpretrain/report` | `employeeFormSuperPretrain.report` |
| 12 | POST | `/employeeform/superpretrain/remove` | `employeeFormSuperPretrain.remove` |
| 13 | POST | `/employeeform/assessment/create` | `employeeFormAssessment.create` |
| 14 | POST | `/employeeform/assessment/list` | `employeeFormAssessment.list` |
| 15 | POST | `/employeeform/assessment/detail` | `employeeFormAssessment.detail` |
| 16 | POST | `/employeeform/assessment/update` | `employeeFormAssessment.update` |
| 17 | POST | `/employeeform/assessment/report` | `employeeFormAssessment.reportAssess` |
| 18 | POST | `/employeeform/assessment/remove` | `employeeFormAssessment.remove` |
| 19 | POST | `/employeeform/supervise/create` | `employeeFormSupervise.create` |
| 20 | POST | `/employeeform/supervise/list` | `employeeFormSupervise.list` |
| 21 | POST | `/employeeform/supervise/detail` | `employeeFormSupervise.detail` |
| 22 | POST | `/employeeform/supervise/update` | `employeeFormSupervise.update` |
| 23 | POST | `/employeeform/supervise/report` | `employeeFormSupervise.downloadSupervise` |
| 24 | POST | `/employeeform/supervise/remove` | `employeeFormSupervise.remove` |
| 25 | POST | `/employeeform/seniorSupervise/create` | `employeeFormSeniorSupervise.create` |
| 26 | POST | `/employeeform/seniorSupervise/list` | `employeeFormSeniorSupervise.list` |
| 27 | POST | `/employeeform/seniorSupervise/detail` | `employeeFormSeniorSupervise.detail` |
| 28 | POST | `/employeeform/seniorSupervise/update` | `employeeFormSeniorSupervise.update` |
| 29 | POST | `/employeeform/seniorSupervise/report` | `employeeFormSeniorSupervise.downloadSupervise` |
| 30 | POST | `/employeeform/seniorSupervise/remove` | `employeeFormSeniorSupervise.remove` |

### `/employeeRecord` 前綴（共 5 條 route）— 獨立路由，不在 `/employee` 下

| # | 方法 | 路徑 | Controller Method |
|---|------|------|-------------------|
| 1 | POST | `/employeeRecord/create` | `ctr.create` |
| 2 | POST | `/employeeRecord/query` | `ctr.query` |
| 3 | POST | `/employeeRecord/update` | `ctr.update` |
| 4 | POST | `/employeeRecord/delete` | `ctr.delete` |
| 5 | POST | `/employeeRecord/statistics` | `ctr.statistics` |

---

## 3. Spec vs 原始碼比對

### Spec 聲稱的範圍

- API 路徑前綴：`/employee/*`
- 路由總數：26
- Controllers：6（含 employeeformController、employeeRecordController）

### 實際發現

| 範圍 | 原始碼 Route 數 | Spec 列出數 | 差異 |
|------|----------------|-------------|------|
| `/employee` 前綴（4 個 controller） | **52** | **26** | **-26（遺漏）** |
| `/employeeform` 前綴 | 30 | 0（spec 未列 API） | spec 視為同模組但未列 route |
| `/employeeRecord` 前綴 | 5 | 0（spec 未列 API） | spec 視為同模組但未列 route |
| **合計** | **87** | **26** | — |

### 3.1 Spec 有列出、原始碼也有（26 條）— 全部正確

Spec 列出的 26 條 route 全部來自 `employeeController.js`，與原始碼完全吻合。

### 3.2 原始碼有但 Spec 遺漏（26 條，同前綴 `/employee`）

#### 來自 employeeDayCare.js（5 條）

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/employee/shift/dayCare/profile` | 查詢日照照服員打卡資料 |
| POST | `/employee/shift/dayCare/list` | 日照照服員打卡列表 |
| POST | `/employee/shift/dayCare/update` | 更新日照照服員打卡時間 |
| POST | `/employee/shift/dayCare/delete` | 刪除日照照服員打卡時間 |
| POST | `/employee/shift/dayCare/calculate` | 統計日照照服員打卡 |

#### 來自 employeeShare.js（5 條）

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/employee/share/query` | 查詢拆帳設定 |
| POST | `/employee/share/create` | 建立拆帳設定 |
| POST | `/employee/share/update` | 更新拆帳設定 |
| POST | `/employee/share/delete` | 刪除拆帳設定 |
| POST | `/employee/share/switch` | 切換拆帳設定 |

#### 來自 employeeLeave.js（16 條）

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/employee/leave/list` | 請假列表 |
| POST | `/employee/leave/create` | 建立請假 |
| POST | `/employee/leave/cancel` | 銷假 |
| POST | `/employee/leave/update` | 更新請假 |
| POST | `/employee/leave/delete` | 刪除請假 |
| POST | `/employee/leave/count` | 請假統計 |
| POST | `/employee/leave/records` | 請假紀錄（V3） |
| POST | `/employee/leave/countRecord` | 請假紀錄統計 |
| POST | `/employee/leave/dayCare/list` | 日照請假列表 |
| POST | `/employee/leave/dayCare/upsert` | 日照請假新增/更新 |
| POST | `/employee/leave/dayCare/listEmployee` | 日照請假員工列表 |
| POST | `/employee/leave/dayCare/listLeaveDurationSchedule` | 日照請假區間排班 |
| POST | `/employee/leave/dayCare/getSubDriverHasShuttle` | 代理司機排班查詢 |
| POST | `/employee/leaveManager/list` | 請假管理列表 |
| POST | `/employee/leaveManager/listLeaveDurationShift` | 請假區間班表 |
| POST | `/employee/leave/multiReview` | 批次審核請假 |

### 3.3 Spec 有列但原始碼沒有（0 條）

無。Spec 列出的 26 條全部存在於原始碼。

### 3.4 獨立路由前綴（Spec 提及但未列 Route）

Spec 在「主要檔案」表格中列出了 `employeeformController.js`（517 行）和 `employeeRecordController.js`（329 行），並在核心功能、業務邏輯、依賴矩陣中描述了它們的功能，但 **API 端點 section 完全未列出這兩個 controller 的 route**。

由於這兩個 controller 的路由前綴分別為 `/employeeform` 和 `/employeeRecord`（不是 `/employee`），嚴格來說不屬於 `/employee/*` 前綴範圍。但 spec 既然已將它們視為同一模組的一部分來描述，建議在 API 端點 section 中也補充列出。

---

## 4. 問題摘要

### 問題 A：Spec 總覽數據不正確

- Spec 聲稱「路由總數：26」，但同一 `/employee` 前綴下實際有 **52** 條 route
- 原因：Spec 只統計了 `employeeController.js` 的 route，遺漏了透過 `CONTROLLER_ROUTING_MAPPING` 映射到同一前綴的 3 個 controller（`employeeDayCare.js`、`employeeShare.js`、`employeeLeave.js`）

### 問題 B：API 端點 section 缺少 3 個 controller 的 route

遺漏的 route 按來源：

| Controller | 遺漏數 |
|-----------|--------|
| `employeeDayCare.js` | 5 |
| `employeeShare.js` | 5 |
| `employeeLeave.js` | 16 |
| **小計** | **26** |

### 問題 C：`employeeformController.js` 與 `employeeRecordController.js` 的 route 未列出

雖然這兩個 controller 的路由前綴不同（`/employeeform`、`/employeeRecord`），Spec 在其他 section 中已將它們視為同模組。建議在 API 端點 section 新增獨立子區塊列出其 route（共 35 條）。

---

## 5. 完整性驗證

### `/employee` 前綴（核心範圍）

| 指標 | 數值 |
|------|------|
| 原始碼 route 總數 | 52 |
| Spec 列出數量 | 26 |
| 完整度 | **50%** |
| 遺漏來源 | employeeDayCare(5) + employeeShare(5) + employeeLeave(16) |

### 全模組（含獨立路由前綴）

| 指標 | 數值 |
|------|------|
| 原始碼 route 總數 | 87 |
| Spec 列出數量 | 26 |
| 完整度 | **30%** |
| 遺漏來源 | employeeDayCare(5) + employeeShare(5) + employeeLeave(16) + employeeform(30) + employeeRecord(5) |

---

## 6. 建議修正

1. **API 端點 section**：補充 employeeDayCare、employeeShare、employeeLeave 的 route（+26 條），這些共用 `/employee` 前綴，屬於核心範圍
2. **總覽路由總數**：從 26 更正為 52（或 87 含獨立前綴）
3. **新增子 section**：為 `/employeeform` 和 `/employeeRecord` 各建立獨立 API 端點區塊
4. **Spec 總覽的 Controllers 數量**：已正確標示 6 個
