import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { spawnSync } from 'child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { parseArgs } from './credential-scan';

/** 被測腳本的路徑 */
const SCRIPT = join(import.meta.dir, 'credential-scan.ts');

/**
 * 假憑證：執行期才拼接，原始碼裡不出現完整字面序列，
 * 否則本測試檔自己 commit 時會被 credential-commit-guard 掃到。
 */
const FAKE_TOKEN = `ghp${'_'}${'a'.repeat(36)}`;

/** 退出碼：沒有命中 */
const EXIT_CLEAN = 0;
/** 退出碼：有命中 */
const EXIT_HIT = 1;
/** 退出碼：掃描沒跑成 */
const EXIT_ERROR = 2;

/** 測試用 git repo 根目錄 */
let repo = '';
/** 非 git 的臨時目錄 */
let plain = '';

/**
 * 在測試 repo 執行 git。
 * @param args git 參數
 * @throws git 以非 0 結束時，錯誤訊息帶 stderr
 */
const git = (args: string[]): void => {
  const r = spawnSync('git', ['-C', repo, ...args], { encoding: 'utf8' });
  if (r.status !== 0) {
    throw new Error(`git ${args.join(' ')} 失敗：${r.stderr}`);
  }
};

/**
 * 執行被測腳本。
 * @param args 傳給腳本的命令列參數
 * @param cwd 執行的工作目錄（預設為測試 repo）
 * @returns spawnSync 的結果（status、stdout、stderr）
 */
const scan = (args: string[], cwd: string = repo) =>
  spawnSync('bun', [SCRIPT, ...args], { cwd, encoding: 'utf8' });

beforeAll(() => {
  repo = mkdtempSync(join(tmpdir(), 'cred-scan-repo-'));
  plain = mkdtempSync(join(tmpdir(), 'cred-scan-plain-'));
  git(['init', '-q']);
  git(['config', 'user.email', 't@example.com']);
  git(['config', 'user.name', 't']);
  writeFileSync(join(repo, 'base.txt'), 'base\n');
  git(['add', 'base.txt']);
  git(['commit', '-q', '-m', 'base']);
});

afterAll(() => {
  rmSync(repo, { recursive: true, force: true });
  rmSync(plain, { recursive: true, force: true });
});

describe('parseArgs', () => {
  test('--all 與路徑', () => {
    expect(parseArgs(['--all', '/x'])).toEqual({ all: true, repo: '/x' });
    expect(parseArgs([])).toEqual({ all: false, repo: null });
  });

  test('未知旗標與多個路徑都拋錯', () => {
    expect(() => parseArgs(['--bogus'])).toThrow('未知旗標');
    expect(() => parseArgs(['/a', '/b'])).toThrow('只能指定一個');
  });
});

describe('credential-scan.ts', () => {
  test('暫存區乾淨 → exit 0', () => {
    writeFileSync(join(repo, 'ok.txt'), 'nothing secret\n');
    git(['add', 'ok.txt']);
    const r = scan([]);
    expect(r.status).toBe(EXIT_CLEAN);
    expect(r.stdout).toContain('✅');
  });

  test('暫存區含憑證 → exit 1，只列檔名、不印憑證值', () => {
    writeFileSync(join(repo, 'leak.env'), `TOKEN=${FAKE_TOKEN}\n`);
    git(['add', 'leak.env']);
    const r = scan([]);
    expect(r.status).toBe(EXIT_HIT);
    expect(r.stdout).toContain('leak.env');
    expect(r.stdout).not.toContain(FAKE_TOKEN);
    expect(r.stderr).not.toContain(FAKE_TOKEN);
  });

  test('用 && 串接：命中時後面的指令不會執行（commit 被擋）', () => {
    const r = spawnSync('sh', ['-c', `bun ${SCRIPT} && echo COMMIT_RAN`], { cwd: repo, encoding: 'utf8' });
    expect(r.stdout).not.toContain('COMMIT_RAN');
    expect(r.status).toBe(EXIT_HIT);
  });

  test('只移除憑證的變更不算命中（清理外洩的 commit 不會被自己擋住）', () => {
    git(['commit', '-q', '--no-verify', '-m', 'leak']);
    writeFileSync(join(repo, 'leak.env'), 'TOKEN=${TOKEN}\n');
    git(['add', 'leak.env']);
    expect(scan([]).status).toBe(EXIT_CLEAN);
    git(['commit', '-q', '-m', 'clean']);
  });

  test('未暫存的已追蹤變更：預設不掃，--all 才掃', () => {
    writeFileSync(join(repo, 'leak.env'), `TOKEN=${FAKE_TOKEN}\n`);
    expect(scan([]).status).toBe(EXIT_CLEAN);
    const all = scan(['--all']);
    expect(all.status).toBe(EXIT_HIT);
    expect(all.stdout).toContain('leak.env');
  });

  test('不是 git repo → exit 2（與「沒命中」可區分）', () => {
    const r = scan([], plain);
    expect(r.status).toBe(EXIT_ERROR);
    expect(r.stderr).toContain('沒跑成');
  });

  test('未知旗標 → exit 2', () => {
    expect(scan(['--bogus']).status).toBe(EXIT_ERROR);
  });
});
