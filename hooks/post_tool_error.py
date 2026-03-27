#!/usr/bin/env python3
"""
PostToolUse hook — appends a structured JSONL record to ~/.claude/.learnings/ERRORS.jsonl
whenever a tool call exits with a non-zero code.

Claude Code runs this automatically after every tool execution.
Pipe: Claude Code → stdin (JSON) → this script → appends to ERRORS.jsonl

Input schema (from Claude Code):
{
  "tool_name": "Bash",
  "tool_input": {"command": "..."},
  "tool_response": {
    "exit_code": 1,
    "stdout": "...",
    "stderr": "..."
  }
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

    tool_response = hook_input.get("tool_response", {})
    exit_code = tool_response.get("exit_code")

    # Only log actual failures (non-zero exit code)
    if not isinstance(exit_code, int) or exit_code == 0:
        sys.exit(0)

    # Global learnings directory under ~/.claude/
    log_path = Path.home() / ".claude" / ".learnings" / "ERRORS.jsonl"

    # Ensure the directory exists (idempotent)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the error message from stdout + stderr
    stdout = tool_response.get("stdout", "") or ""
    stderr = tool_response.get("stderr", "") or ""
    error_text = (stdout + "\n" + stderr).strip()
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
