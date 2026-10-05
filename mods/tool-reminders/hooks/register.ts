import type { Register } from 'claude-code'

/**
 * 一個提醒類檢查：在 Write/Edit 成功後執行。
 * 腳本協定：從 stdin 讀 `{ tool_name, tool_input: { file_path } }`；
 * exit 0 = 檢查完成（stdout 非空即為要給 model 的提醒，空則無提醒），exit ≠ 0 = 檢查失敗（原因寫 stderr）。
 * 腳本不得用 exit 0 表示失敗，否則 mod 無從分辨「沒有提醒」與「檢查壞掉」。
 */
interface ReminderCheck {
  /** 檢查名稱，出現在失敗訊息中 */
  readonly name: string
  /** 相對於 HOME 的腳本路徑 */
  readonly script: string
  /** 傳給腳本的額外參數 */
  readonly args?: readonly string[]
}

/**
 * 要執行的檢查清單。檢查邏輯（含路徑篩選）全部留在腳本內，mod 只負責轉接，
 * 避免同一份篩選條件在 mod 與腳本各寫一次而分歧。
 */
const CHECKS: readonly ReminderCheck[] = [
  { name: 'inventory-drift', script: '.claude/scripts/inventory-drift-detector.ts' },
  { name: 'spec-skeleton', script: '.claude/scripts/spec-section-validator.ts', args: ['--warn-only'] },
]

/** 單一檢查腳本的逾時（毫秒）；腳本只讀本機檔案，正常在 1 秒內結束 */
const CHECK_TIMEOUT_MS = 10_000

/** 失敗原因帶進 context 與 transcript 時，stderr／stdout 摘錄的最大字數 */
const OUTPUT_EXCERPT_MAX = 200

/** context 前綴，讓 model 辨識提醒來源 */
const PREFIX = '[tool-reminders]'

/** 單一檢查的執行結果：成功時帶提醒文字（可能為空），失敗時帶原因 */
type CheckOutcome =
  | {
      /** 檢查完成 */
      ok: true
      /** 提醒文字（已 trim），空字串表示無提醒 */
      text: string
    }
  | {
      /** 檢查失敗 */
      ok: false
      /** 失敗原因 */
      reason: string
    }

/**
 * 註冊 Write/Edit 的 tool.call hook：工具成功後平行執行 CHECKS，把非空輸出附加到 context。
 * 檢查失敗（含 HOME 未設定）不影響工具結果，但會在 transcript 留紀錄、跳 toast，並告知 model 該檢查結果未知。
 * @param on - 註冊 hook 的函式
 */
export const register: Register = on => {
  on('tool.call', { tool: ['Write', 'Edit'] }, async ($, e, next) => {
    // STEP 01: 先讓工具執行；被拒或出錯時不做檢查
    /** 工具（與下層 plugin）的執行結果 */
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError === true) {
      return ran
    }

    // STEP 02: 組出腳本的 stdin（PostToolUse 輸入的子集，只含 tool_name 與 tool_input.file_path；新增檢查若需其他欄位須先擴充此處）並平行執行所有檢查
    /** 使用者家目錄，用來組出腳本絕對路徑 */
    const home = await $.env.get('HOME')
    /** 送給每支腳本的 stdin */
    const stdin = JSON.stringify({ tool_name: e.tool, tool_input: { file_path: e.file_path } })

    /**
     * 執行單一檢查腳本。
     * @param check - 要執行的檢查
     * @returns 成功時的 stdout（已 trim），或失敗原因
     */
    const runCheck = async (check: ReminderCheck): Promise<CheckOutcome> => {
      // STEP 01: 沒有 HOME 就組不出腳本路徑，視為檢查失敗走同一個出口
      if (!home) {
        return { ok: false, reason: 'HOME 未設定' }
      }
      try {
        // STEP 02: 執行腳本
        /** 子行程的命令列 */
        const argv = ['bun', `${home}/${check.script}`, ...(check.args ?? [])]
        /** 子行程結果 */
        const r = await $.process.run(argv, { stdin, timeoutMs: CHECK_TIMEOUT_MS })
        // STEP 03: 依腳本協定判斷；stderr 為空時改帶 stdout 摘錄，避免原因只剩 exit code
        if (r.exitCode !== 0) {
          /** 失敗時可供診斷的輸出摘錄 */
          const detail = (r.stderr.trim() || r.stdout.trim()).slice(0, OUTPUT_EXCERPT_MAX)
          return { ok: false, reason: `exit ${r.exitCode}：${detail}` }
        }
        return { ok: true, text: r.stdout.trim() }
      } catch (err) {
        // STEP 04: 逾時、bun 不存在等子行程層級錯誤
        return { ok: false, reason: err instanceof Error ? err.message : String(err) }
      }
    }
    /** 每個檢查的名稱與結果 */
    const outcomes = await Promise.all(CHECKS.map(async c => ({ name: c.name, o: await runCheck(c) })))

    // STEP 03: 分類結果；失敗的檢查留紀錄並告知 model，不可靜默
    /** 要附加到工具結果的 context */
    const context: string[] = []
    outcomes.forEach(({ name, o }) => {
      if (!o.ok) {
        $.ui.log(`${PREFIX} ${name} 檢查失敗：${o.reason}`)
        $.ui.toast(`${PREFIX} ${name} 檢查失敗`)
        context.push(`${PREFIX} ${name} 檢查執行失敗，本次結果未知：${o.reason}`)
        return
      }
      if (o.text) {
        context.push(`${PREFIX} ${name}\n${o.text}`)
      }
    })

    // STEP 04: 有提醒才附加 context（保留下層既有的 context），否則原樣回傳
    if (context.length === 0) {
      return ran
    }
    return { ...ran, context: [...(ran.context ?? []), ...context] }
  })
}
