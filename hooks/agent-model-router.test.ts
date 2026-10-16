import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { spawnSync } from 'child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { HOOK_TIMEOUT_MS, JEV_MODEL, truncateMiddle } from '../scripts/lib/jev-client';
import {
  type AgentDirs,
  buildOutput,
  buildState,
  capByParent,
  decideRoute,
  FABLE_FALLBACK_MODEL,
  HEAD_BYTES,
  HEAD_MAX_BYTES,
  inheritsModel,
  MAX_BRIEF_CHARS,
  modelFamily,
  type ParentState,
  parseAgentInput,
  preSkipReason,
  readConsentFallback,
  readParentModel,
  readParentState,
  readTier,
  resolveAgentFile,
  ROUTE_CONF_MIN,
  ROUTE_TIMEOUT_MS,
  routeModel,
  TAIL_BYTES,
  TIER_MODEL,
} from './agent-model-router';

/** hook 腳本絕對路徑（整合測試 spawn 用） */
const HOOK = join(import.meta.dir, 'agent-model-router.ts');

/** fixture：遠高於門檻的 confidence */
const HIGH_CONF = 0.9;
/** fixture：門檻本身（剛好等於時應路由） */
const AT_MIN_CONF = 0.3;
/** fixture：剛好低於 AT_MIN_CONF */
const BELOW_MIN_CONF = 0.29;
/** fixture：接近滿分的 confidence */
const MAX_CONF = 0.99;
/** fixture：遠低於 ROUTE_CONF_MIN 的 confidence */
const LOW_CONF = 0.1;
/** fixture：tier 題各等級機率（small 最高、mid 次高） */
const PROBS = { light: 0.1, small: 0.6, mid: 0.25, top: 0.05 };
/** fixture：sk- 憑證本體長度（遮罩樣式要求 ≥ 20） */
const SECRET_BODY_LEN = 30;
/** fixture：跨截斷邊界時，憑證落在頭段內的字元數（sk- 之後只剩 7 字，不足遮罩樣式的 20 字） */
const SECRET_IN_HEAD = 10;
/** fixture：填充文字長度相對 MAX_BRIEF_CHARS 的倍數，確保一定觸發截斷 */
const FILLER_FACTOR = 2;
/** fixture：把 identity 推過 HEAD_MAX_BYTES 上限的額外位元組 */
const KIB_PROBE = 1024;
/** fixture：大型 transcript 填充行的文字長度 */
const FILLER_LINE_CHARS = 1000;
/** stub 延遲：介於共用 HOOK_TIMEOUT_MS 與本 hook ROUTE_TIMEOUT_MS 之間，用來證明 hook 真的帶 ROUTE_TIMEOUT_MS */
const STUB_SLOW_MS = 2500;
/** stub 延遲：超過 ROUTE_TIMEOUT_MS，hook 應逾時 */
const STUB_HANG_MS = ROUTE_TIMEOUT_MS + 1500;
/** 打 stub 的慢速測試逾時（bun test 預設 5 秒不夠） */
const SLOW_TEST_TIMEOUT_MS = 15000;
/** stub 要求的假 API key */
const FAKE_KEY = 'fake-key';
/** fixture：Fable 額度到頂時 Claude Code 換到的模型（2026-09-17 真實記錄的 fallbackModel） */
const FALLBACK_TO = 'claude-sonnet-5';
/** fixture：父模型 fable 且可用 */
const FABLE_PARENT: ParentState = { model: 'claude-fable-5-1', fableOff: false };
/** fixture：父模型 sonnet（user 自選，fable 可用） */
const SONNET_PARENT: ParentState = { model: 'claude-sonnet-5-5', fableOff: false };
/** fixture：父模型讀不到 */
const UNKNOWN_PARENT: ParentState = { model: null, fableOff: false };
/** fixture：Fable 額度到頂被強制換到 sonnet，fable 不可用 */
const FABLE_OFF_PARENT: ParentState = { model: FALLBACK_TO, fableOff: true };

/** 測試用暫存根目錄（假 HOME 與假 agent 定義） */
let root = '';
/** 不含專案層的查找位置 */
let dirs: AgentDirs;
/** 含專案層的查找位置 */
let projDirs: AgentDirs;

/**
 * 寫一個 agent 定義檔
 * @param file - 絕對路徑
 * @param front - frontmatter 內容（不含 ---）
 */
const writeAgent = (file: string, front: string): void => {
  // STEP 01: frontmatter 加本文
  writeFileSync(file, `---\n${front}\n---\n\n本文`);
};

/**
 * transcript 的 identity attachment 行
 * @param modelId - 模型 ID
 * @returns JSON 行
 */
const identityLine = (modelId: string): string => {
  // STEP 01: 與真實 transcript 同結構
  return JSON.stringify({ type: 'attachment', attachment: { type: 'model', identity: { modelId } } });
};

/**
 * transcript 的 assistant 記錄行
 * @param model - message.model
 * @returns JSON 行
 */
const assistantLine = (model: string): string => {
  // STEP 01: 與真實 transcript 同結構
  return JSON.stringify({ type: 'assistant', message: { model, content: [] } });
};

/**
 * transcript 的 model_consent_fallback 系統記錄行（Fable 額度到頂、user 不用 usage credits 時 Claude Code 寫入）
 * @param originalModel - 被換掉的模型 ID
 * @param fallbackModel - 換到的模型 ID
 * @returns JSON 行
 */
const fallbackLine = (originalModel: string, fallbackModel: string): string => {
  // STEP 01: 與 2026-09-17 真實記錄同結構（略去 uuid／timestamp 等 hook 不看的欄位）
  return JSON.stringify({
    type: 'system', subtype: 'model_consent_fallback', level: 'warning', choice: 'switch_default', originalModel, fallbackModel, persistedAsDefault: true,
  });
};

/**
 * transcript 的 user 記錄行（填充用）
 * @returns JSON 行
 */
const fillerLine = (): string => {
  // STEP 01: 固定長度文字
  return JSON.stringify({ type: 'user', message: { content: 'x'.repeat(FILLER_LINE_CHARS) } });
};

/**
 * 至少 bytes 位元組的填充行
 * @param bytes - 下限位元組數
 * @returns 填充行
 */
const fillerLines = (bytes: number): string[] => {
  // STEP 01: 行數向上取整再多一行
  return Array.from({ length: Math.ceil(bytes / FILLER_LINE_CHARS) + 1 }, fillerLine);
};

/**
 * 寫一個假 transcript
 * @param name - 檔名
 * @param lines - 各行
 * @param trailingNewline - 結尾是否有換行（沒有＝最後一行正在寫入）
 * @returns 絕對路徑
 */
const writeTranscript = (name: string, lines: string[], trailingNewline = true): string => {
  // STEP 01: 寫檔
  /** 假 transcript 路徑 */
  const file = join(root, name);
  writeFileSync(file, lines.join('\n') + (trailingNewline ? '\n' : ''));
  return file;
};

beforeAll(() => {
  // STEP 01: 使用者層 agent 目錄
  root = mkdtempSync(join(tmpdir(), 'agent-router-'));
  /** 使用者層 agent 目錄 */
  const userAgentsDir = join(root, 'agents');
  mkdirSync(userAgentsDir);
  writeAgent(join(userAgentsDir, 'inherit-agent.md'), 'name: inherit-agent\ndescription: x\nmodel: inherit');
  writeAgent(join(userAgentsDir, 'nomodel-agent.md'), 'name: nomodel-agent\ndescription: x');
  writeAgent(join(userAgentsDir, 'opus-agent.md'), 'name: opus-agent\ndescription: x\nmodel: opus');
  // STEP 02: 專案層：蓋過使用者層同名 agent、蓋過內建 Plan 與 general-purpose
  /** 專案層 agent 目錄（<cwd>/.claude/agents） */
  const projectAgentsDir = join(root, 'proj', '.claude', 'agents');
  mkdirSync(projectAgentsDir, { recursive: true });
  writeAgent(join(projectAgentsDir, 'inherit-agent.md'), 'name: inherit-agent\ndescription: x\nmodel: opus');
  writeAgent(join(projectAgentsDir, 'Plan.md'), 'name: Plan\ndescription: x\nmodel: sonnet');
  writeAgent(join(projectAgentsDir, 'general-purpose.md'), 'name: general-purpose\ndescription: x\nmodel: haiku');
  // STEP 03: plugin（一個正常、一個在兩個 installPath 都有同名檔、一個沒有 installPath）
  /** 正常 plugin 的 agents 目錄 */
  const pa = join(root, 'pa', 'agents');
  /** 同名 plugin 第一個安裝目錄 */
  const pb1 = join(root, 'pb1', 'agents');
  /** 同名 plugin 第二個安裝目錄 */
  const pb2 = join(root, 'pb2', 'agents');
  for (const d of [pa, pb1, pb2]) {
    mkdirSync(d, { recursive: true });
  }
  writeAgent(join(pa, 'helper.md'), 'name: helper\ndescription: x\nmodel: inherit');
  writeAgent(join(pa, 'fixed.md'), 'name: fixed\ndescription: x\nmodel: haiku');
  writeAgent(join(pb1, 'dup.md'), 'name: dup\nmodel: inherit');
  writeAgent(join(pb2, 'dup.md'), 'name: dup\nmodel: inherit');
  /** 假 installed_plugins.json */
  const pluginsFile = join(root, 'installed_plugins.json');
  writeFileSync(pluginsFile, JSON.stringify({
    plugins: {
      'pa@market': [{ installPath: join(root, 'pa') }, {}],
      'pb@m1': [{ installPath: join(root, 'pb1') }],
      'pb@m2': [{ installPath: join(root, 'pb2') }],
    },
  }));
  dirs = { projectAgentsDir: null, userAgentsDir, pluginsFile };
  projDirs = { ...dirs, projectAgentsDir };
});

afterAll(() => {
  // STEP 01: 清掉暫存目錄
  rmSync(root, { recursive: true, force: true });
});

describe('inheritsModel', () => {
  test('model 缺省或 inherit → 可路由', () => {
    expect(inheritsModel('---\nname: a\n---\nbody')).toBe(true);
    expect(inheritsModel('---\nname: a\nmodel: inherit\n---')).toBe(true);
    expect(inheritsModel('---\nname: a\nmodel: "inherit"\n---')).toBe(true);
  });
  test('固定 model → 不路由', () => {
    expect(inheritsModel('---\nname: a\nmodel: opus\n---')).toBe(false);
    expect(inheritsModel('---\r\nname: a\r\nmodel: sonnet\r\n---')).toBe(false);
  });
  test('沒有 frontmatter → 不路由', () => {
    expect(inheritsModel('# README\nmodel: inherit')).toBe(false);
  });
  test('description 含未加引號的冒號（YAML 嚴格解析會丟錯）仍能判讀', () => {
    expect(inheritsModel('---\nname: a\ndescription: Use when: x\\n<example>user: "hi"</example>\nmodel: inherit\n---')).toBe(true);
  });
  test('縮排在 description 區塊內的 model: 不算', () => {
    expect(inheritsModel('---\ndescription: |\n  model: opus\n---')).toBe(true);
  });
});

describe('resolveAgentFile', () => {
  test('使用者層 agent 找得到', () => {
    expect(resolveAgentFile('inherit-agent', dirs)).toBe(join(dirs.userAgentsDir, 'inherit-agent.md'));
  });
  test('專案層與使用者層同名 → 專案層優先', () => {
    expect(resolveAgentFile('inherit-agent', projDirs)).toBe(join(root, 'proj', '.claude', 'agents', 'inherit-agent.md'));
  });
  test('專案層沒有的名稱 → 退回使用者層', () => {
    expect(resolveAgentFile('opus-agent', projDirs)).toBe(join(dirs.userAgentsDir, 'opus-agent.md'));
  });
  test('plugin agent 依 installed_plugins.json 的 installPath 找（沒有 installPath 的紀錄略過）', () => {
    expect(resolveAgentFile('pa:helper', dirs)).toBe(join(root, 'pa', 'agents', 'helper.md'));
  });
  test('同名 plugin 對到多個不同檔 → 不明確，回 null', () => {
    expect(resolveAgentFile('pb:dup', dirs)).toBeNull();
  });
  test('不存在或名稱含路徑字元 → null', () => {
    expect(resolveAgentFile('missing', dirs)).toBeNull();
    expect(resolveAgentFile('../agents/inherit-agent', dirs)).toBeNull();
    expect(resolveAgentFile('pa:../pa/agents/helper', dirs)).toBeNull();
    expect(resolveAgentFile('nope:helper', dirs)).toBeNull();
  });
  test('installed_plugins.json 格式不符 → 丟錯（不默默當成沒有 plugin）', () => {
    // STEP 01: 寫一個 plugins 值不是陣列的清單
    /** 格式不符的安裝清單 */
    const bad = join(root, 'bad_plugins.json');
    writeFileSync(bad, JSON.stringify({ plugins: { 'pa@market': 'oops' } }));
    // STEP 02: 斷言丟錯；頂層 null 也丟錯
    expect(() => resolveAgentFile('pa:helper', { ...dirs, pluginsFile: bad })).toThrow();
    writeFileSync(bad, 'null');
    expect(() => resolveAgentFile('pa:helper', { ...dirs, pluginsFile: bad })).toThrow();
  });
});

describe('preSkipReason', () => {
  /** 會被路由的基本輸入 */
  const base = { description: 'd', prompt: '做點事' };
  test('內建可路由類型（含未指定）→ null', () => {
    for (const t of [undefined, '', 'general-purpose', 'claude', 'Explore', 'Plan']) {
      expect(preSkipReason({ ...base, subagent_type: t }, dirs)).toBeNull();
    }
  });
  test('已明寫 model → model_set', () => {
    expect(preSkipReason({ ...base, model: 'sonnet' }, dirs)).toBe('model_set');
  });
  test('prompt 空白 → no_prompt', () => {
    expect(preSkipReason({ description: 'd', prompt: '  ' }, dirs)).toBe('no_prompt');
  });
  test('fork → fork', () => {
    expect(preSkipReason({ ...base, subagent_type: 'fork' }, dirs)).toBe('fork');
  });
  test('自訂／plugin agent：inherit 或缺省可路由，固定 model 不路由，找不到定義不路由', () => {
    expect(preSkipReason({ ...base, subagent_type: 'inherit-agent' }, dirs)).toBeNull();
    expect(preSkipReason({ ...base, subagent_type: 'nomodel-agent' }, dirs)).toBeNull();
    expect(preSkipReason({ ...base, subagent_type: 'pa:helper' }, dirs)).toBeNull();
    expect(preSkipReason({ ...base, subagent_type: 'opus-agent' }, dirs)).toBe('fixed_model');
    expect(preSkipReason({ ...base, subagent_type: 'pa:fixed' }, dirs)).toBe('fixed_model');
    expect(preSkipReason({ ...base, subagent_type: 'unknown-agent' }, dirs)).toBe('no_def');
  });
  test('專案層定義蓋過使用者層：使用者層 inherit、專案層固定 opus → fixed_model', () => {
    expect(preSkipReason({ ...base, subagent_type: 'inherit-agent' }, projDirs)).toBe('fixed_model');
  });
  test('內建名稱被固定 model 的同名定義檔覆蓋 → fixed_model（未指定類型視為 general-purpose）', () => {
    expect(preSkipReason({ ...base, subagent_type: 'Plan' }, projDirs)).toBe('fixed_model');
    expect(preSkipReason({ ...base, subagent_type: 'general-purpose' }, projDirs)).toBe('fixed_model');
    expect(preSkipReason(base, projDirs)).toBe('fixed_model');
    expect(preSkipReason({ ...base, subagent_type: 'Explore' }, projDirs)).toBeNull();
  });
});

describe('parseAgentInput', () => {
  test('合法輸入原樣回傳（含其他欄位）', () => {
    // STEP 01: 帶 isolation 的合法輸入
    /** 測試用的 Agent 工具輸入 */
    const ti = { description: 'd', prompt: 'p', subagent_type: 'Explore', isolation: 'worktree' };
    expect(parseAgentInput(ti)).toEqual(ti);
  });
  test('不是物件、缺 prompt／description、型別不符 → null', () => {
    for (const bad of [null, 'x', [], { description: 'd' }, { prompt: 'p' }, { description: 'd', prompt: 1 }, { description: 'd', prompt: 'p', model: 1 }, { description: 'd', prompt: 'p', subagent_type: null }]) {
      expect(parseAgentInput(bad)).toBeNull();
    }
  });
});

describe('modelFamily', () => {
  test('完整 ID 與裸名', () => {
    expect(modelFamily('claude-sonnet-5-5')).toBe('sonnet');
    expect(modelFamily('claude-fable-5-1')).toBe('fable');
    expect(modelFamily('claude-opus-4-6[1m]')).toBe('opus');
    expect(modelFamily('haiku')).toBe('haiku');
  });
  test('不在等級表內 → null', () => {
    for (const m of ['claude-3-5-sonnet-20241022', 'gpt-4', 'constructor', '', '<synthetic>']) {
      expect(modelFamily(m)).toBeNull();
    }
  });
});

describe('readParentModel', () => {
  test('只有 identity（第一回合 assistant 記錄還沒落盤）→ identity 的 modelId', () => {
    // STEP 01: 只含 identity 的 transcript
    /** 假 transcript 路徑 */
    const f = writeTranscript('t-identity.jsonl', [fillerLine(), identityLine('claude-sonnet-5-5'), fillerLine()]);
    expect(readParentModel(f)).toBe('claude-sonnet-5-5');
  });
  test('有 assistant 記錄 → 最後一則真實 model，跳過 <synthetic>', () => {
    // STEP 01: identity 是 fable，之後換過模型，最後一則是 synthetic
    /** 假 transcript 路徑 */
    const f = writeTranscript('t-assistant.jsonl', [
      identityLine('claude-fable-5-1'), assistantLine('claude-fable-5-1'), assistantLine('claude-opus-4-6'), assistantLine('<synthetic>'),
    ]);
    expect(readParentModel(f)).toBe('claude-opus-4-6');
  });
  test('最後一行寫到一半（無結尾換行）→ 忽略該行', () => {
    // STEP 01: 最後一行是截斷的 assistant 記錄
    /** 寫到一半的最後一行 */
    const half = assistantLine('claude-haiku-4-5').slice(0, -5);
    /** 假 transcript 路徑 */
    const f = writeTranscript('t-partial.jsonl', [identityLine('claude-fable-5-1'), assistantLine('claude-sonnet-5-5'), half], false);
    expect(readParentModel(f)).toBe('claude-sonnet-5-5');
  });
  test('assistant 記錄被擠出尾端視窗 → 退回檔頭 identity', () => {
    // STEP 01: identity 在檔頭，尾端 TAIL_BYTES 內只有填充
    /** 假 transcript 路徑 */
    const f = writeTranscript('t-big.jsonl', [identityLine('claude-fable-5-1'), assistantLine('claude-haiku-4-5'), ...fillerLines(TAIL_BYTES)]);
    expect(readParentModel(f)).toBe('claude-fable-5-1');
  });
  test('identity 落在 HEAD_BYTES 之後、尾端視窗之前 → 倍增掃描仍找到', () => {
    // STEP 01: 填充把 identity 推出第一輪檔頭視窗，再用填充把它推出尾端視窗
    /** 假 transcript 路徑 */
    const f = writeTranscript('t-late.jsonl', [...fillerLines(HEAD_BYTES * 3), identityLine('claude-fable-5-1'), ...fillerLines(TAIL_BYTES)]);
    expect(readParentModel(f)).toBe('claude-fable-5-1');
  });
  test('identity 落在 HEAD_MAX_BYTES 之後且被擠出尾端 → null（fail-safe 上限）', () => {
    // STEP 01: 填充超過倍增掃描上限
    /** 假 transcript 路徑 */
    const f = writeTranscript('t-beyond.jsonl', [...fillerLines(HEAD_MAX_BYTES + KIB_PROBE), identityLine('claude-fable-5-1'), ...fillerLines(TAIL_BYTES)]);
    expect(readParentModel(f)).toBeNull();
  });
  test('尾端 identity 晚於最後一則 assistant（中途 /model 切換）→ 取較晚的 identity', () => {
    // STEP 01: assistant 是 opus，之後出現 sonnet 的 identity
    /** 假 transcript 路徑 */
    const f = writeTranscript('t-switch.jsonl', [identityLine('claude-opus-5-5'), assistantLine('claude-opus-5-5'), identityLine('claude-sonnet-5-5'), fillerLine()]);
    expect(readParentModel(f)).toBe('claude-sonnet-5-5');
  });
  test('沒帶路徑、檔案不存在、兩處都沒有 → null', () => {
    // STEP 01: 三種讀不到的情況
    expect(readParentModel(null)).toBeNull();
    expect(readParentModel(join(root, 'nope.jsonl'))).toBeNull();
    expect(readParentModel(writeTranscript('t-empty.jsonl', [fillerLine()]))).toBeNull();
  });
});

describe('readParentState / readConsentFallback', () => {
  /** 從 fable 被強制換到 sonnet 的 transcript（識別、對話、強制換模型、換後的 assistant 與 identity） */
  const switched = [
    identityLine('claude-fable-5-1'), assistantLine('claude-fable-5-1'), fallbackLine('claude-fable-5-1', FALLBACK_TO),
    assistantLine(FALLBACK_TO), identityLine(FALLBACK_TO), assistantLine(FALLBACK_TO),
  ];
  test('從 fable 被強制換到 sonnet 且仍在 sonnet → fableOff', () => {
    // STEP 01: 記錄讀得到、狀態為 fable 不可用
    /** 假 transcript 路徑 */
    const f = writeTranscript('s-off.jsonl', switched);
    expect(readConsentFallback(f)).toEqual({ originalModel: 'claude-fable-5-1', fallbackModel: FALLBACK_TO });
    expect(readParentState(f)).toEqual({ model: FALLBACK_TO, fableOff: true });
  });
  test('換走後 user 手動換到別的家族（opus）或換回 fable → 不是 fableOff', () => {
    // STEP 01: 換到 opus：父模型家族不等於換到的家族
    expect(readParentState(writeTranscript('s-opus.jsonl', [...switched, identityLine('claude-opus-5-5'), assistantLine('claude-opus-5-5')])))
      .toEqual({ model: 'claude-opus-5-5', fableOff: false });
    // STEP 02: 換回 fable：正在用 fable
    expect(readParentState(writeTranscript('s-back.jsonl', [...switched, identityLine('claude-fable-5-1')])))
      .toEqual({ model: 'claude-fable-5-1', fableOff: false });
  });
  test('沒有強制換模型記錄、或記錄不是從 fable 換走 → 不是 fableOff', () => {
    // STEP 01: user 自選 sonnet
    expect(readParentState(writeTranscript('s-plain.jsonl', [identityLine(FALLBACK_TO), assistantLine(FALLBACK_TO)])))
      .toEqual({ model: FALLBACK_TO, fableOff: false });
    // STEP 02: 從 opus 被換走與 fable 無關
    expect(readParentState(writeTranscript('s-opus-off.jsonl', [identityLine('claude-opus-5-5'), fallbackLine('claude-opus-5-5', FALLBACK_TO), assistantLine(FALLBACK_TO)])))
      .toEqual({ model: FALLBACK_TO, fableOff: false });
  });
  test('較晚的一行只是內容含粗篩字串（不是 system 記錄）→ 跳過、仍找到前面的真記錄', () => {
    // STEP 01: key 名稱剛好是 subtype 的 user 記錄（JSON.stringify 不跳脫 key 引號，粗篩會命中）
    /** 內容含粗篩字串的 user 記錄 */
    const mention = JSON.stringify({ type: 'user', note: { subtype: 'model_consent_fallback' } });
    /** 假 transcript 路徑 */
    const f = writeTranscript('s-mention.jsonl', [...switched, mention, assistantLine(FALLBACK_TO)]);
    expect(readParentState(f)).toEqual({ model: FALLBACK_TO, fableOff: true });
  });
  test('記錄被擠出尾端視窗（整檔掃描）→ 仍找到', () => {
    // STEP 01: 記錄在檔頭，尾端 TAIL_BYTES 內只有填充與換後的 assistant
    /** 假 transcript 路徑 */
    const f = writeTranscript('s-far.jsonl', [identityLine('claude-fable-5-1'), fallbackLine('claude-fable-5-1', FALLBACK_TO), ...fillerLines(TAIL_BYTES), assistantLine(FALLBACK_TO)]);
    expect(readParentState(f)).toEqual({ model: FALLBACK_TO, fableOff: true });
  });
  test('記錄是最後一行且寫到一半 → 當作沒有', () => {
    // STEP 01: 截斷的記錄仍含粗篩字串，但解析失敗
    /** 寫到一半的記錄行 */
    const half = fallbackLine('claude-fable-5-1', FALLBACK_TO).slice(0, -5);
    /** 假 transcript 路徑 */
    const f = writeTranscript('s-half.jsonl', [identityLine(FALLBACK_TO), half], false);
    expect(readConsentFallback(f)).toBeNull();
    expect(readParentState(f)).toEqual({ model: FALLBACK_TO, fableOff: false });
  });
  test('沒帶路徑、檔案不存在 → 讀不到且不是 fableOff', () => {
    expect(readParentState(null)).toEqual({ model: null, fableOff: false });
    expect(readParentState(join(root, 'nope.jsonl'))).toEqual({ model: null, fableOff: false });
  });
});

describe('capByParent / routeModel / TIER_MODEL', () => {
  test('對照表：top 不填；fable 不可用時 top 改填 opus', () => {
    expect(TIER_MODEL).toEqual({ light: 'haiku', small: 'sonnet', mid: 'opus', top: null });
    expect(FABLE_FALLBACK_MODEL).toBe('opus');
  });
  test('父模型 fable：達門檻依等級填 model', () => {
    expect(routeModel('light', HIGH_CONF, AT_MIN_CONF, FABLE_PARENT)).toEqual({ model: 'haiku', skip: null });
    expect(routeModel('small', HIGH_CONF, AT_MIN_CONF, FABLE_PARENT)).toEqual({ model: 'sonnet', skip: null });
    expect(routeModel('mid', HIGH_CONF, AT_MIN_CONF, { model: 'fable', fableOff: false })).toEqual({ model: 'opus', skip: null });
  });
  test('剛好等於門檻 → 路由；低於門檻 → low_conf', () => {
    expect(routeModel('small', AT_MIN_CONF, AT_MIN_CONF, FABLE_PARENT).model).toBe('sonnet');
    expect(routeModel('small', BELOW_MIN_CONF, AT_MIN_CONF, FABLE_PARENT)).toEqual({ model: null, skip: 'low_conf' });
  });
  test('top 即使高 confidence 也不填', () => {
    expect(routeModel('top', MAX_CONF, AT_MIN_CONF, FABLE_PARENT)).toEqual({ model: null, skip: 'top' });
  });
  test('只降不升：候選不比父模型便宜 → would_upgrade', () => {
    expect(routeModel('mid', HIGH_CONF, AT_MIN_CONF, SONNET_PARENT)).toEqual({ model: null, skip: 'would_upgrade' });
    expect(routeModel('small', HIGH_CONF, AT_MIN_CONF, SONNET_PARENT)).toEqual({ model: null, skip: 'would_upgrade' });
    expect(capByParent('haiku', { model: 'claude-haiku-4-5', fableOff: false })).toEqual({ model: null, skip: 'would_upgrade' });
  });
  test('候選比父模型便宜 → 填', () => {
    expect(routeModel('light', HIGH_CONF, AT_MIN_CONF, SONNET_PARENT)).toEqual({ model: 'haiku', skip: null });
    expect(capByParent('sonnet', { model: 'opus', fableOff: false })).toEqual({ model: 'sonnet', skip: null });
  });
  test('父模型讀不到或不在等級表 → parent_unknown', () => {
    expect(routeModel('light', HIGH_CONF, AT_MIN_CONF, UNKNOWN_PARENT)).toEqual({ model: null, skip: 'parent_unknown' });
    expect(capByParent('haiku', { model: 'claude-3-5-sonnet-20241022', fableOff: false })).toEqual({ model: null, skip: 'parent_unknown' });
  });
  test('fable 不可用（父模型被迫換到 sonnet）：上限放寬到 fable，top／mid 填 opus、small 填 sonnet、light 填 haiku，低 confidence 仍不填', () => {
    expect(routeModel('top', HIGH_CONF, AT_MIN_CONF, FABLE_OFF_PARENT)).toEqual({ model: 'opus', skip: null });
    expect(routeModel('mid', HIGH_CONF, AT_MIN_CONF, FABLE_OFF_PARENT)).toEqual({ model: 'opus', skip: null });
    expect(routeModel('small', HIGH_CONF, AT_MIN_CONF, FABLE_OFF_PARENT)).toEqual({ model: 'sonnet', skip: null });
    expect(routeModel('light', HIGH_CONF, AT_MIN_CONF, FABLE_OFF_PARENT)).toEqual({ model: 'haiku', skip: null });
    expect(routeModel('top', BELOW_MIN_CONF, AT_MIN_CONF, FABLE_OFF_PARENT)).toEqual({ model: null, skip: 'low_conf' });
  });
});

describe('readTier / decideRoute', () => {
  /**
   * 產生 tier 題答案
   * @param choice - 選中的標籤
   * @param confidence - confidence
   * @returns 單題原始答案
   */
  const ans = (choice: string, confidence: number) => {
    // STEP 01: 固定機率分佈
    return { type: 'choice' as const, choice, confidence, probabilities: PROBS };
  };
  test('readTier 帶出等級、confidence 與次高', () => {
    expect(readTier(ans('small', HIGH_CONF))).toEqual({ tier: 'small', conf: HIGH_CONF, second: 'mid', secondP: PROBS.mid });
  });
  test('decideRoute 套用 ROUTE_CONF_MIN 與父模型狀態', () => {
    expect(decideRoute(ans('small', ROUTE_CONF_MIN), FABLE_PARENT)).toEqual({
      tier: 'small', conf: ROUTE_CONF_MIN, second: 'mid', secondP: PROBS.mid, model: 'sonnet', skip: null,
    });
    expect(decideRoute(ans('small', HIGH_CONF), SONNET_PARENT).skip).toBe('would_upgrade');
    expect(decideRoute(ans('top', HIGH_CONF), FABLE_OFF_PARENT).model).toBe('opus');
  });
  test('標籤不在選項內 → 丟錯', () => {
    expect(() => readTier(ans('huge', HIGH_CONF))).toThrow();
  });
  test('缺答案 → 丟錯', () => {
    expect(() => decideRoute(undefined, FABLE_PARENT)).toThrow();
  });
});

describe('buildState', () => {
  test('憑證跨越截斷邊界：先遮罩再截斷，輸出含遮罩標記且無憑證片段', () => {
    // STEP 01: 頭段長度 = 截斷標記第一個字元（換行）的位置
    /** truncateMiddle 保留的頭段長度（截斷標記以換行開頭） */
    const head = truncateMiddle('y'.repeat(MAX_BRIEF_CHARS * FILLER_FACTOR), MAX_BRIEF_CHARS).indexOf('\n');
    // STEP 02: 憑證起點放在頭段尾端前 SECRET_IN_HEAD 字，後面接長填充
    /** 測試用 sk- 憑證 */
    const secret = 'sk-' + 'a'.repeat(SECRET_BODY_LEN);
    /** 憑證跨越頭段尾端的 brief */
    const prompt = 'y'.repeat(head - SECRET_IN_HEAD) + secret + 'x'.repeat(MAX_BRIEF_CHARS * FILLER_FACTOR);
    /** buildState 結果 */
    const s = buildState({ subagent_type: 'Explore', description: 'd', prompt });
    // STEP 03: 先截斷再遮罩時頭段會留下 sk-aaaaaaa（不足 20 字遮罩不到），這裡必須沒有
    expect(s.prompt.length).toBeLessThanOrEqual(MAX_BRIEF_CHARS);
    expect(s.prompt).toContain('[MASKED]');
    expect(s.prompt).not.toContain('sk-');
    expect(s.subagent_type).toBe('Explore');
  });
  test('prompt 缺漏或空白 → 丟錯（不補空字串）', () => {
    expect(() => buildState({ description: 'd', prompt: '   ' })).toThrow('prompt');
    expect(() => buildState({ description: 'd' } as never)).toThrow('prompt');
  });
});

describe('buildOutput', () => {
  test('保留原輸入全部欄位並填 model', () => {
    // STEP 01: 帶 isolation 的輸入
    /** 測試用的 Agent 工具輸入 */
    const ti = { description: 'd', prompt: 'p', subagent_type: 'Explore', isolation: 'worktree' };
    expect(buildOutput(ti, 'sonnet')).toEqual({
      hookSpecificOutput: { hookEventName: 'PreToolUse', updatedInput: { ...ti, model: 'sonnet' } },
    });
  });
  test('不修改傳入物件', () => {
    // STEP 01: 呼叫後原物件不變
    /** 測試用的 Agent 工具輸入 */
    const ti = { description: 'd', prompt: 'p' };
    buildOutput(ti, 'haiku');
    expect(ti).toEqual({ description: 'd', prompt: 'p' });
  });
});

/**
 * 讀假 HOME 下 decisions.jsonl 中的 D-route 紀錄
 * @param session - 指定時只回該 session 的紀錄
 * @returns 紀錄物件
 */
const logsOf = (session?: string): Record<string, unknown>[] => {
  // STEP 01: 讀檔（還沒寫過就是空）
  /** 假 HOME 下的決策 log */
  const file = join(root, '.claude', 'state', 'jev', 'decisions.jsonl');
  /** log 的非空白行 */
  const lines = existsSync(file) ? readFileSync(file, 'utf-8').split('\n').filter(isNonBlank) : [];
  // STEP 02: 只留 D-route，指定 session 時再篩
  /** 所有 D-route 紀錄 */
  const all = lines.map(parseLog).filter(isRouteLog);
  /**
   * 是否為指定 session 的紀錄（filter 回呼）
   * @param e - 紀錄
   * @returns true 表示 session 相符
   */
  const ofSession = (e: Record<string, unknown>): boolean => e.session === session;
  return session === undefined ? all : all.filter(ofSession);
};

/**
 * 是否為非空白行（filter 回呼）
 * @param l - 一行文字
 * @returns true 表示有內容
 */
function isNonBlank(l: string): boolean {
  // STEP 01: 去空白後非空
  return l.trim() !== '';
}

/**
 * 解析一行決策 log（map 回呼）
 * @param l - 一行 JSON
 * @returns 紀錄物件
 */
function parseLog(l: string): Record<string, unknown> {
  // STEP 01: JSON 解析
  return JSON.parse(l) as Record<string, unknown>;
}

/**
 * 是否為 D-route 的紀錄（filter 回呼）
 * @param e - 紀錄
 * @returns true 表示 hook=D-route
 */
function isRouteLog(e: Record<string, unknown>): boolean {
  // STEP 01: 比對 hook 名稱
  return e.hook === 'D-route';
}

/**
 * 紀錄的 error 欄位（map 回呼）
 * @param e - 紀錄
 * @returns 錯誤訊息；沒有 error 欄位回 null
 */
function errorOf(e: Record<string, unknown>): string | null {
  // STEP 01: 只接受字串
  return typeof e.error === 'string' ? e.error : null;
}

/**
 * 是否為字串（filter 回呼）
 * @param v - 任意值
 * @returns true 表示是字串
 */
function isString(v: unknown): v is string {
  // STEP 01: 型別判斷
  return typeof v === 'string';
}

/**
 * 紀錄的 skip 欄位（map 回呼）
 * @param e - 紀錄
 * @returns skip 值
 */
function skipOf(e: Record<string, unknown>): unknown {
  // STEP 01: 取欄位
  return e.skip;
}

/**
 * D-route 錯誤紀錄（askJev 寫的錯誤不帶 session）
 * @returns 錯誤訊息
 */
const errorLogs = (): string[] => {
  // STEP 01: 只取有 error 欄位的
  return logsOf().map(errorOf).filter(isString);
};

describe('子行程整合（spawn 真 hook，假 HOME、不帶 API key）', () => {
  /**
   * 以 stdin 餵 PreToolUse 事件執行 hook
   * @param input - stdin 內容（物件會轉 JSON）
   * @param extraEnv - 額外環境變數
   * @returns exit code 與輸出
   */
  const run = (input: unknown, extraEnv: Record<string, string> = {}) => {
    // STEP 01: 只傳 PATH 與假 HOME，不帶 TYPESAFE_API_KEY，避免打到真 Jev、寫到真 log
    /** stdin 內容 */
    const body = typeof input === 'string' ? input : JSON.stringify(input);
    /** hook 子行程結果 */
    const r = spawnSync('bun', [HOOK], { input: body, encoding: 'utf8', env: { PATH: process.env.PATH ?? '', HOME: root, ...extraEnv } });
    // STEP 02: 回傳 exit code 與輸出
    return { code: r.status, stdout: r.stdout, stderr: r.stderr };
  };
  /** 一般會被路由的 Agent 事件 */
  const agentEvent = { session_id: 's1', tool_name: 'Agent', tool_input: { description: 'd', prompt: 'x' } };

  // 這兩種不寫任何 log：比對執行前後 D-route 紀錄總數（askJev 失敗的錯誤紀錄不帶 session，不能只看 session）
  test('JEV_HOOKS_DISABLED=1 → 無輸出、exit 0、不寫 log', () => {
    // STEP 01: 執行前後紀錄數不變
    /** 執行前的 D-route 紀錄數 */
    const before = logsOf().length;
    /** hook 執行結果 */
    const r = run({ ...agentEvent, session_id: 'disabled' }, { JEV_HOOKS_DISABLED: '1' });
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(logsOf().length).toBe(before);
  });
  test('tool_name 不是 Agent → 無輸出、exit 0、不寫 log', () => {
    // STEP 01: 執行前後紀錄數不變
    /** 執行前的 D-route 紀錄數 */
    const before = logsOf().length;
    /** hook 執行結果 */
    const r = run({ ...agentEvent, session_id: 'bash', tool_name: 'Bash', tool_input: { command: 'ls' } });
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(logsOf().length).toBe(before);
  });
  test('tool_input.model 已有值 → 無輸出、exit 0、log 只記 skip=model_set', () => {
    // STEP 01: 執行並比對 log
    /** hook 執行結果 */
    const r = run({ ...agentEvent, session_id: 'modelset', tool_input: { ...agentEvent.tool_input, model: 'opus' } });
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(logsOf('modelset')).toEqual([expect.objectContaining({ skip: 'model_set' })]);
    expect(logsOf('modelset')[0]).not.toHaveProperty('model_out');
  });
  test('tool_input 缺 prompt → 無輸出、exit 0、log skip=invalid_input', () => {
    // STEP 01: 執行並比對 log
    /** hook 執行結果 */
    const r = run({ ...agentEvent, session_id: 'invalid', tool_input: { description: 'd' } });
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(logsOf('invalid').map(skipOf)).toEqual(['invalid_input']);
  });
  test('stdin 不是 JSON → 未預期錯誤：無輸出、stderr 有訊息、exit 1（不阻擋工具，wrapper 記 ERRORS.jsonl）', () => {
    // STEP 01: 執行並檢查三個出口
    /** 執行前的錯誤紀錄數 */
    const before = errorLogs().length;
    /** hook 執行結果 */
    const r = run('not json');
    expect(r.code).toBe(1);
    expect(r.stdout).toBe('');
    expect(r.stderr).toContain('未預期錯誤');
    expect(errorLogs().length).toBe(before + 1);
  });
});

describe('子行程整合（本機 Jev stub，驗證 transport 與決策）', () => {
  /** 本機 stub server */
  let server: ReturnType<typeof Bun.serve>;
  /** stub 收到的合法請求數（驗證 hook 真的有呼叫 Jev） */
  let hits = 0;
  /** 父模型為 fable 的假 transcript */
  let fableTranscript = '';
  /** 父模型為 sonnet 的假 transcript */
  let sonnetTranscript = '';
  /** Fable 額度到頂被強制換到 sonnet 的假 transcript（fable 不可用） */
  let fableOffTranscript = '';

  /**
   * 延遲
   * @param ms - 毫秒
   * @returns 到時 resolve
   */
  const sleep = (ms: number): Promise<void> => {
    // STEP 01: 包 setTimeout
    return new Promise((resolve) => setTimeout(resolve, ms));
  };

  /**
   * tier 題成功回應
   * @param choice - 選中的等級
   * @param confidence - confidence
   * @returns HTTP 回應
   */
  const tierResponse = (choice: string, confidence: number): Response => {
    // STEP 01: 與 systemOne 回應同結構
    return Response.json({ answers: { tier: { type: 'choice', choice, confidence, probabilities: PROBS } } });
  };

  /**
   * stub 的請求處理：驗證 hook 送出的 transport，再依 state.description 選情境
   * @param req - HTTP 請求
   * @returns HTTP 回應
   */
  const handle = async (req: Request): Promise<Response> => {
    // STEP 01: 驗 Authorization、模型版本與題目；不符回 400，hook 會當成失敗
    /** hook 送出的請求 body */
    const body = (await req.json()) as { model?: string; state?: { description?: string }; questions?: Record<string, unknown> };
    if (req.headers.get('authorization') !== `Bearer ${FAKE_KEY}` || body.model !== JEV_MODEL || !body.questions?.tier) {
      return new Response('bad request', { status: 400 });
    }
    hits += 1;
    // STEP 02: 依情境回應
    switch (body.state?.description) {
      case 'ok-small':
        return tierResponse('small', HIGH_CONF);
      case 'ok-mid':
        return tierResponse('mid', HIGH_CONF);
      case 'low':
        return tierResponse('small', LOW_CONF);
      case 'top':
        return tierResponse('top', HIGH_CONF);
      case 'http500':
        return new Response('boom', { status: 500 });
      case 'noanswers':
        return Response.json({});
      case 'slow':
        await sleep(STUB_SLOW_MS);
        return tierResponse('small', HIGH_CONF);
      case 'hang':
        await sleep(STUB_HANG_MS);
        return tierResponse('small', HIGH_CONF);
      default:
        return new Response('unknown case', { status: 400 });
    }
  };

  /**
   * 以 Bun.spawn 非同步執行 hook（spawnSync 會卡住同一 event loop 上的 stub）
   * @param session - session ID
   * @param scenario - 情境（放在 description 傳給 stub）
   * @param transcript - 假 transcript 路徑
   * @returns exit code、stdout、stderr
   */
  const runHook = async (session: string, scenario: string, transcript: string) => {
    // STEP 01: 組事件（含 hook 不使用、須原樣保留的欄位）
    /** Agent 工具輸入（isolation 為 hook 不使用、須原樣保留的欄位） */
    const toolInput = { description: scenario, prompt: '把 foo 改名為 bar', subagent_type: 'Explore', isolation: 'worktree' };
    /** PreToolUse stdin 事件 */
    const event = { session_id: session, tool_name: 'Agent', tool_input: toolInput, transcript_path: transcript, cwd: root };
    // STEP 02: 帶 stub 位址、假 key、假 HOME 執行
    /** hook 子行程 */
    const proc = Bun.spawn(['bun', HOOK], {
      stdin: new TextEncoder().encode(JSON.stringify(event)),
      stdout: 'pipe',
      stderr: 'pipe',
      env: { PATH: process.env.PATH ?? '', HOME: root, TYPESAFE_API_KEY: FAKE_KEY, JEV_API_URL: server.url.href },
    });
    /** hook 的 exit code */
    const code = await proc.exited;
    // STEP 03: 讀輸出
    return { code, stdout: await new Response(proc.stdout).text(), stderr: await new Response(proc.stderr).text(), toolInput };
  };

  beforeAll(() => {
    // STEP 01: 起 stub、寫假 transcript
    server = Bun.serve({ port: 0, fetch: handle });
    fableTranscript = writeTranscript('t-fable.jsonl', [identityLine('claude-fable-5-1')]);
    sonnetTranscript = writeTranscript('t-sonnet.jsonl', [identityLine('claude-sonnet-5-5')]);
    fableOffTranscript = writeTranscript('t-fable-off.jsonl', [identityLine('claude-fable-5-1'), fallbackLine('claude-fable-5-1', FALLBACK_TO), assistantLine(FALLBACK_TO)]);
  });

  afterAll(() => {
    // STEP 01: 關 stub（含進行中的連線）
    server.stop(true);
  });

  test('有效答案 → stdout 為完整 updatedInput（原欄位全保留＋model），decisions.jsonl 有 D-route 行', async () => {
    // STEP 01: 執行
    /** 執行前 stub 收到的請求數 */
    const before = hits;
    /** hook 執行結果 */
    const r = await runHook('stub-ok', 'ok-small', fableTranscript);
    // STEP 02: transport 真的有打到 stub，輸出為完整 JSON
    expect(hits).toBe(before + 1);
    expect(r.code).toBe(0);
    expect(JSON.parse(r.stdout)).toEqual({ hookSpecificOutput: { hookEventName: 'PreToolUse', updatedInput: { ...r.toolInput, model: 'sonnet' } } });
    // STEP 03: 決策 log
    /** 本 session 唯一一筆決策紀錄 */
    const [log] = logsOf('stub-ok');
    expect(log).toMatchObject({ tier: 'small', model_out: 'sonnet', skip: null, parent_model: 'claude-fable-5-1', fable_off: false, subagent_type: 'Explore' });
  });

  test('低 confidence → stdout 空、skip=low_conf', async () => {
    // STEP 01: 執行並比對
    /** hook 執行結果 */
    const r = await runHook('stub-low', 'low', fableTranscript);
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(logsOf('stub-low').map(skipOf)).toEqual(['low_conf']);
  });

  test('top → stdout 空、skip=top', async () => {
    // STEP 01: 執行並比對
    /** hook 執行結果 */
    const r = await runHook('stub-top', 'top', fableTranscript);
    expect(r.stdout).toBe('');
    expect(logsOf('stub-top').map(skipOf)).toEqual(['top']);
  });

  test('父模型 sonnet、候選 opus → stdout 空、skip=would_upgrade', async () => {
    // STEP 01: 執行並比對
    /** hook 執行結果 */
    const r = await runHook('stub-up', 'ok-mid', sonnetTranscript);
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(logsOf('stub-up')).toEqual([expect.objectContaining({ skip: 'would_upgrade', parent_model: 'claude-sonnet-5-5', fable_off: false, tier: 'mid' })]);
  });

  test('fable 不可用（父模型被迫換到 sonnet）、top → stdout 填 opus、log fable_off=true', async () => {
    // STEP 01: 執行並比對輸出與 log
    /** hook 執行結果 */
    const r = await runHook('stub-off-top', 'top', fableOffTranscript);
    expect(r.code).toBe(0);
    expect(JSON.parse(r.stdout).hookSpecificOutput.updatedInput).toEqual({ ...r.toolInput, model: 'opus' });
    expect(logsOf('stub-off-top')).toEqual([expect.objectContaining({ tier: 'top', model_out: 'opus', skip: null, parent_model: FALLBACK_TO, fable_off: true })]);
  });

  test('fable 不可用、mid → 填 opus（對照 stub-up：同是父模型 sonnet，沒有強制換模型記錄時是 would_upgrade）', async () => {
    // STEP 01: 執行並比對
    /** hook 執行結果 */
    const r = await runHook('stub-off-mid', 'ok-mid', fableOffTranscript);
    expect(r.code).toBe(0);
    expect(JSON.parse(r.stdout).hookSpecificOutput.updatedInput.model).toBe('opus');
    expect(logsOf('stub-off-mid').map(skipOf)).toEqual([null]);
  });

  test('HTTP 500 → fail-open：stdout 空、exit 0、log 有 error', async () => {
    // STEP 01: 執行並比對錯誤紀錄數
    /** 執行前的錯誤紀錄數 */
    const before = errorLogs().length;
    /** hook 執行結果 */
    const r = await runHook('stub-500', 'http500', fableTranscript);
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(errorLogs().slice(before)).toEqual([expect.stringContaining('HTTP 500')]);
  });

  test('回應缺 answers → fail-open：stdout 空、exit 0、log 有 error', async () => {
    // STEP 01: 執行並比對錯誤紀錄數
    /** 執行前的錯誤紀錄數 */
    const before = errorLogs().length;
    /** hook 執行結果 */
    const r = await runHook('stub-noans', 'noanswers', fableTranscript);
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(errorLogs().slice(before)).toEqual([expect.stringContaining('缺 answers')]);
  });

  test(`stub 延遲 ${STUB_SLOW_MS}ms（> 共用 HOOK_TIMEOUT_MS）仍成功 → hook 帶的是 ROUTE_TIMEOUT_MS`, async () => {
    // STEP 01: 前提：延遲介於兩個逾時之間
    expect(STUB_SLOW_MS).toBeGreaterThan(HOOK_TIMEOUT_MS);
    expect(STUB_SLOW_MS).toBeLessThan(ROUTE_TIMEOUT_MS);
    // STEP 02: 執行並比對
    /** hook 執行結果 */
    const r = await runHook('stub-slow', 'slow', fableTranscript);
    expect(r.code).toBe(0);
    expect(JSON.parse(r.stdout).hookSpecificOutput.updatedInput.model).toBe('sonnet');
  }, SLOW_TEST_TIMEOUT_MS);

  test(`stub 延遲 ${STUB_HANG_MS}ms（> ROUTE_TIMEOUT_MS）→ 逾時 fail-open：stdout 空、exit 0、log 有 error`, async () => {
    // STEP 01: 執行並比對錯誤紀錄數
    /** 執行前的錯誤紀錄數 */
    const before = errorLogs().length;
    /** hook 執行結果 */
    const r = await runHook('stub-hang', 'hang', fableTranscript);
    expect(r.code).toBe(0);
    expect(r.stdout).toBe('');
    expect(errorLogs().length).toBe(before + 1);
  }, SLOW_TEST_TIMEOUT_MS);
});
