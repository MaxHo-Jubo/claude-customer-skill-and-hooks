/**
 * pending-review marker 共用工具。
 *
 * 被四個消費端共用，統一 marker 檔案路徑與判定邏輯，避免各自複製造成分歧：
 * - scripts/post-commit-review.ts（PostToolUse：Tier 2/3 commit 後「寫入」marker）
 * - hooks/commit-gate-guard.ts（PreToolUse Bash：偵測 marker「阻擋」新 commit）
 * - scripts/clear-pending-review.ts（review 完成後「清除」marker）
 * - （未來）hooks/subagent-review-clear.ts（SubagentStop：review agent 完成後自動清除）
 *
 * 設計：marker 存在 = 該 repo 有一個 Tier 2/3 commit 的 review 尚未完成，禁止開新 commit。
 * 這是 fail-closed 強制閘門，取代舊版「靠 systemMessage 提醒但無強制力」的做法。
 */
import { homedir } from 'os';
import { join, resolve, isAbsolute } from 'path';
import { execSync } from 'child_process';

/** marker 檔案存放目錄 */
export const MARKER_DIR = join(homedir(), '.claude', 'state', 'pending-review');

/** marker 逾期門檻：超過此時間視為卡死，PreToolUse 放行並自動清除，避免永久 brick 住 commit */
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
