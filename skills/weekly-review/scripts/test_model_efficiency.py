"""model-efficiency.py 的已知答案測試：用暫存 transcript 驗證去重、工具呼叫、期間篩選與失敗路徑。

執行方式（在 scripts 目錄）：python3 -B -m unittest test_model_efficiency -v
"""

import contextlib
import datetime
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
# 被測腳本的路徑（檔名含連字號，不能直接 import，改用 importlib 載入）
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model-efficiency.py")
# 載入後的模組物件；各測試把它的 PROJECTS_ROOT 指到暫存目錄
SPEC = importlib.util.spec_from_file_location("model_efficiency", SCRIPT)
ME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ME)
# 一天的秒數，用來造期間內與期間外的時間戳
DAY = 86400
# 測試用的回顧天數
DAYS = 7


def iso(days_ago):
    """產生 N 天前的 ISO 時間字串（UTC、Z 結尾）。

    @param {number} days_ago 距今天數
    @returns {str} 例如 2026-10-19T09:37:12.000Z
    """
    # STEP 01: 現在時間往回推
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=days_ago * DAY)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def asst(mid, ts, content=None, out=1, cr=10, model="claude-sonnet-5-5", usage=True):
    """組一筆 assistant 記錄。

    @param {str|None} mid message.id；None 表示缺 id
    @param {str} ts ISO 時間字串
    @param {list|None} content content block 清單
    @param {int} out output_tokens
    @param {int} cr cache_read_input_tokens
    @param {str} model 模型名稱
    @param {bool} usage False 時 usage 給空物件
    @returns {dict} transcript 記錄
    """
    # STEP 01: 依參數組出 message
    msg = {"model": model, "content": content or [{"type": "text", "text": "x"}],
           "usage": {"input_tokens": 1, "output_tokens": out, "cache_read_input_tokens": cr, "cache_creation_input_tokens": 2} if usage else {}}
    if mid is not None:
        msg["id"] = mid
    return {"type": "assistant", "timestamp": ts, "message": msg}


class ModelEfficiencyTest(unittest.TestCase):
    """用暫存目錄當 PROJECTS_ROOT 的已知答案測試。"""

    def setUp(self):
        """建立暫存根目錄並把被測模組指過去。"""
        # STEP 01: 暫存目錄與模組路徑
        # 暫存 transcript 根目錄
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ME.PROJECTS_ROOT = self.tmp.name

    def write(self, rel, lines):
        """寫一個 transcript 檔。

        @param {str} rel 相對於根目錄的路徑
        @param {list} lines dict（轉成 JSON）或字串（原樣寫入）的清單
        @returns {None}
        """
        # STEP 01: 建目錄並逐行寫入
        # 目標檔的絕對路徑
        path = os.path.join(self.tmp.name, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")

    def test_same_id_counts_once_and_keeps_last_chunk(self):
        """同一 message.id 的多個 chunk 只計一次，且取最後一個 chunk 的 output_tokens。"""
        # STEP 01: 同 id 兩個 chunk，output 5 → 50
        self.write("-p/aaaaaaaa.jsonl", [asst("m1", iso(1), out=5), asst("m1", iso(1), out=50)])
        # 彙整結果
        d = ME.collect(DAYS)
        # STEP 02: 驗證
        c = d["by_model"][("claude-sonnet-5-5", "main")]
        self.assertEqual((c["n"], c["out"], c["cr"]), (1, 50, 10))

    def test_tool_calls_in_later_chunk_are_counted(self):
        """工具呼叫在後面的 chunk 時也要計入：Agent（haiku）與 advisor（server_tool_use）。"""
        # STEP 01: 第一個 chunk 純文字，第二個 chunk 帶工具呼叫
        agent = {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "general-purpose", "model": "haiku", "description": "d", "prompt": "p"}}
        advisor = {"type": "server_tool_use", "name": "advisor", "input": {}}
        self.write("-p/bbbbbbbb.jsonl", [asst("m1", iso(1)), asst("m1", iso(1), content=[agent, advisor])])
        d = ME.collect(DAYS)
        # STEP 02: 驗證
        self.assertEqual(sum(d["haiku_tasks"].values()), 1)
        self.assertEqual(sum(d["advisor_by_sid"].values()), 1)
        self.assertEqual(d["agent_calls"][("general-purpose", "haiku", "main")], 1)

    def test_unspecified_model_is_labelled_not_inherit(self):
        """Agent 沒帶 model 時標為「未指定」，不當成已確認的繼承。"""
        # STEP 01: Agent 呼叫不帶 model
        agent = {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "Explore", "prompt": "p"}}
        self.write("-p/cccccccc.jsonl", [asst("m1", iso(1), content=[agent])])
        d = ME.collect(DAYS)
        # STEP 02: 驗證
        self.assertEqual(d["agent_calls"][("Explore", ME.UNSPECIFIED_LABEL, "main")], 1)

    def test_out_of_window_messages_are_excluded(self):
        """期間外的訊息不計入。"""
        # STEP 01: 一則 30 天前、一則 1 天前
        self.write("-p/dddddddd.jsonl", [asst("old", iso(30)), asst("new", iso(1))])
        d = ME.collect(DAYS)
        # STEP 02: 驗證
        self.assertEqual(d["stats"]["messages"], 1)

    def test_bad_and_non_object_lines_are_counted(self):
        """JSON 解析失敗與合法但不是物件的行都計入壞行，且不中斷。"""
        # STEP 01: 三種壞行加一筆好記錄
        self.write("-p/eeeeeeee.jsonl", ["not json", "[]", "null", asst("m1", iso(1))])
        d = ME.collect(DAYS)
        # STEP 02: 驗證
        self.assertEqual((d["stats"]["bad_lines"], d["stats"]["messages"]), (3, 1))

    def test_null_fields_do_not_crash(self):
        """message 為 null、Agent 的 input／prompt 為 null 時不拋例外。"""
        # STEP 01: 子 agent 檔含 message=null 的 user 記錄；主檔含 input=null 與 prompt=null 的 Agent 呼叫
        self.write("-p/ffffffff/subagents/agent-1.jsonl", [{"type": "user", "message": None}, asst("m1", iso(1))])
        nulls = [{"type": "tool_use", "name": "Agent", "input": None},
                 {"type": "tool_use", "name": "Agent", "input": {"model": "haiku", "prompt": None, "description": None}}]
        self.write("-p/ffffffff.jsonl", [asst("m2", iso(1), content=nulls)])
        # STEP 02: 不拋例外，兩個 Agent 呼叫都計入
        d = ME.collect(DAYS)
        self.assertEqual(sum(d["agent_calls"].values()), 2)

    def test_session_started_before_window_is_excluded_from_first_turn_stats(self):
        """跨過期間起點的 session 不納入首輪 context 統計；期間內開始的才納入。"""
        # STEP 01: 兩個各 6 回合的 session，一個從 30 天前開始、一個從 1 天前開始
        started_before = [asst("o0", iso(30))] + [asst(f"o{i}", iso(1)) for i in range(1, 6)]
        started_inside = [asst(f"n{i}", iso(1)) for i in range(6)]
        self.write("-p/11111111.jsonl", started_before)
        self.write("-p/22222222.jsonl", started_inside)
        d = ME.collect(DAYS)
        # STEP 02: 只有期間內開始的那個（6 回合）被納入
        self.assertEqual([len(s) for s in d["sessions"]], [6])

    def test_missing_id_is_counted_per_record_and_reported(self):
        """缺 message.id 的記錄逐筆計價並計入 no_id。"""
        # STEP 01: 兩筆缺 id
        self.write("-p/33333333.jsonl", [asst(None, iso(1)), asst(None, iso(1))])
        d = ME.collect(DAYS)
        # STEP 02: 驗證
        self.assertEqual((d["stats"]["no_id"], d["stats"]["messages"]), (2, 2))

    def test_usage_without_fields_is_skipped_and_exit_is_one(self):
        """usage 為空物件的記錄不計價；沒有任何可用訊息時 main 回 1 並印 stderr。"""
        # STEP 01: 只有一筆 usage 為空的記錄
        self.write("-p/44444444.jsonl", [asst("m1", iso(1), usage=False)])
        d = ME.collect(DAYS)
        self.assertEqual((d["stats"]["no_usage"], d["stats"]["messages"]), (1, 0))
        # STEP 02: main 失敗並寫 stderr
        err = io.StringIO()
        argv = sys.argv
        sys.argv = ["model-efficiency.py", "--days", str(DAYS)]
        try:
            with contextlib.redirect_stderr(err):
                code = ME.main()
        finally:
            sys.argv = argv
        self.assertEqual(code, 1)
        self.assertIn("找不到任何 assistant 訊息", err.getvalue())

    def test_report_has_all_sections(self):
        """報告含所有 heading 與自檢段。"""
        # STEP 01: 一筆正常記錄
        self.write("-p/55555555.jsonl", [asst("m1", iso(1))])
        report = ME.render(DAYS, ME.collect(DAYS))
        # STEP 02: 驗證每個 heading
        for heading in ("### 模型 × 主/子 session", "### 專案占比", "### 主 session context 長度", "### Agent 呼叫",
                        "### advisor 呼叫：0 次", "### Haiku 任務清單", "### 自檢"):
            self.assertIn(heading, report)


if __name__ == "__main__":
    unittest.main()
