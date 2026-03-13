#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

/**
 * 從 spec/*.md 的「相關檔案」表中提取檔案路徑，生成 spec/file-mapping.json。
 *
 * 用法: node generate-spec-mapping.cjs [project-root]
 * 若未提供 project-root，使用目前工作目錄。
 *
 * 映射表格式:
 * {
 *   "app/login/LoginPage.js": ["spec/login-flow.md"],
 *   "app/login/*": ["spec/login-flow.md"],
 *   ...
 * }
 */

const projectRoot = process.argv[2] || process.cwd();
const specDir = path.join(projectRoot, 'spec');

if (!fs.existsSync(specDir)) {
  console.error(`spec/ 目錄不存在: ${specDir}`);
  process.exit(1);
}

const specFiles = fs.readdirSync(specDir)
  .filter(f => f.endsWith('.md') && f !== 'index.md');

if (specFiles.length === 0) {
  console.error('spec/ 目錄中沒有找到 markdown 檔案');
  process.exit(1);
}

/**
 * 正規化路徑：若路徑缺少 app/ 前綴但檔案實際存在於 app/ 下，自動補上。
 *
 * @param {string} filePath - 原始路徑（如 sync/SyncManager.js）
 * @returns {string} 正規化後的路徑（如 app/sync/SyncManager.js）
 */
function normalizePath(filePath) {
  if (filePath.startsWith('app/')) {
    return filePath;
  }

  // STEP 01: 嘗試在檔案系統上找到對應路徑
  const withAppPrefix = `app/${filePath}`;
  if (fs.existsSync(path.join(projectRoot, withAppPrefix))) {
    return withAppPrefix;
  }

  // STEP 02: 原始路徑也不存在就回傳原值（可能是舊檔案或已刪除）
  return filePath;
}

/**
 * 從 spec markdown 檔案中提取相關的源碼檔案路徑。
 *
 * 解析策略:
 * 1. 找「相關檔案」或「總覽」section 的 markdown table
 * 2. 提取 backtick 包裹、含 / 路徑、以 .js/.jsx/.ts/.tsx 結尾的字串
 * 3. 若第一步沒結果，掃描全文的 backtick 路徑作為 fallback
 * 4. 所有路徑都經過 normalizePath 正規化
 *
 * @param {string} specFilePath - spec 檔案完整路徑
 * @returns {string[]} 提取到的源碼檔案路徑陣列
 */
function extractFilePaths(specFilePath) {
  const content = fs.readFileSync(specFilePath, 'utf8');
  const paths = new Set();
  const lines = content.split('\n');

  // STEP 01: 從含「檔案」或「總覽」的 section heading 下方 table 提取
  // 支援三種格式:
  //   A) 完整路徑: | UI | `app/login/LoginPage.js` | ... |
  //   B) 目錄+裸檔名: | LoginPage.js | `app/login/` | ... |
  //   C) 目錄在 heading: ### Constants (`shared/constants/`) + 裸檔名 table
  const SECTION_HEADING_RE = /^#+\s*.*(?:檔案|總覽)/;
  let inTableSection = false;
  let tableStarted = false;
  /** 進入 section 時的 heading 層級 (# 的數量) */
  let sectionLevel = 0;
  /** Format C: 從子標題提取的目錄前綴 */
  let headingDir = '';

  for (const line of lines) {
    const headingMatch = line.match(/^(#+)\s/);
    const currentLevel = headingMatch ? headingMatch[1].length : 0;

    // STEP 01.01: 偵測 section 標題（含「檔案」或「總覽」字樣）
    if (SECTION_HEADING_RE.test(line)) {
      inTableSection = true;
      tableStarted = false;
      sectionLevel = currentLevel;

      // STEP 01.01.01: Format C — 從 heading 中提取 backtick 目錄
      //   例: ### Constants (`shared/constants/`)
      const dirInHeading = line.match(/`([^`]+\/)`/);
      headingDir = dirInHeading ? dirInHeading[1] : '';
      continue;
    }

    if (inTableSection) {
      // STEP 01.02: heading 層級處理
      if (currentLevel > 0) {
        if (currentLevel <= sectionLevel) {
          // STEP 01.02.01: 同層或更高層的 heading → 結束 section
          inTableSection = false;
          headingDir = '';
          continue;
        }
        // STEP 01.02.02: 子標題 → 更新 headingDir，重置 table 狀態
        const dirInHeading = line.match(/`([^`]+\/)`/);
        headingDir = dirInHeading ? dirInHeading[1] : headingDir;
        tableStarted = false;
        continue;
      }

      // STEP 01.03: 偵測 table row
      if (line.includes('|')) {
        tableStarted = true;
        const backtickMatches = line.match(/`([^`]+)`/g);

        if (backtickMatches) {
          for (const match of backtickMatches) {
            const filePath = match.replace(/`/g, '');
            // STEP 01.03.01: Format A — 完整路徑
            //   例: `app/login/LoginPage.js`
            if (filePath.match(/\.(js|jsx|ts|tsx)$/) && filePath.includes('/')) {
              paths.add(normalizePath(filePath));
            }
            // STEP 01.03.02: Format B — backtick 是目錄，裸檔名在同行其他欄位
            //   例: | LoginPage.js | `app/login/` | ...
            if (filePath.endsWith('/')) {
              const cells = line.split('|').map(c => c.trim());
              for (const cell of cells) {
                const bareFile = cell.match(/^(\S+\.(js|jsx|ts|tsx))(\s|$)/);
                if (bareFile) {
                  paths.add(normalizePath(filePath + bareFile[1]));
                }
              }
            }
          }
        }

        // STEP 01.03.03: Format C — 沒有 backtick 目錄但有 heading 目錄
        //   例: heading = `shared/constants/`, row = | index.js | ~728 | ... |
        if (headingDir && (!backtickMatches || !backtickMatches.some(m => m.includes('/')))) {
          const cells = line.split('|').map(c => c.trim());
          for (const cell of cells) {
            const bareFile = cell.match(/^(\S+\.(js|jsx|ts|tsx))(\s|$)/);
            if (bareFile) {
              paths.add(normalizePath(headingDir + bareFile[1]));
            }
          }
        }
      }

      // STEP 01.04: table 結束（非空行且不是 table 內容）
      if (tableStarted && !line.includes('|') && line.trim() !== '' && !line.startsWith('|')) {
        if (line.startsWith('---') || line.startsWith('**')) {
          inTableSection = false;
          headingDir = '';
        }
      }
    }
  }

  // STEP 02: Fallback — 若 table 沒找到路徑，掃描全文
  if (paths.size === 0) {
    const allMatches = content.match(/`(app\/[^`]+\.(js|jsx|ts|tsx))`/g);
    if (allMatches) {
      for (const match of allMatches) {
        paths.add(normalizePath(match.replace(/`/g, '')));
      }
    }
  }

  return [...paths];
}

// STEP 03: 建立 source file → spec files 的映射
const mapping = {};

for (const specFile of specFiles) {
  const specPath = `spec/${specFile}`;
  const fullPath = path.join(specDir, specFile);
  const filePaths = extractFilePaths(fullPath);

  for (const filePath of filePaths) {
    if (!mapping[filePath]) {
      mapping[filePath] = [];
    }
    if (!mapping[filePath].includes(specPath)) {
      mapping[filePath].push(specPath);
    }
  }
}

// STEP 04: 補充特殊 spec 的映射（table 格式不含完整路徑的）
// realm-schema.md 的 table 只有裸檔名，需要用目錄掃描方式補映射
const SPECIAL_DIR_MAPPINGS = {
  'spec/realm-schema.md': ['app/db/schema', 'app/db/manager'],
};

for (const [specPath, dirs] of Object.entries(SPECIAL_DIR_MAPPINGS)) {
  if (!specFiles.includes(specPath.replace('spec/', ''))) {
    continue;
  }
  for (const dir of dirs) {
    const fullDir = path.join(projectRoot, dir);
    if (!fs.existsSync(fullDir)) {
      continue;
    }
    const files = fs.readdirSync(fullDir)
      .filter(f => f.match(/\.(js|jsx|ts|tsx)$/));
    for (const file of files) {
      const filePath = `${dir}/${file}`;
      if (!mapping[filePath]) {
        mapping[filePath] = [];
      }
      if (!mapping[filePath].includes(specPath)) {
        mapping[filePath].push(specPath);
      }
    }
  }
}

// STEP 06: 加入目錄層級映射
// 從已知的檔案路徑推導出目錄 → spec 的對應關係
const dirToSpecs = {};
for (const [file, specs] of Object.entries(mapping)) {
  const dir = path.dirname(file);
  if (!dirToSpecs[dir]) {
    dirToSpecs[dir] = new Set();
  }
  for (const spec of specs) {
    dirToSpecs[dir].add(spec);
  }
}

for (const [dir, specs] of Object.entries(dirToSpecs)) {
  const dirKey = `${dir}/*`;
  mapping[dirKey] = [...specs];
}

// STEP 07: 排序 key 並輸出
const sortedMapping = {};
for (const key of Object.keys(mapping).sort()) {
  sortedMapping[key] = mapping[key];
}

const outputPath = path.join(specDir, 'file-mapping.json');
fs.writeFileSync(outputPath, JSON.stringify(sortedMapping, null, 2) + '\n');

// STEP 08: 輸出摘要
const fileCount = Object.keys(sortedMapping).filter(k => !k.endsWith('/*')).length;
const dirCount = Object.keys(sortedMapping).filter(k => k.endsWith('/*')).length;

console.log(`映射表已生成: ${outputPath}`);
console.log(`  ${fileCount} 個檔案 + ${dirCount} 個目錄 -> ${specFiles.length} 份 spec`);

// STEP 09: 警告沒有匹配到檔案的 spec
const mappedSpecs = new Set(Object.values(sortedMapping).flat());
const unmappedSpecs = specFiles
  .map(f => `spec/${f}`)
  .filter(s => !mappedSpecs.has(s));

if (unmappedSpecs.length > 0) {
  console.log(`\n以下 spec 沒有匹配到任何檔案 (可能需要手動補充映射):`);
  for (const s of unmappedSpecs) {
    console.log(`  - ${s}`);
  }
}
