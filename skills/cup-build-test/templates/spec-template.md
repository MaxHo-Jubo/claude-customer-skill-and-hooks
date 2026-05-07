<!--
  CUP 測試規格文件樣板（人 + Playwright 共讀）

  使用方式：
  - skill 階段 2 會以此檔為骨架，根據階段 1 的 coverage.json 填空
  - 雙大括號（兩個左大括號 + 內容 + 兩個右大括號）是 placeholder，全部需替換
  - case 類型標記語法：
      #### A1.1 主流程 ‹read-only›
      #### A1.2 邊界情況 ‹mutation›
    （若一個 case 內混 read-only 與 mutation，整體標 mutation；‹...› 是示意框，實際寫 [read-only] 或 [mutation]）
  - 此檔產出後手動修改也 OK，skill 階段 5 會用 HTML comment 標註修正紀錄
  - 帶有 case-block 標記（HTML comment 形式）的整段需被 skill 階段 2 整段重寫，不可保留教學佔位符
-->

# {{ISSUE_KEY}} {{FEATURE_TITLE}} 測試計劃

> **Jira**：{{ISSUE_KEY}}
> **範圍**：{{FEATURE_PATH}}
> **目的**：{{PURPOSE}}
> **狀態**：{{STATUS}}
> **更新**：{{YYYY-MM-DD}}

---

## 使用方式

### 階段一：R15 正式環境 baseline

在 R15 正式環境逐項操作。每個 step 看 UI 是否符合預期，逐個打勾。
此輪結果是「正確版本」基準。

### 階段二：R18 測試環境驗證

R18 升級部署到測試環境後，用同份計劃再跑一次。
比對結果：每個 step 在 R18 應該得到跟 R15 完全相同的 UI 表現。

### 結果代碼

| 代碼 | 意義 | 處置 |
|------|------|------|
| ✅ Pass | R18 行為與 R15 baseline 完全一致 | 通過 |
| ⚠️ Diff | 行為不同但可接受（如 UI 微調、文案改善） | 紀錄差異、需 PM/QA 同意 |
| ❌ Fail | 功能壞掉、流程斷裂、操作失效 | 立刻擋升級、回開 ticket |
| 🚫 N/A | R15 未實作或環境不適用 | 略過 |

### Case 類型標記

| 標記 | 意義 |
|------|------|
| `[read-only]` | 只讀取，不會修改任何資料；正式環境跑無風險 |
| `[mutation]` | 會建立 / 修改 / 刪除資料；正式環境跑前需確認，跑完需手動清理 |

---

## 環境資訊（測試前補齊）

| 項目 | R15 正式環境 | R18 測試環境 |
|------|------------|------------|
| URL | https://luna.compal-health.com | _TBD_ |
| **Entry path** | `{{ENTRY_PATH}}` | 同 |
| 測試帳號 | _TBD_ | _TBD_ |
| 機構 | _TBD_ | _TBD_ |
| 角色 | {{REQUIRED_ROLE}} | 同 |
| 測試資料 | {{REQUIRED_TEST_DATA}} | 同 |
| Viewport | 1440 × 900 | 同 |
| Locale | zh-TW | 同 |

> **Entry path** 是腳本登入後第一個 navigate 的相對路徑（例：`/activityManager/activityCalendar`）。skill 階段 3 從這欄位取出寫入 cjs 的 `ENTRY_PATH` 常數。
>
> **動態參數**：若 path 含 `{caseId}` `{orderId}` 等模板變數（例：`/case/list/{caseId}/yearlyQuotaSetting`），階段 4c 跑測試前必須提供對應 env var（`CASE_ID=...` 等）。skill 階段 4a dry-run 會偵測並中止直到使用者提供。

---

## 共用前置條件

每個 case 開始前確認：

- [ ] 已用測試帳號登入
- [ ] {{ENTRY_PATH_DESCRIPTION}}
- [ ] 頁面已載入完成
- [ ] 畫面無紅色錯誤提示

---

<!-- TEMPLATE-CASE-BLOCK: skill 階段 2 必須以下列教學內容為「結構參考」，依 coverage 完整重寫每個 case，不得保留任何教學佔位符（`操作步驟 1` 等）。產出後此區塊不應再含 TEMPLATE-CASE-BLOCK 標記。 -->

## A. {{LARGE_FEATURE_A_TITLE}}

### A1. {{SUB_FEATURE_A1_TITLE}}

#### A1.1 主流程 [read-only|mutation]

操作步驟（依 coverage 對應 API 流程逐項列出）：

- [ ] 操作步驟 1（從 coverage 推導，例：點選「新增」按鈕）
- [ ] **預期**：UI 結果 1（例：Modal 開啟）
- [ ] 操作步驟 2
- [ ] **預期**：
  - [ ] 預期細節 1
  - [ ] 預期細節 2

**涉及 API**：
- `METHOD ENDPOINT`（從 coverage.apiEndpoints 對應，例：`POST /api/activity/create`）

#### A1.2 邊界情況 [read-only|mutation]

通用樣板（每項都需具體化或刪除）：

- [ ] **必填漏填**：必填欄位留空 → 儲存 → 驗證錯誤、Modal 不關閉
- [ ] **時間/數值反置**（若有相關欄位）：結束早於開始 → 驗證錯誤
- [ ] **重複送出**：連點儲存兩下 → 只建立一筆 / 按鈕 disable
- [ ] **取消**：填一半 → 點「取消」→ Modal 關閉、無變化
- [ ] **背景點擊**：點 Modal 外側陰影區 → 觀察 Modal 行為
- [ ] **Esc 鍵**：按 Esc → 觀察 Modal 行為
- [ ] 該功能特有邊界（依 coverage 補）

### A2. {{SUB_FEATURE_A2_TITLE}}

<!-- 重複 A1 結構，內容由 skill 完整重寫 -->

<!-- /TEMPLATE-CASE-BLOCK -->

---

## B. {{LARGE_FEATURE_B_TITLE}}

<!-- TEMPLATE-CASE-BLOCK: 重複 A 結構，內容由 skill 完整重寫 -->
<!-- /TEMPLATE-CASE-BLOCK -->

---

## 執行紀錄表

| Case | 類型 | R15 Baseline | R18 結果 | 差異備註 |
|------|------|------|------|------|
| A1.1 主流程 | mutation | ⬜ | ⬜ | |
| A1.2 必填漏填 | mutation | ⬜ | ⬜ | |
| A1.2 重複送出 | mutation | ⬜ | ⬜ | |
| A1.2 取消 | read-only | ⬜ | ⬜ | |
| A1.2 Esc 鍵 | read-only | ⬜ | ⬜ | |
| A2.1 主流程 | mutation | ⬜ | ⬜ | |
| ... | ... | ⬜ | ⬜ | |

---

## 跑測試後的處理

### 全綠
- 在 Jira {{ISSUE_KEY}} 留 comment 連結到本檔 + 關鍵截圖
- 注意：本檔不入 git（.gitignore 過濾），需要存證請另上傳到 Confluence 或 Jira 附件

### 出現 ⚠️ Diff
- 在差異備註欄寫清楚：哪邊行為不同、是 R15 bug 已修 / R18 故意改 / 還是回歸
- PM/QA 確認後分別標記為 ✅ 或 ❌

### 出現 ❌ Fail
- 立刻擋 R18 升級
- 開 sub-ticket、回對應 sub-PR 補修
- 修完重跑該 case，更新本檔

---

## 自動化執行（搭配 cup-build-test skill）

本檔由 `/cup-build-test` skill 階段 2 產出，並由階段 3 同步產出 Playwright 腳本 `.claude/{{ISSUE_KEY}}-test.cjs`。

執行命令（不需要 npm install playwright）：

```bash
# R15 正式環境（baseline）
VARIANT=r15 BASE_URL=https://luna.compal-health.com \
  npx --yes -p playwright@latest node .claude/{{ISSUE_KEY}}-test.cjs

# 本地 R18
npx --yes -p playwright@latest node .claude/{{ISSUE_KEY}}-test.cjs

# Staging R18
BASE_URL=https://staging.example.com \
  npx --yes -p playwright@latest node .claude/{{ISSUE_KEY}}-test.cjs

# 只跑某個 prefix
ONLY=A1 npx --yes -p playwright@latest node .claude/{{ISSUE_KEY}}-test.cjs

# 第一個 fail 就停
STOP_ON_FAIL=true npx --yes -p playwright@latest node .claude/{{ISSUE_KEY}}-test.cjs
```

執行前：
- `.playwright-auth/auth.json` 已透過 skill 階段 4b 互動式登入產生
- 第一次跑時 npx 會下載 chromium driver（會慢一點，後續快取生效）

---

<!-- TEMPLATE-CASE-BLOCK: skill 階段 2 步驟 8 從 coverage.apiEndpoints 與 coverage.reduxActions 自動填表，重寫整個附錄表並移除 TEMPLATE-CASE-BLOCK 標記 -->

## 附錄：API 覆蓋率追蹤（dev 確認用）

> 此表給開發者確認測試 case 是否覆蓋到所有 API；測試執行時不需查看。
> 由 skill 階段 1 從 git diff 反推自動填寫。

| API | 對應 Case | 來源檔案 |
|-----|----------|---------|
| METHOD ENDPOINT 範例 | A1, A2 | src/.../file.ts 範例 |
| 範例：請依 coverage 重寫 | ... | ... |

<!-- /TEMPLATE-CASE-BLOCK -->
