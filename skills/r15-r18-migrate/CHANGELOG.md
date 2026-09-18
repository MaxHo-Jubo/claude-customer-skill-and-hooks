# CHANGELOG

## 1.1.0 (2026-09-18)

完整錯誤回報機制。部署到無人看管的機器之前，對 `helpers/runner.py` 的觀測盲區做一次盤點（9 項），最嚴重的兩項是「逾時被殺時 stdout 是空的」（`--output-format json` 只在結束時輸出）與「runner 未預期例外沒有 traceback、不進 paused，launchd 每次重啟都通知一次」。結構化輸出 schema 新增欄位（契約變更），版號升 minor。動 `helpers/runner.py`、新增 `helpers/diagnostics.py` 與 `helpers/stream_events.py`（stream-json 解析獨立成模組，runner 與 diagnostics 共用同一份解析器；依賴方向 runner → diagnostics → stream_events）、`templates/result.schema.json`、`templates/headless-rules.txt`、`templates/progress.template.md`、`SKILL.md`、`docs/environment.md`、`docs/queue-schema.md`。

- **CLI 改 `stream-json --verbose` 逐事件落檔**：`call_claude` 的 stdout 直接寫 `sessions/<entry>-<n>.stream.jsonl`（不進記憶體），逾時 TERM／KILL 後檔案仍保留到那一刻為止的所有事件；`parse_cli_payload` 改讀最後一筆 `result` 事件（`structured_output`／`session_id`／`total_cost_usd`／`permission_denials`／`terminal_reason`／`num_turns`），`STATUS:` fallback 改掃 `result` 文字與 assistant 文字；`REQUIRED_CLI_FLAGS` 加 `--verbose`（2.1.275 實測 `-p` 模式的 stream-json 需要它）。`sessions/<entry>-<n>.json` 改為 meta（returncode／逾時／耗時／stderr 尾端／stream 路徑與事件統計／`result` 事件全文）。
- **hook_denied 先看 `permission_denials`**：`judge_outcome` 在非零退出／`is_error` 時先看 `result.permission_denials` 是否非空，`HOOK_DENY_RE` 文字特徵降為備援；`cli_outcome` 事件加記 `terminal_reason`／`num_turns`／`permission_denials` 數／stream 路徑。
- **子行程全文落檔**：`run_command` 加 `log_path`，build／smoke／`npm ci`／基準分支 merge／斷點回流 merge／ff-merge／push／`gh pr create` 的完整 stdout＋stderr 寫到 `sessions/<entry>-<n>-<name>.log`；queue／通知的 detail 維持截尾段，但字尾附 `（全文: sessions/…）`。
- **runner 例外統一出口 `handle_runner_crash`**：traceback 全文寫 `crashes/<ts>-<簽名>.txt` 並印到 stderr，記 `runner_crashed` 事件（含簽名 `<例外類別>@<檔>:<行>`），走 `enter_paused(signature=…)` 而不是 raise。`enter_paused` 的去重條件加上「同簽名」；同簽名第二次出現設 `runner_state.hold`，之後每次啟動在 pre-flight 之前就靜默退出（連認證 smoke 都不呼叫），直到 `runner.py unblock --runner`；hold 是新狀態，即使算重複也通知一次。`runner_state` 新增 `crash_signature`／`hold`。
- **環境指紋**：`environment_fingerprint` 在每次 `run` 啟動時算一次（skill 版本、runner／diagnostics sha1、CLI 版本、模型、node、python、repo HEAD／分支、主機），寫進新的 `runner_started` 事件、`runner_started` 通知與每個診斷包；`module_started` 事件加記 `branch`／`repo_head`。
- **失敗當下自動凍結診斷包（新模組 `helpers/diagnostics.py`）**：判讀為 timeout／error／blocked／hook_denied／auth_expired、以及 L1 非 done 時，先呼叫 `freeze_entry_bundle` 把該次呼叫的 stream（gzip）、meta、子行程 log、progress／contract／report、queue entry 快照、runner 事件切片複製到 `diagnostics/<entry>-<n>-<ts>/`，並產給 Claude 讀的 `SUMMARY.md`（呼叫概況、環境指紋、結構化結果、tool_use→tool_result 時間軸含 subagent 縮排、全部 `is_error` 結果、`permission_denials`、最後 10 個事件、stderr 尾端、progress 勾選與失敗紀錄、smoke 的 `[ignored:*]`／FAIL 行、runner 事件）。每個 paused 也產 runner 級診斷包（`runner_state`、traceback、最近 200 筆事件、queue.json 原檔複本——即使損毀）。`SUMMARY.md` 內命中 `SECRET_PATTERN_LABELS` 的行整行換成 `[REDACTED:<類別>]`，原檔複本不遮罩，目錄權限 700。entry 新增執行期欄位 `last_diagnostics`；`diagnostics/` 與 `crashes/` 不受 `SESSIONS_RETENTION_DAYS` 清理。
- **通知指路**：`module_blocked`／`module_failed`／`paused`／`runner_crashed` 的內文第一行改為 `診斷: diagnostics/<名稱>`，300 字元截斷時路徑一定在；`status --verbose` 與 `PROGRESS.md` 待人工事項也列出。
- **新子命令 `diagnose`**：`diagnose <entry> [--attempt N]`、`--all-failed`、`--runner`、`--tar`，手動（重）產診斷包；只讀 queue 不寫。`--attempt` 預設取 `sessions/` 內最大編號（blocked 不累加 `attempts`，不能從 queue 推）。
- **呼叫序號與 `attempts` 脫鉤**（fresh-context 實跑驗收抓到）：`sessions/<entry>-<n>.*` 與診斷包名稱的 `<n>` 原本直接用 `attempts+1`，`unblock` 把 `attempts` 歸零後下一輪會回頭覆寫 `<entry>-1.*`，`diagnose` 預設的「最大編號」也不再是最新一次。新增 `next_call_number`：取「`attempts`+1」與「`sessions/` 內最大編號+1」的較大者，序號單調遞增；`queue.attempts` 維持純失敗計數。`docs/queue-schema.md` 的 `attempts` 列與 `docs/environment.md` 的 `runner.log.jsonl` 列同步說明。
- **`cost_usd_total` 每輪都累加**（同一輪驗收 BONUS）：原本只在 done 累加，blocked／error／timeout／等額度那幾輪燒掉的錢只留在 `cli_outcome` 事件、entry 帳面低估。抽 `add_cost` helper，四個寫回點（等額度、blocked、error、done）共用。
- **skill 契約**：`result.schema.json` 新增必填 `failed_at`（`null` 或 `{ phase: "0"–"4", step, file }`，blocked／error 必填物件）；`templates/progress.template.md` 尾端新增 `## 失敗紀錄` 表；`SKILL.md` §7 新增「失敗定位」兩條、§8 補規則與範例；`templates/headless-rules.txt` 第 2 條補句。
- **文件**：`docs/environment.md` 旗標清單補 `--verbose`、狀態目錄表補四列、launchd 段補 crash 去重與 hold、新增「出錯時怎麼做」小節；`docs/queue-schema.md` 補 `runner_state.crash_signature`／`hold`、`last_diagnostics`、`failed_at`。

## 1.0.4 (2026-09-17)

fresh-context 驗收在 inventory 產出階段抓到 5 個零檔 R15 tab（子頁直接渲染別的模組已遷移的元件，R15 端沒有專屬元件檔）用殼檔占位、照現行規則會被誤判成一般子頁而卡在 Phase 0 (2)；同一輪驗收另外抓到 3 處文件錯與一個值域漏檢查，一併修正。只動 `SKILL.md`、`docs/queue-schema.md`、`docs/route-and-flag.md`、`docs/redux-mapping.md`、`helpers/runner.py`。

- **tab-reuse entry（零檔 tab）**：新增第三種允許 `r15_paths` 為空的情況——`type: page` 且 `route.kind == "sub"` 且 `shared_deps` 恰一筆且 `r18_equivalent` 非空。`SKILL.md` Phase 0 (2)(3) 定義例外條件、Phase 1 補合約抽取做法（不派三群 agent，只填元件表一列 + shared_deps 對照）、Phase 2 步驟 1/2 整個跳過、步驟 3 補 Route element 來源（`shared_deps[0].r18_equivalent`）、步驟 4/6 補對應做法、Phase 3(a)(b)(c) 補跳過/縮減範圍規則、Phase 4 commit message 補 `FeaturePath` 取法。`docs/route-and-flag.md` §4 新增 4.5「tab-reuse（零檔 tab）」小節，列出 5 個已知實例（daycase 3.2/3.3/6/14、employee 2）的 R15 content 殼座標與渲染的元件檔，行號對 master 核對過。`docs/queue-schema.md` 的 `r15_paths[]`／`shared_deps[]`（補選填 `note` 子欄位）同步更新。
- **`helpers/runner.py` 值域檢查**：`cmd_import_inventory` 新增 `is_tab_reuse_entry()` helper 與 STEP 05（`type` 只接受 `page`／`shared`，`route.switch` 只接受省略或 `static_list`，違規逐筆列出 entry id 與實際值後 exit 1，值域抽成模組層具名常數 `ENTRY_TYPE_VALUES`／`ROUTE_SWITCH_STATIC_LIST`）；原 STEP 06（今 STEP 07）的空 `r15_paths` 檢查改為只在 `is_tab_reuse_entry()` 為真時放行，否則沿用原錯誤並附加提示文字；後續 STEP 全數 +1 重排。
- **`docs/queue-schema.md` 的 `type` 欄位補值域說明**：`group`（連同 `members[]`）維持為保留值，但補上一句事實——Phase 0～Phase 4 目前都沒有分支處理它，`import-inventory` 新加的值域檢查會拒絕 `type: "group"`，需要先實作對應流程才能重新開放。
- **`docs/redux-mapping.md` 補 R18 redux 註冊檔小節**：新增列出 `redux/actions.js`／`reducers/index.js`／`sagas/index.js`／`IReducerState.tsx` 四個檔案的用途（各檔內容以 master 核對過）；`SKILL.md` §0 對這四個檔的出處從 `docs/route-and-flag.md` 改指向 `docs/redux-mapping.md`——這四個檔案的職責（action type 群組鍵、reducer 註冊、saga 註冊、state 型別）與 `route-and-flag.md` 描述的路由開關三層無關，原文誤植出處。
- **`docs/route-and-flag.md` §4.4 措辭修正**：`f16b6d6f3e` 對 `frontend/react_18/src/pages/case/GCodeStatSetting.tsx` 的描述改成「該範本 commit 內的 R18 落點（不在 master，僅供對照做法）」——原文「R18 頁面本體微調」讓人誤以為這是現行 master 上的程式碼，但該 commit 本身不在 master。
- **落點規則改成不看 `type`**：`SKILL.md` 步驟 2 與 `docs/queue-schema.md` 的 `r18_dir` 欄位說明統一改成「落點計算以 `r18_dir` 本身判定，不看 `type`」，並補一句 `shared_deps` 列出規則的事實（消費檔的 import 複製後相對路徑會變才列進 `shared_deps`，`r18_equivalent` 即依落點規則算出的提供者落點；同根落點不列）——inventory 出現 `type: shared` 但落點在 `pages/...` 模組內共用的 entry（例如模組內共用工具、活動共用邏輯），原「page entry／`r15-legacy/` legacy entry」二分對它沒有定義。

## 1.0.3 (2026-09-17)

產 inventory 時發現 `docs/route-and-flag.md` §6 的前綴規則有一個未涵蓋的情境，只補文件、不動程式。

- **§6.1 步驟 4**：碰撞檢查原本只對 `routes.js` 的 path 做前綴比對，補上 `sheetRoutingConfig.js` 的 subPathname——子頁 tab 的碰撞來源是後者不是前者。
- **§6.2 新增第四列**：同模組兩個 subPathname 互為前綴（`employee` 群組的 `leaveRecord` 與 `leaveRecordByShifts`）時，「完整 subPathname 不加錨」會把另一個 tab 一起攔走，`$` 錨又比對不到真實的 `/<id>` 路徑，定案用尾斜線（`employee/leaveRecord/`）。原第三列的理由補上前提條件。
- **SKILL.md**：frontmatter `version` 同步為 `1.0.3`。
- **SKILL.md Phase 0 (2)／步驟 3**：`type: shared` 的 entry 免驗 `route`／`feature_flag` 並整個跳過步驟 3——shared entry 從拆分規則定案起就存在，但輸入契約一直把頁面欄位當成全部 entry 必填，照原文跑會把每一個 shared entry 判成 `inventory_incomplete`。
- **`route.switch: static_list`**：新增靜態清單切換模式，給沒有登入 session 也要拿到 R18 bundle 的頁面用（後端的 featureSetting 判斷只在有 session 時執行，靜態清單判斷不看 session）；步驟 3 改寫 `feConfig.route.react_18`、不建 flag、R18 route 不包 guard。`docs/queue-schema.md` 兩欄與 `docs/route-and-flag.md` §1.4 同步。
- **SKILL.md 步驟 2 不覆寫守衛**：`r15_paths` 複製到 R18 落點時，目標路徑已有同名檔一律不覆寫、改 `blocked(needs_human)` 並在 `notes` 列出撞到的檔。產 inventory 時發現 shared 層有多個檔在 R18 同相對路徑已存在（例如 `components/AlertMessage.js`、`components/Datepicker.js`），照原步驟 2 會直接蓋掉 R18 正在用的元件，而且 build 不會紅。
- **落點規則明文化＋`r15-legacy/`**：步驟 2 補落點計算方式（page entry 去掉 `frontend/react_15/<模組>/`、legacy entry 只去掉 `frontend/react_15/` 保留完整相對路徑；原文「相對路徑原樣對映」沒說相對於什麼）；shared 層搬過來的檔一律落在 `frontend/react_18/src/r15-legacy/`，與 R18 既有同名元件並存，消費者靠 `shared_deps.r18_equivalent` 指到 legacy 路徑。Phase 3(c) 對 `shared_deps` 逐項回填 `R18 對應／等價`——原本只回填 entry 自己檔案的合約列，共用依賴的介面差異（例如 R18 `AlertMessage` 沒有 `clean`／`fail` prop）沒有任何步驟會比。`docs/queue-schema.md` 的 `r18_dir`／`shared_deps` 兩欄同步。

## 1.0.2 (2026-09-16)

fresh-context 實跑驗收（V3）找到 `boot-smoke.cjs` 網路類 console error 用 regex 忽略清單的 3 個缺陷，改成由 Playwright 結構化事件（`response`/`requestfailed`）依 URL 路徑判定；驗收過程中發現舊判準的寬鬆退回機制意外掩蓋了另一個結構性缺口，一併修正。只動 `helpers/boot-smoke.cjs`、`helpers/runner.py`（`run_smoke` 與新常數）、文件、`SKILL.md` 的 `version` frontmatter。

- **V3-1（真 404 不可達）**：`startStaticServer` 原本對任何不存在的路徑一律回退 index.html／合成 app shell（200 + HTML），從不回真 404，導致 `IGNORED_ERROR_PATTERNS` 裡 `RESOURCE_LOAD_FAILURE`／`HTTP_STATUS_ERROR` 兩個 regex 在 `--dist` 模式下永遠不會被觸發；缺資產實際會以瀏覽器把 HTML 誤當成 JS 解析的 `pageerror: Unexpected token '<'` 失敗，訊息完全誤導、看不出真正缺了哪個檔案。改成：後端前綴回真 404（JSON body）、有副檔名的缺檔回真 404、只有無副檔名路徑才走 SPA fallback；同時新增 `response`/`requestfailed` 監聽把網路層失敗交給 `judgeNetworkFailure` 依 URL 路徑判定，失敗訊息改成明確的 `resource: GET <path> → 404`。
- **V3-2（regex 過度寬鬆吞真錯誤）**：`API_AUTH_ENDPOINT_FAILURE` 的 regex `/\/(api|auth)\/[^\s'")]*.*\b(fail|error|reject)/i` 只要訊息裡出現 `/api/`或`/auth/` 加上 fail/error/reject 字樣就整句吞掉，會把「呼叫 `/api/case/list` 時發生的 TypeError」這類真正的程式錯誤也判成網路雜訊而 fail-open（exit 0）。改成：忽略與否不再用文字內容猜測，而是由 `response`/`requestfailed` 事件依「URL pathname 是否命中 `/api/`、`/auth/` 前綴」判定；console error 只剩一種例外（瀏覽器自身回聲的 `Failed to load resource` 開頭訊息，已由網路事件判過），其餘 console.error 一律算失敗，不會再誤吞 app 自己印的錯誤訊息。
- **V3-3（風格缺口）**：新函式 `classifyIgnoredConsoleError` 沒有 `STEP XX:` 註解，與既有函式 100% 至少含一個 STEP 註解的慣例不符。該函式已隨 V3-1/V3-2 的重構整個移除，替代它的 `isBackendEndpointPath`、`judgeNetworkFailure`、`resolveStaticFile` 皆補上 JSDoc 與 STEP 註解。
- **V3 追加發現（手足靜態資源缺口）**：實作 V3-1 的真 404 判定後，對真實 production build（`dist-prod`）跑 smoke 從原本的 exit 0 變成 exit 1，唯一失敗是 `resource: GET /locales/lang/zh-TW/common.json → 404`。查證：`frontend/react_18/src/i18next.js:47` 的 `loadPath` 打 `${DEPLOY_PREFIX}/locales/lang/zh-TW/{{ns}}.json`，實體檔只在 `backend/public/locales/`，是 `backend/public/build/react18/`（`--dist` 唯一掛載的靜態根）的手足目錄，不在、也不會在 vite build 產物內——這個 404 舊版本來就存在，只是被舊的「缺檔一律回退 index.html」蓋住而從未被看見。因為這是任何 production build 都會踩到的結構性缺口（不是這次 fixture 特有），加 `--static-root <目錄>`（可重複）讓靜態伺服器同時服務多個唯讀根目錄（`resolveStaticFile` 依序尋找，dist 永遠優先、SPA fallback 只認 dist 的 index.html），`runner.py` 的 `run_smoke` 固定多帶一個指向 `backend/public` 的 `--static-root`。
- **docs/environment.md**：判準描述同步改寫為「pageerror／console error 一律失敗（唯一例外是網路事件已判過的瀏覽器回聲），網路失敗依 URL 路徑判、只忽略 `/api/`、`/auth/`」，並補一段說明 `--static-root` 與 `locales/` 手足目錄缺口。
- **SKILL.md**：frontmatter `version` 同步為 `1.0.2`。

## 1.0.1 (2026-09-16)

fresh-context 實跑驗收（R2-B）找到的 8 個 runner 缺陷與 3 個文件缺口修正（R8 為驗收後追加），只動 `helpers/runner.py`、文件、與 `SKILL.md` 的 `version` frontmatter，不動 `boot-smoke.cjs`/`run_smoke`。

- **R1**：首次啟動的 `runner_started` 通知一律印「基線 SHA: None」——`preflight()` 在 pre-flight 的 `git ls-remote` 那步（原本只用來確認遠端整合分支存在）就先留住 SHA，`integration_tip_sha` 還是 `null` 時直接寫入當基線，通知才讀得到值；`module_preflight()` 原本的寫入邏輯保留當防禦，正常路徑不會再觸發。
- **R2**：`paused` 去重的旗標 `resumed_pause_reason` 在模組真正執行前就被清空，對「模組執行後才觸發的暫停原因」（如 `auth_expired`）去重失效，重啟會多送一則內容不實的「已解除」通知並再呼叫一次 skill。改用整個 process 生命週期不清除的 `startup_paused_reason` 判斷是否重複；「已續跑」通知延後到第一個模組真的 `done` 才發（`finish_done_entry`），措辭為「先前的暫停原因 X 已確認解除（模組 Y 完成）」——只在模組真的完成後才發，是有證據的陳述；重啟當下不再發任何「已解除」通知。
- **R3**：`import-inventory` 沒有檢查 `wave` 的值域，非 0–5 整數（含超出範圍或字串）會原樣寫入 queue。新增值域檢查，違規逐筆列出 entry id 後 exit 1。
- **R4**：`queue.json` 損毀（`queue_corrupt`）只印錯誤、exit 2，沒有通知，且重啟後無法判斷是否為同一問題。改走 `paused(queue_corrupt)` 通知一則 + exit 3；因 queue 本身讀不到，去重改看 `runner.log.jsonl` 最後一筆狀態事件（跳過 notify 系列的投遞紀錄）。
- **R5**：secret 掃描命中的原始內容（含憑證片段本身）被寫進 `queue.json` 的 `last_error` 與 `runner.log.jsonl`，違反 LOG-SAFETY。改成只記「檔名:行號 + 樣式類別名」（如 `github-token`），不再記命中片段或整行；行號改用 diff hunk 標頭換算成新檔的實際行號。
- **R6**：`master_conflict` 與 `deps_install_failed` 的 detail 常是空字串或被硬截斷——`master_conflict` 在 `git merge --abort` 之前先問一次 `git diff --name-only --diff-filter=U`，記下衝突檔名；`deps_install_failed` 改記 `npm ci` 合併後 stdout+stderr 的末 20 行（原本只截 stderr 或硬切 300 字元）。
- **R7**：pre-flight 只驗 4 個 CLI 旗標，但組指令時實際用了 8 個（另外 4 個是 `--model`/`--output-format`/`--disallowedTools`/`--append-system-prompt`），兩份清單會分歧。收斂成同一份常數 `REQUIRED_CLI_FLAGS`，pre-flight 檢查與 `build_claude_command` 組指令都讀這份清單。
- **R8**：`preflight()` 的認證 smoke 偵測到 `auth_expired`、磁碟空間偵測到 `disk_low` 時只印 stderr 就 exit 2，不是 paused，也不通知——配合 launchd `KeepAlive`+`ThrottleInterval`，token 到期後 runner 會每隔幾分鐘靜默重試、永遠沒人知道。這兩項改走 `enter_paused`（通知一則 + exit 3），去重沿用既有的 queue.runner_state 檢查（這兩項在 `cmd_run` 把 runner_state 改成 running 之前就會觸發，查得到上一輪留下的 paused 狀態，不需要、也還沒有 `startup_paused_reason` 可用）；`enter_paused` docstring 補三層去重機制的完整說明。其餘 pre-flight 失敗（lock 被活行程持有、狀態目錄未被 git 忽略、CLI 旗標缺、遠端無整合分支）維持 exit 2 印錯誤，這些是部署當下就會被人看到的設定錯誤。
- **docs/environment.md**：旗標實測清單補齊 8 個（與 R7 同一份清單）；「整合分支守則」補一行 `runner.py unblock --integration-tip` 的解除手段；「launchd 常駐與重啟行為」補一段說明 `R15_R18_MIGRATE_ENV` 是 bootstrap 變數、優先序、以及為何不寫在 env 檔內；同段補一句提醒 exit 2 類 pre-flight 失敗不發通知、首次 `launchctl load` 後要看 `StandardErrorPath`（R8）。
- **SKILL.md**：frontmatter `version` 同步為 `1.0.1`。
- **docs/queue-schema.md**：`runner_state` 補上已實作但先前沒列的 `last_digest_date` 欄位。
- **templates/r15-r18-migrate.env.example**：檔頭補註解說明 `R15_R18_MIGRATE_ENV` 的角色與優先序，並註明它不是本檔內的變數。

## 1.0.0 (2026-09-16)

首版。把「R15 頁面以最小改動遷移到 R18」這件事收斂成一個可在無人看管模式下逐 entry 呼叫的 skill。

- **SKILL.md**：`/r15-r18-migrate <entry-id> [--resume]` 主流程。
  - 硬性不變量：保留 class、不轉 hooks / TS、命名沿用 R15、機制沿用 R18、註解逐字照搬、R15 檔不刪。
  - 流程邊界：不切分支、不 push、不開 PR、不跑後續審查；`git add` 範圍限本 entry 與列舉的共用註冊檔。
  - Phase 0 輸入契約五項檢查（entry 存在、必要欄位、規模上限、git 狀態、`--resume` 判定），缺欄位一律 blocked，不 grep 補全。
  - Phase 1 合約抽取：三群分法、每群 ≤ 4 檔、subagent 平行、agent prompt 內嵌本檔、主流程親自核對 action 對應與 success 副作用。
  - Phase 2 六步機械轉換（Redux → 元件 → 路由開關 → 註解 → 建置 → 無對照盤點），含逐條禁止事項。
  - Phase 3 等價性驗證 (a) 差異測試 (b) 靜態比對 (c) 合約表回填 (d) 頁面 E2E（無環境則列 unverified，禁止假 PASS）。
  - Phase 4 收尾：逐行讀 diff 自檢清單、固定格式 commit message、產報告、輸出結構化結果。
  - blocked 八種列舉、結構化輸出規則與 `STATUS:` fallback 行、resume 速查表、九個會靜默壞掉的地方。
- **templates/progress.template.md**：四個 Phase 勾選清單（Phase 2 六步各一個 checkbox）+ 頂部 metadata 行，供 resume。
- **templates/contract.template.md**：四張合約表（逐函式 / action / reducer / 元件）、每列 `路徑:行號` 來源欄、主流程核對結論區、⚠ 清單與 `R18 對應 | 等價` 回填欄。
- **templates/report.template.md**：合約回填摘要、⚠ 清單、unverified_items、build 結果（指令 + 末 5 行）、差異測試三欄、頁面 E2E 有無執行、供 PR body 的統計行。
- **templates/queue.template.json**：queue.json 完整頂層骨架（`limits` 六欄、`runner_state`、`integration_tip_sha`、一個 checkpoint 範例、一個含全部靜態與執行期欄位初始值的 entry 範例），值一律佔位。
- **templates/result.schema.json**：JSON Schema draft-07，`status` 四種、`blocked_reason` 八種 + null、`build`、`warnings_count`、`unverified_items`、`report_path`、`notes`；`additionalProperties: false`。
- **templates/headless-rules.txt**：給 `--append-system-prompt` 的無人看管守則（不得提問、無法決定即 `needs_human`、禁用指令清單與敏感檔禁讀清單、禁止假 PASS）。
- 細則不寫進 SKILL.md，改以相對路徑引用 `docs/` 六份文件（api-mapping / redux-mapping / route-and-flag / contract-extraction / queue-schema / environment）。
