---
name: spec-design
description: "從需求到設計 spec 的結構化流程：brainstorming → openspec 撰寫 → 4-agent review → 迭代修正。當使用者提到 /spec-design、「設計新功能」、「寫設計 spec」、「brainstorm 新功能」、「需求探索」、「新功能架構設計」、「技術方案討論」、「寫 RFC」、想從零開始設計一個功能或系統時觸發。不適用於：讀原始碼產 spec（用 spec-module）、重構既有程式碼、寫測試、bug fix。"
version: 3.1.0
---

# Spec Design — 需求探索到設計 spec + 實作計畫

從模糊需求出發，先用 openspec explore 自由探索問題空間，再透過 `superpowers:brainstorming` 結構化收斂，以 openspec 撰寫 spec 並經 4 輪平行 review，最後用 plan mode 產出實作計畫並經 4-agent plan review。所有互動式討論在此 skill 完成，產出物可直接交給 `plan-and-execute` 自動執行。

**前置條件**：
- superpowers plugin 必須安裝且啟用
- `@fission-ai/openspec` CLI 必須已全域安裝（`npm install -g @fission-ai/openspec`）

## 使用方式

- `/spec-design` — 互動式需求探索
- `/spec-design <需求描述>` — 帶初始需求直接開始

## 流程概覽

```
Phase 0: openspec explore（自由探索問題空間）
    ↓
Phase 1-4: superpowers:brainstorming（結構化收斂：需求釐清 + 方案比較 + 設計確認）
    ↓
Phase 5: 偵測 openspec → 建立 change → 用 brainstorming 結果填入 artifact
    ↓
Phase 6: 4-agent spec review
    ↓
Phase 7: spec 迭代修正（直到 🔴 = 0）
    ↓
Phase 8: plan mode 互動式規劃（產出 plan.md）
    ↓
Phase 9: 4-agent plan review + 迭代修正
    ↓
Phase 10: 使用者最終確認 + 轉入下一步
```

## Phase 0: Explore（openspec explore）

以 openspec explore 模式自由探索問題空間。這是 thinking partner，不是工作流。

**進入方式**：調用 openspec-explore skill（若專案已 init）或直接以 explore 姿態對話。

**做什麼**：
- 問問題、挑戰假設、重新定義問題
- 讀 codebase 了解現有架構（grounded，不空談）
- 畫 ASCII 圖視覺化（系統圖、狀態機、資料流、比較表）
- 比較方案、發散思考、跟隨有價值的切線
- 若專案已有 openspec change，讀取既有 artifact 作為探索上下文

**不做什麼**：
- 不寫程式碼、不實作功能
- 不走固定流程、不強制產出
- 不急著收斂（那是 brainstorming 的工作）

**結束時機**：
- 使用者說「夠了」「可以開始了」「進入 brainstorming」
- 問題空間已充分理解，自然過渡到 Phase 1
- 可選：摘要探索結果（問題定義、初步方向、開放問題）

**跳過條件**：使用者帶著明確需求直接來（如 `/spec-design 新增使用者匯出功能`），可跳過 Phase 0 直接進 Phase 1。

## Phase 1-4: Brainstorming

調用 `superpowers:brainstorming` skill，完成：
- 專案 context 探索
- 需求釐清（互動式對話）
- 方案比較與推薦
- 設計呈現與確認

Phase 0 的探索結果作為 brainstorming 的輸入上下文。brainstorming 結束後，取得已確認的設計內容，進入 Phase 5。

## Phase 5: 撰寫 openspec

將 brainstorming 產出轉寫為 openspec change。

### 5.1 偵測 openspec 環境

```
檢查專案根目錄是否有 openspec/ 目錄：
  有 → 跳到 5.2
  無 → 執行 openspec init --tools claude → 產生 openspec/ 目錄 + .claude/commands/opsx/ + .claude/skills/openspec-*/
```

### 5.2 建立 change

從 brainstorming 的功能名稱衍生 kebab-case 名稱。

```bash
openspec new change "<change-name>"
```

### 5.3 取得 artifact 建構順序

```bash
openspec status --change "<change-name>" --json
```

解析 JSON 取得：
- `applyRequires`：實作前須完成的 artifact ID 列表
- `artifacts`：所有 artifact 的狀態與依賴關係

### 5.4 依序填入 artifact

按依賴順序（無依賴的先做），對每個 artifact：

1. **取得 template 與指令**：
   ```bash
   openspec instructions <artifact-id> --change "<change-name>" --json
   ```
   JSON 回傳：
   - `template`：artifact 的結構模板（用這個當輸出骨架）
   - `instruction`：schema 對此 artifact 的撰寫指引
   - `context`：專案背景（作為撰寫約束，不寫入檔案）
   - `rules`：artifact 規則（作為撰寫約束，不寫入檔案）
   - `outputPath`：寫入路徑
   - `dependencies`：前置 artifact，讀取作為上下文

2. **用 brainstorming 結果填入 template**：
   - 讀取已完成的前置 artifact 作為上下文
   - 以 `template` 為骨架，從 brainstorming 確認的設計內容提取對應段落填入
   - `context` 和 `rules` 是撰寫約束，**不可**複製進檔案內容

3. **寫入檔案**，顯示進度：「Created \<artifact-id\>」

4. **重新檢查狀態**：
   ```bash
   openspec status --change "<change-name>" --json
   ```
   確認該 artifact 為 `done`，繼續下一個，直到 `applyRequires` 全部完成。

### 5.5 驗證結構

```bash
openspec validate --changes
```

### 5.6 Commit

寫完後詢問使用者是否要 commit：
> openspec change 已寫入 `openspec/changes/<change-name>/`。要先 commit 嗎？（Y/N）

使用者確認後才執行 `git add` + `git commit`。

## Phase 6: Spec Review（4 個平行 Opus Subagent）

撰寫完成後，使用 Agent tool **同時**啟動 4 個 review subagent（`model: "opus"`）。

**調用方式**：
- 使用 Agent tool 平行啟動 4 個 subagent，每個 subagent 的 prompt 包含 change 目錄路徑
- 每個 subagent 自行讀取 change 目錄下的所有 artifact（proposal.md、specs/、design.md、tasks.md）
- 等待 4 個 subagent 全部完成後，彙整結果進入 Phase 7

#### Agent 1: 完整性 + 一致性

```
讀取 change 目錄下所有 artifact，檢查：
1. 是否有 TODO / TBD / placeholder / 未完成區段
2. proposal、spec、design 之間是否矛盾（例如 proposal 說 sync，design 說 async）
3. 名詞/數字在不同 artifact 間是否一致
4. 資料流是否有缺口（spec 定義的需求 design 沒有對應方案）
5. 每個 requirement 是否都有 scenario
6. tasks.md 是否涵蓋 design 中所有決策

標記嚴重度：🔴 會導致 plan 出錯 🟡 模糊但可能不影響 🟢 建議改善
```

#### Agent 2: 可實作性

```
讀取 change 目錄和專案既有架構（目錄結構、相關模組、技術棧），檢查：
1. 每個 requirement + scenario 是否清楚到能直接寫 plan（不用回頭問使用者）
2. 技術方案是否可行（API 存在嗎、套件能裝嗎、平台支援嗎）
3. 每個 scenario 是否能寫成測試（可測試性）
4. tasks.md 的工作量是否合理（有沒有隱藏的複雜度）
5. 依賴的外部服務 / 第三方套件是否明確

標記嚴重度：🔴 無法實作或需求不明確 🟡 可實作但有風險 🟢 建議改善
```

#### Agent 3: 邊界與風險

```
讀取 change 目錄，檢查：
1. 邊界情況是否涵蓋（null / 空值 / 併發 / 極端值 / 斷網）
2. 向後相容性（會破壞既有功能嗎）
3. 跨模組影響（資料結構改動影響哪些現有模組）
4. 資料 migration 是否有處理（schema 變更時既有資料怎麼辦）
5. 安全性（權限、資料外洩、注入）

標記嚴重度：🔴 會導致既有功能壞掉或資料遺失 🟡 邊界未處理 🟢 建議改善
```

#### Agent 4: 範圍與品味

```
讀取 change 目錄，檢查：
1. YAGNI — 有沒有沒人要求的功能混進來
2. Scope — 是否聚焦到單一 plan 可處理（沒有混入多個獨立子系統）
3. 資料結構設計是否消除邊界情況（而非用 if 處理）
4. 抽象是否適當（不過度封裝、不過度簡化）
5. 與既有 codebase pattern 是否一致

標記嚴重度：🔴 scope 失控或設計反模式 🟡 可精簡 🟢 建議改善
```

## Phase 7: 迭代修正

1. **彙整 4 份 review** → 統一報告：
   - 🔴 問題數量
   - 🟡 問題數量
   - 各 agent 的重點發現
   - 若不同 agent 的建議互相矛盾，由 orchestrator 判斷優先順序（完整性 > 可實作性 > 邊界風險 > 品味）

2. **修正所有 🔴 問題**，盡量修 🟡

3. **重新啟動 4 個 review subagent**（針對完整 change 目錄重跑，因為局部修正可能引入新問題）

4. **重複直到 🔴 = 0**（最多 3 輪，超過則向使用者報告剩餘問題，由使用者判斷是否接受）

5. **殘留 🟡 處理**：迭代結束後仍有 🟡 的，記錄到 design.md 的「Open Questions」區段

6. **驗證格式**：`npx @fission-ai/openspec validate --changes`

## Phase 8: Plan Mode 互動式規劃

spec review 通過後，進入 plan mode 產出實作計畫。

### 8.1 進入 plan mode

以 openspec change 的 artifacts 為輸入，產出包含以下結構的實作計畫：

**File Structure Map**：
- 列出所有將建立或修改的檔案及其職責
- 每個檔案一個職責，偏好小而聚焦的檔案
- 既有 codebase 優先 follow existing pattern

**拆 Wave**：
- 依據依賴關係將 tasks 分組為 Wave
- Wave 1 處理基礎層（DB / model / provider）
- 後續 Wave 依序往上疊加（service → UI → integration）
- 同一 Wave 內的 tasks 盡量獨立
- openspec tasks.md 的分組作為 Wave 劃分的參考骨架

**拆 Task**（每 task 2-5 分鐘粒度）：

每個 Task 包含：
```markdown
### Task N: [Component Name]

**Wave:** N
**Model:** haiku | sonnet | opus（依複雜度）
**openspec task:** 對應 tasks.md 的 checkbox 項目
**Files:**
- Create: `exact/path/to/file`
- Modify: `exact/path/to/existing:line-range`
- Test: `tests/exact/path/to/test`

- [ ] **Step 1: 寫 failing test**
（完整測試程式碼）

- [ ] **Step 2: 跑測試確認 FAIL**
Run: `<exact command>`
Expected: FAIL with "<expected error>"

- [ ] **Step 3: 寫最小實作**
（完整實作程式碼）

- [ ] **Step 4: 跑測試確認 PASS**
Run: `<exact command>`
Expected: PASS

- [ ] **Step 5: Commit + 更新 openspec tasks.md**
```

**Model 分級標註**：
- 1-2 檔 + 明確 spec → `haiku`（機械式實作）
- 多檔整合 + pattern matching → `sonnet`（標準實作）
- 架構判斷 + 跨模組協調 → `opus`（需要設計判斷）

### 8.2 使用者確認

plan mode 內建互動確認。使用者可直接修改、調整 Wave 順序、增刪 Task。

### 8.3 寫入 plan.md

使用者確認後，將 plan 寫入 `openspec/changes/<change-name>/plan.md` 並 commit。

## Phase 9: Plan Review（4 × Opus subagent）+ 迭代修正

使用 Agent tool 同時啟動 4 個 review subagent（`model: "opus"`）。每個 subagent 讀取 plan.md 和 openspec change 目錄。

**結果合併**：若建議互相矛盾，優先順序：完整性 > 可執行性 > TDD 合規 > 排序依賴。

#### Agent 1: 完整性

```
比對 openspec specs/ 的每個 Requirement + Scenario 與 plan 的 tasks：
- ✅ 已覆蓋（對應 Task 編號）
- ❌ 未覆蓋（缺少對應 task）
- ⚠️ 部分覆蓋（缺什麼步驟）
覆蓋率 = ✅ / (✅ + ❌ + ⚠️)
標記：🔴 覆蓋率 < 90% 🟡 90-99% 🟢 100%
```

#### Agent 2: 可執行性

```
讀取 plan 的每個 step，檢查：
1. 程式碼是否完整（不是 "add validation" 而是完整程式碼）
2. 指令是否精確（exact command + expected output）
3. 檔案路徑是否正確（專案中實際存在或將建立的路徑）
4. 依賴是否已安裝或在 plan 中安排安裝
5. 給 Sonnet/Haiku 的 task 是否足夠清楚（不需猜測）
標記：🔴 模糊到會做錯 🟡 可能需要額外 context 🟢 建議改善
```

#### Agent 3: TDD 合規

```
檢查每個 Task 的 TDD 流程：
1. Step 1 是否先寫測試（不是先寫實作）
2. Step 2 是否跑測試確認 FAIL（不是跳過）
3. Step 3 的實作是否最小化（不超出測試要求）
4. 測試是否覆蓋正常路徑 + 邊界情況 + 錯誤路徑
5. 是否有 task 缺少測試步驟
標記：🔴 違反 TDD（先實作後測試）🟡 測試不足 🟢 建議改善
```

#### Agent 4: 排序與依賴

```
檢查 Wave 和 Task 的排序：
1. Wave 內的 tasks 是否真的獨立（無隱含依賴）
2. Wave 間的依賴方向是否正確（底層先做）
3. 有沒有 circular dependency
4. 每個 Wave 完成後是否可以獨立驗證
5. Model 分級是否合理（複雜 task 不該用 haiku）
標記：🔴 依賴順序錯誤 🟡 可優化排序 🟢 建議改善
```

**迭代**：修正所有 🔴，盡量修 🟡。重跑 review 直到 🔴=0（最多 3 輪）。修正後更新 plan.md 並 commit。

## Phase 10: 使用者最終確認 + 轉入下一步

1. **通知使用者**：

   > openspec change + plan 已完成並通過所有 review（🔴=0）。
   > 產出物：`openspec/changes/<change-name>/`（含 plan.md）
   >
   > 下一步：
   > - A. 直接執行 `/plan-and-execute <change-name>`（預設）
   > - B. 需要修改 spec 或 plan（說明哪裡要改）
   > - C. 先到這裡，之後再用 `/plan-and-execute <change-name>` 執行

2. **使用者選 A**：調用 `plan-and-execute` skill
3. **使用者選 B**：修改後回到對應 review phase 重跑
4. **使用者選 C**：結束。plan.md 已持久化，任何時候可開新 session 執行 `/plan-and-execute <change-name>`

## 注意事項

- 需求釐清階段（Phase 1-4）不寫程式碼、不動檔案，只對話
- 產出物使用 openspec 格式，存放於 `openspec/changes/<change-name>/`
- plan.md 存放於同一 change 目錄，與 openspec artifacts 共存
- Review subagent 強制使用 Opus model（spec review + plan review 共 8 個 agent 調用）
- 實作完成後可用 `openspec archive` 歸檔 change 並合併回主 specs
- 與 `spec-module` 的差異：`spec-module` 是逆向工程（讀原始碼產 spec），本 skill 是正向設計（從需求產 spec）
