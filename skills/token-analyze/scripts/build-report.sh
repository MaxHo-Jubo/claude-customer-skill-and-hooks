#!/usr/bin/env bash
# 拼 token-analysis 報表（dogfood 用）
set -e
DATA=/tmp/token-analyze-turns.json
OUT=$1
SESSION_UUID=$2
TRANSCRIPT=$3

fmt_t() {
    awk -v n="$1" 'BEGIN {
        if (n+0 >= 1000000) printf "%.1fm", n/1000000
        else if (n+0 >= 1000) printf "%.1fk", n/1000
        else printf "%d", n
    }'
}

# Summary
read N TIN TCC TCR TOUT < <(jq -r '
  reduce .[] as $t ({n:0,in:0,cc:0,cr:0,out:0};
    {n: (.n+1), in: (.in + $t.in), cc: (.cc + $t.cc),
     cr: (.cr + $t.cr), out: (.out + $t.out)})
  | "\(.n) \(.in) \(.cc) \(.cr) \(.out)"
' "$DATA")

COST=$(awk -v i=$TIN -v c=$TCC -v r=$TCR -v o=$TOUT \
    'BEGIN { printf "%.2f", (i*15 + c*18.75 + r*1.5 + o*75) / 1000000 }')

GEN_TIME=$(date '+%Y-%m-%d %H:%M')
SHORT_UUID=${SESSION_UUID:0:8}

# Per-turn 表格
PER_TURN=$(jq -r '
  to_entries[] | .key as $i | .value as $t |
  ($t.tools | reduce .[] as $x ({}; .[$x] = (.[$x] // 0) + 1) |
   to_entries | map(if .value > 1 then "\(.key)×\(.value)" else .key end) | join(", ")) as $tools_str |
  [$i+1, $t.ts[11:19], $t.in, $t.cc, $t.cr, $t.out, $tools_str] | @tsv
' "$DATA" | awk -F'\t' '
{
  cost = ($3*15 + $4*18.75 + $5*1.5 + $6*75) / 1000000
  # 格式化 token 數
  for (i=3; i<=6; i++) {
    n = $i + 0
    if (n >= 1000000) f[i] = sprintf("%.1fm", n/1000000)
    else if (n >= 1000) f[i] = sprintf("%.1fk", n/1000)
    else f[i] = n
  }
  printf "| %d | %s | %s | %s | %s | %s | $%.2f | %s |\n",
    $1, $2, f[3], f[4], f[5], f[6], cost, $7
}')

# Top 5 燒錢 turn
TOP5=$(jq -r '
  to_entries | map(. + {cost: ((.value.in*15 + .value.cc*18.75 + .value.cr*1.5 + .value.out*75) / 1000000)})
  | sort_by(-.cost) | .[0:5]
  | .[] | .key as $i | .value as $t |
  ($t.tools | reduce .[] as $x ({}; .[$x] = (.[$x] // 0) + 1) |
   to_entries | map(if .value > 1 then "\(.key)×\(.value)" else .key end) | join(", ")) as $tools_str |
  ($t.files | map(split("/") | .[-1]) | unique | .[0:3] | join(", ")) as $files_str |
  "| \($i+1) | \($t.ts[11:19]) | $\((.cost * 100 + 0.5 | floor) / 100 | tostring | if test("\\.\\d$") then . + "0" elif test("^\\d+$") then . + ".00" else . end) | \($tools_str) | \($files_str) |"
' "$DATA")

cat > "$OUT" <<EOF
# Token Analysis — ${SHORT_UUID}

> 生成時間：${GEN_TIME}
> Transcript: \`${TRANSCRIPT}\`
> 總 turn 數：${N}

## Session 工作摘要

__SUMMARY_PLACEHOLDER__

> ※ 摘要從 turn 時間段 + 主要工具 + 主要檔名歸納，幫助判斷哪段工作 token 量較大。

## Summary

| 欄位 | 值 |
|---|---|
| 總 turn 數 | ${N} |
| 總 input | $(fmt_t $TIN) |
| 總 cache_create | $(fmt_t $TCC) |
| 總 cache_read | $(fmt_t $TCR) |
| 總 output | $(fmt_t $TOUT) |
| **總成本** | **\$${COST}** |

### 三種 input token 的意義（提醒）

- \`input_tokens\`：純新寫、沒進快取的輸入（100% 計費）
- \`cache_creation_input_tokens\`：第一次寫入快取的內容，**新讀檔案的真正成本**（125%）
- \`cache_read_input_tokens\`：從快取重讀（10%）

## Top 5 燒錢 turn

| # | 時間 | cost | 工具 | 主要檔案 |
|---|---|---|---|---|
${TOP5}

## Per-turn 明細

| # | 時間 | in | cc | cr | out | cost | 工具 |
|---|---|---|---|---|---|---|---|
${PER_TURN}
EOF

echo "Wrote: $OUT"
