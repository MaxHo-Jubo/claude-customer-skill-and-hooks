#!/usr/bin/env bun
import fs from 'fs';
import { askJev, jevDisabled, type JevAnswer, logDecision, readAnswer, topChoices } from './lib/jev-client';
import { NO_SKILL, routingQuestions } from './lib/jev-questions';

/**
 * Skill Activation Hook（UserPromptSubmit）— Jev 版
 *
 * 用 Jev 對 user prompt 一次問三題：該用哪個 skill、是否在糾正 Claude、任務類型，
 * 命中條件時以 plain stdout 注入提示（UserPromptSubmit 的 stdout 會成為 Claude 可見的 context）。
 * 任何錯誤一律 fail-open：不輸出、不擋 prompt，錯誤寫入 ~/.claude/state/jev/decisions.jsonl。
 * kill switch：環境變數 JEV_HOOKS_DISABLED=1。
 *
 * 門檻來源：tasks/jev-trial-plan.md 階段 1（jev-1.13.0 離線評估，user 2026-09-21 拍板）。
 * 題目或門檻改動 → 重跑 scripts/jev-eval/run-eval.ts。
 *
 * 沿革：舊版以 skill-rules.json 關鍵字比對，但從 process.env.CLAUDE_USER_CONTENT 讀 prompt——
 * Claude Code 從未提供該變數（2.1.278 binary 內 0 次出現），prompt 實際在 stdin JSON 的 `prompt` 欄位，
 * 舊版因此永遠讀到空字串直接放行，從未運作過。
 */

/** hook 名稱，寫入決策 log 用 */
const HOOK_NAME = 'A-routing';
/**
 * skill 推薦的 confidence 門檻。
 * 2026-09-21 選項改為動態讀取（user 層 27 個）後重跑評估（n=47）：t≥0.8 推薦 27 次、推錯 1 次（A09，conf 0.99，任何門檻都擋不掉），
 * 26 句正例全數召回；t=0.6／0.7 召回相同但多推錯 2／1 次（見 tasks/jev-trial-plan.md 2.2b）
 */
const SKILL_MIN_CONF = 0.8;
/** 送給 Jev 的 prompt 最大字元數：貼大段 log 時截斷，避免大量無關內容（jev-1.13 已知弱點）與外送過多資料 */
const MAX_PROMPT_CHARS = 2000;
/** 任務類型 → 注入的提示；未列出的類型（question / small_change / ops）不注入 */
const TASK_HINTS: Record<string, string> = {
  debug: '除錯任務：第一個修正性編輯前，先過 ~/.claude/harness/judgment-matrix.md §5（2-4 個候選根因＋各自否證檢查）',
  multi_step: '多步驟任務：GATE-1 先一句話重述需求請 user 確認；3+ 步驟走 GATE-2 plan mode',
};
/** 偵測到糾正時注入的提示 */
const CORRECTION_HINT = 'user 可能在糾正你：依 ~/.claude/harness/knowledge-protocol.md §2 當下寫 feedback memory，不等 session 結尾';
/**
 * correction 的行動下限（同 B、C）：判「是」且 confidence 達此值才注入。
 * 2026-09-21 上線當天兩筆誤報的 confidence 為 0.40、0.00（p=0.50 擲銅板也注入），user 選 0.3
 */
const CORRECTION_MIN_CONF = 0.3;

/** UserPromptSubmit stdin 中本 hook 用到的欄位 */
interface PromptInput {
  /** user 送出的 prompt */
  prompt?: string;
  /** session ID，寫入決策 log 用 */
  session_id?: string;
}

/**
 * 注入行的第二行：列出第一名與次高的機率（與 confidence 是不同量，分開標示）
 * @param top - topChoices 的結果
 * @returns 縮排的機率行
 */
function probLine([first, second]: ReturnType<typeof topChoices>): string {
  return `\n  機率：${first.label} ${first.p.toFixed(2)}／次高 ${second.label} ${second.p.toFixed(2)}`;
}

/**
 * 依 Jev 答案組出要注入的提示與決策摘要
 * @param answers - Jev 原始答案
 * @returns 提示（可能為空；skill、task_type 提示附上次高）與寫入 log 的摘要
 */
export function buildHints(answers: Record<string, JevAnswer>) {
  // STEP 01: 讀三題答案與兩個 choice 題的前兩名（缺題或缺機率會丟錯，由呼叫端 fail-open）
  const skill = readAnswer(answers.skill);
  const correction = readAnswer(answers.correction);
  const task = readAnswer(answers.task_type);
  const skillTop = topChoices(answers.skill);
  const taskTop = topChoices(answers.task_type);
  // STEP 02: 依門檻組提示
  const hints: string[] = [];
  if (skill.pred !== NO_SKILL && skill.conf >= SKILL_MIN_CONF) {
    hints.push(`建議 skill：${skill.pred}（Jev confidence ${skill.conf.toFixed(2)}）${probLine(skillTop)}`);
  }
  if (correction.pred === true && correction.conf >= CORRECTION_MIN_CONF) {
    hints.push(CORRECTION_HINT);
  }
  const taskHint = TASK_HINTS[String(task.pred)];
  if (taskHint) {
    hints.push(`${taskHint}（Jev confidence ${task.conf.toFixed(2)}）${probLine(taskTop)}`);
  }
  // STEP 03: 決策摘要（不含 prompt 原文）
  const summary = {
    skill: skill.pred, skill_conf: skill.conf, skill_2nd: skillTop[1].label, skill_2nd_p: skillTop[1].p,
    correction: correction.pred, correction_conf: correction.conf,
    task_type: task.pred, task_conf: task.conf, task_2nd: taskTop[1].label, task_2nd_p: taskTop[1].p,
  };
  return { hints, summary };
}

/**
 * 主流程：讀 stdin → 問 Jev → 命中條件時輸出提示
 */
async function main(): Promise<void> {
  // STEP 01: kill switch 與輸入檢查；slash command 已明確指定 skill，不必路由
  const input = JSON.parse(fs.readFileSync(0, 'utf-8')) as PromptInput;
  const prompt = (input.prompt ?? '').trim();
  if (jevDisabled() || !prompt || prompt.startsWith('/')) {
    return;
  }
  // STEP 02: 問 Jev（skill 選項依專案層 skillOverrides 過濾）；失敗已在 askJev 內寫 log，直接放行
  const questions = routingQuestions(process.env.CLAUDE_PROJECT_DIR);
  const res = await askJev(HOOK_NAME, { user_message: prompt.slice(0, MAX_PROMPT_CHARS) }, questions);
  if (!res) {
    return;
  }
  // STEP 03: 組提示、寫決策 log、輸出
  const { hints, summary } = buildHints(res.answers);
  logDecision({ hook: HOOK_NAME, session: input.session_id, ms: Math.round(res.ms), injected: hints.length, ...summary });
  if (hints.length > 0) {
    console.log(['[Jev 路由提示]', ...hints.map((h) => `- ${h}`)].join('\n'));
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
