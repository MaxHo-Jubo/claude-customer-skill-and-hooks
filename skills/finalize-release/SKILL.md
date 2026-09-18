---
name: finalize-release
description: "手動觸發發版最後兩步驟：(1) merge 版號 PR (2) 執行 jira-release-sync。App Store / Google Play 的正式發布由使用者自行手動處理，不屬於本 skill 範圍。當使用者提到 /finalize-release、「發版最後階段」、「把版號merge掉並同步jira」時觸發。僅支援居服App、日照App（家屬App 目前沒有 GitHub Actions，尚不支援）。"
version: 2.0.0
---

# Finalize Release — 發版最後兩步驟一鍵觸發

使用者確認 App Store / Google Play 都已經手動發布完成後，手動觸發本 skill，
依序完成：merge 版號 PR → 執行 `jira-release-sync`。

**iOS／Android 的正式發布動作雙平台都由使用者自己到 App Store Connect／Google Play Console 網頁手動點擊，
本 skill 完全不觸碰**（2026-09-04 使用者確認：原本規劃過的 `release_pending_ios_version`／
`release_pending_android_version` 兩個 fastlane lane 構想已全部放棄，Fastfile／release.yml 不需要任何改動）。

**PR merge 是對外可見、有點難撤銷的動作**，只有一個確認點（STEP 02），確認後會連續執行到底，中途不會再問。

## 支援範圍（PROJECT-MAP）

| repo 內是否存在 | App 名稱 | GitHub repo |
|---|---|---|
| `HomeCareStaffRN/fastlane/Fastfile` | 居服App | `compal-swhq/luna_RN_HomeCareStaff` |
| `DayCareStaff/fastlane/Fastfile` | 日照App | `compal-swhq/luna_RN_DayCareStaff` |

家屬App（`FamilyMember`）目前沒有 GitHub Actions（送審仍是人工本機跑 fastlane），其他 repo 皆不適用。
判定不到上述兩者時，直接說明原因並停止，不要猜。

## 執行步驟

### STEP 00: 判定 App

1. `git rev-parse --show-toplevel` 取得目前 repo 根目錄。
2. 檢查 `HomeCareStaffRN/fastlane/Fastfile` 或 `DayCareStaff/fastlane/Fastfile` 是否存在於該根目錄下，對應判定 App 名稱與 GitHub repo（見上方 PROJECT-MAP）。
3. 兩者皆非 → 回報「目前目錄不是居服App或日照App的repo（或家屬App尚不支援），本 skill 無法執行」，結束。

### STEP 01: 找版號 PR

```bash
gh pr list --repo <repo> --state open --json number,title,headRefName,url
```

篩出 `headRefName` 符合正規表示式 `^\d+\.\d+\.\d+$`（純版本號，`commit_version` lane 建立的 branch 就是這個命名方式）。

- 0 筆 → 回報「找不到待處理的版號 PR，請確認 commit_version 或 release lane 是否已跑過」，結束。
- ≥2 筆 → 全部列出（PR 號、branch、標題），請使用者指定要處理哪一筆，不要自己猜。
- 1 筆 → 記錄 `PR_NUMBER`、`VERSION`（= branch 名稱）、`PR_URL`。

### STEP 02: 唯一確認點

輸出格式：

```
## 發版最終確認 — {APP_NAME} {VERSION}

版號 PR：{PR_URL}

接下來會依序執行：
1. Merge 版號 PR #{PR_NUMBER}（一定用 merge commit）
2. 執行 jira-release-sync（過程中還會有它自己的候選清單確認）

請確認：
- [ ] App Store / Google Play 都已經手動發布完成

確認後會連續執行到底，中途不會再問。是否繼續？
```

**在使用者明確回覆確認前，不得執行 STEP 03 之後的任何動作。**

### STEP 03: Merge 版號 PR

```bash
gh pr merge <PR_NUMBER> --repo <repo> --merge
```

**禁止 `--squash` / `--rebase`**——`jira-release-sync` 的 `scan_commits.py` 認版本靠 commit subject 精確符合
`Merge pull request #N from {org}/{X.Y.Z}`，squash/rebase 不會產生這個 subject，會讓 jira-release-sync 整個失效。

失敗（conflict、required check 未過等）→ 停止，明確提示「PR #{PR_NUMBER} merge 失敗，需要手動 merge 之後再手動跑 `/jira-release-sync`」。

### STEP 04: 執行 jira-release-sync

直接呼叫既有 `jira-release-sync` skill 的完整流程（沿用它自己 STEP 00~06，包含內部候選清單確認 gate，不跳過）。
`weeks` 參數預設帶 `2`（比 jira-release-sync 自己預設的 1 週保守，涵蓋版號 PR 開了一段時間才 merge 的情況）；
若使用者在觸發本 skill 時有指定週數，原樣傳遞。

### STEP 05: 總結

```
## 發版最終步驟完成 — {APP_NAME} {VERSION}

- PR #{PR_NUMBER} merge：✅/❌
- jira-release-sync：（沿用該 skill 自己的 STEP 06 輸出）
```

## 注意事項

- iOS／Android 的正式發布一律在 App Store Connect／Google Play Console 網頁手動處理，Fastfile 沒有、也不需要對應的 lane。
