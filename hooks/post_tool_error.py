#!/usr/bin/env python3
"""
PostToolUseFailure hook — appends a structured JSONL record to ~/.claude/.learnings/ERRORS.jsonl
whenever a tool call fails.

Claude Code fires PostToolUseFailure only for failed tool calls; PostToolUse only fires on success,
so registering this script under PostToolUse never saw a single failure (fixed 2026-09-14).
Permission/sandbox-blocked calls fire neither event and are not recorded.
Pipe: Claude Code → stdin (JSON) → this script → appends to ERRORS.jsonl

Input schema (Claude Code 2.1.270, verified 2026-09-14):
{
  "hook_event_name": "PostToolUseFailure",
  "tool_name": "Bash",
  "tool_input": {"command": "..."},
  "tool_use_id": "...",
  "error": "Exit code 42\\nboom",
  "is_interrupt": false,
  "duration_ms": 12
}
"""
import json
import re
import sys
import os
from datetime import datetime, timezone
from pathlib import Path


# Max characters to store from error output (keeps the log lean)
ERROR_TRUNCATE = 500

# skill 目錄路徑 pattern，用於從 tool_input 推斷 active skill
SKILL_PATH_RE = re.compile(r"/skills/([^/]+)/")
# hook/script 路徑 pattern
HOOK_PATH_RE = re.compile(r"/(?:hooks|scripts)/([^/]+?)(?:\.\w+)?$")
# Bash 失敗時 error 欄位開頭的 exit code 格式（如 "Exit code 42\nboom"）；其他工具沒有
EXIT_CODE_RE = re.compile(r"^Exit code (\d+)")


def infer_context(tool_input: dict, tool_name: str) -> str:
    """
    從 tool_input 推斷當前操作的 context（skill 名稱或檔案路徑）。
    優先序：skill 目錄 > hook/script 名稱 > 檔案路徑摘要 > unknown
    """
    # STEP 01: 取得可分析的路徑字串
    raw = (
        tool_input.get("command")
        or tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("url")
        or ""
    )

    # STEP 02: 嘗試從路徑提取 skill 名稱
    m = SKILL_PATH_RE.search(raw)
    if m:
        return f"skill:{m.group(1)}"

    # STEP 03: 嘗試從 hook/script 路徑提取名稱
    m = HOOK_PATH_RE.search(raw)
    if m:
        return f"hook:{m.group(1)}"

    # STEP 04: 有檔案路徑但不在 skill/hook 目錄，取最後兩層作為 context
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if file_path:
        parts = Path(file_path).parts
        # 取最後兩層（如 "src/utils"）
        return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]

    return "unknown"


def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        # Not a valid hook call — exit silently, never block Claude
        sys.exit(0)

    # Claude Code 在取消的 tool 或部分 MCP tool 會送 null；全部視為沒東西可記
    if not isinstance(hook_input, dict):
        sys.exit(0)

    # 使用者中斷不是工具失敗，不記錄
    if hook_input.get("is_interrupt"):
        sys.exit(0)

    # 失敗原因；PostToolUseFailure 必帶此欄位
    error_raw = hook_input.get("error")
    if not isinstance(error_raw, str) or not error_raw.strip():
        # 缺 error 代表掛錯事件或 schema 改了——報錯讓 hook-error-wrapper 記下，不可靜默略過（舊版就是這樣空轉）
        print(
            f"post_tool_error: 輸入缺少 error 欄位（hook_event_name={hook_input.get('hook_event_name')}）",
            file=sys.stderr,
        )
        sys.exit(1)

    # 只有 Bash 類失敗帶 exit code，Read/MCP 等工具失敗記為 None
    exit_match = EXIT_CODE_RE.match(error_raw)
    exit_code = int(exit_match.group(1)) if exit_match else None

    # Global learnings directory under ~/.claude/
    log_path = Path.home() / ".claude" / ".learnings" / "ERRORS.jsonl"

    # Ensure the directory exists (idempotent)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Truncate the error message (keeps the log lean)
    error_text = error_raw.strip()
    if len(error_text) > ERROR_TRUNCATE:
        error_text = error_text[:ERROR_TRUNCATE] + "…"

    tool_name = hook_input.get("tool_name", "unknown")
    tool_input = hook_input.get("tool_input", {})

    record = {
        "ts":        datetime.now(timezone.utc).isoformat(),
        "context":   infer_context(tool_input, tool_name),
        "tool":      tool_name,
        "exit_code": exit_code,
        # Best-effort: grab the command or path from the tool input
        "cmd":       (
            tool_input.get("command")
            or tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("url")
            or ""
        )[:300],
        "error":     error_text,
    }

    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Never crash Claude Code even if the log write fails
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
