// @ts-check
// CUP E2E Test - API 登入 helper
//
// 對應 SKILL.md 階段 4b（API 登入模式）。把互動式 Playwright MCP 登入流程
// 替換為呼叫 /account/login API，無人為介入即可取得登入態。
//
// 兩種匯出：
// - loginInContext(context, opts)（**主流程**）：在既有 BrowserContext 內登入，
//     cookies 自動進該 context 的 cookie jar。不經 storageState 序列化，
//     **host-only cookies（無 Domain 屬性）也能保留**。
// - authStateFromApi(opts)（deprecated）：用 playwright.request.newContext 拿 storageState，
//     **storageState 序列化會漏 host-only cookies**（如 luna staging 的 token cookie），
//     不建議新 cjs 使用；保留僅為向後相容。
//
// 設計重點：
// - 不在記憶體/檔案存明文密碼；密碼從 env var 讀取，由 caller 透過 .env.local
//   或 GitHub Secrets 注入。
// - 若登入失敗，拋 Error 由 caller 處理；不 fallback 至互動模式（CI 沒得互動）。

/** @type {any} — playwright 的 named exports 在 d.ts 與 runtime 不完全對齊 */
const playwright = require('playwright');

/**
 * 在既有 BrowserContext 內登入；cookies 直接進該 context 的 cookie jar
 *   **主流程使用此 API。** 比 authStateFromApi+storageState 流程更可靠 —
 *   不會漏 host-only cookies（無 Domain 屬性，luna staging 的 `token` cookie 就是）
 *
 * @param {import('playwright').BrowserContext} context 既由 browser.newContext() 開好的空 context
 * @param {{ baseUrl: string, account: string, password: string, type?: string, loginPath?: string }} opts
 */
async function loginInContext(context, opts) {
  // STEP 01: 驗證必填參數
  const { baseUrl, account, password } = opts;
  const type = opts.type || 'e';
  const loginPath = opts.loginPath || '/account/login';

  if (!baseUrl) { throw new Error('loginInContext: baseUrl is required'); }
  if (!account) { throw new Error('loginInContext: account is required'); }
  if (!password) { throw new Error('loginInContext: password is required'); }

  // STEP 02: 用 context.request 打 login — set-cookie 自動寫入 context cookie jar
  //   - body from: 'web' 後端 req.body.from 分支判斷（postAuthenticate / app 授權）需要
  //   - header x-request-from: 'web' 是 luna 前端 SPA 自帶的客製 header，**後端依此才發 token cookie**。
  //     2026-05-19 從 DevTools 觀察登入回應 set-cookie 含 token；cjs 無此 header 只回 lunastaging.sid 缺 token
  //   - Origin / Referer 補上模擬瀏覽器送出（部分 middleware 對缺 Origin 的 request 行為不同）
  // @ts-ignore — local stubs.d.ts 未含 BrowserContext.request；runtime 有
  const res = await context.request.post(`${baseUrl}${loginPath}`, {
    headers: {
      Origin: baseUrl,
      Referer: `${baseUrl}/login`,
      'x-request-from': 'web',
    },
    data: { account, password, type, from: 'web' },
  });

  // STEP 03: 驗證 response 成功
  if (!res.ok()) {
    const bodyText = await res.text().catch(() => '<unreadable>');
    throw new Error(
      `loginInContext: HTTP ${res.status()} ${res.statusText()} — ${bodyText.slice(0, 200)}`,
    );
  }

  // STEP 04: 印出登入後 context cookie jar 內 cookie 名稱（除錯用）— 不印 value
  // @ts-ignore — local stubs.d.ts 未含 BrowserContext.cookies；runtime 有
  const cookies = await context.cookies();
  const names = cookies.map((c) => c.name).join(',');
  console.log(`[login] OK ${res.status()} — ${cookies.length} cookies: ${names}`);
}

/**
 * @deprecated 用 loginInContext + browser.newContext() 取代
 *   此函式透過 storageState 序列化傳遞 cookies，會漏 host-only cookies（如 luna staging 的 token）
 *
 * @param {{
 *   baseUrl: string,
 *   account: string,
 *   password: string,
 *   type?: string,
 *   loginPath?: string,
 * }} opts
 * @returns {Promise<{ cookies: Array<any>, origins: Array<any> }>}
 */
async function authStateFromApi(opts) {
  // STEP 01: 驗證必填參數
  const { baseUrl, account, password } = opts;
  const type = opts.type || 'e';
  const loginPath = opts.loginPath || '/account/login';

  if (!baseUrl) { throw new Error('authStateFromApi: baseUrl is required'); }
  if (!account) { throw new Error('authStateFromApi: account is required'); }
  if (!password) { throw new Error('authStateFromApi: password is required'); }

  // STEP 02: 建立 APIRequest context（會自動處理 Set-Cookie）
  const ctx = await playwright.request.newContext({ baseURL: baseUrl });

  try {
    // STEP 03: 打 login API
    const res = await ctx.post(loginPath, {
      data: { account, password, type },
    });

    // STEP 04: 驗證 response 成功；失敗時讀 body 給診斷訊息
    if (!res.ok()) {
      const bodyText = await res.text().catch(() => '<unreadable>');
      throw new Error(
        `Login failed: HTTP ${res.status()} ${res.statusText()} — ${bodyText.slice(0, 200)}`,
      );
    }

    // STEP 05: 從 ctx 抽出 storageState（cookies + localStorage + origins）
    const state = await ctx.storageState();
    return state;
  } finally {
    // STEP 06: 一定 dispose ctx 避免 leak
    await ctx.dispose();
  }
}

/**
 * 從 env var 組登入參數（給 CI / .env.local 使用）
 *
 * 預設讀：
 * - process.env.BASE_URL
 * - process.env.E2E_ACCOUNT
 * - process.env.E2E_PASSWORD
 * - process.env.E2E_TYPE (預設 'e')
 *
 * 缺任一必填則拋 Error。
 *
 * @returns {{ baseUrl: string, account: string, password: string, type: string }}
 */
function loginParamsFromEnv() {
  const baseUrl = process.env.BASE_URL;
  const account = process.env.E2E_ACCOUNT;
  const password = process.env.E2E_PASSWORD;
  const type = process.env.E2E_TYPE || 'e';

  const missing = [];
  if (!baseUrl) { missing.push('BASE_URL'); }
  if (!account) { missing.push('E2E_ACCOUNT'); }
  if (!password) { missing.push('E2E_PASSWORD'); }

  if (missing.length > 0) {
    throw new Error(
      `loginParamsFromEnv: missing env vars: ${missing.join(', ')}. ` +
      `Set them in .env.local (local) or GitHub Secrets (CI).`,
    );
  }

  // @ts-ignore — 上面已 guard，TS 不認得
  return { baseUrl, account, password, type };
}

module.exports = { authStateFromApi, loginInContext, loginParamsFromEnv };
