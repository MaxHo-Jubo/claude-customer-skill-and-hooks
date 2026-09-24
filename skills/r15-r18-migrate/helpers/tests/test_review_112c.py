"""runner.py 1.1.2 第三批的回歸測試：第二批 agent review（兩位 reviewer）逐條查證後修正的項目。

  * 發佈段 ff-merge「可以快轉但環境失敗」與「祖先檢查失敗」改用專屬暫停原因＋簽名：同原因連續第二次鎖定（hold），
    中間有 entry 完成就重新起算；也不再和前置作業的「遠端 tip 不符」共用 integration_diverged 的通知去重。
  * enter_paused 的通知去重以 (原因, 簽名) 完全相等為準；entry 完成時連原因一起清（追加項）。
  * session_log_path 的 name 不合規（含 `--`、不以小寫字母開頭、含 `/`）直接拋 ValueError；import-inventory 擋下會組出
    不合規 log 名稱的斷點 id。
  * abort_failed_merge 在沒有進行中的合併時不呼叫 abort，附註寫「合併未開始」。

拓撲 helper 從 test_stale_branch、fixture 從 review_fixtures 匯入（只匯入函式與常數，不匯入 TestCase，免得被重複收集）。
新的暫停原因在這裡寫成字面值而不是引用 runner 的常數：修正前常數不存在，引用它會讓測試以 AttributeError 失敗、
而不是以 AssertionError 證明「還沒修」；字面值同時釘住 status／通知標題上看得到的那個字串。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import argparse
import contextlib
import io
import json
import os
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
    R15_RELATIVE_PATH,
    build_fixture,
    queue_entry,
    run_git,
    start_patches,
)
from test_stale_branch import (  # noqa: E402  pylint: disable=wrong-import-position
    add_entry_branch,
    git_with_override,
    stale_fixture,
)

# 發佈段 ff-merge 因環境失敗（或祖先檢查失敗）的專屬暫停原因（runner.FF_ENV_FAILED_REASON 的值）
ENV_FF_REASON = "ff_merge_env_failed"
# 注入的環境類 git 失敗（index.lock 被占用）：跟分支拓撲無關，任何 entry 都可能遇到
INDEX_LOCK_ERROR = "fatal: Unable to create '.git/index.lock': File exists."
# 注入的 ff-merge 失敗：參數開頭與回傳值
FF_MERGE_PREFIX = ("merge", "--ff-only")
FF_MERGE_FAILURE = (128, "", INDEX_LOCK_ERROR)


def simulate_restart(config):
    """模擬 launchd 重啟後 cmd_run 做的事：記下上一輪的暫停原因與簽名、runner_state 改成 running。

    @param config runner 設定（就地寫入 startup_paused_reason／startup_crash_signature）
    @return 重啟前落盤的 runner_state
    """
    # STEP 01: 讀上一輪留下的狀態，照 cmd_run STEP 02.01 存進 config
    # 上一輪結束時的 runner_state
    state = runner.load_queue(config)["runner_state"]
    config["startup_paused_reason"] = state.get("reason")
    config["startup_crash_signature"] = state.get("crash_signature")
    runner.set_runner_state(config, "running")
    return state


def last_paused_event(config):
    """runner.log.jsonl 裡最後一筆 paused 事件的 detail。

    @param config runner 設定
    @return dict（reason、repeated、hold…）；沒有 paused 事件回 None
    """
    # STEP 01: 由後往前找
    # 事件紀錄檔的每一行
    with open(runner.state_path(config, "runner.log.jsonl"), "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    for line in reversed(lines):
        # 這一行解析後的事件
        record = json.loads(line)
        if record.get("event") == "paused":
            # STEP 01.01: 找到就回它的 detail
            return record.get("detail")
    return None


class EnvFfPauseBrakeTest(unittest.TestCase):
    """發佈段 ff-merge 的環境類失敗：專屬原因＋簽名，連續第二次鎖定；不吞掉之後前置作業的「遠端 tip 不符」通知。"""

    def setUp(self):
        """通知與進度報表隔離；enter_paused 用真的（要驗去重與鎖定）。

        @return None
        """
        # STEP 01: 隔離
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress")
        # CLI 判讀結果（發佈段收尾用到 structured、session_id、cost）
        self.outcome = {"structured": {}, "session_id": "s", "cost": 0.1}
        # 測試用的 git 環境與狀態目錄（entry 分支可以快轉）
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-envff-"))
        # runner 設定
        self.config = self.fixture["config"]

    def _publish(self, entry, inject):
        """跑一次發佈段；inject 為真時 ff-merge 注入 index.lock 失敗。

        @param entry 要發佈的 entry
        @param inject 是否注入 ff-merge 失敗
        @return publish_verified_entry 的回傳值
        """
        # STEP 01: 需要時注入
        if not inject:
            # STEP 01.01: 不注入，真的合併推送
            return runner.publish_verified_entry(self.config, entry, self.outcome, 1)
        with mock.patch.object(runner, "git", git_with_override(FF_MERGE_PREFIX, FF_MERGE_FAILURE)):
            return runner.publish_verified_entry(self.config, entry, self.outcome, 1)

    def test_same_env_failure_twice_without_done_holds(self):
        """環境失敗 → 重啟 → 同一個環境失敗：第一次一般暫停（專屬原因＋簽名、通知），第二次鎖定。

        修正前：integration_diverged 無簽名，第二次只是「同原因重複暫停、不通知」，launchd 重啟後再跑一次完整 CLI，沒有盡頭。

        @return None
        """
        # STEP 01: 第一次——專屬原因與簽名、不鎖定
        self.assertEqual(self._publish(self.fixture["entry"], True), runner.EXIT_PAUSED)
        # 第一次暫停後落盤的 runner_state
        state = simulate_restart(self.config)
        self.assertEqual((state.get("reason"), state.get("crash_signature")), (ENV_FF_REASON, ENV_FF_REASON))
        self.assertFalse(state.get("hold"), state)
        # STEP 02: 重啟後同一個 entry 再失敗一次（中間沒有 done）→ 鎖定
        self.assertEqual(self._publish(self.fixture["entry"], True), runner.EXIT_PAUSED)
        # 第二次暫停後落盤的 runner_state
        state = runner.load_queue(self.config)["runner_state"]
        self.assertEqual(state.get("reason"), ENV_FF_REASON)
        self.assertTrue(state.get("hold"), state)

    def test_done_in_between_does_not_hold(self):
        """環境失敗 → 重啟 → 環境恢復、entry 完成 → 另一個 entry 環境失敗：一般暫停、不鎖定。

        @return None
        """
        # STEP 01: 第一次環境失敗、重啟
        self.assertEqual(self._publish(self.fixture["entry"], True), runner.EXIT_PAUSED)
        simulate_restart(self.config)
        # STEP 02: 環境恢復，e1 完成；e2 從前進後的整合分支切出、遇到同一個環境失敗
        self.assertIsNone(self._publish(self.fixture["entry"], False))
        self.assertEqual(queue_entry(self.fixture)[1]["status"], "done")
        # 第二個 entry
        second = add_entry_branch(self.fixture, "e2", "e2-branch")
        self.assertEqual(self._publish(second, True), runner.EXIT_PAUSED)
        # STEP 03: 專屬原因、不鎖定
        # 落盤的 runner_state
        state = runner.load_queue(self.config)["runner_state"]
        self.assertEqual(state.get("reason"), ENV_FF_REASON)
        self.assertFalse(state.get("hold"), state)

    def test_env_pause_then_remote_tip_mismatch_still_notifies(self):
        """環境類暫停 → 重啟 → 前置作業發現遠端 tip 與記錄值不同：這是要人處理的暫停，必須通知（repeated=False）。

        修正前：兩者共用 integration_diverged，重啟時存下的 startup_paused_reason 讓後者被當成「同原因重複」而不通知。

        @return None
        """
        # STEP 01: 環境類暫停、重啟
        self.assertEqual(self._publish(self.fixture["entry"], True), runner.EXIT_PAUSED)
        simulate_restart(self.config)
        self.mocks["notify"].reset_mock()
        # STEP 02: 記錄的 tip 與遠端不同（有人在 runner 不知道的情況下動了整合分支）→ 前置作業回 integration_diverged
        run_git(self.config["repo_dir"], "checkout", INTEGRATION_BRANCH)
        runner.set_integration_tip(self.config, "0" * 40)
        # 前置作業的結果：是否通過、暫停原因、細節
        ok, reason, detail = runner.module_preflight(self.config, runner.load_queue(self.config))
        self.assertEqual((ok, reason), (False, "integration_diverged"), detail)
        # STEP 03: 照 cmd_run 的方式進暫停；必須是新事件、有通知
        self.assertEqual(runner.enter_paused(self.config, reason, detail), runner.EXIT_PAUSED)
        self.assertFalse(last_paused_event(self.config)["repeated"])
        self.assertTrue(self.mocks["notify"].called, "遠端 tip 不符的暫停被去重吞掉，沒有通知")
        self.assertIn("integration_diverged", self.mocks["notify"].call_args.args[2])


class PauseDedupKeyTest(unittest.TestCase):
    """enter_paused 的通知去重以 (原因, 簽名) 完全相等為準；entry 完成後先前的暫停視為已解除，同原因再暫停是新事件。

    修正前第一、二層在這次沒有簽名時只比原因：「帶簽名的暫停 → 重啟 → 同原因、不帶簽名的暫停」被判成重複、不通知，
    被吞掉的若是要人處理的那種（遠端 tip 不符），之後每次重啟都只會安靜退出。
    """

    # 測試共用的暫停原因（推送失敗與遠端 tip 不符都用它）
    REASON = "integration_diverged"

    def setUp(self):
        """通知與進度報表隔離；enter_paused 用真的。

        @return None
        """
        # STEP 01: 隔離與 fixture
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-dedup-"))
        # runner 設定
        self.config = self.fixture["config"]

    def _pause_again(self, signature, config=None):
        """清掉通知紀錄後再暫停一次，回傳這次的 paused 事件。

        @param signature 這次暫停的簽名（None 表示不帶）
        @param config 要用的 runner 設定；None 用 fixture 的
        @return 這次的 paused 事件 detail
        """
        # STEP 01: 暫停並取事件
        # 這次暫停用的 runner 設定
        target = config or self.config
        self.mocks["notify"].reset_mock()
        runner.enter_paused(target, self.REASON, "second", signature=signature)
        return last_paused_event(target)

    def test_signed_then_unsigned_after_restart_notifies(self):
        """(a) 第一層：帶簽名的暫停 → 重啟 → 同原因、不帶簽名：不是重複、有通知。

        @return None
        """
        # STEP 01: 推送失敗類暫停、重啟
        runner.enter_paused(self.config, self.REASON, "first", signature=runner.PUSH_FAILED_SIGNATURE)
        simulate_restart(self.config)
        # STEP 02: 遠端 tip 不符類（不帶簽名）
        # 第二次暫停的事件
        event = self._pause_again(None)
        self.assertFalse(event["repeated"])
        self.assertTrue(self.mocks["notify"].called)

    def test_signed_then_unsigned_before_main_loop_notifies(self):
        """(a) 第二層：queue 仍是帶簽名的 paused、這個行程還沒存 startup_*（主迴圈之前的暫停）：同原因不帶簽名一樣要通知。

        @return None
        """
        # STEP 01: 帶簽名的暫停；新行程的設定沒有 startup_* 欄位
        runner.enter_paused(self.config, self.REASON, "first", signature=runner.PUSH_FAILED_SIGNATURE)
        # 新行程的 runner 設定（還沒走到 cmd_run 存 startup_* 那一步）
        fresh = {key: value for key, value in self.config.items() if not key.startswith("startup_")}
        # STEP 02: 不帶簽名的暫停
        # 第二次暫停的事件
        event = self._pause_again(None, fresh)
        self.assertFalse(event["repeated"])
        self.assertTrue(self.mocks["notify"].called)

    def test_unsigned_then_signed_notifies(self):
        """(b) 反向：不帶簽名 → 重啟 → 同原因帶簽名：不是重複、有通知、不鎖定。

        @return None
        """
        # STEP 01: 兩次暫停
        runner.enter_paused(self.config, self.REASON, "first")
        simulate_restart(self.config)
        # 第二次暫停的事件
        event = self._pause_again(runner.PUSH_FAILED_SIGNATURE)
        # STEP 02: 新事件
        self.assertFalse(event["repeated"])
        self.assertFalse(event["hold"])
        self.assertTrue(self.mocks["notify"].called)

    def test_same_signature_twice_holds(self):
        """(c) 同原因同簽名連續兩次：重複、鎖定（鎖定是新狀態，通知一次）。

        @return None
        """
        # STEP 01: 兩次暫停
        runner.enter_paused(self.config, self.REASON, "first", signature=runner.PUSH_FAILED_SIGNATURE)
        simulate_restart(self.config)
        # 第二次暫停的事件
        event = self._pause_again(runner.PUSH_FAILED_SIGNATURE)
        # STEP 02: 重複且鎖定
        self.assertTrue(event["repeated"])
        self.assertTrue(event["hold"])

    def test_unsigned_twice_is_repeated_without_notify(self):
        """(d) 同原因都不帶簽名連續兩次：重複、不再通知、不鎖定（既有行為）。

        @return None
        """
        # 「沒有簽名」的三種落盤表示法：enter_paused 寫的 None、舊版 queue 缺欄位、手改成空字串
        for stored in ("none", "missing", "empty"):
            with self.subTest(stored=stored):
                # STEP 01: 每種表示法用自己的 fixture；第一次暫停後改寫落盤的簽名欄位
                self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-dedup-d-"))
                self.config = self.fixture["config"]
                runner.enter_paused(self.config, self.REASON, "first")

                def rewrite(queue):
                    """mutate_queue 用：把 runner_state.crash_signature 改成這一輪要測的表示法（就地修改）。

                    @param queue 整份 queue
                    @return None
                    """
                    # STEP 01: 依表示法改寫
                    if stored == "missing":
                        # STEP 01.01: 刪掉欄位
                        queue["runner_state"].pop("crash_signature", None)
                    elif stored == "empty":
                        # STEP 01.02: 空字串
                        queue["runner_state"]["crash_signature"] = ""

                runner.mutate_queue(self.config, rewrite)
                simulate_restart(self.config)
                # 第二次暫停的事件
                event = self._pause_again(None)
                # STEP 02: 重複、沒通知、不鎖定
                self.assertTrue(event["repeated"])
                self.assertFalse(event["hold"])
                self.mocks["notify"].assert_not_called()

    def test_pause_after_done_entry_notifies(self):
        """(e) 暫停 → 重啟 → entry 完成 → 同原因不帶簽名：先前的暫停已確認解除，這是新事件、要通知。

        @return None
        """
        # STEP 01: 暫停、重啟、e1 發佈完成
        runner.enter_paused(self.config, self.REASON, "first")
        simulate_restart(self.config)
        self.assertIsNone(runner.publish_verified_entry(self.config, self.fixture["entry"], {"structured": {}, "session_id": "s", "cost": 0.1}, 1))
        self.assertEqual(queue_entry(self.fixture)[1]["status"], "done")
        # STEP 02: 同原因再暫停
        # 第二次暫停的事件
        event = self._pause_again(None)
        self.assertFalse(event["repeated"])
        self.assertTrue(self.mocks["notify"].called)


class SessionLogNameGuardTest(unittest.TestCase):
    """session_log_path 的 name 約束要在程式裡擋，不能只寫在 docstring；import-inventory 擋下會組出壞名稱的斷點 id。"""

    def test_invalid_names_raise(self):
        """含 `--`、大寫開頭、`-` 開頭、含 `/`、空字串：一律 ValueError；合法名稱照常組路徑。

        @return None
        """
        # STEP 01: 模組脈絡下的設定
        # 最小 runner 設定（只用到 state_dir 與目前的 entry／序號）
        config = {"state_dir": tempfile.mkdtemp(prefix="r18-logguard-"), "current_entry": "e1", "current_attempt": 3}
        # 不合規的名稱
        for name in ("git-merge-cp-a--b", "Build", "-x", "git/merge", ""):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    runner.session_log_path(config, name)
        # STEP 02: 對照組：合法名稱（含斷點名稱的形狀）照常
        self.assertTrue(runner.session_log_path(config, "git-merge-cp-auto-20260923-1200").endswith("e1-3--git-merge-cp-auto-20260923-1200.log"))

    def _import_errors(self, checkpoint_id):
        """用只有一個斷點的盤點檔跑 import-inventory，回傳 stderr。

        其他欄位是否合法不重要：驗證錯誤一次全列，這裡只看斷點 id 那一條有沒有出現。

        @param checkpoint_id 斷點 id
        @return stderr 全文
        """
        # STEP 01: 盤點檔
        # 暫存根目錄
        root = tempfile.mkdtemp(prefix="r18-import-cp-")
        # 盤點檔路徑
        inventory_path = os.path.join(root, "inventory.json")
        with open(inventory_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "entries": [{"id": "e1", "wave": 0, "type": "page", "r15_paths": [R15_RELATIVE_PATH]}],
                    "checkpoints": [{"id": checkpoint_id, "after": {"wave": 0}, "mode": "soft"}],
                },
                handle,
            )
        # STEP 02: 匯入，收 stderr
        # 最小 runner 設定（上限值只為了讓驗證跑完，不影響斷點 id 的判定）
        config = {
            "state_dir": os.path.join(root, "state"),
            "repo_dir": root,
            "branch_user": "tester",
            "entry_max_files": 50,
            "entry_max_lines": 5000,
        }
        # 捕捉 stderr 的緩衝
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured), contextlib.redirect_stdout(io.StringIO()):
            runner.cmd_import_inventory(config, argparse.Namespace(inventory=inventory_path))
        return captured.getvalue()

    def test_import_rejects_checkpoint_id_that_breaks_log_name(self):
        """斷點 id 含 `--`：import-inventory 列出這個錯誤；對照組 `cp-1` 不會。

        @return None
        """
        # STEP 01: 壞 id 有錯誤、好 id 沒有
        self.assertIn("斷點 id `cp--1`", self._import_errors("cp--1"))
        self.assertNotIn("斷點 id `cp-1`", self._import_errors("cp-1"))


class AbortWithoutMergeTest(unittest.TestCase):
    """合併在開始之前就失敗（沒有 MERGE_HEAD）：不呼叫 merge --abort，附註說「合併未開始」，不宣稱 repo 可能停在合併中。"""

    def test_prepare_merge_not_started_skips_abort(self):
        """prepare_branch 的合併注入「未追蹤檔會被覆寫」（git 在動手前就拒絕）：暫停（非衝突）、abort 沒被呼叫。

        @return None
        """
        # STEP 01: 無衝突的舊分支拓撲、跑前置作業
        start_patches(self, "notify", "write_progress")
        # 測試用的 git 環境與狀態目錄
        fixture = stale_fixture(conflict=False)
        # runner 設定
        config = fixture["config"]
        # 前置作業的結果
        ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(ok, "%s: %s" % (reason, detail))
        # STEP 02: 合併注入失敗，其餘 git 照常並記下參數
        # 注入 merge 失敗的 git（其餘照常）
        injected = git_with_override(
            ("merge", "--ff", "--no-edit"), (1, "", "error: untracked working tree files would be overwritten by merge")
        )
        # 每次 git 呼叫的參數
        calls = []

        def recording_git(config_arg, *args, **kwargs):
            """記下參數後交給注入版 git。

            @param config_arg runner 設定
            @param args git 參數
            @param kwargs 原樣轉交
            @return (returncode, stdout, stderr)
            """
            # STEP 01: 記錄並轉交
            calls.append(args)
            return injected(config_arg, *args, **kwargs)

        with mock.patch.object(runner, "git", recording_git):
            # prepare_branch 的結果與細節
            status, detail = runner.prepare_branch(config, fixture["entry"])
        # STEP 03: 暫停、非衝突、合併未開始、沒呼叫 abort
        self.assertEqual(status, runner.PREPARE_PAUSE, detail)
        self.assertIn("非衝突", detail)
        self.assertIn("合併未開始", detail)
        self.assertNotIn("repo 可能停在合併中", detail)
        self.assertNotIn(("merge", "--abort"), calls)


if __name__ == "__main__":
    unittest.main()
