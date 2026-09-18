# queue.json Schema

## 背景

`queue.json` 是批次遷移 runner 的狀態真相來源。它由兩種行為寫入：

- `helpers/runner.py import-inventory <盤點檔>`：把人工盤點好的清單（哪些頁面要搬、依賴關係、分幾個 wave…）原樣轉錄成本檔的靜態欄位。這一步是冪等的，且不從盤點檔推導任何東西——`depends_on` 照盤點檔填、不自動計算。
- runner 執行期：每處理一個 entry 就更新該 entry 的執行狀態欄位（`status`、`attempts`、`last_commit`…）。

**人工不會直接編輯這個檔案**；要改內容一律透過 `import-inventory` 重跑，或由 runner 在執行過程中寫入。

下面是完整欄位定義。`entry`（`modules[]` 的元素）分成兩類欄位：**盤點期填**（`import-inventory` 寫入，之後不再變動）與**執行期填**（只有 runner 會寫）。

## 頂層欄位

| 欄位 | 說明 |
|---|---|
| `version` | 固定為 `1`，schema 版本號 |
| `repo_dir` | repo 根目錄路徑 |
| `integration_branch` | 整合分支名稱；所有頁面 branch 從這個分支的 HEAD 切出，完成後 fast-forward merge 回去 |
| `base_branch` | 最終要合併回去的正式分支（例如 `master`） |
| `limits` | `{ entry_max_files, entry_max_lines, checkpoint_max_modules, checkpoint_max_lines, module_timeout_min, module_budget_usd }`——單個 entry 允許的最大檔數/行數、多少模組或多少行累積後自動開一個斷點、單模組跑多久算超時、單模組預算上限。這組值由 runner 啟動時從環境變數寫入，skill 執行期只讀不寫 |
| `runner_state` | `{ state, reason, since, pid, host, consecutive_failures, last_digest_date, crash_signature, hold }`；`state` 是 `idle` \| `running` \| `waiting_quota` \| `paused_for_review` \| `paused` 之一。`last_digest_date` 是每日摘要通知（`daily_digest`）最後送出的日期（`YYYY-MM-DD`），用來避免同一天重送；由 runner 寫入，非人工填。`crash_signature`（1.1.0）是最近一次 runner 未預期例外的簽名 `<例外類別>@<檔>:<行>`，暫停原因不是 crash 時為 `null`；`hold`（1.1.0）為 `true` 表示同簽名例外已發生兩次、runner 鎖定，每次啟動在 pre-flight 之前就靜默退出，直到 `runner.py unblock --runner` 清掉 |
| `integration_tip_sha` | runner 每次 push 整合分支後寫入的 HEAD SHA。每次要處理新模組之前，runner 會把這個值跟遠端整合分支的實際 tip 比對；不同就代表有人在 runner 不知道的情況下動過整合分支，runner 會暫停並發通知，不會繼續往下處理。首次啟動時這個值是 `null`，runner 會直接把當下的遠端 tip 寫進來當基線 |
| `checkpoints[]` | 斷點清單，見下方「checkpoint 物件」 |
| `modules[]` | entry 清單，見下方「entry 物件」 |

## checkpoint 物件

| 欄位 | 說明 |
|---|---|
| `id` | 斷點識別碼 |
| `after` | `{ wave: N }`——這個 wave 的全部 entry 都變成 `done` 時觸發這個斷點 |
| `mode` | `soft`（開完 PR 繼續往下跑）或 `hard`（停下等待人工放行） |
| `pr_base` | 這個斷點對應的 PR 要開去哪個分支 |
| `title` | 斷點標題（給 PR 用） |
| `status` | `pending` \| `opened` \| `failed` \| `released` \| `merged` |
| `branch` | 這個斷點凍結出來的分支名稱 |
| `pr_url` | 對應的 PR 連結 |
| `opened_at` / `last_remind_at` | 時間戳 |

`hard` 斷點卡住時，靠外部下 release 指令來放行，不是靠人工直接改這個欄位。

## entry 物件（`modules[]` 的元素）

### 盤點期欄位（`import-inventory` 寫入）

| 欄位 | 說明 |
|---|---|
| `id` | entry 識別碼，格式 `<模組>-<sub\|main\|modals\|shared-xxx>` |
| `type` | `shared`（被多個頁面依賴的共用代碼）\| `page`（一個獨立頁面）\| `group`（真的分不開的互相引用組，**保留值**，見下）。`import-inventory` 的值域檢查（1.0.4 新增）只接受 `page`／`shared`，缺省視為 `page`；`group` 目前沒有對應的執行邏輯（Phase 0～Phase 4 都沒有分支處理它），帶 `type: "group"` 的盤點檔會被拒絕，需要先實作對應流程才能重新開放 |
| `members[]` | 只有 `type: group` 才有；把幾個綁在一起的模組各自的 `r15_paths` 合併列在這裡（`type: group` 目前被 `import-inventory` 拒絕，這欄暫時沒有作用中的消費者） |
| `wave` | 執行波次編號（0 起算）。這是 runner 取件時的**第一排序鍵**，但不取代 `depends_on`——同一 wave 內仍然要照 `depends_on` 排序，`wave` 只決定「大致上先做哪一批」 |
| `r15_paths[]` | 這個 entry 涵蓋的 R15 原始檔（repo 相對路徑），包含元件檔與這個頁面專屬的 action/reducer 檔。**可為空的唯一情況**：`type` 為 `page` 且 `route.kind == "sub"` 且 `shared_deps` 恰一筆且其 `r18_equivalent` 非 `null`（tab-reuse entry，見 `SKILL.md` Phase 0 (2)）；不符這三個條件的空陣列會被 `import-inventory` 拒絕 |
| `r18_dir` | 遷移後 R18 側的目標目錄。落點計算**以 `r18_dir` 本身判定，不看 `type`**：`r18_dir` 為 `r15-legacy/` 的 entry 只去掉 `frontend/react_15/`、保留完整相對路徑；其他任何 entry（不論 `type` 是 `page` 或 `shared`）落點 = `r18_dir` + `r15_path` 去掉 `frontend/react_15/<模組>/`。shared 層的檔（`frontend/react_15/` 下的 `components/`、`utils/`、`actions/`、`modules/`、`configs/`、`Modals/`，以及各模組的 `actions.js` 殼）一律填 `frontend/react_18/src/r15-legacy/`，與 R18 既有同名檔並存、不覆寫。跨 entry 的 import（消費檔在本 entry、被 import 的檔屬於另一個 entry）只要複製後相對路徑會改變，都已列進該 entry 的 `shared_deps`，`r18_equivalent` 即依上述規則算出的提供者落點；相對路徑不變（同根落點）的不列 |
| `route` | `{ kind, fe_config_prefix, r18_router_file, r15_entry }`：`kind` 是 `top`（獨立頁面）或 `sub`（某個頁面下的分頁 tab）；`fe_config_prefix` 是這個頁面在 R18 的路由開關 key；`r18_router_file` 是要加路由的 R18 router 檔；`r15_entry` 是這個頁面在 R15 端的進入點（供產出報告時對照，不是給程式讀的）；`switch`（選填，值域：省略，或 `static_list`——`import-inventory` 的值域檢查對其他值一律拒絕）：值為 `static_list` 表示這頁不走 featureSetting 開關、由 `feConfig.route.react_18` 靜態清單切換（給沒有登入 session 的頁面，見 route-and-flag.md §1.4）；`type: shared` 的 entry 此欄為空物件 `{}` |
| `feature_flag` | `{ key, default }`——這個頁面切換 R15/R18 用的開關名稱與預設值（預設一律 `false`，遷移完成、驗證過才手動打開）；`type: shared` 或 `route.switch: static_list` 的 entry 此欄為空物件 `{}` |
| `sidebar_entries[]` | 這個頁面對應的側邊選單條目；可以是空陣列 |
| `shared_deps[]` | `{ r15_path, r18_equivalent, note }`——這個 entry 依賴的共用檔案，及它在 R18 側已知的對應檔（basename 對不上、還沒查到對應檔的填 `null`）。`note`（選填）是給人讀的處置說明，`import-inventory` 原樣轉錄、skill 不解析它。被 shared entry 搬進 `r15-legacy/` 的共用檔，消費者也要列一筆、`r18_equivalent` 指向 legacy 落點——skill 靠這欄改 import，不自己推路徑 |
| `depends_on[]` | 這個 entry 依賴哪些其他 entry 的 `id`；runner 只有在列出來的依賴全部 `done` 之後才會排這個 entry。**這個欄位是盤點時人工填的，工具不會自動推導**，所以盤點時漏填等於 runner 排程時漏掉這個依賴關係 |
| `jira` | 對應的 Jira issue key |
| `branch` | 這個 entry 對應的頁面分支名稱（從整合分支 HEAD 切出）。由 `import-inventory` 依樣板 `<jira>/refactor/<BRANCH_USER>/<entry-id>` 產生，人工不填；`BRANCH_USER` 是 runner 的必填環境變數（見執行環境文件的 env 變數表） |

### 執行期欄位（只有 runner 寫）

| 欄位 | 說明 |
|---|---|
| `status` | `pending` \| `running` \| `waiting_quota` \| `done` \| `failed` \| `blocked` |
| `blocked_reason` | 卡住的具體原因。來源有兩種：skill 自己回報的八種（`inventory_incomplete` / `too_large` / `git_state` / `build_env` / `no_mapping` / `unsupported_ajax_field` / `build_failed` / `needs_human`，見下方 `result.schema.json`），以及 runner 在 L1 驗證與判讀時自己寫入的三種（`build_unverified`：runner 自跑 build 或啟動 smoke 失敗；`secret_detected`：diff 內掃到疑似憑證；`hook_denied`：CLI 輸出含 deny/permission 字樣）。人工 `unblock` 後才會回到 `pending` |
| `attempts` | 失敗計數：只在 error／timeout 累加（達上限轉 `failed`），blocked 不累加，`unblock` 歸零。**不是** `sessions/<entry>-<n>.*` 與診斷包名稱的 `<n>`——那是呼叫序號，由 runner 取「`attempts`+1」與「`sessions/` 內最大編號+1」的較大者，單調遞增，`unblock` 後重跑不會回頭覆寫舊的 session 檔（1.1.0） |
| `last_session_id` | 最後一次執行用的 session 識別碼 |
| `last_commit` | 最後一次 commit 的 hash |
| `last_error` | 最後一次失敗訊息 |
| `pr_url` / `pr_failed` | 這個 entry 對整合分支開的 PR 連結；開 PR 失敗時 `pr_failed` 設 `true` |
| `r15_hashes` | 這個 entry 涵蓋的每個 R15 原始檔在遷移當下的內容 hash，用於偵測「遷移完之後 R15 原始檔又被別的分支改過」這種情況 |
| `checkpoint_id` | 這個 entry 被哪個斷點凍結 |
| `started_at` / `finished_at` | 時間戳 |
| `cost_usd_total` | 這個 entry 累積花費——每一輪呼叫不論結果（done／blocked／error／timeout／等額度）都累加（1.1.0 起；之前只在 done 累加，失敗輪次的花費只留在 `cli_outcome` 事件） |
| `last_diagnostics` | （1.1.0）最近一次失敗自動凍結出來的診斷包，相對狀態目錄的路徑（例如 `diagnostics/<entry>-1-<時間>`）；判讀為 timeout／error／blocked／hook_denied／auth_expired 或 L1 沒過時寫入，`unblock` 後仍保留供回溯；手動 `diagnose` 產的包不寫這欄 |

## `result.schema.json`（skill 每次呼叫最後一則輸出；runner 用它強制 skill 輸出符合結構的結果）

```
{
  status: done | blocked | error | rate_limited,
  module,
  branch,
  commit: string | null,
  blocked_reason: inventory_incomplete | too_large | git_state | build_env | no_mapping | unsupported_ajax_field | build_failed | needs_human | null,
  build: { status: pass | fail | skipped, cmd },
  warnings_count,
  unverified_items: [],
  report_path,
  notes,
  failed_at: { phase: "0" | "1" | "2" | "3" | "4", step: string | null, file: string | null } | null
}
```

`rate_limited` 只在 skill 內部派工的 subagent 收到額度錯誤、且沒辦法完成任務時輸出；一般情況下額度用完是 CLI 直接失敗退出，這種情況由 runner 自己判讀退出碼，不會走到這個欄位。

`failed_at`（1.1.0）是失敗定位：`status` 為 `blocked`／`error` 時必填物件（`phase` 必填，`step`／`file` 查得到就填、查不到 `null`），`done`／`rate_limited` 一律 `null`。runner 原樣寫進診斷包的 `SUMMARY.md`，供統計哪個 Phase 最常失敗；同一份內容 skill 也會追加到 `<entry>-progress.md` 尾端的「## 失敗紀錄」表。

## 範例：`employeelist` entry

下面是一個實際填好的 entry，示範每個盤點期欄位對應到真實 repo 內容應該長什麼樣子。這個頁面在原始 R15 codebase 裡對應的路由是「員工管理 - 員工列表」，7 個程式檔、共 2373 行，分派在第 1 波（W1）執行。

```json
{
  "id": "employeelist",
  "type": "page",
  "wave": 1,
  "r15_paths": [
    "frontend/react_15/employeeList/actions.js",
    "frontend/react_15/employeeList/index.jsx",
    "frontend/react_15/employeeList/components/ButtonList.jsx",
    "frontend/react_15/employeeList/components/EmployeeTable.jsx",
    "frontend/react_15/employeeList/components/EmployeeShiftShortcut.jsx",
    "frontend/react_15/employeeList/components/EmployeeSettingModal.js",
    "frontend/react_15/employeeList/components/EmployeeCreateModal.js"
  ],
  "r18_dir": "frontend/react_18/src/pages/employeeList/",
  "route": {
    "kind": "top",
    "fe_config_prefix": "employee$",
    "r18_router_file": "frontend/react_18/src/routes/EmployeeRoute.tsx",
    "r15_entry": "employee (frontend/react_15/routes.js:84)"
  },
  "feature_flag": {
    "key": "employeeListR18",
    "default": false
  },
  "sidebar_entries": [
    "navItem: employee (frontend/react_15/configs/sidebarConf.js:439-440)"
  ],
  "shared_deps": [
    {
      "r15_path": "frontend/react_15/actions/settingAction.js",
      "r18_equivalent": null
    },
    {
      "r15_path": "frontend/react_15/actions/serviceItemAction.js",
      "r18_equivalent": "frontend/react_18/src/redux/actioncreators/serviceItemActionCreator.js"
    },
    {
      "r15_path": "frontend/react_15/utils/localStorageUtil.js",
      "r18_equivalent": "frontend/react_18/src/shared/utils/localStorageUtil.js"
    }
  ],
  "depends_on": [
    "shared-serviceitem-actions",
    "shared-localstorage-utility"
  ],
  "jira": "<JIRA-KEY>",
  "branch": "<JIRA-KEY>/refactor/<BRANCH_USER>/employeelist",
  "status": "pending",
  "blocked_reason": null,
  "attempts": 0,
  "last_session_id": null,
  "last_commit": null,
  "last_error": null,
  "pr_url": null,
  "pr_failed": false,
  "r15_hashes": {},
  "checkpoint_id": null,
  "started_at": null,
  "finished_at": null,
  "cost_usd_total": 0
}
```

欄位對照說明：

- `fe_config_prefix` 用 `employee$`（結尾錨定），不是裸字串 `employee`：因為這個模組的路由前綴判斷用的是無結尾邊界的字首比對，裸字串 `employee` 會連帶攔到 `employee/:id` 底下已經遷移完成的分頁，造成「關掉這個頁面的開關，反而讓已經上線的其他分頁退回舊版」的回歸。所有跟其他現存路徑有前綴關係的 `fe_config_prefix` 都要照這個規則加 `$`。
- `route.kind` 是 `top`，因為 `employeelist`（列表頁）跟 `employee`（單一員工的分頁詳細資料）是兩個不同的頁面模組，各自有自己的 entry；不要把列表頁誤標成某個分頁的 `sub`。
- `r18_router_file` 指到 `EmployeeRoute.tsx`，不是 `AppRouter.jsx`：R18 目前已經把 `/employee/*` 這整個路徑用萬用字元指到 `EmployeeRoute` 元件（在 `AppRouter.jsx` 裡註冊），所以「裸網址 `/employee`（列表頁）」實際上也會落到 `EmployeeRoute` 內部處理，要在這個檔案裡新增一個對應列表頁的路由，不是在 `AppRouter.jsx` 新增一條全新的頂層路由。
- `shared_deps` 裡 `settingAction.js` 的 `r18_equivalent` 是 `null`：R18 側找不到同名檔案（基於檔名比對抓不到），需要靠人工確認它的邏輯被合併進了哪個現有檔案，不能直接假設「沒找到同名檔=不需要處理」。
- `depends_on` 列的兩個 id 是共用檔案各自被抽出來的獨立 entry（因為 `serviceItemAction.js` 與 `localStorageUtil.js` 都是被多個頁面引用的共用檔案，要照「共用先抽」規則各自變成一個 `type: shared` 的 entry，排在依賴它的頁面 entry 之前跑）。
- `branch` 樣板是 `<jira>/refactor/<BRANCH_USER>/<entry-id>`：Jira 編號放最前面，是因為 commit message 規則要從分支名取票號；型別固定用 `refactor`，沿用既有 R18 升級分支的型別慣例；描述段用 entry id 而不是自由文字，是因為一張 Jira 票可能對應多個 entry，只有 entry id 能保證唯一。這跟斷點分支用 `<整合分支 id>/cp-<斷點 id>` 是不同的命名邏輯——斷點分支不掛 Jira 前綴，因為 runner 不會在斷點分支上產生 commit，沒有 commit message 要從分支名取票號的需求。
- 執行期欄位（`status` 以下）在這裡呈現的是 `import-inventory` 剛寫入、entry 還沒開始跑的初始狀態，不是執行完成後的樣子。
