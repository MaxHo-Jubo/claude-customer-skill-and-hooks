"""runner.py 對 sync commit 05aeecf 的 codex review 修正的回歸測試。

涵蓋兩條要改碼的 finding：
- CRITICAL：開斷點 PR 時 `gh pr create` 退出碼 0 卻沒印連結、再查**確定**沒有 open 的 PR，原本仍算開成（opened＋蓋章＋通知
  「已開 PR」）：hard 斷點的人工閘門等人放行一個不存在的 PR。修正後（user 選 B）只有 hard 走開啟失敗：保持 opening、以
  checkpoint_open_failed 暫停（連續第二次 hold）。soft／auto 沒有閘門，維持 (c1)：opened＋pr_unverified＋蓋章＋通知「連結未知」——
  改成失敗的話 entry 沒蓋章，auto 每完成一個模組再開一次（1.1.1 第六批 K1，test_checkpoint_hold 釘住）。再查**失敗**（無法確認）
  不分模式都是 (c1)。
- IMPORTANT：連結未知（pr_unverified）只在 opened 狀態補查。修正後 released／merged 也補查，merged 用 `gh pr list --state merged`
  （合併後的 PR 已不是 open），只補連結、清旗標，狀態不動；find_pr_by_head 的預設 state 仍是 open，其他呼叫點行為不變。

情境沿用 test_checkpoint_reconcile 的 CheckpointHarness（真 bare 遠端＋工作 repo、e1 done、e2 pending、wave 0 之後的 hard 斷點 w0；
CLI、額度、通知、等人放行隔離），gh 換成 fake_gh.write_scripted_gh（依 --head／--base／--state 過濾、記下每次呼叫的 --state）。

新增的字串（暫停原因、事件名）寫成字面值，不讀實作的常數——修正前的紅要是 AssertionError，不是 AttributeError。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 480; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_review_05aeecf.py -v
"""

import json
import os
import sys
import unittest

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runner  # noqa: E402  pylint: disable=wrong-import-position
from fake_gh import gh_commands, set_gh_modes  # noqa: E402  pylint: disable=wrong-import-position
from test_checkpoint_reconcile import (  # noqa: E402  pylint: disable=wrong-import-position
    CP_BRANCH,
    EXISTING_CP_PR_URL,
    OPEN_FAILED_REASON,
    CheckpointHarness,
    checkpoint,
    cp_pr,
)
from test_reconcile import HARD_CHECKPOINT_ID, events  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import ENTRY_ID, INTEGRATION_BRANCH  # noqa: E402  pylint: disable=wrong-import-position

# 開斷點成功時的通知事件名（hard 斷點「確定沒有 PR」不可以發它；soft／auto 要發、內文寫「連結未知」）
OPENED_NOTIFY_EVENT = "checkpoint_opened"
# 開啟失敗的說明裡「再查確定沒有」的字樣（操作者在 last_error／通知看到的）
CONFIRMED_ABSENT_NOTE = "再查也沒有 open 的 PR"
# (c1) 通知內文裡的字樣
UNVERIFIED_NOTE = "連結未知"
# `gh pr list --state` 的預設值與 merged 斷點要用的值（外部契約，寫成字面值）
EXPECTED_DEFAULT_STATE = "open"
EXPECTED_MERGED_STATE = "merged"
# 補查成功時記的事件名
VERIFIED_EVENT = "checkpoint_pr_verified"
# 一次開啟的 `pr list` 次數：create 前查一次、拿不到連結之後再查一次
LOOKUPS_PER_OPEN = 2
# (a) 重啟的次數（第一次暫停、第二次 hold）；每次重啟只該 create 一次，所以也是 create 的總次數
HOLD_CYCLE_RESTARTS = 2
# 預設 state 對照組裡的查詢次數：直接呼叫、頁面 PR、開斷點 PR 各一次
DEFAULT_CALLER_LOOKUPS = 3


def gh_list_states(gh):
    """假 gh 收到的每一次 `pr list` 帶的 --state（依序；沒帶是 None）。

    @param gh write_scripted_gh 的回傳值
    @return --state 值的清單；沒被呼叫過是空清單
    """
    # STEP 01: 紀錄檔不存在＝沒被呼叫過
    if not os.path.exists(gh["calls"]):
        return []
    # STEP 02: 逐行解析，只留 pr list
    with open(gh["calls"], encoding="utf-8") as handle:
        # 每一次呼叫的紀錄
        records = [json.loads(line) for line in handle if line.strip()]
    return [record["state"] for record in records if record["cmd"] == "pr list"]


class ConfirmedAbsentHarness(CheckpointHarness):
    """`gh pr create` 退出碼 0、印的不是連結、也沒真的建；create 前後的 `pr list` 都正常而且都沒有 PR（再查確定沒有）。"""

    def setUp(self):
        """CheckpointHarness 之上把 create 換成「退出碼 0、不印連結」。

        @return None
        """
        # STEP 01: 共用隔離＋拓撲；list 維持 ok（沒有任何 PR）
        super().setUp()
        set_gh_modes(self.gh, create_mode="nolink")

    def notified(self, event):
        """被 notify 的某個事件的所有呼叫參數（config, event, title, body）。

        @param event 事件名
        @return 參數 tuple 的清單
        """
        # STEP 01: 從 mock 的呼叫紀錄篩
        return [call.args for call in self.mocks["notify"].call_args_list if call.args[1] == event]

    def assert_unverified_and_stamped(self, checkpoint_id):
        """soft／auto「確定沒有」維持 (c1) 的共同斷言：opened＋pr_unverified、連結空白、e1 蓋章、通知含「連結未知」、只 create 一次。

        @param checkpoint_id 斷點 id
        @return None
        """
        # STEP 01: queue
        queue = runner.load_queue(self.config)
        # 落盤後的斷點
        found = runner.find_checkpoint(queue, checkpoint_id)
        self.assertEqual((found["status"], found.get("pr_url"), found.get("pr_unverified")), ("opened", "", True))
        self.assertEqual(runner.find_entry(queue, ENTRY_ID).get("checkpoint_id"), checkpoint_id, "K1：沒有閘門的斷點要照樣蓋章")
        # STEP 02: 通知與 gh 呼叫
        # 斷點開啟通知的內文
        bodies = [args[3] for args in self.notified(OPENED_NOTIFY_EVENT)]
        self.assertTrue(bodies and UNVERIFIED_NOTE in bodies[-1], bodies)
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)


class HardConfirmedAbsentTest(ConfirmedAbsentHarness):
    """(a) hard 斷點：再查確定沒有 PR → 仍是 opening、以 checkpoint_open_failed 暫停；再重啟同樣失敗 → hold。"""

    def test_hard_pauses_then_holds(self):
        """第一次重啟暫停（不等放行、不處理 e2）；第二次同原因同簽名 → hold，閘門仍在。

        修正前：算開成 → opened＋pr_unverified → 進入等待放行（等一個不存在的 PR）。

        @return None
        """
        # STEP 01: 第一次啟動：啟動時的斷點檢查開 w0
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        # 落盤後的 w0
        found = checkpoint(self.config)
        self.assertEqual(found["status"], "opening", "再查確定沒有 PR 不可以算開成")
        self.assertFalse(found.get("pr_unverified"), found)
        self.assertIn(CONFIRMED_ABSENT_NOTE, found.get("last_error") or "")
        self.assertIn(CP_BRANCH, found.get("last_error") or "")
        # 第一次暫停後的 runner_state
        state = self.runner_state()
        self.assertEqual(state.get("reason"), OPEN_FAILED_REASON, state)
        self.assertFalse(state.get("hold"), state)
        self.mocks["wait_for_release"].assert_not_called()
        self.mocks["process_one_entry"].assert_not_called()
        self.assertEqual(self.notified(OPENED_NOTIFY_EVENT), [])
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        # STEP 02: 第二次啟動：補開同樣失敗 → hold，閘門仍在
        self.assertEqual(self.restart(), runner.EXIT_PAUSED)
        self.assertTrue(self.runner_state().get("hold"), self.runner_state())
        self.assertEqual(checkpoint(self.config)["status"], "opening")
        self.mocks["wait_for_release"].assert_not_called()
        self.mocks["process_one_entry"].assert_not_called()
        self.assertEqual(gh_commands(self.gh).count("pr create"), HOLD_CYCLE_RESTARTS, "每次啟動只該 create 一次")


class SoftAutoConfirmedAbsentTest(ConfirmedAbsentHarness):
    """(b) soft／auto 斷點：再查確定沒有 PR → 維持 (c1)：opened＋pr_unverified＋蓋章＋通知「連結未知」（user 選 B，保住 K1）。"""

    def test_soft_stays_unverified_and_stamped(self):
        """soft 斷點（宣告的 w0 改成 soft）：不因「確定沒有」改成 failed。

        @return None
        """
        # STEP 01: 模組完成後的斷點檢查（只看宣告的斷點）
        self.set_checkpoint(mode="soft")
        self.assertEqual(runner.handle_checkpoints(self.config, include_auto=False), (False, HARD_CHECKPOINT_ID))
        # STEP 02: 斷言
        self.assert_unverified_and_stamped(HARD_CHECKPOINT_ID)

    def test_auto_stays_unverified_and_does_not_repeat(self):
        """auto 斷點（沒有宣告的斷點、門檻 1）：算開成＋蓋章；對同一份 queue 再呼叫不再 create、不另開新 id（K1）。

        @return None
        """
        # STEP 01: 模組完成後的斷點檢查觸發 auto，再對同一份狀態呼叫一次（沒有新模組完成）
        runner.mutate_queue(self.config, lambda queue: queue.update({"checkpoints": []}))
        self.config["checkpoint_max_modules"] = 1
        self.assertEqual(runner.handle_checkpoints(self.config), (False, None))
        self.assertEqual(runner.handle_checkpoints(self.config), (False, None))
        # STEP 02: 只有一筆 auto 記錄，而且是 opened＋連結未知＋蓋章、只 create 過一次
        # write-ahead 落盤的 auto 斷點
        seeded = runner.load_queue(self.config)["checkpoints"]
        self.assertEqual(len(seeded), 1, seeded)
        self.assert_unverified_and_stamped(seeded[0]["id"])

    def test_single_create_per_open(self):
        """對照組：同一次開啟只 create 一次、查兩次（create 前一次、拿不到連結後再查一次）。

        @return None
        """
        # STEP 01: 直接開一次 soft 的 w0
        self.set_checkpoint(mode="soft")
        runner.open_checkpoint(self.config, HARD_CHECKPOINT_ID)
        # STEP 02: 次數
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)
        self.assertEqual(gh_commands(self.gh).count("pr list"), LOOKUPS_PER_OPEN)


class RecheckFailedStillUnverifiedTest(CheckpointHarness):
    """對照組 (c1)：create 前的查詢正常、create 退出碼 0 沒印連結、再查失敗（無法確認）→ 仍是 opened＋pr_unverified。修正前後都綠。"""

    def test_recheck_failure_keeps_opened_unverified(self):
        """hard 斷點照常算開成（回 True、等人放行），連結未知、通知寫「連結未知」、只 create 一次。

        @return None
        """
        # STEP 01: 第一次 list 正常、之後的 list 失敗；create 不印連結
        set_gh_modes(self.gh, list_mode="ok_then_fail", list_ok_left=1, create_mode="nolink")
        self.assertEqual(runner.handle_checkpoints(self.config, include_auto=False), (True, HARD_CHECKPOINT_ID))
        # STEP 02: opened＋連結未知
        found = checkpoint(self.config)
        self.assertEqual((found["status"], found.get("pr_url"), found.get("pr_unverified")), ("opened", "", True))
        self.assertEqual(runner.find_entry(runner.load_queue(self.config), ENTRY_ID).get("checkpoint_id"), HARD_CHECKPOINT_ID)
        # STEP 03: 通知與次數
        # 斷點開啟通知的內文
        bodies = [call.args[3] for call in self.mocks["notify"].call_args_list if call.args[1] == OPENED_NOTIFY_EVENT]
        self.assertTrue(bodies and UNVERIFIED_NOTE in bodies[-1], bodies)
        self.assertEqual(gh_commands(self.gh).count("pr create"), 1)


class RefreshPassedCheckpointTest(CheckpointHarness):
    """(c)(d) released／merged 的斷點帶 pr_unverified 也補查：只補連結、清旗標，狀態不動；merged 用 --state merged 查。"""

    def seed_unverified(self, status, pr_state):
        """把 w0 改成指定狀態＋連結未知，GitHub 上有一支指定狀態的斷點 PR。

        @param status 斷點狀態
        @param pr_state GitHub 上那支 PR 的狀態（open／merged）
        @return 假 gh 路徑組
        """
        # STEP 01: queue 裡的 w0
        self.set_checkpoint(status=status, branch=CP_BRANCH, pr_url="", pr_unverified=True)
        # STEP 02: 假 gh（只有這一支 PR）
        return self.use_gh(prs=[dict(cp_pr(EXISTING_CP_PR_URL), state=pr_state)])

    def assert_filled(self, status):
        """補查之後：狀態仍是 status、連結補上、旗標清掉、記了補查成功的事件。

        @param status 預期（未變）的斷點狀態
        @return None
        """
        # STEP 01: 斷點
        found = checkpoint(self.config)
        self.assertEqual((found["status"], found.get("pr_url"), found.get("pr_unverified")), (status, EXISTING_CP_PR_URL, False))
        # STEP 02: 事件
        self.assertTrue(events(self.config, VERIFIED_EVENT))

    def test_released_open_pr_is_filled(self):
        """(c) released＋PR 仍 open → 用 --state open 查到、補上，狀態仍是 released。

        修正前：只補查 opened，released 被跳過、pr_url 永遠空白。

        @return None
        """
        # STEP 01: 補查
        gh = self.seed_unverified("released", "open")
        self.assertEqual(runner.refresh_unverified_checkpoint_prs(self.config), [HARD_CHECKPOINT_ID])
        # STEP 02: 斷言
        self.assert_filled("released")
        self.assertEqual(gh_list_states(gh), [EXPECTED_DEFAULT_STATE])

    def test_merged_pr_is_filled_with_merged_state(self):
        """(d) merged＋PR 已合併 → 用 --state merged 查到、補上，狀態仍是 merged。

        修正前：只補查 opened；只放寬過濾、仍用 open 查的話，合併後的 PR 永遠查不到。

        @return None
        """
        # STEP 01: 補查
        gh = self.seed_unverified("merged", "merged")
        self.assertEqual(runner.refresh_unverified_checkpoint_prs(self.config), [HARD_CHECKPOINT_ID])
        # STEP 02: 斷言（假 gh 收到的是 --state merged）
        self.assert_filled("merged")
        self.assertEqual(gh_list_states(gh), [EXPECTED_MERGED_STATE])

    def test_opened_still_queries_open(self):
        """對照組：opened 照舊用 --state open 查。

        @return None
        """
        # STEP 01: 補查
        gh = self.seed_unverified("opened", "open")
        self.assertEqual(runner.refresh_unverified_checkpoint_prs(self.config), [HARD_CHECKPOINT_ID])
        # STEP 02: 斷言
        self.assert_filled("opened")
        self.assertEqual(gh_list_states(gh), [EXPECTED_DEFAULT_STATE])


class DefaultLookupStateTest(CheckpointHarness):
    """對照組：find_pr_by_head 沒傳 state 的既有呼叫點仍帶 `--state open`。"""

    def test_default_callers_query_open(self):
        """直接呼叫、頁面 PR（push_branch_and_open_pr）、開斷點 PR（find_or_create_checkpoint_pr）三處都查 open。

        @return None
        """
        # STEP 01: 直接呼叫（沒有 PR）
        self.assertEqual(runner.find_pr_by_head(self.config, CP_BRANCH, INTEGRATION_BRANCH), (None, None))
        # STEP 02: 頁面 PR（查 → create）
        # 頁面 PR 的結果
        page_url, page_error = runner.push_branch_and_open_pr(self.config, self.fixture["entry"])
        self.assertIsNone(page_error)
        self.assertTrue(page_url)
        # STEP 03: 開斷點 PR（查 → create）
        self.assertTrue(runner.open_checkpoint(self.config, HARD_CHECKPOINT_ID))
        # STEP 04: 三次查詢都帶 --state open
        self.assertEqual(gh_list_states(self.gh), [EXPECTED_DEFAULT_STATE] * DEFAULT_CALLER_LOOKUPS)


if __name__ == "__main__":
    unittest.main()
