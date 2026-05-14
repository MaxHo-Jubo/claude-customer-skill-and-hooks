// @ts-check
// {{ISSUE_KEY}} {{FEATURE_TITLE}} 回歸測試腳本
//
// 此檔由 /cup-build-test skill 階段 3 自動產出，原始模板：
//   ~/.claude/skills/cup-build-test/templates/test-cjs-template.cjs
//
// 共用邏輯由 helpers/ 提供（env/step/modal/browser/bundle/report），
// 修 bug 或加新功能優先改 helpers/，不要 inline patch 在 cjs。
// Helper API 速查請看 ~/.claude/skills/cup-build-test/SKILL.md「Helper API 速查」段。
//
// 用法（target 專案 0 dep；playwright runtime 由 helpers/ user-level 提供）：
//   node .claude/{{ISSUE_KEY}}-test.cjs
//   HEADLESS=false node .claude/{{ISSUE_KEY}}-test.cjs                          # 看著瀏覽器跑
//   VARIANT=r15 BASE_URL=https://luna.compal-health.com node .claude/{{ISSUE_KEY}}-test.cjs
//   STOP_ON_FAIL=true node .claude/{{ISSUE_KEY}}-test.cjs                       # 第一個 fail 就中斷
//   ONLY=A1 node .claude/{{ISSUE_KEY}}-test.cjs                                 # 只跑指定 case prefix
//   RESUME_FROM=A2.1 node .claude/{{ISSUE_KEY}}-test.cjs                        # 跨 session 續跑：跳過 caseId ≤ A2.1
//
// 前置：
//   1. helpers user-level setup（一次性，跨專案共用）：
//        cd ~/.claude/skills/cup-build-test/helpers && npm install && npx playwright install chromium
//   2. dev server（local 跑時）：npm run dev（預設 localhost:3000）
//   3. 登入態：.playwright-auth/auth.json 存在（無則跑互動模式產生）
//
// 輸出（皆在 .gitignore 內）：
//   stdout: 一行一個 JSON（step / status / screenshot），最後一行 summary
//   .claude/{{ISSUE_KEY}}-temp/<variant>/_results.json 完整報告
//   .claude/{{ISSUE_KEY}}-temp/<variant>/NN-<step>.png 每步截圖
//
// Exit codes：
//   0  全 pass
//   1  有 fail
//   2  AUTH_MISSING（auth.json 不存在）
//   3  AUTH_EXPIRED（被踢回登入頁）
//   4  MISSING_ENV（ENTRY_PATH 含動態參數但 env var 沒設，例 CASE_ID）

const path = require('path');
const os = require('os');

// STEP 01: 載入 cup-build-test helper library
//   helpers/ 預設位於 ~/.claude/skills/cup-build-test/helpers/
//   CI / 鏡像位置可用 CUP_HELPERS_DIR 環境變數覆寫
const HELPERS_DIR = process.env.CUP_HELPERS_DIR
  || path.join(os.homedir(), '.claude/skills/cup-build-test/helpers');

const { parseEnv } = require(path.join(HELPERS_DIR, 'env.cjs'));
const { createStepRunner } = require(path.join(HELPERS_DIR, 'step.cjs'));
const { waitAndDismissOnEntry, dismissAnnouncement, ensureCleanState } = require(path.join(HELPERS_DIR, 'modal.cjs'));
const { confirmYes, confirmNo } = require(path.join(HELPERS_DIR, 'confirmDialog.cjs'));
const { launchBrowser, attachConsoleCollector } = require(path.join(HELPERS_DIR, 'browser.cjs'));
const { detectBundle, assertVariant } = require(path.join(HELPERS_DIR, 'bundle.cjs'));
const { writeResultsJson, printSummary, exitCodeForResults } = require(path.join(HELPERS_DIR, 'report.cjs'));

// STEP 02: 解析環境變數
const env = parseEnv({
  issueKey: '{{ISSUE_KEY}}',
  entryPath: '{{ENTRY_PATH}}', // 例：/activityManager/activityCalendar 或 /case/list/{caseId}/yearlyQuotaSetting
});

// STEP 03: 標記 helper 引用（template 階段未實際呼叫的避免 unused warning）
void dismissAnnouncement;
void detectBundle;
void assertVariant;

(async () => {
  // STEP 04: 環境準備 & 開瀏覽器
  require('fs').mkdirSync(env.screenshotDir, { recursive: true });
  const { browser, page } = await launchBrowser({
    headless: env.headless,
    authPath: env.authPath,
  });

  /** @type {string[]} */
  const consoleErrors = [];
  attachConsoleCollector(page, consoleErrors);

  // STEP 05: 建立 step runner（含 ONLY / RESUME_FROM filter + progress.md 寫入）
  const { step, skipStep, waitStable, getResults } = createStepRunner({
    screenshotDir: env.screenshotDir,
    progressPath: env.progressPath,
    only: env.only,
    resumeFrom: env.resumeFrom,
    stopOnFail: env.stopOnFail,
  });

  try {
    // STEP 06: 進入目標頁面
    await page.goto(env.baseUrl + env.entryPath, { waitUntil: 'networkidle', timeout: 30000 });
    await waitStable(page, 1000);

    // STEP 06.01: 偵測是否被踢回登入頁
    if (/\/login/.test(page.url())) {
      console.error(`AUTH_EXPIRED: redirected to ${page.url()}. Re-login via skill stage 4b.`);
      process.exit(3);
    }

    // STEP 06.02: dismiss 環境級彈窗（公告 modal 攔截 pointer events 會讓後續 step 全 fail）
    //   helper 已內建兩種已知 luna 公告 modal：.latest-release-rote-modal + .FeatureTermsOfUseModal
    //   未來新 modal 直接加進 helpers/modal.cjs 的 DEFAULT_ANNOUNCEMENT_SELECTORS
    await waitAndDismissOnEntry(page);

    // === 測試步驟區塊（由 skill 階段 3 依 test-plan.md 填入）===
    //
    // selector 優先序：data-testid > getByRole > 文字 > class
    //
    // ---- read-only step 範例 ----
    //   await step(page, 'A1.1', 'page-loaded', async (p) => {
    //     await p.waitForSelector('[data-testid="main-container"]', { timeout: 15000 });
    //   });
    //   await step(page, 'A1.1', 'click-add', async (p) => {
    //     await p.locator('button:has-text("新增")').first().click();
    //     await p.waitForSelector('.modal.in, .modal.show', { timeout: 5000 });
    //     await waitStable(p, 300);
    //   });
    //
    // ---- mutation step 範例（含防禦性 cleanup + 確認對話處理）----
    //   //  注意：mutation step 必須先呼叫 ensureCleanState 避免 case 順序污染
    //   //        （CUP-179 實戰：前面 case 留下 modal 殘留會讓新 modal 開不起來或讀不到值）
    //   await mutationStep('C2.1', 'edit-save-flow', async (p) => {
    //     await ensureCleanState(p);                                            // 防禦性 cleanup
    //     const editBtn = p.locator('table tbody tr')
    //       .filter({ has: p.locator('.btn-warning') })
    //       .nth(0).locator('.btn-warning').first();
    //     await editBtn.click({ force: true });
    //     await p.waitForSelector('.modal.show', { timeout: 5000 });
    //     // ... 改欄位 + 點儲存
    //     await p.locator('.modal.show button:has-text("儲存")').click({ force: true });
    //     // 跳「改動此日期...」二次確認對話 → 點「是」
    //     await confirmYes(p);
    //     await p.waitForSelector('.modal.show', { state: 'hidden', timeout: 8000 });
    //   });
    //
    // ---- 其他常用 helper ----
    //   await dismissAnnouncement(p);                  // navigate 到其他 case 後重複 dismiss
    //   await assertVariant(p, env.variant);           // bundle / variant 驗證
    //   await confirmNo(p, { scope: p.locator('.modal.show') });  // 拒絕確認對話（取消刪除）

    // STEP 06.03: 標記 helper 已被引用（template 階段尚無實際呼叫）
    void step;
    void skipStep;
    void waitStable;
    void ensureCleanState;
    void confirmYes;
    void confirmNo;

    // === 測試步驟區塊結束 ===

  } finally {
    await browser.close();
  }

  // STEP 07: 寫完整結果報告
  const results = getResults();
  writeResultsJson(env.screenshotDir, {
    issueKey: env.issueKey,
    variant: env.variant,
    baseUrl: env.baseUrl,
    results,
    consoleErrors,
  });

  // STEP 08: 印 summary 與決定 exit code
  printSummary(results, consoleErrors);
  process.exit(exitCodeForResults(results));
})();
