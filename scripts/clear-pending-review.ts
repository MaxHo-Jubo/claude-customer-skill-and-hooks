#!/usr/bin/env bun
/**
 * 清除 pending-review marker，解鎖該 repo 的 commit 閘門。
 *
 * 用途：Tier 2/3 commit 的 review 完成、Critical 問題處理完後執行，之後才能在該 repo 開新 commit
 * （commit-gate-guard 放行）、回合也才能結束（stop-review-guard）。
 *
 * 【2026-08-19 加上機械閘門】此前本腳本無條件 unlink，整套閘門「上鎖機械、解鎖靠自覺」：
 * hook 判 Tier、寫 marker、PreToolUse deny 全是程式強制，解鎖卻只靠 SKILL.md 的兩行散文前置條件，
 * 而兩個閘門的攔阻訊息還把解鎖指令直接印給模型——在最想結束回合的時刻遞上鑰匙。
 * 現要求顯式聲明跑完幾個面向，不足即拒絕，且每條解鎖路徑都寫 audit log。
 * N 仍是呼叫端自報（腳本無從驗證 agent 真的跑過），但把靜默省略換成顯式、可事後對帳的斷言。
 *
 * 引數解析採嚴格模式（未知 flag、重複給值、缺值一律 exit 1）。理由：本腳本的全部價值就是那個
 * 斷言，斷言的輸入若能被靜默曲解，閘門等於不存在。實測踩過的三種——`--force <repo路徑>` 把路徑
 * 吞成理由並解鎖了 cwd 的 repo、`--force --aspects-done=2` 把旗標吞成理由並整個跳過檢查、
 * `--aspects-done 6`（空格）被當成 repo 路徑——都是靜默走到錯誤結果且 exit 0。
 *
 * 用法：
 *   bun ~/.claude/scripts/clear-pending-review.ts --aspects-done=6
 *   bun ~/.claude/scripts/clear-pending-review.ts /path/repo --aspects-done=1
 *   bun ~/.claude/scripts/clear-pending-review.ts --force="review agent 因 API 額度中斷，已回報使用者"
 */
import { existsSync, unlinkSync, appendFileSync, mkdirSync } from 'fs';
import { join } from 'path';
import {
  markerPathForRepo, resolveRepoRoot, readMarkerRaw, aspectsForTier,
  MARKER_DIR, MARKER_MAX_AGE_MS, type ReviewMarker,
} from './lib/review-marker';

/** 解鎖稽核紀錄檔：每次解鎖嘗試（含被拒與逾期自動清除）都追加一行，供事後對帳 */
const AUDIT_LOG = join(MARKER_DIR, 'unlock-audit.log');

/**
 * 印出用法並以 exit 1 結束。
 * @param message 錯誤訊息
 */
function fail(message: string): never {
  console.error(`❌ ${message}`);
  console.error('');
  console.error('用法：bun ~/.claude/scripts/clear-pending-review.ts [repo路徑] --aspects-done=<N>');
  console.error('      bun ~/.claude/scripts/clear-pending-review.ts [repo路徑] --force="<理由>"');
  process.exit(1);
}

/**
 * 追加一行解鎖稽核紀錄。
 * @param fields 欄位陣列，以 tab 串接
 * @returns 是否寫入成功
 */
function writeAudit(fields: (string | number)[]): boolean {
  try {
    mkdirSync(MARKER_DIR, { recursive: true });
    appendFileSync(AUDIT_LOG, fields.join('\t') + '\n', 'utf8');
    return true;
  } catch {
    return false;
  }
}

// STEP 01: 嚴格解析引數——未知 flag / 重複給值 / 缺值一律拒絕，不靜默曲解
/** 原始引數陣列（去掉 bun 與腳本路徑） */
const argv = process.argv.slice(2);
/** 呼叫端聲明已完成的 review 面向數；未帶為 null */
let aspectsDone: number | null = null;
/** 強制解鎖的理由；未帶 --force 為 null */
let forceReason: string | null = null;
/** 目標 repo 路徑（位置引數）；未帶為 null，改用 cwd */
let argRepo: string | null = null;

for (const arg of argv) {
  if (arg.startsWith('--aspects-done=')) {
    if (aspectsDone !== null) {
      fail('--aspects-done 重複指定。稽核用的斷言不接受多值，請只給一次。');
    }
    /** --aspects-done 的原始字串值，需為非負整數 */
    const raw = arg.slice('--aspects-done='.length);
    if (!/^\d+$/.test(raw)) {
      fail(`--aspects-done 必須是非負整數，收到「${raw}」。（拒絕 6.5 / 0x6 / 1e9 / -1 / 空值等寫法）`);
    }
    aspectsDone = Number(raw);
  } else if (arg.startsWith('--force=')) {
    if (forceReason !== null) {
      fail('--force 重複指定。');
    }
    forceReason = arg.slice('--force='.length).trim();
    if (!forceReason) {
      fail('--force 必須帶理由：--force="<理由>"。理由會寫進 audit log，空理由等同無紀錄。');
    }
  } else if (arg === '--force') {
    // 舊的空格形式會把下一個 argv（很可能是 repo 路徑或另一個 flag）吞成理由，實測會解鎖錯的 repo
    fail('--force 必須用等號形式並帶理由：--force="<理由>"。（空格形式會把下一個引數誤吞為理由）');
  } else if (arg.startsWith('--')) {
    fail(`不認識的參數「${arg}」。未知 flag 一律拒絕，避免拼錯後靜默略過檢查。`);
  } else {
    if (argRepo !== null) {
      fail(`只能指定一個 repo 路徑，收到多個（「${argRepo}」與「${arg}」）。`);
    }
    argRepo = arg;
  }
}

// STEP 02: 決定目標 repo（引數優先，否則用當前工作目錄解析）
const repoRoot = argRepo ? resolveRepoRoot(argRepo) : resolveRepoRoot(process.cwd());

if (!repoRoot) {
  fail(`無法解析 git repo 根目錄${argRepo ? `（引數「${argRepo}」）` : '（當前工作目錄）'}，請在 repo 內執行或帶入正確的 repo 路徑。`);
}

// STEP 03: marker 不存在 → 無需清除
const markerPath = markerPathForRepo(repoRoot);
if (!existsSync(markerPath)) {
  console.log(`ℹ️  ${repoRoot} 沒有 pending-review marker，無需清除。`);
  process.exit(0);
}

// STEP 04: 讀出 marker（共用 readMarkerRaw 的 shape guard，與兩個閘門同一份判定）
const marker: ReviewMarker | null = readMarkerRaw(markerPath);
if (!marker) {
  fail(`marker 檔內容無法解析或不是物件：${markerPath}。請檢查後手動移除。`);
}

/** commit hash 前綴，供訊息與稽核顯示 */
const shortHash = (marker.commitHash || '').slice(0, 10);
/** marker 年齡（分鐘），供稽核紀錄 */
const ageMin = Math.round((Date.now() - (marker.createdAt || 0)) / 60000);

// STEP 05: 決定該 Tier 應完成的面向數
// 型別異常時 fail closed——不 silent fallback（no-fallback-after-root-cause）。
// 舊 marker 缺欄位則由 tier 推導，不再無條件放行：expectedAspects 是 tier 的純函數，
// 「不知道應跑幾個」這個狀態不存在，留一條繞過路徑等於在防洩漏的改動上自開後門。
if ('expectedAspects' in marker && typeof marker.expectedAspects !== 'number') {
  fail(`marker 的 expectedAspects 型別異常（${typeof marker.expectedAspects}）：${JSON.stringify(marker.expectedAspects)}。閘門無法判定，拒絕解鎖。`);
}
/** 該 Tier 應完成的面向數 */
const expected = typeof marker.expectedAspects === 'number'
  ? marker.expectedAspects
  : aspectsForTier(marker.tier);

// STEP 06: 機械閘門——聲明數必須達標，否則拒絕（被拒也要留痕：那代表該輪 review 真的縮水了）
if (forceReason === null) {
  if (aspectsDone === null) {
    writeAudit([new Date().toISOString(), repoRoot, shortHash, `tier=${marker.tier}`,
                `expected=${expected}`, 'done=none', 'result=REFUSED-no-claim']);
    console.error(`❌ 拒絕解鎖：Tier ${marker.tier} commit ${shortHash} 需聲明已完成的 review 面向數。`);
    console.error(`   本 Tier 應完成 ${expected} 個面向${expected >= 6 ? '（pr-reviewer lite + 5 個 pr-review-toolkit 面向）' : '（pr-reviewer lite）'}。`);
    console.error('');
    console.error(`   跑完了：bun ~/.claude/scripts/clear-pending-review.ts --aspects-done=<實際收齊的面向數>`);
    console.error('   沒跑完：依 commit-review SKILL.md §3.1 先向使用者回報未回傳的面向名稱，');
    console.error('           取得同意後用 --force="<理由>"');
    process.exit(1);
  }
  if (aspectsDone < expected) {
    writeAudit([new Date().toISOString(), repoRoot, shortHash, `tier=${marker.tier}`,
                `expected=${expected}`, `done=${aspectsDone}`, 'result=REFUSED-short']);
    console.error(`❌ 拒絕解鎖：聲明完成 ${aspectsDone} 個面向，Tier ${marker.tier} 需要 ${expected} 個（缺 ${expected - aspectsDone} 個）。`);
    console.error('   依 commit-review SKILL.md §3.1，降級時不得清 marker——請先向使用者回報未回傳的面向名稱，');
    console.error('   由其決定補跑，或取得同意後用 --force="<理由>"。');
    process.exit(1);
  }
  if (aspectsDone > expected) {
    // 不擋，但要標注：多半是打錯字，靜默收下會讓 audit log 失去意義
    console.warn(`⚠️  聲明完成 ${aspectsDone} 個面向，但本 Tier 只需 ${expected} 個——請確認數字無誤。`);
  }
}

// STEP 07: 先寫 audit 再刪 marker
// 順序刻意如此：最壞情況是「有紀錄但沒解鎖」（重跑即可），反過來是「解了鎖但沒紀錄」（不可回復）。
// 舊版先 unlink 再寫、失敗空 catch 吞掉，然後照樣印「已記入」——主動陳述一件沒發生的事。
/** 稽核紀錄欄位 */
const auditFields = [
  new Date().toISOString(), repoRoot, shortHash, `tier=${marker.tier}`,
  `expected=${expected}`, `done=${aspectsDone ?? 'n/a'}`,
  forceReason ? `result=FORCE reason=${forceReason}` : 'result=OK',
  `age=${ageMin}min`,
];
if (!writeAudit(auditFields)) {
  fail(`無法寫入稽核紀錄 ${AUDIT_LOG}，拒絕解鎖。\n   「解了鎖但沒紀錄」不可回復，故此處 fail closed；修好寫入權限後重跑即可。`);
}

try {
  unlinkSync(markerPath);
} catch (err) {
  console.error('❌ 清除 marker 失敗：', err instanceof Error ? err.message : String(err));
  console.error(`   稽核紀錄已寫入（result 欄位不代表實際解鎖），請確認 ${markerPath} 狀態。`);
  process.exit(1);
}

// STEP 08: 回報結果
if (forceReason) {
  console.log(`⚠️  已強制解鎖 pending-review 閘門：Tier ${marker.tier} commit ${shortHash}（${repoRoot}）。`);
  console.log(`   理由：${forceReason}`);
  console.log(`   已記入 ${AUDIT_LOG}`);
} else {
  console.log(`✅ 已清除 pending-review 閘門：Tier ${marker.tier} commit ${shortHash}，聲明完成 ${aspectsDone}/${expected} 個面向（${repoRoot}）。`);
}
if (ageMin > MARKER_MAX_AGE_MS / 60000) {
  console.log(`   ℹ️  此 marker 已逾期 ${ageMin} 分鐘，兩個閘門實際上早已放行。`);
}
