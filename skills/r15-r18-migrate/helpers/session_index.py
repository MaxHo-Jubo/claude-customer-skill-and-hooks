#!/usr/bin/env python3
"""session_index.py — sessions/ 內呼叫檔的命名與掃描（runner.py 與 diagnostics.py 共用）。

一次 CLI 呼叫在 sessions/ 留下的檔案都以 `<entry>-<n>` 開頭：`.claim`（序號佔號）、`.stream.jsonl`、
`.json`（meta）、`-<名稱>.log`（子行程全文）。本模組只負責「哪些檔屬於哪個 entry 的第幾號」：

  * 錨定整段檔名比對，不用前綴比對——entry `foo` 與 `foo-1` 共存時，`foo-1-5-npm-ci.log`
    （foo-1 第 5 次）的前綴也是 `foo-1-`，前綴比對會把它算成 foo 第 1 次的 log。
  * 子行程 log 名稱一律以小寫字母開頭（runner.session_log_path 的呼叫點都是），才分得出上面那種檔名。

設計約束：
  * 只用 python3 標準函式庫；不 import runner.py 或 diagnostics.py（依賴方向是它們 import 本檔）。
  * 只讀不寫；佔號（建立 .claim）由 runner.next_call_number 做。
"""

import os
import re

# ================================================================ 常數

# stream 落檔、meta 檔、呼叫序號佔號檔的副檔名（與 runner.save_session_output／next_call_number 的命名一致）
STREAM_SUFFIX = ".stream.jsonl"
META_SUFFIX = ".json"
CLAIM_SUFFIX = ".claim"
# 屬於某個 entry 的呼叫檔：<id>-<n> 後面只能接三種固定後綴或 -<小寫開頭名稱>.log（%s 填 re.escape 過的 entry id）
ATTEMPT_FILE_PATTERN = r"^%%s-(\d+)(%s|%s|%s|-[a-z][^/]*\.log)$" % (
    re.escape(META_SUFFIX),
    re.escape(STREAM_SUFFIX),
    re.escape(CLAIM_SUFFIX),
)


# ================================================================ 掃描


def attempt_files(directory, entry_id):
    """列出 sessions 目錄內屬於 entry_id 的呼叫檔。

    @param directory sessions/ 的完整路徑
    @param entry_id entry id
    @return [(序號, 後綴, 檔名)]，依檔名排序；後綴是 .json／.stream.jsonl／.claim 或 -<名稱>.log；目錄不存在回空清單
    """
    # STEP 01: 沒有目錄就沒有任何呼叫紀錄
    if not os.path.isdir(directory):
        return []
    # STEP 02: 逐檔錨定比對
    pattern = re.compile(ATTEMPT_FILE_PATTERN % re.escape(entry_id))
    matches = (pattern.match(name) for name in sorted(os.listdir(directory)))
    return [(int(match.group(1)), match.group(2), match.group(0)) for match in matches if match]


def highest_used_attempt(directory, entry_id):
    """任何呼叫檔（含只佔了號的 .claim、只有 stream 的中斷呼叫、子行程 log）用過的最大序號。

    runner.next_call_number 從它的下一號開始佔；只看 .json 的話，被訊號中斷（沒有 .json）的那一號會被重用、
    stream 與子行程 log 被覆寫。

    @param directory sessions/ 的完整路徑
    @param entry_id entry id
    @return int，或沒有任何呼叫檔時 None
    """
    # STEP 01: 取最大值
    numbers = [number for number, _suffix, _name in attempt_files(directory, entry_id)]
    return max(numbers) if numbers else None
