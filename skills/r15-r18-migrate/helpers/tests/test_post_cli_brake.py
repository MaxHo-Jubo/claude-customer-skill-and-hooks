"""runner.py 1.1.2 第七批項目 3 的回歸測試：CLI 跑完之後的暫停跨簽名煞車。

「同簽名連續第二次就鎖定」只擋得住同一種失敗；幾種 CLI 之後的失敗（整合分支推送失敗、切換整合分支失敗、ff-merge
環境類失敗、CLI 判 auth_expired、crash）輪流出現時，每次 launchd 重啟都再燒一次完整模組。修正後 runner_state 記
post_cli_pause_count：CLI 呼叫之後的暫停逐次 +1，累計到門檻就鎖定（hold）；有模組完成、`unblock --runner` 歸零；
CLI 之前的暫停（git 前置、準備分支）不計。

每一輪是一次真的 cmd_run（模擬 launchd 重啟：config 從基底重新複製），git 前置、準備分支、發佈段、推送都走真的
bare 遠端＋工作 repo；只換掉 CLI（假件在分支上真的 commit）、判讀、L1、通知與環境檢查。故障一律用真的拓撲或只攔
發佈段那一次 git 呼叫。

共用的 fixture 與小工具從 review_fixtures／test_stale_branch／test_reconcile 匯入（只匯入函式與常數，不匯入 TestCase）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 480; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_post_cli_brake.py -v
"""

import argparse
import contextlib
import io
import os
import stat
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
    ENTRY_ID,
    GIT_FATAL_EXIT_CODE,
    INTEGRATION_BRANCH,
    NOTIFY_MAX_TEXT_CHARS,
    R15_RELATIVE_PATH,
    build_fixture,
    git_with_failure,
    reject_entry_branch_push,
    run_git,
    start_patches,
)
from test_reconcile import add_entry, events, publish  # noqa: E402  pylint: disable=wrong-import-position
from test_stale_branch import (  # noqa: E402  pylint: disable=wrong-import-position
    SECOND_ENTRY_BRANCH,
    SECOND_ENTRY_ID,
    advance_integration,
    install_failing_pre_merge_hook,
)

# user 拍板的鎖定門檻（外部契約，不引用 runner 的常數：常數被改掉時測試要紅）
USER_THRESHOLD = 3
# runner_state 裡 CLI 後暫停計數的欄位名（queue-schema.md 的欄位名是外部契約）
COUNT_FIELD = "post_cli_pause_count"
# 假 CLI 一輪的花費與 session id
ROUND_COST = 0.2
SESSION_ID = "session-brake"
# 假 CLI 判讀結果的預設種類（模組做完）
CLI_DONE = "done"
# 通知事件裡屬於暫停的兩種（crash 走 runner_crashed）
PAUSE_EVENTS = ("paused", "runner_crashed")
# 計數鎖定的通知文字片段（前半句，後接次數）
COUNT_CAUSE_TEXT = "CLI 跑完後連續暫停"
# 同簽名鎖定的通知文字片段
SAME_SIGNATURE_TEXT = "同一原因連續發生"
# 計數欄位格式錯的通知文字片段
MALFORMED_TEXT = "格式錯"
# 解除鎖定的指令（通知截斷後一定要看得到）
UNBLOCK_TEXT = "unblock --runner"
# 冗長拒絕 hook 的填充行數與每行長度：讓推送失敗的細節遠超通知上限
VERBOSE_HOOK_LINES = 12
VERBOSE_HOOK_LINE_CHARS = 40
# 計數欄位的幾種格式錯樣本：字串、布林（bool 是 int 的子類，要另外擋）、負數、null
MALFORMED_COUNTS = ("x", True, -1, None)
# T3.7 預先放進 queue 的計數（驗「不變」要從非零起算，歸零與不動才分得出來）
PRESET_COUNT = 1
# T3.5 預先放進 queue 的計數
RECONCILE_PRESET_COUNT = 2
# 已達上限前一次的 attempts：再失敗一次 entry 就轉 failed，主迴圈改挑下一個 entry
LAST_ATTEMPT_BEFORE_FAIL = runner.MAX_ATTEMPTS - 1
# 門檻前一次：兩輪 CLI 後暫停之後還不該鎖定
BELOW_THRESHOLD = USER_THRESHOLD - 1
# 同簽名煞車鎖定所需的連續次數（既有機制：連續第二次）
SAME_SIGNATURE_ROUNDS = 2
# 熔斷門檻（本檔只有 T3.7 會累加一次失敗，遠低於它）
CIRCUIT_BREAKER_N = 3
# 自動斷點門檻：設得夠大，測試期間不會觸發開斷點（那會呼叫 gh）
CHECKPOINT_MAX_MODULES = 100
CHECKPOINT_MAX_LINES = 100000
# 假 CLI 回報的執行秒數
FAKE_DURATION_SECONDS = 1
# 呼叫序號樣本：第一輪與第二輪
FIRST_ATTEMPT = 1
SECOND_ATTEMPT = 2
# cmd_run 同一個行程處理兩個模組（T3.7：e1 之後接著 e2）
TWO_MODULES = 2


def scoped_merge_failure(match, response):
    """回傳 merge_to_integration 的替身：只在發佈段合併期間讓某一種 git 呼叫失敗，前置作業與準備分支照常。

    @param match 要攔截的 git 參數前綴（tuple）
    @param response 攔截時回的 (code, out, err)
    @return 可以拿去 patch runner.merge_to_integration 的函式
    """
    # 被替換前的真 merge_to_integration（patch 之前取）
    real_merge = runner.merge_to_integration

    def merge(config, entry, expected_tip):
        """在注入期間跑真的 merge_to_integration。

        @param config runner 設定
        @param entry 要合併的 entry
        @param expected_tip 預期的 entry 分支 tip
        @return 真的 merge_to_integration 的回傳值
        """
        # STEP 01: 只在這一段換掉 git
        with mock.patch.object(runner, "git", git_with_failure(match, response)):
            return real_merge(config, entry, expected_tip)

    return merge


def install_verbose_reject_hook(remote):
    """在 bare 遠端裝一支拒絕所有推送、並印出冗長 stderr 的 pre-receive hook（通知截斷測試用）。

    @param remote bare 遠端 repo 的路徑
    @return hook 檔路徑
    """
    # STEP 01: 多行填充的拒絕訊息
    # hook 檔路徑
    hook_path = os.path.join(remote, "hooks", "pre-receive")
    # 填充行（每行一句 echo 到 stderr）
    filler = "\n".join('echo "filler %02d %s" >&2' % (n, "x" * VERBOSE_HOOK_LINE_CHARS) for n in range(VERBOSE_HOOK_LINES))
    with open(hook_path, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/bash\n%s\nexit 1\n" % filler)
    # STEP 02: 執行權限
    os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IXUSR)
    return hook_path


class BrakeHarness(unittest.TestCase):
    """真 cmd_run 的共用隔離：一輪＝一次 launchd 重啟，故障以 run_round 的種類注入。"""

    def setUp(self):
        """真的 git 環境（e1 pending）＋cmd_run 外部依賴隔離。

        @return None
        """
        # STEP 01: fixture；基準分支設成整合分支本身，前置作業的基準合併是 no-op（這裡不測它）
        # build_fixture 的回傳值
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-brake-"), {"status": "pending"})
        # 每一輪 cmd_run 複製的設定基底（不含佔號欄位：那是行程內的狀態）
        self.base_config = {
            key: value for key, value in self.fixture["config"].items() if key not in ("current_entry", "current_attempt")
        }
        self.base_config.update(
            {
                "base_branch": INTEGRATION_BRANCH,
                "circuit_breaker_n": CIRCUIT_BREAKER_N,
                "checkpoint_max_modules": CHECKPOINT_MAX_MODULES,
                "checkpoint_max_lines": CHECKPOINT_MAX_LINES,
            }
        )
        self.set_runner_state({"state": "idle"})
        # STEP 02: 隔離
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(
            self, "install_shutdown_handlers", "require_config", "lockfile_hash", "preflight", "environment_fingerprint",
            "notify", "maybe_daily_digest", "quota_snapshot", "quota_blocks_start", "write_progress", "render_progress_text",
            "freeze_runner_bundle", "freeze_entry_bundle", "call_claude", "save_session_output", "judge_outcome", "l1_verify",
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
        self.mocks["call_claude"].side_effect = self._fake_cli
        self.mocks["judge_outcome"].side_effect = self._judge
        self.mocks["l1_verify"].return_value = ("verified", "L1 ok")
        # 假 CLI 這一輪的判讀種類
        self.cli_kind = CLI_DONE
        # 假 CLI 被呼叫時額外要做的事（None 表示沒有）
        self.on_cli = None
        # 最近一輪 cmd_run 用過的 config（檢查行程內標記）
        self.last_config = None

    def _preflight(self, config):
        """代替 preflight：只做它對 queue 的那件事——把上一輪被中斷的 entry 放回 pending。

        @param config runner 設定
        @return 0（通過）
        """
        # STEP 01: 與 preflight 的 mutator 同一個函式
        runner.mutate_queue(config, runner.recover_interrupted_entries)
        return 0

    def _fake_cli(self, config, entry, attempt, _resume):
        """代替 call_claude：在目前的分支上真的 commit 一次（模組有產出），必要時執行 on_cli。

        @param config runner 設定
        @param entry 被處理的 entry
        @param attempt 呼叫序號
        @param _resume 是否續接 session（不用）
        @return call_claude 形狀的結果（process_one_entry 用到 duration_s、stream_path）
        """
        # STEP 01: commit
        # 工作 repo 路徑
        work = config["repo_dir"]
        # 這一輪新增的檔名
        name = "%s-%s.js" % (entry["id"], attempt)
        with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
            handle.write("// %s round %s\n" % (entry["id"], attempt))
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "migrate %s round %s" % (entry["id"], attempt))
        # STEP 02: 額外動作
        if self.on_cli is not None:
            self.on_cli(config, entry)
        return {"duration_s": FAKE_DURATION_SECONDS, "stream_path": os.path.join(config["state_dir"], name + ".stream")}

    def _judge(self, _config, _call_result):
        """代替 judge_outcome：回這一輪指定的種類。

        @param _config runner 設定（不用）
        @param _call_result call_claude 的結果（不用）
        @return 判讀結果 dict
        """
        # STEP 01: 組結果
        return {"kind": self.cli_kind, "cost": ROUND_COST, "session_id": SESSION_ID, "detail": "fake %s" % self.cli_kind, "structured": {}}

    def set_runner_state(self, state):
        """把 queue 的 runner_state 整個換成 state（造前置狀態用）。

        @param state 新的 runner_state
        @return None
        """
        # STEP 01: 就地替換（沿用 mutate_queue 的寫入契約）
        runner.mutate_queue(self.base_config, lambda queue: queue.update({"runner_state": dict(state)}))

    def runner_state(self):
        """重讀落盤後的 runner_state。

        @return runner_state dict
        """
        # STEP 01: 讀檔
        return runner.load_queue(self.base_config)["runner_state"]

    def last_pause_notice(self):
        """最後一則暫停類通知的 (標題, 內文)。

        @return (title, body)
        @raises AssertionError 沒有任何暫停通知
        """
        # STEP 01: 由新到舊找第一則
        for call in reversed(self.mocks["notify"].call_args_list):
            if call.args[1] in PAUSE_EVENTS:
                return call.args[2], call.args[3]
        raise AssertionError("沒有任何暫停通知")

    def _inject_push(self, stack):
        """推送失敗：遠端拒收整合分支（真的 pre-receive hook），這一輪結束時移除。

        @param stack 這一輪的 ExitStack（登記還原）
        @return None
        """
        # STEP 01: 裝 hook、登記移除
        reject_entry_branch_push(self.fixture["remote"], branch=INTEGRATION_BRANCH)
        stack.callback(os.unlink, os.path.join(self.fixture["remote"], "hooks", "pre-receive"))

    def _inject_switch(self, stack):
        """發佈段切換整合分支失敗（只攔發佈段那一次 checkout；前置作業的 checkout 照常）。

        @param stack 這一輪的 ExitStack（登記還原）
        @return None
        """
        # STEP 01: 換掉 merge_to_integration
        stack.enter_context(
            mock.patch.object(
                runner, "merge_to_integration",
                scoped_merge_failure(("checkout", INTEGRATION_BRANCH), (GIT_FATAL_EXIT_CODE, "", "switch boom")),
            )
        )

    def _inject_ff_env(self, stack):
        """發佈段 ff-merge 失敗但可以快轉（環境類）：只攔 `merge --ff-only`，祖先檢查用真的（回 0）。

        @param stack 這一輪的 ExitStack（登記還原）
        @return None
        """
        # STEP 01: 換掉 merge_to_integration
        stack.enter_context(
            mock.patch.object(
                runner, "merge_to_integration", scoped_merge_failure(("merge", "--ff-only"), (GIT_FATAL_EXIT_CODE, "", "index.lock boom"))
            )
        )

    def _inject_cli_kind(self, stack, kind):
        """這一輪 CLI 判成 kind，結束時改回 done。

        @param stack 這一輪的 ExitStack（登記還原）
        @param kind 判讀種類
        @return None
        """
        # STEP 01: 設定並登記還原
        self.cli_kind = kind
        stack.callback(setattr, self, "cli_kind", CLI_DONE)

    def _inject_dirty(self, stack):
        """真的髒工作樹：改一個已追蹤檔，前置作業判 integration_dirty（CLI 之前）；結束時還原。

        @param stack 這一輪的 ExitStack（登記還原）
        @return None
        """
        # STEP 01: 改檔、登記還原
        # 工作 repo 路徑
        work = self.base_config["repo_dir"]
        with open(os.path.join(work, R15_RELATIVE_PATH), "a", encoding="utf-8") as handle:
            handle.write("// uncommitted\n")
        stack.callback(run_git, work, "checkout", "--", R15_RELATIVE_PATH)

    def _inject_crash(self, stack):
        """CLI 之後、發佈段取收尾資料時拋出未預期例外（走 crash 流程）。

        @param stack 這一輪的 ExitStack（登記還原）
        @return None
        """
        # STEP 01: 換掉 collect_closing_data
        stack.enter_context(mock.patch.object(runner, "collect_closing_data", side_effect=RuntimeError("closing boom")))

    def run_round(self, kind, max_modules=1):
        """跑一輪（一次 launchd 重啟）：注入 kind 的故障後呼叫真的 cmd_run。

        @param kind push／switch／ff_env／auth／error／dirty／crash／done
        @param max_modules cmd_run 最多處理的模組數
        @return cmd_run 的退出碼
        """
        # STEP 01: 種類 → 注入方式
        # 每一種故障的注入函式（done 不注入）
        injectors = {
            "push": self._inject_push,
            "switch": self._inject_switch,
            "ff_env": self._inject_ff_env,
            "auth": lambda stack: self._inject_cli_kind(stack, "auth_expired"),
            "error": lambda stack: self._inject_cli_kind(stack, "error"),
            "dirty": self._inject_dirty,
            "crash": self._inject_crash,
            "done": lambda stack: None,
        }
        # STEP 02: 新行程的 config、注入、執行（輸出不是受測對象）
        # 這一輪的 config（新行程）
        config = dict(self.base_config)
        with contextlib.ExitStack() as stack:
            injectors[kind](stack)
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            # cmd_run 的退出碼
            code = runner.cmd_run(config, argparse.Namespace(max_modules=max_modules))
        self.last_config = config
        return code

    def run_rounds(self, kinds):
        """依序跑多輪；每一輪都必須以暫停結束（前置條件自驗）。

        @param kinds 故障種類清單
        @return None
        """
        # STEP 01: 逐輪；不是 crash 那一種卻以 crash 暫停，代表測試假件自己壞了（暫停照樣發生，不擋的話會被當成受測行為）
        for kind in kinds:
            self.assertEqual(self.run_round(kind), runner.EXIT_PAUSED, "%s 這一輪沒有暫停: %s" % (kind, self.runner_state()))
            if kind != "crash":
                self.assertNotEqual(self.runner_state().get("reason"), runner.CRASH_REASON, events(self.base_config, runner.CRASH_REASON))

    def assert_count_hold(self, count, hold):
        """落盤的計數與 hold 是預期值。

        @param count 預期的 post_cli_pause_count
        @param hold 預期的 hold
        @return None
        """
        # STEP 01: 一次比兩個欄位
        # 落盤後的 runner_state
        state = self.runner_state()
        self.assertEqual((state.get(COUNT_FIELD), bool(state.get("hold"))), (count, hold), state)


class CrossSignatureBrakeTest(BrakeHarness):
    """T3.1／T3.2／T3.12：不同簽名的 CLI 後暫停輪流出現，累計到門檻就鎖定。"""

    def test_push_switch_push_locks_on_third(self):
        """T3.1：推送失敗 → 切換整合分支失敗 → 推送失敗，第 3 輪鎖定、通知寫明次數與解除指令；鎖定後再重啟不累加。

        修正前：三輪的 (原因, 簽名) 兩兩不同，同簽名煞車永遠不觸發，每次重啟都重燒一次 CLI。

        @return None
        """
        # STEP 01: 兩輪之後還沒鎖
        self.run_rounds(["push", "switch"])
        self.assert_count_hold(BELOW_THRESHOLD, False)
        # STEP 02: 第 3 輪鎖定
        self.run_rounds(["push"])
        self.assert_count_hold(USER_THRESHOLD, True)
        # 最後一則暫停通知
        title, body = self.last_pause_notice()
        self.assertIn("%s %d 次" % (COUNT_CAUSE_TEXT, USER_THRESHOLD), body)
        self.assertIn(UNBLOCK_TEXT, body)
        # 最後一筆 paused 事件的細節
        detail = events(self.base_config, "paused")[-1]["detail"]
        self.assertEqual((detail.get("cli_spent"), detail.get(COUNT_FIELD)), (True, USER_THRESHOLD), detail)
        self.assertIn("integration_diverged", title)
        # STEP 03: 鎖定中再重啟：pre-flight 之前就退出，CLI 不呼叫、計數不動
        # 鎖定前 CLI 被呼叫的次數
        cli_calls = self.mocks["call_claude"].call_count
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        self.assertEqual(self.mocks["call_claude"].call_count, cli_calls)
        self.assert_count_hold(USER_THRESHOLD, True)

    def test_push_ffenv_push_locks_on_third(self):
        """T3.2：推送失敗 → ff-merge 環境類失敗 → 推送失敗，第 3 輪鎖定。

        @return None
        """
        # STEP 01: 三輪
        self.run_rounds(["push", "ff_env", "push"])
        # STEP 02: 鎖定，最後一輪是推送失敗
        self.assert_count_hold(USER_THRESHOLD, True)
        self.assertEqual(self.runner_state().get("crash_signature"), runner.PUSH_FAILED_SIGNATURE)

    def test_auth_push_auth_interleaved_counts(self):
        """T3.12：CLI 判 auth_expired 與推送失敗交錯，照樣累計到門檻鎖定。

        @return None
        """
        # STEP 01: 三輪
        self.run_rounds(["auth", "push", "auth"])
        # STEP 02: 鎖定，暫停原因是最後那次 auth_expired
        self.assert_count_hold(USER_THRESHOLD, True)
        self.assertEqual(self.runner_state().get("reason"), "auth_expired")


class CountScopeTest(BrakeHarness):
    """T3.3／T3.7／T3.8：哪些暫停算「CLI 之後」。"""

    def test_pre_cli_pauses_are_not_counted(self):
        """T3.3：推送失敗(1) → 三次真的髒工作樹（git 前置暫停，CLI 之前）→ ff 環境類失敗(2)：不鎖定、計數 2。

        @return None
        """
        # STEP 01: 五輪
        self.run_rounds(["push", "dirty", "dirty", "dirty"])
        self.assertEqual(self.runner_state().get("reason"), "integration_dirty")
        self.run_rounds(["ff_env"])
        # STEP 02: 只有兩次 CLI 後暫停
        self.assert_count_hold(BELOW_THRESHOLD, False)
        self.assertEqual(self.mocks["call_claude"].call_count, BELOW_THRESHOLD)

    def test_mark_is_scoped_to_its_entry(self):
        """T3.7：同一個行程裡 e1 的 CLI 回報錯誤（不暫停）→ e2 準備分支時在 CLI 之前暫停：計數不動，行程內標記已清。

        @return None
        """
        # STEP 01: e1 再錯一次就轉 failed（主迴圈才會改挑 e2）；e2 有自己的舊分支、整合分支前進過（準備分支要真的合併）
        runner.mutate_queue(
            self.base_config, lambda queue: runner.find_entry(queue, ENTRY_ID).update({"attempts": LAST_ATTEMPT_BEFORE_FAIL})
        )
        # 工作 repo 路徑
        work = self.base_config["repo_dir"]
        run_git(work, "checkout", "-b", SECOND_ENTRY_BRANCH, self.fixture["base_sha"])
        with open(os.path.join(work, "e2.js"), "w", encoding="utf-8") as handle:
            handle.write("// e2 earlier round\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "migrate e2 earlier round")
        advance_integration(self.fixture, "other.js", "// e0 migrated\n", "migrate e0")
        add_entry(self.fixture, SECOND_ENTRY_ID, SECOND_ENTRY_BRANCH, status="pending")
        self.set_runner_state({"state": "idle", COUNT_FIELD: PRESET_COUNT})
        # STEP 02: e1 的 CLI 跑完才裝「合併一律失敗」的 hook（e1 自己的準備分支要先過）
        self.on_cli = lambda config, entry: install_failing_pre_merge_hook(config["repo_dir"])
        self.cli_kind = "error"
        self.assertEqual(self.run_round("done", max_modules=TWO_MODULES), runner.EXIT_PAUSED)
        # STEP 03: e2 在 CLI 之前暫停；計數維持預設值，行程內標記已清
        self.assertEqual(self.mocks["call_claude"].call_count, 1)
        self.assertEqual(self.runner_state().get("reason"), "integration_dirty")
        self.assert_count_hold(PRESET_COUNT, False)
        self.assertNotIn("cli_spent", self.last_config)

    def test_mark_key_requires_same_entry_and_attempt(self):
        """T3.7 補充：標記要 (entry, 呼叫序號) 都相同才算——同 entry 第二輪 CLI 前暫停、另一個 entry 的暫停都不計；相同才計（對照組）。

        @return None
        """
        # 三種情境：名稱、目前的 (entry, 序號)、殘留的標記、預期計數
        cases = (
            ("same_entry_next_attempt", (ENTRY_ID, SECOND_ATTEMPT), (ENTRY_ID, FIRST_ATTEMPT), PRESET_COUNT),
            ("other_entry", (ENTRY_ID, FIRST_ATTEMPT), (SECOND_ENTRY_ID, FIRST_ATTEMPT), PRESET_COUNT),
            ("match_control", (ENTRY_ID, SECOND_ATTEMPT), (ENTRY_ID, SECOND_ATTEMPT), PRESET_COUNT + 1),
        )
        for label, current, mark, expected in cases:
            with self.subTest(label):
                # STEP 01: 預設計數、組 config 後直接暫停
                self.set_runner_state({"state": "idle", COUNT_FIELD: PRESET_COUNT})
                # 這個情境的 config
                config = dict(self.base_config, current_entry=current[0], current_attempt=current[1], cli_spent=mark)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.enter_paused(config, "integration_dirty", label), runner.EXIT_PAUSED)
                # STEP 02: 計數
                self.assertEqual(self.runner_state().get(COUNT_FIELD), expected)

    def test_crash_after_cli_counts(self):
        """T3.8：CLI 之後的 crash 也算：crash → 推送失敗 → 切換失敗，第 3 輪鎖定。

        @return None
        """
        # STEP 01: crash 那一輪
        self.run_rounds(["crash"])
        self.assertEqual(self.runner_state().get("reason"), runner.CRASH_REASON)
        self.assert_count_hold(1, False)
        # STEP 02: 再兩輪
        self.run_rounds(["push", "switch"])
        self.assert_count_hold(USER_THRESHOLD, True)


class CountResetTest(BrakeHarness):
    """T3.4／T3.5／T3.6：有模組完成、重啟對帳補 done、unblock --runner 都歸零。"""

    def test_done_resets_count(self):
        """T3.4：兩次 CLI 後暫停 → e1 真的完成（歸零）→ e2 一次 CLI 後暫停：計數 1、不鎖定。

        @return None
        """
        # STEP 01: e2 排在 e1 之後
        add_entry(self.fixture, SECOND_ENTRY_ID, SECOND_ENTRY_BRANCH, status="pending")
        self.run_rounds(["push", "switch"])
        self.assert_count_hold(BELOW_THRESHOLD, False)
        # STEP 02: e1 完成
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assertEqual(runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)["status"], "done")
        self.assert_count_hold(0, False)
        # STEP 03: e2 推送失敗
        self.run_rounds(["push"])
        self.assert_count_hold(1, False)

    def test_reconcile_done_resets_count(self):
        """T3.5：推送之後、done 寫回之前被殺 → 重啟對帳補 done：計數歸零（與 done 同一次寫入），CLI 不呼叫。

        @return None
        """
        # STEP 01: 預設計數，發佈段在 done 之前被殺（publish 要求 entry 為 running）
        self.set_runner_state({"state": "running", COUNT_FIELD: RECONCILE_PRESET_COUNT})
        runner.mutate_queue(self.base_config, lambda queue: runner.find_entry(queue, ENTRY_ID).update({"status": "running"}))
        with contextlib.redirect_stdout(io.StringIO()):
            publish(self.fixture, kill_before_done=True)
        # STEP 02: 重啟
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        # STEP 03: 對帳補了 done、計數歸零
        self.assertEqual(runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)["status"], "done")
        self.assertEqual(self.mocks["call_claude"].call_count, 0)
        self.assert_count_hold(0, False)

    def test_unblock_runner_resets_count(self):
        """T3.6：計數鎖定之後 unblock --runner：hold、計數一起清，回 idle；下一輪照常處理。

        @return None
        """
        # STEP 01: 鎖定
        self.run_rounds(["push", "switch", "push"])
        self.assert_count_hold(USER_THRESHOLD, True)
        # STEP 02: 解除
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.unblock_runner(dict(self.base_config)), runner.EXIT_OK)
        self.assert_count_hold(0, False)
        self.assertEqual(self.runner_state().get("state"), "idle")
        # STEP 03: 下一輪處理 e1 並完成
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assertEqual(runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)["status"], "done")


class CountEdgeTest(BrakeHarness):
    """T3.9／T3.10／T3.11：欄位格式錯、與同簽名煞車的先後、通知截斷。"""

    def test_malformed_count_locks_immediately(self):
        """T3.9：計數欄位格式錯（字串、布林、負數、null）→ 下一次 CLI 後暫停直接鎖定，通知寫明格式錯。

        @return None
        """
        # 每一種格式錯樣本
        for value in MALFORMED_COUNTS:
            with self.subTest(value=value):
                # STEP 01: 放進格式錯的值（清掉上一個樣本留下的 hold）
                self.set_runner_state({"state": "idle", COUNT_FIELD: value})
                self.run_rounds(["push"])
                # STEP 02: 鎖定、計數以門檻寫回、通知說明原因
                self.assert_count_hold(USER_THRESHOLD, True)
                self.assertIn(MALFORMED_TEXT, self.last_pause_notice()[1])

    def test_missing_count_is_zero(self):
        """T3.9 對照：沒有計數欄位＝0，第一次 CLI 後暫停寫 1、不鎖定。

        @return None
        """
        # STEP 01: setUp 的 runner_state 沒有這個欄位
        self.assertNotIn(COUNT_FIELD, self.runner_state())
        self.run_rounds(["push"])
        # STEP 02: 1、不鎖定
        self.assert_count_hold(1, False)

    def test_same_signature_locks_first(self):
        """T3.10：推送失敗連兩次——第 2 次由同簽名煞車先鎖（計數 2），通知文字是同簽名的那一種。

        @return None
        """
        # STEP 01: 兩輪
        self.run_rounds(["push", "push"])
        # STEP 02: 鎖定、計數 2、文字
        self.assert_count_hold(SAME_SIGNATURE_ROUNDS, True)
        # 最後一則暫停通知的內文
        body = self.last_pause_notice()[1]
        self.assertIn(SAME_SIGNATURE_TEXT, body)
        self.assertNotIn(COUNT_CAUSE_TEXT, body)

    def test_count_lock_notice_survives_truncation(self):
        """T3.11：計數鎖定的通知照 notify.sh 截到 300 字（emoji＋標題＋內文），次數與 unblock --runner 仍在。

        @return None
        """
        # STEP 01: auth → 切換失敗 → 冗長 stderr 的推送失敗
        self.run_rounds(["auth", "switch"])
        # 冗長拒絕 hook 的路徑（這一輪結束後移除）
        hook_path = install_verbose_reject_hook(self.fixture["remote"])
        self.addCleanup(os.unlink, hook_path)
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        self.assert_count_hold(USER_THRESHOLD, True)
        # STEP 02: 前置條件：全文確實超過上限（否則截斷沒被測到）
        # 最後一則暫停通知的標題與內文
        title, body = self.last_pause_notice()
        # 照 notify.sh 組起來的全文
        full = "⏸ %s\n%s" % (title, body)
        self.assertGreater(len(full), NOTIFY_MAX_TEXT_CHARS, full)
        # STEP 03: 截斷後
        # notify.sh 截斷後實際送出的文字
        text = full[:NOTIFY_MAX_TEXT_CHARS]
        self.assertIn("%s %d 次" % (COUNT_CAUSE_TEXT, USER_THRESHOLD), text, text)
        self.assertIn(UNBLOCK_TEXT, text, text)


if __name__ == "__main__":
    unittest.main()
