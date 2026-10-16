// 本機改版：交接內容改由真的回合執行 save-progress skill 寫成交接紀錄檔，不用 fork 摘要（純函式與常數，不碰 $；流程在 register.ts）
import type { TurnCompleteInput } from 'claude-code'
import { tag } from './notes'
import { isAbs, slash } from './paths'
import type { Away } from './records'

/** 送給 model 的存檔 prompt 帶這個標記，turn.start 靠它（加上每次嘗試的識別碼）認出存檔回合 */
export const SAVE_MARK = '[ctx-handoff:save]'
/** 存檔 prompt 要求 model 在回覆最後一行回報交接紀錄路徑的固定格式；只認回覆中最後一個 */
const FILE_LINE = /^HANDOFF_FILE:\s*`?([^`\n]+?)`?\s*$/gm
/** 一分鐘的毫秒數（訊息中換算分鐘用） */
export const MS_PER_MIN = 60_000
/** 存檔 prompt 送出後超過這麼久仍沒有被 turn.start 認出，就視為遺失並結束這次交接（計時器，避免交接中一直攔訊息） */
export const SAVE_LOST_MS = 10 * MS_PER_MIN
/** 連續存檔回合失敗次數（含 prompt 送出失敗、遺失、中斷、驗證不過、記錄寫入失敗），驗證通過即歸零；達這個次數就暫停門檻自動交接 */
export const MAX_SAVE_FAILURES = 2

/** 存檔回合的觸發原因：門檻（present）、/handoff now（manual）、離席（away） */
export type SaveKind = 'present' | 'manual' | 'away'

/** 進行中的存檔回合 */
export type Saving = {
  /** 觸發原因 */
  kind: SaveKind
  /** 這次嘗試的識別碼：寫進 prompt，逾時後舊嘗試的回合不會被下一次嘗試誤認 */
  attempt: string
  /** 發起這次嘗試的 session id；turn.start 只認同一個 session 的回合 */
  sessionId: string
  /** 送出存檔 prompt 前的時間（$.clock.now() 毫秒），驗證交接紀錄 mtime 用 */
  startedAt: number
  /** turn.start 認出這次嘗試後記下的回合 id；尚未認出時為 undefined */
  turnId?: string
  /** 存檔回合結束（或遺失）時呼叫：帶該回合的 turn.complete 輸入，遺失時為 undefined */
  settle: (e: TurnCompleteInput | undefined) => void
}

/**
 * 每次存檔嘗試寫進 prompt 的識別標記。
 * @param attempt 這次嘗試的識別碼
 * @returns 帶識別碼的標記（含右括號，識別碼互為前綴時也不會誤中）
 */
export const attemptTag = (attempt: string) => `[ctx-handoff:attempt:${attempt}]`

/**
 * 判斷是否已因連續存檔失敗而暫停門檻自動交接。
 * @param failures 連續存檔失敗次數
 * @returns 達上限時為 true
 */
export const isPausedBy = (failures: number) => failures >= MAX_SAVE_FAILURES

/**
 * 組存檔回合的 prompt：要求 model 跑 save-progress 並回報交接紀錄路徑。
 * 開頭是 tag，整理（distill）才不會把它當成使用者自己說的話。
 * @param kind 觸發原因
 * @param tokens 觸發當下的 context token 數；讀不到時為 null
 * @param attempt 這次嘗試的識別碼
 * @returns 送給 model 的 prompt 文字
 */
export function savePrompt(kind: SaveKind, tokens: number | null, attempt: string) {
  // STEP 01: 依觸發原因說明為什麼要交接
  /** 交接原因，寫進 prompt 開頭 */
  const why = kind === 'manual' ? '使用者執行 /handoff now'
    : kind === 'away' ? '使用者離席已久，舊對話快取即將過期'
    : `context 已達 ${tokens ?? '?'} tokens`
  // STEP 02: 組出帶標記與識別碼、要求回報 HANDOFF_FILE 的 prompt
  return [
    `${tag} ${SAVE_MARK} ${attemptTag(attempt)} ${why}，即將交接給新對話。`,
    '請執行 save-progress skill 存檔交接紀錄，不要做其他工作。',
    '完成後，回覆的最後一行只寫：HANDOFF_FILE: <交接紀錄的絕對路徑>',
  ].join('\n')
}

/**
 * 從存檔回合的回覆取出交接紀錄路徑。
 * @param answer 該回合 model 最後的可見文字
 * @returns 絕對路徑；沒有或不是絕對路徑時為 undefined
 */
export function parseFile(answer: string) {
  // STEP 01: 取回覆中最後一個 HANDOFF_FILE 行
  /** 回覆中最後一個 HANDOFF_FILE 行的路徑 */
  const file = [...answer.matchAll(FILE_LINE)].at(-1)?.[1]?.trim()
  // STEP 02: 只收絕對路徑
  if (file === undefined || !isAbs(slash(file))) {
    return undefined
  }
  return file
}

/**
 * 檢查 store 裡的離席紀錄形狀：要有字串 file（交接紀錄路徑），held 有的話要是字串。
 * 上游 0.5–0.7 的 { handoff }（fork 摘要）或其他壞資料回 undefined，呼叫端當成沒有並刪掉，不會送出 "undefined"。
 * @param v store 讀到的值
 * @returns 合格的離席紀錄；不合格時為 undefined
 */
export function parseAway(v: unknown): Away | undefined {
  // STEP 01: 要是物件且有非空字串 file
  if (typeof v !== 'object' || v === null) {
    return undefined
  }
  /** 待檢查的紀錄 */
  const r = v as { file?: unknown; held?: unknown }
  if (typeof r.file !== 'string' || r.file.trim() === '') {
    return undefined
  }
  // STEP 02: held 只能是字串或沒有
  if (r.held !== undefined && typeof r.held !== 'string') {
    return undefined
  }
  return r.held === undefined ? { file: r.file } : { file: r.file, held: r.held }
}

/**
 * 從格式不符的離席紀錄救出使用者被攔下的訊息文字（舊格式 { handoff, held } 也有），
 * 讓呼叫端捨棄紀錄時能告知使用者，不讓他的訊息無聲消失。
 * @param v store 讀到的值
 * @returns 非空字串的 held；沒有時為 undefined
 */
export function strandedHeld(v: unknown): string | undefined {
  // STEP 01: 要是物件且 held 是非空字串
  if (typeof v !== 'object' || v === null) {
    return undefined
  }
  /** held 欄位的值 */
  const held = (v as { held?: unknown }).held
  return typeof held === 'string' && held.trim() !== '' ? held : undefined
}
