"""runner.py 1.1.2 第七批項目 2 的回歸測試：合併途中被打斷留下 MERGE_HEAD 的自動收拾（主流程、記錄讀寫、失敗出口）。

runner 每次做會留下 MERGE_HEAD 的非快轉合併（前置作業合併基準分支、斷點分支回流、準備分支把整合分支合進既有 entry 分支）
之前，先把合併記錄寫進狀態目錄的 merge-intent.json；合併途中被打斷的話，下次啟動只在記錄與 repo 實況逐項吻合時才自動
`git merge --abort` 並續跑，任一項不符就保持原狀、以 integration_dirty 暫停並通知。

「runner 留下的狀態」一律照真的造：真 cmd_run 跑到真衝突，只把合併失敗後的共用收尾（abort_failed_merge）換成拋
ShutdownSignal（停止訊號剛好落在 git 退出之後、abort 之前）。拓撲一律是真的：真 bare 遠端、真衝突、真 MERGE_HEAD。
R4 逐項比對的測試在 test_merge_recovery_checks.py（從本檔匯入 harness）。

檔名、事件名、記錄欄位是外部契約（docs/environment.md），測試用字面值、不引用 runner 的新常數：常數被改掉時測試要紅；
也讓 T2.1／T2.2 在基準版（還沒有這些常數與函式）上以 AssertionError 轉紅，而不是 AttributeError。

共用的 fixture 與小工具從 review_fixtures／test_post_cli_brake／test_reconcile／test_review_112b／test_stale_branch 匯入
（只匯入函式、常數與沒有測試方法的 harness，不匯入帶測試的 TestCase，免得被重複收集）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 480; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_merge_recovery.py -v
"""

import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runner  # noqa: E402  pylint: disable=wrong-import-position
import test_post_cli_brake  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    BASE_BRANCH,
    ENTRY_BRANCH,
    ENTRY_ID,
    GIT_FATAL_EXIT_CODE,
    INTEGRATION_BRANCH,
    run_git,
)
from test_reconcile import events  # noqa: E402  pylint: disable=wrong-import-position
from test_review_112b import (  # noqa: E402  pylint: disable=wrong-import-position
    base_conflict_fixture,
    checkpoint_conflict_fixture,
)
from test_stale_branch import stale_fixture  # noqa: E402  pylint: disable=wrong-import-position

# 合併記錄的檔名（docs/environment.md 狀態目錄表的外部契約）
INTENT_NAME = "merge-intent.json"
# 自動收拾成功的事件名（外部契約）
RECOVERED_EVENT = "merge_recovered"
# 記錄在、MERGE_HEAD 不在（或記錄讀不懂而且沒有合併）時清掉記錄的事件名（外部契約）
CLEARED_EVENT = "merge_intent_cleared"
# 不收拾、或收拾不完而暫停時的暫停原因
DIRTY_REASON = "integration_dirty"
# 前置作業合併基準分支／回流斷點衝突的暫停原因（收拾之後照常判出來的那一個）
CONFLICT_REASON = "master_conflict"
# 合併記錄的 kind（外部契約）：前置作業合併基準分支
KIND_BASE = "base"
# 合併記錄的 kind（外部契約）：前置作業回流斷點分支
KIND_CHECKPOINT = "checkpoint"
# 合併記錄的 kind（外部契約）：準備分支把整合分支合進既有 entry 分支
KIND_CATCH_UP = "catch_up"
# 合併記錄的格式版本（外部契約）
INTENT_VERSION = 1
# 前置作業合併的基準分支 ref
BASE_REF = "origin/%s" % BASE_BRANCH
# CLI 後暫停計數的欄位名（queue-schema.md）
COUNT_FIELD = "post_cli_pause_count"
# CLI 後暫停計數的預設值：驗「收拾失敗的暫停不計入」要從非零起算
PRESET_COUNT = 1
# 讀不懂的記錄內容：非 UTF-8 位元組＋不完整的 JSON
GARBAGE_BYTES = b"\xff\xfe{not json"
# 讀不懂的記錄裡可辨識的一段（事件要帶原始內容摘要）
GARBAGE_MARKER = "not json"
# 不收拾而暫停之前記的事件名（外部契約）
HALTED_EVENT = "merge_recovery_halted"
# json 讀得進來、卻不能拿來算時間的 written_epoch：NaN／Infinity（json.dump 照寫、json.loads 照樣解析成 float），
# 以及位數多到轉 float 會 OverflowError 的整數
UNUSABLE_EPOCHS = (float("nan"), float("inf"), 10 ** 400)
# 工作樹裡的未追蹤檔（T2.19）
LEFTOVER_FILE = "leftover.js"
# 未追蹤檔比 MERGE_HEAD 早的秒數（R4 的時間比對照樣吻合）
LEFTOVER_AGE_SECONDS = 30
# 人工合併之後 launchd 重啟的次數（驗「只通知一次」）
RESTART_ROUNDS = 2
# 直接呼叫前置作業／準備分支時用的呼叫序號
DIRECT_ATTEMPT = 1
# T2.16 無衝突拓撲裡會寫記錄的合併次數：前置作業合併基準分支、準備分支合併整合分支
RECORDED_MERGES = 2


def git_failing(prefixes, response):
    """回傳包住真 git 的替身：參數開頭符合 prefixes 任一個的呼叫回 response，其餘照常執行。

    @param prefixes 要攔截的 git 參數開頭（tuple 的清單）
    @param response 攔截時回的 (code, out, err)
    @return 可以拿去 patch runner.git 的函式
    """
    # STEP 01: 先握住真的 git（patch 之後 runner.git 就是替身），再包出替身
    # 被替換前的真 git（patch 之前取）
    real_git = runner.git

    def fake_git(config, *args, **kwargs):
        """命中任一開頭就回 response，否則轉給真的 git。

        @param config runner 設定
        @param args git 參數
        @param kwargs 原樣轉給真的 git（timeout、log_path）
        @return (code, out, err)
        """
        # STEP 01: 比對開頭
        if any(tuple(args[: len(prefix)]) == tuple(prefix) for prefix in prefixes):
            return response
        return real_git(config, *args, **kwargs)

    return fake_git


def read_bytes_or_none(path):
    """讀檔案的原始位元組；不存在回 None。

    @param path 檔案路徑
    @return bytes 或 None
    """
    # STEP 01: 不存在是合法狀態
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


class MergeRecoveryHarness(test_post_cli_brake.BrakeHarness):
    """真 cmd_run 一輪＝一次 launchd 重啟（沿用 BrakeHarness 的隔離），拓撲換成真的衝突版；本身沒有測試方法。"""

    def make_fixture(self):
        """這組測試的拓撲；預設是衝突版舊分支拓撲（準備分支把整合分支合進 entry 分支時 add/add 衝突）。

        @return build_fixture 形狀的 fixture
        """
        # STEP 01: 子類別覆寫就換拓撲
        return stale_fixture(conflict=True)

    def setUp(self):
        """BrakeHarness 的隔離＋這組的拓撲；基準分支改回真的另一條。

        @return None
        """
        # STEP 01: BrakeHarness.setUp 以 test_post_cli_brake 模組裡的 build_fixture 建拓撲，換成 make_fixture
        with mock.patch.object(test_post_cli_brake, "build_fixture", lambda _root, _overrides: self.make_fixture()):
            super().setUp()
        # STEP 02: 基準分支是真的另一條（BrakeHarness 為了讓基準合併成 no-op 設成整合分支本身）
        self.base_config["base_branch"] = BASE_BRANCH
        # 工作 repo 路徑
        self.work = self.base_config["repo_dir"]
        # 工作 repo 的 git 目錄
        self.git_dir = os.path.join(self.work, ".git")
        # 合併記錄的路徑
        self.record_path = os.path.join(self.base_config["state_dir"], INTENT_NAME)

    def merge_head_path(self, work=None):
        """MERGE_HEAD 檔的路徑。

        @param work 工作 repo（None 表示這組的 repo）
        @return 路徑
        """
        # STEP 01: 組路徑
        return os.path.join(work or self.work, ".git", "MERGE_HEAD")

    def leave_interrupted_merge(self):
        """造 runner 留下的狀態：真 cmd_run 跑到真衝突，合併失敗後的共用收尾換成拋停止訊號（git 已退出、還沒 abort）。

        @return None
        """
        # STEP 01: cmd_run 把 ShutdownSignal 當正常停止
        with mock.patch.object(runner, "abort_failed_merge", side_effect=runner.ShutdownSignal()):
            self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        # STEP 02: 前置條件自驗：真的留下 MERGE_HEAD
        self.assertTrue(os.path.exists(self.merge_head_path()), "前置條件：應該留下 MERGE_HEAD")

    def snapshot(self, work=None):
        """repo 的可觀察狀態：分支、HEAD、MERGE_HEAD 內容、工作樹狀態（status 不寫回 index，免得改到受測的時間）。

        @param work 工作 repo（None 表示這組的 repo）
        @return dict
        """
        # STEP 01: 逐項讀
        # 要看的 repo
        repo = work or self.work
        return {
            "branch": run_git(repo, "symbolic-ref", "-q", "HEAD"),
            "head": run_git(repo, "rev-parse", "HEAD"),
            "merge_head": read_bytes_or_none(self.merge_head_path(repo)),
            "status": run_git(repo, "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
        }

    def record(self):
        """讀合併記錄。

        @return 記錄 dict
        """
        # STEP 01: 讀檔
        with open(self.record_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def rewrite_record(self, **changes):
        """改寫合併記錄的幾個欄位（其餘不動）。

        @param changes 要改的欄位與新值
        @return None
        """
        # STEP 01: 讀、改、寫
        # 改寫後的記錄
        updated = dict(self.record(), **changes)
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(updated, handle)

    def paused_details(self):
        """所有 paused 事件的細節文字（由舊到新）。

        @return 字串清單
        """
        # STEP 01: 取 detail.detail
        return [record["detail"]["detail"] for record in events(self.base_config, "paused")]

    def entry_config(self):
        """直接呼叫前置作業／準備分支用的設定（cmd_run 會先佔好 entry 與呼叫序號）。

        @return runner 設定
        """
        # STEP 01: 補上佔號
        return dict(self.base_config, current_entry=ENTRY_ID, current_attempt=DIRECT_ATTEMPT)

    def assert_refused(self, before, marker, work=None):
        """共同斷言：不收拾——repo 原狀、記錄保留、integration_dirty 暫停、細節點名不符的項目、沒有收拾事件。

        @param before 重啟前的 snapshot
        @param marker 暫停細節裡必須出現的字（不符項目的欄位名）
        @param work 工作 repo（None 表示這組的 repo）
        @return None
        """
        # STEP 01: repo 不動、記錄保留
        self.assertEqual(self.snapshot(work), before)
        self.assertTrue(os.path.exists(self.record_path))
        # STEP 02: 暫停與細節、沒有收拾事件
        self.assertEqual(self.runner_state().get("reason"), DIRTY_REASON)
        self.assertIn(marker, self.paused_details()[-1])
        self.assertEqual(events(self.base_config, RECOVERED_EVENT), [])


class NoConflictHarness(MergeRecoveryHarness):
    """無衝突版舊分支拓撲（合併都會成功）；本身沒有測試方法。"""

    def make_fixture(self):
        """無衝突版：另一個 entry 新增別的檔。

        @return build_fixture 形狀的 fixture
        """
        # STEP 01: 無衝突
        return stale_fixture(conflict=False)


class CatchUpRecoveryTest(MergeRecoveryHarness):
    """T2.1／T2.4／T2.12／T2.18／T2.19：準備分支合併被打斷之後的重啟。"""

    def test_catch_up_merge_is_recovered(self):
        """T2.1：準備分支合併整合分支時被打斷 → 重啟自動 abort、續跑，接著照常判出真衝突 blocked(git_state)。

        修正前：前置作業看到殘留 MERGE_HEAD（或切不回整合分支）→ integration_dirty 暫停，要人手動收拾。

        @return None
        """
        # STEP 01: runner 留下的狀態，重啟
        self.leave_interrupted_merge()
        # 重啟那一輪的退出碼
        code = self.run_round("done")
        # STEP 02: 收拾了：一筆 merge_recovered（catch_up）、不是 integration_dirty、記錄刪了
        # 收拾成功的事件
        recovered = events(self.base_config, RECOVERED_EVENT)
        self.assertEqual(len(recovered), 1, self.runner_state())
        self.assertEqual(recovered[0]["detail"]["record"]["kind"], KIND_CATCH_UP)
        self.assertNotEqual(self.runner_state().get("reason"), DIRTY_REASON)
        self.assertFalse(os.path.exists(self.record_path))
        # STEP 03: 續跑到同一個真衝突：entry blocked(git_state)、合併已 abort、CLI 沒呼叫
        # 落盤後的 entry
        entry = runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)
        self.assertEqual((entry["status"], entry["blocked_reason"]), ("blocked", "git_state"))
        self.assertFalse(os.path.exists(self.merge_head_path()))
        self.assertEqual(self.mocks["call_claude"].call_count, 0)
        self.assertEqual(code, runner.EXIT_OK)

    def test_manual_merge_without_record_is_left_alone(self):
        """T2.4：人手動合併（沒有記錄）→ 原狀、integration_dirty 暫停，重啟兩次只通知一次。

        @return None
        """
        # STEP 01: 人在 entry 分支上手動把整合分支合進來（真衝突）
        run_git(self.work, "checkout", ENTRY_BRANCH)
        # 手動合併的結果（預期衝突）
        result = subprocess.run(["git", "merge", INTEGRATION_BRANCH], cwd=self.work, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0, "前置條件：手動合併應該衝突")
        # 重啟前的 repo 狀態
        before = self.snapshot()
        # STEP 02: 重啟兩次
        for _round in range(RESTART_ROUNDS):
            self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 03: 原狀、原因、只通知一次、沒有收拾事件與記錄
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.runner_state().get("reason"), DIRTY_REASON)
        self.assertEqual([call.args[1] for call in self.mocks["notify"].call_args_list].count("paused"), 1)
        self.assertEqual(events(self.base_config, RECOVERED_EVENT), [])
        self.assertFalse(os.path.exists(self.record_path))

    def test_abort_failure_keeps_record_then_recovers(self):
        """T2.12：收拾時 merge --abort 失敗（真 index.lock）→ 暫停、細節含 index.lock、記錄保留；移除後重啟自動收拾。

        收拾失敗的暫停在 CLI 之前、沒有佔號，不計入 CLI 後暫停計數。

        @return None
        """
        # STEP 01: runner 留下的狀態＋真的 index.lock；計數預設非零
        self.leave_interrupted_merge()
        self.set_runner_state({"state": "running", COUNT_FIELD: PRESET_COUNT})
        # 殘留的 index.lock
        lock_path = os.path.join(self.git_dir, "index.lock")
        with open(lock_path, "w", encoding="utf-8"):
            pass
        # STEP 02: 重啟：暫停、細節含 index.lock、記錄與 MERGE_HEAD 都在、計數不動
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        self.assertTrue(os.path.exists(self.record_path))
        self.assertTrue(os.path.exists(self.merge_head_path()))
        self.assertEqual(self.runner_state().get("reason"), DIRTY_REASON)
        self.assertIn("index.lock", self.paused_details()[-1])
        self.assertEqual(self.runner_state().get(COUNT_FIELD), PRESET_COUNT)
        # STEP 03: 人移除 index.lock 後再重啟：自動收拾、續跑到真衝突
        os.remove(lock_path)
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assertEqual(len(events(self.base_config, RECOVERED_EVENT)), 1)
        self.assertFalse(os.path.exists(self.record_path))
        self.assertEqual(runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)["status"], "blocked")

    def test_hold_skips_recovery(self):
        """T2.18：鎖定中（hold）重啟不收拾：repo 與記錄原狀，hold_active 之後就退出。

        @return None
        """
        # STEP 01: runner 留下的狀態，之後鎖定
        self.leave_interrupted_merge()
        # 重啟前的 repo 狀態
        before = self.snapshot()
        self.set_runner_state({"state": "paused", "reason": runner.CRASH_REASON, "hold": True})
        # STEP 02: 重啟
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 03: 都沒動
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(os.path.exists(self.record_path))
        self.assertEqual(events(self.base_config, RECOVERED_EVENT), [])
        self.assertEqual(len(events(self.base_config, "hold_active")), 1)

    def test_leftover_untracked_after_abort_pauses(self):
        """T2.19：abort 之後工作樹還有未追蹤檔（時間比 MERGE_HEAD 早）→ 暫停、列出路徑、記錄刪了、不算收拾成功。

        @return None
        """
        # STEP 01: runner 留下的狀態；多一個比 MERGE_HEAD 早的未追蹤檔（R4 的時間比對照樣吻合）
        self.leave_interrupted_merge()
        # 未追蹤檔路徑
        leftover = os.path.join(self.work, LEFTOVER_FILE)
        with open(leftover, "w", encoding="utf-8") as handle:
            handle.write("// leftover\n")
        # 未追蹤檔的時間：比 MERGE_HEAD 早
        earlier = os.stat(self.merge_head_path()).st_mtime - LEFTOVER_AGE_SECONDS
        os.utime(leftover, (earlier, earlier))
        # STEP 02: 重啟
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 03: 合併已 abort、記錄刪了；暫停細節列出那個檔；沒有收拾成功的事件、CLI 沒呼叫
        self.assertFalse(os.path.exists(self.merge_head_path()))
        self.assertFalse(os.path.exists(self.record_path))
        self.assertEqual(self.runner_state().get("reason"), DIRTY_REASON)
        self.assertIn(LEFTOVER_FILE, self.paused_details()[-1])
        self.assertEqual(events(self.base_config, RECOVERED_EVENT), [])
        self.assertEqual(self.mocks["call_claude"].call_count, 0)


class BaseMergeRecoveryTest(MergeRecoveryHarness):
    """T2.2：前置作業合併基準分支時被打斷。"""

    def make_fixture(self):
        """基準分支與整合分支改了同一個檔：前置作業合併基準分支必衝突。

        @return build_fixture 形狀的 fixture
        """
        # STEP 01: 沿用 test_review_112b 的拓撲
        return base_conflict_fixture()

    def test_base_merge_is_recovered(self):
        """T2.2：基準分支合併真衝突時被打斷 → 重啟收拾後照常以 master_conflict 暫停，不是 integration_dirty。

        @return None
        """
        # STEP 01: runner 留下的狀態，重啟
        self.leave_interrupted_merge()
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 02: 收拾了（base），接著前置作業照常判出衝突
        # 收拾成功的事件
        recovered = events(self.base_config, RECOVERED_EVENT)
        self.assertEqual(len(recovered), 1, self.runner_state())
        self.assertEqual(recovered[0]["detail"]["record"]["kind"], KIND_BASE)
        self.assertEqual(self.runner_state().get("reason"), CONFLICT_REASON)
        self.assertFalse(os.path.exists(self.record_path))
        self.assertFalse(os.path.exists(self.merge_head_path()))
        self.assertEqual(self.mocks["call_claude"].call_count, 0)


class CheckpointMergeRecoveryTest(MergeRecoveryHarness):
    """T2.3：前置作業回流斷點分支時被打斷。"""

    def make_fixture(self):
        """基準分支與 opened 斷點分支改了同一個檔：基準合併成功、斷點回流必衝突。

        @return build_fixture 形狀的 fixture
        """
        # STEP 01: 沿用 test_review_112b 的拓撲
        return checkpoint_conflict_fixture()

    def test_checkpoint_merge_is_recovered(self):
        """T2.3：斷點回流真衝突時被打斷 → 重啟收拾後照常以 master_conflict（斷點回流衝突）暫停。

        @return None
        """
        # STEP 01: runner 留下的狀態，重啟
        self.leave_interrupted_merge()
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 02: 收拾了（checkpoint），接著前置作業照常判出斷點回流衝突
        # 收拾成功的事件
        recovered = events(self.base_config, RECOVERED_EVENT)
        self.assertEqual(len(recovered), 1, self.runner_state())
        self.assertEqual(recovered[0]["detail"]["record"]["kind"], KIND_CHECKPOINT)
        self.assertEqual(self.runner_state().get("reason"), CONFLICT_REASON)
        self.assertTrue(self.paused_details()[-1].startswith("斷點分支"), self.paused_details()[-1])
        self.assertFalse(os.path.exists(self.record_path))
        self.assertFalse(os.path.exists(self.merge_head_path()))


class IntentLeftoverTest(MergeRecoveryHarness):
    """T2.11／T2.13：記錄在、MERGE_HEAD 不在，以及記錄讀不懂。"""

    def _assert_cleared_and_continued(self, code):
        """共同斷言：記錄刪了、一筆 merge_intent_cleared、續跑（不暫停，跑到 entry 的真衝突 blocked）。

        @param code 重啟那一輪的退出碼
        @return None
        """
        # STEP 01: 記錄與事件
        self.assertFalse(os.path.exists(self.record_path))
        self.assertEqual(len(events(self.base_config, CLEARED_EVENT)), 1)
        # STEP 02: 沒有暫停
        self.assertEqual(code, runner.EXIT_OK)
        self.assertNotEqual(self.runner_state().get("state"), "paused")

    def test_record_left_after_completed_merge_is_cleared(self):
        """T2.11：基準分支合併已完成、刪記錄之前被打斷 → 重啟刪記錄、續跑、不暫停。

        @return None
        """
        # STEP 01: 收尾記錄那一步換成拋停止訊號（合併本身已成功）
        with mock.patch.object(runner, "finish_recorded_merge", side_effect=runner.ShutdownSignal()):
            self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assertTrue(os.path.exists(self.record_path), "前置條件：記錄應該還在")
        self.assertFalse(os.path.exists(self.merge_head_path()))
        # STEP 02: 重啟
        self._assert_cleared_and_continued(self.run_round("done"))

    def test_record_written_but_merge_not_run_is_cleared(self):
        """T2.11：記錄寫了、git merge 還沒跑就被打斷 → 重啟刪記錄、續跑、不暫停。

        @return None
        """
        # STEP 01: 基準分支的 git merge 一被呼叫就拋停止訊號（記錄已寫、合併沒跑）
        # 被替換前的真 git
        real_git = runner.git

        def signal_on_base_merge(config, *args, **kwargs):
            """基準分支合併的那次呼叫拋停止訊號，其餘轉給真的 git。

            @param config runner 設定
            @param args git 參數
            @param kwargs 原樣轉交
            @return (code, out, err)
            @raises runner.ShutdownSignal 基準分支合併
            """
            # STEP 01: 攔基準分支合併
            if args[:2] == ("merge", BASE_REF):
                raise runner.ShutdownSignal()
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", signal_on_base_merge):
            self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assertTrue(os.path.exists(self.record_path), "前置條件：記錄應該已寫")
        # STEP 02: 重啟
        self._assert_cleared_and_continued(self.run_round("done"))

    def test_unreadable_record_with_merge_head_pauses(self):
        """T2.13：記錄是垃圾位元組、MERGE_HEAD 在 → 不動 repo、記錄原封不動、暫停並寫明記錄讀不懂。

        @return None
        """
        # STEP 01: runner 留下的狀態，記錄換成垃圾
        self.leave_interrupted_merge()
        with open(self.record_path, "wb") as handle:
            handle.write(GARBAGE_BYTES)
        # 重啟前的 repo 狀態
        before = self.snapshot()
        # STEP 02: 重啟
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 03: 都沒動、暫停細節寫明讀不懂
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(read_bytes_or_none(self.record_path), GARBAGE_BYTES)
        self.assertEqual(self.runner_state().get("reason"), DIRTY_REASON)
        self.assertIn("讀不懂", self.paused_details()[-1])
        self.assertEqual(events(self.base_config, RECOVERED_EVENT), [])

    def test_unreadable_record_without_merge_head_is_cleared(self):
        """T2.13：記錄是垃圾位元組、沒有進行中的合併 → 刪記錄（事件帶原始內容摘要）、續跑。

        @return None
        """
        # STEP 01: 只有一份讀不懂的記錄
        with open(self.record_path, "wb") as handle:
            handle.write(GARBAGE_BYTES)
        # STEP 02: 重啟
        self._assert_cleared_and_continued(self.run_round("done"))
        # STEP 03: 事件帶原始內容摘要
        self.assertIn(GARBAGE_MARKER, json.dumps(events(self.base_config, CLEARED_EVENT)[0]["detail"], ensure_ascii=False))

    def test_non_finite_epoch_is_unreadable(self):
        """T2.13 延伸：written_epoch 是 NaN／Infinity／超大整數（MERGE_HEAD 在）→ 當成讀不懂暫停，不是在時間比對時拋例外變成 crash。

        修正前型別檢查只看 int／float，NaN 一路放行到 `%d` 格式化拋 ValueError，走 runner_crashed（第二次就鎖定）。

        @return None
        """
        # STEP 01: runner 留下的狀態
        self.leave_interrupted_merge()
        for epoch in UNUSABLE_EPOCHS:
            with self.subTest(epoch=epoch):
                # STEP 02: 記錄的時間換成不能算的值，重啟
                self.rewrite_record(written_epoch=epoch)
                self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
                # STEP 03: 讀不懂的暫停（不是 crash）、點名 written_epoch、repo 沒動
                self.assertEqual(self.runner_state().get("reason"), DIRTY_REASON)
                # 最後一筆不收拾的事件
                halted = events(self.base_config, HALTED_EVENT)[-1]["detail"]
                self.assertEqual(halted["stage"], "unreadable")
                self.assertIn("written_epoch", halted["problem"])
                self.assertTrue(os.path.exists(self.merge_head_path()))
                self.assertEqual(events(self.base_config, RECOVERED_EVENT), [])


class MergeHeadReadFailureTest(MergeRecoveryHarness):
    """T2.14：MERGE_HEAD 讀不到不等於沒有（收拾端與收尾端）。"""

    def test_recovery_read_failure_is_not_absent(self):
        """T2.14：重啟時讀 MERGE_HEAD 失敗（rev-parse 128）→ 不當成沒有：記錄保留、repo 不動、暫停。

        連 `rev-parse --git-dir` 一起失敗：寬容版 merge_in_progress 此時回 False，用它判斷的話會把記錄刪掉續跑。

        @return None
        """
        # STEP 01: runner 留下的狀態
        self.leave_interrupted_merge()
        # 重啟前的 repo 狀態
        before = self.snapshot()
        # STEP 02: 重啟時讀 MERGE_HEAD 與 git 目錄都失敗
        # 注入失敗的 git
        failing = git_failing(
            [("rev-parse", "-q", "--verify", "MERGE_HEAD"), ("rev-parse", "--git-dir")],
            (GIT_FATAL_EXIT_CODE, "", "fatal: injected read failure"),
        )
        with mock.patch.object(runner, "git", failing):
            self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 03: 記錄保留、repo 不動、暫停細節提到 MERGE_HEAD、沒有清記錄或收拾的事件
        self.assertTrue(os.path.exists(self.record_path))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.runner_state().get("reason"), DIRTY_REASON)
        self.assertIn("MERGE_HEAD", self.paused_details()[-1])
        self.assertEqual(events(self.base_config, CLEARED_EVENT), [])
        self.assertEqual(events(self.base_config, RECOVERED_EVENT), [])

    def test_abort_side_read_failure_is_not_merge_not_started(self):
        """T2.14（收尾端）：準備分支真衝突之後讀 MERGE_HEAD 失敗 → 附註寫「無法判斷」、不寫「合併未開始」、不 abort、記錄保留。

        @return None
        """
        # STEP 01: 前置作業（真的）通過
        # 直接呼叫用的設定
        config = self.entry_config()
        # 前置作業的結果
        ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(ok, "%s: %s" % (reason, detail))
        # STEP 02: 準備分支：真衝突，之後讀 MERGE_HEAD 失敗；記下每次 git 參數
        # 每次 git 呼叫的參數
        calls = []
        # 注入失敗的 git
        failing = git_failing([("rev-parse", "-q", "--verify", "MERGE_HEAD")], (GIT_FATAL_EXIT_CODE, "", "fatal: injected"))

        def recording_git(config_arg, *args, **kwargs):
            """記下參數後交給注入版 git。

            @param config_arg runner 設定
            @param args git 參數
            @param kwargs 原樣轉交
            @return (code, out, err)
            """
            # STEP 01: 記錄並轉交
            calls.append(args)
            return failing(config_arg, *args, **kwargs)

        with mock.patch.object(runner, "git", recording_git):
            # prepare_branch 的結果與細節
            status, detail = runner.prepare_branch(config, self.fixture["entry"])
        # STEP 03: 暫停、附註照實、沒有 abort、記錄與 MERGE_HEAD 都在
        self.assertEqual(status, runner.PREPARE_PAUSE, detail)
        self.assertIn("無法判斷", detail)
        self.assertNotIn("合併未開始", detail)
        self.assertNotIn(("merge", "--abort"), calls)
        self.assertTrue(os.path.exists(self.record_path))
        self.assertTrue(os.path.exists(self.merge_head_path()))


class IntentCleanupTest(MergeRecoveryHarness):
    """T2.16（衝突版）：合併失敗 abort 之後，記錄只在 MERGE_HEAD 確定不在時刪。"""

    def test_conflict_abort_clears_record(self):
        """準備分支真衝突、abort 乾淨 → blocked，記錄刪了、MERGE_HEAD 不在。

        @return None
        """
        # STEP 01: 前置作業＋準備分支（真的）
        # 直接呼叫用的設定
        config = self.entry_config()
        self.assertTrue(runner.module_preflight(config, runner.load_queue(config))[0])
        # prepare_branch 的結果與細節
        status, detail = runner.prepare_branch(config, self.fixture["entry"])
        # STEP 02: blocked、記錄刪了
        self.assertEqual(status, runner.PREPARE_ENTRY_BLOCKED, detail)
        self.assertFalse(os.path.exists(self.record_path))
        self.assertFalse(os.path.exists(self.merge_head_path()))

    def test_abort_failure_keeps_record_and_restart_recovers(self):
        """準備分支真衝突、abort 失敗（注入）→ 暫停，記錄保留、MERGE_HEAD 在；重啟自動收拾。

        @return None
        """
        # STEP 01: 前置作業（真的）＋準備分支（abort 失敗）
        # 直接呼叫用的設定
        config = self.entry_config()
        self.assertTrue(runner.module_preflight(config, runner.load_queue(config))[0])
        with mock.patch.object(runner, "git", git_failing([("merge", "--abort")], (GIT_FATAL_EXIT_CODE, "", "abort boom"))):
            # prepare_branch 的結果與細節
            status, detail = runner.prepare_branch(config, self.fixture["entry"])
        self.assertEqual(status, runner.PREPARE_PAUSE, detail)
        self.assertTrue(os.path.exists(self.record_path))
        self.assertTrue(os.path.exists(self.merge_head_path()))
        # STEP 02: 重啟：收拾、續跑到真衝突 blocked
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assertEqual(len(events(self.base_config, RECOVERED_EVENT)), 1)
        self.assertFalse(os.path.exists(self.record_path))
        self.assertEqual(runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)["status"], "blocked")


class IntentWriteTest(NoConflictHarness):
    """T2.15／T2.16：寫入端——記錄內容、合併成功後刪、寫不進去就不合併。"""

    def test_record_write_failure_skips_merge_and_pauses_before_cli(self):
        """T2.15：記錄寫不進去（路徑預先建成目錄）→ 不合併、CLI 之前暫停、細節寫明。

        @return None
        """
        # STEP 01: 記錄路徑是目錄；記下本機整合分支
        os.makedirs(self.record_path)
        # 本機整合分支原本的 tip
        local_before = run_git(self.work, "rev-parse", INTEGRATION_BRANCH)
        # STEP 02: 重啟
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 03: 沒有合併、CLI 沒呼叫、以前置作業的合併失敗暫停、細節寫明
        self.assertEqual(run_git(self.work, "rev-parse", INTEGRATION_BRANCH), local_before)
        self.assertEqual(self.mocks["call_claude"].call_count, 0)
        self.assertEqual(self.runner_state().get("reason"), CONFLICT_REASON)
        self.assertIn("寫合併記錄失敗", self.paused_details()[-1])
        self.assertFalse(os.path.exists(self.merge_head_path()))

    def test_record_content_and_cleanup_on_success(self):
        """T2.16：前置作業合併基準分支、準備分支合併整合分支都成功：合併當下的記錄內容照實，合併完記錄刪了。

        @return None
        """
        # STEP 01: 合併前的事實
        # 合併前的本機整合分支 tip
        integration_before = run_git(self.work, "rev-parse", INTEGRATION_BRANCH)
        # 基準分支（遠端追蹤）的 sha
        base_sha = run_git(self.work, "rev-parse", BASE_REF)
        # 每次合併當下讀到的記錄
        captured = []
        # 被替換前的真 git
        real_git = runner.git

        def capturing_git(config, *args, **kwargs):
            """非快轉合併（不含 --abort／--ff-only）被呼叫的當下讀一次記錄，再轉給真的 git。

            @param config runner 設定
            @param args git 參數
            @param kwargs 原樣轉交
            @return (code, out, err)
            """
            # STEP 01: 讀記錄
            if args[:1] == ("merge",) and args[1] not in ("--abort", "--ff-only"):
                with open(self.record_path, "r", encoding="utf-8") as handle:
                    captured.append(json.load(handle))
            return real_git(config, *args, **kwargs)

        # STEP 02: 真的前置作業＋準備分支
        # 直接呼叫用的設定
        config = self.entry_config()
        # 呼叫前後的時間（written_epoch 要落在中間）
        started = time.time()
        with mock.patch.object(runner, "git", capturing_git):
            self.assertTrue(runner.module_preflight(config, runner.load_queue(config))[0])
            # 基準合併之後的本機整合分支（準備分支合併的對象）
            integration_after = run_git(self.work, "rev-parse", INTEGRATION_BRANCH)
            self.assertEqual(runner.prepare_branch(config, self.fixture["entry"])[0], runner.PREPARE_READY)
        # 兩次合併都做完之後的時間
        finished = time.time()
        # STEP 03: 兩份記錄的內容
        self.assertEqual(len(captured), RECORDED_MERGES, captured)
        # 兩次合併各自的預期欄位
        expected = (
            {"kind": KIND_BASE, "branch_ref": "refs/heads/%s" % INTEGRATION_BRANCH, "head_before": integration_before,
             "target_ref": BASE_REF, "target_sha": base_sha},
            {"kind": KIND_CATCH_UP, "branch_ref": "refs/heads/%s" % ENTRY_BRANCH, "head_before": self.fixture["stale_entry_sha"],
             "target_ref": INTEGRATION_BRANCH, "target_sha": integration_after},
        )
        for record, fields in zip(captured, expected):
            self.assertEqual({key: record.get(key) for key in fields}, fields)
            self.assertEqual(
                (record.get("version"), record.get("pid"), record.get("entry"), record.get("attempt")),
                (INTENT_VERSION, os.getpid(), ENTRY_ID, DIRECT_ATTEMPT),
            )
            self.assertEqual(record.get("repo_real"), os.path.realpath(self.work))
            self.assertEqual(record.get("git_dir"), os.path.realpath(self.git_dir))
            self.assertTrue(started <= record.get("written_epoch") <= finished, record)
            self.assertIsInstance(record.get("written_iso"), str)
        # STEP 04: 合併完記錄刪了
        self.assertFalse(os.path.exists(self.record_path))


if __name__ == "__main__":
    unittest.main()
