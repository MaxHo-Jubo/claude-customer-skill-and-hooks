---
name: jira-release-sync
description: "掃描一段期間內的 git commit，找出已隨版本 merge 進 master（已上架）的 Jira issue，於 Jira 留言告知版本與修正/上線狀態，並將狀態轉為 Resolved、附上結案日。當使用者提到 /jira-release-sync、「掃描已上架的commit留言jira」、「同步發版狀態到jira」、「把上架的issue結案」時觸發。"
version: 1.5.0
---

# Jira Release Sync — 發版狀態同步

掃描一段期間內的 commit，判定哪些 `[ISSUE-ID]` commit 已經隨某個版本上架，
自動在對應 Jira issue 留言版本資訊、轉換狀態為 Resolved、附上結案日。

支援兩種 repo，判定規則完全不同（見下方「Repo 模式判定」）：
- **`app-store` 模式**（居服App／日照App／家屬App）：commit 是否已隨版本 merge 進 master。
- **`luna` 模式**（luna_web）：限 Max_Ho 的 commit 是否已隨版本 tag merge 進 release 分支，frontend/backend 分開判定。

**不寫入 Jira Fix Version 欄位**（見下方說明）——只留言 + 轉態 + 結案日。

## 設定（首次使用會自動引導，沿用 `jira` skill 的設定值）

| 設定項 | 說明 | 範例 |
|--------|------|------|
| `JIRA_CLOUD_ID` | Atlassian Cloud ID | `c7b686ea-9df3-46c7-a982-3f0175a96e59` |

從使用者的 `~/.claude/CLAUDE.md` 讀取（`<conn>` 區塊或「## Jira 設定」表格）。若找不到，比照 `jira` skill 的首次設定流程詢問並寫回 CLAUDE.md。

### Repo 模式判定（先做這一步，決定後面用哪一套規則）

依當前工作目錄路徑判斷，兩套規則完全不同、不可混用：

| 路徑包含 | 模式 | 說明 |
|---------|------|------|
| `luna_web` | `luna` | 見下方「核心判定規則（`luna` 模式）」段落，規則跟 App repo 完全不同（release 分支、tag 判定、限定作者、frontend/backend 分開判定） |
| `HomeCareStaffRN` / `DayCareStaff` / `FamilyMember` | `app-store` | 本文件其餘段落原有規則（master/main 分支、merge commit 規則判版） |

都不符合 → **不要猜**，直接問使用者這個 repo 要套用哪一套規則。

### App 名稱判定（PROJECT-MAP，僅 `app-store` 模式使用）

依當前工作目錄路徑判斷留言中要寫的 App 名稱，對應規則（來自使用者 CLAUDE.md `PROJECT-MAP`）：

| 路徑包含 | App 名稱 |
|---------|---------|
| `HomeCareStaffRN` | 居服App |
| `DayCareStaff` | 日照App |
| `FamilyMember` | 家屬App |

若當前路徑都不符合上述任一 pattern，**不要猜**，直接問使用者這個 repo 對應的留言 App 名稱該寫什麼。

`luna` 模式不需要判定 APP_NAME，留言不含 App 名稱（見下方「留言用詞判定」的 `luna` 模式模板）。

### 留言用詞判定（Jira 專案前綴）

依 Jira ID 前綴（`-` 前的字母部分）決定動作詞，對應使用者 CLAUDE.md `JIRA branch-prefix` 設定：

| 前綴 | 類型 | 動作詞 |
|------|------|--------|
| `LVB` | fix | 修正 |
| `ERPD` | feat | 上線 |
| 其他 | 未知 | 預設用「修正」，並在候選清單標註 `⚠️ 未知專案前綴，請確認用詞` |

留言內容模板（`app-store` 模式）：`{APP_NAME} 版本 {release_version} 已{動作詞}`（例：「居服App 版本 1.50.34 已修正」）。

留言內容模板（`luna` 模式，2026-09-04 使用者確認，不含 APP_NAME）：`{release_version} 已{動作詞}`（例：「2026.09.03 已上線」「2026.09.03 已修正」）。

### 留言標註人員（固定 TAG_USERS，每筆留言一律 mention，2026-09-04 使用者確認）

每筆留言主文下方，一律標註以下 4 人（帳號已用 `lookupJiraAccountId` 解析並鎖定，重複執行不再重查；若日後有人離職或改名，需重新查 accountId 更新下表，不要用顯示名稱重新猜測）：

| 顯示名稱 | accountId |
|---------|-----------|
| 許少宇 | `712020:76e333da-4a6b-46af-b4cf-20625280c3e4` |
| andyzeng | `712020:61ff7f88-9bb8-4a65-8921-92322a9ba9c8` |
| weihuang | `712020:4628ffd9-efa5-42ac-8620-806c1b306a1a` |
| Yenwen Chen 陳妍妏 | `712020:7c9fe298-14d9-4c4b-97ce-c545c1e401f4` |

**留言必須用 HTML 格式送出**（`addOrEditJiraIssueComment` 的 `contentFormat: "html"`），mention 才會渲染成可點擊、會通知對方的標註。**2026-09-04 版原先寫的 `contentFormat: "adf"` 是錯的**——2026-09-17 實測：這支工具的 `contentFormat` 參數 schema 只接受 `"markdown"` / `"html"` 兩種 enum 值，沒有 `"adf"`，照原文件寫法會直接被參數驗證擋掉。正確做法是呼叫 `getContentFormatGuide(toolName: "addOrEditJiraIssueComment")` 取得 HTML 節點對照表，mention 節點語法是 `<span data-type="mention" data-user-id="ACCOUNT_ID">@顯示名稱</span>`，`data-user-id` 就是 accountId（含 `712020:` 前綴原樣帶入）。純文字/markdown 格式下 `[~accountid:...]` 這類 wiki markup 語法在這個 MCP 工具上未經驗證，不要用。

HTML body 結構：主文一個 `<p>`，標註人員另起一個 `<p>`、每人一個 mention span：

```html
<p>{release_version} 已{動作詞}</p>
<p><span data-type="mention" data-user-id="712020:76e333da-4a6b-46af-b4cf-20625280c3e4">@許少宇</span> <span data-type="mention" data-user-id="712020:61ff7f88-9bb8-4a65-8921-92322a9ba9c8">@andyzeng</span> <span data-type="mention" data-user-id="712020:4628ffd9-efa5-42ac-8620-806c1b306a1a">@weihuang</span> <span data-type="mention" data-user-id="712020:7c9fe298-14d9-4c4b-97ce-c545c1e401f4">@Yenwen Chen 陳妍妏</span></p>
```

呼叫時 `commentBody` 直接傳入這段 HTML 字串（不需要 stringify、不是 JSON），並帶 `contentFormat: "html"`。上例第一個 `<p>` 的文字是 `luna` 模式範例（不含 APP_NAME）；`app-store` 模式主文文字換成「留言用詞判定」段落中 `app-store` 的模板，結構（標註人員 `<p>`）不變。**驗證方式**：送出後用 `listJiraIssueComments`（或 `getJiraIssue` 的 comments）讀回該筆留言，`responseContentFormat` 不指定時預設回 HTML——若讀回的內容仍是 `<span data-type="mention" ...>` 而非變成純文字 `@許少宇`，代表伺服器端真的存成 ADF mention node（2026-09-17 對 ERPD-12013 comment 114136 實測確認）。

## 使用方式

- `/jira-release-sync` — 掃描預設 1 週內
- `/jira-release-sync --weeks 3` 或「掃 3 週」— 指定週數（clamp 到 1~8）
- 使用者用天數描述（例如「兩週前」）時換算成最接近的整數週數

## 核心判定規則（已與使用者確認，勿自行更動邏輯）

1. **只掃 master/main 分支祖先歷史**：未合併進 master 的 commit 一律視為未上架，不列入候選。
2. **版本釋出日 = 該版本 merge 進 master 的日期**，不是版號 commit 自己的 committer date。「版本 merge commit」定義為 subject 符合 `Merge pull request #N from {org}/{X.Y.Z}`（分支名稱純粹是版本號本身）的 commit，release_version 取自分支名稱，release_date 取該 merge commit 自己的 committer date。
3. **「已上架」判定用 ancestry，不用日期比較**：一個 `[ISSUE-ID]` commit 若是某個版本 merge commit 的祖先（`git merge-base --is-ancestor`），即視為已上架；取「時間序上最早」符合此條件的版本 merge commit 為其釋出版本。**不可**改回單純比較 commit 日期早晚——commit 自己的 committer date 不等於它真正併入 master 的時間，會誤判上架版本（本 repo 實測案例：`[LVB-8340]` fix commit 的 committer date 是 2026-08-31T10:51，晚於 `update version to 1.50.33` 這個版號 commit 自己的 committer date 2026-08-28T11:32；但 LVB-8340 是透過 PR #1143 在 2026-08-31T17:47 併入 master，早於 1.50.33 真正 merge 進 master 的 PR #1144（2026-08-31T17:59），所以正確答案是有搭上 1.50.33。單純比較「commit 日期 vs 版號 commit 自己的日期」會誤判成沒搭上、掉到下一版 1.50.34；改用 ancestry 判斷 commit 是否為 1.50.33 那個 merge commit 的祖先，才會正確給出 1.50.33）。
4. **同一 issue 對應多個 commit**：取版本 merge 時間最晚的一筆（代表該 issue 最終完整修正被包進去的版本；例如同一 issue 先有一次修正搭上某版本，後又補一個 amendment commit、剛好卡在下一個版本 cut 之後，就以較晚版本為準）。
5. **結案日 = 該 issue 最終被包進去的那個版本 merge commit 的 committer date**（不是留言/執行當下的日期，也不是 Jira transition 自動蓋上的日期，見 STEP 06 的已知限制）。
6. **去重規則**：已是 Resolved（或 statusCategory=done）的 issue 直接跳過，不重複處理；尚未 Resolved 的則不管先前是否已留言過，一律照跑（留言不去重）。

## 核心判定規則（`luna` 模式，2026-09-04 與使用者確認，跟上面 `app-store` 規則不共用）

1. **只掃 `release` 分支**（不是 master/main）的祖先歷史；luna_web 的 master 是開發分支，跟 release 早已分岔（實測 2026-09-04：`master..release` 13 筆、`release..master` 24 筆），用 master 判斷會全錯。
2. **只收 author 是 Max_Ho 的 commit**（跟 App repo「不限作者」不同）。這個 repo 同一人有多種 git author 變體（`Max_Ho <max_ho@compal.com>`／`Max Ho <...@users.noreply.github.com>`／`Max Ho <maxho@ENG-Mac-Studio.local>` 等），比對用大小寫不敏感的 `max[_ ]?ho` pattern（腳本內建，不用手動維護 email 清單）。**`git log --author` 預設是 BRE，`[_ ]?` 的 `?` 不會被當成量詞解析、會比對不到任何 commit——必須加 `--extended-regexp`**（2026-09-04 實測踩過：沒加這個 flag 直接掃出 0 筆）。
3. **版本釋出點 = release 分支上精確格式的 git tag**，不是 merge commit subject 規則：`frontend-vYYYY.MM.DD` 或 `backend-vYYYY.MM.DD`（lightweight tag，tag 指到的 commit committer date 即釋出日）。排除 `-test`／`-2`／`-fix-107901`／`.1` 這類非正式 tag，也排除 `frontend-v20260605` 這種舊的無點分隔格式——只認結尾就是 `v\d{4}\.\d{2}\.\d{2}` 的精確格式。
4. **frontend 與 backend 分開部署，不同步上架**（實測 2026-08-19 只打 frontend tag、2026-08-20 只打 backend tag）：一個 commit 依改動檔案的頂層目錄（`frontend/` 或 `backend/`）判斷屬於哪個 component，比對 commit message 的 `(FE)`/`(BE)` 標籤更可靠——不是每筆 commit 都有標（例如 `[LVB-8296] fix pr issues` 這種 follow-up commit 常常沒標，但改動路徑仍能判斷出是 frontend）。再對該 component 自己的 tag 序列做 ancestry 判斷（同 `app-store` 規則 3 的 ancestry 原則，只是 tag 序列換成該 component 專屬的）。
5. **同一 Jira issue 若橫跨 frontend 與 backend 兩個 component**（同一筆 commit 同時動兩邊路徑，或分成兩筆 commit 各自只動一邊——後者是實際樣本裡真的會發生的型態），**兩邊都要各自找到自己 component 的 tag 才算「已上架」，日期取兩邊較晚者**；只要有一邊還沒 tag，整個 issue 這輪都先不當候選，改列進「尚未完全上架」給使用者看目前卡在哪個 component（不要在只有一半上架時就留言/轉 Resolved）。
6. **commit 改動路徑完全沒有落在 `frontend/` 或 `backend/` 底下** → 無法判定 component，列進「需人工確認」，不自動處理、不亂猜。
7. **去重規則**：跟 `app-store` 規則 6 相同——已 Resolved 的 issue 跳過，其餘不管留言過沒有一律照跑。

## 執行步驟

### STEP 00: 前置檢查

1. 確認 Atlassian MCP 連線可用（用最小查詢，例如 `getVisibleJiraProjects` 或 JQL 限 1 筆，失敗則停下並比照 `weekly-review` skill STEP 00 的處理方式提示使用者，不自動 degrade）。
2. 判定 `REPO_MODE`（見上方「Repo 模式判定」）：`app-store` 或 `luna`，判不出來直接問使用者。
3. `app-store` 模式才需要判定 `APP_NAME`（見 PROJECT-MAP 表，查不到就直接問使用者）；`luna` 模式不需要。
4. 解析週數參數 `WEEKS`，clamp 到 `[1, 8]`，預設 `1`。

### STEP 01: 掃描 commit 取得候選清單

**`app-store` 模式**執行：

```bash
python3 ~/.claude/skills/jira-release-sync/scan_commits.py --weeks {WEEKS}
```

回傳 JSON array，每筆含 `jira_id` / `release_version` / `release_date` / `commit_hash` / `commit_subject` / `commit_date`（判定邏輯已內建於腳本，不要用肉眼重新推導日期順序——見核心判定規則）。

**`luna` 模式**執行：

```bash
python3 ~/.claude/skills/jira-release-sync/scan_commits_luna.py --weeks {WEEKS}
```

腳本執行時會**自動先 `git fetch origin release:release`**（fast-forward only）才開始掃描，不需要另外手動 fetch；若本地 release 已 diverge（non-fast-forward）腳本會直接中止並印出原因，這時要人工排查、不能繞過（2026-09-17 實測踩過本地落後 origin 158 個 commit、漏掉一次 master merge，詳見「注意事項」段落）。

回傳 JSON **object**（跟 `app-store` 模式的 array 不同，不要用同一套解析邏輯套用）：

```json
{ "candidates": [...], "pending": [...], "manual_review": [...] }
```

- `candidates`：可執行候選，欄位含 `jira_id` / `release_version` / `release_date` / `components`（該 issue 橫跨的 component 陣列）/ `commit_hash` / `commit_subject` / `commit_date` / `commits_detail`（逐 commit 的 component + 對應 tag 明細）。
- `pending`：至少一個必要 component 還沒對應的 tag，本輪**不當作候選**，只在 STEP 04 呈現讓使用者知道卡在哪個 component（見核心判定規則 5）。
- `manual_review`：commit 改動路徑判斷不出屬於 frontend 還是 backend，需人工確認（見核心判定規則 6）。

不論哪個模式，可執行候選清單（`app-store` 的 array 或 `luna` 的 `candidates`）為空 → 直接回報「本期間內無已上架且待處理的 Jira issue」；`luna` 模式若 `pending`/`manual_review` 非空，仍要把這兩份原因一併回報，不要略過，結束 skill。

### STEP 02: 查詢每個候選 issue 的現況並去重

對每個 `jira_id` 呼叫：

```
getJiraIssue(cloudId, issueIdOrKey=jira_id, fields=["status", "summary", "resolution"])
```

- `status.statusCategory.key == "done"` → 移到「已跳過」清單，附上目前狀態，不再處理
- 否則 → 保留為待確認候選，記錄目前 `status.name` 與 `summary`

### STEP 03: 組裝候選清單（決定用詞、留言內容）

對每筆保留的候選：
- 依 Jira ID 前綴決定動作詞（修正/上線），未知前綴標註警告
- 留言內容：
  - `app-store` 模式 = `{APP_NAME} 版本 {release_version} 已{動作詞}`
  - `luna` 模式 = `{release_version} 已{動作詞}`（不含 APP_NAME）
- 結案日待寫入值 = `release_date`

### STEP 04: 輸出候選清單，等待使用者確認

格式：

```
## Jira 發版同步 — 候選清單（{起始日}~{今日}，共 N 筆）

| Issue | 目前狀態 | 動作 | 留言內容 | 結案日 |
|-------|---------|------|---------|--------|
| LVB-8340 | In Review | 修正 | 居服App 版本 1.50.33 已修正 | 2026-08-31 |

### 已跳過（已是 Resolved，不重複處理）
- LVB-8213（目前狀態：Resolved）

（若有未知前綴警告，逐筆列在候選清單下方）

（每筆留言結尾將一律標註：@許少宇 @andyzeng @weihuang @Yenwen Chen 陳妍妏）

請確認是否執行以上 N 筆的 Jira 留言 + 轉 Resolved？可回覆「確認」全部執行，或列出要排除的 issue 編號。
```

**以下兩段僅 `luna` 模式、且 STEP 01 有回傳非空內容時才輸出**（`app-store` 模式沒有這兩個概念，不要輸出空段落）：

```
### 尚未完全上架（等待另一個 component，本輪不處理）
| Issue | 已上架 component | 尚未上架 component | 卡住的 commit |
|-------|------------------|---------------------|----------------|
| LVB-8369 | （無） | frontend | [LVB-8369] fix(FE): ... |

### 需人工確認 component 歸屬（改動路徑判斷不出 frontend/backend）
| Issue | Commit |
|-------|--------|
```

**在使用者明確確認前，不得呼叫任何寫入類 Jira 工具**（`addOrEditJiraIssueComment` / `transitionJiraIssue` / `editJiraIssue`）。這是外部系統、對全team可見的動作，比照系統規範需先預覽。

### STEP 05: 執行寫入（使用者確認後，逐筆處理）

對每筆確認要處理的候選，依序：

1. **留言**：組裝 HTML body（主文 + 固定標註人員，見上方「留言標註人員」章節），呼叫 `addOrEditJiraIssueComment(cloudId, issueIdOrKey, commentBody=<HTML 字串>, contentFormat="html")`
2. **找 Resolved 轉換**：`executeRead(name="listJiraIssueTransitions", cloudId, inputs={issueIdOrKey})`（`cloudId` 是 `executeRead` 的頂層參數，不要塞進 `inputs`），在回傳的 `transitions` 中找 `name` 完全等於或包含 `"Resolved"`（或中文「已解決」）者，取其 `id`
   - 找不到 → 記錄失敗「目前狀態無可直接轉換至 Resolved 的路徑，可用轉換：{列出所有 name}，需人工處理」，跳過此筆剩餘步驟
3. **執行轉換**：`transitionJiraIssue(cloudId, issueIdOrKey, transitionId="<上一步取得的 id>", fields={"resolutiondate": "{release_date}T00:00:00.000+0800"})`
   - 若該 transition screen 不接受 `resolutiondate` 欄位而報錯，改用不帶 `fields` 的方式重試一次（純轉換）（2026-09-17 對 ERPD-12013/12014/12090 實測：transition `hasScreen: false`，帶 `resolutiondate` 必然 400，一律會走到這一步的 retry）
4. **回填結案日（best-effort，僅在 STEP 05.3 未成功帶入時才需要）**，依序嘗試兩層：
   a. **系統欄位**：`editJiraIssue(cloudId, issueIdOrKey, fields={"resolutiondate": "{release_date}T00:00:00.000+0800"})`
      - 多數 Jira 專案會失敗，錯誤是 `Field 'resolutiondate' cannot be set. It is not on the appropriate screen, or unknown.`（系統欄位唯讀，轉態當下自動蓋今天日期）→ 進 b
   b. **專案自訂「結案日」欄位（2026-09-03 實測發現，非所有專案都有）**：原設計是 a 失敗時從錯誤回應的 `problems[0].settableFields` 動態找欄位 ID；**2026-09-17 實測發現這層 MCP 包裝的錯誤格式只有 `{error, message}`，不會帶 `problems[0].settableFields`**（不是 Jira REST 原始錯誤格式，這支工具吞掉了那個欄位），所以這個自動探測管道目前對這支工具不可行。退回人工判斷：已知 LVB 專案有「結案日」自訂欄位（`customfield_10502`，只在 LVB 驗證過）、ERPD 專案沒有（2026-09-03 起多次實測一致）；遇到不在這兩個已知專案清單內的專案，如果需要精確結案日，才值得另外呼叫 `getJiraIssueTypeMetaWithFields` 或問使用者，不要假設一定能自動探測到：
      - 找到 → `editJiraIssue(cloudId, issueIdOrKey, fields={"<那個 id>": "{release_date}"})`，**純日期字串 `YYYY-MM-DD`，不要用 datetime ISO 格式**（此自訂欄位是 date 型別不是 datetime，實測帶完整 ISO 字串格式不符會被拒）
        - 成功 → 這筆視為完全成功
        - 失敗 → 記錄實際錯誤，標記部分成功
      - 沒找到（清單裡沒有 `name === "結案日"`，例如 ERPD 專案）→ 記錄「結案日欄位維持系統轉態當下日期，無法回填為 {release_date}；正確版本與日期已寫入留言內文」，不視為整體失敗
   - **`customfield_10502` 這個 ID 只在 LVB 專案驗證過，不可寫死當全域常數**——不同 Jira 專案就算都有「結案日」欄位，custom field 的編號也可能不同，每次都要照 a 失敗後的 `settableFields` 動態找，不要跳過 a 直接猜 ID。

**不寫入 Fix Version 欄位（2026-09-03 使用者確認）**：使用者帳號沒有在 Jira 專案新增 Version 的權限，`release_version` 若尚未存在於該專案的 Version 清單，寫入一定失敗；就算已存在，這裡也刻意不去動這個欄位。版本資訊已完整包含在留言文字內，足夠追溯，Fix Version 由使用者自行視情況手動處理。

**已知限制（照實記錄在結果，不要隱藏）**：
- Jira `resolutiondate` 系統欄位在多數專案是唯讀的，只能在「轉為 Resolved 的當下」由 Jira 自動填今天日期，本 skill 會嘗試回填但**不保證成功**——這是 Jira API 本身的限制，不是 bug。
- 「結案日」自訂欄位是否存在、欄位 ID 為何，因專案而異（2026-09-03 實測：LVB 專案有、ERPD 專案沒有）。沒有這個自訂欄位時，結案日只能停在留言文字裡，Jira 系統欄位本身回填不進去。

### STEP 06: 輸出最終結果

```
## Jira 發版同步結果（{起始日}~{今日}）

### ✅ 成功（留言 + 轉 Resolved + 結案日皆完成）
| Issue | 版本 | 結案日 | 留言內容 |
|-------|------|--------|---------|

### ⚠️ 部分成功（留言/轉態成功，但結案日需人工確認）
| Issue | 已完成 | 待人工處理 |
|-------|--------|-----------|

### ❌ 失敗
| Issue | 原因 |
|-------|------|

### 已跳過（已是 Resolved）
| Issue | 目前狀態 |
|-------|---------|
```

## 注意事項

### `app-store` 模式

- 掃描範圍是**整個 repo 的所有 commit**（不限特定作者），因為目的是同步「這個 App 版本上架了什麼」而非個人工作記錄。
- `scan_commits.py` 用 `git merge-base --is-ancestor` 判斷「已上架」，已用本 repo 實際歷史驗證過一個真實邊界案例：LVB-8340 的 fix commit 自己的 committer date（2026-08-31T10:51）晚於 `update version to 1.50.33` 版號 commit 自己的日期（2026-08-28T11:32），若單純比日期會誤判成沒搭上 1.50.33、掉到 1.50.34；但它實際透過 PR #1143 在 1.50.33 真正 merge 進 master（PR #1144，2026-08-31T17:59）之前就先併入，ancestry 判斷正確給出 1.50.33。**這是本 skill 從日期比較改成 ancestry 判斷的直接原因，不要再改回日期比較。**
- 版本判定只認「分支名稱純粹是版本號」的 merge commit（`Merge pull request #N from {org}/{X.Y.Z}`）；`LVB-8340/fix/...`、`chore/...` 這類 feature branch 的 merge commit 不會被誤認成版本釋出點。
- `is_ancestor` 檢查以「每個候選 commit × 每個版本 merge，依時間序找第一個命中」提前 return，一般不會有效能問題；候選數與版本數都不多（單月頂多十幾筆）時可忽略。

### `luna` 模式

- `scan_commits_luna.py` 掃描範圍**限定 author 是 Max_Ho**，跟 `app-store` 模式（不限作者）完全相反——因為 luna_web 是多人協作 repo，目的是同步「我自己」的哪些修改上架了，不是整個系統的發版紀錄。
- `git log --author` 預設吃 BRE（basic regex），`max[_ ]?ho` 這種帶 `?` 量詞的 pattern 在 BRE 下 `?` 不會被解析成量詞、直接掃出 0 筆；腳本已加 `--extended-regexp` 修正，**這是 2026-09-04 實測踩過的坑，之後改這支腳本的 author 比對邏輯不要拿掉這個 flag**。
- 版本判定不是靠 merge commit subject 規則，是直接讀 release 分支上 `frontend-vYYYY.MM.DD` / `backend-vYYYY.MM.DD` 精確格式的 git tag；`load_component_releases()` 只認結尾就是 `v\d{4}\.\d{2}\.\d{2}` 的 tag 名稱，`-test`／`-2`／`.1` 這類尾綴或舊的無點格式（`frontend-v20260605`）一律排除，且會驗證 tag 指到的 commit 確實是 `release` 分支的祖先才採用（避免拿到打在其他分支或已失效的 tag）。
- frontend／backend 分開上架、同一 Jira issue 橫跨兩者時「兩邊都上架才算完成、取較晚日期」這條規則，已用手動建立的合成 repo 驗證過三種情境（單一 commit 同時動兩邊路徑／同一 issue 拆兩筆 commit 各自只動一邊／commit 還沒被任何 tag 收進去），行為符合預期——2026-09-04 因為近 8 週真實樣本剛好沒出現橫跨兩個 component 的 issue，才特地補這個合成測試，不是憑空信任邏輯正確。
- `pending` 與 `manual_review` 是刻意設計成「看得到卡在哪裡」而不是靜默丟掉：component 判定不出來的 commit 不會被排除在輸出之外，而是進 `manual_review` 附上原因；只上架一半的 issue 也不會被誤判成已完成，而是進 `pending` 附上已上架/尚未上架的明細。
- **腳本每次執行都會先 `git fetch origin release:release`（fast-forward only），不會直接信任本地 release 分支**——2026-09-04 加入前，2026-09-17 實測踩過真坑：本地 release 落後 origin 158 個 commit，其中一次 `Merge pull request #11124 from compal-swhq/master`（master 併入 release）只有 fetch 後才看得到，導致當時整輪掃描漏掉 ERPD-12090 等已 merge 進 release 但用舊分支資料完全查不到蹤影的 issue（不是進 `pending`，是整個不出現在任何清單，因為 `git log release --author=...` 本身就讀不到那幾筆 commit）。fetch 只接受 fast-forward；本地有 origin 沒有的 commit 視為 diverge，腳本會直接中止讓人工排查，不靜默覆蓋本地分支。

### 共用

- 若使用者要求的週數超過 8，clamp 到 8 並告知使用者（不要靜默執行超出範圍的掃描）。
- STEP 05 每筆之間互相獨立，單筆失敗不影響其他筆繼續執行；全部跑完才輸出 STEP 06 總表。
