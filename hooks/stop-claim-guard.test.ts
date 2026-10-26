import { describe, expect, test } from 'bun:test';
import { buildReason, canBlock, isWaitingForBackground, MAX_BLOCKS, shouldBlock, shouldSkip } from './stop-claim-guard';

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

describe('isWaitingForBackground', () => {
  test('S2 實例：「修正進行中、等探針通知」→ 等待中', () => {
    expect(isWaitingForBackground('codex review 的處理方向已定，修正進行中，表格突變探針在背景循序跑（等探針通知，期間不開其他重工作）')).toBe(true);
  });
  test('等 agent 回報 → 等待中', () => {
    expect(isWaitingForBackground('已派出三個檢討 agent，等 agent 回報後再合併')).toBe(true);
  });
  test('背景任務執行中 → 等待中', () => {
    expect(isWaitingForBackground('目前背景任務執行中，先不下結論')).toBe(true);
  });
  test('只有 Jira 狀態字樣「進行中」→ 不算等待（避免誤放行真正的完成宣告）', () => {
    expect(isWaitingForBackground('已修好，測試全綠。Jira 狀態：進行中')).toBe(false);
  });
  test('一般完成宣告 → 不算等待', () => {
    expect(isWaitingForBackground('根因是 A，已改 B，測試 12 pass 0 fail')).toBe(false);
  });
  test('「等於」「相等」這類無關字樣 → 不算等待', () => {
    expect(isWaitingForBackground('兩者相等，回傳值等於 5，結果已寫入')).toBe(false);
  });
  test('只看結尾：等待字樣在很前面、結尾是完成宣告 → 不算等待', () => {
    expect(isWaitingForBackground(`先前在等探針通知。${'已確認。'.repeat(120)}全部完成，測試通過。`)).toBe(false);
  });
  test('否定：「不必等待 agent 回報，已修好」→ 不算等待', () => {
    expect(isWaitingForBackground('不必等待 agent 回報，已修好，測試 12 pass')).toBe(false);
  });
  test('否定的其他寫法（不用／無需／不需／毋須／不再）→ 不算等待', () => {
    for (const neg of ['不用', '無需', '不需', '毋須', '不再']) {
      expect(isWaitingForBackground(`${neg}等探針通知，結果已確認`)).toBe(false);
    }
  });
  test('狀態已改變：「原本在等探針通知，現在已全部完成」→ 不算等待', () => {
    expect(isWaitingForBackground('原本在等探針通知，現在已全部完成')).toBe(false);
  });
  test('等待字樣在前一句、最後一句是完成宣告（短訊息，不靠長度推出窗口）→ 不算等待', () => {
    expect(isWaitingForBackground('先前在等探針通知。全部完成，測試通過。')).toBe(false);
  });
  test('同一句內等待字樣與完成宣告並存 → 不算等待（寧可多檢查一次，不放行未驗證的宣告）', () => {
    expect(isWaitingForBackground('等 agent 回報，另外 X 已修好，測試全綠')).toBe(false);
  });
  test('最後一句才是等待、前面有別的敘述 → 仍算等待', () => {
    expect(isWaitingForBackground('已讀完三個檔案，找到兩個候選。agent 還在跑，等通知')).toBe(true);
  });
});

describe('shouldSkip：等待背景任務', () => {
  test('回覆結尾自述等背景通知 → 略過（中途回報不是完成宣告）', () => {
    expect(shouldSkip({ hook_event_name: 'Stop', session_id: 's1', stop_hook_active: false, last_assistant_message: '修正進行中，等探針通知' })).toBe(true);
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
