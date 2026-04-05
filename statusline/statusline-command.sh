#!/usr/bin/env bash
# Claude Code statusLine command
# 合併自：
#   - sd0xdev/sd0x-dev-flow (--skill statusline-config) — 佈局、context window、session、git、thinking 狀態
#   - @kamranahmedse/claude-statusline — OAuth rate limits（5h / 7d / extra usage 進度條）
set -f

input=$(cat)

if [ -z "$input" ]; then
    printf "Claude"
    exit 0
fi

# ── Colors ──────────────────────────────────────────────
blue='\033[38;2;0;153;255m'
orange='\033[38;2;255;176;85m'
green='\033[38;2;0;175;80m'
cyan='\033[38;2;86;182;194m'
red='\033[38;2;255;85;85m'
yellow='\033[38;2;230;200;0m'
white='\033[38;2;220;220;220m'
magenta='\033[38;2;180;140;255m'
dim='\033[2m'
reset='\033[0m'

sep=" ${dim}│${reset} "

# ── Helpers ─────────────────────────────────────────────
format_tokens() {
    local num=$1
    if [ "$num" -ge 1000000 ]; then
        awk "BEGIN {printf \"%.1fm\", $num / 1000000}"
    elif [ "$num" -ge 1000 ]; then
        awk "BEGIN {printf \"%.0fk\", $num / 1000}"
    else
        printf "%d" "$num"
    fi
}

color_for_pct() {
    local pct=$1
    if [ "$pct" -ge 90 ]; then printf "$red"
    elif [ "$pct" -ge 70 ]; then printf "$yellow"
    elif [ "$pct" -ge 50 ]; then printf "$orange"
    else printf "$green"
    fi
}

build_bar() {
    local pct=$1
    local width=$2
    [ "$pct" -lt 0 ] 2>/dev/null && pct=0
    [ "$pct" -gt 100 ] 2>/dev/null && pct=100

    local filled=$(( pct * width / 100 ))
    local empty=$(( width - filled ))
    local bar_color
    bar_color=$(color_for_pct "$pct")

    local filled_str="" empty_str=""
    for ((i=0; i<filled; i++)); do
        [ -n "$filled_str" ] && filled_str+=" "
        filled_str+="●"
    done
    for ((i=0; i<empty; i++)); do
        [ -n "$empty_str" ] && empty_str+=" "
        empty_str+="○"
    done
    # Add space between filled and empty sections
    if [ -n "$filled_str" ] && [ -n "$empty_str" ]; then
        empty_str=" ${empty_str}"
    fi

    printf "${bar_color}${filled_str}${dim}${empty_str}${reset}"
}

iso_to_epoch() {
    local iso_str="$1"

    local epoch
    epoch=$(date -d "${iso_str}" +%s 2>/dev/null)
    if [ -n "$epoch" ]; then
        echo "$epoch"
        return 0
    fi

    local stripped="${iso_str%%.*}"
    stripped="${stripped%%Z}"
    stripped="${stripped%%+*}"
    stripped="${stripped%%-[0-9][0-9]:[0-9][0-9]}"

    if [[ "$iso_str" == *"Z"* ]] || [[ "$iso_str" == *"+00:00"* ]] || [[ "$iso_str" == *"-00:00"* ]]; then
        epoch=$(env TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%S" "$stripped" +%s 2>/dev/null)
    else
        epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$stripped" +%s 2>/dev/null)
    fi

    if [ -n "$epoch" ]; then
        echo "$epoch"
        return 0
    fi

    return 1
}

format_reset_time() {
    local iso_str="$1"
    local style="$2"
    [ -z "$iso_str" ] || [ "$iso_str" = "null" ] && return

    local epoch
    epoch=$(iso_to_epoch "$iso_str")
    [ -z "$epoch" ] && return

    case "$style" in
        time)
            date -j -r "$epoch" +"%l:%M%p" 2>/dev/null | sed 's/^ //; s/\.//g' | tr '[:upper:]' '[:lower:]' || \
            date -d "@$epoch" +"%l:%M%P" 2>/dev/null | sed 's/^ //; s/\.//g'
            ;;
        datetime)
            date -j -r "$epoch" +"%b %-d, %l:%M%p" 2>/dev/null | sed 's/  / /g; s/^ //; s/\.//g' | tr '[:upper:]' '[:lower:]' || \
            date -d "@$epoch" +"%b %-d, %l:%M%P" 2>/dev/null | sed 's/  / /g; s/^ //; s/\.//g'
            ;;
        *)
            date -j -r "$epoch" +"%b %-d" 2>/dev/null | tr '[:upper:]' '[:lower:]' || \
            date -d "@$epoch" +"%b %-d" 2>/dev/null
            ;;
    esac
}

# ── Extract JSON data ───────────────────────────────────
model_name=$(echo "$input" | jq -r '.model.display_name // "Claude"')

size=$(echo "$input" | jq -r '.context_window.context_window_size // 200000')
[ "$size" -eq 0 ] 2>/dev/null && size=200000

input_tokens=$(echo "$input" | jq -r '.context_window.current_usage.input_tokens // 0')
cache_create=$(echo "$input" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0')
cache_read=$(echo "$input" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0')
current=$(( input_tokens + cache_create + cache_read ))

if [ "$size" -gt 0 ]; then
    pct_used=$(( current * 100 / size ))
else
    pct_used=0
fi
pct_remaining=$(( 100 - pct_used ))

# transcript 路徑（用於取得工具/agent/todo 資料）
transcript_path=$(echo "$input" | jq -r '.transcript_path // empty')

# thinking 系統預設開啟，只有明確設為 false 才關閉
thinking_on=true
settings_path="$HOME/.claude/settings.json"
if [ -f "$settings_path" ]; then
    thinking_val=$(jq -r '.alwaysThinkingEnabled // "unset"' "$settings_path" 2>/dev/null)
    [ "$thinking_val" = "false" ] && thinking_on=false
fi

# ── LINE 1: Dir (branch*) ──
cwd=$(echo "$input" | jq -r '.cwd // .workspace.current_dir // ""')
[ -z "$cwd" ] || [ "$cwd" = "null" ] && cwd=$(pwd)
home_dir="$HOME"
short_dir="${cwd/#$home_dir/\~}"

git_branch=""
git_dirty=""
if git -C "$cwd" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git_branch=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" symbolic-ref --short HEAD 2>/dev/null)
    if [ -z "$git_branch" ]; then
        git_branch=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" describe --tags --exact-match HEAD 2>/dev/null)
    fi
    if [ -n "$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" status --porcelain 2>/dev/null)" ]; then
        git_dirty="*"
    fi
fi

session_duration=""
session_start=$(echo "$input" | jq -r '.session.start_time // empty')
if [ -n "$session_start" ] && [ "$session_start" != "null" ]; then
    start_epoch=$(iso_to_epoch "$session_start")
    if [ -n "$start_epoch" ]; then
        now_epoch=$(date +%s)
        elapsed=$(( now_epoch - start_epoch ))
        if [ "$elapsed" -ge 3600 ]; then
            session_duration="$(( elapsed / 3600 ))h$(( (elapsed % 3600) / 60 ))m"
        elif [ "$elapsed" -ge 60 ]; then
            session_duration="$(( elapsed / 60 ))m"
        else
            session_duration="${elapsed}s"
        fi
    fi
fi

# context color
if [ "$pct_used" -ge 80 ]; then
    ctx_color="$red"
elif [ "$pct_used" -ge 60 ]; then
    ctx_color="$yellow"
else
    ctx_color="$blue"
fi

line1="${yellow}${short_dir}${reset}"
if [ -n "$git_branch" ]; then
    line1+=" ${green}(${git_branch}${red}${git_dirty}${green})${reset}"
fi

# ── Transcript data (cached 3s) ────────────────────────
t_tools="" t_agents=0 t_todo="" t_session_name=""
t_cache="/tmp/claude/statusline-transcript.json"

if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    t_refresh=true
    if [ -f "$t_cache" ]; then
        t_age=$(( $(date +%s) - $(stat -f %m "$t_cache" 2>/dev/null || echo 0) ))
        [ "$t_age" -lt 3 ] && t_refresh=false
    fi

    if $t_refresh; then
        # STEP 01: session name（第一行）
        t_session_name=$(head -1 "$transcript_path" | jq -r '.slug // .customTitle // ""' 2>/dev/null)

        # STEP 02: 工具統計（streaming jq，逐行處理不載入全檔）
        t_tools=$(jq -r '.message?.content[]? | select(.type == "tool_use") | .name' "$transcript_path" 2>/dev/null \
            | sort | uniq -c | sort -rn | head -5 \
            | awk '{printf "%s×%s ", $2, $1}' | sed 's/ $//')

        # STEP 03: agent 數量
        t_agents=$(jq -r '.message?.content[]? | select(.type == "tool_use" and .name == "Agent") | "x"' "$transcript_path" 2>/dev/null \
            | wc -l | tr -d ' ')
        [ -z "$t_agents" ] && t_agents=0

        # STEP 04: todo 進度（從 TodoWrite + TaskCreate + TaskUpdate 取）
        t_todo="" t_todo_current=""
        t_todo_state=$(jq -s '
          [.[] | .message?.content[]? |
           select(.type == "tool_use" and
             (.name == "TodoWrite" or .name == "TaskCreate" or .name == "TaskUpdate")
           ) | {name, input}] |
          reduce .[] as $b ({todos:[]};
            if $b.name == "TodoWrite" then
              {todos: [($b.input.todos // [])[] |
                {c: (.content // ""), s: (.status // "pending")}]}
            elif $b.name == "TaskCreate" then
              .todos += [{
                c: ($b.input.description // $b.input.subject // ""),
                s: ($b.input.status // "pending")
              }]
            elif $b.name == "TaskUpdate" then
              ($b.input.id // $b.input.taskId // null) as $raw |
              (if $raw == null then -1
               elif ($raw | type) == "number" then ($raw - 1)
               else (($raw | tonumber? // -1) - 1) end) as $idx |
              if $idx >= 0 and $idx < (.todos | length) then
                .todos[$idx].s = ($b.input.status // .todos[$idx].s)
              else . end
            else . end
          ) |
          (.todos | length) as $total |
          ([.todos[] | select(.s == "completed" or .s == "complete" or .s == "done")] | length) as $done |
          ([.todos[] | select(.s == "in_progress" or .s == "running")] | first | .c // "") as $cur |
          {total: $total, done: $done,
           current: ($cur | if length > 50 then .[:50] + "…" else . end)}
        ' "$transcript_path" 2>/dev/null)

        if [ -n "$t_todo_state" ]; then
            t_t=$(echo "$t_todo_state" | jq -r '.total // 0')
            t_d=$(echo "$t_todo_state" | jq -r '.done // 0')
            t_todo_current=$(echo "$t_todo_state" | jq -r '.current // ""')
            [ "$t_t" -gt 0 ] 2>/dev/null && t_todo="${t_d}/${t_t}"
        fi

        # STEP 05: 寫入 cache
        jq -nc --arg name "$t_session_name" --arg tools "$t_tools" \
            --argjson agents "${t_agents:-0}" --arg todo "$t_todo" \
            --arg todo_current "$t_todo_current" \
            '{name:$name,tools:$tools,agents:$agents,todo:$todo,todo_current:$todo_current}' > "$t_cache" 2>/dev/null
    else
        # STEP 06: 讀取 cache
        t_data=$(cat "$t_cache" 2>/dev/null)
        t_session_name=$(echo "$t_data" | jq -r '.name // ""' 2>/dev/null)
        t_tools=$(echo "$t_data" | jq -r '.tools // ""' 2>/dev/null)
        t_agents=$(echo "$t_data" | jq -r '.agents // 0' 2>/dev/null)
        t_todo=$(echo "$t_data" | jq -r '.todo // ""' 2>/dev/null)
        t_todo_current=$(echo "$t_data" | jq -r '.todo_current // ""' 2>/dev/null)
    fi
fi

# ── Config counts (cached 120s) ────────────────────────
cfg_md=0 cfg_rules=0 cfg_hooks=0
cfg_cache="/tmp/claude/statusline-config.json"

cfg_refresh=true
if [ -f "$cfg_cache" ]; then
    cfg_age=$(( $(date +%s) - $(stat -f %m "$cfg_cache" 2>/dev/null || echo 0) ))
    [ "$cfg_age" -lt 120 ] && cfg_refresh=false
fi

if $cfg_refresh; then
    # STEP 01: 計算 CLAUDE.md 數量
    cfg_md=0
    [ -f "$HOME/.claude/CLAUDE.md" ] && cfg_md=$((cfg_md + 1))
    [ -n "$cwd" ] && [ -f "$cwd/CLAUDE.md" ] && cfg_md=$((cfg_md + 1))

    # STEP 02: 計算 rules 數量
    cfg_rules=$(find "$HOME/.claude/rules" -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')

    # STEP 03: 計算 hooks 數量
    cfg_hooks=$(jq '.hooks | keys | length' "$HOME/.claude/settings.json" 2>/dev/null || echo 0)

    # STEP 04: 寫入 cache
    jq -nc --argjson md "$cfg_md" --argjson rules "${cfg_rules:-0}" --argjson hooks "${cfg_hooks:-0}" \
        '{md:$md,rules:$rules,hooks:$hooks}' > "$cfg_cache" 2>/dev/null
else
    cfg_data=$(cat "$cfg_cache" 2>/dev/null)
    cfg_md=$(echo "$cfg_data" | jq -r '.md // 0' 2>/dev/null)
    cfg_rules=$(echo "$cfg_data" | jq -r '.rules // 0' 2>/dev/null)
    cfg_hooks=$(echo "$cfg_data" | jq -r '.hooks // 0' 2>/dev/null)
fi

# ── LINE 2: Account │ Session name │ Model │ Context │ Session │ Thinking ──
line2=""

# 帳號名稱（依據 CLAUDE_CONFIG_DIR 判斷）
account_name="max"
if [ -n "$CLAUDE_CONFIG_DIR" ] && [ "$CLAUDE_CONFIG_DIR" != "$HOME/.claude" ]; then
    # 從目錄名稱取帳號（如 ~/.claude-max-2 → max-2，再對應帳號名）
    case "$CLAUDE_CONFIG_DIR" in
        *claude-max-2*) account_name="jubo-team" ;;
        *) account_name=$(basename "$CLAUDE_CONFIG_DIR") ;;
    esac
fi
line2+="${orange}${account_name}${reset}"

# session name
if [ -n "$t_session_name" ] && [ "$t_session_name" != "null" ]; then
    line2+="${sep}${magenta}${t_session_name}${reset}"
fi

# model
line2+="${sep}${cyan}${model_name}${reset}"

# context
line2+="${sep}${ctx_color}ctx:${pct_remaining}%${reset}"

# session duration
if [ -n "$session_duration" ]; then
    line2+="${sep}${dim}⏱ ${reset}${white}${session_duration}${reset}"
fi

# thinking
if $thinking_on; then
    line2+="${sep}${magenta}◐ thinking${reset}${dim}(on by default, meta+t to switch current thinking mode)${reset}"
else
    line2+="${sep}${dim}◑ thinking(off by default, meta+t to switch current thinking mode)${reset}"
fi

# ── LINE 3: Tools │ Agents │ Todos │ Config ──
line3=""

# 工具統計
if [ -n "$t_tools" ]; then
    [ -n "$line3" ] && line3+="${sep}"
    line3+="${cyan}◐${reset} ${white}${t_tools}${reset}"
fi

# agent 數量
if [ "$t_agents" -gt 0 ] 2>/dev/null; then
    [ -n "$line3" ] && line3+="${sep}"
    line3+="${green}⚡${t_agents} agents${reset}"
fi

# todo 進度
if [ -n "$t_todo" ] && [ "$t_todo" != "0/0" ]; then
    [ -n "$line3" ] && line3+="${sep}"
    line3+="${yellow}☑ ${t_todo}${reset}"
fi

# config counts
[ -n "$line3" ] && line3+="${sep}"
line3+="${dim}${cfg_md}md ${cfg_rules}rules ${cfg_hooks}hooks${reset}"

# ── Rate limit data（2.1.80+ 原生支援，從 stdin JSON 取得）──
# STEP 01: 從原生 rate_limits 取得資料，轉換欄位名稱以相容既有 render 邏輯
# 原生格式: used_percentage (int) + resets_at (epoch)
# 既有格式: utilization (float) + resets_at (ISO 8601)
usage_stale=false
cache_file="$HOME/.claude/statusline-usage-cache.json"

usage_data=$(echo "$input" | jq -c '
  .rate_limits // empty
  | if . then
      {
        five_hour: {
          utilization: (.five_hour.used_percentage // 0),
          resets_at: ((.five_hour.resets_at // 0) | todate)
        },
        seven_day: {
          utilization: (.seven_day.used_percentage // 0),
          resets_at: ((.seven_day.resets_at // 0) | todate)
        }
      }
    else empty end
' 2>/dev/null)

# STEP 02: 有資料→寫入 cache；無資料→fallback 舊 cache 並標記 stale
if [ -n "$usage_data" ]; then
    echo "$usage_data" > "$cache_file"
else
    if [ -f "$cache_file" ]; then
        usage_data=$(cat "$cache_file" 2>/dev/null)
        usage_stale=true
    fi
fi

# ── [LEGACY] OAuth token resolution（2.1.80 前的 fallback）──
# get_oauth_token() {
#     local token=""
#
#     if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
#         echo "$CLAUDE_CODE_OAUTH_TOKEN"
#         return 0
#     fi
#
#     if command -v security >/dev/null 2>&1; then
#         local blob
#         blob=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null)
#         if [ -n "$blob" ]; then
#             token=$(echo "$blob" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
#             if [ -n "$token" ] && [ "$token" != "null" ]; then
#                 echo "$token"
#                 return 0
#             fi
#         fi
#     fi
#
#     local creds_file="${HOME}/.claude/.credentials.json"
#     if [ -f "$creds_file" ]; then
#         token=$(jq -r '.claudeAiOauth.accessToken // empty' "$creds_file" 2>/dev/null)
#         if [ -n "$token" ] && [ "$token" != "null" ]; then
#             echo "$token"
#             return 0
#         fi
#     fi

#     echo ""
# }
#
# # ── Fetch usage data (cached) ──────────────────────────
# cache_file="/tmp/claude/statusline-usage-cache.json"
# cache_max_age=60
# mkdir -p /tmp/claude
#
# needs_refresh=true
# usage_data=""
# usage_stale=false
#
# if [ -f "$cache_file" ]; then
#     cache_mtime=$(stat -f %m "$cache_file" 2>/dev/null || stat -c %Y "$cache_file" 2>/dev/null)
#     now=$(date +%s)
#     cache_age=$(( now - cache_mtime ))
#     if [ "$cache_age" -lt "$cache_max_age" ]; then
#         needs_refresh=false
#         usage_data=$(cat "$cache_file" 2>/dev/null)
#     fi
# fi
#
# if $needs_refresh; then
#     token=$(get_oauth_token)
#     if [ -n "$token" ] && [ "$token" != "null" ]; then
#         response=$(curl -s --max-time 5 \
#             -H "Accept: application/json" \
#             -H "Content-Type: application/json" \
#             -H "Authorization: Bearer $token" \
#             -H "anthropic-beta: oauth-2025-04-20" \
#             -H "User-Agent: claude-code/2.1.34" \
#             "https://api.anthropic.com/api/oauth/usage" 2>/dev/null)
#         if [ -n "$response" ] && echo "$response" | jq -e '.five_hour' >/dev/null 2>&1; then
#             usage_data="$response"
#             echo "$response" > "$cache_file"
#         fi
#     fi
#     # STEP 01: API 失敗時 fallback 到舊 cache（不管多舊），標記為 stale
#     if [ -z "$usage_data" ] && [ -f "$cache_file" ]; then
#         usage_data=$(cat "$cache_file" 2>/dev/null)
#         usage_stale=true
#     fi
# fi

# ── Rate limit lines ────────────────────────────────────
rate_lines=""

if [ -n "$usage_data" ] && echo "$usage_data" | jq -e . >/dev/null 2>&1; then
    bar_width=10
    # STEP 01: stale 標記（淺灰色）— 原生 rate_limits 為空時 fallback cache 顯示
    stale_tag=""
    if $usage_stale; then
        stale_tag=" ${dim}(stale)${reset}"
    fi

    five_hour_pct=$(echo "$usage_data" | jq -r '.five_hour.utilization // 0' | awk '{printf "%.0f", $1}')
    five_hour_reset_iso=$(echo "$usage_data" | jq -r '.five_hour.resets_at // empty')
    five_hour_reset=$(format_reset_time "$five_hour_reset_iso" "time")
    five_hour_bar=$(build_bar "$five_hour_pct" "$bar_width")
    five_hour_pct_color=$(color_for_pct "$five_hour_pct")
    five_hour_pct_fmt=$(printf "%3d" "$five_hour_pct")

    rate_lines+="${white}current${reset} ${five_hour_bar} ${five_hour_pct_color}${five_hour_pct_fmt}%${reset} ${dim}⟳${reset} ${white}${five_hour_reset}${reset}${stale_tag}"

    seven_day_pct=$(echo "$usage_data" | jq -r '.seven_day.utilization // 0' | awk '{printf "%.0f", $1}')
    seven_day_reset_iso=$(echo "$usage_data" | jq -r '.seven_day.resets_at // empty')
    seven_day_reset=$(format_reset_time "$seven_day_reset_iso" "datetime")
    seven_day_bar=$(build_bar "$seven_day_pct" "$bar_width")
    seven_day_pct_color=$(color_for_pct "$seven_day_pct")
    seven_day_pct_fmt=$(printf "%3d" "$seven_day_pct")

    rate_lines+="\n${white}weekly${reset}  ${seven_day_bar} ${seven_day_pct_color}${seven_day_pct_fmt}%${reset} ${dim}⟳${reset} ${white}${seven_day_reset}${reset}${stale_tag}"

    extra_enabled=$(echo "$usage_data" | jq -r '.extra_usage.is_enabled // false')
    if [ "$extra_enabled" = "true" ]; then
        extra_pct=$(echo "$usage_data" | jq -r '.extra_usage.utilization // 0' | awk '{printf "%.0f", $1}')
        extra_used=$(echo "$usage_data" | jq -r '.extra_usage.used_credits // 0' | awk '{printf "%.2f", $1/100}')
        extra_limit=$(echo "$usage_data" | jq -r '.extra_usage.monthly_limit // 0' | awk '{printf "%.2f", $1/100}')
        extra_bar=$(build_bar "$extra_pct" "$bar_width")
        extra_pct_color=$(color_for_pct "$extra_pct")

        extra_reset=$(date -v+1m -v1d +"%b %-d" 2>/dev/null | tr '[:upper:]' '[:lower:]')
        if [ -z "$extra_reset" ]; then
            extra_reset=$(date -d "$(date +%Y-%m-01) +1 month" +"%b %-d" 2>/dev/null | tr '[:upper:]' '[:lower:]')
        fi

        rate_lines+="\n${white}extra${reset}   ${extra_bar} ${extra_pct_color}\$${extra_used}${dim}/${reset}${white}\$${extra_limit}${reset} ${dim}⟳${reset} ${white}${extra_reset}${reset}${stale_tag}"
    fi
fi

# ── Todo line ────────────────────────────────────────────
todo_line=""
if [ -n "$t_todo" ] && [ "$t_todo" != "0/0" ]; then
    if [ -n "$t_todo_current" ] && [ "$t_todo_current" != "null" ]; then
        todo_line="${yellow}▸${reset} ${white}${t_todo_current}${reset} ${dim}(${t_todo})${reset}"
    else
        # 全部完成或無 in_progress task
        t_done_count="${t_todo%%/*}"
        t_total_count="${t_todo##*/}"
        if [ "$t_done_count" = "$t_total_count" ]; then
            todo_line="${green}✓ All todos complete${reset} ${dim}(${t_todo})${reset}"
        else
            todo_line="${yellow}☑${reset} ${dim}(${t_todo})${reset}"
        fi
    fi
fi

# ── Output ──────────────────────────────────────────────
printf "%b" "$line1"
[ -n "$line2" ] && printf "\n%b" "$line2"
[ -n "$line3" ] && printf "\n%b" "$line3"
[ -n "$rate_lines" ] && printf "\n\n%b" "$rate_lines"
[ -n "$todo_line" ] && printf "\n%b" "$todo_line"

exit 0
