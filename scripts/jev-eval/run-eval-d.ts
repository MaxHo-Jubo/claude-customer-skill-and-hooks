#!/usr/bin/env bun
import fs from 'fs';
import path from 'path';
import { readTier, ROUTE_TIMEOUT_MS, routeModel } from '../../hooks/agent-model-router';
import { loadJsonl, pct } from '../lib/eval-utils';
import { callJev, JEV_MODEL } from '../lib/jev-client';
import { type Tier, TIER_LABELS, TIER_QUESTIONS } from '../lib/jev-questions';
import { DATASET_PATH, type Row } from './extract-d-route';

/**
 * 掛載點 D 離線評估：派工模型等級題
 *
 * 讀 extract-d-route.ts 產出的資料集（state 目錄，含 brief 原文），逐筆問 Jev tier 題，
 * 以主模型明寫的 model 當 label，印出混淆矩陣、一致率、confidence 分佈與各門檻的路由統計。
 * 讀答案用 hook 的 readTier、路由與否用 hook 的 routeModel，評估的就是 hook 的決策邏輯；
 * 父模型固定視為 EVAL_PARENT_MODEL（fable，等級最高），所以只降不升的上限在評估中不會擋下任何候選。
 * 門檻挑選規則事先寫死（MAX_CHEAPER_RATE／MIN_ROUTED_N），不看結果再調。
 * 結果存 results-d-<時間>.json：只存統計與逐筆預測，不存 brief 原文（scripts/ 會被同步到公開 repo）。
 *
 * 已知偏差：資料集是「主模型有寫 model」的派工，hook 實際處理的是「沒寫 model」的派工，兩者分佈不同。
 *
 * 用法：bun ~/.claude/scripts/jev-eval/run-eval-d.ts
 */

/** 單次呼叫逾時（毫秒）；離線評估放寬 */
const TIMEOUT_MS = 10000;
/** 並行呼叫數（資料依索引輪流分到各條 lane，各 lane 內循序） */
const CONCURRENCY = 4;
/** 單筆失敗重試次數 */
const RETRIES = 1;
/** 門檻候選值 */
const THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8];
/** 挑門檻的規則：有路由的案例中「比主模型選的更便宜」（品質風險）比例上限 */
const MAX_CHEAPER_RATE = 0.1;
/** 挑門檻的規則：有路由的案例數下限，太少時比例不可信 */
const MIN_ROUTED_N = 20;
/** 評估時的父模型：固定視為 fable（資料集沒有記錄派工當下的主模型） */
const EVAL_PARENT_MODEL = 'fable';
/** confidence 分佈的分桶寬度 */
const CONF_BUCKET = 0.1;
/** confidence 分桶標籤的小數位數 */
const BUCKET_DIGITS = 1;
/** 浮點誤差容忍值：conf 剛好落在桶邊界時歸入上面那一桶 */
const FLOAT_EPS = 1e-9;
/** 延遲中位數的百分位 */
const MEDIAN = 50;
/** 延遲尾端的百分位 */
const P95 = 95;
/** 比例轉百分比的倍數 */
const PERCENT = 100;
/** 百分比顯示的小數位數 */
const PCT_DIGITS = 1;
/** 毫秒顯示的小數位數 */
const MS_DIGITS = 0;
/** 結果 JSON 的縮排空格數 */
const JSON_INDENT = 2;
/** 評估失敗時的 exit code */
const EXIT_FAILURE = 1;
/** 結果輸出目錄 */
const DIR = import.meta.dir;
/** 資料集每筆必須為字串的欄位（label 另驗） */
const ROW_STRING_FIELDS = ['id', 'subagent_type', 'description', 'prompt', 'session', 'ts'];

/** 單筆評估結果（不含原文） */
interface CaseResult {
  /** 案例 ID */
  id: string;
  /** 子代理類型 */
  subagent_type: string;
  /** label 等級 */
  label: Tier;
  /** Jev 預測等級 */
  pred: Tier;
  /** confidence */
  conf: number;
  /** 各等級機率 */
  probs: Record<string, number>;
  /** 次高等級 */
  second: string;
  /** 呼叫耗時毫秒 */
  ms: number;
}

/** 單筆最終結果：成功或失敗訊息恰有一個 */
type Outcome = { result: CaseResult; error: null } | { result: null; error: string };

/**
 * 等級 → [等級, 由便宜到貴的序號]（map 回呼）
 * @param t - 等級
 * @param i - 在 TIER_LABELS 中的索引
 * @returns [等級, 序號]
 */
function tierRankEntry(t: Tier, i: number): [Tier, number] {
  // STEP 01: 索引即序號
  return [t, i];
}

/** 各等級由便宜到貴的序號 */
const RANK = Object.fromEntries(TIER_LABELS.map(tierRankEntry)) as Record<Tier, number>;

/**
 * 是否為 TIER_LABELS 內的標籤
 * @param v - 任意值
 * @returns true 表示是合法等級
 */
function isTier(v: unknown): v is Tier {
  // STEP 01: 比對選項
  return (TIER_LABELS as readonly unknown[]).includes(v);
}

/**
 * 驗證資料集一行並轉型（loadJsonl 的 parse 回呼）；不合法時丟錯，由 loadJsonl 補上行號
 * @param raw - 解析後的原始值
 * @returns 資料集的一筆
 */
function parseRow(raw: unknown): Row {
  // STEP 01: 非 null 物件
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new Error('資料列不是 JSON 物件');
  }
  // STEP 02: 必要字串欄位與 label
  /** 資料列（欄位驗證前） */
  const r = raw as Record<string, unknown>;
  /**
   * 欄位是否不是字串（filter 回呼）
   * @param k - 欄位名稱
   * @returns true 表示缺漏或型別不符
   */
  const notString = (k: string): boolean => typeof r[k] !== 'string';
  /** 缺漏或型別不符的字串欄位 */
  const missing = ROW_STRING_FIELDS.filter(notString);
  if (missing.length > 0) {
    throw new Error(`資料列缺字串欄位：${missing.join(', ')}`);
  }
  if (!isTier(r.label)) {
    throw new Error(`label 不在 TIER_LABELS 內：${String(r.label)}`);
  }
  return r as unknown as Row;
}

/**
 * 問一筆，失敗時重試 RETRIES 次
 * @param r - 資料集一筆
 * @param attempt - 目前是第幾次重試（0 為首次）
 * @returns 評估結果；用完重試仍失敗時丟錯
 */
async function evalRow(r: Row, attempt = 0): Promise<CaseResult> {
  // STEP 01: 送出與 hook 相同格式的 state（資料集文字已遮罩＋截斷）
  try {
    /** Jev 原始答案與耗時 */
    const { answers, ms } = await callJev({ subagent_type: r.subagent_type, description: r.description, prompt: r.prompt }, TIER_QUESTIONS, TIMEOUT_MS);
    // STEP 01.01: 讀答案（與 hook 共用 readTier）
    /** tier 讀數 */
    const t = readTier(answers.tier);
    /** 各等級機率 */
    const probs = answers.tier?.probabilities;
    if (!probs) {
      throw new Error('tier 答案缺 probabilities');
    }
    return { id: r.id, subagent_type: r.subagent_type, label: r.label, pred: t.tier, conf: t.conf, probs, second: t.second, ms };
  } catch (err) {
    // STEP 01.02: 還有重試額度就再試，否則帶 ID 丟錯
    if (attempt < RETRIES) {
      return evalRow(r, attempt + 1);
    }
    throw new Error(`${r.id} 呼叫失敗：${String(err)}`);
  }
}

/**
 * 問一筆並把最終失敗轉成 Outcome，不中斷整批
 * @param r - 資料集一筆
 * @returns 成功結果或失敗訊息
 */
async function settle(r: Row): Promise<Outcome> {
  // STEP 01: 成功回結果，失敗回訊息
  try {
    return { result: await evalRow(r), error: null };
  } catch (err) {
    return { result: null, error: String(err) };
  }
}

/**
 * 循序跑完一條 lane
 * @param rows - 分到此 lane 的資料
 * @returns 各筆結果（依輸入順序）
 */
async function runLane(rows: Row[]): Promise<Outcome[]> {
  /**
   * 等前面的結果完成後再跑下一筆，回傳新陣列（reduce 回呼）
   * @param acc - 前面各筆的結果
   * @param r - 下一筆
   * @returns 加上這一筆後的新結果陣列
   */
  const step = async (acc: Promise<Outcome[]>, r: Row): Promise<Outcome[]> => [...(await acc), await settle(r)];
  // STEP 01: 以 reduce 串成循序執行
  return rows.reduce(step, Promise.resolve<Outcome[]>([]));
}

/**
 * 依索引把資料輪流分成 n 條 lane
 * @param rows - 資料集
 * @param n - lane 數
 * @returns 各 lane 的資料
 */
function toLanes(rows: Row[], n: number): Row[][] {
  /**
   * 第 k 條 lane 的資料（Array.from 的 map 回呼）
   * @param _ - 未使用
   * @param k - lane 索引
   * @returns 索引除以 n 餘 k 的資料
   */
  const lane = (_: unknown, k: number): Row[] => {
    /**
     * 索引是否屬於第 k 條 lane（filter 回呼）
     * @param __ - 未使用
     * @param i - 資料索引
     * @returns true 表示 i 除以 n 餘 k
     */
    const inLane = (__: Row, i: number): boolean => i % n === k;
    // STEP 01: 篩出該 lane 的資料
    return rows.filter(inLane);
  };
  // STEP 01: 產生 n 條 lane
  return Array.from({ length: n }, lane);
}

/**
 * Outcome 的成功結果（map 回呼）
 * @param o - 單筆結果
 * @returns 成功結果；失敗回 null
 */
function resultOf(o: Outcome): CaseResult | null {
  // STEP 01: 取欄位
  return o.result;
}

/**
 * Outcome 的失敗訊息（map 回呼）
 * @param o - 單筆結果
 * @returns 失敗訊息；成功回 null
 */
function errorOf(o: Outcome): string | null {
  // STEP 01: 取欄位
  return o.error;
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
 * 依案例 ID 排序（toSorted 回呼）
 * @param a - 結果 a
 * @param b - 結果 b
 * @returns 比較值
 */
function byId(a: CaseResult, b: CaseResult): number {
  // STEP 01: 字串比較
  return a.id.localeCompare(b.id);
}

/**
 * 以固定並行數跑完全部資料；單筆最終失敗記入 errors，不中斷整批
 * @param rows - 資料集
 * @returns 依 ID 排序的成功結果與失敗訊息
 */
async function runAll(rows: Row[]): Promise<{ results: CaseResult[]; errors: string[] }> {
  // STEP 01: 各 lane 並行、lane 內循序
  /** 全部 lane 的單筆結果 */
  const outcomes = (await Promise.all(toLanes(rows, CONCURRENCY).map(runLane))).flat();
  // STEP 02: 拆成成功與失敗
  return { results: outcomes.map(resultOf).filter(isNonNull).toSorted(byId), errors: outcomes.map(errorOf).filter(isNonNull) };
}

/**
 * 某門檻下的路由統計（路由與否由 hook 的 routeModel 決定，父模型固定 EVAL_PARENT_MODEL；pred=top 不路由）
 * @param rs - 評估結果
 * @param t - 門檻
 * @param hi - 區段上界（不含）；不給為累計（conf ≥ t 全部）
 * @returns 有路由比例、路由後一致率、更貴／更便宜比例
 */
function thresholdRow(rs: CaseResult[], t: number, hi = Infinity) {
  /**
   * 是否在此門檻（與區段上界）下被路由（filter 回呼）
   * @param r - 評估結果
   * @returns true 表示 hook 會填 model
   */
  const isRouted = (r: CaseResult): boolean => routeModel(r.pred, r.conf, t, EVAL_PARENT_MODEL).model !== null && r.conf < hi;
  // STEP 01: 篩出會被路由的案例
  /** 會被路由的案例 */
  const routed = rs.filter(isRouted);
  /** 路由數 */
  const n = routed.length;
  /**
   * 路由案例中符合條件的比例
   * @param f - 條件
   * @returns 比例；沒有路由案例時為 NaN
   */
  const rate = (f: (r: CaseResult) => boolean): number => {
    // STEP 01: 分母為路由數
    return n ? routed.filter(f).length / n : NaN;
  };
  // STEP 02: 各比例
  return {
    t, hi: Number.isFinite(hi) ? hi : null, n, routed: n / rs.length,
    agree: rate(isAgree),
    pricier: rate(isPricier),
    cheaper: rate(isCheaper),
  };
}

/**
 * 預測與 label 一致（filter 回呼）
 * @param r - 評估結果
 * @returns true 表示一致
 */
function isAgree(r: CaseResult): boolean {
  // STEP 01: 比對等級
  return r.pred === r.label;
}

/**
 * 預測比主模型選的更貴（filter 回呼）
 * @param r - 評估結果
 * @returns true 表示預測等級較高
 */
function isPricier(r: CaseResult): boolean {
  // STEP 01: 比序號
  return RANK[r.pred] > RANK[r.label];
}

/**
 * 預測比主模型選的更便宜（filter 回呼）
 * @param r - 評估結果
 * @returns true 表示預測等級較低
 */
function isCheaper(r: CaseResult): boolean {
  // STEP 01: 比序號
  return RANK[r.pred] < RANK[r.label];
}

/**
 * 混淆矩陣（label × pred）
 * @param rs - 評估結果
 * @returns label → pred → 筆數
 */
function confusionMatrix(rs: CaseResult[]): Record<Tier, Record<Tier, number>> {
  /**
   * 某 label 的一列（map 回呼）
   * @param l - label
   * @returns [label, pred → 筆數]
   */
  const rowFor = (l: Tier): [Tier, Record<Tier, number>] => {
    /**
     * 某格的筆數（map 回呼）
     * @param p - pred
     * @returns [pred, 筆數]
     */
    const cell = (p: Tier): [Tier, number] => {
      /**
       * 是否落在 (l, p) 這一格（filter 回呼）
       * @param r - 評估結果
       * @returns true 表示 label=l 且 pred=p
       */
      const inCell = (r: CaseResult): boolean => r.label === l && r.pred === p;
      // STEP 01: 計數
      return [p, rs.filter(inCell).length];
    };
    // STEP 01: 該列各格
    return [l, Object.fromEntries(TIER_LABELS.map(cell)) as Record<Tier, number>];
  };
  // STEP 01: 各列
  return Object.fromEntries(TIER_LABELS.map(rowFor)) as Record<Tier, Record<Tier, number>>;
}

/**
 * 各 label 的筆數與一致率
 * @param rs - 評估結果
 * @returns label → { n, agree }
 */
function perLabelAgree(rs: CaseResult[]): Record<Tier, { n: number; agree: number }> {
  /**
   * 某 label 的統計（map 回呼）
   * @param l - label
   * @returns [label, { n, agree }]
   */
  const statFor = (l: Tier): [Tier, { n: number; agree: number }] => {
    /**
     * 是否為此 label 的案例（filter 回呼）
     * @param r - 評估結果
     * @returns true 表示 label=l
     */
    const hasLabel = (r: CaseResult): boolean => r.label === l;
    // STEP 01: 該 label 的案例與一致率
    /** 此 label 的案例 */
    const sub = rs.filter(hasLabel);
    return [l, { n: sub.length, agree: sub.length ? sub.filter(isAgree).length / sub.length : NaN }];
  };
  // STEP 01: 各 label
  return Object.fromEntries(TIER_LABELS.map(statFor)) as Record<Tier, { n: number; agree: number }>;
}

/**
 * confidence 分佈（每 CONF_BUCKET 一桶）；桶索引用整數運算，避免 0.6 等邊界值因浮點誤差掉出所有桶
 * @param rs - 評估結果
 * @returns 各桶範圍與筆數
 */
function confDistribution(rs: CaseResult[]): { range: string; n: number }[] {
  // STEP 01: 以 reduce 累加，每次回傳新陣列
  /** 分桶數 */
  const buckets = Math.round(1 / CONF_BUCKET);
  /**
   * 把一筆加進對應的桶（reduce 回呼）
   * @param acc - 目前各桶筆數
   * @param r - 評估結果
   * @returns 新的各桶筆數
   */
  const addTo = (acc: number[], r: CaseResult): number[] => {
    // STEP 01: 算桶索引後以 with 產生新陣列
    /** 桶索引 */
    const i = Math.min(buckets - 1, Math.floor(r.conf * buckets + FLOAT_EPS));
    return acc.with(i, acc[i] + 1);
  };
  /** 各桶筆數 */
  const counts = rs.reduce(addTo, new Array<number>(buckets).fill(0));
  // STEP 02: 加總檢查
  if (counts.reduce(sum, 0) !== rs.length) {
    throw new Error('conf 分佈加總不等於案例數');
  }
  /**
   * 桶 → 範圍標籤與筆數（map 回呼）
   * @param n - 該桶筆數
   * @param i - 桶索引
   * @returns { range, n }
   */
  const label = (n: number, i: number) => ({ range: `${(i * CONF_BUCKET).toFixed(BUCKET_DIGITS)}-${((i + 1) * CONF_BUCKET).toFixed(BUCKET_DIGITS)}`, n });
  // STEP 03: 加上範圍標籤
  return counts.map(label);
}

/**
 * 加總（reduce 回呼）
 * @param a - 目前總和
 * @param b - 下一個值
 * @returns 新總和
 */
function sum(a: number, b: number): number {
  // STEP 01: 相加
  return a + b;
}

/**
 * 門檻列是否符合事先寫死的挑選規則（find 回呼）
 * @param x - 門檻列
 * @param x.n - 路由數
 * @param x.cheaper - 更便宜比例
 * @returns true 表示路由數 ≥ MIN_ROUTED_N 且更便宜比例 ≤ MAX_CHEAPER_RATE
 */
function meetsRule(x: { n: number; cheaper: number }): boolean {
  // STEP 01: 兩條件同時成立
  return x.n >= MIN_ROUTED_N && x.cheaper <= MAX_CHEAPER_RATE;
}

/**
 * 預測是否為 top（filter 回呼）
 * @param r - 評估結果
 * @returns true 表示 pred=top
 */
function isPredTop(r: CaseResult): boolean {
  // STEP 01: 比對等級
  return r.pred === 'top';
}

/**
 * 評估結果的耗時（map 回呼）
 * @param r - 評估結果
 * @returns 毫秒
 */
function msOf(r: CaseResult): number {
  // STEP 01: 取欄位
  return r.ms;
}

/**
 * 耗時是否超過 hook 的 ROUTE_TIMEOUT_MS（filter 回呼）
 * @param x - 毫秒
 * @returns true 表示在 hook 中會逾時
 */
function overRouteTimeout(x: number): boolean {
  // STEP 01: 比較
  return x > ROUTE_TIMEOUT_MS;
}

/**
 * 計算全部統計
 * @param rs - 評估結果
 * @returns 混淆矩陣、一致率、conf 分佈、門檻表與挑中的門檻
 */
function summarize(rs: CaseResult[]) {
  // STEP 01: 整體一致率（混淆矩陣、各 label 一致率、conf 分佈在 STEP 04 組回傳值時計算）
  /** 整體一致率 */
  const agree = rs.filter(isAgree).length / rs.length;
  /**
   * 累計門檻表的一列（map 回呼）
   * @param t - 門檻
   * @returns 該門檻的統計
   */
  const cumulative = (t: number) => thresholdRow(rs, t);
  /**
   * 相鄰門檻之間的區段（map 回呼）
   * @param t - 區段下界
   * @param i - 門檻索引
   * @returns 該區段的統計
   */
  const band = (t: number, i: number) => thresholdRow(rs, t, THRESHOLDS[i + 1]);
  // STEP 02: 門檻表（累計）＋區段（邊際）；依事先寫死的規則挑最低的達標門檻（路由最多）
  /** 累計門檻表 */
  const table = THRESHOLDS.map(cumulative);
  /** 相鄰門檻之間的區段統計 */
  const bands = THRESHOLDS.map(band);
  /** 規則挑中的門檻列；無門檻達標為 null */
  const pick = table.find(meetsRule) ?? null;
  /** 預測為 top（不路由）的比例 */
  const predTop = rs.filter(isPredTop).length / rs.length;
  // STEP 03: 延遲：超過 hook 實際逾時 ROUTE_TIMEOUT_MS 的呼叫在 hook 中會 fail-open
  /** 各筆呼叫耗時 */
  const ms = rs.map(msOf);
  /** 延遲統計與超過 ROUTE_TIMEOUT_MS 的比例 */
  const latency = { p50: pct(ms, MEDIAN), p95: pct(ms, P95), overRouteTimeout: ms.filter(overRouteTimeout).length / ms.length };
  // STEP 04: 組回傳值（混淆矩陣、各 label 一致率、conf 分佈在此計算）
  return {
    n: rs.length, confusion: confusionMatrix(rs), agree, perLabel: perLabelAgree(rs), confDist: confDistribution(rs),
    table, bands, pick, predTop, latency,
  };
}

/**
 * 比例轉百分比文字
 * @param x - 比例
 * @returns 百分比字串；NaN 為 '-'
 */
function pctText(x: number): string {
  // STEP 01: NaN 顯示為 -
  return Number.isNaN(x) ? '-' : `${(x * PERCENT).toFixed(PCT_DIGITS)}%`;
}

/**
 * conf 分桶的顯示文字（map 回呼）
 * @param b - 分桶
 * @param b.range - 範圍標籤
 * @param b.n - 筆數
 * @returns 「範圍:筆數」
 */
function bucketText(b: { range: string; n: number }): string {
  // STEP 01: 組字串
  return `${b.range}:${b.n}`;
}

/**
 * 寫一行到 stdout
 * @param line - 內容（不含換行）
 */
function out(line: string): void {
  // STEP 01: 補換行
  process.stdout.write(`${line}\n`);
}

/**
 * 印出報告
 * @param s - summarize 的結果
 * @param errors - 失敗訊息
 */
function printReport(s: ReturnType<typeof summarize>, errors: string[]): void {
  // STEP 01: 混淆矩陣與一致率
  out(`\n## D 派工等級（n=${s.n}，失敗 ${errors.length}，父模型固定視為 ${EVAL_PARENT_MODEL}）整體一致率 ${pctText(s.agree)}｜pred=top ${pctText(s.predTop)}`);
  out(`label\\pred | ${TIER_LABELS.join(' | ')} | 一致率`);
  for (const l of TIER_LABELS) {
    /**
     * 混淆矩陣 (l, p) 格的筆數（map 回呼）
     * @param p - pred
     * @returns 筆數
     */
    const cellOf = (p: Tier): number => s.confusion[l][p];
    out(`${l} | ${TIER_LABELS.map(cellOf).join(' | ')} | ${pctText(s.perLabel[l].agree)}（n=${s.perLabel[l].n}）`);
  }
  // STEP 02: conf 分佈與門檻表
  out(`\nconf 分佈：${s.confDist.map(bucketText).join(' ')}`);
  out('\n門檻 | 有路由 | 路由後一致率 | 比主模型更貴 | 比主模型更便宜');
  for (const x of s.table) {
    out(`${x.t} | ${x.n}（${pctText(x.routed)}） | ${pctText(x.agree)} | ${pctText(x.pricier)} | ${pctText(x.cheaper)}`);
  }
  out('\n區段（邊際） | 路由數 | 一致率 | 比主模型更貴 | 比主模型更便宜');
  for (const b of s.bands) {
    out(`[${b.t}, ${b.hi ?? 1}${b.hi ? ')' : ']'} | ${b.n} | ${pctText(b.agree)} | ${pctText(b.pricier)} | ${pctText(b.cheaper)}`);
  }
  out(`\n延遲（並行 ${CONCURRENCY}）：p50=${s.latency.p50.toFixed(MS_DIGITS)} p95=${s.latency.p95.toFixed(MS_DIGITS)} ms｜超過 hook 逾時 ROUTE_TIMEOUT_MS=${ROUTE_TIMEOUT_MS}ms：${pctText(s.latency.overRouteTimeout)}`);
  out(`\n挑選規則：路由 ≥ ${MIN_ROUTED_N} 筆且更便宜比例 ≤ ${pctText(MAX_CHEAPER_RATE)} 的最低門檻 → ${s.pick ? `t=${s.pick.t}` : '無門檻達標'}`);
  // STEP 03: 失敗明細
  for (const e of errors) {
    out(`  ✗ ${e}`);
  }
}

/**
 * 主流程：讀資料集 → 逐筆評估 → 統計 → 存結果
 * @returns 完成時 resolve；資料不合法或全數失敗時丟錯
 */
async function main(): Promise<void> {
  // STEP 01: 讀資料集（逐行驗證，不合法帶行號中止）並跑
  /** 資料集 */
  const rows = loadJsonl(DATASET_PATH, parseRow);
  /** 成功結果與失敗訊息 */
  const { results, errors } = await runAll(rows);
  if (results.length === 0) {
    throw new Error('沒有任何一筆成功');
  }
  // STEP 02: 統計與報告
  /** 統計結果 */
  const s = summarize(results);
  printReport(s, errors);
  // STEP 03: 存結果（不含 brief 原文）
  /** 結果檔路徑 */
  const file = path.join(DIR, `results-d-${new Date().toISOString().replace(/[:.]/g, '-')}.json`);
  /** 本次評估的挑選規則與前提（寫入結果檔） */
  const rule = { MAX_CHEAPER_RATE, MIN_ROUTED_N, parentModel: EVAL_PARENT_MODEL, routeTimeoutMs: ROUTE_TIMEOUT_MS };
  fs.writeFileSync(file, JSON.stringify({ model: JEV_MODEL, rule, summary: s, errors, results }, null, JSON_INDENT));
  out(`結果：${file}`);
}

if (import.meta.main) {
  try {
    await main();
  } catch (err) {
    process.stderr.write(`評估中斷：${err instanceof Error ? (err.stack ?? err.message) : String(err)}\n`);
    process.exit(EXIT_FAILURE);
  }
}
