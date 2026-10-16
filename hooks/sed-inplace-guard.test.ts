/**
 * sed-inplace-guard 測試：
 * (1) isSedInPlace 的命中／放行矩陣（旗標寫法、指令位置、引號與 heredoc 內的文字、逃生門）
 * (2) 以子行程執行真的 guard（stdin 餵 PreToolUse 事件）：deny 輸出格式、DENIALS.jsonl 紀錄、
 *     放行不寫紀錄、壞輸入與非 Bash 工具 fail-open、記錄模組不存在時仍照常 deny
 * 假 HOME 只傳給子行程，不碰真實的 ~/.claude/.learnings。
 */
import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { spawnSync } from 'child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { isSedInPlace } from './sed-inplace-guard';

/** hooks 目錄 */
const HOOKS = import.meta.dir;
/** guard 檔案 */
const GUARD = join(HOOKS, 'sed-inplace-guard.ts');

/** 應命中的指令 */
const SHOULD_HIT: Array<[string, string]> = [
  ['基本 -i', `sed -i 's/a/b/' f`],
  ['for 迴圈 do 之後', 'for f in *.ts; do sed -i s/a/b/ "$f"; done'],
  ['if then 之後', 'if true; then sed -i s/a/b/ f; fi'],
  ['while do 之後', 'while read f; do sed -i s/a/b/ "$f"; done < list'],
  ['-i 帶後綴', 'sed -i.bak s/a/b/ f'],
  ['BSD 寫法 -i 空字串', `sed -i '' 's/a/b/' f`],
  ['合併旗標 -ni', `sed -ni 's/a/b/p' f`],
  ['合併旗標 -Ei', `sed -Ei 's/x/y/' f`],
  ['合併旗標 -ie', 'sed -ie s/a/b/ f'],
  ['--in-place', 'sed --in-place s/a/b/ f'],
  ['--in-place=後綴', 'sed --in-place=.bak s/a/b/ f'],
  ['第二段指令', `sed -n 1p f && sed -i s/a/b/ g`],
  ['xargs 管線', `find . -name '*.js' | xargs sed -i 's/a/b/'`],
  ['xargs 帶旗標與 {}', `find . -name x | xargs -I {} sed -i s/a/b/ {}`],
  ['sudo', 'sudo sed -i s/a/b/ /etc/x'],
  ['環境變數前綴', 'LC_ALL=C sed -i s/a/b/ f'],
  ['絕對路徑', '/usr/bin/sed -i s/a/b/ f'],
  ['gsed', 'gsed -i s/a/b/ f'],
  ['指令替換內', 'echo $(sed -i s/a/b/ f)'],
  ['反引號內', 'echo `sed -i s/a/b/ f`'],
  ['子殼層內', '(cd x && sed -i s/a/b/ f)'],
  ['旗標在 script 之後', 'sed s/a/b/ -i f'],
  ['換行分隔的第二行', 'cd x\nsed -i s/a/b/ f'],
];

/** 不應命中的指令 */
const SHOULD_PASS: Array<[string, string]> = [
  ['一般 sed 輸出', `sed -n '1,5p' f`],
  ['重導向輸出', `sed 's/a/b/' f > out`],
  ['引號內的 i 旗標', `sed -e 's/a/b/i' f`],
  ['未引號 script 帶 i 旗標', 'sed -e s/a/b/gi f'],
  ['-n -e', 'sed -n -e p f'],
  ['--silent／--expression', 'sed --silent --expression=p f'],
  ['-s 分別處理檔案', 'sed -s p f1 f2'],
  ['grep 引號內提到', `grep "sed -i" notes.md`],
  ['echo 引號內提到', `echo 'use sed -i here'`],
  ['commit message 提到', `git commit -m "ban sed -i"`],
  ['heredoc 內提到', `cat <<'EOF'\nsed -i s/a/b/ f\nEOF`],
  ['引號內有分隔符後接 sed -i', `echo "run; sed -i s/a/b/ f"`],
  ['sed 不在指令位置', 'echo sed -i x'],
  ['關鍵字後仍是別的指令的引數', 'for f in a; do echo sed -i x; done'],
  ['git log 的引數', 'git log --grep sed -i'],
  ['逃生門', 'sed -i s/a/b/ f # [allow-sed-i]'],
  ['空指令', ''],
];

describe('isSedInPlace：應命中', () => {
  for (const [name, cmd] of SHOULD_HIT) {
    test(name, () => {
      expect(isSedInPlace(cmd)).toBe(true);
    });
  }
});

describe('isSedInPlace：不應命中', () => {
  for (const [name, cmd] of SHOULD_PASS) {
    test(name, () => {
      expect(isSedInPlace(cmd)).toBe(false);
    });
  }
});

/** guard 子行程結果 */
interface Run {
  /** exit code */
  code: number | null;
  /** stdout 原文 */
  stdout: string;
}

/**
 * 以子行程執行 guard。
 * @param stdin 餵給 guard 的 stdin 內容
 * @param home 子行程的假 HOME
 * @param script guard 檔案路徑
 * @returns 執行結果
 */
const runGuard = (stdin: string, home: string, script: string = GUARD): Run => {
  const r = spawnSync('bun', [script], { input: stdin, encoding: 'utf8', env: { ...process.env, HOME: home } });
  return { code: r.status, stdout: r.stdout };
};

/** 組一個 PreToolUse Bash 事件 */
const bashEvent = (command: string): string =>
  JSON.stringify({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command }, session_id: 'sed-guard-test', cwd: '/tmp/some-repo' });

/** 假 HOME */
let home = '';

/** 讀 DENIALS.jsonl 內所有紀錄；檔案不存在為空陣列 */
const denials = (): Array<Record<string, unknown>> => {
  /** 紀錄檔路徑 */
  const f = join(home, '.claude', '.learnings', 'DENIALS.jsonl');
  return existsSync(f) ? readFileSync(f, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)) : [];
};

beforeAll(() => {
  home = mkdtempSync(join(tmpdir(), 'sed-guard-home-'));
});

afterAll(() => {
  rmSync(home, { recursive: true, force: true });
});

describe('sed-inplace-guard 子行程', () => {
  test('放行：不輸出、不寫紀錄', () => {
    const r = runGuard(bashEvent(`sed -n '1,5p' f`), home);
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(denials()).toHaveLength(0);
  });

  test('擋下：deny 輸出、原因帶改用建議、DENIALS 多一筆', () => {
    const r = runGuard(bashEvent(`sed -i 's/a/b/' f`), home);
    expect(r.code).toBe(0);
    const out = JSON.parse(r.stdout);
    expect(out.hookSpecificOutput.permissionDecision).toBe('deny');
    expect(out.hookSpecificOutput.permissionDecisionReason).toContain('Edit 工具');
    expect(out.hookSpecificOutput.permissionDecisionReason).toContain('[allow-sed-i]');
    /** 紀錄 */
    const log = denials();
    expect(log).toHaveLength(1);
    expect(log[0].guard).toBe('sed-inplace-guard');
    expect(String(log[0].target)).toContain('sed -i');
  });

  test('逃生門：放行且不再多寫紀錄', () => {
    const r = runGuard(bashEvent(`sed -i s/a/b/ f # [allow-sed-i]`), home);
    expect(r.stdout).toBe('');
    expect(denials()).toHaveLength(1);
  });

  test('非 Bash 工具、壞 JSON、缺 command 都 fail-open', () => {
    expect(runGuard(JSON.stringify({ tool_name: 'Edit', tool_input: { file_path: '/x', command: 'sed -i x' } }), home).stdout).toBe('');
    expect(runGuard('not json', home).stdout).toBe('');
    expect(runGuard(JSON.stringify({ tool_name: 'Bash', tool_input: {} }), home).stdout).toBe('');
  });

  test('記錄模組不存在：仍照常 deny，原因附註記錄失敗（不得讓整支 guard 失效）', () => {
    /** 只含 guard 與 shell-text 的臨時樹，刻意不放 denial-log.ts */
    const tree = mkdtempSync(join(tmpdir(), 'sed-guard-tree-'));
    try {
      mkdirSync(join(tree, 'hooks'), { recursive: true });
      mkdirSync(join(tree, 'scripts', 'lib'), { recursive: true });
      copyFileSync(GUARD, join(tree, 'hooks', 'sed-inplace-guard.ts'));
      copyFileSync(join(HOOKS, '..', 'scripts', 'lib', 'shell-text.ts'), join(tree, 'scripts', 'lib', 'shell-text.ts'));
      const r = runGuard(bashEvent('sed -i s/a/b/ f'), home, join(tree, 'hooks', 'sed-inplace-guard.ts'));
      const out = JSON.parse(r.stdout);
      expect(out.hookSpecificOutput.permissionDecision).toBe('deny');
      expect(out.hookSpecificOutput.permissionDecisionReason).toContain('擋下紀錄模組載入失敗');
    } finally {
      rmSync(tree, { recursive: true, force: true });
    }
  });
});
