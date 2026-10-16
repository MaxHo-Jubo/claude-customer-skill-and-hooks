/**
 * shell-text 的 maskQuotedText 測試：遮罩後長度不變，引號內文字與 heredoc 本體被蓋掉，
 * 真正的指令結構（分隔符、git、旗標）原樣保留。
 */
import { describe, expect, test } from 'bun:test';
import { maskQuotedText } from './shell-text';

describe('maskQuotedText', () => {
  test('任何輸入長度都不變（位置可對回原字串）', () => {
    for (const c of ['git commit -m "a b"', "echo 'x'", "cat <<'E'\nbody\nE\ngit status", 'a <<< "b" && c', '']) {
      expect(maskQuotedText(c).length).toBe(c.length);
    }
  });

  test('雙引號與單引號內容被蓋掉，引號本身與引號外保留', () => {
    expect(maskQuotedText('git commit -m "fix && git commit"')).toBe('git commit -m "' + '_'.repeat(17) + '"');
    expect(maskQuotedText("echo 'a; b'")).toBe("echo '____'");
  });

  test('雙引號內的跳脫引號不結束字串', () => {
    expect(maskQuotedText('echo "a\\"b" && git commit')).toBe('echo "____" && git commit');
  });

  test('heredoc 本體連同結尾分隔字被蓋掉，起始標記行與之後的指令保留', () => {
    expect(maskQuotedText("python3 - <<'E'\nx && git commit\nE\ngit status")).toBe(
      // 本體、本體與結尾分隔字之間的換行、結尾分隔字，全部遮成同一串（長度 = 15 + 1 + 1）；起始標記行之後的換行與其後指令保留
      "python3 - <<'E'\n" + '_'.repeat('x && git commit'.length + 2) + '\ngit status',
    );
  });

  test('結尾分隔字必須獨占一行：本體中以分隔字開頭的行不會提早結束', () => {
    /** 分隔字是 E，本體第二行以 E 開頭但不是獨占一行 */
    const masked = maskQuotedText('cat <<E\nline\nEXTRA && git commit\nE\ngit push');
    expect(masked.endsWith('\ngit push')).toBe(true);
    expect(masked).not.toContain('git commit');
  });

  test('here-string（<<<）不是 heredoc：其後的引號照一般規則遮罩，後面的指令保留', () => {
    expect(maskQuotedText('cat <<< "hello" && git commit')).toBe('cat <<< "_____" && git commit');
  });

  test('一行宣告多個 heredoc：依序吃掉各自的本體', () => {
    /** 兩個 heredoc 的本體都含 git commit 字樣 */
    const masked = maskQuotedText("cat <<A <<B\nx git commit\nA\ny git commit\nB\ngit status");
    expect(masked).not.toContain('git commit');
    expect(masked.endsWith('git status')).toBe(true);
  });

  test('heredoc 沒有結尾分隔字：本體蓋到字串結尾（不拋錯、不無窮迴圈）', () => {
    expect(maskQuotedText("cat <<E\ngit commit")).toBe('cat <<E\n' + '_'.repeat('git commit'.length));
  });
});
