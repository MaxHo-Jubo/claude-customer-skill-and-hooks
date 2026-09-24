#!/usr/bin/env bun
import fs from 'fs';
import path from 'path';
import { callJev, JEV_MODEL, type JevAnswer, readAnswer } from '../lib/jev-client';
import { CLAIM_QUESTIONS, type JevQuestion, REPEAT_QUESTIONS, routingQuestions } from '../lib/jev-questions';

/**
 * Jev 試用階段 1.2：離線評估
 *
 * 讀 a-routing / b-claims / c-repeat 三份評估集，以 HTTP 直接呼叫 TypeSafe systemOne，
 * 印出各題準確率、confidence 門檻表、錯誤案例與延遲；原始結果存 results-<時間>.json。
 * 門檻挑選規則事先寫死（THRESHOLDS / MIN_PRECISION / MIN_COVERAGE），不看結果再調。
 *
 * 用法：bun ~/.claude/scripts/jev-eval/run-eval.ts
 */

/** 單次呼叫逾時（毫秒）；離線評估放寬，hook 用 jev-client 的 HOOK_TIMEOUT_MS */
const TIMEOUT_MS = 10000;
/** 門檻候選值 */
const THRESHOLDS = [0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95];
/** 及格線：門檻以上的預測準確率 */
const MIN_PRECISION = 0.9;
/** 及格線：門檻以上涵蓋的案例比例 */
const MIN_COVERAGE = 0.5;
/** 決定性檢查要重跑的案例數（取 A 的前幾筆） */
const REPEAT_CHECK_N = 3;
/** 評估集目錄 */
const DIR = import.meta.dir;

/** 單一案例的評估結果 */
interface CaseResult {
  /** 案例 ID */
  id: string;
  /** 標準答案，key 為題名 */
  truth: Record<string, string | boolean>;
  /** Jev 預測 */
  pred: Record<string, string | boolean>;
  /** 各題 confidence（noul 以 |2p-1| 換算） */
  conf: Record<string, number>;
  /** 呼叫耗時毫秒 */
  ms: number;
  /** 原始答案 */
  raw: Record<string, JevAnswer>;
}

/** 單一資料集的設定 */
interface Suite {
  /** 資料集名稱 */
  name: string;
  /** jsonl 檔名 */
  file: string;
  /** 題目 */
  questions: Record<string, JevQuestion>;
  /** 由一筆資料組出 state */
  toState: (row: Record<string, unknown>) => unknown;
}

/** 三個掛載點的評估設定；A 不帶專案目錄，skill 選項只套 user 層 skillOverrides */
const SUITES: Suite[] = [
  { name: 'A 路由', file: 'a-routing.jsonl', questions: routingQuestions(), toState: (r) => ({ user_message: r.prompt }) },
  { name: 'B 完成宣告', file: 'b-claims.jsonl', questions: CLAIM_QUESTIONS, toState: (r) => ({ assistant_message: r.message }) },
  { name: 'B 長文', file: 'b-long.jsonl', questions: CLAIM_QUESTIONS, toState: (r) => ({ assistant_message: r.message }) },
  { name: 'C 同錯', file: 'c-repeat.jsonl', questions: REPEAT_QUESTIONS, toState: (r) => ({ previous_failure: r.previous, current_failure: r.current }) },
];

/**
 * 讀 jsonl 評估集
 * @param file - 檔名（相對 DIR）
 * @returns 每行一筆物件
 */
function loadJsonl(file: string): Record<string, unknown>[] {
  const lines = fs.readFileSync(path.join(DIR, file), 'utf-8').split('\n');
  return lines.filter((l) => l.trim()).map((l) => JSON.parse(l) as Record<string, unknown>);
}

/**
 * 逐筆跑一個資料集
 * @param suite - 資料集設定
 * @returns 每筆的評估結果
 */
async function runSuite(suite: Suite): Promise<CaseResult[]> {
  const out: CaseResult[] = [];
  for (const row of loadJsonl(suite.file)) {
    // STEP 01: 呼叫
    const { answers, ms } = await callJev(suite.toState(row), suite.questions, TIMEOUT_MS);
    // STEP 02: 逐題對照標準答案
    const res: CaseResult = { id: String(row.id), truth: {}, pred: {}, conf: {}, ms, raw: answers };
    for (const q of Object.keys(suite.questions)) {
      const { pred, conf } = readAnswer(answers[q]);
      res.truth[q] = row[q] as string | boolean;
      res.pred[q] = pred;
      res.conf[q] = conf;
    }
    out.push(res);
  }
  return out;
}

/**
 * 單題門檻表，並依事先寫死的規則挑門檻：precision ≥ MIN_PRECISION 的最低門檻
 * @param rs - 評估結果
 * @param q - 題名
 * @returns 整體準確率、門檻表、挑中的門檻列、是否及格
 */
function evaluate(rs: CaseResult[], q: string) {
  const acc = rs.filter((r) => r.pred[q] === r.truth[q]).length / rs.length;
  const table = THRESHOLDS.map((t) => {
    const kept = rs.filter((r) => r.conf[q] >= t);
    const ok = kept.filter((r) => r.pred[q] === r.truth[q]).length;
    return { t, n: kept.length, coverage: kept.length / rs.length, precision: kept.length ? ok / kept.length : NaN };
  });
  const pick = table.find((x) => x.n > 0 && x.precision >= MIN_PRECISION);
  return { acc, table, pick, pass: pick !== undefined && pick.coverage >= MIN_COVERAGE };
}

/**
 * 印出單一資料集的報告
 * @param suite - 資料集設定
 * @param rs - 評估結果
 */
function printSuite(suite: Suite, rs: CaseResult[]): void {
  console.log(`\n## ${suite.name}（n=${rs.length}）`);
  for (const q of Object.keys(suite.questions)) {
    // STEP 01: 總覽與門檻表
    const e = evaluate(rs, q);
    const pickText = e.pick ? `t=${e.pick.t} precision=${e.pick.precision.toFixed(2)} coverage=${e.pick.coverage.toFixed(2)}` : '無門檻達標';
    console.log(`\n### ${q}：acc=${e.acc.toFixed(2)}｜門檻 ${pickText}｜${e.pass ? 'PASS' : 'FAIL'}`);
    console.log(e.table.map((x) => `  t≥${x.t}: n=${x.n} cov=${x.coverage.toFixed(2)} prec=${Number.isNaN(x.precision) ? '-' : x.precision.toFixed(2)}`).join('\n'));
    // STEP 02: 錯誤案例
    for (const r of rs.filter((x) => x.pred[q] !== x.truth[q])) {
      console.log(`  ✗ ${r.id} truth=${r.truth[q]} pred=${r.pred[q]} conf=${r.conf[q].toFixed(2)}`);
    }
  }
}

/**
 * B 的最終擋下決策：claims 為是且 evidence 為否
 * @param name - 資料集名稱
 * @param rs - B 的評估結果
 */
function printBlockDecision(name: string, rs: CaseResult[]): void {
  const block = (x: Record<string, string | boolean>) => x.claims === true && x.evidence === false;
  const wrongBlock = rs.filter((r) => block(r.pred) && !block(r.truth)).map((r) => r.id);
  const missed = rs.filter((r) => !block(r.pred) && block(r.truth)).map((r) => r.id);
  const ok = rs.length - wrongBlock.length - missed.length;
  console.log(`\n### ${name} 擋下決策：${ok}/${rs.length} 正確｜誤擋 ${wrongBlock.join(',') || '無'}｜漏擋 ${missed.join(',') || '無'}`);
}

/**
 * 決定性檢查：同一輸入再呼叫一次，比較機率差
 * @param suite - A 的設定
 * @param first - 第一次的結果
 * @returns 最大機率差
 */
async function checkDeterminism(suite: Suite, first: CaseResult[]): Promise<number> {
  let maxDiff = 0;
  const rows = loadJsonl(suite.file).slice(0, REPEAT_CHECK_N);
  for (const [i, row] of rows.entries()) {
    const { answers } = await callJev(suite.toState(row), suite.questions, TIMEOUT_MS);
    for (const [q, a] of Object.entries(answers)) {
      const prev = first[i].raw[q];
      const cur = a.type === 'noul' ? { yes: a.noul ?? NaN } : (a.probabilities ?? {});
      const old = prev.type === 'noul' ? { yes: prev.noul ?? NaN } : (prev.probabilities ?? {});
      for (const k of Object.keys(cur)) {
        maxDiff = Math.max(maxDiff, Math.abs(cur[k] - old[k]));
      }
    }
  }
  return maxDiff;
}

/**
 * 取百分位數（nearest-rank）
 * @param xs - 數列
 * @param p - 百分位（0-100）
 * @returns 該百分位的值
 */
function pct(xs: number[], p: number): number {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1)];
}

try {
  // STEP 01: 依序跑三個資料集
  const all: Record<string, CaseResult[]> = {};
  for (const s of SUITES) {
    all[s.name] = await runSuite(s);
    printSuite(s, all[s.name]);
  }
  for (const s of SUITES.filter((x) => x.questions === CLAIM_QUESTIONS)) {
    printBlockDecision(s.name, all[s.name]);
  }
  // STEP 02: 決定性與延遲
  const diff = await checkDeterminism(SUITES[0], all[SUITES[0].name]);
  const ms = Object.values(all).flat().map((r) => r.ms);
  console.log(`\n## 其他\n決定性：前 ${REPEAT_CHECK_N} 筆重跑，最大機率差 ${diff.toFixed(4)}`);
  console.log(`延遲（同一 process，連線重用）：n=${ms.length} p50=${pct(ms, 50).toFixed(0)} p95=${pct(ms, 95).toFixed(0)} ms`);
  // STEP 03: 存原始結果
  const out = path.join(DIR, `results-${new Date().toISOString().replace(/[:.]/g, '-')}.json`);
  fs.writeFileSync(out, JSON.stringify({ model: JEV_MODEL, results: all }, null, 2));
  console.log(`原始結果：${out}`);
} catch (err) {
  console.error('評估中斷：', err);
  process.exit(1);
}
