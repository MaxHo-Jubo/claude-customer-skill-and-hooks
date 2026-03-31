#!/usr/bin/env bun
import fs from 'fs';
import path from 'path';

/**
 * 從 spec/**\/*.md 提取檔案路徑，生成 spec/file-mapping.json。
 *
 * 用法: bun generate-spec-mapping.ts [project-root]
 * 若未提供 project-root，使用目前工作目錄。
 *
 * 支援的路徑格式：
 * - 前端：`app/login/LoginPage.js`
 * - 後端：`backend/models/caseModel.js`
 * - 標頭：`> 原始碼：\`backend/models/xxx.js\``
 * - 標頭：`> 路徑：\`backend/services/xxx.js\``
 *
 * 映射表格式:
 * {
 *   "app/login/LoginPage.js": ["spec/login-flow.md"],
 *   "models/caseModel.js": ["spec/models/caseModel.md"],
 *   ...
 * }
 */

/** 專案根目錄 */
const projectRoot = process.argv[2] || process.cwd();
/** spec 目錄路徑 */
const specDir = path.join(projectRoot, 'spec');

if (!fs.existsSync(specDir)) {
  console.error(`spec/ 目錄不存在: ${specDir}`);
  process.exit(1);
}

/**
 * 遞迴掃描目錄，回傳所有 .md 檔案的相對路徑（相對於 specDir）。
 * 排除 index.md。
 *
 * @param dir - 要掃描的目錄
 * @param prefix - 目前的路徑前綴（遞迴用）
 * @returns 相對路徑陣列，如 ['config.md', 'models/base.md']
 */
function scanSpecFiles(dir: string, prefix = ''): string[] {
  // STEP 01: 讀取目錄內容
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  /** 收集到的 spec 檔案路徑 */
  const results: string[] = [];

  for (const entry of entries) {
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;

    if (entry.isDirectory()) {
      // STEP 01.01: 遞迴掃描子目錄
      results.push(...scanSpecFiles(path.join(dir, entry.name), relativePath));
    } else if (entry.isFile() && entry.name.endsWith('.md') && entry.name !== 'index.md') {
      // STEP 01.02: 收集非 index 的 markdown 檔
      results.push(relativePath);
    }
  }

  return results;
}

/** 所有 spec 檔案相對路徑 */
const specFiles = scanSpecFiles(specDir);

if (specFiles.length === 0) {
  console.error('spec/ 目錄中沒有找到 markdown 檔案');
  process.exit(1);
}

/**
 * 偵測專案類型，決定路徑前綴。
 * 前端專案：路徑以 app/ 開頭
 * 後端專案：路徑以 backend/ 開頭，映射時去掉 backend/ 前綴
 *
 * @returns 專案類型
 */
function detectProjectType(): 'frontend' | 'backend' {
  // STEP 01: 檢查目錄結構判斷專案類型
  if (fs.existsSync(path.join(projectRoot, 'app'))) {
    return 'frontend';
  }
  if (fs.existsSync(path.join(projectRoot, 'models')) || fs.existsSync(path.join(projectRoot, 'controllers'))) {
    return 'backend';
  }
  return 'frontend';
}

/** 專案類型 */
const projectType = detectProjectType();

/**
 * 正規化路徑：
 * - 前端：若缺少 app/ 前綴但檔案存在於 app/ 下，自動補上
 * - 後端：去掉 backend/ 前綴（因為 projectRoot 已經是 backend/）
 *
 * @param filePath - 原始路徑
 * @returns 正規化後的路徑
 */
function normalizePath(filePath: string): string {
  if (projectType === 'backend') {
    // STEP 01: 後端路徑去掉 backend/ 前綴
    return filePath.replace(/^backend\//, '');
  }

  // STEP 02: 前端路徑嘗試補 app/ 前綴
  if (filePath.startsWith('app/')) {
    return filePath;
  }
  const withAppPrefix = `app/${filePath}`;
  if (fs.existsSync(path.join(projectRoot, withAppPrefix))) {
    return withAppPrefix;
  }
  return filePath;
}

/**
 * 從 spec markdown 的標頭行（blockquote）提取源碼路徑。
 * 支援格式：
 *   > 原始碼：`backend/models/caseModel.js`（1,024 行）
 *   > 路徑：`backend/services/Account.js`
 *   > 掃描路徑：`backend/models/`
 *
 * @param lines - 檔案各行
 * @returns files: 檔案路徑, dirs: 目錄路徑
 */
function extractHeaderPaths(lines: string[]): { files: string[]; dirs: string[] } {
  /** 從標頭提取的檔案路徑 */
  const files: string[] = [];
  /** 從標頭提取的目錄路徑 */
  const dirs: string[] = [];

  for (const line of lines) {
    // STEP 01: 只處理 blockquote 行
    if (!line.startsWith('>')) {
      // STEP 01.01: 遇到非 blockquote 行就停止（標頭結束）
      if (line.trim() !== '' && !line.startsWith('#')) {
        break;
      }
      continue;
    }

    // STEP 02: 提取 backtick 中的路徑
    const backtickMatches = line.match(/`([^`]+)`/g);
    if (!backtickMatches) {
      continue;
    }

    for (const match of backtickMatches) {
      const filePath = match.replace(/`/g, '');

      // STEP 02.01: 完整檔案路徑（含副檔名）
      if (filePath.match(/\.(js|jsx|ts|tsx)$/) && filePath.includes('/')) {
        files.push(filePath);
      }
      // STEP 02.02: 目錄路徑（以 / 結尾）→ 記錄為目錄映射（不遞迴掃描）
      else if (filePath.endsWith('/')) {
        dirs.push(filePath);
      }
    }
  }

  return { files, dirs };
}

/**
 * 從 spec markdown 檔案中提取相關的源碼檔案路徑。
 *
 * 解析策略（依優先序）:
 * 1. 從 blockquote 標頭提取（原始碼/路徑/掃描路徑）
 * 2. 從「檔案」「總覽」section 的 table 提取
 * 3. Fallback：掃描全文 backtick 路徑
 *
 * @param specFilePath - spec 檔案完整路徑
 * @returns 提取到的源碼檔案路徑與目錄
 */
function extractFilePaths(specFilePath: string): { files: string[]; dirs: string[] } {
  const content = fs.readFileSync(specFilePath, 'utf8');
  const paths = new Set<string>();
  const lines = content.split('\n');

  // STEP 01: 從標頭 blockquote 提取
  const header = extractHeaderPaths(lines);
  for (const p of header.files) {
    paths.add(normalizePath(p));
  }
  /** 標頭中聲明的目錄路徑（用於目錄層級映射） */
  const headerDirs = header.dirs;

  // STEP 02: 從含「檔案」或「總覽」的 section heading 下方 table 提取
  const SECTION_HEADING_RE = /^#+\s*.*(?:檔案|總覽)/;
  /** 是否在目標 section 中 */
  let inTableSection = false;
  /** 是否已進入 table */
  let tableStarted = false;
  /** 進入 section 時的 heading 層級 */
  let sectionLevel = 0;
  /** 從子標題提取的目錄前綴 */
  let headingDir = '';

  for (const line of lines) {
    const headingMatch = line.match(/^(#+)\s/);
    const currentLevel = headingMatch ? headingMatch[1].length : 0;

    // STEP 02.01: 偵測 section 標題
    if (SECTION_HEADING_RE.test(line)) {
      inTableSection = true;
      tableStarted = false;
      sectionLevel = currentLevel;
      const dirInHeading = line.match(/`([^`]+\/)`/);
      headingDir = dirInHeading ? dirInHeading[1] : '';
      continue;
    }

    if (inTableSection) {
      // STEP 02.02: heading 層級處理
      if (currentLevel > 0) {
        if (currentLevel <= sectionLevel) {
          inTableSection = false;
          headingDir = '';
          continue;
        }
        const dirInHeading = line.match(/`([^`]+\/)`/);
        headingDir = dirInHeading ? dirInHeading[1] : headingDir;
        tableStarted = false;
        continue;
      }

      // STEP 02.03: table row 處理
      if (line.includes('|')) {
        tableStarted = true;
        const backtickMatches = line.match(/`([^`]+)`/g);

        if (backtickMatches) {
          for (const match of backtickMatches) {
            const filePath = match.replace(/`/g, '');
            // STEP 02.03.01: Format A — 完整路徑
            if (filePath.match(/\.(js|jsx|ts|tsx)$/) && filePath.includes('/')) {
              paths.add(normalizePath(filePath));
            }
            // STEP 02.03.02: Format B — backtick 是目錄，裸檔名在同行
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

        // STEP 02.03.03: Format C — heading 目錄 + 裸檔名
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

      // STEP 02.04: table 結束
      if (tableStarted && !line.includes('|') && line.trim() !== '' && !line.startsWith('|')) {
        if (line.startsWith('---') || line.startsWith('**')) {
          inTableSection = false;
          headingDir = '';
        }
      }
    }
  }

  // STEP 03: Fallback — 若前面都沒找到，掃描全文 backtick 路徑
  if (paths.size === 0 && headerDirs.length === 0) {
    /** 匹配含 / 的 .js/.jsx/.ts/.tsx backtick 路徑 */
    const allMatches = content.match(/`([a-zA-Z][^`]*\/[^`]+\.(js|jsx|ts|tsx))`/g);
    if (allMatches) {
      for (const match of allMatches) {
        paths.add(normalizePath(match.replace(/`/g, '')));
      }
    }
  }

  return { files: [...paths], dirs: headerDirs };
}

// STEP 04: 建立 source file → spec files 的映射
/** 源碼路徑 → spec 路徑陣列 */
const mapping: Record<string, string[]> = {};
/** 標頭目錄 → spec 集合（直接從標頭聲明建立） */
const headerDirToSpecs: Record<string, Set<string>> = {};

for (const specFile of specFiles) {
  const specPath = `spec/${specFile}`;
  const fullPath = path.join(specDir, specFile);
  const { files: filePaths, dirs: dirPaths } = extractFilePaths(fullPath);

  // STEP 04.01: 檔案層級映射
  for (const filePath of filePaths) {
    if (!mapping[filePath]) {
      mapping[filePath] = [];
    }
    if (!mapping[filePath].includes(specPath)) {
      mapping[filePath].push(specPath);
    }
  }

  // STEP 04.02: 標頭目錄映射（`> 原始碼：\`backend/models/\`` 等）
  for (const dirPath of dirPaths) {
    const normalizedDir = normalizePath(dirPath.replace(/\/$/, ''));
    const dirKey = `${normalizedDir}/*`;
    if (!headerDirToSpecs[dirKey]) {
      headerDirToSpecs[dirKey] = new Set();
    }
    headerDirToSpecs[dirKey].add(specPath);
  }
}

// STEP 05: 補充特殊 spec 的映射（table 格式不含完整路徑的）
/** 特殊目錄映射：spec 路徑 → 需掃描的目錄陣列 */
const SPECIAL_DIR_MAPPINGS: Record<string, string[]> = {
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
/** 目錄 → spec 集合 */
const dirToSpecs: Record<string, Set<string>> = {};
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

// STEP 06.02: 合併標頭目錄映射
for (const [dirKey, specs] of Object.entries(headerDirToSpecs)) {
  if (!mapping[dirKey]) {
    mapping[dirKey] = [];
  }
  for (const spec of specs) {
    if (!mapping[dirKey].includes(spec)) {
      mapping[dirKey].push(spec);
    }
  }
}

// STEP 07: 排序 key 並輸出
/** 排序後的映射表 */
const sortedMapping: Record<string, string[]> = {};
for (const key of Object.keys(mapping).sort()) {
  sortedMapping[key] = mapping[key];
}

/** 輸出路徑 */
const outputPath = path.join(specDir, 'file-mapping.json');
fs.writeFileSync(outputPath, JSON.stringify(sortedMapping, null, 2) + '\n');

// STEP 08: 輸出摘要
/** 檔案映射數 */
const fileCount = Object.keys(sortedMapping).filter(k => !k.endsWith('/*')).length;
/** 目錄映射數 */
const dirCount = Object.keys(sortedMapping).filter(k => k.endsWith('/*')).length;

console.log(`映射表已生成: ${outputPath}`);
console.log(`  專案類型: ${projectType}`);
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
