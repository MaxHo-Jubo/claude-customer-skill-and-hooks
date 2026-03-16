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
import sys
import os
from datetime import datetime, timezone
from pathlib import Path


# Max characters to store from error output (keeps the log lean)
ERROR_TRUNCATE = 500


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

    tool_input = hook_input.get("tool_input", {})

    record = {
        "ts":        datetime.now(timezone.utc).isoformat(),
        "skill":     os.environ.get("CLAUDE_SKILL_NAME", "unknown"),
        "tool":      hook_input.get("tool_name", "unknown"),
        "exit_code": exit_code,
        # Best-effort: grab the command or path from the tool input
        "cmd":       (
            tool_input.get("command")
            or tool_input.get("path")
            or tool_input.get("url")
            or ""
        )[:300],
        "error":     error_text,
        "task_hint": os.environ.get("CLAUDE_TASK_DESCRIPTION", ""),
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
