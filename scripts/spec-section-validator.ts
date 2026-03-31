#!/usr/bin/env bun
import fs from 'fs';
import path from 'path';

/**
 * PostToolUse hook: 驗證 spec markdown 檔案包含必要 section。
 *
 * 觸發條件: Write 或 Edit tool 修改了 spec/*.md 檔案
 * 輸出: 缺少必要 section 時輸出警告
 */

/** 跳過驗證的檔案（導航/索引用途） */
const SKIP_FILES = ['index.md', 'file-mapping.json'];

/** 概述類 section（至少要有一個） */
const OVERVIEW_PATTERNS = ['規模', '概述'];

/** 品質類 section（至少要有一個） */
const QUALITY_PATTERNS = ['品質', '架構觀察'];

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
    const toolName: string = data.tool_name;

    // STEP 01: 只處理 Write 和 Edit
    if (toolName !== 'Write' && toolName !== 'Edit') {
      process.exit(0);
    }

    // STEP 02: 取得檔案路徑
    const filePath: string = data.tool_input?.file_path || '';
    if (!filePath) {
      process.exit(0);
    }

    // STEP 03: 只驗證 spec/ 目錄下的 .md 檔案
    const normalizedPath = filePath.replace(/\\/g, '/');
    if (!normalizedPath.includes('/spec/') || !normalizedPath.endsWith('.md')) {
      process.exit(0);
    }

    // STEP 04: 跳過導航/索引檔案
    const fileName = path.basename(filePath);
    const parentDir = path.basename(path.dirname(filePath));
    if (parentDir === 'spec' && SKIP_FILES.includes(fileName)) {
      process.exit(0);
    }

    // STEP 05: 讀取檔案內容
    let content: string;
    try {
      content = fs.readFileSync(filePath, 'utf8');
    } catch {
      process.exit(0);
      return; // unreachable，讓 TS 知道 content 已賦值
    }

    // STEP 06: 擷取所有 h2 heading
    const headings = content.match(/^## .+$/gm) || [];
    if (headings.length === 0) {
      console.log(`\n⚠️  Spec 驗證: ${fileName} 沒有任何 ## heading，可能是空骨架`);
      process.exit(0);
    }

    // STEP 07: 檢查必要 section
    const headingText = headings.join(' ');
    const missing: string[] = [];

    const hasOverview = OVERVIEW_PATTERNS.some(p => headingText.includes(p));
    if (!hasOverview) {
      missing.push(`規模/概述 (${OVERVIEW_PATTERNS.join(' 或 ')})`);
    }

    const hasQuality = QUALITY_PATTERNS.some(p => headingText.includes(p));
    if (!hasQuality) {
      missing.push(`品質/架構觀察 (${QUALITY_PATTERNS.join(' 或 ')})`);
    }

    // STEP 08: 輸出結果
    if (missing.length > 0) {
      let msg = `\n⚠️  Spec 驗證: ${fileName} 缺少以下 section:\n`;
      for (const m of missing) {
        msg += `   - ${m}\n`;
      }
      msg += `   現有 headings: ${headings.map(h => h.replace('## ', '')).join(', ')}`;
      console.log(msg);
    }
  } catch {
    // 靜默失敗
    process.exit(0);
  }
});
