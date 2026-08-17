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
import { readFileSync, unlinkSync, appendFileSync } from 'fs';

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
 * 依 repo 根目錄推導對應的 marker 檔案路徑。
 * 沿用專案目錄慣例：路徑分隔符換成 '-'（如 /Users/maxhero/... → -Users-maxhero-...）。
 * @param repoRoot git repo 根目錄絕對路徑
 * @returns marker 檔案完整路徑
 */
export function markerPathForRepo(repoRoot: string): string {
  const sanitized = repoRoot.replace(/[/\\]/g, '-');
  return join(MARKER_DIR, `${sanitized}.json`);
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
