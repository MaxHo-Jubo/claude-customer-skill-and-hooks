import { expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'

/** 測試用 HOME */
const HOME = '/home/u'
/** 本 session id */
const ME = 'session-me'
/** 測試時鐘的現在時間（epoch ms） */
const NOW = 1_000_000_000_000
/** 一分鐘（毫秒） */
const MINUTE_MS = 60_000

/** 一顆有效 marker 的腳本輸出（12 分鐘前建立、本 session） */
const MARKER = { file: 'x.json', repo: 'repo-a', repoRoot: '/w/repo-a', commit: 'abcdef1', tier: 3, engine: 'codex', expectedAspects: 6, createdAt: NOW - 12 * MINUTE_MS, sessionId: ME, missing: [] as string[] }

/** 列舉腳本的模擬結果 */
type Script = { exitCode: number; stdout?: string; stderr?: string }

/** 測試世界的可變狀態（測試中途可改，模擬 marker 被建立或清掉） */
type World = {
  /** marker 目錄裡的檔名；undefined 表示目錄不存在 */
  files?: string[]
  /** 列舉腳本的結果 */
  script: Script
  /** fs.list 是否失敗（模擬 EACCES；引擎以 deny 回應，$.fs.list 會 reject） */
  listThrows?: boolean
  /** $.env.get('HOME') 的回傳值 */
  home?: string
  /** 下層 Bash 執行時要套用的變更（模擬「指令執行後才寫入 marker」） */
  onBash?: () => void
}

/**
 * 輸出一份列舉結果的 JSON。
 * @param markers - marker 清單
 * @param invalid - 無法解析的檔名
 * @returns 腳本 stdout
 */
const listing = (markers: object[], invalid: string[] = []) => JSON.stringify({ markers, invalid })

/**
 * 建立引擎底下的世界：模擬 env／fs／process／session／clock／tool／ui，並記錄 spawn 次數。
 * @param on - 測試框架提供的 hook 註冊函式，掛在受測 plugin 之下充當引擎
 * @param w - 世界狀態（測試可在中途修改）
 * @returns spawn 紀錄
 */
const world = (on: On, w: World) => {
  // STEP 01: 紀錄容器
  /** 執行過的子行程 argv */
  const runs: (readonly string[])[] = []
  // STEP 02: 模擬 env、session、clock、fs
  on('env.get', () => ({ value: w.home ?? HOME }))
  on('session.id', () => ({ value: ME }))
  on('session.start', (_$, e: { cwd: string }) => ({ cwd: e.cwd }))
  on('turn.complete', () => ({ text: '' }))
  on('clock.now', () => ({ value: NOW }))
  on('fs.exists', () => ({ value: w.files !== undefined }))
  on('fs.list', () => {
    if (w.listThrows) {
      return { deny: 'EACCES: permission denied' }
    }
    return { value: (w.files ?? []).map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false })) }
  })
  // STEP 03: 模擬列舉腳本與工具（Bash 執行時才套用 onBash，用來驗證刷新發生在工具之後）
  on('process.run', (_$, e: { argv: readonly string[] }) => {
    runs.push(e.argv)
    return { value: { exitCode: w.script.exitCode, stdout: w.script.stdout ?? '', stderr: w.script.stderr ?? '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('tool.call', () => {
    w.onBash?.()
    return { result: { stdout: '', stderr: '', interrupted: false } }
  })
  // STEP 04: 模擬引擎自己的 band：plugin 不畫時由它接手，畫一個空 Box
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  return { runs }
}

/** band 可用的列數（測試用的一般終端機尺寸） */
const BAND_ROWS = 10
/** band 可用的欄數（測試用的一般終端機尺寸） */
const BAND_COLUMNS = 120

/** AbovePrompt 的掛載參數 */
const BAND = {
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: BAND_ROWS, bodyColumns: BAND_COLUMNS, scroll: { offset: 0, bodyRows: BAND_ROWS }, view: {} },
} as const

test('有效 marker：Bash 結束後刷新，band 顯示 repo／Tier／commit／引擎／面向數／經過分鐘，並標記本 session', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { files: ['x.json', 'x.lasthead'], script: { exitCode: 0, stdout: listing([MARKER]) } })
  await $.tool.call({ tool: 'Bash', command: 'git status' })
  expect(w.runs).toEqual([['bun', `${HOME}/.claude/scripts/list-pending-review.ts`]])
  for (const surface of ['terminal', 'desktop'] as const) {
    /** 掛載的 band */
    const ui = await $.ui.mount({ plugin: 'review-band', surface, ...BAND })
    /** marker 那一列 */
    const row = await ui.find({ type: 'Text', text: /pending-review/ })
    expect(row?.text).toContain('repo-a Tier 3（abcdef1）· codex · 應跑 6 個面向 · 12 分鐘前 · 本 session')
    await ui.unmount()
  }
})

test('marker 被清掉：同一個 session 內 band 由有變無（不殘留舊狀態）', async ($, on) => {
  /** 世界狀態 */
  const state: World = { files: ['x.json'], script: { exitCode: 0, stdout: listing([MARKER]) } }
  world(on, state)
  await $.tool.call({ tool: 'Bash', command: 'git commit -m x' })
  state.files = ['x.lasthead']
  await $.tool.call({ tool: 'Bash', command: 'bun clear-pending-review.ts' })
  /** 掛載的 band */
  const ui = await $.ui.mount({ plugin: 'review-band', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /pending-review/ })).toBeUndefined()
  await ui.unmount()
})

test('刷新發生在 Bash 執行之後：讀到的是指令寫入後的 marker', async ($, on) => {
  /** 世界狀態：一開始沒有 marker，Bash 執行時才建立 */
  const state: World = { files: undefined, script: { exitCode: 0, stdout: listing([MARKER]) } }
  state.onBash = () => {
    state.files = ['x.json']
  }
  world(on, state)
  await $.tool.call({ tool: 'Bash', command: 'git commit -m x' })
  /** 掛載的 band */
  const ui = await $.ui.mount({ plugin: 'review-band', surface: 'terminal', ...BAND })
  expect((await ui.find({ type: 'Text', text: /pending-review/ }))?.text).toContain('repo-a')
  await ui.unmount()
})

test('session.start 與 turn.complete 都會刷新', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { files: ['x.json'], script: { exitCode: 0, stdout: listing([MARKER]) } })
  await $.session.start({ cwd: '/w', surface: 'terminal', isInteractive: true })
  expect(w.runs.length).toBe(1)
  await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  expect(w.runs.length).toBe(2)
})

test('marker 目錄沒有 .json：不 spawn，band 不佔位', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { files: ['x.lasthead', 'unlock-audit.log'], script: { exitCode: 0, stdout: listing([]) } })
  await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(w.runs).toEqual([])
  /** 掛載的 band */
  const ui = await $.ui.mount({ plugin: 'review-band', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /pending-review/ })).toBeUndefined()
  await ui.unmount()
})

test('Bash 以外的工具不刷新', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { files: ['x.json'], script: { exitCode: 0, stdout: listing([MARKER]) } })
  await $.tool.call({ tool: 'Read', file_path: '/x' })
  expect(w.runs).toEqual([])
})

test('讀取失敗的各種來源（腳本 exit≠0、fs.list 拋錯、HOME 未設定、輸出形狀不符）都顯示原因', async ($, on) => {
  /** 世界狀態 */
  const state: World = { files: ['x.json'], script: { exitCode: 1, stderr: 'list-pending-review: EACCES' } }
  world(on, state)
  /** 依序套用的失敗情境與預期顯示 */
  const cases: [() => void, string][] = [
    [() => undefined, 'exit 1：list-pending-review: EACCES'],
    [() => { state.listThrows = true }, 'EACCES: permission denied'],
    [() => { state.listThrows = false; state.home = '' }, 'HOME 未設定'],
    [() => { state.home = HOME; state.script = { exitCode: 0, stdout: '{"items":[]}' } }, '缺 markers／invalid 陣列'],
  ]
  for (const [apply, expected] of cases) {
    apply()
    await $.tool.call({ tool: 'Bash', command: 'git status' })
    /** 掛載的 band */
    const ui = await $.ui.mount({ plugin: 'review-band', surface: 'terminal', ...BAND })
    expect({ expected, text: (await ui.find({ type: 'Text', text: /讀取失敗/ }))?.text ?? '' }).toEqual({ expected, text: expect.stringContaining(expected) })
    await ui.unmount()
  }
})

test('格式不完整的 marker：缺的欄位顯示「?」並註明閘門仍會擋；無法解析的檔另列', async ($, on) => {
  /** 缺 repoRoot／commitHash 的 marker */
  const partial = { ...MARKER, file: 'p.json', repo: null, repoRoot: null, commit: null, sessionId: 'other', missing: ['repoRoot', 'commitHash'] }
  world(on, { files: ['p.json', 'bad.json'], script: { exitCode: 0, stdout: listing([partial], ['bad.json']) } })
  await $.tool.call({ tool: 'Bash', command: 'git status' })
  /** 掛載的 band */
  const ui = await $.ui.mount({ plugin: 'review-band', surface: 'terminal', ...BAND })
  /** marker 那一列 */
  const row = (await ui.find({ type: 'Text', text: /pending-review/ }))?.text ?? ''
  expect(row).toContain('? Tier 3（?）')
  expect(row).toContain('格式不完整（缺 repoRoot, commitHash，閘門仍會擋）')
  expect(row).not.toContain('本 session')
  expect((await ui.find({ type: 'Text', text: /無法解析/ }))?.text).toContain('1 個 marker 檔無法解析（閘門視為無 marker 放行）：bad.json')
  await ui.unmount()
})
