import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { dirname, join } from 'path';
import { planEslintRuns } from './eslint-targets';

/** 每個案例獨立的臨時目錄；repo 放在其下的 repo/ 子資料夾，好測「不越過 repo 根目錄往上找」 */
let outer = '';
/** 受測的 git repo 根目錄（臨時，不需真的 git init） */
let repo = '';

/**
 * 建立空檔案（含上層資料夾）；內容無關緊要。
 * @param parts 路徑片段，以 join 組成絕對路徑
 * @returns 建立的檔案絕對路徑
 */
const touch = (...parts: string[]): string => {
  /** 檔案絕對路徑 */
  const p = join(...parts);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, '');
  return p;
};

beforeEach(() => {
  outer = mkdtempSync(join(tmpdir(), 'eslint-targets-'));
  repo = join(outer, 'repo');
  mkdirSync(repo, { recursive: true });
});

afterEach(() => {
  rmSync(outer, { recursive: true, force: true });
});

describe('planEslintRuns', () => {
  test('設定檔與本機 eslint 在子資料夾：分成一組，路徑改為相對於該資料夾', () => {
    touch(repo, 'frontend/react_18/.eslintrc.js');
    const bin = touch(repo, 'frontend/react_18/node_modules/.bin/eslint');
    touch(repo, 'frontend/react_18/src/a.ts');
    touch(repo, 'frontend/react_18/src/b.tsx');

    const plan = planEslintRuns(repo, ['frontend/react_18/src/a.ts', 'frontend/react_18/src/b.tsx']);

    expect(plan.unconfigured).toEqual([]);
    expect(plan.groups).toEqual([{ dir: join(repo, 'frontend/react_18'), bin, files: ['src/a.ts', 'src/b.tsx'] }]);
  });

  test('兩個不同設定資料夾 → 兩組，檔案各歸各組', () => {
    touch(repo, 'backend/.eslintrc.json');
    touch(repo, 'frontend/react_18/.eslintrc.js');
    touch(repo, 'backend/x.js');
    touch(repo, 'frontend/react_18/y.js');

    const plan = planEslintRuns(repo, ['backend/x.js', 'frontend/react_18/y.js']);

    expect(plan.groups.map((g) => [g.dir.replace(repo + '/', ''), g.files])).toEqual([
      ['backend', ['x.js']],
      ['frontend/react_18', ['y.js']],
    ]);
  });

  test('巢狀設定檔：最近的設定檔優先', () => {
    touch(repo, 'app/.eslintrc.js');
    touch(repo, 'app/legacy/.eslintrc.json');
    touch(repo, 'app/legacy/old.js');
    touch(repo, 'app/new.js');

    const plan = planEslintRuns(repo, ['app/legacy/old.js', 'app/new.js']);

    expect(plan.groups.map((g) => [g.dir.replace(repo + '/', ''), g.files])).toEqual([
      ['app/legacy', ['old.js']],
      ['app', ['new.js']],
    ]);
  });

  test('flat config（eslint.config.*）也算設定檔', () => {
    touch(repo, 'pkg/eslint.config.mjs');
    touch(repo, 'pkg/a.js');
    expect(planEslintRuns(repo, ['pkg/a.js']).groups).toHaveLength(1);
  });

  test('往上找不到任何設定檔 → 列入 unconfigured', () => {
    touch(repo, 'src/a.js');
    expect(planEslintRuns(repo, ['src/a.js'])).toEqual({ groups: [], unconfigured: ['src/a.js'] });
  });

  test('有設定檔但整條路徑上都沒有本機 eslint → bin 為 null（不退回 npx）', () => {
    touch(repo, 'pkg/.eslintrc.js');
    touch(repo, 'pkg/a.js');
    expect(planEslintRuns(repo, ['pkg/a.js']).groups[0].bin).toBeNull();
  });

  test('eslint 裝在上層（hoisted）：從設定檔資料夾往上找得到', () => {
    touch(repo, 'pkg/.eslintrc.js');
    touch(repo, 'pkg/a.js');
    const bin = touch(repo, 'node_modules/.bin/eslint');
    expect(planEslintRuns(repo, ['pkg/a.js']).groups[0].bin).toBe(bin);
  });

  test('搜尋不越過 repo 根目錄：上層資料夾的設定檔與 eslint 不算', () => {
    touch(outer, '.eslintrc.js');
    touch(outer, 'node_modules/.bin/eslint');
    touch(repo, 'src/a.js');
    expect(planEslintRuns(repo, ['src/a.js'])).toEqual({ groups: [], unconfigured: ['src/a.js'] });
  });

  test('已刪除的檔案略過，不拖累同組其他檔、也不列入 unconfigured', () => {
    touch(repo, 'pkg/.eslintrc.js');
    touch(repo, 'pkg/keep.js');

    const plan = planEslintRuns(repo, ['pkg/gone.js', 'pkg/keep.js']);
    expect(plan.groups[0].files).toEqual(['keep.js']);
    expect(plan.unconfigured).toEqual([]);

    expect(planEslintRuns(repo, ['pkg/gone.js'])).toEqual({ groups: [], unconfigured: [] });
  });

  test('設定寫在 package.json 的 eslintConfig：視為設定檔資料夾，成一組', () => {
    writeFileSync(join(repo, 'package.json'), JSON.stringify({ name: 'x', eslintConfig: { root: true } }));
    const bin = touch(repo, 'node_modules/.bin/eslint');
    touch(repo, 'src/a.js');

    const plan = planEslintRuns(repo, ['src/a.js']);

    expect(plan.unconfigured).toEqual([]);
    expect(plan.groups).toEqual([{ dir: repo, bin, files: ['src/a.js'] }]);
  });

  test('package.json 沒有 eslintConfig → 不算設定，繼續往上找；找不到則列為 unconfigured', () => {
    // STEP 01: 子資料夾的 package.json 只有一般欄位，上層才有真正的設定
    touch(repo, '.eslintrc.json');
    mkdirSync(join(repo, 'pkg'), { recursive: true });
    writeFileSync(join(repo, 'pkg/package.json'), JSON.stringify({ name: 'pkg', scripts: {} }));
    touch(repo, 'pkg/a.js');
    expect(planEslintRuns(repo, ['pkg/a.js']).groups.map((g) => g.dir)).toEqual([repo]);

    // STEP 02: 整個 repo 都沒有設定 → unconfigured
    rmSync(join(repo, '.eslintrc.json'));
    expect(planEslintRuns(repo, ['pkg/a.js'])).toEqual({ groups: [], unconfigured: ['pkg/a.js'] });
  });

  test('eslintConfig 不是物件（null、字串）或 package.json 壞掉 → 不算設定，也不拋錯', () => {
    touch(repo, 'a.js');
    for (const body of [JSON.stringify({ eslintConfig: null }), JSON.stringify({ eslintConfig: 'strict' }), '{ not json', 'null']) {
      writeFileSync(join(repo, 'package.json'), body);
      expect(planEslintRuns(repo, ['a.js'])).toEqual({ groups: [], unconfigured: ['a.js'] });
    }
  });

  test('獨立設定檔與 package.json eslintConfig 並存 → 仍是同一組（不重複分組）', () => {
    touch(repo, 'app/.eslintrc.json');
    writeFileSync(join(repo, 'app/package.json'), JSON.stringify({ eslintConfig: {} }));
    touch(repo, 'app/a.js');
    touch(repo, 'app/b.js');
    expect(planEslintRuns(repo, ['app/a.js', 'app/b.js']).groups).toHaveLength(1);
  });
});
