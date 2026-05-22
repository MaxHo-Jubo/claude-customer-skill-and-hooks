---
name: jira-test-report
description: "對 Jira issue 跑 Playwright E2E 測試，自動截圖並 inline 上傳到 issue comment（截圖直接顯示在留言中，非附件清單）。當使用者提到 /jira-test-report、「跑測試報告」、「驗收測試上 Jira」、「截圖到 Jira」、「自動化測試 + Jira」、想對某個 issue 跑驗收測試並把結果留在 Jira 時觸發。"
version: 2.5.5
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

```
RATE-LIMIT-STRATEGY:
  context: Anthropic 5h 滾動視窗 + 5min prompt cache TTL
  banned: 閒置等待 reset → cache 過期 → 恢復時重讀 SKILL.md + cjs / 測試步驟 瞬間燒幾萬 token 重建
  action: rate limit 命中 → /clear 開新 session → 下次 --resume 續跑
  three-phase-cost: 跑測試 + 上傳 + 發 comment 三階段都吃 token
```

### progress.md 結構

`.claude/{ISSUE_KEY}-progress.md`，由 skill 在「跑測試前」建檔。完整範本見 [`templates/progress.template.md`](./templates/progress.template.md)（v2.5.1+ 抽出）。

**結構摘要**：

- **Header**：`Mode` / `Variant` / `Started` / `Last update`
- **Phase A：跑測試** — step 條目 `[x]/[ ]` + `Status` + `Screenshot` path + `Run at`
- **Phase B：Jira 截圖上傳** — 每張截圖一條，記下 attachment id
- **Phase C：Jira inline comment** — 1 條，所有 step 跑完才發

### 寫入時機

```
PROGRESS-WRITE:
  pre-phase-A: 建檔，所有 step 列為 [ ] 未勾選（從測試步驟清單推得）
  during-phase-A: 每跑完一 step → 條目 [ ] → [x]，填 status / screenshot / run at
  during-phase-B: 每張上傳完 → 條目 [x] + 記 attachment id
  during-phase-C: comment 發完 → 條目 [x]
```

### 續跑模式（`--resume`）

```
RESUME-FSM:
  trigger: --resume 旗標啟動
  state-1-load: 進入步驟 0.5 → 讀 .claude/{ISSUE_KEY}-progress.md
  state-2-phase-A-incomplete: Phase A 仍有 [ ] → 從第一個未勾選 step 續跑
  state-3-phase-A-done: Phase A 全 [x] + Phase B 仍有 [ ] → 跳過 A 直接補上傳
  state-4-phase-B-done: A/B 都全 [x] + Phase C 仍 [ ] → 直接發 comment
  state-5-all-done: 三 Phase 全 [x] → 提示「已完成，無事可做」
```

### 模式對應

```
PROGRESS-WRITER:
  互動模式: 主 context（Edit 工具）每 step 結束時更新
  腳本模式: cjs 內 step() wrapper 用 updateProgressMd()（同 cup-build-test 設計，見 S3 cjs 範例）
  phase-B/C: 不論模式都由主 context Edit
```

### 為什麼要顯式 `--resume` 旗標

```
EXPLICIT-RESUME:
  avoid-1: 舊 progress.md 殘留（上次失敗忘了清，新需求被誤判續跑）
  avoid-2: 同 issue 不同測試範圍（測試步驟 .md 改了，舊 progress 過時）
  fallback: 無 --resume 旗標但偵測到 progress.md 存在 → 步驟 0.5 問使用者（不自動決定）
```

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

完整範本見 [`templates/env.local.example`](./templates/env.local.example)（v2.5.1+ 抽出），包含三組必要 keys：

- **E2E 登入**：`BASE_URL` / `STAGING_URL` / `E2E_ACCOUNT` / `E2E_PASSWORD` / `E2E_TYPE`
- **Jira API**：`ATLASSIAN_EMAIL` / `ATLASSIAN_API_TOKEN` / `ATLASSIAN_SITE`
- **業務 fixture**：依 cjs 需求補（如 `CASE_ID` / `DAYCARE_CASE_ID`），CI 端用 generic 名稱對齊本地

`.gitignore` 必含 `.env.local`，缺則 append。skill 執行時用 dotenv 或簡易 parser 讀入 `process.env`，**禁止**把 token / 密碼寫入任何 commit 進 git 的檔案。

---

## 步驟 0.5：進度檔偵測（cross-session resume）

```
RESUME-DETECT-FSM:
  timing: 在 issue key 確定後（步驟 1 / S1 之後），模式 1、2 都跑
  check: .claude/{ISSUE_KEY}-progress.md 是否存在

  state-not-exist: 走完整流程（建檔在跑測試前）
  state-exist-with-resume: 進入續跑（refer RESUME-FSM）
    interactive: 主 context 跳過已 [x] 的 step
    script: 用 RESUME_FROM_IDX={N} env 傳給 cjs
  state-exist-no-resume: 問使用者三選一（不自動決定，refer prompt-block）

prompt-block: |
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

依測試步驟逐項操作，每步存截圖到專案根目錄下暫存資料夾（不能在 frontend 之外，Playwright MCP 有 root 限制）：

```
SCREENSHOT-TEMP:
  pre-run: rm -rf {ISSUE_KEY}-temp（v2.4.1+ 強制清空；--resume 例外）
  mkdir: mkdir -p {ISSUE_KEY}-temp
  filename: {ISSUE_KEY}-temp/{流水號-2位}-{語意描述}.png
  why-clean: step 改名（如 04-A4-鄧 → 04-A4-陳）會留兩版本污染 Phase B 上傳
  resume-exception: --resume 模式依 progress.md 跳過已完成 step，不要清 temp
```

```
INTERACTIVE-TOKEN-RULE:
  rule: 互動模式必遵守 token 節省鐵則
  banned-1: browser_take_screenshot 不指定 filename → 回 base64 進 context（5K-20K+ tokens / 張）
  banned-2: 對同個畫面重複 snapshot
  how: browser_snapshot 用 depth 限制 a11y tree 層級，或用 filename 存檔不入 context
```

```
INTERACTIVE-PROGRESS-WRITE:
  pre-run: 建 .claude/{ISSUE_KEY}-progress.md，所有測試步驟列為 [ ]
  per-step: 截完圖後用 Edit 工具改 [x] + 填 Status / Screenshot / Run at
  resume: 讀 progress.md，跳過所有已 [x] 的 step，從第一個 [ ] 開始
```

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

#### 產 cjs 流程（v2.5.0+ skeleton 已抽到 templates/skeleton.cjs）

骨架原檔：`~/.claude/skills/jira-test-report/templates/skeleton.cjs`（v2.4.4 風格、~170 行、含 placeholder 字串供替換）

```
GEN-CJS-PIPELINE:
  step-1-read: 用 Read 工具讀 ~/.claude/skills/jira-test-report/templates/skeleton.cjs
  step-2-substitute: 依下方 PLACEHOLDER 替換清單做字串替換
  step-3-fill-steps: 在 try{} 區塊「=== 測試步驟區塊（依 test plan 填充）===」與「=== 測試步驟區塊結束 ===」之間依 test plan 加 step()，遵守寫腳本準則 + S3.5 三合一 + S3.6 機構切換（若 case 屬非 compal）
  step-4-write: 用 Write 工具寫到 .claude/{ISSUE_KEY}-test.cjs
  mandatory: 必須先 Read templates/skeleton.cjs，禁止從記憶寫骨架
  why-mandatory: 容易漏 helpers require / parseEnv / progress 寫入 / finally 收尾，且 Opus 4.7 預設較少 spawn tool call 容易跳過 Read
  verify-high-risk: grep -E '<paste-staging-case-id>|\{ISSUE_KEY\}' .claude/{ISSUE_KEY}-test.cjs 應 0 命中（這兩個沒替換會直接讓執行失敗：staging fixture 不對 / progress.md 路徑錯）
  verify-low-risk: grep -E '\{[一-龥]' .claude/{ISSUE_KEY}-test.cjs 應 0 命中（中文 placeholder 都該已替換，如 `{一句話描述}` / `{場景一名稱}` 等）
  note: '{caseId}' 是 parseEnv runtime 佔位（entryPath 內由 process.env.CASE_ID 代入），**不需替換**；JS 物件解構如 `{ parseEnv }` 也不在 verify 範圍
  banned: 從記憶寫骨架 / 跳過 Read templates/skeleton.cjs / 漏掉骨架預設的 helpers require 任一項
```

##### PLACEHOLDER 替換清單

| Placeholder | 來源 | 範例 |
|---|---|---|
| `{ISSUE_KEY}` | branch / Jira issue key | `LVB-7963` |
| `{一句話描述}` | test plan 標題 | `結案原因下拉選項驗證` |
| `{root cause 一兩行摘要}` | `.claude/{ISSUE_KEY}.md` Root cause 段 | `R18 enum 漏 4 項 (9/10/11/12)` |
| `{file path}` + `{修正摘要}` | issue 對應 PR diff（可多筆） | `src/.../CaseClose.tsx：補 enum 9-12` |
| `{頁面路徑}` + `{預期結果}` | test plan「驗證情境」 | `/homecareCaseClose/{caseId}`、`完整 14 項可選` |
| `{fixture env var}` | cjs 需要的業務 fixture | `CASE_ID` / `DAYCARE_CASE_ID` |
| `<paste-staging-case-id>` | staging 穩定 fixture（S8.4 規範） | `a3f2c891-...` |
| `'/path/to/entry/{caseId}'` | entryPath，**保留 `{caseId}` runtime 佔位**（由 parseEnv 自動代入 `process.env.CASE_ID`） | `'/homecareCaseClose/{caseId}'` |
| `{fixture 來源說明}` | fixture 性質一句話 | `「已結案」狀態居服個案，staging 穩定存在` |
| `{場景一名稱}` | test plan A 區場景名 | `下拉選項驗證` |

##### 步驟區塊填充

骨架預留三處示範供參考：
- 入口 step `A1.1 頁面載入` — 示範三合一寫法（`waitForSelector` + `isVisible` + `injectEvidence`）
- 註解區範例 `A2.1` — 純資料斷言用 `expandSelectAsListbox` 補 UI 證據（規範 (a)）
- finally 區 — 已包好 `writeResultsJson` / `printSummary` / `exitCodeForResults`

依 test plan 在 `=== 測試步驟區塊 ===` section 之間加 step()。遵守下方「寫腳本準則」+ S3.5 三合一規範 + S3.6 機構切換（若 case 屬非 compal）。

##### 維護 skeleton.cjs

- 修 `templates/skeleton.cjs` 要同步更新本段 PLACEHOLDER 清單
- 新增的 placeholder 一律 `{ }` 包起（或 `<…>` 形式如 `<paste-staging-case-id>`）讓 grep 可命中未替換位置
- 改動需在 CHANGELOG 記版本

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

**LVB-7963 範本重構（示範三合一）**：範例 cjs 見 [`templates/snippets/three-in-one.cjs`](./templates/snippets/three-in-one.cjs)（v2.5.2+ 抽出），含 A3.2 / A3.3 兩個 step：
- **A3.2**：純資料斷言用 (b) 逐一 `selectOption` 補 UI 證據（必要選項皆可選取）
- **A3.3**：純資料斷言用 (a) `expandSelectAsListbox` 強制 listbox 展開（完整 14 項視覺呈現）

**Cleanup 鐵則**（自 v2.4.5 起強制，AI-parsing 結構化 v2.4.7+）：

```
CLEANUP-EVIDENCE-BEFORE-UI:
  rule: 同 step 內 injectEvidence 之後若還有任何 UI 互動，動作前必須 await clearEvidence(p)
  triggers: closeModal / .click() / .fill() / .selectOption() 等任何點按互動
  why: #e2e-evidence-panel 注入在 viewport 右上角 fixed 定位，Modal 寬度大時會 intercept pointer events → Playwright click 60 次 retry 全被擋 → 30s timeout step FAIL（功能本身沒 bug、人工點得下去）
  case: ERPD-11841 A8「重開 selectedCase 為空」injectEvidence 後直接 closeModal(p) → staging 100% 重現 timeout，error log = "<div>…</div> from <div id='e2e-evidence-panel'>…</div> subtree intercepts pointer events"
  inverse-evidence: 同 cjs A4 / A7 PASS 因 closeModal 在 injectEvidence「之前」執行，順序不同沒踩到
```

正確 pattern 範例見 [`templates/snippets/cleanup-evidence.cjs`](./templates/snippets/cleanup-evidence.cjs)（v2.5.2+ 抽出），含兩個 case：
- **case 1**：step 結尾要 `closeModal` — `injectEvidence` 後、`closeModal` 前 `clearEvidence`
- **case 2**：step 結尾要 cancel modal — 同理（step 開頭 `clearEvidence` 清前一輪即可）

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

**cjs 整合範本**：範例 cjs 見 [`templates/snippets/org-switch.cjs`](./templates/snippets/org-switch.cjs)（v2.5.2+ 抽出），兩種寫法依需要選一：

- **推薦版**：A0 / Z9 step 結構，切換動作也進 evidence；finally 區用 try/catch 包，避免切回失敗中斷收尾
- **簡化版**：不註冊成 step、純前後切換（無 evidence overlay）

REQUIRED_ORG 寫法：`keyword` 帶 internal code（如 `'compal'`）或顯示名片段（如 `'豐原'`，要過濾結果唯一）；`expectedDisplay` 是切後右上角 `.list-dropdown-text` 真正顯示文字。

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

```
UPLOAD-FLOW:
  auth: Basic（從 .env.local 讀 ATLASSIAN_EMAIL / ATLASSIAN_API_TOKEN / ATLASSIAN_SITE 組）
  endpoint: POST https://{site}/rest/api/3/issue/{issueKey}/attachments
  headers: Authorization=Basic <auth> | X-Atlassian-Token=no-check
  body: FormData(file=Blob[png], filename=screenshot.png)
  iterate: 逐張 upload，記下回傳 attachment id
  note: attachment id 留作確認用；inline 顯示只用 filename
  phase-B-write: 每張上傳成功 → Edit progress.md Phase B 條目 [x] + 記 attachment id
  resume-behavior: --resume → 跳過 Phase B 已 [x] 的截圖（避免重複 attachment）
```

範例 code（node fetch + FormData）：

```javascript
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

### 步驟 7：發 inline comment（**核心 know-how**）

```
COMMENT-FLOW:
  core-knowhow: MCP addCommentToJiraIssue 走 ADF v3，attachment ID 不能直接當 media id → ATTACHMENT_VALIDATION_ERROR
  correct: REST API v2 + wiki markup → 後端自動把 !filename! 轉成正確 ADF mediaSingle node（含真正 media UUID）
  endpoint: POST https://{ATLASSIAN_SITE}/rest/api/2/issue/{issueKey}/comment
  headers: Authorization=Basic <auth> | Content-Type=application/json
  body: JSON.stringify({ body: wiki })   # wiki = wiki markup 字串
  banned: REST v3（不接受 wiki）
  wiki-syntax: 見 docs/wiki-markup.md；comment 結構見 docs/comment-template.md
  script-mode-extra: comment 加 執行時間 / variant(r15 vs r18) / console error 數(_results.json.consoleErrors.length) / fail step error
  phase-C-write: comment POST 成功 → Edit progress.md Phase C [ ] → [x] + 記 comment id
  resume-behavior: Phase C 已 [x] = 上次發過 → 預設 append 新 comment（避免覆蓋人工修改）；或 PUT 覆蓋（依使用者意圖）
```

範例 code（wiki markup body + REST v2 POST）：

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

### 步驟 8：publish 到 release-tests（腳本模式強制）

腳本模式跑完 Phase A/B/C 後，**強制執行**將 cjs 轉成 release-tests 形態（讓 GitHub Actions release-e2e workflow 能跑）。互動模式不適用（未產 cjs）。

#### S8.1 機械改動清單（v2.4.4+ 大幅簡化）

```
PATCH-LIST:
  copy: .claude/{ISSUE_KEY}-test.cjs → <repo-root>/e2e/release-tests/{ISSUE_KEY}.cjs
  patch-count: 1（v2.4.4+ 骨架全面 helpers 化後）
  patch-1:
    target: HELPERS_DIR fallback
    from: path.join(os.homedir(), '.claude/skills/jira-test-report/helpers')
    to: path.join(__dirname, '_helpers')   # vendor 副本，release-tests 自帶
  pre-handled-by-skeleton: [chromium-require, SCREENSHOT_DIR, env-local-load, progress-silent, 檔頭格式, step-中文化]
```

骨架已預先處理的 6 項（為何不再需要 publish 時手動改）：

| 原 # | 項目 | 為何不再需要 |
|---|---|---|
| 2 | chromium require | 骨架不直接 require playwright，全由 `launchBrowser` 從 helpers 內 node_modules 拿 |
| 3 | SCREENSHOT_DIR | `parseEnv` 自動處理 `SCREENSHOT_BASE_DIR` env var（v0.4.0+），CI 設 `SCREENSHOT_BASE_DIR=.` 即可 |
| 4 | .env.local 自動載入 | 骨架不寫此邏輯（依 release-tests/README 規範由 shell 預先 `set -a; source .env.local; set +a`） |
| 5 | progress.md 寫入 | `createStepRunner` 內部已 silent（`progressPath` 對應檔案不存在時 noop） |
| 6 | 檔頭格式 | 骨架已為 LVB-7963 風格 6 段（root cause / 修正 / 驗證情境 / 用法 / 前置 / exit codes） |
| 7 | step 中文化 | 骨架已用 5 參數中文版簽名 |

```
PUBLISH-VERIFY-GREP:
  grep-1: step(page, → 全 5 參數（caseId + 中文短名 + 中文長描述 + fn）；非中文 / 4 參數需補
  grep-2: injectEvidence|expandSelectAsListbox|clearEvidence → 斷言 step 都有注入 evidence（三合一規範）
  target: <release-tests>/{KEY}.cjs
```

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
| **publish 後（每次改 cjs）** | release-tests 位置 + staging URL | release-tests 環境 wiring 正確 + staging 已部署該功能 | 從 `frontend/` 跑：`set -a; source .env.local; set +a; BASE_URL=$STAGING_URL node ../e2e/release-tests/{ISSUE_KEY}.cjs` |

```
DUAL-ENV-URLS:
  declare-in: .env.local（兩組同時宣告）
  BASE_URL: http://localhost:3000           # local dev server
  STAGING_URL: https://lunastaging.compal-health.com   # staging (release-e2e workflow 同源)
  switch-by: BASE_URL=$STAGING_URL 前綴覆寫（不需改 cjs）
  ci-naming: 對齊 secrets.E2E_STAGING_URL
  skip-staging-when: feature branch 尚未 merge 進 master / staging 未部署該 commit
  skip-action: 標註「Staging 驗證待 staging 部署該 commit 後再跑」
```

#### S8.4 測試 fixture 管理（CASE_ID / DAYCARE_CASE_ID 等業務輸入）

```
FIXTURE-STRATEGY:
  primary: hardcode-staging-default + env-override
  fallback: github-variables-json-map
  applies-to: cjs 需要業務 fixture（如 LVB-7963 需「已結案個案 ID」）
  guard: 缺必填 env 必 exit 4（MISSING_ENV，對齊 LVB-7963 exit code 規範）
```

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

```
HARDCODE-DEFAULT:
  pros:
    - cjs = 自帶測試規格（看 cjs 即知測哪個個案，不必跨檔 trace Variables / yml）
    - 新增 cjs 只需 1 PR（不必再開第 2 PR 設 Variable）
    - 本地仍可 env override 走自己 dev db 個案
    - 個案 id 過期時 git blame 找得到當初是誰加的
  applies-when:
    - 個案 uuid 不含個資（純機器生成 id）— luna 符合
    - staging db 不常重建、fixture 穩定
```

##### Fallback：GitHub Variables JSON map（hardcode 不適用時）

```
JSON-MAP-FALLBACK:
  applies-when: 公司政策禁止測試資料 commit 進 git
  storage: GitHub Variables 名為 RELEASE_TEST_FIXTURES，value 為 JSON map
  key: issue key（如 LVB-7963）；value: env map（如 { CASE_ID, DAYCARE_CASE_ID }）
  ci-decode: release-e2e.yml matrix step 用 jq export 為 $GITHUB_ENV
  local-decode: .env.local 用 generic 名（如 CASE_ID=abc123）
  cjs-side: 只讀 generic env，本地與 CI 程式碼一致
```

範例 JSON map：

```
Name: RELEASE_TEST_FIXTURES
Value:
{
  "LVB-7963": { "CASE_ID": "case_uuid_1", "DAYCARE_CASE_ID": "case_uuid_2" },
  "CUP-180":  { "CASE_ID": "case_uuid_3" },
  "ERPD-11841": {}
}
```

workflow yml 解碼片段：

```yaml
- name: Load fixtures for ${{ matrix.issue }}
  shell: bash
  env:
    FIXTURES: ${{ vars.RELEASE_TEST_FIXTURES }}
    ISSUE: ${{ matrix.issue }}
  run: |
    echo "$FIXTURES" | jq -r --arg k "$ISSUE" '.[$k] // {} | to_entries[] | "\(.key)=\(.value)"' >> "$GITHUB_ENV"
```

##### 缺 fixture 的 guard

```
MISSING-ENV-GUARD:
  shared-by: [hardcode-default, json-map-fallback]
  rule: 缺必填 env → exit 4（MISSING_ENV）→ 不跑下去
  hardcode-note: 通常不會 trigger（default 已注入），留著以防有人手動 unset
```

```javascript
if (!process.env.CASE_ID) {
  console.error('MISSING_ENV: CASE_ID required');
  process.exit(4);
}
```

#### S8.5 機械步驟（v2.4.4+ 因 helpers 已收斂，步驟精簡）

```
PUBLISH-PIPELINE:
  step-1-detect-root: git rev-parse --show-toplevel
  step-2-check-release-tests: <root>/e2e/release-tests/ 含 _helpers/(vendor) | on-missing: abort+提示「結構未建立」
  step-3-check-helpers:
    list: [env.cjs, step.cjs, modal.cjs, browser.cjs, report.cjs, evidence.cjs]
    on-missing: ~/.claude/skills/cup-build-test/scripts/sync-helpers.sh --force（master → 所有 mirrors）
    legal-state: _helpers/ 只含 node_modules/ 沒 cjs 也合法（首次 publish 常見），不中止
  step-4-copy: cp .claude/{ISSUE_KEY}-test.cjs <root>/e2e/release-tests/{ISSUE_KEY}.cjs
  step-5-patch: 套 S8.1 PATCH-LIST.patch-1（Edit 工具）| extra: 移除 const os = require('os')
  step-6-fixture: 若 cjs 需 fixture → primary: S8.4 HARDCODE-DEFAULT | fallback: S8.4 JSON-MAP-FALLBACK
  step-7-grep-check: 套 S8.1 PUBLISH-VERIFY-GREP
  step-8-verify-local: 套 S8.3 publish-前（pre-condition: 當前 branch 應含 feature commit）
  step-9-verify-staging: staging 已部署 → 套 S8.3 publish-後 | 未部署 → 標註「待 staging 部署該 commit 後再驗」
  step-10-prompt-user: 「PR 開出 / push 後可手動觸發 release-e2e workflow 對 staging 跑」
```

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

完整語法表見 [`docs/wiki-markup.md`](./docs/wiki-markup.md)（v2.5.3+ 抽出）。

**最常用**：`h2. 標題` / `h3. 標題` / `*粗體*` / `----` 分隔線 / `!file.png|width=900!` inline 截圖 / `|| header ||` 表頭 + `| cell |` 表格。

**關鍵紀律**：

- endpoint 必須 **REST v2**（v3 不接受 wiki）：`/rest/api/2/issue/{key}/comment`
- 標題 `h2.` / `h3.` 後面**要有空格**才生效
- Code block `{code}...{code}` 內部不解析任何字串

## Comment 結構建議

完整範本（含區塊說明、腳本模式建議補充、簡化範例）見 [`docs/comment-template.md`](./docs/comment-template.md)（v2.5.3+ 抽出）。

**標準骨架**：

1. `h2.` 摘要一行（環境 + 結果 + 模式）
2. `----` 分隔
3. 各 step `h3. N. 步驟標題` + 說明 + `!filename|width=900!` inline 截圖
4. `----` 分隔
5. `h3. 邏輯驗證表`（純資料斷言整合，可選）
6. `----` 分隔
7. `h3. 結論`（通過 / 失敗 + 重點觀察）

## 失敗處理

完整 symptom 清單（含 `cause` / `why` / `banned` / `note` 細節）見 [`docs/troubleshooting.md`](./docs/troubleshooting.md)（v2.5.4+ 抽出）。

**速查表**（symptom → 一行 action，常見錯誤掃這裡）：

| Symptom | 一行 Action |
|---|---|
| `LOGIN-4xx` | 驗證 `.env.local`（不要在對話貼密碼） |
| `LOGIN-5xx` | retry 一次 → 仍失敗中止 |
| `UPLOAD-401` | token 失效 → 重新驗證 |
| `COMMENT-ATTACHMENT-VALIDATION` | 改回 v2 wiki（誤用 v3 ADF + attachment id） |
| `SCREENSHOT-ACCESS-DENIED` | filename 改寫進 `frontend/` 內（MCP 限制） |
| `SESSION-EXPIRED` | 不該發生；若有則縮短測試或加 keep-alive |
| `PLAYWRIGHT-MODULE-MISSING` | `cd helpers && npm install && npx playwright install chromium` |
| `SELECTOR-NOT-FOUND` | `HEADLESS=false` 重跑看實際畫面 |
| `RATE-LIMIT` | 不要閒置等待；`/clear` 後 `--resume` 從 progress.md 接續 |
| `RESUME-NO-PROGRESS` | 提示「尚未跑過，去掉 `--resume`」 |
| `PROGRESS-ISSUE-MISMATCH` | 中止，提示「進度檔屬於別的 issue」 |

## 參考做法（記憶提示）

- 第一次用這個 skill 的完整成功 case：ERPD-11841（2026-05-04），12 張截圖全 inline，互動模式
- 腳本模式首發 case：CUP-80（2026-05-07），活動行事曆 R18 回歸驗證
- attachment 上傳 endpoint v3 OK，但 comment 要用 v2 wiki 才能 inline
- 不要嘗試從 attachment redirect 拿 media UUID 自己拼 ADF，太繞且 location header 可能被 CDN 截斷
- 互動模式截圖**必指定 filename**，否則 base64 入 context 噴 token

---

## Changelog

歷史變更紀錄已抽到 [./CHANGELOG.md](./CHANGELOG.md)（v2.0.0 起的完整版本歷史）。

**最近版本**（詳細見 CHANGELOG.md）：

- **v2.5.5**（2026-05-22）— 剩餘 prose 段落 AI.MD v4 結構化（P1-P5），token -220
- **v2.5.4**（2026-05-22）— 失敗處理抽到 `docs/troubleshooting.md`，SKILL.md 再瘦 -35 行
- **v2.5.3**（2026-05-22）— Wiki Markup 速查 + Comment 範本抽到 `docs/`，SKILL.md 再瘦 -20 行
- **v2.5.2**（2026-05-22）— S3.5 / S3.6 範例 cjs 抽到 `templates/snippets/`，SKILL.md 再瘦 -115 行
- **v2.5.1**（2026-05-22）— progress.md 範本 + .env.local 範例抽到 `templates/`，SKILL.md 再瘦 -35 行
