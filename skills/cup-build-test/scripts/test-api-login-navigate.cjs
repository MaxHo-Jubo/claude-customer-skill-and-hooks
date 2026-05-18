// @ts-check
// test-api-login-navigate.cjs
//
// 驗證 API 登入後能否實際進入受保護頁面。
// 用 API 取 storageState → 開 headed browser → goto dashboard → 觀察被導去哪裡。
//
// 用法（與 diagnose-auth.cjs 同樣的 env var）：
//   cd <business-repo-frontend>
//   BASE_URL=... E2E_ACCOUNT=... E2E_PASSWORD=... E2E_TYPE=e \
//   ENTRY_PATH=/dashboard \
//     node <skill>/scripts/test-api-login-navigate.cjs
//
// 觀察：
// - Final URL 仍在 dashboard       → API 登入足夠
// - Final URL 跳回 /login          → 前端需要 localStorage flag，要補 addInitScript
// - 彈窗（條款/release note）       → cjs 要加 dismiss 步驟（既有 modal helper 已支援）

const path = require('path');

const { authStateFromApi, loginParamsFromEnv } = require(
  path.join(__dirname, '..', 'helpers', 'login.cjs'),
);
/** @type {any} */
const playwright = require(
  path.join(__dirname, '..', 'helpers', 'node_modules', 'playwright'),
);

async function main() {
  // STEP 01: 拿登入參數 + storageState
  const params = loginParamsFromEnv();
  const entryPath = process.env.ENTRY_PATH || '/';
  const headless = process.env.HEADLESS === 'true';

  console.log(`=== 設定 ===`);
  console.log(`  baseUrl   : ${params.baseUrl}`);
  console.log(`  entryPath : ${entryPath}`);
  console.log(`  headless  : ${headless}`);
  console.log('');

  console.log('=== STEP 1: API 登入取 storageState ===');
  const state = await authStateFromApi(params);
  console.log(`  ✓ cookies: ${state.cookies.map((c) => c.name).join(', ')}`);
  console.log('');

  // STEP 02: 開 browser、注入 state、導到 entry path
  console.log('=== STEP 2: 開 browser 導到 entry path ===');
  const browser = await playwright.chromium.launch({ headless });
  const context = await browser.newContext({ storageState: state });
  const page = await context.newPage();

  /** @type {Array<{type: string, text: string}>} */
  const consoleMessages = [];
  page.on('console', (msg) => {
    consoleMessages.push({ type: msg.type(), text: msg.text() });
  });
  page.on('pageerror', (err) => {
    consoleMessages.push({ type: 'pageerror', text: err.message });
  });

  const targetUrl = params.baseUrl.replace(/\/$/, '') + entryPath;
  console.log(`  goto: ${targetUrl}`);

  await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(2000);

  // STEP 03: 觀察結果
  console.log('');
  console.log('=== STEP 3: 觀察結果 ===');
  console.log(`  Final URL  : ${page.url()}`);
  console.log(`  Page title : ${await page.title()}`);

  const finalUrl = page.url();
  const isLoginPage = /login|signin|auth/i.test(finalUrl);
  if (isLoginPage) {
    console.log('  ❌ 被踢回登入頁 — API 登入不足，需要補 localStorage 或其他狀態');
  } else if (finalUrl.includes(entryPath)) {
    console.log('  ✅ 成功進入目標頁 — API 登入足夠');
  } else {
    console.log('  ⚠️  被導到其他頁，請肉眼確認（可能是首頁、彈窗、其他）');
  }

  // STEP 04: 偵測彈窗
  console.log('');
  console.log('=== STEP 4: 偵測常見彈窗 ===');
  const dialogTexts = await page.evaluate(() => {
    /** @type {string[]} */
    const found = [];
    document.querySelectorAll('[role="dialog"], .modal, .ant-modal, [class*="Modal"]').forEach(
      (el) => {
        const text = (el.textContent || '').trim().slice(0, 100);
        if (text) { found.push(text); }
      },
    );
    return found;
  });
  if (dialogTexts.length === 0) {
    console.log('  ✅ 無偵測到彈窗');
  } else {
    console.log(`  ⚠️  發現 ${dialogTexts.length} 個彈窗：`);
    dialogTexts.forEach((t, i) => console.log(`     [${i + 1}] ${t}`));
  }

  // STEP 05: console errors 摘要
  console.log('');
  console.log('=== STEP 5: console errors / pageerrors ===');
  const errors = consoleMessages.filter(
    (m) => m.type === 'error' || m.type === 'pageerror',
  );
  if (errors.length === 0) {
    console.log('  ✅ 無 errors');
  } else {
    console.log(`  ⚠️  ${errors.length} errors（前 5 個）：`);
    errors.slice(0, 5).forEach((e) => console.log(`     [${e.type}] ${e.text.slice(0, 150)}`));
  }

  if (!headless) {
    console.log('');
    console.log('💡 headed 模式：browser 窗口保留 10 秒讓你目視確認');
    await page.waitForTimeout(10000);
  }

  await browser.close();
  console.log('\n=== 完成 ===');
}

main().catch((err) => {
  console.error('\n❌ 失敗：', err);
  process.exit(1);
});
