#!/bin/bash
#
# notify.sh <event> <title> <body>
#
# 批次遷移 runner 的單一通知出口。負責：
#   1. 事件分級（HIGH 一定送、INFO 受開關與月額度限制）
#   2. LINE Messaging API 推播（主要管道）
#   3. 失敗時寫 deadletter、退回本機通知，連續失敗達門檻後整個生命週期降級
#   4. 月推播計數（與其他發版通知共用同一個官方帳號，額度要省著用）
#
# 狀態檔（都在 MIGRATION_STATE_DIR 下，不另外新增檔案）：
#   notify-usage.json        { month, sent, consecutive_failures, degraded, digest[] }
#   notify-deadletter.jsonl  送失敗的通知，下次成功時合併成單則摘要補送
#
# 慣例：只有環境變數用大寫，腳本內部變數一律小寫（方便用 grep 稽核讀了哪些環境變數）。
# 退出碼一律 0（通知失敗不該讓 runner 主流程中斷），參數不足才回 64。

set -uo pipefail

# ---------------------------------------------------------------- 常數

# LINE Messaging API 推播端點
readonly line_push_url="https://api.line.me/v2/bot/message/push"
# 月推播用量查詢端點；查得到就以它的 totalUsage 當主計數，查不到退回本地計數
# 註：實作當下手邊沒有可用憑證，此端點未經實測驗證，失敗時自動走本地計數
readonly line_quota_url="https://api.line.me/v2/bot/message/quota/consumption"

# 連續送失敗幾次之後，這個 runner 生命週期內不再嘗試 LINE，直接用本機通知
readonly degrade_after_failures=5
# 單則訊息長度上限（超過截斷）
readonly max_text_chars=300
# curl 逾時秒數
readonly curl_timeout_seconds=10

# HIGH 類事件：不受 INFO 開關與月額度限制，一定送
readonly high_events="module_failed module_blocked checkpoint_opened paused_for_review paused quota_wait_long queue_complete queue_stalled runner_crashed"

# ---------------------------------------------------------------- 參數

if [ "$#" -lt 3 ]; then
  echo "用法: notify.sh <event> <title> <body>" >&2
  exit 64
fi

# 事件代號（決定分級與 emoji）
event="$1"
# 主旨（訊息第一行）
title="$2"
# 內文（key: value 逐行）
body="$3"

# ---------------------------------------------------------------- 環境

# 通知管道：line = 走 LINE 推播；其他值 = 只用本機通知
notify_channel="${NOTIFY_CHANNEL:-line}"
# 月推播則數上限，超過後 INFO 類事件不送、只進摘要佇列
monthly_cap="${LINE_MONTHLY_CAP:-180}"
# 模組完成事件是否即時推播（0 = 只進每日摘要）
notify_on_done="${NOTIFY_ON_DONE:-0}"
# 額度等待事件是否即時推播（0 = 只留紀錄）
notify_on_quota_wait="${NOTIFY_ON_QUOTA_WAIT:-0}"
# LINE 憑證與推播對象（缺任一就退回本機通知）
line_token="${LINE_CHANNEL_ACCESS_TOKEN:-}"
line_target="${LINE_NOTIFY_TARGET_ID:-}"

# 狀態目錄：runner 會 export；單獨執行時用與 runner 相同的預設規則推導
state_dir="${MIGRATION_STATE_DIR:-}"
if [ -z "$state_dir" ]; then
  repo_dir_value="${REPO_DIR:-}"
  if [ -n "$repo_dir_value" ]; then
    state_dir="$HOME/r18-migration-state/$(basename "$repo_dir_value")"
  else
    state_dir="$HOME/r18-migration-state/default"
  fi
fi
mkdir -p "$state_dir"

# 狀態檔路徑
usage_file="$state_dir/notify-usage.json"
deadletter_file="$state_dir/notify-deadletter.jsonl"

# 當月代號，用於月計數歸零判斷
current_month="$(date +%Y-%m)"
# 最後一次 LINE 回應碼（line_push 失敗時填入）
last_http_code=""

# ---------------------------------------------------------------- 工具函式

# 取得事件分級：印出 HIGH 或 INFO
event_class() {
  local target="$1"
  local known
  for known in $high_events; do
    if [ "$target" = "$known" ]; then
      echo "HIGH"
      return 0
    fi
  done
  echo "INFO"
}

# 取得事件對應 emoji（訊息第一行開頭）
event_emoji() {
  local target="$1"
  case "$target" in
    module_done|queue_complete) echo "✅" ;;
    module_failed|runner_crashed) echo "❌" ;;
    module_blocked|queue_stalled) echo "⛔" ;;
    paused|paused_for_review) echo "⏸" ;;
    checkpoint_opened) echo "🔖" ;;
    quota_wait_started|quota_wait_long) echo "⏳" ;;
    daily_digest) echo "📋" ;;
    *) echo "ℹ️" ;;
  esac
}

# 讀 notify-usage.json 的單一欄位；檔案不存在或欄位缺漏時印出預設值
usage_field() {
  local field="$1"
  local fallback="$2"
  if [ ! -f "$usage_file" ]; then
    echo "$fallback"
    return 0
  fi
  local value
  value="$(jq -r --arg f "$field" --arg d "$fallback" '.[$f] // $d' "$usage_file" 2>/dev/null)"
  if [ -z "$value" ] || [ "$value" = "null" ]; then
    echo "$fallback"
  else
    echo "$value"
  fi
}

# 以 jq 覆寫 notify-usage.json；第一個參數是 jq 運算式，其餘原樣傳給 jq
usage_update() {
  local expression="$1"
  shift
  local current="{}"
  if [ -f "$usage_file" ]; then
    current="$(cat "$usage_file")"
    if [ -z "$current" ]; then
      current="{}"
    fi
  fi
  local updated
  updated="$(printf '%s' "$current" | jq -c "$@" "$expression" 2>/dev/null)"
  if [ -n "$updated" ]; then
    printf '%s\n' "$updated" > "$usage_file"
  fi
}

# 月份切換時把計數歸零；同時確保必要欄位存在
roll_month_if_needed() {
  local stored
  stored="$(usage_field month "")"
  if [ "$stored" != "$current_month" ]; then
    usage_update '{month: $m, sent: 0, consecutive_failures: 0, degraded: false, digest: []}' --arg m "$current_month"
  fi
}

# 把一則通知記進摘要佇列（被抑制時用）
digest_append() {
  usage_update '.digest = ((.digest // []) + [{ts: $ts, event: $ev, title: $tt}])' \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg ev "$event" --arg tt "$title"
}

# 本機通知備援（不保證有 GUI 環境，失敗也不影響退出碼）
osascript_notify() {
  local notify_title="$1"
  local notify_body="$2"
  # 雙引號會破壞 osascript 字面字串，先換成單引號
  local safe_title="${notify_title//\"/\'}"
  local safe_body="${notify_body//\"/\'}"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$safe_body\" with title \"$safe_title\"" >/dev/null 2>&1 || true
  fi
}

# 把一則通知寫進 deadletter，供下次成功時合併補送
deadletter_append() {
  local reason="$1"
  local text="$2"
  jq -cn --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg ev "$event" --arg reason "$reason" --arg text "$text" \
    '{ts: $ts, event: $ev, reason: $reason, text: $text}' >> "$deadletter_file" 2>/dev/null || true
}

# 產生帶 Authorization 標頭的 curl 設定檔（權限 600），避免憑證出現在 process list
make_curl_config() {
  local config_path="$1"
  : > "$config_path"
  chmod 600 "$config_path"
  printf 'header = "Authorization: Bearer %s"\n' "$line_token" >> "$config_path"
  printf 'silent\n' >> "$config_path"
  printf 'max-time = %s\n' "$curl_timeout_seconds" >> "$config_path"
}

# 送一則文字到 LINE；成功回 0、失敗回 1。不論成敗都不印出憑證
line_push() {
  local text="$1"
  local config_path
  config_path="$(mktemp -t r18notify)"
  make_curl_config "$config_path"

  local payload
  payload="$(jq -n --arg to "$line_target" --arg text "$text" \
    '{to: $to, messages: [{type: "text", text: $text}]}')"

  local http_code
  http_code="$(curl --config "$config_path" -o /dev/null -w '%{http_code}' \
    -X POST "$line_push_url" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>/dev/null)"
  rm -f "$config_path"

  case "$http_code" in
    2*)
      return 0
      ;;
    *)
      last_http_code="$http_code"
      return 1
      ;;
  esac
}

# 查 LINE 官方的當月已用量；查得到印出數字，查不到印出空字串
line_quota_consumption() {
  local config_path
  config_path="$(mktemp -t r18quota)"
  make_curl_config "$config_path"
  local response
  response="$(curl --config "$config_path" "$line_quota_url" 2>/dev/null)"
  rm -f "$config_path"
  if [ -z "$response" ]; then
    echo ""
    return 0
  fi
  printf '%s' "$response" | jq -r '.totalUsage // empty' 2>/dev/null
}

# deadletter 補送：把累積的失敗通知合併成單則摘要送出，成功才清空檔案
deadletter_flush() {
  if [ ! -s "$deadletter_file" ]; then
    return 0
  fi
  local count
  count="$(wc -l < "$deadletter_file" | tr -d ' ')"
  local lines
  lines="$(jq -r '"- " + .ts + " " + .event' "$deadletter_file" 2>/dev/null | tail -n 10)"
  local text
  text="$(printf '📨 補送先前未送達的通知 %s 則\n%s' "$count" "$lines")"
  if line_push "$text"; then
    : > "$deadletter_file"
    usage_update '.sent = ((.sent // 0) + 1)'
  fi
}

# ---------------------------------------------------------------- 主流程

# STEP 01: 組出最終訊息文字（首行 emoji + 主旨，其後內文），並截斷到長度上限
class="$(event_class "$event")"
emoji="$(event_emoji "$event")"
text="$(printf '%s %s\n%s' "$emoji" "$title" "$body")"
if [ "${#text}" -gt "$max_text_chars" ]; then
  text="${text:0:$max_text_chars}"
fi

# STEP 02: 月份切換歸零，並把當月計數與降級狀態讀出來
roll_month_if_needed
sent_count="$(usage_field sent 0)"
degraded="$(usage_field degraded false)"
failures="$(usage_field consecutive_failures 0)"

# STEP 03: INFO 類事件的抑制規則——被抑制的事件不送，改進摘要佇列
suppress_reason=""
if [ "$class" = "INFO" ]; then
  # STEP 03.01: heartbeat 永遠只留紀錄，不推播
  if [ "$event" = "heartbeat" ]; then
    suppress_reason="heartbeat 只留紀錄"
  fi
  # STEP 03.02: 模組完成預設只進每日摘要
  if [ -z "$suppress_reason" ] && [ "$event" = "module_done" ] && [ "$notify_on_done" != "1" ]; then
    suppress_reason="module_done 依設定只進每日摘要"
  fi
  # STEP 03.03: 額度等待事件預設只留紀錄
  if [ -z "$suppress_reason" ] && [ "$event" = "quota_wait_started" ] && [ "$notify_on_quota_wait" != "1" ]; then
    suppress_reason="quota_wait_started 依設定只留紀錄"
  fi
  # STEP 03.04: 月額度用完後，INFO 一律不送
  if [ -z "$suppress_reason" ] && [ "$sent_count" -ge "$monthly_cap" ]; then
    suppress_reason="本月推播已達上限 $monthly_cap"
  fi
fi

if [ -n "$suppress_reason" ]; then
  digest_append
  echo "suppressed: $suppress_reason"
  exit 0
fi

# STEP 04: 送出每日摘要後要清空摘要佇列（摘要內容由 runner 組進 body）
clear_digest_after_send=0
if [ "$event" = "daily_digest" ]; then
  clear_digest_after_send=1
fi

# STEP 05: 決定實際管道。非 line 管道、已降級、或缺憑證/對象 → 走本機通知
use_line=1
fallback_reason=""
if [ "$notify_channel" != "line" ]; then
  use_line=0
  fallback_reason="管道設定為 $notify_channel"
elif [ "$degraded" = "true" ]; then
  use_line=0
  fallback_reason="已連續失敗 $failures 次，本生命週期降級為本機通知"
elif [ -z "$line_token" ] || [ -z "$line_target" ]; then
  use_line=0
  fallback_reason="缺少 LINE 憑證或推播對象設定"
fi

if [ "$use_line" -eq 0 ]; then
  osascript_notify "$title" "$body"
  # 只有「本來該走 LINE 卻走不成」才進 deadletter；管道本來就設本機通知不算失敗
  if [ "$notify_channel" = "line" ]; then
    deadletter_append "$fallback_reason" "$text"
  fi
  echo "fallback: $fallback_reason"
  exit 0
fi

# STEP 06: 以官方用量覆寫本地計數（查得到才用），再做一次 INFO 的額度檢查
official_usage="$(line_quota_consumption)"
if [ -n "$official_usage" ]; then
  usage_update '.sent = ($u | tonumber)' --arg u "$official_usage"
  sent_count="$official_usage"
  if [ "$class" = "INFO" ] && [ "$sent_count" -ge "$monthly_cap" ]; then
    digest_append
    echo "suppressed: 官方用量 $sent_count 已達上限 $monthly_cap"
    exit 0
  fi
fi

# STEP 07: 送出。成功則計數 +1、清空連續失敗數，並補送 deadletter
if line_push "$text"; then
  usage_update '.sent = ((.sent // 0) + 1) | .consecutive_failures = 0'
  if [ "$clear_digest_after_send" -eq 1 ]; then
    usage_update '.digest = []'
  fi
  deadletter_flush
  echo "sent: $event"
  exit 0
fi

# STEP 08: 失敗 → deadletter + 本機通知；連續失敗達門檻就降級
failures=$((failures + 1))
usage_update '.consecutive_failures = ($n | tonumber)' --arg n "$failures"
if [ "$failures" -ge "$degrade_after_failures" ]; then
  usage_update '.degraded = true'
fi
deadletter_append "LINE 回應 ${last_http_code:-無回應}" "$text"
osascript_notify "$title" "$body"
echo "failed: LINE 回應 ${last_http_code:-無回應}，已寫入 deadletter"
exit 0
