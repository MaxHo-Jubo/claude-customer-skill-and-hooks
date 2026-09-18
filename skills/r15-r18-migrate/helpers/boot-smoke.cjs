/**
 * boot-smoke.cjs — 建置產物的「啟動 smoke」。
 *
 * 用瀏覽器實際載入前端建置產物的 app shell，觀察一段時間。任何 `pageerror`、
 * 任何 console error 一律判定失敗；網路層失敗（HTTP ≥ 400 或請求本身失敗）改由
 * Playwright 的 `response`/`requestfailed` 結構化事件依 URL 路徑判定——只有命中
 * `BACKEND_ENDPOINT_PREFIXES`（/api/、/auth/）才忽略，因為合成 shell 沒有後端可打、
 * 未登入才會觸發的端點失敗是預期雜訊；其餘網路失敗（如缺資產）一律算失敗。用途是
 * 擋掉「build 綠燈但一開就白屏」這類只有真的載入才看得到的迴歸。
 *
 * 用法：
 *   node boot-smoke.cjs --dist <建置產物目錄>      # 自行起靜態伺服器載入；目錄沒有 index.html 但有
 *                                               # manifest.json（js/modulePreloads/css 契約）時，
 *                                               # 依 manifest 合成一頁 app shell 載入（見 buildSyntheticIndexHtml）
 *   node boot-smoke.cjs --dist <目錄> --static-root <目錄> [--static-root <目錄> ...]
 *                                               # 額外掛載唯讀靜態根目錄（可重複），供產物目錄本身
 *                                               # 不含、但頁面實際會打的手足靜態資源使用（如 backend/public
 *                                               # 下的 locales/，見 resolveStaticFile）；dist 永遠優先
 *   node boot-smoke.cjs --url http://host:port/    # 載入已經跑起來的位址；共用同一套網路失敗判定
 *
 * 退出碼：
 *   0 = 觀察期內零錯誤
 *   1 = 抓到 pageerror / console error / 非後端前綴的網路失敗（詳情印在 stdout）
 *   2 = 找不到 playwright（印出安裝指引；**不當成通過**）
 *   3 = 參數或產物目錄有問題（含 --static-root 指定的目錄不存在或不是目錄）
 */

'use strict';

const fs = require('fs');
const http = require('http');
const path = require('path');

/** 觀察視窗：頁面載入後持續監聽這麼久，期間零錯誤才算通過 */
const OBSERVE_WINDOW_MS = 5000;
/** 導頁逾時：超過這個時間還沒載入完成就算失敗 */
const NAV_TIMEOUT_MS = 30000;
/** 瀏覽器啟動逾時 */
const LAUNCH_TIMEOUT_MS = 60000;
/** 產物目錄相對於 repo 根目錄的預設位置 */
const DEFAULT_DIST_RELATIVE = path.join('backend', 'public', 'build', 'react18');
/** 前端專案相對於 repo 根目錄的位置（用來解析它的 node_modules） */
const FRONTEND_RELATIVE = path.join('frontend', 'react_18');

/** 退出碼 */
const EXIT_OK = 0;
const EXIT_ERRORS_FOUND = 1;
const EXIT_NO_PLAYWRIGHT = 2;
const EXIT_BAD_INPUT = 3;

/** 靜態伺服器用的副檔名對 MIME 型別表 */
const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.map': 'application/json; charset=utf-8',
};

/** 合成 app shell 讀取的 manifest 檔名（R18 vite.config.js 產出的自訂契約：js/modulePreloads/css/cMaps/standardFonts） */
const MANIFEST_FILENAME = 'manifest.json';
/** 合成 app shell 用的 CSP nonce，鏡像 backend/views 目前寫死的值；本機靜態伺服器不送 CSP header，這裡純粹是來源鏡像不影響行為 */
const SYNTHETIC_NONCE = 'Y29tcGFsLWVycHYz';
/**
 * 合成 app shell 的 __PRELOADED_STATE__：未登入情境固定為 `{}`，鏡像
 * backend/routes/index.js:222-225 實際渲染行為——`preload: { user: req.session.user,
 * candidate: req.session.candidate }` 未登入時兩者皆為 `undefined`，EJS 用
 * `JSON.stringify(preload)` 序列化時會把 `undefined` 值的鍵整個剔除，最終送到瀏覽器的
 * 就是空物件，不是 `{user:null,candidate:null}`（那樣序列化會保留兩個 key，讓
 * `createStore(reducer, {user:null,candidate:null})` 對不到任何 reducer key 而噴
 * "Unexpected keys" 警告——實測踩過，故不可用 null）
 */
const SYNTHETIC_PRELOADED_STATE_JSON = JSON.stringify({});
/**
 * 後端 API 路徑前綴：靜態伺服器的 SPA fallback 判斷、與網路失敗事件的忽略判斷共用
 * 同一份出處。合成 shell 沒有真正的後端可打，未登入才會觸發的端點失敗是預期雜訊，
 * 兩處都依此判定為「後端端點」而忽略。
 */
const BACKEND_ENDPOINT_PREFIXES = ['/api/', '/auth/'];
/** 網路層失敗判定門檻：`response` 事件的 HTTP 狀態碼達到或超過此值視為失敗（見 judgeNetworkFailure） */
const HTTP_ERROR_STATUS_THRESHOLD = 400;
/** Chromium 導頁中斷既有請求時的網路層錯誤代碼：屬於中斷本身的副作用，非資源載入失敗 */
const REQUEST_ABORTED_STATUS = 'net::ERR_ABORTED';
/**
 * 瀏覽器自身為資源載入失敗（fetch/XHR/img/script 等）印出的 console error 訊息前綴。
 * 這類訊息對應的 HTTP 狀態已經由 `judgeNetworkFailure` 透過 Playwright 的
 * `response`/`requestfailed` 結構化事件判過一次，這裡只是同一件事在 console 上的
 * 回聲，直接忽略、不重複計入失敗；除此之外的 console error 一律算失敗。
 */
const BROWSER_RESOURCE_LOAD_MESSAGE_PREFIX = 'Failed to load resource';

/**
 * 解析命令列參數。
 * @param {string[]} argv 原始參數陣列（不含 node 與腳本本身）
 * @returns {{url: string|null, dist: string|null, observeMs: number, staticRoots: string[]}} 解析後的選項；
 *   staticRoots 是 --static-root 依出現順序收集的清單，可為空陣列
 */
function parseArgs(argv) {
  // STEP 01: 建立預設值，再逐一掃描命令列參數覆寫
  const options = { url: null, dist: null, observeMs: OBSERVE_WINDOW_MS, staticRoots: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--url') {
      options.url = argv[i + 1] || null;
      i += 1;
    } else if (arg === '--dist') {
      options.dist = argv[i + 1] || null;
      i += 1;
    } else if (arg === '--observe-ms') {
      options.observeMs = parseInt(argv[i + 1], 10) || OBSERVE_WINDOW_MS;
      i += 1;
    } else if (arg === '--static-root') {
      // 可重複出現；存在性/是否為目錄留給 main() 與 --dist 同等級驗證，這裡只收集
      if (argv[i + 1]) {
        options.staticRoots.push(argv[i + 1]);
      }
      i += 1;
    }
  }
  return options;
}

/**
 * 找出並載入 playwright 模組。
 *
 * 解析順序：本腳本自己的 node_modules → NODE_PATH → 前端專案的 node_modules。
 * @param {string|null} repoDir repo 根目錄（可為 null）
 * @returns {object|null} playwright 模組，找不到時回 null
 */
function loadPlaywright(repoDir) {
  // STEP 01: 組出候選解析路徑
  const searchPaths = [];
  const nodePath = process.env.NODE_PATH;
  if (nodePath) {
    nodePath.split(path.delimiter).forEach((entry) => {
      if (entry) {
        searchPaths.push(entry);
      }
    });
  }
  if (repoDir) {
    searchPaths.push(path.join(repoDir, FRONTEND_RELATIVE, 'node_modules'));
    searchPaths.push(path.join(repoDir, FRONTEND_RELATIVE));
  }

  // STEP 02: 先試一般 require，再試帶 paths 的解析
  try {
    return require('playwright');
  } catch (err) {
    if (searchPaths.length === 0) {
      return null;
    }
  }
  try {
    const resolved = require.resolve('playwright', { paths: searchPaths });
    return require(resolved);
  } catch (err) {
    return null;
  }
}

/**
 * 讀取 manifest.json 並驗證足以合成 app shell（至少要有 entry chunk 的 js 欄位）。
 * 用於 R18 這類沒有實體 index.html、由 backend EJS 掛載的建置產物。
 * @param {string} distDir 產物目錄
 * @returns {object|null} 解析後的 manifest；目錄沒有 manifest.json、JSON 壞掉、或缺 js 欄位時回傳 null
 */
function readManifestForSynthesis(distDir) {
  // STEP 01: 沒有 manifest.json 就不用往下猜
  const manifestPath = path.join(distDir, MANIFEST_FILENAME);
  if (!fs.existsSync(manifestPath)) {
    return null;
  }
  // STEP 02: JSON 壞掉或缺必要欄位一律視為不可用，不當機、交給呼叫端判斷退出碼
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    if (!manifest || typeof manifest.js !== 'string' || manifest.js.length === 0) {
      return null;
    }
    return manifest;
  } catch (err) {
    return null;
  }
}

/**
 * 從 manifest.json 合成一份最小 index.html，鏡像 backend/views/index_18.ejs 與
 * partials/assetLoader.ejs 在「未登入、manifest 已知」情境下最終會產生的 DOM 狀態：
 * __webpack_nonce__、__PRELOADED_STATE__（固定空值）、#content / #print-mount 掛載點、
 * PDF cMaps/standardFonts 全域、css/modulepreload 標籤、entry chunk 的 module script。
 * 不鏡像 assetLoader.ejs 執行期 fetch manifest.json 再動態插標籤的那段機制本身——
 * 這裡在 Node 端一次性把同一份 manifest 解析結果直接寫死進 HTML，兩者最終 DOM 等價。
 * 資源路徑一律用「相對於 distDir」的相對網址，交由呼叫端把 distDir 直接當成靜態伺服器
 * 根目錄（R18 vite.config.js 的 `base: ''` 本來就是相對路徑解析，不依賴特定網址前綴）。
 * @param {{js: string, css?: string[], modulePreloads?: string[], cMaps?: string, standardFonts?: string}} manifest
 *   R18 vite.config.js 產出的自訂 manifest 契約
 * @returns {string} 完整 HTML 文件字串
 */
function buildSyntheticIndexHtml(manifest) {
  // STEP 01: 補齊可選欄位預設值，manifest 缺欄位時不當機
  const cssFiles = Array.isArray(manifest.css) ? manifest.css : [];
  const modulePreloads = Array.isArray(manifest.modulePreloads) ? manifest.modulePreloads : [];

  // STEP 02: 組出 css 與 modulepreload 標籤（對應 assetLoader.ejs 執行後 <head> 會有的結果）
  const cssTags = cssFiles
    .map((file) => '<link rel="stylesheet" href="' + file + '" nonce="' + SYNTHETIC_NONCE + '" />')
    .join('\n        ');
  const modulePreloadTags = modulePreloads
    .map((file) => '<link rel="modulepreload" href="' + file + '" nonce="' + SYNTHETIC_NONCE + '" />')
    .join('\n        ');
  const pdfCmapGlobal = manifest.cMaps
    ? '            window.__PDF_CMAP_URL__ = ' + JSON.stringify(manifest.cMaps) + ';\n'
    : '';
  const pdfFontGlobal = manifest.standardFonts
    ? '            window.__PDF_STANDARD_FONT_URL__ = ' + JSON.stringify(manifest.standardFonts) + ';\n'
    : '';

  // STEP 03: 組出完整頁面；伺服器資料一律用空值，未登入導向交給 R18 自己的路由處理
  return '<!DOCTYPE html>\n'
    + '<html>\n'
    + '    <head>\n'
    + '        <meta charset="utf-8" />\n'
    + '        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=0" />\n'
    + '        <title>i 照護</title>\n'
    + '        <script nonce="' + SYNTHETIC_NONCE + '">\n'
    + '            window.__webpack_nonce__ = \'' + SYNTHETIC_NONCE + '\';\n'
    + '        </script>\n'
    + '        ' + cssTags + '\n'
    + '        ' + modulePreloadTags + '\n'
    + '        <script nonce="' + SYNTHETIC_NONCE + '">\n'
    + '            window.__PRELOADED_STATE__ = ' + SYNTHETIC_PRELOADED_STATE_JSON + ';\n'
    + pdfCmapGlobal
    + pdfFontGlobal
    + '        </script>\n'
    + '    </head>\n'
    + '    <body id="body" class="bg-g">\n'
    + '        <div id="content"></div>\n'
    + '        <div id="print-mount"></div>\n'
    + '        <script type="module" nonce="' + SYNTHETIC_NONCE + '" src="' + manifest.js + '"></script>\n'
    + '    </body>\n'
    + '</html>\n';
}

/**
 * 判斷一個 pathname 是否命中後端 API 前綴。伺服器 SPA fallback 與網路失敗判定
 * 共用這個函式，確保兩處判準永遠一致（見 BACKEND_ENDPOINT_PREFIXES 註解）。
 * @param {string} pathname URL 的 pathname 部分（不含 query string）
 * @returns {boolean} 是否命中 BACKEND_ENDPOINT_PREFIXES 任一前綴
 */
function isBackendEndpointPath(pathname) {
  // STEP 01: 逐一比對前綴，任一命中即算後端端點
  for (let i = 0; i < BACKEND_ENDPOINT_PREFIXES.length; i += 1) {
    if (pathname.startsWith(BACKEND_ENDPOINT_PREFIXES[i])) {
      return true;
    }
  }
  return false;
}

/**
 * 判定一筆網路失敗（`response` 狀態碼 >= HTTP_ERROR_STATUS_THRESHOLD，或 `requestfailed`
 * 事件）是否應被忽略。命中就即時印出 `[ignored:<原因>]` 並記進 ignored 清單；
 * 其餘一律記進 errors 清單，視為 boot 失敗。
 * @param {string} method HTTP 方法
 * @param {string} url 完整請求網址
 * @param {string} status HTTP 狀態碼字串，或 Chromium `requestfailed` 的網路層錯誤代碼
 * @param {string[]} errors 真正失敗的錯誤清單（就地 push）
 * @param {string[]} ignored 已忽略的錯誤清單（就地 push）
 * @returns {void}
 */
function judgeNetworkFailure(method, url, status, errors, ignored) {
  // STEP 01: 解析 pathname；理論上 Playwright 一律給完整網址，解析失敗時退回原字串
  let pathname = url;
  try {
    pathname = new URL(url).pathname;
  } catch (err) {
    pathname = url;
  }
  const line = method + ' ' + pathname + ' → ' + status;

  // STEP 02: 命中後端前綴 → 忽略，合成 shell 沒有後端可打
  if (isBackendEndpointPath(pathname)) {
    console.log('[boot-smoke] [ignored:BACKEND_ENDPOINT] ' + line);
    ignored.push(line);
    return;
  }

  // STEP 03: 導頁中斷既有請求 → 忽略，非資源本身載入失敗
  if (status === REQUEST_ABORTED_STATUS) {
    console.log('[boot-smoke] [ignored:REQUEST_ABORTED] ' + line);
    ignored.push(line);
    return;
  }

  // STEP 04: 其餘一律算失敗（如缺資產）
  errors.push('resource: ' + line);
}

/**
 * 依序在多個靜態根目錄中尋找 requestPath 對應的實體檔案。dist 永遠排在 roots[0]，
 * 其餘依 --static-root 給定順序排在後面。單一根目錄的路徑逃逸只代表「這個根目錄
 * 沒有這個資源」，跳過去看下一個；是否要整體視為惡意逃逸（403）由呼叫端另外判斷，
 * 這裡只負責找檔案。
 * @param {string[]} roots 靜態根目錄清單，依優先序排列
 * @param {string} requestPath 已解碼、去除 query string 的請求路徑
 * @returns {string|null} 第一個命中且為一般檔案的絕對路徑；全部落空回傳 null
 */
function resolveStaticFile(roots, requestPath) {
  // STEP 01: 依序嘗試每個根目錄，命中「未逃逸 + 實體檔存在 + 非目錄」就回傳
  for (let i = 0; i < roots.length; i += 1) {
    const root = roots[i];
    const candidate = path.join(root, requestPath);
    if (!candidate.startsWith(root)) {
      continue;
    }
    if (fs.existsSync(candidate) && !fs.statSync(candidate).isDirectory()) {
      return candidate;
    }
  }
  return null;
}

/**
 * 起一個只讀的靜態伺服器提供建置產物，可疊加額外的唯讀靜態根目錄（--static-root）
 * 提供產物目錄本身不含的手足靜態資源。決策順序：(1) 目錄逃逸——requestPath 對每個
 * 根目錄都跳出該目錄範圍才 403（單一根目錄逃逸只代表那個根目錄沒有這項資源，換下
 * 一個根目錄看）；(2) pathname 命中後端前綴一律回真 404（合成 shell 沒有後端，不可
 * 落 SPA fallback，否則「後端失敗」會被誤判成「頁面資源」）；(3) 依序在每個根目錄
 * 找實體檔（見 resolveStaticFile），命中依 MIME 回 200；(4) 有副檔名的缺檔視為真的
 * 資源遺失，回真 404（不再無條件退回 index.html，避免瀏覽器把 HTML 當成該資源類型
 * 解析）；(5) 其餘（無副檔名路徑或目錄）才是 SPA 路由，只看 distDir 本身的
 * index.html → 合成 app shell → 404（額外靜態根不參與頁面路由 fallback，它們只
 * 提供手足靜態資源）。
 * @param {string} distDir 產物目錄，永遠是靜態根目錄清單的第一個
 * @param {string|null} syntheticIndexHtml distDir 沒有實體 index.html 時要退回的合成內容；
 *   distDir 有實體 index.html 時一律傳 null，行為與純檔案模式完全相同
 * @param {string[]} staticRoots 額外的唯讀靜態根目錄（來自 --static-root，可為空陣列）
 * @returns {Promise<{server: http.Server, baseUrl: string, roots: string[]}>} 伺服器、基底位址、
 *   實際使用的根目錄清單（dist 在前）
 */
function startStaticServer(distDir, syntheticIndexHtml, staticRoots) {
  // STEP 01: 組出靜態根目錄清單，dist 永遠第一
  const roots = [distDir].concat(staticRoots);

  // STEP 02: 建立 server
  const server = http.createServer((req, res) => {
    const requestPath = decodeURIComponent((req.url || '/').split('?')[0]);

    // STEP 03: 目錄逃逸防護——每個根目錄各自判斷，全部逃逸才 403
    const allRootsEscaped = roots.every((root) => !path.join(root, requestPath).startsWith(root));
    if (allRootsEscaped) {
      res.writeHead(403);
      res.end('forbidden');
      return;
    }

    // STEP 04: pathname 命中後端前綴 → 一律回真 404，不落 SPA fallback
    if (isBackendEndpointPath(requestPath)) {
      res.writeHead(404, { 'Content-Type': MIME_TYPES['.json'] });
      res.end(JSON.stringify({ error: 'boot-smoke: no backend' }));
      return;
    }

    // STEP 05: 依序在每個根目錄找實體檔，命中依副檔名決定 MIME 後回傳
    const resolvedPath = resolveStaticFile(roots, requestPath);
    if (resolvedPath) {
      const mime = MIME_TYPES[path.extname(resolvedPath).toLowerCase()] || 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': mime });
      fs.createReadStream(resolvedPath).pipe(res);
      return;
    }

    // STEP 06: 有副檔名的缺檔（如 missing.js）是真的資源遺失，回真 404，不再退回 index.html
    if (path.extname(requestPath) !== '') {
      res.writeHead(404);
      res.end('not found');
      return;
    }

    // STEP 07: 其餘（無副檔名路徑或目錄）才是 SPA 路由：只看 distDir 本身的
    // index.html → 合成 app shell → 404（額外靜態根不參與頁面路由 fallback）
    const indexPath = path.join(distDir, 'index.html');
    if (fs.existsSync(indexPath)) {
      res.writeHead(200, { 'Content-Type': MIME_TYPES['.html'] });
      fs.createReadStream(indexPath).pipe(res);
      return;
    }
    if (syntheticIndexHtml) {
      res.writeHead(200, { 'Content-Type': MIME_TYPES['.html'] });
      res.end(syntheticIndexHtml);
      return;
    }
    res.writeHead(404);
    res.end('not found');
  });

  // STEP 08: 綁到本機隨機埠，回傳實際位址與使用的根目錄清單
  return new Promise((resolve, reject) => {
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      resolve({ server, baseUrl: 'http://127.0.0.1:' + address.port + '/', roots });
    });
  });
}

/**
 * 實際開頁面並收集錯誤。pageerror 一律算失敗；console error 只有一種例外
 * （瀏覽器自身回聲的資源載入失敗訊息，見 BROWSER_RESOURCE_LOAD_MESSAGE_PREFIX），
 * 其餘一律算失敗；網路層失敗（HTTP >= 400 的回應、或請求本身失敗）改由
 * `response`/`requestfailed` 結構化事件交給 judgeNetworkFailure 依 URL 路徑判定。
 * @param {object} playwright playwright 模組
 * @param {string} url 要載入的位址
 * @param {number} observeMs 觀察視窗毫秒數
 * @returns {Promise<{errors: string[], ignored: string[]}>} 真正失敗的錯誤，與已忽略的錯誤
 */
async function collectPageErrors(playwright, url, observeMs) {
  // STEP 01: 啟動瀏覽器與分頁，掛上 pageerror／console／response／requestfailed 四種監聽
  const errors = [];
  const ignored = [];
  const browser = await playwright.chromium.launch({ timeout: LAUNCH_TIMEOUT_MS });
  try {
    const page = await browser.newPage();
    page.on('pageerror', (err) => {
      errors.push('pageerror: ' + (err && err.message ? err.message : String(err)));
    });
    page.on('console', (message) => {
      if (message.type() !== 'error') {
        return;
      }
      const text = message.text();
      // 瀏覽器自身對資源載入失敗的回聲：對應的 HTTP 狀態已由下面的 response/requestfailed
      // 監聽經 judgeNetworkFailure 判過一次，這裡不重複計入失敗
      if (text.indexOf(BROWSER_RESOURCE_LOAD_MESSAGE_PREFIX) === 0) {
        console.log('[boot-smoke] [ignored:REPORTED_VIA_NETWORK_EVENT] ' + text);
        ignored.push(text);
        return;
      }
      errors.push('console.error: ' + text);
    });
    page.on('response', (response) => {
      const status = response.status();
      if (status >= HTTP_ERROR_STATUS_THRESHOLD) {
        judgeNetworkFailure(response.request().method(), response.url(), String(status), errors, ignored);
      }
    });
    page.on('requestfailed', (request) => {
      const failure = request.failure();
      const status = failure ? failure.errorText : 'unknown';
      judgeNetworkFailure(request.method(), request.url(), status, errors, ignored);
    });

    // STEP 02: 導頁；導頁本身失敗也算一筆錯誤
    try {
      await page.goto(url, { waitUntil: 'load', timeout: NAV_TIMEOUT_MS });
    } catch (err) {
      errors.push('navigation: ' + (err && err.message ? err.message : String(err)));
      return { errors, ignored };
    }

    // STEP 03: 維持觀察視窗，讓延遲執行的程式有機會拋錯
    await page.waitForTimeout(observeMs);
    return { errors, ignored };
  } finally {
    await browser.close();
  }
}

/**
 * 主流程。
 * @returns {Promise<number>} 退出碼
 */
async function main() {
  // STEP 01: 解析參數，決定要載入的位址（--url 優先，否則自行起靜態伺服器）
  const options = parseArgs(process.argv.slice(2));
  const repoDir = process.env.REPO_DIR || null;

  const playwright = loadPlaywright(repoDir);
  if (!playwright) {
    console.log('[boot-smoke] 找不到 playwright，無法執行啟動 smoke（不視為通過）。');
    console.log('[boot-smoke] 安裝方式（擇一）：');
    console.log('  npm install --no-save playwright && npx playwright install chromium');
    console.log('  或設定 NODE_PATH 指向已安裝 playwright 的 node_modules 目錄');
    return EXIT_NO_PLAYWRIGHT;
  }

  let server = null;
  let targetUrl = options.url;
  if (!targetUrl) {
    // STEP 02: 沒給 --url 就用產物目錄起伺服器
    const distDir = path.resolve(
      options.dist || (repoDir ? path.join(repoDir, DEFAULT_DIST_RELATIVE) : DEFAULT_DIST_RELATIVE)
    );

    // STEP 02.01: 驗證額外靜態根目錄，與 --dist 同等級的壞輸入（必須存在且是目錄）
    const staticRoots = [];
    for (let i = 0; i < options.staticRoots.length; i += 1) {
      const resolvedRoot = path.resolve(options.staticRoots[i]);
      if (!fs.existsSync(resolvedRoot) || !fs.statSync(resolvedRoot).isDirectory()) {
        console.log('[boot-smoke] --static-root 指定的目錄不存在或不是目錄: ' + resolvedRoot);
        return EXIT_BAD_INPUT;
      }
      staticRoots.push(resolvedRoot);
    }

    let syntheticIndexHtml = null;
    if (!fs.existsSync(path.join(distDir, 'index.html'))) {
      // STEP 02.02: 沒有實體 index.html（如 R18 這類由 backend EJS 掛載的產物）
      // → 嘗試從 manifest.json 合成一份最小 app shell；manifest 也不可用才真的失敗
      const manifest = readManifestForSynthesis(distDir);
      if (!manifest) {
        console.log('[boot-smoke] 產物目錄缺少 index.html，且找不到可用的 manifest.json（需含 js 欄位）: ' + distDir);
        return EXIT_BAD_INPUT;
      }
      syntheticIndexHtml = buildSyntheticIndexHtml(manifest);
      console.log('[boot-smoke] 找不到 index.html，改用 manifest.json 合成 app shell: ' + distDir);
    }
    const started = await startStaticServer(distDir, syntheticIndexHtml, staticRoots);
    server = started.server;
    targetUrl = started.baseUrl;
    console.log('[boot-smoke] 靜態伺服器啟動: ' + targetUrl + ' (' + started.roots.join(', ') + ')');
  }

  // STEP 03: 收錯並輸出結論
  try {
    const { errors, ignored } = await collectPageErrors(playwright, targetUrl, options.observeMs);
    if (errors.length > 0) {
      console.log('[boot-smoke] FAIL 共 ' + errors.length + ' 筆錯誤（另有 ' + ignored.length + ' 筆已忽略，逐筆見上方 [ignored:*]）：');
      errors.slice(0, 20).forEach((line) => {
        console.log('  ' + line);
      });
      return EXIT_ERRORS_FOUND;
    }
    console.log('[boot-smoke] PASS 觀察 ' + options.observeMs + 'ms 零錯誤（' + ignored.length + ' 筆已忽略，逐筆見上方 [ignored:*]）');
    return EXIT_OK;
  } finally {
    if (server) {
      server.close();
    }
  }
}

main()
  .then((code) => {
    process.exit(code);
  })
  .catch((err) => {
    // 這裡只可能是非預期例外；印出原因並以「有錯誤」收場，不假裝通過
    console.log('[boot-smoke] 非預期例外: ' + (err && err.stack ? err.stack : String(err)));
    process.exit(EXIT_ERRORS_FOUND);
  });
