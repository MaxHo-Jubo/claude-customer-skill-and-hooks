#!/usr/bin/env bun
/**
 * 唯讀列出目前有效（未逾期）的 pending-review marker，輸出 JSON 給 review-band mod 顯示。
 *
 * 判準與閘門一致：
 * - 「有效」= readMarkerRaw 解析得出物件 + isMarkerExpired 為 false，兩者都是閘門（readValidMarker）用的同一份函式。
 *   閘門不檢查 repoRoot／tier 等欄位，所以格式不完整但未逾期的 marker 照樣列出（閘門照樣會擋），缺的欄位記在 missing。
 * - invalid 只收 readMarkerRaw 回 null 的檔（閘門同樣視為無 marker 放行）。
 * 刻意不用 readValidMarker：它會就地刪除逾期 marker 並寫 unlock-audit.log，顯示用的讀取不能有副作用。
 *
 * 輸出：PendingReviewListing（契約定義在 mods/review-band/types/index.d.ts，產生端與消費端共用）。
 * marker 目錄不存在視為沒有 marker（從未上鎖過）。
 * 失敗：讀目錄失敗等非預期錯誤 → stderr + exit 1，讓 mod 顯示「讀取失敗」而不是當成沒有 marker。
 */
import { existsSync, readdirSync } from 'fs';
import { basename, join } from 'path';
import type { PendingReview, PendingReviewListing } from '../mods/review-band/types';
import { LEGACY_MARKER_ENGINE } from './lib/review-engine';
import type { ReviewMarker } from './lib/review-marker';
import { MARKER_DIR, aspectsForTier, isMarkerExpired, readMarkerRaw } from './lib/review-marker';

/** commit hash 顯示長度 */
const COMMIT_SHORT_LEN = 7;

/**
 * 把一顆未逾期的 marker 轉成顯示資料；缺漏或型別不符的欄位設為 null 並記入 missing，不以預設值掩蓋。
 * @param file - marker 檔名
 * @param m - readMarkerRaw 解析出的 marker
 * @returns 顯示資料
 */
function toPendingReview(file: string, m: ReviewMarker): PendingReview {
  // STEP 01: 逐欄位檢查型別
  /** 缺漏或型別不符的欄位 */
  const missing: string[] = [];
  /** repo 根目錄 */
  const repoRoot = typeof m.repoRoot === 'string' ? m.repoRoot : null;
  if (repoRoot === null) {
    missing.push('repoRoot');
  }
  /** commit hash */
  const commit = typeof m.commitHash === 'string' ? m.commitHash.slice(0, COMMIT_SHORT_LEN) : null;
  if (commit === null) {
    missing.push('commitHash');
  }
  /** Tier */
  const tier = typeof m.tier === 'number' ? m.tier : null;
  if (tier === null) {
    missing.push('tier');
  }
  // STEP 02: 組出顯示資料；舊 marker 缺 engine／expectedAspects 時依閘門同一套規則推導
  return {
    file,
    repo: repoRoot === null ? null : basename(repoRoot),
    repoRoot,
    commit,
    tier,
    engine: m.engine ?? LEGACY_MARKER_ENGINE,
    expectedAspects: typeof m.expectedAspects === 'number' ? m.expectedAspects : tier === null ? null : aspectsForTier(tier),
    createdAt: m.createdAt,
    sessionId: typeof m.sessionId === 'string' ? m.sessionId : null,
    missing,
  };
}

try {
  // STEP 01: 目錄不存在 → 沒有 marker
  /** 輸出結果 */
  const listing: PendingReviewListing = { markers: [], invalid: [] };
  if (existsSync(MARKER_DIR)) {
    // STEP 02: 逐一解析 marker 檔（.lasthead、log 等非 marker 檔不在範圍）
    /** 現在時間（epoch ms） */
    const now = Date.now();
    for (const name of readdirSync(MARKER_DIR).filter(n => n.endsWith('.json'))) {
      /** 解析出的 marker；壞檔為 null */
      const m = readMarkerRaw(join(MARKER_DIR, name));
      if (!m) {
        listing.invalid.push(name);
        continue;
      }
      // STEP 02.01: 逾期的 marker 閘門已不再擋，不顯示（也不刪，刪除由閘門負責）
      if (isMarkerExpired(m, now)) {
        continue;
      }
      listing.markers.push(toPendingReview(name, m));
    }
  }
  // STEP 03: 輸出
  console.log(JSON.stringify(listing));
} catch (err) {
  console.error(`list-pending-review: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
}
