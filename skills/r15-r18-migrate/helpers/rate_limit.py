"""從 CLI 的 stream-json 事件取額度使用率（rate_limit_event）。

背景：runner 原本靠 quota-usage.py 打 `/api/oauth/usage` 查用量，但該端點需要 `user:profile` scope，
`claude setup-token` 的長效 token 只有 `user:inference`，一律 429。每次 CLI 呼叫的 stream 都帶
`rate_limit_event`，內有 `rate_limit_info.unifiedWindows.five_hour／seven_day` 的 `utilization` 與 `resetsAt`
（2026-09-30 在真環境的 14 筆事件驗證過），不需要那個端點。

這個模組只做純資料轉換，不讀檔、不寫 queue、不記事件，方便單獨測試。
"""

import datetime

# 事件裡 utilization 是 0～1 的比例；runner 的門檻（80／95）是百分比整數，所以乘上這個數再四捨五入。
# 單位的依據有兩個：(1) 真實樣本的量級與增量（五小時值每個小模組約升 0.01、一次燒發後 0.28）；(2) Claude Code 2.1.285
# 本體處理同一組視窗的程式：`utilization < 1` 視為未耗盡、`surpassedThreshold < 1`、嚴重度 `> 0.95` critical／`> 0.75` warning，
# 顯示百分比時才 `Math.round(x * 100)`。user 於 2026-09-30 用 `/usage` 畫面對照過，回報「大致正確」（沒有逐點比對）；
# **仍沒看到 rate_limit_event 的 unifiedWindows 與那段程式的直接對應**，所以說「有佐證、人工對照大致正確」，不說完全驗證。若實際上事件給的就是百分比，這個換算會讓門檻過度敏感（誤擋，看得到）；
# 反過來不換算則永遠不擋（看不到），所以選前者。
UTILIZATION_TO_PERCENT = 100

# 需要的兩個視窗，鍵名同時是事件裡與輸出裡的名稱
WINDOW_NAMES = ("five_hour", "seven_day")


def _is_number(value):
    """是不是可用的數字：布林是 int 的子類別，要排除；NaN 與無限大不算。

    @param value 任意值
    @return bool
    """
    # STEP 01: 布林先排除；再要求有限的 int／float
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def _window(raw):
    """把事件裡的單一視窗轉成 runner 用的格式；任何欄位不合格就回 None（整個事件視為無效）。

    @param raw `unifiedWindows.<視窗名>` 的值
    @return {"utilization": 百分比整數, "resets_at": ISO 字串} 或 None
    """
    # STEP 01: 必須是 dict，utilization 非負數字，resetsAt 是正數
    if not isinstance(raw, dict):
        return None
    utilization = raw.get("utilization")
    resets_at = raw.get("resetsAt")
    if not _is_number(utilization) or utilization < 0 or not _is_number(resets_at) or resets_at <= 0:
        return None

    # STEP 02: epoch 秒轉成帶時區的 ISO，runner 的 parse_iso／wait_until 都認得
    try:
        iso = datetime.datetime.fromtimestamp(resets_at, datetime.timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None
    return {"utilization": int(round(utilization * UTILIZATION_TO_PERCENT)), "resets_at": iso}


def latest_rate_limit(events):
    """取事件清單裡最後一筆「兩個視窗都有效」的 rate_limit_event。

    最後一筆壞掉就退回它前面最近的有效那筆，而不是丟掉全部——stream 被殺時尾端常是半行或殘缺事件。

    @param events stream_events.read_stream 回傳的事件 dict 清單
    @return {"status": str 或 None, "five_hour": {...}, "seven_day": {...}}；沒有有效事件回 None
    """
    # STEP 01: 由後往前找第一筆有效的
    for event in reversed(events):
        if not isinstance(event, dict) or event.get("type") != "rate_limit_event":
            continue
        info = event.get("rate_limit_info")
        windows = info.get("unifiedWindows") if isinstance(info, dict) else None
        if not isinstance(windows, dict):
            continue

        # STEP 02: 兩個視窗都要有效，缺一個就整筆不用（半套資料會讓取件前檢查漏看另一個視窗）
        parsed = {name: _window(windows.get(name)) for name in WINDOW_NAMES}
        if any(value is None for value in parsed.values()):
            continue
        status = info.get("status")
        return dict(parsed, status=status if isinstance(status, str) else None)
    return None
