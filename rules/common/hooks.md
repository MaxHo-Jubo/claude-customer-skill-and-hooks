# HOOKS | for-AI-parsing

<rules>

HOOK-TYPES:
  PreToolUse: before tool execution(validation/parameter modification)
  PostToolUse: after tool execution(auto-format/checks)
  Stop: session ends(final verification)

HOOK-OUTPUT:
  PostToolUse-stdout: 不注入 AI context，Claude 看不到
  PostToolUse-systemMessage: JSON { systemMessage } 顯示給使用者，Claude 看不到
  implication: hook 無法命令 Claude 做事；需靠 CLAUDE.md 規則驅動 Claude + hook systemMessage 作為使用者端安全網

AUTO-ACCEPT:
  enable: trusted, well-defined plans
  disable: exploratory work
  banned: dangerously-skip-permissions flag
  prefer: configure allowedTools in ~/.claude.json

TODOWRITE:
  use-for: track multi-step progress / verify understanding / enable real-time steering / show granular steps
  reveals: out-of-order steps / missing items / extra items / wrong granularity / misinterpreted requirements

</rules>
