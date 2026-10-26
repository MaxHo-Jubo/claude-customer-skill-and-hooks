"""runner.py 1.1.4 的回歸測試：runner 開的 PR 標題要與 commit 標題逐字相同。

起因（2026-10-19）：斷點 PR #11362 的標題是「R18 遷移自動斷點（累積 1 個模組未進斷點）」，與裡面唯一的 commit
`[CUP-227] feat(FE): 未使用-R18遷移-companydashboard` 對不上，審查者在 PR 清單看不出是哪個模組。
拓撲一律用真的 git（build_fixture 的 bare 遠端＋工作 repo）；`gh pr create` 的參數用包住 run_command 的方式攔截，
因為既有的假 gh 只記子命令、不記 --title。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest helpers.tests.test_pr_title -v
"""

import argparse
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
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    ENTRY_BRANCH,
    INTEGRATION_BRANCH,
    build_fixture,
    git_with_failure,
    queue_entry,
    reject_entry_branch_push,
    run_git,
    start_patches,
)

# build_fixture 的 entry 分支上唯一一個 commit 的標題（fixture 內寫死）
FIXTURE_COMMIT_SUBJECT = "migrate e1"
# 測試用的真實格式 commit 標題（含全形字元與括號，確認逐字照用）
REAL_SUBJECT = "[CUP-227] feat(FE): 未使用-R18遷移-companydashboard"
# 兩個 commit 的 committer 時間（unix 秒）：git 的 raw 日期格式要求至少 9 位數；固定值讓「由舊到新」的排序可重現
OLDER_COMMIT_TIME = 1_700_000_000
NEWER_COMMIT_TIME = 1_800_000_000
# 前一個（被關閉的斷點涵蓋的）模組的 commit 標題
OLD_SUBJECT = "[CUP-227] feat(FE): 未使用-R18遷移-companydashboard"

# 完成出口發現「done 缺 last_commit」時的暫停原因（外部契約：runner_state.reason、paused 事件與通知看到的字串，寫成字面值）
DONE_MISSING_COMMIT_REASON = "done_missing_last_commit"
# 佇列全部完成的通知事件名（外部契約）
QUEUE_COMPLETE_EVENT = "queue_complete"


def entry_spec(entry_id, last_commit, checkpoint_id=None, status="done"):
    """組一個 queue entry（只填測試用得到的欄位，其餘取 runner 的預設）。"""
    return dict(
        runner.RUNTIME_FIELD_DEFAULTS,
        id=entry_id,
        branch="%s-branch" % entry_id,
        type="page",
        wave=0,
        r18_dir="pages/%s" % entry_id,
        r15_paths=["frontend/react_15/%s.js" % entry_id],
        status=status,
        last_commit=last_commit,
        checkpoint_id=checkpoint_id,
    )


def set_entries(config, entries):
    """把 queue 的 modules 換成指定的 entry 清單（其餘欄位不動）。"""

    def mutator(queue):
        """替換 modules。"""
        queue["modules"] = entries

    runner.mutate_queue(config, mutator)


def commit_with_time(work, filename, subject, unix_time):
    """在工作 repo 目前分支加一個指定 committer 時間的 commit，回傳它的 sha。"""
    with open(os.path.join(work, filename), "w", encoding="utf-8") as handle:
        handle.write(subject)
    run_git(work, "add", "-A")
    env = dict(os.environ, GIT_COMMITTER_DATE="%d +0000" % unix_time, GIT_AUTHOR_DATE="%d +0000" % unix_time)
    subprocess.run(["git", "commit", "-q", "-m", subject], cwd=work, env=env, check=True, capture_output=True)
    return run_git(work, "rev-parse", "HEAD")


def add_commit(work, filename, subject):
    """在工作 repo 目前分支加一個 commit（檔案內容就是標題，確保每次都有變更）。"""
    with open(os.path.join(work, filename), "w", encoding="utf-8") as handle:
        handle.write(subject)
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", subject)


def read_events(config, event):
    """讀 runner.log.jsonl 中指定事件名的所有紀錄。"""
    path = os.path.join(config["state_dir"], "runner.log.jsonl")
    with open(path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    return [record for record in records if record.get("event") == event]


class PrTitleFromCommitsTest(unittest.TestCase):
    """pr_title_from_commits：單一 commit 逐字照用、多個加後綴、取不到（git 失敗或沒有 commit）拋 PrTitleError。"""

    def setUp(self):
        """每個測試一組全新的 git 環境（entry 分支比整合分支多一個 commit）。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = build_fixture(self.tmp.name)
        self.config = self.fixture["config"]
        self.work = self.config["repo_dir"]

    def test_single_commit_title_is_verbatim(self):
        """範圍內只有一個 commit：標題與 commit 標題逐字相同。"""
        title = runner.pr_title_from_commits(self.config, INTEGRATION_BRANCH, ENTRY_BRANCH)
        self.assertEqual(title, FIXTURE_COMMIT_SUBJECT)
        self.assertEqual(read_events_safe(self.config, runner.PR_TITLE_FALLBACK_EVENT), [])

    def test_real_format_subject_is_verbatim(self):
        """真實格式（Jira 編號、全形字、括號）的 commit 標題不被改動。"""
        run_git(self.work, "commit", "--amend", "-m", REAL_SUBJECT)
        title = runner.pr_title_from_commits(self.config, INTEGRATION_BRANCH, ENTRY_BRANCH)
        self.assertEqual(title, REAL_SUBJECT)

    def test_multiple_commits_use_oldest_with_suffix(self):
        """範圍內有多個 commit：取最舊的那個（不是 tip），後面接總數後綴。"""
        add_commit(self.work, "second.js", "second commit")
        add_commit(self.work, "third.js", "third commit")
        title = runner.pr_title_from_commits(self.config, INTEGRATION_BRANCH, ENTRY_BRANCH)
        self.assertEqual(title, FIXTURE_COMMIT_SUBJECT + runner.PR_TITLE_MORE_COMMITS_SUFFIX % 3)

    def test_merge_commits_are_not_counted(self):
        """範圍內的 merge commit（prepare_branch 把整合分支合進來的那種）不算進標題與總數。"""
        run_git(self.work, "checkout", INTEGRATION_BRANCH)
        add_commit(self.work, "other.js", "other entry landed")
        run_git(self.work, "checkout", ENTRY_BRANCH)
        run_git(self.work, "merge", "--no-ff", "--no-edit", INTEGRATION_BRANCH)
        # 整合分支前進後，範圍是 integration..entry：只剩 entry 自己的那個 commit（merge commit 被排除）
        title = runner.pr_title_from_commits(self.config, INTEGRATION_BRANCH, ENTRY_BRANCH)
        self.assertEqual(title, FIXTURE_COMMIT_SUBJECT)

    def test_empty_range_raises(self):
        """範圍內沒有 commit：拋 PrTitleError（不回傳舊標題），訊息指出範圍。"""
        with self.assertRaises(runner.PrTitleError) as ctx:
            runner.pr_title_from_commits(self.config, ENTRY_BRANCH, ENTRY_BRANCH)
        self.assertIn("沒有 commit", str(ctx.exception))
        self.assertIn("%s..%s" % (ENTRY_BRANCH, ENTRY_BRANCH), str(ctx.exception))

    def test_bad_ref_raises(self):
        """git 失敗（ref 不存在）：拋 PrTitleError，訊息有退出碼，不與「範圍內沒有 commit」混為一談。"""
        with self.assertRaises(runner.PrTitleError) as ctx:
            runner.pr_title_from_commits(self.config, "no-such-ref", ENTRY_BRANCH)
        self.assertIn("git log 失敗", str(ctx.exception))
        self.assertNotIn("沒有 commit", str(ctx.exception))


def read_events_safe(config, event):
    """事件檔可能還不存在（沒寫過任何事件）；不存在視為沒有事件。"""
    try:
        return read_events(config, event)
    except FileNotFoundError:
        return []


class PrTitleFromEntryCommitsTest(unittest.TestCase):
    """pr_title_from_entry_commits：只看「done 且還沒蓋章」的 entry 的 last_commit；資料異常拋 PrTitleError，沒有涵蓋的 entry 回 None。"""

    def setUp(self):
        """每個測試一組全新的 git 環境。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = build_fixture(self.tmp.name)
        self.config = self.fixture["config"]
        self.work = self.config["repo_dir"]

    def title(self, entries):
        """用指定 entry 清單呼叫 helper。"""
        return runner.pr_title_from_entry_commits(self.config, {"modules": entries})

    def test_single_covered_entry_is_verbatim(self):
        """只有一個涵蓋的 entry：標題與它的 commit 標題逐字相同。"""
        sha = self.fixture["entry_sha"]
        self.assertEqual(self.title([entry_spec("e1", sha)]), FIXTURE_COMMIT_SUBJECT)

    def test_stamped_and_unfinished_entries_are_excluded(self):
        """已蓋章（前一個斷點涵蓋）的 entry、還沒 done 的 entry 都不算進標題。"""
        old_sha = commit_with_time(self.work, "old.js", OLD_SUBJECT, OLDER_COMMIT_TIME)
        new_sha = commit_with_time(self.work, "new.js", REAL_SUBJECT, NEWER_COMMIT_TIME)
        entries = [
            entry_spec("old", old_sha, checkpoint_id="auto-closed"),
            entry_spec("running", old_sha, status="running"),
            entry_spec("e1", new_sha),
        ]
        self.assertEqual(self.title(entries), REAL_SUBJECT)

    def test_multiple_covered_use_oldest_commit_by_time_not_queue_order(self):
        """多個涵蓋的 entry：取 commit 時間最舊的，而不是 queue 裡排最前面的。"""
        older = commit_with_time(self.work, "a.js", "older commit", OLDER_COMMIT_TIME)
        newer = commit_with_time(self.work, "b.js", "newer commit", NEWER_COMMIT_TIME)
        # queue 順序刻意與時間順序相反
        title = self.title([entry_spec("newer", newer), entry_spec("older", older)])
        self.assertEqual(title, "older commit" + runner.PR_TITLE_MORE_COMMITS_SUFFIX % 2)

    def test_missing_last_commit_raises_not_partial_title(self):
        """有一個涵蓋的 entry 沒有 last_commit（done 的不變量被破壞）：拋 PrTitleError，不拿剩下的湊、也不回傳舊標題。"""
        sha = self.fixture["entry_sha"]
        with self.assertRaises(runner.PrTitleError) as ctx:
            self.title([entry_spec("e1", sha), entry_spec("broken", None)])
        self.assertIn("broken 沒有 last_commit", str(ctx.exception))
        self.assertNotIn("e1 ", str(ctx.exception))

    def test_unreadable_commit_raises(self):
        """last_commit 在 repo 裡不存在（git show 失敗）：拋 PrTitleError，訊息有 entry id 與退出碼。"""
        with self.assertRaises(runner.PrTitleError) as ctx:
            self.title([entry_spec("e1", "0" * 40)])
        self.assertIn("e1", str(ctx.exception))
        self.assertIn("讀不到標題", str(ctx.exception))

    def test_all_problems_are_reported_together(self):
        """兩個涵蓋的 entry 都有問題：訊息一次列出兩個，不是只報第一個。"""
        with self.assertRaises(runner.PrTitleError) as ctx:
            self.title([entry_spec("broken-a", None), entry_spec("broken-b", "0" * 40)])
        self.assertIn("broken-a 沒有 last_commit", str(ctx.exception))
        self.assertIn("broken-b", str(ctx.exception))

    def test_no_covered_entry_returns_none_and_logs(self):
        """沒有任何涵蓋的 entry（例如宣告的斷點到期時，它的 entry 已被前一個 auto 斷點蓋章）：不是錯誤，回 None 並留事件。"""
        title = self.title([entry_spec("old", self.fixture["entry_sha"], checkpoint_id="auto-closed")])
        self.assertIsNone(title)
        events = read_events(self.config, runner.PR_TITLE_FALLBACK_EVENT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["detail"]["reason"], "沒有涵蓋的 entry")


class UncoveredDoneEntriesTest(unittest.TestCase):
    """B6：「done 且還沒進斷點」的判準只有一份（uncovered_done_entries），標題、auto 門檻、凍結涵蓋集合、蓋章四處共用。"""

    def setUp(self):
        """每個測試一組全新的 git 環境。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = build_fixture(self.tmp.name)
        self.config = self.fixture["config"]
        # begin_checkpoint_opening 新建 auto 斷點時讀的基準分支
        self.config.setdefault("base_branch", INTEGRATION_BRANCH)
        # 一個 done、沒蓋章；一個 done、已蓋章；一個 running；一個 pending；另一個 done、沒蓋章
        self.entries = [
            entry_spec("a", self.fixture["entry_sha"]),
            entry_spec("stamped", self.fixture["entry_sha"], checkpoint_id="auto-closed"),
            entry_spec("running", self.fixture["entry_sha"], status="running"),
            entry_spec("pending", None, status="pending"),
            entry_spec("b", self.fixture["entry_sha"]),
        ]

    def test_helper_selects_done_without_checkpoint_id(self):
        """只回 done 且沒有 checkpoint_id 的 entry、保持 queue 順序，回傳的是 queue 裡的原物件（蓋章要就地改）。"""
        found = runner.uncovered_done_entries({"modules": self.entries})
        self.assertEqual([entry["id"] for entry in found], ["a", "b"])
        self.assertIs(found[0], self.entries[0])

    def test_helper_tolerates_queue_without_modules(self):
        """queue 沒有 modules 欄位：回空 list（與四個呼叫點原本的 `queue.get("modules", [])` 一致）。"""
        self.assertEqual(runner.uncovered_done_entries({}), [])

    def test_four_sites_agree_on_the_same_set(self):
        """同一份 queue：標題涵蓋、auto 門檻、covered_entries、蓋章四處看到同一個集合 {a, b}。"""
        queue = {"modules": self.entries}
        # auto 門檻：兩個未進斷點 → max=2 觸發、max=3 不觸發（base_ref 為 None，不碰 git）
        config = dict(self.config, checkpoint_max_modules=2, checkpoint_max_lines=10**9)
        self.assertTrue(runner.auto_checkpoint_needed(config, queue)[0])
        self.assertFalse(runner.auto_checkpoint_needed(dict(config, checkpoint_max_modules=3), queue)[0])
        # 標題：兩個 entry 的 last_commit 同一個 → 取到同一個 commit 標題＋兩個 commit 的後綴
        self.assertEqual(
            runner.pr_title_from_entry_commits(self.config, queue),
            FIXTURE_COMMIT_SUBJECT + runner.PR_TITLE_MORE_COMMITS_SUFFIX % 2,
        )
        # 凍結涵蓋集合
        set_entries(self.config, self.entries)
        record = runner.begin_checkpoint_opening(self.config, "auto-agree", "cp/auto-agree", None, frozen_sha="f" * 40)
        self.assertEqual(record["covered_entries"], ["a", "b"])
        # 蓋章
        stamped_queue = {"modules": [dict(entry) for entry in self.entries]}
        runner.stamp_covered_entries(stamped_queue, {"id": "auto-agree", "covered_entries": None})
        self.assertEqual([entry["checkpoint_id"] for entry in stamped_queue["modules"] if entry["id"] in ("a", "b")], ["auto-agree"] * 2)
        self.assertEqual(stamped_queue["modules"][2].get("checkpoint_id"), None)

    def test_each_site_calls_the_shared_helper(self):
        """機械式證明四處真的走同一個 helper：把它換成固定回傳，四處的結果都跟著變（各自維護判準的話不會變）。"""
        spy_entry = entry_spec("spy-only", self.fixture["entry_sha"])
        with mock.patch.object(runner, "uncovered_done_entries", return_value=[spy_entry]) as spy:
            # auto 門檻：queue 裡一個 done 都沒有，helper 回一個 → max=1 觸發
            config = dict(self.config, checkpoint_max_modules=1, checkpoint_max_lines=10**9)
            self.assertTrue(runner.auto_checkpoint_needed(config, {"modules": []})[0])
            # 標題：queue 沒有 entry，helper 回一個有 commit 的 → 取得它的標題
            self.assertEqual(runner.pr_title_from_entry_commits(self.config, {"modules": []}), FIXTURE_COMMIT_SUBJECT)
            # 凍結涵蓋集合
            record = runner.begin_checkpoint_opening(self.config, "auto-spy", "cp/auto-spy", None, frozen_sha="f" * 40)
            self.assertEqual(record["covered_entries"], ["spy-only"])
            # 蓋章：只蓋 helper 回的那個
            other = entry_spec("other", None)
            runner.stamp_covered_entries({"modules": [other, spy_entry]}, {"id": "auto-spy", "covered_entries": None})
            self.assertEqual(spy_entry["checkpoint_id"], "auto-spy")
            self.assertIsNone(other.get("checkpoint_id"))
            self.assertGreaterEqual(spy.call_count, 4)


def count_gh_creates(fixture):
    """假 gh 的呼叫紀錄檔裡 `pr create` 的次數；檔案不存在代表 gh 一次都沒被呼叫。

    @param fixture build_fixture 的回傳值（取 gh_calls 路徑）
    @return pr create 的次數
    """
    # STEP 01: 讀呼叫紀錄；檔案不存在 = gh 從沒被呼叫
    try:
        with open(fixture["gh_calls"], encoding="utf-8") as handle:
            return len([line for line in handle if line.strip() == "pr create"])
    except FileNotFoundError:
        return 0


class DoneMissingCommitRestartTest(unittest.TestCase):
    """完成出口的狀態不變量（方案 b）：存在「done 且還沒蓋章、卻缺 last_commit」的 entry，cmd_run 不得宣告佇列完成。

    起因：auto 斷點取標題失敗（PrTitleError）發生在斷點意圖落盤之前，runner 走 crash → paused；重啟時 cmd_run 不再看 auto 斷點
    （include_auto=False），主迴圈 ready 為空就判「佇列全部完成」、改 idle 並通知，斷點 PR 從頭到尾沒建立，也沒有任何可辨識的暫停原因。
    修正只記一個可辨識的暫停原因（不保存斷點意圖、不動斷點狀態機）。cmd_run 的外部依賴隔離方式同 test_reconcile.RestartHarness。
    """

    def setUp(self):
        """每個測試一組全新的 git 環境，並隔離 cmd_run 與本測試無關的外部依賴。"""
        # STEP 01: 真的 git 環境；基準分支設成整合分支本身（前置作業的基準合併是 no-op）；auto 門檻 1 個模組就觸發
        # 測試用的 git 環境與狀態目錄
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-donemissing-"))
        # runner 設定
        self.config = self.fixture["config"]
        self.config.update(
            {"base_branch": INTEGRATION_BRANCH, "circuit_breaker_n": 3, "checkpoint_max_modules": 1, "checkpoint_max_lines": 10**9}
        )
        # STEP 02: 隔離（preflight 只做「把上一輪 running 放回 pending」）
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
        self.mocks["preflight"].side_effect = self.fake_preflight
        self.mocks["environment_fingerprint"].return_value = {}
        self.mocks["quota_snapshot"].return_value = {}
        self.mocks["quota_blocks_start"].return_value = (False, "", None)
        self.mocks["render_progress_text"].return_value = "body"
        self.mocks["freeze_runner_bundle"].return_value = None
        self.mocks["freeze_entry_bundle"].return_value = None
        self.mocks["wait_for_release"].return_value = False
        self.mocks["process_one_entry"].return_value = runner.EXIT_PAUSED
        # fixture 的 entry sha（正常 done entry 的 last_commit）
        self.sha = self.fixture["entry_sha"]

    def fake_preflight(self, config):
        """代替 preflight：只做它對 queue 的那件事——把上一輪被中斷的 entry 放回 pending。

        @param config runner 設定
        @return 0（通過）
        """
        # STEP 01: 與 preflight 的 mutator 同一個函式
        runner.mutate_queue(config, runner.recover_interrupted_entries)
        return 0

    def restart(self):
        """跑一次 cmd_run（最多處理一個模組）。

        @return cmd_run 的退出碼
        """
        # STEP 01: 主迴圈
        return runner.cmd_run(self.config, argparse.Namespace(max_modules=1))

    def notified_events(self):
        """到目前為止 notify 被呼叫過的事件名（依序）。"""
        return [call.args[1] for call in self.mocks["notify"].call_args_list]

    def runner_state(self):
        """重讀落盤後的 runner_state。"""
        return runner.load_queue(self.config).get("runner_state", {})

    def assert_paused_for_missing_commit(self, code, *entry_ids):
        """退出碼是暫停、原因是新的暫停原因、沒有通知佇列完成、狀態不是 idle，而且訊息列出了指定的 entry id。

        @param code cmd_run 的退出碼
        @param entry_ids 預期出現在暫停訊息裡的 entry id
        @return 暫停訊息（paused 事件的 detail 文字）
        """
        # STEP 01: 退出碼、狀態與通知
        self.assertEqual(code, runner.EXIT_PAUSED)
        state = self.runner_state()
        self.assertEqual(state.get("state"), "paused", state)
        self.assertEqual(state.get("reason"), DONE_MISSING_COMMIT_REASON, state)
        self.assertNotIn(QUEUE_COMPLETE_EVENT, self.notified_events())
        # STEP 02: paused 事件的細節列出 entry id 與要修的欄位
        paused = [record for record in read_events_safe(self.config, "paused") if record["detail"]["reason"] == DONE_MISSING_COMMIT_REASON]
        self.assertTrue(paused, "沒有以新原因記錄 paused 事件")
        text = paused[-1]["detail"]["detail"]
        for entry_id in entry_ids:
            self.assertIn(entry_id, text)
        self.assertIn("last_commit", text)
        return text

    def assert_completed(self, code):
        """cmd_run 正常宣告完成：EXIT_OK、狀態 idle、通知過一次佇列完成。"""
        self.assertEqual(code, runner.EXIT_OK)
        self.assertEqual(self.runner_state().get("state"), "idle", self.runner_state())
        self.assertEqual(self.notified_events().count(QUEUE_COMPLETE_EVENT), 1)

    def test_reproduction_crash_in_auto_checkpoint_then_restart_does_not_complete(self):
        """重現：最後一個 entry done 但缺 last_commit，第一次 auto 斷點取標題拋 PrTitleError → crash 暫停；重啟不得 idle、不得通知完成。

        修正前：第二次回 EXIT_OK、runner_state 變 idle、通知「佇列全部完成」。
        """
        self.mocks["process_one_entry"].side_effect = self.finish_without_last_commit
        # STEP 01: 第一次：auto 斷點取標題拋例外，走 crash 流程暫停
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assertEqual(self.runner_state().get("reason"), runner.CRASH_REASON)
        self.assertEqual(self.mocks["process_one_entry"].call_count, 1)
        # STEP 02: 重啟：可辨識的暫停原因，不通知完成，process_one_entry 沒有再被叫；過程中 runner_state 一次都沒被設成 idle
        with mock.patch.object(runner, "set_runner_state", wraps=runner.set_runner_state) as spy:
            code = self.restart()
        self.assert_paused_for_missing_commit(code, "e1")
        self.assertEqual(self.mocks["process_one_entry"].call_count, 1)
        self.assertNotIn("idle", [call.args[1] for call in spy.call_args_list])

    def test_one_missing_among_many_done_lists_only_the_broken_one(self):
        """多個 done entry 其中一個缺 last_commit：暫停，訊息只列缺的那個。"""
        set_entries(
            self.config,
            [entry_spec("mod-a", self.sha), entry_spec("mod-b", None), entry_spec("mod-c", self.sha)],
        )
        text = self.assert_paused_for_missing_commit(self.restart(), "mod-b")
        self.assertNotIn("mod-a", text)
        self.assertNotIn("mod-c", text)

    def test_all_missing_are_listed_together(self):
        """兩個 done entry 都缺：一次列出全部（不是修一個、重啟、再暫停一次）。"""
        set_entries(self.config, [entry_spec("a", None), entry_spec("b", ""), entry_spec("c", self.sha)])
        self.assert_paused_for_missing_commit(self.restart(), "a", "b")

    def test_stamped_done_entry_without_last_commit_does_not_block(self):
        """已蓋章（有 checkpoint_id）的 done entry 缺 last_commit：不擋。

        理由：會造成「斷點漏開」的只有還沒進斷點、標題要取它 last_commit 的 entry（uncovered_done_entries）；已蓋章代表它涵蓋的
        斷點已經開過、PR 已存在，沒有東西會因此漏掉，擋它只會讓舊資料被誤暫停。
        """
        set_entries(self.config, [entry_spec("a", self.sha), entry_spec("old", None, checkpoint_id="auto-closed")])
        self.assert_completed(self.restart())

    def test_healthy_queue_completes_normally(self):
        """所有 entry 都正常（done 都有 last_commit）：照常通知完成、idle，不得誤暫停。"""
        set_entries(self.config, [entry_spec("a", self.sha), entry_spec("b", self.sha, checkpoint_id="auto-x")])
        self.assert_completed(self.restart())

    def test_fixing_last_commit_by_hand_then_restart_completes(self):
        """暫停之後人工把 modules[].last_commit 補上、重啟：正常宣告完成，暫停原因被清掉。"""
        set_entries(self.config, [entry_spec("a", None)])
        self.assert_paused_for_missing_commit(self.restart(), "a")
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, "a").update(last_commit=self.sha))
        self.assert_completed(self.restart())
        self.assertIsNone(self.runner_state().get("reason"))

    def test_after_manual_fix_restart_opens_the_auto_checkpoint(self):
        """人工補上 last_commit 後重啟：auto 斷點要補開，不能只宣告完成而把斷點默默略過。

        起因：auto 斷點取標題失敗發生在意圖落盤之前，重啟時 STEP 02.07 只在「對帳補了 done」才看 auto 斷點；
        完成出口（STEP 03.03.02）依佇列現況補看（unattempted_done_entries），否則資料修好後 runner 宣告完成、斷點 PR 卻從頭到尾沒開。
        """
        # STEP 01: entry done 缺 last_commit → 暫停；此時還沒有任何斷點、gh 沒有收到 pr create
        set_entries(self.config, [entry_spec("a", None)])
        self.assert_paused_for_missing_commit(self.restart(), "a")
        self.assertFalse(runner.load_queue(self.config).get("checkpoints"))
        self.assertEqual(count_gh_creates(self.fixture), 0)
        # STEP 02: 人工補上 last_commit 後重啟：auto 斷點被開出（queue 多一個斷點、假 gh 收到一次 pr create）
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, "a").update(last_commit=self.sha))
        self.restart()
        self.assertEqual(len(runner.load_queue(self.config).get("checkpoints") or []), 1)
        self.assertEqual(count_gh_creates(self.fixture), 1)

    def test_unreadable_last_commit_blocks_completion_like_a_missing_one(self):
        """last_commit 有值但 git show 讀不到（commit 不存在）：和缺 last_commit 一樣不得宣告佇列完成，以同一個可辨識原因暫停。

        第三輪 codex review 的重現：檢查若只看 last_commit 是否為空，這種 PrTitleError（斷點意圖落盤之前拋出）
        走 crash 暫停、重啟後出口檢查放行、通知佇列完成，auto 斷點永久漏開。
        """
        # STEP 01: 不存在的 commit（git show 失敗）；出口檢查直接擋下，訊息有 entry id
        bad_sha = "0" * 40
        set_entries(self.config, [entry_spec("a", bad_sha)])
        self.assert_paused_for_missing_commit(self.restart(), "a")

    def test_unreadable_last_commit_crash_then_restart_does_not_complete_and_recovers(self):
        """codex 第三輪的完整重現：done entry 的 last_commit 讀不到 → auto 斷點取標題拋 PrTitleError → crash 暫停；
        重啟不得通知完成（原因是可辨識的暫停），人工補成存在的 commit 後重啟，auto 斷點被補開。
        """
        bad_sha = "0" * 40

        def finish_with_unreadable_commit(config, _entry):
            """代替 process_one_entry：把 entry 標 done、last_commit 指向不存在的 commit，回 None 讓主迴圈往下做斷點檢查。"""
            # STEP 01: 落盤
            runner.mutate_queue(config, lambda queue: runner.find_entry(queue, "e1").update(status="done", last_commit=bad_sha))

        self.mocks["process_one_entry"].side_effect = finish_with_unreadable_commit
        # STEP 01: 第一次：auto 斷點取標題拋例外，crash 暫停（還沒有斷點、gh 沒收到 pr create）
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assertEqual(self.runner_state().get("reason"), runner.CRASH_REASON)
        self.assertEqual(count_gh_creates(self.fixture), 0)
        # STEP 02: 重啟：不得通知完成，原因是可辨識的暫停
        self.assert_paused_for_missing_commit(self.restart(), "e1")
        # STEP 03: 人工補成存在的 commit 後重啟：auto 斷點被補開
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, "e1").update(last_commit=self.sha))
        self.restart()
        self.assertEqual(len(runner.load_queue(self.config).get("checkpoints") or []), 1)
        self.assertEqual(count_gh_creates(self.fixture), 1)

    def finish_without_last_commit(self, config, _entry):
        """代替 process_one_entry：把 entry 標 done 卻不記 last_commit，回 None 讓主迴圈往下做斷點檢查（auto 斷點取標題會拋 PrTitleError）。"""
        # STEP 01: 落盤
        runner.mutate_queue(config, lambda queue: runner.find_entry(queue, "e1").update(status="done", last_commit=None))

    def crash_at_last_entry_then_fix_data(self):
        """造出「最後一個 entry 完成時 auto 斷點取標題 crash、暫停原因是 runner_crashed，之後人工把資料補好」的狀態。

        @return None（呼叫後 queue 的 e1 是 done、有 last_commit、沒蓋章，沒有任何斷點，runner_state 是 paused／runner_crashed）
        """
        # STEP 01: 第一次：auto 斷點取標題拋例外，走 crash 流程暫停（斷點意圖沒落盤、gh 沒收到 pr create）
        self.mocks["process_one_entry"].side_effect = self.finish_without_last_commit
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assertEqual(self.runner_state().get("reason"), runner.CRASH_REASON)
        self.assertFalse(runner.load_queue(self.config).get("checkpoints"))
        # STEP 02: 人工把 last_commit 補好（資料現在是健康的）
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, "e1").update(last_commit=self.sha))

    def test_crash_pause_then_data_fixed_restart_opens_the_auto_checkpoint(self):
        """暫停原因是 runner_crashed（不是 done_missing_last_commit），資料在重啟前已補好：auto 斷點仍要補開，不能直接宣告完成。

        第四輪 review 的 IMPORTANT：補開的條件原本是「上次暫停原因剛好是 done_missing_last_commit」，這條路徑漏開。
        """
        # STEP 01: crash 暫停＋資料補好
        self.crash_at_last_entry_then_fix_data()
        # STEP 02: 重啟：auto 斷點被開出（queue 多一個斷點、假 gh 收到一次 pr create），且已蓋章
        self.restart()
        self.assertEqual(len(runner.load_queue(self.config).get("checkpoints") or []), 1)
        self.assertEqual(count_gh_creates(self.fixture), 1)
        self.assertTrue(runner.find_entry(runner.load_queue(self.config), "e1").get("checkpoint_id"))

    def test_unblock_runner_then_restart_opens_the_auto_checkpoint(self):
        """crash 暫停後執行 `unblock --runner`（暫停原因被清成 None、狀態回 idle），資料是好的：重啟一樣要補開 auto 斷點。"""
        # STEP 01: crash 暫停＋資料補好，再 unblock
        self.crash_at_last_entry_then_fix_data()
        self.assertEqual(runner.unblock_runner(self.config), runner.EXIT_OK)
        self.assertIsNone(self.runner_state().get("reason"))
        # STEP 02: 重啟：auto 斷點被開出
        self.restart()
        self.assertEqual(len(runner.load_queue(self.config).get("checkpoints") or []), 1)
        self.assertEqual(count_gh_creates(self.fixture), 1)

    def test_failed_auto_checkpoint_is_attempted_once_not_on_every_restart(self):
        """補開 auto 斷點失敗（cp 分支推不上去）：只嘗試一次，之後每次重啟不再推新 id 的 cp 分支（launchd 每 300 秒重啟一次）。

        條件是 unattempted_done_entries：write-ahead 把 covered_entries 落盤，失敗（failed）之後它還在，集合就變空。
        每次重啟都要正常走到完成（EXIT_OK、idle），而且完成通知帶出「斷點開失敗、它涵蓋的模組沒有 PR」。
        """
        # STEP 01: 遠端拒絕所有 cp 分支的推送；entry 正常 done 且未蓋章，runner 因別的原因（crash）暫停
        reject_entry_branch_push(self.fixture["remote"], branch=runner.CHECKPOINT_BRANCH_TEMPLATE % "", prefix=True)
        set_entries(self.config, [entry_spec("a", self.sha)])
        runner.set_runner_state(self.config, "paused", reason=runner.CRASH_REASON)
        # STEP 02: 連續重啟三次：每次都是 EXIT_OK＋idle；斷點記錄只有一筆（failed）；沒有任何 pr create，遠端也沒有 cp 分支
        for _ in range(3):
            self.assertEqual(self.restart(), runner.EXIT_OK)
            self.assertEqual(self.runner_state().get("state"), "idle", self.runner_state())
        checkpoints = runner.load_queue(self.config).get("checkpoints") or []
        self.assertEqual(len(checkpoints), 1, checkpoints)
        self.assertEqual(checkpoints[0]["status"], runner.CheckpointStatus.FAILED)
        self.assertEqual(count_gh_creates(self.fixture), 0)
        self.assertEqual(run_git(self.fixture["remote"], "branch", "--list", "r18-migration/cp-*"), "")
        # STEP 03: 每一則完成通知都帶出失敗的斷點 id（notify 的第 4 個位置參數是內文）
        complete_bodies = [call.args[3] for call in self.mocks["notify"].call_args_list if call.args[1] == QUEUE_COMPLETE_EVENT]
        self.assertEqual(len(complete_bodies), 3)
        for body in complete_bodies:
            self.assertIn(checkpoints[0]["id"], body)

    def test_healthy_completion_notification_does_not_mention_failed_checkpoints(self):
        """沒有開失敗的斷點時，完成通知內文只有模組數（不帶任何警告）。"""
        set_entries(self.config, [entry_spec("a", self.sha, checkpoint_id="auto-x")])
        self.assert_completed(self.restart())
        complete_bodies = [call.args[3] for call in self.mocks["notify"].call_args_list if call.args[1] == QUEUE_COMPLETE_EVENT]
        self.assertEqual(complete_bodies, ["共 1 個模組"])

    def test_legacy_checkpoint_without_covered_entries_is_retried_once_then_bounded(self):
        """舊記錄（failed 但沒有 covered_entries）不涵蓋任何 entry：完成出口補開一次，新記錄帶涵蓋集合，之後重啟不再嘗試。

        這是改成「None 不涵蓋」的取捨：最壞多補開一次；改前（視為涵蓋全部）會讓這批永久不補、而且沒有任何通知。
        """
        # STEP 01: 遠端拒絕所有 cp 分支；queue 裡先有一筆舊的 failed 斷點（沒有 covered_entries）
        reject_entry_branch_push(self.fixture["remote"], branch=runner.CHECKPOINT_BRANCH_TEMPLATE % "", prefix=True)
        set_entries(self.config, [entry_spec("a", self.sha)])

        def add_legacy(queue):
            """加一筆舊格式的 failed 斷點：沒有 covered_entries 欄位。"""
            checkpoint = dict(runner.CHECKPOINT_FIELD_DEFAULTS)
            checkpoint.update({"id": "legacy-1", "status": runner.CheckpointStatus.FAILED, "mode": "soft"})
            checkpoint.pop("covered_entries", None)
            queue.setdefault("checkpoints", []).append(checkpoint)

        runner.mutate_queue(self.config, add_legacy)
        # STEP 02: 連續重啟三次：只多一筆新記錄（舊的加新的共 2 筆），新的帶 covered_entries
        for _ in range(3):
            self.assertEqual(self.restart(), runner.EXIT_OK)
        checkpoints = runner.load_queue(self.config).get("checkpoints") or []
        self.assertEqual(len(checkpoints), 2, checkpoints)
        self.assertEqual(checkpoints[1]["covered_entries"], ["a"])

    def test_unreadable_integration_tip_still_records_the_attempt(self):
        """讀不到整合分支 tip（凍結不了）而開失敗：失敗記錄仍帶 covered_entries，重啟不會把同一批當成從沒嘗試過。

        改前 covered_entries 綁在 frozen_sha 上，這種記錄是 None，完成出口會把同一批 entry 當成沒嘗試過。
        """
        # STEP 01: rev-parse 整合分支失敗；entry 正常 done 且未蓋章，runner 因別的原因（crash）暫停
        set_entries(self.config, [entry_spec("a", self.sha)])
        runner.set_runner_state(self.config, "paused", reason=runner.CRASH_REASON)
        broken_tip = git_with_failure(("rev-parse", "--verify", "refs/heads/%s" % INTEGRATION_BRANCH), (128, "", "fatal: injected"))
        # STEP 02: 連續重啟兩次：只有一筆 failed 記錄，帶 covered_entries，沒有 pr create
        with mock.patch.object(runner, "git", broken_tip):
            for _ in range(2):
                self.assertEqual(self.restart(), runner.EXIT_OK)
        checkpoints = runner.load_queue(self.config).get("checkpoints") or []
        self.assertEqual(len(checkpoints), 1, checkpoints)
        self.assertEqual(checkpoints[0]["status"], runner.CheckpointStatus.FAILED)
        self.assertEqual(checkpoints[0]["covered_entries"], ["a"])
        self.assertEqual(count_gh_creates(self.fixture), 0)

    def test_begin_opening_records_covered_entries_even_without_a_frozen_tip(self):
        """begin_checkpoint_opening：讀不到 tip（frozen_sha=None）也寫 covered_entries；之後凍結成功以凍結當下的集合覆寫。"""
        # STEP 01: 兩個 done 未蓋章的 entry；沒有 tip：記下涵蓋集合、沒有 frozen_sha
        set_entries(self.config, [entry_spec("a", self.sha), entry_spec("b", self.sha)])
        first = runner.begin_checkpoint_opening(self.config, "auto-t", "r18-migration/cp-auto-t", "標題", None)
        self.assertIsNone(first.get("frozen_sha"))
        self.assertEqual(first["covered_entries"], ["a", "b"])
        # STEP 02: 中間又多一個 done 的 entry；這次讀得到 tip：凍結並以當下的集合覆寫
        runner.mutate_queue(self.config, lambda queue: queue["modules"].append(entry_spec("c", self.sha)))
        second = runner.begin_checkpoint_opening(self.config, "auto-t", "r18-migration/cp-auto-t", "標題", self.sha)
        self.assertEqual(second["frozen_sha"], self.sha)
        self.assertEqual(second["covered_entries"], ["a", "b", "c"])
        # STEP 03: 已凍結就沿用，不再被覆寫
        runner.mutate_queue(self.config, lambda queue: queue["modules"].append(entry_spec("d", self.sha)))
        third = runner.begin_checkpoint_opening(self.config, "auto-t", "r18-migration/cp-auto-t", "標題", self.sha)
        self.assertEqual(third["covered_entries"], ["a", "b", "c"])

    def test_below_threshold_restart_does_not_open_an_auto_checkpoint(self):
        """沒到 auto 門檻（模組數、行數都沒超）：完成出口補看之後也不開斷點，照常宣告完成。"""
        # STEP 01: 門檻拉高，entry 正常 done 且未蓋章
        self.config["checkpoint_max_modules"] = 5
        set_entries(self.config, [entry_spec("a", self.sha)])
        # STEP 02: 重啟：沒有斷點、gh 沒有收到 pr create、正常完成
        self.assert_completed(self.restart())
        self.assertFalse(runner.load_queue(self.config).get("checkpoints"))
        self.assertEqual(count_gh_creates(self.fixture), 0)

    def test_unattempted_helper_excludes_entries_any_started_checkpoint_covers(self):
        """unattempted_done_entries：只列「done、未蓋章、不在任何已開始開啟的斷點的 covered_entries」的 entry。

        pending 的斷點不算；沒有 covered_entries 的舊記錄（任何狀態）不涵蓋任何 entry——一筆這樣的記錄不會遮蔽整份 queue，
        也不會影響別的斷點的涵蓋集合；released 帶涵蓋集合的照算（release 不蓋章，但這批已被人決定不開）。
        """
        modules = [entry_spec("x", self.sha), entry_spec("y", self.sha), entry_spec("z", self.sha)]
        # STEP 01: 沒有斷點、只有 pending 的斷點：全部都是
        self.assertEqual([e["id"] for e in runner.unattempted_done_entries({"modules": modules})], ["x", "y", "z"])
        pending = {"id": "p", "status": "pending", "covered_entries": ["x"]}
        self.assertEqual(len(runner.unattempted_done_entries({"modules": modules, "checkpoints": [pending]})), 3)
        # STEP 02: failed 且涵蓋 x、y：只剩 z
        failed = {"id": "f", "status": "failed", "covered_entries": ["x", "y"]}
        self.assertEqual([e["id"] for e in runner.unattempted_done_entries({"modules": modules, "checkpoints": [failed]})], ["z"])
        # STEP 03: 沒有涵蓋集合的舊記錄（任何狀態）不涵蓋任何 entry，也不遮蔽同一份 queue 裡其他斷點的涵蓋集合
        for status in ("failed", "opening", "opened", "merged", "released"):
            legacy = {"id": "l", "status": status, "covered_entries": None}
            self.assertEqual(len(runner.unattempted_done_entries({"modules": modules, "checkpoints": [legacy]})), 3, status)
            alongside = runner.unattempted_done_entries({"modules": modules, "checkpoints": [legacy, failed]})
            self.assertEqual([e["id"] for e in alongside], ["z"], status)
        # STEP 04: released 帶涵蓋集合：照算（人已決定不開這批的 PR，不再補開）
        released = {"id": "r", "status": "released", "covered_entries": ["x", "y", "z"]}
        self.assertEqual(runner.unattempted_done_entries({"modules": modules, "checkpoints": [released]}), [])

    def test_failed_checkpoints_with_unstamped_entries_helper(self):
        """failed_checkpoints_with_unstamped_entries：只列 failed、而且涵蓋的 entry 至今沒蓋章的斷點 id。"""
        modules = [entry_spec("x", self.sha), entry_spec("y", self.sha, checkpoint_id="auto-ok")]
        checkpoints = [
            {"id": "f-open", "status": "failed", "covered_entries": ["x"]},
            {"id": "f-stamped", "status": "failed", "covered_entries": ["y"]},
            {"id": "f-legacy", "status": "failed", "covered_entries": None},
            {"id": "o", "status": "opened", "covered_entries": ["x"]},
        ]
        self.assertEqual(runner.failed_checkpoints_with_unstamped_entries({"modules": modules, "checkpoints": checkpoints}), ["f-open"])
        self.assertEqual(runner.failed_checkpoints_with_unstamped_entries({"modules": modules}), [])

    def test_mark_done_entry_has_last_commit_and_completes(self):
        """mark-done 路徑寫入的 done entry 有 last_commit：不被新檢查誤擋，佇列照常完成。"""
        work = self.config["repo_dir"]
        run_git(work, "checkout", INTEGRATION_BRANCH)
        run_git(work, "merge", "--ff-only", ENTRY_BRANCH)
        run_git(work, "push", "origin", INTEGRATION_BRANCH)
        # STEP 01: fixture 的 entry 先放回人工接手的典型狀態（pending 且缺 last_commit），再用 cmd_mark_done 標 done
        runner.mutate_queue(self.config, lambda queue: runner.find_entry(queue, "e1").update(status="pending", last_commit=None))
        args = argparse.Namespace(entry_id="e1", commit=self.sha, note="人工")
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with mock.patch.object(sys, "stdout", sink):
                self.assertEqual(runner.cmd_mark_done(self.config, args), runner.EXIT_OK)
        self.assertEqual(queue_entry(self.fixture)[1]["last_commit"], self.sha)
        # STEP 02: 重啟
        self.assert_completed(self.restart())

    def test_restart_while_already_paused_for_it_stays_paused_without_renotifying(self):
        """已經因這個原因 paused 時再重啟（launchd 每 300 秒一次）：仍是暫停、不重複通知、原因不變。"""
        set_entries(self.config, [entry_spec("a", None)])
        self.assert_paused_for_missing_commit(self.restart(), "a")
        first = [event for event in self.notified_events() if event != "runner_started"]
        self.assert_paused_for_missing_commit(self.restart(), "a")
        second = [event for event in self.notified_events() if event != "runner_started"]
        self.assertEqual(first, second, "同原因重啟不應再發通知")

    def test_pending_entry_still_runs_check_only_guards_the_completion_exit(self):
        """還有 pending 的 entry 可跑時不在完成出口：照常取件，不因別的 entry 缺 last_commit 提早暫停（檢查只守「宣告完成」）。"""
        set_entries(self.config, [entry_spec("a", None), entry_spec("p", None, status="pending")])
        self.restart()
        self.assertEqual(self.mocks["process_one_entry"].call_count, 1)
        self.assertNotEqual(self.runner_state().get("reason"), DONE_MISSING_COMMIT_REASON)

    def test_stalled_queue_is_not_reported_as_complete_or_as_this_pause(self):
        """有 blocked 的 entry（佇列停滯、不是完成）：走既有的 queue_stalled，不是這個暫停原因（完成出口以外不歸這個檢查管）。"""
        set_entries(self.config, [entry_spec("a", None), entry_spec("b", None, status="blocked")])
        self.assertEqual(self.restart(), runner.EXIT_OK)
        self.assertIn("queue_stalled", self.notified_events())
        self.assertNotIn(QUEUE_COMPLETE_EVENT, self.notified_events())

    def test_helper_reports_only_unstamped_done_entries_with_unreadable_titles(self):
        """done_title_problem：只看「done、沒蓋章」的 entry；缺 last_commit（None 或空字串）與「有值但讀不到」都算問題，
        訊息只列有問題的 entry id；都讀得到或沒有涵蓋的 entry 回 None；不改傳入的 queue。
        """
        # STEP 01: 一個正常、兩個缺值、一個有值但不存在的 commit，另有已蓋章與非 done 的（都不該被列）
        queue = {
            "modules": [
                entry_spec("ok", self.sha),
                entry_spec("none", None),
                entry_spec("empty", ""),
                entry_spec("ghost", "0" * 40),
                entry_spec("stamped", None, checkpoint_id="auto-1"),
                entry_spec("pending", None, status="pending"),
            ]
        }
        before = json.dumps(queue, sort_keys=True)
        # STEP 02: 問題描述列出三個有問題的，不列其他三個
        problem = runner.done_title_problem(self.config, queue)
        for broken in ("none", "empty", "ghost"):
            self.assertIn(broken, problem)
        for fine in ("ok", "stamped", "pending"):
            self.assertNotIn(fine, problem)
        self.assertEqual(json.dumps(queue, sort_keys=True), before)
        # STEP 03: 都讀得到、沒有涵蓋的 entry、空 queue：回 None
        self.assertIsNone(runner.done_title_problem(self.config, {"modules": [entry_spec("ok", self.sha)]}))
        self.assertIsNone(runner.done_title_problem(self.config, {"modules": [entry_spec("stamped", None, checkpoint_id="auto-1")]}))
        self.assertIsNone(runner.done_title_problem(self.config, {}))


class PrCreateTitleTest(unittest.TestCase):
    """titles 真的傳給 `gh pr create`：頁面 PR（push_branch_and_open_pr）與斷點 PR（open_checkpoint）。"""

    def setUp(self):
        """每個測試一組全新的 git 環境，並把 commit 標題換成真實格式。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = build_fixture(self.tmp.name)
        self.config = self.fixture["config"]
        self.work = self.config["repo_dir"]
        run_git(self.work, "commit", "--amend", "-m", REAL_SUBJECT)
        self.entry = dict(self.fixture["entry"])

    def capture_pr_create_titles(self, call):
        """執行 call()，回傳期間所有 `gh pr create` 的 --title 值（呼叫照常轉給真的 run_command）。"""
        titles = []
        real_run_command = runner.run_command

        def wrapper(args, *rest, **kwargs):
            if "create" in args and "--title" in args:
                titles.append(args[args.index("--title") + 1])
            return real_run_command(args, *rest, **kwargs)

        with mock.patch.object(runner, "run_command", wrapper):
            call()
        return titles

    def test_entry_pr_title_is_commit_subject(self):
        """頁面 PR 的標題是 entry 分支 commit 的標題，不再是「<jira> R18 升級: <id>」。"""
        titles = self.capture_pr_create_titles(lambda: runner.push_branch_and_open_pr(self.config, self.entry))
        self.assertEqual(titles, [REAL_SUBJECT])

    def test_auto_checkpoint_title_is_commit_subject(self):
        """auto 斷點 PR 的標題是它涵蓋的 entry 的 commit 標題，不再是「R18 遷移自動斷點（…）」。"""
        # 整合分支（本機）前進一個 commit（e1 的），e1 標成 done、還沒蓋章
        run_git(self.work, "checkout", INTEGRATION_BRANCH)
        run_git(self.work, "merge", "--ff-only", ENTRY_BRANCH)
        set_entries(self.config, [entry_spec("e1", run_git(self.work, "rev-parse", "HEAD"))])
        self.config.setdefault("base_branch", INTEGRATION_BRANCH)
        titles = self.capture_pr_create_titles(
            lambda: runner.open_checkpoint(self.config, "auto-test", auto_title="R18 遷移自動斷點（累積 1 個模組未進斷點）")
        )
        self.assertEqual(titles, [REAL_SUBJECT])
        checkpoint = runner.find_checkpoint(runner.load_queue(self.config), "auto-test")
        self.assertEqual(checkpoint["title"], REAL_SUBJECT)

    def test_previous_checkpoint_closed_does_not_leak_into_title(self):
        """前一個斷點被關閉不合併（commit 還在整合分支上、不在 pr_base）：新斷點標題只看自己涵蓋的 entry。

        2026-10-19 #11364 的真實情境：用 `origin/<pr_base>..<tip>` 的 git 範圍會把前一個模組的 commit 也算進來，
        標題變成前一個模組。
        """
        run_git(self.work, "checkout", INTEGRATION_BRANCH)
        add_commit(self.work, "closed.js", OLD_SUBJECT)
        old_sha = run_git(self.work, "rev-parse", "HEAD")
        add_commit(self.work, "current.js", REAL_SUBJECT)
        new_sha = run_git(self.work, "rev-parse", "HEAD")
        set_entries(self.config, [entry_spec("old", old_sha, checkpoint_id="auto-closed"), entry_spec("e1", new_sha)])
        self.config.setdefault("base_branch", INTEGRATION_BRANCH)
        # 對照組：舊做法（git 範圍）在這個拓撲下確實會取到前一個模組，證明這個測試有能力抓到那個缺陷
        range_title = runner.pr_title_from_commits(self.config, "origin/%s" % INTEGRATION_BRANCH, INTEGRATION_BRANCH)
        self.assertEqual(range_title, OLD_SUBJECT + runner.PR_TITLE_MORE_COMMITS_SUFFIX % 2)
        titles = self.capture_pr_create_titles(lambda: runner.open_checkpoint(self.config, "auto-test", auto_title="舊 auto 標題"))
        self.assertEqual(titles, [REAL_SUBJECT])


    def land_e1_on_integration(self, entry_id="e1", last_commit="HEAD"):
        """整合分支（本機）前進到 e1 的 commit，queue 只有一個 done、沒蓋章的 e1；last_commit 傳 None 模擬欄位遺失。"""
        run_git(self.work, "checkout", INTEGRATION_BRANCH)
        run_git(self.work, "merge", "--ff-only", ENTRY_BRANCH)
        sha = run_git(self.work, "rev-parse", "HEAD") if last_commit == "HEAD" else last_commit
        set_entries(self.config, [entry_spec(entry_id, sha)])
        self.config.setdefault("base_branch", INTEGRATION_BRANCH)

    def test_page_pr_title_failure_returns_error_and_does_not_create(self):
        """B7：頁面 PR 的標題取不到（範圍內沒有 commit）：回 (None, 錯誤)、不呼叫 `gh pr create`，走呼叫端既有的 pr_error 路徑。"""
        entry = dict(self.entry, branch=INTEGRATION_BRANCH)
        results = []
        titles = self.capture_pr_create_titles(lambda: results.append(runner.push_branch_and_open_pr(self.config, entry)))
        self.assertEqual(titles, [])
        pr_url, pr_error = results[0]
        self.assertIsNone(pr_url)
        self.assertIn("PR 標題", pr_error)
        self.assertIn("沒有 commit", pr_error)

    def test_auto_checkpoint_with_broken_covered_entry_raises_before_write_ahead(self):
        """B7：auto 斷點涵蓋的 done entry 沒有 last_commit：open_checkpoint 拋例外（走 cmd_run 的 crash 流程暫停）。

        不開 PR、不寫 write-ahead（queue 沒有這個斷點）、entry 不蓋章。
        """
        self.land_e1_on_integration(last_commit=None)
        with self.assertRaises(RuntimeError) as ctx:
            runner.open_checkpoint(self.config, "auto-test", auto_title="舊 auto 標題")
        self.assertIn("沒有 last_commit", str(ctx.exception))
        queue = runner.load_queue(self.config)
        self.assertIsNone(runner.find_checkpoint(queue, "auto-test"))
        self.assertIsNone(queue["modules"][0].get("checkpoint_id"))
        # 沒走到 gh pr create（例外在標題階段就拋了）
        self.assertEqual(self.gh_create_count(), 0)

    def test_declared_hard_checkpoint_stays_pending_when_title_data_broken(self):
        """B7：宣告的 hard 斷點（pending）遇到標題資料異常：例外往外拋、斷點維持 pending，人工閘門不會因此消失或被標成 failed。"""
        self.land_e1_on_integration(last_commit=None)

        def declare(queue):
            """宣告一個 hard 斷點（pending）。"""
            queue["checkpoints"] = [
                dict(runner.CHECKPOINT_FIELD_DEFAULTS, id="hard-test", after={"wave": 0}, mode="hard", pr_base=INTEGRATION_BRANCH, status="pending")
            ]

        runner.mutate_queue(self.config, declare)
        with self.assertRaises(RuntimeError):
            runner.open_checkpoint(self.config, "hard-test")
        checkpoint = runner.find_checkpoint(runner.load_queue(self.config), "hard-test")
        self.assertEqual(checkpoint["status"], "pending")
        self.assertEqual(self.gh_create_count(), 0)

    def test_zero_covered_declared_checkpoint_still_opens_with_default_title(self):
        """沒有涵蓋的 entry 不是資料異常（entry 已被前一個斷點蓋章）：斷點照開，標題用呼叫端給的預設，不拋例外。"""
        run_git(self.work, "checkout", INTEGRATION_BRANCH)
        run_git(self.work, "merge", "--ff-only", ENTRY_BRANCH)
        set_entries(self.config, [entry_spec("e1", run_git(self.work, "rev-parse", "HEAD"), checkpoint_id="auto-closed")])
        self.config.setdefault("base_branch", INTEGRATION_BRANCH)
        titles = self.capture_pr_create_titles(lambda: runner.open_checkpoint(self.config, "auto-test", auto_title="預設標題-無涵蓋"))
        self.assertEqual(titles, ["預設標題-無涵蓋"])

    def gh_create_count(self):
        """假 gh 的呼叫紀錄檔裡 `pr create` 的次數；檔案不存在代表 gh 一次都沒被呼叫。"""
        # STEP 01: 與 DoneMissingCommitRestartTest 共用同一個計數函式
        return count_gh_creates(self.fixture)


if __name__ == "__main__":
    unittest.main()
