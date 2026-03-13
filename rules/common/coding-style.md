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

</rules>

<checklist label="完工前檢查">

- [ ] readable + well-named
- [ ] functions <50 lines
- [ ] files <800 lines
- [ ] nesting ≤4 levels
- [ ] proper error handling
- [ ] no hardcoded values → constants/config
- [ ] no mutation → immutable patterns

</checklist>
