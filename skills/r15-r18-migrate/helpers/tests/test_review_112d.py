"""runner.py 1.1.2 第四批的回歸測試。

  * unblock --runner 解除帶簽名的鎖定（或 ff-merge 後 HEAD 不符那種以 integration_diverged 鎖定的）時，暫停原因一起清掉：
    留著的話之後同原因、不帶簽名的暫停（遠端 tip 不符）和它完全相同，被當成重複而永遠不通知。
  * run 在 pre-flight 之前檢查 queue 裡的斷點 id（與 import-inventory 同一個判斷）：舊版匯入的壞 id 不能等到前置作業組
    log 名稱才以 ValueError 冒出來。
  * 判定為重複的暫停不再凍結新的診斷包，沿用上一包（launchd 每 300 秒重啟一次，一個週末會累積數百個目錄）。

fixture 從 review_fixtures、小工具從 test_review_112c 匯入（只匯入函式與常數，不匯入 TestCase，免得被重複收集）。
新的暫停原因與訊息寫成字面值，理由同 test_review_112c：修正前常數不存在，引用會以 AttributeError 而不是 AssertionError 失敗。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import argparse
import contextlib
import io
import os
import shutil
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
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    INTEGRATION_BRANCH,
    build_fixture,
    reject_entry_branch_push,
    run_git,
    start_patches,
)
from test_review_112c import last_paused_event, simulate_restart  # noqa: E402  pylint: disable=wrong-import-position

# 斷點 id 不合規時 run 的暫停原因（runner.CHECKPOINT_ID_INVALID_REASON 的值）
CHECKPOINT_ID_INVALID = "checkpoint_id_invalid"
# 發佈段交給收尾的 CLI 判讀結果
OUTCOME = {"structured": {}, "session_id": "s", "cost": 0.1}


def unblock_quietly(config):
    """執行 unblock --runner，吞掉它印到 stdout 的說明，回傳那段文字。

    @param config runner 設定
    @return unblock_runner 印出的文字
    """
    # STEP 01: 捕捉輸出
    # 捕捉 stdout 的緩衝
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        runner.unblock_runner(config)
    return captured.getvalue()


def tip_mismatch_pause(config):
    """記錄的 tip 改成別的值，跑前置作業拿到 integration_diverged，照 cmd_run 的方式進暫停。

    @param config runner 設定
    @return 這次的 paused 事件 detail
    """
    # STEP 01: 造出遠端 tip 與記錄值不同
    run_git(config["repo_dir"], "checkout", INTEGRATION_BRANCH)
    runner.set_integration_tip(config, "0" * 40)
    # 前置作業的結果：是否通過、暫停原因、細節
    ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
    if ok or reason != "integration_diverged":
        # STEP 01.01: 前置條件不成立就讓測試直接失敗
        raise AssertionError("前置條件不成立：前置作業應回 integration_diverged，實際 %s %s" % (reason, detail))
    # STEP 02: 暫停
    runner.enter_paused(config, reason, detail)
    return last_paused_event(config)


class UnblockRunnerClearsSignedPauseTest(unittest.TestCase):
    """unblock --runner 之後，同原因、不帶簽名的暫停必須是新事件（通知）。"""

    def setUp(self):
        """通知與進度報表隔離。

        @return None
        """
        # STEP 01: 隔離與 fixture
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-unblock-"))
        # runner 設定
        self.config = self.fixture["config"]

    def _restart_and_tip_mismatch(self):
        """模擬重啟、然後遠端 tip 不符；回傳那次暫停的事件。

        @return paused 事件 detail
        """
        # STEP 01: 重啟、清通知紀錄、暫停
        simulate_restart(self.config)
        self.mocks["notify"].reset_mock()
        return tip_mismatch_pause(self.config)

    def test_push_failure_hold_then_unblock_then_tip_mismatch_notifies(self):
        """推送失敗兩次 → 鎖定 → unblock --runner → 遠端 tip 不符：repeated=False、有通知。

        @return None
        """
        # STEP 01: 推送失敗兩次（中間重啟）→ 鎖定
        reject_entry_branch_push(self.fixture["remote"], branch=INTEGRATION_BRANCH)
        runner.publish_verified_entry(self.config, self.fixture["entry"], OUTCOME, 1)
        simulate_restart(self.config)
        runner.publish_verified_entry(self.config, self.fixture["entry"], OUTCOME, 2)
        self.assertTrue(runner.load_queue(self.config)["runner_state"]["hold"])
        os.unlink(os.path.join(self.fixture["remote"], "hooks", "pre-receive"))
        # STEP 02: 解除後遠端 tip 不符
        unblock_quietly(self.config)
        # 遠端 tip 不符那次的事件
        event = self._restart_and_tip_mismatch()
        self.assertFalse(event["repeated"])
        self.assertTrue(self.mocks["notify"].called)

    def test_merge_mismatch_hold_then_unblock_then_tip_mismatch_notifies(self):
        """ff-merge 後 HEAD 不符那種鎖定（integration_diverged、無簽名、第一次就鎖）→ unblock --runner → 遠端 tip 不符：要通知。

        @return None
        """
        # STEP 01: 以 HOLD_MERGE_RESULTS 的方式鎖定
        runner.enter_paused(self.config, "integration_diverged", "HEAD 不符", force_hold=True)
        unblock_quietly(self.config)
        # STEP 02: 遠端 tip 不符
        # 遠端 tip 不符那次的事件
        event = self._restart_and_tip_mismatch()
        self.assertFalse(event["repeated"])
        self.assertTrue(self.mocks["notify"].called)

    def test_local_ahead_reason_is_kept(self):
        """integration_local_ahead 的鎖定解除後，暫停原因留著，而且提醒對齊本機與 --integration-tip（行為不變）。

        @return None
        """
        # STEP 01: 鎖定、解除
        runner.enter_paused(self.config, runner.LOCAL_AHEAD_REASON, "本機領先", force_hold=True)
        # unblock 印出的說明
        text = unblock_quietly(self.config)
        # STEP 02: 原因留著、提醒還在、hold 已清
        # 解除後落盤的 runner_state
        state = runner.load_queue(self.config)["runner_state"]
        self.assertEqual((state["state"], state["reason"], state["hold"]), ("paused", runner.LOCAL_AHEAD_REASON, False))
        self.assertIn("unblock --integration-tip", text)


class RunChecksCheckpointIdsTest(unittest.TestCase):
    """run 在 pre-flight 之前擋下 queue 裡不合規的斷點 id，不等前置作業組 log 名稱時才以 ValueError 冒出來。"""

    def _run_with_checkpoint(self, checkpoint_id):
        """queue 放一個 opened 斷點後跑 cmd_run（外部依賴全部隔離，enter_paused 換成假件）。

        @param checkpoint_id 斷點 id
        @return (cmd_run 的退出碼, mock 表)
        """
        # STEP 01: fixture 與斷點
        # 測試用的 git 環境與狀態目錄（entry 回 pending，跟重啟時一樣）
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-cpid-"), {"status": "pending"})
        # runner 設定
        config = fixture["config"]
        config.update({"circuit_breaker_n": 3, "notify_daily_digest": "09:00", "base_branch": "master"})

        def add_checkpoint(queue):
            """mutate_queue 用：登記一個 opened、soft 的斷點（就地修改）。

            @param queue 整份 queue
            @return None
            """
            # STEP 01: 登記
            queue["checkpoints"] = [
                {"id": checkpoint_id, "status": "opened", "mode": "soft", "branch": "r18-migration/cp-x", "after": {"wave": 0}}
            ]
            queue["runner_state"] = {"state": "idle"}

        runner.mutate_queue(config, add_checkpoint)
        # STEP 02: 隔離後執行
        # 被換掉的 runner 函式：名稱 → mock
        mocks = start_patches(
            self,
            "install_shutdown_handlers",
            "require_config",
            "lockfile_hash",
            "preflight",
            "environment_fingerprint",
            "notify",
            "maybe_daily_digest",
            "quota_snapshot",
            "quota_blocks_start",
            "handle_checkpoints",
            "enter_paused",
            "process_one_entry",
            "handle_runner_crash",
        )
        mocks["require_config"].return_value = True
        mocks["lockfile_hash"].return_value = None
        mocks["preflight"].return_value = 1
        mocks["enter_paused"].return_value = runner.EXIT_PAUSED
        mocks["handle_runner_crash"].return_value = runner.EXIT_PAUSED
        # cmd_run 的退出碼
        code = runner.cmd_run(config, argparse.Namespace(max_modules=1))
        return code, mocks

    def test_invalid_checkpoint_id_stops_before_preflight(self):
        """opened 斷點 id 是 `cp--1`：pre-flight（含認證 smoke 的 CLI 呼叫）之前就暫停，細節有 id 與 queue.json。

        @return None
        """
        # STEP 01: 執行
        # 退出碼與 mock 表
        code, mocks = self._run_with_checkpoint("cp--1")
        # STEP 02: 在 pre-flight 之前停下、專屬原因、細節帶 id 與處理方式
        self.assertEqual(code, runner.EXIT_PAUSED)
        mocks["preflight"].assert_not_called()
        mocks["process_one_entry"].assert_not_called()
        self.assertEqual(mocks["enter_paused"].call_args.args[1], CHECKPOINT_ID_INVALID)
        # 暫停細節
        detail = mocks["enter_paused"].call_args.args[2]
        self.assertIn("cp--1", detail)
        self.assertIn("queue.json", detail)

    def test_valid_checkpoint_id_reaches_preflight(self):
        """對照組：id 是 `cp-1`，照常走到 pre-flight（這裡讓 pre-flight 回非零、直接退出）。

        @return None
        """
        # STEP 01: 執行
        # 退出碼與 mock 表
        code, mocks = self._run_with_checkpoint("cp-1")
        # STEP 02: pre-flight 有被呼叫、沒有斷點 id 的暫停
        self.assertEqual(code, 1)
        mocks["preflight"].assert_called_once()
        mocks["enter_paused"].assert_not_called()


class RepeatedPauseReusesBundleTest(unittest.TestCase):
    """判定為重複的暫停不凍結新的診斷包，沿用上一包。"""

    def setUp(self):
        """通知與進度報表隔離。

        @return None
        """
        # STEP 01: 隔離與 fixture
        start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-bundle-"))
        # runner 設定
        self.config = self.fixture["config"]

    def _bundles(self):
        """目前 diagnostics/ 底下 runner 級診斷包的目錄名稱。

        @return 已排序的名稱清單
        """
        # STEP 01: 列目錄
        # 診斷包目錄
        directory = os.path.join(self.config["state_dir"], "diagnostics")
        if not os.path.isdir(directory):
            # STEP 01.01: 還沒有任何診斷包
            return []
        return sorted(name for name in os.listdir(directory) if name.startswith("runner-"))

    def test_repeated_unsigned_pause_reuses_bundle(self):
        """同一個不帶簽名的暫停連續兩次：第一次凍結一包（對照），第二次不多凍結、事件引用同一包。

        @return None
        """
        # STEP 01: 第一次——正常凍結
        runner.enter_paused(self.config, "integration_dirty", "工作樹有未提交的變更")
        # 第一次暫停的事件
        first = last_paused_event(self.config)
        self.assertEqual(len(self._bundles()), 1)
        self.assertTrue(first["diagnostics"])
        # STEP 02: 重啟、同原因再一次——判定為重複、不多凍結、沿用同一包
        simulate_restart(self.config)
        runner.enter_paused(self.config, "integration_dirty", "工作樹有未提交的變更")
        # 第二次暫停的事件
        second = last_paused_event(self.config)
        self.assertTrue(second["repeated"])
        self.assertEqual(len(self._bundles()), 1)
        self.assertEqual(second["diagnostics"], first["diagnostics"])

    def test_repeated_pause_with_corrupt_queue_reuses_bundle(self):
        """queue.json 損毀（第三層、看 log 尾端判斷重複）時一樣不出錯、不多凍結。

        @return None
        """
        # STEP 01: 弄壞 queue，連續兩次 queue_corrupt 暫停
        with open(runner.queue_file(self.config), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        runner.enter_paused(self.config, "queue_corrupt", "queue.json 解析失敗")
        # 第一次暫停的事件
        first = last_paused_event(self.config)
        runner.enter_paused(self.config, "queue_corrupt", "queue.json 解析失敗")
        # 第二次暫停的事件
        second = last_paused_event(self.config)
        # STEP 02: 重複、同一包
        self.assertTrue(second["repeated"])
        self.assertEqual(len(self._bundles()), 1)
        self.assertEqual(second["diagnostics"], first["diagnostics"])


class ReusedBundleGuardTest(unittest.TestCase):
    """沿用上一包的兩個防呆：簽名不同的包不沿用、目錄已不在的不沿用（都改成凍結新包）。"""

    def setUp(self):
        """通知與進度報表隔離；queue 弄壞，讓去重走第三層（只比原因）。

        @return None
        """
        # STEP 01: 隔離與 fixture
        start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-bundle-guard-"))
        # runner 設定
        self.config = self.fixture["config"]
        with open(runner.queue_file(self.config), "w", encoding="utf-8") as handle:
            handle.write("{not json")

    def test_bundle_of_other_signature_is_not_reused(self):
        """第三層只比原因：(R, 簽名 x) 之後的 (R, 無簽名) 被判成重複，但不能沿用簽名 x 那一包。

        @return None
        """
        # STEP 01: 兩次暫停
        runner.enter_paused(self.config, "queue_corrupt", "first", signature="x")
        # 第一次暫停的事件
        first = last_paused_event(self.config)
        runner.enter_paused(self.config, "queue_corrupt", "second")
        # 第二次暫停的事件
        second = last_paused_event(self.config)
        # STEP 02: 重複，但凍結了新包
        self.assertTrue(second["repeated"])
        self.assertTrue(second["diagnostics"])
        self.assertNotEqual(second["diagnostics"], first["diagnostics"])

    def test_missing_bundle_directory_is_not_reused(self):
        """上一包的目錄被刪了：重複的暫停改凍結新包，事件不引用不存在的目錄。

        @return None
        """
        # STEP 01: 第一次暫停後刪掉那一包
        runner.enter_paused(self.config, "queue_corrupt", "first")
        # 第一次暫停的事件
        first = last_paused_event(self.config)
        shutil.rmtree(os.path.join(self.config["state_dir"], first["diagnostics"]))
        runner.enter_paused(self.config, "queue_corrupt", "second")
        # 第二次暫停的事件
        second = last_paused_event(self.config)
        # STEP 02: 重複、新包存在
        self.assertTrue(second["repeated"])
        self.assertFalse(second["diagnostics_reused"])
        self.assertTrue(os.path.isdir(os.path.join(self.config["state_dir"], second["diagnostics"])))


class SignedPauseEdgeTest(unittest.TestCase):
    """補兩個邊界：沒鎖定、只帶簽名的暫停被 unblock --runner 之後一樣要清原因；這次才鎖定的暫停照樣凍結新包。"""

    def setUp(self):
        """通知與進度報表隔離。

        @return None
        """
        # STEP 01: 隔離與 fixture
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-signed-edge-"))
        # runner 設定
        self.config = self.fixture["config"]

    def test_unheld_push_failure_then_unblock_then_tip_mismatch_notifies(self):
        """推送失敗一次（帶簽名、沒鎖定）→ unblock --runner → 遠端 tip 不符：要通知。

        只清簽名的話落盤的是 (integration_diverged, None)，跟遠端 tip 不符完全相同。

        @return None
        """
        # STEP 01: 帶簽名的暫停、解除
        runner.enter_paused(self.config, "integration_diverged", "推送失敗", signature=runner.PUSH_FAILED_SIGNATURE)
        unblock_quietly(self.config)
        # STEP 02: 遠端 tip 不符
        simulate_restart(self.config)
        self.mocks["notify"].reset_mock()
        # 遠端 tip 不符那次的事件
        event = tip_mismatch_pause(self.config)
        self.assertFalse(event["repeated"])
        self.assertTrue(self.mocks["notify"].called)

    def test_hold_transition_freezes_new_bundle(self):
        """同簽名第二次（這次才鎖定）：雖然判定為重複，仍凍結新包——第二次的證據正是要看的。

        @return None
        """
        # STEP 01: 同簽名兩次
        runner.enter_paused(self.config, "integration_diverged", "推送失敗", signature=runner.PUSH_FAILED_SIGNATURE)
        # 第一次暫停的事件
        first = last_paused_event(self.config)
        simulate_restart(self.config)
        runner.enter_paused(self.config, "integration_diverged", "推送失敗", signature=runner.PUSH_FAILED_SIGNATURE)
        # 第二次暫停的事件
        second = last_paused_event(self.config)
        # STEP 02: 重複、鎖定、新包
        self.assertTrue(second["repeated"] and second["hold"])
        self.assertTrue(second["diagnostics"])
        self.assertNotEqual(second["diagnostics"], first["diagnostics"])


# 寫進 runner.log.jsonl 尾端的壞內容：半個 UTF-8 多位元組字元（磁碟滿時寫到一半）、一行合法但不是物件的 JSON、
# detail 不是物件的 paused 事件
BAD_LOG_TAILS = (
    ("bad_utf8", b"\xe5\xb7"),
    ("non_dict", b"123\n"),
    ("non_dict_detail", b'{"event": "paused", "detail": "x"}\n'),
)


def append_to_log(config, raw):
    """把原始位元組附加到 runner.log.jsonl 尾端（log 是 append-only，壞掉的內容會永久留著）。

    @param config runner 設定
    @param raw 要附加的位元組
    @return None
    """
    # STEP 01: 以二進位附加
    with open(runner.state_path(config, "runner.log.jsonl"), "ab") as handle:
        handle.write(raw)


class CorruptLogReadTest(unittest.TestCase):
    """讀 runner.log.jsonl 的兩個函式遇到壞內容不得拋例外；enter_paused 在壞 log 下仍是暫停、不走 crash。"""

    def setUp(self):
        """通知與進度報表隔離。

        @return None
        """
        # STEP 01: 隔離
        start_patches(self, "notify", "write_progress")

    def _paused_fixture(self, raw):
        """暫停一次後在 log 尾端附加壞內容。

        @param raw 要附加的位元組
        @return runner 設定
        """
        # STEP 01: 暫停、弄壞 log
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-badlog-"))
        runner.enter_paused(fixture["config"], "integration_dirty", "d1")
        append_to_log(fixture["config"], raw)
        return fixture["config"]

    def test_log_readers_do_not_raise(self):
        """last_paused_reason_from_log 與 previous_pause_bundle × 兩種壞內容：都不得拋例外。

        @return None
        """
        # 壞內容的名稱與位元組
        for name, raw in BAD_LOG_TAILS:
            # 受測呼叫：名稱 → 函式
            calls = {
                "last_paused_reason_from_log": lambda config: runner.last_paused_reason_from_log(config),
                "previous_pause_bundle": lambda config: runner.previous_pause_bundle(config, "integration_dirty", None),
            }
            for label, call in calls.items():
                with self.subTest(content=name, reader=label):
                    # STEP 01: 每格用自己的 fixture
                    # 已暫停一次、log 尾端壞掉的設定
                    config = self._paused_fixture(raw)
                    # STEP 02: 呼叫，例外轉成測試失敗
                    try:
                        call(config)
                    except Exception as exc:  # pylint: disable=broad-except
                        self.fail("%s 對 %s 拋出 %s: %s" % (label, name, type(exc).__name__, exc))

    def test_repeated_pause_with_corrupt_log_still_pauses(self):
        """壞 log 下同原因再暫停：回 EXIT_PAUSED、不拋例外（不走 crash 流程）。

        @return None
        """
        # 壞內容的名稱與位元組
        for name, raw in BAD_LOG_TAILS:
            with self.subTest(content=name):
                # STEP 01: 暫停、弄壞 log、重啟
                # 已暫停一次、log 尾端壞掉的設定
                config = self._paused_fixture(raw)
                simulate_restart(config)
                # STEP 02: 再暫停
                try:
                    # enter_paused 的回傳值
                    code = runner.enter_paused(config, "integration_dirty", "d1")
                except Exception as exc:  # pylint: disable=broad-except
                    self.fail("壞 log（%s）下 enter_paused 拋出 %s: %s" % (name, type(exc).__name__, exc))
                self.assertEqual(code, runner.EXIT_PAUSED)


class ReuseOnlyBeforeAnyEntryTest(unittest.TestCase):
    """診斷包只在「這個行程還沒處理過任何 entry」時沿用：處理過 entry 之後同原因的暫停可能是另一件事，要凍結新包。"""

    def test_pause_after_processing_an_entry_freezes_new_bundle(self):
        """paused(X) → 重啟 → 處理一個 entry（沒有 done）→ 同原因 X 再暫停：凍結新包、不沿用。

        對照組（一重啟就再暫停 → 沿用）是 RepeatedPauseReusesBundleTest。

        @return None
        """
        # STEP 01: 第一次暫停、重啟
        start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-reuse-entry-"))
        # runner 設定
        config = fixture["config"]
        runner.enter_paused(config, "integration_dirty", "d1")
        # 第一次暫停的事件
        first = last_paused_event(config)
        simulate_restart(config)
        # STEP 02: 開始處理一個 entry，CLI 呼叫失敗（沒有 done）
        with mock.patch.object(runner, "call_claude", side_effect=RuntimeError("CLI 失敗（測試）")):
            with self.assertRaises(RuntimeError):
                runner.process_one_entry(config, fixture["entry"])
        # STEP 03: 同原因再暫停——新包
        runner.enter_paused(config, "integration_dirty", "d1")
        # 第二次暫停的事件
        second = last_paused_event(config)
        self.assertTrue(second["repeated"])
        self.assertFalse(second["diagnostics_reused"])
        self.assertNotEqual(second["diagnostics"], first["diagnostics"])


class UnblockRunnerRemainingReasonMessageTest(unittest.TestCase):
    """unblock --runner 清不掉的暫停原因（例如 checkpoint_id_invalid）還在時，不能印「下次啟動會續跑」。"""

    def test_remaining_reason_is_reported(self):
        """paused(checkpoint_id_invalid) → unblock --runner：說明寫出原因還在、要先處理，不宣稱會續跑。

        @return None
        """
        # STEP 01: 暫停、解除
        start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-unblock-msg-"))
        runner.enter_paused(fixture["config"], CHECKPOINT_ID_INVALID, "斷點 id `cp--1` 不合規")
        # unblock 印出的說明
        text = unblock_quietly(fixture["config"])
        # STEP 02: 照實說明
        self.assertIn(CHECKPOINT_ID_INVALID, text)
        self.assertNotIn("下次啟動會續跑", text)


if __name__ == "__main__":
    unittest.main()
