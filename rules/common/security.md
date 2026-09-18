# SECURITY | for-AI-parsing

<checklist label="pre-commit mandatory">

- [ ] no hardcoded secrets(API keys/passwords/tokens) — staged 內容已用 SECRET-MGMT pre-commit-scan 掃過
- [ ] all user inputs validated
- [ ] SQL injection prevention(parameterized queries)
- [ ] XSS prevention(sanitized HTML)
- [ ] CSRF protection enabled
- [ ] auth/authz verified
- [ ] rate limiting on all endpoints
- [ ] error messages don't leak sensitive data
- [ ] logs don't contain sensitive data(token/password/API key/session)

</checklist>

<rules>

SECRET-MGMT:
  banned: hardcoded secrets in source
  scope: 不只原始碼——腳本、報告、memory、`~/.claude.json`／`.mcp.json` 等設定檔，一律不得寫入明文憑證（正式環境 DB 連線字串、密碼、token）
  action: environment variables or secret manager
  mcp-config: MCP server 連線字串用 `${VAR}` 展開（2026-09-14 實證：`~/.claude.json` 的 luna-web-readonly `env.MDB_MCP_CONNECTION_STRING` 用此寫法可正常連線）；交付時告訴 user 要 export 哪些變數，只列變數名、不列值
  pre-commit-scan: commit 前先跑 `git diff --cached --name-only -E -G'://[^/:@[:space:]]+:[^@/[:space:]]+@|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY'`，只列命中的檔名，不會把憑證值印進 context（違反 LOG-SAFETY）。有輸出 → 停止 commit，回報檔名。2026-09-14 已用假樣本驗證：連線字串內嵌密碼、ghp_、sk-、AIza、PEM 私鑰 5 類全部命中，`task-runner`、`desk-lamp`、不含密碼的連線字串不誤判。本機沒裝 gitleaks／trufflehog／git-secrets，這步是 commit 前唯一的憑證防線
  why-scope: 2026-08-24～09-14 至少 2 個 session 把明文正式環境憑證往 `~/.claude.json`、data-fix 腳本裡寫，被平台分類器擋下；另 1 個 session 發現正式環境憑證已經 stage 進 git，分類器當時沒有攔下。2026-09 另有 5 組明文憑證外洩到 claude-mem（追蹤見 claude-customer-skill-and-hooks 專案 auto-memory project_2026_09_secret_leak_incident_pending_rotations）
  startup: validate required secrets present
  exposed: rotate immediately

LOG-SAFETY:
  banned: 禁止在 log 中印出敏感資料（token/password/API key/session）
  action: log 前過濾或遮罩敏感欄位

SECURITY-INCIDENT:
  1: STOP immediately
  2: 執行 /security-review skill（本機無專用 security-reviewer agent）
  3: fix CRITICAL before continuing
  4: rotate exposed secrets
  5: review entire codebase for similar issues

</rules>
