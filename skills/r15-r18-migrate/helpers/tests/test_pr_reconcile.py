"""runner.py 1.1.2 第五批階段二的回歸測試：頁面 PR 已開、URL 未落盤（已知缺口 a）。

涵蓋 find_pr_by_head 的三態（url／None／錯誤）、push_branch_and_open_pr 先查再開、create 失敗或空輸出後再查一次、
「gh pr create → record_pr_result 落盤」的停止訊號延後區間、重啟對帳遇到空 pr_url 時補查，以及 plist ExitTimeOut。
外部狀態用真的：bare 遠端＋工作 repo、可設定情境的假 gh（fake_gh.write_scripted_gh，真的依 --state 過濾）。
「中斷 → cmd_run 重啟」沿用 test_reconcile 的 RestartHarness：BaseException 模擬 SIGKILL，CLI（process_one_entry）換成
「再跑一次發佈段」——重跑那一輪 CLI 的結果還是同一個 commit，受測的是發佈段怎麼處理已經存在的 PR。

新函式 find_pr_by_head 用 getattr 取：修正前它不存在，直接呼叫會以 AttributeError 失敗、不是以 AssertionError 證明「還沒修」。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 200; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import inspect
import json
import os
import re
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
from fake_gh import gh_commands, gh_prs, set_gh_modes, write_scripted_gh  # noqa: E402  pylint: disable=wrong-import-position
from test_reconcile import RestartHarness, SimulatedKill, events, publish  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    ENTRY_BRANCH,
    ENTRY_ID,
    INTEGRATION_BRANCH,
    build_fixture,
    queue_entry,
    read_plist_integer,
    reject_entry_branch_push,
    remote_tip,
    start_patches,
)

# 上一輪已經開好、仍是 open 的 PR（重跑時應沿用）
OPEN_PR_URL = "https://example.invalid/pull/41"
# 同一分支上已關閉的舊 PR（不可沿用）
CLOSED_PR_URL = "https://example.invalid/pull/40"
# fork 上同名分支開往同一個 base 的 PR（gh --head 不分 owner 會一起列出；不可沿用）
FORK_PR_URL = "https://example.invalid/fork/pull/200"
# 同 repo 的第二筆 open PR（正常不會有；出現就是查詢結果無法判定）
SECOND_OWN_PR_URL = "https://example.invalid/pull/42"
# find_pr_by_head 的 --limit 下限：至少要看得到兩筆，才分得出 fork 與自家、才抓得到「多於一筆」
MIN_LOOKUP_LIMIT = 2
# gh 兩個子命令（pr list／pr create）的逾時上限（秒）：計畫定的外部契約，不讀實作的常數
EXPECTED_GH_TIMEOUT_SECONDS = 30
# 發佈段延後區間三段有逾時的外部呼叫（推送 45＋ls-remote 15＋暫停通知 30）：plist ExitTimeOut 要大於它們的和
PUBLISH_REGION_TIMEOUTS = (45, 15, 30)
# 發佈段裡重跑那一輪 CLI 的判讀結果（發佈段只讀這三個欄位）
RERUN_OUTCOME = {"structured": {}, "session_id": "session-rerun", "cost": 0.2}


def pr_record(url, state, cross=False, head_oid=None):
    """假 gh 狀態檔裡的一筆 PR（head／base 是測試用的 entry 分支與整合分支）。

    @param url PR 連結
    @param state open 或 closed
    @param cross 是不是 fork 上同名分支開的（isCrossRepository）
    @param head_oid 指定的 headRefOid；None 表示取遠端 entry 分支現在的 commit
    @return dict
    """
    # STEP 01: 組欄位
    return {"url": url, "head": ENTRY_BRANCH, "base": INTEGRATION_BRANCH, "state": state, "cross": cross, "head_oid": head_oid}


def use_scripted_gh(fixture, prs=None, **modes):
    """把 fixture 的 gh 換成可設定情境的假 gh。

    @param fixture build_fixture 的回傳值
    @param prs 一開始就存在的 PR
    @param modes list_mode／create_mode
    @return write_scripted_gh 的回傳值
    """
    # STEP 01: 放在 fixture 根目錄、改 config
    # 假 gh 的路徑組
    gh = write_scripted_gh(os.path.dirname(fixture["remote"]), prs=prs, remote=fixture["remote"], **modes)
    fixture["config"]["gh_bin"] = gh["bin"]
    return gh


def lookup_function(test_case):
    """取 runner.find_pr_by_head；不存在時以 AssertionError 失敗（修正前的紅）。

    @param test_case 目前的 TestCase
    @return 函式
    """
    # STEP 01: getattr 而不是直接屬性存取
    # 受測函式
    function = getattr(runner, "find_pr_by_head", None)
    test_case.assertIsNotNone(function, "runner.find_pr_by_head 尚未實作")
    return function


class LookupHarness(unittest.TestCase):
    """直接呼叫 find_pr_by_head 的共用 fixture 與查詢包裝（本身沒有測試）。"""

    def setUp(self):
        """fixture。

        @return None
        """
        # STEP 01: 真的 git 環境（log 要落在它的狀態目錄）
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-findpr-"))

    def lookup(self, prs=None, **modes):
        """以指定情境查一次 entry 分支。

        @param prs 假 gh 上已有的 PR
        @param modes list_mode
        @return find_pr_by_head 的回傳值
        """
        # STEP 01: 換 gh → 查
        use_scripted_gh(self.fixture, prs=prs, **modes)
        return lookup_function(self)(self.fixture["config"], ENTRY_BRANCH, INTEGRATION_BRANCH)


class FindPrByHeadTest(LookupHarness):
    """find_pr_by_head 的三態：查到回 url、確定沒有回 None、查不到（gh 失敗／輸出壞掉）回錯誤——錯誤不可當成 None。"""

    def test_open_pr_is_found(self):
        """有 open PR → (url, None)。

        @return None
        """
        # STEP 01: 查
        self.assertEqual(self.lookup([pr_record(OPEN_PR_URL, "open")]), (OPEN_PR_URL, None))

    def test_only_closed_pr_is_none(self):
        """只有已關閉的 PR → (None, None)：那是「確定沒有 open PR」，不是錯誤。

        @return None
        """
        # STEP 01: 查
        self.assertEqual(self.lookup([pr_record(CLOSED_PR_URL, "closed")]), (None, None))

    def test_broken_answers_are_errors_not_none(self):
        """gh 非零退出、輸出不是 JSON、JSON 形狀不對、連結不是 PR 的形狀 → 一律是錯誤，不可回 (None, None)。

        @return None
        """
        # STEP 01: 四種壞答案
        # (情境名稱, 已有的 PR, list_mode)
        cases = (
            ("nonzero", [pr_record(OPEN_PR_URL, "open")], "fail"),
            ("notjson", [pr_record(OPEN_PR_URL, "open")], "notjson"),
            ("badshape", [pr_record(OPEN_PR_URL, "open")], "badshape"),
            ("not_pr_url", [pr_record("https://example.invalid/login/device", "open")], "ok"),
            ("notdict", [pr_record(OPEN_PR_URL, "open")], "notdict"),
            ("nocross", [pr_record(OPEN_PR_URL, "open")], "nocross"),
            ("nohead", [pr_record(OPEN_PR_URL, "open")], "nohead"),
            ("toomany", [pr_record(OPEN_PR_URL, "open"), pr_record(CLOSED_PR_URL, "open")], "ignorelimit"),
            # gh 不理 --limit、印出比上限還多的筆數（全是 fork）：形狀不符，不可當成「沒有」
            (
                "overlimit",
                [
                    pr_record("https://example.invalid/fork%d/pull/1" % index, "open", cross=True)
                    for index in range(getattr(runner, "PR_LOOKUP_LIMIT", MIN_LOOKUP_LIMIT) + 1)
                ],
                "ignorelimit",
            ),
        )
        for name, prs, mode in cases:
            with self.subTest(name=name):
                # 不可 raise（呼叫端都在 CLI 跑完之後，raise 會重燒一輪 CLI）：raise 也要以 AssertionError 呈現（在 except 外面 fail，不帶例外鏈）
                # 查詢拋出的例外；沒拋是 None
                raised = None
                try:
                    url, error = self.lookup(prs, list_mode=mode)
                except Exception as exc:  # pylint: disable=broad-except
                    raised = exc
                self.assertIsNone(raised, "find_pr_by_head 不可 raise")
                self.assertIsNone(url)
                self.assertTrue(error, "錯誤必須有說明（不可是 None／空字串）")

    def test_command_timeout_and_log(self):
        """指令就是計畫定的那一條、逾時 30 秒，全文落在合規名稱的子行程 log。

        @return None
        """
        # STEP 01: 包住 run_command 記參數
        # 每次 run_command 的 (參數, timeout, log_path)
        seen = []
        real_run = runner.run_command

        def spy(args, cwd=None, timeout=runner.GIT_TIMEOUT_SECONDS, env=None, log_path=None):
            """記錄後轉發。"""
            # STEP 01: 記錄並轉發
            seen.append((list(args), timeout, log_path))
            return real_run(args, cwd=cwd, timeout=timeout, env=env, log_path=log_path)

        with mock.patch.object(runner, "run_command", spy):
            self.lookup([pr_record(OPEN_PR_URL, "open")])
        # STEP 02: 參數、逾時、log
        args, timeout, log_path = seen[-1]
        self.assertEqual(
            args[1:-1],
            [
                "pr", "list", "--head", ENTRY_BRANCH, "--base", INTEGRATION_BRANCH, "--state", "open",
                "--json", "url,isCrossRepository,headRefOid", "--limit",
            ],
        )
        # --limit 至少 2：只取 1 筆的話 fork 同名分支的 PR 會把自家的擠掉，「多於一筆就報錯」也永遠不會觸發（review 112g P1）
        self.assertGreaterEqual(int(args[-1]), MIN_LOOKUP_LIMIT)
        self.assertEqual(timeout, EXPECTED_GH_TIMEOUT_SECONDS)
        self.assertTrue(log_path and os.path.exists(log_path), log_path)
        self.assertRegex(os.path.basename(log_path), r"^%s-1--gh-pr-list[a-z-]*\.log$" % ENTRY_ID)


class ForkAndHeadLookupTest(LookupHarness):
    """review 112g P1：gh 的 --head 不分 owner——fork 同名分支的 PR 不可沿用；同 repo 多筆是錯誤；給了 expected_head 就要比對 headRefOid。"""

    def lookup_with_head(self, prs, expected_head):
        """帶 expected_head 查一次；參數不存在時以 AssertionError 失敗（修正前的紅）。

        @param prs 假 gh 上已有的 PR
        @param expected_head 要求的 headRefOid
        @return find_pr_by_head 的回傳值
        """
        # STEP 01: 確認參數存在 → 查
        # 受測函式
        function = lookup_function(self)
        self.assertIn("expected_head", inspect.signature(function).parameters, "find_pr_by_head 沒有 expected_head 參數")
        use_scripted_gh(self.fixture, prs=prs)
        return function(self.fixture["config"], ENTRY_BRANCH, INTEGRATION_BRANCH, expected_head=expected_head)

    def test_newer_fork_pr_listed_first_own_is_reused(self):
        """fork 的 PR 較新、排在前面，自家的也在 → 沿用自家的。

        @return None
        """
        # STEP 01: 查
        prs = [pr_record(FORK_PR_URL, "open", cross=True), pr_record(OPEN_PR_URL, "open")]
        self.assertEqual(self.lookup(prs), (OPEN_PR_URL, None))

    def test_only_fork_pr_is_none(self):
        """只有 fork 的 PR → (None, None)：自家的 PR 還沒開，要去 create。

        @return None
        """
        # STEP 01: 查
        self.assertEqual(self.lookup([pr_record(FORK_PR_URL, "open", cross=True)]), (None, None))

    def test_two_own_open_prs_is_error(self):
        """同 repo 兩筆 open PR → 錯誤（無法判定要沿用哪一筆）。

        @return None
        """
        # STEP 01: 查
        url, error = self.lookup([pr_record(OPEN_PR_URL, "open"), pr_record(SECOND_OWN_PR_URL, "open")])
        self.assertIsNone(url)
        self.assertTrue(error)

    def test_limit_filled_with_forks_is_error(self):
        """回傳筆數頂到 --limit 而且全是 fork → 自家的可能在截斷線之外，是錯誤、不是「沒有」。

        @return None
        """
        # STEP 01: 造出剛好頂到上限的 fork PR
        # 上限（修正前沒有這個常數，退回下限）
        limit = getattr(runner, "PR_LOOKUP_LIMIT", MIN_LOOKUP_LIMIT)
        forks = [pr_record("https://example.invalid/fork%d/pull/1" % index, "open", cross=True) for index in range(limit)]
        url, error = self.lookup(forks)
        self.assertIsNone(url)
        self.assertTrue(error)

    def test_expected_head_must_match(self):
        """headRefOid 與 expected_head 不符 → 不沿用、回說明；相符 → 沿用。

        @return None
        """
        # STEP 01: 不符
        url, error = self.lookup_with_head([pr_record(OPEN_PR_URL, "open", head_oid=self.fixture["base_sha"])], self.fixture["entry_sha"])
        self.assertIsNone(url)
        self.assertIn(OPEN_PR_URL, error or "")
        # STEP 02: 相符
        matched = self.lookup_with_head([pr_record(OPEN_PR_URL, "open", head_oid=self.fixture["entry_sha"])], self.fixture["entry_sha"])
        self.assertEqual(matched, (OPEN_PR_URL, None))


class OpenPrLookupTest(unittest.TestCase):
    """push_branch_and_open_pr／publish_verified_entry：pr_url 為空時先查、查不到才開、開完拿不到連結再查一次。"""

    def setUp(self):
        """fixture；通知、進度、診斷包隔離。

        @return None
        """
        # STEP 01: fixture 與隔離
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-openpr-"))
        start_patches(self, "notify", "write_progress", "freeze_entry_bundle", "freeze_runner_bundle")
        self.addCleanup(self._reset_signal_state)

    @staticmethod
    def _reset_signal_state():
        """延後區間的模組層狀態歸零，免得失敗的測試汙染後面的測試。

        @return None
        """
        # STEP 01: 歸零
        runner._SIGNAL_DEFER_DEPTH = 0
        runner._PENDING_SIGNUM = None

    def open_pr(self, prs=None, **modes):
        """以指定情境跑一次 push_branch_and_open_pr。

        @param prs 假 gh 上已有的 PR
        @param modes list_mode／create_mode
        @return ((pr_url, pr_error), 假 gh 路徑組)
        """
        # STEP 01: 換 gh → 執行
        # 假 gh 的路徑組
        gh = use_scripted_gh(self.fixture, prs=prs, **modes)
        return runner.push_branch_and_open_pr(self.fixture["config"], self.fixture["entry"]), gh

    def test_only_fork_pr_creates_own(self):
        """review 112g P1b：分支上只有 fork 同名分支的 PR → 不沿用，開自家的。

        @return None
        """
        # STEP 01: 執行
        (url, error), gh = self.open_pr([pr_record(FORK_PR_URL, "open", cross=True)])
        self.assertIsNone(error)
        self.assertNotEqual(url, FORK_PR_URL)
        self.assertEqual(gh_commands(gh), ["pr list", "pr create"])

    def test_publish_does_not_reuse_pr_on_other_head(self):
        """發佈段把剛推上去的 tip 當 expected_head：既有 PR 的 headRefOid 不是它 → 不沿用、不 create（PR 已存在，create 只會失敗），記 pr_failed。

        @return None
        """
        # STEP 01: 既有 PR 的 head 停在基線
        gh = use_scripted_gh(self.fixture, prs=[pr_record(OPEN_PR_URL, "open", head_oid=self.fixture["base_sha"])])
        runner.publish_verified_entry(self.fixture["config"], self.fixture["entry"], RERUN_OUTCOME, 1)
        # STEP 02: 沒沿用、沒 create、pr_failed
        entry = queue_entry(self.fixture)[1]
        self.assertFalse(entry["pr_url"])
        self.assertTrue(entry["pr_failed"])
        self.assertEqual(gh_commands(gh), ["pr list"])

    def test_existing_open_pr_is_reused(self):
        """分支上已有 open PR（上一輪開了、URL 沒落盤）→ 沿用，不 create。

        @return None
        """
        # STEP 01: 執行
        result, gh = self.open_pr([pr_record(OPEN_PR_URL, "open")])
        self.assertEqual(result, (OPEN_PR_URL, None))
        self.assertEqual(gh_commands(gh), ["pr list"])

    def test_only_closed_pr_creates_new_one(self):
        """必測 3：同分支只有已關閉的舊 PR → 不沿用，查過之後開新的（查詢要帶 --state open，假 gh 真的依它過濾）。

        @return None
        """
        # STEP 01: 執行
        (url, error), gh = self.open_pr([pr_record(CLOSED_PR_URL, "closed")])
        self.assertIsNone(error)
        self.assertNotEqual(url, CLOSED_PR_URL)
        self.assertIn(url, [pr["url"] for pr in gh_prs(gh) if pr["state"] == "open"])
        self.assertEqual(gh_commands(gh), ["pr list", "pr create"])

    def test_create_exit_zero_without_url_rechecks(self):
        """必測 4：create 退出 0 但沒有連結（PR 其實建了）→ 再查一次，補上連結。

        @return None
        """
        # STEP 01: 執行
        (url, error), gh = self.open_pr(create_mode="empty")
        self.assertIsNone(error)
        self.assertEqual([url], [pr["url"] for pr in gh_prs(gh)])
        self.assertEqual(gh_commands(gh), ["pr list", "pr create", "pr list"])

    def test_create_failure_rechecks(self):
        """create 非零退出：建了（逾時／連線中斷）的話再查會找到並沿用；沒建的話維持原本的錯誤。

        @return None
        """
        # STEP 01: 建了但回報失敗
        (url, error), gh = self.open_pr(create_mode="fail_after_create")
        self.assertEqual((url, error), (gh_prs(gh)[0]["url"], None))
        # STEP 02: 真的沒建：錯誤照舊，而且確實再查過一次
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-openpr-fail-"))
        (url, error), gh = self.open_pr(create_mode="fail")
        self.assertIsNone(url)
        self.assertIn("開 PR 失敗", error)
        self.assertEqual(gh_commands(gh), ["pr list", "pr create", "pr list"])

    def test_create_uses_short_timeout(self):
        """gh pr create 在延後區間內，要有 30 秒逾時（預設 600 秒比 ExitTimeOut 長）。

        @return None
        """
        # STEP 01: 包住 run_command 記 create 的逾時
        # 每次 run_command 的 (子命令, timeout)
        seen = []
        real_run = runner.run_command

        def spy(args, cwd=None, timeout=runner.GIT_TIMEOUT_SECONDS, env=None, log_path=None):
            """記錄後轉發。"""
            # STEP 01: 記錄並轉發
            seen.append((" ".join(args[1:3]), timeout))
            return real_run(args, cwd=cwd, timeout=timeout, env=env, log_path=log_path)

        with mock.patch.object(runner, "run_command", spy):
            self.open_pr()
        self.assertIn(("pr create", EXPECTED_GH_TIMEOUT_SECONDS), seen)

    def test_lookup_failure_goes_to_pr_error_and_merges(self):
        """必測 2：pr list 失敗 → 不 raise（CLI 已跑完，raise 會走 crash、重燒一輪 CLI）、不 create，走 pr_error，合併照做。

        @return None
        """
        # STEP 01: 發佈
        gh = use_scripted_gh(self.fixture, list_mode="fail")
        self.assertIsNone(runner.publish_verified_entry(self.fixture["config"], self.fixture["entry"], RERUN_OUTCOME, 1))
        # STEP 02: done、pr_failed、沒 create、整合分支已推送
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertTrue(entry["pr_failed"])
        self.assertFalse(entry["pr_url"])
        self.assertEqual(gh_commands(gh), ["pr list"])
        self.assertEqual(remote_tip(self.fixture, INTEGRATION_BRANCH), self.fixture["entry_sha"])

    def test_sigterm_during_create_persists_pr_url_before_stopping(self):
        """必測 15（gh create 那一半）：gh pr create 執行中收到 SIGTERM → 延後到 pr_url 落盤之後才以 ShutdownSignal 停下。

        修正前：訊號當場拋出，PR 已建、queue 沒記——就是 (a)。

        @return None
        """
        # STEP 01: create 返回前送 SIGTERM（直接呼叫 handler，與 test_reconcile 的延後區間測試同一種注入）
        gh = use_scripted_gh(self.fixture)
        real_run = runner.run_command

        def signalling_run(args, **kwargs):
            """create 跑完、回到 runner 之前注入停止訊號。"""
            # STEP 01: 轉發 → 注入
            result = real_run(args, **kwargs)
            if list(args[1:3]) == ["pr", "create"]:
                runner.shutdown_signal_handler(signal.SIGTERM, None)
            return result

        with mock.patch.object(runner, "run_command", signalling_run):
            with self.assertRaises(runner.ShutdownSignal):
                runner.publish_verified_entry(self.fixture["config"], self.fixture["entry"], RERUN_OUTCOME, 1)
        # STEP 02: pr_url 已落盤、是假 gh 真的建的那一個
        self.assertEqual(queue_entry(self.fixture)[1]["pr_url"], gh_prs(gh)[0]["url"])


class PrCrashRestartTest(RestartHarness):
    """必測 1：PR 已建、URL 還沒落盤時被殺 → cmd_run 重啟、重跑發佈段時沿用原 PR。"""

    def test_crash_before_record_reuses_pr_on_restart(self):
        """create 返回之後、record_pr_result 之前被殺 → 重啟後沿用原 PR，pr_failed=False，create 只呼叫過 1 次。

        修正前：重跑時再 create → PR 已存在而失敗 → done 但 pr_failed=True、沒有連結。

        @return None
        """
        # STEP 01: 第一輪發佈，record_pr_result 那次寫入之前被殺
        gh = use_scripted_gh(self.fixture)
        real_mutate = runner.mutate_queue

        def killing_mutate(config, mutator):
            """record_pr_result 落盤之前模擬 SIGKILL；其餘照常。"""
            # STEP 01: 分流
            if getattr(mutator, "__name__", "") == "record_pr_result":
                raise SimulatedKill()
            return real_mutate(config, mutator)

        with mock.patch.object(runner, "mutate_queue", killing_mutate):
            with self.assertRaises(SimulatedKill):
                runner.publish_verified_entry(self.config, self.fixture["entry"], RERUN_OUTCOME, 1)
        # 前置條件：PR 建了、queue 沒記、整合分支沒動
        created = [pr["url"] for pr in gh_prs(gh)]
        self.assertEqual(len(created), 1)
        self.assertFalse(queue_entry(self.fixture)[1]["pr_url"])
        self.assertEqual(remote_tip(self.fixture, INTEGRATION_BRANCH), self.fixture["base_sha"])

        # STEP 02: 重啟；CLI 重跑之後再走一次發佈段
        def rerun(config, entry):
            """代替 process_one_entry：CLI 重跑的結果是同一個 commit，直接進發佈段。"""
            # STEP 01: 發佈
            return runner.publish_verified_entry(config, entry, RERUN_OUTCOME, config["current_attempt"])

        self.mocks["process_one_entry"].side_effect = rerun
        self.assertEqual(self.restart(), runner.EXIT_OK)
        # STEP 03: 沿用、沒有 pr_failed、create 只有第一輪那一次
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["pr_url"], created[0])
        self.assertFalse(entry["pr_failed"])
        self.assertEqual(gh_commands(gh).count("pr create"), 1)


class ReconcileLookupTest(RestartHarness):
    """必測（對帳路徑）：重啟對帳遇到 pr_url 為空 → 用 find_pr_by_head 補；查不到或查詢出錯才轉 pr_error。"""

    def crash_without_pr_url(self, prs=None, **modes):
        """分支上已有 open PR；發佈段推送整合分支後被殺，再把 queue 的連結拿掉（等同那一輪沒拿到連結）。

        @param prs 假 gh 上已有的 PR；None 表示一筆 head 跟著遠端分支的 open PR（OPEN_PR_URL）
        @param modes 重啟前把假 gh 改成的情境
        @return None
        """
        # STEP 01: 發佈（被殺）→ 清連結 → 設情境
        gh = use_scripted_gh(self.fixture, prs=prs or [pr_record(OPEN_PR_URL, "open")])
        publish(self.fixture, kill_before_done=True)
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, ENTRY_ID).update({"pr_url": None}))
        set_gh_modes(gh, **modes)

    def test_entry_branch_not_pushed_does_not_fill_old_pr(self):
        """review 112g P3：頁面分支推送被拒、整合分支推成功、done 之前被殺、舊 PR 還開著 → 對帳不查、不補舊 PR，與沒被殺時的發佈段一致
        （pr_url 空、pr_failed=True）。

        @return None
        """
        # STEP 01: 對照組——同情境不中斷的發佈段
        control = build_fixture(tempfile.mkdtemp(prefix="r18-p3-control-"))
        use_scripted_gh(control, prs=[pr_record(OPEN_PR_URL, "open")])
        reject_entry_branch_push(control["remote"])
        with mock.patch.object(runner, "freeze_entry_bundle", return_value=None):
            runner.publish_verified_entry(control["config"], control["entry"], RERUN_OUTCOME, 1)
        # 對照組的結果（pr_url, pr_failed）
        expected = (queue_entry(control)[1]["pr_url"], queue_entry(control)[1]["pr_failed"])
        # STEP 02: 中斷 → 重啟
        gh = use_scripted_gh(self.fixture, prs=[pr_record(OPEN_PR_URL, "open")])
        reject_entry_branch_push(self.fixture["remote"])
        publish(self.fixture, kill_before_done=True)
        self.restart()
        # STEP 03: 與對照組一致，而且和發佈段一樣根本不查 PR（光靠 head 比對擋不住 head 碰巧相等的舊 PR）
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertEqual((entry["pr_url"], entry["pr_failed"]), expected)
        self.assertEqual(expected, (None, True), "對照組前提")
        self.assertEqual(gh_commands(gh), [])

    def test_reconcile_does_not_fill_pr_on_other_head(self):
        """頁面分支已推上去，但既有 PR 的 headRefOid 不是 entry tip → 對帳不補連結、記 pr_failed（expected_head 要帶 entry tip）。

        @return None
        """
        # STEP 01: PR 的 head 停在基線 → 中斷 → 重啟
        self.crash_without_pr_url(prs=[pr_record(OPEN_PR_URL, "open", head_oid=self.fixture["base_sha"])])
        self.restart()
        # STEP 02: done、沒補、pr_failed
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertFalse(entry["pr_url"])
        self.assertTrue(entry["pr_failed"])

    def test_empty_pr_url_is_filled_by_lookup(self):
        """查到 open PR → 補上連結，pr_failed=False，沒有 pr_failed 事件。

        @return None
        """
        # STEP 01: 中斷 → 重啟
        self.crash_without_pr_url()
        self.restart()
        # STEP 02: done、連結補上
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["pr_url"], OPEN_PR_URL)
        self.assertFalse(entry["pr_failed"])
        self.assertEqual(events(self.config, "pr_failed"), [])
        self.mocks["process_one_entry"].assert_not_called()

    def test_lookup_failure_is_reported_as_pr_error(self):
        """查詢出錯 → 照樣補 done，pr_failed=True，事件寫明是查詢失敗（不是「沒有 PR」）。

        @return None
        """
        # STEP 01: 中斷 → 查詢會失敗 → 重啟
        self.crash_without_pr_url(list_mode="fail")
        self.restart()
        # STEP 02: done、pr_failed、事件說明
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "done")
        self.assertTrue(entry["pr_failed"])
        self.assertFalse(entry["pr_url"])
        self.assertIn("查詢既有 PR 失敗", json.dumps(events(self.config, "pr_failed"), ensure_ascii=False))


class RecordReconciledPrUrlTest(unittest.TestCase):
    """對帳查回的連結只補空值：queue 裡已有連結（別的寫入者先補上）不覆寫；entry 已不在 queue 不 raise。"""

    def test_only_fills_empty_and_tolerates_missing_entry(self):
        """已有連結不覆寫；entry 不存在時安靜略過。

        @return None
        """
        # STEP 01: 已有連結
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-recordpr-"), {"pr_url": OPEN_PR_URL})
        # 受測函式
        record = getattr(runner, "record_reconciled_pr_url", None)
        self.assertIsNotNone(record, "runner.record_reconciled_pr_url 尚未實作")
        record(fixture["config"], ENTRY_ID, CLOSED_PR_URL)
        self.assertEqual(queue_entry(fixture)[1]["pr_url"], OPEN_PR_URL)
        # STEP 02: entry 不存在（在 except 外面斷言，不帶例外鏈）
        # 寫入時拋出的例外；沒拋是 None
        raised = None
        try:
            record(fixture["config"], "no-such-entry", CLOSED_PR_URL)
        except Exception as exc:  # pylint: disable=broad-except
            raised = exc
        self.assertIsNone(raised, "entry 不存在時不可 raise")


class ExitTimeOutTest(unittest.TestCase):
    """plist ExitTimeOut 要蓋住延後區間最壞的時長：發佈區間三段有逾時的外部呼叫，以及 PR 區間的 create＋再查。"""

    def test_exit_timeout_covers_deferral_regions(self):
        """發佈區間 45＋15＋30＝90 秒已經頂到舊值 90，本機 git 與寫檔只能溢出；PR 區間是 30＋30。

        @return None
        """
        # STEP 01: 讀範本
        # plist 範本路徑
        template_path = os.path.join(os.path.dirname(HELPERS_DIR), "templates", "launchd.plist.template")
        with open(template_path, encoding="utf-8") as handle:
            exit_timeout = read_plist_integer(handle.read(), "ExitTimeOut")
        # STEP 02: 兩段各自要放得下，而且留本機時間
        self.assertGreater(exit_timeout, sum(PUBLISH_REGION_TIMEOUTS))
        self.assertGreater(exit_timeout, 2 * EXPECTED_GH_TIMEOUT_SECONDS)
        self.assertIsNotNone(re.search(r"\b%d\b" % exit_timeout, runner.ShutdownDeferral.__doc__), "docstring 第 (6) 類要寫到新值")


if __name__ == "__main__":
    unittest.main()
