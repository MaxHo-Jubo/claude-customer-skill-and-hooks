"""runner.py 1.1.1 review 修復的回歸測試——合併進整合分支（push 前確認 ff-merge 後的 HEAD、推送失敗與退回本機）。

由原 test_review_fixes.py 依主題拆出（1.1.2 第六批，測試內容逐字搬移；之後依 review 補過註解與具名常數，斷言未變）；
共用的 fixture 與小工具在 review_fixtures.py。
唯一不是逐字搬移的地方：`_git_with_failure` 的本體搬到 review_fixtures.git_with_failure（另外兩個檔也要用），類別內留別名。
每一組對應一個 review 確認過的缺陷。外部狀態一律用真的：行程與 process group、flock、
git（bare 遠端＋工作 repo，含用 pre-receive hook 造出來的推送失敗）、一支會留紀錄的假 gh。
mock 只用在三種地方：
(1) 測試裡造不出來的事件——斷電（只驗 fsync／replace 的呼叫順序）、訊號剛好落在某一行；
(2) 注入失敗——R15 原檔讀取失敗、合併失敗、合併當下 entry 被人從 queue 移除；
(3) 隔離與受測行為無關的副作用——通知、進度報表、診斷包、crash 流程。

執行方式（在 skill 根目錄）：
    python3 -B -m unittest discover -s helpers/tests -v
只跑這個檔：
    python3 -B -m unittest discover -s helpers/tests -p test_merge_integration.py -v

`-B` 與下方的 `sys.dont_write_bytecode` 是為了不在 skill 目錄留下 __pycache__。
"""

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
    FULL_SHA_CHARS,
    GIT_FATAL_EXIT_CODE,
    SHA_PREFIX_CHARS,
    IMPOSSIBLE_SHA,
    INTEGRATION_BRANCH,
    ENTRY_BRANCH,
    R15_RELATIVE_PATH,
    run_git,
    reject_entry_branch_push,
    build_fixture,
    remote_tip,
    git_with_failure,
)

# merge_to_integration 依序讀 HEAD 的次數編號：第 1 次合併前、第 2 次合併後、第 3 次是 reset 之前的再確認
# 合併後那一次（第 2 次）
POST_MERGE_HEAD_READ = 2
# reset 之前再確認的那一次（第 3 次）；替身在這一次換掉回傳值，斷言也以它核對確實讀到這一次
PRE_RESET_HEAD_READ = 3
# 整合分支推送的 git 參數前綴（替身以它辨認推送那一次呼叫）
INTEGRATION_PUSH_ARGS = ("push", "origin", INTEGRATION_BRANCH)


class MergeToIntegrationTest(unittest.TestCase):
    """C3：push 之前要確認 ff-merge 後的 HEAD 就是預期的 entry commit。"""

    def test_head_mismatch_refuses_to_push(self):
        """HEAD 與預期不符：回報 integration_mismatch（呼叫端據此鎖定），遠端整合分支不動。"""
        # STEP 01: 給一個不可能相符的預期值
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-"))
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], IMPOSSIBLE_SHA)

        # STEP 02: 拒絕推送
        self.assertEqual(result, "integration_mismatch", detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])

    def test_head_mismatch_resets_local_integration_branch(self):
        """HEAD 與預期不符時，本機整合分支要退回合併前的 commit，不能停在那個非預期的 commit 上。

        ff-merge 已經把本機分支往前推了；只回報不推送的話，本機領先遠端、下一次 --ff-only 同步是
        no-op，後面的 entry 會從那個 commit 切分支、最後把它推上去。退回成功的結果值是
        integration_mismatch，與一般 diverged 分開——呼叫端對它要鎖定。
        """
        # STEP 01: 預期值取 collect 當下的 entry commit，之後 entry 分支又多了一個 commit（殘留行程還在改 repo 的情境）
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-reset-"))
        work = fixture["config"]["repo_dir"]
        with open(os.path.join(work, "late.js"), "w", encoding="utf-8") as handle:
            handle.write("// committed after closing data was collected\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "late commit")
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 拒絕推送，而且本機整合分支回到基線
        self.assertEqual(result, "integration_mismatch", detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"], detail)

    def _mismatch_fixture(self):
        """建一組「collect 之後 entry 分支又多了一個 commit」的環境，回傳 (fixture, 那個晚到的 commit sha)。"""
        # STEP 01: fixture＋晚到的 commit
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-unrec-"))
        work = fixture["config"]["repo_dir"]
        with open(os.path.join(work, "late.js"), "w", encoding="utf-8") as handle:
            handle.write("// late\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "late commit")
        return fixture, run_git(work, "rev-parse", "HEAD")

    # 本體在 review_fixtures.git_with_failure（拆檔時搬出：別的測試檔也要用，又不能 import 這個 TestCase 以免重複收集）
    _git_with_failure = staticmethod(git_with_failure)

    def test_reset_failure_is_reported_as_unrecovered(self):
        """mismatch 且 reset 失敗：結果要是 integration_unrecovered（呼叫端據此鎖定），不能只是 detail 裡一句「請人工處理」。"""
        # STEP 01: 注入 reset --keep 中止（仿真 git 的兩行輸出：第一行點名哪個檔 not uptodate、第二行 fatal 帶 40 字元 sha；
        # 路徑取長的，總長超過 200，取尾端就會把檔名切掉——第十六輪實測 git 就是這樣印的）
        fixture, _late = self._mismatch_fixture()
        long_path = "src/containers/Form/Calendar/ServiceTime/SeparateStartDate/Modal/CalendarServiceTimeSeparateStartDateModal/index.js"
        git_error = "error: Entry '%s' not uptodate. Cannot merge.\nfatal: Could not reset index file to revision '%s'." % (long_path, "f" * FULL_SHA_CHARS)
        # 門檻是改前「取尾端」的摘要長度（runner.STDERR_EXCERPT_CHARS）：超過它，只取尾端就看不到第一行
        self.assertGreater(len(git_error), runner.STDERR_EXCERPT_CHARS, "前置條件：錯誤要長到取尾端會切掉第一行")
        fake_git = self._git_with_failure(("reset", "--keep"), (GIT_FATAL_EXIT_CODE, "", git_error))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 結果值本身要能區分「沒退回」；detail 要帶合併前的 HEAD（人工退回時要知道退到哪，diagnostics 不收 git 狀態）、
        # 要點名是哪個檔讓 --keep 中止（取第一行，不是尾端）
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn("error: Entry 'src/containers", detail)
        self.assertIn("reset --keep", detail)
        self.assertIn(fixture["base_sha"][:SHA_PREFIX_CHARS], detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])

    def test_head_off_integration_branch_skips_reset(self):
        """mismatch 時 HEAD 已不在整合分支上（別的東西切走了）：不可以 reset（會打到別人的分支），回 unrecovered。"""
        # STEP 01: 讓「現在在哪個分支」回別的名字
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        fake_git = self._git_with_failure(("symbolic-ref", "--short", "HEAD"), (0, "someone-else\n", ""))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 沒 reset（本機整合分支仍停在晚到的 commit）、結果是 unrecovered、detail 說了在哪、帶合併前的 HEAD
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn("someone-else", detail)
        self.assertIn(fixture["base_sha"][:SHA_PREFIX_CHARS], detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)

    def test_dirty_tree_at_mismatch_skips_reset(self):
        """mismatch 時已追蹤檔有未提交變更：reset --hard 會把別人留下的東西無聲抹掉，所以不 reset、把清單留在 detail、回 unrecovered。"""
        # STEP 01: 改一個已追蹤檔、不提交（真的髒，不 mock）
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        dirty_path = os.path.join(work, R15_RELATIVE_PATH)
        with open(dirty_path, "a", encoding="utf-8") as handle:
            handle.write("// someone was here\n")
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 變更還在、分支沒動、detail 點名那個檔、帶合併前的 HEAD
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn(R15_RELATIVE_PATH, detail)
        self.assertIn(fixture["base_sha"][:SHA_PREFIX_CHARS], detail)
        with open(dirty_path, "r", encoding="utf-8") as handle:
            self.assertIn("someone was here", handle.read())
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)

    def test_dirty_list_shows_first_lines_and_total(self):
        """髒污清單超過預覽行數：detail 列前幾個檔名＋總數，不是尾端截斷（通知會再截尾，前幾行才是有用的）。"""
        # STEP 01: 比預覽行數多兩個的已追蹤檔——先加在整合分支、entry 分支 rebase 上去（兩邊內容相同，
        # checkout 才會把未提交的修改帶著走），然後全部改一次不提交；不符用不可能的預期值造
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-dirty-list-"))
        work = fixture["config"]["repo_dir"]
        names = ["dirty-%d.js" % index for index in range(runner.DIRTY_LIST_PREVIEW_LINES + 2)]
        run_git(work, "checkout", INTEGRATION_BRANCH)
        for name in names:
            with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
                handle.write("// tracked\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "tracked files")
        run_git(work, "checkout", ENTRY_BRANCH)
        run_git(work, "rebase", INTEGRATION_BRANCH)
        for name in names:
            with open(os.path.join(work, name), "a", encoding="utf-8") as handle:
                handle.write("// modified\n")
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], IMPOSSIBLE_SHA)

        # STEP 02: 前幾個在、最後一個不在、總數在
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn(names[0], detail)
        self.assertNotIn(names[-1], detail)
        self.assertIn("共 %d" % len(names), detail)

    def test_untracked_file_does_not_block_reset(self):
        """mismatch 時只有未追蹤檔：reset --hard 不會動它們，所以照樣退回；清單另附進 detail 給人看。"""
        # STEP 01: 工作樹留一個未追蹤檔
        fixture, _late = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        with open(os.path.join(work, "leftover-evidence.txt"), "w", encoding="utf-8") as handle:
            handle.write("someone was here\n")
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 退回了、檔案還在、detail 點名那個檔
        self.assertEqual(result, "integration_mismatch", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"])
        self.assertTrue(os.path.exists(os.path.join(work, "leftover-evidence.txt")))
        self.assertIn("leftover-evidence.txt", detail)

    def test_status_failure_is_reported_distinctly(self):
        """mismatch 時 git status 本身失敗：不能歸成「工作樹不乾淨」，要說是 status 失敗、帶它的錯誤，而且不 reset。"""
        # STEP 01: 注入 status 失敗
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        fake_git = self._git_with_failure(("status", "--porcelain"), (GIT_FATAL_EXIT_CODE, "", "simulated status failure"))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: unrecovered、原因說對（不是「有東西會被抹掉」那一種）、沒 reset
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn("simulated status failure", detail)
        self.assertNotIn("reset --hard 會抹掉", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)

    def test_tracked_change_after_status_check_is_not_wiped(self):
        """status 看到乾淨之後、reset 之前有人改了已追蹤檔（它在合併前後兩個 commit 之間有差）：不可以抹掉，回 unrecovered。

        這個函式正是在「可能有別的寫入者」時被呼叫的，status 與 reset 之間的窗不是純理論；reset --hard 會無條件
        覆寫工作樹，改用 reset --keep——要覆寫的檔有本機修改就整個中止。
        """
        # STEP 01: 包住 status：照真的跑、回真的結果，但回傳前先改 late.js（合併後 HEAD 有、合併前沒有的檔）
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        late_path = os.path.join(work, "late.js")
        # 被替換前的 runner.git，替身照常轉給它
        real_git = runner.git

        def fake_git(config, *args, **kwargs):
            """status 剛回報乾淨就有人寫檔。

            @param config runner 設定（原樣轉給真的 git）
            @param args git 子命令與參數
            @param kwargs 其餘關鍵字參數（原樣轉給真的 git）
            @return 真的 git 的 (code, out, err)
            """
            # STEP 01: 照常執行；是 status 的話，回傳前改 late.js
            result = real_git(config, *args, **kwargs)
            if tuple(args[:2]) == ("status", "--porcelain"):
                with open(late_path, "a", encoding="utf-8") as handle:
                    handle.write("// written by someone else right after the status check\n")
            return result

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 沒退回、對方的修改還在
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)
        with open(late_path, "r", encoding="utf-8") as handle:
            self.assertIn("written by someone else", handle.read())

    def test_head_changed_between_check_and_reset_skips_reset(self):
        """symbolic-ref／status 檢查之後、reset 之前 HEAD 又變了：不 reset（會抹掉那個新 commit），回 unrecovered。

        不符的前提就是「有別的東西在改 repo」，檢查與 reset 之間它可能再 commit 一次；reset 之前要再比一次 HEAD。
        """
        # STEP 01: 第三次 rev-parse HEAD（前兩次是合併前後的正常讀取）回一個別的 sha
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        # 被替換前的 runner.git，非攔截的呼叫轉給它
        real_git = runner.git
        # 每一次 rev-parse HEAD 的參數，依呼叫順序；長度就是「這是第幾次讀 HEAD」
        head_reads = []

        def fake_git(config, *args, **kwargs):
            """第三次讀 HEAD 時假裝有人又動了它。

            @param config runner 設定（原樣轉給真的 git）
            @param args git 子命令與參數
            @param kwargs 其餘關鍵字參數（原樣轉給真的 git）
            @return (code, out, err)：第 PRE_RESET_HEAD_READ 次讀 HEAD 回 IMPOSSIBLE_SHA，其餘是真的 git 的結果
            """
            # STEP 01: 記錄讀 HEAD 的次數，到 reset 前那一次換掉回傳值
            if tuple(args) == ("rev-parse", "HEAD"):
                head_reads.append(args)
                if len(head_reads) == PRE_RESET_HEAD_READ:
                    return 0, IMPOSSIBLE_SHA + "\n", ""
            # STEP 02: 其餘照常
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 前置條件：確實讀了三次；結果 unrecovered、沒 reset
        self.assertEqual(len(head_reads), PRE_RESET_HEAD_READ, "reset 之前應該再讀一次 HEAD")
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn(IMPOSSIBLE_SHA, detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)

    def test_push_failure_restores_local_branch_and_stays_retryable(self):
        """ff-merge 成功但推送失敗：本機整合分支要退回合併前，結果是 integration_push_failed（可重試），entry 分支的 commit 還在。

        不退回的話本機領先遠端，下一輪前置作業會判成 integration_local_ahead 並鎖定——一次網路抖動
        就要人工介入；退回之後重跑：l1_verify 看得到 entry 分支相對整合分支的新 commit、PR 沿用、再 ff-merge 再推。
        結果值與一般 diverged 分開：呼叫端要對它帶簽名，連續第二次才鎖定。
        """
        # STEP 01: 遠端只拒絕整合分支（真的 pre-receive hook）
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-pushfail-"))
        work = fixture["config"]["repo_dir"]
        reject_entry_branch_push(fixture["remote"], branch=INTEGRATION_BRANCH)
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: push_failed、本機退回基線、遠端沒動、entry 分支還在原處
        self.assertEqual(result, "integration_push_failed", detail)
        self.assertIn("pre-receive hook declined", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"], detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])
        self.assertEqual(run_git(work, "rev-parse", ENTRY_BRANCH), fixture["entry_sha"])

    def test_push_reported_failed_but_remote_updated_counts_as_done(self):
        """git push 回非零（逾時、連線在回報前斷掉）但遠端其實已是預期的 commit：要當成 done，不退回、不暫停。

        退回的話本機退到合併前、遠端已前進、tip 沒記，下一輪前置作業 STEP 03 判成「遠端整合分支 tip
        與記錄值不同」——文件定義的「有別人動了整合分支」，實際是 runner 自己，而且同原因重複暫停不通知。
        """
        # STEP 01: push 真的執行、然後假裝失敗
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-pushlie-"))
        work = fixture["config"]["repo_dir"]
        # 被替換前的 runner.git，替身照常轉給它
        real_git = runner.git

        def fake_git(config, *args, **kwargs):
            """推送照做，回報改成失敗。

            @param config runner 設定（原樣轉給真的 git）
            @param args git 子命令與參數
            @param kwargs 其餘關鍵字參數（原樣轉給真的 git）
            @return (code, out, err)：整合分支推送那次回逾時退出碼，其餘是真的 git 的結果
            """
            # STEP 01: 照常執行；是整合分支推送的話，把結果換成 run_command 的逾時
            result = real_git(config, *args, **kwargs)
            if tuple(args[: len(INTEGRATION_PUSH_ARGS)]) == INTEGRATION_PUSH_ARGS:
                return runner.COMMAND_TIMEOUT_CODE, "", "simulated timeout after the push landed"
            return result

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: done、遠端與本機都在 entry commit、detail 說明推送回報失敗但遠端已對
        self.assertEqual(result, "done", detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["entry_sha"])
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["entry_sha"])
        self.assertIn("simulated timeout", detail)

    def test_push_failure_with_unknown_remote_state_locks_without_restore(self):
        """推送失敗、而且問遠端也失敗：不知道遠端有沒有收到，不可以退回本機、也不可以說可重試——回 unrecovered（呼叫端鎖定），本機留在原處當證據。

        退回的話：遠端其實收到了 → 本機落後、tip 沒記、下一輪 STEP 03 靜默 diverged；說可重試的話：重跑一次完整模組。
        """
        # STEP 01: 遠端拒絕整合分支，ls-remote 也失敗
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-pushunknown-"))
        work = fixture["config"]["repo_dir"]
        reject_entry_branch_push(fixture["remote"], branch=INTEGRATION_BRANCH)
        fake_git = self._git_with_failure(("ls-remote",), (GIT_FATAL_EXIT_CODE, "", "simulated ls-remote failure"))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: unrecovered、本機沒退回（停在 entry commit）、detail 帶錯誤與兩個 sha
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["entry_sha"])
        self.assertIn("simulated ls-remote failure", detail)
        self.assertIn(fixture["entry_sha"], detail)
        self.assertIn(fixture["base_sha"], detail)

    def test_head_unreadable_after_merge_is_not_called_a_change(self):
        """合併後讀不到 HEAD：不 reset、回 unrecovered，訊息要說「讀不到」，不能說「HEAD 又變了」（人會去追不存在的寫入者）。"""
        # STEP 01: 第二次 rev-parse HEAD（合併後那次）失敗，其餘照常
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        # 被替換前的 runner.git，非攔截的呼叫轉給它
        real_git = runner.git
        # 每一次 rev-parse HEAD 的參數，依呼叫順序；長度就是「這是第幾次讀 HEAD」
        head_reads = []

        def fake_git(config, *args, **kwargs):
            """合併後那次讀 HEAD 失敗。

            @param config runner 設定（原樣轉給真的 git）
            @param args git 子命令與參數
            @param kwargs 其餘關鍵字參數（原樣轉給真的 git）
            @return (code, out, err)：第 POST_MERGE_HEAD_READ 次讀 HEAD 回失敗，其餘是真的 git 的結果
            """
            # STEP 01: 記錄讀 HEAD 的次數，合併後那一次回失敗
            if tuple(args) == ("rev-parse", "HEAD"):
                head_reads.append(args)
                if len(head_reads) == POST_MERGE_HEAD_READ:
                    return GIT_FATAL_EXIT_CODE, "", "simulated post-merge failure"
            # STEP 02: 其餘照常
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: unrecovered、沒 reset、措辭對
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)
        self.assertIn("simulated post-merge failure", detail)
        self.assertNotIn("又變了", detail)

    def test_untracked_list_failure_is_said_plainly(self):
        """列未追蹤檔的指令失敗：退回照做（那只是附帶資訊），但說明要寫「清單讀取失敗」，不能跟「沒有未追蹤檔」同形。"""
        # STEP 01: 注入 ls-files 失敗
        fixture, _late = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        fake_git = self._git_with_failure(("ls-files", "--others"), (GIT_FATAL_EXIT_CODE, "", "simulated ls-files failure"))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 退回了、說明帶失敗原因
        self.assertEqual(result, "integration_mismatch", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"])
        self.assertIn("simulated ls-files failure", detail)

    def test_read_head_before_merge_failure_stops_before_merge(self):
        """合併前讀不到 HEAD：不合併（沒有東西可退回），回 integration_diverged，本機分支不動。

        用記錄呼叫的假 git 釘住「沒有跑 merge --ff-only」——只看結果值與分支位置的話，把合併前那次
        讀取刪掉、讓合併後的讀取失敗，結果一樣是 diverged＋分支退回基線，測試照樣綠。
        """
        # STEP 01: 所有 rev-parse HEAD 都失敗，其餘照常，並記下每一次 git 呼叫
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-head-"))
        work = fixture["config"]["repo_dir"]
        # 被替換前的 runner.git，非攔截的呼叫轉給它
        real_git = runner.git
        # 每一次 git 呼叫的參數，依呼叫順序（用來確認沒有跑 merge --ff-only）
        calls = []

        def fake_git(config, *args, **kwargs):
            """記錄後轉發；讀 HEAD 一律失敗。

            @param config runner 設定（原樣轉給真的 git）
            @param args git 子命令與參數
            @param kwargs 其餘關鍵字參數（原樣轉給真的 git）
            @return (code, out, err)：讀 HEAD 一律回失敗，其餘是真的 git 的結果
            """
            # STEP 01: 記錄；讀 HEAD 回失敗，其餘照常
            calls.append(tuple(args))
            if tuple(args) == ("rev-parse", "HEAD"):
                return 1, "", "simulated rev-parse failure"
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 停在合併之前——沒有任何一次 merge --ff-only
        self.assertEqual(result, "integration_diverged", detail)
        self.assertIn("simulated rev-parse failure", detail)
        self.assertEqual([call for call in calls if call[:2] == ("merge", "--ff-only")], [])
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"])


if __name__ == "__main__":
    unittest.main()
