# route-and-flag — R15/R18 版本並行開關與路由掛載

本檔是 `r15-r18-migrate` skill Phase 2 步驟 3（路由與開關）的唯一依據。每個檔案與行號都經過實檔核對。R15 檔案一律保留、R15 `routes.js` 一律不動。

本檔自足，不需要參照任何外部文件。

---

## 0. 全貌：一個請求怎麼決定拿到 R15 還是 R18 bundle

`backend/routes/index.js` 的 catch-all handler（`router.get('*', …)`，`:201`）依序判斷：

| 順序 | 位置 | 判斷 | 結果 |
|---|---|---|---|
| 0 | `:203-205` | path 命中 `/locales`、`/photo`、`/build`、`/favicon` | `next()`（靜態資源，不渲染） |
| 1 | `:228-242` | **`featureControlledRoutes`**：登入中（有 `companyId`）且 path 前綴命中 | 查機構 `featureSetting` → `enable` 為真 render `index_18`，否則 render `index`（R15） |
| 2 | `:244-248` | **`feConfig.route.react_18`** 靜態清單前綴命中 | render `index_18` |
| 3 | `:249` | 皆未命中 | render `index`（R15） |

所以「加一個 R18 頁面並保留 R15」＝ **在第 1 層加一行 map**，第 2 層靜態清單完全不動（靜態清單＝已經沒有 R15 版本、永久 R18 的頁面）。

---

## 1. `featureControlledRoutes`（`backend/routes/index.js`）

### 1.1 現況與精確行號

```
192-196  /** featureSetting 控制的路由：…… key: URL 路徑前綴, value: featureSetting 的 feature 名稱 */
197      const featureControlledRoutes = {
198      };                                   ← master 上是空物件，尚無任何 entry
229      const companyId = req.session.user?.companyId;
230      const matchedFeature = Object.entries(featureControlledRoutes)
231        .find(([route]) => new RegExp(`^/${route}`).test(req.path));
232      if (companyId && matchedFeature) {
233        const [, feature] = matchedFeature;
235        const company = await companyModel.findById(companyId, { featureSetting: 1 }, { lean: true });
236        const isEnabled = company?.featureSetting?.find(f => f.feature === feature && f.enable);
237        return res.render(isEnabled ? 'index_18' : 'index', viewEngineParam);
238-241    } catch (err) { …… return res.render('index', viewEngineParam); }   ← 查詢失敗 fallback R15
```

物件形狀：`{ '<URL 路徑前綴（不含開頭斜線）>': '<featureSetting 的 feature 名稱>' }`。

### 1.2 比對方式的四個硬事實

1. **無結尾錨**：`:231` 的 `new RegExp(`^/${route}`)` 只鎖開頭。key `employee` 會同時攔到 `/employee`（員工清單）、`/employee/123`、`/employee/certification/123`…。
2. **key 是 regex 片語不是字面字串**：`:231` 直接把 key 丟進 `RegExp` 建構子，所以 `$`、`(A|B)`、`[0-9a-f]{24}` 都會被當 regex 解讀。靜態清單已有先例：`backend/config/frontend/index.js:135` 的 `'writeOff(HC|DC)/fa300'`。
3. **`.find` 取第一個命中**：物件屬性順序即判斷順序。同前綴時，長的 key 必須排在短的前面。
4. **只對已登入使用者生效**：`:232` 要求 `companyId` 存在。未登入 → 跳過整段，落到靜態清單或 R15。

### 1.3 新增一行的寫法（先例：commit `f16b6d6f3e`，`backend/routes/index.js` +3 行）

```js
  const featureControlledRoutes = {
    'case/gServiceSetting': 'gServiceSetting',
    'daycase/gServiceSetting': 'gServiceSetting',
  };
```

本 skill 的通式：`'<entry.route.fe_config_prefix>': '<entry.feature_flag.key>'`。同一個 key 可以對應多個路徑前綴（居服 / 日照共用一支 R18 頁面時）。

### 1.4 靜態清單切換（沒有登入 session 的頁面）

`backend/routes/index.js` 的判斷順序是：`:229` 先取 `req.session.user?.companyId`，`:232` `if (companyId && matchedFeature)` 才查 featureSetting——**沒有 session 就整層跳過**；接著 `:244-248` 用 `feConfig.route.react_18`（`backend/config/frontend/index.js`）的靜態清單做同樣的 `^/<item>` 前綴比對，**這層不看 session**；都沒命中才回 R15。

所以給沒登入使用者看的頁面（例：掛在 `frontend/react_15/routes.js:52` App 根層、Main 之外的 `caseMealRecord/:id`，是家屬 App 開的 RWD 頁），featureSetting 開關**永遠不會生效**，flag 開了也是 R15。這類頁面在 inventory 標 `route.switch: "static_list"`、`feature_flag` 留空物件，skill 步驟 3 改寫靜態清單、不建 flag、R18 route 不包 guard。

取捨：靜態清單是「部署即切、全機構同時生效、退回靠 revert」，沒有逐機構開關，也不能像其他頁面那樣用 featureSetting 切回 R15。前綴碰撞規則（§6）對靜態清單同樣適用，寫法一樣。

---

## 2. `backend/const/companyDefault.js` 三個 template

三個機構型別 template 各有一個 `featureSetting` 陣列，新機構建立時複製為預設值。**三處都要加，而且一律 `enable: false`**（新機構預設走 R15，由人工逐機構開啟）。

| template | 物件起點 | `featureSetting` 陣列範圍 | 陣列最後一個元素的 `}` | 插入位置 |
|---|---|---|---|---|
| `CONST.hc`（居服） | `:16` | `:164-189` | `:188` | 在 `:188` 的 `}` 後補 `,` 再接新元素，`:189` 的 `]` 之前 |
| `CONST.hcLite`（居服精簡） | `:513` | `:692-717` | `:716` | 同上，`:717` 的 `]` 之前 |
| `CONST.dc`（日照） | `:1043` | `:1145-1178` | `:1177` | 同上，`:1178` 的 `],` 之前 |

新元素形狀（與既有元素完全一致，兩層縮排在陣列內）：

```js
              {
                feature: '<entry.feature_flag.key>',
                enable: false
              }
```

先例：commit `f16b6d6f3e` 在這三個位置各加了 4 行（`gServiceSetting` / `enable: false`）。

⚠ `CONST.dc` 的陣列以 `],` 結尾（後面還有 `serviceUsageCategory`），`CONST.hc` / `CONST.hcLite` 以 `]` 結尾。不要改錯結尾符號。

---

## 3. R18 側的 route guard

### 3.1 兩個 `checkFeatureSettingEnable`（用途不同，別選錯）

| 版本 | 位置 | 形式 | 用在哪 |
|---|---|---|---|
| 共用版 | `frontend/react_18/src/shared/utils/roleMenuUtils.js:83-92`（`export` 於 `:94-98`） | hook（內部 `useSelector`，`:85`） | 子路由檔（`CaseRoute.tsx` / `DaycaseRoute.tsx` / `EmployeeRoute.tsx`）與頁面元件 |
| AppRouter 區域版 | `frontend/react_18/src/routes/AppRouter.jsx:163-168` | `useCallback`，讀同一份 `company` | **只在 `AppRouter.jsx` 內用**，不要再 import 共用版 |

兩版行為相同：`featureSetting` 為空 → 回 `true`（fail-open，見 `roleMenuUtils.js:87-89` 與 `AppRouter.jsx:164-166`）。這是既有設計，不要改。

import 寫法先例：`frontend/react_18/src/routes/EmployeeRoute.tsx:36`
使用先例：`frontend/react_18/src/routes/EmployeeRoute.tsx:69`（`const enableAttendanceManager = checkFeatureSettingEnable('attendanceManager');`）

### 3.2 頂層頁面掛 route（`frontend/react_18/src/routes/AppRouter.jsx`）

現有的 flag 變數集中宣告在 `:189-204`，每個都是「註解一行 + `useMemo`」：

```jsx
  // 是否啟用用餐紀錄功能
  const enableMealRecord = useMemo(() => checkFeatureSettingEnable('mealRecord'), [checkFeatureSettingEnable]);
```

新增時照這個形狀接在 `:204` 之後。

route 掛載先例：
- 把 flag 當 prop 往下傳：`:254`（`mealManager/*`）、`:389`（`company/*`）、`:425`（`contactBookList`）
- 條件渲染整個 `<Route>`：`frontend/react_18/src/routes/DaycaseRoute.tsx:373-378`（`{enableMedicineUsageManagement && (<Route … />)}`）
- 不符條件導 404：`frontend/react_18/src/routes/AppRouter.jsx:550`（`<Navigate to="/404" replace />`）
- 既有 wildcard（**已經註冊，不要重複加**）：`:428` `/case/*` → `CaseRoute`、`:429` `/daycase/*` → `DaycaseRoute`、`:430` `/employee/*` → `EmployeeRoute`、`:556` `/writeOffHC/*`、`:557` `/writeOffDC/*`

**必做的 guard（不是可選）**：後端只在「瀏覽器對該 path 發出真正的 HTTP request」時才判斷。使用者若已經在 R18 bundle 裡（因為別的頁面 flag 開著），點一個 SPA 內部 `<Link>` 走到新頁面時 **完全不經過後端**。因此 `AppRouter.jsx` 的 `<Route>` 必須自己再 gate 一次：

```jsx
<Route
  path={`${config.DEPLOY_PREFIX}/<路徑>`}
  element={enableXxxR18 ? <Xxx /> : <Navigate to="/404" replace />}
/>
```

同理，任何指向新頁面的 in-app 連結（sidebar 以外）也要在 flag 關閉時改成整頁 `href`（見 §4 的 `isNeedReload` 機制）。

---

## 4. case / daycase / employee 子頁 tab

### 4.1 R18 三個子路由檔的結構

| 檔 | tabs 定義 | Route 區塊 |
|---|---|---|
| `frontend/react_18/src/routes/CaseRoute.tsx` | `const tabs = () => (` `:174`，`routes` 陣列 `:178-282` | `:292-309` |
| `frontend/react_18/src/routes/DaycaseRoute.tsx` | `const tabs = () => (` `:188`，`routes` 陣列 `:191-332` | `:350-379` |
| `frontend/react_18/src/routes/EmployeeRoute.tsx` | `employeeRoutes` 陣列 `useMemo` `:103-203`，`tabs` `:205-218` | `:227-242` |

tab 物件欄位：`name`（Employee 用 `pageTitle`）、`path`（Employee 用 `subPathname`）、`isNeedReload`、`isHide`、`dropdownItems`、`component`。

### 4.2 `isNeedReload` 就是版本開關（機制在 `TabRouteWithPageTitle.tsx:52-72`）

- `isNeedReload: true` → 渲染 `<Nav.Link href={route.path}>`（`:58`）＝**整頁跳轉**，瀏覽器發 HTTP request → 後端 `featureControlledRoutes` 判斷 → 目前多半落回 R15。
- `isNeedReload: false` → 渲染 `<Link to={route.path}>`（`:63`）＝**SPA 內部導航**，直接吃 R18 的 `<Route>`。

**重點**：R18 三個子路由檔**已經預先放好所有尚未遷移的 tab**，全部 `isNeedReload: true`、且 path 已經是未來 R18 的 subPathname。遷移時 **不要新增 tab 物件**，只要把該 tab 的 `isNeedReload` 接上 flag。

待遷移 tab 的既有座標（`isNeedReload: true` 者）：

| 模組 | tab | path 內的 subPathname | `isNeedReload` 所在行 |
|---|---|---|---|
| Case | 基本資料 | `case/<id>`（無 subPathname） | `CaseRoute.tsx:182` |
| Case | 目前照顧計畫 | `case/currentCarePlan` | `CaseRoute.tsx:193` |
| Case | 照顧計畫歷史紀錄 | `case/carePlanHistory` | `CaseRoute.tsx:198` |
| Case | 每年額度設定 | `case/gServiceSetting` | `CaseRoute.tsx:203` |
| Case | 服務紀錄 | `case/hcCaseServiceRecord` | `CaseRoute.tsx:215` |
| Case | 暫停 / 結案 | `case/casePauseOrClose` | `CaseRoute.tsx:220` |
| Case | 個案班表 | `case/hcCaseShift` | `CaseRoute.tsx:225` |
| Case | 居服評鑑表單 | `case/hcAssessmentForm` | `CaseRoute.tsx:241` |
| Case | 居服員工作記錄表 | `case/hcWorkingRecord` | `CaseRoute.tsx:247` |
| Daycase | 基本資料 | `daycase/<id>`（無 subPathname） | `DaycaseRoute.tsx:195` |
| Daycase | 目前照顧計畫 | `daycase/currentCarePlan` | `DaycaseRoute.tsx:206` |
| Daycase | 照顧計畫歷史紀錄 | `daycase/carePlanHistory` | `DaycaseRoute.tsx:211` |
| Daycase | 每年額度設定 | `daycase/gServiceSetting` | `DaycaseRoute.tsx:216` |
| Daycase | 暫停 / 結案 | `daycase/casePauseOrClose` | `DaycaseRoute.tsx:233` |
| Daycase | 個案班表 | `daycase/dcCaseShift` | `DaycaseRoute.tsx:238` |
| Daycase | 活動 | `daycase/dcActivity` | `DaycaseRoute.tsx:243` |
| Employee | 基本資料 | `''`（無 subPathname） | `EmployeeRoute.tsx:117` |
| Employee | 居服班表 | `hcshift` | `EmployeeRoute.tsx:123` |
| Employee | 請假記錄（月薪制） | `leaveRecord` | `EmployeeRoute.tsx:130` |
| Employee | 請假記錄（時薪制） | `leaveRecordByShifts` | `EmployeeRoute.tsx:137` |
| Employee | 滿意度回饋 | `feedback` | `EmployeeRoute.tsx:143` |
| Employee | 居服員考核表單 | `employeeEvaluation` | `EmployeeRoute.tsx:156` |
| Employee | 薪資設定 | `salarySetting` | `EmployeeRoute.tsx:162` |

⚠ 日照「床位」tab 不在上表 —— 該 tab 不下架、不變更，R18 側維持現狀。

### 4.3 遷移一個子頁 tab 的四個動作（先例：commit `f16b6d6f3e`，9 檔）

**(a) R18 子路由檔：flag 變數 + flip `isNeedReload`**

`CaseRoute.tsx` 加 import（`:36` 附近，緊接 `TabRouteWithPageTitle` import 之後）與 flag 變數（元件內 state 宣告區之後）：

```jsx
import { checkFeatureSettingEnable } from '../shared/utils/roleMenuUtils';
…
  /** 是否啟用R18版每年額度設定 */
  const enableGServiceSetting = checkFeatureSettingEnable('gServiceSetting');
```

再把該 tab 的 `isNeedReload: true` 改成 `isNeedReload: !enable<Xxx>R18,`（注意補逗號）。

**(b) R18 子路由檔：加 `<Route>`**

在該檔的 `<Route element={tabs()}>` 區塊內加一行，path 用 `<subPathname>/:id`（R18 既有形狀，例：`CaseRoute.tsx:294-308`、`DaycaseRoute.tsx:352-378`）。Employee 的 Route 是從 `employeeRoutes` 自動產生的（`EmployeeRoute.tsx:229-240`），只要在該 tab 物件加 `component: Xxx` 並把 `isNeedReload` 接上 flag 即可，**不用手寫 `<Route>`**。

**(c) R15 Header：tab 從 `eventKey` 改成條件式 `href`**

R15 的 header 裡，`eventKey="X"` ＝「本頁內切換、由 Content 的 switch 渲染 R15 元件」；`href={...}` ＝「整頁跳走（讓後端決定版本）」。遷移就是把該項在 flag 開啟時換成 `href`：

```jsx
{enableGServiceSetting
  ? <NavItem href={`/case/gServiceSetting/${caseId}`}>每年額度設定</NavItem>
  : <NavItem eventKey="3.3">每年額度設定</NavItem>
}
```

R15 的 flag 讀取函式：`frontend/react_15/utils/featureSettingUtil.js:14-22`（`checkFeatureSettingEnable`，讀 `store.getState()`，非 hook）。

三個 header 檔與現況：

| 模組 | 檔 | 元件 | tab 元素 | 已是 `href`（R18）的示例 |
|---|---|---|---|---|
| Case | `frontend/react_15/case/components/CaseHeader.js` | `TrackedNavItem`（包裝 `NavItem` 加 GA 追蹤，定義於 `frontend/react_15/case/components/TrackedNavItem.js:21`） | `:110-137` | `:122`、`:128`、`:129` |
| Daycase | `frontend/react_15/daycase/components/CaseHeader.jsx` | `NavItem` | `:102-137` | `:114`、`:116`、`:128` |
| Employee | `frontend/react_15/employee/components/EmployeeHeader.js` | `NavItem` | `:71-85` | `:79`、`:82`、`:83`、`:84`、`:85` |

**(d) R15 Content：switch 分支加 flag 條件**

把該 `case` 分支包成「flag 關閉才渲染」，`case` 標籤本身保留（不刪 R15 程式碼）：

```jsx
    case '3.3':
      if (!enableGServiceSetting) {
        content = <GCodeStatSetting key={caseId} caseId={caseId} caseType={CaseType.HOMECARE.value} />;
      }
      break;
```

三個 content 檔與 switch 位置：

| 模組 | 檔 | switch 分支行號 |
|---|---|---|
| Case | `frontend/react_15/case/components/CaseContent.js` | `:42`(1) `:46`(3) `:49`(3.2) `:52`(3.3) `:56`(5) `:62`(6) `:70`(9) `:74`(22) `:78`(23) `:82`(24) |
| Daycase | `frontend/react_15/daycase/components/CaseContent.js` | `:50`(1) `:54`(2) `:58`(3) `:61`(3.2) `:64`(3.3) `:68`(5) `:72`(6) `:76`(7) `:80`(14) `:92`(15) `:95`(20) `:98`(23) `:102`(29) |
| Employee | `frontend/react_15/employee/components/EmployeeContent.js` | `:88`(1) `:92`(2) `:103`(3) `:107`(4) `:111`(5) `:115`(6) `:119`(10) `:123`(11) |

### 4.4 `f16b6d6f3e` 對 tab 連結做了什麼（摘要）

該 commit 是本 skill 子頁遷移的完整模板，9 個檔、+62/-7：

- `backend/routes/index.js`：`featureControlledRoutes` 加 2 行（`'case/gServiceSetting'` / `'daycase/gServiceSetting'` 都指向 `'gServiceSetting'`），另補一行 `// STEP 03未匹配到 feature 名稱，渲染 R15 bundle` 註解。
- `backend/const/companyDefault.js`：三個 template 各加 `{ feature: 'gServiceSetting', enable: false }`。
- `frontend/react_15/case/components/CaseHeader.js` / `frontend/react_15/daycase/components/CaseHeader.jsx`：import R15 版 `checkFeatureSettingEnable`、算出 `enableGServiceSetting`、把「每年額度設定」那一項改成三元式（flag 開 → `href` 整頁跳；flag 關 → `eventKey` 留在 R15）。
- `frontend/react_15/case/components/CaseContent.js` / `frontend/react_15/daycase/components/CaseContent.js`：新增/保留 `case '3.3'` 分支，內容包在 `if (!enableGServiceSetting)` 裡。
- `frontend/react_18/src/routes/CaseRoute.tsx` / `DaycaseRoute.tsx`：import `checkFeatureSettingEnable`、加 `enableGServiceSetting`、該 tab `isNeedReload: false` → `isNeedReload: !enableGServiceSetting`。
- `frontend/react_18/src/pages/case/GCodeStatSetting.tsx`：該範本 commit 內的 R18 落點（不在 master，僅供對照做法）。

**注意**：`f16b6d6f3e` 不在 master，且它的 diff context 取自較舊的 master（例如當時 `case/components/CaseHeader.js` 還沒引入 `TrackedNavItem`，`CaseContent.js` 還沒有 `case '3.3'`）。**照它的做法、不要照它的行號**；行號一律以本檔 §4.2 / §4.3 的實檔座標為準。

### 4.5 tab-reuse（零檔 tab）

**適用情境**：某個 tab 在 R15 content 殼裡不是渲染自己模組的元件，而是直接渲染**另一個模組**的元件——那個元件已經（或即將）隨提供者 entry 搬到 R18。這種 tab 在 R15 端沒有專屬的元件檔可搬，`r15_paths` 為空陣列（tab-reuse entry 的定義見 `SKILL.md` Phase 0 (2)）。

**與一般子頁的差異**：一般子頁遷移做 §4.3 的 (a)(b)(c)(d) 四個動作，(b) 是「加 `<Route>`」且 Route element 是本 entry 自己複製過來的元件。tab-reuse entry 一樣做 (a)（flag 變數 + flip `isNeedReload`）、(c)（R15 Header 三元式）、(d)（R15 Content `if (!flag)` 包裹），但 (b) 的 Route element 改成直接用 `entry.shared_deps[0].r18_equivalent` 指到的元件（提供者 entry 已經搬過去的落點），不複製、不新建元件檔；props 照 Phase 1 從 R15 content 殼逐字抄下的 JSX 原樣傳。

**5 個已知實例**（R15 content 殼座標，行號對 master 核對過；表格與元件檔皆為 `.js`）：

| 模組 | tab（eventKey） | R15 content 殼座標 | 渲染的元件檔 |
|---|---|---|---|
| Daycase | 3.2 目前照顧計畫歷史 | `frontend/react_15/daycase/components/CaseContent.js:61-63` | `frontend/react_15/case/components/PlanHistory.js`（import 於 `CaseContent.js:29`） |
| Daycase | 3.3 每年額度設定 | `frontend/react_15/daycase/components/CaseContent.js:64-66` | `frontend/react_15/case/components/GCodeStatSetting.js`（import 於 `CaseContent.js:32`） |
| Daycase | 6 結案 | `frontend/react_15/daycase/components/CaseContent.js:72-74` | `frontend/react_15/case/components/Closure.js`（import 於 `CaseContent.js:25`） |
| Daycase | 14 活動管理 | `frontend/react_15/daycase/components/CaseContent.js:80-90` | `frontend/react_15/activityCalendar/index.js`（import 於 `CaseContent.js:26`；模組層共用元件，不在 `case/` 下） |
| Employee | 2 居服班表 | `frontend/react_15/employee/components/EmployeeContent.js:92-101` | `frontend/react_15/case/components/service/index.js`（import 於 `EmployeeContent.js:17`） |

遷移時實際 import 路徑一律取 `entry.shared_deps[0].r18_equivalent`，不要自己推——提供者 entry 搬移後的實際落點才是唯一真值。

---

## 5. `feature_flag.key` 命名

- **規則**：camelCase 功能名 + `R18` 後綴。例：`caseListR18`、`hcCaseShiftR18`、`employeeListR18`、`dcActivityR18`。一眼看得出是遷移開關。
- **既有 featureSetting key 慣例**（`backend/const/companyDefault.js:164-189` / `:692-717` / `:1145-1178`）：純 camelCase、無前綴、無分隔符 —— `contractManagement`、`myDataCalendar`、`hcScheduleCard`、`attendanceManager`、`vitalSignV2`、`clipboard`、`medicineUsageManagement`、`mealRecord`、`contactBookList`。新 key 與此一致，只多 `R18` 後綴。
- key 不得與既有 key 重名（重名會讓既有功能被遷移開關連動）。加之前先在 `companyDefault.js` 與 `frontend/react_18/src/routes/AppRouter.jsx:189-204` 兩處 grep 一次。
- 同一支 R18 頁面同時服務居服與日照時，共用一個 key、在 `featureControlledRoutes` 放兩行不同前綴（先例：`f16b6d6f3e`）。

---

## 6. 前綴碰撞規則（`fe_config_prefix` 怎麼寫）

因 §1.2 的「無結尾錨」+「key 是 regex 片語」，key 的寫法必須逐案判斷。

### 6.1 判斷流程（`import-inventory` 對每個 `fe_config_prefix` 都要跑一次）

1. 取候選 key。
2. 檢查它是否為 **`backend/config/frontend/index.js:55-143` 靜態清單任一項的前綴**。
3. 檢查它是否為 **其他 entry 的 `fe_config_prefix` 的前綴**。
4. 檢查它是否為 **R15 `frontend/react_15/routes.js` 任一 path、或 `frontend/react_15/configs/sheetRoutingConfig.js` 任一 subPathname 的前綴**（同模組的子路徑會被誤攔；subPathname 互為前綴的實例見 §6.2 第四列）。
5. 任一命中 → key 必須加 `$` 結尾錨；否則用完整 subPathname、不加錨。

### 6.2 定案寫法

| 情境 | key 寫法 | 理由 |
|---|---|---|
| list 頁（居服個案清單 / 員工清單 / 日照個案清單 / 日照喘息清單） | `case$`、`employee$`、`daycase$`、`restcase$` | R15 route 就是 `/case`、`/employee`、`/daycase`、`/restcase`（`frontend/react_15/routes.js:56,84,67,78`），而 `/case/*`、`/employee/*`、`/daycase/*` 底下有大量已是 R18 的靜態子頁。不加錨會把子頁一起攔走，flag 關閉時整批退回 R15 ＝ 回歸。 |
| 基本資料 tab（R15 route 形如 `/case/:id`） | `case/[0-9a-f]{24}$`、`daycase/[0-9a-f]{24}$`、`employee/[0-9a-f]{24}$` | 路徑最後一段是 24 位十六進位 id，沒有 subPathname 可用；需錨定避免攔到 `/case/xxx/...`。 |
| 其餘子頁 tab | 完整 subPathname，**不加錨**，例 `case/hcCaseShift`、`daycase/dcActivity`、`employee/hcshift` | 這些 subPathname 之下只有 `/:id`，沒有更深的其他路徑；前提是該 subPathname 不是同模組另一個 subPathname 的前綴（是的話走下一列）。 |
| 子頁 tab 的 subPathname 是同模組另一個 subPathname 的前綴（`sheetRoutingConfig.js` 的 `employee` 群組同時有 `leaveRecord` 與 `leaveRecordByShifts`） | 完整 subPathname 加**尾斜線**、不加 `$`，例 `employee/leaveRecord/` | 裸 `employee/leaveRecord` 會前綴命中 `/employee/leaveRecordByShifts/<id>`，把另一個 tab 一起攔走；真實路徑是 `/employee/leaveRecord/<id>`，加 `$` 又完全比對不到。尾斜線是唯一同時避開兩者的寫法。 |
| 同一支頁面服務居服 / 日照 | 兩行分別寫，或用 regex 分支（先例 `backend/config/frontend/index.js:135` 的 `'writeOff(HC|DC)/fa300'`） | key 進 `RegExp`，分支語法合法。 |

### 6.3 已知的前綴外溢（證明機制真的會發生，不是理論）

靜態清單 `backend/config/frontend/index.js:117` 的 `'epidemicPreventionRecord'` 會前綴命中 `/epidemicPreventionRecordDaycare`（該路徑是實際存在的 R18 route，見 `frontend/react_18/src/routes/AppRouter.jsx:540`）。兩邊都是 R18 所以看不出問題 —— 但同樣的機制套在「一邊 R15 一邊 R18」就是 flag 關閉時子頁整批退回 R15。

### 6.4 已知且可接受的漏網

尾斜線形式 `/case/`（path 結尾多一個斜線）不會命中 `case$`，會落到第 3 層 fallback、拿到 R15 bundle。此情境視為可接受，不為它調整 regex。

### 6.5 絕對不要做的事

**不要改 `backend/routes/index.js:231` 的判斷式**（例如改成 `^/${key}(/|$)`）。那一行同時被第 2 層靜態清單以外的所有 key 使用，改動需要對整份 feConfig 做回歸，遠超本 skill 範圍。所有邊界都用 key 自身的 regex 解決。

---

## 7. sidebar 三份設定檔要同步

| # | 檔 | 角色 |
|---|---|---|
| 1 | `backend/config/sidebarConf.js` | source of truth，export 函式 `(option, userRole) => sidebar`，後端依機構設定與角色產生選單存進 session |
| 2 | `frontend/react_15/configs/sidebarConf.js` | 檔頭註解自稱「從 backend 完整複製過來」，實際已與 source 漂移。消費者：`frontend/react_15/main/components/SideBar.js:14`、`frontend/react_15/main/components/Header.js:23`、`frontend/react_15/error/index.js:14` |
| 3 | `frontend/react_18/config/sidebarConf.js` | 同上（`:20` 有相同的「完整複製」註解）。消費者：`frontend/react_18/src/pages/mainFrame/components/Sidebar.jsx:31`、`frontend/react_18/src/containers/Header/Header.tsx:37` |

三份的 entry 形狀完全一致（比對 `backend/config/sidebarConf.js:43-61` 與 `frontend/react_18/config/sidebarConf.js:63-81`）：

```js
      {
        memo: '<中文選單名>',
        to: '/<路徑>',
        navItem: '<選單識別字>',
        containerParams: {
          allowRole: [<角色位元值…>],
          hidden: 'true'
        },
        navItemParams: {},
        new: true,            // 選填：顯示 NEW 標記
        pageAuthorities: [    // 選填：頁面內細部權限
          { item: '<識別字>', memo: '<說明>', allowRole: [...], hidden: true }
        ],
      },
```

**規則**：
- 只有 `entry.sidebar_entries` 非空時才動 sidebar。**遷移既有頁面通常不需要動** —— `to` 路徑不變、選單項目不變，backend 依 path 決定 bundle，sidebar 完全無感。
- 真的需要新增條目時，**三份都要加，形狀與 `allowRole` 一字不差**。只加一份的症狀是「某些頁面看得到選單、某些看不到」。
- `hidden: 'true'` 是字串不是布林（既有慣例，照抄）。

---

## 8. R15 側的不變量

- **R15 檔案一律不刪**：遷移完成後 R15 的頁面元件、actions、reducers、樣式全部留在原處。回退手段是把 `featureSetting` 的 `enable` 關回 `false`，不是 revert。
- **`frontend/react_15/routes.js` 不動**：不新增、不刪除、不改 path。R15 route 必須繼續存在，否則 flag 關閉時後端 render 了 R15 bundle 卻沒有對應 route。
- **`frontend/react_15/configs/sheetRoutingConfig.js` 不動**（除非 §7 明確要求）。
- R15 只允許以下兩類改動：§4.3(c) header 的三元式、§4.3(d) content switch 的 `if (!flag)` 包裹。其餘 R15 程式碼一行都不改。

---

## 9. 完成檢查清單（Phase 2 步驟 3 收尾自檢）

- [ ] `backend/routes/index.js` 的 `featureControlledRoutes` 多了一行（或多行），key 依 §6 判斷過前綴碰撞（`type: shared` 跳過；`route.switch: static_list` 改驗靜態清單有加）
- [ ] `backend/const/companyDefault.js` 三個 template（`:164-189` / `:692-717` / `:1145-1178`）都加了同一個 key、`enable: false`，逗號與結尾符號正確（`type: shared` 跳過；`route.switch: static_list` 改驗靜態清單有加）
- [ ] R18 側 flag 變數已宣告（頂層頁面在 `AppRouter.jsx:189-204` 之後；子頁在該子路由檔元件內）（`type: shared` 跳過；`route.switch: static_list` 改驗靜態清單有加）
- [ ] 頂層頁面：`<Route>` 已加、且 `element` 有 flag gate（§3.2）（`type: shared` 跳過；`route.switch: static_list` 改驗靜態清單有加）
- [ ] 子頁：對應 tab 的 `isNeedReload` 已改成 `!<flag>`，`<Route>` 已加（Employee 改為補 `component:`）
- [ ] R15 header 該 tab 已改成三元式；R15 content switch 該分支已包 `if (!flag)`
- [ ] R15 檔案沒有被刪；`frontend/react_15/routes.js` 沒有被改
- [ ] sidebar：`sidebar_entries` 為空 → 三份都沒動；非空 → 三份都動且形狀一致
- [ ] key 命名符合 camelCase + `R18`，且未與既有 featureSetting key 重名
