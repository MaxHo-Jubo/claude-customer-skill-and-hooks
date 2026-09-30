"""runner.py 1.1.2 第七批項目 1 的回歸測試（讀取端）：輪替之後，讀事件紀錄的地方跨 current＋封存檔讀，行為與輪替前一致。

讀取點：重啟對帳（last_cli_outcome，另以這一輪的 started_at 界定）、暫停去重第三層（last_paused_reason_from_log）、
診斷包沿用（previous_pause_bundle）、診斷包的事件切片（diagnostics.read_runner_events：freeze_entry 的 attempt 起全部、
freeze_runner 的尾端 200 筆）。另驗讀取失敗不等於空（讀不到的封存檔、列不出目錄）與讀取順序（先讀完 current 才列封存檔）。

「事件在封存檔」一律是真的封存檔：用與輪替相同的改名（archive_current）造出來，不經過受測的輪替程式，所以先紅的
T1.3／T1.5 實作之前以 AssertionError 失敗；較新的檔裡放非目標事件（別的 entry、別的原因、通知投遞紀錄），讀取端要越過它們。
共用小工具從 test_log_rotation 匯入（只匯入函式與常數，不匯入 TestCase）。chmod 000 的情境在 root 下 skip（root 讀得到）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 480; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_log_rotation_reads.py -v
"""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import diagnostics  # noqa: E402  pylint: disable=wrong-import-position
import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    ENTRY_ID,
    INTEGRATION_BRANCH,
    build_fixture,
    queue_entry,
    remote_tip,
    start_patches,
)
from test_log_rotation import (  # noqa: E402  pylint: disable=wrong-import-position
    FIRST_ARCHIVE,
    LISTDIR_ERROR,
    RENAME_ERROR,
    archive_current,
    archive_name,
    event_names,
    failing_for,
    load_event_log,
    log_path,
    make_state,
    patch_threshold,
    quiet,
)
from test_reconcile import (  # noqa: E402  pylint: disable=wrong-import-position
    CRASHED_ROUND_COST,
    CRASHED_SESSION_ID,
    PRIOR_COST_TOTAL,
    RestartHarness,
    SimulatedKill,
    publish,
)
from test_review_112c import last_paused_event, simulate_restart  # noqa: E402  pylint: disable=wrong-import-position

# 早於任何一輪 started_at 的時間戳（造「更舊一輪」的事件；runner.now_iso 是 UTC 秒精度字串）
OLD_TS = "2000-01-01T00:00:00+00:00"
# 比 FIRST_ARCHIVE 新一號的封存序號
SECOND_ARCHIVE = FIRST_ARCHIVE + 1
# 呼叫序號：第一輪（更早的那一輪）
FIRST_ATTEMPT = 1
# 呼叫序號：第二輪（被中斷的那一輪）
SECOND_ATTEMPT = 2
# 非目標事件：別的 entry 的 id
OTHER_ENTRY_ID = "e9"
# 非目標事件：別的 entry 那一輪的 session id
OTHER_SESSION_ID = "session-other-entry"
# 非目標事件：別的 entry 那一輪的花費
OTHER_COST = 9.0
# 更早一輪（花費已記過）的 session id
PRIOR_SESSION_ID = "session-prior-round"
# 更早一輪（已記過）的花費
PRIOR_ROUND_COST = 0.3
# T1.9 被中斷那一輪的 session id（事件在讀不到的封存檔裡）
INTERRUPTED_SESSION_ID = "session-interrupted"
# T1.9 被中斷那一輪的花費
INTERRUPTED_COST = 0.7
# T1.7 封存檔的事件數（比診斷包尾端筆數多）
ARCHIVE_EVENTS = 300
# T1.7 current 的事件數（比尾端筆數少，尾端要跨進封存檔）
CURRENT_EVENTS = 50
# T1.7 長 current 的事件數（單檔就超過尾端筆數，封存檔不該被開）
LONG_CURRENT_EVENTS = 250
# 讀取順序測試每個檔的事件數
ORDER_EVENTS = 3
# 真的壞位元組（不合法的 UTF-8＋不是 JSON）：queue_corrupt
BAD_QUEUE_BYTES = b"\xff\xfe{not json"
# queue_corrupt 暫停的細節（原因相同即可，細節不參與去重）
CORRUPT_DETAIL = "queue.json 解析失敗"
# integration_dirty 暫停的細節
DIRTY_DETAIL = "工作樹有未提交的變更"
# chmod 000 之後還原成的權限（擁有者讀寫）
RESTORE_MODE = stat.S_IRUSR | stat.S_IWUSR


def skip_if_root(test_case):
    """root 讀得到 chmod 000 的檔，「讀不到」的情境造不出來，skip。

    @param test_case 目前的 TestCase
    @return None
    """
    # STEP 01: 看有效 uid
    if os.geteuid() == 0:
        test_case.skipTest("root 讀得到 chmod 000 的檔")


def make_unreadable(test_case, path):
    """把檔案改成 chmod 000，測試結束時還原。

    @param test_case 目前的 TestCase（登記還原）
    @param path 檔案路徑
    @return None
    """
    # STEP 01: 改權限並登記還原
    os.chmod(path, 0)
    test_case.addCleanup(os.chmod, path, RESTORE_MODE)


def log_non_target(config):
    """在較新的檔裡放非目標事件：別的 entry 的 cli_outcome、一筆 runner 級事件（讀取端要越過它們）。

    @param config runner 設定
    @return None
    """
    # STEP 01: 兩筆
    runner.log_event(config, OTHER_ENTRY_ID, "cli_outcome", attempt=FIRST_ATTEMPT, session_id=OTHER_SESSION_ID, cost_usd=OTHER_COST)
    runner.log_event(config, None, "reconcile_skipped", detail={"reason": "entry_match", "detail": "non-target"})


def log_ticks(config, source, count):
    """寫 count 筆帶來源與序號的事件（驗時序用）。

    @param config runner 設定
    @param source 來源標記（寫進 detail.src）
    @param count 筆數
    @return None
    """
    # STEP 01: 逐筆寫
    with quiet():
        for number in range(count):
            runner.log_event(config, None, "tick", detail={"src": source, "n": number})


def ticks(records):
    """事件清單裡 tick 事件的 (來源, 序號)；None（讀不到的行或檔）略過。

    @param records 事件 dict（或 None）清單
    @return (來源, 序號) 清單
    """
    # STEP 01: 篩選
    return [(r["detail"]["src"], r["detail"]["n"]) for r in records if r is not None and r.get("event") == "tick"]


def set_entry_fields(config, **fields):
    """把欄位寫進 queue 裡測試用 entry（ENTRY_ID）。

    @param config runner 設定
    @param fields 要寫的欄位
    @return None
    """
    # STEP 01: 一次寫入
    runner.mutate_queue(config, lambda queue: runner.find_entry(queue, ENTRY_ID).update(fields))


class ReconcileAcrossArchiveTest(RestartHarness):
    """T1.3／T1.4：重啟對帳補記花費與 session id 跨檔找被中斷那一輪的 cli_outcome，並以這一輪的 started_at 界定。"""

    def test_interrupted_round_outcome_in_archive_is_recorded(self):
        """T1.3（先紅）：cli_outcome → 輪替 → 非目標事件；對帳補記的花費是中斷那一輪的一次、session id 是那一輪的。

        修正前：只讀 current，找不到那一輪的 cli_outcome，花費少記、session id 退回舊值。

        @return None
        """
        # STEP 01: 中斷、輪替、較新的檔裡放非目標事件、重啟
        publish(self.fixture, kill_before_done=True)
        archive_current(self.config, FIRST_ARCHIVE)
        log_non_target(self.config)
        self.restart()
        # STEP 02: done、那一輪的 session id 與花費
        queue, entry = queue_entry(self.fixture)
        self.assertEqual(entry["status"], "done", queue["runner_state"])
        self.assertEqual(entry["last_session_id"], CRASHED_SESSION_ID)
        self.assertAlmostEqual(entry["cost_usd_total"], PRIOR_COST_TOTAL + CRASHED_ROUND_COST)

    def test_older_round_outcome_in_archive_is_not_recorded(self):
        """T1.4：封存檔裡只有更早一輪（早於 started_at、花費已記過）的 cli_outcome，中斷那一輪的缺席 → 花費與 session id 都不動。

        沒有 started_at 界定的話會把更早那一輪的花費再記一次。

        @return None
        """
        # STEP 01: 更早一輪的 cli_outcome（時間早於這一輪）進封存檔
        set_entry_fields(self.config, last_session_id=PRIOR_SESSION_ID)
        with mock.patch.object(runner, "now_iso", return_value=OLD_TS):
            runner.log_event(self.config, ENTRY_ID, "cli_outcome", attempt=FIRST_ATTEMPT, session_id=PRIOR_SESSION_ID, cost_usd=PRIOR_ROUND_COST)
        archive_current(self.config, FIRST_ARCHIVE)
        # STEP 02: 這一輪開始、發佈段推送後被殺（沒有這一輪的 cli_outcome）、非目標事件、重啟
        set_entry_fields(self.config, started_at=runner.now_iso())
        with mock.patch.object(runner, "finish_done_entry", side_effect=SimulatedKill):
            with contextlib.suppress(SimulatedKill):
                runner.publish_verified_entry(self.config, self.fixture["entry"], {"structured": {}, "session_id": None, "cost": None}, FIRST_ATTEMPT)
        self.assertEqual(remote_tip(self.fixture, INTEGRATION_BRANCH), self.fixture["entry_sha"], "前置條件：整合分支應已推上去")
        log_non_target(self.config)
        self.restart()
        # STEP 03: done，但花費與 session id 不動
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["last_session_id"], PRIOR_SESSION_ID)
        self.assertAlmostEqual(entry["cost_usd_total"], PRIOR_COST_TOTAL)


class PauseAcrossArchiveTest(unittest.TestCase):
    """T1.5／T1.6：去重第三層與診斷包沿用跨檔找上一次的 paused 事件；啟動輪替自己記的事件不擋去重。"""

    def setUp(self):
        """通知與進度報表隔離；真的 git 環境與狀態目錄。

        @return None
        """
        # STEP 01: 隔離與 fixture
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-logrot-pause-"))
        # runner 設定
        self.config = self.fixture["config"]

    def _previous_process_paused_on_corrupt_queue(self):
        """上一個行程：queue.json 是真的壞位元組 → queue_corrupt 暫停，接著 notify() 記一筆投遞紀錄（notify 被換掉，照形狀補記）。

        @return None
        """
        # STEP 01: 弄壞 queue、暫停、投遞紀錄
        with open(runner.queue_file(self.config), "wb") as handle:
            handle.write(BAD_QUEUE_BYTES)
        runner.enter_paused(self.config, "queue_corrupt", CORRUPT_DETAIL)
        runner.log_event(self.config, None, "notify", detail={"event": "paused", "out": ""})
        self.mocks["notify"].reset_mock()

    def assert_repeated_without_notice(self):
        """再一次 queue_corrupt 暫停：判定為重複、不通知。

        @return None
        """
        # STEP 01: 暫停、驗
        runner.enter_paused(self.config, "queue_corrupt", CORRUPT_DETAIL)
        self.assertFalse(self.mocks["notify"].called, self.mocks["notify"].call_args_list)
        self.assertTrue(last_paused_event(self.config)["repeated"])

    def test_third_layer_finds_pause_in_archive(self):
        """T1.5（先紅）：上一次的 paused＋通知紀錄在封存檔、較新的 current 只有投遞紀錄 → 判定為重複、不通知。

        修正前：只讀 current，找不到 paused，每 300 秒重啟一次就通知一次。

        @return None
        """
        # STEP 01: 上一行程、輪替、較新的檔裡只有非狀態事件
        self._previous_process_paused_on_corrupt_queue()
        archive_current(self.config, FIRST_ARCHIVE)
        runner.log_event(self.config, None, "notify_skipped", detail="找不到 notify.sh")
        # STEP 02: 重複、不通知
        self.assert_repeated_without_notice()

    def test_third_layer_skips_log_rotated(self):
        """真的啟動輪替：新 current 第一筆是 log_rotated，它不是狀態事件，去重要越過它到封存檔。

        @return None
        """
        # STEP 01: 上一行程；門檻設成 current 目前的大小（剛好達到），真的輪替
        self._previous_process_paused_on_corrupt_queue()
        patch_threshold(self, os.path.getsize(log_path(self.config)))
        with quiet():
            self.assertTrue(runner.rotate_runner_log(self.config).rotated)
        # STEP 02: 重複、不通知
        self.assert_repeated_without_notice()

    def test_third_layer_skips_log_rotate_failed(self):
        """啟動輪替失敗：current 最新一筆是 log_rotate_failed，它不是狀態事件，去重要越過它。

        @return None
        """
        # STEP 01: 上一行程；輪替時改名失敗
        self._previous_process_paused_on_corrupt_queue()
        patch_threshold(self, os.path.getsize(log_path(self.config)))
        # current 的路徑
        path = log_path(self.config)
        with mock.patch.object(os, "rename", failing_for(os.rename, path, RENAME_ERROR)), quiet():
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertFalse(runner.rotate_runner_log(self.config).rotated)
        self.assertEqual(event_names(path)[-1], "log_rotate_failed")
        # STEP 02: 重複、不通知
        self.assert_repeated_without_notice()

    def test_bundle_in_archive_is_reused(self):
        """T1.6：上一次同原因暫停的診斷包記在封存檔的 paused 事件裡 → 沿用、不凍結新包。

        @return None
        """
        # STEP 01: 第一次暫停（凍結一包）、輪替、較新的檔裡放別的原因的 paused
        runner.enter_paused(self.config, "integration_dirty", DIRTY_DETAIL)
        # 第一次暫停的事件
        first = last_paused_event(self.config)
        archive_current(self.config, FIRST_ARCHIVE)
        runner.log_event(self.config, None, "paused", detail={"reason": "disk_low", "signature": None, "diagnostics": "diagnostics/x"})
        # STEP 02: 重啟、同原因再一次
        simulate_restart(self.config)
        runner.enter_paused(self.config, "integration_dirty", DIRTY_DETAIL)
        # 第二次暫停的事件
        second = last_paused_event(self.config)
        # STEP 03: 沿用同一包、沒有新目錄
        self.assertTrue(second["repeated"])
        self.assertTrue(second["diagnostics_reused"], second)
        self.assertEqual(second["diagnostics"], first["diagnostics"])
        # 診斷包目錄
        directory = os.path.join(self.config["state_dir"], "diagnostics")
        self.assertEqual(len([name for name in os.listdir(directory) if name.startswith("runner-")]), 1)


class DiagnosticsAcrossArchiveTest(unittest.TestCase):
    """T1.7／T1.8：診斷包的事件切片跨檔；尾端讀取是惰性的；讀不到的檔寫進 SUMMARY、不宣稱沒有事件。"""

    def setUp(self):
        """空狀態目錄。

        @return None
        """
        # STEP 01: 狀態目錄
        # runner 設定
        self.config = make_state(self)

    def freeze_runner(self):
        """凍結一包 runner 級診斷包，回傳包內的事件與 SUMMARY 全文。

        @return (事件 dict 清單, SUMMARY 文字)
        """
        # STEP 01: 凍結、讀回
        # 診斷包目錄
        bundle = diagnostics.freeze_runner(self.config["state_dir"], "test_reason", "detail", {}, [])
        return self._bundle_contents(bundle)

    @staticmethod
    def _bundle_contents(bundle):
        """讀診斷包內的事件切片與 SUMMARY。

        @param bundle 診斷包目錄
        @return (事件 dict 清單, SUMMARY 文字)
        """
        # STEP 01: 兩個檔
        with open(os.path.join(bundle, diagnostics.SUMMARY_NAME), "r", encoding="utf-8") as handle:
            # SUMMARY 全文
            summary = handle.read()
        # 事件切片檔
        events_path = os.path.join(bundle, diagnostics.RUNNER_EVENTS_COPY_NAME)
        with open(events_path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()], summary

    def test_runner_tail_spans_archive_in_order(self):
        """T1.7：封存 300＋current 50 → 剛好最近 200 筆、時序正確（封存檔的最後 150 筆接 current 的 50 筆）。

        @return None
        """
        # STEP 01: 兩個檔的事件
        log_ticks(self.config, "archive", ARCHIVE_EVENTS)
        archive_current(self.config, FIRST_ARCHIVE)
        log_ticks(self.config, "current", CURRENT_EVENTS)
        # STEP 02: 尾端
        # 包內的事件
        records, _summary = self.freeze_runner()
        # 尾端裡來自封存檔的筆數
        from_archive = diagnostics.RUNNER_EVENTS_TAIL - CURRENT_EVENTS
        # 預期的 (來源, 序號)
        expected = [("archive", n) for n in range(ARCHIVE_EVENTS - from_archive, ARCHIVE_EVENTS)]
        expected += [("current", n) for n in range(CURRENT_EVENTS)]
        self.assertEqual(ticks(records), expected)

    def test_tail_within_current_does_not_open_archive(self):
        """T1.7：current 250＋封存 chmod 000 → 成功、只取 current 的最後 200 筆、SUMMARY 沒有讀不到的註記（惰性：根本沒開封存檔）。

        @return None
        """
        # STEP 01: 讀不到的封存檔、夠長的 current
        skip_if_root(self)
        log_ticks(self.config, "archive", CURRENT_EVENTS)
        archive_current(self.config, FIRST_ARCHIVE)
        make_unreadable(self, log_path(self.config, archive_name(FIRST_ARCHIVE)))
        log_ticks(self.config, "current", LONG_CURRENT_EVENTS)
        # STEP 02: 驗
        # 包內的事件與 SUMMARY
        records, summary = self.freeze_runner()
        # 預期的 (來源, 序號)
        expected = [("current", n) for n in range(LONG_CURRENT_EVENTS - diagnostics.RUNNER_EVENTS_TAIL, LONG_CURRENT_EVENTS)]
        self.assertEqual(ticks(records), expected)
        self.assertNotIn(archive_name(FIRST_ARCHIVE), summary)

    def test_unreadable_archive_is_reported_in_summary(self):
        """對照組：current 只有 50 筆、封存 chmod 000 → 包裡是讀得到的 50 筆，SUMMARY 寫明哪個檔讀不到。

        @return None
        """
        # STEP 01: 讀不到的封存檔、短 current
        skip_if_root(self)
        log_ticks(self.config, "archive", CURRENT_EVENTS)
        archive_current(self.config, FIRST_ARCHIVE)
        make_unreadable(self, log_path(self.config, archive_name(FIRST_ARCHIVE)))
        log_ticks(self.config, "current", CURRENT_EVENTS)
        # STEP 02: 驗
        # 包內的事件與 SUMMARY
        records, summary = self.freeze_runner()
        self.assertEqual(ticks(records), [("current", n) for n in range(CURRENT_EVENTS)])
        self.assertIn(archive_name(FIRST_ARCHIVE), summary)

    def _entry_history(self):
        """entry 級切片的事件：attempt 開始（module_started）在封存檔、之後的在 current，兩邊都有非目標事件。

        @return None
        """
        # STEP 01: 封存檔：attempt 之前的 runner 級事件（不該進包）、module_started、attempt 之後的 runner 級事件
        with quiet():
            with mock.patch.object(runner, "now_iso", return_value=OLD_TS):
                runner.log_event(self.config, None, "before_attempt")
            runner.log_event(self.config, ENTRY_ID, "module_started", attempt=FIRST_ATTEMPT)
            runner.log_event(self.config, None, "archived_runner_event")
            archive_current(self.config, FIRST_ARCHIVE)
            # STEP 02: current：這個 entry 的、別的 entry 的（不該進包）、runner 級的
            runner.log_event(self.config, ENTRY_ID, "cli_outcome", attempt=FIRST_ATTEMPT)
            runner.log_event(self.config, OTHER_ENTRY_ID, "cli_outcome", attempt=FIRST_ATTEMPT)
            runner.log_event(self.config, None, "current_runner_event")

    def test_entry_bundle_uses_attempt_start_in_archive(self):
        """T1.8：freeze_entry 的 since 取自封存檔裡的 module_started；包裡有 since 之後兩個檔的 runner 級事件。

        @return None
        """
        # STEP 01: 事件、凍結
        self._entry_history()
        # 包內的事件
        records, _summary = self._bundle_contents(
            diagnostics.freeze_entry(self.config["state_dir"], {"id": ENTRY_ID}, FIRST_ATTEMPT, "test_reason", "detail", {}, [])
        )
        # STEP 02: 恰好這四筆、時序正確
        self.assertEqual(
            [record["event"] for record in records], ["module_started", "archived_runner_event", "cli_outcome", "current_runner_event"]
        )

    def test_entry_summary_reports_unreadable_archive(self):
        """freeze_entry 遇到讀不到的封存檔：SUMMARY 寫明那個檔（不宣稱沒有事件）。

        @return None
        """
        # STEP 01: 事件、封存檔讀不到、凍結
        skip_if_root(self)
        self._entry_history()
        make_unreadable(self, log_path(self.config, archive_name(FIRST_ARCHIVE)))
        # 包內的 SUMMARY
        _records, summary = self._bundle_contents(
            diagnostics.freeze_entry(self.config["state_dir"], {"id": ENTRY_ID}, FIRST_ATTEMPT, "test_reason", "detail", {}, [])
        )
        # STEP 02: 註記
        self.assertIn(archive_name(FIRST_ARCHIVE), summary)

    def test_entry_summary_reports_archive_unreadable_only_on_first_read(self):
        """freeze_entry 讀兩次事件紀錄（先找 attempt 起點、再切片）：只有第一次讀不到封存檔時，SUMMARY 照樣寫明那個檔。

        第一次讀不到會讓 module_started 找不到、起點缺失，runner 級事件整段不進切片；只收第二次的讀取錯誤的話，
        切片少了一段、SUMMARY 卻沒有「事件不完整」的註記（codex 第七批 silent-failure）。

        @return None
        """
        # STEP 01: 事件；封存檔只在 freeze_entry 的第一次讀取時讀不到
        skip_if_root(self)
        self._entry_history()
        # 封存檔路徑
        path = log_path(self.config, archive_name(FIRST_ARCHIVE))
        # 被替換前的真讀取函式
        real_read = diagnostics.event_log.read_chronological
        # 讀取次數
        calls = []

        def unreadable_on_first_read(*args, **kwargs):
            """第一次讀取時封存檔 chmod 000，讀完還原；之後照常。

            @param args 原樣轉交
            @param kwargs 原樣轉交
            @return 真讀取函式的回傳值
            """
            # STEP 01: 只有第一次改權限
            calls.append(len(calls) + 1)
            if len(calls) > 1:
                return real_read(*args, **kwargs)
            os.chmod(path, 0)
            try:
                return real_read(*args, **kwargs)
            finally:
                os.chmod(path, RESTORE_MODE)

        with mock.patch.object(diagnostics.event_log, "read_chronological", unreadable_on_first_read):
            # 包內的 SUMMARY
            _records, summary = self._bundle_contents(
                diagnostics.freeze_entry(self.config["state_dir"], {"id": ENTRY_ID}, FIRST_ATTEMPT, "test_reason", "detail", {}, [])
            )
        # STEP 02: 前置條件（確實讀了兩次）與註記
        self.assertEqual(len(calls), 2)
        self.assertIn(archive_name(FIRST_ARCHIVE), summary)


class UnreadableArchiveTest(unittest.TestCase):
    """T1.9：讀取失敗不等於空——讀不到的封存檔、列不出的目錄都不能被當成「沒有事件」。"""

    def setUp(self):
        """空狀態目錄。

        @return None
        """
        # STEP 01: 狀態目錄
        # runner 設定
        self.config = make_state(self)

    def _paused_in_archive(self):
        """封存 1：上一次 queue_corrupt 的 paused＋投遞紀錄；封存 2 與 current：只有投遞紀錄。回傳封存 2 的路徑。

        封存 2 讀得到時，去重要穿過它（只有投遞紀錄）找到封存 1 的 paused；讀不到時它裡面可能有任何狀態事件，不能穿過。

        @return 封存 2 的路徑
        """
        # STEP 01: 三個檔
        with quiet():
            runner.log_event(self.config, None, "paused", detail={"reason": "queue_corrupt", "signature": None})
            runner.log_event(self.config, None, "notify", detail={"event": "paused", "out": ""})
            archive_current(self.config, FIRST_ARCHIVE)
            runner.log_event(self.config, None, "notify_failed", detail="timeout")
            archive_current(self.config, SECOND_ARCHIVE)
            runner.log_event(self.config, None, "notify_skipped", detail="找不到 notify.sh")
        # STEP 02: 對照組：讀得到時穿過封存 2、判得出上一次是 queue_corrupt
        self.assertEqual(runner.last_paused_reason_from_log(self.config), "queue_corrupt")
        return log_path(self.config, archive_name(SECOND_ARCHIVE))

    def test_dedupe_stops_at_unreadable_archive(self):
        """去重第三層：中間的封存檔讀不到 → None（判不出來就不宣稱重複），不越過它去拿更舊的 paused。

        @return None
        """
        # STEP 01: 封存 2 讀不到
        skip_if_root(self)
        make_unreadable(self, self._paused_in_archive())
        # STEP 02: 驗
        self.assertIsNone(runner.last_paused_reason_from_log(self.config))

    def test_listdir_failure_is_not_empty(self):
        """列不出狀態目錄：去重第三層 None；讀取序列在 current 之後產出 None 哨兵；read_chronological 回報讀不到。

        @return None
        """
        # STEP 01: 列目錄注定失敗
        self._paused_in_archive()
        with mock.patch.object(os, "listdir", failing_for(os.listdir, self.config["state_dir"], LISTDIR_ERROR)):
            # STEP 02: 三個讀取面
            self.assertIsNone(runner.last_paused_reason_from_log(self.config))
            # 讀取序列
            records = list(runner.log_records_newest_first(self.config))
            # 跨檔讀取回報的讀不到的來源
            _records, unreadable =load_event_log().read_chronological(self.config["state_dir"])
        self.assertEqual(records[0]["event"], "notify_skipped")
        self.assertIsNone(records[-1])
        self.assertTrue(unreadable)
        self.assertIn(LISTDIR_ERROR, " ".join(unreadable))

    def _outcomes_in_two_archives(self):
        """封存 1：更早一輪（早於 started_at）的 cli_outcome；封存 2：這一輪的 cli_outcome；current：非目標事件。

        @return (這一輪的 entry, 封存 2 的路徑)
        """
        # STEP 01: 兩個封存檔、current
        with quiet():
            with mock.patch.object(runner, "now_iso", return_value=OLD_TS):
                runner.log_event(self.config, ENTRY_ID, "cli_outcome", attempt=FIRST_ATTEMPT, session_id=PRIOR_SESSION_ID, cost_usd=PRIOR_ROUND_COST)
            archive_current(self.config, FIRST_ARCHIVE)
            # 這一輪開始的時間
            started_at = runner.now_iso()
            runner.log_event(self.config, ENTRY_ID, "cli_outcome", attempt=SECOND_ATTEMPT, session_id=INTERRUPTED_SESSION_ID, cost_usd=INTERRUPTED_COST)
            archive_current(self.config, SECOND_ARCHIVE)
            log_non_target(self.config)
        # 這一輪的 entry（queue 形狀）
        entry = {"id": ENTRY_ID, "started_at": started_at, "last_session_id": PRIOR_SESSION_ID}
        # STEP 02: 對照組：讀得到時取這一輪的
        self.assertEqual(runner.last_cli_outcome(self.config, entry), (INTERRUPTED_SESSION_ID, INTERRUPTED_COST))
        return entry, log_path(self.config, archive_name(SECOND_ARCHIVE))

    def test_cli_outcome_does_not_fall_back_to_older_round(self):
        """T1.9：這一輪的 cli_outcome 在讀不到的封存檔 → 不越過它拿更舊一輪的（花費 None、session id 維持 entry 現值）。

        @return None
        """
        # STEP 01: 封存 2 讀不到
        skip_if_root(self)
        # 這一輪的 entry、這一輪 cli_outcome 所在的封存檔
        entry, newer_archive = self._outcomes_in_two_archives()
        make_unreadable(self, newer_archive)
        # STEP 02: 兩個值都不取
        self.assertEqual(runner.last_cli_outcome(self.config, entry), (PRIOR_SESSION_ID, None))

    def test_cli_outcome_without_started_at_takes_neither(self):
        """entry 沒有 started_at（界定不了是哪一輪）：session id 與花費都不取，與找不到同一個出口。

        @return None
        """
        # STEP 01: 讀得到這一輪的事件，但 entry 沒有 started_at
        # 這一輪的 entry（下面拿掉 started_at）
        entry, _archive =self._outcomes_in_two_archives()
        # STEP 02: 兩個值都不取
        self.assertEqual(runner.last_cli_outcome(self.config, dict(entry, started_at=None)), (PRIOR_SESSION_ID, None))


class ReadOrderTest(unittest.TestCase):
    """讀取順序：先讀完 current 才列封存檔。反過來的話「列完封存檔、開 current」之間發生輪替，舊 current 改名成一個
    不在清單裡的封存檔，那一批事件整個漏掉；照現在的順序頂多重複讀到（docstring 寫明的已知限制）。"""

    def setUp(self):
        """封存 1 與 current 各三筆 tick。

        @return None
        """
        # STEP 01: 兩個檔
        # runner 設定
        self.config = make_state(self)
        log_ticks(self.config, "archive", ORDER_EVENTS)
        archive_current(self.config, FIRST_ARCHIVE)
        log_ticks(self.config, "current", ORDER_EVENTS)
        # 全部的 (來源, 序號)
        self.expected = [("archive", n) for n in range(ORDER_EVENTS)] + [("current", n) for n in range(ORDER_EVENTS)]
        # 被換掉之前的 os.listdir
        self.real_listdir = os.listdir
        # 改名是否已做過（只做一次）
        self.rotated = False

    def _rotate_once(self):
        """模擬別的行程輪替：把 current 改名成 2 號封存檔（只做一次）。

        @return None
        """
        # STEP 01: 第一次才改名
        if not self.rotated:
            archive_current(self.config, SECOND_ARCHIVE)
            self.rotated = True

    def _read_with(self, hook):
        """把 os.listdir 換成 hook 之後讀完整個序列。

        @param hook 替身 listdir
        @return 讀到的 (來源, 序號)
        """
        # STEP 01: 讀
        with mock.patch.object(os, "listdir", side_effect=hook):
            # 讀取序列
            records = list(load_event_log().iter_newest_first(self.config["state_dir"]))
        self.assertTrue(self.rotated, "前置條件：讀取途中應已發生一次改名")
        return ticks(records)

    def test_rotation_right_after_listing_loses_nothing(self):
        """列完目錄之後立刻輪替：current 已經先讀完，一筆不少、也不重複（反過來的順序會漏掉 current 那一批）。

        @return None
        """

        def listdir_then_rotate(path):
            """先列目錄、再改名。

            @param path 要列的目錄
            @return 改名之前列出的檔名
            """
            # STEP 01: 列、改名
            # 改名之前列出的檔名
            names = self.real_listdir(path)
            self._rotate_once()
            return names

        # STEP 01: 讀、驗
        self.assertEqual(sorted(self._read_with(listdir_then_rotate)), sorted(self.expected))

    def test_rotation_between_current_and_listing_loses_nothing(self):
        """讀完 current、列目錄之前輪替：剛讀過的 current 以 2 號封存檔再出現一次（重複），但一筆不少。

        @return None
        """

        def rotate_then_listdir(path):
            """先改名、再列目錄。

            @param path 要列的目錄
            @return 改名之後列出的檔名
            """
            # STEP 01: 改名、列
            self._rotate_once()
            return self.real_listdir(path)

        # STEP 01: 讀、驗（允許重複，不允許缺）
        # 讀到的 (來源, 序號)
        found = self._read_with(rotate_then_listdir)
        self.assertEqual(set(found), set(self.expected))
        self.assertGreaterEqual(len(found), len(self.expected))


if __name__ == "__main__":
    unittest.main()
