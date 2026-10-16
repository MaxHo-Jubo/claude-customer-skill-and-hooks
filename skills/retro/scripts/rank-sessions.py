#!/usr/bin/env python3
"""依成本權重列出近 N 天 token 最高的 Claude Code session，供 retro 挑選檢討對象。

用法：python3 -I rank-sessions.py [--days 7] [--top 3]   (--top 0 = 全部)
輸出：TSV，欄位 = 排名、成本權重、turn 數、專案目錄、最後寫入時間、jsonl 絕對路徑
"""

import argparse
import glob
import json
import os
import time

# 專案目錄名稱前綴為此者是 scratchpad／探針產生的暫存 session，不算工作 session
SCRATCH_PREFIX = "-private-tmp"
# 各 usage 欄位換算成「input token 等價量」的權重（倍率以 token-analyze 為準：cache 寫入 2x、讀取 0.1x、output 5x）
WEIGHTS = {
    "input_tokens": 1.0,
    "cache_creation_input_tokens": 2.0,
    "cache_read_input_tokens": 0.1,
    "output_tokens": 5.0,
}
# 一天的秒數，用於把 --days 換算成 mtime 門檻
SECONDS_PER_DAY = 86400


def score_session(path):
    """計算單一 transcript 的成本權重。

    同一個 API 回應可能被拆成多筆 assistant 紀錄（每個 content block 一筆），
    以 message.id 去重、保留最後一筆，避免重複計價。

    @param {str} path transcript jsonl 絕對路徑
    @returns {tuple} (成本權重, 去重後的 assistant turn 數)
    """
    # STEP 01: 逐行解析，依 message.id 保留最後一筆 usage
    last_usage = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            msg = rec.get("message")
            if rec.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            key = msg.get("id") or rec.get("requestId") or rec.get("uuid")
            last_usage[key] = usage
    # STEP 02: 加權加總
    total = sum(
        (u.get(field) or 0) * weight
        for u in last_usage.values()
        for field, weight in WEIGHTS.items()
    )
    return total, len(last_usage)


def main():
    """解析參數、掃描 transcript、依成本權重排序後輸出 TSV。"""
    # STEP 01: 解析參數
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args()
    cutoff = time.time() - args.days * SECONDS_PER_DAY
    root = os.path.expanduser("~/.claude/projects")
    # STEP 02: 收集期間內有寫入的工作 session
    rows = []
    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        proj = os.path.basename(os.path.dirname(path))
        mtime = os.path.getmtime(path)
        if proj.startswith(SCRATCH_PREFIX) or mtime < cutoff:
            continue
        weight, turns = score_session(path)
        rows.append((weight, turns, proj, mtime, path))
    # STEP 03: 排序並輸出（成本權重由高到低）
    rows.sort(reverse=True)
    if args.top > 0:
        rows = rows[: args.top]
    for rank, (weight, turns, proj, mtime, path) in enumerate(rows, 1):
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        print("\t".join([str(rank), "%.0f" % weight, str(turns), proj, stamp, path]))


if __name__ == "__main__":
    main()
