---
name: r15-r18-migrate
description: 把一個 React 15 頁面 entry 以最小改動遷移到 React 18（保留 class、不轉 hooks、命名沿用 R15、機制沿用 R18），一次處理一個 entry 並產出 commit 與結構化結果；觸發語 `/r15-r18-migrate <entry-id> [--resume]`。
version: 1.1.0
---

# R15 → R18 最小改動遷移（單 entry）

`$ARGUMENTS` = `<entry-id> [--resume]`

本 skill 一次只處理 `queue.json` 裡的一個 entry，在**目前所在分支**完成遷移並 commit，然後輸出一則結構化 JSON 結果。分支切換、合併、推送、開 PR、建置複驗、通知全部由外層排程程式（runner）負責，本 skill 一律不做。

執行環境是無人看管的 headless 模式：沒有人會回答問題，任何猶豫都必須收斂成 `blocked`，不能靠猜。

本輪流程總覽（每一格做完就更新 progress 勾選）：

1. **Phase 0 輸入契約** — 讀 entry、驗欄位、算規模、驗 git 狀態、處理 `--resume`。
2. **Phase 1 合約抽取** — 三群 subagent 平行抽表，主流程親自核對 action 對應與 success 副作用。
3. **Phase 2 遷移實作** — 六個步驟固定順序：Redux → 元件 → 路由開關 → 註解 → 建置 → 無對照盤點。
4. **Phase 3 等價性驗證** — 差異測試、靜態比對、合約表回填、頁面 E2E（可選）。
5. **Phase 4 收尾** — 逐行讀 diff → commit → 報告 → 結構化輸出。

任一格判定 blocked 就停在該格，保留已完成的工作，輸出結構化結果結束本輪。

## 0. 硬性不變量（違反即視為本輪失敗）

遷移方式：

- **保留 class component**，不轉 functional、不轉 hooks、不轉 TypeScript；檔案副檔名沿用 R15（`.js` 保持 `.js`，`.jsx` 保持 `.jsx`）。
- **命名沿用 R15**：action 常數 identifier 與字串、reducer 檔名與函式名、state 欄位名、action creator 函式名一律照搬，不加前綴。
- **機制沿用 R18**：saga 基礎層（`baseSaga` / `api.js` / `actionCreator`）零改動，照 R18 既有樣板接線。
- **註解逐字照搬**：不補 STEP 註解、不補 JSDoc、不修錯字、不重排；原本沒有註解的就沒有。
- 所有**建立或修改**的檔案，檔頭 `Modified` 欄位加一行 `YYYY/MM/DD <執行者>`。
- 禁止順手重構、禁止改名、禁止換套件（例如把 moment 換掉）、禁止調整與本次無關的檔案。
- **R15 檔案一律不刪**，`frontend/react_15/routes.js` 一行都不改。回退手段是把 feature flag 關回 `false`。

流程邊界：

- 不執行 `git checkout` / `switch` / `merge` / `rebase` / `push` / `reset` / `restore` / `stash` / `clean` / `cherry-pick` / `worktree` / `commit --amend`，不執行 `gh pr merge|close`、不執行 `rm -rf`。**絕不做任何丟棄未 commit 變更的動作。**
- 不 push、不開 PR、不跑任何後續的自動審查流程。
- 不讀取 `.env*`、`.npmrc`、`local-test/**`、`applicationConf*.json`；報告與 commit message 只寫路徑與統計，不貼檔案內容。
- `git add` 範圍只有兩類：(a) 本 entry 的 `r15_paths` 對應的 R18 落點與 `r18_dir` 底下的檔；(b) 共用註冊檔——`docs/route-and-flag.md` 列出的 `backend/routes/index.js`、`backend/const/companyDefault.js`、`entry.route.r18_router_file`、`frontend/react_18/src/routes/AppRouter.jsx`、三份 `sidebarConf.js`（僅 `sidebar_entries` 非空時）；`docs/redux-mapping.md` 列出的 R18 redux 註冊檔（`redux/actions.js`、`reducers/index.js`、`sagas/index.js`、`IReducerState.tsx`）；以及子頁 tab 需要的 R15 header／content 兩處改動。其餘檔案一律不進 staging。
- 不得提問。無法決定就 `status=blocked` + `blocked_reason=needs_human`，在 `notes` 寫清楚卡在哪個檔案、哪一列合約表、需要什麼資訊。
- 以上兩段與 `templates/headless-rules.txt`（runner 用 `--append-system-prompt` 帶入）內容一致；兩邊若有出入，以本檔為準。

## 1. 狀態目錄

狀態目錄從環境變數 `MIGRATION_STATE_DIR` 讀取；未設定時預設為 `$HOME/r18-migration-state/<repo 目錄名>/`。本文其餘部分以 `${MIGRATION_STATE_DIR}` 代表它。

| 檔案 | 讀/寫 | 用途 |
|---|---|---|
| `${MIGRATION_STATE_DIR}/queue.json` | **只讀** | entry 清單與 `limits`。這是 runner 的狀態真值，skill 一個位元都不准寫 |
| `${MIGRATION_STATE_DIR}/<entry>-progress.md` | 讀寫 | 階段勾選；resume 的依據。範本 `templates/progress.template.md` |
| `${MIGRATION_STATE_DIR}/<entry>-contract.md` | 讀寫 | 四張合約表。範本 `templates/contract.template.md` |
| `${MIGRATION_STATE_DIR}/<entry>-report.md` | 寫 | 完成報告。範本 `templates/report.template.md` |
| `${MIGRATION_STATE_DIR}/diff-tests/<entry>/*.test.js` | 寫 | Phase 3(a) 差異測試，**不進 repo** |

每個 Phase（Phase 2 為每個步驟）一做完就立刻更新 `<entry>-progress.md` 的勾選。做到一半不要先勾——resume 會從第一個未勾項往下做，勾錯等於跳過。

細則文件（全部以相對路徑引用，不要把內容複製進本檔）：

- `docs/queue-schema.md` — queue.json 欄位定義與範例 entry
- `docs/contract-extraction.md` — 四張合約表格式、分群規則、Phase 3(b) 靜態比對檢查表、回填格式
- `docs/redux-mapping.md` — Redux 對照規則（命名、樣板、欄位對照表、reducer 改寫、併發）
- `docs/api-mapping.md` — 第三方 API 對照（react-bootstrap、表格、react-select、router、React 15→18、樣式、i18n）
- `docs/route-and-flag.md` — 路由開關三層（後端前綴、機構預設、R18 guard）、子頁 tab、flag 命名、前綴碰撞、sidebar
- `docs/environment.md` — 環境需求與狀態目錄佈局

## 2. Phase 0：輸入契約（五項檢查，任一不過就結束本輪）

**(1) 讀 entry**：從 `${MIGRATION_STATE_DIR}/queue.json` 取 `modules[]` 中 `id == <entry-id>` 的元素與頂層 `limits`（欄位定義見 `docs/queue-schema.md`，骨架見 `templates/queue.template.json`）。找不到 entry → `blocked(inventory_incomplete)`。

**(2) 驗必要欄位**：`r15_paths[]`（非空；**唯一例外**：`type` 為 `page` 且 `route.kind == "sub"` 且 `shared_deps` 恰一筆且其 `r18_equivalent` 非 `null` 時可為空陣列，稱 **tab-reuse entry**——R15 的 tab 直接渲染其他 entry 已搬的元件，本 entry 只做路由與開關；不符這三個條件的空陣列 → `blocked(inventory_incomplete)`）、`r18_dir`、`shared_deps[]`（每一項都要有 `r15_path`，且 `r18_equivalent` 欄位存在——值可以是 `null`，但欄位不能缺）、`jira`、`branch`；**`type` 為 `page` 時另加** `route.kind`、`route.fe_config_prefix`、`route.r18_router_file` 與 `feature_flag.key`（`route.switch` 為 `static_list` 時 `feature_flag` 應為空物件，不驗 `key`）。`type` 為 `shared` 的 entry 沒有頁面也沒有開關，`route`／`feature_flag` 為空物件 `{}` 是正常的，不驗。任一缺漏 → `blocked(inventory_incomplete)`。
**不要自己 grep 補全**。盤點是人工職責，skill 補出來的欄位沒有人複核過，等於把錯誤靜默寫進遷移結果。

**(3) 算規模**：`wc -l` 算 `r15_paths` 的檔數與總行數，與 `limits.entry_max_files`、`limits.entry_max_lines` 比。任一超限 → `blocked(too_large)`，`notes` 寫實際數字與上限，供人工重新拆分。tab-reuse entry 的 `r15_paths` 是空陣列，檔數與行數都是 0，這是合法值，不算超限。

**(4) 驗 git 狀態**：
- `git branch --show-current` 必須等於 `entry.branch`，不等 → `blocked(git_state)`（分支是 runner 準備的，skill 不切換）。
- `git status --porcelain` 為空，或所有髒檔都落在本 entry 的路徑範圍內（`r18_dir` 底下、或 §0 允許的共用註冊檔）。有範圍外的髒檔 → `blocked(git_state)`，`notes` 列出檔名。

**(5) `--resume` 判定**（帶此旗標時才做，順序不可調換）：
1. 先跑 `git log <integration_branch>..HEAD --oneline`。**只要本分支已經有本 entry 的 commit**，就直接跳到 Phase 3，不重做 Phase 1–2。（重做會讓共用註冊檔出現重複行，這是最貴的失敗模式。）
2. 沒有 commit → 讀 `<entry>-progress.md`，從第一個未勾的項目往下做；progress 檔不存在就當作全新一輪，從 Phase 1 開始。
3. progress 全勾但沒有 commit → 重跑 Phase 4（只補 commit 與報告，不重做前面）。

沒帶 `--resume` 時：若 `<entry>-progress.md` 已存在，覆寫成新一輪（`attempt` +1），但 §0 的「不重複改共用註冊檔」仍然適用——動手前先 `git diff` 確認註冊檔是否已經被改過。

## 3. Phase 1：合約抽取

目的是在動手改程式碼之前，把 R15 原始檔的行為窮舉成表格，作為 Phase 2 機械轉換與 Phase 3 等價比對的依據。格式與欄位語意見 `docs/contract-extraction.md`。

**分群**（三群，每群最多 4 個檔案，超過就在同一群語意下再切一個 subagent）：

| 群 | 涵蓋 | 產出 |
|---|---|---|
| 元件檔 | 主元件、子元件、Modal 元件 | 逐函式表、元件表 |
| action + reducer 檔 | action creator、reducer、middleware 觸發點 | 逐函式表（限 action creator）、action 表、reducer 表 |
| 第三方 API 掃描 | 用到第三方元件的檔案 | 元件表「第三方元件用法」欄 + 用到的 props/方法清單 |

三群平行派工。以下 prompt 逐字使用，只代入 `{分群角色}` / `{必讀檔案}` / `{輸出表格}` 三個變數：

```
你是 R15→R18 最小改動遷移的合約抽取 agent，負責「{分群角色}」這一群。

## 任務
逐一分析以下檔案，把它們的實際行為抽成結構化表格，供後續機械轉換與等價性比對使用。
你的產出是素材，不是結論——不要下任何「這樣改沒問題」「這兩者等價」之類的判斷。

## 必讀檔案
{必讀檔案列表，每個檔案給完整路徑；若該檔案在目前 checkout 分支已被刪除或修改，改用
`git show <base>:{path}` 取得遷移前版本，並在該檔案的表格列註明取得方式}

## 輸出格式（嚴格遵守，缺欄位視為未完成）
{輸出表格：依所屬群別，從下列四張表選對應的表格全文貼上表頭，逐列填寫}

- 逐函式表：函式 | 輸入（params / 讀取的 props·state·refs） | 輸出（return / setState 欄位 / dispatch / callback / DOM 副作用） | 呼叫者
- action 表：type | url | method | data 形狀 | query | headers | file 欄位 | callback / dispatch / redirect / lastExcutionFunction
- reducer 表：欄位 | 型別 | 初始值 | 哪些 case 修改
- 元件表：props | state | lifecycle | handlers | refs | 第三方元件用法

## 規則
1. **每一列都要附來源**：在該列末尾或獨立欄註明 `路徑:行號`，行號取該行為最具代表性的那一行（例如函式定義行、`dispatch(...)` 那一行）。無法定位行號的整表視為不合格，退回重做。
2. **禁止推測**：只寫程式碼裡實際寫出來的行為。看不出型別、看不出初始值、看不出呼叫者，就寫「未找到」，不要用「應該是」「推測為」這類字眼。
3. **不要省略你認為不重要的欄位**：欄位表頭列出的每一欄都要填，找不到內容寫「未找到」，不留空白。
4. **不要判斷等價性**：即使你同時看得到 R18 現有程式碼，也只描述 R15 這一份的事實；R15/R18 是否等價由主流程比對。
5. **字數上限**：單一 agent 的完整輸出（含所有表格）不得超過 6000 字；預期超過時優先精簡「呼叫者」「第三方元件用法」等輔助欄位的描述長度，四張核心表格的列不得因此省略。

現在開始分析。
```

**主流程親自核對**（agent 產表是素材，不是結論，這兩項不准外包）：

1. **action 對應**：逐列讀 R15 action creator 原文與要照抄的 R18 樣板，確認 `url`、`method`、`data 形狀` 一致。名稱相似但參數或 endpoint 不同的 action 是最常見的錯配。
2. **success 副作用完整性**：對照 reducer 表的「哪些 case 修改」欄，逐一確認每個 `_SUCCESS` 分支改動的欄位都被抄進表裡——尤其是 Modal 開關欄位（`modal` / `open` / `visible`）與「順便再打一支 API」這種次要副作用。

其餘（URL 字串、HTTP method、action type 常數、import 來源）可直接採信。核對完把四張表與核對結論寫進 `${MIGRATION_STATE_DIR}/<entry>-contract.md`。

**tab-reuse entry 的合約抽取**：tab-reuse entry（定義見 Phase 0 (2)）不派三群 agent，主流程只做兩件事：

1. **元件表**：在 R15 content 殼（座標見 `docs/route-and-flag.md` §4「tab-reuse（零檔 tab）」小節）找到本 tab 對應的 `case '<eventKey>'`——`eventKey` 由 `route.fe_config_prefix` 的 subPathname 對回 `frontend/react_15/configs/sheetRoutingConfig.js` 取得——逐字抄下該分支渲染的 JSX（元件名、每個 prop 與其來源）成合約檔表四「元件表」一列，並附 `路徑:行號`。
2. **shared_deps 對照**：照常填表五（Phase 3(c)）。

其餘本節的三群分工與上面的 agent prompt 不適用於 tab-reuse entry。

## 4. Phase 2：遷移實作（六步，順序固定）

### 步驟 1：Redux 層

tab-reuse entry（見 Phase 0 (2)）整個步驟 1 跳過：沒有 `r15_paths`，沒有 action／reducer 可搬。

依 `docs/redux-mapping.md`：每個帶 `ajax` 的 action creator 對應「action creator（`type` 改 `X.BASE`）+ `got*` entity + saga watcher」三個產物；reducer 依該檔的改寫對照表處理（特別是 R18 會同時發 `ERROR`/`FAIL`/`X_FAILURE`，照搬的 `_FAIL` 分支會被誤觸）。

R15 放在 action 頂層的 `callback` / `dispatch` / `lastExcutionFunction` / `redirect` **一律搬進 `ajax` 物件內**，放在頂層會被靜默忽略。帶 `{key}` 取代的 redirect 改名 `ajax.redirectTo`。

三個產物的骨架（完整規則與 `legacyEntity` factory 定義見 `docs/redux-mapping.md`）：

```js
// 1. action creator：type 改成 X.BASE，副作用欄位全部放在 ajax 物件內
export const fetchXxx = (params) => ({
  type: FETCH_XXX.BASE,
  ajax: { url: `/xxx/list?caseId=${params.caseId}`, method: 'get', data: {}, callback: params.callback },
});

// 2. entity：一行，交給共用 factory 產生 success handler
export const gotFetchXxx = legacyEntity(FETCH_XXX);

// 3. saga watcher：放該頁自己的 saga 檔，再到總入口 fork 進去
yield takeLatest(FETCH_XXX.BASE, function* (action) {
  yield fork(ajaxRequest, gotFetchXxx, action.ajax, { ...GENERAL_AJAX_SETTING });
});
```

action 表若出現對照表列為「不支援」的欄位（`headers`、`authorizationToken`、`file1`~`file3`、`files`）→ `blocked(unsupported_ajax_field)`，`notes` 指出是哪一個 action 的哪一欄。

### 步驟 2：元件層

tab-reuse entry（見 Phase 0 (2)）整個步驟 2 跳過：沒有元件檔要複製。

把 `r15_paths` 的元件檔複製到 `entry.r18_dir`（R18 落點是 R15 相對路徑原樣對映，不切檔、不合併；**目標路徑已有同名檔時一律不覆寫**——那是 R18 已在使用的元件，覆寫會讓既有 R18 頁面壞掉而 build 照樣綠。遇到就停：`blocked(needs_human)`，`notes` 列出撞到的每一個檔，由人決定改 import 沿用 R18 版還是把該檔移出 entry），再依 `docs/api-mapping.md` 做機械式對照替換：`React.PropTypes` → `prop-types`；`componentWillX` → `UNSAFE_componentWillX`；string refs 保留；bootstrap 元件與 prop 改名；表格套件 v1 → next（`filterFormatted` → `filterValue`、`sortFunc` 由 row 改吃 cell）；react-select 1 → 5 的 props 改名與 value adapter；`this.props.location` → `withLocation`、`this.props.router.push/replace` → dispatch 對應的導頁 action；i18n HOC 改名並保留 `{ wait: true }`；同層 css/scss 照搬並保留 import。

落點計算：**以 `r18_dir` 本身判定，不看 `type`**。`r18_dir` 為 `frontend/react_18/src/r15-legacy/` 的 entry **只去掉 `frontend/react_15/`、保留完整相對路徑**（`daycase/actions.js` → `r15-legacy/daycase/actions.js`，七支同名的模組級 `actions.js` 殼才不會互撞）；其他任何 entry（不論 `type` 是 `page` 或 `shared`）把 `r15_path` 去掉 `frontend/react_15/<模組>/`（`<模組>` 是 R15 的第一段目錄）後接在 `entry.r18_dir` 之後。shared 層搬過來的檔（`r18_dir` 為 `r15-legacy/` 者，由盤點填好）與 R18 既有同名元件並存、不覆寫；消費者的 import 路徑一律取 `shared_deps.r18_equivalent`，**不要自己推 R18 路徑**。跨 entry 的 import（消費檔在本 entry、被 import 的檔屬於另一個 entry）只要複製後相對路徑會改變，盤點都已列進 `shared_deps`，`r18_equivalent` 就是依上述規則算出的提供者落點；相對路徑不變（同根落點）的不列。

**禁止**：改成 hooks、改名、順手重構、換套件、動 `TableContainer`。

### 步驟 3：路由與開關

依 `docs/route-and-flag.md` 的三層 + 子頁處理：

`type: shared` 的 entry **整個步驟 3 跳過**：沒有路由、沒有開關、不動 sidebar，直接進步驟 4。

`route.switch == "static_list"` 的 entry（沒有登入 session 也要拿到 R18 bundle 的頁面，機制與取捨見 `docs/route-and-flag.md` §1.4）：**不做** 1、2，改在 `backend/config/frontend/index.js` 的 `feConfig.route.react_18` 陣列加一項 `'<route.fe_config_prefix>'`（前綴碰撞規則同樣適用）；3 的 R18 route **不包** `checkFeatureSettingEnable` guard（沒有 flag 可查）；4、5 照常。

1. `backend/routes/index.js` 的 `featureControlledRoutes` 加一行 `'<route.fe_config_prefix>': '<feature_flag.key>'`（前綴碰撞規則見該文件 §6，key 是其他活路徑的前綴時要加 `$` 結尾錨）。
2. `backend/const/companyDefault.js` **三個 template 都要加**同一個 key、`enable: false`。
3. R18 側加 route 與 `checkFeatureSettingEnable` guard（頂層頁面在 `AppRouter.jsx`；子頁在 `entry.route.r18_router_file`）。tab-reuse entry 的 Route element 用 `entry.shared_deps[0].r18_equivalent` 指到的元件（import 路徑相對 `entry.route.r18_router_file` 計算），props 逐字照 Phase 1 抄下的 JSX；`key`／`caseId`／`employeeId` 這類取自路由參數的值，照同一子路由檔其他已遷移 tab 的既有寫法。
4. `route.kind == "sub"` 時另做 tab 處理：對應 tab 的 `isNeedReload` 改成 `!<flag>`，R15 側 header 三元式與 content switch 的 `if (!flag)` 包裹（這是 R15 唯二允許的改動）。
5. `entry.sidebar_entries` 非空才動 sidebar，且三份 `sidebarConf.js` 形狀與 `allowRole` 一字不差；為空則三份都不動。

收尾跑一次該文件 §9 的完成檢查清單。

### 步驟 4：註解與命名

原註解逐字照搬；所有建立或修改的檔案，檔頭 `Modified` 欄位新增一行。不補 STEP、不補 JSDoc、不改變數名。tab-reuse entry 沒有被複製或新建的元件檔，只對本次實際修改的檔（R15 header／content、R18 子路由檔）加 `Modified`。

### 步驟 5：建置

1. 先 `pgrep -f "vite.*--watch"`。有 watcher 在跑 → `blocked(build_env)`：無人看管環境不該有人開著 watch，建置結果不可信。
2. 在 `frontend/react_18` 跑 `node --max_old_space_size=4096 ./node_modules/vite/bin/vite.js build`。
3. 紅燈**最多修 2 次**，仍紅 → `blocked(build_failed)`，`notes` 附錯誤首行與檔案位置。修法只允許修正遷移造成的錯（漏 import、路徑錯、prop 名稱錯），不准為了讓建置過而改行為或砍功能。
4. eslint 只跑本次變更的檔、只修 error 等級；warning 不動（避免把既有程式碼改出範圍外的 diff）。eslint error 同樣**最多修 2 次**，仍有 error → `blocked(build_failed)`，`notes` 首行寫「eslint」並附規則名與檔案位置，不得用 `eslint-disable` 註解壓掉。

### 步驟 6：無對照項目盤點

對照表查無、且 R18 全庫也找不到先例的用法 → 在合約表標 ⚠ 並 `blocked(no_mapping)`，`notes` 寫出是哪個套件／哪個 API／哪一行。**不要自己發明轉換規則**：發明出來的寫法沒有先例可比對，Phase 3 也驗不出來。

tab-reuse entry 只盤 `shared_deps` 那一筆：其 `r18_equivalent` 在磁碟不存在 → `blocked(no_mapping)`，`notes` 寫「提供者 entry 的落點尚未存在」（`depends_on` 理論上已保證這個依賴已完成，這裡是防禦性檢查）。

## 5. Phase 3：等價性驗證

### (a) 差異測試

tab-reuse entry 跳過本節：沒有 action／reducer 可比對，在報告寫「不適用：無 action／reducer」。

從合約表的 action 表與 reducer 表產生測試檔到 `${MIGRATION_STATE_DIR}/diff-tests/<entry>/`（模板在 helpers 的 diff-test harness），**測試檔不進 repo**：

- 每個 action creator：用合約表的參數範例（最小一組 + 典型一組）餵 R15 與 R18 兩版，斷言產出深相等。
- 每個 reducer case：用 `initialState` + 範例 payload 餵兩版，斷言結果深相等（type 字串經 `actionTypeMap` 轉換）。
- utils 純函式同法。

用 diff-test harness 的 jest 設定執行，結果（通過／失敗／預期不同）寫進報告。「預期不同」必須逐條寫出理由，寫不出理由的一律算失敗。

### (b) 靜態比對

套 `docs/contract-extraction.md` 的 L1–L3 檢查項目逐條標記，含三個 MUST-CHECK 與 feature flag 三層一致性表。三個 MUST-CHECK 即使判定 N/A 也要逐條寫出判定理由，不准整項跳過——尤其 cleanFail on hide 與 Modal 自動關閉這兩項，在「元件原樣搬、Redux 機制換掉」的不對稱改動下是最容易破的地方。

tab-reuse entry 只做 feature flag 三層一致性表，與三個 MUST-CHECK 各自的 N/A 判定理由（仍不准整項跳過）；L1–L3 檢查項目不適用（沒有 R15/R18 元件對照可比）。

### (c) 合約表回填

對 `<entry>-contract.md` 的每一列回填 `R18 對應`（路徑:行號或名稱，找不到寫「無對應」）與 `等價 ✅/⚠️/❌`。`entry.shared_deps[]` 的每一項也各佔一列（填在合約檔的「shared_deps 對照」表）：`r18_equivalent` 非 null 的，比對 R15 檔的 export 面與本 entry 實際用到的 props／函式名是否都存在於該 R18 檔，缺的逐一列出並標 ⚠️（這些就是呼叫端要改的地方）；為 null 的直接標 ❌「無對應」。⚠️ 的語意是「需要人工複查」，不是「大概沒問題」。所有 ⚠️ 與 ❌ 的列都必須進報告的 ⚠ 清單，並計入 `warnings_count`。

tab-reuse entry 只回填表五（shared_deps 對照）——沒有其他合約表列可回填。

### (d) 頁面 E2E（可選）

偵測本機是否有 `.env.local` 與可用的 dev server：

- 有 → 用 Playwright 開該頁路由，斷言載入後無 console error，結果寫進報告。
- 沒有 → 在 `unverified_items` 加一筆「頁面 E2E（無 dev server）」。**禁止假 PASS**：沒跑就是沒跑。

（bundle 啟動 smoke 由 runner 強制執行，不在本 skill 範圍。）

## 6. Phase 4：收尾

1. **逐行讀 `git diff`**，逐項確認：

   - [ ] 沒有測試殘留（差異測試檔應在狀態目錄，不在 repo）
   - [ ] 沒有除錯用的 `console.log`、沒有被註解掉的舊程式碼
   - [ ] 沒有把 feature flag 臨時硬開成 `true`（預設一律 `false`）
   - [ ] 沒有任何憑證、連線字串、機構實際設定值
   - [ ] 沒有範圍外檔案；R15 只有允許的兩處改動、`routes.js` 沒被碰
   - [ ] 共用註冊檔每個 key 只出現一次（resume 最容易在這裡寫出重複行）
   - [ ] 所有新增或修改的檔都補了 `Modified` 一行
2. `git add` 僅限 §0 允許的範圍。
3. commit，訊息格式固定：

   ```
   [<JIRA>] feat(FE): <FeaturePath>-R18遷移-<entry>
   ```

   `<JIRA>` 取自 `entry.jira`（與分支名前段一致）；`<FeaturePath>` 取自被遷移檔案檔頭的 `FeaturePath` 欄位，取不到就用該頁面的業務路徑；`<entry>` 是 entry id。tab-reuse entry 沒有被遷移的檔案可取 `FeaturePath`，`<FeaturePath>` 一律用該 tab 的業務路徑（例：日照系統-個案-活動）。
4. 產出 `${MIGRATION_STATE_DIR}/<entry>-report.md`（範本 `templates/report.template.md`）：合約回填摘要、⚠ 清單、`unverified_items`、build 結果（指令 + 末 5 行）、差異測試三欄統計、頁面 E2E 有無執行、供 PR body 用的統計行。
5. `<entry>-progress.md` 全部勾完。
6. 輸出結構化結果（見 §8）。

**不 review、不 push、不開 PR。** 這三件事都是 runner 的職責，skill 先做只會製造衝突。

## 7. blocked 列舉（八種，字面值不得增減）

| blocked_reason | 觸發點 | 意思 |
|---|---|---|
| `inventory_incomplete` | Phase 0 (1)(2) | entry 不存在或必要欄位缺漏；盤點要補，skill 不補 |
| `too_large` | Phase 0 (3) | 檔數或行數超過 `limits`；要人工重新拆分 entry |
| `git_state` | Phase 0 (4) | 分支不符，或工作目錄有本 entry 範圍外的髒檔 |
| `build_env` | Phase 2 步驟 5 | 偵測到 vite watcher 在跑，建置結果不可信 |
| `no_mapping` | Phase 2 步驟 6 | 對照表查無且 R18 無先例，需要人工決定轉換方式 |
| `unsupported_ajax_field` | Phase 2 步驟 1 | action 用到 R18 saga 基礎層不支援的欄位 |
| `build_failed` | Phase 2 步驟 5 | 修兩次後建置仍紅 |
| `needs_human` | 任何階段 | 其他無法在無人看管下決定的情況；`notes` 必須寫清楚卡點 |

blocked 時仍要：更新 progress（勾到卡住前的最後一項）、把已完成的工作保留在工作目錄（**不要回退、不要清理**）、輸出結構化結果。已經 commit 過才發現要 blocked 的情況，保留該 commit，在 `notes` 說明。

**失敗定位（blocked 與 error 都要做）**：

1. 結構化輸出的 `failed_at` 填物件 `{ "phase": "<0-4>", "step": "<步驟或檢查項，無則 null>", "file": "<最直接相關的 repo 相對路徑，無則 null>" }`；`phase` 對應上表「觸發點」欄的 Phase 編號（Phase 0 (2) → `"0"`／`"(2) 驗必要欄位"`；Phase 2 步驟 5 → `"2"`／`"步驟 5 建置"`）。`done`／`rate_limited` 一律 `null`。
2. 在 `<entry>-progress.md` 尾端的 `## 失敗紀錄` 表追加一列：`attempt | 階段 | blocked_reason | 一句原因 | 相關檔`，內容與 `failed_at` 一致。resume 不讀這段；它是給人與 runner 的 `diagnose` 看的，runner 會把它連同 CLI 事件串、build／smoke 全文一起凍結成診斷包。

## 8. 輸出（每一輪最後必做）

最後一則輸出必須是符合 `templates/result.schema.json` 的 JSON 物件：

```json
{
  "status": "done",
  "module": "<entry-id>",
  "branch": "<entry.branch>",
  "commit": "<hash 或 null>",
  "blocked_reason": null,
  "build": { "status": "pass", "cmd": "<實際建置指令>" },
  "warnings_count": 0,
  "unverified_items": [],
  "report_path": "${MIGRATION_STATE_DIR}/<entry>-report.md",
  "notes": "<一句話結論>",
  "failed_at": null
}
```

規則：

- `status=blocked` 時 `blocked_reason` 必填，其餘狀態一律 `null`。
- `status=blocked` 或 `error` 時 `failed_at` 必填物件（`phase` 必填、`step`／`file` 查得到就填，查不到填 `null`），格式與填法見 §7「失敗定位」；`done`／`rate_limited` 一律 `null`。
- `status=error` 用於非預期失敗；`rate_limited` 只在 skill 內部派工的 subagent 撞到額度且無法完成時使用（一般額度耗盡是 CLI 直接失敗，由 runner 判讀，不會走到這裡）。
- `warnings_count` 必須等於報告 ⚠ 清單的項目數。
- `build.status=skipped` 只限尚未走到建置就 blocked 的情況，`cmd` 仍填預定要跑的指令。
- 即使 blocked 或 error 也要輸出這則 JSON；缺這則輸出，runner 會判為 `error` 並整輪重試。
- JSON 之後在 stdout 末段**另印一行 fallback**，供結構化輸出遺失時判讀：

  ```
  STATUS: <done|blocked|error|rate_limited>
  ```

## 9. resume 速查

| 情況 | 做什麼 |
|---|---|
| 分支已有本 entry commit | 直接跳 Phase 3，**不重做 Phase 1–2**（重做會讓共用註冊檔出現重複行） |
| progress 全勾、無 commit | 只重跑 Phase 4 |
| progress 勾到 Phase 2 步驟 3 | 從步驟 4 往下做；動註冊檔前先 `git diff` 確認步驟 3 是否已寫入 |
| 無 progress 檔 | 當作全新一輪，從 Phase 1 開始 |
| 合約表存在但 Phase 1 未勾完 | 重跑 Phase 1 的未完成分群，已完成的表格保留不重抽 |

## 10. 會靜默壞掉的九個地方（動手前先看一遍）

這些全部是「改錯了但建置照過、畫面看起來正常」的類型，靠 Phase 3 才抓得到，抓不到就會帶進 production。

| # | 症狀 | 成因 | 防法 |
|---|---|---|---|
| 1 | callback / dispatch / redirect 全都沒發生 | 副作用欄位留在 action 頂層；`baseSaga` 只展開 `ajax` 物件 | 步驟 1 逐個檢查這四個欄位都在 `ajax` 內 |
| 2 | 導頁後整頁重載、SPA 狀態全失 | 帶 `{key}` 取代的 redirect 沿用 `ajax.redirect` 原名 | 帶 `{key}` 的一律改名 `ajax.redirectTo` |
| 3 | 錯誤時走到不該走的分支 | R18 HTTP error 同時發三種 action，R15 只發一種 | reducer 的 `_FAIL` 分支依 `docs/redux-mapping.md` 改寫，不照搬 |
| 4 | API 回 200 但資料是錯的（例如整機構混在一起） | POST + `query` 的值被刪掉沒內嵌進 url，後端少一個查詢條件 | 逐個 `query` 欄位確認已內嵌 url 或改放 `ajax.fetchData` |
| 5 | 關掉本頁開關，**別的**已上線頁面退回 R15 | `fe_config_prefix` 是其他活路徑的前綴、又沒加結尾錨 | 照 `docs/route-and-flag.md` §6 判斷是否加 `$` |
| 6 | 只有部分機構看得到新頁 | `companyDefault.js` 三個 template 只加了一個 | 三處都加，跑該文件 §9 檢查清單 |
| 7 | 畫面顯示 i18n key 而不是文字 | R18 的翻譯 HOC 只解析第一個 namespace、沒有 fallback | 依 `docs/api-mapping.md` §9.2 處理非首 namespace 的 key |
| 8 | 儲存成功但 Modal 不自動關 | entity 的 success handler 漏抄 reducer 原本的 `modal: false` | Phase 3(b) MUST-CHECK 1 逐列比對 reducer 表 |
| 9 | 共用註冊檔出現重複 key / 重複 route | `--resume` 重做了已完成的步驟 3 | resume 先看 `git log`，有 commit 就直接跳 Phase 3 |
