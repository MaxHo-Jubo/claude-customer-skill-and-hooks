"""helpers/eslint_gate.py 的測試。

起因（2026-10-23，CUP-225 `caselist-modals`）：剩下 76 個 entry 的 283 個 R15 檔，281 個檔在 R18 的 eslint 設定下有 error，
舊規則（有 error 就 blocked、又不准 eslint-disable）下 runner 幾乎每個 page entry 都會停住；整檔 eslint-disable 又會把
eslint 唯一的用處（抓翻譯新引入的錯）一起關掉。閘門改成「只容忍 R15 原檔本來就有的違規」。

單元測試用注入的假 lint 函式（不依賴 eslint）驗證判定邏輯、檔頭寫入與重跑的冪等、全有或全無、結束碼；
最後一組整合測試用真的 eslint（找不到 react_18 的 node_modules 就略過），確認 parse error／no-undef／壞 import
真的會被抓到、被忽略的檔案不會被當成「0 error」。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 120; exec @ARGV' python3 -B -m unittest helpers.tests.test_eslint_gate -v
"""

import glob
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)

import eslint_gate as gate  # noqa: E402

SCRIPT = os.path.join(HELPERS_DIR, 'eslint_gate.py')


def msg(rule, line=1, severity=2, message='x'):
    """組一筆 eslint 訊息。"""
    return {'ruleId': rule, 'severity': severity, 'line': line, 'message': message}


class FakeLint(object):
    """假 lint：依 (文字內容) 回傳預先指定的訊息，並記錄每次被呼叫時收到的文字與檔名。"""

    def __init__(self, by_text=None, default=None):
        self.by_text = by_text or {}
        self.default = default or []
        self.calls = []

    def __call__(self, text, filename):
        self.calls.append((text, filename))
        return self.by_text.get(text, self.default)


class CountErrorsTest(unittest.TestCase):
    def test_only_severity_2_is_counted(self):
        counts = gate.count_errors([msg('semi'), msg('semi'), msg('no-console', severity=1)])
        self.assertEqual(counts, {'semi': 2})

    def test_parse_error_key_is_none(self):
        self.assertEqual(gate.count_errors([msg(None)]), {None: 1})


class EvaluateTest(unittest.TestCase):
    def test_same_counts_as_baseline_passes_and_lists_rules_sorted(self):
        violations, disable = gate.evaluate({'semi': 3, 'arrow-parens': 2}, {'semi': 3, 'arrow-parens': 2})
        self.assertEqual(violations, [])
        self.assertEqual(disable, ['arrow-parens', 'semi'])

    def test_fewer_than_baseline_passes(self):
        violations, disable = gate.evaluate({'semi': 3}, {'semi': 1})
        self.assertEqual(violations, [])
        self.assertEqual(disable, ['semi'])

    def test_more_than_baseline_is_a_violation_with_both_numbers(self):
        violations, _ = gate.evaluate({'semi': 3}, {'semi': 4})
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][:3], ('semi', 4, 3))

    def test_rule_absent_in_baseline_is_a_violation(self):
        violations, _ = gate.evaluate({}, {'no-undef': 1})
        self.assertEqual(violations[0][:3], ('no-undef', 1, 0))

    def test_unresolved_import_must_be_zero_even_if_baseline_has_it(self):
        violations, _ = gate.evaluate({'import/no-unresolved': 5}, {'import/no-unresolved': 1})
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][3], '必須為 0')

    def test_parse_error_must_be_zero_even_if_baseline_has_it(self):
        violations, _ = gate.evaluate({None: 1}, {None: 1})
        self.assertEqual(len(violations), 1)

    def test_path_dependent_import_rules_are_allowed_without_baseline(self):
        violations, disable = gate.evaluate({}, {'import/no-relative-packages': 15, 'import/extensions': 3})
        self.assertEqual(violations, [])
        self.assertEqual(disable, ['import/extensions', 'import/no-relative-packages'])

    def test_other_import_rules_follow_the_baseline_rule(self):
        violations, _ = gate.evaluate({}, {'import/no-cycle': 1})
        self.assertEqual(len(violations), 1)

    def test_no_errors_means_nothing_to_disable(self):
        self.assertEqual(gate.evaluate({'semi': 2}, {}), ([], []))

    def test_parse_error_is_never_listed_as_a_rule_to_disable(self):
        _, disable = gate.evaluate({}, {None: 1, 'semi': 1})
        self.assertEqual(disable, ['semi'])


class HeaderTest(unittest.TestCase):
    def test_build_then_strip_roundtrips(self):
        body = '/*\n * FeaturePath: x\n */\nimport a from "a";\n'
        header = gate.build_header(['arrow-parens', 'semi'])
        self.assertEqual(gate.strip_header(header + body), body)

    def test_strip_without_header_is_identity(self):
        body = '/* eslint-disable no-undef */\nconst a = 1;\n'
        self.assertEqual(gate.strip_header(body), body)

    def test_header_lists_one_rule_per_line(self):
        header = gate.build_header(['a', 'b'])
        self.assertEqual(header.split('\n')[1:5], ['/* eslint-disable', '  a,', '  b', '*/'])

    def test_unterminated_header_is_an_error(self):
        with self.assertRaises(gate.GateError):
            gate.strip_header(gate.HEADER_MARK + 'x\n/* eslint-disable\n  a\n')

    def test_hand_written_disable_is_not_stripped(self):
        text = '/* eslint-disable */\nx\n'
        self.assertEqual(gate.strip_header(text), text)

    def test_header_does_not_claim_every_violation_is_from_r15(self):
        # A5：閘門只比規則數量，無法證明逐筆違規來自 R15，檔頭不可宣稱「違規是 R15 既有寫法」
        header = gate.build_header(['semi'])
        self.assertNotIn('是 R15 既有寫法', header)
        self.assertIn('基準', header.split('\n')[0])

    def test_header_marks_path_dependent_rules_as_exempt_without_baseline(self):
        # A5：路徑相關規則是直接放行、沒有基準比對，檔頭要點名這些規則並說明
        lines = gate.build_header(['import/extensions', 'semi']).split('\n')
        note = [line for line in lines if line.startswith('//') and 'import/extensions' in line]
        self.assertEqual(len(note), 1)
        self.assertIn('沒有基準', note[0])
        self.assertNotIn('semi', note[0])

    def test_header_has_no_path_note_when_no_path_dependent_rule(self):
        header = gate.build_header(['semi'])
        self.assertEqual([line for line in header.split('\n') if line.startswith('//')], header.split('\n')[:1])

    def test_header_with_path_note_still_roundtrips(self):
        body = 'const a = 1;\n'
        header = gate.build_header(['import/extensions', 'semi'])
        self.assertEqual(gate.strip_header(header + body), body)


class DirectiveTest(unittest.TestCase):
    """A4：手寫的 eslint 停用／啟用指令偵測。"""

    def test_finds_block_line_and_next_line_forms_with_line_numbers(self):
        text = '/* eslint-disable */\nx\n// eslint-disable-next-line no-undef\ny // eslint-disable-line semi\n/* eslint-enable */\n'
        self.assertEqual(gate.find_directive_lines(text), [1, 3, 4, 5])

    def test_plain_comments_and_code_are_not_directives(self):
        self.assertEqual(gate.find_directive_lines('// 說明 eslint 的用法\nconst a = 1;\n'), [])

    def test_directive_inside_script_header_is_removed_by_strip_header_first(self):
        text = gate.build_header(['semi']) + 'const a = 1;\n'
        self.assertEqual(gate.find_directive_lines(gate.strip_header(text)), [])


# 指令偵測的對抗性案例：(案例名, 原文, 預期的指令行號清單)。
# 設計原則：偵測只是「禁止手寫停用」的政策檢查（eslint 本身已用 --no-inline-config 讓檔內指令失效），
# 漏報的代價小、誤報（把字串當指令而擋掉正確遷移）的代價大，所以無法判定時偏向「不計入」。
DIRECTIVE_CASES = [
    # --- 字串／模板字串／正規表示式內的文字：不是註解，不計入 ---
    ('codex 重現：雙引號字串內的行註解指令', 'const example = "// eslint-disable-next-line no-undef";\n', []),
    ('單引號字串內的行註解指令', "const example = '// eslint-disable-next-line no-undef';\n", []),
    ('單行模板字串內的指令', 'const example = `// eslint-disable-next-line no-undef`;\n', []),
    ('多行模板字串第二行的指令', 'const example = `first\n// eslint-disable-next-line no-undef\nthird`;\n', []),
    ('雙引號字串內的區塊註解指令', 'const example = "/* eslint-disable */";\n', []),
    ('單引號字串內的區塊註解指令', "const example = '/* eslint-disable no-undef */';\n", []),
    ('模板字串內的區塊註解指令', 'const example = `/* eslint-disable */`;\n', []),
    ('字串內有跳脫的雙引號，後面仍在字串內', 'const s = "a\\" // eslint-disable x";\n', []),
    ('字串內有跳脫的單引號，後面仍在字串內', "const s = 'it\\'s // eslint-disable x';\n", []),
    ('模板字串內有跳脫的反引號，後面仍在字串內', 'const s = `a \\` // eslint-disable x`;\n', []),
    ('正規表示式字面值內的跳脫斜線與指令文字', 'const r = /a\\/\\/ eslint-disable x/;\n', []),
    ('正規表示式字元集合內的雙斜線', 'const r = /[//]/;\n', []),
    ('模板字串運算式內的字串含雙斜線', 'const t = `a ${ "// eslint-disable x" } b`;\n', []),
    ('模板字串運算式內再巢狀模板字串', 'const t = `a ${ `// eslint-disable x` } b`;\n', []),
    ('模板字串運算式內有物件字面值的大括號，其後的字串仍在模板內', 'const t = `${ { a: 1 }.a } // eslint-disable x`;\n', []),
    ('運算式內的字串含 // 且後面還有文字', 'const t = `${ "//x" } // eslint-disable x`;\n', []),
    # --- 不在註解開頭的文字：不是指令 ---
    ('行註解中途提到區塊註解指令', '// see /* eslint-disable */ docs\n', []),
    ('區塊註解第二行才出現指令文字', '/* header\n eslint-disable */\n', []),
    ('相似但不是指令的名稱', '// eslint-disabled\n// eslint-disable-foo\n// eslint-enables\n', []),
    # --- 真的註解指令：必須計入 ---
    ('行註解指令', '// eslint-disable-line no-undef\n', [1]),
    ('行註解指令前面沒有空白', '//eslint-disable-line\n', [1]),
    ('區塊註解指令', '/* eslint-disable */\n', [1]),
    ('區塊註解 enable', 'x();\n/* eslint-enable */\n', [2]),
    ('程式碼後面接行尾指令', 'foo(); // eslint-disable-line no-undef\n', [1]),
    ('多行區塊註解開頭換行後才是指令', 'a();\n/*\n  eslint-disable\n  no-undef\n*/\nb();\n', [2]),
    ('字串含 // 之後同一行真有註解', 'const u = "http://x"; // eslint-disable-line no-undef\n', [1]),
    ('單引號字串含 // 之後同一行真有區塊註解', "const u = 'http://x'; /* eslint-disable */\n", [1]),
    ('模板字串結束後同一行有註解', 'const t = `a${1}b`; // eslint-disable-line\n', [1]),
    ('運算式內有大括號的模板字串後同一行有註解', 'const t = `${ { a: 1 }.a }`; // eslint-disable-line\n', [1]),
    ('模板字串運算式內的真區塊註解', 'const t = `${ /* eslint-disable */ 1 }`;\n', [1]),
    ('正規表示式含 // 之後同一行真有註解', 'const r = /[//]/; // eslint-disable-line\n', [1]),
    ('return 後的正規表示式含雙引號，之後真有註解', 'function f(s) {\n  return /"/.test(s); // eslint-disable-line\n}\n', [2]),
    ('除法之後真有註解', 'const q = a / b / c; // eslint-disable-line\n', [1]),
    ('後置遞增之後的除法，之後真有註解', 'const q = a++ / 2; // eslint-disable-line\n', [1]),
    ('行註解內有單引號，下一行的指令仍要計入', "// it's here\n// eslint-disable-line\n", [2]),
    ('區塊註解內有反引號與引號，下一行的指令仍要計入', "/* it's ` */\n// eslint-disable-next-line x\n", [2]),
    ('未結束的單引號字串在行尾結束，下一行的指令仍要計入', "const a = 'oops\n// eslint-disable-line\n", [2]),
    ('同一份文字內字串不計、真註解計入並回報正確行號', 'const a = "// eslint-disable x";\n\n/* eslint-disable */\nconst b = `x`;\n// eslint-enable\n', [3, 5]),
    # --- JSX ---
    ('JSX 內的區塊註解指令', 'const a = <div>{/* eslint-disable */}</div>;\n', [1]),
    ('JSX 內 next-line 指令且不吃掉後面的運算式', 'const a = (\n  <div>\n    {/* eslint-disable-next-line no-undef */}\n    {foo}\n  </div>\n);\n', [3]),
    ('JSX 閉合標籤的斜線不會吞掉同一行後面的註解', 'const a = <a>x</a>; // eslint-disable-line\n', [1]),
    ('正規表示式字元集合內的斜線之後還有雙引號，同一行真有註解', 'const r = /[/]"/; // eslint-disable-line\n', [1]),
    ('模板字串內跳脫反引號之後的運算式字串含指令文字', 'const s = `a \\` ${ "// eslint-disable x" } b`;\n', []),
    ('JSX 閉合標籤的斜線不會吞掉後面行的註解', 'const a = <a>x</a>;\n// eslint-disable-line\n', [2]),
    ('JSX 屬性字串內的指令文字', 'const a = <div title="// eslint-disable x" />;\n', []),
    # --- `/` 是除法還是正規表示式：`)`／`]` 之後是除法，不能把後面的 `//` 註解當成正規表示式吞掉（漏報方向，正是閘門要擋的） ---
    ('右小括號之後的除法，同一行真有註解', 'const q = (a) / 2; // eslint-disable-line\n', [1]),
    ('右中括號之後的除法，同一行真有註解', 'const q = [a][0] / 2; // eslint-disable-line\n', [1]),
    ('反斜線接換行不是合法的正規表示式，下一行的指令仍要計入', 'const r = /a\\\n// eslint-disable-line\n', [2]),
]


class DirectiveAdversarialTest(unittest.TestCase):
    """指令偵測只計入真正的 JS／TS 註解 token：字串、模板字串（含 ${} 巢狀）、正規表示式字面值內的文字不算。"""

    def test_each_adversarial_case_has_the_expected_lines(self):
        """逐案例比對行號清單；用 subTest 讓每個案例獨立回報。"""
        # STEP 01: 逐一餵案例，比對預期行號
        for name, text, expected in DIRECTIVE_CASES:
            with self.subTest(case=name):
                self.assertEqual(gate.find_directive_lines(text), expected)

    def test_case_table_covers_both_positive_and_negative_expectations(self):
        """防呆：案例表同時有「不計入」與「計入」兩類，避免整張表只剩單一方向而失去鑑別力。"""
        # STEP 01: 統計兩類案例數量
        positives = [c for c in DIRECTIVE_CASES if c[2]]
        negatives = [c for c in DIRECTIVE_CASES if not c[2]]
        self.assertGreaterEqual(len(positives), 8)
        self.assertGreaterEqual(len(negatives), 8)

    def test_function_does_not_mutate_or_raise_on_empty_and_unterminated_input(self):
        """空字串、沒結束的區塊註解／模板字串／運算式／正規表示式都不得拋錯；未結束的區塊註解仍是註解。"""
        # STEP 01: 各種殘缺輸入逐一確認不拋錯、結果符合預期
        cases = [
            ('', []),
            ('/* eslint-disable', [1]),
            ('const a = `abc ${ 1', []),
            ('const a = `abc', []),
            ('const r = /abc', []),
            ('const s = "abc', []),
            ('}}}\n// eslint-disable\n', [2]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(gate.find_directive_lines(text), expected)


class CheckPairsAndMainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = []

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def read(self, path):
        with open(path, encoding='utf-8') as f:
            return f.read()

    def run_main(self, lint, *pairs, write=False):
        argv = ['--repo', self.tmp.name]
        if write:
            argv.append('--write')
        for r15, r18 in pairs:
            argv += ['--pair', '%s=%s' % (r15, r18)]
        return gate.main(argv, lint_factory=lambda repo: lint, out=self.out.append)

    def test_baseline_is_linted_from_r15_text_and_after_from_r18_body(self):
        r15 = self.write('r15/a.js', 'R15 TEXT\n')
        r18 = self.write('r18/a.js', 'R18 TEXT\n')
        lint = FakeLint()
        self.run_main(lint, (r15, r18))
        self.assertEqual([c[0] for c in lint.calls], ['R15 TEXT\n', 'R18 TEXT\n'])
        self.assertTrue(all(c[1] == r18 for c in lint.calls))

    def test_existing_header_is_removed_before_linting(self):
        r15 = self.write('r15/a.js', 'R15 TEXT\n')
        r18 = self.write('r18/a.js', gate.build_header(['semi']) + 'BODY\n')
        lint = FakeLint(by_text={'R15 TEXT\n': [msg('semi')], 'BODY\n': [msg('semi')]})
        self.assertEqual(self.run_main(lint, (r15, r18)), 0)
        self.assertEqual(lint.calls[1][0], 'BODY\n')

    def test_without_write_nothing_is_changed(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        lint = FakeLint(default=[msg('semi')])
        self.assertEqual(self.run_main(lint, (r15, r18)), 0)
        self.assertEqual(self.read(r18), 'R18\n')

    def test_write_adds_header_with_only_triggered_rules(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        lint = FakeLint(default=[msg('semi'), msg('arrow-parens')])
        self.assertEqual(self.run_main(lint, (r15, r18), write=True), 0)
        self.assertEqual(self.read(r18), gate.build_header(['arrow-parens', 'semi']) + 'R18\n')

    def test_write_is_idempotent(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        lint = FakeLint(default=[msg('semi')])
        self.run_main(lint, (r15, r18), write=True)
        first = self.read(r18)
        self.run_main(lint, (r15, r18), write=True)
        self.assertEqual(self.read(r18), first)
        self.assertEqual(first.count(gate.HEADER_MARK), 1)

    def test_header_is_removed_when_no_rules_are_left(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', gate.build_header(['semi']) + 'BODY\n')
        lint = FakeLint()
        self.assertEqual(self.run_main(lint, (r15, r18), write=True), 0)
        self.assertEqual(self.read(r18), 'BODY\n')

    def test_new_error_beyond_baseline_fails_with_exit_1_and_writes_nothing(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        lint = FakeLint(by_text={'R15\n': [msg('semi')], 'R18\n': [msg('semi'), msg('no-undef', line=7)]})
        self.assertEqual(self.run_main(lint, (r15, r18), write=True), 1)
        self.assertEqual(self.read(r18), 'R18\n')
        self.assertTrue(any('no-undef' in line and '[7]' in line for line in self.out))

    def test_all_or_nothing_when_second_file_fails(self):
        r15a = self.write('r15/a.js', 'R15A\n')
        r18a = self.write('r18/a.js', 'R18A\n')
        r15b = self.write('r15/b.js', 'R15B\n')
        r18b = self.write('r18/b.js', 'R18B\n')
        lint = FakeLint(by_text={'R15A\n': [msg('semi')], 'R18A\n': [msg('semi')], 'R15B\n': [], 'R18B\n': [msg('no-undef')]})
        self.assertEqual(self.run_main(lint, (r15a, r18a), (r15b, r18b), write=True), 1)
        self.assertEqual(self.read(r18a), 'R18A\n')
        self.assertEqual(self.read(r18b), 'R18B\n')

    def test_hand_written_disable_added_in_r18_fails_with_exit_1_and_writes_nothing(self):
        # A4：R15 沒有、R18 手寫了 eslint-disable：即使 lint 沒回報任何錯，也要明確失敗並指出原因與行號
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', '/* eslint-disable */\nR18\n')
        self.assertEqual(self.run_main(FakeLint(), (r15, r18), write=True), 1)
        self.assertEqual(self.read(r18), '/* eslint-disable */\nR18\n')
        self.assertTrue(any(line.startswith('FAIL') and gate.DIRECTIVE_RULE in line and '[1]' in line for line in self.out), self.out)

    def test_hand_written_disable_after_script_header_still_fails(self):
        # A4：腳本檔頭被 strip_header 移除後，檔頭之後手寫的指令仍要被抓到
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', gate.build_header(['semi']) + '// eslint-disable-next-line no-undef\nR18\n')
        lint = FakeLint(default=[msg('semi')])
        self.assertEqual(self.run_main(lint, (r15, r18), write=True), 1)

    def test_directive_count_not_above_r15_is_not_a_new_failure(self):
        # A4：R15 原檔本來就有的指令照搬（執行時一律不吃 inline 設定，基準與搬遷後同一把尺），不算翻譯新引入
        r15 = self.write('r15/a.js', '// eslint-disable-next-line no-undef\nR15\n')
        r18 = self.write('r18/a.js', '// eslint-disable-next-line no-undef\nR18\n')
        self.assertEqual(self.run_main(FakeLint(), (r15, r18)), 0)

    def test_directive_text_inside_a_string_added_in_r18_is_not_a_violation(self):
        """codex 重現：R15 沒有、R18 新增含指令文字的合法字串，lint 零錯誤時不得被擋（也不得被改寫）。"""
        # STEP 01: R18 只新增字串字面值，沒有任何真的停用指令
        r15 = self.write('r15/a.js', 'const a = 1;\n')
        r18 = self.write('r18/a.js', 'const a = 1;\nconst example = "// eslint-disable-next-line no-undef";\n')
        # STEP 02: 結束碼 0、輸出沒有 FAIL
        self.assertEqual(self.run_main(FakeLint(), (r15, r18), write=True), 0)
        self.assertFalse(any(line.startswith('FAIL') for line in self.out), self.out)
        self.assertEqual(self.read(r18), 'const a = 1;\nconst example = "// eslint-disable-next-line no-undef";\n')

    def test_r15_directive_copied_over_with_a_string_mention_added_is_not_a_violation(self):
        """R15 本來就有 1 個真指令，R18 照搬並多一個含指令文字的字串：數量仍是 1 比 1，不得誤擋。"""
        # STEP 01: 兩邊各 1 個真指令，R18 另有 1 個字串內的指令文字
        r15 = self.write('r15/a.js', '// eslint-disable-next-line no-undef\nR15();\n')
        r18 = self.write('r18/a.js', '// eslint-disable-next-line no-undef\nR15();\nconst s = `/* eslint-disable */`;\n')
        # STEP 02: 不違規
        self.assertEqual(self.run_main(FakeLint(), (r15, r18)), 0)

    def test_real_directive_added_next_to_a_string_mention_is_still_a_violation(self):
        """R15 有 1 個真指令，R18 有 2 個真指令（另有字串內文字）：仍要列為違規，行號只含真指令。"""
        # STEP 01: R18 比 R15 多一個真指令
        r15 = self.write('r15/a.js', '// eslint-disable-next-line no-undef\nR15();\n')
        r18 = self.write('r18/a.js', '// eslint-disable-next-line no-undef\nconst s = "// eslint-disable";\n/* eslint-disable */\n')
        # STEP 02: 失敗、指出數量 2 比 1、行號 [1, 3]
        self.assertEqual(self.run_main(FakeLint(), (r15, r18)), 1)
        fails = [line for line in self.out if line.startswith('FAIL')]
        self.assertEqual(len(fails), 1, self.out)
        self.assertIn('搬遷後 2 個、R15 基準 1 個', fails[0])
        self.assertIn('[1, 3]', fails[0])

    def test_directive_violation_reason_says_over_r15_count_baseline(self):
        """違規原因文字與實際行為一致：按 R15 指令數量基準比較，超過才違規（不是「沒有基準比對」）。"""
        # STEP 01: 常數本身的措辭
        self.assertIn('超過 R15 指令數量基準', gate.DIRECTIVE_WHY)
        self.assertNotIn('沒有基準比對', gate.DIRECTIVE_WHY)
        # STEP 02: 實際輸出的 FAIL 行帶有同樣的原因
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', '/* eslint-disable */\nR18\n')
        self.run_main(FakeLint(), (r15, r18))
        self.assertTrue(any('超過 R15 指令數量基準' in line for line in self.out), self.out)

    def test_module_doc_does_not_claim_directives_have_no_baseline(self):
        """模組說明不得再說手寫指令「沒有基準比對」（實際有按數量比較），且要說明「不證明個別指令相同」。"""
        # STEP 01: 矛盾句已移除
        doc = gate.__doc__
        self.assertNotIn('手寫指令沒有基準比對', doc)
        self.assertNotIn('手寫的 eslint-disable 沒有基準比對', doc)
        # STEP 02: 新說明在位：按 R15 數量基準比較、不證明個別指令相同
        self.assertIn('R18 超過 R15 數量才列違規', doc)
        self.assertIn('不證明個別指令相同', doc)
        # STEP 03: 路徑相關規則「沒有基準比對」是另一件事，必須保留
        self.assertIn('路徑相關規則是直接放行、沒有基準比對', doc)

    def test_path_dependent_rule_without_baseline_passes_but_header_says_so(self):
        # A5：R15 基準為空、R18 新增 import/extensions 違規：維持放行，但檔頭不可宣稱它源自 R15
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        lint = FakeLint(by_text={'R15\n': [], 'R18\n': [msg('import/extensions')]})
        self.assertEqual(self.run_main(lint, (r15, r18), write=True), 0)
        written = self.read(r18)
        self.assertNotIn('是 R15 既有寫法', written)
        self.assertIn('沒有基準', written)

    def test_risk_rules_are_reported_when_disabled(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        lint = FakeLint(default=[msg('eqeqeq'), msg('semi')])
        self.assertEqual(self.run_main(lint, (r15, r18)), 0)
        risk = [line for line in self.out if line.startswith('RISK:')]
        self.assertEqual(len(risk), 1)
        self.assertIn('eqeqeq', risk[0])

    def test_non_js_files_are_skipped_and_counted(self):
        r15 = self.write('r15/a.scss', '.a{}\n')
        r18 = self.write('r18/a.scss', '.a{}\n')
        lint = FakeLint()
        self.assertEqual(self.run_main(lint, (r15, r18)), 0)
        self.assertEqual(lint.calls, [])
        self.assertIn('略過非 JS/TS 1 個', self.out[-1])

    def test_summary_line_is_printed_and_is_last_without_write(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        self.run_main(FakeLint(default=[msg('semi')]), (r15, r18))
        self.assertTrue(self.out[-1].startswith('eslint_gate: 檢查 1 個檔'), self.out[-1])

    def test_summary_line_is_printed_before_the_write_report(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        self.run_main(FakeLint(default=[msg('semi')]), (r15, r18), write=True)
        self.assertTrue(self.out[-2].startswith('eslint_gate: 檢查 1 個檔'), self.out[-2])
        self.assertEqual(self.out[-1], 'eslint_gate: 已寫入 1 個檔的檔頭')

    def test_missing_r18_file_is_exit_2(self):
        r15 = self.write('r15/a.js', 'R15\n')
        self.assertEqual(self.run_main(FakeLint(), (r15, os.path.join(self.tmp.name, 'nope.js'))), 2)
        self.assertTrue(self.out[-1].startswith('eslint_gate: 檢查 0 個檔'))

    def test_missing_r15_file_is_exit_2(self):
        r18 = self.write('r18/a.js', 'R18\n')
        self.assertEqual(self.run_main(FakeLint(), (os.path.join(self.tmp.name, 'nope.js'), r18)), 2)

    def test_lint_error_is_exit_2(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')

        def boom(text, filename):
            raise gate.GateError('eslint 本身出錯')

        self.assertEqual(self.run_main(boom, (r15, r18)), 2)

    def test_no_pair_is_exit_2(self):
        self.assertEqual(gate.main(['--repo', self.tmp.name], lint_factory=lambda r: FakeLint(), out=self.out.append), 2)

    def test_bad_pair_format_is_exit_2(self):
        self.assertEqual(gate.main(['--repo', self.tmp.name, '--pair', 'no-equals'], lint_factory=lambda r: FakeLint(), out=self.out.append), 2)

    def test_missing_eslint_binary_is_exit_2(self):
        r15 = self.write('r15/a.js', 'R15\n')
        r18 = self.write('r18/a.js', 'R18\n')
        argv = ['--repo', self.tmp.name, '--pair', '%s=%s' % (r15, r18)]
        self.assertEqual(gate.main(argv, out=self.out.append), 2)
        self.assertTrue(any('找不到 eslint' in line for line in self.out))

    def test_relative_paths_are_resolved_against_repo(self):
        self.write('r15/a.js', 'R15\n')
        self.write('r18/a.js', 'R18\n')
        lint = FakeLint()
        argv = ['--repo', self.tmp.name, '--pair', 'r15/a.js=r18/a.js']
        self.assertEqual(gate.main(argv, lint_factory=lambda r: lint, out=self.out.append), 0)
        self.assertEqual(lint.calls[0][1], os.path.join(os.path.abspath(self.tmp.name), 'r18/a.js'))


class EslintRunnerFailureTest(unittest.TestCase):
    """make_eslint_runner 的失敗路徑：以假的 subprocess 結果驗證，一律當環境錯誤，不能被當成「0 error」。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        bin_dir = os.path.join(self.tmp.name, 'frontend/react_18/node_modules/eslint/bin')
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, 'eslint.js'), 'w') as f:
            f.write('// fake\n')
        self.lint = gate.make_eslint_runner(self.tmp.name)

    def fake_run(self, returncode, stdout='', stderr=''):
        def run(*args, **kwargs):
            return subprocess.CompletedProcess(args, returncode, stdout, stderr)
        return run

    def call(self, returncode, stdout='', stderr=''):
        original = gate.subprocess.run
        gate.subprocess.run = self.fake_run(returncode, stdout, stderr)
        try:
            return self.lint('x', '/p/a.js')
        finally:
            gate.subprocess.run = original

    def test_ignored_file_message_is_an_error_not_zero_errors(self):
        out = '[{"messages": [{"ruleId": null, "severity": 1, "message": "File ignored because of a matching ignore pattern."}]}]'
        with self.assertRaises(gate.GateError) as ctx:
            self.call(0, out)
        self.assertIn('忽略', str(ctx.exception))

    def test_eslint_fatal_exit_code_2_is_an_error(self):
        with self.assertRaises(gate.GateError):
            self.call(2, '', 'boom')

    def test_exit_code_2_is_an_error_even_if_stdout_looks_like_valid_json(self):
        # 結束碼 2 = eslint 自己出錯；就算 stdout 剛好是合法的空結果，也不能當成「0 error」
        with self.assertRaises(gate.GateError) as ctx:
            self.call(2, '[{"messages": []}]', 'fatal')
        self.assertIn('結束碼 2', str(ctx.exception))

    def test_non_json_output_is_an_error(self):
        with self.assertRaises(gate.GateError):
            self.call(0, 'not json')

    def test_multiple_results_for_one_file_is_an_error(self):
        with self.assertRaises(gate.GateError):
            self.call(0, '[{"messages": []}, {"messages": []}]')

    def test_exit_code_1_with_errors_is_normal(self):
        out = '[{"messages": [{"ruleId": "semi", "severity": 2, "line": 3, "message": "m"}]}]'
        self.assertEqual(gate.count_errors(self.call(1, out)), {'semi': 1})

    def test_eslint_is_invoked_with_stdin_filename_and_no_ignore(self):
        seen = {}

        def run(cmd, **kwargs):
            seen['cmd'] = cmd
            seen['cwd'] = kwargs.get('cwd')
            seen['input'] = kwargs.get('input')
            return subprocess.CompletedProcess(cmd, 0, '[{"messages": []}]', '')

        original = gate.subprocess.run
        gate.subprocess.run = run
        try:
            self.lint('TEXT', '/p/a.js')
        finally:
            gate.subprocess.run = original
        self.assertIn('--stdin', seen['cmd'])
        self.assertIn('--no-ignore', seen['cmd'])
        self.assertIn('--no-inline-config', seen['cmd'])
        self.assertEqual(seen['cmd'][seen['cmd'].index('--stdin-filename') + 1], '/p/a.js')
        self.assertEqual(seen['input'], 'TEXT')
        self.assertTrue(seen['cwd'].endswith('frontend/react_18'))


def find_real_repo():
    """找得到 react_18 的 eslint 才跑整合測試：環境變數 ESLINT_GATE_REPO，或家目錄下 Documents/*/* 與 r18/* 兩種常見擺法（glob 比對，不寫死 repo 名稱與使用者路徑）。"""
    # 用 glob 找出含 react_18 eslint 的 repo 根目錄（依序：Documents 兩層、r18 一層）
    eslint_rel = 'frontend/react_18/node_modules/eslint/bin/eslint.js'
    home = os.path.expanduser('~')
    globbed = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(p))))))
               for pat in (os.path.join(home, 'Documents', '*', '*', eslint_rel), os.path.join(home, 'r18', '*', eslint_rel))
               for p in sorted(glob.glob(pat))]
    candidates = [os.environ.get('ESLINT_GATE_REPO')] + globbed
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, 'frontend/react_18/node_modules/eslint/bin/eslint.js')):
            return c
    return None


REAL_REPO = find_real_repo()


@unittest.skipUnless(REAL_REPO, '找不到 react_18 的 eslint，略過整合測試')
class RealEslintTest(unittest.TestCase):
    """用真的 eslint 驗證：已知答案會被抓到、被忽略的檔案不會被當成 0 error。"""

    def setUp(self):
        self.lint = gate.make_eslint_runner(REAL_REPO)
        self.path = os.path.join(REAL_REPO, 'frontend/react_18/src/pages/_gate_test_/x.js')

    def rules(self, text):
        return gate.count_errors(self.lint(text, self.path))

    def test_parse_error_is_reported_as_none(self):
        self.assertEqual(self.rules('const = ;\n').get(None), 1)

    def test_undefined_variable_is_reported(self):
        self.assertEqual(self.rules('export default function f() { return undefinedProbe(); }\n').get('no-undef'), 1)

    def test_unresolved_import_is_reported(self):
        self.assertEqual(self.rules("import a from './does-not-exist-anywhere';\nexport default a;\n").get('import/no-unresolved'), 1)

    def test_known_style_error_is_reported(self):
        self.assertGreaterEqual(self.rules("const a = 1\nexport default a;\n").get('semi', 0), 1)

    def test_clean_file_has_no_errors(self):
        self.assertEqual(self.rules("const a = 1;\n\nexport default a;\n"), {})

    def test_inline_disable_does_not_hide_errors_with_real_eslint(self):
        # A4：手寫 `/* eslint-disable */` 不可讓真 eslint 的 no-undef 消失（執行時必須不吃 inline 設定）
        text = '/* eslint-disable */\nexport default function f() { return undefinedProbe(); }\n'
        self.assertEqual(self.rules(text).get('no-undef'), 1)

    def run_check_pairs_recording(self, r15_text, r18_text):
        """C8 輔助：用真 eslint 走 check_pairs 的基準與搬遷後兩條路徑；回傳 (結果清單, 記錄的 lint 呼叫清單)。

        檔案內容以 mock 的 read_text 供應（不寫進真 repo）；落點路徑用 self.path（在 react_18 底下，吃得到 R18 設定）。
        """
        r15_path = '/virtual/r15/x.js'
        texts = {r15_path: r15_text, self.path: r18_text}
        calls = []

        def recording_lint(text, filename):
            calls.append((text, filename))
            return self.lint(text, filename)

        with mock.patch.object(gate, 'read_text', side_effect=lambda p: texts[p]):
            results, _ = gate.check_pairs([(r15_path, self.path)], recording_lint)
        return results, calls

    def test_check_pairs_lints_r15_baseline_at_the_r18_path_and_counts_known_violations(self):
        # C8：R15 基準與搬遷後各走一次 lint；已知樣本缺分號數量固定為 1（基準）與 2（搬遷後）
        r15_text = 'const a = 1\nexport default a;\n'
        r18_text = 'const a = 1\nconst b = 2\nexport default [a, b];\n'
        results, calls = self.run_check_pairs_recording(r15_text, r18_text)
        self.assertEqual(calls, [(r15_text, self.path), (r18_text, self.path)])
        self.assertEqual(results[0]['baseline'].get('semi'), 1)
        self.assertEqual(results[0]['after'].get('semi'), 2)
        self.assertEqual([v[:3] for v in results[0]['violations']], [('semi', 2, 1)])

    def test_check_pairs_baseline_is_not_empty_when_r15_text_has_violations(self):
        # C8：基準若永遠回空（例如 lint 或 count 壞掉），已知有違規的 R15 文字會讓這條紅
        results, _ = self.run_check_pairs_recording('const a = 1\nexport default a;\n', 'const a = 1;\n\nexport default a;\n')
        self.assertEqual(results[0]['baseline'].get('semi'), 1)
        self.assertEqual(results[0]['after'], {})
        self.assertEqual(results[0]['violations'], [])

    def test_check_pairs_catches_hand_written_disable_with_real_eslint(self):
        # A4：codex 重現輸入——R18 新增未定義變數、再手寫 `/* eslint-disable */`：no-undef 與指令兩項都要被列為違規
        r15_text = 'const a = 1;\n\nexport default a;\n'
        r18_text = '/* eslint-disable */\nconst a = 1;\n\nundefinedProbe();\nexport default a;\n'
        results, _ = self.run_check_pairs_recording(r15_text, r18_text)
        self.assertEqual(sorted(v[0] for v in results[0]['violations']), sorted(['no-undef', gate.DIRECTIVE_RULE]))
        self.assertEqual(results[0]['lines'][gate.DIRECTIVE_RULE], [1])

    def test_check_pairs_does_not_flag_directive_text_in_a_string_with_real_eslint(self):
        """codex 重現（真 eslint）：R18 新增含指令文字的字串、lint 零錯誤時，check_pairs 不得新增任何違規。"""
        # STEP 01: R18 比 R15 只多一個字串字面值（單引號，符合 R18 的 quotes 規則）
        r15_text = 'const a = 1;\n\nexport default a;\n'
        r18_text = "const a = 1;\nconst example = '// eslint-disable-next-line no-undef';\n\nexport default [a, example];\n"
        results, _ = self.run_check_pairs_recording(r15_text, r18_text)
        # STEP 02: 沒有任何違規、沒有指令行號
        self.assertEqual(results[0]['after'], {})
        self.assertEqual(results[0]['violations'], [])
        self.assertNotIn(gate.DIRECTIVE_RULE, results[0]['lines'])

    def test_translation_adding_an_error_is_detected_with_real_eslint(self):
        # 基準是乾淨的 R15 文字，搬遷後多了一個未定義變數：用真 eslint 的結果餵給 evaluate，必須恰好抓到 no-undef
        baseline = gate.count_errors(self.lint('const a = 1;\n\nexport default a;\n', self.path))
        after = gate.count_errors(self.lint('const a = 1;\nundefinedProbe();\nexport default a;\n', self.path))
        violations, _ = gate.evaluate(baseline, after)
        self.assertEqual([v[0] for v in violations], ['no-undef'])

    def test_inherited_style_errors_are_tolerated_with_real_eslint(self):
        # R15 原本就有的 semi 違規，搬遷後數量相同：不算違規，只列入要關的規則
        text = 'const a = 1\nexport default a;\n'
        counts = gate.count_errors(self.lint(text, self.path))
        violations, disable = gate.evaluate(counts, counts)
        self.assertEqual(violations, [])
        self.assertIn('semi', disable)


class CliSubprocessTest(unittest.TestCase):
    def test_no_args_is_exit_2(self):
        r = subprocess.run([sys.executable, '-B', SCRIPT], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_missing_repo_eslint_is_exit_2_and_prints_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, 'a.js')
            with open(a, 'w', encoding='utf-8') as f:
                f.write('x\n')
            r = subprocess.run([sys.executable, '-B', SCRIPT, '--repo', tmp, '--pair', '%s=%s' % (a, a)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn('eslint_gate: 檢查 0 個檔', r.stdout)


if __name__ == '__main__':
    unittest.main()
