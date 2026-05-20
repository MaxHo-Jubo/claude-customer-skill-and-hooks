// @ts-check
// 機構切換 helper — jira-test-report / cup-build-test 共用
//
// 用途：
//   jira-test-report 跑特定 case 前若需切換至非預設機構（例外 case 屬於特定機構），
//   用此 helper 切換並斷言；跑完於 finally 切回預設機構，避免污染後續測試。
//
// 主流程：
//   1. switchOrg() — 切換 + 等切換 + 重新導向 /case/ + 斷言新機構名
//   2. currentOrg() — 讀當前右上角機構名（從 .list-dropdown-text）
//   3. ensureOrg() — 確認當前為目標機構；不符則自動切（switchOrg 的封裝）
//
// 預設機構（jira-test-report 多數 case 走的機構）：
//   DEFAULT_ORG = { keyword: 'compal', expectedDisplay: '仁寶長照機構' }
//
// DOM 依據（luna FE r15 / r18 共用 react-select v1）：
//   - .list-dropdown-text     — 當前機構名稱 + dropdown trigger
//   - .Select-input input     — react-select 搜尋輸入框
//   - .Select-option          — 過濾後選項
//
// 雪坑記錄：
//   - 切換動作會觸發 navigation，page.context 會被 destroyed → 必須在 wait 後重新 evaluate
//   - 切換後若導向 `/`（首頁）會 SSO redirect 到 icaretest115，所以 helper 強制 navigate /case/
//   - 過濾關鍵字必須唯一過濾，多於 1 筆 throw 避免選錯機構

const path = require('path');

// STEP 01: lazy require modal helper（避免啟動時循環依賴與 missing helper 噴錯）
let _modalCache;
function getModalHelper() {
  if (!_modalCache) {
    try {
      _modalCache = require(path.join(__dirname, 'modal.cjs'));
    } catch (_e) {
      _modalCache = null;
    }
  }
  return _modalCache;
}

// STEP 02: 預設機構（多數 jira-test-report cjs 走這個機構）
//   keyword 對應 internal code（dropdown 顯示「display (code)」格式，code 唯一）；
//   expectedDisplay 對應切換後右上角顯示文字（與 dropdown text 是兩套不同 mapping）。
//   例：keyword='compal' filter 7 筆，helper 自動挑「endsWith (compal)」那筆 = 仁寶躍虎 (compal)，
//       切完右上角顯示「仁寶長照機構」。
const DEFAULT_ORG = {
  keyword: 'compal',
  expectedDisplay: '仁寶長照機構',
};

const DEFAULT_WAIT_MS = 10000;
const DEFAULT_POST_NAV_PATH = '/case/';

/**
 * 讀取右上角當前機構名稱
 * @param {import('playwright').Page} page
 * @returns {Promise<string|null>}
 */
async function currentOrg(page) {
  // STEP 01: 從 .list-dropdown-text 取文字（luna FE r15 / r18 共用 class）
  return await page.evaluate(() => {
    const el = document.querySelector('.list-dropdown-text');
    return el ? (el.textContent || '').trim() : null;
  });
}

/**
 * 切換到指定機構並斷言切換成功
 *
 * 流程：
 *   1. 若當前已是目標機構 → noop（回 { switched: false }）
 *   2. 點 .list-dropdown-text 開 dropdown
 *   3. 在 .Select-input input 填關鍵字過濾
 *   4. 列 .Select-option 確認唯一過濾（多筆 throw 防選錯）
 *   5. click option，等 waitMs 給後端切換
 *   6. navigate baseUrl + postNavPath（避免 SSO 踢到 icaretest）
 *   7. dismiss 可能再彈的公告 modal
 *   8. 讀 currentOrg 斷言等於 expectedDisplay
 *
 * @param {import('playwright').Page} page
 * @param {{
 *   keyword: string,
 *   expectedDisplay: string,
 *   waitMs?: number,
 *   postNavPath?: string,
 *   baseUrl?: string,
 * }} opts
 *   - keyword: react-select 過濾關鍵字（須唯一過濾出目標機構）
 *   - expectedDisplay: 切換完成後右上角預期顯示文字（用作斷言）
 *   - waitMs: 切換後等待後端完成切換的時間，預設 10000ms
 *   - postNavPath: 切換完成後 navigate 的 path，預設 '/case/'
 *   - baseUrl: 切換完成後 navigate 的 base URL；省略時用 page.url() 的 origin
 * @returns {Promise<{ switched: boolean, before: string|null, after: string|null }>}
 */
async function switchOrg(page, opts) {
  // STEP 01: 驗證必填參數
  const { keyword, expectedDisplay } = opts;
  const waitMs = typeof opts.waitMs === 'number' ? opts.waitMs : DEFAULT_WAIT_MS;
  const postNavPath = opts.postNavPath || DEFAULT_POST_NAV_PATH;
  if (!keyword) { throw new Error('switchOrg: keyword is required'); }
  if (!expectedDisplay) { throw new Error('switchOrg: expectedDisplay is required'); }

  // STEP 02: 若當前已是目標機構則 noop
  const before = await currentOrg(page);
  if (before === expectedDisplay) {
    return { switched: false, before, after: before };
  }

  // STEP 03: 點 dropdown trigger 開啟 react-select
  const trigger = page.locator('.list-dropdown-text').first();
  if ((await trigger.count()) === 0) {
    throw new Error('switchOrg: 找不到 .list-dropdown-text（機構 dropdown trigger）— 確認已登入並在 protected route');
  }
  await trigger.click();
  await page.waitForTimeout(600);

  // STEP 04: 填入過濾關鍵字
  const input = page.locator('.Select-input input').first();
  if ((await input.count()) === 0) {
    throw new Error('switchOrg: 找不到 .Select-input input（react-select 輸入框）');
  }
  await input.fill(keyword);
  await page.waitForTimeout(700);

  // STEP 05: 列出過濾結果並挑選正確 option
  //   優先用「結尾 (keyword)」匹配（internal code 模式，dropdown text 格式為「display (code)」）；
  //   若沒匹配且結果唯一，選唯一那筆（substring 唯一模式，例如 keyword='豐原'）；
  //   否則 throw 防選錯。
  const options = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.Select-option'))
      .map((o) => (o.textContent || '').trim()),
  );
  if (options.length === 0) {
    throw new Error(`switchOrg: 關鍵字「${keyword}」沒過濾出任何機構選項`);
  }
  let matchIdx = options.findIndex((o) => o.endsWith(`(${keyword})`));
  if (matchIdx === -1) {
    if (options.length === 1) {
      matchIdx = 0;
    } else {
      throw new Error(
        `switchOrg: 關鍵字「${keyword}」過濾出 ${options.length} 筆，既無結尾 "(${keyword})" 也非唯一，請改用更精準的 keyword。實際：${JSON.stringify(options)}`,
      );
    }
  }

  // STEP 06: 點選命中的 option（會觸發 navigation，page context 即將 destroyed）
  await page.locator('.Select-option').nth(matchIdx).click();

  // STEP 07: 等切換完成（後端 session 切換 + 前端 redirect）
  await page.waitForTimeout(waitMs);

  // STEP 08: 主動 navigate 到 protected route，避免被 SSO 踢到 icaretest
  let baseUrl = opts.baseUrl;
  if (!baseUrl) {
    try {
      baseUrl = new URL(page.url()).origin;
    } catch (_e) {
      baseUrl = null;
    }
  }
  if (!baseUrl) {
    throw new Error('switchOrg: 無法判定 baseUrl，請傳入 opts.baseUrl');
  }
  await page.goto(`${baseUrl}${postNavPath}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2000);

  // STEP 09: dismiss 切換後可能再彈的公告 modal（缺 helper 不擋流程）
  const modal = getModalHelper();
  if (modal && typeof modal.waitAndDismissOnEntry === 'function') {
    try {
      await modal.waitAndDismissOnEntry(page);
    } catch (_e) {
      // dismiss 失敗不擋切換流程；後續斷言會抓到真正的問題
    }
  }

  // STEP 10: 斷言新機構名
  const after = await currentOrg(page);
  if (after !== expectedDisplay) {
    throw new Error(
      `switchOrg: 切換後機構名不符。實測「${after}」/ 預期「${expectedDisplay}」（keyword="${keyword}"）`,
    );
  }

  return { switched: true, before, after };
}

/**
 * 確認當前機構為目標機構；不符則自動切（switchOrg 的薄封裝，語意更清楚）
 * @param {import('playwright').Page} page
 * @param {Parameters<typeof switchOrg>[1]} opts
 */
async function ensureOrg(page, opts) {
  return await switchOrg(page, opts);
}

module.exports = {
  DEFAULT_ORG,
  currentOrg,
  switchOrg,
  ensureOrg,
};
