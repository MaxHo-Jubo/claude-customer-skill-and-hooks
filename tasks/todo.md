# Health Audit TODO — 2026-03-17

來源：`/health` 審計結果 + 使用者回應

---

## 已完成

- [x] **#1 settings.local.json 加入 .gitignore** — 防止未來 secret 洩漏
- [x] **#3 POST-COMMIT-REVIEW hook 加回** — 方案 D：CLAUDE.md（意圖層）+ PostToolUse hook systemMessage（使用者提示層）雙層並存
- [x] **#4 on-correction memory save** — 結論：語意層面規則 hook 無法強制，維持 CLAUDE.md 宣告 + `/weekly-review` 定期補救
- [x] **#5 Compact Instructions 加入 CLAUDE.md** — `<compact>` 區段定義壓縮保留優先序，搭配 PreCompact hook + LEARNING.on-compact 三層齊全

## 使用者自行調整
- [x] **#7 sync-my-claude-setting 補 frontmatter + 優化 description** — 補 name/version/description，description 加入觸發條件與 restore 說明
- [x] **#9 skill descriptions 精簡** — 9 個自建 skill 精簡完成（commit-spec 移除），平均縮減 30-50%
- [x] **#11 MEMORY.md 記憶歸檔** — 新增 3 筆專案記憶 + hook 輸出限制寫入 rules/common/hooks.md（共 6 筆→按類型分類索引）
- [x] **#13 自建 skill 加 version 號** — 10 個自建 skill 加入 `version: 1.0.0`（含 sync-my-claude-setting 補 frontmatter）

## 暫不處理（有明確理由）

- **#2 CLAUDE.md 重複** — repo 用途為備份/同步設定，重複是必然
- **#6 allowedTools 清理（45 條）** — 暫不調整
- **#8 ai-md skill 體積（2698w）** — 不處理
- **#10 TS rules 全域安裝** — 幾乎所有專案都用 TS，不需調整
- **#12 全域 MCP servers** — atlassian/claude-mem/context-mode/context7 全部需要

## 行為觀察備註

- Glob 回傳空結果未交叉驗證 → 已存 `feedback_cross_verify_tool_results.md`
- sync STEP 03 被跳過 → 已存 `feedback_sync_step03_no_skip.md`
- 記憶系統運作正常，糾正後有正確歸檔
