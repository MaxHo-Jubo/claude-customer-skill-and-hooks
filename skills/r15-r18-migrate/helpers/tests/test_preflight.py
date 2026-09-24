"""runner.py 1.1.1 review 修復的回歸測試——模組開工前的 git 前置作業（本機領先偵測）、重啟時放回被中斷的 entry、cmd_run 對前置失敗的處置。

由原 test_review_fixes.py 依主題拆出（1.1.2 第六批，測試內容逐字搬移；之後依 review 補過註解與具名常數，斷言未變）；
共用的 fixture 與小工具在 review_fixtures.py。
唯一不是逐字搬移的地方：原本的 `MergeToIntegrationTest._git_with_failure(...)` 改呼叫 review_fixtures.git_with_failure
（import 那個 TestCase 會被 discover 重複收集）。
每一組對應一個 review 確認過的缺陷。外部狀態一律用真的：行程與 process group、flock、
git（bare 遠端＋工作 repo，含用 pre-receive hook 造出來的推送失敗）、一支會留紀錄的假 gh。
mock 只用在三種地方：
(1) 測試裡造不出來的事件——斷電（只驗 fsync／replace 的呼叫順序）、訊號剛好落在某一行；
(2) 注入失敗——R15 原檔讀取失敗、合併失敗、合併當下 entry 被人從 queue 移除；
(3) 隔離與受測行為無關的副作用——通知、進度報表、診斷包、crash 流程。

執行方式（在 skill 根目錄）：
    python3 -B -m unittest discover -s helpers/tests -v
只跑這個檔：
    python3 -B -m unittest discover -s helpers/tests -p test_preflight.py -v

`-B` 與下方的 `sys.dont_write_bytecode` 是為了不在 skill 目錄留下 __pycache__。
"""

import argparse
import os
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
    GIT_FATAL_EXIT_CODE,
    SHA_PREFIX_CHARS,
    NOTIFY_MAX_TEXT_CHARS,
    IMPOSSIBLE_SHA,
    INTEGRATION_BRANCH,
    BASE_BRANCH,
    ENTRY_BRANCH,
    CHECKPOINT_BRANCH,
    ENTRY_ID,
    R15_RELATIVE_PATH,
    CHECKPOINT_ID,
    run_git,
    build_fixture,
    _register_opened_checkpoint,
    start_patches,
    git_with_failure,
)


class ModulePreflightTest(unittest.TestCase):
    """第十批起：本機整合分支上「不是 runner 合進來的 commit」要在模組開工前被偵測到、用專屬原因暫停（呼叫端據此鎖定）。

    本機領先遠端本身是常態——前置作業會把基準分支與斷點分支合進本機而不推；排除 merge commit、
    排除可從基準／斷點分支到達的 commit 之後還剩下的，才是上一輪沒走完的發佈段（合併了但推送失敗
    或被中斷、退不回去、或人只跑了 `unblock --runner` 沒把本機對齊）留下的：原本的 `--ff-only`
    同步對它是 no-op，下一個 entry 會從那個 commit 切分支、最後把它推上去。
    """

    def _preflight_fixture(self):
        """真的 git 環境：獨立的基準分支從基線切出、推上遠端、再前進一個 commit；停在整合分支上。

        基準分支一定要跟整合分支分開而且已經前進——前置作業會把它合進本機整合分支、而且不推，
        這正是「runner 自己造出來的本機領先」；第十批的對照組把基準分支設成整合分支本身
        （合併是 no-op），跑不到這個拓撲，回歸就這樣漏掉了。

        @return build_fixture 的回傳值
        """
        # STEP 01: fixture＋基準分支前進一個 commit＋切回整合分支
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-preflight-"))
        work = fixture["config"]["repo_dir"]
        fixture["config"]["base_branch"] = BASE_BRANCH
        run_git(work, "checkout", "-b", BASE_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(work, "hotfix.js"), "w", encoding="utf-8") as handle:
            handle.write("// landed on base after the integration branch was cut\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "base moves")
        run_git(work, "push", "-u", "origin", BASE_BRANCH)
        run_git(work, "checkout", INTEGRATION_BRANCH)
        return fixture

    def test_own_base_merge_is_not_treated_as_ahead(self):
        """基準分支前進、前置作業把它合進本機整合分支而不推：這種領先是 runner 自己造的，下一輪不可以當成異常。

        修正前：第一次通過（並留下領先的 commit），第二次就 integration_local_ahead＋鎖定——只要
        base 動過、而該 entry 沒走到 push（失敗／blocked／額度／斷點），runner 就鎖死。
        """
        # STEP 01: 連跑兩次前置作業
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        ahead = run_git(work, "rev-list", "--count", "origin/%s..%s" % (INTEGRATION_BRANCH, INTEGRATION_BRANCH))
        self.assertNotEqual(ahead, "0", "前置條件：base 合併後本機整合分支應該領先遠端")
        second = runner.module_preflight(config, runner.load_queue(config))

        # STEP 02: 第二次照樣通過
        self.assertTrue(second[0], "%s: %s" % (second[1], second[2]))

    def test_checkpoint_conflict_after_base_merge_does_not_lock_next_round(self):
        """base 已合進本機、斷點回流衝突退出：下一輪要再回 master_conflict（真正的原因），不能變成 integration_local_ahead 鎖定。

        第十二批的記錄式判定只在前置作業全部成功時才記本機 HEAD，這條路徑 HEAD 動了但沒記，下一輪就
        誤鎖、細節還說「不是 runner 自己做的合併」；判定改成結構式（只數不可從 base／斷點分支到達的
        非 merge commit）之後沒有這個窗。
        """
        # STEP 01: base 與斷點分支改同一個檔（不同內容）；斷點登記成 opened
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        run_git(work, "checkout", BASE_BRANCH)
        with open(os.path.join(work, R15_RELATIVE_PATH), "w", encoding="utf-8") as handle:
            handle.write("// base version\n")
        run_git(work, "commit", "-am", "base edits a.js")
        run_git(work, "push", "origin", BASE_BRANCH)
        run_git(work, "checkout", "-b", CHECKPOINT_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(work, R15_RELATIVE_PATH), "w", encoding="utf-8") as handle:
            handle.write("// checkpoint version\n")
        run_git(work, "commit", "-am", "checkpoint edits a.js")
        run_git(work, "checkout", INTEGRATION_BRANCH)
        runner.mutate_queue(config, _register_opened_checkpoint)

        # STEP 02: 兩輪都是 master_conflict；本機仍領先（base 合進來了）、但不是鎖定
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertEqual(first[1], "master_conflict", first[2])
        ahead = run_git(work, "rev-list", "--count", "origin/%s..%s" % (INTEGRATION_BRANCH, INTEGRATION_BRANCH))
        self.assertNotEqual(ahead, "0", "前置條件：base 合併後本機整合分支應該領先遠端")
        second = runner.module_preflight(config, runner.load_queue(config))
        self.assertEqual(second[1], "master_conflict", second[2])

    def test_own_checkpoint_merge_is_not_treated_as_ahead(self):
        """斷點分支多了人工修正、前置作業把它合進本機整合分支而不推：這種領先也是 runner 自己做的，下一輪照常通過。"""
        # STEP 01: 斷點分支從整合分支切出、多一個不衝突的 commit、登記成 opened
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        run_git(work, "checkout", "-b", CHECKPOINT_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(work, "review-fix.js"), "w", encoding="utf-8") as handle:
            handle.write("// pushed to the checkpoint branch by a reviewer\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "review fix on checkpoint")
        run_git(work, "checkout", INTEGRATION_BRANCH)
        runner.mutate_queue(config, _register_opened_checkpoint)

        # STEP 02: 兩輪都通過
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        self.assertTrue(os.path.exists(os.path.join(work, "review-fix.js")), "前置條件：斷點分支應已回流")
        second = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(second[0], "%s: %s" % (second[1], second[2]))

    def test_local_ahead_is_named_and_left_untouched(self):
        """前置作業之後本機整合分支又多了一個不是 runner 做的 commit：回專屬原因、動作在前、detail 帶兩個 sha 與那個 commit、本機分支不動。"""
        # STEP 01: 先跑一次前置作業（base 已合進本機），再在整合分支上多一個 commit、不推
        fixture = self._preflight_fixture()
        work = fixture["config"]["repo_dir"]
        first = runner.module_preflight(fixture["config"], runner.load_queue(fixture["config"]))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        with open(os.path.join(work, "unpushed.js"), "w", encoding="utf-8") as handle:
            handle.write("// merged locally, never pushed\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "foreign-commit-subject")
        local_sha = run_git(work, "rev-parse", "HEAD")
        ok, reason, detail = runner.module_preflight(fixture["config"], runner.load_queue(fixture["config"]))

        # STEP 02: 專屬原因、兩個 sha 與那個 commit 的主旨都在、分支沒被動；對齊指令排在診斷之前（通知會截尾，動作要先看到）
        self.assertFalse(ok)
        self.assertEqual(reason, runner.LOCAL_AHEAD_REASON, detail)
        self.assertIn(local_sha[:SHA_PREFIX_CHARS], detail)
        self.assertIn(fixture["base_sha"][:SHA_PREFIX_CHARS], detail)
        self.assertIn("foreign-commit-subject", detail)
        self.assertIn("1 個", detail)
        self.assertLess(detail.index("reset --hard"), detail.index(local_sha[:SHA_PREFIX_CHARS]), detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), local_sha)

    def test_local_ahead_action_survives_notification_truncation(self):
        """用正式預設的整合分支名走一次真的 enter_paused（鎖定），把通知照 notify.sh 的規則（emoji＋標題＋內文，300 字截斷）
        組起來：截斷後仍要看得到對齊指令與 unblock --runner。

        期望值是 notify.sh 的 max_text_chars=300 這個外部契約，不是實作自己的長度常數——拿實作的常數當期望值，
        常數改成 1000 測試照樣綠。第十二批的句子 191 字，這一段截掉 `git reset --hard` 與「再 unblock --runner」（第十二輪實測）。
        """
        # STEP 01: 狀態目錄＋通知 mock；用預設分支名組細節，走真的 enter_paused（會凍結 runner 級診斷包、寫狀態）
        config = {"state_dir": tempfile.mkdtemp(prefix="r18-budget-"), "notify_channel": "none"}
        runner.ensure_state_dir(config)
        runner.write_queue_new(config, {"modules": [], "runner_state": {"state": "running"}})
        detail = runner.local_ahead_detail(runner.DEFAULT_INTEGRATION_BRANCH, "3", "a" * SHA_PREFIX_CHARS, "b" * SHA_PREFIX_CHARS, "abc1234 x\ndef5678 y\n0123456 z")
        with mock.patch.object(runner, "notify") as notify:
            self.assertEqual(runner.enter_paused(config, runner.LOCAL_AHEAD_REASON, detail, force_hold=True), runner.EXIT_PAUSED)
        _config, _event, title, body = notify.call_args.args

        # STEP 02: 照 notify.sh 組字並截斷（emoji 1 字＋空白＋標題＋換行＋內文）
        text = ("🔴 %s\n%s" % (title, body))[:NOTIFY_MAX_TEXT_CHARS]
        self.assertIn("reset --hard origin/%s" % runner.DEFAULT_INTEGRATION_BRANCH, text, text)
        self.assertIn("unblock --runner", text, text)

    def test_checkpoint_ref_listing_failure_does_not_lock(self):
        """列本機 ref 的指令失敗：不能把「查不到」當成「斷點分支都不存在」——那會讓回流進來的斷點 commit 全被當成外來的而鎖定。"""
        # STEP 01: 斷點分支回流進本機（自己做的領先），再讓 for-each-ref 失敗
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        run_git(work, "checkout", "-b", CHECKPOINT_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(work, "review-fix.js"), "w", encoding="utf-8") as handle:
            handle.write("// reviewer fix\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "review fix on checkpoint")
        run_git(work, "checkout", INTEGRATION_BRANCH)
        runner.mutate_queue(config, _register_opened_checkpoint)
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        fake_git = git_with_failure(("for-each-ref",), (GIT_FATAL_EXIT_CODE, "", "simulated for-each-ref failure"))
        with mock.patch.object(runner, "git", fake_git):
            ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))

        # STEP 02: 不放行、但也不是鎖定的那個原因；錯誤有帶出來
        self.assertFalse(ok)
        self.assertNotEqual(reason, runner.LOCAL_AHEAD_REASON, detail)
        self.assertIn("simulated for-each-ref failure", detail)

    def test_foreign_commit_listing_failure_is_not_treated_as_zero(self):
        """列「不是 runner 合進來的 commit」的指令失敗：不能當成 0 個放行。"""
        # STEP 01: 造出領先（base 合併），再讓那條 git log 失敗
        fixture = self._preflight_fixture()
        config = fixture["config"]
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        fake_git = git_with_failure(("log", "--no-merges"), (GIT_FATAL_EXIT_CODE, "", "simulated log failure"))
        with mock.patch.object(runner, "git", fake_git):
            ok, _reason, detail = runner.module_preflight(config, runner.load_queue(config))
        self.assertFalse(ok)
        self.assertIn("simulated log failure", detail)

    def test_not_ahead_passes(self):
        """對照組：本機與遠端一致（基準分支沒動）時前置作業照常通過。"""
        # STEP 01: 基準分支就用整合分支本身，什麼都不合併
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-preflight-plain-"))
        fixture["config"]["base_branch"] = INTEGRATION_BRANCH
        run_git(fixture["config"]["repo_dir"], "checkout", INTEGRATION_BRANCH)
        queue = runner.load_queue(fixture["config"])
        ok, reason, detail = runner.module_preflight(fixture["config"], queue)
        self.assertTrue(ok, "%s: %s" % (reason, detail))

    def test_local_tip_read_failure_is_said_plainly(self):
        """領先且讀不到本機 tip：訊息要說「讀取失敗」，不能渲染成空字串讓人以為 sha 是空的。"""
        # STEP 01: 造出領先，再讓讀本機整合分支 sha 那一次失敗
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        with open(os.path.join(work, "unpushed.js"), "w", encoding="utf-8") as handle:
            handle.write("// unpushed\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "unpushed")
        fake_git = git_with_failure(("rev-parse", INTEGRATION_BRANCH), (GIT_FATAL_EXIT_CODE, "", "simulated tip failure"))
        with mock.patch.object(runner, "git", fake_git):
            ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))

        # STEP 02: 仍判定領先，訊息帶「讀取失敗」
        self.assertFalse(ok)
        self.assertEqual(reason, runner.LOCAL_AHEAD_REASON, detail)
        self.assertIn("讀取失敗", detail)

    def test_ahead_count_read_failure_is_not_treated_as_zero(self):
        """rev-list 本身失敗：不能當成「領先 0 個」放行，要當成讀不到而暫停。"""
        # STEP 01: 注入 rev-list 失敗
        fixture = self._preflight_fixture()
        fake_git = git_with_failure(("rev-list", "--count"), (GIT_FATAL_EXIT_CODE, "", "simulated rev-list failure"))
        queue = runner.load_queue(fixture["config"])
        with mock.patch.object(runner, "git", fake_git):
            ok, _reason, detail = runner.module_preflight(fixture["config"], queue)

        # STEP 02: 不放行、錯誤有帶出來
        self.assertFalse(ok)
        self.assertIn("simulated rev-list failure", detail)


class RecoverInterruptedEntriesTest(unittest.TestCase):
    """重啟時把上一輪被中斷的 entry 放回 pending：running 之外 waiting_quota 也要——它是停止訊號落在額度等待
    期間留下的，取件只挑 pending、unblock 只收 failed／blocked，不放回就永久卡住、沒有任何指令能救。
    """

    def test_running_and_waiting_quota_go_back_to_pending(self):
        """running 與 waiting_quota 都回 pending、attempts 不變；其餘狀態不動；回傳被復原的 id。"""
        # STEP 01: 五種狀態各一個
        queue = {
            "modules": [
                {"id": "a", "status": "running", "attempts": 2},
                {"id": "b", "status": "waiting_quota", "attempts": 1},
                {"id": "c", "status": "pending", "attempts": 0},
                {"id": "d", "status": "done", "attempts": 0},
                {"id": "e", "status": "blocked", "attempts": 0},
            ]
        }
        recovered = runner.recover_interrupted_entries(queue)

        # STEP 02: 只有前兩個被放回 pending
        self.assertEqual(recovered, ["a", "b"])
        self.assertEqual([m["status"] for m in queue["modules"]], ["pending", "pending", "pending", "done", "blocked"])
        self.assertEqual([m["attempts"] for m in queue["modules"]], [2, 1, 0, 0, 0])


class RunPreflightPauseTest(unittest.TestCase):
    """cmd_run 對 git 前置失敗的處置：本機領先要鎖定；已鎖定時 pre-flight 之前就退出。"""

    def setUp(self):
        """狀態目錄裡放一份有 pending entry 的 queue；主迴圈走到 git 前置之前會碰到的外部依賴全部隔離。"""
        # STEP 01: 狀態目錄與 queue
        self.state_dir = tempfile.mkdtemp(prefix="r18-run-preflight-")
        self.config = {
            "state_dir": self.state_dir,
            "notify_channel": "none",
            "integration_branch": INTEGRATION_BRANCH,
            # 熔斷門檻沿用 runner 預設值（這組測試停在第一個模組之前，不會累積到它）
            "circuit_breaker_n": runner.DEFAULT_CIRCUIT_BREAKER_N,
        }
        runner.ensure_state_dir(self.config)
        entry = dict(runner.RUNTIME_FIELD_DEFAULTS, id=ENTRY_ID, branch=ENTRY_BRANCH, type="page", wave=0, r15_paths=[])
        runner.write_queue_new(
            self.config,
            {"integration_tip_sha": IMPOSSIBLE_SHA, "runner_state": {"state": "idle"}, "modules": [entry]},
        )
        self.args = argparse.Namespace(max_modules=None)
        # STEP 02: 隔離——handler 安裝、必填檢查、pre-flight、指紋、通知、每日摘要、額度
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
            # 1.1.2 第五批：啟動時的重啟對帳會跑 git，這組測試的狀態目錄沒有 repo（對帳另見 test_reconcile.py）
            "reconcile_published_entries",
        )
        # 對帳沒有補任何 entry（回 None，啟動時就不看 auto 斷點門檻）
        self.mocks["reconcile_published_entries"].return_value = None
        self.mocks["require_config"].return_value = True
        self.mocks["lockfile_hash"].return_value = None
        self.mocks["preflight"].return_value = 0
        self.mocks["environment_fingerprint"].return_value = {}
        self.mocks["quota_snapshot"].return_value = {}
        self.mocks["quota_blocks_start"].return_value = (False, "", None)

    def test_local_ahead_pause_is_held(self):
        """git 前置回本機領先：進入暫停時要 force_hold；一般的 diverged 不鎖（對照組）。"""
        # STEP 01: 兩種原因各跑一次主迴圈
        for reason, expect_hold in ((runner.LOCAL_AHEAD_REASON, True), ("integration_diverged", False)):
            with self.subTest(reason=reason):
                with mock.patch.object(runner, "module_preflight", return_value=(False, reason, "模擬")), \
                        mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
                    self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)
                # STEP 02: 原因原樣傳入、hold 旗標對
                self.assertEqual(paused.call_args.args[1], reason)
                self.assertEqual(paused.call_args.kwargs.get("force_hold", False), expect_hold)

    def test_opened_hard_checkpoint_is_waited_before_taking_next_entry(self):
        """上一輪在 hard 斷點等人放行時被停掉：重啟後要先回到等待，不能先處理下一個模組（人工閘門被繞過）。

        斷點停在 opened，而模組完成後的斷點檢查只看 pending 的斷點，所以主迴圈要在取件之前自己找 opened 的 hard 斷點。
        """
        # STEP 01: queue 裡放一個 opened 的 hard 斷點；記下「等待」與「取件後的 git 前置」誰先被呼叫
        # 呼叫紀錄：("wait", 斷點 id) 或 ("preflight", None)，依呼叫順序
        calls = []

        def add_checkpoint(queue):
            """登記 opened 的 hard 斷點（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
            @return None
            """
            # STEP 01: 斷點清單換成只有一個 opened 的 hard 斷點
            queue["checkpoints"] = [{"id": CHECKPOINT_ID, "status": "opened", "mode": "hard", "branch": CHECKPOINT_BRANCH}]

        runner.mutate_queue(self.config, add_checkpoint)

        def fake_wait(config, checkpoint_id):
            """記錄後放行：跟真的一樣，只有斷點真的變成 released 才回 True（不改狀態就回 True 會讓主迴圈反覆回來等）。

            @param config runner 設定
            @param checkpoint_id 要等的斷點 id
            @return True（斷點已改成 released）
            """
            # STEP 01: 記錄呼叫
            calls.append(("wait", checkpoint_id))

            def release(queue):
                """人工放行（就地修改，沿用 mutate_queue 的寫入契約）。

                @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
                @return None
                """
                # STEP 01: 斷點狀態改成 released
                runner.find_checkpoint(queue, checkpoint_id)["status"] = "released"

            # STEP 02: 真的把斷點改成 released 再回 True
            runner.mutate_queue(config, release)
            return True

        def fake_preflight(config, queue):
            """記錄後用一般暫停把主迴圈結束掉。

            @param config runner 設定（不使用）
            @param queue 整份 queue（不使用）
            @return (False, "integration_diverged", "模擬")：讓主迴圈走一般暫停
            """
            # STEP 01: 記錄呼叫、回一般暫停
            calls.append(("preflight", None))
            return False, "integration_diverged", "模擬"

        with mock.patch.object(runner, "wait_for_release", fake_wait), \
                mock.patch.object(runner, "module_preflight", fake_preflight), \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)

        # STEP 02: 先等斷點、放行後才走到取件；等待逾時要走 paused_for_review 出口（斷點重設回 opened 再跑一次）
        self.assertEqual(calls[:2], [("wait", CHECKPOINT_ID), ("preflight", None)], calls)
        runner.mutate_queue(self.config, add_checkpoint)
        with mock.patch.object(runner, "wait_for_release", return_value=False), \
                mock.patch.object(runner, "module_preflight") as preflight, \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)
        self.assertEqual(paused.call_args.args[1], "paused_for_review")
        preflight.assert_not_called()

    def test_released_checkpoint_is_not_waited_again(self):
        """對照組：已放行（released）或已合併的 hard 斷點不再等，主迴圈直接取件。"""
        # STEP 01: released 的 hard 斷點
        def add_checkpoint(queue):
            """登記 released 的 hard 斷點（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
            @return None
            """
            # STEP 01: 斷點清單換成只有一個 released 的 hard 斷點
            queue["checkpoints"] = [{"id": CHECKPOINT_ID, "status": "released", "mode": "hard", "branch": CHECKPOINT_BRANCH}]

        runner.mutate_queue(self.config, add_checkpoint)
        # 一被呼叫就拋（不是回 True）：回 True 又不改狀態的話，實作若真的去等它，主迴圈會無限迴圈而不是紅
        with mock.patch.object(runner, "wait_for_release", side_effect=AssertionError("不該等已放行的斷點")) as wait, \
                mock.patch.object(runner, "module_preflight", return_value=(False, "integration_diverged", "模擬")), \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)
        wait.assert_not_called()

    def test_hold_exits_before_preflight(self):
        """runner_state.hold 為真：pre-flight 一次都不跑就以 EXIT_PAUSED 退出，並留一筆 hold_active 事件。"""
        # STEP 01: 狀態改成鎖定中

        def hold(queue):
            """鎖定（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
            @return None
            """
            # STEP 01: runner_state 換成本機領先的鎖定
            queue["runner_state"] = {"state": "paused", "reason": runner.LOCAL_AHEAD_REASON, "hold": True}

        runner.mutate_queue(self.config, hold)
        self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)

        # STEP 02: pre-flight 沒被呼叫；事件有記
        self.mocks["preflight"].assert_not_called()
        with open(runner.state_path(self.config, "runner.log.jsonl"), "r", encoding="utf-8") as handle:
            self.assertIn('"event": "hold_active"', handle.read())


if __name__ == "__main__":
    unittest.main()
