import type { EngineInterface, Register, Timer, TurnCompleteInput } from 'claude-code'

const tag = '[ctx-handoff]'

// 在場 handoff：context 達 min(600k, 視窗 × 80%) 時跑 save-progress → /clear → 讓新對話讀交接紀錄
const THRESHOLD = 600_000
const WINDOW_RATIO = 0.8
// 1 小時快取：最後一次用到快取後 55 分鐘刷新，最多 3 次，第 4 次改跑 save-progress 存離席交接
const IDLE_MS = 55 * 60_000
const MAX_REFRESH = 3
// 太小的 context 重建很便宜，不值得刷新或產生離席交接
const MIN_TOKENS = 30_000
// $.store 保留最近幾筆交接紀錄
const KEEP = 5

// 送給 model 的存檔 prompt 帶這個標記，turn.start 靠它認出存檔回合
const SAVE_MARK = '[ctx-handoff:save]'
// 存檔 prompt（savePrompt）要求 model 在回覆最後一行回報交接紀錄路徑的固定格式；只認回覆中最後一個
const FILE_LINE = /^HANDOFF_FILE:\s*`?([^`\n]+?)`?\s*$/gm
// 存檔 prompt 送出後超過這麼久仍沒有被 turn.start 認出，就視為遺失並解除存檔中狀態。
// 不是計時器：在下一個主對話回合結束（turn.complete）時檢查
const SAVE_LOST_MS = 10 * 60_000
// 連續幾次存檔驗證失敗後，暫停這個 session 的自動交接（避免每個回合都再插一次存檔回合）
const MAX_SAVE_FAILURES = 2
// 絕對路徑（POSIX 或 Windows 磁碟機）
const ABS_PATH = /^(\/|[A-Za-z]:[\\/])/

type Kind = 'present' | 'away' | 'manual'
// $.store 'handoffs' 的一筆：何時、哪個 session、為什麼、交接紀錄在哪
type Saved = { at: number; sessionId: string; kind: Kind; tokens: number | null; file: string }
// 離席交接：交接紀錄路徑，及使用者回來後被攔下的第一則訊息
type Away = { file: string; held?: string }
// 進行中的存檔回合；turnId 在 turn.start 認出標記後才有
type Saving = { kind: Kind; tokens: number | null; startedAt: number; turnId?: string }

const awayKey = (sessionId: string) => `away:${sessionId}`
const thresholdOf = (window: number) => Math.min(THRESHOLD, Math.floor(window * WINDOW_RATIO))

let idle: Timer | undefined
let refreshes = 0
// 有人在 prompt 前（REPL）才做自動交接與閒置刷新；-p／SDK 等無人看管的 session 一律不動，
// 否則會在呼叫端等結果時插入存檔回合並 /clear。session.start 前未知，先當成無人看管
let interactive = false
// /clear 與送出進行中
let busy = false
// 存檔回合進行中（從送出 save prompt 到該回合 turn.complete）
let saving: Saving | undefined
// 連續存檔失敗次數；交接成功歸零，達 MAX_SAVE_FAILURES 就暫停自動交接
let failures = 0
// 背景 shell／workflow／monitor：id → 開始時間（子代理另由 $.agent.list() 查）
const background = new Map<string, number>()
const STALE_MS = 12 * 60 * 60_000
const BG_ID = /\b(?:task[ _-]?id|ID)\b["'\s:=]+([A-Za-z0-9_-]{6,})/i

async function runningWork($: EngineInterface) {
  const now = await $.clock.now()
  for (const [id, at] of background) if (now - at > STALE_MS) background.delete(id)
  const agents = (await $.agent.list()).filter(a => a.status === 'running').length
  return background.size + agents
}

async function isRefreshOn($: EngineInterface) {
  return (await $.store.get('refresh')) !== false
}

/**
 * 送出 prompt；被其他 plugin 或 settings hook 擋下（resolve 成 { drop }，不會 reject）時改為拋出，
 * 讓呼叫端走同一個失敗出口，不會當成已送出。
 * @param $ engine 介面
 * @param text 要送出的 prompt
 * @returns void
 */
async function submit($: EngineInterface, text: string) {
  const r = await $.prompt.submit({ text })
  if (r.drop !== undefined) {
    throw new Error(`prompt 被攔下：${r.drop}`)
  }
}

/**
 * 計時器啟動的非同步工作統一出口：引擎不 await 計時器 callback，reject 會無聲消失，
 * 所以在這裡寫 log 並跳 toast。
 * @param $ engine 介面
 * @param name 工作名稱（顯示在訊息中）
 * @param work 要執行的非同步工作
 * @returns void
 */
function guard($: EngineInterface, name: string, work: Promise<void>) {
  void work.catch(err => {
    $.ui.log(`${tag} ${name} 失敗：${String(err)}`)
    $.ui.toast(`${tag} ${name} 失敗：${String(err)}`)
  })
}

/**
 * 組存檔回合的 prompt：要求 model 跑 save-progress 並回報交接紀錄路徑。
 * @param kind 觸發原因
 * @param tokens 觸發當下的 context token 數
 * @returns 送給 model 的 prompt 文字
 */
function savePrompt(kind: Kind, tokens: number | null) {
  const why = kind === 'manual' ? '使用者執行 /handoff-now'
    : kind === 'away' ? '使用者離席已久，舊對話快取即將過期'
    : `context 已達 ${tokens} tokens`
  return [
    `${SAVE_MARK} ${why}，即將交接給新對話。`,
    '請執行 save-progress skill 存檔交接紀錄，不要做其他工作。',
    '完成後，回覆的最後一行只寫：HANDOFF_FILE: <交接紀錄的絕對路徑>',
  ].join('\n')
}

/**
 * 組新對話的開場 prompt：讀交接紀錄、回報現況、等指示。
 * @param why 上一段對話為何被清掉
 * @param file 交接紀錄的絕對路徑
 * @param held 使用者回來後被攔下的訊息；有就要求新對話回應它
 * @returns 送進新對話的 prompt 文字
 */
function readPrompt(why: string, file: string, held?: string) {
  const head = `${tag} 上一段對話因${why}，已 /clear。請先讀交接紀錄 ${file}` +
    '（若是 Jira 開發筆記，整份讀完，以「## 交接紀錄」段落為準）。'
  return held === undefined
    ? `${head}讀完後用幾行回報你理解的現況與下一步，然後等使用者指示，不要直接動手。`
    : `${head}依交接紀錄的脈絡回應以下使用者訊息：\n\n${held}`
}

/**
 * 從存檔回合的回覆取出交接紀錄路徑。
 * @param answer 該回合 model 最後的可見文字
 * @returns 絕對路徑；沒有或不是絕對路徑時為 undefined
 */
function parseFile(answer: string) {
  const file = [...answer.matchAll(FILE_LINE)].at(-1)?.[1]?.trim()
  return file !== undefined && ABS_PATH.test(file) ? file : undefined
}

/**
 * 送出存檔 prompt，開始一個存檔回合；結果由 turn.complete 交給 finishSave。
 * @param $ engine 介面
 * @param kind 觸發原因
 * @param tokens 觸發當下的 context token 數
 */
async function startSave($: EngineInterface, kind: Kind, tokens: number | null) {
  // STEP 01: 標記存檔中並停掉閒置計時器，避免刷新與存檔重疊
  idle?.cancel()
  idle = undefined
  saving = { kind, tokens, startedAt: await $.clock.now() }
  // STEP 02: 送出存檔 prompt；送不出去就解除標記，不留卡住的狀態
  try {
    await submit($, savePrompt(kind, tokens))
  } catch (err) {
    saving = undefined
    $.ui.log(`${tag} 存檔 prompt 送出失敗：${String(err)}`)
    $.ui.toast(`${tag} 存檔 prompt 送出失敗，未交接`)
  }
}

/**
 * 存檔回合結束後：驗證交接紀錄真的寫好，再依觸發原因 /clear 接續或存成離席交接。
 * 任何一步驗證失敗都不 /clear，避免清掉對話卻沒有交接紀錄。
 * @param $ engine 介面
 * @param s 這個存檔回合的狀態
 * @param e 該回合的 turn.complete 輸入
 */
async function finishSave($: EngineInterface, s: Saving, e: TurnCompleteInput) {
  const fail = (why: string) => {
    failures += 1
    const paused = failures >= MAX_SAVE_FAILURES ? `；已連續 ${failures} 次失敗，自動交接暫停，可用 /handoff-now yes 手動交接` : ''
    $.ui.log(`${tag} 交接取消：${why}${paused}`)
    $.ui.toast(`${tag} 交接取消：${why}${paused}`)
  }
  // STEP 01: 回合要正常結束且回報了絕對路徑
  if (e.reason !== 'answer') {
    return fail(`存檔回合未正常結束（${e.reason}）`)
  }
  const file = parseFile(e.answer)
  if (file === undefined) {
    return fail('回覆中沒有 HANDOFF_FILE 絕對路徑')
  }
  // STEP 02: 檔案要存在，且是這個存檔回合開始後才寫的
  const stat = await $.fs.stat(file).catch(() => undefined)
  if (stat === undefined || stat.kind !== 'file' || stat.mtimeMs < s.startedAt) {
    return fail(`交接紀錄未寫入：${file}`)
  }
  // STEP 03: 記錄這次交接
  failures = 0
  const sessionId = await $.session.id()
  const saved: Saved = { at: await $.clock.now(), sessionId, kind: s.kind, tokens: s.tokens, file }
  const list = ((await $.store.get('handoffs')) as Saved[] | undefined) ?? []
  await $.store.set('handoffs', [...list, saved].slice(-KEEP))
  // STEP 04: 離席只存不清；在場／手動則 /clear 後讓新對話讀交接紀錄
  if (s.kind === 'away') {
    await $.store.set(awayKey(sessionId), { file } satisfies Away)
    $.ui.log(`${tag} 離席交接已存好（${s.tokens} tokens）：${file}，不會自動 /clear`)
    $.ui.toast(`${tag} 離席交接已存好`)
    return
  }
  const why = s.kind === 'manual' ? '手動執行 /handoff-now' : `context 達 ${s.tokens} tokens`
  busy = true
  try {
    await clearAndSubmit($, readPrompt(why, file))
    refreshes = 0
  } catch (err) {
    $.ui.log(`${tag} /clear 或送出失敗：${String(err)}；交接紀錄在 ${file}`)
    $.ui.toast(`${tag} /clear 或送出失敗，交接紀錄在 ${file}，請手動讀取`)
  } finally {
    busy = false
  }
}

// /clear → 把開場 prompt 送進新對話；被攔下時拋出（見 submit）
async function clearAndSubmit($: EngineInterface, text: string) {
  await $.command.run({ command: 'clear' })
  await submit($, text)
}

function schedule($: EngineInterface) {
  idle?.cancel()
  idle = $.clock.after(IDLE_MS, () => guard($, '閒置刷新（已停止，下個回合後重新排程）', onIdle($)))
}

async function onIdle($: EngineInterface) {
  idle = undefined
  if (busy || saving !== undefined) return
  // 已有離席交接就不再刷新或重存（例如背景通知又跑了一個回合）
  if ((await $.store.get(awayKey(await $.session.id()))) !== undefined) return
  const { context } = await $.session.usage()
  const tokens = context.tokens ?? 0
  if (tokens < MIN_TOKENS) return

  if ((await isRefreshOn($)) && refreshes < MAX_REFRESH) {
    const r = await $.model.fork({ prompt: '只回覆 OK' })
    refreshes += 1
    $.ui.log(r.isAnswered
      ? `${tag} 快取刷新 ${refreshes}/${MAX_REFRESH} cache_read=${r.usage.cache_read_input_tokens} cache_creation=${r.usage.cache_creation_input_tokens}`
      : `${tag} 快取刷新 ${refreshes}/${MAX_REFRESH} 失敗：${r.reason}`)
    schedule($)
    return
  }

  await startSave($, 'away', tokens)
}

export const register: Register = on => {
  idle = undefined
  refreshes = 0
  interactive = false
  busy = false
  saving = undefined
  failures = 0
  background.clear()

  on('session.start', async ($, e, next) => {
    interactive = e.isInteractive
    for (const [name, description] of [
      ['handoff-status', 'ctx-handoff: 顯示 context 用量、門檻、刷新與離席交接狀態'],
      ['handoff-refresh', 'ctx-handoff: 開關閒置時的快取刷新（on / off）'],
      ['handoff-resume', 'ctx-handoff: 用離席交接紀錄開新對話接續（會 /clear）'],
      ['handoff-continue', 'ctx-handoff: 放棄離席交接，在舊對話送出剛才被攔下的訊息'],
      ['handoff-now', 'ctx-handoff: 立刻 save-progress 並 /clear；參數要打 yes'],
    ] as const) {
      await $.command.register({ name, description })
    }
    return next(e)
  })

  // 認出存檔回合：記下它的 turnId，turn.complete 才知道哪個回合是它
  on('turn.start', async ($, e, next) => {
    if (saving !== undefined && saving.turnId === undefined && e.text.includes(SAVE_MARK)) {
      saving = { ...saving, turnId: e.turnId }
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const out = await next(e)
    if (e.agentId !== undefined) return out
    // 存檔中：只處理存檔回合本身，其他回合（使用者插話）不觸發任何事
    if (saving !== undefined) {
      const s = saving
      if (e.turnId === s.turnId) {
        saving = undefined
        $.clock.after(0, () => guard($, '交接', finishSave($, s, e)))
      } else if (s.turnId === undefined && (await $.clock.now()) - s.startedAt > SAVE_LOST_MS) {
        saving = undefined
        $.ui.log(`${tag} 交接取消：存檔回合送出 ${SAVE_LOST_MS / 60_000} 分鐘仍未被辨識（交接紀錄可能已寫入）`)
        $.ui.toast(`${tag} 交接取消：存檔回合未被辨識，交接紀錄可能已寫入，請用 /handoff-status 或手動確認`)
      }
      return out
    }
    if (busy || !interactive) return out
    // 每個回合都用到快取，TTL 從這裡重算
    schedule($)
    if (e.reason !== 'answer') return out
    const { context } = await $.session.usage()
    if (context.tokens === undefined || context.tokens < thresholdOf(context.window)) return out
    const tokens = context.tokens
    // 連續失敗已達上限：不再自動插入存檔回合，改由使用者 /handoff-now 手動
    if (failures >= MAX_SAVE_FAILURES) {
      $.ui.status(`${tag} 自動交接暫停（連續 ${failures} 次失敗），可用 /handoff-now yes`)
      return out
    }
    // 還有背景工作就先不交接：它結束時的通知會再跑一個回合，到時再判斷
    const running = await runningWork($)
    if (running > 0) {
      $.ui.status(`${tag} 交接延後：${running} 個背景工作還在跑`)
      $.ui.log(`${tag} context ${tokens} 已達門檻，但有 ${running} 個背景工作，等它們結束再交接`)
      return out
    }
    $.ui.status(undefined)
    $.clock.after(0, () => guard($, '存檔', startSave($, 'present', tokens)))
    return out
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError === true) return ran
    const at = await $.clock.now()
    if (e.tool === 'Bash') {
      const id = (ran.result as { backgroundTaskId?: string } | undefined)?.backgroundTaskId
      if (id !== undefined) background.set(id, at)
    } else if (e.tool === 'Workflow' || e.tool === 'Monitor') {
      const id = BG_ID.exec(ran.text ?? '')?.[1]
      if (id !== undefined) background.set(id, at)
    } else if (e.tool === 'TaskStop') {
      if (e.task_id !== undefined) background.delete(e.task_id)
    }
    return ran
  })

  on('prompt.submit', async ($, e, next) => {
    if (e.origin.kind === 'task-notification') {
      for (const id of background.keys()) if (e.text.includes(id)) background.delete(id)
    }
    const isHuman = e.origin.kind === 'composer' || e.origin.kind === 'bridge'
    if (!isHuman) return next(e)
    idle?.cancel()
    idle = undefined
    refreshes = 0

    const key = awayKey(await $.session.id())
    const away = (await $.store.get(key)) as Away | undefined
    if (away === undefined || e.text.trimStart().startsWith('/')) return next(e)
    if (away.held === undefined) {
      await $.store.set(key, { ...away, held: e.text } satisfies Away)
      return {
        drop: `${tag} 有一份離席交接紀錄（${away.file}），舊對話的快取已過期。` +
          '/handoff-resume：開新對話接續，並帶上這則訊息；/handoff-continue：在舊對話送出這則訊息（或直接再送一次）。',
      }
    }
    // 第二次直接送出＝選擇繼續舊對話
    await $.store.delete(key)
    return next(e)
  })

  on('command.run', { command: 'handoff-status' }, async $ => {
    const { context } = await $.session.usage()
    const away = (await $.store.get(awayKey(await $.session.id()))) as Away | undefined
    const list = ((await $.store.get('handoffs')) as Saved[] | undefined) ?? []
    const last = list.at(-1)
    return {
      text: [
        `${tag} context ${context.tokens ?? '?'} / 門檻 ${thresholdOf(context.window)}（視窗 ${context.window}）`,
        `自動交接：${!interactive ? 'off（非互動 session：-p／SDK）' : failures >= MAX_SAVE_FAILURES ? `暫停（連續 ${failures} 次失敗）` : 'on'}`,
        `快取刷新 ${(await isRefreshOn($)) ? 'on' : 'off'}，本次閒置已刷新 ${refreshes}/${MAX_REFRESH}，計時器${idle ? '等待中' : '未啟動'}`,
        `存檔回合：${saving ? `進行中（${saving.kind}${saving.turnId ? '' : '，尚未開始'}）` : '無'}`,
        `離席交接：${away ? `${away.file}${away.held === undefined ? '' : '（已攔下一則訊息）'}` : '無'}`,
        `最近一份交接：${last ? `${new Date(last.at).toLocaleString()} ${last.kind} ${last.file}` : '無'}`,
      ].join('\n'),
    }
  })

  on('command.run', { command: 'handoff-refresh' }, async ($, e) => {
    const arg = e.args.trim()
    if (arg !== 'on' && arg !== 'off') return { text: `${tag} 目前 ${(await isRefreshOn($)) ? 'on' : 'off'}；用法 /handoff-refresh on|off` }
    await $.store.set('refresh', arg === 'on')
    return { text: `${tag} 快取刷新已設為 ${arg}${arg === 'off' ? `（閒置 ${IDLE_MS / 60_000} 分鐘就直接存離席交接）` : ''}` }
  })

  on('command.run', { command: 'handoff-resume' }, async $ => {
    const key = awayKey(await $.session.id())
    const away = (await $.store.get(key)) as Away | undefined
    if (away === undefined) return { text: `${tag} 沒有離席交接紀錄` }
    const text = readPrompt('閒置過久', away.file, away.held)
    busy = true
    // 成功後才刪離席紀錄：失敗時被攔下的訊息（held）還留在 store，可再 /handoff-resume 或 /handoff-continue
    const resume = async () => {
      try {
        await clearAndSubmit($, text)
        await $.store.delete(key)
      } finally {
        busy = false
      }
    }
    $.clock.after(0, () => guard($, `離席接續（交接紀錄在 ${away.file}）`, resume()))
    return { text: `${tag} 即將 /clear 並讓新對話讀 ${away.file}` }
  })

  on('command.run', { command: 'handoff-continue' }, async $ => {
    const key = awayKey(await $.session.id())
    const away = (await $.store.get(key)) as Away | undefined
    if (away === undefined) return { text: `${tag} 沒有離席交接紀錄` }
    const held = away.held
    if (held === undefined) {
      await $.store.delete(key)
      return { text: `${tag} 已捨棄離席交接，繼續舊對話` }
    }
    // 送出成功才刪離席紀錄；送不出去就把訊息放回輸入框，不讓使用者的原文消失
    const resend = async () => {
      try {
        await submit($, held)
        await $.store.delete(key)
      } catch (err) {
        await $.prompt.fill({ text: held })
        throw err
      }
    }
    $.clock.after(0, () => guard($, '送出被攔下的訊息（已放回輸入框）', resend()))
    return { text: `${tag} 已捨棄離席交接，在舊對話送出剛才的訊息` }
  })

  on('command.run', { command: 'handoff-now' }, async ($, e) => {
    if (e.args.trim() !== 'yes') return { text: `${tag} 會先跑 save-progress 再清掉目前對話；確定請打 /handoff-now yes` }
    if (busy || saving !== undefined) return { text: `${tag} 正在處理另一個交接` }
    const { context } = await $.session.usage()
    const tokens = context.tokens ?? null
    $.clock.after(0, () => guard($, '存檔', startSave($, 'manual', tokens)))
    return { text: `${tag} 將跑 save-progress，寫好交接紀錄後 /clear 再接續` }
  })
}
