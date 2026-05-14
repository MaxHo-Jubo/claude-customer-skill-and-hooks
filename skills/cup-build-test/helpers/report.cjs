// @ts-check
// CUP E2E Test - 結果報告 helper
//
// 匯出：
//   - writeResultsJson(dir, payload): 寫 _results.json
//   - printSummary(results, consoleErrors): stdout 印一行 summary
//   - exitCodeForResults(results): 有 FAIL 回 1，否則 0

/** @typedef {import('./types').StepResult} StepResult */

const fs = require('fs');
const path = require('path');

/**
 * 寫完整結果 JSON 到 SCREENSHOT_DIR/_results.json
 * @param {string} dir 截圖目錄（與 _results.json 同層）
 * @param {{
 *   issueKey: string,
 *   variant: string,
 *   baseUrl: string,
 *   results: StepResult[],
 *   consoleErrors: string[],
 * }} payload
 */
function writeResultsJson(dir, payload) {
  const summary = {
    total: payload.results.length,
    pass: payload.results.filter((r) => r.status === 'PASS').length,
    fail: payload.results.filter((r) => r.status === 'FAIL').length,
    skip: payload.results.filter((r) => r.status === 'SKIP').length,
  };
  fs.writeFileSync(
    path.join(dir, '_results.json'),
    JSON.stringify({ ...payload, summary }, null, 2),
  );
}

/**
 * stdout 印一行 summary（給 ctx_execute / stdout 解析用）
 * @param {StepResult[]} results
 * @param {string[]} consoleErrors
 */
function printSummary(results, consoleErrors) {
  const pass = results.filter((r) => r.status === 'PASS').length;
  const skip = results.filter((r) => r.status === 'SKIP').length;
  console.log(
    `\nDONE: ${pass}/${results.length} PASS (skip: ${skip}), console errors: ${consoleErrors.length}`,
  );
}

/**
 * 依結果決定 exit code
 *   - 有任何 FAIL → 1
 *   - 否則 → 0
 * @param {StepResult[]} results
 * @returns {number}
 */
function exitCodeForResults(results) {
  return results.some((r) => r.status === 'FAIL') ? 1 : 0;
}

module.exports = { writeResultsJson, printSummary, exitCodeForResults };
