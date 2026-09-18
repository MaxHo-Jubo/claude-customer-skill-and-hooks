"""runner.py 1.1.1 review 修復的回歸測試。

每一組對應一個 review 確認過的缺陷。外部狀態一律用真的：行程與 process group、flock、
git（bare 遠端＋工作 repo，含用 pre-receive hook 造出來的推送失敗）、一支會留紀錄的假 gh。
mock 只用在三種地方：
(1) 測試裡造不出來的事件——斷電（只驗 fsync／replace 的呼叫順序）、訊號剛好落在某一行；
(2) 注入失敗——R15 原檔讀取失敗、合併失敗、合併當下 entry 被人從 queue 移除；
(3) 隔離與受測行為無關的副作用——通知、進度報表、診斷包、crash 流程。

執行方式（在 skill 根目錄）：
    python3 -B -m unittest discover -s helpers/tests -v

`-B` 與下方的 `sys.dont_write_bytecode` 是為了不在 skill 目錄留下 __pycache__。
"""

import argparse
import contextlib
import io
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
# helpers 目錄（runner.py 所在）；測試檔在 helpers/tests/ 底下
HELPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HELPERS_DIR)

import runner  # noqa: E402  pylint: disable=wrong-import-position

# 子行程情境腳本的整體上限（秒）：超過代表 runner 卡住，測試判定失敗而不是跟著卡
SCENARIO_TIMEOUT_SECONDS = 20
# 送出訊號後等待孫行程真的消失的上限（秒）：訊號遞送與收屍是非同步的
GRANDCHILD_EXIT_WAIT_SECONDS = 3
# 輪詢孫行程是否還活著的間隔（秒）
POLL_INTERVAL_SECONDS = 0.1
# 情境裡孫行程的睡眠秒數：要遠大於 SCENARIO_TIMEOUT_SECONDS，才分得出「被殺」與「自己醒來」
GRANDCHILD_SLEEP_SECONDS = 600
# 情境裡外層 communicate 的逾時（秒）：只要夠讓 bash 主行程先退出即可
SCENARIO_COMMUNICATE_TIMEOUT_SECONDS = 1
# 測試呼叫 _terminate_process_group 時給的 TERM 寬限期（秒）：孫行程（sleep）收到 TERM 就會結束，不需要等久
TEST_TERM_GRACE_SECONDS = 1
# 等一個「立刻結束的行程」真的結束、成為待收屍狀態的時間（秒）
ZOMBIE_SETTLE_SECONDS = 0.5
# notify.sh 的單則訊息長度上限（helpers/notify.sh 的 max_text_chars；外部契約，測試以它為準、不讀實作的長度常數）
NOTIFY_MAX_TEXT_CHARS = 300
# 一個不可能等於任何真實 commit 的 sha（40 個 0），用來驗「HEAD 與預期不符就不推送」
IMPOSSIBLE_SHA = "0" * 40
# 假 gh 印出的 PR 連結（.invalid 是保留網域，不會對應到任何真實位址）
FAKE_PR_URL = "https://example.invalid/pull/7"
# 上一輪已經開好的 PR 連結（用來驗重跑時沿用、不被覆寫）
EXISTING_PR_URL = "https://example.invalid/pull/3"
# 測試用的整合分支與 entry 分支名稱；基準分支只在要造「前置作業把 base 合進整合分支」的拓撲時才另建
INTEGRATION_BRANCH = "integration"
BASE_BRANCH = "master"
ENTRY_BRANCH = "e1-branch"
# 測試用的斷點分支（前置作業會把 opened 的斷點分支回流進本機整合分支）；斷點 id 見下方 CHECKPOINT_ID
CHECKPOINT_BRANCH = "cp-1"
# 測試用的 entry id（build_fixture 建的那一個 entry）
ENTRY_ID = "e1"
# entry 涵蓋的 R15 原始檔（相對 repo 根目錄）
R15_RELATIVE_PATH = "legacy/a.js"

# 在獨立行程裡重現「CLI 主行程先退出、孫行程握著 stderr pipe」；
# argv[1] = helpers 目錄，argv[2] = 孫行程 pid 要寫到哪個檔
LEADER_EXITS_FIRST_SCENARIO = """
import subprocess, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
process = subprocess.Popen(
    ["bash", "-c", 'sleep %d & echo $! > "$0"; exit 0', sys.argv[2]],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    text=True, start_new_session=True,
)
try:
    process.communicate(timeout=%d)
    print("NO_TIMEOUT")
except subprocess.TimeoutExpired:
    runner._terminate_process_group(process, %d)
    print("RETURNED")
""" % (GRANDCHILD_SLEEP_SECONDS, SCENARIO_COMMUNICATE_TIMEOUT_SECONDS, TEST_TERM_GRACE_SECONDS)

# 情境裡把 runner 的收屍上限調成這個值（秒），測試才不必每次等滿正式的上限
SCENARIO_REAP_LIMIT_SECONDS = 1
# gh 以退出碼 0 結束、但 stdout 不是 PR 連結的三種輸出：空的、純文字、不是 PR 的網址（登入／更新提示那一類）
NON_PR_OUTPUTS = ("", "Creating pull request...", "https://example.invalid/login/device")

# 在獨立行程裡重現「孫行程自行 setsid 脫離 process group、還握著 stderr pipe」——killpg 送不到它；
# argv[1] = helpers 目錄，argv[2] = 脫離者 pid 要寫到哪個檔
ESCAPED_PROCESS_SCENARIO = """
import subprocess, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
runner.REAP_LIMIT_SECONDS = %d
escaper = "import os,sys,time; os.setsid(); open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(%d)"
process = subprocess.Popen(
    ["bash", "-c", 'python3 -c "$0" "$1" & exit 0', escaper, sys.argv[2]],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    text=True, start_new_session=True,
)
try:
    process.communicate(timeout=%d)
    print("NO_TIMEOUT")
except subprocess.TimeoutExpired:
    try:
        runner._terminate_process_group(process, %d)
        print("RETURNED_NORMALLY")
    except runner.LeftoverProcessError:
        print("LEFTOVER_REPORTED")
""" % (
    SCENARIO_REAP_LIMIT_SECONDS,
    GRANDCHILD_SLEEP_SECONDS,
    SCENARIO_COMMUNICATE_TIMEOUT_SECONDS + 1,
    TEST_TERM_GRACE_SECONDS,
)

# 在獨立行程裡重現「同一個 group 內有行程忽略 SIGTERM、而且不握 runner 的 pipe」：主行程（bash）收到 TERM 就死、
# pipe 隨之關閉，但 group 還沒空；argv[1] = helpers 目錄，argv[2] = 忽略者 pid 要寫到哪個檔
TERM_IGNORER_SCENARIO = """
import subprocess, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
ignorer = ("import os,signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
           "open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(%d)")
process = subprocess.Popen(
    ["bash", "-c", 'python3 -c "$1" "$0" >/dev/null 2>&1 & wait', sys.argv[2], ignorer],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    text=True, start_new_session=True,
)
try:
    process.communicate(timeout=%d)
    print("NO_TIMEOUT")
except subprocess.TimeoutExpired:
    runner._terminate_process_group(process, %d)
    print("RETURNED")
""" % (GRANDCHILD_SLEEP_SECONDS, SCENARIO_COMMUNICATE_TIMEOUT_SECONDS + 1, TEST_TERM_GRACE_SECONDS)

# 收尾期間再收到一次停止訊號：group 裡有忽略 SIGTERM 的行程（pid 寫進 argv[2]），
# 開始收尾 0.5 秒後對自己送 SIGTERM。第二個訊號不可以打斷收尾——收尾完成之後才拋出
SECOND_SIGNAL_DURING_CLEANUP_SCENARIO = """
import os, signal, subprocess, sys, threading, time
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
ignorer = ("import os,signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
           "open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(%d)")
process = subprocess.Popen(
    ["bash", "-c", 'python3 -c "$1" "$0" >/dev/null 2>&1 & wait', sys.argv[2], ignorer],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    text=True, start_new_session=True,
)
time.sleep(%s)
runner.install_shutdown_handlers()
threading.Timer(%s, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
try:
    runner._terminate_process_group(process, %d)
    print("RETURNED")
except runner.ShutdownSignal:
    print("SHUTDOWN")
""" % (GRANDCHILD_SLEEP_SECONDS, ZOMBIE_SETTLE_SECONDS, ZOMBIE_SETTLE_SECONDS, TEST_TERM_GRACE_SECONDS)

# 停止訊號落在「子行程已經建立、但 subprocess.Popen(...) 還沒返回給 call_claude」：假的 Popen 子類真的
# 啟動子行程（pid 寫進 argv[2]），在自己的 __init__ 裡、super().__init__ 返回之後對自己送 SIGTERM。
# 這造的是 Popen 內部 fork/exec 之後那段視窗；「Popen 返回後、變數綁定前」那段跟它同屬一個延後
# 區間，這裡沒有另外造（要精準落在那幾個 bytecode 之間造不出來）。call_claude 必須先把子行程收掉
# 再讓 ShutdownSignal 往外傳
SIGNAL_AFTER_POPEN_SCENARIO = """
import os, signal, subprocess, sys, time
from unittest import mock
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
real_popen = subprocess.Popen
class SignalAfterPopen(real_popen):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        open(sys.argv[2], "w").write(str(self.pid))
        os.kill(os.getpid(), signal.SIGTERM)
state_dir = sys.argv[3]
os.makedirs(os.path.join(state_dir, "sessions"), exist_ok=True)
config = {"state_dir": state_dir, "repo_dir": state_dir, "claude_config_dir": None, "module_timeout_min": 1}
runner.install_shutdown_handlers()
subprocess.Popen = SignalAfterPopen
try:
    with mock.patch.object(runner, "build_claude_command", return_value=["sleep", "%d"]):
        runner.call_claude(config, {"id": "e1"}, 1, False)
    print("RETURNED")
except runner.ShutdownSignal:
    print("SHUTDOWN")
""" % GRANDCHILD_SLEEP_SECONDS

# 測試用的斷點 id
CHECKPOINT_ID = "cp1"

# 在獨立行程裡裝上真的 SIGTERM／SIGHUP handler 再對自己送訊號（不在測試行程裡裝，以免改掉它的訊號處理）；
# argv[1] = helpers 目錄，argv[2] = 訊號名稱
REAL_SIGNAL_SCENARIO = """
import os, signal, sys, time
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import runner
runner.install_shutdown_handlers()
try:
    os.kill(os.getpid(), getattr(signal, sys.argv[2]))
    time.sleep(5)
    print("NOT_CONVERTED")
except runner.ShutdownSignal:
    print("CONVERTED")
"""


def is_alive(pid):
    """判斷某個 pid 是否還存在。

    @param pid 要檢查的行程 id
    @return 行程還在回 True；已不存在回 False
    """
    # STEP 01: signal 0 只做存在性檢查，不會真的送訊號
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_until_gone(pid, limit_seconds):
    """等某個 pid 消失，最多等 limit_seconds。

    @param pid 要等待的行程 id
    @param limit_seconds 等待上限（秒）
    @return 期限內消失回 True；逾時仍在回 False
    """
    # STEP 01: 輪詢到期限為止
    deadline = time.time() + limit_seconds
    while time.time() < deadline:
        if not is_alive(pid):
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return not is_alive(pid)


def kill_pid_in_file(pid_file):
    """把情境腳本寫進檔案的 pid 送 SIGKILL（還活著才送）；檔案不存在代表情境沒跑到那一步。

    @param pid_file 情境腳本寫入行程 pid 的檔案
    @return None
    """
    # STEP 01: pid 檔不存在代表情境根本沒跑到那一步，沒有東西要清
    if not os.path.exists(pid_file):
        return
    with open(pid_file, "r", encoding="utf-8") as handle:
        text = handle.read().strip()
    # STEP 02: 還活著才送 KILL
    if text and is_alive(int(text)):
        os.kill(int(text), signal.SIGKILL)


def read_pid_file(pid_file):
    """讀情境腳本寫下的 pid。

    @param pid_file 情境腳本寫入行程 pid 的檔案
    @return int
    """
    # STEP 01: 直接讀
    with open(pid_file, "r", encoding="utf-8") as handle:
        return int(handle.read().strip())


def run_git(cwd, *args):
    """在指定目錄執行 git，失敗直接拋例外（測試前置不容許靜默失敗）。

    @param cwd 執行目錄
    @param args git 子命令與參數
    @return stdout 去頭尾空白後的字串
    """
    # STEP 01: check=True 讓前置步驟失敗時測試直接報錯，而不是帶著壞的 fixture 往下跑
    result = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def write_fake_gh(directory, remote, output=FAKE_PR_URL):
    """建立一支假的 gh：記下每次呼叫，以及「被呼叫當下」遠端整合分支的 tip，並印出指定的輸出。

    記 tip 是為了釘住「先開 PR、再合併」的順序：開 PR 的那一刻整合分支必須還停在基線，
    順序一旦反過來，記到的就會是 entry 的 commit。

    @param directory 放腳本與紀錄檔的目錄
    @param remote bare 遠端 repo 的路徑
    @param output 腳本印到 stdout 的內容（一律以退出碼 0 結束）；預設是一個合法的 PR 連結
    @return (腳本路徑, 呼叫紀錄檔路徑, 呼叫當下整合分支 tip 的紀錄檔路徑)
    """
    # STEP 01: 腳本內容——一次呼叫追加一行紀錄；只記前兩個參數（子命令），
    # --body 是多行文字，整串記下來會讓「一行 = 一次呼叫」不成立
    script_path = os.path.join(directory, "fake-gh")
    calls_path = os.path.join(directory, "fake-gh.calls")
    tips_path = os.path.join(directory, "fake-gh.tips")
    script_lines = [
        "#!/bin/bash",
        'echo "$1 $2" >> "%s"' % calls_path,
        'git --git-dir="%s" rev-parse "refs/heads/%s" >> "%s"' % (remote, INTEGRATION_BRANCH, tips_path),
        'echo "%s"' % output,
    ]
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(script_lines) + "\n")
    # STEP 02: 加上可執行權限
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IXUSR)
    return script_path, calls_path, tips_path


def reject_entry_branch_push(remote, branch=ENTRY_BRANCH):
    """在 bare 遠端裝一支 pre-receive hook：拒絕指定分支的推送，其餘分支照常接受。

    用來造出「某一支分支推不上去、其餘推得上去」的真實情境，不必 mock git；預設拒絕 entry 分支。

    @param remote bare 遠端 repo 的路徑
    @param branch 要拒絕的分支名稱
    @return None
    """
    # STEP 01: hook 從 stdin 逐行收到「舊值 新值 ref 名稱」，命中就以非零結束
    hook_path = os.path.join(remote, "hooks", "pre-receive")
    hook_lines = [
        "#!/bin/bash",
        "while read -r _old _new ref; do",
        '  if [ "$ref" = "refs/heads/%s" ]; then echo "rejected by test hook" >&2; exit 1; fi' % branch,
        "done",
        "exit 0",
    ]
    os.makedirs(os.path.dirname(hook_path), exist_ok=True)
    with open(hook_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(hook_lines) + "\n")
    # STEP 02: 加上可執行權限，git 才會執行它
    os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IXUSR)


def build_fixture(root, entry_overrides=None):
    """建立一組真實的 git 環境與狀態目錄：bare 遠端、工作 repo、一個有 commit 的 entry 分支。

    @param root 暫存根目錄
    @param entry_overrides 要覆寫進 entry 的欄位（例如先前已開過的 pr_url）；None 表示不覆寫
    @return dict：config、entry、remote（bare repo 路徑）、base_sha、entry_sha、gh_calls、gh_tips
    """
    # STEP 01: bare 遠端 + 工作 repo，整合分支先有一個基線 commit 並推上遠端
    remote = os.path.join(root, "origin.git")
    work = os.path.join(root, "work")
    state_dir = os.path.join(root, "state")
    os.makedirs(os.path.join(work, os.path.dirname(R15_RELATIVE_PATH)))
    run_git(root, "init", "--bare", remote)
    run_git(work, "init")
    run_git(work, "config", "user.name", "test")
    run_git(work, "config", "user.email", "test@example.invalid")
    run_git(work, "checkout", "-b", INTEGRATION_BRANCH)
    with open(os.path.join(work, R15_RELATIVE_PATH), "w", encoding="utf-8") as handle:
        handle.write("// r15 original\n")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "base")
    run_git(work, "remote", "add", "origin", remote)
    run_git(work, "push", "-u", "origin", INTEGRATION_BRANCH)
    base_sha = run_git(work, "rev-parse", "HEAD")

    # STEP 02: entry 分支多一個 commit；停在 entry 分支上（與 runner 呼叫 L1 時的狀態一致）
    run_git(work, "checkout", "-b", ENTRY_BRANCH)
    with open(os.path.join(work, "migrated.js"), "w", encoding="utf-8") as handle:
        handle.write("// r18 migrated\n")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "migrate e1")
    entry_sha = run_git(work, "rev-parse", "HEAD")

    # STEP 03: 狀態目錄與 queue.json（entry 為 running，tip 記錄為基線）
    gh_bin, gh_calls, gh_tips = write_fake_gh(root, remote)
    config = {
        "state_dir": state_dir,
        "repo_dir": work,
        "integration_branch": INTEGRATION_BRANCH,
        "gh_bin": gh_bin,
        "current_entry": ENTRY_ID,
        "current_attempt": 1,
        "resumed_pause_reason": None,
        "notify_channel": "none",
    }
    runner.ensure_state_dir(config)
    base_entry = dict(
        runner.RUNTIME_FIELD_DEFAULTS,
        id=ENTRY_ID,
        branch=ENTRY_BRANCH,
        type="page",
        wave=0,
        r18_dir="pages/e1",
        r15_paths=[R15_RELATIVE_PATH],
        status="running",
    )
    # 覆寫欄位疊在預設之上（可以覆寫 status 這類預設已經給值的欄位）
    entry = {**base_entry, **(entry_overrides or {})}
    runner.write_queue_new(
        config,
        {
            "integration_branch": INTEGRATION_BRANCH,
            "integration_tip_sha": base_sha,
            "runner_state": {"state": "running"},
            "modules": [entry],
        },
    )
    return {
        "config": config,
        "entry": entry,
        "remote": remote,
        "base_sha": base_sha,
        "entry_sha": entry_sha,
        "gh_calls": gh_calls,
        "gh_tips": gh_tips,
    }


def remote_tip(fixture, branch):
    """讀 bare 遠端某個分支目前的 commit；分支不存在回 None。

    @param fixture build_fixture 的回傳值
    @param branch 分支名稱
    @return 完整 sha 或 None
    """
    # STEP 01: 直接問 bare repo，不經過工作 repo 的 remote-tracking 快取
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "refs/heads/%s" % branch],
        cwd=fixture["remote"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def queue_entry(fixture):
    """從 queue.json 重新讀出測試用的 entry。

    @param fixture build_fixture 的回傳值
    @return (整份 queue, entry dict)
    """
    # STEP 01: 每次都重讀檔案，驗的是落盤後的狀態而不是記憶體裡的物件
    queue = runner.load_queue(fixture["config"])
    return queue, runner.find_entry(queue, ENTRY_ID)


def _register_opened_checkpoint(queue):
    """mutate_queue 用：把測試用的斷點以 opened 狀態登記進 queue（前置作業會回流它的分支）。

    @param queue 整份 queue
    @return None
    """
    # STEP 01: 只放前置作業會看的兩個欄位
    queue["checkpoints"] = [{"id": CHECKPOINT_ID, "status": "opened", "branch": CHECKPOINT_BRANCH}]


def start_patches(test_case, *names):
    """把 runner 模組上的幾個副作用函式換成 mock，測試結束時自動還原。

    @param test_case 目前的 TestCase（用它的 addCleanup 還原）
    @param names 要換掉的 runner 模組層級函式名稱
    @return dict：名稱 → mock 物件（要看呼叫內容時用）
    """
    # STEP 01: 逐個啟動並登記還原
    mocks = {}
    for name in names:
        patcher = mock.patch.object(runner, name)
        mocks[name] = patcher.start()
        test_case.addCleanup(patcher.stop)
    return mocks


def read_plist_integer(template_text, key):
    """從 launchd plist 範本文字讀一個整數鍵的值；鍵不存在回 None。

    @param template_text plist 全文
    @param key 要找的 <key> 名稱
    @return int 或 None
    """
    # STEP 01: 只認「<key>名稱</key> 緊接 <integer>數字</integer>」這個形狀，避免誤抓註解裡的字
    match = re.search(r"<key>%s</key>\s*<integer>(\d+)</integer>" % re.escape(key), template_text)
    return int(match.group(1)) if match else None


class TerminateProcessGroupTest(unittest.TestCase):
    """C1：process group 的收尾不能因為主行程先退出就卡住或漏殺孫行程。"""

    def test_leader_exits_first_grandchild_holds_pipe(self):
        """主行程已退出（zombie）、孫行程握著 stderr pipe：要在期限內返回，且孫行程被收掉。"""
        # STEP 01: 在獨立行程跑情境——修復前這裡會永久卡住，所以整段要有外層上限
        workdir = tempfile.mkdtemp(prefix="r18-c1-")
        pid_file = os.path.join(workdir, "grandchild.pid")
        self.addCleanup(self._kill_grandchild, pid_file)
        try:
            result = subprocess.run(
                [sys.executable, "-B", "-c", LEADER_EXITS_FIRST_SCENARIO, HELPERS_DIR, pid_file],
                capture_output=True,
                text=True,
                timeout=SCENARIO_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("_terminate_process_group 在 %d 秒內沒有返回（卡在沒有上限的 communicate）" % SCENARIO_TIMEOUT_SECONDS)

        # STEP 02: 情境確實走到了逾時分支並返回
        self.assertIn("RETURNED", result.stdout, result.stderr)

        # STEP 03: 孫行程必須真的被訊號收掉，不是只有 runner 自己脫身
        with open(pid_file, "r", encoding="utf-8") as handle:
            grandchild_pid = int(handle.read().strip())
        self.assertTrue(
            wait_until_gone(grandchild_pid, GRANDCHILD_EXIT_WAIT_SECONDS),
            "孫行程 %d 仍然存活：process group 沒有收到訊號" % grandchild_pid,
        )

    def test_zombie_only_group_does_not_raise(self):
        """group 裡只剩尚未收屍的主行程：macOS 的 killpg 會回 EPERM，收尾不可因此拋例外。"""
        # STEP 01: 主行程立刻結束且不收屍，group 內沒有其他成員
        process = subprocess.Popen(
            ["true"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        time.sleep(ZOMBIE_SETTLE_SECONDS)

        # STEP 02: 收尾要正常返回 (stdout, stderr)，並且把主行程收屍
        _stdout, stderr = runner._terminate_process_group(process, TEST_TERM_GRACE_SECONDS)
        self.assertEqual(stderr, "")
        self.assertEqual(process.returncode, 0)

    def test_escaped_process_holding_pipe_is_reported(self):
        """孫行程自行脫離 group 還握著 pipe：訊號送不到它，收尾不可當成一般逾時返回，要明確回報有殘留行程。"""
        # STEP 01: 在獨立行程跑情境（收屍上限調短）；脫離者的 pid 由它自己寫進檔案，收場時清掉
        workdir = tempfile.mkdtemp(prefix="r18-escaped-")
        pid_file = os.path.join(workdir, "escaped.pid")
        self.addCleanup(self._kill_grandchild, pid_file)
        result = subprocess.run(
            [sys.executable, "-B", "-c", ESCAPED_PROCESS_SCENARIO, HELPERS_DIR, pid_file],
            capture_output=True,
            text=True,
            timeout=SCENARIO_TIMEOUT_SECONDS,
            check=False,
        )

        # STEP 02: 前置條件——脫離者真的還活著（否則這個測試什麼都沒驗到）
        with open(pid_file, "r", encoding="utf-8") as handle:
            self.assertTrue(is_alive(int(handle.read().strip())), "前置條件：脫離 group 的行程應該還活著")

        # STEP 03: 必須以專屬例外回報，不是回傳一個看起來正常的 (stdout, stderr)
        self.assertEqual(result.stdout.strip(), "LEFTOVER_REPORTED", result.stderr)

    def test_term_ignorer_in_group_is_killed(self):
        """同一個 group 內有行程忽略 SIGTERM 且不握 pipe：pipe 關閉不等於 group 已空，必須升級成 SIGKILL 把它收掉。"""
        # STEP 01: 在獨立行程跑情境；忽略者的 pid 由它自己寫進檔案，收場時清掉
        workdir = tempfile.mkdtemp(prefix="r18-ignorer-")
        pid_file = os.path.join(workdir, "ignorer.pid")
        self.addCleanup(self._kill_grandchild, pid_file)
        result = subprocess.run(
            [sys.executable, "-B", "-c", TERM_IGNORER_SCENARIO, HELPERS_DIR, pid_file],
            capture_output=True,
            text=True,
            timeout=SCENARIO_TIMEOUT_SECONDS,
            check=False,
        )

        # STEP 02: 收尾正常返回（KILL 收得掉它，不需要走例外）
        self.assertEqual(result.stdout.strip(), "RETURNED", result.stderr)

        # STEP 03: 忽略者必須已經不在了
        with open(pid_file, "r", encoding="utf-8") as handle:
            ignorer_pid = int(handle.read().strip())
        self.assertTrue(
            wait_until_gone(ignorer_pid, GRANDCHILD_EXIT_WAIT_SECONDS),
            "忽略 SIGTERM 的行程 %d 仍然存活：收尾在 pipe 關閉時就返回了，沒有確認 group 已空" % ignorer_pid,
        )

    def test_group_still_populated_after_kill_raises(self):
        """SIGKILL 之後 group 仍有成員（同使用者的行程造不出這種狀態，用注入）：不可正常返回。"""
        # STEP 01: 一個收到 TERM 就結束的真行程；「group 是否已空」的檢查一律回報還沒空
        process = subprocess.Popen(
            ["sleep", str(GRANDCHILD_SLEEP_SECONDS)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        self.addCleanup(process.communicate)

        # STEP 02: 必須以 LeftoverProcessError 回報
        with mock.patch.object(runner, "_wait_group_empty", return_value=False):
            with self.assertRaises(runner.LeftoverProcessError):
                runner._terminate_process_group(process, TEST_TERM_GRACE_SECONDS)

    def test_unsignalable_group_raises(self):
        """killpg 一直回 EPERM（收屍後重試仍然如此）：group 裡有送不了訊號的活行程，不可當成「已無對象」。"""
        # STEP 01: 一個立刻結束的主行程；killpg 一律回 EPERM，重試之間的等待不真的睡
        process = subprocess.Popen(
            ["true"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        self.addCleanup(process.communicate)

        # STEP 02: 要以收尾專屬的例外往外拋（不是泛用的 PermissionError，也不是吞掉後照常返回）
        with mock.patch.object(runner.os, "killpg", side_effect=PermissionError("測試")) as killpg, \
                mock.patch.object(runner.time, "sleep"):
            with self.assertRaises(runner.UnsignalableGroupError):
                runner._terminate_process_group(process, TEST_TERM_GRACE_SECONDS)

        # STEP 03: 真的重試過——第一次加上 EPERM_RETRY_COUNT 次重試
        self.assertEqual(killpg.call_count, 1 + runner.EPERM_RETRY_COUNT)

    @staticmethod
    def _kill_grandchild(pid_file):
        """測試收場：不論斷言成敗，都不留下睡 10 分鐘的孤兒行程。

        @param pid_file 情境腳本寫入孫行程 pid 的檔案
        """
        # STEP 01: 交給模組層 helper（ShutdownDeferralTest 也用）
        kill_pid_in_file(pid_file)


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
        recorder = mock.Mock()
        real_fsync = os.fsync
        real_replace = os.replace

        def spy_fsync(fd):
            """依 fd 指向的是不是目錄分類後轉發。"""
            kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
            recorder("fsync:%s" % kind)
            return real_fsync(fd)

        def spy_replace(source, target):
            """記錄後轉發。"""
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
            """把 marker 加一。"""
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
        self.outcome = {"structured": {}, "session_id": "session-1", "cost": 0.5}
        # STEP 02: notify 會呼叫外部腳本、write_progress 會產報表，都不是受測對象
        for name in ("notify", "write_progress"):
            patcher = mock.patch.object(runner, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_success_writes_tip_and_done_together(self):
        """成功路徑：遠端整合分支前進到 entry commit，queue 的 tip 與 done 在同一次寫入裡出現。"""
        fixture = self.fixture
        # STEP 01: 包住 mutate_queue，每次寫入後記下「tip 是否已前進、entry 是否已 done」
        recorder = mock.Mock()
        real_mutate = runner.mutate_queue

        def spy_mutate(config, mutator):
            """轉發後記錄落盤狀態。"""
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
            """把測試用的 entry 從 queue 拿掉。"""
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
        real_merge = runner.merge_to_integration

        def merge_then_drop(config, entry, expected_tip):
            """轉發給真正的合併，成功後移除 entry。"""
            outcome = real_merge(config, entry, expected_tip)

            def drop_entry(queue):
                """把測試用的 entry 從 queue 拿掉。"""
                queue["modules"] = [item for item in queue["modules"] if item["id"] != ENTRY_ID]

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
        """退不回去的鎖定通知：照 notify.sh 的規則組字並以 300 字截斷之後，仍要看得到「合併前的 sha」、退不回去的原因、與兩個 unblock 指示。

        合併前的 sha 是人工退回時唯一能知道「該退到哪」的紀錄（診斷包不收 git 狀態）；第十六批之前它與原因
        都排在兩個 40 字元 sha 的不符敘述之後，300 字只剩「先依下面的說明…」——說明本身被切掉（第十六輪實測 684 字）。
        """
        fixture = self.fixture
        # STEP 01: 真的走「collect 之後 entry 分支又多了 commit、HEAD 已被切走」的退不回去情境，enter_paused 真的跑、只擋通知
        work = fixture["config"]["repo_dir"]
        real_collect = runner.collect_closing_data

        def collect_then_late_commit(config, entry):
            """收尾資料取完之後 entry 分支才多一個 commit（殘留寫入者還在改 repo）。"""
            closing = real_collect(config, entry)
            with open(os.path.join(work, "late.js"), "w", encoding="utf-8") as handle:
                handle.write("// late\n")
            run_git(work, "add", "-A")
            run_git(work, "commit", "-m", "late commit")
            return closing

        fake_git = MergeToIntegrationTest._git_with_failure(("symbolic-ref", "--short", "HEAD"), (0, "someone-else\n", ""))
        with mock.patch.object(runner, "collect_closing_data", collect_then_late_commit), \
                mock.patch.object(runner, "git", fake_git), mock.patch.object(runner, "notify") as notify:
            self.assertEqual(runner.publish_verified_entry(fixture["config"], fixture["entry"], self.outcome, 1), runner.EXIT_PAUSED)
        _config, _event, title, body = notify.call_args.args

        # STEP 02: 照 notify.sh 組字並截斷
        text = ("🔴 %s\n%s" % (title, body))[:NOTIFY_MAX_TEXT_CHARS]
        self.assertIn(fixture["base_sha"][:12], text, text)
        self.assertIn("someone-else", text, text)
        self.assertIn("unblock --integration-tip", text, text)

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
                # STEP 02: 看 force_hold；退不回去的那種，兩個 unblock 的指示要排在診斷文字之前（通知會截尾）
                self.assertEqual(paused.call_args.kwargs.get("force_hold", False), expect_hold)
                if merge_result == "integration_unrecovered":
                    detail = paused.call_args.args[2]
                    self.assertLess(detail.index("unblock --integration-tip"), detail.index("模擬"), detail)

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


class OpenCheckpointTest(unittest.TestCase):
    """斷點 PR 拿不到連結時**仍然**寫成 opened 並蓋章——這是第六批刻意還原的行為。

    第五批把它改成「沒連結就 failed、回 False」，與頁面 PR 對齊；但兩個呼叫端都靠 opened／蓋章
    運作：hard 斷點只在 True 時暫停（人工閘門消失），auto 斷點不在 queue 裡、標 failed 是空轉、
    entry 沒蓋章就會每完成一個模組再推一支 cp 分支、再開一個真的 PR（第六輪 review 用本檔的
    fixture 實跑重現）。正解是查該分支既有的 PR 沿用，那是 1.1.2 重啟對帳的一部分。
    """

    def setUp(self):
        """每個測試一組 git 環境：entry 已完成（斷點要蓋章的對象），queue 裡有一個待開的斷點。"""
        # STEP 01: fixture；斷點 PR 的 base 用整合分支即可（假 gh 不看）
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-cp-"), {"status": "done"})
        self.fixture["config"]["base_branch"] = INTEGRATION_BRANCH

        def add_checkpoint(queue):
            """加入一個 pending 的斷點。"""
            queue["checkpoints"] = [dict(runner.CHECKPOINT_FIELD_DEFAULTS, id=CHECKPOINT_ID, mode="soft", title="cp")]

        runner.mutate_queue(self.fixture["config"], add_checkpoint)
        # STEP 02: 通知與進度報表不是受測對象，但要看通知內文
        self.notify = start_patches(self, "notify", "write_progress")["notify"]

    def _checkpoint_and_entry(self):
        """重讀 queue，回傳 (斷點, entry)。"""
        # STEP 01: 驗落盤後的狀態
        queue, entry = queue_entry(self.fixture)
        return runner.find_checkpoint(queue, CHECKPOINT_ID), entry

    def test_without_pr_link_still_opens_and_stamps(self):
        """沒有 PR 連結：照樣 opened、蓋章、回 True；通知要說清楚沒有連結、請人到 GitHub 確認該分支。"""
        fixture = self.fixture
        # STEP 01: 假 gh 成功退出但印的是登入提示網址
        write_fake_gh(os.path.dirname(fixture["remote"]), fixture["remote"], NON_PR_OUTPUTS[2])

        # STEP 02: 執行
        self.assertTrue(runner.open_checkpoint(fixture["config"], CHECKPOINT_ID))

        # STEP 03: 狀態與蓋章都在，連結是空的
        checkpoint, entry = self._checkpoint_and_entry()
        self.assertEqual(checkpoint["status"], "opened")
        self.assertFalse(checkpoint.get("pr_url"))
        self.assertEqual(entry["checkpoint_id"], CHECKPOINT_ID)

        # STEP 04: 通知不可假裝有連結，而且要帶 cp 分支名讓人去查
        body = self.notify.call_args.args[3]
        self.assertIn("未回傳連結", body)
        self.assertIn("r18-migration/cp-%s" % CHECKPOINT_ID, body)

    def test_with_pr_link_opens(self):
        """對照組：有合法連結時照常開啟並蓋章——確認上一個測試的失敗不是因為 fixture 本來就開不起來。"""
        fixture = self.fixture
        # STEP 01: 預設的假 gh 會印合法連結
        self.assertTrue(runner.open_checkpoint(fixture["config"], CHECKPOINT_ID))

        # STEP 02: 斷點已開、entry 已蓋章
        checkpoint, entry = self._checkpoint_and_entry()
        self.assertEqual(checkpoint["status"], "opened")
        self.assertEqual(checkpoint["pr_url"], FAKE_PR_URL)
        self.assertEqual(entry["checkpoint_id"], CHECKPOINT_ID)


class HandleCheckpointsTest(unittest.TestCase):
    """釘住 open_checkpoint 的兩個呼叫端在「斷點 PR 拿不到連結」時的行為（第六輪 review 的 K1）。

    hard 斷點：人工閘門不可以因為拿不到連結而消失。
    auto 斷點：一次沒拿到連結只能推一支 cp 分支、開一次 PR，不能每完成一個模組就再來一輪。
    """

    def setUp(self):
        """entry 已完成的 git 環境；假 gh 成功退出但不印 PR 連結。"""
        # STEP 01: fixture；自動斷點門檻設成 1 個模組就觸發，行數門檻設到不會觸發
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-hc-"), {"status": "done"})
        self.config = self.fixture["config"]
        self.config.update({"base_branch": INTEGRATION_BRANCH, "checkpoint_max_modules": 1, "checkpoint_max_lines": 10 ** 6})
        _bin, self.gh_calls, _tips = write_fake_gh(
            os.path.dirname(self.fixture["remote"]), self.fixture["remote"], NON_PR_OUTPUTS[2]
        )
        # STEP 02: 通知與進度報表不是受測對象
        start_patches(self, "notify", "write_progress")

    def _gh_call_count(self):
        """假 gh 被呼叫的次數（紀錄檔一行一次；還沒被呼叫過時檔案不存在）。"""
        # STEP 01: 讀紀錄檔
        if not os.path.exists(self.gh_calls):
            return 0
        with open(self.gh_calls, encoding="utf-8") as handle:
            return len(handle.read().splitlines())

    def test_hard_checkpoint_without_link_still_pauses(self):
        """hard 斷點沒拿到連結：仍然回 (True, id)，runner 才會停下來等人放行。"""
        # STEP 01: 宣告一個 wave 0 之後的 hard 斷點
        def add_checkpoint(queue):
            """加入 pending 的 hard 斷點。"""
            queue["checkpoints"] = [
                dict(runner.CHECKPOINT_FIELD_DEFAULTS, id=CHECKPOINT_ID, mode="hard", after={"wave": 0}, title="cp")
            ]

        runner.mutate_queue(self.config, add_checkpoint)

        # STEP 02: 閘門要在
        self.assertEqual(runner.handle_checkpoints(self.config), (True, CHECKPOINT_ID))

    def test_auto_checkpoint_without_link_does_not_repeat(self):
        """auto 斷點沒拿到連結：對同一份 queue 再呼叫一次不可以再開一次 PR，而且累積的模組數已經歸零。"""
        # STEP 01: 沒有宣告的斷點，靠模組數門檻觸發；第一次會開 auto 斷點。第二次是對「第一次已經蓋過章」的
        # 同一份狀態再呼叫（沒有新模組完成）：修正前 entry 沒被蓋章，門檻仍成立，會再開一次
        self.assertEqual(runner.handle_checkpoints(self.config), (False, None))
        self.assertEqual(runner.handle_checkpoints(self.config), (False, None))

        # STEP 02: 只開過一次 PR，entry 已被第一個 auto 斷點蓋章、門檻不再成立
        self.assertEqual(self._gh_call_count(), 1)
        needed, _detail = runner.auto_checkpoint_needed(self.config, runner.load_queue(self.config))
        self.assertFalse(needed)


class EnterPausedPersistFailureTest(unittest.TestCase):
    """hold 寫不進狀態檔時，通知不可以說「已鎖定」——launchd 幾分鐘後照樣重啟，人要立刻手動停掉服務。"""

    def setUp(self):
        """狀態目錄與一份執行中的 queue；狀態寫入注入失敗。"""
        # STEP 01: 狀態目錄與 queue
        self.config = {"state_dir": tempfile.mkdtemp(prefix="r18-persist-"), "notify_channel": "none"}
        runner.ensure_state_dir(self.config)
        runner.write_queue_new(self.config, {"modules": [], "runner_state": {"state": "running"}})
        # STEP 02: 注入落盤失敗；通知只看內文
        self.notify = start_patches(self, "notify")["notify"]
        patcher = mock.patch.object(runner, "set_runner_state", side_effect=OSError("磁碟已滿"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_hold_not_persisted_is_said_plainly(self):
        """強制 hold 但落盤失敗：通知要說鎖定沒有寫進狀態檔、要人立刻停掉 launchd 服務。"""
        # STEP 01: 走 force_hold 的暫停
        exit_code = runner.enter_paused(self.config, runner.CRASH_REASON, "細節", signature="sig", force_hold=True)
        self.assertEqual(exit_code, runner.EXIT_PAUSED)

        # STEP 02: 通知內文
        body = self.notify.call_args.args[3]
        self.assertNotIn("已鎖定", body)
        self.assertIn("沒有寫進狀態檔", body)
        self.assertIn("launchctl", body)

        # STEP 03: 事件紀錄也要留下「hold 沒落盤」
        with open(os.path.join(self.config["state_dir"], "runner.log.jsonl"), encoding="utf-8") as handle:
            last_event = handle.read().splitlines()[-1]
        self.assertIn('"hold_persisted": false', last_event)


class LaunchdTemplateTest(unittest.TestCase):
    """launchd 停服務時的 SIGTERM→SIGKILL 間隔要蓋得住中斷路徑最壞的收尾時間，否則殘留行程的鎖定永遠寫不到。"""

    def test_exit_timeout_covers_worst_case_cleanup(self):
        """ExitTimeOut 必須存在，且大於「TERM 寬限＋有上限收屍＋KILL 後確認＋通知子行程上限」的總和——鎖定落盤後的那一則通知也要送得出去。"""
        # STEP 01: 讀範本
        template_path = os.path.join(os.path.dirname(HELPERS_DIR), "templates", "launchd.plist.template")
        with open(template_path, encoding="utf-8") as handle:
            exit_timeout = read_plist_integer(handle.read(), "ExitTimeOut")

        # STEP 02: 最壞收尾＝TERM 寬限期 + _reap_with_limit + KILL 之後的 _wait_group_empty + 通知子行程
        worst_case = runner.TERM_GRACE_SECONDS + 2 * runner.REAP_LIMIT_SECONDS + runner.NOTIFY_TIMEOUT_SECONDS
        self.assertIsNotNone(exit_timeout, "plist 範本缺 ExitTimeOut")
        self.assertGreater(exit_timeout, worst_case)


class CrashHoldTest(unittest.TestCase):
    """回報「CLI 的子孫行程沒收乾淨」的例外第一次出現就要鎖定 runner；其他例外維持同簽名第二次才鎖定。"""

    def setUp(self):
        """只需要狀態目錄與一份 runner 正在執行中的 queue。"""
        # STEP 01: 狀態目錄與 queue
        self.config = {"state_dir": tempfile.mkdtemp(prefix="r18-hold-"), "notify_channel": "none"}
        runner.ensure_state_dir(self.config)
        runner.write_queue_new(self.config, {"modules": [], "runner_state": {"state": "running"}})
        # STEP 02: 通知不是受測對象，但要看它的內文
        patcher = mock.patch.object(runner, "notify")
        self.notify = patcher.start()
        self.addCleanup(patcher.stop)

    def _crash_with(self, error):
        """在 except 區塊內呼叫 handle_runner_crash（它用 traceback.format_exc 取當前例外），回傳 (退出碼, runner_state)。

        @param error 要拋出的例外物件
        """
        # STEP 01: 拋出並交給 crash 流程
        try:
            raise error
        except Exception as exc:  # pylint: disable=broad-except
            exit_code = runner.handle_runner_crash(self.config, exc)
        return exit_code, runner.load_queue(self.config)["runner_state"]

    def test_leftover_process_forces_hold_on_first_occurrence(self):
        """殘留行程：launchd 會在幾分鐘後自動重啟 runner，不立刻鎖定的話它會在殘留行程還活著時又開始動 repo。"""
        # STEP 01: 兩種收尾例外各驗一次
        for error in (runner.LeftoverProcessError("測試"), runner.UnsignalableGroupError("測試")):
            with self.subTest(error=type(error).__name__):
                runner.write_queue_new(self.config, {"modules": [], "runner_state": {"state": "running"}})
                exit_code, state = self._crash_with(error)

                # STEP 02: 第一次就鎖定，通知要告訴人為什麼鎖、怎麼解除（不可套用「重複發生」那句）
                self.assertEqual(exit_code, runner.EXIT_PAUSED)
                self.assertTrue(state["hold"])
                body = self.notify.call_args.args[3]
                self.assertIn("必須人工確認後才能繼續", body)
                self.assertNotIn("重複發生", body)
                self.assertIn("unblock --runner", body)

    def test_signal_during_crash_flow_does_not_skip_hold(self):
        """crash 流程凍結診斷包期間再收到停止訊號：hold 仍要落盤、回 EXIT_PAUSED，訊號不能從 except handler 裡跳出去放鎖。"""
        # STEP 01: 凍結診斷包期間觸發 handler（直接呼叫模擬訊號，不真的裝訊號）
        real_freeze = runner.freeze_runner_bundle

        def freeze_with_signal(*args, **kwargs):
            """先觸發停止訊號的 handler，再照常凍結。"""
            runner.shutdown_signal_handler(signal.SIGTERM, None)
            return real_freeze(*args, **kwargs)

        with mock.patch.object(runner, "freeze_runner_bundle", freeze_with_signal):
            raised = None
            try:
                exit_code, state = self._crash_with(runner.LeftoverProcessError("測試"))
            except BaseException as exc:  # pylint: disable=broad-except
                raised, exit_code, state = exc, None, runner.load_queue(self.config)["runner_state"]

        # STEP 02: 沒有例外跳出、hold 已落盤、區間狀態清乾淨
        self.assertIsNone(raised, "訊號從 crash 流程跳出: %r" % raised)
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self.assertTrue(state.get("hold"))
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_signal_during_forced_hold_persist_does_not_skip_hold(self):
        """force_hold 的暫停（不經 crash 流程）在凍結證據期間再收到停止訊號：hold 仍要落盤、回 EXIT_PAUSED。

        不然訊號落在「本機整合分支已退回」與「hold 寫進 queue」之間，外層當正常停止回 EXIT_OK；重啟後
        本機已對齊、前置作業偵測不到原本的不符，entry 放回 pending 繼續跑——宣稱必須人工確認的鎖定被整個繞過。
        """
        # STEP 01: 凍結 runner 級診斷包期間觸發 handler
        real_freeze = runner.freeze_runner_bundle

        def freeze_with_signal(*args, **kwargs):
            """先觸發停止訊號的 handler，再照常凍結。"""
            runner.shutdown_signal_handler(signal.SIGTERM, None)
            return real_freeze(*args, **kwargs)

        with mock.patch.object(runner, "freeze_runner_bundle", freeze_with_signal):
            raised = None
            try:
                exit_code = runner.enter_paused(self.config, "integration_diverged", "模擬 mismatch", force_hold=True)
            except BaseException as exc:  # pylint: disable=broad-except
                raised, exit_code = exc, None

        # STEP 02: 沒有例外跳出、hold 已落盤、區間狀態清乾淨
        state = runner.load_queue(self.config)["runner_state"]
        self.assertIsNone(raised, "訊號從 enter_paused 跳出: %r" % raised)
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self.assertTrue(state.get("hold"))
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_ordinary_crash_does_not_hold_on_first_occurrence(self):
        """對照組：一般例外第一次只暫停、不鎖定——確認不是所有 crash 都被改成立刻鎖定。"""
        # STEP 01: 一般的 RuntimeError
        exit_code, state = self._crash_with(RuntimeError("測試"))
        self.assertEqual(exit_code, runner.EXIT_PAUSED)
        self.assertFalse(state["hold"])


class MergeToIntegrationTest(unittest.TestCase):
    """C3：push 之前要確認 ff-merge 後的 HEAD 就是預期的 entry commit。"""

    def test_head_mismatch_refuses_to_push(self):
        """HEAD 與預期不符：回報 integration_mismatch（呼叫端據此鎖定），遠端整合分支不動。"""
        # STEP 01: 給一個不可能相符的預期值
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-"))
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], IMPOSSIBLE_SHA)

        # STEP 02: 拒絕推送
        self.assertEqual(result, "integration_mismatch", detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])

    def test_head_mismatch_resets_local_integration_branch(self):
        """HEAD 與預期不符時，本機整合分支要退回合併前的 commit，不能停在那個非預期的 commit 上。

        ff-merge 已經把本機分支往前推了；只回報不推送的話，本機領先遠端、下一次 --ff-only 同步是
        no-op，後面的 entry 會從那個 commit 切分支、最後把它推上去。退回成功的結果值是
        integration_mismatch，與一般 diverged 分開——呼叫端對它要鎖定。
        """
        # STEP 01: 預期值取 collect 當下的 entry commit，之後 entry 分支又多了一個 commit（殘留行程還在改 repo 的情境）
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-reset-"))
        work = fixture["config"]["repo_dir"]
        with open(os.path.join(work, "late.js"), "w", encoding="utf-8") as handle:
            handle.write("// committed after closing data was collected\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "late commit")
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 拒絕推送，而且本機整合分支回到基線
        self.assertEqual(result, "integration_mismatch", detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"], detail)

    def _mismatch_fixture(self):
        """建一組「collect 之後 entry 分支又多了一個 commit」的環境，回傳 (fixture, 那個晚到的 commit sha)。"""
        # STEP 01: fixture＋晚到的 commit
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-unrec-"))
        work = fixture["config"]["repo_dir"]
        with open(os.path.join(work, "late.js"), "w", encoding="utf-8") as handle:
            handle.write("// late\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "late commit")
        return fixture, run_git(work, "rev-parse", "HEAD")

    @staticmethod
    def _git_with_failure(match, response):
        """回傳一個包住真 git 的替身：參數以 match 開頭的那次呼叫回 response，其餘照常執行。

        @param match 要攔截的 git 子命令參數前綴（tuple）
        @param response 攔截時回傳的 (code, out, err)
        @return 可用來 patch runner.git 的函式
        """
        real_git = runner.git

        def fake_git(config, *args, **kwargs):
            """只攔一種呼叫。"""
            if tuple(args[: len(match)]) == match:
                return response
            return real_git(config, *args, **kwargs)

        return fake_git

    def test_reset_failure_is_reported_as_unrecovered(self):
        """mismatch 且 reset 失敗：結果要是 integration_unrecovered（呼叫端據此鎖定），不能只是 detail 裡一句「請人工處理」。"""
        # STEP 01: 注入 reset --keep 中止（仿真 git 的兩行輸出：第一行點名哪個檔 not uptodate、第二行 fatal 帶 40 字元 sha；
        # 路徑取長的，總長超過 200，取尾端就會把檔名切掉——第十六輪實測 git 就是這樣印的）
        fixture, _late = self._mismatch_fixture()
        long_path = "src/containers/Form/Calendar/ServiceTime/SeparateStartDate/Modal/CalendarServiceTimeSeparateStartDateModal/index.js"
        git_error = "error: Entry '%s' not uptodate. Cannot merge.\nfatal: Could not reset index file to revision '%s'." % (long_path, "f" * 40)
        self.assertGreater(len(git_error), 200, "前置條件：錯誤要長到取尾端會切掉第一行")
        fake_git = self._git_with_failure(("reset", "--keep"), (128, "", git_error))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 結果值本身要能區分「沒退回」；detail 要帶合併前的 HEAD（人工退回時要知道退到哪，diagnostics 不收 git 狀態）、
        # 要點名是哪個檔讓 --keep 中止（取第一行，不是尾端）
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn("error: Entry 'src/containers", detail)
        self.assertIn("reset --keep", detail)
        self.assertIn(fixture["base_sha"][:12], detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])

    def test_head_off_integration_branch_skips_reset(self):
        """mismatch 時 HEAD 已不在整合分支上（別的東西切走了）：不可以 reset（會打到別人的分支），回 unrecovered。"""
        # STEP 01: 讓「現在在哪個分支」回別的名字
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        fake_git = self._git_with_failure(("symbolic-ref", "--short", "HEAD"), (0, "someone-else\n", ""))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 沒 reset（本機整合分支仍停在晚到的 commit）、結果是 unrecovered、detail 說了在哪、帶合併前的 HEAD
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn("someone-else", detail)
        self.assertIn(fixture["base_sha"][:12], detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)

    def test_dirty_tree_at_mismatch_skips_reset(self):
        """mismatch 時已追蹤檔有未提交變更：reset --hard 會把別人留下的東西無聲抹掉，所以不 reset、把清單留在 detail、回 unrecovered。"""
        # STEP 01: 改一個已追蹤檔、不提交（真的髒，不 mock）
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        dirty_path = os.path.join(work, R15_RELATIVE_PATH)
        with open(dirty_path, "a", encoding="utf-8") as handle:
            handle.write("// someone was here\n")
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 變更還在、分支沒動、detail 點名那個檔、帶合併前的 HEAD
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn(R15_RELATIVE_PATH, detail)
        self.assertIn(fixture["base_sha"][:12], detail)
        with open(dirty_path, "r", encoding="utf-8") as handle:
            self.assertIn("someone was here", handle.read())
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)

    def test_dirty_list_shows_first_lines_and_total(self):
        """髒污清單超過預覽行數：detail 列前幾個檔名＋總數，不是尾端截斷（通知會再截尾，前幾行才是有用的）。"""
        # STEP 01: 比預覽行數多兩個的已追蹤檔——先加在整合分支、entry 分支 rebase 上去（兩邊內容相同，
        # checkout 才會把未提交的修改帶著走），然後全部改一次不提交；不符用不可能的預期值造
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-dirty-list-"))
        work = fixture["config"]["repo_dir"]
        names = ["dirty-%d.js" % index for index in range(runner.DIRTY_LIST_PREVIEW_LINES + 2)]
        run_git(work, "checkout", INTEGRATION_BRANCH)
        for name in names:
            with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
                handle.write("// tracked\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "tracked files")
        run_git(work, "checkout", ENTRY_BRANCH)
        run_git(work, "rebase", INTEGRATION_BRANCH)
        for name in names:
            with open(os.path.join(work, name), "a", encoding="utf-8") as handle:
                handle.write("// modified\n")
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], IMPOSSIBLE_SHA)

        # STEP 02: 前幾個在、最後一個不在、總數在
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn(names[0], detail)
        self.assertNotIn(names[-1], detail)
        self.assertIn("共 %d" % len(names), detail)

    def test_untracked_file_does_not_block_reset(self):
        """mismatch 時只有未追蹤檔：reset --hard 不會動它們，所以照樣退回；清單另附進 detail 給人看。"""
        # STEP 01: 工作樹留一個未追蹤檔
        fixture, _late = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        with open(os.path.join(work, "leftover-evidence.txt"), "w", encoding="utf-8") as handle:
            handle.write("someone was here\n")
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 退回了、檔案還在、detail 點名那個檔
        self.assertEqual(result, "integration_mismatch", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"])
        self.assertTrue(os.path.exists(os.path.join(work, "leftover-evidence.txt")))
        self.assertIn("leftover-evidence.txt", detail)

    def test_status_failure_is_reported_distinctly(self):
        """mismatch 時 git status 本身失敗：不能歸成「工作樹不乾淨」，要說是 status 失敗、帶它的錯誤，而且不 reset。"""
        # STEP 01: 注入 status 失敗
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        fake_git = self._git_with_failure(("status", "--porcelain"), (128, "", "simulated status failure"))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: unrecovered、原因說對（不是「有東西會被抹掉」那一種）、沒 reset
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn("simulated status failure", detail)
        self.assertNotIn("reset --hard 會抹掉", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)

    def test_tracked_change_after_status_check_is_not_wiped(self):
        """status 看到乾淨之後、reset 之前有人改了已追蹤檔（它在合併前後兩個 commit 之間有差）：不可以抹掉，回 unrecovered。

        這個函式正是在「可能有別的寫入者」時被呼叫的，status 與 reset 之間的窗不是純理論；reset --hard 會無條件
        覆寫工作樹，改用 reset --keep——要覆寫的檔有本機修改就整個中止。
        """
        # STEP 01: 包住 status：照真的跑、回真的結果，但回傳前先改 late.js（合併後 HEAD 有、合併前沒有的檔）
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        late_path = os.path.join(work, "late.js")
        real_git = runner.git

        def fake_git(config, *args, **kwargs):
            """status 剛回報乾淨就有人寫檔。"""
            result = real_git(config, *args, **kwargs)
            if tuple(args[:2]) == ("status", "--porcelain"):
                with open(late_path, "a", encoding="utf-8") as handle:
                    handle.write("// written by someone else right after the status check\n")
            return result

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 沒退回、對方的修改還在
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)
        with open(late_path, "r", encoding="utf-8") as handle:
            self.assertIn("written by someone else", handle.read())

    def test_head_changed_between_check_and_reset_skips_reset(self):
        """symbolic-ref／status 檢查之後、reset 之前 HEAD 又變了：不 reset（會抹掉那個新 commit），回 unrecovered。

        不符的前提就是「有別的東西在改 repo」，檢查與 reset 之間它可能再 commit 一次；reset 之前要再比一次 HEAD。
        """
        # STEP 01: 第三次 rev-parse HEAD（前兩次是合併前後的正常讀取）回一個別的 sha
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        real_git = runner.git
        head_reads = []

        def fake_git(config, *args, **kwargs):
            """第三次讀 HEAD 時假裝有人又動了它。"""
            if tuple(args) == ("rev-parse", "HEAD"):
                head_reads.append(args)
                if len(head_reads) == 3:
                    return 0, IMPOSSIBLE_SHA + "\n", ""
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 前置條件：確實讀了三次；結果 unrecovered、沒 reset
        self.assertEqual(len(head_reads), 3, "reset 之前應該再讀一次 HEAD")
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertIn(IMPOSSIBLE_SHA, detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)

    def test_push_failure_restores_local_branch_and_stays_retryable(self):
        """ff-merge 成功但推送失敗：本機整合分支要退回合併前，結果是 integration_push_failed（可重試），entry 分支的 commit 還在。

        不退回的話本機領先遠端，下一輪前置作業會判成 integration_local_ahead 並鎖定——一次網路抖動
        就要人工介入；退回之後重跑：l1_verify 看得到 entry 分支相對整合分支的新 commit、PR 沿用、再 ff-merge 再推。
        結果值與一般 diverged 分開：呼叫端要對它帶簽名，連續第二次才鎖定。
        """
        # STEP 01: 遠端只拒絕整合分支（真的 pre-receive hook）
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-pushfail-"))
        work = fixture["config"]["repo_dir"]
        reject_entry_branch_push(fixture["remote"], branch=INTEGRATION_BRANCH)
        result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: push_failed、本機退回基線、遠端沒動、entry 分支還在原處
        self.assertEqual(result, "integration_push_failed", detail)
        self.assertIn("pre-receive hook declined", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"], detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["base_sha"])
        self.assertEqual(run_git(work, "rev-parse", ENTRY_BRANCH), fixture["entry_sha"])

    def test_push_reported_failed_but_remote_updated_counts_as_done(self):
        """git push 回非零（逾時、連線在回報前斷掉）但遠端其實已是預期的 commit：要當成 done，不退回、不暫停。

        退回的話本機退到合併前、遠端已前進、tip 沒記，下一輪前置作業 STEP 03 判成「遠端整合分支 tip
        與記錄值不同」——文件定義的「有別人動了整合分支」，實際是 runner 自己，而且同原因重複暫停不通知。
        """
        # STEP 01: push 真的執行、然後假裝失敗
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-pushlie-"))
        work = fixture["config"]["repo_dir"]
        real_git = runner.git

        def fake_git(config, *args, **kwargs):
            """推送照做，回報改成失敗。"""
            result = real_git(config, *args, **kwargs)
            if tuple(args[:3]) == ("push", "origin", INTEGRATION_BRANCH):
                return 124, "", "simulated timeout after the push landed"
            return result

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: done、遠端與本機都在 entry commit、detail 說明推送回報失敗但遠端已對
        self.assertEqual(result, "done", detail)
        self.assertEqual(remote_tip(fixture, INTEGRATION_BRANCH), fixture["entry_sha"])
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["entry_sha"])
        self.assertIn("simulated timeout", detail)

    def test_push_failure_with_unknown_remote_state_locks_without_restore(self):
        """推送失敗、而且問遠端也失敗：不知道遠端有沒有收到，不可以退回本機、也不可以說可重試——回 unrecovered（呼叫端鎖定），本機留在原處當證據。

        退回的話：遠端其實收到了 → 本機落後、tip 沒記、下一輪 STEP 03 靜默 diverged；說可重試的話：重跑一次完整模組。
        """
        # STEP 01: 遠端拒絕整合分支，ls-remote 也失敗
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-pushunknown-"))
        work = fixture["config"]["repo_dir"]
        reject_entry_branch_push(fixture["remote"], branch=INTEGRATION_BRANCH)
        fake_git = self._git_with_failure(("ls-remote",), (128, "", "simulated ls-remote failure"))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: unrecovered、本機沒退回（停在 entry commit）、detail 帶錯誤與兩個 sha
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["entry_sha"])
        self.assertIn("simulated ls-remote failure", detail)
        self.assertIn(fixture["entry_sha"], detail)
        self.assertIn(fixture["base_sha"], detail)

    def test_head_unreadable_after_merge_is_not_called_a_change(self):
        """合併後讀不到 HEAD：不 reset、回 unrecovered，訊息要說「讀不到」，不能說「HEAD 又變了」（人會去追不存在的寫入者）。"""
        # STEP 01: 第二次 rev-parse HEAD（合併後那次）失敗，其餘照常
        fixture, late_sha = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        real_git = runner.git
        head_reads = []

        def fake_git(config, *args, **kwargs):
            """合併後那次讀 HEAD 失敗。"""
            if tuple(args) == ("rev-parse", "HEAD"):
                head_reads.append(args)
                if len(head_reads) == 2:
                    return 128, "", "simulated post-merge failure"
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: unrecovered、沒 reset、措辭對
        self.assertEqual(result, "integration_unrecovered", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), late_sha)
        self.assertIn("simulated post-merge failure", detail)
        self.assertNotIn("又變了", detail)

    def test_untracked_list_failure_is_said_plainly(self):
        """列未追蹤檔的指令失敗：退回照做（那只是附帶資訊），但說明要寫「清單讀取失敗」，不能跟「沒有未追蹤檔」同形。"""
        # STEP 01: 注入 ls-files 失敗
        fixture, _late = self._mismatch_fixture()
        work = fixture["config"]["repo_dir"]
        fake_git = self._git_with_failure(("ls-files", "--others"), (128, "", "simulated ls-files failure"))
        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 退回了、說明帶失敗原因
        self.assertEqual(result, "integration_mismatch", detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"])
        self.assertIn("simulated ls-files failure", detail)

    def test_read_head_before_merge_failure_stops_before_merge(self):
        """合併前讀不到 HEAD：不合併（沒有東西可退回），回 integration_diverged，本機分支不動。

        用記錄呼叫的假 git 釘住「沒有跑 merge --ff-only」——只看結果值與分支位置的話，把合併前那次
        讀取刪掉、讓合併後的讀取失敗，結果一樣是 diverged＋分支退回基線，測試照樣綠。
        """
        # STEP 01: 所有 rev-parse HEAD 都失敗，其餘照常，並記下每一次 git 呼叫
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-merge-head-"))
        work = fixture["config"]["repo_dir"]
        real_git = runner.git
        calls = []

        def fake_git(config, *args, **kwargs):
            """記錄後轉發；讀 HEAD 一律失敗。"""
            calls.append(tuple(args))
            if tuple(args) == ("rev-parse", "HEAD"):
                return 1, "", "simulated rev-parse failure"
            return real_git(config, *args, **kwargs)

        with mock.patch.object(runner, "git", fake_git):
            result, detail = runner.merge_to_integration(fixture["config"], fixture["entry"], fixture["entry_sha"])

        # STEP 02: 停在合併之前——沒有任何一次 merge --ff-only
        self.assertEqual(result, "integration_diverged", detail)
        self.assertIn("simulated rev-parse failure", detail)
        self.assertEqual([call for call in calls if call[:2] == ("merge", "--ff-only")], [])
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), fixture["base_sha"])


class ModulePreflightTest(unittest.TestCase):
    """第十批起：本機整合分支上「不是 runner 合進來的 commit」要在模組開工前被偵測到、用專屬原因暫停（呼叫端據此鎖定）。

    本機領先遠端本身是常態——前置作業會把基準分支與斷點分支合進本機而不推；排除 merge commit、
    排除可從基準／斷點分支到達的 commit 之後還剩下的，才是上一輪沒走完的發佈段（合併了但推送失敗
    或被中斷、退不回去、或人只跑了 `unblock --runner` 沒把本機對齊）留下的：原本的 `--ff-only`
    同步對它是 no-op，下一個 entry 會從那個 commit 切分支、最後把它推上去。
    """

    def _preflight_fixture(self):
        """真的 git 環境：獨立的基準分支從基線切出、推上遠端、再前進一個 commit；停在整合分支上。

        基準分支一定要跟整合分支分開而且已經前進——前置作業會把它合進本機整合分支、而且不推，
        這正是「runner 自己造出來的本機領先」；第十批的對照組把基準分支設成整合分支本身
        （合併是 no-op），跑不到這個拓撲，回歸就這樣漏掉了。

        @return build_fixture 的回傳值
        """
        # STEP 01: fixture＋基準分支前進一個 commit＋切回整合分支
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-preflight-"))
        work = fixture["config"]["repo_dir"]
        fixture["config"]["base_branch"] = BASE_BRANCH
        run_git(work, "checkout", "-b", BASE_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(work, "hotfix.js"), "w", encoding="utf-8") as handle:
            handle.write("// landed on base after the integration branch was cut\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "base moves")
        run_git(work, "push", "-u", "origin", BASE_BRANCH)
        run_git(work, "checkout", INTEGRATION_BRANCH)
        return fixture

    def test_own_base_merge_is_not_treated_as_ahead(self):
        """基準分支前進、前置作業把它合進本機整合分支而不推：這種領先是 runner 自己造的，下一輪不可以當成異常。

        修正前：第一次通過（並留下領先的 commit），第二次就 integration_local_ahead＋鎖定——只要
        base 動過、而該 entry 沒走到 push（失敗／blocked／額度／斷點），runner 就鎖死。
        """
        # STEP 01: 連跑兩次前置作業
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        ahead = run_git(work, "rev-list", "--count", "origin/%s..%s" % (INTEGRATION_BRANCH, INTEGRATION_BRANCH))
        self.assertNotEqual(ahead, "0", "前置條件：base 合併後本機整合分支應該領先遠端")
        second = runner.module_preflight(config, runner.load_queue(config))

        # STEP 02: 第二次照樣通過
        self.assertTrue(second[0], "%s: %s" % (second[1], second[2]))

    def test_checkpoint_conflict_after_base_merge_does_not_lock_next_round(self):
        """base 已合進本機、斷點回流衝突退出：下一輪要再回 master_conflict（真正的原因），不能變成 integration_local_ahead 鎖定。

        第十二批的記錄式判定只在前置作業全部成功時才記本機 HEAD，這條路徑 HEAD 動了但沒記，下一輪就
        誤鎖、細節還說「不是 runner 自己做的合併」；判定改成結構式（只數不可從 base／斷點分支到達的
        非 merge commit）之後沒有這個窗。
        """
        # STEP 01: base 與斷點分支改同一個檔（不同內容）；斷點登記成 opened
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        run_git(work, "checkout", BASE_BRANCH)
        with open(os.path.join(work, R15_RELATIVE_PATH), "w", encoding="utf-8") as handle:
            handle.write("// base version\n")
        run_git(work, "commit", "-am", "base edits a.js")
        run_git(work, "push", "origin", BASE_BRANCH)
        run_git(work, "checkout", "-b", CHECKPOINT_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(work, R15_RELATIVE_PATH), "w", encoding="utf-8") as handle:
            handle.write("// checkpoint version\n")
        run_git(work, "commit", "-am", "checkpoint edits a.js")
        run_git(work, "checkout", INTEGRATION_BRANCH)
        runner.mutate_queue(config, _register_opened_checkpoint)

        # STEP 02: 兩輪都是 master_conflict；本機仍領先（base 合進來了）、但不是鎖定
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertEqual(first[1], "master_conflict", first[2])
        ahead = run_git(work, "rev-list", "--count", "origin/%s..%s" % (INTEGRATION_BRANCH, INTEGRATION_BRANCH))
        self.assertNotEqual(ahead, "0", "前置條件：base 合併後本機整合分支應該領先遠端")
        second = runner.module_preflight(config, runner.load_queue(config))
        self.assertEqual(second[1], "master_conflict", second[2])

    def test_own_checkpoint_merge_is_not_treated_as_ahead(self):
        """斷點分支多了人工修正、前置作業把它合進本機整合分支而不推：這種領先也是 runner 自己做的，下一輪照常通過。"""
        # STEP 01: 斷點分支從整合分支切出、多一個不衝突的 commit、登記成 opened
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        run_git(work, "checkout", "-b", CHECKPOINT_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(work, "review-fix.js"), "w", encoding="utf-8") as handle:
            handle.write("// pushed to the checkpoint branch by a reviewer\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "review fix on checkpoint")
        run_git(work, "checkout", INTEGRATION_BRANCH)
        runner.mutate_queue(config, _register_opened_checkpoint)

        # STEP 02: 兩輪都通過
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        self.assertTrue(os.path.exists(os.path.join(work, "review-fix.js")), "前置條件：斷點分支應已回流")
        second = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(second[0], "%s: %s" % (second[1], second[2]))

    def test_local_ahead_is_named_and_left_untouched(self):
        """前置作業之後本機整合分支又多了一個不是 runner 做的 commit：回專屬原因、動作在前、detail 帶兩個 sha 與那個 commit、本機分支不動。"""
        # STEP 01: 先跑一次前置作業（base 已合進本機），再在整合分支上多一個 commit、不推
        fixture = self._preflight_fixture()
        work = fixture["config"]["repo_dir"]
        first = runner.module_preflight(fixture["config"], runner.load_queue(fixture["config"]))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        with open(os.path.join(work, "unpushed.js"), "w", encoding="utf-8") as handle:
            handle.write("// merged locally, never pushed\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "foreign-commit-subject")
        local_sha = run_git(work, "rev-parse", "HEAD")
        ok, reason, detail = runner.module_preflight(fixture["config"], runner.load_queue(fixture["config"]))

        # STEP 02: 專屬原因、兩個 sha 與那個 commit 的主旨都在、分支沒被動；對齊指令排在診斷之前（通知會截尾，動作要先看到）
        self.assertFalse(ok)
        self.assertEqual(reason, runner.LOCAL_AHEAD_REASON, detail)
        self.assertIn(local_sha[:12], detail)
        self.assertIn(fixture["base_sha"][:12], detail)
        self.assertIn("foreign-commit-subject", detail)
        self.assertIn("1 個", detail)
        self.assertLess(detail.index("reset --hard"), detail.index(local_sha[:12]), detail)
        self.assertEqual(run_git(work, "rev-parse", INTEGRATION_BRANCH), local_sha)

    def test_local_ahead_action_survives_notification_truncation(self):
        """用正式預設的整合分支名走一次真的 enter_paused（鎖定），把通知照 notify.sh 的規則（emoji＋標題＋內文，300 字截斷）
        組起來：截斷後仍要看得到對齊指令與 unblock --runner。

        期望值是 notify.sh 的 max_text_chars=300 這個外部契約，不是實作自己的長度常數——拿實作的常數當期望值，
        常數改成 1000 測試照樣綠。第十二批的句子 191 字，這一段截掉 `git reset --hard` 與「再 unblock --runner」（第十二輪實測）。
        """
        # STEP 01: 狀態目錄＋通知 mock；用預設分支名組細節，走真的 enter_paused（會凍結 runner 級診斷包、寫狀態）
        config = {"state_dir": tempfile.mkdtemp(prefix="r18-budget-"), "notify_channel": "none"}
        runner.ensure_state_dir(config)
        runner.write_queue_new(config, {"modules": [], "runner_state": {"state": "running"}})
        detail = runner.local_ahead_detail(runner.DEFAULT_INTEGRATION_BRANCH, "3", "a" * 12, "b" * 12, "abc1234 x\ndef5678 y\n0123456 z")
        with mock.patch.object(runner, "notify") as notify:
            self.assertEqual(runner.enter_paused(config, runner.LOCAL_AHEAD_REASON, detail, force_hold=True), runner.EXIT_PAUSED)
        _config, _event, title, body = notify.call_args.args

        # STEP 02: 照 notify.sh 組字並截斷（emoji 1 字＋空白＋標題＋換行＋內文）
        text = ("🔴 %s\n%s" % (title, body))[:NOTIFY_MAX_TEXT_CHARS]
        self.assertIn("reset --hard origin/%s" % runner.DEFAULT_INTEGRATION_BRANCH, text, text)
        self.assertIn("unblock --runner", text, text)

    def test_checkpoint_ref_listing_failure_does_not_lock(self):
        """列本機 ref 的指令失敗：不能把「查不到」當成「斷點分支都不存在」——那會讓回流進來的斷點 commit 全被當成外來的而鎖定。"""
        # STEP 01: 斷點分支回流進本機（自己做的領先），再讓 for-each-ref 失敗
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        run_git(work, "checkout", "-b", CHECKPOINT_BRANCH, INTEGRATION_BRANCH)
        with open(os.path.join(work, "review-fix.js"), "w", encoding="utf-8") as handle:
            handle.write("// reviewer fix\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "review fix on checkpoint")
        run_git(work, "checkout", INTEGRATION_BRANCH)
        runner.mutate_queue(config, _register_opened_checkpoint)
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        fake_git = MergeToIntegrationTest._git_with_failure(("for-each-ref",), (128, "", "simulated for-each-ref failure"))
        with mock.patch.object(runner, "git", fake_git):
            ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))

        # STEP 02: 不放行、但也不是鎖定的那個原因；錯誤有帶出來
        self.assertFalse(ok)
        self.assertNotEqual(reason, runner.LOCAL_AHEAD_REASON, detail)
        self.assertIn("simulated for-each-ref failure", detail)

    def test_foreign_commit_listing_failure_is_not_treated_as_zero(self):
        """列「不是 runner 合進來的 commit」的指令失敗：不能當成 0 個放行。"""
        # STEP 01: 造出領先（base 合併），再讓那條 git log 失敗
        fixture = self._preflight_fixture()
        config = fixture["config"]
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        fake_git = MergeToIntegrationTest._git_with_failure(("log", "--no-merges"), (128, "", "simulated log failure"))
        with mock.patch.object(runner, "git", fake_git):
            ok, _reason, detail = runner.module_preflight(config, runner.load_queue(config))
        self.assertFalse(ok)
        self.assertIn("simulated log failure", detail)

    def test_not_ahead_passes(self):
        """對照組：本機與遠端一致（基準分支沒動）時前置作業照常通過。"""
        # STEP 01: 基準分支就用整合分支本身，什麼都不合併
        fixture = build_fixture(tempfile.mkdtemp(prefix="r18-preflight-plain-"))
        fixture["config"]["base_branch"] = INTEGRATION_BRANCH
        run_git(fixture["config"]["repo_dir"], "checkout", INTEGRATION_BRANCH)
        queue = runner.load_queue(fixture["config"])
        ok, reason, detail = runner.module_preflight(fixture["config"], queue)
        self.assertTrue(ok, "%s: %s" % (reason, detail))

    def test_local_tip_read_failure_is_said_plainly(self):
        """領先且讀不到本機 tip：訊息要說「讀取失敗」，不能渲染成空字串讓人以為 sha 是空的。"""
        # STEP 01: 造出領先，再讓讀本機整合分支 sha 那一次失敗
        fixture = self._preflight_fixture()
        config = fixture["config"]
        work = config["repo_dir"]
        first = runner.module_preflight(config, runner.load_queue(config))
        self.assertTrue(first[0], "%s: %s" % (first[1], first[2]))
        with open(os.path.join(work, "unpushed.js"), "w", encoding="utf-8") as handle:
            handle.write("// unpushed\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "unpushed")
        fake_git = MergeToIntegrationTest._git_with_failure(("rev-parse", INTEGRATION_BRANCH), (128, "", "simulated tip failure"))
        with mock.patch.object(runner, "git", fake_git):
            ok, reason, detail = runner.module_preflight(config, runner.load_queue(config))

        # STEP 02: 仍判定領先，訊息帶「讀取失敗」
        self.assertFalse(ok)
        self.assertEqual(reason, runner.LOCAL_AHEAD_REASON, detail)
        self.assertIn("讀取失敗", detail)

    def test_ahead_count_read_failure_is_not_treated_as_zero(self):
        """rev-list 本身失敗：不能當成「領先 0 個」放行，要當成讀不到而暫停。"""
        # STEP 01: 注入 rev-list 失敗
        fixture = self._preflight_fixture()
        fake_git = MergeToIntegrationTest._git_with_failure(("rev-list", "--count"), (128, "", "simulated rev-list failure"))
        queue = runner.load_queue(fixture["config"])
        with mock.patch.object(runner, "git", fake_git):
            ok, _reason, detail = runner.module_preflight(fixture["config"], queue)

        # STEP 02: 不放行、錯誤有帶出來
        self.assertFalse(ok)
        self.assertIn("simulated rev-list failure", detail)


class UnblockReminderTest(unittest.TestCase):
    """兩個 unblock 子命令各只清一半狀態：另一半還在時要提醒，不能只印「下次啟動會繼續」。

    鎖定（hold）配 integration 類的暫停原因時，`--integration-tip` 清得掉暫停原因、清不掉 hold，
    只跑它 runner 下次啟動仍在 pre-flight 之前靜默退出；`--runner` 清得掉 hold、清不掉暫停原因，
    只跑它的話遠端整合分支若有變動，下次啟動會再次暫停而且（同原因重複）不通知。
    """

    def setUp(self):
        """真的 git 環境（--integration-tip 會 fetch），runner 狀態設成「本機領先」的鎖定暫停。"""
        # STEP 01: fixture＋狀態
        self.fixture = build_fixture(tempfile.mkdtemp(prefix="r18-unblock-"))

        def lock_on_local_ahead(queue):
            """runner_state 改成鎖定中的 integration 類暫停。"""
            queue["runner_state"] = {"state": "paused", "reason": runner.LOCAL_AHEAD_REASON, "hold": True}

        runner.mutate_queue(self.fixture["config"], lock_on_local_ahead)

    def _run_capturing_stdout(self, function):
        """執行 unblock 函式並收下它印到 stdout 的文字。

        @param function 要執行的 unblock 函式（只吃 config）
        @return (退出碼, stdout 全文)
        """
        # STEP 01: 導向 stdout
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = function(self.fixture["config"])
        return code, buffer.getvalue()

    def test_integration_tip_clears_reason_but_warns_about_hold(self):
        """--integration-tip：本機領先這個原因要清得掉；hold 還在就要說還要 --runner，不能說下次啟動會繼續。"""
        # STEP 01: 執行
        code, output = self._run_capturing_stdout(runner.unblock_integration_tip)
        self.assertEqual(code, runner.EXIT_OK, output)

        # STEP 02: 暫停原因清了、hold 沒動、提醒有印
        queue = runner.load_queue(self.fixture["config"])
        self.assertEqual(queue["runner_state"]["state"], "idle")
        self.assertTrue(queue["runner_state"]["hold"])
        self.assertIn("unblock --runner", output)
        self.assertNotIn("下次啟動會從這個 SHA 繼續", output)

    def test_runner_clears_hold_but_warns_about_integration_reason(self):
        """--runner：hold 清掉；integration 類的暫停原因還在就要提醒本機對齊後跑 --integration-tip。"""
        # STEP 01: 執行
        code, output = self._run_capturing_stdout(runner.unblock_runner)
        self.assertEqual(code, runner.EXIT_OK, output)

        # STEP 02: hold 清了、原因沒動、提醒有印；不能先印「下次啟動會續跑」（本機沒對齊就會再鎖，那是假話）
        queue = runner.load_queue(self.fixture["config"])
        self.assertFalse(queue["runner_state"]["hold"])
        self.assertEqual(queue["runner_state"]["reason"], runner.LOCAL_AHEAD_REASON)
        self.assertIn("unblock --integration-tip", output)
        self.assertNotIn("下次啟動會續跑", output)


class NotifyScriptTest(unittest.TestCase):
    """notify.sh 的長度上限要以字元計，不是 byte：bash 3.2 在 locale 不是 UTF-8 時（沒設、或 C／POSIX）
    `${#text}`／`${text:0:N}` 都是 byte 語意，300 的上限對中文只剩約 100 個字。runner 用 CPython 啟動這支
    腳本時 PEP 538 已經帶入 `LC_CTYPE=C.UTF-8`，那條路徑本來就是字元語意；這裡驗的是手動執行、或非 Python
    呼叫端（launchd 的環境沒有 LANG）下的防禦性 locale 守衛。
    """

    def test_length_is_counted_in_characters_without_utf8_locale(self):
        """沒有任何 locale 變數（env -i）、有設但不是 UTF-8（LANG=C）、高優先序是 C 而低優先序是 UTF-8（LC_ALL=C LANG=en_US.UTF-8，有效值是 C）、或名字寫 utf8 但系統沒有這個 locale（bash 安靜退回 C）：載入 notify.sh 的開頭之後，中文字串的長度要等於字元數。判斷用實測（一個中文字算出來是不是 1），不靠名字。

        只 source 到 locale 段的結尾標記；腳本後面會讀參數、動狀態檔，不能整支跑。
        """
        # STEP 01: 兩種環境各跑一次
        script = os.path.join(HELPERS_DIR, "notify.sh")
        probe = 'eval "$(sed -n "1,/^# ---- locale-end/p" "$0")"; t="本機整合分支領先遠端"; printf "%s" "${#t}"'
        for env_name, extra_env in (
            ("empty", []),
            ("LANG=C", ["LANG=C"]),
            ("LC_ALL=C 蓋過 LANG=UTF-8", ["LC_ALL=C", "LANG=en_US.UTF-8"]),
            ("LANG=en_US.utf8（glibc 寫法，這台沒有這個 locale）", ["LANG=en_US.utf8"]),
        ):
            with self.subTest(env=env_name):
                result = subprocess.run(
                    ["env", "-i"] + extra_env + ["/bin/bash", "-c", probe, script],
                    capture_output=True,
                    text=True,
                    timeout=SCENARIO_TIMEOUT_SECONDS,
                    check=False,
                )
                # STEP 02: 10 個中文字就是 10，不是 30
                self.assertEqual(result.stdout.strip(), "10", result.stderr)


class RecoverInterruptedEntriesTest(unittest.TestCase):
    """重啟時把上一輪被中斷的 entry 放回 pending：running 之外 waiting_quota 也要——它是停止訊號落在額度等待
    期間留下的，取件只挑 pending、unblock 只收 failed／blocked，不放回就永久卡住、沒有任何指令能救。
    """

    def test_running_and_waiting_quota_go_back_to_pending(self):
        """running 與 waiting_quota 都回 pending、attempts 不變；其餘狀態不動；回傳被復原的 id。"""
        # STEP 01: 五種狀態各一個
        queue = {
            "modules": [
                {"id": "a", "status": "running", "attempts": 2},
                {"id": "b", "status": "waiting_quota", "attempts": 1},
                {"id": "c", "status": "pending", "attempts": 0},
                {"id": "d", "status": "done", "attempts": 0},
                {"id": "e", "status": "blocked", "attempts": 0},
            ]
        }
        recovered = runner.recover_interrupted_entries(queue)

        # STEP 02: 只有前兩個被放回 pending
        self.assertEqual(recovered, ["a", "b"])
        self.assertEqual([m["status"] for m in queue["modules"]], ["pending", "pending", "pending", "done", "blocked"])
        self.assertEqual([m["attempts"] for m in queue["modules"]], [2, 1, 0, 0, 0])


class RunPreflightPauseTest(unittest.TestCase):
    """cmd_run 對 git 前置失敗的處置：本機領先要鎖定；已鎖定時 pre-flight 之前就退出。"""

    def setUp(self):
        """狀態目錄裡放一份有 pending entry 的 queue；主迴圈走到 git 前置之前會碰到的外部依賴全部隔離。"""
        # STEP 01: 狀態目錄與 queue
        self.state_dir = tempfile.mkdtemp(prefix="r18-run-preflight-")
        self.config = {
            "state_dir": self.state_dir,
            "notify_channel": "none",
            "integration_branch": INTEGRATION_BRANCH,
            "circuit_breaker_n": 3,
        }
        runner.ensure_state_dir(self.config)
        entry = dict(runner.RUNTIME_FIELD_DEFAULTS, id=ENTRY_ID, branch=ENTRY_BRANCH, type="page", wave=0, r15_paths=[])
        runner.write_queue_new(
            self.config,
            {"integration_tip_sha": IMPOSSIBLE_SHA, "runner_state": {"state": "idle"}, "modules": [entry]},
        )
        self.args = argparse.Namespace(max_modules=None)
        # STEP 02: 隔離——handler 安裝、必填檢查、pre-flight、指紋、通知、每日摘要、額度
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
        )
        self.mocks["require_config"].return_value = True
        self.mocks["lockfile_hash"].return_value = None
        self.mocks["preflight"].return_value = 0
        self.mocks["environment_fingerprint"].return_value = {}
        self.mocks["quota_snapshot"].return_value = {}
        self.mocks["quota_blocks_start"].return_value = (False, "", None)

    def test_local_ahead_pause_is_held(self):
        """git 前置回本機領先：進入暫停時要 force_hold；一般的 diverged 不鎖（對照組）。"""
        # STEP 01: 兩種原因各跑一次主迴圈
        for reason, expect_hold in ((runner.LOCAL_AHEAD_REASON, True), ("integration_diverged", False)):
            with self.subTest(reason=reason):
                with mock.patch.object(runner, "module_preflight", return_value=(False, reason, "模擬")), \
                        mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
                    self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)
                # STEP 02: 原因原樣傳入、hold 旗標對
                self.assertEqual(paused.call_args.args[1], reason)
                self.assertEqual(paused.call_args.kwargs.get("force_hold", False), expect_hold)

    def test_opened_hard_checkpoint_is_waited_before_taking_next_entry(self):
        """上一輪在 hard 斷點等人放行時被停掉：重啟後要先回到等待，不能先處理下一個模組（人工閘門被繞過）。

        斷點停在 opened，而模組完成後的斷點檢查只看 pending 的斷點，所以主迴圈要在取件之前自己找 opened 的 hard 斷點。
        """
        # STEP 01: queue 裡放一個 opened 的 hard 斷點；記下「等待」與「取件後的 git 前置」誰先被呼叫
        calls = []

        def add_checkpoint(queue):
            """登記 opened 的 hard 斷點。"""
            queue["checkpoints"] = [{"id": CHECKPOINT_ID, "status": "opened", "mode": "hard", "branch": CHECKPOINT_BRANCH}]

        runner.mutate_queue(self.config, add_checkpoint)

        def fake_wait(config, checkpoint_id):
            """記錄後放行：跟真的一樣，只有斷點真的變成 released 才回 True（不改狀態就回 True 會讓主迴圈反覆回來等）。"""
            calls.append(("wait", checkpoint_id))

            def release(queue):
                """人工放行。"""
                runner.find_checkpoint(queue, checkpoint_id)["status"] = "released"

            runner.mutate_queue(config, release)
            return True

        def fake_preflight(config, queue):
            """記錄後用一般暫停把主迴圈結束掉。"""
            calls.append(("preflight", None))
            return False, "integration_diverged", "模擬"

        with mock.patch.object(runner, "wait_for_release", fake_wait), \
                mock.patch.object(runner, "module_preflight", fake_preflight), \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)

        # STEP 02: 先等斷點、放行後才走到取件；等待逾時要走 paused_for_review 出口（斷點重設回 opened 再跑一次）
        self.assertEqual(calls[:2], [("wait", CHECKPOINT_ID), ("preflight", None)], calls)
        runner.mutate_queue(self.config, add_checkpoint)
        with mock.patch.object(runner, "wait_for_release", return_value=False), \
                mock.patch.object(runner, "module_preflight") as preflight, \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED) as paused:
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)
        self.assertEqual(paused.call_args.args[1], "paused_for_review")
        preflight.assert_not_called()

    def test_released_checkpoint_is_not_waited_again(self):
        """對照組：已放行（released）或已合併的 hard 斷點不再等，主迴圈直接取件。"""
        # STEP 01: released 的 hard 斷點
        def add_checkpoint(queue):
            """登記 released 的 hard 斷點。"""
            queue["checkpoints"] = [{"id": CHECKPOINT_ID, "status": "released", "mode": "hard", "branch": CHECKPOINT_BRANCH}]

        runner.mutate_queue(self.config, add_checkpoint)
        # 一被呼叫就拋（不是回 True）：回 True 又不改狀態的話，實作若真的去等它，主迴圈會無限迴圈而不是紅
        with mock.patch.object(runner, "wait_for_release", side_effect=AssertionError("不該等已放行的斷點")) as wait, \
                mock.patch.object(runner, "module_preflight", return_value=(False, "integration_diverged", "模擬")), \
                mock.patch.object(runner, "enter_paused", return_value=runner.EXIT_PAUSED):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)
        wait.assert_not_called()

    def test_hold_exits_before_preflight(self):
        """runner_state.hold 為真：pre-flight 一次都不跑就以 EXIT_PAUSED 退出，並留一筆 hold_active 事件。"""
        # STEP 01: 狀態改成鎖定中

        def hold(queue):
            """鎖定。"""
            queue["runner_state"] = {"state": "paused", "reason": runner.LOCAL_AHEAD_REASON, "hold": True}

        runner.mutate_queue(self.config, hold)
        self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)

        # STEP 02: pre-flight 沒被呼叫；事件有記
        self.mocks["preflight"].assert_not_called()
        with open(runner.state_path(self.config, "runner.log.jsonl"), "r", encoding="utf-8") as handle:
            self.assertIn('"event": "hold_active"', handle.read())


class ShutdownDeferralTest(unittest.TestCase):
    """停止訊號落在兩個關鍵區間（Popen 到收尾保護生效之間、收尾本身）時要延後到區間結束，不能留下活的 CLI 行程。

    兩個情境都在獨立行程跑：要真的裝 handler、真的送訊號，不能污染測試行程自己的 handler。
    """

    def _run_scenario(self, script, *extra_args):
        """跑一個情境腳本，回傳 (stdout, stderr)。

        @param script 情境腳本原始碼
        @param extra_args 接在 helpers 目錄之後的 argv
        @return (stdout 去頭尾, stderr)
        """
        # STEP 01: 獨立行程
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, HELPERS_DIR] + list(extra_args),
            capture_output=True,
            text=True,
            timeout=SCENARIO_TIMEOUT_SECONDS,
            check=False,
        )
        return result.stdout.strip(), result.stderr

    def test_second_signal_during_cleanup_is_deferred(self):
        """收尾期間第二次 SIGTERM：收尾照樣把忽略 SIGTERM 的行程 KILL 掉，然後才把訊號當 ShutdownSignal 拋出。"""
        # STEP 01: 情境；忽略者 pid 由它自己寫檔，收場清掉
        workdir = tempfile.mkdtemp(prefix="r18-defer-")
        pid_file = os.path.join(workdir, "ignorer.pid")
        self.addCleanup(kill_pid_in_file, pid_file)
        stdout, stderr = self._run_scenario(SECOND_SIGNAL_DURING_CLEANUP_SCENARIO, pid_file)

        # STEP 02: 訊號沒有被吞掉——收尾完成後仍以 ShutdownSignal 往外傳
        self.assertEqual(stdout, "SHUTDOWN", stderr)

        # STEP 03: 但忽略者必須已經被收掉（修正前：第二個訊號從收尾中途跳出，它還活著）
        ignorer_pid = read_pid_file(pid_file)
        self.assertTrue(
            wait_until_gone(ignorer_pid, GRANDCHILD_EXIT_WAIT_SECONDS),
            "收尾被第二個訊號打斷，忽略 SIGTERM 的行程 %d 仍然存活" % ignorer_pid,
        )

    def test_signal_after_popen_still_cleans_up(self):
        """訊號落在 Popen 內部（子行程已建立、建構子未返回）：call_claude 要先收掉剛啟動的子行程，再讓 ShutdownSignal 往外傳。"""
        # STEP 01: 情境；子行程 pid 由假 Popen 寫檔，收場清掉
        workdir = tempfile.mkdtemp(prefix="r18-popen-")
        pid_file = os.path.join(workdir, "child.pid")
        self.addCleanup(kill_pid_in_file, pid_file)
        stdout, stderr = self._run_scenario(SIGNAL_AFTER_POPEN_SCENARIO, pid_file, workdir)

        # STEP 02: 訊號仍然往外傳
        self.assertEqual(stdout, "SHUTDOWN", stderr)

        # STEP 03: 子行程必須已經不在（修正前：例外直接離開 call_claude，子行程沒人管）
        child_pid = read_pid_file(pid_file)
        self.assertTrue(
            wait_until_gone(child_pid, GRANDCHILD_EXIT_WAIT_SECONDS),
            "訊號落在 Popen 之後，子行程 %d 沒有被收尾就被放著" % child_pid,
        )

    def test_signal_when_popen_fails_is_not_swallowed(self):
        """Popen 失敗（CLI 不存在）當下收到停止訊號：要拋 ShutdownSignal，不能回一個「CLI 失敗」結果讓 runner 繼續。"""
        # STEP 01: 假 Popen 模擬「啟動期間收到訊號、然後啟動失敗」（直接呼叫 handler，不真的裝訊號）
        def failing_popen(*_args, **_kwargs):
            """先觸發 handler 再以 OSError 失敗。"""
            runner.shutdown_signal_handler(signal.SIGTERM, None)
            raise OSError("no such file")

        state_dir = tempfile.mkdtemp(prefix="r18-popen-fail-")
        os.makedirs(os.path.join(state_dir, "sessions"))
        config = {"state_dir": state_dir, "repo_dir": state_dir, "claude_config_dir": None, "module_timeout_min": 1}

        # STEP 02: 訊號要往外傳，而且區間狀態要清乾淨
        with mock.patch.object(runner, "build_claude_command", return_value=["x"]), \
                mock.patch.object(subprocess, "Popen", failing_popen):
            raised = None
            try:
                result = runner.call_claude(config, {"id": "e1"}, 1, False)
            except BaseException as exc:  # pylint: disable=broad-except
                raised = exc
                result = None
        self.assertIsInstance(raised, runner.ShutdownSignal, "訊號被吞掉，call_claude 回了 %r" % result)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_deferral_records_first_signal_and_raises_once_on_normal_exit(self):
        """區間內不論收到幾次訊號都只記第一次、不拋；正常離開區間時拋一次 ShutdownSignal。"""
        # STEP 01: 直接呼叫 handler（不真的裝訊號，避免污染測試行程）；區間內兩次呼叫都不能拋
        reached_end_of_block = False
        with self.assertRaises(runner.ShutdownSignal) as raised:
            with runner.ShutdownDeferral():
                runner.shutdown_signal_handler(signal.SIGTERM, None)
                runner.shutdown_signal_handler(signal.SIGHUP, None)
                reached_end_of_block = True
        self.assertTrue(reached_end_of_block, "handler 在區間內就拋了")
        # STEP 02: 拋的是第一個訊號；狀態已清乾淨，之後的訊號恢復立即拋出
        self.assertIn("15", str(raised.exception))
        self.assertIsNone(runner._PENDING_SIGNUM)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        with self.assertRaises(runner.ShutdownSignal):
            runner.shutdown_signal_handler(signal.SIGTERM, None)

    def test_explicit_end_follows_constructor_flag(self):
        """不帶參數的 end() 要照建構子的 raise_on_normal_exit 決定，不能用自己的預設值蓋掉建構時的宣告。"""
        # STEP 01: 建構時宣告不拋，區間內收到訊號，顯式 end()
        deferral = runner.ShutdownDeferral(raise_on_normal_exit=False)
        raised = None
        with deferral:
            runner.shutdown_signal_handler(signal.SIGTERM, None)
            try:
                deferral.end()
            except BaseException as exc:  # pylint: disable=broad-except
                raised = exc
        # STEP 02: 沒拋、狀態乾淨
        self.assertIsNone(raised, "end() 無視建構子宣告拋了: %r" % raised)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_nested_inner_exception_leaves_decision_to_outer(self):
        """巢狀區間：內層以例外離開只減深度，訊號留給最外層依它自己的離開方式決定（外層正常離開就拋）。"""
        # STEP 01: 內層拋 RuntimeError 被外層接住吞掉，外層正常離開
        raised = None
        try:
            with runner.ShutdownDeferral():
                try:
                    with runner.ShutdownDeferral():
                        runner.shutdown_signal_handler(signal.SIGTERM, None)
                        raise RuntimeError("內層")
                except RuntimeError:
                    pass
        except BaseException as exc:  # pylint: disable=broad-except
            raised = exc
        # STEP 02: 訊號在最外層拋出
        self.assertIsInstance(raised, runner.ShutdownSignal, "最外層正常離開卻沒拋延後的訊號: %r" % raised)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)
        self.assertIsNone(runner._PENDING_SIGNUM)

    def test_deferral_keeps_body_exception_and_drops_pending_signal(self):
        """區間以例外結束（例如收尾回報殘留行程）：原例外優先往外傳，延後的訊號不覆蓋它、也不留到下次。"""
        # STEP 01: 區間內收到訊號後拋出收尾例外；接 BaseException 是為了把「拋錯型別」也變成斷言失敗
        raised = None
        try:
            with runner.ShutdownDeferral():
                runner.shutdown_signal_handler(signal.SIGTERM, None)
                raise runner.LeftoverProcessError("測試")
        except BaseException as exc:  # pylint: disable=broad-except
            raised = exc
        self.assertIsInstance(raised, runner.LeftoverProcessError, "延後的訊號覆蓋了收尾例外: %r" % raised)
        # STEP 02: 沒有殘留的 pending 狀態
        self.assertIsNone(runner._PENDING_SIGNUM)
        self.assertEqual(runner._SIGNAL_DEFER_DEPTH, 0)


class RunShutdownTest(unittest.TestCase):
    """cmd_run：handler 裝好之後的整段都要有出口；沒持鎖時不得走會寫 queue 的 crash 流程。"""

    def setUp(self):
        """最小 config；不在測試行程裡真的安裝 signal handler。"""
        # STEP 01: 狀態目錄
        self.state_dir = tempfile.mkdtemp(prefix="r18-run-")
        self.config = {"state_dir": self.state_dir, "notify_channel": "none"}
        self.args = argparse.Namespace()
        # STEP 02: 隔離 handler 安裝（會改掉測試行程自己的訊號處理）
        patcher = mock.patch.object(runner, "install_shutdown_handlers")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _assert_lock_free(self):
        """確認 runner.lock 沒有被持有（同一行程另開一個 fd 取鎖，flock 以 open file description 為單位）。"""
        # STEP 01: 取得到就立刻放掉
        probe = runner.ProcessLock(runner.state_path(self.config, "runner.lock"))
        self.assertTrue(probe.acquire(), "runner.lock 仍被持有：cmd_run 沒有釋放鎖")
        probe.release()

    def test_shutdown_during_handler_install_exits_ok(self):
        """安裝函式呼叫期間就冒出 ShutdownSignal：同樣要走 EXIT_OK 出口（驗的是 try 有涵蓋安裝那一行）。

        真實時機是「第一個 handler 已裝好、函式還沒返回」；這裡不重現那個中間狀態，只把安裝
        函式整個換成一呼叫就拋，足以驗證 try 的涵蓋範圍。
        """
        # STEP 01: 覆寫 setUp 的隔離，讓安裝動作本身拋出 ShutdownSignal
        with mock.patch.object(runner, "install_shutdown_handlers", side_effect=runner.ShutdownSignal("測試")):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_OK)

    def test_real_signals_are_converted(self):
        """真的裝 handler、真的送訊號：SIGTERM／SIGHUP／SIGINT 都要被轉成 ShutdownSignal（在獨立行程裡跑）。

        SIGINT 也要走同一個 handler：沒接管的話 Python 內建的 KeyboardInterrupt 不受關鍵區間延後，連按兩次
        Ctrl-C 的第二次會打斷收尾；接管之後（第七批）關鍵區間內的第二次 Ctrl-C 一樣只被記下、延後。
        """
        # STEP 01: 三個訊號各跑一次；handler 沒註冊的話行程會直接被訊號終止（SIGINT 則是 KeyboardInterrupt），stdout 是空的
        for signal_name in ("SIGTERM", "SIGHUP", "SIGINT"):
            with self.subTest(signal=signal_name):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", REAL_SIGNAL_SCENARIO, HELPERS_DIR, signal_name],
                    capture_output=True,
                    text=True,
                    timeout=SCENARIO_TIMEOUT_SECONDS,
                    check=False,
                )
                self.assertEqual(result.stdout.strip(), "CONVERTED", result.stderr)

    def test_shutdown_before_lock_exits_ok(self):
        """取鎖之前就收到停止訊號：安靜地以 EXIT_OK 結束，不是讓例外逃出去。"""
        # STEP 01: 訊號落在必填檢查那一行
        with mock.patch.object(runner, "require_config", side_effect=runner.ShutdownSignal("測試")):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_OK)

    def test_shutdown_after_lock_exits_ok_and_releases(self):
        """取鎖之後、主迴圈之前收到停止訊號：EXIT_OK，而且鎖有放掉。"""
        # STEP 01: 訊號落在初始 lockfile hash 那一行（取鎖之後的第一個動作）
        with mock.patch.object(runner, "require_config", return_value=True), \
                mock.patch.object(runner, "lockfile_hash", side_effect=runner.ShutdownSignal("測試")):
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_OK)
        # STEP 02: 鎖已釋放
        self._assert_lock_free()

    def test_error_before_lock_skips_crash_flow(self):
        """取鎖之前的例外：原樣往外拋，不得呼叫會寫 queue 的 handle_runner_crash。"""
        # STEP 01: 例外發生在還沒持鎖的階段
        with mock.patch.object(runner, "require_config", side_effect=RuntimeError("測試")), \
                mock.patch.object(runner, "handle_runner_crash") as crash:
            with self.assertRaises(RuntimeError):
                runner.cmd_run(self.config, self.args)
        # STEP 02: crash 流程沒被碰
        crash.assert_not_called()

    def test_error_after_lock_goes_to_crash_flow(self):
        """取鎖之後的例外（含初始 lockfile hash）：走 crash 流程，而且鎖有放掉。"""
        # STEP 01: 嚴格版 hash 讀取失敗
        with mock.patch.object(runner, "require_config", return_value=True), \
                mock.patch.object(runner, "lockfile_hash", side_effect=RuntimeError("測試")), \
                mock.patch.object(runner, "handle_runner_crash", return_value=runner.EXIT_PAUSED) as crash:
            self.assertEqual(runner.cmd_run(self.config, self.args), runner.EXIT_PAUSED)
        # STEP 02: crash 流程被呼叫一次，鎖已釋放
        crash.assert_called_once()
        self._assert_lock_free()


if __name__ == "__main__":
    unittest.main()
