---
name: plan-and-execute
description: "從設計 spec 到完成實作的結構化流程。Plan → TDD → 分 Wave 實作 → 驗證。當使用者提到 /plan-and-execute、「寫 plan」、「執行計畫」、「從 spec 開工」、「從 spec 開始實作」、想從設計文件開始實作時觸發。不適用於簡單 bug fix 或單檔修改。"
version: 1.1.0
---

# Plan and Execute — 從 Spec 到實作完成

讀取設計 spec，產出細粒度 TDD 實作計畫，經 review 後分 Wave 執行：先寫測試（RED）→ 派 subagent 實作（GREEN）→ 驗證 → 下一個 Wave。

有 superpowers 時 delegate 給 `writing-plans` + `subagent-driven-development`；無 superpowers 時走原生流程。兩條路徑最後都調用 `test-module` 和 `spec-to-e2e-test` 做最終驗證。

## 使用方式

- `/plan-and-execute <spec路徑>` — 指定 spec 開始完整流程
- `/plan-and-execute` — 無參數時搜尋 `docs/superpowers/specs/` 列出可用 spec
- `/plan-and-execute --plan-only` — 只產 plan 不執行
- `/plan-and-execute --resume <plan路徑>` — 從已有 plan 的某個 Wave 繼續

## 環境偵測

```
從 system prompt 的 available skills 列表判斷（不需讀取 config 檔案）：

若 superpowers:writing-plans 存在：
  → Phase 1: 調用 superpowers:writing-plans 產出 plan
  → Phase 3: 調用 superpowers:subagent-driven-development 執行
  → Phase 4: 回到本 skill 做最終驗證（test-module + spec-to-e2e-test）
否則：
  → 走 Phase 1 ~ Phase 5 原生流程
```

## 原生流程

### Phase 1: 寫 Plan（建議 Opus，使用 Agent tool 的 `model: "opus"` 參數）

1. **讀取 spec**：
   - 解析設計 spec 的所有 scenario 和需求
   - 掃描專案現有架構（目錄結構、技術棧、既有 pattern）
   - 識別需要建立/修改的檔案

2. **File Structure Map**：
   - 列出所有將建立或修改的檔案及其職責
   - 每個檔案一個職責，偏好小而聚焦的檔案
   - 既有 codebase 優先 follow existing pattern

3. **拆 Wave**：
   - 依據依賴關係將 tasks 分組為 Wave
   - Wave 1 處理基礎層（DB/model/provider）
   - 後續 Wave 依序往上疊加（service → UI → integration）
   - 同一 Wave 內的 tasks 盡量獨立

4. **拆 Task**（每 task 2-5 分鐘粒度）：

   每個 Task 包含：
   ```markdown
   ### Task N: [Component Name]

   **Wave:** N
   **Model:** haiku | sonnet | opus（依複雜度）
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

   - [ ] **Step 5: Commit**
   `git add <files> && git commit -m "<message>"`
   ```

5. **Model 分級標註**：
   - 每個 Task 標註建議 model
   - 1-2 檔 + 明確 spec → `haiku`（機械式實作）
   - 多檔整合 + pattern matching → `sonnet`（標準實作）
   - 架構判斷 + 跨模組協調 → `opus`（需要設計判斷）

6. **Plan Header**：

   ```markdown
   # [Feature Name] Implementation Plan

   **Goal:** [一句話描述]
   **Architecture:** [2-3 句方法論]
   **Tech Stack:** [關鍵技術]
   **Spec:** [spec 檔案路徑]
   **Waves:** N 個 Wave, M 個 Tasks

   ---
   ```

7. **寫入檔案**：`docs/superpowers/plans/YYYY-MM-DD-<name>.md` + commit

8. **Context Window 檢查點**：
   - 評估剩餘 token 與預估執行量（Wave 數 × Task 數 × review 輪數）
   - 若 Wave > 5 或 Task > 20，建議使用者分 session 執行（用 `--resume`）
   - 向使用者報告：`Plan 共 N Waves / M Tasks，預估需要 X 輪 subagent 調用`

### Phase 2: Plan Review（4 × Opus subagent）

使用 Agent tool 同時啟動 4 個 review subagent（`model: "opus"`）。每個 subagent 的 prompt 包含 plan 檔案路徑和 spec 檔案路徑。

**結果合併**：4 個 agent 完成後，orchestrator 彙整所有結果。若不同 agent 建議互相矛盾（如 Agent 1 要加 task 但 Agent 4 說 scope 太大），以完整性 > 可執行性 > TDD 合規 > 排序依賴的優先順序判斷。

#### Agent 1: 完整性

```
比對 spec 的每個 scenario/requirement 與 plan 的 tasks：
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

**迭代**：修正所有 🔴，盡量修 🟡。重跑 review 直到 🔴=0（最多 3 輪）。

### Phase 3: 逐 Wave 執行

#### 3a. 寫測試（RED）

每個 Wave 開始前：
1. **產出 unit test**：
   - 若該 Wave 修改的檔案**已存在**：調用 `test-module`，輸入檔案路徑，test-module 自行掃描函式簽名
   - 若該 Wave 的檔案**尚未建立**：根據 plan 中 Step 3 的程式碼片段和 spec 的 interface 定義，手動撰寫測試（不調用 test-module，因為目標檔案不存在無法掃描）
   - 測試檔案路徑遵循 plan 中指定的 `Test:` 欄位
2. 跑測試，確認全部 FAIL（RED 狀態）
3. 若有測試意外 PASS → 檢查是否測試寫錯或功能已存在

#### 3b. 實作（GREEN）

依 plan 逐 task 派 subagent 實作：

1. **派 subagent**：
   - 提供完整 task 文字 + 上下文（不讓 subagent 讀 plan 檔案）
   - 依 task 標註的 model 分級選擇 model
   - subagent 遵循 plan 的每個 step

2. **subagent 狀態處理**（從自然語言回應判斷）：
   - **DONE**（回應包含完成摘要 + commit hash）：進入 review
   - **DONE_WITH_CONCERNS**（完成但附帶疑慮描述）：評估 concerns 後進入 review
   - **NEEDS_CONTEXT**（回應包含「需要知道...」「缺少...的資訊」等提問）：提供缺失 context，重新派
   - **BLOCKED**（回應包含「無法完成」「卡住」「錯誤無法解決」）：
     - context 問題 → 補 context 重派
     - 推理不足 → 換更強 model 重派
     - task 太大 → 拆分後重派
     - plan 本身有錯 → 停下，通知使用者

3. **每 task 完成後 review**（2 階段）：
   - **Spec compliance**：實作是否符合 spec（不多做不少做）
   - **Code quality**：程式碼品質（命名、結構、STEP 註解、magic number）
   - 有問題 → 修正 → 重跑 review

4. **每 task 完成**：跑測試確認 PASS → commit → 更新 plan 檔案的 checkbox → amend commit（確保進度持久化）

#### 3c. Task 失敗處理

| 情況 | 處理 |
|------|------|
| 單 task 測試 FAIL | 同 subagent 重試修正（最多 3 次） |
| 重試 3 次仍 FAIL | 標記 task 為 `SKIP`，在 plan 中記錄原因，繼續下一個 task |
| 同 Wave 多個 task FAIL | 暫停 Wave，向使用者報告失敗 tasks，等指示（修 plan / 跳過 / 終止） |
| 後續 Wave 發現前一 Wave 設計有問題 | 停止執行，向使用者報告，建議回到 Phase 1 修正 plan（已 commit 的程式碼不 revert，用新 commit 修正） |

**原則**：已 commit 的程式碼不做 revert（避免 destructive operation），問題用新 commit 修正。

#### 3d. Wave 驗證

- 該 Wave 所有 tasks 完成後（含 SKIP），跑全部測試確認無 regression
- **Context window 檢查**：評估剩餘 token 與後續 Wave 的預估消耗。若 context 不足以完成下一個 Wave，commit 當前進度並建議使用者用 `--resume` 開新 session 繼續
- 向使用者報告進度：`Wave N/M 完成，X tasks pass / Y tasks skip`
- 進入下一個 Wave

**循序執行**：同一時間只有一個 subagent 在實作（避免衝突），但 review subagent 可平行。

### Phase 4: 最終驗證

全部 Wave 完成後：

1. **跑全部 unit test + coverage**

2. **調用 `spec-to-e2e-test`**：
   - 輸入：spec 文件路徑
   - spec-to-e2e-test 會自行完成：偵察 → 撰寫 E2E → 4 agent review → 迭代 → 執行
   - E2E 測試結果作為最終驗收

3. **補充 unit test**（條件觸發）：
   - 觸發條件：Phase 3 執行中有新增的整合層程式碼（如 Wave 間共用的 service/controller），且這些程式碼不在任何 Wave 的 test-module 範圍內
   - 調用 `test-module` 針對這些整合層檔案補充測試
   - 確認整體 coverage ≥ 80%

4. **最終 code review**（整體）：
   - 派 subagent review 整個 implementation 的一致性
   - 跨檔案的命名、pattern、import 是否一致

5. **產出驗證報告**（寫入 `docs/superpowers/reports/YYYY-MM-DD-<name>-report.md`）：

   ```markdown
   # Implementation Report: <Feature Name>

   - 日期：YYYY-MM-DD
   - Spec：<path>
   - Plan：<path>

   ## 數據
   - Waves: N 個
   - Tasks: M 個（X 個 haiku, Y 個 sonnet, Z 個 opus）
   - Unit Tests: A 個, Coverage: XX%
   - E2E Tests: B 個（C 個 pass, D 個 skip）
   - Plan Review 迭代: N 輪
   - 實作 Review 修正: N 次

   ## Spec 覆蓋率
   | Scenario | 狀態 | 對應 Task | E2E 覆蓋 |
   |----------|------|----------|---------|

   ## 發現的問題
   | 問題 | 來源 | 修正方式 |
   |------|------|---------|

   ## 被 Skip 的測試（如有）
   | Test | 原因 |
   |------|------|
   ```

### Phase 5: 收尾

1. **通知使用者**：

   > 實作完成，驗證報告已寫入 `<path>`。
   > - Unit Tests: A 個 (XX% coverage)
   > - E2E Tests: B 個
   >
   > 下一步：
   > - A. Merge 到主分支
   > - B. 建 PR（推薦）
   > - C. 先到這裡

2. **使用者選 A**：merge + 清理 branch
3. **使用者選 B**：push + 建 PR（gh pr create）
4. **使用者選 C**：告知使用者後續可用 `/plan-and-execute --resume <plan路徑>` 繼續

## Superpowers 路徑補充

有 superpowers 時，Phase 1~3 由 superpowers skills 處理，但 Phase 4（最終驗證）始終由本 skill 執行：

```
superpowers:writing-plans → 產出 plan
superpowers:subagent-driven-development → 執行 plan（含 TDD + 2 階段 review）
superpowers:finishing-a-development-branch → 收尾選項
↓
本 skill Phase 4: 最終驗證
  → test-module（補充測試 + coverage 確認）
  → spec-to-e2e-test（E2E 驗收）
  → 產出驗證報告
```

## Model 策略摘要

| 角色 | Model | 原因 |
|------|-------|------|
| Plan 撰寫 | Opus | 架構決策不能省 |
| Plan Review (4 agents) | Opus | 需要判斷力 |
| 寫 unit test (test-module) | 依 test-module 預設 | test-module 自行管理 |
| 實作 subagent (簡單) | Haiku | 1-2 檔、明確 spec |
| 實作 subagent (標準) | Sonnet | 多檔整合 |
| 實作 subagent (複雜) | Opus | 架構判斷 |
| Spec compliance review | Sonnet | 比對 spec 和程式碼 |
| Code quality review | Sonnet | 品質檢查 |
| E2E 測試 (spec-to-e2e-test) | 依 skill 預設 | skill 自行管理 |
| 最終整體 review | Opus | 跨模組一致性 |

## 注意事項

- Plan 和 spec 使用相同的 `docs/superpowers/` 路徑結構，確保與 superpowers 互通
- 同一時間只有一個實作 subagent 在工作（避免 git 衝突）
- 每個 subagent 接收完整 task 文字，不讓 subagent 自己讀 plan 檔案
- BLOCKED 狀態不硬推，停下通知使用者
- `--resume` 模式讀取 plan 的 checkbox 狀態，從第一個未完成的 task 繼續
- 與 `spec-design` 的銜接：spec-design Phase 8 選 A 後自動調用本 skill
