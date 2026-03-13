# TS-SECURITY | extends common/security | for-AI-parsing

<rules>

SECRET-MGMT:
  banned: const apiKey = "sk-proj-xxxxx"
  action: const apiKey = process.env.API_KEY → validate at startup
  agent: security-reviewer

</rules>
