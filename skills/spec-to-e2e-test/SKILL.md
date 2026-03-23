---
name: spec-to-e2e-test
description: "從 spec 文件產出 E2E 整合測試。當使用者提到 /spec-to-e2e-test、「spec 轉測試」、「從 spec 寫 E2E」、「寫整合測試」、「E2E test case」、想從規格文件產生端對端測試時觸發。"
version: 1.2.0
---

# Spec to E2E Test

從結構化 spec 文件產出 E2E 整合測試，經 4 輪平行 review 迭代至零問題後執行測試驗證。

框架無關 — 適用 Flutter integration_test、React Testing Library、Playwright、Cypress 等。核心流程一致，差異僅在測試語法與 widget/element finder。

## 使用方式

- `/spec-to-e2e-test <spec路徑或模組名>` — 完整流程（偵察→撰寫→review→迭代→執行）
- `/spec-to-e2e-test` — 無參數時自動掃描專案中的 spec 目錄，列出可用模組
- `/spec-to-e2e-test --scan` — 執行全 spec 跨模組依賴掃描（建議首次使用時先跑）

範例：
- `/spec-to-e2e-test exercise-library`
- `/spec-to-e2e-test openspec/specs/session-management/spec.md`
- `/spec-to-e2e-test spec/client-management.md --with spec/package-management.md`

## 執行步驟

### Phase -1: 跨模組依賴掃描（首次或多模組批次作業時必做）

**觸發條件**：首次對專案執行 E2E 測試、或一次要處理多個模組時。若已有依賴圖且未新增 spec，可跳過。

**目的**：在寫任何測試之前，先建立全域的 scenario 依賴圖，避免寫到一半才發現某個 scenario 需要其他模組的資料，也避免跨模組 scenario 被遺漏。

**步驟**：

1. **掃描所有 spec**：讀取 spec 目錄下所有模組的 spec 檔案
2. **對每個 spec 的每個 scenario，判斷**：
   - **獨立**：該 scenario 只涉及本模組的實體和操作，可在本模組 E2E 中獨立完成
   - **依賴其他模組**：需要其他模組的資料作為前置條件（例如「刪除學員 → 取消未來課程」需要先有 session）
   - **被其他模組依賴**：本模組的實體是其他模組 scenario 的前置條件
3. **產出依賴圖**：

```
## E2E 跨模組依賴圖

### 依賴方向（A 依賴 B = 測試 A 的某些 scenario 需要 B 的資料）

| Scenario | 所屬模組 | 依賴模組 | 依賴內容 | 建議測試位置 |
|----------|---------|---------|---------|------------|
| Delete cascade → cancel sessions | client | session | 需先建立 session 資料 | session 模組 E2E |
| ... | ... | ... | ... | ... |

### 建議執行順序（依賴少→依賴多）
1. ...
2. ...

### 不可測 Scenario（需系統層級互動）
| Scenario | 原因 | 替代方案 |
|----------|------|---------|
| ... | ... | ... |
```

4. **將依賴圖存為檔案**（例如 `integration_test/DEPENDENCY_MAP.md`），後續每個模組的 Phase 0 和 Phase 2 review 都要參照
5. **跨模組 scenario 的處理原則**：
   - 標記為「延後」，記錄在依賴圖中，不在當前模組硬寫
   - 等依賴模組的 E2E 完成時，在該模組的測試中一併補上
   - Spec 覆蓋率 review 時，延後的 scenario 標記為 `⏳ 延後（等 XX 模組）`，與 `❌ 未覆蓋` 區分

### Phase 0: Spec 定位與偵察

1. **定位 spec 檔案**：
   - 有給路徑 → 直接使用
   - 給模組名 → 在 `openspec/specs/`、`spec/`、`docs/specs/` 中搜尋
   - 無參數 → 掃描上述目錄，列出所有可用模組讓使用者選擇

2. **讀取 spec 並分析**：
   - 列出所有 Requirement 和 Scenario
   - 統計總 scenario 數量（後續計算覆蓋率的分母）
   - 識別跨模組引用：掃描 spec 中是否提到其他模組的概念或實體
   - 若有跨模組引用 → 列出建議一併讀取的 spec，詢問使用者確認範圍

3. **探索 UI 程式碼**：
   - 用 Explore subagent 分析 spec 對應的畫面程式碼
   - 產出 **Widget/Element Finder 參考表**，包含：
     - 畫面層級結構（哪個 Screen 包含哪些 Widget/Component）
     - 文字標籤（按鈕文字、輸入框 label、提示訊息）
     - 圖示識別碼（Icon 類型、aria-label）
     - 導航流程（畫面間如何跳轉）
     - 可能的多重匹配陷阱（IndexedStack、Tab 重複文字、overlay）
   - 這張參考表是寫測試的基礎，必須在 Phase 1 之前完成

4. **評估複雜度**：
   - 向使用者報告：scenario 數量、涉及幾個畫面、預估 test case 數量
   - 評估剩餘 token 是否足夠完成完整流程

### Phase 1: 撰寫測試

基於 spec scenario 和 UI 探索結果撰寫 E2E 測試檔案。

#### 撰寫原則

**結構**：
- 每個 Requirement 對應一個 `group`
- 相關的 scenario 合併或拆分為 `testWidgets`/`test`
- CRUD 類操作合併為單一流程測試（新增→驗證→編輯→驗證→刪除→驗證），避免跨測試狀態依賴

**Finder 選擇（按優先序）**：
- `find.byKey` / `data-testid` > `find.widgetWithText(WidgetType, text)` > `find.byType` > `find.text`
- 避免裸用 `find.text` — 容易匹配多個 widget（TabBar + NavigationBar 同名、Dropdown overlay 複製）
- Dropdown overlay 選取：封裝為輔助方法，加 assert 確認選項存在
- 搜尋欄 finder：不用 hintText（輸入文字後消失），用 `byType` 或 `byKey`

**斷言強度**：
- 禁止 `findsWidgets` 搭配無意義的存在性檢查 — 至少驗數量或具體內容
- `lessThanOrEqualTo` 改用 `lessThan`（等於代表功能沒效果也通過）
- 數量比較：記錄操作前數量，操作後驗 delta（例如收藏 +1）

**穩定性**：
- 每個 `enterText` 後加 `pumpAndSettle`（或等價的 wait）
- 避免在 CRUD 流程中混入驗證錯誤測試（表單狀態干擾）— 拆為獨立 test case
- 不使用 `if` guard 靜默跳過 — 找不到 widget 必須 fail，不能假通過

**清理**：
- 每個建立測試資料的 test case 自行清理
- 測試名稱前綴用 `E2E測試_` 或 `E2E_TEST_` 區分測試資料

**共用輔助方法**：
- 導航到目標頁面
- 常用操作封裝（Dropdown 選取、表單填寫、刪除確認）

### Phase 2: 平行 Review（4 個 subagent）

撰寫完成後，**同時**啟動 4 個 review subagent，每個專注一個面向。

#### Agent 1: Spec 覆蓋率

```
比對 spec 與測試檔案，逐一列出每個 Scenario 的覆蓋狀態：
- ✅ 已覆蓋（對應測試名稱）
- ⚠️ 部分覆蓋（缺什麼）
- ⏳ 延後（需 XX 模組資料，已記錄在依賴圖中）
- ❌ 未覆蓋
覆蓋率計算：✅=1, ⚠️=0.5, ⏳=不計入分母, ❌=0
同時檢查：依賴圖中標記為「延後」的 scenario 是否確實無法在本模組獨立測試。
若有 scenario 被錯誤標記為延後（實際上可以獨立測試），標記為 🔴。
```

#### Agent 2: 語法正確性

```
讀取測試檔案和被測的 UI 程式碼，檢查：
1. Widget finder 文字/類型是否與 UI 一致
2. 操作順序是否合理（是否需要先滾動、等待）
3. API 呼叫是否正確（pumpAndSettle、enterText、click 等）
4. import 是否完整
5. find.text 是否可能匹配多個 widget（IndexedStack、overlay）
6. Dropdown/Select overlay 的處理方式
標記嚴重度：🔴 會失敗 🟡 不穩定 🟢 建議改善
```

#### Agent 3: 測試品質

```
檢查：
1. 重複測試：有無驗證相同邏輯的測試
2. 斷言品質：expect 是否精確（非 findsWidgets 混過去）
3. 測試命名：是否描述行為與預期結果
4. 測試獨立性：有無 if guard 靜默跳過、跨測試狀態依賴
5. 邊界案例：重要遺漏
給出品質評分（1-10）。
```

#### Agent 4: 穩定性（Flakiness）

```
專注檢查會導致測試不穩定的問題：
1. Widget finder 脆弱性（.last、byType 多重匹配、hintText 消失）
2. 時序問題（缺 pumpAndSettle/waitFor、動畫未完成、async 操作）
3. 資料隔離（跨測試殘留、DB 清理、file-based vs in-memory）
4. 平台差異（IndexedStack 預建構、overlay 行為、響應式佈局）
5. 表單狀態干擾（驗證錯誤後的 re-validate、focus 切換）
標記嚴重度：🔴 必定不穩 🟡 偶發 🟢 建議改善
```

### Phase 3: 迭代修正

1. **彙整 4 份 review** → 統一報告：
   - 🔴 問題數量
   - 🟡 問題數量
   - Spec 覆蓋率 %
   - 品質評分

2. **修正所有 🔴 問題**，盡量修 🟡

3. **重新啟動 4 個 review subagent**

4. **重複直到 🔴 = 0**：
   - 若某個 🔴 問題經過 2 輪迭代仍無法解決：
     - 在測試檔案中將該 test case 加上 `skip` 註解
     - 在 test case 上方加文件說明原因
     - 繼續迭代其餘問題
   - 每輪迭代向使用者報告進度（v1 → v2 → v3 的改善趨勢）

5. **迭代完成條件**：
   - 🔴 = 0（含已 skip 並記錄的）
   - 向使用者報告最終狀態：通過數 / skip 數 / 覆蓋率 / 品質評分

### Phase 4: 執行測試

1. **執行測試套件**，記錄結果

2. **若有失敗**，依原因分類處理：

   | 失敗原因 | 改什麼 | commit 方式 |
   |----------|--------|------------|
   | 測試寫錯（finder 錯誤、缺 pumpAndSettle、斷言邏輯錯誤） | 改測試 | 歸入測試 commit，不另外分 commit |
   | 測試環境問題（overlay 多重匹配、IndexedStack 干擾） | 改測試 | 同上 |
   | 程式碼有 bug（行為與 spec 定義不符） | 改程式碼 | 獨立 commit：`fix: <描述>（E2E 測試發現）` |
   | Spec 與實作不一致（spec 定義的行為實作沒做到） | 改程式碼對齊 spec | 獨立 commit：`fix: <描述>（對齊 spec 定義）` |

   - Spec 是 source of truth — 測試是 spec 的翻譯，程式碼是被測對象
   - 程式碼 bug 和 spec 不一致的修正必須各自獨立 commit，不可與測試修正混在一起
   - 修正後重跑測試驗證

3. **若修正後仍失敗且原因無法在合理時間內解決**：
   - 加 `skip` 註解 + 原因說明
   - 記錄到最終報告

4. **全部通過後**：
   - 向使用者報告最終結果
   - 列出被 skip 的 test case 及原因（如有）
   - 等待使用者指示是否 commit

### Phase 5: 最終報告

產出結構化報告並**寫入檔案**，供後續查詢與追蹤。

**檔案路徑**：`integration_test/reports/<模組名>_report.md`

**報告內容**：

```markdown
# E2E 測試報告：<模組名>

- 日期：YYYY-MM-DD
- Spec 路徑：<spec 檔案路徑>
- 測試路徑：<測試檔案路徑>

## 數據
- Spec Scenarios: X 個
- Test Cases: Y 個（Z 個 skip）
- Spec 覆蓋率: XX%（有效覆蓋率 YY%，排除跨模組延後 scenario）
- 品質評分: X/10
- Review 迭代次數: N 輪

## Scenario 覆蓋明細
| Scenario | 狀態 | 對應測試 | 備註 |
|----------|------|---------|------|
| ... | ✅/⚠️/⏳/❌ | ... | ... |

## 被 Skip 的測試（如有）
| Test Case | 原因 | 相關 Spec Scenario |
|-----------|------|-------------------|

## 延後的跨模組 Scenario（如有）
| Scenario | 依賴模組 | 建議測試位置 |
|----------|---------|------------|

## 執行中修正的問題
| 問題 | 修正方式 |
|------|---------|

## 已知限制
- ...

## 建議後續
- ...
```

**報告用途**：
- 後續模組開發時，查詢已完成模組的覆蓋狀態
- 從「延後的跨模組 Scenario」撈出待補的測試
- 追蹤各模組的品質評分趨勢
- commit 前確認報告已更新

## 跨功能 Spec 處理

### 全域依賴掃描（Phase -1）

批次作業前必須先做 Phase -1 掃描。掃描結果存為 `integration_test/DEPENDENCY_MAP.md`，後續每個模組都參照。

### 單一模組中遇到跨模組 scenario

1. **自動偵測**：Phase 0 讀 spec 時掃描是否引用其他模組的實體名稱或概念
2. **手動指定**：`--with <其他spec路徑>` 參數
3. **判斷能否獨立測試**：
   - 能獨立 → 在本模組測試中完成（可能需要 setup helper 建立前置資料）
   - 不能獨立（依賴模組尚未有 E2E 測試 / setup helper） → 標記為 `⏳ 延後`
4. **延後 scenario 的追蹤**：
   - 記錄在 `integration_test/DEPENDENCY_MAP.md` 的依賴圖中
   - 標明：scenario 名稱、所屬模組、依賴模組、建議測試位置
   - 實作依賴模組的 E2E 時，從依賴圖撈出所有「建議在此模組測試」的延後 scenario 一併處理
   - 處理完畢後更新依賴圖狀態為 ✅
5. **可獨立的跨模組測試**：
   - 讀取所有相關模組的 spec
   - Explore subagent 分析所有相關畫面的 UI 程式碼
   - 測試可能需要跨多個畫面操作（先建立客戶 → 再建立課程包 → 再建立課程）
   - setup 輔助方法封裝前置資料建立

## 框架適配

本 skill 的撰寫原則和踩坑經驗目前以 **Flutter integration_test** 為主。核心流程（偵察→撰寫→4 agent review→迭代→執行）適用於所有框架，但具體語法、finder 策略、穩定性陷阱因框架而異。

**當偵測到非 Flutter 專案時**，必須在 Phase 0 結束前提醒使用者：

> ⚠️ 本 skill 的撰寫原則與已知陷阱目前以 Flutter 為主。偵測到本專案使用 [框架名稱]，以下內容需要調整：
> - Finder 策略（Flutter 的 `find.byType` / `find.widgetWithText` → 該框架的等價方式）
> - 等待機制（Flutter 的 `pumpAndSettle` → 該框架的等價方式）
> - 穩定性陷阱（IndexedStack、Dropdown overlay 等為 Flutter 特有，需替換為該框架的已知陷阱）
> - 建議先更新本 skill 的框架適配內容後再繼續（version bump）

以下為快速對照表供參考，但不足以取代各框架的深入適配：

| 概念 | Flutter | React (Testing Library) | Playwright | Cypress |
|------|---------|------------------------|------------|---------|
| 測試函式 | `testWidgets` | `test` / `it` | `test` | `it` |
| 元素尋找 | `find.byType` | `screen.getByRole` | `page.locator` | `cy.get` |
| 點擊 | `tester.tap` | `fireEvent.click` | `locator.click` | `.click` |
| 輸入文字 | `tester.enterText` | `fireEvent.change` | `locator.fill` | `.type` |
| 等待 | `pumpAndSettle` | `waitFor` | auto-wait | auto-wait |
| 斷言 | `expect(finder, matcher)` | `expect(element).toBe` | `expect(locator).toBe` | `.should` |

進入 Phase 1 前，先偵測專案使用的框架和測試工具。若為 Flutter 則直接使用本 skill 的完整指引；若為其他框架則顯示上述提醒後繼續。
