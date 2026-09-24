#!/usr/bin/env python3
"""session_index.py — sessions/ 內呼叫檔的命名與掃描（runner.py 與 diagnostics.py 共用）。

一次 CLI 呼叫在 sessions/ 留下的檔案都以 `<entry>-<n>` 開頭：`.claim`（序號佔號）、`.stream.jsonl`、
`.json`（meta）、`--<名稱>.log`（子行程全文，序號與名稱之間是雙減號）。本模組只負責「哪些檔屬於哪個 entry 的第幾號」：

  * 錨定整段檔名比對，不用前綴比對——entry `foo` 與 `foo-1` 共存時，`foo-1-5--npm-ci.log`
    （foo-1 第 5 次）的前綴也是 `foo-1-`，前綴比對會把它算成 foo 第 1 次的 log。
  * 子行程 log 用雙減號分隔、名稱以小寫字母開頭而且不含 `--`（runner.session_log_path 的呼叫點都是）。
    1.1.2 第一批是單減號 `-<名稱>.log`，錨定比對仍有歧義：`orders-sub-1-a-sub-5-npm-ci.log`（entry
    `orders-sub-1-a-sub` 第 5 次）也符合 `orders-sub` 第 1 次、名稱 `a-sub-5-npm-ci`。雙減號之後，短 id 要認領
    長 id 的檔，名稱段勢必含 `--`，被「名稱不含 `--`」擋掉。舊格式的 log 不再被任何 entry 認領（不進診斷包、不參與取號）。

設計約束：
  * 只用 python3 標準函式庫；不 import runner.py 或 diagnostics.py（依賴方向是它們 import 本檔）。
  * 只讀不寫；佔號（建立 .claim）由 runner.next_call_number 做。
"""

import os
import re

# ================================================================ 常數

# CLI stream-json 落檔的副檔名（路徑由 runner.stream_output_path 組；啟動 CLI 前就建立，被訊號中斷的呼叫也會有）
STREAM_SUFFIX = ".stream.jsonl"
# 呼叫 meta 檔的副檔名（runner.save_session_output 在 CLI 結束後寫；被中斷的呼叫沒有它）
META_SUFFIX = ".json"
# 呼叫序號佔號檔的副檔名（runner.next_call_number 以 O_EXCL 建立的空檔，只當「這一號已被用過」的紀錄）
CLAIM_SUFFIX = ".claim"
# 子行程 log 檔名裡序號與名稱之間的分隔（runner.session_log_path 用它組檔名）；名稱本身不可含它
LOG_SEPARATOR = "--"
# 子行程 log 名稱的合法形狀：小寫字母開頭、不含 `/`、不含 `--`（runner.session_log_path 以它檢查、下方掃描規則以它比對，同一份）
LOG_NAME_PATTERN = r"[a-z](?:[^/-]|-(?!-))*"
# 屬於某個 entry 的呼叫檔：<id>-<n> 後面只能接三種固定後綴，或 --<合法名稱>.log（%s 填 re.escape 過的 entry id）
ATTEMPT_FILE_PATTERN = r"^%%s-(\d+)(%s|%s|%s|%s%s\.log)$" % (
    re.escape(META_SUFFIX),
    re.escape(STREAM_SUFFIX),
    re.escape(CLAIM_SUFFIX),
    re.escape(LOG_SEPARATOR),
    LOG_NAME_PATTERN,
)


# ================================================================ 命名


def is_valid_log_name(name):
    """子行程 log 名稱是否合法（LOG_NAME_PATTERN 整段比對）。

    不合法的名稱組出來的 log 不會被任何 entry 認領（不進診斷包、不參與取號），所以 runner 在組檔名前就拒絕。

    @param name 子行程名稱（例如 `npm-ci`、`git-merge-cp-<斷點 id>`）
    @return bool
    """
    # STEP 01: 型別不對直接不合法，其餘整段比對
    return isinstance(name, str) and re.fullmatch(LOG_NAME_PATTERN, name) is not None


# ================================================================ 掃描


def attempt_files(directory, entry_id):
    """列出 sessions 目錄內屬於 entry_id 的呼叫檔。

    @param directory sessions/ 的完整路徑
    @param entry_id entry id
    @return [(序號, 後綴, 檔名)]，依檔名排序；後綴是 .json／.stream.jsonl／.claim 或 --<名稱>.log；目錄不存在回空清單
    """
    # STEP 01: 沒有目錄就沒有任何呼叫紀錄
    if not os.path.isdir(directory):
        # STEP 01.01: 合法的空結果（這個狀態目錄還沒有任何呼叫），不是錯誤
        return []
    # STEP 02: 逐檔錨定比對
    # 這個 entry 專屬的整段檔名比對規則
    pattern = re.compile(ATTEMPT_FILE_PATTERN % re.escape(entry_id))
    # 每個檔名的比對結果（不符合的是 None）
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
    # 這個 entry 所有呼叫檔的序號（同一號可能出現多次）
    numbers = [number for number, _suffix, _name in attempt_files(directory, entry_id)]
    return max(numbers) if numbers else None
