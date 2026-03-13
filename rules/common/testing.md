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
  agent: tdd-guide
  1: check test isolation
  2: verify mocks
  3: fix implementation not tests(unless tests are wrong)

</rules>
