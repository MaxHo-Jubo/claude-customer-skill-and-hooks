/**
 * R15 vs R18 差異測試樣板——action creator 對跑、reducer 對跑、util 對跑三個區段。
 *
 * 本檔案不可直接執行：`__R15_PATH__`、`__R18_PATH__`、`__CASES__`、`__ACTION_TYPE_MAP__`
 * 是留給產生器（generator）做文字替換的佔位符。它們在語法上都是合法的 JS
 * （`__CASES__`/`__ACTION_TYPE_MAP__` 是合法識別字、`__R15_PATH__`/`__R18_PATH__` 落在字串常值
 * 內），`node --check` 能通過，但替換前執行會直接失敗：require 找不到檔案、
 * CASES/ACTION_TYPE_MAP 是 undefined。
 *
 * 佔位符替換契約：
 * - `__R15_PATH__` / `__R18_PATH__`：本次「主要模組」（reducer 對跑區段用）的絕對路徑字串，
 *   直接替換進 require('') 的參數位置，例如 require('/abs/path/to/xxxReducer.js')。
 * - `__CASES__`：單一物件常值，取代成一整包三個區段各自的測試案例陣列，形狀見下方型別註解。
 *   action creator／util 要測的模組通常跟 reducer 不同檔（R15 是 actions/xxxAction.js、
 *   utils/xxxUtil.js，R18 是 actioncreators/xxxActionCreator.ts 等），所以這兩區段的每個
 *   case 都要自帶 r15ModulePath/r18ModulePath（絕對路徑字串），不依賴頂層的
 *   __R15_PATH__/__R18_PATH__——那兩個只給 reducer 對跑區段用。
 * - `__ACTION_TYPE_MAP__`：單一物件常值，key 是 __CASES__.reducer 裡每一筆 case 用到的
 *   action.type 字面字串（R15 慣例，例如 'CREATE_PROPLAN_SUCCESS'），value 是對應的 R18
 *   action.type 字面字串（R18 慣例是 `X.SUCCESS` 這種物件屬性存取，這裡要填的是它解析出來
 *   的字串值，例如 'CREATE_PROPLAN_SUCCESS'——R18 的 SUCCESS/FAILURE 字尾不一定跟 R15 的
 *   SUCCESS/FAIL 一樣，兩邊都要用實際常數值核對，不要用字串規則猜）。
 *   即使 R15/R18 兩邊字面相同，也要顯式列出恆等映射——不要指望「查不到就用原字串」這種
 *   靜默 fallback，那會把未來 R18 改了常數值的差異吃掉，變成兩邊用不同 type 各自落進
 *   default 分支、卻因為都回傳 { ...state } 而誤判成通過。
 *
 * @typedef {Object} ActionCreatorCase
 * @property {string} description - 案例描述
 * @property {string} r15ModulePath - R15 action creator 檔案絕對路徑
 * @property {string} r18ModulePath - R18 action creator 檔案絕對路徑
 * @property {string} r15FnName - 該檔案匯出的 R15 函式名稱
 * @property {string} r18FnName - 該檔案匯出的 R18 函式名稱（可能與 r15FnName 不同名）
 * @property {any[]} args - 呼叫兩邊函式用的參數（同一組參數餵兩邊）
 *
 * @typedef {Object} ReducerCase
 * @property {string} description - 案例描述
 * @property {any} [state] - 前置 state；省略則兩邊都用各自 reducer 的預設參數值（undefined）
 * @property {{ type: string, [key: string]: any }} action - R15 慣例的 action（type 用 R15
 *   字面字串，會先經 ACTION_TYPE_MAP 轉換出 R18 端要用的 type 才丟給 R18 reducer；其餘欄位
 *   原樣帶給兩邊，若 R15/R18 的 payload 欄位名不同，case 準備時就要各自對齊，本樣板不做欄位改名）
 *
 * @typedef {Object} UtilCase
 * @property {string} description - 案例描述
 * @property {string} r15ModulePath - R15 util 檔案絕對路徑
 * @property {string} r18ModulePath - R18 util 檔案絕對路徑
 * @property {string} r15FnName - 該檔案匯出的 R15 函式名稱
 * @property {string} r18FnName - 該檔案匯出的 R18 函式名稱
 * @property {any[]} args - 呼叫兩邊函式用的參數
 */
'use strict';

// STEP 01: 載入本次對跑的主要模組（reducer 對跑區段使用）
const r15Module = require('__R15_PATH__');
const r18Module = require('__R18_PATH__');

// STEP 02: 載入案例資料與 action type 對應表，內容由產生器負責填入
const CASES = __CASES__;
const ACTION_TYPE_MAP = __ACTION_TYPE_MAP__;

/**
 * 把 R15 reducer 測試案例裡的 action type（R15 慣例：`${X}_SUCCESS`/`${X}_FAIL` 純字串常數）
 * 轉換成 R18 慣例對應的 action type 字串。查不到就直接 throw，不做靜默 fallback——
 * 查不到代表 ACTION_TYPE_MAP 沒補全，應該回頭補產生器輸入，而不是讓這個案例用錯的 type
 * 跑出一個看似通過、實際上兩邊落進不同分支的假陽性。
 * @param {string} r15Type - R15 action.type 字面字串
 * @returns {string} 對應的 R18 action.type 字面字串
 */
function resolveR18ActionType(r15Type) {
  if (!Object.prototype.hasOwnProperty.call(ACTION_TYPE_MAP, r15Type)) {
    throw new Error(`ACTION_TYPE_MAP 缺少 R15 action type「${r15Type}」的 R18 對應值，請補齊產生器輸入`);
  }
  return ACTION_TYPE_MAP[r15Type];
}

/**
 * 取一個模組的預設 export，相容兩種形狀：
 * - R15 原始碼是 `export default function xxx() {}`，經 babel transform-modules-commonjs
 *   轉譯後變成 `{ default: fn, __esModule: true }`
 * - 少數檔案本來就用具名 export（`module.exports = fn` 或 `exports.xxx = fn`），沒有 default
 *   屬性時視整個 module.exports 本身就是目標函式/物件
 * @param {any} mod - require() 回傳的模組物件
 * @returns {any} 實際要使用的匯出內容
 */
function unwrapDefaultExport(mod) {
  return Object.prototype.hasOwnProperty.call(mod, 'default') ? mod.default : mod;
}

describe('action creator 對跑：R15 vs R18', () => {
  /** @type {ActionCreatorCase[]} */
  const actionCreatorCases = CASES.actionCreator || [];

  if (actionCreatorCases.length === 0) {
    it.todo('尚未提供 action creator 對跑案例');
  }

  actionCreatorCases.forEach(({
    description, r15ModulePath, r18ModulePath, r15FnName, r18FnName, args,
  }) => {
    it(description, () => {
      // STEP 01: 各自載入案例指定的模組（通常跟 reducer 不同檔，見檔案頂部佔位符契約說明）
      const r15Fn = require(r15ModulePath)[r15FnName];
      const r18Fn = require(r18ModulePath)[r18FnName];

      // STEP 02: 同一組參數餵兩邊，斷言回傳的 action 物件深相等
      const r15Result = r15Fn(...args);
      const r18Result = r18Fn(...args);
      expect(r18Result).toEqual(r15Result);
    });
  });
});

describe('reducer 對跑：R15 vs R18', () => {
  /** @type {ReducerCase[]} */
  const reducerCases = CASES.reducer || [];
  const r15Reducer = unwrapDefaultExport(r15Module);
  const r18Reducer = unwrapDefaultExport(r18Module);

  if (reducerCases.length === 0) {
    it.todo('尚未提供 reducer 對跑案例');
  }

  reducerCases.forEach(({ description, state, action }) => {
    it(description, () => {
      // STEP 01: R15 reducer 直接吃原始 action（type 是 reducer 內部字面比對用的 R15 字串）
      const r15Result = r15Reducer(state, action);

      // STEP 02: R18 reducer 要吃轉換過 type 的 action，其餘欄位原樣帶過去
      const r18Action = { ...action, type: resolveR18ActionType(action.type) };
      const r18Result = r18Reducer(state, r18Action);

      // STEP 03: 斷言兩邊輸出深相等
      expect(r18Result).toEqual(r15Result);
    });
  });
});

describe('util 對跑：R15 vs R18', () => {
  /** @type {UtilCase[]} */
  const utilCases = CASES.util || [];

  if (utilCases.length === 0) {
    it.todo('尚未提供 util 對跑案例');
  }

  utilCases.forEach(({
    description, r15ModulePath, r18ModulePath, r15FnName, r18FnName, args,
  }) => {
    it(description, () => {
      const r15Fn = require(r15ModulePath)[r15FnName];
      const r18Fn = require(r18ModulePath)[r18FnName];

      const r15Result = r15Fn(...args);
      const r18Result = r18Fn(...args);
      expect(r18Result).toEqual(r15Result);
    });
  });
});
