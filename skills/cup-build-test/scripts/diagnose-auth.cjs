// @ts-check
// diagnose-auth.cjs
//
// 比對「API 登入產出的 storageState」與「手動登入存的 .playwright-auth/auth.json」，
// 確認兩者結構等價。執行一次後即可決定 cjs 是否能無痛切換到 API 登入模式。
//
// 用法：
//   cd <business-repo-frontend>
//   BASE_URL=https://staging.example.com \
//   E2E_ACCOUNT=xxx \
//   E2E_PASSWORD=yyy \
//   E2E_TYPE=e \
//     node <skill-path>/scripts/diagnose-auth.cjs
//
// 輸出：
//   - API 與手動兩邊的 cookies 名稱清單（domain/path/expires 摘要）
//   - localStorage / sessionStorage origins
//   - 差異提示（如手動有但 API 沒有，需要 addInitScript 補塞）
//
// 不修改任何檔案。退出碼 0 表示完成（不代表等價，請看輸出判斷）。

const fs = require('fs');
const path = require('path');

// helpers/login.cjs 在同 skill 的 helpers/ 內
const { authStateFromApi, loginParamsFromEnv } = require(
  path.join(__dirname, '..', 'helpers', 'login.cjs'),
);

const AUTH_JSON_PATH = process.env.AUTH_JSON_PATH || '.playwright-auth/auth.json';

/**
 * 把 cookies 陣列摘要成可比對的形式
 * @param {Array<any>} cookies
 */
function summarizeCookies(cookies) {
  return (cookies || []).map((c) => ({
    name: c.name,
    domain: c.domain,
    path: c.path,
    httpOnly: !!c.httpOnly,
    secure: !!c.secure,
    sameSite: c.sameSite,
    // 不印 value，避免敏感資料外洩
  })).sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * 把 origins 陣列摘要：列每個 origin 的 localStorage key 清單
 * @param {Array<any>} origins
 */
function summarizeOrigins(origins) {
  return (origins || []).map((o) => ({
    origin: o.origin,
    localStorageKeys: (o.localStorage || []).map((kv) => kv.name).sort(),
  }));
}

async function main() {
  // STEP 01: 用 API 登入取得 state
  console.log('=== STEP 1: 透過 API 登入取得 storageState ===');
  const params = loginParamsFromEnv();
  console.log(`  baseUrl: ${params.baseUrl}`);
  console.log(`  account: ${params.account}`);
  console.log(`  type   : ${params.type}`);

  const apiState = await authStateFromApi(params);
  console.log(`  ✓ 完成（cookies=${apiState.cookies.length}, origins=${apiState.origins.length}）\n`);

  // STEP 02: 讀手動登入存檔（若存在）
  console.log('=== STEP 2: 讀手動登入存檔 ===');
  /** @type {{ cookies: Array<any>, origins: Array<any> } | null} */
  let manualState = null;
  if (fs.existsSync(AUTH_JSON_PATH)) {
    try {
      const parsed = JSON.parse(fs.readFileSync(AUTH_JSON_PATH, 'utf8'));
      manualState = parsed;
      console.log(`  ✓ ${AUTH_JSON_PATH} 讀取成功`);
      console.log(`    cookies=${parsed.cookies.length}, origins=${parsed.origins.length}\n`);
    } catch (err) {
      console.log(`  ⚠️  讀取失敗：${err.message}\n`);
    }
  } else {
    console.log(`  ⚠️  ${AUTH_JSON_PATH} 不存在 — 無法比對\n`);
  }

  // STEP 03: 印 API state 摘要
  console.log('=== STEP 3: API 登入的 cookies ===');
  console.table(summarizeCookies(apiState.cookies));
  console.log('\n=== STEP 3.1: API 登入的 origins / localStorage ===');
  console.log(JSON.stringify(summarizeOrigins(apiState.origins), null, 2));

  if (!manualState) {
    console.log('\n（無手動 state 可比對，僅印 API 結果供你檢視）');
    return;
  }

  // STEP 04: 印手動 state 摘要
  console.log('\n=== STEP 4: 手動登入的 cookies ===');
  console.table(summarizeCookies(manualState.cookies));
  console.log('\n=== STEP 4.1: 手動登入的 origins / localStorage ===');
  console.log(JSON.stringify(summarizeOrigins(manualState.origins), null, 2));

  // STEP 05: 計算差異
  console.log('\n=== STEP 5: 差異分析 ===');
  const apiCookieNames = new Set(apiState.cookies.map((c) => c.name));
  const manualCookieNames = new Set(manualState.cookies.map((c) => c.name));

  const onlyInManual = [...manualCookieNames].filter((n) => !apiCookieNames.has(n));
  const onlyInApi = [...apiCookieNames].filter((n) => !manualCookieNames.has(n));

  if (onlyInManual.length === 0 && onlyInApi.length === 0) {
    console.log('  ✅ cookies 名稱完全一致（domain/path 請肉眼看 STEP 3 vs STEP 4 表格）');
  } else {
    if (onlyInManual.length > 0) {
      console.log(`  ⚠️  只在手動 state 出現的 cookie: ${onlyInManual.join(', ')}`);
      console.log('     → 可能登入 API 沒設這幾個 cookie，需要前端額外行為才會出現');
    }
    if (onlyInApi.length > 0) {
      console.log(`  ⚠️  只在 API state 出現的 cookie: ${onlyInApi.join(', ')}`);
      console.log('     → API 多給的 cookie，通常不影響（手動可能 expire 了）');
    }
  }

  // STEP 06: localStorage 差異
  const apiLsKeys = apiState.origins.flatMap(
    (o) => (o.localStorage || []).map((kv) => `${o.origin}:${kv.name}`),
  );
  const manualLsKeys = manualState.origins.flatMap(
    (o) => (o.localStorage || []).map((kv) => `${o.origin}:${kv.name}`),
  );
  const lsOnlyInManual = manualLsKeys.filter((k) => !apiLsKeys.includes(k));

  if (lsOnlyInManual.length === 0) {
    console.log('  ✅ localStorage 條目 API 已涵蓋手動全部 keys');
  } else {
    console.log(`  ⚠️  手動有但 API 沒有的 localStorage keys:`);
    lsOnlyInManual.forEach((k) => console.log(`       - ${k}`));
    console.log('     → 需要在 cjs 用 context.addInitScript 補塞');
  }

  console.log('\n=== 完成 ===');
  console.log('  下一步：');
  console.log('  - 若全 ✅，cjs 可直接切換到 authStateFromApi');
  console.log('  - 若有 ⚠️，依提示調整 helpers/login.cjs 或 cjs 的 context 設定');
}

main().catch((err) => {
  console.error('\n❌ diagnose 失敗：');
  console.error(err);
  process.exit(1);
});
