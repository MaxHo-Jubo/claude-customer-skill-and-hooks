"""runner.py 1.1.4 的回歸測試：runner 開的 PR 標題要與 commit 標題逐字相同。

起因（2026-10-19）：斷點 PR #11362 的標題是「R18 遷移自動斷點（累積 1 個模組未進斷點）」，與裡面唯一的 commit
`[CUP-227] feat(FE): 未使用-R18遷移-companydashboard` 對不上，審查者在 PR 清單看不出是哪個模組。
拓撲一律用真的 git（build_fixture 的 bare 遠端＋工作 repo）；`gh pr create` 的參數用包住 run_command 的方式攔截，
因為既有的假 gh 只記子命令、不記 --title。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest helpers.tests.test_pr_title -v
"""

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
    run_git,
)

# build_fixture 的 entry 分支上唯一一個 commit 的標題（fixture 內寫死）
FIXTURE_COMMIT_SUBJECT = "migrate e1"
# 測試用的真實格式 commit 標題（含全形字元與括號，確認逐字照用）
REAL_SUBJECT = "[CUP-227] feat(FE): 未使用-R18遷移-companydashboard"
# 退回舊標題時用的標記字串
FALLBACK_TITLE = "舊標題-fallback"
# 兩個 commit 的 committer 時間（unix 秒）：git 的 raw 日期格式要求至少 9 位數；固定值讓「由舊到新」的排序可重現
OLDER_COMMIT_TIME = 1_700_000_000
NEWER_COMMIT_TIME = 1_800_000_000
# 前一個（被關閉的斷點涵蓋的）模組的 commit 標題
OLD_SUBJECT = "[CUP-227] feat(FE): 未使用-R18遷移-companydashboard"


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
    """pr_title_from_commits：單一 commit 逐字照用、多個加後綴、取不到退回舊標題並留紀錄。"""

    def setUp(self):
        """每個測試一組全新的 git 環境（entry 分支比整合分支多一個 commit）。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = build_fixture(self.tmp.name)
        self.config = self.fixture["config"]
        self.work = self.config["repo_dir"]

    def test_single_commit_title_is_verbatim(self):
        """範圍內只有一個 commit：標題與 commit 標題逐字相同。"""
        title = runner.pr_title_from_commits(self.config, INTEGRATION_BRANCH, ENTRY_BRANCH, FALLBACK_TITLE)
        self.assertEqual(title, FIXTURE_COMMIT_SUBJECT)
        self.assertEqual(read_events_safe(self.config, runner.PR_TITLE_FALLBACK_EVENT), [])

    def test_real_format_subject_is_verbatim(self):
        """真實格式（Jira 編號、全形字、括號）的 commit 標題不被改動。"""
        run_git(self.work, "commit", "--amend", "-m", REAL_SUBJECT)
        title = runner.pr_title_from_commits(self.config, INTEGRATION_BRANCH, ENTRY_BRANCH, FALLBACK_TITLE)
        self.assertEqual(title, REAL_SUBJECT)

    def test_multiple_commits_use_oldest_with_suffix(self):
        """範圍內有多個 commit：取最舊的那個（不是 tip），後面接總數後綴。"""
        add_commit(self.work, "second.js", "second commit")
        add_commit(self.work, "third.js", "third commit")
        title = runner.pr_title_from_commits(self.config, INTEGRATION_BRANCH, ENTRY_BRANCH, FALLBACK_TITLE)
        self.assertEqual(title, FIXTURE_COMMIT_SUBJECT + runner.PR_TITLE_MORE_COMMITS_SUFFIX % 3)

    def test_merge_commits_are_not_counted(self):
        """範圍內的 merge commit（prepare_branch 把整合分支合進來的那種）不算進標題與總數。"""
        run_git(self.work, "checkout", INTEGRATION_BRANCH)
        add_commit(self.work, "other.js", "other entry landed")
        run_git(self.work, "checkout", ENTRY_BRANCH)
        run_git(self.work, "merge", "--no-ff", "--no-edit", INTEGRATION_BRANCH)
        # 整合分支前進後，範圍是 integration..entry：只剩 entry 自己的那個 commit（merge commit 被排除）
        title = runner.pr_title_from_commits(self.config, INTEGRATION_BRANCH, ENTRY_BRANCH, FALLBACK_TITLE)
        self.assertEqual(title, FIXTURE_COMMIT_SUBJECT)

    def test_empty_range_falls_back_and_logs(self):
        """範圍內沒有 commit：退回舊標題，而且留下 pr_title_fallback 事件（不靜默）。"""
        title = runner.pr_title_from_commits(self.config, ENTRY_BRANCH, ENTRY_BRANCH, FALLBACK_TITLE)
        self.assertEqual(title, FALLBACK_TITLE)
        events = read_events(self.config, runner.PR_TITLE_FALLBACK_EVENT)
        self.assertEqual(len(events), 1)
        self.assertIn("範圍內沒有 commit", events[0]["detail"]["reason"])

    def test_bad_ref_falls_back_and_logs(self):
        """git 失敗（ref 不存在）：退回舊標題，事件裡有退出碼。"""
        title = runner.pr_title_from_commits(self.config, "no-such-ref", ENTRY_BRANCH, FALLBACK_TITLE)
        self.assertEqual(title, FALLBACK_TITLE)
        events = read_events(self.config, runner.PR_TITLE_FALLBACK_EVENT)
        self.assertEqual(len(events), 1)
        self.assertIn("git log 失敗", events[0]["detail"]["reason"])


def read_events_safe(config, event):
    """事件檔可能還不存在（沒寫過任何事件）；不存在視為沒有事件。"""
    try:
        return read_events(config, event)
    except FileNotFoundError:
        return []


class PrTitleFromEntryCommitsTest(unittest.TestCase):
    """pr_title_from_entry_commits：只看「done 且還沒蓋章」的 entry 的 last_commit。"""

    def setUp(self):
        """每個測試一組全新的 git 環境。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = build_fixture(self.tmp.name)
        self.config = self.fixture["config"]
        self.work = self.config["repo_dir"]

    def title(self, entries):
        """用指定 entry 清單呼叫 helper。"""
        return runner.pr_title_from_entry_commits(self.config, {"modules": entries}, FALLBACK_TITLE)

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

    def test_missing_last_commit_falls_back_whole_and_logs(self):
        """有一個涵蓋的 entry 沒有 last_commit：整個退回舊標題（不拿剩下的湊），並留事件。"""
        sha = self.fixture["entry_sha"]
        title = self.title([entry_spec("e1", sha), entry_spec("broken", None)])
        self.assertEqual(title, FALLBACK_TITLE)
        events = read_events(self.config, runner.PR_TITLE_FALLBACK_EVENT)
        self.assertEqual(len(events), 1)
        self.assertIn("broken 沒有 last_commit", events[0]["detail"]["reason"])

    def test_unreadable_commit_falls_back_and_logs(self):
        """last_commit 在 repo 裡不存在：退回舊標題並留事件。"""
        title = self.title([entry_spec("e1", "0" * 40)])
        self.assertEqual(title, FALLBACK_TITLE)
        events = read_events(self.config, runner.PR_TITLE_FALLBACK_EVENT)
        self.assertEqual(len(events), 1)
        self.assertIn("讀不到標題", events[0]["detail"]["reason"])

    def test_no_covered_entry_falls_back_and_logs(self):
        """沒有任何涵蓋的 entry：退回舊標題並留事件。"""
        title = self.title([entry_spec("old", self.fixture["entry_sha"], checkpoint_id="auto-closed")])
        self.assertEqual(title, FALLBACK_TITLE)
        events = read_events(self.config, runner.PR_TITLE_FALLBACK_EVENT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["detail"]["reason"], "沒有涵蓋的 entry")


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
        range_title = runner.pr_title_from_commits(self.config, "origin/%s" % INTEGRATION_BRANCH, INTEGRATION_BRANCH, FALLBACK_TITLE)
        self.assertEqual(range_title, OLD_SUBJECT + runner.PR_TITLE_MORE_COMMITS_SUFFIX % 2)
        titles = self.capture_pr_create_titles(lambda: runner.open_checkpoint(self.config, "auto-test", auto_title="舊 auto 標題"))
        self.assertEqual(titles, [REAL_SUBJECT])


if __name__ == "__main__":
    unittest.main()
