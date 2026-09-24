"""runner.py 1.1.2 D2 的回歸測試：呼叫序號覆寫，以及 sessions/ 檔名的歸屬判定。

D2：被訊號中斷的呼叫沒有 `.json`，修正前序號只看 `.json`，下一次呼叫重用同一個號碼、覆寫 stream 與子行程 log。
第二批（c8093cb 的 codex review）：子行程 log 改成 `<entry>-<n>--<name>.log`（雙減號），長 id 的 log 不再被短 id 認領。

從 review_fixtures 匯入 fixture 與小工具（只匯入函式與常數，不匯入 TestCase，免得被重複收集）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import argparse
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import diagnostics  # noqa: E402  pylint: disable=wrong-import-position
import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    ENTRY_BRANCH,
    ENTRY_ID,
    INTEGRATION_BRANCH,
    build_fixture,
    start_patches,
)

# 兩個 entry id 互為前綴（`foo` 與 `foo-1`）：修正前的前綴比對會把 foo-1 的檔案算成 foo 的
PREFIX_ENTRY_ID = "foo"
PREFIXED_ENTRY_ID = "foo-1"
# 子行程 log 檔名歧義的 id 組（第二批，review IMPORTANT）：長 id ＝ 短 id＋「-數字-小寫開頭字串」，
# 單減號的 `<entry>-<n>-<name>.log` 下，長 id 的 log 會被短 id 的 regex 解析成它的某一號。前兩組是 review 指定的；
# 第三組的長 id 本身含 `--`，驗「log 名稱不可含 `--`」那一段（少了它，短 id 會把 `mod-1--sub-5--npm-ci.log` 認成自己第 1 次的 log）。
# 每組是 (短 id, 短 id 的呼叫序號, 長 id, 長 id 的呼叫序號)
AMBIGUOUS_ID_PAIRS = (
    ("orders-sub", 1, "orders-sub-1-a-sub", 5),
    ("case", 1, "case-23-caseplan-v1", 2),
    ("mod", 1, "mod-1--sub", 5),
)


def touch_session_file(state_dir, name):
    """在 sessions/ 放一個空檔（模擬某次呼叫留下的檔案）。

    @param state_dir 狀態目錄
    @param name 檔名
    @return 完整路徑
    """
    # STEP 01: 建目錄與檔
    # 要建立的檔案完整路徑
    path = os.path.join(diagnostics.sessions_dir(state_dir), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("")
    return path


class CallNumberClaimTest(unittest.TestCase):
    """D2：呼叫序號以 O_EXCL 佔號，被中斷、只留 stream 或只留 claim 的號碼都不會被重用。"""

    def setUp(self):
        """只需要狀態目錄。

        @return None
        """
        # STEP 01: config 與 entry
        # 狀態目錄
        self.state_dir = tempfile.mkdtemp(prefix="r18-callno-")
        # runner 設定
        self.config = {"state_dir": self.state_dir}
        # 取號用的最小 entry
        self.entry = {"id": ENTRY_ID, "attempts": 0}

    def test_stream_only_number_is_not_reused(self):
        """上一次呼叫被訊號中斷、只留 stream：下一個號碼要跳過它，否則覆寫那份 stream。

        @return None
        """
        # STEP 01: 只有 stream
        touch_session_file(self.state_dir, "%s-1%s" % (ENTRY_ID, diagnostics.STREAM_SUFFIX))
        # STEP 02: 取號
        self.assertEqual(runner.next_call_number(self.config, self.entry), 2)

    def test_claim_only_number_is_not_reused(self):
        """取了號、還沒呼叫 CLI 就被中斷（只留 .claim）：下一個號碼要跳過它。

        @return None
        """
        # STEP 01: 只有 claim
        touch_session_file(self.state_dir, "%s-1.claim" % ENTRY_ID)
        # STEP 02: 取號
        self.assertEqual(runner.next_call_number(self.config, self.entry), 2)

    def test_consecutive_claims_are_distinct(self):
        """兩次取號之間沒有任何呼叫落檔：第二次也要拿到新號碼（佔號本身就留下紀錄）。

        @return None
        """
        # STEP 01: 連取兩次
        # 第一次取到的序號
        first = runner.next_call_number(self.config, self.entry)
        # 第二次取到的序號
        second = runner.next_call_number(self.config, self.entry)
        # STEP 02: 不同、遞增
        self.assertEqual((first, second), (1, 2))

    def test_queue_attempts_still_raise_the_floor(self):
        """對照組：sessions/ 是空的但 queue.attempts 是 2，號碼從 3 起跳（沿用 1.1.0 的下限）。

        @return None
        """
        # STEP 01: 取號
        self.assertEqual(runner.next_call_number(self.config, {"id": ENTRY_ID, "attempts": 2}), 3)

    def test_claim_collision_moves_to_next_number(self):
        """候選號已經被佔（兩個取號之間的競爭：掃描時還沒有、建檔時已存在）：往下一號，不重用。

        @return None
        """
        # STEP 01: 1 號的 claim 已存在，但讓掃描看不到它（模擬掃描與建檔之間被別人佔走）
        touch_session_file(self.state_dir, "%s-1%s" % (ENTRY_ID, runner.session_index.CLAIM_SUFFIX))
        with mock.patch.object(runner.session_index, "highest_used_attempt", return_value=None):
            self.assertEqual(runner.next_call_number(self.config, self.entry), 2)

    def test_prefix_entry_files_are_not_counted(self):
        """`foo` 與 `foo-1` 共存：foo-1 的檔案不算 foo 的號碼、foo 的 log 清單不含 foo-1 的 log。

        @return None
        """
        # STEP 01: foo-1 第 5 次呼叫的全部檔案＋foo 第 1 次呼叫的 json 與 log
        # 要放進 sessions/ 的檔名
        for name in ("foo-1-5.json", "foo-1-5.stream.jsonl", "foo-1-5.claim", "foo-1-5--npm-ci.log", "foo-1--git-merge-ff.log"):
            touch_session_file(self.state_dir, name)
        touch_session_file(self.state_dir, "foo-1.json")
        touch_session_file(self.state_dir, "foo-2--build.log")

        # STEP 02: foo 第 1 次的 log 只有自己的那一個（修正前前綴比對會把 foo-1-5--npm-ci.log 也算進來；第 2 次的 log 也不算）
        # 某次呼叫的子行程 log 檔名清單
        logs = [os.path.basename(path) for path in diagnostics.session_files(self.state_dir, PREFIX_ENTRY_ID, 1)["logs"]]
        self.assertEqual(logs, ["foo-1--git-merge-ff.log"])
        # STEP 03: 兩個 entry 的號碼各算各的
        self.assertEqual(runner.next_call_number(self.config, {"id": PREFIX_ENTRY_ID, "attempts": 0}), 3)
        self.assertEqual(runner.next_call_number(self.config, {"id": PREFIXED_ENTRY_ID, "attempts": 0}), 6)

    def test_diagnose_default_picks_latest_json_or_stream(self):
        """diagnose 預設取「有 json 或 stream」的最大號：被中斷的那次（只有 stream）才是最新的一次；只有 claim 的不算。

        @return None
        """
        # STEP 01: 第 2 次完整、第 3 次只有 stream、第 4 次只有 claim
        # 要放進 sessions/ 的檔名
        for name in ("e1-2.json", "e1-2.stream.jsonl", "e1-3.stream.jsonl", "e1-4.claim"):
            touch_session_file(self.state_dir, name)
        # STEP 02: 取最新
        self.assertEqual(diagnostics.latest_attempt(self.state_dir, ENTRY_ID), 3)


class RunClaimPlacementTest(unittest.TestCase):
    """D2：取號在額度檢查之後、git 前置之前；process_one_entry 沿用取件時的號碼，不重算。"""

    def setUp(self):
        """最小 queue 與主迴圈隔離（同 test_preflight 的 RunPreflightPauseTest）。

        @return None
        """
        # STEP 01: 狀態目錄與 queue
        # 狀態目錄
        self.state_dir = tempfile.mkdtemp(prefix="r18-claim-run-")
        # runner 設定
        self.config = {"state_dir": self.state_dir, "notify_channel": "none", "integration_branch": INTEGRATION_BRANCH, "circuit_breaker_n": 3}
        runner.ensure_state_dir(self.config)
        # queue 裡唯一的 entry（執行期欄位用預設值）
        entry = dict(runner.RUNTIME_FIELD_DEFAULTS, id=ENTRY_ID, branch=ENTRY_BRANCH, type="page", wave=0, r15_paths=[])
        runner.write_queue_new(self.config, {"integration_tip_sha": None, "runner_state": {"state": "idle"}, "modules": [entry]})
        # cmd_run 的命令列參數
        self.args = argparse.Namespace(max_modules=None)
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
            "wait_until",
        )
        self.mocks["require_config"].return_value = True
        self.mocks["lockfile_hash"].return_value = None
        self.mocks["preflight"].return_value = 0
        self.mocks["environment_fingerprint"].return_value = {}
        self.mocks["quota_snapshot"].return_value = {}
        self.mocks["wait_until"].return_value = True

    def test_quota_wait_does_not_burn_numbers(self):
        """額度等一輪再放行：只佔一個號，git 前置看到的就是那個號。

        @return None
        """
        # STEP 01: 第一次額度不足（等完 continue）、第二次放行；git 前置記下序號後用一般暫停結束主迴圈
        self.mocks["quota_blocks_start"].side_effect = [(True, "five_hour", None), (False, "", None)]
        # 假件記下的呼叫序號
        seen = []

        def fake_preflight(config, queue):
            """代替 module_preflight：記下當下的序號後回暫停，結束主迴圈。

            @param config runner 設定
            @param queue 整份 queue（不用）
            @return (False, "integration_diverged", "模擬")
            """
            # STEP 01: 記序號
            seen.append(config.get("current_attempt"))
            return False, "integration_diverged", "模擬"

        with mock.patch.object(runner, "module_preflight", fake_preflight), \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)

        # STEP 02: 只有一個 claim，號碼是 1
        # sessions/ 內的佔號檔
        claims = sorted(name for name in os.listdir(diagnostics.sessions_dir(self.state_dir)) if name.endswith(".claim"))
        self.assertEqual(claims, ["%s-1.claim" % ENTRY_ID])
        self.assertEqual(seen, [1])

    def test_process_one_entry_uses_config_attempt(self):
        """process_one_entry 用 config["current_attempt"] 呼叫 CLI，不自己重算（重算會跟子行程 log 的號碼分裂）。

        只驗 config 的序號被沿用；不建立 .claim、也不驗 .claim 是否存在（佔號本身由 CallNumberClaimTest 驗）。

        @return None
        """
        # STEP 01: 真的 git 環境；本測試直接把 current_attempt 設成 7、沒有建立 .claim（sessions/ 是空的，若重算只會得到 1）
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-claim-proc-"))
        # runner 設定
        config = fixture["config"]
        config["current_entry"] = ENTRY_ID
        config["current_attempt"] = 7
        # 假件記下的呼叫序號
        seen = []

        class StopHere(Exception):
            """呼叫 CLI 的那一刻就停，後面的判讀不是受測對象。"""

        def fake_call(config_arg, entry, attempt, resume):
            """代替 call_claude：記下序號後停。

            @param config_arg runner 設定（不用）
            @param entry entry（不用）
            @param attempt 呼叫序號
            @param resume 是否續接 session（不用）
            @return 不回傳
            @raises StopHere 一律
            """
            # STEP 01: 記序號後停
            seen.append(attempt)
            raise StopHere()

        # STEP 02: 呼叫
        with mock.patch.object(runner, "call_claude", fake_call):
            with self.assertRaises(StopHere):
                runner.process_one_entry(config, fixture["entry"])
        self.assertEqual(seen, [7])

    def test_process_one_entry_with_foreign_current_entry_refuses(self):
        """config 的 current_entry 是別的 entry（沒經過 cmd_run 替這個 entry 取號）：明確拋錯，不自己算一個號碼、也不呼叫 CLI。

        檢查依據是 config 的 current_entry／current_attempt，不是 .claim 檔是否存在。

        @return None
        """
        # STEP 01: current_entry 指向別的 entry
        # 測試用的 git 環境與狀態目錄
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-claim-guard-"))
        # runner 設定
        config = fixture["config"]
        config["current_entry"] = "someone-else"
        # STEP 02: 呼叫 CLI 的假件用不同訊息的 RuntimeError，才分得出是哪一個拋的
        with mock.patch.object(runner, "call_claude", side_effect=RuntimeError("called CLI")):
            with self.assertRaisesRegex(RuntimeError, "沒有佔呼叫序號"):
                runner.process_one_entry(config, fixture["entry"])


class SessionLogNameTest(unittest.TestCase):
    """第二批（review IMPORTANT）：子行程 log 檔名 `<entry>-<n>--<name>.log`（雙減號），長 id 的 log 不會被短 id 認領。"""

    def _touch_log(self, state_dir, entry_id, attempt, name):
        """照 runner.session_log_path 的命名建一個空的子行程 log。

        @param state_dir 狀態目錄
        @param entry_id 所屬 entry
        @param attempt 呼叫序號
        @param name 子行程名稱
        @return 檔名（不含目錄）
        """
        # STEP 01: 用 runner 自己的命名（不在測試裡寫死格式）
        # runner 命名的 log 路徑（只取檔名，實際建在 state_dir 底下）
        path = runner.session_log_path({"state_dir": state_dir, "current_entry": entry_id, "current_attempt": attempt}, name)
        return os.path.basename(touch_session_file(state_dir, os.path.basename(path)))

    def test_long_id_logs_are_not_claimed_by_short_id(self):
        """AMBIGUOUS_ID_PAIRS 的三組 id（`orders-sub`／`orders-sub-1-a-sub`、`case`／`case-23-caseplan-v1`、`mod`／`mod-1--sub`）各自共存：log 清單與最大序號各算各的。

        @return None
        """
        # 一組互相歧義的 id 與各自的呼叫序號
        for short_id, short_number, long_id, long_number in AMBIGUOUS_ID_PAIRS:
            with self.subTest(short_id=short_id, long_id=long_id):
                # STEP 01: 兩個 entry 各有一次呼叫（meta＋一個子行程 log）
                # 這組 id 專用的狀態目錄
                state_dir = tempfile.mkdtemp(prefix="r18-logname-")
                touch_session_file(state_dir, "%s-%s.json" % (short_id, short_number))
                touch_session_file(state_dir, "%s-%s.json" % (long_id, long_number))
                # 短 id 那次呼叫的 log 檔名
                short_log = self._touch_log(state_dir, short_id, short_number, "git-merge-ff")
                # 長 id 那次呼叫的 log 檔名
                long_log = self._touch_log(state_dir, long_id, long_number, "npm-ci")
                # STEP 02: log 清單只含自己的
                # 要驗的 entry、呼叫序號、預期的唯一 log
                for entry_id, number, expected in ((short_id, short_number, short_log), (long_id, long_number, long_log)):
                    # 某次呼叫的子行程 log 檔名清單
                    logs = [os.path.basename(path) for path in diagnostics.session_files(state_dir, entry_id, number)["logs"]]
                    self.assertEqual(logs, [expected])
                # STEP 03: 最大序號只看自己的檔
                # sessions/ 的完整路徑
                directory = diagnostics.sessions_dir(state_dir)
                self.assertEqual(runner.session_index.highest_used_attempt(directory, short_id), short_number)
                self.assertEqual(runner.session_index.highest_used_attempt(directory, long_id), long_number)

    def test_runner_level_log_name_unchanged(self):
        """對照組：不在模組脈絡時仍是 `runner-<時間>-<name>.log`（單減號），不在這次改名範圍。

        @return None
        """
        # STEP 01: 沒有 current_entry
        # runner 級 log 的檔名
        name = os.path.basename(runner.session_log_path({"state_dir": "/nonexistent"}, "git-merge-ff"))
        # STEP 02: 單減號形式
        self.assertRegex(name, r"^runner-\d{8}T\d{6}-git-merge-ff\.log$")


if __name__ == "__main__":
    unittest.main()
