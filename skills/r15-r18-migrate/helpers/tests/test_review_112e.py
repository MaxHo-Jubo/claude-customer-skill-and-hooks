"""runner.py 1.1.2 第四批複審修正的回歸測試。

  * 讀 runner.log.jsonl 的 helper 對任何一行都不拋（深度巢狀的 JSON 會拋 RecursionError），而且由新到舊惰性解析、
    找到就停——壞行放在 log 哪裡都不能讓暫停變成 crash。
  * 「這個行程已經開始處理 entry」的旗標在 entry 通過 git 前置之後就設（prepare_branch 衝突 blocked 之後的 continue
    不經過 process_one_entry）；一重啟就在 git 前置暫停的仍沿用上一包。
  * 沿用的診斷包路徑要是字串、相對路徑、正規化後仍在 diagnostics/ 底下。

測試檔獨立於 test_review_112d.py：那個檔已近 600 行，800 行上限放不下。小工具從 review_fixtures／test_review_112c／
test_stale_branch 匯入（只匯入函式與常數，不匯入 TestCase，免得被重複收集）。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -v
"""

import argparse
import json
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

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import build_fixture, start_patches  # noqa: E402  pylint: disable=wrong-import-position
from test_review_112c import simulate_restart  # noqa: E402  pylint: disable=wrong-import-position
from test_stale_branch import SECOND_ENTRY_BRANCH, SECOND_ENTRY_ID, stale_fixture  # noqa: E402  pylint: disable=wrong-import-position

# 深度巢狀 JSON 的層數（同 reviewer 探針）：Python 3.14 的 json C 解析器以 C 堆疊深度判斷遞迴，sys.setrecursionlimit
# 調低不會觸發（實測 5000 層照樣解析成功），10 萬層也能解析；100 萬層拋 RecursionError，而且只要約 5 ms
DEEP_NESTING_LEVELS = 1000000
# 一行深度巢狀、語法合法的 JSON（含換行）
DEEP_LINE = b"[" * DEEP_NESTING_LEVELS + b"]" * DEEP_NESTING_LEVELS + b"\n"


def append_to_log(config, raw):
    """把原始位元組附加到 runner.log.jsonl 尾端。

    @param config runner 設定
    @param raw 要附加的位元組
    @return None
    """
    # STEP 01: 以二進位附加
    with open(runner.state_path(config, "runner.log.jsonl"), "ab") as handle:
        handle.write(raw)


def runner_bundles(config):
    """目前 diagnostics/ 底下 runner 級診斷包的目錄名稱。

    @param config runner 設定
    @return 已排序的名稱清單
    """
    # STEP 01: 列目錄
    # 診斷包目錄
    directory = os.path.join(config["state_dir"], "diagnostics")
    if not os.path.isdir(directory):
        # STEP 01.01: 還沒有任何診斷包
        return []
    return sorted(name for name in os.listdir(directory) if name.startswith("runner-"))


def last_paused_detail(config):
    """用 runner 自己的防禦讀法取最近一筆 paused 事件的 detail（log 裡有深度巢狀的行時，測試自己的讀法也不能炸）。

    @param config runner 設定
    @return dict 或 None
    """
    # STEP 01: 由新到舊找
    for record in runner.log_records_newest_first(config):
        if record is not None and record.get("event") == "paused":
            # STEP 01.01: 找到
            return record.get("detail")
    return None


class DeepNestedLogLineTest(unittest.TestCase):
    """log 裡有一行深度巢狀的 JSON：重複暫停不得拋例外（前段與尾端各一；queue 正常與損毀各一）。"""

    def setUp(self):
        """通知與進度報表隔離。

        @return None
        """
        # STEP 01: 隔離
        start_patches(self, "notify", "write_progress")

    def _pause_twice(self, position, corrupt_queue):
        """在指定位置放深度巢狀的行，連續暫停兩次；回傳第二次的退出碼（拋例外就讓測試失敗）。

        @param position "head"（log 最前面）或 "tail"（第一次暫停之後）
        @param corrupt_queue 是否把 queue.json 弄壞（去重走第三層、只讀 log）
        @return (runner 設定, 第二次 enter_paused 的回傳值)
        """
        # STEP 01: fixture；前段的話先寫壞行
        # 測試用的 git 環境與狀態目錄
        config = build_fixture(tempfile.mkdtemp(prefix="r18-deeplog-"))["config"]
        if position == "head":
            # STEP 01.01: log 最前面
            append_to_log(config, DEEP_LINE)
        # 這組用的暫停原因（queue 損毀時就是 queue_corrupt）
        reason = "queue_corrupt" if corrupt_queue else "disk_low"
        if corrupt_queue:
            # STEP 01.02: 弄壞 queue
            with open(runner.queue_file(config), "w", encoding="utf-8") as handle:
                handle.write("{broken")
        try:
            # STEP 02: 第一次暫停（前段壞行＋queue 損毀時，第一次就會讀 log）；尾端的話之後寫壞行
            runner.enter_paused(config, reason, "d1")
            if position == "tail":
                # STEP 02.01: 最新的一行
                append_to_log(config, DEEP_LINE)
            if not corrupt_queue:
                # STEP 02.02: queue 正常時照 cmd_run 模擬重啟
                simulate_restart(config)
            # STEP 03: 第二次暫停
            return config, runner.enter_paused(config, reason, "d1")
        except Exception as exc:  # pylint: disable=broad-except
            self.fail("深度巢狀的 log 行（%s，queue 損毀=%s）讓 enter_paused 拋出 %s" % (position, corrupt_queue, type(exc).__name__))
        return config, None

    def test_repeated_pause_does_not_raise(self):
        """前段／尾端 × queue 正常／損毀：第二次暫停回 EXIT_PAUSED、判定為重複。

        @return None
        """
        # 壞行位置與 queue 是否損毀的組合
        for position in ("head", "tail"):
            for corrupt_queue in (False, True):
                with self.subTest(position=position, corrupt_queue=corrupt_queue):
                    # STEP 01: 暫停兩次
                    # 設定與第二次的退出碼
                    config, code = self._pause_twice(position, corrupt_queue)
                    # STEP 02: 暫停、有凍結到診斷包（診斷包收錄 log 尾端，壞行不能讓凍結失敗）；判定為重複，只有
                    # 「queue 損毀＋壞行就是最新一行」例外——去重第三層讀到壞行就不宣稱重複（寧可多通知一次）
                    self.assertEqual(code, runner.EXIT_PAUSED)
                    # 第二次暫停的事件
                    detail = last_paused_detail(config)
                    self.assertTrue(detail["diagnostics"])
                    self.assertEqual(detail["repeated"], not (position == "tail" and corrupt_queue))

    def test_head_deep_line_is_never_parsed_when_match_is_newer(self):
        """惰性解析：符合的事件比壞行新時，找到就停，壞行根本不解析（前段壞行、沿用上一包、只有一包）。

        @return None
        """
        # STEP 01: 前段壞行、queue 正常、暫停兩次；json.loads 包一層記錄被解析過的行長
        # 被包住的真 json.loads
        real_loads = json.loads
        # 被解析過的行的長度
        parsed_sizes = []

        def recording_loads(text, *args, **kwargs):
            """記下長度後交給真的 json.loads。

            @param text 要解析的字串
            @param args 原樣轉交
            @param kwargs 原樣轉交
            @return 解析結果
            """
            # STEP 01: 記錄並轉交
            parsed_sizes.append(len(text))
            return real_loads(text, *args, **kwargs)

        class JsonProxy:
            """只換掉 runner 模組看到的 json.loads，其餘轉給真的 json（diagnostics 凍結診斷包時的解析不算在內）。"""

            loads = staticmethod(recording_loads)

            def __getattr__(self, name):
                """其餘屬性轉給真的 json 模組。

                @param name 屬性名稱
                @return 真的 json 模組上的屬性
                """
                # STEP 01: 轉交
                return getattr(json, name)

        with mock.patch.object(runner, "json", JsonProxy()):
            # 設定與第二次的退出碼
            config, code = self._pause_twice("head", False)
        # STEP 02: 暫停、沿用、深度巢狀的那一行沒被解析
        self.assertEqual(code, runner.EXIT_PAUSED)
        self.assertEqual(len(runner_bundles(config)), 1)
        self.assertNotIn(len(DEEP_LINE.strip()), parsed_sizes)


class EntryStartedAfterPreflightTest(unittest.TestCase):
    """cmd_run 層級：entry 通過 git 前置就算「開始處理」；一重啟就在 git 前置暫停的仍沿用上一包。"""

    def setUp(self):
        """衝突版舊分支拓撲＋第二個 entry；上一輪留下 paused(integration_dirty) 與一包診斷；主迴圈外部依賴隔離。

        @return None
        """
        # STEP 01: 拓撲、第二個 entry、上一輪的暫停
        # 測試用的 git 環境與狀態目錄
        self.fixture = stale_fixture(conflict=True)
        # runner 設定
        self.config = self.fixture["config"]
        self.config.update({"circuit_breaker_n": 3, "notify_daily_digest": "09:00"})
        # 第二個 entry
        second = dict(self.fixture["entry"], id=SECOND_ENTRY_ID, branch=SECOND_ENTRY_BRANCH, status="pending")

        def append(queue):
            """mutate_queue 用：登記第二個 entry（就地修改）。

            @param queue 整份 queue
            @return None
            """
            # STEP 01: 登記
            queue["modules"].append(second)

        runner.mutate_queue(self.config, append)
        # STEP 02: 隔離（enter_paused 用真的）
        # 被換掉的 runner 函式：名稱 → mock
        self.mocks = start_patches(
            self,
            "install_shutdown_handlers",
            "require_config",
            "lockfile_hash",
            "preflight",
            "environment_fingerprint",
            "notify",
            "write_progress",
            "maybe_daily_digest",
            "quota_snapshot",
            "quota_blocks_start",
            "handle_checkpoints",
            "process_one_entry",
        )
        self.mocks["require_config"].return_value = True
        self.mocks["lockfile_hash"].return_value = None
        self.mocks["preflight"].return_value = 0
        self.mocks["environment_fingerprint"].return_value = {}
        self.mocks["quota_snapshot"].return_value = {}
        self.mocks["quota_blocks_start"].return_value = (False, "", None)
        self.mocks["handle_checkpoints"].return_value = (False, None)
        # STEP 03: 上一輪的暫停（一包）；cmd_run 開始時會把它讀成 startup_paused_reason
        runner.enter_paused(self.config, "integration_dirty", "上一輪：工作樹有未提交的變更")
        self.first = last_paused_detail(self.config)["diagnostics"]
        # 真的 module_preflight（patch 之前先取）
        self.real_preflight = runner.module_preflight

    def _run(self, preflight_results):
        """跑 cmd_run；module_preflight 依序回 preflight_results 的值（None 表示呼叫真的）。

        @param preflight_results 每次呼叫 module_preflight 的回傳值清單
        @return 最後一筆 paused 事件的 detail
        """
        # STEP 01: 依序回傳
        # 還沒用掉的回傳值
        pending = list(preflight_results)

        def fake_preflight(config_arg, queue):
            """依序回預設結果；None 就跑真的前置作業。

            @param config_arg runner 設定
            @param queue 整份 queue
            @return (ok, 暫停原因, 細節)
            """
            # STEP 01: 取下一個
            # 這次要回的結果
            result = pending.pop(0)
            return self.real_preflight(config_arg, queue) if result is None else result

        with mock.patch.object(runner, "module_preflight", fake_preflight):
            runner.cmd_run(self.config, argparse.Namespace(max_modules=5))
        return last_paused_detail(self.config)

    def test_pause_after_blocked_entry_freezes_new_bundle(self):
        """重啟 → e1 前置作業通過、prepare_branch 衝突標 blocked（不進 process_one_entry）→ e2 前置作業以同原因暫停：新包。

        @return None
        """
        # STEP 01: e1 真的前置作業、e2 同原因暫停
        # 第二次暫停的事件
        second = self._run([None, (False, "integration_dirty", "e2：另一件事")])
        # STEP 02: e1 確實 blocked、沒有進 process_one_entry；這次凍結了新包
        self.mocks["process_one_entry"].assert_not_called()
        self.assertTrue(second["repeated"])
        self.assertFalse(second["diagnostics_reused"])
        self.assertNotEqual(second["diagnostics"], self.first)

    def test_pause_in_first_preflight_after_restart_reuses_bundle(self):
        """對照組：重啟後第一個 entry 的 git 前置就以同原因暫停（沒解除的暫停每 300 秒重啟一次的那種）：沿用上一包。

        @return None
        """
        # STEP 01: 第一次前置作業就暫停
        # 第二次暫停的事件
        second = self._run([(False, "integration_dirty", "工作樹有未提交的變更")])
        # STEP 02: 重複、沿用
        self.assertTrue(second["repeated"])
        self.assertTrue(second["diagnostics_reused"])
        self.assertEqual(second["diagnostics"], self.first)


class ReusedBundlePathValidationTest(unittest.TestCase):
    """沿用的診斷包路徑：非字串、絕對路徑、跳出 diagnostics/ 的一律不沿用（不拋例外）。"""

    def test_invalid_paths_are_not_reused(self):
        """log 裡最近一筆同原因的 paused 事件帶三種壞路徑：previous_pause_bundle 回 None。

        @return None
        """
        # 壞路徑
        for bad in (5, "/tmp", "diagnostics/../.."):
            with self.subTest(path=bad):
                # STEP 01: 只有一筆 paused 事件的 log
                # 最小 runner 設定
                config = {"state_dir": tempfile.mkdtemp(prefix="r18-badpath-")}
                os.makedirs(os.path.join(config["state_dir"], "diagnostics"))
                append_to_log(
                    config,
                    (json.dumps({"event": "paused", "detail": {"reason": "disk_low", "signature": None, "diagnostics": bad}}) + "\n").encode(),
                )
                # STEP 02: 不沿用、不拋
                try:
                    # 沿用結果
                    found = runner.previous_pause_bundle(config, "disk_low", None)
                except Exception as exc:  # pylint: disable=broad-except
                    self.fail("路徑 %r 讓 previous_pause_bundle 拋出 %s" % (bad, type(exc).__name__))
                self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
