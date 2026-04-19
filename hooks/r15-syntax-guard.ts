#!/usr/bin/env bun
/**
 * PreToolUse hook：擋下 luna_web react_15 專案內使用 optional chaining (?.) 或 nullish coalescing (??)。
 *
 * Why: react_15 用 babel 6 + preset-es2015/stage-0，不含 ES2020 語法 plugin。
 * 寫進去會在 build 時噴 SyntaxError，比執行期 review 早攔下。
 *
 * 觸發條件：Write / Edit / MultiEdit 寫入路徑含 react_15/ 的 .js/.jsx/.ts/.tsx 檔案。
 * 行為：偵測到禁用語法 → 回傳 deny decision，附上正確寫法範例。
 */

let input = '';
process.stdin.setEncoding('utf8');

const stdinTimeout = setTimeout(() => { process.exit(0); }, 2000);

process.stdin.on('data', (chunk: string) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);
    const tool: string = data.tool_name;

    // STEP 01: 只處理寫入類 tool
    if (tool !== 'Write' && tool !== 'Edit' && tool !== 'MultiEdit') {
      process.exit(0);
    }

    // STEP 02: 確認是 react_15/ 路徑下的 JS/TS 檔
    const filePath: string = data.tool_input?.file_path || '';
    const normalizedPath = filePath.replace(/\\/g, '/');
    if (!normalizedPath.includes('/react_15/')) {
      process.exit(0);
    }
    if (!/\.(jsx?|tsx?)$/.test(normalizedPath)) {
      process.exit(0);
    }

    // STEP 03: 蒐集本次寫入的內容片段
    const fragments: string[] = [];
    if (tool === 'Write') {
      fragments.push(data.tool_input?.content || '');
    } else if (tool === 'Edit') {
      fragments.push(data.tool_input?.new_string || '');
    } else if (tool === 'MultiEdit') {
      const edits: Array<{ new_string?: string }> = data.tool_input?.edits || [];
      for (const e of edits) {
        fragments.push(e.new_string || '');
      }
    }

    // STEP 04: 偵測禁用語法
    // STEP 04.01: 移除字串、template literal、註解，避免誤判
    const violations: string[] = [];
    for (const raw of fragments) {
      const stripped = stripStringsAndComments(raw);
      // STEP 04.02: optional chaining：?. 但排除 ?? 後面跟著的合法情境（已被 stripped 處理）
      if (/\?\./.test(stripped)) {
        violations.push('optional chaining (?.)');
      }
      // STEP 04.03: nullish coalescing：?? 但要排除 React JSX 屬性的 ?? 不會出現在屬性值裸寫
      if (/\?\?/.test(stripped)) {
        violations.push('nullish coalescing (??)');
      }
    }

    // STEP 05: 沒違規 → 放行
    if (violations.length === 0) {
      process.exit(0);
    }

    // STEP 06: 違規 → 回傳 deny decision
    const unique = Array.from(new Set(violations));
    const reason = [
      `🚫 R15 不支援 ${unique.join(' / ')}`,
      '',
      'react_15/ 用 babel 6 + preset-es2015/stage-0，不含 ES2020 plugin，build 會炸。',
      '',
      '正確寫法：',
      '  // ❌ x?.length > 0',
      '  // ✅ x && x.length > 0',
      '  // ❌ name ?? "預設"',
      '  // ✅ name != null ? name : "預設"',
      '',
      '若該檔在 react_18/ 路徑下，請確認 file_path 是否寫錯。',
    ].join('\n');

    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reason,
      },
    }));
    process.exit(0);
  } catch {
    process.exit(0);
  }
});

/**
 * 移除字串字面值、template literal、單行/多行註解，避免註解或字串內的 ?. ?? 被誤判。
 * @param src 原始程式碼片段
 * @returns 已清除字串與註解的版本（保留長度結構不重要，只需供 regex 偵測）
 */
function stripStringsAndComments(src: string): string {
  let out = src;
  // 多行註解
  out = out.replace(/\/\*[\s\S]*?\*\//g, '');
  // 單行註解
  out = out.replace(/\/\/[^\n]*/g, '');
  // 字串字面值（雙引號 / 單引號 / template literal）— 簡化處理，不解析 escape
  out = out.replace(/"(?:[^"\\]|\\.)*"/g, '""');
  out = out.replace(/'(?:[^'\\]|\\.)*'/g, "''");
  out = out.replace(/`(?:[^`\\]|\\.)*`/g, '``');
  return out;
}
