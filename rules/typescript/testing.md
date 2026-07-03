# TS-TESTING | extends common/testing | for-AI-parsing

<rules>

E2E:
  framework: Playwright
  scope: critical user flows
  tool: playwright plugin MCP（browser_* 工具）或 general-purpose agent 執行 npx playwright test（舊 e2e-runner agent 屬已停用 plugin）

</rules>
