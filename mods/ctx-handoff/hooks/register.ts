import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer, TurnCompleteInput } from 'claude-code'
import type { PanelData, PanelSetting, PanelUi } from '../types'
import { panelTree, showSetting } from './panel'
import type { PanelActions } from './panel'
import { getLang, pickLang, setLang, t } from './i18n'
import type { Lang } from './i18n'
import { addRejected, applyActions, distillPrompt, guardAnswers, guardPromotions, latestProgress, looksSecret, parseActions, squash } from './distill'
import type { Action, Rejected } from './distill'
import { progressForPrompt, progressKey, progressOffer, withOffered } from './progress'
import type { Progress, ProgressFields } from './progress'
import { GUARD_ASK_ITEMS, GUARD_MIN_COUNT, applyGuardChange, guardAskText, guardCandidatesOf, guardChangeOf, guardHitKey, guardHits, guardListText, guardPrompt, guardSummaryText, inputText, parseGuards, withHits, withProposals } from './guards'
import type { Guard, GuardMode } from './guards'
import { NOTE_TAG, PROJECT_DECLINED, PROJECT_IN, contextText, localStamp, memHead, noteBlock, parseNotes, renderNotes, tag } from './notes'
import type { Notes, Rule } from './notes'
import { encodeProject, isAbs, resolveDots, slash } from './paths'
import { anchorOf, transcriptOf } from './transcript'
import type { Row } from './transcript'
import { DISTILL_EFFORT, DISTILL_MAX_TOKENS, DISTILL_TIMEOUT_MS, GUARD_MAX_TOKENS, HANDOFF_TIMEOUT_MS, KEEP, DEFER_CAP_EXTRA, DEFER_CAP_RATIO, RELOAD_GRACE_MS, RETRY_MS, RETRY_TURNS, STOPPED, cfg, optionsOf, resetConfig, resolveConfig, settingSource, settingValue, specOf, stepSetting, thresholdOf } from './config'
import { resetRuntime, rt } from './runtime'
import { doneCheck, freshWork, noteCall, trackFailure } from './loops'
import { clearNext, noteStep, peekNext, resolveReplyLang, takePending } from './lang'
import { addStat, awayKey, describeUsage, pendingKey, pruneSeen, statsKey } from './records'
import type { Away, DistillError, DistillLast, HandoffError, Kind, Saved, Stats, Usage } from './records'
import { HANDOFF_PROMPT, forkFailure, heldBlock } from './handoff'
import { buryMissing, isBuried, memTitles, tombKey } from './tombstones'
import type { Tombstones } from './tombstones'
import { guardsFoundInRepo, markAsked, promoteCandidates, promoteItems, promoteText, releaseAsked } from './promote'
import type { PromoteAsk } from './promote'
import { backupPath, keepMemory, panelSnapshot, withoutNote } from './panel-data'
import { distillStatusText, statusText, usageText } from './status'
import { MS_PER_MIN, SAVE_LOST_MS, SAVE_MARK, attemptTag, isPausedBy, parseAway, parseFile, savePrompt, strandedHeld } from './save'
import type { SaveKind } from './save'

// 讀本 plugin 的設定：面板存在 store 的 settings 優先，其次 settings.json 的 pluginConfigs["ctx-handoff@<marketplace>"].options
async function readSettings($: EngineInterface) {
  let options: Record<string, unknown> = {}
  try {
    options = optionsOf((await $.settings.read()).pluginConfigs as Record<string, { options?: Record<string, unknown> }> | undefined)
  } catch {}
  const panel = ((await $.store.get('settings')) as Record<string, unknown> | undefined) ?? {}
  return { options, panel }
}

async function loadConfig($: EngineInterface) {
  const { options, panel } = await readSettings($)
  Object.assign(cfg, resolveConfig(options, panel))
}

// 重讀設定（送出新訊息、面板改值）：別的 session 在面板改的值也在這時生效；語言、閒置計時、回覆語言跟著換
async function reloadConfig($: EngineInterface) {
  const before = { ...cfg }
  await loadConfig($)
  if (cfg.replyLanguage !== before.replyLanguage) rt.replyTarget = undefined
  if (cfg.language !== before.language) {
    rt.langReady = undefined
    await initLang($)
  }
  if (cfg.idleMs !== before.idleMs && rt.idle !== undefined) await schedule($)
  if (cfg.minTokens !== before.minTokens || cfg.distillEvery !== before.distillEvery) await showDistillStatus($)
}

async function isRefreshOn($: EngineInterface) {
  return (await $.store.get('refresh')) !== false
}

// 最多等 ms：逾時回 fallback（原本的 promise 照樣跑完，只是不再等它）
async function within<T, F>($: EngineInterface, p: Promise<T>, ms: number, fallback: F): Promise<T | F> {
  let timer: Timer | undefined
  const late = new Promise<F>(resolve => { timer = $.clock.after(ms, () => resolve(fallback)) })
  try {
    return await Promise.race([p, late])
  } finally {
    timer?.cancel()
  }
}

type ForkResult = Awaited<ReturnType<EngineInterface['model']['fork']>>
type ForkOutcome = ForkResult | { isAnswered: false; reason: 'timeout' }
const forkWithin = ($: EngineInterface, prompt: string, ms: number): Promise<ForkOutcome> =>
  within($, $.model.fork({ prompt }), ms, { isAnswered: false as const, reason: 'timeout' as const })

// 工作區鍵：經驗檔所在目錄的名稱（<claude>/projects/<這一層>/memory/ctx-handoff.md）
async function projectKey($: EngineInterface) {
  const file = await notesFile($)
  return file?.split('/').at(-3) ?? 'unknown'
}

// 每個 session 一把的鍵第一次出現的時間，給清理用；已記錄過的不再重寫
async function touchSeen($: EngineInterface, key: string) {
  if (rt.seenKnown.has(key)) return
  rt.seenKnown.add(key)
  const seen = ((await $.store.get('seen')) as Record<string, number> | undefined) ?? {}
  if (seen[key] === undefined) await $.store.set('seen', { ...seen, [key]: await $.clock.now() })
}

// 累計統計（北極星的量測用）：記帳失敗不影響原本的流程；疑似金鑰的內容不記
// 同一個 process 的寫入排隊：讀改寫同時進行時後寫的會蓋掉先寫的（交接與交接前整理並行）
async function stat($: EngineInterface, what: string, n = 1, event?: { failure?: string; hit?: string }) {
  const run = rt.statQueue.then(() => writeStat($, what, n, event))
  rt.statQueue = run
  await run
}

async function writeStat($: EngineInterface, what: string, n: number, event?: { failure?: string; hit?: string }) {
  try {
    const clean = (s: string | undefined) => (s !== undefined && looksSecret(s) ? t().reject.secret : s)
    const key = statsKey(await projectKey($))
    const prev = (await $.store.get(key)) as Stats | undefined
    await $.store.set(key, addStat(prev, await $.clock.now(), what, n, { failure: clean(event?.failure), hit: clean(event?.hit) }))
  } catch { /* 只是記帳 */ }
}

// 失敗寫進 store 讓 /handoff 看得到；在場交接失敗還要擋一陣子才重試
async function recordFailure($: EngineInterface, kind: Kind, tokens: number | null, reason: string, sid?: string) {
  const at = await $.clock.now()
  const turns = await $.session.turns()
  const err: HandoffError = { at, sessionId: sid ?? await $.session.id(), kind, reason, tokens, turns }
  await $.store.set(`handoff:error:${await projectKey($)}`, err)
  await stat($, `handoff.${kind}.fail`, 1, { failure: reason })
  if (kind === 'present' || kind === 'manual') rt.retryAfter = { turns, at }
}

// 本機改版：fork 摘要只剩 /handoff dry（試產、不 /clear）使用；在場／手動／離席交接改走 saveTurn
async function makeHandoff($: EngineInterface, kind: 'dry', tokens: number | null) {
  const started = await $.clock.now()
  const r = await forkWithin($, HANDOFF_PROMPT, HANDOFF_TIMEOUT_MS)
  if (!r.isAnswered) {
    $.ui.log(t().handoff.failedLog(forkFailure(r.reason)))
    $.ui.toast(t().handoff.failedToast)
    await recordFailure($, kind, tokens, t().handoff.failGenerate(forkFailure(r.reason)))
    return undefined
  }
  const at = await $.clock.now()
  const usage: Usage = {
    input: r.usage.input_tokens,
    cacheRead: r.usage.cache_read_input_tokens,
    cacheCreation: r.usage.cache_creation_input_tokens,
    output: r.usage.output_tokens,
    ms: at - started,
  }
  const saved: Saved = { at, sessionId: await $.session.id(), kind, tokens, text: r.text, usage }
  const handoffsKey = `handoffs:${await projectKey($)}`
  const list = ((await $.store.get(handoffsKey)) as Saved[] | undefined) ?? []
  await $.store.set(handoffsKey, [...list, saved].slice(-KEEP))
  rt.lastHandoff = { text: r.text }
  $.ui.log(t().handoff.savedLog(kind, describeUsage(usage)))
  return r.text
}

/**
 * 本機改版：在場／手動／離席交接的交接內容。送出存檔 prompt，讓真的回合執行 save-progress skill，
 * 等該回合結束（turn.complete）後驗證交接紀錄檔真的寫好；取代 fork 摘要（makeHandoff 只剩 /handoff dry 使用）。
 * @param $ engine 介面
 * @param kind 觸發原因
 * @param tokens 觸發當下的 context token 數；讀不到時為 null
 * @returns 交接紀錄檔的絕對路徑；送出失敗、遺失、回合未正常結束、驗證不過或記錄寫入失敗時為 undefined（已經 saveFailed 記錄並告知）
 * @throws 引擎呼叫（clock／session／store）失敗，或 saveFailed 內 recordFailure 寫 store 失敗時往上拋，由呼叫端的 catch 處理
 */
async function saveTurn($: EngineInterface, kind: SaveKind, tokens: number | null) {
  // STEP 01: 登記這次存檔嘗試：獨立識別碼與發起的 session；turn.start 兩者都對上才記下 turnId
  /** 送出存檔 prompt 前的時間，驗證交接紀錄 mtime 用 */
  const startedAt = await $.clock.now()
  /** 發起這次嘗試的 session id */
  const sessionId = await $.session.id()
  rt.saveSeq += 1
  /** 這次嘗試的識別碼 */
  const attempt = `${startedAt}-${rt.saveSeq}`
  /** 存檔回合的結束：該回合的 turn.complete 輸入；遺失時為 undefined */
  const ended = new Promise<TurnCompleteInput | undefined>(resolve => {
    rt.saving = { kind, attempt, sessionId, startedAt, settle: resolve }
  })
  // STEP 02: 遺失計時：交接期間人類訊息都被攔下，不會有別的回合幫忙檢查，所以用計時器結束等待
  /** 到期仍未認出存檔回合就結束等待的計時器 */
  const lost = $.clock.after(SAVE_LOST_MS, () => {
    // STEP 02.01: 只結束同一次嘗試，且尚未被認出
    if (rt.saving?.attempt === attempt && rt.saving.turnId === undefined) {
      rt.saving.settle(undefined)
    }
  })
  try {
    // STEP 03: 送出存檔 prompt；被攔下（drop）或丟例外就不等
    try {
      await submitText($, savePrompt(kind, tokens, attempt))
    } catch (err) {
      return await saveFailed($, kind, tokens, t().save.submitFailed(String(err)))
    }
    // STEP 04: 等存檔回合結束，驗證回覆與交接紀錄
    /** 存檔回合的 turn.complete 輸入；遺失時為 undefined */
    const e = await ended
    /** 驗證結果：成功帶交接紀錄路徑，失敗帶原因 */
    const verdict = e === undefined ? { reason: t().save.lost(SAVE_LOST_MS / MS_PER_MIN) } : await verifySave($, e, startedAt)
    if ('reason' in verdict) {
      return await saveFailed($, kind, tokens, verdict.reason)
    }
    // STEP 05: 記錄這次交接（/handoff 狀態的「最近一份」）；寫不進 store 也走失敗出口，不 /clear
    try {
      /** 交接紀錄清單在 store 的鍵（依工作區） */
      const handoffsKey = `handoffs:${await projectKey($)}`
      /** 既有的交接紀錄清單 */
      const list = ((await $.store.get(handoffsKey)) as Saved[] | undefined) ?? []
      /** 這次交接的紀錄：交接內容是檔案，不是摘要文字 */
      const saved: Saved = { at: await $.clock.now(), sessionId, kind, tokens, file: verdict.file }
      await $.store.set(handoffsKey, [...list, saved].slice(-KEEP))
    } catch (err) {
      return await saveFailed($, kind, tokens, t().save.recordFailed(String(err)))
    }
    rt.saveFailures = 0
    return verdict.file
  } finally {
    lost.cancel()
    rt.saving = undefined
  }
}

/**
 * 本機改版：存檔回合結束後驗證交接紀錄。任何一項不符都不 /clear，避免清掉對話卻沒有交接紀錄。
 * @param $ engine 介面
 * @param e 存檔回合的 turn.complete 輸入
 * @param startedAt 送出存檔 prompt 前的時間（交接紀錄的 mtime 要不早於它）
 * @returns 成功時 { file }，失敗時 { reason }
 */
async function verifySave($: EngineInterface, e: TurnCompleteInput, startedAt: number): Promise<{ file: string } | { reason: string }> {
  // STEP 01: 回合要正常結束，且回覆最後回報了絕對路徑
  if (e.reason !== 'answer') {
    return { reason: t().save.notAnswered(e.reason) }
  }
  /** model 回報的交接紀錄絕對路徑 */
  const file = parseFile(e.answer)
  if (file === undefined) {
    return { reason: t().save.noFile }
  }
  // STEP 02: 檔案要存在，且是這個存檔回合開始後才寫的
  /** 交接紀錄檔的狀態；不存在或讀不到時為 undefined */
  const stat = await $.fs.stat(file).catch(() => undefined)
  if (stat === undefined || stat.kind !== 'file' || stat.mtimeMs < startedAt) {
    return { reason: t().save.notWritten(file) }
  }
  // STEP 03: 內容不能是空的；讀不到就失敗，不用空字串頂替
  /** 讀檔結果：成功帶內容，失敗帶原因 */
  const read = await $.fs.read(file).then(text => ({ text }), (err: unknown) => ({ err: String(err) }))
  if ('err' in read) {
    return { reason: t().save.unreadable(file, read.err) }
  }
  if (read.text.trim() === '') {
    return { reason: t().save.empty(file) }
  }
  return { file }
}

/**
 * 本機改版：存檔交接失敗的共同出口：累計連續失敗（達上限暫停門檻自動交接），log + toast，
 * 並走上游的 recordFailure（/handoff 狀態、統計、短期不重試）。
 * @param $ engine 介面
 * @param kind 觸發原因
 * @param tokens 觸發當下的 context token 數；讀不到時為 null
 * @param why 失敗原因
 * @returns 一律 undefined（給 saveTurn 直接 return）
 * @throws recordFailure 寫 store 失敗時往上拋
 */
async function saveFailed($: EngineInterface, kind: SaveKind, tokens: number | null, why: string) {
  // STEP 01: 累計連續失敗；達上限時附上暫停說明
  rt.saveFailures += 1
  /** 達失敗上限時附加的暫停說明 */
  const paused = isPausedBy(rt.saveFailures) ? t().save.paused(rt.saveFailures) : ''
  // STEP 02: 告知並記錄
  $.ui.log(t().save.cancelled(`${why}${paused}`))
  $.ui.toast(t().save.cancelled(`${why}${paused}`))
  await recordFailure($, kind, tokens, why)
  return undefined
}

// $.prompt.submit 被別的 hook 丟棄時只回 { drop }、不會丟例外：沒送進對話，當成失敗
async function submitText($: EngineInterface, text: string) {
  const r = await $.prompt.submit({ text })
  if (r.drop !== undefined) throw new Error(t().handoff.dropped(r.drop))
}

// /clear → 把完整文字送進新對話。送出前先存成 pendingSubmit:<舊 session id>，成功才刪；
// 失敗時回傳階段與原因（clear 失敗＝還在舊對話，pending 已刪；submit 失敗＝pending 留著給 /handoff resend）
async function clearAndSubmit($: EngineInterface, text: string) {
  const sid = await $.session.id()
  const key = pendingKey(sid)
  await $.store.set(key, text)
  await touchSeen($, key)
  rt.myPending = { sid }
  rt.pendingToasted = false
  // 新對話第一則訊息（就是這份 handoff）開頭不要再提供同一段的進度備忘：先標記，/clear 失敗再還原
  await markHanded($, sid, true)
  try {
    await $.command.run({ command: 'clear' })
  } catch (err) {
    await $.store.delete(key)
    rt.myPending = undefined
    await markHanded($, sid, false)
    return { stage: 'clear', reason: String(err) }
  }
  try {
    await submitText($, text)
  } catch (err) {
    return { stage: 'submit', reason: String(err) }
  }
  await $.store.delete(key)
  rt.myPending = undefined
  return undefined
}

// ---------- 背景整理：位置與流程 ----------

async function claudeDir($: EngineInterface) {
  const custom = await $.env.get('CLAUDE_CONFIG_DIR')
  if (custom) return slash(custom)
  const home = (await $.env.get('USERPROFILE')) ?? (await $.env.get('HOME')) ?? ''
  return `${slash(home)}/.claude`
}

async function readText($: EngineInterface, path: string) {
  try { return await $.fs.read(path) } catch { return '' }
}

// 嚴格讀取：只有檔案不存在才當空字串；存在卻讀不出來就丟出錯誤。
// distill 用「寫前再讀一次、與整理前相同才寫」防止覆蓋別人的修改；兩次讀取都失敗若都變成空字串會被判成「沒變更」，
// 接著用新內容覆蓋整份舊記憶（codex review 重現）
async function readTextStrict($: EngineInterface, path: string) {
  if (!(await $.fs.exists(path))) return ''
  return await $.fs.read(path)
}

// 工作區：session 啟動的資料夾；從 git worktree 啟動時算主工作樹（.git 是檔案：gitdir: <主工作樹>/.git/worktrees/<名稱>）。
// 不用 $.session.repo()：它依目前工作目錄判斷，會跟著 Bash 的 cd 變
async function workspace($: EngineInterface) {
  const root = slash(await $.session.root())
  const m = /^gitdir:\s*(.+?)\/\.git\/worktrees\/[^/]+\s*$/m.exec(slash(await readText($, `${root}/.git`)))
  if (!m?.[1]) return root
  const main = slash(m[1])
  return isAbs(main) ? main : resolveDots(`${root}/${main}`)
}

// 經驗檔：<claude>/projects/<編碼後的工作區路徑>/memory/ctx-handoff.md；每個工作區只有這一份。
// 不寫 MEMORY.md：那是內建 auto memory 的索引，開啟 auto memory 時會被載入兩次、也會被它改寫
async function notesFile($: EngineInterface) {
  return `${await claudeDir($)}/projects/${encodeProject(await workspace($))}/memory/ctx-handoff.md`
}

// 整理看得到的既有指引：工作區與使用者的 CLAUDE.md。新對話本來就會讀到，整理才知道哪些不用再記
// （2026-10-09 評估：沒給它看時，常把 CLAUDE.md 已有的事又記一次）
async function guidesText($: EngineInterface) {
  const parts: string[] = []
  for (const [label, path] of [['工作區', `${await workspace($)}/CLAUDE.md`], ['使用者', `${await claudeDir($)}/CLAUDE.md`]] as const) {
    const text = (await readText($, path)).trim()
    if (text) parts.push(`--- ${label}：${path} ---\n${text}`)
  }
  return parts.join('\n\n')
}

async function isDistillOn($: EngineInterface) {
  return (await $.store.get('distill')) !== false
}

// 整理要用的這段對話：交接時在 /clear 之前讀好，之後才整理也不受影響（/clear 後 session id 與訊息都換了）
type DistillSnap = { sid: string; turns: number; anchor: string | undefined; rows: readonly Row[] }
async function distillSnap($: EngineInterface): Promise<DistillSnap> {
  const sid = await $.session.id()
  return {
    sid,
    turns: await $.session.turns(),
    anchor: (await $.store.get(`last:${sid}`)) as string | undefined,
    rows: (await $.session.messages()) as readonly Row[],
  }
}

// 整理上次之後新增的對話：先讀好對話片段（之後 /clear 也不影響），再交給設定的整理模型
// queue=false：交接前整理，之後會 /clear，不排入差異
// 一次只跑一個整理；已有整理在跑時，帶 snap 的（交接前整理）排在它之後，其他的直接略過（正在跑的那次會涵蓋）
async function distill($: EngineInterface, why: string, queue = true, snap?: DistillSnap) {
  if (rt.distilling) {
    if (snap === undefined) return undefined
    $.ui.log(t().distill.waiting(why))
    while (rt.distilling) await rt.distillDone
  }
  const sid = snap?.sid ?? await $.session.id()
  const key = `distill:${sid}`
  const prev = (await $.store.get(key)) as { turn: number; anchor?: string } | undefined
  const turns = snap?.turns ?? await $.session.turns()
  if (turns <= (prev?.turn ?? 0)) return undefined
  // 讀 store 的空檔可能有別的整理先開始
  if (rt.distilling) return undefined
  rt.distilling = true
  let done = () => {}
  rt.distillDone = new Promise<void>(r => { done = r })
  rt.distillFailed = false
  await showDistillStatus($, why)
  const fail = async (reason: string) => {
    rt.distillFailed = true
    $.ui.log(t().distill.failLog(why, reason))
    await $.store.set(`distill:error:${await projectKey($)}`, { at: await $.clock.now(), why, reason })
    await stat($, 'distill.fail', 1, { failure: `${why}: ${reason}` })
  }
  try {
    // 這次整理到使用者最後一則訊息為止；下次從它之後開始
    const anchor = snap ? snap.anchor : (await $.store.get(`last:${sid}`)) as string | undefined
    const rows = snap?.rows ?? (await $.session.messages()) as readonly Row[]
    const transcript = transcriptOf(rows, prev?.anchor)
    // quote 的比對對象：使用者自己送出的訊息（本程式注入的經驗與 handoff 不算）
    const userText = squash(rows.filter(r => r.role === 'user' && !r.text.startsWith(NOTE_TAG) && !r.text.startsWith(tag)).map(r => r.text).join('\n'))
    const file = await notesFile($)
    const original = await readTextStrict($, file)
    const notes = parseNotes(original)
    // 上次整理之後被刪掉的記憶留墓碑（面板、tools/notes.mjs、直接改檔都算），這次不讓整理加回
    const tk = tombKey(await projectKey($))
    const tombs = buryMissing((await $.store.get(tk)) as Tombstones | undefined, memTitles(notes), await $.clock.now())
    await $.store.set(tk, tombs)
    // 還沒放進 repo 的規則、流程與守門：整理從對話認出放好了就記上
    const candidates = promoteCandidates(await loadGuards($), notes)
    // 守門草稿：整理從對話認出使用者要不要採用
    const drafts = (await loadGuards($)).filter(g => g.state === 'proposed').map(g => ({ id: `G${g.id}`, name: g.rule }))
    const started = await $.clock.now()
    const r = await $.model.complete({
      model: cfg.notesModel,
      effort: DISTILL_EFFORT,
      maxTokens: DISTILL_MAX_TOKENS,
      timeoutMs: DISTILL_TIMEOUT_MS,
      system: distillPrompt(transcript.found ? prev?.anchor : undefined, notes, localStamp(started).slice(0, 10), progressForPrompt(await loadProgress($), started), candidates, await guidesText($), drafts, tombs.dead.map(d => d.title)),
      prompt: `=== 對話紀錄 ===\n${transcript.text || '（沒有新的對話內容）'}\n=== 對話紀錄結束 ===\n\n依系統指示輸出 ACTIONS。`,
    })
    if (!r.isAnswered) {
      const reason = r.reason === 'api-error' ? `api-error ${r.status ?? ''} ${r.error}`.replace(/\s+/g, ' ')
        : r.reason === 'aborted' ? t().distill.timeout(DISTILL_TIMEOUT_MS / 60_000) : r.reason
      await fail(reason)
      return r
    }
    const now = await $.clock.now()
    const stamp = localStamp(now)
    const parsed = parseActions(r.text, notes, userText, candidates.map(c => c.id), drafts.map(d => d.id))
    const rejected = parsed.rejected
    const actions = (await checkPromotions($, parsed.actions, rejected)).filter(a => {
      if (a.op !== 'add_memory' || !isBuried(tombs, a.title, a.quote !== undefined)) return true
      addRejected(rejected, t().reject.buried(a.title), JSON.stringify(a))
      return false
    })
    // 整理期間經驗檔被改過：編號對不上，這次不寫也不推進進度，下次重新整理同一段
    if ((await readTextStrict($, file)) !== original) {
      const reason = t().distill.edited(file)
      $.ui.log(t().distill.skipLog(why, reason))
      await $.store.set(`distill:error:${await projectKey($)}`, { at: now, why, reason })
      await stat($, 'distill.fail', 1, { failure: `${why}: ${reason}` })
      rt.distillFailed = true
      return r
    }
    const { notes: updated, changes: noteChanges } = applyActions(actions, notes, stamp.slice(0, 10), sid)
    if (noteChanges.length > 0) {
      await $.fs.write(file, renderNotes(updated, stamp))
      await $.store.set(tk, { ...tombs, known: memTitles(updated) })
    }
    const changes = [...noteChanges, ...await applyPromotions($, actions, candidates, sid, started), ...await applyGuardAnswers($, actions)]
    // 進度備忘（沒有實際進展時模型不輸出，前一份保留）
    const progress = latestProgress(actions)
    if (progress) await saveProgress($, sid, progress, now)
    await $.store.set(key, { turn: turns, at: now, anchor })
    await touchSeen($, key)
    const usage = describeUsage({ input: r.usage.input_tokens, cacheRead: r.usage.cache_read_input_tokens, cacheCreation: r.usage.cache_creation_input_tokens, output: r.usage.output_tokens, ms: now - started })
    await $.store.set(`distill:last:${await projectKey($)}`, { at: now, why, changes, file, usage, rejected } satisfies DistillLast)
    await stat($, 'distill.ok')
    // 寫成文字還擋不住的規則：背景起草守門，下一段新對話請 AI 問使用者（失敗不影響整理）
    await autoDraftGuards($, updated, rows).catch(err => $.ui.log(t().guard.autoFailed(String(err))))
    await refreshPanel($)
    $.ui.log(t().distill.doneLog(why, changes.length, rejected.count, file))
    // 先寫檔再排入；差異跟著下一則真正送進對話的訊息帶入（見 prompt.submit）
    if (changes.length > 0 && queue) {
      rt.pendingNotes.set(sid, { changes: [...(rt.pendingNotes.get(sid)?.changes ?? []), ...changes], file })
      $.ui.log(t().distill.queued(changes.length))
    }
    // 讓使用者看得到：寫了哪份檔案（完整路徑），不送訊息、不花 token
    if (changes.length > 0) {
      $.ui.toast(t().distill.toast(changes.length, queue, file))
    }
    return r
  } catch (err) {
    await fail(t().distill.writeFailed(String(err)))
    return undefined
  } finally {
    rt.distilling = false
    done()
    await showDistillStatus($)
  }
}

// 狀態列：整理中顯示原因，平常顯示距離下次「每 N 則」整理還差幾則；handoff 延後時讓給延後訊息
async function showDistillStatus($: EngineInterface, running?: string) {
  if (rt.deferral) return
  if (!(await isDistillOn($))) return $.ui.status(undefined)
  if (running) return $.ui.status(t().status.running)
  const left = cfg.distillEvery - (await sinceDistill($))
  if (left > 0) return $.ui.status(t().status.left(left))
  $.ui.status(((await $.session.usage()).context.tokens ?? 0) < cfg.minTokens ? t().status.short : t().status.next)
}

// 上次整理之後的使用者訊息數
async function sinceDistill($: EngineInterface) {
  const last = ((await $.store.get(`distill:${await $.session.id()}`)) as { turn: number } | undefined)?.turn ?? 0
  return Math.max(0, (await $.session.turns()) - last)
}

async function distillStatus($: EngineInterface) {
  const on = await isDistillOn($)
  const pk = await projectKey($)
  const d = (await $.store.get(`distill:last:${pk}`)) as DistillLast | undefined
  const err = (await $.store.get(`distill:error:${pk}`)) as DistillError | undefined
  const file = await notesFile($)
  const notes = parseNotes(await readText($, file))
  const today = localStamp(await $.clock.now()).slice(0, 10)
  return distillStatusText({ on, d, err, file, notes, today, since: on ? await sinceDistill($) : 0 })
}

// 到期時間與刷新次數另存 $.state：熱重載會清掉計時器與模組變數，session.start 依它重排
const idleState = atom({ plugin: 'ctx-handoff', key: 'idle' } as const, null)

async function schedule($: EngineInterface, delay = cfg.idleMs) {
  rt.idle?.cancel()
  rt.idle = $.clock.after(delay, () => void onIdle($))
  const due = (await $.clock.now()) + delay
  await update($, idleState, () => ({ due, refreshes: rt.refreshes }))
}

async function resumeSchedule($: EngineInterface) {
  const saved = await read($, idleState)
  // 本機改版：非互動 session 不閒置刷新
  if (!saved || rt.idle || !rt.interactive) {
    return
  }
  const left = saved.due - (await $.clock.now())
  if (left < -RELOAD_GRACE_MS) return
  rt.refreshes = saved.refreshes
  await schedule($, Math.max(0, left))
}

async function onIdle($: EngineInterface) {
  await initLang($)
  rt.idle = undefined
  await update($, idleState, () => null)
  // 本機改版：非互動 session 不閒置刷新、不存離席交接
  if (rt.busy || !rt.interactive) {
    return
  }
  const { context } = await $.session.usage()
  const tokens = context.tokens ?? 0
  if (tokens < cfg.minTokens) return

  if ((await isRefreshOn($)) && rt.refreshes < cfg.maxRefresh) {
    // 刷新用最便宜的 fork（只回 OK）讀一次快取；整理是另一個不帶歷史的請求，有新對話才跑
    const r = await forkWithin($, '只回覆 OK', HANDOFF_TIMEOUT_MS)
    if (await isDistillOn($)) await distill($, t().distill.why.idle)
    rt.refreshes += 1
    $.ui.log(r.isAnswered
      ? t().idle.refresh(rt.refreshes, cfg.maxRefresh, r.usage.cache_read_input_tokens, r.usage.cache_creation_input_tokens)
      : t().idle.refreshFailed(rt.refreshes, cfg.maxRefresh, r.reason))
    await schedule($)
    return
  }

  rt.busy = true
  try {
    if (await isDistillOn($)) await distill($, t().distill.why.away)
    // 本機改版：離席交接也跑 save-progress 存檔回合寫交接紀錄檔（不用 fork 摘要）；只存不 /clear，等使用者回來選
    const file = await saveTurn($, 'away', tokens)
    if (file === undefined) {
      return
    }
    const key = awayKey(await $.session.id())
    await $.store.set(key, { file } satisfies Away)
    await touchSeen($, key)
    $.ui.log(t().idle.awaySavedLog(tokens))
    await stat($, 'handoff.away.ok')
    $.ui.toast(t().idle.awaySavedToast)
  } finally {
    rt.busy = false
  }
}

// 在場交接開始：同步設好旗標，之後的使用者訊息先攔下
function beginPresent() {
  rt.busy = true
  rt.presenting = true
  rt.held = []
  rt.presentStartedAt = undefined
  rt.idle?.cancel()
  rt.idle = undefined
}

async function present($: EngineInterface, tokens: number | null, kind: 'present' | 'manual', note?: string) {
  rt.presentStartedAt = await $.clock.now()
  const sid = await $.session.id()
  // rt.held 已處理到第幾則：之前的已包進送出的文字，或已另外送出
  let delivered = 0
  const drain = async (send: (batch: string, n: number) => Promise<void>) => {
    while (rt.held.length > delivered) {
      const n = rt.held.length - delivered
      const batch = rt.held.slice(delivered).join('\n\n')
      delivered = rt.held.length
      await send(batch, n)
    }
  }
  const resubmit = async (batch: string, n: number) => {
    try { await submitText($, batch) } catch (err) {
      $.ui.log(t().handoff.resubmitFailed(String(err)))
      await stat($, 'held.lost', n, { failure: String(err) })
    }
  }
  try {
    // 存檔回合（本機改版，原為交接 fork）和 /clear 前的最後整理同時進行。整理要的對話片段先讀好，/clear 只等它讀完，
    // 不等整理本身：整理在背景跑完照樣寫檔（它不排入差異），已有整理在跑就排在它之後
    const snap = isDistillOn($).then(on => on ? distillSnap($) : undefined).catch(() => undefined)
    void snap.then(s => s && distill($, t().distill.why.before, false, s)).catch(() => undefined)
    // 本機改版：交接內容改由 save-progress 存檔回合寫成交接紀錄檔（取代 fork 摘要），新對話讀檔。
    // 先等整理的對話片段讀好，存檔回合（save-progress 的對話）才不會被當成要整理的內容
    await snap
    const file = await saveTurn($, kind, tokens)
    if (file === undefined) {
      await drain(resubmit)
      return
    }
    const why = kind === 'manual' ? t().handoff.whyManual : t().handoff.whyTokens(tokens ?? 0)
    const included = [...rt.held]
    delivered = included.length
    rt.lastHandoff = { text: t().save.intro(why, file) }
    const intro = `${tag} ${included.length === 0 ? t().save.intro(why, file) : t().save.introHeld(why, file)}`
    const text = `${intro}${note ? t().handoff.note(note) : ''}${included.length ? `\n\n${heldBlock(included)}` : ''}`
    const failed = await clearAndSubmit($, text)
    if (failed?.stage === 'clear') {
      $.ui.log(t().handoff.clearFailedLog(failed.reason))
      await recordFailure($, kind, tokens, t().handoff.reasonClear(failed.reason), sid)
      delivered = 0
      await drain(resubmit)
    } else if (failed) {
      $.ui.log(t().handoff.submitFailedLog(failed.reason))
      $.ui.toast(t().handoff.submitFailedToast)
      await recordFailure($, kind, tokens, t().handoff.reasonSubmit(failed.reason), sid)
      // 文字建好之後才到的訊息：補進這份 pendingSubmit，重送時一起送
      let pending = text
      await drain(async batch => {
        pending += included.length === 0 && pending === text ? `\n\n${heldBlock([batch])}` : `\n\n${batch}`
        await $.store.set(pendingKey(sid), pending)
      })
    } else {
      rt.retryAfter = undefined
      rt.refreshes = 0
      await stat($, `handoff.${kind}.ok`)
      // 文字建好之後才到的訊息：接在 handoff 那一輪之後送出
      await drain(resubmit)
    }
  } catch (err) {
    $.ui.log(t().handoff.failedAll(String(err)))
    try {
      await recordFailure($, kind, tokens, t().handoff.reasonException(String(err)), sid)
      delivered = 0
      await drain(resubmit)
    } catch (err2) {
      $.ui.log(t().handoff.failedCleanup(String(err2)))
    }
  } finally {
    const held = rt.held.length
    rt.presenting = false
    rt.held = []
    rt.busy = false
    if (held > 0) await stat($, 'held', held)
  }
}

// classic.Stop：每次主對話停下來時判斷要不要交接。快照裡有背景工作與排程，
// 背景工作和一次性排程會再叫醒這個 session，先不 /clear；循環排程不算
async function onStop($: EngineInterface, e: { agent_id?: string; background_tasks?: { status: string }[]; session_crons?: { recurring: boolean }[] }) {
  if (e.agent_id !== undefined) return
  const tasks = (e.background_tasks ?? []).filter(t => !STOPPED.has(t.status)).length
  const crons = e.session_crons ?? []
  const oneShot = crons.filter(c => !c.recurring).length
  rt.snapshot = { tasks, oneShot, recurring: crons.length - oneShot }
  if (rt.busy) return
  // 自動交接關閉：到門檻也不交接，交給 Claude Code 自己的 compact
  // 本機改版：非互動 session（-p／SDK）也一樣，呼叫端在等結果，不插入存檔回合也不 /clear（判斷在 autoState，和整理讓位共用）
  const auto = autoState()
  if (auto === 'off' || auto === 'noninteractive') {
    rt.deferral = undefined
    rt.deferToasted = false
    return
  }
  const { context } = await $.session.usage()
  const tokens = context.tokens
  const threshold = thresholdOf(context.window)
  if (tokens === undefined || tokens < threshold) {
    rt.deferral = undefined
    rt.deferToasted = false
    return
  }
  // 本機改版：存檔交接連續失敗達上限：不再每次停下都插入存檔回合，改由使用者 /handoff now 手動
  if (auto === 'paused') {
    $.ui.status(t().save.pausedStatus(rt.saveFailures))
    return
  }
  const agents = (await $.agent.list()).filter(a => a.status === 'running').length
  const parts = [tasks && t().stop.tasks(tasks), oneShot && t().stop.oneShot(oneShot), agents && t().stop.agents(agents)].filter(Boolean)
  const partsText = parts.join(t().list)
  let note: string | undefined
  if (parts.length > 0) {
    const cap = Math.min(Math.floor(context.window * DEFER_CAP_RATIO), threshold + DEFER_CAP_EXTRA)
    if (tokens < cap) {
      rt.deferral = t().stop.deferral(partsText, cap)
      $.ui.status(t().status.deferred(partsText))
      $.ui.log(t().stop.deferLog(tokens, partsText))
      if (!rt.deferToasted) { rt.deferToasted = true; $.ui.toast(t().status.deferred(partsText)) }
      return
    }
    note = t().stop.note(partsText, cap)
    $.ui.log(t().stop.capLog(tokens, cap, partsText))
  }
  // 上次失敗不久：先不重試
  if (rt.retryAfter && (await $.session.turns()) - rt.retryAfter.turns < RETRY_TURNS && (await $.clock.now()) - rt.retryAfter.at < RETRY_MS) {
    $.ui.log(t().stop.retryLog(tokens))
    return
  }
  rt.deferral = undefined
  rt.deferToasted = false
  $.ui.status(undefined)
  beginPresent()
  $.clock.after(0, () => void present($, tokens, 'present', note))
}

// 設定與介面語言：第一次用到時讀一次就記住（熱重載會重算）。每個 hook 一進來先等它，之後 cfg、t() 同步取用
const initLang = ($: EngineInterface) =>
  (rt.langReady ??= loadConfig($).then(() => detectLang($)).then(setLang, () => setLang('en')))

async function detectLang($: EngineInterface): Promise<Lang> {
  if (cfg.language !== 'auto') return cfg.language
  let setting: unknown
  try { setting = (await $.settings.read()).language } catch {}
  let locale: string | undefined
  try { locale = Intl.DateTimeFormat().resolvedOptions().locale } catch {}
  return pickLang(setting, locale)
}

async function prune($: EngineInterface) {
  const now = await $.clock.now()
  const seen = ((await $.store.get('seen')) as Record<string, number> | undefined) ?? {}
  const { changed, expired } = pruneSeen(await $.store.keys(), seen, now)
  for (const k of expired) await $.store.delete(k)
  if (changed) await $.store.set('seen', seen)
}

// ---------- 守門：狀態與流程（型別、提示、比對在 guards.ts） ----------
// 模型只提草稿（proposed），使用者 /handoff guard on N 核准才生效；依工作區存在 $.store，不進經驗檔
// 每次工具呼叫都會用到：工作區在 process 內不變，算一次就記住（熱重載會重算）
const guardsKey = async ($: EngineInterface) => (rt.guardsKeyCache ??= `guards:${await projectKey($)}`)
async function loadGuards($: EngineInterface) {
  return ((await $.store.get(await guardsKey($))) as Guard[] | undefined) ?? []
}

async function guardCandidates($: EngineInterface) {
  const guards = await loadGuards($)
  const notes = parseNotes(await readText($, await notesFile($)))
  return guardCandidatesOf(notes.rules, guards)
}

// 請整理模型把規則寫成守門草稿（proposed），程式驗證格式並試比對這段對話跑過的工具呼叫
async function draftGuards($: EngineInterface, candidates: Rule[], rows: readonly Row[]) {
  const calls = rows.flatMap(r => r.toolUses)
  const r = await $.model.complete({
    model: cfg.notesModel,
    effort: DISTILL_EFFORT,
    maxTokens: GUARD_MAX_TOKENS,
    timeoutMs: DISTILL_TIMEOUT_MS,
    system: guardPrompt(candidates, [...new Set(calls.map(c => c.tool))]),
    prompt: '依系統指示輸出 ACTIONS。',
  })
  if (!r.isAnswered) return { failed: r.reason }
  const { out, rejected } = parseGuards(r.text, new Set(candidates.map(c => c.name)))
  const guards = await loadGuards($)
  const added = withProposals(out, guards, calls, await $.clock.now())
  await $.store.set(await guardsKey($), [...guards, ...added])
  return { added, rejected }
}

async function suggestGuards($: EngineInterface) {
  const candidates = await guardCandidates($)
  if (candidates.length === 0) return { text: `${t().guard.noCandidates(GUARD_MIN_COUNT)}\n${await guardList($)}` }
  const d = await draftGuards($, candidates, (await $.session.messages()) as readonly Row[])
  if ('failed' in d) return { text: `${t().guard.suggestFailed(String(d.failed))}` }
  const { added, rejected } = d
  await markTried($, candidates)
  return {
    text: [
      `${t().guard.suggested(candidates.length, added.length)}`,
      ...(rejected.length ? [`${t().ind}${t().guard.droppedLines(rejected.length, rejected.join(t().slashList))}`] : []),
      '',
      await guardList($),
    ].join('\n'),
  }
}

// 起草過的規則記下當時的次數（guardTried:<工作區>）：模型判斷寫不成守門的，次數沒再增加就不重試
const triedKey = async ($: EngineInterface) => `guardTried:${await projectKey($)}`
async function markTried($: EngineInterface, rules: Rule[]) {
  const tried = ((await $.store.get(await triedKey($))) as Record<string, number> | undefined) ?? {}
  for (const r of rules) tried[r.name] = r.count
  await $.store.set(await triedKey($), tried)
}

// 整理完自動起草：只送還沒起草過、或起草後又被糾正（次數增加）的候選
async function autoDraftGuards($: EngineInterface, notes: Notes, rows: readonly Row[]) {
  const tried = ((await $.store.get(await triedKey($))) as Record<string, number> | undefined) ?? {}
  const candidates = guardCandidatesOf(notes.rules, await loadGuards($)).filter(r => tried[r.name] !== r.count)
  if (candidates.length === 0) return
  const d = await draftGuards($, candidates, rows)
  if ('failed' in d) { $.ui.log(t().guard.autoFailed(String(d.failed))); return }
  await markTried($, candidates)
  if (d.added.length > 0) $.ui.log(t().guard.autoDrafted(d.added.length))
}

// 使用者在對話裡對草稿的回答（整理認出、附原話）：要就啟用，不要就停用（留著，不再提議同一條規則）；收回對應的詢問
async function applyGuardAnswers($: EngineInterface, actions: Action[]) {
  const answers = guardAnswers(actions)
  if (answers.length === 0) return []
  const guards = await loadGuards($)
  const changes: string[] = []
  for (const a of answers) {
    const g = guards.find(x => x.id === a.id && x.state === 'proposed')
    if (!g) continue
    g.state = a.approve ? 'on' : 'off'
    changes.push(a.approve ? t().change.guardApproved(g.id, g.rule) : t().change.guardDeclined(g.id, g.rule))
  }
  await $.store.set(await guardsKey($), guards)
  const asked = await loadAsked($)
  for (const a of answers) delete asked[`q:${a.id}`]
  await $.store.set(await promoteKey($), asked)
  return changes
}

// 新對話開頭請 AI 問使用者要不要採用的草稿：交給別段對話還沒收回的不問（和放進專案共用交代紀錄，鍵 q:<編號>）
async function guardAskBlock($: EngineInterface, notes: Notes) {
  const asked = await loadAsked($)
  const drafts = (await loadGuards($)).filter(g => g.state === 'proposed' && asked[`q:${g.id}`] === undefined).slice(0, GUARD_ASK_ITEMS)
  if (drafts.length === 0) return undefined
  const sid = await $.session.id()
  const now = await $.clock.now()
  for (const g of drafts) asked[`q:${g.id}`] = { sid, at: now }
  await $.store.set(await promoteKey($), asked)
  return guardAskText(drafts.map(g => ({ guard: g, rule: notes.rules.find(r => r.name === g.rule) })))
}

// 顯示用：併上統計裡的命中次數
async function guardViews($: EngineInterface) {
  const stats = (await $.store.get(statsKey(await projectKey($)))) as Stats | undefined
  return withHits(await loadGuards($), stats?.counts, stats?.hits)
}

const guardList = async ($: EngineInterface) => guardListText(await guardViews($))

async function guardCommand($: EngineInterface, args: string[]) {
  const [action = '', idText = '', modeText = ''] = args
  if (action === '') return { text: await guardList($) }
  if (action === 'suggest') return suggestGuards($)
  const usage = `${t().guard.usage}`
  const change = guardChangeOf(action, modeText)
  if (change === undefined || !idText) return { text: usage }
  const g = await changeGuard($, Number(idText), change)
  if (!g) return { text: `${t().guard.missing(idText)}\n${await guardList($)}` }
  return { text: `${t().guard.changed(g.id, change === 'drop')}\n${await guardList($)}` }
}

// 啟用／停用／刪除／換模式；回傳改到的那一條，找不到回 undefined
async function changeGuard($: EngineInterface, id: number, change: 'on' | 'off' | 'drop' | GuardMode) {
  const r = applyGuardChange(await loadGuards($), id, change)
  if (!r) return undefined
  await $.store.set(await guardsKey($), r.updated)
  return r.g
}

// /handoff panel：開或關輸入框上方的面板（再打一次就關）
async function togglePanel($: EngineInterface) {
  const open = !(await read($, panelUi)).open
  // 先備好資料再打開，畫面一出來就有內容
  if (open) {
    const data = await loadPanelData($)
    await update($, panelData, () => data)
  }
  await update($, panelUi, u => ({ open, tab: u.tab, expanded: u.expanded, suggesting: u.suggesting }))
  return {
    text: `${open ? t().panelCmd.opened : t().panelCmd.closed}`,
  }
}

async function guardSummary($: EngineInterface) {
  return guardSummaryText(await loadGuards($), (await guardCandidates($)).length)
}

async function recordHit($: EngineInterface, id: number, tool: string, input: string) {
  // 次數記在統計，不改守門資料（避免和面板核准互蓋）；擋得對不對程式判斷不了，留指令片段評估時再看
  await stat($, guardHitKey(id), 1, { hit: `#${id} ${tool}: ${input}` })
  await refreshPanel($)
}

// ---------- 面板：/handoff panel，看最近整理的變動、刪掉記錯的筆記、核准守門 ----------
// 畫在輸入框上方（AbovePrompt），不用 Pane：終端機全螢幕版面的 Pane 一定停靠在側邊
// 畫面只讀 $.state 裡的快照：重畫不碰檔案與 store，按鈕不會等 I/O 才有反應
const panelUi = atom({ plugin: 'ctx-handoff', key: 'panelUi' } as const, { open: false, tab: 'guard', expanded: [], suggesting: false })
const panelData = atom({ plugin: 'ctx-handoff', key: 'panelData' } as const, null)

async function loadPanelData($: EngineInterface): Promise<PanelData> {
  const file = await notesFile($)
  const notes = parseNotes(await readText($, file))
  const guards = await guardViews($)
  const d = (await $.store.get(`distill:last:${await projectKey($)}`)) as DistillLast | undefined
  return panelSnapshot(file, notes, guards, d, localStamp(await $.clock.now()).slice(0, 10), await settingRows($))
}

// 設定分頁的列：SETTINGS 的值加上兩個用指令也能切的開關（保持快取、專案筆記，存在 store 的 refresh／distill），依主題排
const SETTING_ORDER = ['auto_handoff', 'threshold', 'window_ratio', 'refresh', 'idle_minutes', 'max_refresh', 'distill', 'distill_every', 'min_tokens', 'notes_model', 'resume_hint', 'retry_nudge', 'done_check', 'reply_language', 'language']
const STORE_SWITCHES = new Set(['refresh', 'distill'])

async function settingRows($: EngineInterface): Promise<PanelSetting[]> {
  const { options, panel } = await readSettings($)
  const rows: PanelSetting[] = []
  for (const key of SETTING_ORDER) {
    if (STORE_SWITCHES.has(key)) {
      const stored = await $.store.get(key)
      rows.push({ key, kind: 'bool', value: stored !== false, source: stored === undefined ? 'default' : 'panel' })
      continue
    }
    const spec = specOf(key)
    if (!spec) continue
    const shown = key === 'reply_language' && cfg.replyLanguage === 'auto' ? (await replyTarget($)) ?? 'off'
      : key === 'language' && cfg.language === 'auto' ? getLang() : undefined
    rows.push({ key, kind: spec.kind, value: settingValue(spec, panel[key] ?? options[key]), source: settingSource(key, panel, options), ...(shown ? { shown } : {}) })
  }
  return rows
}

// 面板改一個設定：數字加減一格、開關反過來、選項往後輪；存進 store 後馬上重讀（其他 session 在下一則訊息重讀）
async function changeSetting($: EngineInterface, key: string, dir: 1 | -1) {
  const name = t().panel.settingName[key] ?? key
  if (STORE_SWITCHES.has(key)) {
    const on = (await $.store.get(key)) !== false
    await $.store.set(key, !on)
    if (key === 'distill') await showDistillStatus($)
    return t().panelCmd.settingSet(name, on ? t().panel.offValue : t().panel.on)
  }
  const spec = specOf(key)
  if (!spec) return t().panelCmd.notFound
  const { options, panel } = await readSettings($)
  const value = stepSetting(spec, panel[key] ?? options[key], dir)
  await $.store.set('settings', { ...panel, [key]: value })
  await reloadConfig($)
  return t().panelCmd.settingSet(name, showSetting(key, value))
}

// 還原：拿掉面板存的值，回到 settings.json 或預設
async function resetSetting($: EngineInterface, key: string) {
  const name = t().panel.settingName[key] ?? key
  if (STORE_SWITCHES.has(key)) {
    await $.store.delete(key)
    if (key === 'distill') await showDistillStatus($)
    return t().panelCmd.settingReset(name, t().panel.on)
  }
  const spec = specOf(key)
  if (!spec) return t().panelCmd.notFound
  const { options, panel } = await readSettings($)
  const { [key]: _drop, ...rest } = panel
  await $.store.set('settings', rest)
  await reloadConfig($)
  return t().panelCmd.settingReset(name, showSetting(key, settingValue(spec, options[key])))
}

// 面板開著才重算快照；失敗寫進提示列，不影響呼叫的地方
async function refreshPanel($: EngineInterface) {
  if (!(await read($, panelUi)).open) return
  try {
    const data = await loadPanelData($)
    await update($, panelData, () => data)
  } catch (err) {
    await setNote($, t().panelCmd.readFailed(String(err)))
  }
}

// 換掉提示列（undefined 清掉），順便清掉等待確認的刪除
const setNote = ($: EngineInterface, note: string | undefined) =>
  update($, panelUi, ({ confirming: _c, note: _n, ...u }) => (note ? { ...u, note } : u))

// 刪一條記憶（m:<原文>）或規則（r:<名稱>）：重讀經驗檔、比對原文，寫檔前把原檔備份到旁邊的 .ctx-handoff-backup/
// 封存的記憶按「留下」：加一筆今天的根據，等於人工證實一次（不刪內容，不用備份）
async function keepNote($: EngineInterface, head: string) {
  if (rt.distilling) return t().panelCmd.busyKeep
  const file = await notesFile($)
  const notes = parseNotes(await readText($, file))
  const m = notes.memory.find(x => memHead(x) === head)
  if (!m) return t().panelCmd.notFound
  const now = await $.clock.now()
  keepMemory(m, localStamp(now).slice(0, 10))
  await $.fs.write(file, renderNotes(notes, localStamp(now)))
  return t().panelCmd.kept(m.title)
}

async function dropNote($: EngineInterface, key: string) {
  if (rt.distilling) return t().panelCmd.busyDrop
  const file = await notesFile($)
  const original = await readText($, file)
  const notes = parseNotes(original)
  const removed = withoutNote(notes, key)
  if (!removed) return t().panelCmd.notFound
  const now = await $.clock.now()
  const dir = file.slice(0, file.lastIndexOf('/'))
  await $.fs.write(backupPath(dir, now), original)
  await $.fs.write(file, renderNotes(removed.updated, localStamp(now)))
  return t().panelCmd.deleted(key.startsWith('m:') ? 'm' : key.startsWith('p:') ? 'p' : 'r', removed.target, dir)
}

// ---------- 進度備忘：整理順手留下「停在哪」，下一段對話開頭提供一次（型別、文字在 progress.ts） ----------
// 依工作區存一份在 $.store（暫時性的，不進經驗檔）；同一工作區的多個 session 同時整理時，最後寫的那份為準
const progressKeyOf = async ($: EngineInterface) => progressKey(await projectKey($))
const loadProgress = async ($: EngineInterface) => (await $.store.get(await progressKeyOf($))) as Progress | undefined

// 已經交接出去的 session 之後才跑完的整理：照樣存成最新的一份，但標記已交接（handoff 摘要已涵蓋，不再提供）；
// 不存的話留下的會是更早、別的 session 的進度，新對話反而拿到過時的那份
async function saveProgress($: EngineInterface, sid: string, p: ProgressFields, at: number) {
  await $.store.set(await progressKeyOf($), { ...p, sid, at, ...(rt.handed.has(sid) ? { handed: true as const } : {}) } satisfies Progress)
}

// 自動交接（/clear 之後把 handoff 送進新對話）：這個 session 的進度備忘不再提供；on=false 還原。
// 進度只是附帶的，失敗不影響交接
async function markHanded($: EngineInterface, sid: string, on: boolean) {
  try {
    if (on) rt.handed.add(sid)
    else rt.handed.delete(sid)
    const p = await loadProgress($)
    if (p?.sid !== sid) return
    const { handed: _h, ...rest } = p
    await $.store.set(await progressKeyOf($), on ? { ...rest, handed: true as const } : rest)
  } catch {}
}

// 這段對話開頭要提供的進度：不是這個 session 留下的、一天內、沒被 handoff 取代、還沒提供給這個 session
async function progressBlock($: EngineInterface) {
  if (!cfg.resumeHint) return undefined
  const p = await loadProgress($)
  const sid = await $.session.id()
  const text = progressOffer(p, sid, await $.clock.now())
  if (!text || !p) return undefined
  await $.store.set(await progressKeyOf($), withOffered(p, sid))
  return text
}

// ---------- 放進專案 ----------
const promoteKey = async ($: EngineInterface) => `promote:${await projectKey($)}`
const loadAsked = async ($: EngineInterface) => ((await $.store.get(await promoteKey($))) as Record<string, PromoteAsk> | undefined) ?? {}

// 這段對話開頭要交代的：session 啟動資料夾是 git repo 才交代；交給別段對話還沒收回的不交代
async function promoteBlock($: EngineInterface, notes: Notes) {
  const root = slash(await $.session.root())
  if (!(await $.fs.exists(`${root}/.git`))) return undefined
  const asked = await loadAsked($)
  const released = await guardsAlreadyInRepo($, root, asked)
  const items = promoteItems(await loadGuards($), notes, asked)
  if (items.length === 0) {
    if (released) await $.store.set(await promoteKey($), asked)
    return undefined
  }
  markAsked(asked, items, await $.session.id(), await $.clock.now())
  await $.store.set(await promoteKey($), asked)
  return promoteText(items)
}

// 啟用中的守門，提醒文字已經寫在 repo 的 .claude/hooks/ 或 .claude/settings.json：記成已在那個檔案並停用這份，
// 收回它的交代紀錄（asked 由呼叫端寫回）。只讀 repo，不寫
async function guardsAlreadyInRepo($: EngineInterface, root: string, asked: Record<string, PromoteAsk>) {
  const guards = await loadGuards($)
  if (!guards.some(g => g.state === 'on' && g.project === undefined)) return false
  const paths = ['.claude/settings.json']
  try {
    for (const e of await $.fs.list(`${root}/.claude/hooks`)) if (e.kind === 'file') paths.push(`.claude/hooks/${e.name}`)
  } catch {}
  const files: { path: string; text: string }[] = []
  for (const p of paths) {
    try { files.push({ path: p, text: await $.fs.read(`${root}/${p}`) }) } catch {}
  }
  const found = guardsFoundInRepo(guards, files)
  if (found.length === 0) return false
  for (const f of found) {
    const g = guards.find(x => x.id === f.id)
    if (!g) continue
    g.project = `${PROJECT_IN}${f.where}`
    g.state = 'off'
    delete asked[`g:${g.id}`]
    $.ui.log(t().change.inProject(g.rule, f.where))
  }
  await $.store.set(await guardsKey($), guards)
  await refreshPanel($)
  return true
}

// 收回交給這段對話的項目（before：只收回這個時間之前交代的），下一段新對話再交代
async function releasePromote($: EngineInterface, sid: string, before?: number) {
  const asked = await loadAsked($)
  if (releaseAsked(asked, sid, before)) await $.store.set(await promoteKey($), asked)
}

// 整理說放進 repo 的位置要真的存在：相對路徑以 session 啟動資料夾為準，絕對路徑在它底下就改成相對路徑；
// 不存在的丟掉並記進丟棄樣本
async function checkPromotions($: EngineInterface, actions: Action[], rejected: Rejected) {
  const root = slash(await $.session.root())
  const out: Action[] = []
  for (const a of actions) {
    if (a.op !== 'in_project') { out.push(a); continue }
    const p = slash(a.where).replace(/^\.\//, '')
    const abs = isAbs(p) ? p : `${root}/${p}`
    if (!(await $.fs.exists(abs))) { addRejected(rejected, t().reject.whereMissing(a.where), JSON.stringify(a)); continue }
    out.push({ ...a, where: abs.toLowerCase().startsWith(`${root.toLowerCase()}/`) ? abs.slice(root.length + 1) : p })
  }
  return out
}

// 整理認出的放進 repo：守門記 project（放進 repo 的停用 ctx-handoff 自己這份），收回對應的交代紀錄；
// 這段對話在整理開始前交代的其他項目也收回（整理看過了，卻沒看到放好），下一段新對話再交代
async function applyPromotions($: EngineInterface, actions: Action[], candidates: { id: string; key: string; name: string }[], sid: string, started: number) {
  const changes: string[] = []
  const promos = guardPromotions(actions)
  if (promos.length > 0) {
    const guards = await loadGuards($)
    for (const p of promos) {
      const g = guards.find(x => x.id === p.id)
      if (!g) continue
      g.project = p.where === undefined ? PROJECT_DECLINED : `${PROJECT_IN}${p.where}`
      if (p.where !== undefined) g.state = 'off'
      changes.push(p.where === undefined ? t().change.notInProject(g.rule) : t().change.inProject(g.rule, p.where))
    }
    await $.store.set(await guardsKey($), guards)
  }
  const asked = await loadAsked($)
  const keyOf = new Map(candidates.map(c => [c.id, c.key]))
  let changed = releaseAsked(asked, sid, started)
  for (const a of actions) {
    const key = (a.op === 'in_project' || a.op === 'not_in_project') ? keyOf.get(a.id) : undefined
    if (key !== undefined && asked[key] !== undefined) { delete asked[key]; changed = true }
  }
  if (changed) await $.store.set(await promoteKey($), asked)
  return changes
}

function panelActions($: EngineInterface): PanelActions {
  // 讀寫檔的動作在背景跑（不讓按鍵等它），跑完重算快照、結果寫進提示列；只改畫面狀態的直接寫 $.state
  const run = (work: () => Promise<string | undefined>) => {
    void work()
      .catch(err => t().panelCmd.failed(String(err)))
      .then(async note => { await refreshPanel($); await setNote($, note) })
  }
  const setUi = (fn: (u: PanelUi) => PanelUi) => update($, panelUi, fn)
  return {
    guard: (id, action) => run(async () => {
      const g = await changeGuard($, id, action)
      return g ? t().guard.panelDone(id, action) : t().guard.missing(String(id))
    }),
    suggest: () => run(async () => {
      if ((await read($, panelUi)).suggesting) return undefined
      await setUi(u => ({ ...u, suggesting: true }))
      try { return (await suggestGuards($)).text.split('\n')[0]?.replace(``, '') }
      finally { await setUi(u => ({ ...u, suggesting: false })) }
    }),
    tab: tab => setUi(({ confirming: _c, note: _n, ...u }) => ({ ...u, tab })),
    toggle: key => setUi(u => ({ ...u, expanded: u.expanded.includes(key) ? u.expanded.filter(k => k !== key) : [...u.expanded, key] })),
    ask: key => setUi(({ confirming: _c, note: _n, ...u }) => (key ? { ...u, confirming: key } : u)),
    drop: key => run(() => dropNote($, key)),
    setting: (key, dir) => run(() => changeSetting($, key, dir)),
    resetSetting: key => run(() => resetSetting($, key)),
    keep: head => run(() => keepNote($, head)),
    close: () => setUi(u => ({ ...u, open: false })),
  }
}

// 工具呼叫結束後的觀察（不碰 $，失敗一律放行原結果，絕不丟例外、不擋呼叫）：
// A 同一個工具連續兩次因同樣原因失敗，在第 2 次的結果後面附一段提醒（context，模型看得到、使用者看不到）；
// B 記下這一輪的改檔與驗證，給回合結束時的檢查用；
// C 主對話上一步的說明不是目標語言（watchReply 排的），在這個結果後面附回覆語言提醒
function watchCall<R extends { deny?: string; isError?: boolean; text?: string; result?: unknown; context?: readonly string[] }>(
  e: { tool: string },
  r: R,
): R {
  try {
    if (r.deny !== undefined) return r
    const failed = r.isError === true
    const agent = (e as { agentId?: string }).agentId ?? ''
    // 只記主對話自己的呼叫：子代理（含還在背景跑的）改檔或驗證不算主對話這一輪（2026-10-08 實機誤判）
    if (cfg.doneCheck && agent === '') noteCall(rt.work, e.tool, e as Record<string, unknown>, failed)
    const extra: string[] = []
    if (cfg.retryNudge) {
      const text = r.text ?? (typeof r.result === 'string' ? r.result : undefined)
      const nudge = trackFailure(rt.streaks, `${agent}|${e.tool}`, e.tool, failed, text)
      if (nudge) extra.push(nudge)
    }
    // 回覆語言：主對話上一步的說明不是目標語言，這個工具結果帶出提醒（子代理的結果不帶）
    const reply = agent === '' ? takePending(rt.reply) : undefined
    if (reply) extra.push(reply)
    return extra.length ? { ...r, context: [...(r.context ?? []), ...extra] } : r
  } catch {
    return r
  }
}

// 回覆語言的目標：設定指定的語言；auto 跟著 Claude Code 的 language 設定，沒設或認不得就是 undefined（不提醒）。
// 算一次就記住，設定改了（config.set）或熱重載才重算
async function replyTarget($: EngineInterface) {
  if (rt.replyTarget) return rt.replyTarget.lang
  let setting: unknown
  if (cfg.replyLanguage === 'auto') {
    try { setting = (await $.settings.read()).language } catch { return undefined }
  }
  const lang = resolveReplyLang(cfg.replyLanguage, setting)
  rt.replyTarget = { lang }
  return lang
}

// turn.step 之後：主對話這一步的說明不是目標語言就排一次提醒（絕不丟例外、不改這一步的結果）。
// 這步還要呼叫工具，提醒跟著下一個工具結果（watchCall）；最終回答則跟著使用者的下一則訊息（prompt.submit）
async function watchReply($: EngineInterface, r: { answer: string; toolUses: readonly unknown[] }) {
  try {
    await initLang($)
    if (cfg.replyLanguage === 'off' || !r.answer) return
    const target = await replyTarget($)
    if (target) noteStep(rt.reply, r.answer, r.toolUses.length > 0, target)
  } catch {}
}

// 回合結束時說完成了，但這一輪改檔之後沒有跑任何測試或檢查：回傳要擋下停止的理由（每回合最多一次）。
// 紀錄用完就清；擋下的那次保留 reminded，之後同一回合的停止不再擋。使用者中斷的回合 Stop 不會觸發，
// 紀錄由 turn.complete（isAborted）與下一則人類訊息清掉
function doneReason(e: { stop_hook_active?: boolean; last_assistant_message?: string }): string | undefined {
  try {
    if (cfg.doneCheck) {
      const reason = doneCheck(rt.work, e.last_assistant_message, e.stop_hook_active === true)
      if (reason) return reason
    }
  } catch {}
  rt.work = freshWork()
  return undefined
}

export const register: Register = on => {
  resetRuntime()
  resetConfig()
  setLang('en')

  on('session.start', async ($, e, next) => {
    // 本機改版：記下有沒有人在 prompt 前；-p／SDK 不做門檻自動交接與閒置刷新
    rt.interactive = e.isInteractive
    await initLang($)
    // 本機改版：保留舊指令名（與 /handoff 的子指令同一套流程）
    for (const [name, desc] of [
      ['handoff-now', t().save.descNow],
      ['handoff-status', t().save.descStatus],
      ['handoff-resume', t().save.descResume],
      ['handoff-continue', t().save.descContinue],
      ['handoff-refresh', t().save.descRefresh],
    ] as const) {
      try {
        await $.command.register({ name, description: desc })
      } catch (err) {
        $.ui.log(t().start.registerFailed(String(err)))
      }
    }
    const description = t().start.description
    // 專案或使用者已有同名的 /handoff（例如自己的 skill）時，改用 /ctx-handoff
    try {
      await $.command.register({ name: 'handoff', description })
    } catch (err) {
      try {
        await $.command.register({ name: 'ctx-handoff', description })
        $.ui.log(t().start.taken(String(err)))
      } catch (err2) {
        $.ui.log(t().start.registerFailed(String(err2)))
      }
    }
    try {
      await showDistillStatus($)
    } catch {}
    // 熱重載也會跑到這裡：接回被清掉的閒置計時
    try {
      await resumeSchedule($)
    } catch (err) {
      $.ui.log(t().start.resumeFailed(String(err)))
    }
    try {
      await prune($)
    } catch (err) {
      $.ui.log(t().start.pruneFailed(String(err)))
    }
    return next(e)
  })

  // 對話結束（退出、/clear、resume、訊號）：交給它的放進專案收回，下一段新對話再交代
  on('session.end', async ($, e, next) => {
    try {
      await releasePromote($, e.sessionId)
    } catch {}
    return next(e)
  })

  /**
   * 本機改版：認出存檔回合：存檔中、主對話、同一個 session，且 prompt 帶存檔標記與這次嘗試的識別碼，
   * 就記下它的 turnId，turn.complete 才知道哪個回合是它。逾時的舊嘗試識別碼不同，不會被誤認。
   * @param $ engine 介面
   * @param e turn.start 輸入
   * @param next 下一層
   * @returns 下一層的結果（不改回合）
   */
  on('turn.start', async ($, e, next) => {
    // STEP 01: 只認尚未認出的這次嘗試
    /** 進行中的存檔嘗試 */
    const s = rt.saving
    if (e.agentId === undefined && s !== undefined && s.turnId === undefined && e.text.includes(SAVE_MARK) && e.text.includes(attemptTag(s.attempt))) {
      // STEP 01.01: 還要是發起嘗試的同一個 session；讀完 session 後再確認嘗試沒換掉
      if ((await $.session.id()) === s.sessionId && rt.saving === s) {
        rt.saving = { ...s, turnId: e.turnId }
      }
    }
    // STEP 02: 交回引擎
    return next(e)
  })

  // 回覆語言提醒：只看主對話的步驟，不改請求（model、effort 原封不動往下傳，不影響快取）
  on('turn.step', async function* ($, e, next) {
    const r = yield* next(e)
    if (e.agentId === undefined) await watchReply($, r)
    return r
  })

  // 使用者在 /config 改了 Claude Code 的設定（例如 language）：回覆語言 auto 要重新解析
  on('config.set', async (_$, e, next) => {
    const out = await next(e)
    if (out.deny === undefined) rt.replyTarget = undefined
    return out
  })

  // 每段新對話（含 /clear 之後）開頭帶入這個工作區的經驗；只在開頭一次，不影響之後的快取
  on('prompt.context', async ($, e, next) => {
    const out = await next(e)
    await initLang($)
    try {
      const file = await notesFile($)
      const notes = parseNotes(await readText($, file))
      const text = contextText(notes, file, localStamp(await $.clock.now()).slice(0, 10))
      const promote = await promoteBlock($, notes)
      const guardAsk = await guardAskBlock($, notes).catch(() => undefined)
      // 進度備忘出錯不影響經驗與放進專案的交代
      const progress = await progressBlock($).catch(() => undefined)
      const blocks = [
        ...(text ? [{ name: 'ctxHandoffProject', text }] : []),
        ...(promote ? [{ name: 'ctxHandoffPromote', text: promote }] : []),
        ...(guardAsk ? [{ name: 'ctxHandoffGuardAsk', text: guardAsk }] : []),
        ...(progress ? [{ name: 'ctxHandoffProgress', text: progress }] : []),
      ]
      return blocks.length ? { ...out, blocks: [...out.blocks, ...blocks] } : out
    } catch {
      return out
    }
  })

  // 守門：只有使用者核准（on）的才比對；hook 自己出錯時放行，不擋正常工作
  on('tool.call', async ($, e, next) => {
    let hit: Guard | undefined
    try {
      const text = inputText(e as Record<string, unknown>)
      hit = (await loadGuards($)).find(g => g.state === 'on' && guardHits(g, e.tool, text))
    } catch (err) {
      await initLang($)
      $.ui.log(t().guard.checkFailed(String(err)))
    }
    await initLang($)
    if (!hit) return watchCall(e, await next(e))
    await recordHit($, hit.id, e.tool, inputText(e as Record<string, unknown>))
    const head = `${tag} ${t().guard.head(hit.id, hit.rule, hit.message)}`
    if (hit.mode === 'deny') {
      $.ui.toast(t().guard.denyToast(hit.id, e.tool, hit.rule))
      return { deny: `${head}\n${t().guard.denyHint(hit.id)}` }
    }
    const r = await next(e)
    return watchCall(e, r.deny === undefined ? { ...r, context: [...(r.context ?? []), head] } : r)
  })

  // 面板沒開、或問卷佔著輸入框上方時，交給下層（其他 plugin 或引擎自己的）
  // 只讀 $.state（讀了就訂閱，寫入時自動重畫），不讀檔
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    await initLang($)
    const ui = await read($, panelUi)
    const data = ui.open && !e.props.hasSurvey ? await read($, panelData) : null
    return data
      ? panelTree($.ui.resolve(e), { ...data, ...ui, columns: e.props.bodyColumns }, panelActions($))
      : next(e)
  })

  on('turn.complete', async ($, e, next) => {
    await initLang($)
    const out = await next(e)
    // 被中斷的回合沒有 Stop：清掉這一輪的改檔紀錄，免得算到下一輪
    if (e.agentId === undefined && e.isAborted) rt.work = freshWork()
    // 本機改版：存檔回合結束：交給 saveTurn 驗證（交接中 rt.busy 為 true，要在下面的提前返回之前）
    if (e.agentId === undefined && rt.saving?.turnId !== undefined && rt.saving.turnId === e.turnId) {
      rt.saving.settle(e)
      return out
    }
    if (e.agentId !== undefined || rt.busy) return out
    // 別的 session 可能改了經驗檔或守門：每個回合結束重算一次面板快照（面板沒開時只讀一個 state）
    await refreshPanel($)
    // 主對話又往前走了：沒有被攔下訊息的離席 handoff 已經過時
    const { key: staleKey, away } = await loadAway($)
    if (away !== undefined && away.held === undefined) {
      await $.store.delete(staleKey)
      $.ui.log(t().idle.outdated)
      await stat($, 'away.stale')
    }
    // 每個回合都用到快取，TTL 從這裡重算（本機改版：非互動 session 不排閒置刷新）
    if (rt.interactive) {
      await schedule($)
    }
    if (e.reason !== 'answer') return out
    const { context } = await $.session.usage()
    // 到門檻的交接由 classic.Stop 判斷；這裡只處理還沒到門檻的整理（自動交接關閉時門檻不算數）
    // 本機改版：依「實際能否自動交接」（autoState，和 onStop 同一判斷），非互動或暫停時照樣整理
    if (autoState() === 'on' && context.tokens !== undefined && context.tokens >= thresholdOf(context.window)) {
      return out
    }
    // 每 distill_every 則使用者訊息，趁快取熱整理一次
    if ((context.tokens ?? 0) >= cfg.minTokens && !rt.distilling && (await isDistillOn($)) && (await sinceDistill($)) >= cfg.distillEvery) {
      const every = cfg.distillEvery
      $.clock.after(0, () => void distill($, t().distill.why.every(every)))
    }
    if (!rt.distilling) await showDistillStatus($)
    return out
  })

  on('classic.Stop', async ($, e, next) => {
    await initLang($)
    const out = await next(e)
    // 別的 Stop hook 要求繼續：回合其實沒結束，等它真正停下的那次 Stop 再判斷
    if (out.block !== undefined) return out
    // 說完成了卻沒驗證：擋下這次停止，回合還沒結束，不判斷交接
    const reason = e.agent_id === undefined ? doneReason(e) : undefined
    if (reason !== undefined) {
      $.ui.log(t().loops.doneLog)
      return { ...out, block: reason }
    }
    try {
      await onStop($, e)
    } catch (err) {
      $.ui.log(t().stop.stopFailed(String(err)))
    }
    return out
  })

  on('prompt.submit', async ($, e, next) => {
    const isHuman = e.origin.kind === 'composer' || e.origin.kind === 'bridge'
    if (!isHuman) return next(e)
    await initLang($)
    try { await reloadConfig($) } catch {}
    const isSlash = e.text.trimStart().startsWith('/')
    // 交接進行中：訊息先攔下，建好的文字或交接後一起送進新對話
    const hasAttachments = (e.attachments?.length ?? 0) > 0
    if (rt.presenting && !isSlash && (e.text.trim() || hasAttachments)) {
      const elapsed = rt.presentStartedAt === undefined ? 0 : Math.round(((await $.clock.now()) - rt.presentStartedAt) / 1000)
      // 本機改版：交接等的是存檔回合（不是 fork 時限），提示寫存檔回合沒開始就取消的時限
      const wait = t().submit.wait(elapsed, SAVE_LOST_MS / MS_PER_MIN)
      // 只能暫存文字：mod 拿不到附件內容
      const attachNote = hasAttachments ? t().submit.attach : ''
      if (!e.text.trim()) return { drop: `${t().submit.busy(wait, attachNote)}` }
      // 以為卡住而重送：同樣的內容只送一次
      if (rt.held.some(h => h.trim() === e.text.trim())) {
        return { drop: `${t().submit.dup(wait, attachNote)}` }
      }
      rt.held.push(e.text)
      return { drop: `${t().submit.held(wait, attachNote)}` }
    }
    rt.idle?.cancel()
    rt.idle = undefined
    rt.refreshes = 0
    // 新的一輪從使用者的新訊息開始：改檔與驗證紀錄重算
    rt.work = freshWork()
    await update($, idleState, () => null)
    const sid = await $.session.id()
    // 背景整理的錨點：下次從這則訊息之後開始
    if (!isSlash && e.text.trim()) {
      await $.store.set(`last:${sid}`, anchorOf(e.text))
      await touchSeen($, `last:${sid}`)
    }
    if (rt.myPending && !rt.busy && !rt.pendingToasted) {
      rt.pendingToasted = true
      $.ui.toast(t().submit.pendingToast)
    }
    if (isSlash) return next(e)

    const { key, away } = await loadAway($)
    let msg = e
    if (away !== undefined) {
      if (away.held === undefined) {
        // 只有附件、沒有文字：沒有可以暫存的內容，先請使用者選擇
        if (!e.text.trim()) {
          return { drop: `${t().submit.awayAttach}` }
        }
        await $.store.set(key, { ...away, held: e.text } satisfies Away)
        return { drop: `${t().submit.awayHeld(hasAttachments)}` }
      }
      // 再送一次＝選擇繼續舊對話；文字不同就把先前攔下的那則一起帶上
      await $.store.delete(key)
      if (e.text !== away.held) msg = { ...e, text: `${away.held}\n\n${e.text}` }
    }
    // 背景整理的差異：只有訊息真的進了對話才帶入並清掉
    // 回覆語言提醒也一樣：上一則回答不是目標語言的話，跟著這則訊息帶入
    const pend = rt.pendingNotes.get(sid)
    const reply = peekNext(rt.reply)
    if (!pend && reply.length === 0) return next(msg)
    const r = await next({ ...msg, context: [...(msg.context ?? []), ...(pend ? [noteBlock(pend.changes, pend.file)] : []), ...reply] })
    if ((r as { drop?: string }).drop === undefined) {
      rt.pendingNotes.delete(sid)
      clearNext(rt.reply)
    }
    return r
  })

  // 只有一個指令 /handoff（被佔用時是 /ctx-handoff），用子指令區分；不帶參數就顯示狀態和用法
  for (const command of ['handoff', 'ctx-handoff']) on('command.run', { command }, async ($, e) => {
    await initLang($)
    const [sub = '', arg = '', ...rest] = e.args.trim().split(/\s+/)
    switch (sub) {
      case '': return { text: await status($) }
      case 'now': return handoffNow($)
      case 'dry': return handoffDry($)
      case 'distill': return distillCommand($, arg)
      case 'resume': return resume($)
      case 'continue': return keepOld($)
      case 'resend': return resend($)
      case 'refresh': return refreshCommand($, arg)
      case 'guard': {
        const r = await guardCommand($, [arg, ...rest])
        await refreshPanel($)
        return r
      }
      case 'panel': return togglePanel($)
      default: return { text: `${t().cmd.unknown(sub)}\n${usageText()}` }
    }
  })

  /**
   * 本機改版：舊指令 /handoff-now（要打 yes 才動作），走 /handoff now 同一條 save-progress 流程。
   * @param $ engine 介面
   * @param e 指令輸入（args 要是 yes）
   * @returns 指令回覆
   */
  on('command.run', { command: 'handoff-now' }, async ($, e) => {
    // STEP 01: 要明確打 yes
    await initLang($)
    if (e.args.trim() !== 'yes') {
      return { text: t().save.nowNeedsYes }
    }
    // STEP 02: 交給 /handoff now
    return handoffNow($)
  })

  /**
   * 本機改版：舊指令 /handoff-status：等同 /handoff 不帶參數（含「自動交接」一行）。
   * @param $ engine 介面
   * @returns 狀態文字
   */
  on('command.run', { command: 'handoff-status' }, async $ => {
    // STEP 01: 讀狀態並回覆
    await initLang($)
    return { text: await status($) }
  })

  /**
   * 本機改版：舊指令 /handoff-resume、/handoff-continue、/handoff-refresh 對應到 /handoff resume|continue|refresh。
   * @param $ engine 介面
   * @param e 指令輸入（refresh 帶 on|off）
   * @returns 對應子指令的回覆
   */
  for (const [command, sub] of [['handoff-resume', 'resume'], ['handoff-continue', 'continue'], ['handoff-refresh', 'refresh']] as const) {
    on('command.run', { command }, async ($, e) => {
      // STEP 01: 依舊指令名轉給對應的子指令
      await initLang($)
      if (sub === 'resume') {
        return resume($)
      }
      if (sub === 'continue') {
        return keepOld($)
      }
      return refreshCommand($, e.args.trim())
    })
  }
}

/** 本機改版：門檻自動交接的現況 */
type AutoState = 'on' | 'off' | 'noninteractive' | 'paused'

/**
 * 本機改版：門檻自動交接實際能不能做：onStop（要不要交接）、turn.complete（整理要不要讓位）與狀態顯示共用這一個判斷。
 * @returns 非互動 > 設定關閉 > 連續失敗暫停 > 開啟
 */
function autoState(): AutoState {
  // STEP 01: 依優先序判斷
  if (!rt.interactive) {
    return 'noninteractive'
  }
  if (!cfg.autoHandoff) {
    return 'off'
  }
  return isPausedBy(rt.saveFailures) ? 'paused' : 'on'
}

/**
 * 本機改版：給 /handoff 狀態顯示的「自動交接：…」一行。
 * @returns 狀態文字
 */
function autoLine() {
  // STEP 01: 依目前狀態組字串
  return t().save.auto(autoState(), rt.saveFailures)
}

/**
 * 本機改版：讀這個 session 的離席紀錄；格式不符（例如上游 0.5–0.7 的 { handoff } 摘要）就刪掉並當成沒有，
 * 不會在 resume 送出 "undefined"。
 * @param $ engine 介面
 * @returns 合格的離席紀錄與它的鍵；沒有時 away 為 undefined
 */
async function loadAway($: EngineInterface) {
  // STEP 01: 讀出並檢查形狀
  /** 這個 session 的離席紀錄鍵 */
  const key = awayKey(await $.session.id())
  /** store 裡的原始值 */
  const raw = await $.store.get(key)
  /** 檢查過的離席紀錄 */
  const away = parseAway(raw)
  // STEP 02: 有值但格式不符：刪掉並告知；使用者被攔下的訊息文字一併印出，不讓它無聲消失
  if (raw !== undefined && away === undefined) {
    await $.store.delete(key)
    /** 紀錄裡使用者被攔下的訊息；沒有時為 undefined */
    const stranded = strandedHeld(raw)
    $.ui.log(stranded === undefined ? t().save.awayMalformed : t().save.awayMalformedHeld(stranded))
    if (stranded !== undefined) {
      $.ui.toast(t().save.awayMalformedHeld(stranded))
    }
  }
  return { key, away }
}

async function status($: EngineInterface) {
  const { context } = await $.session.usage()
  const { away } = await loadAway($)
  const pk = await projectKey($)
  const list = ((await $.store.get(`handoffs:${pk}`)) as Saved[] | undefined) ?? []
  const herr = (await $.store.get(`handoff:error:${pk}`)) as HandoffError | undefined
  return statusText({
    tokens: context.tokens, window: context.window, refreshOn: await isRefreshOn($), away, last: list.at(-1), herr,
    distill: await distillStatus($), guards: await guardSummary($), progress: await progressStatus($), replyLang: await replyLangLabel($),
    auto: autoLine(),
  })
}

// /handoff 狀態裡的回覆語言：auto 一併顯示解析出的結果
async function replyLangLabel($: EngineInterface) {
  if (cfg.replyLanguage !== 'auto') return cfg.replyLanguage
  return `auto → ${(await replyTarget($)) ?? 'off'}`
}

async function progressStatus($: EngineInterface) {
  const p = await loadProgress($)
  return p && t().progress.status(new Date(p.at).toLocaleString(), p.task, t().progress.states[p.state] ?? p.state, !cfg.resumeHint)
}

async function handoffNow($: EngineInterface) {
  if (rt.busy) return { text: `${t().cmd.busy}` }
  const { context } = await $.session.usage()
  const tokens = context.tokens ?? null
  beginPresent()
  $.clock.after(0, () => void present($, tokens, 'manual'))
  return { text: `${t().cmd.nowStarted}` }
}

async function handoffDry($: EngineInterface) {
  if (rt.busy) return { text: `${t().cmd.busy}` }
  const { context } = await $.session.usage()
  rt.busy = true
  try {
    const text = await makeHandoff($, 'dry', context.tokens ?? null)
    if (text === undefined) return { text: `${t().cmd.dryFailed}` }
    const list = ((await $.store.get(`handoffs:${await projectKey($)}`)) as Saved[] | undefined) ?? []
    const usage = list.at(-1)?.usage
    return {
      text: `${t().cmd.dryDone(String(context.tokens ?? '?'))}\n` +
        `${usage ? describeUsage(usage) : ''}\n\n${text}`,
    }
  } finally {
    rt.busy = false
  }
}

async function distillCommand($: EngineInterface, arg: string) {
  if (arg === 'on' || arg === 'off') {
    await $.store.set('distill', arg === 'on')
    await showDistillStatus($)
    return { text: t().cmd.distillSet(arg) }
  }
  if (arg !== '') return { text: `${t().cmd.distillUsage}` }
  if (rt.distilling) return { text: `${t().cmd.distilling}` }
  const r = await distill($, t().distill.why.manual)
  if (r === undefined || !r.isAnswered || rt.distillFailed) {
    return { text: `${t().cmd.distillNone}\n${await distillStatus($)}` }
  }
  return { text: `${t().cmd.distillDone}\n${await distillStatus($)}` }
}

async function refreshCommand($: EngineInterface, arg: string) {
  if (arg !== 'on' && arg !== 'off') return { text: `${t().cmd.refreshNow((await isRefreshOn($)) ? 'on' : 'off')}` }
  await $.store.set('refresh', arg === 'on')
  return { text: t().cmd.refreshSet(arg, cfg.idleMs / 60_000) }
}

async function resume($: EngineInterface) {
  // 本機改版：離席紀錄是 save-progress 交接紀錄檔；新對話讀檔，有攔下的訊息就附在後面
  const { key, away } = await loadAway($)
  if (away === undefined) return { text: `${t().cmd.noAway}` }
  await $.store.delete(key)
  const intro = `${tag} ${away.held === undefined ? t().save.resumeIntro(away.file) : t().save.resumeIntroHeld(away.file)}`
  const body = away.held === undefined ? intro : `${intro}\n\n${t().cmd.resumeHeld}\n${away.held}`
  rt.busy = true
  const sid = await $.session.id()
  $.clock.after(0, () => {
    void clearAndSubmit($, body)
      .then(async failed => {
        if (!failed) { await stat($, 'away.resume'); return }
        $.ui.log(t().cmd.resumeFailedLog(failed.reason))
        await recordFailure($, 'away', null, t().handoff.reasonStage(failed.stage, failed.reason), sid)
        // 還在舊對話：放回離席 handoff（連同攔下的訊息），可以再 /handoff resume 或 continue
        if (failed.stage === 'clear') {
          await $.store.set(key, away)
          $.ui.toast(t().cmd.resumeClearFailed)
        }
      })
      .catch(err => $.ui.log(t().cmd.resumeFailedLog(String(err))))
      .finally(() => { rt.busy = false })
  })
  return { text: `${t().cmd.resuming}` }
}

// 重新送出沒送達的 handoff：只用這個 process 自己的紀錄，不碰其他 session 的 pendingSubmit；不 /clear
async function resend($: EngineInterface) {
  let text: string | undefined
  let key: string | undefined
  if (rt.myPending) {
    key = pendingKey(rt.myPending.sid)
    const stored = await $.store.get(key)
    text = typeof stored === 'string' ? stored : undefined
  }
  if (text === undefined && rt.lastHandoff) {
    text = `${tag} ${t().cmd.resendIntro}

${rt.lastHandoff.text}`
  }
  if (text === undefined) return { text: `${t().cmd.nothingToResend}` }
  const body = text
  $.clock.after(0, () => {
    void submitText($, body)
      .then(async () => {
        if (key !== undefined) await $.store.delete(key)
        rt.myPending = undefined
      })
      .catch(err => $.ui.log(t().cmd.resendFailed(String(err))))
  })
  return { text: `${t().cmd.resending}` }
}

async function keepOld($: EngineInterface) {
  const { key, away } = await loadAway($)
  if (away === undefined) return { text: `${t().cmd.noAway}` }
  await stat($, 'away.continue')
  const msg = away.held
  if (msg === undefined) {
    await $.store.delete(key)
    return { text: `${t().cmd.discarded}` }
  }
  // 送出成功才刪離席紀錄：送出被別的 hook drop 或拋錯時，被攔下的訊息還留在 store，可以再 continue 一次
  // （先刪再送的話，失敗後訊息就永遠消失；與 resend 的做法一致）
  $.clock.after(0, () => {
    void submitText($, msg)
      .then(() => $.store.delete(key))
      .catch(err => $.ui.log(t().cmd.sendHeldFailed(String(err))))
  })
  return { text: `${t().cmd.discardedSend}` }
}
