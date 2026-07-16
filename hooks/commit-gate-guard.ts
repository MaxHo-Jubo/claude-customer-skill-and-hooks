#!/usr/bin/env bun
/**
 * PreToolUse hook：pending-review 閘門。
 *
 * 當某 repo 有 Tier 2/3 commit 的 review 尚未完成（存在 pending-review marker）時，
 * 阻擋在同一 repo 開「新 commit」，強制先完成 review。取代舊版只靠 systemMessage 提醒的無強制力做法。
 *
 * 放行條件（任一成立即不阻擋）：
 * - 非 Bash 工具、或指令不含 git commit
 * - 指令含 --amend（修正正在被 review 的 commit 是 review 流程本身，允許）
 * - 指令含 push（commit and push 是 policy 定義的 review 略過情境）
 * - commit message 含 [skip-review]（明確逃生門）
 * - 無法解析 repo 根目錄（fail-open，不阻斷）
 * - 無 marker、或 marker 已逾期（逾期自動清除後放行，避免永久 brick）
 *
 * 失敗一律 fail-open（exit 0），絕不因 hook 自身錯誤而擋掉正常 commit。
 */
import { existsSync, readFileSync, unlinkSync } from 'fs';
import {
  markerPathForRepo, resolveRepoRootFromCommand, isGitCommitCommand, MARKER_MAX_AGE_MS, type ReviewMarker,
} from '../scripts/lib/review-marker';

let input = '';
process.stdin.setEncoding('utf8');

const stdinTimeout = setTimeout(() => { process.exit(0); }, 2000);

process.stdin.on('data', (chunk: string) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);

    // STEP 01: 只處理 Bash 工具
    if (data.tool_name !== 'Bash') {
      process.exit(0);
    }

    const command: string = data.tool_input?.command || '';

    // STEP 02: 非 git commit 指令 → 放行（含 git -C <path> commit 等全域選項在前的形式）
    if (!isGitCommitCommand(command)) {
      process.exit(0);
    }

    // STEP 03: amend / push / [skip-review] → 放行
    // STEP 03.01: --amend 是修正被 review 的 commit，屬 review 流程本身
    if (/--amend/.test(command)) {
      process.exit(0);
    }
    // STEP 03.02: commit and push 是 policy 定義的略過情境
    if (/push/i.test(command)) {
      process.exit(0);
    }
    // STEP 03.03: 明確逃生門
    if (/\[skip-review\]/i.test(command)) {
      process.exit(0);
    }

    // STEP 04: 解析 commit 實際目標 repo（支援 git -C / cd）；解析不出來 → fail-open 放行
    const cwd: string = data.cwd || process.cwd();
    const repoRoot = resolveRepoRootFromCommand(command, cwd);
    if (!repoRoot) {
      process.exit(0);
    }

    // STEP 05: 無 marker → 無待完成 review，放行
    const markerPath = markerPathForRepo(repoRoot);
    if (!existsSync(markerPath)) {
      process.exit(0);
    }

    // STEP 06: 讀 marker；解析失敗 → 保守放行（不因壞檔擋 commit）
    let marker: ReviewMarker;
    try {
      marker = JSON.parse(readFileSync(markerPath, 'utf8'));
    } catch {
      process.exit(0);
    }

    // STEP 07: marker 逾期 → 自動清除並「靜默放行」（exit 0），避免永久 brick 住 commit。
    // 刻意不回傳顯式 allow：顯式 allow 會 auto-approve、短路其他權限判斷；靜默 exit 0 為純中立放行。
    const age = Date.now() - (marker.createdAt || 0);
    if (age > MARKER_MAX_AGE_MS) {
      try {
        unlinkSync(markerPath);
      } catch {
        // 清除失敗不影響放行
      }
      process.exit(0);
    }

    // STEP 08: marker 有效 → deny 這次新 commit
    const reason = [
      `🔒 pending-review 閘門：Tier ${marker.tier} commit ${(marker.commitHash || '').slice(0, 10)} 的 review 尚未完成，禁止開新 commit。`,
      '',
      '請先完成該 commit 的 review（/pr-review-toolkit:review-pr 或 pr-reviewer agent），',
      '並等 review 子 agent 回報、處理完 Critical 問題後，執行以下指令解鎖：',
      '  bun ~/.claude/scripts/clear-pending-review.ts',
      '',
      '若這個 commit 確實不需要 review，在 commit message 加上 [skip-review] 即可略過本閘門。',
    ].join('\n');

    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reason,
      },
    }));
    process.exit(0);
  } catch {
    process.exit(0);
  }
});
