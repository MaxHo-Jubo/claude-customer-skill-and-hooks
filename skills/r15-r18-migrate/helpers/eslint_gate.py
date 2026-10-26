"""eslint 基準比對閘門（1.2.0 新增）：取代「eslint 有 error 就 blocked、又不准 eslint-disable」的舊規則。

為什麼要換：2026-10-23 實測剩下的 76 個 entry、283 個 R15 檔，281 個檔在 R18 的 eslint 設定下有 error（71/71 個 entry
都有），舊規則下 runner 幾乎每個 page entry 都會停在 `blocked(build_failed)`。但整檔 `eslint-disable` 又會把 eslint
唯一的用處（抓「翻譯過程新引入的錯」）一起關掉。折衷：**只容忍 R15 原檔本來就有的違規**。

做法（每個 R15→R18 檔對）：
1. 基準：把 R15 原檔內容當成放在 R18 落點路徑，用 R18 的 eslint 設定跑一次，得到每條規則的 error 數量；
2. 搬遷後：把 R18 檔（先去掉本腳本之前寫過的檔頭）再跑一次；
3. 判定：
   - parse error、`import/no-unresolved` 必須為 0（那是真的壞檔／壞 import，不能蓋）；
   - `PATH_DEPENDENT` 內的 import 規則（遷移後路徑必然不同，沒有意義的基準）放行，不做基準比對；
   - 其餘每條規則，搬遷後的數量不得超過 R15 基準，超過就是「翻譯新引入」→ 不過；
   - 搬遷後的檔（去掉本腳本檔頭後）手寫的 eslint-disable／enable 指令，按 R15 原檔的指令數量基準比較：
     R18 超過 R15 數量才列違規，但不證明個別指令相同（只比數量，不比內容）。指令只計入實際的 JS／TS 註解 token，
     字串、模板字串、正規表示式字面值內的文字不算；遇到無法判定的語法偏向不計入（漏報代價小、誤報會擋掉正確遷移）。
     執行 eslint 時一律帶 `--no-inline-config`，基準與搬遷後都不吃檔案內的 inline 設定，
     所以手寫的停用指令藏不住錯，且 R15 原檔本來就有的指令照搬不會被誤擋；
4. 全部檔對都過，才在每個需要的檔最前面寫檔頭 `/* eslint-disable <實際觸發的規則> */`（只列實際觸發的規則，不整檔關閉）。
   任何一個檔不過就一個檔都不寫（全有或全無，重跑結果才一致）。
   檔頭只代表「已通過規則數量的基準比對」：不證明逐筆違規都源自 R15；路徑相關規則是直接放行、沒有基準比對，
   檔頭會另用一行點名這些規則。
5. 被關掉的規則裡有「可能掩蓋真問題」的（`RISK_RULES`）逐行印 `RISK:`，請寫進報告的 ⚠ 清單。

檔頭只能由本腳本產生：手寫的 eslint-disable 指令只按 R15 數量基準比較、不證明個別指令相同，在基準數量內仍可能讓翻譯新引入的錯被放過。
本腳本不修任何程式碼、不用 `--fix`（會對 R15 原碼大範圍重排，破壞逐行比對）。

用法（在 skill 根目錄）：
    python3 helpers/eslint_gate.py --repo <repo 根目錄> [--write] --pair <R15 檔>=<R18 檔> [--pair ...]
路徑可為絕對路徑或相對 `--repo`。沒帶 `--write` 只檢查、不寫檔。只處理 `.js .jsx .ts .tsx`，其他副檔名計入略過。

結束碼：0 = 全部通過（有 `--write` 時檔頭已寫入）；1 = 有檔不過（逐行印原因，沒有任何檔被改）；
2 = 用法錯誤或環境問題（檔案不存在、找不到 eslint、eslint 本身出錯、檔案被 eslint 忽略），不靜默略過。
最後一行一定印出「eslint_gate: 檢查 N 個檔…」。
"""

import argparse
import json
import os
import re
import subprocess
import sys

# 本腳本寫的檔頭的第一行（用來辨識並在重跑時整段換掉，避免重複疊加）
HEADER_MARK = '// R15 原碼逐字搬遷：'
# 檔頭第一行：只宣稱「已通過規則數量的基準比對」，不宣稱逐筆違規都源自 R15
HEADER_REASON = HEADER_MARK + '下列規則已通過 eslint_gate 的 R15 基準數量比對（搬遷後每條規則的 error 數量不超過 R15 基準；只列本檔實際觸發的規則）\n'

# 路徑相關規則出現在檔頭時的補充說明前綴（後面接規則名單）；說明這些規則沒有基準比對
HEADER_PATH_NOTE = '// 其中路徑相關規則（遷移後路徑必然不同）沒有基準比對、直接放行：'

# 會被檢查的副檔名
LINT_EXTS = ('.js', '.jsx', '.ts', '.tsx')

# 必須為 0 的規則；`None` 代表 parse error（eslint 回報的 ruleId 是 null）
ALWAYS_ZERO = frozenset([None, 'import/no-unresolved'])

# 遷移後路徑必然不同的 import 規則：沒有意義的基準，放行
PATH_DEPENDENT = frozenset([
    'import/no-relative-packages', 'import/extensions', 'import/order', 'import/newline-after-import',
    'import/first', 'import/no-useless-path-segments',
])

# 被關掉時要請人寫進報告 ⚠ 清單的規則：它們可能掩蓋真問題（死碼、未定義變數、行為相依的寬鬆比較、未宣告依賴…）
RISK_RULES = frozenset([
    'no-undef', 'react/jsx-no-undef', 'no-unused-vars', '@typescript-eslint/no-unused-vars', 'no-unreachable',
    'no-shadow', '@typescript-eslint/no-shadow', 'consistent-return', 'array-callback-return', 'eqeqeq',
    'react/no-deprecated', 'react/no-direct-mutation-state', 'react/jsx-key', 'no-dupe-class-members', 'no-dupe-keys',
    'no-redeclare', 'no-prototype-builtins', 'import/no-extraneous-dependencies', 'react-hooks/rules-of-hooks',
    'react-hooks/exhaustive-deps',
])

# 手寫的 eslint 停用／啟用指令：套用在「註解內容」（不含 `//`、`/*`、`*/`）的開頭，
# 內容以 eslint-disable／eslint-enable（含 -line／-next-line 變體）開頭，後面接空白或結尾（與 eslint 自己的判斷一致）
DIRECTIVE_PATTERN = re.compile(r'\s*eslint-(?:disable|enable)(?:-next-line|-line)?(?:\s|$)')

# 之後的 `/` 是正規表示式開頭（不是除法）的關鍵字
REGEX_PRECEDING_KEYWORDS = frozenset([
    'return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void', 'throw', 'case', 'do', 'else', 'yield', 'await',
])

# 識別字／數字／正規表示式旗標：連續的字母、數字、底線、`$`（含非 ASCII 字母）
WORD_PATTERN = re.compile(r'[\w$]+')

# 手寫指令違規在違規清單與行號表中使用的名稱（不是 eslint 規則 id）
DIRECTIVE_RULE = '手寫 eslint-disable/enable 指令'

# 手寫指令違規的原因說明
DIRECTIVE_WHY = '手寫的停用指令超過 R15 指令數量基準（只比數量，不證明個別指令相同）；閘門不接受'

# eslint 對被忽略檔案給的訊息關鍵字（被忽略 = 沒檢查，必須當成環境錯誤，不能當成「0 error」）
IGNORED_MARKER = 'File ignored'


class GateError(Exception):
    """用法或環境問題（對應結束碼 2）。"""


def strip_header(text):
    """去掉本腳本寫過的檔頭（第一行是 HEADER_MARK、到第一個單獨一行的 `*/` 為止）；沒有檔頭就原樣回傳。"""
    if not text.startswith(HEADER_MARK):
        return text
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if line.strip() == '*/':
            return '\n'.join(lines[i + 1:])
    raise GateError('檔頭只有開頭沒有結尾 `*/`，請人工檢查')


def build_header(rules):
    """組檔頭：一行原因註解 + （有路徑相關規則時）一行豁免說明 + 每條規則一行的 eslint-disable 區塊。"""
    # STEP 01: 挑出名單中沒有基準比對的路徑相關規則
    path_rules = [r for r in rules if r in PATH_DEPENDENT]
    # STEP 02: 有才多一行豁免說明，沒有就維持原本的一行原因
    note = HEADER_PATH_NOTE + '、'.join(path_rules) + '\n' if path_rules else ''
    return HEADER_REASON + note + '/* eslint-disable\n' + ',\n'.join('  ' + r for r in rules) + '\n*/\n'


def skip_quoted(text, start):
    """跳過以 text[start]（單引號或雙引號）開頭的字串字面值，回傳字串結束後的位置。

    字串不跨行：遇到未跳脫的換行就在換行處結束（未結束的字串不會吞掉後面的行）；遇到檔尾回傳檔尾。
    """
    quote = text[start]
    n = len(text)
    j = start + 1
    # STEP 01: 逐字元找結束引號
    while j < n:
        ch = text[j]
        # STEP 01.01: 反斜線連同下一個字元一起跳過（含跳脫的引號與行尾續行）
        if ch == '\\':
            j += 2
        elif ch == quote:
            return j + 1
        elif ch == '\n':
            return j
        else:
            j += 1
    return n


def scan_template(text, start, depths):
    """掃模板字串本文，從 start（開頭反引號之後，或 `${ }` 的結尾 `}` 之後）到結尾反引號或下一個 `${`。

    depths 是每層尚未結束的 `${ }` 運算式內、未配對 `{` 的數量（最內層在最後）；不修改傳入的 depths。
    回傳 (新位置, 之後的 `/` 能否是正規表示式開頭, 新 depths)：遇到 `${` 就回到程式碼狀態並多一層；
    遇到結尾反引號或檔尾就結束這個模板字串。
    """
    n = len(text)
    j = start
    # STEP 01: 逐字元找結尾反引號或 `${`
    while j < n:
        ch = text[j]
        # STEP 01.01: 反斜線連同下一個字元一起跳過（含跳脫的反引號與 `\${`）
        if ch == '\\':
            j += 2
        elif ch == '`':
            return j + 1, False, depths
        elif ch == '$' and text.startswith('{', j + 1):
            return j + 2, True, depths + (0,)
        else:
            j += 1
    return n, False, depths


def skip_regex(text, start):
    """嘗試把 text[start] 的 `/` 當成正規表示式字面值開頭並跳過，回傳（含旗標）結束後的位置；
    同一行內找不到結尾就回傳 None（呼叫端改當除法處理，偏向不吞掉後面的文字）。
    """
    n = len(text)
    j = start + 1
    in_class = False
    # STEP 01: 逐字元找結尾斜線（字元集合 [...] 內的斜線不算結尾）
    while j < n:
        ch = text[j]
        # STEP 01.01: 反斜線連同下一個字元一起跳過；跳脫換行或直接換行都不是合法的正規表示式
        if ch == '\\':
            if text[j + 1:j + 2] == '\n':
                return None
            j += 2
        elif ch == '\n':
            return None
        elif ch == '[':
            in_class = True
            j += 1
        elif ch == ']':
            in_class = False
            j += 1
        elif ch == '/' and not in_class:
            flags = WORD_PATTERN.match(text, j + 1)
            return flags.end() if flags else j + 1
        else:
            j += 1
    return None


def scan_comments(text):
    """依序產出文字中每個 JS／TS 註解 token：(註解起始位置, 註解內容（不含 `//`、`/*`、`*/`）)。

    只做純 Python 的輕量掃描，不是完整的 parser：會跳過單雙引號字串、模板字串（含 `${ }` 巢狀）與正規表示式字面值，
    其內的 `//`、`/*` 不算註解。`/` 判斷為正規表示式或除法靠「前一個有意義的 token」的啟發式；
    無法判定時偏向不吞字元／不產出註解（漏報代價小，誤報會擋掉正確遷移）。未結束的區塊註解算到檔尾。
    已知限制：JSX 文字節點（標籤之間的純文字）不辨識，其中的 `//` 與 `/* */`（例如網址、被當成文字的區塊註解寫法）都會被當成註解；
    只有該文字緊接 eslint-disable／enable 才會誤報（例如 `<div>/* eslint-disable */</div>` 會算成指令；2026-10-26 對
    react_15、react_18 共 1905 個 JS／TS 檔、48035 個註解與 @babel/parser 逐一比對，只有 2 個檔的 JSX 網址文字多算註解，
    590 個指令行號完全一致）。
    """
    n = len(text)
    i = 0
    # 目前位置若遇到 `/`，能否是正規表示式開頭（檔案開頭與運算子之後可以；識別字、數字、字串、`)`、`]`、`}` 之後是除法）
    regex_ok = True
    # 每層尚未結束的 `${ }` 運算式內，未配對 `{` 的數量（最內層在最後）；空 tuple = 不在任何 `${ }` 內
    depths = ()
    # STEP 01: 逐 token 前進
    while i < n:
        ch = text[i]
        pair = text[i:i + 2]
        # STEP 01.01: 註解（程式碼狀態下 `//`、`/*` 一定是註解，不會是正規表示式）；不改變 regex_ok
        if pair == '//':
            end = text.find('\n', i)
            end = n if end < 0 else end
            yield i, text[i + 2:end]
            i = end
        elif pair == '/*':
            end = text.find('*/', i + 2)
            yield i, text[i + 2:n if end < 0 else end]
            i = n if end < 0 else end + 2
        # STEP 01.02: 空白與 `++`／`--`（後置遞增後的 `/` 是除法，所以不改變 regex_ok）
        elif ch.isspace():
            i += 1
        elif pair in ('++', '--'):
            i += 2
        # STEP 01.03: 單雙引號字串與模板字串
        elif ch in '"\'':
            i = skip_quoted(text, i)
            regex_ok = False
        elif ch == '`':
            i, regex_ok, depths = scan_template(text, i + 1, depths)
        # STEP 01.04: 大括號：只在 `${ }` 內才需要配對，最內層的 `}` 配完就回到模板字串本文
        elif ch == '{':
            depths = depths[:-1] + (depths[-1] + 1,) if depths else depths
            regex_ok = True
            i += 1
        elif ch == '}' and depths and depths[-1] == 0:
            i, regex_ok, depths = scan_template(text, i + 1, depths[:-1])
        elif ch == '}':
            depths = depths[:-1] + (depths[-1] - 1,) if depths else depths
            regex_ok = False
            i += 1
        # STEP 01.05: `/`：前一個 token 允許時嘗試當正規表示式；`</`（JSX 閉合標籤）、同一行找不到結尾都當除法
        elif ch == '/':
            end = skip_regex(text, i) if regex_ok and text[i - 1:i] != '<' else None
            i = i + 1 if end is None else end
            regex_ok = end is None
        # STEP 01.06: 識別字／數字（部分關鍵字之後可接正規表示式）或其他標點（`)`、`]` 之後是除法）
        else:
            word = WORD_PATTERN.match(text, i)
            if word:
                i = word.end()
                regex_ok = word.group() in REGEX_PRECEDING_KEYWORDS
            else:
                i += 1
                regex_ok = ch not in ')]'


def find_directive_lines(text):
    """找出文字中手寫的 eslint-disable／enable 指令，回傳各自所在的行號（1 起算）清單；沒有就回空清單。

    只計入實際的註解 token（見 scan_comments），字串、模板字串、正規表示式內長得像指令的文字不算；
    指令必須在註解內容的開頭（與 eslint 一致），註解中途提到指令文字不算。
    """
    # STEP 01: 掃出所有註解，留下內容以指令開頭的，轉成起始位置所在的行號
    return [text.count('\n', 0, start) + 1 for start, body in scan_comments(text) if DIRECTIVE_PATTERN.match(body)]


def count_errors(messages):
    """eslint 訊息 → {ruleId（parse error 為 None）: error 數量}；只算 severity 2。"""
    counts = {}
    for m in messages:
        if m.get('severity') == 2:
            key = m.get('ruleId')
            counts[key] = counts.get(key, 0) + 1
    return counts


def evaluate(baseline, after):
    """比對基準與搬遷後的規則數量。回傳 (違規清單, 需要關掉的規則)。

    違規 = (規則, 搬遷後數量, 基準數量, 原因)。需要關掉的規則 = 搬遷後仍有 error 的規則（排序後的字串清單）。
    """
    violations = []
    for rule, n in sorted(after.items(), key=lambda kv: str(kv[0])):
        if rule in ALWAYS_ZERO:
            violations.append((rule, n, baseline.get(rule, 0), '必須為 0'))
        elif rule in PATH_DEPENDENT:
            continue
        elif n > baseline.get(rule, 0):
            violations.append((rule, n, baseline.get(rule, 0), '比 R15 基準多（翻譯新引入）'))
    disable = sorted(r for r, n in after.items() if n > 0 and r is not None)
    return violations, disable


def make_eslint_runner(repo):
    """回傳 lint(text, filename) → eslint 訊息清單；用 R18 的 eslint CLI（stdin，不碰檔案系統上的原檔）。"""
    app = os.path.join(repo, 'frontend', 'react_18')
    eslint_bin = os.path.join(app, 'node_modules', 'eslint', 'bin', 'eslint.js')
    if not os.path.isfile(eslint_bin):
        raise GateError('找不到 eslint：%s（react_18 的 node_modules 沒裝？）' % eslint_bin)

    def lint(text, filename):
        # --no-inline-config：不吃檔案內的 eslint-disable／設定註解，否則手寫的停用指令會讓未檢查的程式碼回報 0 error
        proc = subprocess.run(
            ['node', eslint_bin, '--stdin', '--stdin-filename', filename, '--no-ignore', '--no-inline-config', '-f', 'json'],
            input=text, capture_output=True, text=True, cwd=app,
        )
        # eslint 結束碼：0 = 沒有 error、1 = 有 error、2 = eslint 自己出錯
        if proc.returncode not in (0, 1):
            raise GateError('eslint 本身出錯（結束碼 %d）：%s' % (proc.returncode, proc.stderr.strip()[:300]))
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            raise GateError('eslint 輸出不是 JSON：%s' % proc.stdout.strip()[:300])
        if len(data) != 1:
            raise GateError('eslint 對一個檔回了 %d 筆結果' % len(data))
        messages = data[0].get('messages', [])
        if any(IGNORED_MARKER in (m.get('message') or '') for m in messages):
            raise GateError('檔案被 eslint 忽略（沒有實際檢查）：%s' % filename)
        return messages

    return lint


def read_text(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError as exc:
        raise GateError('讀不了檔案 %s：%s' % (path, exc))


def check_pairs(pairs, lint):
    """逐檔對做基準比對。回傳 (結果清單, 略過數)。結果 = dict(r18, body, disable, violations, lines, baseline, after)。"""
    results = []
    skipped = 0
    for r15_path, r18_path in pairs:
        if not r18_path.endswith(LINT_EXTS):
            skipped += 1
            continue
        r15_text = read_text(r15_path)
        r18_text = read_text(r18_path)
        body = strip_header(r18_text)
        baseline_msgs = lint(r15_text, r18_path)
        after_msgs = lint(body, r18_path)
        baseline = count_errors(baseline_msgs)
        after = count_errors(after_msgs)
        violations, disable = evaluate(baseline, after)
        lines = {}
        for m in after_msgs:
            if m.get('severity') == 2:
                lines.setdefault(m.get('ruleId'), []).append(m.get('line'))
        # 手寫指令：比 R15 原檔多就是違規（行號進 lines，與規則違規同一個回報路徑）
        r15_directives = find_directive_lines(r15_text)
        after_directives = find_directive_lines(body)
        if len(after_directives) > len(r15_directives):
            violations.append((DIRECTIVE_RULE, len(after_directives), len(r15_directives), DIRECTIVE_WHY))
            lines[DIRECTIVE_RULE] = after_directives
        results.append({
            'r18': r18_path, 'text': r18_text, 'body': body, 'disable': disable,
            'violations': violations, 'lines': lines, 'baseline': baseline, 'after': after,
        })
    return results, skipped


def apply_headers(results):
    """全部通過後，把檔頭寫進需要的檔；沒有需要關的規則就維持（或還原成）沒有檔頭。回傳寫了幾個檔。"""
    written = 0
    for r in results:
        new_text = (build_header(r['disable']) if r['disable'] else '') + r['body']
        if new_text != r['text']:
            with open(r['r18'], 'w', encoding='utf-8') as f:
                f.write(new_text)
            written += 1
    return written


def report(results, skipped, out):
    """印逐檔結果與摘要；回傳是否全部通過。"""
    failed = 0
    risk_lines = []
    for r in results:
        if r['violations']:
            failed += 1
            for rule, n, base, why in r['violations']:
                shown = r['lines'].get(rule, [])[:5]
                out('FAIL %s: %s 搬遷後 %d 個、R15 基準 %d 個（%s）；行 %s'
                    % (r['r18'], rule if rule is not None else 'parse error', n, base, why, shown))
        else:
            out('OK   %s: %s' % (r['r18'], '、'.join(r['disable']) if r['disable'] else '無需檔頭'))
            for rule in r['disable']:
                if rule in RISK_RULES:
                    risk_lines.append('RISK: %s 關掉了 %s（%d 個）→ 請寫進報告 ⚠ 清單' % (r['r18'], rule, r['after'][rule]))
    for line in risk_lines:
        out(line)
    out('eslint_gate: 檢查 %d 個檔（略過非 JS/TS %d 個）：%d 個不過、%d 個有風險類規則被關'
        % (len(results), skipped, failed, len(risk_lines)))
    return failed == 0


def parse_pair(value, repo):
    if '=' not in value:
        raise GateError('--pair 格式要是 <R15 檔>=<R18 檔>：%s' % value)
    left, right = value.split('=', 1)
    return tuple(p if os.path.isabs(p) else os.path.join(repo, p) for p in (left, right))


def main(argv, lint_factory=make_eslint_runner, out=print):
    parser = argparse.ArgumentParser(prog='eslint_gate.py', add_help=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--pair', action='append', default=[])
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    try:
        if not args.pair:
            raise GateError('至少要一個 --pair')
        repo = os.path.abspath(args.repo)
        pairs = [parse_pair(p, repo) for p in args.pair]
        lint = lint_factory(repo)
        results, skipped = check_pairs(pairs, lint)
    except GateError as exc:
        out('eslint_gate: 錯誤：%s' % exc)
        out('eslint_gate: 檢查 0 個檔（未完成，環境或用法有問題）')
        return 2
    ok = report(results, skipped, out)
    if not ok:
        return 1
    if args.write:
        written = apply_headers(results)
        out('eslint_gate: 已寫入 %d 個檔的檔頭' % written)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
