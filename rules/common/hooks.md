# HOOKS | for-AI-parsing

<rules>

HOOK-TYPES:
  PreToolUse: before tool execution(validation/parameter modification)
  PostToolUse: after successful tool execution(auto-format/checks)
  PostToolUseFailure: after a tool call fails(error logging；讀 `error`/`is_interrupt`)
  Stop: session ends(final verification)

HOOK-OUTPUT:
  stdout: 一般情況下 hook 的 stdout 不注入 AI context，Claude 看不到
  stdout-exception: **例外**——PostToolUse 印出 `{"decision":"block","reason":"..."}` 到 stdout 並 `exit 2` 時，reason 會以 blocking error 完整送達 Claude（2026-08-14 對 spec-section-validator 實測確認：故意寫入缺 section 的 spec 檔，reason 全文出現在 Claude 的 context）。不要因為「stdout 看不到」就假設阻擋理由沒送達
  PreToolUse-additionalContext: Claude 看得到（v2.1.9+），即時注入
  PostToolUse-systemMessage: Claude 下一個 turn 看得到；使用者也看得到
  PostToolUse-additionalContext: 有已知 bug（#24788），不可靠，避免依賴
  implication: PostToolUse systemMessage 可同時作為使用者安全網與 Claude 自動觸發來源；CLAUDE.md 規則仍為主要驅動層

HOOK-FAILURE-BLINDSPOT:
  fact: **PostToolUse 只在 tool 成功時觸發；失敗走獨立事件 `PostToolUseFailure`**（2026-09-14 以 Claude Code 2.1.270 隔離 `--settings` 實測：`exit 42` 的 Bash、讀不存在檔案的 Read 皆觸發 PostToolUseFailure，輸入含 `error`（如 `"Exit code 42\nboom"`）、`is_interrupt`、`duration_ms`，沒有 `tool_response`；被權限/sandbox 擋下的呼叫兩種事件都不觸發）
  action: 記錄 tool 失敗時掛 `PostToolUseFailure`、讀 `error` 欄位。`~/.claude/hooks/post_tool_error.py` 原本掛在 PostToolUse、讀 `tool_response.exit_code`，空轉到 2026-09-14 才改掛。不要留一個永不觸發的記錄器，它會讓 ERRORS.jsonl 的「0 筆」被誤讀成「沒有錯誤」而非「沒有記錄」
  why: 2026-08-14 版本只確認「PostToolUse 不觸發」，就推論「用 hook 捕捉失敗從根本上不可行、改用 Stop hook 掃 transcript」，沒查有沒有其他事件——否定結論前沒驗觀測範圍（見 CLAUDE.md verify-the-observer）

AUTO-ACCEPT:
  enable: trusted, well-defined plans
  disable: exploratory work
  banned: dangerously-skip-permissions flag
  prefer: configure allowedTools in ~/.claude.json

TODOWRITE:
  use-for: track multi-step progress / verify understanding / enable real-time steering / show granular steps
  reveals: out-of-order steps / missing items / extra items / wrong granularity / misinterpreted requirements

</rules>
