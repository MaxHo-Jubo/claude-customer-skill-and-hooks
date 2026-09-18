/**
 * 差異測試 harness 的 smoke test：驗證 jest.config.js + babel.config.js 真的能在同一個
 * jest process 內載入 react_15（babel6 stage-0）與 react_18（TypeScript）兩棵樹的 reducer，
 * 而不是只靠設定檔字面看起來合理。
 *
 * 怎麼跑（細節見同目錄 README.md「怎麼跑」一節）：
 *   REPO_DIR=<repo 根目錄> DIFF_TEST_DIR=<本檔所在目錄> \
 *     <REPO_DIR>/frontend/react_18/node_modules/.bin/jest --config <本目錄>/jest.config.js
 *
 * 對跑目標：
 * - R15：frontend/react_15/reducers/proPlanReducer.js
 * - R18：frontend/react_18/src/redux/reducers/proPlanReducer.ts
 */
'use strict';

const path = require('path');
const { resolveHarnessEnv } = require('./lib/env');

// STEP 01: 組出兩邊 reducer 的絕對路徑，REPO_DIR 必填性已由 resolveHarnessEnv 驗證
const { react15Dir, react18Dir } = resolveHarnessEnv();
const R15_REDUCER_PATH = path.join(react15Dir, 'reducers', 'proPlanReducer.js');
const R18_REDUCER_PATH = path.join(react18Dir, 'src', 'redux', 'reducers', 'proPlanReducer.ts');

describe('smoke: react_15 proPlanReducer 可載入', () => {
  // require 本身就是第一層斷言——babel 轉譯失敗（例如 stage-0 語法沒對到 plugin）
  // 會讓這行直接拋錯，測試變紅，不會偷偷跑到後面才發現載入失敗
  const r15Reducer = require(R15_REDUCER_PATH).default;

  it('對未知 action 回傳跟 initial state 同形狀的物件', () => {
    const result = r15Reducer(undefined, { type: '__UNKNOWN_ACTION_TYPE__' });
    expect(result).toEqual({
      plan: {},
      version: '',
      list: [],
      planForms: {},
      fail: null,
      record: {},
      recordList: [],
    });
  });
});

describe('smoke: react_18 proPlanReducer 可載入', () => {
  const r18Reducer = require(R18_REDUCER_PATH).default;

  it('對未知 action 回傳跟 initial state 同形狀的物件', () => {
    const result = r18Reducer(undefined, { type: '__UNKNOWN_ACTION_TYPE__' });
    expect(result).toEqual({
      plan: {},
      version: '1.00',
      list: [],
      planForms: {},
      fail: null,
      overviewList: [],
    });
  });
});

describe('smoke: trivial 深相等斷言', () => {
  it('物件深相等但參考不同時仍判斷相等（證明 toEqual 真的在比對內容而非參考）', () => {
    const a = { nested: { x: 1, y: [1, 2, 3] } };
    const b = { nested: { x: 1, y: [1, 2, 3] } };
    expect(a).not.toBe(b);
    expect(a).toEqual(b);
  });
});
