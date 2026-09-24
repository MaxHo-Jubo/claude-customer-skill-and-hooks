"""scan_commits_luna.py 的測試：用真的臨時 git repo（bare origin + 工作 repo），不 mock git。

腳本在 cwd 的 repo 上跑：先把本地 release fast-forward 到 origin/release，只看 release 分支上
作者符合 max[_ ]?ho 的 commit，依改動路徑判 frontend／backend，再用 release 分支上合法格式的
`frontend-vYYYY.MM.DD`／`backend-vYYYY.MM.DD` tag（ancestry）判定是否上架；跨兩個 component 的 issue
兩邊都上架才算候選，否則進 pending；路徑判不出 component 的進 manual_review。

建出的歷史（天數 = 距今幾天；Max = 作者名稱符合 pattern 的各種變體）：
    c0  70  Alice  README                         —
    c1  65  Max    backend   [ABC-9]             tag backend-v2026.07.20（時間窗外，整筆不該出現）
    c2  60  Max    backend   [ABC-6]             （窗外，但 ABC-6 有窗內 commit，完成性判斷要看到它）
    c3  10  Max    frontend  [ABC-6]
    c4   9  Max Ho frontend  [ABC-1]
    c5   8  Max    both      [ABC-2]
    c6   7  Alice  frontend  [ABC-3]             （別人的 commit）
    c7   6  Max    docs/     [ABC-4]             tag frontend-v2026.09.10
    c8   5  Max    frontend  fix pr issues        （沒有 Jira 編號）
    c9   4  Max    frontend  [ABC-8]             tag frontend-v2026.09.16
    c10  3  Max    frontend  [ABC-5]
      s1 側分支（從 c10 分出，不在 release 上）    tag frontend-v2026.09.22
    c11  2  Alice  frontend  chore                tag frontend-v2026.09.23-test／frontend-v20260923／backend-v2026.09.23.1
推上 origin 之後把本地 release 退回 c9（落後 origin 兩個 commit），停在 master 上跑腳本。

執行方式（在 skill 根目錄）：
    python3 -B -m unittest discover -s tests -v
"""

import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

# 受測腳本的路徑（skill 根目錄下）
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scan_commits_luna.py")
# 腳本整體執行的上限（秒）：超過代表卡住（例如 git 在等輸入），測試判定失敗而不是跟著卡
SCRIPT_TIMEOUT_SECONDS = 60
# 掃描的時間窗（週）：窗內是 10 天內的 commit，窗外是 60 天以上的
SCAN_WEEKS = 2
# commit 時間用的時區：固定 +08:00，腳本輸出的 iso 字串才能逐字比對
COMMIT_TZ = datetime.timezone(datetime.timedelta(hours=8))
# 作者身分：名稱／email 各一種符合 max[_ ]?ho 的變體，以及一個不符合的
MAX_UNDERSCORE = ("Max_Ho", "max_ho@example.invalid")
MAX_SPACE = ("Max Ho", "maxho@eng-mac.example.invalid")
OTHER_AUTHOR = ("Alice", "alice@example.invalid")
# 隔離使用者的全域／系統 git 設定（hooksPath、簽章等），fixture 的 commit 與腳本裡的 git 都照同一份環境跑
GIT_ISOLATION_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git_env(extra=None):
    """組出跑 git 用的環境變數：目前環境 + 隔離設定 + 呼叫端補的欄位。

    @param extra 要再蓋上的欄位（dict）或 None
    @return dict
    """
    # STEP 01: 不改到 os.environ 本身
    return {**os.environ, **GIT_ISOLATION_ENV, **(extra or {})}


def run_git(cwd, *args, env=None):
    """在指定目錄跑 git，失敗直接拋例外（fixture 不容許靜默失敗）。

    @param cwd 執行目錄
    @param args git 子命令與參數
    @param env 額外環境變數或 None
    @return stdout 去頭尾空白
    """
    # STEP 01: check=True 讓前置步驟失敗時測試直接報錯
    result = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, check=True,
                            env=git_env(env), timeout=SCRIPT_TIMEOUT_SECONDS)
    return result.stdout.strip()


def iso_days_ago(days):
    """回傳距今 days 天、時區 +08:00、精確到秒的 ISO 8601 字串（git 的 iso-strict 會原樣印回來）。

    @param days 距今天數（可為小數）
    @return str
    """
    # STEP 01: 秒以下捨去，git 只存到秒
    moment = datetime.datetime.now(COMMIT_TZ).replace(microsecond=0) - datetime.timedelta(days=days)
    return moment.isoformat()


def commit(work, paths, subject, author, days):
    """在目前分支寫入指定檔案並以指定作者、時間 commit。

    @param work 工作 repo
    @param paths 要新增的檔案（相對路徑）
    @param subject commit 訊息
    @param author (名稱, email)
    @param days 距今天數
    @return (commit sha, commit 時間的 iso 字串)
    """
    # STEP 01: 每個檔案寫入唯一內容，確保 commit 真的有改動
    for rel in paths:
        full = os.path.join(work, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write("%s\n" % subject)
    run_git(work, "add", "-A")
    # STEP 02: author 與 committer 用同一個身分與時間（腳本讀 %ct／%cd，--author 比對 author）
    when = iso_days_ago(days)
    identity = {
        "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1], "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": author[0], "GIT_COMMITTER_EMAIL": author[1], "GIT_COMMITTER_DATE": when,
    }
    run_git(work, "commit", "-q", "-m", subject, env=identity)
    return run_git(work, "rev-parse", "HEAD"), when


def run_scan(work, json_out):
    """在 work 裡跑受測腳本（--weeks SCAN_WEEKS --json-out json_out）。

    @param work 工作 repo
    @param json_out 輸出檔路徑
    @return subprocess.CompletedProcess
    """
    # STEP 01: -B 不留 __pycache__；逾時拋 TimeoutExpired、測試失敗
    return subprocess.run(
        [sys.executable, "-B", SCRIPT_PATH, "--weeks", str(SCAN_WEEKS), "--json-out", json_out],
        cwd=work, capture_output=True, text=True, env=git_env(), timeout=SCRIPT_TIMEOUT_SECONDS, check=False,
    )


def load_script_module():
    """以檔案路徑載入受測腳本（不執行 main），用來測模組層的正規式。

    @return module
    """
    # STEP 01: 腳本不在任何套件裡，用 spec_from_file_location 直接載入
    spec = importlib.util.spec_from_file_location("scan_commits_luna_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def by_jira(items):
    """把輸出清單轉成 jira_id → 單筆 的 dict。

    @param items candidates／pending／manual_review 其中一個清單
    @return dict
    """
    # STEP 01: jira_id 在每個清單內唯一
    return {item["jira_id"]: item for item in items}


class ScanReleaseHistoryTest(unittest.TestCase):
    """端到端：依模組說明裡的歷史跑一次腳本，逐類別驗輸出。"""

    @classmethod
    def setUpClass(cls):
        """建 origin 與工作 repo、造出整段歷史、跑一次腳本並讀回 JSON。"""
        # STEP 01: bare origin + 工作 repo，歷史建在 release 分支
        cls.root = tempfile.mkdtemp(prefix="scan-luna-")
        origin = os.path.join(cls.root, "origin.git")
        work = os.path.join(cls.root, "work")
        cls.work = work
        run_git(cls.root, "init", "-q", "--bare", origin)
        run_git(cls.root, "init", "-q", "-b", "master", work)
        run_git(work, "remote", "add", "origin", origin)
        cls.c = {}
        cls.c["c0"] = commit(work, ["README.md"], "init", OTHER_AUTHOR, 70)
        run_git(work, "checkout", "-q", "-b", "release")
        cls.c["c1"] = commit(work, ["backend/a.js"], "[ABC-9] feat(BE): old backend", MAX_UNDERSCORE, 65)
        run_git(work, "tag", "backend-v2026.07.20")
        cls.c["c2"] = commit(work, ["backend/b.js"], "[ABC-6] feat(BE): backend half", MAX_UNDERSCORE, 60)
        cls.c["c3"] = commit(work, ["frontend/b.js"], "[ABC-6] feat(FE): frontend half", MAX_UNDERSCORE, 10)
        cls.c["c4"] = commit(work, ["frontend/c.js"], "[ABC-1] fix(FE): frontend only", MAX_SPACE, 9)
        cls.c["c5"] = commit(work, ["frontend/d.js", "backend/d.js"], "[ABC-2] feat: both sides", MAX_UNDERSCORE, 8)
        cls.c["c6"] = commit(work, ["frontend/e.js"], "[ABC-3] fix(FE): someone else", OTHER_AUTHOR, 7)
        cls.c["c7"] = commit(work, ["docs/f.md"], "[ABC-4] docs: no component", MAX_UNDERSCORE, 6)
        run_git(work, "tag", "frontend-v2026.09.10")
        cls.c["c8"] = commit(work, ["frontend/g.js"], "fix pr issues", MAX_UNDERSCORE, 5)
        cls.c["c9"] = commit(work, ["frontend/h.js"], "[ABC-8] fix(FE): tagged at itself", MAX_UNDERSCORE, 4)
        run_git(work, "tag", "frontend-v2026.09.16")
        cls.c["c10"] = commit(work, ["frontend/i.js"], "[ABC-5] fix(FE): only unofficial tags", MAX_UNDERSCORE, 3)

        # STEP 02: 側分支上的合法格式 tag（不是 release 的祖先），以及 release 上的非正式 tag
        run_git(work, "checkout", "-q", "-b", "side")
        commit(work, ["frontend/j.js"], "side work", OTHER_AUTHOR, 2.5)
        run_git(work, "tag", "frontend-v2026.09.22")
        run_git(work, "checkout", "-q", "release")
        cls.c["c11"] = commit(work, ["frontend/k.js"], "chore: bump", OTHER_AUTHOR, 2)
        for tag in ("frontend-v2026.09.23-test", "frontend-v20260923", "backend-v2026.09.23.1"):
            run_git(work, "tag", tag)

        # STEP 03: 推上 origin，本地 release 退回 c9（落後），停在 master 上（fetch 不能寫入目前分支）
        run_git(work, "push", "-q", "origin", "release", "master")
        run_git(work, "update-ref", "refs/heads/release", cls.c["c9"][0])
        run_git(work, "checkout", "-q", "master")
        cls.origin_release = run_git(origin, "rev-parse", "refs/heads/release")

        # STEP 04: 跑腳本
        cls.json_out = os.path.join(cls.root, "out.json")
        cls.result = run_scan(work, cls.json_out)
        cls.output = json.loads(cls.result.stdout) if cls.result.returncode == 0 else None

    @classmethod
    def tearDownClass(cls):
        """刪掉暫存 repo。"""
        shutil.rmtree(cls.root, True)

    def setUp(self):
        """腳本本身要成功，後面的斷言才有意義。"""
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_candidates_are_exactly_fully_released_issues(self):
        """候選只有 ABC-1、ABC-8；ABC-1 被兩個 tag 包含，取最早的那個。"""
        # STEP 01: 集合
        candidates = by_jira(self.output["candidates"])
        self.assertEqual(sorted(candidates), ["ABC-1", "ABC-8"])

        # STEP 02: ABC-1（作者是「Max Ho」變體）取最早包含它的 frontend-v2026.09.10，日期是 tag 指向的 c7
        first = candidates["ABC-1"]
        tag_time = self.c["c7"][1]
        self.assertEqual(first["release_version"], "2026.09.10")
        self.assertEqual(first["release_datetime_iso"], tag_time)
        self.assertEqual(first["release_date"], tag_time[:10])
        self.assertEqual(first["components"], ["frontend"])
        self.assertEqual(first["commit_hash"], self.c["c4"][0])
        self.assertEqual(first["commit_date"], self.c["c4"][1][:10])
        self.assertEqual([d["release_tag"] for d in first["commits_detail"]], ["frontend-v2026.09.10"])

        # STEP 03: ABC-8 的 tag 就打在它自己身上
        self.assertEqual(candidates["ABC-8"]["release_version"], "2026.09.16")

    def test_cross_component_issue_waits_for_both_tags(self):
        """單一 commit 同時動 frontend／backend：只有 frontend tag 包含它 → pending，卡在 backend。"""
        # STEP 01: 在 pending、不在 candidates
        pending = by_jira(self.output["pending"])
        self.assertNotIn("ABC-2", by_jira(self.output["candidates"]))
        self.assertEqual(pending["ABC-2"]["resolved_components"], ["frontend"])
        self.assertEqual(pending["ABC-2"]["pending_components"], ["backend"])

    def test_old_commit_outside_window_still_blocks_completion(self):
        """ABC-6 窗內只有 frontend commit（已上架），窗外的 backend commit 還沒上架 → 仍是 pending。"""
        # STEP 01: 完成性判斷要看完整歷史，不能被時間窗截斷
        pending = by_jira(self.output["pending"])
        self.assertIn("ABC-6", pending)
        self.assertEqual(pending["ABC-6"]["pending_components"], ["backend"])
        self.assertEqual([d["commit_hash"] for d in pending["ABC-6"]["pending_detail"]], [self.c["c2"][0]])

    def test_tags_off_release_or_malformed_are_ignored(self):
        """ABC-5 只被側分支上的合法 tag 與 release 上的非正式 tag 包含 → 視為沒上架（pending、無已上架 component）。"""
        # STEP 01: 在 pending，且沒有任何 resolved
        pending = by_jira(self.output["pending"])
        self.assertIn("ABC-5", pending)
        self.assertEqual(pending["ABC-5"]["resolved_components"], [])
        self.assertEqual(pending["ABC-5"]["pending_components"], ["frontend"])

    def test_unknown_component_goes_to_manual_review(self):
        """只動到 docs/ 的 commit 判不出 component → manual_review，不進候選也不進 pending。"""
        # STEP 01: 三個清單各查一次
        manual = by_jira(self.output["manual_review"])
        self.assertEqual(sorted(manual), ["ABC-4"])
        self.assertEqual([c["commit_hash"] for c in manual["ABC-4"]["commits"]], [self.c["c7"][0]])
        self.assertNotIn("ABC-4", by_jira(self.output["pending"]))

    def test_other_authors_unticketed_and_out_of_window_issues_are_absent(self):
        """別人的 commit（ABC-3）、時間窗外的 issue（ABC-9）不出現；沒有 Jira 編號的 commit 不產生任何項目。"""
        # STEP 01: 全部輸出的 jira_id 就是預期的那幾個
        seen = [item["jira_id"] for key in ("candidates", "pending", "manual_review") for item in self.output[key]]
        self.assertEqual(sorted(seen), ["ABC-1", "ABC-2", "ABC-4", "ABC-5", "ABC-6", "ABC-8"])

    def test_local_release_is_fast_forwarded_before_scanning(self):
        """本地 release 落後 origin：腳本要先 fast-forward（ABC-5 在落後的那段裡，找得到才代表掃的是新歷史）。"""
        # STEP 01: 本地 release 已對齊 origin
        self.assertEqual(run_git(self.work, "rev-parse", "refs/heads/release"), self.origin_release)
        self.assertIn("ABC-5", by_jira(self.output["pending"]))

    def test_json_out_matches_stdout(self):
        """--json-out 寫的內容與 stdout 相同。"""
        # STEP 01: 兩邊解析後相等
        with open(self.json_out, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), self.output)


class DivergedReleaseTest(unittest.TestCase):
    """本地 release 有 origin 沒有的 commit（已 diverge）：不可覆蓋，腳本要以非零結束、不輸出結果。"""

    def test_diverged_release_aborts(self):
        """fast-forward 不成立就中止。"""
        # STEP 01: origin 與本地各自多一個 commit
        root = tempfile.mkdtemp(prefix="scan-luna-div-")
        self.addCleanup(shutil.rmtree, root, True)
        origin = os.path.join(root, "origin.git")
        work = os.path.join(root, "work")
        run_git(root, "init", "-q", "--bare", origin)
        run_git(root, "init", "-q", "-b", "master", work)
        run_git(work, "remote", "add", "origin", origin)
        commit(work, ["README.md"], "init", OTHER_AUTHOR, 5)
        run_git(work, "checkout", "-q", "-b", "release")
        base = commit(work, ["frontend/a.js"], "[ABC-1] fix(FE): a", MAX_UNDERSCORE, 4)[0]
        remote_only = commit(work, ["frontend/b.js"], "[ABC-2] fix(FE): b", MAX_UNDERSCORE, 3)[0]
        run_git(work, "push", "-q", "origin", "release", "master")
        run_git(work, "reset", "-q", "--hard", base)
        local_only = commit(work, ["frontend/c.js"], "[ABC-3] fix(FE): c", MAX_UNDERSCORE, 2)[0]
        run_git(work, "checkout", "-q", "master")

        # STEP 02: 跑腳本：非零、沒有 JSON、本地 release 沒被改
        result = run_scan(work, os.path.join(root, "out.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("fetch", result.stderr)
        self.assertEqual(run_git(work, "rev-parse", "refs/heads/release"), local_only)
        self.assertNotEqual(local_only, remote_only)


class PatternTest(unittest.TestCase):
    """模組層的 tag 與 Jira 編號正規式。"""

    @classmethod
    def setUpClass(cls):
        """載入腳本模組（不執行 main）。"""
        cls.module = load_script_module()

    def test_tag_pattern_accepts_only_exact_dotted_format(self):
        """只認 frontend-/backend-vYYYY.MM.DD；-test／-2／.1／無點分隔／其他前綴都不認。"""
        # STEP 01: 合法的要解析出 component 與版本
        match = self.module.TAG_RE.match("backend-v2026.09.03")
        self.assertEqual((match.group(1), match.group(2)), ("backend", "2026.09.03"))
        self.assertIsNotNone(self.module.TAG_RE.match("frontend-v2026.12.31"))

        # STEP 02: 非正式與舊格式
        for tag in ("frontend-v2026.09.03-test", "frontend-v2026.09.03-2", "backend-v2026.09.03.1",
                    "frontend-v20260903", "app-v2026.09.03", "frontend-2026.09.03", "frontend-v2026.9.3"):
            with self.subTest(tag=tag):
                self.assertIsNone(self.module.TAG_RE.match(tag))

    def test_jira_pattern_requires_leading_bracket(self):
        """Jira 編號只取 subject 開頭的 [KEY-123]；中間出現的不算。"""
        # STEP 01: 開頭的取得到，其餘取不到
        self.assertEqual(self.module.JIRA_RE.match("[XYZ-7866] fix(App): x").group(1), "XYZ-7866")
        self.assertIsNone(self.module.JIRA_RE.match("fix: follow-up of [ABC-1]"))
        self.assertIsNone(self.module.JIRA_RE.match("Merge pull request #11124 from example-org/master"))


if __name__ == "__main__":
    unittest.main()
