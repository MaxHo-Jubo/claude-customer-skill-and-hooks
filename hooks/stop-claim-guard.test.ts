import { describe, expect, test } from 'bun:test';
import { buildReason, canBlock, MAX_BLOCKS, shouldBlock, shouldSkip } from './stop-claim-guard';

/** 產生單題判定 */
const v = (pred: boolean, conf: number) => ({ pred, conf });

describe('shouldBlock', () => {
  test('宣稱完成且無證據、兩題都達行動下限 → 擋', () => {
    expect(shouldBlock(v(true, 0.9), v(false, 0.9))).toBe(true);
  });
  test('剛好等於行動下限 → 擋', () => {
    expect(shouldBlock(v(true, 0.3), v(false, 0.3))).toBe(true);
  });
  test('claims 低於行動下限 → 放行', () => {
    expect(shouldBlock(v(true, 0.29), v(false, 0.9))).toBe(false);
  });
  test('evidence 低於行動下限 → 放行（B02 翻盤的情況）', () => {
    expect(shouldBlock(v(true, 0.84), v(false, 0.02))).toBe(false);
  });
  test('有證據 → 放行', () => {
    expect(shouldBlock(v(true, 0.9), v(true, 0.9))).toBe(false);
  });
  test('沒宣稱完成 → 放行', () => {
    expect(shouldBlock(v(false, 0.9), v(false, 0.9))).toBe(false);
  });
});

describe('canBlock', () => {
  test(`同 session 擋滿 ${MAX_BLOCKS} 次後不再擋`, () => {
    expect([0, 1, 2, 3].map(canBlock)).toEqual([true, true, false, false]);
  });
});

describe('shouldSkip', () => {
  /** 一般會被檢查的 Stop 輸入 */
  const base = { hook_event_name: 'Stop', session_id: 's1', stop_hook_active: false, last_assistant_message: '修好了' };
  test('一般 Stop 事件不略過', () => {
    expect(shouldSkip(base)).toBe(false);
  });
  test('stop_hook_active（已被 Stop hook 擋過、正在續跑）→ 略過，防迴圈', () => {
    expect(shouldSkip({ ...base, stop_hook_active: true })).toBe(true);
  });
  test('不是 Stop 事件（誤掛到 SubagentStop 等）→ 略過', () => {
    expect(shouldSkip({ ...base, hook_event_name: 'SubagentStop' })).toBe(true);
  });
  test('沒有回覆文字 → 略過', () => {
    expect(shouldSkip({ ...base, last_assistant_message: '   ' })).toBe(true);
    expect(shouldSkip({ ...base, last_assistant_message: undefined })).toBe(true);
  });
});

describe('buildReason', () => {
  test('含次數、判準出處與誤判時的出口', () => {
    const r = buildReason(1, v(true, 0.9), v(false, 0.8));
    expect(r).toContain(`第 1/${MAX_BLOCKS} 次`);
    expect(r).toContain('judgment-matrix.md §2');
    expect(r).toContain('直接再結束一次');
  });
});
