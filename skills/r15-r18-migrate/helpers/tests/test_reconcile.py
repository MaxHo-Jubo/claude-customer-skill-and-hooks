"""runner.py 1.1.2 第五批階段一的回歸測試：重啟對帳（已知缺口 b）、發佈段延後區間、人工提示、啟動時的斷點檢查。

情境都是「真的中斷 → cmd_run 重啟」：真 bare 遠端＋工作 repo 上真的 ff-merge 並推送整合分支，然後以一個
不被任何 except 接住的 BaseException（模擬 SIGKILL／斷電）打斷在「done 寫回 queue」之前，再用 cmd_run 重啟。
cmd_run 只隔離與受測行為無關的外部依賴：CLI 旗標／認證 smoke（preflight 換成只做「把 running 放回 pending」）、
額度查詢、通知、診斷包、進度報表、等人放行（wait_for_release 換成立刻回報逾時）；CLI 本身（process_one_entry）
換成記錄器——「不呼叫 CLI」就是斷言它沒被叫到。git 前置、對帳、開斷點都用真的。

對帳的新函式不直接呼叫：修正前它不存在，直接呼叫會以 AttributeError 失敗、不是以 AssertionError 證明「還沒修」。
略過的原因代號（reconcile_skipped 事件）寫成字面值，同時釘住操作者在 runner.log.jsonl 看到的字串。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import argparse
import contextlib
import io
import json
import os
import signal
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    ENTRY_BRANCH,
    ENTRY_ID,
    EXISTING_PR_URL,
    FAKE_PR_URL,
    INTEGRATION_BRANCH,
    R15_RELATIVE_PATH,
    build_fixture,
    queue_entry,
    reject_entry_branch_push,
    remote_tip,
    run_git,
    start_patches,
)

# 被中斷那一輪 CLI 的 session id（process_one_entry 在發佈段之前寫進 cli_outcome 事件的值）
CRASHED_SESSION_ID = "session-crashed-round"
# 被中斷那一輪 CLI 的花費：done 那一輪的花費只在 done 寫回時累加，tip 沒記就代表沒記過，對帳要從 cli_outcome 事件補記
CRASHED_ROUND_COST = 0.7
# entry 在被中斷之前已經累計的花費
PRIOR_COST_TOTAL = 1.25
# 第二個 entry（wave 1，排在斷點之後；主迴圈若先處理它就是繞過了 hard 閘門）
SECOND_ENTRY_ID = "e2"
SECOND_ENTRY_BRANCH = "e2-branch"
# wave 0 完成後觸發的 hard 斷點
HARD_CHECKPOINT_ID = "w0"
# 發佈段延後區間內推送整合分支與 ls-remote 的逾時上限（秒）：計畫定的外部契約，不讀實作的常數
EXPECTED_PUSH_TIMEOUT_SECONDS = 45
EXPECTED_LS_REMOTE_TIMEOUT_SECONDS = 15
# P5 情境：遠端 pre-receive hook 每次收推送都睡這麼久（秒），整合分支推送逾時縮到比它短，造出「逾時被 kill、遠端晚一點收下」
LATE_HOOK_SLEEP_SECONDS = 3
# P5 情境裡整合分支推送的逾時（秒），要比 LATE_HOOK_SLEEP_SECONDS 短
LATE_PUSH_TIMEOUT_SECONDS = 1
# 等遠端晚收下的上限與輪詢間隔（秒）
LATE_LANDING_WAIT_SECONDS = 15
LATE_LANDING_POLL_SECONDS = 0.2


class SimulatedKill(BaseException):
    """模擬 SIGKILL／斷電：不是 Exception，也不是 ShutdownSignal，任何 except 都接不住、延後區間也擋不住。"""


def events(config, name):
    """runner.log.jsonl 裡所有指定名稱的事件（由舊到新）。

    @param config runner 設定
    @param name 事件名稱
    @return 事件 dict 清單
    """
    # STEP 01: 逐行解析、篩選
    # 事件紀錄檔路徑
    path = runner.state_path(config, "runner.log.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return [record for record in map(json.loads, handle) if record.get("event") == name]


def skip_reasons(config):
    """所有 reconcile_skipped 事件的原因代號。

    @param config runner 設定
    @return 原因代號清單
    """
    # STEP 01: 取 detail.reason
    return [record["detail"]["reason"] for record in events(config, "reconcile_skipped")]


def add_entry(fixture, entry_id, branch, **fields):
    """在 queue 裡多登記一個 entry（沿用 fixture entry 的靜態欄位）。

    @param fixture build_fixture 的回傳值
    @param entry_id 新 entry 的 id
    @param branch 新 entry 的分支名稱
    @param fields 要覆寫的欄位（status、wave…）
    @return None
    """
    # STEP 01: 組出 entry 後追加
    # 新 entry
    entry = dict(fixture["entry"], id=entry_id, branch=branch, **fields)
    runner.mutate_queue(fixture["config"], lambda queue: queue["modules"].append(entry))


def add_hard_checkpoint(fixture):
    """登記一個 wave 0 完成後觸發的 hard 斷點。

    @param fixture build_fixture 的回傳值
    @return None
    """
    # STEP 01: 宣告的斷點（pending）
    # 斷點記錄
    checkpoint = dict(
        runner.CHECKPOINT_FIELD_DEFAULTS, id=HARD_CHECKPOINT_ID, after={"wave": 0}, mode="hard", title="wave 0", pr_base=INTEGRATION_BRANCH
    )
    runner.mutate_queue(fixture["config"], lambda queue: queue.setdefault("checkpoints", []).append(checkpoint))


def publish(fixture, kill_before_done):
    """真的跑一次發佈段（開 PR、ff-merge、推送整合分支）；kill_before_done 為真時在 done 寫回之前被殺。

    先照 process_one_entry 的順序寫一筆 cli_outcome 事件——那是對帳時唯一找得到這一輪 session id 的地方。

    @param fixture build_fixture 的回傳值
    @param kill_before_done 是否在 finish_done_entry 之前模擬行程被殺
    @return None
    """
    # STEP 01: 這一輪 CLI 的判讀事件
    # runner 設定
    config = fixture["config"]
    runner.log_event(config, ENTRY_ID, "cli_outcome", attempt=1, session_id=CRASHED_SESSION_ID, cost_usd=CRASHED_ROUND_COST)
    # CLI 判讀結果
    outcome = {"structured": {}, "session_id": CRASHED_SESSION_ID, "cost": CRASHED_ROUND_COST}
    # STEP 02: 發佈；被殺的那種要確認整合分支真的已經推上去
    if not kill_before_done:
        runner.publish_verified_entry(config, fixture["entry"], outcome, 1)
        return
    with mock.patch.object(runner, "finish_done_entry", side_effect=SimulatedKill):
        try:
            runner.publish_verified_entry(config, fixture["entry"], outcome, 1)
        except SimulatedKill:
            pass
    assert remote_tip(fixture, INTEGRATION_BRANCH) == fixture["entry_sha"], "前置條件：整合分支應已推上去"
    assert queue_entry(fixture)[1]["status"] == "running", "前置條件：done 應尚未寫回"


class RestartHarness(unittest.TestCase):
    """cmd_run 重啟的共用隔離；子類別在 setUp 之後自己造「中斷之前」的狀態。"""

    def setUp(self):
        """fixture＋cmd_run 的隔離。

        @return None
        """
        # STEP 01: 真的 git 環境；基準分支設成整合分支本身，前置作業的基準合併是 no-op（這裡不測它）
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-reconcile-"), {"cost_usd_total": PRIOR_COST_TOTAL})
        # runner 設定
        self.config = self.fixture["config"]
        self.config.update(
            {
                "base_branch": INTEGRATION_BRANCH,
                "circuit_breaker_n": 3,
                "checkpoint_max_modules": 100,
                "checkpoint_max_lines": 100000,
            }
        )
        # STEP 02: 隔離
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(
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
            "write_progress",
            "render_progress_text",
            "freeze_runner_bundle",
            "freeze_entry_bundle",
            "wait_for_release",
            "process_one_entry",
        )
        self.mocks["require_config"].return_value = True
        self.mocks["lockfile_hash"].return_value = None
        self.mocks["preflight"].side_effect = self._preflight
        self.mocks["environment_fingerprint"].return_value = {}
        self.mocks["quota_snapshot"].return_value = {}
        self.mocks["quota_blocks_start"].return_value = (False, "", None)
        self.mocks["render_progress_text"].return_value = "body"
        self.mocks["freeze_runner_bundle"].return_value = None
        self.mocks["freeze_entry_bundle"].return_value = None
        self.mocks["wait_for_release"].return_value = False
        self.mocks["process_one_entry"].return_value = runner.EXIT_PAUSED

    def _preflight(self, config):
        """代替 preflight：只做它對 queue 的那件事——把上一輪被中斷的 entry 放回 pending。

        @param config runner 設定
        @return 0（通過）
        """
        # STEP 01: 與 preflight 的 mutator 同一個函式
        runner.mutate_queue(config, runner.recover_interrupted_entries)
        return 0

    def restart(self):
        """launchd 重啟：跑一次 cmd_run（最多處理一個模組）。

        @return cmd_run 的退出碼
        """
        # STEP 01: 主迴圈
        return runner.cmd_run(self.config, argparse.Namespace(max_modules=1))

    def assert_not_reconciled(self, pause_reason, skip_reason):
        """沒有對帳：entry 不是 done、tip 沒動、照舊暫停，而且 log 說明了為什麼沒對帳。

        @param pause_reason 預期的暫停原因
        @param skip_reason 預期的 reconcile_skipped 原因代號
        @return None
        """
        # STEP 01: 狀態與原因
        queue, entry = queue_entry(self.fixture)
        self.assertNotEqual(entry["status"], "done")
        self.assertEqual(queue["integration_tip_sha"], self.fixture["base_sha"])
        self.assertEqual(queue["runner_state"].get("reason"), pause_reason, queue["runner_state"])
        self.assertIn(skip_reason, skip_reasons(self.config))


class ReconcileAfterPushTest(RestartHarness):
    """(b) 整合分支已推送、done 沒寫回：重啟時對帳補 done，不呼叫 CLI。"""

    def test_crash_after_push_is_reconciled_on_restart(self):
        """必測 4：push 成功後被殺 → 重啟補 done：tip、hash、session id 正確，花費補記那一輪的一次（review 4a），CLI 一次都不呼叫。

        修正前：前置作業看到遠端 tip 與記錄值不同 → paused(integration_diverged)；照舊提示跑 --integration-tip 之後
        CLI 判 no_commit、attempts 累加，這個 entry 永遠到不了 done。

        @return None
        """
        # STEP 01: 中斷 → 重啟
        publish(self.fixture, kill_before_done=True)
        self.assertEqual(self.restart(), runner.EXIT_OK)
        # STEP 02: done 與收尾資料
        queue, entry = queue_entry(self.fixture)
        self.assertEqual(entry["status"], "done", queue["runner_state"])
        self.assertEqual(queue["integration_tip_sha"], self.fixture["entry_sha"])
        self.assertEqual(entry["last_commit"], self.fixture["entry_sha"])
        self.assertEqual(list(entry["r15_hashes"]), [R15_RELATIVE_PATH])
        self.assertIsNotNone(entry["r15_hashes"][R15_RELATIVE_PATH])
        self.assertEqual(entry["last_session_id"], CRASHED_SESSION_ID)
        self.assertAlmostEqual(entry["cost_usd_total"], PRIOR_COST_TOTAL + CRASHED_ROUND_COST)
        self.assertEqual(entry["pr_url"], FAKE_PR_URL)
        self.assertFalse(entry["pr_failed"])
        # STEP 03: CLI 沒被呼叫、有對帳通知
        self.mocks["process_one_entry"].assert_not_called()
        self.assertIn("reconciled_done", [call.args[1] for call in self.mocks["notify"].call_args_list])

    def test_missing_pr_url_is_reported_as_pr_error(self):
        """對帳時 queue 沒有 PR 連結（階段一不查 GitHub）：照樣補 done，但 pr_failed 要是真、原因要記下來，不能假裝有 PR。

        @return None
        """
        # STEP 01: 中斷之後把連結拿掉（等同 PR 步驟這一輪沒拿到連結）→ 重啟
        publish(self.fixture, kill_before_done=True)

        def drop_pr_url(queue):
            """mutate_queue 用：清掉 entry 的 pr_url。"""
            # STEP 01: 就地清空
            runner.find_entry(queue, ENTRY_ID)["pr_url"] = None

        runner.mutate_queue(self.config, drop_pr_url)
        self.restart()
        # STEP 02: done、pr_failed、有 pr_failed 事件
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertTrue(entry["pr_failed"])
        self.assertEqual(len(events(self.config, "pr_failed")), 1)

    def test_single_pending_match_ignores_non_pending_entries(self):
        """分支指向同一個 commit 的其他 entry 不是 pending（failed）：不算候選，唯一的 pending 那個照樣對帳。

        @return None
        """
        # STEP 01: e2 已 failed、分支也指向 entry commit
        publish(self.fixture, kill_before_done=True)
        run_git(self.config["repo_dir"], "branch", SECOND_ENTRY_BRANCH, self.fixture["entry_sha"])
        add_entry(self.fixture, SECOND_ENTRY_ID, SECOND_ENTRY_BRANCH, status="failed")
        self.restart()
        # STEP 02: e1 done
        self.assertEqual(queue_entry(self.fixture)[1]["status"], "done")


class ReconcileReviewFixTest(RestartHarness):
    """第五批階段一 review 修正（P1／P3／P5）：對帳補 done 之後的 auto 斷點、頁面分支沒推上去的 pr_failed、推送逾時後遠端晚收下。"""

    def test_reconciled_done_checks_auto_checkpoint(self):
        """P1：被對帳的是最後一個 entry、auto 門檻已到 → 對帳補 done 那一次要開 auto 斷點（等同那個模組剛完成）。

        修正前：啟動時一律不看 auto，之後佇列沒有下一個模組完成，auto 斷點永遠不開。

        @return None
        """
        # STEP 01: 沒有宣告的斷點、門檻 1、中斷 → 重啟
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": []}))
        self.config["checkpoint_max_modules"] = 1
        publish(self.fixture, kill_before_done=True)
        self.restart()
        # STEP 02: auto 斷點開了、entry 蓋章
        queue, entry = queue_entry(self.fixture)
        self.assertEqual([item["id"][:5] for item in queue.get("checkpoints", [])], ["auto-"], queue.get("checkpoints"))
        self.assertEqual(entry["checkpoint_id"], queue["checkpoints"][0]["id"])

    def test_entry_branch_not_pushed_marks_pr_failed(self):
        """P3：這一輪頁面分支推送被拒（既有 PR 沒更新到這個 commit）後被殺 → 對帳要記 pr_failed，與沒被殺時的收尾一致。

        @return None
        """
        # STEP 01: 上一輪已有 PR 連結、遠端拒絕頁面分支 → 發佈（被殺）→ 重啟
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, ENTRY_ID).update({"pr_url": EXISTING_PR_URL}))
        self.fixture["entry"]["pr_url"] = EXISTING_PR_URL
        reject_entry_branch_push(self.fixture["remote"])
        publish(self.fixture, kill_before_done=True)
        self.restart()
        # STEP 02: done、pr_failed、連結沿用、有 pr_failed 事件
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertTrue(entry["pr_failed"])
        self.assertEqual(entry["pr_url"], EXISTING_PR_URL)
        self.assertEqual(len(events(self.config, "pr_failed")), 1)

    def test_push_timeout_then_late_landing_is_reconciled(self):
        """P5：推送逾時被 kill → 本機退回、以推送失敗暫停 → 遠端晚一點收下 → 重啟時本機整合分支停在記錄值，要快轉後補 done。

        修正前：對帳以 local_not_at_remote 略過 → integration_diverged，提醒叫人跑 --integration-tip，照做就是 (b)。

        @return None
        """
        # STEP 01: 遠端 hook 每次收推送都睡 LATE_HOOK_SLEEP_SECONDS 秒，整合分支推送逾時縮到 LATE_PUSH_TIMEOUT_SECONDS 秒
        hook = os.path.join(self.fixture["remote"], "hooks", "pre-receive")
        with open(hook, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/bash\ncat >/dev/null\nsleep %d\nexit 0\n" % LATE_HOOK_SLEEP_SECONDS)
        os.chmod(hook, os.stat(hook).st_mode | stat.S_IXUSR)
        with mock.patch.object(runner, "PUBLISH_PUSH_TIMEOUT_SECONDS", LATE_PUSH_TIMEOUT_SECONDS):
            publish(self.fixture, kill_before_done=False)
        # 前置條件：本機退回、以推送失敗暫停
        state = runner.load_queue(self.config)["runner_state"]
        self.assertEqual(state.get("crash_signature"), runner.PUSH_FAILED_SIGNATURE, state)
        self.assertEqual(run_git(self.config["repo_dir"], "rev-parse", INTEGRATION_BRANCH), self.fixture["base_sha"])
        # STEP 02: 等遠端真的收下
        deadline = time.monotonic() + LATE_LANDING_WAIT_SECONDS
        while remote_tip(self.fixture, INTEGRATION_BRANCH) != self.fixture["entry_sha"] and time.monotonic() < deadline:
            time.sleep(LATE_LANDING_POLL_SECONDS)
        self.assertEqual(remote_tip(self.fixture, INTEGRATION_BRANCH), self.fixture["entry_sha"], "前置條件：遠端應晚一點收下")
        os.remove(hook)
        # STEP 03: 重啟 → done、本機快轉到 entry commit
        self.restart()
        queue, entry = queue_entry(self.fixture)
        self.assertEqual(entry["status"], "done", skip_reasons(self.config))
        self.assertEqual(queue["integration_tip_sha"], self.fixture["entry_sha"])
        self.assertEqual(run_git(self.config["repo_dir"], "rev-parse", INTEGRATION_BRANCH), self.fixture["entry_sha"])

    def test_skipped_reconcile_warns_against_integration_tip(self):
        """P5 (ii)：對帳略過、但遠端 tip 是 pending entry 的 commit → 暫停細節與 unblock 兩個子命令都不可以叫人跑 --integration-tip；
        --integration-tip 直接拒絕（事後才提醒來不及），記錄值不動。

        @return None
        """
        # STEP 01: 兩個 pending 都指向 entry commit（對帳略過）→ 重啟 → integration_diverged
        publish(self.fixture, kill_before_done=True)
        run_git(self.config["repo_dir"], "branch", SECOND_ENTRY_BRANCH, self.fixture["entry_sha"])
        add_entry(self.fixture, SECOND_ENTRY_ID, SECOND_ENTRY_BRANCH, status="pending")
        self.restart()
        # 暫停細節
        detail = events(self.config, "paused")[-1]["detail"]["detail"]
        self.assertIn("不要跑 --integration-tip", detail)
        # STEP 02: --integration-tip 拒絕、記錄值不動
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = runner.unblock_integration_tip(self.config)
        self.assertEqual(code, runner.EXIT_USAGE)
        self.assertIn("不要跑 --integration-tip", err.getvalue())
        self.assertEqual(runner.load_queue(self.config)["integration_tip_sha"], self.fixture["base_sha"])
        # STEP 03: --runner 的提醒
        with contextlib.redirect_stdout(io.StringIO()) as out:
            runner.unblock_runner(self.config)
        self.assertIn("不要跑 --integration-tip", out.getvalue())


class ReconcileRefusalTest(RestartHarness):
    """判準任一不成立就不動，交給既有的暫停。"""

    def test_no_commit_entry_at_recorded_tip_is_not_marked_done(self):
        """必測 5（護欄）：no_commit 的 entry 分支 == origin == 記錄值（prepare 把分支快轉到整合分支 tip、CLI 沒 commit）——
        不可以被當成已推送而標 done；照常重跑 CLI。修正前也是綠的，靠突變「拿掉 origin ≠ 記錄值」驗它有在守。

        @return None
        """
        # STEP 01: entry 分支退回整合分支 tip、entry 放回 pending
        run_git(self.config["repo_dir"], "checkout", INTEGRATION_BRANCH)
        run_git(self.config["repo_dir"], "branch", "-f", ENTRY_BRANCH, INTEGRATION_BRANCH)
        runner.mutate_queue(self.config, runner.recover_interrupted_entries)
        # STEP 02: 重啟 → CLI 被呼叫的那一刻 entry 仍不是 done
        # CLI 被呼叫當下 entry 的狀態
        seen = []
        self.mocks["process_one_entry"].side_effect = lambda config, entry: seen.append(queue_entry(self.fixture)[1]["status"]) or runner.EXIT_PAUSED
        self.restart()
        self.assertEqual(seen, ["pending"])
        self.assertEqual(runner.load_queue(self.config)["integration_tip_sha"], self.fixture["base_sha"])
        self.assertEqual(events(self.config, "reconciled_done"), [])

    def test_someone_pushed_after_crash_keeps_diverged_pause(self):
        """必測 6：被殺之後有人又推了整合分支 → 沒有 entry 分支等於 origin tip，不對帳，照舊 integration_diverged。

        @return None
        """
        # STEP 01: 中斷 → 另一個 clone 在整合分支上多推一個 commit
        publish(self.fixture, kill_before_done=True)
        # 別人的 clone
        other = os.path.join(tempfile.mkdtemp(prefix="r18-reconcile-other-"), "other")
        run_git(os.path.dirname(other), "clone", "-q", "-b", INTEGRATION_BRANCH, self.fixture["remote"], other)
        run_git(other, "-c", "user.name=x", "-c", "user.email=x@example.invalid", "commit", "-q", "--allow-empty", "-m", "foreign")
        run_git(other, "push", "-q", "origin", INTEGRATION_BRANCH)
        # STEP 02: 重啟
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assert_not_reconciled("integration_diverged", "entry_match")
        self.mocks["process_one_entry"].assert_not_called()

    def test_missing_local_entry_branch_is_not_reconciled(self):
        """必測 7a：本機 entry 分支不存在 → 找不到候選，不對帳，照舊 integration_diverged。

        @return None
        """
        # STEP 01: 中斷 → 刪掉本機 entry 分支
        publish(self.fixture, kill_before_done=True)
        run_git(self.config["repo_dir"], "branch", "-D", ENTRY_BRANCH)
        # STEP 02: 重啟
        self.restart()
        self.assert_not_reconciled("integration_diverged", "entry_match")

    def test_dirty_tree_is_not_reconciled(self):
        """必測 7b：工作樹髒 → R15 hash 會記到髒的內容，不對帳，照舊暫停（前置作業判 integration_dirty）。

        @return None
        """
        # STEP 01: 中斷 → 改一個已追蹤檔
        publish(self.fixture, kill_before_done=True)
        with open(os.path.join(self.config["repo_dir"], R15_RELATIVE_PATH), "a", encoding="utf-8") as handle:
            handle.write("// dirty\n")
        # STEP 02: 重啟
        self.restart()
        self.assert_not_reconciled("integration_dirty", "tree_dirty")

    def test_local_integration_behind_origin_is_not_reconciled(self):
        """本機整合分支既不是 origin tip、也不是記錄值：快轉不過去、工作樹不是那個 commit 的樹，R15 hash 會記錯，不對帳。

        （停在記錄值的那一種是 P5：快轉後對帳，見 ReconcileReviewFixTest。）

        @return None
        """
        # STEP 01: 中斷 → 本機整合分支換成基線上另一個只在本機的 commit
        publish(self.fixture, kill_before_done=True)
        work = self.config["repo_dir"]
        run_git(work, "reset", "-q", "--hard", self.fixture["base_sha"])
        run_git(work, "commit", "-q", "--allow-empty", "-m", "local only")
        # STEP 02: 重啟
        self.restart()
        self.assert_not_reconciled("integration_diverged", "local_not_at_remote")

    def test_two_pending_matches_are_not_reconciled(self):
        """兩個 pending entry 的分支都等於 origin tip：不知道是哪一個，不對帳（不是挑第一個）。

        @return None
        """
        # STEP 01: 中斷 → e2 分支也指向 entry commit
        publish(self.fixture, kill_before_done=True)
        run_git(self.config["repo_dir"], "branch", SECOND_ENTRY_BRANCH, self.fixture["entry_sha"])
        add_entry(self.fixture, SECOND_ENTRY_ID, SECOND_ENTRY_BRANCH, status="pending")
        # STEP 02: 重啟
        self.restart()
        self.assert_not_reconciled("integration_diverged", "entry_match")

    def test_recorded_tip_not_ancestor_is_not_reconciled(self):
        """記錄值不是 origin tip 的祖先（merge-base 退出碼 1）：整合分支被改寫過，不對帳。

        @return None
        """
        # STEP 01: 中斷 → 記錄值換成一個不在 origin 歷史上的 commit
        publish(self.fixture, kill_before_done=True)
        work = self.config["repo_dir"]
        run_git(work, "checkout", "-q", "-b", "side", self.fixture["base_sha"])
        run_git(work, "commit", "-q", "--allow-empty", "-m", "side")
        # 不在 origin 歷史上的 commit
        side = run_git(work, "rev-parse", "HEAD")
        run_git(work, "checkout", "-q", INTEGRATION_BRANCH)
        runner.set_integration_tip(self.config, side)
        # STEP 02: 重啟
        self.restart()
        self.assertIn("recorded_not_ancestor", skip_reasons(self.config))
        self.assertNotEqual(queue_entry(self.fixture)[1]["status"], "done")

    def test_ancestry_check_failure_is_not_treated_as_no(self):
        """祖先檢查本身失敗（記錄值不是合法 commit，退出碼 128）：不對帳，而且原因與「不是祖先」分開記。

        @return None
        """
        # STEP 01: 中斷 → 記錄值換成不存在的 sha
        publish(self.fixture, kill_before_done=True)
        runner.set_integration_tip(self.config, "0" * 40)
        # STEP 02: 重啟
        self.restart()
        self.assertIn("ancestry_check_failed", skip_reasons(self.config))
        self.assertNotIn("recorded_not_ancestor", skip_reasons(self.config))
        self.assertNotEqual(queue_entry(self.fixture)[1]["status"], "done")


class StartupCheckpointTest(RestartHarness):
    """啟動時先看一次斷點（補 c3）：wave 已完成的 hard 斷點要在處理下一個模組之前開啟並等待。"""

    def setUp(self):
        """多一個 wave 1 的 pending entry 與 wave 0 的 hard 斷點。

        @return None
        """
        # STEP 01: 共用隔離＋拓撲
        super().setUp()
        add_entry(self.fixture, SECOND_ENTRY_ID, SECOND_ENTRY_BRANCH, status="pending", wave=1)
        add_hard_checkpoint(self.fixture)

    def assert_gate_held(self):
        """斷點已開、在等人放行，下一個模組沒被處理。

        @return None
        """
        # STEP 01: 斷點狀態、等待、CLI
        queue = runner.load_queue(self.config)
        self.assertEqual(runner.find_checkpoint(queue, HARD_CHECKPOINT_ID)["status"], "opened")
        self.mocks["wait_for_release"].assert_called_once_with(self.config, HARD_CHECKPOINT_ID)
        self.mocks["process_one_entry"].assert_not_called()
        self.assertEqual(queue["runner_state"].get("reason"), "paused_for_review")

    def test_reconciled_done_opens_due_hard_checkpoint(self):
        """必測 8：對帳補 done 之後 wave 0 完成，hard 斷點立刻開啟並等待，不先處理 e2。

        @return None
        """
        # STEP 01: 中斷 → 重啟
        publish(self.fixture, kill_before_done=True)
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # STEP 02: e1 done、閘門守住
        self.assertEqual(queue_entry(self.fixture)[1]["status"], "done")
        self.assert_gate_held()

    def test_crash_between_done_and_checkpoint_check(self):
        """必測 14（c3）：done 寫完、斷點檢查之前被殺 → 重啟時先開 due 的 hard 斷點，不先處理 e2。

        修正前：主迴圈只在「模組完成之後」看 pending 斷點、取件前只看 opened 的——重啟後直接處理 e2，閘門繞過一個模組。

        @return None
        """
        # STEP 01: 發佈段完整跑完（done 已落盤），之後的斷點檢查沒跑到 → 重啟
        publish(self.fixture, kill_before_done=False)
        self.assertEqual(queue_entry(self.fixture)[1]["status"], "done")
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # STEP 02: 閘門守住
        self.assert_gate_held()

    def test_startup_does_not_open_auto_checkpoint(self):
        """護欄：啟動時只看宣告的斷點，不開 auto 斷點——auto 開失敗不落盤，每次 launchd 重啟都會再推一支新 id 的 cp 分支。

        @return None
        """
        # STEP 01: 拿掉宣告的斷點、門檻降到 1、e1 done（沒蓋章）→ 重啟
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": []}))
        self.config["checkpoint_max_modules"] = 1
        publish(self.fixture, kill_before_done=False)
        self.restart()
        # STEP 02: gh 只被頁面 PR 叫過一次、queue 沒有 auto 斷點
        with open(self.fixture["gh_calls"], "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read().split("\n").count("pr create"), 1)
        self.assertEqual(runner.load_queue(self.config).get("checkpoints"), [])


class UnrecoveredHintTest(RestartHarness):
    """推送回報失敗而且問不到遠端（integration_unrecovered）：提示只叫人跑 unblock --runner，照做之後重啟會對帳補 done。"""

    def test_hint_then_unblock_runner_reconciles(self):
        """必測 9：照新提示只跑 unblock --runner → 重啟補 done。修正前的提示叫人跑 --integration-tip，照做就是 (b)。

        @return None
        """
        # STEP 01: 推送真的成功、但回報失敗，ls-remote 也失敗 → 鎖定
        real_git = runner.git

        def flaky_git(config, *args, **kwargs):
            """整合分支的 push 照推、回報失敗；ls-remote 一律失敗；其餘轉發。"""
            # STEP 01: 分流
            if args[:3] == ("push", "origin", INTEGRATION_BRANCH):
                real_git(config, *args, **kwargs)
                return 1, "", "simulated: connection reset after push"
            if args[:1] == ("ls-remote",):
                return 128, "", "simulated ls-remote failure"
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", flaky_git):
            publish(self.fixture, kill_before_done=False)
        # 鎖定暫停的細節（通知就是這一段）
        detail = events(self.config, "paused")[-1]["detail"]["detail"]
        self.assertTrue(runner.load_queue(self.config)["runner_state"]["hold"])
        self.assertNotIn("unblock --integration-tip", detail)
        self.assertIn("unblock --runner", detail)
        # STEP 02: 只跑 unblock --runner → 重啟
        with contextlib.redirect_stdout(io.StringIO()):
            runner.unblock_runner(self.config)
        self.restart()
        # STEP 03: done、tip 對齊
        queue, entry = queue_entry(self.fixture)
        self.assertEqual(entry["status"], "done")
        self.assertEqual(queue["integration_tip_sha"], self.fixture["entry_sha"])


class PublishDeferralTest(unittest.TestCase):
    """發佈段的延後區間：ff-merge 到 done 落盤之間收到停止訊號，side effect 做完、落盤之後才停；區間內的外部呼叫有短逾時。"""

    def setUp(self):
        """fixture；通知與進度報表隔離。

        @return None
        """
        # STEP 01: fixture 與隔離
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-deferral-"))
        # runner 設定
        self.config = self.fixture["config"]
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress", "freeze_entry_bundle", "freeze_runner_bundle")
        self.mocks["freeze_entry_bundle"].return_value = None
        self.mocks["freeze_runner_bundle"].return_value = None
        # 呼叫 git 時帶的 (參數, timeout)
        self.calls = []
        self.addCleanup(self._reset_signal_state)

    @staticmethod
    def _reset_signal_state():
        """測試失敗時延後區間的模組層狀態可能沒歸零，歸零免得汙染後面的測試。

        @return None
        """
        # STEP 01: 歸零
        runner._SIGNAL_DEFER_DEPTH = 0
        runner._PENDING_SIGNUM = None

    def _spy_git(self, signal_after_push):
        """包住 git：記下參數與 timeout；signal_after_push 為真時整合分支 push 完成後送一個 SIGTERM（直接呼叫 handler）。

        @param signal_after_push 是否在 push 之後注入停止訊號
        @return 取代 runner.git 的函式
        """
        # STEP 01: 轉發前記錄
        real_git = runner.git

        def spy(config, *args, **kwargs):
            """記錄、轉發、需要時注入訊號。"""
            # STEP 01: 記錄並轉發
            self.calls.append((args, kwargs.get("timeout")))
            result = real_git(config, *args, **kwargs)
            if signal_after_push and args[:3] == ("push", "origin", INTEGRATION_BRANCH):
                # STEP 01.01: launchd 的 SIGTERM 剛好落在 push 返回之後
                runner.shutdown_signal_handler(signal.SIGTERM, None)
            return result

        return spy

    def test_sigterm_during_push_persists_done_before_stopping(self):
        """必測 15 的前半（本階段範圍）：push 之後收到 SIGTERM → done 與 tip 落盤之後才以 ShutdownSignal 停下。

        修正前：訊號當場拋出，遠端已前進、queue 沒記——就是 (b)。

        @return None
        """
        # STEP 01: 發佈中注入訊號
        with mock.patch.object(runner, "git", self._spy_git(True)):
            with self.assertRaises(runner.ShutdownSignal):
                runner.publish_verified_entry(self.config, self.fixture["entry"], {"structured": {}, "session_id": "s", "cost": 0.1}, 1)
        # STEP 02: 已落盤
        queue, entry = queue_entry(self.fixture)
        self.assertEqual(entry["status"], "done")
        self.assertEqual(queue["integration_tip_sha"], self.fixture["entry_sha"])
        # STEP 03: 通知不在區間內——訊號在 done 落盤後就拋出，完成通知不發（它最長 30 秒，放進區間會吃掉 ExitTimeOut）
        self.assertNotIn("module_done", [call.args[1] for call in self.mocks["notify"].call_args_list])

    def test_sigterm_with_failed_push_persists_pause_before_stopping(self):
        """P2：區間內收到 SIGTERM、合併結果不是 done（推送失敗）→ 暫停（鎖定或簽名）落盤之後才停。

        兩種：推送失敗＋問不到遠端（integration_unrecovered，第一次就鎖定）；推送失敗、遠端確認沒收到（本機退回，帶簽名）。
        修正前：合併結果一出來就離開區間，訊號在 enter_paused 之前拋出，鎖定與簽名都沒落盤、runner 被當成正常停止。

        @return None
        """
        # STEP 01: 兩種各用一組新的 fixture
        for ls_remote_fails, expect in ((True, ("hold", True)), (False, ("crash_signature", runner.PUSH_FAILED_SIGNATURE))):
            with self.subTest(ls_remote_fails=ls_remote_fails):
                # 這一種的 git 環境
                fixture = build_fixture(tempfile.mkdtemp(prefix="r18-deferral-p2-"))
                reject_entry_branch_push(fixture["remote"], branch=INTEGRATION_BRANCH)
                real_git = runner.git

                def failing_git(config, *args, **kwargs):
                    """推送整合分支當下送 SIGTERM；需要時 ls-remote 失敗；其餘轉發。"""
                    # STEP 01: 分流
                    if args[:3] == ("push", "origin", INTEGRATION_BRANCH):
                        runner.shutdown_signal_handler(signal.SIGTERM, None)
                    if ls_remote_fails and args[:1] == ("ls-remote",):
                        return 128, "", "simulated ls-remote failure"
                    return real_git(config, *args, **kwargs)

                # STEP 02: 發佈 → 停止訊號在暫停落盤之後才拋出
                with mock.patch.object(runner, "git", failing_git):
                    with self.assertRaises(runner.ShutdownSignal):
                        runner.publish_verified_entry(fixture["config"], fixture["entry"], {"structured": {}, "session_id": "s", "cost": 0.1}, 1)
                # 落盤的 runner_state
                state = runner.load_queue(fixture["config"])["runner_state"]
                self.assertEqual(state.get("state"), "paused", state)
                self.assertEqual(state.get(expect[0]), expect[1], state)

    def test_push_and_ls_remote_use_short_timeouts(self):
        """延後區間內的 push 與 ls-remote 要有短逾時（ExitTimeOut 是 90 秒，預設 600 秒會被 SIGKILL 在半路）。

        @return None
        """
        # STEP 01: 遠端拒絕整合分支 → push 失敗 → ls-remote 問遠端
        reject_entry_branch_push(self.fixture["remote"], branch=INTEGRATION_BRANCH)
        with mock.patch.object(runner, "git", self._spy_git(False)):
            runner.merge_to_integration(self.config, self.fixture["entry"], self.fixture["entry_sha"])
        # STEP 02: 兩個遠端呼叫的逾時
        # 參數開頭 → timeout
        timeouts = {args[:2]: timeout for args, timeout in self.calls}
        self.assertEqual(timeouts.get(("push", "origin")), EXPECTED_PUSH_TIMEOUT_SECONDS, self.calls)
        self.assertEqual(timeouts.get(("ls-remote", "origin")), EXPECTED_LS_REMOTE_TIMEOUT_SECONDS, self.calls)


if __name__ == "__main__":
    unittest.main()
