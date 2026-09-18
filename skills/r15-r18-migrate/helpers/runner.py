#!/usr/bin/env python3
"""runner.py — 無人看管批次遷移的主控程式。

一次處理一個 entry：從 queue.json 取件 → 準備 git 環境 → 用 headless CLI 呼叫遷移
skill → 自己驗證建置與啟動 → fast-forward 併入整合分支 → 開 PR → 更新進度與通知。

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
# 單一 entry 最多嘗試次數，達到即 failed
MAX_ATTEMPTS = 3
# 這幾種判讀結果要在寫回 queue、發通知之前先把證據凍結成診斷包（額度類不凍結：不是錯誤）
FREEZE_OUTCOME_KINDS = ("timeout", "error", "blocked", "hook_denied", "auth_expired")
# 文字特徵判讀（額度／未登入樣式）時，assistant 文字與 stderr 各只看末尾這麼多字元
STREAM_TEXT_TAIL_CHARS = 4000
# runner 未預期例外的暫停原因代號（enter_paused 的 reason、unblock --runner 解除的對象）
CRASH_REASON = "runner_crashed"

# 退出碼
EXIT_OK = 0
EXIT_LOCKED = 1
EXIT_PREFLIGHT = 2
EXIT_PAUSED = 3
EXIT_USAGE = 64

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
    """計算單一檔案內容的 sha1；讀不到時回 None。"""
    try:
        with open(path, "rb") as handle:
            return hashlib.sha1(handle.read()).hexdigest()
    except OSError:
        return None


def tail_lines(text, n):
    """回傳文字最後 n 行接成的字串；空字串輸入回空字串。"""
    if not text:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-n:])


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
            timeout=120,
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


class ProcessLock(object):
    """runner.lock：確保同一個狀態目錄同時只有一個 run 迴圈。

    取鎖用 O_EXCL；若鎖已存在則檢查裡面的 pid 是否還活著，死掉就接管。
    """

    def __init__(self, path):
        """記住鎖檔路徑。"""
        self.path = path
        self.acquired = False

    def acquire(self):
        """嘗試取鎖；成功回 True，已被活著的行程持有回 False。"""
        # STEP 01: 先試 O_EXCL 建檔
        payload = json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "since": now_iso()})
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, payload.encode("utf-8"))
            os.close(fd)
            self.acquired = True
            return True
        except FileExistsError:
            pass
        # STEP 02: 鎖已存在 → 讀 pid 判斷是否仍活著
        holder_pid = None
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                holder_pid = json.load(handle).get("pid")
        except (OSError, ValueError):
            holder_pid = None
        if holder_pid and self._pid_alive(int(holder_pid)):
            return False
        # STEP 03: 持有者已死 → 接管
        try:
            os.unlink(self.path)
        except OSError:
            return False
        return self.acquire()

    @staticmethod
    def _pid_alive(pid):
        """判斷 pid 是否還在跑。"""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def release(self):
        """釋放鎖（只刪自己建立的鎖檔）。"""
        if not self.acquired:
            return
        try:
            os.unlink(self.path)
        except OSError as exc:
            print("警告：移除 runner.lock 失敗: %s" % exc, file=sys.stderr)
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


def mutate_queue(config, mutator):
    """在 flock 保護下讀-改-寫 queue.json。

    mutator 收到整份 queue dict，就地修改；回傳值會被原樣傳回呼叫端。
    run 迴圈與 release / unblock / import-inventory 共用這把鎖，確保互斥。
    """
    path = queue_file(config)
    # STEP 01: 用 r+ 開檔並上獨占鎖（檔案必須已存在）
    with open(path, "r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            try:
                queue = json.load(handle)
            except ValueError as exc:
                raise ValueError("queue.json 解析失敗（queue_corrupt）: %s" % exc)
            # STEP 02: 交給呼叫端修改
            outcome = mutator(queue)
            # STEP 03: 就地覆寫（維持同一個 fd，鎖才不會斷）
            handle.seek(0)
            handle.truncate()
            json.dump(queue, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            return outcome
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_queue_new(config, queue):
    """建立新的 queue.json（import-inventory 第一次執行時用）。"""
    # STEP 01: 先寫暫存檔再改名，避免中途中斷留下半份檔案
    path = queue_file(config)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(queue, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp_path, path)


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
    """執行 git 並回傳去空白的 stdout；失敗時回空字串。"""
    code, out, _err = git(config, *args)
    if code != 0:
        return ""
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
    """回傳前端 lockfile 的內容 hash；檔案不存在時回 None。"""
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
        "runner_sha1": (file_sha1(os.path.abspath(__file__)) or "")[:12] or None,
        "diagnostics_sha1": (file_sha1(os.path.abspath(diagnostics.__file__)) or "")[:12] or None,
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
    try:
        process = subprocess.Popen(
            command,
            cwd=config["repo_dir"],
            stdin=devnull,
            stdout=stream_handle,
            stderr=subprocess.PIPE,
            text=True,
            env=child_env,
        )
    except OSError as exc:
        devnull.close()
        stream_handle.close()
        return {
            "returncode": 127,
            "stream_path": stream_path,
            "stderr": "無法執行 CLI: %s" % exc,
            "timed_out": False,
            "duration_s": 0,
        }

    # STEP 02: 等待結果；逾時先 TERM 再 KILL（stdout 已在檔案裡，communicate 只收 stderr）
    try:
        _stdout, stderr = process.communicate(timeout=config["module_timeout_min"] * 60)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.terminate()
        try:
            _stdout, stderr = process.communicate(timeout=TERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            _stdout, stderr = process.communicate()
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


def l1_verify_and_merge(config, entry):
    """L1 判準 (2)–(6)：commit 存在 → build → smoke → 秘密掃描 → ff-merge + push。

    回傳 (result, detail)，result 是 done / build_unverified / secret_detected /
    no_commit / integration_diverged。
    """
    integration = config["integration_branch"]
    # STEP 01: (2) branch 必須真的有 commit
    log_out = git_out(config, "log", "--oneline", "%s..%s" % (integration, entry["branch"]))
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

    # STEP 05: (6) 切回整合分支做 fast-forward 合併（merge／push 全文落檔）
    code, _out, err = git(config, "checkout", integration)
    if code != 0:
        return "integration_diverged", "切換到整合分支失敗: %s" % err.strip()[-200:]
    log_path = session_log_path(config, "git-merge-ff")
    code, _out, err = git(config, "merge", "--ff-only", entry["branch"], log_path=log_path)
    if code != 0:
        return "integration_diverged", "ff-merge 失敗: %s%s" % (err.strip()[-200:], log_ref(config, log_path))
    log_path = session_log_path(config, "git-push-integration")
    code, _out, err = git(config, "push", "origin", integration, log_path=log_path)
    if code != 0:
        return "integration_diverged", "推送整合分支失敗: %s%s" % (err.strip()[-200:], log_ref(config, log_path))

    log_event(
        config,
        entry["id"],
        "l1_passed",
        detail={"build": build_detail, "smoke": smoke_detail, "commits": len(log_out.splitlines())},
    )
    return "done", "ff-merge 完成"


def push_branch_and_open_pr(config, entry):
    """推送頁面分支並開 PR（L1'）。

    回傳 (pr_url, error)；失敗時 pr_url 為 None。
    """
    integration = config["integration_branch"]
    # STEP 01: 推送頁面分支（全文落檔）
    log_path = session_log_path(config, "git-push-branch")
    code, _out, err = git(config, "push", "-u", "origin", entry["branch"], log_path=log_path)
    if code != 0:
        return None, "推送頁面分支失敗: %s%s" % (err.strip()[-200:], log_ref(config, log_path))

    # STEP 02: 組 PR 內文（只放統計與路徑，不放檔案內容）
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
    # STEP 03: 從輸出取 URL（gh 會把 PR 連結印在最後一行）
    url = ""
    for line in (out or "").strip().splitlines():
        if line.strip().startswith("http"):
            url = line.strip()
    return url or (out or "").strip(), None


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
    """記錄本次遷移當下每個 R15 原始檔的內容 hash。"""
    # STEP 01: 逐檔算 hash，讀不到的記成 None（代表檔案已不在）
    hashes = {}
    for relative in entry.get("r15_paths", []):
        hashes[relative] = file_sha1(os.path.join(config["repo_dir"], relative))
    return hashes


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
        mark_checkpoint_failed(config, checkpoint_id, "推送 cp 分支失敗: %s" % err.strip()[-200:])
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
        mark_checkpoint_failed(config, checkpoint_id, "開 cp PR 失敗: %s" % (err or out).strip()[-200:])
        return False

    # STEP 03: 寫回狀態，並把這個斷點涵蓋的模組標記起來
    pr_url = ""
    for line in (out or "").strip().splitlines():
        if line.strip().startswith("http"):
            pr_url = line.strip()

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
    # STEP 04: 斷點歸屬變了，進度檔要重畫一次（模組完成時畫的那份還沒有斷點區塊）
    write_progress(config)
    log_event(config, None, "checkpoint_opened", detail={"checkpoint": checkpoint_id, "pr": pr_url})
    notify(
        config,
        "checkpoint_opened",
        "斷點 %s 已開 PR" % checkpoint_id,
        "分支: %s\nPR: %s\n模式: %s" % (branch, pr_url or "（無連結）", checkpoint.get("mode", "soft")),
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
    """比對 r15_hashes 找出「遷移後 R15 原檔又被改過」的模組。"""
    # STEP 01: 只看已完成且有記錄 hash 的 entry
    changed = []
    for entry in queue.get("modules", []):
        if entry.get("status") != "done":
            continue
        drifted = []
        for relative, recorded in (entry.get("r15_hashes") or {}).items():
            current = file_sha1(os.path.join(config["repo_dir"], relative))
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

    回傳 (ok, pause_reason, detail)。ok 為 False 時 runner 應進入 paused。
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

    # STEP 04: 本地落後就補齊（ff-only；本地領先則是 no-op）
    code, _out, err = git(config, "merge", "--ff-only", "origin/%s" % integration)
    if code != 0:
        return False, "integration_diverged", "整合分支無法 fast-forward: %s" % err.strip()[-200:]

    # STEP 05: 與基準分支同步；衝突自己 abort
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

    # STEP 06: 回流所有還開著的斷點分支
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
    return enter_paused(
        config, CRASH_REASON, detail, signature=signature, trace_text=trace_text, notify_event="runner_crashed"
    )


def enter_paused(config, reason, detail, signature=None, trace_text=None, notify_event="paused"):
    """進入 runner 級暫停：凍結證據、記錄、必要時通知，然後回傳退出碼。

    同一個原因重啟後再次偵測到時只留紀錄、不重複通知（避免通知疲勞）。

    signature：runner 例外的簽名（crash_signature）。給定時去重條件加上「同簽名」，且同簽名
    第二次出現會設 runner_state.hold——之後每次啟動在 pre-flight 之前就靜默退出，直到
    `unblock --runner`（否則 crash 若落在模組執行之後，每次 launchd 重啟都白燒一個模組預算）。
    hold 是新狀態，即使算重複也要通知一次。
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
    hold = previous_hold or bool(signature is not None and repeated)

    # STEP 02: 凍結 runner 級證據（不依賴 queue 可讀；queue_corrupt 時原檔照樣複製進包）
    bundle = freeze_runner_bundle(config, reason, detail, trace_text=trace_text)

    # STEP 03: 寫狀態與紀錄
    try:
        set_runner_state(config, "paused", reason, extra={"crash_signature": signature, "hold": hold})
    except (OSError, ValueError) as exc:
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
            "diagnostics": bundle,
        },
    )

    # STEP 04: 第一次進入才通知；hold 是新狀態，即使重複也要通知一次
    hold_transition = hold and not previous_hold
    if not repeated or hold_transition:
        if hold_transition:
            body = (
                "同一例外重複發生，runner 已鎖定（hold）；修正後執行 `runner.py unblock --runner` 解除\n細節: %s"
                % detail
            )
        else:
            body = "細節: %s\n處理後 runner 會在下次重啟時自動續跑" % detail
        notify(config, notify_event, "runner 已暫停: %s" % reason, with_diagnostics_line(body, bundle))
    return EXIT_PAUSED


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
        recovered = []
        for entry in queue.get("modules", []):
            if entry.get("status") == "running":
                entry["status"] = "pending"
                recovered.append(entry["id"])
        return {"recovered": recovered, "baseline_written": baseline_written}

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


def finish_done_entry(config, entry, outcome):
    """L1 通過後的收尾：開 PR、記 hash、標 done、更新進度與通知。"""
    # STEP 01: 記錄整合分支新的 tip
    tip = git_out(config, "rev-parse", "HEAD")
    if tip:
        set_integration_tip(config, tip)

    # STEP 02: 推分支並開 PR（失敗不影響 done，只標 pr_failed）
    pr_url, pr_error = push_branch_and_open_pr(config, entry)
    hashes = record_r15_hashes(config, entry)
    commit = git_out(config, "rev-parse", entry["branch"])
    structured = outcome.get("structured") or {}

    def mutator(queue):
        """把 entry 標成 done 並寫回執行結果。"""
        target = find_entry(queue, entry["id"])
        if target is None:
            return None
        target["status"] = "done"
        target["blocked_reason"] = None
        target["last_commit"] = commit
        target["last_session_id"] = outcome.get("session_id")
        target["pr_url"] = pr_url
        target["pr_failed"] = bool(pr_error)
        target["r15_hashes"] = hashes
        target["finished_at"] = now_iso()
        target["last_error"] = None
        add_cost(target, outcome)
        queue.setdefault("runner_state", {})["consecutive_failures"] = 0
        return target

    mutate_queue(config, mutator)

    # STEP 03: 通知與進度
    if pr_error:
        log_event(config, entry["id"], "pr_failed", detail=pr_error)
        notify(config, "module_blocked", "模組 %s 的 PR 未開成功" % entry["id"], pr_error)
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

    # STEP 05: L1 驗證與合併
    result, detail = l1_verify_and_merge(config, entry)
    log_event(config, entry_id, "l1_result", detail={"result": result, "detail": detail})
    if result == "done":
        finish_done_entry(config, entry, outcome)
        return None
    # STEP 05.01: L1 沒過一律先凍結——skill 回報 done 但 runner 自驗失敗，stream 是找原因的依據
    bundle = freeze_entry_bundle(config, entry_id, attempt, "l1_%s" % result, detail)
    if result == "integration_diverged":
        if bundle:
            detail = "%s（entry 診斷: %s）" % (detail, bundle)
        return enter_paused(config, "integration_diverged", detail)
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

    # STEP 06: 其餘（沒有 commit）視為 error，累加 attempts
    apply_outcome(
        config,
        entry_id,
        {"kind": "error", "detail": detail, "session_id": outcome.get("session_id"), "diagnostics": bundle},
    )
    refresh_bundle_snapshot(config, entry_id, bundle)
    return None


def cmd_run(config, args):
    """run 子命令：主迴圈。"""
    # STEP 01: 必填檢查與取鎖
    if not require_config(config, ["repo_dir", "branch_user", "has_oauth_token"]):
        return EXIT_PREFLIGHT
    if config["notify_channel"] == "line" and not (
        os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") and os.environ.get("LINE_NOTIFY_TARGET_ID")
    ):
        print("錯誤：NOTIFY_CHANNEL=line 但缺少 LINE 憑證或推播對象設定", file=sys.stderr)
        return EXIT_PREFLIGHT
    ensure_state_dir(config)
    lock = ProcessLock(state_path(config, "runner.lock"))
    if not lock.acquire():
        print("錯誤：已有另一個 runner 在執行（runner.lock 被持有）", file=sys.stderr)
        return EXIT_LOCKED

    processed = 0
    stalled_notified = False
    previous_lock_hash = lockfile_hash(config)
    try:
        # STEP 01.01: 上一輪同簽名 crash 兩次 → hold；人工 unblock --runner 之前靜默退出，
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

            # STEP 03.02: 取件
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

            # STEP 03.03: 額度 pre-flight
            snapshot = quota_snapshot(config)
            should_wait, reason, resets_at = quota_blocks_start(config, snapshot)
            if should_wait:
                if not wait_until(config, resets_at, reason, "seven_day" in reason):
                    notify(config, "runner_crashed", "等待額度超過上限", "原因: %s" % reason)
                    return EXIT_PAUSED
                continue

            # STEP 03.04: git 前置
            ok, pause_reason, detail = module_preflight(config, queue)
            if not ok:
                return enter_paused(config, pause_reason, detail)

            # STEP 03.05: 依賴安裝
            # （原本這裡會在 git 前置一過就先發「已續跑」通知，但那時模組還沒真的跑，
            #   像 auth_expired 這類原因要等模組真的呼叫過 CLI 才知道是否還在發生；
            #   改成只在第一個模組真的 done 之後才發，見 finish_done_entry。R2）
            ok, previous_lock_hash, detail = install_deps_if_lockfile_changed(config, previous_lock_hash)
            if not ok:
                return enter_paused(config, "deps_install_failed", detail)

            # STEP 03.06: 切分支後才呼叫 skill
            ok, detail = prepare_branch(config, entry)
            if not ok:
                return enter_paused(config, "integration_dirty", detail)

            exit_code = process_one_entry(config, entry)
            processed += 1
            if exit_code is not None:
                return exit_code

            # STEP 03.07: 斷點檢查
            should_pause, checkpoint_id = handle_checkpoints(config)
            if should_pause:
                if not wait_for_release(config, checkpoint_id):
                    return enter_paused(config, "paused_for_review", "斷點 %s 等待逾時" % checkpoint_id)
                set_runner_state(config, "running")
    except KeyboardInterrupt:
        log_event(config, None, "interrupted", detail="收到中斷訊號")
        return EXIT_OK
    except Exception as exc:
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
    """把記錄的整合分支 tip 重新對齊遠端現況，並解除 integration_diverged 暫停。

    用於「有人直接推了整合分支、人工確認過內容沒問題」之後讓 runner 續跑。
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

    # STEP 02: 寫回新的基線並清掉對應的暫停狀態
    def mutator(queue):
        """更新 integration_tip_sha，必要時解除暫停。"""
        queue["integration_tip_sha"] = remote_tip
        runner_state = queue.setdefault("runner_state", {})
        if runner_state.get("state") == "paused" and runner_state.get("reason") in (
            "integration_diverged",
            "master_conflict",
            "integration_dirty",
        ):
            runner_state["state"] = "idle"
            runner_state["reason"] = None
        return remote_tip

    try:
        mutate_queue(config, mutator)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    log_event(config, None, "integration_tip_rebaselined", detail={"sha": remote_tip})
    print("已把整合分支基線對齊到 %s；下次啟動會從這個 SHA 繼續" % remote_tip[:12])
    return EXIT_OK


def unblock_runner(config):
    """解除 runner 級鎖定（hold）與 runner_crashed 暫停，讓下次啟動可以續跑。"""

    def mutator(queue):
        """清掉 hold 與 crash 簽名；若暫停原因就是 crash，一併回 idle。"""
        runner_state = queue.setdefault("runner_state", {})
        was_hold = bool(runner_state.get("hold"))
        runner_state["hold"] = False
        runner_state["crash_signature"] = None
        if runner_state.get("state") == "paused" and runner_state.get("reason") == CRASH_REASON:
            runner_state["state"] = "idle"
            runner_state["reason"] = None
        return was_hold

    try:
        was_hold = mutate_queue(config, mutator)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        return EXIT_PREFLIGHT
    log_event(config, None, "runner_unblocked", detail={"was_hold": was_hold})
    print("已解除 runner 鎖定（hold %s → false），下次啟動會續跑" % ("true" if was_hold else "false"))
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

    # STEP 11: 寫檔（既有檔在 flock 下就地更新，否則直接新建）
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
        description="R15→R18 批次遷移 runner：取件、呼叫遷移 skill、驗證、合併、開 PR、通知。",
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
