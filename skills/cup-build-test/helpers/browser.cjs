// @ts-check
// CUP E2E Test - Browser launch helper
//
// 匯出：
//   - launchBrowser(options): chromium.launch + newContext(storageState) + newPage
//     ・主流程：opts.login 提供 API 登入參數 → 內部呼叫 authStateFromApi 取 state
//     ・既有 cjs 後備：opts.authPath 指向 .playwright-auth/auth.json（deprecated，僅向後相容）
//   - attachConsoleCollector(page, errors): 註冊 console.error / pageerror handler
//
// 設計：
//   - API 登入失敗 → throw（由呼叫端決定 exit code）
//   - authPath 不存在 → exit code 2 (AUTH_MISSING)，僅 deprecated 模式
//   - 預設 viewport / locale 與 luna 既有測試一致

const fs = require('fs');
const path = require('path');
const os = require('os');
const { createRequire } = require('module');
const { authStateFromApi } = require('./login.cjs');

/** @typedef {import('./types').BrowserBundle} BrowserBundle */

/**
 * 解析 playwright module。多層 fallback：
 *   1. cwd node_modules — 專案剛好已裝（如 luna frontend）
 *   2. helpers/ user-level node_modules — 主要路徑（一次裝、跨專案共用）
 *   3. ~/.npm/_npx/<hash>/node_modules/playwright — npx 暫存區 emergency fallback
 *
 * 設計目的：target 專案保持 0 個額外 npm dep。helpers/ user-level 設定後，
 * 任何 cwd 都能跑 cup-build-test，不需在專案 package.json 加 playwright。
 *
 * 完全 require 失敗時印 setup 指南並 throw。
 * @returns {typeof import('playwright')}
 */
function requirePlaywright() {
  /** @type {Array<{ source: string, anchor: string }>} */
  const candidates = [
    { source: 'cwd',     anchor: path.join(process.cwd(), 'noop.js') },
    { source: 'helpers', anchor: path.join(__dirname, 'noop.js') },
  ];

  // STEP 01: npx 暫存區 emergency fallback（hash 目錄不穩定，最後嘗試）
  try {
    const npxRoot = path.join(os.homedir(), '.npm/_npx');
    if (fs.existsSync(npxRoot)) {
      for (const hash of fs.readdirSync(npxRoot)) {
        const pwPath = path.join(npxRoot, hash, 'node_modules/playwright');
        if (fs.existsSync(pwPath)) {
          candidates.push({
            source: `npx:${hash}`,
            anchor: path.join(npxRoot, hash, 'noop.js'),
          });
        }
      }
    }
  } catch {
    // STEP 01.01: 讀 npx cache 失敗無妨，繼續下一個 fallback
  }

  /** @type {string[]} */
  const errors = [];
  for (const { source, anchor } of candidates) {
    try {
      const req = createRequire(anchor);
      const pw = req('playwright');
      return pw;
    } catch (e) {
      errors.push(`  - ${source}: ${(e && e.message ? e.message : String(e)).slice(0, 80)}`);
    }
  }

  // STEP 02: 全失敗 — 印 setup 指南
  const setupHint = [
    'playwright module not resolvable from any source:',
    ...errors,
    '',
    'Setup（一次性，跨專案共用，不污染專案 package.json）：',
    '  cd ~/.claude/skills/cup-build-test/helpers',
    '  npm install',
    '  npx playwright install chromium',
  ].join('\n');
  console.error(setupHint);
  throw new Error('playwright module not found');
}

/**
 * 啟動 chromium、套登入態、開新分頁
 *
 * 兩種登入模式（擇一）：
 * - `login`（主流程）：API 登入，內部呼叫 authStateFromApi 取 storageState
 * - `authPath`（deprecated，僅向後相容既有 cjs）：載入 .playwright-auth/auth.json
 *
 * 兩者都未提供時直接 throw。
 *
 * @param {{
 *   headless?: boolean,
 *   login?: { baseUrl: string, account: string, password: string, type?: string, loginPath?: string },
 *   authPath?: string,
 *   viewport?: { width: number, height: number },
 *   locale?: string,
 * }} options
 * @returns {Promise<BrowserBundle>}
 */
async function launchBrowser(options) {
  const {
    headless = true,
    login,
    authPath,
    viewport = { width: 1440, height: 900 },
    locale = 'zh-TW',
  } = options;

  if (!login && !authPath) {
    throw new Error('launchBrowser: must provide either `login` (API mode) or `authPath` (deprecated file mode)');
  }

  // STEP 01: 取得 storageState
  //   API 模式：用 login params 即時 POST 取 cookies
  //   File 模式：playwright 接受檔案路徑 string 自動解析
  /** @type {string | { cookies: Array<any>, origins: Array<any> }} */
  let storageState;
  if (login) {
    storageState = await authStateFromApi(login);
  } else {
    // STEP 01.01: deprecated file mode — 驗證檔案存在
    // @ts-ignore — authPath 已 guard 過
    if (!fs.existsSync(authPath)) {
      // @ts-ignore
      console.error(`AUTH_MISSING: ${authPath} not found. 改用 API 登入模式或先產生 storageState。`);
      process.exit(2);
    }
    // @ts-ignore
    storageState = authPath;
  }

  // STEP 02: lazy require playwright（helpers/ 本身不裝，由呼叫專案 cwd 的 node_modules 提供）
  const { chromium } = requirePlaywright();

  // STEP 03: launch + context + page
  const browser = await chromium.launch({ headless });
  const context = await browser.newContext({
    storageState,
    viewport,
    locale,
  });
  const page = await context.newPage();

  return { browser, context, page };
}

/**
 * 註冊 console.error / pageerror handler，append 訊息到傳入的 errors 陣列
 * 設計成 push 到外部陣列而非回傳新陣列，方便最終一起寫進 _results.json
 *
 * @param {import('playwright').Page} page
 * @param {string[]} errors 外部 console errors 收集陣列（會被 mutate）
 */
function attachConsoleCollector(page, errors) {
  page.on('console', (/** @type {import('playwright').ConsoleMessage} */ m) => {
    if (m.type() === 'error') {
      errors.push(`[console.error] ${m.text()}`);
    }
  });
  page.on('pageerror', (/** @type {Error} */ e) => {
    errors.push(`[pageerror] ${e.message}`);
  });
}

module.exports = { launchBrowser, attachConsoleCollector };
