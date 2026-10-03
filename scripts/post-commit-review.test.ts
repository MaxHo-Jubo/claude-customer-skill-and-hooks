import { afterAll, beforeAll, beforeEach, describe, expect, test } from 'bun:test';
import { execFileSync, execSync } from 'child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/**
 * post-commit-review hook 的回歸測試：以子行程執行真的 hook（stdin 餵 PostToolUse 事件），
 * 驗證 `git commit -q` 會上鎖、失敗重試不重複上鎖、HEAD 紀錄與判定失敗都會回報而不是靜默略過。
 * 假 HOME 只傳給子行程，不改動測試行程本身的環境。
 */

/** 受測 hook 的絕對路徑 */
const HOOK = join(import.meta.dir, 'post-commit-review.ts');
/** 模擬 harness 回報的本次工具呼叫耗時（毫秒） */
const DURATION_MS = 1500;

/** 子行程用的假 HOME：marker 與 .lasthead 都寫在這裡 */
let fakeHome = '';
/** 測試用 git repo 根目錄（git rev-parse 的結果，macOS 上會是 /private/var/...） */
let repo = '';

/**
 * 在測試 repo 執行 git 指令。
 * @param args git 參數字串
 * @returns 指令 stdout
 */
const git = (args: string): string =>
  execSync(`git ${args}`, { cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });

/**
 * 推導 hook 在假 HOME 下的狀態檔路徑（與 review-marker.ts 的 repoRootToken 規則相同）。
 * @param ext 副檔名（`.json` 為 marker、`.lasthead` 為已處理 HEAD）
 * @returns 狀態檔絕對路徑
 */
const statePath = (ext: string): string =>
  join(fakeHome, '.claude', 'state', 'pending-review', `${repo.replace(/[/\\]/g, '-')}${ext}`);

/**
 * 以子行程執行 hook，模擬一次 Bash 工具呼叫結束後的 PostToolUse 事件。
 * @param command 該次 Bash 指令
 * @param stdout 該次指令的 stdout（-q commit 為空字串）
 * @returns hook 印出的 systemMessage；沒有輸出時為 null
 */
const runHook = (command: string, stdout: string): string | null => {
  // STEP 01: 組出與真實 harness 同形的事件（2026-10-03 以 --settings 探針實測欄位）
  const event = {
    hook_event_name: 'PostToolUse',
    tool_name: 'Bash',
    tool_input: { command },
    tool_response: { stdout, stderr: '', interrupted: false },
    duration_ms: DURATION_MS,
    cwd: repo,
    session_id: 'test-session',
  };
  // STEP 02: 執行 hook；引擎固定為 agent，跳過 codex 探測
  const out = execFileSync('bun', [HOOK], {
    input: JSON.stringify(event),
    encoding: 'utf8',
    env: { ...process.env, HOME: fakeHome, CLAUDE_COMMIT_REVIEW_ENGINE: 'agent' },
  }).trim();
  // STEP 03: 取出 systemMessage
  return out ? (JSON.parse(out) as { systemMessage: string }).systemMessage : null;
};

/**
 * 以 -q 提交一個 lib/ 下的檔案（敏感路徑，Tier 3 才會寫 marker）。
 * @param name 檔名（放在 lib/ 下）
 * @returns 新 commit 的完整 hash
 */
const quietCommit = (name: string): string => {
  writeFileSync(join(repo, 'lib', name), `${name}-${Math.random()}\n`);
  git(`add lib/${name}`);
  git(`commit -q -m ${name}`);
  return git('rev-parse HEAD').trim();
};

beforeAll(() => {
  fakeHome = mkdtempSync(join(tmpdir(), 'post-commit-home-'));
  const dir = mkdtempSync(join(tmpdir(), 'post-commit-repo-'));
  execSync('git init -q', { cwd: dir });
  repo = execSync('git rev-parse --show-toplevel', { cwd: dir, encoding: 'utf8' }).trim();
  git('config user.email t@example.com');
  git('config user.name t');
  mkdirSync(join(repo, 'lib'));
  writeFileSync(join(repo, 'README.md'), 'init\n');
  git('add README.md');
  git('commit -q -m init');
});

beforeEach(() => {
  rmSync(statePath('.json'), { force: true });
  rmSync(statePath('.lasthead'), { recursive: true, force: true });
});

afterAll(() => {
  rmSync(repo, { recursive: true, force: true });
  rmSync(fakeHome, { recursive: true, force: true });
});

describe('post-commit-review hook：-q commit', () => {
  test('stdout 為空、沒有 gitOperation 的 -q commit → 寫入 marker 並指派 review', () => {
    const head = quietCommit('a.py');
    const message = runHook('git commit -q -m a.py', '');
    expect(message).toContain('Skill(commit-review)');
    expect(message).toContain('tier=3');
    const marker = JSON.parse(readFileSync(statePath('.json'), 'utf8')) as { commitHash: string; repoRoot: string };
    expect(marker.commitHash).toBe(head);
    expect(marker.repoRoot).toBe(repo);
    expect(readFileSync(statePath('.lasthead'), 'utf8').trim()).toBe(head);
  });

  test('已處理的 HEAD 上失敗重試（nothing to commit）→ 不再上鎖、不輸出', () => {
    quietCommit('b.py');
    expect(runHook('git commit -q -m b.py', '')).toContain('Skill(commit-review)');
    rmSync(statePath('.json'));
    expect(() => git('commit -q -m retry')).toThrow();
    expect(runHook('git commit -q -m retry', '')).toBeNull();
    expect(existsSync(statePath('.json'))).toBe(false);
  });
});

describe('post-commit-review hook：失敗要回報，不可靜默略過', () => {
  test('HEAD 紀錄寫不進去 → 仍寫 marker、仍指派 review，並在訊息中警告', () => {
    const head = quietCommit('c.py');
    mkdirSync(statePath('.lasthead'), { recursive: true });
    const message = runHook('git commit -m c.py', `[main ${head.slice(0, 7)}] c.py`);
    expect(message).toContain('Skill(commit-review)');
    expect(message).toContain('無法記錄已處理的 HEAD');
    expect(existsSync(statePath('.json'))).toBe(true);
  });

  test('-q 路徑的 git 狀態判定失敗 → 輸出警告請手動 review，不靜默結束', () => {
    quietCommit('d.py');
    mkdirSync(statePath('.lasthead'), { recursive: true });
    const message = runHook('git commit -q -m d.py', '');
    expect(message).toContain('無法以 git 狀態判定是否產生新 commit');
    expect(message).toContain('/commit-review');
  });
});
