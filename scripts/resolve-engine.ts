#!/usr/bin/env bun
/**
 * commit-review skill 手動模式用的引擎決策 CLI。
 *
 * 與 PostToolUse hook（post-commit-review.ts）共用 lib/review-engine.ts 的 resolveEngine()，
 * 確保「被動模式（hook 在 commit 上鎖當下探測）」與「手動模式（此 CLI 在呼叫當下探測）」
 * 引擎決策單一來源、不分歧——修正手動模式先前只在 SKILL.md 文字寫死「預設 codex」、
 * 從未實際探測 codex 是否可執行的落差（2026-08-24 實測發現：codex 未安裝時手動路徑會
 * 直接判定該面向失敗、回報 Tier 降級，而非像被動模式一樣自動退回 agent）。
 *
 * 用法：
 *   bun ~/.claude/scripts/resolve-engine.ts
 *
 * 輸出（供 skill 解析的 key=value 格式）：
 *   ENGINE=codex
 *   REASON=（探測通過採預設時為空；覆寫或降級時印出原因，供 skill 原樣轉告使用者）
 */
import { resolveEngine } from './lib/review-engine';

// STEP 01: 決定本次手動 review 要用的引擎，邏輯與被動模式共用同一份 resolveEngine()
const decision = resolveEngine();

// STEP 02: 以 key=value 格式輸出，供 skill 解析；REASON 未設時輸出空字串而非省略該行，
// 讓呼叫端固定讀兩行、不必判斷該行存不存在
console.log(`ENGINE=${decision.engine}`);
console.log(`REASON=${decision.reason ?? ''}`);
