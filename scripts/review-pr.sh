#!/usr/bin/env bash
# review-pr.sh — 本機手動觸發 PR full review，結果貼到 PR comment
#
# 用法：
#   review-pr.sh <PR_NUMBER_OR_URL>
#   review-pr.sh 1234
#   review-pr.sh https://github.com/org/repo/pull/1234
#
# 環境變數：
#   REVIEW_TIMEOUT_MIN   逾時分鐘數（預設 30）
#
# 使用 CLAUDE_CONFIG_DIR=~/.claude-review 隔離帳號（省個人額度）
# 需先執行一次：CLAUDE_CONFIG_DIR=~/.claude-review claude auth login
#
# v2（2026-08-13）：
#   - 移除 `> /dev/null || true`。舊版把 claude 的 stdout 全丟棄、exit code 全吞掉，
#     流程一旦卡住或耗盡 max-turns，使用者只看得到無盡的靜默——即「等很久沒反應」的直接來源。
#   - 改為觸發 pr-reviewer skill（主 session orchestrate），不再包一層 pr-reviewer agent。
#   - 加入 watchdog 逾時與進度心跳（macOS 無 timeout 指令，自行以背景 job 實作）。
set -euo pipefail

# ── 參數檢查 ──
if [ -z "${1:-}" ]; then
    echo "用法: review-pr.sh <PR_NUMBER_OR_URL>"
    exit 1
fi

PR_INPUT="$1"

# ── 設定 ──
# 隔離帳號的設定目錄，避免消耗個人額度
REVIEW_CONFIG_DIR="$HOME/.claude-review"
# review 報告的輸出檔（以 PID 區隔，避免多次執行互相覆蓋）
RESULT_FILE="/tmp/claude-review-result-$$.md"
# claude 執行過程的完整 log（失敗時的唯一線索，不得丟棄）
LOG_FILE="/tmp/claude-review-log-$$.txt"
# 逾時分鐘數：full review 實測約 5-15 分鐘，預設 30 分鐘給足餘裕
TIMEOUT_MIN="${REVIEW_TIMEOUT_MIN:-30}"
# 逾時秒數（供 watchdog 使用）
TIMEOUT_SEC=$((TIMEOUT_MIN * 60))
# 進度心跳間隔秒數：讓使用者知道流程還活著
HEARTBEAT_SEC=30
# claude 非互動模式的最大 turn 數：spawn 5 面向 + 收 notification + 評分 + post，實測約 25 turn
MAX_TURNS=80

# ── 檢查認證 ──
if [ ! -d "$REVIEW_CONFIG_DIR" ]; then
    echo "錯誤: $REVIEW_CONFIG_DIR 不存在"
    echo "請先執行: CLAUDE_CONFIG_DIR=$REVIEW_CONFIG_DIR claude auth login"
    exit 1
fi

# ── 清理舊結果 ──
rm -f "$RESULT_FILE" "$LOG_FILE"

# ── 執行 review ──
echo "開始 PR review: $PR_INPUT"
echo "使用帳號: $REVIEW_CONFIG_DIR"
echo "結果檔案: $RESULT_FILE"
echo "執行 log: $LOG_FILE"
echo "逾時設定: ${TIMEOUT_MIN} 分鐘"
echo "---"

CLAUDE_CONFIG_DIR="$REVIEW_CONFIG_DIR" claude -p "$(cat <<EOF
使用 pr-reviewer skill 對這個 PR 做 full review: ${PR_INPUT}

執行方式：呼叫 Skill(pr-reviewer)，依該 skill 的 STEP 01-09 完整執行。

重要規則：
1. 所有輸出必須使用繁體中文（檔案路徑、code identifier 維持英文）
2. 只產出一份報告，嚴格按照 skill 引用的 references/review-spec.md 輸出格式
3. 不要重複輸出英文版本
4. 將完整 review 結果寫入 ${RESULT_FILE}
5. 不要用 gh pr comment，外部 script 會處理
6. 不要只印到 stdout，必須寫檔
EOF
)" --allowedTools "Read,Write,Edit,Grep,Glob,Bash,Agent,Skill" --max-turns "$MAX_TURNS" > "$LOG_FILE" 2>&1 &
CLAUDE_PID=$!

# ── watchdog：逾時強制中止（macOS 無 timeout 指令）──
(
    sleep "$TIMEOUT_SEC"
    if kill -0 "$CLAUDE_PID" 2>/dev/null; then
        echo "" >> "$LOG_FILE"
        echo "[watchdog] 逾時 ${TIMEOUT_MIN} 分鐘，強制中止 review 程序" >> "$LOG_FILE"
        kill -TERM "$CLAUDE_PID" 2>/dev/null || true
    fi
) &
WATCHDOG_PID=$!

# ── 進度心跳：每 HEARTBEAT_SEC 印一次狀態，避免看起來像當機 ──
(
    ELAPSED=0
    while kill -0 "$CLAUDE_PID" 2>/dev/null; do
        sleep "$HEARTBEAT_SEC"
        ELAPSED=$((ELAPSED + HEARTBEAT_SEC))
        # 從 log 尾端取最後一行非空內容，讓使用者看得到目前進度
        LAST_LINE=$(grep -v '^[[:space:]]*$' "$LOG_FILE" 2>/dev/null | tail -1 | cut -c1-100 || true)
        echo "[${ELAPSED}s] review 進行中... ${LAST_LINE}"
    done
) &
HEARTBEAT_PID=$!

# ── 等待完成並取得 exit code ──
# set -e 下 wait 失敗會終止腳本，需顯式捕捉；stderr 導掉以抑制 shell 的 job 終止通知
EXIT_CODE=0
wait "$CLAUDE_PID" 2>/dev/null || EXIT_CODE=$?

# ── 收掉背景 job（kill 後 wait 收割，避免殘留 job 通知污染輸出）──
kill "$WATCHDOG_PID" "$HEARTBEAT_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" "$HEARTBEAT_PID" 2>/dev/null || true

echo "---"

# ── 檢查執行結果（失敗一律揭露 log，不靜默）──
# 被 SIGTERM 中止的 exit code 為 128 + 15，即 watchdog 逾時所致
TIMEOUT_EXIT_CODE=143
if [ "$EXIT_CODE" -eq "$TIMEOUT_EXIT_CODE" ]; then
    echo "錯誤: review 逾時（超過 ${TIMEOUT_MIN} 分鐘）已被中止"
    echo ""
    echo "可調整逾時：REVIEW_TIMEOUT_MIN=45 review-pr.sh $PR_INPUT"
    echo ""
    echo "── log 尾部 40 行 ──"
    tail -40 "$LOG_FILE" || true
    echo ""
    echo "完整 log: $LOG_FILE"
    exit 1
fi

if [ "$EXIT_CODE" -ne 0 ]; then
    echo "錯誤: claude 執行失敗（exit code: $EXIT_CODE）"
    echo ""
    echo "── log 尾部 40 行 ──"
    tail -40 "$LOG_FILE" || true
    echo ""
    echo "完整 log: $LOG_FILE"
    exit 1
fi

if [ ! -f "$RESULT_FILE" ]; then
    echo "錯誤: review 結果檔案未產生 ($RESULT_FILE)"
    echo ""
    echo "常見原因：耗盡 max-turns（目前 $MAX_TURNS）、子 agent 結果未回流、或 skill 未被觸發。"
    echo ""
    echo "── log 尾部 40 行 ──"
    tail -40 "$LOG_FILE" || true
    echo ""
    echo "完整 log: $LOG_FILE"
    exit 1
fi

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
# 不刪 result file 與 log，使用者可能還要看
