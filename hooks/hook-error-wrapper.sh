#!/usr/bin/env bash
# hook-error-wrapper.sh — 包裝 hook 命令，失敗時記錄到 ERRORS.jsonl
#
# 用法: hook-error-wrapper.sh <hook_event> <command...>
# 範例: hook-error-wrapper.sh PostToolUse node ~/.claude/scripts/spec-section-validator.cjs
#
# - stdin 透傳給實際 hook 命令
# - stdout 透傳回 Claude Code（PreToolUse additionalContext 等需要）
# - 失敗時（exit code != 0）附加一筆 JSONL 記錄到 ~/.claude/.learnings/ERRORS.jsonl

# STEP 01: 解析參數
HOOK_EVENT="$1"
shift
HOOK_CMD="$*"
# 從命令中取腳本名作為識別（取最後一個路徑的 basename，去掉副檔名）
HOOK_SCRIPT_NAME=$(basename "${@: -1}" | sed 's/\.[^.]*$//')

# STEP 02: 讀取 stdin 暫存（hook 需要 passthrough）
STDIN_TMP=$(mktemp)
STDERR_TMP=$(mktemp)
cat > "$STDIN_TMP"

# STEP 03: 執行實際 hook，透傳 stdin，保留 stdout，捕獲 stderr
"$@" < "$STDIN_TMP" 2>"$STDERR_TMP"
EXIT_CODE=$?

# STEP 04: 失敗時記錄錯誤
# exit 2 是 PostToolUse/PreToolUse 的「阻擋」約定信號，不是進程失敗——
# hook 正常擋下一次操作也會 exit 2。單純排除 exit 2 會漏記真正 crash 成 2 的情況，
# 所以再看 stderr：正常阻擋的 reason 走 stdout（stderr 空），真 crash 一定有 stderr。
# 依據：2026-08-14 實測，ERRORS.jsonl 29/53 筆假陽性全部是 exit 2 + stderr 空。
SHOULD_LOG=1
if [ $EXIT_CODE -eq 0 ]; then
    SHOULD_LOG=0
elif [ $EXIT_CODE -eq 2 ] && [ ! -s "$STDERR_TMP" ]; then
    SHOULD_LOG=0
fi

if [ $SHOULD_LOG -eq 1 ]; then
    LOG_DIR="$HOME/.claude/.learnings"
    LOG_FILE="$LOG_DIR/ERRORS.jsonl"
    mkdir -p "$LOG_DIR"

    # 截取 stderr 前 500 字元
    STDERR_CONTENT=$(head -c 500 "$STDERR_TMP")

    # 用 python3 生成合法 JSON（避免 shell 跳脫問題）
    python3 -c "
import json, os, sys
from datetime import datetime, timezone

record = {
    'ts':        datetime.now(timezone.utc).isoformat(),
    'skill':     'hook:' + sys.argv[1],
    'tool':      sys.argv[2],
    'exit_code': int(sys.argv[3]),
    'cmd':       sys.argv[4][:300],
    'error':     sys.argv[5][:500],
    'task_hint': os.environ.get('CLAUDE_TASK_DESCRIPTION', ''),
}

with open(sys.argv[6], 'a', encoding='utf-8') as f:
    f.write(json.dumps(record, ensure_ascii=False) + '\n')
" "$HOOK_SCRIPT_NAME" "$HOOK_EVENT" "$EXIT_CODE" "$HOOK_CMD" "$STDERR_CONTENT" "$LOG_FILE" 2>/dev/null
fi

# STEP 05: 清理暫存檔，回傳原始 exit code
rm -f "$STDIN_TMP" "$STDERR_TMP"
exit $EXIT_CODE
