/**
 * review-band 的型別契約（自成一體：引擎要求契約檔不得 import 其他檔）。
 * PendingReview／PendingReviewListing 同時是 scripts/list-pending-review.ts（產生端）的輸出契約，
 * 該腳本以 type-only import 引用本檔，兩端共用這一份定義。
 */

/** 單一未逾期 marker 的顯示資料；閘門照樣會擋的格式不完整 marker 也在此列，缺的欄位為 null 並列入 missing */
export type PendingReview = {
  /** marker 檔名 */
  file: string
  /** repo 資料夾名稱；repoRoot 缺漏時為 null */
  repo: string | null
  /** repo 根目錄絕對路徑；缺漏時為 null */
  repoRoot: string | null
  /** commit hash 前 7 碼；缺漏時為 null */
  commit: string | null
  /** Tier；缺漏或非數字時為 null */
  tier: number | null
  /** review 引擎；舊 marker 無此欄位時依 LEGACY_MARKER_ENGINE 推導 */
  engine: string
  /** 應跑的面向數；舊 marker 無此欄位時依 aspectsForTier 推導，tier 也缺時為 null */
  expectedAspects: number | null
  /** 建立時間（epoch ms）；經過時間由顯示端即時計算 */
  createdAt: number
  /** 觸發 marker 的 session id */
  sessionId: string | null
  /** 缺漏或型別不符的欄位名稱（閘門不檢查這些欄位，照樣會擋） */
  missing: string[]
}

/** list-pending-review.ts 的完整輸出 */
export type PendingReviewListing = {
  /** 未逾期的 marker（含格式不完整者） */
  markers: PendingReview[]
  /** 無法解析的 marker 檔名（閘門的 readMarkerRaw 同樣回 null，視為無 marker 放行） */
  invalid: string[]
}

/** band 顯示用的快照：讀取成功時帶 list-pending-review 的輸出，失敗時帶原因；沒有東西可顯示時整個快照為 null */
export type Snapshot =
  | ({
      /** 讀取成功 */
      ok: true
    } & PendingReviewListing)
  | {
      /** 讀取失敗 */
      ok: false
      /** 失敗原因 */
      error: string
    }

declare module 'claude-code' {
  interface PluginState {
    'review-band': {
      /** 最近一次讀到的快照；沒有任何要顯示的內容時為 null（band 不佔位） */
      snapshot: Snapshot | null
    }
  }
}
