import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { execSync } from 'child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/** 測試用假 HOME：MARKER_DIR 在 import 時由 homedir() 決定，必須在 import 前改掉，不污染真實 state */
const FAKE_HOME = mkdtempSync(join(tmpdir(), 'review-marker-home-'));
process.env.HOME = FAKE_HOME;
const { detectNewCommit, recordSeenHead, lastSeenHeadPath, commitWindowSec } = await import('./review-marker');

/** 固定時效窗（秒）：無 duration_ms 時的退路值，與 review-marker.ts 的 NEW_COMMIT_WINDOW_SEC 一致 */
const FALLBACK_WINDOW_SEC = 120;
/** 「本次指令」耗時的測試值（毫秒）：模擬 commit 後接一段 10 分鐘建置的指令 */
const LONG_COMMAND_MS = 10 * 60 * 1000;
/** 模擬 hook 在 commit 之後多久才觸發（秒）：超過舊版固定 120 秒窗 */
const LATE_HOOK_SEC = 121;

/** 測試用 git repo 根目錄 */
let repo = '';

/** 在測試 repo 執行 git 指令 */
const git = (args: string): string => execSync(`git ${args}`, { cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });

/** 寫檔並 commit（-q：重現 hook 漏判的情境） */
const commitQuiet = (name: string, extra = ''): void => {
  writeFileSync(join(repo, name), `${name}-${Math.random()}\n`);
  git(`add ${name}`);
  git(`commit -q ${extra} -m ${name}`);
};

beforeAll(() => {
  repo = mkdtempSync(join(tmpdir(), 'review-marker-repo-'));
  git('init -q');
  git('config user.email t@example.com');
  git('config user.name t');
});

afterAll(() => {
  rmSync(repo, { recursive: true, force: true });
  rmSync(FAKE_HOME, { recursive: true, force: true });
});

describe('detectNewCommit', () => {
  test('-q commit（無任何 stdout）：HEAD 前進且 reflog 在時效窗內 → true', () => {
    commitQuiet('a.js');
    expect(detectNewCommit(repo)).toBe(true);
  });

  test('已記錄的 HEAD 不重複判定（失敗的重試 commit 不會再上鎖）', () => {
    recordSeenHead(repo);
    expect(readFileSync(lastSeenHeadPath(repo), 'utf8').trim()).toBe(git('rev-parse HEAD').trim());
    expect(detectNewCommit(repo)).toBe(false);
  });

  test('nothing to commit 失敗：不寫 reflog、HEAD 沒變 → false', () => {
    expect(() => git('commit -q -m noop')).toThrow();
    expect(detectNewCommit(repo)).toBe(false);
  });

  test('下一個 -q commit 再度判為新 commit', () => {
    commitQuiet('b.js');
    expect(detectNewCommit(repo)).toBe(true);
  });

  test('--amend 也算 commit 類動作', () => {
    recordSeenHead(repo);
    commitQuiet('c.js', '--amend');
    expect(detectNewCommit(repo)).toBe(true);
  });

  test('reflog 最新一筆是非 commit 動作（checkout）→ false', () => {
    // checkout 到上一個 commit：HEAD 與已記錄值不同、reflog 也在窗內，
    // 只剩「動作不是 commit」這一個條件能擋，拿掉 action 檢查這個案例就會轉紅
    recordSeenHead(repo);
    git('checkout -q -b other HEAD~1');
    expect(git('rev-parse HEAD').trim()).not.toBe(readFileSync(lastSeenHeadPath(repo), 'utf8').trim());
    expect(detectNewCommit(repo)).toBe(false);
  });

  test('超過時效窗的舊 commit → false（注入未來時間）', () => {
    git('checkout -q -');
    commitQuiet('d.js');
    const farFuture = Math.floor(Date.now() / 1000) + 3600;
    expect(detectNewCommit(repo, FALLBACK_WINDOW_SEC, farFuture)).toBe(false);
  });

  test('長指令：commit 後過了 121 秒 hook 才觸發，用本次耗時算出的窗仍判得到', () => {
    commitQuiet('e.js');
    const lateNow = Math.floor(Date.now() / 1000) + LATE_HOOK_SEC;
    expect(detectNewCommit(repo, FALLBACK_WINDOW_SEC, lateNow)).toBe(false);
    expect(detectNewCommit(repo, commitWindowSec(LONG_COMMAND_MS), lateNow)).toBe(true);
  });
});

describe('commitWindowSec', () => {
  test('沒有 duration_ms → 固定退路窗', () => {
    expect(commitWindowSec(null)).toBe(FALLBACK_WINDOW_SEC);
  });

  test('有 duration_ms → 耗時（無條件進位到秒）加緩衝，涵蓋整條指令', () => {
    expect(commitWindowSec(LONG_COMMAND_MS)).toBeGreaterThan(LONG_COMMAND_MS / 1000);
    expect(commitWindowSec(1)).toBeGreaterThanOrEqual(1);
  });
});

describe('recordSeenHead', () => {
  test('紀錄檔副檔名不是 .json（stop-review-guard 以 .json 過濾，不會誤當 marker 讀）', () => {
    recordSeenHead(repo);
    expect(lastSeenHeadPath(repo).endsWith('.json')).toBe(false);
    expect(existsSync(lastSeenHeadPath(repo))).toBe(true);
  });
});
