/**
 * post-commit eslint 的執行目標規劃。
 *
 * 背景：多數 repo 的 eslint 設定與 node_modules 不在 git 根目錄，而在子資料夾
 * （web 專案的 frontend/react_18、App 專案的 HomeCareStaffRN 等）。
 * 舊版一律在 repo 根目錄跑 `npx eslint`，根目錄沒有本機 eslint 時 npx 會去下載另一個版本
 * （實測抓到 ESLint 10.x）並以 exit 2 結束，被當成「環境問題」跳過——lint 從沒真的跑過
 * （2026-10 週檢討 3 個 session 重現；同檔案在子資料夾以本機 eslint 8 執行則 exit 1 抓到真問題）。
 *
 * 規劃方式：每個變更檔往上找最近含 eslint 設定檔的資料夾，再從該資料夾往上找本機
 * node_modules/.bin/eslint；同一資料夾的檔案併成一組、路徑改成相對於該資料夾。
 * 找不到設定檔或本機執行檔時如實回報，不退回 npx（避免下載錯版本、也避免把 exit 1 的語意搞混）。
 */
import { existsSync } from 'fs';
import { dirname, join, relative } from 'path';

/** eslint 設定檔名單：舊式 eslintrc 與 flat config 兩種格式 */
const ESLINT_CONFIG_NAMES = [
  '.eslintrc',
  '.eslintrc.js',
  '.eslintrc.cjs',
  '.eslintrc.json',
  '.eslintrc.yml',
  '.eslintrc.yaml',
  'eslint.config.js',
  'eslint.config.mjs',
  'eslint.config.cjs',
  'eslint.config.ts',
];

/** 一組要一起執行 eslint 的檔案（同一個設定檔資料夾） */
export interface EslintGroup {
  /** 設定檔所在資料夾絕對路徑，也是執行 eslint 的 cwd */
  dir: string;
  /** 本機 eslint 執行檔絕對路徑；從 dir 往上到 repo 根目錄都找不到時為 null */
  bin: string | null;
  /** 相對於 dir 的檔案路徑 */
  files: string[];
}

/** 一次 commit 的 eslint 執行規劃 */
export interface EslintPlan {
  /** 依設定檔資料夾分組的執行目標 */
  groups: EslintGroup[];
  /** 往上找不到任何 eslint 設定檔的檔案（相對於 repo 根目錄） */
  unconfigured: string[];
}

/**
 * 從 startDir 往上走到 repoRoot（含），回傳第一個讓 probe 回傳非 null 的結果。
 * @param startDir 起點資料夾絕對路徑（須在 repoRoot 之內）
 * @param repoRoot 搜尋上界（含）
 * @param probe 對每個資料夾回傳找到的值，沒有則回 null
 * @returns 第一個命中的值；走到上界都沒有為 null
 */
function findUp<T>(startDir: string, repoRoot: string, probe: (dir: string) => T | null): T | null {
  /** 目前檢查的資料夾 */
  let dir = startDir;
  while (true) {
    /** 本層探測結果 */
    const found = probe(dir);
    if (found !== null) {
      return found;
    }
    /** 上一層資料夾 */
    const parent = dirname(dir);
    if (dir === repoRoot || parent === dir) {
      return null;
    }
    dir = parent;
  }
}

/**
 * 依 eslint 設定檔位置，把本次 commit 的變更檔規劃成多組執行目標。
 * 已不存在的檔案（commit 刪除的檔案）直接略過：eslint 對不存在的路徑會以 exit 2 結束，
 * 那是被刪除而非環境問題，不應列入也不應拖累同組其他檔案。
 * @param repoRoot git repo 根目錄絕對路徑
 * @param changedFiles 相對於 repoRoot 的變更檔路徑
 * @returns 分組後的執行規劃
 */
export function planEslintRuns(repoRoot: string, changedFiles: string[]): EslintPlan {
  /** 設定檔資料夾 → 該組（用 Map 保持首次出現順序，輸出穩定） */
  const byDir = new Map<string, EslintGroup>();
  /** 找不到設定檔的檔案 */
  const unconfigured: string[] = [];

  for (const rel of changedFiles) {
    // STEP 01: 略過已刪除的檔案
    /** 檔案絕對路徑 */
    const abs = join(repoRoot, rel);
    if (!existsSync(abs)) {
      continue;
    }

    // STEP 02: 往上找最近的 eslint 設定檔資料夾
    /** 最近含 eslint 設定檔的資料夾 */
    const cfgDir = findUp(dirname(abs), repoRoot, (d) =>
      ESLINT_CONFIG_NAMES.some((n) => existsSync(join(d, n))) ? d : null);
    if (cfgDir === null) {
      unconfigured.push(rel);
      continue;
    }

    // STEP 03: 併入該資料夾的組；第一次遇到才去找本機 eslint 執行檔
    /** 既有的組；尚未建立為 undefined */
    let group = byDir.get(cfgDir);
    if (!group) {
      group = {
        dir: cfgDir,
        bin: findUp(cfgDir, repoRoot, (d) => {
          /** 候選的本機 eslint 執行檔 */
          const bin = join(d, 'node_modules', '.bin', 'eslint');
          return existsSync(bin) ? bin : null;
        }),
        files: [],
      };
      byDir.set(cfgDir, group);
    }
    group.files.push(relative(cfgDir, abs));
  }

  return { groups: [...byDir.values()], unconfigured };
}
