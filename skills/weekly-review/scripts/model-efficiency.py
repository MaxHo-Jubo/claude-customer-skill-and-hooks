#!/usr/bin/env python3
"""彙整近 N 天 Claude Code session 的模型使用效率，供 weekly-review STEP 10 產出報告。

用法：python3 -I model-efficiency.py [--days 7]
輸出：markdown 報告到 stdout；統計不到任何 assistant 訊息時 exit 1
涵蓋：模型×主/子 session token 占比、專案占比、context 長度分桶、Agent 呼叫的 model 分布、
      advisor 呼叫次數、Haiku 任務清單（只列清單，是否為機械性工作由使用者判斷）
"""

import argparse
import collections
import datetime
import glob
import json
import math
import os
import statistics
import sys

# transcript 根目錄：Claude Code 把每個專案的 session 存在 <根>/<專案目錄>/<uuid>.jsonl，子 agent 在 <uuid>/subagents/
PROJECTS_ROOT = os.path.expanduser("~/.claude/projects")
# scratchpad／探針產生的暫存 session 的專案目錄前綴，不算工作 session
SCRATCH_PREFIX = "-private-tmp"
# claude-mem observer 背景 session 的專案目錄關鍵字，獨立成一列，不混進工作 session 的 context 統計
OBSERVER_KEYWORD = "observer"
# --days 預設值（天），對應 weekly-review 的回顧週期
DEFAULT_DAYS = 7
# 一天的秒數，用於把 --days 換算成 mtime 預篩門檻
SECONDS_PER_DAY = 86400
# context 分桶：(上限 token, 桶名稱)，由小到大，最後一桶用 math.inf 當上限收尾
CTX_BUCKETS = [(100_000, "<100k"), (200_000, "100-200k"), (400_000, "200-400k"), (math.inf, ">400k")]
# 計算 session 回合數／首輪 context 時，少於此回合數的 session 不納入（避免短暫探針拉低中位數）
MIN_TURNS = 5
# 專案占比表只列前幾名
TOP_PROJECTS = 8
# Haiku 任務清單中 prompt 開頭擷取的字數
PROMPT_HEAD = 110
# 子 session 首句擷取的字數
HEAD_CHARS = 80
# session 短碼取檔名（uuid）的前幾碼
SID_LEN = 8
# 專案占比表中專案名稱顯示的寬度（字元）
PROJ_NAME_WIDTH = 48
# Haiku 任務清單中 description 顯示的寬度（字元）
DESC_WIDTH = 40
# assistant 記錄的 usage 要至少有其中一個欄位才算有用量資料（全缺的記錄不計價，避免以 0 代替未知用量）
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
# 專案目錄名是「家目錄路徑把 / 換成 -」再接 Documents-：專案占比表顯示時去掉這段固定前綴（由 HOME 推導，不寫死使用者名稱）
PROJECT_DIR_PREFIX = os.path.expanduser("~").replace("/", "-") + "-Documents-"
# Agent 工具在 transcript 的名稱（舊版叫 Task）
AGENT_TOOL_NAMES = ("Agent", "Task")
# advisor 是 server tool，content block 類型是 server_tool_use（不是 tool_use），名稱為 advisor
ADVISOR_BLOCK_TYPE = "server_tool_use"
# Agent 呼叫沒有明確帶 model 參數時的顯示名稱：實際模型可能是繼承主對話模型，也可能是該 agent 定義檔自帶的預設（例如 multi-repo-commit-scanner 預設 haiku），腳本不解析 agent 定義，所以只能標「未指定」
UNSPECIFIED_LABEL = "(未指定)"
# 判斷「Haiku 系列」的子字串：Agent 的 model 參數（別名 haiku）與 message.model（完整 ID）都含它，版本換號也不用改
HAIKU_KEYWORD = "haiku"
# p90 的分位數
P90 = 0.9


def parse_ts(raw):
    """把 transcript 的 ISO 時間字串轉成 epoch 秒。

    @param {str} raw 例如 2026-10-19T09:37:12.345Z
    @returns {float|None} epoch 秒；缺漏或無法解析回 None
    """
    # STEP 01: 解析；格式不符的行當作沒有時間戳
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def iter_records(path, stats):
    """逐行讀 jsonl，回傳合法的物件列；JSON 解析失敗與合法但不是物件的行都計入 stats['bad_lines']。

    @param {str} path transcript 絕對路徑
    @param {dict} stats 自檢計數器（會被就地更新）
    @returns {iterator} dict 記錄
    """
    # STEP 01: 逐行解析，解析失敗與非物件行都只計數不中斷
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                # 單行解析結果
                rec = json.loads(line)
            except ValueError:
                stats["bad_lines"] += 1
                continue
            if not isinstance(rec, dict):
                stats["bad_lines"] += 1
                continue
            yield rec


def ctx_bucket(tokens):
    """依 CTX_BUCKETS 把 context token 數歸桶。

    @param {int} tokens 該回合送進模型的 context 總量
    @returns {str} 桶名稱
    """
    # STEP 01: 由小到大找第一個上限大於 tokens 的桶（最後一桶上限是 inf，必有命中）
    return next(name for limit, name in CTX_BUCKETS if tokens < limit)


def first_user_text(rec):
    """取 user 記錄的文字內容。

    @param {dict} rec transcript 記錄
    @returns {str} 純文字（block 清單則串接 text 欄位）
    """
    # STEP 01: message 與 content 都可能缺漏或是 null；content 可能是字串或 block 清單
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def scan_blocks(msg, kind, sid, acc):
    """掃一筆 assistant 記錄的 content block，累計 advisor 與 Agent 呼叫。

    同一個 API 回應會被拆成多筆記錄（每個 content block 一筆），後面的 chunk 才有工具呼叫，
    所以每一筆都要掃，不能只看去重後保留的那筆。

    @param {dict} msg assistant 記錄的 message
    @param {str} kind main 或 sub，記錄呼叫端
    @param {str} sid session 短碼
    @param {dict} acc 累計容器（會被就地更新）：stats、advisor_by_sid、agent_calls、haiku_tasks
    @returns {None}
    """
    # STEP 01: content 不是 block 清單就沒有工具呼叫
    content = msg.get("content")
    if not isinstance(content, list):
        return
    # STEP 02: 逐 block 累計
    for blk in content:
        if not isinstance(blk, dict):
            continue
        acc["stats"]["blocks_scanned"] += 1
        btype, name = blk.get("type"), blk.get("name")
        if btype == ADVISOR_BLOCK_TYPE and name == "advisor":
            acc["advisor_by_sid"][sid] += 1
        if btype != "tool_use" or name not in AGENT_TOOL_NAMES:
            continue
        # Agent 呼叫的參數：subagent_type、model、description、prompt；input 或各欄位可能缺漏或型別不對，一律轉成字串
        inp = blk.get("input") if isinstance(blk.get("input"), dict) else {}
        stype = str(inp.get("subagent_type") or "default")
        model = str(inp.get("model") or UNSPECIFIED_LABEL)
        acc["agent_calls"][(stype, model, kind)] += 1
        if HAIKU_KEYWORD in model:
            acc["haiku_tasks"][(stype, str(inp.get("description") or ""), str(inp.get("prompt") or "")[:PROMPT_HEAD].replace("\n", " "))] += 1


def collect(days):
    """掃描期間內的 transcript，彙整所有統計。

    同一個 API 回應會被拆成多筆 assistant 記錄（每個 content block 一筆）：token 以 message.id 分組、
    取最後一筆的 usage（串流過程中 output_tokens 會更新，最後一筆才是最終值；input／cache 欄位各筆相同）；
    缺 message.id 的記錄無法分組，逐筆計價並計入 stats['no_id'] 顯示在自檢。

    @param {int} days 回顧天數
    @returns {dict} 彙整結果
    """
    # STEP 01: 初始化計數器
    # 自檢計數：掃描檔數、壞行數、assistant 記錄數、去重後訊息數、缺 id／缺時間戳的記錄數
    stats = collections.Counter()
    # (模型, main|sub|obs) -> 各 token 欄位加總
    by_model = collections.defaultdict(collections.Counter)
    # 專案目錄 -> 各 token 欄位加總
    by_proj = collections.defaultdict(collections.Counter)
    # 主 session 工作回合的 context 分桶 -> 回合數 n 與 cache read cr 加總
    ctx_stat = collections.defaultdict(collections.Counter)
    # 每個 ≥MIN_TURNS 回合的主 session 的逐回合 context 量（首輪取 [0]、回合數取 len）
    sessions = []
    # 累計容器：交給 scan_blocks 就地更新
    acc = {
        "stats": stats,
        # session 短碼 -> advisor 呼叫次數
        "advisor_by_sid": collections.Counter(),
        # (subagent_type, model, 呼叫端 main|sub) -> 次數
        "agent_calls": collections.Counter(),
        # Haiku 任務：(subagent_type, description, prompt 開頭) -> 次數
        "haiku_tasks": collections.Counter(),
    }
    # Haiku 子 session 首句 -> 次數（涵蓋 agent 定義預設 haiku 而沒帶 model 參數的情況）
    haiku_sub_heads = collections.Counter()
    # 期間起點的 epoch 秒
    cutoff = datetime.datetime.now().timestamp() - days * SECONDS_PER_DAY

    # STEP 02: 逐檔處理
    for path in glob.glob(PROJECTS_ROOT + "/**/*.jsonl", recursive=True):
        if os.path.getmtime(path) < cutoff:
            continue
        stats["files"] += 1
        # 檔案層常數：是否為子 agent transcript、所屬專案目錄、呼叫端標籤、by_model 的來源標籤、session 短碼
        is_sub = "/subagents/" in path
        proj = path[len(PROJECTS_ROOT) + 1:].split("/")[0]
        is_obs = OBSERVER_KEYWORD in proj
        kind = "sub" if is_sub else "main"
        src = "obs" if is_obs else kind
        sid = (path.split("/")[-3] if is_sub else os.path.basename(path))[:SID_LEN]
        # 是否為「主 session 工作回合」：計入 context 統計（子 agent、observer、暫存 session 都不算）
        is_work = not (is_sub or is_obs or proj.startswith(SCRATCH_PREFIX))
        # message.id -> 該訊息最後一筆 chunk 的 message（後到的覆蓋先到的，鍵順序保持首次出現）；缺 id 的另存
        last = {}
        loose = []
        # 子 session 的首句（user 第一筆文字）
        head = ""
        # 此檔第一筆有時間戳的 assistant 記錄的時間（不論是否在期間內）：用來判斷 session 是不是在期間內開始
        first_ts = None

        # STEP 02.01: 逐行讀入
        for rec in iter_records(path, stats):
            rtype = rec.get("type")
            if rtype == "user":
                if is_sub and not head:
                    head = first_user_text(rec)[:HEAD_CHARS].replace("\n", " ")
                continue
            if rtype != "assistant":
                continue
            # 該行的 message；缺少或 synthetic 的略過
            msg = rec.get("message")
            if not isinstance(msg, dict) or msg.get("model") == "<synthetic>":
                continue
            # 缺時間戳的記錄無法判斷是否在期間內，略過並計入自檢（實測目前為 0）
            ts = parse_ts(rec.get("timestamp", ""))
            if ts is None:
                stats["no_ts"] += 1
                continue
            if first_ts is None:
                first_ts = ts
            if ts < cutoff:
                continue
            stats["assistant_records"] += 1
            scan_blocks(msg, kind, sid, acc)
            # usage 不是物件或欄位全缺：不計價（不以 0 代替未知用量），計入自檢
            usage = msg.get("usage")
            if not isinstance(usage, dict) or not any(k in usage for k in USAGE_KEYS):
                stats["no_usage"] += 1
                continue
            if msg.get("id"):
                last[msg["id"]] = msg
            else:
                stats["no_id"] += 1
                loose.append(msg)

        # STEP 02.02: token 計價（每則訊息一次）
        # 此檔各回合的 context 量，依序；此檔是否出現過 Haiku 系列模型
        file_ctx = []
        has_haiku = False
        for msg in [*last.values(), *loose]:
            stats["messages"] += 1
            usage = msg["usage"]
            # 此回合各 token 欄位
            tok = collections.Counter(
                n=1,
                inp=usage.get("input_tokens", 0),
                out=usage.get("output_tokens", 0),
                cr=usage.get("cache_read_input_tokens", 0),
                cc=usage.get("cache_creation_input_tokens", 0),
            )
            model = msg.get("model", "?")
            has_haiku = has_haiku or HAIKU_KEYWORD in model
            by_model[(model, src)].update(tok)
            by_proj[proj].update(tok)
            if is_work:
                # 此回合送進模型的 context 總量
                ctx = tok["inp"] + tok["cr"] + tok["cc"]
                file_ctx.append(ctx)
                ctx_stat[ctx_bucket(ctx)].update(n=1, cr=tok["cr"])

        # STEP 02.03: 檔案層彙整
        # 只納入「在期間內開始」的 session：跨過期間起點的 session，file_ctx[0] 是期間內的第一輪而不是真正首輪，回合數也被截斷
        if len(file_ctx) >= MIN_TURNS and first_ts is not None and first_ts >= cutoff:
            sessions.append(file_ctx)
        if is_sub and has_haiku and head:
            haiku_sub_heads[head] += 1

    return {
        "stats": stats, "by_model": by_model, "by_proj": by_proj, "ctx_stat": ctx_stat, "sessions": sessions,
        "agent_calls": acc["agent_calls"], "advisor_by_sid": acc["advisor_by_sid"],
        "haiku_tasks": acc["haiku_tasks"], "haiku_sub_heads": haiku_sub_heads,
    }


def pct(part, whole):
    """計算百分比字串。

    @param {number} part 分子
    @param {number} whole 分母
    @returns {str} 例如 "37%"；分母為 0 回 "-"
    """
    # STEP 01: 避免除以零
    return f"{part / whole:.0%}" if whole else "-"


def mb(value):
    """把 token 數換成「M」單位字串。

    @param {number} value token 數
    @returns {str} 例如 "12.5M"
    """
    # STEP 01: 百萬為單位、小數一位
    return f"{value / 1e6:.1f}M"


def p90(sorted_values):
    """取已排序數列的 p90（nearest-rank：第 ceil(0.9n) 個）。

    @param {list} sorted_values 由小到大排序、非空的數列
    @returns {number} p90 值；n 很小時退化成最大值是 nearest-rank 的正常結果
    """
    # STEP 01: nearest-rank 的索引
    return sorted_values[min(len(sorted_values) - 1, math.ceil(len(sorted_values) * P90) - 1)]


def render(days, d):
    """把彙整結果輸出成 markdown。

    @param {int} days 回顧天數
    @param {dict} d collect() 的回傳值
    @returns {str} markdown 報告
    """
    # STEP 01: 標題與模型表
    out = [f"## 模型使用效率（近 {days} 天）", ""]
    # 全部模型的 cache 讀取／寫入總量，當占比的分母
    total_cr = sum(c["cr"] for c in d["by_model"].values())
    total_cc = sum(c["cc"] for c in d["by_model"].values())
    out += ["### 模型 × 主/子 session", "",
            "| 模型 | 來源 | 回合 | output | cache 寫入 | cache 讀取 | 讀取占比 |", "|---|---|---|---|---|---|---|"]
    for (model, kind), c in sorted(d["by_model"].items(), key=lambda x: -x[1]["cr"]):
        out.append(f"| {model} | {kind} | {c['n']} | {c['out'] / 1e3:.0f}k | {mb(c['cc'])} | {mb(c['cr'])} | {pct(c['cr'], total_cr)} |")
    # claude-mem observer 背景 session 的 cache 寫入量
    obs_cc = sum(c["cc"] for (_, k), c in d["by_model"].items() if k == "obs")
    out += ["", f"（obs = claude-mem observer 背景 session；其 cache 寫入占全部 {pct(obs_cc, total_cc)}）", ""]

    # STEP 02: 專案表
    out += ["### 專案占比（依 cache 讀取）", "", "| 專案 | 回合 | cache 讀取 | 占比 |", "|---|---|---|---|"]
    for proj, c in sorted(d["by_proj"].items(), key=lambda x: -x[1]["cr"])[:TOP_PROJECTS]:
        out.append(f"| {proj.replace(PROJECT_DIR_PREFIX, '')[:PROJ_NAME_WIDTH]} | {c['n']} | {mb(c['cr'])} | {pct(c['cr'], total_cr)} |")
    out.append("")

    # STEP 03: context 分桶
    out += ["### 主 session context 長度（不含 observer 與暫存 session）", "",
            "| 桶 | 回合 | cache 讀取 | 占比 |", "|---|---|---|---|"]
    # 主 session 工作回合的 cache 讀取總量，當分桶占比的分母
    ctx_total = sum(c["cr"] for c in d["ctx_stat"].values())
    for _, name in CTX_BUCKETS:
        c = d["ctx_stat"][name]
        out.append(f"| {name} | {c['n']} | {mb(c['cr'])} | {pct(c['cr'], ctx_total)} |")
    if d["sessions"]:
        # 各 session 的首輪 context 量、回合數（由小到大排序，供中位數與 p90 用）
        fc = sorted(s[0] for s in d["sessions"])
        tp = sorted(len(s) for s in d["sessions"])
        out += ["", f"- 納入 {len(fc)} 個期間內開始、≥{MIN_TURNS} 回合的 session：首輪 context 中位數 {statistics.median(fc) / 1e3:.0f}k（p90 {p90(fc) / 1e3:.0f}k）；"
                f"回合數中位數 {statistics.median(tp):.0f}、p90 {p90(tp)}、最長 {tp[-1]}"]
    out.append("")

    # STEP 04: Agent 呼叫與 advisor
    # Agent 呼叫計數：(subagent_type, model, 呼叫端) -> 次數；總次數；未明確指定 model 的次數
    calls = d["agent_calls"]
    total_calls = sum(calls.values())
    unspecified = sum(n for (_, m, _), n in calls.items() if m == UNSPECIFIED_LABEL)
    out += [f"### Agent 呼叫（共 {total_calls} 次，未明確指定 model {unspecified} 次 = {pct(unspecified, total_calls)}；實際可能是繼承主對話模型，或 agent 定義自帶預設）", "",
            "| subagent_type | model | 呼叫端 | 次數 |", "|---|---|---|---|"]
    for (t, m, k), n in calls.most_common():
        out.append(f"| {t} | {m} | {k} | {n} |")
    out += ["", f"### advisor 呼叫：{sum(d['advisor_by_sid'].values())} 次，分布於 {len(d['advisor_by_sid'])} 個 session", ""]

    # STEP 05: Haiku 任務清單（只列清單，是否機械性由使用者判斷）
    out += ["### Haiku 任務清單（只列事實，是否為機械性工作由使用者判斷）", ""]
    if d["haiku_tasks"]:
        out += ["| 次數 | subagent_type | description | prompt 開頭 |", "|---|---|---|---|"]
        for (t, desc, head), n in d["haiku_tasks"].most_common():
            out.append(f"| {n} | {t} | {desc[:DESC_WIDTH]} | {head} |")
    else:
        out.append("無明確帶 `model: haiku` 的 Agent 呼叫。")
    if d["haiku_sub_heads"]:
        out += ["", "Haiku 子 session 首句（含 agent 定義預設 haiku 者）：", ""]
        out += [f"- ×{n} {h}" for h, n in d["haiku_sub_heads"].most_common()]
    out.append("")

    # STEP 06: 自檢
    # 自檢計數器（collect 累計）
    s = d["stats"]
    out += ["### 自檢", "",
            f"- 掃描 {s['files']} 檔、{s['assistant_records']} 筆 assistant 記錄、去重後 {s['messages']} 則訊息、掃過 {s['blocks_scanned']} 個 content block、壞行（解析失敗或非物件）{s['bad_lines']}",
            f"- 缺 message.id 的記錄 {s['no_id']} 筆（逐筆計價，非 0 時 token 可能偏高）、缺時間戳 {s['no_ts']} 筆與缺用量欄位 {s['no_usage']} 筆（皆已略過，非 0 時統計可能偏低）",
            "- 去重後訊息數應小於等於 assistant 記錄數；壞行非 0 時統計可能不完整"]
    return "\n".join(out)


def main():
    """解析參數、彙整並輸出報告。

    @returns {int} exit code；沒有任何訊息回 1
    """
    # STEP 01: 參數
    ap = argparse.ArgumentParser(description="近 N 天模型使用效率報告")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = ap.parse_args()
    # STEP 02: 彙整；統計不到訊息視為失敗，避免把「0」誤讀成「沒用量」
    data = collect(args.days)
    if data["stats"]["messages"] == 0:
        print("找不到任何 assistant 訊息：檢查 " + PROJECTS_ROOT, file=sys.stderr)
        return 1
    print(render(args.days, data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
