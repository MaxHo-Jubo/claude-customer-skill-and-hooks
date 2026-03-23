---
name: test-module
description: "對指定模組掃描可測試函式並產出單元測試。當使用者提到 /test-module、「幫這個寫測試」、「批量產生測試」時觸發。"
version: 2.0.0
---

# Test Module 測試產生

對指定模組掃描可測試函式，產出單元測試，經 4 輪平行 review 迭代至零問題後執行測試驗證。

框架無關 — 適用 Jest、Vitest、Mocha、flutter_test、pytest、go test 等。核心流程一致，差異僅在測試語法與 mock 機制。

## 使用方式

- `/test-module <檔案或目錄路徑>` — 完整測試流程
- `/test-module <路徑> --plan-only` — 只產出測試計畫，不寫測試
- `/test-module <路徑> --phase <N>` — 執行指定 phase

範例：
- `/test-module lib/services/session_service.dart`
- `/test-module react_18/src/shared/utils/serviceRecordUtil.js`
- `/test-module react_15/case/components/service/ --plan-only`

## 執行步驟

### Phase 0: 偵察

1. 用 Explore subagent 分析目標：
   - 列出所有 export 的函式/方法
   - 分類：pure function / stateful / side-effect / DOM-dependent
   - 識別依賴：外部模組、Redux store、API call、DOM 操作、DB 操作
   - 判斷可測試性（pure > stateful > side-effect > DOM/IO）

2. 偵測專案測試框架：
   - 檢查 `package.json` / `pubspec.yaml` / `go.mod` 的 test dependencies
   - 檢查現有測試檔案的 import 風格
   - 檢查 jest.config / vitest.config / analysis_options 等設定檔
   - 沿用專案既有的測試框架與慣例

3. 產出測試計畫（到 `tasks/todo.md` 或直接報告）：
   - 按可測試性分群
   - 每群列出要測試的函式和預計 test case 數量
   - 優先測試 pure functions 和 utility methods
   - 跳過需要複雜 mock 的 IO 操作（但記錄為 skip）
   - 識別每個函式的分支路徑數量（if/else/switch/try-catch）

4. 如果帶 `--plan-only`，到這裡結束，等使用者確認

### Phase 1: 撰寫測試

5. 依測試計畫逐一撰寫測試：
   - 測試檔案位置：遵循專案現有慣例（`__tests__/` 或同層 `*.test.js` 或 `test/`）
   - 每個函式至少 3 個 test case（正常、邊界、異常）
   - 使用專案的共用測試常數（如果有）
   - 加上中文註解說明每個 test case 的目的

6. 測試撰寫原則：

   **結構**：
   - 每個函式/方法對應一個 `describe`/`group`
   - 正常路徑 → 邊界案例 → 錯誤路徑，依序排列
   - AAA pattern：Arrange → Act → Assert

   **Mock 原則**：
   - Mock 只用在外部依賴（DB、API、file system、notification）
   - 不 mock 被測函式的內部邏輯
   - Mock 行為必須反映真實依賴的合約（型別、回傳值、例外）
   - 驗證 mock 被呼叫的次數和參數（不只驗回傳值）

   **斷言原則**：
   - 驗回傳值的具體內容，不只驗型別或 truthy
   - 驗副作用（DB 呼叫、狀態變更、事件觸發）
   - 驗例外的型別和訊息，不只驗「有拋例外」
   - 禁止空斷言（test body 沒有 expect/assert）

   **邊界案例必測清單**：
   - null / undefined / 空字串 / 空陣列 / 空物件
   - 負數、0、極大值
   - 重複呼叫、concurrent 呼叫
   - 型別邊界（int overflow、float precision）

7. 執行測試確認全數通過

### Phase 2: 平行 Review（4 個 subagent）

撰寫完成後，**同時**啟動 4 個 review subagent，每個專注一個面向。

#### Agent 1: 覆蓋率

```
比對源碼與測試，檢查分支覆蓋：
- 列出源碼中每個 if/else/switch/try-catch 分支
- 對每個分支標記是否有 test case 覆蓋
- 標記：✅ 已覆蓋 / ❌ 未覆蓋
- 計算分支覆蓋率
- 特別注意：error path（catch block）是否被測試
```

#### Agent 2: Mock 正確性

```
讀取測試和被 mock 的依賴源碼，檢查：
1. Mock 的回傳值型別是否與真實依賴一致
2. Mock 是否遺漏了真實依賴會拋出的例外
3. Mock 的行為是否過度簡化（例如真實依賴有 side effect 但 mock 忽略）
4. 是否有不該 mock 的東西被 mock 了（例如純函式、constants）
5. mock.verify / expect(mock).toHaveBeenCalled 是否驗證了呼叫次數和參數
標記嚴重度：🔴 mock 行為與真實不符 🟡 mock 過度簡化 🟢 建議改善
```

#### Agent 3: 斷言精確度

```
檢查每個 test case 的斷言：
1. 是否有空斷言（test body 沒有 expect/assert）
2. 是否只驗型別不驗值（expect(result).toBeInstanceOf(X) 但不驗內容）
3. 是否用了過度寬鬆的 matcher（toBeTruthy / toBeDefined 但應該用 toEqual）
4. 副作用是否被驗證（DB mock 被呼叫幾次、傳了什麼參數）
5. 錯誤路徑是否驗了錯誤型別和訊息
6. 非同步操作是否正確 await / expectAsync
給出精確度評分（1-10）
```

#### Agent 4: 邊界案例

```
對每個被測函式，列出重要的邊界案例：
- null / undefined / 空值輸入
- 極端數值（0、負數、MAX_INT、NaN、Infinity）
- 空集合 / 單元素集合 / 超大集合
- 特殊字元（emoji、Unicode、超長字串）
- concurrent / 重複呼叫
- 時間相關（跨日、跨時區、過去/未來）

對每個邊界案例標記：
- ✅ 已測
- ❌ 遺漏（標明嚴重度：高/中/低）
```

### Phase 3: 迭代修正

1. **彙整 4 份 review** → 統一報告：
   - 🔴 問題數量
   - 🟡 問題數量
   - 分支覆蓋率 %
   - 斷言精確度評分

2. **修正所有 🔴 問題**，盡量修 🟡

3. **重新啟動 4 個 review subagent**

4. **重複直到 🔴 = 0**

5. **迭代完成條件**：
   - 🔴 = 0
   - 分支覆蓋率 ≥ 80%

### Phase 4: 執行驗證

1. **執行測試套件**，確認全數通過
2. **執行 coverage 報告**（如果框架支援）：
   - 目標：被測試函式 80%+ branch coverage
   - 如果 coverage 不足，針對未覆蓋的分支補寫 test case
3. **若有失敗**，依原因分類：
   - 測試寫錯 → 改測試
   - 程式碼有 bug → 獨立 commit：`fix: <描述>（unit test 發現）`

### Phase 5: 最終報告

產出結構化報告並**寫入檔案**（`test/reports/<模組名>_report.md`）：

```markdown
# Unit Test 報告：<模組名>

- 日期：YYYY-MM-DD
- 源碼路徑：<被測檔案路徑>
- 測試路徑：<測試檔案路徑>

## 數據
- 被測函式: X 個
- Test Cases: Y 個
- 分支覆蓋率: XX%
- 斷言精確度: X/10
- Review 迭代次數: N 輪

## 函式覆蓋明細
| 函式 | Test Cases | 分支覆蓋 | 備註 |
|------|-----------|---------|------|

## 被 Skip 的函式（如有）
| 函式 | 原因 |
|------|------|

## 發現的 Bug（如有）
| Bug | 修正 | Commit |
|-----|------|--------|

## 建議後續
- ...
```

Commit 測試檔案（遵循 CLAUDE.md commit 規則）：
- message 格式：`test(專案標識): 新增 <模組名稱> 單元測試`

## 注意事項

- Pure function 優先，不要浪費時間 mock 複雜外部依賴
- 如果模組超過 30 個可測試函式，分成多個 phase 並在每個 phase 結束時 commit
- 測試命名用英文，註解用繁體中文
- 不要在測試中使用 `console.log` / `print`
- 使用專案既有的 mock 模式和測試工具，不要引入新的測試依賴
- 測試不應依賴執行順序 — 每個 test case 必須獨立
- 不 mock 被測函式本身的邏輯（只 mock 外部依賴）

## 框架適配

| 概念 | Jest/Vitest | flutter_test | pytest | go test |
|------|-------------|-------------|--------|---------|
| 分組 | `describe` | `group` | class | func Test |
| 測試 | `it`/`test` | `test` | `def test_` | `func Test` |
| 斷言 | `expect().toBe()` | `expect(x, y)` | `assert` | `assert/require` |
| Mock | `jest.fn()`/`vi.fn()` | `MockClient` | `unittest.mock` | interface |
| 覆蓋率 | `--coverage` | `--coverage` | `--cov` | `-cover` |

進入 Phase 1 前，先偵測專案使用的框架和測試工具。
