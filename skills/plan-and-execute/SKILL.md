---
name: plan-and-execute
description: "從 openspec change 的 plan.md 自動執行實作。讀取 plan → TDD 分 Wave 實作 → 驗證 → 收尾。純自動執行，不需互動（除非 BLOCKED）。可搭配 /loop 分批執行。當使用者提到 /plan-and-execute、「執行計畫」、「從 spec 開工」、「從 spec 開始實作」、「開始做」時觸發。不適用於簡單 bug fix 或單檔修改。"
version: 2.0.0
---

# Plan and Execute — 自動執行 openspec plan

讀取 openspec change 目錄的 `plan.md`（由 `spec-design` 產出），逐 Wave 自動執行 TDD 實作，同步更新 openspec tasks.md。

**前置條件**：
- superpowers plugin 必須安裝且啟用
- `@fission-ai/openspec` CLI 必須已全域安裝
- 專案已執行 `openspec init`（有 `openspec/` 目錄）
- change 目錄下必須有 `plan.md`（由 `spec-design` Phase 8-9 產出）

## 使用方式

- `/plan-and-execute <change-name>` — 指定 openspec change，從 plan.md 開始自動執行
- `/plan-and-execute` — 無參數時列出 `openspec/changes/` 下有 plan.md 的 change
- `/plan-and-execute --resume <change-name>` — 從上次中斷處繼續（讀 plan.md checkbox 狀態）
- `/plan-and-execute --wave <N> <change-name>` — 只執行指定 Wave

## 流程概覽

```
Phase 1: 讀取 plan.md + openspec artifacts
    ↓
Phase 2: 逐 Wave 執行（TDD + subagent + review）
    ↓
Phase 3: 最終驗證
    ↓
Phase 4: 收尾（PR / merge / archive）
```

## Phase 1: 讀取 plan + artifacts

### 1.1 定位 change

```bash
openspec list
```

若使用者未指定 change-name，列出有 `plan.md` 的 change 讓使用者選擇。

### 1.2 載入執行狀態

讀取 `openspec/changes/<change-name>/plan.md`：
- 解析 Wave / Task 結構
- 從 checkbox 狀態判斷已完成 / 未完成的 task
- `--resume` 模式：從第一個未完成的 task 所在 Wave 開始

### 1.3 讀取 context

讀取 change 目錄的 artifacts 作為執行上下文：
- `specs/` — 需求與場景（用於 spec compliance review）
- `design.md` — 技術設計（用於理解架構決策）
- `tasks.md` — openspec checkbox（執行完同步更新）

### 1.4 Context Window 檢查

- 評估剩餘 token 與預估執行量（Wave 數 × Task 數）
- 若不足以完成所有 Wave，報告可完成的 Wave 數量
- 建議使用者用 `--wave <N>` 或 `/loop` 分批執行

## Phase 2: 逐 Wave 執行

### 2a. 寫測試（RED）

每個 Wave 開始前：
1. **產出 unit test**：
   - 若該 Wave 修改的檔案**已存在**：調用 `test-module`，輸入檔案路徑
   - 若該 Wave 的檔案**尚未建立**：根據 plan.md 中 Step 3 的程式碼片段和 specs 的 Scenario 定義，撰寫測試
   - 測試檔案路徑遵循 plan 中指定的 `Test:` 欄位
2. 跑測試，確認全部 FAIL（RED 狀態）
3. 若有測試意外 PASS → 檢查是否測試寫錯或功能已存在

### 2b. 實作（GREEN）

依 plan 逐 task 派 subagent 實作：

1. **派 subagent**：
   - 提供完整 task 文字 + 上下文（不讓 subagent 讀 plan 檔案）
   - 依 task 標註的 model 分級選擇 model
   - subagent 遵循 plan 的每個 step

2. **subagent 狀態處理**（從自然語言回應判斷）：
   - **DONE**（完成摘要 + commit hash）：進入 review
   - **DONE_WITH_CONCERNS**（完成但附帶疑慮）：評估 concerns 後進入 review
   - **NEEDS_CONTEXT**（提問缺失資訊）：提供缺失 context，重新派
   - **BLOCKED**（無法完成）：
     - context 問題 → 補 context 重派
     - 推理不足 → 換更強 model 重派
     - task 太大 → 拆分後重派
     - plan 本身有錯 → **停下，通知使用者**

3. **每 task 完成後 review**（2 階段）：
   - **Spec compliance**：實作是否符合 openspec specs（不多做不少做）
   - **Code quality**：程式碼品質（命名、結構、STEP 註解、magic number）
   - 有問題 → 修正 → 重跑 review

4. **每 task 完成**：
   - 跑測試確認 PASS → commit
   - 更新 plan.md 的 checkbox（勾選完成的 step）
   - 更新 openspec tasks.md 對應的 checkbox
   - amend commit（確保進度持久化）

### 2c. Task 失敗處理

| 情況 | 處理 |
|------|------|
| 單 task 測試 FAIL | 同 subagent 重試修正（最多 3 次） |
| 重試 3 次仍 FAIL | 標記 task 為 `SKIP`，在 plan 中記錄原因，繼續下一個 task |
| 同 Wave 多個 task FAIL | 暫停 Wave，向使用者報告失敗 tasks，等指示 |
| 後續 Wave 發現前一 Wave 設計有問題 | 停止執行，向使用者報告，建議回到 `spec-design` 修正 plan（已 commit 的程式碼不 revert，用新 commit 修正） |

**原則**：已 commit 的程式碼不做 revert（避免 destructive operation），問題用新 commit 修正。

### 2d. Wave 驗證

- 該 Wave 所有 tasks 完成後（含 SKIP），跑全部測試確認無 regression
- **Context window 檢查**：若 context 不足以完成下一個 Wave，commit 當前進度並結束（使用者可用 `--resume` 繼續）
- 向使用者報告進度：`Wave N/M 完成，X tasks pass / Y tasks skip`
- 進入下一個 Wave

**循序執行**：同一時間只有一個 subagent 在實作（避免衝突），但 review subagent 可平行。

## Phase 3: 最終驗證

全部 Wave 完成後：

1. **跑全部 unit test + coverage**

2. **調用 `spec-to-e2e-test`**：
   - 輸入：openspec change 的 specs/ 目錄路徑
   - spec-to-e2e-test 自行完成：偵察 → 撰寫 E2E → review → 執行
   - E2E 測試結果作為最終驗收

3. **補充 unit test**（條件觸發）：
   - 觸發條件：Phase 2 執行中有新增的整合層程式碼，且不在任何 Wave 的 test-module 範圍內
   - 調用 `test-module` 補充測試
   - 確認整體 coverage ≥ 80%

4. **最終 code review**（整體）：
   - 派 subagent review 整個 implementation 的一致性
   - 跨檔案的命名、pattern、import 是否一致

5. **驗證 openspec 完成度**：
   ```bash
   openspec status --change "<change-name>"
   ```
   確認所有 tasks 已勾選。

6. **產出驗證報告**（寫入 `openspec/changes/<change-name>/report.md`）：

   ```markdown
   # Implementation Report: <Change Name>

   - 日期：YYYY-MM-DD
   - Change：openspec/changes/<change-name>/

   ## 數據
   - Waves: N 個
   - Tasks: M 個（X 個 haiku, Y 個 sonnet, Z 個 opus）
   - Unit Tests: A 個, Coverage: XX%
   - E2E Tests: B 個（C 個 pass, D 個 skip）
   - 實作 Review 修正: N 次

   ## Spec 覆蓋率
   | Requirement | Scenario | 狀態 | 對應 Task | E2E 覆蓋 |
   |-------------|----------|------|----------|---------|

   ## 發現的問題
   | 問題 | 來源 | 修正方式 |
   |------|------|---------|

   ## 被 Skip 的測試（如有）
   | Test | 原因 |
   |------|------|
   ```

## Phase 4: 收尾

1. **通知使用者**：

   > 實作完成，驗證報告已寫入 `openspec/changes/<change-name>/report.md`。
   > - Unit Tests: A 個 (XX% coverage)
   > - E2E Tests: B 個
   >
   > 下一步：
   > - A. 建 PR（推薦）
   > - B. Merge 到主分支
   > - C. Archive openspec change（歸檔並合併回主 specs）
   > - D. 先到這裡

2. **使用者選 A**：push + `gh pr create`
3. **使用者選 B**：merge + 清理 branch
4. **使用者選 C**：`openspec archive <change-name>`
5. **使用者選 D**：告知使用者後續可用 `--resume` 繼續

> A/B/C 可複選（例如先建 PR，merge 後再 archive）。

## 執行模式指南

### `--resume`：跨 session 繼續

從上次中斷處繼續。讀 plan.md 的 checkbox，找到第一個未勾選的 task 所在 Wave，從那裡開始。

```
/plan-and-execute --resume my-change
```

**場景**：跑到 Wave 3 時 context window 不夠了自動停止。關掉 session，隔天開新 session 用 `--resume` 繼續。

### `--wave <N>`：只跑指定 Wave

只執行指定的單一 Wave，做完就停。

```
/plan-and-execute --wave 1 my-change
```

**場景**：想先看基礎層（Wave 1）的結果確認沒問題，再決定要不要繼續。滿意後跑 `--wave 2` 或 `--resume`。

### `/loop` + `--resume`：全自動分批（推薦）

搭配 loop skill 全自動分批執行。每次 session 跑到 context 不夠時自動停止，loop 開新 session 用 `--resume` 繼續，直到全部完成。

```
/loop 0 /plan-and-execute --resume my-change
```

`0` 表示上一輪結束後立即開下一輪。適合大功能（5+ Wave），放著跑完去喝咖啡。

### 三者比較

| 方式 | 人介入 | 適用場景 |
|------|--------|---------|
| `--resume` | 每次手動啟動 | 跨 session 繼續、想檢查中間結果 |
| `--wave <N>` | 指定跑哪一波 | 謹慎模式、只想跑特定層 |
| `/loop` + `--resume` | 全自動 | 大功能、放著跑完（推薦） |

## Model 策略摘要

| 角色 | Model | 原因 |
|------|-------|------|
| 寫 unit test (test-module) | 依 test-module 預設 | test-module 自行管理 |
| 實作 subagent (簡單) | Haiku | 1-2 檔、明確 spec |
| 實作 subagent (標準) | Sonnet | 多檔整合 |
| 實作 subagent (複雜) | Opus | 架構判斷 |
| Spec compliance review | Sonnet | 比對 spec 和程式碼 |
| Code quality review | Sonnet | 品質檢查 |
| E2E 測試 (spec-to-e2e-test) | 依 skill 預設 | skill 自行管理 |
| 最終整體 review | Opus | 跨模組一致性 |

## 注意事項

- 本 skill 是純 executor，所有互動式決策已在 `spec-design` 完成
- plan.md 由 `spec-design` Phase 8-9 產出並經 4-agent review，本 skill 不再 review plan
- 同一時間只有一個實作 subagent 在工作（避免 git 衝突）
- 每個 subagent 接收完整 task 文字，不讓 subagent 自己讀 plan
- BLOCKED 狀態不硬推，停下通知使用者
- `--resume` 模式讀取 plan.md checkbox 狀態，從第一個未完成的 task 繼續
- 與 `spec-design` 的銜接：spec-design Phase 10 選 A 後自動調用本 skill
- 實作完成後可用 `openspec archive` 歸檔 change 並合併回主 specs
