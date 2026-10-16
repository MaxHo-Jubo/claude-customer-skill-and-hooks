/**
 * Bash 指令字串的文字前處理，供各 PreToolUse guard 共用。
 * 原本是 hooks/credential-commit-guard.ts 的私有函式；sed-inplace-guard 需要同一份行為，
 * 依「同一概念出現在 2 個以上呼叫點就抽共用」抽到這裡，兩支 guard 不各自維護一份。
 */

/**
 * 去除引號內文字與 heredoc 內容，避免 commit message、grep 樣式等文字裡的 `;`、`&&`、`-a`、`sed -i`
 * 被當成真正的指令與旗標。
 * @param command Bash 指令字串
 * @returns 去除後的字串（引號內文字以空引號取代）
 */
export function stripQuotedText(command: string): string {
  // STEP 01: 先去除 heredoc 內容（含結尾分隔字）——要早於引號處理，避免 heredoc 內的引號干擾配對
  // STEP 02: 雙引號內文字換成空雙引號（保留跳脫字元的配對）
  // STEP 03: 單引號內文字換成空單引號
  return command
    .replace(/<<-?\s*['"]?(\w+)['"]?[\s\S]*?\n\s*\1\b/g, ' ')
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'[^']*'/g, "''");
}
