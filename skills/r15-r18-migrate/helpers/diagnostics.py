#!/usr/bin/env python3
"""diagnostics.py — 錯誤證據的凍結與彙整（runner.py 的輔助模組）。

負責三件事：
  1. 讀狀態目錄裡一次呼叫的全部證據（sessions/ 的 stream／meta／子行程 log、progress、runner 事件）
  2. 把它們凍結成 diagnostics/<名稱>/（SUMMARY.md + 原檔複本），或打成 tar
  3. 憑證遮罩（只對 SUMMARY.md，原檔複本不動）

stream-json 本身的解析（讀檔容錯、result 事件、時間軸）在 stream_events.py，本檔與 runner.py 都用它。

設計約束：
  * 只用 python3 標準函式庫；不 import runner.py（避免循環），需要的常數由呼叫端傳入。
  * 本模組絕不寫 queue.json；只讀狀態目錄、只寫 diagnostics/ 底下。
  * 任何讀檔失敗都轉成 SUMMARY 內的一行說明，不讓診斷本身炸掉主流程。
"""

import datetime
import gzip
import json
import os
import re
import shutil
import tarfile

# stream-json 解析（runner.py 也直接用它；依賴方向：runner → diagnostics → stream_events）
from stream_events import (
    build_timeline,
    clip,
    event_brief,
    init_event,
    last_result_event,
    read_stream,
)

# ================================================================ 常數

# 狀態目錄下的子目錄名
SESSIONS_DIR_NAME = "sessions"
DIAGNOSTICS_DIR_NAME = "diagnostics"
CRASHES_DIR_NAME = "crashes"
# stream 落檔與 meta 檔的副檔名（與 runner.save_session_output 的命名一致）
STREAM_SUFFIX = ".stream.jsonl"
META_SUFFIX = ".json"
# 診斷包內的固定檔名
SUMMARY_NAME = "SUMMARY.md"
STREAM_COPY_NAME = "stream.jsonl.gz"
META_COPY_NAME = "meta.json"
QUEUE_ENTRY_COPY_NAME = "queue-entry.json"
QUEUE_COPY_NAME = "queue.json.snapshot"
RUNNER_EVENTS_COPY_NAME = "runner-events.jsonl"
TRACE_COPY_NAME = "traceback.txt"
# 診斷包目錄權限（內含工具輸出原文，只給擁有者）
BUNDLE_DIR_MODE = 0o700
# 時間軸最多列出幾列；超過時取頭尾各一半，中間以一行說明省略
TIMELINE_MAX_ROWS = 400
# 「最後幾個事件」區段的筆數（逾時定位用）
LAST_EVENTS_COUNT = 10
# 子行程 log 與 CLI stderr 在 SUMMARY 內只列末幾行
LOG_TAIL_LINES = 50
# runner 級診斷包收錄的 runner.log.jsonl 尾端筆數
RUNNER_EVENTS_TAIL = 200
# 遮罩後的替代文字格式（%s 是憑證樣式類別名）
REDACTED_FORMAT = "[REDACTED:%s]"
# progress.md 的失敗紀錄段標題（與 templates/progress.template.md 一致）
PROGRESS_FAILURE_HEADING = "## 失敗紀錄"
# boot-smoke 輸出裡值得單獨抽出的行（逐筆忽略項與最終判定）
SMOKE_NOTABLE_RE = re.compile(r"\[ignored:|\bFAIL\b|\bPASS\b")
# progress.md 勾選列
PROGRESS_ITEM_RE = re.compile(r"^- \[( |x|X)\] (.*)$")
# 診斷包名稱裡不允許的字元（檔名安全）
UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


# ================================================================ 小工具


def now_iso():
    """回傳本地時區的 ISO 8601 時間字串。"""
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def compact_ts():
    """回傳給檔名用的緊湊時間戳（YYYYmmddTHHMMSS）。"""
    return datetime.datetime.now().strftime("%Y%m%dT%H%M%S")


def safe_name(text):
    """把任意字串轉成可當檔名片段的形式。"""
    cleaned = UNSAFE_NAME_RE.sub("-", str(text)).strip("-")
    return cleaned or "unknown"


def tail_lines(text, count):
    """回傳文字的最後幾行。"""
    lines = (text or "").splitlines()
    return "\n".join(lines[-count:])


def read_text(path):
    """讀純文字檔；不存在或讀失敗回 None。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def read_json(path):
    """讀 JSON 檔；不存在或解析失敗回 None。"""
    text = read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def relpath_in(state_dir, path):
    """回傳 path 相對於狀態目錄的相對路徑（給通知與 log 用，短且不含家目錄）。"""
    try:
        return os.path.relpath(path, state_dir)
    except ValueError:
        return path


# ================================================================ 憑證遮罩


def mask_text(text, secret_labels):
    """把命中憑證樣式的行整行換成 [REDACTED:<類別>]。

    secret_labels 是 [(類別名, 已編譯 regex)]，由呼叫端（runner）傳入，避免兩份清單分歧。
    只用於 SUMMARY.md；原檔複本不遮罩（遮罩會破壞證據，原檔靠目錄權限保護）。
    """
    # STEP 01: 沒有樣式清單就原樣回傳
    if not secret_labels:
        return text
    # STEP 02: 逐行比對，命中第一個類別就整行換掉
    masked = []
    for line in (text or "").splitlines():
        label = None
        for name, pattern in secret_labels:
            if pattern.search(line):
                label = name
                break
        masked.append(REDACTED_FORMAT % label if label else line)
    return "\n".join(masked)


# ================================================================ 狀態目錄讀取


def sessions_dir(state_dir):
    """回傳 sessions/ 的完整路徑。"""
    return os.path.join(state_dir, SESSIONS_DIR_NAME)


def latest_attempt(state_dir, entry_id):
    """掃 sessions/<entry>-<n>.json 找最大的 n；沒有任何 session 檔回 None。

    queue 的 attempts 只在 error／timeout 時累加、blocked 不累加、unblock 會歸零，所以
    「最新一次呼叫」的編號不能從 queue 推，只能看檔案；runner 的 next_call_number 用本函式
    保證序號單調遞增，最大編號就是最新一次。
    """
    # STEP 01: 沒有 sessions/ 就沒有任何呼叫紀錄
    prefix = "%s-" % entry_id
    best = None
    directory = sessions_dir(state_dir)
    if not os.path.isdir(directory):
        return None
    # STEP 02: 掃 <entry>-<n>.json 取最大的 n
    for name in os.listdir(directory):
        if not name.startswith(prefix) or not name.endswith(META_SUFFIX):
            continue
        middle = name[len(prefix) : -len(META_SUFFIX)]
        if middle.isdigit():
            number = int(middle)
            if best is None or number > best:
                best = number
    return best


def session_files(state_dir, entry_id, attempt):
    """列出某次呼叫的全部檔案：meta、stream、以及子行程 log（<entry>-<n>-<name>.log）。"""
    # STEP 01: meta 與 stream 是固定檔名
    directory = sessions_dir(state_dir)
    base = "%s-%s" % (entry_id, attempt)
    meta = os.path.join(directory, base + META_SUFFIX)
    stream = os.path.join(directory, base + STREAM_SUFFIX)
    # STEP 02: 子行程 log 依前綴掃出來
    logs = []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            if name.startswith(base + "-") and name.endswith(".log"):
                logs.append(os.path.join(directory, name))
    return {
        "meta": meta if os.path.exists(meta) else None,
        "stream": stream if os.path.exists(stream) else None,
        "logs": logs,
    }


def read_runner_events(state_dir, entry_id=None, since_iso=None, tail=None):
    """讀 runner.log.jsonl 並切片。

    entry_id 給定時：取該 entry 的全部事件，加上 since_iso 之後的 runner 級事件（entry 為 null）。
    entry_id 為 None 時：取全部事件。tail 給定時只留最後幾筆。壞行跳過。
    """
    # STEP 01: 讀檔；不存在回空
    path = os.path.join(state_dir, "runner.log.jsonl")
    text = read_text(path)
    if text is None:
        return []
    # STEP 02: 逐行篩選（entry 相符，或 since 之後的 runner 級事件）
    selected = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if entry_id is None:
            selected.append(record)
            continue
        if record.get("entry") == entry_id:
            selected.append(record)
        elif record.get("entry") is None and since_iso and str(record.get("ts", "")) >= since_iso:
            selected.append(record)
    # STEP 03: 只留尾端
    if tail:
        selected = selected[-tail:]
    return selected


def attempt_started_iso(events, attempt):
    """從 entry 的事件裡找這次 attempt 的 module_started 時間；找不到回 None。"""
    for record in events:
        if record.get("event") == "module_started" and record.get("attempt") == attempt:
            return record.get("ts")
    return None


def parse_progress(text):
    """解析 <entry>-progress.md。

    回傳 dict：phases 是 [(標題, 已勾, 總數, 第一個未勾項)]，failure_section 是
    「## 失敗紀錄」段的原文（沒有回空字串）。
    """
    # STEP 01: 逐行走；遇到 ## 換段（失敗紀錄段整段原文保留，其餘段數勾選）
    phases = []
    failure_lines = []
    current = None
    in_failure = False
    for line in (text or "").splitlines():
        if line.startswith("## "):
            in_failure = line.strip() == PROGRESS_FAILURE_HEADING
            if in_failure:
                current = None
                continue
            current = [line[3:].strip(), 0, 0, None]
            phases.append(current)
            continue
        if in_failure:
            failure_lines.append(line)
            continue
        # STEP 02: 勾選列計數，並記住第一個未勾項
        match = PROGRESS_ITEM_RE.match(line)
        if match and current is not None:
            current[2] += 1
            if match.group(1).lower() == "x":
                current[1] += 1
            elif current[3] is None:
                current[3] = match.group(2).strip()
    return {
        "phases": [tuple(item) for item in phases],
        "failure_section": "\n".join(failure_lines).strip(),
    }


# ================================================================ SUMMARY 產生


def fingerprint_table(fingerprint):
    """把環境指紋 dict 排成 markdown 表格列。"""
    # STEP 01: 依 key 排序輸出，空表補一列說明
    lines = ["| 項目 | 值 |", "|---|---|"]
    for key in sorted((fingerprint or {}).keys()):
        lines.append("| %s | %s |" % (key, clip(str(fingerprint[key]), 120)))
    if len(lines) == 2:
        lines.append("| （無） | |")
    return "\n".join(lines)


def timeline_table(timeline):
    """把時間軸列成 markdown 表格；超過上限只留頭尾。"""
    # STEP 01: 表頭；沒有列就補一列說明
    rows = timeline["rows"]
    lines = ["| # | +秒 | 層 | 工具 | 內容 | 耗時 s | 錯誤 |", "|---|---|---|---|---|---|---|"]
    if not rows:
        lines.append("| | | | | （stream 內沒有任何工具呼叫或文字） | | |")
        return "\n".join(lines)
    # STEP 02: 超過上限取頭尾各半，中間插一列省略說明
    half = TIMELINE_MAX_ROWS // 2
    if len(rows) > TIMELINE_MAX_ROWS:
        shown = rows[:half] + [None] + rows[-half:]
    else:
        shown = rows
    # STEP 03: 逐列輸出（tool 列把輸入與結果摘要串起來）
    for row in shown:
        if row is None:
            lines.append("| … | | | | （中間省略 %d 列，全文見 stream.jsonl.gz） | | |" % (len(rows) - TIMELINE_MAX_ROWS))
            continue
        layer = "sub" if row.get("parent") else "main"
        content = row["input"]
        if row["kind"] == "tool" and row.get("result"):
            content = "%s → %s" % (row["input"], row["result"])
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s |"
            % (
                row["seq"],
                "" if row["rel_s"] is None else row["rel_s"],
                layer,
                row["tool"] or "(text)",
                content.replace("|", "\\|"),
                "" if row["duration_s"] is None else row["duration_s"],
                "❌" if row["is_error"] else "",
            )
        )
    return "\n".join(lines)


def runner_events_table(records):
    """把 runner.log.jsonl 的紀錄列成 markdown 表格。"""
    # STEP 01: 表頭；沒有紀錄補一列
    lines = ["| ts | entry | event | attempt | detail |", "|---|---|---|---|---|"]
    if not records:
        lines.append("| | | （無） | | |")
        return "\n".join(lines)
    # STEP 02: detail 不論字串或物件都壓成單行摘要
    for record in records:
        detail = record.get("detail")
        detail_text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        lines.append(
            "| %s | %s | %s | %s | %s |"
            % (
                record.get("ts", ""),
                record.get("entry") or "",
                record.get("event", ""),
                "" if record.get("attempt") is None else record.get("attempt"),
                clip(detail_text, 200).replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def render_entry_summary(ctx):
    """產出 entry 級 SUMMARY.md 的全文（尚未遮罩）。

    ctx 欄位：entry, entry_id, attempt, reason, detail, fingerprint, meta, events, bad_lines,
    stream_error, result, timeline, stderr, progress, has_contract, has_report,
    logs（[(名稱, 全文)]）, runner_events, files（診斷包內檔案清單）, generated_at
    """
    entry = ctx.get("entry") or {}
    result = ctx.get("result") or {}
    structured = result.get("structured_output") if isinstance(result.get("structured_output"), dict) else None
    lines = []
    # STEP 01: 標頭與判讀摘要
    lines.append("# 診斷：%s attempt %s（%s）" % (ctx["entry_id"], ctx["attempt"], ctx["reason"]))
    lines.append("")
    lines.append("- 產生時間: %s" % ctx["generated_at"])
    lines.append("- 判讀: `%s`；detail: %s" % (ctx["reason"], clip(ctx.get("detail") or "", 300)))
    lines.append(
        "- queue entry: status=`%s` blocked_reason=`%s` attempts=%s last_error=%s"
        % (entry.get("status"), entry.get("blocked_reason"), entry.get("attempts"), clip(entry.get("last_error") or "", 200))
    )
    if structured:
        lines.append(
            "- skill 回報: status=`%s` blocked_reason=`%s` failed_at=`%s` warnings=%s"
            % (
                structured.get("status"),
                structured.get("blocked_reason"),
                json.dumps(structured.get("failed_at"), ensure_ascii=False),
                structured.get("warnings_count"),
            )
        )
        lines.append("- notes: %s" % clip(structured.get("notes") or "", 300))
    else:
        lines.append("- skill 回報: （沒有 structured_output——被殺、逾時、或 CLI 在輸出前失敗）")
    lines.append("")
    # STEP 02: session meta 與 result 事件的統計欄位
    meta = ctx.get("meta") or {}
    lines.append("## 0. 呼叫概況")
    lines.append("")
    lines.append(
        "- returncode=%s timed_out=%s duration_s=%s"
        % (meta.get("returncode"), meta.get("timed_out"), meta.get("duration_s"))
    )
    init = ctx.get("init") or {}
    lines.append(
        "- session_id=%s model=%s cost_usd=%s num_turns=%s"
        % (result.get("session_id"), init.get("model"), result.get("total_cost_usd"), result.get("num_turns"))
    )
    lines.append(
        "- terminal_reason=%s stop_reason=%s is_error=%s permission_denials=%d"
        % (
            result.get("terminal_reason"),
            result.get("stop_reason"),
            result.get("is_error"),
            len(result.get("permission_denials") or []),
        )
    )
    lines.append(
        "- stream 事件 %d 筆、壞行 %d%s"
        % (len(ctx.get("events") or []), ctx.get("bad_lines") or 0, "；%s" % ctx["stream_error"] if ctx.get("stream_error") else "")
    )
    lines.append("")
    lines.append("### 環境指紋")
    lines.append("")
    lines.append(fingerprint_table(ctx.get("fingerprint")))
    lines.append("")
    # STEP 03: 結構化結果全文
    lines.append("## 1. 結構化結果")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(structured, ensure_ascii=False, indent=2) if structured else "null")
    lines.append("```")
    lines.append("")
    # STEP 04: 時間軸
    timeline = ctx.get("timeline") or {"rows": [], "errors": [], "tool_count": 0, "text_count": 0}
    lines.append("## 2. 時間軸（工具呼叫 %d 筆、文字 %d 筆）" % (timeline["tool_count"], timeline["text_count"]))
    lines.append("")
    lines.append("層 = main（主流程）／sub（subagent，事件帶 parent_tool_use_id）。內容欄是 tool_use 輸入 → tool_result 摘要。")
    lines.append("")
    lines.append(timeline_table(timeline))
    lines.append("")
    # STEP 05: 錯誤
    lines.append("## 3. 錯誤")
    lines.append("")
    lines.append("### 3.1 tool_result is_error（%d 筆）" % len(timeline["errors"]))
    lines.append("")
    if not timeline["errors"]:
        lines.append("（無）")
    for seq, tool, text in timeline["errors"]:
        lines.append("- #%s `%s`" % (seq, tool))
        lines.append("")
        lines.append("```")
        lines.append(text.strip())
        lines.append("```")
    lines.append("")
    lines.append("### 3.2 permission_denials")
    lines.append("")
    denials = result.get("permission_denials") or []
    if not denials:
        lines.append("（無）")
    else:
        lines.append("```json")
        lines.append(json.dumps(denials, ensure_ascii=False, indent=2))
        lines.append("```")
    lines.append("")
    lines.append("### 3.3 最後 %d 個事件（逾時／被殺時看這裡）" % LAST_EVENTS_COUNT)
    lines.append("")
    events = ctx.get("events") or []
    if not events:
        lines.append("（stream 內沒有事件）")
    for event in events[-LAST_EVENTS_COUNT:]:
        lines.append("- %s" % event_brief(event, timeline.get("base_ts")))
    lines.append("")
    lines.append("### 3.4 CLI stderr 末 %d 行" % LOG_TAIL_LINES)
    lines.append("")
    lines.append("```")
    lines.append(tail_lines(ctx.get("stderr") or "", LOG_TAIL_LINES) or "（空）")
    lines.append("```")
    lines.append("")
    # STEP 06: skill 側狀態
    lines.append("## 4. skill 側狀態")
    lines.append("")
    progress = ctx.get("progress")
    if progress is None:
        lines.append("- progress.md: 不存在（skill 未走到 Phase 0 寫檔，或狀態目錄不同）")
    else:
        for title, checked, total, first_unchecked in progress["phases"]:
            lines.append(
                "- %s: %d/%d 勾選%s" % (title, checked, total, "；第一個未勾：%s" % first_unchecked if first_unchecked else "")
            )
        lines.append("")
        lines.append("#### 失敗紀錄（progress.md）")
        lines.append("")
        lines.append(progress["failure_section"] or "（空）")
    lines.append("")
    lines.append("- contract.md: %s；report.md: %s" % ("有" if ctx.get("has_contract") else "無", "有" if ctx.get("has_report") else "無"))
    lines.append("")
    # STEP 07: 子行程輸出
    logs = ctx.get("logs") or []
    lines.append("## 5. 子行程輸出（%d 個 log）" % len(logs))
    lines.append("")
    if not logs:
        lines.append("（本次沒有 build／smoke／npm／git 子行程紀錄）")
    for name, text in logs:
        lines.append("### %s（末 %d 行）" % (name, LOG_TAIL_LINES))
        lines.append("")
        notable = [line for line in (text or "").splitlines() if SMOKE_NOTABLE_RE.search(line)]
        if "smoke" in name and notable:
            lines.append("smoke 判定與逐筆忽略項：")
            lines.append("")
            lines.append("```")
            lines.extend(notable)
            lines.append("```")
            lines.append("")
        lines.append("```")
        lines.append(tail_lines(text, LOG_TAIL_LINES) or "（空）")
        lines.append("```")
        lines.append("")
    # STEP 08: runner 事件與檔案清單
    lines.append("## 6. runner 事件（本 entry 全部 + 本次 attempt 期間的 runner 級事件）")
    lines.append("")
    lines.append(runner_events_table(ctx.get("runner_events") or []))
    lines.append("")
    lines.append("## 7. 診斷包內檔案")
    lines.append("")
    for name in ctx.get("files") or []:
        lines.append("- `%s`" % name)
    lines.append("")
    lines.append("_憑證樣式命中的行已在本檔遮罩為 [REDACTED:類別]；原檔複本未遮罩，目錄權限 700。_")
    return "\n".join(lines) + "\n"


def render_runner_summary(ctx):
    """產出 runner 級 SUMMARY.md 的全文（尚未遮罩）。

    ctx 欄位：reason, detail, fingerprint, runner_state, queue_readable, trace_text,
    runner_events, latest_session（meta dict 或 None）, files, generated_at
    """
    lines = []
    # STEP 01: 標頭
    lines.append("# 診斷：runner（%s）" % ctx["reason"])
    lines.append("")
    lines.append("- 產生時間: %s" % ctx["generated_at"])
    lines.append("- reason: `%s`" % ctx["reason"])
    lines.append("- detail: %s" % clip(ctx.get("detail") or "", 500))
    lines.append("")
    lines.append("### 環境指紋")
    lines.append("")
    lines.append(fingerprint_table(ctx.get("fingerprint")))
    lines.append("")
    # STEP 02: runner_state
    lines.append("## 1. runner_state")
    lines.append("")
    if ctx.get("queue_readable"):
        lines.append("```json")
        lines.append(json.dumps(ctx.get("runner_state") or {}, ensure_ascii=False, indent=2))
        lines.append("```")
    else:
        lines.append("（queue.json 讀不到或解析失敗——原檔已複製為 queue.json.snapshot 供檢視）")
    lines.append("")
    # STEP 03: traceback
    lines.append("## 2. traceback")
    lines.append("")
    lines.append("```")
    lines.append((ctx.get("trace_text") or "（本次不是例外，沒有 traceback）").rstrip())
    lines.append("```")
    lines.append("")
    # STEP 04: 事件與最近一次 session
    lines.append("## 3. 最近 %d 筆 runner 事件" % RUNNER_EVENTS_TAIL)
    lines.append("")
    lines.append(runner_events_table(ctx.get("runner_events") or []))
    lines.append("")
    lines.append("## 4. 最近一次 CLI 呼叫")
    lines.append("")
    latest = ctx.get("latest_session")
    if not latest:
        lines.append("（sessions/ 內沒有任何 meta 檔）")
    else:
        lines.append(
            "- entry=%s attempt=%s returncode=%s timed_out=%s duration_s=%s stream=%s"
            % (
                latest.get("entry"),
                latest.get("attempt"),
                latest.get("returncode"),
                latest.get("timed_out"),
                latest.get("duration_s"),
                latest.get("stream_path"),
            )
        )
        lines.append("- entry 級診斷包請用 `runner.py diagnose %s --attempt %s` 另外產生" % (latest.get("entry"), latest.get("attempt")))
    lines.append("")
    lines.append("## 5. 診斷包內檔案")
    lines.append("")
    for name in ctx.get("files") or []:
        lines.append("- `%s`" % name)
    lines.append("")
    lines.append("_憑證樣式命中的行已在本檔遮罩為 [REDACTED:類別]；原檔複本未遮罩，目錄權限 700。_")
    return "\n".join(lines) + "\n"


# ================================================================ 凍結（產診斷包）


def make_bundle_dir(state_dir, name):
    """建立 diagnostics/<name>/（同名已存在就加序號），權限 700，回傳完整路徑。"""
    # STEP 01: 找一個不撞名的目錄名（同一秒內兩次凍結會撞）
    root = os.path.join(state_dir, DIAGNOSTICS_DIR_NAME)
    os.makedirs(root, exist_ok=True)
    candidate = os.path.join(root, name)
    suffix = 1
    while os.path.exists(candidate):
        suffix += 1
        candidate = os.path.join(root, "%s-%d" % (name, suffix))
    # STEP 02: 建立並鎖權限（makedirs 的 mode 會被 umask 影響，再 chmod 一次）
    os.makedirs(candidate, mode=BUNDLE_DIR_MODE)
    os.chmod(candidate, BUNDLE_DIR_MODE)
    return candidate


def copy_into(bundle_dir, source, target_name=None, gzip_copy=False):
    """把 source 複製進診斷包；gzip_copy 為真時壓縮。回傳診斷包內檔名，來源不存在回 None。"""
    # STEP 01: 來源不存在不算錯（例如沒走到 build 就沒有 build log）
    if not source or not os.path.exists(source):
        return None
    # STEP 02: 複製（stream 用 gzip，其餘原樣）；複製失敗回 None 讓 SUMMARY 的檔案清單少一項
    name = target_name or os.path.basename(source)
    target = os.path.join(bundle_dir, name)
    try:
        if gzip_copy:
            with open(source, "rb") as src, gzip.open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            shutil.copyfile(source, target)
    except OSError:
        return None
    return name


def write_bundle_file(bundle_dir, name, text):
    """把文字寫進診斷包；回傳檔名。"""
    with open(os.path.join(bundle_dir, name), "w", encoding="utf-8") as handle:
        handle.write(text)
    return name


def freeze_entry(state_dir, entry, attempt, reason, detail, fingerprint, secret_labels):
    """把一個 entry 某次呼叫的全部證據凍結成診斷包，回傳診斷包完整路徑。

    entry 是 queue 內的 entry dict（至少要有 id）；attempt 是 sessions 檔名用的次數。
    """
    entry_id = entry.get("id")
    bundle_dir = make_bundle_dir(state_dir, "%s-%s-%s" % (safe_name(entry_id), attempt, compact_ts()))
    files = []
    # STEP 01: 複製原始檔（stream 壓縮、其餘原樣）
    session = session_files(state_dir, entry_id, attempt)
    name = copy_into(bundle_dir, session["stream"], STREAM_COPY_NAME, gzip_copy=True)
    if name:
        files.append(name)
    name = copy_into(bundle_dir, session["meta"], META_COPY_NAME)
    if name:
        files.append(name)
    logs = []
    for log_path in session["logs"]:
        name = copy_into(bundle_dir, log_path)
        if name:
            files.append(name)
            logs.append((os.path.basename(log_path), read_text(log_path) or ""))
    for suffix in ("-progress.md", "-contract.md", "-report.md"):
        name = copy_into(bundle_dir, os.path.join(state_dir, "%s%s" % (entry_id, suffix)))
        if name:
            files.append(name)
    # STEP 02: queue entry 快照與 runner 事件切片
    files.append(write_bundle_file(bundle_dir, QUEUE_ENTRY_COPY_NAME, json.dumps(entry, ensure_ascii=False, indent=2) + "\n"))
    entry_events = read_runner_events(state_dir, entry_id=entry_id)
    since = attempt_started_iso(entry_events, attempt)
    runner_events = read_runner_events(state_dir, entry_id=entry_id, since_iso=since)
    files.append(
        write_bundle_file(
            bundle_dir,
            RUNNER_EVENTS_COPY_NAME,
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in runner_events),
        )
    )
    # STEP 03: 解析 stream 與 progress，組 SUMMARY
    events, bad_lines, stream_error = read_stream(session["stream"])
    meta = read_json(session["meta"]) if session["meta"] else None
    progress_text = read_text(os.path.join(state_dir, "%s-progress.md" % entry_id))
    ctx = {
        "entry": entry,
        "entry_id": entry_id,
        "attempt": attempt,
        "reason": reason,
        "detail": detail,
        "fingerprint": fingerprint,
        "meta": meta,
        "events": events,
        "bad_lines": bad_lines,
        "stream_error": stream_error,
        "result": last_result_event(events),
        "init": init_event(events),
        "timeline": build_timeline(events),
        "stderr": (meta or {}).get("stderr", ""),
        "progress": parse_progress(progress_text) if progress_text is not None else None,
        "has_contract": os.path.exists(os.path.join(state_dir, "%s-contract.md" % entry_id)),
        "has_report": os.path.exists(os.path.join(state_dir, "%s-report.md" % entry_id)),
        "logs": logs,
        "runner_events": runner_events,
        "files": files + [SUMMARY_NAME],
        "generated_at": now_iso(),
    }
    summary = mask_text(render_entry_summary(ctx), secret_labels)
    write_bundle_file(bundle_dir, SUMMARY_NAME, summary)
    return bundle_dir


def refresh_entry_snapshot(bundle_dir, entry):
    """apply_outcome 寫回 queue 之後，用最新的 entry 覆寫診斷包內的 queue-entry.json。"""
    # STEP 01: 診斷包不存在（凍結失敗）就不做事；覆寫失敗也不影響主流程
    if not bundle_dir or not os.path.isdir(bundle_dir):
        return
    try:
        write_bundle_file(bundle_dir, QUEUE_ENTRY_COPY_NAME, json.dumps(entry, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        pass


def latest_session_meta(state_dir):
    """回傳 sessions/ 內修改時間最新的 meta 檔內容；沒有回 None。"""
    # STEP 01: 沒有 sessions/ 就沒有紀錄
    directory = sessions_dir(state_dir)
    if not os.path.isdir(directory):
        return None
    # STEP 02: 依 mtime 找最新的 meta 檔
    newest = None
    newest_mtime = -1
    for name in os.listdir(directory):
        if not name.endswith(META_SUFFIX):
            continue
        full = os.path.join(directory, name)
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest = full
    return read_json(newest) if newest else None


def freeze_runner(state_dir, reason, detail, fingerprint, secret_labels, trace_text=None):
    """把 runner 級事件（paused／crash）的證據凍結成診斷包，回傳完整路徑。

    不依賴 queue.json 可讀：讀不到就原檔複製當證據、SUMMARY 標明讀不到。
    """
    bundle_dir = make_bundle_dir(state_dir, "runner-%s-%s" % (compact_ts(), safe_name(reason)))
    files = []
    # STEP 01: queue.json 原檔（即使損毀也複製）、deadletter、traceback
    name = copy_into(bundle_dir, os.path.join(state_dir, "queue.json"), QUEUE_COPY_NAME)
    if name:
        files.append(name)
    name = copy_into(bundle_dir, os.path.join(state_dir, "notify-deadletter.jsonl"))
    if name:
        files.append(name)
    if trace_text:
        files.append(write_bundle_file(bundle_dir, TRACE_COPY_NAME, trace_text))
    # STEP 02: runner 事件尾端
    runner_events = read_runner_events(state_dir, tail=RUNNER_EVENTS_TAIL)
    files.append(
        write_bundle_file(
            bundle_dir,
            RUNNER_EVENTS_COPY_NAME,
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in runner_events),
        )
    )
    # STEP 03: SUMMARY
    queue = read_json(os.path.join(state_dir, "queue.json"))
    ctx = {
        "reason": reason,
        "detail": detail,
        "fingerprint": fingerprint,
        "runner_state": (queue or {}).get("runner_state"),
        "queue_readable": queue is not None,
        "trace_text": trace_text,
        "runner_events": runner_events,
        "latest_session": latest_session_meta(state_dir),
        "files": files + [SUMMARY_NAME],
        "generated_at": now_iso(),
    }
    summary = mask_text(render_runner_summary(ctx), secret_labels)
    write_bundle_file(bundle_dir, SUMMARY_NAME, summary)
    return bundle_dir


def write_tarball(bundle_dir):
    """把診斷包目錄打成同名 .tar.gz（放在 diagnostics/ 下），回傳 tar 路徑。"""
    # STEP 01: 以目錄名當 tar 內的頂層目錄，權限 600
    tar_path = bundle_dir.rstrip(os.sep) + ".tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(bundle_dir, arcname=os.path.basename(bundle_dir))
    os.chmod(tar_path, 0o600)
    return tar_path
