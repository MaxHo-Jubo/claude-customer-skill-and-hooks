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

# 去除 ANSI 顏色碼
strip_ansi() {
    printf "%b" "$1" | sed $'s/\x1b\\[[0-9;]*m//g'
}

# 計算字串顯示寬度（去 ANSI 後）
# - ASCII 1 格
# - 2-byte UTF-8 → 1 格（⟳≈▸▸等 Latin Extended / General Punctuation）
# - 3-byte UTF-8 → 視 codepoint 分類：
#     Geometric Shapes (U+25A0~25FF，含 ●○◐◑◯◉) → 2 格（Ghostty/iTerm 實測）
#     CJK / 全形 (U+4E00~9FFF, U+3000~30FF, U+FF00~FFEF) → 2 格
#     其他箭頭/符號（U+2190~24FF, U+2600~26FF） → 1 格
# - 4-byte UTF-8 → 2 格（emoji）
visible_width() {
    strip_ansi "$1" | awk '{
        s=$0; w=0; i=1; n=length(s);
        while(i<=n){
            c=substr(s,i,1); b=0;
            for(k=0;k<256;k++){ if(sprintf("%c",k)==c){b=k;break} }
            if(b<128){ w+=1; i+=1 }
            else if(b<224){ w+=1; i+=2 }
            else if(b<240){
                # 取 3-byte 字元的 codepoint
                c2=substr(s,i+1,1); c3=substr(s,i+2,1);
                b2=0; b3=0;
                for(k=0;k<256;k++){ if(sprintf("%c",k)==c2){b2=k;break} }
                for(k=0;k<256;k++){ if(sprintf("%c",k)==c3){b3=k;break} }
                cp = ((b-224)*4096) + ((b2-128)*64) + (b3-128);
                # Geometric Shapes (●○等) U+25A0..25FF = 9632..9727 → 1 格
                if(cp >= 9632 && cp <= 9727) w+=1;
                # Arrows / Misc Technical / Symbols U+2190..24FF = 8592..9471 → 1 格
                else if(cp >= 8592 && cp <= 9471) w+=1;
                # Misc Symbols U+2600..26FF = 9728..9983 → 1 格
                else if(cp >= 9728 && cp <= 9983) w+=1;
                # CJK / 全形 U+3000+ = 12288+ → 2 格
                else if(cp >= 12288) w+=2;
                else w+=1;
                i+=3;
            }
            else { w+=2; i+=4 }
        }
        print w
    }'
}

# 截斷純文字到 max_width（字元寬，中文 2 格）；尾端補「…」
truncate_visible() {
    local str="$1" max="$2"
    awk -v s="$str" -v m="$max" '
    BEGIN{
        w=0; out=""; n=length(s); i=1;
        while(i<=n && w<m){
            c=substr(s,i,1); b=0;
            for(k=0;k<256;k++){ if(sprintf("%c",k)==c){b=k;break} }
            if(b<128){ cw=1; step=1 }
            else if(b<224){ cw=1; step=2 }
            else if(b<240){
                c2=substr(s,i+1,1); c3=substr(s,i+2,1);
                b2=0; b3=0;
                for(k=0;k<256;k++){ if(sprintf("%c",k)==c2){b2=k;break} }
                for(k=0;k<256;k++){ if(sprintf("%c",k)==c3){b3=k;break} }
                cp = ((b-224)*4096) + ((b2-128)*64) + (b3-128);
                if(cp >= 9632 && cp <= 9727) cw=1;
                else if(cp >= 8592 && cp <= 9471) cw=1;
                else if(cp >= 9728 && cp <= 9983) cw=1;
                else if(cp >= 12288) cw=2;
                else cw=1;
                step=3;
            }
            else { cw=2; step=4 }
            if(w+cw>m) break;
            out = out substr(s,i,step);
            w += cw; i += step;
        }
        if(i<=n) out = out "…";
        print out
    }'
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

    # 強制 C locale → am/pm 為英文（避免 zh_TW 變成「上午/下午」）
    case "$style" in
        time)
            LC_TIME=C date -j -r "$epoch" +"%l:%M%p" 2>/dev/null | sed 's/^ //; s/\.//g' | tr '[:upper:]' '[:lower:]' || \
            LC_TIME=C date -d "@$epoch" +"%l:%M%P" 2>/dev/null | sed 's/^ //; s/\.//g'
            ;;
        datetime)
            LC_TIME=C date -j -r "$epoch" +"%b %-d, %l:%M%p" 2>/dev/null | sed 's/  / /g; s/^ //; s/\.//g' | tr '[:upper:]' '[:lower:]' || \
            LC_TIME=C date -d "@$epoch" +"%b %-d, %l:%M%P" 2>/dev/null | sed 's/  / /g; s/^ //; s/\.//g'
            ;;
        *)
            LC_TIME=C date -j -r "$epoch" +"%b %-d" 2>/dev/null | tr '[:upper:]' '[:lower:]' || \
            LC_TIME=C date -d "@$epoch" +"%b %-d" 2>/dev/null
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
        # STEP 02.01: 砍掉 mcp__<plugin>__<server>__ 前綴，只留工具名；取 top 3
        t_tools=$(jq -r '.message?.content[]? | select(.type == "tool_use") | .name' "$transcript_path" 2>/dev/null \
            | sed 's|^mcp__[^_]*__[^_]*__||' \
            | sort | uniq -c | sort -rn | head -3 \
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

        # STEP 05: 最後 assistant 回應時間（ISO 8601）
        t_last_reply=$(jq -s -r '[.[] | select(.type == "assistant") | .timestamp // empty] | last // ""' "$transcript_path" 2>/dev/null)

        # STEP 06: token 加總（session 累計，所有 assistant turn 的 usage 加起來）
        # 來源：transcript 每個 assistant message 都有 message.usage 四欄
        t_usage_sum=$(jq -s '[.[] | select(.type == "assistant") | .message.usage // {}] |
            {tin: (map(.input_tokens // 0) | add // 0),
             tcc: (map(.cache_creation_input_tokens // 0) | add // 0),
             tcr: (map(.cache_read_input_tokens // 0) | add // 0),
             tout: (map(.output_tokens // 0) | add // 0)}' "$transcript_path" 2>/dev/null)
        t_tok_in=$(echo "$t_usage_sum" | jq -r '.tin // 0' 2>/dev/null)
        t_tok_cc=$(echo "$t_usage_sum" | jq -r '.tcc // 0' 2>/dev/null)
        t_tok_cr=$(echo "$t_usage_sum" | jq -r '.tcr // 0' 2>/dev/null)
        t_tok_out=$(echo "$t_usage_sum" | jq -r '.tout // 0' 2>/dev/null)

        # STEP 07: 寫入 cache
        jq -nc --arg name "$t_session_name" --arg tools "$t_tools" \
            --argjson agents "${t_agents:-0}" --arg todo "$t_todo" \
            --arg todo_current "$t_todo_current" \
            --arg last_reply "$t_last_reply" \
            --argjson tin "${t_tok_in:-0}" --argjson tcc "${t_tok_cc:-0}" \
            --argjson tcr "${t_tok_cr:-0}" --argjson tout "${t_tok_out:-0}" \
            '{name:$name,tools:$tools,agents:$agents,todo:$todo,todo_current:$todo_current,last_reply:$last_reply,tok_in:$tin,tok_cc:$tcc,tok_cr:$tcr,tok_out:$tout}' > "$t_cache" 2>/dev/null
    else
        # STEP 08: 讀取 cache
        t_data=$(cat "$t_cache" 2>/dev/null)
        t_session_name=$(echo "$t_data" | jq -r '.name // ""' 2>/dev/null)
        t_tools=$(echo "$t_data" | jq -r '.tools // ""' 2>/dev/null)
        t_agents=$(echo "$t_data" | jq -r '.agents // 0' 2>/dev/null)
        t_todo=$(echo "$t_data" | jq -r '.todo // ""' 2>/dev/null)
        t_todo_current=$(echo "$t_data" | jq -r '.todo_current // ""' 2>/dev/null)
        t_last_reply=$(echo "$t_data" | jq -r '.last_reply // ""' 2>/dev/null)
        t_tok_in=$(echo "$t_data" | jq -r '.tok_in // 0' 2>/dev/null)
        t_tok_cc=$(echo "$t_data" | jq -r '.tok_cc // 0' 2>/dev/null)
        t_tok_cr=$(echo "$t_data" | jq -r '.tok_cr // 0' 2>/dev/null)
        t_tok_out=$(echo "$t_data" | jq -r '.tok_out // 0' 2>/dev/null)
    fi
fi

# ── Lifetime 5h aggregation (cached 30s) ──────────────
# 聚合最近 5h 內有活動的所有 session 的 usage，對齊 5h quota window
l5_tok_in=0 l5_tok_cc=0 l5_tok_cr=0 l5_tok_out=0
l5_cache="/tmp/claude/statusline-lifetime-5h.json"

l5_refresh=true
if [ -f "$l5_cache" ]; then
    l5_age=$(( $(date +%s) - $(stat -f %m "$l5_cache" 2>/dev/null || echo 0) ))
    [ "$l5_age" -lt 30 ] && l5_refresh=false
fi

if $l5_refresh; then
    now_ts=$(date +%s)
    cutoff_ts=$(( now_ts - 5*3600 ))
    # STEP 01: 先用 find -mmin 快速過濾 5h 內有改動的 transcript，避免掃 2000+ 檔
    l5_files=$(find "$HOME/.claude/projects" -name "*.jsonl" -type f -mmin -300 2>/dev/null)

    if [ -n "$l5_files" ]; then
        # STEP 02: 把符合的檔案丟給 jq 聚合，只算 timestamp 在 cutoff 之後的 assistant turn
        l5_sum=$(echo "$l5_files" | while IFS= read -r f; do
            [ -f "$f" ] && printf "%s\0" "$f"
        done | xargs -0 jq -s --argjson cutoff "$cutoff_ts" '
            [.[]
             | select(type == "object")
             | select(.type == "assistant")
             | select(
                 (.timestamp // "")
                 | split(".")[0] + "Z"
                 | fromdateiso8601? // 0
                 | . >= $cutoff
               )
             | .message.usage // {}] |
            {tin: (map(.input_tokens // 0) | add // 0),
             tcc: (map(.cache_creation_input_tokens // 0) | add // 0),
             tcr: (map(.cache_read_input_tokens // 0) | add // 0),
             tout: (map(.output_tokens // 0) | add // 0)}
        ' 2>/dev/null)

        if [ -n "$l5_sum" ]; then
            l5_tok_in=$(echo "$l5_sum" | jq -r '.tin // 0')
            l5_tok_cc=$(echo "$l5_sum" | jq -r '.tcc // 0')
            l5_tok_cr=$(echo "$l5_sum" | jq -r '.tcr // 0')
            l5_tok_out=$(echo "$l5_sum" | jq -r '.tout // 0')
        fi
    fi

    jq -nc --argjson tin "${l5_tok_in:-0}" --argjson tcc "${l5_tok_cc:-0}" \
        --argjson tcr "${l5_tok_cr:-0}" --argjson tout "${l5_tok_out:-0}" \
        '{tok_in:$tin,tok_cc:$tcc,tok_cr:$tcr,tok_out:$tout}' > "$l5_cache" 2>/dev/null
else
    l5_data=$(cat "$l5_cache" 2>/dev/null)
    l5_tok_in=$(echo "$l5_data" | jq -r '.tok_in // 0')
    l5_tok_cc=$(echo "$l5_data" | jq -r '.tok_cc // 0')
    l5_tok_cr=$(echo "$l5_data" | jq -r '.tok_cr // 0')
    l5_tok_out=$(echo "$l5_data" | jq -r '.tok_out // 0')
fi

# ── Compact count（讀 PreCompact hook 寫入的檔案）────────
compact_count=0
session_id_raw=$(echo "$input" | jq -r '.session_id // .sessionId // empty' 2>/dev/null)
if [ -n "$session_id_raw" ]; then
    cc_file="$HOME/.claude/compact-counts/${session_id_raw}.count"
    if [ -f "$cc_file" ]; then
        compact_count=$(cat "$cc_file" 2>/dev/null || echo 0)
        [ -z "$compact_count" ] && compact_count=0
    fi
fi

# ── Message history（transcript 尾段，取最後 N 筆 user/assistant 純文字）──
# 只在下方 render 時使用，這裡先抽出到變數
history_lines=""
if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    # STEP 01: 抽出 user/assistant 純文字（排除 tool_result / system-reminder / caveat）
    # STEP 02: 只保留最後 N 筆 user + 每筆 user 後方的第一句 assistant 回應
    history_lines=$(jq -s -r '
      [.[]
       | select(type == "object")
       | select(.type == "user" or .type == "assistant")
       | if .type == "user" then
           (if (.message.content | type) == "string" then .message.content
            elif (.message.content | type) == "array" then
              ((.message.content // []) | map(select(.type == "text" or (has("text") and (.type == null)))) | .[0].text // "")
            else "" end) as $t
           | if ($t | length) == 0 then empty
             elif ($t | startswith("<") or startswith("[{") or startswith("Caveat:")) then empty
             else {t: "u", x: ($t | gsub("\n"; " "))}
             end
         else
           (((.message.content // []) | map(select(.type == "text")) | .[0].text // "")) as $t
           | if ($t | length) == 0 then empty else {t: "a", x: ($t | gsub("\n"; " "))} end
         end
      ]
      # 對於連續 assistant，只保留第一筆（最靠近前一個 user）
      | reduce .[] as $m ([];
          if ($m.t == "a" and (length > 0) and (.[length-1].t == "a")) then .
          else . + [$m] end
        )
      # 取最後 8 筆（對應 box 的 8 行）
      | .[-8:]
      | .[]
      | "\(.t)|\(.x)"
    ' "$transcript_path" 2>/dev/null)
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

fi

# ── Last reply line ─────────────────────────────────────
# 最後 assistant 回應時間，超過 55 分鐘顯示 TTL expired 警告
last_reply_line=""
TTL_SECONDS=3300  # 55 分鐘
if [ -n "$t_last_reply" ] && [ "$t_last_reply" != "null" ] && [ "$t_last_reply" != "" ]; then
    reply_epoch=$(iso_to_epoch "$t_last_reply")
    if [ -n "$reply_epoch" ]; then
        reply_fmt=$(format_reset_time "$t_last_reply" "datetime")
        last_reply_line="${dim}last reply${reset} ${white}${reply_fmt}${reset}"
        now_epoch=$(date +%s)
        elapsed=$(( now_epoch - reply_epoch ))
        if [ "$elapsed" -ge "$TTL_SECONDS" ]; then
            last_reply_line+=" ${red}TTL expired${reset}"
        fi
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

# ── Token usage lines（turn 與 session 累計）────────────
# Opus 4.x 定價（USD per 1M tokens）
#   in: $15、cc: $18.75（in×1.25）、cr: $1.50（in×0.10）、out: $75
# 來源：Anthropic 官方 pricing；變動時改下方 awk 公式
calc_cost() {
    local in=$1 cc=$2 cr=$3 out=$4
    awk -v i="$in" -v c="$cc" -v r="$cr" -v o="$out" \
        'BEGIN { printf "%.2f", (i*15 + c*18.75 + r*1.5 + o*75) / 1000000 }'
}

# 顏色：成本分級（綠/黃/紅）
color_for_cost() {
    awk -v c="$1" 'BEGIN {
        if (c+0 < 1) print "g"
        else if (c+0 < 3) print "y"
        else print "r"
    }'
}

# 渲染一排 token 行：label in cc cr ≈$cost
render_tok_line() {
    local label=$1 in=$2 cc=$3 cr=$4 out=$5
    local cost cost_color color_code
    cost=$(calc_cost "$in" "$cc" "$cr" "$out")
    cost_color=$(color_for_cost "$cost")
    case "$cost_color" in
        g) color_code="$green" ;;
        y) color_code="$yellow" ;;
        r) color_code="$red" ;;
    esac
    local in_fmt cc_fmt cr_fmt
    in_fmt=$(format_tokens "$in")
    cc_fmt=$(format_tokens "$cc")
    cr_fmt=$(format_tokens "$cr")
    printf "${dim}%-5s${reset} in=${white}%-7s${reset} cc=${white}%-7s${reset} cr=${white}%-7s${reset} ${dim}≈${reset}${color_code}\$%s${reset}" \
        "$label" "$in_fmt" "$cc_fmt" "$cr_fmt" "$cost"
}

# 本 turn 數字（既有 line 138-141 提取的 current_usage）
turn_tok_line=""
if [ "$input_tokens" -gt 0 ] || [ "$cache_create" -gt 0 ] || [ "$cache_read" -gt 0 ] 2>/dev/null; then
    # turn 沒有 output_tokens（statusline JSON 不含），先當 0
    turn_tok_line=$(render_tok_line "turn" "$input_tokens" "$cache_create" "$cache_read" 0)
fi

# Session 累計（從 transcript 加總）
total_tok_line=""
if [ -n "$t_tok_in" ] && { [ "$t_tok_in" -gt 0 ] || [ "$t_tok_cc" -gt 0 ] || [ "$t_tok_cr" -gt 0 ]; } 2>/dev/null; then
    total_tok_line=$(render_tok_line "total" "$t_tok_in" "$t_tok_cc" "$t_tok_cr" "$t_tok_out")
fi

# 5h lifetime 累計（跨 session）
life_tok_line=""
if { [ "$l5_tok_cc" -gt 0 ] || [ "$l5_tok_cr" -gt 0 ]; } 2>/dev/null; then
    life_tok_line=$(render_tok_line "5h" "$l5_tok_in" "$l5_tok_cc" "$l5_tok_cr" "$l5_tok_out")
fi

# ── Build box content lines ─────────────────────────────
# 區塊順序（自上而下）：rate limits → last reply → tokens
# 每一行放進 box_rows 陣列，之後用 box drawing 包起來並配右側 history
box_rows=()

if [ -n "$rate_lines" ]; then
    # rate_lines 是兩行（5h + weekly）用 \n 串起
    while IFS= read -r r; do
        [ -n "$r" ] && box_rows+=("$r")
    done < <(printf "%b\n" "$rate_lines")
fi

# compact count
if [ "$compact_count" -gt 0 ] 2>/dev/null; then
    if [ "$compact_count" -eq 1 ]; then
        box_rows+=("${dim}compact${reset} ${white}1 time${reset}")
    else
        box_rows+=("${dim}compact${reset} ${white}${compact_count} times${reset}")
    fi
fi

# STEP 01: rate limits 與 token 統計間插入分隔線（sentinel: "__SEP__"）
if [ -n "$turn_tok_line" ] || [ -n "$total_tok_line" ] || [ -n "$life_tok_line" ]; then
    [ ${#box_rows[@]} -gt 0 ] && box_rows+=("__SEP__")
fi

[ -n "$turn_tok_line" ] && box_rows+=("$turn_tok_line")
[ -n "$total_tok_line" ] && box_rows+=("$total_tok_line")
[ -n "$life_tok_line" ] && box_rows+=("$life_tok_line")

# ── History lines（右側）──────────────────────────────
history_rows=()
if [ -n "$history_lines" ]; then
    while IFS= read -r hl; do
        [ -z "$hl" ] && continue
        tag="${hl%%|*}"
        text="${hl#*|}"
        case "$tag" in
            u) history_rows+=("u|$text") ;;
            a) history_rows+=("a|$text") ;;
        esac
    done <<< "$history_lines"
fi

# ── 計算 box 與 history 寬度 ─────────────────────────────
# 計算基準：weekly 行（含中文日期 + ●○ 序列）在 Ghostty Monaspace Neon 下
# 是最寬的內容行。我們取所有 box_rows 最大 visible_width，再加固定補正值，
# 確保右邊框位置落在 terminal 實際 render 的最寬內容之後。
#
# 補正原理：Monaspace Neon 對 ●○ 等 Geometric Shapes 實測為 2 格，但由於
# visible_width 內部計算與 terminal 實際 render 的 cell advance 有微小差異
# （特別是帶色彩跟全形混合時），加 3 格緩衝確保右邊框不被內容擠掉。
# 框線寬度強制以 limit rate（weekly 行）為基準
# token 區塊維持不 pad 收合，由使用者稍後微調
left_content_width=0
if [ -n "$rate_lines" ]; then
    while IFS= read -r r; do
        [ -z "$r" ] && continue
        w=$(visible_width "$r")
        [ "$w" -gt "$left_content_width" ] && left_content_width=$w
    done < <(printf "%b\n" "$rate_lines")
fi
# fallback: 沒 rate 資料時用所有 box_rows 最大寬
if [ "$left_content_width" -eq 0 ]; then
    for r in "${box_rows[@]}"; do
        [ "$r" = "__SEP__" ] && continue
        w=$(visible_width "$r")
        [ "$w" -gt "$left_content_width" ] && left_content_width=$w
    done
fi

# 邊框：│ + space + content + space + │ = content + 4
box_outer_width=$(( left_content_width + 4 ))

# 終端寬度（statusline 非 TTY 下執行，tput 不可靠）
# 優先序：CC_STATUSLINE_WIDTH > COLUMNS > tput cols > fallback 200
term_cols=${CC_STATUSLINE_WIDTH:-0}
[ "$term_cols" -eq 0 ] 2>/dev/null && term_cols=${COLUMNS:-0}
if [ "$term_cols" -eq 0 ] 2>/dev/null; then
    term_cols=$(tput cols 2>/dev/null || echo 0)
fi
# tput 回 80 視為測不到 → 套 fallback 140
[ "$term_cols" -le 80 ] 2>/dev/null && term_cols=140

# 右側 history 可用寬度（扣掉 box 外框與雙空格間隔）
history_width=$(( term_cols - box_outer_width - 2 ))
[ "$history_width" -lt 20 ] && history_width=0

# ── Box drawing 字元（Unicode single-line）────────────
BOX_TL="┌" BOX_TR="┐" BOX_BL="└" BOX_BR="┘" BOX_H="─" BOX_V="│"
BOX_SEP_L="├" BOX_SEP_R="┤"

# 畫一條橫線（中間可帶 label）
# $1 = 總寬（content_width），$2 = label（可空），$3 = 左角，$4 = 右角
draw_border() {
    local w=$1 label=$2 lc=$3 rc=$4
    local inner
    if [ -n "$label" ]; then
        local lw=${#label}
        local remain=$(( w - lw - 2 ))
        local half=$(( remain / 2 ))
        local rest=$(( remain - half ))
        local left_dash="" right_dash=""
        for ((i=0;i<half;i++)); do left_dash+="$BOX_H"; done
        for ((i=0;i<rest;i++)); do right_dash+="$BOX_H"; done
        inner="${left_dash} ${label} ${right_dash}"
    else
        for ((i=0;i<w;i++)); do inner+="$BOX_H"; done
    fi
    printf "${dim}%s%s%s${reset}" "$lc" "$inner" "$rc"
}

# ── Output ──────────────────────────────────────────────
printf "%b" "$line1"
[ -n "$line2" ] && printf "\n%b" "$line2"
[ -n "$line3" ] && printf "\n%b" "$line3"

# ── 印一行 history（無 box 內容，右側對齊 history column）──
print_history_for_row() {
    local idx=$1
    if [ "$history_width" -gt 0 ] && [ "$idx" -lt "${#history_rows[@]}" ]; then
        local hl="${history_rows[$idx]}"
        local tag="${hl%%|*}"
        local text="${hl#*|}"
        local marker txt_color trunc
        if [ "$tag" = "u" ]; then
            marker="${cyan}▶${reset}"
            txt_color="${white}"
        else
            marker="${magenta}◀${reset}"
            txt_color="${dim}"
        fi
        trunc=$(truncate_visible "$text" $(( history_width - 3 )))
        printf "  %b %b%s${reset}" "$marker" "$txt_color" "$trunc"
    fi
}

# Box block + 右側 history（並排，含框線行也顯示 history）
if [ ${#box_rows[@]} -gt 0 ]; then
    printf "\n"
    h_idx=0

    # 頂邊 + 第 1 筆 history
    printf "%b" "$(draw_border $(( left_content_width + 2 )) "" "$BOX_TL" "$BOX_TR")"
    print_history_for_row "$h_idx"
    h_idx=$(( h_idx + 1 ))
    printf "\n"

    total_rows=${#box_rows[@]}
    for ((i=0; i<total_rows; i++)); do
        row="${box_rows[$i]}"

        # sentinel 行 → 畫分隔線 ├────┤，同時並排 history
        if [ "$row" = "__SEP__" ]; then
            sep_inner=""
            for ((j=0;j<left_content_width+2;j++)); do sep_inner+="$BOX_H"; done
            printf "${dim}${BOX_SEP_L}%s${BOX_SEP_R}${reset}" "$sep_inner"
            print_history_for_row "$h_idx"
            h_idx=$(( h_idx + 1 ))
            printf "\n"
            continue
        fi

        row_w=$(visible_width "$row")
        pad=$(( left_content_width - row_w ))
        pad_str=""
        for ((j=0;j<pad;j++)); do pad_str+=" "; done

        # 左側 box 行
        printf "${BOX_V} %b%s ${BOX_V}" "$row" "$pad_str"
        print_history_for_row "$h_idx"
        h_idx=$(( h_idx + 1 ))
        printf "\n"
    done

    # 底邊 + 最後一筆 history
    printf "%b" "$(draw_border $(( left_content_width + 2 )) "" "$BOX_BL" "$BOX_BR")"
    print_history_for_row "$h_idx"
fi

# ── Box 外：last reply / todo（不受框線包圍）────────────
[ -n "$last_reply_line" ] && printf "\n%b" "$last_reply_line"
[ -n "$todo_line" ] && printf "\n%b" "$todo_line"

exit 0
