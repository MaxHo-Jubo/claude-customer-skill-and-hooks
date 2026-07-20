/**
 * Commit 分級（Tier）判定共用工具。
 *
 * 從 post-commit-review.ts 抽出，讓兩個消費端共用同一份判定邏輯，避免各自複製造成分歧：
 * - scripts/post-commit-review.ts（PostToolUse：被動，commit 後算 Tier 決定是否上鎖）
 * - scripts/compute-tier.ts（commit-review skill 手動模式：使用者主動對指定 commit 算 Tier）
 *
 * 判準對應 harness/commit-review-policy.md 的「分級判定」表——該表為本檔的實作依據，
 * 兩者須同步；本檔只做機械計算，實際 review chain 由 commit-review skill 執行。
 */
import { execSync } from 'child_process';

/**
 * Tier 0 副檔名：文件/圖片/資料檔，不算「程式碼檔」。
 * 註：呼叫端須先 `.toLowerCase()`（本清單皆為小寫，用 endsWith 比對）。
 */
export const TIER0_EXTENSIONS = ['.md', '.html', '.txt', '.png', '.jpg', '.jpeg', '.svg', '.csv'];

/**
 * 日期/流水號後綴：比對副檔名前先剝除。
 * sync-my-claude-setting skill 會產生 `CLAUDE.md.20260720` 這類日期後綴備份，
 * 直接 endsWith('.md') 會是 false，導致自家同步產物被誤算成「程式碼檔」而虛增 Tier。
 */
export const NUMERIC_SUFFIX_REGEX = /\.\d+$/;

/** Tier 1 上限：程式碼變更行數 */
export const TIER1_MAX_LINES = 50;
/** Tier 1 上限：程式碼檔案數 */
export const TIER1_MAX_FILES = 2;
/** Tier 2 上限：程式碼變更行數 */
export const TIER2_MAX_LINES = 300;
/** Tier 2 上限：程式碼檔案數 */
export const TIER2_MAX_FILES = 5;

/**
 * 動到即視為 Tier 3 的敏感路徑（公共 API / 共用 lib / 資料模型）。
 * 用 segment-aware regex：git diff 路徑相對 repo root 且無開頭斜線（如 models/x.js），
 * 故 models/lib/shared 以「行首或 /」為界比對，避免 mymodels.js 之類誤判、也不漏 repo 根層目錄。
 * 例外：`base(controller|bean|model)` 刻意不加邊界，要抓任意層的 BaseXxx，
 * 代價是 firebasemodel.js 之類誤判——方向是向上取嚴，可接受。
 * 註：呼叫端須先 `.toLowerCase()`（本 regex 無 i flag）。
 */
export const SENSITIVE_PATH_REGEX = /(^|\/)(models|lib|shared)\/|(^|\/)routes\/middlewares\/|base(controller|bean|model)/;

/** 單次 commit 的分級統計結果 */
export interface TierStats {
  /** 判定出的 Tier（0~3） */
  tier: number;
  /** 程式碼檔案數（不含 Tier 0 副檔名的檔案） */
  codeFileCount: number;
  /** 程式碼變更行數（增 + 刪） */
  codeLineCount: number;
  /** 是否動到敏感路徑（公共 API / 共用 lib / 資料模型） */
  touchesSensitive: boolean;
}

/**
 * 依 commit-review-policy.md 判準機械計算指定 commit 的分級統計。
 * 由上而下取第一個命中：Tier 0（全文件/圖片）→ Tier 3（動到敏感路徑）→
 * Tier 1（≤50 行且≤2 檔）→ Tier 2（≤300 行且≤5 檔）→ 超過則 Tier 3。
 * @param repoRoot 目標 repo 根目錄
 * @param commitRef 目標 commit（預設 HEAD），比對範圍為 <ref>~1..<ref>
 * @returns 分級統計；判定失敗（如無父 commit）時保守回傳 Tier 3（向上取嚴）
 */
export function getTierStats(repoRoot: string, commitRef: string = 'HEAD'): TierStats {
  try {
    // STEP 01: 用 numstat 取指定 commit 相對其父 commit 每個檔案的增刪行數。
    // --no-renames 必要：git 預設把 rename 併成 `old => new` 或 `dir/{a => b}/x.ts` 單列，
    // 敏感路徑 regex 會漏判「把檔案搬進 lib/」這種高 blast radius 操作（實測會誤判成 Tier 1）；
    // 關掉 rename 偵測後拆成 delete + add 兩列，兩側路徑都能各自比對。
    // stdio 忽略 stderr，與 review-marker.ts 的 resolveRepoRoot 一致，避免 git 錯訊噴進 hook 輸出。
    const numstat = execSync(`git diff --numstat --no-renames ${commitRef}~1 ${commitRef}`, {
      cwd: repoRoot,
      encoding: 'utf8',
      timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    // 空 diff = 空 commit，對應 policy 的免跑條件，與 Tier 0 同樣只需通知
    if (!numstat) {
      return { tier: 0, codeFileCount: 0, codeLineCount: 0, touchesSensitive: false };
    }

    // STEP 02: 逐行解析，分出「程式碼檔」與其變更行數
    const rows = numstat.split('\n').filter(Boolean);
    let codeFileCount = 0;
    let codeLineCount = 0;
    let touchesSensitive = false;
    for (const row of rows) {
      const [addedRaw, deletedRaw, ...pathParts] = row.split('\t');
      const filePath = pathParts.join('\t');
      const lowerPath = filePath.toLowerCase();
      // STEP 02.01: Tier 0 副檔名不算程式碼檔（先剝日期後綴，見 NUMERIC_SUFFIX_REGEX）
      const comparablePath = lowerPath.replace(NUMERIC_SUFFIX_REGEX, '');
      const isTier0 = TIER0_EXTENSIONS.some((ext) => comparablePath.endsWith(ext));
      if (isTier0) {
        continue;
      }
      // STEP 02.02: 累計程式碼檔數與變更行數（binary 檔以 '-' 表示，視為 0 行）
      codeFileCount += 1;
      const added = parseInt(addedRaw, 10) || 0;
      const deleted = parseInt(deletedRaw, 10) || 0;
      codeLineCount += added + deleted;
      // STEP 02.03: 命中敏感路徑 → 標記為需 Tier 3
      if (SENSITIVE_PATH_REGEX.test(lowerPath)) {
        touchesSensitive = true;
      }
    }

    // STEP 03: 全部都是文件/圖片 → Tier 0
    if (codeFileCount === 0) {
      return { tier: 0, codeFileCount, codeLineCount, touchesSensitive };
    }
    // STEP 04: 動到公共 API / 共用 lib / 資料模型 → Tier 3（不論大小，須先於尺寸判定，
    //          否則對 model 的小改動會先命中 Tier 1 而漏掉高 blast radius 的 review）
    if (touchesSensitive) {
      return { tier: 3, codeFileCount, codeLineCount, touchesSensitive };
    }
    // STEP 05: 小改動 → Tier 1
    if (codeLineCount <= TIER1_MAX_LINES && codeFileCount <= TIER1_MAX_FILES) {
      return { tier: 1, codeFileCount, codeLineCount, touchesSensitive };
    }
    // STEP 06: 標準改動 → Tier 2，超過門檻 → Tier 3
    if (codeLineCount <= TIER2_MAX_LINES && codeFileCount <= TIER2_MAX_FILES) {
      return { tier: 2, codeFileCount, codeLineCount, touchesSensitive };
    }
    return { tier: 3, codeFileCount, codeLineCount, touchesSensitive };
  } catch {
    // 判定失敗時向上取嚴，寧可多跑一級
    return { tier: 3, codeFileCount: 0, codeLineCount: 0, touchesSensitive: false };
  }
}

/**
 * 依 commit-review-policy.md 判準機械計算指定 commit 的 Tier。
 * getTierStats 的薄封裝，只回傳 Tier 數字，維持 post-commit-review.ts 既有呼叫端介面。
 * @param repoRoot 目標 repo 根目錄
 * @param commitRef 目標 commit（預設 HEAD）
 * @returns Tier 數字（0~3）
 */
export function computeTier(repoRoot: string, commitRef: string = 'HEAD'): number {
  return getTierStats(repoRoot, commitRef).tier;
}
