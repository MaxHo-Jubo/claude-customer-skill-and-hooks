---
name: jira-test-report
description: "對 Jira issue 跑 Playwright E2E 測試，自動截圖並 inline 上傳到 issue comment（截圖直接顯示在留言中，非附件清單）。當使用者提到 /jira-test-report、「跑測試報告」、「驗收測試上 Jira」、「截圖到 Jira」、「自動化測試 + Jira」、想對某個 issue 跑驗收測試並把結果留在 Jira 時觸發。"
version: 2.4.0
---

# Jira E2E 測試報告（含 inline 截圖）

對 Jira issue 跑 Playwright 自動化測試，截圖每個步驟，並用 wiki-style 把截圖 **inline 顯示在 comment 中**（而不是只列附件清單）。

## 使用方式

- `/jira-test-report` — 從 branch 自動取 issue key，預設 **互動模式**
- `/jira-test-report ERPD-XXXX` — 指定 issue key
- `/jira-test-report --script` — 強制 **腳本模式**（先產 .cjs 再 node 執行）
- `/jira-test-report --script ERPD-XXXX` — 指定 issue key 且用腳本模式
- `/jira-test-report --resume` — 從 `.claude/{ISSUE_KEY}-progress.md` 續跑（rate limit 中斷後用，跳過已完成 step 與已 upload 的截圖）
- `/jira-test-report --resume ERPD-XXXX` — 指定 issue key 續跑

## 模式選擇（先決定再開工）

| 模式 | 適用 | Token 成本 | 可重跑 | Debug |
|------|------|-----------|-------|-------|
| **互動模式**（Playwright MCP） | 探索式、流程未定型、UI 變動頻繁 | 高（每步 a11y tree + 可能 base64 截圖） | 否 | 容易（即時看截圖） |
| **腳本模式**（生成 .cjs + node 執行） | 回歸驗證、流程已穩定、CI 候選 | 低（只回 stdout 摘要，省 80%+） | 是 | 較難（需看 log + 截圖檔） |

**判斷依據**：
- 第一次跑這個 issue / 流程不確定 → 互動模式
- 同 issue 第二次以後 / 已有 test plan / 同流程要 R15 vs R18 比對 → 腳本模式
- 使用者明確指定 `--script` flag → 腳本模式（覆蓋預設）

## 進度紀錄機制（rate limit 與 cross-session resume）

跑測試 + 上傳 + 發 comment 三階段都吃 token，**跑到一半 rate limit 時若閒置等待 reset 反而最貴** — Anthropic 是 5 小時滾動視窗，session 閒置會讓 prompt cache（5 分鐘 TTL）過期，恢復時整個 SKILL.md 與 cjs / 測試步驟都得重讀，瞬間燒幾萬 token 重建 cache。

正確策略：**rate limit 一到就 `/clear` 開新 session**，下次用 `--resume` 旗標續跑。

### progress.md 結構

`.claude/{ISSUE_KEY}-progress.md`，由 skill 在「跑測試前」建檔：

```markdown
## Test Run Progress — ERPD-XXXX

Mode: script  (or interactive)
Variant: r18
Started: 2026-05-08 14:00
Last update: 2026-05-08 14:45

### Phase A: 跑測試
- [x] 01 page-loaded
  - Status: PASS
  - Screenshot: .claude/ERPD-XXXX-temp/r18/01-page-loaded.png
  - Run at: 2026-05-08 14:23
- [x] 02 click-add
  - Status: PASS
  - Screenshot: .claude/ERPD-XXXX-temp/r18/02-click-add.png
  - Run at: 2026-05-08 14:24
- [ ] 03 fill-form   ← 下次 --resume 從這裡接
- [ ] 04 submit
- [ ] 05 verify

### Phase B: Jira 截圖上傳
- [x] 01-page-loaded.png → attachment id 12345
- [x] 02-click-add.png → attachment id 12346
- [ ] 03-fill-form.png    （尚未跑到，暫不 upload）

### Phase C: Jira inline comment
- [ ] comment posted    （所有 step 跑完才發）
```

### 寫入時機

- **Phase A 開始前**：建檔，所有 step 列為 `[ ]` 未勾選（從測試步驟清單推得）
- **Phase A 每跑完一個 step**：對應條目從 `[ ]` 改 `[x]`，填 status / screenshot / run at
- **Phase B 每張上傳完**：對應條目改 `[x]`，記下 attachment id
- **Phase C comment 發完**：對應條目改 `[x]`

### 續跑模式（`--resume`）

帶 `--resume` 旗標啟動時：
1. 進入**步驟 0.5**：讀 `.claude/{ISSUE_KEY}-progress.md`
2. **Phase A 仍有 `[ ]`** → 從第一個未勾選 step 續跑
3. **Phase A 全 `[x]` + Phase B 仍有 `[ ]`** → 跳過 Phase A 直接補上傳
4. **Phase A、B 都全 `[x]` + Phase C 仍 `[ ]`** → 直接發 comment
5. **三 Phase 全 `[x]`** → 提示使用者「已完成，無事可做」

### 模式對應

| 模式 | progress.md 寫入端 |
|---|---|
| 互動模式 | 主 context（Edit 工具）每 step 結束時更新 |
| 腳本模式 | cjs 內 `step()` wrapper 用 `updateProgressMd()` 函式（同 cup-build-test 設計，見步驟 S3 cjs 範例）|

Phase B / Phase C 不論模式都由主 context Edit。

### 為什麼要顯式 `--resume` 旗標

避免兩種誤觸發：
1. **舊 progress.md 殘留**（上次失敗忘了清，新需求被誤判為續跑）
2. **同 issue 不同測試範圍**（測試步驟 .md 改了，舊 progress 過時）

無 `--resume` 旗標但偵測到 progress.md 存在時，**步驟 0.5 問使用者**（不自動決定）。

## 共用先決條件（先確認，缺哪項先補哪項）

| 項目 | 取得方式 |
|------|---------|
| Atlassian API token | https://id.atlassian.com/manage-profile/security/api-tokens — **存到 `.env.local` 的 `ATLASSIAN_API_TOKEN`，不在對話貼明文** |
| Atlassian email | 對應 Jira 帳號 email — **存到 `.env.local` 的 `ATLASSIAN_EMAIL`** |
| Jira site | 例如 `jubo-health.atlassian.net` — 存到 `.env.local` 的 `ATLASSIAN_SITE`（不含 https 前綴） |
| dev server 已啟動 | `npm run dev` 或專案對應命令 |
| 登入帳密 | frontend 根目錄有 `.env.local`，含 `BASE_URL` / `E2E_ACCOUNT` / `E2E_PASSWORD` / `E2E_TYPE`（gitignored） |
| 測試步驟來源 | `.claude/{ISSUE_KEY}.md` / `.claude/{ISSUE_KEY}-test-plan.md` 的「測試步驟」section |
| Playwright 可用 | 互動模式：playwright MCP plugin；腳本模式：`playwright` npm package（`npx playwright install chromium` 一次） |

**Token / email**：一律存 `.env.local`，**不在對話中貼明文**。token 用完仍提醒使用者去 Atlassian 後台撤銷。

### `.env.local` 完整範例

```
# --- E2E 登入 ---
BASE_URL=http://localhost:3000                              # local dev server
STAGING_URL=https://lunastaging.compal-health.com          # staging（release-e2e workflow 同源）
E2E_ACCOUNT=<帳號>
E2E_PASSWORD=<密碼>
E2E_TYPE=e

# --- Jira API（jira-test-report skill 用）---
ATLASSIAN_EMAIL=<your-email@example.com>
ATLASSIAN_API_TOKEN=<從 id.atlassian.com 申請；於 YYYY-MM-DD 到期>
ATLASSIAN_SITE=jubo-health.atlassian.net

# --- 業務 fixture（依 cjs 需求補；本地與 CI generic 名稱對齊）---
# CASE_ID=<已結案居服個案 id；LVB-7963 用>
# DAYCARE_CASE_ID=<已結案日照個案 id；LVB-7963 B 區用>
```

`.gitignore` 必含 `.env.local`，缺則 append。skill 執行時用 dotenv 或簡易 parser 讀入 `process.env`，**禁止**把 token / 密碼寫入任何 commit 進 git 的檔案。

---

## 步驟 0.5：進度檔偵測（cross-session resume）

**模式 1、2 都跑此步驟**，在 issue key 確定後（步驟 1 / S1 之後）執行：

1. 檢查 `.claude/{ISSUE_KEY}-progress.md` 是否存在
2. **不存在** → 走完整流程（建檔在跑測試前）
3. **存在 + 帶 `--resume` 旗標** → 進入續跑：
   - 讀 progress.md，依 Phase A/B/C 各自的勾選狀態決定從哪裡接
   - Phase A 用 `RESUME_FROM_IDX={N}` 環境變數傳給 cjs（腳本模式）；互動模式則由主 context 跳過已 `[x]` 的 step
4. **存在但無 `--resume` 旗標** → **問使用者**：

   ```
   ⚠️  偵測到既有進度檔：.claude/ERPD-XXXX-progress.md
       最後更新：2026-05-08 14:45
       Phase A: 5 / 8 step 完成
       Phase B: 5 / 5 上傳完成
       Phase C: 尚未發 comment

   選擇：
     [1] 續跑（等同 --resume）
     [2] 刪除舊檔，重跑完整流程
     [3] 中止，我要手動檢查
   ```

---

## 模式 1：互動模式（Playwright MCP）

### 步驟 1：拿 issue key

```bash
git branch --show-current | grep -oE '[A-Z]+-[0-9]+' | head -1
```

取不到就問使用者。

### 步驟 2：驗證 token

從 `.env.local` 讀 `ATLASSIAN_EMAIL` / `ATLASSIAN_API_TOKEN` / `ATLASSIAN_SITE`，組 Basic auth header 打 `https://{ATLASSIAN_SITE}/rest/api/3/myself`，回 displayName 即過。失敗時提示使用者更新 `.env.local`（**不要**請使用者貼 token 到對話）。

### 步驟 3：讀測試步驟

從 `.claude/{ISSUE_KEY}.md` 拿「## 測試步驟」section。沒這個檔就讓使用者口述步驟。

### 步驟 4：取得登入態（API 模式，無人為介入）

local dev 與 CI 都統一走 API 登入：

1. **檢查 `.env.local`** 在 frontend 根目錄存在；缺則提示使用者依「`.env.local` 完整範例」段建立（含 E2E + Atlassian 兩組 keys）
2. **確認 `.gitignore` 含 `.env.local`**，缺則 append 並提示
3. **互動模式**：透過 `mcp__plugin_playwright_playwright__browser_run_code_unsafe` 呼叫 `helpers/login.cjs::authStateFromApi` 直接取 storageState，無需手動填帳密
4. **腳本模式**：cjs 內 `launchBrowser({ login: env.login })` 自動處理，env.login 由 `helpers/env.cjs::parseEnv` 從 env var 組合
5. **安全紀律**：密碼只放 `.env.local` 或 macOS Keychain，**不在對話中分享**、不寫進 cjs。skill 看到密碼字串立即中止

### 步驟 5：跑測試 + 截圖

依測試步驟逐項操作，每步存截圖到專案根目錄下 **暫存資料夾**（不能在 frontend 之外，Playwright MCP 有 root 限制）：

```
rm -rf {ISSUE_KEY}-temp       # 自 v2.4.1 起強制：清除上一次 FAIL/重跑留下的 stale 截圖
mkdir -p {ISSUE_KEY}-temp
filename: {ISSUE_KEY}-temp/01-xxx.png, 02-xxx.png, ...
```

命名規則：`{流水號}-{語意描述}.png`，流水號保 2 位數方便 sort。

**為什麼跑前必清空**：step 命名若在不同 run 之間改名（例如 `04-A4-下拉搜尋鄧候選.png` 改 `04-A4-下拉搜尋陳候選.png`），temp dir 會同時留兩個版本。Phase B 上傳前若沒手動過濾，會把 stale 截圖一起傳到 Jira，造成 inline comment 與舊截圖混淆。`--resume` 模式例外，依 progress.md 跳過已完成 step（不要清 temp）。

**Token 節省鐵則**（互動模式必遵守）：
- `browser_take_screenshot` **必須**指定 `filename` 參數，否則回 base64 進 context（單張可吃 5,000–20,000+ tokens）
- `browser_snapshot` 用 `depth` 參數限制 a11y tree 層級，或用 `filename` 存檔不入 context
- 不要對同個畫面重複 snapshot

**Progress.md 寫入（cross-session resume）**：
- 跑測試前先建 `.claude/{ISSUE_KEY}-progress.md`，把所有測試步驟列為 `[ ]`
- 每跑完一個 step（截完圖後），用 Edit 工具把對應條目改 `[x]` 並填 Status / Screenshot / Run at
- `--resume` 模式下：先讀 progress.md，跳過所有已 `[x]` 的 step，從第一個 `[ ]` 開始

### 步驟 6–9：見「共用後段」

---

## 模式 2：腳本模式（生成 .cjs + node 執行）

### 步驟 S1：拿 issue key + 驗證 token

同互動模式步驟 1–2。

### 步驟 S2：讀測試步驟 + 確認 .env.local 存在

```bash
test -f .env.local || echo "NEED_ENV_LOCAL"
# E2E 登入必要 keys
grep -E '^(BASE_URL|E2E_ACCOUNT|E2E_PASSWORD|E2E_TYPE)=' .env.local | wc -l   # 應為 4
# Jira API 必要 keys（Phase B/C 才需要；只跑 Phase A 可暫缺）
grep -E '^(ATLASSIAN_EMAIL|ATLASSIAN_API_TOKEN|ATLASSIAN_SITE)=' .env.local | wc -l   # 應為 3
```

若無，提示使用者依「`.env.local` 完整範例」段建立。**absolute 不要從對話索取密碼或 token**。

### 步驟 S3：生成 Playwright 腳本

寫到 `.claude/{ISSUE_KEY}-test.cjs`（用 Write 工具，不要用 ctx_execute）：

#### Helpers 架構與 API 速查（v2.4.4+ 全面 helpers 化）

`~/.claude/skills/jira-test-report/helpers/` 是 jira-test-report skill 自帶的 helpers，**獨立可運作不依賴 cup-build-test**。透過 `~/.claude/skills/cup-build-test/scripts/sync-helpers.sh` 從 master（`~/.claude/skills/cup-build-test/helpers/`）同步以避免分歧。

骨架預設 `require` 整套 helpers（無需手動加），API 速查：

| Helper | 主要 API | 用途 |
|---|---|---|
| `env.cjs` | `parseEnv({ issueKey, entryPath })` | 解析 BASE_URL / HEADLESS / SCREENSHOT_BASE_DIR / login / fixture placeholder 等成 `env` 物件 |
| `browser.cjs` | `launchBrowser({ headless, login })` / `attachConsoleCollector(page, errors)` | 開瀏覽器 + API 登入（內部走 `loginInContext`，含 host-only token cookie + `x-request-from: web` header）；console error 收集 |
| `step.cjs` | `createStepRunner({ screenshotDir, progressPath, only, resumeFrom, stopOnFail })` → `{ step, skipStep, waitStable, getResults }` | 5 參數中文化 step、自動截圖、progress.md 寫入、ONLY / RESUME_FROM 過濾 |
| `modal.cjs` | `waitAndDismissOnEntry(page)` / `dismissAnnouncement(page)` / `ensureCleanState(page)` | 進入頁面後 dismiss 公告 modal（多輪重試）；mutation step 入口防殘留 |
| `confirmDialog.cjs` | `confirmYes(page)` / `confirmNo(page, { scope })` | 二次確認對話「是/否」「確認/取消」統一處理 |
| `evidence.cjs` | `injectEvidence(p, ev)` / `clearEvidence(p)` / `expandSelectAsListbox(selectLocator)` | 三合一規範必備：右上角證據面板 + select 強制展開為 listbox（規範 (a)） |
| `report.cjs` | `writeResultsJson(dir, payload)` / `printSummary(results, errors)` / `exitCodeForResults(results)` | finally 收尾統一處理 |
| `login.cjs` | `loginParamsFromEnv()` / `loginInContext(...)` | 已被 `parseEnv` 與 `launchBrowser` 包裝，cjs 通常不直接 require |
| `orgGuard.cjs` | `switchOrg(page, { keyword, expectedDisplay, waitMs })` / `currentOrg(page)` / `DEFAULT_ORG` | luna 機構切換：jira-test-report 例外 case 屬非預設機構（如豐原醫院）時，A1 前切過去、finally 切回；切後自動 navigate `/case/` 避 SSO 踢 + dismiss 公告 modal + 斷言右上角 `expectedDisplay` |

**首次 setup**（一次性）：

```bash
cd ~/.claude/skills/jira-test-report/helpers
npm install                       # 拉 playwright
npx playwright install chromium   # 共用 ~/Library/Caches/ms-playwright/
```

**修 helper 的方向**：先改 master `~/.claude/skills/cup-build-test/helpers/`，再跑 `sync-helpers.sh` 推到 jira-test-report mirror 與 `e2e/release-tests/_helpers/`。直接改 mirror 會在下次 sync 被覆蓋。

完整 API 參考：`~/.claude/skills/cup-build-test/SKILL.md`「Helper API 速查」段。

> ⚠️ **既有 cjs 應升級** — v2.4.3 以前的 cjs 大量 inline 重複邏輯（step / evidence / progress / results 寫入），下次回歸時建議改寫對齊 v2.4.4 骨架；新產 cjs 一律走 helpers。

---

**腳本骨架**（自 v2.4.4 起全面 helpers 化，對齊 LVB-7963 風格）：

```javascript
// .claude/{ISSUE_KEY}-test.cjs
// @ts-check
// {ISSUE_KEY} {一句話描述} 回歸測試腳本
//
// 此檔由 /jira-test-report skill 階段 S3 自動產出，共用邏輯由 jira-test-report/helpers
// 提供（env / step / modal / browser / report / evidence），修 bug 或加新功能優先改 helpers/。
//
// Root cause（見 frontend/.claude/{ISSUE_KEY}.md）：
//   {root cause 一兩行摘要}
//
// 修正：
//   - {file path}：{修正摘要}
//
// 驗證情境：
//   - {頁面路徑}
//   - 預期：{預期結果}
//
// 用法（不需 npm install playwright，helpers/ 已自帶）：
//   .claude/ 階段（skill 產出後本機驗證）：
//     node .claude/{ISSUE_KEY}-test.cjs
//   release-tests 階段（publish 後本機對 staging 驗證）：
//     cd frontend
//     set -a; source .env.local; set +a
//     BASE_URL=$STAGING_URL node ../e2e/release-tests/{ISSUE_KEY}.cjs
//
// 環境變數：
//   HEADLESS=false               看畫面 debug
//   STOP_ON_FAIL=true            遇 FAIL 即停
//   ONLY=A1.1                    只跑指定 step
//   RESUME_FROM=A3.1             從指定 step 接續
//   CUP_HELPERS_DIR=<path>       覆寫 helpers 路徑（預設 ~/.claude/skills/jira-test-report/helpers）
//
// 前置：
//   1. API 登入用 env：BASE_URL / E2E_ACCOUNT / E2E_PASSWORD / E2E_TYPE
//      本地走 .env.local（set -a; source .env.local），CI 走 GitHub Secrets
//   2. {fixture env var}（如 CASE_ID）已 hardcode staging default，可 env 覆寫
//
// Exit codes：
//   0 = 全 PASS / 1 = 有 FAIL / 3 = AUTH_EXPIRED / 4 = MISSING_ENV

const path = require('path');
const os = require('os');

// STEP 01: 載入 helpers（.claude/ 階段預設指向 jira-test-report skill；publish 到 release-tests 後改指 _helpers vendor）
const HELPERS_DIR = process.env.CUP_HELPERS_DIR
  || path.join(os.homedir(), '.claude/skills/jira-test-report/helpers');

const { parseEnv } = require(path.join(HELPERS_DIR, 'env.cjs'));
const { createStepRunner } = require(path.join(HELPERS_DIR, 'step.cjs'));
const { waitAndDismissOnEntry, ensureCleanState } = require(path.join(HELPERS_DIR, 'modal.cjs'));
const { launchBrowser, attachConsoleCollector } = require(path.join(HELPERS_DIR, 'browser.cjs'));
const { writeResultsJson, printSummary, exitCodeForResults } = require(path.join(HELPERS_DIR, 'report.cjs'));
const { injectEvidence, clearEvidence, expandSelectAsListbox } = require(path.join(HELPERS_DIR, 'evidence.cjs'));

// STEP 01.05: Staging fixture（hardcode 預設值，本地驗證可 env 覆寫）
//   {fixture 來源說明 — 例：「已結案」狀態個案，於 staging 環境穩定存在；過期請 PR 更新}
const STAGING_CASE_ID = '<paste-staging-case-id>';
process.env.CASE_ID = process.env.CASE_ID || STAGING_CASE_ID;

// STEP 02: 解析環境變數（parseEnv 統一處理 BASE_URL / HEADLESS / SCREENSHOT_DIR / PROGRESS_PATH / login 等）
const env = parseEnv({
  issueKey: '{ISSUE_KEY}',
  entryPath: '/path/to/entry/{caseId}',   // {caseId} placeholder 會自動代入 process.env.CASE_ID
});

// STEP 03: 共用 selector 與預期值定義（依測試情境填）
// 例：
// const MODAL_OPEN_SEL = '.modal.in, .modal.show';        // R15 .in + R18 .show 雙覆蓋
// const EXPECTED_OPTIONS = ['選項 A', '選項 B'];

(async () => {
  // STEP 01: 環境準備 & 開瀏覽器
  require('fs').mkdirSync(env.screenshotDir, { recursive: true });
  // 開瀏覽器 + API 登入：launchBrowser 內部走 loginInContext，cookies 直接進 context jar
  //   含 host-only token cookie + x-request-from: web header（見 S3 準則「登入用 launchBrowser」）
  //   啟動第一行應印 `[login] OK 200 — N cookies: token,lunastaging.sid`
  const { browser, page } = await launchBrowser({
    headless: env.headless,
    login: env.login,
  });

  /** @type {string[]} */
  const consoleErrors = [];
  attachConsoleCollector(page, consoleErrors);

  // STEP 02: 建立 step runner（5 參數中文化簽名、自動截圖、progress.md 寫入、ONLY / RESUME_FROM 過濾）
  const { step, skipStep, waitStable, getResults } = createStepRunner({
    screenshotDir: env.screenshotDir,
    progressPath: env.progressPath,
    only: env.only,
    resumeFrom: env.resumeFrom,
    stopOnFail: env.stopOnFail,
  });

  try {
    // ========================================================================
    // A. {場景一名稱}
    // ========================================================================

    // STEP 03: 進入頁面（waitUntil 一律 'domcontentloaded'，禁 'networkidle'，見 S3 準則）
    await page.goto(env.baseUrl + env.entryPath, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitStable(page, 1000);

    // STEP 03.01: AUTH_EXPIRED fail-fast — token 失效不要拖到 step 才爆
    if (/\/login/.test(page.url())) {
      console.error(`AUTH_EXPIRED: redirected to ${page.url()}.`);
      process.exit(3);
    }

    // STEP 03.02: dismiss 公告 modal（helpers 內建多輪重試捕捉晚到 modal）
    await waitAndDismissOnEntry(page);

    // === 測試步驟區塊（依 test plan 填充）===
    // step 呼叫一律 5 參數中文版（v2.3.2+ 強制）：
    //   step(page, caseId, '中文短名', '中文長描述', async (p) => {...})
    // 每個斷言 step 必須三合一：程式邏輯 throw + 真實 UI 操作或視覺變更 + injectEvidence overlay（見 S3.5）

    await step(page, 'A1.1', '頁面載入', '進入入口頁，等關鍵 anchor 渲染', async (p) => {
      // STEP 01: 真實 UI 等待
      await p.waitForSelector('.your-anchor-selector', { timeout: 15000 });
      await waitStable(p, 500);
      // STEP 02: evidence — 標頁面狀態
      const ok = await p.locator('.your-anchor-selector').first().isVisible();
      await injectEvidence(p, {
        title: 'A1.1 頁面載入',
        actual: { url: p.url(), anchorVisible: ok },
        conclusion: ok ? '頁面已渲染' : '頁面未渲染',
        ok,
      });
    });

    // 範例：純資料斷言 step 用 expandSelectAsListbox 補 UI 證據（規範 (a)）
    // await step(page, 'A2.1', '驗證下拉完整列表', '把 select 強制 size=N 展開為 listbox，肉眼可數所有 option', async (p) => {
    //   await clearEvidence(p);
    //   const selectLocator = p.locator('select.form-control').first();
    //   await expandSelectAsListbox(selectLocator);
    //   const actual = await selectLocator.evaluate((el) =>
    //     Array.from(/** @type {HTMLSelectElement} */ (el).options).map((o) => (o.textContent || '').trim()));
    //   const missing = EXPECTED_OPTIONS.filter((e) => !actual.includes(e));
    //   await injectEvidence(p, {
    //     title: `A2.1 完整 ${actual.length} 項`,
    //     actual, expected: EXPECTED_OPTIONS,
    //     conclusion: missing.length === 0 ? '完全覆蓋' : `缺少 ${JSON.stringify(missing)}`,
    //     ok: missing.length === 0,
    //   });
    //   if (missing.length > 0) {
    //     throw new Error(`下拉缺少：${JSON.stringify(missing)}`);
    //   }
    // });

    // === 測試步驟區塊結束 ===
  } finally {
    // STEP 05: 收尾 — 寫 _results.json + 印 summary + 關 browser + 回 exit code
    const results = getResults();
    writeResultsJson(env.screenshotDir, {
      issueKey: env.issueKey,
      variant: env.variant,
      baseUrl: env.baseUrl,
      results,
      consoleErrors,
    });
    printSummary(results, consoleErrors);
    await browser.close();
    process.exit(exitCodeForResults(results));
  }
})().catch((err) => {
  console.error('FATAL:', err);
  process.exit(1);
});
```

**寫腳本準則**（AI-parsing 結構化，v2.4.7+；每條 rule + why + how/banned，歷史 context 保留作 reason）：

```
STEP-PER-ASSERTION:
  rule: 一個 step() = 一個測試斷言
  screenshot: 只在 step 結束時拍一次（含 fail 也拍）
  banned: step 中間額外截圖

SELECTOR-PRIORITY:
  order: data-testid > getByRole > 文字 > class > nth-child（最後才 nth-child）

LOCATOR-CHAIN:
  rule: page.locator(...) 鏈式呼叫
  banned: 存中間變數（locator 是 lazy 的）

WAIT-STRATEGY:
  use: waitForSelector | waitForLoadState
  banned: page.waitForTimeout(N) 死等

MUTATION-SAFETY:
  rule: 不可逆操作（建立 / 刪除）必 try/catch 包
  why: 避免污染下次測試資料

EDIT-STATE-DETECTION (v2.4.1+):
  rule: 進入子頁/編輯狀態預設 DOM-driven，不要 URL-driven
  why: SPA inline 編輯（同 URL 開 modal / 切 panel / 列 inline 編輯）URL 通常不變，url !== originalUrl 永遠 false
  how: 靠 DOM 訊號（表單欄位 mount / 預期按鈕「儲存」「取消」出現 / typeahead mount）
  first-time: HEADLESS=false 觀察一次，luna FE 多數頁面屬此模式但少數會 push history state
  example: const enteredEdit = (await p.locator('.bootstrap-typeahead input').count()) > 0;

THIRD-PARTY-SELECTOR (v2.4.1+):
  rule: 第三方元件 selector 寫前先 grep 實際版本
  why: react-bootstrap-typeahead v1.x=.bootstrap-typeahead / v4+=.rbt-，class 名差很大
  how: grep <project>/node_modules/<lib>/lib/*.js 或 package.json 確認版本

LOGIN (v2.4.3+，v2.4.4 改走 parseEnv 封裝):
  rule: launchBrowser({ login: env.login })
  banned: authStateFromApi + storageState
  why: luna staging token cookie 是 host-only（無 Domain 屬性），storageState 序列化會漏 → SSO redirect icaretest*.compal-health.com → 30s timeout（症狀像 wait condition 問題實為登入機制問題，可從 page.title() 看到 "Loading https://icaretest..." 確認）
  how: browser.cjs::launchBrowser({ login }) 內走 loginInContext，cookies 直接寫入 BrowserContext jar（含 host-only），自動帶 x-request-from: web header 後端才發 token cookie
  parseEnv: 已從 E2E_ACCOUNT / E2E_PASSWORD / E2E_TYPE 組好 env.login，cjs 不再直接 require loginParamsFromEnv
  verify: 啟動第 1 行 console = "[login] OK 200 — N cookies: token,lunastaging.sid"（token 必在 list）
  deprecated: authStateFromApi（見 _helpers/login.cjs:11-13）

GOTO-WAIT (v2.4.2+):
  rule: page.goto waitUntil='domcontentloaded'
  banned: 'networkidle'
  why: R18 SPA 背景 GA4 / tracking / polling / WebSocket 持續活動，networkidle（500ms 無 network request）多數頁面達不到，CI 必 30s timeout；同寫法 /homecareCaseClose 過、/supervisorVisitRecord fail，行為不穩定
  how: domcontentloaded 等 DOM 載入後，真正 ready 條件靠 waitAndDismissOnEntry + 各 step waitFor({ state: 'visible' })（Playwright 對 SPA 官方建議）
  fail-fast: page.goto 後立刻加 if (/\/login/.test(page.url())) { console.error('AUTH_EXPIRED'); process.exit(3); } — token 失效不要拖到 step 才爆

STEP-CHINESE (v2.3.2+，強制):
  rule: 5 參數中文版 step(page, caseId, '中文短名', '中文長描述', async (p) => {...})
  example: step(page, 'A1.1', '結案頁載入', '進入個案結案頁，等歷史紀錄區塊載入', async (p) => {...})
  why: 截圖檔名 / Jira inline comment / progress.md / GitHub Actions log 都吃 name + description，中文化讓非技術 stakeholder 看 release-e2e workflow 結果就能理解每步在做什麼
  helper: step.cjs createStepRunner 已支援 5 參數簽名向後相容（4 參數舊用法 description 為空）

ASSERTION-EVIDENCE (v2.4.0+，強制):
  rule: 每個 step 三合一（程式邏輯斷言 + 真實 UI 操作/視覺變更 + injectEvidence overlay）
  anti-pattern: 純資料比對 step（截圖前後雷同）
  ref: S3.5 專段

HELPERS-ONLY (v2.4.4+):
  rule: cjs 主體只放測試 step 邏輯與業務專屬 selector / fixture / 預期值
  banned: cjs 內 inline step() runner / updateProgressMd / injectEvidence / writeResultsJson 等已抽 helper 的功能
  helper-edit: 改 master ~/.claude/skills/cup-build-test/helpers/ → sync-helpers.sh，不直接改 release-tests/_helpers 或 jira-test-report/helpers
```

### 步驟 S3.5：斷言截圖三合一規範（v2.4.0+ 強制）

**問題背景**：截圖測試報告同時有兩個目的 — **驗證程式邏輯**（陣列比對、欄位順序、API 回傳）與**驗證 UI 行為**（按鈕真的能點、選項真的能選、Modal 真的會開）。若 step 只做程式邏輯比對（純 `array.includes()` / `JSON.stringify()` 比對），雖然 PASS 但截圖會跟前一步一模一樣，**非工程 stakeholder 看 Jira / GitHub Actions artifact 無法判讀斷言依據**，等同沒測。

LVB-7963 A3.2~A3.4 是反面教材：「必要選項皆存在」「完整 14 項皆存在」「順序正確」三步截圖完全雷同，因為三步都只比對 A3.1 收進來的 `actualOptions` 陣列，沒有任何 page 操作。

**三合一規範**：每個 step 必須同時滿足下列三點：

| 要素 | 內容 | 失敗例 |
|---|---|---|
| 1. 程式邏輯斷言 | `throw new Error(...)` 條件式必須能被自動化判讀；錯誤訊息含「實測 vs 預期」對比 | `expect(...)` 抽象包裝、err 只 throw 「失敗」沒寫差異 |
| 2. 真實頁面操作或視覺變更 | DOM 至少有一處可被截圖識別的變化（點擊後狀態切換、屬性注入、focus、scroll、hover、樣式變更等） | 純讀資料、不對 page 做任何操作 |
| 3. 斷言結論可視化 | 注入 evidence overlay：固定位置 div，列出實測值 / 預期值 / 結論（✅/❌）；截圖直接呈現「斷言依據與結果」 | 結論只在 stdout、Jira 看不到 |

**純資料斷言 step 強制重構**：若 step 本質是「對 JS 陣列 / 物件做比對」，必須用下列方式之一補回頁面證據：

- (a) **強制 native 元素展開呈現**：例如 `<select>` 改 `size = options.length` 變 listbox 直接看見所有選項；`<details>` 改 `open=true` 展開
- (b) **逐項真實 UI 互動**：例如要驗證 4 個必要選項都能選，就 `selectLocator.selectOption(value)` 逐一選一次，最後留在最後一個選項狀態
- (c) **highlight + 標號**：用 `evaluate` 在 DOM 上加 outline / badge 標出比對的元素
- (a/b/c) 任選一個必須伴隨 evidence overlay 注入

**evidence overlay 由 `evidence.cjs` helper 提供**（自 v2.4.4 起，三個 API 都在 `_helpers/evidence.cjs` 與 `jira-test-report/helpers/evidence.cjs`，無需 inline）：

| API | 簽名 | 用途 |
|---|---|---|
| `injectEvidence(p, ev)` | `ev: { title, actual, expected?, conclusion, ok }` | 右上角注入證據面板，紅綠框依 `ok`；同 step 內可重複呼叫覆寫 |
| `clearEvidence(p)` | - | 移除證據面板（下一個 step 開頭 / mutation 前用） |
| `expandSelectAsListbox(selectLocator)` | - | 把 native `<select>` 強制 `size = options.length` 變 listbox，截圖肉眼可數所有 option（搭配三合一規範 (a)） |

骨架已 `require` 此三個 API：

```javascript
const { injectEvidence, clearEvidence, expandSelectAsListbox } = require(path.join(HELPERS_DIR, 'evidence.cjs'));
```

**LVB-7963 範本重構（示範三合一）**：

```javascript
// A3.2 必要選項皆可選取 — 程式邏輯 + UI 逐一選取 + evidence
await step(page, 'A3.2', '必要選項皆可選取', '逐一在下拉中選取 4 個必要選項（value 9/10/11/12），確認 UI 接受', async (p) => {
  const selectLocator = p.locator(MODAL_SELECT_SEL).first();
  const requiredValues = ['9', '10', '11', '12'];
  // STEP 01: 真實 UI 操作 — 逐一 selectOption（不只是 DOM 存在，UI 可選才算）
  for (const v of requiredValues) {
    await selectLocator.selectOption(v);
    await waitStable(p, 150);
  }
  // STEP 02: 程式邏輯斷言
  const missing = findMissingOptions(actualOptions, REQUIRED_NEW_OPTIONS);
  // STEP 03: evidence overlay（不論 pass / fail 都注入）
  await injectEvidence(p, {
    title: 'A3.2 必要選項皆可選取',
    actual: actualOptions.filter((o) => REQUIRED_NEW_OPTIONS.includes(o)),
    expected: REQUIRED_NEW_OPTIONS,
    conclusion: missing.length === 0
      ? `4 個必要選項皆出現於下拉且 UI 可選（已逐一 selectOption 驗證）`
      : `缺少 ${missing.length} 項：${JSON.stringify(missing)}`,
    ok: missing.length === 0,
  });
  if (missing.length > 0) {
    throw new Error(`結案原因下拉缺少必要選項：${JSON.stringify(missing)}`);
  }
});

// A3.3 完整 14 項皆存在 — 把 select 展開成 listbox 視覺呈現（用 evidence.cjs::expandSelectAsListbox）
await step(page, 'A3.3', '完整 14 項列表展示', '將 select 強制展開為 listbox 視覺呈現 14 項，搭配 evidence 標示比對結果', async (p) => {
  // STEP 01: 真實 UI 變更 — helper 一行搞定（內部就是 s.size = s.options.length + 樣式）
  const selectLocator = p.locator(MODAL_SELECT_SEL).first();
  await expandSelectAsListbox(selectLocator);
  // STEP 02: 程式邏輯斷言
  const missing = findMissingOptions(actualOptions, EXPECTED_FULL_ORDER);
  // STEP 03: evidence
  await injectEvidence(p, {
    title: `A3.3 完整 ${actualOptions.length} 項`,
    actual: actualOptions,
    expected: EXPECTED_FULL_ORDER,
    conclusion: missing.length === 0
      ? `實測 ${actualOptions.length} 項 / 預期 ${EXPECTED_FULL_ORDER.length} 項，完全覆蓋`
      : `缺少 ${missing.length} 項：${JSON.stringify(missing)}`,
    ok: missing.length === 0 && actualOptions.length === EXPECTED_FULL_ORDER.length,
  });
  if (missing.length > 0) {
    throw new Error(`結案原因下拉缺少完整選項：${JSON.stringify(missing)}`);
  }
});
```

**Cleanup 鐵則**（自 v2.4.5 起強制，AI-parsing 結構化 v2.4.7+）：

```
CLEANUP-EVIDENCE-BEFORE-UI:
  rule: 同 step 內 injectEvidence 之後若還有任何 UI 互動，動作前必須 await clearEvidence(p)
  triggers: closeModal / .click() / .fill() / .selectOption() 等任何點按互動
  why: #e2e-evidence-panel 注入在 viewport 右上角 fixed 定位，Modal 寬度大時會 intercept pointer events → Playwright click 60 次 retry 全被擋 → 30s timeout step FAIL（功能本身沒 bug、人工點得下去）
  case: ERPD-11841 A8「重開 selectedCase 為空」injectEvidence 後直接 closeModal(p) → staging 100% 重現 timeout，error log = "<div>…</div> from <div id='e2e-evidence-panel'>…</div> subtree intercepts pointer events"
  inverse-evidence: 同 cjs A4 / A7 PASS 因 closeModal 在 injectEvidence「之前」執行，順序不同沒踩到
```

正確 pattern 範例：

```javascript
// case 1: step 結尾要 closeModal — injectEvidence 後、closeModal 前 clearEvidence
await step(page, 'A8', '重開selectedCase為空', '...', async (p) => {
  await clearEvidence(p);              // step 開頭清前一輪
  await openModalAndCheck(p);
  await injectEvidence(p, { ... });    // 注入證據
  if (failed) { throw new Error(...); }
  await clearEvidence(p);              // ← 鐵則：closeModal 前必清
  await closeModal(p);
});

// case 2: step 結尾要 cancel modal — 同理
await step(page, 'A4.1', '取消 Modal 不送出', '...', async (p) => {
  await clearEvidence(p);
  const cancelBtn = p.locator(MODAL_FOOTER_BTN_SEL).filter({ hasText: /取消|cancel/i }).first();
  await cancelBtn.click();
  await p.waitForSelector(MODAL_OPEN_SEL, { state: 'hidden', timeout: 5000 });
});
```

**Code review grep**（產出 cjs 後跑一次）：

```bash
# 找 injectEvidence 後緊接 UI 動作但中間沒 clearEvidence 的 step（人工複查每筆）
grep -A 20 'injectEvidence' <cjs-path> | grep -E 'closeModal|\.click\(|\.fill\(|\.selectOption\('
```

**自我檢核清單（產出 cjs 前過一次）**：

- [ ] 每個斷言 step 都有 `throw new Error(...)` 條件式（不是 silent 比對）
- [ ] 純資料 step 已用 (a)/(b)/(c) 之一補上 UI 證據
- [ ] 每個斷言 step 都有 `injectEvidence(p, {...})` 呼叫
- [ ] **同 step 內 `injectEvidence` 之後若還有 UI 動作（closeModal / click / fill / selectOption），動作前有 `clearEvidence(p)`**（v2.4.5+ 鐵則）
- [ ] 連續斷言 step 之間 evidence overlay 已 cleanup 或被覆寫
- [ ] error message 含「實測 vs 預期」對比，不只「失敗」

### 步驟 S3.6：機構切換（例外 case 才用，v2.4.6+）

**背景**：jira-test-report 多數 cjs 用預設機構（仁寶長照機構 / internal code `compal`）的 CASE_ID。少數 issue 為「只有特定機構特定 case_id 才能重現」的 bug，跑這類 cjs 需在 A1 前切到該機構、finally 切回，避免污染後續測試。

**何時要用 / 不用**（AI-parsing 結構化 v2.4.7+）：

```
USE-WHEN:
  case_id_non_compal: CASE_ID 不屬於 compal 機構（如豐原醫院、台南御宇）
  bug_org_specific: bug 只在特定機構參數 / 權限設定下可重現
SKIP-WHEN:
  case_id_compal: CASE_ID 屬 compal 預設機構 → 不用，省一個 step 開銷
```

**Helper API**：

```js
const { switchOrg, currentOrg, DEFAULT_ORG } = require(path.join(HELPERS_DIR, 'orgGuard.cjs'));
// DEFAULT_ORG = { keyword: 'compal', expectedDisplay: '仁寶長照機構' }
```

**切換邏輯**（helper 內建，AI-parsing 結構化 v2.4.7+）：

```
SWITCH-ORG-PIPELINE:
  step-1-shortcut: currentOrg(page) === expectedDisplay → noop（回 { switched: false }）
  step-2-open: 點 .list-dropdown-text 開 react-select dropdown
  step-3-filter: .Select-input input 填 keyword 過濾
  step-4-pick:
    primary: 結尾 "(${keyword})" 那筆（internal code 模式，dropdown text 格式 "display (code)"）
    fallback: 沒匹配且結果唯一 → 選唯一那筆（substring 唯一，如 keyword='豐原'）
    otherwise: throw 防選錯
  step-5-navigate: click option 觸發 navigation → wait waitMs（預設 10s）→ goto /case/ 避 SSO 踢到 icaretest → dismiss 公告 modal
  step-6-assert: currentOrg(page) === expectedDisplay，不符 throw
```

**cjs 整合範本**（推薦：A0 / Z9 step 結構讓切換動作也進 evidence）：

```javascript
const { switchOrg, DEFAULT_ORG } = require(path.join(HELPERS_DIR, 'orgGuard.cjs'));

// 該 issue 的 case_id 屬於豐原醫院機構
const REQUIRED_ORG = {
  keyword: '豐原',
  expectedDisplay: '衛生福利部豐原醫院附設居家長照機構',
};

(async () => {
  const { browser, page } = await launchBrowser({ ... });
  try {
    // ... goto + waitAndDismissOnEntry ...

    // A0: 切換到測試機構
    await step(page, 'A0', '切換到測試機構',
      `從預設 compal 切換到豐原醫院機構（${REQUIRED_ORG.expectedDisplay}），準備跑該機構的測試`,
      async (p) => {
        const r = await switchOrg(p, REQUIRED_ORG);
        await injectEvidence(p, {
          title: 'A0 切換到測試機構',
          actual: r,
          expected: { after: REQUIRED_ORG.expectedDisplay },
          conclusion: r.switched ? `切換成功：${r.before} → ${r.after}` : `已是目標機構，無需切換`,
          ok: true,
        });
      });

    // A1-AN: 正常測試步驟
    // ...

  } finally {
    // Z9: 切回預設機構（finally 強制執行，即使中間 step fail）
    try {
      await switchOrg(page, DEFAULT_ORG);
    } catch (e) {
      console.error('[orgGuard] 切回預設機構失敗：', e.message, '— 請手動切回避免後續測試污染');
    }
    // ... writeResultsJson + browser.close + exit ...
  }
})();
```

**簡化版**（不註冊成 step、純前後切換）：

```javascript
await switchOrg(page, REQUIRED_ORG);
try {
  // 測試 step
} finally {
  await switchOrg(page, DEFAULT_ORG);
}
```

**自我檢核**：

- [ ] CASE_ID 確認屬於 REQUIRED_ORG 機構（在該機構登入 staging 手動翻得到該 case）
- [ ] `REQUIRED_ORG.keyword` 帶 internal code（穩定）；非已知 code 時用顯示名片段且結果唯一
- [ ] `REQUIRED_ORG.expectedDisplay` 用切完後右上角 `.list-dropdown-text` 真正顯示的文字（**不是 dropdown 內的 text**，兩套 mapping 不同）
- [ ] cjs 用 try / finally 包，確保 Z9 切回不被中間 throw 跳過
- [ ] 跑前在本機 smoke 一次 round-trip，確認 `keyword` 能精準命中目標 option

### 步驟 S4：執行腳本

```bash
# 跑前清空 stale 截圖（v2.4.1+ 強制；--resume 模式例外）
rm -rf .claude/{ISSUE_KEY}-temp

# 預設 headless 跑（CI 或快速回歸）
node .claude/{ISSUE_KEY}-test.cjs

# 看著瀏覽器跑（debug 用）
HEADLESS=false node .claude/{ISSUE_KEY}-test.cjs

# R15 / R18 比對：跑兩次，截圖分開存
VARIANT=r15 BASE_URL=https://r15.example.com node .claude/{ISSUE_KEY}-test.cjs
VARIANT=r18 BASE_URL=http://localhost:3000 node .claude/{ISSUE_KEY}-test.cjs
```

stdout 每行一個 JSON 結果，最後一行是 summary。**不要** 把整個 stdout 倒進 context，用 `tail -20` 或讀 `_results.json`。

### 步驟 S5：分析結果

```bash
cat .claude/{ISSUE_KEY}-temp/{variant}/_results.json
```

只讀 summary + fail 項目的 error，**不要** 把所有截圖貼進來。

### 步驟 S6–S9：見「共用後段」

---

## 共用後段（兩種模式皆適用）

### 步驟 6：批量上傳到 Jira

從 `.env.local` 讀 `ATLASSIAN_EMAIL` / `ATLASSIAN_API_TOKEN` / `ATLASSIAN_SITE` 組 Basic auth：

```javascript
// node fetch + FormData
const auth = Buffer.from(`${process.env.ATLASSIAN_EMAIL}:${process.env.ATLASSIAN_API_TOKEN}`).toString('base64');
const site = process.env.ATLASSIAN_SITE;   // e.g. jubo-health.atlassian.net
const fd = new FormData();
fd.append("file", new Blob([buf], { type: "image/png" }), filename);
await fetch(`https://${site}/rest/api/3/issue/${issueKey}/attachments`, {
  method: "POST",
  headers: { Authorization: `Basic ${auth}`, "X-Atlassian-Token": "no-check" },
  body: fd,
});
```

逐張 upload，記下回傳的 attachment id（之後用來確認；inline 顯示其實只用 filename）。

**Phase B progress 寫入**：
- 每張上傳成功後，立刻 Edit `progress.md` 把 Phase B 區塊對應條目改 `[x]` 並記下 attachment id
- `--resume` 模式下：先讀 progress.md，跳過 Phase B 已 `[x]` 的截圖，避免重複上傳產生重複 attachment

### 步驟 7：發 inline comment（**核心 know-how**）

**關鍵**：MCP `addCommentToJiraIssue` 走 ADF v3，attachment ID 不能直接當 media id（會回 `ATTACHMENT_VALIDATION_ERROR`）。

**正確做法**：用 REST API v2 + wiki markup，後端會自動把 `!filename!` 轉成正確的 ADF mediaSingle node（含真正的 media UUID）。

```javascript
const wiki = [
  "h2. 自動化測試結果",
  "",
  "*環境*：localhost / 帳號 X　|　*結果*：N/N PASS",
  "----",
  "",
  "h3. 1. 步驟標題",
  "步驟說明文字",
  "!01-list-page.png|width=900!",
  "",
  "h3. 2. 下一步",
  "...",
  "!02-modal.png|width=900!",
  "",
].join("\n");

await fetch(`https://${process.env.ATLASSIAN_SITE}/rest/api/2/issue/${issueKey}/comment`, {
  method: "POST",
  headers: { Authorization: `Basic ${auth}`, "Content-Type": "application/json" },
  body: JSON.stringify({ body: wiki }),
});
```

注意：
- 一定要 **REST v2**（v3 不接受 wiki），endpoint 是 `/rest/api/2/issue/{key}/comment`
- `!filename.png|width=900!` 中 width 視截圖比例調整（一般 800-900 看得清）
- 表格用 `|| header || header ||` + `| cell | cell |`
- 分隔線 `----`
- 標題 `h2.` `h3.`（注意空格）
- 粗體 `*text*`

**腳本模式**的 comment 額外建議加上：
- 執行時間 / variant（r15 vs r18）
- console error 數量（從 `_results.json.consoleErrors.length`）
- fail step 的 error 訊息

**Phase C progress 寫入**：
- comment POST 成功後，立刻 Edit `progress.md` Phase C 從 `[ ]` 改 `[x]`，記下 comment id
- `--resume` 模式下：若 Phase C 已 `[x]` 表示上次已發過 — 此時應改 PUT comment（覆蓋）或 append 新 comment（依使用者意圖選一），**預設 append** 避免覆蓋人工修改

### 步驟 8：publish 到 release-tests（腳本模式強制）

腳本模式跑完 Phase A/B/C 後，**強制執行**將 cjs 轉成 release-tests 形態（讓 GitHub Actions release-e2e workflow 能跑）。互動模式不適用（未產 cjs）。

#### S8.1 機械改動清單（v2.4.4+ 大幅簡化）

把 `.claude/{ISSUE_KEY}-test.cjs` 複製到 `<repo-root>/e2e/release-tests/{ISSUE_KEY}.cjs`，因為 S3 骨架已全面 helpers 化，**publish 時實質只剩 1 點機械改動**：

| # | 項目 | 從 | 到 |
|---|---|---|---|
| 1 | HELPERS_DIR fallback | `path.join(os.homedir(), '.claude/skills/jira-test-report/helpers')` | `path.join(__dirname, '_helpers')`（vendor 副本，release-tests 自帶） |

其餘原本機械改動（chromium require、SCREENSHOT_DIR、.env.local 載入、progress.md silent、檔頭格式、step 中文化）**已由骨架預先處理**：

| 原 # | 原項目 | 為何不再需要 |
|---|---|---|
| 2 | chromium require | 骨架不直接 require playwright，全由 `launchBrowser` 從 helpers 內 node_modules 拿 |
| 3 | SCREENSHOT_DIR | `parseEnv` 自動處理 `SCREENSHOT_BASE_DIR` env var（v0.4.0+），CI 設 `SCREENSHOT_BASE_DIR=.` 即可 |
| 4 | .env.local 自動載入 | 骨架本來就不寫此邏輯（依 release-tests/README 規範由 shell 預先 `set -a; source .env.local; set +a`） |
| 5 | progress.md 寫入 | `createStepRunner` 內部已 silent（`progressPath` 對應檔案不存在時 noop） |
| 6 | 檔頭格式 | 骨架已為 LVB-7963 風格（root cause / 修正 / 驗證情境 / 用法 / 前置 / exit codes 6 段） |
| 7 | step 中文化 | 骨架已用 5 參數中文版 `step(page, caseId, '中文短名', '中文長描述', async (p) => {...})` |

**publish 後仍應 grep 一次自我檢查**：

- `grep "step(page," <release-tests>/{KEY}.cjs` 確認所有呼叫都是 5 參數（caseId + 中文短名 + 中文長描述 + fn），非中文 / 4 參數需補
- `grep "injectEvidence\|expandSelectAsListbox\|clearEvidence" <release-tests>/{KEY}.cjs` 確認斷言 step 都注入 evidence（三合一規範）

#### S8.2 範本 require 區塊（v2.4.4+ 對齊 S3 骨架完整 helpers 列表）

publish 時 HELPERS_DIR fallback 路徑改指 `_helpers/`，其餘 require 整段照搬：

```javascript
const path = require('path');

const HELPERS_DIR = process.env.CUP_HELPERS_DIR
  || path.join(__dirname, '_helpers');   // ← .claude/ 階段是 ~/.claude/skills/jira-test-report/helpers

const { parseEnv } = require(path.join(HELPERS_DIR, 'env.cjs'));
const { createStepRunner } = require(path.join(HELPERS_DIR, 'step.cjs'));
const { waitAndDismissOnEntry, ensureCleanState } = require(path.join(HELPERS_DIR, 'modal.cjs'));
const { launchBrowser, attachConsoleCollector } = require(path.join(HELPERS_DIR, 'browser.cjs'));
const { writeResultsJson, printSummary, exitCodeForResults } = require(path.join(HELPERS_DIR, 'report.cjs'));
const { injectEvidence, clearEvidence, expandSelectAsListbox } = require(path.join(HELPERS_DIR, 'evidence.cjs'));
// 例外 case 需切換機構時加（多數 cjs 用預設 compal 機構，不必 require）：
// const { switchOrg, DEFAULT_ORG } = require(path.join(HELPERS_DIR, 'orgGuard.cjs'));
```

#### S8.3 驗證時機（Local + Staging 雙環境）

| 時機 | URL 來源 | 驗證對象 | 命令 |
|---|---|---|---|
| **publish 前** | localhost dev server | 當前 feature branch 含 commit | 從 `.claude/` 跑：`BASE_URL=http://localhost:3000 node .claude/{ISSUE_KEY}-test.cjs` |
| **publish 後（每次改 cjs）** | release-tests 內位置 + staging URL | release-tests 環境 wiring 正確 + staging 已部署該功能 | 從 `frontend/` 跑：`set -a; source .env.local; set +a; BASE_URL=$STAGING_URL node ../e2e/release-tests/{ISSUE_KEY}.cjs` |

**`.env.local` 同時宣告兩組 URL**：

```
BASE_URL=http://localhost:3000          # local dev server
STAGING_URL=https://lunastaging.compal-health.com   # staging（release-e2e workflow 同源）
```

切換僅靠 `BASE_URL=$STAGING_URL` 前綴覆寫，不需改 cjs；對齊 CI 端 `secrets.E2E_STAGING_URL` 命名語義。

**何時跳過 staging 驗證**：當前 feature branch 尚未 merge 進 master / staging 未部署該 commit → 跳過，標註「Staging 驗證待 staging 部署該 commit 後再跑」。

#### S8.4 測試 fixture 管理（CASE_ID / DAYCARE_CASE_ID 等業務輸入）

某些 cjs 需要業務 fixture（如 LVB-7963 需「已結案個案 ID」）。**推薦：hardcode staging 預設值 + env 可覆寫**。

##### 主推：Hardcode default + env override

cjs 內宣告 STAGING 常數，`process.env` 覆寫即可；CI 不需要 Variables，workflow yml 不需要 jq step。

```javascript
// ----- staging fixture（hardcode 預設值）-----
// 「已結案」狀態居服個案，於 staging 環境穩定存在；過期請 PR 更新此值
const STAGING_CASE_ID = 'a3f2c891-xxxx-xxxx-xxxx-xxxxxxxx';
const STAGING_DAYCARE_CASE_ID = 'b7d4e123-yyyy-yyyy-yyyy-yyyyyyyy';

// 本地可 export CASE_ID / DAYCARE_CASE_ID 覆寫
process.env.CASE_ID = process.env.CASE_ID || STAGING_CASE_ID;
process.env.DAYCARE_CASE_ID = process.env.DAYCARE_CASE_ID || STAGING_DAYCARE_CASE_ID;
```

**優點：**
- cjs = 自帶測試規格，看 cjs 就知道測哪個個案（不必跨檔 trace Variables / yml）
- 新增 cjs 只需 1 個 PR（不必再開第 2 個 PR 設 Variable）
- 本地測試仍可 env override 走自己 dev db 個案
- 個案 id 過期時 `git blame` 找得到當初是誰加的

**適用前提：**
- 個案 uuid 不含個資（純機器生成 id）— luna 符合，可進 git
- staging db 不常重建、fixture 穩定

##### Fallback：GitHub Variables JSON map（hardcode 不適用時）

如果公司政策禁止任何測試資料 commit 進 git，改用 GitHub Variables：

| 來源 | 寫法 | 範例 |
|---|---|---|
| 本地 `.env.local` | generic 名 | `CASE_ID=abc123` |
| GitHub Variables | JSON map 集中 | 見下方 |

```
Name: RELEASE_TEST_FIXTURES
Value:
{
  "LVB-7963": { "CASE_ID": "case_uuid_1", "DAYCARE_CASE_ID": "case_uuid_2" },
  "CUP-180":  { "CASE_ID": "case_uuid_3" },
  "ERPD-11841": {}
}
```

`release-e2e.yml` matrix step 用 `jq` 解析：

```yaml
- name: Load fixtures for ${{ matrix.issue }}
  shell: bash
  env:
    FIXTURES: ${{ vars.RELEASE_TEST_FIXTURES }}
    ISSUE: ${{ matrix.issue }}
  run: |
    echo "$FIXTURES" | jq -r --arg k "$ISSUE" '.[$k] // {} | to_entries[] | "\(.key)=\(.value)"' >> "$GITHUB_ENV"
```

cjs 端只讀 generic env，本地與 CI 程式碼一致。

##### 缺 fixture 的 guard

兩種方案共用：缺必填 env 必須 exit 4（MISSING_ENV，對齊 LVB-7963 exit code 規範），不跑下去。

```javascript
if (!process.env.CASE_ID) {
  console.error('MISSING_ENV: CASE_ID required');
  process.exit(4);
}
```

hardcode 方案因為已注入 default，這個 guard 通常不會 trigger，但留著以防有人手動 unset。

#### S8.5 機械步驟（v2.4.4+ 因 helpers 已收斂，步驟精簡）

1. 偵測 repo root：`git rev-parse --show-toplevel`
2. 確認 `<root>/e2e/release-tests/` 存在且含 `_helpers/`（vendor）；若無 → 中止，提示 release-tests 結構未建立
3. **確認 `_helpers/` 內必要 cjs 完整**（自 v2.4.1 起，v2.4.4 helpers 列表擴充）：列出當前 cjs require 的 helper（骨架預設用：`env.cjs` / `step.cjs` / `modal.cjs` / `browser.cjs` / `report.cjs` / `evidence.cjs`），對每個 helper 檢查 `<root>/e2e/release-tests/_helpers/<helper>.cjs` 是否存在。**若缺**，跑 `~/.claude/skills/cup-build-test/scripts/sync-helpers.sh --force` 一次性同步（master `cup-build-test/helpers/` → 所有 mirrors 含 release-tests）。注意 `_helpers/` 即使只含 `node_modules/` 而沒有任何 cjs 檔也是合法狀態（首次 publish 時常見），不要因此中止流程
4. `cp .claude/{ISSUE_KEY}-test.cjs <root>/e2e/release-tests/{ISSUE_KEY}.cjs`
5. 套用 S8.1 第 1 點機械改動（用 Edit 工具改 `HELPERS_DIR` fallback：`os.homedir() + '.claude/skills/jira-test-report/helpers'` → `path.join(__dirname, '_helpers')`，順帶把不再需要的 `const os = require('os')` 移除）
6. 若 cjs 需 fixture：確認 STAGING 預設值已 hardcode 在 cjs（S8.4 主推方案），CI 端不需設 Variable；若用 Fallback 方案則更新 `RELEASE_TEST_FIXTURES` Variable 並補進 `.env.local`
7. grep 自我檢查：`step(page,` 全 5 參數中文版；斷言 step 都有 `injectEvidence`（三合一）
8. 跑 S8.3「publish 前」local 驗證 1 次（當前 branch 應含 feature commit）
9. 若 staging 已部署 → 跑 S8.3「publish 後」staging 驗證；若未部署 → 標註待 staging 後驗證
10. 提示使用者：「PR 開出 / push 後可手動觸發 release-e2e workflow 對 staging 跑」

### 步驟 9：清理

```bash
rm -rf .claude/{ISSUE_KEY}-temp
# 腳本檔案保留在 .claude/{ISSUE_KEY}-test.cjs，下次回歸可重跑
# progress.md 預設保留作為執行歷史，使用者下次跑全新 issue 前可手動刪除
```

`.env.local` **保留**（每次跑都 API 登入，無暫存 session 檔需要清理）。
`.claude/{ISSUE_KEY}-progress.md` **預設保留**（執行歷史紀錄）；下次跑同 issue 全新流程前用 `rm` 或選擇 `[2] 刪除舊檔，重跑完整流程`。

### 步驟 10：提醒撤銷 token（選用）

token 已存 `.env.local` 持續複用；若使用者要求一次性使用或要 rotate，提醒去 https://id.atlassian.com/manage-profile/security/api-tokens 撤銷後從 `.env.local` 刪除舊值。

## Wiki Markup 速查

| 功能 | 語法 |
|------|------|
| h2 標題 | `h2. 文字` |
| h3 標題 | `h3. 文字` |
| 粗體 | `*文字*` |
| 斜體 | `_文字_` |
| 行內 code | `{{code}}` |
| Code block | `{code:javascript}...{code}` |
| 引用 | `bq. 文字` |
| 分隔線 | `----` |
| 圖片 inline | `!filename.png\|width=900!` |
| 表頭 | `\|\| col1 \|\| col2 \|\|` |
| 表格 | `\| cell \| cell \|` |
| 連結 | `[文字\|https://url]` |
| 編號清單 | `# item` |
| 項目清單 | `* item` |

## Comment 結構建議

```
h2. 自動化測試結果（環境/方法）
摘要一行：環境 + 結果 + 模式（互動/腳本）

----

h3. 1. {步驟標題}
{說明 + 預期行為}
!{螢幕截圖}|width=900!

h3. 2. {下一步}
...

----

h3. 邏輯驗證表
|| 條件 || 預期 || 實測 ||
| ... | ... | ✅ |

----

h3. 結論
通過/失敗 + 重點觀察
```

## 失敗處理

AI-parsing 結構化（v2.4.7+）：每個 symptom 對應一個 action / why。

```
LOGIN-4xx:
  symptom: API 登入回 4xx
  action: 密碼錯 / account 鎖 → 驗證 .env.local 內容（不要在對話貼密碼）

LOGIN-5xx:
  symptom: API 登入回 5xx
  action: 後端問題 → retry 一次 → 仍失敗則中止

UPLOAD-401:
  symptom: attachment upload 回 401
  action: token 失效 → 重新驗證

COMMENT-ATTACHMENT-VALIDATION:
  symptom: Comment POST 400 ATTACHMENT_VALIDATION_ERROR
  cause: 誤用 v3 ADF + attachment id
  action: 改回 v2 wiki（/rest/api/2/issue/{key}/comment + wiki markup body）

SCREENSHOT-ACCESS-DENIED:
  symptom: 互動模式截圖 access denied
  cause: Playwright MCP 限制只能存到專案根目錄之內
  action: filename 改寫進 frontend/.playwright-mcp/ 或 frontend/ 內，不可寫 ~/Desktop / /tmp

SESSION-EXPIRED:
  symptom: 跑到一半被導回 /login
  why: API 登入 stateless 每跑都重取，不該發生
  if-still-happens: 後端 session 失效時間 < cjs 跑完時間 → 縮短測試或登入 API 加 keep-alive 邏輯

PLAYWRIGHT-MODULE-MISSING:
  symptom: 腳本模式 "Cannot find module 'playwright'"
  action: cd ~/.claude/skills/jira-test-report/helpers && npm install && npx playwright install chromium
  note: .claude/ 階段預設 require jira-test-report/helpers

SELECTOR-NOT-FOUND:
  symptom: 腳本模式 selector 找不到（特別 R18 升級後）
  action: HEADLESS=false 重跑看實際畫面 → 調整 selector

RATE-LIMIT:
  symptom: 跑到一半 rate limit
  banned: 閒置等待（5 分鐘 prompt cache 過期，恢復時燒幾萬 token 重建 cache）
  action: 當前 step 跑完後 /clear → 新 session 用 /jira-test-report --resume 從 progress.md 接續（Phase A/B/C 自動接力）

RESUME-NO-PROGRESS:
  symptom: --resume 但 progress.md 不存在
  action: 提示使用者「尚未跑過，無進度可續，請去掉 --resume 旗標」

PROGRESS-ISSUE-MISMATCH:
  symptom: progress.md 存在但 issue key 不符
  action: 中止，提示「進度檔屬於別的 issue」
```

## 參考做法（記憶提示）

- 第一次用這個 skill 的完整成功 case：ERPD-11841（2026-05-04），12 張截圖全 inline，互動模式
- 腳本模式首發 case：CUP-80（2026-05-07），活動行事曆 R18 回歸驗證
- attachment 上傳 endpoint v3 OK，但 comment 要用 v2 wiki 才能 inline
- 不要嘗試從 attachment redirect 拿 media UUID 自己拼 ADF，太繞且 location header 可能被 CDN 截斷
- 互動模式截圖**必指定 filename**，否則 base64 入 context 噴 token

---

## Changelog

版本號採 [Semver](https://semver.org/lang/zh-TW/)。MAJOR=破壞既有 cjs / 流程行為、MINOR=新增 helper / 模式 / 階段步驟、PATCH=修 bug 或文件更新。

### v2.4.7 — 2026-05-20（PATCH：規則性段落 AI.MD v4 結構化，prose bullets → structured labels）

**變更**（局部 reformat，無新規則 / 新 helper / 流程行為變更）：

四個規則性段落從 prose bullets 改為 AI-parsing structured labels（套 AI.MD v4 方法論：每條 rule + why + how/banned，attention 不被 dense prose 切散；歷史 context 保留作 `why` / `case` 子欄）。Code 範例、changelog、API 速查表、Wiki Markup 速查、共用先決條件等其他段落**原樣保留**。

| 段落 | 行為 |
|---|---|
| S3「寫腳本準則」12 條 | prose bullets → 12 個 structured rule blocks（STEP-PER-ASSERTION / SELECTOR-PRIORITY / LOCATOR-CHAIN / WAIT-STRATEGY / MUTATION-SAFETY / EDIT-STATE-DETECTION / THIRD-PARTY-SELECTOR / LOGIN / GOTO-WAIT / STEP-CHINESE / ASSERTION-EVIDENCE / HELPERS-ONLY） |
| S3.5「Cleanup 鐵則」prose | 改 `CLEANUP-EVIDENCE-BEFORE-UI` block（rule / triggers / why / case / inverse-evidence）；code 範例 + grep + 自我檢核 checklist 保留 |
| S3.6「何時用 + 切換邏輯」 | `USE-WHEN` / `SKIP-WHEN` + `SWITCH-ORG-PIPELINE`（step-1 ~ step-6）；cjs 整合範本 code + 自我檢核 checklist 保留 |
| 失敗處理 11 條 | prose bullets → 11 個 symptom/action/why block（LOGIN-4xx / LOGIN-5xx / UPLOAD-401 / COMMENT-ATTACHMENT-VALIDATION / SCREENSHOT-ACCESS-DENIED / SESSION-EXPIRED / PLAYWRIGHT-MODULE-MISSING / SELECTOR-NOT-FOUND / RATE-LIMIT / RESUME-NO-PROGRESS / PROGRESS-ISSUE-MISMATCH） |

**設計動機**（AI.MD v4 理論支撐）：

- **Attention splitting**：dense prose 多條規則用 `|` / 句號黏在一行時，模型 attention 分散，部分規則 weight 降到近零。獨立 line + label 讓每條規則拿到完整 attention
- **Zero-inference labels**：`rule:` / `why:` / `banned:` / `how:` 等 label 直接宣告語意，免去模型從 prose context 推論
- **Semantic anchoring**：`LOGIN:` / `GOTO-WAIT:` / `CLEANUP-EVIDENCE-BEFORE-UI:` 等 ALL-CAPS 標題 = 可被 user prompt 直接 hash 命中的 anchor

**範圍邊界**（沒做的部分）：

- code 範例（S3 骨架、S3.5/S3.6 cjs 範本、wiki markup 範例）：完整 copy-paste 可執行，不該結構化打散
- API 速查表 / Wiki Markup 速查 / 共用先決條件：已是 structured table，AI.MD 化反而冗餘
- Changelog（v2.4.6 以前歷史）：時序紀錄，給人讀的
- multi-model 完整驗證（AI.MD v4 Phase 6）：此次屬 PATCH 局部 reformat，未跑 8 道測題 multi-model 驗證；下次跑 cjs 時實測 compliance 即可

**影響範圍**：

- 既有 cjs：不受影響（rule 內容未變，只變呈現形式）
- 新產出 cjs：AI 跟 skill 時規則命中率預期提升（特別是長對話 / 多輪 context 場景）
- 同步：cup-build-test SKILL.md 對應段落可比照 reformat（後續另起 PR）

### v2.4.6 — 2026-05-20（新增 orgGuard.cjs helper：機構切換 + 例外 case 支援）

**新增**：

- **新 helper `orgGuard.cjs`**：提供 `switchOrg(page, { keyword, expectedDisplay, waitMs })` / `currentOrg(page)` / `DEFAULT_ORG` 三個 API。jira-test-report 例外 case 屬於非預設機構（如豐原醫院、台南御宇）時，A1 前切過去、finally 切回 `compal`（仁寶長照機構），避免污染後續測試
- **新增步驟 S3.6「機構切換」段**：何時要用、helper API、切換邏輯、cjs 整合範本（A0 / Z9 step 結構 + 簡化版）、自我檢核 5 點
- **Helpers 速查表加 `orgGuard.cjs` 一行**
- **S8.2 範本 require 區塊加註解**：例外 case 才 require `orgGuard`，多數 cjs 不需要

**設計動機**：

- 帳號 `adm_max_ho` 為通用最高權限可切換機構帳號，預設機構 `仁寶長照機構` (internal code `compal`)；少部分 bug 只在特定機構特定 case_id 可重現
- 之前若手動切換到別機構後忘了切回，下次跑 LVB-7977 / ERPD-11841 等預設機構 cjs 會撈不到 case 或撈到別機構的 case，產生誤判
- helper 強制切後斷言 `expectedDisplay`，比手動點 dropdown 穩定；切後自動 `goto /case/` 避踩到 `/` 路由的 SSO redirect 雪坑

**切換邏輯關鍵設計**（解決兩個雪坑）：

1. **dropdown 顯示文字與右上角顯示文字是兩套 mapping**：dropdown 選項 `仁寶躍虎 (compal)`，但切後右上角顯示 `仁寶長照機構`。helper 不靠 substring 比對 dropdown text，而是優先用「endsWith `(${keyword})`」精準匹配 internal code（多筆過濾結果也能挑對）；fallback 才是「過濾結果唯一」分支（支援 `keyword='豐原'` 這種顯示名片段）
2. **切換後預設導向 `/` 會 SSO redirect 到 icaretest115**：helper 切後強制 `goto /case/` protected route，前端讀 token cookie 正常通過

**Smoke 驗證**：

`/tmp/orgguard-smoke.cjs` round-trip 全綠：
- Smoke 1 `currentOrg` → `仁寶長照機構`
- Smoke 2 `switchOrg(DEFAULT_ORG)` 已在預設 → noop（`switched: false`）
- Smoke 3 `switchOrg({ keyword: '豐原', ... })` → 切換成功（唯一過濾分支）
- Smoke 4 `switchOrg(DEFAULT_ORG)` → 切回成功（endsWith `(compal)` 多筆分支）

**影響範圍**：

- 新產出 cjs：屬於非預設機構的 issue 強制套用 S3.6（A0 切換 / Z9 切回）
- 既有 cjs（LVB-7977 / ERPD-11841 等預設機構 case）：不受影響，繼續用 `compal` 機構跑
- 對應 memory 候選：可加 `feedback_org_switch_required_for_non_compal_cases.md` 記錄機構切換時機（後續）

### v2.4.5 — 2026-05-20（ERPD-11841 staging 實戰回饋：injectEvidence 後 UI 互動前必須 clearEvidence）

**新增**：

- **S3.5 Cleanup 鐵則升級**：同一 step 內 `injectEvidence` 之後若還有任何 UI 互動（closeModal / .click / .fill / .selectOption 等），動作前必須 `await clearEvidence(p);`。從「下個 step 開頭 / cancel modal 前」軟性建議升級為硬性規則
- 加 ERPD-11841 A8 實戰範例：原 step 結尾 `injectEvidence → closeModal` 順序在 staging 100% 重現 `Timeout 30000ms exceeded`，error log `<div>… from <div id="e2e-evidence-panel">… subtree intercepts pointer events`；同 cjs A4 / A7 PASS 因 closeModal 在 injectEvidence「之前」
- 加 Code review grep 指令：`grep -A 20 'injectEvidence' <cjs> | grep -E 'closeModal|\.click\(|\.fill\(|\.selectOption\('`
- 自我檢核清單加一條（v2.4.5+ 鐵則）：「同 step 內 injectEvidence 之後若還有 UI 動作，動作前有 clearEvidence」

**設計動機**：

`#e2e-evidence-panel` 由 `evidence.cjs::injectEvidence` 注入 viewport 右上角 `position: fixed`，Modal 寬度大時會剛好覆蓋 modal-header 右上角的 close button，Playwright 60 次 retry 全被 pointer-events 攔截。功能本身沒 bug（人工點得下去），但腳本自己擋自己，是「腳本 bug 看起來像功能 bug」的典型雪坑。

ERPD-11841 staging 跑 A8 9 step 中 1 個 FAIL 30 秒就是這個原因。修法是 `closeModal` 前一行加 `await clearEvidence(p);`，從 47s elapsed FAIL 變 16s 全 PASS。

**影響範圍**：

- 已修：`e2e/release-tests/ERPD-11841.cjs:529` + `.claude/ERPD-11841-test.cjs:534`
- 新產 cjs：強制套用 S3.5 Cleanup 鐵則
- 既有 cjs：grep `injectEvidence` 後緊接 UI 動作但中間沒 clearEvidence 的 step，回頭補上
- 對應 memory：`feedback_clear_evidence_before_ui_action.md`

### v2.4.4 — 2026-05-19（LVB-7963 風格 codify + helpers 全面化 + 雙 skill 獨立）

**新增**：

- **S3 腳本骨架全面 helpers 化**：require 整套 `env.cjs` / `step.cjs` / `modal.cjs` / `browser.cjs` / `report.cjs` / `evidence.cjs`，cjs 主體只放測試 step 邏輯。不再 inline 寫 `step()` runner、`updateProgressMd`、`injectEvidence`、`writeResultsJson`、`fs.writeFileSync(_results.json)`、console error 收集等已有 helper 的程式碼
- **檔頭格式對齊 LVB-7963 6 段**：(1) 一句話描述 (2) Root cause (3) 修正 (4) 驗證情境 (5) 用法 / 環境變數 / 前置 (6) Exit codes（0/1/3/4）
- **S3.5 evidence overlay 改 require `evidence.cjs`**：不再 inline 30+ 行 `injectEvidence` 函式；列出 `injectEvidence` / `clearEvidence` / `expandSelectAsListbox` 三個 API 用途
- **S3 寫腳本準則加「helpers 全面化禁止 inline 重複」條**：明確禁止在 cjs 重複實作已 helper 化的功能
- **進階用法段重寫為「Helpers 架構與 API 速查」**：列出 7 個 helper 的 API 簽名與用途；標註修 helper 走 master + sync-helpers.sh
- **S8.1 機械改動從 7 點縮為 1 點**：只剩 `HELPERS_DIR` fallback 從 `~/.claude/skills/jira-test-report/helpers` 改 `path.join(__dirname, '_helpers')`；附表列出原 6 點為何不再需要
- **S8.2 require 區塊對齊 S3 完整 helpers 列表**：6 個 require 一次補齊
- **S8.5 機械步驟對齊新流程**：第 3 點 helpers 完整性檢查改為跑 `sync-helpers.sh --force` 一次性同步；第 5 點改動量從 6 點縮為 1 點；第 7 點新增 `grep injectEvidence` 自我檢查
- **失敗處理段 npm install 路徑**：從 `cup-build-test/helpers` 改為 `jira-test-report/helpers`（兩個 skill 獨立可運作）

**helpers 變化（反向同步補齊 master）**：

- `cup-build-test/helpers/evidence.cjs` 新增（先前只在 `e2e/release-tests/_helpers/`，回灌 master）：提供 `injectEvidence` / `clearEvidence` / `expandSelectAsListbox` 三個三合一規範必備 API
- `cup-build-test/helpers/env.cjs` 更新到 release-tests 端 v0.4.0：新增 `SCREENSHOT_BASE_DIR` env var（給 CI 設 `.` 避開 hidden dir glob）、`SCREENSHOT_DIR` 完全覆寫、拿掉冗餘 variant 子目錄層
- `cup-build-test/helpers/step.cjs` 更新到 release-tests 端 v0.4.0：`createStepRunner` 5 參數中文簽名 + `sanitizeForFilename` helper（保留 unicode 中文檔名）
- `cup-build-test/helpers/types.d.ts` 更新：`StepResult` 加 `description?: string`
- `sync-helpers.sh --force` 已把上述 4 個檔案推到 jira-test-report mirror 與 release-tests vendor，三邊一致

**設計動機**：

- LVB-7963 是 release-tests 第一個完整 helpers 化的腳本（520 行，cjs 主體只剩測試邏輯），但即將被刪除。先前 skill 範本仍是 v2.0 inline 寫法（LVB-7977 為證，562 行內含 100+ 行重複 helper 邏輯），新產出的 cjs 都未對齊 LVB-7963 風格
- evidence.cjs 只在 release-tests/_helpers/ 沒同步回 master，導致 .claude/ 階段腳本無法 require → 每個 cjs 都得 inline 30+ 行 injectEvidence，違反 v2.4.0 三合一規範要求
- 使用者明確要求「兩個 skill（cup-build-test / jira-test-report）獨立不互相依賴」：兩邊各自完整 helpers，透過 sync-helpers.sh 保持同步

**影響範圍**：

- **新產出 cjs**：強制套用新骨架（S3 + S3.5 + S8.1/S8.2/S8.5），平均行數從 ~560 行縮到 ~280 行
- **既有 cjs**（v2.4.3 以前）：LVB-7977 / ERPD-11841 等下次回歸時建議改寫對齊；LVB-7963 即將刪除，其風格已 codify
- **helpers master 版本建議 bump 0.3.0 → 0.4.0**：因新增 evidence.cjs + env.cjs 行為變更（破壞性需 caller 對齊新 SCREENSHOT_BASE_DIR 預設）

### v2.4.3 — 2026-05-19（ERPD-11841 實戰回饋第 2 輪：禁用 authStateFromApi，登入改 launchBrowser({ login })）

**新增**：

- S3 寫腳本準則加「**登入用 `launchBrowser({ login: loginParamsFromEnv() })`，禁止 `authStateFromApi` + `storageState`**」：luna staging `token` cookie 是 host-only，storageState 序列化會漏，且 `authStateFromApi` 沒帶 `x-request-from: web` header，後端根本不發 token cookie
- S3 骨架範本（main 開場 + S8.2 require 區塊）改用 `launchBrowser` + `loginParamsFromEnv`，移除手動 `chromium.launch` + `newContext({ storageState })` + 拋棄 `authStateFromApi`
- 本機驗證指標：腳本啟動第一行應印出 `[login] OK 200 — N cookies: token,lunastaging.sid`，**`token` 必須在 cookie 列表中**，否則進頁面後會被 SSO redirect 到 `icaretest*`

**設計動機**：ERPD-11841 在 GitHub Actions 跑 staging timeout 後本機重現，瀏覽器 `title="Loading https://icaretest115.compal-health.com/?q=ic"` 揭露真因 — 不是 wait condition，是 token cookie 沒拿到 → SSO redirect 卡死。v2.4.2 改 `domcontentloaded` 治標、v2.4.3 改 `launchBrowser({ login })` 治本。

**影響範圍**：

- 新產出 cjs 強制套用（S3 骨架已改）
- 既有 cjs `grep authStateFromApi` 應全清為 `launchBrowser({ login })`：ERPD-11841（已修）；LVB-7963 / LVB-7977 早就用 `launchBrowser` 不需動
- skill 互動模式段（約 193 行）的 `helpers/login.cjs::authStateFromApi` 引用建議下個版本一併更新為 `loginInContext`

### v2.4.2 — 2026-05-19（ERPD-11841 實戰回饋：禁用 networkidle + AUTH_EXPIRED fail-fast）

**新增**：

- S3 寫腳本準則加「**`page.goto` waitUntil 一律用 `'domcontentloaded'`，禁止 `'networkidle'`**」：luna staging R18 SPA 背景 GA4/polling 持續，networkidle 30 秒 timeout
- S3 骨架範本第 440 行同步改 `domcontentloaded`，並補上 `AUTH_EXPIRED` fail-fast block（對齊 LVB-7963.cjs 既有慣例）

**設計動機**：ERPD-11841 在 GitHub Actions release-tests workflow 跑 staging 時 `page.goto('/supervisorVisitRecord', { waitUntil: 'networkidle' })` 30 秒 timeout 直接 fail。同寫法 LVB-7963 `/homecareCaseClose` 過得了是因為該頁 polling 較少，networkidle 在 SPA 上行為不穩定不可靠。

**影響範圍**：

- 新產出 cjs 強制套用（S3 骨架已改）
- 既有 cjs 應逐步回頭把 `networkidle` 換成 `domcontentloaded`：ERPD-11841（已修）、LVB-7963（暫時還能過但建議下次回歸時換掉）

### v2.4.1 — 2026-05-19（LVB-7977 實戰回饋：DOM-driven 判斷 + _helpers 完整性檢查 + 跑前清空 temp）

**新增**：

- S3 寫腳本準則加「**判斷進入子頁/編輯狀態預設 DOM-driven**」：SPA inline 編輯 URL 通常不變，靠 URL diff 判斷會永遠 false。改靠 DOM 訊號（表單欄位 / 按鈕 / typeahead mount）。luna FE r15/r18 多數頁面屬此模式但少數會 push history state，第一次寫腳本時 `HEADLESS=false` 觀察一次再決定
- S3 寫腳本準則加「**第三方元件 selector 寫前先 grep 實際版本**」：react-bootstrap-typeahead v1.x 用 `.bootstrap-typeahead`，v4+ 改 `.rbt-`，差異大；寫死 selector 前先查 `node_modules/<lib>/lib/*.js` 或 `package.json`
- S8.5 機械步驟第 3 點：**確認 `_helpers/` 內必要 cjs 完整**，缺則自動 cp from `~/.claude/skills/cup-build-test/helpers/`。空 `_helpers/`（只含 node_modules）為首次 publish 常見狀態，不應中止流程
- 步驟 5 / S4 開頭加 `rm -rf .claude/{ISSUE_KEY}-temp` 跑前清空（`--resume` 模式例外）：避免 step 改名留下 stale 截圖污染 Phase B 上傳

**設計動機**：LVB-7977 實戰踩到三個坑 — (1) A2 用 `url !== originalUrl` 判斷進入編輯頁永遠 false（luna 點編輯 URL 不變）；(2) TYPEAHEAD selector 用 v4+ `.rbt-*` 但 react_15 是 v1.x `.bootstrap-typeahead`，找不到任何元素；(3) Phase B 上傳前 temp dir 留有「A4 鄧 → 改成 A4 陳」兩個版本的截圖，未手動刪會混淆 Jira inline comment。

### v2.4.0 — 2026-05-19（斷言截圖三合一規範：程式邏輯 + 真實頁面操作 + evidence overlay）

**變更**：

- 新增 **S3.5 斷言截圖三合一規範**（強制）：每個 step 必須同時具備
  1. 程式邏輯斷言（throw new Error 含實測 vs 預期對比）
  2. 真實頁面操作或視覺變更（DOM 至少一處可截圖識別的變化）
  3. 斷言結論可視化（evidence overlay 注入右上角）
- 純資料比對 step（截圖前後雷同）視為 anti-pattern，強制用以下方式之一補回頁面證據：
  - (a) 強制 native 元素展開呈現（如 `<select>.size = N` 變 listbox）
  - (b) 逐項真實 UI 互動（如 `selectLocator.selectOption()` 逐選驗證）
  - (c) DOM highlight + 標號 outline / badge
- 提供 `injectEvidence(p, {...})` 標準格式 helper 範例（inline 在 cjs，可選擇抽到 _helpers/evidence.cjs）
- 提供 LVB-7963 A3.2 / A3.3 範本重構（必要選項用 (b) 逐一 selectOption、完整 14 項用 (a) listbox 展開）
- 提供 cleanup pattern（cancel modal 前移除 evidence overlay）
- 提供 self-check 5 點清單（每個 step throw / UI 證據 / evidence / cleanup / 對比訊息）

**設計動機**：LVB-7963 實戰發現 A3.2~A3.4 三步截圖完全雷同（純對 JS 陣列做 includes 比對 + 順序比對），非工程 stakeholder 看 Jira inline comment 與 GitHub Actions artifact 無法判讀斷言依據，等同沒測。三合一規範強制每個斷言 step 都同時驗證程式邏輯與 UI 行為，截圖內可見斷言結論。

**影響範圍**：
- 新產出 cjs 強制套用（S3 寫腳本準則 + S3.5 規範）
- 既有 cjs（LVB-7963 / CUP-180 / ERPD-11841）建議下次回歸時逐步補上 evidence overlay；LVB-7963 為首要範例改造目標
- S8.5 機械步驟可加第 9 點：grep `injectEvidence` 確認斷言 step 都有注入（未來版本補）

### v2.3.2 — 2026-05-19（產出 release-tests cjs 強制中文化 step 呼叫）

**變更**：

- S3「寫腳本準則」加一條「step 呼叫中文化」：所有產出 cjs 一律用 5 參數中文版簽名 `step(page, caseId, '中文短名', '中文長描述', async (p) => {...})`
- S3 腳本骨架的 `step()` inline 函式改為支援 4 參數新版 + 2 參數 legacy 向後相容；截圖檔名改為 `{idx}-{caseId}-{中文短名}.png`，sanitize 改保留 unicode（中文不被替換成 `-`）
- S3 腳本骨架的「測試步驟區塊」範例改用 5 參數中文版示範
- S8.1 機械改動清單加第 7 點：publish 到 release-tests 時 grep `step(page,` 確認所有呼叫已中文化，未中文化要補
- 設計動機：release-e2e workflow 跑完後，使用者在 GitHub Actions Job summary / artifact `_results.json` / 截圖檔名 / Jira inline comment 都吃 `name` / `description`，中文化讓非技術 stakeholder 看 workflow 結果就能理解每步在做什麼；對齊 LVB-7963 已落地的 `_helpers/step.cjs createStepRunner` 5 參數簽名規範

**helpers 變化**：

- `e2e/release-tests/_helpers/step.cjs` `createStepRunner` 已於 LVB-7963 commit 提供 5 參數簽名向後相容（typeof 判斷第 4 個 arg 是 function 或 string）
- `e2e/release-tests/_helpers/types.d.ts` `StepResult` 加 `description?: string`
- jira-test-report skill helpers/ 透過 `~/.claude/skills/cup-build-test/scripts/sync-helpers.sh` 同步即跟進

### v2.3.1 — 2026-05-18（fixture 管理改推 hardcode default）

**變更**：

- S8.4 fixture 管理主推方案改為 **hardcode staging default + `process.env` 覆寫**（JSON map 移至 Fallback 段）
- 設計動機：luna 個案 uuid 不含個資，hardcode 進 cjs 比 GitHub Variables 設定簡單、新增 cjs 不需要二段 PR、cjs 自帶測試規格不必跨檔 trace
- JSON map 保留作為「公司政策禁止個案 id 進 git」時的 fallback 方案

### v2.3.0 — 2026-05-18（步驟 8 publish 到 release-tests 強制 + 雙環境驗證 + fixture 管理）

**變更**：

- 步驟 8「publish 到 release-tests」從「選用」改強制執行（只腳本模式適用）
- 新增 **S8.1 機械改動清單**：6 點對齊（HELPERS_DIR、chromium 路徑、SCREENSHOT_DIR、env.local 載入、progress.md silent、檔頭註解）
- 新增 **S8.2 範本 require 區塊**：可直接複製對齊 LVB-7963 風格
- 新增 **S8.3 驗證時機**：Local + Staging 雙環境
  - `.env.local` 同時宣告 `BASE_URL`（dev）與 `STAGING_URL`（staging）
  - 切換靠 `BASE_URL=$STAGING_URL` 前綴，不需改 cjs
  - 對齊 CI `secrets.E2E_STAGING_URL` 語義
- 新增 **S8.4 fixture 管理**：CASE_ID / DAYCARE_CASE_ID 等業務輸入
  - 推薦 GitHub Variables 用 **JSON map `RELEASE_TEST_FIXTURES`**（key=issue, value=env map）
  - workflow matrix step 用 `jq` export 為 env，cjs 完全不知 issue key
  - 缺 fixture exit code 4（MISSING_ENV，對齊 LVB-7963）
- 新增 **S8.5 機械步驟**：8 步驟清單從偵測 repo root 到提示使用者觸發 workflow

**設計動機**：先前 release-tests publish 是選用、僅留指針到 cup-build-test，導致 ERPD-11841 手動補 6 點機械改動才能上 release-tests。把這些抽出來、加上雙環境驗證紀律與 fixture 統一管理規範

### v2.2.0 — 2026-05-18（Atlassian credentials 改存 .env.local）

**變更**：

- Atlassian email / API token / site 一律改存 `.env.local`（keys：`ATLASSIAN_EMAIL` / `ATLASSIAN_API_TOKEN` / `ATLASSIAN_SITE`），**不再從對話索取**
- 新增「`.env.local` 完整範例」段，列出 E2E + Atlassian 兩組必要 keys
- 步驟 2 / 步驟 S2 / 步驟 6 / 步驟 7 / 步驟 10 全部改為從 `process.env` 讀
- 步驟 10「撤銷 token」改為選用 — token 持續複用，rotate 時才撤銷
- `.gitignore` 必含 `.env.local`（之前已有，文字加強）

**設計動機**：避免每次跑都要使用者貼 token，省 round trip；同時把 secret 集中在 gitignored 檔，降低不小心 commit 風險

### v2.1.0 — 2026-05-14（與 cup-build-test 共用 helpers）

**新增**：

- 引入 cup-build-test helpers 共用機制：`~/.claude/skills/jira-test-report/helpers/` 從 cup-build-test sync 而來（用 `~/.claude/skills/cup-build-test/scripts/sync-helpers.sh`）
- 步驟 S3 加「進階用法：引用 cup-build-test helpers」段，建議 cjs 引用：
  - `waitAndDismissOnEntry / dismissAnnouncement`（公告 modal 集中處理）
  - `ensureCleanState`（mutation step 入口防禦性 cleanup）
  - `confirmYes / confirmNo`（「是/否」「確認/取消」二次確認對話統一處理）
- 既有 cjs 不強制升級，新產 cjs 推薦用 helpers

**設計動機**：cup-build-test v1.1.0 累積的 luna 系統 modal handling 修正（CUP-179 / CUP-180 實戰），抽 helper 共用避免兩個 skill 重複維護。修一處兩個 skill 受益。

**helpers/ 版本**：跟 cup-build-test/helpers/ 0.2.0 一致（透過 sync-helpers.sh 同步）

### v2.0.0 — 2026-05-08（progress.md cross-session resume）

**新增**：

- 模式 1 互動模式（Playwright MCP）+ 模式 2 腳本模式（生成 .cjs + node 執行）並存
- progress.md 跨 session resume 機制（rate limit 預備）
- `--resume` 旗標 + 顯式要求機制
- Phase A/B/C 分段紀錄（跑測試 / Jira 上傳 / inline comment）
- Wiki Markup inline 截圖機制（comment 要用 v2 wiki 才能 inline，v3 ADF 不行）
- attachment 上傳走 v3 endpoint
- 互動模式截圖必指定 filename（避免 base64 入 context）

**首發案例**：ERPD-11841（2026-05-04，互動模式）、CUP-80（2026-05-07，腳本模式首發）
