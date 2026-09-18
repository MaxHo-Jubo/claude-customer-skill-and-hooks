/**
 * 差異測試 harness 共用的環境路徑解析。
 * jest.config.js、babel.config.js、smoke.test.js 都需要同一組「REPO_DIR 底下兩棵前端樹的路徑」，
 * 依專案 EXTRACT-SHARED-HELPER 慣例——同一個概念性判斷第一次出現在 2 個以上呼叫點就抽共用 helper，
 * 不各寫一份、之後各自分歧。
 */
'use strict';

const path = require('path');
const os = require('os');

/**
 * 解析並回傳 harness 執行所需的全部路徑資訊。
 * REPO_DIR 沒有預設值：猜錯 repo 位置會讓測試安靜地在錯的樹上跑出「全部通過」的假訊號，
 * 這比直接丟出錯誤更危險，所以缺少時一律 throw，不做任何猜測性 fallback。
 * @returns {{
 *   repoDir: string,
 *   react15Dir: string,
 *   react18Dir: string,
 *   react15NodeModules: string,
 *   react18NodeModules: string,
 *   migrationStateDir: string,
 *   diffTestDir: string,
 * }} 解析後的路徑集合
 */
function resolveHarnessEnv() {
  // STEP 01: REPO_DIR 為必填，指向目標 repo 根目錄（內含 frontend/react_15 與 frontend/react_18）
  const repoDir = process.env.REPO_DIR;
  if (!repoDir) {
    throw new Error('REPO_DIR 未設定：需指向目標 repo 根目錄（內含 frontend/react_15 與 frontend/react_18）');
  }

  // STEP 02: 組出兩棵前端樹與各自 node_modules 的絕對路徑
  const react15Dir = path.join(repoDir, 'frontend', 'react_15');
  const react18Dir = path.join(repoDir, 'frontend', 'react_18');
  const react15NodeModules = path.join(react15Dir, 'node_modules');
  const react18NodeModules = path.join(react18Dir, 'node_modules');

  // STEP 03: 狀態目錄與差異測試檔目錄，預設值沿用本 skill 既有 MIGRATION_STATE_DIR 慣例
  // （家目錄下 r18-migration-state/<repo 資料夾名稱>/），未設定 DIFF_TEST_DIR 時退回其下的 diff-tests/
  const defaultMigrationStateDir = path.join(os.homedir(), 'r18-migration-state', path.basename(repoDir));
  const migrationStateDir = process.env.MIGRATION_STATE_DIR || defaultMigrationStateDir;
  const diffTestDir = process.env.DIFF_TEST_DIR || path.join(migrationStateDir, 'diff-tests');

  return {
    repoDir,
    react15Dir,
    react18Dir,
    react15NodeModules,
    react18NodeModules,
    migrationStateDir,
    diffTestDir,
  };
}

/**
 * 從指定 node_modules 目錄解析一個套件的絕對入口路徑；解析不到時 throw 帶清楚訊息的錯誤，
 * 不做任何靜默 fallback——找不到套件就是環境沒裝好或 REPO_DIR 指錯，讓呼叫方立刻知道要修哪裡，
 * 而不是留給後面某個看似無關的錯誤訊息去猜。
 * @param {string} nodeModulesDir - 搜尋起點的 node_modules 絕對路徑
 * @param {string} packageName - 要解析的套件名稱
 * @returns {string} 套件入口檔的絕對路徑
 */
function resolvePackageFrom(nodeModulesDir, packageName) {
  try {
    // STEP 01: 用 require.resolve 的 paths 選項指定搜尋起點，不依賴 NODE_PATH 或 process.cwd()
    return require.resolve(packageName, { paths: [nodeModulesDir] });
  } catch (err) {
    throw new Error(`找不到套件「${packageName}」（搜尋目錄：${nodeModulesDir}）。原始錯誤：${err.message}`);
  }
}

module.exports = { resolveHarnessEnv, resolvePackageFrom };
