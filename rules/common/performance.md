# PERFORMANCE | for-AI-parsing

<rules>

MODEL-SELECT:
  authority: ~/.claude/harness/model-dispatch.md §3 為模型分工單一真相（2026-07-03 更新，舊 4.5 世代選單已過時）
  haiku: 已解出固定模式的批次套用 / 格式整理；禁區＝除錯、找原因、多步工具串接
  sonnet: 預設工作馬（搜尋 / 明確 spec 實作 / 有測試保護的重構 / checklist 審查）
  opus: 架構設計 / 模糊除錯 / 評審裁判 / 失敗升級終點

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
  agent: general-purpose ＋ superpowers:systematic-debugging skill（舊 build-error-resolver 屬已停用 plugin）
  flow: analyze errors → fix incrementally → verify after each fix

</rules>
