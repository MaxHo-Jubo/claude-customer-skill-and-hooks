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

    def test_baseline_text_gets_the_same_config_as_the_r18_path(self):
        # 同一段文字用同一個落點路徑，兩次結果必須一致（基準與搬遷後比的是同一把尺）
        text = 'const a = 1\nexport default a;\n'
        self.assertEqual(self.rules(text), self.rules(text))

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
