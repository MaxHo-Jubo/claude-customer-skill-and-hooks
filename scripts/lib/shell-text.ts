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

/** 遮罩用的填充字元：不是空白、也不是任何 shell 分隔符，遮罩後的文字不會被當成指令或旗標 */
const MASK_CHAR = '_';

/** heredoc 起始標記（`<<EOF`、`<<-'EOF'`、`<<"EOF"`），不含 here-string 的 `<<<` */
const HEREDOC_START = /^<<-?\s*(['"]?)(\w+)\1/;

/**
 * 把引號內文字與 heredoc 本體換成等長的填充字元，**保留原字串長度與引號、heredoc 標記本身**。
 * 與 stripQuotedText 的差別：長度不變，所以在遮罩後的字串上找到的位置可以對回原字串取值
 * （例如在遮罩字串上定位真正的 `git -C`，再從原字串讀出被引號包住的路徑）。
 * 用途：判斷「這個 git commit／git -C 是真的指令，還是出現在 commit message、heredoc、echo 的引數裡的文字」。
 * 單趟掃描、依序處理：單引號（內容全字面）、雙引號（反斜線跳脫）、heredoc（標記所在行結束後，
 * 到獨占一行的結尾分隔字為止，整段是文字）。引號與 heredoc 互相巢狀時以先出現者為準。
 * @param command Bash 指令字串
 * @returns 與輸入等長的字串，引號內與 heredoc 本體以 '_' 取代
 */
export function maskQuotedText(command: string): string {
  // STEP 01: 初始化掃描狀態
  /** 輸出片段（逐字元累加後 join，避免字串重複複製） */
  const out: string[] = [];
  /** 目前所處的引號：null 表示一般文字 */
  let quote: "'" | '"' | null = null;
  /** 已讀到起始標記、等下一個換行後才開始的 heredoc 結尾分隔字（依出現順序） */
  const pending: string[] = [];
  /** 目前掃描位置 */
  let i = 0;

  // STEP 02: 逐字元掃描
  while (i < command.length) {
    /** 目前字元 */
    const c = command[i];

    // STEP 02.01: 引號內——內容遮罩，遇到對應的結尾引號回到一般文字
    if (quote !== null) {
      if (quote === '"' && c === '\\' && i + 1 < command.length) {
        out.push(MASK_CHAR, MASK_CHAR);
        i += 2;
        continue;
      }
      if (c === quote) {
        quote = null;
        out.push(c);
      } else {
        out.push(MASK_CHAR);
      }
      i += 1;
      continue;
    }

    // STEP 02.02: 一般文字——反斜線跳脫、開引號、heredoc 起始標記、換行後接 heredoc 本體
    if (c === '\\' && i + 1 < command.length) {
      out.push(c, command[i + 1]);
      i += 2;
    } else if (c === "'" || c === '"') {
      quote = c;
      out.push(c);
      i += 1;
    } else if (command.startsWith('<<<', i)) {
      // here-string：`<<<` 後面是普通字串（引號照一般規則遮罩），不是 heredoc；三個字元一起吃掉，
      // 避免後兩個 `<<` 被誤當成 heredoc 起始標記
      out.push('<<<');
      i += 3;
    } else if (c === '<' && command.startsWith('<<', i)) {
      /** heredoc 起始標記的比對結果 */
      const m = HEREDOC_START.exec(command.slice(i));
      if (m) {
        pending.push(m[2]);
        out.push(m[0]);
        i += m[0].length;
      } else {
        out.push(c);
        i += 1;
      }
    } else if (c === '\n' && pending.length > 0) {
      out.push(c);
      i += 1;
      // STEP 02.02.01: 依序吃掉每個 heredoc 本體，直到獨占一行的結尾分隔字（含該行）
      for (const delim of pending) {
        while (i < command.length) {
          /** 本行結束位置（換行字元的索引；沒有換行為字串結尾） */
          const eol = command.indexOf('\n', i);
          /** 本行範圍的結束（不含換行） */
          const end = eol === -1 ? command.length : eol;
          /** 本行文字 */
          const line = command.slice(i, end);
          out.push(MASK_CHAR.repeat(line.length));
          i = end;
          if (line.trim() === delim) {
            break;
          }
          if (eol !== -1) {
            out.push(MASK_CHAR);
            i += 1;
          }
        }
      }
      pending.length = 0;
    } else {
      out.push(c);
      i += 1;
    }
  }
  return out.join('');
}
