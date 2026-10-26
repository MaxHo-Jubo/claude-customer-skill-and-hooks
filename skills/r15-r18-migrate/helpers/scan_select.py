"""掃描遷移產出檔的 react-select 預設值退化（1.2.0 新增）。

為什麼要掃：react-select v1（R15，1.3.0）→ v5（R18，5.8.0）有兩個「省略 prop 時行為相反」的靜默退化，
建置、eslint、smoke 都不會報（見 `docs/api-mapping.md` §6.3，事故 CUP-225 `caselist-modals`，PR #11400）：
1. v1 的 `clearable` 預設 `true`、v5 單選的 `isClearable` 預設 `false`：R15 沒寫 `clearable` 的單選，搬完就失去清除鈕；
2. 同層 scss／css 針對 v1 class（`.Select-control`、`.Select--multi` 等）的規則，在 v5 不命中而靜默失效。

本腳本機械檢查這兩項：
- 成對檔（`<R15 檔>=<R18 檔>`）：把兩邊的 `<Select ...>` 元素依出現順序一一配對；
  R15 單選（沒有 `multi`）沒寫 `clearable={false}` 而 R18 沒有 `isClearable` → 命中；
  R15 明寫 `clearable={false}` 而 R18 卻有 `isClearable`（沒寫成 false）→ 命中；
  R18 元素有展開 props（`{...x}`）→ 判斷不了、一律命中，請人工看；
  兩邊 `<Select>` 元素數不同 → 配對不了、一律命中，請人工看（不靜默略過）；
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
    """抽出所有 `<name ...>` 元素的 props 字串與行號：[(行號, props)]。大括號深度與字串引號都處理。"""
    found = []
    for m in re.finditer(r'<' + re.escape(name) + r'(?=[\s/>])', text):
        j = m.end()
        depth = 0
        quote = None
        while j < len(text):
            c = text[j]
            if quote:
                if c == quote and text[j - 1] != '\\':
                    quote = None
            elif c in QUOTES:
                quote = c
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            elif c == '>' and depth == 0:
                break
            j += 1
        found.append((text.count('\n', 0, m.start()) + 1, text[m.end():j]))
    return found


def flags(props, v1):
    """回傳 (是否多選, clearable 系 prop 是否出現, 該 prop 是否明寫 false)。v1：multi／clearable；v5：isMulti／isClearable。"""
    multi_name, clear_name = ('multi', 'clearable') if v1 else ('isMulti', 'isClearable')
    multi = re.search(r'(?<![\w])' + multi_name + r'(?![\w])', props) is not None
    m = re.search(r'(?<![\w])' + clear_name + r'(?:=\{([^}]*)\})?(?![\w])', props)
    present = m is not None
    is_false = present and m.group(1) is not None and m.group(1).strip() == 'false'
    return multi, present, is_false


def has_spread(props):
    return re.search(r'\{\s*\.\.\.', props) is not None


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
    for (l15, p15), (l18, p18) in zip(e15, e18):
        multi15, _, false15 = flags(p15, True)
        _, present18, false18 = flags(p18, False)
        if has_spread(p18):
            hits.append('R18 第 %d 行的 <Select> 有展開 props，判斷不了清除鈕，請人工看（R15 第 %d 行）' % (l18, l15))
        elif not multi15 and not false15 and not present18:
            hits.append('R15 第 %d 行的單選預設可清除、R18 第 %d 行缺 isClearable' % (l15, l18))
        elif not multi15 and false15 and present18 and not false18:
            hits.append('R15 第 %d 行明寫 clearable={false}、R18 第 %d 行卻可清除（isClearable 沒寫成 false）' % (l15, l18))
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
