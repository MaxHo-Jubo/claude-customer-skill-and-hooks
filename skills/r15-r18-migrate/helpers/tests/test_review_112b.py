"""runner.py 1.1.2 第二批的回歸測試：c8093cb 的 codex review（tier 3）逐條查證後修正的項目。

  * ff-merge 非零不等於「entry 分支不是後代」：要用 merge-base --is-ancestor 確認（退出碼 1）才標 blocked。
  * 兩條新 blocked 路徑的「寫 blocked＋通知」在同一個停止訊號延後區間內。
  * mark_entry_blocked 找不到 entry 要拋錯，不能安靜回 None。
  * 合併失敗收尾共用 helper（abort_failed_merge）：前置作業兩處的清單讀取失敗與 abort 失敗寫進 detail、暫停原因不變。
子行程 log 雙減號的測試在 test_call_number.py；prepare_branch 的 detail 不宣稱「非衝突」在 test_stale_branch.py。

拓撲 helper 從 test_stale_branch、fixture 從 review_fixtures 匯入（只匯入函式與常數，不匯入 TestCase，免得被重複收集）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import os
import signal
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
    BASE_BRANCH,
    CHECKPOINT_BRANCH,
    ENTRY_BRANCH,
    INTEGRATION_BRANCH,
    R15_RELATIVE_PATH,
    _register_opened_checkpoint,
    build_fixture,
    queue_entry,
    remote_tip,
    run_git,
    start_patches,
)
from test_stale_branch import (  # noqa: E402  pylint: disable=wrong-import-position
    OTHER_ENTRY_FILE,
    advance_integration,
    git_with_override,
    is_ancestor,
    stale_fixture,
)

# 注入的環境類 git 失敗（index.lock 被占用）：跟分支拓撲無關，任何 entry 都可能遇到
INDEX_LOCK_ERROR = "fatal: Unable to create '.git/index.lock': File exists."


def reset_signal_deferral():
    """把 runner 的停止訊號延後區間狀態歸零（addCleanup 用：受測程式在區間內拋錯時，別讓殘留深度汙染後面的測試）。

    @return None
    """
    # STEP 01: 深度與延後中的訊號一併清掉
    runner._SIGNAL_DEFER_DEPTH = 0  # pylint: disable=protected-access
    runner._PENDING_SIGNUM = None  # pylint: disable=protected-access


def blocked_then_signal():
    """包住真的 mark_entry_blocked：寫完 blocked 立刻觸發停止訊號 handler（模擬訊號恰好落在「寫 blocked」與「通知」之間）。

    @return 可以拿去 mock.patch.object(runner, "mark_entry_blocked", ...) 的函式
    """
    # 被包住的真函式（patch 之前先取，否則會拿到假件自己）
    real_mark = runner.mark_entry_blocked

    def fake_mark(*args, **kwargs):
        """照常寫 blocked，之後送出停止訊號。

        @param args 原樣轉給 mark_entry_blocked
        @param kwargs 原樣轉給 mark_entry_blocked
        @return mark_entry_blocked 的回傳值（訊號在延後區間內才會走到這行）
        """
        # STEP 01: 寫 blocked
        # mark_entry_blocked 的回傳值（寫入後的 entry）
        written = real_mark(*args, **kwargs)
        # STEP 02: 直接呼叫 handler 模擬訊號（不真的裝訊號）；不在延後區間時它會在這裡拋 ShutdownSignal
        runner.shutdown_signal_handler(signal.SIGTERM, None)
        return written

    return fake_mark


def base_conflict_fixture():
    """基準分支與整合分支改了同一個檔（內容不同）：前置作業 STEP 06 合併基準分支會衝突。

    @return build_fixture 的回傳值（config 補上 base_branch；停在整合分支上）
    """
    # STEP 01: 基準分支從基線切出、改 R15 檔、推上遠端
    # 測試用的 git 環境與狀態目錄
    fixture = build_fixture(tempfile.mkdtemp(prefix="r18-base-conflict-"))
    # 工作 repo 路徑
    work = fixture["config"]["repo_dir"]
    fixture["config"]["base_branch"] = BASE_BRANCH
    run_git(work, "checkout", "-b", BASE_BRANCH, fixture["base_sha"])
    with open(os.path.join(work, R15_RELATIVE_PATH), "w", encoding="utf-8") as handle:
        handle.write("// base version\n")
    run_git(work, "commit", "-am", "base edits a.js")
    run_git(work, "push", "-u", "origin", BASE_BRANCH)
    # STEP 02: 另一個 entry 在整合分支上改同一個檔（已推送、tip 已記）
    advance_integration(fixture, R15_RELATIVE_PATH, "// integration version\n", "e0 edits a.js")
    return fixture


def checkpoint_conflict_fixture():
    """基準分支與 opened 斷點分支改了同一個檔：前置作業合併基準分支成功，STEP 07 回流斷點分支時衝突。

    @return build_fixture 的回傳值（config 補上 base_branch；queue 登記一個 opened 斷點；停在整合分支上）
    """
    # STEP 01: 基準分支改 R15 檔並推上遠端
    # 測試用的 git 環境與狀態目錄
    fixture = build_fixture(tempfile.mkdtemp(prefix="r18-cp-conflict-"))
    # 工作 repo 路徑
    work = fixture["config"]["repo_dir"]
    fixture["config"]["base_branch"] = BASE_BRANCH
    run_git(work, "checkout", "-b", BASE_BRANCH, fixture["base_sha"])
    with open(os.path.join(work, R15_RELATIVE_PATH), "w", encoding="utf-8") as handle:
        handle.write("// base version\n")
    run_git(work, "commit", "-am", "base edits a.js")
    run_git(work, "push", "-u", "origin", BASE_BRANCH)
    # STEP 02: 斷點分支從整合分支切出、改同一個檔（不同內容），登記成 opened
    run_git(work, "checkout", "-b", CHECKPOINT_BRANCH, INTEGRATION_BRANCH)
    with open(os.path.join(work, R15_RELATIVE_PATH), "w", encoding="utf-8") as handle:
        handle.write("// checkpoint version\n")
    run_git(work, "commit", "-am", "checkpoint edits a.js")
    run_git(work, "checkout", INTEGRATION_BRANCH)
    runner.mutate_queue(fixture["config"], _register_opened_checkpoint)
    return fixture


class PublishFfFailureClassificationTest(unittest.TestCase):
    """第二批（review CRITICAL）：ff-merge 非零不等於「entry 分支不是整合分支的後代」，要用祖先關係確認過才標 blocked。"""

    def setUp(self):
        """通知、進度報表、診斷包凍結隔離；enter_paused 換成假件記下暫停原因與細節。

        @return None
        """
        # STEP 01: 隔離
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress", "freeze_entry_bundle", "enter_paused")
        self.mocks["freeze_entry_bundle"].return_value = None
        self.mocks["enter_paused"].return_value = runner.EXIT_PAUSED
        # 發佈段交給收尾的 CLI 判讀結果（這裡只會用到花費）
        self.outcome = {"structured": {}, "session_id": "session-1", "cost": 0.5}

    def _publish(self, fixture, prefix, response):
        """注入一種 git 失敗後跑發佈段。

        @param fixture build_fixture 的回傳值（停在 entry 分支上）
        @param prefix 要注入失敗的 git 參數開頭
        @param response 注入的 (returncode, stdout, stderr)
        @return publish_verified_entry 的回傳值
        """
        # STEP 01: 注入並發佈
        with mock.patch.object(runner, "git", git_with_override(prefix, response)):
            return runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)

    def _assert_paused_not_blocked(self, fixture, remote_before, expected_text):
        """共同斷言：runner 級暫停（第三批起是專屬原因＋同值簽名）、細節帶原因、entry 仍是 running、遠端整合分支沒動。

        @param fixture build_fixture 的回傳值
        @param remote_before 發佈前的遠端整合分支 tip
        @param expected_text 暫停細節裡必須出現的原因文字
        @return None
        """
        # STEP 01: 暫停原因、簽名與細節
        self.assertTrue(self.mocks["enter_paused"].called, "應該 runner 級暫停，卻沒有呼叫 enter_paused")
        self.assertEqual(self.mocks["enter_paused"].call_args.args[1], runner.FF_ENV_FAILED_REASON)
        self.assertEqual(self.mocks["enter_paused"].call_args.kwargs.get("signature"), runner.FF_ENV_FAILED_REASON)
        self.assertIn(expected_text, self.mocks["enter_paused"].call_args.args[2])
        # STEP 02: entry 沒被標 blocked、遠端沒動
        self.assertEqual(queue_entry(fixture)[1]["status"], "running")
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), remote_before)

    def test_ffable_branch_with_env_merge_failure_pauses_not_blocks(self):
        """entry 分支可以快轉、但 git merge 因環境失敗（index.lock）：runner 級暫停，不標 git_state blocked。

        修正前：任何 ff-merge 非零都回 entry_not_ff → entry 永久 blocked，環境恢復後也不會自動重試，
        同一個環境問題還會把後面的 entry 逐一清成 blocked。

        @return None
        """
        # STEP 01: 沒有別的 entry 合併過（entry 分支是整合分支的後代）；merge --ff-only 注入 index.lock 失敗
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-ff-env-"))
        # 工作 repo 路徑
        work = fixture["config"]["repo_dir"]
        self.assertTrue(is_ancestor(work, INTEGRATION_BRANCH, ENTRY_BRANCH), "前置條件：entry 分支應可快轉")
        # 發佈前的遠端整合分支 tip
        remote_before = remote_tip(fixture, INTEGRATION_BRANCH)
        # 受測呼叫回的 runner 退出碼（None 表示主迴圈繼續）
        exit_code = self._publish(fixture, ("merge", "--ff-only"), (128, "", INDEX_LOCK_ERROR))
        # STEP 02: 暫停，細節帶環境錯誤與「可以快轉」的判定
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self._assert_paused_not_blocked(fixture, remote_before, "index.lock")
        self.assertIn("可以快轉", self.mocks["enter_paused"].call_args.args[2])

    def test_ancestry_check_failure_pauses_not_blocks(self):
        """entry 分支確實落後、ff-merge 失敗，但祖先檢查本身失敗：無法判定，runner 級暫停、不標 blocked。

        @return None
        """
        # STEP 01: 整合分支被另一個 entry 推進過（ff 會真的失敗）；merge-base 注入指令失敗
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-ff-ancestry-"))
        advance_integration(fixture, OTHER_ENTRY_FILE, "// e0 migrated\n", "migrate e0")
        run_git(fixture["config"]["repo_dir"], "checkout", ENTRY_BRANCH)
        # 發佈前的遠端整合分支 tip
        remote_before = remote_tip(fixture, INTEGRATION_BRANCH)
        # 受測呼叫回的 runner 退出碼（None 表示主迴圈繼續）
        exit_code = self._publish(fixture, ("merge-base", "--is-ancestor"), (128, "", "fatal: ancestry boom"))
        # STEP 02: 暫停，細節帶祖先檢查的錯誤
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self._assert_paused_not_blocked(fixture, remote_before, "ancestry boom")


class BlockedNotifyDeferralTest(unittest.TestCase):
    """第二批（review CRITICAL）：新的兩條 blocked 路徑，寫 blocked 與通知要在同一個停止訊號延後區間內。

    不然訊號落在兩步之間：外層當正常停止，entry 已是 blocked（重啟後不會再被取件），通知卻永遠不會送出。
    """

    def setUp(self):
        """通知、進度報表、診斷包凍結隔離；延後區間狀態在每個測試後歸零。

        @return None
        """
        # STEP 01: 隔離
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress", "freeze_entry_bundle")
        self.mocks["freeze_entry_bundle"].return_value = None
        self.addCleanup(reset_signal_deferral)

    def _assert_blocked_and_notified(self, fixture, raised):
        """共同斷言：訊號在通知之後才拋出、entry 已 blocked、通知已送、區間狀態清乾淨。

        @param fixture build_fixture 的回傳值
        @param raised 受測呼叫拋出的例外（沒拋是 None）
        @return None
        """
        # STEP 01: 通知有送（修正前訊號在寫完 blocked 當下就拋出，通知不會送）
        self.assertEqual([call.args[1] for call in self.mocks["notify"].call_args_list], ["module_blocked"])
        self.assertEqual(queue_entry(fixture)[1]["status"], "blocked")
        # STEP 02: 延後的訊號在區間結束時照樣拋出（runner 仍會停），區間狀態歸零
        self.assertIsInstance(raised, runner.ShutdownSignal)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)  # pylint: disable=protected-access
        self.assertIsNone(runner._PENDING_SIGNUM)  # pylint: disable=protected-access

    def test_signal_between_block_and_notify_in_prepare(self):
        """prepare_branch 合併衝突：訊號落在寫 blocked 之後，通知仍要送出。

        @return None
        """
        # STEP 01: 衝突拓撲＋前置作業
        # 測試用的 git 環境與狀態目錄
        fixture = stale_fixture(conflict=True)
        # runner 設定
        config = fixture["config"]
        # 前置作業的結果：是否通過、暫停原因、細節
        ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(ok, "%s: %s" % (reason, detail))
        # STEP 02: 準備分支
        # 受測呼叫拋出的例外
        raised = None
        with mock.patch.object(runner, "mark_entry_blocked", blocked_then_signal()):
            try:
                runner.prepare_branch(config, fixture["entry"])
            except runner.ShutdownSignal as exc:
                raised = exc
        self._assert_blocked_and_notified(fixture, raised)

    def test_signal_between_block_and_notify_in_publish(self):
        """發佈段 ff-merge 失敗（確定不是後代）：訊號落在寫 blocked 之後，通知仍要送出。

        @return None
        """
        # STEP 01: 整合分支被另一個 entry 推進過，停在 entry 分支上
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-defer-publish-"))
        advance_integration(fixture, OTHER_ENTRY_FILE, "// e0 migrated\n", "migrate e0")
        run_git(fixture["config"]["repo_dir"], "checkout", ENTRY_BRANCH)
        # 發佈段交給收尾的 CLI 判讀結果
        outcome = {"structured": {}, "session_id": "session-1", "cost": 0.5}
        # STEP 02: 發佈
        # 受測呼叫拋出的例外
        raised = None
        with mock.patch.object(runner, "mark_entry_blocked", blocked_then_signal()):
            try:
                runner.publish_verified_entry(fixture["config"], fixture["entry"], outcome, 1)
            except runner.ShutdownSignal as exc:
                raised = exc
        self._assert_blocked_and_notified(fixture, raised)


class MarkEntryBlockedMissingEntryTest(unittest.TestCase):
    """第二批（review CRITICAL）：mark_entry_blocked 找不到 entry 要拋錯，不能安靜回 None 讓呼叫端照樣宣稱「已 blocked」。"""

    def setUp(self):
        """通知隔離；fixture 只有 e1 一個 entry。

        @return None
        """
        # STEP 01: 隔離與 fixture
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify")
        # build_fixture 的回傳值
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-blocked-missing-"))

    def test_missing_entry_raises_with_id_and_leaves_queue(self):
        """entry 已不在 queue 裡：RuntimeError 帶 entry id，queue 內容不變。

        @return None
        """
        # STEP 01: 呼叫前的 queue
        # runner 設定
        config = self.fixture["config"]
        # 呼叫前的 queue 內容
        before = runner.load_queue(config)
        # STEP 02: 拋錯、queue 不變
        with self.assertRaisesRegex(RuntimeError, "ghost-entry"):
            runner.mark_entry_blocked(config, "ghost-entry", "git_state", "模擬")
        self.assertEqual(runner.load_queue(config), before)

    def test_cli_blocked_for_missing_entry_does_not_notify(self):
        """apply_outcome(blocked) 遇到已被移除的 entry：拋錯走 crash 流程，不發「卡住」通知。

        @return None
        """
        # STEP 01: 呼叫
        with self.assertRaisesRegex(RuntimeError, "ghost-entry"):
            runner.apply_outcome(self.fixture["config"], "ghost-entry", {"kind": "blocked", "detail": "too_large"})
        # STEP 02: 沒有通知
        self.mocks["notify"].assert_not_called()


class PreflightMergeCleanupTest(unittest.TestCase):
    """第二批（review IMPORTANT）：前置作業兩處合併失敗改用共用收尾 helper——清單讀取失敗與 abort 失敗寫進 detail，暫停原因與流程不變。"""

    def _preflight(self, fixture, prefix, response):
        """注入一種 git 失敗後跑前置作業。

        @param fixture base_conflict_fixture／checkpoint_conflict_fixture 的回傳值
        @param prefix 要注入失敗的 git 參數開頭
        @param response 注入的 (returncode, stdout, stderr)
        @return module_preflight 的回傳值 (ok, pause_reason, detail)
        """
        # STEP 01: 注入並跑前置作業
        # runner 設定
        config = fixture["config"]
        with mock.patch.object(runner, "git", git_with_override(prefix, response)):
            return runner.module_preflight(config, runner.load_queue(config))

    def test_merge_cleanup_failures_are_reported_with_same_reason(self):
        """基準分支合併與斷點回流 × 清單讀取失敗與 abort 失敗：一律 master_conflict，細節帶該失敗的原文。

        @return None
        """
        # 每組是 (情境名稱, fixture 建構函式, 注入的 git 參數開頭, 注入的 stderr, 細節裡必須出現的字)
        cases = (
            ("base-list", base_conflict_fixture, ("diff", "--name-only", "--diff-filter=U"), "list boom", "衝突檔清單讀取失敗"),
            ("base-abort", base_conflict_fixture, ("merge", "--abort"), "abort boom", "merge --abort 也失敗"),
            ("cp-list", checkpoint_conflict_fixture, ("diff", "--name-only", "--diff-filter=U"), "list boom", "衝突檔清單讀取失敗"),
            ("cp-abort", checkpoint_conflict_fixture, ("merge", "--abort"), "abort boom", "merge --abort 也失敗"),
        )
        # 見上面 cases 的說明
        for label, make_fixture, prefix, stderr, marker in cases:
            with self.subTest(label):
                # STEP 01: 注入失敗後跑前置作業
                # 前置作業的結果：是否通過、暫停原因、細節
                ok, reason, detail = self._preflight(make_fixture(), prefix, (128, "", stderr))
                # STEP 02: 原因不變、細節帶失敗原文
                self.assertFalse(ok)
                self.assertEqual(reason, "master_conflict", detail)
                self.assertIn(marker, detail)
                self.assertIn(stderr, detail)

    def test_conflict_files_still_listed(self):
        """對照組：沒注入失敗時，基準分支衝突的細節照舊列出衝突檔、原因是 master_conflict、合併已 abort。

        @return None
        """
        # STEP 01: 前置作業
        # 測試用的 git 環境與狀態目錄
        fixture = base_conflict_fixture()
        # 前置作業的結果：是否通過、暫停原因、細節
        ok, reason, detail = self._preflight(fixture, ("no-such-git-command",), (0, "", ""))
        # STEP 02: 原因、衝突檔、已 abort
        self.assertEqual((ok, reason), (False, "master_conflict"), detail)
        self.assertIn(R15_RELATIVE_PATH, detail)
        self.assertFalse(os.path.exists(os.path.join(fixture["config"]["repo_dir"], ".git", "MERGE_HEAD")))


if __name__ == "__main__":
    unittest.main()
