#!/usr/bin/env python3
"""event_log.py — runner.log.jsonl 的輪替與跨檔讀取（runner.py 與 diagnostics.py 共用，1.1.2 第七批）。

事件紀錄分成兩種檔，都在狀態目錄底下：
  * current：`runner.log.jsonl`。runner.log_event 一律追加到這裡（任何子命令都寫）。
  * 封存檔：`runner.log.<六位數序號>.jsonl`，序號越大越新。只有持 runner.lock 的 run 會在 current 達到 MAX_BYTES 時
    把它改名成下一個序號（rotate_if_needed），並只保留最新 KEEP 份。

讀取一律由新到舊跨檔（iter_newest_first／read_chronological）：先把 current 讀完，才去列封存檔。

設計約束：
  * 只用 python3 標準函式庫；不 import runner.py、diagnostics.py（兩者都 import 本模組）。
  * 讀取失敗不等於空：列目錄失敗時不輪替，讀取序列裡產出一個 None；讀不到的檔同樣產出 None。只有「本來就沒有」
    （current 不存在、封存檔列出之後才被刪掉）才當成空。
  * 封存檔名的比對錨定整段檔名，狀態目錄裡的 `.tmp`、`.gz`、`merge-intent.json` 等其他檔一律不碰。
"""

import collections
import json
import os
import re

# ================================================================ 常數

# current 的檔名（runner.log_event 追加的對象）
RUNNER_LOG_NAME = "runner.log.jsonl"
# 封存檔序號的位數（檔名固定寬度補零）
ARCHIVE_DIGITS = 6
# 封存檔名格式（套序號）
ARCHIVE_NAME_FORMAT = "runner.log.%0" + str(ARCHIVE_DIGITS) + "d.jsonl"
# 封存檔名比對：錨定頭尾、序號恰好六位 ASCII 數字（配 fullmatch 用，檔名尾端多一個換行也不算）
ARCHIVE_PATTERN = re.compile(r"^runner\.log\.(\d{%d})\.jsonl$" % ARCHIVE_DIGITS, re.ASCII)
# 最後一個可用的序號：用完之後改名的目標會對不上 ARCHIVE_PATTERN（讀不到也刪不掉），所以不再輪替
MAX_ARCHIVE_NUMBER = 10 ** ARCHIVE_DIGITS - 1
# current 達到（大於或等於）這個大小（位元組）就在下一個輪替點改名封存（user 拍板：5 MB）
MAX_BYTES = 5 * 1024 * 1024
# 最多保留幾份封存檔，超過的刪最舊的（user 拍板：5 份；總量上限約 MAX_BYTES ×（KEEP＋1））
KEEP = 5

# rotate_if_needed 的結果：rotated 是否改名了；archive 新封存檔的檔名；removed 刪掉的舊封存檔檔名；
# error 沒有輪替的原因（沒達門檻時是 None）；prune_error 改名成功但刪舊檔失敗的說明（多留幾份，不影響輪替本身）
RotationResult = collections.namedtuple("RotationResult", ["rotated", "archive", "removed", "error", "prune_error"])


# ================================================================ 路徑與列目錄


def current_path(state_dir):
    """current 的完整路徑。

    @param state_dir 狀態目錄
    @return 完整路徑
    """
    # STEP 01: 組路徑
    return os.path.join(state_dir, RUNNER_LOG_NAME)


def archive_paths(state_dir):
    """狀態目錄裡的封存檔，序號由大到小（最新的在前）。

    列目錄失敗照樣拋出，不回空清單：呼叫端要分得出「沒有封存檔」與「不知道有沒有」——輪替拿空清單會從 1 號重新編、
    序號倒退，讀取拿空清單會把讀不到當成沒有事件。

    @param state_dir 狀態目錄
    @return [(序號, 完整路徑)]
    @raises OSError 列不出狀態目錄
    """
    # STEP 01: 只收整段檔名符合的
    found = []
    for name in os.listdir(state_dir):
        # 檔名比對結果（不符合是 None）
        match = ARCHIVE_PATTERN.fullmatch(name)
        if match:
            found.append((int(match.group(1)), os.path.join(state_dir, name)))
    # STEP 02: 新的在前
    return sorted(found, reverse=True)


# ================================================================ 讀取


def _read_lines(path):
    """讀一個事件紀錄檔的全部行（errors="replace"：壞位元組變替代字元，那一行的 JSON 解析會失敗）。

    @param path 檔案路徑
    @return (行清單, 錯誤說明)：不存在是 ([], None)——current 還沒有事件、或封存檔列出之後才被刪掉，都是本來就沒有；
        其他讀取錯誤是 (None, 說明)
    """
    # STEP 01: 讀檔
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.readlines(), None
    except FileNotFoundError:
        return [], None
    except OSError as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)


def _files_newest_first(state_dir):
    """由新到舊逐檔產出 (檔名, 行清單, 錯誤說明)：先 current，current 讀完、呼叫端還要下一筆時才列封存檔。

    順序不能反過來：先列封存檔、再開 current 的話，兩者之間若有輪替，舊的 current 會被改名成一個不在清單裡的封存檔，
    那一整批事件就漏掉；照現在的順序，讀完 current 之後才發生的輪替頂多讓同一批事件以封存檔再出現一次。
    只有持 runner.lock 的 run 會輪替，runner 自己的讀取與輪替在同一個行程裡依序發生，不會碰到；別的行程
    （diagnose 子命令）讀的時候剛好碰上 run 輪替，可能重複讀到那一批——已知限制，不會漏。

    @param state_dir 狀態目錄
    @return generator：(檔名, 行清單或 None, 錯誤說明或 None)；列不出封存檔時產出一個 (說明, None, 錯誤) 後結束
    """
    # STEP 01: current
    # current 的各行與讀取錯誤
    lines, error = _read_lines(current_path(state_dir))
    yield RUNNER_LOG_NAME, lines, error
    # STEP 02: 封存檔（到這裡才列目錄）；列不出來就是讀不到，不是沒有
    try:
        # 封存檔（新的在前）
        archives = archive_paths(state_dir)
    except OSError as exc:
        yield "封存檔清單", None, "列目錄失敗 %s: %s" % (type(exc).__name__, exc)
        return
    for _number, path in archives:
        lines, error = _read_lines(path)
        yield os.path.basename(path), lines, error


def _parse_record(text):
    """把一行解析成事件；解析失敗或不是物件（dict）回 None。

    @param text 去掉頭尾空白、非空的一行
    @return 事件 dict 或 None
    """
    # STEP 01: 解析
    try:
        # 這一行解析後的值
        record = json.loads(text)
    except Exception:  # pylint: disable=broad-except
        # 讀取既有證據的防禦邊界：這一行是過去寫進來的資料，壞成什麼樣都可能（ValueError、深度巢狀的 RecursionError、
        # 其他解析器內部錯誤），對呼叫端都只是「這一行讀不懂」；往外拋只會把一次暫停變成 crash
        return None
    return record if isinstance(record, dict) else None


def _newest_first(state_dir):
    """由新到舊逐筆產出 (事件或 None, 讀不到的來源說明或 None)；惰性：呼叫端停下就不再讀後面的檔、不再解析更舊的行。

    @param state_dir 狀態目錄
    @return generator：壞行是 (None, None)；讀不到的檔或列不出的目錄是 (None, 說明)
    """
    # STEP 01: 逐檔
    for name, lines, error in _files_newest_first(state_dir):
        # STEP 01.01: 讀不到的檔：一個哨兵，交給呼叫端決定
        if lines is None:
            yield None, "%s（%s）" % (name, error)
            continue
        # STEP 01.02: 由新到舊逐行解析，空行略過
        for line in reversed(lines):
            # 去掉頭尾空白的這一行
            text = line.strip()
            if text:
                yield _parse_record(text), None


def iter_newest_first(state_dir):
    """由新到舊逐筆產出事件（generator），永不拋例外；壞行、讀不到的檔、列不出的目錄都產出 None。

    None 是同一個哨兵：呼叫端既有的壞行策略（停下或略過）同樣適用於讀不到的檔，不會把讀不到當成沒有事件。
    順序與已知限制見 _files_newest_first。

    @param state_dir 狀態目錄
    @return generator，逐筆產出事件 dict 或 None；最新的先產出
    """
    # STEP 01: 丟掉來源說明
    for record, _gap in _newest_first(state_dir):
        yield record


def read_chronological(state_dir, tail=None, keep=None):
    """跨檔讀事件，由舊到新回傳；壞行略過，讀不到的檔另外列出（呼叫端寫進 SUMMARY，不宣稱沒有事件）。

    tail 給定時由新到舊收滿 tail 筆符合的就停（更舊的檔不開），再反轉成由舊到新。

    @param state_dir 狀態目錄
    @param tail 只要最新的幾筆（None 或 0 表示全部）
    @param keep 篩選函式（事件 dict → bool），先篩再算 tail；None 表示全收
    @return (事件 dict 清單（由舊到新）, 讀不到的來源說明清單)
    """
    # STEP 01: 由新到舊收
    # 收到的事件（由新到舊）
    records = []
    # 讀不到的來源說明
    unreadable = []
    for record, gap in _newest_first(state_dir):
        if gap is not None:
            unreadable.append(gap)
            continue
        if record is None or (keep is not None and not keep(record)):
            continue
        records.append(record)
        if tail and len(records) >= tail:
            break
    # STEP 02: 反轉成由舊到新
    return records[::-1], unreadable


# ================================================================ 輪替


def _prune(paths_newest_first):
    """保留最新 KEEP 份封存檔，刪掉其餘的。

    @param paths_newest_first 封存檔完整路徑，最新的在前（只含符合 ARCHIVE_PATTERN 的）
    @return (刪掉的檔名清單, 刪除失敗的說明或 None)
    """
    # STEP 01: 超過 KEEP 的逐一刪；已經不在的不算失敗
    # 刪掉的檔名
    removed = []
    # 刪不掉的檔與原因
    errors = []
    for path in paths_newest_first[KEEP:]:
        try:
            os.remove(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append("%s: %s" % (os.path.basename(path), exc))
            continue
        removed.append(os.path.basename(path))
    return removed, "；".join(errors) or None


def rotate_if_needed(state_dir):
    """current 達到 MAX_BYTES 就改名成下一個序號的封存檔，並刪掉超過 KEEP 份的最舊封存檔。

    前提：呼叫端持有 runner.lock（唯一的輪替者），所以「檢查目標不存在 → 改名」之間沒有競爭。改名是原子的；
    刪舊檔中途被殺頂多多留一份。序號而不是時間戳：時鐘回撥不會讓檔名排序倒退。
    不輪替的情況都不拋例外，由結果的 error 說明：讀不到 current 的大小、列不出目錄（不當成沒有封存檔）、序號用完、
    目標已存在（不覆寫）、改名失敗。

    @param state_dir 狀態目錄
    @return RotationResult
    """
    # STEP 01: 大小未達門檻（含 current 不存在）不輪替；讀不到大小不算沒達到
    # current 的路徑
    path = current_path(state_dir)
    try:
        # current 的大小（位元組）
        size = os.stat(path).st_size
    except FileNotFoundError:
        return RotationResult(False, None, [], None, None)
    except OSError as exc:
        return RotationResult(False, None, [], "讀不到 %s 的大小: %s" % (RUNNER_LOG_NAME, exc), None)
    if size < MAX_BYTES:
        return RotationResult(False, None, [], None, None)
    # STEP 02: 嚴格列目錄，取最大序號＋1
    try:
        # 既有的封存檔（新的在前）
        archives = archive_paths(state_dir)
    except OSError as exc:
        return RotationResult(False, None, [], "列不出封存檔，不輪替: %s" % exc, None)
    # 下一個序號
    number = archives[0][0] + 1 if archives else 1
    if number > MAX_ARCHIVE_NUMBER:
        return RotationResult(False, None, [], "封存序號已用到 %d，不輪替（先搬走舊的封存檔）" % MAX_ARCHIVE_NUMBER, None)
    # 新封存檔的完整路徑
    target = os.path.join(state_dir, ARCHIVE_NAME_FORMAT % number)
    # STEP 03: 目標已存在就中止（不覆寫任何檔）；改名
    if os.path.lexists(target):
        return RotationResult(False, None, [], "%s 已存在，不覆寫、不輪替" % os.path.basename(target), None)
    try:
        os.rename(path, target)
    except OSError as exc:
        return RotationResult(False, None, [], "%s 改名失敗: %s" % (RUNNER_LOG_NAME, exc), None)
    # STEP 04: 刪最舊的（只看剛才列出的封存檔＋新的這一份）
    # 刪掉的舊封存檔與刪除失敗的說明
    removed, prune_error = _prune([target] + [archive for _number, archive in archives])
    return RotationResult(True, os.path.basename(target), removed, None, prune_error)
