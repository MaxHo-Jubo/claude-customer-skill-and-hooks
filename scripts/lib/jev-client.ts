import fs from 'fs';
import os from 'os';
import path from 'path';
import type { JevQuestion } from './jev-questions';

/**
 * Jev（TypeSafe systemOne）HTTP client，hook 與離線評估共用
 *
 * - callJev：出錯就丟，給離線評估用
 * - askJev：fail-open 版，給 hook 用；任何錯誤回 null 並寫入決策 log，不擋 user 流程
 *
 * 不用官方 SDK：~/.claude/scripts 沒有 npm 依賴，且 SDK 預設每次嘗試 10s、重試 2 次、
 * 沒有總時間上限，同步 hook 最壞會卡 30 秒以上（tasks/jev-trial-plan.md 階段 0）。
 */

/** systemOne 端點 */
const API_URL = 'https://api.typesafe.ai/v1/systemone';
/** 固定模型版本：門檻只對評估過的版本有效，升版要重跑 scripts/jev-eval/run-eval.ts */
export const JEV_MODEL = 'jev-1.13.0';
/** hook 內單次呼叫逾時（毫秒）：冷啟動 p95 826ms 的約 2.4 倍 */
export const HOOK_TIMEOUT_MS = 2000;
/** noul 判為「是」的機率下限 */
export const NOUL_YES = 0.5;
/** kill switch：設為 '1' 時所有 Jev hook 直接放行 */
const DISABLE_ENV = 'JEV_HOOKS_DISABLED';
/** Jev hook 的狀態根目錄（決策 log 與各 hook 的 per-session state） */
const STATE_ROOT = path.join(os.homedir(), '.claude', 'state', 'jev');
/** 決策 log：只記預測、confidence 與耗時，不記原文 */
const LOG_PATH = path.join(STATE_ROOT, 'decisions.jsonl');
/** 合法的 session id：拼進檔名前檢查，避免跳出 STATE_ROOT */
const SESSION_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;
/** 送出前遮罩的憑證樣式與替換字串（樣式同 rules/common/security.md pre-commit-scan） */
const SECRET_PATTERNS: [RegExp, string][] = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)/g, '[MASKED_PRIVATE_KEY]'],
  [/(:\/\/[^/:@\s]+:)[^@/\s]+@/g, '$1[MASKED]@'],
  [/ghp_[A-Za-z0-9]{30,}/g, '[MASKED]'],
  [/github_pat_[A-Za-z0-9_]{30,}/g, '[MASKED]'],
  [/sk-[A-Za-z0-9_-]{20,}/g, '[MASKED]'],
  [/AIza[0-9A-Za-z_-]{30,}/g, '[MASKED]'],
];

/** truncateMiddle 截斷時插在中間的標記 */
const TRUNC_MARK = '\n…（中間截斷）…\n';

/** systemOne 回傳的單題答案 */
export interface JevAnswer {
  /** 題型 */
  type: 'choice' | 'noul';
  /** choice 選中的標籤 */
  choice?: string;
  /** choice 的 confidence */
  confidence?: number;
  /** noul 為「是」的機率 */
  noul?: number;
  /** choice 各標籤機率 */
  probabilities?: Record<string, number>;
}

/** 一次成功呼叫的結果 */
export interface JevResult {
  /** 各題原始答案，key 為題名 */
  answers: Record<string, JevAnswer>;
  /** 呼叫耗時毫秒 */
  ms: number;
}

/**
 * kill switch 是否開啟
 * @returns true 表示 hook 應直接放行
 */
export function jevDisabled(): boolean {
  return process.env[DISABLE_ENV] === '1';
}

/**
 * 遮罩字串中的憑證
 * @param s - 原字串
 * @returns 遮罩後字串
 */
export function maskSecrets(s: string): string {
  return SECRET_PATTERNS.reduce((acc, [re, rep]) => acc.replace(re, rep), s);
}

/**
 * 超過上限時保留頭尾、截掉中間（送給 Jev 的長文字用；大量無關內容是 jev-1.13 已知弱點）
 * @param s - 原字串
 * @param max - 最大字元數（須大於截斷標記長度）
 * @returns 長度不超過 max 的字串
 */
export function truncateMiddle(s: string, max: number): string {
  // STEP 01: 未超長原樣回傳
  if (s.length <= max) {
    return s;
  }
  // STEP 02: 頭尾各留一半
  const keep = max - TRUNC_MARK.length;
  const head = Math.ceil(keep / 2);
  return s.slice(0, head) + TRUNC_MARK + s.slice(s.length - (keep - head));
}

/**
 * 遞迴遮罩 state 內所有字串
 * @param v - 任意 JSON 值
 * @returns 遮罩後的新值（不修改原物件）
 */
function deepMask(v: unknown): unknown {
  if (typeof v === 'string') {
    return maskSecrets(v);
  }
  if (Array.isArray(v)) {
    return v.map(deepMask);
  }
  if (v !== null && typeof v === 'object') {
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, deepMask(x)]));
  }
  return v;
}

/**
 * 呼叫 systemOne 一次，出錯就丟
 * @param state - 要判斷的狀態（送出前自動遮罩憑證）
 * @param questions - 題目
 * @param timeoutMs - 逾時毫秒
 * @returns 原始答案與耗時
 */
export async function callJev(state: unknown, questions: Record<string, JevQuestion>, timeoutMs: number): Promise<JevResult> {
  // STEP 01: 檢查 API key
  const key = process.env.TYPESAFE_API_KEY;
  if (!key) {
    throw new Error('TYPESAFE_API_KEY 未設定');
  }
  // STEP 02: 送出請求並計時
  const t0 = performance.now();
  const res = await fetch(API_URL, {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ model: JEV_MODEL, state: deepMask(state), questions }),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const ms = performance.now() - t0;
  // STEP 03: 非 2xx 直接丟錯，不吞
  if (!res.ok) {
    throw new Error(`systemOne HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  const body = (await res.json()) as { answers?: Record<string, JevAnswer> };
  if (!body.answers) {
    throw new Error('systemOne 回應缺 answers 欄位');
  }
  return { answers: body.answers, ms };
}

/**
 * hook 用的 fail-open 版呼叫：失敗寫 log 後回 null
 * @param hook - hook 名稱（寫入 log 用）
 * @param state - 要判斷的狀態
 * @param questions - 題目
 * @returns 成功回結果，失敗回 null
 */
export async function askJev(hook: string, state: unknown, questions: Record<string, JevQuestion>): Promise<JevResult | null> {
  try {
    return await callJev(state, questions, HOOK_TIMEOUT_MS);
  } catch (err) {
    logDecision({ hook, error: String(err) });
    return null;
  }
}

/**
 * 把原始答案轉成預測值與 confidence
 * @param a - 單題原始答案
 * @returns 預測值（choice 為標籤、noul 為是否 ≥ NOUL_YES）與 confidence（noul 以 |2p-1| 換算成與 choice 同尺度）
 */
export function readAnswer(a: JevAnswer | undefined): { pred: string | boolean; conf: number } {
  // STEP 01: 缺題直接丟錯
  if (!a) {
    throw new Error('Jev 回應缺少題目答案');
  }
  // STEP 02: noul
  if (a.type === 'noul') {
    if (typeof a.noul !== 'number') {
      throw new Error(`noul 答案缺 noul 欄位：${JSON.stringify(a)}`);
    }
    return { pred: a.noul >= NOUL_YES, conf: Math.abs(2 * a.noul - 1) };
  }
  // STEP 03: choice
  if (typeof a.choice !== 'string' || typeof a.confidence !== 'number') {
    throw new Error(`choice 答案欄位不完整：${JSON.stringify(a)}`);
  }
  return { pred: a.choice, conf: a.confidence };
}

/**
 * choice 題機率最高的前兩名。注意 probabilities 與 confidence 是不同量：第一名的機率不等於 confidence
 * @param a - 單題原始答案（須為 choice 且帶 probabilities，否則丟錯）
 * @returns 第一名與第二名的標籤、機率
 */
export function topChoices(a: JevAnswer | undefined): [{ label: string; p: number }, { label: string; p: number }] {
  // STEP 01: 檢查欄位
  if (a?.type !== 'choice' || !a.probabilities) {
    throw new Error(`choice 答案缺 probabilities：${JSON.stringify(a)}`);
  }
  // STEP 02: 依機率由高到低取前兩名
  const [first, second] = Object.entries(a.probabilities).sort((x, y) => y[1] - x[1]);
  if (!second) {
    throw new Error('choice 答案不足兩個選項');
  }
  return [{ label: first[0], p: first[1] }, { label: second[0], p: second[1] }];
}

/**
 * 追加一筆決策 log；寫入失敗只印 stderr，不影響 hook
 * @param entry - 要記錄的欄位（不得含 prompt／回覆原文）
 */
export function logDecision(entry: Record<string, unknown>): void {
  try {
    fs.mkdirSync(path.dirname(LOG_PATH), { recursive: true });
    fs.appendFileSync(LOG_PATH, JSON.stringify({ ts: new Date().toISOString(), model: JEV_MODEL, ...entry }) + '\n');
  } catch (err) {
    console.error('jev decision log 寫入失敗：', err);
  }
}

/**
 * hook 的 per-session state 檔路徑：~/.claude/state/jev/<name>/<session>.json
 * @param name - hook 的子目錄名稱
 * @param session - session ID（格式不合法直接丟錯）
 * @returns state 檔絕對路徑
 */
export function sessionStatePath(name: string, session: string): string {
  if (!SESSION_ID_RE.test(session)) {
    throw new Error(`session_id 格式不合法：${session.slice(0, 50)}`);
  }
  return path.join(STATE_ROOT, name, `${session}.json`);
}

/**
 * 原子寫入 JSON：先寫暫存檔再 rename，平行寫入時不會留下寫一半的檔案
 * @param file - 目標檔案路徑
 * @param data - 要寫入的值
 */
export function writeJsonAtomic(file: string, data: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data));
  fs.renameSync(tmp, file);
}
