#!/usr/bin/env bun
import { execSync } from 'child_process';
import { writeFileSync, mkdirSync } from 'fs';
import { MARKER_DIR, markerPathForRepo, resolveRepoRootFromCommand, isGitCommitCommand, isGitPushCommand, type ReviewMarker, aspectsForTier } from './lib/review-marker';
import { computeTier } from './lib/tier';
import { resolveEngine, buildSkillInvocation, type EngineDecision, type ReviewEngine } from './lib/review-engine';

/**
 * PostToolUse hook：git commit 後依 commit-review-policy.md 機械判定 Tier，
 * Tier 2/3 寫入 pending-review marker，交由 PreToolUse commit-gate-guard 強制阻擋下一個 commit、
 * Stop stop-review-guard 阻擋回合結束。
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
        // 檔名逐一 quote：含空白的路徑不 quote 會被 shell 拆成多個引數
        const quotedFiles = changedFiles.map((f) => `'${f.replace(/'/g, `'\\''`)}'`).join(' ');
        execSync(`npx eslint ${quotedFiles}`, {
          cwd: repoRoot,
          encoding: 'utf8',
          timeout: 30000,
          stdio: ['ignore', 'pipe', 'ignore'],
        });
        /** eslint 通過，無錯誤 */
        eslintResult = '✅ eslint: 全部通過';
      } catch (e: unknown) {
        /** eslint 非 0 離開：status 1 才是真的抓到 lint 問題 */
        const err = e as { stdout?: string; message?: string; status?: number };
        if (err.status === 1) {
          eslintResult = '❌ eslint 發現問題:\n' + (err.stdout || '').slice(0, 2000);
        } else {
          // status 2（缺 eslint.config.*）/ 127（未安裝）等屬環境問題，不是程式碼問題。
          // 報成「發現問題」會讓 Claude 去修不存在的 lint 錯誤（本 repo 無 config，實測踩到）。
          eslintResult = `⏭️ eslint: 未執行（無設定檔或工具不可用，exit ${err.status ?? '?'}），跳過`;
        }
      }
    } else if (!repoRoot) {
      // 與「確實沒有 JS/TS 變更」區分：這裡是根本沒查成，不可謊稱已檢查過
      eslintResult = '⚠️ eslint: 無法解析目標 repo，未執行';
    } else {
      eslintResult = '⏭️ eslint: 無 JS/TS 檔案變更，跳過';
    }

    // STEP 08: 機械判定 Tier（不再由主 agent 憑感覺分級）。
    // repoRoot 解析失敗 → null 而非 0：判定前提不成立時不得偽裝成任何 Tier，
    // 尤其不能落在 Tier 0（最寬鬆），否則使用者會收到「純文件，無需 review」這種
    // 未經證實的斷言，而 marker 同時因缺 repoRoot 寫不進去 → 閘門靜默失效。
    const tier: number | null = repoRoot ? computeTier(repoRoot) : null;

    // STEP 09: 決定本輪 review 引擎（只在 Tier 2~3 探測——SKILL.md 明定「engine 只影響
    // Tier 2/3 的面向 review」，Tier 0/1 不消費這個值：Tier 0 不經 skill、Tier 1 不 spawn
    // review agent。探測是同步、up to 5s 的子進程呼叫，Tier 1 是最常見的非瑣碎 commit 類型，
    // 對它跑一次用不到的探測是純浪費，與 Tier 0 已排除的理由完全同類。
    // 探測結果隨即寫入 marker，Stop gate 之後只讀不重探，確保同一輪 review 引擎一致。
    /** 本輪引擎決策；Tier 0/1 或判定失敗時為 null（不需要引擎） */
    const engineDecision: EngineDecision | null =
      tier !== null && tier >= 2 ? resolveEngine() : null;

    // STEP 10: Tier 2/3 寫入 pending-review marker，供 PreToolUse 閘門阻擋下一個 commit、
    // Stop 閘門阻擋回合結束。sessionId 一併寫入，作為 stop-review-guard 的第一比對鍵。
    // 例外：命令含 [skip-review] 或 --amend 時不寫（與 commit-gate-guard 放行條件對稱，
    // 否則 skip-review 的 commit 雖自身放行，卻仍替下一個 commit 上鎖）。
    let gateNote = '';
    const skipMarker = /\[skip-review\]/i.test(command) || /--amend/.test(command);
    if (tier !== null && tier >= 2 && repoRoot && !skipMarker && engineDecision) {
      /** 本次 hook 事件所屬 session id；缺漏時不寫入欄位（stop gate 退回 repoRoot 比對） */
      const sessionId = typeof data.session_id === 'string' && data.session_id ? data.session_id : undefined;
      gateNote = writeMarker(tier, repoRoot, engineDecision.engine, sessionId);
    }

    // STEP 11: 依 Tier 輸出對應 systemMessage
    console.log(JSON.stringify({
      systemMessage: buildMessage(tier, eslintResult, gateNote, engineDecision),
    }));
  } catch {
    process.exit(0);
  }
});

/**
 * 寫入 pending-review marker 檔。
 * @param tier 本次 commit 的 Tier（2 或 3）
 * @param repoRoot 目標 repo 根目錄
 * @param engine 本輪 review 引擎，釘在上鎖時點供 Stop gate 讀取，不由後者重新探測
 * @param sessionId 觸發 commit 的 session id；undefined 時 JSON 序列化自動略去該欄位
 * @returns 給 systemMessage 用的閘門說明字串；寫入失敗回傳空字串（fail-open，不阻斷）
 */
function writeMarker(tier: number, repoRoot: string, engine: ReviewEngine, sessionId?: string): string {
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
      sessionId,
      expectedAspects: aspectsForTier(tier),
      engine,
    };
    writeFileSync(markerPathForRepo(repoRoot), JSON.stringify(marker, null, 2), 'utf8');

    // STEP 03: 回傳閘門狀態說明
    return [
      '',
      `🔒 已寫入 pending-review 閘門（Tier ${tier}，commit ${commitHash.slice(0, 10)}）。`,
      '在完成 review 前，此 repo 的「新 commit」會被 PreToolUse 阻擋。',
      `review 完成後執行：bun ~/.claude/scripts/clear-pending-review.ts --aspects-done=${aspectsForTier(tier)}`,
    ].join('\n');
  } catch {
    return '';
  }
}

/**
 * 依 Tier 組出 systemMessage 內容。
 * @param tier Tier 數字；null 代表 repoRoot 解析失敗、判定前提不成立
 * @param eslintResult eslint 執行結果字串
 * @param gateNote 閘門說明字串（Tier 2/3 才有值）
 * @param engineDecision 本輪引擎決策；Tier 0 與判定失敗路徑為 null（該路徑不指派 skill）
 * @returns 完整 systemMessage
 */
function buildMessage(
  tier: number | null,
  eslintResult: string,
  gateNote: string,
  engineDecision: EngineDecision | null,
): string {
  // STEP 01: 判定前提不成立——如實說明，不得降級成 Tier 0 而謊稱「無需 review」。
  // 此路徑 marker 也寫不進去（缺 repoRoot），閘門等同失效，必須讓使用者看見。
  if (tier === null) {
    return [
      '⚠️ Post-commit（Tier 判定失敗）',
      '',
      eslintResult,
      '',
      '無法解析本次 commit 的目標 repo，Tier 未判定、pending-review 閘門未上鎖。',
      '請確認 commit 指令的目標目錄；需要 review 時手動執行：/commit-review',
    ].join('\n');
  }
  // STEP 02: Tier 0 純文件，只需通知，不經 skill
  if (tier === 0) {
    return `📋 Post-commit（Tier 0 純文件）\n\n${eslintResult}\n\n只需通知，無需 review。`;
  }
  // STEP 03: Tier 1 不 spawn review agent、不消費 engine（STEP 09 本就沒為它探測），
  // 指派字串照 SKILL.md §1.1「Tier 0/1 不受 engine 影響」不含 engine 欄位。
  if (tier === 1) {
    return [
      '📋 Post-commit（Tier 1）',
      '',
      eslintResult,
      '',
      'Claude 應執行 commit-review skill 跑 Tier 1 的檢查（不 spawn review agent）：',
      '  Skill(commit-review) args: "tier=1 target=HEAD"',
    ].join('\n');
  }
  // STEP 04: Tier 2/3 一律需要 engine（STEP 09 已為它們探測）。走到這裡仍是 null，
  // 代表 STEP 09 的判斷條件與這裡的 tier 判斷分歧——如實回報而非挑一個引擎猜，
  // 否則分歧會被藏在一次看似正常的指派裡。
  if (!engineDecision) {
    return [
      `⚠️ Post-commit（Tier ${tier}，引擎未決定）`,
      '',
      eslintResult,
      '',
      '本次未能決定 review 引擎，未指派 skill。請手動執行：/commit-review',
      gateNote,
    ].join('\n');
  }

  return [
    `📋 Post-commit（Tier ${tier}｜engine=${engineDecision.engine}）`,
    '',
    eslintResult,
    '',
    // 只在覆寫或降級時印理由；走預設且探測通過時 reason 為 null，不製造每次 commit 都出現的噪音
    ...(engineDecision.reason ? [`ℹ️ ${engineDecision.reason}`, ''] : []),
    `Claude 應執行 commit-review skill 跑 Tier ${tier} 的 review chain：`,
    `  ${buildSkillInvocation(tier, 'HEAD', engineDecision.engine)}`,
    gateNote,
  ].join('\n');
}
