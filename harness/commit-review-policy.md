# Commit 後審查分級制（POST-COMMIT-REVIEW v2） | status: DONE

> 取代舊版「每次 commit 強制六步」規則（舊版全文見 `~/.claude/CLAUDE.md.bak-20260703`）。
> 設計依據：舊制與 diff 大小無關，改 3 行也跑 6~10 個 agent（M4 機器診斷實測，見 repo `max-m4pro-setting` 分支 harness-diagnosis.md §3）。
> 讀者：主對話模型。觸發時機：用 Bash 成功執行 `git commit` 之後。
> 建立：Fable 5，2026-07-03（M4 機器）；本機化：Sonnet 5，2026-07-03（Tier 2/3 加入 blast radius 步驟）。維護權限：黃區。

## 免跑條件（任一成立 → 只執行通知步驟）

- commit 指令本身包含 push，或 user 說「commit and push」
- 空 commit / commit 失敗
- amend 既有 commit 且新增 diff < 10 行

## 分級判定（機械執行，不憑感覺）

先跑：`git show --stat HEAD --format=""` 取得檔案清單與行數，再依下表由上而下取**第一個**命中的 Tier：

| Tier | 判準（由上而下先命中先用） | 執行步驟 |
|------|--------------------------|---------|
| **0 純文件** | 全部檔案皆為 `.md .html .txt .png .jpg .svg .csv`（文件/圖片/資料） | 只發通知 |
| **1 小改動** | 程式碼變更 ≤ 50 行 且 ≤ 2 個程式碼檔 | eslint（有設定檔才跑）→ 自查 judgment-matrix.md §2 對應 DoD checklist → 通知。**不 spawn agent** |
| **2 標準** | 程式碼變更 ≤ 300 行 且 ≤ 5 個程式碼檔 | eslint → `/simplify` → pr-reviewer agent（lite）→ 自動修 CRITICAL（修完 amend）→ blast radius（見下）→ 通知 |
| **3 大改動** | 超過 Tier 2 門檻，或動到公共 API / 共用 lib / 資料模型 | Tier 2 全部 ＋ `/pr-review-toolkit:review-pr code comments errors tests types` → 修 Critical/Important（不另 commit）→ 通知 |

- 「程式碼檔」= 非 Tier 0 副檔名清單的檔案。
- 通知步驟（所有 Tier 必跑）：`osascript` 發 macOS 通知「commit 與 review 完成（Tier N）」。
- Tier 2/3 發現的問題若是**本次自己寫出來的壞習慣**（非既有代碼）→ 依 knowledge-protocol.md §2 存 feedback memory。

## Blast Radius 分析（Tier 2/3 必跑；資訊性輸出，不自動修改）

用 codebase-memory-mcp 對本次 commit 修改的 symbol 執行影響面分析：

1. `git diff HEAD~1` 抓改動函式清單
2. 逐一 `trace_path`(direction: inbound, risk_labels: true) 查詢 caller 與影響面
3. project 未索引（`list_projects` 確認）→ 標註「impact 未取得」並跳過，不硬跑
4. 揭露遺漏 caller / 影響面時回報給 user，由人工決定是否補 commit
5. **盲區警告**：`trace_path` 對「方法當 callback 參照傳遞」（React class method 綁定後當 prop 傳出、Redux dispatch 等間接呼叫）抓不到——callers 回空不能當「無人呼叫」結論，此類 case 需用 grep 補查（model-dispatch.md §6 graph-first 規則）

## 範例

- 「docs: 補進度報告 HTML」改 2 個 .html → **Tier 0**，只通知。
- 「fix: debounce 門檻 50→80ms」改 1 檔 3 行 → **Tier 1**，eslint（無設定跳過）＋自查 bugfix DoD＋通知。
- 「feat: 班表頁新增請假狀態篩選」改 3 檔 180 行 → **Tier 2**。
- 「refactor: ApiResponse envelope 改版」動共用 lib → **Tier 3**（就算只有 80 行，資料模型 = 公共 API 判準命中）。

## 禁止事項

- 不得為了少跑步驟而故意拆 commit 規避分級（一個邏輯變更拆成 10 個 Tier 1 commit = 違規）。
- Tier 判定有疑義時就近**向上**取嚴（寧可多跑一級）。
- pr-reviewer / review-pr 修出來的改動一律 amend 或留 uncommitted，不得自行開新 commit。
