"""runner.py 1.1.1 review 修復的回歸測試——queue.json 原子寫入與 L1 通過後的發佈段（取收尾資料 → 開 PR → 合併 → 寫回 done、PR 連結判定）。

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
    python3 -B -m unittest discover -s helpers/tests -p test_queue_publish.py -v

`-B` 與下方的 `sys.dont_write_bytecode` 是為了不在 skill 目錄留下 __pycache__。
"""

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

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    SHA_PREFIX_CHARS,
    NOTIFY_MAX_TEXT_CHARS,
    FAKE_PR_URL,
    EXISTING_PR_URL,
    INTEGRATION_BRANCH,
    ENTRY_BRANCH,
    ENTRY_ID,
    R15_RELATIVE_PATH,
    NON_PR_OUTPUTS,
    run_git,
    write_fake_gh,
    reject_entry_branch_push,
    build_fixture,
    remote_tip,
    queue_entry,
    git_with_failure,
)

# 假 CLI 判讀結果的單輪花費（美元）：任意非零值，發佈段只負責原樣累加
ROUND_COST_USD = 0.5


class AtomicWriteTest(unittest.TestCase):
    """C2：queue.json 的寫入順序必須是 fsync 檔案 → replace → fsync 父目錄。"""

    def setUp(self):
        """每個測試一個獨立的狀態目錄。"""
        # STEP 01: 只需要狀態目錄，不需要 git
        self.state_dir = tempfile.mkdtemp(prefix="r18-c2-")
        self.config = {"state_dir": self.state_dir}
        runner.ensure_state_dir(self.config)

    def _record_write_sequence(self, action):
        """執行 action，並記下期間 os.fsync／os.replace 的呼叫順序。

        @param action 無參數的 callable，內部會寫 queue.json
        @return 事件名稱的 list，元素是 "fsync:file"、"fsync:dir"、"replace"
        """
        # STEP 01: 包一層轉發到真正的系統呼叫，順便把事件記到同一個 recorder 上
        # 依呼叫順序收下事件名稱的記錄器
        recorder = mock.Mock()
        # 被替換前的 os.fsync，spy_fsync 記錄後轉發給它（真的落盤）
        real_fsync = os.fsync
        # 被替換前的 os.replace，spy_replace 記錄後轉發給它（真的換檔）
        real_replace = os.replace

        def spy_fsync(fd):
            """依 fd 指向的是不是目錄分類後轉發。

            @param fd 要 fsync 的檔案描述符（檔案或父目錄）
            @return 真的 os.fsync 的回傳值（None）
            """
            # STEP 01: 分類記錄、再轉發
            kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
            recorder("fsync:%s" % kind)
            return real_fsync(fd)

        def spy_replace(source, target):
            """記錄後轉發。

            @param source 暫存檔路徑
            @param target 目標檔路徑（queue.json）
            @return 真的 os.replace 的回傳值（None）
            """
            # STEP 01: 記錄、再轉發
            recorder("replace")
            return real_replace(source, target)

        # STEP 02: 只在 action 期間替換
        with mock.patch.object(runner.os, "fsync", spy_fsync), mock.patch.object(runner.os, "replace", spy_replace):
            action()
        return [call.args[0] for call in recorder.call_args_list]

    def test_write_queue_new_sequence(self):
        """首次建立 queue.json 也要走完整的三步。"""
        # STEP 01: 寫入並比對順序
        sequence = self._record_write_sequence(lambda: runner.write_queue_new(self.config, {"modules": []}))
        self.assertEqual(sequence, ["fsync:file", "replace", "fsync:dir"])

        # STEP 02: 內容正確、沒有留下暫存檔
        self.assertEqual(runner.load_queue(self.config), {"modules": []})
        self.assertFalse(os.path.exists(runner.queue_file(self.config) + ".tmp"))

    def test_mutate_queue_sequence(self):
        """讀-改-寫同樣走完整的三步，且 mutator 的修改有落盤。"""
        # STEP 01: 先有一份 queue
        runner.write_queue_new(self.config, {"modules": [], "marker": 0})

        def bump(queue):
            """把 marker 加一（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
            @return 加一之後的 marker
            """
            # STEP 01: 加一並回傳新值
            queue["marker"] = queue["marker"] + 1
            return queue["marker"]

        # STEP 02: 比對順序與回傳值
        outcome = {}
        sequence = self._record_write_sequence(lambda: outcome.update(value=runner.mutate_queue(self.config, bump)))
        self.assertEqual(sequence, ["fsync:file", "replace", "fsync:dir"])
        self.assertEqual(outcome["value"], 1)
        self.assertEqual(runner.load_queue(self.config)["marker"], 1)


class PublishVerifiedEntryTest(unittest.TestCase):
    """C3 與 PR 連結持久化：L1 通過之後「取收尾資料 → 開 PR → 合併 → 寫回 done」這一段的順序不變量。"""

    def setUp(self):
        """每個測試一組全新的 git 環境；通知與進度檔與本測試無關，一律隔離。"""
        # STEP 01: fixture
        self.root = tempfile.mkdtemp(prefix="r18-c3-")
        self.fixture = build_fixture(self.root)
        # 交給發佈段的 CLI 判讀結果（花費取任意非零值）
        self.outcome = {"structured": {}, "session_id": "session-1", "cost": ROUND_COST_USD}
        # STEP 02: notify 會呼叫外部腳本、write_progress 會產報表，都不是受測對象
        for name in ("notify", "write_progress"):
            patcher = mock.patch.object(runner, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_success_writes_tip_and_done_together(self):
        """成功路徑：遠端整合分支前進到 entry commit，queue 的 tip 與 done 在同一次寫入裡出現。"""
        fixture = self.fixture
        # STEP 01: 包住 mutate_queue，每次寫入後記下「tip 是否已前進、entry 是否已 done」
        # 每次落盤後的 (tip 是否已前進, entry 狀態) 記錄器
        recorder = mock.Mock()
        # 被替換前的 mutate_queue，spy_mutate 轉發給它（真的寫入）
        real_mutate = runner.mutate_queue

        def spy_mutate(config, mutator):
            """轉發後記錄落盤狀態。

            @param config runner 設定
            @param mutator 要在鎖內執行的修改函式
            @return 真的 mutate_queue 的回傳值
            """
            # STEP 01: 轉發、重讀落盤結果並記錄
            value = real_mutate(config, mutator)
            queue, entry = queue_entry(fixture)
            recorder(queue["integration_tip_sha"] == fixture["entry_sha"], entry["status"])
            return value

        with mock.patch.object(runner, "mutate_queue", spy_mutate):
            exit_code = runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)

        # STEP 02: 結果正確
        self.assertIsNone(exit_code)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["entry_sha"])
        queue, entry = queue_entry(fixture)
        self.assertEqual(queue["integration_tip_sha"], fixture["entry_sha"])
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["last_commit"], fixture["entry_sha"])
        self.assertEqual(entry["pr_url"], FAKE_PR_URL)
        self.assertFalse(entry["pr_failed"])
        self.assertEqual(list(entry["r15_hashes"]), [R15_RELATIVE_PATH])
        self.assertIsNotNone(entry["r15_hashes"][R15_RELATIVE_PATH])

        # STEP 03: 任何一次落盤都不能出現「tip 已前進但 entry 還沒 done」的中間態
        snapshots = [call.args for call in recorder.call_args_list]
        self.assertNotIn((True, "running"), snapshots)
        self.assertIn((True, "done"), snapshots)

        # STEP 04: 「先開 PR、再合併」——假 gh 被呼叫的那一刻，遠端整合分支還停在基線
        with open(fixture["gh_tips"], "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read().split(), [fixture["base_sha"]])

    def test_entry_removed_from_queue_stops_before_merge(self):
        """entry 已被人從 queue 移除（執行中重跑了 import-inventory）：不得繼續合併與推送。"""
        fixture = self.fixture
        # STEP 01: 盤點檔拿掉這個 entry 之後重新匯入的結果——modules 裡沒有它了

        def drop_entry(queue):
            """把測試用的 entry 從 queue 拿掉（就地修改，沿用 mutate_queue 的寫入契約）。

            @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
            @return None
            """
            # STEP 01: modules 濾掉測試用的 entry
            queue["modules"] = [item for item in queue["modules"] if item["id"] != ENTRY_ID]

        runner.mutate_queue(fixture["config"], drop_entry)

        # STEP 02: 必須明確失敗，而不是靜默跳過寫回、照樣往下合併
        with self.assertRaises(RuntimeError):
            runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)

        # STEP 03: 整合分支沒有被推送
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])

    def test_entry_removed_during_merge_is_reported_with_tip_recorded(self):
        """合併推送的那幾秒內 entry 被移除：推送已不可逆，tip 要照記，而且必須明確失敗、不可假裝 done。"""
        fixture = self.fixture
        # STEP 01: 真的合併推送，完成後才把 entry 從 queue 拿掉
        # 被替換前的 merge_to_integration，merge_then_drop 轉發給它（真的合併推送）
        real_merge = runner.merge_to_integration

        def merge_then_drop(config, entry, expected_tip):
            """轉發給真正的合併，成功後移除 entry。

            @param config runner 設定
            @param entry 要合併的 entry
            @param expected_tip 預期 ff-merge 後的 HEAD
            @return 真的 merge_to_integration 的回傳值
            """
            # STEP 01: 真的合併推送
            outcome = real_merge(config, entry, expected_tip)

            def drop_entry(queue):
                """把測試用的 entry 從 queue 拿掉（就地修改，沿用 mutate_queue 的寫入契約）。

                @param queue 整份 queue（mutate_queue 鎖內重讀的最新內容）
                @return None
                """
                # STEP 01: modules 濾掉測試用的 entry
                queue["modules"] = [item for item in queue["modules"] if item["id"] != ENTRY_ID]

            # STEP 02: 合併之後才移除 entry
            runner.mutate_queue(config, drop_entry)
            return outcome

        # STEP 02: 收尾找不到 entry 要拋例外
        with mock.patch.object(runner, "merge_to_integration", merge_then_drop):
            with self.assertRaises(RuntimeError):
                runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)

        # STEP 03: 遠端確實已前進，queue 的 tip 也記到了（否則下一個模組開始前會被判成 tip 不符）
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["entry_sha"])
        queue, _entry = queue_entry(fixture)
        self.assertEqual(queue["integration_tip_sha"], fixture["entry_sha"])

    def test_pr_error_is_not_hidden_when_merge_also_fails(self):
        """PR 步驟與合併都失敗：暫停原因裡兩個錯誤都要看得到，不是只剩合併的那一個。"""
        fixture = self.fixture
        # STEP 01: entry 分支推不上去（真的 pre-receive hook）→ 這一輪的 PR 步驟失敗；合併也失敗
        reject_entry_branch_push(fixture["remote"])
        with mock.patch.object(runner, "merge_to_integration", return_value=("integration_diverged", "模擬合併失敗")), \
                mock.patch.object(runner, "freeze_entry_bundle", return_value=None) as freeze, \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
            runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)

        # STEP 02: 兩個錯誤都在暫停原因裡
        detail = paused.call_args.args[2]
        self.assertIn("模擬合併失敗", detail)
        self.assertIn("推送頁面分支失敗", detail)

        # STEP 03: 凍結診斷包的那一刻就已經帶著 PR 的錯誤（操作者帶走的是那個包，不是通知）
        self.assertIn("推送頁面分支失敗", freeze.call_args.args[4])

        # STEP 04: 事件紀錄裡有一筆 pr_failed
        with open(runner.state_path(fixture["config"], "runner.log.jsonl"), "r", encoding="utf-8") as handle:
            events = [line for line in handle.read().splitlines() if '"event": "pr_failed"' in line]
        self.assertEqual(len(events), 1)
        self.assertIn("推送頁面分支失敗", events[0])

    def test_unrecovered_notification_keeps_sha_and_reason_within_budget(self):
        """退不回去的鎖定通知：照 notify.sh 的規則組字並以 300 字截斷之後，仍要看得到「合併前的 sha」、退不回去的原因、與 unblock 指示。

        指示從「unblock --integration-tip 與 --runner」改成「只跑 unblock --runner、不要先跑 --integration-tip」（1.1.2 第五批）：
        推送回報失敗而遠端其實收到的那一種，--integration-tip 會讓重啟對帳認不出來、entry 永遠到不了 done。

        合併前的 sha 是人工退回時唯一能知道「該退到哪」的紀錄（診斷包不收 git 狀態）；第十六批之前它與原因
        都排在兩個 40 字元 sha 的不符敘述之後，300 字只剩「先依下面的說明…」——說明本身被切掉（第十六輪實測 684 字）。
        """
        fixture = self.fixture
        # STEP 01: 真的走「collect 之後 entry 分支又多了 commit、HEAD 已被切走」的退不回去情境，enter_paused 真的跑、只擋通知
        work = fixture["config"]["repo_dir"]
        # 被替換前的 collect_closing_data，替身先轉發給它取收尾資料
        real_collect = runner.collect_closing_data

        def collect_then_late_commit(config, entry):
            """收尾資料取完之後 entry 分支才多一個 commit（殘留寫入者還在改 repo）。

            @param config runner 設定
            @param entry 要收尾的 entry
            @return 真的 collect_closing_data 的回傳值（晚到的 commit 之前取的）
            """
            # STEP 01: 先取收尾資料，再在 entry 分支多提交一個 commit
            closing = real_collect(config, entry)
            with open(os.path.join(work, "late.js"), "w", encoding="utf-8") as handle:
                handle.write("// late\n")
            run_git(work, "add", "-A")
            run_git(work, "commit", "-m", "late commit")
            return closing

        fake_git = git_with_failure(("symbolic-ref", "--short", "HEAD"), (0, "someone-else\n", ""))
        with mock.patch.object(runner, "collect_closing_data", collect_then_late_commit), \
                mock.patch.object(runner, "git", fake_git), mock.patch.object(runner, "notify") as notify:
            self.assertEqual(runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1), runner.EXIT_PAUSED)
        _config, _event, title, body = notify.call_args.args

        # STEP 02: 照 notify.sh 組字並截斷
        text = ("🔴 %s\n%s" % (title, body))[:NOTIFY_MAX_TEXT_CHARS]
        self.assertIn(fixture["base_sha"][:SHA_PREFIX_CHARS], text, text)
        self.assertIn("someone-else", text, text)
        self.assertIn("不要先跑 --integration-tip", text, text)

    def test_unrecovered_merge_locks_runner(self):
        """合併結果是 mismatch（HEAD 不符，不論本機整合分支退回與否）：這次暫停必須鎖定（force_hold）。

        退不回去（unrecovered）要鎖是第九批；退回成功（mismatch）也要鎖是第十批——不符的前提就是
        「有別的東西在改 repo」，一般暫停 launchd 幾分鐘後重啟、preflight 把同一個 entry 放回 pending
        重試，多半再次不符、同原因重複暫停不再通知，無上限地燒額度。一般的 diverged（推送失敗那類）不鎖。
        """
        fixture = self.fixture
        # STEP 01: 三種結果各驗一次
        for merge_result, expect_hold in (
            ("integration_unrecovered", True),
            ("integration_mismatch", True),
            ("integration_diverged", False),
        ):
            with self.subTest(merge_result=merge_result):
                with mock.patch.object(runner, "merge_to_integration", return_value=(merge_result, "模擬")), \
                        mock.patch.object(runner, "freeze_entry_bundle", return_value=None), \
                        mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
                    runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)
                # STEP 02: 看 force_hold；退不回去的那種，unblock 的指示要排在診斷文字之前（通知會截尾）
                self.assertEqual(paused.call_args.kwargs.get("force_hold", False), expect_hold)
                if merge_result == "integration_unrecovered":
                    detail = paused.call_args.args[2]
                    self.assertLess(detail.index("unblock --runner"), detail.index("模擬"), detail)

    def test_repeated_push_failure_locks_runner(self):
        """整合分支持續推不上去：第一次一般暫停（可重試），重啟後第二次連續失敗就要鎖定，不能每輪重跑完整模組。

        第十二批把推送失敗改成退回本機、可重試之後，本機與遠端一致、前置作業放行、entry 放回 pending
        重跑一次完整 CLI 呼叫、再推再失敗——沒有任何計數器會停，而且同原因重複暫停不再通知（第十二輪實測）。
        沿用 enter_paused 既有的「同簽名連續第二次 → hold」機制。
        """
        # STEP 01: 遠端持續拒絕整合分支；第一次發佈 → 一般暫停、帶簽名、不鎖
        fixture = self.fixture
        config = fixture["config"]
        reject_entry_branch_push(fixture["remote"], branch=INTEGRATION_BRANCH)
        self.assertEqual(runner.publish_verified_entry(config, fixture["entry"], self.outcome, 1), runner.EXIT_PAUSED)
        state = runner.load_queue(config)["runner_state"]
        self.assertEqual(state["reason"], "integration_diverged")
        self.assertFalse(state.get("hold"))
        self.assertEqual(state.get("crash_signature"), runner.PUSH_FAILED_SIGNATURE)

        # STEP 02: 模擬 launchd 重啟——cmd_run 啟動時會把上一輪的暫停原因與簽名存進 config、把狀態改成 running
        config["startup_paused_reason"] = state["reason"]
        config["startup_crash_signature"] = state.get("crash_signature")
        runner.set_runner_state(config, "running")
        self.assertEqual(runner.publish_verified_entry(config, fixture["entry"], self.outcome, 2), runner.EXIT_PAUSED)

        # STEP 03: 第二次就鎖定
        state = runner.load_queue(config)["runner_state"]
        self.assertTrue(state.get("hold"), state)

    def test_existing_pr_url_survives_branch_push_failure(self):
        """上一輪已開 PR、這一輪 entry 分支推不上去但整合分支推得上去：done 寫回不得把既有連結蓋成空值。"""
        # STEP 01: entry 帶著上一輪的連結；遠端用 pre-receive hook 只拒絕 entry 分支
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-n3-"), {"pr_url": EXISTING_PR_URL})
        reject_entry_branch_push(fixture["remote"])

        # STEP 02: 發佈段照常走完（entry 分支推送失敗不擋合併，這是既有行為）
        exit_code = runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)
        self.assertIsNone(exit_code)
        self.assertIsNone(remote_tip(fixture, ENTRY_BRANCH), "前置條件：entry 分支應該被 hook 擋下")
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["entry_sha"])

        # STEP 03: 既有連結還在；這一輪的 PR 步驟有錯，pr_failed 要標起來讓人去看
        _queue, entry = queue_entry(fixture)
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["pr_url"], EXISTING_PR_URL)
        self.assertTrue(entry["pr_failed"])

    def test_closing_data_failure_happens_before_push(self):
        """收尾資料取不到（嚴格版拋例外）時，整合分支還沒被推送、queue 也沒被改。"""
        fixture = self.fixture
        # STEP 01: 模擬 R15 原檔存在卻讀不到
        with mock.patch.object(runner, "record_r15_hashes", side_effect=RuntimeError("讀取失敗")):
            with self.assertRaises(RuntimeError):
                runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)

        # STEP 02: 不可逆的那一步還沒發生——遠端整合分支停在基線
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])
        # STEP 03: queue 維持原狀，重啟後這個 entry 仍可正常重跑
        queue, entry = queue_entry(fixture)
        self.assertEqual(queue["integration_tip_sha"], fixture["base_sha"])
        self.assertEqual(entry["status"], "running")

    def test_pr_url_is_persisted_even_if_merge_fails(self):
        """PR 開成功、合併失敗：連結要已經寫進 queue，不是只留在暫停訊息裡。"""
        fixture = self.fixture
        # STEP 01: 合併失敗；凍結診斷包與進入暫停不是受測對象
        with mock.patch.object(runner, "merge_to_integration", return_value=("integration_diverged", "模擬失敗")), \
                mock.patch.object(runner, "freeze_entry_bundle", return_value=None), \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
            exit_code = runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1)

        # STEP 02: 走了暫停出口，且暫停原因帶著 PR 連結
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self.assertIn(FAKE_PR_URL, paused.call_args.args[2])
        # STEP 03: 連結已落盤
        _queue, entry = queue_entry(fixture)
        self.assertEqual(entry["pr_url"], FAKE_PR_URL)


class PushBranchAndOpenPrTest(unittest.TestCase):
    """先前已開過 PR 的 entry 重跑時，只推分支、不再呼叫 gh pr create。"""

    def test_existing_pr_url_skips_gh_create(self):
        """entry 已有 pr_url：分支照推（PR 才會帶到新 commit），gh 不被呼叫，回傳既有連結。"""
        # STEP 01: entry 帶著上一輪留下的連結
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-pr-"), {"pr_url": EXISTING_PR_URL})

        # STEP 02: 執行
        pr_url, pr_error = runner.push_branch_and_open_pr(fixture["config"], fixture["entry"])

        # STEP 03: 沿用既有連結、沒有錯誤、gh 一次都沒被呼叫、分支確實推上遠端
        self.assertEqual((pr_url, pr_error), (EXISTING_PR_URL, None))
        self.assertFalse(os.path.exists(fixture["gh_calls"]), "gh 不應該被呼叫")
        self.assertFalse(os.path.exists(fixture["gh_calls"] + ".list"), "gh pr list 也不應該被呼叫")
        self.assertEqual(remote_tip(fixture, ENTRY_BRANCH), fixture["entry_sha"])

    def test_gh_success_without_pr_link_is_failure(self):
        """gh 以退出碼 0 結束但 stdout 沒有 PR 連結：一律視為失敗，不可把不相干的網址當成 pr_url 記下來。"""
        # STEP 01: 三種輸出各跑一次——空的、純文字、不是 PR 的網址
        for output in NON_PR_OUTPUTS:
            with self.subTest(output=output):
                fixture = build_fixture(tempfile.mkdtemp(prefix="r18-nopr-"))
                write_fake_gh(os.path.dirname(fixture["remote"]), fixture["remote"], output)

                # STEP 02: 回傳失敗，而且 gh 確實被呼叫過（不是因為沒走到那一步）
                pr_url, pr_error = runner.push_branch_and_open_pr(fixture["config"], fixture["entry"])
                self.assertIsNone(pr_url)
                self.assertIn("無可用 PR URL", pr_error)
                self.assertTrue(os.path.exists(fixture["gh_calls"]))

    def test_without_pr_url_creates_pr(self):
        """對照組：entry 沒有 pr_url 時照常開 PR——確認上一個測試的「沒呼叫 gh」不是因為假 gh 根本不會動。"""
        # STEP 01: 預設 fixture 的 pr_url 為 None
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-pr-"))

        # STEP 02: 執行並確認 gh 被呼叫一次
        pr_url, pr_error = runner.push_branch_and_open_pr(fixture["config"], fixture["entry"])
        self.assertEqual((pr_url, pr_error), (FAKE_PR_URL, None))
        with open(fixture["gh_calls"], "r", encoding="utf-8") as handle:
            self.assertEqual(len(handle.read().splitlines()), 1)


class ExtractPrUrlTest(unittest.TestCase):
    """PR 連結的判定：形狀、整行比對、多個符合時取最後一個。"""

    def test_takes_last_matching_line(self):
        """gh 把新建的 PR 連結印在最後；前面若也有 PR 形狀的行（例如提到相關 PR），不可取到前面那個。"""
        # STEP 01: 兩行都符合形狀，中間夾一行進度文字
        output = "https://example.invalid/o/r/pull/1\nCreating pull request...\nhttps://example.invalid/o/r/pull/2\n"
        self.assertEqual(runner.extract_pr_url(output), "https://example.invalid/o/r/pull/2")

    def test_rejects_non_pr_shapes(self):
        """不是 PR 形狀的輸出一律回空字串，含 None。"""
        # STEP 01: NON_PR_OUTPUTS 之外再加 None、句子裡夾著連結、不是 /pull/<編號> 的網址
        samples = NON_PR_OUTPUTS + (None, "see https://example.invalid/o/r/pull/3 for details", "https://example.invalid/o/r/pulls")
        for output in samples:
            with self.subTest(output=output):
                self.assertEqual(runner.extract_pr_url(output), "")


if __name__ == "__main__":
    unittest.main()
