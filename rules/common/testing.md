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

FAKE-PASS:
  rule: 宣告「通過」前要證明這個測試有能力變紅
  checks: (1) 故意改壞被測邏輯確認會紅（mutation probe）(2) 情境測試只在受測維度上有差異，避免被前面的早退檢查短路、真正的判斷從沒跑到 (3) mock/fake 回傳成功時要做出真函式保證的狀態轉移，否則等待/重試迴圈會卡住而不是紅 (4) 自製測試腳本要有斷言數下限＋.catch／watchdog，await 永不 settle 時 exit 0 不算通過 (5) 在完整套件下跑才算數；型別檢查先確認 tsconfig extends 有解析成功 (6) E2E「前置條件不成立」回報 SKIP，不可算 PASS
  why: 6 份 feedback 同一結構——綠燈來自測試沒跑到目標邏輯，而不是邏輯正確（detect_fake_pass_in_e2e / async-iife-test-exit-zero / fake_must_honor_postcondition / scenario_test_vary_one_dimension / broken_tsconfig_extends_masks_type_errors / verify_test_in_full_suite）

</rules>
