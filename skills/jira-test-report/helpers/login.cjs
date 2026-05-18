// @ts-check
// CUP E2E Test - API 登入 helper
//
// 對應 SKILL.md 階段 4b（API 登入模式）。把互動式 Playwright MCP 登入流程
// 替換為呼叫 /account/login API，無人為介入即可取得 Playwright storageState。
//
// 設計重點：
// - Playwright APIRequest 會自動接收並儲存 Set-Cookie，呼叫 storageState() 得到的
//   結構（cookies + origins）跟手動登入存的 .playwright-auth/auth.json 完全相容。
// - 不在記憶體/檔案存明文密碼；密碼從 env var 讀取，由 caller 透過 .env.local
//   或 GitHub Secrets 注入。
// - 若登入失敗，拋 Error 由 caller 處理；不 fallback 至互動模式（CI 沒得互動）。

/** @type {any} — playwright 的 named exports 在 d.ts 與 runtime 不完全對齊 */
const playwright = require('playwright');

/**
 * 用 API 登入取得 Playwright storageState
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

module.exports = { authStateFromApi, loginParamsFromEnv };
