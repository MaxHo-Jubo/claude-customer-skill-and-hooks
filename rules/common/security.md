# SECURITY | for-AI-parsing

<checklist label="pre-commit mandatory">

- [ ] no hardcoded secrets(API keys/passwords/tokens)
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
  action: environment variables or secret manager
  startup: validate required secrets present
  exposed: rotate immediately

LOG-SAFETY:
  banned: 禁止在 log 中印出敏感資料（token/password/API key/session）
  action: log 前過濾或遮罩敏感欄位

SECURITY-INCIDENT:
  1: STOP immediately
  2: security-reviewer agent
  3: fix CRITICAL before continuing
  4: rotate exposed secrets
  5: review entire codebase for similar issues

</rules>
