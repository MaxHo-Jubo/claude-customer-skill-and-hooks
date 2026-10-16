/**
 * post-commit-review hook 的 eslint 分組回歸測試：以子行程執行真的 hook，repo 內放「假的本機 eslint」
 * （shell 腳本，記下 cwd 與 argv，依 `.fake-exit` 檔決定 exit code），驗證 hook 真的照分組規劃執行。
 *
 * 為什麼需要：eslint-targets.test.ts 只驗證分組資料，post-commit-review.test.ts 全部提交 .py 檔、
 * 不會進入 eslint 執行分支。hook 沒用分組結果、cwd 傳錯、錯誤分類失效時，這兩份測試仍全綠。
 * 舊行為（2026-10 週檢討）：一律在 repo 根目錄跑 `npx eslint`，根目錄沒有本機 eslint 時 npx 下載
 * ESLint 10 並 exit 2、被當環境問題跳過——lint 從沒真的跑過。
 *
 * 未涵蓋：逾時（ESLINT_TIMEOUT_MS 是 30 秒常數、無注入點）與總時間預算（40 秒），測試不等這麼久。
 * 假 HOME 只傳給子行程，不碰真實的 ~/.claude/state。
 */
import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { execFileSync, execSync } from 'child_process';
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { dirname, join } from 'path';

/** 受測 hook 的絕對路徑 */
const HOOK = join(import.meta.dir, 'post-commit-review.ts');

/** 假 eslint 的內容：記錄 `實體 cwd|argv`，exit code 取自 cwd 下的 `.fake-exit`（沒有為 0） */
const FAKE_ESLINT = `#!/bin/sh
echo "$(pwd -P)|$*" >> "$ESLINT_LOG"
code=$(cat "$(pwd -P)/.fake-exit" 2>/dev/null || echo 0)
if [ "$code" = "1" ]; then echo "src/a.js 1:1 error no-unused-vars"; fi
if [ "$code" = "2" ]; then echo "config broke: cannot read .eslintrc" >&2; fi
exit $code
`;

/** 子行程用的假 HOME */
let fakeHome = '';
/** 測試用 git repo 根目錄（實體路徑） */
let repo = '';
/** 假 eslint 的呼叫紀錄檔 */
let logFile = '';

/**
 * 在測試 repo 執行 git 指令。
 * @param args git 參數字串
 * @returns 指令 stdout
 */
const git = (args: string): string =>
  execSync(`git ${args}`, { cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });

/**
 * 在 repo 內寫檔（自動建父目錄）。
 * @param rel 相對於 repo 的路徑
 * @param content 檔案內容
 */
function put(rel: string, content: string): void {
  mkdirSync(dirname(join(repo, rel)), { recursive: true });
  writeFileSync(join(repo, rel), content, 'utf8');
}

/**
 * 在資料夾放一份假的本機 eslint。
 * @param dir 相對於 repo 的資料夾（其下建 node_modules/.bin/eslint）
 * @param exitCode 假 eslint 離開時的 exit code
 */
function installFakeEslint(dir: string, exitCode: number = 0): void {
  put(`${dir}/node_modules/.bin/eslint`, FAKE_ESLINT);
  chmodSync(join(repo, dir, 'node_modules', '.bin', 'eslint'), 0o755);
  put(`${dir}/.fake-exit`, String(exitCode));
}

/**
 * 提交指定檔案並以子行程執行 hook。
 * @param files 要 add 並 commit 的相對路徑
 * @returns hook 印出的 systemMessage；沒有輸出為 null
 */
function commitAndRunHook(files: string[]): string | null {
  // STEP 01: 提交檔案（node_modules 與 .fake-exit 不進 commit，只提交 JS 檔）
  git(`add ${files.join(' ')}`);
  git('commit -q -m change');
  /** 新 commit 的完整 hash */
  const head = git('rev-parse HEAD').trim();

  // STEP 02: 組出與真實 harness 同形的 PostToolUse 事件，以假 HOME 執行 hook；引擎固定 agent 跳過 codex 探測
  /** hook 的 stdout */
  const out = execFileSync('bun', [HOOK], {
    input: JSON.stringify({
      hook_event_name: 'PostToolUse',
      tool_name: 'Bash',
      tool_input: { command: 'git commit -m change' },
      tool_response: { stdout: `[main ${head.slice(0, 7)}] change`, stderr: '', interrupted: false },
      duration_ms: 1500,
      cwd: repo,
      session_id: 'eslint-test-session',
    }),
    encoding: 'utf8',
    env: { ...process.env, HOME: fakeHome, CLAUDE_COMMIT_REVIEW_ENGINE: 'agent', ESLINT_LOG: logFile },
  }).trim();

  // STEP 03: 取出 systemMessage
  return out ? (JSON.parse(out) as { systemMessage: string }).systemMessage : null;
}

/**
 * 讀取假 eslint 的呼叫紀錄。
 * @returns 每次呼叫一筆 `{ cwd, argv }`；從未被呼叫為空陣列
 */
function eslintCalls(): Array<{ cwd: string; argv: string }> {
  if (!existsSync(logFile)) {
    return [];
  }
  return readFileSync(logFile, 'utf8').trim().split('\n').filter(Boolean).map((l) => {
    /** 以第一個 | 切成 cwd 與 argv */
    const i = l.indexOf('|');
    return { cwd: l.slice(0, i), argv: l.slice(i + 1) };
  });
}

beforeEach(() => {
  fakeHome = mkdtempSync(join(tmpdir(), 'eslint-test-home-'));
  /** git init 用的暫存資料夾 */
  const dir = mkdtempSync(join(tmpdir(), 'eslint-test-repo-'));
  execSync('git init -q', { cwd: dir });
  repo = realpathSync(execSync('git rev-parse --show-toplevel', { cwd: dir, encoding: 'utf8' }).trim());
  logFile = join(fakeHome, 'eslint-calls.log');
  git('config user.email t@example.com');
  git('config user.name t');
  put('README.md', 'init\n');
  git('add README.md');
  git('commit -q -m init');
});

afterEach(() => {
  rmSync(repo, { recursive: true, force: true });
  rmSync(fakeHome, { recursive: true, force: true });
});

describe('post-commit-review eslint 分組：實際執行位置', () => {
  test('設定檔與本機 eslint 在子資料夾 → 在該資料夾執行，argv 是相對路徑，結果標通過', () => {
    put('app/.eslintrc.json', '{}');
    installFakeEslint('app');
    put('app/src/a.js', 'a\n');
    const message = commitAndRunHook(['app/src/a.js']);
    expect(eslintCalls()).toEqual([{ cwd: join(repo, 'app'), argv: 'src/a.js' }]);
    expect(message).toContain('✅ eslint [app]：1 檔通過');
  });

  test('兩個子專案各有設定檔與 eslint → 各組在自己的資料夾執行一次，不在 repo 根目錄跑', () => {
    put('app/.eslintrc.json', '{}');
    installFakeEslint('app');
    put('web/eslint.config.js', 'export default [];');
    installFakeEslint('web');
    put('app/src/a.js', 'a\n');
    put('web/src/b.js', 'b\n');
    const message = commitAndRunHook(['app/src/a.js', 'web/src/b.js']);
    /** 呼叫的 cwd 集合 */
    const cwds = eslintCalls().map((c) => c.cwd).sort();
    expect(cwds).toEqual([join(repo, 'app'), join(repo, 'web')]);
    expect(cwds).not.toContain(repo);
    expect(message).toContain('✅ eslint [app]：1 檔通過');
    expect(message).toContain('✅ eslint [web]：1 檔通過');
  });

  test('同一資料夾的多個檔案併成一次呼叫', () => {
    put('app/.eslintrc.json', '{}');
    installFakeEslint('app');
    put('app/src/a.js', 'a\n');
    put('app/src/c.js', 'c\n');
    commitAndRunHook(['app/src/a.js', 'app/src/c.js']);
    /** 呼叫紀錄 */
    const calls = eslintCalls();
    expect(calls).toHaveLength(1);
    expect(calls[0].argv.split(' ').sort()).toEqual(['src/a.js', 'src/c.js']);
  });
});

describe('post-commit-review eslint 分組：結果分類', () => {
  test('exit 1 → 回報「發現問題」並帶出 eslint 輸出', () => {
    put('app/.eslintrc.json', '{}');
    installFakeEslint('app', 1);
    put('app/src/a.js', 'a\n');
    const message = commitAndRunHook(['app/src/a.js']);
    expect(message).toContain('❌ eslint [app] 發現問題');
    expect(message).toContain('no-unused-vars');
  });

  test('exit 2（設定壞掉）→ 回報「未執行」並附 stderr 首行，不當成 lint 問題', () => {
    put('app/.eslintrc.json', '{}');
    installFakeEslint('app', 2);
    put('app/src/a.js', 'a\n');
    const message = commitAndRunHook(['app/src/a.js']);
    expect(message).toContain('⏭️ eslint [app]：未執行（exit 2：config broke');
    expect(message).not.toContain('❌ eslint');
  });

  test('有設定檔但找不到本機 eslint → 如實回報跳過，不呼叫任何 eslint', () => {
    put('app/.eslintrc.json', '{}');
    put('app/src/a.js', 'a\n');
    const message = commitAndRunHook(['app/src/a.js']);
    expect(eslintCalls()).toEqual([]);
    expect(message).toContain('找不到本機 eslint（node_modules/.bin/eslint），跳過 1 檔');
  });

  test('往上找不到任何設定檔 → 如實回報，不呼叫 eslint', () => {
    installFakeEslint('app');
    put('app/src/a.js', 'a\n');
    const message = commitAndRunHook(['app/src/a.js']);
    expect(eslintCalls()).toEqual([]);
    expect(message).toContain('1 檔找不到 eslint 設定檔，跳過');
  });
});
