#!/usr/bin/env bun
import { execSync } from 'child_process';
import { writeFileSync, mkdirSync } from 'fs';
import {
  MARKER_DIR, markerPathForRepo, resolveRepoRootFromCommand, isGitCommitCommand, type ReviewMarker,
} from './lib/review-marker';

/**
 * PostToolUse hook：git commit 後依 commit-review-policy.md 機械判定 Tier，
 * Tier 2/3 寫入 pending-review marker，交由 PreToolUse commit-gate-guard 強制阻擋下一個 commit。
 *
 * 設計沿革：舊版只靠這個 hook 的 systemMessage 提醒「應執行 review」，但 systemMessage 無強制力，
 * 主 agent 可以無視它直接開下一個 commit（ERPD-11970 b4eee29e0e 即如此，review 被跳過）。
 * 現改為「Tier 判定進腳本 + marker + PreToolUse deny」的 fail-closed 閘門，不再依賴自覺。
 *
 * 觸發條件：Bash 執行的命令包含 `git commit`
 * 例外：命令同時包含 `push`（commit and push 場景跳過）
 */

/** Tier 0 副檔名：文件/圖片/資料檔，不算「程式碼檔」 */
const TIER0_EXTENSIONS = ['.md', '.html', '.txt', '.png', '.jpg', '.jpeg', '.svg', '.csv'];

/** Tier 1 上限：程式碼變更行數 */
const TIER1_MAX_LINES = 50;
/** Tier 1 上限：程式碼檔案數 */
const TIER1_MAX_FILES = 2;
/** Tier 2 上限：程式碼變更行數 */
const TIER2_MAX_LINES = 300;
/** Tier 2 上限：程式碼檔案數 */
const TIER2_MAX_FILES = 5;

/**
 * 動到即視為 Tier 3 的敏感路徑（公共 API / 共用 lib / 資料模型）。
 * 用 segment-aware regex：git diff 路徑相對 repo root 且無開頭斜線（如 models/x.js），
 * 故 models/lib/shared 以「行首或 /」為界比對，避免 mymodels.js 之類誤判、也不漏 repo 根層目錄。
 */
const SENSITIVE_PATH_REGEX = /(^|\/)(models|lib|shared)\/|(^|\/)routes\/middlewares\/|base(controller|bean|model)/;

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

    // STEP 03: 例外 — 命令包含 push 則跳過
    if (command.match(/push/i)) {
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

    // STEP 05: 解析 commit 實際目標 repo（支援 git -C / cd 到其他 repo），寫入與讀取側共用同一解析
    const repoRoot = resolveRepoRootFromCommand(command, process.cwd());

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

    // STEP 09: 依 Tier 輸出對應 systemMessage
    console.log(JSON.stringify({
      systemMessage: buildMessage(tier, eslintResult, gateNote),
    }));
  } catch {
    process.exit(0);
  }
});

/**
 * 依 commit-review-policy.md 判準機械計算本次 commit 的 Tier。
 * 由上而下取第一個命中：Tier 0（全文件/圖片）→ Tier 3（動到敏感路徑）→
 * Tier 1（≤50 行且≤2 檔）→ Tier 2（≤300 行且≤5 檔）→ 超過則 Tier 3。
 * @param repoRoot 目標 repo 根目錄
 * @returns Tier 數字（0~3）；判定失敗時保守回傳 3（向上取嚴）
 */
function computeTier(repoRoot: string): number {
  try {
    // STEP 01: 用 numstat 取每個檔案的增刪行數
    const numstat = execSync('git diff --numstat HEAD~1 HEAD', {
      cwd: repoRoot,
      encoding: 'utf8',
      timeout: 5000,
    }).trim();
    if (!numstat) {
      return 0;
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
      // STEP 02.01: Tier 0 副檔名不算程式碼檔
      const isTier0 = TIER0_EXTENSIONS.some((ext) => lowerPath.endsWith(ext));
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
      return 0;
    }
    // STEP 04: 動到公共 API / 共用 lib / 資料模型 → Tier 3（不論大小，須先於尺寸判定，
    //          否則對 model 的小改動會先命中 Tier 1 而漏掉高 blast radius 的 review）
    if (touchesSensitive) {
      return 3;
    }
    // STEP 05: 小改動 → Tier 1
    if (codeLineCount <= TIER1_MAX_LINES && codeFileCount <= TIER1_MAX_FILES) {
      return 1;
    }
    // STEP 06: 標準改動 → Tier 2，超過門檻 → Tier 3
    if (codeLineCount <= TIER2_MAX_LINES && codeFileCount <= TIER2_MAX_FILES) {
      return 2;
    }
    return 3;
  } catch {
    // 判定失敗時向上取嚴，寧可多跑一級
    return 3;
  }
}

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
  // STEP 01: Tier 0 只需通知
  if (tier === 0) {
    return `📋 Post-commit（Tier 0 純文件）\n\n${eslintResult}\n\n只需通知，無需 review。`;
  }
  // STEP 02: Tier 1 跑 eslint + 自查 DoD，不 spawn agent
  if (tier === 1) {
    return `📋 Post-commit（Tier 1 小改動）\n\n${eslintResult}\n\nClaude 應：修正 eslint 錯誤（如有）→ 自查 judgment-matrix.md §2 對應 DoD checklist → 通知。不 spawn agent。`;
  }
  // STEP 03: Tier 2/3 需跑完整 review chain，且已被閘門鎖住
  const reviewSteps = tier === 3
    ? 'eslint 修正（如有）→ /simplify → pr-reviewer agent → /pr-review-toolkit:review-pr code comments errors tests types → 修 Critical → blast radius → 通知'
    : 'eslint 修正（如有）→ /simplify → pr-reviewer agent（lite）→ 修 CRITICAL（amend）→ blast radius → 通知';
  return `📋 Post-commit（Tier ${tier}）\n\n${eslintResult}\n\nClaude 應自動執行：${reviewSteps}${gateNote}`;
}
