import { expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'

/** 測試用 HOME */
const HOME = '/home/u'
/** 被寫入的檔案路徑 */
const FILE = '/home/u/.claude/skills/foo/SKILL.md'
/** 工具成功時下層回傳的結果 */
const WRITE_RESULT = { type: 'create' as const, filePath: FILE, content: 'x', structuredPatch: [], originalFile: null }

/** CHECKS 裡的腳本檔名；限定 key 避免打錯檔名時 fixture 悄悄退回預設 */
type ScriptName = 'inventory-drift-detector.ts' | 'spec-section-validator.ts'

/** 單一腳本的模擬行為：正常結束（exit + 輸出）或拋錯（模擬逾時／bun 不存在），兩者互斥 */
type Script =
  | {
      /** 子行程 exit code */
      exitCode: number
      /** 標準輸出 */
      stdout?: string
      /** 標準錯誤 */
      stderr?: string
      /** 正常結束的分支不得同時帶 throws */
      throws?: never
    }
  | {
      /** process.run 拋出的錯誤訊息 */
      throws: string
    }

/** 下層 tool.call 的模擬行為 */
type ToolOutcome = 'ok' | 'error' | 'deny'

/** 測試世界設定 */
type World = {
  /** 依腳本檔名決定行為；沒列的腳本正常結束、無輸出 */
  scripts?: Partial<Record<ScriptName, Script>>
  /** 下層 tool.call 的結果 */
  tool?: ToolOutcome
  /** 下層 tool.call 已帶的 context（模擬其他 plugin 的提醒） */
  baseContext?: string[]
  /** $.env.get('HOME') 的回傳值 */
  home?: string
}

/**
 * 建立引擎底下的世界：模擬 env／process／ui／tool，並記錄子行程、toast、transcript log。
 * @param on - 測試框架提供的 hook 註冊函式，掛在受測 plugin 之下充當引擎
 * @param config - 世界設定（見 World）
 * @returns 各種紀錄陣列
 */
const world = (on: On, { scripts = {}, tool = 'ok', baseContext, home = HOME }: World = {}) => {
  // STEP 01: 紀錄容器
  /** 執行過的子行程：argv、stdin 與逾時設定 */
  const runs: { argv: readonly string[]; stdin?: string; timeoutMs?: number }[] = []
  /** 跳出的 toast 文字 */
  const toasts: string[] = []
  /** 寫進 transcript 的 log */
  const logs: string[] = []
  // STEP 02: 模擬 env 與 ui
  on('env.get', () => ({ value: home }))
  on('ui.toast', (_$, e: { text: string }) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.log', (_$, e: { text: string }) => {
    logs.push(e.text)
    return { value: undefined }
  })
  // STEP 03: 模擬子行程，依腳本檔名回傳設定的行為
  on('process.run', (_$, e: { argv: readonly string[]; init?: { stdin?: string; timeoutMs?: number } }) => {
    runs.push({ argv: e.argv, stdin: e.init?.stdin, timeoutMs: e.init?.timeoutMs })
    /** 依腳本檔名查到的模擬行為 */
    const s = scripts[(e.argv[1]?.split('/').pop() ?? '') as ScriptName]
    if (s && 'throws' in s && s.throws !== undefined) {
      throw new Error(s.throws)
    }
    return {
      value: { exitCode: s?.exitCode ?? 0, stdout: s?.stdout ?? '', stderr: s?.stderr ?? '', isStdoutTruncated: false, isStderrTruncated: false },
    }
  })
  // STEP 04: 模擬下層 tool.call
  on('tool.call', () => {
    if (tool === 'deny') {
      return { deny: 'nope' }
    }
    if (tool === 'error') {
      return { isError: true as const, result: 'boom', text: 'boom' }
    }
    return { result: WRITE_RESULT, ...(baseContext ? { context: baseContext } : {}) }
  })
  return { runs, toasts, logs }
}

test('有 drift：輸出附加到 context，argv、stdin、逾時正確', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { scripts: { 'inventory-drift-detector.ts': { exitCode: 0, stdout: '\n[新增 Skill] "foo"\n' } } })
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Write', file_path: FILE, content: 'x' })
  expect(w.runs.map(x => x.argv)).toEqual([
    ['bun', `${HOME}/.claude/scripts/inventory-drift-detector.ts`],
    ['bun', `${HOME}/.claude/scripts/spec-section-validator.ts`, '--warn-only'],
  ])
  expect(JSON.parse(w.runs[0]?.stdin ?? '{}')).toEqual({ tool_name: 'Write', tool_input: { file_path: FILE } })
  expect(w.runs.map(x => x.timeoutMs)).toEqual([10_000, 10_000])
  expect(r.context).toEqual(['[tool-reminders] inventory-drift\n[新增 Skill] "foo"'])
  expect(w.toasts).toEqual([])
})

test('所有檢查都沒輸出：不附加 context；Edit 的 tool_name 照實傳給腳本', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on)
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Edit', file_path: FILE, old_string: 'a', new_string: 'b' })
  expect(w.runs.length).toBe(2)
  expect(JSON.parse(w.runs[0]?.stdin ?? '{}').tool_name).toBe('Edit')
  expect(r.context).toBeUndefined()
})

test('下層已有 context：保留在前，本 mod 的提醒接在後', async ($, on) => {
  world(on, { baseContext: ['other'], scripts: { 'spec-section-validator.ts': { exitCode: 0, stdout: '⚠️ 空骨架' } } })
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Write', file_path: FILE, content: 'x' })
  expect(r.context).toEqual(['other', '[tool-reminders] spec-skeleton\n⚠️ 空骨架'])
})

test('工具本身出錯：不執行任何檢查，原結果照傳', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { tool: 'error' })
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Write', file_path: FILE, content: 'x' })
  expect(w.runs).toEqual([])
  expect(r.isError).toBe(true)
})

test('工具被下層拒絕：不執行任何檢查，deny 照傳', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { tool: 'deny' })
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Write', file_path: FILE, content: 'x' })
  expect(w.runs).toEqual([])
  expect(r.deny).toBe('nope')
})

test('非 Write/Edit 工具：不執行任何檢查', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on)
  await $.tool.call({ tool: 'Read', file_path: FILE })
  expect(w.runs).toEqual([])
})

test('腳本 exit 非 0：toast + transcript log + 告知 model 結果未知，其他檢查照常，原結果不變', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, {
    scripts: {
      'inventory-drift-detector.ts': { exitCode: 1, stderr: 'stdin 不是合法 JSON' },
      'spec-section-validator.ts': { exitCode: 0, stdout: '⚠️ 空骨架' },
    },
  })
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Write', file_path: FILE, content: 'x' })
  expect(w.toasts).toEqual(['[tool-reminders] inventory-drift 檢查失敗'])
  expect(w.logs[0]).toContain('exit 1：stdin 不是合法 JSON')
  expect(r.context).toEqual([
    '[tool-reminders] inventory-drift 檢查執行失敗，本次結果未知：exit 1：stdin 不是合法 JSON',
    '[tool-reminders] spec-skeleton\n⚠️ 空骨架',
  ])
  expect(r.result).toEqual(WRITE_RESULT)
})

test('stderr 為空時失敗原因改帶 stdout 摘錄', async ($, on) => {
  world(on, { scripts: { 'spec-section-validator.ts': { exitCode: 2, stdout: '{"decision":"block"}' } } })
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Write', file_path: FILE, content: 'x' })
  expect(r.context?.[0]).toContain('exit 2：{"decision":"block"}')
})

test('子程序拋錯（逾時／bun 不存在）：走同一個失敗出口', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { scripts: { 'spec-section-validator.ts': { throws: 'timed out' } } })
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Write', file_path: FILE, content: 'x' })
  expect(w.toasts).toEqual(['[tool-reminders] spec-skeleton 檢查失敗'])
  expect(r.context?.[0]).toContain('spec-skeleton 檢查執行失敗')
})

test('HOME 未設定：不執行腳本，每個檢查都走失敗出口', async ($, on) => {
  /** 世界紀錄 */
  const w = world(on, { home: '' })
  /** 受測呼叫的結果 */
  const r = await $.tool.call({ tool: 'Write', file_path: FILE, content: 'x' })
  expect(w.runs).toEqual([])
  expect(w.toasts.length).toBe(2)
  expect(r.context).toEqual([
    '[tool-reminders] inventory-drift 檢查執行失敗，本次結果未知：HOME 未設定',
    '[tool-reminders] spec-skeleton 檢查執行失敗，本次結果未知：HOME 未設定',
  ])
})
