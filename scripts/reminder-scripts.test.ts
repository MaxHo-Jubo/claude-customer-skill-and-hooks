import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { spawnSync } from 'child_process';
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/**
 * tool-reminders mod 與兩支提醒腳本之間的介面約定測試。
 * mod 自己的測試把 $.process.run 整個 mock 掉，驗不到「mod 送的 stdin 腳本讀不讀得懂」與「exit code 語意」；
 * 這裡用 mod 實際送出的 stdin 格式（{ tool_name, tool_input: { file_path } }）spawn 真的腳本，假 HOME 只傳給子行程。
 */

/** inventory-drift-detector 的絕對路徑 */
const DRIFT = join(import.meta.dir, 'inventory-drift-detector.ts');
/** spec-section-validator 的絕對路徑 */
const SPEC = join(import.meta.dir, 'spec-section-validator.ts');

/** 子行程用的假 HOME */
let home = '';

/** 子行程執行結果 */
interface RunResult {
  /** exit code */
  code: number | null;
  /** 標準輸出 */
  stdout: string;
  /** 標準錯誤 */
  stderr: string;
}

/**
 * 以 mod 的 stdin 格式執行腳本。
 * @param script - 腳本絕對路徑
 * @param stdin - 要寫入 stdin 的文字
 * @param args - 額外參數
 * @param env - 覆寫的環境變數（預設 HOME 指向假 HOME）
 * @returns exit code 與輸出
 */
const run = (script: string, stdin: string, args: string[] = [], env: Record<string, string> = { HOME: home }): RunResult => {
  const r = spawnSync('bun', [script, ...args], { input: stdin, encoding: 'utf8', env: { PATH: process.env.PATH ?? '', ...env } });
  return { code: r.status, stdout: r.stdout, stderr: r.stderr };
};

/**
 * 組出 mod 送給腳本的 stdin。
 * @param filePath - 被寫入的檔案路徑
 * @param tool - 工具名稱
 * @returns JSON 字串
 */
const payload = (filePath: string, tool = 'Write'): string =>
  JSON.stringify({ tool_name: tool, tool_input: { file_path: filePath } });

beforeAll(() => {
  // STEP 01: 建立假 HOME：一個已記錄、一個未記錄的 skill，外加應被排除的 synced 與 node_modules
  home = mkdtempSync(join(tmpdir(), 'reminder-scripts-'));
  const claude = join(home, '.claude');
  for (const dir of ['skills/known', 'skills/fresh', 'skills/synced/u/docx', 'skills/known/node_modules/pw/trace', 'scripts', 'projects/-Users-maxhero/memory']) {
    mkdirSync(join(claude, dir), { recursive: true });
  }
  for (const f of ['skills/known/SKILL.md', 'skills/fresh/SKILL.md', 'skills/synced/u/docx/SKILL.md', 'skills/known/node_modules/pw/trace/SKILL.md']) {
    writeFileSync(join(claude, f), '# x\n');
  }
  writeFileSync(join(claude, 'scripts/foo.ts'), '');
  writeFileSync(join(claude, 'projects/-Users-maxhero/memory/inventory.md'), '| known |\n');
  // STEP 02: 模擬多帳號：另一個設定目錄的 scripts 是指向 ~/.claude/scripts 的 symlink
  mkdirSync(join(home, '.claude-alt'));
  symlinkSync(join(claude, 'scripts'), join(home, '.claude-alt/scripts'));
  // STEP 03: spec 檔：空骨架、缺 section、齊全
  mkdirSync(join(home, 'proj/spec'), { recursive: true });
  writeFileSync(join(home, 'proj/spec/empty.md'), '# empty\n');
  writeFileSync(join(home, 'proj/spec/partial.md'), '# p\n\n## 其他\n');
  writeFileSync(join(home, 'proj/spec/full.md'), '# f\n\n## 概述\n\n## 品質\n');
});

afterAll(() => {
  rmSync(home, { recursive: true, force: true });
});

describe('inventory-drift-detector', () => {
  test('相關路徑：只回報未記錄的 skill，排除 synced 與 node_modules', () => {
    const r = run(DRIFT, payload(join(home, '.claude/scripts/foo.ts')));
    expect(r.code).toBe(0);
    expect(r.stdout).toContain('"fresh"');
    expect(r.stdout).not.toContain('"known"');
    expect(r.stdout).not.toContain('"docx"');
    expect(r.stdout).not.toContain('"trace"');
    expect(r.stdout).toContain('[Hook 腳本變更] foo.ts');
  });

  test('經 symlink 的路徑與實體路徑結果相同', () => {
    const r = run(DRIFT, payload(join(home, '.claude-alt/scripts/foo.ts'), 'Edit'));
    expect(r.code).toBe(0);
    expect(r.stdout).toContain('[Hook 腳本變更] foo.ts');
  });

  test('不相關路徑：exit 0 無輸出', () => {
    const r = run(DRIFT, payload(join(home, 'proj/spec/full.md')));
    expect(r).toMatchObject({ code: 0, stdout: '' });
  });

  test('輸入不符契約一律 exit 1 並寫 stderr', () => {
    for (const bad of ['not json', JSON.stringify({ tool_name: 'Write', tool_input: {} }), payload(join(home, 'x'), 'Read')]) {
      const r = run(DRIFT, bad);
      expect(r.code).toBe(1);
      expect(r.stderr).toContain('inventory-drift-detector:');
    }
  });

  test('HOME 未設定：exit 1', () => {
    const r = run(DRIFT, payload('/tmp/x'), [], {});
    expect(r.code).toBe(1);
    expect(r.stderr).toContain('HOME 未設定');
  });
});

describe('spec-section-validator', () => {
  test('--warn-only：空骨架輸出警告、exit 0', () => {
    const r = run(SPEC, payload(join(home, 'proj/spec/empty.md')), ['--warn-only']);
    expect(r.code).toBe(0);
    expect(r.stdout).toContain('empty.md 沒有任何 ## heading');
  });

  test('--warn-only：缺 section 也不 block（exit 0、無輸出）', () => {
    const r = run(SPEC, payload(join(home, 'proj/spec/partial.md')), ['--warn-only']);
    expect(r).toMatchObject({ code: 0, stdout: '' });
  });

  test('預設模式：缺 section 仍以 decision:block + exit 2 回報', () => {
    const r = run(SPEC, payload(join(home, 'proj/spec/partial.md')));
    expect(r.code).toBe(2);
    expect(JSON.parse(r.stdout).decision).toBe('block');
  });

  test('預設模式：section 齊全時 exit 0 無輸出', () => {
    const r = run(SPEC, payload(join(home, 'proj/spec/full.md')));
    expect(r).toMatchObject({ code: 0, stdout: '' });
  });

  test('輸入不符契約或讀檔失敗：兩種模式都 exit 1 並寫 stderr', () => {
    for (const args of [[], ['--warn-only']]) {
      for (const bad of ['not json', JSON.stringify({ tool_name: 'Write', tool_input: {} }), payload(join(home, 'proj/spec/nope.md'))]) {
        const r = run(SPEC, bad, args);
        expect(r.code).toBe(1);
        expect(r.stderr).toContain('spec-section-validator:');
      }
    }
  });
});
