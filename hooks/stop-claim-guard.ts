#!/usr/bin/env bun
import fs from 'fs';
import { askJev, jevDisabled, logDecision, readAnswer, sessionStatePath, truncateMiddle, writeJsonAtomic } from '../scripts/lib/jev-client';
import { CLAIM_QUESTIONS } from '../scripts/lib/jev-questions';

/**
 * 完成宣告檢查 Hook（Stop）— Jev 版，對應 tasks/jev-trial-plan.md 掛載點 B
 *
 * 回合結束時，用 Jev 問 Claude 的最後一則回覆兩題：有沒有宣稱完成／修好／找到根因、有沒有附具體驗證證據。
 * 宣稱了但沒證據（兩題 confidence 都達行動下限）→ 以 `{"decision":"block"}` 擋下回合結束，
 * reason 依 harness/judgment-matrix.md §2 完成判準要求補證據或改成「待確認」。
 * 防迴圈：stop_hook_active 為真（已被 Stop hook 擋過、正在續跑）一律放行；同一 session 最多擋 MAX_BLOCKS 次。
 * 任何錯誤一律 fail-open：放行、不輸出，錯誤寫入 ~/.claude/state/jev/decisions.jsonl。
 * kill switch：環境變數 JEV_HOOKS_DISABLED=1。
 *
 * 不用 exit 2 擋：hook-error-wrapper 會把「exit 2 且有 stderr」記成 ERRORS.jsonl 錯誤；
 * 改用 stdout JSON decision:block ＋ exit 0，與 stop-review-guard 同一做法。
 * 門檻來源：階段 1 B 評估（短句 15/15、長文 6/6，套行動下限後）與 user 2026-09-21 拍板的行動下限 0.3。
 */

/** hook 名稱，寫入決策 log 用 */
const HOOK_NAME = 'B-claim';
/** 同一 session 最多擋幾次：超過就放行，避免誤判時反覆打斷 */
export const MAX_BLOCKS = 2;
/** 行動下限：claims 與 evidence 兩題的 confidence 都要達此值才擋 */
const ACTION_MIN_CONF = 0.3;
/** 送給 Jev 的回覆最大字元數：長文評估最長 3,876 字仍準確，超過則保留頭尾（宣稱常在開頭或結尾） */
const MAX_MESSAGE_CHARS = 6000;
/** state 檔的子目錄名稱：~/.claude/state/jev/claim/<session>.json */
const STATE_NAME = 'claim';

/** 單題判定 */
interface Verdict {
  /** 預測值（noul 為是否「是」） */
  pred: string | boolean;
  /** confidence（noul 以 |2p-1| 換算） */
  conf: number;
}

/** Stop hook stdin 中本 hook 用到的欄位 */
interface StopInput {
  /** 事件名稱，防誤掛到 SubagentStop 等其他事件 */
  hook_event_name?: string;
  /** session ID，state 檔名與決策 log 用 */
  session_id?: string;
  /** 為 true 表示本回合已被 Stop hook 擋過、正在續跑 */
  stop_hook_active?: boolean;
  /** Claude 最後一則回覆的文字 */
  last_assistant_message?: string;
}

/** 本 hook 的 per-session state */
interface ClaimState {
  /** 本 session 已擋下的次數 */
  blocks: number;
}

/**
 * 是否擋下：宣稱完成且無證據，兩題都達行動下限
 * @param claims - 「宣稱完成」題的判定
 * @param evidence - 「附有證據」題的判定
 * @returns true 表示擋下
 */
export function shouldBlock(claims: Verdict, evidence: Verdict): boolean {
  return claims.pred === true && claims.conf >= ACTION_MIN_CONF && evidence.pred === false && evidence.conf >= ACTION_MIN_CONF;
}

/**
 * 本 session 是否還能擋
 * @param blocks - 已擋下的次數
 * @returns true 表示還沒擋滿
 */
export function canBlock(blocks: number): boolean {
  return blocks < MAX_BLOCKS;
}

/**
 * 是否整個略過檢查（不呼叫 Jev）
 * @param input - Stop hook stdin
 * @returns true 表示略過
 */
export function shouldSkip(input: StopInput): boolean {
  return input.hook_event_name !== 'Stop' || input.stop_hook_active === true || !input.last_assistant_message?.trim();
}

/**
 * 組擋下時回給 Claude 的理由
 * @param n - 這是本 session 第幾次擋
 * @param claims - 「宣稱完成」題的判定
 * @param evidence - 「附有證據」題的判定
 * @returns reason 文字
 */
export function buildReason(n: number, claims: Verdict, evidence: Verdict): string {
  return [
    `[Jev 完成宣告檢查] 這則回覆宣稱已完成、已修好或已找到根因，但沒有附具體驗證證據（宣稱 conf ${claims.conf.toFixed(2)}、無證據 conf ${evidence.conf.toFixed(2)}）。`,
    '依 ~/.claude/harness/judgment-matrix.md §2 完成判準，宣告完成前要能寫出「我改了 X，因為根因/需求是 Y，證據是 Z」：',
    '- 能驗證 → 實際跑驗證，把輸出（測試結果末幾行、指令輸出、量測數字）補進回覆',
    '- 無法驗證 → 把宣稱改成「可能原因／待確認」，並寫明缺什麼、怎麼驗',
    '- 只寫「已驗證」不算證據',
    `若這是誤判（回覆其實沒有宣稱完成，或已附證據），直接再結束一次即可，本檢查不會連續擋第二次。（本 session 第 ${n}/${MAX_BLOCKS} 次）`,
  ].join('\n');
}

/**
 * 讀本 session 已擋下的次數；檔案不存在代表還沒擋過
 * @param file - state 檔路徑
 * @returns 已擋下的次數
 */
function loadBlocks(file: string): number {
  // STEP 01: 本 session 還沒擋過
  if (!fs.existsSync(file)) {
    return 0;
  }
  // STEP 02: 格式不對直接丟錯，不默默歸零（歸零等於解除上限）
  const data = JSON.parse(fs.readFileSync(file, 'utf-8')) as Partial<ClaimState>;
  if (typeof data.blocks !== 'number') {
    throw new Error(`state 檔格式錯誤：${file}`);
  }
  return data.blocks;
}

/**
 * 主流程：讀 stdin → 檢查上限 → 問 Jev → 宣稱無證據時擋下
 */
async function main(): Promise<void> {
  // STEP 01: kill switch 與略過條件
  const input = JSON.parse(fs.readFileSync(0, 'utf-8')) as StopInput;
  if (jevDisabled() || shouldSkip(input)) {
    return;
  }
  if (typeof input.session_id !== 'string') {
    throw new Error('stdin 缺 session_id');
  }
  // STEP 02: 擋滿就不再呼叫 Jev（省下回合結束的延遲）
  const file = sessionStatePath(STATE_NAME, input.session_id);
  const blocks = loadBlocks(file);
  const msg = String(input.last_assistant_message);
  if (!canBlock(blocks)) {
    logDecision({ hook: HOOK_NAME, session: input.session_id, len: msg.length, capped: true, blocked: 0 });
    return;
  }
  // STEP 03: 問 Jev；失敗已在 askJev 內寫 log，直接放行
  const res = await askJev(HOOK_NAME, { assistant_message: truncateMiddle(msg, MAX_MESSAGE_CHARS) }, CLAIM_QUESTIONS);
  if (!res) {
    return;
  }
  const claims = readAnswer(res.answers.claims);
  const evidence = readAnswer(res.answers.evidence);
  const block = shouldBlock(claims, evidence);
  logDecision({
    hook: HOOK_NAME, session: input.session_id, ms: Math.round(res.ms), len: msg.length,
    claims: claims.pred, claims_conf: claims.conf, evidence: evidence.pred, evidence_conf: evidence.conf,
    blocked: block ? 1 : 0, blocks: block ? blocks + 1 : blocks,
  });
  // STEP 04: 擋下：先記次數再輸出，確保上限生效
  if (block) {
    writeJsonAtomic(file, { blocks: blocks + 1 } satisfies ClaimState);
    process.stdout.write(JSON.stringify({ decision: 'block', reason: buildReason(blocks + 1, claims, evidence) }));
  }
}

if (import.meta.main) {
  try {
    await main();
  } catch (err) {
    // 任何未預期錯誤都 fail-open，只記 log
    logDecision({ hook: HOOK_NAME, error: String(err) });
  }
}
