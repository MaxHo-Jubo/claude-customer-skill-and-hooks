// {{ISSUE_KEY}} {{FEATURE_TITLE}} 回歸測試腳本
//
// 此檔由 /cup-build-test skill 階段 3 自動產出，原始模板：
//   ~/.claude/skills/cup-build-test/templates/test-cjs-template.cjs
//
// 用法（不需要 npm install playwright）：
//   npx --yes -p playwright@latest node .claude/{{ISSUE_KEY}}-test.cjs
//   HEADLESS=false npx ... node .claude/{{ISSUE_KEY}}-test.cjs       # 看著瀏覽器跑
//   VARIANT=r15 BASE_URL=https://luna.compal-health.com npx ... node .claude/{{ISSUE_KEY}}-test.cjs
//   STOP_ON_FAIL=true npx ... node .claude/{{ISSUE_KEY}}-test.cjs    # 第一個 fail 就中斷
//   ONLY=A1 npx ... node .claude/{{ISSUE_KEY}}-test.cjs              # 只跑指定 case prefix
//
// 前置：
//   1. dev server（local 跑時）：npm run dev（預設 localhost:3000）
//   2. 登入態：.playwright-auth/auth.json 存在（無則跑互動模式產生）
//   3. 第一次執行 npx 會下載 chromium driver，會慢一點
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

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// STEP 01: 解析環境變數與常數
const ISSUE_KEY = '{{ISSUE_KEY}}';
const VARIANT = process.env.VARIANT || 'r18';
const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
const HEADLESS = process.env.HEADLESS !== 'false';
const STOP_ON_FAIL = process.env.STOP_ON_FAIL === 'true';
const ONLY = process.env.ONLY || '';
const SCREENSHOT_DIR = path.join('.claude', `${ISSUE_KEY}-temp`, VARIANT);
const AUTH_PATH = '.playwright-auth/auth.json';
const ENTRY_PATH_TEMPLATE = '{{ENTRY_PATH}}'; // 例：/activityManager/activityCalendar 或 /case/list/{caseId}/yearlyQuotaSetting

// STEP 01.01: 解析 ENTRY_PATH 中的模板變數（{caseId} → process.env.CASE_ID）
function resolveEntryPath(template) {
  return template.replace(/{(\w+)}/g, (_, key) => {
    const envKey = key.replace(/([A-Z])/g, '_$1').toUpperCase();
    const value = process.env[envKey];
    if (!value) {
      console.error(`MISSING_ENV: ${envKey} required for ENTRY_PATH ${template}`);
      process.exit(4);
    }
    return value;
  });
}
const ENTRY_PATH = resolveEntryPath(ENTRY_PATH_TEMPLATE);

// STEP 02: 結果收集
const results = [];
const consoleErrors = [];

function logResult(r) {
  console.log(JSON.stringify(r));
  results.push(r);
}

/**
 * 執行單一測試步驟，自動截圖與計時
 * @param {import('playwright').Page} page
 * @param {string} caseId 測試案例編號（如 A1.1）
 * @param {string} name 步驟名稱
 * @param {(p: import('playwright').Page) => Promise<void>} fn
 */
async function step(page, caseId, name, fn) {
  if (ONLY && !caseId.startsWith(ONLY)) {
    return;
  }
  const idx = String(results.length + 1).padStart(2, '0');
  const safeName = `${caseId}-${name}`.replace(/[^\w.-]+/g, '-');
  const screenshot = `${idx}-${safeName}.png`;
  const screenshotPath = path.join(SCREENSHOT_DIR, screenshot);
  const t0 = Date.now();
  try {
    await fn(page);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    logResult({ step: idx, caseId, name, status: 'PASS', screenshot, ms: Date.now() - t0 });
  } catch (e) {
    try {
      await page.screenshot({ path: screenshotPath, fullPage: true });
    } catch {
      // STEP 02.01: 連截圖都失敗就放棄，不要再吞 error
    }
    logResult({
      step: idx,
      caseId,
      name,
      status: 'FAIL',
      screenshot,
      error: e.message,
      ms: Date.now() - t0,
    });
    if (STOP_ON_FAIL) {
      throw e;
    }
  }
}

/**
 * 等待網路閒置 + modal/網頁 transition 結束
 * Bootstrap modal (.modal.fade.in) 有 transition 動畫，需等結束
 * @param {import('playwright').Page} page
 * @param {number} ms 額外等待時間（預設 500ms）
 */
async function waitStable(page, ms = 500) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(ms);
}

(async () => {
  // STEP 03: 環境準備
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  if (!fs.existsSync(AUTH_PATH)) {
    console.error(`AUTH_MISSING: ${AUTH_PATH} not found. Run skill stage 4b to login first.`);
    process.exit(2);
  }

  const browser = await chromium.launch({ headless: HEADLESS });
  const context = await browser.newContext({
    storageState: AUTH_PATH,
    viewport: { width: 1440, height: 900 },
    locale: 'zh-TW',
  });
  const page = await context.newPage();

  // STEP 04: 收集 console / pageerror（不入主 context，只寫檔）
  page.on('console', m => {
    if (m.type() === 'error') {
      consoleErrors.push(`[console.error] ${m.text()}`);
    }
  });
  page.on('pageerror', e => {
    consoleErrors.push(`[pageerror] ${e.message}`);
  });

  try {
    // STEP 05: 進入目標頁面
    await page.goto(BASE_URL + ENTRY_PATH, { waitUntil: 'networkidle', timeout: 30000 });
    await waitStable(page, 1000);

    // STEP 05.01: 偵測是否被踢回登入頁
    if (/\/login/.test(page.url())) {
      console.error(`AUTH_EXPIRED: redirected to ${page.url()}. Re-login via skill stage 4b.`);
      process.exit(3);
    }

    // STEP 05.02: dismiss 環境級彈窗（公告 / 引導 / Tooltip）— 攔截 pointer events 會讓後續 step 全 fail
    // 雙保險：先 click 「確認」，再 nuclear DOM remove（click 不一定生效因 fade-in 動畫）
    try {
      const confirmBtn = page.locator('button:has-text("確認"), button:has-text("我知道了"), button:has-text("關閉")').first();
      if (await confirmBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
        await confirmBtn.click().catch(() => {});
        await waitStable(page, 300);
      }
    } catch {
      // STEP 05.02.01: click 失敗無妨，下面 nuclear 會處理
    }
    await page.evaluate(() => {
      // STEP 05.02.02: nuclear remove — luna 公告 modal class 已知為 latest-release-rote-modal、其他 R15/R18 通用
      const selectors = [
        '.latest-release-rote-modal',
        '.modal-backdrop',
        '.modal.in:not([data-keep])',
        '.modal.show:not([data-keep])',
        '[role="dialog"]:not([data-keep])',
        '.popover',
        '.tooltip',
      ];
      for (const sel of selectors) {
        document.querySelectorAll(sel).forEach((el) => el.remove());
      }
      // STEP 05.02.03: 解鎖 body scroll（Bootstrap modal 加的）
      document.body.classList.remove('modal-open');
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    });
    await waitStable(page, 200);

    // === 測試步驟區塊（由 skill 階段 3 依 spec.md 填入）===
    //
    // selector 優先序：data-testid > getByRole > 文字 > class
    //
    // 範例（skill 階段 3 將整段替換）：
    //   await step(page, 'A1.1', 'page-loaded', async (p) => {
    //     await p.waitForSelector('[data-testid="main-container"]', { timeout: 15000 });
    //   });
    //   await step(page, 'A1.1', 'click-add', async (p) => {
    //     await p.locator('button:has-text("新增")').first().click();
    //     await p.waitForSelector('.modal.in, .modal.show', { timeout: 5000 });
    //     await waitStable(p, 300);
    //   });

    // STEP 05.02: 標記 step / waitStable 已被引用（template 階段尚無實際呼叫）
    void step;
    void waitStable;

    // === 測試步驟區塊結束 ===

  } finally {
    await browser.close();
  }

  // STEP 06: 寫完整結果報告
  fs.writeFileSync(
    path.join(SCREENSHOT_DIR, '_results.json'),
    JSON.stringify(
      {
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
      },
      null,
      2,
    ),
  );

  // STEP 07: 印 summary 與決定 exit code
  const pass = results.filter(r => r.status === 'PASS').length;
  console.log(
    `\nDONE: ${pass}/${results.length} PASS, console errors: ${consoleErrors.length}`,
  );
  if (results.some(r => r.status === 'FAIL')) {
    process.exit(1);
  }
})();
