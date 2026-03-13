# PERFORMANCE | for-AI-parsing

<rules>

MODEL-SELECT:
  haiku-4.5: lightweight agents / pair programming / worker agents(90% sonnet capability, 3x savings)
  sonnet-4.5: main dev / orchestration / complex coding
  opus-4.5: complex architecture / deep reasoning / research

CONTEXT-WINDOW:
  avoid-last-20%: large refactoring / multi-file features / complex debugging
  low-sensitivity: single-file edits / utility creation / docs / simple bug fixes

THINKING:
  default: enabled(up to 31,999 tokens)
  toggle: Option+T(macOS) / Alt+T(Windows/Linux)
  config: alwaysThinkingEnabled in ~/.claude/settings.json
  budget: MAX_THINKING_TOKENS env var
  verbose: Ctrl+O

COMPLEX-TASK:
  1: enable extended thinking
  2: enable plan mode
  3: multiple critique rounds
  4: split role sub-agents

BUILD-FAIL:
  agent: build-error-resolver
  flow: analyze errors → fix incrementally → verify after each fix

</rules>
