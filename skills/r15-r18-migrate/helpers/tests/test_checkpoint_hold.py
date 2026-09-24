"""runner.py 1.1.1 review 修復的回歸測試——斷點 PR、鎖定（hold）與通知（open_checkpoint 與呼叫端、hold 落盤失敗、launchd ExitTimeOut、crash 鎖定、unblock 提醒、notify.sh 長度上限）。

由原 test_review_fixes.py 依主題拆出（1.1.2 第六批，測試內容逐字搬移；之後依 review 補過註解與具名常數，斷言未變）；
共用的 fixture 與小工具在 review_fixtures.py。
每一組對應一個 review 確認過的缺陷。外部狀態一律用真的：行程與 process group、flock、
git（bare 遠端＋工作 repo，含用 pre-receive hook 造出來的推送失敗）、一支會留紀錄的假 gh。
mock 只用在三種地方：
(1) 測試裡造不出來的事件——斷電（只驗 fsync／replace 的呼叫順序）、訊號剛好落在某一行；
(2) 注入失敗——R15 原檔讀取失敗、合併失敗、合併當下 entry 被人從 queue 移除；
(3) 隔離與受測行為無關的副作用——通知、進度報表、診斷包、crash 流程。

執行方式（在 skill 根目錄）：
    python3 -B -m unittest discover -s helpers/tests -v
只跑這個檔：
    python3 -B -m unittest discover -s helpers/tests -p test_checkpoint_hold.py -v

`-B` 與下方的 `sys.dont_write_bytecode` 是為了不在 skill 目錄留下 __pycache__。
"""

import contextlib
import io
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    SCENARIO_TIMEOUT_SECONDS,
    FAKE_PR_URL,
    INTEGRATION_BRANCH,
    NON_PR_OUTPUTS,
    CHECKPOINT_ID,
    write_fake_gh,
    build_fixture,
    queue_entry,
    start_patches,
    read_plist_integer,
)

# 自動斷點的行數門檻：設到一百萬行，測試的 entry 不可能累積到，只讓模組數門檻觸發
UNREACHABLE_CHECKPOINT_LINES = 10 ** 6


class OpenCheckpointTest(unittest.TestCase):
    """斷點 PR 拿不到連結時**仍然**寫成 opened 並蓋章——這是第六批刻意還原的行為。

    第五批把它改成「沒連結就 failed、回 False」，與頁面 PR 對齊；但兩個呼叫端都靠 opened／蓋章
    運作：hard 斷點只在 True 時暫停（人工閘門消失），auto 斷點不在 queue 裡、標 failed 是空轉、
    entry 沒蓋章就會每完成一個模組再推一支 cp 分支、再開一個真的 PR（第六輪 review 用本檔的
    fixture 實跑重現）。正解是查該分支既有的 PR 沿用，那是 1.1.2 重啟對帳的一部分。
    """

    def setUp(self):
        """每個測試一組 git 環境：entry 已完成（斷點要蓋章的對象），queue 裡有一個待開的斷點。"""
        # STEP 01: fixture；斷點 PR 的 base 用整合分支即可（假 gh 不看）
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-cp-"), {"status": "done"})
        self.fixture["config"]["base_branch"] = INTEGRATION_BRANCH

        def add_checkpoint(queue):
            """加入一個 pending 的斷點（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
            @return None
            """
            # STEP 01: 斷點清單換成只有一個 pending 的 soft 斷點
            queue["checkpoints"] = [dict(runner.CHECKPOINT_FIELD_DEFAULTS, id=CHECKPOINT_ID, mode="soft", title="cp")]

        runner.mutate_queue(self.fixture["config"], add_checkpoint)
        # STEP 02: 通知與進度報表不是受測對象，但要看通知內文
        self.notify = start_patches(self, "notify", "write_progress")["notify"]

    def _checkpoint_and_entry(self):
        """重讀 queue，回傳 (斷點, entry)。"""
        # STEP 01: 驗落盤後的狀態
        queue, entry = queue_entry(self.fixture)
        return runner.find_checkpoint(queue, CHECKPOINT_ID), entry

    def test_without_pr_link_still_opens_and_stamps(self):
        """沒有 PR 連結：照樣 opened、蓋章、回 True；通知要說清楚沒有連結、請人到 GitHub 確認該分支。"""
        fixture = self.fixture
        # STEP 01: 假 gh 成功退出但印的是登入提示網址
        write_fake_gh(os.path.dirname(fixture["remote"]), fixture["remote"], NON_PR_OUTPUTS[2])

        # STEP 02: 執行
        self.assertTrue(runner.open_checkpoint(fixture["config"], CHECKPOINT_ID))

        # STEP 03: 狀態與蓋章都在，連結是空的
        checkpoint, entry = self._checkpoint_and_entry()
        self.assertEqual(checkpoint["status"], "opened")
        self.assertFalse(checkpoint.get("pr_url"))
        self.assertEqual(entry["checkpoint_id"], CHECKPOINT_ID)

        # STEP 04: 通知不可假裝有連結，而且要帶 cp 分支名讓人去查
        body = self.notify.call_args.args[3]
        self.assertIn("未回傳連結", body)
        self.assertIn("r18-migration/cp-%s" % CHECKPOINT_ID, body)

    def test_with_pr_link_opens(self):
        """對照組：有合法連結時照常開啟並蓋章——確認上一個測試的失敗不是因為 fixture 本來就開不起來。"""
        fixture = self.fixture
        # STEP 01: 預設的假 gh 會印合法連結
        self.assertTrue(runner.open_checkpoint(fixture["config"], CHECKPOINT_ID))

        # STEP 02: 斷點已開、entry 已蓋章
        checkpoint, entry = self._checkpoint_and_entry()
        self.assertEqual(checkpoint["status"], "opened")
        self.assertEqual(checkpoint["pr_url"], FAKE_PR_URL)
        self.assertEqual(entry["checkpoint_id"], CHECKPOINT_ID)


class HandleCheckpointsTest(unittest.TestCase):
    """釘住 open_checkpoint 的兩個呼叫端在「斷點 PR 拿不到連結」時的行為（第六輪 review 的 K1）。

    hard 斷點：人工閘門不可以因為拿不到連結而消失。
    auto 斷點：一次沒拿到連結只能推一支 cp 分支、開一次 PR，不能每完成一個模組就再來一輪。
    """

    def setUp(self):
        """entry 已完成的 git 環境；假 gh 成功退出但不印 PR 連結。"""
        # STEP 01: fixture；自動斷點門檻設成 1 個模組就觸發，行數門檻設到不會觸發
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-hc-"), {"status": "done"})
        self.config = self.fixture["config"]
        self.config.update({"base_branch": INTEGRATION_BRANCH, "checkpoint_max_modules": 1, "checkpoint_max_lines": UNREACHABLE_CHECKPOINT_LINES})
        _bin, self.gh_calls, _tips = write_fake_gh(
            os.path.dirname(self.fixture["remote"]), self.fixture["remote"], NON_PR_OUTPUTS[2]
        )
        # STEP 02: 通知與進度報表不是受測對象
        start_patches(self, "notify", "write_progress")

    def _gh_call_count(self):
        """假 gh 被呼叫的次數（紀錄檔一行一次；還沒被呼叫過時檔案不存在）。"""
        # STEP 01: 讀紀錄檔
        if not os.path.exists(self.gh_calls):
            return 0
        with open(self.gh_calls, encoding="utf-8") as handle:
            return len(handle.read().splitlines())

    def test_hard_checkpoint_without_link_still_pauses(self):
        """hard 斷點沒拿到連結：仍然回 (True, id)，runner 才會停下來等人放行。"""
        # STEP 01: 宣告一個 wave 0 之後的 hard 斷點
        def add_checkpoint(queue):
            """加入 pending 的 hard 斷點（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
            @return None
            """
            # STEP 01: 斷點清單換成只有一個 wave 0 之後的 hard 斷點
            queue["checkpoints"] = [
                dict(runner.CHECKPOINT_FIELD_DEFAULTS, id=CHECKPOINT_ID, mode="hard", after={"wave": 0}, title="cp")
            ]

        runner.mutate_queue(self.config, add_checkpoint)

        # STEP 02: 閘門要在
        self.assertEqual(runner.handle_checkpoints(self.config), (True, CHECKPOINT_ID))

    def test_auto_checkpoint_without_link_does_not_repeat(self):
        """auto 斷點沒拿到連結：對同一份 queue 再呼叫一次不可以再開一次 PR，而且累積的模組數已經歸零。"""
        # STEP 01: 沒有宣告的斷點，靠模組數門檻觸發；第一次會開 auto 斷點。第二次是對「第一次已經蓋過章」的
        # 同一份狀態再呼叫（沒有新模組完成）：修正前 entry 沒被蓋章，門檻仍成立，會再開一次
        self.assertEqual(runner.handle_checkpoints(self.config), (False, None))
        self.assertEqual(runner.handle_checkpoints(self.config), (False, None))

        # STEP 02: 只開過一次 PR，entry 已被第一個 auto 斷點蓋章、門檻不再成立
        self.assertEqual(self._gh_call_count(), 1)
        needed, _detail = runner.auto_checkpoint_needed(self.config, runner.load_queue(self.config))
        self.assertFalse(needed)


class EnterPausedPersistFailureTest(unittest.TestCase):
    """hold 寫不進狀態檔時，通知不可以說「已鎖定」——launchd 幾分鐘後照樣重啟，人要立刻手動停掉服務。"""

    def setUp(self):
        """狀態目錄與一份執行中的 queue；狀態寫入注入失敗。"""
        # STEP 01: 狀態目錄與 queue
        self.config = {"state_dir": tempfile.mkdtemp(prefix="r18-persist-"), "notify_channel": "none"}
        runner.ensure_state_dir(self.config)
        runner.write_queue_new(self.config, {"modules": [], "runner_state": {"state": "running"}})
        # STEP 02: 注入落盤失敗；通知只看內文
        self.notify = start_patches(self, "notify")["notify"]
        patcher = mock.patch.object(runner, "set_runner_state", side_effect=OSError("磁碟已滿"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_hold_not_persisted_is_said_plainly(self):
        """強制 hold 但落盤失敗：通知要說鎖定沒有寫進狀態檔、要人立刻停掉 launchd 服務。"""
        # STEP 01: 走 force_hold 的暫停
        exit_code = runner.enter_paused(self.config, runner.CRASH_REASON, "細節", signature="sig", force_hold=True)
        self.assertEqual(exit_code, runner.EXIT_PAUSED)

        # STEP 02: 通知內文
        body = self.notify.call_args.args[3]
        self.assertNotIn("已鎖定", body)
        self.assertIn("沒有寫進狀態檔", body)
        self.assertIn("launchctl", body)

        # STEP 03: 事件紀錄也要留下「hold 沒落盤」
        with open(os.path.join(self.config["state_dir"], "runner.log.jsonl"), encoding="utf-8") as handle:
            last_event = handle.read().splitlines()[-1]
        self.assertIn('"hold_persisted": false', last_event)


class LaunchdTemplateTest(unittest.TestCase):
    """launchd 停服務時的 SIGTERM→SIGKILL 間隔要蓋得住中斷路徑最壞的收尾時間，否則殘留行程的鎖定永遠寫不到。"""

    def test_exit_timeout_covers_worst_case_cleanup(self):
        """ExitTimeOut 必須存在，且大於「TERM 寬限＋有上限收屍＋KILL 後確認＋通知子行程上限」的總和——鎖定落盤後的那一則通知也要送得出去。"""
        # STEP 01: 讀範本
        template_path = os.path.join(os.path.dirname(HELPERS_DIR), "templates", "launchd.plist.template")
        with open(template_path, encoding="utf-8") as handle:
            exit_timeout = read_plist_integer(handle.read(), "ExitTimeOut")

        # STEP 02: 最壞收尾＝TERM 寬限期 + _reap_with_limit + KILL 之後的 _wait_group_empty + 通知子行程
        worst_case = runner.TERM_GRACE_SECONDS + 2 * runner.REAP_LIMIT_SECONDS + runner.NOTIFY_TIMEOUT_SECONDS
        self.assertIsNotNone(exit_timeout, "plist 範本缺 ExitTimeOut")
        self.assertGreater(exit_timeout, worst_case)


class CrashHoldTest(unittest.TestCase):
    """回報「CLI 的子孫行程沒收乾淨」的例外第一次出現就要鎖定 runner；其他例外維持同簽名第二次才鎖定。"""

    def setUp(self):
        """只需要狀態目錄與一份 runner 正在執行中的 queue。"""
        # STEP 01: 狀態目錄與 queue
        self.config = {"state_dir": tempfile.mkdtemp(prefix="r18-hold-"), "notify_channel": "none"}
        runner.ensure_state_dir(self.config)
        runner.write_queue_new(self.config, {"modules": [], "runner_state": {"state": "running"}})
        # STEP 02: 通知不是受測對象，但要看它的內文
        patcher = mock.patch.object(runner, "notify")
        self.notify = patcher.start()
        self.addCleanup(patcher.stop)

    def _crash_with(self, error):
        """在 except 區塊內呼叫 handle_runner_crash（它用 traceback.format_exc 取當前例外），回傳 (退出碼, runner_state)。

        @param error 要拋出的例外物件
        """
        # STEP 01: 拋出並交給 crash 流程
        try:
            raise error
        except Exception as exc:  # pylint: disable=broad-except
            exit_code = runner.handle_runner_crash(self.config, exc)
        return exit_code, runner.load_queue(self.config)["runner_state"]

    def test_leftover_process_forces_hold_on_first_occurrence(self):
        """殘留行程：launchd 會在幾分鐘後自動重啟 runner，不立刻鎖定的話它會在殘留行程還活著時又開始動 repo。"""
        # STEP 01: 兩種收尾例外各驗一次
        for error in (runner.LeftoverProcessError("測試"), runner.UnsignalableGroupError("測試")):
            with self.subTest(error=type(error).__name__):
                runner.write_queue_new(self.config, {"modules": [], "runner_state": {"state": "running"}})
                exit_code, state = self._crash_with(error)

                # STEP 02: 第一次就鎖定，通知要告訴人為什麼鎖、怎麼解除（不可套用「重複發生」那句）
                self.assertEqual(exit_code, runner.EXIT_PAUSED)
                self.assertTrue(state["hold"])
                body = self.notify.call_args.args[3]
                self.assertIn("必須人工確認後才能繼續", body)
                self.assertNotIn("重複發生", body)
                self.assertIn("unblock --runner", body)

    def test_signal_during_crash_flow_does_not_skip_hold(self):
        """crash 流程凍結診斷包期間再收到停止訊號：hold 仍要落盤、回 EXIT_PAUSED，訊號不能從 except handler 裡跳出去放鎖。"""
        # STEP 01: 凍結診斷包期間觸發 handler（直接呼叫模擬訊號，不真的裝訊號）
        # 被替換前的 freeze_runner_bundle，替身觸發訊號後轉給它
        real_freeze = runner.freeze_runner_bundle

        def freeze_with_signal(*args, **kwargs):
            """先觸發停止訊號的 handler，再照常凍結。

            @param args 原樣轉給真的 freeze_runner_bundle
            @param kwargs 原樣轉給真的 freeze_runner_bundle
            @return 真的 freeze_runner_bundle 的回傳值
            """
            # STEP 01: 模擬訊號落在凍結期間，再照常凍結
            runner.shutdown_signal_handler(signal.SIGTERM, None)
            return real_freeze(*args, **kwargs)

        with mock.patch.object(runner, "freeze_runner_bundle", freeze_with_signal):
            raised = None
            try:
                exit_code, state = self._crash_with(runner.LeftoverProcessError("測試"))
            except BaseException as exc:  # pylint: disable=broad-except
                raised, exit_code, state = exc, None, runner.load_queue(self.config)["runner_state"]

        # STEP 02: 沒有例外跳出、hold 已落盤、區間狀態清乾淨
        self.assertIsNone(raised, "訊號從 crash 流程跳出: %r" % raised)
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self.assertTrue(state.get("hold"))
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_signal_during_forced_hold_persist_does_not_skip_hold(self):
        """force_hold 的暫停（不經 crash 流程）在凍結證據期間再收到停止訊號：hold 仍要落盤、回 EXIT_PAUSED。

        不然訊號落在「本機整合分支已退回」與「hold 寫進 queue」之間，外層當正常停止回 EXIT_OK；重啟後
        本機已對齊、前置作業偵測不到原本的不符，entry 放回 pending 繼續跑——宣稱必須人工確認的鎖定被整個繞過。
        """
        # STEP 01: 凍結 runner 級診斷包期間觸發 handler
        # 被替換前的 freeze_runner_bundle，替身觸發訊號後轉給它
        real_freeze = runner.freeze_runner_bundle

        def freeze_with_signal(*args, **kwargs):
            """先觸發停止訊號的 handler，再照常凍結。

            @param args 原樣轉給真的 freeze_runner_bundle
            @param kwargs 原樣轉給真的 freeze_runner_bundle
            @return 真的 freeze_runner_bundle 的回傳值
            """
            # STEP 01: 模擬訊號落在凍結期間，再照常凍結
            runner.shutdown_signal_handler(signal.SIGTERM, None)
            return real_freeze(*args, **kwargs)

        with mock.patch.object(runner, "freeze_runner_bundle", freeze_with_signal):
            raised = None
            try:
                exit_code = runner.enter_paused(self.config, "integration_diverged", "模擬 mismatch", force_hold=True)
            except BaseException as exc:  # pylint: disable=broad-except
                raised, exit_code = exc, None

        # STEP 02: 沒有例外跳出、hold 已落盤、區間狀態清乾淨
        state = runner.load_queue(self.config)["runner_state"]
        self.assertIsNone(raised, "訊號從 enter_paused 跳出: %r" % raised)
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self.assertTrue(state.get("hold"))
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_ordinary_crash_does_not_hold_on_first_occurrence(self):
        """對照組：一般例外第一次只暫停、不鎖定——確認不是所有 crash 都被改成立刻鎖定。"""
        # STEP 01: 一般的 RuntimeError
        exit_code, state = self._crash_with(RuntimeError("測試"))
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self.assertFalse(state["hold"])


class UnblockReminderTest(unittest.TestCase):
    """兩個 unblock 子命令各只清一半狀態：另一半還在時要提醒，不能只印「下次啟動會繼續」。

    鎖定（hold）配 integration 類的暫停原因時，`--integration-tip` 清得掉暫停原因、清不掉 hold，
    只跑它 runner 下次啟動仍在 pre-flight 之前靜默退出；`--runner` 清得掉 hold、清不掉暫停原因，
    只跑它的話遠端整合分支若有變動，下次啟動會再次暫停而且（同原因重複）不通知。
    """

    def setUp(self):
        """真的 git 環境（--integration-tip 會 fetch），runner 狀態設成「本機領先」的鎖定暫停。"""
        # STEP 01: fixture＋狀態
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-unblock-"))

        def lock_on_local_ahead(queue):
            """runner_state 改成鎖定中的 integration 類暫停（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
            @return None
            """
            # STEP 01: 換成本機領先的鎖定暫停
            queue["runner_state"] = {"state": "paused", "reason": runner.LOCAL_AHEAD_REASON, "hold": True}

        runner.mutate_queue(self.fixture["config"], lock_on_local_ahead)

    def _run_capturing_stdout(self, function):
        """執行 unblock 函式並收下它印到 stdout 的文字。

        @param function 要執行的 unblock 函式（只吃 config）
        @return (退出碼, stdout 全文)
        """
        # STEP 01: 導向 stdout
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = function(self.fixture["config"])
        return code, buffer.getvalue()

    def test_integration_tip_clears_reason_but_warns_about_hold(self):
        """--integration-tip：本機領先這個原因要清得掉；hold 還在就要說還要 --runner，不能說下次啟動會繼續。"""
        # STEP 01: 執行
        code, output = self._run_capturing_stdout(runner.unblock_integration_tip)
        self.assertEqual(code, runner.EXIT_OK, output)

        # STEP 02: 暫停原因清了、hold 沒動、提醒有印
        queue = runner.load_queue(self.fixture["config"])
        self.assertEqual(queue["runner_state"]["state"], "idle")
        self.assertTrue(queue["runner_state"]["hold"])
        self.assertIn("unblock --runner", output)
        self.assertNotIn("下次啟動會從這個 SHA 繼續", output)

    def test_runner_clears_hold_but_warns_about_integration_reason(self):
        """--runner：hold 清掉；integration 類的暫停原因還在就要提醒本機對齊後跑 --integration-tip。"""
        # STEP 01: 執行
        code, output = self._run_capturing_stdout(runner.unblock_runner)
        self.assertEqual(code, runner.EXIT_OK, output)

        # STEP 02: hold 清了、原因沒動、提醒有印；不能先印「下次啟動會續跑」（本機沒對齊就會再鎖，那是假話）
        queue = runner.load_queue(self.fixture["config"])
        self.assertFalse(queue["runner_state"]["hold"])
        self.assertEqual(queue["runner_state"]["reason"], runner.LOCAL_AHEAD_REASON)
        self.assertIn("unblock --integration-tip", output)
        self.assertNotIn("下次啟動會續跑", output)


class NotifyScriptTest(unittest.TestCase):
    """notify.sh 的長度上限要以字元計，不是 byte：bash 3.2 在 locale 不是 UTF-8 時（沒設、或 C／POSIX）
    `${#text}`／`${text:0:N}` 都是 byte 語意，300 的上限對中文只剩約 100 個字。runner 用 CPython 啟動這支
    腳本時 PEP 538 已經帶入 `LC_CTYPE=C.UTF-8`，那條路徑本來就是字元語意；這裡驗的是手動執行、或非 Python
    呼叫端（launchd 的環境沒有 LANG）下的防禦性 locale 守衛。
    """

    def test_length_is_counted_in_characters_without_utf8_locale(self):
        """沒有任何 locale 變數（env -i）、有設但不是 UTF-8（LANG=C）、高優先序是 C 而低優先序是 UTF-8（LC_ALL=C LANG=en_US.UTF-8，有效值是 C）、或名字寫 utf8 但系統沒有這個 locale（bash 安靜退回 C）：載入 notify.sh 的開頭之後，中文字串的長度要等於字元數。判斷用實測（一個中文字算出來是不是 1），不靠名字。

        只 source 到 locale 段的結尾標記；腳本後面會讀參數、動狀態檔，不能整支跑。
        """
        # STEP 01: 兩種環境各跑一次
        script = os.path.join(HELPERS_DIR, "notify.sh")
        probe = 'eval "$(sed -n "1,/^# ---- locale-end/p" "$0")"; t="本機整合分支領先遠端"; printf "%s" "${#t}"'
        for env_name, extra_env in (
            ("empty", []),
            ("LANG=C", ["LANG=C"]),
            ("LC_ALL=C 蓋過 LANG=UTF-8", ["LC_ALL=C", "LANG=en_US.UTF-8"]),
            ("LANG=en_US.utf8（glibc 寫法，這台沒有這個 locale）", ["LANG=en_US.utf8"]),
        ):
            with self.subTest(env=env_name):
                result = subprocess.run(
                    ["env", "-i"] + extra_env + ["/bin/bash", "-c", probe, script],
                    capture_output=True,
                    text=True,
                    timeout=SCENARIO_TIMEOUT_SECONDS,
                    check=False,
                )
                # STEP 02: 10 個中文字就是 10，不是 30
                self.assertEqual(result.stdout.strip(), "10", result.stderr)


if __name__ == "__main__":
    unittest.main()
