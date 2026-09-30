# TESTING | for-AI-parsing

<rules>

COVERAGE:
  minimum: 80%

TEST-TYPES:
  unit: individual functions/utilities/components
  integration: API endpoints/database operations
  e2e: critical user flows(framework per language)

TDD:
  priority: mandatory
  flow: write-test(RED) → run-fail → implement(GREEN) → run-pass → refactor(IMPROVE) → verify-coverage

TROUBLESHOOT:
  agent: 派 general-purpose agent
  rule: fix implementation not tests(unless tests are wrong)

</rules>
