# GIT-WORKFLOW | for-AI-parsing

> 專案特定 commit 規則見 CLAUDE.md COMMIT-MSG section，以該處為準。

<rules>

COMMIT-FORMAT:
  template: "<type>: <description>\n\n<optional body>"
  types: feat/fix/refactor/docs/test/chore/perf/ci
  attribution: disabled(~/.claude/settings.json)

RESTORE-SAFETY:
  banned: 用 `git restore --source=<commit> --worktree -- <files>` 來「還原成我剛才的工作版本」
  why: `--source=<commit>` 是還原成該 commit 的內容，不是還原成你的工作版本；工作目錄的未 commit 變更沒有任何備份會被直接覆蓋。實測踩過：review 後尚未 commit 的 8 處修正全數蒸發，重做一次
  instead:
    - 只想對照舊版行為 → `git show <commit>:<path> > /tmp/old.js` 另存比對，完全不動工作目錄（最安全）
    - 需要暫時切走 → `git stash push -- <files>` 再 `git stash pop`；但對已 commit 的檔案 `stash push <path>` 會是 no-op 且 exit 0，之後的 `pop` 會彈出**別人的** stash，所以先 `git stash list` 確認
    - 只在確定要丟棄工作目錄變更時才用 `git restore --source`

PR-WORKFLOW:
  1: analyze full commit history(not just latest)
  2: git diff [base-branch]...HEAD
  3: draft comprehensive PR summary
  4: include test plan with TODOs
  5: push -u if new branch

</rules>

<rhythm>

FEATURE-IMPL:
  plan: 派 Plan agent → identify dependencies/risks → break into phases
  tdd: 派 general-purpose agent 照 rules/common/testing.md TDD 流程 → RED→GREEN→IMPROVE → verify 80%+ coverage
  review: 派 pr-review-toolkit:code-reviewer agent → fix CRITICAL/HIGH → fix MEDIUM when possible
  commit: detailed message, conventional commits format

</rhythm>
