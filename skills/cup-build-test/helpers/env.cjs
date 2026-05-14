// @ts-check
// CUP E2E Test - Environment 解析 helper
//
// 匯出：
//   - parseEnv(defaults): 解析 process.env 並回傳 frozen EnvConfig
//   - resolveEntryPath(template, params): 替換 {caseId} 等模板變數
//
// 設計：
//   - 預設值集中此處，呼叫端只覆寫差異
//   - 必填欄位（ISSUE_KEY、ENTRY_PATH 含動態參數時對應的 env var）缺失即 process.exit(4)
//   - frozen 物件避免 helper 內部誤改

/** @typedef {import('./types').EnvConfig} EnvConfig */
/** @typedef {import('./types').VariantName} VariantName */

const path = require('path');

/**
 * 解析環境變數並組合 EnvConfig
 * @param {{ issueKey: string, entryPath: string, defaults?: Partial<EnvConfig> }} input
 *   - issueKey: 必填，由 template 填入（如 'CUP-180'）
 *   - entryPath: 必填，可含 {caseId} 等模板變數
 *   - defaults: 選填覆寫預設值
 * @returns {EnvConfig}
 */
function parseEnv(input) {
  // STEP 01: 必填參數驗證
  if (!input || !input.issueKey) {
    console.error('parseEnv: issueKey is required');
    process.exit(4);
  }
  if (!input.entryPath) {
    console.error('parseEnv: entryPath is required');
    process.exit(4);
  }

  // STEP 02: 從 process.env 讀取設定（含 fallback 預設值）
  const issueKey = input.issueKey;
  const variant = /** @type {VariantName} */ (process.env.VARIANT || 'r18');
  const baseUrl = process.env.BASE_URL || 'http://localhost:3000';
  const headless = process.env.HEADLESS !== 'false';
  const stopOnFail = process.env.STOP_ON_FAIL === 'true';
  const only = process.env.ONLY || '';
  const resumeFrom = process.env.RESUME_FROM || '';
  const screenshotDir = path.join('.claude', `${issueKey}-temp`, variant);
  const progressPath = path.join('.claude', `${issueKey}-progress.md`);
  const authPath = '.playwright-auth/auth.json';

  // STEP 03: 解析 ENTRY_PATH 中的 {placeholder}
  const entryPath = resolveEntryPath(input.entryPath);

  // STEP 04: 套用 defaults 覆寫（如 template 想改 authPath 等）
  const merged = {
    issueKey, variant, baseUrl, headless, stopOnFail,
    only, resumeFrom, screenshotDir, progressPath, authPath, entryPath,
    ...(input.defaults || {}),
  };

  return Object.freeze(merged);
}

/**
 * 把 ENTRY_PATH 內 {caseId} 等 placeholder 換成對應 env var
 *   '/case/gServiceSetting/{caseId}' + CASE_ID=abc → '/case/gServiceSetting/abc'
 * camelCase placeholder → SNAKE_CASE env var (caseId → CASE_ID)
 * @param {string} template
 * @returns {string}
 */
function resolveEntryPath(template) {
  return template.replace(/{(\w+)}/g, (_, key) => {
    const envKey = key.replace(/([A-Z])/g, '_$1').toUpperCase();
    const value = process.env[envKey];
    if (!value) {
      console.error(`MISSING_ENV: ${envKey} required for ENTRY_PATH ${template}`);
      process.exit(4);
    }
    return value;
  });
}

module.exports = { parseEnv, resolveEntryPath };
