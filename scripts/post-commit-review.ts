#!/usr/bin/env bun

/**
 * PostToolUse hook：git commit 後提醒 Claude 依分級制執行 review。
 *
 * 注意：PostToolUse hook 的 systemMessage 會在下一個 turn 注入 AI context。
 * ~/.claude/harness/commit-review-policy.md 為主要驅動層（Tier 0~3 分級），hook 為安全網。
 * 2026-07-03 改造：移除內建 eslint 執行（原本最多同步阻塞 30 秒；eslint 改由分級制在 Tier 1+ 驅動）。
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

    // STEP 05: 透過 systemMessage 提醒依分級制執行 review
    console.log(JSON.stringify({
      systemMessage: '📋 Post-commit review 觸發：依 ~/.claude/harness/commit-review-policy.md 執行分級審查——先跑 git show --stat HEAD --format="" 判定 Tier（0 純文件→只通知；1 小改動→eslint＋DoD 自查；2 標準→＋/simplify＋pr-reviewer lite；3 大改動→全套），有疑義向上取嚴。'
    }));
  } catch {
    process.exit(0);
  }
});
