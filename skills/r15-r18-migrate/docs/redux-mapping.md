# Redux 對照規則（R15 → R18）

## 背景

目標 repo 的前端有 react_15（class component + 自製 `reduxAjaxMiddleware`）與 react_18（class/functional 混用 + redux-saga）兩套 codebase 並存。本文件引用路徑的慣例：R18 路徑相對 `frontend/react_18/src/`、R15 路徑相對 `frontend/react_15/`；行號以 2026-09-16 的 master 為準，只當定位提示，遷移時以當下 grep 結果為準。R18 的基礎層長這樣：

- `redux/actions.js`：用 `createAction('X')` 產生一個帶 `.BASE` / `.REQUEST` / `.SUCCESS` / `.FAILURE` 四個 type 的物件。
- `redux/sagas/base/baseSaga.js:173` 的 `ajaxRequest(entity, ajax, settings)`：saga watcher 收到 `X.BASE` action 後呼叫，把 `action.ajax` 當請求參數送出，成功時呼叫 `entity.success(response, request, rest)`、失敗時呼叫 `entity.fail(response)`，回傳值（單一 action 或陣列）逐一 `put`；`request.redirect` 的整頁導頁處理在同檔 `:134-140`。
- `shared/actionCreator.tsx:36` 的 `generateActionEntity(X, handlers)`：產生上述 `entity` 物件的 factory，預設 `request`/`fail`，讓你覆寫 `success` 加副作用。同檔 `:24` 的 `getSubActions(X)` 是更陽春的版本，三個函式都用預設值。
- `shared/api/api.js`：實際發 HTTP 請求；GET 把 `options.data` 轉成 query string，其他 method 把 `options.data` 轉成 JSON body；不讀 `options.query`。

本次遷移路線：**R15 class component 保留、命名沿用 R15、redux 機制沿用上述 R18 現行 saga**。R15 專有的 `reduxAjaxMiddleware`（統一處理 `callback` / `dispatch` / `lastExcutionFunction` / `redirect` 四個副作用欄位）在 R18 沒有對應 middleware，這段語意改由 entity 的 `success` handler 吸收。

## R18 redux 註冊檔（步驟 1 會改到、Phase 4 允許 `git add` 的四個檔）

新增一個帶 `ajax` 的 action creator，除了該頁自己的 action/reducer/saga 檔，還要接上以下四個既有的共用註冊檔——這四個檔就是 `SKILL.md` §0 允許 `git add` 的 R18 redux 註冊檔，四個檔都已存在，只新增內容，不改動既有內容：

| 檔 | 用途 |
|---|---|
| `frontend/react_18/src/redux/actions.js` | action type 群組鍵：每個模組的 action 常數集中宣告在這裡（`createAction('X')` 機制見上方「背景」），新增的 `X.BASE`／`X.SUCCESS`／`X.FAILURE` 常數要加進來 |
| `frontend/react_18/src/redux/reducers/index.js` | `combineReducers` 註冊：新頁面的 reducer 檔要 import 進來、加進 `combineReducers({ ... })` 的物件 |
| `frontend/react_18/src/redux/sagas/index.js` | saga watcher 註冊：新頁面自己的 saga 檔要 import 進來、`fork` 進總 saga 入口（「樣板」小節最後一步提到的「總入口 fork 進去」就是這裡） |
| `frontend/react_18/src/shared/interfaces/IReducerState.tsx` | root state 型別：`IReducerState` 介面要補上新 reducer 對應的欄位型別 |

改動範圍與既有 `import`／`combineReducers`／`fork`／`interface` 的形狀一致，不重構、不動其他模組已經註冊的內容。

## 命名規則

- action 常數：`export const FETCH_PROPLAN = createAction('FETCH_PROPLAN')`；identifier 與字串都用 R15 原文，不加任何前綴（不套用 R18 部分模組常見的 `ACTION_CATEGORY` 命名空間前綴）。R18 已有同型先例：`redux/actions.js:78-87` 的 company 區塊十個常數（`FETCH_COMPANY` … `DELETE_RECIEPT_QRCODE`）都是 `createAction('X')` 不加前綴；反例是 `PRO_PLAN` 物件內的 `createAction('proPlan/UPDATE_PROPLAN')`（`redux/actions.js:736`），新頁面不要跟。
- reducer 檔名、reducer 函式名、state 欄位名、`initState`、action creator 函式名：沿用 R15。
- entity（saga 呼叫的 `{ request, success, fail }` 物件）命名照 R18 既有慣例 `got<ActionCreatorName>`（例如 `gotFetchProPlanList`）。

## 樣板：每個帶 `ajax` 的 action creator 一組

R15 的一個 action creator 若帶 `ajax` 欄位，遷移後在 R18 側對應三個產物：

1. **action creator**：`type` 改成 `X.BASE`。R15 放在 action 頂層的 `callback` / `dispatch` / `lastExcutionFunction` 全部**搬進 `ajax` 物件內**（`baseSaga` 只把 `ajax` 展開成 `request` 傳給 entity handler，放在 action 頂層會被忽略、靜默失效——R18 `redux/actioncreators/daycaseActionCreator.js:508` 的 `deleteCase` 就把 `redirect: '/daycase'` 放在 action 頂層而不是 `ajax` 內，是既有的踩坑實例）。R15 的 `redirect` 欄位全庫 9 處，分兩種：
   - 靜態路徑（值不含 `{key}` 佔位：固定字串如 `'/login'`，或像 `login/actions.js:52` 那樣直接傳變數）：直接搬進 `ajax.redirect`，這是 R18 原生欄位，`baseSaga` 對它的處理是 SUCCESS 後整頁 `location.href` 導頁。R15 共 4 處（`daycase/actions.js:670`、`case/actions.js:494`、`employee/actions.js:173`、`login/actions.js:52`）；R18 已有 2 檔先例把它正確放在 `ajax` 內（`redux/actioncreators/accountActionCreator.js:141,392`、`redux/actioncreators/expertAcaseActionCreator.js:1064,1992,2019`）；`daycaseActionCreator.js:508` 是放錯層的反例，不算先例。
   - 帶 `{key}` 動態取代的（如 `'/x/{_id}'`）：改名成 `ajax.redirectTo`，由 factory 取代 `{key}` 後轉成 SPA 導頁（`push`）。**不能沿用 `ajax.redirect` 這個名字**，否則 `baseSaga` 會把它當靜態路徑再整頁重載一次。R15 共 5 處（`daycaseEvaluateList/actions.js:44`、`employeeList/actions.js:137`、`daycaseList/actions.js:70`、`daycaseList/actions.js:138`、`caseList/actionsBase.js:333`）；R18 無先例。
2. **entity**：新增一個共用 factory `redux/actioncreators/base/legacyEntity.js`（約 15 行，R18 基礎層 `baseSaga` / `api.js` 零改動，與既有的 `getSubActions` / `generateActionEntity` 兩個 factory 並列）統一產生 success handler。R18 現況：`export const got…` 形式的 entity 共 525 個，其中只有 37 個用 `generateActionEntity`、其餘全部手寫，沒有任何共用副作用工廠；`legacyEntity` 是新增的第三個產生器：

   ```js
   export const legacyEntity = (X) => generateActionEntity(X, {
     success: (response, request, rest) => {
       if (request.callback) { request.callback({ success: true, data: response }); }
       const chained = [].concat(request.dispatch || []).map((d) => d());
       if (request.lastExcutionFunction) { request.lastExcutionFunction(); }
       const nav = request.redirectTo ? [redirect(fillKey(request.redirectTo, response))] : [];
       return [action(X.SUCCESS, { response }), ...chained, ...nav];
     },
   });
   ```

   `fillKey` 把 `'/employee/{_id}'` 的 `{_id}` 換成 `response._id`（與 R15 `middlewares/reduxAjaxMiddleware.js` 的 `successHandler` 同語意）；`redirect` 是既有 `redux/actioncreators/base/baseActionCreator.js:22` export 的 `redirect(url)`（底層是 redux-first-history 的 `push`；R18 全庫目前 0 處使用，本 factory 會是第一個消費者），對應 R15 的 SPA `push` 導頁。SUCCESS action 形狀刻意與 `getSubActions` 相同（`{ response }`），不展開 `rest`（查證結論見下一節）；callback 參數同樣不展開 `rest`。R15 middleware 的 `successHandler` 執行順序是 redirect → dispatch → callback → `_SUCCESS` → lastExcutionFunction；factory 內 callback 也在回傳 SUCCESS action **之前**執行，順序一致。`fail` 用預設值 `action(X.FAILURE, { response })`，因為 R15 的 `_FAIL` 本來就沒有副作用。

   為什麼不逐頁手寫：R15 全庫 `dispatch` 181 個區塊、`callback` 205 個、`lastExcutionFunction` 24 個、`redirect` 9 個，重疊後估計要重複寫三百多段幾乎相同的樣板程式碼，且由無人看管方式批次產生，任何一處漏 `rest`、callback 形狀寫錯、忘了 `{key}` 取代都只會在該頁出錯，review 抓不完。factory 只需要一次寫對、一次 review，之後每頁一行 `export const gotX = legacyEntity(X);`。
3. **saga watcher**：

   ```js
   yield takeLatest(X.BASE, function* (action) {
     yield fork(ajaxRequest, gotX, action.ajax, { ...GENERAL_AJAX_SETTING });
   });
   ```

   放在該頁自己的 saga 檔，並在總 saga 入口 `redux/sagas/index.js` fork 進去。

## 欄位對照表（R15 `ajax` / action 欄位 → R18 寫法）

| R15 | R18 寫法 | 備註 |
|---|---|---|
| `url` / `method` / `data`（POST） | 原樣搬 | |
| `method: 'get'` + `query` | 改放進 `data` | `api.js` 對 GET 會把 `data` 轉成 query string；R15 GET 的 `data` 本來就會被瀏覽器丟掉，所以合併不會漏資料 |
| `method: 'post'` + `query` | **內嵌進 `url`**：單一 id / 日期值直接插值成模板字串，如 `` `/proPlan/list?caseId=${caseId}` ``（R18 35 處慣例，先例 `redux/actioncreators/proPlanActionCreator.ts:91`）；多鍵或值含自由文字用 `new URLSearchParams(obj).toString()` 拼在 url 後面（先例 `redux/actioncreators/formActionCreator.js:441`，該處是 GET 情境，拼 url 的技法相同）。`query` 欄位本身刪除；handler 需要這些值當函式參數時改放 `ajax.fetchData`（R18 `request.fetchData` 讀取 20 處慣例） | R15 共 36 個區塊。後端有 controller 從 `req.query` 取值（如 `controllers/dayCaseController/daycaseScheduleController.js:1586` 的 list handler 用 `...req.query` 組查詢條件），不能直接把這些值改塞進 body，否則後端條件少一個、回 200 但資料是錯的（例如整機構混在一起）。R18 現有 `query:` 殘留 11 處（`scheduleActionCreator.js` 8、`reportActionCreator.js` 2、`abnormalEventActionCreator.js` 1）是 url 未內嵌的半成品，沒有 R18 頁面在呼叫；遷移對應 entry 時要補 url，盤點 `shared_deps.r18_equivalent` 時標註 |
| `dispatch: f` / `dispatch: f.bind(null, a, b)` / 陣列 | 原樣搬進 `ajax.dispatch`，factory 逐一呼叫 `d()` 後併入回傳的 action 陣列 | `.bind` 閉包保留，不需改參數傳遞方式；R18 手寫版先例 `redux/actioncreators/activityManagerActionCreator.js:178-184`（見文末範例） |
| `callback(data, dispatch)` | 原樣搬進 `ajax.callback`；factory 以 `{ success: true, data: response }` 呼叫，元件端的 callback 函式本身不用改 | 108 個實際呼叫點只讀 `.success` 與 `.data`（含 `.data.xxx`），`.total` / `.message` / `.errors` 有效讀取 0 處（查證結論見下一節）；第二參數 `dispatch` 全庫 0 處使用（唯二出現在 `actions/scheduleAction.js:222,324`，且已被註解掉），不支援；R15 只在 `body.success` 為真時呼叫 callback，factory 同樣只在 success handler 呼叫，時機一致 |
| `lastExcutionFunction` | 原樣搬進 `ajax`，factory 呼叫 | R18 手寫版先例 `redux/actioncreators/scheduleActionCreator.js:292` |
| `redirect: '/x'`（靜態路徑） | 搬進 `ajax.redirect`（R18 原生：SUCCESS 後整頁 `location.href`） | R15 4 處（daycase / case / employee / login，行號見樣板小節）；R18 2 檔先例（account / expertAcase，行號見樣板小節） |
| `redirect: '/x/{_id}'` | 改名 `ajax.redirectTo`，factory 取代 `{key}` 後回傳 `redirect(...)`（SPA push） | R15 5 處（daycaseEvaluateList / employeeList / daycaseList ×2 / caseList）；R18 無先例 |
| `redirect: 'reload:…'` | `ajax.redirect` 原樣搬 | `baseSaga` 原生支援這種值 |
| `headers` / `authorizationToken` / `file1~3` / `files` | 不支援 → entry 標 `blocked(unsupported_ajax_field)`，該頁遷移時要人工評估 | 全庫 `ajax` 區塊內這批欄位的使用量是 0，遇到才需要額外設計 |
| `file` + `data` | `ajax.data = { file, ...data }`，saga 傳入的設定改用 `MULTIPART_AJAX_SETTING`（定義在 `shared/constants/general.ts:45`；用法先例 `redux/sagas/activityManagerSaga.js:104`） | R15 1 處 |
| `edgeAjax` | 不移植（已棄用） | 只有 `deviceManagerList/actions.js`、`deviceSensorList/actions.js` 與 `middlewares/edgeServerMiddleware.js` 在用，這兩個頁面已移出遷移範圍 |

## callback 語意查證結論

範圍：R15 全庫，只算最終真的會被 `middlewares/reduxAjaxMiddleware.js:47-49`（`if (action.callback) { action.callback(data, store.dispatch); }`）呼叫到的 callback；而這段只在 `:180-182` 的 `if (response.body.success)` 為真時才走進 `successHandler`。2026-09-15 實查結果：**108 個呼叫點 = 18 個 callback 內嵌在 action creator 內（只讀 `.data` 15、同時讀 `.success` 與 `.data` 3）＋ 90 個由呼叫端傳入且追到終端（讀欄位 8：只讀 `.data` 1、讀 `.success` 7，後者有 5 個同時讀 `.data`；不讀任何欄位 82）**。另外 28 個 action creator 的 callback 參數是死碼（沒有任何元件帶入），其餘 pass-through 因呼叫時未帶 callback 永不觸發，未歸類。整包轉傳（把 `res` 原樣丟給下一層）0 處；第二參數 `dispatch` 0 處（`actions/scheduleAction.js:222,324` 兩處已註解）；callback 寫在 `ajax` 內（而非頂層）的 0 處（46 個含 `ajax:` 的檔全查）。

讀頂層非 `data` 欄位的呼叫點（全部只讀 `.success`；2026-09-16 對現行 master 複核行號，並發現 caseList 新增一處同形讀者 `fetchCaseSourceOptions`，表列由 10 處增為 11 處，結論不變）：

| 位置 | action creator | 讀取欄位 |
|---|---|---|
| `daycaseList/actions.js:253-254` | downloadDaycaseExcelTemplate | `.success` `.data` |
| `caseList/actionsBase.js:506` | downloadCaseExcelTemplate | `.success` `.data` |
| `employee/actions.js:485-486` | downloadLeaveRecordExcel | `.success` `.data.path` |
| `caseList/index.jsx:455` | fetchCasesForSelectAll | `.success` `.data` |
| `caseList/index.jsx:584` | fetchCaseCategoryOptions | `.success` `.data` |
| `caseList/index.jsx:597` | fetchCaseSourceOptions | `.success` `.data`（2026-09-16 複核時新增的來源下拉選項讀者，與 `fetchCaseCategoryOptions` 同形） |
| `caseList/index.jsx:611` | fetchCaseFilterPresets | `.success` `.data` |
| `caseList/index.jsx:635-637` | createCaseFilterPreset | `.success` `.data`；`.errors.error.message` 在 `!res.success` 分支，R15 下為死碼 |
| `caseList/index.jsx:651` | deleteCaseFilterPreset | `.success` |
| `caseList/index.jsx:669` | setCaseFilterPresetDefault | `.success` |
| `case/components/CaseSwitcher.jsx:126` | fetchCaseNameOptions | `.success` `.data.list` `.data.total` |

結論：factory 傳 `{ success: true, data: response }` 就涵蓋全部既有呼叫點，`...rest` 沒有讀者、不需要展開。`createCaseFilterPreset` 那一處在 `!res.success` 分支讀 `.errors.error.message`，但 R15 middleware 只在 `body.success` 為真時才會呼叫 callback，所以那個分支在 R15 下本來就是死碼，factory 沿用同樣的呼叫時機，行為一致（不是新引入的行為差異）。Phase 1 合約表的 action 表 `callback` 欄要記「讀取欄位」；之後遷移過程中如果真的挖到某個 callback 讀了 `.total` / `.message` 之類的頂層欄位，contract.md 標 ⚠、反查它的呼叫時機是否真的會被觸發，若確認需要，是加回 `...rest` 這一行改動、一次生效，不需要每頁分別處理。

附帶發現（遷移時原樣搬、Phase 1 合約表標 ⚠，不在遷移 commit 內順手修）：

- **R15 既有 bug**：`case/components/service/components/CalendarOptionModal.js:720-733` 呼叫 `deleteShiftRecord` 時只給 6 個位置參數，字串 `'刪除服務未遇(新制)'` 落在第 6 個參數 `callback`（簽名見 `case/actions.js:1789`：`(shift, viewType, type, month, year, callback = () => {}, actionName)`），`actionName` 變 undefined、字串原樣進 action 頂層的 `callback`。middleware 對字串呼叫 `action.callback(data, dispatch)` 會丟 TypeError，後面的 `DELETE_SHIFT_RECORD_SUCCESS` 與 `lastExcutionFunction` 不會跑。factory 對字串呼叫同樣會丟 TypeError，行為一致；規劃期已決定 R15 不修。
- `shiftList/actions.js:152,394`（`removeOneDayShift` / `leaveMultiOneDay`）的 callback 是 `() => { if (callback) { callback(); } }` 包一層，呼叫端永遠拿不到 `res`；原樣搬即可，factory 行為一致。

## reducer 改寫對照表

| R15 | R18 |
|---|---|
| `` case `${X}_SUCCESS` `` | `case X.SUCCESS` |
| `` case `${X}_FAIL` `` | `case X.FAILURE` |
| `case X`（BASE 本身） | `case X.BASE`（BASE action 兩邊都會進 reducer，行為一致） |
| `action.data` | `action.response` |
| `action.errors` / `action.message`（FAIL 分支讀取） | `action.response.errors` / `action.response.message` |
| `action.total` 等 response 頂層其他欄位 | 這批欄位全庫實際上沒有 reducer 在讀（規劃期 2026-09-07 對 R15 全部 53 個 reducer 的統計：讀 `action.data` 368 處、`action.errors` 400 處、`action.message` 10 處、BASE action 自帶的 `action.initial` 22 處，`action.total` 類頂層欄位 0 處）；真的遇到需要讀的情況，改成 `action.response.<欄位>`（`data` 是物件時 `baseSaga` 已經把其他頂層欄位併進 `response`；`data` 是陣列時要另外寫 handler） |
| `action.initial` 等 BASE action 自帶欄位 | 原樣（BASE action 是原始物件直接進 reducer，不經過 entity 轉換） |
| `errorReducer` / `errorType` / `AUTH_FAIL` 導頁 | 不搬；R18 沒有獨立的 ERROR reducer，認證失效由既有主框架 `pages/mainFrame/index.jsx` 的 `LOGIN_URL` 導頁邏輯處理 |

**接受的行為差異**（這些是 R18 production 現行語意，遷移時不回頭模擬 R15 的舊行為）：

- HTTP 錯誤時 R18 會同時發出通用的 `ERROR`、`FAIL`，以及 `X.FAILURE`（R15 的 middleware 只發 `ERROR`），所以 `_FAIL` 分支在 HTTP 錯誤時也會被跑到。
- 逾時設定是 600 秒。
- 成功時會多發一個全域的 `cleanFail()`。
- 副作用執行順序是 SUCCESS 先、redirect 後（R15 middleware 是 redirect 先）。

差異測試遇到這幾項要標「預期不同」，不要當成回歸失敗。

## 併發

預設用 `takeLatest`（R18 目前的主流慣例：`takeLatest(` 451 處 vs `takeEvery(` 36 處，2026-09-16 統計）。但如果 Phase 1 合約盤點發現同一個 action type 會被迴圈 dispatch、或多個實例同時 dispatch 且每個實例都要拿到各自的回應（例如逐檔上傳、逐列儲存這類情境），該 watcher 要用 `takeEvery`，並在對照文件標記理由——R15 middleware 本身是「每個 action 各自處理」的語意（fire-every），所以判斷要逐 action type 做，不能為了省事全域切成同一種。

## 不需移植的 R15 middleware 行為

- **`gaTrackingMiddleware`**（`middlewares/gaTrackingMiddleware.js`，`:12` 監聽 `AUTHENTICATE_SUCCESS` / `LOGIN_SUCCESS` 去送 GA user properties）：R18 已經在登入成功的 saga（`redux/sagas/accountSaga.js:66`）與應用程式 preload 流程（`index.js:74`）各呼叫過一次 `setGAUserProperties`，不需要額外搬。遷移個別頁面時如果遇到 R15 的 `AUTHENTICATE_SUCCESS`（非登入流程觸發的 session 重驗）情境，要另外確認 R18 的 preload 流程是否也覆蓋得到。
- **`edgeServerMiddleware`**（`middlewares/edgeServerMiddleware.js`，處理 `edgeAjax` 欄位）：已棄用（範圍見欄位對照表最後一列），不移植。

## 決策紀錄：兩個曾經討論過的技術選項

以下兩項在規劃期經過討論並已定案，此處只留結論，不重複列出討論細節：

- **POST 請求要帶查詢參數（對應欄位對照表的 `method: 'post'` + `query`）**：選定「action creator 自己把值內嵌進 url 模板字串或用 `URLSearchParams` 拼接」，不改動 R18 基礎層的 `api.js`。R15 受影響的 `method: 'post'` + `query` 區塊共 36 個。被否決的替代方案是 `api.js` 加約 5 行、任何 method 都把 `options.query` 序列化附加到 URL（R18 現行沒有任何 live 請求帶 `options.query`，向後相容成立），好處是 36 處 action creator 可原樣搬、差異測試可直接斷言輸出相同。否決理由：`api.js` 目前完全不認 `options.query`，改 `api.js` 要對現有全部呼叫點做一次回歸測試，風險與工作量都大於直接改寫這批 action creator 本身；維持 `api.js` 不動也保證對其他既有頁面零副作用。選定方案的代價要認：要自己 encode、action creator 輸出與 R15 不同（差異測試對這 36 處特判）、並行期 R15 修這些 action 時兩邊寫法不同。
- **R15 副作用欄位（callback / dispatch / lastExcutionFunction / redirect）搬到 R18 的做法**：選定「新增共用的 `legacyEntity` factory」，不逐頁手寫 `generateActionEntity`。理由：手寫版本重複度高、由無人看管流程批次產生時出錯不易被 review 抓到（見樣板小節的量化說明）；factory 版本把邏輯集中寫一次，之後每頁只要一行呼叫，出錯範圍也集中好修。代價：factory 有 bug 一次影響所有已遷移頁（修也一次修好）；R18 從此三個 entity 產生器並存，`legacy` 命名標明它是 R15 語意相容層。

## 完整範例：`proPlan` 四檔對照

這裡用一個真實存在的 action creator（`updateProPlan`）示範上面規則具體套用起來的樣子。

**重要澄清**：`proPlanRecord` 這個頁面本身**不在**本次遷移範圍內（規劃期已定案不搬，因為它是孤兒路由、sidebar 沒有任何入口）。但它背後共用的 redux 檔（`actions/proPlanAction.js`、`reducers/proPlanReducer.js`）在 R18 side **已經有實作**——這是更早一輪「整頁重寫成 functional + hooks + 新寫 saga」的遷移留下的產物，寫法是逐個 action 手刻 `{ request, success, fail }` 物件，並不是用本文件介紹的 `legacyEntity` factory（那時這個 factory 還不存在）。下面同時列出 R15 原始寫法與 R18 現有真實寫法，讓你看到兩種寫法的落差，但**這不是本 skill 要產出的目標寫法**——新遷移的頁面一律套用上面「樣板」小節的 factory 方式，不要模仿這個舊範例手刻。

### 1. action 常數與 action creator

R15（`frontend/react_15/actions/proPlanAction.js`；常數在第 14 行，action creator 在第 112–123 行）：

```js
export const UPDATE_PROPLAN = 'UPDATE_PROPLAN';

export function updateProPlan(id, data, callback) {
  return {
    type: UPDATE_PROPLAN,
    ajax: {
      url: '/proPlan/update',
      method: 'post',
      data,
      query: { id },
    },
    callback,
  };
}
```

R18 現有真實寫法（action 常數在 `frontend/react_18/src/redux/actions.js` 第 728–747 行的 `PRO_PLAN` 物件內，`UPDATE_PROPLAN` 本身在第 736 行；是整個 proPlan 模組共用一個具名空間物件，而不是本文件建議的「每個常數各自 `createAction`、不加前綴」寫法）：

```js
export const PRO_PLAN = {
  // …
  UPDATE_PROPLAN: createAction('proPlan/UPDATE_PROPLAN'), // 更新專業照顧計畫
  // …
};
```

action creator（`frontend/react_18/src/redux/actioncreators/proPlanActionCreator.ts` 第 176–186 行）：

```ts
export function updateProPlan(id: string, data: IUpdateProPlanParams, callback: Function | null) {
  return {
    type: UPDATE_PROPLAN.BASE,
    ajax: {
      url: `/proPlan/update?id=${id}`,
      method: 'post',
      data,
      callback,
    },
  };
}
```

對照上面規則：`query: { id }` 被拿掉，`id` 直接內嵌進 `url` 模板字串（欄位對照表「POST + query」那一列的做法）；`callback` 搬進 `ajax` 物件內。這兩點跟本文件的規則一致。差異只在常數命名空間加了 `proPlan/` 前綴，這是舊範例的寫法，新頁面不要跟著加。

若照本文件規則、不參照這個舊範例，`UPDATE_PROPLAN` 應該寫成：

```js
export const UPDATE_PROPLAN = createAction('UPDATE_PROPLAN');
```

### 2. entity（legacyEntity 版 vs. R18 現有手刻版）

依本文件樣板寫法：

```js
export const gotUpdateProPlan = legacyEntity(UPDATE_PROPLAN);
```

R18 現有真實寫法是手刻版（`frontend/react_18/src/redux/actioncreators/proPlanActionCreator.ts` 第 316–328 行），沒有走共用 factory，而是每個 entity 各自複製一段幾乎相同的程式碼：

```ts
export const gotUpdateProPlan = {
  request: (): any => action(UPDATE_PROPLAN.REQUEST, {}),
  success: (response: any, req: any): any => {
    if (req.callback) {
      req.callback();
    }
    if (!req.data.queryAll) {
      return action(UPDATE_PROPLAN.SUCCESS, { response });
    }
    return [action(UPDATE_PROPLAN.SUCCESS, { response }), fetchProPlanOverviewList(req.data.queryAll)];
  },
  fail: (response: any): any => action(UPDATE_PROPLAN.FAILURE, { response }),
};
```

這正好示範了本文件在「樣板」小節解釋的「為什麼不逐頁手寫」：這段程式碼在同一個檔案裡對 `CREATE_PROPLAN`、`REMOVE_PROPLAN`、`UPDATE_PROPLAN_STATUS` 各重複了一次（只有呼叫的 action 常數不同），而且 `req.callback()` 呼叫時沒有帶任何參數，跟 R15 `callback(data, dispatch)` 的呼叫慣例不同——這是因為這批程式碼是整頁重寫時全新設計的呼叫慣例，不是保留 R15 相容性。本 skill 的 `legacyEntity` factory 要保留 R15 callback 呼叫慣例（`callback({ success: true, data: response })`），所以不能照抄這個現有寫法。

### 3. saga watcher

依本文件樣板寫法：

```js
yield takeLatest(UPDATE_PROPLAN.BASE, function* (action) {
  yield fork(ajaxRequest, gotUpdateProPlan, action.ajax, { ...GENERAL_AJAX_SETTING });
});
```

R18 現有真實寫法（`frontend/react_18/src/redux/sagas/proPlanSaga.ts` 第 85–92 行），形狀與樣板一致（差異只在 TypeScript 的型別標註）：

```ts
yield takeLatest(UPDATE_PROPLAN.BASE, function* (action: any) {
  yield fork(
    ajaxRequest as any,
    gotUpdateProPlan,
    action.ajax,
    GENERAL_AJAX_SETTING
  );
});
```

### 4. reducer

R15（`frontend/react_15/reducers/proPlanReducer.js` 第 59–68 行）：

```js
case `${UPDATE_PROPLAN}_SUCCESS`:
  return {
    ...state,
    fail: null,
  };
case `${UPDATE_PROPLAN}_FAIL`:
  return {
    ...state,
    fail: action.errors,
  };
```

R18 現有真實寫法（`frontend/react_18/src/redux/reducers/proPlanReducer.ts` 第 65–70 行、第 120–129 行）：

```ts
case CREATE_PROPLAN.SUCCESS:
case UPDATE_PROPLAN.SUCCESS:
  return {
    ...state,
    fail: null,
  };
// …
case LATEST_DETAIL_PROPLAN.FAILURE:
case CREATE_PROPLAN.FAILURE:
case UPDATE_PROPLAN.FAILURE:
case REMOVE_PROPLAN.FAILURE:
case UPDATE_PROPLAN_STATUS.FAILURE:
case FETCH_FROM_OVERVIEW_PROPLAN_LIST.FAILURE:
  return {
    ...state,
    fail: action.response.errors,
  };
```

對照上面「reducer 改寫對照表」：`` `${UPDATE_PROPLAN}_SUCCESS` `` → `UPDATE_PROPLAN.SUCCESS`、`` `${UPDATE_PROPLAN}_FAIL` `` → `UPDATE_PROPLAN.FAILURE`、`action.errors` → `action.response.errors`，三條都完全對上規則表。這裡的 `SUCCESS`／`FAILURE` case 被合併寫成多個常數共用同一段 return（`CREATE_PROPLAN.SUCCESS` 和 `UPDATE_PROPLAN.SUCCESS` 落地邏輯相同），這是既有程式碼自己的組織方式，跟本文件規則無關，遷移其他頁面時沒有義務照抄這種合併寫法，維持一個 case 對一段邏輯即可、比較不容易在之後單獨修改某個 action 的行為時互相影響。

### R18 側另一個手寫 entity 先例（非 proPlan，用來對照 dispatch 副作用寫法）

`frontend/react_18/src/redux/actioncreators/activityManagerActionCreator.js` 第 178–184 行，是「不用共用 factory、自己寫 `generateActionEntity` 覆寫 `success`」的先例，示範了本文件樣板中 `dispatch` 那一類副作用（成功後追加 dispatch 另一個 action）在 R18 現有程式碼中長什麼樣子：

```js
export const gotCreateActivitySchedule = generateActionEntity(CREATE_ACTIVITY_SCHEDULE, {
  success: (response, request) => [
    action(CREATE_ACTIVITY_SCHEDULE.SUCCESS, { response }),
    fetchActivityCalendar({ scheduleDate: request.data.scheduleDate, caseId: '' }),
    fetchActivityLocation({ companyId: request.fetchData.companyId })
  ],
});
```

`legacyEntity` factory 的 `success` handler 就是把這種手寫模式抽象成通用版本：把 `request.dispatch` 陣列裡每個函式呼叫一次，取代這裡手寫的「直接呼叫 `fetchActivityCalendar(...)`」。
