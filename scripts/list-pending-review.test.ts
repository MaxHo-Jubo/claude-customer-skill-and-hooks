import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { spawnSync } from 'child_process';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { readValidMarker } from './lib/review-marker';

/**
 * list-pending-review.ts 的測試：假 HOME 只傳給子行程（MARKER_DIR 由 homedir() 推導）。
 * 重點：(1) 逾期 marker 不顯示但也不能被刪（顯示用讀取不得有副作用）
 * (2) 與閘門判準一致：readValidMarker 判有效的，CLI 一定列在 markers；判無效的不會出現在 markers。
 */

/** CLI 絕對路徑 */
const CLI = join(import.meta.dir, 'list-pending-review.ts');
/** 一小時（毫秒） */
const HOUR_MS = 60 * 60 * 1000;
/** 子行程用的假 HOME */
let home = '';
/** 假 HOME 下的 marker 目錄 */
let dir = '';

/**
 * 執行 CLI。
 * @returns exit code、解析後的 stdout 與 stderr
 */
const run = () => {
  const r = spawnSync('bun', [CLI], { encoding: 'utf8', env: { PATH: process.env.PATH ?? '', HOME: home } });
  return { code: r.status, out: r.stdout.trim() ? JSON.parse(r.stdout) : null, stderr: r.stderr };
};

/**
 * 寫一顆 marker。
 * @param name - 檔名
 * @param body - 內容（物件會轉 JSON，字串原樣寫入）
 */
const marker = (name: string, body: object | string) =>
  writeFileSync(join(dir, name), typeof body === 'string' ? body : JSON.stringify(body));

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), 'list-pr-'));
  dir = join(home, '.claude/state/pending-review');
});

afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

describe('list-pending-review', () => {
  test('marker 目錄不存在：輸出空清單', () => {
    expect(run()).toMatchObject({ code: 0, out: { markers: [], invalid: [] } });
  });

  test('只列未逾期的 marker；舊 marker 缺 engine／expectedAspects 時推導；逾期檔不被刪', () => {
    mkdirSync(dir, { recursive: true });
    /** a.json 的建立時間 */
    const createdAt = Date.now() - 30 * 60000;
    marker('a.json', { repoRoot: '/w/repo-a', commitHash: 'abcdef1234', tier: 3, createdAt, sessionId: 's1', expectedAspects: 6, engine: 'codex' });
    marker('legacy.json', { repoRoot: '/w/repo-b', commitHash: '1234567890', tier: 2, createdAt });
    marker('old.json', { repoRoot: '/w/repo-c', commitHash: 'x', tier: 2, createdAt: Date.now() - 5 * HOUR_MS });
    marker('x.lasthead', 'deadbeef');
    const r = run();
    expect(r.code).toBe(0);
    /** 依檔名排序後的結果，避免依賴 readdir 順序 */
    const ms = [...r.out.markers].sort((p: { file: string }, q: { file: string }) => p.file.localeCompare(q.file));
    expect(ms).toEqual([
      { file: 'a.json', repo: 'repo-a', repoRoot: '/w/repo-a', commit: 'abcdef1', tier: 3, engine: 'codex', expectedAspects: 6, createdAt, sessionId: 's1', missing: [] },
      { file: 'legacy.json', repo: 'repo-b', repoRoot: '/w/repo-b', commit: '1234567', tier: 2, engine: 'agent', expectedAspects: 1, createdAt, sessionId: null, missing: [] },
    ]);
    expect(existsSync(join(dir, 'old.json'))).toBe(true);
  });

  test('格式不完整但未逾期：照樣列出（閘門照樣擋），缺的欄位為 null 並列入 missing；無法解析的列入 invalid', () => {
    mkdirSync(dir, { recursive: true });
    marker('noroot.json', { tier: 2, createdAt: Date.now() });
    marker('strtier.json', { repoRoot: '/w/r', commitHash: 'abc', tier: '3', createdAt: Date.now() });
    marker('bad.json', '{not json');
    marker('null.json', 'null');
    const r = run();
    expect(r.code).toBe(0);
    /** 依檔名索引的 marker */
    const byFile = Object.fromEntries(r.out.markers.map((m: { file: string }) => [m.file, m]));
    expect(byFile['noroot.json']).toMatchObject({ repo: null, commit: null, tier: 2, expectedAspects: 1, missing: ['repoRoot', 'commitHash'] });
    expect(byFile['strtier.json']).toMatchObject({ tier: null, expectedAspects: null, missing: ['tier'] });
    expect([...r.out.invalid].sort()).toEqual(['bad.json', 'null.json']);
  });

  test('與閘門判準一致：readValidMarker 有效 ⇔ 出現在 markers', () => {
    mkdirSync(dir, { recursive: true });
    /** 各種未逾期或缺 createdAt 的 fixture（不放逾期檔：readValidMarker 會刪檔並寫 audit） */
    const fixtures: Record<string, object | string> = {
      'full.json': { repoRoot: '/w/a', commitHash: 'abc', tier: 2, createdAt: Date.now() },
      'noroot.json': { tier: 2, createdAt: Date.now() },
      'notier.json': { repoRoot: '/w/b', createdAt: Date.now() },
      'nocreated.json': { repoRoot: '/w/c', tier: 2 },
      'bad.json': '{not json',
      'null.json': 'null',
    };
    for (const [name, body] of Object.entries(fixtures)) {
      marker(name, body);
    }
    /** CLI 列為有效的檔名 */
    const listed = new Set(run().out.markers.map((m: { file: string }) => m.file));
    for (const name of Object.keys(fixtures)) {
      if (name === 'nocreated.json') {
        // 缺 createdAt 在閘門端屬逾期，readValidMarker 會刪檔，改以 CLI 結果直接斷言
        expect(listed.has(name)).toBe(false);
        continue;
      }
      expect({ name, listed: listed.has(name) }).toEqual({ name, listed: readValidMarker(join(dir, name), Date.now()) !== null });
    }
  });

  test('目錄無法讀取：exit 1 並寫 stderr', () => {
    mkdirSync(join(home, '.claude/state'), { recursive: true });
    writeFileSync(dir, 'not a dir');
    const r = run();
    expect(r.code).toBe(1);
    expect(r.stderr).toContain('list-pending-review:');
  });
});
