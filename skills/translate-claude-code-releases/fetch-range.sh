#!/usr/bin/env bash
# fetch-range.sh — 取得 claude-code releases 待翻譯範圍，並產生原始 notes 資料檔
#
# 用法：
#   fetch-range.sh                # 自動模式：從 last-version.txt 記錄版本「之後（不含）」翻到最新
#   fetch-range.sh 2.1.154        # 指定模式：從 2.1.154「（含）」翻到最新
#   fetch-range.sh v2.1.154       # 開頭 v 會自動去除
#
# 行為：
#   - 寫入 raw.md（純抓取的原始英文 release notes，依時間 舊→新 排列；供翻譯 subagent 讀取）
#   - stdout 印出範圍 metadata 供主 agent 解析（FROM/TO/COUNT/MODE/RAW）
#   - 不更新 last-version.txt（成功翻譯後才由主 agent 用 Write 更新，避免翻譯失敗卻記錄）
set -euo pipefail

# STEP 01: 基礎路徑與常數
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"   # skill 根目錄（state 與 raw.md 落點）
STATE_FILE="$SKILL_DIR/last-version.txt"     # 記錄上次翻譯到的最新版本
RAW_FILE="$SKILL_DIR/raw.md"                 # 原始 release notes 暫存檔
REPO="anthropics/claude-code"                # 目標 repo

# STEP 02: 去除版本號開頭的 v（v2.1.154 -> 2.1.154）
norm() { echo "${1#v}"; }

# STEP 03: 決定起始版本與 inclusive 旗標
#   INCLUSIVE=1 → 起始版本本身要翻譯；INCLUSIVE=0 → 只翻起始版本「之後」的新版本
if [ "$#" -ge 1 ] && [ -n "${1:-}" ]; then
  START="$(norm "$1")"; INCLUSIVE=1; MODE="explicit(>= $START)"
elif [ -f "$STATE_FILE" ] && [ -s "$STATE_FILE" ]; then
  START="$(norm "$(cat "$STATE_FILE")")"; INCLUSIVE=0; MODE="auto(> $START)"
else
  START=""; INCLUSIVE=1; MODE="first-run(latest only)"
fi

# STEP 04: 抓取全部 release（tag<TAB>published_at；GitHub 預設 新→舊）
ALL="$(gh api "repos/$REPO/releases" --paginate --jq '.[] | [.tag_name, .published_at] | @tsv')"

# STEP 05: 依版本範圍篩出 tag（用 sort -V 做 semver 比較）
select_tags() {
  # STEP 05.01: 無起始版本（首次執行）→ 只取最新一個
  if [ -z "$START" ]; then
    echo "$ALL" | head -1 | cut -f1
    return
  fi
  # STEP 05.02: 逐版比較，max(v,START)==v 代表 v>=START
  echo "$ALL" | while IFS=$'\t' read -r tag _date; do
    v="$(norm "$tag")"
    top="$(printf '%s\n%s\n' "$v" "$START" | sort -V | tail -1)"
    if [ "$top" = "$v" ]; then
      # v >= START 成立；exclusive 模式再排除等於起始版本者
      if [ "$INCLUSIVE" = "0" ] && [ "$v" = "$START" ]; then
        continue
      fi
      echo "$tag"
    fi
  done
}

# STEP 06: 取得待翻譯 tag 清單（新→舊），反轉成 舊→新 方便依時序閱讀
TAGS_DESC="$(select_tags)"
if [ -z "$TAGS_DESC" ]; then
  echo "COUNT=0"
  echo "MODE=$MODE"
  echo "（沒有比 $START 更新的版本，無需翻譯）" >&2
  exit 0
fi
TAGS_ASC="$(echo "$TAGS_DESC" | tail -r 2>/dev/null || echo "$TAGS_DESC" | tac)"

# STEP 07: 組合 raw.md（每版標題 + 發佈日 + 原始 body）
{
  echo "# Claude Code Releases — 原始英文 notes（待翻譯）"
  echo ""
  while IFS= read -r tag; do
    [ -z "$tag" ] && continue
    body="$(gh api "repos/$REPO/releases/tags/$tag" --jq '.body // "(no release notes)"')"
    date="$(gh api "repos/$REPO/releases/tags/$tag" --jq '.published_at // ""' | cut -dT -f1)"
    echo "## ${tag} （發佈日：${date}）"
    echo ""
    echo "$body"
    echo ""
  done <<< "$TAGS_ASC"
} > "$RAW_FILE"

# STEP 08: 輸出範圍 metadata 給主 agent
FROM="$(echo "$TAGS_ASC" | head -1)"
TO="$(echo "$TAGS_ASC" | tail -1)"
COUNT="$(echo "$TAGS_ASC" | grep -c . || true)"
echo "FROM=$FROM"
echo "TO=$TO"
echo "COUNT=$COUNT"
echo "MODE=$MODE"
echo "RAW=$RAW_FILE"
