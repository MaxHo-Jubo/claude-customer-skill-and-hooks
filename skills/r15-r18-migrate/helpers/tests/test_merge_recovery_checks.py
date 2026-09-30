"""runner.py 1.1.2 第七批項目 2 的回歸測試（R4）：合併記錄與 repo 實況逐項比對，任一項不符就不收拾。

每個測試先造「runner 留下的狀態」（真 cmd_run 跑到準備分支的真衝突、共用收尾換成拋停止訊號），再只動受測的那一個條件，
其餘條件全部維持成立——對照組（test_merge_recovery.py 的 T2.1、本檔的年齡上限內與換回原 repo）證明不動任何條件時會收拾。
不符時的共同要求：repo 原狀（分支、HEAD、MERGE_HEAD 內容、工作樹狀態）、記錄保留、integration_dirty 暫停、細節點名不符的欄位。

時間相關的條件一律做成確定值、不靠 sleep：年齡用「只在收拾那一步換掉 runner 看到的時鐘」；檔案時間用 os.utime 設成
MERGE_HEAD 之後的確定時間。不把整個狀態的檔案時間往前推：工作樹檔案的時間一變，index 裡記的 stat 就對不上，git merge --abort
（reset --merge）會以「not uptodate」拒絕——那是 runner 應有的保守反應，但會讓「其餘條件全成立」的前提不成立。

主流程、記錄讀寫與失敗出口的測試在 test_merge_recovery.py（harness 從那裡匯入）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 480; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_merge_recovery_checks.py -v
"""

import os
import shutil
import sys
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
    ENTRY_ID,
    GIT_FATAL_EXIT_CODE,
    INTEGRATION_BRANCH,
    NOTIFY_MAX_TEXT_CHARS,
    R15_RELATIVE_PATH,
    run_git,
)
from test_merge_recovery import (  # noqa: E402  pylint: disable=wrong-import-position
    CLEARED_EVENT,
    DIRTY_REASON,
    HALTED_EVENT,
    RECOVERED_EVENT,
    MergeRecoveryHarness,
    git_failing,
)
from test_reconcile import events  # noqa: E402  pylint: disable=wrong-import-position
from test_stale_branch import ENTRY_FILE  # noqa: E402  pylint: disable=wrong-import-position

# user 拍板的自動收拾年齡上限（秒；外部契約，不引用 runner 的常數：常數被改掉時測試要紅）
USER_MAX_AGE_SECONDS = 900
# 年齡測試離上限的距離（秒）：大於時間容差，上限的值被改動時兩邊的測試各紅一邊
AGE_MARGIN_SECONDS = 10
# 檔案時間設在 MERGE_HEAD 之後的秒數：大於時間容差（index／工作樹檔案「比 MERGE_HEAD 新」）
NEWER_THAN_MERGE_HEAD_SECONDS = 10
# MERGE_HEAD 時間落在視窗之後的幅度（秒）：超過「記錄時間＋git 逾時」的上緣
WINDOW_MARGIN_SECONDS = 60
# 同 sha 另開的分支名（T2.7）
COPY_BRANCH = "copy"
# 另一個 clone 的目錄後綴（T2.17）
CLONE_SUFFIX = "-clone"
# abort 失敗暫停細節裡給人的步驟：自己 abort（細節開頭「自動收拾中斷的合併時 git merge --abort 失敗」也含指令字樣，所以帶「執行」）
MANUAL_ABORT_STEP = "執行 git merge --abort"
# 暫停細節裡錯誤摘要的開頭：人工步驟要出現在它之前（通知會截尾）
ERROR_PREFIX = "錯誤:"
# 超過年齡上限才移除 index.lock 時，記錄沒被收拾而清掉的原因（R3 的外部契約值）
NO_MERGE_HEAD_REASON = "no_merge_head"
# 對照組：整合分支把基線檔改名後的路徑
RENAMED_PATH = "legacy/renamed.js"
# queue.json 損毀時寫進去的內容（非 UTF-8＋不完整的 JSON）
CORRUPT_QUEUE_BYTES = b"\xff{corrupt"
# queue 損毀期間 launchd 重啟的次數（驗只通知一次）
CORRUPT_QUEUE_RESTARTS = 2
# R6 事後驗證不通過時 merge_recovery_halted 事件的 stage
VERIFY_FAILED_STAGE = "verify_failed"


class MergeIntentCheckTest(MergeRecoveryHarness):
    """T2.5–T2.10、T2.17：只動一個條件，其餘全成立；另有 T2.12 延伸（index.lock 超過年齡上限才移除，要人工 abort）。"""

    def setUp(self):
        """先造 runner 留下的狀態（準備分支合併真衝突時被打斷）。

        @return None
        """
        # STEP 01: harness＋留下的狀態
        super().setUp()
        self.leave_interrupted_merge()

    def restart_at(self, offset):
        """重啟一次；收拾那一步看到的「現在」是記錄寫下的時間＋offset 秒（只在收拾期間換掉 runner 的時鐘）。

        @param offset 記錄寫下之後的秒數
        @return cmd_run 的退出碼
        """
        # STEP 01: 包住真的收拾函式（patch 之前取）
        # 被包住的真收拾函式
        real_recover = runner.recover_interrupted_merge
        # 收拾時的「現在」
        later = self.record()["written_epoch"] + offset

        def recover_later(config):
            """收拾期間 runner 看到的 time.time() 固定是 later。

            @param config runner 設定
            @return 真收拾函式的回傳值
            """
            # STEP 01: 只換 runner 模組的 time
            with mock.patch.object(runner, "time") as fake_time:
                fake_time.time.return_value = later
                return real_recover(config)

        # STEP 02: 重啟
        with mock.patch.object(runner, "recover_interrupted_merge", recover_later):
            return self.run_round("done")

    def refused_after_restart(self, marker, work=None, offset=None):
        """重啟一次，斷言不收拾（見 assert_refused）。

        @param marker 暫停細節裡必須出現的欄位名
        @param work 受測的工作 repo（None 表示這組的 repo）
        @param offset 收拾時的「現在」在記錄寫下之後幾秒（None 表示用真的時鐘）
        @return None
        """
        # STEP 01: 重啟前的狀態、重啟、斷言
        # 重啟前的 repo 狀態
        before = self.snapshot(work)
        # 重啟那一輪的退出碼
        code = self.run_round("done") if offset is None else self.restart_at(offset)
        self.assertEqual(code, runner.EXIT_PAUSED)
        self.assert_refused(before, marker, work)

    def set_newer_than_merge_head(self, path):
        """把檔案的時間設成 MERGE_HEAD 之後 NEWER_THAN_MERGE_HEAD_SECONDS 秒（確定值，不靠 sleep）。

        @param path 檔案路徑
        @return None
        """
        # STEP 01: 以 MERGE_HEAD 為基準
        # 比 MERGE_HEAD 新的時間
        newer = os.stat(self.merge_head_path()).st_mtime + NEWER_THAN_MERGE_HEAD_SECONDS
        os.utime(path, (newer, newer))

    def assert_recovered(self):
        """共同斷言：收拾了、續跑到 entry 的真衝突 blocked。

        @return None
        """
        # STEP 01: 事件、記錄、entry
        self.assertEqual(len(events(self.base_config, RECOVERED_EVENT)), 1, self.paused_details())
        self.assertFalse(os.path.exists(self.record_path))
        self.assertEqual(runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)["status"], "blocked")

    def test_head_moved(self):
        """T2.5：HEAD 不是合併前的 sha（分支 ref 被移走，MERGE_HEAD 還在）→ 不收拾。

        @return None
        """
        # STEP 01: 把 entry 分支移到基線（只改 ref，不碰 index 與工作樹）
        run_git(self.work, "update-ref", "refs/heads/%s" % ENTRY_BRANCH, self.fixture["base_sha"])
        # STEP 02: 重啟
        self.refused_after_restart("head_before")

    def test_target_differs_from_record(self):
        """T2.6：MERGE_HEAD 不是記錄的合併對象 → 不收拾。

        @return None
        """
        # STEP 01: 記錄的合併對象換成另一個真 commit
        self.rewrite_record(target_sha=self.fixture["base_sha"])
        # STEP 02: 重啟
        self.refused_after_restart("target_sha")

    def test_merge_head_with_two_lines(self):
        """T2.6：MERGE_HEAD 不只一行（第一行仍是記錄的對象；rev-parse 只看第一行）→ 不收拾。

        @return None
        """
        # STEP 01: 多寫一行，時間還原（只動內容這一個條件）
        # MERGE_HEAD 原本的時間
        info = os.stat(self.merge_head_path())
        with open(self.merge_head_path(), "a", encoding="utf-8") as handle:
            handle.write(self.fixture["base_sha"] + "\n")
        os.utime(self.merge_head_path(), (info.st_atime, info.st_mtime))
        # STEP 02: 重啟
        self.refused_after_restart("target_sha")

    def test_branch_differs(self):
        """T2.7：HEAD 同一個 sha、但在另一支分支上（MERGE_HEAD 還在）→ 不收拾。

        設計寫的 `git checkout -b copy` 會順手清掉 MERGE_HEAD（git 2.50 實測），造不出這個狀態；改用 branch＋symbolic-ref
        只換 HEAD 指向的分支。

        @return None
        """
        # STEP 01: 同 sha 另開分支、HEAD 指過去
        run_git(self.work, "branch", COPY_BRANCH)
        run_git(self.work, "symbolic-ref", "HEAD", "refs/heads/%s" % COPY_BRANCH)
        # STEP 02: 重啟
        self.refused_after_restart("branch_ref")

    def test_merge_head_mtime_outside_window(self):
        """T2.8：MERGE_HEAD 的時間晚於「記錄時間＋git 逾時」→ 不收拾（往後推，index 與工作樹的比對照樣成立）。

        @return None
        """
        # STEP 01: MERGE_HEAD 的時間移到視窗之後
        # 視窗上緣之外的時間
        late = self.record()["written_epoch"] + runner.GIT_TIMEOUT_SECONDS + WINDOW_MARGIN_SECONDS
        os.utime(self.merge_head_path(), (late, late))
        # STEP 02: 重啟
        self.refused_after_restart("merge_head_mtime")

    def test_age_over_limit(self):
        """T2.9：收拾時記錄已寫下 910 秒（上限 900）→ 不收拾。

        @return None
        """
        # STEP 01: 重啟（收拾時的時鐘在上限之後）
        self.refused_after_restart("age", offset=USER_MAX_AGE_SECONDS + AGE_MARGIN_SECONDS)

    def test_age_within_limit_recovers(self):
        """T2.9 對照組：收拾時記錄寫下 890 秒（上限內）→ 照樣收拾。

        @return None
        """
        # STEP 01: 重啟（收拾時的時鐘在上限之前）
        self.assertEqual(self.restart_at(USER_MAX_AGE_SECONDS - AGE_MARGIN_SECONDS), runner.EXIT_OK)
        # STEP 02: 收拾了
        self.assert_recovered()

    def test_conflict_file_newer_than_merge_head(self):
        """T2.10：衝突檔的時間比 MERGE_HEAD 新（有人在改）→ 不收拾，細節列出那個檔。

        @return None
        """
        # STEP 01: 衝突檔的時間移到 MERGE_HEAD 之後
        self.set_newer_than_merge_head(os.path.join(self.work, ENTRY_FILE))
        # STEP 02: 重啟
        self.refused_after_restart("worktree_mtime")
        self.assertIn(ENTRY_FILE, self.paused_details()[-1])

    def test_deleted_conflict_file_is_left_alone(self):
        """R4：衝突檔被人刪掉（沒 git add，index 時間不變；porcelain 仍顯示 `AA`）→ 不收拾，細節點名那個檔。

        修正前檔案不存在就略過、照樣 abort：人的刪除被還原、記 merge_recovered 不通知（codex 第七批 silent-failure）。
        合併本身讓檔案不存在的情況見 MergeRemovedPathControlTest（對照組，照樣收拾）。

        @return None
        """
        # STEP 01: 刪掉衝突檔
        os.remove(os.path.join(self.work, ENTRY_FILE))
        # STEP 02: 重啟
        self.refused_after_restart("worktree_deleted")
        self.assertIn(ENTRY_FILE, self.paused_details()[-1])

    def test_abort_failed_notice_puts_manual_step_before_lock_path(self):
        """abort 因 index.lock 失敗的通知：人工步驟要排在 index.lock 絕對路徑之前，而且整段落在 notify.sh 的 300 字內。

        stub 驗收實測：路徑排在前面時，repo 路徑一長（約 190 字）「再到 repo 執行 git merge --abort」就被 300 字截斷切掉，
        LINE 收到的通知停在 `.git/ind`。步驟排在路徑前面，路徑再長也擠不掉它。

        @return None
        """
        # STEP 01: 收拾時 abort 撞上真的 index.lock
        with open(os.path.join(self.git_dir, "index.lock"), "w", encoding="utf-8"):
            pass
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # STEP 02: 照 notify.sh 組字（標題一行＋內文）
        # 最後一則暫停通知的標題與內文
        _config, _event, title, body = [call.args for call in self.mocks["notify"].call_args_list if call.args[1] == "paused"][-1]
        # 截斷前的通知全文
        text = "⏸ %s\n%s" % (title, body)
        # STEP 03: 步驟在路徑之前、整段在 300 字內
        # 人工步驟結束的位置
        step_end = text.index(MANUAL_ABORT_STEP) + len(MANUAL_ABORT_STEP)
        self.assertLess(text.index(MANUAL_ABORT_STEP), text.index(os.path.join(self.git_dir, "index.lock")), text)
        self.assertLessEqual(step_end, NOTIFY_MAX_TEXT_CHARS, text)

    def test_corrupt_queue_mismatch_notifies_once(self):
        """queue.json 損毀＋記錄與現況不符：每次重啟都停在收拾，但 integration_dirty 只通知一次。

        queue 讀不到時去重退到第三層（看事件紀錄最後一筆實質事件）。修正前 halt_merge_recovery 先記的 merge_recovery_halted
        不在跳過清單裡，最後一筆永遠是它、判成不重複，launchd 每次重啟（300 秒）都再通知一次（code-review agent 第七批）。

        @return None
        """
        # STEP 01: 記錄的合併對象改成不符；queue 寫壞
        self.rewrite_record(target_sha=self.fixture["base_sha"])
        with open(os.path.join(self.base_config["state_dir"], "queue.json"), "wb") as handle:
            handle.write(CORRUPT_QUEUE_BYTES)
        # STEP 02: 重啟數次：每次都停在收拾
        for _round in range(CORRUPT_QUEUE_RESTARTS):
            self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        self.assertEqual(len(events(self.base_config, HALTED_EVENT)), CORRUPT_QUEUE_RESTARTS)
        # STEP 03: 只通知一次
        self.assertEqual([call.args[1] for call in self.mocks["notify"].call_args_list].count("paused"), 1)

    def restart_with_change_after_abort(self, git_args):
        """重啟一次；收拾的 git merge --abort 真的成功之後，立刻對 repo 做一個變動（工作樹保持乾淨），模擬 abort 與事後驗證之間
        有別的寫入者動了 HEAD 或分支。

        @param git_args abort 成功後要跑的 git 參數
        @return cmd_run 的退出碼
        """
        # STEP 01: 包住真的 git，只在第一次 merge --abort 成功後動手
        # 被替換前的真 git
        real_git = runner.git
        # 是否已經動過手
        done = []

        def change_after_abort(config, *args, **kwargs):
            """第一次 merge --abort 成功後跑 git_args，其餘轉給真的 git。

            @param config runner 設定
            @param args git 參數
            @param kwargs 原樣轉交
            @return 真 git 的 (code, out, err)
            """
            # STEP 01: 先照常執行
            result = real_git(config, *args, **kwargs)
            if args[:2] == ("merge", "--abort") and result[0] == 0 and not done:
                done.append(True)
                run_git(self.work, *git_args)
            return result

        with mock.patch.object(runner, "git", change_after_abort):
            return self.run_round("done")

    def assert_verify_failed(self, marker):
        """共同斷言：R6 事後驗證不通過而暫停——沒有 merge_recovered、沒有呼叫 CLI、細節點名不符的欄位。

        @param marker 暫停細節裡必須出現的欄位名
        @return None
        """
        # STEP 01: 暫停原因與事件
        self.assertEqual(self.runner_state().get("reason"), DIRTY_REASON)
        # 最後一筆不收拾的事件
        halted = events(self.base_config, HALTED_EVENT)[-1]["detail"]
        self.assertEqual(halted["stage"], VERIFY_FAILED_STAGE)
        self.assertIn(marker, halted["detail"])
        self.assertEqual(events(self.base_config, RECOVERED_EVENT), [])
        self.assertEqual(self.mocks["call_claude"].call_count, 0)

    def test_head_moved_after_abort_is_not_recovered(self):
        """R6：收拾前比對全吻合、abort 成功，但 abort 之後 HEAD 被移走（工作樹乾淨）→ 不續跑，以 verify_failed 暫停。

        @return None
        """
        # STEP 01: abort 後把分支連同工作樹移到基線
        self.assertEqual(self.restart_with_change_after_abort(("reset", "-q", "--hard", self.fixture["base_sha"])), runner.EXIT_PAUSED)
        # STEP 02: 斷言
        self.assert_verify_failed("head_before")

    def test_branch_changed_after_abort_is_not_recovered(self):
        """R6：收拾前比對全吻合、abort 成功，但 abort 之後 HEAD 換到另一支分支（同 sha、工作樹乾淨）→ 不續跑，以 verify_failed 暫停。

        @return None
        """
        # STEP 01: abort 後同 sha 開新分支並切過去
        self.assertEqual(self.restart_with_change_after_abort(("checkout", "-q", "-b", COPY_BRANCH)), runner.EXIT_PAUSED)
        # STEP 02: 斷言
        self.assert_verify_failed("branch_ref")

    def test_index_newer_after_git_add(self):
        """T2.10：有人 `git add` 過（index 比 MERGE_HEAD 新）→ 不收拾。

        `git add` 寫 index 的時間離合併可能不到容差（測試跑得快），所以 add 之後把 index 的時間設成確定值。

        @return None
        """
        # STEP 01: 真的 git add 衝突檔（工作樹檔的時間不變），index 的時間移到 MERGE_HEAD 之後
        run_git(self.work, "add", ENTRY_FILE)
        self.set_newer_than_merge_head(os.path.join(self.git_dir, "index"))
        # STEP 02: 重啟
        self.refused_after_restart("index_mtime")

    def test_status_failure_is_mismatch(self):
        """R4：列工作樹路徑的 git status 失敗 → 當成不符，不收拾。

        @return None
        """
        # STEP 01: 只攔 status
        # 注入失敗的 git
        failing = git_failing([("--no-optional-locks", "status")], (GIT_FATAL_EXIT_CODE, "", "fatal: injected status failure"))
        with mock.patch.object(runner, "git", failing):
            self.refused_after_restart("status")

    def test_other_clone_is_left_alone(self):
        """T2.17：repo_dir 換成另一個 clone（狀態一模一樣、路徑不同）→ 兩個 repo 都不動；換回原 repo 才收拾（對照組）。

        @return None
        """
        # STEP 01: 整份複製（copy2 保留時間）、repo_dir 指過去
        # 另一個 clone 的路徑
        clone = self.work + CLONE_SUFFIX
        shutil.copytree(self.work, clone, symlinks=True)
        # STEP 02: 複本的 inode／ctime 都變了，index 記的 stat 對不上（abort 會以 not uptodate 拒絕，repo 不動變成碰巧）：
        # 在複本跑一次會寫回 index 的 status 刷新 stat，再把 index 的時間設回原本的（時間比對照樣成立，只剩 repo 身分不同）
        # 原 repo 的 index 時間
        index_info = os.stat(os.path.join(self.git_dir, "index"))
        run_git(clone, "status", "--porcelain")
        os.utime(os.path.join(clone, ".git", "index"), (index_info.st_atime, index_info.st_mtime))
        # 原 repo 的狀態
        original = self.snapshot()
        self.base_config["repo_dir"] = clone
        # STEP 03: 重啟：不收拾，細節點名 repo 與 git 目錄；原 repo 也沒動
        self.refused_after_restart("repo_real", work=clone)
        self.assertIn("git_dir", self.paused_details()[-1])
        self.assertEqual(self.snapshot(), original)
        # STEP 04: 對照組：換回原 repo 就收拾
        self.base_config["repo_dir"] = self.work
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assert_recovered()

    def test_late_lock_removal_needs_manual_abort(self):
        """T2.12 延伸：abort 因 index.lock 失敗、人超過年齡上限才移除 → 只刪 index.lock 不會自動收拾（age 不符、同原因不再通知），
        所以暫停細節在錯誤摘要之前就要叫人自己 git merge --abort；照做之後重啟清掉記錄、續跑。

        修正前細節只叫人刪 index.lock、「再等 runner 重啟（記錄保留，下次會再試）」：無人看管時超過 15 分鐘才處理是常態，
        照做的人看到的是 runner 靜默停著。

        @return None
        """
        # STEP 01: 收拾時 abort 撞上真的 index.lock → 暫停
        # 殘留的 index.lock
        lock_path = os.path.join(self.git_dir, "index.lock")
        with open(lock_path, "w", encoding="utf-8"):
            pass
        self.assertEqual(self.run_round("done"), runner.EXIT_PAUSED)
        # abort 失敗的暫停細節
        detail = self.paused_details()[-1]
        # STEP 02: 人工 abort 的步驟在錯誤摘要之前
        self.assertIn(MANUAL_ABORT_STEP, detail.split(ERROR_PREFIX)[0], detail)
        # STEP 03: 超過年齡上限才只刪 index.lock → 不收拾（age）、同原因不再通知
        os.remove(lock_path)
        self.refused_after_restart("age", offset=USER_MAX_AGE_SECONDS + AGE_MARGIN_SECONDS)
        self.assertEqual([call.args[1] for call in self.mocks["notify"].call_args_list].count("paused"), 1)
        # STEP 04: 照細節自己 abort 之後重啟：清掉記錄、續跑到 entry 的真衝突
        run_git(self.work, "merge", "--abort")
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assertFalse(os.path.exists(self.record_path))
        self.assertEqual(events(self.base_config, CLEARED_EVENT)[-1]["detail"]["reason"], NO_MERGE_HEAD_REASON)
        self.assertEqual(runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)["status"], "blocked")


class MergeRemovedPathControlTest(MergeRecoveryHarness):
    """對照組：合併本身讓檔案不存在（整合分支刪掉或改名基線檔）時照樣收拾——缺檔只擋「合併動過、卻被人刪掉」的。"""

    def change_on_integration(self, git_args, message):
        """另一個 entry 在整合分支上對基線檔做了變動並推上遠端，queue 的 tip 記錄跟著前進。

        @param git_args 變動用的 git 參數（rm／mv）
        @param message commit 訊息
        @return None
        """
        # STEP 01: commit＋push
        run_git(self.work, "checkout", INTEGRATION_BRANCH)
        run_git(self.work, *git_args)
        run_git(self.work, "commit", "-m", message)
        run_git(self.work, "push", "origin", INTEGRATION_BRANCH)
        # 整合分支的新 tip
        tip = run_git(self.work, "rev-parse", "HEAD")

        # STEP 02: queue 記下新 tip
        def record_tip(queue):
            """mutate_queue 用：整合分支 tip 前進（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue
            @return None
            """
            # STEP 01: 寫 tip
            queue["integration_tip_sha"] = tip

        runner.mutate_queue(self.base_config, record_tip)

    def assert_recovers_with_absent_path(self, status_line):
        """留下中斷的合併（除了衝突檔，還有一個合併本身讓它不存在的基線檔），重啟照樣收拾。

        @param status_line 前置條件：git status 裡那個基線檔應有的那一行
        @return None
        """
        # STEP 01: runner 留下的狀態；前置條件自驗（合併真的讓基線檔不存在、狀態碼如預期）
        self.leave_interrupted_merge()
        self.assertIn(status_line, run_git(self.work, "--no-optional-locks", "status", "--porcelain=v1").splitlines())
        self.assertFalse(os.path.exists(os.path.join(self.work, R15_RELATIVE_PATH)))
        # STEP 02: 重啟：收拾了、續跑到 entry 的真衝突
        self.assertEqual(self.run_round("done"), runner.EXIT_OK)
        self.assertEqual(len(events(self.base_config, RECOVERED_EVENT)), 1, self.paused_details())
        self.assertFalse(os.path.exists(self.record_path))
        self.assertEqual(runner.find_entry(runner.load_queue(self.base_config), ENTRY_ID)["status"], "blocked")

    def test_file_deleted_by_merge_still_recovers(self):
        """整合分支刪掉基線檔：合併把刪除寫進 index（`D `）、檔案不存在 → 照樣收拾。

        @return None
        """
        # STEP 01: 另一個 entry 刪檔
        self.change_on_integration(("rm", "-q", R15_RELATIVE_PATH), "e0 removes legacy file")
        # STEP 02: 收拾
        self.assert_recovers_with_absent_path("D  %s" % R15_RELATIVE_PATH)

    def test_file_renamed_by_merge_still_recovers(self):
        """整合分支改名基線檔：原路徑是改名項目的來源（`R  舊 -> 新`；-z 格式是「新、舊」兩段）、不存在 → 照樣收拾。

        @return None
        """
        # STEP 01: 另一個 entry 改名
        self.change_on_integration(("mv", R15_RELATIVE_PATH, RENAMED_PATH), "e0 renames legacy file")
        # STEP 02: 收拾
        self.assert_recovers_with_absent_path("R  %s -> %s" % (R15_RELATIVE_PATH, RENAMED_PATH))


if __name__ == "__main__":
    unittest.main()
