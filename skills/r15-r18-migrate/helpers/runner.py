#!/usr/bin/env python3
"""runner.py — 無人看管批次遷移的主控程式。

一次處理一個 entry：從 queue.json 取件 → 準備 git 環境 → 用 headless CLI 呼叫遷移
skill → 自己驗證建置與啟動 → 開 PR → fast-forward 併入整合分支並推送 → 更新進度與通知。

子命令：
  run                          主迴圈（無人看管）
  status                       印出佇列統計與 runner 狀態
  release <cp-id>              放行一個停下等人工檢視的斷點
  unblock <entry-id>           把 failed/blocked 的 entry 放回 pending（--runner 解除 crash hold）
  import-inventory <file.json> 把盤點結果轉成 queue.json（冪等、全量驗證）
  render-progress              重新產生 PROGRESS.md（或某個斷點的 PR 內文）
  diagnose <entry-id>          把一次失敗的全部證據打包成 diagnostics/<名稱>/（含 SUMMARY.md）

設計約束：
  * 只用 python3 標準函式庫，不安裝任何套件。
  * queue.json 是唯一狀態真值，只有本程式寫；每次寫入都在 flock 保護下讀-改-寫。
  * 不吞錯：所有失敗都會落進 runner.log.jsonl，並轉成明確的 entry 狀態或 runner 暫停狀態。
  * 失敗當下就凍結證據：CLI 的 stream-json 逐事件落檔、子行程全文落檔、失敗即產診斷包
    （diagnostics.py），通知第一行附診斷包路徑；runner 例外走 paused（去重、同簽名兩次即 hold）。
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback

# 同目錄的診斷模組（證據凍結、SUMMARY）與 stream-json 解析模組；runner.py 以腳本執行時 sys.path[0] 就是 helpers/
# 依賴方向：runner → diagnostics → stream_events
import diagnostics
import stream_events

# ================================================================ 常數

# 本 skill 的根目錄與各輔助檔位置（全部相對於本檔，不寫死絕對路徑）
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(SKILL_ROOT, "templates")
HELPERS_DIR = os.path.join(SKILL_ROOT, "helpers")
RESULT_SCHEMA_PATH = os.path.join(TEMPLATES_DIR, "result.schema.json")
HEADLESS_RULES_PATH = os.path.join(TEMPLATES_DIR, "headless-rules.txt")
NOTIFY_SCRIPT = os.path.join(HELPERS_DIR, "notify.sh")
QUOTA_SCRIPT = os.path.join(HELPERS_DIR, "quota-usage.py")
BOOT_SMOKE_SCRIPT = os.path.join(HELPERS_DIR, "boot-smoke.cjs")

# repo 內的相對位置
FRONTEND_R18_RELATIVE = os.path.join("frontend", "react_18")
BUILD_OUTPUT_RELATIVE = os.path.join("backend", "public", "build", "react18")
# vite build 產物本身不含的手足靜態資源根目錄（例如 i18n 的 locales/，見
# react_18/src/i18next.js 的 loadPath 打 /locales/lang/zh-TW/{{ns}}.json，
# 實體檔在 backend/public/locales/，與 BUILD_OUTPUT_RELATIVE 是手足目錄）；
# 供 run_smoke 額外掛給 boot-smoke.cjs 的 --static-root，避免 smoke 對這類
# 資源誤判為 404
PUBLIC_STATIC_RELATIVE = os.path.join("backend", "public")
LOCKFILE_RELATIVE = os.path.join(FRONTEND_R18_RELATIVE, "package-lock.json")

# 建置指令與它需要的堆積大小（大型前端專案預設堆積不夠）
BUILD_COMMAND = ["npm", "run", "build"]
BUILD_NODE_HEAP_MB = 4096
# 建置與啟動 smoke 的逾時秒數
BUILD_TIMEOUT_SECONDS = 3600
SMOKE_TIMEOUT_SECONDS = 600
NPM_CI_TIMEOUT_SECONDS = 3600
# 一般 git / gh 指令逾時秒數
GIT_TIMEOUT_SECONDS = 600

# 環境變數缺省值
DEFAULT_INTEGRATION_BRANCH = "feat/r18-migration"
DEFAULT_BASE_BRANCH = "master"
DEFAULT_CLAUDE_BIN = "claude"
DEFAULT_CLAUDE_MODEL = "sonnet"
DEFAULT_GH_BIN = "gh"
DEFAULT_MODULE_BUDGET_USD = 15
DEFAULT_MODULE_TIMEOUT_MIN = 150
DEFAULT_QUOTA_PREFLIGHT_FIVE_HOUR = 80
DEFAULT_QUOTA_PREFLIGHT_SEVEN_DAY = 95
DEFAULT_MAX_WAIT_HOURS = 168
DEFAULT_ENTRY_MAX_FILES = 12
DEFAULT_ENTRY_MAX_LINES = 4000
DEFAULT_CHECKPOINT_MAX_MODULES = 8
DEFAULT_CHECKPOINT_MAX_LINES = 3000
DEFAULT_CIRCUIT_BREAKER_N = 3
DEFAULT_DISK_MIN_GB = 20
DEFAULT_SESSIONS_RETENTION_DAYS = 14
DEFAULT_NOTIFY_PAUSE_REMIND_HOURS = 24
DEFAULT_NOTIFY_DAILY_DIGEST = "09:00"
DEFAULT_STATE_DIR_NAME = "r18-migration-state"

# entry.wave 合法值域（決策 24）：0（shared 層）到 5（班表家族 + residual 清理）
ENTRY_WAVE_MIN = 0
ENTRY_WAVE_MAX = 5

# entry.type 合法值域（1.0.4 新增值域檢查）：缺省視為 page，不報錯
ENTRY_TYPE_VALUES = ("page", "shared")

# entry.route.switch 唯一合法值（route-and-flag.md §1.4 的靜態清單切換模式）；缺省（None）代表不使用
ROUTE_SWITCH_STATIC_LIST = "static_list"

# npm ci 失敗時，detail 只保留合併後 stdout+stderr 的最後幾行（避免整段輸出灌爆通知/記錄）
NPM_FAILURE_TAIL_LINES = 20

# 失敗後的額度判準（決策 6）：超過這兩個門檻才認定是額度問題
QUOTA_FAIL_FIVE_HOUR = 95
QUOTA_FAIL_SEVEN_DAY = 98
# 額度 API 查不到時的固定等待（分鐘）
QUOTA_API_UNAVAILABLE_WAIT_MIN = 60
# 等待恢復後再多等的隨機抖動範圍（秒），避免多台機器同時醒來
QUOTA_JITTER_MIN_SECONDS = 60
QUOTA_JITTER_MAX_SECONDS = 180
# 等待期間的心跳與輪詢間隔（秒）
HEARTBEAT_SECONDS = 600
HARD_CHECKPOINT_POLL_SECONDS = 600
STALLED_RECHECK_SECONDS = 1800
# 逾時後先送 TERM，再等這麼久才送 KILL
TERM_GRACE_SECONDS = 30
# process group 已經沒有可以送訊號的對象（已 KILL、或只剩待收屍的行程）之後，最後一次收屍等待的上限（秒）。
# 正常情況 pipe 在那一刻就已關閉、立刻返回；等不到代表有行程自行脫離了 group 還握著 pipe，
# 訊號送不到它——任何一個收尾步驟都不可以沒有上限，超過就以 LeftoverProcessError 回報
REAP_LIMIT_SECONDS = 10
# killpg 回 EPERM 時的重試：macOS 對「group 裡只剩待收屍行程」回的是 EPERM 而不是 ESRCH，
# 主行程收屍後其餘待收屍的子孫要等系統收走才會消失，所以隔一小段時間再試、最多這麼多次；
# 試完仍是 EPERM 才認定 group 裡真的有送不了訊號的活行程
EPERM_RETRY_COUNT = 5
EPERM_RETRY_INTERVAL_SECONDS = 0.2
# 等 process group 清空時，兩次 signal 0 檢查之間的間隔（秒）
GROUP_POLL_INTERVAL_SECONDS = 0.2
# gh pr create 成功時印在 stdout 的 PR 連結：http(s)://<host>/…/pull/<編號>。
# 只認這個形狀——gh 以退出碼 0 結束時也可能印登入、更新提示之類的網址，那些不是 PR
PR_URL_RE = re.compile(r"^https?://[^/\s]+(?:/\S*)?/pull/\d+\S*$")
# 單一 entry 最多嘗試次數，達到即 failed
MAX_ATTEMPTS = 3
# 這幾種判讀結果要在寫回 queue、發通知之前先把證據凍結成診斷包（額度類不凍結：不是錯誤）
FREEZE_OUTCOME_KINDS = ("timeout", "error", "blocked", "hook_denied", "auth_expired")
# 文字特徵判讀（額度／未登入樣式）時，assistant 文字與 stderr 各只看末尾這麼多字元
STREAM_TEXT_TAIL_CHARS = 4000
# runner 未預期例外的暫停原因代號（enter_paused 的 reason、unblock --runner 解除的對象）
CRASH_REASON = "runner_crashed"
# 模組開工前發現本機整合分支領先遠端的暫停原因代號：上一輪的發佈段沒走完（合併了但沒推成、
# 退不回去、或人只跑了 unblock --runner 沒把本機對齊），cmd_run 對它第一次就鎖定
LOCAL_AHEAD_REASON = "integration_local_ahead"
# unblock --integration-tip 會解除的暫停原因（都是「整合分支狀態要人工確認」那一類）；
# unblock --runner 看到這些原因還在時要提醒對方也要跑
INTEGRATION_PAUSE_REASONS = ("integration_diverged", "master_conflict", "integration_dirty", LOCAL_AHEAD_REASON)
# merge_to_integration 的這些結果代表本機整合分支曾停在非預期 commit 上（有別的東西在改 repo），
# publish_verified_entry 對它們鎖定而不是一般暫停
HOLD_MERGE_RESULTS = ("integration_mismatch", "integration_unrecovered")
# 整合分支推送失敗的暫停簽名：enter_paused 對同簽名連續第二次就鎖定——推送失敗退回本機之後是可重試的，
# 但「持續推不上去」（分支保護、憑證過期、遠端 hook）沒有這個簽名就會每輪重跑完整模組而且不再通知
PUSH_FAILED_SIGNATURE = "integration_push_failed"
# 工作樹髒污／未追蹤檔清單放進 detail 時最多列幾行，其餘只給總數（通知會截尾，前幾行比尾端有用）
DIRTY_LIST_PREVIEW_LINES = 5

# 退出碼
EXIT_OK = 0
EXIT_LOCKED = 1
EXIT_PREFLIGHT = 2
EXIT_PAUSED = 3
EXIT_USAGE = 64

# 通知子行程（notify.sh）的上限秒數：它裡面 curl 逾時 10 秒；這個值要算進 launchd ExitTimeOut 的最壞收尾
# （收乾淨 process group 約 50 秒＋鎖定落盤後的那一則通知），原本 120 秒比 ExitTimeOut 90 還長，等於通知可能被 SIGKILL 掉
NOTIFY_TIMEOUT_SECONDS = 30

# 呼叫 CLI 時收回的破壞性工具（決策 5、20）
DISALLOWED_TOOLS = [
    "Bash(git reset:*)",
    "Bash(git restore:*)",
    "Bash(git stash:*)",
    "Bash(git clean:*)",
    "Bash(git checkout:*)",
    "Bash(git switch:*)",
    "Bash(git push:*)",
    "Bash(git rebase:*)",
    "Bash(git merge:*)",
    "Bash(git branch -D:*)",
    "Bash(git branch -d:*)",
    "Bash(git commit --amend:*)",
    "Bash(git cherry-pick:*)",
    "Bash(git worktree:*)",
    "Bash(gh pr merge:*)",
    "Bash(gh pr close:*)",
    "Bash(rm -rf:*)",
    "Read(**/.npmrc)",
    "Read(**/local-test/**)",
    "Read(**/.env*)",
    "Read(**/applicationConf*.json)",
]

# CLI 旗標名稱：pre-flight 要驗的清單與 build_claude_command 組指令時用的清單
# 曾經各自寫一份字面字串、實際組指令用到的旗標比 pre-flight 驗的還多（R7），
# 改成兩處都讀同一份常數，不再各自維護一份清單
FLAG_MODEL = "--model"
FLAG_OUTPUT_FORMAT = "--output-format"
FLAG_JSON_SCHEMA = "--json-schema"
FLAG_PERMISSION_MODE = "--permission-mode"
FLAG_PERMISSION_PROMPTS = "--permission-prompts"
FLAG_MAX_BUDGET_USD = "--max-budget-usd"
FLAG_DISALLOWED_TOOLS = "--disallowedTools"
FLAG_APPEND_SYSTEM_PROMPT = "--append-system-prompt"
# stream-json 在 -p 模式下要配 --verbose 才會逐事件輸出（2.1.275 實測）
FLAG_VERBOSE = "--verbose"
# CLI 輸出格式：一行一事件的 stream-json（逾時被殺時檔案仍保留到那一刻的事件；json 格式只在結束時輸出、被殺＝空）
OUTPUT_FORMAT_STREAM_JSON = "stream-json"

# pre-flight 要確認 CLI 支援的旗標（= build_claude_command 實際會用到的全部旗標）
REQUIRED_CLI_FLAGS = [
    FLAG_MODEL,
    FLAG_OUTPUT_FORMAT,
    FLAG_JSON_SCHEMA,
    FLAG_PERMISSION_MODE,
    FLAG_PERMISSION_PROMPTS,
    FLAG_MAX_BUDGET_USD,
    FLAG_DISALLOWED_TOOLS,
    FLAG_APPEND_SYSTEM_PROMPT,
    FLAG_VERBOSE,
]

# 判讀用的字串樣式
QUOTA_TEXT_RE = re.compile(r"hit your limit|usage limit|rate.?limit|resets at|429", re.IGNORECASE)
AUTH_TEXT_RE = re.compile(r"not logged in", re.IGNORECASE)
HOOK_DENY_RE = re.compile(r"\bdeny\b|permission denied|pending-review", re.IGNORECASE)
STATUS_FALLBACK_RE = re.compile(r"^STATUS:\s*([a-z_]+)\s*$", re.MULTILINE)
# 合併前掃描 diff 用的憑證樣式（決策 20）
SECRET_RE = re.compile(
    r"ghp_|ghs_|github_pat_|AKIA|-----BEGIN|password\s*[:=]|_token\s*[:=]"
)
# 憑證樣式分類（供 log/通知記類別名用；SECRET_RE 本身只判斷「有沒有命中」）。
# 命中内容本身可能就是憑證值，不能寫進 log/queue（見 LOG-SAFETY），所以只留類別名。
SECRET_PATTERN_LABELS = [
    ("github-token", re.compile(r"ghp_|ghs_|github_pat_")),
    ("aws-access-key", re.compile(r"AKIA")),
    ("private-key", re.compile(r"-----BEGIN")),
    ("password-literal", re.compile(r"password\s*[:=]", re.IGNORECASE)),
    ("token-literal", re.compile(r"_token\s*[:=]", re.IGNORECASE)),
]
# unified diff 的 hunk 標頭，例如 `@@ -12,3 +15,4 @@`；用來換算新增行在新檔裡的實際行號
DIFF_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# entry 執行期欄位的初始值（import-inventory 只在 entry 不存在時寫入）
RUNTIME_FIELD_DEFAULTS = {
    "status": "pending",
    "blocked_reason": None,
    "attempts": 0,
    "last_session_id": None,
    "last_commit": None,
    "last_error": None,
    "pr_url": None,
    "pr_failed": False,
    "r15_hashes": {},
    "checkpoint_id": None,
    "started_at": None,
    "finished_at": None,
    "cost_usd_total": 0,
    # 最近一次失敗凍結出來的診斷包（相對狀態目錄的路徑，例如 diagnostics/<entry>-1-<ts>）
    "last_diagnostics": None,
}

# checkpoint 執行期欄位初始值
CHECKPOINT_FIELD_DEFAULTS = {
    "status": "pending",
    "branch": None,
    "pr_url": None,
    "opened_at": None,
    "last_remind_at": None,
}


# ================================================================ 小工具


def to_int(raw, default):
    """把環境變數字串轉成整數；空值或格式錯誤時退回預設值。"""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def now_iso():
    """回傳目前時間的 UTC ISO 字串（秒精度）。"""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(text):
    """把 ISO 時間字串轉成帶時區的 datetime；解析不出來時回 None。"""
    if not text:
        return None
    try:
        value = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value


def jitter_seconds():
    """回傳額度恢復後要多等的秒數（以行程 pid 與時間決定，不需額外套件）。"""
    span = QUOTA_JITTER_MAX_SECONDS - QUOTA_JITTER_MIN_SECONDS
    return QUOTA_JITTER_MIN_SECONDS + (int(time.time()) + os.getpid()) % (span + 1)


def file_sha1(path):
    """計算單一檔案內容的 sha1；檔案不存在回 None，其他讀取失敗（權限、I/O 錯誤等）一律拋出例外。

    「檔案不存在」是合法狀態，但「存在卻讀不到」代表真的出了問題，跟「不存在」與
    「內容沒變」是三件不同的事，不能全部折疊成同一個 None——例如 lockfile_hash 若把
    讀取失敗也當成 None，`install_deps_if_lockfile_changed` 會把它跟「沒變」用同一個
    分支處理，靜默跳過本來必要的 npm ci。允許「讀不到也視為沒差別」的呼叫端（純診斷
    ／報表用途）請改用 file_sha1_or_none，不要回頭放寬這裡的例外。
    """
    try:
        with open(path, "rb") as handle:
            return hashlib.sha1(handle.read()).hexdigest()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeError("讀取 %s 計算 hash 失敗: %s" % (path, exc))


def file_sha1_or_none(path):
    """file_sha1 的寬容版本：任何讀取失敗都回 None，供純診斷／報表用途（不影響任何決策分支）。"""
    try:
        return file_sha1(path)
    except RuntimeError:
        return None


def tail_lines(text, n):
    """回傳文字最後 n 行接成的字串；空字串輸入回空字串。"""
    if not text:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def preview_lines(text, n):
    """把多行輸出縮成「前 n 行（逗號接起）＋總行數」；空白行不算；空輸入回空字串。

    給 git status／ls-files 這類清單用：通知會從尾端截斷，尾端截斷的清單會把前面的
    檔名丟掉、留下沒用的後半段；改成固定列前幾個、再標總數，被截到也還看得出規模。

    @param text 多行文字
    @param n 最多列幾行
    @return 摘要字串；行數超過 n 時形如「a, b, c …（共 7 行）」
    """
    # STEP 01: 去掉空白行，列前 n 行
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    shown = ", ".join(lines[:n])
    # STEP 02: 超過就補總數
    if len(lines) > n:
        return "%s …（共 %d 行）" % (shown, len(lines))
    return shown


# ================================================================ 設定載入


def load_config():
    """從環境變數組出設定 dict。

    這裡是本程式唯一讀取環境變數的地方；每個變數都用字面名稱呼叫，方便用 grep 稽核。
    """
    # STEP 01: 目標 repo 與分支
    repo_dir_raw = os.environ.get("REPO_DIR", "").strip()
    repo_dir = os.path.abspath(os.path.expanduser(repo_dir_raw)) if repo_dir_raw else ""
    integration_branch = os.environ.get("INTEGRATION_BRANCH", "").strip() or DEFAULT_INTEGRATION_BRANCH
    base_branch = os.environ.get("BASE_BRANCH", "").strip() or DEFAULT_BASE_BRANCH
    branch_user = os.environ.get("BRANCH_USER", "").strip()

    # STEP 02: 狀態目錄（預設放在家目錄底下，以 repo 目錄名分隔）
    state_dir_raw = os.environ.get("MIGRATION_STATE_DIR", "").strip()
    if state_dir_raw:
        state_dir = os.path.abspath(os.path.expanduser(state_dir_raw))
    else:
        repo_name = os.path.basename(repo_dir) if repo_dir else "default"
        state_dir = os.path.join(os.path.expanduser("~"), DEFAULT_STATE_DIR_NAME, repo_name)

    # STEP 03: CLI 與外部指令
    claude_bin = os.environ.get("CLAUDE_BIN", "").strip() or DEFAULT_CLAUDE_BIN
    claude_model = os.environ.get("CLAUDE_MODEL", "").strip() or DEFAULT_CLAUDE_MODEL
    claude_config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    gh_bin = os.environ.get("GH_BIN", "").strip() or DEFAULT_GH_BIN
    has_oauth_token = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip())

    # STEP 04: 額度、預算、上限
    config = {
        "repo_dir": repo_dir,
        "integration_branch": integration_branch,
        "base_branch": base_branch,
        "branch_user": branch_user,
        "state_dir": state_dir,
        "claude_bin": claude_bin,
        "claude_model": claude_model,
        "claude_config_dir": claude_config_dir,
        "gh_bin": gh_bin,
        "has_oauth_token": has_oauth_token,
        "module_budget_usd": to_int(os.environ.get("MODULE_BUDGET_USD", ""), DEFAULT_MODULE_BUDGET_USD),
        "module_timeout_min": to_int(os.environ.get("MODULE_TIMEOUT_MIN", ""), DEFAULT_MODULE_TIMEOUT_MIN),
        "quota_preflight_five_hour": to_int(
            os.environ.get("QUOTA_PREFLIGHT_FIVE_HOUR", ""), DEFAULT_QUOTA_PREFLIGHT_FIVE_HOUR
        ),
        "quota_preflight_seven_day": to_int(
            os.environ.get("QUOTA_PREFLIGHT_SEVEN_DAY", ""), DEFAULT_QUOTA_PREFLIGHT_SEVEN_DAY
        ),
        "max_wait_hours": to_int(os.environ.get("MAX_WAIT_HOURS", ""), DEFAULT_MAX_WAIT_HOURS),
        "entry_max_files": to_int(os.environ.get("ENTRY_MAX_FILES", ""), DEFAULT_ENTRY_MAX_FILES),
        "entry_max_lines": to_int(os.environ.get("ENTRY_MAX_LINES", ""), DEFAULT_ENTRY_MAX_LINES),
        "checkpoint_max_modules": to_int(
            os.environ.get("CHECKPOINT_MAX_MODULES", ""), DEFAULT_CHECKPOINT_MAX_MODULES
        ),
        "checkpoint_max_lines": to_int(
            os.environ.get("CHECKPOINT_MAX_LINES", ""), DEFAULT_CHECKPOINT_MAX_LINES
        ),
        "circuit_breaker_n": to_int(os.environ.get("CIRCUIT_BREAKER_N", ""), DEFAULT_CIRCUIT_BREAKER_N),
        "disk_min_gb": to_int(os.environ.get("DISK_MIN_GB", ""), DEFAULT_DISK_MIN_GB),
        "sessions_retention_days": to_int(
            os.environ.get("SESSIONS_RETENTION_DAYS", ""), DEFAULT_SESSIONS_RETENTION_DAYS
        ),
        "notify_channel": os.environ.get("NOTIFY_CHANNEL", "").strip() or "line",
        "notify_pause_remind_hours": to_int(
            os.environ.get("NOTIFY_PAUSE_REMIND_HOURS", ""), DEFAULT_NOTIFY_PAUSE_REMIND_HOURS
        ),
        "notify_daily_digest": os.environ.get("NOTIFY_DAILY_DIGEST", "").strip() or DEFAULT_NOTIFY_DAILY_DIGEST,
        # 以下兩個只在測試 stub 環境用，正式執行絕不設定
        "skip_build": os.environ.get("RUNNER_SKIP_BUILD", "").strip() == "1",
        "skip_smoke": os.environ.get("RUNNER_SKIP_SMOKE", "").strip() == "1",
    }
    return config


def require_config(config, names):
    """檢查必填設定；缺項時印出清單並回 False。"""
    # STEP 01: 逐項檢查，缺的一次列完再回報
    missing = [name for name in names if not config.get(name)]
    if not missing:
        return True
    label = {
        "repo_dir": "REPO_DIR",
        "branch_user": "BRANCH_USER",
        "has_oauth_token": "CLAUDE_CODE_OAUTH_TOKEN",
    }
    print("錯誤：缺少必填環境變數 " + ", ".join(label.get(name, name) for name in missing), file=sys.stderr)
    print("請確認已載入 env 檔（範本見 templates/r15-r18-migrate.env.example）", file=sys.stderr)
    return False


# ================================================================ 狀態檔 I/O


def state_path(config, name):
    """組出狀態目錄下某個檔案的完整路徑。"""
    return os.path.join(config["state_dir"], name)


def ensure_state_dir(config):
    """確保狀態目錄與其子目錄存在。"""
    # STEP 01: 主目錄與四個子目錄一次建好（diagnostics/ 與 crashes/ 不受 sessions 保留期清理）
    for path in [
        config["state_dir"],
        os.path.join(config["state_dir"], "sessions"),
        os.path.join(config["state_dir"], "diff-tests"),
        os.path.join(config["state_dir"], diagnostics.DIAGNOSTICS_DIR_NAME),
        os.path.join(config["state_dir"], diagnostics.CRASHES_DIR_NAME),
    ]:
        os.makedirs(path, exist_ok=True)


def log_event(config, entry_id, event, **fields):
    """把一筆事件追加到 runner.log.jsonl。

    寫入失敗只印到 stderr，不讓紀錄失敗中斷主流程（但也不靜默）。
    """
    # STEP 01: 組出固定欄位，再併入呼叫端給的補充欄位
    record = {
        "ts": now_iso(),
        "entry": entry_id,
        "event": event,
        "attempt": fields.pop("attempt", None),
        "duration_s": fields.pop("duration_s", None),
        "cost_usd": fields.pop("cost_usd", None),
        "session_id": fields.pop("session_id", None),
        "detail": fields.pop("detail", None),
    }
    if fields:
        record["detail"] = {"detail": record["detail"], "extra": fields}
    # STEP 02: 追加寫入；同時印一行到 stdout 方便看 launchd 的日誌
    line = json.dumps(record, ensure_ascii=False)
    print(line, flush=True)
    try:
        with open(state_path(config, "runner.log.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        print("警告：寫入 runner.log.jsonl 失敗: %s" % exc, file=sys.stderr)


def notify(config, event, title, body):
    """呼叫 notify.sh 送一則通知。

    通知本身失敗不影響主流程，但一定會留下紀錄。
    """
    # STEP 01: 沒有 notify.sh 就只留紀錄
    if not os.path.exists(NOTIFY_SCRIPT):
        log_event(config, None, "notify_skipped", detail="找不到 notify.sh")
        return
    # STEP 02: 把狀態目錄與 repo 目錄傳進子行程，讓 notify.sh 找得到狀態檔
    child_env = os.environ.copy()
    child_env["MIGRATION_STATE_DIR"] = config["state_dir"]
    if config["repo_dir"]:
        child_env["REPO_DIR"] = config["repo_dir"]
    try:
        result = subprocess.run(
            ["bash", NOTIFY_SCRIPT, event, title, body],
            capture_output=True,
            text=True,
            timeout=NOTIFY_TIMEOUT_SECONDS,
            env=child_env,
        )
        log_event(config, None, "notify", detail={"event": event, "out": result.stdout.strip()})
    except (OSError, subprocess.SubprocessError) as exc:
        log_event(config, None, "notify_failed", detail="%s: %s" % (type(exc).__name__, exc))


# ================================================================ 診斷凍結


def with_diagnostics_line(body, bundle_relpath):
    """通知內文第一行放診斷包路徑（notify.sh 300 字元截斷時路徑一定還在）；沒有診斷包就原樣回傳。"""
    if not bundle_relpath:
        return body
    return "診斷: %s\n%s" % (bundle_relpath, body)


def freeze_entry_bundle(config, entry_id, attempt, reason, detail):
    """把 entry 某次呼叫的證據凍結成診斷包；回傳相對狀態目錄的路徑，失敗回 None。

    診斷本身不能讓主流程炸掉：任何例外只記一筆 diagnostics_failed 事件。
    queue 讀不到時仍以最小 entry（只有 id）產包——證據比 queue 快照重要。
    """
    # STEP 01: 取 entry 快照（讀不到就用最小形狀）
    entry = None
    try:
        entry = find_entry(load_queue(config), entry_id)
    except (OSError, ValueError):
        entry = None
    if entry is None:
        entry = {"id": entry_id}
    # STEP 02: 產包；失敗只留紀錄
    try:
        ensure_state_dir(config)
        bundle_dir = diagnostics.freeze_entry(
            config["state_dir"],
            entry,
            attempt,
            reason,
            detail or "",
            config.get("fingerprint") or {},
            SECRET_PATTERN_LABELS,
        )
    except Exception as exc:  # 診斷失敗不可中斷主流程，但一定留紀錄
        log_event(
            config,
            entry_id,
            "diagnostics_failed",
            attempt=attempt,
            detail={"scope": "entry", "reason": reason, "error": "%s: %s" % (type(exc).__name__, exc)},
        )
        return None
    relative = diagnostics.relpath_in(config["state_dir"], bundle_dir)
    log_event(config, entry_id, "diagnostics_frozen", attempt=attempt, detail={"scope": "entry", "reason": reason, "path": relative})
    return relative


def freeze_runner_bundle(config, reason, detail, trace_text=None):
    """把 runner 級事件（paused／crash）的證據凍結成診斷包；回傳相對路徑，失敗回 None。"""
    try:
        ensure_state_dir(config)
        bundle_dir = diagnostics.freeze_runner(
            config["state_dir"],
            reason,
            detail or "",
            config.get("fingerprint") or {},
            SECRET_PATTERN_LABELS,
            trace_text=trace_text,
        )
    except Exception as exc:  # 同 freeze_entry_bundle：不中斷、但留紀錄
        log_event(
            config,
            None,
            "diagnostics_failed",
            detail={"scope": "runner", "reason": reason, "error": "%s: %s" % (type(exc).__name__, exc)},
        )
        return None
    relative = diagnostics.relpath_in(config["state_dir"], bundle_dir)
    log_event(config, None, "diagnostics_frozen", detail={"scope": "runner", "reason": reason, "path": relative})
    return relative


def refresh_bundle_snapshot(config, entry_id, bundle_relpath):
    """apply_outcome 寫回 queue 之後，把最新的 entry 狀態覆寫進診斷包的 queue-entry.json。"""
    if not bundle_relpath:
        return
    try:
        entry = find_entry(load_queue(config), entry_id)
    except (OSError, ValueError):
        return
    if entry is not None:
        diagnostics.refresh_entry_snapshot(state_path(config, bundle_relpath), entry)


class ShutdownSignal(BaseException):
    """SIGTERM／SIGHUP／SIGINT 轉成的例外，見 install_shutdown_handlers()。"""


# 停止訊號延後區間的巢狀深度：大於 0 時 handler 只記下訊號、不拋例外。訊號 handler 拿不到
# 呼叫端的任何物件，只能靠模組層變數與 ShutdownDeferral 溝通；深度而非布林，區間才能巢狀
_SIGNAL_DEFER_DEPTH = 0
# 延後區間內收到的第一個訊號編號；None 表示區間內沒收到訊號。只記第一個：後面的訊號意圖相同
_PENDING_SIGNUM = None


def shutdown_signal_handler(signum, _frame):
    """停止訊號的 handler：不在延後區間就轉成 ShutdownSignal 拋出，在區間內只記下來。

    模組層函式而非閉包，測試才能不真的裝訊號、直接呼叫它驗證延後行為。

    @param signum 收到的訊號編號
    @param _frame 訊號當下的 frame（不用）
    @return None（區間內）
    @raises ShutdownSignal 不在延後區間時
    """
    global _PENDING_SIGNUM
    # STEP 01: 延後區間內只記第一個訊號
    if _SIGNAL_DEFER_DEPTH > 0:
        if _PENDING_SIGNUM is None:
            _PENDING_SIGNUM = signum
        return
    # STEP 02: 其餘時候立刻轉成例外，交給呼叫堆疊上既有的 except/finally 處理
    raise ShutdownSignal("收到訊號 %d" % signum)


class ShutdownDeferral(object):
    """關鍵區間：進入後停止訊號只記錄不拋，區間結束才以 ShutdownSignal 拋出。

    四個地方需要它。前兩個是「訊號一旦從這裡冒出來，就會留下活的 CLI 行程而 runner 照樣放鎖」，
    後兩個是「訊號一旦從這裡冒出來，鎖定（hold）就沒落盤而 runner 被當成正常停止、重啟後照跑」：
    (1) call_claude 從 Popen 返回到收尾保護的 try 生效之間——CPython 在 CALL 返回後、變數綁定前
        就會跑 signal handler（3.14 實測），例外會帶著一個沒人握住的子行程離開；Popen 內部
        fork/exec 之後的那段同理，它的 except 只關 fd、不殺子行程。
    (2) _terminate_process_group 整段——收尾最長約 50 秒，期間第二次 Ctrl-C／SIGTERM 會從收尾
        中途跳出，group 沒 KILL 也沒確認空，cmd_run 當正常停止回 EXIT_OK 並釋放 runner.lock。
    (3) handle_runner_crash 整段——收尾回報殘留行程之後，凍結診斷包、把鎖定（hold）寫進 queue 的
        這幾秒沒有保護的話，第二次訊號會從 cmd_run 的 except handler 裡冒出來，sibling 的
        except 接不到，finally 放鎖、hold 沒寫，launchd 照樣重啟。
    (4) enter_paused 整段——不經 crash 流程的鎖定（HEAD 不符、本機領先、殘留寫入者）同樣要保護：
        訊號落在「本機已退回」與「hold 寫進 queue」之間，外層當正常停止回 EXIT_OK，重啟後前置作業看不出
        原本的不符、entry 繼續跑。代價是每一次暫停（凍結證據＋通知，最長約 NOTIFY_TIMEOUT_SECONDS 秒）都是延後窗。
    不用 pthread_sigmask：mask 會被 fork 出來的 CLI 繼承，CLI 就收不到我們之後送的 SIGTERM。

    延後的訊號由**最外層**區間在結束時處理（內層結束只減深度，不論它怎麼離開）：
      最外層正常結束（end()／with 正常離開）→ 預設拋 ShutdownSignal。呼叫端要把結束點放在能
        處理它的位置（call_claude 放在收尾 try 裡面）。建構時給 raise_on_normal_exit=False 則
        印到 stderr 後丟棄——給「區間跑完 runner 本來就要退出」的地方用（crash 流程回 EXIT_PAUSED
        就結束了，再拋一次只會把退出碼換成 traceback）。
      最外層以例外離開 with → 原例外優先往外傳，延後的訊號印到 stderr 後丟棄：收尾例外
        （ProcessCleanupError）會讓 runner 走 crash 流程暫停並鎖定，「停下來」的意圖已經達成，
        用 ShutdownSignal 覆蓋它反而會把「有殘留行程、必須鎖定」變成一次正常停止。
    代價：區間內第二次 Ctrl-C 沒有反應，要立刻中止只能 kill -9（那會留下殘留行程）。
    """

    def __init__(self, raise_on_normal_exit=True):
        """尚未進入區間。

        @param raise_on_normal_exit 最外層正常離開時，延後的訊號要拋出（True）還是印 stderr 後丟棄（False）
        """
        # 是否已離開區間；end() 只做一次，with 正常離開時若已呼叫過 end() 就不再重複
        self.ended = False
        # 正常離開時的處置，見類別 docstring
        self.raise_on_normal_exit = raise_on_normal_exit

    def __enter__(self):
        """進入區間。"""
        # STEP 01: 深度加一，handler 從此只記錄
        global _SIGNAL_DEFER_DEPTH
        _SIGNAL_DEFER_DEPTH += 1
        return self

    def end(self, raise_pending=None):
        """離開區間；最外層區間結束且有延後的訊號時拋出（或丟棄）。

        @param raise_pending None（預設）照建構子的 raise_on_normal_exit；True 拋出；False 印到 stderr 後丟棄。
                             呼叫端只在「離開方式不是正常結束」時才需要明給 False（__exit__ 用）
        @return None
        @raises ShutdownSignal 區間內收到過停止訊號且最後決定是拋出
        """
        global _SIGNAL_DEFER_DEPTH, _PENDING_SIGNUM
        # STEP 01: 只離開一次
        if self.ended:
            return
        self.ended = True
        _SIGNAL_DEFER_DEPTH -= 1
        # STEP 02: 還在更外層的區間裡就先不處理，交給最外層
        if _SIGNAL_DEFER_DEPTH > 0 or _PENDING_SIGNUM is None:
            return
        signum, _PENDING_SIGNUM = _PENDING_SIGNUM, None
        # STEP 03: 拋出或丟棄；沒明給就照建構時的宣告。丟棄時把原因寫進 stderr，兩種原因分開講
        if raise_pending is None:
            reason = "區間結束後 runner 本來就會退出"
            raise_pending = self.raise_on_normal_exit
        else:
            reason = "區間以例外結束、原例外優先"
        if raise_pending:
            raise ShutdownSignal("收到訊號 %d（關鍵區間內延後）" % signum)
        print("警告：關鍵區間內收到訊號 %d，%s，訊號不再另外拋出" % (signum, reason), file=sys.stderr)

    def __exit__(self, exc_type, _exc, _tb):
        """離開 with：正常離開照建構子的 raise_on_normal_exit；以例外離開明給 False——最外層才真的丟棄，內層只減深度、訊號留給最外層依它自己的離開方式決定。"""
        # STEP 01: 例外離開明給 False；正常離開交給 end() 讀建構子宣告
        self.end(raise_pending=None if exc_type is None else False)
        return False


def install_shutdown_handlers():
    """把 SIGTERM／SIGHUP／SIGINT 轉成可被既有 try/except/finally 捕捉的例外。

    Python 對 SIGINT 有內建處理（轉成 KeyboardInterrupt 往外拋），但 SIGTERM／SIGHUP
    沒有——預設動作是作業系統直接終止行程，完全不執行任何 Python 層的 except／finally，
    包括 call_claude 裡對 Claude CLI process group 的收尾清理與 cmd_run 的 runner.lock
    釋放。launchd 正常停止服務、系統登出都會送 SIGTERM／SIGHUP，不是只有測試環境的
    Ctrl-C（SIGINT）才需要處理。繼承 BaseException 而非 Exception，才不會被
    cmd_run 主迴圈那個泛用的 `except Exception as exc: handle_runner_crash(...)`
    攔截後誤判成一般執行期錯誤。
    SIGINT 也接管：內建的 KeyboardInterrupt 不受 ShutdownDeferral 延後，連按兩次 Ctrl-C
    的第二次會從收尾中途跳出。cmd_run 本來就把 KeyboardInterrupt 與 ShutdownSignal 當同一件事。
    """
    # STEP 01: 三個訊號共用同一個 handler
    signal.signal(signal.SIGTERM, shutdown_signal_handler)
    signal.signal(signal.SIGHUP, shutdown_signal_handler)
    signal.signal(signal.SIGINT, shutdown_signal_handler)


class ProcessLock(object):
    """runner.lock：用 flock 確保同一個狀態目錄同時只有一個 run 迴圈。

    互斥性完全交給 flock：同一個 inode 上，核心保證同一時間只有一個行程能拿到 LOCK_EX。
    行程不論正常結束或被 SIGKILL／斷電，核心都會在該行程的檔案描述符全部關閉時自動釋放
    flock，所以不需要（也不能）像舊版那樣自行讀 pid 判斷持有者是否還活著再決定要不要
    接管——那個「先讀 pid、判斷已死、刪檔、重建」的過程本身就是 TOCTOU：兩個新 runner
    可能同時判定舊鎖已死，其中一個接管後，另一個才執行到 unlink，把剛建立的新鎖也刪掉，
    兩邊都以為自己是唯一持有者。
    """

    def __init__(self, path):
        """記住鎖檔路徑；acquire() 成功前 handle 為 None。"""
        self.path = path
        self.handle = None
        self.acquired = False

    def acquire(self):
        """嘗試取鎖；成功回 True，已被其他活著的行程持有回 False。"""
        # STEP 01: 開檔（不存在就建立）；fd 要活到 release() 才能關閉，flock 綁在 fd 的生命週期上
        handle = open(self.path, "a+")
        # STEP 02: 非阻塞方式嘗試 LOCK_EX；已被別的活行程持有會丟 BlockingIOError，直接回 False
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        # STEP 03: flock 一成功就記下持有狀態——cmd_run 的 except／finally 靠 acquired 判斷有沒有持鎖，
        # 下面寫診斷資訊的途中若被訊號打斷，acquired 必須已經是 True，release() 才會真的放鎖
        self.handle = handle
        self.acquired = True
        # STEP 04: 寫入診斷用的 pid/host/since；只供人工排查，不影響互斥語意
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "since": now_iso()}))
        handle.flush()
        os.fsync(handle.fileno())
        return True

    def release(self):
        """釋放鎖：解 flock、關閉 fd。刻意不 unlink 鎖檔——flock+unlink 併用時，若在
        LOCK_UN 與 unlink 之間有其他行程恰好用同一個 path 開檔並成功拿到鎖，
        本行程後續的 unlink 只會移除 path 對應這個新鎖的 inode，讓再下一個行程
        open(path) 時建到另一個全新的、沒有任何鎖狀態的 inode，等於重新引入
        TOCTOU。不刪檔案本身沒有正確性風險：下一次 acquire() 一樣重用同一個
        inode，flock 保證互斥。
        """
        if not self.acquired:
            return
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None
        self.acquired = False


def queue_file(config):
    """回傳 queue.json 的路徑。"""
    return state_path(config, "queue.json")


def load_queue(config):
    """唯讀載入 queue.json；檔案不存在或壞掉時丟出明確的例外訊息。"""
    path = queue_file(config)
    # STEP 01: 不存在就給可行動的錯誤訊息，不讓呼叫端看到 traceback
    if not os.path.exists(path):
        raise FileNotFoundError(
            "找不到 %s；請先執行 `python3 runner.py import-inventory <inventory.json>` 建立佇列" % path
        )
    # STEP 02: 解析失敗一律視為 queue_corrupt
    with open(path, "r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except ValueError as exc:
            raise ValueError("queue.json 解析失敗（queue_corrupt）: %s" % exc)


def atomic_write_json(path, payload):
    """把 payload 以 JSON 寫到 path：暫存檔 → fsync → os.replace → fsync 父目錄。

    保證的是兩件事：(1) 任何時刻中斷，path 上不是舊的完整內容就是新的完整內容，不會有
    半份 JSON；(2) 返回之前，檔案內容與 rename 產生的目錄項都已要求核心落盤——只 fsync
    暫存檔不夠，rename 改的是父目錄，目錄沒 fsync 的話斷電後可能退回舊檔。
    不保證的事：macOS 的 fsync 不穿透磁碟本身的寫入快取（那要 F_FULLFSYNC），
    所以這裡不宣稱對斷電有完整的持久性。

    @param path 目標檔案的完整路徑；暫存檔固定為 path + ".tmp"，與目標同目錄才能原子替換
    @param payload 可被 json.dump 序列化的物件
    @return None
    """
    # STEP 01: 完整內容先寫進暫存檔並落盤
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    # STEP 02: 原子替換
    os.replace(tmp_path, path)

    # STEP 03: rename 改的是父目錄的目錄項，父目錄也要落盤
    directory_fd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def mutate_queue(config, mutator):
    """在 sidecar flock 保護下讀-改-寫 queue.json，寫入採 tmp+os.replace 原子替換。

    mutator 收到整份 queue dict，就地修改；回傳值會被原樣傳回呼叫端。
    run 迴圈與 release / unblock / import-inventory 共用這把鎖，確保互斥。

    鎖與資料檔刻意分離（鎖檔是 queue.json.lock，不是 queue.json 本身）：queue.json
    是唯一狀態真值，若直接對它 truncate 後原地寫回，行程被終止、斷電或磁碟寫入失敗
    只要發生在 truncate 之後、寫完之前，就會留下半份或全空的 JSON，下次啟動只能判定
    queue_corrupt，所有 entry 執行狀態可能遺失——flock 只能防並行存取，防不了寫入
    半途中斷。改成 atomic_write_json 的「暫存檔 → 原子替換」才不會留下半份檔案
    （保證範圍見該函式的 docstring）；而 replace 會換掉 queue.json 的 inode，若鎖直接綁在它身上，flock 語意會被打斷（下一個開檔的
    行程會鎖到新 inode，跟前一個行程持有的舊 inode 鎖毫無關係），所以鎖必須放在
    一個永遠不被替換的獨立檔案上。
    """
    path = queue_file(config)
    lock_path = path + ".lock"
    # STEP 01: 鎖檔本身永不被替換，flock 才能持續有效
    with open(lock_path, "a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            # STEP 02: 鎖內重新讀最新內容（不可用呼叫前讀到的舊快照）
            queue = load_queue(config)
            # STEP 03: 交給呼叫端修改
            outcome = mutator(queue)
            # STEP 04: 原子寫回（仍在鎖內）
            atomic_write_json(path, queue)
            return outcome
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def write_queue_new(config, queue):
    """建立新的 queue.json（import-inventory 第一次執行時用）。"""
    # STEP 01: 與 mutate_queue 走同一條原子寫入路徑；不持鎖是沿用原行為——queue.json 還不存在時
    # runner 的 mutate_queue 會在 load_queue 就失敗（FileNotFoundError），不會成為另一個寫入者
    atomic_write_json(queue_file(config), queue)


def find_entry(queue, entry_id):
    """依 id 找 entry；找不到回 None。"""
    for entry in queue.get("modules", []):
        if entry.get("id") == entry_id:
            return entry
    return None


def find_checkpoint(queue, checkpoint_id):
    """依 id 找 checkpoint；找不到回 None。"""
    for checkpoint in queue.get("checkpoints", []):
        if checkpoint.get("id") == checkpoint_id:
            return checkpoint
    return None


def set_runner_state(config, state, reason=None, extra=None):
    """更新 queue.runner_state 的狀態與原因；extra 是要一併寫入的補充欄位（例如 crash_signature／hold）。"""

    def mutator(queue):
        """就地改寫 runner_state。"""
        runner_state = queue.setdefault("runner_state", {})
        runner_state["state"] = state
        runner_state["reason"] = reason
        runner_state["since"] = now_iso()
        runner_state["pid"] = os.getpid()
        runner_state["host"] = socket.gethostname()
        runner_state.setdefault("consecutive_failures", 0)
        for key, value in (extra or {}).items():
            runner_state[key] = value
        return runner_state

    return mutate_queue(config, mutator)


# ================================================================ git / 外部指令


def session_log_path(config, name):
    """回傳子行程全量輸出的落檔路徑：sessions/<entry>-<n>-<name>.log。

    不在模組脈絡（config 沒有 current_entry）時用 runner-<時間>-<name>.log。
    """
    entry_id = config.get("current_entry")
    if entry_id:
        filename = "%s-%s-%s.log" % (entry_id, config.get("current_attempt"), name)
    else:
        filename = "runner-%s-%s.log" % (diagnostics.compact_ts(), name)
    return os.path.join(config["state_dir"], "sessions", filename)


def log_ref(config, log_path):
    """detail 字尾用的指路片段：queue／通知只留輸出尾段，全文靠這個檔。"""
    return "（全文: %s）" % diagnostics.relpath_in(config["state_dir"], log_path)


def write_command_log(log_path, args, cwd, code, out, err):
    """把一次外部指令的完整 stdout＋stderr 落檔；寫入失敗只印警告，不影響呼叫端。"""
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("cmd: %s\ncwd: %s\nreturncode: %s\nts: %s\n" % (" ".join(args), cwd, code, now_iso()))
            handle.write("----- stdout -----\n%s\n----- stderr -----\n%s\n" % (out or "", err or ""))
    except OSError as exc:
        print("警告：寫入指令輸出 %s 失敗: %s" % (log_path, exc), file=sys.stderr)


def run_command(args, cwd=None, timeout=GIT_TIMEOUT_SECONDS, env=None, log_path=None):
    """執行一個外部指令，回傳 (returncode, stdout, stderr)。

    逾時或無法啟動都轉成非零 returncode 與可讀訊息，不丟例外。
    log_path 給定時把完整 stdout＋stderr 落檔——呼叫端回傳給 queue／通知的 detail
    只截尾段，全文靠這個檔（build 的錯誤堆疊、smoke 的逐筆 [ignored:*] 都在裡面）。
    """
    # STEP 01: 執行並攔截逾時／找不到執行檔兩種失敗
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
        )
        code, out, err = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, "", "指令逾時（%ss）: %s" % (timeout, " ".join(args))
    except OSError as exc:
        code, out, err = 127, "", "指令無法執行: %s (%s)" % (" ".join(args), exc)
    # STEP 02: 需要時把全文落檔
    if log_path:
        write_command_log(log_path, args, cwd, code, out, err)
    return code, out, err


def git(config, *args, **kwargs):
    """在 repo 目錄下執行 git，回傳 (returncode, stdout, stderr)；kwargs 只認 timeout 與 log_path。"""
    timeout = kwargs.pop("timeout", GIT_TIMEOUT_SECONDS)
    log_path = kwargs.pop("log_path", None)
    return run_command(["git"] + list(args), cwd=config["repo_dir"], timeout=timeout, log_path=log_path)


def git_out(config, *args):
    """執行 git 並回傳去空白的 stdout；失敗時回空字串。

    多數呼叫端本來就把「查到空結果」與「指令失敗」一視同仁地當「沒有」處理，這是
    可接受的簡化。極少數呼叫端會直接拿空字串推導業務結論（entry 沒有 commit、entry
    已完成寫回 done）——這幾處不可用這個寬容版本，改用 git_out_or_raise，見其說明。
    """
    code, out, _err = git(config, *args)
    if code != 0:
        return ""
    return out.strip()


def git_out_or_raise(config, *args):
    """執行 git 並回傳去空白的 stdout；git 指令本身失敗時拋出例外，不可與『合法空結果』混淆。

    `l1_verify` 用它判斷 entry 分支是否真的沒有 commit、`collect_closing_data` 用它取得
    要寫進 queue 的 commit hash——這兩處若把「git 指令失敗」誤判成「真的沒有」，會讓
    entry 被錯誤地打上永久狀態（誤標 no_commit、或以空 commit hash 標記 done）。
    寧可讓例外冒出去，交給外層 handle_runner_crash 暫停整個 runner，也不要帶著錯誤的
    空字串繼續往下寫。查到「有指令執行、但結果真的是空」的情況不受影響，仍正常回傳
    空字串——只有 returncode != 0 才會走到這裡的例外。
    """
    code, out, err = git(config, *args)
    if code != 0:
        raise RuntimeError("git %s 失敗: %s" % (" ".join(args), err.strip()[-200:]))
    return out.strip()


def working_tree_clean(config):
    """判斷工作樹是否乾淨（porcelain 無輸出）。"""
    code, out, _err = git(config, "status", "--porcelain")
    if code != 0:
        return False
    return out.strip() == ""


def merge_in_progress(config):
    """判斷是否有殘留的 MERGE_HEAD（上一次 merge 沒收乾淨）。"""
    git_dir = git_out(config, "rev-parse", "--git-dir")
    if not git_dir:
        return False
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(config["repo_dir"], git_dir)
    return os.path.exists(os.path.join(git_dir, "MERGE_HEAD"))


def disk_free_gb(path):
    """回傳指定路徑所在磁碟的剩餘空間（GB）。"""
    usage = shutil.disk_usage(path)
    return usage.free / (1024 ** 3)


def cleanup_sessions(config):
    """刪除超過保留天數的 sessions 檔。"""
    # STEP 01: 算出保留界線
    sessions_dir = os.path.join(config["state_dir"], "sessions")
    if not os.path.isdir(sessions_dir):
        return 0
    cutoff = time.time() - config["sessions_retention_days"] * 86400
    removed = 0
    # STEP 02: 逐檔比對修改時間，過期就刪
    for name in os.listdir(sessions_dir):
        full = os.path.join(sessions_dir, name)
        try:
            if os.path.isfile(full) and os.path.getmtime(full) < cutoff:
                os.unlink(full)
                removed += 1
        except OSError as exc:
            print("警告：清理 sessions 檔失敗 %s: %s" % (full, exc), file=sys.stderr)
    return removed


def lockfile_hash(config):
    """回傳前端 lockfile 的內容 hash；檔案不存在時回 None，讀取失敗時拋出例外（見 file_sha1）。

    這裡刻意用嚴格版的 file_sha1、不用 file_sha1_or_none：install_deps_if_lockfile_changed
    會把回傳值拿去跟上一輪的 hash 比對決定要不要重跑 npm ci，若讀取失敗被吞成 None
    又剛好跟上一輪的 None 相等，會被誤判成「沒變」而靜默跳過必要的依賴安裝。
    """
    return file_sha1(os.path.join(config["repo_dir"], LOCKFILE_RELATIVE))


# ================================================================ 額度


def quota_snapshot(config):
    """呼叫 quota-usage.py 取得目前額度。

    回傳 dict：available 為 False 代表查不到（呼叫端需視為「額度 API 不可用」）。
    """
    # STEP 01: 用同一個 python 直譯器跑輔助腳本
    code, out, err = run_command([sys.executable, QUOTA_SCRIPT], timeout=60)
    # STEP 02: 解析輸出；解析不了就當不可用（但要留下紀錄）
    try:
        data = json.loads(out.strip() or "{}")
    except ValueError:
        data = {}
    if not data:
        log_event(config, None, "quota_unavailable", detail={"code": code, "stderr": err.strip()[:200]})
        return {"available": False}
    return data


def quota_blocks_start(config, snapshot):
    """pre-flight 判斷：現在的額度是否高到該先等一等。

    回傳 (should_wait, reason, resets_at)。
    """
    # STEP 01: 查不到額度時不擋啟動（失敗後另有判讀路徑）
    if not snapshot.get("available"):
        return False, "", None
    five = snapshot.get("five_hour", {})
    seven = snapshot.get("seven_day", {})
    # STEP 02: 兩個視窗各自比對門檻
    if to_int(seven.get("utilization"), 0) >= config["quota_preflight_seven_day"]:
        return True, "seven_day %s%%" % seven.get("utilization"), seven.get("resets_at")
    if to_int(five.get("utilization"), 0) >= config["quota_preflight_five_hour"]:
        return True, "five_hour %s%%" % five.get("utilization"), five.get("resets_at")
    return False, "", None


def wait_until(config, resets_at, reason, long_wait):
    """等到指定的重置時間（加抖動），期間每隔一段時間留一筆心跳。

    回傳 True 表示等完了，False 表示超過 MAX_WAIT_HOURS 上限。
    """
    # STEP 01: 算出目標時間；沒有 resets_at 就退回固定等待
    target = parse_iso(resets_at)
    if target is None:
        target = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=QUOTA_API_UNAVAILABLE_WAIT_MIN
        )
    target = target + datetime.timedelta(seconds=jitter_seconds())
    limit = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=config["max_wait_hours"])
    if target > limit:
        notify(
            config,
            "quota_wait_long",
            "額度等待超過上限",
            "原因: %s\n預計恢復: %s\n上限: %s 小時" % (reason, resets_at, config["max_wait_hours"]),
        )
        return False

    # STEP 02: 發出等待通知（長等待才是 HIGH）
    event = "quota_wait_long" if long_wait else "quota_wait_started"
    notify(
        config,
        event,
        "額度等待中",
        "原因: %s\n預計恢復: %s" % (reason, target.isoformat()),
    )
    log_event(config, None, event, detail={"reason": reason, "until": target.isoformat()})
    set_runner_state(config, "waiting_quota", reason)

    # STEP 03: 分段睡眠，每段結束留一筆心跳
    while True:
        remaining = (target - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(HEARTBEAT_SECONDS, remaining))
        log_event(config, None, "heartbeat", detail={"waiting_for": reason, "remaining_s": int(remaining)})
    set_runner_state(config, "running")
    return True


# ================================================================ CLI 呼叫


def read_text_file(path):
    """讀取純文字檔；不存在時回 None。"""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def skill_version():
    """讀 SKILL.md frontmatter 的 version；讀不到回 None。"""
    text = read_text_file(os.path.join(SKILL_ROOT, "SKILL.md")) or ""
    match = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def environment_fingerprint(config):
    """組出環境指紋：哪一版 skill／runner／CLI／模型／node／repo 產生了這次的紀錄。

    每次 run 啟動算一次存進 config["fingerprint"]，寫進 runner_started 事件與每個診斷包；
    跨版本比對錯誤時才知道是哪版程式產生的。查不到的項目記 None，不擋流程。
    """
    # STEP 01: skill 與 runner 自身版本
    fingerprint = {
        "skill_version": skill_version(),
        "runner_sha1": (file_sha1_or_none(os.path.abspath(__file__)) or "")[:12] or None,
        "diagnostics_sha1": (file_sha1_or_none(os.path.abspath(diagnostics.__file__)) or "")[:12] or None,
        "model": config["claude_model"],
        "python": platform.python_version(),
        "host": socket.gethostname(),
        "generated_at": now_iso(),
    }
    # STEP 02: 外部工具版本
    code, out, _err = run_command([config["claude_bin"], "--version"], timeout=60)
    fingerprint["cli_version"] = out.strip() if code == 0 and out.strip() else None
    code, out, _err = run_command(["node", "--version"], timeout=30)
    fingerprint["node"] = out.strip() if code == 0 and out.strip() else None
    # STEP 03: repo 狀態
    if config["repo_dir"]:
        fingerprint["repo_head"] = git_out(config, "rev-parse", "HEAD") or None
        fingerprint["repo_branch"] = git_out(config, "branch", "--show-current") or None
    return fingerprint


def build_claude_command(config, entry, resume):
    """組出呼叫遷移 skill 的完整指令列。"""
    # STEP 01: 基本旗標（stream-json 逐事件輸出，配 --verbose；json 格式被殺時什麼都拿不到）
    prompt = "/r15-r18-migrate %s%s" % (entry["id"], " --resume" if resume else "")
    command = [
        config["claude_bin"],
        "-p",
        prompt,
        FLAG_MODEL,
        config["claude_model"],
        FLAG_OUTPUT_FORMAT,
        OUTPUT_FORMAT_STREAM_JSON,
        FLAG_VERBOSE,
    ]
    # STEP 02: 結構化輸出 schema（範本缺檔時只留警告，不偽裝成有掛 schema）
    schema_text = read_text_file(RESULT_SCHEMA_PATH)
    if schema_text:
        command += [FLAG_JSON_SCHEMA, schema_text]
    # STEP 03: 權限、預算與收回的工具
    command += [
        FLAG_PERMISSION_MODE,
        "auto",
        FLAG_PERMISSION_PROMPTS,
        "none",
        FLAG_MAX_BUDGET_USD,
        str(config["module_budget_usd"]),
        FLAG_DISALLOWED_TOOLS,
    ]
    command += DISALLOWED_TOOLS
    # STEP 04: 無人看管期間的附加規則
    rules_text = read_text_file(HEADLESS_RULES_PATH)
    if rules_text:
        command += [FLAG_APPEND_SYSTEM_PROMPT, rules_text]
    return command


def stream_output_path(config, entry_id, attempt):
    """回傳某次呼叫的 stream-json 落檔路徑（sessions/<entry>-<n>.stream.jsonl）。"""
    return os.path.join(
        config["state_dir"], "sessions", "%s-%s%s" % (entry_id, attempt, diagnostics.STREAM_SUFFIX)
    )


def _terminate_process_group(process, grace_seconds):
    """對整個 process group 依序送 TERM/KILL 並收屍。

    Claude CLI 執行期間會再啟動 Bash 等子行程；若只 terminate/kill 直接子行程，
    CLI 的孫行程可能在逾時、SIGTERM 或 runner 被中斷後繼續留著修改 repo，
    outer 隨後釋放 runner.lock 或被 launchd 重啟，就可能與殘留行程並行操作。
    這裡假設 process 是用 start_new_session=True 啟動的，其 pgid 等於 pid，
    os.killpg 才能一次訊號到它與所有繼承同一個 process group 的子孫行程。

    pgid 直接取 process.pid，不用 os.getpgid 事後查：CLI 主行程先退出、孫行程還握著
    stderr pipe 時，主行程是尚未被收屍的 zombie，macOS 的 getpgid 對它回 ESRCH
    （ProcessLookupError）。把那個錯誤解讀成「已自然結束」會漏掉還活著的孫行程，
    接著沒有上限的 communicate 會陪它一直等下去——runner 卡住、runner.lock 不放。
    主行程在被收屍之前 pid 不會被重用，group 只要還有成員 pgid 也不會被重用，所以直接用
    process.pid 是安全的。主行程收屍之後這個保證只剩後半：group 一旦全空，pgid 理論上可以
    被回收。收屍後還會對同一個 pgid 送訊號的只有 _signal_group 的 EPERM 重試與
    _wait_group_empty 的輪詢，兩者一看到 ESRCH（group 已空）就停手、總時間有上限，
    撞上回收的機率極低，但不是零。

    正常返回的條件有兩個，都驗過才返回：(1) group 已經沒有成員——對 pgid 送 signal 0 得到
    ESRCH；(2) CLI 的輸出 pipe 已關閉。只看 (2) 不夠：pipe 關閉只代表「握著 pipe 的行程都
    結束了」，同一個 group 內忽略 SIGTERM、又沒握 pipe 的行程會活下來（實測）。呼叫端拿到
    正常返回就會繼續動 repo、之後釋放 runner.lock，殘留行程若還在改檔案，就是兩個寫入者
    並行，所以驗不過一律拋 ProcessCleanupError 的子類，由 cmd_run 的 crash 流程暫停、
    鎖定並通知。
    這兩個條件看不到的東西：自行脫離 group（setsid）**而且**關掉或改向了 stdio 的行程，
    也就是標準的 daemon 化——它不在 group 裡、也不握 pipe，這個函式無從得知它存在。

    整段是 ShutdownDeferral 區間：收尾最長約 50 秒，期間再收到停止訊號不可以從中途跳出
    （group 沒 KILL、沒確認空，呼叫端卻會繼續放鎖）；訊號延後到收尾完成才拋。

    @param process 已用 start_new_session=True 啟動的 subprocess.Popen
    @param grace_seconds SIGTERM 後等待多久才升級 SIGKILL
    @return (stdout, stderr) communicate() 的殘餘輸出
    @raises UnsignalableGroupError group 裡有送不了訊號的活行程
    @raises LeftoverProcessError 期限內 pipe 沒關閉（有行程脫離 group 還握著它），或 SIGKILL 之後 group 仍有成員
    @raises ShutdownSignal 收尾期間收到停止訊號（收尾已完成才拋）
    """
    with ShutdownDeferral():
        return _terminate_process_group_uninterrupted(process, grace_seconds)


def _terminate_process_group_uninterrupted(process, grace_seconds):
    """_terminate_process_group 的本體；呼叫端負責把它包在 ShutdownDeferral 裡。

    @param process 已用 start_new_session=True 啟動的 subprocess.Popen
    @param grace_seconds SIGTERM 後等待多久才升級 SIGKILL
    @return (stdout, stderr) communicate() 的殘餘輸出
    @raises UnsignalableGroupError group 裡有送不了訊號的活行程
    @raises LeftoverProcessError 期限內 pipe 沒關閉，或 SIGKILL 之後 group 仍有成員
    """
    # STEP 01: pgid 就是主行程的 pid（start_new_session=True 保證），不事後查詢
    pgid = process.pid

    # STEP 02: 對整個 group 送 TERM；group 已空就只剩收屍
    if not _signal_group(process, pgid, signal.SIGTERM):
        return _reap_with_limit(process)

    # STEP 03: 給 grace_seconds 自行收尾。pipe 提早關閉時，剩下的寬限期留給 group 裡還沒結束的成員
    grace_deadline = time.time() + grace_seconds
    try:
        result = process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        result = None
    if result is not None and _wait_group_empty(process, pgid, grace_deadline - time.time()):
        return result

    # STEP 04: 寬限期過了 group 還有成員（或 pipe 還沒關）→ KILL，有上限的收屍，再確認 group 真的空了
    _signal_group(process, pgid, signal.SIGKILL)
    if result is None:
        result = _reap_with_limit(process)
    if not _wait_group_empty(process, pgid, REAP_LIMIT_SECONDS):
        raise LeftoverProcessError(
            "已對 CLI（pid %d）的 process group 送 SIGKILL，但 %d 秒後 group 仍有成員。"
            "請人工確認沒有殘留行程後再讓 runner 繼續" % (process.pid, REAP_LIMIT_SECONDS)
        )
    return result


class ProcessCleanupError(RuntimeError):
    """CLI 的子孫行程沒有確認收乾淨。

    這一類例外的共同點：可能還有行程在改 repo，runner 不可以自己恢復執行。call_claude 看到它
    不重複收尾、原樣往外傳；handle_runner_crash 看到它第一次就鎖定（hold），不等同簽名第二次。
    用專屬的型別而不是 PermissionError 之類的內建例外當標記，呼叫端才分得出「來自收尾流程」
    與「try 區塊裡別處剛好也拋了同型別的例外」。
    """


class LeftoverProcessError(ProcessCleanupError):
    """期限內收不乾淨：有行程脫離了 group 還握著 CLI 的輸出 pipe，或 SIGKILL 之後 group 仍有成員。"""


class UnsignalableGroupError(ProcessCleanupError):
    """group 裡有送不了訊號的活行程（killpg 在收屍並重試之後仍回 EPERM）。"""


def _wait_group_empty(process, pgid, limit_seconds):
    """輪詢到 process group 沒有成員為止，約等 limit_seconds。

    用 signal 0 問（只檢查、不真的送訊號），沿用 _signal_group 對 macOS EPERM 語意的處理。
    剛被 KILL 的成員在被收屍之前仍算成員（killpg 回 EPERM），所以期限內的
    UnsignalableGroupError 視為「還沒空」繼續等；到期仍是它才往外拋。
    期限只在每次探測之間檢查，而一次探測內部最多含 EPERM_RETRY_COUNT 次重試
    （各隔 EPERM_RETRY_INTERVAL_SECONDS），所以實際可能超過 limit_seconds 約一秒。

    @param process 這個 group 的主行程
    @param pgid process group id
    @param limit_seconds 大約等多久（秒）；小於等於 0 表示只問一次
    @return True 表示 group 已空；False 表示到期仍有可送訊號的成員
    @raises UnsignalableGroupError 到期時 group 裡剩下的是送不了訊號的行程
    """
    # STEP 01: 問到空為止；到期時依最後一次的結果決定回 False 還是往外拋
    deadline = time.time() + max(limit_seconds, 0)
    while True:
        pending_error = None
        try:
            if not _signal_group(process, pgid, 0):
                return True
        except UnsignalableGroupError as exc:
            pending_error = exc
        if time.time() >= deadline:
            if pending_error is not None:
                raise pending_error
            return False
        time.sleep(GROUP_POLL_INTERVAL_SECONDS)


def _signal_group(process, pgid, sig):
    """對 process group 送訊號，並分清楚「group 已空」與「有送不了訊號的活行程」。

    killpg 的兩種失敗在 macOS 上不能只看例外類別：ProcessLookupError 是 group 已不存在；
    PermissionError 則有兩種來源——group 裡只剩待收屍的行程（macOS 對這種情況回 EPERM
    而不是 ESRCH，實測），或者 group 裡真的有送不了訊號的活行程（例如以別的使用者身分
    執行）。前者等同已空，後者不是。分辨方式：把主行程收屍後重試，待收屍的子孫被系統收走
    之後 killpg 會變成 ESRCH；試滿次數仍是 EPERM，就是後者，以 UnsignalableGroupError 往外拋。

    @param process 這個 group 的主行程（用來收屍）
    @param pgid process group id
    @param sig 要送的訊號；0 表示只檢查 group 還有沒有成員
    @return True 表示訊號已送出（sig 為 0 時：group 還有成員）；False 表示 group 已經沒有成員
    @raises UnsignalableGroupError 重試後仍然送不了：group 裡有無法終止的活行程
    """
    # STEP 01: 直接送；成功或 group 已不存在都在這裡結束
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        pass

    # STEP 02: EPERM——先把主行程收屍，再隔一小段時間重試，等系統收走其餘待收屍的子孫
    process.poll()
    for _ in range(EPERM_RETRY_COUNT):
        try:
            os.killpg(pgid, sig)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            time.sleep(EPERM_RETRY_INTERVAL_SECONDS)

    # STEP 03: 試滿次數仍是 EPERM
    raise UnsignalableGroupError(
        "process group %d 裡有送不了訊號的行程（收屍後重試 %d 次仍回 EPERM），無法確認 CLI 的子孫行程已終止"
        % (pgid, EPERM_RETRY_COUNT)
    )


def _reap_with_limit(process):
    """process group 已無可送訊號的對象之後的最後收屍；REAP_LIMIT_SECONDS 內收不完就拋例外。

    正常情況所有 pipe 的寫入端都已隨行程結束而關閉，communicate 立刻返回。仍然等不到，
    代表有子孫行程自行脫離了 process group（自己 setsid）還握著 pipe——killpg 送不到它，
    它還活著、還可能在改 repo。這不是可以帶過的狀況：不能回一個看起來正常的結果讓呼叫端
    把這一輪當成一般逾時繼續跑。

    @param process 已對其 process group 送過訊號（或確認無對象可送）的 subprocess.Popen
    @return (stdout, stderr) communicate() 的殘餘輸出
    @raises LeftoverProcessError 期限內 pipe 沒有關閉
    """
    # STEP 01: 有上限的收屍
    try:
        return process.communicate(timeout=REAP_LIMIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass

    # STEP 02: 關掉自己這一端的 pipe、把主行程收屍（它已收過 KILL 或早已結束），然後回報
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    process.poll()
    raise LeftoverProcessError(
        "CLI（pid %d）的 process group 已收尾，但 %d 秒後仍有行程握著它的輸出 pipe：有子孫行程脫離了 group，"
        "runner 終止不了它，它可能還在修改 repo。請人工確認沒有殘留行程後再讓 runner 繼續"
        % (process.pid, REAP_LIMIT_SECONDS)
    )


def call_claude(config, entry, attempt, resume):
    """呼叫 CLI 執行一個 entry，帶 wall-clock watchdog。

    stdout（stream-json，一行一事件）直接寫進 sessions/<entry>-<n>.stream.jsonl，
    不進記憶體：逾時被 TERM／KILL 時檔案仍保留到那一刻為止的所有事件，這是事後
    定位「卡在哪一步」唯一的現場。stderr 量小，仍走 PIPE。

    回傳 dict：returncode / stream_path / stderr / timed_out / duration_s。
    """
    command = build_claude_command(config, entry, resume)
    child_env = os.environ.copy()
    if config["claude_config_dir"]:
        child_env["CLAUDE_CONFIG_DIR"] = config["claude_config_dir"]
    stream_path = stream_output_path(config, entry["id"], attempt)

    # STEP 01: 開 stream 落檔，再啟動子行程；stdin 直接關掉（避免等 stdin 的 3 秒警告）
    started = time.time()
    timed_out = False
    devnull = open(os.devnull, "rb")
    try:
        stream_handle = open(stream_path, "w", encoding="utf-8")
    except OSError as exc:
        devnull.close()
        return {
            "returncode": 127,
            "stream_path": stream_path,
            "stderr": "無法建立 stream 落檔 %s: %s" % (stream_path, exc),
            "timed_out": False,
            "duration_s": 0,
        }
    # 從 Popen 到 STEP 02 收尾保護的 try 生效之間，停止訊號延後：訊號在這段冒出來會帶著一個沒人
    # 握住的子行程離開（CPython 在 CALL 返回後、變數綁定前就跑 handler；Popen 內部 fork/exec
    # 之後的那段同理）。區間在兩個地方明確結束：Popen 失敗時（沒有子行程要收，延後的訊號直接拋，
    # 不能回一個「CLI 失敗」的結果讓 runner 繼續跑下一個）、STEP 02 的 try 裡面（延後的訊號在
    # 那裡拋，走 BaseException 分支收尾）。with 只是安全網：沒走到任一結束點的例外離開也要把
    # 區間關掉，否則深度永遠不歸零、之後所有停止訊號都被無聲吃掉
    with ShutdownDeferral() as deferral:
        try:
            process = subprocess.Popen(
                command,
                cwd=config["repo_dir"],
                stdin=devnull,
                stdout=stream_handle,
                stderr=subprocess.PIPE,
                text=True,
                env=child_env,
                start_new_session=True,  # CLI 衍生的子行程與它同屬一個新 process group，逾時/中斷才能一次收乾淨
            )
        except OSError as exc:
            devnull.close()
            stream_handle.close()
            deferral.end()
            return {
                "returncode": 127,
                "stream_path": stream_path,
                "stderr": "無法執行 CLI: %s" % exc,
                "timed_out": False,
                "duration_s": 0,
            }

        # STEP 02: 等待結果；逾時先 TERM 再 KILL 整個 process group（stdout 已在檔案裡，communicate 只收 stderr）
        # group_cleaned：逾時路徑的收尾在被呼叫之前就標記——收尾完成後若拋出延後的 ShutdownSignal，
        # 呼叫不會「返回」，事後才標會漏掉，BaseException 分支就會對已空的 group 再收一次
        group_cleaned = False
        try:
            try:
                deferral.end()
                _stdout, stderr = process.communicate(timeout=config["module_timeout_min"] * 60)
            except subprocess.TimeoutExpired:
                timed_out = True
                group_cleaned = True
                _stdout, stderr = _terminate_process_group(process, TERM_GRACE_SECONDS)
        except ProcessCleanupError:
            # 逾時後的收尾自己回報「收不乾淨」：已經收過一次了，不再重複，原樣往外拋，
            # 由 cmd_run 的 crash 流程暫停、鎖定並通知——不可以把這一輪當成一般逾時繼續跑。
            # 只接收尾流程專屬的型別：try 區塊裡別處拋的 OSError 家族仍要走下面的 BaseException 分支做收尾
            raise
        except BaseException:
            # ShutdownSignal／SystemExit 等任何中斷都要先把整個 process group 收乾淨，
            # 才能把例外往外拋；外層 cmd_run 的 finally 在呼叫堆疊回到它之前不會釋放 runner.lock，
            # 所以這裡完成清理即滿足「清理完才釋放鎖」。收尾若回報收不乾淨，那個例外會取代
            # 原本的中斷往外傳（原例外留在 __context__）：此時該讓人知道的是有殘留行程。
            # 收尾本身是 ShutdownDeferral 區間，期間再來的訊號延後到收尾完成才拋
            if not group_cleaned:
                _terminate_process_group(process, TERM_GRACE_SECONDS)
            raise
        finally:
            devnull.close()
            stream_handle.close()

    return {
        "returncode": process.returncode,
        "stream_path": stream_path,
        "stderr": stderr or "",
        "timed_out": timed_out,
        "duration_s": int(time.time() - started),
    }


def save_session_output(config, entry, attempt, call_result):
    """把這次呼叫的 meta 存進 sessions/<entry>-<n>.json，供事後追查。

    stream 本身已由 call_claude 直接落檔；這裡只存 returncode／逾時／耗時／stderr 尾端、
    stream 的相對路徑與事件統計，以及 result 事件全文（含 structured_output、cost、
    permission_denials、terminal_reason 等統計欄位）。回傳 meta 路徑。
    """
    # STEP 01: 檔名用 entry id 與嘗試次數，避免互相覆蓋
    path = os.path.join(config["state_dir"], "sessions", "%s-%s%s" % (entry["id"], attempt, diagnostics.META_SUFFIX))
    events, bad_lines, stream_error = stream_events.read_stream(call_result["stream_path"])
    payload = {
        "ts": now_iso(),
        "entry": entry["id"],
        "attempt": attempt,
        "returncode": call_result["returncode"],
        "timed_out": call_result["timed_out"],
        "duration_s": call_result["duration_s"],
        "stream_path": diagnostics.relpath_in(config["state_dir"], call_result["stream_path"]),
        "stream_events": len(events),
        "stream_bad_lines": bad_lines,
        "stream_error": stream_error,
        "stderr": call_result["stderr"][-STREAM_TEXT_TAIL_CHARS:],
        "result_event": stream_events.last_result_event(events),
    }
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        print("警告：寫入 session meta 失敗: %s" % exc, file=sys.stderr)
    return path


# ================================================================ 判讀


def parse_cli_payload(call_result):
    """解析 CLI 的 stream-json 落檔。

    回傳 (payload, structured, transcript)：payload 是最後一筆 result 事件（沒有就空 dict），
    structured 是它的 structured_output（沒有就退回掃 `STATUS:` 行；都沒有為 None），
    transcript 是 assistant 文字的末段（給文字特徵判讀用）。
    stream 解析與 diagnostics.py 共用同一份 stream_events.read_stream，避免兩份解析器分歧。
    """
    # STEP 01: 讀 stream，取 result 事件與 assistant 文字
    events, _bad_lines, _error = stream_events.read_stream(call_result["stream_path"])
    payload = stream_events.last_result_event(events) or {}
    transcript = stream_events.transcript_text(events, STREAM_TEXT_TAIL_CHARS)
    # STEP 02: 取結構化輸出；沒有就退回掃 STATUS: 行（先看 result 文字，再由後往前看 assistant 文字）
    structured = payload.get("structured_output")
    if isinstance(structured, dict):
        return payload, structured, transcript
    candidates = [payload.get("result") or ""]
    candidates += [text for _ts, text, _parent in reversed(stream_events.assistant_texts(events))]
    for text in candidates:
        match = STATUS_FALLBACK_RE.search(text or "")
        if match:
            return payload, {"status": match.group(1), "_fallback": True}, transcript
    return payload, None, transcript


def judge_outcome(config, call_result):
    """依既定順序判讀一次呼叫的結果。

    回傳 dict：kind 是下列之一
      timeout / auth_expired / quota / quota_api_unavailable / hook_denied /
      error / done / blocked / rate_limited
    每種結果都帶 session_id / cost / terminal_reason / num_turns / denials（統計用）。
    """
    payload, structured, transcript = parse_cli_payload(call_result)
    text = "\n".join(
        [str(payload.get("result", "")), transcript, call_result["stderr"][-STREAM_TEXT_TAIL_CHARS:]]
    )
    denials = payload.get("permission_denials") or []
    base = {
        "session_id": payload.get("session_id"),
        "cost": payload.get("total_cost_usd"),
        "terminal_reason": payload.get("terminal_reason"),
        "num_turns": payload.get("num_turns"),
        "denials": len(denials),
    }

    # STEP 01: 逾時／被殺一律視為暫時性失敗
    if call_result["timed_out"]:
        return dict(base, kind="timeout", detail="wall-clock 逾時")

    # STEP 02: 非零退出或 is_error → 依文字特徵分流
    if call_result["returncode"] != 0 or payload.get("is_error"):
        if AUTH_TEXT_RE.search(text):
            return dict(base, kind="auth_expired", detail="CLI 回報未登入")
        if QUOTA_TEXT_RE.search(text):
            snapshot = quota_snapshot(config)
            if not snapshot.get("available"):
                return dict(base, kind="quota_api_unavailable", detail="文字命中額度樣式但額度 API 不可用")
            five = to_int(snapshot.get("five_hour", {}).get("utilization"), 0)
            seven = to_int(snapshot.get("seven_day", {}).get("utilization"), 0)
            if five >= QUOTA_FAIL_FIVE_HOUR or seven >= QUOTA_FAIL_SEVEN_DAY:
                resets_at = (
                    snapshot.get("seven_day", {}).get("resets_at")
                    if seven >= QUOTA_FAIL_SEVEN_DAY
                    else snapshot.get("five_hour", {}).get("resets_at")
                )
                return dict(
                    base,
                    kind="quota",
                    detail="five_hour %s%% / seven_day %s%%" % (five, seven),
                    resets_at=resets_at,
                    long_wait=seven >= QUOTA_FAIL_SEVEN_DAY,
                )
            return dict(base, kind="error", detail="文字像額度問題但 API 顯示額度充足（five %s / seven %s）" % (five, seven))
        # STEP 02.01: 權限拒絕先看 result 事件的結構化欄位，regex 只當備援
        if denials:
            names = sorted(
                {str(item.get("tool_name") or item.get("tool") or "?") for item in denials if isinstance(item, dict)}
            )
            return dict(
                base,
                kind="hook_denied",
                detail="CLI 回報 %d 筆 permission_denials（%s）" % (len(denials), ", ".join(names[:3]) or "?"),
            )
        if HOOK_DENY_RE.search(text):
            return dict(base, kind="hook_denied", detail="呼叫被權限或外掛檢查擋下（文字特徵）")
        return dict(base, kind="error", detail=("退出碼 %s: " % call_result["returncode"]) + text.strip()[-300:])

    # STEP 03: 正常退出 → 看結構化輸出
    if not structured:
        return dict(base, kind="error", detail="退出碼 0 但沒有 structured_output，也找不到 STATUS: 行")
    status = structured.get("status")
    if status == "done":
        return dict(base, kind="done", structured=structured)
    if status == "blocked":
        return dict(base, kind="blocked", structured=structured, detail=structured.get("blocked_reason") or "needs_human")
    if status == "rate_limited":
        return dict(base, kind="rate_limited", structured=structured, detail="skill 內部回報額度不足")
    return dict(base, kind="error", structured=structured, detail="未知的 status: %s" % status)


# ================================================================ L1 驗證與合併


def run_build(config):
    """在前端專案跑一次建置。

    回傳 (ok, detail)。設定 RUNNER_SKIP_BUILD=1 時直接回傳 skipped（僅測試用）。
    """
    # STEP 01: 測試旗標
    if config["skip_build"]:
        return True, "skipped(RUNNER_SKIP_BUILD)"
    # STEP 02: 以加大堆積的方式跑建置；全文落檔，detail 只留尾段並指路
    build_env = os.environ.copy()
    build_env["NODE_OPTIONS"] = "--max-old-space-size=%d" % BUILD_NODE_HEAP_MB
    cwd = os.path.join(config["repo_dir"], FRONTEND_R18_RELATIVE)
    log_path = session_log_path(config, "build")
    code, out, err = run_command(
        BUILD_COMMAND, cwd=cwd, timeout=BUILD_TIMEOUT_SECONDS, env=build_env, log_path=log_path
    )
    if code != 0:
        return False, (err or out).strip()[-500:] + log_ref(config, log_path)
    return True, "build ok"


def run_smoke(config):
    """跑建置產物的啟動 smoke。

    回傳 (ok, detail)。設定 RUNNER_SKIP_SMOKE=1 時直接回傳 skipped（僅測試用）。
    """
    # STEP 01: 測試旗標
    if config["skip_smoke"]:
        return True, "skipped(RUNNER_SKIP_SMOKE)"
    # STEP 02: 呼叫 boot-smoke.cjs；退出碼 2（缺 playwright）也算失敗，不假裝通過。
    # 額外掛 --static-root 指向 backend/public，讓 vite 產物目錄外的手足靜態資源
    # （locales/ 等）能被找到，不會被 boot-smoke 誤判成缺資產的真 404
    smoke_env = os.environ.copy()
    smoke_env["REPO_DIR"] = config["repo_dir"]
    dist_dir = os.path.join(config["repo_dir"], BUILD_OUTPUT_RELATIVE)
    public_static_dir = os.path.join(config["repo_dir"], PUBLIC_STATIC_RELATIVE)
    log_path = session_log_path(config, "smoke")
    code, out, err = run_command(
        ["node", BOOT_SMOKE_SCRIPT, "--dist", dist_dir, "--static-root", public_static_dir],
        cwd=config["repo_dir"],
        timeout=SMOKE_TIMEOUT_SECONDS,
        env=smoke_env,
        log_path=log_path,
    )
    if code != 0:
        return False, ("退出碼 %s: " % code) + (out or err).strip()[-500:] + log_ref(config, log_path)
    return True, "smoke ok"


def classify_secret_pattern(line):
    """判斷命中的憑證樣式屬於哪個類別，只回傳類別名稱。

    絕不回傳命中內容本身——命中的那段文字可能就是憑證值，寫進 log/queue
    會違反 LOG-SAFETY（R5）。找不到對應分類（理論上不會發生，SECRET_RE 已先篩過一次）回 'unknown'。
    """
    for name, pattern in SECRET_PATTERN_LABELS:
        if pattern.search(line):
            return name
    return "unknown"


def scan_secrets(config, entry):
    """掃描分支相對整合分支的 diff 有沒有疑似憑證。

    回傳命中清單，每筆格式「檔名:行號 類別名」（例如 `src/x.ts:12 github-token`）；
    不含命中內容本身，避免憑證值被寫進 log/queue（R5）。空清單 = 乾淨。
    """
    # STEP 01: 取整段 diff（含檔名標頭）
    code, out, err = git(
        config, "diff", "%s..%s" % (config["integration_branch"], entry["branch"])
    )
    if code != 0:
        return ["diff 讀取失敗: %s" % err.strip()[-200:]]
    # STEP 02: 逐行掃描；靠 hunk 標頭換算新增行在新檔裡的實際行號，只看新增行
    hits = []
    current_file = ""
    new_line_no = 0
    for line in out.splitlines():
        if line.startswith("diff --git") or line.startswith("index ") or line.startswith("--- "):
            continue
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("+++"):
            continue
        hunk_match = DIFF_HUNK_HEADER_RE.match(line)
        if hunk_match:
            new_line_no = int(hunk_match.group(1))
            continue
        if line.startswith("+"):
            if SECRET_RE.search(line):
                hits.append("%s:%d %s" % (current_file, new_line_no, classify_secret_pattern(line)))
            new_line_no += 1
            continue
        if line.startswith("-") or line.startswith("\\"):
            # 刪除行不在新檔裡；"\ No newline at end of file" 標記也不算一行
            continue
        # 其餘（含 context 行）在新檔裡也佔一行，行號要跟著遞增
        new_line_no += 1
    return hits


def l1_verify(config, entry):
    """L1 判準 (2)–(5)：commit 存在 → build → smoke → 秘密掃描（不含合併）。

    回傳 (result, detail)，result 是 verified / build_unverified / secret_detected / no_commit。

    合併另外交給 merge_to_integration，且呼叫順序刻意是「先開 PR、再合併」：
    entry 分支要在還沒被 ff-merge 進整合分支之前開 PR，這時兩者才有真正的差異可以
    審查；ff-merge 一旦先做，entry 分支與整合分支 tip 相同，以整合分支為 base 的
    PR 會被 GitHub 判定沒有差異而必定失敗（每個成功 entry 都會固定落成 pr_failed）。
    """
    integration = config["integration_branch"]
    # STEP 01: (2) branch 必須真的有 commit——用嚴格版 git_out，區分「真的沒有」與
    # 「git 指令本身失敗」，避免把後者誤判成 no_commit
    log_out = git_out_or_raise(config, "log", "--oneline", "%s..%s" % (integration, entry["branch"]))
    if not log_out:
        return "no_commit", "分支相對整合分支沒有任何 commit"

    # STEP 02: (3) 自己跑建置，不採信報告
    ok, detail = run_build(config)
    if not ok:
        return "build_unverified", "build 失敗: %s" % detail
    build_detail = detail

    # STEP 03: (4) 啟動 smoke
    ok, detail = run_smoke(config)
    if not ok:
        return "build_unverified", "啟動 smoke 失敗: %s" % detail
    smoke_detail = detail

    # STEP 04: (5) 秘密掃描
    hits = scan_secrets(config, entry)
    if hits:
        return "secret_detected", "疑似憑證 %d 處: %s" % (len(hits), hits[0])

    log_event(
        config,
        entry["id"],
        "l1_checks_passed",
        detail={"build": build_detail, "smoke": smoke_detail, "commits": len(log_out.splitlines())},
    )
    return "verified", "L1 檢查通過，待開 PR 與合併"


def _restore_integration_branch(config, integration, head_before_merge, head_after_merge):
    """ff-merge 後 HEAD 不符時，把本機整合分支退回合併前；退不回去就照實回報。

    只在四個條件都成立時才 reset：HEAD 仍在整合分支上、已追蹤檔沒有未提交變更、reset 前
    再讀一次 HEAD 仍是合併後那個 commit、reset 成功（用 --keep，要覆寫的檔有本機修改就中止，
    補上 status 與 reset 之間的窗）。不一致的成因就是「還有別的東西在改
    repo」，所以前三個條件都不能假設：HEAD 可能已被切走（reset 會打到別人的分支）、工作樹
    可能留著別人的未提交變更（reset --hard 會無聲抹掉）、檢查到 reset 之間它可能又 commit
    了一次（reset 會抹掉那個 commit）。未追蹤檔不先擋、只列進說明給人看：reset --keep 對「退回會寫到同一路徑」的
    未追蹤檔會中止（回 unrecovered、鎖定），其餘不動。

    每一種退不回去的說明都帶合併前的 HEAD——診斷包不收 git 狀態，這段文字是人工退回時
    唯一能知道「該退到哪」的紀錄。

    兩個呼叫端：ff-merge 後 HEAD 不符（退回成功算 integration_mismatch，仍要鎖定）與推送失敗
    （退回成功算 integration_push_failed，第一次可重試、同簽名連續第二次鎖定——不退回的話本機
    領先遠端，下一輪前置作業會判成 integration_local_ahead 而鎖定，一次網路抖動就要人工介入）。結果值由呼叫端決定，這裡
    只回「退回了沒有」。

    @param config runner 設定
    @param integration 整合分支名稱
    @param head_before_merge 合併前的整合分支 HEAD（完整 sha）
    @param head_after_merge 合併後讀到的 HEAD（完整 sha；讀不到時是空字串，這時不 reset）
    @return (restored, note)：退回成功是 (True, 說明)；退不回去是 (False, 原因＋「請人工處理」)
    """
    # 每一種退不回去的說明都以這句開頭：合併前的 sha 是人工退回時唯一的依據，通知 300 字截尾也要看得到
    stuck = "本機整合分支停在非預期 commit（合併前是 %s），請人工處理" % head_before_merge[:12]
    # STEP 01: HEAD 還在整合分支上嗎
    code, out, err = git(config, "symbolic-ref", "--short", "HEAD")
    current_branch = out.strip() if code == 0 else ""
    if current_branch != integration:
        return (
            False,
            "%s；HEAD 已不在整合分支上（現在是 %s），未退回"
            % (stuck, current_branch or ("讀取失敗: %s" % err.strip()[-200:])),
        )
    # STEP 02: 已追蹤檔有沒有未提交變更（status 本身失敗與「有變更」分開講：前者不知道工作樹長什麼樣，一樣不 reset）
    code, out, err = git(config, "status", "--porcelain", "--untracked-files=no")
    if code != 0:
        return (
            False,
            "%s；git status 執行失敗（%s），無法確認工作樹、未退回" % (stuck, err.strip()[-200:] or "無錯誤輸出"),
        )
    if out.strip():
        return (
            False,
            "%s；工作樹有未提交的變更，未退回（退回會動到這些）: %s"
            % (stuck, preview_lines(out, DIRTY_LIST_PREVIEW_LINES)),
        )
    # 未追蹤檔只是附帶資訊、不擋退回；但「清單讀取失敗」與「沒有未追蹤檔」要分得出來
    code, out, err = git(config, "ls-files", "--others", "--exclude-standard")
    if code != 0:
        untracked_note = "（未追蹤檔清單讀取失敗: %s）" % err.strip()[-200:]
    elif out.strip():
        untracked_note = "（工作樹留有未追蹤檔: %s）" % preview_lines(out, DIRTY_LIST_PREVIEW_LINES)
    else:
        untracked_note = ""
    # STEP 03: reset 之前再確認 HEAD 沒有在上面兩個檢查期間又被動過；合併後就讀不到 HEAD 的也不 reset
    # （兩種分開講：前者要去追是誰動的，後者是 git 本身出了問題）
    if not head_after_merge:
        return False, "%s；合併後讀不到 HEAD，無法確認要退回的狀態、未退回" % stuck
    code, out, _err = git(config, "rev-parse", "HEAD")
    current_head = out.strip() if code == 0 else ""
    if current_head != head_after_merge:
        return (
            False,
            "%s；HEAD 在檢查期間又變了（合併後 %s → 現在 %s），未退回"
            % (stuck, head_after_merge, current_head or "讀取失敗"),
        )
    # STEP 04: reset。用 --keep 不用 --hard：上面 status 到這裡之間那個別的寫入者可能又改了已追蹤檔（這個函式
    # 正是在「可能有別的寫入者」時才被呼叫的），--hard 會無條件覆寫工作樹、把它的修改無聲抹掉；--keep 對
    # 「合併前後有差、而且有本機修改」的檔會整個中止，中止就是 unrecovered
    code, _out, err = git(config, "reset", "--keep", head_before_merge)
    if code != 0:
        # git 把關鍵的那一行（哪個檔 not uptodate／會被覆寫）印在最前面、fatal 那行在後面，取頭不取尾
        first_line = (err.strip().splitlines() or ["無錯誤輸出"])[0][:200]
        return (
            False,
            "%s；退回本機整合分支時中止（要寫到的檔在檢查之後又有本機修改或未追蹤檔，reset --keep 不覆寫）: %s" % (stuck, first_line),
        )
    return True, "本機整合分支已退回 %s%s" % (head_before_merge, untracked_note)


def merge_to_integration(config, entry, expected_tip):
    """L1 判準 (6)：切回整合分支做 fast-forward 合併（merge／push 全文落檔）。

    呼叫前應已完成 l1_verify（結果為 verified）並已呼叫 push_branch_and_open_pr——合併
    之後 entry 分支與整合分支 tip 相同，此時才開 PR 一定會失敗，見 l1_verify docstring。

    push 是這一段唯一不可逆的步驟，所以「合併後的 HEAD 是哪個 commit」要在 push 之前
    確認，而不是 push 之後再讀：之後才讀，讀取一失敗就是「遠端已前進、queue 沒記到」。
    ff-merge 成功後 HEAD 必然等於 entry 分支的 tip，呼叫端把事先取得的那個 commit 傳
    進來當 expected_tip，這裡驗證兩者一致才推送；不一致代表本機整合分支的狀態跟預期
    不同（collect 之後 entry 分支又多了 commit——還有別的東西在改 repo），寧可停下來。
    停下來之前把本機整合分支退回合併前的 commit：ff-merge 已經把它推到那個非預期的 commit
    上，留著不管的話本機領先遠端、下一次 --ff-only 同步是 no-op，後面的 entry 會從那個
    commit 切分支、最後把它推上去。退回成功回 integration_mismatch、退不回去回
    integration_unrecovered，兩種呼叫端都鎖定 runner（hold）而不是一般暫停：不一致的前提
    就是「有別的東西在改 repo」，一般暫停 launchd 幾分鐘後就重啟、把同一個 entry 放回 pending
    重試，多半再次不一致、同原因重複暫停不再通知，等於無上限地燒額度；退不回去的更不能重啟
    （module_preflight 現在對「本機領先」看得出來並鎖定，但那是第二道防線，第一道是這裡）。
    退不回去的情況見 _restore_integration_branch。推送失敗也走同一個退回：ff-merge 已經把本機推
    到 entry 的 commit，不退回的話本機領先遠端、下一輪前置作業會判成 integration_local_ahead 而
    鎖定；退回之後才是真的可重試（entry 分支的 commit 還在、PR 沿用）。

    @param config runner 設定
    @param entry queue 裡的 entry（用到 branch）
    @param expected_tip 事先取得的 entry 分支 commit（完整 sha）；推送成功後它就是整合分支的新 tip
    @return (result, detail)，result 是 done / integration_diverged（切換、讀取或 ff-merge 失敗，可重試）/ integration_push_failed（推送失敗且本機已退回，可重試；呼叫端連續第二次就鎖定）/ integration_mismatch（HEAD 不符、本機已退回）/ integration_unrecovered（HEAD 不符或推送失敗，而且本機整合分支停在非預期 commit 上，必須人工處理）
    """
    integration = config["integration_branch"]
    # STEP 01: 切回整合分支，記下合併前的 HEAD（mismatch 時退回用；讀不到就不合併）
    code, _out, err = git(config, "checkout", integration)
    if code != 0:
        return "integration_diverged", "切換到整合分支失敗: %s" % err.strip()[-200:]
    code, out, err = git(config, "rev-parse", "HEAD")
    if code != 0:
        return "integration_diverged", "讀取合併前的整合分支 HEAD 失敗: %s" % err.strip()[-200:]
    head_before_merge = out.strip()
    # STEP 02: fast-forward 合併
    log_path = session_log_path(config, "git-merge-ff")
    code, _out, err = git(config, "merge", "--ff-only", entry["branch"], log_path=log_path)
    if code != 0:
        return "integration_diverged", "ff-merge 失敗: %s%s" % (err.strip()[-200:], log_ref(config, log_path))
    # STEP 03: 推送之前確認 HEAD 就是預期的 commit（讀不到也算不一致，一樣不推）；不一致就退回合併前
    code, out, err = git(config, "rev-parse", "HEAD")
    head_after_merge = out.strip() if code == 0 else ""
    if not head_after_merge or head_after_merge != expected_tip:
        mismatch = "ff-merge 後的 HEAD（%s）不是預期的 entry commit（%s），未推送" % (
            head_after_merge or ("讀取失敗: %s" % err.strip()[-200:]),
            expected_tip,
        )
        restored, reset_note = _restore_integration_branch(config, integration, head_before_merge, head_after_merge)
        # 退不回去的說明（帶合併前 sha 與原因）排在不符敘述（兩個 40 字元 sha）之前：通知 300 字截尾也要看得到
        if restored:
            return "integration_mismatch", "%s；%s" % (mismatch, reset_note)
        return "integration_unrecovered", "%s；%s" % (reset_note, mismatch)
    # STEP 04: 推送（不可逆）。推不上去也要把本機退回合併前——留著的話本機領先遠端，下一輪前置作業
    # 會判成 integration_local_ahead 並鎖定，一次網路抖動就要人工介入；退回之後才是真的可重試：
    # entry 分支的 commit 還在、PR 沿用、下一輪再 ff-merge 再推。退不回去的一樣鎖定
    log_path = session_log_path(config, "git-push-integration")
    code, _out, err = git(config, "push", "origin", integration, log_path=log_path)
    if code != 0:
        push_error = "推送整合分支失敗: %s%s" % (err.strip()[-200:], log_ref(config, log_path))
        # STEP 04.01: 推送回報失敗不代表沒推上去（逾時、連線在回報前斷掉）：先問遠端。已經是預期的 commit 就是 done——
        # 退回的話本機退到合併前、遠端已前進、tip 沒記，下一輪 STEP 03 會判成「有別人動了整合分支」而且同原因不再通知。
        # 問不到遠端就什麼都不能斷定：不退回（遠端若收到了，退回等於本機落後）、也不說可重試（會重跑一次完整模組），
        # 回 unrecovered 讓呼叫端鎖定、人工對帳；本機留在合併後的 commit 當證據
        code, out, err = git(config, "ls-remote", "origin", "refs/heads/%s" % integration)
        if code != 0:
            return (
                "integration_unrecovered",
                "%s；而且無法確認遠端是否已收到（ls-remote 失敗: %s），本機未退回、停在 %s（合併前是 %s）。"
                "請人工看 origin/%s 的 tip：等於 %s 就照 done 處理（unblock --integration-tip 與 --runner），"
                "否則 git reset --hard %s 後 unblock --runner"
                % (push_error, err.strip()[-200:], head_after_merge, head_before_merge, integration, expected_tip, head_before_merge),
            )
        remote_now = out.split()
        if remote_now and remote_now[0] == expected_tip:
            return "done", "ff-merge 完成（推送回報失敗但遠端已是預期的 commit；%s）" % push_error
        restored, reset_note = _restore_integration_branch(config, integration, head_before_merge, head_after_merge)
        if restored:
            return "integration_push_failed", "%s；%s" % (push_error, reset_note)
        return "integration_unrecovered", "%s；%s" % (reset_note, push_error)
    return "done", "ff-merge 完成"


def extract_pr_url(output):
    """從 `gh pr create` 的 stdout 取出 PR 連結。

    頁面 PR 與斷點 PR 共用：兩邊都是「退出碼 0 之後從 stdout 找連結」，判斷標準必須一致。

    @param output gh 的 stdout；可為 None 或空字串
    @return 最後一個符合 PR_URL_RE 的連結（gh 把連結印在最後，前面可能有進度文字）；沒有就回空字串
    """
    # STEP 01: 逐行比對形狀，取最後一個符合的
    matched = [line.strip() for line in (output or "").splitlines() if PR_URL_RE.match(line.strip())]
    return matched[-1] if matched else ""


def push_branch_and_open_pr(config, entry):
    """推送頁面分支並開 PR（L1'）。

    entry 已經有 pr_url（上一輪開成功、但之後的合併或收尾沒走完）時只推分支、不再開 PR：
    同一個分支重複 `gh pr create` 會因為 PR 已存在而失敗，這一輪就會被記成 pr_failed、
    通知說「PR 未開成功」，而 PR 明明在（既有的 pr_url 不會被覆寫——record_pr_result 只在
    拿到新連結時寫、finish_done_entry 不碰它——但那一次 gh 呼叫是白做的、旗標是錯的）。
    分支仍然要推——重跑可能多了 commit，推上去既有的 PR 才會帶到。

    @param config runner 設定
    @param entry queue 裡的 entry（用到 branch、pr_url 與 PR 標題／內文需要的欄位）
    @return (pr_url, error)；成功時 error 為 None，失敗時 pr_url 為 None
    """
    integration = config["integration_branch"]
    # STEP 01: 推送頁面分支（全文落檔）
    log_path = session_log_path(config, "git-push-branch")
    code, _out, err = git(config, "push", "-u", "origin", entry["branch"], log_path=log_path)
    if code != 0:
        return None, "推送頁面分支失敗: %s%s" % (err.strip()[-200:], log_ref(config, log_path))

    # STEP 02: 已開過 PR 就沿用，不重開
    if entry.get("pr_url"):
        return entry["pr_url"], None

    # STEP 03: 組 PR 內文（只放統計與路徑，不放檔案內容）
    body = pr_body_for_entry(config, entry)
    title = "%s R18 升級: %s" % (entry.get("jira") or "", entry["id"])
    log_path = session_log_path(config, "gh-pr-create")
    code, out, err = run_command(
        [
            config["gh_bin"],
            "pr",
            "create",
            "--base",
            integration,
            "--head",
            entry["branch"],
            "--draft",
            "--title",
            title.strip(),
            "--body",
            body,
        ],
        cwd=config["repo_dir"],
        log_path=log_path,
    )
    if code != 0:
        return None, "開 PR 失敗: %s%s" % ((err or out).strip()[-200:], log_ref(config, log_path))
    # STEP 04: 從輸出取 PR 連結（gh 會把它印在最後一行）；只認 PR_URL_RE 的形狀，找不到一律視為失敗，
    # 不可用 (out.strip(), None) 蒙混——呼叫端用 `pr_error is None` 判斷 pr_failed，
    # 退出碼 0 但沒有 URL（例如 gh 輸出格式跑掉、PR 其實沒真的建立）曾經因此被誤記成
    # pr_failed=False、pr_url="" 這種看起來成功但完全無法追蹤的假狀態。
    # 也不能「以 http 開頭就算」：pr_url 現在會立刻寫進 queue，而且 STEP 02 看到它有值就不再開 PR，
    # 把登入／更新提示的網址記進去，這個 entry 就永遠不會有 PR 了
    url = extract_pr_url(out)
    if not url:
        return None, "gh pr create 退出碼 0 但輸出無可用 PR URL: %s" % (out or "").strip()[-200:]
    return url, None


def pr_body_for_entry(config, entry):
    """組出頁面 PR 的內文：entry 資訊 + 進度統計一行。"""
    # STEP 01: entry 基本資訊
    lines = [
        "## 遷移 entry `%s`" % entry["id"],
        "",
        "- 類型: %s / 波次: %s" % (entry.get("type"), entry.get("wave")),
        "- 目標目錄: `%s`" % entry.get("r18_dir"),
        "- 功能開關: `%s`（預設 %s）"
        % (entry.get("feature_flag", {}).get("key"), entry.get("feature_flag", {}).get("default")),
        "- 涵蓋原始檔 %d 個" % len(entry.get("r15_paths", [])),
        "",
    ]
    # STEP 02: 報告路徑與整體統計
    report_path = state_path(config, "%s-report.md" % entry["id"])
    if os.path.exists(report_path):
        lines.append("- 驗證報告: `%s`" % report_path)
    try:
        queue = load_queue(config)
        lines.append("")
        lines.append(progress_stat_line(queue))
    except (OSError, ValueError) as exc:
        lines.append("（統計無法產生: %s）" % exc)
    return "\n".join(lines)


def record_r15_hashes(config, entry):
    """記錄本次遷移當下每個 R15 原始檔的內容 hash，供 changed_r15_files 事後比對。

    刻意用嚴格版 file_sha1、不用 file_sha1_or_none：若這裡把讀取失敗吞成 None，
    未來 changed_r15_files 比對時，只要同一個檔案在「記錄當下」與「事後檢查」兩次
    都剛好讀取失敗，兩次都會是 None，`None != None` 為 False，反而會被判定成
    「沒有變動」——跟「讀不到就該當成已變動看待」的原意正好相反。讀取失敗在這個
    時間點就應該直接讓例外冒出去（由 collect_closing_data 在合併與推送之前呼叫，
    此時拋例外整合分支還沒動，值得停下來檢查），不要留到事後比對才發現資料本來就不可信。檔案「不存在」仍合法回 None（entry 遷移後刻意刪除
    R15 原檔的正常狀況）。
    """
    # STEP 01: 逐檔用嚴格版 file_sha1 記錄；讀取失敗直接往外拋
    hashes = {}
    for relative in entry.get("r15_paths", []):
        hashes[relative] = file_sha1(os.path.join(config["repo_dir"], relative))
    return hashes


def collect_closing_data(config, entry):
    """取得 entry 收尾時要寫回 queue 的資料；必須在整合分支 push（不可逆）之前呼叫。

    這裡兩個讀取都是嚴格版、失敗會拋例外。放在 push 之前，拋了也只是「這一輪沒做完」：
    遠端整合分支還沒動，重啟後 entry 照常重跑。放在 push 之後，拋了就是「遠端已前進、
    entry 還停在 running」，重啟後 l1_verify 看到分支相對整合分支沒有新 commit，
    只會判成沒有 commit，這個 entry 再也標不成 done。

    在 entry 分支上算的 R15 hash 與合併後算的相同：ff-merge 不產生新 commit，
    合併後整合分支的檔案樹就是 entry 分支的檔案樹。

    @param config runner 設定
    @param entry queue 裡的 entry（用到 branch、r15_paths）
    @return {"commit": entry 分支 tip 的完整 sha, "r15_hashes": {相對路徑: sha1 或 None}}
    """
    # STEP 01: entry 分支的 commit——ff-merge 並推送成功後，它同時就是整合分支的新 tip
    commit = git_out_or_raise(config, "rev-parse", entry["branch"])
    # STEP 02: R15 原始檔的內容 hash
    hashes = record_r15_hashes(config, entry)
    return {"commit": commit, "r15_hashes": hashes}


# ================================================================ 斷點


def wave_completed(queue, wave):
    """判斷某個 wave 的所有 entry 是否都已 done。"""
    entries = [item for item in queue.get("modules", []) if item.get("wave") == wave]
    if not entries:
        return False
    return all(item.get("status") == "done" for item in entries)


def due_checkpoint(queue):
    """找出現在該觸發的斷點（wave 全 done 且尚未開）。"""
    # STEP 01: 依宣告順序找第一個符合的
    for checkpoint in queue.get("checkpoints", []):
        if checkpoint.get("status") != "pending":
            continue
        wave = (checkpoint.get("after") or {}).get("wave")
        if wave is None:
            continue
        if wave_completed(queue, wave):
            return checkpoint
    return None


def auto_checkpoint_needed(config, queue):
    """自動保險：距離上一個斷點累積的模組數或行數是否已超門檻。

    回傳 (needed, detail)。
    """
    # STEP 01: 找出上一個已開的斷點分支當比較基準
    opened = [cp for cp in queue.get("checkpoints", []) if cp.get("status") in ("opened", "merged", "released")]
    base_ref = None
    if opened:
        base_ref = opened[-1].get("branch")
    modules_since = 0
    for entry in queue.get("modules", []):
        if entry.get("status") == "done" and not entry.get("checkpoint_id"):
            modules_since += 1
    if modules_since >= config["checkpoint_max_modules"]:
        return True, "累積 %d 個模組未進斷點" % modules_since
    # STEP 02: 行數門檻（沒有基準分支就跳過行數判斷）
    if base_ref:
        stat = git_out(config, "diff", "--shortstat", "%s..%s" % (base_ref, config["integration_branch"]))
        numbers = [int(value) for value in re.findall(r"(\d+) (?:insertion|deletion)", stat)]
        if sum(numbers) >= config["checkpoint_max_lines"]:
            return True, "累積 %d 行未進斷點" % sum(numbers)
    return False, ""


def open_checkpoint(config, checkpoint_id, auto_title=None):
    """凍結斷點分支、推送、開 draft PR，並更新 checkpoint 狀態。"""
    integration = config["integration_branch"]
    branch = "r18-migration/cp-%s" % checkpoint_id
    # STEP 01: 從整合分支 HEAD 建立 cp 分支
    code, _out, err = git(config, "branch", "-f", branch, integration)
    if code != 0:
        mark_checkpoint_failed(config, checkpoint_id, "建立 cp 分支失敗: %s" % err.strip()[-200:])
        return False
    code, _out, err = git(config, "push", "-u", "origin", branch)
    if code != 0:
        mark_checkpoint_failed(config, checkpoint_id, "推送 cp 分支 %s 失敗: %s" % (branch, err.strip()[-200:]))
        return False

    # STEP 02: 以 render-progress 的全文當 PR 內文
    queue = load_queue(config)
    checkpoint = find_checkpoint(queue, checkpoint_id) or {}
    body = render_progress_text(config, queue, checkpoint_id=checkpoint_id)
    title = checkpoint.get("title") or auto_title or ("R18 遷移斷點 %s" % checkpoint_id)
    code, out, err = run_command(
        [
            config["gh_bin"],
            "pr",
            "create",
            "--base",
            checkpoint.get("pr_base") or config["base_branch"],
            "--head",
            branch,
            "--draft",
            "--title",
            title,
            "--body",
            body,
        ],
        cwd=config["repo_dir"],
    )
    if code != 0:
        # cp 分支已經推上 origin，訊息帶分支名，人工接手時才知道要對哪支分支開 PR
        mark_checkpoint_failed(
            config, checkpoint_id, "開 cp PR 失敗（分支 %s 已推上 origin）: %s" % (branch, (err or out).strip()[-200:])
        )
        return False

    # STEP 03: 取 PR 連結。gh 退出碼 0 但 stdout 沒有 PR 連結時**不**當成失敗，照樣往下寫 opened、
    # 蓋章——與頁面 PR（push_branch_and_open_pr）的標準刻意不同。兩個呼叫端都靠 opened／蓋章運作：
    # hard 斷點只有 open_checkpoint 回 True 才會停下等人放行（回 False＝人工閘門消失）；auto 斷點在
    # 開成功之前不在 queue 裡，標 failed 是空轉，entry 沒蓋章的話 auto_checkpoint_needed 永遠不歸零，
    # 每完成一個模組就再推一支 cp 分支、再開一個真的 PR（1.1.1 第六輪 review 實跑重現）。
    # 代價是 pr_url 可能是空的：通知與進度檔會寫明沒有連結、請人到 GitHub 看該分支有沒有 PR。
    # 正解是在這裡查該分支既有的 PR 沿用、查不到才失敗並把失敗落盤——那是 1.1.2 重啟對帳的一部分。
    pr_url = extract_pr_url(out)

    # STEP 04: 寫回狀態，並把這個斷點涵蓋的模組標記起來

    def mutator(queue_data):
        """更新 checkpoint 與其涵蓋的 entry。"""
        target = find_checkpoint(queue_data, checkpoint_id)
        if target is None:
            target = dict(CHECKPOINT_FIELD_DEFAULTS)
            target.update({"id": checkpoint_id, "after": {"wave": None}, "mode": "soft",
                           "pr_base": config["base_branch"], "title": title})
            queue_data.setdefault("checkpoints", []).append(target)
        target["status"] = "opened"
        target["branch"] = branch
        target["pr_url"] = pr_url
        target["opened_at"] = now_iso()
        for entry in queue_data.get("modules", []):
            if entry.get("status") == "done" and not entry.get("checkpoint_id"):
                entry["checkpoint_id"] = checkpoint_id
        return target

    mutate_queue(config, mutator)
    # STEP 05: 斷點歸屬變了，進度檔要重畫一次（模組完成時畫的那份還沒有斷點區塊）
    write_progress(config)
    log_event(config, None, "checkpoint_opened", detail={"checkpoint": checkpoint_id, "pr": pr_url})
    pr_line = pr_url or "（gh 未回傳連結，請到 GitHub 確認分支 %s 是否已有 PR；輸出: %s）" % (
        branch,
        (out or "").strip()[-200:],
    )
    notify(
        config,
        "checkpoint_opened",
        "斷點 %s 已開 PR" % checkpoint_id,
        "分支: %s\nPR: %s\n模式: %s" % (branch, pr_line, checkpoint.get("mode", "soft")),
    )
    return True


def mark_checkpoint_failed(config, checkpoint_id, reason):
    """把斷點標成 failed 並通知。"""

    def mutator(queue_data):
        """就地改寫 checkpoint 狀態。"""
        target = find_checkpoint(queue_data, checkpoint_id)
        if target is not None:
            target["status"] = "failed"
        return target

    mutate_queue(config, mutator)
    log_event(config, None, "checkpoint_failed", detail={"checkpoint": checkpoint_id, "reason": reason})
    notify(config, "module_blocked", "斷點 %s 失敗" % checkpoint_id, reason)


def sync_merged_checkpoints(config, queue):
    """偵測已經合進基準分支的 cp 分支，標成 merged 之後不再回流。"""
    # STEP 01: 逐個 opened 斷點用 merge-base 判斷是否已是基準分支的祖先
    changed = []
    for checkpoint in queue.get("checkpoints", []):
        if checkpoint.get("status") != "opened" or not checkpoint.get("branch"):
            continue
        code, _out, _err = git(
            config,
            "merge-base",
            "--is-ancestor",
            checkpoint["branch"],
            "origin/%s" % config["base_branch"],
        )
        if code == 0:
            changed.append(checkpoint["id"])
    if not changed:
        return []

    def mutator(queue_data):
        """把偵測到的斷點標成 merged。"""
        for checkpoint in queue_data.get("checkpoints", []):
            if checkpoint.get("id") in changed:
                checkpoint["status"] = "merged"
        return changed

    mutate_queue(config, mutator)
    return changed


# ================================================================ 進度輸出


def count_status(queue):
    """統計各狀態的 entry 數量。"""
    counts = {}
    for entry in queue.get("modules", []):
        status = entry.get("status", "pending")
        counts[status] = counts.get(status, 0) + 1
    return counts


def progress_stat_line(queue):
    """組出一行統計字串。"""
    counts = count_status(queue)
    order = ["done", "running", "pending", "blocked", "failed", "waiting_quota"]
    parts = ["%s %d" % (name, counts.get(name, 0)) for name in order]
    runner_state = queue.get("runner_state", {})
    parts.append("runner %s%s" % (runner_state.get("state", "idle"),
                                  "(%s)" % runner_state["reason"] if runner_state.get("reason") else ""))
    return "統計：" + " / ".join(parts)


def report_stats(config, entry_id):
    """從 <entry>-report.md 取出警告數與未執行驗證項目。

    報告不存在時回 (0, [])。
    """
    # STEP 01: 讀檔
    path = state_path(config, "%s-report.md" % entry_id)
    text = read_text_file(path)
    if not text:
        return 0, []
    # STEP 02: 警告數 = ⚠ 出現次數；未執行驗證 = 對應段落的條列項
    warnings = text.count("⚠")
    unverified = []
    collecting = False
    for line in text.splitlines():
        if line.startswith("#"):
            collecting = "未執行" in line or "未驗證" in line
            continue
        if collecting and line.strip().startswith("-"):
            unverified.append(line.strip().lstrip("- ").strip())
    return warnings, unverified[:5]


def changed_r15_files(config, queue):
    """比對 r15_hashes 找出「遷移後 R15 原檔又被改過」的模組。

    這是報表產生路徑（render_progress_text 用），單一檔案讀取失敗不該讓整份
    PROGRESS.md 產不出來，所以用 try/except 而不是直接用寬容版 file_sha1_or_none
    ——寬容版會把「讀不到」跟「內容沒變」用同一個 None 表示，若記錄當下與比對當下
    剛好都讀取失敗，兩次 None 會被誤判成沒有變動；這裡改成讀取失敗也明確視為
    「已變動」，跟語意相符又不影響報表產生。
    """
    # STEP 01: 只看已完成且有記錄 hash 的 entry
    changed = []
    for entry in queue.get("modules", []):
        if entry.get("status") != "done":
            continue
        drifted = []
        for relative, recorded in (entry.get("r15_hashes") or {}).items():
            path = os.path.join(config["repo_dir"], relative)
            try:
                current = file_sha1(path)
            except RuntimeError:
                drifted.append(relative)
                continue
            if current != recorded:
                drifted.append(relative)
        if drifted:
            changed.append((entry["id"], drifted))
    return changed


def render_progress_text(config, queue, checkpoint_id=None):
    """產生 PROGRESS.md（或某個斷點 PR 內文）的完整內容。"""
    lines = ["# R18 遷移進度", "", progress_stat_line(queue), ""]

    # STEP 01: 通知降級警示（deadletter 有殘留就標在最前面）
    deadletter_path = state_path(config, "notify-deadletter.jsonl")
    deadletter_count = 0
    if os.path.exists(deadletter_path):
        with open(deadletter_path, "r", encoding="utf-8") as handle:
            deadletter_count = sum(1 for _line in handle)
    if deadletter_count:
        lines.append("> ⚠ 有 %d 則通知尚未送達（notify-deadletter.jsonl）" % deadletter_count)
        lines.append("")

    # STEP 02: 本斷點包含的模組表
    target_checkpoint = checkpoint_id
    if target_checkpoint is None:
        opened = [cp for cp in queue.get("checkpoints", []) if cp.get("status") == "opened"]
        target_checkpoint = opened[-1]["id"] if opened else None
    if target_checkpoint:
        lines.append("## 斷點 %s 涵蓋的模組" % target_checkpoint)
        lines.append("")
        lines.append("| 模組 | 類型 | 波次 | commit | 頁面 PR | ⚠ 數 | 未執行驗證 |")
        lines.append("|---|---|---|---|---|---|---|")
        for entry in queue.get("modules", []):
            if entry.get("checkpoint_id") != target_checkpoint:
                continue
            warnings, unverified = report_stats(config, entry["id"])
            lines.append(
                "| %s | %s | %s | %s | %s | %d | %s |"
                % (
                    entry["id"],
                    entry.get("type", ""),
                    entry.get("wave", ""),
                    (entry.get("last_commit") or "")[:10],
                    entry.get("pr_url") or "-",
                    warnings,
                    "；".join(unverified) if unverified else "-",
                )
            )
        lines.append("")

    # STEP 03: 全部模組總表
    lines.append("## 全部模組")
    lines.append("")
    lines.append("| 模組 | 類型 | 波次 | 狀態 | 頁面 PR | 所屬斷點 | 備註 |")
    lines.append("|---|---|---|---|---|---|---|")
    for entry in queue.get("modules", []):
        note = entry.get("blocked_reason") or entry.get("last_error") or ""
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s |"
            % (
                entry["id"],
                entry.get("type", ""),
                entry.get("wave", ""),
                entry.get("status", "pending"),
                entry.get("pr_url") or "-",
                entry.get("checkpoint_id") or "-",
                str(note)[:80].replace("|", "/"),
            )
        )
    lines.append("")

    # STEP 04: R15 原檔在遷移後又被改動的模組
    lines.append("## R15 原檔已變動的已遷移模組")
    lines.append("")
    drift = changed_r15_files(config, queue)
    if not drift:
        lines.append("（無）")
    else:
        for entry_id, files in drift:
            lines.append("- `%s`：%s" % (entry_id, "、".join(files)))
    lines.append("")

    # STEP 05: 待人工事項
    lines.append("## 待人工事項")
    lines.append("")
    pending_human = []
    for entry in queue.get("modules", []):
        if entry.get("status") in ("blocked", "failed"):
            pending_human.append(
                "- `%s` %s：%s%s"
                % (
                    entry["id"],
                    entry.get("status"),
                    entry.get("blocked_reason") or entry.get("last_error") or "",
                    "（診斷: `%s`）" % entry["last_diagnostics"] if entry.get("last_diagnostics") else "",
                )
            )
        if entry.get("pr_failed"):
            pending_human.append("- `%s` 頁面 PR 未開成功，需人工補開" % entry["id"])
    for checkpoint in queue.get("checkpoints", []):
        if checkpoint.get("status") == "failed":
            pending_human.append("- 斷點 `%s` 失敗，需人工處理" % checkpoint["id"])
        if checkpoint.get("status") == "opened" and checkpoint.get("mode") == "hard":
            pending_human.append(
                "- 斷點 `%s` 等待放行：`python3 runner.py release %s`" % (checkpoint["id"], checkpoint["id"])
            )
    if deadletter_count:
        pending_human.append("- 通知 deadletter 尚有 %d 則未送達" % deadletter_count)
    if not pending_human:
        pending_human.append("（無）")
    lines.extend(pending_human)
    lines.append("")
    lines.append("_更新時間：%s_" % now_iso())
    return "\n".join(lines)


def write_progress(config, queue=None):
    """把進度內容寫進 PROGRESS.md。"""
    # STEP 01: 沒帶 queue 就自己讀一份
    if queue is None:
        queue = load_queue(config)
    text = render_progress_text(config, queue)
    path = state_path(config, "PROGRESS.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return path


# ================================================================ 取件與前置


def eligible_entries(queue):
    """挑出可以執行的 entry：pending 且依賴全部 done。

    排序：wave 小→大 → shared 優先 → 檔數少→多。
    """
    # STEP 01: 先建 id → status 對照
    status_by_id = {entry.get("id"): entry.get("status") for entry in queue.get("modules", [])}
    ready = []
    for entry in queue.get("modules", []):
        if entry.get("status") != "pending":
            continue
        deps = entry.get("depends_on") or []
        if all(status_by_id.get(dep) == "done" for dep in deps):
            ready.append(entry)
    # STEP 02: 依三層鍵排序
    ready.sort(
        key=lambda item: (
            item.get("wave", 0),
            0 if item.get("type") == "shared" else 1,
            len(item.get("r15_paths", [])),
            item.get("id", ""),
        )
    )
    return ready


def module_preflight(config, queue):
    """每個模組開工前的 git 前置作業。

    回傳 (ok, pause_reason, detail)。ok 為 False 時 runner 應進入 paused；pause_reason 是
    LOCAL_AHEAD_REASON 時呼叫端要鎖定（hold），其餘一般暫停。
    """
    integration = config["integration_branch"]
    # STEP 01: 取得遠端最新狀態
    code, _out, err = git(config, "fetch", "origin")
    if code != 0:
        return False, "master_conflict", "git fetch 失敗: %s" % err.strip()[-200:]

    # STEP 02: 切到整合分支並確認樹是乾淨的
    code, _out, err = git(config, "checkout", integration)
    if code != 0:
        return False, "integration_dirty", "切換整合分支失敗: %s" % err.strip()[-200:]
    if merge_in_progress(config):
        return False, "integration_dirty", "整合分支殘留 MERGE_HEAD"
    if not working_tree_clean(config):
        return False, "integration_dirty", "工作樹有未提交的變更"

    # STEP 03: 比對遠端整合分支 tip 與記錄值（決策 21）
    remote_tip = git_out(config, "rev-parse", "origin/%s" % integration)
    recorded_tip = queue.get("integration_tip_sha")
    if not remote_tip:
        return False, "integration_diverged", "讀不到 origin/%s 的 tip" % integration
    if recorded_tip is None:
        set_integration_tip(config, remote_tip)
        log_event(config, None, "integration_tip_baseline", detail={"sha": remote_tip})
    elif recorded_tip != remote_tip:
        return (
            False,
            "integration_diverged",
            "遠端整合分支 tip %s 與記錄值 %s 不同" % (remote_tip[:10], str(recorded_tip)[:10]),
        )

    # STEP 04: 本機整合分支領先遠端時，只接受「runner 自己前置作業做的合併」那種領先。下面 STEP 06／07
    # 會把基準分支與斷點分支合進本機整合分支而不推（要等該 entry 走到 merge_to_integration 的 push 才上遠端），
    # 所以 entry 沒走到 push（失敗／blocked／額度／斷點）、或前置作業本身在合併之後才失敗（斷點回流衝突、
    # 停止訊號）時，本機本來就會領先。判定用結構、不用記錄（記錄式有「HEAD 動了但還沒記」的窗）：領先的
    # commit 裡只數「不是 merge commit、而且不可從 origin/<base> 或任何斷點分支到達」的——runner 自己做的
    # 只有 merge commit 與 base／斷點分支上的 commit，entry 分支不可能有 merge commit（CLI 被禁用 git merge）。
    # 數到的只會來自沒走完的發佈段（ff-merge 之後被中斷、退不回去、或人只跑了 unblock --runner 沒把本機對齊）：
    # 下一步的 --ff-only 對它是 no-op、看不出來，之後 prepare_branch 會從這個 commit 切下一個 entry 的分支、
    # 最後把它推上去。專屬原因，呼叫端據此鎖定；本機分支不動（那是證據）。git 指令失敗不能當成 0 個放行
    code, out, err = git(config, "rev-list", "--count", "origin/%s..%s" % (integration, integration))
    if code != 0:
        return False, "integration_diverged", "讀取本機整合分支領先數失敗: %s" % err.strip()[-200:]
    if out.strip() != "0":
        try:
            exclude = ["origin/%s" % integration, "origin/%s" % config["base_branch"]] + checkpoint_refs(config, queue)
        except RuntimeError as exc:
            return False, "integration_diverged", "列本機分支失敗，無法判定領先的 commit 是不是 runner 合進來的: %s" % exc
        code, out, err = git(config, "log", "--no-merges", "--oneline", integration, "--not", *exclude)
        if code != 0:
            return False, "integration_diverged", "列本機整合分支多出來的 commit 失敗: %s" % err.strip()[-200:]
        foreign = [line for line in out.splitlines() if line.strip()]
        if foreign:
            code, out, err = git(config, "rev-parse", integration)
            local_tip = (out.strip()[:12] if code == 0 else "") or ("讀取失敗: %s" % err.strip()[-200:])
            return (
                False,
                LOCAL_AHEAD_REASON,
                local_ahead_detail(integration, str(len(foreign)), local_tip, remote_tip[:12], "\n".join(foreign)),
            )

    # STEP 05: 本地落後就補齊（ff-only；上一步已確認本地要嘛沒領先、要嘛只領先自己做的合併）
    code, _out, err = git(config, "merge", "--ff-only", "origin/%s" % integration)
    if code != 0:
        return False, "integration_diverged", "整合分支無法 fast-forward: %s" % err.strip()[-200:]

    # STEP 06: 與基準分支同步；衝突自己 abort
    # git merge 的衝突檔名清單印在 stdout（不是 stderr），只截 stderr 常常拿到空字串，
    # 所以在 abort 之前先問一次「目前哪些檔案還沒解決」（abort 後這個查詢就查不到了）
    log_path = session_log_path(config, "git-merge-base")
    code, _out, err = git(config, "merge", "origin/%s" % config["base_branch"], log_path=log_path)
    if code != 0:
        conflicted = git_out(config, "diff", "--name-only", "--diff-filter=U")
        git(config, "merge", "--abort")
        detail = "與基準分支合併衝突: %s%s" % (
            conflicted.replace("\n", ", ") if conflicted else err.strip()[-200:],
            log_ref(config, log_path),
        )
        return False, "master_conflict", detail

    # STEP 07: 回流所有還開著的斷點分支
    sync_merged_checkpoints(config, queue)
    for checkpoint in queue.get("checkpoints", []):
        if checkpoint.get("status") != "opened" or not checkpoint.get("branch"):
            continue
        log_path = session_log_path(config, "git-merge-cp-%s" % checkpoint["id"])
        code, _out, err = git(config, "merge", checkpoint["branch"], log_path=log_path)
        if code != 0:
            conflicted = git_out(config, "diff", "--name-only", "--diff-filter=U")
            git(config, "merge", "--abort")
            detail = "斷點分支 %s 回流衝突: %s%s" % (
                checkpoint["id"],
                conflicted.replace("\n", ", ") if conflicted else err.strip()[-200:],
                log_ref(config, log_path),
            )
            return False, "master_conflict", detail
    return True, "", ""


def checkpoint_refs(config, queue):
    """列出 queue 裡每個斷點分支在本機存在的 ref（本機分支與 origin 追蹤分支都算），給 module_preflight 排除用。

    不看斷點狀態：已 released／merged 的斷點分支早就回流進本機整合分支，它的 commit 一樣是 runner 合進來的。
    ref 不存在的略過（rev-list 拿到不存在的名字會整個失敗）；列 ref 的指令本身失敗則往外拋——
    用寬容版把失敗當成空清單，等於「斷點分支都不存在」，回流進來的斷點 commit 會全被當成外來的而鎖定。

    @param config runner 設定
    @param queue 整份 queue（用到 checkpoints[].branch）
    @return ref 名稱清單（refs/heads/… 與 refs/remotes/origin/…）
    @raises RuntimeError for-each-ref 失敗
    """
    # STEP 01: 一次列出所有本機分支與 origin 追蹤分支（嚴格版：失敗不可與「沒有分支」混淆）
    existing = set(git_out_or_raise(config, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin").splitlines())
    # STEP 02: 斷點分支名對上就收
    refs = []
    for checkpoint in queue.get("checkpoints", []):
        branch = checkpoint.get("branch")
        if not branch:
            continue
        for candidate in ("refs/heads/%s" % branch, "refs/remotes/origin/%s" % branch):
            if candidate in existing:
                refs.append(candidate)
    return refs


def local_ahead_detail(integration, foreign_count, local_tip, remote_tip, foreign_listing):
    """組 integration_local_ahead 暫停的細節：動作一句在前、診斷在後。

    通知會在 300 字截尾（notify.sh 的 max_text_chars），扣掉標題（約 38）、`診斷:` 一行（約 63）與鎖定前綴
    （約 75）只剩約 124 字，第一句一定要放得下「先對齊再 unblock」，分支名只出現兩次（對齊指令裡）；
    測試用預設分支名走一次真的 enter_paused、照 notify.sh 的規則截斷後驗。

    @param integration 整合分支名稱
    @param foreign_count 不是 runner 合進來的 commit 數（字串）
    @param local_tip 本機整合分支 tip（短 sha 或「讀取失敗: …」）
    @param remote_tip 遠端整合分支 tip（短 sha）
    @param foreign_listing 那些 commit 的 --oneline 清單（多行）
    @return 細節文字
    """
    # STEP 01: 動作句＋診斷句
    return (
        "先看下列 commit、確認保留後 git checkout %s && git reset --hard origin/%s，再 unblock --runner。"
        "本機整合分支有 %s 個不是 runner 合進來的 commit（本機 %s、遠端 %s）: %s"
        % (integration, integration, foreign_count, local_tip, remote_tip, preview_lines(foreign_listing, DIRTY_LIST_PREVIEW_LINES))
    )


def set_integration_tip(config, sha):
    """把整合分支的 HEAD 記進 queue.json。"""

    def mutator(queue):
        """就地更新 integration_tip_sha。"""
        queue["integration_tip_sha"] = sha
        return sha

    return mutate_queue(config, mutator)


def install_deps_if_lockfile_changed(config, previous_hash):
    """lockfile 有變動就重新安裝依賴。

    回傳 (ok, new_hash, detail)。
    """
    # STEP 01: 比對 hash，沒變就什麼都不做
    current = lockfile_hash(config)
    if current is None or current == previous_hash:
        return True, current, "lockfile 未變動"
    # STEP 02: 變動就跑一次乾淨安裝（全文落檔）
    cwd = os.path.join(config["repo_dir"], FRONTEND_R18_RELATIVE)
    log_path = session_log_path(config, "npm-ci")
    code, out, err = run_command(["npm", "ci"], cwd=cwd, timeout=NPM_CI_TIMEOUT_SECONDS, log_path=log_path)
    if code != 0:
        # stdout+stderr 合併後只留末段，通知/記錄才看得到實際的 npm 錯誤輸出
        combined = "%s\n%s" % (out or "", err or "")
        return False, current, tail_lines(combined, NPM_FAILURE_TAIL_LINES) + log_ref(config, log_path)
    return True, current, "npm ci 完成"


def prepare_branch(config, entry):
    """切到（必要時建立）entry 的頁面分支。

    回傳 (ok, detail)。
    """
    # STEP 01: 分支已存在就直接切過去（resume 情境）
    branch = entry.get("branch")
    if not branch:
        return False, "entry 缺少 branch 欄位"
    exists = git_out(config, "rev-parse", "--verify", "--quiet", "refs/heads/%s" % branch)
    if exists:
        code, _out, err = git(config, "checkout", branch)
        if code != 0:
            return False, "切換既有分支失敗: %s" % err.strip()[-200:]
        return True, "checkout 既有分支"
    # STEP 02: 不存在就從整合分支 HEAD 建立
    code, _out, err = git(config, "checkout", "-b", branch, config["integration_branch"])
    if code != 0:
        return False, "建立分支失敗: %s" % err.strip()[-200:]
    return True, "建立新分支"


# ================================================================ run 主流程


def last_paused_reason_from_log(config):
    """讀 runner.log.jsonl 最後一筆「實質」事件，若是 paused 就回傳它的 reason。

    queue.json 損毀（queue_corrupt）時 enter_paused 讀不到 runner_state，
    去重就不能靠 queue 內容，改看 log 檔（log 檔不受 queue 損毀影響）。
    log_event("paused", ...) 之後通常緊接著 notify() 自己再記一筆 notify/notify_failed/
    notify_skipped，那些只是通知投遞的紀錄、不是新的狀態事件，往前跳過去找真正的最後一筆事件；
    那筆不是 paused，或檔案不存在／讀不出來，都回傳 None。
    """
    # STEP 01: 檔案不存在就沒有歷史可查
    path = state_path(config, "runner.log.jsonl")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    # STEP 02: 由後往前找，跳過 notify 系列的投遞紀錄，取第一筆真正的狀態事件
    notify_wrapper_events = ("notify", "notify_failed", "notify_skipped")
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            return None
        if record.get("event") in notify_wrapper_events:
            continue
        if record.get("event") != "paused":
            return None
        return (record.get("detail") or {}).get("reason")
    return None


def crash_signature(exc):
    """例外簽名：<例外類別>@<檔名>:<行號>（traceback 最內層），同簽名視為同一個 bug。"""
    frames = traceback.extract_tb(exc.__traceback__)
    if frames:
        last = frames[-1]
        return "%s@%s:%s" % (type(exc).__name__, os.path.basename(last.filename), last.lineno)
    return "%s@unknown" % type(exc).__name__


def handle_runner_crash(config, exc):
    """未預期例外的統一出口：traceback 落檔、印到 stderr、記事件，然後走 paused。回傳退出碼。

    必須在 except 區塊內呼叫（traceback.format_exc 才取得到當前例外）。走 enter_paused
    而不是 raise：raise 會讓 launchd 每隔 ThrottleInterval 重啟一次、每次一則 HIGH 通知，
    且 runner_state 停在 running 看不出曾經 crash；enter_paused 有去重與 hold。

    整段是 ShutdownDeferral 區間：這裡在 cmd_run 的 except handler 裡執行，期間再收到停止訊號
    會從 handler 裡冒出來、sibling 的 except 接不到，finally 放鎖而 hold 沒寫——對「收尾回報
    殘留行程」那一類 crash，等於鎖定沒生效、launchd 幾分鐘後照樣重啟。跑完 runner 本來就要以
    EXIT_PAUSED 退出，延後的訊號印 stderr 後丟棄、不再拋。

    @param config runner 設定
    @param exc 當前的例外
    @return runner 的退出碼（EXIT_PAUSED）
    """
    with ShutdownDeferral(raise_on_normal_exit=False):
        return _handle_runner_crash_uninterrupted(config, exc)


def _handle_runner_crash_uninterrupted(config, exc):
    """handle_runner_crash 的本體；呼叫端負責把它包在 ShutdownDeferral 裡。

    @param config runner 設定
    @param exc 當前的例外（必須仍在 except 區塊內）
    @return runner 的退出碼
    """
    # STEP 01: traceback 全文落檔到 crashes/，同時印到 stderr（launchd 的 StandardErrorPath 也看得到）
    trace_text = traceback.format_exc()
    signature = crash_signature(exc)
    print(trace_text, file=sys.stderr)
    # 檔名帶 pid：launchd 重啟間隔內同一秒兩次 crash 不會互相覆寫（stub 實測撞過）
    trace_name = "%s-%s-%s.txt" % (diagnostics.compact_ts(), os.getpid(), diagnostics.safe_name(signature))
    trace_path = os.path.join(config["state_dir"], diagnostics.CRASHES_DIR_NAME, trace_name)
    try:
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        with open(trace_path, "w", encoding="utf-8") as handle:
            handle.write(
                "signature: %s\nfingerprint: %s\n\n%s"
                % (signature, json.dumps(config.get("fingerprint") or {}, ensure_ascii=False), trace_text)
            )
    except OSError as os_exc:
        print("警告：寫入 traceback 失敗: %s" % os_exc, file=sys.stderr)
    # STEP 02: 事件紀錄（含簽名與檔案位置），再走 paused 統一出口
    trace_relative = diagnostics.relpath_in(config["state_dir"], trace_path)
    detail = "%s: %s（traceback: %s）" % (type(exc).__name__, exc, trace_relative)
    log_event(
        config,
        None,
        CRASH_REASON,
        detail={"signature": signature, "message": str(exc), "trace_path": trace_relative},
    )
    # STEP 03: 子孫行程沒收乾淨的那一類第一次就鎖定——不鎖的話 launchd 幾分鐘後重啟 runner，
    # preflight 把 entry 放回 pending、prepare_branch 開始動 repo，而殘留行程可能還活著
    return enter_paused(
        config,
        CRASH_REASON,
        detail,
        signature=signature,
        trace_text=trace_text,
        notify_event="runner_crashed",
        force_hold=isinstance(exc, ProcessCleanupError),
    )


def enter_paused(config, reason, detail, signature=None, trace_text=None, notify_event="paused", force_hold=False):
    """進入 runner 級暫停：凍結證據、記錄、必要時通知，然後回傳退出碼（整段是停止訊號的延後區間）。

    延後的理由與 handle_runner_crash 相同：訊號落在「判定要鎖定」與「hold 寫進 queue」之間，外層會當
    正常停止回 EXIT_OK；重啟後造成鎖定的狀況可能已看不出來（例如本機整合分支已退回），entry 放回 pending
    繼續跑，宣稱必須人工確認的鎖定被整個繞過。區間跑完 runner 本來就以 EXIT_PAUSED 退出，延後的訊號丟棄。
    參數與行為見 _enter_paused_uninterrupted。

    @param config runner 設定
    @param reason 暫停原因代號
    @param detail 給人看的細節
    @param signature 這次暫停的簽名（同簽名連續第二次就鎖定）；None 表示不看簽名
    @param trace_text 例外 traceback 全文（進 runner 級診斷包）
    @param notify_event 通知事件代號
    @param force_hold 第一次就鎖定
    @return EXIT_PAUSED
    """
    # STEP 01: 整段納入延後區間
    with ShutdownDeferral(raise_on_normal_exit=False):
        return _enter_paused_uninterrupted(config, reason, detail, signature, trace_text, notify_event, force_hold)


def _enter_paused_uninterrupted(config, reason, detail, signature, trace_text, notify_event, force_hold):
    """enter_paused 的本體；呼叫端一律經 enter_paused（它負責延後停止訊號）。

    同一個原因重啟後再次偵測到時只留紀錄、不重複通知（避免通知疲勞）。

    force_hold：第一次出現就鎖定（hold），不等同簽名第二次。給「runner 不可以自己恢復執行」
    的暫停用——paused 只是結束行程，launchd 的 KeepAlive 幾分鐘後就會把 runner 重新拉起來、
    照常往下跑；需要人先確認過才能繼續的狀況（例如 CLI 的子孫行程沒收乾淨，可能還在改 repo），
    只有 hold 擋得住。hold 寫不進狀態檔（磁碟滿、I/O 錯誤）時照樣通知並回退出碼，但通知
    會寫明「鎖定沒有落盤、請立刻停掉 launchd 服務」，不宣稱已鎖定；事件紀錄帶 hold_persisted。

    signature：這次暫停的簽名（runner 例外用 crash_signature；整合分支推送失敗用 PUSH_FAILED_SIGNATURE）。
    給定時去重條件加上「同簽名」，且同簽名連續第二次出現會設 runner_state.hold——之後每次啟動在
    pre-flight 之前就靜默退出，直到 `unblock --runner`（否則 crash 若落在模組執行之後、或整合分支
    持續推不上去，每次 launchd 重啟都白燒一個模組預算）。hold 是新狀態，即使算重複也要通知一次。
    trace_text：例外 traceback 全文，進 runner 級診斷包。
    notify_event：通知事件代號（crash 用 runner_crashed，其餘 paused）。

    去重靠三層、依序嘗試，各自對應呼叫時機不同的盲區：
      1. config["startup_paused_reason"]（R2）——本次 process 啟動時從 queue 讀到的
         上一次 paused 原因，整個 process 生命週期不清除。給「cmd_run 主迴圈把
         runner_state 改成 running 之後才觸發」的暫停原因用（例如模組真的呼叫 CLI
         才發現的 auth_expired、L1 驗證時的 master_conflict/integration_diverged）——
         這些時間點查 queue.runner_state 只會看到「running」，查不到「上一輪也是
         paused」，只能靠這個 process 啟動當下就存好的值。
      2. queue.runner_state（既有機制）——直接讀目前 queue 記的狀態。給「還沒進主迴圈、
         runner_state 還沒被改成 running」的暫停原因用（例如 preflight() 內就判定的
         auth_expired/disk_low，見 R8）：這種情況下 queue 裡留的就是上一輪結束時的
         paused 狀態，不需要、也還沒有 startup_paused_reason 可用。
      3. runner.log.jsonl 尾端（R4）——查 1、2 都失敗（queue 讀不到，例如 queue_corrupt）
         時的最後手段，log 檔不受 queue 損毀影響。
    """
    # STEP 01: 判斷是不是「同一個原因的重複暫停」，見上方 docstring 的三層說明；有簽名時要同簽名才算重複
    repeated = config.get("startup_paused_reason") == reason
    if signature is not None:
        repeated = repeated and config.get("startup_crash_signature") == signature
    previous_hold = False
    try:
        queue = load_queue(config)
        runner_state = queue.get("runner_state", {})
        previous_hold = bool(runner_state.get("hold"))
        if runner_state.get("state") == "paused" and runner_state.get("reason") == reason:
            if signature is None or runner_state.get("crash_signature") == signature:
                repeated = True
    except (OSError, ValueError):
        # queue 本身壞掉（queue_corrupt）時讀不到 runner_state，改看 log 尾端（R4）
        if last_paused_reason_from_log(config) == reason:
            repeated = True
    hold = previous_hold or force_hold or bool(signature is not None and repeated)

    # STEP 02: 凍結 runner 級證據（不依賴 queue 可讀；queue_corrupt 時原檔照樣複製進包）
    bundle = freeze_runner_bundle(config, reason, detail, trace_text=trace_text)

    # STEP 03: 寫狀態與紀錄。落盤失敗不中斷（還是要通知、要回退出碼），但要記下來——
    # 下面的通知內容取決於 hold 到底有沒有寫進去
    persist_error = None
    try:
        set_runner_state(config, "paused", reason, extra={"crash_signature": signature, "hold": hold})
    except (OSError, ValueError) as exc:
        persist_error = exc
        print("警告：寫入 paused 狀態失敗: %s" % exc, file=sys.stderr)
    log_event(
        config,
        None,
        "paused",
        detail={
            "reason": reason,
            "detail": detail,
            "repeated": repeated,
            "signature": signature,
            "hold": hold,
            "hold_persisted": persist_error is None,
            "diagnostics": bundle,
        },
    )

    # STEP 04: 第一次進入才通知；hold 是新狀態，即使重複也要通知一次
    hold_transition = hold and not previous_hold
    if not repeated or hold_transition:
        if hold_transition:
            # 前綴盡量短（通知 300 字要省給細節）；第一次就鎖定的那種仍要說明為什麼鎖，殘留行程那條的細節只有例外名
            hold_cause = "必須人工確認後才能繼續，" if force_hold else "同一原因連續發生（%s），" % signature
            if persist_error is None:
                body = "%srunner 已鎖定（hold）；處理後執行 `runner.py unblock --runner` 解除\n細節: %s" % (
                    hold_cause,
                    detail,
                )
            else:
                # hold 只存在記憶體裡：launchd 的 KeepAlive 幾分鐘後照樣重啟 runner、沒有東西擋它，
                # 唯一有效的處置是人立刻把服務停掉，不能讓通知假裝已經鎖住了
                body = (
                    "%s鎖定（hold）沒有寫進狀態檔（%s）——launchd 會照常重啟 runner，"
                    "請立即 `launchctl unload` 停掉服務，處理完再 load\n細節: %s" % (hold_cause, persist_error, detail)
                )
        else:
            body = "細節: %s\n處理後 runner 會在下次重啟時自動續跑" % detail
            if persist_error is not None:
                body += "\n（paused 狀態沒有寫進狀態檔: %s；重啟後會重新偵測原因，可能重複通知）" % persist_error
        notify(config, notify_event, "runner 已暫停: %s" % reason, with_diagnostics_line(body, bundle))
    return EXIT_PAUSED


# 重啟時要放回 pending 的 entry 狀態：上一輪被中斷時留下的兩種「進行中」——running（模組執行中）與
# waiting_quota（額度等待中）。取件只挑 pending、unblock 只收 failed／blocked，不放回就永久卡住、沒有指令能救
INTERRUPTED_ENTRY_STATUSES = ("running", "waiting_quota")


def recover_interrupted_entries(queue):
    """把上一輪被中斷的 entry 放回 pending（就地改 queue），attempts 不變；回傳被復原的 entry id。

    waiting_quota 放回 pending 是安全的：主迴圈取件後、呼叫 CLI 之前還有額度 pre-flight，額度沒恢復會再等。

    @param queue 整份 queue（mutate_queue 的 mutator 內呼叫）
    @return 被放回 pending 的 entry id 清單（依 modules 順序）
    """
    # STEP 01: 逐個看狀態
    recovered = []
    for entry in queue.get("modules", []):
        if entry.get("status") in INTERRUPTED_ENTRY_STATUSES:
            entry["status"] = "pending"
            recovered.append(entry["id"])
    return recovered


def opened_hard_checkpoint(queue):
    """找出還在等人放行的 hard 斷點（status 仍是 opened）；沒有回 None。

    hard 斷點開了之後 runner 停在 wait_for_release 等人 release；等待期間被停掉（launchd 的 SIGTERM）
    斷點就停在 opened，而模組完成後的斷點檢查只看 pending 的斷點——主迴圈取件前要自己找它、回到等待，
    否則重啟後直接處理下一個模組，人工閘門被繞過。released／merged 的不算。

    @param queue 整份 queue
    @return 斷點 id 或 None
    """
    # STEP 01: 依宣告順序找第一個
    for checkpoint in queue.get("checkpoints", []):
        if checkpoint.get("status") == "opened" and checkpoint.get("mode") == "hard":
            return checkpoint.get("id")
    return None


def preflight(config):
    """啟動前的環境檢查。

    回傳 0 表示通過，非零表示應該直接退出。
    """
    # STEP 01: 狀態目錄若在 repo 內，必須被 git 忽略
    ensure_state_dir(config)
    if config["state_dir"].startswith(config["repo_dir"] + os.sep):
        code, _out, _err = git(config, "check-ignore", "-q", config["state_dir"])
        if code != 0:
            print("錯誤：狀態目錄位於 repo 內但未被 git 忽略: %s" % config["state_dir"], file=sys.stderr)
            return EXIT_PREFLIGHT

    # STEP 02: 磁碟空間
    # disk_low 跟 STEP01/03/05 不同——那三項是「部署當下就會被人看到」的設定錯誤，
    # 這項是執行期才會惡化的狀態；配合 launchd KeepAlive + ThrottleInterval，
    # 只印錯誤 exit 2 會變成每隔幾分鐘靜默重試一次、永遠沒人知道，正是決策 16 要防的
    # 無人看管盲區。改走 paused：通知一則 + exit 3，去重機制見 enter_paused docstring（R8）
    free_gb = disk_free_gb(config["state_dir"])
    if free_gb < config["disk_min_gb"]:
        detail = "磁碟剩餘 %.1f GB，低於下限 %d GB" % (free_gb, config["disk_min_gb"])
        return enter_paused(config, "disk_low", detail)

    # STEP 03: CLI 旗標支援度
    code, out, err = run_command([config["claude_bin"], "--help"], timeout=120)
    help_text = (out or "") + (err or "")
    if code != 0 and not help_text:
        print("錯誤：無法執行 CLI（%s）" % config["claude_bin"], file=sys.stderr)
        return EXIT_PREFLIGHT
    missing_flags = [flag for flag in REQUIRED_CLI_FLAGS if flag not in help_text]
    if missing_flags:
        print("錯誤：目前的 CLI 不支援下列旗標: %s" % ", ".join(missing_flags), file=sys.stderr)
        return EXIT_PREFLIGHT

    # STEP 04: 認證 smoke
    auth_env = os.environ.copy()
    if config["claude_config_dir"]:
        auth_env["CLAUDE_CONFIG_DIR"] = config["claude_config_dir"]
    code, out, err = run_command(
        [
            config["claude_bin"],
            "-p",
            "echo ok",
            "--output-format",
            "json",
            "--permission-mode",
            "auto",
            "--permission-prompts",
            "none",
        ],
        cwd=config["repo_dir"],
        timeout=300,
        env=auth_env,
    )
    if AUTH_TEXT_RE.search((out or "") + (err or "")):
        # 同 disk_low（STEP02 的註解）：token 到期是執行期狀態，不是部署當下的設定錯誤，
        # 一樣改走 paused 而不是單純印錯誤退出（R8）
        detail = "CLI 回報未登入。請重跑 `claude setup-token` 並更新 env 檔中的長效憑證。"
        return enter_paused(config, "auth_expired", detail)

    # STEP 05: 遠端整合分支必須存在
    integration = config["integration_branch"]
    code, out, _err = git(config, "ls-remote", "--heads", "origin", integration)
    if code != 0 or not out.strip():
        print("錯誤：遠端沒有整合分支 %s。請先手動建立：" % integration, file=sys.stderr)
        print(
            "  git checkout -b %s origin/%s && git push -u origin %s"
            % (integration, config["base_branch"], integration),
            file=sys.stderr,
        )
        return EXIT_PREFLIGHT
    # ls-remote 輸出格式是「<sha>\trefs/heads/<branch>」；先留住這個 SHA。
    # 首次啟動（queue.integration_tip_sha 還是 null）時直接在這裡寫入當基線，
    # 不等到 module_preflight 才寫——否則 STEP 02.02 的 runner_started 通知會先發出去，
    # 那時候基線還沒寫，印出來的 SHA 永遠是 None（R1）
    remote_integration_sha = out.strip().splitlines()[0].split()[0] if out.strip() else None

    # STEP 06: 清理過期 sessions、把 limits 寫進 queue、必要時寫入整合分支基線
    removed = cleanup_sessions(config)

    def mutator(queue):
        """把 env 的上限值寫進 queue.limits、修正殘留的 running 狀態，必要時寫入基線 SHA。"""
        queue["limits"] = {
            "entry_max_files": config["entry_max_files"],
            "entry_max_lines": config["entry_max_lines"],
            "checkpoint_max_modules": config["checkpoint_max_modules"],
            "checkpoint_max_lines": config["checkpoint_max_lines"],
            "module_timeout_min": config["module_timeout_min"],
            "module_budget_usd": config["module_budget_usd"],
        }
        queue["repo_dir"] = config["repo_dir"]
        queue["integration_branch"] = config["integration_branch"]
        queue["base_branch"] = config["base_branch"]
        # 只有「還沒有任何基線」時才寫；已有記錄值時交給 module_preflight 的既有比對邏輯處理
        baseline_written = None
        if queue.get("integration_tip_sha") is None and remote_integration_sha:
            queue["integration_tip_sha"] = remote_integration_sha
            baseline_written = remote_integration_sha
        return {"recovered": recover_interrupted_entries(queue), "baseline_written": baseline_written}

    try:
        mutator_result = mutate_queue(config, mutator)
    except ValueError as exc:
        # queue.json 損毀（queue_corrupt）：走 paused 通知路徑而不是單純印錯誤退出（R4）
        if "queue_corrupt" in str(exc):
            return enter_paused(config, "queue_corrupt", str(exc))
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    except OSError as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    recovered = mutator_result["recovered"]
    if mutator_result["baseline_written"]:
        log_event(config, None, "integration_tip_baseline", detail={"sha": mutator_result["baseline_written"]})
    log_event(config, None, "preflight_ok", detail={"sessions_removed": removed, "recovered": recovered})
    return 0


def add_cost(entry, outcome):
    """把這次呼叫的花費累進 entry.cost_usd_total（就地修改，供 mutator 內呼叫）。

    每一輪不論 done／blocked／error／等額度都要記——原本只在 done 累加，失敗輪次燒掉的錢
    只留在 cli_outcome 事件裡、entry 帳面低估（fresh-context 驗收 BONUS 抓到）。
    """
    if outcome.get("cost") is not None:
        entry["cost_usd_total"] = float(entry.get("cost_usd_total") or 0) + float(outcome["cost"])


def apply_outcome(config, entry_id, outcome):
    """把一次呼叫的判讀結果寫回 queue。

    回傳 (next_action, detail)：next_action 是 continue / verify / pause / wait。
    """
    kind = outcome["kind"]

    # STEP 01: 需要 runner 級暫停的兩種情況先處理
    if kind == "auth_expired":
        return "pause", ("auth_expired", outcome.get("detail", ""))

    # STEP 02: 額度類：狀態改 waiting_quota，不計 attempts
    if kind in ("quota", "quota_api_unavailable", "rate_limited"):

        def quota_mutator(queue):
            """標記為等待額度。"""
            entry = find_entry(queue, entry_id)
            if entry is not None:
                entry["status"] = "waiting_quota"
                entry["last_error"] = outcome.get("detail")
                add_cost(entry, outcome)
            return entry

        mutate_queue(config, quota_mutator)
        return "wait", outcome

    # STEP 03: done 交給 L1 驗證
    if kind == "done":
        return "verify", outcome

    # STEP 04: blocked / hook_denied 直接落地，不再重試
    if kind in ("blocked", "hook_denied"):
        reason = "hook_denied" if kind == "hook_denied" else (outcome.get("detail") or "needs_human")

        def blocked_mutator(queue):
            """標記為 blocked。"""
            entry = find_entry(queue, entry_id)
            if entry is not None:
                entry["status"] = "blocked"
                entry["blocked_reason"] = reason
                entry["last_error"] = outcome.get("detail")
                entry["last_diagnostics"] = outcome.get("diagnostics")
                entry["finished_at"] = now_iso()
                add_cost(entry, outcome)
            return entry

        mutate_queue(config, blocked_mutator)
        notify(
            config,
            "module_blocked",
            "模組 %s 卡住" % entry_id,
            with_diagnostics_line("原因: %s" % reason, outcome.get("diagnostics")),
        )
        return "continue", outcome

    # STEP 05: timeout / error：attempts++，達上限轉 failed
    def error_mutator(queue):
        """累加 attempts 並決定下一個狀態。"""
        entry = find_entry(queue, entry_id)
        if entry is None:
            return None
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_error"] = outcome.get("detail")
        entry["last_diagnostics"] = outcome.get("diagnostics")
        add_cost(entry, outcome)
        if entry["attempts"] >= MAX_ATTEMPTS:
            entry["status"] = "failed"
            entry["finished_at"] = now_iso()
        else:
            entry["status"] = "pending"
        runner_state = queue.setdefault("runner_state", {})
        runner_state["consecutive_failures"] = int(runner_state.get("consecutive_failures", 0)) + 1
        return entry

    entry_after = mutate_queue(config, error_mutator)
    if entry_after is not None and entry_after.get("status") == "failed":
        notify(
            config,
            "module_failed",
            "模組 %s 連續失敗 %d 次" % (entry_id, MAX_ATTEMPTS),
            with_diagnostics_line("最後錯誤: %s" % str(outcome.get("detail"))[:200], outcome.get("diagnostics")),
        )
    return "continue", outcome


def finish_done_entry(config, entry, outcome, pr_error, closing):
    """L1 通過並完成合併後的收尾：整合分支 tip 與 entry 的 done 一次寫回，再更新進度與通知。

    整合分支此時已經推送（不可逆），所以從進入這個函式到 queue 寫回之間不放任何會拋
    例外的讀取：要寫回的 commit 與 R15 hash 由呼叫端在 push 之前用
    collect_closing_data 取好傳進來。tip 與 done 也刻意放在同一次 mutate_queue——
    分兩次寫，兩次之間一中斷就是「tip 已前進、entry 還是 running」。

    這裡不開 PR，也不寫 pr_url：PR 由呼叫端在合併「之前」開（原因見 l1_verify 的
    docstring），連結當下就由 publish_verified_entry 的 record_pr_result 記進 queue。
    這裡只寫 pr_failed（這一輪的 PR 步驟有沒有出錯）；pr_url 留著 queue 裡原本的值——
    這一輪沒拿到連結不代表沒有 PR，上一輪開成功的連結不能被空值蓋掉。

    @param config runner 設定
    @param entry queue 裡的 entry（用到 id）
    @param outcome CLI 呼叫的判讀結果（用到 structured、session_id、cost）
    @param pr_error 這一輪推 entry 分支／開 PR 的錯誤訊息；沒有錯誤為 None
    @param closing collect_closing_data 的回傳值（commit、r15_hashes）
    @return None
    @raises RuntimeError entry 已不在 queue 裡。整合分支已推送、tip 已記錄，但沒有 entry 可以標成 done
    """
    # STEP 01: 要寫回的值全部來自 push 之前取得的 closing；ff-merge 後整合分支的 tip 就是 entry 的 commit
    # （merge_to_integration 在推送前已驗證過兩者一致）
    commit = closing["commit"]
    hashes = closing["r15_hashes"]
    structured = outcome.get("structured") or {}

    def mutator(queue):
        """同一次寫入：整合分支 tip 前進，entry 標成 done 並寫回執行結果。"""
        # tip 先記：遠端確實已經前進，即使 entry 在這期間被人從 queue 移除也一樣要記
        queue["integration_tip_sha"] = commit
        target = find_entry(queue, entry["id"])
        if target is None:
            return None
        target["status"] = "done"
        target["blocked_reason"] = None
        target["last_commit"] = commit
        target["last_session_id"] = outcome.get("session_id")
        target["pr_failed"] = bool(pr_error)
        target["r15_hashes"] = hashes
        target["finished_at"] = now_iso()
        target["last_error"] = None
        add_cost(target, outcome)
        queue.setdefault("runner_state", {})["consecutive_failures"] = 0
        return target

    # STEP 02: 一次寫回（tip + done）。回 None 代表 entry 在合併推送的那幾秒內被人從 queue 移除：
    # tip 已經照記（mutator 沒有拋例外，queue 有寫入），但不能假裝這個 entry 完成了
    written = mutate_queue(config, mutator)
    if written is None:
        raise RuntimeError(
            "整合分支已推送到 %s，但 entry %s 已不在 queue 裡，無法標成 done（執行中重跑過 import-inventory？）"
            % (commit[:10], entry["id"])
        )
    # 通知要顯示的連結以 queue 裡的為準（可能是上一輪開的）
    pr_url = written.get("pr_url")

    # STEP 03: 通知與進度；PR 步驟出錯時分清楚是「沒有 PR」還是「有 PR 但這一輪分支沒推上去」
    if pr_error:
        log_event(config, entry["id"], "pr_failed", detail=pr_error)
        pr_problem = "既有 PR 沒有更新到這一輪的 commit" if pr_url else "PR 未開成功"
        notify(config, "module_blocked", "模組 %s 的 %s" % (entry["id"], pr_problem), pr_error)
    # 從暫停重啟後，第一個模組真的做完才代表先前的暫停原因確實解除了；
    # 比 git 前置一過就先宣稱「已解除」更誠實（R2：只清這裡用的旗標，
    # enter_paused 去重用的 startup_paused_reason 不受影響、留到 process 結束）
    if config.get("resumed_pause_reason"):
        notify(
            config,
            "runner_started",
            "遷移 runner 已續跑",
            "先前的暫停原因 %s 已確認解除（模組 %s 完成）\n整合分支: %s"
            % (config["resumed_pause_reason"], entry["id"], config["integration_branch"]),
        )
        config["resumed_pause_reason"] = None
    notify(
        config,
        "module_done",
        "模組 %s 完成" % entry["id"],
        "commit: %s\nPR: %s\n警告數: %s"
        % (commit[:10], pr_url or "（未開成功）", structured.get("warnings_count", "?")),
    )
    write_progress(config)
    log_event(config, entry["id"], "module_done", session_id=outcome.get("session_id"), cost_usd=outcome.get("cost"))


def handle_checkpoints(config):
    """每個模組完成後檢查是否要開斷點。

    回傳 (should_pause, checkpoint_id)。
    """
    queue = load_queue(config)
    # STEP 01: 先看宣告的斷點
    checkpoint = due_checkpoint(queue)
    if checkpoint is not None:
        opened = open_checkpoint(config, checkpoint["id"])
        if opened and checkpoint.get("mode") == "hard":
            return True, checkpoint["id"]
        return False, checkpoint["id"]

    # STEP 02: 再看自動保險門檻
    needed, detail = auto_checkpoint_needed(config, queue)
    if needed:
        auto_id = "auto-%s" % datetime.datetime.now().strftime("%Y%m%d-%H%M")
        log_event(config, None, "auto_checkpoint", detail=detail)
        open_checkpoint(config, auto_id, auto_title="R18 遷移自動斷點（%s）" % detail)
    return False, None


def wait_for_release(config, checkpoint_id):
    """hard 斷點：停下等人工放行，每 10 分鐘查一次。

    回傳 True 表示已放行，False 表示超過等待上限。
    """
    set_runner_state(config, "paused_for_review", checkpoint_id)
    notify(
        config,
        "paused_for_review",
        "斷點 %s 等待人工檢視" % checkpoint_id,
        "放行指令: python3 runner.py release %s" % checkpoint_id,
    )
    deadline = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=config["max_wait_hours"])
    last_remind = datetime.datetime.now(datetime.timezone.utc)

    # STEP 01: 輪詢 checkpoint 狀態
    while True:
        time.sleep(HARD_CHECKPOINT_POLL_SECONDS)
        try:
            queue = load_queue(config)
        except (OSError, ValueError) as exc:
            log_event(config, None, "release_poll_failed", detail=str(exc))
            return False
        checkpoint = find_checkpoint(queue, checkpoint_id) or {}
        if checkpoint.get("status") in ("released", "merged"):
            set_runner_state(config, "running")
            return True
        now = datetime.datetime.now(datetime.timezone.utc)
        # STEP 02: 定時重複提醒
        if (now - last_remind).total_seconds() >= config["notify_pause_remind_hours"] * 3600:
            notify(
                config,
                "paused_for_review",
                "斷點 %s 仍在等待" % checkpoint_id,
                "放行指令: python3 runner.py release %s" % checkpoint_id,
            )
            last_remind = now
        if now > deadline:
            return False
        log_event(config, None, "heartbeat", detail={"waiting_release": checkpoint_id})


def maybe_daily_digest(config):
    """到了設定時間就送一則每日摘要。"""
    # STEP 01: 解析設定的時間字串
    parts = config["notify_daily_digest"].split(":")
    if len(parts) != 2:
        return
    hour = to_int(parts[0], -1)
    minute = to_int(parts[1], -1)
    if hour < 0 or minute < 0:
        return
    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")
    if (now.hour, now.minute) < (hour, minute):
        return

    # STEP 02: 今天已送過就不重送（記在 runner_state.last_digest_date）
    queue = load_queue(config)
    if queue.get("runner_state", {}).get("last_digest_date") == today:
        return
    counts = count_status(queue)

    def mutator(queue_data):
        """記下今天已送過摘要。"""
        queue_data.setdefault("runner_state", {})["last_digest_date"] = today
        return today

    mutate_queue(config, mutator)
    notify(
        config,
        "daily_digest",
        "每日進度摘要",
        "完成: %d\n等待中: %d\n卡住: %d\n失敗: %d"
        % (counts.get("done", 0), counts.get("pending", 0), counts.get("blocked", 0), counts.get("failed", 0)),
    )


def next_call_number(config, entry):
    """本次呼叫的序號（sessions/<entry>-<n>.* 與診斷包名稱的 n）：單調遞增，不跟 queue.attempts 綁死。

    queue.attempts 只在 error／timeout 累加、unblock 會歸零；序號若直接用 attempts+1，
    unblock 後重跑會回頭覆寫 sessions/<entry>-1.*，diagnose 也會把最大編號誤當最新一次
    （fresh-context 驗收抓到）。改取「attempts+1」與「sessions/ 內最大編號+1」的較大者。
    """
    from_queue = int(entry.get("attempts", 0)) + 1
    from_files = (diagnostics.latest_attempt(config["state_dir"], entry["id"]) or 0) + 1
    return max(from_queue, from_files)


def publish_verified_entry(config, entry, outcome, attempt):
    """L1 檢查通過之後的發佈段：取收尾資料 → 開 PR → 合併並推送 → 寫回 done。

    順序就是這個函式存在的理由，兩條不變量：
    (1) PR 要在 ff-merge 之前開——合併之後 entry 分支與整合分支沒有差異，PR 開不成
        （見 l1_verify 的 docstring）。
    (2) 這一段有三個外部副作用：推 entry 分支、開 PR、推整合分支。前兩個可以重做——
        分支可以重推，開過的 PR 連結記在 queue 裡、重跑時沿用；只有整合分支的 push
        重做不了（重啟後 l1_verify 會看到 entry 分支已經沒有新 commit）。所以任何可能
        失敗的讀取都排在它之前（collect_closing_data），它之後到 queue 寫回之間只有
        一筆 log_event（寫檔失敗只印警告、不往外拋）與 finish_done_entry 的一次
        mutate_queue。

    pr_url 只有一個寫入點：開 PR 之後、合併之前的 record_pr_result。不等到收尾才寫，
    之後的合併若失敗，這個 entry 重跑時 push_branch_and_open_pr 才知道 PR 已經存在；
    收尾不再碰 pr_url，這一輪沒拿到連結（例如 entry 分支推送失敗）就不會把上一輪記下
    的連結蓋掉。同一次寫入順便確認 entry 還在 queue 裡——import-inventory 可以在
    runner 執行中重跑，盤點檔拿掉的 entry 會從 queue 消失；那種情況要在合併之前就
    停下來，不是寫不進去還照樣把它推進整合分支。

    @param config runner 設定
    @param entry queue 裡的 entry
    @param outcome CLI 呼叫的判讀結果（交給 finish_done_entry 寫回）
    @param attempt 這次呼叫的序號（凍結診斷包用）
    @return None 表示主迴圈繼續；否則為 runner 的 exit code（進入暫停）
    @raises RuntimeError entry 已不在 queue 裡（合併前發現：整合分支未動；合併後發現：見 finish_done_entry）
    """
    entry_id = entry["id"]
    # STEP 01: 收尾要寫回的資料先取好（會拋例外的讀取全部在 push 之前）
    closing = collect_closing_data(config, entry)

    # STEP 02: 開 PR——entry 分支這時還沒併進整合分支，diff 是真的
    pr_url, pr_error = push_branch_and_open_pr(config, entry)

    def record_pr_result(queue):
        """合併前的唯一一次寫入：確認 entry 還在，這一輪有拿到 PR 連結就記下來。"""
        target = find_entry(queue, entry_id)
        if target is None:
            raise RuntimeError(
                "entry %s 已不在 queue 裡（執行中重跑過 import-inventory？），停止合併；整合分支未動。PR: %s"
                % (entry_id, pr_url or "（這一輪沒有開成功）")
            )
        if pr_url:
            target["pr_url"] = pr_url
        return target

    # STEP 03: 落盤（例外發生在 mutator 內，queue 不會被寫入）
    mutate_queue(config, record_pr_result)

    # STEP 04: 合併並推送；成功就收尾
    merge_result, merge_detail = merge_to_integration(config, entry, closing["commit"])
    log_event(config, entry_id, "merge_result", detail={"result": merge_result, "detail": merge_detail})
    if merge_result == "done":
        finish_done_entry(config, entry, outcome, pr_error, closing)
        return None

    # STEP 05: 合併失敗——PR 若已經開成功，分支已經真的推上去了，把連結留在
    # 暫停原因裡供人工接手，不能因為合併失敗就假裝沒開過 PR；PR 步驟自己也出錯的話同樣要留下來
    # （收尾不會執行，這裡不記，pr_error 就不會出現在任何地方，只剩合併的那個錯誤）。
    # 要在凍結診斷包之前記：包裡的 detail 與事件切片是凍結當下的快照，操作者帶走的是那個包
    if pr_error:
        log_event(config, entry_id, "pr_failed", detail=pr_error)
        merge_detail = "%s（PR 步驟也失敗: %s）" % (merge_detail, pr_error)
    bundle = freeze_entry_bundle(config, entry_id, attempt, "l1_%s" % merge_result, merge_detail)
    if pr_url:
        merge_detail = "%s（PR: %s）" % (merge_detail, pr_url)
    if bundle:
        merge_detail = "%s（entry 診斷: %s）" % (merge_detail, bundle)
    # STEP 06: ff-merge 後 HEAD 不符（本機整合分支曾停在非預期 commit 上）→ 鎖定，不能只是一般暫停，
    # 退回成功與否都一樣：不符的前提就是有別的東西在改 repo，一般暫停 launchd 幾分鐘後就重啟、
    # 把同一個 entry 放回 pending 重試，多半再次不符、同原因重複暫停不再通知，無上限地燒額度；
    # 退不回去的還多一層——下一個 entry 會從那個 commit 切分支、最後把它推上去（module_preflight
    # 對本機領先會擋，但那是第二道防線）。退不回去的處理後要 unblock --integration-tip 與 --runner——
    # 指示放最前面：通知會截尾，尾端的指示送不到，人只看到鎖定前綴寫死的「unblock --runner」就照做
    locked = merge_result in HOLD_MERGE_RESULTS
    if merge_result == "integration_unrecovered":
        merge_detail = "先照下面說明對齊本機、處理寫入者，再 unblock --integration-tip 與 --runner。%s" % merge_detail
    # STEP 07: 推送失敗本機已退回、可重試——但「持續推不上去」（分支保護、憑證過期、遠端 hook）沒有煞車：
    # 重啟後前置作業放行、entry 放回 pending、重跑一次完整 CLI 呼叫、再推再失敗，而且同原因重複暫停不通知。
    # 帶簽名讓 enter_paused 在連續第二次就鎖定（既有機制，unblock --runner 解除）
    signature = PUSH_FAILED_SIGNATURE if merge_result == "integration_push_failed" else None
    return enter_paused(config, "integration_diverged", merge_detail, signature=signature, force_hold=locked)


def process_one_entry(config, entry):
    """完整處理一個 entry：呼叫 → 判讀 → 凍結證據 → L1 → 收尾。

    回傳 (exit_code_or_None)：非 None 代表 runner 應該退出。
    """
    entry_id = entry["id"]
    attempt = next_call_number(config, entry)
    # 子行程 log 與診斷包命名用的模組脈絡
    config["current_entry"] = entry_id
    config["current_attempt"] = attempt

    # STEP 01: 標記 running
    def start_mutator(queue):
        """把 entry 標成 running。"""
        target = find_entry(queue, entry_id)
        if target is not None:
            target["status"] = "running"
            target["started_at"] = now_iso()
        return target

    mutate_queue(config, start_mutator)
    log_event(
        config,
        entry_id,
        "module_started",
        attempt=attempt,
        detail={"branch": entry.get("branch"), "repo_head": git_out(config, "rev-parse", "HEAD") or None},
    )

    # STEP 02: 呼叫 CLI（已在分支上），並保存原始輸出
    resume = bool(entry.get("last_session_id")) or os.path.exists(
        state_path(config, "%s-progress.md" % entry_id)
    )
    call_result = call_claude(config, entry, attempt, resume)
    save_session_output(config, entry, attempt, call_result)
    outcome = judge_outcome(config, call_result)
    log_event(
        config,
        entry_id,
        "cli_outcome",
        attempt=attempt,
        duration_s=call_result["duration_s"],
        cost_usd=outcome.get("cost"),
        session_id=outcome.get("session_id"),
        detail={
            "kind": outcome["kind"],
            "detail": str(outcome.get("detail"))[:300],
            "terminal_reason": outcome.get("terminal_reason"),
            "num_turns": outcome.get("num_turns"),
            "permission_denials": outcome.get("denials"),
            "stream": diagnostics.relpath_in(config["state_dir"], call_result["stream_path"]),
        },
    )

    # STEP 03: 失敗類判讀先凍結證據——要在寫回 queue、發通知之前，通知才附得上診斷包路徑
    if outcome["kind"] in FREEZE_OUTCOME_KINDS:
        outcome["diagnostics"] = freeze_entry_bundle(config, entry_id, attempt, outcome["kind"], outcome.get("detail"))

    # STEP 04: 依判讀結果決定後續；寫回 queue 後把最新 entry 狀態補進診斷包
    action, payload = apply_outcome(config, entry_id, outcome)
    refresh_bundle_snapshot(config, entry_id, outcome.get("diagnostics"))
    if action == "pause":
        reason, detail = payload
        if outcome.get("diagnostics"):
            detail = "%s（entry 診斷: %s）" % (detail, outcome["diagnostics"])
        return enter_paused(config, reason, detail)
    if action == "wait":
        long_wait = bool(payload.get("long_wait"))
        resets_at = payload.get("resets_at")
        reason = payload.get("detail") or "額度"
        if not wait_until(config, resets_at, reason, long_wait):
            notify(config, "runner_crashed", "等待額度超過上限", "原因: %s" % reason)
            return EXIT_PAUSED

        def back_to_pending(queue):
            """等完額度把 entry 放回 pending，attempts 不變。"""
            target = find_entry(queue, entry_id)
            if target is not None and target.get("status") == "waiting_quota":
                target["status"] = "pending"
            return target

        mutate_queue(config, back_to_pending)
        return None
    if action != "verify":
        return None

    # STEP 05: L1 檢查（commit 存在／build／smoke／秘密掃描，不含合併）
    result, detail = l1_verify(config, entry)
    log_event(config, entry_id, "l1_result", detail={"result": result, "detail": detail})
    if result == "verified":
        # STEP 05.01: 檢查通過 → 發佈段（取收尾資料 → 開 PR → 合併 → 寫回 done），順序不變量見該函式
        return publish_verified_entry(config, entry, outcome, attempt)

    # STEP 06: L1 檢查沒過一律先凍結——skill 回報 done 但 runner 自驗失敗，stream 是找原因的依據
    bundle = freeze_entry_bundle(config, entry_id, attempt, "l1_%s" % result, detail)
    if result in ("build_unverified", "secret_detected"):

        def blocked_mutator(queue):
            """L1 失敗 → blocked。"""
            target = find_entry(queue, entry_id)
            if target is not None:
                target["status"] = "blocked"
                target["blocked_reason"] = result
                target["last_error"] = detail
                target["last_diagnostics"] = bundle
                target["finished_at"] = now_iso()
            return target

        mutate_queue(config, blocked_mutator)
        refresh_bundle_snapshot(config, entry_id, bundle)
        notify(
            config,
            "module_blocked",
            "模組 %s 未通過 L1（%s）" % (entry_id, result),
            with_diagnostics_line(detail, bundle),
        )
        return None

    # STEP 07: 其餘（沒有 commit）視為 error，累加 attempts
    apply_outcome(
        config,
        entry_id,
        {"kind": "error", "detail": detail, "session_id": outcome.get("session_id"), "diagnostics": bundle},
    )
    refresh_bundle_snapshot(config, entry_id, bundle)
    return None


def cmd_run(config, args):
    """run 子命令：主迴圈。"""
    # STEP 01: 鎖物件先建好（建構子只記路徑，不開檔、不取鎖），except／finally 用 lock.acquired
    # 分辨「現在有沒有持鎖」；release() 在沒取到鎖時本來就什麼都不做
    lock = ProcessLock(state_path(config, "runner.lock"))
    try:
        # STEP 01.01: 裝 SIGTERM/SIGHUP/SIGINT handler，讓 launchd 停止服務時也能走到下面的清理路徑，
        # 不是只有 Ctrl-C 才會被妥善處理。handler 一裝好，訊號就會變成 ShutdownSignal
        # 從任何一行冒出來（包括安裝函式自己還沒返回的那一刻），所以安裝動作本身也要在 try 裡面
        install_shutdown_handlers()
        # STEP 01.02: 必填檢查
        if not require_config(config, ["repo_dir", "branch_user", "has_oauth_token"]):
            return EXIT_PREFLIGHT
        if config["notify_channel"] == "line" and not (
            os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") and os.environ.get("LINE_NOTIFY_TARGET_ID")
        ):
            print("錯誤：NOTIFY_CHANNEL=line 但缺少 LINE 憑證或推播對象設定", file=sys.stderr)
            return EXIT_PREFLIGHT
        # STEP 01.03: 取鎖
        ensure_state_dir(config)
        if not lock.acquire():
            print("錯誤：已有另一個 runner 在執行（runner.lock 被持有）", file=sys.stderr)
            return EXIT_LOCKED

        processed = 0
        stalled_notified = False
        previous_lock_hash = lockfile_hash(config)

        # STEP 01.04: 上一輪同簽名 crash 兩次（或殘留行程類例外第一次）→ hold；人工 unblock --runner 之前靜默退出，
        # 放在 pre-flight 之前是為了連認證 smoke 那次 CLI 呼叫都省掉（launchd 每 ThrottleInterval 重啟一次）
        try:
            early_state = load_queue(config).get("runner_state", {})
        except (FileNotFoundError, OSError, ValueError):
            early_state = {}
        if early_state.get("hold"):
            log_event(
                config,
                None,
                "hold_active",
                detail={"reason": early_state.get("reason"), "signature": early_state.get("crash_signature")},
            )
            return EXIT_PAUSED

        # STEP 02: pre-flight
        code = preflight(config)
        if code != 0:
            return code
        # STEP 02.01: 記住「本次是不是從暫停狀態被 launchd 重啟的」
        # resumed_pause_reason 只用來控制「續跑通知」何時發送，第一個模組真的 done 時
        # 在 finish_done_entry 被清掉；startup_paused_reason 是 enter_paused 去重用的依據，
        # 整個 process 生命週期不清除（見 R2：模組執行中途才觸發的暫停原因，
        # 不能靠會被提早清掉的旗標判斷是否重複）；startup_crash_signature 同理，給 crash 去重用
        queue = load_queue(config)
        previous_state = queue.get("runner_state", {})
        if previous_state.get("state") == "paused":
            config["resumed_pause_reason"] = previous_state.get("reason")
            config["startup_paused_reason"] = previous_state.get("reason")
            config["startup_crash_signature"] = previous_state.get("crash_signature")
        set_runner_state(config, "running")

        # STEP 02.02: 環境指紋——寫進 runner_started 事件與之後每個診斷包，跨版本比對錯誤時才知道是哪版產生的
        config["fingerprint"] = environment_fingerprint(config)
        log_event(config, None, "runner_started", detail=config["fingerprint"])

        # STEP 02.03: 全新啟動才立刻通知；從暫停重啟的要等第一個模組真的做完才發（見 finish_done_entry）
        if not config.get("resumed_pause_reason"):
            notify(
                config,
                "runner_started",
                "遷移 runner 已啟動",
                "整合分支: %s\n基線 SHA: %s\n待處理: %d\nskill %s / CLI %s"
                % (
                    config["integration_branch"],
                    str(queue.get("integration_tip_sha"))[:10],
                    count_status(queue).get("pending", 0),
                    config["fingerprint"].get("skill_version"),
                    config["fingerprint"].get("cli_version"),
                ),
            )

        # STEP 03: 主迴圈
        while True:
            if args.max_modules and processed >= args.max_modules:
                log_event(config, None, "max_modules_reached", detail={"processed": processed})
                set_runner_state(config, "idle")
                return EXIT_OK

            maybe_daily_digest(config)
            queue = load_queue(config)

            # STEP 03.01: 熔斷檢查
            failures = int(queue.get("runner_state", {}).get("consecutive_failures", 0))
            if failures >= config["circuit_breaker_n"]:
                return enter_paused(config, "circuit_breaker", "連續 %d 個模組失敗" % failures)

            # STEP 03.02: 上一輪在 hard 斷點等人放行時被停掉（斷點停在 opened）：先回到等待，不能先處理下一個模組——
            # 模組完成後的斷點檢查只看 pending 的斷點，不在這裡補的話重啟就繞過人工閘門
            interrupted_checkpoint = opened_hard_checkpoint(queue)
            if interrupted_checkpoint is not None:
                if not wait_for_release(config, interrupted_checkpoint):
                    return enter_paused(config, "paused_for_review", "斷點 %s 等待逾時" % interrupted_checkpoint)
                set_runner_state(config, "running")
                continue

            # STEP 03.03: 取件
            ready = eligible_entries(queue)
            if not ready:
                counts = count_status(queue)
                if counts.get("done", 0) == len(queue.get("modules", [])) and queue.get("modules"):
                    notify(config, "queue_complete", "佇列全部完成", "共 %d 個模組" % counts.get("done", 0))
                    set_runner_state(config, "idle")
                    return EXIT_OK
                if not stalled_notified:
                    notify(
                        config,
                        "queue_stalled",
                        "佇列停滯",
                        "沒有可執行的模組；blocked %d / failed %d"
                        % (counts.get("blocked", 0), counts.get("failed", 0)),
                    )
                    stalled_notified = True
                if args.max_modules:
                    return EXIT_OK
                log_event(config, None, "queue_stalled_wait", detail=counts)
                time.sleep(STALLED_RECHECK_SECONDS)
                continue

            entry = ready[0]
            # 從這裡起的 git 前置／依賴安裝子行程 log 都掛在這個 entry 名下（序號與 process_one_entry 同一算法）
            config["current_entry"] = entry["id"]
            config["current_attempt"] = next_call_number(config, entry)

            # STEP 03.04: 額度 pre-flight
            snapshot = quota_snapshot(config)
            should_wait, reason, resets_at = quota_blocks_start(config, snapshot)
            if should_wait:
                if not wait_until(config, resets_at, reason, "seven_day" in reason):
                    notify(config, "runner_crashed", "等待額度超過上限", "原因: %s" % reason)
                    return EXIT_PAUSED
                continue

            # STEP 03.05: git 前置。本機整合分支領先遠端的那一種要鎖定：一般暫停 launchd 幾分鐘後重啟、
            # 同原因重複暫停不再通知，而本機領先不會自己消失
            ok, pause_reason, detail = module_preflight(config, queue)
            if not ok:
                return enter_paused(config, pause_reason, detail, force_hold=pause_reason == LOCAL_AHEAD_REASON)

            # STEP 03.06: 依賴安裝
            # （原本這裡會在 git 前置一過就先發「已續跑」通知，但那時模組還沒真的跑，
            #   像 auth_expired 這類原因要等模組真的呼叫過 CLI 才知道是否還在發生；
            #   改成只在第一個模組真的 done 之後才發，見 finish_done_entry。R2）
            ok, previous_lock_hash, detail = install_deps_if_lockfile_changed(config, previous_lock_hash)
            if not ok:
                return enter_paused(config, "deps_install_failed", detail)

            # STEP 03.07: 切分支後才呼叫 skill
            ok, detail = prepare_branch(config, entry)
            if not ok:
                return enter_paused(config, "integration_dirty", detail)

            exit_code = process_one_entry(config, entry)
            processed += 1
            if exit_code is not None:
                return exit_code

            # STEP 03.08: 斷點檢查
            should_pause, checkpoint_id = handle_checkpoints(config)
            if should_pause:
                if not wait_for_release(config, checkpoint_id):
                    return enter_paused(config, "paused_for_review", "斷點 %s 等待逾時" % checkpoint_id)
                set_runner_state(config, "running")
    except (KeyboardInterrupt, ShutdownSignal):
        # 取鎖前就被要求停止：還沒動過 queue（狀態目錄與 runner.lock 檔可能已由 ensure_state_dir／
        # acquire 建好，那兩樣留著無害），安靜結束即可；取鎖後才記事件。兩種都是正常停止，回 EXIT_OK、不走 crash 流程（不凍結診斷包、不通知）。
        # 退出碼擋不住重啟：plist 是無條件 KeepAlive，job 還載入著就會再拉起 runner，
        # 只有 launchctl unload 才會真的停；KeyboardInterrupt 只會在 handler 裝好之前出現
        if lock.acquired:
            log_event(config, None, "interrupted", detail="收到中斷訊號")
        return EXIT_OK
    except Exception as exc:
        # 沒持鎖時不得走 crash 流程：handle_runner_crash 會寫 queue 與狀態目錄，而此刻
        # 可能有另一個 runner 正持鎖在跑。取鎖前的例外維持原行為，原樣往外拋
        if not lock.acquired:
            raise
        # 未預期例外：traceback 落檔 + 診斷包 + paused（去重、同簽名兩次即 hold），不 raise、不靜默
        return handle_runner_crash(config, exc)
    finally:
        lock.release()


# ================================================================ 其他子命令


def cmd_status(config, args):
    """status 子命令：印出佇列統計與 runner 狀態。"""
    # STEP 01: 讀 queue；不存在時給可行動訊息而不是 traceback
    try:
        queue = load_queue(config)
    except (FileNotFoundError, ValueError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT

    # STEP 02: 印統計
    counts = count_status(queue)
    runner_state = queue.get("runner_state", {})
    print("狀態目錄: %s" % config["state_dir"])
    print("整合分支: %s（tip 記錄 %s）" % (queue.get("integration_branch"), str(queue.get("integration_tip_sha"))[:12]))
    print(
        "runner: %s%s（pid %s @ %s，自 %s）"
        % (
            runner_state.get("state", "idle"),
            "（%s）" % runner_state["reason"] if runner_state.get("reason") else "",
            runner_state.get("pid"),
            runner_state.get("host"),
            runner_state.get("since"),
        )
    )
    print("連續失敗: %s" % runner_state.get("consecutive_failures", 0))
    print("模組總數: %d" % len(queue.get("modules", [])))
    for name in ["done", "running", "pending", "waiting_quota", "blocked", "failed"]:
        print("  %-14s %d" % (name, counts.get(name, 0)))

    # STEP 03: 印斷點與待人工項目
    print("斷點:")
    for checkpoint in queue.get("checkpoints", []):
        print(
            "  %-10s wave %-3s %-6s %-8s %s"
            % (
                checkpoint.get("id"),
                (checkpoint.get("after") or {}).get("wave"),
                checkpoint.get("mode"),
                checkpoint.get("status"),
                checkpoint.get("pr_url") or "",
            )
        )
    if args.verbose:
        for entry in queue.get("modules", []):
            if entry.get("status") in ("blocked", "failed"):
                print(
                    "  ! %s %s: %s%s"
                    % (
                        entry["id"],
                        entry.get("status"),
                        entry.get("blocked_reason") or entry.get("last_error"),
                        "\n      診斷: %s" % entry["last_diagnostics"] if entry.get("last_diagnostics") else "",
                    )
                )
        if runner_state.get("hold"):
            print("  ! runner hold=true（crash_signature %s）：`unblock --runner` 解除" % runner_state.get("crash_signature"))
    return EXIT_OK


def cmd_release(config, args):
    """release 子命令：放行一個等待人工檢視的斷點。"""

    def mutator(queue):
        """把 checkpoint 標成 released。"""
        checkpoint = find_checkpoint(queue, args.checkpoint_id)
        if checkpoint is None:
            return None
        if checkpoint.get("status") not in ("opened", "failed"):
            return {"error": "目前狀態是 %s，不需要放行" % checkpoint.get("status")}
        checkpoint["status"] = "released"
        return checkpoint

    # STEP 01: 在同一把資料鎖下修改
    try:
        result = mutate_queue(config, mutator)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    if result is None:
        print("錯誤：找不到斷點 %s" % args.checkpoint_id, file=sys.stderr)
        return EXIT_USAGE
    if isinstance(result, dict) and result.get("error"):
        print("錯誤：%s" % result["error"], file=sys.stderr)
        return EXIT_USAGE
    log_event(config, None, "checkpoint_released", detail={"checkpoint": args.checkpoint_id})
    print("已放行斷點 %s，runner 會在下一次輪詢時續跑" % args.checkpoint_id)
    return EXIT_OK


def unblock_integration_tip(config):
    """把記錄的整合分支 tip 重新對齊遠端現況，並解除 integration 類的暫停（INTEGRATION_PAUSE_REASONS）。

    用於「有人直接推了整合分支、人工確認過內容沒問題」之後讓 runner 續跑。只清暫停原因、
    不清鎖定（hold）：兩者是兩件事，hold 是「人要確認過才能繼續」，由 unblock --runner 解除。
    hold 還在時不能印「下次啟動會繼續」——那不是真的，runner 會在 pre-flight 之前靜默退出。
    """
    # STEP 01: 先取遠端最新狀態
    code, _out, err = git(config, "fetch", "origin")
    if code != 0:
        print("錯誤：git fetch 失敗: %s" % err.strip()[-200:], file=sys.stderr)
        return EXIT_PREFLIGHT
    remote_tip = git_out(config, "rev-parse", "origin/%s" % config["integration_branch"])
    if not remote_tip:
        print("錯誤：讀不到 origin/%s 的 tip" % config["integration_branch"], file=sys.stderr)
        return EXIT_PREFLIGHT

    # STEP 02: 寫回新的基線並清掉對應的暫停狀態；回報 hold 是否還在
    def mutator(queue):
        """更新 integration_tip_sha，必要時解除暫停；回傳 hold 是否仍為真。"""
        queue["integration_tip_sha"] = remote_tip
        runner_state = queue.setdefault("runner_state", {})
        if runner_state.get("state") == "paused" and runner_state.get("reason") in INTEGRATION_PAUSE_REASONS:
            runner_state["state"] = "idle"
            runner_state["reason"] = None
        return bool(runner_state.get("hold"))

    try:
        hold_remains = mutate_queue(config, mutator)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    log_event(config, None, "integration_tip_rebaselined", detail={"sha": remote_tip, "hold_remains": hold_remains})
    # STEP 03: 說實話——hold 還在就不會續跑
    if hold_remains:
        print(
            "已把整合分支基線對齊到 %s；runner 仍處於鎖定（hold），還要執行 `runner.py unblock --runner` 才會續跑"
            % remote_tip[:12]
        )
    else:
        print("已把整合分支基線對齊到 %s；下次啟動會從這個 SHA 繼續" % remote_tip[:12])
    return EXIT_OK


def unblock_runner(config):
    """解除 runner 級鎖定（hold）與 runner_crashed 暫停，讓下次啟動可以續跑。

    只清 hold 與 crash 類的暫停原因；integration 類的暫停原因（INTEGRATION_PAUSE_REASONS）
    留著，由 unblock --integration-tip 處理——它還會把記錄的 tip 對齊遠端。看到那類原因還在
    就提醒：只跑這一個的話，遠端整合分支若有變動，下次啟動會再次暫停，而且同原因重複不通知。
    """

    def mutator(queue):
        """清掉 hold 與 crash 簽名；若暫停原因就是 crash，一併回 idle。回傳 (原本是否 hold, 留下的暫停原因)。"""
        runner_state = queue.setdefault("runner_state", {})
        was_hold = bool(runner_state.get("hold"))
        runner_state["hold"] = False
        runner_state["crash_signature"] = None
        if runner_state.get("state") == "paused" and runner_state.get("reason") == CRASH_REASON:
            runner_state["state"] = "idle"
            runner_state["reason"] = None
        remaining = runner_state.get("reason") if runner_state.get("state") == "paused" else None
        return was_hold, remaining

    # STEP 01: 在同一把資料鎖下修改
    try:
        was_hold, remaining_reason = mutate_queue(config, mutator)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    log_event(config, None, "runner_unblocked", detail={"was_hold": was_hold, "remaining_reason": remaining_reason})
    # STEP 02: integration 類的暫停原因不歸這裡清，提醒另一個子命令；這時不能說「下次啟動會續跑」——
    # 本機沒對齊的話下次啟動會再鎖一次
    hold_note = "已解除 runner 鎖定（hold %s → false）" % ("true" if was_hold else "false")
    if remaining_reason in INTEGRATION_PAUSE_REASONS:
        print(
            "%s；暫停原因 %s 仍在：先確認本機整合分支已對齊遠端（否則下次啟動會再次鎖定），"
            "遠端整合分支若有變動且你已審閱過那些 commit，再執行 `runner.py unblock --integration-tip` 重新對齊記錄的 tip"
            "（不跑的話遠端有變動時下次啟動會再次暫停，且同原因不重複通知）" % (hold_note, remaining_reason)
        )
    else:
        print("%s，下次啟動會續跑" % hold_note)
    return EXIT_OK


def cmd_unblock(config, args):
    """unblock 子命令：把 failed / blocked 的 entry 放回 pending、重新對齊整合分支基線、或解除 runner hold。"""
    # STEP 01: 三種模式擇一
    if args.integration_tip:
        return unblock_integration_tip(config)
    if args.runner:
        return unblock_runner(config)
    if not args.entry_id:
        print("錯誤：請給 entry id，或用 --integration-tip / --runner", file=sys.stderr)
        return EXIT_USAGE

    def mutator(queue):
        """重設 entry 狀態與計數。"""
        entry = find_entry(queue, args.entry_id)
        if entry is None:
            return None
        if entry.get("status") not in ("failed", "blocked"):
            return {"error": "目前狀態是 %s，不需要解鎖" % entry.get("status")}
        entry["status"] = "pending"
        entry["blocked_reason"] = None
        entry["attempts"] = 0
        entry["last_error"] = None
        runner_state = queue.setdefault("runner_state", {})
        runner_state["consecutive_failures"] = 0
        # 熔斷造成的暫停一併解除，讓下次重啟可以續跑
        if runner_state.get("state") == "paused" and runner_state.get("reason") == "circuit_breaker":
            runner_state["state"] = "idle"
            runner_state["reason"] = None
        return entry

    # STEP 02: 在同一把資料鎖下修改
    try:
        result = mutate_queue(config, mutator)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    if result is None:
        print("錯誤：找不到 entry %s" % args.entry_id, file=sys.stderr)
        return EXIT_USAGE
    if isinstance(result, dict) and result.get("error"):
        print("錯誤：%s" % result["error"], file=sys.stderr)
        return EXIT_USAGE
    log_event(config, None, "entry_unblocked", detail={"entry": args.entry_id})
    print("已把 %s 放回 pending（attempts 歸零）" % args.entry_id)
    return EXIT_OK


def cmd_render_progress(config, args):
    """render-progress 子命令：重新產生 PROGRESS.md 或某個斷點的 PR 內文。"""
    # STEP 01: 讀 queue
    try:
        queue = load_queue(config)
    except (FileNotFoundError, ValueError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    # STEP 02: 指定斷點時印到 stdout，否則寫檔
    if args.checkpoint_id:
        print(render_progress_text(config, queue, checkpoint_id=args.checkpoint_id))
        return EXIT_OK
    path = write_progress(config, queue)
    print("已更新 %s" % path)
    return EXIT_OK


def cmd_diagnose(config, args):
    """diagnose 子命令：對指定 entry（或全部 blocked/failed、或 runner 級）產診斷包，印出路徑。

    只讀 queue、不寫；產出全部在 diagnostics/ 底下。帶 --tar 時另打成 .tar.gz 方便 scp。
    """
    # STEP 01: 參數擇一
    if not args.runner and not args.all_failed and not args.entry_id:
        print("錯誤：請給 entry id，或用 --all-failed / --runner", file=sys.stderr)
        return EXIT_USAGE
    ensure_state_dir(config)
    config["fingerprint"] = environment_fingerprint(config)
    bundles = []

    # STEP 02: runner 級
    if args.runner:
        relative = freeze_runner_bundle(config, "manual", "手動執行 diagnose --runner")
        if relative:
            bundles.append(relative)

    # STEP 03: entry 級——attempt 預設取 sessions/ 內最大編號（blocked 不累加 attempts，不能從 queue 推）
    if args.entry_id or args.all_failed:
        try:
            queue = load_queue(config)
        except (FileNotFoundError, ValueError) as exc:
            print("錯誤：%s" % exc, file=sys.stderr)
            return EXIT_PREFLIGHT
        targets = []
        if args.entry_id:
            entry = find_entry(queue, args.entry_id)
            if entry is None:
                print("錯誤：找不到 entry %s" % args.entry_id, file=sys.stderr)
                return EXIT_USAGE
            targets.append(entry)
        if args.all_failed:
            for entry in queue.get("modules", []):
                if entry.get("status") in ("blocked", "failed") and entry not in targets:
                    targets.append(entry)
        for entry in targets:
            attempt = (
                args.attempt
                or diagnostics.latest_attempt(config["state_dir"], entry["id"])
                or int(entry.get("attempts", 0)) + 1
            )
            relative = freeze_entry_bundle(
                config,
                entry["id"],
                attempt,
                "manual",
                entry.get("last_error") or entry.get("blocked_reason") or "手動執行 diagnose",
            )
            if relative:
                bundles.append(relative)

    # STEP 04: 輸出（可選打包）
    if not bundles:
        print("錯誤：沒有產生任何診斷包（見 runner.log.jsonl 的 diagnostics_failed 事件）", file=sys.stderr)
        return EXIT_PREFLIGHT
    for relative in bundles:
        full = state_path(config, relative)
        print(diagnostics.write_tarball(full) if args.tar else full)
    return EXIT_OK


# ================================================================ import-inventory


def detect_cycle(entries):
    """用 DFS 找 depends_on 的環。

    回傳第一個找到的環（id 串列）；沒有環回 None。
    """
    # STEP 01: 建鄰接表
    graph = {entry["id"]: [dep for dep in (entry.get("depends_on") or [])] for entry in entries}
    visiting = set()
    visited = set()
    stack = []

    def visit(node):
        """深度優先走訪，遇到還在堆疊上的節點就是環。"""
        if node in visited:
            return None
        if node in visiting:
            index = stack.index(node) if node in stack else 0
            return stack[index:] + [node]
        visiting.add(node)
        stack.append(node)
        for neighbour in graph.get(node, []):
            if neighbour not in graph:
                continue
            found = visit(neighbour)
            if found:
                return found
        stack.pop()
        visiting.discard(node)
        visited.add(node)
        return None

    # STEP 02: 對每個節點各走一次
    for entry_id in graph:
        found = visit(entry_id)
        if found:
            return found
    return None


def count_lines(path):
    """數一個檔案有幾行；讀不到時回 0。"""
    try:
        with open(path, "rb") as handle:
            return sum(1 for _line in handle)
    except OSError:
        return 0


def prefix_collisions(entries):
    """檢查 route.fe_config_prefix 的前綴碰撞。

    規則（決策 26）：A 是 B 的前綴且 A 不以 `$` 結尾就會誤命中，必須列出。
    """
    # STEP 01: 收集所有非空前綴
    items = []
    for entry in entries:
        prefix = ((entry.get("route") or {}).get("fe_config_prefix") or "").strip()
        if prefix:
            items.append((entry["id"], prefix))
    # STEP 02: 兩兩比對
    collisions = []
    for left_id, left in items:
        for right_id, right in items:
            if left_id == right_id or left == right:
                continue
            if right.startswith(left) and not left.endswith("$"):
                collisions.append(
                    "前綴碰撞：`%s` 的 `%s` 是 `%s` 的 `%s` 的前綴且未加 $ 結尾錨"
                    % (left_id, left, right_id, right)
                )
    return collisions


def build_branch_name(config, entry):
    """依樣板產生頁面分支名稱：<jira>/refactor/<BRANCH_USER>/<entry-id>。"""
    jira = (entry.get("jira") or "").strip()
    prefix = "%s/" % jira if jira else ""
    return "%srefactor/%s/%s" % (prefix, config["branch_user"], entry["id"])


def is_tab_reuse_entry(entry):
    """判斷 entry 是否為 tab-reuse entry（唯一可以有空 `r15_paths` 的情況）。

    三個條件同時成立才算：
    1. `type` 為 `page`（缺省視為 `page`）
    2. `route.kind` 為 `sub`
    3. `shared_deps` 恰一筆，且該筆的 `r18_equivalent` 非 `None`
    """
    if entry.get("type", "page") != "page":
        return False
    route = entry.get("route") or {}
    if route.get("kind") != "sub":
        return False
    shared_deps = entry.get("shared_deps") or []
    if len(shared_deps) != 1:
        return False
    return shared_deps[0].get("r18_equivalent") is not None


def cmd_import_inventory(config, args):
    """import-inventory 子命令：把盤點 JSON 轉成 queue.json。

    只做格式轉換與驗證，不推導任何依賴關係；錯誤一次全列出再退出。
    """
    # STEP 01: 必填設定與輸入檔
    if not require_config(config, ["repo_dir", "branch_user"]):
        return EXIT_PREFLIGHT
    ensure_state_dir(config)
    try:
        with open(args.inventory, "r", encoding="utf-8") as handle:
            inventory = json.load(handle)
    except (OSError, ValueError) as exc:
        print("錯誤：讀取盤點檔失敗: %s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT

    entries_in = inventory.get("entries")
    if not isinstance(entries_in, list) or not entries_in:
        print("錯誤：盤點檔缺少非空的 entries 陣列", file=sys.stderr)
        return EXIT_PREFLIGHT
    checkpoints_in = inventory.get("checkpoints") or []

    errors = []
    warnings = []

    # STEP 02: id 唯一性
    seen_ids = set()
    for entry in entries_in:
        entry_id = entry.get("id")
        if not entry_id:
            errors.append("有 entry 缺少 id")
            continue
        if entry_id in seen_ids:
            errors.append("entry id 重複: %s" % entry_id)
        seen_ids.add(entry_id)

    # STEP 03: depends_on 目標存在 + 無環
    for entry in entries_in:
        for dep in entry.get("depends_on") or []:
            if dep not in seen_ids:
                errors.append("entry `%s` 的 depends_on 指向不存在的 id: %s" % (entry.get("id"), dep))
    cycle = detect_cycle([entry for entry in entries_in if entry.get("id")])
    if cycle:
        errors.append("depends_on 有環: %s" % " → ".join(cycle))

    # STEP 04: entry 自身的 wave 值域（決策 24：0–5，且必須是整數，不接受字串/浮點數）
    for entry in entries_in:
        wave = entry.get("wave")
        is_valid_wave = isinstance(wave, int) and not isinstance(wave, bool)
        if not is_valid_wave or wave < ENTRY_WAVE_MIN or wave > ENTRY_WAVE_MAX:
            errors.append(
                "entry `%s` 的 wave 值不合法: %r（必須是 %d–%d 的整數）"
                % (entry.get("id"), wave, ENTRY_WAVE_MIN, ENTRY_WAVE_MAX)
            )

    # STEP 05: entry 的 type／route.switch 值域（1.0.4 新增，避免盤點打錯字靜默寫入 queue）
    for entry in entries_in:
        entry_type = entry.get("type", "page")
        if entry_type not in ENTRY_TYPE_VALUES:
            errors.append(
                "entry `%s` 的 type 值不合法: %r（必須是 %s）"
                % (entry.get("id"), entry_type, " 或 ".join(ENTRY_TYPE_VALUES))
            )
        route_switch = (entry.get("route") or {}).get("switch")
        if route_switch is not None and route_switch != ROUTE_SWITCH_STATIC_LIST:
            errors.append(
                "entry `%s` 的 route.switch 值不合法: %r（若有值必須等於 `%s`）"
                % (entry.get("id"), route_switch, ROUTE_SWITCH_STATIC_LIST)
            )

    # STEP 06: checkpoint 的 after.wave 必須有對應 entry
    waves = {entry.get("wave") for entry in entries_in}
    for checkpoint in checkpoints_in:
        wave = (checkpoint.get("after") or {}).get("wave")
        if wave is None:
            errors.append("斷點 `%s` 缺少 after.wave" % checkpoint.get("id"))
            continue
        if wave not in waves:
            errors.append("斷點 `%s` 的 after.wave=%s 沒有任何對應的 entry" % (checkpoint.get("id"), wave))

    # STEP 07: r15_paths 逐檔存在，並算檔數／行數對 limits（tab-reuse entry 允許空陣列）
    too_large = {}
    for entry in entries_in:
        paths = entry.get("r15_paths") or []
        if not paths:
            if is_tab_reuse_entry(entry):
                continue
            errors.append(
                "entry `%s` 沒有 r15_paths（tab-reuse entry 須 type=page、route.kind=sub、"
                "shared_deps 恰一筆且 r18_equivalent 非空）" % entry.get("id")
            )
            continue
        total_lines = 0
        for relative in paths:
            full = os.path.join(config["repo_dir"], relative)
            if not os.path.exists(full):
                errors.append("entry `%s` 的 r15_paths 檔案不存在: %s" % (entry.get("id"), relative))
                continue
            total_lines += count_lines(full)
        if len(paths) > config["entry_max_files"] or total_lines > config["entry_max_lines"]:
            too_large[entry["id"]] = "%d 檔 / %d 行（上限 %d 檔 / %d 行）" % (
                len(paths),
                total_lines,
                config["entry_max_files"],
                config["entry_max_lines"],
            )
            warnings.append("entry `%s` 超過上限，標記為 blocked(too_large): %s" % (entry["id"], too_large[entry["id"]]))

    # STEP 08: 前綴碰撞
    errors.extend(prefix_collisions([entry for entry in entries_in if entry.get("id")]))

    # STEP 09: 有錯就全部列出並退出，不寫任何檔案
    if errors:
        print("盤點檔驗證失敗，共 %d 個問題：" % len(errors), file=sys.stderr)
        for message in errors:
            print("  - %s" % message, file=sys.stderr)
        return 1

    # STEP 10: 讀既有 queue（冪等：保留執行期欄位）
    existing = None
    if os.path.exists(queue_file(config)):
        try:
            existing = load_queue(config)
        except ValueError as exc:
            print("錯誤：既有 queue.json 無法解析，請先處理: %s" % exc, file=sys.stderr)
            return EXIT_PREFLIGHT

    def build_queue(queue):
        """把盤點內容併進 queue（就地修改），回傳統計。"""
        modules = []
        for entry_in in entries_in:
            entry_id = entry_in["id"]
            old = find_entry(queue, entry_id) if queue else None
            merged = dict(RUNTIME_FIELD_DEFAULTS)
            if old:
                for field in RUNTIME_FIELD_DEFAULTS:
                    merged[field] = old.get(field, RUNTIME_FIELD_DEFAULTS[field])
            # 靜態欄位一律以盤點檔為準（原樣轉錄）
            merged.update(
                {
                    "id": entry_id,
                    "type": entry_in.get("type", "page"),
                    "members": entry_in.get("members", []),
                    "wave": entry_in.get("wave"),
                    "r15_paths": entry_in.get("r15_paths", []),
                    "r18_dir": entry_in.get("r18_dir"),
                    "route": entry_in.get("route", {}),
                    "feature_flag": entry_in.get("feature_flag", {}),
                    "sidebar_entries": entry_in.get("sidebar_entries", []),
                    "shared_deps": entry_in.get("shared_deps", []),
                    "depends_on": entry_in.get("depends_on", []),
                    "jira": entry_in.get("jira"),
                    "branch": (entry_in.get("branch") or "").strip() or build_branch_name(config, entry_in),
                }
            )
            # 超限的 entry 標記為 blocked，但不從佇列中略過
            if entry_id in too_large and merged["status"] in ("pending", "blocked"):
                merged["status"] = "blocked"
                merged["blocked_reason"] = "too_large"
                merged["last_error"] = too_large[entry_id]
            modules.append(merged)

        checkpoints = []
        for checkpoint_in in checkpoints_in:
            old = find_checkpoint(queue, checkpoint_in.get("id")) if queue else None
            merged = dict(CHECKPOINT_FIELD_DEFAULTS)
            if old:
                for field in CHECKPOINT_FIELD_DEFAULTS:
                    merged[field] = old.get(field, CHECKPOINT_FIELD_DEFAULTS[field])
            merged.update(
                {
                    "id": checkpoint_in.get("id"),
                    "after": checkpoint_in.get("after", {}),
                    "mode": checkpoint_in.get("mode", "soft"),
                    "pr_base": checkpoint_in.get("pr_base", config["base_branch"]),
                    "title": checkpoint_in.get("title", ""),
                }
            )
            checkpoints.append(merged)

        queue["version"] = 1
        queue["repo_dir"] = config["repo_dir"]
        queue["integration_branch"] = config["integration_branch"]
        queue["base_branch"] = config["base_branch"]
        queue["limits"] = {
            "entry_max_files": config["entry_max_files"],
            "entry_max_lines": config["entry_max_lines"],
            "checkpoint_max_modules": config["checkpoint_max_modules"],
            "checkpoint_max_lines": config["checkpoint_max_lines"],
            "module_timeout_min": config["module_timeout_min"],
            "module_budget_usd": config["module_budget_usd"],
        }
        queue.setdefault(
            "runner_state",
            {"state": "idle", "reason": None, "since": None, "pid": None, "host": None, "consecutive_failures": 0},
        )
        queue.setdefault("integration_tip_sha", None)
        queue["checkpoints"] = checkpoints
        queue["modules"] = modules
        return {"modules": len(modules), "checkpoints": len(checkpoints)}

    # STEP 11: 寫檔（既有檔走 mutate_queue：持 queue.json.lock、原子替換；否則直接新建）
    if existing is None:
        fresh = {}
        stats = build_queue(fresh)
        write_queue_new(config, fresh)
    else:
        stats = mutate_queue(config, build_queue)

    for message in warnings:
        print("警告：%s" % message)
    print("已寫入 %s：%d 個 entry、%d 個斷點" % (queue_file(config), stats["modules"], stats["checkpoints"]))
    log_event(config, None, "inventory_imported", detail=stats)
    return EXIT_OK


# ================================================================ 進入點


def build_parser():
    """建立命令列解析器。"""
    parser = argparse.ArgumentParser(
        prog="runner.py",
        description="R15→R18 批次遷移 runner：取件、呼叫遷移 skill、驗證、開 PR、合併、通知。",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<子命令>")

    run_parser = subparsers.add_parser("run", help="主迴圈（無人看管執行）")
    run_parser.add_argument(
        "--max-modules",
        type=int,
        default=0,
        help="最多處理幾個模組後就停（0 = 不限制；測試用）",
    )

    status_parser = subparsers.add_parser("status", help="印出佇列統計與 runner 狀態")
    status_parser.add_argument("--verbose", action="store_true", help="一併列出卡住的模組明細")

    release_parser = subparsers.add_parser("release", help="放行一個等待人工檢視的斷點")
    release_parser.add_argument("checkpoint_id", help="斷點 id")

    unblock_parser = subparsers.add_parser("unblock", help="把 failed/blocked 的 entry 放回 pending")
    unblock_parser.add_argument("entry_id", nargs="?", default=None, help="entry id")
    unblock_parser.add_argument(
        "--integration-tip",
        action="store_true",
        help="改為把整合分支基線對齊遠端現況，用於人工確認過外部 commit 之後解除 integration_diverged",
    )
    unblock_parser.add_argument(
        "--runner",
        action="store_true",
        help="改為解除 runner 級鎖定（同簽名例外兩次後的 hold）與 runner_crashed 暫停",
    )

    import_parser = subparsers.add_parser("import-inventory", help="把盤點 JSON 轉成 queue.json")
    import_parser.add_argument("inventory", help="盤點 JSON 檔路徑")

    progress_parser = subparsers.add_parser("render-progress", help="重新產生 PROGRESS.md")
    progress_parser.add_argument("--checkpoint-id", default=None, help="改為輸出指定斷點的 PR 內文")

    diagnose_parser = subparsers.add_parser("diagnose", help="把一次失敗的全部證據打包成 diagnostics/<名稱>/（含 SUMMARY.md）")
    diagnose_parser.add_argument("entry_id", nargs="?", default=None, help="entry id")
    diagnose_parser.add_argument("--attempt", type=int, default=0, help="指定第幾次呼叫（預設取 sessions/ 內最新一次）")
    diagnose_parser.add_argument("--all-failed", action="store_true", help="對所有 blocked／failed 的 entry 各產一包")
    diagnose_parser.add_argument("--runner", action="store_true", help="產 runner 級診斷包（runner_state、最近事件、最近一次 crash）")
    diagnose_parser.add_argument("--tar", action="store_true", help="另外打成 .tar.gz，印出 tar 路徑")

    return parser


def main(argv):
    """進入點：解析參數後分派到子命令。"""
    # STEP 01: 解析參數；沒給子命令就印說明
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE

    # STEP 02: 載入設定後分派
    config = load_config()
    handlers = {
        "run": cmd_run,
        "status": cmd_status,
        "release": cmd_release,
        "unblock": cmd_unblock,
        "import-inventory": cmd_import_inventory,
        "render-progress": cmd_render_progress,
        "diagnose": cmd_diagnose,
    }
    return handlers[args.command](config, args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
