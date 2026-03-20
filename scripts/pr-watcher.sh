#!/usr/bin/env bash
# pr-watcher.sh — 定期輪詢 GitHub PR，有新/更新的 PR 時發 macOS 通知
# 點擊通知 → 執行 review-pr.sh
#
# 用法：直接執行或由 cron 觸發
#   ~/.claude/scripts/pr-watcher.sh
set -euo pipefail

# ── 監聽的 repo 清單 ──
REPOS=(
    "compal-swhq/luna_web"
    "compal-swhq/luna_RN_HomeCareStaff"
)

# ── 設定 ──
STATE_DIR="$HOME/.claude/pr-watcher"
REVIEW_SCRIPT="$HOME/.claude/scripts/review-pr.sh"
NOTIFIER="terminal-notifier"

# ── 確保 state 目錄存在 ──
mkdir -p "$STATE_DIR"

# ── 確認工具可用 ──
if ! command -v gh &>/dev/null; then
    echo "錯誤: gh CLI 未安裝"
    exit 1
fi

if ! command -v "$NOTIFIER" &>/dev/null; then
    echo "錯誤: terminal-notifier 未安裝"
    exit 1
fi

# ── 輪詢每個 repo ──
for REPO in "${REPOS[@]}"; do
    # repo 名稱作為 state 檔名（/ 換成 _）
    REPO_KEY="${REPO//\//_}"
    STATE_FILE="$STATE_DIR/${REPO_KEY}.json"

    # 取得 open PRs（最近更新的前 20 筆）
    PRS=$(gh api "repos/${REPO}/pulls?state=open&sort=updated&direction=desc&per_page=20" 2>/dev/null) || continue

    # 逐筆檢查
    echo "$PRS" | jq -c '.[]' | while read -r PR; do
        PR_NUMBER=$(echo "$PR" | jq -r '.number')
        PR_TITLE=$(echo "$PR" | jq -r '.title')
        PR_URL=$(echo "$PR" | jq -r '.html_url')
        PR_UPDATED=$(echo "$PR" | jq -r '.updated_at')
        PR_AUTHOR=$(echo "$PR" | jq -r '.user.login')
        PR_DRAFT=$(echo "$PR" | jq -r '.draft')

        # 跳過 draft PR
        if [ "$PR_DRAFT" = "true" ]; then
            continue
        fi

        # 跳過自己的 PR（不 review 自己的）
        if [ "$PR_AUTHOR" = "max_ho" ] || [ "$PR_AUTHOR" = "maxhero" ]; then
            continue
        fi

        # 檢查是否已通知過這個版本
        LAST_SEEN=""
        if [ -f "$STATE_FILE" ]; then
            LAST_SEEN=$(jq -r ".\"${PR_NUMBER}\" // empty" "$STATE_FILE" 2>/dev/null)
        fi

        if [ "$LAST_SEEN" = "$PR_UPDATED" ]; then
            # 已通知過，跳過
            continue
        fi

        # 判斷事件類型
        if [ -z "$LAST_SEEN" ]; then
            EVENT_TYPE="新 PR"
        else
            EVENT_TYPE="PR 更新"
        fi

        # 取得 repo 短名
        REPO_SHORT="${REPO##*/}"

        # 發送通知（osascript）
        osascript -e "display notification \"${PR_TITLE}\" with title \"📋 ${EVENT_TYPE}\" subtitle \"${REPO_SHORT} #${PR_NUMBER}\" sound name \"Ping\"" &>/dev/null || true

        # 記錄待 review 的 PR 到 queue 檔案
        echo "${PR_URL}" >> "$STATE_DIR/review-queue.txt"

        # 更新 state
        if [ -f "$STATE_FILE" ]; then
            TMP=$(mktemp)
            jq ".\"${PR_NUMBER}\" = \"${PR_UPDATED}\"" "$STATE_FILE" > "$TMP" && mv "$TMP" "$STATE_FILE"
        else
            echo "{\"${PR_NUMBER}\": \"${PR_UPDATED}\"}" > "$STATE_FILE"
        fi

        echo "[$(date '+%H:%M:%S')] ${EVENT_TYPE}: ${REPO_SHORT}#${PR_NUMBER} - ${PR_TITLE}"
    done
done
