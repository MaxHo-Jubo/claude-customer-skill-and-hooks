import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

const usage = (tokens: number) =>
  ({ input_tokens: 1, output_tokens: 1, cache_read_input_tokens: tokens, cache_creation_input_tokens: 0 })

// 交接紀錄的測試路徑
const FILE = '/repo/.claude/PROJ-1234.md'
// 檔案的修改時間：FRESH 一定晚於存檔開始，STALE 一定早於
const FRESH = 1e15
const STALE = -1

type World = {
  tokens: number
  window?: number
  store?: Record<string, unknown>
  agents?: { id: string; status: string }[]
  files?: Record<string, number>
  // 回傳 true 的 prompt 會被引擎擋下（resolve 成 { drop }），模擬其他 plugin 或 settings hook 攔截
  dropIf?: (text: string) => boolean
}

// 引擎底下的世界：用量、fork、/clear、送出、檔案，全部記下來
const world = (on: On, { tokens, window = 1_000_000, store = {}, agents = [], files = { [FILE]: FRESH }, dropIf = () => false }: World) => {
  const forks: string[] = []
  const commands: string[] = []
  const submits: string[] = []
  // /clear 與送出依發生順序記錄，用來斷言「先 /clear 再送出」
  const events: string[] = []
  const toasts: string[] = []
  const fills: string[] = []
  const clock = mock.clock(on)
  mock.store(on, store)
  on('session.id', () => ({ value: 'S1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens, window }, rateLimits: [] } }))
  on('model.fork', (_$, e: { prompt: string }) => {
    forks.push(e.prompt)
    return { value: { isAnswered: true as const, text: 'OK', usage: usage(tokens) } }
  })
  on('fs.stat', (_$, e: { path: string }) => {
    const mtimeMs = files[e.path]
    if (mtimeMs === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: { kind: 'file' as const, size: 1, mtimeMs, isLink: false } }
  })
  on('command.run', (_$, e: { command: string }) => {
    commands.push(e.command)
    events.push(e.command)
    return { text: '' }
  })
  on('ui.toast', (_$, e: { text: string }) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.log', () => ({ value: undefined }))
  on('prompt.fill', (_$, e: { text: string }) => {
    fills.push(e.text)
    return { isFilled: true }
  })
  on('session.start', (_$, e: { cwd: string }) => ({ cwd: e.cwd }))
  on('command.register', (_$, e: { name: string }) => ({ value: { command: e.name } }))
  on('turn.start', (_$, e: { turnId: string }) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('agent.list', () => ({ value: agents.map(a => ({ ...a, description: '', type: 'general-purpose' })) }))
  on('tool.call', (_$, e: { tool: string }) => e.tool === 'Workflow'
    ? { result: {}, text: 'Workflow started in the background. Task ID: wf_abc123' }
    : { result: { stdout: '', stderr: '', interrupted: false, backgroundTaskId: 'bg123456' } })
  on('prompt.submit', (_$, e: { text?: string }) => {
    const text = e.text ?? ''
    if (dropIf(text)) {
      return { drop: 'blocked by test hook' }
    }
    submits.push(text)
    events.push(`submit:${text}`)
    return { text }
  })
  return { clock, forks, commands, submits, events, toasts, fills }
}

// 模擬 session 啟動：預設為有人在 prompt 前的 REPL；isInteractive=false 代表 -p／SDK
const boot = ($: Engine, isInteractive = true) =>
  $.session.start({ cwd: '/repo', surface: isInteractive ? 'terminal' : null, isInteractive })

const command = ($: Engine, name: string, args = '') =>
  $.command.run({ command: name, args, origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } })

const resume = ($: Engine) => command($, 'handoff-resume')

// 模擬使用者在輸入框送出訊息（composer），回傳 hook 鏈的結果（被攔下時含 drop）
const userSays = ($: Engine, text: string) =>
  $.prompt.submit({ text, origin: { kind: 'composer' }, wait: false })

// 讀 /handoff-status 的輸出（測試用的 $ 沒有 store，改從狀態指令觀察離席紀錄）
const status = async ($: Engine) => (await command($, 'handoff-status')).text

const endTurn = ($: Engine, turnId = 't1', answer = 'ok', reason: 'answer' | 'aborted' = 'answer') =>
  $.turn.complete({ answer, durationMs: 1, isAborted: reason === 'aborted', turnId, reason })

// 模擬引擎跑起 mod 送出的存檔 prompt：turn.start 帶該 prompt，結束時回覆 answer
// prompt 為 undefined（mod 沒送出）時 turn.start 認不出標記，後續斷言會失敗
const runSave = async ($: Engine, prompt: string | undefined, answer = `存好了\nHANDOFF_FILE: ${FILE}`, reason: 'answer' | 'aborted' = 'answer') => {
  await $.turn.start({ text: prompt ?? '', turnId: 'save1' })
  await endTurn($, 'save1', answer, reason)
}

test('達 600k：跑 save-progress → 驗證交接紀錄 → /clear → 新對話讀交接紀錄', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  expect(w.forks).toEqual([])
  expect(w.submits.length).toBe(1)
  expect(w.submits[0]).toContain('[ctx-handoff:save]')
  expect(w.submits[0]).toContain('save-progress')
  expect(w.commands).toEqual([])
  await runSave($, w.submits[0])
  await w.clock.advance(0)
  expect(w.commands).toEqual(['clear'])
  expect(w.submits.length).toBe(2)
  expect(w.submits[1]).toContain(FILE)
  // 先 /clear 再送出：反過來的話開場 prompt 會進舊對話，接著被清掉
  expect(w.events.slice(-2).map(x => x.split(':')[0])).toEqual(['clear', 'submit'])
  // /clear 成功後 busy 歸零：下一次達門檻還能再交接
  await endTurn($, 't9')
  await w.clock.advance(0)
  expect(w.submits.at(-1)).toContain('[ctx-handoff:save]')
})

test('200k 視窗：門檻降為 160k', async ($, on) => {
  const w = world(on, { tokens: 170_000, window: 200_000 })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  expect(w.submits[0]).toContain('[ctx-handoff:save]')
})

test('交接紀錄不存在：不 /clear，並以 toast 告知', async ($, on) => {
  const w = world(on, { tokens: 650_000, files: {} })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  await runSave($, w.submits[0])
  await w.clock.advance(0)
  expect(w.commands).toEqual([])
  expect(w.submits.length).toBe(1)
  expect(w.toasts.some(t => t.includes('交接取消'))).toBe(true)
})

test('交接紀錄是舊檔（存檔開始前就寫的）：不 /clear', async ($, on) => {
  const w = world(on, { tokens: 650_000, files: { [FILE]: STALE } })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  await runSave($, w.submits[0])
  await w.clock.advance(0)
  expect(w.commands).toEqual([])
})

test('回覆沒有 HANDOFF_FILE 或不是絕對路徑：不 /clear', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  await runSave($, w.submits[0], 'HANDOFF_FILE: .claude/PROJ-1234.md')
  await w.clock.advance(0)
  expect(w.commands).toEqual([])
})

test('回覆有多個 HANDOFF_FILE：取最後一個，可帶反引號', async ($, on) => {
  const other = '/repo/.claude/handoff-main.md'
  const w = world(on, { tokens: 650_000, files: { [other]: FRESH } })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  await runSave($, w.submits[0], `HANDOFF_FILE: ${FILE}\n改存到\nHANDOFF_FILE: \`${other}\``)
  await w.clock.advance(0)
  expect(w.commands).toEqual(['clear'])
  expect(w.submits[1]).toContain(other)
})

test('存檔回合被中斷：不 /clear，下一個達門檻的回合再試', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  await runSave($, w.submits[0], '', 'aborted')
  await w.clock.advance(0)
  expect(w.commands).toEqual([])
  await endTurn($, 't2')
  await w.clock.advance(0)
  expect(w.submits.length).toBe(2)
  expect(w.submits[1]).toContain('[ctx-handoff:save]')
})

test('存檔中使用者插話的回合：不觸發交接，也不重送存檔 prompt', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  await $.turn.start({ text: '使用者插話', turnId: 'u1' })
  await endTurn($, 'u1')
  await w.clock.advance(0)
  expect(w.submits.length).toBe(1)
  expect(w.commands).toEqual([])
  await runSave($, w.submits[0])
  await w.clock.advance(0)
  expect(w.commands).toEqual(['clear'])
})

test('存檔回合一直沒被認出：10 分鐘後解除，之後能再觸發', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  await w.clock.advance(11 * 60_000)
  await endTurn($, 't2')
  await w.clock.advance(0)
  expect(w.submits.length).toBe(1)
  await endTurn($, 't3')
  await w.clock.advance(0)
  expect(w.submits.length).toBe(2)
  expect(w.submits[1]).toContain('[ctx-handoff:save]')
})

test('門檻以下閒置：刷新 3 次後跑 save-progress 存離席交接，不 /clear', async ($, on) => {
  const w = world(on, { tokens: 100_000 })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  for (let i = 1; i <= 3; i++) {
    await w.clock.advance(55 * 60_000)
    expect(w.forks).toEqual(Array(i).fill('只回覆 OK'))
  }
  await w.clock.advance(55 * 60_000)
  expect(w.forks.length).toBe(3)
  expect(w.submits.length).toBe(1)
  expect(w.submits[0]).toContain('離席')
  await runSave($, w.submits[0])
  await w.clock.advance(0)
  expect(w.commands).toEqual([])
  // 之後不再刷新或重存
  await w.clock.advance(5 * 60 * 60_000)
  expect(w.forks.length).toBe(3)
  expect(w.submits.length).toBe(1)
  // 存下的離席交接能用 /handoff-resume 取回
  await resume($)
  await w.clock.advance(0)
  expect(w.commands).toEqual(['clear'])
  expect(w.submits[1]).toContain(FILE)
})

test('刷新關閉：閒置 55 分鐘直接跑 save-progress', async ($, on) => {
  const w = world(on, { tokens: 100_000, store: { refresh: false } })
  await boot($)
  await endTurn($)
  await w.clock.advance(55 * 60_000)
  expect(w.forks).toEqual([])
  expect(w.submits[0]).toContain('[ctx-handoff:save]')
})

test('context 太小：不刷新也不存檔', async ($, on) => {
  const w = world(on, { tokens: 10_000 })
  await boot($)
  await endTurn($)
  await w.clock.advance(5 * 60 * 60_000)
  expect(w.forks).toEqual([])
  expect(w.submits).toEqual([])
})

test('handoff-resume：/clear 後送出交接紀錄路徑和被攔下的訊息', async ($, on) => {
  const w = world(on, { tokens: 100_000, store: { 'away:S1': { file: FILE, held: '我回來了' } } })
  await boot($)
  await resume($)
  await w.clock.advance(0)
  expect(w.commands).toContain('clear')
  expect(w.submits[0]).toContain(FILE)
  expect(w.submits[0]).toContain('我回來了')
  // 用過就刪：再跑一次不會再 /clear
  await resume($)
  await w.clock.advance(0)
  expect(w.commands).toEqual(['clear'])
})

test('背景 shell 還在跑：延後交接，通知到了再做', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($)
  await $.tool.call({ tool: 'Bash', command: 'sleep 999', run_in_background: true })
  await endTurn($)
  await w.clock.advance(0)
  expect(w.submits).toEqual([])
  // 背景工作結束的通知會帶 task id，並觸發下一個回合
  await $.prompt.submit({ text: '<task-notification> bg123456 completed', origin: { kind: 'task-notification' }, wait: false })
  await endTurn($)
  await w.clock.advance(0)
  expect(w.submits.at(-1)).toContain('[ctx-handoff:save]')
})

test('子代理還在跑：延後交接', async ($, on) => {
  const w = world(on, { tokens: 650_000, agents: [{ id: 'a1', status: 'running' }] })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  expect(w.submits).toEqual([])
})

test('背景 Workflow：從輸出抓到 task id，延後到通知再做', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($)
  await $.tool.call({ tool: 'Workflow', script: 'export const meta = {}' })
  await endTurn($)
  await w.clock.advance(0)
  expect(w.submits).toEqual([])
  await $.prompt.submit({ text: '<task-notification> wf_abc123 completed', origin: { kind: 'task-notification' }, wait: false })
  await endTurn($)
  await w.clock.advance(0)
  expect(w.submits.at(-1)).toContain('[ctx-handoff:save]')
})

test('非互動 session（-p／SDK）：達門檻不交接、閒置不刷新也不存檔', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($, false)
  await endTurn($)
  await w.clock.advance(0)
  await w.clock.advance(5 * 60 * 60_000)
  expect(w.submits).toEqual([])
  expect(w.forks).toEqual([])
  expect(w.commands).toEqual([])
})

test('連續驗證失敗達上限：暫停自動交接，不再每個回合插入存檔回合', async ($, on) => {
  const w = world(on, { tokens: 650_000, files: {} })
  await boot($)
  for (const t of ['t1', 't2']) {
    await endTurn($, t)
    await w.clock.advance(0)
    await runSave($, w.submits.at(-1))
    await w.clock.advance(0)
  }
  expect(w.submits.length).toBe(2)
  expect(w.toasts.at(-1)).toContain('自動交接暫停')
  await endTurn($, 't3')
  await w.clock.advance(0)
  expect(w.submits.length).toBe(2)
})

test('存檔 prompt 被攔下（drop）：解除存檔中狀態並告知，下一個達門檻回合可再試', async ($, on) => {
  let block = true
  const w = world(on, { tokens: 650_000, dropIf: t => block && t.includes('[ctx-handoff:save]') })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  expect(w.submits).toEqual([])
  expect(w.toasts.some(t => t.includes('存檔 prompt 送出失敗'))).toBe(true)
  block = false
  await endTurn($, 't2')
  await w.clock.advance(0)
  expect(w.submits[0]).toContain('[ctx-handoff:save]')
})

test('/clear 後開場 prompt 被攔下（drop）：toast 告知交接紀錄路徑，不靜默', async ($, on) => {
  const w = world(on, { tokens: 650_000, dropIf: t => t.includes('請先讀交接紀錄') })
  await boot($)
  await endTurn($)
  await w.clock.advance(0)
  await runSave($, w.submits[0])
  await w.clock.advance(0)
  expect(w.commands).toEqual(['clear'])
  expect(w.toasts.some(t => t.includes(FILE))).toBe(true)
})

test('離席攔截：回來後第一則訊息被攔下並存起來，第二次送出則放行並刪除離席紀錄', async ($, on) => {
  const w = world(on, { tokens: 100_000, store: { 'away:S1': { file: FILE } } })
  await boot($)
  const first = await userSays($, '我回來了')
  expect(first.drop).toContain('離席交接紀錄')
  expect(await status($)).toContain('已攔下一則訊息')
  const slash = await userSays($, '/handoff-status')
  expect(slash.drop).toBeUndefined()
  const second = await userSays($, '我回來了')
  expect(second.drop).toBeUndefined()
  expect(await status($)).toContain('離席交接：無')
  expect(w.submits).toContain('我回來了')
})

test('handoff-continue：送出被攔下的訊息；被擋下時放回輸入框並保留離席紀錄', async ($, on) => {
  const w = world(on, { tokens: 100_000, store: { 'away:S1': { file: FILE, held: '我回來了' } }, dropIf: t => t === '我回來了' })
  await boot($)
  await command($, 'handoff-continue')
  await w.clock.advance(0)
  expect(w.fills).toEqual(['我回來了'])
  expect(await status($)).toContain('已攔下一則訊息')
  expect(w.toasts.length).toBe(1)
})

test('handoff-now：沒打 yes 不動作；打 yes 走完存檔 → /clear', async ($, on) => {
  const w = world(on, { tokens: 100_000 })
  await boot($)
  await command($, 'handoff-now')
  await w.clock.advance(0)
  expect(w.submits).toEqual([])
  await command($, 'handoff-now', 'yes')
  await w.clock.advance(0)
  expect(w.submits[0]).toContain('[ctx-handoff:save]')
  await runSave($, w.submits[0])
  await w.clock.advance(0)
  expect(w.commands).toEqual(['clear'])
})

test('使用者中斷達門檻的一般回合（aborted）：不觸發交接', async ($, on) => {
  const w = world(on, { tokens: 650_000 })
  await boot($)
  await endTurn($, 't1', '', 'aborted')
  await w.clock.advance(0)
  expect(w.submits).toEqual([])
})
