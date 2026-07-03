# PERFORMANCE | for-AI-parsing

<rules>

MODEL-SELECT:
  rule: 模型分工表見 ~/.claude/harness/model-dispatch.md §3（haiku=批次機械/格式整理、sonnet=預設工作馬、opus=架構/模糊除錯/裁判；Haiku 禁區與升降級狀態機同檔）

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
  agent: 派 general-purpose agent（本機無專用 build-error-resolver）
  flow: analyze errors → fix incrementally → verify after each fix

</rules>
