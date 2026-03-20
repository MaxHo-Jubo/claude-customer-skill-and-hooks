#!/usr/bin/env bash
# review-pr.sh — 本機手動觸發 PR review，結果貼到 PR comment
#
# 用法：
#   review-pr.sh <PR_NUMBER_OR_URL>
#   review-pr.sh 1234
#   review-pr.sh https://github.com/org/repo/pull/1234
#
# 使用 CLAUDE_CONFIG_DIR=~/.claude-review 隔離帳號（省個人額度）
# 需先執行一次：CLAUDE_CONFIG_DIR=~/.claude-review claude auth login
set -euo pipefail

# ── 參數檢查 ──
if [ -z "${1:-}" ]; then
    echo "用法: review-pr.sh <PR_NUMBER_OR_URL>"
    exit 1
fi

PR_INPUT="$1"

# ── 設定 ──
REVIEW_CONFIG_DIR="$HOME/.claude-review"
RESULT_FILE="/tmp/claude-review-result-$$.md"

# ── 檢查認證 ──
if [ ! -d "$REVIEW_CONFIG_DIR" ]; then
    echo "錯誤: $REVIEW_CONFIG_DIR 不存在"
    echo "請先執行: CLAUDE_CONFIG_DIR=$REVIEW_CONFIG_DIR claude auth login"
    exit 1
fi

# ── 清理舊結果 ──
rm -f "$RESULT_FILE"

# ── 執行 review ──
echo "開始 PR review: $PR_INPUT"
echo "使用帳號: $REVIEW_CONFIG_DIR"
echo "結果檔案: $RESULT_FILE"
echo "---"

# claude -p 的 stdout 輸出導到 /dev/null，只保留檔案結果
CLAUDE_CONFIG_DIR="$REVIEW_CONFIG_DIR" claude -p "$(cat <<EOF
Use the pr-reviewer agent in full mode to review this PR: ${PR_INPUT}

mode: full

重要規則：
1. 所有輸出必須使用繁體中文（檔案路徑、code identifier 維持英文）
2. 只產出一份報告，嚴格按照 pr-reviewer agent 定義的輸出格式（Code Review Results + Quality Score）
3. 不要重複輸出英文版本
4. 將完整 review 結果寫入 ${RESULT_FILE}
5. 不要用 gh pr comment，外部 script 會處理
6. 不要只印到 stdout，必須寫檔
EOF
)" --allowedTools "Read,Write,Edit,Grep,Glob,Bash,Agent" --max-turns 50 > /dev/null || true

# ── 檢查結果 ──
if [ ! -f "$RESULT_FILE" ]; then
    echo "錯誤: review 結果檔案未產生 ($RESULT_FILE)"
    exit 1
fi

echo "---"
echo "Review 完成，結果已寫入: $RESULT_FILE"
echo ""

# ── 預覽結果 ──
cat "$RESULT_FILE"
echo ""

# ── 詢問是否貼到 PR ──
read -p "是否將結果貼到 PR comment？(y/N) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # 從 PR input 取得 PR number 和 repo
    PR_JSON=$(gh pr view "$PR_INPUT" --json number,url 2>/dev/null)
    PR_NUMBER=$(echo "$PR_JSON" | jq -r '.number')
    # 從 URL 解析 owner/repo（例如 https://github.com/compal-swhq/luna_web/pull/10421）
    PR_REPO=$(echo "$PR_JSON" | jq -r '.url' | sed 's|https://github.com/||; s|/pull/.*||')

    if [ -z "$PR_NUMBER" ] || [ -z "$PR_REPO" ]; then
        echo "錯誤: 無法取得 PR 資訊"
        exit 1
    fi

    gh pr comment "$PR_NUMBER" --repo "$PR_REPO" --body-file "$RESULT_FILE"
    echo "已貼到 ${PR_REPO}#${PR_NUMBER}"
else
    echo "已跳過。結果保留在: $RESULT_FILE"
fi

# ── 清理 ──
# 不刪 result file，使用者可能還要看
