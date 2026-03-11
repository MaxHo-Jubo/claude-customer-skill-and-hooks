---
name: spec-module
description: "對指定模組進行完整探索，產出結構化 spec markdown 文件。當使用者提到 /spec-module、想產出模組文件、想建立 spec、或說「幫我寫這個模組的 spec」時使用此 skill。"
---

# Spec Module 文件產生

對指定模組進行完整探索，產出結構化 spec markdown 文件。

## 使用方式

- `/spec-module <模組路徑>` — 探索模組並產出 spec（快速模式，不逐一讀完所有原始碼）
- `/spec-module <模組路徑> --full` — 強制完整掃描，逐一讀取所有 route/method 定義，確保 API 列表 100% 完整
- `/spec-module <模組路徑> --verify` — 驗證已存在的 spec 完整性，比對原始碼找出遺漏並補上
- `/spec-module <模組路徑> --commit` — 完成後自動 commit（可與 `--full` / `--verify` 組合）

範例：
- `/spec-module react_15/case`
- `/spec-module react_18/src/pages/report --commit`
- `/spec-module backend/controllers/employeeController.js --full`
- `/spec-module backend/spec/controllers/employee.md --verify`
- `/spec-module backend/spec/controllers/ --verify` — 批次驗證目錄下所有 spec

## 執行步驟

### Phase 1: 探索（使用 subagent）

1. 用 Explore subagent 對目標目錄進行完整掃描：
   - 列出所有檔案，統計數量與行數
   - 識別檔案類型（元件、工具函式、樣式、設定檔等）
   - 偵測框架特徵（React Class/Functional、Redux connect/hooks、Router 等）
   - 識別跨模組引用與外部依賴

2. subagent 回傳結構化資料：
   - 檔案清單（路徑、行數、類型）
   - 層級關係（元件樹、呼叫鏈）
   - 外部依賴（Redux、API、第三方函式庫）
   - 疑似死程式碼

3. **`--full` 模式額外步驟（強制完整掃描）：**
   - **後端 controller**：
     1. 先讀 `routes/index.js` 的路由映射表，找出目標 controller 對應的所有相關 controller 檔案
     2. 對每個相關 controller 用 grep 搜尋所有 `router.route(` / `router.get(` / `router.post(` 等 route 定義，逐一列出
     3. 產出的 spec 必須包含「完整性驗證」section，記錄：原始碼 route 總數 vs spec 列出數量
   - **前端元件**：讀取所有 export 的元件和 hooks，列出完整 props interface
   - **禁止**只掃檔案結構就跳到 Phase 2，必須讀到 route/method 層級

### Phase 1.5: 驗證模式（`--verify` 專用）

當指定 `--verify` 時，跳過 Phase 1 的一般探索，改為：

1. **定位 spec 與原始碼的對應關係：**
   - 如果傳入的是 spec 檔案路徑（如 `backend/spec/controllers/employee.md`），讀取 spec 內容，從中找出對應的原始碼檔案
   - 如果傳入的是 spec 目錄（如 `backend/spec/controllers/`），對目錄下每個 spec 檔案逐一執行驗證
   - **對應規則（按優先序）：**
     1. **路由映射表**（最精確）：讀取 `routes/index.js`（或專案的路由註冊檔），找到 `CONTROLLER_ROUTING_MAPPING` 或類似的路由映射定義，從中建立「路由前綴 → controller 檔案」的完整對應關係
     2. **Spec 內部標註**：如果 spec 檔案中已標註對應的原始碼路徑，以此為準
     3. **檔名推斷**（fallback）：`spec/controllers/X.md` → `controllers/XController.js`
   - **關鍵**：一個 spec 可能對應多個 controller（例如 `employee.md` 對應 `employeeController.js` + `employeeDayCare.js` + `employeeShare.js` + `employeeLeave.js` + `employeeformController.js` + `employeeRecordController.js`）。必須透過路由映射表找出所有共用相同路由前綴的 controller，不能只靠檔名推斷

2. **從原始碼提取完整 API 清單：**
   - 對 Step 1 找到的**所有**對應 controller 檔案，用 grep 搜尋所有 `router.route(` / `router.get(` / `router.post(` / `router.put(` / `router.delete(` / `router.patch(` 定義
   - 記錄每個 route 的：路徑、HTTP method、綁定的 controller method、來源檔案

3. **比對 spec 與原始碼：**
   - spec 列出但原始碼沒有的 → 標記為「已移除？」
   - 原始碼有但 spec 沒列的 → 標記為「遺漏」
   - 產出比對報告表格

4. **補完 spec：**
   - 如果有遺漏的 API，讀取對應的 controller method 實作，提取參數資訊
   - 將遺漏的 API 補入 spec 的對應 section
   - 不覆蓋已有的正確內容，只追加遺漏的部分

5. **在 spec 末尾更新驗證紀錄：**
   ```markdown
   ## 完整性驗證
   - 驗證日期：YYYY-MM-DD
   - 原始碼 route 總數：N
   - Spec 列出數量：N
   - 完整度：100%
   ```

6. **批次模式輸出摘要：**
   ```
   ✅ employee.md — 26/26 (100%)
   ⚠️ case.md — 18/22 (82%) — 補了 4 個遺漏 API
   ✅ fee.md — 17/17 (100%)
   ```

### Phase 2: 撰寫 Spec

> `--verify` 模式在 Phase 1.5 完成後直接跳到 Phase 3 收尾。

3. 根據探索結果，撰寫 spec markdown 檔案：
   - 模組 spec：`spec/<module-name>/index.md` 或 `spec/<module-name>.md`
   - 子系統 spec：`spec/<module-name>/<subsystem>.md`
   - 如果目標路徑已有 spec 檔案，更新而不是覆蓋

4. Spec 檔案結構（根據模組特性選用適合的 section）：

   **通用必要 section：**
   ```markdown
   ## 規模
   檔案數、總行數、語言分布

   ## 入口架構
   主要入口檔案的結構、export、routing

   ## 檔案一覽
   表格或列表，含檔案路徑、行數、類型、用途

   ## 品質觀察
   技術債、死程式碼、過度耦合、命名問題等
   ```

   **前端模組額外 section（視情況加入）：**
   ```markdown
   ## 元件層級
   元件樹結構與 props 傳遞

   ## 狀態管理
   Redux / Context / 本地 state 的使用方式

   ## 路由
   頁面路由對應
   ```

   **Reducer / Store 模組額外 section：**
   ```markdown
   ## State 結構
   ## Action 分類
   ## 關鍵業務邏輯
   ```

   **後端模組額外 section（視情況加入）：**
   ```markdown
   ## API 端點
   路由、方法、參數

   ## 資料模型
   Schema 或 Model 結構

   ## 中介層
   Middleware / Guard / Interceptor
   ```

### Phase 3: 收尾

5. 如果帶 `--commit` 參數：
   - 調用 `/commit-spec` 的邏輯（stage + commit）

6. 檢查 `spec/file-mapping.json` 是否需要更新：
   - 提醒執行 `node ~/.claude/scripts/generate-spec-mapping.cjs <project-root>`

7. 報告摘要：
   - 掃描了多少檔案
   - 產出了哪些 spec 檔案
   - 關鍵發現（死程式碼數量、技術債等）

## Spec 撰寫規範

- 語言：繁體中文
- 用詞：「元件」而非「組件」，「屬性」而非「道具」
- 程式碼引用：用 backtick 包裹，如 `CaseContent.js`
- 檔案路徑：相對於模組根目錄
- 行數統計：實測數值，不要估算
- 表格：超過 5 個同類項目用表格呈現，否則用列表

## 注意事項

- 探索階段用 subagent 保持主 context 乾淨
- 不要在探索階段花超過 40% 的 effort，剩下給撰寫（`--full` 模式例外，可花 60%）
- 如果模組超過 200 檔，拆成多個子系統 spec
- 已有的 spec 只更新，不覆蓋（先讀取現有內容再決定改動）
- Spec section 不是死板模板——根據模組實際特性選用，沒有 Redux 就不寫 Redux section

### 模式選擇指引

| 模式 | 適用場景 | Token 消耗 |
|------|---------|-----------|
| 預設（無參數） | 快速產出概覽 spec，掌握模組結構 | 低 |
| `--full` | 新模組首次建 spec，需要 100% API 完整度 | 高 |
| `--verify` | 已有 spec，想確認是否有遺漏並補完 | 中（只讀 route 定義，不讀全部原始碼） |
| `--verify --full` | 已有 spec，要連參數細節一起驗證補完 | 高 |
