"""helpers/scan_rem.py 的測試。

起因（2026-10-21，CUP-228）：用餐紀錄頁從 R15 遷到 R18 時，`style.scss` 與 `Datepicker.js` 的 `4rem` 原樣照搬，
R15 根字級 10px（40px）變成 R18 13px（52px），字體比活動紀錄頁大很多，建置與 build smoke 都綠燈。
測試用的「命中」樣本取自該事故的真實內容（R15 `caseMealRecord/style.scss`、`components/Datepicker.js`），
對照組取自修正後的寫法，確認掃描器對已知答案給得出對的結論（不是只會回 0）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 60; exec @ARGV' python3 -B -m unittest helpers.tests.test_scan_rem -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
# helpers 目錄（scan_rem.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)

import scan_rem  # noqa: E402

SCRIPT = os.path.join(HELPERS_DIR, 'scan_rem.py')

# R15 `caseMealRecord/style.scss` 的真實片段（CUP-228 事故來源）
R15_SCSS = """.header {
  height: 60px;
  > span {
    font-size: 4rem;
  }
}
.select-date {
  font-size: 4rem;
}
"""

# R15 `components/Datepicker.js` 的真實片段：行內 style 字串，只掃樣式檔會漏
R15_JS = """  RWDWebStyle = {
    width: '100%',
    fontSize: '4rem',
    padding: '2px 5px'
  }
"""

# 修正後的寫法：換成與活動紀錄頁相同的 1.2rem 前的 px 版本（或具名變數）
FIXED_SCSS = """.header {
  height: 30px;
  > span {
    font-size: 18px;
  }
}
"""


def write(tmpdir, name, content):
    """在 tmpdir 寫一個檔並回傳路徑。"""
    path = os.path.join(tmpdir, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def run_cli(*paths):
    """以子行程執行 scan_rem.py，回傳 (exit code, stdout, stderr)。"""
    proc = subprocess.run([sys.executable, '-B', SCRIPT, *paths], capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


class ScanFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_r15_scss_hits_with_line_numbers(self):
        hits = scan_rem.scan_file(write(self.tmp, 'style.scss', R15_SCSS))
        self.assertEqual([h[0] for h in hits], [4, 8])

    def test_js_inline_style_string_hits(self):
        hits = scan_rem.scan_file(write(self.tmp, 'Datepicker.js', R15_JS))
        self.assertEqual([h[0] for h in hits], [3])

    def test_px_version_is_clean(self):
        self.assertEqual(scan_rem.scan_file(write(self.tmp, 'style.scss', FIXED_SCSS)), [])

    def test_em_is_not_flagged(self):
        self.assertEqual(scan_rem.scan_file(write(self.tmp, 'a.scss', '.a { margin: 2em; font-size: 1.5em; }\n')), [])

    def test_decimal_values_hit(self):
        self.assertEqual(len(scan_rem.scan_file(write(self.tmp, 'a.css', '.a { width: calc(100% - 0.375rem); }\n'))), 1)

    def test_leading_dot_decimal_values_hit(self):
        """省略前導零的小數（`.5rem`、`-.5rem`）是合法 CSS 值，必須命中（codex A3）。"""
        # STEP 01: 每個樣本都是「單獨一行、預期恰好命中 1 行」的合法寫法
        samples = [
            '.a { margin: .5rem; }\n',
            '.a { margin: -.5rem; }\n',
            '.a { margin:.5rem; }\n',
            '.a { width: calc(1px + .5rem); }\n',
            '.a { width: calc(1px+.5rem); }\n',
            "  fontSize: '.5rem',\n",
            "  marginTop: '-.5rem',\n",
        ]
        for i, content in enumerate(samples):
            with self.subTest(content=content):
                hits = scan_rem.scan_file(write(self.tmp, f'lead{i}.scss', content))
                self.assertEqual(len(hits), 1)

    def test_malformed_or_embedded_numbers_are_not_flagged(self):
        """識別字夾帶與畸形數值不命中：這是既有邊界，新增小數分支後不得退化。"""
        # STEP 01: 每個樣本都不該命中
        samples = [
            'foo.5rem;\n',  # 識別字後接 `.5rem`（成員存取形式）
            'a.b.5rem;\n',
            'x3rem;\n',  # 識別字結尾是 rem
            '.a { margin: 1.2.3rem; }\n',  # 多個小數點
            '.a { margin: .5.5rem; }\n',  # 省略前導零但仍有第二個小數點
            '.a { margin: 1..5rem; }\n',
            '.a { margin: 1.rem; }\n',  # 小數點後沒有數字
            '.a { margin: .rem; }\n',  # 只有小數點
            '.a { margin: .5remx; }\n',  # rem 後緊接英數字
        ]
        for i, content in enumerate(samples):
            with self.subTest(content=content):
                self.assertEqual(scan_rem.scan_file(write(self.tmp, f'bad{i}.scss', content)), [])

    def test_identifier_ending_in_rem_is_not_flagged(self):
        self.assertEqual(scan_rem.scan_file(write(self.tmp, 'a.js', 'const x3rem = 1;\n')), [])

    def test_comments_are_ignored(self):
        content = (
            '/* 4rem 在 R15 是 40px */\n'
            '// font-size: 4rem;\n'
            '/*\n * 多行註解 3rem\n */\n'
            '.a { color: red; } // 原本是 2rem\n'
            '.b { color: red; } /* 1rem */\n'
        )
        self.assertEqual(scan_rem.scan_file(write(self.tmp, 'a.scss', content)), [])

    def test_line_after_multiline_comment_keeps_line_number(self):
        content = '/*\n * 說明\n */\n.a { font-size: 4rem; }\n'
        hits = scan_rem.scan_file(write(self.tmp, 'a.scss', content))
        self.assertEqual([h[0] for h in hits], [4])

    def test_rem_ok_marker_skips_the_line(self):
        content = '.a { font-size: 4rem; } /* rem-ok: 刻意與 R18 全站字級連動 */\n.b { font-size: 4rem; }\n'
        hits = scan_rem.scan_file(write(self.tmp, 'a.scss', content))
        self.assertEqual([h[0] for h in hits], [2])

    def test_url_with_double_slash_is_not_treated_as_comment(self):
        content = ".a { background: url(http://x/y.png); font-size: 4rem; }\n"
        self.assertEqual(len(scan_rem.scan_file(write(self.tmp, 'a.scss', content))), 1)


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_exit_1_and_prints_hits(self):
        path = write(self.tmp, 'style.scss', R15_SCSS)
        code, out, _ = run_cli(path)
        self.assertEqual(code, 1)
        self.assertIn(f'{path}:4: font-size: 4rem;', out)
        self.assertIn('掃描 1 個檔', out)
        self.assertIn('命中 2 行', out)

    def test_exit_0_when_clean_and_still_prints_summary(self):
        code, out, _ = run_cli(write(self.tmp, 'style.scss', FIXED_SCSS))
        self.assertEqual(code, 0)
        self.assertIn('掃描 1 個檔', out)

    def test_missing_file_is_exit_2_not_skipped(self):
        code, _, err = run_cli(os.path.join(self.tmp, 'nope.scss'))
        self.assertEqual(code, 2)
        self.assertIn('不存在', err)

    def test_no_args_is_exit_2(self):
        code, _, _ = run_cli()
        self.assertEqual(code, 2)

    def test_non_style_files_are_skipped_but_counted(self):
        md = write(self.tmp, 'notes.md', 'font-size: 4rem\n')
        code, out, _ = run_cli(md)
        self.assertEqual(code, 0)
        self.assertIn('掃描 0 個檔（略過 1 個', out)

    def test_hit_in_second_file_still_reported_after_clean_first_file(self):
        clean = write(self.tmp, 'a.scss', FIXED_SCSS)
        dirty = write(self.tmp, 'b.js', R15_JS)
        code, out, _ = run_cli(clean, dirty)
        self.assertEqual(code, 1)
        self.assertIn(f'{dirty}:3:', out)
        self.assertIn('掃描 2 個檔', out)


if __name__ == '__main__':
    unittest.main()
