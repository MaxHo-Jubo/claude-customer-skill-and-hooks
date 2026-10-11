#!/usr/bin/env bun
import fs from 'fs';
import os from 'os';
import path from 'path';
import { buildState, MAX_BRIEF_CHARS, type RoutedModel, TIER_MODEL } from '../../hooks/agent-model-router';
import type { Tier } from '../lib/jev-questions';

/**
 * 掛載點 D 評估資料集抽取：近 30 天主模型「明寫 model」的 Agent／Task 派工，以主模型的選擇當 label
 *
 * 掃 ~/.claude/projects/<專案>/<session>.jsonl 中 type=assistant 的 tool_use，依 tool_use id 去重（保留第一次出現）。
 * 文字欄位用 hook 的 buildState 處理（遮罩憑證＋截斷到 MAX_BRIEF_CHARS），與 hook 實際送出的內容一致；
 * 因此 MAX_BRIEF_CHARS 改動後必須重抽。prompt 缺漏或空白的派工不進資料集，計入 excluded.no_prompt。
 * JSON 解析錯誤一律帶「檔名:行號」中止；唯一例外是「檔案最後一行且沒有結尾換行」（正在寫入的 transcript），只計數。
 * 輸出存 ~/.claude/state/jev/eval/d-route.jsonl：prompt 含公司專案內容，不放 scripts/（會被 sync 到公開 repo）。
 *
 * 用法：bun ~/.claude/scripts/jev-eval/extract-d-route.ts
 */

/** 回溯天數 */
const LOOKBACK_DAYS = 30;
/** 一天的毫秒數 */
const DAY_MS = 86_400_000;
/** 資料集最少筆數：不到代表掃描範圍或欄位判斷有誤，不寫檔 */
const MIN_ROWS = 150;
/** 案例 ID 的前綴 */
const CASE_ID_PREFIX = 'D';
/** 案例 ID 數字部分的位數（不足補 0） */
const CASE_ID_WIDTH = 3;
/** 行號從 1 起算的位移 */
const LINE_BASE = 1;
/** transcript 根目錄 */
const PROJECTS_DIR = path.join(os.homedir(), '.claude', 'projects');
/** 資料集輸出路徑 */
export const DATASET_PATH = path.join(os.homedir(), '.claude', 'state', 'jev', 'eval', 'd-route.jsonl');
/** 派工工具名稱（舊版叫 Task） */
const AGENT_TOOLS = new Set(['Agent', 'Task']);
/** 解析前的粗篩字串：含 tool_use 的行才解析 */
const TOOL_USE_MARK = '"tool_use"';
/** 排除統計的 key：prompt 缺漏或空白 */
const EXCLUDED_NO_PROMPT = 'no_prompt';
/** 排除統計的 key：description 不是字串或 subagent_type 不是字串 */
const EXCLUDED_INVALID = 'invalid_input';
/** parseRecord 的回傳值：正在寫入的最後一行，略過並計數 */
const PARTIAL = Symbol('partial');
/** 抽取失敗時的 exit code */
const EXIT_FAILURE = 1;

/** transcript 檔名的副檔名 */
const TRANSCRIPT_EXT = '.jsonl';

/**
 * TIER_MODEL 中有對應 model 的項目（filter 回呼）
 * @param entry - [等級, model 或 null]
 * @returns true 表示該等級有填 model
 */
function hasRoutedModel(entry: [string, RoutedModel | null]): entry is [string, RoutedModel] {
  // STEP 01: 排除 top（null）
  return entry[1] !== null;
}

/**
 * [等級, model] 反轉成 [model, 等級]（map 回呼）
 * @param entry - [等級, model]
 * @returns [model, 等級]
 */
function swapEntry(entry: [string, RoutedModel]): [RoutedModel, Tier] {
  // STEP 01: 交換鍵值
  return [entry[1], entry[0] as Tier];
}

/** 主模型選的 model → label 等級，由 hook 的 TIER_MODEL 反推；不在表內的 model（fable 等）不收 */
const MODEL_TIER: Record<string, Tier> = Object.fromEntries(Object.entries(TIER_MODEL).filter(hasRoutedModel).map(swapEntry));

/** Agent／Task 工具輸入中抽取用到的欄位（transcript 原始資料，型別在分類時才驗證） */
interface ToolUseInput {
  /** 子代理類型：缺省或字串 */
  subagent_type?: unknown;
  /** 主模型寫的摘要：須為字串 */
  description?: unknown;
  /** 派工 brief：須為非空白字串 */
  prompt?: unknown;
}

/** 一筆明寫 model 的派工（尚未分類） */
interface Dispatch {
  /** tool_use id，去重用 */
  id: string;
  /** 主模型明寫的 model */
  model: string;
  /** 工具輸入 */
  input: ToolUseInput;
  /** session ID */
  session: string;
  /** 派工時間 */
  ts: string;
}

/** 單一 transcript 的掃描結果 */
interface TranscriptScan {
  /** 明寫 model 的派工 */
  dispatches: Dispatch[];
  /** 略過的「正在寫入的最後一行」數 */
  partial: number;
}

/** 資料集的一筆（run-eval-d.ts 共用） */
export interface Row {
  /** 案例 ID */
  id: string;
  /** 子代理類型（未指定為空字串） */
  subagent_type: string;
  /** 摘要（已遮罩） */
  description: string;
  /** brief（已遮罩＋截斷） */
  prompt: string;
  /** 主模型選擇對應的等級 */
  label: Tier;
  /** session ID */
  session: string;
  /** 派工時間 */
  ts: string;
}

/** 單筆派工的分類結果：收錄（尚未編號）或排除 */
type Classified = { row: Omit<Row, 'id'>; excludedKey: null } | { row: null; excludedKey: string };

/**
 * 是否為非 null、非陣列的物件
 * @param v - 任意值
 * @returns true 表示可當成 Record 讀欄位
 */
function isRecord(v: unknown): v is Record<string, unknown> {
  // STEP 01: 排除 null 與陣列
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * 是否不為 null（filter 回呼）
 * @param v - 任意值
 * @returns true 表示不是 null
 */
function isNonNull<T>(v: T | null): v is T {
  // STEP 01: 排除 null
  return v !== null;
}

/**
 * 列出近 LOOKBACK_DAYS 天內有修改的 transcript（mtime 預篩，逐筆再以 timestamp 精篩）
 * @param cutoff - 起算時間（epoch 毫秒）
 * @returns transcript 絕對路徑
 */
function listTranscripts(cutoff: number): string[] {
  /**
   * 專案目錄下的 transcript 路徑（flatMap 回呼）
   * @param d - PROJECTS_DIR 下的目錄項
   * @returns 該專案目錄的 .jsonl 絕對路徑；不是目錄回空陣列
   */
  const transcriptsIn = (d: fs.Dirent): string[] => {
    // STEP 01: 只看目錄，取其下的 .jsonl
    if (!d.isDirectory()) {
      return [];
    }
    /** 專案 transcript 目錄 */
    const dir = path.join(PROJECTS_DIR, d.name);
    /**
     * 檔名 → 絕對路徑（map 回呼）
     * @param f - 檔名
     * @returns 絕對路徑
     */
    const inDir = (f: string): string => path.join(dir, f);
    return fs.readdirSync(dir).filter(isTranscriptName).map(inDir);
  };
  /**
   * 是否在回溯範圍內修改過（filter 回呼）
   * @param f - 檔案路徑
   * @returns true 表示 mtime ≥ cutoff
   */
  const modifiedSince = (f: string): boolean => fs.statSync(f).mtimeMs >= cutoff;
  // STEP 01: 各專案目錄的 transcript，依 mtime 預篩
  return fs.readdirSync(PROJECTS_DIR, { withFileTypes: true }).flatMap(transcriptsIn).filter(modifiedSince);
}

/**
 * 是否為 transcript 檔名（filter 回呼）
 * @param f - 檔名
 * @returns true 表示副檔名為 .jsonl
 */
function isTranscriptName(f: string): boolean {
  // STEP 01: 比對副檔名
  return f.endsWith(TRANSCRIPT_EXT);
}

/**
 * 解析 transcript 一行
 * @param line - 一行文字
 * @param mayBePartial - 是否為「檔案最後一行且沒有結尾換行」
 * @param where - 錯誤訊息用的「檔名:行號」
 * @returns 解析結果；mayBePartial 且解析失敗回 PARTIAL，其他解析失敗丟錯
 */
function parseRecord(line: string, mayBePartial: boolean, where: string): unknown {
  // STEP 01: 解析；只有正在寫入的最後一行允許失敗
  try {
    return JSON.parse(line);
  } catch (err) {
    if (mayBePartial) {
      return PARTIAL;
    }
    throw new Error(`${where} JSON 解析失敗：${String(err)}`);
  }
}

/**
 * content 陣列的一個元素 → 明寫 model 的 Agent／Task 派工
 * @param c - content 元素（可能是 null 或任意型別）
 * @param session - session ID
 * @param ts - 該則記錄的時間
 * @returns 派工；不是明寫 model 的 Agent／Task tool_use 時回 null
 */
function toDispatch(c: unknown, session: string, ts: string): Dispatch | null {
  // STEP 01: 先確認是非 null 物件，再讀欄位
  if (!isRecord(c) || c.type !== 'tool_use' || typeof c.name !== 'string' || !AGENT_TOOLS.has(c.name)) {
    return null;
  }
  // STEP 02: 需要 id、物件型 input、非空 model
  if (typeof c.id !== 'string' || !isRecord(c.input) || typeof c.input.model !== 'string' || !c.input.model) {
    return null;
  }
  return { id: c.id, model: c.input.model, input: c.input, session, ts };
}

/**
 * 一則 transcript 記錄中的派工
 * @param rec - 解析後的記錄
 * @param file - transcript 路徑（記錄沒帶 sessionId 時以檔名當 session）
 * @param cutoff - 起算時間（epoch 毫秒）
 * @returns 明寫 model 的派工；不是回溯範圍內的 assistant 記錄回空陣列
 */
function recordDispatches(rec: unknown, file: string, cutoff: number): Dispatch[] {
  // STEP 01: 回溯範圍內、content 為陣列的 assistant 記錄
  if (!isRecord(rec) || rec.type !== 'assistant' || !isRecord(rec.message) || !Array.isArray(rec.message.content)) {
    return [];
  }
  /** 記錄時間（驗證前） */
  const ts = rec.timestamp;
  if (typeof ts !== 'string' || Date.parse(ts) < cutoff) {
    return [];
  }
  // STEP 02: 逐個 content 元素轉派工（transcript 檔名就是 session ID）
  /** session ID（記錄沒帶就用 transcript 檔名） */
  const session = typeof rec.sessionId === 'string' ? rec.sessionId : path.basename(file, TRANSCRIPT_EXT);
  /**
   * content 元素 → 派工（map 回呼）
   * @param c - content 元素
   * @returns 派工或 null
   */
  const toDispatchHere = (c: unknown): Dispatch | null => toDispatch(c, session, ts);
  return rec.message.content.map(toDispatchHere).filter(isNonNull);
}

/**
 * 掃一個 transcript
 * @param file - transcript 路徑
 * @param cutoff - 起算時間（epoch 毫秒）
 * @returns 明寫 model 的派工與略過的半行數
 */
function scanTranscript(file: string, cutoff: number): TranscriptScan {
  // STEP 01: 切行；檔尾沒有換行時，最後一行可能正在寫入
  /** transcript 全文 */
  const text = fs.readFileSync(file, 'utf-8');
  /** 各行 */
  const lines = text.split('\n');
  /** 可能正在寫入的最後一行索引；結尾有換行時為 -1 */
  const partialIdx = text.endsWith('\n') ? -1 : lines.length - 1;
  /**
   * 粗篩後解析一行（map 回呼）
   * @param line - 一行文字
   * @param i - 行索引（0 起算）
   * @returns 解析結果；不含 tool_use 回 null，正在寫入的最後一行回 PARTIAL
   */
  const parseLine = (line: string, i: number): unknown =>
    (line.includes(TOOL_USE_MARK) ? parseRecord(line, i === partialIdx, `${file}:${i + LINE_BASE}`) : null);
  /**
   * 解析結果 → 派工（flatMap 回呼）
   * @param rec - 解析結果
   * @returns 派工
   */
  const dispatchesOf = (rec: unknown): Dispatch[] => (rec === PARTIAL ? [] : recordDispatches(rec, file, cutoff));
  // STEP 02: 逐行解析後取派工
  /** 各行解析結果 */
  const records = lines.map(parseLine);
  return { dispatches: records.flatMap(dispatchesOf), partial: records.filter(isPartial).length };
}

/**
 * 是否為略過的半行（filter 回呼）
 * @param r - parseLine 的結果
 * @returns true 表示是 PARTIAL
 */
function isPartial(r: unknown): boolean {
  // STEP 01: 比對哨兵值
  return r === PARTIAL;
}

/**
 * 分類一筆派工：model 不在對照表、prompt 缺漏或空白、其他欄位型別不符都排除
 * @param d - 派工
 * @returns 收錄的列（尚未編號）或排除的 key
 */
function classify(d: Dispatch): Classified {
  // STEP 01: 不在對照表的 model 以 model 名稱計數
  if (!Object.hasOwn(MODEL_TIER, d.model)) {
    return { row: null, excludedKey: d.model };
  }
  // STEP 02: prompt 必須是非空白字串（buildState 對空 prompt 會丟錯，這裡先分流計數）
  /** 待驗證的工具輸入欄位 */
  const { prompt, description, subagent_type } = d.input;
  if (typeof prompt !== 'string' || !prompt.trim()) {
    return { row: null, excludedKey: EXCLUDED_NO_PROMPT };
  }
  if (typeof description !== 'string' || (subagent_type !== undefined && typeof subagent_type !== 'string')) {
    return { row: null, excludedKey: EXCLUDED_INVALID };
  }
  // STEP 03: 與 hook 相同的遮罩＋截斷
  /** 遮罩＋截斷後的 state */
  const s = buildState({ subagent_type, description, prompt });
  return { row: { ...s, label: MODEL_TIER[d.model], session: d.session, ts: d.ts }, excludedKey: null };
}

/**
 * 案例 ID：前綴＋補零序號
 * @param i - 收錄順序（0 起算）
 * @returns 案例 ID（如 D001）
 */
function caseId(i: number): string {
  // STEP 01: 序號 1 起算並補零
  return `${CASE_ID_PREFIX}${String(i + 1).padStart(CASE_ID_WIDTH, '0')}`;
}

/**
 * 計數累加（reduce 回呼）
 * @param acc - 目前的計數
 * @param key - 要 +1 的 key
 * @returns 新的計數物件（不修改 acc）
 */
function countKey(acc: Record<string, number>, key: string): Record<string, number> {
  // STEP 01: 以 spread 產生新物件
  return { ...acc, [key]: (acc[key] ?? 0) + 1 };
}

/**
 * 掃描結果的派工（flatMap 回呼）
 * @param s - 單一 transcript 的掃描結果
 * @returns 派工
 */
function dispatchesOfScan(s: TranscriptScan): Dispatch[] {
  // STEP 01: 取欄位
  return s.dispatches;
}

/**
 * 派工的去重 key（Map.groupBy 回呼）
 * @param d - 派工
 * @returns tool_use id
 */
function dispatchId(d: Dispatch): string {
  // STEP 01: 取欄位
  return d.id;
}

/**
 * 同 id 派工群組的第一筆（map 回呼）
 * @param g - 同 id 的派工（依出現順序，至少一筆）
 * @returns 第一次出現的那筆
 */
function firstOfGroup(g: Dispatch[]): Dispatch {
  // STEP 01: 取第一筆
  return g[0];
}

/**
 * 累加半行數（reduce 回呼）
 * @param n - 目前總數
 * @param s - 單一 transcript 的掃描結果
 * @returns 新總數
 */
function sumPartial(n: number, s: TranscriptScan): number {
  // STEP 01: 相加
  return n + s.partial;
}

/**
 * 分類結果的收錄列（map 回呼）
 * @param c - 分類結果
 * @returns 收錄列；被排除回 null
 */
function rowOf(c: Classified): Omit<Row, 'id'> | null {
  // STEP 01: 取欄位
  return c.row;
}

/**
 * 分類結果的排除 key（map 回呼）
 * @param c - 分類結果
 * @returns 排除 key；被收錄回 null
 */
function excludedKeyOf(c: Classified): string | null {
  // STEP 01: 取欄位
  return c.excludedKey;
}

/**
 * 收錄列加上案例 ID（map 回呼）
 * @param r - 收錄列
 * @param i - 收錄順序（0 起算）
 * @returns 資料集的一筆
 */
function withCaseId(r: Omit<Row, 'id'>, i: number): Row {
  // STEP 01: ID 放第一個欄位
  return { id: caseId(i), ...r };
}

/**
 * 資料列的 label（map 回呼）
 * @param r - 資料列
 * @returns label
 */
function labelOf(r: Row): string {
  // STEP 01: 取欄位
  return r.label;
}

/**
 * 資料列序列化成一行 JSON（map 回呼）
 * @param r - 資料列
 * @returns JSON 字串
 */
function toJsonLine(r: Row): string {
  // STEP 01: 序列化
  return JSON.stringify(r);
}

/**
 * 主流程：掃 transcript → 去重 → 依 model 標 label → 寫資料集
 * @returns 無；資料不足或解析錯誤時丟錯
 */
function main(): void {
  // STEP 01: 掃描並依 tool_use id 去重（Map.groupBy 保留第一次出現的順序與那一筆）
  /** 回溯起算時間（epoch 毫秒） */
  const cutoff = Date.now() - LOOKBACK_DAYS * DAY_MS;
  /**
   * 掃一個 transcript（map 回呼）
   * @param f - transcript 路徑
   * @returns 掃描結果
   */
  const scan = (f: string): TranscriptScan => scanTranscript(f, cutoff);
  /** 各 transcript 的掃描結果 */
  const scans = listTranscripts(cutoff).map(scan);
  /** 去重後的派工 */
  const seen = [...Map.groupBy(scans.flatMap(dispatchesOfScan), dispatchId).values()].map(firstOfGroup);
  /** 略過的「正在寫入的最後一行」總數 */
  const partialLines = scans.reduce(sumPartial, 0);
  // STEP 02: 分類、編號、統計
  /** 各派工的分類結果 */
  const classified = seen.map(classify);
  /** 收錄的資料列 */
  const rows = classified.map(rowOf).filter(isNonNull).map(withCaseId);
  /** 排除原因 → 筆數 */
  const excluded = classified.map(excludedKeyOf).filter(isNonNull).reduce(countKey, {});
  /** label → 筆數 */
  const byLabel = rows.map(labelOf).reduce(countKey, {});
  process.stdout.write(`明寫 model 的派工 ${seen.length} 筆（去重後）｜收錄 ${rows.length}｜label ${JSON.stringify(byLabel)}｜排除 ${JSON.stringify(excluded)}｜略過寫入中的末行 ${partialLines}｜截斷上限 ${MAX_BRIEF_CHARS}\n`);
  if (rows.length < MIN_ROWS) {
    throw new Error(`只抽到 ${rows.length} 筆（< ${MIN_ROWS}），掃描範圍或欄位判斷可能有誤，不寫檔`);
  }
  // STEP 03: 寫檔
  fs.mkdirSync(path.dirname(DATASET_PATH), { recursive: true });
  fs.writeFileSync(DATASET_PATH, rows.map(toJsonLine).join('\n') + '\n');
  process.stdout.write(`資料集：${DATASET_PATH}\n`);
}

if (import.meta.main) {
  try {
    main();
  } catch (err) {
    process.stderr.write(`抽取中斷：${err instanceof Error ? (err.stack ?? err.message) : String(err)}\n`);
    process.exit(EXIT_FAILURE);
  }
}
