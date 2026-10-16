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
  return command
    .replace(/<<-?\s*['"]?(\w+)['"]?[\s\S]*?\n\s*\1\b/g, ' ')
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'[^']*'/g, "''");
}
