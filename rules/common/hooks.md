# HOOKS | for-AI-parsing

<rules>

HOOK-TYPES:
  PreToolUse: before tool execution(validation/parameter modification)
  PostToolUse: after tool execution(auto-format/checks)
  Stop: session ends(final verification)

HOOK-OUTPUT:
  stdout: 一般情況下 hook 的 stdout 不注入 AI context，Claude 看不到
  stdout-exception: **例外**——PostToolUse 印出 `{"decision":"block","reason":"..."}` 到 stdout 並 `exit 2` 時，reason 會以 blocking error 完整送達 Claude（2026-08-14 對 spec-section-validator 實測確認：故意寫入缺 section 的 spec 檔，reason 全文出現在 Claude 的 context）。不要因為「stdout 看不到」就假設阻擋理由沒送達
  PreToolUse-additionalContext: Claude 看得到（v2.1.9+），即時注入
  PostToolUse-systemMessage: Claude 下一個 turn 看得到；使用者也看得到
  PostToolUse-additionalContext: 有已知 bug（#24788），不可靠，避免依賴
  implication: PostToolUse systemMessage 可同時作為使用者安全網與 Claude 自動觸發來源；CLAUDE.md 規則仍為主要驅動層

HOOK-FAILURE-BLINDSPOT:
  fact: **PostToolUse hook 只在 tool 成功時觸發；失敗的 tool call 完全不觸發**（2026-08-14 實測：`exit 42` 的 Bash、讀不存在檔案的 Read，兩者皆未觸發 hook；同期成功的命令都有觸發）
  implication: 任何「用 PostToolUse 捕捉 tool 失敗」的設計從根本上不可行，不是判定條件寫錯的問題。`~/.claude/hooks/post_tool_error.py` 就是這樣一個空轉了 115 天的錯誤記錄器——它每次成功的 tool call 都跑一次 python3 然後 exit 0，對失敗一無所知
  action: 需要記錄 tool 失敗時，改用 Stop hook 掃 transcript，或接受這層無法自動捕捉；不要留一個永不觸發的記錄器，它會讓 ERRORS.jsonl 的「0 筆」被誤讀成「沒有錯誤」而非「沒有記錄」

AUTO-ACCEPT:
  enable: trusted, well-defined plans
  disable: exploratory work
  banned: dangerously-skip-permissions flag
  prefer: configure allowedTools in ~/.claude.json

TODOWRITE:
  use-for: track multi-step progress / verify understanding / enable real-time steering / show granular steps
  reveals: out-of-order steps / missing items / extra items / wrong granularity / misinterpreted requirements

</rules>
