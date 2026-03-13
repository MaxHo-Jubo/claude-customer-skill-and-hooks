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
  plan: planner agent → identify dependencies/risks → break into phases
  tdd: tdd-guide agent → RED→GREEN→IMPROVE → verify 80%+ coverage
  review: code-reviewer agent → fix CRITICAL/HIGH → fix MEDIUM when possible
  commit: detailed message, conventional commits format

</rhythm>
