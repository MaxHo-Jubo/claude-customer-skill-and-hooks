#!/usr/bin/env bun
import fs from 'fs';
import { askJev, jevDisabled, logDecision, readAnswer, sessionStatePath, truncateMiddle, writeJsonAtomic } from '../scripts/lib/jev-client';
import { REPEAT_QUESTIONS } from '../scripts/lib/jev-questions';

/**
 * 同錯偵測 Hook（PostToolUseFailure）— Jev 版，對應 tasks/jev-trial-plan.md 掛載點 C
 *
 * 每個 session 在 state 檔保留最近幾組「不同的」工具失敗。新失敗進來時，字面完全相同就直接歸組，
 * 否則用 Jev 與每組平行比對「是不是同一個問題」。某組累積到 REPEAT_TRIGGER 的倍數次時，
 * 以 additionalContext 注入 harness/judgment-matrix.md §1 S1（同一錯誤第三次出現）的換路徑提示。
 * 任何錯誤一律 fail-open：不輸出，錯誤寫入 ~/.claude/state/jev/decisions.jsonl。
 * kill switch：環境變數 JEV_HOOKS_DISABLED=1。
 *
 * 比對格式（{ command, error }）與 C 評估集相同，評估準確率才適用；行動下限為 user 2026-09-21 拍板。
 * 已知限制：同一回合平行失敗的多個工具呼叫會同時讀寫 state，可能少算一次（原子寫入保證檔案不會寫壞）。
 */

/** hook 名稱，寫入決策 log 用 */
const HOOK_NAME = 'C-repeat';
/** 每個 session 保留幾組不同的失敗，也是每次最多呼叫 Jev 的次數 */
export const MAX_CLUSTERS = 3;
/** 送給 Jev 的 error 最大字元數：測試輸出常很長，保留頭尾（大量無關內容是 jev-1.13 已知弱點） */
export const MAX_ERROR_CHARS = 1000;
/** 送給 Jev 的 command 最大字元數：非 Bash 工具的輸入 JSON 可能含整段檔案內容 */
const MAX_COMMAND_CHARS = 300;
/** 行動下限：Jev 判「是」且 confidence 達此值才算同一失敗 */
const SAME_MIN_CONF = 0.3;
/** 同一失敗每累積幾次注入一次提示（judgment-matrix §1 S1：同一錯誤第三次出現） */
const REPEAT_TRIGGER = 3;
/** state 檔的子目錄名稱：~/.claude/state/jev/repeat/<session>.json */
const STATE_NAME = 'repeat';

/** 一次失敗的摘要，格式同 C 評估集的 previous／current */
interface Failure {
  /** Bash 為指令字串，其他工具為「工具名 輸入 JSON」（已截斷） */
  command: string;
  /** Claude Code 給的錯誤文字（已截斷） */
  error: string;
}

/** 一組被判定為同一問題的失敗 */
export interface Cluster {
  /** 最近一次的失敗，下次比對用（行號位移等漂移以最新為準） */
  last: Failure;
  /** 累積次數 */
  count: number;
}

/** 單次比對的結果；null 表示該次 Jev 呼叫失敗 */
type Verdict = { pred: string | boolean; conf: number } | null;

/** 新失敗與既有各組的比對結果 */
interface Match {
  /** 所屬組的 index；-1 表示自成新組 */
  idx: number;
  /** Jev 判定的 confidence；字面相同或自成新組時為 null */
  conf: number | null;
  /** 是否因字面完全相同而歸組（未呼叫 Jev） */
  exact: boolean;
  /** 各組的 Jev 比對結果（字面相同時為空） */
  verdicts: Verdict[];
  /** 呼叫 Jev 的耗時毫秒（平行呼叫，取整批） */
  ms: number;
}

/** PostToolUseFailure stdin 中本 hook 用到的欄位 */
interface FailureInput {
  /** session ID，state 檔名與決策 log 用 */
  session_id?: string;
  /** 失敗的工具名稱 */
  tool_name?: string;
  /** 工具輸入 */
  tool_input?: unknown;
  /** 錯誤文字（Bash 為 "Exit code N\n<輸出>"） */
  error?: string;
  /** 使用者中斷造成的失敗 */
  is_interrupt?: boolean;
}

/**
 * 把 stdin 轉成送給 Jev 的失敗摘要
 * @param input - PostToolUseFailure stdin
 * @returns 失敗摘要
 */
export function describeFailure(input: FailureInput): Failure {
  // STEP 01: Bash 取指令字串（與 C 評估集同格式），其他工具取工具名＋輸入 JSON
  const cmd = (input.tool_input as { command?: unknown } | undefined)?.command;
  const command = input.tool_name === 'Bash' && typeof cmd === 'string' ? cmd : `${input.tool_name} ${JSON.stringify(input.tool_input)}`;
  // STEP 02: 兩者都截斷
  return { command: truncateMiddle(command, MAX_COMMAND_CHARS), error: truncateMiddle(input.error ?? '', MAX_ERROR_CHARS) };
}

/**
 * 從各組的比對結果挑出所屬組：判「是」且達行動下限者中 confidence 最高，同分取較新的一組
 * @param verdicts - 依組順序（新到舊）的比對結果
 * @returns 所屬組 index 與 confidence；都不符合回 null
 */
export function pickMatch(verdicts: Verdict[]): { idx: number; conf: number } | null {
  // STEP 01: 篩出判「是」且達行動下限者
  const hits = verdicts.flatMap((v, idx) => (v?.pred === true && v.conf >= SAME_MIN_CONF ? [{ idx, conf: v.conf }] : []));
  if (hits.length === 0) {
    return null;
  }
  // STEP 02: 取 confidence 最高；嚴格大於才換，同分保留較前面（較新）的一組
  return hits.reduce((a, b) => (b.conf > a.conf ? b : a));
}

/**
 * 把新失敗記進 state：歸入所屬組（次數 +1、代表改成這次）或自成新組，並移到最前面
 * @param clusters - 目前各組（新到舊），不會被修改
 * @param f - 新失敗
 * @param idx - 所屬組 index；-1 表示自成新組
 * @returns 新的各組與這次所屬組的累積次數
 */
export function recordFailure(clusters: Cluster[], f: Failure, idx: number): { clusters: Cluster[]; count: number } {
  // STEP 01: 算這次所屬組的新次數
  const count = idx >= 0 ? clusters[idx].count + 1 : 1;
  // STEP 02: 這次放最前面，其餘照原順序，超過保留數丟最舊的
  const rest = clusters.filter((_, i) => i !== idx);
  return { clusters: [{ last: f, count }, ...rest].slice(0, MAX_CLUSTERS), count };
}

/**
 * 是否注入提示：累積到 REPEAT_TRIGGER 的倍數次（第 3、6、9…次）
 * @param count - 所屬組的累積次數
 * @returns true 表示注入
 */
export function shouldInject(count: number): boolean {
  return count % REPEAT_TRIGGER === 0;
}

/**
 * session 的 state 檔路徑
 * @param session - session ID
 * @returns state 檔絕對路徑
 */
export function statePath(session: string): string {
  return sessionStatePath(STATE_NAME, session);
}

/**
 * 讀 state；檔案不存在代表本 session 還沒有失敗
 * @param file - state 檔路徑
 * @returns 各組（新到舊）
 */
function loadClusters(file: string): Cluster[] {
  // STEP 01: 本 session 第一次失敗
  if (!fs.existsSync(file)) {
    return [];
  }
  // STEP 02: 格式不對直接丟錯，不默默重置計數
  const data: unknown = JSON.parse(fs.readFileSync(file, 'utf-8'));
  if (!Array.isArray(data)) {
    throw new Error(`state 檔格式錯誤：${file}`);
  }
  return data as Cluster[];
}

/**
 * 找新失敗所屬的組：字面相同直接歸組，否則與每組平行問 Jev
 * @param clusters - 目前各組
 * @param f - 新失敗
 * @returns 比對結果
 */
async function findMatch(clusters: Cluster[], f: Failure): Promise<Match> {
  // STEP 01: 字面完全相同就是同一失敗，不必問 Jev
  const exactIdx = clusters.findIndex((c) => c.last.command === f.command && c.last.error === f.error);
  if (exactIdx >= 0) {
    return { idx: exactIdx, conf: null, exact: true, verdicts: [], ms: 0 };
  }
  // STEP 02: 與每組平行比對；單次呼叫失敗已在 askJev 寫 log，該組視為不同
  const t0 = performance.now();
  const verdicts = await Promise.all(clusters.map(async (c) => {
    const res = await askJev(HOOK_NAME, { previous_failure: c.last, current_failure: f }, REPEAT_QUESTIONS);
    return res ? readAnswer(res.answers.same) : null;
  }));
  const ms = performance.now() - t0;
  // STEP 03: 挑所屬組
  const hit = pickMatch(verdicts);
  return { idx: hit ? hit.idx : -1, conf: hit ? hit.conf : null, exact: false, verdicts, ms };
}

/**
 * 組注入給 Claude 的換路徑提示
 * @param count - 所屬組的累積次數
 * @param m - 比對結果
 * @returns 提示文字
 */
function buildHint(count: number, m: Match): string {
  // 會注入代表已歸組：conf 為 null 只可能是字面相同
  const basis = m.conf === null ? '與前次輸出完全相同' : `Jev 判定與前次為同一問題，confidence ${m.conf.toFixed(2)}`;
  return [
    `[Jev 同錯偵測] 同一個失敗已出現第 ${count} 次（${basis}）。`,
    '依 ~/.claude/harness/judgment-matrix.md §1 S1：停止修改 → 用一句話重寫「我認為的根因」→ 換一層診斷（程式邏輯 → 資料結構 → 環境/工具鏈 → 執行時實況），不要在原地換個寫法再試。',
    '若這幾次失敗是刻意的（例如確認錯誤可重現），忽略本提示。',
  ].join('\n');
}

/**
 * 主流程：讀 stdin → 找所屬組 → 更新 state → 達門檻時注入
 */
async function main(): Promise<void> {
  // STEP 01: kill switch 與輸入檢查；使用者中斷不算失敗
  const input = JSON.parse(fs.readFileSync(0, 'utf-8')) as FailureInput;
  if (jevDisabled() || input.is_interrupt) {
    return;
  }
  if (typeof input.session_id !== 'string' || typeof input.tool_name !== 'string') {
    throw new Error('stdin 缺 session_id 或 tool_name');
  }
  // STEP 02: 讀 state，找所屬組
  const file = statePath(input.session_id);
  const f = describeFailure(input);
  const clusters = loadClusters(file);
  const m = await findMatch(clusters, f);
  // STEP 03: 更新 state、寫決策 log（不含失敗原文）
  const { clusters: next, count } = recordFailure(clusters, f, m.idx);
  writeJsonAtomic(file, next);
  const inject = shouldInject(count);
  logDecision({
    hook: HOOK_NAME, session: input.session_id, tool: input.tool_name, ms: Math.round(m.ms),
    compared: m.verdicts.length, exact: m.exact, matched: m.idx >= 0, same_conf: m.conf, verdicts: m.verdicts,
    count, injected: inject ? 1 : 0,
  });
  // STEP 04: 達門檻時以 additionalContext 注入（階段 0.2 實測此事件可送達 Claude）
  if (inject) {
    process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'PostToolUseFailure', additionalContext: buildHint(count, m) } }));
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
