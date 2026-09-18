#!/usr/bin/env python3
"""stream_events.py — CLI stream-json 落檔的解析（runner.py 與 diagnostics.py 共用）。

負責：
  1. 逐行讀 sessions/<entry>-<n>.stream.jsonl，容錯半行與非 JSON 行（被殺時最後一行常是半行）
  2. 取 result 事件（structured_output、session_id、cost、permission_denials、terminal_reason）
  3. 把事件序列展開成時間軸（tool_use → tool_result 配對、耗時、錯誤、subagent 歸屬）

設計約束：
  * 只用 python3 標準函式庫；不 import runner.py 或 diagnostics.py（依賴方向是它們 import 本檔）。
  * 只讀不寫。
"""

import datetime
import json
import os

# ================================================================ 常數

# 時間軸每列的輸入／文字摘要長度上限（字元）
TIMELINE_INPUT_CHARS = 200
TIMELINE_TEXT_CHARS = 300
# 每個事件單行摘要的長度上限
EVENT_BRIEF_CHARS = 120


# ================================================================ 小工具


def parse_ts(value):
    """把事件的 timestamp（ISO 字串，可帶 Z）轉成 aware datetime；轉不了回 None。"""
    # STEP 01: 只接受字串；Z 後綴換成 fromisoformat 認得的 +00:00
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # STEP 02: 解析；沒帶時區的補成 UTC
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def clip(text, limit):
    """把文字壓成單行並截到長度上限，截斷時加省略號。"""
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


# ================================================================ stream 解析


def read_stream(path):
    """讀取 stream-json 落檔。

    回傳 (events, bad_lines, error)：events 是依序的事件 dict 清單；bad_lines 是解析不了
    而被跳過的行數（被殺時最後一行常是半行）；error 是整個檔案讀不到時的說明，否則 None。
    """
    # STEP 01: 檔案層失敗直接回報，不丟例外
    if not path or not os.path.exists(path):
        return [], 0, "stream 檔不存在: %s" % path
    events = []
    bad_lines = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            # STEP 02: 逐行解析，壞行計數後跳過
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except ValueError:
                    bad_lines += 1
                    continue
                if isinstance(parsed, dict):
                    events.append(parsed)
                else:
                    bad_lines += 1
    except OSError as exc:
        return [], 0, "stream 檔讀取失敗: %s" % exc
    return events, bad_lines, None


def last_result_event(events):
    """回傳最後一筆 type == result 的事件；沒有（被殺／未完成）回 None。"""
    for event in reversed(events):
        if event.get("type") == "result":
            return event
    return None


def init_event(events):
    """回傳 system/init 事件（含 model、tools、cwd 等）；沒有回 None。"""
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "init":
            return event
    return None


def content_blocks(event):
    """取出 assistant／user 事件裡的內容區塊清單；不是這兩類或形狀不對回空清單。"""
    # STEP 01: 只處理 assistant／user 兩類事件
    if event.get("type") not in ("assistant", "user"):
        return []
    message = event.get("message") or {}
    content = message.get("content")
    # STEP 02: 陣列原樣過濾成 dict 區塊；純字串包成單一 text 區塊
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def block_text(block):
    """把 tool_result 的 content（字串或區塊清單）壓成純文字。"""
    # STEP 01: 字串直接回
    content = block.get("content")
    if isinstance(content, str):
        return content
    # STEP 02: 區塊清單逐一展開，text 取原文、其餘轉 JSON
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts)
    return "" if content is None else str(content)


def assistant_texts(events):
    """收集所有 assistant 文字區塊，回傳 [(timestamp, text, parent_tool_use_id)]。"""
    # STEP 01: 逐事件取 text 區塊，保留時間與 subagent 歸屬
    texts = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in content_blocks(event):
            if block.get("type") == "text" and block.get("text"):
                texts.append((event.get("timestamp"), block["text"], event.get("parent_tool_use_id")))
    return texts


def transcript_text(events, limit_chars):
    """把 assistant 文字依序串起來，只保留末段（給文字特徵判讀用）。"""
    joined = "\n".join(text for _ts, text, _parent in assistant_texts(events))
    return joined[-limit_chars:]


def event_brief(event, base_ts):
    """把一個事件壓成單行摘要：+秒 類型/子類 摘要。"""
    # STEP 01: 相對秒數
    ts = parse_ts(event.get("timestamp"))
    rel = "+%ds" % int((ts - base_ts).total_seconds()) if (ts and base_ts) else "+?"
    kind = event.get("type", "?")
    subtype = event.get("subtype")
    label = "%s/%s" % (kind, subtype) if subtype else kind
    # STEP 02: 依事件類型取最有辨識度的內容
    summary = ""
    if kind in ("assistant", "user"):
        pieces = []
        for block in content_blocks(event):
            block_type = block.get("type")
            if block_type == "tool_use":
                pieces.append("tool_use %s %s" % (block.get("name"), clip(json.dumps(block.get("input", {}), ensure_ascii=False), 60)))
            elif block_type == "tool_result":
                pieces.append("tool_result%s %s" % (" (error)" if block.get("is_error") else "", clip(block_text(block), 60)))
            elif block_type == "text":
                pieces.append("text %s" % clip(block.get("text", ""), 60))
            else:
                pieces.append(str(block_type))
        summary = "; ".join(pieces)
    elif kind == "result":
        summary = "subtype=%s is_error=%s terminal_reason=%s" % (
            subtype,
            event.get("is_error"),
            event.get("terminal_reason"),
        )
    else:
        summary = clip(json.dumps({k: v for k, v in event.items() if k not in ("type", "subtype", "timestamp", "uuid", "session_id")}, ensure_ascii=False), 60)
    return clip("%s %s %s" % (rel, label, summary), EVENT_BRIEF_CHARS)


def build_timeline(events):
    """從事件序列抽出時間軸與錯誤。

    回傳 dict：
      rows      — 依時間排序的列，每列 {kind: tool|text, rel_s, tool, input, duration_s,
                  is_error, result, parent, seq}
      errors    — 所有 is_error 的 tool_result，[(seq, tool, 全文)]
      base_ts   — 第一個有 timestamp 的事件時間（相對秒數的原點）
      tool_count / text_count
    """
    # STEP 01: 找相對秒數的原點
    base_ts = None
    for event in events:
        base_ts = parse_ts(event.get("timestamp"))
        if base_ts:
            break
    rows = []
    errors = []
    pending = {}
    seq = 0
    # STEP 02: 逐事件展開區塊；tool_use 先登記，tool_result 回頭補耗時與結果
    for event in events:
        ts = parse_ts(event.get("timestamp"))
        rel_s = int((ts - base_ts).total_seconds()) if (ts and base_ts) else None
        parent = event.get("parent_tool_use_id")
        for block in content_blocks(event):
            block_type = block.get("type")
            if block_type == "tool_use":
                seq += 1
                row = {
                    "kind": "tool",
                    "seq": seq,
                    "rel_s": rel_s,
                    "ts": ts,
                    "tool": block.get("name") or "?",
                    "input": clip(json.dumps(block.get("input", {}), ensure_ascii=False), TIMELINE_INPUT_CHARS),
                    "duration_s": None,
                    "is_error": False,
                    "result": "",
                    "parent": parent,
                }
                rows.append(row)
                if block.get("id"):
                    pending[block["id"]] = row
            elif block_type == "tool_result":
                row = pending.pop(block.get("tool_use_id"), None)
                text = block_text(block)
                if row is not None:
                    if ts and row.get("ts"):
                        row["duration_s"] = int((ts - row["ts"]).total_seconds())
                    row["is_error"] = bool(block.get("is_error"))
                    row["result"] = clip(text, TIMELINE_INPUT_CHARS)
                    if row["is_error"]:
                        errors.append((row["seq"], row["tool"], text))
                elif block.get("is_error"):
                    errors.append((None, "?", text))
            elif block_type == "text" and event.get("type") == "assistant" and block.get("text"):
                seq += 1
                rows.append(
                    {
                        "kind": "text",
                        "seq": seq,
                        "rel_s": rel_s,
                        "ts": ts,
                        "tool": "",
                        "input": clip(block["text"], TIMELINE_TEXT_CHARS),
                        "duration_s": None,
                        "is_error": False,
                        "result": "",
                        "parent": parent,
                    }
                )
    # STEP 03: 沒收到結果的 tool_use（被殺時最後一個）標記出來
    for row in pending.values():
        row["result"] = "（未收到 tool_result）"
    return {
        "rows": rows,
        "errors": errors,
        "base_ts": base_ts,
        "tool_count": sum(1 for row in rows if row["kind"] == "tool"),
        "text_count": sum(1 for row in rows if row["kind"] == "text"),
    }
