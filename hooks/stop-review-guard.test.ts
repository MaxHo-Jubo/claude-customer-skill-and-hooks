/**
 * stop-review-guard 回歸測試：以子行程執行真的 Stop hook（stdin 餵 Stop 事件）。
 *
 * 守的是 2026-10 週檢討修的問題：codex review 在背景跑時，Stop 閘門一再 block 只會逼模型空轉輪詢，
 * 連擋 3 次就耗盡保險絲（4 個 session 重現）。單元測試只測 isCodexReviewRunning 不夠——
 * 刪掉 hook 的 STEP 06 放行，或把計數遞增搬到放行判斷之前，單元測試仍全綠。
 * 本檔驗證 hook 本身的行為：
 * (1) codex 進行中 → 不 block、不遞增 stopBlockCounts（連續多次回合結束也不耗保險絲）
 * (2) review 結束（summary.json）、codex 靜止逾時、輸出目錄不屬於這顆 commit → 恢復 block 並計數
 * (3) 進行中期間不耗保險絲，結束後仍有完整的 MAX_STOP_BLOCKS 次攔截額度
 * 假 HOME 只傳給子行程（marker 與 codex 輸出目錄都落在假 HOME 下），不碰真實的 ~/.claude/state。
 */
import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { spawnSync } from 'child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/** hooks 目錄 */
const HOOKS = import.meta.dir;
/** 被測的 Stop hook */
const GUARD = join(HOOKS, 'stop-review-guard.ts');

/** 測試用 session id */
const SESSION = 'sess-stop-test';
/** 測試用 repo 根目錄（不需真的存在：sessionId 命中就不會解析 repoRoot） */
const REPO = '/tmp/fake-repo-for-stop-guard';
/** repoRootToken(REPO) 的結果：codex 輸出目錄在輸出根目錄下的子目錄名 */
const REPO_TOKEN = '-tmp-fake-repo-for-stop-guard';
/** 測試用完整 commit hash */
const COMMIT = '0123456789abcdef0123456789abcdef01234567';
/** codex 輸出目錄名（git short sha，取 hash 前 10 碼） */
const SHORT = COMMIT.slice(0, 10);
/** hook 的 MAX_STOP_BLOCKS：同 session 最多被 block 的次數 */
const MAX_BLOCKS = 3;
/** 超過 CODEX_RUNNING_MAX_IDLE_MS（20 分鐘）的靜止時間（毫秒），用來模擬 codex 已死 */
const STALE_MS = 25 * 60 * 1000;

/** 子行程的假 HOME */
let home = '';

/** marker 檔路徑（假 HOME 下） */
function markerPath(): string {
  return join(home, '.claude', 'state', 'pending-review', 'marker.json');
}

/** 該 commit 的 codex 輸出目錄（假 HOME 下） */
function runDir(): string {
  return join(home, '.claude', 'state', 'codex-review', REPO_TOKEN, SHORT);
}

/**
 * 寫入 pending-review marker。
 * @param counts 預先設定的 stopBlockCounts；不給則不寫此欄位
 */
function writeMarker(counts?: Record<string, number>): void {
  // STEP 01: 建目錄並寫入 Tier 3、codex 引擎的有效 marker
  mkdirSync(join(home, '.claude', 'state', 'pending-review'), { recursive: true });
  writeFileSync(markerPath(), JSON.stringify({
    repoRoot: REPO,
    commitHash: COMMIT,
    tier: 3,
    createdAt: Date.now(),
    sessionId: SESSION,
    expectedAspects: 6,
    engine: 'codex',
    ...(counts ? { stopBlockCounts: counts } : {}),
  }), 'utf8');
}

/**
 * 建立 codex 輸出目錄並放一個面向 log。
 * @param name 輸出目錄名（預設為這顆 commit 的 short sha）
 * @param ageMs 讓目錄與檔案的 mtime 回到多久以前（毫秒）；0 表示剛寫入
 */
function writeCodexRun(name: string = SHORT, ageMs: number = 0): void {
  // STEP 01: 建輸出目錄與一個面向 log
  /** 輸出目錄 */
  const dir = join(home, '.claude', 'state', 'codex-review', REPO_TOKEN, name);
  mkdirSync(dir, { recursive: true });
  /** 面向 log 檔 */
  const log = join(dir, 'aspect-rules.log');
  writeFileSync(log, 'running', 'utf8');

  // STEP 02: 把 mtime 調回 ageMs 之前（目錄與檔案都要調，isCodexReviewRunning 取兩者最新值）
  if (ageMs > 0) {
    /** 調整後的時間 */
    const past = new Date(Date.now() - ageMs);
    utimesSync(log, past, past);
    utimesSync(dir, past, past);
  }
}

/**
 * 執行一次 Stop hook。
 * @returns hook 的 stdout 解析結果（空輸出為 null）與目前 marker 內的本 session 計數
 */
function runStop(): { out: { decision?: string; reason?: string; systemMessage?: string } | null; count: number } {
  // STEP 01: 以假 HOME 子行程執行 hook，stdin 餵 Stop 事件
  /** 子行程結果 */
  const r = spawnSync('bun', [GUARD], {
    input: JSON.stringify({ hook_event_name: 'Stop', session_id: SESSION, cwd: REPO }),
    encoding: 'utf8',
    env: { ...process.env, HOME: home },
  });
  expect(r.status).toBe(0);

  // STEP 02: 解析 stdout 與 marker 內的計數
  /** stdout 去空白後的內容 */
  const text = (r.stdout || '').trim();
  /** marker 目前內容 */
  const marker = JSON.parse(readFileSync(markerPath(), 'utf8'));
  return {
    out: text === '' ? null : JSON.parse(text),
    count: marker.stopBlockCounts?.[SESSION] ?? 0,
  };
}

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), 'stop-guard-home-'));
});

afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

describe('stop-review-guard：codex review 進行中', () => {
  test('對照組：沒有 codex 輸出目錄 → block 並計數 +1', () => {
    writeMarker();
    const r = runStop();
    expect(r.out?.decision).toBe('block');
    expect(r.count).toBe(1);
  });

  test('輸出目錄剛寫入且無 summary.json → 放行、不遞增計數', () => {
    writeMarker();
    writeCodexRun();
    const r = runStop();
    expect(r.out?.decision).toBeUndefined();
    expect(r.out?.systemMessage).toContain('仍在背景執行');
    expect(r.count).toBe(0);
  });

  test('連續多次回合結束（超過保險絲上限）都放行、計數維持 0', () => {
    writeMarker();
    writeCodexRun();
    for (let i = 0; i < MAX_BLOCKS + 2; i++) {
      const r = runStop();
      expect(r.out?.decision).toBeUndefined();
      expect(r.count).toBe(0);
    }
  });

  test('進行中期間不耗保險絲：review 結束後仍有完整的 MAX_STOP_BLOCKS 次攔截', () => {
    // STEP 01: 進行中放行 4 次，計數仍為 0
    writeMarker();
    writeCodexRun();
    for (let i = 0; i < MAX_BLOCKS + 1; i++) {
      runStop();
    }
    // STEP 02: summary.json 出現（review 結束但未解鎖）→ 連續 block MAX_STOP_BLOCKS 次，之後保險絲才放行
    writeFileSync(join(runDir(), 'summary.json'), '{}', 'utf8');
    for (let i = 1; i <= MAX_BLOCKS; i++) {
      const r = runStop();
      expect(r.out?.decision).toBe('block');
      expect(r.count).toBe(i);
    }
    const fused = runStop();
    expect(fused.out?.decision).toBeUndefined();
    expect(fused.out?.systemMessage).toContain('保險絲達上限');
  });
});

describe('stop-review-guard：codex review 不算進行中 → 恢復攔截', () => {
  test('summary.json 已出現 → block 並計數 +1', () => {
    writeMarker();
    writeCodexRun();
    writeFileSync(join(runDir(), 'summary.json'), '{}', 'utf8');
    const r = runStop();
    expect(r.out?.decision).toBe('block');
    expect(r.count).toBe(1);
  });

  test('輸出目錄靜止超過 20 分鐘（codex 已死）→ block 並計數 +1', () => {
    writeMarker();
    writeCodexRun(SHORT, STALE_MS);
    const r = runStop();
    expect(r.out?.decision).toBe('block');
    expect(r.count).toBe(1);
  });

  test('輸出目錄屬於別的 commit → block 並計數 +1', () => {
    writeMarker();
    writeCodexRun('fedcba9876');
    const r = runStop();
    expect(r.out?.decision).toBe('block');
    expect(r.count).toBe(1);
  });
});
