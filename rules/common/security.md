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

</checklist>

<rules>

SECRET-MGMT:
  banned: hardcoded secrets in source
  action: environment variables or secret manager
  startup: validate required secrets present
  exposed: rotate immediately

SECURITY-INCIDENT:
  1: STOP immediately
  2: security-reviewer agent
  3: fix CRITICAL before continuing
  4: rotate exposed secrets
  5: review entire codebase for similar issues

</rules>
