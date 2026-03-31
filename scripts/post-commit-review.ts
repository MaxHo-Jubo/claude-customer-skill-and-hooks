#!/usr/bin/env bun
import { execSync } from 'child_process';

/**
 * PostToolUse hook：git commit 後提醒使用者 Claude 應執行 review 流程。
 *
 * 注意：PostToolUse hook 的 systemMessage 會在下一個 turn 注入 AI context。
 * CLAUDE.md POST-COMMIT-REVIEW 規則為主要驅動層，hook 為安全網。
 *
 * 觸發條件：Bash 執行的命令包含 `git commit`
 * 例外：命令同時包含 `push`（commit and push 場景跳過）
 */

/** hook 的 stdin JSON 資料 */
let input = '';
process.stdin.setEncoding('utf8');

/** stdin 超時防呆：2 秒內未收到資料則靜默退出 */
const stdinTimeout = setTimeout(() => { process.exit(0); }, 2000);

process.stdin.on('data', (chunk: string) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);

    // STEP 01: 只處理 Bash 工具
    if (data.tool_name !== 'Bash') {
      process.exit(0);
    }

    const command: string = data.tool_input?.command || '';

    // STEP 02: 確認是 git commit 命令
    if (!command.match(/git\s+commit/)) {
      process.exit(0);
    }

    // STEP 03: 例外 — 命令包含 push 則跳過
    if (command.match(/push/i)) {
      process.exit(0);
    }

    // STEP 04: 確認 commit 成功
    const output = typeof data.tool_output === 'string'
      ? data.tool_output
      : JSON.stringify(data.tool_output || '');

    if (output.includes('nothing to commit') ||
        output.includes('no changes added') ||
        output.match(/^fatal:/m) ||
        output.match(/^error:/m)) {
      process.exit(0);
    }

    // STEP 05: 取得本次 commit 修改的檔案
    let changedFiles: string[] = [];
    try {
      /** 從最近一次 commit 取得修改的 JS/TS 檔案清單 */
      const filesRaw = execSync('git diff --name-only HEAD~1 HEAD -- "*.js" "*.jsx" "*.ts" "*.tsx"', {
        encoding: 'utf8',
        timeout: 5000
      }).trim();
      changedFiles = filesRaw ? filesRaw.split('\n').filter(Boolean) : [];
    } catch {
      changedFiles = [];
    }

    // STEP 06: 對修改的檔案執行 eslint
    let eslintResult = '';
    if (changedFiles.length > 0) {
      try {
        execSync(`npx eslint ${changedFiles.join(' ')}`, {
          encoding: 'utf8',
          timeout: 30000
        });
        /** eslint 通過，無錯誤 */
        eslintResult = '✅ eslint: 全部通過';
      } catch (e: unknown) {
        /** eslint 有錯誤，擷取輸出 */
        const err = e as { stdout?: string; message?: string };
        eslintResult = '❌ eslint 發現問題:\n' + (err.stdout || err.message || '').slice(0, 2000);
      }
    } else {
      eslintResult = '⏭️ eslint: 無 JS/TS 檔案變更，跳過';
    }

    // STEP 07: 透過 systemMessage 回傳 eslint 結果與 review 提醒
    console.log(JSON.stringify({
      systemMessage: `📋 Post-commit review 觸發\n\n${eslintResult}\n\nClaude 應自動執行：eslint 錯誤修正（如有）→ /simplify → /pr-review-toolkit:review-pr code comments errors tests types → 通知`
    }));
  } catch {
    process.exit(0);
  }
});
