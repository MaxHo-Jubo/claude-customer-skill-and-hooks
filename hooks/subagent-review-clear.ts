#!/usr/bin/env bun
/**
 * SubagentStop hook：review 類子 agent 完成時，自動清除該 repo 的 pending-review marker。
 *
 * 這是 pending-review 閘門的「便利層」——手動 clear-pending-review.ts 仍是權威解鎖方式。
 * 本 hook 只在能明確判斷「剛完成的是 review 類子 agent」時才清 marker，其餘一律不動（降級安全）：
 * agent_type 缺失或非 review → 不清；marker 不存在 → 不動。最壞情況只是「自動沒生效、手動還在」。
 *
 * 判定依據：SubagentStop payload 的 `agent_type`（含 review/reviewer，如 pr-reviewer、code-reviewer、
 * pr-review-toolkit:code-reviewer）。payload 不直接帶子 agent 的 prompt，故以型別為主要訊號。
 *
 * 每次觸發都把 agent_type 記入 debug log，供實測驗證真實型別值、必要時調校比對模式。
 * 失敗一律 fail-open（exit 0），絕不影響子 agent 或主流程。
 */
import { existsSync, unlinkSync, appendFileSync, mkdirSync } from 'fs';
import { join } from 'path';
import { markerPathForRepo, resolveRepoRoot, MARKER_DIR } from '../scripts/lib/review-marker';

/** 判定為 review 類 agent 的型別比對模式 */
const REVIEW_AGENT_PATTERN = /review/i;

let input = '';
process.stdin.setEncoding('utf8');

const stdinTimeout = setTimeout(() => { process.exit(0); }, 2000);

process.stdin.on('data', (chunk: string) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);
    /** SubagentStop payload 的 agent 型別（不同版本可能用 agent_type 或 subagent_type） */
    const agentType: string = data.agent_type || data.subagent_type || '';
    const cwd: string = data.cwd || process.cwd();

    // STEP 01: debug 記錄本次 agent_type（供實測驗證真實型別值）
    logDebug(agentType);

    // STEP 02: 僅處理 review 類 agent，其餘不動
    if (!REVIEW_AGENT_PATTERN.test(agentType)) {
      process.exit(0);
    }

    // STEP 03: 解析 repo 根目錄；解析不出來 → 不動
    const repoRoot = resolveRepoRoot(cwd);
    if (!repoRoot) {
      process.exit(0);
    }

    // STEP 04: 無 marker → 無待清除，不動
    const markerPath = markerPathForRepo(repoRoot);
    if (!existsSync(markerPath)) {
      process.exit(0);
    }

    // STEP 05: 清除 marker 並以 additionalContext 通知主 agent
    unlinkSync(markerPath);
    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'SubagentStop',
        additionalContext: `✅ review 類子 agent（${agentType}）已完成，自動清除 ${repoRoot} 的 pending-review 閘門。請確認已處理 review 發現的 Critical 問題，之後即可開新 commit。`,
      },
    }));
    process.exit(0);
  } catch {
    process.exit(0);
  }
});

/**
 * 把 SubagentStop 的 agent_type 記入 debug log，供實測驗證與調校。
 * @param agentType 本次子 agent 的型別
 */
function logDebug(agentType: string): void {
  try {
    mkdirSync(MARKER_DIR, { recursive: true });
    const logPath = join(MARKER_DIR, 'subagent-stop-debug.log');
    appendFileSync(logPath, `${new Date().toISOString()}\t${agentType || '(empty)'}\n`, 'utf8');
  } catch {
    // debug log 失敗不影響主流程
  }
}
