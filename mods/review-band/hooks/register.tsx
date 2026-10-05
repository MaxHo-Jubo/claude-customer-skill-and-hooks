import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { PendingReview, PendingReviewListing, Snapshot } from '../types'

/** 相對於 HOME 的 marker 目錄（只用來判斷要不要 spawn；有效性由腳本判斷） */
const MARKER_DIR = '.claude/state/pending-review'

/** 相對於 HOME 的唯讀列舉腳本（marker 有效性與閘門共用 scripts/lib/review-marker.ts） */
const SCRIPT = '.claude/scripts/list-pending-review.ts'

/** 列舉腳本的逾時（毫秒）；只讀本機小檔，正常在 1 秒內結束 */
const SCRIPT_TIMEOUT_MS = 10_000

/** 讀取失敗時帶進 band 的 stderr 摘錄最大字數 */
const ERROR_EXCERPT_MAX = 160

/** 一分鐘（毫秒），用來顯示 marker 已存在多久 */
const MINUTE_MS = 60_000

/** band 讀取的快照 */
const snapshot = atom({ plugin: 'review-band', key: 'snapshot' } as const, null)

/**
 * 驗證列舉腳本的輸出形狀；不符就拋錯，讓呼叫端走「讀取失敗」出口，而不是把殘缺物件交給 render。
 * @param raw - JSON.parse 後的腳本輸出
 * @returns 驗證過的輸出
 */
const parseListing = (raw: unknown): PendingReviewListing => {
  // STEP 01: 外層形狀
  if (typeof raw !== 'object' || raw === null) {
    throw new Error('列舉腳本輸出不是物件')
  }
  /** 外層物件 */
  const o = raw as Record<string, unknown>
  if (!Array.isArray(o.markers) || !Array.isArray(o.invalid)) {
    throw new Error('列舉腳本輸出缺 markers／invalid 陣列')
  }
  // STEP 02: 每顆 marker 至少要有 render 用到的欄位型別
  for (const m of o.markers as Record<string, unknown>[]) {
    if (typeof m.file !== 'string' || typeof m.createdAt !== 'number' || !Array.isArray(m.missing)) {
      throw new Error('列舉腳本輸出的 marker 缺 file／createdAt／missing')
    }
  }
  return raw as PendingReviewListing
}

/**
 * 重新讀取 marker 狀態並寫回快照。
 * 所有讀取步驟（HOME、目錄列舉、腳本、輸出驗證）都在同一個 try 裡：任何一步失敗都寫入 ok:false 快照，band 顯示原因，
 * 不會停在舊快照，也不會被當成沒有 marker。沒有任何要顯示的內容時快照為 null。
 * @param $ - 引擎介面
 * @returns 完成時 resolve
 */
const refresh = async ($: EngineInterface): Promise<void> => {
  try {
    // STEP 01: 組出路徑；沒有 HOME 屬於讀取失敗
    /** 使用者家目錄 */
    const home = await $.env.get('HOME')
    if (!home) {
      throw new Error('HOME 未設定')
    }
    // STEP 02: 沒有任何 marker 檔就不 spawn
    /** marker 目錄絕對路徑 */
    const dir = `${home}/${MARKER_DIR}`
    /** 目錄內是否有 marker 檔 */
    const hasMarker = (await $.fs.exists(dir)) && (await $.fs.list(dir)).some(f => f.name.endsWith('.json'))
    if (!hasMarker) {
      await update($, snapshot, () => null)
      return
    }
    // STEP 03: 執行唯讀列舉腳本並驗證輸出
    /** 腳本結果 */
    const r = await $.process.run(['bun', `${home}/${SCRIPT}`], { timeoutMs: SCRIPT_TIMEOUT_MS })
    if (r.exitCode !== 0) {
      throw new Error(`exit ${r.exitCode}：${(r.stderr.trim() || r.stdout.trim()).slice(0, ERROR_EXCERPT_MAX)}`)
    }
    /** 驗證過的腳本輸出 */
    const listing = parseListing(JSON.parse(r.stdout))
    // STEP 04: 有東西可顯示才寫快照，否則清空
    /** 新快照 */
    const next: Snapshot | null = listing.markers.length > 0 || listing.invalid.length > 0 ? { ok: true, ...listing } : null
    await update($, snapshot, () => next)
  } catch (err) {
    // STEP 05: 任何一步失敗都走 ok:false，band 會顯示原因
    /** 失敗原因 */
    const reason = err instanceof Error ? err.message : String(err)
    await update($, snapshot, (): Snapshot => ({ ok: false, error: reason }))
  }
}

/**
 * 組出單顆 marker 的顯示文字；缺的欄位以「?」顯示並附註缺漏，不用預設值掩蓋。
 * @param m - marker 顯示資料
 * @param me - 本 session id
 * @param now - 現在時間（epoch ms）
 * @returns 顯示文字
 */
const describeMarker = (m: PendingReview, me: string, now: number): string => {
  // STEP 01: 主體
  /** 經過分鐘數 */
  const ageMin = Math.max(0, Math.floor((now - m.createdAt) / MINUTE_MS))
  /** 主體文字 */
  const main = `🔒 pending-review：${m.repo ?? '?'} Tier ${m.tier ?? '?'}（${m.commit ?? '?'}）· ${m.engine} · 應跑 ${m.expectedAspects ?? '?'} 個面向 · ${ageMin} 分鐘前`
  // STEP 02: 附註
  /** 本 session 標記 */
  const mine = m.sessionId === me ? ' · 本 session' : ''
  /** 格式不完整附註 */
  const incomplete = m.missing.length > 0 ? ` · ⚠️ 格式不完整（缺 ${m.missing.join(', ')}，閘門仍會擋）` : ''
  return main + mine + incomplete
}

/**
 * 註冊 review-band：在 session 開始、每回合結束、每次 Bash 結束後刷新（commit 與解鎖都走 Bash），
 * 並在 AbovePrompt 畫出有效 marker；沒有 marker 時不佔位。只讀，不影響閘門與 commit-review。
 * @param on - 註冊 hook 的函式
 * @returns void
 */
export const register: Register = on => {
  /**
   * session 開始時刷新，讓開場就看得到既有的 marker。
   * @returns 下層結果
   */
  on('session.start', async ($, e, next) => {
    await refresh($)
    return next(e)
  })

  /**
   * 每回合結束時刷新。
   * @returns 下層結果
   */
  on('turn.complete', async ($, e, next) => {
    await refresh($)
    return next(e)
  })

  /**
   * Bash 執行完才刷新（commit 上鎖與解鎖都在指令執行之後才寫入 marker）。
   * @returns 下層的工具結果（原樣回傳）
   */
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    // STEP 01: 先讓工具執行
    /** 下層的工具結果 */
    const ran = await next(e)
    // STEP 02: 刷新後原樣回傳
    await refresh($)
    return ran
  })

  /**
   * 畫出 band；沒有快照或有 survey 時讓位。
   * @returns band 的元素樹，或下層結果
   */
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // STEP 01: 讓位給 survey；沒有快照就不畫
    /** 目前快照 */
    const s = await read($, snapshot)
    if (e.props.hasSurvey || s === null) {
      return next(e)
    }
    /** 依目前畫面元件表解析出的元件 */
    const { Box, Text } = $.ui.resolve(e)
    // STEP 02: 讀取失敗
    if (!s.ok) {
      return (
        <Box>
          <Text key="error" color="red">
            pending-review 狀態讀取失敗：{s.error}
          </Text>
        </Box>
      )
    }
    // STEP 03: 每顆 marker 與無法解析的檔
    /** 本 session id，用來標記哪顆是自己這輪的 */
    const me = await $.session.id()
    /** 現在時間（epoch ms），用來即時計算 marker 已存在多久 */
    const now = await $.clock.now()
    return (
      <Box flexDirection="column">
        {s.markers.map(m => (
          <Text key={`m-${m.file}`} color="yellow">
            {describeMarker(m, me, now)}
          </Text>
        ))}
        {s.invalid.length > 0 ? (
          <Text key="invalid" color="yellow">
            ⚠️ {s.invalid.length} 個 marker 檔無法解析（閘門視為無 marker 放行）：{s.invalid.join(', ')}
          </Text>
        ) : null}
      </Box>
    )
  })
}
