// ============================================================================
// jira-test-report skill — cjs 骨架範本（v2.5.0+）
// ============================================================================
// 用法：
//   1. 由 /jira-test-report skill 在步驟 S3 自動 Read 本檔
//   2. 套用 SKILL.md「PLACEHOLDER 替換清單」做字串替換
//   3. 在 try{} 區塊內依 test plan 加 step()
//   4. Write 到 .claude/{ISSUE_KEY}-test.cjs
//
// 維護：
//   - 修這個檔 → 同時更新 SKILL.md「PLACEHOLDER 替換清單」表
//   - 新增的 placeholder 一律用 { } 包起（如 {ISSUE_KEY}）或 <…> 形式（如 <paste-staging-case-id>）
//     確保產 cjs 時 grep 可命中所有未替換位置
//   - 不要直接 node 跑本檔，placeholder 字串會炸
// ============================================================================

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
