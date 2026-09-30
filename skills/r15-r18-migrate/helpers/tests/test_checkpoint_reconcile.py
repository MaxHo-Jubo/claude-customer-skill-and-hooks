"""runner.py 1.1.2 第五批階段三的回歸測試：斷點的重啟對帳（已知缺口 c）。

涵蓋 checkpoint 的 `opening` write-ahead（任何 side effect 之前就落盤 branch 與 auto 斷點的 id）、開斷點先查既有 PR 沿用、
hard 斷點 push／gh 失敗時保持 opening 並以專屬簽名暫停（第二次 hold、閘門不消失、release 可放行）、soft／auto 失敗沿用 failed、
(c1) gh 退出 0 沒有連結時的 `pr_unverified` 與之後的補查、重新匯入保留兩個新欄位、停止訊號延後區間與短逾時。

情境盡量做成「中斷 → cmd_run 重啟」：沿用 test_reconcile 的 RestartHarness（真 bare 遠端＋工作 repo；CLI、額度、通知、等人放行隔離），
gh 換成 fake_gh.write_scripted_gh（真的依 --head／--base／--state 過濾、create 遇到已存在的 open PR 以非零退出）；
SimulatedKill（BaseException）模擬 SIGKILL，任何 except 都接不住、延後區間也擋不住。

新增的暫停原因寫成字面值（"checkpoint_open_failed"），同時釘住操作者在通知與 runner.log.jsonl 看到的字串；
不用 getattr 取新常數——修正前它不存在，直接取會以 AttributeError 失敗、不是以 AssertionError 證明「還沒修」。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 300; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import argparse
import contextlib
import io
import json
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runner  # noqa: E402  pylint: disable=wrong-import-position
from fake_gh import (  # noqa: E402  pylint: disable=wrong-import-position
    FAKE_PR_URL_PREFIX,
    FIRST_PR_NUMBER,
    gh_commands,
    gh_prs,
    set_gh_modes,
    write_scripted_gh,
)
from test_reconcile import (  # noqa: E402  pylint: disable=wrong-import-position
    HARD_CHECKPOINT_ID,
    SECOND_ENTRY_BRANCH,
    SECOND_ENTRY_ID,
    RestartHarness,
    SimulatedKill,
    add_entry,
    add_hard_checkpoint,
    events,
)
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    ENTRY_ID,
    INTEGRATION_BRANCH,
    R15_RELATIVE_PATH,
    reject_entry_branch_push,
    remote_tip,
)

# 宣告的斷點 w0 凍結出來的分支
CP_BRANCH = "r18-migration/cp-%s" % HARD_CHECKPOINT_ID
# 假 gh 第一次 create 出來的 PR 連結
FIRST_CREATED_PR_URL = "%s%d" % (FAKE_PR_URL_PREFIX, FIRST_PR_NUMBER)
# GitHub 上已經存在、runner 不知道的斷點 PR（(c1) 之後補查應找到它）
EXISTING_CP_PR_URL = "https://example.invalid/pull/55"
# hard 斷點開啟失敗的暫停原因（計畫定的外部字串）
OPEN_FAILED_REASON = "checkpoint_open_failed"
# 斷點延後區間內 push 與 gh 的逾時上限（秒）：計畫定的外部契約，不讀實作的常數
EXPECTED_CP_PUSH_TIMEOUT_SECONDS = 45
EXPECTED_CP_GH_TIMEOUT_SECONDS = 30
# 已知答案的 auto 斷點 id（直接寫進 queue 的 opening 記錄用；形狀同 handle_checkpoints 產生的）
SEEDED_AUTO_ID = "auto-20260101-0000"
# 匯入時的 render_progress_text（RestartHarness 會把模組上的換成 mock；進度檔的測試要用真的）
REAL_RENDER_PROGRESS_TEXT = runner.render_progress_text


def cp_pr(url, branch=CP_BRANCH):
    """假 gh 狀態檔裡的一筆斷點 PR（base 是測試用的整合分支，同 add_hard_checkpoint 的 pr_base）。

    @param url PR 連結
    @param branch head 分支
    @return dict
    """
    # STEP 01: 組欄位
    return {"url": url, "head": branch, "base": INTEGRATION_BRANCH, "state": "open"}


def checkpoint(config, checkpoint_id=HARD_CHECKPOINT_ID):
    """重讀 queue 取某個斷點（驗落盤後的狀態）。

    @param config runner 設定
    @param checkpoint_id 斷點 id
    @return 斷點 dict；不存在是 None
    """
    # STEP 01: 每次重讀
    return runner.find_checkpoint(runner.load_queue(config), checkpoint_id)


def kill_after_gh(subcommand):
    """讓 run_command 在指定 gh 子命令**真的跑完之後**以 SimulatedKill 中斷（模擬 SIGKILL 落在 gh 返回、落盤之前）。

    @param subcommand 例如 "pr create"
    @return mock.patch 物件（with 用）
    """
    # STEP 01: 轉發後比對子命令
    real_run = runner.run_command

    def wrapper(args, cwd=None, timeout=runner.GIT_TIMEOUT_SECONDS, env=None, log_path=None):
        """轉發；命中就中斷。"""
        # STEP 01: 轉發、比對
        result = real_run(args, cwd=cwd, timeout=timeout, env=env, log_path=log_path)
        if list(args[1:3]) == subcommand.split():
            raise SimulatedKill()
        return result

    return mock.patch.object(runner, "run_command", wrapper)


def remote_cp_branches(fixture):
    """bare 遠端上所有斷點分支的名稱。

    @param fixture build_fixture 的回傳值
    @return 分支名清單（排序）
    """
    # STEP 01: 直接問 bare repo
    result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/r18-migration/"],
        cwd=fixture["remote"],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(line for line in result.stdout.splitlines() if line.strip())


class CheckpointHarness(RestartHarness):
    """e1 已 done（wave 0 完成）、e2 是 wave 1 的 pending、wave 0 之後有一個 hard 斷點；gh 換成可設定情境的假 gh。"""

    def setUp(self):
        """共用隔離＋拓撲。

        @return None
        """
        # STEP 01: RestartHarness 的隔離；e1 done、e2 pending、hard 斷點
        super().setUp()
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, ENTRY_ID).update({"status": "done"}))
        add_entry(self.fixture, SECOND_ENTRY_ID, SECOND_ENTRY_BRANCH, status="pending", wave=1)
        add_hard_checkpoint(self.fixture)
        # STEP 02: 可設定情境的假 gh（預設：沒有任何 PR、list 與 create 都正常）
        # 假 gh 的路徑組
        self.gh = self.use_gh()
        self.addCleanup(self._reset_signal_state)

    @staticmethod
    def _reset_signal_state():
        """測試失敗時延後區間的模組層狀態可能沒歸零，歸零免得汙染後面的測試。

        @return None
        """
        # STEP 01: 歸零
        runner._SIGNAL_DEFER_DEPTH = 0
        runner._PENDING_SIGNUM = None

    def use_gh(self, prs=None, **modes):
        """把 gh 換成 write_scripted_gh（放在 fixture 根目錄）。

        @param prs 一開始就存在的 PR
        @param modes list_mode／create_mode
        @return write_scripted_gh 的回傳值
        """
        # STEP 01: 換 gh
        # 假 gh 的路徑組
        gh = write_scripted_gh(os.path.dirname(self.fixture["remote"]), prs=prs, remote=self.fixture["remote"], **modes)
        self.config["gh_bin"] = gh["bin"]
        return gh

    def set_checkpoint(self, **fields):
        """改 w0 的欄位（例如 mode）。

        @param fields 要覆寫的欄位
        @return None
        """
        # STEP 01: 就地更新
        runner.mutate_queue(self.config, lambda queue: runner.find_checkpoint(queue, HARD_CHECKPOINT_ID).update(fields))

    def runner_state(self):
        """落盤的 runner_state。

        @return dict
        """
        # STEP 01: 重讀
        return runner.load_queue(self.config)["runner_state"]


class HardCheckpointCrashTest(CheckpointHarness):
    """必測 10（c2）：hard 斷點 gh create 之後、落盤之前被殺 → 重啟沿用 PR、進入等待，不先處理下一個模組。"""

    def test_crash_after_create_reuses_pr_and_waits(self):
        """create 只被呼叫一次；重啟後斷點 opened＋第一次建的 PR；等待的是 w0；e2 沒被處理。

        修正前：斷點停在 pending，重啟時重開 → create 因 PR 已存在而失敗 → failed、閘門消失 → 直接處理 e2。

        @return None
        """
        # STEP 01: 第一次啟動：啟動時的斷點檢查開 w0，create 返回後被殺
        with kill_after_gh("pr create"):
            with self.assertRaises(SimulatedKill):
                self.restart()
        self.assertEqual(checkpoint(self.config)["status"], "opening", "write-ahead：被殺之前斷點應已是 opening")
        # STEP 02: 重啟
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # STEP 03: 沿用那一支 PR、只 create 過一次、閘門守住
        cp = checkpoint(self.config)
        self.assertEqual(cp["status"], "opened")
        self.assertEqual(cp["pr_url"], FIRST_CREATED_PR_URL)
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        self.mocks["wait_for_release"].assert_called_once_with(self.config, HARD_CHECKPOINT_ID)
        self.mocks["process_one_entry"].assert_not_called()
        self.assertEqual(self.runner_state().get("reason"), "paused_for_review")


class AutoCheckpointCrashTest(CheckpointHarness):
    """必測 11（c2）：auto 斷點在 opening 時被殺 → 重啟後沿用同一個 id、同一支分支，沒有孤兒分支或 PR。"""

    def setUp(self):
        """拿掉宣告的斷點、e2 拿掉（佇列只剩 done 的 e1），模組數門檻降到 1。

        @return None
        """
        # STEP 01: 拓撲
        super().setUp()
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": [], "modules": queue["modules"][:1]}))
        self.config["checkpoint_max_modules"] = 1

    def assert_single_auto_opened(self, auto_id):
        """queue 只有這一個 auto 斷點、已 opened＋蓋章；遠端只有它的分支；GitHub 上只有一支斷點 PR。

        @param auto_id 預期的 auto 斷點 id
        @return None
        """
        # STEP 01: queue
        queue = runner.load_queue(self.config)
        self.assertEqual([cp["id"] for cp in queue["checkpoints"]], [auto_id])
        cp = queue["checkpoints"][0]
        self.assertEqual(cp["status"], "opened")
        self.assertEqual(cp["branch"], "r18-migration/cp-%s" % auto_id)
        self.assertEqual(cp["pr_url"], FIRST_CREATED_PR_URL)
        self.assertEqual(runner.find_entry(queue, ENTRY_ID)["checkpoint_id"], auto_id)
        # STEP 02: 外部：沒有孤兒
        self.assertEqual(remote_cp_branches(self.fixture), [cp["branch"]])
        self.assertEqual([pr["head"] for pr in gh_prs(self.gh)], [cp["branch"]])
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)

    def test_crash_after_create_reuses_same_id(self):
        """模組完成後的斷點檢查觸發 auto，create 返回後被殺 → 重啟補完同一個 id。

        修正前：auto 斷點開成功之前不在 queue 裡，被殺就什麼都沒留下，分支與 PR 成了孤兒、id 也無從得知。

        @return None
        """
        # STEP 01: 主迴圈的斷點檢查（模組剛完成）→ 被殺
        with kill_after_gh("pr create"):
            with self.assertRaises(SimulatedKill):
                runner.handle_checkpoints(self.config)
        # 被殺之前落盤的 auto 斷點
        seeded = runner.load_queue(self.config).get("checkpoints") or []
        self.assertEqual([cp.get("status") for cp in seeded], ["opening"], "write-ahead：auto 斷點的 id 應已落盤")
        # STEP 02: 重啟 → 同一個 id 補完
        self.assertEqual(self.restart(), runner.EXIT_OK)
        self.assert_single_auto_opened(seeded[0]["id"])

    def test_startup_completes_existing_opening_auto_only(self):
        """啟動時只補完既有的 opening auto（用已知 id 直接放進 queue），不觸發新的 auto。

        @return None
        """
        # STEP 01: queue 裡放一筆 opening 的 auto 斷點（還沒推分支）→ 重啟
        self.seed_opening_auto()
        self.restart()
        # STEP 02: 只有這一個、已補完
        self.assert_single_auto_opened(SEEDED_AUTO_ID)

    def test_module_check_reuses_opening_auto(self):
        """模組完成後的斷點檢查：已有 opening 的 auto 斷點就沿用它的 id 補完，不另開新 id（門檻同時成立也一樣）。

        @return None
        """
        # STEP 01: 放一筆 opening 的 auto 斷點（e1 done、沒蓋章，門檻 1 成立）→ 模組完成後的檢查
        self.seed_opening_auto()
        self.assertEqual(runner.handle_checkpoints(self.config), (False, None))
        # STEP 02: 只有這一個、已補完
        self.assert_single_auto_opened(SEEDED_AUTO_ID)

    def seed_opening_auto(self):
        """queue 裡放一筆 opening 的 auto 斷點（還沒推分支），id 是 SEEDED_AUTO_ID。

        @return None
        """
        # STEP 01: 形狀同 begin 寫下的記錄
        # opening 的 auto 記錄
        record = dict(
            runner.CHECKPOINT_FIELD_DEFAULTS,
            id=SEEDED_AUTO_ID,
            after={"wave": None},
            mode="soft",
            pr_base=INTEGRATION_BRANCH,
            title="auto",
            status="opening",
            branch="r18-migration/cp-%s" % SEEDED_AUTO_ID,
        )
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": [record]}))


class HardCheckpointFailureTest(CheckpointHarness):
    """必測 12：hard 斷點的 push 或 gh 持續失敗 → 暫停、第二次 hold、不標 failed、閘門不被繞過；release 可以放行 opening。"""

    def run_failure_cycle(self, creates_per_run=None):
        """跑兩次重啟（都失敗）→ release → unblock --runner → 再重啟；逐步斷言。

        @param creates_per_run 每次重啟預期的 `gh pr create` 次數；None 表示不看（推送失敗時根本走不到 create）。
            一次重啟只該嘗試開一次：開失敗之後沒暫停、讓主迴圈取件前的閘門再開一次，外部看起來一樣是暫停，只有次數分得出來
        @return None
        """
        # STEP 01: 第一次：暫停、沒鎖、不標 failed、e2 沒被處理
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        if creates_per_run is not None:
            self.assertEqual(gh_commands(self.gh).count("pr create"), creates_per_run)
        self.assertEqual(checkpoint(self.config)["status"], "opening")
        state = self.runner_state()
        self.assertEqual(state.get("reason"), OPEN_FAILED_REASON, state)
        self.assertFalse(state.get("hold"), state)
        self.mocks["process_one_entry"].assert_not_called()
        self.mocks["wait_for_release"].assert_not_called()
        # STEP 02: 第二次：同原因同簽名 → hold，閘門仍在
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assertTrue(self.runner_state().get("hold"), self.runner_state())
        self.assertEqual(checkpoint(self.config)["status"], "opening")
        self.mocks["process_one_entry"].assert_not_called()
        # STEP 03: 人工放行 opening → 解除鎖定 → 重啟會處理 e2
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.cmd_release(self.config, argparse.Namespace(checkpoint_id=HARD_CHECKPOINT_ID)), runner.EXIT_OK)
            runner.unblock_runner(self.config)
        self.assertEqual(checkpoint(self.config)["status"], "released")
        self.restart()
        self.mocks["process_one_entry"].assert_called_once()

    def test_push_keeps_failing(self):
        """cp 分支推送一直被拒。

        @return None
        """
        # STEP 01: 遠端拒絕 cp 分支
        reject_entry_branch_push(self.fixture["remote"], branch=CP_BRANCH)
        self.run_failure_cycle()

    def test_create_keeps_failing(self):
        """gh pr create 一直失敗（再查也沒有）。

        @return None
        """
        # STEP 01: create 失敗；每次重啟只 create 一次
        set_gh_modes(self.gh, create_mode="fail")
        self.run_failure_cycle(creates_per_run=1)


class LookupAndRecheckTest(CheckpointHarness):
    """開斷點 PR 的查詢順序：查詢失敗不冒險 create；create 回報失敗但其實建了 → 再查沿用。"""

    def test_lookup_failure_does_not_create(self):
        """hard 斷點、pr list 失敗：不 create、以 checkpoint_open_failed 暫停、斷點仍是 opening。

        @return None
        """
        # STEP 01: list 失敗 → 重啟
        set_gh_modes(self.gh, list_mode="fail")
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # STEP 02: 沒 create、暫停、閘門在
        self.assertNotIn("pr create", gh_commands(self.gh))
        self.assertEqual(self.runner_state().get("reason"), OPEN_FAILED_REASON)
        self.assertEqual(checkpoint(self.config)["status"], "opening")

    def test_create_reported_failure_but_created_is_reused(self):
        """create 建了卻以非零退出（例如逾時）→ 再查找到 → opened＋那支 PR，hard 閘門照常等待。

        @return None
        """
        # STEP 01: create 建了但回報失敗
        set_gh_modes(self.gh, create_mode="fail_after_create")
        self.assertEqual(runner.handle_checkpoints(self.config, include_auto=False), (True, HARD_CHECKPOINT_ID))
        # STEP 02: 沿用
        cp = checkpoint(self.config)
        self.assertEqual((cp["status"], cp["pr_url"]), ("opened", FIRST_CREATED_PR_URL))
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)


class SoftAndAutoFailureTest(CheckpointHarness):
    """soft／auto 斷點開失敗：沿用既有的 failed 行為，不暫停、不擋下一個模組。"""

    def test_soft_failure_marks_failed(self):
        """soft 斷點 create 失敗 → failed、runner 不因斷點暫停、e2 照常處理。

        @return None
        """
        # STEP 01: soft、create 失敗 → 重啟
        self.set_checkpoint(mode="soft")
        set_gh_modes(self.gh, create_mode="fail")
        self.restart()
        # STEP 02: failed、沒有 checkpoint_open_failed 暫停、e2 有被處理
        self.assertEqual(checkpoint(self.config)["status"], "failed")
        self.assertNotEqual(self.runner_state().get("reason"), OPEN_FAILED_REASON)
        self.mocks["process_one_entry"].assert_called_once()

    def test_auto_failure_marks_failed(self):
        """auto 斷點 create 失敗 → 記錄停在 failed（不留 opening、不暫停）。

        @return None
        """
        # STEP 01: 沒有宣告的斷點、門檻 1、create 失敗 → 模組完成後的檢查
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": []}))
        self.config["checkpoint_max_modules"] = 1
        set_gh_modes(self.gh, create_mode="fail")
        self.assertEqual(runner.handle_checkpoints(self.config), (False, None))
        # STEP 02: 一筆 failed
        self.assertEqual([cp.get("status") for cp in runner.load_queue(self.config)["checkpoints"]], ["failed"])


class UnverifiedLinkTest(CheckpointHarness):
    """必測 13（c1）：gh 退出 0 沒有連結 → 仍是 opened＋pr_unverified；之後補查補上連結；查詢失敗不改狀態。"""

    def test_empty_link_then_filled_on_restart(self):
        """soft 斷點：gh 印的不是連結 → opened＋pr_unverified、通知寫「連結未知」；重啟時 gh 失敗 → 不動；gh 正常 → 補上、清旗標。

        @return None
        """
        # STEP 01: gh 退出 0 但沒印連結（也沒真的建）；create 前的查詢正常（沒有 PR）、create 後的再查失敗——無法確認才是 (c1)
        # （再查確定沒有是開啟失敗，05aeecf review）
        self.set_checkpoint(mode="soft")
        set_gh_modes(self.gh, list_mode="ok_then_fail", list_ok_left=1, create_mode="nolink")
        self.assertEqual(runner.handle_checkpoints(self.config, include_auto=False), (False, HARD_CHECKPOINT_ID))
        cp = checkpoint(self.config)
        self.assertEqual(cp["status"], "opened")
        self.assertTrue(cp.get("pr_unverified"), cp)
        self.assertFalse(cp.get("pr_url"))
        # 斷點開啟通知的內文
        bodies = [call.args[3] for call in self.mocks["notify"].call_args_list if call.args[1] == "checkpoint_opened"]
        self.assertTrue(bodies and "連結未知" in bodies[-1], bodies)
        # STEP 02: 重啟、查詢失敗 → 狀態不變、有事件、runner 照跑
        gh = self.use_gh(prs=[cp_pr(EXISTING_CP_PR_URL)], list_mode="fail")
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        cp = checkpoint(self.config)
        self.assertTrue(cp.get("pr_unverified"), cp)
        self.assertFalse(cp.get("pr_url"))
        self.assertTrue(events(self.config, "checkpoint_pr_verify_failed"))
        self.mocks["process_one_entry"].assert_called_once()
        # STEP 03: 重啟、查得到 → 補上連結、清旗標。上一次重啟的前置作業把 w0 標成 merged：這組 fixture 的基準分支就是整合分支，
        # cp 分支（＝整合分支 tip）一定是它的祖先——真實環境的 merged 是 PR 已合併、不必再查。放回 opened
        self.set_checkpoint(status="opened")
        set_gh_modes(gh, list_mode="ok")
        self.restart()
        cp = checkpoint(self.config)
        self.assertEqual(cp.get("pr_url"), EXISTING_CP_PR_URL)
        self.assertFalse(cp.get("pr_unverified"), cp)

    def test_rechecked_after_each_module(self):
        """模組完成後也查一次：CLI（process_one_entry）跑的期間出現一筆連結未知的斷點 → 那一輪結束就補上。

        @return None
        """
        # STEP 01: 沒有宣告的斷點；CLI 跑的期間放進一筆 opened＋pr_unverified（啟動時的補查碰不到它）
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": []}))
        self.use_gh(prs=[cp_pr(EXISTING_CP_PR_URL)])
        # 連結未知的斷點記錄
        record = dict(
            runner.CHECKPOINT_FIELD_DEFAULTS,
            id=HARD_CHECKPOINT_ID,
            after={"wave": 0},
            mode="soft",
            pr_base=INTEGRATION_BRANCH,
            status="opened",
            branch=CP_BRANCH,
            pr_url="",
            pr_unverified=True,
        )

        def module_then_unverified(config, _entry):
            """代替 CLI：放進記錄、回 None（模組照常結束）。"""
            # STEP 01: 放進去
            runner.mutate_queue(config, lambda queue: queue["checkpoints"].append(record))

        self.mocks["process_one_entry"].side_effect = module_then_unverified
        self.assertEqual(self.restart(), runner.EXIT_OK)
        # STEP 02: 補上
        cp = checkpoint(self.config)
        self.assertEqual(cp.get("pr_url"), EXISTING_CP_PR_URL)
        self.assertFalse(cp.get("pr_unverified"), cp)


class CheckpointDeferralTest(CheckpointHarness):
    """必測 15：SIGTERM 落在斷點的 push 或 gh create 中 → side effect 完成、結果落盤後才退出；push 45 秒、gh 30 秒逾時。"""

    def test_sigterm_during_push(self):
        """push 進行中送 SIGTERM：push 做完（遠端有 cp 分支）、write-ahead 記錄在盤上，之後才以 ShutdownSignal 停下、沒 create。

        訊號在真的 push 之前送進 handler（等同 push 跑到一半收到）：不在延後區間的話 handler 當場拋出、push 根本沒做。

        @return None
        """
        # STEP 01: push 開始時注入訊號
        real_git = runner.git

        def spy(config, *args, **kwargs):
            """cp 分支 push 之前送 SIGTERM，再轉發。"""
            # STEP 01: 注入、轉發
            if args[:1] == ("push",) and CP_BRANCH in args:
                runner.shutdown_signal_handler(signal.SIGTERM, None)
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", spy):
            with self.assertRaises(runner.ShutdownSignal):
                runner.open_checkpoint(self.config, HARD_CHECKPOINT_ID)
        # STEP 02: 遠端已推、記錄在盤、沒有走到 create
        self.assertEqual(remote_tip(self.fixture, CP_BRANCH), self.fixture["base_sha"])
        cp = checkpoint(self.config)
        self.assertEqual((cp["status"], cp["branch"]), ("opening", CP_BRANCH))
        self.assertNotIn("pr create", gh_commands(self.gh))

    def test_sigterm_during_create(self):
        """create 進行中送 SIGTERM：create 做完、opened＋連結落盤之後才以 ShutdownSignal 停下。

        訊號在真的 create 之前送進 handler（等同 create 跑到一半收到）：不在延後區間的話 handler 當場拋出、create 根本沒做。
        「create 返回、落盤之前」那個窗另見 test_sigterm_after_create_before_persist。

        @return None
        """
        # STEP 01: create 開始時注入訊號
        real_run = runner.run_command

        def spy(args, cwd=None, timeout=runner.GIT_TIMEOUT_SECONDS, env=None, log_path=None):
            """pr create 之前送 SIGTERM，再轉發。"""
            # STEP 01: 注入、轉發
            if list(args[1:3]) == ["pr", "create"]:
                runner.shutdown_signal_handler(signal.SIGTERM, None)
            return real_run(args, cwd=cwd, timeout=timeout, env=env, log_path=log_path)

        with mock.patch.object(runner, "run_command", spy):
            with self.assertRaises(runner.ShutdownSignal):
                runner.open_checkpoint(self.config, HARD_CHECKPOINT_ID)
        # STEP 02: 已落盤
        cp = checkpoint(self.config)
        self.assertEqual((cp["status"], cp["pr_url"]), ("opened", FIRST_CREATED_PR_URL))

    def test_sigterm_after_create_before_persist(self):
        """create 返回、連結還沒落盤時送 SIGTERM（(c2) 的窗）：opened＋連結落盤之後才以 ShutdownSignal 停下。

        @return None
        """
        # STEP 01: create 返回後注入訊號
        real_run = runner.run_command

        def spy(args, cwd=None, timeout=runner.GIT_TIMEOUT_SECONDS, env=None, log_path=None):
            """轉發；pr create 返回後送 SIGTERM。"""
            # STEP 01: 轉發、注入
            result = real_run(args, cwd=cwd, timeout=timeout, env=env, log_path=log_path)
            if list(args[1:3]) == ["pr", "create"]:
                runner.shutdown_signal_handler(signal.SIGTERM, None)
            return result

        with mock.patch.object(runner, "run_command", spy):
            with self.assertRaises(runner.ShutdownSignal):
                runner.open_checkpoint(self.config, HARD_CHECKPOINT_ID)
        # STEP 02: 已落盤
        cp = checkpoint(self.config)
        self.assertEqual((cp["status"], cp["pr_url"]), ("opened", FIRST_CREATED_PR_URL))

    def test_short_timeouts(self):
        """cp 分支 push 逾時 45 秒，gh pr list／create 逾時 30 秒。

        @return None
        """
        # STEP 01: 記錄所有外部指令的 (參數開頭, timeout)
        seen = []
        real_run = runner.run_command

        def spy(args, cwd=None, timeout=runner.GIT_TIMEOUT_SECONDS, env=None, log_path=None):
            """記錄後轉發。"""
            # STEP 01: 記錄、轉發
            seen.append((tuple(args[1:3]), timeout))
            return real_run(args, cwd=cwd, timeout=timeout, env=env, log_path=log_path)

        with mock.patch.object(runner, "run_command", spy):
            self.assertTrue(runner.open_checkpoint(self.config, HARD_CHECKPOINT_ID))
        # STEP 02: 逐一比對
        # 參數開頭 → 逾時（同一個子命令出現多次時取最後一次）
        timeouts = dict(seen)
        self.assertEqual(timeouts.get(("push", "-u")), EXPECTED_CP_PUSH_TIMEOUT_SECONDS, seen)
        self.assertEqual(timeouts.get(("pr", "list")), EXPECTED_CP_GH_TIMEOUT_SECONDS, seen)
        self.assertEqual(timeouts.get(("pr", "create")), EXPECTED_CP_GH_TIMEOUT_SECONDS, seen)


class OpeningReadersTest(CheckpointHarness):
    """讀 checkpoint status 的地方對 opening／pr_unverified 的處理：取件前的閘門、進度檔待人工事項、重新匯入。"""

    def test_opened_hard_checkpoint_includes_opening(self):
        """opening 的 hard 斷點也算「取件前要先處理的閘門」；soft 的不算。

        @return None
        """
        # STEP 01: hard／soft 各看一次
        for mode, expected in (("hard", HARD_CHECKPOINT_ID), ("soft", None)):
            with self.subTest(mode=mode):
                self.set_checkpoint(status="opening", branch=CP_BRANCH, mode=mode)
                self.assertEqual(runner.opened_hard_checkpoint(runner.load_queue(self.config)), expected)

    def test_progress_lists_opening_and_unverified(self):
        """待人工事項：opening 的 hard 斷點帶 release 指令；連結未知的斷點帶分支名與「連結未知」。

        @return None
        """
        # STEP 01: w0 opening（hard）＋另一筆 opened＋pr_unverified
        self.set_checkpoint(status="opening", branch=CP_BRANCH, last_error="推送 cp 分支失敗")
        # 連結未知的斷點
        unverified = dict(runner.CHECKPOINT_FIELD_DEFAULTS, id="w9", mode="soft", status="opened", branch="r18-migration/cp-w9",
                          pr_url="", pr_unverified=True)
        runner.mutate_queue(self.config, lambda queue: queue["checkpoints"].append(unverified))
        # STEP 02: 真的 render（RestartHarness 把它換掉了，這裡用匯入時留下的原函式）
        body = REAL_RENDER_PROGRESS_TEXT(self.config, runner.load_queue(self.config))
        section = body.split("## 待人工事項", 1)[1]
        self.assertIn("release %s" % HARD_CHECKPOINT_ID, section)
        self.assertIn("r18-migration/cp-w9", section)
        self.assertIn("連結未知", section)

    def test_reimport_keeps_opening_and_unverified(self):
        """重新 import-inventory：opening 與 pr_unverified 都保留。

        @return None
        """
        # STEP 01: queue 裡 w0 opening、w1 opened＋pr_unverified
        self.set_checkpoint(status="opening", branch=CP_BRANCH)
        # 連結未知的宣告斷點
        second = dict(runner.CHECKPOINT_FIELD_DEFAULTS, id="w1", after={"wave": 0}, mode="soft", status="opened",
                      branch="r18-migration/cp-w1", pr_url="", pr_unverified=True)
        runner.mutate_queue(self.config, lambda queue: queue["checkpoints"].append(second))
        # STEP 02: 盤點檔（同樣兩個斷點）→ 匯入
        # 盤點檔路徑
        inventory_path = os.path.join(os.path.dirname(self.fixture["remote"]), "inventory.json")
        with open(inventory_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "entries": [{"id": ENTRY_ID, "wave": 0, "type": "page", "r15_paths": [R15_RELATIVE_PATH]}],
                    "checkpoints": [
                        {"id": HARD_CHECKPOINT_ID, "after": {"wave": 0}, "mode": "hard"},
                        {"id": "w1", "after": {"wave": 0}, "mode": "soft"},
                    ],
                },
                handle,
            )
        self.config.update({"branch_user": "tester", "entry_max_files": 50, "entry_max_lines": 5000, "module_timeout_min": 10,
                            "module_budget_usd": 1})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.cmd_import_inventory(self.config, argparse.Namespace(inventory=inventory_path)), runner.EXIT_OK)
        # STEP 03: 兩個欄位都在
        self.assertEqual(checkpoint(self.config)["status"], "opening")
        self.assertEqual(checkpoint(self.config)["branch"], CP_BRANCH)
        self.assertTrue(checkpoint(self.config, "w1").get("pr_unverified"))


if __name__ == "__main__":
    unittest.main()
