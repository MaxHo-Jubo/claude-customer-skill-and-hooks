// @ts-check
// CUP E2E Test - 公告 Modal dismiss + 殘留 Modal cleanup helper
//
// 匯出：
//   - DEFAULT_ANNOUNCEMENT_SELECTORS: luna 已知會跳的兩種公告 modal
//   - dismissAnnouncement(page, extraSelectors?): nuclear DOM remove
//   - waitAndDismissOnEntry(page, options?): entry page 完整 dismiss 流程（click + nuke）
//   - ensureCleanState(page, options?): mutation step 入口的防禦性 cleanup（CUP-179 實戰新增）
//
// 設計：
//   - luna 登入後常跳兩種 modal，都會攔截 pointer events 讓後續 step 全 fail
//   - selector 集中此處，將來新 modal 直接加進 DEFAULT 或從 extraSelectors 疊加
//
// 已知 luna 公告 modal（CUP-180 實戰確認）：
//   - .latest-release-rote-modal：最新版本公告（每次登入跳）
//   - .FeatureTermsOfUseModal：功能使用條款（feature 上線跳）

/**
 * luna 已知公告 modal selector
 * 新增模式時直接 push 此陣列，dismiss helper 會自動處理
 */
const DEFAULT_ANNOUNCEMENT_SELECTORS = [
  '.latest-release-rote-modal',
  '.FeatureTermsOfUseModal',
];

/**
 * 額外要 nuke 的通用 selector（modal-backdrop / popover / tooltip）
 * dismiss 時一併處理避免 pointer events 被攔
 */
const GENERIC_OVERLAY_SELECTORS = [
  '.modal-backdrop',
  '.popover',
  '.tooltip',
];

/**
 * Nuclear dismiss 公告 modal — 直接從 DOM 移除（不點 confirm）
 * 用途：navigate 到其他 case 後重複呼叫；click + checkbox 流程已在 waitAndDismissOnEntry 跑過
 *
 * @param {import('playwright').Page} page
 * @param {string[]} [extraSelectors] 額外要 nuke 的 selector（疊加到 DEFAULT）
 */
async function dismissAnnouncement(page, extraSelectors = []) {
  const selectors = [
    ...DEFAULT_ANNOUNCEMENT_SELECTORS,
    ...GENERIC_OVERLAY_SELECTORS,
    ...extraSelectors,
  ];
  await page.evaluate((/** @type {string[]} */ sels) => {
    for (const sel of sels) {
      document.querySelectorAll(sel).forEach((el) => el.remove());
    }
    // STEP 01: 解鎖 body scroll（Bootstrap modal 加的）
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';
  }, selectors);
}

/**
 * 單輪 dismiss pass — 等 modal 出現 → click confirm/checkbox → nuclear nuke
 * 內部 helper，waitAndDismissOnEntry 多輪呼叫；不對外匯出
 *
 * @param {import('playwright').Page} page
 * @param {string[]} extraSelectors  除 DEFAULT 外要處理的 modal selector
 * @param {number} timeout  等 modal 出現的 timeout（ms）
 */
async function runDismissPass(page, extraSelectors, timeout) {
  const modalSelectors = [...DEFAULT_ANNOUNCEMENT_SELECTORS, ...extraSelectors];
  const joinedSelector = modalSelectors.join(', ');

  // STEP 01: 等任一公告 modal 出現（超時不報錯）
  const found = await page.waitForSelector(joinedSelector, {
    timeout,
    state: 'visible',
  }).then(() => true).catch(() => false);

  // STEP 02: 試著勾 checkbox + 點 confirm（click 不一定生效，但有些 modal 需要才不會再跳）
  if (found) {
    try {
      const checkboxSelector = modalSelectors
        .map((s) => `${s} input[type="checkbox"]`)
        .join(', ');
      const cb = page.locator(checkboxSelector).first();
      if (await cb.count() > 0 && !(await cb.isChecked())) {
        await cb.check({ timeout: 2000 }).catch(() => {});
      }
      const confirmBtnSelector = modalSelectors
        .flatMap((s) => [
          `${s} button:has-text("確定")`,    // luna 公告 modal 實際用此（CUP-179 實戰糾正）
          `${s} button:has-text("確認")`,
          `${s} button:has-text("同意")`,
          `${s} button:has-text("我知道了")`,
          `${s} button:has-text("關閉")`,
        ])
        .join(', ');
      const confirmBtn = page.locator(confirmBtnSelector).first();
      if (await confirmBtn.count() > 0) {
        await confirmBtn.click({ timeout: 3000, force: true }).catch(() => {});
      }
      await page.waitForTimeout(300);
    } catch {
      // STEP 02.01: click 失敗無妨，下面 nuclear 會處理
    }
  }

  // STEP 03: Nuclear DOM remove（最終保險；DOM 沒 modal 時 querySelectorAll 回空，no-op）
  await dismissAnnouncement(page, extraSelectors);
}

/**
 * 進入頁面後的完整 dismiss 流程（多輪重試）：
 *   1. 第一輪：等 timeout 內公告 modal 出現 → click confirm/checkbox → nuke
 *   2. 重試輪 × retries：用 retryTimeout 短等再次 dismiss
 *      LVB-7963 實戰兩種情境都會撞到：
 *        (a) modal mount 比第一輪 timeout 慢 → i=0 miss、i=1 catch
 *        (b) modal 被 nuke 後 React 又 re-mount → i=0 hit、i=1 再 catch 第二次
 *      因此無論 i=0 是否命中，都必須跑完 retry 輪（不可 early-exit）
 *
 * @param {import('playwright').Page} page
 * @param {{
 *   timeout?: number,
 *   extraSelectors?: string[],
 *   waitMs?: number,
 *   retries?: number,
 *   retryTimeout?: number,
 * }} [options]
 *   - timeout: 第一輪等 modal 出現的 timeout（預設 5000ms）
 *   - extraSelectors: 除 DEFAULT 外要處理的 modal selector
 *   - waitMs: 每輪結束額外等待時間（預設 500ms）
 *   - retries: 額外重試輪數，捕捉晚到 / re-mount 的 modal（預設 1）
 *   - retryTimeout: 重試輪等 modal 出現的 timeout（預設 3000ms，比首輪短）
 */
async function waitAndDismissOnEntry(page, options = {}) {
  const {
    timeout = 5000,
    extraSelectors = [],
    waitMs = 500,
    retries = 1,
    retryTimeout = 3000,
  } = options;

  for (let i = 0; i <= retries; i += 1) {
    const passTimeout = i === 0 ? timeout : retryTimeout;
    await runDismissPass(page, extraSelectors, passTimeout);
    await page.waitForTimeout(waitMs);
  }
}

/**
 * 「真正的」編輯/確認/檢視 modal 的預設 selector
 *   排除公告 modal（latest-release-rote-modal / FeatureTermsOfUseModal）
 *   R15 用 `.modal.in`、R18 用 `.modal.show`，兩者皆覆蓋
 */
const DEFAULT_APP_MODAL_SEL = [
  ...DEFAULT_ANNOUNCEMENT_SELECTORS.map((s) => `.modal.in:not(${s})`),
  ...DEFAULT_ANNOUNCEMENT_SELECTORS.map((s) => `.modal.show:not(${s})`),
].join(', ');

/**
 * 防禦性 cleanup — 確保 case 開始時頁面處於乾淨狀態
 *
 * 解決問題（CUP-179 實戰）：連跑 case 時前面留下的 modal 殘留會：
 *   1. 攔截後續 click（pointer events 被擋）
 *   2. 破壞 React/Redux state 與 DOM 的同步（直接 nuke DOM 但 Redux state 還是 true
 *      → 下次 dispatch show modal 時 state 沒變化 → React 不重 render → modal 不顯示）
 *
 * 流程：
 *   1. dismiss 公告 modal（可能延遲跳出）
 *   2. 若有殘留 app modal，先點「取消」/「否」讓 Redux state 同步（dispatch hideModal）
 *   3. 再 nuke DOM 上殘留（雙保險）
 *   4. 清 body.modal-open / overflow / paddingRight
 *
 * 用法：每個 mutation step 入口呼叫
 *   await mutationStep('C2.1', 'edit-save-flow', async (p) => {
 *     await ensureCleanState(p);
 *     // ... 真正的測試邏輯
 *   });
 *
 * 為何只在 mutation step 用：
 *   - read-only step 不開 modal，前面殘留 modal 不影響
 *   - mutation step 會開 modal 改 state，最容易撞到「殘留 state 干擾」
 *   - 全部 step 都加會增加總跑時間（0.5-1s × 30 case），不划算
 *
 * @param {import('playwright').Page} page
 * @param {{ appModalSel?: string, extraAnnouncementSelectors?: string[], waitMs?: number }} [options]
 *   - appModalSel: 自訂編輯/確認 modal selector（預設 DEFAULT_APP_MODAL_SEL）
 *   - extraAnnouncementSelectors: 公告 modal 之外的額外 selector
 *   - waitMs: 流程結束後等待時間（預設 500ms）
 */
async function ensureCleanState(page, options = {}) {
  const {
    appModalSel = DEFAULT_APP_MODAL_SEL,
    extraAnnouncementSelectors = [],
    waitMs = 500,
  } = options;

  // STEP 01: 公告 modal dismiss（可能延遲跳出）
  await dismissAnnouncement(page, extraAnnouncementSelectors);

  // STEP 02: 檢查是否有殘留 app modal（編輯/確認/檢視）
  const residualCount = await page.locator(appModalSel).count();
  if (residualCount > 0) {
    // STEP 02.01: 先試點「取消」/「否」讓 Redux state 同步
    //   優先序：取消 > 否 > 關閉（避免誤點「是」「確認」等送出操作的按鈕）
    const cancelBtn = page.locator(appModalSel)
      .locator('button:has-text("取消"), button:has-text("否"), button:has-text("關閉")')
      .first();
    if (await cancelBtn.count() > 0) {
      await cancelBtn.click({ timeout: 2000, force: true }).catch(() => {});
      await page.waitForTimeout(500);
    }

    // STEP 02.02: 不管成不成，nuke DOM 上殘留
    await page.evaluate((/** @type {string} */ sel) => {
      document.querySelectorAll(sel).forEach((el) => el.remove());
      document.querySelectorAll('.modal-backdrop').forEach((el) => el.remove());
      document.body.classList.remove('modal-open');
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    }, appModalSel);
  }

  // STEP 03: 等狀態穩定
  await page.waitForTimeout(waitMs);
}

module.exports = {
  DEFAULT_ANNOUNCEMENT_SELECTORS,
  DEFAULT_APP_MODAL_SEL,
  GENERIC_OVERLAY_SELECTORS,
  dismissAnnouncement,
  waitAndDismissOnEntry,
  ensureCleanState,
};
