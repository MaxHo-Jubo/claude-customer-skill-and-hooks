"""runner.py 1.1.2 第五批收尾修正的 review（112i）回歸測試：凍結點 frozen_sha、merged 蓋章、等待期間補查的去重與退避。

test_reconcile_followups.py 已近 800 行上限，另開這個檔；情境沿用它的真實拓撲 RealTopologyHarness（master 與整合分支分岔、
pr_base＝master）。新欄位與新常數一律寫成字面值，不 getattr——修正前不存在，直接取會以 AttributeError 失敗、不是 AssertionError。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 420; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_reconcile_followups_review.py -v
"""

import os
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runner  # noqa: E402  pylint: disable=wrong-import-position
from fake_gh import gh_commands, set_gh_modes  # noqa: E402  pylint: disable=wrong-import-position
from test_checkpoint_reconcile import CP_BRANCH, OPEN_FAILED_REASON, checkpoint, kill_after_gh  # noqa: E402  pylint: disable=wrong-import-position
from test_reconcile import HARD_CHECKPOINT_ID, SECOND_ENTRY_ID, SimulatedKill, add_entry, events  # noqa: E402  pylint: disable=wrong-import-position
from test_reconcile_followups import (  # noqa: E402  pylint: disable=wrong-import-position
    REAL_WAIT_FOR_RELEASE,
    RealTopologyHarness,
    git_failing_when,
    release,
)
from review_fixtures import BASE_BRANCH, ENTRY_ID, INTEGRATION_BRANCH, remote_tip, run_git  # noqa: E402  pylint: disable=wrong-import-position

# 退避測試裡第幾次輪詢時放行
RELEASE_ON_POLL = 20
# 放行前的輪詢次數內，補查最多該跑幾次（1、3、7、15 → 4 次；留一次餘裕，只要求遠少於每次輪詢都查的 19 次）
MAX_VERIFY_CALLS_BEFORE_RELEASE = 5
# 同一個斷點連續補查失敗的次數（事件去重用）
REPEATED_VERIFY_CALLS = 3


class FrozenShaMergedTest(RealTopologyHarness):
    """review 112i CRITICAL：「已合併」只看 write-ahead 凍結的 frozen_sha，不看本機同名的 cp 分支。"""

    def put_stale_local_cp_branch(self):
        """本機放一支同名、早已在 master 裡的舊 cp 分支（佇列重建後又用了同一個宣告 id）。

        @return None
        """
        # STEP 01: 指向 master 的上一個 commit
        run_git(self.work, "branch", "-f", CP_BRANCH, run_git(self.work, "rev-parse", "origin/%s~1" % BASE_BRANCH))

    def assert_reopened_and_waiting(self):
        """重啟後：沒被標 merged、正常補開、停在等待。

        @return None
        """
        # STEP 01: opened、create 1 次、等待 w0、e2 沒被處理
        self.assertEqual(checkpoint(self.config)["status"], "opened")
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        self.mocks["wait_for_release"].assert_called_with(self.config, HARD_CHECKPOINT_ID)
        self.mocks["process_one_entry"].assert_not_called()

    def test_stale_local_branch_on_legacy_record_does_not_pass_gate(self):
        """p1：舊記錄（沒有 frozen_sha）停在 opening、本機有已在 master 的舊同名分支 → 不判 merged，補開並等待。

        @return None
        """
        # STEP 01: opening（write-ahead 之後、branch -f 之前停下）＋舊分支 → 重啟
        self.set_checkpoint(status="opening", branch=CP_BRANCH)
        self.put_stale_local_cp_branch()
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assert_reopened_and_waiting()

    def test_stale_local_branch_with_unmerged_frozen_sha_does_not_pass_gate(self):
        """記錄有 frozen_sha（整合分支 tip，不在 master）、本機有已在 master 的舊同名分支 → 不判 merged，cp 凍結在 frozen_sha。

        @return None
        """
        # STEP 01: opening＋凍結點＋舊分支 → 重啟
        frozen = run_git(self.work, "rev-parse", INTEGRATION_BRANCH)
        self.set_checkpoint(status="opening", branch=CP_BRANCH, frozen_sha=frozen, covered_entries=[ENTRY_ID])
        self.put_stale_local_cp_branch()
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assert_reopened_and_waiting()
        self.assertEqual(remote_tip(self.fixture, CP_BRANCH), frozen)

    def test_merged_frozen_sha_is_marked_merged_without_local_branch(self):
        """對照組：frozen_sha 確實已被合進 master（本機 cp 分支已刪）→ 標 merged、不 create、閘門已過。

        @return None
        """
        # STEP 01: 中斷 → 人合併 → 本機分支刪掉 → 重啟
        self.kill_while_opening_hard()
        self.human_merges_cp_pr()
        run_git(self.work, "branch", "-D", CP_BRANCH)
        self.restart()
        # STEP 02: merged、create 只有第一輪那次、e2 被處理
        self.assertEqual(checkpoint(self.config)["status"], "merged")
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        self.mocks["process_one_entry"].assert_called_once()

    def test_unreadable_integration_tip_fails_open(self):
        """讀不到整合分支 tip（凍結點無從得知）→ 仍寫 opening（閘門不消失）、以 checkpoint_open_failed 暫停，不拿別的 ref 湊。

        @return None
        """
        # STEP 01: 只讓讀整合分支 tip 的 rev-parse 失敗 → 重啟
        target = ("rev-parse", "--verify", "refs/heads/%s" % INTEGRATION_BRANCH)
        with git_failing_when(lambda args: args == target):
            self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # STEP 02: opening、沒有凍結點、開啟失敗的暫停
        found = checkpoint(self.config)
        self.assertEqual((found["status"], found.get("frozen_sha")), ("opening", None))
        self.assertEqual(self.runner_state().get("reason"), OPEN_FAILED_REASON)

    def test_new_fields_survive_reimport(self):
        """frozen_sha、covered_entries 在 CHECKPOINT_FIELD_DEFAULTS（import-inventory 重匯入只保留這裡列的欄位）。

        @return None
        """
        # STEP 01: 欄位清單
        self.assertLessEqual({"frozen_sha", "covered_entries"}, set(runner.CHECKPOINT_FIELD_DEFAULTS))


class CoveredEntriesTest(RealTopologyHarness):
    """review 112i MINOR：蓋章集合是 write-ahead 時凍結的 covered_entries；merged 也要蓋章。"""

    def test_merged_while_opening_stamps_covered_entries(self):
        """p2：hard 斷點補完時判 merged → e1 蓋 w0 的章，之後不被算進 auto 斷點。

        @return None
        """
        # STEP 01: 中斷 → 人合併 → 重啟（e2 做完、門檻 2）
        self.kill_while_opening_hard()
        self.human_merges_cp_pr()
        self.mark_done_on_process()
        self.config["checkpoint_max_modules"] = 2
        self.restart()
        # STEP 02: e1 蓋 w0；沒有 auto 斷點
        queue = runner.load_queue(self.config)
        self.assertEqual(runner.find_entry(queue, ENTRY_ID)["checkpoint_id"], HARD_CHECKPOINT_ID)
        self.assertEqual([item["id"] for item in queue["checkpoints"]], [HARD_CHECKPOINT_ID])

    def test_resumed_auto_keeps_frozen_tip_and_covered_set(self):
        """auto 斷點 create 後被殺；補完前又有 e2 做完、整合分支前進 → cp 仍凍結在原本的 tip，只替 e1 蓋章、e2 不蓋。

        @return None
        """
        # STEP 01: 只有 e1、沒有宣告的斷點；auto create 後被殺
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": [], "modules": queue["modules"][:1]}))
        self.config["checkpoint_max_modules"] = 1
        frozen = run_git(self.work, "rev-parse", INTEGRATION_BRANCH)
        with kill_after_gh("pr create"):
            with self.assertRaises(SimulatedKill):
                runner.handle_checkpoints(self.config)
        # 被中斷的 auto 斷點 id
        auto_id = runner.load_queue(self.config)["checkpoints"][0]["id"]
        # STEP 02: e2 做完、整合分支前進
        add_entry(self.fixture, SECOND_ENTRY_ID, "e2-branch", status="done", wave=1)
        with open(os.path.join(self.work, "e2.js"), "w", encoding="utf-8") as handle:
            handle.write("// e2\n")
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", "e2")
        # STEP 03: 補完
        self.assertTrue(runner.open_checkpoint(self.config, auto_id))
        queue = runner.load_queue(self.config)
        self.assertEqual(runner.find_checkpoint(queue, auto_id)["status"], "opened")
        # 這個 auto 斷點的 cp 分支（本機與遠端都要停在凍結點：前置作業回流與 merged 偵測讀的是本機分支）
        cp_branch = "r18-migration/cp-%s" % auto_id
        self.assertEqual((run_git(self.work, "rev-parse", cp_branch), remote_tip(self.fixture, cp_branch)), (frozen, frozen))
        self.assertEqual(runner.find_entry(queue, ENTRY_ID)["checkpoint_id"], auto_id)
        self.assertIsNone(runner.find_entry(queue, SECOND_ENTRY_ID)["checkpoint_id"])


class VerifyNoiseTest(RealTopologyHarness):
    """review 112i MINOR：等待期間補查不可每次輪詢都留一份 log／一筆事件。"""

    def setUp(self):
        """w0 opened＋連結未知；GitHub 上沒有 PR、查詢失敗。

        @return None
        """
        # STEP 01: opened＋pr_unverified；查詢失敗
        super().setUp()
        self.set_checkpoint(status="opened", branch=CP_BRANCH, pr_url="", pr_unverified=True)
        set_gh_modes(self.gh, list_mode="fail")
        self.config.update({"max_wait_hours": 24, "notify_pause_remind_hours": 24})

    def test_repeated_failure_is_logged_once_per_kind(self):
        """同一個斷點連續查詢失敗 → 事件只記一次；結果種類改變（查得到、但沒有 PR）→ 再記一次。

        @return None
        """
        # STEP 01: 失敗 N 次
        for _index in range(REPEATED_VERIFY_CALLS):
            runner.refresh_unverified_checkpoint_prs(self.config)
        self.assertEqual(len(events(self.config, "checkpoint_pr_verify_failed")), 1)
        # STEP 02: 改成查得到、沒有 PR
        set_gh_modes(self.gh, list_mode="ok")
        for _index in range(REPEATED_VERIFY_CALLS):
            runner.refresh_unverified_checkpoint_prs(self.config)
        self.assertEqual(len(events(self.config, "checkpoint_pr_still_unverified")), 1)

    def test_waiting_backs_off_verify_calls(self):
        """等待 19 次輪詢才放行 → 補查（gh pr list）遠少於 19 次。

        @return None
        """
        # 已經 sleep 的次數
        sleeps = []

        def fake_sleep(seconds):
            """第 RELEASE_ON_POLL 次放行。"""
            sleeps.append(seconds)
            if len(sleeps) == RELEASE_ON_POLL:
                release(self.config)

        # STEP 01: 等待
        with mock.patch.object(runner.time, "sleep", fake_sleep):
            self.assertIs(REAL_WAIT_FOR_RELEASE(self.config, HARD_CHECKPOINT_ID), True)
        # STEP 02: 補查次數
        calls = gh_commands(self.gh).count("pr list")
        self.assertGreaterEqual(calls, 1)
        self.assertLessEqual(calls, MAX_VERIFY_CALLS_BEFORE_RELEASE)


if __name__ == "__main__":
    unittest.main()
