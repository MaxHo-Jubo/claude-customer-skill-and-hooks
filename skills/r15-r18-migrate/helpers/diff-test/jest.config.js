/**
 * R15/R18 差異測試 harness 的 jest 設定。
 * 讓 react_15（babel 6 語法）與 react_18（TypeScript/babel 7 語法）的 reducer、action creator、
 * util 這類不 import React 的純邏輯模組能在同一個 jest process 內載入並對跑深相等。
 * 詳細限制（例如不支援會 import React 的檔案、兩個 react 版本同 process 衝突）見同目錄 README.md。
 *
 * 使用方式：
 *   REPO_DIR=<目標 repo 根目錄> DIFF_TEST_DIR=<測試檔目錄> \
 *     <REPO_DIR>/frontend/react_18/node_modules/.bin/jest --config <本檔絕對路徑>
 */
'use strict';

const path = require('path');
const { resolveHarnessEnv, resolvePackageFrom } = require('./lib/env');

// STEP 01: 解析 REPO_DIR 底下兩棵前端樹的 node_modules 與差異測試檔目錄
const { react15NodeModules, react18NodeModules, diffTestDir } = resolveHarnessEnv();

// STEP 02: babel-jest 本身也要從 react_18 既有安裝解析——harness 目錄故意不放 node_modules（見 README）
const BABEL_JEST_PATH = resolvePackageFrom(react18NodeModules, 'babel-jest');

module.exports = {
  // 設成 harness 自己的目錄，而不是 REPO_DIR——rootDir 只用來解析本檔內其他選項裡的
  // <rootDir> token（moduleNameMapper 的 mock 檔路徑），跟「去哪裡找測試檔/原始碼」無關，
  // 那兩件事分別由下面的 roots 與各檔案自己的 require 路徑決定
  rootDir: __dirname,
  // 測試檔搜尋目錄：預設吃 DIFF_TEST_DIR（未設定則落在 MIGRATION_STATE_DIR/diff-tests 底下，
  // 見 lib/env.js）。smoke 測試時把 DIFF_TEST_DIR 指到本目錄自己，才會抓到 smoke.test.js
  roots: [diffTestDir],
  testMatch: ['**/*.test.js'],
  testEnvironment: 'node',
  // react_15 檔案的相對 import（例如 reducer import 同樹的 action 常數檔）本來就會透過 Node
  // 預設向上尋找 node_modules 命中自己樹的 node_modules，不需要 moduleDirectories 介入；
  // 這裡兩棵樹都放進去是保險機制，涵蓋「測試檔本身要 require 一個 bare package 名稱」這種
  // 不會發生在對跑目標檔案內、但產生器產出的 CASES 可能用到的情境
  moduleDirectories: [react18NodeModules, react15NodeModules, 'node_modules'],
  transform: {
    '^.+\\.(js|jsx|ts|tsx)$': [BABEL_JEST_PATH, { configFile: path.join(__dirname, 'babel.config.js') }],
  },
  // css/scss/圖片等非 JS 資源 import 一律 stub 掉，避免 jest 嘗試解析而炸掉；
  // 差異測試只在意 reducer/action creator/util 的邏輯輸出，不在意資源實際內容
  moduleNameMapper: {
    '\\.(css|scss|less)$': path.join(__dirname, 'mocks', 'styleMock.js'),
    '\\.(png|jpe?g|gif|svg|eot|ttf|woff2?)$': path.join(__dirname, 'mocks', 'fileMock.js'),
  },
  moduleFileExtensions: ['js', 'jsx', 'ts', 'tsx', 'json'],
  verbose: true,
};
