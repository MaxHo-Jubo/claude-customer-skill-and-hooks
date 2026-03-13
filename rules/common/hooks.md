# HOOKS | for-AI-parsing

<rules>

HOOK-TYPES:
  PreToolUse: before tool execution(validation/parameter modification)
  PostToolUse: after tool execution(auto-format/checks)
  Stop: session ends(final verification)

AUTO-ACCEPT:
  enable: trusted, well-defined plans
  disable: exploratory work
  banned: dangerously-skip-permissions flag
  prefer: configure allowedTools in ~/.claude.json

TODOWRITE:
  use-for: track multi-step progress / verify understanding / enable real-time steering / show granular steps
  reveals: out-of-order steps / missing items / extra items / wrong granularity / misinterpreted requirements

</rules>
