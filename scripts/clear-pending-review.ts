#!/usr/bin/env bun
/**
 * 清除 pending-review marker，解鎖該 repo 的 commit 閘門。
 *
 * 用途：Tier 2/3 commit 的 review 完成、Critical 問題處理完後執行此腳本，
 * 之後才能在該 repo 開新 commit（commit-gate-guard 會放行）。
 *
 * 用法：
 *   bun ~/.claude/scripts/clear-pending-review.ts            # 清除當前 repo 的 marker
 *   bun ~/.claude/scripts/clear-pending-review.ts /path/repo # 清除指定 repo 的 marker
 */
import { existsSync, unlinkSync, readFileSync } from 'fs';
import { markerPathForRepo, resolveRepoRoot, type ReviewMarker } from './lib/review-marker';

// STEP 01: 決定目標 repo（引數優先，否則用當前工作目錄解析）
const argRepo = process.argv[2];
const repoRoot = argRepo ? resolveRepoRoot(argRepo) : resolveRepoRoot(process.cwd());

if (!repoRoot) {
  console.error('❌ 無法解析 git repo 根目錄，請在 repo 內執行或帶入 repo 路徑引數。');
  process.exit(1);
}

// STEP 02: marker 不存在 → 無需清除
const markerPath = markerPathForRepo(repoRoot);
if (!existsSync(markerPath)) {
  console.log(`ℹ️  ${repoRoot} 沒有 pending-review marker，無需清除。`);
  process.exit(0);
}

// STEP 03: 讀出 marker 內容供確認，再刪除
try {
  const marker: ReviewMarker = JSON.parse(readFileSync(markerPath, 'utf8'));
  unlinkSync(markerPath);
  console.log(`✅ 已清除 pending-review 閘門：Tier ${marker.tier} commit ${(marker.commitHash || '').slice(0, 10)}（${repoRoot}）。現在可以開新 commit。`);
} catch (err) {
  console.error('❌ 清除 marker 失敗：', err instanceof Error ? err.message : String(err));
  process.exit(1);
}
