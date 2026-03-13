# 完整性驗證報告 — caseController.js

## 驗證摘要

| 項目 | 數值 |
|------|------|
| 驗證日期 | 2026-03-11 |
| 原始碼路徑 | `backend/controllers/caseController.js` |
| 檔案總行數 | 1,884 |
| 原始碼 route 總數 | 12 |
| Spec 列出數量 | 12 |
| 完整度 | **100%** |
| 遺漏 | 0 |
| 多餘 | 0 |

## 驗證方法

1. 使用 grep 搜尋所有 `router.route(` / `router.get(` / `router.post(` / `router.put(` / `router.delete(` / `router.patch(` 定義
2. 比對搜尋結果與 spec 列出的 API 端點
3. 逐一確認每個 route 的路徑、HTTP method、綁定的 controller method

## 原始碼 Route 定義（L1870–L1884）

```javascript
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

## 逐筆比對

| # | Route | Method | Controller Method | Method 定義行號 | Spec 涵蓋 | 狀態 |
|---|-------|--------|-------------------|----------------|-----------|------|
| 1 | `/create` | POST | `create` | L165 | V | OK |
| 2 | `/updateBasic` | POST | `updateBasic` | L1049 | V | OK |
| 3 | `/updateContact` | POST | `updateContact` | L1277 | V | OK |
| 4 | `/updateContract` | POST | `updateContract` | L1090 | V | OK |
| 5 | `/profile` | POST | `profile` | L1287 | V | OK |
| 6 | `/delete` | POST | `delete` | L1351 | V | OK |
| 7 | `/transformService` | POST | `transformService` | L1477 | V | OK |
| 8 | `/updateServiceTime` | POST | `updateServiceTime` | L1635 | V | OK |
| 9 | `/autoJudgeAA11` | POST | `autoJudgeAA11` | L1697 | V | OK |
| 10 | `/multiUpdateCase` | POST | `multiUpdateCase` | L1723 | V | OK |
| 11 | `/exportExcel` | POST | `exportExcel` | L1777 | V | OK |
| 12 | `/importExcel` | POST | `importExcel` | L1835 | V | OK |

## 額外觀察：未掛載但存在的方法

以下方法定義在 `CaseControl` 中但**未註冊為 route**，屬於內部輔助方法：

| 方法 | 行號 | 說明 |
|------|------|------|
| `getGeocoder` | L122 | 從地址查詢 GPS 座標（內部使用） |
| `uploadFile` | L1405 | 上傳檔案（被其他 route 呼叫） |
| `removeFile` | L1445 | 移除檔案（被其他 route 呼叫） |

這些方法不是 route handler，不計入 route 總數。

## 結論

Spec 完整涵蓋所有 12 個已註冊的 route，無遺漏、無多餘。
