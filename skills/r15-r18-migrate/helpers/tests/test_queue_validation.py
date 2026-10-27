"""queue.json 斷點記錄的載入驗證（validate_queue_checkpoints）與 covered_entries 的語意（checkpoint_covered_ids）。

起因：1.2.2 第三輪 review 的 D 組——load_queue 只做 json.load，斷點狀態是未知值、covered_entries 是字串時，
unattempted_done_entries 這類「跳過 PENDING、其餘一律當已嘗試」的黑名單會讓整批 entry 永遠不補開也沒有通知；
而 covered_entries 為 None 的舊記錄在三個讀取點的處理刻意不同，需要一個集中定義並用測試釘住的地方。
fixture 建立階段（review_fixtures.build_fixture）會執行 git（init、commit、push）；這裡只取它的 config 與 queue.json 路徑，
受測的驗證與涵蓋集合邏輯本身不查詢 git。

執行方式（在 skill 根目錄）：
    perl -e 'alarm 150; exec @ARGV' python3 -B -m unittest helpers.tests.test_queue_validation -v
"""

import json
import os
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
    IMPOSSIBLE_SHA,
    INTEGRATION_BRANCH,
    build_fixture,
)

# 讀不到整合分支 tip 時，呼叫端傳給 begin_checkpoint_opening 的凍結點
NO_FROZEN_TIP = None
# 驗證會擋的 covered_entries 型別錯誤案例：(案例名, 值)
BAD_COVERED_CASES = [
    ("字串（會被拆成字元）", "abc"),
    ("整數", 7),
    ("dict", {"a": 1}),
    ("list 含整數", ["a", 1]),
    ("list 含 None", [None]),
    ("巢狀 list", [["a"]]),
]
# 驗證會擋的狀態案例：(案例名, 值)；None 代表欄位存在但值是 null
BAD_STATUS_CASES = [
    ("大小寫不對", "OPENED"),
    ("entry 才有的狀態", "done"),
    ("空字串", ""),
    ("null", None),
    ("拼錯", "openning"),
    ("list（unhashable，成員檢查會丟 TypeError）", []),
    ("dict（unhashable，成員檢查會丟 TypeError）", {}),
    ("整數", 3),
]
# 驗證會擋的容器形狀案例：(案例名, 整個 checkpoints 欄位的值)
BAD_CONTAINER_CASES = [
    ("checkpoints 是 null", None),
    ("checkpoints 是字串", "cp"),
    ("checkpoints 是 dict", {"id": "cp"}),
    ("元素是 null", [None]),
    ("元素是字串", ["cp"]),
    ("元素是 list", [[]]),
]
# 合法的 covered_entries 值：(標籤, 值)；None＝舊記錄，空 list＝確定沒涵蓋，字串 list＝涵蓋這些 entry
VALID_COVERED_CASES = [("none", None), ("empty", []), ("ids", ["a", "b"])]


def make_entry(entry_id, last_commit=IMPOSSIBLE_SHA, checkpoint_id=None):
    """組一個 done 的 queue entry（只填測試用得到的欄位，其餘取 runner 的預設）。

    @param entry_id entry id
    @param last_commit entry 的 last_commit
    @param checkpoint_id 已蓋章的斷點 id；None＝未蓋章
    @return 新的 entry dict
    """
    # STEP 01: 預設欄位 + 測試欄位
    return {
        **runner.RUNTIME_FIELD_DEFAULTS,
        "id": entry_id,
        "branch": "%s-branch" % entry_id,
        "type": "page",
        "wave": 0,
        "r18_dir": "pages/%s" % entry_id,
        "r15_paths": ["frontend/react_15/%s.js" % entry_id],
        "status": "done",
        "last_commit": last_commit,
        "checkpoint_id": checkpoint_id,
    }


def make_checkpoint(checkpoint_id, status, **fields):
    """組一個斷點記錄（取 runner 的預設欄位，再蓋上指定欄位）。

    @param checkpoint_id 斷點 id
    @param status 斷點狀態（測試壞資料時可傳非法值）
    @param fields 要覆寫的欄位（例如 covered_entries）
    @return 新的斷點 dict
    """
    # STEP 01: 預設欄位 + id／mode／pr_base + 指定欄位（後者覆寫前者）
    return {
        **runner.CHECKPOINT_FIELD_DEFAULTS,
        "id": checkpoint_id,
        "after": {"wave": None},
        "mode": "soft",
        "pr_base": "base",
        "status": status,
        **fields,
    }


def without(record, key):
    """回傳拿掉指定欄位的新 dict（模擬欄位缺漏的舊記錄）。

    @param record 原 dict
    @param key 要拿掉的欄位
    @return 新的 dict，不含 key
    """
    # STEP 01: 篩掉該欄位
    return {name: value for name, value in record.items() if name != key}


def write_raw_queue(config, drop=(), **fields):
    """直接讀寫 queue.json 檔案、覆寫指定欄位（繞過 load_queue 的驗證，用來造壞檔或乾淨的初始內容）。

    走 load_queue／mutate_queue 的話，前一個案例留下的壞檔會先被驗證擋掉，所以測試資料一律用這個寫。

    @param config runner 設定
    @param drop 要從頂層拿掉的欄位名
    @param fields 要覆寫的頂層欄位（例如 modules、checkpoints）
    @return None
    """
    # STEP 01: 讀目前的內容
    path = runner.queue_file(config)
    with open(path, "r", encoding="utf-8") as handle:
        queue = json.load(handle)
    # STEP 02: 拿掉 drop 的欄位、蓋上 fields，原子寫回
    runner.atomic_write_json(path, {**{name: value for name, value in queue.items() if name not in drop}, **fields})


class QueueCheckpointValidationTest(unittest.TestCase):
    """load_queue 對斷點記錄形狀的驗證。"""

    def setUp(self):
        """每個測試一組全新的 fixture（只用它的 config 與 queue.json）。

        @return None
        """
        # STEP 01: 測試用的狀態目錄與 runner 設定
        self.config = build_fixture(tempfile.mkdtemp(prefix="r18-qvalid-"))["config"]

    def assert_load_raises_queue_corrupt(self, *expected_fragments):
        """load_queue 丟 ValueError，訊息帶 queue_corrupt 與指定片段。

        @param expected_fragments 訊息裡必須出現的片段
        @return None
        """
        # STEP 01: 載入必須失敗
        with self.assertRaises(ValueError) as caught:
            runner.load_queue(self.config)
        # STEP 02: 訊息帶 queue_corrupt 與指定片段
        message = str(caught.exception)
        self.assertIn("queue_corrupt", message)
        for fragment in expected_fragments:
            self.assertIn(fragment, message)

    def test_unknown_status_raises_with_the_checkpoint_id(self):
        """斷點狀態不是 CheckpointStatus.ALL 的成員（含非字串）：load_queue 丟 ValueError，訊息帶 queue_corrupt、斷點 id 與實際值。

        @return None
        """
        # STEP 01: 逐案例造壞檔再載入
        for name, bad_status in BAD_STATUS_CASES:
            with self.subTest(case=name):
                # STEP 01.01: 壞檔
                write_raw_queue(self.config, checkpoints=[make_checkpoint("cp-bad", bad_status)])
                # STEP 01.02: 載入失敗，訊息指出斷點與實際值
                self.assert_load_raises_queue_corrupt("cp-bad", repr(bad_status))

    def test_missing_status_key_raises(self):
        """斷點記錄連 status 欄位都沒有：視同未知狀態，不當成 pending 放行。

        @return None
        """
        # STEP 01: 拿掉 status 欄位
        write_raw_queue(self.config, checkpoints=[without(make_checkpoint("cp-nostatus", "pending"), "status")])
        # STEP 02: 載入失敗
        self.assert_load_raises_queue_corrupt("cp-nostatus")

    def test_malformed_containers_raise_value_error_not_type_error(self):
        """checkpoints 不是 list、或元素不是 JSON 物件：一律 ValueError（queue_corrupt），不是 TypeError／AttributeError。

        呼叫端的 queue_corrupt 處理只接 ValueError；其他例外型別會讓啟動錯誤處理與暫停通知一起失敗。

        @return None
        """
        # STEP 01: 逐案例造壞檔再載入
        for name, bad_checkpoints in BAD_CONTAINER_CASES:
            with self.subTest(case=name):
                # STEP 01.01: 壞檔
                write_raw_queue(self.config, checkpoints=bad_checkpoints)
                # STEP 01.02: 載入失敗
                self.assert_load_raises_queue_corrupt("checkpoints")

    def test_covered_entries_of_the_wrong_type_raises(self):
        """covered_entries 不是 None 或字串 list：load_queue 丟 ValueError（字串會被拆成字元、非字串元素永遠對不上 entry id）。

        @return None
        """
        # STEP 01: 逐案例造壞檔再載入
        for name, bad_covered in BAD_COVERED_CASES:
            with self.subTest(case=name):
                # STEP 01.01: 壞檔
                write_raw_queue(self.config, checkpoints=[make_checkpoint("cp-cov", "failed", covered_entries=bad_covered)])
                # STEP 01.02: 載入失敗，訊息指出欄位與斷點
                self.assert_load_raises_queue_corrupt("covered_entries", "cp-cov")

    def test_valid_shapes_load_for_every_status(self):
        """每個合法狀態 × covered_entries 為 None／空 list／字串 list／欄位缺漏：都能載入，內容原樣。

        @return None
        """
        # STEP 01: 全部組合寫進同一份 queue
        checkpoints = [
            make_checkpoint("%s-%s" % (status, label), status, covered_entries=covered)
            for status in sorted(runner.CheckpointStatus.ALL)
            for label, covered in VALID_COVERED_CASES
        ] + [
            without(make_checkpoint("%s-missing" % status, status), "covered_entries")
            for status in sorted(runner.CheckpointStatus.ALL)
        ]
        write_raw_queue(self.config, checkpoints=checkpoints)
        # STEP 02: 載入不丟例外，筆數與 id 不變
        loaded = runner.load_queue(self.config)
        self.assertEqual([checkpoint["id"] for checkpoint in loaded["checkpoints"]], [checkpoint["id"] for checkpoint in checkpoints])

    def test_queue_without_a_checkpoints_key_loads(self):
        """沒有 checkpoints 欄位（沒宣告任何斷點）合法。

        @return None
        """
        # STEP 01: 拿掉欄位後載入
        write_raw_queue(self.config, drop=("checkpoints",))
        self.assertNotIn("checkpoints", runner.load_queue(self.config))

    def test_mutate_queue_rejects_a_corrupt_file_before_calling_the_mutator(self):
        """mutate_queue 在鎖內重讀也走 load_queue：壞檔不會被 mutator 拿到、也不會被寫回。

        @return None
        """
        # STEP 01: 造壞檔
        write_raw_queue(self.config, checkpoints=[make_checkpoint("cp-bad", "bogus")])
        # 被呼叫就記下來的旗標 list
        called = []

        def record_call(queue):
            """代替真正的 mutator：被呼叫就留下記錄。

            @param queue 鎖內重讀的 queue（本測試不該走到這裡）
            @return None
            """
            # STEP 01: 留下記錄
            called.append(queue)

        # STEP 02: mutator 不得被呼叫，例外往外拋
        with self.assertRaises(ValueError):
            runner.mutate_queue(self.config, record_call)
        self.assertEqual(called, [])

    def test_status_all_matches_the_public_status_constants(self):
        """CheckpointStatus.ALL 與類別上所有公開的狀態常數一致：新增狀態常數卻忘了加進 ALL，驗證會把它當成壞資料。

        @return None
        """
        # STEP 01: 收集類別上大寫開頭、值是字串的常數（排除 ALL 本身）
        declared = {value for name, value in vars(runner.CheckpointStatus).items() if name.isupper() and name != "ALL" and isinstance(value, str)}
        self.assertEqual(runner.CheckpointStatus.ALL, frozenset(declared))


class CheckpointCoveredIdsTest(unittest.TestCase):
    """checkpoint_covered_ids 與三個讀取點對 None（舊記錄）的刻意不同處理。"""

    def test_none_missing_and_empty_are_distinguished(self):
        """欄位缺漏與 null 是「涵蓋範圍不明」（None）；空 list 是「確定什麼都沒涵蓋」（空集合），兩者不可混為一談。

        @return None
        """
        # STEP 01: 缺漏、null → None
        self.assertIsNone(runner.checkpoint_covered_ids({}))
        self.assertIsNone(runner.checkpoint_covered_ids({"covered_entries": None}))
        # STEP 02: 空 list → 空集合（不是 None）；字串 list → frozenset
        self.assertEqual(runner.checkpoint_covered_ids({"covered_entries": []}), frozenset())
        self.assertIsNotNone(runner.checkpoint_covered_ids({"covered_entries": []}))
        self.assertEqual(runner.checkpoint_covered_ids({"covered_entries": ["a", "b"]}), frozenset({"a", "b"}))

    def test_legacy_none_is_read_differently_by_design_at_the_three_readers(self):
        """同一筆 covered_entries 為 None 的舊記錄：蓋章時蓋全部、完成出口補看時不涵蓋任何 entry、完成通知時有未蓋章就列入。

        @return None
        """
        # STEP 01: 兩個 done 未蓋章的 entry + 一筆 failed 的舊記錄
        queue = {"modules": [make_entry("a"), make_entry("b")], "checkpoints": [make_checkpoint("legacy", "failed", covered_entries=None)]}
        # STEP 02: 完成出口補看：舊記錄不涵蓋任何 entry，兩個都算沒嘗試過
        self.assertEqual([entry["id"] for entry in runner.unattempted_done_entries(queue)], ["a", "b"])
        # STEP 03: 完成通知：還有未蓋章的 done entry，就列入
        self.assertEqual([checkpoint["id"] for checkpoint in runner.failed_checkpoints_with_unstamped_entries(queue)], ["legacy"])
        # STEP 04: 蓋章：舊記錄蓋所有未蓋章的 done entry（stamp_covered_entries 在 mutator 內就地蓋章是刻意設計）
        runner.stamp_covered_entries(queue, queue["checkpoints"][0])
        self.assertEqual([entry["checkpoint_id"] for entry in queue["modules"]], ["legacy", "legacy"])
        # STEP 05: 蓋完之後沒有未蓋章的 entry：完成通知不再列入
        self.assertEqual(runner.failed_checkpoints_with_unstamped_entries(queue), [])

    def test_empty_covered_list_covers_nothing_at_every_reader(self):
        """covered_entries 是空 list（確定沒涵蓋）：三個讀取點一致——不蓋章、不排除、不列入通知。

        @return None
        """
        # STEP 01: 兩個 done 未蓋章的 entry + 一筆 failed、涵蓋範圍為空的記錄
        queue = {"modules": [make_entry("a"), make_entry("b")], "checkpoints": [make_checkpoint("empty", "failed", covered_entries=[])]}
        # STEP 02: 補看：沒有任何 entry 被排除
        self.assertEqual([entry["id"] for entry in runner.unattempted_done_entries(queue)], ["a", "b"])
        # STEP 03: 通知：交集為空，不列入
        self.assertEqual(runner.failed_checkpoints_with_unstamped_entries(queue), [])
        # STEP 04: 蓋章：一個都不蓋
        runner.stamp_covered_entries(queue, queue["checkpoints"][0])
        self.assertEqual([entry["checkpoint_id"] for entry in queue["modules"]], [None, None])


class CoveredEntriesInvariantTest(unittest.TestCase):
    """新資料不變量：所有離開 PENDING 的寫入都同時留下非 None 的 covered_entries（舊記錄之外不會出現 None）。"""

    def setUp(self):
        """每個測試一組全新的 fixture，queue 裡放兩個 done 未蓋章的 entry 與兩個宣告的 pending 斷點。

        @return None
        """
        # STEP 01: 測試用的狀態目錄與 runner 設定；新建 auto 斷點時 pr_base 取 base_branch
        self.config = build_fixture(tempfile.mkdtemp(prefix="r18-qinvariant-"))["config"]
        self.config.update({"base_branch": INTEGRATION_BRANCH})
        # STEP 02: 兩個 done entry + 兩個宣告的 pending 斷點（分別對應讀得到／讀不到 tip）
        write_raw_queue(
            self.config,
            modules=[make_entry("a"), make_entry("b")],
            checkpoints=[make_checkpoint("declared-tip", "pending"), make_checkpoint("declared-no-tip", "pending")],
        )

    def test_every_path_out_of_pending_records_a_covered_list(self):
        """宣告的 pending 斷點與新建的 auto 斷點 × 讀得到／讀不到整合分支 tip：begin_checkpoint_opening 之後都帶非 None 的涵蓋集合。

        @return None
        """
        # STEP 01: 四種組合各用不同的斷點 id（auto 斷點沿用 queue 裡不存在的 id 即新建）
        cases = [
            ("declared-tip", IMPOSSIBLE_SHA, "宣告的斷點、讀得到 tip"),
            ("declared-no-tip", NO_FROZEN_TIP, "宣告的斷點、讀不到 tip"),
            ("auto-with-tip", IMPOSSIBLE_SHA, "新的 auto 斷點、讀得到 tip"),
            ("auto-no-tip", NO_FROZEN_TIP, "新的 auto 斷點、讀不到 tip"),
        ]
        for checkpoint_id, frozen_sha, label in cases:
            with self.subTest(case=label):
                # STEP 01.01: 開啟的 write-ahead
                record = runner.begin_checkpoint_opening(self.config, checkpoint_id, "cp-%s" % checkpoint_id, "標題", frozen_sha)
                # STEP 01.02: 離開了 PENDING，而且同一次寫入帶著涵蓋集合
                self.assertNotEqual(record["status"], runner.CheckpointStatus.PENDING)
                self.assertEqual(record["covered_entries"], ["a", "b"])
        # STEP 02: 落盤後再讀一次也是（不只回傳值）
        for checkpoint in runner.load_queue(self.config)["checkpoints"]:
            self.assertEqual(checkpoint["covered_entries"], ["a", "b"], checkpoint["id"])

    def test_declared_pending_checkpoint_starts_with_none(self):
        """對照組：PENDING 的斷點還沒開始開啟，covered_entries 是 None（正常的初始值，不是舊記錄）。

        @return None
        """
        # STEP 01: 宣告的斷點尚未開啟
        declared = [checkpoint for checkpoint in runner.load_queue(self.config)["checkpoints"] if checkpoint["id"] == "declared-tip"][0]
        self.assertEqual(declared["status"], runner.CheckpointStatus.PENDING)
        self.assertIsNone(declared["covered_entries"])


if __name__ == "__main__":
    unittest.main()
