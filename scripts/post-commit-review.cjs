#!/usr/bin/env node
'use strict';

/**
 * PostToolUse hook：git commit 後提醒使用者 Claude 應執行 review 流程。
 *
 * 注意：PostToolUse hook 的 stdout 不會注入 AI context，
 * 只能透過 JSON { systemMessage } 顯示給使用者。
 * AI 端的指令改由 feedback memory 驅動。
 *
 * 觸發條件：Bash 執行的命令包含 `git commit`
 * 例外：命令同時包含 `push`（commit and push 場景跳過）
 */

let input = '';
process.stdin.setEncoding('utf8');

/** stdin 超時防呆：2 秒內未收到資料則靜默退出 */
const stdinTimeout = setTimeout(() => { process.exit(0); }, 2000);

process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);

    // STEP 01: 只處理 Bash 工具
    if (data.tool_name !== 'Bash') {
      process.exit(0);
    }

    const command = data.tool_input?.command || '';

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

    // STEP 05: 透過 systemMessage 提醒使用者
    console.log(JSON.stringify({
      systemMessage: '📋 Post-commit review 觸發 — Claude 應自動執行 /simplify → code review → 通知'
    }));
  } catch {
    process.exit(0);
  }
});
