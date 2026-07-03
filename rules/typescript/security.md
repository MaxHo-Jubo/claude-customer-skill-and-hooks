# TS-SECURITY | extends common/security | for-AI-parsing

<rules>

SECRET-MGMT:
  banned: const apiKey = "sk-proj-xxxxx"
  action: const apiKey = process.env.API_KEY → validate at startup
  agent: general-purpose 依 rules/common/security.md checklist 掃描（舊 security-reviewer 屬已停用 plugin）

</rules>
