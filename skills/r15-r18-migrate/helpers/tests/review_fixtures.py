"""r15-r18-migrate 測試共用的 fixture、情境腳本與小工具（原 test_review_fixes.py 的模組層部分，1.1.2 第六批拆出）。

檔名不以 test_ 開頭，unittest discover 不會把它當測試檔收集；這裡只放函式與常數，不放 TestCase。
各測試檔以 `from review_fixtures import ...` 取用。

`sys.dont_write_bytecode` 是為了不在 skill 目錄留下 __pycache__。
"""

import os
import re
import signal
import stat
import subprocess
import sys
import time
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
# 完整 git sha 的長度（SHA-1 十六進位 40 字）
FULL_SHA_CHARS = 40
# 一個不可能等於任何真實 commit 的 sha（40 個 0），用來驗「HEAD 與預期不符就不推送」
IMPOSSIBLE_SHA = "0" * FULL_SHA_CHARS
# 斷言暫停細節／通知含某個 sha 時取的前綴長度：runner 寫進 detail 的縮寫 sha 長度（GIT_SHA_SHORT_CHARS，12）
SHA_PREFIX_CHARS = runner.GIT_SHA_SHORT_CHARS
# 替身 git 模擬失敗時回的退出碼（git 的 fatal 錯誤一律是 128）
GIT_FATAL_EXIT_CODE = 128
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
    runner._terminate_process_group(process, %d, None)
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
        runner._terminate_process_group(process, %d, None)
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
    runner._terminate_process_group(process, %d, None)
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
    runner._terminate_process_group(process, %d, None)
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

# 對自己送訊號後等 handler 轉成例外的上限秒數：超過仍沒轉換就印 NOT_CONVERTED（正常情況下訊號立即送達，不會等滿）
SIGNAL_DELIVERY_WAIT_SECONDS = 5

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
    time.sleep(%d)
    print("NOT_CONVERTED")
except runner.ShutdownSignal:
    print("CONVERTED")
""" % SIGNAL_DELIVERY_WAIT_SECONDS


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
    # `pr list`（1.1.2 第五批起開 PR 前先查既有 PR）回「沒有 open PR」，呼叫記在另一個檔 <呼叫紀錄檔>.list：
    # 既有測試數的是 create／斷點的呼叫，斷言「gh 不應被呼叫」的要兩個檔一起看。情境要分辨子命令的改用 fake_gh.write_scripted_gh
    script_lines = [
        "#!/bin/bash",
        'if [ "$1 $2" = "pr list" ]; then echo "$1 $2" >> "%s.list"; echo "[]"; exit 0; fi' % calls_path,
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


def git_with_failure(match, response):
    """回傳一個包住真 git 的替身：參數以 match 開頭的那次呼叫回 response，其餘照常執行。

    @param match 要攔截的 git 子命令參數前綴（tuple）
    @param response 攔截時回傳的 (code, out, err)
    @return 可用來 patch runner.git 的函式
    """
    # STEP 01: 先握住真的 git（patch 之後 runner.git 就是替身），再包出只攔一種呼叫的替身
    # 被替換前的 runner.git，非攔截的呼叫轉給它
    real_git = runner.git

    def fake_git(config, *args, **kwargs):
        """只攔一種呼叫：參數前綴等於 match 就回 response，其餘轉給真的 git。

        @param config runner 設定（原樣轉給真的 git）
        @param args git 子命令與參數
        @param kwargs 其餘關鍵字參數（原樣轉給真的 git）
        @return (code, out, err)：攔截時是 response，否則是真的 git 的結果
        """
        # STEP 01: 前綴相符就回預設結果，否則照常執行
        if tuple(args[: len(match)]) == match:
            return response
        return real_git(config, *args, **kwargs)

    return fake_git
