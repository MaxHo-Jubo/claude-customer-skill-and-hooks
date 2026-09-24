"""runner.py 1.1.2 D1 的回歸測試：舊 entry 分支重跑無煞車，以及「同簽名連續第二次就鎖定」的連續要真的連續。

D1：entry 分支從舊 tip 切出（逾時重試、blocked 後 unblock），期間別的 entry 已經合併、整合分支前進——
修正前 prepare_branch 只 checkout 舊分支，CLI 重跑之後 ff-merge 必敗、一般暫停、launchd 重啟再燒一次，
無限迴圈。拓撲一律用真的：entry 分支確實落後於「被另一個 entry 推進過」的整合分支，基準分支是另一條、
而且也前進過（前置作業會把它合進本機整合分支而不推），不用 no-op 合併冒充。
D2（呼叫序號）的測試在 test_call_number.py，第二批（c8093cb 的 codex review）修正的測試在 test_review_112b.py；
test_review_112b 從本檔匯入拓撲 helper（只匯入函式與常數）。

共用的 fixture 與小工具從 review_fixtures 匯入（只匯入函式與常數，不匯入 TestCase，免得被重複收集）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import argparse
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
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    BASE_BRANCH,
    ENTRY_BRANCH,
    ENTRY_ID,
    INTEGRATION_BRANCH,
    build_fixture,
    queue_entry,
    reject_entry_branch_push,
    remote_tip,
    run_git,
    start_patches,
)

# 另一個 entry 在整合分支上留下的檔案（無衝突版）：entry 分支沒碰過它
OTHER_ENTRY_FILE = "other.js"
# build_fixture 的 entry 分支新增的檔案；衝突版讓另一個 entry 也新增同名、內容不同的檔（add/add 衝突）
ENTRY_FILE = "migrated.js"
# 第二個 entry（cmd_run 分流測試用）：沒有既有分支，prepare_branch 會從整合分支新建
SECOND_ENTRY_ID = "e2"
SECOND_ENTRY_BRANCH = "e2-branch"


def advance_integration(fixture, filename, content, message):
    """另一個 entry 已經合併：在整合分支上多一個 commit 並推上遠端，queue 的 tip 記錄跟著前進。

    @param fixture build_fixture 的回傳值
    @param filename 那個 commit 新增的檔案（相對 repo 根目錄）
    @param content 檔案內容
    @param message commit 訊息
    @return 整合分支的新 tip（完整 sha）
    """
    # STEP 01: 在整合分支上 commit 並推送（runner 對另一個 entry 做完 ff-merge＋push 後的狀態）
    # 工作 repo 路徑
    work = fixture["config"]["repo_dir"]
    run_git(work, "checkout", INTEGRATION_BRANCH)
    with open(os.path.join(work, filename), "w", encoding="utf-8") as handle:
        handle.write(content)
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", message)
    run_git(work, "push", "origin", INTEGRATION_BRANCH)
    # 整合分支的新 tip（完整 sha）
    tip = run_git(work, "rev-parse", "HEAD")

    # STEP 02: queue 記下新 tip（finish_done_entry 會做的事）
    def record_tip(queue):
        """mutate_queue 用：整合分支 tip 前進（就地修改，沿用 mutate_queue 的寫入契約）。

        @param queue 整份 queue
        @return None
        """
        # STEP 01: 寫 tip
        queue["integration_tip_sha"] = tip

    runner.mutate_queue(fixture["config"], record_tip)
    return tip


def stale_fixture(conflict):
    """entry 分支落後的真實拓撲：基準分支另一條且已前進、整合分支被另一個 entry 推進過、entry 分支停在舊 tip。

    @param conflict True 時另一個 entry 也新增了 entry 分支的那個檔（內容不同），合併會衝突
    @return build_fixture 的回傳值（config 補上 base_branch；entry 狀態改回 pending，跟重跑時一樣；另加 stale_entry_sha）
    @raises AssertionError 造出來的拓撲裡 entry 分支沒有落後（前置條件不成立）
    """
    # STEP 01: 基本 fixture；基準分支從基線切出、前進一個 commit、推上遠端
    # 測試用的 git 環境與狀態目錄
    fixture = build_fixture(tempfile.mkdtemp(prefix="r18-stale-"), {"status": "pending"})
    # runner 設定
    config = fixture["config"]
    # 工作 repo 路徑
    work = config["repo_dir"]
    config["base_branch"] = BASE_BRANCH
    run_git(work, "checkout", "-b", BASE_BRANCH, fixture["base_sha"])
    with open(os.path.join(work, "hotfix.js"), "w", encoding="utf-8") as handle:
        handle.write("// landed on base after the integration branch was cut\n")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "base moves")
    run_git(work, "push", "-u", "origin", BASE_BRANCH)
    # STEP 02: 另一個 entry 合併進整合分支（entry 分支還停在舊基線上）
    if conflict:
        # STEP 02.01: 衝突版：另一個 entry 也新增了 entry 分支的那個檔（add/add）
        advance_integration(fixture, ENTRY_FILE, "// someone else's version\n", "migrate e0 (same file)")
    else:
        # STEP 02.02: 無衝突版：另一個 entry 新增別的檔
        advance_integration(fixture, OTHER_ENTRY_FILE, "// e0 migrated\n", "migrate e0")
    # STEP 03: 前置條件自驗——整合分支確實不是 entry 分支的祖先（entry 分支落後）；不成立就讓用到它的測試直接失敗
    if is_ancestor(work, INTEGRATION_BRANCH, ENTRY_BRANCH):
        raise AssertionError("前置條件不成立：entry 分支沒有落後於整合分支")
    # STEP 04: 記下舊分支 tip（測試用來確認 abort 之後分支沒動）
    fixture["stale_entry_sha"] = run_git(work, "rev-parse", ENTRY_BRANCH)
    return fixture


def is_ancestor(work, ancestor, descendant):
    """ancestor 是否為 descendant 的祖先（merge-base --is-ancestor：0 是、1 不是，其餘是指令失敗）。

    @param work 工作 repo
    @param ancestor 祖先候選
    @param descendant 後代候選
    @return bool
    @raises AssertionError git 指令本身失敗（不能當成「不是祖先」）
    """
    # STEP 01: 區分三種退出碼
    # merge-base 的執行結果
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=work, capture_output=True, text=True, check=False
    )
    if result.returncode not in (0, 1):
        # STEP 01.01: 指令失敗不能當成「不是祖先」
        raise AssertionError("merge-base 失敗: %s" % result.stderr)
    return result.returncode == 0


def install_failing_pre_merge_hook(work):
    """在工作 repo 裝一支一律失敗的 pre-merge-commit hook：造出「沒有衝突、但合併失敗」的真實情境。

    git 會停在合併中（MERGE_HEAD 還在、沒有 U 檔），跟分支保護、磁碟滿之類的非衝突失敗同一型。

    @param work 工作 repo
    @return None
    """
    # STEP 01: 寫 hook 並加執行權限
    # hook 檔路徑（git 只執行 .git/hooks/ 底下有執行權限的同名檔）
    hook_path = os.path.join(work, ".git", "hooks", "pre-merge-commit")
    os.makedirs(os.path.dirname(hook_path), exist_ok=True)
    with open(hook_path, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/sh\necho 'rejected by test hook' >&2\nexit 1\n")
    os.chmod(hook_path, 0o755)


def add_entry_branch(fixture, entry_id, branch):
    """從目前的整合分支切出一個新 entry 分支、多一個 commit，並登記進 queue（running，等發佈）。

    @param fixture build_fixture 的回傳值
    @param entry_id 新 entry 的 id
    @param branch 新 entry 的分支名稱
    @return 新 entry dict
    """
    # STEP 01: 分支與 commit
    # 工作 repo 路徑
    work = fixture["config"]["repo_dir"]
    run_git(work, "checkout", "-b", branch, INTEGRATION_BRANCH)
    with open(os.path.join(work, "%s.js" % entry_id), "w", encoding="utf-8") as handle:
        handle.write("// %s migrated\n" % entry_id)
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "migrate %s" % entry_id)
    # STEP 02: queue
    # 新 entry（沿用 fixture entry 的其餘欄位）
    entry = dict(fixture["entry"], id=entry_id, branch=branch, status="running", pr_url=None)

    def append(queue):
        """mutate_queue 用：登記新 entry（就地修改，沿用 mutate_queue 的寫入契約）。

        @param queue 整份 queue
        @return None
        """
        # STEP 01: 加進 modules
        queue["modules"].append(entry)

    runner.mutate_queue(fixture["config"], append)
    return entry


def git_with_override(prefix, response):
    """包住 runner.git：參數開頭符合 prefix 的那一種呼叫直接回 response，其餘照常執行（注入單一 git 失敗用）。

    @param prefix git 參數的開頭（tuple），例如 ("merge", "--abort")
    @param response 要回的 (returncode, stdout, stderr)
    @return 可以拿去 mock.patch.object(runner, "git", ...) 的函式
    """
    # 被包住的真函式（patch 之前先取，否則會拿到假件自己）
    real_git = runner.git

    def fake_git(config, *args, **kwargs):
        """符合就回假結果，否則轉給真的 git。

        @param config runner 設定
        @param args git 參數
        @param kwargs 原樣轉給 runner.git（timeout、log_path）
        @return (returncode, stdout, stderr)
        """
        # STEP 01: 比對參數開頭
        if tuple(args[: len(prefix)]) == tuple(prefix):
            # STEP 01.01: 命中就回注入的結果
            return response
        # STEP 02: 其餘照常執行
        return real_git(config, *args, **kwargs)

    return fake_git


class PrepareStaleBranchTest(unittest.TestCase):
    """D1：既有 entry 分支重跑前要先跟上整合分支；跟不上時分成 entry 級 blocked 與 runner 級暫停。"""

    def setUp(self):
        """通知與進度報表不是受測對象。

        @return None
        """
        # STEP 01: 隔離
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress")
        # CLI 判讀結果（發佈段收尾用到 structured、session_id、cost）
        self.outcome = {"structured": {}, "session_id": "session-2", "cost": 0.5}

    def _preflight(self, fixture):
        """跑一次真的前置作業（會把前進過的基準分支合進本機整合分支而不推），必須通過。

        @param fixture stale_fixture 的回傳值
        @return None
        """
        # STEP 01: 前置作業
        # runner 設定
        config = fixture["config"]
        # 前置作業的結果：是否通過、暫停原因、細節
        ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(ok, "%s: %s" % (reason, detail))

    def test_stale_branch_catches_up_and_publishes(self):
        """無衝突：prepare_branch 之後整合分支是 entry 分支的祖先，CLI 再 commit 一次之後發佈段可以 ff 合併並推送。

        修正前：只 checkout 舊分支，發佈段的 ff-merge 必敗 → integration_diverged 一般暫停 → 重啟重燒整個模組。

        @return None
        """
        # STEP 01: 前置作業＋準備分支
        # 測試用的 git 環境與狀態目錄
        fixture = stale_fixture(conflict=False)
        # runner 設定
        config = fixture["config"]
        # 工作 repo 路徑
        work = config["repo_dir"]
        self._preflight(fixture)
        self.assertFalse(is_ancestor(work, INTEGRATION_BRANCH, ENTRY_BRANCH), "前置條件：entry 分支應該落後")
        # prepare_branch 的結果與細節
        status, detail = runner.prepare_branch(config, fixture["entry"])

        # STEP 02: 已跟上（整合分支——含前置作業合進來的基準分支——是 entry 分支的祖先），舊的 commit 還在
        self.assertTrue(is_ancestor(work, INTEGRATION_BRANCH, ENTRY_BRANCH), detail)
        self.assertTrue(is_ancestor(work, fixture["stale_entry_sha"], ENTRY_BRANCH))
        self.assertEqual(run_git(work, "symbolic-ref", "--short", "HEAD"), ENTRY_BRANCH)
        self.assertEqual(status, runner.PREPARE_READY, detail)

        # STEP 03: CLI 重跑又 commit 一次；發佈段走完、遠端整合分支前進到 entry 分支的 tip
        with open(os.path.join(work, ENTRY_FILE), "a", encoding="utf-8") as handle:
            handle.write("// second run\n")
        run_git(work, "commit", "-am", "migrate e1 again")
        # CLI 重跑再 commit 之後的 entry 分支 tip
        entry_tip = run_git(work, "rev-parse", "HEAD")
        # 落盤後重讀的 queue 與 entry
        _queue, entry = queue_entry(fixture)
        self.assertIsNone(runner.publish_verified_entry(config, entry, self.outcome, 2))
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), entry_tip)
        self.assertEqual(queue_entry(fixture)[1]["status"], "done")

    def test_conflicting_stale_branch_blocks_entry(self):
        """有衝突：abort 乾淨、entry 標 blocked(git_state) 並通知，runner 不暫停（其他 entry 照跑）。

        @return None
        """
        # STEP 01: 前置作業＋準備分支
        # 測試用的 git 環境與狀態目錄
        fixture = stale_fixture(conflict=True)
        # runner 設定
        config = fixture["config"]
        # 工作 repo 路徑
        work = config["repo_dir"]
        self._preflight(fixture)
        # prepare_branch 的結果與細節
        status, detail = runner.prepare_branch(config, fixture["entry"])

        # STEP 02: entry 標 blocked、原因 git_state、細節帶衝突檔名與全文 log 指路
        # 落盤後重讀的 queue 與 entry
        _queue, entry = queue_entry(fixture)
        self.assertEqual(entry["status"], "blocked", detail)
        self.assertEqual(entry["blocked_reason"], "git_state")
        self.assertIn(ENTRY_FILE, entry["last_error"])
        self.assertIn("sessions/", entry["last_error"])
        self.assertIsNotNone(entry["finished_at"])
        self.assertEqual(status, runner.PREPARE_ENTRY_BLOCKED)

        # STEP 03: 合併已 abort：沒有 MERGE_HEAD、工作樹乾淨、entry 分支還在舊 tip
        self.assertFalse(os.path.exists(os.path.join(work, ".git", "MERGE_HEAD")))
        self.assertEqual(run_git(work, "status", "--porcelain"), "")
        self.assertEqual(run_git(work, "rev-parse", ENTRY_BRANCH), fixture["stale_entry_sha"])
        # STEP 04: 有通知，runner_state 沒有進 paused
        self.assertEqual(self.mocks["notify"].call_args.args[1], "module_blocked")
        self.assertNotEqual(runner.load_queue(config)["runner_state"].get("state"), "paused")

    def test_non_conflict_merge_failure_pauses_runner(self):
        """沒有衝突檔的合併失敗（hook 拒絕）：abort 乾淨、回 runner 級暫停，entry 不標 blocked。

        標 blocked 的話，同一個環境問題會把整條佇列逐一清成 blocked（紅隊第 3 點）。

        @return None
        """
        # STEP 01: 前置作業（hook 要在前置作業之後才裝，否則前置作業合併基準分支就先失敗）＋準備分支
        # 測試用的 git 環境與狀態目錄
        fixture = stale_fixture(conflict=False)
        # runner 設定
        config = fixture["config"]
        # 工作 repo 路徑
        work = config["repo_dir"]
        self._preflight(fixture)
        install_failing_pre_merge_hook(work)
        # prepare_branch 的結果與細節
        status, detail = runner.prepare_branch(config, fixture["entry"])

        # STEP 02: runner 級暫停（細節帶 hook 的錯誤輸出）；entry 維持 pending
        self.assertIn("rejected by test hook", detail)
        self.assertIn("非衝突", detail)
        self.assertEqual(status, runner.PREPARE_PAUSE, detail)
        self.assertEqual(queue_entry(fixture)[1]["status"], "pending")
        # STEP 03: 合併已 abort
        self.assertFalse(os.path.exists(os.path.join(work, ".git", "MERGE_HEAD")))
        self.assertEqual(run_git(work, "status", "--porcelain"), "")


class PrepareInjectedFailureTest(unittest.TestCase):
    """prepare_branch 的三個防呆：合併回報成功但沒跟上、衝突檔清單讀不到、abort 失敗——都不能當成可以往下走或 entry 級 blocked。"""

    def setUp(self):
        """通知與進度報表隔離。

        @return None
        """
        # STEP 01: 隔離
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress")

    def _prepare(self, conflict, prefix, response):
        """建舊分支拓撲、跑前置作業，注入一個 git 失敗後呼叫 prepare_branch。

        @param conflict 是否用衝突版拓撲
        @param prefix 要注入失敗的 git 參數開頭
        @param response 注入的 (returncode, stdout, stderr)
        @return (fixture, status, detail)
        """
        # STEP 01: 拓撲與前置作業
        # 測試用的 git 環境與狀態目錄
        fixture = stale_fixture(conflict=conflict)
        # runner 設定
        config = fixture["config"]
        # 前置作業的結果：是否通過、暫停原因、細節
        ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(ok, "%s: %s" % (reason, detail))
        # STEP 02: 注入後準備分支
        with mock.patch.object(runner, "git", git_with_override(prefix, response)):
            # prepare_branch 的結果與細節
            status, detail = runner.prepare_branch(config, fixture["entry"])
        return fixture, status, detail

    def test_merge_reported_success_but_not_caught_up_pauses(self):
        """合併指令回 0 但其實沒合（整合分支仍不是祖先）：暫停，不可以放行去呼叫 CLI。

        @return None
        """
        # STEP 01: 合併指令被換成「什麼都沒做的成功」
        # 注入失敗後 prepare_branch 的結果
        fixture, status, detail = self._prepare(False, ("merge", "--ff", "--no-edit"), (0, "", ""))
        # STEP 02: 暫停、entry 不動
        self.assertEqual(status, runner.PREPARE_PAUSE, detail)
        self.assertIn("祖先", detail)
        self.assertEqual(queue_entry(fixture)[1]["status"], "pending")

    def test_conflict_list_failure_is_not_treated_as_no_conflict_or_blocked(self):
        """衝突檔清單讀不到：不知道是不是衝突，走暫停（不標 blocked），細節說清楚是清單讀取失敗；合併照樣 abort。

        @return None
        """
        # STEP 01: 衝突版拓撲，清單指令失敗
        # 注入失敗後 prepare_branch 的結果
        fixture, status, detail = self._prepare(True, ("diff", "--name-only", "--diff-filter=U"), (1, "", "boom"))
        # STEP 02: 暫停、entry 不動、已 abort
        self.assertEqual(status, runner.PREPARE_PAUSE, detail)
        self.assertIn("衝突檔清單讀取失敗", detail)
        self.assertIn("無法判定是否衝突", detail)
        self.assertNotIn("非衝突", detail)
        self.assertEqual(queue_entry(fixture)[1]["status"], "pending")
        self.assertFalse(os.path.exists(os.path.join(fixture["config"]["repo_dir"], ".git", "MERGE_HEAD")))

    def test_abort_failure_after_conflict_pauses(self):
        """衝突但 abort 失敗（repo 停在合併中）：不能標 blocked 就換下一個 entry——下一個的前置作業也過不去；暫停並說明。

        @return None
        """
        # STEP 01: 衝突版拓撲，abort 失敗
        # 注入失敗後 prepare_branch 的結果
        fixture, status, detail = self._prepare(True, ("merge", "--abort"), (128, "", "abort boom"))
        # STEP 02: 暫停、entry 不動、細節帶分類標籤、衝突檔與 abort 的錯誤
        self.assertEqual(status, runner.PREPARE_PAUSE, detail)
        self.assertIn("有衝突但 abort 失敗", detail)
        self.assertIn(ENTRY_FILE, detail)
        self.assertIn("abort boom", detail)
        self.assertNotIn("非衝突", detail)
        self.assertEqual(queue_entry(fixture)[1]["status"], "pending")


class MarkEntryBlockedParityTest(unittest.TestCase):
    """抽出 mark_entry_blocked 之後，CLI 回報 blocked 的那條路徑欄位與花費不變。"""

    def test_cli_blocked_outcome_fields_and_cost(self):
        """apply_outcome(blocked)：status／blocked_reason（取 detail）／last_error／last_diagnostics／finished_at／花費都寫到。

        @return None
        """
        # STEP 01: fixture 與判讀結果
        start_patches(self, "notify")
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-blocked-parity-"))
        # CLI 判讀結果
        outcome = {"kind": "blocked", "detail": "too_large", "diagnostics": "diagnostics/x", "cost": 0.25}
        # STEP 02: 寫回
        self.assertEqual(runner.apply_outcome(fixture["config"], ENTRY_ID, outcome)[0], "continue")
        # 落盤後重讀的 queue 與 entry
        _queue, entry = queue_entry(fixture)
        self.assertEqual(
            (entry["status"], entry["blocked_reason"], entry["last_error"], entry["last_diagnostics"], entry["cost_usd_total"]),
            ("blocked", "too_large", "too_large", "diagnostics/x", 0.25),
        )
        self.assertIsNotNone(entry["finished_at"])


class PublishEntryNotFfTest(unittest.TestCase):
    """D1 第二道：發佈段 ff-merge 失敗（entry 分支不是整合分支的後代）要把 entry 標 blocked，不再一般暫停。"""

    def setUp(self):
        """entry 分支停在基線，整合分支被另一個 entry 推進過（沒有經過 prepare_branch 的跟上步驟）。

        @return None
        """
        # STEP 01: fixture；entry 還在 running（L1 通過、正要發佈）
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "notify", "write_progress", "freeze_entry_bundle")
        self.mocks["freeze_entry_bundle"].return_value = None
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-notff-"))
        advance_integration(self.fixture, OTHER_ENTRY_FILE, "// e0 migrated\n", "migrate e0")
        run_git(self.fixture["config"]["repo_dir"], "checkout", ENTRY_BRANCH)
        # CLI 判讀結果（發佈段收尾用到 structured、session_id、cost）
        self.outcome = {"structured": {}, "session_id": "session-1", "cost": 0.5}

    def test_ff_failure_blocks_entry_and_continues(self):
        """ff-merge 失敗：回 None（主迴圈繼續）、entry blocked(git_state)＋通知、花費有記，runner 不進暫停。

        修正前：integration_diverged 一般暫停 → launchd 重啟 → 前置作業放行 → 同一個舊分支再跑一次完整 CLI。

        @return None
        """
        # STEP 01: 發佈
        # 測試用的 git 環境與狀態目錄
        fixture = self.fixture
        # runner 設定
        config = fixture["config"]
        # 發佈前的遠端整合分支 tip（ff 失敗之後必須原封不動）
        remote_before = remote_tip(fixture, INTEGRATION_BRANCH)
        with mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
            # 受測呼叫回的 runner 退出碼（None 表示主迴圈繼續）
            exit_code = runner.publish_verified_entry(config, fixture["entry"], self.outcome, 1)

        # STEP 02: 沒有暫停
        paused.assert_not_called()
        self.assertIsNone(exit_code)
        # STEP 03: entry blocked、花費記入；遠端整合分支沒動
        # 落盤後重讀的 queue 與 entry
        _queue, entry = queue_entry(fixture)
        self.assertEqual(entry["status"], "blocked")
        self.assertEqual(entry["blocked_reason"], "git_state")
        self.assertIn("ff-merge", entry["last_error"])
        self.assertEqual(entry["cost_usd_total"], 0.5)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), remote_before)
        self.assertEqual(self.mocks["notify"].call_args.args[1], "module_blocked")


class RunPrepareDispatchTest(unittest.TestCase):
    """cmd_run 依 prepare_branch 的結果分流：entry 級 blocked → 換下一個 entry；非衝突失敗 → 暫停，CLI 都不呼叫。"""

    def setUp(self):
        """衝突版的舊分支拓撲＋第二個（沒有分支的）entry；主迴圈的外部依賴隔離，git 前置與準備分支用真的。

        @return None
        """
        # STEP 01: 拓撲與第二個 entry
        # 測試用的 git 環境與狀態目錄
        self.fixture = stale_fixture(conflict=True)
        # runner 設定
        self.config = self.fixture["config"]
        self.config.update({"circuit_breaker_n": 3, "notify_daily_digest": "09:00"})
        # 第二個 entry
        second = dict(self.fixture["entry"], id=SECOND_ENTRY_ID, branch=SECOND_ENTRY_BRANCH, status="pending")

        def append(queue):
            """mutate_queue 用：登記第二個 entry（排在 e1 之後：同 wave、同型別、同檔數，依 id 排序），runner 狀態設成 idle。

            @param queue 整份 queue（就地修改）
            @return None
            """
            # STEP 01: 登記並重設狀態
            queue["modules"].append(second)
            queue["runner_state"] = {"state": "idle"}

        runner.mutate_queue(self.config, append)
        # cmd_run 的命令列參數
        self.args = argparse.Namespace(max_modules=1)
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
            "handle_checkpoints",
        )
        self.mocks["require_config"].return_value = True
        self.mocks["lockfile_hash"].return_value = None
        self.mocks["preflight"].return_value = 0
        self.mocks["environment_fingerprint"].return_value = {}
        self.mocks["quota_snapshot"].return_value = {}
        self.mocks["quota_blocks_start"].return_value = (False, "", None)
        self.mocks["handle_checkpoints"].return_value = (False, None)
        # 假的 process_one_entry 處理過的 (entry id, 呼叫序號)
        self.processed = []

    def _fake_process(self, config, entry):
        """代替 process_one_entry：記下 entry 與當下的呼叫序號，並照真函式的後置條件把 entry 標成 done。

        不改狀態的話，主迴圈下一輪會再挑到同一個 entry（假件回「成功」卻沒做出狀態轉移）。

        @param config runner 設定
        @param entry 被處理的 entry
        @return None（主迴圈繼續）
        """
        # STEP 01: 紀錄＋狀態轉移
        self.processed.append((entry["id"], config.get("current_attempt")))

        def mark_done(queue):
            """mutate_queue 用：把被處理的 entry 標成 done（就地修改）。

            @param queue 整份 queue
            @return None
            """
            # STEP 01: 狀態轉移
            runner.find_entry(queue, entry["id"])["status"] = "done"

        runner.mutate_queue(config, mark_done)
        return None

    def test_conflict_blocks_entry_and_moves_on(self):
        """e1 分支合併衝突：e1 blocked，不呼叫 CLI，主迴圈接著處理 e2。

        @return None
        """
        # STEP 01: 主迴圈
        with mock.patch.object(runner, "process_one_entry", self._fake_process), \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_OK)

        # STEP 02: 只有 e2 被處理；e1 blocked；沒有暫停
        self.assertEqual([item[0] for item in self.processed], [SECOND_ENTRY_ID])
        self.assertEqual(queue_entry(self.fixture)[1]["status"], "blocked")
        paused.assert_not_called()

    def test_non_conflict_failure_pauses_before_cli(self):
        """e1 分支合併被 hook 拒絕（非衝突）：integration_dirty 暫停，CLI 一次都不呼叫、e1 不標 blocked。

        @return None
        """
        # STEP 01: 換成無衝突拓撲再裝 hook（hook 要在前置作業合併基準分支之後才生效，所以攔在前置作業之後）
        # 測試用的 git 環境與狀態目錄
        fixture = stale_fixture(conflict=False)
        # runner 設定
        config = fixture["config"]
        config.update({"circuit_breaker_n": 3})
        # 被包住的真 module_preflight（patch 之前先取）
        real_preflight = runner.module_preflight

        def preflight_then_hook(config_arg, queue):
            """代替 module_preflight：先跑真的前置作業，跑完才裝 hook。

            @param config_arg runner 設定
            @param queue 整份 queue
            @return 真的 module_preflight 的回傳值
            """
            # STEP 01: 真的前置作業
            # 真的前置作業的回傳值
            result = real_preflight(config_arg, queue)
            # STEP 02: 裝 hook
            install_failing_pre_merge_hook(config_arg["repo_dir"])
            return result

        with mock.patch.object(runner, "module_preflight", preflight_then_hook), \
                mock.patch.object(runner, "process_one_entry", self._fake_process), \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
            self.assertEqual(runner.cmd_run(config, self.args), runner.EXIT_PAUSED)

        # STEP 02: 暫停原因與 CLI 沒被呼叫
        self.assertEqual(paused.call_args.args[1], "integration_dirty")
        self.assertEqual(self.processed, [])
        self.assertEqual(queue_entry(fixture)[1]["status"], "pending")


class SignatureResetAfterDoneTest(unittest.TestCase):
    """F4：「同簽名連續第二次就鎖定」的連續要是真的連續——中間有 entry 完成就重新起算。"""

    def setUp(self):
        """通知與進度報表隔離。

        @return None
        """
        # STEP 01: 隔離
        start_patches(self, "notify", "write_progress")
        # CLI 判讀結果（發佈段收尾用到 structured、session_id、cost）
        self.outcome = {"structured": {}, "session_id": "s", "cost": 0.1}

    def test_push_failure_after_two_done_entries_does_not_hold(self):
        """推送失敗暫停 → 重啟 → 兩個 entry 完成 → 再一次推送失敗：一般暫停、不鎖定。

        修正前 startup_crash_signature 整個行程不清，第三次推送失敗被當成「連續第二次」而鎖死。

        @return None
        """
        # STEP 01: 第一次推送失敗（遠端拒收整合分支）→ 帶簽名的一般暫停
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-sigreset-"))
        # runner 設定
        config = fixture["config"]
        # 遠端拒收推送的 pre-receive hook 路徑（刪掉就恢復）
        hook = os.path.join(fixture["remote"], "hooks", "pre-receive")
        reject_entry_branch_push(fixture["remote"], branch=INTEGRATION_BRANCH)
        self.assertEqual(runner.publish_verified_entry(config, fixture["entry"], self.outcome, 1), runner.EXIT_PAUSED)
        # 落盤後的 runner_state
        state = runner.load_queue(config)["runner_state"]
        self.assertEqual(state.get("crash_signature"), runner.PUSH_FAILED_SIGNATURE)

        # STEP 02: 模擬 launchd 重啟（cmd_run 存下上一輪原因與簽名）；遠端恢復，e1 與 e2 依序完成
        config["startup_paused_reason"] = state["reason"]
        config["startup_crash_signature"] = state.get("crash_signature")
        runner.set_runner_state(config, "running")
        os.unlink(hook)
        self.assertIsNone(runner.publish_verified_entry(config, fixture["entry"], self.outcome, 2))
        # 第二個 entry（e2，從前進後的整合分支切出）
        second = add_entry_branch(fixture, "e2", "e2-branch")
        self.assertIsNone(runner.publish_verified_entry(config, second, self.outcome, 1))

        # STEP 03: 遠端又拒收；第三個 entry 推送失敗只能是一般暫停
        # 第三個 entry
        third = add_entry_branch(fixture, "e3", "e3-branch")
        reject_entry_branch_push(fixture["remote"], branch=INTEGRATION_BRANCH)
        self.assertEqual(runner.publish_verified_entry(config, third, self.outcome, 1), runner.EXIT_PAUSED)
        state = runner.load_queue(config)["runner_state"]
        self.assertEqual(state.get("reason"), "integration_diverged")
        self.assertFalse(state.get("hold"), state)


if __name__ == "__main__":
    unittest.main()
