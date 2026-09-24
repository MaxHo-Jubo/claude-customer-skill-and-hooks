"""runner.py 1.1.1 review 修復的回歸測試——process group 收尾與停止訊號（SIGTERM／SIGHUP 轉例外、關鍵區間延後訊號、cmd_run 各出口）。

由原 test_review_fixes.py 依主題拆出（1.1.2 第六批，測試內容逐字搬移；之後依 review 補過註解，並因 config 改為必填而明寫
config=None，斷言未變）；共用的 fixture 與小工具在 review_fixtures.py。
每一組對應一個 review 確認過的缺陷。外部狀態一律用真的：行程與 process group、flock、
git（bare 遠端＋工作 repo，含用 pre-receive hook 造出來的推送失敗）、一支會留紀錄的假 gh。
mock 只用在三種地方：
(1) 測試裡造不出來的事件——斷電（只驗 fsync／replace 的呼叫順序）、訊號剛好落在某一行；
(2) 注入失敗——R15 原檔讀取失敗、合併失敗、合併當下 entry 被人從 queue 移除；
(3) 隔離與受測行為無關的副作用——通知、進度報表、診斷包、crash 流程。

執行方式（在 skill 根目錄）：
    python3 -B -m unittest discover -s helpers/tests -v
只跑這個檔：
    python3 -B -m unittest discover -s helpers/tests -p test_process_shutdown.py -v

`-B` 與下方的 `sys.dont_write_bytecode` 是為了不在 skill 目錄留下 __pycache__。
"""

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    SCENARIO_TIMEOUT_SECONDS,
    GRANDCHILD_EXIT_WAIT_SECONDS,
    GRANDCHILD_SLEEP_SECONDS,
    TEST_TERM_GRACE_SECONDS,
    ZOMBIE_SETTLE_SECONDS,
    LEADER_EXITS_FIRST_SCENARIO,
    ESCAPED_PROCESS_SCENARIO,
    TERM_IGNORER_SCENARIO,
    SECOND_SIGNAL_DURING_CLEANUP_SCENARIO,
    SIGNAL_AFTER_POPEN_SCENARIO,
    REAL_SIGNAL_SCENARIO,
    is_alive,
    wait_until_gone,
    kill_pid_in_file,
    read_pid_file,
)


class TerminateProcessGroupTest(unittest.TestCase):
    """C1：process group 的收尾不能因為主行程先退出就卡住或漏殺孫行程。"""

    def test_leader_exits_first_grandchild_holds_pipe(self):
        """主行程已退出（zombie）、孫行程握著 stderr pipe：要在期限內返回，且孫行程被收掉。"""
        # STEP 01: 在獨立行程跑情境——修復前這裡會永久卡住，所以整段要有外層上限
        workdir = tempfile.mkdtemp(prefix="r18-c1-")
        pid_file = os.path.join(workdir, "grandchild.pid")
        self.addCleanup(self._kill_grandchild, pid_file)
        try:
            result = subprocess.run(
                [sys.executable, "-B", "-c", LEADER_EXITS_FIRST_SCENARIO, HELPERS_DIR, pid_file],
                capture_output=True,
                text=True,
                timeout=SCENARIO_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("_terminate_process_group 在 %d 秒內沒有返回（卡在沒有上限的 communicate）" % SCENARIO_TIMEOUT_SECONDS)

        # STEP 02: 情境確實走到了逾時分支並返回
        self.assertIn("RETURNED", result.stdout, result.stderr)

        # STEP 03: 孫行程必須真的被訊號收掉，不是只有 runner 自己脫身
        with open(pid_file, "r", encoding="utf-8") as handle:
            grandchild_pid = int(handle.read().strip())
        self.assertTrue(
            wait_until_gone(grandchild_pid, GRANDCHILD_EXIT_WAIT_SECONDS),
            "孫行程 %d 仍然存活：process group 沒有收到訊號" % grandchild_pid,
        )

    def test_zombie_only_group_does_not_raise(self):
        """group 裡只剩尚未收屍的主行程：macOS 的 killpg 會回 EPERM，收尾不可因此拋例外。"""
        # STEP 01: 主行程立刻結束且不收屍，group 內沒有其他成員
        process = subprocess.Popen(
            ["true"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        time.sleep(ZOMBIE_SETTLE_SECONDS)

        # STEP 02: 收尾要正常返回 (stdout, stderr)，並且把主行程收屍
        _stdout, stderr = runner._terminate_process_group(process, TEST_TERM_GRACE_SECONDS, config=None)
        self.assertEqual(stderr, "")
        self.assertEqual(process.returncode, 0)

    def test_escaped_process_holding_pipe_is_reported(self):
        """孫行程自行脫離 group 還握著 pipe：訊號送不到它，收尾不可當成一般逾時返回，要明確回報有殘留行程。"""
        # STEP 01: 在獨立行程跑情境（收屍上限調短）；脫離者的 pid 由它自己寫進檔案，收場時清掉
        workdir = tempfile.mkdtemp(prefix="r18-escaped-")
        pid_file = os.path.join(workdir, "escaped.pid")
        self.addCleanup(self._kill_grandchild, pid_file)
        result = subprocess.run(
            [sys.executable, "-B", "-c", ESCAPED_PROCESS_SCENARIO, HELPERS_DIR, pid_file],
            capture_output=True,
            text=True,
            timeout=SCENARIO_TIMEOUT_SECONDS,
            check=False,
        )

        # STEP 02: 前置條件——脫離者真的還活著（否則這個測試什麼都沒驗到）
        with open(pid_file, "r", encoding="utf-8") as handle:
            self.assertTrue(is_alive(int(handle.read().strip())), "前置條件：脫離 group 的行程應該還活著")

        # STEP 03: 必須以專屬例外回報，不是回傳一個看起來正常的 (stdout, stderr)
        self.assertEqual(result.stdout.strip(), "LEFTOVER_REPORTED", result.stderr)

    def test_term_ignorer_in_group_is_killed(self):
        """同一個 group 內有行程忽略 SIGTERM 且不握 pipe：pipe 關閉不等於 group 已空，必須升級成 SIGKILL 把它收掉。"""
        # STEP 01: 在獨立行程跑情境；忽略者的 pid 由它自己寫進檔案，收場時清掉
        workdir = tempfile.mkdtemp(prefix="r18-ignorer-")
        pid_file = os.path.join(workdir, "ignorer.pid")
        self.addCleanup(self._kill_grandchild, pid_file)
        result = subprocess.run(
            [sys.executable, "-B", "-c", TERM_IGNORER_SCENARIO, HELPERS_DIR, pid_file],
            capture_output=True,
            text=True,
            timeout=SCENARIO_TIMEOUT_SECONDS,
            check=False,
        )

        # STEP 02: 收尾正常返回（KILL 收得掉它，不需要走例外）
        self.assertEqual(result.stdout.strip(), "RETURNED", result.stderr)

        # STEP 03: 忽略者必須已經不在了
        with open(pid_file, "r", encoding="utf-8") as handle:
            ignorer_pid = int(handle.read().strip())
        self.assertTrue(
            wait_until_gone(ignorer_pid, GRANDCHILD_EXIT_WAIT_SECONDS),
            "忽略 SIGTERM 的行程 %d 仍然存活：收尾在 pipe 關閉時就返回了，沒有確認 group 已空" % ignorer_pid,
        )

    def test_group_still_populated_after_kill_raises(self):
        """SIGKILL 之後 group 仍有成員（同使用者的行程造不出這種狀態，用注入）：不可正常返回。"""
        # STEP 01: 一個收到 TERM 就結束的真行程；「group 是否已空」的檢查一律回報還沒空
        process = subprocess.Popen(
            ["sleep", str(GRANDCHILD_SLEEP_SECONDS)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        self.addCleanup(process.communicate)

        # STEP 02: 必須以 LeftoverProcessError 回報
        with mock.patch.object(runner, "_wait_group_empty", return_value=False):
            with self.assertRaises(runner.LeftoverProcessError):
                runner._terminate_process_group(process, TEST_TERM_GRACE_SECONDS, config=None)

    def test_unsignalable_group_raises(self):
        """killpg 一直回 EPERM（收屍後重試仍然如此）：group 裡有送不了訊號的活行程，不可當成「已無對象」。"""
        # STEP 01: 一個立刻結束的主行程；killpg 一律回 EPERM，重試之間的等待不真的睡
        process = subprocess.Popen(
            ["true"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        self.addCleanup(process.communicate)

        # STEP 02: 要以收尾專屬的例外往外拋（不是泛用的 PermissionError，也不是吞掉後照常返回）
        with mock.patch.object(runner.os, "killpg", side_effect=PermissionError("測試")) as killpg, \
                mock.patch.object(runner.time, "sleep"):
            with self.assertRaises(runner.UnsignalableGroupError):
                runner._terminate_process_group(process, TEST_TERM_GRACE_SECONDS, config=None)

        # STEP 03: 真的重試過——第一次加上 EPERM_RETRY_COUNT 次重試
        self.assertEqual(killpg.call_count, 1 + runner.EPERM_RETRY_COUNT)

    @staticmethod
    def _kill_grandchild(pid_file):
        """測試收場：不論斷言成敗，都不留下睡 10 分鐘的孤兒行程。

        @param pid_file 情境腳本寫入孫行程 pid 的檔案
        """
        # STEP 01: 交給模組層 helper（ShutdownDeferralTest 也用）
        kill_pid_in_file(pid_file)


class ShutdownDeferralTest(unittest.TestCase):
    """停止訊號落在兩個關鍵區間（Popen 到收尾保護生效之間、收尾本身）時要延後到區間結束，不能留下活的 CLI 行程。

    兩個情境都在獨立行程跑：要真的裝 handler、真的送訊號，不能污染測試行程自己的 handler。
    """

    def _run_scenario(self, script, *extra_args):
        """跑一個情境腳本，回傳 (stdout, stderr)。

        @param script 情境腳本原始碼
        @param extra_args 接在 helpers 目錄之後的 argv
        @return (stdout 去頭尾, stderr)
        """
        # STEP 01: 獨立行程
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, HELPERS_DIR] + list(extra_args),
            capture_output=True,
            text=True,
            timeout=SCENARIO_TIMEOUT_SECONDS,
            check=False,
        )
        return result.stdout.strip(), result.stderr

    def test_second_signal_during_cleanup_is_deferred(self):
        """收尾期間第二次 SIGTERM：收尾照樣把忽略 SIGTERM 的行程 KILL 掉，然後才把訊號當 ShutdownSignal 拋出。"""
        # STEP 01: 情境；忽略者 pid 由它自己寫檔，收場清掉
        workdir = tempfile.mkdtemp(prefix="r18-defer-")
        pid_file = os.path.join(workdir, "ignorer.pid")
        self.addCleanup(kill_pid_in_file, pid_file)
        stdout, stderr = self._run_scenario(SECOND_SIGNAL_DURING_CLEANUP_SCENARIO, pid_file)

        # STEP 02: 訊號沒有被吞掉——收尾完成後仍以 ShutdownSignal 往外傳
        self.assertEqual(stdout, "SHUTDOWN", stderr)

        # STEP 03: 但忽略者必須已經被收掉（修正前：第二個訊號從收尾中途跳出，它還活著）
        ignorer_pid = read_pid_file(pid_file)
        self.assertTrue(
            wait_until_gone(ignorer_pid, GRANDCHILD_EXIT_WAIT_SECONDS),
            "收尾被第二個訊號打斷，忽略 SIGTERM 的行程 %d 仍然存活" % ignorer_pid,
        )

    def test_signal_after_popen_still_cleans_up(self):
        """訊號落在 Popen 內部（子行程已建立、建構子未返回）：call_claude 要先收掉剛啟動的子行程，再讓 ShutdownSignal 往外傳。"""
        # STEP 01: 情境；子行程 pid 由假 Popen 寫檔，收場清掉
        workdir = tempfile.mkdtemp(prefix="r18-popen-")
        pid_file = os.path.join(workdir, "child.pid")
        self.addCleanup(kill_pid_in_file, pid_file)
        stdout, stderr = self._run_scenario(SIGNAL_AFTER_POPEN_SCENARIO, pid_file, workdir)

        # STEP 02: 訊號仍然往外傳
        self.assertEqual(stdout, "SHUTDOWN", stderr)

        # STEP 03: 子行程必須已經不在（修正前：例外直接離開 call_claude，子行程沒人管）
        child_pid = read_pid_file(pid_file)
        self.assertTrue(
            wait_until_gone(child_pid, GRANDCHILD_EXIT_WAIT_SECONDS),
            "訊號落在 Popen 之後，子行程 %d 沒有被收尾就被放著" % child_pid,
        )

    def test_signal_when_popen_fails_is_not_swallowed(self):
        """Popen 失敗（CLI 不存在）當下收到停止訊號：要拋 ShutdownSignal，不能回一個「CLI 失敗」結果讓 runner 繼續。"""
        # STEP 01: 假 Popen 模擬「啟動期間收到訊號、然後啟動失敗」（直接呼叫 handler，不真的裝訊號）
        def failing_popen(*_args, **_kwargs):
            """先觸發 handler 再以 OSError 失敗。

            @return 不會返回
            @raises OSError 一律拋出（模擬 CLI 執行檔不存在）
            """
            # STEP 01: 模擬訊號落在啟動期間，再以啟動失敗結束
            runner.shutdown_signal_handler(signal.SIGTERM, None)
            raise OSError("no such file")

        state_dir = tempfile.mkdtemp(prefix="r18-popen-fail-")
        os.makedirs(os.path.join(state_dir, "sessions"))
        config = {"state_dir": state_dir, "repo_dir": state_dir, "claude_config_dir": None, "module_timeout_min": 1}

        # STEP 02: 訊號要往外傳，而且區間狀態要清乾淨
        with mock.patch.object(runner, "build_claude_command", return_value=["x"]), \
                mock.patch.object(subprocess, "Popen", failing_popen):
            raised = None
            try:
                result = runner.call_claude(config, {"id": "e1"}, 1, False)
            except BaseException as exc:  # pylint: disable=broad-except
                raised = exc
                result = None
        self.assertIsInstance(raised, runner.ShutdownSignal, "訊號被吞掉，call_claude 回了 %r" % result)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_deferral_records_first_signal_and_raises_once_on_normal_exit(self):
        """區間內不論收到幾次訊號都只記第一次、不拋；正常離開區間時拋一次 ShutdownSignal。"""
        # STEP 01: 直接呼叫 handler（不真的裝訊號，避免污染測試行程）；區間內兩次呼叫都不能拋
        reached_end_of_block = False
        with self.assertRaises(runner.ShutdownSignal) as raised:
            with runner.ShutdownDeferral(config=None):
                runner.shutdown_signal_handler(signal.SIGTERM, None)
                runner.shutdown_signal_handler(signal.SIGHUP, None)
                reached_end_of_block = True
        self.assertTrue(reached_end_of_block, "handler 在區間內就拋了")
        # STEP 02: 拋的是第一個訊號；狀態已清乾淨，之後的訊號恢復立即拋出
        self.assertIn("15", str(raised.exception))
        self.assertIsNone(runner._PENDING_SIGNUM)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        with self.assertRaises(runner.ShutdownSignal):
            runner.shutdown_signal_handler(signal.SIGTERM, None)

    def test_explicit_end_follows_constructor_flag(self):
        """不帶參數的 end() 要照建構子的 raise_on_normal_exit 決定，不能用自己的預設值蓋掉建構時的宣告。"""
        # STEP 01: 建構時宣告不拋，區間內收到訊號，顯式 end()
        deferral = runner.ShutdownDeferral(raise_on_normal_exit=False, config=None)
        raised = None
        with deferral:
            runner.shutdown_signal_handler(signal.SIGTERM, None)
            try:
                deferral.end()
            except BaseException as exc:  # pylint: disable=broad-except
                raised = exc
        # STEP 02: 沒拋、狀態乾淨
        self.assertIsNone(raised, "end() 無視建構子宣告拋了: %r" % raised)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_nested_inner_exception_leaves_decision_to_outer(self):
        """巢狀區間：內層以例外離開只減深度，訊號留給最外層依它自己的離開方式決定（外層正常離開就拋）。"""
        # STEP 01: 內層拋 RuntimeError 被外層接住吞掉，外層正常離開
        raised = None
        try:
            with runner.ShutdownDeferral(config=None):
                try:
                    with runner.ShutdownDeferral(config=None):
                        runner.shutdown_signal_handler(signal.SIGTERM, None)
                        raise RuntimeError("內層")
                except RuntimeError:
                    pass
        except BaseException as exc:  # pylint: disable=broad-except
            raised = exc
        # STEP 02: 訊號在最外層拋出
        self.assertIsInstance(raised, runner.ShutdownSignal, "最外層正常離開卻沒拋延後的訊號: %r" % raised)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_deferral_keeps_body_exception_and_drops_pending_signal(self):
        """區間以例外結束（例如收尾回報殘留行程）：原例外優先往外傳，延後的訊號不覆蓋它、也不留到下次。"""
        # STEP 01: 區間內收到訊號後拋出收尾例外；接 BaseException 是為了把「拋錯型別」也變成斷言失敗
        raised = None
        try:
            with runner.ShutdownDeferral(config=None):
                runner.shutdown_signal_handler(signal.SIGTERM, None)
                raise runner.LeftoverProcessError("測試")
        except BaseException as exc:  # pylint: disable=broad-except
            raised = exc
        self.assertIsInstance(raised, runner.LeftoverProcessError, "延後的訊號覆蓋了收尾例外: %r" % raised)
        # STEP 02: 沒有殘留的 pending 狀態
        self.assertIsNone(runner._PENDING_SIGNUM)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)


class RunShutdownTest(unittest.TestCase):
    """cmd_run：handler 裝好之後的整段都要有出口；沒持鎖時不得走會寫 queue 的 crash 流程。"""

    def setUp(self):
        """最小 config；不在測試行程裡真的安裝 signal handler。"""
        # STEP 01: 狀態目錄
        self.state_dir = tempfile.mkdtemp(prefix="r18-run-")
        self.config = {"state_dir": self.state_dir, "notify_channel": "none"}
        self.args = argparse.Namespace()
        # STEP 02: 隔離 handler 安裝（會改掉測試行程自己的訊號處理）
        patcher = mock.patch.object(runner, "install_shutdown_handlers")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _assert_lock_free(self):
        """確認 runner.lock 沒有被持有（同一行程另開一個 fd 取鎖，flock 以 open file description 為單位）。"""
        # STEP 01: 取得到就立刻放掉
        probe = runner.ProcessLock(runner.state_path(self.config, "runner.lock"))
        self.assertTrue(probe.acquire(), "runner.lock 仍被持有：cmd_run 沒有釋放鎖")
        probe.release()

    def test_shutdown_during_handler_install_exits_ok(self):
        """安裝函式呼叫期間就冒出 ShutdownSignal：同樣要走 EXIT_OK 出口（驗的是 try 有涵蓋安裝那一行）。

        真實時機是「第一個 handler 已裝好、函式還沒返回」；這裡不重現那個中間狀態，只把安裝
        函式整個換成一呼叫就拋，足以驗證 try 的涵蓋範圍。
        """
        # STEP 01: 覆寫 setUp 的隔離，讓安裝動作本身拋出 ShutdownSignal
        with mock.patch.object(runner, "install_shutdown_handlers", side_effect=runner.ShutdownSignal("測試")):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_OK)

    def test_real_signals_are_converted(self):
        """真的裝 handler、真的送訊號：SIGTERM／SIGHUP／SIGINT 都要被轉成 ShutdownSignal（在獨立行程裡跑）。

        SIGINT 也要走同一個 handler：沒接管的話 Python 內建的 KeyboardInterrupt 不受關鍵區間延後，連按兩次
        Ctrl-C 的第二次會打斷收尾；接管之後（第七批）關鍵區間內的第二次 Ctrl-C 一樣只被記下、延後。
        """
        # STEP 01: 三個訊號各跑一次；handler 沒註冊的話行程會直接被訊號終止（SIGINT 則是 KeyboardInterrupt），stdout 是空的
        for signal_name in ("SIGTERM", "SIGHUP", "SIGINT"):
            with self.subTest(signal=signal_name):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", REAL_SIGNAL_SCENARIO, HELPERS_DIR, signal_name],
                    capture_output=True,
                    text=True,
                    timeout=SCENARIO_TIMEOUT_SECONDS,
                    check=False,
                )
                self.assertEqual(result.stdout.strip(), "CONVERTED", result.stderr)

    def test_shutdown_before_lock_exits_ok(self):
        """取鎖之前就收到停止訊號：安靜地以 EXIT_OK 結束，不是讓例外逃出去。"""
        # STEP 01: 訊號落在必填檢查那一行
        with mock.patch.object(runner, "require_config", side_effect=runner.ShutdownSignal("測試")):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_OK)

    def test_shutdown_after_lock_exits_ok_and_releases(self):
        """取鎖之後、主迴圈之前收到停止訊號：EXIT_OK，而且鎖有放掉。"""
        # STEP 01: 訊號落在初始 lockfile hash 那一行（取鎖之後的第一個動作）
        with mock.patch.object(runner, "require_config", return_value=True), \
                mock.patch.object(runner, "lockfile_hash", side_effect=runner.ShutdownSignal("測試")):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_OK)
        # STEP 02: 鎖已釋放
        self._assert_lock_free()

    def test_error_before_lock_skips_crash_flow(self):
        """取鎖之前的例外：原樣往外拋，不得呼叫會寫 queue 的 handle_runner_crash。"""
        # STEP 01: 例外發生在還沒持鎖的階段
        with mock.patch.object(runner, "require_config", side_effect=RuntimeError("測試")), \
                mock.patch.object(runner, "handle_runner_crash") as crash:
            with self.assertRaises(RuntimeError):
                runner.cmd_run(self.config, self.args)
        # STEP 02: crash 流程沒被碰
        crash.assert_not_called()

    def test_error_after_lock_goes_to_crash_flow(self):
        """取鎖之後的例外（含初始 lockfile hash）：走 crash 流程，而且鎖有放掉。"""
        # STEP 01: 嚴格版 hash 讀取失敗
        with mock.patch.object(runner, "require_config", return_value=True), \
                mock.patch.object(runner, "lockfile_hash", side_effect=RuntimeError("測試")), \
                mock.patch.object(runner, "handle_runner_crash", return_value=runner.EXIT_PAUSED) as crash:
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)
        # STEP 02: crash 流程被呼叫一次，鎖已釋放
        crash.assert_called_once()
        self._assert_lock_free()


if __name__ == "__main__":
    unittest.main()
