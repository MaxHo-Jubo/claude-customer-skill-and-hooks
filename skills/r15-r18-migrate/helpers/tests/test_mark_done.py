"""runner.py `mark-done` 子命令的測試：人工（本機）處理完的 entry，在佇列標成 done。

情境：某些 entry（例如 Redux actions 殼）R18 已有等價實作，改由人在本機處理並合進整合分支。runner 沒有其他方式把它們標成
done，而 eligible_entries 只挑「依賴全部 done」的 entry，下游會永遠輪不到。mark-done 補上這個缺口，安全條件是：
給的 commit 必須已經在**遠端**整合分支上（只在本機、只在 entry 分支、不存在的 commit 一律拒絕），且佇列在拒絕時原封不動。

拓撲一律用真的：bare 遠端 + 工作 repo（review_fixtures.build_fixture），不用假 git。
共用 fixture 從 review_fixtures 匯入（只匯入函式與常數，不匯入 TestCase）。

先紅：cmd_mark_done 還沒實作時，測試以 AssertionError 失敗（call_mark_done 先檢查它存在），不是 AttributeError。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest discover -s helpers/tests -p test_mark_done.py -v
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    ENTRY_BRANCH,
    ENTRY_ID,
    INTEGRATION_BRANCH,
    build_fixture,
    queue_entry,
    run_git,
)

# 下游 entry 的 id（依賴 ENTRY_ID）
DOWNSTREAM_ID = "downstream"
# 拒絕與失敗的退出碼（外部契約，寫成字面值以免與實作同步出錯）
EXIT_OK = 0
EXIT_USAGE = 64
EXIT_PREFLIGHT = 2
# 標記完成的事件名（外部契約）
MARKED_EVENT = "entry_marked_done"
# 提醒使用者對齊整合分支 tip 的指令片段
TIP_REMINDER = "--integration-tip"
# 不該被標成 done 的狀態：done 已經完成；running／waiting_quota 是 runner 正在處理
REFUSED_STATUSES = ("done", "running", "waiting_quota")
# 可以被標成 done 的狀態
ACCEPTED_STATUSES = ("pending", "blocked", "failed")


class MarkDoneTest(unittest.TestCase):
    """mark-done 的行為。"""

    def make_fixture(self, status="blocked"):
        """建立真實 git 環境；entry 預設是 blocked（人工接手的典型狀態）。

        @param status entry 的初始狀態
        @return build_fixture 的回傳值
        """
        # STEP 01: 暫存根目錄，測試結束時整個刪掉
        root = tempfile.mkdtemp(prefix="r18-markdone-")
        self.addCleanup(shutil.rmtree, root, True)
        # STEP 02: entry 帶著失敗的殘留欄位，用來驗證 done 會清掉它們
        return build_fixture(
            root,
            entry_overrides={"status": status, "blocked_reason": "needs_human", "last_error": "carry", "attempts": 2},
        )

    def merge_entry(self, fixture, push=True):
        """把 entry 分支快轉進整合分支；push 決定要不要推上遠端。

        @param fixture build_fixture 的回傳值
        @param push 是否推上遠端
        @return None
        """
        # STEP 01: build_fixture 結束時工作 repo 停在 entry 分支
        work = fixture["config"]["repo_dir"]
        run_git(work, "checkout", INTEGRATION_BRANCH)
        run_git(work, "merge", "--ff-only", ENTRY_BRANCH)
        if push:
            run_git(work, "push", "origin", INTEGRATION_BRANCH)

    def call_mark_done(self, fixture, entry_id=ENTRY_ID, commit=None, note=None):
        """呼叫 cmd_mark_done，回傳 (退出碼, stdout, stderr)。

        @param fixture build_fixture 的回傳值
        @param entry_id entry id
        @param commit 要標記的 commit；None 表示用 fixture 的 entry_sha
        @param note 備註
        @return (int, str, str)
        """
        # STEP 01: 先紅時要拿到 AssertionError，所以不直接 runner.cmd_mark_done
        handler = getattr(runner, "cmd_mark_done", None)
        self.assertIsNotNone(handler, "cmd_mark_done 尚未實作")
        args = argparse.Namespace(entry_id=entry_id, commit=commit or fixture["entry_sha"], note=note)
        # STEP 02: 輸出不是受測對象，但提醒文字要能斷言，所以收下來
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = handler(fixture["config"], args)
        return code, out.getvalue(), err.getvalue()

    def read_events(self, fixture):
        """讀事件紀錄。

        @param fixture build_fixture 的回傳值
        @return list[dict]
        """
        # STEP 01: 還沒有任何事件時檔案不存在，那是合法的「沒有事件」（拒絕的情況就是這樣）
        path = os.path.join(fixture["config"]["state_dir"], "runner.log.jsonl")
        if not os.path.exists(path):
            return []
        # STEP 02: 每行一個 JSON
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_marks_done_when_commit_is_on_remote_integration_branch(self):
        """commit 已在遠端整合分支：entry 變 done、殘留欄位清掉、commit 與時間寫回、事件帶 commit 與備註。

        @return None
        """
        # STEP 01: entry 已合併並推上遠端
        fixture = self.make_fixture()
        self.merge_entry(fixture)
        # STEP 02: 標記
        code, _out, _err = self.call_mark_done(fixture, note="本機處理，PR 已合併")
        self.assertEqual(code, EXIT_OK)
        # STEP 03: 落盤後的 entry
        _queue, entry = queue_entry(fixture)
        self.assertEqual(entry["status"], "done")
        self.assertIsNone(entry["blocked_reason"])
        self.assertIsNone(entry["last_error"])
        self.assertEqual(entry["last_commit"], fixture["entry_sha"])
        self.assertTrue(entry["finished_at"])
        # attempts 是歷史紀錄，不因人工標記而改寫
        self.assertEqual(entry["attempts"], 2)
        # STEP 04: 事件
        events = [item for item in self.read_events(fixture) if item.get("event") == MARKED_EVENT]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["entry"], ENTRY_ID)
        self.assertEqual(events[0]["detail"]["commit"], fixture["entry_sha"])
        self.assertEqual(events[0]["detail"]["note"], "本機處理，PR 已合併")

    def test_refuses_and_leaves_queue_untouched(self):
        """各種不該通過的輸入：拒絕、退出碼正確、佇列一個位元都不變。

        @return None
        """
        # STEP 01: (說明, 準備函式, entry_id, commit, 預期退出碼)。準備函式接 fixture
        def commit_only_on_entry_branch(_fixture):
            """entry 的 commit 只在 entry 分支，整合分支根本沒有。"""

        def merged_locally_not_pushed(fixture):
            """本機整合分支已有，但沒推上遠端：判準看的是遠端，不是本機。"""
            self.merge_entry(fixture, push=False)

        def fetch_broken(fixture):
            """遠端連不上：沒辦法確認，就不能標。"""
            work = fixture["config"]["repo_dir"]
            run_git(work, "remote", "set-url", "origin", os.path.join(os.path.dirname(work), "no-such.git"))

        cases = [
            ("commit 只在 entry 分支", commit_only_on_entry_branch, ENTRY_ID, None, EXIT_USAGE),
            ("只合併在本機、沒推遠端", merged_locally_not_pushed, ENTRY_ID, None, EXIT_USAGE),
            ("不存在的 commit", lambda fixture: self.merge_entry(fixture), ENTRY_ID, "0" * 40, EXIT_USAGE),
            ("不存在的 entry", lambda fixture: self.merge_entry(fixture), "no-such-entry", None, EXIT_USAGE),
            ("遠端連不上", fetch_broken, ENTRY_ID, None, EXIT_PREFLIGHT),
        ]
        for label, prepare, entry_id, commit, expected in cases:
            with self.subTest(label):
                fixture = self.make_fixture()
                prepare(fixture)
                before = runner.load_queue(fixture["config"])
                code, _out, err = self.call_mark_done(fixture, entry_id=entry_id, commit=commit)
                self.assertEqual(code, expected)
                self.assertTrue(err.strip(), "拒絕必須說明原因")
                self.assertEqual(runner.load_queue(fixture["config"]), before)
                self.assertEqual([item for item in self.read_events(fixture) if item.get("event") == MARKED_EVENT], [])

    def test_status_guard(self):
        """done／running／waiting_quota 拒絕（且佇列不變）；pending／blocked／failed 接受。

        @return None
        """
        # STEP 01: 拒絕組
        for status in REFUSED_STATUSES:
            with self.subTest("拒絕 %s" % status):
                fixture = self.make_fixture(status=status)
                self.merge_entry(fixture)
                before = runner.load_queue(fixture["config"])
                code, _out, err = self.call_mark_done(fixture)
                self.assertEqual(code, EXIT_USAGE)
                self.assertTrue(err.strip())
                self.assertEqual(runner.load_queue(fixture["config"]), before)
        # STEP 02: 接受組（對照組：同樣的準備，只有狀態不同，證明上面的拒絕是狀態造成的）
        for status in ACCEPTED_STATUSES:
            with self.subTest("接受 %s" % status):
                fixture = self.make_fixture(status=status)
                self.merge_entry(fixture)
                code, _out, _err = self.call_mark_done(fixture)
                self.assertEqual(code, EXIT_OK)
                self.assertEqual(queue_entry(fixture)[1]["status"], "done")

    def test_downstream_becomes_eligible(self):
        """這個子命令存在的理由：標 done 之前下游不能被取件，之後可以。

        @return None
        """
        # STEP 01: 加一個依賴 ENTRY_ID 的下游 entry
        fixture = self.make_fixture()
        self.merge_entry(fixture)

        def add_downstream(queue):
            """登記下游 entry。"""
            queue["modules"].append(
                dict(runner.RUNTIME_FIELD_DEFAULTS, id=DOWNSTREAM_ID, type="page", wave=0, r15_paths=["x.js"], depends_on=[ENTRY_ID])
            )

        runner.mutate_queue(fixture["config"], add_downstream)
        # STEP 02: 之前不可取件
        before_ids = [item["id"] for item in runner.eligible_entries(runner.load_queue(fixture["config"]))]
        self.assertNotIn(DOWNSTREAM_ID, before_ids)
        # STEP 03: 標記後可取件
        code, _out, _err = self.call_mark_done(fixture)
        self.assertEqual(code, EXIT_OK)
        after_ids = [item["id"] for item in runner.eligible_entries(runner.load_queue(fixture["config"]))]
        self.assertIn(DOWNSTREAM_ID, after_ids)

    def test_does_not_touch_runner_counters(self):
        """人工標記不是 runner 的一次成功：熔斷計數不歸零，整合分支 tip 記錄也不動（對齊是 unblock --integration-tip 的事）。

        @return None
        """
        # STEP 01: 預先把計數設成非零
        fixture = self.make_fixture()
        self.merge_entry(fixture)
        runner.mutate_queue(fixture["config"], lambda queue: queue["runner_state"].update({"consecutive_failures": 2}))
        # STEP 02: 標記
        code, _out, _err = self.call_mark_done(fixture)
        self.assertEqual(code, EXIT_OK)
        queue = runner.load_queue(fixture["config"])
        self.assertEqual(queue["runner_state"]["consecutive_failures"], 2)
        self.assertEqual(queue["integration_tip_sha"], fixture["base_sha"])

    def test_reminds_to_realign_integration_tip_only_when_needed(self):
        """遠端整合分支 tip 與記錄不同（人工合併造成）：提醒 unblock --integration-tip；已對齊就不囉嗦。

        @return None
        """
        # STEP 01: 記錄還是基線、遠端已前進 → 要提醒
        fixture = self.make_fixture()
        self.merge_entry(fixture)
        code, out, err = self.call_mark_done(fixture)
        self.assertEqual(code, EXIT_OK)
        self.assertIn(TIP_REMINDER, out + err)
        # STEP 02: 對照組：記錄已對齊遠端 → 不提醒
        fixture = self.make_fixture()
        self.merge_entry(fixture)
        runner.mutate_queue(fixture["config"], lambda queue: queue.update({"integration_tip_sha": fixture["entry_sha"]}))
        code, out, err = self.call_mark_done(fixture)
        self.assertEqual(code, EXIT_OK)
        self.assertNotIn(TIP_REMINDER, out + err)


def parse_quietly(argv):
    """解析命令列；解析失敗（SystemExit）轉成測試失敗，不讓它以 error 的形式冒出來。

    @param argv 參數清單
    @return argparse.Namespace
    """
    # STEP 01: argparse 出錯會印說明並 SystemExit，先收下說明再轉成 AssertionError
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return runner.build_parser().parse_args(argv)
    except SystemExit:
        raise AssertionError("命令列解析失敗: %s" % err.getvalue().strip()[-200:]) from None


class MarkDoneParserTest(unittest.TestCase):
    """命令列介面。"""

    def test_parser_accepts_entry_commit_and_note(self):
        """mark-done <entry> --commit <sha> [--note 文字]。

        @return None
        """
        args = parse_quietly(["mark-done", "e1", "--commit", "abc123", "--note", "備註"])
        self.assertEqual((args.command, args.entry_id, args.commit, args.note), ("mark-done", "e1", "abc123", "備註"))

    def test_commit_is_required(self):
        """沒給 --commit 不能通過：不存在「不驗證就標」的用法。

        @return None
        """
        # STEP 01: 對照組：帶 --commit 必須能解析。沒有這一步的話，子命令根本不存在時 argparse 一樣會 SystemExit，
        # 這個測試在實作前後都是綠的
        self.assertEqual(parse_quietly(["mark-done", "e1", "--commit", "abc123"]).commit, "abc123")
        # STEP 02: 不帶 --commit 才是受測對象
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                runner.build_parser().parse_args(["mark-done", "e1"])


if __name__ == "__main__":
    unittest.main()
