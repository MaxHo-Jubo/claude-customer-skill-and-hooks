/**
 * pending-review marker 共用工具。
 *
 * 被四個 marker 讀寫消費端共用，統一 marker 檔案路徑與判定邏輯，避免各自複製造成分歧
 * （另有 scripts/compute-tier.ts 只借用 resolveRepoRoot，不碰 marker）：
 * - scripts/post-commit-review.ts（PostToolUse：Tier 2/3 commit 後「寫入」marker）
 * - hooks/commit-gate-guard.ts（PreToolUse Bash：偵測 marker「阻擋」新 commit）
 * - hooks/stop-review-guard.ts（Stop：marker 未清時「阻擋」回合結束，強制指派 review）
 * - scripts/clear-pending-review.ts（review 完成後「清除」marker——唯一的清除路徑）
 *
 * hooks/subagent-review-clear.ts 自 2026-08-17 起只借用 MARKER_DIR 寫 debug log，不再清除 marker
 * （原「型別含 review 就清」會在 Tier 3 並行時被第一個完成的 agent 提前解鎖，詳見該檔檔頭）。
 *
 * 設計：marker 存在 = 該 repo 有一個 Tier 2/3 commit 的 review 尚未完成，
 * 禁止開新 commit、且回合不得結束。
 * 這是 fail-closed 強制閘門，取代舊版「靠 systemMessage 提醒但無強制力」的做法。
 */
import { homedir } from 'os';
import { join, resolve, isAbsolute } from 'path';
import { execSync } from 'child_process';
import { readFileSync, unlinkSync, appendFileSync, existsSync, mkdirSync, writeFileSync } from 'fs';
import type { ReviewEngine } from './review-engine';

/** marker 檔案存放目錄 */
export const MARKER_DIR = join(homedir(), '.claude', 'state', 'pending-review');

/** marker 逾期門檻：超過此時間視為卡死，閘門（commit-gate-guard / stop-review-guard）經 readValidMarker 放行並自動清除，避免永久 brick */
export const MARKER_MAX_AGE_MS = 4 * 60 * 60 * 1000;

/** pending-review marker 內容 */
export interface ReviewMarker {
  /** git repo 根目錄絕對路徑 */
  repoRoot: string;
  /** 觸發 marker 的 commit hash */
  commitHash: string;
  /** 判定出的 Tier（2 或 3） */
  tier: number;
  /** 建立時間（epoch ms），供逾期判定 */
  createdAt: number;
  /** 觸發此 marker 的 session id（Stop gate 的第一比對鍵）；舊 marker 無此欄位，optional 保持向後相容 */
  sessionId?: string;
  /**
   * 該 Tier 應跑完的 review 面向數，由 aspectsForTier() 於上鎖當下寫入（把政策釘在上鎖時點，
   * 日後改映射不影響在途 marker）。解鎖時 clear-pending-review.ts 要求 `--aspects-done=N`
   * 且 N >= 本值，不足則拒絕。
   * 存在理由：上鎖是機械的（hook 判 Tier、寫 marker、PreToolUse deny），解鎖若只靠 skill 的
   * 自然語言前置條件，等於把 fail-closed 閘門的一半退回「依賴自覺」。N 仍是自報，但把靜默省略
   * 換成顯式且留痕的斷言。
   * **刻意不設 optional**：本值是 tier 的純函數，「不知道應跑幾個」這個狀態不存在；設成 optional
   * 會在唯一為了關掉 fail-open 而做的改動上再開一條 fail-open。舊 marker（無此欄位）最多存活
   * MARKER_MAX_AGE_MS，讀取端一律用 `?? aspectsForTier(tier)` 推導，不放行。
   */
  expectedAspects: number;
  /**
   * 本輪 review 要用的執行引擎，由 resolveEngine() 於上鎖當下探測並寫入。
   * 與 expectedAspects 同樣是「把政策釘在上鎖時點」——engine 一次決定、全程一致，Stop gate
   * 之後只讀不重新探測，否則同一輪 review 可能因 codex 可用性中途變化而被指派成兩種引擎。
   * 舊 marker（本功能上線前建立）無此欄位，讀取端一律以 LEGACY_MARKER_ENGINE 推導——那是還原
   * 它們建立當下的實際行為，不是「不知道就給預設值」。
   */
  engine?: ReviewEngine;
  /**
   * Stop gate 有界保險絲：sessionId → 該 session 已被 block 的次數。
   * 採 per-session 計數而非全域單一計數：同 repo 的其他 session（尤其 skill spawn 的
   * headless claude -p）repoRoot 命中也會被 block，全域計數會被它們把額度吃光、
   * 讓主 session 免審通過。舊 marker 無此欄位，optional 保持向後相容。
   */
  stopBlockCounts?: Record<string, number>;
}

/**
 * 依 Tier 推導該跑幾個 review 面向：Tier 3 = pr-reviewer lite + 5 個 pr-review-toolkit 面向；
 * Tier 2 = 僅 lite。與 skills/commit-review/SKILL.md §3 的 Tier 對應表為同一份政策。
 *
 * 抽在此處的理由：此映射原本在 post-commit-review.ts 與兩個閘門各有一份 inline 複製，而唯一
 * 真正「擋」的 clear-pending-review.ts 一份也沒有——防護加在只負責印字的地方，該有的地方沒有
 * （CLAUDE.md EXTRACT-SHARED-HELPER 的 signal (a)）。
 * @param tier 判定出的 Tier
 * @returns 該 Tier 應完成的面向數
 */
export function aspectsForTier(tier: number): number {
  return tier >= 3 ? 6 : 1;
}

/**
 * 解析 marker 檔並做 shape guard，**不含逾期判定**。
 * 供 clear-pending-review.ts 使用——它需要對逾期 marker 也能給出明確訊息，不能用 readValidMarker
 * （後者會就地刪檔並回 null）。抽出此函式的理由：clear 腳本原本自己 JSON.parse + cast，繞過了
 * readValidMarker 的 shape guard，marker 內容為字面 `null` 時會在 try 外 TypeError crash，
 * 與兩個閘門對「什麼是有效 marker」的判定不一致——而本檔檔頭宣稱自己是該定義的唯一出處。
 * @param path marker 檔完整路徑
 * @returns 解析成功且為物件的 marker；否則 null
 */
export function readMarkerRaw(path: string): ReviewMarker | null {
  // STEP 01: 解析——壞檔回 null，不 throw 到呼叫端
  let marker: ReviewMarker;
  try {
    marker = JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
  // STEP 02: shape guard——合法 JSON 但非物件（如字面 null）同樣視為無效
  if (!marker || typeof marker !== 'object') {
    return null;
  }
  return marker;
}

/**
 * 判斷指令是否為「git commit」——包含 `git -C <path> commit`、`git -c <cfg> commit`、
 * `git --no-pager commit` 等把全域選項夾在 git 與 commit 之間的形式（使用者慣用 `git -C <repo> commit`）。
 * 用「subcommand 必須是 commit」的方式排除 `git log --grep commit`、`git show ... commit` 等把
 * commit 當參數的指令；也用負向 lookahead 排除 `git commit-tree` 之類 plumbing 子指令。
 * @param command Bash 指令字串
 * @returns 是否為 git commit 指令
 */
export function isGitCommitCommand(command: string): boolean {
  // git 必須位於「指令起始位置」（字串開頭，或 shell 分隔符 && || ; | ( 換行 之後），
  // 才不會把 `git log --grep "git commit"`、`echo git commit` 這類字串/引數裡的 git 誤判為指令。
  return /(?:^|[\n;&|(])\s*git\s+(?:-C\s+\S+\s+|-c\s+\S+\s+|--[\w-]+(?:=\S+)?\s+)*commit(?![\w-])/.test(command);
}

/**
 * 判斷指令是否包含「git push」子指令——與 isGitCommitCommand 同樣用行首/分隔符錨定，
 * 只認位於指令起始位置的 `git push`，不把 commit message 或引數裡的 "push" 字樣（如
 * `git commit -m "移除 code push 設定"`、"push notification"）誤判為 push 指令。
 * 用途：`git commit && git push` 是 policy 定義的 review 略過情境，需精確辨識 push 指令本身。
 * @param command Bash 指令字串
 * @returns 是否包含 git push 子指令
 */
export function isGitPushCommand(command: string): boolean {
  return /(?:^|[\n;&|(])\s*git\s+(?:-C\s+\S+\s+|-c\s+\S+\s+|--[\w-]+(?:=\S+)?\s+)*push(?![\w-])/.test(command);
}

/**
 * 把 repo 根目錄的絕對路徑正規化成可安全當檔名的 token。
 * 沿用專案目錄慣例：路徑分隔符換成 '-'（如 /Users/maxhero/... → -Users-maxhero-...）。
 * 抽成共用函式而非只在 markerPathForRepo 內部使用，是為了讓任何需要用 repoRoot 當檔名
 * 一部分的地方（如 codex-review.ts 的報告輸出目錄）都用同一份正規化規則——只取 basename
 * 會讓兩個 basename 相同、路徑不同的 repo 共用同一個輸出位置並互相覆寫。
 * @param repoRoot git repo 根目錄絕對路徑
 * @returns 安全可當檔名的 token
 */
export function repoRootToken(repoRoot: string): string {
  return repoRoot.replace(/[/\\]/g, '-');
}

/**
 * 依 repo 根目錄推導對應的 marker 檔案路徑。
 * @param repoRoot git repo 根目錄絕對路徑
 * @returns marker 檔案完整路徑
 */
export function markerPathForRepo(repoRoot: string): string {
  return join(MARKER_DIR, `${repoRootToken(repoRoot)}.json`);
}

/**
 * 讀取單一 marker 檔並驗證有效性（可解析且未逾期）。
 * marker「有效性」的唯一定義處——commit-gate-guard（PreToolUse）與 stop-review-guard（Stop）
 * 共用此函式，避免兩個閘門對同一顆 marker 判定分歧。
 * @param path marker 檔完整路徑
 * @param now 現在時間（epoch ms），供逾期判定
 * @returns 有效 marker；壞檔或逾期回傳 null（呼叫端一律視為「無此 marker」fail-open 放行）
 */
export function readValidMarker(path: string, now: number): ReviewMarker | null {
  // STEP 01: 解析並做 shape guard（與 clear-pending-review.ts 共用同一份判定）
  const marker = readMarkerRaw(path);
  if (!marker) {
    return null;
  }

  // STEP 02: 逾期 marker 就地清除後視為無效，避免殘留 marker 永久 brick 閘門
  if (now - (marker.createdAt || 0) > MARKER_MAX_AGE_MS) {
    // 逾期自動清除是「不經 clear 腳本」的解鎖路徑，必須留痕——否則 unlock-audit.log 裡
    // 「沒有 FORCE 紀錄」會被誤讀成「沒有未審放行」（同 CLAUDE.md HOOK-FAILURE-BLINDSPOT
    // 的「0 筆 = 沒有錯誤 vs 沒有記錄」陷阱）
    try {
      appendFileSync(
        join(MARKER_DIR, 'unlock-audit.log'),
        [new Date().toISOString(), marker.repoRoot || path, (marker.commitHash || '').slice(0, 10),
         `tier=${marker.tier}`, 'result=EXPIRED-AUTO-CLEAR',
         `age=${Math.round((now - (marker.createdAt || 0)) / 60000)}min`].join('\t') + '\n',
        'utf8',
      );
    } catch {
      // 稽核寫入失敗不改變「逾期即無效」的結論——此處是閘門讀取路徑，不可因此擋住正常 commit
    }
    try {
      unlinkSync(path);
    } catch {
      // 清除失敗不影響「視為無效」的結論
    }
    return null;
  }
  return marker;
}

/** 判定「剛才那次 commit」的 reflog 時效窗（秒）：harness 沒提供本次工具呼叫耗時（duration_ms）時的退路 */
const NEW_COMMIT_WINDOW_SEC = 120;
/** 時效窗在「本次工具呼叫耗時」之外再加的緩衝（秒）：涵蓋 hook 啟動延遲與秒數取整 */
const COMMIT_WINDOW_SLACK_SEC = 30;
/** 每秒的毫秒數 */
const MS_PER_SEC = 1000;

/**
 * 依本次工具呼叫耗時算出 reflog 時效窗，讓窗口綁定「這一次指令」而不是固定秒數：
 * `git commit -q && <超過兩分鐘的建置>` 這種指令，commit 發生在呼叫開始之後、hook 觸發之前，
 * 固定 120 秒會漏判；改用耗時 + 緩衝後，凡是本次指令內產生的 commit 都在窗內。
 * PostToolUse 的 duration_ms 涵蓋整條前景指令（2026-10-03 實測前景 `sleep 4` 回報 5910）。
 * @param durationMs 本次工具呼叫耗時（毫秒）；harness 未提供時為 null
 * @returns 時效窗（秒）
 */
export function commitWindowSec(durationMs: number | null): number {
  if (durationMs === null) {
    return NEW_COMMIT_WINDOW_SEC;
  }
  return Math.ceil(durationMs / MS_PER_SEC) + COMMIT_WINDOW_SLACK_SEC;
}

/**
 * 依 repo 根目錄推導「上次已處理 HEAD」紀錄檔路徑。副檔名刻意不用 .json，
 * stop-review-guard 以 .json 過濾 MARKER_DIR，不會把它當 marker 讀。
 * @param repoRoot git repo 根目錄絕對路徑
 * @returns 紀錄檔完整路徑
 */
export function lastSeenHeadPath(repoRoot: string): string {
  return join(MARKER_DIR, `${repoRootToken(repoRoot)}.lasthead`);
}

/**
 * 不看 git 輸出文字，改用 git 自身狀態判斷「這個 repo 剛剛是否新增了 commit」。
 * 補 `git commit -q`／`--quiet` 的洞：該旗標不印 `[branch hash]` 確認行，harness 也不提供
 * gitOperation.commit，stdout 訊號全部落空。兩個條件須同時成立：
 * (a) HEAD 的 reflog 最新一筆是 commit 類動作（含 amend／merge）且落在時效窗內；
 * (b) 目前 HEAD 與上次已處理的 HEAD 不同——擋掉已處理 commit 的重複觸發（例如失敗的重試 commit）。
 * 這是「窗內有一筆尚未處理的 commit」的啟發式判定，不能證明本次指令成功：失敗的 commit 不寫 reflog，
 * 若窗內恰有一筆 hook 沒處理過的 commit（例如手動提交），本次失敗的 commit 仍會命中那一筆。
 * 時效窗由呼叫端以 commitWindowSec(本次工具耗時) 傳入，縮到本次指令的執行期間，降低這種誤判。
 * git 指令失敗時直接拋出，由呼叫端決定如何回報，不在這裡吞掉。
 * @param repoRoot git repo 根目錄絕對路徑
 * @param windowSec reflog 時效窗（秒），預設為無耗時資訊時的退路值
 * @param nowSec 目前時間（Unix 秒），預設取系統時間，測試時可注入
 * @returns HEAD 是否為窗內產生且尚未處理過的 commit
 */
export function detectNewCommit(
  repoRoot: string,
  windowSec: number = NEW_COMMIT_WINDOW_SEC,
  nowSec: number = Math.floor(Date.now() / MS_PER_SEC),
): boolean {
  // STEP 01: 讀 HEAD reflog 最新一筆（時間用 unix 秒，格式 `HEAD@{<秒>}<TAB><動作>: <說明>`）
  const reflog = execSync('git reflog -1 --date=unix --format=%gd%x09%gs HEAD', {
    cwd: repoRoot,
    encoding: 'utf8',
    timeout: 5000,
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  const [selector = '', action = ''] = reflog.split('\t');
  const at = /@\{(\d+)\}/.exec(selector);
  if (!at || !action.startsWith('commit') || nowSec - Number(at[1]) > windowSec) {
    return false;
  }

  // STEP 02: 與上次已處理的 HEAD 比對
  const head = execSync('git rev-parse HEAD', {
    cwd: repoRoot,
    encoding: 'utf8',
    timeout: 5000,
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  const recorded = existsSync(lastSeenHeadPath(repoRoot))
    ? readFileSync(lastSeenHeadPath(repoRoot), 'utf8').trim()
    : '';
  return head !== recorded;
}

/**
 * 記錄「此 HEAD 已處理」，供 detectNewCommit 之後比對。任何路徑判定為「確實 commit 了」都要呼叫
 * （含 stdout 確認行的主要路徑），否則同一個 commit 之後會被 -q 路徑再判一次。
 * 呼叫時機須在 review 指派與 marker 寫入之後：先標記再上鎖，上鎖途中失敗就會留下「已處理」卻沒有 review。
 * 寫入失敗直接拋出，由呼叫端回報。
 * @param repoRoot git repo 根目錄絕對路徑
 * @returns void
 */
export function recordSeenHead(repoRoot: string): void {
  const head = execSync('git rev-parse HEAD', {
    cwd: repoRoot,
    encoding: 'utf8',
    timeout: 5000,
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  mkdirSync(MARKER_DIR, { recursive: true });
  writeFileSync(lastSeenHeadPath(repoRoot), head, 'utf8');
}

/**
 * 在指定工作目錄解析 git repo 根目錄。
 * @param cwd 執行 git 的工作目錄
 * @returns repo 根目錄絕對路徑；非 git 目錄或指令失敗回傳 null
 */
export function resolveRepoRoot(cwd: string): string | null {
  try {
    return execSync('git rev-parse --show-toplevel', {
      cwd,
      encoding: 'utf8',
      timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim() || null;
  } catch {
    return null;
  }
}

/**
 * 把指令中擷取到的目錄字串正規化成絕對路徑（處理 ~ 展開與相對路徑）。
 * @param dir 原始目錄字串
 * @param base 相對路徑的基準目錄
 * @returns 絕對路徑
 */
function normalizeDir(dir: string, base: string): string {
  const expanded = dir.startsWith('~') ? join(homedir(), dir.slice(1)) : dir;
  return isAbsolute(expanded) ? expanded : resolve(base, expanded);
}

/**
 * 從 Bash 指令字串解析出實際目標 repo 根目錄。
 * 優先序：`git -C <path>` > 開頭的 `cd <path> &&` > fallbackCwd。
 * 目的：`git -C /other commit` 或 `cd /other && git commit` 能對應到正確 repo，
 * 而非 hook 自身的 cwd（否則會對錯誤的 repo 上鎖 / 漏鎖）。寫入側與讀取側共用此函式以保持一致。
 * @param command Bash 指令字串
 * @param fallbackCwd 指令未指定目錄時的基準工作目錄
 * @returns 目標 repo 根目錄絕對路徑；解析不出回傳 null
 */
export function resolveRepoRootFromCommand(command: string, fallbackCwd: string): string | null {
  // STEP 01: 擷取 git -C <path>（引號或裸路徑）
  let targetDir = fallbackCwd;
  const cMatch = command.match(/\bgit\s+-C\s+(?:"([^"]+)"|'([^']+)'|(\S+))/);
  if (cMatch) {
    targetDir = normalizeDir(cMatch[1] || cMatch[2] || cMatch[3] || fallbackCwd, fallbackCwd);
  } else {
    // STEP 02: 否則看開頭是否為 cd <path> &&
    const cdMatch = command.match(/^\s*cd\s+(?:"([^"]+)"|'([^']+)'|(\S+))\s*&&/);
    if (cdMatch) {
      targetDir = normalizeDir(cdMatch[1] || cdMatch[2] || cdMatch[3] || fallbackCwd, fallbackCwd);
    }
  }
  // STEP 03: 在目標目錄解析 repo 根
  return resolveRepoRoot(targetDir);
}
