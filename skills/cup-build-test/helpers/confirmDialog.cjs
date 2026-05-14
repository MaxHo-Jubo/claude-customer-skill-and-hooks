// @ts-check
// CUP E2E Test - 確認對話框（二次確認）處理 helper
//
// 匯出：
//   - confirmYes(page, options?): 點「是 / 確認 / 確定 / 刪除 / 同意」按鈕（接受操作）
//   - confirmNo(page, options?): 點「否 / 取消 / 關閉」按鈕（拒絕操作）
//   - DEFAULT_YES_BUTTON_TEXTS / DEFAULT_NO_BUTTON_TEXTS: 預設按鈕文字清單
//
// 設計動機（CUP-179 實戰）：
//   luna R18 mutation 流程常跳「二次確認對話」，原本散落各 case inline 處理：
//   - C2.1 編輯送出 → 跳「改動此日期可能會造成統計資料的改動」→ 點「是」
//   - D1.1 刪除主流程 → 跳刪除確認對話 → 點「是」/「確認」/「刪除」
//   - 不同 mutation 流程確認按鈕文字可能不一樣，但語意都是「接受/拒絕」
//
//   helper 統一處理：
//   - 預設文字清單按優先序排列，按鈕命中即點
//   - strategy=last（預設）：DOM 順序最後 = 最新跳出的 modal（適合「edit modal 上又跳確認對話」場景）
//   - strategy=first：適合單一 modal 場景
//   - scope 參數：可限定在特定 locator 範圍內找，避免誤點其他 modal 按鈕

/**
 * 接受操作的按鈕文字（按優先序）
 *
 * 順序考量：
 *   - 「是」第一：luna 常見的「確定要更改嗎? 是/否」對話框
 *   - 「確認」「確定」次之：通用確認對話
 *   - 「刪除」「同意」：刪除流程 / 條款同意
 *
 * 警示：不放「儲存」「送出」這類**啟動操作**的按鈕文字 — 那是 mutation 起點，
 *   不是「二次確認接受」按鈕。誤把儲存當 confirmYes 會在 modal 沒跳時直接送 mutation。
 */
const DEFAULT_YES_BUTTON_TEXTS = ['是', '確認', '確定', '刪除', '同意'];

/**
 * 拒絕操作的按鈕文字（按優先序）
 */
const DEFAULT_NO_BUTTON_TEXTS = ['否', '取消', '關閉'];

/**
 * @typedef {Object} ConfirmOptions
 * @property {number} [timeout] click timeout（預設 5000ms）
 * @property {import('playwright').Locator} [scope] 限定查找範圍（預設 page 全域）
 * @property {string[]} [extraButtonTexts] 額外可接受的按鈕文字（疊加到預設清單前）
 * @property {'last'|'first'} [strategy] 'last' (default) 抓 DOM 後出現的 modal、'first' 抓第一個
 */

/**
 * 從文字清單組合 selector
 * @param {string[]} texts
 * @returns {string}
 */
function buildButtonSelector(texts) {
  return texts.map((t) => `button:has-text("${t}")`).join(', ');
}

/**
 * 點確認對話框的「接受」按鈕（是 / 確認 / 確定 / 刪除 / 同意）
 *
 * 用法範例：
 *   // C2.1 編輯送出，按儲存後跳「改動此日期...」確認對話
 *   await modal.locator(SAVE_BTN_SEL).first().click();
 *   await confirmYes(p);
 *
 *   // D1.1 刪除，限定在特定 modal scope 內找按鈕
 *   await deleteBtn.click();
 *   await confirmYes(p, { scope: p.locator(CONFIRM_SEL) });
 *
 *   // 加自訂按鈕文字（例如 modal 用「我要刪除」）
 *   await confirmYes(p, { extraButtonTexts: ['我要刪除'] });
 *
 * @param {import('playwright').Page} page
 * @param {ConfirmOptions} [options]
 */
async function confirmYes(page, options = {}) {
  const {
    timeout = 5000,
    scope,
    extraButtonTexts = [],
    strategy = 'last',
  } = options;
  const texts = [...extraButtonTexts, ...DEFAULT_YES_BUTTON_TEXTS];
  const selector = buildButtonSelector(texts);
  const root = scope || page;
  const btn = strategy === 'last'
    ? root.locator(selector).last()
    : root.locator(selector).first();
  await btn.click({ timeout, force: true });
}

/**
 * 點確認對話框的「拒絕」按鈕（否 / 取消 / 關閉）
 *
 * 用法範例：
 *   // D1.2 取消刪除：點刪除按鈕後跳確認，按取消
 *   await deleteBtn.click();
 *   await confirmNo(p, { scope: p.locator(CONFIRM_SEL) });
 *
 * @param {import('playwright').Page} page
 * @param {ConfirmOptions} [options]
 */
async function confirmNo(page, options = {}) {
  const {
    timeout = 5000,
    scope,
    extraButtonTexts = [],
    strategy = 'last',
  } = options;
  const texts = [...extraButtonTexts, ...DEFAULT_NO_BUTTON_TEXTS];
  const selector = buildButtonSelector(texts);
  const root = scope || page;
  const btn = strategy === 'last'
    ? root.locator(selector).last()
    : root.locator(selector).first();
  await btn.click({ timeout, force: true });
}

module.exports = {
  DEFAULT_YES_BUTTON_TEXTS,
  DEFAULT_NO_BUTTON_TEXTS,
  confirmYes,
  confirmNo,
};
