"""runner.py 1.1.2 第六批「階段 B」的回歸測試：CHANGELOG「不在這批」登記的九個小缺口。

  (1) 丟棄的延後訊號除了 stderr，也寫一筆 deferred_signal_dropped 事件；寫不進去不拋、stderr 註明事件未寫入。
  (2) L1 沒過與 no_commit 兩條路徑把這一輪 CLI 花費記進 cost_usd_total（只記一次）。
  (3) stderr 摘要保留首行＋尾段（stderr_excerpt），index.lock 這類在首行的關鍵字不再被切掉。
  (4) prepare_branch 合併衝突標 blocked 時記一筆 entry 級事件（prepare_result）。
  (6) config["current_entry"] 在 entry 處理結束後清掉。
  (7) CLI 回報 blocked 與 L1 沒過的「寫 blocked＋通知」在同一個停止訊號延後區間內。
  (8) 前置作業合併失敗但沒有衝突檔時，detail 不再以「合併衝突」開頭（暫停原因不變）。
  (9) CLI 判 auth_expired 的暫停帶簽名：同簽名連續第二次鎖定，unblock --runner 解除。
第 (5) 項只改 SKILL.md，沒有測試。

fixture 從 test_stale_branch／test_review_112b 匯入（只匯入函式與常數，不匯入 TestCase，免得被重複收集）；
原本的 test_review_fixes 已在第六批拆成各主題測試檔、共用 fixture 收進 review_fixtures.py（這裡從它取常數，以及發佈段用的 build_fixture，改名 build_publish_fixture 以免與 test_stale_branch 的同名函式衝突）。
另有 stub 驗收後補的 PushFailedNotifyPointerTest：推送失敗通知截到 300 字仍看得到退回的 sha 與全文 log 指路。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import signal
import stat
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
    GIT_FATAL_EXIT_CODE,
    INTEGRATION_BRANCH,
    NOTIFY_MAX_TEXT_CHARS,
    SHA_PREFIX_CHARS,
    build_fixture as build_publish_fixture,
)
from test_review_112b import (  # noqa: E402  pylint: disable=wrong-import-position
    blocked_then_signal,
    checkpoint_conflict_fixture,
    reset_signal_deferral,
)
from test_stale_branch import (  # noqa: E402  pylint: disable=wrong-import-position
    ENTRY_BRANCH,
    ENTRY_ID,
    SECOND_ENTRY_BRANCH,
    SECOND_ENTRY_ID,
    build_fixture,
    git_with_override,
    install_failing_pre_merge_hook,
    queue_entry,
    stale_fixture,
    start_patches,
)

# 推送被拒時 hook 首行印的拒絕原因（通知截斷後仍要看得到）
PUSH_REASON_KEYWORD = "PUSH-REASON-FIRSTLINE branch protection"
# hook 在拒絕原因之後印的填充行數與每行填充長度：讓 stderr 明顯超過摘要上限
PUSH_HOOK_FILLER_LINES = 12
PUSH_HOOK_FILLER_CHARS = 40
# 丟棄延後訊號時寫的事件名
DROPPED_EVENT = "deferred_signal_dropped"
# 假 CLI 一輪的花費
ROUND_COST = 0.3
# notify.sh 截斷前 runner 放進 detail 的 stderr 摘要上限（與改前的尾段 200 字同一個預算）
EXCERPT_LIMIT = 200
# 首行超長樣本的 A 段長度：EXCERPT_LIMIT 的 3/4（150），超過 stderr_excerpt 保留首行的上限（limit 的一半），驗首行被截短
OVERLONG_HEAD_CHARS = EXCERPT_LIMIT * 3 // 4
# 首行超長樣本的 B 段長度：EXCERPT_LIMIT 的 2 倍（400），讓整段遠超上限、尾段必須被截取
OVERLONG_TAIL_CHARS = EXCERPT_LIMIT * 2
# 真實的 index.lock 錯誤：關鍵字在首行，後面的說明超過 200 字，只取尾段就會把它切掉
LONG_INDEX_LOCK_ERROR = (
    "fatal: Unable to create '/Users/someone/work/sample_web/.git/index.lock': File exists.\n\n"
    "Another git process seems to be running in this repository, e.g.\n"
    "an editor opened by 'git commit'. Please make sure all processes\n"
    "are terminated then try again. If it still fails, a git process\n"
    "may have crashed in this repository earlier:\n"
    "remove the file manually to continue."
)


def events(config, name):
    """runner.log.jsonl 裡指定事件名的所有紀錄（檔案不存在回空清單）。

    @param config runner 設定
    @param name 事件名
    @return 事件 dict 清單（依寫入順序）
    """
    # STEP 01: 逐行解析、過濾
    # 事件紀錄檔路徑
    path = runner.state_path(config, "runner.log.jsonl")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return [record for record in map(json.loads, handle) if record.get("event") == name]


def signal_then(exc=None):
    """給 mock 的 side_effect：模擬停止訊號落在這一步，之後照常返回或拋出 exc。

    @param exc 送完訊號後要拋的例外；None 表示正常返回
    @return side_effect 函式
    """
    # STEP 01: 包出 side_effect（訊號在它被呼叫時才送出，不是現在）

    def side_effect(*_args, **_kwargs):
        """送訊號（直接呼叫 handler，不真的裝訊號），必要時再拋例外。

        @return None
        @raises Exception exc 有給時
        """
        # STEP 01: 送訊號、再決定拋不拋
        runner.shutdown_signal_handler(signal.SIGTERM, None)
        if exc is not None:
            raise exc

    return side_effect


class EntryHarness(unittest.TestCase):
    """process_one_entry 的共用隔離：CLI、判讀、診斷包、通知都換成假件，L1 由各測試指定結果。"""

    def setUp(self):
        """真實 git fixture（entry running、current_entry 已設）＋隔離。

        @return None
        """
        # STEP 01: fixture 與隔離
        # build_fixture 的回傳值
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-112j-"))
        # runner 設定
        self.config = self.fixture["config"]
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(
            self, "call_claude", "save_session_output", "judge_outcome", "freeze_entry_bundle",
            "freeze_runner_bundle", "notify", "write_progress", "l1_verify",
        )
        self.mocks["call_claude"].return_value = {"duration_s": 1, "stream_path": os.path.join(self.config["state_dir"], "x")}
        self.mocks["freeze_entry_bundle"].return_value = None
        self.mocks["freeze_runner_bundle"].return_value = None
        self.addCleanup(reset_signal_deferral)

    def run_entry(self, kind, l1_result=None):
        """跑一次 process_one_entry：CLI 判讀為 kind、L1 回 l1_result。

        @param kind CLI 判讀結果種類
        @param l1_result (result, detail)；None 表示不會走到 L1
        @return process_one_entry 的回傳值
        """
        # STEP 01: 設定假件並執行
        self.mocks["judge_outcome"].return_value = {"kind": kind, "cost": ROUND_COST, "session_id": "s1", "detail": "CLI 回報未登入"}
        self.mocks["l1_verify"].return_value = l1_result
        return runner.process_one_entry(self.config, self.fixture["entry"])


class DroppedSignalEventTest(unittest.TestCase):
    """(1) 暫停區間跑完 runner 本來就要退出，延後的訊號被丟棄：要留一筆事件，不能只有 stderr。"""

    def setUp(self):
        """fixture＋隔離（診斷包凍結、通知）。

        @return None
        """
        # STEP 01: fixture 與隔離
        # runner 設定
        self.config = build_fixture(tempfile.mkdtemp(prefix="r18-drop-"))["config"]
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(self, "freeze_runner_bundle", "notify")
        self.mocks["freeze_runner_bundle"].return_value = None
        self.addCleanup(reset_signal_deferral)

    def test_normal_exit_drop_writes_event(self):
        """enter_paused 的通知當下收到 SIGTERM：區間正常結束時丟棄，事件帶訊號名與原因。

        @return None
        """
        # STEP 01: 通知時送訊號
        self.mocks["notify"].side_effect = signal_then()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(runner.enter_paused(self.config, "disk_low", "x"), runner.EXIT_PAUSED)
        # STEP 02: 事件
        # 丟棄事件
        dropped = events(self.config, DROPPED_EVENT)
        self.assertEqual(len(dropped), 1, dropped)
        self.assertIn("SIGTERM", json.dumps(dropped[0]["detail"], ensure_ascii=False))
        self.assertIn("本來就會退出", json.dumps(dropped[0]["detail"], ensure_ascii=False))

    def test_exception_exit_drop_writes_event(self):
        """區間以例外離開：原例外照樣往外傳，事件的原因寫明是例外結束。

        @return None
        """
        # STEP 01: 通知時送訊號再拋錯
        self.mocks["notify"].side_effect = signal_then(RuntimeError("notify boom"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(RuntimeError, "notify boom"):
            runner.enter_paused(self.config, "disk_low", "x")
        # STEP 02: 事件
        # 丟棄事件
        dropped = events(self.config, DROPPED_EVENT)
        self.assertEqual(len(dropped), 1, dropped)
        self.assertIn("例外", json.dumps(dropped[0]["detail"], ensure_ascii=False))

    def test_event_write_failure_is_reported_not_raised(self):
        """runner.log.jsonl 寫不進去（路徑是目錄）或 log_event 本身拋錯：不拋出，stderr 註明事件未寫入。

        @return None
        """
        # 兩種失敗：真的寫檔失敗／log_event 拋出非 OSError
        real_log_event = runner.log_event

        def raising_log_event(config, entry_id, event, **fields):
            """只對丟棄事件拋錯，其餘照常。

            @param config runner 設定（原樣轉給真的 log_event）
            @param entry_id entry id（runner 級事件為 None）
            @param event 事件名
            @param fields 其餘事件欄位（原樣轉給真的 log_event）
            @return real_log_event 的回傳值
            @raises ValueError 丟棄事件
            """
            # STEP 01: 丟棄事件拋錯
            if event == DROPPED_EVENT:
                raise ValueError("log boom")
            return real_log_event(config, entry_id, event, **fields)

        for label in ("unwritable", "raising"):
            with self.subTest(label):
                # STEP 01: 造失敗並觸發丟棄
                # 事件紀錄檔路徑
                log_path = runner.state_path(self.config, "runner.log.jsonl")
                if label == "unwritable":
                    # STEP 01.01: 把紀錄檔換成目錄
                    if os.path.isfile(log_path):
                        os.unlink(log_path)
                    os.makedirs(log_path, exist_ok=True)
                    self.addCleanup(shutil.rmtree, log_path, True)
                # 攔下來的 stderr
                captured = io.StringIO()
                self.mocks["notify"].side_effect = signal_then()
                patcher = mock.patch.object(runner, "log_event", raising_log_event) if label == "raising" else contextlib.nullcontext()
                with patcher, contextlib.redirect_stderr(captured):
                    # 每個情境用不同的暫停原因：同原因第二次算重複、不通知，訊號就不會送
                    self.assertEqual(runner.enter_paused(self.config, "disk_low_%s" % label, label), runner.EXIT_PAUSED)
                # STEP 02: stderr 有丟棄訊號的警告，也註明事件沒寫進去
                self.assertIn("訊號 %d" % signal.SIGTERM, captured.getvalue())
                self.assertIn("事件未寫入", captured.getvalue())
                reset_signal_deferral()


class CostRecordedTest(EntryHarness):
    """(2) L1 沒過與 no_commit：這一輪 CLI 確實跑完、花了錢，要記進 cost_usd_total，而且只記一次。"""

    def assert_l1_failure_records_cost_once(self, result):
        """L1 沒過（result）跑一輪：blocked，花費記一輪。

        原本在同一個測試的迴圈裡對兩種結果各呼叫一次 self.setUp()，第二輪的 patch 疊在第一輪上面；
        拆成兩個測試各用自己的 setUp，斷言不變。

        @param result l1_verify 的結果（build_unverified／secret_detected）
        @return None
        """
        # STEP 01: 跑一輪（setUp 已建好全新 fixture：entry running、尚無花費）
        self.assertIsNone(self.run_entry("done", (result, "boom")))
        # STEP 02: blocked、花費恰好一輪
        # 落盤後的 entry
        entry = queue_entry(self.fixture)[1]
        self.assertEqual(entry["status"], "blocked")
        self.assertAlmostEqual(entry["cost_usd_total"], ROUND_COST)

    def test_l1_failure_records_cost_once(self):
        """build_unverified：blocked，花費記一輪。

        @return None
        """
        # STEP 01: build_unverified
        self.assert_l1_failure_records_cost_once("build_unverified")

    def test_l1_secret_detected_records_cost_once(self):
        """secret_detected：blocked，花費記一輪。

        @return None
        """
        # STEP 01: secret_detected
        self.assert_l1_failure_records_cost_once("secret_detected")

    def test_no_commit_records_cost_once(self):
        """no_commit：回 pending、attempts+1，花費記一輪。

        @return None
        """
        # STEP 01: 跑一輪
        self.assertIsNone(self.run_entry("done", ("no_commit", "分支相對整合分支沒有任何 commit")))
        # STEP 02: 狀態與花費
        # 落盤後的 entry
        entry = queue_entry(self.fixture)[1]
        self.assertEqual((entry["status"], entry["attempts"]), ("pending", 1))
        self.assertAlmostEqual(entry["cost_usd_total"], ROUND_COST)


class StderrExcerptTest(unittest.TestCase):
    """(3) stderr 摘要保留首行＋尾段、總長不超過上限。"""

    def test_publish_ff_env_failure_keeps_first_line_keyword(self):
        """發佈段 ff-merge 因 index.lock 失敗：暫停細節同時看得到首行的 index.lock 與尾段的處置說明。

        @return None
        """
        # STEP 01: 隔離後發佈（merge --ff-only 注入真實長度的 index.lock 錯誤）
        # 被換掉的 runner 函式：名稱 → mock
        mocks = start_patches(self, "notify", "write_progress", "freeze_entry_bundle", "enter_paused")
        mocks["freeze_entry_bundle"].return_value = None
        mocks["enter_paused"].return_value = runner.EXIT_PAUSED
        # build_fixture 的回傳值（entry 分支可快轉）
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-excerpt-"))
        # 發佈段交給收尾的 CLI 判讀結果
        outcome = {"structured": {}, "session_id": "s1", "cost": ROUND_COST}
        with mock.patch.object(runner, "git", git_with_override(("merge", "--ff-only"), (GIT_FATAL_EXIT_CODE, "", LONG_INDEX_LOCK_ERROR))):
            self.assertEqual(runner.publish_verified_entry(fixture["config"], fixture["entry"], outcome, 1), runner.EXIT_PAUSED)
        # STEP 02: 首行關鍵字與尾段都在（runner 自己的說明文字也提到 index.lock，所以比對 stderr 首行原文）
        # 暫停細節
        detail = mocks["enter_paused"].call_args.args[2]
        self.assertIn("Unable to create '/Users/someone/work/sample_web/.git/index.lock'", detail)
        self.assertIn("remove the file manually to continue", detail)

    def test_excerpt_shape(self):
        """短的原樣回；長的是「首行…尾段」且不超過上限；首行本身超長也不超過；None 當空字串。

        @return None
        """
        # STEP 01: 短
        self.assertEqual(runner.stderr_excerpt("  short\n"), "short")
        self.assertEqual(runner.stderr_excerpt(None), "")
        # STEP 02: 長
        # 摘要
        text = runner.stderr_excerpt(LONG_INDEX_LOCK_ERROR, EXCERPT_LIMIT)
        self.assertLessEqual(len(text), EXCERPT_LIMIT)
        self.assertTrue(text.startswith("fatal: Unable to create"), text)
        self.assertTrue(text.endswith("remove the file manually to continue."), text)
        self.assertIn("…", text)
        # STEP 03: 首行超長（單行）
        text = runner.stderr_excerpt("A" * OVERLONG_HEAD_CHARS + "B" * OVERLONG_TAIL_CHARS, EXCERPT_LIMIT)
        self.assertLessEqual(len(text), EXCERPT_LIMIT)
        self.assertTrue(text.startswith("A") and text.endswith("B"), text)


class PrepareConflictEventTest(unittest.TestCase):
    """(4) prepare_branch 合併衝突標 blocked(git_state)：runner.log.jsonl 要有 entry 級事件。"""

    def test_conflict_logs_entry_event(self):
        """衝突拓撲：prepare_result 事件，entry 是這個 entry、detail 帶 git_state 與衝突細節。

        @return None
        """
        # STEP 01: 前置作業＋準備分支
        start_patches(self, "notify")
        # 衝突版的舊分支拓撲
        fixture = stale_fixture(conflict=True)
        # runner 設定
        config = fixture["config"]
        # 前置作業結果
        ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(ok, "%s: %s" % (reason, detail))
        self.assertEqual(runner.prepare_branch(config, fixture["entry"])[0], runner.PREPARE_ENTRY_BLOCKED)
        # STEP 02: 事件
        # entry 級的 prepare_result 事件
        found = [record for record in events(config, "prepare_result") if record.get("entry") == ENTRY_ID]
        self.assertEqual(len(found), 1, events(config, "prepare_result"))
        self.assertIn(runner.GIT_STATE_REASON, json.dumps(found[0]["detail"], ensure_ascii=False))
        self.assertIn("合併衝突", json.dumps(found[0]["detail"], ensure_ascii=False))


class CurrentEntryClearedTest(unittest.TestCase):
    """(6) current_entry 在 entry 處理結束後清掉：entry 之外的子行程 log 用 runner 級命名。"""

    def setUp(self):
        """衝突版舊分支拓撲（e1 prepare 衝突）＋沒有分支的 e2；主迴圈的外部依賴隔離。

        @return None
        """
        # STEP 01: 拓撲與第二個 entry
        # 衝突版的舊分支拓撲
        self.fixture = stale_fixture(conflict=True)
        # runner 設定
        self.config = self.fixture["config"]
        # 熔斷門檻沿用 runner 預設值；每日摘要時間只是 cmd_run 必讀的設定（maybe_daily_digest 已換成假件）
        self.config.update({"circuit_breaker_n": runner.DEFAULT_CIRCUIT_BREAKER_N, "notify_daily_digest": "09:00"})
        # 第二個 entry
        second = dict(self.fixture["entry"], id=SECOND_ENTRY_ID, branch=SECOND_ENTRY_BRANCH, status="pending")

        def append(queue):
            """mutate_queue 用：登記 e2、runner 狀態 idle（就地修改）。

            @param queue 整份 queue
            @return None
            """
            # STEP 01: 登記
            queue["modules"].append(second)
            queue["runner_state"] = {"state": "idle"}

        runner.mutate_queue(self.config, append)
        # 真的 cmd_run 啟動時 config 沒有 current_entry（build_fixture 為了直接呼叫 process_one_entry 才預先設好）
        self.config.pop("current_entry")
        self.config.pop("current_attempt")
        # STEP 02: 隔離；每輪開頭（maybe_daily_digest）與斷點檢查時記下 current_entry
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(
            self, "install_shutdown_handlers", "require_config", "lockfile_hash", "preflight", "environment_fingerprint",
            "notify", "maybe_daily_digest", "quota_snapshot", "quota_blocks_start", "settle_checkpoints", "handle_runner_crash",
        )
        self.mocks["require_config"].return_value = True
        self.mocks["lockfile_hash"].return_value = None
        self.mocks["preflight"].return_value = 0
        self.mocks["environment_fingerprint"].return_value = {}
        self.mocks["quota_snapshot"].return_value = {}
        self.mocks["quota_blocks_start"].return_value = (False, "", None)
        self.mocks["handle_runner_crash"].return_value = runner.EXIT_PAUSED
        # (時點, current_entry) 紀錄
        self.seen = []
        self.mocks["maybe_daily_digest"].side_effect = lambda config: self.seen.append(("loop", config.get("current_entry")))

        def settle(config, include_auto):
            """記下斷點檢查時的 current_entry 與 log 命名。

            @param config runner 設定（讀 current_entry）
            @param include_auto 是否連 auto 斷點一起處理（不使用）
            @return None（主迴圈繼續）
            """
            # STEP 01: 紀錄
            self.seen.append(("settle", config.get("current_entry")))
            self.seen.append(("log", os.path.basename(runner.session_log_path(config, "gh-cp-pr-list"))))

        self.mocks["settle_checkpoints"].side_effect = settle

    def _process(self, config, entry):
        """代替 process_one_entry：記下當下的 current_entry，並把 entry 標 done。

        @param config runner 設定（讀 current_entry）
        @param entry 要處理的 entry
        @return None
        """
        # STEP 01: 紀錄＋狀態轉移
        self.seen.append(("process", config.get("current_entry")))
        runner.mutate_queue(config, lambda queue: runner.find_entry(queue, entry["id"]).update(status="done"))

    def test_cleared_after_blocked_and_after_processing(self):
        """e1 prepare 衝突 → 下一輪開頭已清；e2 處理中仍是 e2；之後的斷點檢查已清、log 是 runner 級命名。

        @return None
        """
        # STEP 01: 主迴圈（處理一個 entry 就結束）
        with mock.patch.object(runner, "process_one_entry", self._process):
            self.assertEqual(runner.cmd_run(self.config, argparse.Namespace(max_modules=1)), runner.EXIT_OK)
        # STEP 02: 各時點：啟動時的斷點檢查、兩輪開頭（第二輪在 e1 blocked 之後）、e2 處理中、e2 之後的斷點檢查
        self.assertEqual(
            [item for item in self.seen if item[0] != "log"],
            [("settle", None), ("loop", None), ("loop", None), ("process", SECOND_ENTRY_ID), ("settle", None)],
        )
        # 斷點檢查時組出的 log 名稱都是 runner 級
        names = [item[1] for item in self.seen if item[0] == "log"]
        self.assertEqual(len(names), 2, self.seen)
        self.assertTrue(all(name.startswith("runner-") for name in names), names)
        self.assertNotIn("current_entry", self.config)

    def test_cleared_when_processing_raises(self):
        """處理中拋例外（走 crash 流程）：cmd_run 返回後也已清掉。

        @return None
        """
        # STEP 01: e1 改成沒有衝突的路徑不必要——e1 衝突 blocked 後 e2 處理時拋錯
        with mock.patch.object(runner, "process_one_entry", side_effect=RuntimeError("boom")):
            self.assertEqual(runner.cmd_run(self.config, argparse.Namespace(max_modules=1)), runner.EXIT_PAUSED)
        # STEP 02: 已清
        self.assertNotIn("current_entry", self.config)


class BlockedNotifyDeferralTest(EntryHarness):
    """(7) CLI 回報 blocked 與 L1 沒過：訊號落在寫 blocked 之後，通知仍要送出，訊號之後照樣拋出。"""

    def _assert_blocked_and_notified(self, raised):
        """共同斷言：通知已送、entry blocked、訊號在區間結束後拋出、區間狀態歸零。

        @param raised 受測呼叫拋出的例外（沒拋是 None）
        @return None
        """
        # STEP 01: 通知與狀態
        self.assertEqual([call.args[1] for call in self.mocks["notify"].call_args_list], ["module_blocked"])
        self.assertEqual(queue_entry(self.fixture)[1]["status"], "blocked")
        # STEP 02: 訊號與區間
        self.assertIsInstance(raised, runner.ShutdownSignal)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)  # pylint: disable=protected-access
        self.assertIsNone(runner._PENDING_SIGNUM)  # pylint: disable=protected-access

    def test_cli_blocked(self):
        """apply_outcome(blocked)。

        @return None
        """
        # STEP 01: 呼叫
        # 受測呼叫拋出的例外
        raised = None
        with mock.patch.object(runner, "mark_entry_blocked", blocked_then_signal()):
            try:
                runner.apply_outcome(self.config, ENTRY_ID, {"kind": "blocked", "detail": "too_large", "cost": ROUND_COST})
            except runner.ShutdownSignal as exc:
                raised = exc
        self._assert_blocked_and_notified(raised)

    def test_l1_failure(self):
        """L1 build_unverified。

        @return None
        """
        # STEP 01: 呼叫
        # 受測呼叫拋出的例外
        raised = None
        with mock.patch.object(runner, "mark_entry_blocked", blocked_then_signal()):
            try:
                self.run_entry("done", ("build_unverified", "boom"))
            except runner.ShutdownSignal as exc:
                raised = exc
        self._assert_blocked_and_notified(raised)


class PreflightNoConflictDetailTest(unittest.TestCase):
    """(8) 前置作業合併失敗而且確實沒有衝突檔：detail 照實寫「合併失敗（無衝突檔）」，暫停原因仍是 master_conflict。"""

    def test_base_merge_rejected_by_hook(self):
        """基準分支合併被 pre-merge-commit hook 拒絕（MERGE_HEAD 在、沒有 U 檔）。

        @return None
        """
        # STEP 01: 基準分支已前進的拓撲＋hook
        # 無衝突版的舊分支拓撲
        fixture = stale_fixture(conflict=False)
        # runner 設定
        config = fixture["config"]
        install_failing_pre_merge_hook(config["repo_dir"])
        # 前置作業結果
        ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
        # STEP 02: 原因不變、detail 照實
        self.assertEqual((ok, reason), (False, "master_conflict"), detail)
        self.assertTrue(detail.startswith("與基準分支合併失敗（無衝突檔）"), detail)
        self.assertIn("rejected by test hook", detail)

    def test_checkpoint_merge_failed_without_conflicts(self):
        """斷點回流的 git merge 失敗、合併未開始（沒有 MERGE_HEAD）。

        @return None
        """
        # STEP 01: opened 斷點；回流那次 merge 注入失敗
        # 有 opened 斷點的 fixture
        fixture = checkpoint_conflict_fixture()
        # runner 設定
        config = fixture["config"]
        # 斷點
        checkpoint = runner.load_queue(config)["checkpoints"][0]
        with mock.patch.object(runner, "git", git_with_override(("merge", checkpoint["branch"]), (1, "", "cp boom"))):
            ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))
        # STEP 02: 原因不變、detail 照實
        self.assertEqual((ok, reason), (False, "master_conflict"), detail)
        self.assertTrue(detail.startswith("斷點分支 %s 回流失敗（無衝突檔）" % checkpoint["id"]), detail)
        self.assertIn("cp boom", detail)


class AuthExpiredSignatureTest(EntryHarness):
    """(9) CLI 判 auth_expired：暫停帶簽名，同簽名連續第二次鎖定；unblock --runner 連原因一起解除。"""

    def test_second_cli_auth_expired_holds_and_unblock_clears(self):
        """第一次一般暫停（帶簽名）→ 重啟 → 第二次鎖定 → unblock --runner 回 idle。

        @return None
        """
        # STEP 01: 第一次
        self.assertEqual(self.run_entry("auth_expired"), runner.EXIT_PAUSED)
        # 落盤後的 runner_state
        state = runner.load_queue(self.config)["runner_state"]
        self.assertEqual(state.get("reason"), "auth_expired")
        self.assertIsNotNone(state.get("crash_signature"), state)
        self.assertFalse(state.get("hold"), state)
        # STEP 02: 模擬重啟（cmd_run STEP 02.01），第二次
        self.config["startup_paused_reason"] = state["reason"]
        self.config["startup_crash_signature"] = state["crash_signature"]
        runner.set_runner_state(self.config, "running")
        self.assertEqual(self.run_entry("auth_expired"), runner.EXIT_PAUSED)
        state = runner.load_queue(self.config)["runner_state"]
        self.assertTrue(state.get("hold"), state)
        # STEP 03: unblock --runner
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.unblock_runner(self.config), runner.EXIT_OK)
        state = runner.load_queue(self.config)["runner_state"]
        self.assertEqual((state.get("state"), state.get("reason"), state.get("hold")), ("idle", None, False))


class PushFailedNotifyPointerTest(unittest.TestCase):
    """stub 驗收補修：推送失敗的通知截到 300 字後，仍要看得到本機退回的 sha、全文 log 路徑與 stderr 首行。

    stub 實跑實測：runner 送出 549 字，指路（全文 log、已退回 sha）排在 stderr 之後，被 notify.sh 截掉。
    """

    def setUp(self):
        """真的 git 環境；遠端 pre-receive hook 拒絕整合分支並印出多行 stderr。

        @return None
        """
        # STEP 01: fixture（暫存目錄測試結束刪除）
        # 本測試的暫存根目錄
        self.root = tempfile.mkdtemp(prefix="r18-pushnotify-")
        self.addCleanup(shutil.rmtree, self.root, True)
        # 發佈段 fixture：bare 遠端、工作 repo、一個有 commit 的 entry 分支
        self.fixture = build_publish_fixture(self.root)
        # STEP 02: hook 首行印拒絕原因，接著多行填充，模擬 GitHub 分支保護的長訊息
        hook_path = os.path.join(self.fixture["remote"], "hooks", "pre-receive")
        filler = "\n".join('echo "%s" >&2' % ("filler line %02d " % n + "x" * PUSH_HOOK_FILLER_CHARS) for n in range(PUSH_HOOK_FILLER_LINES))
        with open(hook_path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/bash\necho \"%s\" >&2\n%s\nexit 1\n" % (PUSH_REASON_KEYWORD, filler))
        os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IXUSR)

    def test_notify_keeps_restored_sha_and_log_pointer(self):
        """publish_verified_entry 推送被拒 → 暫停通知照 notify.sh 截到 300 字，三項資訊都要在。

        @return None
        """
        # STEP 01: 真的跑發佈段，只擋通知與進度報表
        fixture = self.fixture
        outcome = {"structured": {}, "session_id": "session-1", "cost": ROUND_COST}
        with mock.patch.object(runner, "notify") as notify, mock.patch.object(runner, "write_progress"):
            self.assertEqual(runner.publish_verified_entry(fixture["config"], fixture["entry"], outcome, 1), runner.EXIT_PAUSED)
        # STEP 02: 確認走的是推送失敗、本機已退回那一條
        state = runner.load_queue(fixture["config"])["runner_state"]
        self.assertEqual(state.get("crash_signature"), runner.PUSH_FAILED_SIGNATURE, state)
        self.assertEqual(run_git_rev(fixture["config"]["repo_dir"], INTEGRATION_BRANCH), fixture["base_sha"])
        # STEP 03: 照 notify.sh 組字並截斷，三項都要看得到
        _config, _event, title, body = notify.call_args.args
        text = ("⏸ %s\n%s" % (title, body))[:NOTIFY_MAX_TEXT_CHARS]
        self.assertIn(fixture["base_sha"][:SHA_PREFIX_CHARS], text, text)
        self.assertIn("git-push-integration.log", text, text)
        self.assertIn(PUSH_REASON_KEYWORD, text, text)


def run_git_rev(repo, ref):
    """讀某個 ref 目前指向的 commit。

    @param repo 工作 repo 路徑
    @param ref 分支名稱
    @return 完整 sha 字串
    """
    # STEP 01: rev-parse 並去掉換行
    return subprocess.run(["git", "-C", repo, "rev-parse", ref], capture_output=True, text=True, check=True).stdout.strip()


class ConfigRequiredTest(unittest.TestCase):
    """(1) 的補強：ShutdownDeferral 與 _terminate_process_group 的 config 必填，漏傳就拋 TypeError，不靜默略過丟棄事件。"""

    def test_missing_config_raises_type_error(self):
        """不傳 config 呼叫兩者都拋 TypeError；收尾本體換成假件，漏傳被接受時會正常返回而讓測試失敗。

        @return None
        """
        # STEP 01: ShutdownDeferral 不帶 config（位置參數與關鍵字各一次）
        with self.assertRaises(TypeError):
            runner.ShutdownDeferral()
        with self.assertRaises(TypeError):
            runner.ShutdownDeferral(raise_on_normal_exit=False)
        # STEP 02: _terminate_process_group 不帶 config；收尾本體換成回空輸出的假件，不碰真的行程
        with mock.patch.object(runner, "_terminate_process_group_uninterrupted", return_value=("", "")):
            with self.assertRaises(TypeError):
                runner._terminate_process_group(object(), 1)  # pylint: disable=protected-access


if __name__ == "__main__":
    unittest.main()
