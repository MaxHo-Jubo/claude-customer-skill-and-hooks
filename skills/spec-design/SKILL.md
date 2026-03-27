---
name: spec-design
description: "從需求到設計 spec 的結構化流程：需求釐清 → 方案比較 → 設計呈現 → 撰寫 spec → 4-agent review → 迭代修正。當使用者提到 /spec-design、「設計新功能」、「寫設計 spec」、「brainstorm 新功能」、「需求探索」、「新功能架構設計」、「技術方案討論」、「寫 RFC」、想從零開始設計一個功能或系統時觸發。不適用於：讀原始碼產 spec（用 spec-module）、重構既有程式碼、寫測試、bug fix。"
version: 1.2.0
---

# Spec Design — 需求探索到設計 spec

從模糊需求出發，透過結構化對話釐清需求、比較方案、產出設計 spec，經 4 輪平行 review 迭代至零問題。

有 superpowers plugin 時自動 delegate 給 `superpowers:brainstorming`（brainstorming 包含完整的需求釐清 + 方案比較 + 撰寫 spec + review loop，產出已 review 的設計 spec）；無 superpowers 時走本 skill 的原生流程。兩條路徑的產出物格式可能略有差異（brainstorming 由 plugin 控制），但都是寫入 `docs/superpowers/specs/` 的設計 spec。

## 使用方式

- `/spec-design` — 互動式需求探索（偵測環境後自動選路徑）
- `/spec-design <需求描述>` — 帶初始需求直接開始
- `/spec-design --native` — 強制走原生流程（即使有 superpowers，用於 debug 或偏好原生 review）

## 環境偵測

```
檢查當前 session 的 available skills 列表是否包含 superpowers:brainstorming
（系統提示中的 skill 列表即為判斷依據，不需讀取設定檔）

若 superpowers:brainstorming 存在（且使用者未指定 --native）：
  → 調用 superpowers:brainstorming skill
  → brainstorming 會自行完成 Phase 1~7 等價的工作（需求釐清 + 方案比較 + 撰寫 spec + review loop）
  → brainstorming 結束後，本 skill 從 Phase 8 接手（轉入下一步）
否則：
  → 走 Phase 1 ~ Phase 8 原生流程
```

## 原生流程

### Phase 1: 專案 Context 探索

1. **掃描專案狀態**：
   - 讀取 CLAUDE.md、README.md、package.json / pubspec.yaml
   - `git log --oneline -20` 了解近期開發方向
   - 掃描目錄結構（特別是 `spec/`、`openspec/`、`docs/` 是否已有相關文件）
   - 識別技術棧（語言、框架、狀態管理、DB）

2. **檢查既有 spec**：
   - 若專案有 openspec 或 spec 目錄，列出已有的 spec 清單
   - 判斷新需求與既有 spec 的關聯（擴充 vs 全新）

3. **向使用者報告**：簡述專案現狀、技術棧、與新需求可能相關的既有模組

### Phase 2: 需求釐清

**規則**：
- **一次只問一個問題**，不要一次丟多個問題
- 優先用**選擇題**（A/B/C），開放式問題只在必要時使用
- 聚焦於：目的（為什麼要做）、限制（不能怎樣）、成功標準（怎樣算做完）

**提問框架**（依序，不一定每題都問，視需求複雜度跳過）：

1. **目的**：這個功能要解決什麼問題？誰會用？
2. **範圍**：核心功能是什麼？哪些東西明確不做？
3. **資料**：涉及哪些資料實體？關係是什麼？
4. **互動**：使用者的操作流程是什麼？主要畫面有幾個？
5. **邊界**：例外情況怎麼處理？（斷網、空資料、併發）
6. **限制**：效能需求？平台限制？向後相容？
7. **驗收**：怎樣算「做完了」？有量化標準嗎？

**Scope 檢查**：若需求涵蓋多個獨立子系統，先協助使用者拆解，確認本次 spec 只處理一個子系統。

**中途退出**：使用者可在任何 Phase 說「暫停」或「先到這裡」。已討論的內容保留在對話中，後續可用 `/spec-design` 繼續。若 Phase 4 之前退出，不產出任何檔案；Phase 4 之後退出，已確認的設計段落可先寫入 draft 檔案。

### Phase 3: 方案比較

1. **提出 2-3 個方案**，每個方案包含：
   - 核心思路（一句話）
   - 優點 / 缺點
   - 技術複雜度（低/中/高）
   - 對既有架構的影響

2. **給出推薦**：明確說推薦哪個方案 + 為什麼

3. **等使用者確認**方向後再進入設計

### Phase 4: 設計呈現

**分段呈現，每段確認後再進下一段。** 每段依複雜度調整篇幅（簡單幾句話，複雜可到 200-300 字）。

呈現順序：

1. **資料結構**：實體定義、關係、DB schema 變更
2. **架構**：模組劃分、依賴方向、介面定義
3. **使用者流程**：操作步驟、畫面切換、狀態變化
4. **錯誤處理**：例外情境、降級策略、使用者提示
5. **測試策略**：哪些 scenario 要測、測試類型（unit/integration/e2e）
6. **Migration / 向後相容**：既有資料怎麼處理、是否需要 migration

**設計原則**：
- 資料結構先行 — 資料對了，程式碼自然簡單
- 消除邊界情況 > 增加條件判斷
- YAGNI — 砍掉沒人要的功能
- 拆成小單元，每個單元一個職責、明確介面、可獨立測試
- 既有 codebase 優先 follow existing pattern

### Phase 5: 撰寫設計 spec

設計確認後，寫入檔案並 commit：

**檔案路徑**：`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
（若使用者有指定其他路徑，以使用者為準）

**路徑衝突處理**：若目標檔案已存在，詢問使用者：
- A. 覆蓋（視為同功能的新版 spec）
- B. 加序號（`-v2`、`-v3`）
- C. 指定新路徑

**文件結構**：

```markdown
# <功能名稱> 設計 spec

- 日期：YYYY-MM-DD
- 狀態：Draft → Reviewed → Approved
- 相關 Spec：（若有既有 openspec/spec 引用）

## 背景與目的
（為什麼要做、解決什麼問題）

## 範圍
### 包含
- ...
### 不包含
- ...

## 資料結構
（實體定義、關係圖、DB schema 變更）

## 架構設計
（模組劃分、依賴方向、介面定義）

## 使用者流程
（操作步驟、畫面切換、狀態變化）

## 錯誤處理
（例外情境、降級策略）

## 測試策略
（哪些 scenario、測試類型）

## Migration / 向後相容
（既有資料處理、是否需 migration）

## 風險與待決事項
- ...
```

寫完後詢問使用者是否要 commit：
> Spec 已寫入 `<path>`。要先 commit 嗎？（Y/N）

使用者確認後才執行 `git add` + `git commit`。

### Phase 6: Spec Review（4 個平行 Opus Subagent）

撰寫完成後，使用 Agent tool **同時**啟動 4 個 review subagent（`model: "opus"`）。

**調用方式**：
- 使用 Agent tool 平行啟動 4 個 subagent，每個 subagent 的 prompt 包含 spec 檔案路徑
- 每個 subagent 自行讀取 spec 檔案（不由 orchestrator 傳入內容）
- 等待 4 個 subagent 全部完成後，彙整結果進入 Phase 7

#### Agent 1: 完整性 + 一致性

```
讀取 spec 文件，檢查：
1. 是否有 TODO / TBD / placeholder / 未完成區段
2. 前後描述是否矛盾（例如 Phase A 說 sync，Phase B 說 async）
3. 名詞/數字前後是否一致
4. 資料流是否有缺口（A 產出的東西 B 沒有接住）
5. 每個區段是否都有實質內容（不只是標題）

標記嚴重度：🔴 會導致 plan 出錯 🟡 模糊但可能不影響 🟢 建議改善
```

#### Agent 2: 可實作性

```
讀取 spec 文件和專案既有架構（目錄結構、相關模組、技術棧），檢查：
1. 每個需求是否清楚到能直接寫 plan（不用回頭問使用者）
2. 技術方案是否可行（API 存在嗎、套件能裝嗎、平台支援嗎）
3. 每個 scenario 是否能寫成測試（可測試性）
4. 預估的工作量是否合理（有沒有隱藏的複雜度）
5. 依賴的外部服務 / 第三方套件是否明確

標記嚴重度：🔴 無法實作或需求不明確 🟡 可實作但有風險 🟢 建議改善
```

#### Agent 3: 邊界與風險

```
讀取 spec 文件，檢查：
1. 邊界情況是否涵蓋（null / 空值 / 併發 / 極端值 / 斷網）
2. 向後相容性（會破壞既有功能嗎）
3. 跨模組影響（資料結構改動影響哪些現有模組）
4. 資料 migration 是否有處理（schema 變更時既有資料怎麼辦）
5. 安全性（權限、資料外洩、注入）

標記嚴重度：🔴 會導致既有功能壞掉或資料遺失 🟡 邊界未處理 🟢 建議改善
```

#### Agent 4: 範圍與品味

```
讀取 spec 文件，檢查：
1. YAGNI — 有沒有沒人要求的功能混進來
2. Scope — 是否聚焦到單一 plan 可處理（沒有混入多個獨立子系統）
3. 資料結構設計是否消除邊界情況（而非用 if 處理）
4. 抽象是否適當（不過度封裝、不過度簡化）
5. 與既有 codebase pattern 是否一致

標記嚴重度：🔴 scope 失控或設計反模式 🟡 可精簡 🟢 建議改善
```

### Phase 7: 迭代修正

1. **彙整 4 份 review** → 統一報告：
   - 🔴 問題數量
   - 🟡 問題數量
   - 各 agent 的重點發現
   - 若不同 agent 的建議互相矛盾，由 orchestrator 判斷優先順序（完整性 > 可實作性 > 邊界風險 > 品味）

2. **修正所有 🔴 問題**，盡量修 🟡

3. **重新啟動 4 個 review subagent**（針對完整 spec 重跑，因為局部修正可能引入新問題）

4. **重複直到 🔴 = 0**（最多 3 輪，超過則向使用者報告剩餘問題，由使用者判斷是否接受）

5. **殘留 🟡 處理**：迭代結束後仍有 🟡 的，記錄到 spec 的「風險與待決事項」區段

6. **更新文件狀態**：`Draft` → `Reviewed`

### Phase 8: 使用者最終 Review + 轉入下一步

1. **通知使用者**：

   > Spec 已寫入 `<path>` 並通過 review（🔴=0）。請檢閱後告訴我：
   > - A. 沒問題，繼續進入 plan-and-execute（預設）
   > - B. 需要修改（說明哪裡要改）
   > - C. 先到這裡，之後再繼續

2. **使用者選 A**：
   - 更新文件狀態：`Reviewed` → `Approved`
   - 偵測環境：
     - 有 superpowers → 調用 `superpowers:writing-plans`
     - 無 superpowers → 調用 `plan-and-execute` skill（待建立）
     - `plan-and-execute` 也不存在 → 提示使用者手動規劃

3. **使用者選 B**：修改後回到 Phase 6 重跑 review

4. **使用者選 C**：結束，告知使用者後續可用 `/plan-and-execute <spec-path>` 銜接

## 注意事項

- 需求釐清階段不寫程式碼、不動檔案，只對話
- 設計 spec路徑與 superpowers:brainstorming 產出相同（`docs/superpowers/specs/`），確保兩條路徑的產出物互通
- Review subagent 強制使用 Opus model
- 與 `spec-module` 的差異：`spec-module` 是逆向工程（讀原始碼產 spec），本 skill 是正向設計（從需求產 spec）
