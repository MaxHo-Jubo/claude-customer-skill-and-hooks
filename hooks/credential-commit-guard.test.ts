/**
 * credential-commit-guard 回歸測試：以子行程執行真的 hook（stdin 餵 PreToolUse 事件），在臨時 git repo 內驗證
 * (1) 五種憑證形態（ghp_／github_pat_／sk-／AIza／PEM 私鑰）與內嵌密碼連線字串各自被擋，reason 只列檔名不含內容，且寫一筆 DENIALS.jsonl
 * (2) 所有放行情境一律斷言 exit 0、無 deny、stderr 為空、沒有新增 DENIALS 紀錄——放行時 exit 1 不得被當成通過
 * (3) 只掃新增行：移除憑證、把憑證換成環境變數的 commit 不被擋（否則清理外洩的 commit 自己被卡住）
 * (4) -a／--all 與 pathspec 會把未暫存的內容納入掃描；commit message 裡的 `;`、`-a` 不干擾旗標解析
 * (5) hook 自身錯誤（無效 JSON、事件欄位型別不符、暫存區損毀）不擋 commit，但 exit 1 + stderr
 * (6) CREDENTIAL_PATTERN 與 security.md、sync skill 內的副本逐字一致
 * 假憑證一律在執行期用字串拼接組出，避免本檔原始碼自己命中 pre-commit-scan。假 HOME 只傳給子行程。
 */
import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { execFileSync, spawnSync } from 'child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'fs';
import { homedir, tmpdir } from 'os';
import { join } from 'path';
import { CREDENTIAL_PATTERN, parseCommit } from './credential-commit-guard';

/** 被測 hook 路徑 */
const GUARD = join(import.meta.dir, 'credential-commit-guard.ts');
/** hook 子行程的等待上限（毫秒）：bun 冷啟動加 git 子行程，慢機器上也要夠用 */
const HOOK_TEST_TIMEOUT_MS = 15000;
/** 假 token 主體的長度：須大於 pattern 要求的最短長度（ghp_ 30、sk- 20、AIza 30、github_pat_ 30） */
const FAKE_TOKEN_BODY_LENGTH = 40;

/** 假 HOME（讓 DENIALS.jsonl 寫到臨時目錄，不污染真的紀錄） */
let home = '';
/** 測試用 git repo（realpath） */
let repo = '';
/** 測試用 git repo，暫存區之後會被刻意弄壞 */
let brokenRepo = '';

/** 各類憑證的假資料（執行期拼接）：名稱 → 內容 */
const FAKE_CREDENTIALS: Array<[string, string]> = [
  ['ghp_ token', 'T=ghp_' + 'a'.repeat(FAKE_TOKEN_BODY_LENGTH)],
  ['github_pat_ token', 'T=github_pat_' + 'b'.repeat(FAKE_TOKEN_BODY_LENGTH)],
  ['sk- 金鑰', 'K=sk-' + 'c'.repeat(FAKE_TOKEN_BODY_LENGTH)],
  ['AIza 金鑰', 'G=AIza' + 'd'.repeat(FAKE_TOKEN_BODY_LENGTH)],
  ['PEM 私鑰標頭', '-----BEGIN RSA ' + 'PRIVATE KEY-----'],
  ['內嵌密碼的連線字串', 'u=mongodb+srv://user:' + 'pw' + '@host/db'],
];
/** 單一假 token，供只需要一個憑證的情境用 */
const FAKE_TOKEN = FAKE_CREDENTIALS[0][1];

/** hook 子行程結果 */
interface GuardRun {
  /** exit code */
  code: number | null;
  /** 解析後的 deny 原因；未擋下為 null */
  reason: string | null;
  /** stderr 全文 */
  stderr: string;
}

/**
 * 在指定 repo 內執行 git；失敗即拋錯。
 * @param dir repo 路徑
 * @param args git 參數
 * @returns 無
 */
function git(dir: string, ...args: string[]): void {
  execFileSync('git', ['-C', dir, ...args], { stdio: 'ignore' });
}

/**
 * 建立一個有一筆初始 commit 的臨時 git repo。
 * @param prefix 目錄前綴
 * @returns repo 的 realpath
 */
function makeRepo(prefix: string): string {
  // STEP 01: 建臨時目錄並初始化
  /** 臨時 repo 目錄（realpath，避免 macOS /var → /private/var 造成路徑比對差異） */
  const dir = realpathSync(mkdtempSync(join(tmpdir(), prefix)));
  git(dir, 'init', '-q');
  git(dir, 'config', 'user.email', 't@t');
  git(dir, 'config', 'user.name', 't');
  // STEP 02: 放一筆初始 commit，讓 HEAD 存在
  writeFileSync(join(dir, 'base.txt'), 'base\n');
  git(dir, 'add', 'base.txt');
  git(dir, 'commit', '-q', '-m', 'init');
  return dir;
}

/**
 * 把暫存區與工作目錄還原成目前 HEAD，並清掉未追蹤檔。
 * @param dir repo 路徑
 * @returns 無
 */
function reset(dir: string): void {
  git(dir, 'reset', '-q', '--hard');
  git(dir, 'clean', '-fdq');
}

/**
 * 以子行程執行 hook，餵一個 PreToolUse 事件原文。
 * @param stdin 餵給 hook 的 stdin 全文
 * @returns 執行結果
 */
function runRaw(stdin: string): GuardRun {
  // STEP 01: 啟動子行程（假 HOME）
  const r = spawnSync('bun', [GUARD], { input: stdin, encoding: 'utf8', env: { ...process.env, HOME: home }, timeout: HOOK_TEST_TIMEOUT_MS });
  if (r.error) {
    throw new Error(`hook 子行程啟動失敗：${r.error.message}`);
  }
  // STEP 02: 解析 stdout 的 deny 決定
  /** stdout 去空白後的內容 */
  const out = (r.stdout || '').trim();
  /** deny 原因；未擋下為 null */
  let reason: string | null = null;
  if (out) {
    /** hook 輸出的 JSON */
    const parsed = JSON.parse(out);
    reason = parsed.hookSpecificOutput?.permissionDecision === 'deny' ? parsed.hookSpecificOutput.permissionDecisionReason : null;
  }
  return { code: r.status, reason, stderr: r.stderr || '' };
}

/**
 * 以子行程執行 hook，餵一個 Bash（或指定工具）事件。
 * @param command Bash 指令
 * @param cwd hook 輸入的 cwd
 * @param toolName 工具名稱
 * @returns 執行結果
 */
function runGuard(command: string, cwd: string, toolName = 'Bash'): GuardRun {
  return runRaw(JSON.stringify({ tool_name: toolName, tool_input: { command }, cwd, session_id: 'cred-test' }));
}

/**
 * 讀出假 HOME 的 DENIALS.jsonl 所有列。
 * @returns 解析後的列
 */
function denialRows(): Array<{ guard: string; target: string }> {
  /** 紀錄檔路徑 */
  const f = join(home, '.claude/.learnings/DENIALS.jsonl');
  if (!existsSync(f)) {
    return [];
  }
  return readFileSync(f, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));
}

/**
 * 斷言一次執行是「乾淨放行」：exit 0、未 deny、stderr 空、沒有新增 DENIALS 紀錄。
 * @param run 執行結果
 * @param deniedBefore 執行前的 DENIALS 列數
 * @returns 無
 */
function expectPass(run: GuardRun, deniedBefore: number): void {
  expect(run.code).toBe(0);
  expect(run.reason).toBeNull();
  expect(run.stderr).toBe('');
  expect(denialRows().length).toBe(deniedBefore);
}

beforeAll(() => {
  // STEP 01: 建假 HOME 與兩個測試 repo
  home = realpathSync(mkdtempSync(join(tmpdir(), 'cred-guard-home-')));
  mkdirSync(join(home, '.claude/.learnings'), { recursive: true });
  repo = makeRepo('cred-guard-repo-');
  brokenRepo = makeRepo('cred-guard-broken-');
});

afterAll(() => {
  // STEP 01: 清掉臨時目錄
  for (const d of [home, repo, brokenRepo]) {
    if (d) {
      rmSync(d, { recursive: true, force: true });
    }
  }
});

describe('parseCommit', () => {
  test('-a／-am／--all 視為帶 all', () => {
    expect(parseCommit('git commit -a -m "x"').all).toBe(true);
    expect(parseCommit('git commit -am "x"').all).toBe(true);
    expect(parseCommit('git commit --all -m x').all).toBe(true);
    expect(parseCommit('git -C /r commit -a -m x').all).toBe(true);
  });
  test('message 含分隔符或 -a 字樣不影響判斷（引號內容先去除）', () => {
    expect(parseCommit('git commit -m "fix; x" -a').all).toBe(true);
    expect(parseCommit('echo commit && git commit -am "x"').all).toBe(true);
    expect(parseCommit('git commit -m "msg with -a flag"').all).toBe(false);
    expect(parseCommit("git commit -m \"$(cat <<'EOF'\nfix -a ; thing\nEOF\n)\"").all).toBe(false);
  });
  test('沒有 -a 的 commit 不算', () => {
    expect(parseCommit('git commit -m "x"').all).toBe(false);
    expect(parseCommit('git commit --amend --no-edit').all).toBe(false);
  });
  test('pathspec：-- 之後、或省略 -- 的非選項 token；message 值不算路徑', () => {
    expect(parseCommit('git commit -m x -- tracked.env').paths).toEqual(['tracked.env']);
    expect(parseCommit('git commit -m x tracked.env other.js').paths).toEqual(['tracked.env', 'other.js']);
    expect(parseCommit('git commit -m "a b" -- a.txt').paths).toEqual(['a.txt']);
    expect(parseCommit('git commit -am "x"').paths).toEqual([]);
    expect(parseCommit('git commit --message foo --author "A <a@b>" f.txt').paths).toEqual(['f.txt']);
  });
});

describe('credential-commit-guard 擋下', () => {
  test.each(FAKE_CREDENTIALS)('暫存區有 %s → deny；reason 列檔名、不含內容；DENIALS 多一筆', (_name, content) => {
    reset(repo);
    writeFileSync(join(repo, 'leak.env'), content + '\n');
    git(repo, 'add', 'leak.env');
    /** 執行前的 DENIALS 列數 */
    const before = denialRows().length;
    const r = runGuard('git commit -m "x"', repo);
    expect(r.code).toBe(0);
    expect(r.reason).toContain('leak.env');
    expect(r.reason).not.toContain(content);
    /** 執行後的 DENIALS 列 */
    const rows = denialRows();
    expect(rows.length).toBe(before + 1);
    expect(rows[rows.length - 1].guard).toBe('credential-commit-guard');
  });

  test('git -C <repo> commit 形式（cwd 在 repo 外）也能辨識並 deny', () => {
    reset(repo);
    writeFileSync(join(repo, 'leak.env'), `${FAKE_TOKEN}\n`);
    git(repo, 'add', 'leak.env');
    expect(runGuard(`git -C ${repo} commit -m "x"`, tmpdir()).reason).toContain('leak.env');
  });

  test('-a：未暫存的已追蹤檔新增憑證 → deny（含 message 帶分號、-a 在 message 之後）；沒帶 -a → 放行', () => {
    reset(repo);
    writeFileSync(join(repo, 'base.txt'), `base\n${FAKE_TOKEN}\n`);
    expect(runGuard('git commit -am "x"', repo).reason).toContain('base.txt');
    expect(runGuard('git commit -m "fix; x" -a', repo).reason).toContain('base.txt');
    expect(runGuard('echo commit && git commit -am "x"', repo).reason).toContain('base.txt');
    /** 執行前的 DENIALS 列數 */
    const before = denialRows().length;
    expectPass(runGuard('git commit -m "x"', repo), before);
  });

  test('pathspec：git commit -m x -- file 會提交該檔的工作目錄版本 → 掃到未暫存的憑證 deny；不指定路徑則放行', () => {
    reset(repo);
    writeFileSync(join(repo, 'base.txt'), `base\n${FAKE_TOKEN}\n`);
    expect(runGuard('git commit -m "x" -- base.txt', repo).reason).toContain('base.txt');
    expect(runGuard('git commit -m "x" base.txt', repo).reason).toContain('base.txt');
    /** 執行前的 DENIALS 列數 */
    const before = denialRows().length;
    expectPass(runGuard('git commit -m "x"', repo), before);
  });
});

describe('credential-commit-guard 放行', () => {
  test('乾淨暫存', () => {
    reset(repo);
    writeFileSync(join(repo, 'ok.txt'), 'hello\n');
    git(repo, 'add', 'ok.txt');
    /** 執行前的 DENIALS 列數 */
    const before = denialRows().length;
    expectPass(runGuard('git commit -m "x"', repo), before);
  });

  test('只有變數名 process.env.API_KEY（非憑證）', () => {
    reset(repo);
    writeFileSync(join(repo, 'code.js'), 'const k = process.env.API_KEY;\n');
    git(repo, 'add', 'code.js');
    /** 執行前的 DENIALS 列數 */
    const before = denialRows().length;
    expectPass(runGuard('git commit -m "x"', repo), before);
  });

  test('非 commit 指令即使暫存區有憑證也放行（修復指令不能被擋）', () => {
    reset(repo);
    writeFileSync(join(repo, 'leak.env'), `${FAKE_TOKEN}\n`);
    git(repo, 'add', 'leak.env');
    /** 執行前的 DENIALS 列數 */
    const before = denialRows().length;
    expectPass(runGuard('git restore --staged leak.env', repo), before);
    expectPass(runGuard('git status', repo), before);
    expectPass(runGuard('echo git commit', repo), before);
  });

  test('非 Bash 工具', () => {
    reset(repo);
    writeFileSync(join(repo, 'leak.env'), `${FAKE_TOKEN}\n`);
    git(repo, 'add', 'leak.env');
    /** 執行前的 DENIALS 列數 */
    const before = denialRows().length;
    expectPass(runGuard('git commit -m "x"', repo, 'Read'), before);
  });

  test('指令含 [skip-credential-scan]', () => {
    reset(repo);
    writeFileSync(join(repo, 'fixture.txt'), `${FAKE_TOKEN}\n`);
    git(repo, 'add', 'fixture.txt');
    /** 執行前的 DENIALS 列數 */
    const before = denialRows().length;
    expectPass(runGuard('git commit -m "test: 假憑證 fixture [skip-credential-scan]"', repo), before);
  });

  test('只掃新增行：刪除含憑證的檔案、或把憑證換成環境變數的 commit 不被擋', () => {
    /** 本測試專用 repo：先把含憑證的檔案 commit 進去，再模擬清理 */
    const dir = makeRepo('cred-guard-cleanup-');
    try {
      writeFileSync(join(dir, 'leak.env'), `${FAKE_TOKEN}\n`);
      writeFileSync(join(dir, 'conf.js'), `const t = '${FAKE_TOKEN}';\n`);
      git(dir, 'add', '-A');
      git(dir, 'commit', '-q', '-m', 'oops leaked');
      /** 執行前的 DENIALS 列數 */
      const before = denialRows().length;
      // 刪除整個含憑證的檔案
      git(dir, 'rm', '-q', 'leak.env');
      expectPass(runGuard('git commit -m "remove leak"', dir), before);
      // 把憑證換成環境變數
      writeFileSync(join(dir, 'conf.js'), 'const t = process.env.TOKEN;\n');
      git(dir, 'add', 'conf.js');
      expectPass(runGuard('git commit -m "use env"', dir), before);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe('credential-commit-guard 自身錯誤：不擋 commit，但 exit 1 + stderr', () => {
  test('暫存區損毀 → 掃描失敗', () => {
    reset(brokenRepo);
    writeFileSync(join(brokenRepo, '.git/index'), 'not an index');
    const r = runGuard('git commit -m "x"', brokenRepo);
    expect(r.reason).toBeNull();
    expect(r.code).toBe(1);
    expect(r.stderr).toContain('掃描失敗');
  });

  test('stdin 不是合法 JSON', () => {
    const r = runRaw('not json');
    expect(r.reason).toBeNull();
    expect(r.code).toBe(1);
    expect(r.stderr).toContain('內部錯誤');
  });

  test('JSON 是 null（事件不是物件）', () => {
    const r = runRaw('null');
    expect(r.code).toBe(1);
    expect(r.stderr).toContain('不是 JSON 物件');
  });

  test('Bash 事件的 cwd 型別不符', () => {
    const r = runRaw(JSON.stringify({ tool_name: 'Bash', tool_input: { command: 'git commit -m x' }, cwd: 42 }));
    expect(r.code).toBe(1);
    expect(r.stderr).toContain('cwd 不是字串');
  });

  test('Bash 事件缺 command', () => {
    const r = runRaw(JSON.stringify({ tool_name: 'Bash', tool_input: {}, cwd: repo }));
    expect(r.code).toBe(1);
    expect(r.stderr).toContain('command 不是字串');
  });
});

describe('pattern 一致性', () => {
  test('CREDENTIAL_PATTERN 與 security.md、sync skill 內的副本逐字一致', () => {
    /** 必須含有同一份 pattern 的檔案 */
    const copies = [
      join(homedir(), '.claude/rules/common/security.md'),
      join(homedir(), '.claude/skills/sync-my-claude-setting/SKILL.md'),
    ];
    for (const f of copies) {
      expect(existsSync(f)).toBe(true);
      expect(readFileSync(f, 'utf8')).toContain(CREDENTIAL_PATTERN);
    }
  });
});
