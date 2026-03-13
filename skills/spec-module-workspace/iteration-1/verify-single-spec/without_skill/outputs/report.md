# Spec 驗證報告：backend/spec/controllers/employee.md

> 驗證日期：2026-03-11
> 驗證方式：比對 spec 文件與原始碼 `router.route()` 定義

---

## 結論

**Spec 嚴重不完整。** 原始碼共有 **82 條 API endpoint**，spec 僅列出 **26 條**（覆蓋率 31.7%）。

---

## 數量比對總覽

| 來源 | Spec 記載 | 原始碼實際 | 差異 |
|------|-----------|-----------|------|
| `/employee/*`（employeeController.js） | 26 | 26 | 0（完全吻合） |
| `/employee/*`（employeeDayCare.js） | 0 | 5 | -5（全部遺漏） |
| `/employee/*`（employeeShare.js） | 0 | 5 | -5（全部遺漏） |
| `/employee/*`（employeeLeave.js） | 0 | 16 | -16（全部遺漏） |
| `/employeeRecord/*`（employeeRecordController.js） | 0 | 5 | -5（全部遺漏） |
| `/employeeform/*`（employeeformController.js） | 0 | 30 | -30（全部遺漏） |
| **合計** | **26** | **87** | **-61** |

> 注意：spec 總覽表中寫「路由總數 26」，這個數字僅對應 employeeController.js 一個檔案，其餘 5 個 controller 的路由完全未記錄。

---

## 詳細比對

### 1. employeeController.js → `/employee/*`（26 條）— Spec 完全覆蓋

| # | 方法 | 路徑 | Spec 有記錄 |
|---|------|------|-------------|
| 1 | POST | `/employee/list` | Yes |
| 2 | POST | `/employee/profile` | Yes |
| 3 | POST | `/employee/create` | Yes |
| 4 | POST | `/employee/update` | Yes |
| 5 | POST | `/employee/delete` | Yes |
| 6 | POST | `/employee/query` | Yes |
| 7 | POST | `/employee/getMasterSupervisorList` | Yes |
| 8 | POST | `/employee/recommend` | Yes |
| 9 | POST | `/employee/recommendFast` | Yes |
| 10 | POST | `/employee/getAvailableList` | Yes |
| 11 | POST | `/employee/additionalSetting/query` | Yes |
| 12 | POST | `/employee/additionalSetting/update` | Yes |
| 13 | POST | `/employee/salary/update` | Yes |
| 14 | POST | `/employee/attendance/list` | Yes |
| 15 | POST | `/employee/attendance/update` | Yes |
| 16 | POST | `/employee/attendance/delete` | Yes |
| 17 | POST | `/employee/agreedPrivacyPolicyHistory` | Yes |
| 18 | POST | `/employee/agreedFeatureTermsOfUse` | Yes |
| 19 | POST | `/employee/multiUpdateEmployee` | Yes |
| 20 | POST | `/employee/changeEmployeeSupervisor` | Yes |
| 21 | POST | `/employee/changeCaseDriverAndDaycaregiver` | Yes |
| 22 | POST | `/employee/calendar/list` | Yes |
| 23 | POST | `/employee/calendar/update` | Yes |
| 24 | POST | `/employee/calendar/delete` | Yes |
| 25 | POST | `/employee/shiftSetting/list` | Yes |
| 26 | POST | `/employee/shiftSetting/update` | Yes |

### 2. employeeDayCare.js → `/employee/*`（5 條）— Spec 全部遺漏

| # | 方法 | 路徑 | Spec 有記錄 |
|---|------|------|-------------|
| 1 | POST | `/employee/shift/dayCare/profile` | **No** |
| 2 | POST | `/employee/shift/dayCare/list` | **No** |
| 3 | POST | `/employee/shift/dayCare/update` | **No** |
| 4 | POST | `/employee/shift/dayCare/delete` | **No** |
| 5 | POST | `/employee/shift/dayCare/calculate` | **No** |

### 3. employeeShare.js → `/employee/*`（5 條）— Spec 全部遺漏

| # | 方法 | 路徑 | Spec 有記錄 |
|---|------|------|-------------|
| 1 | POST | `/employee/share/query` | **No** |
| 2 | POST | `/employee/share/create` | **No** |
| 3 | POST | `/employee/share/update` | **No** |
| 4 | POST | `/employee/share/delete` | **No** |
| 5 | POST | `/employee/share/switch` | **No** |

### 4. employeeLeave.js → `/employee/*`（16 條）— Spec 全部遺漏

| # | 方法 | 路徑 | Spec 有記錄 |
|---|------|------|-------------|
| 1 | POST | `/employee/leave/list` | **No** |
| 2 | POST | `/employee/leave/create` | **No** |
| 3 | POST | `/employee/leave/cancel` | **No** |
| 4 | POST | `/employee/leave/update` | **No** |
| 5 | POST | `/employee/leave/delete` | **No** |
| 6 | POST | `/employee/leave/count` | **No** |
| 7 | POST | `/employee/leave/records` | **No** |
| 8 | POST | `/employee/leave/countRecord` | **No** |
| 9 | POST | `/employee/leave/dayCare/list` | **No** |
| 10 | POST | `/employee/leave/dayCare/upsert` | **No** |
| 11 | POST | `/employee/leave/dayCare/listEmployee` | **No** |
| 12 | POST | `/employee/leave/dayCare/listLeaveDurationSchedule` | **No** |
| 13 | POST | `/employee/leave/dayCare/getSubDriverHasShuttle` | **No** |
| 14 | POST | `/employee/leaveManager/list` | **No** |
| 15 | POST | `/employee/leaveManager/listLeaveDurationShift` | **No** |
| 16 | POST | `/employee/leave/multiReview` | **No** |

### 5. employeeRecordController.js → `/employeeRecord/*`（5 條）— Spec 全部遺漏

| # | 方法 | 路徑 | Spec 有記錄 |
|---|------|------|-------------|
| 1 | POST | `/employeeRecord/create` | **No** |
| 2 | POST | `/employeeRecord/query` | **No** |
| 3 | POST | `/employeeRecord/update` | **No** |
| 4 | POST | `/employeeRecord/delete` | **No** |
| 5 | POST | `/employeeRecord/statistics` | **No** |

### 6. employeeformController.js → `/employeeform/*`（30 條）— Spec 全部遺漏

| # | 方法 | 路徑 | Spec 有記錄 |
|---|------|------|-------------|
| 1 | POST | `/employeeform/pretrain/create` | **No** |
| 2 | POST | `/employeeform/pretrain/list` | **No** |
| 3 | POST | `/employeeform/pretrain/detail` | **No** |
| 4 | POST | `/employeeform/pretrain/update` | **No** |
| 5 | POST | `/employeeform/pretrain/report` | **No** |
| 6 | POST | `/employeeform/pretrain/remove` | **No** |
| 7 | POST | `/employeeform/superpretrain/create` | **No** |
| 8 | POST | `/employeeform/superpretrain/list` | **No** |
| 9 | POST | `/employeeform/superpretrain/detail` | **No** |
| 10 | POST | `/employeeform/superpretrain/update` | **No** |
| 11 | POST | `/employeeform/superpretrain/report` | **No** |
| 12 | POST | `/employeeform/superpretrain/remove` | **No** |
| 13 | POST | `/employeeform/assessment/create` | **No** |
| 14 | POST | `/employeeform/assessment/list` | **No** |
| 15 | POST | `/employeeform/assessment/detail` | **No** |
| 16 | POST | `/employeeform/assessment/update` | **No** |
| 17 | POST | `/employeeform/assessment/report` | **No** |
| 18 | POST | `/employeeform/assessment/remove` | **No** |
| 19 | POST | `/employeeform/supervise/create` | **No** |
| 20 | POST | `/employeeform/supervise/list` | **No** |
| 21 | POST | `/employeeform/supervise/detail` | **No** |
| 22 | POST | `/employeeform/supervise/update` | **No** |
| 23 | POST | `/employeeform/supervise/report` | **No** |
| 24 | POST | `/employeeform/supervise/remove` | **No** |
| 25 | POST | `/employeeform/seniorSupervise/create` | **No** |
| 26 | POST | `/employeeform/seniorSupervise/list` | **No** |
| 27 | POST | `/employeeform/seniorSupervise/detail` | **No** |
| 28 | POST | `/employeeform/seniorSupervise/update` | **No** |
| 29 | POST | `/employeeform/seniorSupervise/report` | **No** |
| 30 | POST | `/employeeform/seniorSupervise/remove` | **No** |

---

## Spec 內部一致性檢查

| 項目 | Spec 宣稱 | 實際驗證 | 一致？ |
|------|-----------|----------|--------|
| 檔案數 | 60 | 未完整計算（僅驗證 controller 層） | — |
| 路由總數 | 26 | 87（含所有 employee 相關 controller） | **不一致**（僅計算了 employeeController.js） |
| Controllers 數量 | 6 | 6（employeeController、employeeDayCare、employeeShare、employeeLeave、employeeRecordController、employeeformController） | 一致 |
| API 路徑前綴 | `/employee/*` | `/employee/*`、`/employeeRecord/*`、`/employeeform/*` | **不完整** |

---

## 問題摘要

1. **API 端點嚴重不足**：spec 僅記錄了 employeeController.js 的 26 條路由，其餘 5 個 controller 共 61 條路由完全未記錄
2. **路徑前綴不完整**：spec 總覽僅標示 `/employee/*`，遺漏了 `/employeeRecord/*` 和 `/employeeform/*`
3. **路由總數錯誤**：宣稱 26 條，實際應為 87 條
4. **業務邏輯記錄不對稱**：spec 的「核心功能」和「業務邏輯」章節有提及請假、拆帳、紀錄管理等功能的 Service 方法，但對應的 API endpoint 卻未在「API 端點」章節列出

---

## 驗證方法

1. 讀取 spec 文件 `backend/spec/controllers/employee.md`
2. 透過 `routes/index.js` 確認路由映射規則（`CONTROLLER_ROUTING_MAPPING`）
3. 在 6 個相關 controller 檔案中搜尋 `router.route()` 呼叫，提取所有已註冊的 API endpoint
4. 逐條比對 spec 記載與原始碼實際定義
