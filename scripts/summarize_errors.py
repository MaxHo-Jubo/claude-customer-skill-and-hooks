#!/usr/bin/env python3
"""
summarize_errors.py — reads ~/.claude/.learnings/ERRORS.jsonl and prints a human-readable
review report grouped by skill, tool, and recurring error pattern.

Usage:
    python3 ~/.claude/scripts/summarize_errors.py [--days N] [--min-count N]

Options:
    --days N        Only consider errors from the last N days (default: 30)
    --min-count N   Only show patterns with at least N occurrences (default: 2)
"""
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict


def parse_args():
    p = argparse.ArgumentParser(description="Summarize skill error logs")
    p.add_argument("--days", type=int, default=30, help="Look-back window in days")
    p.add_argument("--min-count", type=int, default=2, help="Minimum occurrences to surface")
    p.add_argument("--log", type=Path, default=Path.home() / ".claude" / ".learnings" / "ERRORS.jsonl")
    return p.parse_args()


def load_records(log_path: Path, since: datetime) -> list[dict]:
    if not log_path.exists():
        print(f"[!] Log not found: {log_path}", file=sys.stderr)
        return []
    records = []
    with log_path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(rec["ts"])
                if ts >= since:
                    records.append(rec)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"[!] Skipping malformed line {lineno}: {e}", file=sys.stderr)
    return records


def first_line(text: str) -> str:
    """Return the first non-empty line of a multi-line string."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return text[:120]


def summarize(records: list[dict], min_count: int) -> None:
    if not records:
        print("No errors in the selected window. 🎉")
        return

    total = len(records)
    print(f"\n{'='*60}")
    print(f"  SKILL ERROR SUMMARY  ({total} errors total)")
    print(f"{'='*60}\n")

    # --- By context (向下相容：舊記錄用 "skill"，新記錄用 "context") ---
    by_ctx: dict[str, list] = defaultdict(list)
    for r in records:
        ctx = r.get("context") or r.get("skill", "unknown")
        by_ctx[ctx].append(r)

    print("## Errors by context\n")
    for ctx, recs in sorted(by_ctx.items(), key=lambda x: -len(x[1])):
        pct = len(recs) / total * 100
        print(f"  {ctx:<40} {len(recs):>4} errors  ({pct:.0f}%)")

    # --- By tool ---
    by_tool: dict[str, list] = defaultdict(list)
    for r in records:
        by_tool[r.get("tool", "unknown")].append(r)

    print("\n## Errors by tool\n")
    for tool, recs in sorted(by_tool.items(), key=lambda x: -len(x[1])):
        pct = len(recs) / total * 100
        print(f"  {tool:<30} {len(recs):>4} errors  ({pct:.0f}%)")

    # --- Recurring patterns (first line of error message) ---
    by_pattern: dict[str, list] = defaultdict(list)
    for r in records:
        pattern = first_line(r.get("error", ""))
        if pattern:
            by_pattern[pattern].append(r)

    print(f"\n## Recurring error patterns (≥{min_count} occurrences)\n")
    found_any = False
    for pattern, recs in sorted(by_pattern.items(), key=lambda x: -len(x[1])):
        if len(recs) < min_count:
            continue
        found_any = True
        skills_affected = sorted(set(r.get("context") or r.get("skill", "?") for r in recs))
        print(f"  [{len(recs)}x]  {pattern}")
        print(f"         Skills: {', '.join(skills_affected)}")
        print()
    if not found_any:
        print(f"  No patterns with ≥{min_count} occurrences. Good sign!\n")

    # --- Recent errors (last 5) ---
    print("## Last 5 errors\n")
    for r in records[-5:]:
        ts = r.get("ts", "")[:19].replace("T", " ")
        skill = r.get("context") or r.get("skill", "?")
        tool = r.get("tool", "?")
        error = first_line(r.get("error", "(no message)"))
        print(f"  {ts}  [{skill}] {tool}: {error}")
    print()


def main():
    args = parse_args()
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    records = load_records(args.log, since)
    summarize(records, args.min_count)


if __name__ == "__main__":
    main()
