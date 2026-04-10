---
name: r15-r18-verify
description: "R15 到 R18 頁面遷移的功能等價性驗證。逐層比對 Redux、元件行為、錯誤處理等，產出結構化報告並修復發現的 bug。當使用者提到 /r15-r18-verify、「驗證 r18」、「比對 r15 r18」、「遷移驗證」時觸發。"
version: 1.3.0
---

# R15→R18 功能等價性驗證

對已完成 R15→R18 遷移的頁面，從程式碼角度系統性驗證功能等價性。

## 驗證深度分層（L1-L4）

驗證不是「有沒有檢查過」，而是**檢查了多深**。四層對應四種不同的 bug：

| 層 | 檢查內容 | 容易抓到的 bug |
|---|---|---|
| **L1 合約層** | action types / API endpoints / state shape / props 介面 | 漏 action、URL 錯、參數型別不符 |
| **L2 結構層** | 元件拆分、欄位存在性、formatter/sort 函式簽名、lifecycle → useEffect 對應 | 欄位丟失、元件拆錯、useEffect 依賴錯 |
| **L3 行為層** | 按鈕 click → action → saga → reducer 完整鏈路、Modal 開/關時機、錯誤流、副作用 | **Modal 不自動關**、**fail 殘留**、**Redux ↔ local state 脫節**、競態 |
| **L4 等價性層** | 相同輸入資料兩版本渲染結果是否相同 | 格式化差異、filter/sort 行為差異、邊界值 |

**階段 1 ≈ L1，階段 2 ≈ L2，階段 3 ≈ L3**。**L4 靜態比對抓不到**，必須手測（flag 開啟後並列兩版本跑真實 data）。

完成 L1+L2 不代表通過驗證 — 過去實際案例顯示 L3 才是遷移最容易失分的地方，尤其 Redux → local state 遷移時。

## 前置條件

- R18 頁面已完成開發
- 有明確的 R15 原始元件可供比對
- 知道 Jira 編號（用於報告檔名）

## 輸入

使用者需提供或由 skill 自動識別：
1. **目標頁面**：哪個功能/頁面要驗證（例：每年額度設定 GCodeStatSetting）
2. **Jira 編號**：從 branch 名稱自動取得，或使用者指定

## 輸出

- 結構化比對報告：`.claude/{JIRA_ID}-r15-r18-comparison.md`
- 同份報告作為 PR body（使用 `gh pr edit --body "$(cat {report})"` 覆蓋）
- 發現的 bug 直接修復

---

## 執行流程

### 階段 0：確定範圍

**CRITICAL**：驗證對象是**整個 branch 相對 master 的遷移**，不是單一 commit。即便最新 commit 看起來只改了 feature flag，也必須往前追到遷移本體 commit。

#### 0.1 列出 branch 所有改動

```
git log master..HEAD --oneline
git log master..HEAD --name-only --pretty=format:"%h %s" | head -100
git diff master..HEAD --stat
```

#### 0.2 識別 commit 性質（分類）

將 branch 的每個 commit 分成三類：

| 類別 | 特徵 | 驗證優先序 |
|------|------|-----------|
| **遷移本體** | 新增 `react_18/` 檔案 + 刪除/修改 `react_15/` 對應檔案 | P0（必驗）|
| **Feature Flag 並行切換** | 加 `featureControlledRoutes` / `checkFeatureSettingEnable` / companyDefault flag / 還原已刪除的 R15 檔案 | P1 |
| **Bug fix / Refactor** | 其他修正、重構 | P2 |

**若 branch 只有 P1（feature flag，無遷移本體）**：改跑「feature-flag-verify 模式」（階段 2 重點比對 flag 切換邏輯與 backend/前端三層一致性，階段 1/3 可精簡）。

**若 branch 含 P0（遷移本體）**：以 P0 為主要驗證對象，P1 作為附加驗證，兩者都要做。

#### 0.3 取得 R15 ground truth（舊版基準）

**關鍵**：R15 原始元件可能在 branch 中已被刪除或修改，不能直接讀 `HEAD` 的 R15 檔案當基準。

| 情境 | 取得方式 |
|------|---------|
| R15 檔案仍在 master | `git show master:{path}` 或直接讀 `master` 分支的檔案 |
| R15 檔案在 branch 中被刪除 | `git show {delete-commit}^:{path}` — 找出刪除該檔的 commit，取其父 commit 版本 |
| R15 檔案在 branch 中被修改 | `git show master:{path}` 取遷移前的版本 |
| R15 檔案在 branch 中被還原（feature flag 並行） | `git show master:{path}`（如果 master 還有）或 `git show {delete-commit}^:{path}` |

找刪除 commit 的方法：
```
git log master..HEAD --diff-filter=D --name-only -- react_15/
git log --all --full-history -- {path}
```

#### 0.4 建立對應關係表

產出這張表，作為後續階段的輸入：

| R15 原始（舊） | R18 新 | 取得方式 | 涵蓋 commit |
|---|---|---|---|
| `master:react_15/.../PlanHistory.js` | `HEAD:react_18/src/pages/case/PlanHistory.tsx` + ... | `git show master:...` | ac9d8b..., e34614... |
| `master:react_15/.../planAction.js` | `HEAD:react_18/.../carePlanHistoryActionCreator.ts` + saga + reducer | 同上 | 同上 |

#### 0.5 確認比對範圍

列出本次要驗的清單：
- Redux 模組（action creator / reducer / saga / state shape / IReducerState）
- 元件（主元件 + 拆分後的子元件）
- 路由（CaseRoute / DaycaseRoute / sheetRoutingConfig）
- Feature flag 相關（companyDefault / featureControlledRoutes / checkFeatureSettingEnable）

### 階段 1：Redux / Props 合約比對

用 2 個平行 Explore agent 分別分析 R15 和 R18 的 Redux 層。

#### Checklist

- [ ] **Action Types** — 逐一比對，確認每個 R15 action 在 R18 都有對應
- [ ] **State Shape** — reducer initialState 每個欄位比對，標記 Redux→local state 的合理遷移
- [ ] **API Endpoints** — 每個 CRUD 操作的 endpoint、HTTP method、參數
- [ ] **非同步處理** — R15 middleware vs R18 saga 的行為等價性（成功後 re-fetch、callback 等）

### 階段 2：元件行為清單比對

用 2 個平行 Explore agent 分別分析 R15 和 R18 的元件。

#### Checklist

- [ ] **元件對應關係** — 哪個 R15 class 對應哪個 R18 functional component
- [ ] **使用者行為** — 每個按鈕、表單提交、Modal 開關的觸發方式
- [ ] **生命週期** — componentDidMount/WillUnmount/WillReceiveProps vs useEffect 依賴陣列
- [ ] **Business Logic** — 計算邏輯、資料轉換、工具函式
- [ ] **表格/列表** — 欄位、formatter、排序、過濾、分頁
- [ ] **Redux State 使用** — mapStateToProps vs useSelector，確認沒有死 prop 也沒有遺漏

### 階段 3：風險導向深入比對（L3 行為層）

**依頁面特性選擇適用項目**，但以下三項是 **Redux → local state 遷移類**頁面的 **MUST**，不得省略：

#### MUST-CHECK 1：Modal 自動關閉機制（最常見退化）

R15 class + Redux 常見模式：
- Modal `show={this.props.modal}` 讀 Redux
- reducer 在 `UPDATE_XXX.SUCCESS` 裡直接設 `modal: false`
- 使用者儲存成功 → reducer 把 modal 設 false → Modal 自動關

**R18 遷移到 local useState 時的陷阱**：
- 元件改用 `const [modal, setModal] = useState(false)`
- reducer 的 `modal: false` 與 local state 脫鉤 → **Modal 不會自動關**
- 使用者體驗：儲存完 Modal 還停在那裡，以為沒成功

**必查步驟**：
1. `grep "_SUCCESS" {reducer}` 看 R15 reducer 有沒有在 success case 設 `modal: false` / `open: false` / `visible: false` 等
2. 若有，檢查 R18 Modal 狀態是 local 還是 Redux
3. 若是 local，必須加同步機制：
   - 選項 A（推薦）：**R18 仍用 Redux modal state** 對齊 R15，不要混用
   - 選項 B：保留 local state，但用 `useEffect([reduxModal])` 監聽 Redux modal 變化同步
4. 同步檢查 `IReducerState` 有沒有包含 `modal` 欄位（reducer 有但 interface 漏寫是常見問題）

#### MUST-CHECK 2：Modal useState 初始值 stale

R18 functional component 的 `useState(data.xxx)` **只在首次 mount 跑一次**。若 Modal 不 unmount 而是用 `show` 控制顯示，切換編輯不同 row 時**會顯示上一次的資料**。

**必查步驟**：
1. 看 R15 父元件有沒有用 `{profile._id && <Modal .../>}` 條件渲染讓 Modal 隨資料存在而 mount/unmount
2. 若有，R18 必須保留相同模式，並加 `key={data._id}` 雙保險
3. 或者把 Modal 內的初始值邏輯改用 `useEffect([data])` 同步 local state

#### MUST-CHECK 3：cleanFail on Modal hide

R15 `AlertMessage` 常有 `clean` prop 讓使用者手動關閉錯誤；R18 若改用純顯示元件，必須在 Modal `onHide` 時 `dispatch(cleanFail())`，否則下次開啟會殘留舊錯誤。這是 f16b6d6f3e (GCodeStatSetting) 與 CUP-179 (PlanHistory) 兩次遷移都發生過的 bug。

---

**其他可選深入項目**（依頁面特性選擇）：

| 項目 | 適用時機 | 比對重點 |
|------|---------|---------|
| **Props 傳遞鏈** | 元件有跨路由的 props（如 caseType） | 動態值 vs 硬編碼、未載入時的 fallback |
| **跨頁狀態觸發** | 有從其他頁面觸發 Modal/動作的機制 | 觸發源、導航方式、接收處理、清除時機 |
| **錯誤處理** | 有 CRUD 操作的頁面（幾乎都有） | fail 格式、UI 顯示、cleanFail 清除時機 |
| **日期/時間邏輯** | 有日期選擇器或時間相關計算 | 驗證函數、初始值、自動計算、提交格式、邊界案例 |
| **Feature Flag** | 有版本切換控制 | tab 顯示/隱藏、導航模式、fallback |
| **權限控制** | 有角色相關的顯示/操作限制 | R15 的權限檢查在 R18 是否保留 |
| **i18n** | 有多語系支援 | 翻譯 key 是否一致 |
| **檔案上傳/下載** | 有 file 相關操作 | FormData 組裝、API 參數、回應處理 |
| **第三方元件** | 有 react-bootstrap-table、react-datetime 等 | 版本差異、props API 差異 |
| **WebSocket/即時更新** | 有 real-time 功能 | 訂閱/取消訂閱的生命週期 |

### 階段 4：修復與產出

1. 修復發現的 bug
2. 產出結構化報告到 `.claude/{JIRA_ID}-r15-r18-comparison.md`
3. 更新報告的結論區段

---

## 報告格式

報告同時作為 `.claude/{JIRA_ID}-r15-r18-comparison.md` 和 **PR body** 的內容（直接用 `gh pr edit --body` 覆蓋）。

```markdown
# R15 vs R18 {頁面名稱} 功能等價性驗證報告

> 驗證日期：{date}
> 分支：{branch}（{N} commits）
> 驗證深度：L1-L3（L4 需手測）

## 階段 0：範圍

### Commit 分類
（表格：Commit hash | 類型 P0/P1/P2 | 描述）

### 元件對應
（表格：R15 原始路徑 | R18 新路徑）

## 階段 1：Redux / Props 合約比對

### Action Types 對照
（表格：Action Type | R15 | R18 | 等價 ✅/⚠️/❌）

### State Shape 對照
（表格：欄位 | R15 來源 | R18 來源 | 等價）

### API Endpoints 對照
（表格：Endpoint | Method | R15 | R18 | 等價）

## 階段 2：元件行為清單比對

### 使用者行為對照
（表格：操作 | R15 行為 | R18 行為 | 等價）

### 生命週期對照
（表格：R15 生命週期 | R18 等價 | 等價）

### 居服 vs 日照差異
（表格：差異點 | R15 處理 | R18 處理 | 等價）
— 僅居服/日照並存時需要此區段

## 階段 3：深入比對

### MUST-CHECK 1：Modal 自動關閉機制 ✅/❌
（描述 R15 機制 → R18 機制 → 結論）

### MUST-CHECK 2：useState 初始值 stale ✅/❌
（描述 key prop / 條件渲染策略 → 結論）

### MUST-CHECK 3：cleanFail on Modal hide ✅/❌
（描述兩版本 AlertMessage 用法 → 結論）

### Feature Flag 三層一致性 ✅/❌
（表格：層 | 設定 | 狀態）
— 僅有 P1 feature flag commit 時需要

### {其他依頁面特性選用的項目} 🔴/✅
（描述問題與修復狀態）

## 結論

### 需修復的問題
（表格：# | 問題 | 嚴重度 | 位置 | 狀態 ✅已修復/🔴待修）

### 已在之前 commit 修復的問題
（表格：# | 問題 | Commit | 說明）
— 僅當 branch 有 bug fix commit 時需要

### 合理的架構改善
（列表：本次遷移帶來的結構改善）

### L4 手測建議
（checkbox 列表：需要手動測試的場景）
```

---

## 平行化策略

### Agent 分派總覽

| 階段 | Agent 數 | 角色 | 信任等級 |
|------|---------|------|---------|
| 階段 1 | 4 | R15 reducer / R15 saga·middleware / R18 reducer / R18 saga | 中 — 結論需 double check |
| 階段 2 | 4 | R15 元件 / R15 表格 / R18 元件 / R18 表格 | 中 — 結論需 double check |
| 階段 3 | 0+1 | MUST-CHECK 主流程親自做；做完後派 1 個 adversarial reviewer | 高（主流程）/ 輔助（reviewer） |

### Agent Prompt Template

每個 agent 的 prompt 必須包含以下結構：

```
你是 R15/R18 遷移驗證的 {角色名} agent。

## 任務
分析 {R15|R18} 版本的 {Redux 層|元件層}，產出結構化表格。

## 必讀檔案
{列出具體檔案路徑，用 git show 取得的要標明}

## 輸出格式（嚴格遵守，不可省略欄位）

### {階段 1 用} Action Types
| Action Type | 對應函式 | API Endpoint | HTTP Method | 成功後副作用 |

### {階段 1 用} State Shape
| 欄位名 | 型別 | 初始值 | 哪些 action 會修改 |

### {階段 1 用} 非同步處理
| Action | middleware/saga 位置 | 成功回調 | 失敗回調 | re-fetch 行為 |

### {階段 2 用} 元件清單
| 元件名 | 類型(class/functional) | 主要 props | 內部 state |

### {階段 2 用} 使用者行為
| 操作（按鈕/表單/Modal） | 觸發函式 | dispatch 的 action | 成功後 UI 行為 |

### {階段 2 用} 生命週期
| 生命週期方法/useEffect | 依賴 | 做什麼事 | cleanup |

### {階段 2 用} 表格欄位
| 欄位名 | dataField | formatter | filterValue | sortFunc 簽名 |

## 禁止事項
- 不要下結論說「等價」或「不等價」— 只列事實，由主流程比對
- 不要省略你認為「不重要」的欄位
- 不要猜測另一版本的行為
```

#### 階段 1 細分 agent（4 個平行）

| Agent | 職責 | 必讀檔案 | 輸出表格 | 額外指示 |
|-------|------|---------|---------|---------|
| R15 reducer | state shape + action 處理 | reducer.js（`git show master:{path}`） | State Shape、Action→欄位變化對照 | 標記 SUCCESS case 裡設定 `modal`/`open`/`visible` 為 false 的分支 |
| R15 saga/middleware | 非同步流 + 副作用 | middleware.js 或 saga.js + action creator（`git show master:{path}`） | Action Types、API Endpoints、成功/失敗回調、re-fetch 行為 | 標記 success handler 裡的所有副作用（dispatch 其他 action、callback 呼叫） |
| R18 reducer | state shape + action 處理 | reducer.ts、IReducerState | State Shape、Action→欄位變化對照 | 標記 IReducerState 是否包含 modal 相關欄位；標記 initialState 與 R15 的差異 |
| R18 saga | 非同步流 + 副作用 | saga.ts、actionCreator.ts | Action Types、API Endpoints、成功/失敗回調、re-fetch 行為 | 標記 saga 裡的 callback 參數（如 `action.payload.onSuccess`）和 put 的所有 action |

> **為什麼拆成 4 個而不是 2 個**：reducer 和 saga 的關注點不同 — reducer 管 state 變化，saga 管非同步副作用。合在一起時 agent 容易顧此失彼，尤其在 saga success handler 的副作用清單上漏列。

#### 階段 2 細分 agent（4 個平行）

| Agent | 職責 | 必讀檔案 | 輸出表格 | 額外指示 |
|-------|------|---------|---------|---------|
| R15 元件 | 元件結構 + 使用者行為 + 生命週期 | 主元件 + Modal 元件（`git show master:{path}`） | 元件清單、使用者行為、生命週期 | 列出所有 mapStateToProps/mapDispatchToProps 欄位；標記條件渲染的 Modal（`{condition && <Modal/>}`） |
| R15 表格 | 表格欄位 + formatter + filter + sort | 主元件中的表格區段（`git show master:{path}`） | 表格欄位（含 dataField、formatter、filterFormatted、sortFunc 完整簽名） | 特別標記 `filterFormatted: true` 的欄位和 sortFunc 參數用法（v1: a/b 是整 row） |
| R18 元件 | 元件結構 + 使用者行為 + hook | 主元件 + Modal 元件 + custom hook | 元件清單、使用者行為、生命週期（useEffect） | 列出所有 useSelector/useDispatch 使用；標記 useState 初始值來源（props/常數/計算值） |
| R18 表格 | 表格欄位 + formatter + filter + sort | 主元件中的表格區段 | 表格欄位（含 dataField、formatter、filterValue、sortFunc 完整簽名） | 特別標記有無 `filterValue` 函式和 sortFunc 參數用法（v2: a/b 是 cell 值） |

> **為什麼拆出表格 agent**：react-bootstrap-table v1→v2 的 filter/sort 介面差異是歷史上最常出 bug 的地方（filterFormatted→filterValue、sortFunc 簽名變化），專門拆一個 agent 確保每個欄位都有列出完整的 formatter/filter/sort 配置。

### Agent 回來後的驗證規則

Agent 產出的表格是**原始素材**，不是結論。主流程必須執行以下 double check：

#### 必須自己讀原始碼驗證的結論

| 結論類型 | 為什麼不能信 agent | 驗證方式 |
|---------|-------------------|---------|
| 「某 action 在 R18 有對應」 | agent 可能把名稱相似但行為不同的 action 配對 | 讀兩邊 action creator，確認參數和 API call 一致 |
| 「Modal 開關機制等價」 | agent 不理解 Redux vs local state 的同步問題 | **階段 3 MUST-CHECK 1 親自做** |
| 「生命週期已正確遷移」 | agent 可能漏看 useEffect 依賴陣列或 cleanup | 逐一比對 componentDidMount/WillUnmount → useEffect |
| 「表格 formatter 等價」 | agent 看得到函式名但不一定看懂 v1→v2 介面差異 | 確認 filterValue/sortFunc 簽名是否符合 v2 規格 |
| 「成功後副作用一致」 | **歷史案例：agent 誤判 endDate 自動計算等價** | 讀 saga 的 success handler，比對 R15 middleware 的 success 分支 |
| 「欄位沒有遺漏」 | agent 可能漏列 computed props 或 derived state | 對照 mapStateToProps 每個欄位，確認 R18 useSelector 都有取 |

#### 可以信任 agent 的結論

| 結論類型 | 前提條件 |
|---------|---------|
| 「API endpoint URL 和 HTTP method」 | agent 有列出具體 URL 字串和 method |
| 「元件拆分對應關係」 | agent 有列出檔案路徑 |
| 「Action type 字串常數」 | agent 有列出完整字串值 |
| 「import 來源」 | 事實陳述，不涉及行為判斷 |

### 階段 3：MUST-CHECK 執行規則

> **⚠️ 階段 3 的三個 MUST-CHECK 不可委託 agent，必須主流程親自讀碼。**
>
> 理由：MUST-CHECK 涉及跨檔案的狀態同步判斷（Redux ↔ local state、reducer ↔ 元件、saga callback ↔ UI 更新），
> agent 只看單一版本無法判斷兩版本的行為是否等價。歷史案例中 agent 在這三項的誤判率最高。
>
> 具體做法：
> 1. **MUST-CHECK 1（Modal 自動關閉）**：主流程自己 `grep "_SUCCESS"` reducer，逐一檢查 modal 欄位變化，再讀 R18 對應元件確認 local state 同步機制
> 2. **MUST-CHECK 2（useState stale）**：主流程自己讀 R15 父元件的條件渲染邏輯，再讀 R18 對應元件確認 key prop 或 useEffect 同步
> 3. **MUST-CHECK 3（cleanFail on hide）**：主流程自己讀 R15 AlertMessage 的 clean prop 用法，再讀 R18 Modal onHide handler 確認有無 dispatch cleanFail

### 階段 3 後：Adversarial Review（反駁驗證）

主流程完成 MUST-CHECK 1/2/3 並寫下結論後，派 **1 個 adversarial reviewer agent** 嘗試推翻結論。

#### Adversarial Reviewer Prompt Template

```
你是 R15→R18 遷移驗證的 adversarial reviewer。你的工作是**嘗試推翻**主流程的結論。

## 背景
主流程已完成三項 MUST-CHECK 並得出以下結論：
{貼入主流程的三項結論，含具體檔案路徑和行號}

## 你的任務
對每項結論，嘗試找出主流程可能遺漏或判斷錯誤的地方：

1. **Modal 自動關閉**：主流程說 {結論}。
   - 檢查：是否有其他 SUCCESS action 也應該關閉 Modal 但被遺漏？
   - 檢查：saga 的 callback 是否真的會被執行（有無條件分支跳過）？
   - 檢查：有無競態可能（兩個 action 同時 dispatch 導致 Modal 狀態衝突）？

2. **useState stale**：主流程說 {結論}。
   - 檢查：除了主流程看的 Modal，有無其他元件也用了 useState(props.xxx) 但沒被檢查到？
   - 檢查：key prop 的值是否真的會隨資料變化（有無用 index 當 key 的情況）？

3. **cleanFail on hide**：主流程說 {結論}。
   - 檢查：除了 Modal onHide，有無其他離開路徑（路由切換、tab 切換）也該清 fail？
   - 檢查：cleanFail dispatch 的時機是否正確（在 onHide 而非 onExited）？

## 必讀檔案
{列出 R18 的 reducer、saga、所有 Modal 元件路徑}

## 輸出格式
對每項結論，回答：
| 結論 | 同意/反對 | 理由（附行號） | 建議動作 |

## 規則
- 你的目標是找漏洞，不是確認正確。預設立場是「主流程可能漏了什麼」
- 如果真的找不到問題，明確說「無法推翻，結論成立」— 不要硬編理由
- 不要重複主流程已經做過的檢查，專注在主流程**沒覆蓋到的角度**
```

#### 處理 Adversarial Review 結果

| Reviewer 回應 | 主流程動作 |
|--------------|-----------|
| 「反對 + 具體行號」 | 主流程**必須**讀該行號驗證，確認是真問題還是 reviewer 誤判 |
| 「反對 + 無具體行號」 | 忽略 — 沒有行號的反對等於猜測 |
| 「無法推翻」 | 結論確認，進入階段 4 |

> **為什麼需要 adversarial review**：主流程在 MUST-CHECK 時已經形成了判斷，容易產生確認偏誤（confirmation bias）。
> 獨立的 reviewer 從「嘗試推翻」的角度出發，能補上主流程視角盲區。
> 但 reviewer 的反對意見仍需主流程親自驗證 — 不是 reviewer 說有問題就有問題。

## 注意事項

- R15 class component 的 componentWillReceiveProps → R18 可能對應多個 useEffect，需逐一確認
- Modal 狀態從 Redux 移到 local state 是常見且合理的遷移，不算 bug
- 死 prop（R15 取了但沒用的 state）不需要在 R18 保留
- **一定要讀 R15 原始碼驗證**，不要只靠 agent 報告的結論（本次就有 agent 誤判 ModifyModal endDate 自動計算的案例）
- **驗證範圍是整個 branch，不是單一 commit**（2026-04-09 修正）：即便最新 commit 是 feature flag 切換，也要往前追遷移本體 commit；若 R15 檔案在 branch 中已被刪除，必須用 `git show {delete-commit}^:{path}` 取得刪除前版本當 ground truth，不能只讀 HEAD 的 R15 檔案
- **feature flag 並行切換 commit 不等於遷移等價性驗證**：flag 切換只驗「切換機制本身正確」，遷移本體的等價性（Redux/元件/生命週期/表格/日期邏輯）要對 P0 commit 獨立做
- **L1+L2 完成不代表驗完**：Redux 合約對齊 + 元件欄位對齊只是 L1/L2，還有 L3 行為層（Modal 開關鏈路、成功後副作用、錯誤狀態流）才是最常出 bug 的地方，必做 MUST-CHECK 1/2/3
- **react-bootstrap-table v1 → v2 filter 陷阱**：R15 `filterFormatted` 會對 formatter 後的字串比對；R18 `textFilter` 預設對原始 cell 值比對。若欄位是物件（例如 `{quota: 50000}`）或 ISO 日期字串，必須加 `filterValue: (cell) => formattedString` 讓 filter 對格式化後字串比對，否則 filter 會壞掉或顯示 `[object Object]`
- **react-bootstrap-table v1 → v2 sortFunc 簽名陷阱**：v1 `sortFunc(a, b, order, field)` 的 a/b 是整 row；v2 `sortFunc(a, b, order, dataField)` 的 a/b 是該欄位 cell 值。R15 寫 `a[field].quota`，R18 要改 `a.quota`
- **reducer 有 modal 欄位但 IReducerState 漏寫**：常見問題。修 MUST-CHECK 1 時順手檢查
- **useState(props.xxx) 初始值陷阱**：只在 mount 跑一次；若 Modal 不 unmount，切換不同 row 會顯示舊資料。參考 MUST-CHECK 2
- **AlertMessage 介面變化**：R15 `<AlertMessage fail clean={cleanFail} />` 有內建關閉鈕；R18 `<AlertMessage message={[...]} />` 是純顯示。從 R15 → R18 遷移時，若父元件沒主動 dispatch cleanFail，錯誤會殘留
- **L4 必須手測**：展開列真實資料、日期格式化、filter 行為、排序連點 asc/desc — 這層靜態比對不出來，需要開 browser 並列 R15/R18 跑同一筆資料確認
