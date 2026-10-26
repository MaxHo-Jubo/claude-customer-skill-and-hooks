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


# react-select 的 import 行，供 sel() 組出最小可掃描的來源檔
IMPORT_LINE = "import Select from 'react-select';\n"


def sel(*lines):
    """組出只含 react-select import 與指定行的測試來源檔。

    參數：lines - import 之後的每一行（第 1 行是 import，所以 lines[0] 是第 2 行）。
    回傳：完整的檔案文字。
    """
    # STEP 01: import 行在第 1 行，其餘行依序接上
    return IMPORT_LINE + '\n'.join(lines) + '\n'


class ClearableValueTest(unittest.TestCase):
    """A1／C9：R15 單選可清除時，R18 isClearable 的「值」也要檢查，不是只看有沒有出現。"""

    def test_r15_omitted_clearable_but_r18_isclearable_false_hits_with_reason_and_lines(self):
        """R15 省略 clearable、R18 寫 isClearable={false}：必須命中，訊息帶兩邊行號與原因。"""
        # STEP 01: R15 省略 clearable（v1 預設可清除）、R18 明寫 false
        r15 = sel('<Select options={o} />')
        r18 = sel('<Select options={o} isClearable={false} />')
        # STEP 02: 命中 1 筆，原因與行號都要在訊息裡
        hits, n = pair(r15, r18)
        self.assertEqual(n, 1)
        self.assertEqual(len(hits), 1)
        self.assertIn('R15 第 2 行', hits[0])
        self.assertIn('R18 第 2 行', hits[0])
        self.assertIn('isClearable={false}', hits[0])

    def test_r15_clearable_true_but_r18_isclearable_false_hits(self):
        """R15 明設 clearable（bare 與 ={true} 兩種寫法）、R18 isClearable={false}：都命中。"""
        for r15_prop in ('clearable', 'clearable={true}'):
            with self.subTest(r15_prop=r15_prop):
                # STEP 01: 兩種「明設 true」的寫法
                hits, _ = pair(sel('<Select %s options={o} />' % r15_prop), sel('<Select isClearable={ false } options={o} />'))
                # STEP 02: 空白不影響判定，仍是 1 筆命中且點出 false
                self.assertEqual(len(hits), 1)
                self.assertIn('isClearable={false}', hits[0])

    def test_r18_isclearable_dynamic_expression_needs_manual_confirmation(self):
        """R15 可清除、R18 isClearable 是無法靜態判定的運算式：命中並要求人工確認。"""
        # STEP 01: R18 的值是變數
        hits, _ = pair(sel('<Select options={o} />'), sel('<Select options={o} isClearable={canClear} />'))
        # STEP 02: 命中且訊息要求人工確認、帶出運算式
        self.assertEqual(len(hits), 1)
        self.assertIn('需人工確認', hits[0])
        self.assertIn('canClear', hits[0])

    def test_r18_isclearable_true_forms_are_clean(self):
        """R18 isClearable 的 bare 與 ={true} 寫法都與 R15 可清除等價：零命中。"""
        for r18_prop in ('isClearable', 'isClearable={true}'):
            with self.subTest(r18_prop=r18_prop):
                # STEP 01: R15 省略 clearable
                self.assertEqual(pair(sel('<Select options={o} />'), sel('<Select options={o} %s />' % r18_prop)), ([], 1))

    def test_r15_clearable_false_but_r18_dynamic_isclearable_needs_manual_confirmation(self):
        """R15 明寫 false、R18 isClearable 是運算式：無法確認等價，命中並要求人工確認。"""
        # STEP 01: R15 固定不可清除、R18 動態
        hits, _ = pair(sel('<Select clearable={false} />'), sel('<Select isClearable={x} />'))
        # STEP 02: 要人工確認
        self.assertEqual(len(hits), 1)
        self.assertIn('需人工確認', hits[0])


class PropStateTest(unittest.TestCase):
    """A2：每個布林 prop 建模為 ABSENT／TRUE／FALSE／EXPRESSION，套預設值後再比對。"""

    def test_parse_props_states(self):
        """parse_props 對各種寫法回傳正確狀態，運算式保留原文字。"""
        # STEP 01: 涵蓋 bare、={true}、={false}、運算式、字串、缺席
        props = scan_select.parse_props('multi clearable={false} a={ x ? 1 : 2 } b="s" c={true}')
        # STEP 02: 逐一斷言
        self.assertEqual(props['multi'], (scan_select.TRUE, ''))
        self.assertEqual(props['clearable'], (scan_select.FALSE, ''))
        self.assertEqual(props['a'], (scan_select.EXPRESSION, 'x ? 1 : 2'))
        self.assertEqual(props['b'], (scan_select.EXPRESSION, '"s"'))
        self.assertEqual(props['c'], (scan_select.TRUE, ''))
        self.assertNotIn('isMulti', props)

    def test_same_name_text_inside_string_or_nested_expression_is_not_a_prop(self):
        """字串或巢狀運算式裡的同名文字不是 prop。"""
        # STEP 01: multi／clearable／isClearable 只出現在字串、箭頭函式、物件字面值裡
        props = scan_select.parse_props('placeholder="multi clearable" onChange={() => multi} style={{ clearable: false, isClearable: 1 }}')
        # STEP 02: 頂層只有 3 個 prop
        self.assertEqual(sorted(props), ['onChange', 'placeholder', 'style'])

    def test_spread_contents_are_not_props(self):
        """頂層 `{...x}` 展開整段跳過，裡面的識別字不算 prop。"""
        # STEP 01: 展開的變數名與物件字面值都剛好叫 multi／clearable
        props = scan_select.parse_props('{...multi} {...{ clearable: false }} options={o}')
        # STEP 02: 只有 options
        self.assertEqual(sorted(props), ['options'])

    def test_r15_multi_false_is_single_and_missing_isclearable_hits(self):
        """multi={false} 是單選：R18 漏補 isClearable 必須命中（codex 重現：原本回 ([], 1)）。"""
        # STEP 01: R15 明確單選、R18 漏補
        hits, n = pair(sel('<Select multi={false} options={o} />'), sel('<Select options={o} />'))
        # STEP 02: 命中缺 isClearable，帶行號
        self.assertEqual(n, 1)
        self.assertEqual(len(hits), 1)
        self.assertIn('缺 isClearable', hits[0])
        self.assertIn('R15 第 2 行', hits[0])

    def test_r15_multi_true_expression_form_is_skipped(self):
        """multi={true} 與 bare multi 等價：多選不需要 isClearable。"""
        # STEP 01: R18 沒有 isClearable
        self.assertEqual(pair(sel('<Select multi={true} options={o} />'), sel('<Select isMulti options={o} />')), ([], 1))

    def test_dynamic_multi_with_equivalent_r18_ismulti_still_checks_clearable(self):
        """multi 是運算式、R18 isMulti 同運算式：視為等價，但單選分支的 isClearable 缺漏仍要命中。"""
        # STEP 01: 兩邊同一個運算式
        hits, _ = pair(sel('<Select multi={m} options={o} />'), sel('<Select isMulti={ m } options={o} />'))
        # STEP 02: 缺 isClearable 命中（若是單選會退化）
        self.assertEqual(len(hits), 1)
        self.assertIn('缺 isClearable', hits[0])

    def test_dynamic_multi_with_equivalent_r18_ismulti_and_isclearable_is_clean(self):
        """同上但 R18 有補 isClearable：零命中。"""
        # STEP 01: R18 補了 isClearable
        self.assertEqual(pair(sel('<Select multi={m} />'), sel('<Select isMulti={m} isClearable />')), ([], 1))

    def test_dynamic_multi_without_equivalent_r18_ismulti_needs_manual_confirmation(self):
        """multi 是運算式、R18 沒有等價 isMulti：判斷不了單選或多選，命中並要求人工確認。"""
        for r18_props in ('options={o}', 'isMulti options={o}', 'isMulti={other}'):
            with self.subTest(r18_props=r18_props):
                # STEP 01: 即使 R18 有 isClearable，multi 無法對上仍須人工確認
                hits, _ = pair(sel('<Select multi={m} />'), sel('<Select isClearable %s />' % r18_props))
                # STEP 02: 要人工確認並點出運算式
                self.assertEqual(len(hits), 1)
                self.assertIn('需人工確認', hits[0])
                self.assertIn('multi={m}', hits[0])

    def test_dynamic_clearable_replaced_by_fixed_isclearable_needs_manual_confirmation(self):
        """clearable={canClear} 改成固定 isClearable：不是等價改寫，命中並要求人工確認（codex 重現）。"""
        # STEP 01: R15 動態、R18 固定 true
        hits, _ = pair(sel('<Select clearable={canClear} />'), sel('<Select isClearable />'))
        # STEP 02: 要人工確認，訊息帶 R15 運算式
        self.assertEqual(len(hits), 1)
        self.assertIn('需人工確認', hits[0])
        self.assertIn('canClear', hits[0])

    def test_dynamic_clearable_with_same_expression_is_clean(self):
        """clearable={canClear} → isClearable={ canClear }：同運算式，等價，零命中。"""
        # STEP 01: 空白差異不算不同
        self.assertEqual(pair(sel('<Select clearable={canClear} />'), sel('<Select isClearable={ canClear } />')), ([], 1))

    def test_dynamic_clearable_dropped_in_r18_needs_manual_confirmation(self):
        """clearable={canClear} 在 R18 整個消失：v5 預設不可清除，命中並要求人工確認。"""
        # STEP 01: R18 沒有 isClearable
        hits, _ = pair(sel('<Select clearable={canClear} />'), sel('<Select options={o} />'))
        # STEP 02: 要人工確認
        self.assertEqual(len(hits), 1)
        self.assertIn('需人工確認', hits[0])

    def test_isclearable_text_inside_other_prop_is_not_a_prop(self):
        """R18 只是 placeholder 字串含 isClearable：不算有補，仍命中缺 isClearable。"""
        # STEP 01: 字串內的同名文字
        hits, _ = pair(sel('<Select options={o} />'), sel('<Select placeholder="isClearable" options={o} />'))
        # STEP 02: 命中缺 isClearable
        self.assertEqual(len(hits), 1)
        self.assertIn('缺 isClearable', hits[0])

    def test_multi_text_inside_string_does_not_make_r15_multi(self):
        """R15 只是 placeholder 字串含 multi：仍是單選，R18 漏補 isClearable 要命中。"""
        # STEP 01: 字串與箭頭函式裡的 multi
        r15 = sel('<Select placeholder="multi" onChange={() => multi} options={o} />')
        hits, _ = pair(r15, sel('<Select options={o} />'))
        # STEP 02: 命中缺 isClearable
        self.assertEqual(len(hits), 1)
        self.assertIn('缺 isClearable', hits[0])


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


class JsLexingTest(unittest.TestCase):
    """第二輪 codex review：scan_braces 要認得 JS 的字串／模板／註解／正規表示式／JSX，認不得時一律「需人工確認」（不靜默放行）。

    每個案例都是「R18 的 isClearable 寫在複雜運算式『之後』」：若運算式的結尾判錯，isClearable 會被吞掉（誤擋）；
    若 R15 的 clearable 寫在之後，則會被吞掉而套預設值（靜默放行），所以兩個方向都測。
    """

    def assert_clean(self, r15_props, r18_props):
        """R15／R18 props 逐字給定：兩邊應等價，零命中且配對 1 個元素。"""
        # STEP 01: 組成最小來源檔後掃描
        self.assertEqual(pair(sel('<Select %s />' % r15_props), sel('<Select %s />' % r18_props)), ([], 1))

    def assert_manual(self, r15_props, r18_props, who='R18'):
        """應命中且訊息是「無法可靠解析…需人工確認」，who 指出是哪一邊解析不了。"""
        # STEP 01: 掃描並取得命中
        hits, n = pair(sel('<Select %s />' % r15_props), sel('<Select %s />' % r18_props))
        # STEP 02: 命中 1 筆，訊息要點名解析失敗與哪一邊，且要求人工確認
        self.assertEqual(len(hits), 1, hits)
        self.assertIn('無法可靠解析', hits[0])
        self.assertIn('需人工確認', hits[0])
        self.assertIn('%s：' % who, hits[0])

    def test_codex_repro_regex_with_quote_swallowed_clearable_false_now_hits(self):
        """缺陷 1（codex 重現）：regex 內的 `"` 讓舊版把 clearable={false} 吞掉、回零命中；現在必須命中且是精確的「卻可清除」。"""
        # STEP 01: R15 clearable={false} 在 regex 之後；R18 多出 isClearable
        r15 = '<Select onInputChange={v => v.replace(/"/g, \'\')} clearable={false} />'
        r18 = '<Select isClearable onInputChange={v => v.replace(/"/g, \'\')} />'
        hits, n = pair(sel(r15), sel(r18))
        # STEP 02: 命中 1 筆且是正確解析出的差異，不是零命中
        self.assertEqual(n, 1)
        self.assertEqual(len(hits), 1, hits)
        self.assertIn('卻可清除', hits[0])

    def test_codex_repro_regex_with_brace_swallowed_isclearable_now_clean(self):
        """缺陷 2（codex 重現）：regex 內的 `{` 讓舊版吞掉後面的 isClearable、誤報缺 isClearable；正確遷移現在要通過。"""
        # STEP 01: R15 單選沒寫 clearable、R18 補了 isClearable，filterOption 的 regex 含 `\{`
        self.assert_clean('filterOption={o => /\\{/.test(o.label)}', 'filterOption={o => /\\{/.test(o.label)} isClearable')

    def test_regex_with_closing_brace_before_isclearable_is_clean(self):
        """regex 含 `}`：不得提早結束運算式。"""
        self.assert_clean('f={o => /\\}/.test(o)}', 'f={o => /\\}/.test(o)} isClearable')

    def test_regex_with_single_quote_and_backtick_is_clean(self):
        """regex 含 `'` 與反引號：不得被當成字串／模板開頭。"""
        self.assert_clean("f={o => /'/.test(o)} g={o => /`/.test(o)}", "g={o => /`/.test(o)} f={o => /'/.test(o)} isClearable")

    def test_regex_char_class_containing_slash_and_quote_is_clean(self):
        """regex 字元集 `[/"]` 內的 `/` 不結束 regex，`"` 不開字串。"""
        self.assert_clean('f={s => s.match(/[/"]/gi)}', 'f={s => s.match(/[/"]/gi)} isClearable')

    def test_regex_followed_by_prop_with_swapped_order_still_catches_clearable_diff(self):
        """屬性換序：R15 clearable={false} 在 regex 之前，R18 isClearable 在 regex 之後，仍要攔到清除鈕差異。"""
        # STEP 01: 兩邊順序不同、都含 regex 引號
        hits, _ = pair(sel('<Select clearable={false} f={v => v.replace(/"/g, "")} />'),
                       sel('<Select f={v => v.replace(/"/g, "")} isClearable />'))
        # STEP 02: 精確命中
        self.assertEqual(len(hits), 1, hits)
        self.assertIn('卻可清除', hits[0])

    def test_division_is_not_a_regex(self):
        """`a / b / c` 是除法：若被當成 regex，後面字串內的 `/` 會被誤當 regex 結尾，運算式就判錯。"""
        # STEP 01: 第一個 `/` 若被當 regex 開頭，會在字串 '/' 內結束，之後的 `' }}` 變成沒收尾的字串
        expr = "style={{ w: a / 2, label: '/', h: b / c / d }}"
        self.assert_clean(expr, expr + ' isClearable')

    def test_division_after_paren_and_bracket_is_not_a_regex(self):
        """`)`／`]` 之後的 `/` 是除法。"""
        expr = "w={(a + b) / 2 + xs[0] / 3 + '/'}"
        self.assert_clean(expr, expr + ' isClearable')

    def test_regex_after_return_keyword_is_a_regex(self):
        """`return /"/.test(s)`：關鍵字之後的 `/` 開 regex，其中的 `"` 不開字串。"""
        expr = 'f={s => { return /"/.test(s) }}'
        self.assert_clean(expr, expr + ' isClearable')

    def test_regex_after_if_paren_is_a_regex(self):
        """`if (x) /"/.test(s)`：if 括號之後的 `/` 開 regex。"""
        expr = 'f={s => { if (s) /"/.test(s) }}'
        self.assert_clean(expr, expr + ' isClearable')

    def test_template_literal_with_nested_braces_is_clean(self):
        """模板字串內 `${ {a:1}.a }` 巢狀大括號，以及模板文字裡的 `}`：不得提早結束。"""
        expr = 't={`}${ {a:1}.a }{ ${`x`} `}'
        self.assert_clean(expr, expr + ' isClearable')

    def test_braces_inside_strings_are_ignored(self):
        """字串內的 `{`、`}`、被跳脫的引號：不影響括號配對。"""
        expr = r'''a={'{'} b={"}"} c={'it\'s }'}'''
        self.assert_clean(expr, expr + ' isClearable')

    def test_jsx_comment_with_brace_is_ignored(self):
        """JSX 註解 `{/* } */}`：出現在 JSX 子節點與頂層 props 都不影響配對。"""
        # STEP 01: 運算式內的 JSX 子節點註解
        expr = 'render={() => <div>{/* } */}</div>}'
        self.assert_clean(expr, expr + ' isClearable')
        # STEP 02: 頂層（props 位置）的 `{/* } */}`
        self.assert_clean('{/* } */} options={o}', '{/* } */} options={o} isClearable')

    def test_comments_inside_expression_are_ignored(self):
        """行註解含引號、區塊註解含 `}`：都不影響配對。"""
        expr = "f={s => {\n // it's a \"test\" {\n s /* } */ }}"
        self.assert_clean(expr, expr + ' isClearable')

    def test_arrow_returning_object_literal_with_brace_string_is_clean(self):
        """`x => ({a: '}'})`：括號內物件字面值含 `}` 字串。"""
        expr = "getOptionValue={x => ({a: '}'})}"
        self.assert_clean(expr, expr + ' isClearable')

    def test_jsx_in_expression_with_apostrophe_text_is_clean(self):
        """運算式內的 JSX 子節點文字含 `'`、`}` 以外字元與結尾標籤：以 JSX 規則掃，不當成 JS。"""
        expr = "formatOptionLabel={o => <span className='x'>don't {o.label} <b>/</b></span>}"
        self.assert_clean(expr, expr + ' isClearable')

    def test_less_than_and_greater_than_operators_are_clean(self):
        """比較運算子 `<`／`>` 不是 JSX 開頭。"""
        expr = 'f={a < b && c > d}'
        self.assert_clean(expr, expr + ' isClearable')

    def test_line_comment_inside_tag_with_gt_does_not_end_element(self):
        """標籤層級的註解含 `>`：不得提早結束元素，否則 R15 的 clearable={false} 被截掉而套預設值。"""
        # STEP 01: R15 的 clearable={false} 在含 `>` 的註解之後；R18 多出 isClearable
        hits, _ = pair(sel('<Select /* a > b */ clearable={false} />'), sel('<Select isClearable />'))
        # STEP 02: 精確命中
        self.assertEqual(len(hits), 1, hits)
        self.assertIn('卻可清除', hits[0])

    def test_tag_level_comment_words_are_not_props(self):
        """標籤層級註解裡的 `clearable={false}` 不是 prop：R15 仍是預設可清除。"""
        self.assert_clean('/* clearable={false} */ options={o}', 'isClearable options={o}')

    def test_property_named_like_keyword_is_not_a_keyword(self):
        """`x.in / 2`、`x.of / 2`：屬性名恰好是 `in`／`of` 時，之後的 `/` 仍是除法。"""
        expr = "w={x.in / 2 + '/'}"
        self.assert_clean(expr, expr + ' isClearable')

    def test_jsx_attribute_string_ending_with_backslash_is_clean(self):
        """JSX 屬性字串沒有跳脫：`"C:\\"` 的反斜線是普通字元，字串在第二個引號結束（若照 JS 跳脫會吞到後面）。"""
        self.assert_clean('path="C:\\" options={o}', 'path="C:\\" options={o} isClearable')

    def test_unterminated_string_does_not_leak_into_next_line_or_element(self):
        """字串沒收尾（換行前沒有結尾引號）：第 1 個元素回報解析失敗，不得吃進下一行／下一個元素的引號而當成正常。"""
        # STEP 01: R18 第 1 個元素的字串沒收尾，第 2 個元素有引號（可被誤當作第 1 個的結尾）
        r15 = sel("<Select options={a} />", "<Select placeholder='x' />")
        r18 = sel("<Select placeholder={'abc} />", "<Select placeholder='x' isClearable />")
        hits, n = pair(r15, r18)
        # STEP 02: 第 1 個元素命中「無法可靠解析」；第 2 個元素正常、零命中（共 1 筆）
        self.assertEqual(n, 2)
        self.assertEqual(len(hits), 1, hits)
        self.assertIn('無法可靠解析', hits[0])
        self.assertIn('R18 第 2 行', hits[0])

    def test_unterminated_string_needs_manual_confirmation(self):
        """沒收尾的字串：不得靜默繼續，要求人工確認。"""
        self.assert_manual('options={o}', "placeholder={'abc} isClearable")

    def test_unterminated_brace_needs_manual_confirmation(self):
        """括號沒收尾：要求人工確認，不是把剩下的文字當成運算式。"""
        self.assert_manual('options={o}', 'onChange={() => { isClearable')

    def test_unterminated_template_and_regex_need_manual_confirmation(self):
        """沒收尾的模板字串與 regex：都要求人工確認。"""
        self.assert_manual('options={o}', 'a={`abc} isClearable')
        self.assert_manual('options={o}', 'a={s => s.replace(/abc, "")} isClearable')

    def test_unterminated_block_comment_needs_manual_confirmation(self):
        """沒收尾的區塊註解。"""
        self.assert_manual('options={o}', 'a={x /* } isClearable')

    def test_mismatched_brackets_need_manual_confirmation(self):
        """括號種類對不上（`( }`）：判斷不了結尾。"""
        self.assert_manual('options={o}', 'a={(x} isClearable')

    def test_ambiguous_slash_after_close_brace_needs_manual_confirmation(self):
        """`}` 之後的 `/`：區塊結尾（regex）還是物件字面值（除法）無法判定，要求人工確認。"""
        self.assert_manual('options={o}', 'a={ {x: 1} / 2 } isClearable')

    def test_ambiguous_slash_after_increment_needs_manual_confirmation(self):
        """`x++ / 2 / 3`：`++` 之後的 `/` 無法判定是 regex 還是除法（若硬猜成 regex，會把 `/ 2 /` 吃成字面值而看似正常）。"""
        self.assert_manual('options={o}', 'a={i++ / 2 / 3} isClearable')

    def test_unterminated_jsx_needs_manual_confirmation(self):
        """運算式內的 JSX 沒收尾。"""
        self.assert_manual('options={o}', 'a={() => <div>text} isClearable')

    def test_unterminated_tag_needs_manual_confirmation(self):
        """元素本身沒有結尾的 `>`：回報解析失敗，不是把到檔尾的文字當 props。"""
        hits, _ = pair(sel('<Select options={o} />'), IMPORT_LINE + '<Select options={o} isClearable\n')
        self.assertEqual(len(hits), 1, hits)
        self.assertIn('無法可靠解析', hits[0])

    def test_r15_side_parse_failure_is_reported_as_r15(self):
        """R15 那邊解析失敗：訊息點名 R15。"""
        self.assert_manual("a={'x}", 'isClearable', who='R15')

    def test_template_with_backtick_inside_nested_expression_is_clean(self):
        """模板 `${ '`' }` 的運算式內有字串形式的反引號：要遞迴掃 `${}`，不是看到第 2 個反引號就當模板結尾。"""
        expr = "t={`x${ '`' }y`}"
        self.assert_clean(expr, expr + ' isClearable')

    def test_scan_braces_unit_unterminated_and_mismatched_raise(self):
        """scan_braces 單元：沒收尾、括號種類對不上、字串或 regex 內的換行都丟 UnparsableError；行尾反斜線接續字串合法。"""
        # STEP 01: 這些輸入都不得回傳索引
        for bad in ('{ a', '{ [ } ]', "{ 'a\nb' }", '{ (a }', '{ a ) }', '{ x = /a\n/ }'):
            with self.subTest(bad=bad):
                with self.assertRaises(scan_select.UnparsableError):
                    scan_select.scan_braces(bad, 0)
        # STEP 02: 反斜線接續換行的字串合法，回傳 `}` 之後的索引
        ok = "{ 'a\\\nb' }"
        self.assertEqual(scan_select.scan_braces(ok, 0), len(ok))

    def test_regex_literal_with_backslash_newline_raises(self):
        """正規表示式字面值不能跨行，「反斜線＋換行」也算跨行：skip_regex 與 scan_braces 都丟 UnparsableError。

        第三輪 codex review：反斜線分支原本直接跳過下一字元，`/a\\<換行>b/` 會當成合法 regex 回傳結尾索引，與 docstring 的契約不符。
        """
        # STEP 01: skip_regex 直接呼叫
        regex = '/a\\\nb/'
        with self.assertRaises(scan_select.UnparsableError):
            scan_select.skip_regex(regex, 0)
        # STEP 02: 經由 scan_braces（運算式內的 regex）也不得回傳猜出來的結尾
        with self.assertRaises(scan_select.UnparsableError):
            scan_select.scan_braces('{ x = ' + regex + ' }', 0)
        # STEP 03: 對照組：同一個 regex 不含換行時合法，回傳結尾 `/` 之後的索引
        self.assertEqual(scan_select.skip_regex('/a\\/b/', 0), 6)

    def test_parse_props_unterminated_expression_or_string_raises(self):
        """parse_props 單元：運算式或屬性字串沒收尾丟 UnparsableError，不是把剩下的文字當成值。"""
        for bad in ('a={ x', 'a="abc', 'a={ x } b={ "y'):
            with self.subTest(bad=bad):
                with self.assertRaises(scan_select.UnparsableError):
                    scan_select.parse_props(bad)

    def test_scan_braces_returns_index_after_matching_brace_and_raises_when_unterminated(self):
        """scan_braces 單元：正常回傳 `}` 之後的索引；沒收尾丟 UnparsableError（不再回 len(text)）。"""
        # STEP 01: 正常情況回傳 `}` 之後一格
        text = '{ /"}/.test(x) } tail'
        self.assertEqual(text[scan_select.scan_braces(text, 0):], ' tail')
        # STEP 02: 沒收尾丟例外
        with self.assertRaises(scan_select.UnparsableError):
            scan_select.scan_braces('{ "abc', 0)

    def test_elements_reports_parse_error_per_element_and_keeps_counting(self):
        """elements：解析失敗的元素帶錯誤原因、不吞掉其他元素。"""
        # STEP 01: 第 1 個元素字串沒收尾（同行到換行為止），第 2 個正常
        els = scan_select.elements("import S from 'react-select';\n<S a={'x} />\n<S isClearable />\n", 'S')
        # STEP 02: 兩個元素都在；第 1 個有錯誤、第 2 個沒有
        self.assertEqual(len(els), 2)
        self.assertTrue(els[0][2])
        self.assertIsNone(els[1][2])
        self.assertIn('isClearable', els[1][1])


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

    def test_exit_1_when_r15_clearable_and_r18_isclearable_false(self):
        """C9：R15 省略 clearable、R18 isClearable={false}：CLI 退出碼 1，輸出含原因與行號，摘要行仍在最後。"""
        # STEP 01: 兩個成對檔
        a = self.write('a.js', sel('<Select options={o} />'))
        b = self.write('b.js', sel('<Select options={o} isClearable={false} />'))
        # STEP 02: 退出碼 1、訊息帶行號與原因
        r = self.run_cli('%s=%s' % (a, b))
        self.assertEqual(r.returncode, 1)
        self.assertIn('R15 第 2 行', r.stdout)
        self.assertIn('R18 第 2 行', r.stdout)
        self.assertIn('isClearable={false}', r.stdout)
        self.assertTrue(r.stdout.strip().split('\n')[-1].startswith('scan_select: 掃描 1 個 <Select> 元素、0 個 scss：1 處命中'))

    def test_exit_1_when_dynamic_prop_needs_manual_confirmation(self):
        """動態運算式無法確認等價：CLI 退出碼 1 並印出「需人工確認」。"""
        # STEP 01: R15 動態 clearable、R18 固定 isClearable
        a = self.write('a.js', sel('<Select clearable={canClear} />'))
        b = self.write('b.js', sel('<Select isClearable />'))
        # STEP 02: 退出碼 1
        r = self.run_cli('%s=%s' % (a, b))
        self.assertEqual(r.returncode, 1)
        self.assertIn('需人工確認', r.stdout)

    def test_exit_1_when_props_unparsable_and_summary_still_last(self):
        """解析不了的元素：CLI 退出碼 1、印出「需人工確認」，摘要行仍在最後。"""
        # STEP 01: R18 的字串沒收尾
        a = self.write('a.js', sel('<Select options={o} />'))
        b = self.write('b.js', sel("<Select placeholder={'abc} isClearable />"))
        # STEP 02: 退出碼 1、訊息與摘要
        r = self.run_cli('%s=%s' % (a, b))
        self.assertEqual(r.returncode, 1)
        self.assertIn('需人工確認', r.stdout)
        self.assertTrue(r.stdout.strip().split('\n')[-1].startswith('scan_select: 掃描 1 個 <Select> 元素、0 個 scss：1 處命中'))

    def test_hit_in_second_pair_still_reported_after_clean_first_pair(self):
        a = self.write('a.js', R15_SINGLE)
        ok = self.write('ok.js', R18_FIXED)
        bad = self.write('bad.js', R18_MISSING)
        r = self.run_cli('%s=%s' % (a, ok), '%s=%s' % (a, bad))
        self.assertEqual(r.returncode, 1)
        self.assertIn('bad.js', r.stdout)


if __name__ == '__main__':
    unittest.main()
