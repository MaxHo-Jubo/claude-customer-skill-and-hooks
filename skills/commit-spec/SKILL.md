---
name: commit-spec
description: "快速 commit spec/ 目錄下的改動，自動產生描述性 commit message。當使用者提到 /commit-spec、想 commit spec 文件、或說「提交 spec」時使用此 skill。"
---

# Commit Spec 文件

快速 commit spec/ 目錄下的改動，產生描述性 commit message。

## 使用方式

- `/commit-spec` — commit 所有 spec 改動
- `/commit-spec <描述>` — 使用指定描述作為 commit message 的一部分

## 執行步驟

1. 執行 `git status` 查看 spec/ 相關的改動（含 untracked）

2. 如果沒有 spec/ 相關改動，告知使用者「沒有需要 commit 的 spec 改動」並結束

3. 分析改動內容：
   - 列出新增、修改、刪除的 spec 檔案
   - 從檔案路徑推斷涉及的模組名稱（如 `spec/case/service.md` → case/service）

4. 產生 commit message：
   - 遵循 CLAUDE.md 的「Commit Message 規則」，格式：`[Jira編號] 類型(專案標識): 說明`
   - 類型固定為 `chore`
   - 專案標識從 CLAUDE.md 的「專案對照表」查詢，根據當前工作目錄判斷
   - Jira 編號從 branch 名稱取得（若有）
   - 說明部分：`建立/更新/移除 <模組列表> spec`
   - 如果使用者提供了描述參數，附加到說明中
   - 範例：
     - `chore(FE): 建立 case/service spec`
     - `[ERPD-1234] chore(v3FE): 更新 redux/caseReducer, daycase/index spec`

5. 執行：
   ```bash
   git add spec/
   git commit -m "<generated message>"
   ```

6. Commit 完成後：
   - 顯示 commit hash 和 message
   - 如果專案有 `spec/file-mapping.json`，提醒執行：
     `node ~/.claude/scripts/generate-spec-mapping.cjs <project-root>`

## 判斷動詞規則

| 狀態 | 動詞 |
|------|------|
| 新增的檔案 | 建立 |
| 修改的檔案 | 更新 |
| 混合 | 建立/更新 |
| 刪除 | 移除 |

## 注意事項

- 只 stage spec/ 目錄下的檔案，不動其他改動
- commit message 用繁體中文
- 專案標識必須從 CLAUDE.md 的對照表查詢，不要硬編碼
