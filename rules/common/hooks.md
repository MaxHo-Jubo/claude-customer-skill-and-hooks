# HOOKS | for-AI-parsing

<rules>

HOOK-TYPES:
  PreToolUse: before tool execution(validation/parameter modification)
  PostToolUse: after tool execution(auto-format/checks)
  Stop: session ends(final verification)

HOOK-OUTPUT:
  stdout: 所有 hook 的 stdout 都不注入 AI context，Claude 看不到
  PreToolUse-additionalContext: Claude 看得到（v2.1.9+），即時注入
  PostToolUse-systemMessage: Claude 下一個 turn 看得到；使用者也看得到
  PostToolUse-additionalContext: 有已知 bug（#24788），不可靠，避免依賴
  implication: PostToolUse systemMessage 可同時作為使用者安全網與 Claude 自動觸發來源；CLAUDE.md 規則仍為主要驅動層

AUTO-ACCEPT:
  enable: trusted, well-defined plans
  disable: exploratory work
  banned: dangerously-skip-permissions flag
  prefer: configure allowedTools in ~/.claude.json

TODOWRITE:
  use-for: track multi-step progress / verify understanding / enable real-time steering / show granular steps
  reveals: out-of-order steps / missing items / extra items / wrong granularity / misinterpreted requirements

</rules>
