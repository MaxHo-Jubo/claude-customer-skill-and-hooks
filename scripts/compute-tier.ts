#!/usr/bin/env bun
/**
 * commit-review skill 手動模式用的 Tier 計算 CLI。
 *
 * 與 PostToolUse hook（post-commit-review.ts）共用 lib/tier.ts 的 getTierStats，
 * 確保「被動模式（hook 算）」與「手動模式（此 CLI 算）」判定邏輯單一來源、不分歧。
 *
 * 用法：
 *   bun ~/.claude/scripts/compute-tier.ts            # 對 HEAD 計算
 *   bun ~/.claude/scripts/compute-tier.ts HEAD~3     # 對指定 commit 計算
 *
 * 輸出（供 skill 解析的 key=value 格式）：
 *   TIER=2
 *   FILES=3 LINES=180 SENSITIVE=false COMMIT=<短 hash>
 */
import { execSync } from 'child_process';
import { resolveRepoRoot } from './lib/review-marker';
import { getTierStats } from './lib/tier';

// STEP 01: 目標 commit（引數優先，預設 HEAD）
const commitRef = process.argv[2] || 'HEAD';

// STEP 02: 解析當前 repo 根目錄
const repoRoot = resolveRepoRoot(process.cwd());
if (!repoRoot) {
  console.error('❌ 無法解析 git repo 根目錄，請在 repo 內執行。');
  process.exit(1);
}

// STEP 03: 驗證目標 commit 存在並取短 hash。
// ref 打錯是手動模式最常見的失誤（數錯層數、hash 貼漏一碼），必須立即失敗：
// 否則 getTierStats 會走 catch 回傳「向上取嚴」的 Tier 3，CLI 卻以 exit 0 輸出
// TIER=3 FILES=0 LINES=0 這組自相矛盾的值，skill 會對一個不存在的 commit 跑完整 chain。
let shortHash = '';
try {
  shortHash = execSync(`git rev-parse --short --verify ${commitRef}^{commit}`, {
    cwd: repoRoot,
    encoding: 'utf8',
    timeout: 5000,
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
} catch {
  console.error(`❌ 無法解析 commit「${commitRef}」，請確認 ref 是否正確。`);
  process.exit(1);
}

// STEP 04: 計算分級統計並以 key=value 格式輸出
const stats = getTierStats(repoRoot, commitRef);
console.log(`TIER=${stats.tier}`);
console.log(`FILES=${stats.codeFileCount} LINES=${stats.codeLineCount} SENSITIVE=${stats.touchesSensitive} COMMIT=${shortHash}`);
