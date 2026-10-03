"""runner.py 額度前置檢查改從 stream 的 rate_limit_event 取用量（取代 quota-usage.py 打用量端點）。

背景：`/api/oauth/usage` 需要 `user:profile` scope，`claude setup-token` 的長效 token 只有 `user:inference`，
對它一律 429；而每次 CLI 呼叫的 stream 都帶 `rate_limit_event`，內有 `unifiedWindows.five_hour／seven_day`
的 `utilization` 與 `resetsAt`（2026-09-30 在真環境的 14 筆事件驗證過）。舊的 quota_snapshot 在腳本失敗時輸出
`{"available": false}`（非空 JSON），事件 quota_unavailable 永遠不會記——額度檢查靜默失效。

契約（外部）：
- `rate_limit.latest_rate_limit(events)`：純函式，取最後一筆有效事件，回
  `{"status", "five_hour": {"utilization": 百分比整數, "resets_at": ISO}, "seven_day": {...}}`；沒有有效事件回 None。
  utilization 在事件裡是 0～1 的比例（**單位未對照 /usage 驗證**），換成百分比整數，才與 runner 的 80／95 門檻同單位。
- `runner.record_rate_limit(config, stream_path)`：CLI 呼叫結束後把最後一筆寫進 queue 的 runner_state.last_rate_limit；
  讀不到就保留舊值並記事件 rate_limit_missing，不拋例外。
- `runner.quota_snapshot(config)`：不呼叫任何外部指令；回 quota_blocks_start 認得的格式；過期的視窗略過；查不到時
  **記事件 quota_unavailable（帶原因）**，不再靜默。

先紅：rate_limit 模組、record_rate_limit 尚未實作時，測試以 AssertionError 失敗，不是 ImportError／AttributeError。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_rate_limit.py -v
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import ENTRY_ID, build_fixture  # noqa: E402  pylint: disable=wrong-import-position

# 2026-09-30 在真環境 stream 裡看到的事件（五小時 28%、七天 40%）：時間戳與換算後的 ISO 寫成字面值（外部契約）
REAL_FIVE_RESET = 1790764800
REAL_SEVEN_RESET = 1790838000
REAL_FIVE_ISO = "2026-09-30T10:40:00+00:00"
REAL_SEVEN_ISO = "2026-10-01T07:00:00+00:00"
# 事件名（外部契約）
MISSING_EVENT = "rate_limit_missing"
UNAVAILABLE_EVENT = "quota_unavailable"
# 取件前門檻（百分比整數，與 runner 預設一致）
FIVE_HOUR_THRESHOLD = 80
SEVEN_DAY_THRESHOLD = 95
# 距離現在多久算「還沒重置」／「已重置」（秒）
ONE_HOUR = 3600


def rl_event(five=0.28, seven=0.40, five_reset=REAL_FIVE_RESET, seven_reset=REAL_SEVEN_RESET, status="allowed"):
    """組一筆與真實 stream 同形狀的 rate_limit_event。

    @param five 五小時 utilization（0～1 比例）
    @param seven 七天 utilization
    @param five_reset 五小時重置時間（epoch 秒）
    @param seven_reset 七天重置時間（epoch 秒）
    @param status 事件的 status
    @return dict
    """
    # STEP 01: 欄位照 2026-09-30 的真實樣本
    info = {
        "status": status,
        "resetsAt": five_reset,
        "rateLimitType": "five_hour",
        "overageStatus": "rejected",
        "overageDisabledReason": "org_level_disabled",
        "isUsingOverage": False,
        "unifiedWindows": {
            "five_hour": {"utilization": five, "resetsAt": five_reset},
            "seven_day": {"utilization": seven, "resetsAt": seven_reset},
        },
    }
    return {"type": "rate_limit_event", "rate_limit_info": info, "uuid": "u-1", "session_id": "s-1"}


def load_rate_limit(test_case):
    """延遲匯入 rate_limit；還沒實作時讓測試以 AssertionError 失敗。

    @param test_case 目前的 TestCase
    @return rate_limit 模組
    """
    # STEP 01: 匯入（sys.path 已含 helpers/）
    try:
        import rate_limit  # pylint: disable=import-outside-toplevel
    except ImportError:
        test_case.fail("rate_limit 模組尚未實作")
    return rate_limit


def write_stream(directory, events, raw_lines=()):
    """把事件寫成 stream-json 落檔（一行一事件），再附加原樣的壞行。

    @param directory 目錄
    @param events 事件 dict 清單
    @param raw_lines 要原樣附加的行（例如半行）
    @return 檔案路徑
    """
    # STEP 01: 寫檔
    path = os.path.join(directory, "x.stream.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
        for line in raw_lines:
            handle.write(line + "\n")
    return path


class LatestRateLimitTest(unittest.TestCase):
    """純函式：從事件清單取最後一筆有效的用量。"""

    def test_real_sample_is_converted_to_percent_and_iso(self):
        """真實樣本：0.28／0.40 → 28／40，epoch → UTC ISO；status 帶出。

        @return None
        """
        # STEP 01: 解析
        rate_limit = load_rate_limit(self)
        result = rate_limit.latest_rate_limit([rl_event()])
        # STEP 02: 單位是百分比整數，與 runner 的 80／95 門檻同單位
        self.assertEqual(result["status"], "allowed")
        self.assertEqual(result["five_hour"], {"utilization": 28, "resets_at": REAL_FIVE_ISO})
        self.assertEqual(result["seven_day"], {"utilization": 40, "resets_at": REAL_SEVEN_ISO})
        # STEP 03: runner 的 parse_iso 認得這個格式（wait_until 用它）
        self.assertIsNotNone(runner.parse_iso(result["five_hour"]["resets_at"]))

    def test_rounding(self):
        """換算成整數是四捨五入（避開恰好 .5 的平手）。

        @return None
        """
        rate_limit = load_rate_limit(self)
        low = rate_limit.latest_rate_limit([rl_event(five=0.284)])
        high = rate_limit.latest_rate_limit([rl_event(five=0.286)])
        self.assertEqual((low["five_hour"]["utilization"], high["five_hour"]["utilization"]), (28, 29))

    def test_takes_the_last_valid_event(self):
        """多筆事件取最後一筆；最後一筆壞掉就退回它前面最近的有效那筆（不是丟掉全部）。

        @return None
        """
        rate_limit = load_rate_limit(self)
        # STEP 01: 依序 5%、6% → 取 6%
        first = rl_event(five=0.05)
        second = rl_event(five=0.06)
        self.assertEqual(rate_limit.latest_rate_limit([first, second])["five_hour"]["utilization"], 6)
        # STEP 02: 後面接各種壞事件，結果不變（對照組是上一行：同樣的前兩筆，有效）
        broken_variants = {
            "utilization 不是數字": rl_event(five="abc"),
            "utilization 是布林": rl_event(five=True),
            "utilization 是負數": rl_event(five=-0.1),
            "utilization 是 null": rl_event(five=None),
            "少一個視窗": {**rl_event(), "rate_limit_info": {"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.9, "resetsAt": REAL_FIVE_RESET}}}},
            "resetsAt 不是數字": rl_event(five_reset="soon"),
            "rate_limit_info 不是 dict": {"type": "rate_limit_event", "rate_limit_info": "x"},
        }
        for label, broken in broken_variants.items():
            with self.subTest(label):
                result = rate_limit.latest_rate_limit([first, second, broken])
                self.assertIsNotNone(result)
                self.assertEqual(result["five_hour"]["utilization"], 6)

    def test_no_usable_event(self):
        """沒有事件、或只有別種事件／全壞：回 None，不拋例外。

        @return None
        """
        rate_limit = load_rate_limit(self)
        self.assertIsNone(rate_limit.latest_rate_limit([]))
        self.assertIsNone(rate_limit.latest_rate_limit([{"type": "assistant"}, {"type": "result"}]))
        self.assertIsNone(rate_limit.latest_rate_limit([rl_event(five="abc")]))

    def test_over_limit_values_are_kept(self):
        """超過 100% 是有意義的訊號（已撞牆）：不截斷成 100。

        @return None
        """
        rate_limit = load_rate_limit(self)
        result = rate_limit.latest_rate_limit([rl_event(five=1.05, status="rejected")])
        self.assertEqual(result["five_hour"]["utilization"], 105)
        self.assertEqual(result["status"], "rejected")


class RecordAndSnapshotTest(unittest.TestCase):
    """runner 端：CLI 呼叫後存檔、取件前取用。"""

    def setUp(self):
        """建一個空的狀態目錄與 queue。

        @return None
        """
        # STEP 01: 暫存根目錄
        root = tempfile.mkdtemp(prefix="r18-ratelimit-")
        self.addCleanup(shutil.rmtree, root, True)
        # 放 stream 落檔的目錄
        self.root = root
        # runner 設定
        self.config = {"state_dir": os.path.join(root, "state"), "repo_dir": root, "notify_channel": "none"}
        runner.ensure_state_dir(self.config)
        runner.write_queue_new(self.config, {"runner_state": {"state": "idle"}, "modules": []})
        # STEP 02: 這個類別的任何測試都不可以呼叫外部指令。舊版 quota_snapshot 會跑 quota-usage.py，而它會讀本機 Keychain／
        # 環境變數的 token 去打真實端點——先紅階段也不能碰真的憑證，所以在這裡封死（新版 quota_snapshot 本來就不該呼叫）
        patcher = mock.patch.object(runner, "run_command", side_effect=AssertionError("不該呼叫外部指令"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def last_event(self, name):
        """取指定名稱的最後一筆事件；沒有就以斷言失敗（不是 IndexError）。

        @param name 事件名
        @return dict
        """
        # STEP 01: 先斷言有，才取最後一筆
        found = self.events(name)
        self.assertTrue(found, "沒有記到事件 %s" % name)
        return found[-1]

    def events(self, name):
        """讀事件紀錄裡指定名稱的事件。

        @param name 事件名
        @return list[dict]
        """
        # STEP 01: 沒有紀錄檔就是沒有事件
        path = os.path.join(self.config["state_dir"], "runner.log.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            return [item for item in (json.loads(line) for line in handle if line.strip()) if item.get("event") == name]

    def stored(self):
        """讀 queue 裡記下的最後一筆用量。

        @return dict 或 None
        """
        return runner.load_queue(self.config).get("runner_state", {}).get("last_rate_limit")

    def record(self, events, raw_lines=()):
        """把事件寫成 stream 檔並交給 record_rate_limit。

        @param events 事件清單
        @param raw_lines 要附加的壞行
        @return record_rate_limit 的回傳值
        """
        # STEP 01: 先紅時拿到 AssertionError
        handler = getattr(runner, "record_rate_limit", None)
        self.assertIsNotNone(handler, "record_rate_limit 尚未實作")
        return handler(self.config, write_stream(self.root, events, raw_lines))

    def future_event(self, five=0.5, seven=0.5):
        """兩個視窗都還沒重置的事件。

        @param five 五小時 utilization
        @param seven 七天 utilization
        @return dict
        """
        now = int(time.time())
        return rl_event(five=five, seven=seven, five_reset=now + ONE_HOUR, seven_reset=now + 24 * ONE_HOUR)

    def test_record_stores_last_event_and_ignores_bad_lines(self):
        """最後一筆有效事件落盤；stream 尾端被殺的半行不影響。

        @return None
        """
        # STEP 01: 兩筆事件＋半行
        self.assertTrue(self.record([rl_event(five=0.05), rl_event(five=0.06)], raw_lines=['{"type": "rate_limit_ev']))
        # STEP 02: 落盤內容
        stored = self.stored()
        self.assertEqual(stored["five_hour"]["utilization"], 6)
        self.assertEqual(stored["seven_day"]["resets_at"], REAL_SEVEN_ISO)
        self.assertTrue(stored["observed_at"])

    def test_missing_event_keeps_previous_value_and_says_so(self):
        """這一輪沒有可用事件：保留上一輪的值、記 rate_limit_missing（帶原因），回 False，不拋例外。

        @return None
        """
        # STEP 01: 先有一筆
        self.assertTrue(self.record([rl_event(five=0.11)]))
        # STEP 02: 這一輪 stream 沒有 rate_limit_event
        self.assertFalse(self.record([{"type": "assistant"}]))
        self.assertEqual(self.stored()["five_hour"]["utilization"], 11)
        missing = self.events(MISSING_EVENT)
        self.assertEqual(len(missing), 1)
        self.assertTrue(missing[0]["detail"]["reason"])
        # STEP 03: stream 檔根本不存在
        handler = getattr(runner, "record_rate_limit")
        self.assertFalse(handler(self.config, os.path.join(self.root, "nope.jsonl")))
        self.assertEqual(len(self.events(MISSING_EVENT)), 2)

    def test_snapshot_uses_stored_value_without_external_commands(self):
        """quota_snapshot 只讀已存的值：available、百分比整數、ISO 時間，且完全不呼叫外部指令。

        @return None
        """
        # STEP 01: 存一筆兩個視窗都沒過期的
        self.assertTrue(self.record([self.future_event(five=0.85, seven=0.40)]))
        # STEP 02: 取用（setUp 已封死外部指令，呼叫了會直接失敗）
        snapshot = runner.quota_snapshot(self.config)
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["five_hour"]["utilization"], 85)
        self.assertEqual(snapshot["seven_day"]["utilization"], 40)
        self.assertIsNotNone(runner.parse_iso(snapshot["five_hour"]["resets_at"]))
        self.assertEqual(self.events(UNAVAILABLE_EVENT), [])

    def test_snapshot_without_data_is_loud(self):
        """沒有任何資料：available False，而且**記事件 quota_unavailable**（原因 no_data）。這是修靜默失效的核心。

        @return None
        """
        snapshot = runner.quota_snapshot(self.config)
        self.assertFalse(snapshot["available"])
        events = self.events(UNAVAILABLE_EVENT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["detail"]["reason"], "no_data")

    def test_expired_window_is_skipped_not_faked(self):
        """五小時視窗已過期、七天還沒：五小時略過（不當 0、不當舊值），七天照用；兩個都過期則 unavailable(stale)。

        @return None
        """
        now = int(time.time())
        # STEP 01: 五小時 1 小時前就重置了
        self.assertTrue(self.record([rl_event(five=0.99, seven=0.40, five_reset=now - ONE_HOUR, seven_reset=now + 24 * ONE_HOUR)]))
        snapshot = runner.quota_snapshot(self.config)
        self.assertTrue(snapshot["available"])
        self.assertNotIn("five_hour", snapshot)
        self.assertEqual(snapshot["seven_day"]["utilization"], 40)
        # STEP 02: 兩個都過期
        self.assertTrue(self.record([rl_event(five=0.99, seven=0.99, five_reset=now - ONE_HOUR, seven_reset=now - ONE_HOUR)]))
        snapshot = runner.quota_snapshot(self.config)
        self.assertFalse(snapshot["available"])
        self.assertEqual(self.last_event(UNAVAILABLE_EVENT)["detail"]["reason"], "stale")

    def test_unreadable_queue_is_unavailable_not_a_crash(self):
        """queue 讀不到：unavailable（原因 queue_unreadable），不拋例外——取件前檢查壞了不能讓整個 runner 倒。

        @return None
        """
        # STEP 01: 把 queue.json 拿掉
        os.remove(runner.state_path(self.config, "queue.json"))
        # STEP 02: 不拋例外、說明原因
        snapshot = runner.quota_snapshot(self.config)
        self.assertFalse(snapshot["available"])
        self.assertEqual(self.last_event(UNAVAILABLE_EVENT)["detail"]["reason"], "queue_unreadable")

    def test_snapshot_drives_preflight_in_percent_units(self):
        """把單位釘死：85% 要擋（>=80），50% 不擋。少了 ×100 的換算，0.85 永遠小於 80，前置檢查形同虛設。

        @return None
        """
        config = dict(self.config, quota_preflight_five_hour=FIVE_HOUR_THRESHOLD, quota_preflight_seven_day=SEVEN_DAY_THRESHOLD)
        # STEP 01: 85% → 擋，原因與重置時間帶出
        self.assertTrue(self.record([self.future_event(five=0.85)]))
        should_wait, reason, resets_at = runner.quota_blocks_start(config, runner.quota_snapshot(self.config))
        self.assertTrue(should_wait)
        self.assertIn("five_hour", reason)
        self.assertIsNotNone(runner.parse_iso(resets_at))
        # STEP 02: 對照組：50% → 不擋
        self.assertTrue(self.record([self.future_event(five=0.50)]))
        self.assertEqual(runner.quota_blocks_start(config, runner.quota_snapshot(self.config))[0], False)
        # STEP 03: 七天 96% → 擋（七天門檻 95）
        self.assertTrue(self.record([self.future_event(five=0.10, seven=0.96)]))
        should_wait, reason, _resets = runner.quota_blocks_start(config, runner.quota_snapshot(self.config))
        self.assertTrue(should_wait)
        self.assertIn("seven_day", reason)


class WiringTest(unittest.TestCase):
    """接線：process_one_entry 在 CLI 呼叫結束後、判讀之前就把用量存進 queue。"""

    def test_usage_is_recorded_before_the_outcome_is_judged(self):
        """判讀（judge_outcome）會用 quota_snapshot 決定是不是額度問題，所以存檔必須在判讀之前。

        @return None
        """
        # STEP 01: 真的 git 環境；CLI 假件回一個帶 rate_limit_event 的 stream
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-ratelimit-wire-"))
        self.addCleanup(shutil.rmtree, os.path.dirname(fixture["config"]["state_dir"]), True)
        config = fixture["config"]
        config["current_entry"] = ENTRY_ID
        config["current_attempt"] = 1
        stream_path = write_stream(os.path.dirname(config["state_dir"]), [rl_event(five=0.42)])
        # 判讀當下 queue 裡已記下的值
        seen = {}

        class StopHere(Exception):
            """判讀的那一刻就停，後面不是受測對象。"""

        def fake_call(_config, _entry, _attempt, _resume):
            """代替 call_claude：回一個帶 stream 的結果。"""
            return {"returncode": 0, "stream_path": stream_path, "stderr": "", "timed_out": False, "duration_s": 1.0}

        def fake_judge(config_arg, _call_result):
            """代替 judge_outcome：記下此刻 queue 裡的用量後停。"""
            seen["stored"] = runner.load_queue(config_arg).get("runner_state", {}).get("last_rate_limit")
            raise StopHere()

        # STEP 02: 執行到判讀為止
        with mock.patch.object(runner, "call_claude", fake_call), \
                mock.patch.object(runner, "save_session_output"), \
                mock.patch.object(runner, "judge_outcome", fake_judge):
            with self.assertRaises(StopHere):
                runner.process_one_entry(config, fixture["entry"])
        # STEP 03: 判讀時已經有值
        self.assertIsNotNone(seen.get("stored"), "判讀時用量還沒存進 queue")
        self.assertEqual(seen["stored"]["five_hour"]["utilization"], 42)


if __name__ == "__main__":
    unittest.main()
