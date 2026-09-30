"""runner.py 1.1.2 第七批項目 1 的回歸測試（寫入端）：runner.log.jsonl 輪替。

current（runner.log.jsonl）達到門檻時，只有持 runner.lock 的 run 在取鎖後與主迴圈每輪開頭把它改名成
runner.log.<六位數序號>.jsonl，只保留最新 KEEP 份；其他子命令只追加。本檔驗輪替本身（改名、序號、保留份數、
失敗時不中斷 run、別的子命令不輪替、改名前已開的檔寫入不遺失）；讀取端（跨檔讀、started_at 界定、去重、
診斷包）在 test_log_rotation_reads.py。

事件一律用真的 runner.log_event 寫；門檻多半 patch 成 2KB（event_log.MAX_BYTES），T1.1 用 user 拍板的真門檻。
event_log 是這一批新增的模組，只在用到它的測試函式內匯入（見 load_event_log）：先紅的 T1.1 只走 cmd_run 的公開行為，
實作之前以 AssertionError 失敗，而不是整個檔以 ImportError 失敗。封存檔名、事件名、門檻與份數寫成字面值（外部契約）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 480; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_log_rotation.py -v
"""

import argparse
import contextlib
import errno
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import start_patches  # noqa: E402  pylint: disable=wrong-import-position
from test_post_cli_brake import BrakeHarness  # noqa: E402  pylint: disable=wrong-import-position

# user 拍板的輪替門檻（外部契約：達到 5 MB 就輪替；不引用 event_log 的常數，常數被改掉時測試要紅）
USER_MAX_BYTES = 5 * 1024 * 1024
# user 拍板的封存檔保留份數（外部契約）
USER_KEEP = 5
# 測試裡把門檻 patch 成的小值（位元組）：寫十來筆填充事件就會超過
SMALL_MAX_BYTES = 2048
# 填充事件 detail 的字元數
FILLER_CHARS = 200
# 「大事件」detail 的字元數：一筆就超過 SMALL_MAX_BYTES
BIG_EVENT_CHARS = SMALL_MAX_BYTES + FILLER_CHARS
# current 的檔名（外部契約）
CURRENT_NAME = "runner.log.jsonl"
# 封存檔名格式（外部契約：runner.log.<六位數序號>.jsonl）
ARCHIVE_NAME_FORMAT = "runner.log.%06d.jsonl"
# 封存檔名的比對（同一個外部契約；只給測試數封存檔用）
ARCHIVE_NAME_RE = re.compile(r"runner\.log\.[0-9]{6}\.jsonl")
# 第一次輪替出來的封存序號
FIRST_ARCHIVE = 1
# 列目錄失敗測試裡預先存在的封存序號（1 號空著：失敗若被當成「沒有封存檔」就會改名成 1 號）
EXISTING_ARCHIVE = 3
# 六位數序號的最後一號（用完之後不能再輪替）
LAST_ARCHIVE_NUMBER = 999999
# 保留份數測試要做的輪替次數：比保留份數多兩次，最舊的兩份要被刪掉
PRUNE_ROUNDS = USER_KEEP + 2
# 狀態目錄裡長得像封存檔、但不是封存檔的檔案（輪替與刪舊檔都不能碰）：名稱 → 內容
FOREIGN_FILES = {
    "runner.log.1.jsonl": b'{"event": "hand-made"}\n',
    "runner.log.000001.jsonl.gz": b"gzip-bytes",
    "runner.log.000001.jsonl.tmp": b"partial",
    "merge-intent.json": b'{"version": 1}\n',
}
# 注入的改名錯誤訊息（斷言 stderr 與事件用）
RENAME_ERROR = "rename boom"
# 輪替持續失敗的輪替點次數（同一個行程裡連續遇到同一個錯誤）
REPEATED_FAILURES = 3
# 注入的列目錄錯誤訊息（斷言 stderr 與讀不到的說明用）
LISTDIR_ERROR = "listdir boom"
# 子行程情境的整體上限（秒）：超過代表卡住，測試失敗而不是跟著卡
CHILD_TIMEOUT_SECONDS = 20
# T1.10 改名之後才寫的三筆：輪替自己記的 log_rotated、改名後的新事件、子行程晚寫的那一行（它落在封存檔，讀起來排在另兩筆之前）
LATE_EVENTS = ("log_rotated", "after_rotation", "late_writer")
# 在獨立行程裡模擬「別的子命令在改名前開好檔、改名後才寫」：argv[1] = current 路徑；開檔後印 opened，讀到一行才寫
APPEND_AFTER_RENAME_SCENARIO = """
import sys
handle = open(sys.argv[1], "a", encoding="utf-8")
sys.stdout.write("opened\\n")
sys.stdout.flush()
sys.stdin.readline()
handle.write('{"event": "late_writer"}\\n')
handle.close()
"""


def load_event_log():
    """延遲匯入 event_log。

    event_log 是這一批新增的模組：放在模組層匯入的話，實作之前整個檔以 ImportError 失敗，先紅的測試就拿不到
    AssertionError。只有用到它的測試在函式內呼叫這裡。

    @return event_log 模組
    """
    # STEP 01: 匯入（sys.path 已含 helpers/）
    import event_log  # pylint: disable=import-outside-toplevel

    return event_log


def make_state(test_case):
    """建一個空的狀態目錄（含子目錄），測試結束時整個刪掉。

    @param test_case 目前的 TestCase（登記清理）
    @return runner 設定（只有讀寫事件紀錄與 cmd_run 取鎖前檢查用得到的欄位）
    """
    # STEP 01: 暫存根目錄與設定
    # 暫存根目錄
    root = tempfile.mkdtemp(prefix="r18-logrot-")
    test_case.addCleanup(shutil.rmtree, root, True)
    # runner 設定
    config = {"state_dir": os.path.join(root, "state"), "repo_dir": root, "notify_channel": "none"}
    runner.ensure_state_dir(config)
    return config


def log_path(config, name=CURRENT_NAME):
    """狀態目錄下某個事件紀錄檔的完整路徑。

    @param config runner 設定
    @param name 檔名（預設 current）
    @return 完整路徑
    """
    # STEP 01: 組路徑
    return os.path.join(config["state_dir"], name)


def archive_name(number):
    """第 number 號封存檔的檔名。

    @param number 序號
    @return 檔名
    """
    # STEP 01: 套格式
    return ARCHIVE_NAME_FORMAT % number


def archive_current(config, number):
    """把 current 改名成第 number 號封存檔——與輪替相同的改名，用來造「事件在封存檔」的前置狀態，不經過受測的輪替程式。

    @param config runner 設定
    @param number 封存序號
    @return None
    """
    # STEP 01: 改名
    os.rename(log_path(config), log_path(config, archive_name(number)))


def read_events(path):
    """某個事件紀錄檔的全部事件（由舊到新）。

    @param path 檔案路徑
    @return 事件 dict 清單
    """
    # STEP 01: 逐行解析（空行略過）
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def event_names(path):
    """某個事件紀錄檔裡的事件名稱（由舊到新）。

    @param path 檔案路徑
    @return 名稱清單
    """
    # STEP 01: 取 event 欄位
    return [record.get("event") for record in read_events(path)]


def archive_names_in(config):
    """狀態目錄裡符合封存檔名的檔案（排序後）。

    @param config runner 設定
    @return 檔名清單
    """
    # STEP 01: 整段檔名比對外部契約的格式
    return sorted(name for name in os.listdir(config["state_dir"]) if ARCHIVE_NAME_RE.fullmatch(name))


def quiet():
    """吞掉 log_event 印到 stdout 的每一行（大量事件的測試用）。

    @return context manager
    """
    # STEP 01: 導向記憶體緩衝
    return contextlib.redirect_stdout(io.StringIO())


def fill_current(config, limit):
    """用真的 log_event 寫填充事件，直到 current 超過 limit 位元組。

    @param config runner 設定
    @param limit 位元組數
    @return None
    """
    # STEP 01: 一筆一筆寫、每次重看大小
    # current 的路徑
    path = log_path(config)
    with quiet():
        while not os.path.exists(path) or os.path.getsize(path) <= limit:
            runner.log_event(config, None, "filler", detail="x" * FILLER_CHARS)


def patch_threshold(test_case, value=SMALL_MAX_BYTES):
    """把輪替門檻（event_log.MAX_BYTES）patch 成 value，測試結束時還原。

    @param test_case 目前的 TestCase（登記還原）
    @param value 新門檻（位元組）
    @return None
    """
    # STEP 01: 啟動 patch 並登記還原
    patcher = mock.patch.object(load_event_log(), "MAX_BYTES", value)
    patcher.start()
    test_case.addCleanup(patcher.stop)


def failing_for(real, target, message):
    """回傳一個包住 real 的替身：第一個參數等於 target 時拋 OSError(message)，其餘照常。

    @param real 被包住的真函式（os.rename、os.listdir…）
    @param target 要讓它失敗的路徑
    @param message 錯誤訊息
    @return 替身函式
    """

    # STEP 01: 包出只攔 target 那一次的替身
    def fake(path, *args, **kwargs):
        """只讓 target 那一次失敗。

        @param path 第一個參數（路徑）
        @param args 其餘位置參數（原樣轉給真函式）
        @param kwargs 其餘關鍵字參數（原樣轉給真函式）
        @return 真函式的回傳值
        """
        # STEP 01: 命中就拋，否則照常
        if path == target:
            raise OSError(errno.EIO, message)
        return real(path, *args, **kwargs)

    return fake


class HeldRunHarness(unittest.TestCase):
    """鎖定中的 cmd_run：取鎖、輪替、記 hold_active 就退出——啟動輪替的最短真實路徑。"""

    def setUp(self):
        """空狀態目錄＋鎖定中的 queue；隔離訊號 handler、必填檢查與通知。

        @return None
        """
        # STEP 01: 隔離
        # 被換掉的 runner 函式：名稱 → mock
        mocks = start_patches(self, "install_shutdown_handlers", "require_config", "notify")
        mocks["require_config"].return_value = True
        # STEP 02: 狀態目錄與鎖定中的 queue
        # runner 設定
        self.config = make_state(self)
        runner.write_queue_new(self.config, {"runner_state": {"state": "paused", "reason": "x", "hold": True}, "modules": []})

    def run_held(self):
        """跑一次 cmd_run，回傳退出碼與 stderr 全文。

        @return (退出碼, stderr 文字)
        """
        # STEP 01: 捕捉輸出後執行
        # 捕捉 stderr 的緩衝
        err = io.StringIO()
        with contextlib.redirect_stderr(err), quiet():
            # cmd_run 的退出碼
            code = runner.cmd_run(self.config, argparse.Namespace(max_modules=1))
        return code, err.getvalue()


class StartupRotationTest(HeldRunHarness):
    """T1.1／T1.11：run 取鎖後輪替；輪替失敗記事件、印 stderr，run 照常往下走。"""

    def test_startup_rotation_archives_current(self):
        """T1.1（先紅）：current 超過 user 門檻 → 封存成 000001、位元組完全相同；之後的事件進新的 current。

        修正前：run 從不輪替，current 無限長大。

        @return None
        """
        # STEP 01: 一筆真事件就超過真門檻
        with quiet():
            runner.log_event(self.config, None, "filler", detail="x" * USER_MAX_BYTES)
        with open(log_path(self.config), "rb") as handle:
            # 輪替前 current 的位元組
            before = handle.read()
        # STEP 02: 跑、驗封存檔與新 current
        # cmd_run 的退出碼
        code, _err = self.run_held()
        self.assertEqual(code, runner.EXIT_PAUSED)
        # 第一號封存檔的路徑
        archive = log_path(self.config, archive_name(FIRST_ARCHIVE))
        self.assertTrue(os.path.exists(archive), os.listdir(self.config["state_dir"]))
        with open(archive, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(event_names(log_path(self.config)), ["log_rotated", "hold_active"])

    def test_rename_failure_does_not_stop_run(self):
        """T1.11：改名拋 OSError → 不中斷 run（照樣走到 hold 檢查）、記 log_rotate_failed、stderr 寫明；current 原地不動。

        @return None
        """
        # STEP 01: 超過門檻、改名注定失敗
        patch_threshold(self)
        fill_current(self.config, SMALL_MAX_BYTES)
        # current 的路徑
        path = log_path(self.config)
        with mock.patch.object(os, "rename", failing_for(os.rename, path, RENAME_ERROR)):
            # cmd_run 的退出碼與 stderr
            code, err = self.run_held()
        # STEP 02: run 照常、沒有封存檔、事件與 stderr
        self.assertEqual(code, runner.EXIT_PAUSED)
        self.assertEqual(archive_names_in(self.config), [])
        self.assertEqual(event_names(path)[-2:], ["log_rotate_failed", "hold_active"])
        self.assertIn(RENAME_ERROR, err)
        self.assertIn(RENAME_ERROR, json.dumps(read_events(path)[-2]["detail"], ensure_ascii=False))

    def test_repeated_rotation_failure_is_logged_once(self):
        """輪替持續失敗（同一個錯誤）時，同一個行程只記一筆 log_rotate_failed、只印一次 stderr；輪替成功過之後再失敗會再記。

        修正前每個輪替點（主迴圈每輪開頭）都記一筆、印一次，run 連跑好幾天時事件紀錄被同一句錯誤灌滿。

        @return None
        """
        # STEP 01: 超過門檻、改名注定失敗，同一份設定連續幾個輪替點
        patch_threshold(self)
        fill_current(self.config, SMALL_MAX_BYTES)
        # current 的路徑
        path = log_path(self.config)
        # 輪替失敗期間的 stderr
        err = io.StringIO()
        with mock.patch.object(os, "rename", failing_for(os.rename, path, RENAME_ERROR)), contextlib.redirect_stderr(err):
            for _round in range(REPEATED_FAILURES):
                runner.rotate_runner_log(self.config)
        # STEP 02: 只記一筆、stderr 只一次
        self.assertEqual(event_names(path).count("log_rotate_failed"), 1)
        self.assertEqual(err.getvalue().count(RENAME_ERROR), 1)
        # STEP 03: 改名恢復 → 輪替成功；新 current 再超過門檻、再失敗，會再記一筆
        with quiet():
            self.assertTrue(runner.rotate_runner_log(self.config).rotated)
            fill_current(self.config, SMALL_MAX_BYTES)
            with mock.patch.object(os, "rename", failing_for(os.rename, path, RENAME_ERROR)):
                runner.rotate_runner_log(self.config)
        self.assertEqual(event_names(path).count("log_rotate_failed"), 1)

    def test_listdir_failure_does_not_rename(self):
        """T1.11：列目錄失敗 → 不改名（不當成沒有封存檔從 1 號重編：序號倒退，讀取順序就錯了），記 log_rotate_failed。

        對照組：已有 000003（真的封存檔），1 號是空的——列目錄失敗若被當成「沒有封存檔」，就會改名成 000001。

        @return None
        """
        # STEP 01: 既有 3 號封存檔、current 超過門檻、列狀態目錄注定失敗
        patch_threshold(self)
        with quiet():
            runner.log_event(self.config, None, "old")
        archive_current(self.config, EXISTING_ARCHIVE)
        fill_current(self.config, SMALL_MAX_BYTES)
        with mock.patch.object(os, "listdir", failing_for(os.listdir, self.config["state_dir"], LISTDIR_ERROR)):
            # cmd_run 的退出碼與 stderr
            code, err = self.run_held()
        # STEP 02: 沒改名、事件與 stderr
        self.assertEqual(code, runner.EXIT_PAUSED)
        self.assertEqual(archive_names_in(self.config), [archive_name(EXISTING_ARCHIVE)])
        self.assertEqual(event_names(log_path(self.config))[-2:], ["log_rotate_failed", "hold_active"])
        self.assertIn(LISTDIR_ERROR, err)

    def test_exhausted_sequence_does_not_rename(self):
        """六位數序號用完（已有 999999）：不改名成對不上檔名格式的 1000000（那一份從此讀不到也刪不掉），記 log_rotate_failed。

        @return None
        """
        # STEP 01: 最後一號已存在、current 超過門檻
        patch_threshold(self)
        with quiet():
            runner.log_event(self.config, None, "old")
        archive_current(self.config, LAST_ARCHIVE_NUMBER)
        fill_current(self.config, SMALL_MAX_BYTES)
        # cmd_run 的退出碼
        code, _err = self.run_held()
        # STEP 02: 狀態目錄只有 current 與那一份
        self.assertEqual(code, runner.EXIT_PAUSED)
        self.assertEqual(
            sorted(name for name in os.listdir(self.config["state_dir"]) if name.startswith("runner.log")),
            [archive_name(LAST_ARCHIVE_NUMBER), CURRENT_NAME],
        )
        self.assertIn("log_rotate_failed", event_names(log_path(self.config)))


class OtherSubcommandsDoNotRotateTest(unittest.TestCase):
    """T1.12：unblock（--runner 與 entry）、release 在 current 超過門檻時只追加、不輪替。"""

    def setUp(self):
        """current 超過門檻；queue 有一個 failed entry 與一個 opened 斷點。

        @return None
        """
        # STEP 01: 狀態目錄、門檻、queue
        patch_threshold(self)
        # runner 設定
        self.config = make_state(self)
        runner.write_queue_new(
            self.config,
            {
                "runner_state": {"state": "idle"},
                "modules": [{"id": "e1", "status": "failed"}],
                "checkpoints": [{"id": "cp1", "status": "opened"}],
            },
        )
        fill_current(self.config, SMALL_MAX_BYTES)

    def test_unblock_and_release_only_append(self):
        """三個子命令都成功、事件都寫進 current，沒有任何封存檔；對照組：同一個 current 交給輪替確實會封存。

        @return None
        """
        # STEP 01: 三個子命令（輸出不是受測對象）
        # 各子命令與參數
        calls = [
            (runner.cmd_unblock, argparse.Namespace(integration_tip=False, runner=True, entry_id=None)),
            (runner.cmd_unblock, argparse.Namespace(integration_tip=False, runner=False, entry_id="e1")),
            (runner.cmd_release, argparse.Namespace(checkpoint_id="cp1")),
        ]
        for command, args in calls:
            with quiet():
                self.assertEqual(command(self.config, args), runner.EXIT_OK)
        # STEP 02: 沒有輪替、事件在 current
        self.assertEqual(archive_names_in(self.config), [])
        self.assertEqual(event_names(log_path(self.config))[-3:], ["runner_unblocked", "entry_unblocked", "checkpoint_released"])
        # STEP 03: 對照組：這個 current 本來就該被輪替
        with quiet():
            self.assertTrue(runner.rotate_runner_log(self.config).rotated)
        self.assertEqual(archive_names_in(self.config), [archive_name(FIRST_ARCHIVE)])


class LoopRotationTest(BrakeHarness):
    """主迴圈每輪開頭輪替：一個模組做完、下一輪開頭（max_modules 檢查之前）就輪替。"""

    def test_rotates_at_start_of_next_loop(self):
        """第一輪 CLI 寫了一筆超過門檻的大事件 → 第二輪開頭輪替：那一輪的事件全在 000001，新 current 以 log_rotated 開頭。

        啟動時 current 還沒到門檻（不在啟動那次輪替），所以封存檔只可能是主迴圈輪替出來的。

        @return None
        """
        # STEP 01: 門檻、CLI 期間寫一筆大事件
        patch_threshold(self)
        self.on_cli = lambda config, entry: runner.log_event(config, entry["id"], "big_marker", detail="x" * BIG_EVENT_CHARS)
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        # STEP 02: 恰好一份封存檔（先驗存在再讀），內容是第一輪的事件；新 current 以 log_rotated 開頭
        self.assertEqual(archive_names_in(self.base_config), [archive_name(FIRST_ARCHIVE)])
        # 第一號封存檔的事件名稱
        archived = event_names(log_path(self.base_config, archive_name(FIRST_ARCHIVE)))
        self.assertIn("module_started", archived)
        self.assertIn("big_marker", archived)
        # 新 current 的事件名稱
        current = event_names(log_path(self.base_config))
        self.assertEqual(current[0], "log_rotated")
        self.assertIn("max_modules_reached", current)


class PruneAndThresholdTest(unittest.TestCase):
    """T1.2：只保留最新 KEEP 份、序號遞增、不碰長得像的檔；門檻是「達到」；參數是 user 拍板的值。"""

    def setUp(self):
        """空狀態目錄、放好長得像封存檔的其他檔（門檻由各測試自己設：參數測試要看沒 patch 過的值）。

        @return None
        """
        # STEP 01: 狀態目錄
        # runner 設定
        self.config = make_state(self)
        # STEP 02: 其他檔
        for name, content in FOREIGN_FILES.items():
            with open(log_path(self.config, name), "wb") as handle:
                handle.write(content)

    def test_keeps_newest_and_leaves_foreign_files(self):
        """KEEP+2 次輪替：每次都是下一個序號；最後只剩最新 KEEP 份，各自是自己那一代的事件；其他檔位元組不變。

        @return None
        """
        # STEP 01: 門檻 2KB；每一代先寫一筆代號事件再填滿、輪替
        patch_threshold(self)
        for generation in range(FIRST_ARCHIVE, PRUNE_ROUNDS + 1):
            with quiet():
                runner.log_event(self.config, None, "generation", detail={"n": generation})
            fill_current(self.config, SMALL_MAX_BYTES)
            with quiet():
                # 這一次輪替的結果
                result = runner.rotate_runner_log(self.config)
            self.assertTrue(result.rotated, result)
            self.assertEqual(result.archive, archive_name(generation))
        # STEP 02: 只剩最新 KEEP 份，內容對得上代號
        # 預期留下的序號
        kept = list(range(PRUNE_ROUNDS - USER_KEEP + 1, PRUNE_ROUNDS + 1))
        self.assertEqual(archive_names_in(self.config), [archive_name(number) for number in kept])
        for number in kept:
            # 這一份裡的代號事件
            generations = [r["detail"]["n"] for r in read_events(log_path(self.config, archive_name(number))) if r["event"] == "generation"]
            self.assertEqual(generations, [number])
        # STEP 03: 其他檔不動
        for name, content in FOREIGN_FILES.items():
            with open(log_path(self.config, name), "rb") as handle:
                self.assertEqual(handle.read(), content, name)

    def test_threshold_is_reached_not_exceeded(self):
        """門檻是「達到」：大小剛好等於門檻就輪替，少一個位元組不輪替；常數是 user 拍板的 5 MB、保留 5 份。

        @return None
        """
        # STEP 01: 參數
        # 受測模組
        event_log = load_event_log()
        self.assertEqual((event_log.MAX_BYTES, event_log.KEEP), (USER_MAX_BYTES, USER_KEEP))
        # STEP 02: 門檻比大小多 1 → 不輪替；等於大小 → 輪替
        with quiet():
            runner.log_event(self.config, None, "one")
        # current 的大小
        size = os.path.getsize(log_path(self.config))
        with mock.patch.object(event_log, "MAX_BYTES", size + 1):
            self.assertFalse(event_log.rotate_if_needed(self.config["state_dir"]).rotated)
        with mock.patch.object(event_log, "MAX_BYTES", size):
            self.assertTrue(event_log.rotate_if_needed(self.config["state_dir"]).rotated)


class ConcurrentAppendTest(unittest.TestCase):
    """T1.10：別的子命令在改名前開好 current、改名後才寫：那一行落在封存檔，跨檔讀得到，一行不少。"""

    def test_write_through_fd_opened_before_rename_is_kept(self):
        """子行程開檔 → 輪替 → 新事件 → 子行程寫：前後三批都讀得到。

        @return None
        """
        # STEP 01: 門檻、改名前的事件
        # 受測模組
        event_log = load_event_log()
        patch_threshold(self)
        # runner 設定
        config = make_state(self)
        fill_current(config, SMALL_MAX_BYTES)
        # 改名前 current 裡的事件數
        before_count = len(read_events(log_path(config)))
        # STEP 02: 子行程開檔（等它說 opened），輪替、寫新事件，再放它寫
        # 在改名前開好檔的子行程
        child = subprocess.Popen(
            [sys.executable, "-B", "-c", APPEND_AFTER_RENAME_SCENARIO, log_path(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "opened")
        with quiet():
            self.assertTrue(runner.rotate_runner_log(config).rotated)
            runner.log_event(config, None, "after_rotation")
        child.communicate("go\n", timeout=CHILD_TIMEOUT_SECONDS)
        self.assertEqual(child.returncode, 0)
        # STEP 03: 子行程那一行落在封存檔；跨檔讀到全部：改名前的、log_rotated、改名後的、子行程的
        # 跨檔讀到的事件（由舊到新）與讀不到的來源
        records, unreadable =event_log.read_chronological(config["state_dir"])
        # 讀到的事件名稱
        names = [record.get("event") for record in records]
        self.assertEqual(unreadable, [])
        self.assertEqual(event_names(log_path(config, archive_name(FIRST_ARCHIVE)))[-1], "late_writer")
        self.assertEqual(names.count("filler"), before_count)
        self.assertEqual(sorted(names[before_count:]), sorted(LATE_EVENTS), names)


if __name__ == "__main__":
    unittest.main()
