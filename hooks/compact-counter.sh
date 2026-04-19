#!/usr/bin/env bash
# PreCompact hook：每次 context 壓縮前對 session compact count +1
# 寫入 ~/.claude/compact-counts/<sessionId>.count，供 statusline 讀取顯示

set -e

input=$(cat)

session_id=$(echo "$input" | jq -r '.session_id // .sessionId // empty' 2>/dev/null)
[ -z "$session_id" ] && exit 0

dir="$HOME/.claude/compact-counts"
mkdir -p "$dir"

count_file="$dir/${session_id}.count"
cur=0
[ -f "$count_file" ] && cur=$(cat "$count_file" 2>/dev/null || echo 0)
echo $(( cur + 1 )) > "$count_file"

exit 0
