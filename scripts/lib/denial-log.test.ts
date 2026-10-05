/**
 * scripts/log-denial.ts CLI（與其背後的 lib/denial-log.ts）的單元測試：假 HOME 只傳給子行程。
 */
import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { spawnSync } from 'child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/** CLI 絕對路徑 */
const CLI = join(import.meta.dir, '..', 'log-denial.ts');
/** 子行程用的假 HOME */
let home = '';

/**
 * 以 stdin 執行 CLI。
 * @param stdin - 寫入 stdin 的文字
 * @param env - 環境變數（預設 HOME 指向假 HOME）
 * @returns exit code 與 stderr
 */
const run = (stdin: string, env: Record<string, string> = { HOME: home }) => {
  /** 子行程結果 */
  const r = spawnSync('bun', [CLI], { input: stdin, encoding: 'utf8', env: { PATH: process.env.PATH ?? '', ...env } });
  return { code: r.status, stderr: r.stderr };
};

/**
 * 讀出假 HOME 某個 .learnings 紀錄檔的最後一列。
 * @param name - 檔名
 * @returns 最後一列；檔案不存在為 undefined
 */
const lastRow = (name: string) => {
  /** 紀錄檔路徑 */
  const f = join(home, '.claude/.learnings', name);
  return existsSync(f) ? JSON.parse(readFileSync(f, 'utf8').trim().split('\n').at(-1) ?? '{}') : undefined;
};

beforeAll(() => {
  home = mkdtempSync(join(tmpdir(), 'denial-log-'));
});

afterAll(() => {
  rmSync(home, { recursive: true, force: true });
});

describe('log-denial', () => {
  test('寫入一筆紀錄，欄位與截斷正確', () => {
    /** CLI 結果 */
    const r = run(JSON.stringify({ guard: 'g', tool_name: 'Bash', tool_input: { command: 'c'.repeat(400) }, reason: 'r'.repeat(600), session_id: 's1', cwd: '/w/repo-a' }));
    expect(r.code).toBe(0);
    /** 寫入的紀錄 */
    const row = lastRow('DENIALS.jsonl');
    expect(row).toMatchObject({ kind: 'denied', guard: 'g', tool: 'Bash', cwd_name: 'repo-a', session: 's1' });
    expect(row.target.length).toBe(300);
    expect(row.reason.length).toBe(500);
    expect(typeof row.ts).toBe('string');
  });

  test('target 與 reason 內的憑證寫入前遮罩', () => {
    // 假憑證在執行時才組出，原始碼不留符合 pre-commit-scan 樣式的字面值（否則 commit 前的憑證掃描會命中測試檔）
    /** 假密碼 */
    const fakePass = ['hun', 'ter2'].join('');
    /** 連線字串裡的 @（也在執行時插入） */
    const at = '@';
    /** 內含連線字串密碼與 GitHub token 的指令 */
    const command = `git push https://user:${fakePass}${at}github.com/x.git && echo ghp_${'a'.repeat(36)}`;
    expect(run(JSON.stringify({ guard: 'g', tool_name: 'Bash', tool_input: { command }, reason: `see ghp_${'b'.repeat(36)}` })).code).toBe(0);
    /** 寫入的紀錄 */
    const row = lastRow('DENIALS.jsonl');
    expect(row.target).toBe(`git push https://user:***MASKED***${at}github.com/x.git && echo ***MASKED***`);
    expect(row.reason).toBe('see ***MASKED***');
  });

  test('輸入不合法、缺或型別不符的必要欄位：exit 1、寫 stderr，且 ERRORS.jsonl 留下 hook:denial-log', () => {
    for (const bad of [
      'not json',
      JSON.stringify({ tool_name: 'Read', reason: 'x' }),
      JSON.stringify({ guard: 'g', reason: 'x' }),
      JSON.stringify({ guard: 'g', tool_name: 'Read' }),
      JSON.stringify({ guard: 123, tool_name: 'Read', reason: 'x' }),
    ]) {
      /** CLI 結果 */
      const r = run(bad);
      expect({ bad, code: r.code }).toEqual({ bad, code: 1 });
      expect(r.stderr).toContain('log-denial:');
      expect(lastRow('ERRORS.jsonl')).toMatchObject({ context: 'hook:denial-log' });
    }
  });

  test('HOME 未設定：exit 1', () => {
    /** CLI 結果 */
    const r = run(JSON.stringify({ guard: 'g', tool_name: 'Read', reason: 'x' }), {});
    expect(r.code).toBe(1);
    expect(r.stderr).toContain('HOME 未設定');
  });
});
