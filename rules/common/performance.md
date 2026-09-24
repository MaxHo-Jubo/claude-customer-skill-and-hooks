# PERFORMANCE | for-AI-parsing

<rules>

MODEL-SELECT:
  rule: 模型分工表見 ~/.claude/harness/model-dispatch.md §3（haiku=批次機械/格式整理、sonnet=預設工作馬、opus=架構/模糊除錯/裁判；Haiku 禁區與升降級狀態機同檔）

THINKING:
  owner: thinking 開關與深度由 user 或設定決定，模型不要求、也不假設自己能開關
  config: 本機用 `effortLevel`（~/.claude/settings.json，現值 xhigh）；session 內用 `/effort` 調整

COMPLEX-TASK:
  1: enable plan mode
  2: multiple critique rounds
  3: split role sub-agents

BUILD-FAIL:
  agent: 派 general-purpose agent（本機無專用 build-error-resolver）
  flow: analyze errors → fix incrementally → verify after each fix

</rules>
