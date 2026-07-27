# PERFORMANCE | for-AI-parsing

<rules>

MODEL-SELECT:
  authority: ~/.claude/harness/model-dispatch.md §3 為模型分工單一真相，分工細節見該檔，勿在此重複

CONTEXT-WINDOW:
  avoid-last-20%: large refactoring / multi-file features / complex debugging
  low-sensitivity: single-file edits / utility creation / docs / simple bug fixes

COMPLEX-TASK:
  1: enable extended thinking
  2: enable plan mode
  3: multiple critique rounds
  4: split role sub-agents

BUILD-FAIL:
  agent: general-purpose ＋ superpowers:systematic-debugging skill（舊 build-error-resolver 屬已停用 plugin）
  flow: analyze errors → fix incrementally → verify after each fix

</rules>
