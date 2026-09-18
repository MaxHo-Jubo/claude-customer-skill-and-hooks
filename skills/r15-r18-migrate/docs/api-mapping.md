# api-mapping — R15 → R18 機械對照表

本檔是 `r15-r18-migrate` skill Phase 2「元件層」的唯一對照依據。所有條目都附 **R18 既有先例**（`repo 相對路徑:行號`），照著改即可；標「無先例」的條目代表 R18 全庫查無同類寫法，遇到時走 `blocked(no_mapping)`。

本檔自足，不需要參照任何外部文件。

---

## 0. 版本事實（來源：`frontend/react_15/package.json`、`frontend/react_18/package.json`；版本號取自各自 `node_modules/<pkg>/package.json` 的實裝版本）

| 套件 | R15 實裝 | R18 實裝 | 破壞性 |
|---|---|---|---|
| react / react-dom | 15.6.2 | 18.2.0 | 高 |
| react-bootstrap | 0.32.4 | 2.9.1 | 高 |
| bootstrap（CSS） | 3.4.1 | 5.3.2 | 高 |
| react-bootstrap-table | 2.11.2 | —（改用 react-bootstrap-table-next 4.0.3 + `react-bootstrap-table2-filter` 1.3.3 + `react-bootstrap-table2-paginator` 2.1.2） | 高 |
| react-select | 1.3.0 | 5.8.0 | 高 |
| react-router | 3.2.6（+ react-router-redux 4.0.8） | react-router-dom 6.20.1（+ redux-first-history 5.1.1） | 高 |
| react-i18next / i18next | 2.2.3 / 4.2.0 | 11.18.6 / 21.10.0 | 中（見 §7） |
| redux / react-redux | 3.7.2 / 5.1.2 | 4.2.1 / 8.1.3 | 低（`connect` / `bindActionCreators` 用法不變） |
| redux-saga | 無 | 1.2.3 | — |
| moment | 2.24.0 | 2.29.4 | 無（**不得換掉 moment**） |
| prop-types | 15.7.2 | 15.8.1 | 無 |
| sweetalert2 | 6.11.5 | 11.10.1 | 高（見 §9） |
| react-bootstrap-typeahead | 0.10.4 | 6.3.2 | 高（見 §9） |
| superagent | 3.8.3 | 8.1.2 | 低 |
| ramda | 0.27.2 | 0.28.0 | 低 |
| underscore | 1.10.2 | 1.10.2 | 無 |

**R18 建置鏈**：Vite（`npm run buildReact18Vite`），`.js` 不進 tsconfig 型別檢查，`.js/.jsx` 合法。

---

## 1. 硬性禁止（違反即視為遷移失敗）

| 禁止 | 說明 |
|---|---|
| 改成 hooks | class component 一律保留 class。不得把 `this.state` 改 `useState`、不得把 lifecycle 改 `useEffect`。 |
| 改名 | 常數名、action type 字串、state 欄位、函式名、變數名、CSS class 名全部沿用 R15 原名。 |
| 順手重構 | 不合併函式、不抽 helper、不整理 import 順序、不改縮排風格、不補 STEP/JSDoc 註解。 |
| 換 moment | 兩版同為 moment 2.x，維持 `moment`，不得改 dayjs。 |
| 加 TypeScript | 檔案副檔名沿用 R15（`.js` → `.js`、`.jsx` → `.jsx`），不加型別標註、不改 `.tsx`。 |
| 改用 R18 新式共用元件 | 例如把表格改寫成 `frontend/react_18/src/containers/Table/TableContainer`（見 §5.5）——那是重寫不是遷移。 |
| 補「防護性 fallback」 | 對照表沒有的東西就 `blocked(no_mapping)`，不要用 `?? 預設值` 糊過去。 |

**註解規則**：R15 原有註解逐字照搬（含錯字、含 `FeaturePath` 檔頭）；所有建立或修改的檔在檔頭 JSDoc 追加一行 `Modified: YYYY/MM/DD <執行者>`。

---

## 2. React 15 → 18

| R15 寫法 | R18 寫法 | R18 先例 | 備註 |
|---|---|---|---|
| `componentWillMount()` | `UNSAFE_componentWillMount()` | 無先例（R18 全庫 0 處） | R15 有 83 處。React 18.2.0 仍會呼叫未加前綴的版本（`react-dom` dev build 內 `typeof instance.componentWillMount === 'function'` 判斷仍在），但會印 deprecation 警告；一律加前綴。 |
| `componentWillReceiveProps(nextProps)` | `UNSAFE_componentWillReceiveProps(nextProps)` | `frontend/react_18/src/components/Datepicker.js:323` | R15 有 104 處。 |
| `componentWillUpdate(nextProps)` | `UNSAFE_componentWillUpdate(nextProps)` | 無先例（R18 只有一處**未加前綴**的 `frontend/react_18/src/containers/Form/DaycaseRecordFormLinchdctnV2.js:127`，是既有技術債，**不要照抄**） | R15 有 4 處。 |
| `React.PropTypes.xxx` | `import PropTypes from 'prop-types';` + `PropTypes.xxx` | `frontend/react_18/src/components/ListPagination.jsx:8` | R15 有 179 處 `React.PropTypes`；R18 有 322 處 `import PropTypes from 'prop-types'`、0 處 `React.PropTypes`。React 15.5+ 已把 PropTypes 移出 react 套件。 |
| string ref `ref="foo"` + `this.refs.foo` | **原樣保留** | `frontend/react_18/src/components/AddressSelector.jsx:327`（`ref="city"`）、`frontend/react_18/src/components/AddressSelector.jsx:216`（`this.refs.city`） | R18 已有 379 處 string ref、138 處 `this.refs`。不要改 `createRef`。 |
| `ReactDOM.findDOMNode(x)` | **原樣保留** | `frontend/react_18/src/components/AddressSelector.jsx:216` | R18 有 7 處。React 18 仍支援（StrictMode 下會警告）。R15 有 11 處。 |
| `ReactDOM.render` / `React.createClass` | **不適用**（頁面層不會出現，只在入口 `frontend/react_15/index.js:31`） | 不適用 | 入口檔不遷移，R18 入口 `frontend/react_18/src/index.js` 已存在。 |

**注意**：若同一個 class 同時有 `getDerivedStateFromProps` 或 `getSnapshotBeforeUpdate`，React 會忽略 `UNSAFE_componentWill*`。R15 頁面不會有前兩者，遷移時也不得新增。

---

## 3. react-bootstrap 0.32.4 → 2.9.1

### 3.1 全域 prop 改名（所有元件通用）

| R15 | R18 | R15 出現處（示例） | R18 先例 |
|---|---|---|---|
| `bsStyle="primary"` | `variant="primary"` | `frontend/react_15/deviceSensorList/components/ButtonFormatter.js:43` | `frontend/react_18/src/components/CheckModal.jsx:57` |
| `bsSize="small"` / `bsSize="lg"` | `size="sm"` / `size="lg"` | `frontend/react_15/deviceSensorList/components/ButtonFormatter.js:43`（Button）、`frontend/react_15/breathing/components/BreathingModifyModal.js:42`（Modal） | `frontend/react_18/src/components/EmployeeSelect.jsx:226`（`size="lg"`） |
| `bsClass` | 無對應，改用 `className` | — | 無先例 |

值域對照：`bsSize="xsmall"` → `size="sm"`（v2 只有 `sm` / `lg`）、`bsSize="small"` → `size="sm"`、`bsSize="medium"` → 省略、`bsSize="large"` → `size="lg"`。

⚠️ **反例警告**：R18 仍有 49 處殘留 `bsStyle`、9 處殘留 `bsSize`（例如 `frontend/react_18/src/components/HomeServicerSelect.jsx:214` 的 `bsSize="md"`），react-bootstrap 2 會直接忽略它們。這些是既有錯誤，**不得當成先例照抄**。

### 3.2 元件對照

react-bootstrap 2.9.1 實際匯出清單（`node_modules/react-bootstrap/esm/`）不含 `Panel` / `PanelGroup` / `Glyphicon` / `PageHeader` / `Well` / `Checkbox` / `Radio` / `ControlLabel` / `HelpBlock` / `Grid` / `MenuItem` / `Label` / `Jumbotron`。下表的替代都是實際存在的匯出。

| R15 | R18 | R15 先例 | R18 先例 |
|---|---|---|---|
| `<Panel>` | `<Card>` | `frontend/react_15/employeeList/components/EmployeeCreateModal.js:653` | `frontend/react_18/src/components/CheckBoxList.tsx:103` |
| `<Panel.Heading>` | `<Card.Header>` | `frontend/react_15/employeeList/components/EmployeeCreateModal.js:654` | `frontend/react_18/src/components/CheckBoxList.tsx:104` |
| `<Panel.Body>` | `<Card.Body>` | `frontend/react_15/employeeList/components/EmployeeCreateModal.js:657` | `frontend/react_18/src/components/CheckBoxList.tsx:107` |
| `<Panel.Title>` | `<Card.Title>` | `frontend/react_15/daycase/components/AccreditationForm/FormResultList.js:655` | `frontend/react_18/src/pages/remind/components/RemindType.jsx:105` |
| `<PanelGroup accordion>` + `<Panel eventKey>` + `<Panel.Toggle>` + `<Panel.Collapse>` | `<Accordion>` + `<Card eventKey>` + `<Accordion.Collapse eventKey>`（或 `<Accordion.Item>`/`<Accordion.Header>`/`<Accordion.Body>`） | `frontend/react_15/daycase/components/CreateServiceItemsModal.js:161`、`frontend/react_15/components/AccordinCard.jsx:18-23` | `frontend/react_18/src/components/CreateServiceItemsModal.jsx:249`、`frontend/react_18/src/components/AccordionCard.tsx:116,126`、`frontend/react_18/src/containers/Modal/contactbookList/ContactbookModal.tsx:555-597` |
| `<Glyphicon glyph="plus" />` | `import Glyphicon from '@strongdm/glyphicon';` + 同樣 `<Glyphicon glyph="plus" />` | `frontend/react_15/daycaseShiftList/components/ScheduleMain.js:945`（從 `react-bootstrap` 具名匯入，見同檔 `:11`） | `frontend/react_18/src/containers/Form/FormContent.jsx:32`（import）、`frontend/react_18/src/containers/Form/FormContent.jsx:1635`（使用） |
| `<PageHeader>標題</PageHeader>` | `import PageTitle from '<相對路徑>/components/PageTitle';` + `<PageTitle>標題</PageTitle>` | `frontend/react_15/deviceSensorList/index.js:13` | `frontend/react_18/src/components/PageTitle.tsx:11`（定義）、`frontend/react_18/src/pages/externalIotData/ExternalIotDataPage.tsx:73`（使用）、`frontend/react_18/src/pages/formOverview/FormOverview.tsx:17`（import 路徑寫法） |
| `<ControlLabel>` | `<Form.Label>` | `frontend/react_15/daycase/components/DailyRecordModal.js:78` | `frontend/react_18/src/containers/Form/companyForm/FeedbackAndAppealRecord.tsx:213` |
| `<Checkbox>文字</Checkbox>` | `<Form.Check type="checkbox" label="文字" />` | `frontend/react_15/components/survey/SurveyQuestion.js:48` | `frontend/react_18/src/pages/promptManager/PromptManager.jsx:513` |
| `<Checkbox inline>` | `<Form.Check type="checkbox" inline />` | `frontend/react_15/components/survey/SurveyQuestion.js:48` | 無先例（R18 未見 `Form.Check inline`）；`inline` 是 v2 合法 prop，照加 |
| `<Radio inline value>` | `<Form.Check type="radio" inline value />` | `frontend/react_15/components/survey/SurveyQuestion.js:39` | 無先例（R18 未見 `Form.Check type="radio"`） |
| `<FormGroup>` | `<Form.Group>` | `frontend/react_15/deviceManagerList/components/DayCareDeployModal.js:85` | `frontend/react_18/src/containers/Form/interview/InterviewForm.jsx:299` |
| `<FormControl type="text">` | `<Form.Control type="text">` | `frontend/react_15/components/LocationSelect.js:132` | `frontend/react_18/src/containers/Modal/settingsManager/ChargeModal.js:126` |
| `<FormControl componentClass="select">` | `<Form.Select>` | — | `frontend/react_18/src/containers/ButtonBar/messageManager/MessageButtonBar.js:122` |
| `<FormControl componentClass="textarea" rows={3}>` | `<Form.Control as="textarea" rows={3}>` | — | `frontend/react_18/src/containers/Modal/settingsManager/ChargeModal.js:194` |
| `<Form>` | `<Form>`（不變） | `frontend/react_15/deviceManagerList/components/DayCareDeployModal.js:80` | `frontend/react_18/src/containers/Form/interview/InterviewForm.jsx:293` |
| `<HelpBlock>` | `<Form.Text>` | 無（R15 0 處） | 無先例 |
| `<Modal show onHide backdrop="static">` | 同左（`bsSize` → `size`） | `frontend/react_15/breathing/components/BreathingModifyModal.js:42` | `frontend/react_18/src/components/EmployeeSelect.jsx:226` |
| `<Modal.Header closeButton>` / `<Modal.Title>` / `<Modal.Body>` / `<Modal.Footer>` | 不變 | `frontend/react_15/deviceManagerList/components/DayCareDeployModal.js:76-78` | `frontend/react_18/src/components/CheckModal.jsx:49,52,55` |
| `<Grid fluid>` | `<Container fluid>` | `frontend/react_15/daycaseList/components/CaseImportModal.js:144` | `frontend/react_18/src/pages/daycaseEvaluate/BasicInfo.tsx:448` |
| `<Row>` / `<Col xs={6} md={3}>` | 不變 | `frontend/react_15/deviceManagerList/components/DayCareDeployModal.js:83-84` | `frontend/react_18/src/components/ListPagination.jsx:147-148` |
| `<Button bsStyle="info">` | `<Button variant="info">` | `frontend/react_15/components/customerSelect/CustomerTable.js:59` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:146` |
| `<Button bsStyle="default">` | `<Button variant="secondary">`（BS5 無 `btn-default`） | — | `frontend/react_18/src/components/CheckModal.jsx:57`（variant 寫法） |
| `<ButtonGroup>` / `<ButtonToolbar>` | 不變 | `frontend/react_15/deviceManagerList/components/DayCareDeployModal.js:111` | `frontend/react_18/src/components/CheckModal.jsx:56`、`frontend/react_18/src/containers/ButtonBar/DaycaseServiceFilter.jsx:169` |
| `<Table>` | 不變（⚠ 版面行為不同，見 §8.3） | `frontend/react_15/daycaseList/components/CaseImportModal.js:32` | `frontend/react_18/src/components/PrintTemplate.jsx:191` |
| `<Pagination>` | 不變 | `frontend/react_15/case/components/ListPagination.jsx:88` | `frontend/react_18/src/components/ListPagination.jsx:107` |
| `<OverlayTrigger placement overlay={<Tooltip>}>` | 不變 | `frontend/react_15/daycase/components/CaseCalendar/Modal/ScheduleModal.js:621` | `frontend/react_18/src/containers/ButtonBar/settingsManager/AItemButtonBar.js:110`、`frontend/react_18/src/containers/Form/FormContent.jsx:1392`（Tooltip） |
| `<Nav bsStyle="tabs" activeKey onSelect>` | `<Nav variant="tabs" activeKey onSelect>` | `frontend/react_15/scheduler/components/Header.js:21` | `frontend/react_18/src/containers/Header/TabRouteWithPageTitle.tsx:133` |
| `<NavItem eventKey="1">文字</NavItem>` | `<Nav.Item><Nav.Link eventKey="1">文字</Nav.Link></Nav.Item>`（v2 的 `NavItem` 只渲染 `<li>`，可點擊的是 `Nav.Link`） | `frontend/react_15/breathing/components/Header.js:19` | `frontend/react_18/src/containers/Header/TabRouteWithPageTitle.tsx:65`（`Nav.Link as="div" eventKey`） |
| `<NavItem href="/x">文字</NavItem>` | `<Nav.Link href="/x">文字</Nav.Link>` | `frontend/react_15/daycase/components/CaseHeader.jsx:114` | `frontend/react_18/src/containers/Header/TabRouteWithPageTitle.tsx:58` |
| `<NavDropdown title id>` + `<MenuItem eventKey>` | `<NavDropdown title id>` + `<NavDropdown.Item eventKey>` | `frontend/react_15/case/components/CaseHeader.js:112`（NavDropdown）、`frontend/react_15/daycaseShiftList/components/ScheduleMain.js:973`（MenuItem） | `frontend/react_18/src/containers/Header/TabRouteWithPageTitle.tsx:120`（NavDropdown）；`Dropdown.Item` 寫法見 `frontend/react_18/src/containers/Modal/customer/CustomerSelect/CustomerModal.tsx:242` |
| `<DropdownButton>` + `<MenuItem>` | `<DropdownButton>` + `<Dropdown.Item>` | `frontend/react_15/daycaseShiftList/components/ScheduleMain.js:11` | `frontend/react_18/src/containers/ComboBoxes/MultiCheckboxComboBox.tsx:144`（Dropdown.Item） |
| `<InputGroup.Addon>$</InputGroup.Addon>` | `<InputGroup.Text>$</InputGroup.Text>` | `frontend/react_15/components/MoneyInput.js:62` | `frontend/react_18/src/components/MoneyInput.tsx:36` |
| `<InputGroup.Button>` | 直接放 `<Button>`（v2 無 `InputGroup.Button`） | `frontend/react_15/components/LocationSelect.js:136` | `frontend/react_18/src/components/HomeServicerSelect.jsx:207-208`（`<InputGroup>` 內直接放 `<Button>`） |
| `<Label bsStyle="primary">` | `<Badge bg="primary">` | `frontend/react_15/daycase/components/CountTable.jsx:246` | `frontend/react_18/src/containers/Badge/MessageUnreadBadge.js:53`（`bg="danger"`）、`frontend/react_18/src/pages/documentCenter/DocumentCenterManage.tsx:249` |
| `<Alert bsStyle="danger">` | `<Alert variant="danger">` | `frontend/react_15/components/AlertMessage.js:38` | `frontend/react_18/src/components/AlertMessage.js:17` |
| `<Collapse in={bool}>` | 不變 | `frontend/react_15/components/LocationSelect.js:152` | `frontend/react_18/src/containers/Table/TableContainer/TableBody.jsx:85` |
| `<Well>` | `<Card><Card.Body>` 或 `<div className="…">` | `frontend/react_15/daycase/components/BasicInfo.js:1589` | 無先例（BS5 無 `.well`，R18 全庫無替代寫法） |
| `<Jumbotron>` | 無對應（BS5 移除） | `frontend/react_15/error502/index.js:6` | 無先例 |
| `<Tabs>` / `<Tab>` | 不變 | `frontend/react_15/daycaseList/components/CaseImportModal.js:143` | 無先例（R18 全庫無 `<Tabs>`；v2 有匯出，照搬） |
| `<ListGroupItem>` | `<ListGroup.Item>` | `frontend/react_15/daycase/components/FormMenu.js:9` | 無先例 |
| `<Carousel>` | 不變 | `frontend/react_15/components/multiFileViewer/components/FileItem.js:20` | 無先例（v2 有匯出） |
| `<Popover>` | 不變（`<Popover.Title>` → `<Popover.Header>`、`<Popover.Content>` → `<Popover.Body>`） | `frontend/react_15/deviceManagerList/components/DayCareDeployModal.js:7` | 無先例 |

### 3.3 直接對照的整檔範例（改寫時優先看這兩組同名對應檔）

| R15 | R18 | 用途 |
|---|---|---|
| `frontend/react_15/components/AccordinCard.jsx` | `frontend/react_18/src/components/AccordionCard.tsx` | Panel/PanelGroup → Card/Accordion 全套 |
| `frontend/react_15/daycase/components/CreateServiceItemsModal.js` | `frontend/react_18/src/components/CreateServiceItemsModal.jsx` | Modal + Accordion + Form + ButtonToolbar |
| `frontend/react_15/components/customerSelect/CustomerTable.js` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx` | react-bootstrap-table → next 全套（見 §5） |
| `frontend/react_15/components/MoneyInput.js` | `frontend/react_18/src/components/MoneyInput.tsx` | InputGroup.Addon → InputGroup.Text |
| `frontend/react_15/components/AlertMessage.js` | `frontend/react_18/src/components/AlertMessage.js` | Alert variant |
| `frontend/react_15/components/NavButton.js` | `frontend/react_18/src/components/NavButton.js` | react-router `Link` → react-router-dom `NavLink` |

**class 保留的整頁遷移範本**：commit `e5b7c0e52b`（`frontend/react_15/expertAcase/components/PlanHistory.js` → `frontend/react_18/src/pages/expertAcase/PlanHistory.jsx`，class 名稱沿用、`connect` + `bindActionCreators` + moment + `withTranslation` 照用、同層 `.scss` 一併新增）。

---

## 4. Bootstrap 3 → 5 的 className 對照

R18 的 `frontend/react_18/src/assets/styles/bootstrap.scss:31` 直接 `@import` bootstrap 5.3.2 全套。下表「BS5 是否存在」以 `node_modules/bootstrap/dist/css/bootstrap.css` 實測為準。

| R15 className | BS5 是否存在 | R18 應改成 |
|---|---|---|
| `pull-right` | 否 | `float-end` |
| `pull-left` | 否 | `float-start` |
| `text-right` | 否 | `text-end` |
| `form-inline` | 否 | 用 `d-flex` + `gap-*` 自行排版 |
| `radio-inline` / `checkbox-inline` | 否 | `form-check-inline`（配合 `<Form.Check inline>`） |
| `control-label` | 否 | `form-label` |
| `help-block` | 否 | `form-text` |
| `input-group-addon` | 否 | `input-group-text` |
| `img-responsive` | 否 | `img-fluid` |
| `btn-default` | 否 | `btn-secondary` |
| `label` / `label-primary` | 否 | `badge` / `bg-primary` |
| `hidden` | 否 | `d-none` |
| `panel` / `panel-body` / `panel-heading` | 否 | `card` / `card-body` / `card-header` |
| `well` | 否 | 無對應，改自訂 class |
| `glyphicon` | 否 | 用 `@strongdm/glyphicon`（見 §3.2） |
| `col-xs-6` | 否 | `col-6`（但 `<Col xs={6}>` 元件寫法不用改，react-bootstrap 2 會輸出 `col-6`） |
| `has-error` | 否 | `is-invalid` |
| `caret` / `close` | 否 | 無對應 / `btn-close` |
| `page-header` | 否（BS5 無），但 R18 自行定義於 `frontend/react_18/src/pages/mainFrame/style.scss:5` | 不用改 |
| `table` / `table-bordered` / `modal-header` / `modal-body` | 是 | 不用改 |
| `no-print` / `print-it` | R18 自行定義於 `frontend/react_18/src/pages/mainFrame/style.scss:182,186`（`@media print` 內、頂層 selector） | 不用改 |

⚠️ **反例警告**：R18 既有程式碼裡仍有 42 處 `className` 含 `pull-right`（例如 `frontend/react_18/src/components/CheckModal.jsx:56`），BS5 沒有這個 class，它們是**無效的死 class**。不得因為「R18 也這樣寫」就照抄。

---

## 5. react-bootstrap-table 2.11.2 → react-bootstrap-table-next 4.0.3

### 5.1 import 與整體結構

| R15 | R18 |
|---|---|
| `import { BootstrapTable, TableHeaderColumn } from 'react-bootstrap-table';` | `import BootstrapTable from 'react-bootstrap-table-next';`<br>`import paginationFactory from 'react-bootstrap-table2-paginator';`<br>`import filterFactory, { textFilter, selectFilter } from 'react-bootstrap-table2-filter';` |
| 欄位用 JSX 子元素 `<TableHeaderColumn …>` | 欄位改成 `columns` 陣列（物件），`<BootstrapTable columns={dataColumns} … />` 無子元素 |
| `data={rows}` + 其中一欄 `isKey` | `data={rows}` + `keyField="_id"` |

R18 先例（整段對照）：`frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:101-162`；其 R15 原型為 `frontend/react_15/components/customerSelect/CustomerTable.js:63-96`。
CSS 也要換：R15 `frontend/react_15/index.js:17` 載 `react-bootstrap-table/dist/react-bootstrap-table.min.css`，R18 已在 `frontend/react_18/src/index.js:31-33` 全域載入 next 版三支 CSS，**頁面不需要再 import**。

### 5.2 欄位 props 對照

| R15（`TableHeaderColumn`） | R18（`columns[]` 物件欄位） | R18 先例 |
|---|---|---|
| `dataField='name'` | `dataField: 'name'` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:107` |
| 子節點文字（`>{t('name')}<`） | `text: t('name')` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:108` |
| `isKey` | 移到表格層 `keyField="_id"` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:154` |
| `dataSort` | `sort: true` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:109` |
| `hidden` / `hidden={!flag}` | `hidden: true` / `hidden: !flag` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:105` |
| `dataFormat={fn}`，簽名 `(cell, row, formatExtraData, rowIndex)` | `formatter: fn`，簽名 `(cell, row, rowIndex, formatExtraData)`（**第 3、4 參數對調**） | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:119`、`frontend/react_18/src/pages/epidemicPreventionRecord/VaccineRecordTable.jsx:270` |
| `formatExtraData={x}` | `formatExtraData: x` | 無先例（next 支援同名欄位） |
| `filter={{ type: 'TextFilter', placeholder: 'x' }}` | `filter: textFilter({ placeholder: 'x' })` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:110` |
| `filter={{ type: 'SelectFilter', options: obj, placeholder: 'x' }}` | `filter: selectFilter({ options: obj, placeholder: 'x' })` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:115-118` |
| `filterFormatted`（讓 filter 比對 `dataFormat` 後的值） | `filterValue: (cell, row) => 格式化後的值`（**必須自己再寫一次格式化函式**，沒有布林開關） | `frontend/react_18/src/containers/Table/TOCCRecordTable.tsx:261`、`frontend/react_18/src/containers/Table/dayCareEmployeeShiftList/EmployeeShiftTable.js:155` |
| `sortFunc={fn}`，簽名 `(a, b, order)`，**a/b 是整列物件** | `sortFunc: fn`，簽名 `(a, b, order, dataField, rowA, rowB)`，**a/b 是該欄的 cell 值、整列在 rowA/rowB** | `frontend/react_18/src/containers/Table/contactbookList/ContactBookListTable.tsx:563`、`frontend/react_18/src/containers/Table/formOverview/proPlan/DataTable.tsx:230` |
| `width='120px'` | `headerStyle: { width: '120px' }` + `style: { width: '120px' }`（**兩邊都要給，理由見 §8.3**） | `frontend/react_18/src/containers/Table/dayCareEmployeeShiftList/EmployeeShiftTable.js:140` |
| `columnClassName` / `className` | `classes` / `headerClasses` | 無先例 |
| `editable={false}` | 不需要（next 預設不可編輯，編輯要另裝 `react-bootstrap-table2-editor`） | — |

`sortFunc` 的機械改法：把 R15 的 `(a, b, order) => …a.foo…b.foo…` 改成 `(_a, _b, order, dataField, rowA, rowB) => 原函式(rowA, rowB, order)`，本體一字不動。先例 `frontend/react_18/src/containers/Table/formOverview/proPlan/DataTable.tsx:230` 就是這個形狀。

### 5.3 表格層 props 對照

| R15 | R18 | R18 先例 |
|---|---|---|
| `pagination`（布林） | `pagination={paginationFactory({...})}` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:156` |
| `options={{ sizePerPage: 25, hideSizePerPage: true }}` | 併入 `paginationFactory({ sizePerPage: 25, hideSizePerPage: true })` | `frontend/react_18/src/pages/epidemicPreventionRecord/VaccineRecordTable.jsx:498-504` |
| `options={{ noDataText: t('no-data') }}` | `noDataIndication={t('no-data')}`（表格層 prop） | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:161` |
| `options={{ onPageChange, onSortChange, page, sortName, sortOrder }}` + `remote` + `fetchInfo={{ dataTotalSize }}` | `remote` + `onTableChange={(type, newState) => …}` + `sort={{ dataField, order }}` + `pagination={paginationFactory({ page, sizePerPage, totalSize, onPageChange })}` | `frontend/react_18/src/pages/epidemicPreventionRecord/VaccineRecordTable.jsx:511-555`（`handleTableChange` 的 `type` 為 `'filter'`/`'sort'`/`'pagination'`） |
| `selectRow={{ mode:'radio', clickToSelect:true, onSelect }}` | 同名同形（另可加 `selectColumnStyle` / `headerColumnStyle`） | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:91-97,160` |
| `striped hover condensed` | 不變（另建議加 `bootstrap4`） | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:150-155` |
| `ref='table'` + `this.refs.table.state.currPage` / `.sizePerPage` | **next 沒有這個 state**。序號欄改用 `formatter: (_cell, _row, rowIndex) => (page - 1) * SIZE_PER_PAGE + rowIndex + 1`，`page` 由元件自己持有 | `frontend/react_18/src/pages/epidemicPreventionRecord/VaccineRecordTable.jsx:270` |

R15 需要處理的 `this.refs.table.state` 位置（遷移到這些檔時必踩）：`frontend/react_15/employeeList/components/EmployeeTable.jsx:68`、`frontend/react_15/daycaseList/components/CaseTable.jsx:47`、`frontend/react_15/case/components/CaseForms/CaseFormDataList/CaseFormDataTable/CaseFormDataTable.jsx:50`、`frontend/react_15/case/components/SrviceRecordForm/RecordFormDataList/RecordFormDataTable/index.js:31`。

### 5.4 分頁樣式 class 名改變

R15 `.react-bs-table-pagination` → R18 `.react-bootstrap-table-pagination`。既有證據：R15 `frontend/react_15/style/bootstrap-custom.css:1065` vs R18 `frontend/react_18/src/pages/mainFrame/style.scss:192`。頁面自帶 SCSS 若命中 `react-bs-table*` 前綴，一併改名。

### 5.5 何時用 `TableContainer`（答案：遷移時一律不用）

R18 另有自製表格 `frontend/react_18/src/containers/Table/TableContainer/TableContainer.jsx`（props 定義在 `:561-614`），全庫 18 個檔在用；react-bootstrap-table-next 則有 71 個檔在用。

**規則**：R15 頁面用 `react-bootstrap-table` → R18 一律對映 `react-bootstrap-table-next`。`TableContainer` 的 `columns` / `getList` / `expandRow` 語意與 rbt v1 不同，改用它等於重寫 → 違反最小改動。只有在 R15 頁面本來就沒有表格、而 R18 側需要新建表格時才考慮（本 skill 不會發生）。

---

## 6. react-select 1.3.0 → 5.8.0

### 6.1 核心語意變化（最容易靜默壞掉的一項）

- **v1 + `simpleValue`**：`value` 傳字串（多選時是逗號串接字串），`onChange` 收到的也是字串。
- **v5**：`value` 必須是 **option 物件**（單選）或 **option 物件陣列**（多選）；`onChange` 收到的也是物件 / 物件陣列 / `null`。v5 **沒有 `simpleValue`**。

R15 現況：`simpleValue` 18 處、`multi` 42 處、`clearable` 106 處、`searchable` 36 處、`removeSelected` 24 處、`labelKey` 8 處（統計範圍＝50 個 import 了 react-select 的 R15 檔）。

**value adapter 機械寫法**（R18 先例 `frontend/react_18/src/containers/Selector/YearSelector.tsx:61`）：

```jsx
// R15: value={this.props.filter.category}            // 字串
// R18:
value={options.find((option) => option.value === this.props.filter.category) || null}
```

**onChange adapter**（R18 先例 `frontend/react_18/src/containers/Selector/YearSelector.tsx:50-54`）：單選把 `option?.value` 取出後丟回原本的 handler，handler 本體不動；多選（`isMulti`）傳回的是陣列，若原本 R15 handler 吃逗號字串，就在呼叫前 `.map(o => o.value).join(',')`。R18 多選把物件陣列整包往上傳的先例：`frontend/react_18/src/pages/remind/components/HeaderPanel.jsx:98-104,183`。

### 6.2 props 改名對照

| R15（v1） | R18（v5） | R15 先例 | R18 先例 |
|---|---|---|---|
| `multi` | `isMulti` | `frontend/react_15/shiftList/components/shiftFilter.js:456` | `frontend/react_18/src/pages/remind/components/HeaderPanel.jsx:177` |
| `clearable` / `clearable={false}` | `isClearable` / `isClearable={false}` | `frontend/react_15/daycaseShiftList/components/ScheduleMain.js:875` | `frontend/react_18/src/containers/Selector/report/CommonSelector.tsx:58` |
| `searchable` | `isSearchable` | `frontend/react_15/daycase/components/CaseCalendar/Modal/UpdatePunchRecordModalV2.jsx:1192` | `frontend/react_18/src/containers/Selector/report/CommonSelector.tsx:59` |
| `disabled` | `isDisabled` | `frontend/react_15/shiftList/components/shiftFilter.js:463` | `frontend/react_18/src/containers/Selector/reportSetting/EmployeeListSelector.tsx:162` |
| `simpleValue` | **移除**，改 value adapter（§6.1） | `frontend/react_15/shiftList/components/shiftFilter.js:461` | `frontend/react_18/src/containers/Selector/YearSelector.tsx:61` |
| `removeSelected`（多選已選項目不再出現在選單） | `hideSelectedOptions`（v5 多選預設就是 `true`，通常直接刪掉即可） | `frontend/react_15/shiftList/components/shiftFilter.js:460` | 無先例（R18 全庫 0 處 `hideSelectedOptions`） |
| `labelKey="name"` / `valueKey` | **移除**，改 `getOptionLabel={(o) => o.name}` / `getOptionValue`，或把 options 先 map 成 `{ value, label }` | `frontend/react_15/daycase/components/CaseCalendar/Modal/CreateShiftModalV2.jsx:345` | 無先例（R18 全庫 0 處 `getOptionLabel`）；R18 一律事先 map 成 `{ value, label }`，先例 `frontend/react_18/src/containers/Selector/YearSelector.tsx:36-43` |
| `noResultsText="..."` | `noOptionsMessage={() => '...'}` | `frontend/react_15/case/components/CaseSwitcher.jsx:216` | `frontend/react_18/src/containers/Selector/companySetting/CompanySelect.jsx:71` |
| `optionRenderer` / `valueRenderer` | `components={{ Option, SingleValue }}` | `frontend/react_15/daycase/components/CaseCalendar/Modal/UpdatePunchRecordModalV2.jsx:1353-1354` | `frontend/react_18/src/containers/Selector/companySetting/CompanySelect.jsx:72`（`components={{ Input }}`） |
| `filterOption` | 不變（簽名 `(option, rawInput)`） | `frontend/react_15/daycase/components/CaseCalendar/Modal/UpdatePunchRecordModalV2.jsx:1355` | 無先例 |
| `onInputChange` | 不變 | `frontend/react_15/activityCalendar/components/CalendarActivityCreateModal.js:1026` | 無先例 |
| `options` / `placeholder` / `onChange` | 名稱不變（`onChange` 值形狀變，見 §6.1） | `frontend/react_15/shiftList/components/shiftFilter.js:457-459` | `frontend/react_18/src/containers/Selector/report/CommonSelector.tsx:60-63` |
| `closeMenuOnSelect` | v5 新增，多選時想維持 v1「選完不關」行為就加 `closeMenuOnSelect`（不帶值＝true） | — | `frontend/react_18/src/containers/Selector/reportSetting/EmployeeListSelector.tsx:160` |
| `style` / `menuContainerStyle` | `styles={{ …客製 }}` | — | `frontend/react_18/src/pages/remind/components/HeaderPanel.jsx:184` |
| `import 'react-select/dist/react-select.css'` | **刪掉**（v5 用 emotion，無此檔） | `frontend/react_15/index.js:26` | R18 `frontend/react_18/src/index.js` 無此 import |

⚠️ 不要替 v5 的 `<Select>` 手動加 `closeMenuOnScroll`（會造成捲動即關閉選單；v5 內建的浮動定位本來就會跟隨）。

---

## 7. react-router 3 → 6（class component shim）

R18 沒有 `withRouter`。唯一存在的路由 HOC 是 `withLocation`，定義在 `frontend/react_18/src/pages/mainFrame/index.jsx:91-94`，**且未 export**——它是「照抄的樣板」不是「可 import 的模組」。遷移時把這 4 行複製到要遷移的檔案內、緊接 import 區之後。

```jsx
/**
 * @method withLocation 透過useLocation取得location
 * @param {Component} Children 子元件
 * @returns {Component} 回傳包含location的元件
 */
const withLocation = (Children) => (props) => {
  const location = useLocation();
  return <Children {...props} location={location} />;
};
```

| R15 | R18 | R18 先例 |
|---|---|---|
| `this.props.location`（由 react-router 3 自動注入） | 用上面的 `withLocation` 包最外層，`this.props.location` 仍可用 | 定義 `frontend/react_18/src/pages/mainFrame/index.jsx:91`；套用 `frontend/react_18/src/pages/mainFrame/index.jsx:769`（`connect(...)(withTranslation(...)(withLocation(index)))`，**順序照抄**） |
| `import { useLocation } from 'react-router'` | `import { useLocation } from 'react-router-dom';` | `frontend/react_18/src/components/NavButton.js:17` |
| `this.props.router.push(url)` | `import { push } from 'redux-first-history';` → 在 `mapDispatchToProps` 加 `redirect: (url) => dispatch(push(url))`，元件呼叫 `this.props.redirect(url)` | `frontend/react_18/src/redux/actioncreators/base/baseActionCreator.js:7,22-24`（`redirect(url) { return push(url); }`）。⚠ 此 helper 目前 R18 全庫 **0 個 consumer**，先例只到「API 用法」層級，沒有 class 元件呼叫端先例。R15 對應寫法見 `frontend/react_15/caseList/index.jsx:1170-1177`（`dispatch(push({ pathname, state }))`）——物件形式在 v6 一樣支援。 |
| `this.props.router.replace(url)` | `import { replace } from 'redux-first-history';` + `dispatch(replace(url))` | `redux-first-history` 有匯出 `replace`（與 `push`、`go`、`goBack`、`goForward` 同一組）。R15 呼叫點 `frontend/react_15/writeOff/index.js:169`、`frontend/react_15/activityManager/index.js:96`、`frontend/react_15/components/withSubpageRouter/withSubpageRouter.js:90`。無 R18 先例。 |
| `this.props.router.setRouteLeaveHook(route, fn)` | **v6 移除**。R18 對應能力在 `frontend/react_18/src/shared/hooks/useNavigationPrompt.ts:17-40`（hook，只能用在 function component） | R15 唯一呼叫點 `frontend/react_15/case/components/CaseForms/index.js:152`。class 元件無先例 → `blocked(no_mapping)` |
| `this.props.params.id` | v6 無自動注入。用 `withLocation` 後從 `this.props.location.pathname` 取；R18 既有作法是 `location?.pathname?.split('/').pop()` | `frontend/react_18/src/routes/EmployeeRoute.tsx:71`（`useMemo(() => location?.pathname?.split('/').pop(), [location])`）。R15 呼叫點：`frontend/react_15/deviceSensorList/index.js:15`、`frontend/react_15/caseMealRecord/index.jsx:81` |
| `import { Link } from 'react-router'` | `import { Link } from 'react-router-dom';`（`to` 用法不變） | `frontend/react_18/src/containers/Table/interview/InterviewTable.jsx:22`；R15 對應 `frontend/react_15/daycaseList/components/CaseTable.jsx:60` |
| `<LinkContainer>`（react-router-bootstrap） | 無對應套件（R18 未安裝）→ 改 `<Nav.Link href={...}>` 或 `<Link>` | R15 呼叫點 `frontend/react_15/breathing/components/BreathingHeader.js:10`（5 處）。無 R18 先例 |
| 路徑前綴 | R18 一律 `${config.DEPLOY_PREFIX}${path}` | `frontend/react_18/src/routes/EmployeeRoute.tsx:212` |

---

## 8. 樣式搬移

### 8.1 同層 css/scss：照搬

R15 頁面自帶樣式（`import './xxx.css'` / `'./xxx.scss'`，共 154 處）→ 連檔案一起複製到 R18 落點同層，import 行原樣保留。

- R15 先例：`frontend/react_15/daycaseShiftList/components/ShiftTable/index.js:17`
- R18 先例：`frontend/react_18/src/pages/calendarManager/CompanyCalendar.tsx:50`、`frontend/react_18/src/pages/memberFAQ/MemberFAQ.tsx:14`
- 整頁遷移含新增 `.scss` 的先例：commit `e5b7c0e52b`（新增 `frontend/react_18/src/pages/expertAcase/PlanHistory.scss`）

### 8.2 R15 全域樣式的處置

R15 只在入口 `frontend/react_15/index.js:20-23,27` 載入 5 個全域檔（`style/bootstrap-custom.css`、`style/fit.css`、`style/location.css`、`style/bootstrap-card.css`、`style/global.scss`，`style/_variable.scss` 由 `global.scss` 間接引入）。這 5 個檔共定義 312 個 class，其中 **92 個**被 R15 頁面的 `className` 直接使用。

R18 的全域樣式是 `frontend/react_18/src/assets/styles/`（`index.css`、`bootstrap.scss`、`index.scss`、`fontOverrides.scss`，於 `frontend/react_18/src/index.js:42-45` 載入）。把上述 92 個 class 逐一比對 R18 全庫所有 130 個 `.css`/`.scss`：**55 個在 R18 完全查無定義**。

**規則**（依序判斷）：

1. 該 class 是 **Bootstrap 3 utility**（`pull-right`、`pull-left`、`form-inline`、`table-bordered`、`glyphicon`、`panel-body`、`col-xs-*`…）→ 查 §4 表改成 BS5 對應 class。**不要**把 BS3 定義複製進 R18。
2. 該 class 是 **本頁專屬樣式**（`shift-detail-option-modal`、`activity-calendar-toolbar`、`scheduler-container`、`shift-block`、`case-header`、`prev-header`、`next-header`、`user-col`、`schedule-week`… 這類頁面名開頭者）→ 從 R15 全域檔把該 class 的整段規則剪下，貼進**該頁在 R18 的同層 `.scss`**（沒有就新建，檔名同元件名），再於元件檔 `import './<元件名>.scss';`。**不得**寫進 `frontend/react_18/src/assets/styles/` 任何檔（那是全域，會波及所有頁面）。
3. 該 class 在 R18 已有定義 → 不動。
4. 判斷不出屬於哪一頁（多頁共用的泛用名，如 `title`、`icon`、`red`、`navigation`、`expanded`、`week`）→ contract.md 標 ⚠，並比照 2 搬進本頁 scss（重名風險由「只在本頁 scss、且外層包一個頁面容器 class」降低）。

**自檢**：遷移完成後對該頁 R18 檔案抽出所有 `className` 字面 token，逐一確認「在 R18 某個會被載入的 css/scss 裡找得到」或「是 BS5/tailwind 既有 class」。找不到的即為漏搬。

### 8.3 R18 的 flex 表格版面（影響所有表格欄寬）

`frontend/react_18/src/assets/styles/_default.scss:21-42` 把全站 `table` 改成 flex 版面：`table{display:flex;flex-flow:column}`、`thead{flex:0 0 auto}`、`tbody{display:block;overflow-y:auto}`、`tr{display:table;table-layout:fixed}`。

後果：**thead 的 tr 與 tbody 每一個 tr 都是各自獨立的 table box，欄寬各自計算**。R15 的 `react-bootstrap-table` 的 `width` prop 由元件自行同步 th/td，遷到 R18 後沒有這層同步。

規則：
1. 要指定欄寬，`headerStyle`（或 `headerClasses`）與 `style`（或 `classes`）**兩邊都要給，且值完全相同**。只給一邊＝ bug。
2. **禁止**用 `tw-max-w-[Npx]` 控欄寬（flex table 下 `max-width` 只設上限、不會把欄位撐開）。要換行用 `tw-break-words`，寬度另外用固定寬度值。
3. 不指定寬度的欄位，兩邊都不要寫（兩邊都不給時平均分配結果一致）。

### 8.4 tailwind

R18 有 tailwind（`tw-` 前綴，341 個檔在用）。**遷移時不得把 R15 的 CSS 改寫成 tailwind**；`tw-` 只用在遷移過程中確實必須新寫的樣式（例如 §8.3 的欄寬）。

---

## 9. i18n（react-i18next 2.2.3 → 11.18.6）

### 9.1 HOC 改名

| R15 | R18 | R15 先例 | R18 先例 |
|---|---|---|---|
| `import { translate } from 'react-i18next';` | `import { withTranslation } from 'react-i18next';` | `frontend/react_15/deviceManagerList/components/DayCareDeployModal.js:12` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:194` |
| `translate(['common','device'], { wait: true })(C)` | `withTranslation(['common','device'], { wait: true })(C)` | `frontend/react_15/deviceManagerList/components/DayCareDeployModal.js:143` | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:194`（R18 全庫 46 處同形） |
| 與 `connect` 的組合順序 | `connect(mapStateToProps, mapDispatchToProps)(withTranslation([...], { wait: true })(C))` | — | `frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:194`、`frontend/react_18/src/pages/dispatchCompanyList/DispatchCompanyList.jsx:211` |

`{ wait: true }` 在 react-i18next 11 已經**不再是有效選項**（`withTranslation` 只讀 `options.keyPrefix` 與 `options.withRef`，其餘丟棄）。它無害且是 R18 既定寫法（46 處），照寫即可，**不要**自作主張刪掉或改成 `useSuspense`。

### 9.2 `this.props.t` 的 namespace 解析差異（必查，會靜默壞掉）

實測兩版 dist：

- R15（react-i18next 2.2.3，`dist/commonjs/translate.js:78`）：`this.t = this.i18n.getFixedT(null, namespaces)` — 傳**整個陣列**。i18next 的 resolve 會**依序試每一個 namespace** 直到命中。
- R18（react-i18next 11.18.6，`dist/commonjs/useTranslation.js:71`）：`i18n.getFixedT(null, i18nOptions.nsMode === 'fallback' ? namespaces : namespaces[0], keyPrefix)` — 預設**只用第一個 namespace**。
- 而 `withTranslation(ns, options)` 把 `options` 裡的 `nsMode` **丟掉**（只轉 `keyPrefix`），所以 `withTranslation([...], { nsMode: 'fallback' })` 沒有作用。
- R18 的 i18next init（`frontend/react_18/src/i18next.js`）沒有設 `fallbackNS`。

**結論與機械規則**：R15 元件 `translate(['a','b','c'])` 底下任何取自 `b`/`c` 的 key，遷到 R18 後必須在呼叫端明確指定 namespace：

```jsx
// R15: t('MALE')            // 落在 'enum'，靠陣列 fallback 命中
// R18:
t('MALE', { ns: 'enum' })
```

R18 先例（全庫 532 處同形）：`frontend/react_18/src/containers/ContactSelect/ContactTable.jsx:119`、`frontend/react_18/src/shared/utils/renderOption.jsx:26`、`frontend/react_18/src/shared/utils/getEnumObject.js:11`。

**Phase 1 合約抽取必做**：把該頁所有 `t('...')` 的 key 對照 namespace 檔，凡不在第一個 namespace 的都列進合約表，Phase 2 逐一補 `{ ns: 'xxx' }`。漏掉的症狀是畫面直接顯示原始 key（不會報錯）。

### 9.3 namespace 檔位置

兩版**共用同一組檔案**：`backend/public/locales/lang/zh-TW/*.json`（32 個檔：`common.json`、`case.json`、`employee.json`、`enum.json`、`shift.json`、`report.json`、`settings.json`…）。R18 的 loadPath 設定在 `frontend/react_18/src/i18next.js:47`。

**遷移不需要動 locale 檔**；若 R15 用到的 key 不存在，那是既有問題，contract.md 標 ⚠，不要順手新增。

---

## 10. 其他第三方套件

### 10.1 sweetalert2 6.11.5 → 11.10.1（R15 頁面 44 處 import）

| R15 | R18 | R18 先例 |
|---|---|---|
| `Swal({ title, text, type: 'success' })` 或 `swal({...})` | `Swal.fire({ title, text, icon: 'success' })` | `frontend/react_18/src/containers/Form/Form.jsx:431` |
| `type: 'success' / 'error' / 'warning' / 'info' / 'question'` | `icon:` 同值 | `frontend/react_18/src/containers/Form/IframeForm.jsx:276`（R18 全庫 144 處 `icon:`；R15 全庫 55 處 `type:`，例 `frontend/react_15/daycase/components/AccreditationForm/IframeForm.js:207`） |
| 取消時 **promise reject** → `.catch(() => {})` | promise **永遠 resolve**，用 `.then((result) => { if (result.isConfirmed) {…} })` | `frontend/react_18/src/containers/Form/Form.jsx:440`（`if (result.isConfirmed)`；R18 全庫 65 處） |

R15 呼叫點統計：`Swal(` 49 處、`swal(` 36 處、`.catch(() => {})` 收尾 11 處。R15 先例 `frontend/react_15/daycaseList/index.jsx:126`（`Swal({ type, title, text }).catch(() => {})`）。

### 10.2 react-bootstrap-typeahead 0.10.4 → 6.3.2（R15 34 處 import）

| R15 | R18 | R18 先例 |
|---|---|---|
| `import 'react-bootstrap-typeahead/css/Token.css'`（在 `frontend/react_15/index.js:24`） | `import 'react-bootstrap-typeahead/css/Typeahead.css'`（已在 `frontend/react_18/src/index.js:36` 全域載入，頁面不用再 import） | `frontend/react_18/src/index.js:36` |
| `<Typeahead multiple labelKey options onChange />` | 同名 props 仍可用 | `frontend/react_18/src/containers/Form/HeimlichEvaluationForm.js:142-148`、`frontend/react_18/src/containers/Form/FirstVisitForm.js:1082-1088` |
| `ref="owner"` + `this.refs.owner.getInstance()` | v6 無 `getInstance()`，ref 直接就是實例 | 無先例 |
| `minLength="1"` | `minLength={1}`（v6 要 number） | 無先例 |

⚠ v1.x 的 class 名（`.rbt-*` 之外的舊名）在 v6 已改；頁面 SCSS 若鎖 typeahead 內部 class，contract.md 標 ⚠。

### 10.3 兩版版本相同 / 可直接照搬

`moment` 2.24→2.29、`moment-range` 4.0.2、`underscore` 1.10.2、`ramda` 0.27→0.28、`prop-types`、`sha1`、`signature_pad`、`enumeration`、`rc-time-picker`、`react-to-print` 2.14.11（R15 10 處）、`react-idle-timer` 4.6.4 — 原樣搬。

### 10.4 `lodash`（R15 頁面 23 處）

`lodash` **不在** `frontend/react_18/package.json` 的 dependencies，但 `react_18/node_modules` 有 4.17.21（傳遞相依），且 R18 已有 38 處 `import _ from 'lodash'`（例如 `frontend/react_18/src/containers/Form/ActivityPlanForm.js:6`）。**照搬 import，不要改寫成 ramda/underscore**；若 Phase 5 build 失敗再處理。

### 10.5 R18 沒有的套件 → `blocked(no_mapping)`

下列套件只存在於 R15 且被頁面 import。遷移到用到它們的頁面時，直接 `blocked(no_mapping)`，由人工決定：

| 套件 | R15 版本 | R15 import 數 | R15 先例 |
|---|---|---|---|
| `dayz` | 2.9.0 | 1 | `frontend/react_15/daycase/components/CaseCalendar/index.jsx:18` |
| `react-bootstrap-toggle` | 2.3.2 | 3 | `frontend/react_15/daycase/components/CaseCalendar/index.jsx:21` |
| `react-router-bootstrap`（`LinkContainer`） | 0.23.3 | 5 | `frontend/react_15/breathing/components/BreathingHeader.js:10` |
| `@visx/group` / `@visx/hierarchy` / `@visx/shape` / `d3-hierarchy` | 1.x / 2.0.0 | 17 | `frontend/react_15/case/components/CaseForms/FormEditors/utils/FamilyTree/Genogram/index.js:7-10` |
| `save-svg-as-png` | 1.4.17 | 2 | `frontend/react_15/case/components/CaseForms/FormEditors/utils/FamilyTree/index.js:13` |
| `atob` | 2.1.2 | 3 | `frontend/react_15/case/components/CaseForms/FormEditors/utils/FamilyTree/index.js:9` |
| `async` | 2.6.3 | 3 | `frontend/react_15/daycase/components/CaseCalendar/Modal/CheckinModal.js:16` |
| `qrcode.react` | 0.8.0 | 1 | `frontend/react_15/case/components/QRCodeHistory.js:16` |
| `react-image-file-resizer` | 0.3.1 | 1 | `frontend/react_15/case/components/CaseForms/FormEditors/utils/ImageUpload/index.js:8` |
| `react-open-app` | 1.0.3 | 1 | `frontend/react_15/caseMealRecord/index.jsx:15` |
| `react-addons-css-transition-group` | 15.6.2 | 1 | `frontend/react_15/modules/notification/react-notifications.patch.js:7` |
| `jquery` / `jquery-ui*` | 3.5.0 / 1.12.1 | 只在入口層 `frontend/react_15/index.js:15,25` 載入（頁面不 import） | 頁面若直接用全域 `$`，`blocked(no_mapping)` |

### 10.6 兩版都有但主版本差很多 → 逐案查證，先標 ⚠

`react-dropzone` 3.13.4 → 14.2.3（R15 12 處，API 從 `<Dropzone onDrop>` 子元素改成 `useDropzone`/render prop）、`react-datetime` 2.8.10 → 3.3.1、`react-pdf` 3.0.6 → 6.2.0、`react-cropper` 1.3.0 → 2.3.3、`chart.js` 2.6.0 → 3.9.1 + `react-chartjs-2` 2.1.0 → 5.3.0（chart.js 3 是 tree-shaking 架構，需 `registerables`）、`react-loading` 1.0.5 → 2.0.3、`react-notifications` 1.6.0 → 1.7.4、`superagent` 3.8.3 → 8.1.2。**這些沒有現成逐 prop 對照，一律在 contract.md 標 ⚠ 並在 Phase 3 逐項驗證。**

---

## 11. 「無先例」清單（遇到就 `blocked(no_mapping)` 或人工判斷）

1. `componentWillMount` → `UNSAFE_componentWillMount`（R18 全庫 0 處；規則明確但無範本）
2. `componentWillUpdate` → `UNSAFE_componentWillUpdate`（R18 只有未加前綴的反例）
3. `<Form.Check inline>` / `<Form.Check type="radio">`
4. `<HelpBlock>` → `<Form.Text>`
5. `<Well>` 的替代
6. `<Jumbotron>` 的替代
7. `<Tabs>` / `<Tab>`（v2 有匯出但 R18 無使用範例）
8. `<ListGroupItem>` → `<ListGroup.Item>`
9. `<Carousel>`
10. `<Popover.Title/Content>` → `<Popover.Header/Body>`
11. `bsClass` → `className`
12. rbt-next 的 `formatExtraData`
13. rbt-next 的 `classes` / `headerClasses`（作為 `columnClassName` 的替代）
14. react-select `hideSelectedOptions`（`removeSelected` 的替代）
15. react-select `getOptionLabel` / `getOptionValue`（`labelKey` / `valueKey` 的替代）
16. react-select `filterOption`、`onInputChange`
17. `this.props.router.replace` → `dispatch(replace(url))`
18. `setRouteLeaveHook` 在 class component 的替代
19. `LinkContainer` 的替代
20. typeahead 的 `getInstance()` 與 `minLength` 型別
21. §10.5 全部套件
