import { describe, expect, test } from 'bun:test';
import {
  type Cluster,
  describeFailure,
  MAX_CLUSTERS,
  MAX_ERROR_CHARS,
  pickMatch,
  recordFailure,
  shouldInject,
  statePath,
} from './repeat-failure-detector';
import { truncateMiddle } from '../scripts/lib/jev-client';

/** 測試用的失敗樣本 */
const fail = (command: string, error = 'Exit code 1'): Cluster['last'] => ({ command, error });

describe('truncateMiddle', () => {
  test('未超長原樣回傳', () => {
    expect(truncateMiddle('abc', 10)).toBe('abc');
  });
  test('超長時保留頭尾，總長不超過上限', () => {
    const s = 'H'.repeat(600) + 'M'.repeat(1000) + 'T'.repeat(600);
    const out = truncateMiddle(s, MAX_ERROR_CHARS);
    expect(out.length).toBeLessThanOrEqual(MAX_ERROR_CHARS);
    expect(out.startsWith('HHH')).toBe(true);
    expect(out.endsWith('TTT')).toBe(true);
    expect(out).toContain('截斷');
  });
});

describe('describeFailure', () => {
  test('Bash 用 command 字串（與 C 評估集同格式）', () => {
    const f = describeFailure({ tool_name: 'Bash', tool_input: { command: 'bun test', description: 'x' }, error: 'Exit code 1\nboom' });
    expect(f).toEqual({ command: 'bun test', error: 'Exit code 1\nboom' });
  });
  test('其他工具用工具名＋輸入 JSON', () => {
    const f = describeFailure({ tool_name: 'Read', tool_input: { file_path: '/a.ts' }, error: 'File does not exist.' });
    expect(f.command).toBe('Read {"file_path":"/a.ts"}');
  });
  test('過長的 error 被截斷', () => {
    const f = describeFailure({ tool_name: 'Bash', tool_input: { command: 'x' }, error: 'e'.repeat(5000) });
    expect(f.error.length).toBeLessThanOrEqual(MAX_ERROR_CHARS);
  });
});

describe('pickMatch', () => {
  test('取「是」且 conf ≥ 0.3 中 conf 最高者', () => {
    expect(pickMatch([{ pred: true, conf: 0.4 }, { pred: true, conf: 0.9 }, { pred: false, conf: 1 }])).toEqual({ idx: 1, conf: 0.9 });
  });
  test('conf 相同時取較新的一組（index 小）', () => {
    expect(pickMatch([{ pred: true, conf: 0.8 }, { pred: true, conf: 0.8 }])).toEqual({ idx: 0, conf: 0.8 });
  });
  test('conf 低於行動下限不算同一失敗', () => {
    expect(pickMatch([{ pred: true, conf: 0.29 }])).toBeNull();
  });
  test('Jev 呼叫失敗（null）不算同一失敗', () => {
    expect(pickMatch([null, { pred: false, conf: 0.9 }])).toBeNull();
  });
});

describe('recordFailure', () => {
  test('沒有匹配 → 新組放最前面，次數 1', () => {
    const r = recordFailure([], fail('a'), -1);
    expect(r.count).toBe(1);
    expect(r.clusters).toEqual([{ last: fail('a'), count: 1 }]);
  });
  test('匹配 → 次數 +1、代表改成最新這次、移到最前面', () => {
    const before: Cluster[] = [{ last: fail('b'), count: 1 }, { last: fail('a', 'old'), count: 2 }];
    const r = recordFailure(before, fail('a', 'new'), 1);
    expect(r.count).toBe(3);
    expect(r.clusters).toEqual([{ last: fail('a', 'new'), count: 3 }, { last: fail('b'), count: 1 }]);
  });
  test('超過保留組數時丟掉最舊的', () => {
    const before: Cluster[] = Array.from({ length: MAX_CLUSTERS }, (_, i) => ({ last: fail(`c${i}`), count: 1 }));
    const r = recordFailure(before, fail('new'), -1);
    expect(r.clusters.length).toBe(MAX_CLUSTERS);
    expect(r.clusters[0].last.command).toBe('new');
    expect(r.clusters.map((c) => c.last.command)).not.toContain(`c${MAX_CLUSTERS - 1}`);
  });
  test('不修改傳入的陣列', () => {
    const before: Cluster[] = [{ last: fail('a'), count: 1 }];
    const snapshot = structuredClone(before);
    recordFailure(before, fail('a'), 0);
    expect(before).toEqual(snapshot);
  });
});

describe('shouldInject', () => {
  test('第 3、6 次注入，其他不注入', () => {
    expect([1, 2, 3, 4, 5, 6, 7].map(shouldInject)).toEqual([false, false, true, false, false, true, false]);
  });
});

describe('statePath', () => {
  test('合法 session id 回傳路徑', () => {
    expect(statePath('86b35ad2-52f5-4580-8e3d-5385701a6b17')).toEndWith('/86b35ad2-52f5-4580-8e3d-5385701a6b17.json');
  });
  test('含路徑字元的 session id 丟錯', () => {
    expect(() => statePath('../../etc/passwd')).toThrow();
  });
});
