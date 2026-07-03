# CODING-STYLE | for-AI-parsing

> 專案特定規則見 CLAUDE.md CODE-STYLE section，以該處為準。

<rules>

IMMUTABILITY:
  priority: critical
  action: 建新物件，禁止 mutate 原物件
  pattern: update(original, field, value) → return new copy
  banned: in-place modify

FILE-ORG:
  principle: many-small > few-large
  lines: 200-400 typical, 800 max
  cohesion: high cohesion, low coupling
  organize: by feature/domain, not by type
  large-module: extract utilities

ERROR-HANDLING:
  action: 每層明確處理 error
  ui-facing: user-friendly message
  server-side: log detailed context
  banned: silently swallow errors

INPUT-VALIDATION:
  scope: system boundaries only
  action: validate all user input before processing
  prefer: schema-based validation
  fail-fast: clear error message
  trust: never trust external data(API responses/user input/file content)

MAGIC-NUMBER:
  action: 數字常數抽出為具名常數並加用途註解

NULL-SAFETY:
  action: 空值/undefined 存取必須做防護
  patterns: optional chaining(?.) / guard clause / default value
  scope: 所有可能為 null/undefined 的變數存取

COMMENT-ACCURACY:
  rule: 程式邏輯與註解必須一致
  action: 修改程式碼時同步更新對應註解；刪除已無對應程式碼的舊註解；拼寫與邏輯一致

STEP-COMMENT-INSERT:
  rule: 既有 STEP 序列前/中插入新註解→整段往後 +1 重排；禁止用 STEP 00 規避重排；插入序列尾端則直接接續編號
  encoding: STEP 01 起算，最多4階(STEP 01.01.01.01)；禁止 STEP 00

WRITE-PRESERVE-COMMENTS:
  rule: Write 整檔重寫既有檔案時必須完整保留所有原註解（檔案層 JSDoc / 函式 JSDoc / @type / STEP 編號）
  action: 優先用 Edit 局部替換；必須 Write 時先 Read 完整檔案並用 `git show HEAD:path` 為 baseline；commit 前自己 grep `/\*\*` 數量與 `STEP 0` 出現次數是否與重寫前一致

GLOBAL-MUTATION:
  rule: 移除或修改全域變數/共用常數/共用函式時，必須搜尋該檔案中所有使用點，確認全部已處理

EXTRACT-SHARED-HELPER:
  rule: 同一個概念性判斷/驗證邏輯出現在 2+ 個檔案時，第一次就抽具名共用 helper（如 `isValidLocation`）放對應 utility 檔，所有呼叫點統一引用；不要「先 inline、之後再說」
  why: Inline 重複是 fail-open 類 bug 的溫床，各處邏輯易分歧（一處檢查空值、另一處不檢查 → 行為不一致）

</rules>

<checklist label="完工前檢查">

- [ ] readable + well-named
- [ ] functions <50 lines
- [ ] files <800 lines
- [ ] nesting ≤4 levels
- [ ] proper error handling
- [ ] no hardcoded values → constants/config
- [ ] no magic numbers → named constants with comments
- [ ] no mutation → immutable patterns
- [ ] null/undefined access guarded
- [ ] comments match actual logic (no stale/wrong comments, no typos)

</checklist>
