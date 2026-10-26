"""掃描遷移產出檔裡的 `rem` 用法（1.1.8 新增）。

為什麼要掃：R15 的根字級是 10px（bootstrap 3.4.1 的 `html { font-size: 10px }`），R18 是 13px
（`frontend/react_18/src/assets/styles/_default.scss` 的 `html { font-size: 13px }`）；
另外 R15 的 `index.ejs` 沒有 viewport meta（手機上整頁被縮小）、R18 的 `index_18.ejs` 有 `width=device-width`。
R15 的 `4rem` 是 40px，原樣搬到 R18 變 52px，建置照過、畫面「看起來正常」只是字大很多，
CUP-228（用餐紀錄頁）就是這樣上線的。本腳本只負責「找出所有 rem」，不判斷該換成什麼：
桌機頁與手機瀏覽器頁的處理不同，見 `docs/api-mapping.md` §8.5。

掃描範圍：`.scss .css .js .jsx .ts .tsx`；樣式檔與 JS 行內 style 字串（例如 `fontSize: '4rem'`）都會抓，
註解內的 rem 不算（`//`、`/* */`）。`em` 相對父層、不受根字級影響，不掃。

刻意保留 rem 的行：在同一行尾加註解 `rem-ok: <原因>`（會被略過，但請把該行寫進報告的 ⚠ 清單）。

用法（在 skill 根目錄）：
    python3 helpers/scan_rem.py <檔案...>

結束碼：0 = 無命中；1 = 有命中（逐行印出 `檔:行號: 內容`）；2 = 用法錯誤或檔案不存在／讀不了（不靜默略過）。
最後一行一定印出「掃描 N 個檔…」，用來確認這支真的跑過、不是沒掃到東西。
"""

import os
import re
import sys

# 會被掃描的副檔名；其他副檔名的檔案計入「略過」並在摘要列出數量
SCAN_EXTS = ('.scss', '.css', '.js', '.jsx', '.ts', '.tsx')

# 數值 + rem；前面不得緊接英數字、底線、小數點（避免吃到識別字或 `1.2.3rem` 之類的片段）
REM_RE = re.compile(r'(?<![\w.])\d+(?:\.\d+)?rem\b')

# 行尾放行標記
ALLOW_MARK = 'rem-ok'


def blank_comments(text):
    """把 `/* */` 與 `//` 註解的內容換成空白（換行保留，行號才對得上）。"""
    # STEP 01: 區塊註解（可跨行）：只保留換行
    text = re.sub(r'/\*.*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group()), text, flags=re.S)
    # STEP 02: 行首的 `//` 整行註解
    text = re.sub(r'(?m)^[ \t]*//.*$', '', text)
    # STEP 03: 行尾 `//` 註解；要求 `//` 前面是空白，避免誤砍 `http://` 這類字串
    text = re.sub(r'(?m)(?<=[ \t])//.*$', '', text)
    return text


def scan_file(path):
    """回傳 [(行號, 原始行內容)]：該檔去除註解後仍含 rem、且該行沒有放行標記的行。"""
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    raw_lines = raw.split('\n')
    hits = []
    for i, line in enumerate(blank_comments(raw).split('\n')):
        if REM_RE.search(line) and ALLOW_MARK not in raw_lines[i]:
            hits.append((i + 1, raw_lines[i].strip()))
    return hits


def main(argv):
    if not argv:
        print('用法：python3 helpers/scan_rem.py <檔案...>', file=sys.stderr)
        return 2
    scanned = 0
    skipped = 0
    total = 0
    for path in argv:
        if not os.path.isfile(path):
            print(f'錯誤：檔案不存在或不是檔案：{path}', file=sys.stderr)
            return 2
        if not path.endswith(SCAN_EXTS):
            skipped += 1
            continue
        try:
            hits = scan_file(path)
        except (OSError, UnicodeDecodeError) as err:
            print(f'錯誤：讀不了 {path}：{err}', file=sys.stderr)
            return 2
        scanned += 1
        for lineno, content in hits:
            print(f'{path}:{lineno}: {content}')
        total += len(hits)
    print(f'掃描 {scanned} 個檔（略過 {skipped} 個非樣式／腳本檔），命中 {total} 行')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
