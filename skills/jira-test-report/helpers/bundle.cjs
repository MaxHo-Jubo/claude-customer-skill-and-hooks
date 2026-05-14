// @ts-check
// CUP E2E Test - Bundle / Variant 偵測 helper
//
// 匯出：
//   - detectBundle(page): 回傳 BundleInfo（hasR15 / hasR18 / hasReactBsTable / fiberKey）
//   - assertVariant(page, expected): 驗證 bundle 是否為指定 variant，不符即 throw
//
// 設計：
//   - luna FE 雙 codebase：react_15 與 react_18 共存，由 featureSetting flag 切換
//   - R15 識別：bundle path /build/react15/、.react-bs-table、__reactInternalInstance$
//   - R18 識別：bundle path /build/react18/、無 .react-bs-table、__reactFiber$

/** @typedef {import('./types').BundleInfo} BundleInfo */
/** @typedef {import('./types').VariantName} VariantName */

/**
 * 偵測當前頁面 bundle 與 React 內部結構，回傳 R15/R18 判斷依據
 * @param {import('playwright').Page} page
 * @returns {Promise<BundleInfo>}
 */
async function detectBundle(page) {
  // STEP 01: 抓所有 <script src> 路徑
  /** @type {string[]} */
  const srcs = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('script[src]'))
      .map((s) => /** @type {HTMLScriptElement} */ (s).src);
  });
  const hasR15 = srcs.some((/** @type {string} */ s) => s.includes('/react15/'));
  const hasR18 = srcs.some((/** @type {string} */ s) => s.includes('/react18/'));

  // STEP 02: 偵測 .react-bs-table（R15 用 react-bootstrap-table，R18 不用）
  const reactBsCount = await page.locator('.react-bs-table').count();
  const hasReactBsTable = reactBsCount > 0;

  // STEP 03: 抓 React fiber key（R15/16 用 __reactInternalInstance$，R17+ 改 __reactFiber$）
  const fiberKey = await page.evaluate(() => {
    const root =
      document.querySelector('[data-reactroot]') ||
      document.querySelector('#root') ||
      document.body.firstElementChild;
    if (!root) { return null; }
    const keys = Object.keys(root);
    return {
      hasInternalInstance: keys.some((k) => k.startsWith('__reactInternalInstance')),
      hasReactFiber: keys.some((k) => k.startsWith('__reactFiber')),
      sample: keys.filter((k) => k.startsWith('__react')).slice(0, 3),
    };
  });

  return { hasR15, hasR18, hasReactBsTable, fiberKey };
}

/**
 * 驗證 bundle 為指定 variant，不符即 throw（供 step 內呼叫）
 * 規則：
 *   - r15: bundle path 必含 /react15/ 且 .react-bs-table 存在
 *   - r18: bundle path 必含 /react18/ 且 .react-bs-table 不存在
 *
 * @param {import('playwright').Page} page
 * @param {VariantName} expected
 * @throws {Error} 若 bundle 與 expected 不符
 */
async function assertVariant(page, expected) {
  const info = await detectBundle(page);

  // STEP 01: bundle path 驗證
  if (expected === 'r15' && !info.hasR15) {
    throw new Error(
      `expected R15 bundle but found ${info.hasR18 ? 'react18' : 'unknown'}`,
    );
  }
  if (expected === 'r18' && !info.hasR18) {
    throw new Error(
      `expected R18 bundle but found ${info.hasR15 ? 'react15' : 'unknown'}`,
    );
  }

  // STEP 02: 元件特徵驗證
  if (expected === 'r15' && !info.hasReactBsTable) {
    throw new Error('R15 expected .react-bs-table but not found');
  }
  if (expected === 'r18' && info.hasReactBsTable) {
    throw new Error(`R18 unexpectedly has .react-bs-table`);
  }

  // STEP 03: fiber key 驗證（R15 = __reactInternalInstance$, R18 = __reactFiber$）
  if (info.fiberKey) {
    if (expected === 'r15' && !info.fiberKey.hasInternalInstance) {
      throw new Error(
        `R15 expected __reactInternalInstance$, found: ${info.fiberKey.sample.join(',')}`,
      );
    }
    if (expected === 'r18' && !info.fiberKey.hasReactFiber) {
      throw new Error(
        `R18 expected __reactFiber$, found: ${info.fiberKey.sample.join(',')}`,
      );
    }
  }
}

module.exports = { detectBundle, assertVariant };
