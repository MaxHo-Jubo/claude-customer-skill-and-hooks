"""掃描遷移產出檔的 react-select 預設值退化（1.2.0 新增）。

為什麼要掃：react-select v1（R15，1.3.0）→ v5（R18，5.8.0）有兩個「省略 prop 時行為相反」的靜默退化，
建置、eslint、smoke 都不會報（見 `docs/api-mapping.md` §6.3，事故 CUP-225 `caselist-modals`，PR #11400）：
1. v1 的 `clearable` 預設 `true`、v5 單選的 `isClearable` 預設 `false`：R15 沒寫 `clearable` 的單選，搬完就失去清除鈕；
2. 同層 scss／css 針對 v1 class（`.Select-control`、`.Select--multi` 等）的規則，在 v5 不命中而靜默失效。

本腳本機械檢查這兩項：
- 成對檔（`<R15 檔>=<R18 檔>`）：把兩邊的 `<Select ...>` 元素依出現順序一一配對；
  每個布林 prop 先解析成 ABSENT／TRUE／FALSE／EXPRESSION 狀態、套 v1／v5 各自的預設值再比（`parse_props`、`element_hit`）；
  R15 單選（`multi` 沒寫或明寫 false）可清除（沒寫 `clearable`、或為 true），而 R18 `isClearable` 缺少或明寫 false → 命中；
  R15 明寫 `clearable={false}` 而 R18 卻有 `isClearable`（沒寫成 false）→ 命中；
  `multi`／`clearable`／`isClearable` 是無法靜態判定的運算式 → 只認兩邊逐字相同的運算式，其餘命中並印「需人工確認」；
  R18 元素有展開 props（`{...x}`）→ 判斷不了、一律命中，請人工看；
  兩邊 `<Select>` 元素數不同 → 配對不了、一律命中，請人工看（不靜默略過）；
  props 結構解析不了（字串／模板／註解／正規表示式／括號／JSX 沒收尾，或無法判定 `/` 是除法還是正規表示式）→ 一律命中並印「無法可靠解析…需人工確認」，
  不回傳猜出來的結尾繼續解析（猜錯會把後面的 `clearable`／`isClearable` 吞掉，靜默放行不等價的遷移）；
  R15 檔有 import react-select 而 R18 檔沒有 → 命中。
- `--scss` 檔：去掉註解後，含 v1 class（`.Select`、`.Select-xxx`、`.Select--xxx`）的行 → 命中。

用法（在 skill 根目錄）：
    python3 helpers/scan_select.py [--scss <樣式檔> ...] [<R15 檔>=<R18 檔> ...]

結束碼：0 = 無命中；1 = 有命中（逐行印出原因）；2 = 用法錯誤或檔案不存在／讀不了（不靜默略過）。
最後一行一定印出「掃描 N 個 <Select> 元素、M 個 scss…」，用來確認這支真的跑過、不是沒掃到東西。
"""

import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scan_rem import blank_comments  # noqa: E402

# v1 的 class 名稱：`.Select` 本身、`.Select-xxx`、`.Select--xxx`；後面不得再接英數字或連字號（避免吃到 `.Selector`）
V1_CLASS_RE = re.compile(r'\.Select(?:--?[A-Za-z][\w-]*)?(?![\w-])')

QUOTES = '"\'`'


def react_select_name(text):
    """回傳 react-select 預設匯入的本地名稱；沒有 import 回 None。"""
    m = re.search(r"import\s+(\w+)\s*(?:,\s*\{[^}]*\})?\s+from\s+['\"]react-select['\"]", text)
    return m.group(1) if m else None


def elements(text, name):
    """抽出所有 `<name ...>` 元素的 props 字串與行號：[(行號, props, 解析錯誤)]。

    標籤結尾由 scan_tag_end 判定（字串、註解、大括號運算式都照 JS／JSX 規則處理）。
    解析失敗的元素不丟例外、不影響其他元素：props 給空字串、第三欄是失敗原因（成功時為 None）。
    """
    # STEP 01: 每個 `<name` 各自找標籤結尾，成功與失敗都留一筆（元素數要能對上）
    found = []
    for m in re.finditer(r'<' + re.escape(name) + r'(?=[\s/>])', text):
        line = text.count('\n', 0, m.start()) + 1
        # STEP 01.01: 結尾找得到 → 收 props；找不到 → 記錄原因，由 check_pair 命中「需人工確認」
        try:
            found.append((line, text[m.end():scan_tag_end(text, m.end())], None))
        except UnparsableError as exc:
            found.append((line, '', str(exc)))
    return found


# 布林 prop 的四種狀態：ABSENT＝沒寫、TRUE／FALSE＝靜態可判定的值（bare 或 ={true}／={false}）、EXPRESSION＝動態運算式或字串（無法靜態判定）
ABSENT = 'ABSENT'
TRUE = 'TRUE'
FALSE = 'FALSE'
EXPRESSION = 'EXPRESSION'

# 頂層 prop 名稱：JSX 屬性名允許 `-`、`:`、`.`
PROP_NAME_RE = re.compile(r'[A-Za-z_$][\w$:.-]*')


class UnparsableError(Exception):
    """props 結構無法可靠解析：字串／模板／註解／正規表示式／括號／JSX 沒收尾，或無法判定 `/` 是除法還是正規表示式。"""


# 之後的 `/` 開正規表示式字面值的關鍵字（`return /x/`）；其他識別字、數字之後的 `/` 是除法
REGEX_KEYWORDS = frozenset(['return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void', 'throw', 'case', 'do', 'else', 'yield', 'await'])

# 後面接 `( ... )` 時，右括號之後的 `/` 開正規表示式的關鍵字（`if (x) /re/.test(y)`）；一般的 `(a + b) / 2` 是除法
PAREN_STATEMENT_KEYWORDS = frozenset(['if', 'while', 'for', 'with'])

# 運算式裡 `<` 開 JSX 的判斷：後面接標籤名、`>`（fragment）或 `/`（結尾標籤）；只在「期待運算元」的位置才成立
JSX_OPEN_RE = re.compile(r'<(?=[A-Za-z_$>/])')

# 成對括號：左括號 -> 右括號
BRACKET_PAIRS = {'(': ')', '[': ']', '{': '}'}


def skip_comment(text, j):
    """text[j] 若是 `//` 行註解或 `/* */` 區塊註解的開頭，回傳註解之後的索引；不是註解回 None。

    行註解停在換行字元上（不吃換行）；到檔尾仍沒換行就回傳 len(text)，讓呼叫端因找不到結尾而失敗。
    區塊註解沒收尾丟 UnparsableError。
    """
    # STEP 01: 只有 `//`、`/*` 開頭才是註解（`/>`、單一 `/` 不是）
    pair = text[j:j + 2]
    if pair == '//':
        end = text.find('\n', j)
        return len(text) if end < 0 else end
    if pair == '/*':
        end = text.find('*/', j + 2)
        if end < 0:
            raise UnparsableError('第 %d 個字元起的 /* 註解沒收尾' % j)
        return end + 2
    return None


def skip_js_string(text, j):
    """text[j] 是 `'` 或 `"`：回傳字串結尾引號之後的索引。反斜線跳脫下一個字元；字串內出現換行（行尾沒接 `\\`）或到檔尾沒收尾丟 UnparsableError。"""
    # STEP 01: quote 是開頭引號，逐字找結尾
    quote = text[j]
    k = j + 1
    while k < len(text):
        c = text[k]
        # STEP 01.01: 跳脫字元連同下一字元一起略過；未跳脫的換行不是合法字串
        if c == '\\':
            k += 2
        elif c == quote:
            return k + 1
        elif c == '\n':
            raise UnparsableError('第 %d 個字元起的 %s 字串沒收尾（換行前沒有結尾引號）' % (j, quote))
        else:
            k += 1
    raise UnparsableError('第 %d 個字元起的 %s 字串沒收尾' % (j, quote))


def skip_jsx_string(text, j):
    """text[j] 是 JSX 屬性值的引號：回傳結尾引號之後的索引。JSX 屬性字串沒有跳脫、可以跨行；沒收尾丟 UnparsableError。"""
    # STEP 01: 找下一個同樣的引號
    end = text.find(text[j], j + 1)
    if end < 0:
        raise UnparsableError('第 %d 個字元起的 JSX 屬性字串沒收尾' % j)
    return end + 1


def skip_template(text, j):
    """text[j] 是反引號：回傳模板字串結尾反引號之後的索引。`${ ... }` 內是完整運算式（交給 scan_braces，可巢狀）；沒收尾丟 UnparsableError。"""
    # STEP 01: 逐字掃，跳脫字元略過、`${` 遞迴掃運算式、反引號結尾
    k = j + 1
    while k < len(text):
        c = text[k]
        if c == '\\':
            k += 2
        elif c == '`':
            return k + 1
        elif c == '$' and text[k + 1:k + 2] == '{':
            k = scan_braces(text, k + 1)
        else:
            k += 1
    raise UnparsableError('第 %d 個字元起的模板字串沒收尾' % j)


def skip_regex(text, j):
    """text[j] 是 `/` 且已判定為正規表示式開頭：回傳字面值結尾 `/` 之後的索引（旗標不在內）。

    字元集 `[...]` 內的 `/` 不結尾、反斜線跳脫下一字元；正規表示式不能跨行，換行或檔尾前沒結尾丟 UnparsableError。
    """
    # STEP 01: in_class 追蹤是否在字元集 `[...]` 內
    in_class = False
    k = j + 1
    while k < len(text):
        c = text[k]
        # STEP 01.01: 跳脫、字元集、結尾 `/`（字元集外）、換行
        if c == '\\':
            # 反斜線後接換行也是跨行（正規表示式字面值不能含換行），走下面的「沒收尾」
            if text[k + 1:k + 2] == '\n':
                break
            k += 2
            continue
        if c == '\n':
            break
        if c == '[':
            in_class = True
        elif c == ']':
            in_class = False
        elif c == '/' and not in_class:
            # STEP 01.02: 結尾 `/` 就是終點；後面的旗標（g、i 等）由 scan_braces 當一般識別字處理，結果相同（之後的 `/` 都是除法）
            return k + 1
        k += 1
    raise UnparsableError('第 %d 個字元起的正規表示式沒收尾' % j)


def scan_tag_end(text, j):
    """從標籤名之後 text[j] 起掃屬性區，回傳結尾 `>` 的索引。

    處理：`{...}` 運算式（scan_braces）、屬性字串（skip_jsx_string）、屬性之間的註解（skip_comment）；
    `/>` 的 `/` 不是註解。到檔尾仍沒有 `>` 丟 UnparsableError。
    """
    # STEP 01: 逐字掃，頂層遇 `>` 結束
    while j < len(text):
        c = text[j]
        # STEP 01.01: 註解整段跳過；`{` 與引號交給共用掃描；其餘字元（屬性名、`=`、`/`）逐個前進
        end = skip_comment(text, j) if c == '/' else None
        if end is not None:
            j = end
        elif c == '{':
            j = scan_braces(text, j)
        elif c in QUOTES:
            j = skip_jsx_string(text, j)
        elif c == '>':
            return j
        else:
            j += 1
    raise UnparsableError('標籤沒有結尾的 `>`')


def skip_jsx(text, i):
    """text[i] 是運算式內 JSX 元素／fragment 的 `<`：回傳整個元素結尾之後的索引。

    開頭與結尾標籤的屬性區用 scan_tag_end 掃，子節點的文字不當 JS（可含 `'`、`/` 等）、`{...}` 子節點用 scan_braces；
    只用巢狀深度配對標籤（不比對標籤名）。結構不完整（多餘的結尾標籤、沒收尾）丟 UnparsableError。
    """
    # STEP 01: depth 是尚未關閉的標籤層數；j 是目前位置（永遠停在某個 `<` 上）
    depth = 0
    j = i
    while True:
        # STEP 01.01: 結尾標籤 `</x>`：深度減一，歸零就是整個元素結束
        if text.startswith('</', j):
            depth -= 1
            if depth < 0:
                raise UnparsableError('第 %d 個字元的 JSX 結尾標籤沒有對應的開頭標籤' % j)
            j = scan_tag_end(text, j + 2) + 1
            if depth == 0:
                return j
        else:
            # STEP 01.02: 開頭標籤：`/>` 自關閉不增加深度，否則深度加一
            close = scan_tag_end(text, j + 1)
            self_closing = text[j + 1:close].rstrip().endswith('/')
            j = close + 1
            if self_closing and depth == 0:
                return j
            if not self_closing:
                depth += 1
        # STEP 01.03: 子節點：純文字略過、`{...}` 運算式用 scan_braces，遇到下一個 `<` 回到 STEP 01.01
        while True:
            while j < len(text) and text[j] not in '<{':
                j += 1
            if j >= len(text):
                raise UnparsableError('JSX 元素沒收尾')
            if text[j] == '<':
                break
            j = scan_braces(text, j)


def scan_braces(text, i):
    """從 text[i]（必須是 `{`）掃到對應的 `}`，依 JS 語法略過字串、模板字串、註解、正規表示式、運算式內的 JSX。

    `/` 是除法還是正規表示式開頭，看前一個有意義的 token：運算子、`(`、`,`、`return` 等關鍵字之後是正規表示式；
    識別字、數字、一般運算式的 `)`、`]`、字串之後是除法（例外：`if`／`while`／`for`／`with` 控制敘述的 `)` 之後是正規表示式，
    見 PAREN_STATEMENT_KEYWORDS）；`}` 之後與 `++`／`--` 之後無法判定，丟 UnparsableError，不猜。
    參數：text - 原文；i - `{` 的位置。
    回傳：對應 `}` 之後一格的索引。
    例外：UnparsableError - 沒收尾、括號種類對不上、或遇到無法判定的 `/`（不回傳猜出來的結尾）。
    """
    # STEP 01: stack 放尚未收尾的左括號與「它的右括號之後 `/` 能否開正規表示式」（`(` 依前一個關鍵字、`[` 否、`{` 無法判定）
    stack = [('{', None)]
    # regex_ok：下一個 `/` 能否開正規表示式：True 能、False 是除法、None 無法判定
    regex_ok = True
    # word：緊接在前的識別字（中間只隔空白與註解），沒有則 None；用來判斷 `if (` 與 `return /`
    word = None
    j = i + 1
    while j < len(text):
        c = text[j]
        # STEP 02: 空白與註解不改變 regex_ok／word
        if c.isspace():
            j += 1
            continue
        end = skip_comment(text, j) if c == '/' else None
        if end is not None:
            j = end
            continue
        prev_word, word = word, None
        # STEP 03: 依字元種類前進並更新 regex_ok
        if c in '"\'':
            j = skip_js_string(text, j)
            regex_ok = False
        elif c == '`':
            j = skip_template(text, j)
            regex_ok = False
        elif c == '/':
            # STEP 03.01: `/` 依 regex_ok 當正規表示式或除法；無法判定就不猜
            if regex_ok is None:
                raise UnparsableError('第 %d 個字元的 `/` 無法判定是除法還是正規表示式' % j)
            if regex_ok:
                j = skip_regex(text, j)
                regex_ok = False
            else:
                j += 1
                regex_ok = True
        elif c == '<' and regex_ok is True and JSX_OPEN_RE.match(text, j):
            j = skip_jsx(text, j)
            regex_ok = False
        elif c in BRACKET_PAIRS:
            stack.append((c, prev_word in PAREN_STATEMENT_KEYWORDS if c == '(' else (False if c == '[' else None)))
            regex_ok = True
            j += 1
        elif c in ')]}':
            # STEP 03.02: 右括號要對上最近的左括號；最外層 `{` 收尾就是答案
            if BRACKET_PAIRS[stack[-1][0]] != c:
                raise UnparsableError('第 %d 個字元的 %s 對不上左括號 %s' % (j, c, stack[-1][0]))
            _, regex_ok = stack.pop()
            j += 1
            if not stack:
                return j
        elif c in '+-':
            # STEP 03.03: `++`／`--` 前置還是後置無法判定，之後的 `/` 不猜
            double = text[j + 1:j + 2] == c
            regex_ok = None if double else True
            j += 2 if double else 1
        elif c.isalnum() or c in '_$':
            # STEP 03.04: 識別字／數字：關鍵字（且不是 `.in` 這種屬性名）之後可接正規表示式，其他之後是除法
            k = j
            while k < len(text) and (text[k].isalnum() or text[k] in '_$'):
                k += 1
            word = text[j:k]
            regex_ok = word in REGEX_KEYWORDS and text[j - 1] != '.'
            j = k
        else:
            # STEP 03.05: 其他運算子與標點（`=`、`,`、`:`、`>`、`.` 等）之後是運算元位置
            regex_ok = True
            j += 1
    raise UnparsableError('第 %d 個字元起的 `{` 沒收尾' % i)


def parse_props(props):
    """把 `<Select ...>` 的 props 字串解析成頂層 prop 的 {名稱: (狀態, 運算式文字)}。

    只看頂層 prop：字串、大括號內（箭頭函式、物件字面值）裡的同名文字不算 prop；`{...x}` 展開不收錄（由 has_spread 處理）。
    同名 prop 出現多次以最後一個為準（JSX 語意）。
    參數：props - elements() 回傳的 props 字串。
    回傳：dict；狀態見 ABSENT／TRUE／FALSE／EXPRESSION，只有 EXPRESSION 的第二欄是運算式原文（字串值連引號保留），其餘為空字串。
    例外：UnparsableError - 運算式或字串沒收尾（不再把剩下的文字吞進同一個運算式）。
    """
    # STEP 01: result 收集頂層 prop；i 是目前掃描位置
    result = {}
    i = 0
    while i < len(props):
        c = props[i]
        # STEP 02: 頂層註解與 `{...}`（展開）整段跳過
        end = skip_comment(props, i) if c == '/' else None
        if end is not None:
            i = end
            continue
        if c == '{':
            i = scan_braces(props, i)
            continue
        m = PROP_NAME_RE.match(props, i)
        if not m:
            i += 1
            continue
        name = m.group(0)
        i = m.end()
        # STEP 03: 名稱後面沒有 `=` → bare prop，等同 true
        k = i
        while k < len(props) and props[k].isspace():
            k += 1
        if k >= len(props) or props[k] != '=':
            result[name] = (TRUE, '')
            continue
        k += 1
        while k < len(props) and props[k].isspace():
            k += 1
        # STEP 04: 依值的形式判定狀態：`{...}` 取內文、引號字串整段保留、其他取到空白為止
        if k < len(props) and props[k] == '{':
            end = scan_braces(props, k)
            i = end
            text = props[k + 1:end - 1].strip()
            if text == 'true':
                result[name] = (TRUE, '')
            elif text == 'false':
                result[name] = (FALSE, '')
            else:
                result[name] = (EXPRESSION, text)
        elif k < len(props) and props[k] in QUOTES:
            end = skip_jsx_string(props, k)
            result[name] = (EXPRESSION, props[k:end])
            i = end
        else:
            end = k
            while end < len(props) and not props[end].isspace():
                end += 1
            result[name] = (EXPRESSION, props[k:end])
            i = end
    return result


def same_expression(a, b):
    """兩段運算式文字去掉空白後是否相同（只認逐字相同，認不出的等價一律當不同）。"""
    return re.sub(r'\s+', '', a) == re.sub(r'\s+', '', b)


def element_hit(l15, p15, l18, p18):
    """比對一組配對元素的清除鈕預設值；回傳命中訊息，沒問題回 None。

    先把每個 prop 解析成狀態、套上 v1／v5 各自的預設值（v1 clearable 預設 true、v5 單選 isClearable 預設 false）再比：
    - R15 多選（multi 為 true）：不檢查；multi 是運算式：R18 isMulti 須是同一運算式，否則人工確認；
    - 兩邊都是靜態值：不等價就命中；任一邊是運算式：只認逐字相同的運算式，其餘一律人工確認。
    參數：l15／l18 - R15／R18 元素的行號；p15／p18 - 兩邊 props 字串。
    回傳：命中訊息字串或 None。
    """
    # STEP 01: 解析兩邊 props
    props15 = parse_props(p15)
    props18 = parse_props(p18)
    # STEP 02: multi（v1 預設 false）：多選略過；運算式要 R18 isMulti 是同一運算式才繼續當單選分支檢查
    multi_state, multi_expr = props15.get('multi', (ABSENT, ''))
    if multi_state == TRUE:
        return None
    if multi_state == EXPRESSION:
        ismulti18 = props18.get('isMulti', (ABSENT, ''))
        if ismulti18[0] != EXPRESSION or not same_expression(multi_expr, ismulti18[1]):
            return 'R15 第 %d 行 multi={%s} 是動態值，R18 第 %d 行 isMulti 無法確認等價，需人工確認是單選還是多選（單選要有 isClearable）' % (l15, multi_expr, l18)
    # STEP 03: clearable／isClearable 套預設值：R15 沒寫＝TRUE；R18 沒寫＝FALSE（單選）
    state15, expr15 = props15.get('clearable', (TRUE, ''))
    state18, expr18 = props18.get('isClearable', (ABSENT, ''))
    # STEP 04: R15 是運算式：只有 R18 isClearable 是同一運算式才算等價
    if state15 == EXPRESSION:
        if state18 == EXPRESSION and same_expression(expr15, expr18):
            return None
        return 'R15 第 %d 行 clearable={%s} 是動態值，R18 第 %d 行 isClearable 無法確認等價，需人工確認' % (l15, expr15, l18)
    # STEP 05: R18 是運算式：R15 是靜態值，無法確認 R18 的值是否與之相同
    if state18 == EXPRESSION:
        return 'R15 第 %d 行的清除鈕是靜態值（%s）、R18 第 %d 行 isClearable={%s} 是動態值，需人工確認' % (
            l15, 'clearable={false}' if state15 == FALSE else '可清除', l18, expr18)
    # STEP 06: 兩邊都是靜態值：R15 可清除而 R18 缺或為 false → 退化；R15 不可清除而 R18 為 true → 多出清除鈕
    if state15 == TRUE and state18 == ABSENT:
        return 'R15 第 %d 行的單選預設可清除、R18 第 %d 行缺 isClearable' % (l15, l18)
    if state15 == TRUE and state18 == FALSE:
        return 'R15 第 %d 行的單選可清除、R18 第 %d 行卻明寫 isClearable={false}（清除鈕被關掉）' % (l15, l18)
    if state15 == FALSE and state18 == TRUE:
        return 'R15 第 %d 行明寫 clearable={false}、R18 第 %d 行卻可清除（isClearable 沒寫成 false）' % (l15, l18)
    return None


def has_spread(props):
    return re.search(r'\{\s*\.\.\.', props) is not None


def unparsable_hit(l15, l18, reasons):
    """組「無法可靠解析」的命中訊息。參數：l15／l18 - 兩邊元素行號；reasons - 解析失敗的 [(哪一邊, 原因)]。"""
    # STEP 01: 點名哪一邊、什麼原因，要求人工確認
    detail = '；'.join('%s：%s' % (side, why) for side, why in reasons)
    return 'R15 第 %d 行、R18 第 %d 行的 <Select> props 無法可靠解析（%s），需人工確認清除鈕是否等價' % (l15, l18, detail)


def check_pair(r15_text, r18_text):
    """回傳 (命中訊息清單, 配對到的元素數)。"""
    n15 = react_select_name(r15_text)
    n18 = react_select_name(r18_text)
    if not n15:
        return [], 0
    if not n18:
        return ['R15 檔有 import react-select、R18 檔沒有（用了別的元件？請人工確認清除鈕等預設值）'], 0
    e15 = elements(r15_text, n15)
    e18 = elements(r18_text, n18)
    if len(e15) != len(e18):
        return ['<Select> 元素數不同（R15 %d 個、R18 %d 個），無法配對，請人工逐個比對' % (len(e15), len(e18))], 0
    hits = []
    for (l15, p15, err15), (l18, p18, err18) in zip(e15, e18):
        # STEP 01: 任一邊 props 解析不了：不猜，命中並要求人工確認
        errors = [(side, err) for side, err in (('R15', err15), ('R18', err18)) if err]
        if errors:
            hits.append(unparsable_hit(l15, l18, errors))
            continue
        if has_spread(p18):
            hits.append('R18 第 %d 行的 <Select> 有展開 props，判斷不了清除鈕，請人工看（R15 第 %d 行）' % (l18, l15))
            continue
        # STEP 02: props 已能切出來，但 parse_props 仍可能在個別 prop 上失敗（同樣走人工確認）
        try:
            msg = element_hit(l15, p15, l18, p18)
        except UnparsableError as exc:
            msg = unparsable_hit(l15, l18, [('R15／R18', str(exc))])
        if msg:
            hits.append(msg)
    return hits, len(e15)


def check_scss(text):
    """回傳 [(行號, 內容)]：去掉註解後仍含 v1 class 的行。"""
    raw_lines = text.split('\n')
    hits = []
    for i, line in enumerate(blank_comments(text).split('\n')):
        if V1_CLASS_RE.search(line):
            hits.append((i + 1, raw_lines[i].strip()))
    return hits


def read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError as exc:
        print('scan_select: 讀不了檔案 %s：%s' % (path, exc))
        print('scan_select: 掃描 0 個 <Select> 元素、0 個 scss（未完成）')
        sys.exit(2)


def main(argv):
    scss_files = []
    pairs = []
    i = 0
    while i < len(argv):
        if argv[i] == '--scss':
            if i + 1 >= len(argv):
                print('scan_select: --scss 後面要接檔案')
                return 2
            scss_files.append(argv[i + 1])
            i += 2
        elif '=' in argv[i]:
            pairs.append(tuple(argv[i].split('=', 1)))
            i += 1
        else:
            print('scan_select: 看不懂的參數：%s（成對檔格式 <R15 檔>=<R18 檔>）' % argv[i])
            return 2
    if not pairs and not scss_files:
        print('用法：python3 helpers/scan_select.py [--scss <樣式檔> ...] [<R15 檔>=<R18 檔> ...]')
        return 2

    total_hits = 0
    scanned = 0
    for r15, r18 in pairs:
        hits, n = check_pair(read(r15), read(r18))
        scanned += n
        for msg in hits:
            print('%s: %s' % (r18, msg))
        total_hits += len(hits)
    for path in scss_files:
        for line_no, content in check_scss(read(path)):
            print('%s:%d: 含 react-select v1 的 class，v5 不會命中：%s' % (path, line_no, content))
            total_hits += 1
    print('scan_select: 掃描 %d 個 <Select> 元素、%d 個 scss：%d 處命中' % (scanned, len(scss_files), total_hits))
    return 1 if total_hits else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
