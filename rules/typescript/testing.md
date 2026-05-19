# TS-TESTING | extends common/testing | for-AI-parsing

<rules>

E2E:
  framework: Playwright
  scope: critical user flows
  agent: e2e-runner
  screenshot-evidence-rule: 截圖測試報告需符合「斷言截圖三合一規範」— 每個 step 同時具備 (1) 程式邏輯斷言 throw + 實測 vs 預期 (2) 真實頁面操作或視覺變更 (3) evidence overlay 注入結論。詳見 jira-test-report skill v2.4.0+ / cup-build-test skill v1.2.0+。純資料比對 step（截圖前後雷同）視為 anti-pattern，必須補 UI 證據（select.size=N 展開 / 逐一 selectOption / DOM highlight 任一）。

</rules>
