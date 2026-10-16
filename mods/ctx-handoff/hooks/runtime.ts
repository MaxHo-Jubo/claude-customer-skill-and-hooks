// 這個 process 內 register.ts 用的可變狀態（熱重載會清掉；要接得上的放 $.state）。集中成一個物件，不碰 $
import type { Timer } from 'claude-code'
import type { Change } from './notes'
import { freshWork } from './loops'
import type { Streak, Work } from './loops'
import { freshReply } from './lang'
import type { ReplyLang, ReplyState } from './lang'
import type { Saving } from './save'

export const rt = {
  idle: undefined as Timer | undefined,
  refreshes: 0,
  // 互斥：同一時間只處理一個 handoff（不攔訊息）
  busy: false,
  // 在場交接進行中（門檻或 /handoff now）：使用者訊息先攔下，交接後一併送出
  presenting: false,
  held: [] as string[],
  // 這次在場交接開始的時間（undefined＝還沒開始計時），給攔訊息的提示與等整理的上限用
  presentStartedAt: undefined as number | undefined,
  // 背景整理的差異：依 session id 暫存，跟著下一則真正送進對話的訊息帶入
  pendingNotes: new Map<string, { changes: Change[]; file: string }>(),
  // 這個 process 送出失敗、尚未送達的 handoff（舊 session id）
  myPending: undefined as { sid: string } | undefined,
  pendingToasted: false,
  // 這個 process 最近產生的 handoff，/handoff resend 沒有未送達紀錄時用
  lastHandoff: undefined as { text: string } | undefined,
  retryAfter: undefined as { turns: number; at: number } | undefined,
  // classic.Stop 的最近快照；deferral 是目前延後 handoff 的原因
  snapshot: undefined as { tasks: number; oneShot: number; recurring: number } | undefined,
  deferral: undefined as string | undefined,
  deferToasted: false,
  seenKnown: new Set<string>(),
  distilling: false,
  // 正在跑的整理結束時 resolve：交接前整理撞上它時排在它之後
  distillDone: undefined as Promise<void> | undefined,
  // 統計寫入排隊（writeStat 不丟例外，鏈不會斷）
  statQueue: Promise.resolve() as Promise<void>,
  // 上一次整理有沒有失敗（有回答但沒套用也算），給 /handoff distill 判斷
  distillFailed: false,
  // 放進專案的工具完整名稱（mcp__<plugin>__<name>），以註冊結果為準；這個 process 沒註冊就是 undefined
  // 守門的 store 鍵：工作區在 process 內不變，算一次就記住（熱重載會重算）
  guardsKeyCache: undefined as string | undefined,
  // 設定與介面語言：第一次用到時讀一次就記住（熱重載會重算）
  langReady: undefined as Promise<void> | undefined,
  // 防呆提醒：各工具最近一段連續失敗，與這一輪的改檔／驗證紀錄。熱重載會清掉，清掉只是少一次提醒
  streaks: new Map<string, Streak>(),
  work: freshWork() as Work,
  // 回覆語言提醒：目標語言快取（undefined＝還沒算；{ lang: undefined }＝不提醒）與提醒進度。熱重載會清掉，清掉只是少一次提醒
  replyTarget: undefined as { lang: ReplyLang | undefined } | undefined,
  reply: freshReply() as ReplyState,
  // 已經用 handoff 交接出去的 session（熱重載會清掉）：它的進度備忘不再提供，之後才寫完的整理也不存
  handed: new Set<string>(),
  // 本機改版：有人在 prompt 前（REPL）才做門檻自動交接與閒置刷新；-p／SDK 等無人看管的 session 不動。
  // session.start 才知道，之前一律當成無人看管（熱重載會重跑 session.start）
  interactive: false,
  // 本機改版：進行中的 save-progress 存檔回合（從送出存檔 prompt 到該回合 turn.complete 或遺失）
  saving: undefined as Saving | undefined,
  // 本機改版：連續存檔回合失敗次數（含 prompt 送出失敗、遺失、中斷、驗證不過、記錄寫入失敗），驗證通過即歸零；達 MAX_SAVE_FAILURES 暫停門檻自動交接
  saveFailures: 0,
  // 本機改版：這個 process 發起過幾次存檔嘗試，和開始時間組成每次嘗試的識別碼（熱重載歸零，開始時間仍會不同）
  saveSeq: 0,
}

// 重設程序內狀態（模組重新載入或測試重跑時）；distilling、distillFailed、presentStartedAt 沿用原本不重設的行為
export function resetRuntime() {
  rt.idle?.cancel()
  rt.idle = undefined
  rt.refreshes = 0
  rt.busy = false
  rt.presenting = false
  rt.held = []
  rt.pendingNotes.clear()
  rt.myPending = undefined
  rt.pendingToasted = false
  rt.lastHandoff = undefined
  rt.retryAfter = undefined
  rt.snapshot = undefined
  rt.deferral = undefined
  rt.deferToasted = false
  rt.seenKnown.clear()
  rt.guardsKeyCache = undefined
  rt.langReady = undefined
  rt.streaks.clear()
  rt.work = freshWork()
  rt.replyTarget = undefined
  rt.reply = freshReply()
  rt.handed.clear()
  rt.interactive = false
  rt.saving = undefined
  rt.saveFailures = 0
  rt.saveSeq = 0
}
