# diff-test：R15 / R18 差異測試 harness

讓 React 15 舊碼樹（babel 6 stage-0 語法）與 React 18 新碼樹（TypeScript）的 **reducer、
action creator、純 util 函式**在同一個 jest process 內載入，對跑輸出並斷言深相等。

## 這個 harness 不做什麼

只覆蓋「不 import React」的純邏輯模組（reducer / action creator / util）。**不支援**會
import React 元件的檔案——react_15 用 React 15、react_18 用 React 18，兩個 react 版本裝在
各自的 `node_modules` 下，若同一個 jest process 內兩邊都載入 React 元件，會撞兩份不同版本
的 React 執行期狀態（hooks dispatcher、context 等），行為未定義。純函式/物件（reducer、
action creator、util）沒有這個問題，是唯一保證安全的對跑範圍。

## 怎麼跑

```bash
# 1. 設定必要環境變數
export REPO_DIR=/path/to/target-repo       # 目標 repo 根目錄（內含 frontend/react_15、frontend/react_18）
export DIFF_TEST_DIR=/path/to/test-dir     # 放 *.test.js 的目錄；不設定則預設
                                            # ${MIGRATION_STATE_DIR:-$HOME/r18-migration-state/<repo資料夾名>}/diff-tests

# 2. 用 react_18 既有安裝的 jest 執行（見下方「依賴從哪來」）
"$REPO_DIR/frontend/react_18/node_modules/.bin/jest" \
  --config /path/to/diff-test/jest.config.js
```

跑本 harness 自帶的 smoke test（驗證 harness 本身能動）：

```bash
export REPO_DIR=/path/to/target-repo
export DIFF_TEST_DIR=/path/to/diff-test   # 指到本目錄自己，才會抓到 smoke.test.js
"$REPO_DIR/frontend/react_18/node_modules/.bin/jest" --config ./jest.config.js
```

## 產生實際的差異測試檔

1. 複製 `reducer-diff.test.template.js`，依檔案頂部的「佔位符替換契約」把
   `__R15_PATH__`、`__R18_PATH__`、`__CASES__`、`__ACTION_TYPE_MAP__` 換成實際內容。
2. 檔名以 `.test.js` 結尾（不是 `.test.template.js`），放進 `DIFF_TEST_DIR` 底下
   （慣例：`${MIGRATION_STATE_DIR}/diff-tests/<entry>/*.test.js`，不進 repo）。
3. 依「怎麼跑」執行。

`__CASES__` 與 `__ACTION_TYPE_MAP__` 的精確形狀、三個 describe 區段（action creator / reducer
/ util）各自預期的欄位，見樣板檔頂部的 JSDoc `@typedef` 與逐段註解——那份是唯一出處，這裡不重複。

## 依賴從哪來

**沒有另外安裝任何套件**，全部借用 `react_18/node_modules` 既有安裝：

| 套件 | 版本（`react_18/package.json`） | 用途 |
|---|---|---|
| `jest` | `^27.0.4`（實裝 27.5.1） | 測試 runner，直接用 `react_18/node_modules/.bin/jest` 執行 |
| `babel-jest` | 隨 jest 27 附帶（實裝 27.5.1） | jest 的 babel transform |
| `@babel/core` | `^7.18.6` | babel 7 核心 |
| `@babel/preset-env` | `^7.18.6` | ES2015+ 語法轉譯（兩邊 override 都用） |
| `@babel/preset-typescript` | `^7.18.6` | 轉譯 react_18 的 `.ts` 檔 |
| `@babel/preset-react` | `^7.18.6` | react_18 override 保留 JSX 支援彈性 |
| `@babel/plugin-proposal-class-properties` | react_18 既有安裝內的間接依賴，7.x | react_15 override，對應 babel6 stage-0 的 class properties 語法 |

`babel.config.js`、`jest.config.js` 都用 `require.resolve(pkg, { paths: [react18NodeModules] })`
明確指定解析起點，**不依賴 `NODE_PATH` 環境變數、也不在本目錄放 `node_modules`**——
harness 目錄本身沒有安裝任何東西，純粹是路徑轉介到 `react_18/node_modules`。

`react_15/node_modules` 只裝了 babel 6 系列套件（`babel-core`、`babel-preset-es2015`、
`babel-preset-stage-0` 等），API 不相容 babel 7，**不能**拿來當 babel 7 的 preset/plugin 用。
`babel.config.js` 裡「react_15 override」只是「babel6 stage-0 語法該套用哪組 babel7
preset/plugin」的對應表，套件本體一律從 `react_18/node_modules` 解析。

如果目標機器的 `react_18/node_modules` 缺了上述任一套件（例如尚未 `npm install`），
`jest.config.js`/`babel.config.js` 會在啟動時就丟出清楚的「找不到套件」錯誤（見
`lib/env.js` 的 `resolvePackageFrom`），不會用別的版本靜默頂替。此時的備援做法：把缺的套件
裝到 repo 之外的暫存目錄（例如 `${MIGRATION_STATE_DIR}/diff-test-deps`），改用
`require.resolve(pkg, { paths: [<該暫存目錄>/node_modules, react18NodeModules] })`
的順序解析——本 harness 目前**沒有**實作這條路徑，因為 react_18 既有安裝已經涵蓋全部需求，
一旦需要才照這個方向擴充 `lib/env.js`。

## react_15 語法特性 → babel7 plugin 對應表

實際在 `frontend/react_15` 的 `reducers/`、`actions/`、`utils/` 底下 grep 到、且落在
reducer/action creator/util 範圍內的 stage-0 語法：

| 語法 | grep 證據 | babel7 對應 |
|---|---|---|
| object rest/spread | `reducers/proPlanReducer.js:34`、`actions/gCodeStatAction.js:107` | 已是 ES2018 標準語法，`@babel/preset-env`（targets: node current）原生支援，不需要額外 plugin |
| class properties | `utils/crossTabMessageUtil.js:63`（`canBeUsed = () => {}`，定義在 `export class LocalStorageMessager` 內） | `@babel/plugin-proposal-class-properties` |

decorators、export extensions、function bind（`::`）、exponentiation（`**`）等其他 stage-0
語法，在這個範圍內**沒有** grep 到使用（decorator 的唯一命中是
`components/marquee/style.scss` 的 CSS `@` 語法，不是程式碼，已排除誤報），故沒有預先加對應
plugin。之後若要對跑到用了這些語法的檔案，需自行在 `babel.config.js` 的 `REACT15_PLUGINS`
補上，並在這裡補新的 grep 證據。

`babel-plugin-root-import`（react_15 webpack 設定裡的 `$/xxx` 路徑別名）**沒有**加進本
harness，因為 reducers/actions/utils 範圍內沒有 grep 到這種寫法。若之後要對跑用到 root-import
的檔案，需要自行加上這個 plugin 並補對應的 `rootPathSuffix` 設定。

## 已知限制

- **不支援** import React 的檔案（見上方「這個 harness 不做什麼」）。
- **不支援** decorators / export extensions / function bind / exponentiation 等未 grep 到使用的
  stage-0 語法；踩到時的錯誤訊息會是 babel parse error，此時去擴充 `babel.config.js`。
- reducer 對跑要求呼叫端自己把 R15 `${X}_SUCCESS`/`${X}_FAIL` 字面字串與 R18
  `X.SUCCESS`/`X.FAILURE` 解析出的字面字串，逐一填進 `__ACTION_TYPE_MAP__`；樣板不做任何
  「猜測性」字串轉換（例如自動把 `_FAIL` 換成 `.FAILURE`），因為 R15/R18 的欄位命名沒有保證
  規律（實測 `proPlanReducer` 兩邊就是 `_FAIL` vs `.FAILURE` 不對稱）。
- `transformIgnorePatterns` 沿用 jest 預設（整個 `node_modules` 不轉譯）。若對跑目標間接
  import 到 ESM-only 的 npm 套件，會在該處丟出 `SyntaxError: Unexpected token 'export'`；
  屆時再針對那個套件名稱加 `transformIgnorePatterns` 例外，不要預先全開。
- `moduleDirectories` 目前涵蓋兩棵樹的 `node_modules`，但實務上每個檔案自己的相對 import
  早就會透過 Node 預設向上尋找 `node_modules` 命中自己樹，`moduleDirectories` 只是保險機制。
- 本 harness 未內建把測試檔從 `__R15_PATH__` 等佔位符展開成實際 `.test.js` 的產生器腳本，
  那是本 skill 其他部分的職責；本 harness 只保證「展開後的檔案能被正確載入與對跑」。
