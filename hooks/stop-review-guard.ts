#!/usr/bin/env bun
/**
 * Stop hook：pending-review 閘門的「回合結束」守門員。
 *
 * 生命週期覆蓋：一個回合只有兩種結束方式——(1) 呼叫工具繼續（危險動作已由
 * commit-gate-guard 的 PreToolUse deny 看守）、(2) 結束回合（含純文字回覆）。
 * 2026-07-22 兩次 review 未觸發都走了路徑 (2)：commit 後主 agent 只打字回覆，
 * systemMessage 軟指派被無視。本 hook 補上路徑 (2)：marker 未清就 block 回合結束，
 * reason 以指令級注入（user role「Stop hook feedback:」訊息）指派 commit-review，
 * 實測遵從度遠高於 systemMessage（見 tasks/stop-review-guard-plan.md 實測節）。
 *
 * 比對邏輯（兩鍵擇一命中即攔）：
 * - marker.sessionId === 本次 session_id：本 session 自己欠的 review
 * - marker.repoRoot === resolveRepoRoot(cwd)：跨 session 接手（新 session 開在同 repo）
 *
 * 防 brick 保險絲：per-session 有界計數（stopBlockCounts），達上限放行並印大聲警告。
 * 一律 fail-open：hook 自身任何錯誤都放行，絕不因守門員故障而卡死回合。
 */
import { existsSync, readdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { MARKER_DIR, readValidMarker, resolveRepoRoot, type ReviewMarker } from '../scripts/lib/review-marker';

/**
 * 同一 session 最多被 block 的次數：達上限即放行（改印警告），防止模型連續無視時
 * 無限循環 brick 住回合。reason 為指令級注入，實務上第一次就會照做，3 次是保險絲不是常態。
 */
const MAX_STOP_BLOCKS = 3;

/** hook 的 stdin JSON 資料 */
let input = '';
process.stdin.setEncoding('utf8');

/** stdin 讀取逾時上限（ms）：時限內未讀完（未收到 end）視為異常 */
const STDIN_TIMEOUT_MS = 2000;

/** stdin 超時防呆：時限內未收到 end 則靜默退出（fail-open） */
const stdinTimeout = setTimeout(() => { process.exit(0); }, STDIN_TIMEOUT_MS);

process.stdin.on('data', (chunk: string) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    /** 本次 Stop hook 事件的 stdin JSON payload */
    const data = JSON.parse(input);

    // STEP 01: 只處理 Stop 事件——防止被誤掛到 SubagentStop 等其他事件時擋錯對象
    if (data.hook_event_name !== 'Stop') {
      process.exit(0);
    }

    // STEP 02: plan mode 放行——此模式下 review chain（Edit/commit --amend）根本跑不了，
    // block 只會逼模型連續空轉燒掉保險絲；marker 仍在磁碟上，回到一般模式照樣被攔
    if (data.permission_mode === 'plan') {
      process.exit(0);
    }

    // STEP 03: 短路常態路徑——無 marker 目錄或無 .json marker 立即放行。
    // 本 hook 每個 session 每次回合結束都會執行，這裡之前絕不 spawn git（成本控制）；
    // 過濾 .json 也是必要的：MARKER_DIR 實際存在 debug log 等非 marker 檔案
    if (!existsSync(MARKER_DIR)) {
      process.exit(0);
    }
    /** marker 目錄下的 marker 檔名清單（僅 .json） */
    const markerFiles = readdirSync(MARKER_DIR).filter((f) => f.endsWith('.json'));
    if (markerFiles.length === 0) {
      process.exit(0);
    }

    // STEP 04: 讀取所有 marker——壞檔跳過、逾期自動清除後跳過（有效性判定在
    // readValidMarker，與 commit-gate-guard 共用同一份，避免兩個閘門判定分歧）
    /** 現在時間（epoch ms），供逾期判定 */
    const now = Date.now();
    /** 有效（未逾期且可解析）的 marker 與其檔案路徑 */
    const valid: Array<{ path: string; marker: ReviewMarker }> = [];
    for (const f of markerFiles) {
      /** marker 檔完整路徑 */
      const p = join(MARKER_DIR, f);
      /** 有效 marker；壞檔或逾期（已就地清除）為 null */
      const marker = readValidMarker(p, now);
      if (!marker) {
        continue;
      }
      valid.push({ path: p, marker });
    }
    if (valid.length === 0) {
      process.exit(0);
    }

    // STEP 05: 比對——sessionId 命中優先（不用 spawn git）；未中才解析 cwd 的 repoRoot 補比對。
    // 多個 marker 同時命中時只攔第一個：review 完成清掉後，下次回合結束自然輪到下一個
    /** 本次回合所屬 session id；缺漏時為 ''（各無 id session 在計數表共用同一額度，寧提早燒斷保險絲也不 brick） */
    const sessionId: string = typeof data.session_id === 'string' ? data.session_id : '';
    // STEP 05.01: sessionId 命中比對——本 session 自己欠的 review
    /** 命中的 marker 與其檔案路徑（sessionId 或 repoRoot 比對成功）；未命中為 undefined */
    let hit = valid.find((v) => v.marker.sessionId && sessionId && v.marker.sessionId === sessionId);
    // STEP 05.02: 未命中才解析 cwd 的 repoRoot 補比對——跨 session 接手（新 session 開在同 repo）
    if (!hit) {
      /** 本 session cwd 所在的 git repo 根目錄；非 git 目錄為 null */
      const repoRoot = resolveRepoRoot(data.cwd || process.cwd());
      if (repoRoot) {
        hit = valid.find((v) => v.marker.repoRoot === repoRoot);
      }
    }
    if (!hit) {
      process.exit(0);
    }

    /** 命中 marker 的短 commit hash，供訊息顯示 */
    const hash10 = (hit.marker.commitHash || '').slice(0, 10);
    /** 此 marker 的 per-session block 計數表（sessionId → 次數） */
    const counts = hit.marker.stopBlockCounts || {};
    /** 本 session 在此 marker 上已被 block 的次數 */
    const count = counts[sessionId] || 0;

    // STEP 06: 保險絲——本 session 已達 block 上限，放行並印大聲警告（每次回合結束都會再提醒）
    if (count >= MAX_STOP_BLOCKS) {
      console.log(JSON.stringify({
        systemMessage: [
          `⚠️ pending-review Stop 閘門：本 session 已被攔 ${MAX_STOP_BLOCKS} 次仍未完成 review`,
          `（Tier ${hit.marker.tier} commit ${hash10}），保險絲達上限、本次放行。`,
          `請儘速執行 Skill(commit-review) args: "tier=${hit.marker.tier} target=${hit.marker.commitHash}"。`,
        ].join(''),
      }));
      process.exit(0);
    }

    // STEP 07: 計數 +1 寫回 marker。寫回失敗必須「放行」而非照樣 block：
    // 計數推不進去（磁碟唯讀等）時繼續 block 會變成無上限循環，違反防 brick 原則
    try {
      /** 計數遞增後的新 marker 內容（immutable 更新，不動原物件） */
      const updated: ReviewMarker = {
        ...hit.marker,
        stopBlockCounts: { ...counts, [sessionId]: count + 1 },
      };
      writeFileSync(hit.path, JSON.stringify(updated, null, 2), 'utf8');
    } catch {
      process.exit(0);
    }

    // STEP 08: block 回合結束——reason 直接指派 commit-review，指令級注入不靠自覺
    /** 注入給模型的指派內容：做什麼（skill+args）、做完如何解鎖 */
    const reason = [
      `🔒 pending-review 閘門（Stop）：Tier ${hit.marker.tier} commit ${hash10}（${hit.marker.repoRoot}）的 review 尚未完成，本回合不得結束。`,
      '請立即執行 review chain：',
      `  Skill(commit-review) args: "tier=${hit.marker.tier} target=${hit.marker.commitHash}"`,
      'review 完成（Critical 已處理）後執行解鎖，之後即可正常結束回合：',
      `  bun ~/.claude/scripts/clear-pending-review.ts ${hit.marker.repoRoot}`,
    ].join('\n');
    console.log(JSON.stringify({ decision: 'block', reason }));
    process.exit(0);
  } catch {
    process.exit(0);
  }
});
