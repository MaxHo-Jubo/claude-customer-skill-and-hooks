#!/usr/bin/env bun
import fs from 'fs';
import path from 'path';

/**
 * 驗證 spec markdown 檔案包含必要 section（settings.json PostToolUse 與 tool-reminders mod 共用）。
 *
 * 觸發條件: Write 或 Edit tool 修改了 spec/*.md 檔案
 * 輸出（兩種呼叫模式分工）:
 * - 預設（settings.json PostToolUse）: 缺少必要 section 時輸出 decision:block + exit 2，reason 以 blocking error 回報給 model（檔案已寫入）；空骨架不輸出
 * - `--warn-only`（~/.claude/mods/tool-reminders 呼叫）: 只輸出空骨架警告純文字，經 tool.call context 送給 model；不做 block
 * 分工原因: PostToolUse exit 0 的 plain stdout 只進 debug log，空骨架警告原本從未送達 model
 * 失敗語意（兩種模式相同）: 輸入不符契約、讀檔失敗、未預期例外 → stderr + exit 1，
 * 讓 hook-error-wrapper 記錄、mod 回報「結果未知」，不與「驗證通過」混為同一個 exit 0
 */

/** 是否為 mod 呼叫的警告模式（只輸出空骨架警告，不做 block） */
const WARN_ONLY = process.argv.includes('--warn-only');

/** stdin 逾時（毫秒）：呼叫端寫完 stdin 會關閉，超過即視為呼叫端異常 */
const STDIN_TIMEOUT_MS = 2000;

/**
 * 以 stderr 回報失敗並 exit 1。
 * @param message - 失敗原因
 * @returns never（直接結束行程）
 */
function fail(message: string): never {
  console.error(`spec-section-validator: ${message}`);
  process.exit(1);
}

/** 跳過驗證的檔案（導航/索引用途） */
const SKIP_FILES = ['index.md', 'file-mapping.json'];

/** 概述類 section（至少要有一個） */
const OVERVIEW_PATTERNS = ['規模', '概述'];

/** 品質類 section（至少要有一個） */
const QUALITY_PATTERNS = ['品質', '架構觀察'];

/** hook 的 stdin JSON 資料 */
let input = '';
process.stdin.setEncoding('utf8');

/** stdin 超時防呆：逾時未收到 EOF 即以失敗結束 */
const stdinTimeout = setTimeout(() => { fail(`stdin ${STDIN_TIMEOUT_MS}ms 內未收到 EOF`); }, STDIN_TIMEOUT_MS);

process.stdin.on('data', (chunk: string) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);
    const toolName: string = data.tool_name;

    // STEP 01: 只處理 Write 和 Edit（兩個呼叫端都只送這兩種，其他值是呼叫端的 bug）
    if (toolName !== 'Write' && toolName !== 'Edit') {
      fail(`tool_name 應為 Write 或 Edit，收到 ${JSON.stringify(toolName)}`);
    }

    // STEP 02: 取得檔案路徑
    const filePath: string = data.tool_input?.file_path || '';
    if (!filePath) {
      fail('stdin 缺少 tool_input.file_path');
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
    } catch (err) {
      // 工具成功寫入後才會被呼叫，讀不到代表權限、競態或路徑契約出錯
      fail(`讀取 ${filePath} 失敗：${(err as Error).message}`);
    }

    // STEP 06: 擷取所有 h2 heading
    const headings = content.match(/^## .+$/gm) || [];
    if (headings.length === 0) {
      if (WARN_ONLY) {
        console.log(`⚠️ Spec 驗證: ${fileName} 沒有任何 ## heading，可能是空骨架`);
      }
      process.exit(0);
    }

    // STEP 07: 警告模式不負責 block，有 heading 即結束
    if (WARN_ONLY) {
      process.exit(0);
    }

    // STEP 08: 檢查必要 section
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

    // STEP 09: 輸出結果
    if (missing.length > 0) {
      const existingHeadings = headings.map(h => h.replace('## ', '')).join(', ');
      const missingList = missing.map(m => `- ${m}`).join('\n');
      console.log(JSON.stringify({
        decision: 'block',
        reason: `Spec 驗證失敗: ${fileName} 缺少以下必要 section:\n${missingList}\n現有 headings: ${existingHeadings}\n請補齊後再寫入。`,
      }));
      process.exit(2);
    }
  } catch (err) {
    fail((err as Error).message);
  }
});
