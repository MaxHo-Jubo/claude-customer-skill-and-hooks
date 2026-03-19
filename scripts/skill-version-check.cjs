#!/usr/bin/env node
'use strict';

/**
 * PostToolUse hook：SKILL.md 被編輯時，檢查 version 是否有更新。
 * 若內容有改動但 version 行沒變，提醒使用者進版。
 *
 * 觸發條件：Edit 或 Write tool 對 */skills/*/SKILL.md 檔案操作
 */

let input = '';
process.stdin.setEncoding('utf8');

/** stdin 超時防呆 */
const stdinTimeout = setTimeout(() => { process.exit(0); }, 2000);

process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);

    // STEP 01: 只處理 Edit 和 Write 工具
    const tool = data.tool_name;
    if (tool !== 'Edit' && tool !== 'Write') {
      process.exit(0);
    }

    // STEP 02: 確認是 SKILL.md 檔案
    const filePath = data.tool_input?.file_path || '';
    if (!filePath.match(/\/skills\/[^/]+\/SKILL\.md$/)) {
      process.exit(0);
    }

    // STEP 03: 檢查是否有更新 version 欄位
    const oldStr = data.tool_input?.old_string || '';
    const newStr = data.tool_input?.new_string || '';
    const content = data.tool_input?.content || '';

    /** 判斷 version 行是否在本次編輯中被改動 */
    const versionChanged = oldStr.includes('version:') ||
      newStr.includes('version:') ||
      (tool === 'Write' && content.includes('version:'));

    // STEP 04: 如果 version 沒被改動，發出提醒
    if (!versionChanged) {
      const skillName = filePath.match(/\/skills\/([^/]+)\/SKILL\.md$/)?.[1] || 'unknown';
      console.log(JSON.stringify({
        systemMessage: `⚠️ skill「${skillName}」的 SKILL.md 已修改但 version 未更新，記得進版號（semver）`
      }));
    }
  } catch {
    process.exit(0);
  }
});
