# 執行環境需求

本檔描述無人看管批次執行本 skill 所需的最小環境、部署前 smoke 測試、`CLAUDE_CONFIG_DIR` 隔離做法、認證方式、整合分支守則，以及 runner 的環境變數與狀態目錄佈局。目標是讓 skill 在任何一台乾淨機器上都能照這份文件重建執行環境，不依賴任何本機專屬設定。

## 最小環境需求

| 項目 | 版本/需求 | 用途 |
|---|---|---|
| macOS | 任一支援 `launchd`/`caffeinate` 的版本 | 常駐排程與防止睡眠 |
| Node.js | 20（建議透過 nvm 管理） | 前端建置 |
| python3 | 3.x（標準函式庫即可，不依賴額外套件） | runner 主迴圈、額度查詢腳本 |
| jq | 任一近期版本 | JSON 組裝（通知 payload、env 讀取） |
| gh（GitHub CLI） | 已登入且對 repo 有 push 權限 | 開 PR、查詢遠端分支 |
| git | 任一近期版本 | 全部版本控制操作 |
| Playwright | Node 套件，隨 repo 或 skill 的 helper 一起安裝 | build 產物啟動 smoke（零 `pageerror`/console error 斷言） |
| Claude Code CLI | 需支援下列旗標：`--model`、`--output-format stream-json`、`--verbose`、`--json-schema`、`--permission-mode auto`、`--permission-prompts none`、`--max-budget-usd`、`--disallowedTools`、`--append-system-prompt`（與 `helpers/runner.py` 的 `REQUIRED_CLI_FLAGS` 同一份清單，pre-flight 與組指令共用同一個常數來源，不再各自維護一份；前 8 個 2.1.272 實測皆存在，`--verbose` 是 1.1.0 起 stream-json 逐事件輸出的前提、2.1.275 實測）；`--max-turns` 不是必需（若當前版本沒有此旗標，runner 不依賴它） | headless 呼叫本 skill |

Node 版本以 repo 內若有版本鎖定檔（如 `.nvmrc`）為準；沒有鎖定檔才用上表的預設版本。

## 部署前 smoke 測試

在正式排程執行前，依序驗證以下項目，任一項失敗都要先解決才能啟動 runner：

1. **旗標存在性**：執行 `claude --help`，確認輸出包含 `--model`、`--output-format`、`--json-schema`、`--permission-mode`、`--permission-prompts`、`--max-budget-usd`、`--disallowedTools`、`--append-system-prompt`、`--verbose`（共 9 個；只跑 `claude --help` 核對存在即可，不必真的執行帶這些旗標的呼叫）。缺任一項就是版本太舊，先升級 CLI。
2. **認證 smoke**：
   ```
   claude -p "echo ok" --output-format json --permission-mode auto --permission-prompts none < /dev/null
   ```
   未登入或 token 失效時的失敗簽名是回傳 `is_error:true`、`result` 內含 `Not logged in`。這個簽名同時是 runner pre-flight 判斷認證是否有效的依據，smoke 測試時故意先確認「失敗時長這樣」，之後才好分辨「認證正常」與「認證過期」。
3. **整合分支存在性**：
   ```
   git ls-remote --heads origin <integration-branch>
   ```
   必須有輸出。整合分支由人工從基準分支手動切出並推上遠端，不由 runner 自動建立（見「整合分支守則」）。
4. **磁碟空間**：確認可用空間高於 runner 設定的下限（預設 20GB，見 env 變數表 `DISK_MIN_GB`），空間不足時 build 與 `npm ci` 容易在中途失敗且難以判斷原因。
5. **額度查詢管道是否可用**：確認額度查詢腳本能查到當前用量（`five_hour`/`seven_day` 的 utilization 與 resets_at）。**已知的不確定項目**：用量查詢的 API 是否接受長效 OAuth token（見下一節「認證」）需要在目標機器上實測才能確定；若不接受，改用下一節說明的備援路徑。

### 建置產物啟動 smoke（`helpers/boot-smoke.cjs`）

runner 在 L1 驗證時對 `backend/public/build/react18/` 跑 `node helpers/boot-smoke.cjs --dist <該目錄>`。這個目錄**沒有 index.html**：React 18 的 app shell 由 backend 的 `views/index_18.ejs` 掛載（注入 `window.__PRELOADED_STATE__`），資源由 `views/partials/assetLoader.ejs` 依專案自訂的 `manifest.json` 契約（`js`／`modulePreloads`／`css`）動態插入。所以 `--dist` 模式在找不到 index.html 但找得到 `manifest.json` 時會**自行合成一頁 shell**：鏡像上述兩個 EJS 的 meta／nonce／root 容器／css／modulepreload／module script，`__PRELOADED_STATE__` 給空物件（backend 未登入時 `user`／`candidate` 為 undefined、被 `JSON.stringify` 剔除，等價於空物件），靜態伺服器根目錄就是產物目錄本身（`vite.config.js` 的 `base` 為空字串，產物用相對路徑）。判準：任何 `pageerror` 一律失敗；console error 全部算失敗，唯一例外是瀏覽器自身回聲的 `Failed to load resource` 那一行（對應的 HTTP 狀態已由下面的網路事件判過一次，不重複計入）；網路失敗（HTTP 回應狀態碼 ≥ 400、或請求本身失敗）改依 URL 路徑判定：命中 `/api/`、`/auth/` 前綴才忽略（合成 shell 沒有後端，未登入才會觸發的端點失敗是預期雜訊），其餘（如缺資產）一律失敗；被忽略的每一筆都印在 stdout 標 `[ignored:<原因>]`，不靜默吞掉；靜態伺服器對命中後端前綴的路徑一律回真 404、對有副檔名的缺檔也回真 404，只有無副檔名的路徑才退回 app shell（實體 index.html 或合成版）。產物目錄本身不含 `locales/` 等手足靜態資源——`react_18/src/i18next.js:47` 的 `loadPath` 打 `${DEPLOY_PREFIX}/locales/lang/zh-TW/{{ns}}.json`，實體檔在 `backend/public/locales/`，與 `backend/public/build/react18/` 是手足目錄，不在、也不會在 vite build 產物內；runner 呼叫 `boot-smoke.cjs` 時固定多帶一個 `--static-root <repo>/backend/public` 當第二靜態根（`--dist` 的目錄永遠優先），手動跑忘記帶這個旗標會看到 `resource: GET /locales/… → 404` 而 exit 1，這是預期的 fail-closed，不是誤報。

**smoke 必須對 production build 跑**（runner 的 `npm run build` 在 `frontend/react_18` 執行 `vite build`，預設就是 production 模式）。開發版產物（`npm run devReact18` 的 watch 輸出）會保留 prop-types 執行期檢查，2026-09-16 實測本機開發版產物在合成 shell 下有 7 筆既有的 `PropTypes.oneOf`／`oneOfType` 用法錯誤警告（`react_18/src/containers/Form/DaycaseRecordForm*.jsx` 等），production build 下為零；這些是 repo 既有問題，不屬於遷移範圍，也不該為了讓 smoke 過而加進忽略清單。Playwright 若不在 `frontend/react_18` 的依賴內，用 `NODE_PATH` 指向任一已安裝 `playwright` 與 chromium 的 `node_modules`（例如本機另一個 skill 的 helper 目錄）；找不到時腳本回退出碼 2，runner 不會把它當通過。

## `CLAUDE_CONFIG_DIR` 隔離

無人看管批次跑 headless session 時，**不能沿用日常互動用的設定目錄**。原因：日常設定目錄通常掛了多個 hook（例如 commit 前檢查、程式碼風格檢查）與 plugin，這些是為互動式工作流設計的，headless 執行時同樣會被觸發、介入 skill 的判斷與輸出，讓 headless 流程變得不可預期。

做法：

- 建一個**獨立的真實目錄**（不是 symlink）當 `CLAUDE_CONFIG_DIR`，例如家目錄下的 `.claude-migration`。**不要**用「symlink 共用設定、只在某個子路徑分流」的做法——那種做法的目的正好相反（想共用大部分設定只切憑證），這裡要的是完全隔離。
- 該目錄只放兩樣東西：一份最小 `settings.json`（無 `hooks`、無 `plugins`，並設 `env.DISABLE_AUTOUPDATER="1"` 避免無人看管期間 CLI 自動升版打斷排程）、以及本 skill 本身（放在該目錄的 `skills/` 底下）。
- 驗證隔離是否生效：在全新建立、尚未登入過的 `CLAUDE_CONFIG_DIR` 下執行 `claude -p "echo ok"`，應該在數十毫秒內就回應失敗（`is_error:true`、`result` 含 `Not logged in`），證明憑證、設定、session history 都是跟著目錄走的，不會意外讀到別的設定目錄的登入狀態或 hook 設定。
- 額外確認：目標 repo 本身沒有被版本控制追蹤的專案層 Claude 設定檔（例如某個隱藏設定目錄被 commit 進 repo），否則即使 `CLAUDE_CONFIG_DIR` 隔離了全域設定，repo 層的專案指示仍會在每次呼叫時被自動載入。

## 認證

使用單一帳號，用 `claude setup-token` 產生長效憑證，不用互動式登入、也不直接讀 Keychain 當唯一來源：

1. 在隔離出來的 `CLAUDE_CONFIG_DIR` 下執行 `claude setup-token`，產生一年期 OAuth token。官方用途說明是給「CI pipeline、腳本，或其他無法互動式瀏覽器登入的環境」使用，訂閱制帳號可用。
2. 把產生的 token 寫進一個獨立的環境檔（與通知用的憑證放同一份檔案即可），設成 `CLAUDE_CODE_OAUTH_TOKEN`，該檔案權限設為僅擁有者可讀寫（`chmod 600`）。啟動腳本 `export` 這個變數後，runner 與 skill 之後都不需要碰 Keychain。
3. 額度查詢腳本的讀取順序：先讀 `CLAUDE_CODE_OAUTH_TOKEN` 環境變數，查不到或用量查詢 API 不接受這個 token 時，退回讀 Keychain（含帶雜湊後綴的項目名）。**待實測確認**：用量查詢 API 是否接受長效 token；若不接受，需要在該 `CLAUDE_CONFIG_DIR` 下手動互動式登入一次，讓 Keychain 有對應項目可供備援路徑讀取——headless 呼叫本身仍然只用環境變數裡的 token，不受這次手動登入影響。
4. **token 到期或被撤銷的處理**：runner 把「認證 smoke」段描述的失敗簽名（`Not logged in`）視為認證過期，進入暫停狀態並發一則通知，不計入失敗重試次數。復原方式：重新執行 `claude setup-token` 產生新 token、更新環境檔，再重啟 runner。

## 整合分支守則

假設所在的 GitHub 方案是免費方案、repo 是私有的——這個組合下 GitHub 原生的分支保護與 ruleset 功能都無法對私有 repo 生效（官方文件的「限制可推送對象」功能只在免費方案的公開 repo，或付費方案的私有 repo 才可用；若目前的席數規模去換算升級費用不成比例，這裡選擇不升級方案）。因此整合分支的保護**不靠 GitHub 平台機制，靠 runner 自己比對 SHA**：

- 整合分支由人工手動從基準分支切出並推上遠端（例如 `git checkout -b <integration-branch> origin/<base-branch> && git push -u origin <integration-branch>`），runner 不會自動建立；pre-flight 檢查發現遠端不存在該分支時，直接印出上面這行指令並結束，不會自己補建。
- 團隊約定：**不直接推整合分支**，任何修正都走個別的檢查點分支（cp 分支），再由 runner 統一 fast-forward 合併回整合分支。
- runner 只做 fast-forward 合併，從不 force push；人工不小心推上去的 commit 不會被蓋掉。
- 每次取件前，runner 會 `git fetch` 後比對遠端整合分支的 tip commit 跟它自己記錄的「上次確認過的 tip」——`queue.json` 頂層的 `integration_tip_sha` 欄位——是否一致：一致才繼續、不一致就進 `paused(integration_diverged)`、整批停下發一則通知（代表有人在 runner 不知道的情況下動了整合分支，需要人工確認再繼續，而不是讓 runner 帶著錯誤假設繼續合併）。`integration_tip_sha` 的生命週期：首次啟動時為 `null`，runner 以當下的遠端 tip 寫入當基線並在啟動通知附上該 SHA；之後每次 fast-forward 合併並 push 整合分支成功後，更新為新的 HEAD。這個比對發生在「取模組之前」，不是等到 push 失敗才發現，避免先白燒一個模組的額度。
- 解除 `paused(integration_diverged)`：人工確認過整合分支上的外部變動沒問題後，執行 `python3 helpers/runner.py unblock --integration-tip`——把記錄的 `integration_tip_sha` 重新對齊遠端現況並解除暫停（`integration_diverged`/`master_conflict`/`integration_dirty`/`integration_local_ahead` 都算），下次啟動會從這個新 SHA 繼續，不需要人工直接改 `queue.json`。它只清暫停原因、不清鎖定（hold）；hold 還在時它會印「還要 `unblock --runner`」而不是「下次啟動會繼續」——只跑它，runner 每次啟動都在 pre-flight 之前靜默退出。反過來 `unblock --runner` 只清 hold、不清暫停原因，但暫停原因本身不擋重啟：下次啟動照常跑前置作業，造成暫停的狀況已經不在（本機已對齊、遠端沒變）就繼續，還在就再次暫停、而且同原因不重複通知；所以它看到 integration 類的原因還在會提醒先確認本機已對齊、遠端有變動再跑 `--integration-tip`。
- **同一個原因但通知說「已鎖定（hold）」、細節含「不是預期的 entry commit」**（1.1.1）：這是 ff-merge 之後 HEAD 不是預期的 entry commit（代表 collect 之後 entry 分支又多了 commit——還有別的東西在改 repo）。不論 runner 有沒有把本機整合分支退回合併前，都鎖定：一般暫停擋不住——`launchd` 幾分鐘後重啟、把同一個 entry 放回 pending 重試，多半再次不符、同原因重複暫停不再通知，無上限地燒額度。細節分兩種：(1)「本機整合分支已退回 <sha>」——本機已對齊，找出並處理那個別的寫入者（上一節第 6 點的指令）後 `unblock --runner`；(2)「本機整合分支停在非預期 commit（合併前是 <sha>），請人工處理」——runner 退不回去（HEAD 已被切走、工作樹有未提交變更、`git status` 失敗、檢查到 reset 之間 HEAD 又變了、或 reset 失敗，細節會說是哪一種；未追蹤檔不擋退回，只列出來給人看）。處理順序：先到執行機器上看本機整合分支停在哪、工作樹留了什麼（那是證據，別急著 `reset --hard`），找出並處理那個別的寫入者，把本機整合分支對齊遠端（確認證據已保留後 `git checkout <整合分支> && git reset --hard <細節裡「合併前是」的那個 sha>`，或直接對齊 `origin/<整合分支>`），然後 `unblock --integration-tip` **與** `unblock --runner` 兩個都要跑。
- **`paused(integration_local_ahead)`、已鎖定**（1.1.1）：模組開工前的 git 前置發現本機整合分支上有「不是 runner 合進來的 commit」——領先遠端的 commit 裡，排除 merge commit、排除可從 `origin/<基準分支>` 或任一斷點分支到達的之後還剩下的（`git log --no-merges <整合分支> --not origin/<整合分支> origin/<基準分支> <斷點分支…>`）。前置作業自己會把基準分支與還開著的斷點分支合進本機整合分支而不推（要等該 entry 走到 push 才上遠端），所以 entry 沒走到 push、或前置作業在合併之後才失敗（斷點回流衝突、停止訊號）時本機本來就領先——那種領先全部排除得掉，不算。剩下來的是第二道防線要抓的：上一輪沒走完的發佈段（ff-merge 之後被停止訊號中斷、上一條的退不回去、或人只跑了 `unblock --runner` 沒把本機對齊），runner 對它看不出「為什麼」，只知道不能從這個 commit 切下一個 entry 的分支。本機分支不動（那是證據）。通知的細節第一句就是處理順序（其餘會被 300 字截掉也沒關係）：先看細節列出的那幾個 commit、確認保留後 `git checkout <整合分支> && git reset --hard origin/<整合分支>`，再 `unblock --runner`（`unblock --integration-tip` 也會清這個原因，但這種情況遠端沒動，不跑也可以）。推送整合分支失敗（網路抖動、遠端 hook 拒絕）不會走到這裡：runner 先問遠端是不是其實已經推上去了（是就照 done 收尾），不是就把本機退回合併前、一般暫停，重啟後重試；**連續第二次**推不上去就鎖定（同 crash 的「同簽名兩次」機制，簽名 `integration_push_failed`），不然分支保護、憑證過期這類持續性的失敗會每輪重跑一次完整模組而且第二次起不再通知。
- 這台機器上 `gh auth` 用執行者本人的帳號 token 即可，不需要另外建立機器人帳號——SHA 比對機制本身不檢查身分,只檢查內容一致性。
- 頁面分支（`queue.json` 每個 entry 的 `branch` 欄）命名樣板見 env 變數表 `BRANCH_USER` 一列；整合分支本身不套用這個樣板。

## env 變數表

以下是 runner 與其輔助腳本會讀取的所有環境變數（`*` 為必填；其餘為選填，括號內是預設值）：

| 名稱 | 預設值 | 必填 | 說明 |
|---|---|---|---|
| `REPO_DIR` | — | * | 目標 repo 的工作目錄路徑 |
| `INTEGRATION_BRANCH` | `feat/r18-migration` | | 整合分支名稱 |
| `BASE_BRANCH` | `master` | | 基準分支名稱 |
| `BRANCH_USER` | — | * | 頁面分支名稱第三段用的使用者代號（樣板 `<jira>/refactor/<BRANCH_USER>/<entry-id>`），通常是執行者在 issue tracker 的帳號名；`import-inventory` 產生每個 entry 的 `branch` 欄時讀取 |
| `MIGRATION_STATE_DIR` | 家目錄下的 `r18-migration-state/<repo>/` | | runner 狀態目錄；若指到 repo 內，啟動時必須通過 `git check-ignore` 才能用 |
| `CLAUDE_BIN` | `claude` | | Claude Code CLI 執行檔名稱/路徑 |
| `CLAUDE_MODEL` | `sonnet` | | 呼叫本 skill 時指定的模型 |
| `CLAUDE_CONFIG_DIR` | 空（用 CLI 預設值） | | 隔離用的設定目錄，見上一節 |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | * | `claude setup-token` 產出的長效憑證 |
| `MODULE_BUDGET_USD` | `15` | | 單個模組單次呼叫的預算上限（美元） |
| `MODULE_TIMEOUT_MIN` | `150` | | 單個模組呼叫的 wall-clock 逾時（分鐘），逾時先送 TERM、30 秒後 KILL |
| `QUOTA_PREFLIGHT_FIVE_HOUR` | `80` | | 五小時額度使用率超過此百分比時，取件前先等待 |
| `QUOTA_PREFLIGHT_SEVEN_DAY` | `95` | | 七日額度使用率超過此百分比時，取件前先等待 |
| `MAX_WAIT_HOURS` | `168` | | 等待額度恢復的總時長上限 |
| `ENTRY_MAX_FILES` | `12` | | 單個 entry 允許的最大檔案數，超過視為過大 |
| `ENTRY_MAX_LINES` | `4000` | | 單個 entry 允許的最大總行數，超過視為過大 |
| `CHECKPOINT_MAX_MODULES` | `8` | | 累積多少個模組後自動開一個檢查點 |
| `CHECKPOINT_MAX_LINES` | `3000` | | 累積多少行改動後自動開一個檢查點 |
| `CIRCUIT_BREAKER_N` | `3` | | 連續失敗/錯誤達此次數即整體暫停 |
| `DISK_MIN_GB` | `20` | | 磁碟可用空間下限（GB），低於此值 pre-flight 直接失敗 |
| `SESSIONS_RETENTION_DAYS` | `14` | | 原始呼叫紀錄保留天數，超過自動清除 |
| `NODE_VERSION` | `20` | | 啟動腳本要切換到的 Node 版本 |
| `GH_BIN` | `gh` | | GitHub CLI 執行檔名稱/路徑 |
| `NOTIFY_CHANNEL` | `line` | | 通知管道（`line` 或本機通知備援） |
| `LINE_CHANNEL_ACCESS_TOKEN` | — | * | LINE Messaging API 的 channel token |
| `LINE_NOTIFY_TARGET_ID` | — | * | LINE 推播對象 id。這兩個變數名沿用既有另一支行動 App 發版流程（GitHub Actions 的 LINE Bot 通知步驟）用的同名變數，共用同一個官方帳號與月推播額度，不是本次新申請 |
| `LINE_MONTHLY_CAP` | `180` | | 月推播則數上限，超過後 INFO 等級事件改為靜默（只留 log） |
| `NOTIFY_ON_DONE` | `0` | | 模組完成事件是否即時推播（0=只進每日摘要） |
| `NOTIFY_ON_QUOTA_WAIT` | `0` | | 額度等待事件是否即時推播 |
| `NOTIFY_PAUSE_REMIND_HOURS` | `24` | | 暫停狀態每隔多久重複提醒一次 |
| `NOTIFY_DAILY_DIGEST` | `09:00` | | 每日摘要通知的發送時間 |

共 31 個變數，其中 5 個必填：`REPO_DIR`、`BRANCH_USER`、`CLAUDE_CODE_OAUTH_TOKEN`、`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_NOTIFY_TARGET_ID`。

## 狀態目錄佈局

`MIGRATION_STATE_DIR`（預設在家目錄下、repo 外的 `r18-migration-state/<repo>/`）底下的檔案：

| 檔案/目錄 | 用途 |
|---|---|
| `queue.json` | 唯一的狀態真值：entry 清單、依賴、狀態機、`limits`、整合分支 tip SHA 記錄（`integration_tip_sha`，見「整合分支守則」）。只有 runner 會寫入 |
| `queue.json.lock` | `queue.json` 的寫入鎖（1.1.1）：runner 主迴圈與 `release`／`unblock`／`import-inventory` 改**既有的** `queue.json` 之前都先對這個檔取 flock；唯一例外是 `import-inventory` 第一次建立 `queue.json`，那條路徑不取鎖（檔案還不存在時 runner 本來就跑不起來），所以不要同時跑兩個首次匯入。內容永遠是空的、常駐不刪——`queue.json` 每次寫入都是「寫 `queue.json.tmp` → 原子替換」，會換掉 inode，鎖掛在資料檔本身會失效，所以獨立成一個永不被替換的檔案。寫入途中被殺可能留下 `queue.json.tmp`，下次寫入會直接覆蓋，不需處理 |
| `PROGRESS.md` | 每完成一個模組就重新產生的人類可讀進度總覽 |
| `runner.lock` | 互斥鎖，防止多個 runner 行程同時操作同一份狀態。用 flock 實作（1.1.1）：有沒有人持有由核心決定，行程正常結束或被殺都會自動釋放；runner 結束後檔案**會留著**，裡面的 `pid`／`host`／`since` 是上一次取得鎖時寫的、只供排查——檔案存在、或那個 pid 還活著，都不代表鎖被持有。不要在 runner 執行中刪它：刪掉後另一個 runner 會建出新檔並取到鎖，變成兩個 runner 同時跑 |
| `runner.log.jsonl` | 一行一筆事件紀錄（時間、entry、事件類型、呼叫序號、耗時、花費、session id、細節）。`attempt` 欄是呼叫序號（同 `sessions/<module>-<n>` 的 `<n>`，單調遞增），不是 queue 的失敗計數 `attempts` |
| `notify-usage.json` | 通知額度（月推播計數等）的使用記錄 |
| `notify-deadletter.jsonl` | 通知發送失敗的補送佇列 |
| `<module>-progress.md` | 單個模組的階段勾選進度，供 resume 使用 |
| `<module>-contract.md` | 單個模組的合約表（見另一份合約抽取文件） |
| `<module>-report.md` | 單個模組完成後的驗證報告 |
| `diff-tests/<module>/*.test.js` | 差異測試產出，不進 repo |
| `sessions/<module>-<n>.stream.jsonl` | 每次 CLI 呼叫的 stream-json 逐事件落檔（system／assistant／user／result，含每個工具呼叫與結果）。CLI 直接寫這個檔、不經 runner 記憶體，逾時被殺時仍保留到那一刻為止的事件；依 `SESSIONS_RETENTION_DAYS` 保留 |
| `sessions/<module>-<n>.json` | 該次呼叫的 meta：returncode、逾時、耗時、stderr 尾端、stream 路徑與事件統計、`result` 事件全文（`structured_output`、成本、`permission_denials`、`terminal_reason`）；依 `SESSIONS_RETENTION_DAYS` 保留 |
| `sessions/<module>-<n>-<name>.log` | 子行程完整 stdout＋stderr（`build`、`smoke`、`npm-ci`、`git-merge-base`、`git-merge-cp-<斷點>`、`git-merge-ff`、`git-push-integration`、`git-push-branch`、`gh-pr-create`）；queue／通知裡的 detail 只截尾段並以 `（全文: sessions/…）` 指到這裡；依 `SESSIONS_RETENTION_DAYS` 保留 |
| `diagnostics/<module>-<n>-<時間>/` | 失敗當下自動凍結的診斷包（判讀為 timeout／error／blocked／hook_denied／auth_expired、或 L1 沒過）：`SUMMARY.md`（給人與 Claude 讀）、`stream.jsonl.gz`、`meta.json`、子行程 log、progress／contract／report 快照、`queue-entry.json`、`runner-events.jsonl`。**不受保留期清理**，目錄權限 700。`runner.py diagnose` 也產在這裡 |
| `diagnostics/runner-<時間>-<原因>/` | 每次 runner 級暫停（含 crash）自動凍結的診斷包：`runner_state`、traceback、最近 200 筆事件、`queue.json` 原檔複本（即使損毀）、deadletter |
| `crashes/<時間>-<簽名>.txt` | runner 未預期例外的 traceback 全文（簽名 = `<例外類別>@<檔>:<行>`）；不受保留期清理 |

這個目錄必須在 repo 之外，或者被 repo 的 `.gitignore` 排除——啟動時會用 `git check-ignore` 驗證，驗不過就直接失敗，避免把大量中間產物（尤其是含原始輸出的 `sessions/`）意外版控進 repo。

## 出錯時怎麼做

runner 把「失敗當下的全部證據」凍結成一個目錄，人只要把它帶回開發機交給 Claude 分析即可，不必在無人看管的機器上翻五個檔案：

1. **看通知第一行**：`module_blocked`／`module_failed`／`paused`／`runner_crashed` 的內文第一行固定是 `診斷: diagnostics/<名稱>`（放第一行是因為 notify.sh 會把訊息截到 300 字元，路徑一定要在截斷之前）。`runner.py status --verbose` 與 `PROGRESS.md` 的「待人工事項」也列同一個路徑。
2. **打包**（在執行機器上）：
   ```
   cd <skill 目錄>/helpers
   python3 runner.py diagnose <entry-id> --tar          # 指定 entry，預設取 sessions/ 內最新一次呼叫
   python3 runner.py diagnose --all-failed --tar        # 所有 blocked／failed 各一包
   python3 runner.py diagnose --runner --tar            # runner 級（暫停原因、最近一次 crash）
   ```
   印出來的 `.tar.gz` 就是要帶走的東西。`diagnose` 只讀 `queue.json` 不寫，重跑幾次都安全；自動凍結的那份不會被覆蓋（同名加序號）。
3. **帶回開發機**：`scp <執行機器>:<狀態目錄>/diagnostics/<名稱>.tar.gz .`，解開後先讀 `SUMMARY.md`——它的結構固定：呼叫概況與環境指紋（哪版 skill／runner／CLI／模型／repo HEAD）→ 結構化結果（含 `failed_at`）→ 工具呼叫時間軸（subagent 縮排、每筆耗時、錯誤標記）→ 全部 `is_error` 的工具結果、`permission_denials`、最後 10 個事件（逾時就看這裡）、stderr 尾端 → skill 側 progress 勾選與失敗紀錄 → build／smoke 全文尾端（smoke 另抽 `[ignored:*]`／FAIL 行）→ runner 事件 → 診斷包內檔案清單。要更深就解 `stream.jsonl.gz`。
4. **憑證**：`SUMMARY.md` 內命中憑證樣式（GitHub token、AWS key、私鑰、`password:`／`_token:` 字面）的行整行換成 `[REDACTED:<類別>]`；`stream.jsonl.gz` 與各 log **不遮罩**（遮罩會破壞證據），交出去之前自己看一眼，或只交 `SUMMARY.md`。
5. **解除**：entry 級失敗修好後 `runner.py unblock <entry-id>`；runner 級 crash 同簽名兩次後會鎖定（`runner_state.hold`；第 6 點那一類例外第一次就鎖定），修好後 `runner.py unblock --runner`（見下一節）。
6. **crash 的例外是 `LeftoverProcessError` 或 `UnsignalableGroupError`**（1.1.1）：這不是程式錯誤，是 runner 在回報「CLI 衍生的行程沒有收乾淨」——前者是有行程自行脫離了 process group（訊號送不到）還握著 CLI 的輸出 pipe、或 SIGKILL 之後 group 仍有成員，後者是 group 裡有送不了訊號的行程。它可能還在改 repo，所以 runner 不把這一輪當成一般逾時，而且**第一次出現就鎖定**（`runner_state.hold`）：一般的暫停只是結束行程，`launchd` 幾分鐘後就會把 runner 重新拉起來照常往下跑，只有鎖定擋得住。先在執行機器上找出並處理殘留行程（`ps -ax -o pid,ppid,sess,user,command`，或 `lsof +D <repo 目錄>` 看誰還開著 repo 裡的檔案），確認乾淨之後執行 `runner.py unblock --runner`。runner 偵測不到的一種：自行脫離 group **而且**關掉了 stdio 的行程（標準的 daemon 化）——它不在 group 裡、也不握 pipe；逾時之後若懷疑有這種行程，同樣用上面兩個指令查。

## launchd 常駐與重啟行為

用 `launchd` 的 `KeepAlive` 讓 runner 常駐，搭配 `caffeinate -is` 防止機器在批次執行期間睡眠。`launchd.plist.template` 不會把整份 env 檔內容塞進 plist，只傳一個環境變數 `R15_R18_MIGRATE_ENV` 指向 env 檔路徑（`EnvironmentVariables` 區塊），實際內容由 `run-migration.sh` 在啟動時載入。`run-migration.sh` 找 env 檔的優先序是：第一個參數 > `R15_R18_MIGRATE_ENV` > 家目錄下的預設位置（`$HOME/.claude/r15-r18-migrate.env`）；正因為它是「指向 env 檔的路徑」這個 bootstrap 層變數，所以**不寫在 env 檔本身裡面**（env 檔內的變數是給 `runner.py`/`notify.sh` 讀的執行期設定，`R15_R18_MIGRATE_ENV` 是給 `run-migration.sh` 找 env 檔用的，兩者角色不同、生命週期也不同）。

- runner 進入任何一種「暫停」狀態（例如認證過期、磁碟空間不足、整合分支被意外變更、連續失敗觸發熔斷）時，一律先發一則通知，然後主動結束行程（exit 3）。
- `launchd` 的 `KeepAlive` 設定會偵測到行程結束後自動重啟。重啟後 runner 會重新檢查暫停原因是否已解除：**若原因仍未解除，直接靜默退出，不重複發通知**——避免同一個未處理的問題每次被 `KeepAlive` 重啟就再通知一次，造成通知疲勞。只有原因已解除（例如人工已更新過期的憑證、已確認整合分支變更）才會繼續往下跑並發下一次正常的啟動通知。
- **exit 2 類的 pre-flight 失敗不會發通知**（狀態目錄未被 git 忽略、CLI 旗標缺、遠端沒有整合分支、`runner.lock` 被活行程持有）——這些是部署當下就該被人看到的設定錯誤，故意不走 paused 通知路徑，避免把「一次性的環境沒裝好」誤判成需要長期追蹤的執行期暫停。代價是 `launchd` 的 `KeepAlive` 一樣會每隔 `ThrottleInterval` 重跑一次、但**永遠不會通知**，所以首次 `launchctl load` 之後務必看一次 `StandardErrorPath`（見上方 plist 範本的四個佔位符）確認 pre-flight 真的過了，不要只憑「有沒有收到通知」判斷部署是否成功。
- **runner 未預期例外（crash）**：traceback 寫進 `crashes/`、印到 `StandardErrorPath`，並走 paused（原因 `runner_crashed`，通知事件 `runner_crashed`）而不是直接 raise——直接 raise 會讓 `KeepAlive` 每隔 `ThrottleInterval` 重啟一次、每次一則通知，而且 `runner_state` 停在 `running` 看不出曾經 crash。去重比對「例外簽名」（`<例外類別>@<檔>:<行>`）：同簽名第一次通知、重啟後**第二次**再通知一次並設 `runner_state.hold`，之後每次啟動在 pre-flight 之前就靜默退出（連認證 smoke 那次 CLI 呼叫都不做），直到人工執行 `runner.py unblock --runner`。hold 的理由：crash 若落在模組執行之後（例如開 PR 時），不鎖定的話每次重啟都會白燒一個模組的預算。簽名不同（另一個 bug）視為新事件，照第一次處理。例外：「CLI 衍生的行程沒收乾淨」那一類（上一節第 6 點）**第一次就鎖定**，因為重啟後的第二輪多半不會再出同一個錯，等第二次等於永遠不鎖。hold 寫不進 `queue.json`（磁碟滿、I/O 錯誤）時通知會改說「鎖定沒有寫進狀態檔，請立即 `launchctl unload`」——這時 `KeepAlive` 沒有東西擋，只有人手動停掉服務有效。
- **重啟後被中斷的 entry 與 hard 斷點**（1.1.1）：pre-flight 把上一輪停在 `running`（模組執行中）**與 `waiting_quota`（額度等待中）**的 entry 放回 `pending`、`attempts` 不變——後者原本不會放回，取件只挑 `pending`、`unblock <entry>` 只收 `failed`／`blocked`，停止訊號落在額度等待期間的 entry 會永久卡住（`queue_stalled` 通知會發，但沒有指令能救）；放回是安全的，取件後、呼叫 CLI 前還有一次額度 pre-flight。主迴圈取件之前先找還停在 `opened` 的 **hard** 斷點（上一輪在 `wait_for_release` 等人放行時被停掉），有就回到等待——模組完成後的斷點檢查只看 `pending` 的斷點，不補這步的話重啟會直接處理下一個模組、繞過人工閘門；`released`／`merged` 的不再等。
- **`ExitTimeOut`**（plist 範本，90 秒）：`launchctl unload`／`stop` 送 SIGTERM 之後 launchd 等這麼久才送 SIGKILL。runner 收到 SIGTERM 會先收乾淨 CLI 的 process group（最壞約 50 秒）；收乾淨的話是正常停止（記一筆 `interrupted`、回 EXIT_OK，不凍結、不鎖定），收不乾淨（`ProcessCleanupError`）才走 crash 流程凍結診斷包、寫入鎖定——`ExitTimeOut` 要蓋住的是後面那條。`man launchd.plist` 只說預設值 system-defined，不寫的話 runner 可能在鎖定落盤之前就被 SIGKILL。
- **停止訊號的延後**：SIGTERM／SIGHUP／SIGINT 三種都由 runner 接管。三段期間再送任何一種停止訊號都會被**延後到那一段結束**才生效：CLI 剛啟動的一瞬間、收尾 CLI process group 的期間（最長約 50 秒）——打斷的後果是 CLI 還活著、runner 卻放掉 `runner.lock`；以及每一次進入暫停（凍結證據＋寫狀態＋送通知，最長約 30 秒）——打斷的後果是鎖定（hold）沒落盤、runner 被當成正常停止、重啟後照跑。暫停那一段跑完 runner 本來就會退出，延後的訊號直接丟棄（印一行到 `StandardErrorPath`）。所以手動測試時連按兩次 Ctrl-C 第二次沒有反應是正常的；要立即中止只能 `kill -9`，那會留下殘留行程，之後要照上一節第 6 點清。
