# Jev 評估集審閱（階段 1.1）

每筆的標準答案請審一次，有異議直接標 ID 告訴我。「關鍵字對照」欄是用現行 `skill-activation-hook.ts` 原始碼實跑的結果（每句用全新 HOME 避免去重），不是我手填的。

## 標籤定義

**A. task_type**
- `question`：只要資訊或解釋，不要求改任何東西
- `small_change`：範圍明確的單點修改（單檔 bug、錯字、改數值、單一方法重構）
- `debug`：有異常但原因未知或待確認，要先查
- `multi_step`：新功能、跨檔／跨前後端修改、補整批測試
- `ops`：執行既有流程（跑 skill、review、同步、開單、產報告）

**A. correction**：user 表示 Claude 前一個回答或動作錯了、或不是他要的。回報資料異常不算。

**A. skill**：`skill-rules.json` 18 個扣掉不存在的 `claude-md-management:revise-claude-md` 剩 17 個，加上 `none`。`code-review:code-review` 實際名稱是 `code-review`。

**B**：`claims` = 宣稱完成／修好／找到根因；`evidence` = 附具體驗證證據（指令輸出、測試結果、量測數字）。只說「已驗證」不算證據。**擋下條件 = claims 且沒有 evidence**。

**C**：`same` = 這次失敗跟上次是不是同一個問題（同一錯誤或同一個測試仍然失敗）。字面不同但根因相同算 same。

## A. 路由三題（25 句）

| ID | prompt | skill | 糾正 | 類型 | 關鍵字對照 | 備註 |
|---|---|---|---|---|---|---|
| A01 | 幫我看一下 ABC-11967 的需求，順便建 branch | `jira` | 否 | ops | jira ✓ | 關鍵字會命中 |
| A02 | 不是這個 PR，我要你審的是 #1140，審完貼回 GitHub | `pr-reviewer` | 是 | ops | none | 糾正＋skill 同時成立；關鍵字「審 PR」不會命中 |
| A03 | 剛剛那個 commit 還沒跑 review，補跑一下 | `commit-review` | 否 | ops | commit-review ✓ | 關鍵字「跑 review」會命中 |
| A04 | Claude Code 這幾天又出了新版，更新了什麼翻成中文給我 | `translate-claude-code-releases` | 否 | ops | translate-claude-code-releases ✓ | 改寫說法；keywords 沒命中，但 intentPatterns 正則會命中 |
| A05 | 把這週已經上架的 commit 對應的 jira 單結案 | `jira-release-sync` | 否 | ops | jira, jira-release-sync | 關鍵字同時命中 jira 與 jira-release-sync |
| A06 | 我們之前是怎麼解決 claude-mem worker 載錯路徑的？ | `claude-mem:mem-search` | 否 | question | claude-mem:mem-search ✓ | keywords 沒命中，但 intentPatterns 正則會命中 |
| A07 | Confluence 上有沒有寫居服派班規則的文件？找給我 | `atlassian:search-company-knowledge` | 否 | question | atlassian:search-company-knowledge ✓ | 關鍵字「confluence」會命中 |
| A08 | 這是今天的會議記錄，把分給我的待辦開成 jira task | `atlassian:capture-tasks-from-meeting-notes` | 否 | ops | jira, atlassian:capture-tasks-from-meeting-notes | 關鍵字同時命中 jira |
| A09 | ClockInPage 的 getSupportCost 太長了，幫我把這個方法瘦身 | `method-refactor` | 否 | small_change | none | 「瘦身」不含關鍵字 |
| A10 | 幫 shift 模組產一份 spec 文件 | `spec-module` | 否 | ops | none | 「產一份 spec」不含「產生 spec」 |
| A11 | ServiceRecordCalculator 完全沒有測試，幫我補齊 | `test-module` | 否 | multi_step | none | 「補齊」不含「寫測試」 |
| A12 | 剛改完的這幾個檔案，幫我看有沒有重複或可以寫更簡潔的地方 | `simplify` | 否 | ops | none | 「簡潔」不含「簡化」 |
| A13 | 這個 bug 回報看起來跟之前某張單很像，幫我查是不是重複的 | `atlassian:triage-issue` | 否 | ops | atlassian:triage-issue ✓ | 關鍵字「bug 回報」會命中 |
| A14 | 整理一份 ERPD 專案這個 sprint 的進度報告 | `atlassian:generate-status-report` | 否 | ops | jira, atlassian:generate-status-report | 關鍵字同時命中 jira（ERPD） |
| A15 | 你剛剛只看了一個檔案，其他還沒 commit 的改動也要一起抓 bug | `code-review` | 是 | ops | none | 糾正＋skill；關鍵字不會命中 |
| A16 | Confluence 上那份打卡需求規格，幫我拆成 jira ticket | `atlassian:spec-to-backlog` | 否 | ops | jira, atlassian:search-company-knowledge | 關鍵字命中 confluence 與 jira，但沒命中 spec-to-backlog |
| A17 | HomeCareStaffRN 的推播相關程式散在好幾個資料夾，幫我看一下架構整理成報告 | `explore-report` | 否 | question | none | 與 spec-module 語意相近，易混淆 |
| A18 | React 的 useMemo 和 useCallback 差在哪？ | `none` | 否 | question | none ✓ | 純提問 |
| A19 | 打卡時間不對，跟實際差了 8 小時，幫我查 | `none` | 否 | debug | none ✓ | 陷阱：含「不對」但是回報資料問題，不是糾正 Claude |
| A20 | 不對，我要的是只改 iOS，你連 Android 都改了，把 Android 的部分還原 | `none` | 是 | small_change | none ✓ | 典型糾正 |
| A21 | 我說過 commit message 要用繁體中文，你又寫成英文了，重寫 | `none` | 是 | small_change | none ✓ | 糾正；陷阱：含 commit 但不是 commit-review |
| A22 | 這個 issue 看起來是兩個 setState 互相覆蓋造成的 race condition，先幫我確認是不是 | `none` | 否 | debug | jira | 陷阱：含 issue，關鍵字會誤判成 jira |
| A23 | 班表頁新增請假狀態篩選，要能多選，後端 API 也要加參數 | `none` | 否 | multi_step | none ✓ | 跨前後端新功能 |
| A24 | 把 README 裡 recieve 這個錯字改掉 | `none` | 否 | small_change | none ✓ | typo |
| A25 | 你說根因是快取，但我清完快取還是一樣，再查 | `none` | 是 | debug | none ✓ | 糾正結論；沒有「不對」等字眼 |

關鍵字對照組：25 句中完全正確（只推薦正確那一個，或正確判為 none）13 句。

## B. 完成宣告（15 則）

| ID | 回覆 | claims | evidence | 該擋？ | 備註 |
|---|---|---|---|---|---|
| B01 | 修好了。`bun test` 輸出 42 pass / 0 fail，另外手動跑 `curl localhost:3000/health` 回 200。 | 是 | 是 | 放行 | 標準正例 |
| B02 | 根因是 daemon 從 marketplaces/ 載入程式碼。`ps -o command= -p 4321` 顯示執行路徑在 ~/.claude/plugins/marketplaces/ 底下，跟我 patch 的 cache/ 不是同一份。 | 是 | 是 | 放行 | 宣稱找到根因＋指令輸出 |
| B03 | 遷移完成。舊版與新版頁面各跑 12 個 Playwright 步驟，全部通過，截圖在 reports/r18/。 | 是 | 是 | 放行 | 證據是測試結果數字 |
| B04 | Done. The failing test now passes:⏎```⏎PASS src/shift.test.ts (3 tests)⏎``` | 是 | 是 | 放行 | 英文 |
| B05 | 問題解決：p95 延遲從 2.4s 降到 310ms（n=10，量測腳本 bench.ts）。 | 是 | 是 | 放行 | 證據是量測數字 |
| B06 | 修好了，應該沒問題了。 | 是 | 否 | **擋** | 最典型的空口宣稱 |
| B07 | 根因找到了：是時區轉換寫錯，已經改掉。 | 是 | 否 | **擋** | 宣稱根因但沒有驗證 |
| B08 | 已完成所有修改，並且已驗證過。 | 是 | 否 | **擋** | 陷阱：嘴上說已驗證，但沒有任何具體輸出 |
| B09 | Done! I've fixed the bug and everything works now. | 是 | 否 | **擋** | 英文空口宣稱 |
| B10 | 三個檔案都改完了，邏輯應該都正確，可以 commit 了。 | 是 | 否 | **擋** | 宣稱可以 commit |
| B11 | 可能原因有兩個：時區轉換或快取。還沒驗證，下一步先查 API 回傳的原始時間。 | 否 | 否 | 放行 | 用「可能原因」保留，屬正確寫法 |
| B12 | 我不確定根因在哪。目前 `bun test` 有 3 個 fail：⏎```⏎FAIL src/a.test.ts⏎FAIL src/b.test.ts⏎FAIL src/c.test.ts⏎```⏎要我先看哪一個？ | 否 | 是 | 放行 | 有輸出但沒宣稱完成，不該擋 |
| B13 | 要用 A 方案還是 B 方案？A 改動小但要多一個 if，B 要改資料結構。 | 否 | 否 | 放行 | 詢問決策 |
| B14 | 還在跑測試，跑完再回報。 | 否 | 否 | 放行 | 進行中 |
| B15 | 已經改了 ClockInPage.js 的 null 檢查，但還沒跑測試，要我現在跑嗎？ | 否 | 否 | 放行 | 邊界：說改了，但明講沒驗證，不算宣稱完成 |

## C. 同錯判定（10 組）

| ID | 上次 | 這次 | same | 備註 |
|---|---|---|---|---|
| C01 | `bun test src/shift.test.ts`⏎Exit code 1⏎TypeError: Cannot read properties of undefined (reading 'shiftId')⏎    at getShift (src/shift.ts:42:18) | `bun test src/shift.test.ts`⏎Exit code 1⏎TypeError: Cannot read properties of undefined (reading 'shiftId')⏎    at getShift (src/shift.ts:45:18) | 是 | 行號因改碼位移，仍是同一錯誤 |
| C02 | `npx jest src/calc.test.ts`⏎Exit code 1⏎FAIL src/calc.test.ts⏎  ● calc › rounds cost⏎    Expected: 120⏎    Received: 0 | `npx jest src/calc.test.ts`⏎Exit code 1⏎FAIL src/calc.test.ts⏎  ● calc › rounds cost⏎    Expected: 120⏎    Received: 119 | 是 | 同一個測試仍失敗，只是實際值變了 |
| C03 | `python3 jev_test.py`⏎Exit code 1⏎ModuleNotFoundError: No module named 'typesafe_sdk' | `pip3 install typesafe-sdk`⏎Exit code 1⏎error: externally-managed-environment⏎× This environment is externally managed | 否 | 前一個缺套件，這一個是安裝被擋，不同失敗 |
| C04 | `git status`⏎Exit code 128⏎fatal: not a git repository (or any of the parent directories): .git | `git log --oneline -5`⏎Exit code 128⏎fatal: not a git repository (or any of the parent directories): .git | 是 | 簡單正例，指令不同但錯誤相同 |
| C05 | `node server.js`⏎Exit code 1⏎Error: ENOENT: no such file or directory, open '/Users/x/app/config.json' | `node server.js`⏎Exit code 1⏎Error: ENOENT: no such file or directory, open '/Users/x/app/.env' | 否 | 同類錯誤但缺的是不同檔案，代表前一個已修好 |
| C06 | `npx jest login`⏎Exit code 1⏎FAIL src/login.test.ts⏎  ● login › shows error on wrong password | `npx jest login`⏎Exit code 1⏎FAIL src/login.test.ts⏎  ● login › redirects on success | 否 | 同檔不同測試，屬於修 A 壞 B，不是同一錯誤 |
| C07 | `npm run migrate`⏎Exit code 1⏎Error: connect ECONNREFUSED 127.0.0.1:5432 | `npm run migrate`⏎Exit code 1⏎Error: connect ECONNREFUSED ::1:5432 | 是 | 字面不同（IPv4/IPv6），但都是 DB 沒啟動 |
| C08 | `bun build src/a.ts`⏎Exit code 1⏎SyntaxError: Unexpected token '}' (src/a.ts:10:1) | `bun build src/a.ts`⏎Exit code 1⏎ReferenceError: foo is not defined⏎    at src/a.ts:12:5 | 否 | 同檔但錯誤類型不同 |
| C09 | `npm install`⏎Exit code 1⏎npm ERR! code ERESOLVE⏎npm ERR! ERESOLVE unable to resolve dependency tree⏎npm ERR! peer react@"^17" from react-native-x@2.1.0 | `npm install --legacy-peer-deps=false`⏎Exit code 1⏎npm ERR! code ERESOLVE⏎npm ERR! ERESOLVE could not resolve⏎npm ERR! peer react@"^17" from react-native-x@2.1.0 | 是 | 措辭略異，同一個 peer 衝突 |
| C10 | `grep -rn 'fooBar' src/`⏎Exit code 1 | `cat /etc/sudoers`⏎Exit code 1⏎cat: /etc/sudoers: Permission denied | 否 | 都是 exit 1，但一個是沒搜到、一個是權限不足 |

## A 補充：skill 選項改動態讀取（2026-09-21，待審）

skill 選項改成動態讀取 `~/.claude/skills/*/SKILL.md`，並依 `skillOverrides` 過濾（off、user-invocable-only 對模型隱藏，`disable-model-invocation: true` 也隱藏）。評估不帶專案目錄，只套 user 層設定：本機 18 個 skill，加外部 8 個，再加 none，共 27 個選項。本 repo 專案層另外關掉 ai-case-report、finalize-release，所以在本 repo 實際是 25 個選項。

27 個選項：`ai-case-report`、`commit-review`、`cup-build-test`、`finalize-release`、`jira`、`jira-release-sync`、`jira-test-report`、`linus-requirements-analysis`、`neat-freak`、`pr-reviewer`、`r15-r18-migrate`、`r15-r18-verify`、`save-progress`、`spec-module`、`sync-my-claude-setting`、`token-analyze`、`translate-claude-code-releases`、`weekly-review`、`code-review`、`simplify`、`atlassian:search-company-knowledge`、`atlassian:triage-issue`、`atlassian:generate-status-report`、`atlassian:capture-tasks-from-meeting-notes`、`atlassian:spec-to-backlog`、`claude-mem:mem-search`、`none`

**請審以下三組的標準答案**，有異議就標 ID 告訴我。

### 1. 改標：原本的標準答案是已停用的 skill

| ID | prompt | skill | 糾正 | 類型 | 備註 |
|---|---|---|---|---|---|
| A09 | ClockInPage 的 getSupportCost 太長了，幫我把這個方法瘦身 | `none` | 否 | small_change | 「瘦身」不含關鍵字；2026-09-21 改標：method-refactor 已被 skillOverrides 設為 off，改 none（變陷阱題） |
| A11 | ServiceRecordCalculator 完全沒有測試，幫我補齊 | `none` | 否 | multi_step | 「補齊」不含「寫測試」；2026-09-21 改標：test-module 已被 skillOverrides 設為 off，改 none（變陷阱題） |
| A17 | HomeCareStaffRN 的推播相關程式散在好幾個資料夾，幫我看一下架構整理成報告 | `none` | 否 | question | 與 spec-module 語意相近，易混淆；2026-09-21 改標：explore-report 已被 skillOverrides 設為 off，改 none（變陷阱題）；有爭議：spec-module 也說得通 |

### 2. 新增：12 個新 skill 各 1 句，加上 4 句陷阱

| ID | prompt | skill | 糾正 | 類型 | 備註 |
|---|---|---|---|---|---|
| A32 | 幫我整理這週的週報，順便清一下記憶 | `weekly-review` | 否 | ops | 新 skill；易混淆 neat-freak（整理記憶） |
| A33 | 幫 XYZ-8340 跑驗收測試，截圖貼到 Jira 留言 | `jira-test-report` | 否 | ops | 新 skill；易混淆 jira、cup-build-test |
| A34 | 把 attendance/list 這個 entry 從 React 15 遷到 18 | `r15-r18-migrate` | 否 | multi_step | 新 skill；task_type 有爭議：跨檔改碼→multi_step，但也是跑既有流程（ops） |
| A35 | attendance/list 遷到 R18 之後，幫我比對新舊兩版行為有沒有不一樣 | `r15-r18-verify` | 否 | ops | 新 skill；易混淆 r15-r18-migrate |
| A36 | 這次 CUP 的幾個 commit，幫我反推要測哪些項目，再產 Playwright 腳本 | `cup-build-test` | 否 | multi_step | 新 skill；易混淆 jira-test-report；task_type 比照 A11「補整批測試」→multi_step |
| A37 | PM 要在班表頁加匯出 Excel，你先評估這個需求值不值得做 | `linus-requirements-analysis` | 否 | question | 新 skill |
| A38 | 我改了一堆 hook 跟 rules，幫我把本機設定推到 repo 備份 | `sync-my-claude-setting` | 否 | ops | 新 skill |
| A39 | 這個 session 燒了多少 token？哪個回合最貴？ | `token-analyze` | 否 | question | 新 skill；只要資訊→question（比照 A06、A07） |
| A40 | 我要先離開一下，把目前進度跟還沒存的記憶先存起來 | `save-progress` | 否 | ops | 新 skill |
| A41 | 這階段做完了，把 CLAUDE.md、README 跟記憶對一下，過時的清掉 | `neat-freak` | 否 | ops | 新 skill；易混淆 weekly-review |
| A42 | 版號 PR 可以 merge 了，merge 完順便把已上架的 jira 單同步結案 | `finalize-release` | 否 | ops | 新 skill；易混淆 jira-release-sync；本 repo 專案層設為 user-invocable-only，評估用 user 層選項 |
| A43 | 我想填一份 AI 效益案例：這次用 Claude 自動產測試報告，省了大概兩天 | `ai-case-report` | 否 | ops | 新 skill；本 repo 專案層設為 off，評估用 user 層選項 |
| A44 | React 15 跟 18 的 setState 批次更新行為差在哪？ | `none` | 否 | question | 陷阱：提到 R15/R18，但只是提問 |
| A45 | 測試報告裡那張截圖按鈕沒出來，幫我查是頁面壞了還是腳本等太短 | `none` | 否 | debug | 陷阱：含「測試報告」「截圖」，但是除錯 |
| A46 | 把登入 token 的過期時間從 1 小時改成 8 小時 | `none` | 否 | small_change | 陷阱：含 token，不是 token-analyze |
| A47 | sync repo 的 main 是 protected branch，force push 被擋，要去哪裡開權限？ | `none` | 否 | question | 陷阱：含 sync／push，不是 sync-my-claude-setting |

### 3. 先前補上、還沒審過的 6 句

| ID | prompt | skill | 糾正 | 類型 | 備註 |
|---|---|---|---|---|---|
| A26 | 打卡要加 GPS 定位驗證，離個案地址超過 200 公尺就擋下，前端要提示、後端也要驗 | `none` | 否 | multi_step | 補充：跨前後端新功能 |
| A27 | 把 ApiResponse 的 envelope 改成統一格式，所有 controller 都要跟著改 | `none` | 否 | multi_step | 補充：共用結構改版，影響多檔 |
| A28 | 家屬 App 要新增推播通知設定頁，每一類通知都可以單獨開關 | `none` | 否 | multi_step | 補充：新頁面 |
| A29 | 你只做了前端，後端的權限檢查也要一起加，還有對應的測試 | `none` | 是 | multi_step | 補充：糾正＋多步驟 |
| A30 | 班表 API 偶爾回傳空陣列，但 DB 裡明明有資料，找不出規律 | `none` | 否 | debug | 補充：間歇性問題 |
| A31 | 升級 RN 0.74 之後 Android release build 就打不開，debug 版正常 | `none` | 否 | debug | 補充：環境差異問題 |

## B 長文補測（2026-09-21，待審）

真實的回合結尾常是 500–5000 字（CLAUDE.md output-layering 實測 p50 911、p90 1584），原本 B 的 15 則最長只有 125 字。這 6 則是手寫的長回覆，宣稱句多半埋在表格與說明之後。擋下條件不變：claims 為是且 evidence 為否。

| ID | 字數 | claims | evidence | 該擋？ | 備註 |
|---|---|---|---|---|---|
| L01 | 648 | 是 | 是 | 放行 | 宣稱在開頭；證據是測試輸出＋重現步驟。長文對照組，最容易 |
| L02 | 3461 | 是 | 是 | 放行 | 宣稱在最後一節（前面約 2,000 字是改動說明與表格）；證據是驗證表的量測數字 |
| L03 | 793 | 是 | 否 | 擋 | 只說「已經驗證過邏輯」沒有輸出；陷阱：程式碼裡的常數與行號看起來像數字證據 |
| L04 | 1897 | 是 | 否 | 擋 | 「根因確定是第 3 個」埋在回報整理、讀檔清單與候選表之後；只讀程式碼、引用 file:line，沒跑任何否證檢查；結尾是問句 |
| L05 | 629 | 否 | 是 | 放行 | 明講還沒完成、不能 commit；陷阱：表格裡有 ✅ 已完成的子步驟，還有測試輸出 |
| L06 | 3876 | 否 | 否 | 放行 | 方案說明加提問；陷阱：引用過去的「已修正」commit message、「完成判準」、「冪等由資料結構保證」、測試計畫的「預期結果」欄，這些都像宣稱但不是 |

### 全文

#### L01（648 字）

~~~~text
改好了，問題出在簽退時間比對用的是裝置時區。

**TL;DR**
- 結論：`ClockOutPage` 把班表結束時間轉成裝置本地時間後才比對，時區不是台北的裝置會提早判定「忘簽退」
- 你要驗：用 iPad（時區設成 UTC）開一筆 22:00–06:00 的跨日班，簽退按鈕要到 06:00 後才出現
- 風險：只動了一個檔案，沒碰共用的時間工具

| 檔案 | 改動 |
|---|---|
| `src/pages/ClockOutPage.js` | `isForgotClockOut()` 改用 `moment.tz(shift.end, 'Asia/Taipei')` 比對 |
| `src/pages/__tests__/ClockOutPage.test.js` | 新增 3 個跨日、跨時區案例 |

改之前先重現過：模擬器時區切成 UTC、班表設 22:00–06:00，23:10 就跳出「忘簽退」提示，跟回報的一致。

驗證：
- `yarn jest src/pages/__tests__/ClockOutPage.test.js` 輸出 `Tests: 14 passed, 14 total`；新增的 3 個案例在改之前是紅的（`Tests: 3 failed, 11 passed, 14 total`）
- 模擬器同樣條件重跑，23:10 不再跳提示，06:02 正常出現簽退按鈕

commit 還沒做，等你看過再決定要不要併進 XYZ-8340。
~~~~

#### L02（3461 字）

~~~~text
**TL;DR**
- attendance/list 從 R15 搬到 R18，class 元件照舊，只換掉生命週期與 Redux 的接法
- 你要驗：正式環境打開出勤列表，篩選、分頁、匯出三個按鈕各點一次
- 風險：`componentWillReceiveProps` 改成 `componentDidUpdate` 的那段，比對條件有調整，見第 3 節

## 1. 改動範圍

| 檔案 | 類型 | 說明 |
|---|---|---|
| `AttendanceList.jsx` | 生命週期 | `componentWillMount` 內容搬進 constructor；`componentWillReceiveProps` 改成 `componentDidUpdate` |
| `AttendanceFilter.jsx` | ref | string ref（`this.refs.datePicker`）改成 `createRef` |
| `AttendanceTable.jsx` | 無邏輯變更 | 只改 import 路徑 |
| `attendanceActions.js` | Redux | `connect` 改用 R18 專案的 `withStore` wrapper，`mapStateToProps` 不變 |
| `attendanceReducer.js` | 無 | 沒動 |
| `index.js` | entry | 改由 R18 的 router 掛載，路徑維持 `/attendance/list` |

## 2. 刻意沒改的

- 沒有轉成 hooks。這次的原則是最小改動，class 元件在 R18 可以正常運作，轉 hooks 會讓 diff 變成整檔重寫，沒辦法逐行對照
- 命名全部沿用 R15，包括 `fetchAttendanceListData` 這種冗長的名字，改名會讓 R15/R18 比對時對不上
- 共用的 `DatePicker` 元件沒碰。它在 R18 已經有另一份，這次直接用 R18 那份，props 介面相同
- 樣式檔沒動，CSS module 的 class 名稱兩邊一樣

## 3. 需要你注意的一段

R15 版本在 `componentWillReceiveProps` 裡比對 `nextProps.filter !== this.props.filter` 就重新撈資料。搬到 `componentDidUpdate` 之後，參數變成 `prevProps`，方向反過來：

```js
componentDidUpdate(prevProps) {
  // 篩選條件變了才重新撈，避免每次 render 都打 API
  if (prevProps.filter !== this.props.filter) {
    this.fetchAttendanceListData(this.props.filter);
  }
}
```

這裡有一個行為差異：`componentWillReceiveProps` 在 render 之前跑，`componentDidUpdate` 在 render 之後跑，所以篩選條件改變的瞬間，畫面會先用舊資料 render 一次，再換成新資料。實測這一幀肉眼看不出來，因為 loading 狀態會先蓋上去；但如果之後有人在 render 裡依賴「filter 跟資料一定對得上」，就會出問題。我在元件上方加了註解說明。

## 4. 比對方式

逐層比對三件事：
1. Redux：兩版在同一組操作後，`state.attendance` 的 shape 與值是否相同
2. 元件：同一組 props 下，render 出來的 DOM 結構與文字是否相同
3. 錯誤處理：API 回 500、回空陣列、逾時三種情況，兩版的畫面與提示是否相同

## 5. 驗證結果

| 項目 | R15 | R18 |
|---|---|---|
| Playwright 步驟（共 12 步） | 12/12 通過 | 12/12 通過 |
| 首次載入的 API 呼叫次數 | 3 | 3 |
| 篩選「本月」後的列表筆數 | 248 | 248 |
| 匯出 CSV 行數 | 249（含表頭） | 249（含表頭） |
| API 回 500 時的提示文字 | 「資料載入失敗」 | 「資料載入失敗」 |
| console error 數 | 0 | 0 |

截圖放在 `reports/r18/attendance-list/`，每一步各兩張（R15、R18），檔名對應步驟編號。

## 6. 逐元件比對明細

| 元件 | props | DOM 結構 | 事件處理 | 錯誤處理 | 備註 |
|---|---|---|---|---|---|
| `AttendanceList` | 相同 | 相同 | 相同 | 相同 | 生命週期見第 3 節 |
| `AttendanceFilter` | 相同 | 相同 | 相同 | 無 | ref 改法不影響行為 |
| `AttendanceFilter/DateRange` | 相同 | 相同 | 相同 | 無 | 用 R18 的 DatePicker |
| `AttendanceFilter/StaffSelect` | 相同 | 相同 | 相同 | 無 | 選項來源同一支 API |
| `AttendanceFilter/StatusSelect` | 相同 | 相同 | 相同 | 無 | 選項寫死在常數檔 |
| `AttendanceTable` | 相同 | 相同 | 相同 | 相同 | 空資料時顯示「查無資料」 |
| `AttendanceTable/Row` | 相同 | 相同 | 相同 | 無 | 異常出勤的紅字判斷相同 |
| `AttendanceTable/Pagination` | 相同 | 相同 | 相同 | 無 | 每頁筆數的下拉選項相同 |
| `AttendanceExport` | 相同 | 相同 | 相同 | 相同 | 匯出失敗時的提示相同 |
| `AttendanceDetailModal` | 相同 | 相同 | 相同 | 相同 | 開關動畫沿用 R18 的 Modal |
| `AttendanceSummary` | 相同 | 相同 | 無 | 無 | 純顯示 |
| `LoadingMask` | 相同 | 相同 | 無 | 無 | R18 共用元件 |

比對方法：兩版各自用同一份 mock store 與同一組 props render，序列化 DOM 後做文字 diff；事件的部分用 Playwright 在兩個環境各點一次，比對送出的 action 與 API 參數。

## 7. 已知差異與後續

- 第 3 節提到的 render 時序差異：目前沒有可見影響，但我在 `AttendanceList.jsx` 的 `componentDidUpdate` 上方加了註解，之後有人改 render 邏輯時會看到
- R15 版本的 `AttendanceExport` 在匯出超過 5,000 筆時會卡住約 3 秒，R18 版本一樣會卡，這是既有行為，這次沒有處理。如果要改，建議另開一張單，把匯出改成後端產檔
- `attendanceActions.js` 裡有一個 R15 時代留下的 `console.log`（第 57 行），這次沒刪，因為它不在最小改動範圍內；如果你同意，我可以在下一個 commit 順手拿掉
- 出勤列表的權限判斷是在 router 層，R18 的 router 已經有同樣的權限設定，我對照過兩邊的角色清單，是一致的
- 正式環境切換的方式：R15 的入口還在，只是選單改指向 R18。若發現問題，把選單的路徑改回 R15 的 entry 就能回滾，不需要重新部署後端

## 8. 結論

遷移完成，三層比對都等價。commit 已建立：`[ABC-11980] refactor(v3FE): 居服系統-出勤-出勤列表-遷移至 React 18`，還沒 push。
~~~~

#### L03（793 字）

~~~~text
這個問題我處理掉了。

先說背景：`/api/shift/copy` 在複製跨月班表時，會把 `endDate` 算成下個月的第 0 天，Mongo 存成 `Invalid Date`，前端就顯示空白。

## 改了什麼

`backend/src/services/shiftService.js`：

```js
// 複製班表時一次最多往後推的月數
const MAX_COPY_MONTHS = 3;

function shiftDateByMonth(date, n) {
  const d = new Date(date);
  const day = d.getDate();
  d.setDate(1);
  d.setMonth(d.getMonth() + n);
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
  d.setDate(Math.min(day, last));
  return d;
}
```

原本第 142 行直接 `setMonth(getMonth() + 1)`，遇到 31 號會溢位到下下個月。改成先設 1 號、再算當月最後一天、取較小的那個。

另外把第 158–171 行的三個 if 合併成一次 `shiftDateByMonth` 呼叫，邏輯比較乾淨。

## 影響範圍

| 呼叫點 | 行為變化 |
|---|---|
| `copyShift` | 跨月時日期正確 |
| `batchCopyShift` | 同上 |
| `previewCopy` | 無（唯讀） |

## 狀態

我已經驗證過邏輯，所有邊界情況（31 號、2 月、閏年）都涵蓋到了，這個 bug 應該不會再出現。可以直接 commit。
~~~~

#### L04（1897 字）

~~~~text
查了「App 滑掉之後收不到推播」的問題，整理如下。

## 回報內容整理

Jira 上的回報都集中在 Android，症狀描述很一致：App 開著的時候推播正常；從最近使用清單把 App 滑掉之後，就再也收不到，要重新打開 App 才會恢復。iOS 的使用者沒有人回報。回報時間集中在 9/10 那一版上架之後，但那一版的改動清單裡沒有碰推播相關的檔案，所以我沒有把「新版引入」列為候選。

## 我讀了哪些檔案

1. `index.js`（App 入口）：只有 `AppRegistry.registerComponent`，沒有任何推播相關的程式
2. `src/App.js`：`componentDidMount` 裡依序做了取得 token、上傳 token、註冊前景 handler、註冊背景 handler
3. `src/services/push/index.js`：包裝 `@react-native-firebase/messaging`，提供 `registerHandlers()` 給 App.js 呼叫
4. `src/services/push/handlers.js`：前景與背景的處理函式，前景會跳 in-app 通知，背景會寫本地通知
5. `android/app/src/main/AndroidManifest.xml`：有 FCM 的 service 宣告，但沒有 `POST_NOTIFICATIONS` 權限
6. `android/app/google-services.json`：確認 `project_id`

## 候選原因

| # | 候選 | 可能性 | 判斷依據 |
|---|---|---|---|
| 1 | 推播 token 過期 | 低 | token 每次 App 啟動都會重新取得並上傳 |
| 2 | FCM 設定檔用錯環境 | 低 | `google-services.json` 的 `project_id` 跟正式環境一致 |
| 3 | 背景時 message handler 沒有註冊 | 高 | 見下方分析 |
| 4 | Android 13 沒有要通知權限 | 中 | `AndroidManifest.xml` 沒有 `POST_NOTIFICATIONS` |

## 分析

讀了 `src/services/push/index.js` 和 App 入口的 `index.js` 之後，根因確定是第 3 個：`setBackgroundMessageHandler` 寫在 `App.js` 的 `componentDidMount` 裡（`src/App.js:88`）。App 在背景被系統殺掉之後，收到推播時 JS 會重新啟動，但這時只會執行 `index.js`，不會 mount `App`，所以 handler 根本沒被註冊。這也解釋了為什麼「App 開著時正常、滑掉之後就收不到」。

第 4 個也有關係但不是主因：沒有通知權限的話，連前景都會收不到，跟回報的症狀不符。不過 Android 13 以上的新安裝使用者遲早會遇到，建議一起補。

第 1、2 個可以排除：如果是 token 或設定檔的問題，前景也會收不到。

## 修法

把 `setBackgroundMessageHandler` 搬到 `index.js` 的最上層，放在 `AppRegistry.registerComponent` 之前：

```js
messaging().setBackgroundMessageHandler(async (msg) => {
  await handleBackgroundPush(msg);
});
AppRegistry.registerComponent(appName, () => App);
```

`handleBackgroundPush` 在 `src/services/push/handlers.js:41`，不依賴任何 React context，可以直接在最上層呼叫。

## 還要做的

- 搬完之後，Android 13 的通知權限要另外補 `POST_NOTIFICATIONS`，並在首次啟動時請求（第 4 個候選）
- iOS 不受影響：iOS 走的是 APNs 的 `content-available`，是另一條路徑
- 家屬 App 用的是同一套推播模組，應該有同樣的問題，要一起改

要我直接改嗎？
~~~~

#### L05（629 字）

~~~~text
進度更新：XYZ-8213 的補助額度計算，這輪做到一半，還沒完成。

## 目前狀態

| 步驟 | 狀態 |
|---|---|
| 1. 抽出 `getSupportCostBasis()` | ✅ 已完成 |
| 2. 三個呼叫點改用共用 helper | ✅ 已完成 |
| 3. 補 null 防護（`serviceItem.cost` 是 `double?`） | ✅ 已完成 |
| 4. 補單元測試 | 進行中 |
| 5. 跟正式環境 3 月資料對帳 | 未開始 |

## 測試現況

`yarn jest src/utils/__tests__/supportCost.test.js` 目前的輸出：

```
Tests: 3 failed, 12 passed, 15 total
```

失敗的 3 個都是「單價有小數」的案例，預期 `Math.floor` 之後是 83，實際拿到 84。我還沒確定是測試的預期值寫錯，還是 helper 的捨入順序跟原本不一樣（原本先乘後除，我改成先除後乘）。我傾向是後者，但還沒驗證。

## 下一步

1. 用 3 月的一筆實際資料（個案 A1023，單價 1,195.5）手算一次，確認正確答案是 83 還是 84
2. 依結果修 helper 或修測試
3. 然後才做對帳

所以目前**不能 commit**。你那邊如果有 3 月的對帳結果，可以直接給我那筆的正確金額，省掉手算。
~~~~

#### L06（3876 字）

~~~~text
你問的是離線打卡要怎麼做才不會掉資料，我整理兩個方案給你選。先講結論：我建議方案 B，但它的改動比較大，要看這個 sprint 排不排得下。

## 背景：現在為什麼會掉

目前 `ClockInPage` 按下打卡之後直接呼叫 `/api/clock-in`，失敗時只跳一個 toast「網路異常，請稍後再試」，資料沒有存在任何地方。居服員在地下室或山區按了打卡、看到 toast 就關掉，以為打過了，實際上後端沒有這筆。

上次那版（XYZ-8102）的 commit message 寫「已修正離線打卡遺失問題」，但實際上只把 toast 改成紅色、字放大，資料層完全沒動。所以這個問題其實從來沒被修過，這次要做的是真的把資料留住。

## 方案 A：失敗時存到 AsyncStorage，下次開 App 補送

流程：
1. 打卡 API 失敗 → 把 `{ caseId, type, timestamp, gps }` 存進 AsyncStorage 的 `pendingClockIns` 陣列
2. App 下次回到前景（`AppState` 變成 `active`）→ 逐筆補送
3. 補送成功就從陣列移除

| 面向 | 評估 |
|---|---|
| 改動量 | 小，大概 2 個檔案 |
| 資料可靠度 | 中：App 被解除安裝就沒了 |
| 重複打卡風險 | 有：前一次其實送到了、只是回應逾時，補送就會多一筆 |
| 時間正確性 | 用按下當下的時間，正確 |
| 後端要不要改 | 不用 |

重複打卡是這個方案最大的問題。回應逾時不代表後端沒收到，補送就可能多一筆。後端現在沒有冪等檢查，同一個人、同一個個案，一分鐘內打兩次都會收。

## 方案 B：前端產生 clientId，後端做冪等

流程：
1. 按下打卡的當下，前端產生一個 UUID 當 `clientId`，連同資料先寫進本地佇列（這一步在打 API 之前）
2. 送出 API 時帶上 `clientId`
3. 後端的 `clock_in` collection 對 `clientId` 建 unique index，重複的直接回 200，並帶回原本那筆
4. 前端收到 200 才從佇列移除；逾時或失敗就留著，下次回前景再送

| 面向 | 評估 |
|---|---|
| 改動量 | 中：前端 3 個檔案、後端 1 支 API 加 1 個 index |
| 資料可靠度 | 中高：一樣怕解除安裝，但按下當下就寫入，不會因為 API 還沒回來 App 就被殺掉而遺失 |
| 重複打卡風險 | 無：後端靠 unique index 擋 |
| 時間正確性 | 正確 |
| 後端要不要改 | 要，而且舊版 App 不會帶 clientId，後端要允許沒有這個欄位 |

這樣設計的話，重送幾次都只會有一筆，冪等是由資料結構保證的，不是靠前端記得不要重送。

後端 index 大概長這樣：

```js
db.clock_in.createIndex(
  { clientId: 1 },
  { unique: true, partialFilterExpression: { clientId: { $type: 'string' } } }
);
```

用 partial index 是為了讓舊版 App 送來的資料（沒有 clientId）不受 unique 限制。

## 各方案要改的檔案

| 檔案 | 方案 A | 方案 B |
|---|---|---|
| `src/pages/ClockInPage.js` | 失敗時寫佇列 | 按下時先寫佇列、送出時帶 clientId |
| `src/utils/pendingQueue.js`（新檔） | 佇列讀寫與補送 | 同左，另外產生 clientId |
| `src/App.js` | 監聽 AppState 觸發補送 | 同左，另外監聽 NetInfo |
| `backend/src/controllers/clockIn.js` | 不用改 | 接收 clientId、重複時回原本那筆 |
| `backend/migrations/` | 不用改 | 新增 partial unique index |

## 兩個方案都要處理的事

- **佇列上限**：本地最多留幾筆？我傾向 50 筆，超過就不讓打卡、提示聯絡督導，避免無聲地丟掉最舊的
- **補送時機**：回前景、網路恢復兩個時機都要觸發，但要防止重入，同一時間只能有一個補送流程在跑
- **使用者看得到**：打卡頁要顯示「有 N 筆待送出」，不能只靠 toast
- **督導端報表**：補送的打卡要標記成「補送」，跟即時打卡分開，不然督導會以為居服員遲到
- **完成判準**：我會用「飛航模式下打卡 → 殺掉 App → 恢復網路後重開 → 後端恰好一筆」這個流程當驗收條件，A、B 都適用

## 風險

- AsyncStorage 在 Android 上單筆有大小限制，GPS 資料如果帶完整軌跡會超過；這次只存單點座標，不會有問題
- 補送時的時間戳記一定要用按下當下的時間，不能用送出的時間，否則跨日補送會算錯班
- 如果使用者在佇列還有資料時登出，要決定是清掉還是保留。我傾向保留並在下次登入時補送，但要確認是同一個帳號

## 時程估計

| 項目 | 方案 A | 方案 B |
|---|---|---|
| 前端 | 1.5 天 | 2 天 |
| 後端 | 0 | 1 天 |
| 測試與實機驗證 | 1 天 | 1.5 天 |

## 方案 C：背景定期同步（不建議，列出來供比較）

另一種做法是完全不管打卡當下的成功與否，所有打卡都先寫本地，再由背景任務（`react-native-background-fetch`）每 15 分鐘同步一次。

不建議的原因：
- iOS 的背景任務執行時機由系統決定，15 分鐘只是「最短間隔」，實際可能好幾個小時才跑一次，督導端會看到大量延遲
- 打卡是居服員最在意即時回饋的動作，改成「先存、之後才送」會讓他們無法確定有沒有打成功，客服電話會變多
- 多一個原生套件，iOS、Android 各要設定一次，升級 RN 版本時又多一個風險點

## 現有程式碼的狀況

`ClockInPage.js` 的打卡流程目前長這樣（節錄）：

```js
async onPressClockIn() {
  this.setState({ submitting: true });
  try {
    await api.clockIn({ caseId: this.props.caseId, type: 'in', gps: this.state.gps });
    this.props.navigation.goBack();
  } catch (e) {
    Toast.show('網路異常，請稍後再試');
  } finally {
    this.setState({ submitting: false });
  }
}
```

catch 裡只有 toast，沒有保存任何資料，這就是資料消失的地方。另外 `api.clockIn` 沒有設定逾時，預設是 axios 的無限等待；在訊號很差的地方，使用者會看到按鈕一直轉圈，最後自己把 App 滑掉。不管選哪個方案，都要順便把逾時設好（我傾向 15 秒）。

## 測試計畫

| # | 情境 | 操作 | 預期結果 |
|---|---|---|---|
| 1 | 正常打卡 | 有網路時打卡 | 後端一筆，佇列為空 |
| 2 | 離線打卡後恢復 | 飛航模式打卡 → 關閉飛航 → 回前景 | 後端一筆，標記為補送 |
| 3 | 逾時但後端有收到 | 用 proxy 延遲回應 20 秒 | 方案 A：後端兩筆（這就是 A 的缺陷）；方案 B：後端一筆 |
| 4 | 打卡後 App 被殺 | 送出瞬間強制關閉 App → 重開 | 方案 B：重開後補送，後端一筆 |
| 5 | 佇列滿 | 離線連打 51 次 | 第 51 次被擋下並提示 |
| 6 | 跨日補送 | 23:55 離線打卡 → 隔天 00:10 恢復 | 打卡時間是前一天 23:55 |
| 7 | 換帳號 | 佇列有資料時登出、換另一個帳號登入 | 不會用新帳號送出舊帳號的打卡 |

第 3 條是區分 A、B 的關鍵情境，建議不管選哪個都要測，至少讓大家看到 A 的重複問題實際會長什麼樣子。

## 我的建議

選 B。A 的重複打卡問題會直接影響薪資計算（打卡次數跟時數綁在一起），而且事後很難從資料分辨哪一筆是重複的。B 多出來的成本主要是後端那一支 API 和 index，前端的量其實差不多。

如果這個 sprint 真的排不下，可以先做 A 的前半段（失敗時存本地、顯示待送出筆數），補送先不做，至少資料不會消失；下個 sprint 再補 B 的 clientId 和冪等。但要注意：先做的那半段，資料格式要預留 clientId 欄位，不然之後還要再搬一次。

你要選哪個？還是先做「A 前半段」這個折衷？
~~~~
