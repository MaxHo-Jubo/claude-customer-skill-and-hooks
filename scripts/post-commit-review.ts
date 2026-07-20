#!/usr/bin/env bun
import { execSync } from 'child_process';
import { writeFileSync, mkdirSync } from 'fs';
import {
  MARKER_DIR, markerPathForRepo, resolveRepoRootFromCommand, isGitCommitCommand, isGitPushCommand, type ReviewMarker,
} from './lib/review-marker';
import { computeTier } from './lib/tier';

/**
 * PostToolUse hook：git commit 後依 commit-review-policy.md 機械判定 Tier，
 * Tier 2/3 寫入 pending-review marker，交由 PreToolUse commit-gate-guard 強制阻擋下一個 commit。
 *
 * 設計沿革：舊版只靠這個 hook 的 systemMessage 提醒「應執行 review」，但 systemMessage 無強制力，
 * 主 agent 可以無視它直接開下一個 commit（ERPD-11970 b4eee29e0e 即如此，review 被跳過）。
 * 現改為「Tier 判定進腳本 + marker + PreToolUse deny」的 fail-closed 閘門，不再依賴自覺。
 *
 * 職責分工：本 hook 只負責「偵測 commit + 機械判 Tier + 上鎖」；實際 review chain（eslint/simplify/
 * pr-reviewer/review-pr/blast radius/通知）已收斂到 commit-review skill，systemMessage 只負責指派。
 * Tier 判定邏輯抽在 lib/tier.ts，與 skill 手動模式（compute-tier.ts）共用同一份，避免分歧。
 *
 * 觸發條件：Bash 執行的命令包含 `git commit`
 * 例外：命令包含 `git push` 子指令（commit and push 場景跳過）
 */

/** hook 的 stdin JSON 資料 */
let input = '';
process.stdin.setEncoding('utf8');

/** stdin 超時防呆：2 秒內未收到資料則靜默退出 */
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

    // STEP 02: 確認是 git commit 命令（含 git -C <path> commit 等全域選項在前的形式）
    if (!isGitCommitCommand(command)) {
      process.exit(0);
    }

    // STEP 03: 例外 — 命令包含 git push 子指令則跳過（精確辨識，非 message 裡的 "push" 字樣）
    if (isGitPushCommand(command)) {
      process.exit(0);
    }

    // STEP 04: 確認確實產生了「新 commit」，而非只是指令字串含 git commit。
    // 主要訊號：Bash 工具回傳的 tool_response.gitOperation.commit.kind === 'committed'（harness 結構化訊號，
    // 最可靠）。備援訊號：stdout 含 git 成功確認行 "[branch hash] message"。
    // 注意：真實 harness 的指令輸出在 tool_response.stdout，並無 tool_output 欄位（舊版誤用 tool_output，
    // 因只做負向檢查而未被發現；此處寫 marker 需要正確欄位）。
    const toolResponse = data.tool_response || {};
    const output = typeof toolResponse.stdout === 'string'
      ? toolResponse.stdout
      : (typeof data.tool_output === 'string' ? data.tool_output : '');

    /** git commit 成功時印出的確認行：[分支名 或 detached/root 敘述 + 短 hash] */
    const COMMIT_CONFIRM_PATTERN = /\[[^\]]+\s+[0-9a-f]{7,40}\]/;
    /** harness 對 git commit 的結構化結果（存在且 kind=committed 代表確實產生 commit） */
    const gitCommit = toolResponse.gitOperation?.commit;
    const committed = (gitCommit && gitCommit.kind === 'committed')
      || COMMIT_CONFIRM_PATTERN.test(output);
    if (!committed) {
      process.exit(0);
    }

    // STEP 05: 解析 commit 實際目標 repo（支援 git -C / cd 到其他 repo），寫入與讀取側共用同一解析。
    // fallback cwd 用 data.cwd || process.cwd()，與 commit-gate-guard（讀取側）對齊，
    // 否則沒有 git -C / cd 的一般 commit 會因兩側 base 不同而算出不同 repo → marker 鎖錯/漏鎖。
    const repoRoot = resolveRepoRootFromCommand(command, data.cwd || process.cwd());

    // STEP 06: 取得本次 commit 修改的檔案（在目標 repo 內查詢）
    let changedFiles: string[] = [];
    if (repoRoot) {
      try {
        /** 從最近一次 commit 取得修改的 JS/TS 檔案清單 */
        const filesRaw = execSync('git diff --name-only HEAD~1 HEAD -- "*.js" "*.jsx" "*.ts" "*.tsx"', {
          cwd: repoRoot,
          encoding: 'utf8',
          timeout: 5000
        }).trim();
        changedFiles = filesRaw ? filesRaw.split('\n').filter(Boolean) : [];
      } catch {
        changedFiles = [];
      }
    }

    // STEP 07: 對修改的檔案執行 eslint
    let eslintResult = '';
    if (repoRoot && changedFiles.length > 0) {
      try {
        execSync(`npx eslint ${changedFiles.join(' ')}`, {
          cwd: repoRoot,
          encoding: 'utf8',
          timeout: 30000
        });
        /** eslint 通過，無錯誤 */
        eslintResult = '✅ eslint: 全部通過';
      } catch (e: unknown) {
        /** eslint 有錯誤，擷取輸出 */
        const err = e as { stdout?: string; message?: string };
        eslintResult = '❌ eslint 發現問題:\n' + (err.stdout || err.message || '').slice(0, 2000);
      }
    } else {
      eslintResult = '⏭️ eslint: 無 JS/TS 檔案變更，跳過';
    }

    // STEP 08: 機械判定 Tier（不再由主 agent 憑感覺分級）
    const tier = repoRoot ? computeTier(repoRoot) : 0;

    // STEP 09: Tier 2/3 寫入 pending-review marker，供 PreToolUse 閘門阻擋下一個 commit。
    // 例外：命令含 [skip-review] 或 --amend 時不寫（與 commit-gate-guard 放行條件對稱，
    // 否則 skip-review 的 commit 雖自身放行，卻仍替下一個 commit 上鎖）。
    let gateNote = '';
    const skipMarker = /\[skip-review\]/i.test(command) || /--amend/.test(command);
    if (tier >= 2 && repoRoot && !skipMarker) {
      gateNote = writeMarker(tier, repoRoot);
    }

    // STEP 10: 依 Tier 輸出對應 systemMessage
    console.log(JSON.stringify({
      systemMessage: buildMessage(tier, eslintResult, gateNote),
    }));
  } catch {
    process.exit(0);
  }
});

/**
 * 寫入 pending-review marker 檔。
 * @param tier 本次 commit 的 Tier（2 或 3）
 * @param repoRoot 目標 repo 根目錄
 * @returns 給 systemMessage 用的閘門說明字串；寫入失敗回傳空字串（fail-open，不阻斷）
 */
function writeMarker(tier: number, repoRoot: string): string {
  try {
    // STEP 01: 取得目標 repo 的 commit hash
    const commitHash = execSync('git rev-parse HEAD', {
      cwd: repoRoot,
      encoding: 'utf8',
      timeout: 5000,
    }).trim();

    // STEP 02: 寫入 marker
    mkdirSync(MARKER_DIR, { recursive: true });
    const marker: ReviewMarker = {
      repoRoot,
      commitHash,
      tier,
      createdAt: Date.now(),
    };
    writeFileSync(markerPathForRepo(repoRoot), JSON.stringify(marker, null, 2), 'utf8');

    // STEP 03: 回傳閘門狀態說明
    return [
      '',
      `🔒 已寫入 pending-review 閘門（Tier ${tier}，commit ${commitHash.slice(0, 10)}）。`,
      '在完成 review 前，此 repo 的「新 commit」會被 PreToolUse 阻擋。',
      'review 完成後執行：bun ~/.claude/scripts/clear-pending-review.ts',
    ].join('\n');
  } catch {
    return '';
  }
}

/**
 * 依 Tier 組出 systemMessage 內容。
 * @param tier Tier 數字
 * @param eslintResult eslint 執行結果字串
 * @param gateNote 閘門說明字串（Tier 2/3 才有值）
 * @returns 完整 systemMessage
 */
function buildMessage(tier: number, eslintResult: string, gateNote: string): string {
  // STEP 01: Tier 0 純文件，只需通知，不經 skill
  if (tier === 0) {
    return `📋 Post-commit（Tier 0 純文件）\n\n${eslintResult}\n\n只需通知，無需 review。`;
  }
  // STEP 02: Tier 1~3 一律交給 commit-review skill 執行對應 chain。
  // 步驟明細收斂在 skill（不再於此列舉，避免 hook 字串／skill／policy 三處分歧）：
  // Tier 1 不 spawn agent、Tier 2/3 跑 pr-reviewer／review-pr。tier 由本 hook 算好帶入，
  // skill 被動模式直接採用不重算（判定單一來源）；eslint 結果一併附上供 skill 據以修正。
  return [
    `📋 Post-commit（Tier ${tier}）`,
    '',
    eslintResult,
    '',
    `Claude 應執行 commit-review skill 跑 Tier ${tier} 的 review chain：`,
    `  Skill(commit-review) args: "tier=${tier} target=HEAD"`,
    gateNote,
  ].join('\n');
}
