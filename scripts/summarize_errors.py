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
                # 舊 schema 讀入時統一正規化，下游只認 ts／context：
                # 時間欄位舊紀錄（如 save-progress 2026-09-15）用 timestamp，兩者皆無仍走 KeyError 顯性報出；
                # context 欄位 hook 層舊紀錄用 skill
                rec = {
                    **rec,
                    "ts": rec.get("ts") or rec["timestamp"],
                    "context": rec.get("context") or rec.get("skill") or "unknown",
                }
                ts = datetime.fromisoformat(rec["ts"])
                if ts >= since:
                    records.append(rec)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"[!] Skipping malformed line {lineno}: {e}", file=sys.stderr)
    return records


# 錯誤摘要每一行的截斷長度
LINE_MAX = 120


def first_line(text: str) -> str:
    """Return the first non-empty line of a multi-line string."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:LINE_MAX]
    return text[:LINE_MAX]


def pattern_key(text: str) -> str:
    """
    錯誤分組鍵。Bash 錯誤第一行固定是 'Exit code N'，只看第一行會把所有 Bash 失敗併成一組，
    所以改用 'Exit code N | 下一個非空行'；其他錯誤沿用第一行。

    @param text error 欄位原文
    @returns 分組用字串；空字串代表 error 為空
    """
    # STEP 01: 取所有非空行
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # STEP 02: Bash 錯誤帶上第二行，其餘取第一行
    if len(lines) >= 2 and lines[0].startswith("Exit code "):
        return f"{lines[0]} | {lines[1][:LINE_MAX]}"
    return first_line(text)


def summarize(records: list[dict], min_count: int) -> None:
    if not records:
        print("No errors in the selected window. 🎉")
        return

    total = len(records)
    print(f"\n{'='*60}")
    print(f"  SKILL ERROR SUMMARY  ({total} errors total)")
    print(f"{'='*60}\n")

    # --- By context（舊 schema 的 skill 已在 load_records 正規化成 context） ---
    by_ctx: dict[str, list] = defaultdict(list)
    for r in records:
        by_ctx[r["context"]].append(r)

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
    # 空 error 必須顯性歸類，不能靜默跳過：hook 阻擋型記錄的 reason 走 stdout，
    # wrapper 只捕 stderr，所以 error 是空字串。舊版把它們跳過，導致最大宗的
    # pattern 完全不出現在統計裡，還印出 "Good sign!"（2026-08-14 實測：29/53 筆被漏報）
    EMPTY_PATTERN = "(empty error message — 多為 hook 阻擋，reason 走 stdout 未被捕獲)"
    by_pattern: dict[str, list] = defaultdict(list)
    for r in records:
        pattern = pattern_key(r.get("error", "")) or EMPTY_PATTERN
        by_pattern[pattern].append(r)

    print(f"\n## Recurring error patterns (≥{min_count} occurrences)\n")
    found_any = False
    for pattern, recs in sorted(by_pattern.items(), key=lambda x: -len(x[1])):
        if len(recs) < min_count:
            continue
        found_any = True
        skills_affected = sorted(set(r["context"] for r in recs))
        print(f"  [{len(recs)}x]  {pattern}")
        print(f"         Skills: {', '.join(skills_affected)}")
        print()
    if not found_any:
        print(f"  No patterns with ≥{min_count} occurrences. Good sign!\n")

    # --- Recent errors (last 5) ---
    print("## Last 5 errors\n")
    for r in records[-5:]:
        ts = r["ts"][:19].replace("T", " ")
        skill = r["context"]
        tool = r.get("tool", "?")
        # .get 的 default 只在 key 不存在時觸發；這批記錄是 key 在、值為 ""，故需再 or 一次
        error = first_line(r.get("error") or "") or "(no message)"
        print(f"  {ts}  [{skill}] {tool}: {error}")
    print()


def main():
    args = parse_args()
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    records = load_records(args.log, since)
    summarize(records, args.min_count)


if __name__ == "__main__":
    main()
