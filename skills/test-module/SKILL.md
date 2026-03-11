---
name: test-module
description: "對指定模組掃描可測試函式，產出單元測試並驗證品質。當使用者提到 /test-module、想為某個模組寫測試、說「幫這個寫測試」、或想批量產生測試時使用此 skill。"
---

# Test Module 測試產生

對指定模組掃描可測試函式，產出單元測試並驗證品質。

## 使用方式

- `/test-module <檔案或目錄路徑>` — 完整測試流程
- `/test-module <路徑> --plan-only` — 只產出測試計畫，不寫測試
- `/test-module <路徑> --phase <N>` — 執行指定 phase

範例：
- `/test-module react_18/src/shared/utils/serviceRecordUtil.js`
- `/test-module react_15/case/components/service/ --plan-only`

## 執行步驟

### Phase 0: 偵察

1. 用 Explore subagent 分析目標：
   - 列出所有 export 的函式/方法
   - 分類：pure function / stateful / side-effect / DOM-dependent
   - 識別依賴：外部模組、Redux store、API call、DOM 操作
   - 判斷可測試性（pure > stateful > side-effect > DOM）

2. 偵測專案測試框架：
   - 檢查 `package.json` 的 devDependencies（jest / vitest / mocha 等）
   - 檢查現有測試檔案的 import 風格
   - 檢查 jest.config / vitest.config 等設定檔
   - 沿用專案既有的測試框架與慣例

3. 產出測試計畫（到 `tasks/todo.md` 或直接報告）：
   - 按可測試性分群
   - 每群列出要測試的函式和預計 test case 數量
   - 優先測試 pure functions 和 utility methods
   - 跳過需要複雜 mock 的 MongoDB/Express/DOM 操作

4. 如果帶 `--plan-only`，到這裡結束，等使用者確認

### Phase 1: 撰寫測試

5. 依測試計畫逐一撰寫測試：
   - 測試檔案位置：遵循專案現有慣例（`__tests__/` 或同層 `*.test.js`）
   - 每個函式至少 3 個 test case（正常、邊界、異常）
   - 使用專案的共用測試常數（如果有 `__tests__/constants.js`）
   - 加上中文 JSDoc 註解說明每個 test case 的目的

6. 測試檔案格式：
   ```javascript
   /**
    * @file <模組名稱> 單元測試
    * @description 測試 <模組> 的 <功能描述>
    */

   describe('<函式名稱>', () => {
     /** 正常情境：<描述> */
     it('should <expected behavior>', () => {
       // ...
     });

     /** 邊界情境：<描述> */
     it('should handle <edge case>', () => {
       // ...
     });

     /** 異常情境：<描述> */
     it('should throw/return <error case>', () => {
       // ...
     });
   });
   ```

7. 執行測試確認全數通過：
   ```bash
   npx jest <test-file> --verbose
   ```
   （若專案使用其他測試框架，用對應的執行指令）

### Phase 2: 品質驗證

8. 執行 coverage 報告：
   ```bash
   npx jest <test-file> --coverage --verbose
   ```

9. 檢視 coverage 結果：
   - 目標：被測試函式 80%+ branch coverage
   - 如果 coverage 不足，針對未覆蓋的分支補寫 test case
   - 特別注意 error path 和邊界條件

### Phase 3: 收尾

10. 報告摘要：
    - 測試了幾個函式、幾個 test case
    - Coverage 百分比
    - 跳過的函式及原因

11. Commit 測試檔案（遵循 CLAUDE.md commit 規則）：
    - message 格式：`test(專案標識): 新增 <模組名稱> 單元測試`

## 注意事項

- Pure function 優先，不要浪費時間 mock 複雜外部依賴
- 如果模組超過 30 個可測試函式，分成多個 phase 並在每個 phase 結束時 commit
- 測試命名用英文，JSDoc 註解用繁體中文
- 不要在測試中使用 `console.log`
- 使用專案既有的 mock 模式和測試工具，不要引入新的測試依賴
