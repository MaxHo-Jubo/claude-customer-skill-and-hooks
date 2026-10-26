"""eslint 基準比對閘門（1.2.0 新增）：取代「eslint 有 error 就 blocked、又不准 eslint-disable」的舊規則。

為什麼要換：2026-10-23 實測剩下的 76 個 entry、283 個 R15 檔，281 個檔在 R18 的 eslint 設定下有 error（71/71 個 entry
都有），舊規則下 runner 幾乎每個 page entry 都會停在 `blocked(build_failed)`。但整檔 `eslint-disable` 又會把 eslint
唯一的用處（抓「翻譯過程新引入的錯」）一起關掉。折衷：**只容忍 R15 原檔本來就有的違規**。

做法（每個 R15→R18 檔對）：
1. 基準：把 R15 原檔內容當成放在 R18 落點路徑，用 R18 的 eslint 設定跑一次，得到每條規則的 error 數量；
2. 搬遷後：把 R18 檔（先去掉本腳本之前寫過的檔頭）再跑一次；
3. 判定：
   - parse error、`import/no-unresolved` 必須為 0（那是真的壞檔／壞 import，不能蓋）；
   - `PATH_DEPENDENT` 內的 import 規則（遷移後路徑必然不同，沒有意義的基準）放行；
   - 其餘每條規則，搬遷後的數量不得超過 R15 基準，超過就是「翻譯新引入」→ 不過；
4. 全部檔對都過，才在每個需要的檔最前面寫檔頭 `/* eslint-disable <實際觸發的規則> */`（只列實際觸發的規則，不整檔關閉）。
   任何一個檔不過就一個檔都不寫（全有或全無，重跑結果才一致）。
5. 被關掉的規則裡有「可能掩蓋真問題」的（`RISK_RULES`）逐行印 `RISK:`，請寫進報告的 ⚠ 清單。

檔頭只能由本腳本產生：手寫的 eslint-disable 沒有基準比對，會讓翻譯新引入的錯被放過。
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
import subprocess
import sys

# 本腳本寫的檔頭的第一行（用來辨識並在重跑時整段換掉，避免重複疊加）
HEADER_MARK = '// R15 原碼逐字搬遷：'
HEADER_REASON = HEADER_MARK + '下列規則的違規是 R15 既有寫法，保留以利逐行比對（只列本檔實際觸發的規則）\n'

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
    """組檔頭：一行原因註解 + 每條規則一行的 eslint-disable 區塊。"""
    return HEADER_REASON + '/* eslint-disable\n' + ',\n'.join('  ' + r for r in rules) + '\n*/\n'


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
        proc = subprocess.run(
            ['node', eslint_bin, '--stdin', '--stdin-filename', filename, '--no-ignore', '-f', 'json'],
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
