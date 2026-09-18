# 合約抽取規格

本檔定義 Phase 1（合約抽取）用的四張表格格式、分群規則、內嵌 agent prompt、信任規則，以及 Phase 3(b)（靜態比對）用的檢查表。所有內容針對本 skill 的遷移方式——**保留 class、不轉 hooks、命名沿用 R15、機制沿用 R18**——改寫，不是通用遷移驗證清單的逐字搬移。

## Phase 1：四張合約表

Phase 1 的目的是在動手改程式碼前，先把 R15 原始檔案的行為窮舉成表格，作為 Phase 2 機械轉換與 Phase 3 等價性比對的依據。四張表對應四種不同的分析單位：

### 表一：逐函式表

| 函式 | 輸入（params / 讀取的 props·state·refs） | 輸出（return / setState 欄位 / dispatch / callback / DOM 副作用） | 呼叫者 |
|---|---|---|---|

- 「函式」含 class method、獨立 helper function、事件 handler。
- 「輸入」列出實際讀取的來源，不是型別宣告——例如某函式讀了 `this.props.caseId` 就寫 `props.caseId`，不要只寫「props」。
- 「輸出」凡是有副作用都要列：`return` 值、`this.setState({...})` 改了哪些欄位、`dispatch(...)` 的 action、呼叫了哪個 callback、直接操作 DOM（如 `this.refs.xxx.focus()`）。
- 「呼叫者」列出檔案內或跨檔的呼叫點（`路徑:行號`），找不到呼叫點的獨立函式寫「未找到呼叫者」。

### 表二：action 表

| type | url | method | data 形狀 | query | headers | file 欄位 | callback / dispatch / redirect / lastExcutionFunction |
|---|---|---|---|---|---|---|---|

- 每一個 R15 ajax action（middleware 觸發的那種）各佔一列。
- 「data 形狀」寫實際送出的物件欄位，不是變數名（例如 `{ caseId, startDate, endDate }`）。
- 「callback / dispatch / redirect / lastExcutionFunction」四個都要各自標記有沒有用到，沒用到寫「無」；有用到的要抄出實際內容（callback 內做了什麼、dispatch 了哪個 action、redirect 的目標與是否帶 `{key}` 取代、lastExcutionFunction 呼叫了什麼）。
- 「headers」「file 欄位」若該 action 用了 R18 saga 基礎層不支援的欄位（自訂 headers、`file1`/`file2`/`file3`/`files` 多檔、`authorizationToken`），照實填，不要因為「反正不支援」就跳過不填——Phase 2 要靠這欄判斷是否 `blocked(unsupported_ajax_field)`。

### 表三：reducer 表

| 欄位 | 型別 | 初始值 | 哪些 case 修改 |
|---|---|---|---|

- 「欄位」是 `initState`/`initialState` 的每一個 top-level 欄位（巢狀物件只展到有獨立語意的那一層，不必逐一展開每個葉節點）。
- 「哪些 case 修改」列出所有會動到該欄位的 action type，並標記修改方式（整欄覆寫 / 部分合併 / push 進陣列等）。修改為 `false`/`null` 這類「關閉」語意的一定要標，這是 Modal 開關檢查的資料來源。

### 表四：元件表

| props | state | lifecycle | handlers | refs | 第三方元件用法 |
|---|---|---|---|---|---|

- 「props」列 `mapStateToProps`/`mapDispatchToProps` 或 `PropTypes` 宣告的每個欄位，並標記是否為死 prop（有宣告但 render/method 內找不到使用點）。
- 「state」列 `this.state` 初始值來源——是常數、是 `this.props.xxx`、還是 `this.props.xxx` 加預設值。來源是 `this.props.xxx` 的要特別標記，Phase 3(b) 的 MUST-CHECK 2 要用。
- 「lifecycle」逐一列出用到的生命週期方法（`componentDidMount`/`componentWillReceiveProps`/`UNSAFE_componentWillReceiveProps`/`componentWillUnmount` 等）與各自做的事。
- 「handlers」列使用者互動的 handler（按鈕 onClick、表單 onSubmit、Modal onHide 等），標記各自 dispatch 或呼叫了什麼。
- 「refs」列 string ref 與 `createRef`/`this.refs.xxx` 的用法（本次遷移允許沿用 string ref，不必轉 callback ref）。
- 「第三方元件用法」列 `react-bootstrap`/`react-bootstrap-table`/`react-select`/路由等第三方元件的 props 用法，供對照表比對版本差異。

## 分群規則

Phase 1 的合約抽取用 subagent 平行處理，依檔案性質分三群，**每群最多 4 個檔案**，超過 4 個就再切一群（同群內檔案數不得超限，不是取平均）：

| 群 | 涵蓋範圍 | 產出表格 |
|---|---|---|
| 元件檔 | 主元件 + 拆分出的子元件、Modal 元件 | 表一（逐函式）、表四（元件表） |
| action + reducer 檔 | action creator、reducer、middleware 觸發點 | 表一（逐函式，限 action creator 部分）、表二（action 表）、表三（reducer 表） |
| 第三方 API 掃描 | 該 entry 用到的第三方元件（react-bootstrap-table、react-select、react-datetime 等）的呼叫點 | 表四的「第三方元件用法」欄位素材，額外附一份「用到的 props/方法清單」 |

分群後每群各派一個 subagent，三群平行執行；單群若因檔案數超過 4 個而再切，仍維持「三群」的分類語意（例如元件檔太多就切成「元件檔 A」「元件檔 B」兩個 subagent，但職責都算在「元件檔」這一群）。

## Phase 1 Agent Prompt

以下 prompt 內嵌於主流程呼叫 subagent 時使用，三群共用同一份骨架，依 `{分群角色}`／`{必讀檔案}`／`{輸出表格}` 三個變數代入：

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

三個分群各自代入的變數：

| 群 | `{分群角色}` | `{必讀檔案}` | `{輸出表格}` |
|---|---|---|---|
| 元件檔 | 元件行為抽取 | 主元件 + 子元件 + Modal 元件路徑 | 逐函式表、元件表 |
| action + reducer 檔 | Redux 合約抽取 | action creator、reducer、middleware 觸發點路徑 | 逐函式表（限 action creator）、action 表、reducer 表 |
| 第三方 API 掃描 | 第三方元件用法抽取 | 用到第三方元件的檔案路徑（表格/選單/日期選擇器等） | 元件表（僅「第三方元件用法」欄）+ 附加「用到的 props/方法清單」 |

## 信任規則

Agent 產出的四張表是**原始素材**，不是「已核對過的結論」。主流程收到表格後，必須自己做以下核對，不能直接採信：

- **action 對應是否正確**：agent 可能把「名稱相似但參數或 API 不同」的 action 錯配，主流程要讀兩邊（R15 action creator 原文、R18 現有樣板）確認 URL、method、data 形狀一致。
- **success 副作用是否完整**：agent 常見的漏列是 success handler 裡的次要副作用（re-fetch 另一個 action、關閉另一個 Modal）。主流程要讀 reducer 表「哪些 case 修改」欄位，逐一確認該 action 的 SUCCESS 分支列出的欄位變化都被抄進表裡，沒有遺漏。

其餘可以直接採信 agent 產出的部分：URL 字串、HTTP method、action type 字串常數、import 來源——這些是事實陳述，agent 只要有列出具體值就不必重查。

核對完成後，主流程把四張表整合、附上核對結論，寫成 `<entry>-contract.md`。

## Phase 3(b)：靜態比對檢查表（class 保留路線）

Phase 3(b) 用下列檢查表對 `<entry>-contract.md` 做逐條標記。本節的檢查深度分層與檢查項目，是針對「保留 class、機制沿用 R18、命名沿用 R15」這種**最小改動**遷移方式設計的——多數頁面遷移驗證方法預設的是「重寫成 functional + hooks」，套用前必須先確認這點差異，否則會把不會發生的 bug 類型也列進必查清單、也會漏掉這種遷移方式特有的風險（Redux 機制層被換掉、但元件層原樣搬移，兩層改動幅度不對稱）。

### 驗證深度分層（L1-L4）

| 層 | 檢查內容 | 容易抓到的 bug（本次遷移方式下） |
|---|---|---|
| **L1 合約層** | action types / API endpoint / state shape / props 介面，比對是否符合「命名沿用 R15、機制沿用 R18」的轉換規則 | 漏 action、URL 錯、data 形狀不符、用到 R18 saga 基礎層不支援的欄位卻沒被攔下 |
| **L2 結構層** | 元件拆分是否維持 1:1、欄位存在性、formatter/sort 函式簽名、生命週期方法是否逐字保留（不轉 useEffect） | 欄位丟失、元件拆錯、生命週期方法內容在複製時被誤改 |
| **L3 行為層** | 按鈕 click → action → saga → reducer 完整鏈路、Modal 開/關時機、錯誤流、副作用 | **Modal 不自動關**（成因是 Redux 機制層被換掉，不是元件層被換掉）、fail 殘留、reducer success 副作用漏抄、競態 |
| **L4 等價性層** | 相同輸入資料兩版本渲染結果是否相同 | 格式化差異、filter/sort 行為差異、邊界值。**靜態比對抓不到，必須手測**（flag 開啟後兩版本跑同一筆真實資料並列比對） |

完成 L1+L2 不代表通過驗證。因為本次遷移元件層是原樣搬移，最容易出錯的反而是**元件沒變、但它依賴的 Redux 機制變了**這種不對稱改動——L3 才是這類遷移最容易失分的地方。

### Phase 1（對應合約表：action 表 / reducer 表）檢查項目

- [ ] **Action Types** — 逐一比對 action 表的 `type` 欄位，確認每個 R15 action type 字串在轉換後原樣保留（命名沿用 R15，不加前綴）
- [ ] **State Shape** — 逐一比對 reducer 表的「欄位」欄，確認每個欄位在 R18 版本存在且初始值一致
- [ ] **API Endpoints** — 逐一比對 action 表的 `url`/`method`/`data 形狀`，確認轉換後的實際 HTTP 呼叫與原始一致
- [ ] **非同步處理** — 逐一比對 action 表的 `callback / dispatch / redirect / lastExcutionFunction` 欄位，確認 R18 版本的 success handler 涵蓋了原本這些欄位承載的行為（機制换成 R18 樣板，但行為要對得上）
- [ ] **不支援欄位攔截** — 若 action 表標記了 `headers`/`file1~3`/`files`/`authorizationToken` 等欄位，確認這一列在 Phase 2 有被正確標為需要人工處理，不是被靜默丟棄

### Phase 2（對應合約表：逐函式表 / 元件表）檢查項目

- [ ] **元件對應關係** — 每個 R15 檔案對應到哪個 R18 路徑，1:1 對映沒有被拆散或合併
- [ ] **使用者行為** — 逐一比對元件表的 handlers 欄位，確認每個按鈕/表單提交/Modal 開關的觸發函式與 dispatch 的 action 都原樣保留
- [ ] **生命週期** — 逐一比對元件表的 lifecycle 欄位，確認生命週期方法**逐字保留**（本次不轉 useEffect，`componentWillReceiveProps` 等舊 API 沿用 `UNSAFE_` 前綴即可，不必改寫邏輯）
- [ ] **Business Logic** — 逐函式表列出的計算邏輯、資料轉換、工具函式，比對輸出是否與原函式一致
- [ ] **表格/列表** — 表格欄位、formatter、排序、過濾、分頁，依第三方 API 對照表（另檔）確認 filter/sort 介面轉換正確
- [ ] **Redux State 使用** — 元件表的 props 欄位，逐一確認沒有死 prop、也沒有遺漏；`mapStateToProps`/`mapDispatchToProps` 保持原樣，不因為機制層換掉而跟著改寫

### 三個 MUST-CHECK（class 保留路線改寫版）

以下三項在「重寫成 functional + hooks」的遷移方式下是必查項；本次因為**保留 class、不轉 hooks**，風險分布不同，逐項改寫如下。三項仍然逐條標記，不因為多為 N/A 而省略。

#### MUST-CHECK 1：Modal 自動關閉機制 —— 本次遷移仍然 MUST，不是 N/A

R15 常見模式：Modal `show={this.props.modal}` 讀 Redux；reducer 在 `xxx_SUCCESS` 裡把 `modal` 設為 `false`；使用者儲存成功 → reducer 把 modal 設 false → Modal 自動關。

**本次遷移的風險點**：元件層原樣搬移（Modal 仍然讀 `this.props.modal`），**但 Redux 機制層被換成 R18 樣板**（entity/saga 取代 middleware）。风险不是「元件改用 local state 導致脫鉤」，而是「entity 的 success handler 沒有把原本 reducer 裡 `modal: false` 這個副作用抄過去」。

**必查步驟**：
1. 對照表三（reducer 表）逐一確認每個標記了 `modal`/`open`/`visible` 欄位變化的 case，其對應的 R18 entity success handler 是否有 dispatch 同樣的欄位變化
2. 確認 R18 reducer 的欄位定義（介面/型別宣告）有包含這個欄位——reducer 有寫但介面宣告漏寫是常見問題
3. 因為元件保持讀 Redux prop 不變，只要 Redux 端這個欄位變化被正確搬過去，Modal 自動關閉行為就會維持等價；**不需要**額外加 `useEffect` 同步機制（那是 hooks 遷移才需要的解法，本次不適用）

#### MUST-CHECK 2：元件初始值 stale —— 本次遷移下多為 N/A，但仍需逐條確認排除

原始問題（hooks 版）：`useState(props.xxx)` 只在 mount 時跑一次，Modal 不 unmount 時切換資料會顯示舊值。

**本次為何多為 N/A**：本次遷移規則是「保留 class、不轉 hooks、註解逐字照搬、不做重構」，不會把 `this.state = { xxx: this.props.xxx }` 這種 class 建構子初始化改寫成任何形式的 hooks；只要是機械式複製，就不會**新增**這個 bug。

**仍需確認的例外**（逐條標記，不是整項跳過）：
1. 若合約表四「元件表」的 state 欄標記了「來源是 `this.props.xxx`」，確認 R15 原本是否已經有 `componentWillReceiveProps`/`getDerivedStateFromProps`/`UNSAFE_componentWillReceiveProps` 做同步——若原本就有，遷移時這段邏輯必須逐字保留；若原本就沒有（R15 本身就有 stale 問題），這是 R15 既有行為，遷移規則是原樣搬移不修正，在報告標記「R15 既有行為，不在本次修正範圍」
2. 確認 Phase 2 沒有任何檔案被意外改寫成 functional component（機械轉換規則禁止這麼做，但仍要在此複查一次，作為雙重確認）

#### MUST-CHECK 3：cleanFail on Modal hide —— 本次遷移仍然 MUST

R15 常見模式：`<AlertMessage fail clean={cleanFail} />`，使用者可手動關閉錯誤訊息，或在 Modal `onHide` 時 dispatch `cleanFail()`，避免下次開啟殘留舊錯誤。

**本次遷移的風險點**：元件層的 `onHide` handler 原樣搬移，但 `cleanFail` 這個 action creator 若被合約表二歸類為「不支援欄位」或在 Phase 2 機制轉換時被歸進不同的 entity，可能 dispatch 到錯的 action 或漏掉。

**必查步驟**：
1. 確認合約表一（逐函式表）裡 `onHide`/`handleClose` 這類 handler 的「輸出」欄位是否列出 `dispatch(cleanFail())` 或等價呼叫
2. 確認 R18 對應版本這個 dispatch 呼叫存在且指向轉換後對應的 action（命名沿用 R15，字串不變）
3. 確認沒有其他離開路徑（父層路由切換、tab 切換）原本也會清 fail，但遷移後漏掉

### Feature Flag 三層一致性（僅並行期有 feature flag 切換 commit 時需要）

本次遷移用 feature flag 並行機制切換 R15/R18，三層必須一致才算切換完整：

| 層 | 檢查內容 |
|---|---|
| 後端路徑前綴層 | 該 entry 的 `fe_config_prefix` 是否已加進後端的路徑前綴 → feature 名稱對照表，且該前綴沒有與其他既有活路徑產生無邊界碰撞（成為別的前綴的前綴時要加結尾錨） |
| 機構預設層 | 各機構預設模板是否都新增了這個 feature 的預設值（預設 `enable: false`），三份模板缺一都算不一致 |
| 前端路由守衛層 | R18 路由是否加了對應的 feature 檢查守衛，未開啟時導向 R15、開啟後才進 R18 版本；`case`/`daycase` 子頁另需確認 R15 側的 tab 連結處理是否同步 |

三層有任一層缺漏都標記 ❌，並在報告的「需修復的問題」表列出缺的是哪一層。

## 合約表回填格式

Phase 3(c) 對 `<entry>-contract.md` 的每一列（四張表全部）回填兩欄：

| R18 對應 | 等價 ✅/⚠️/❌ |
|---|---|

- **R18 對應**：填 R18 版本對應的檔案路徑/行號，或對應的名稱（action type 字串、reducer 欄位名等）；完全找不到對應寫「無對應」。
- **等價 ✅**：兩版本行為一致，或差異是本次遷移規則允許的合理改善（如機制層轉換帶來的結構差異）。
- **等價 ⚠️**：無法從靜態閱讀確定是否等價——包括「對照表查無此欄位轉換規則、R18 也沒有先例可循」「需要跑起來看才能確認的行為（filter/sort 實際結果、日期格式化）」「MUST-CHECK 2 例外情境命中但無法排除」這幾種情況。⚠️ 不是「大概沒問題」的委婉說法，是「需要人工複查」的明確信號。
- **等價 ❌**：確認不等價，且不是本次遷移規則允許的差異。

⚠️ 與 ❌ 的列**必須**進 `<entry>-report.md` 的「⚠ 清單」/「需修復的問題」區段，附上合約表列的原始位置（表格名 + 列），不得只留在合約表裡不往上帶。❌ 若在 Phase 2 就已經對應到 `blocked(no_mapping)`，直接引用該 blocked 狀態，不必重複判斷。
