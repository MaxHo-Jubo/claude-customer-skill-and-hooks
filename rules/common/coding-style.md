# CODING-STYLE | for-AI-parsing

> 本檔為 code style 單一真相（2026-07-27 集中化：原全域 CLAUDE.md <code-style> 摘要與 ~/Documents/CLAUDE.md 程式碼規範已併入此處，不再跨層重複）。

<rules>

TOOL-USE:
  priority: critical
  edit: 編輯既有檔案一律用 Edit，建新檔用 Write
  banned: sed -i 編輯檔案（曾清空 build.gradle）

IF-BRACES:
  rule: if 語句一律用 { } 包裹，禁止單行省略大括號

STEP-COMMENTS:
  scope: 函式/方法內部各階段程式碼；不加在函式本身的說明註解
  format: 「STEP XX: 說明」，每個函式從 STEP 01 重新起算
  nesting: 遇縮排或邏輯分支階層 +1（STEP 01 內縮排 → STEP 01.01），最多 4 階（STEP 01.01.01.01）
  react: functional component 本體免加；內部成員函式的內部邏輯要加

COMMENT-REQUIRED:
  vars: 變數與常數都要註解用途與意義
  funcs: 函式/方法註解用途、參數與回傳值格式；JS/TS 依 JSDoc 規範

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
  banned: 未經解釋的數字常數
  action: 抽出為具名常數並加上用途註解

NULL-SAFETY:
  action: 空值/undefined 存取必須做防護
  patterns: optional chaining(?.) / guard clause / default value
  scope: 所有可能為 null/undefined 的變數存取

COMMENT-ACCURACY:
  rule: 程式邏輯與註解必須一致
  banned: 過時註解 / 錯誤註解 / 註解錯字

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
- [ ] if statements braced（無單行 if）
- [ ] STEP comments present & correctly numbered

</checklist>
