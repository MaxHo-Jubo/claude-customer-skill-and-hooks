"""runner.py 1.1.2 第五批「收尾修正」的回歸測試：stub 驗收的 BONUS-1／BONUS-2 與階段三 review 的 MINOR 1–5。

斷點相關情境一律用**真實拓撲**（RealTopologyHarness）：基準分支（master）與整合分支是兩條分支，整合分支上有 base 沒有的 commit
（e1 的遷移），斷點的 pr_base 是 master。既有 fixture 把基準分支設成整合分支本身，cp 分支一推上去就是 base 的祖先、opened 立刻被
sync_merged_checkpoints 判成 merged——「人合併了 PR」「cp 分支上有人推了修正」這類情境在那個拓撲下根本造不出來。

新名稱（例外類別、常數、事件名）一律寫成字面值或用 RuntimeError 斷言，不 getattr 新常數——修正前它們不存在，直接取會以
AttributeError 失敗、不是以 AssertionError 證明「還沒修」。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 360; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_reconcile_followups.py -v
"""

import argparse
import contextlib
import datetime
import io
import json
import os
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
from fake_gh import gh_commands, gh_prs, set_gh_modes  # noqa: E402  pylint: disable=wrong-import-position
from test_checkpoint_reconcile import (  # noqa: E402  pylint: disable=wrong-import-position
    CP_BRANCH,
    FIRST_CREATED_PR_URL,
    OPEN_FAILED_REASON,
    CheckpointHarness,
    checkpoint,
    kill_after_gh,
    remote_cp_branches,
)
from test_pr_reconcile import use_scripted_gh  # noqa: E402  pylint: disable=wrong-import-position
from test_reconcile import (  # noqa: E402  pylint: disable=wrong-import-position
    HARD_CHECKPOINT_ID,
    SECOND_ENTRY_ID,
    RestartHarness,
    SimulatedKill,
    events,
    publish,
)
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    BASE_BRANCH,
    ENTRY_BRANCH,
    ENTRY_ID,
    INTEGRATION_BRANCH,
    remote_tip,
    run_git,
)

# GitHub 上已經存在、runner 不知道的斷點 PR（補查應找到它）
EXISTING_CP_PR_URL = "https://example.invalid/pull/55"
# 凍結的「現在」：同一秒內觸發 auto 斷點
FROZEN_MOMENT = datetime.datetime(2031, 1, 1, 0, 1, 0)
# 修正前的 auto id 格式（到分鐘）在凍結時刻產生的 id
MINUTE_AUTO_ID = "auto-20310101-0001"
# 修正後的 auto id 格式（到秒）在凍結時刻產生的 id
SECOND_AUTO_ID = "auto-20310101-000100"
# 模組完成後的 PR 問題通知（BONUS-2 改名後的事件）
DONE_PR_FAILED_EVENT = "module_done_pr_failed"
# 真實的 wait_for_release（RestartHarness 會把模組上的換成 mock）
REAL_WAIT_FOR_RELEASE = runner.wait_for_release
# wait_for_release 測試裡第幾次 sleep 時放行
RELEASE_ON_SLEEP_CALL = 2
# 單獨執行 notify.sh 片段（event_emoji）的逾時（秒）
NOTIFY_PROBE_TIMEOUT_SECONDS = 10


def cp_pr_on_base(url, **fields):
    """假 gh 狀態檔裡的一筆斷點 PR，base 是真實拓撲的基準分支。

    @param url PR 連結
    @param fields 覆寫欄位（state、head_oid…）
    @return dict
    """
    # STEP 01: 組欄位
    return dict({"url": url, "head": CP_BRANCH, "base": BASE_BRANCH, "state": "open"}, **fields)


def release(config, checkpoint_id=HARD_CHECKPOINT_ID):
    """跑一次 `runner.py release <id>`（吞掉它印的提示）。

    @param config runner 設定
    @param checkpoint_id 斷點 id
    @return cmd_release 的退出碼
    """
    # STEP 01: 放行
    with contextlib.redirect_stdout(io.StringIO()):
        return runner.cmd_release(config, argparse.Namespace(checkpoint_id=checkpoint_id))


@contextlib.contextmanager
def frozen_now(moment):
    """把 runner 看到的 datetime.datetime.now() 固定在某一刻（timezone／timedelta 照舊）。

    @param moment 要固定的時刻
    @return context manager
    """
    # STEP 01: 換掉 runner 模組上的 datetime
    with mock.patch.object(runner, "datetime") as fake:
        fake.datetime.now.return_value = moment
        fake.timezone = datetime.timezone
        fake.timedelta = datetime.timedelta
        yield


def git_failing_when(predicate, code=128):
    """讓 runner.git 對 predicate(args) 為真的呼叫回傳失敗，其餘照常。

    @param predicate 收 git 參數 tuple、回 bool
    @param code 回傳的退出碼
    @return mock.patch 物件（with 用）
    """
    # STEP 01: 轉發或回失敗
    real_git = runner.git

    def wrapper(config, *args, **kwargs):
        """命中就回失敗。"""
        if predicate(tuple(args)):
            return code, "", "fatal: injected failure"
        return real_git(config, *args, **kwargs)

    return mock.patch.object(runner, "git", wrapper)


def git_failing_on(prefix, code=128):
    """讓 runner.git 對參數開頭符合 prefix 的呼叫回傳失敗，其餘照常。

    @param prefix 參數開頭（tuple），例如 ("diff",)
    @param code 回傳的退出碼
    @return mock.patch 物件（with 用）
    """
    # STEP 01: 比對開頭
    return git_failing_when(lambda args: args[: len(prefix)] == prefix, code)


def is_ancestor_against_origin(args):
    """是不是「某個 ref 是否為 origin/<分支> 的祖先」的 merge-base（opening 補完前的已合併判斷）。

    @param args git 參數 tuple
    @return bool
    """
    # STEP 01: merge-base --is-ancestor <a> origin/<b>
    return args[:2] == ("merge-base", "--is-ancestor") and str(args[-1]).startswith("origin/")


def is_ancestor_between_shas(args):
    """是不是兩個 sha 之間的 merge-base（遠端 cp 分支是否已含本機 tip）。

    @param args git 參數 tuple
    @return bool
    """
    # STEP 01: merge-base --is-ancestor <sha> <sha>
    return args[:2] == ("merge-base", "--is-ancestor") and not str(args[-1]).startswith(("origin/", "r18-migration/"))


class RealTopologyHarness(CheckpointHarness):
    """真實拓撲：master 比整合分支多一個 hotfix，整合分支比 master 多 e1 的遷移；w0（hard）的 pr_base 是 master。"""

    def setUp(self):
        """在 CheckpointHarness 之上把基準分支拆出來。

        @return None
        """
        # STEP 01: master 多一個 commit 並推上去
        super().setUp()
        # 工作 repo
        self.work = self.config["repo_dir"]
        run_git(self.work, "checkout", "-b", BASE_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(self.work, "hotfix.js"), "w", encoding="utf-8") as handle:
            handle.write("// base moved\n")
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", "base moves")
        run_git(self.work, "push", "-u", "origin", BASE_BRANCH)
        # STEP 02: 整合分支帶 e1 的 commit（master 沒有）並推上去
        run_git(self.work, "checkout", INTEGRATION_BRANCH)
        run_git(self.work, "merge", "--ff-only", ENTRY_BRANCH)
        run_git(self.work, "push", "origin", INTEGRATION_BRANCH)
        # 整合分支的 tip
        tip = run_git(self.work, "rev-parse", "HEAD")
        runner.mutate_queue(self.config, lambda queue: queue.update({"integration_tip_sha": tip}))
        self.config["base_branch"] = BASE_BRANCH
        self.set_checkpoint(pr_base=BASE_BRANCH)
        # STEP 03: 前置條件：整合分支真的有 base 沒有的 commit
        assert run_git(self.work, "rev-list", "--count", "%s..%s" % (BASE_BRANCH, INTEGRATION_BRANCH)) != "0"

    def mark_done_on_process(self):
        """process_one_entry 改成「把 entry 標 done」（模擬模組做完）。

        @return None
        """

        # STEP 01: 換掉 side effect
        def fake(config, entry):
            """標 done。"""
            runner.mutate_queue(config, lambda queue: runner.find_entry(queue, entry["id"]).update({"status": "done"}))

        self.mocks["process_one_entry"].side_effect = fake

    def kill_while_opening_hard(self):
        """第一次啟動開 w0，`gh pr create` 真的建好 PR 之後被殺：斷點停在 opening。

        @return None
        """
        # STEP 01: 中斷
        with kill_after_gh("pr create"):
            with self.assertRaises(SimulatedKill):
                self.restart()
        assert checkpoint(self.config)["status"] == "opening"

    def human_clone(self):
        """另一個人的 clone（在 fixture 根目錄底下），用來從外部推 commit，不動 runner 的工作 repo。

        @return clone 的路徑
        """
        # STEP 01: clone 遠端
        path = tempfile.mkdtemp(prefix="human-", dir=os.path.dirname(self.fixture["remote"]))
        run_git(path, "clone", "-q", self.fixture["remote"], ".")
        run_git(path, "config", "user.name", "reviewer")
        run_git(path, "config", "user.email", "reviewer@example.invalid")
        return path

    def human_pushes_fix_to_cp(self):
        """審查者從自己的 clone 往 cp 分支推一個修正 commit。

        @return 推上去之後遠端 cp 分支的 tip
        """
        # STEP 01: 在 cp 分支上提交並推送
        clone = self.human_clone()
        run_git(clone, "checkout", "-q", CP_BRANCH)
        with open(os.path.join(clone, "review-fix.js"), "w", encoding="utf-8") as handle:
            handle.write("// review fix\n")
        run_git(clone, "add", "-A")
        run_git(clone, "commit", "-q", "-m", "review fix")
        run_git(clone, "push", "-q", "origin", CP_BRANCH)
        return remote_tip(self.fixture, CP_BRANCH)

    def human_merges_cp_pr(self):
        """審查者在 GitHub 上把 cp PR 合進 master（真的 merge commit），假 gh 上那支 PR 改成 merged。

        @return None
        """
        # STEP 01: 合併並推上 master
        clone = self.human_clone()
        run_git(clone, "checkout", "-q", BASE_BRANCH)
        run_git(clone, "merge", "-q", "--no-ff", "-m", "merge cp", "origin/%s" % CP_BRANCH)
        run_git(clone, "push", "-q", "origin", BASE_BRANCH)
        # STEP 02: PR 狀態
        with open(self.gh["state"], encoding="utf-8") as handle:
            # 假 gh 的狀態
            state = json.load(handle)
        for item in state["prs"]:
            item["state"] = "merged"
        with open(self.gh["state"], "w", encoding="utf-8") as handle:
            json.dump(state, handle)


class RealTopologyRegressionTest(RealTopologyHarness):
    """第五批階段三的關鍵情境在真實拓撲下重跑一次（opened 不會被誤判成 merged）。"""

    def test_hard_crash_after_create_waits_for_release(self):
        """hard 斷點 create 之後被殺 → 重啟沿用 PR、停在等待，不處理 e2，create 只 1 次。

        @return None
        """
        # STEP 01: 中斷 → 重啟
        self.kill_while_opening_hard()
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # STEP 02: opened（真實拓撲下不是 merged）、沿用、等待
        found = checkpoint(self.config)
        self.assertEqual((found["status"], found["pr_url"]), ("opened", FIRST_CREATED_PR_URL))
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        self.mocks["process_one_entry"].assert_not_called()
        self.mocks["wait_for_release"].assert_called_with(self.config, HARD_CHECKPOINT_ID)

    def test_auto_crash_after_create_is_reused(self):
        """auto 斷點 create 之後被殺 → 重啟同 id、同分支，遠端一支 cp 分支、GitHub 一支 PR、e1 蓋章。

        @return None
        """
        # STEP 01: 只有 e1、沒有宣告的斷點，門檻 1
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": [], "modules": queue["modules"][:1]}))
        self.config["checkpoint_max_modules"] = 1
        with kill_after_gh("pr create"):
            with self.assertRaises(SimulatedKill):
                runner.handle_checkpoints(self.config)
        # write-ahead 落盤的 auto id
        auto_id = runner.load_queue(self.config)["checkpoints"][0]["id"]
        # STEP 02: 重啟
        self.assertEqual(self.restart(), runner.EXIT_OK)
        queue = runner.load_queue(self.config)
        self.assertEqual([(item["id"], item["status"]) for item in queue["checkpoints"]], [(auto_id, "opened")])
        self.assertEqual(runner.find_entry(queue, ENTRY_ID)["checkpoint_id"], auto_id)
        self.assertEqual(len(remote_cp_branches(self.fixture)), 1)
        self.assertEqual(len(gh_prs(self.gh)), 1)

    def test_unverified_link_is_filled_on_restart(self):
        """(c1) gh 退出 0 沒印連結 → opened＋pr_unverified；重啟補查查到 → 補上連結、清旗標（真實拓撲下仍是 opened）。

        @return None
        """
        # STEP 01: soft 斷點開成 c1：create 前的查詢正常（沒有 PR）、create 退出 0 沒印連結、create 後的再查失敗（無法確認）
        self.set_checkpoint(mode="soft")
        set_gh_modes(self.gh, list_mode="ok_then_fail", list_ok_left=1, create_mode="nolink")
        self.assertEqual(runner.handle_checkpoints(self.config, include_auto=False), (False, HARD_CHECKPOINT_ID))
        self.assertTrue(checkpoint(self.config)["pr_unverified"])
        # STEP 02: GitHub 上其實有 PR → 重啟補查
        self.use_gh(prs=[cp_pr_on_base(EXISTING_CP_PR_URL)])
        self.restart()
        found = checkpoint(self.config)
        self.assertEqual((found["status"], found["pr_url"], found["pr_unverified"]), ("opened", EXISTING_CP_PR_URL, False))

    def test_opening_without_local_branch_opens_normally(self):
        """write-ahead 之後、`branch -f` 之前被殺（本機沒有 cp 分支）→ 重啟照常開：opened、create 1 次。

        @return None
        """
        # STEP 01: 只有 write-ahead
        self.set_checkpoint(status="opening", branch=CP_BRANCH)
        # STEP 02: 重啟
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assertEqual(checkpoint(self.config)["status"], "opened")
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)


class UniqueAutoIdTest(RealTopologyHarness):
    """BONUS-1：同一分鐘（同一秒）內第二次觸發 auto 斷點不可以把在審的斷點改回 opening 重開。"""

    def test_retrigger_in_same_second_opens_a_new_checkpoint(self):
        """同一時刻已有兩支在審的 auto 分支：一支 id 是修正後同一秒會產生的（在 queue 裡、opened）；一支 id 是修正前到分鐘的
        （記錄被重新 import-inventory 丟掉、分支與 PR 還在）。e2 完成再觸發 auto → 另開一個新 id，兩支舊分支本機與遠端都不動。

        修正前：id 到分鐘，撞到第二支 → 同一支 cp 分支被 `branch -f` 往前移、推上去，新模組蓋進在審的 PR。
        兩支各守一層：queue 裡有的靠撞號加序號；queue 裡沒有的只能靠 id 帶秒數。

        @return None
        """
        # STEP 01: 在審的兩支（本機分支在目前的整合分支 tip；遠端也有）
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": []}))
        # 在審分支的 id → 分支
        seeds = {seed: "r18-migration/cp-%s" % seed for seed in (MINUTE_AUTO_ID, SECOND_AUTO_ID)}
        for branch in seeds.values():
            run_git(self.work, "branch", branch, INTEGRATION_BRANCH)
            run_git(self.work, "push", "-q", "origin", branch)
        record = dict(
            runner.CHECKPOINT_FIELD_DEFAULTS, id=SECOND_AUTO_ID, after={"wave": None}, mode="soft", pr_base=BASE_BRANCH,
            title=SECOND_AUTO_ID, status="opened", branch=seeds[SECOND_AUTO_ID], pr_url=EXISTING_CP_PR_URL,
        )
        runner.mutate_queue(self.config, lambda queue: queue["checkpoints"].append(record))
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, ENTRY_ID).update({"checkpoint_id": SECOND_AUTO_ID}))
        # 兩支在審分支原本的 tip（本機與遠端相同）
        seed_tips = {branch: run_git(self.work, "rev-parse", branch) for branch in seeds.values()}
        self.config["checkpoint_max_modules"] = 1
        # STEP 02: e2 完成 → 同一秒觸發 auto
        self.mark_done_on_process()
        with frozen_now(FROZEN_MOMENT):
            self.restart()
        # STEP 03: 舊的不動；多一個新 id 的 opened，e2 蓋它的章
        queue = runner.load_queue(self.config)
        self.assertEqual(runner.find_checkpoint(queue, SECOND_AUTO_ID)["status"], "opened")
        fresh = [item for item in queue["checkpoints"] if item["id"] not in seeds]
        self.assertEqual(len(fresh), 1, queue["checkpoints"])
        self.assertEqual(fresh[0]["status"], "opened")
        self.assertTrue(runner.checkpoint_id_is_valid(fresh[0]["id"]))
        self.assertEqual(runner.find_entry(queue, SECOND_ENTRY_ID)["checkpoint_id"], fresh[0]["id"])
        self.assertEqual({branch: run_git(self.work, "rev-parse", branch) for branch in seeds.values()}, seed_tips)
        self.assertEqual({branch: remote_tip(self.fixture, branch) for branch in seeds.values()}, seed_tips)

    def test_begin_refuses_statuses_other_than_pending_and_opening(self):
        """begin_checkpoint_opening 遇到 opened／released／merged／failed 一律拒絕（raise），狀態不動。

        @return None
        """
        # STEP 01: 逐一
        for status in ("opened", "released", "merged", "failed"):
            with self.subTest(status=status):
                self.set_checkpoint(status=status, branch=CP_BRANCH)
                with self.assertRaises(RuntimeError):
                    runner.begin_checkpoint_opening(self.config, HARD_CHECKPOINT_ID, CP_BRANCH, None)
                self.assertEqual(checkpoint(self.config)["status"], status)

    def test_release_racing_resume_is_honoured(self):
        """hard 斷點停在 opening，重啟補開的同時被 release：begin 拒絕、hold_hard_checkpoint 照放行處理 → 不重開、處理 e2。

        修正前：begin 把 released 改回 opening → push、開 PR、opened → 停下等待（放行被吃掉）。

        @return None
        """
        # STEP 01: opening；begin 之前先被放行
        self.set_checkpoint(status="opening", branch=CP_BRANCH)
        real_begin = runner.begin_checkpoint_opening

        def racing(config, *args, **kwargs):
            """先 release 再 begin。"""
            release(config)
            return real_begin(config, *args, **kwargs)

        # STEP 02: 重啟
        with mock.patch.object(runner, "begin_checkpoint_opening", racing):
            self.restart()
        self.assertEqual(checkpoint(self.config)["status"], "released")
        self.assertEqual(remote_cp_branches(self.fixture), [])
        self.mocks["process_one_entry"].assert_called_once()

    def test_conflict_with_gate_not_passed_is_raised(self):
        """begin 拒絕重開、但斷點不是 released／merged（例如被改成 failed）→ hold_hard_checkpoint 往外拋，不當成開啟失敗暫停、不放行。

        @return None
        """
        # STEP 01: opening；begin 之前被改成 failed
        self.set_checkpoint(status="opening", branch=CP_BRANCH)
        real_begin = runner.begin_checkpoint_opening

        def racing(config, *args, **kwargs):
            """先改狀態再 begin。"""
            self.set_checkpoint(status="failed")
            return real_begin(config, *args, **kwargs)

        # STEP 02: 直接走閘門
        with mock.patch.object(runner, "begin_checkpoint_opening", racing):
            with self.assertRaises(RuntimeError):
                runner.hold_hard_checkpoint(self.config, HARD_CHECKPOINT_ID)
        self.assertEqual(checkpoint(self.config)["status"], "failed")


class ResumeOpeningTopologyTest(RealTopologyHarness):
    """MINOR 1／2：opening 的斷點重啟時，遠端已經往前（有人推修正）或 PR 已被合併。"""

    def test_human_fix_on_remote_cp_is_not_pushed_over(self):
        """PR 建好後被殺、審查者往 cp 分支推修正 → 重啟：遠端已含本機 tip，不推、以遠端 tip 查 PR 沿用 → opened、等待。

        修正前：`branch -f` 把本機 cp 移回整合分支 tip，非 force push 被拒 → checkpoint_open_failed 暫停，第二次 hold。

        @return None
        """
        # STEP 01: 中斷 → 人推修正 → 重啟
        self.kill_while_opening_hard()
        fixed_tip = self.human_pushes_fix_to_cp()
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # STEP 02: 沿用、遠端不動、等待（不是開啟失敗）
        found = checkpoint(self.config)
        self.assertEqual((found["status"], found["pr_url"]), ("opened", FIRST_CREATED_PR_URL))
        self.assertEqual(remote_tip(self.fixture, CP_BRANCH), fixed_tip)
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        self.assertNotEqual(self.runner_state().get("reason"), OPEN_FAILED_REASON)
        self.mocks["wait_for_release"].assert_called_with(self.config, HARD_CHECKPOINT_ID)

    def test_remote_lookup_failure_does_not_push(self):
        """問遠端 cp 分支失敗（ls-remote 非 0 非 2）→ 不推、hard 以 checkpoint_open_failed 暫停，不猜。

        @return None
        """
        # STEP 01: 中斷 → 重啟時 ls-remote 失敗
        self.kill_while_opening_hard()
        with git_failing_on(("ls-remote",)):
            self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # STEP 02: 仍是 opening、以開啟失敗暫停
        self.assertEqual(checkpoint(self.config)["status"], "opening")
        self.assertEqual(self.runner_state().get("reason"), OPEN_FAILED_REASON)

    def test_hard_pr_merged_before_restart_is_marked_merged(self):
        """PR 建好後被殺、重啟前人已把 PR 合進 master → 直接標 merged：不 create、不等待、閘門已過、處理 e2。

        修正前：查不到 open PR → create（真 GitHub 會失敗）→ hard 暫停後 hold。

        @return None
        """
        # STEP 01: 中斷 → 人合併 → 重啟
        self.kill_while_opening_hard()
        self.human_merges_cp_pr()
        self.restart()
        # STEP 02: merged、沒有第二次 create、沒有等待、e2 被處理
        self.assertEqual(checkpoint(self.config)["status"], "merged")
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        self.mocks["wait_for_release"].assert_not_called()
        self.mocks["process_one_entry"].assert_called_once()

    def test_soft_pr_merged_before_restart_is_marked_merged(self):
        """soft 斷點同情境 → merged（修正前：再 create、真 GitHub 失敗時被標 failed）。

        @return None
        """
        # STEP 01: soft；中斷 → 人合併 → 重啟
        self.set_checkpoint(mode="soft")
        with kill_after_gh("pr create"):
            with self.assertRaises(SimulatedKill):
                self.restart()
        self.human_merges_cp_pr()
        self.restart()
        # STEP 02: merged、沒有第二次 create
        self.assertEqual(checkpoint(self.config)["status"], "merged")
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)

    def test_release_racing_merged_check_keeps_released(self):
        """已合併判斷之後、標 merged 之前被 release → 維持 released（只改 opening），閘門照樣已過。

        @return None
        """
        # STEP 01: 中斷 → 人合併 → 重啟時判斷完被放行（create=True：修正前沒有這個函式，patch 不會生效）
        self.kill_while_opening_hard()
        self.human_merges_cp_pr()
        real_check = getattr(runner, "opening_checkpoint_merged", None)

        def racing(config, *args, **kwargs):
            """判斷、放行、回原結果。"""
            result = real_check(config, *args, **kwargs)
            release(config)
            return result

        with mock.patch.object(runner, "opening_checkpoint_merged", racing, create=True):
            self.restart()
        # STEP 02: released、沒有第二次 create、e2 被處理
        self.assertEqual(checkpoint(self.config)["status"], "released")
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        self.mocks["process_one_entry"].assert_called_once()

    def assert_open_failed_with(self, fragment):
        """重啟之後：仍是 opening、以 checkpoint_open_failed 暫停、失敗原因含 fragment。

        @param fragment 預期出現在 last_error 裡的字串
        @return None
        """
        # STEP 01: 狀態與原因
        found = checkpoint(self.config)
        self.assertEqual(found["status"], "opening")
        self.assertEqual(self.runner_state().get("reason"), OPEN_FAILED_REASON)
        self.assertIn(fragment, found.get("last_error") or "")

    def test_fetch_failure_does_not_guess(self):
        """補完 opening 前的 fetch 失敗 → 不拿舊的 origin/<pr_base> 判斷，當開啟失敗（hard 暫停）。

        @return None
        """
        # STEP 01: 中斷 → 重啟時 fetch 失敗
        self.kill_while_opening_hard()
        with git_failing_on(("fetch",)):
            self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assert_open_failed_with("fetch")

    def test_merged_check_failure_does_not_guess(self):
        """已合併判斷的 merge-base 失敗（非 0 非 1）→ 當開啟失敗，不當成沒合併、繼續推。

        @return None
        """
        # STEP 01: 中斷 → 重啟時判斷失敗
        self.kill_while_opening_hard()
        with git_failing_when(is_ancestor_against_origin):
            self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assert_open_failed_with("是否已合進")

    def test_remote_ancestry_failure_does_not_push(self):
        """人推了修正、判斷遠端是否含本機 tip 的 merge-base 失敗 → 當開啟失敗（原因寫明是判斷失敗），不去推。

        @return None
        """
        # STEP 01: 中斷 → 人推修正 → 重啟時判斷失敗
        self.kill_while_opening_hard()
        self.human_pushes_fix_to_cp()
        with git_failing_when(is_ancestor_between_shas):
            self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assert_open_failed_with("判斷遠端 cp 分支")


class WaitForReleaseRefreshTest(RealTopologyHarness):
    """MINOR 3：hard 斷點帶著 pr_unverified 在 wait_for_release 等待時，輪詢順便補查連結；補查失敗不打斷等待。"""

    def setUp(self):
        """w0 已 opened、連結未知；等待相關設定給值；sleep 換成第 N 次時放行。

        @return None
        """
        # STEP 01: opened＋pr_unverified；GitHub 上其實有 PR
        super().setUp()
        self.set_checkpoint(status="opened", branch=CP_BRANCH, pr_url="", pr_unverified=True)
        self.use_gh(prs=[cp_pr_on_base(EXISTING_CP_PR_URL)])
        self.config.update({"max_wait_hours": 1, "notify_pause_remind_hours": 1})
        # sleep 被呼叫的次數
        self.sleeps = []

        def fake_sleep(_seconds):
            """第 RELEASE_ON_SLEEP_CALL 次放行。"""
            self.sleeps.append(_seconds)
            if len(self.sleeps) == RELEASE_ON_SLEEP_CALL:
                release(self.config)

        patcher = mock.patch.object(runner.time, "sleep", fake_sleep)
        patcher.start()
        self.addCleanup(patcher.stop)

    def wait(self):
        """跑真的 wait_for_release；例外換成字串，讓「等待被打斷」以 AssertionError 呈現。

        @return True／False，或 "raised: <例外>"
        """
        # STEP 01: 呼叫
        try:
            return REAL_WAIT_FOR_RELEASE(self.config, HARD_CHECKPOINT_ID)
        except Exception as exc:  # pylint: disable=broad-except
            return "raised: %r" % exc

    def test_link_is_filled_while_waiting(self):
        """等待中補查到 PR → 補上連結、清旗標，之後照常放行。

        @return None
        """
        # STEP 01: 等待
        self.assertIs(self.wait(), True)
        found = checkpoint(self.config)
        self.assertEqual((found["pr_url"], found["pr_unverified"]), (EXISTING_CP_PR_URL, False))

    def test_refresh_failure_does_not_interrupt_waiting(self):
        """補查本身拋例外 → 記事件、等待照常，放行後回 True。

        @return None
        """
        # STEP 01: 補查拋例外
        with mock.patch.object(runner, "refresh_unverified_checkpoint_prs", side_effect=OSError("disk gone")):
            self.assertIs(self.wait(), True)
        self.assertIn("disk gone", json.dumps(events(self.config, "checkpoint_pr_verify_failed"), ensure_ascii=False))


class ReleaseRaceTest(RealTopologyHarness):
    """MINOR 4：release 與開啟中的斷點撞上——開成功不可把 released 寫回 opened；開失敗不可再暫停或標 failed。"""

    def release_after_pr_step(self):
        """find_or_create_checkpoint_pr 跑完（成功或失敗）之後、落盤之前被 release。

        @return mock.patch 物件（with 用）
        """
        # STEP 01: 轉發後放行
        real_step = runner.find_or_create_checkpoint_pr

        def wrapper(config, *args, **kwargs):
            """轉發、放行、回傳原結果。"""
            result = real_step(config, *args, **kwargs)
            release(config)
            return result

        return mock.patch.object(runner, "find_or_create_checkpoint_pr", wrapper)

    def test_success_keeps_released(self):
        """開成功時已被放行 → 狀態維持 released，連結照補。

        @return None
        """
        # STEP 01: soft 斷點開啟中被放行
        self.set_checkpoint(mode="soft")
        with self.release_after_pr_step():
            runner.open_checkpoint(self.config, HARD_CHECKPOINT_ID)
        # STEP 02: released、有連結
        found = checkpoint(self.config)
        self.assertEqual((found["status"], found["pr_url"]), ("released", FIRST_CREATED_PR_URL))

    def test_hard_failure_after_release_proceeds(self):
        """hard 斷點停在 opening、重啟補開失敗時已被放行 → 不以 checkpoint_open_failed 暫停，閘門已過、處理 e2。

        @return None
        """
        # STEP 01: opening；create 會失敗
        self.set_checkpoint(status="opening", branch=CP_BRANCH)
        set_gh_modes(self.gh, create_mode="fail")
        with self.release_after_pr_step():
            self.restart()
        # STEP 02: released、沒有開啟失敗的暫停、e2 被處理
        self.assertEqual(checkpoint(self.config)["status"], "released")
        self.assertNotEqual(self.runner_state().get("reason"), OPEN_FAILED_REASON)
        self.mocks["process_one_entry"].assert_called_once()

    def test_soft_failure_after_release_is_not_marked_failed(self):
        """soft 斷點同情境 → 維持 released，不被 mark_checkpoint_failed 覆寫成 failed。

        @return None
        """
        # STEP 01: soft opening；create 會失敗
        self.set_checkpoint(status="opening", branch=CP_BRANCH, mode="soft")
        set_gh_modes(self.gh, create_mode="fail")
        with self.release_after_pr_step():
            self.restart()
        # STEP 02: released
        self.assertEqual(checkpoint(self.config)["status"], "released")


class AutoLineThresholdBaseTest(RealTopologyHarness):
    """MINOR 5：auto 行數門檻的比較基準只接受本機實際存在的分支；git 失敗不可靜默變成 0 行。"""

    def setUp(self):
        """w0 已 opened（本機分支在目前的整合分支 tip）；之後整合分支多 3 行；行數門檻 1。

        @return None
        """
        # STEP 01: w0 opened、本機有分支
        super().setUp()
        run_git(self.work, "branch", CP_BRANCH, INTEGRATION_BRANCH)
        self.set_checkpoint(status="opened", branch=CP_BRANCH)
        # STEP 02: 整合分支多 3 行
        with open(os.path.join(self.work, "lines.js"), "w", encoding="utf-8") as handle:
            handle.write("a\nb\nc\n")
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", "lines")
        self.config["checkpoint_max_lines"] = 1

    def test_missing_branch_of_later_checkpoint_is_skipped(self):
        """最後一個斷點是從 opening 放行、本機分支從沒建立 → 跳過它、用前一個真的存在的分支當基準 → 門檻成立。

        修正前：拿不存在的分支去 diff，寬容版 git_out 回空字串 → 0 行 → 不成立。

        @return None
        """
        # STEP 01: 從 opening 放行、分支不存在的斷點
        record = dict(
            runner.CHECKPOINT_FIELD_DEFAULTS, id="auto-20300101-000000", after={"wave": None}, mode="soft",
            pr_base=BASE_BRANCH, title="t", status="released", branch="r18-migration/cp-auto-20300101-000000",
        )
        runner.mutate_queue(self.config, lambda queue: queue["checkpoints"].append(record))
        # STEP 02: 判斷（raise 換成字串，讓「拿不存在的分支去 diff」也以 AssertionError 呈現）
        try:
            needed = runner.auto_checkpoint_needed(self.config, runner.load_queue(self.config))[0]
        except RuntimeError as exc:
            needed = "raised: %s" % exc
        self.assertIs(needed, True)

    def test_diff_failure_raises(self):
        """diff 失敗 → raise，不當成 0 行。

        @return None
        """
        # STEP 01: diff 失敗
        with git_failing_on(("diff",)):
            with self.assertRaises(RuntimeError):
                runner.auto_checkpoint_needed(self.config, runner.load_queue(self.config))

    def test_branch_probe_failure_raises(self):
        """查分支是否存在的 rev-parse 失敗（退出碼不是「不存在」的 1）→ raise，不當成分支不存在。

        @return None
        """
        # STEP 01: rev-parse 失敗
        with git_failing_on(("rev-parse",)):
            with self.assertRaises(RuntimeError):
                runner.auto_checkpoint_needed(self.config, runner.load_queue(self.config))


class DonePrFailedNotifyTest(RestartHarness):
    """BONUS-2：模組已 done、只是頁面 PR 有問題，通知不可以用 module_blocked（「⛔ … PR 未開成功」讀起來像卡住）。"""

    def test_reconciled_done_with_pr_lookup_failure(self):
        """對帳補 done、PR 查詢失敗 → 通知事件是 module_done_pr_failed、標題寫明已完成；不發 module_blocked。

        @return None
        """
        # STEP 01: 發佈後被殺、連結沒落盤、重啟時查詢會失敗
        gh = use_scripted_gh(self.fixture)
        publish(self.fixture, kill_before_done=True)
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, ENTRY_ID).update({"pr_url": None}))
        set_gh_modes(gh, list_mode="fail")
        self.restart()
        # STEP 02: 事件與標題
        sent = [(call.args[1], call.args[2]) for call in self.mocks["notify"].call_args_list]
        self.assertNotIn("module_blocked", [name for name, _title in sent])
        titles = [title for name, title in sent if name == DONE_PR_FAILED_EVENT]
        self.assertEqual(len(titles), 1, sent)
        self.assertIn("已完成", titles[0])

    def test_notify_script_treats_new_event_as_high(self):
        """notify.sh 把新事件列為 HIGH（一定送，與原本的 module_blocked 同級），並給它自己的 emoji。

        @return None
        """
        # STEP 01: 讀腳本
        with open(os.path.join(HELPERS_DIR, "notify.sh"), encoding="utf-8") as handle:
            # notify.sh 全文
            script = handle.read()
        high_line = [line for line in script.splitlines() if line.startswith("readonly high_events=")]
        self.assertEqual(len(high_line), 1)
        self.assertIn(DONE_PR_FAILED_EVENT, high_line[0].split('"')[1].split())
        # STEP 02: emoji 分支（實際執行 event_emoji）
        probe = 'eval "$(sed -n "/^event_emoji()/,/^}/p" "$0")"; event_emoji %s' % DONE_PR_FAILED_EVENT
        result = subprocess.run(
            ["/bin/bash", "-c", probe, os.path.join(HELPERS_DIR, "notify.sh")], capture_output=True, text=True, timeout=NOTIFY_PROBE_TIMEOUT_SECONDS, check=False
        )
        self.assertNotIn(result.stdout.strip(), ("", "ℹ️", "⛔"), result.stderr)


if __name__ == "__main__":
    unittest.main()
