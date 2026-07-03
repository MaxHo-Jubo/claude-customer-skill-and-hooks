# GIT-WORKFLOW | for-AI-parsing

> 專案特定 commit 規則見 CLAUDE.md COMMIT-MSG section，以該處為準。

<rules>

COMMIT-FORMAT:
  template: "<type>: <description>\n\n<optional body>"
  types: feat/fix/refactor/docs/test/chore/perf/ci
  attribution: disabled(~/.claude/settings.json)

PR-WORKFLOW:
  1: analyze full commit history(not just latest)
  2: git diff [base-branch]...HEAD
  3: draft comprehensive PR summary
  4: include test plan with TODOs
  5: push -u if new branch

</rules>

<rhythm>

FEATURE-IMPL:
  plan: 內建 Plan agent → identify dependencies/risks → break into phases
  tdd: superpowers:test-driven-development skill → RED→GREEN→IMPROVE → verify 80%+ coverage
  review: pr-review-toolkit:code-reviewer agent → fix CRITICAL/HIGH → fix MEDIUM when possible
  commit: detailed message, conventional commits format
  # 2026-07-03: planner/tdd-guide/code-reviewer 舊 agent 屬已停用 plugin，改指向實際可用資源

</rhythm>
