#!/usr/bin/env node
'use strict';

/**
 * PostToolUse hook：git commit 後自動觸發 /simplify + /code-review 流程。
 *
 * 觸發條件：Bash 執行的命令包含 `git commit`
 * 例外：命令同時包含 `push`（commit and push 場景跳過）
 *
 * 流程：
 * 1. /simplify → 有變更則 amend commit，無變更則跳過
 * 2. /code-review → 自動修正 80+ issue，不 commit，列出所有 issue
 * 3. 發送終端機通知
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

    // STEP 03: 例外 — 命令包含 push 則跳過（commit and push 場景）
    if (command.match(/push/i)) {
      process.exit(0);
    }

    // STEP 04: 確認 commit 成功（排除失敗、空 commit 等）
    const output = typeof data.tool_output === 'string'
      ? data.tool_output
      : JSON.stringify(data.tool_output || '');

    if (output.includes('nothing to commit') ||
        output.includes('no changes added') ||
        output.match(/^fatal:/m) ||
        output.match(/^error:/m)) {
      process.exit(0);
    }

    // STEP 05: 輸出 AI 指令（利用本機 repo 做更精確的 review）
    const instructions = [
      '',
      '🔄 Post-Commit Review Hook 觸發',
      '━'.repeat(40),
      '請依序執行以下步驟：',
      '',
      '**步驟 1 — /simplify**',
      '- 對剛才 commit 的變更執行 /simplify（程式碼精簡檢查）',
      '- 若 /simplify 產生修改 → `git add` 變更的檔案，然後 `git commit --amend --no-edit` 合併到上一個 commit',
      '- 若無變更 → 跳過，維持原 commit',
      '',
      '**步驟 2 — 收集本機 repo 上下文**',
      '- 執行 `git diff HEAD~1 --name-only` 取得變更檔案清單',
      '- 對每個變更檔案執行 `git blame HEAD -- <file>` 取得歷史脈絡',
      '- 讀取每個變更檔案的完整內容（特別注意函式頂部的註解和約束條件）',
      '- 檢查變更檔案所在目錄是否有 CLAUDE.md，有則一併讀取',
      '',
      '**步驟 3 — /code-review（帶入本機上下文）**',
      '- 將步驟 2 收集的上下文（blame、完整檔案、CLAUDE.md）提供給 review agents',
      '- review 時優先使用本機 `git` 指令而非 `gh api`，因為已在本機 repo 中',
      '- 自動修正所有 **80 分以上** 的 issue（直接改檔案）',
      '- **不要 commit** 這些修正',
      '- 列出所有找到的 issue（含分數與說明）',
      '',
      '**步驟 4 — 終端機通知**',
      '- 發送通知：「commit 與 review 完成，等待下一步」',
      '',
      '⚠️ 這是自動觸發的 post-commit 流程，請依序完成。',
    ].join('\n');

    console.log(instructions);
  } catch {
    // 靜默失敗
    process.exit(0);
  }
});
