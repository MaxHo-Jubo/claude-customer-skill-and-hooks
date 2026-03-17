---
name: spec-module
description: "對指定模組探索並產出結構化 spec markdown。當使用者提到 /spec-module、「寫 spec」、「模組文件」、想建立 spec 時觸發。"
version: 1.0.0
---

# Spec Module 文件產生

對指定模組進行完整探索，產出結構化 spec markdown 文件。

## 使用方式

- `/spec-module <模組路徑>` — 探索模組並產出 spec（讀取基本架構與每個函式，不深入研究業務邏輯，保證正確性與完整性）
- `/spec-module <模組路徑> --full` — 深度分析模式，除了基本架構與函式外，深入研究業務邏輯、演算法、資料流，產出包含關鍵演算法與設計模式的完整 spec
- `/spec-module <模組路徑> --verify` — 比對既有 spec 與原始碼，報告差異並補完有變更的地方
- `/spec-module <模組路徑> --commit` — 完成後自動 commit（可與 `--full` / `--verify` 組合）

範例：
- `/spec-module react_15/case`
- `/spec-module react_18/src/pages/report --commit`
- `/spec-module backend/controllers/employeeController.js --full`
- `/spec-module backend/spec/controllers/employee.md --verify`
- `/spec-module backend/spec/controllers/ --verify` — 批次驗證目錄下所有 spec
- `/spec-module backend/spec/controllers/employee.md --verify --commit` — 驗證補完後自動 commit

## 執行步驟

### Phase 1: 探索（使用 subagent）

1. 用 subagent 對目標目錄進行完整掃描：
   - 列出所有檔案，統計數量與行數
   - 識別檔案類型（元件、工具函式、樣式、設定檔等）
   - 偵測框架特徵（React Class/Functional、Redux connect/hooks、Router 等）
   - 識別跨模組引用與外部依賴

2. **必須讀取每個函式定義**（預設模式與 `--full` 模式皆須）：
   - **後端 controller**：找出目標模組對應的所有 controller 檔案，搜尋所有 route 定義，讀取每個 export 的函式/方法簽名、參數、用途
   - **前端元件**：讀取所有 export 的元件和 hooks，列出完整 props interface
   - **工具函式庫**（非 HTTP controller）：讀取所有 export 的函式簽名與用途
   - **禁止**只掃檔案結構就跳到 Phase 2，必須讀到函式層級

3. **預設模式 vs `--full` 模式的差異：**
   - **預設模式**：讀取函式簽名與參數，從命名和結構推斷用途，**不逐行分析業務邏輯和演算法**
   - **`--full` 模式**：逐行閱讀關鍵函式的實作，分析演算法邏輯、資料流、邊界條件、設計模式

4. **正確性保證**（兩種模式皆須）：
   - Spec 中列出的每個 route/函式必須在原始碼中有對應，不得猜測或編造
   - 原始碼中的每個 route/export 函式必須出現在 spec 中，不得遺漏
   - 行數、檔案數等數值必須實測，不得估算

### Phase 1.5: 驗證模式（`--verify` 專用）

當指定 `--verify` 時，跳過 Phase 1 的一般探索，改為通用驗證流程（適用任何模組類型）：

1. **讀取既有 spec，提取記錄的所有項目：**
   - 檔案清單（檔案一覽 section）
   - 函式/方法清單（API 端點、export 函式、元件、hooks 等）
   - 行數、規模等數值
   - 如果傳入的是 spec 目錄，對目錄下每個 spec 檔案逐一執行驗證

2. **定位對應的原始碼：**
   - **Spec 內部標註**（優先）：如果 spec 中已標註對應的原始碼路徑，以此為準
   - **檔名推斷**（fallback）：從 spec 檔名與路徑推斷目標原始碼目錄

3. **掃描原始碼，提取實際存在的項目：**
   - 掃描目標目錄的所有檔案
   - 提取所有 export 函式/元件/hooks/route 定義
   - 記錄檔案行數等數值

4. **雙向比對，產出差異報告：**
   - spec 有但原始碼沒有 → 標記為「已移除？」
   - 原始碼有但 spec 沒有 → 標記為「遺漏」
   - 數值不一致（行數、檔案數變動） → 標記為「過時」
   - 產出比對報告表格

5. **補完有變更的地方：**
   - 移除 spec 中已不存在的項目（或標註已移除）
   - 將遺漏的項目補入 spec 的對應 section
   - 更新過時的數值（行數、檔案數等）
   - 不覆蓋已有的正確內容

6. **`--verify --full` 額外行為：**
   - 不只補差異，而是完整重新掃描所有函式/元件的簽名與用途
   - 等同於以既有 spec 為基礎，重建完整 spec 內容
   - 適用於 spec 嚴重過時或需要全面更新的場景

7. **在 spec 末尾更新驗證紀錄：**
   ```markdown
   ## 完整性驗證
   - 驗證日期：YYYY-MM-DD
   - 原始碼項目總數：N
   - Spec 列出數量：N
   - 完整度：100%
   ```

8. **批次模式輸出摘要：**
   ```
   ✅ employee.md — 26/26 (100%)
   ⚠️ case.md — 18/22 → 22/22 — 補了 4 個遺漏
   🔄 utils.md — 更新 3 個過時項目
   ❌ deprecated.md — 原始碼已移除，建議刪除此 spec
   ```

### Phase 2: 撰寫 Spec

> `--verify` 模式在 Phase 1.5 完成後直接跳到 Phase 3 收尾。`--verify --full` 模式則在 Phase 1.5 完成完整重建後跳到 Phase 3。

1. 根據探索結果，撰寫 spec markdown 檔案：
   - 模組 spec：`spec/<module-name>/index.md` 或 `spec/<module-name>.md`
   - 子系統 spec：`spec/<module-name>/<subsystem>.md`
   - 如果目標路徑已有 spec 檔案，更新而不是覆蓋

2. **預設模式撰寫原則：**
   - 每個函式/方法都必須出現在 spec 中（函式名、參數、一句話用途說明）
   - 每個 route 都必須列出（路徑、HTTP method、handler）
   - **不寫**：演算法步驟、資料流分析、邊界條件、設計模式解析
   - **不寫**：業務邏輯的「為什麼」，只寫「是什麼」和「做什麼」
   - 用途說明從函式名稱、參數名稱、JSDoc 推斷，不深入閱讀實作

3. **`--full` 模式額外撰寫內容：**
   - 關鍵演算法的步驟拆解
   - 資料流與狀態變化分析
   - 設計模式識別
   - 業務邏輯的詳細描述（含邊界條件與特殊處理）
   - 依賴矩陣（哪個 controller 用哪個 model/service）

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
   ## 關鍵業務邏輯（僅 --full 模式）
   ```

   **後端模組額外 section（視情況加入）：**
   ```markdown
   ## API 端點
   路由、方法、參數

   ## 資料模型
   Schema 或 Model 結構

   ## 中介層
   Middleware / Guard / Interceptor

   ## 關鍵演算法（僅 --full 模式）
   ## 依賴矩陣（僅 --full 模式）
   ```

### Phase 3: 收尾

1. 如果帶 `--commit` 參數：
   - `git add` 所有新增/修改的 spec 檔案
   - commit message 格式：`docs: spec-module 產出 <模組名稱> spec`
   - 如果是 `--verify` 模式：`docs: spec-module 驗證補完 <模組名稱> spec`

2. 檢查 `spec/file-mapping.json` 是否需要更新：
   - 提醒執行 `node ~/.claude/scripts/generate-spec-mapping.cjs <project-root>`

3. 報告摘要：
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
- 預設模式：探索 50%、撰寫 50%（需讀完所有函式簽名，但不深入實作）
- `--full` 模式：探索 60%、撰寫 40%（需逐行閱讀關鍵實作）
- 如果模組超過 200 檔，拆成多個子系統 spec
- 已有的 spec 只更新，不覆蓋（先讀取現有內容再決定改動）
- Spec section 不是死板模板——根據模組實際特性選用，沒有 Redux 就不寫 Redux section

### 模式選擇指引

| 模式 | 適用場景 | Token 消耗 |
|------|---------|-----------|
| 預設（無參數） | 完整架構 + 所有函式簽名，保證正確性與完整性 | 中 |
| `--full` | 深度分析業務邏輯、演算法、資料流、設計模式 | 高 |
| `--verify` | 已有 spec，比對原始碼差異並補完變更 | 中 |
| `--verify --full` | 已有 spec，完整重新掃描補完（等同重建） | 高 |
