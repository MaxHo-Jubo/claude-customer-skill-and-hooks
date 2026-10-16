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
# --days 預設值（天）：只看最近一週有寫入的 session，對應 weekly-review 的回顧週期
DEFAULT_DAYS = 7
# --top 預設值（筆）：未指定時輸出成本權重前 3 名，對應 weekly-review STEP 09 的「前 3 名」選項；可用 --top 覆寫，0 表示全部
DEFAULT_TOP = 3
# transcript 根目錄：Claude Code 把每個專案的 session 存在 <根>/<專案目錄>/<uuid>.jsonl
PROJECTS_ROOT = os.path.expanduser("~/.claude/projects")


def score_session(path):
    """計算單一 transcript 的成本權重。

    同一個 API 回應可能被拆成多筆 assistant 紀錄（每個 content block 一筆），
    以 message.id 去重、保留最後一筆，避免重複計價。

    @param {str} path transcript jsonl 絕對路徑
    @returns {tuple} (成本權重, 去重後的 assistant turn 數)
    """
    # STEP 01: 逐行解析，依 message.id 保留最後一筆 usage
    # message.id（缺則 requestId、uuid）-> 該回應的 usage 欄位 dict
    last_usage = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                # 單行 JSON 解析結果；合法 JSON 但不是物件（null、[]、42）的行直接略過
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            # 該行的 message 物件；非 assistant 或沒有 message 的行略過
            msg = rec.get("message")
            if rec.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            # 該回應的 token 用量 dict；缺漏的行略過
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            # 去重鍵：同一 API 回應的多個 content block 共用 message.id
            key = msg.get("id") or rec.get("requestId") or rec.get("uuid")
            last_usage[key] = usage
    # STEP 02: 加權加總
    # 全部回應的成本權重總和（input token 等價量）
    total = sum(
        (u.get(field) or 0) * weight
        for u in last_usage.values()
        for field, weight in WEIGHTS.items()
    )
    return total, len(last_usage)


def main():
    """解析參數、掃描 transcript、依成本權重排序後輸出 TSV。"""
    # STEP 01: 解析參數
    # 命令列解析器
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--top", type=int, default=DEFAULT_TOP)
    # 解析後的參數（days 天數、top 筆數，0 表示全部）
    args = ap.parse_args()
    # mtime 門檻（epoch 秒）：早於此的 transcript 不納入
    cutoff = time.time() - args.days * SECONDS_PER_DAY
    # STEP 02: 收集期間內有寫入的工作 session
    # 每筆為 (成本權重, turn 數, 專案目錄名, mtime, jsonl 路徑)；用推導式一次建好，不原地 append
    scored = [
        (*score_session(path), os.path.basename(os.path.dirname(path)), os.path.getmtime(path), path)
        for path in glob.glob(os.path.join(PROJECTS_ROOT, "*", "*.jsonl"))
        if not os.path.basename(os.path.dirname(path)).startswith(SCRATCH_PREFIX)
        and os.path.getmtime(path) >= cutoff
    ]
    # STEP 03: 排序並輸出（成本權重由高到低；sorted 回傳新清單，不改動 scored）
    # 排序後、依 --top 截斷的結果
    ranked = sorted(scored, reverse=True)
    if args.top > 0:
        ranked = ranked[: args.top]
    for rank, (weight, turns, proj, mtime, path) in enumerate(ranked, 1):
        # 人類可讀的最後寫入時間（本地時區）
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        print("\t".join([str(rank), "%.0f" % weight, str(turns), proj, stamp, path]))


if __name__ == "__main__":
    main()
