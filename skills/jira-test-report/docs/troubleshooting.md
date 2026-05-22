# jira-test-report 失敗處理

> 由 jira-test-report skill 用（v2.5.4+ 從 SKILL.md 抽出）。
> AI-parsing 結構化（v2.4.7 套用）：每個 symptom 對應一個 action / why / cause / banned。

## 完整 symptom 清單

```
LOGIN-4xx:
  symptom: API 登入回 4xx
  action: 密碼錯 / account 鎖 → 驗證 .env.local 內容（不要在對話貼密碼）

LOGIN-5xx:
  symptom: API 登入回 5xx
  action: 後端問題 → retry 一次 → 仍失敗則中止

UPLOAD-401:
  symptom: attachment upload 回 401
  action: token 失效 → 重新驗證

COMMENT-ATTACHMENT-VALIDATION:
  symptom: Comment POST 400 ATTACHMENT_VALIDATION_ERROR
  cause: 誤用 v3 ADF + attachment id
  action: 改回 v2 wiki（/rest/api/2/issue/{key}/comment + wiki markup body）

SCREENSHOT-ACCESS-DENIED:
  symptom: 互動模式截圖 access denied
  cause: Playwright MCP 限制只能存到專案根目錄之內
  action: filename 改寫進 frontend/.playwright-mcp/ 或 frontend/ 內，不可寫 ~/Desktop / /tmp

SESSION-EXPIRED:
  symptom: 跑到一半被導回 /login
  why: API 登入 stateless 每跑都重取，不該發生
  if-still-happens: 後端 session 失效時間 < cjs 跑完時間 → 縮短測試或登入 API 加 keep-alive 邏輯

PLAYWRIGHT-MODULE-MISSING:
  symptom: 腳本模式 "Cannot find module 'playwright'"
  action: cd ~/.claude/skills/jira-test-report/helpers && npm install && npx playwright install chromium
  note: .claude/ 階段預設 require jira-test-report/helpers

SELECTOR-NOT-FOUND:
  symptom: 腳本模式 selector 找不到（特別 R18 升級後）
  action: HEADLESS=false 重跑看實際畫面 → 調整 selector

RATE-LIMIT:
  symptom: 跑到一半 rate limit
  banned: 閒置等待（5 分鐘 prompt cache 過期，恢復時燒幾萬 token 重建 cache）
  action: 當前 step 跑完後 /clear → 新 session 用 /jira-test-report --resume 從 progress.md 接續（Phase A/B/C 自動接力）

RESUME-NO-PROGRESS:
  symptom: --resume 但 progress.md 不存在
  action: 提示使用者「尚未跑過，無進度可續，請去掉 --resume 旗標」

PROGRESS-ISSUE-MISMATCH:
  symptom: progress.md 存在但 issue key 不符
  action: 中止，提示「進度檔屬於別的 issue」
```

## 使用方式

- AI 遇到上述 symptom 時，依 `action` 處理；`cause` / `why` 是診斷依據，`banned` 是禁止做的反模式
- SKILL.md 內保留 11 個 symptom 的「symptom → 一行 action」速查表，AI 80% 場景掃 SKILL.md 即可
- 細節（`cause` / `why` / `banned` / `note`）來這查 — 特別是 COMMENT-ATTACHMENT-VALIDATION、SCREENSHOT-ACCESS-DENIED、RATE-LIMIT 三個有完整 why / banned 結構的，比較需要展開閱讀
