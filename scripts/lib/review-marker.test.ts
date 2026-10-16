import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { execSync } from 'child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/**
 * 注意：Bun 的 homedir() 不跟隨執行中修改的 process.env.HOME（2026-10-03 實測，改完仍回傳真實家目錄），
 * 所以 MARKER_DIR 仍指向真實的 ~/.claude/state/pending-review，recordSeenHead 會寫進去。
 * 檔名以臨時 repo 路徑為 key，不會碰到真實 repo 的紀錄；afterAll 負責刪掉本檔寫入的那一個。
 * 需要完全隔離的 hook 層測試在 post-commit-review.test.ts，以子行程帶入 HOME。
 */
const { detectNewCommit, recordSeenHead, lastSeenHeadPath, commitWindowSec, isCodexReviewRunning, repoRootToken, CODEX_RUNNING_MAX_IDLE_MS, isGitCommitCommand, isGitPushCommand, resolveRepoRootFromCommand } = await import('./review-marker');

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
  rmSync(lastSeenHeadPath(repo), { force: true });
  rmSync(repo, { recursive: true, force: true });
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

describe('isCodexReviewRunning', () => {
  /** 受測的完整 commit hash（40 字元） */
  const FULL_HASH = 'abcdef0123456789abcdef0123456789abcdef01';
  /** codex-review.ts 輸出目錄名：git short sha（此處 10 字元，與本機 core.abbrev 實況一致） */
  const SHORT = FULL_HASH.slice(0, 10);
  /** 假 repo 根目錄（只用來推導 token 目錄名，不需真實存在） */
  const FAKE_REPO = '/fake/codex-guard-repo';
  /** 距離「最近一次寫入」多少毫秒後才判死：要小於上限才算還活著，這裡取上限前 1 分鐘 */
  const JUST_INSIDE_MS = CODEX_RUNNING_MAX_IDLE_MS - 60 * 1000;
  /** 超過上限 1 分鐘：必判為已死 */
  const JUST_OUTSIDE_MS = CODEX_RUNNING_MAX_IDLE_MS + 60 * 1000;

  /** 臨時輸出根目錄（注入給受測函式，不碰真實 ~/.claude/state/codex-review） */
  let root = '';

  /**
   * 建立 `<root>/<token>/<name>/`，並可選擇寫入檔案。
   * @param name 輸出目錄名（git short sha）
   * @param files 要在目錄內建立的檔名（內容固定為 `{}`）
   * @returns 該目錄的絕對路徑
   */
  const makeRun = (name: string, files: string[] = []): string => {
    /** 該 commit 的輸出目錄 */
    const dir = join(root, repoRootToken(FAKE_REPO), name);
    mkdirSync(dir, { recursive: true });
    for (const f of files) {
      writeFileSync(join(dir, f), '{}');
    }
    return dir;
  };

  beforeAll(() => {
    root = mkdtempSync(join(tmpdir(), 'codex-root-'));
  });

  afterAll(() => {
    rmSync(root, { recursive: true, force: true });
  });

  test('token 目錄不存在 → false', () => {
    expect(isCodexReviewRunning(FAKE_REPO, FULL_HASH, Date.now(), root)).toBe(false);
  });

  test('目錄剛建立、還沒有任何檔案（codex 剛啟動）→ true', () => {
    makeRun(SHORT);
    expect(isCodexReviewRunning(FAKE_REPO, FULL_HASH, Date.now(), root)).toBe(true);
  });

  test('有面向 log、沒有 summary.json → true；完整 hash 以前綴比對縮寫目錄名', () => {
    makeRun(SHORT, ['aspect-rules.log']);
    expect(isCodexReviewRunning(FAKE_REPO, FULL_HASH, Date.now(), root)).toBe(true);
  });

  test('靜止未超過上限 → true；超過上限 → false（注入未來時間，邊界兩側）', () => {
    expect(isCodexReviewRunning(FAKE_REPO, FULL_HASH, Date.now() + JUST_INSIDE_MS, root)).toBe(true);
    expect(isCodexReviewRunning(FAKE_REPO, FULL_HASH, Date.now() + JUST_OUTSIDE_MS, root)).toBe(false);
  });

  test('summary.json 已出現（該輪已結束）→ false', () => {
    makeRun(SHORT, ['aspect-rules.log', 'summary.json']);
    expect(isCodexReviewRunning(FAKE_REPO, FULL_HASH, Date.now(), root)).toBe(false);
  });

  test('另一個 commit 的目錄不影響：hash 不同 → false', () => {
    const other = 'fedcba9876543210fedcba9876543210fedcba98';
    expect(isCodexReviewRunning(FAKE_REPO, other, Date.now(), root)).toBe(false);
  });

  test('目錄名短於 4 字元不做前綴比對（git core.abbrev 最小值 4，更短不可能是縮寫）→ false', () => {
    makeRun('abc', ['x.log']);
    expect(isCodexReviewRunning(FAKE_REPO, FULL_HASH, Date.now(), root)).toBe(false);
  });

  test('core.abbrev=4 產生的 4 字元目錄名也是合法縮寫 → true', () => {
    // STEP 01: 建立 git 允許的最短縮寫（core.abbrev 最小值）長度的輸出目錄
    /** git core.abbrev 的最小值：測試合法縮寫的下界 */
    const MIN_ABBREVIATED_SHA_LENGTH = 4;
    makeRun(FULL_HASH.slice(0, MIN_ABBREVIATED_SHA_LENGTH), ['aspect-rules.log']);

    // STEP 02: 仍判為進行中

    expect(isCodexReviewRunning(FAKE_REPO, FULL_HASH, Date.now(), root)).toBe(true);
  });
});

describe('isGitCommitCommand／isGitPushCommand：只認真正的指令，不認引號與 heredoc 內的文字', () => {
  /** 應判為 git commit 的指令 */
  const COMMITS = [
    'git commit -m "x"',
    'git -C /tmp/r commit -q -m x',
    'git -C "/tmp/a b" commit -m x',
    'cd /tmp/r && git commit --amend --no-edit',
    'git add a && git commit -m "feat: x && y"',
    "git commit -F - <<'EOF'\nmsg\nEOF",
  ];
  /** 不應判為 git commit 的指令（commit 字樣只在文字裡） */
  const NOT_COMMITS = [
    'git status',
    'git log --grep commit',
    'echo "a && git commit -m x"',
    "echo 'a; git commit'",
    "python3 - <<'E'\n說明 `&& git commit` 誤判\nE",
    "cat <<EOF\ngit commit -m x\nEOF",
    'git commit-tree HEAD^{tree}',
  ];

  for (const c of COMMITS) {
    test(`commit：${JSON.stringify(c).slice(0, 60)}`, () => {
      expect(isGitCommitCommand(c)).toBe(true);
    });
  }
  for (const c of NOT_COMMITS) {
    test(`非 commit：${JSON.stringify(c).slice(0, 60)}`, () => {
      expect(isGitCommitCommand(c)).toBe(false);
    });
  }

  test('git push 同理：真指令命中，commit message 與 heredoc 內的 push 字樣不算', () => {
    expect(isGitPushCommand('git commit -m x && git push')).toBe(true);
    expect(isGitPushCommand('git commit -m "移除 && git push 設定"')).toBe(false);
    expect(isGitPushCommand("cat <<'E'\ngit push origin main\nE")).toBe(false);
  });
});

describe('resolveRepoRootFromCommand：引號與 heredoc 內的 git -C 不改變目標 repo', () => {
  /** 兩個互相獨立的臨時 git repo：cwd 所在的 A 與文字裡提到的 B */
  let repoA = '';
  let repoB = '';

  beforeAll(() => {
    repoA = realpathSync(mkdtempSync(join(tmpdir(), 'resolve-a-')));
    repoB = realpathSync(mkdtempSync(join(tmpdir(), 'resolve-b-')));
    execSync('git init -q', { cwd: repoA });
    execSync('git init -q', { cwd: repoB });
  });

  afterAll(() => {
    rmSync(repoA, { recursive: true, force: true });
    rmSync(repoB, { recursive: true, force: true });
  });

  test('真的 git -C <B> 指向 B', () => {
    expect(resolveRepoRootFromCommand(`git -C ${repoB} commit -m x`, repoA)).toBe(repoB);
  });

  test('帶引號的真 git -C 路徑也能讀出', () => {
    expect(resolveRepoRootFromCommand(`git -C "${repoB}" commit -m x`, repoA)).toBe(repoB);
  });

  test('heredoc 說明文字裡的 git -C <B> 不算 → 仍回 cwd 的 A', () => {
    /** 說明文字提到 B 的 git -C，但真正的指令是在 A 做的 */
    const command = `python3 - <<'E'\nnote: git -C ${repoB} status\nE\ngit commit -m x`;
    expect(resolveRepoRootFromCommand(command, repoA)).toBe(repoA);
  });

  test('引號引數裡的 git -C <B> 不算 → 仍回 A', () => {
    expect(resolveRepoRootFromCommand(`echo "git -C ${repoB} x" && git commit -m y`, repoA)).toBe(repoA);
  });
});
