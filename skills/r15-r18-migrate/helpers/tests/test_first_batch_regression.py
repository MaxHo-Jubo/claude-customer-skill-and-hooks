"""runner.py 1.1.1 第一批修復（2026-09-18）補的回歸測試（1.1.2 第六批）。

第一批修復當時只在暫存目錄驗過、沒有留下測試；這裡補上四組：
ProcessLock 的互斥（兩個行程／兩個 fd 搶同一把 flock）、mutate_queue 的併發讀-改-寫、
file_sha1 對真檔案的行為（含 file_sha1_or_none）、git_out_or_raise 的成功與失敗路徑。
外部狀態一律用真的：真檔案、真 flock、真行程（subprocess）、真 git repo；不 mock。
每個跨行程的等待都有上限（SCENARIO_TIMEOUT_SECONDS），runner 卡住時測試判定失敗而不是跟著卡。

執行方式（在 skill 根目錄）：
    python3 -B -m unittest discover -s helpers/tests -v
只跑這個檔：
    python3 -B -m unittest discover -s helpers/tests -p test_first_batch_regression.py -v

`-B` 與下方的 `sys.dont_write_bytecode` 是為了不在 skill 目錄留下 __pycache__。
"""

import hashlib
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)

import runner  # noqa: E402  pylint: disable=wrong-import-position
from review_fixtures import (  # noqa: E402  pylint: disable=wrong-import-position
    SCENARIO_TIMEOUT_SECONDS,
    run_git,
    wait_until_gone,
)

# 等被 SIGKILL 的持鎖行程真的消失的上限（秒）：核心要在行程的 fd 全部關閉時才放掉 flock
HOLDER_EXIT_WAIT_SECONDS = 5
# 同時做讀-改-寫的行程數：要大於 1 才有競爭；4 個在筆電上幾秒內跑完
CONCURRENT_WORKERS = 4
# 每個行程做幾次遞增：總次數 = CONCURRENT_WORKERS × 這個值
INCREMENTS_PER_WORKER = 25
# mutator 讀到舊值之後、寫回之前停多久（秒）：把「讀」和「寫」拉開，沒有鎖時丟更新幾乎必然發生
MUTATOR_HOLD_SECONDS = 0.002
# 造長 stderr 用的 pathspec 長度：git 會把它原樣印進錯誤訊息，要明顯超過 runner.STDERR_EXCERPT_CHARS 才驗得到截斷
LONG_PATHSPEC_LENGTH = 250
# 測試檔內容的大小（bytes）：大於一般讀取緩衝區（64 KiB），確認不是只算到第一個區塊
SHA1_SAMPLE_SIZE = 200 * 1024
# 單一位元組的值域大小（0..255 共 256 種）：樣本內容以它取模循環，確保每種位元組值（含非 UTF-8）都出現
BYTE_VALUE_RANGE = 256

# 在獨立行程裡建一個 ProcessLock 並回報結果；argv[1] = helpers 目錄，argv[2] = 鎖檔，
# argv[3] = "hold" 表示拿到後不放、睡到被殺為止，其他值表示回報完就結束
LOCK_CONTENDER_SCENARIO = """
import sys, time
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
lock = runner.ProcessLock(sys.argv[2])
print("ACQUIRED" if lock.acquire() else "BUSY", flush=True)
if sys.argv[3] == "hold":
    time.sleep(600)
"""

# 在獨立行程裡對同一個 queue.json 做 argv[3] 次 mutate_queue 遞增；argv[1] = helpers 目錄，argv[2] = 狀態目錄。
# mutator 讀到舊值後刻意停一下再寫（MUTATOR_HOLD_SECONDS），讓「沒有互斥」的實作一定會丟更新
QUEUE_INCREMENT_SCENARIO = """
import sys, time
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
config = {"state_dir": sys.argv[2]}
def increment(queue):
    value = queue["counter"]
    time.sleep(%s)
    queue["counter"] = value + 1
for _ in range(int(sys.argv[3])):
    runner.mutate_queue(config, increment)
print("DONE", flush=True)
""" % MUTATOR_HOLD_SECONDS

# 在獨立行程裡不持鎖地反覆讀 queue.json，直到 argv[3] 這個檔出現；印出「讀了幾次 讀到不合法內容幾次」。
# 寫入者用暫存檔 + os.replace，所以任何時刻讀到的都該是完整 JSON；argv[1] = helpers 目錄，argv[2] = 狀態目錄
QUEUE_READER_SCENARIO = """
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
config = {"state_dir": sys.argv[2]}
reads = invalid = 0
while not os.path.exists(sys.argv[3]):
    reads += 1
    try:
        runner.load_queue(config)
    except (ValueError, FileNotFoundError):
        invalid += 1
print("%d %d" % (reads, invalid), flush=True)
"""


def run_scenario(script, *args):
    """跑一個情境腳本到結束（有上限），回傳 CompletedProcess。

    @param script 情境腳本原始碼
    @param args 傳給腳本的 argv[1:]
    @return subprocess.CompletedProcess
    """
    # STEP 01: timeout 到了 subprocess.run 會殺掉子行程並拋 TimeoutExpired，測試直接失敗而不是卡住
    return subprocess.run(
        [sys.executable, "-B", "-c", script] + list(args),
        capture_output=True, text=True, timeout=SCENARIO_TIMEOUT_SECONDS, check=False,
    )


def read_line_with_timeout(process, limit_seconds):
    """從子行程 stdout 讀一行，最多等 limit_seconds；逾時回 None。

    @param process 以 stdout=PIPE、text=True 啟動的 Popen
    @param limit_seconds 等待上限（秒）
    @return 去掉換行的一行字串，或 None
    """
    # STEP 01: 先用 select 等到可讀，避免 readline 在子行程卡住時永遠等下去
    ready, _w, _x = select.select([process.stdout], [], [], limit_seconds)
    if not ready:
        return None
    return process.stdout.readline().strip()


class ProcessLockContentionTest(unittest.TestCase):
    """ProcessLock：同一個鎖檔同時只能有一個持有者；持有者放掉或死掉之後，下一個要拿得到。"""

    def setUp(self):
        """每個測試一個獨立的鎖檔。"""
        # STEP 01: 暫存目錄（測試結束刪除）與其中的鎖檔路徑
        # 放鎖檔的暫存目錄
        self.workdir = tempfile.mkdtemp(prefix="r18-lock-")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        # 受測的鎖檔路徑（還不存在，由 ProcessLock 建立）
        self.lock_path = os.path.join(self.workdir, "runner.lock")

    def test_other_process_cannot_acquire_until_released(self):
        """本行程持鎖時，另一個行程 acquire 要回 False；本行程 release 之後，另一個行程要拿得到。"""
        # STEP 01: 本行程先拿到
        holder = runner.ProcessLock(self.lock_path)
        self.assertTrue(holder.acquire())
        self.addCleanup(holder.release)

        # STEP 02: 另一個行程搶同一把鎖要拿不到
        busy = run_scenario(LOCK_CONTENDER_SCENARIO, HELPERS_DIR, self.lock_path, "once")
        self.assertEqual(busy.returncode, 0, busy.stderr)
        self.assertEqual(busy.stdout.strip(), "BUSY")

        # STEP 03: 放掉之後再搶一次要拿得到
        holder.release()
        free = run_scenario(LOCK_CONTENDER_SCENARIO, HELPERS_DIR, self.lock_path, "once")
        self.assertEqual(free.returncode, 0, free.stderr)
        self.assertEqual(free.stdout.strip(), "ACQUIRED")

    def test_lock_is_freed_when_holder_is_killed(self):
        """持鎖行程被 SIGKILL（沒機會跑 release）之後，鎖要自動釋放——不靠讀 pid 判斷死活。"""
        # STEP 01: 另一個行程拿鎖並一直握著
        holder = subprocess.Popen(
            [sys.executable, "-B", "-c", LOCK_CONTENDER_SCENARIO, HELPERS_DIR, self.lock_path, "hold"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait, SCENARIO_TIMEOUT_SECONDS)
        self.addCleanup(lambda: holder.poll() is None and holder.kill())
        self.assertEqual(read_line_with_timeout(holder, SCENARIO_TIMEOUT_SECONDS), "ACQUIRED")

        # STEP 02: 它活著時本行程拿不到
        contender = runner.ProcessLock(self.lock_path)
        self.assertFalse(contender.acquire())

        # STEP 03: 殺掉它、等它真的消失，本行程就要拿得到
        os.kill(holder.pid, signal.SIGKILL)
        holder.wait(SCENARIO_TIMEOUT_SECONDS)
        self.assertTrue(wait_until_gone(holder.pid, HOLDER_EXIT_WAIT_SECONDS))
        self.assertTrue(contender.acquire())
        contender.release()

    def test_two_handles_in_one_process_are_exclusive(self):
        """同一個行程裡的兩個 ProcessLock（兩個獨立開啟的 fd）也互斥：flock 綁的是開檔，不是行程。"""
        # STEP 01: 第一個拿到、第二個拿不到
        first = runner.ProcessLock(self.lock_path)
        second = runner.ProcessLock(self.lock_path)
        self.assertTrue(first.acquire())
        self.addCleanup(first.release)
        self.assertFalse(second.acquire())
        self.assertFalse(second.acquired)

        # STEP 02: 第一個放掉後第二個拿得到
        first.release()
        self.assertTrue(second.acquire())
        second.release()


class MutateQueueConcurrencyTest(unittest.TestCase):
    """mutate_queue：多個行程同時讀-改-寫，不丟更新；過程中 queue.json 任何時刻都是完整 JSON。"""

    def setUp(self):
        """建一個只有計數器的 queue.json。"""
        # STEP 01: 狀態目錄（測試結束刪除）＋只有計數器的 queue
        # runner 狀態目錄（queue.json 所在）
        self.state_dir = tempfile.mkdtemp(prefix="r18-mq-")
        self.addCleanup(shutil.rmtree, self.state_dir, True)
        # runner 設定（只需要狀態目錄）
        self.config = {"state_dir": self.state_dir}
        runner.write_queue_new(self.config, {"counter": 0, "modules": []})

    def _start_workers(self):
        """啟動 CONCURRENT_WORKERS 個遞增行程（同時開跑，才有競爭）。

        @return Popen 清單
        """
        # STEP 01: 全部先啟動再等，不要一個跑完才啟動下一個
        workers = []
        for _ in range(CONCURRENT_WORKERS):
            process = subprocess.Popen(
                [sys.executable, "-B", "-c", QUEUE_INCREMENT_SCENARIO, HELPERS_DIR, self.state_dir,
                 str(INCREMENTS_PER_WORKER)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.addCleanup(lambda p=process: p.poll() is None and p.kill())
            workers.append(process)
        return workers

    def _finish_workers(self, workers):
        """等所有遞增行程結束（有上限），每個都要以 0 結束。

        @param workers _start_workers 的回傳值
        @return None
        """
        # STEP 01: communicate 有逾時；卡住就拋 TimeoutExpired、測試失敗
        for process in workers:
            out, err = process.communicate(timeout=SCENARIO_TIMEOUT_SECONDS)
            self.assertEqual(process.returncode, 0, err)
            self.assertEqual(out.strip(), "DONE")

    def test_concurrent_increments_lose_no_update(self):
        """4 個行程各遞增 25 次，最後的值要剛好是 100。"""
        # STEP 01: 同時跑完
        self._finish_workers(self._start_workers())

        # STEP 02: 落盤的值等於總次數
        self.assertEqual(runner.load_queue(self.config)["counter"], CONCURRENT_WORKERS * INCREMENTS_PER_WORKER)

    def test_queue_json_is_always_parseable_during_concurrent_writes(self):
        """寫入者並行寫的整段期間，另一個不持鎖的讀者每次讀到的都要是完整 JSON。"""
        # STEP 01: 讀者先開跑，寫完後用停止檔叫它收工
        stop_file = os.path.join(self.state_dir, "stop-reader")
        reader = subprocess.Popen(
            [sys.executable, "-B", "-c", QUEUE_READER_SCENARIO, HELPERS_DIR, self.state_dir, stop_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(lambda: reader.poll() is None and reader.kill())
        self._finish_workers(self._start_workers())
        with open(stop_file, "w", encoding="utf-8") as handle:
            handle.write("stop\n")
        out, err = reader.communicate(timeout=SCENARIO_TIMEOUT_SECONDS)
        self.assertEqual(reader.returncode, 0, err)

        # STEP 02: 讀者真的讀過（不是空轉），而且一次都沒讀到壞的內容
        reads, invalid = (int(value) for value in out.split())
        self.assertGreater(reads, 0)
        self.assertEqual(invalid, 0, "讀者 %d 次裡有 %d 次讀到不完整的 queue.json" % (reads, invalid))
        with open(runner.queue_file(self.config), "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["counter"], CONCURRENT_WORKERS * INCREMENTS_PER_WORKER)


class FileSha1RealPathTest(unittest.TestCase):
    """file_sha1：真檔案算出的值與 hashlib 一致；不存在回 None；存在卻讀不到要拋例外（寬容版回 None）。"""

    def setUp(self):
        """一個放測試檔的暫存目錄。"""
        # STEP 01: 暫存目錄（測試結束刪除）
        # 放測試檔的暫存目錄
        self.workdir = tempfile.mkdtemp(prefix="r18-sha1-")
        self.addCleanup(shutil.rmtree, self.workdir, True)

    def _write_sample(self):
        """寫一個含非 UTF-8 位元組、超過一個讀取區塊的檔案。

        @return (路徑, 內容 bytes)
        """
        # STEP 01: 位元組 0..255 循環填滿，確保以二進位讀取（文字模式會在非 UTF-8 位元組上失敗）
        content = bytes(index % BYTE_VALUE_RANGE for index in range(SHA1_SAMPLE_SIZE))
        path = os.path.join(self.workdir, "sample.bin")
        with open(path, "wb") as handle:
            handle.write(content)
        return path, content

    def test_matches_hashlib_on_real_file(self):
        """真檔案的 sha1 與 hashlib 直接算的一致。"""
        # STEP 01: 兩邊各算一次
        path, content = self._write_sample()
        self.assertEqual(runner.file_sha1(path), hashlib.sha1(content).hexdigest())

    def test_missing_path_returns_none(self):
        """檔案不存在是合法狀態：回 None，不拋例外。"""
        # STEP 01: 拋例外算失敗（用 fail 轉成 AssertionError，才分得出是斷言沒過還是測試壞掉）
        missing = os.path.join(self.workdir, "no-such-file")
        try:
            result = runner.file_sha1(missing)
        except RuntimeError as exc:
            self.fail("不存在的路徑不該拋例外：%s" % exc)
        self.assertIsNone(result)

    def test_unreadable_path_raises_with_path_in_message(self):
        """存在卻讀不到（這裡用目錄——open 會失敗，與執行者權限無關）要拋 RuntimeError，訊息帶路徑。"""
        # STEP 01: 拿目錄當檔案讀
        with self.assertRaises(RuntimeError) as caught:
            runner.file_sha1(self.workdir)
        self.assertIn(self.workdir, str(caught.exception))

    def test_or_none_variant_folds_read_failure_only(self):
        """file_sha1_or_none：讀取失敗與不存在都回 None；讀得到時與 file_sha1 相同。"""
        # STEP 01: 三種情況各一次；寬容版拋例外算失敗（轉成 AssertionError）
        path, content = self._write_sample()
        try:
            results = [runner.file_sha1_or_none(target)
                       for target in (path, self.workdir, os.path.join(self.workdir, "no-such-file"))]
        except RuntimeError as exc:
            self.fail("file_sha1_or_none 不該拋例外：%s" % exc)
        self.assertEqual(results, [hashlib.sha1(content).hexdigest(), None, None])


class GitOutOrRaiseTest(unittest.TestCase):
    """git_out_or_raise：成功回去空白的 stdout（含合法的空結果）；git 失敗拋 RuntimeError，訊息含子命令與 stderr 尾段。"""

    def setUp(self):
        """一個有一個 commit 的真 git repo。"""
        # STEP 01: 建 repo（測試結束刪除）、設提交者、一個空 commit
        # 受測的 git repo 目錄
        self.repo = tempfile.mkdtemp(prefix="r18-gitout-")
        self.addCleanup(shutil.rmtree, self.repo, True)
        run_git(self.repo, "init")
        run_git(self.repo, "config", "user.name", "test")
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        run_git(self.repo, "commit", "--allow-empty", "-m", "base")
        # STEP 02: runner 設定（只需要 repo 目錄）
        self.config = {"repo_dir": self.repo}

    def _call(self, *args):
        """呼叫 git_out_or_raise；拋例外就轉成測試失敗（AssertionError）。

        @param args git 子命令與參數
        @return git_out_or_raise 的回傳值
        """
        # STEP 01: 成功路徑不該拋例外
        try:
            return runner.git_out_or_raise(self.config, *args)
        except RuntimeError as exc:
            self.fail("成功的 git 指令不該拋例外：%s" % exc)

    def test_success_returns_stripped_stdout(self):
        """成功時回傳去頭尾空白的 stdout（git 輸出帶換行）。"""
        # STEP 01: 與 fixture 直接問 git 的結果相同
        self.assertEqual(self._call("rev-parse", "HEAD"), run_git(self.repo, "rev-parse", "HEAD"))

    def test_legitimate_empty_result_is_not_an_error(self):
        """指令成功但結果是空的：回空字串，不拋例外（只有 returncode != 0 才是失敗）。"""
        # STEP 01: HEAD..HEAD 一定是空範圍
        self.assertEqual(self._call("log", "--format=%H", "HEAD..HEAD"), "")

    def test_failure_raises_with_subcommand_and_stderr(self):
        """git 失敗：拋 RuntimeError，訊息帶完整子命令與 git 的 stderr。"""
        # STEP 01: 查一個不存在的分支
        with self.assertRaises(RuntimeError) as caught:
            runner.git_out_or_raise(self.config, "rev-parse", "--verify", "refs/heads/no-such-branch")
        message = str(caught.exception)
        self.assertIn("git rev-parse --verify refs/heads/no-such-branch", message)
        self.assertIn("fatal: Needed a single revision", message)

    def test_long_stderr_keeps_head_and_tail(self):
        """stderr 超過摘要上限時保留首行開頭與尾端（1.1.2 第六批 stderr_excerpt），中間以「…」標示。"""
        # STEP 01: checkout 一個不存在的長 pathspec——git 會把整串印進 stderr，錯誤原因接在最後
        pathspec = "A" * (LONG_PATHSPEC_LENGTH - 1) + "Z"
        with self.assertRaises(RuntimeError) as caught:
            runner.git_out_or_raise(self.config, "checkout", pathspec)
        message = str(caught.exception)
        stderr_part = message.split(": ", 1)[1]

        # STEP 02: 開頭與尾端都在、中間被省略、長度不超過上限
        self.assertTrue(stderr_part.startswith("error: pathspec"), stderr_part)
        self.assertIn("Z' did not match any file(s) known to git", stderr_part)
        self.assertIn("…", stderr_part)
        self.assertLessEqual(len(stderr_part), runner.STDERR_EXCERPT_CHARS)


if __name__ == "__main__":
    unittest.main()
