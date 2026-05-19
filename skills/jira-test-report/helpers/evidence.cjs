// @ts-check
// CUP / Release E2E Test - 斷言證據可視化 helper
//
// 配合 jira-test-report skill v2.4.0「斷言截圖三合一規範」：
//   1. 程式邏輯斷言（throw new Error 含實測 vs 預期對比）
//   2. 真實頁面操作或視覺變更（DOM 至少一處可截圖識別的變化）
//   3. 斷言結論可視化（本檔提供）
//
// 匯出：
//   - injectEvidence(p, ev): 右上角注入紅綠框 evidence panel，列實測 / 預期 / 結論
//   - clearEvidence(p): 移除 evidence panel（避免下個 step 殘留）
//   - expandSelectAsListbox(selectLocator): 把 <select> 強制變 listbox 一次展示所有 option
//
// 使用情境：
//   - 純資料斷言 step（陣列 includes / 順序比對）會讓截圖前後雷同 → 用 injectEvidence 標結論
//   - <select> 下拉選項驗證 → expandSelectAsListbox 把 dropdown 變 listbox 截圖
//   - cancel modal 或離開頁面前 → clearEvidence 避免 overlay 殘留

/**
 * 在頁面右上角注入證據面板，列出實測 / 預期 / 結論
 * 同 step 內可重複呼叫，舊面板會被移除再注入
 * 截圖直接呈現「斷言依據與結論」，非工程 stakeholder 看 Jira / Actions artifact 一眼可判讀
 *
 * @param {import('playwright').Page} p
 * @param {{
 *   title: string,
 *   actual: any,
 *   expected?: any,
 *   conclusion: string,
 *   ok: boolean,
 * }} ev
 */
async function injectEvidence(p, ev) {
  await p.evaluate((e) => {
    // STEP 01: 先移除舊面板
    const old = document.getElementById('e2e-evidence-panel');
    if (old) { old.remove(); }
    // STEP 02: 建證據面板（fixed 右上、紅綠框依結論）
    const div = document.createElement('div');
    div.id = 'e2e-evidence-panel';
    const borderColor = e.ok ? '#3c763d' : '#a94442';
    div.style.cssText = [
      'position:fixed', 'top:8px', 'right:8px', 'z-index:99999',
      'background:#fff', `border:3px solid ${borderColor}`,
      'padding:10px 14px', 'font:13px/1.5 monospace', 'max-width:480px',
      'max-height:90vh', 'overflow:auto',
      'box-shadow:0 4px 12px rgba(0,0,0,0.25)',
    ].join(';');
    const fmt = (v) => typeof v === 'string' ? v : JSON.stringify(v, null, 2);
    const expectedBlock = e.expected
      ? `<div style="margin-bottom:4px"><b>預期</b>：<pre style="margin:2px 0;white-space:pre-wrap">${fmt(e.expected)}</pre></div>`
      : '';
    div.innerHTML =
      `<div style="font-weight:bold;font-size:14px;margin-bottom:6px;color:${borderColor}">` +
        `${e.ok ? '✅' : '❌'} ${e.title}` +
      `</div>` +
      `<div style="margin-bottom:4px"><b>實測</b>：<pre style="margin:2px 0;white-space:pre-wrap">${fmt(e.actual)}</pre></div>` +
      expectedBlock +
      `<div style="margin-top:6px;padding-top:6px;border-top:1px solid #ddd"><b>結論</b>：${e.conclusion}</div>`;
    document.body.appendChild(div);
  }, ev);
}

/**
 * 清除頁面上的 evidence overlay
 * 用於 cancel modal / 換頁前避免下個 step 截圖殘留
 *
 * @param {import('playwright').Page} p
 */
async function clearEvidence(p) {
  await p.evaluate(() => {
    const el = document.getElementById('e2e-evidence-panel');
    if (el) { el.remove(); }
  });
}

/**
 * 把 native <select> 強制變 listbox 一次展示所有 option
 * 對應三合一規範 (a)「強制 native 元素展開呈現」手法
 *
 * 副作用：select 高度會撐大；若 modal 設了 overflow hidden 可能被裁切，
 * 必要時自行對 modal-body 加 overflow:auto。
 *
 * @param {import('playwright').Locator} selectLocator
 */
async function expandSelectAsListbox(selectLocator) {
  await selectLocator.evaluate((el) => {
    const s = /** @type {HTMLSelectElement} */ (el);
    s.size = s.options.length;
    s.style.maxHeight = '400px';
    s.style.overflow = 'auto';
  });
}

module.exports = { injectEvidence, clearEvidence, expandSelectAsListbox };
