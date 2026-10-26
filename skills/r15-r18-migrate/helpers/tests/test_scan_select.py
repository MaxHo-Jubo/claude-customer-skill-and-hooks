"""helpers/scan_select.py 的測試。

起因（2026-10-23，CUP-225 `caselist-modals`，PR #11400）：react-select v1→v5 有兩個省略 prop 時行為相反的靜默退化——
單選的清除鈕（v1 `clearable` 預設 true、v5 `isClearable` 預設 false）、scss 針對 v1 class 的規則在 v5 不命中。
建置、eslint、smoke 都綠燈，是 codex review 與人工讀 diff 才抓到。
「命中」樣本取自該事故的真實內容（R15 `CaseSettingModal.js` 的三個單選、`CaseFilterBar.scss` 的兩條規則），
「對照組」是修正後的寫法，確認掃描器對已知答案給得出對的結論（不是只會回 0）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 60; exec @ARGV' python3 -B -m unittest helpers.tests.test_scan_select -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)

import scan_select  # noqa: E402

SCRIPT = os.path.join(HELPERS_DIR, 'scan_select.py')

# R15 `CaseSettingModal.js` 的真實片段：單選沒寫 clearable（v1 預設可清除）
R15_SINGLE = """import Select from 'react-select';
<Select
  placeholder="選擇主責督導"
  options={this.getSupervisorOption()}
  closeOnSelect
  removeSelected
  value={supervisor}
  disabled={clearSupervisor}
  onChange={this.handleSupervisorSelect}
/>
"""

# 事故當時 R18 的寫法：照 §6.2 逐個翻譯 prop，漏掉 isClearable
R18_MISSING = """import Select from 'react-select';
<Select
  placeholder="選擇主責督導"
  options={this.getSupervisorOption()}
  closeMenuOnSelect
  value={supervisor}
  isDisabled={clearSupervisor}
  onChange={this.handleSupervisorSelect}
/>
"""

# 修正後
R18_FIXED = R18_MISSING.replace('  closeMenuOnSelect\n', '  closeMenuOnSelect\n  isClearable\n')

# R15 `CaseFilterBar.scss` 的真實片段（<TICKET> 多選限高）
R15_SCSS = """.case-filter-bar__select-wrapper {
  display: inline-block;
  // 多選下拉已選項目較多時改為自動換行
  .Select--multi .Select-control {
    max-height: 84px;
  }
  .Select-multi-value-wrapper {
    white-space: normal;
  }
}
"""


def pair(r15, r18):
    return scan_select.check_pair(r15, r18)


class SingleSelectClearableTest(unittest.TestCase):
    def test_incident_single_select_missing_isclearable_hits(self):
        hits, n = pair(R15_SINGLE, R18_MISSING)
        self.assertEqual(n, 1)
        self.assertEqual(len(hits), 1)
        self.assertIn('缺 isClearable', hits[0])

    def test_fixed_version_is_clean(self):
        hits, n = pair(R15_SINGLE, R18_FIXED)
        self.assertEqual((hits, n), ([], 1))

    def test_multi_does_not_need_isclearable(self):
        r15 = "import Select from 'react-select';\n<Select multi options={o} />\n"
        r18 = "import Select from 'react-select';\n<Select isMulti options={o} />\n"
        self.assertEqual(pair(r15, r18), ([], 1))

    def test_r15_clearable_false_and_r18_without_isclearable_is_clean(self):
        r15 = "import Select from 'react-select';\n<Select clearable={false} options={o} />\n"
        r18 = "import Select from 'react-select';\n<Select options={o} />\n"
        self.assertEqual(pair(r15, r18), ([], 1))

    def test_r15_clearable_false_but_r18_clearable_hits(self):
        r15 = "import Select from 'react-select';\n<Select clearable={false} options={o} />\n"
        r18 = "import Select from 'react-select';\n<Select isClearable options={o} />\n"
        hits, _ = pair(r15, r18)
        self.assertEqual(len(hits), 1)
        self.assertIn('卻可清除', hits[0])

    def test_r15_clearable_false_and_r18_isclearable_false_is_clean(self):
        r15 = "import Select from 'react-select';\n<Select clearable={false} options={o} />\n"
        r18 = "import Select from 'react-select';\n<Select isClearable={false} options={o} />\n"
        self.assertEqual(pair(r15, r18), ([], 1))

    def test_explicit_clearable_true_in_r15_needs_isclearable(self):
        r15 = "import Select from 'react-select';\n<Select clearable options={o} />\n"
        r18 = "import Select from 'react-select';\n<Select options={o} />\n"
        hits, _ = pair(r15, r18)
        self.assertEqual(len(hits), 1)

    def test_only_the_offending_element_is_reported_with_its_line_numbers(self):
        r15 = ("import Select from 'react-select';\n"
               "<Select multi options={a} />\n"
               "<Select options={b} />\n")
        r18 = ("import Select from 'react-select';\n"
               "<Select isMulti options={a} />\n"
               "<Select options={b} />\n")
        hits, n = pair(r15, r18)
        self.assertEqual(n, 2)
        self.assertEqual(len(hits), 1)
        self.assertIn('R15 第 3 行', hits[0])
        self.assertIn('R18 第 3 行', hits[0])


class ElementParsingTest(unittest.TestCase):
    def test_arrow_function_in_props_does_not_end_the_element_early(self):
        # 箭頭函式放在第一組大括號裡：`=>` 的 `>` 出現時大括號深度必須是 1，不是 0，否則元素會被提早截斷、後面的 isClearable 看不到
        r15 = ("import Select from 'react-select';\n"
               "<Select onChange={(x) => x > 1} options={o} />\n")
        r18 = ("import Select from 'react-select';\n"
               "<Select onChange={(x) => x > 1} options={o} isClearable />\n")
        self.assertEqual(pair(r15, r18), ([], 1))

    def test_props_after_an_arrow_function_stay_in_the_same_element(self):
        els = scan_select.elements("import S from 'react-select';\n<S onChange={(x) => x > 1} isClearable />\n<S multi />\n", 'S')
        self.assertEqual(len(els), 2)
        self.assertIn('isClearable', els[0][1])
        self.assertNotIn('multi', els[0][1])

    def test_greater_than_inside_string_does_not_end_the_element_early(self):
        els = scan_select.elements("import S from 'react-select';\n<S placeholder=\"a > b\" options={o} />\n", 'S')
        self.assertEqual(len(els), 1)
        self.assertIn('options', els[0][1])

    def test_custom_import_name_is_followed(self):
        r15 = "import ReactSelect from 'react-select';\n<ReactSelect options={o} />\n"
        r18 = "import ReactSelect from 'react-select';\n<ReactSelect options={o} />\n"
        hits, _ = pair(r15, r18)
        self.assertEqual(len(hits), 1)

    def test_similar_tag_names_are_not_counted(self):
        text = "import Select from 'react-select';\n<SelectAll /><Selector /><Select options={o} />\n"
        self.assertEqual(len(scan_select.elements(text, 'Select')), 1)

    def test_neither_file_uses_react_select_is_clean(self):
        self.assertEqual(pair("const a = 1;\n", "const a = 1;\n"), ([], 0))


class FailClosedTest(unittest.TestCase):
    def test_element_count_mismatch_hits(self):
        r15 = "import Select from 'react-select';\n<Select options={a} /><Select options={b} />\n"
        r18 = "import Select from 'react-select';\n<Select options={a} isClearable />\n"
        hits, n = pair(r15, r18)
        self.assertEqual(n, 0)
        self.assertIn('元素數不同', hits[0])

    def test_spread_props_in_r18_hits(self):
        r15 = "import Select from 'react-select';\n<Select options={a} />\n"
        r18 = "import Select from 'react-select';\n<Select {...props} />\n"
        hits, _ = pair(r15, r18)
        self.assertEqual(len(hits), 1)
        self.assertIn('展開 props', hits[0])

    def test_r18_no_longer_imports_react_select_hits(self):
        r15 = "import Select from 'react-select';\n<Select options={a} />\n"
        hits, _ = pair(r15, "import Foo from './foo';\n<Foo />\n")
        self.assertEqual(len(hits), 1)
        self.assertIn('R18 檔沒有', hits[0])


class ScssTest(unittest.TestCase):
    def test_incident_scss_hits_with_line_numbers(self):
        lines = [n for n, _ in scan_select.check_scss(R15_SCSS)]
        self.assertEqual(lines, [4, 7])

    def test_comment_mentioning_class_is_ignored(self):
        text = "// 舊的 .Select--multi .Select-control 規則已改用 styles\n/* .Select-menu-outer */\n.a { color: red; }\n"
        self.assertEqual(scan_select.check_scss(text), [])

    def test_similar_class_names_are_not_flagged(self):
        self.assertEqual(scan_select.check_scss('.Selector { a: b; }\n.SelectAll { a: b; }\n.my-Select-box { a: b; }\n'), [])

    def test_menu_outer_and_bare_select_are_flagged(self):
        lines = [n for n, _ in scan_select.check_scss('.Select-menu-outer { a: b; }\n.Select { a: b; }\n.Select.is-open { a: b; }\n')]
        self.assertEqual(lines, [1, 2, 3])

    def test_v5_prefixed_classes_are_clean(self):
        self.assertEqual(scan_select.check_scss('.probe__control { a: b; }\n.probe__value-container { a: b; }\n'), [])


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', SCRIPT] + list(args), capture_output=True, text=True)

    def test_exit_1_prints_hits_and_summary_last(self):
        a = self.write('a.js', R15_SINGLE)
        b = self.write('b.js', R18_MISSING)
        s = self.write('s.scss', R15_SCSS)
        r = self.run_cli('--scss', s, '%s=%s' % (a, b))
        self.assertEqual(r.returncode, 1)
        last = r.stdout.strip().split('\n')[-1]
        self.assertTrue(last.startswith('scan_select: 掃描 1 個 <Select> 元素、1 個 scss：3 處命中'), last)

    def test_exit_0_when_clean_and_still_prints_summary(self):
        a = self.write('a.js', R15_SINGLE)
        b = self.write('b.js', R18_FIXED)
        r = self.run_cli('%s=%s' % (a, b))
        self.assertEqual(r.returncode, 0)
        self.assertIn('掃描 1 個 <Select> 元素、0 個 scss：0 處命中', r.stdout)

    def test_missing_file_is_exit_2_not_skipped(self):
        a = self.write('a.js', R15_SINGLE)
        r = self.run_cli('%s=%s' % (a, os.path.join(self.tmp.name, 'nope.js')))
        self.assertEqual(r.returncode, 2)
        self.assertIn('讀不了檔案', r.stdout)

    def test_missing_scss_is_exit_2(self):
        r = self.run_cli('--scss', os.path.join(self.tmp.name, 'nope.scss'))
        self.assertEqual(r.returncode, 2)

    def test_no_args_is_exit_2(self):
        self.assertEqual(self.run_cli().returncode, 2)

    def test_unknown_argument_is_exit_2(self):
        self.assertEqual(self.run_cli('whatever').returncode, 2)

    def test_scss_flag_without_value_is_exit_2(self):
        self.assertEqual(self.run_cli('--scss').returncode, 2)

    def test_hit_in_second_pair_still_reported_after_clean_first_pair(self):
        a = self.write('a.js', R15_SINGLE)
        ok = self.write('ok.js', R18_FIXED)
        bad = self.write('bad.js', R18_MISSING)
        r = self.run_cli('%s=%s' % (a, ok), '%s=%s' % (a, bad))
        self.assertEqual(r.returncode, 1)
        self.assertIn('bad.js', r.stdout)


if __name__ == '__main__':
    unittest.main()
