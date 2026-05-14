// @ts-check
// CUP E2E Test - 測試步驟執行 helper
//
// 匯出：
//   - createStepRunner(config): 工廠函式，回傳 { step, skipStep, waitStable, getResults }
//   - caseIdCompare(a, b): caseId 大小比較（給 RESUME_FROM 用）
//
// 設計：
//   - 用 closure 包住 results array，避免全域 state 污染
//   - ONLY / RESUME_FROM filter 內建
//   - 每步自動截圖、計時、寫 progress.md（cross-session resume）

/** @typedef {import('./types').StepResult} StepResult */
/** @typedef {import('./types').StepFn} StepFn */
/** @typedef {import('./types').ProgressFields} ProgressFields */

const fs = require('fs');
const path = require('path');

/**
 * 比較兩個 caseId（如 'A1.1' vs 'A1.2'）
 * 規則：字母優先 → 數字部分逐段比較
 * @param {string} a
 * @param {string} b
 * @returns {number} 負/零/正 表示 a 小於/等於/大於 b
 */
function caseIdCompare(a, b) {
  // STEP 01: 切出開頭字母與數字部分
  const aLetter = a.charAt(0);
  const bLetter = b.charAt(0);
  if (aLetter !== bLetter) {
    return aLetter.localeCompare(bLetter);
  }
  // STEP 02: 數字段逐位比較（A1.1 < A1.2 < A2.1）
  const aParts = a.slice(1).split('.').map(Number);
  const bParts = b.slice(1).split('.').map(Number);
  const len = Math.max(aParts.length, bParts.length);
  for (let i = 0; i < len; i++) {
    const ax = aParts[i] || 0;
    const bx = bParts[i] || 0;
    if (ax !== bx) {
      return ax - bx;
    }
  }
  return 0;
}

/**
 * 跨 session 進度檔更新：把 progress.md 內「caseId + name」對應的 [ ] 改 [x] 並填欄位
 *
 * **唯一性 key**：caseId 不夠，因為同 caseId 可有多 step（A1.1 有 case-list-loaded、
 * case-profile-displayed 兩個 step）。用 caseId + name 完整字串匹配才不會互相覆蓋。
 *
 * 失敗時 silent（progress.md 不存在或格式異常都不影響主流程）
 * @param {string} progressPath
 * @param {string} caseId
 * @param {string} name
 * @param {ProgressFields} fields
 */
function updateProgressMd(progressPath, caseId, name, fields) {
  // STEP 01: 檔案不存在直接跳過（dry-run 沒建檔的情境）
  if (!fs.existsSync(progressPath)) {
    return;
  }
  try {
    // STEP 02: 讀檔 + escape regex（caseId 與 name 都需 escape）
    const content = fs.readFileSync(progressPath, 'utf8');
    const escapeRe = (/** @type {string} */ s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const escapedId = escapeRe(caseId);
    const escapedName = escapeRe(name);
    // STEP 03: 匹配「case 區塊」— `### [ x] caseId name ...` 嚴格匹配 caseId + name，
    //   + 後續任意非 `###` 開頭行（包含 `- ` 明細、Call log、空行、續行內容），
    //   直到下一個 `###` 或檔尾
    const blockRe = new RegExp(
      `(^### \\[[ x]\\] ${escapedId} ${escapedName}(?:[^\\n]*)$)(\\n(?:(?!### )[^\\n]*\\n?)*)`,
      'm',
    );
    const match = content.match(blockRe);
    if (!match) {
      // STEP 03.01: 找不到對應 caseId+name 區塊（progress.md 未列此 step），不影響主流程
      return;
    }
    // STEP 04: 標題行 [ ] → [x]、組新明細
    const newHeader = match[1].replace('[ ]', '[x]');
    const newBlock =
      `${newHeader}\n` +
      `- Status: ${fields.status}\n` +
      `- Screenshot: ${fields.screenshot}\n` +
      `- Run at: ${fields.runAt}\n`;
    // STEP 05: 替換並更新 Last update 欄位
    let updated = content.replace(blockRe, newBlock);
    if (/^Last update: /m.test(updated)) {
      updated = updated.replace(/^Last update: .*$/m, `Last update: ${fields.runAt}`);
    }
    fs.writeFileSync(progressPath, updated);
  } catch {
    // STEP 06: progress.md 寫入失敗不阻斷測試（純輔助檔）
  }
}

/**
 * 建立一組 step / skipStep / waitStable 函式，共用同一份 results 與設定
 * @param {{
 *   screenshotDir: string,
 *   progressPath?: string,
 *   only?: string,
 *   resumeFrom?: string,
 *   stopOnFail?: boolean,
 * }} config
 * @returns {{
 *   step: (page: import('playwright').Page, caseId: string, name: string, fn: StepFn) => Promise<void>,
 *   skipStep: (caseId: string, name: string, reason: string) => void,
 *   waitStable: (page: import('playwright').Page, ms?: number) => Promise<void>,
 *   getResults: () => StepResult[],
 * }}
 */
function createStepRunner(config) {
  // STEP 01: 預設值
  const {
    screenshotDir,
    progressPath = '',
    only = '',
    resumeFrom = '',
    stopOnFail = false,
  } = config;

  /** @type {StepResult[]} */
  const results = [];

  /** @param {StepResult} r */
  function logResult(r) {
    console.log(JSON.stringify(r));
    results.push(r);
  }

  /**
   * 執行單一測試步驟，自動截圖與計時
   * @param {import('playwright').Page} page
   * @param {string} caseId
   * @param {string} name
   * @param {StepFn} fn
   */
  async function step(page, caseId, name, fn) {
    // STEP 01: ONLY filter（指定 prefix 才跑）
    if (only && !caseId.startsWith(only)) {
      return;
    }
    // STEP 02: RESUME_FROM filter — 跨 session 續跑時跳過已完成（caseId ≤ RESUME_FROM）
    if (resumeFrom && caseIdCompare(caseId, resumeFrom) <= 0) {
      return;
    }
    const idx = String(results.length + 1).padStart(2, '0');
    const safeName = `${caseId}-${name}`.replace(/[^\w.-]+/g, '-');
    const screenshot = `${idx}-${safeName}.png`;
    const screenshotPath = path.join(screenshotDir, screenshot);
    const t0 = Date.now();
    let stepStatus = 'PASS';
    /** @type {string | null} */
    let stepError = null;
    try {
      await fn(page);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      logResult({ step: idx, caseId, name, status: 'PASS', screenshot, ms: Date.now() - t0 });
    } catch (e) {
      stepStatus = 'FAIL';
      stepError = e instanceof Error ? e.message : String(e);
      try {
        await page.screenshot({ path: screenshotPath, fullPage: true });
      } catch {
        // STEP 03: 連截圖都失敗就放棄
      }
      logResult({
        step: idx, caseId, name, status: 'FAIL', screenshot,
        error: stepError, ms: Date.now() - t0,
      });
      if (stopOnFail) {
        // STEP 04: STOP_ON_FAIL 模式下也要寫 progress.md 再 throw
        if (progressPath) {
          updateProgressMd(progressPath, caseId, name, {
            status: `FAIL: ${stepError}`,
            screenshot: screenshotPath,
            runAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
          });
        }
        throw e;
      }
    }
    // STEP 05: 每跑完一個 case 立即寫 progress.md（cross-session resume）
    if (progressPath) {
      updateProgressMd(progressPath, caseId, name, {
        status: stepStatus === 'PASS' ? 'PASS' : `FAIL: ${stepError}`,
        screenshot: screenshotPath,
        runAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      });
    }
  }

  /**
   * 記錄 SKIP 狀態（未提供必要 env var 時）；不會 throw，不算 PASS / FAIL
   * @param {string} caseId
   * @param {string} name
   * @param {string} reason
   */
  function skipStep(caseId, name, reason) {
    if (only && !caseId.startsWith(only)) { return; }
    if (resumeFrom && caseIdCompare(caseId, resumeFrom) <= 0) { return; }
    const idx = String(results.length + 1).padStart(2, '0');
    logResult({ step: idx, caseId, name, status: 'SKIP', reason, ms: 0 });
  }

  /**
   * 等待頁面 networkidle + 額外 ms 緩衝，吸收 fade-in 動畫與 react re-render
   * 注意：react-bootstrap-table filter clear 至少需要 700-800ms（CUP-180 實戰確認）
   * @param {import('playwright').Page} page
   * @param {number} [ms=500]
   */
  async function waitStable(page, ms = 500) {
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(ms);
  }

  return {
    step, skipStep, waitStable,
    getResults: () => results,
  };
}

module.exports = { createStepRunner, caseIdCompare, updateProgressMd };
