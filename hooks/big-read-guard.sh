#!/usr/bin/env bash
# big-read-guard.sh — PreToolUse hook：攔截大檔的整檔 Read
#
# 行為：當 Read 目標檔行數 >= 門檻、且未指定 offset/limit（整檔讀）時，
#       deny 這次呼叫並提示先用 smart_outline。每個檔案每 session 只攔一次
#       （重新送出同一個 Read 即放行，等於一個減速丘）。
# 失敗時 fail-open（exit 0），絕不阻斷正常的 Read。

# STEP 01: 設定行數門檻（覺得太吵就調高這個數字）
THRESHOLD=800

# STEP 02: 讀取 PreToolUse 輸入 JSON（由 hook-error-wrapper.sh 透傳 stdin）
INPUT=$(cat)

# STEP 03: 非 Read 工具 → 放行
[ "$(jq -r '.tool_name // ""' <<<"$INPUT")" = "Read" ] || exit 0

# STEP 04: 取參數；已指定 offset/limit 代表是範圍讀取 → 放行
FILE=$(jq -r '.tool_input.file_path // ""' <<<"$INPUT")
OFFSET=$(jq -r '.tool_input.offset // ""' <<<"$INPUT")
LIMIT=$(jq -r '.tool_input.limit // ""' <<<"$INPUT")
[ -n "$OFFSET" ] && exit 0
[ -n "$LIMIT" ] && exit 0
[ -f "$FILE" ] || exit 0

# STEP 05: 行數未達門檻 → 放行
LINES=$(wc -l < "$FILE" 2>/dev/null | tr -d ' ')
[ "${LINES:-0}" -lt "$THRESHOLD" ] && exit 0

# STEP 06: 本 session 對同一檔已攔過 → 放行（讓重新送出的 Read 通過）
SESSION=$(jq -r '.session_id // "nosession"' <<<"$INPUT")
SEEN="/tmp/claude-bigread-${SESSION}"
grep -qxF "$FILE" "$SEEN" 2>/dev/null && exit 0
echo "$FILE" >> "$SEEN"

# STEP 07: deny 這次呼叫，把原因回饋給 Claude
REASON="$(basename "$FILE") 有 ${LINES} 行（>= ${THRESHOLD}）。若只需其中一段，請先用 smart_outline 取得結構與行號、再用 offset/limit 精準 Read，避免整檔進 context。若確實要看全檔（這是要修的 bug 檔、或要編輯它），直接重新送出同一個 Read 即放行——本 hook 對每個檔案只攔一次。"
jq -cn --arg r "$REASON" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'
exit 0
