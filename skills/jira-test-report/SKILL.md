---
name: jira-test-report
description: "對 Jira issue 跑 Playwright E2E 測試，自動截圖並 inline 上傳到 issue comment（截圖直接顯示在留言中，非附件清單）。當使用者提到 /jira-test-report、「跑測試報告」、「驗收測試上 Jira」、「截圖到 Jira」、「自動化測試 + Jira」、想對某個 issue 跑驗收測試並把結果留在 Jira 時觸發。"
version: 2.1.0
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
| Atlassian API token | https://id.atlassian.com/manage-profile/security/api-tokens |
| Atlassian email | 對應 Jira 帳號的 email |
| dev server 已啟動 | `npm run dev` 或專案對應命令 |
| 登入 session | `.playwright-auth/auth.json` 存在；無則跑一次互動模式產生 |
| 測試步驟來源 | `.claude/{ISSUE_KEY}.md` / `.claude/{ISSUE_KEY}-test-plan.md` 的「測試步驟」section |
| Playwright 可用 | 互動模式：playwright MCP plugin；腳本模式：`playwright` npm package（`npx playwright install chromium` 一次） |

**Token / email**：使用者貼到對話中即可（用完提醒撤銷）。

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

打 `/rest/api/3/myself`，回 displayName 即過。失敗時讓使用者重給 token。

### 步驟 3：讀測試步驟

從 `.claude/{ISSUE_KEY}.md` 拿「## 測試步驟」section。沒這個檔就讓使用者口述步驟。

### 步驟 4：登入 + 存 storageState（Playwright MCP）

```
mcp__plugin_playwright_playwright__browser_navigate({ url: <dev URL> })
→ 自動填帳號密碼
→ 暫停讓使用者填驗證碼
→ browser_run_code_unsafe: page.context().storageState({ path: '.playwright-auth/auth.json' })
→ 把 .playwright-auth/ 加 .gitignore
```

### 步驟 5：跑測試 + 截圖

依測試步驟逐項操作，每步存截圖到專案根目錄下 **暫存資料夾**（不能在 frontend 之外，Playwright MCP 有 root 限制）：

```
mkdir -p {ISSUE_KEY}-temp
filename: {ISSUE_KEY}-temp/01-xxx.png, 02-xxx.png, ...
```

命名規則：`{流水號}-{語意描述}.png`，流水號保 2 位數方便 sort。

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

### 步驟 S2：讀測試步驟 + 確認 storageState 存在

```bash
test -f .playwright-auth/auth.json || echo "NEED_LOGIN"
```

若無，先請使用者跑一次互動模式登入，或手動執行：
```bash
npx playwright codegen --save-storage=.playwright-auth/auth.json <DEV_URL>
```

### 步驟 S3：生成 Playwright 腳本

寫到 `.claude/{ISSUE_KEY}-test.cjs`（用 Write 工具，不要用 ctx_execute）：

#### 進階用法：引用 cup-build-test helpers（v2.1.0+ 推薦）

`~/.claude/skills/jira-test-report/helpers/` 從 cup-build-test sync 來（master：`~/.claude/skills/cup-build-test/helpers/`，用 `~/.claude/skills/cup-build-test/scripts/sync-helpers.sh` 同步）。

luna 系統測試常撞的三類問題，**helper 已抽出統一處理**，建議產出 cjs 時引用以省下 inline 維護成本：

| 場景 | 用 helper 取代 inline | Helper |
|---|---|---|
| 進入頁面後跳公告 modal（`.latest-release-rote-modal` / `.FeatureTermsOfUseModal` 攔截 click）| `await waitAndDismissOnEntry(page)` / `await dismissAnnouncement(page)` | `helpers/modal.cjs` |
| mutation step 連跑時前 case 留下 modal 殘留，新 modal 開不起來 | `await ensureCleanState(page)` 加在 step 入口 | `helpers/modal.cjs` |
| 二次確認對話（「改動此日期...」「確認刪除嗎?」這類「是/否」按鈕）| `await confirmYes(page)` / `await confirmNo(page, { scope })` | `helpers/confirmDialog.cjs` |

**首次 setup**（一次性，跟 cup-build-test 共用 chromium driver，無重複安裝成本）：

```bash
cd ~/.claude/skills/jira-test-report/helpers
npm install                       # 拉 playwright
npx playwright install chromium   # 跟 cup-build-test 共用 ~/Library/Caches/ms-playwright/
```

**引用範例**（在「腳本骨架」require 之後加）：

```javascript
const path = require('path');
const os = require('os');
const HELPERS_DIR = process.env.CUP_HELPERS_DIR
  || path.join(os.homedir(), '.claude/skills/jira-test-report/helpers');
const { waitAndDismissOnEntry, dismissAnnouncement, ensureCleanState } = require(path.join(HELPERS_DIR, 'modal.cjs'));
const { confirmYes, confirmNo } = require(path.join(HELPERS_DIR, 'confirmDialog.cjs'));

// 用法：
// 1. 進入頁面後第一件事
await waitAndDismissOnEntry(page);

// 2. mutation step 入口（避免前 case modal 殘留）
await ensureCleanState(page);

// 3. 點儲存後跳「改動此日期可能會造成統計資料的改動」確認對話
await page.locator('button:has-text("儲存")').click();
await confirmYes(page);

// 4. 點刪除後彈確認對話 → 取消
await page.locator('.btn-danger').first().click();
await confirmNo(page, { scope: page.locator('.modal.show') });
```

完整 API 參考：`~/.claude/skills/cup-build-test/SKILL.md`「Helper API 速查」段。

> 💡 **既有 cjs 不強制升級** — 既有測試在 inline 寫 modal handling 也能跑，但新產 cjs 建議用 helpers 共享 cup-build-test 累積的修正。

---

**腳本骨架**（依測試步驟填充 `// === 測試步驟區塊 ===` 內容）：

```javascript
// .claude/{ISSUE_KEY}-test.cjs
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ISSUE_KEY = '{ISSUE_KEY}';
const VARIANT = process.env.VARIANT || 'r18';      // r15 / r18 比對用
const SCREENSHOT_DIR = `.claude/${ISSUE_KEY}-temp/${VARIANT}`;
const AUTH_PATH = '.playwright-auth/auth.json';
const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
const HEADLESS = process.env.HEADLESS !== 'false';
// RESUME_FROM_IDX：跨 session 續跑用（跳過 step idx ≤ RESUME_FROM_IDX 的 step）
const RESUME_FROM_IDX = Number(process.env.RESUME_FROM_IDX || 0);
const PROGRESS_PATH = `.claude/${ISSUE_KEY}-progress.md`;

const results = [];

function logResult(r) {
  // 一行 JSON，方便外部工具 parse
  console.log(JSON.stringify(r));
  results.push(r);
}

/**
 * 跨 session 進度檔更新：把 progress.md 內 step idx 對應條目從 [ ] 改 [x] 並填欄位
 * 失敗時 silent（progress.md 不存在或格式異常都不影響主流程）
 */
function updateProgressMd(idx, name, fields) {
  if (!fs.existsSync(PROGRESS_PATH)) return;
  try {
    const content = fs.readFileSync(PROGRESS_PATH, 'utf8');
    // STEP A: 匹配「- [ ] {idx} {name}」開頭的整個 step block（含後續的 - Status/Screenshot/Run at 行）
    const blockRe = new RegExp(
      `(^- \\[[ x]\\] ${idx} [^\\n]*$)(\\n  - [^\\n]*$)*`,
      'm',
    );
    const match = content.match(blockRe);
    if (!match) return;
    const newHeader = match[1].replace('[ ]', '[x]');
    const newBlock =
      `${newHeader}\n` +
      `  - Status: ${fields.status}\n` +
      `  - Screenshot: ${fields.screenshot}\n` +
      `  - Run at: ${fields.runAt}`;
    let updated = content.replace(blockRe, newBlock);
    if (/^Last update: /m.test(updated)) {
      updated = updated.replace(/^Last update: .*$/m, `Last update: ${fields.runAt}`);
    }
    fs.writeFileSync(PROGRESS_PATH, updated);
  } catch {
    // STEP B: progress.md 寫入失敗不阻斷測試
  }
}

async function step(page, name, fn) {
  const idx = String(results.length + 1).padStart(2, '0');
  // RESUME_FROM_IDX skip：跨 session 續跑時跳過已完成 step（注意：results.push 也跳過，保持 idx 對應）
  if (RESUME_FROM_IDX && Number(idx) <= RESUME_FROM_IDX) {
    results.push({ step: idx, name, status: 'SKIPPED_RESUME' });
    return;
  }
  const safeName = name.replace(/[^\w-]+/g, '-');
  const screenshot = `${idx}-${safeName}.png`;
  const screenshotPath = path.join(SCREENSHOT_DIR, screenshot);
  const t0 = Date.now();
  let stepStatus = 'PASS';
  let stepError = null;
  try {
    await fn(page);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    logResult({ step: idx, name, status: 'PASS', screenshot, ms: Date.now() - t0 });
  } catch (e) {
    stepStatus = 'FAIL';
    stepError = e.message;
    try { await page.screenshot({ path: screenshotPath, fullPage: true }); } catch {}
    logResult({ step: idx, name, status: 'FAIL', screenshot, error: e.message, ms: Date.now() - t0 });
    if (process.env.STOP_ON_FAIL === 'true') {
      updateProgressMd(idx, name, {
        status: `FAIL: ${stepError}`,
        screenshot: screenshotPath,
        runAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      });
      throw e;
    }
  }
  // 每跑完一個 step 立刻寫 progress.md（cross-session resume）
  updateProgressMd(idx, name, {
    status: stepStatus === 'PASS' ? 'PASS' : `FAIL: ${stepError}`,
    screenshot: screenshotPath,
    runAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
  });
}

(async () => {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: HEADLESS });
  const context = await browser.newContext({
    storageState: AUTH_PATH,
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  // Console error 收集（不入主 context，只寫檔）
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));

  try {
    await page.goto(BASE_URL + '/activityManager/activityCalendar', { waitUntil: 'networkidle' });

    // === 測試步驟區塊（依 test plan 填充） ===
    await step(page, 'page-loaded', async (p) => {
      await p.waitForSelector('.fc-toolbar, [class*="calendar"]', { timeout: 15000 });
    });

    // 範例：點某天加號 → 開新增 modal
    // await step(page, 'click-add-button', async (p) => {
    //   await p.locator('th:has-text("3") .glyphicon-plus').first().click();
    //   await p.waitForSelector('.modal.in', { timeout: 5000 });
    // });
    // === 測試步驟區塊結束 ===

  } finally {
    await browser.close();
  }

  fs.writeFileSync(path.join(SCREENSHOT_DIR, '_results.json'), JSON.stringify({
    issueKey: ISSUE_KEY,
    variant: VARIANT,
    baseUrl: BASE_URL,
    results,
    consoleErrors,
    summary: {
      total: results.length,
      pass: results.filter(r => r.status === 'PASS').length,
      fail: results.filter(r => r.status === 'FAIL').length,
    },
  }, null, 2));

  const pass = results.filter(r => r.status === 'PASS').length;
  console.log(`\nDONE: ${pass}/${results.length} PASS, console errors: ${consoleErrors.length}`);
  if (results.some(r => r.status === 'FAIL')) process.exit(1);
})();
```

**寫腳本準則**：
- 一個 `step()` 對應一個測試斷言，**截圖只在 step 結束時拍一次**（含 fail 時也拍），不要在 step 中間額外截圖
- selector 優先用 `data-testid` > `getByRole` > 文字 > class，最後才 nth-child
- `page.locator(...)` 鏈式呼叫，不要存中間變數（locator 是 lazy 的）
- 等待用 `waitForSelector` / `waitForLoadState`，**不要** `page.waitForTimeout(N)` 死等
- 不可逆操作（建立、刪除）要在 try/catch 包起來，避免污染下次測試資料

### 步驟 S4：執行腳本

```bash
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

```javascript
// node fetch + FormData
const fd = new FormData();
fd.append("file", new Blob([buf], { type: "image/png" }), filename);
await fetch(`https://{site}.atlassian.net/rest/api/3/issue/${issueKey}/attachments`, {
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

await fetch(`https://{site}.atlassian.net/rest/api/2/issue/${issueKey}/comment`, {
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

### 步驟 8：清理

```bash
rm -rf .claude/{ISSUE_KEY}-temp
# 腳本檔案保留在 .claude/{ISSUE_KEY}-test.cjs，下次回歸可重跑
# progress.md 預設保留作為執行歷史，使用者下次跑全新 issue 前可手動刪除
```

`.playwright-auth/auth.json` **保留**（下次重用 session）。
`.claude/{ISSUE_KEY}-progress.md` **預設保留**（執行歷史紀錄）；下次跑同 issue 全新流程前用 `rm` 或選擇 `[2] 刪除舊檔，重跑完整流程`。

### 步驟 9：提醒撤銷 token

最後一定提醒使用者去 https://id.atlassian.com/manage-profile/security/api-tokens 撤銷剛才用的 token。

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

- **Login redirect 但驗證碼錯**：請使用者重填，重存 storageState
- **Upload 401**：token 失效，重新驗證
- **Comment 400 ATTACHMENT_VALIDATION_ERROR**：誤用 v3 ADF + attachment id，改回 v2 wiki
- **截圖路徑 access denied（互動模式）**：Playwright MCP 限制只能存到專案根目錄之內，不能存 ~/Desktop
- **session 過期**：刪 `.playwright-auth/auth.json` 重登
- **腳本模式 `Cannot find module 'playwright'`**：在專案根目錄跑 `npm i -D playwright && npx playwright install chromium`
- **腳本模式 storageState 失效（被導回 login）**：跑互動模式重存 auth.json
- **腳本模式 selector 找不到（R18 升級後）**：用 `HEADLESS=false` 重跑看實際畫面，調整 selector
- **跑到一半 rate limit**：**不要閒置等待**（5 分鐘 prompt cache 會過期，恢復時瞬間燒幾萬 token 重建 cache）。建議：當前 step 跑完後 `/clear` 開新 session，下次用 `/jira-test-report --resume` 從 progress.md 接續（Phase A/B/C 自動接力）
- **`--resume` 但 progress.md 不存在**：提示使用者「尚未跑過，無進度可續，請去掉 `--resume` 旗標」
- **progress.md 存在但 issue key 不符**：中止，提示「進度檔屬於別的 issue」

## 參考做法（記憶提示）

- 第一次用這個 skill 的完整成功 case：ERPD-11841（2026-05-04），12 張截圖全 inline，互動模式
- 腳本模式首發 case：CUP-80（2026-05-07），活動行事曆 R18 回歸驗證
- attachment 上傳 endpoint v3 OK，但 comment 要用 v2 wiki 才能 inline
- 不要嘗試從 attachment redirect 拿 media UUID 自己拼 ADF，太繞且 location header 可能被 CDN 截斷
- 互動模式截圖**必指定 filename**，否則 base64 入 context 噴 token

---

## Changelog

版本號採 [Semver](https://semver.org/lang/zh-TW/)。MAJOR=破壞既有 cjs / 流程行為、MINOR=新增 helper / 模式 / 階段步驟、PATCH=修 bug 或文件更新。

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
