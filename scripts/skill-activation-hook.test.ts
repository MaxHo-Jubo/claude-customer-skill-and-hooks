import { describe, expect, test } from 'bun:test';
import type { JevAnswer } from './lib/jev-client';
import { topChoices } from './lib/jev-client';
import { buildHints } from './skill-activation-hook';

/** 產生 choice 題答案 */
const choice = (label: string, confidence: number, probabilities: Record<string, number>): JevAnswer => ({ type: 'choice', choice: label, confidence, probabilities });
/** 產生 noul 題答案（p 為「是」的機率） */
const noul = (p: number): JevAnswer => ({ type: 'noul', noul: p });
/** 不觸發任何提示的預設三題答案 */
const quiet = {
  skill: choice('none', 0.98, { none: 0.98, jira: 0.02 }),
  correction: noul(0.1),
  task_type: choice('question', 0.9, { question: 0.9, ops: 0.1 }),
};

describe('topChoices', () => {
  test('依機率排序取前兩名', () => {
    expect(topChoices(choice('b', 0.5, { a: 0.1, b: 0.6, c: 0.3 }))).toEqual([{ label: 'b', p: 0.6 }, { label: 'c', p: 0.3 }]);
  });
  test('缺 probabilities 直接丟錯', () => {
    expect(() => topChoices({ type: 'choice', choice: 'a', confidence: 1 })).toThrow();
  });
});

describe('buildHints：skill', () => {
  test('推薦 skill 時附上機率與次高', () => {
    const { hints } = buildHints({ ...quiet, skill: choice('weekly-review', 0.99, { 'weekly-review': 0.99, 'neat-freak': 0.01, none: 0 }) });
    expect(hints).toEqual(['建議 skill：weekly-review（Jev confidence 0.99）\n  機率：weekly-review 0.99／次高 neat-freak 0.01']);
  });
  test('confidence 未達門檻不推薦', () => {
    expect(buildHints({ ...quiet, skill: choice('jira', 0.62, { jira: 0.7, none: 0.3 }) }).hints).toEqual([]);
  });
});

describe('buildHints：task_type', () => {
  test('debug 提示附上機率與次高', () => {
    const { hints } = buildHints({ ...quiet, task_type: choice('debug', 0.56, { debug: 0.56, multi_step: 0.42, ops: 0.02 }) });
    expect(hints).toHaveLength(1);
    expect(hints[0]).toStartWith('除錯任務：');
    expect(hints[0]).toEndWith('（Jev confidence 0.56）\n  機率：debug 0.56／次高 multi_step 0.42');
  });
  test('question 類型不注入', () => {
    expect(buildHints(quiet).hints).toEqual([]);
  });
});

describe('buildHints：correction 行動下限 0.3', () => {
  test('p=0.50（conf 0.00，今天第二筆誤報）不注入', () => {
    expect(buildHints({ ...quiet, correction: noul(0.5) }).hints).toEqual([]);
  });
  test('p=0.64（conf 0.28）不注入', () => {
    expect(buildHints({ ...quiet, correction: noul(0.64) }).hints).toEqual([]);
  });
  test('p=0.70（conf 0.40）注入', () => {
    expect(buildHints({ ...quiet, correction: noul(0.7) }).hints).toHaveLength(1);
  });
});

describe('buildHints：決策摘要', () => {
  test('記錄 skill 與 task_type 的次高', () => {
    const { summary } = buildHints(quiet);
    expect(summary).toMatchObject({ skill_2nd: 'jira', skill_2nd_p: 0.02, task_2nd: 'ops', task_2nd_p: 0.1 });
  });
});
