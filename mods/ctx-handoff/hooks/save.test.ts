// 本機改版：在場／手動／離席交接改跑 save-progress 存檔回合 → 驗證交接紀錄檔 → /clear（離席只存）→ 新對話讀檔（由舊版 register.test.ts 移植並補強）
import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { HANDOFF_FILE, STALE, cmd, composer, ctl, presentation, runSave, say, startSession, stop, world } from './test-world'
import { MAX_SAVE_FAILURES, MS_PER_MIN, SAVE_LOST_MS, savePrompt } from './save'

/** 存檔 prompt 的標記 */
const MARK = '[ctx-handoff:save]'
/** 超過門檻的 context token 數（1M 視窗的門檻是 600k） */
const OVER = 650_000
/** 門檻以下、但大於 min_tokens 的 context token 數 */
const UNDER = 100_000
/** context 視窗大小 */
const WINDOW = 1_000_000
/** 上游的失敗後重試間隔（RETRY_MS） */
const RETRY_WAIT = 10 * MS_PER_MIN
/** 閒置多久刷新一次（idle_minutes 預設） */
const IDLE = 55 * MS_PER_MIN
/** 閒置刷新的次數上限（max_refresh 預設） */
const MAX_REFRESH = 3
/** 每幾則使用者訊息整理一次（distill_every 預設） */
const DISTILL_EVERY = 30
/** mtime 邊界測試的存檔開始時間 */
const START_AT = 1_000
/** 舊格式（上游 fork 摘要）的離席紀錄 */
const OLD_AWAY = { handoff: 'HANDOFF: 舊摘要' }

/**
 * 以使用者身分執行舊指令名（/handoff-now、/handoff-status、/handoff-resume…）。
 * @param $ 測試的 engine
 * @param name 指令名稱（不含 /）
 * @param args 指令參數
 * @returns command.run 的結果
 */
const legacy = ($: Engine, name: string, args = '') => $.command.run({ command: name, args, origin: composer, presentation })

/**
 * 模擬 session 啟動；isInteractive=false 代表 -p／SDK。
 * @param $ 測試的 engine
 * @param isInteractive 是否互動 session
 * @returns session.start 的結果
 */
const boot = ($: Engine, isInteractive: boolean) => $.session.start({ cwd: 'C:/proj', surface: isInteractive ? 'terminal' : null, isInteractive })

/**
 * 模擬一個主對話回合結束（可指定 turnId 與子代理）。
 * @param $ 測試的 engine
 * @param turnId 回合 id
 * @param agentId 子代理 id；主對話不帶
 * @returns turn.complete 的結果
 */
const complete = ($: Engine, turnId = 't1', agentId?: string) =>
  $.turn.complete({ answer: `HANDOFF_FILE: ${HANDOFF_FILE}`, durationMs: 1, isAborted: false, turnId, reason: 'answer', ...(agentId ? { agentId } : {}) })

/**
 * 送出過幾次存檔 prompt。
 * @param w 測試世界
 * @returns 次數
 */
const saves = (w: { submits: string[] }) => w.submits.filter(s => s.includes(MARK)).length

/**
 * 達門檻並跑到存檔 prompt 送出為止。
 * @param $ 測試的 engine
 * @param w 測試世界
 * @returns void
 */
const reachThreshold = async ($: Engine, w: { clock: { advance: (ms: number) => Promise<void> } }) => {
  // STEP 01: 主對話停下，交接延到下一個 tick 開始
  await stop($)
  await w.clock.advance(0)
}

/** 門檻交接主流程：存檔回合 → 驗證 → /clear → 讀檔 prompt，不 fork 摘要 */
test('達門檻：跑 save-progress → 驗證交接紀錄 → /clear → 新對話讀交接紀錄（不用 fork 摘要）', async ($, on) => {
  // STEP 01: 達門檻，送出帶標記的存檔 prompt，還沒 /clear
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  expect(w.submits.length).toBe(1)
  expect(w.submits[0]).toContain(MARK)
  expect(w.submits[0]).toContain('save-progress')
  expect(w.submits[0]).toContain('HANDOFF_FILE:')
  expect(w.commands).toEqual([])
  // STEP 02: 存檔回合結束後 /clear，送出讀檔 prompt
  await runSave($, w)
  expect(w.commands).toEqual(['clear'])
  expect(w.submits.length).toBe(2)
  expect(w.submits[1]).toContain(HANDOFF_FILE)
  expect(w.forks.length).toBe(0)
  // STEP 03: 最近一份交接記下檔案路徑
  /** store 裡的交接紀錄清單 */
  const list = w.get('handoffs:C--proj') as { file?: string; kind: string }[]
  expect(list.at(-1)?.file).toBe(HANDOFF_FILE)
  expect(list.at(-1)?.kind).toBe('present')
})

/** 存檔 prompt 的形狀：tag 開頭、帶標記與這次嘗試的識別碼 */
test('存檔 prompt 以 [ctx-handoff] 開頭（整理不把它當使用者的話），並帶存檔標記與嘗試識別碼', () => {
  // STEP 01: 三種觸發原因都帶標記與識別碼
  expect(savePrompt('present', OVER, 'a1').startsWith('[ctx-handoff] ')).toBe(true)
  expect(savePrompt('manual', null, 'a1')).toContain(MARK)
  expect(savePrompt('away', UNDER, 'a2')).toContain('[ctx-handoff:attempt:a2]')
})

/** 交接紀錄驗證失敗的各種情況：都不 /clear */
for (const [name, opts, reason] of [
  ['不存在', { write: false }, '交接紀錄未寫入'],
  ['是空檔', { content: '' }, '交接紀錄是空的'],
  ['只有空白', { content: ' \n\t ' }, '交接紀錄是空的'],
] as const) {
  test(`交接紀錄${name}：不 /clear，toast 告知`, async ($, on) => {
    // STEP 01: 達門檻並跑存檔回合
    const w = world(on, OVER, WINDOW, { distill: false })
    await startSession($)
    await reachThreshold($, w)
    await runSave($, w, opts)
    // STEP 02: 保留原對話並告知
    expect(w.commands).toEqual([])
    expect(w.toasts.some(s => s.includes(reason))).toBe(true)
  })
}

/** 交接紀錄存在但讀不到：失敗，不用空字串頂替 */
test('交接紀錄讀不到：不 /clear，toast 寫出讀不到', async ($, on) => {
  // STEP 01: 讀檔失敗
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  ctl.failRead = HANDOFF_FILE
  await runSave($, w)
  // STEP 02: 保留原對話並告知
  expect(w.commands).toEqual([])
  expect(w.toasts.some(s => s.includes('交接紀錄讀不到'))).toBe(true)
})

/** mtime 邊界：早於存檔開始不算，等於或晚於都算 */
for (const [offset, ok] of [[-1, false], [0, true], [1, true]] as const) {
  test(`交接紀錄 mtime = 存檔開始 ${offset >= 0 ? '+' : ''}${offset} ms：${ok ? '/clear' : '不 /clear'}`, async ($, on) => {
    // STEP 01: 存檔在 START_AT 開始
    const w = world(on, OVER, WINDOW, { distill: false })
    await w.clock.advance(START_AT)
    await startSession($)
    await reachThreshold($, w)
    // STEP 02: 交接紀錄的 mtime 落在邊界附近
    await runSave($, w, { mtime: START_AT + offset })
    expect(w.commands).toEqual(ok ? ['clear'] : [])
  })
}

/** 交接紀錄是存檔開始前就寫的舊檔：不 /clear */
test('交接紀錄是舊檔（存檔開始前就寫的）：不 /clear', async ($, on) => {
  // STEP 01: 舊檔
  const w = world(on, OVER, WINDOW, { distill: false })
  await w.clock.advance(START_AT)
  await startSession($)
  await reachThreshold($, w)
  await runSave($, w, { mtime: STALE })
  // STEP 02: 保留原對話
  expect(w.commands).toEqual([])
  expect(w.toasts.some(s => s.includes('交接紀錄未寫入'))).toBe(true)
})

/** 回覆沒有回報路徑或不是絕對路徑：不 /clear */
for (const [name, answer] of [['沒有 HANDOFF_FILE', '存好了'], ['不是絕對路徑', 'HANDOFF_FILE: notes/a.md']] as const) {
  test(`回覆${name}：不 /clear`, async ($, on) => {
    // STEP 01: 存檔回合回覆不合格
    const w = world(on, OVER, WINDOW, { distill: false })
    await startSession($)
    await reachThreshold($, w)
    await runSave($, w, { answer })
    // STEP 02: 保留原對話並告知
    expect(w.commands).toEqual([])
    expect(w.toasts.some(s => s.includes('HANDOFF_FILE'))).toBe(true)
  })
}

/** 回覆有多個路徑：取最後一個，可帶反引號 */
test('回覆有多個 HANDOFF_FILE：取最後一個，可帶反引號', async ($, on) => {
  // STEP 01: 回覆兩個路徑
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  await runSave($, w, { answer: `HANDOFF_FILE: C:/proj/old.md\n說明\nHANDOFF_FILE: \`${HANDOFF_FILE}\`` })
  // STEP 02: 用最後一個
  expect(w.commands).toEqual(['clear'])
  expect(w.submits.at(-1)).toContain(HANDOFF_FILE)
  expect(w.submits.at(-1)).not.toContain('old.md')
})

/** 存檔回合被中斷：不 /clear，重試間隔後再試 */
test('存檔回合被中斷：不 /clear；10 分鐘後的停下再試', async ($, on) => {
  // STEP 01: 中斷
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  await runSave($, w, { reason: 'aborted' })
  expect(w.commands).toEqual([])
  expect((w.get('handoff:error:C--proj') as { reason: string }).reason).toContain('aborted')
  // STEP 02: 上游的重試間隔：剛失敗不馬上再插存檔回合
  await reachThreshold($, w)
  expect(saves(w)).toBe(1)
  await w.clock.advance(RETRY_WAIT)
  await reachThreshold($, w)
  expect(saves(w)).toBe(2)
})

/** 存檔回合被認出後：別的回合或子代理的結束都不算，仍在等 */
test('存檔回合配對：不同 turnId、子代理的完成事件都不結束等待；真正的存檔回合結束才 /clear', async ($, on) => {
  // STEP 01: 認出存檔回合
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  w.files.set(HANDOFF_FILE, '# 交接紀錄')
  await $.turn.start({ text: w.submits[0] ?? '', turnId: 'save-a' })
  // STEP 02: 不同 turnId 與子代理（同 turnId）的完成：仍在等
  await complete($, 'other')
  await complete($, 'save-a', 'agent-1')
  await w.clock.settle()
  expect(w.commands).toEqual([])
  expect(w.submits.length).toBe(1)
  // STEP 03: 真正的存檔回合結束
  await complete($, 'save-a')
  await w.clock.settle()
  expect(w.commands).toEqual(['clear'])
})

/** 每次嘗試獨立識別碼：逾時的舊嘗試的回合不會被下一次嘗試誤認 */
test('舊嘗試的存檔 prompt 晚到：下一次嘗試不認它，只認自己的', async ($, on) => {
  // STEP 01: 第一次嘗試沒被認出，逾時取消
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  /** 第一次嘗試的存檔 prompt */
  const first = w.submits[0] ?? ''
  await w.clock.advance(SAVE_LOST_MS)
  await w.clock.settle()
  // STEP 02: 重試間隔後第二次嘗試
  await w.clock.advance(RETRY_WAIT)
  await reachThreshold($, w)
  expect(saves(w)).toBe(2)
  // STEP 03: 第一次的 prompt 這時才跑起來：不被認出，結束也不 /clear
  w.files.set(HANDOFF_FILE, '# 交接紀錄')
  await $.turn.start({ text: first, turnId: 'late' })
  await complete($, 'late')
  await w.clock.settle()
  expect(w.commands).toEqual([])
  // STEP 04: 第二次的存檔回合照常完成
  await runSave($, w)
  expect(w.commands).toEqual(['clear'])
})

/** 只認發起嘗試的 session */
test('別的 session 帶同一份存檔 prompt 的回合：不被認出', async ($, on) => {
  // STEP 01: 送出存檔 prompt 後 session 換了
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  ctl.curSid = 'S9'
  w.files.set(HANDOFF_FILE, '# 交接紀錄')
  await $.turn.start({ text: w.submits[0] ?? '', turnId: 'x' })
  await complete($, 'x')
  await w.clock.settle()
  // STEP 02: 仍在等，沒有 /clear
  expect(w.commands).toEqual([])
})

/** 存檔期間的使用者訊息：攔下，交接後帶進新對話 */
test('存檔中使用者送出訊息：先攔下，交接後連同讀檔 prompt 送進新對話', async ($, on) => {
  // STEP 01: 存檔中送訊息
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  /** 送出結果（應被攔下） */
  const r = await say($, '中途訊息')
  expect((r as { drop?: string }).drop).toContain('save-progress')
  expect(w.submits.length).toBe(1)
  // STEP 02: 交接後一起送出
  await runSave($, w)
  expect(w.commands).toEqual(['clear'])
  expect(w.submits[1]).toContain(HANDOFF_FILE)
  expect(w.submits[1]).toContain('中途訊息')
})

/** 存檔回合一直沒被認出：計時器結束等待，不卡住輸入 */
test('存檔回合一直沒被認出：10 分鐘後結束等待，攔下的訊息送回舊對話，之後能再觸發', async ($, on) => {
  // STEP 01: 存檔中送訊息，一般回合結束不算存檔回合
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  await say($, '等很久的訊息')
  await $.turn.start({ text: '別的回合', turnId: 'other' })
  await complete($, 'other')
  await w.clock.advance(SAVE_LOST_MS - MS_PER_MIN)
  expect(w.submits.at(-1)).toContain(MARK)
  // STEP 02: 到期：取消、送回訊息、記錄原因
  await w.clock.advance(MS_PER_MIN)
  await w.clock.settle()
  expect(w.commands).toEqual([])
  expect(w.submits.at(-1)).toBe('等很久的訊息')
  expect((w.get('handoff:error:C--proj') as { reason: string }).reason).toContain('未被辨識')
  // STEP 03: 不再攔訊息；重試間隔後能再觸發
  await say($, '之後的訊息')
  expect(w.submits.at(-1)).toBe('之後的訊息')
  await w.clock.advance(RETRY_WAIT)
  await reachThreshold($, w)
  expect(saves(w)).toBe(2)
})

/** 突變探測的對照組：每組兩個測試只差 isInteractive（auto_handoff 開、達門檻、沒有背景工作） */
for (const interactive of [true, false]) {
  test(`isInteractive=${interactive}：達門檻${interactive ? '跑存檔回合' : '不交接'}`, async ($, on) => {
    // STEP 01: 達門檻
    const w = world(on, OVER, WINDOW, { distill: false })
    await boot($, interactive)
    await reachThreshold($, w)
    // STEP 02: 只有互動 session 送出存檔 prompt
    expect(saves(w)).toBe(interactive ? 1 : 0)
    expect((await legacy($, 'handoff-status')).text).toContain(interactive ? '自動交接：on' : '自動交接：off（非互動')
  })

  test(`isInteractive=${interactive}：門檻以下閒置${interactive ? '刷新' : '不刷新、不存離席交接'}`, async ($, on) => {
    // STEP 01: 門檻以下閒置到刷新與離席都該發生的時間
    const w = world(on, UNDER)
    await boot($, interactive)
    await complete($)
    await w.clock.advance((MAX_REFRESH + 1) * IDLE)
    // STEP 02: 互動 session 刷新 MAX_REFRESH 次並送出離席存檔 prompt；非互動什麼都不做
    expect(w.forks.length).toBe(interactive ? MAX_REFRESH : 0)
    expect(saves(w)).toBe(interactive ? 1 : 0)
  })
}

/** 整理是否讓位依實際能否自動交接：非互動或暫停時照樣每 N 則整理，自動交接開啟時讓給交接 */
for (const mode of ['on', 'noninteractive', 'paused'] as const) {
  test(`達門檻的回合結束：自動交接 ${mode} 時${mode === 'on' ? '不' : '照樣'}做每 ${DISTILL_EVERY} 則整理`, async ($, on) => {
    // STEP 01: 準備：已達整理則數、超過門檻；則數用變數，暫停前的交接前整理會記下目前則數，之後要再累積一輪才會到期
    /** 目前的使用者訊息數 */
    let turns = DISTILL_EVERY
    const w = world(on, OVER, WINDOW, {}, [], () => turns)
    await boot($, mode !== 'noninteractive')
    // STEP 01.01: 暫停：先連續失敗到上限
    if (mode === 'paused') {
      for (let i = 0; i < MAX_SAVE_FAILURES; i++) {
        await reachThreshold($, w)
        await runSave($, w, { write: false })
        await w.clock.advance(RETRY_WAIT)
      }
      turns += DISTILL_EVERY
    }
    /** 回合結束前已發出的整理請求數 */
    const before = w.completes.length
    // STEP 02: 回合結束
    await complete($)
    await w.clock.advance(0)
    expect(w.completes.length - before).toBe(mode === 'on' ? 0 : 1)
  })
}

/** auto_handoff 關閉：互動 session 也不自動交接 */
test('auto_handoff 關閉：互動 session 達門檻也不跑存檔回合；/handoff-status 顯示 off', async ($, on) => {
  // STEP 01: 設定關閉後達門檻
  const w = world(on, OVER, WINDOW, { distill: false })
  ctl.pluginOptions = { auto_handoff: false }
  await startSession($)
  await reachThreshold($, w)
  // STEP 02: 沒有存檔 prompt
  expect(w.submits).toEqual([])
  expect((await legacy($, 'handoff-status')).text).toContain('自動交接：off（設定 auto_handoff 關閉）')
})

/** 連續失敗達上限：暫停門檻交接，手動仍可，成功後恢復 */
test('連續驗證失敗達上限：暫停門檻自動交接；/handoff-now yes 仍可手動，成功後恢復', async ($, on) => {
  // STEP 01: 連續失敗到上限
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  expect((await legacy($, 'handoff-status')).text).toContain('自動交接：on')
  for (let i = 0; i < MAX_SAVE_FAILURES; i++) {
    await reachThreshold($, w)
    await runSave($, w, { write: false })
    await w.clock.advance(RETRY_WAIT)
  }
  expect(saves(w)).toBe(MAX_SAVE_FAILURES)
  // STEP 02: 再停下：暫停，不再插入存檔回合
  await reachThreshold($, w)
  expect(saves(w)).toBe(MAX_SAVE_FAILURES)
  expect((await legacy($, 'handoff-status')).text).toContain(`暫停（連續 ${MAX_SAVE_FAILURES} 次失敗）`)
  // STEP 03: 手動交接成功後恢復
  await legacy($, 'handoff-now', 'yes')
  await w.clock.advance(0)
  await runSave($, w)
  expect(w.commands).toEqual(['clear'])
  expect((await legacy($, 'handoff-status')).text).toContain('自動交接：on')
})

/** 存檔 prompt 被下層攔下：結束交接並告知 */
test('存檔 prompt 被攔下（drop）：結束交接並告知，之後能再觸發', async ($, on) => {
  // STEP 01: 存檔 prompt 送不出去
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  ctl.failSubmits = 1
  await reachThreshold($, w)
  await w.clock.settle()
  expect(w.commands).toEqual([])
  expect(w.toasts.some(s => s.includes('存檔 prompt 送出失敗'))).toBe(true)
  // STEP 02: 交接已結束：訊息不再被攔，重試間隔後能再觸發
  await say($, '一般訊息')
  expect(w.submits.at(-1)).toBe('一般訊息')
  await w.clock.advance(RETRY_WAIT)
  await reachThreshold($, w)
  expect(saves(w)).toBe(1)
})

/** /clear 後讀檔 prompt 被攔下：留下 pendingSubmit 可重送 */
test('/clear 後讀檔 prompt 被攔下（drop）：toast 告知，留下 pendingSubmit 可 /handoff resend', async ($, on) => {
  // STEP 01: 讀檔 prompt 送不出去
  const w = world(on, OVER, WINDOW, { distill: false })
  await startSession($)
  await reachThreshold($, w)
  ctl.failSubmits = 1
  await runSave($, w)
  expect(w.commands).toEqual(['clear'])
  expect(w.toasts.some(s => s.includes('/handoff resend'))).toBe(true)
  expect(w.get('pendingSubmit:S1') as string).toContain(HANDOFF_FILE)
  // STEP 02: 重送
  await cmd($, 'resend')
  await w.clock.settle()
  expect(w.submits.at(-1)).toContain(HANDOFF_FILE)
})

/** /handoff-now：要打 yes；非互動 session 也能手動 */
test('/handoff-now：沒打 yes 不動作；打 yes 走完存檔 → /clear（非互動 session 也可手動）', async ($, on) => {
  // STEP 01: 沒打 yes
  const w = world(on, UNDER, WINDOW, { distill: false })
  await boot($, false)
  expect((await legacy($, 'handoff-now')).text).toContain('/handoff-now yes')
  await w.clock.advance(0)
  expect(w.submits).toEqual([])
  // STEP 02: 打 yes
  await legacy($, 'handoff-now', 'yes')
  await w.clock.advance(0)
  expect(w.submits[0]).toContain(MARK)
  expect(w.submits[0]).toContain('/handoff now')
  await runSave($, w)
  expect(w.commands).toEqual(['clear'])
  expect(w.submits[1]).toContain(HANDOFF_FILE)
  expect((w.get('handoffs:C--proj') as { kind: string }[]).at(-1)?.kind).toBe('manual')
})

/** /handoff now 也走 save-progress */
test('/handoff now 也走 save-progress（不 fork 摘要）', async ($, on) => {
  // STEP 01: 手動交接
  const w = world(on, UNDER, WINDOW, { distill: false })
  await cmd($, 'now')
  await w.clock.advance(0)
  expect(w.submits[0]).toContain(MARK)
  // STEP 02: 存檔回合後 /clear，沒有 fork
  await runSave($, w)
  expect(w.commands).toEqual(['clear'])
  expect(w.forks.length).toBe(0)
})

/** 離席：刷新用完後跑 save-progress，只存不 /clear；resume 讀檔開新對話 */
test('離席：刷新 3 次後跑 save-progress 存離席交接（不 fork 摘要、不 /clear）；回來的訊息攔下，/handoff-resume 讀檔接續', async ($, on) => {
  // STEP 01: 閒置到刷新用完
  const w = world(on, UNDER)
  await startSession($)
  await complete($)
  await w.clock.advance((MAX_REFRESH + 1) * IDLE)
  expect(w.forks).toEqual(Array(MAX_REFRESH).fill('只回覆 OK'))
  expect(saves(w)).toBe(1)
  expect(w.submits[0]).toContain('離席')
  // STEP 02: 存檔回合完成：只存離席紀錄，不 /clear
  await runSave($, w)
  expect(w.commands).toEqual([])
  expect(w.get('away:S1')).toEqual({ file: HANDOFF_FILE })
  expect((w.get('handoffs:C--proj') as { kind: string; file: string }[]).at(-1)).toMatchObject({ kind: 'away', file: HANDOFF_FILE })
  // STEP 03: 使用者回來，第一則被攔下
  /** 回來的第一則訊息的送出結果 */
  const r = await say($, '我回來了')
  expect((r as { drop?: string }).drop).toBeDefined()
  // STEP 04: 舊指令 /handoff-resume：/clear 後讀檔並帶上攔下的訊息
  await legacy($, 'handoff-resume')
  await w.clock.advance(0)
  expect(w.commands).toEqual(['clear'])
  expect(w.submits.at(-1)).toContain(HANDOFF_FILE)
  expect(w.submits.at(-1)).toContain('我回來了')
  expect(w.submits.at(-1)).not.toContain('undefined')
})

/** 離席存檔失敗：不留離席紀錄 */
test('離席存檔回合的交接紀錄是空的：不存離席紀錄', async ($, on) => {
  // STEP 01: 閒置到離席存檔
  const w = world(on, UNDER)
  await startSession($)
  await complete($)
  await w.clock.advance((MAX_REFRESH + 1) * IDLE)
  // STEP 02: 交接紀錄是空的
  await runSave($, w, { content: '' })
  expect(w.get('away:S1')).toBeUndefined()
  expect(w.toasts.some(s => s.includes('交接紀錄是空的'))).toBe(true)
})

/** 舊格式離席紀錄（上游 fork 摘要）：resume 不送出 undefined，紀錄被捨棄 */
test('舊格式離席紀錄 { handoff }：/handoff resume 回沒有離席紀錄，不 /clear、不送出 undefined，紀錄刪掉', async ($, on) => {
  // STEP 01: store 裡有舊格式
  const w = world(on, UNDER, WINDOW, { 'away:S1': OLD_AWAY })
  /** resume 的回覆 */
  const r = await legacy($, 'handoff-resume')
  await w.clock.advance(0)
  // STEP 02: 當成沒有
  expect(r.text).toContain('沒有離席')
  expect(w.commands).toEqual([])
  expect(w.submits).toEqual([])
  expect(w.get('away:S1')).toBeUndefined()
})

/** 各種格式不符的離席紀錄：resume 與 continue 都當成沒有，不 /clear、不送出 undefined，紀錄刪掉 */
for (const [name, bad] of [
  ['file 是空字串', { file: '' }],
  ['file 只有空白', { file: '  ' }],
  ['file 不是字串', { file: 5 }],
  ['沒有 file 只有 held', { held: '我回來了' }],
  ['held 不是字串', { file: HANDOFF_FILE, held: 5 }],
  ['純字串', 'HANDOFF: 舊摘要'],
  ['陣列', ['x']],
  ['null', null],
] as const) {
  test(`離席紀錄格式不符（${name}）：/handoff-resume 與 /handoff-continue 都當成沒有，不送出 undefined`, async ($, on) => {
    // STEP 01: store 裡是壞格式；resume
    const w = world(on, UNDER, WINDOW, { 'away:S1': bad })
    /** resume 的回覆 */
    const r = await legacy($, 'handoff-resume')
    await w.clock.advance(0)
    expect(r.text).toContain('沒有離席')
    expect(w.commands).toEqual([])
    expect(w.submits).toEqual([])
    expect(w.get('away:S1')).toBeUndefined()
    // STEP 02: 再放回壞格式；continue 也不送出任何東西
    w.put('away:S1', bad)
    /** continue 的回覆 */
    const c = await legacy($, 'handoff-continue')
    await w.clock.advance(0)
    expect(c.text).toContain('沒有離席')
    expect(w.submits).toEqual([])
    expect(w.get('away:S1')).toBeUndefined()
  })
}

/** 舊格式紀錄裡有使用者被攔下的訊息：捨棄紀錄時把訊息文字告知，不無聲消失 */
test('舊格式離席紀錄帶著被攔下的訊息：捨棄時 toast 與 log 印出訊息文字', async ($, on) => {
  // STEP 01: 舊格式 { handoff, held }
  const w = world(on, UNDER, WINDOW, { 'away:S1': { ...OLD_AWAY, held: '舊的攔下訊息' } })
  await legacy($, 'handoff-resume')
  await w.clock.advance(0)
  // STEP 02: 不 /clear、不送出；訊息文字出現在 toast 與 log
  expect(w.commands).toEqual([])
  expect(w.submits).toEqual([])
  expect(w.toasts.some(s => s.includes('舊的攔下訊息'))).toBe(true)
  expect(w.logs.some(s => s.includes('舊的攔下訊息'))).toBe(true)
})

/** 離席存檔回合只認發起嘗試的 session */
test('離席：存檔 prompt 送出後 session 換了，那個回合不被認出；10 分鐘後結束等待，不存離席紀錄', async ($, on) => {
  // STEP 01: 閒置到離席存檔 prompt 送出
  const w = world(on, UNDER)
  await startSession($)
  await complete($)
  await w.clock.advance((MAX_REFRESH + 1) * IDLE)
  expect(saves(w)).toBe(1)
  // STEP 02: 別的 session 帶同一份 prompt 跑起來：不被認出
  ctl.curSid = 'S9'
  w.files.set(HANDOFF_FILE, '# 交接紀錄')
  await $.turn.start({ text: w.submits[0] ?? '', turnId: 'x' })
  await complete($, 'x')
  await w.clock.settle()
  expect(w.get('away:S1')).toBeUndefined()
  // STEP 03: 一直等不到自己的回合：到期結束等待、記原因，仍沒有離席紀錄、沒有 /clear
  await w.clock.advance(SAVE_LOST_MS)
  await w.clock.settle()
  expect((w.get('handoff:error:C--proj') as { kind: string; reason: string }).kind).toBe('away')
  expect((w.get('handoff:error:C--proj') as { reason: string }).reason).toContain('未被辨識')
  expect(w.get('away:S1')).toBeUndefined()
  expect(w.commands).toEqual([])
})

/** 離席存檔每次嘗試都有獨立識別碼：第一次逾時後，它的 prompt 晚到不被第二次嘗試認出 */
test('離席：舊嘗試的存檔 prompt 晚到，第二次離席嘗試不認它，只認自己的', async ($, on) => {
  // STEP 01: 第一次離席嘗試沒被認出，逾時
  const w = world(on, UNDER)
  await startSession($)
  await complete($)
  await w.clock.advance((MAX_REFRESH + 1) * IDLE)
  /** 第一次嘗試的存檔 prompt */
  const first = w.submits[0] ?? ''
  await w.clock.advance(SAVE_LOST_MS)
  await w.clock.settle()
  expect(w.get('away:S1')).toBeUndefined()
  // STEP 02: 主對話又完成一個回合，閒置計時重排，到期後第二次離席嘗試
  await complete($, 't2')
  await w.clock.advance(IDLE)
  expect(saves(w)).toBe(2)
  expect(w.submits.at(-1)).not.toBe(first)
  // STEP 03: 第一次的 prompt 這時才跑起來：不被認出，結束也不存離席紀錄
  w.files.set(HANDOFF_FILE, '# 交接紀錄')
  await $.turn.start({ text: first, turnId: 'late' })
  await complete($, 'late')
  await w.clock.settle()
  expect(w.get('away:S1')).toBeUndefined()
  // STEP 04: 第二次自己的回合照常完成：存下離席紀錄，不 /clear
  await runSave($, w)
  expect(w.get('away:S1')).toEqual({ file: HANDOFF_FILE })
  expect(w.commands).toEqual([])
})

/** 舊指令 /handoff-continue、/handoff-refresh */
test('舊指令 /handoff-continue 送出攔下的訊息；/handoff-refresh off 關掉刷新', async ($, on) => {
  // STEP 01: continue
  const w = world(on, UNDER, WINDOW, { 'away:S1': { file: HANDOFF_FILE, held: '我回來了' } })
  await legacy($, 'handoff-continue')
  await w.clock.advance(0)
  expect(w.submits).toEqual(['我回來了'])
  expect(w.get('away:S1')).toBeUndefined()
  // STEP 02: refresh
  await legacy($, 'handoff-refresh', 'off')
  expect(w.get('refresh')).toBe(false)
})

/** continue 送出被攔下（drop）：離席紀錄不能先被刪掉，被攔下的訊息要能再 continue 一次 */
test('舊指令 /handoff-continue 送出被攔下：離席紀錄留著，再 continue 一次才送出並刪除', async ($, on) => {
  // STEP 01: 第一次送出被別的 hook drop：紀錄與訊息都還在
  const w = world(on, UNDER, WINDOW, { 'away:S1': { file: HANDOFF_FILE, held: '我回來了' } })
  ctl.failSubmits = 1
  await legacy($, 'handoff-continue')
  await w.clock.advance(0)
  expect(w.get('away:S1')).toEqual({ file: HANDOFF_FILE, held: '我回來了' })
  // STEP 02: 再 continue：這次送出成功，紀錄才刪掉
  await legacy($, 'handoff-continue')
  await w.clock.advance(0)
  expect(w.submits).toEqual(['我回來了'])
  expect(w.get('away:S1')).toBeUndefined()
})

/** 舊指令名都有註冊 */
test('舊指令名 /handoff-now、/handoff-status、/handoff-resume、/handoff-continue、/handoff-refresh 有註冊', async ($, on) => {
  // STEP 01: 啟動後檢查註冊清單
  world(on, UNDER)
  await startSession($)
  for (const name of ['handoff-now', 'handoff-status', 'handoff-resume', 'handoff-continue', 'handoff-refresh']) {
    expect(ctl.registered).toContain(name)
  }
})
