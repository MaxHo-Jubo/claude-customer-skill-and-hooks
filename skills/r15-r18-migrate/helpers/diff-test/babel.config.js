/**
 * 差異測試 harness 的共用 babel 設定。
 * 用 overrides 依檔案路徑分流：react_15 走「babel6 stage-0 語法」對應的 babel7 plugin 組合，
 * react_18 走該樹既有 webpack babel-loader 用的 preset 組合（對照 react_18/webpack.config.js
 * 的 babel-loader options）。只收斂「reducer / action creator / util」這類不 import React 的
 * 純邏輯模組需要的語法特性；若要對跑會 import React 的檔案，需自行擴充本檔（見 README 已知限制）。
 *
 * 所有 preset/plugin 套件都從 react_18/node_modules 解析，即使是套給 react_15 檔案用的組合也一樣——
 * react_15/node_modules 只裝了 babel 6 系列套件（babel-core、babel-preset-es2015...），
 * API 不相容 babel 7，不能拿來當 babel 7 的 preset/plugin 用。react_15 override 只是
 * 「babel 6 stage-0 語法該套用哪組 babel 7 preset/plugin」的對應表，套件本體仍來自 react_18 樹
 * 既有安裝（react_18 的 devDependencies 剛好也裝了 @babel/preset-stage-0 系列的個別 proposal
 * 套件，版本 7.x，可以直接借來用，不需要另外安裝）。
 */
'use strict';

const { resolveHarnessEnv, resolvePackageFrom } = require('./lib/env');

const { react18NodeModules } = resolveHarnessEnv();

/**
 * 從 react_18 既有安裝解析一個 babel preset/plugin 套件的絕對路徑。
 * @param {string} packageName - 套件名稱
 * @returns {string} 絕對路徑
 */
function resolveBabelPackage(packageName) {
  return resolvePackageFrom(react18NodeModules, packageName);
}

// STEP 01: react_15 專屬語法特性——實際在 <REPO_DIR>/frontend/react_15 grep 過，且落在
//   reducer/action creator/util 範圍內的 stage-0 語法只有以下兩類：
//   (a) object rest/spread（reducers/proPlanReducer.js:34 起大量出現、actions/gCodeStatAction.js:107
//       `const { caseType = ..., ..._data } = data;`）——這已是 ES2018 標準語法，
//       @babel/preset-env 對 node 現行版本目標原生支援，不需要額外 plugin
//   (b) class properties（utils/crossTabMessageUtil.js:63 `canBeUsed = () => { ... }`，
//       定義在 `export class LocalStorageMessager` 內）——babel6 stage-0 涵蓋，
//       babel7 對應 @babel/plugin-proposal-class-properties
//   decorators／export extensions／function bind／exponentiation 等其他 stage-0 語法
//   在這個範圍內沒有 grep 到使用（decorator 的唯一命中是 components/marquee/style.scss 裡的
//   `@` CSS 語法，不是程式碼，非誤報排除），故不預先加對應 plugin；之後若對跑到用了這些語法的
//   檔案，需自行擴充並在這裡補上新的 grep 證據
const REACT15_PLUGINS = [
  resolveBabelPackage('@babel/plugin-proposal-class-properties'),
];

// STEP 02: 兩邊都用 @babel/preset-env 處理 ES2015+ 語法，targets 固定為 node 現行版本
//   （這裡是 jest 在 node 裡跑，不是瀏覽器，不需要照搬 webpack 設定給瀏覽器用的 targets）；
//   modules 明確指定 'commonjs'，不依賴 babel-jest 的 caller.supportsStaticESM 自動偵測，
//   避免不同 babel-jest 版本的 caller 偵測行為差異造成 import/export 轉譯不穩定
const PRESET_ENV_OPTIONS = { targets: { node: 'current' }, modules: 'commonjs' };

module.exports = {
  overrides: [
    {
      // react_15 檔案：preset-env + class-properties plugin
      test: /[\\/]react_15[\\/]/,
      presets: [[resolveBabelPackage('@babel/preset-env'), PRESET_ENV_OPTIONS]],
      plugins: REACT15_PLUGINS,
    },
    {
      // react_18 檔案：對照 react_18/webpack.config.js 的 babel-loader options，
      //   額外加 preset-typescript（.ts 檔）與 preset-react（保留 JSX 支援彈性，
      //   即使目前 reducer/action creator/util 範圍內未用到 JSX）
      test: /[\\/]react_18[\\/]/,
      presets: [
        [resolveBabelPackage('@babel/preset-env'), PRESET_ENV_OPTIONS],
        resolveBabelPackage('@babel/preset-typescript'),
        resolveBabelPackage('@babel/preset-react'),
      ],
    },
  ],
};
