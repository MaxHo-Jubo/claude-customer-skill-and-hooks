/**
 * 三支 PreToolUse guard 的擋下紀錄回歸測試：以子行程執行真的 guard（stdin 餵 PreToolUse 事件），每支 guard 各自一組，驗證
 * (1) 擋下時 deny 照常、原因不帶附註，DENIALS.jsonl 多一筆且 weekly-review 統計用的 target／cwd_name 正確
 * (2) 放行時不寫紀錄（避免灌爆統計）
 * (3) 紀錄檔不可寫時 deny 仍照常輸出，原因後附上失敗原因，且 ERRORS.jsonl 留下一筆 hook:denial-log（記錄失敗不得削弱強制力，也不得靜默）
 * (4) 記錄模組本身不存在（換機未還原、改壞）時 guard 仍照常 deny：模組在擋下當下才動態載入，不得放在檔頭 import 讓整支 guard 失效。
 * 假 HOME 只傳給子行程；big-read-guard 的 /tmp 狀態檔在 afterAll 清除。
 */
import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { execFileSync, spawnSync } from 'child_process';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { homedir, tmpdir } from 'os';
import { basename, join } from 'path';

/** hooks 目錄 */
const HOOKS = import.meta.dir;
/** 本次測試執行的唯一後綴，避免 big-read-guard 的「同檔只擋一次」狀態跨次殘留 */
const RUN_ID = `${process.pid}-${Date.now()}`;
/** 子行程用的假 HOME */
let home = '';
/** big-read-guard 的測試大檔目錄：放在真 HOME 底下，因為 guard 會放行 /tmp 與 /var/folders 路徑 */
let bigDir = '';
/** commit-gate-guard 用的測試 git repo（realpath） */
let repo = '';
/** 本次測試用過的 session id，afterAll 清掉對應的 /tmp/claude-bigread-* 狀態檔 */
const sessions: string[] = [];

/** guard 子行程結果 */
interface GuardRun {
  /** exit code */
  code: number | null;
  /** 解析後的 deny 原因；未擋下為 null */
  reason: string | null;
}

/** 單支 guard 的測試設定 */
interface GuardCase {
  /** guard 名稱 */
  guard: string;
  /** 執行器（bun 或 bash） */
  cmd: string;
  /** guard 檔名 */
  script: string;
  /** deny 原因的開頭 */
  prefix: string;
  /** 會被擋下的 PreToolUse 輸入（不含 session_id） */
  deny: { cwd: string; tool_name: string; tool_input: { file_path?: string; command?: string; content?: string } };
  /** 會被放行的 PreToolUse 輸入（不含 session_id） */
  allow: { cwd: string; tool_name: string; tool_input: { file_path?: string; command?: string; content?: string } };
}

/**
 * 產生一個本次唯一的 session id 並登記清理。
 * @param tag - 用途標籤
 * @returns session id
 */
const session = (tag: string): string => {
  /** 唯一 session id */
  const id = `${tag}-${RUN_ID}`;
  sessions.push(id);
  return id;
};

/**
 * 執行 guard 並解析 deny 原因。
 * @param c - guard 設定
 * @param input - PreToolUse 輸入
 * @returns exit code 與 deny 原因
 */
const runGuard = (c: GuardCase, input: object): GuardRun => {
  // STEP 01: 以假 HOME 執行
  /** 子行程結果 */
  const r = spawnSync(c.cmd, [join(HOOKS, c.script)], { input: JSON.stringify(input), encoding: 'utf8', env: { PATH: process.env.PATH ?? '', HOME: home } });
  // STEP 02: 解析 deny 原因
  /** stdout（去頭尾空白） */
  const out = r.stdout.trim();
  return { code: r.status, reason: out ? JSON.parse(out).hookSpecificOutput.permissionDecisionReason : null };
};

/**
 * 讀出假 HOME 某個 .learnings 紀錄檔的所有列。
 * @param name - 檔名
 * @returns 紀錄陣列
 */
const rows = (name: string): Record<string, unknown>[] => {
  /** 紀錄檔路徑 */
  const f = join(home, '.claude/.learnings', name);
  return existsSync(f) ? readFileSync(f, 'utf8').trim().split('\n').filter(Boolean).map(l => JSON.parse(l)) : [];
};

/**
 * 三支 guard 的設定（beforeAll 之後才有 bigDir／repo，故延遲建立）。
 * @returns guard 設定陣列
 */
const cases = (): GuardCase[] => [
  {
    guard: 'r15-syntax-guard', cmd: 'bun', script: 'r15-syntax-guard.ts', prefix: '🚫 R15 不支援',
    deny: { cwd: '/w/luna', tool_name: 'Write', tool_input: { file_path: '/w/luna/react_15/a.js', content: 'const n = x?.y;\n' } },
    allow: { cwd: '/w/luna', tool_name: 'Write', tool_input: { file_path: '/w/luna/react_15/a.js', content: 'const n = x && x.y;\n' } },
  },
  {
    guard: 'big-read-guard', cmd: 'bash', script: 'big-read-guard.sh', prefix: 'big.md 有 900 行',
    deny: { cwd: '/w/x', tool_name: 'Read', tool_input: { file_path: join(bigDir, 'big.md') } },
    allow: { cwd: '/w/x', tool_name: 'Read', tool_input: { file_path: join(bigDir, 'small.md') } },
  },
  {
    guard: 'commit-gate-guard', cmd: 'bun', script: 'commit-gate-guard.ts', prefix: '🔒 pending-review 閘門',
    deny: { cwd: repo, tool_name: 'Bash', tool_input: { command: 'git commit -m "x"' } },
    allow: { cwd: repo, tool_name: 'Bash', tool_input: { command: 'git commit -m "x [skip-review]"' } },
  },
];

beforeAll(() => {
  // STEP 01: 假 HOME 與 big-read-guard 的大小檔
  home = mkdtempSync(join(tmpdir(), 'denial-guards-'));
  mkdirSync(join(homedir(), '.cache'), { recursive: true });
  bigDir = mkdtempSync(join(homedir(), '.cache', 'denial-guards-'));
  writeFileSync(join(bigDir, 'big.md'), 'x\n'.repeat(900));
  writeFileSync(join(bigDir, 'small.md'), 'x\n');
  // STEP 02: commit-gate-guard 的 git repo 與有效 marker（marker 路徑由 lib 依假 HOME 推導）
  /** git init 的原始路徑 */
  const raw = mkdtempSync(join(tmpdir(), 'denial-repo-'));
  execFileSync('git', ['init', '-q', raw]);
  repo = execFileSync('git', ['-C', raw, 'rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
  /** 假 HOME 下該 repo 的 marker 路徑 */
  const markerPath = execFileSync('bun', ['-e', `import { markerPathForRepo } from '${join(HOOKS, '../scripts/lib/review-marker.ts')}'; console.log(markerPathForRepo(${JSON.stringify(repo)}))`], { encoding: 'utf8', env: { PATH: process.env.PATH ?? '', HOME: home } }).trim();
  mkdirSync(join(markerPath, '..'), { recursive: true });
  writeFileSync(markerPath, JSON.stringify({ repoRoot: repo, commitHash: 'a'.repeat(40), tier: 2, createdAt: Date.now(), sessionId: 's', expectedAspects: 1 }));
});

afterAll(() => {
  rmSync(home, { recursive: true, force: true });
  rmSync(bigDir, { recursive: true, force: true });
  for (const id of sessions) {
    rmSync(`/tmp/claude-bigread-${id}`, { force: true });
  }
});

describe.each(['r15-syntax-guard', 'big-read-guard', 'commit-gate-guard'])('%s', name => {
  /**
   * 取出這支 guard 的設定。
   * @returns guard 設定
   */
  const c = () => cases().find(x => x.guard === name) as GuardCase;

  test('擋下：deny 照常、原因無附註，多一筆紀錄且 target／cwd_name 正確', () => {
    /** 本測試的 session */
    const sid = session(`${name}-ok`);
    /** 執行前的紀錄數 */
    const before = rows('DENIALS.jsonl').length;
    /** guard 結果 */
    const r = runGuard(c(), { ...c().deny, session_id: sid });
    expect(r.code).toBe(0);
    expect(r.reason?.startsWith(c().prefix)).toBe(true);
    expect(r.reason).not.toContain('附註');
    /** 執行後的紀錄 */
    const after = rows('DENIALS.jsonl');
    expect(after.length).toBe(before + 1);
    expect(after.at(-1)).toMatchObject({
      kind: 'denied', guard: name, tool: c().deny.tool_name, session: sid, reason: r.reason,
      target: c().deny.tool_input.file_path ?? c().deny.tool_input.command, cwd_name: basename(c().deny.cwd),
    });
  });

  test('放行：不輸出 deny，也不寫紀錄', () => {
    /** 執行前的紀錄數 */
    const before = rows('DENIALS.jsonl').length;
    /** guard 結果 */
    const r = runGuard(c(), { ...c().allow, session_id: session(`${name}-allow`) });
    expect(r).toEqual({ code: 0, reason: null });
    expect(rows('DENIALS.jsonl').length).toBe(before);
  });

  test('記錄模組不存在：仍 deny，原因後附上載入／寫入失敗', () => {
    // STEP 01: 在暫存目錄重建 hooks／scripts 結構，複製 guard 與其必要相依，但刻意不放 denial-log.ts／log-denial.ts
    /** 暫存根目錄 */
    const root = mkdtempSync(join(tmpdir(), 'denial-nomod-'));
    mkdirSync(join(root, 'hooks'));
    mkdirSync(join(root, 'scripts/lib'), { recursive: true });
    copyFileSync(join(HOOKS, c().script), join(root, 'hooks', c().script));
    for (const lib of ['review-marker.ts', 'review-engine.ts']) {
      copyFileSync(join(HOOKS, '../scripts/lib', lib), join(root, 'scripts/lib', lib));
    }
    try {
      // STEP 02: 執行副本 guard
      /** 子行程結果 */
      const r = spawnSync(c().cmd, [join(root, 'hooks', c().script)], { input: JSON.stringify({ ...c().deny, session_id: session(`${name}-nomod`) }), encoding: 'utf8', env: { PATH: process.env.PATH ?? '', HOME: home } });
      /** 解析出的 deny 原因 */
      const reason: string = JSON.parse(r.stdout.trim()).hookSpecificOutput.permissionDecisionReason;
      expect(r.status).toBe(0);
      expect(reason.startsWith(c().prefix)).toBe(true);
      expect(reason).toMatch(/（附註：擋下紀錄(模組載入失敗|寫入失敗)/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test('紀錄檔不可寫：仍 deny，原因後附上失敗原因，ERRORS.jsonl 留下 hook:denial-log', () => {
    // 檔案本身設唯讀：只鎖目錄擋不住對既有檔案的 append；ERRORS.jsonl 保持可寫，驗證第二條出口
    /** .learnings 目錄 */
    const dir = join(home, '.claude/.learnings');
    /** DENIALS.jsonl 路徑 */
    const file = join(dir, 'DENIALS.jsonl');
    mkdirSync(dir, { recursive: true });
    writeFileSync(file, '', { flag: 'a' });
    writeFileSync(join(dir, 'ERRORS.jsonl'), '', { flag: 'a' });
    chmodSync(file, 0o400);
    /** 執行前的 ERRORS 筆數 */
    const before = rows('ERRORS.jsonl').length;
    try {
      /** guard 結果 */
      const r = runGuard(c(), { ...c().deny, session_id: session(`${name}-ro`) });
      expect(r.code).toBe(0);
      expect(r.reason?.startsWith(c().prefix)).toBe(true);
      expect(r.reason).toMatch(/擋下紀錄寫入失敗：.*(EACCES|permission denied)/i);
      /** 新增的 ERRORS 紀錄 */
      const added = rows('ERRORS.jsonl').slice(before);
      expect(added).toEqual([expect.objectContaining({ context: 'hook:denial-log', tool: name })]);
    } finally {
      chmodSync(file, 0o600);
    }
  });
});
