/**
 * commit-review 的執行引擎決策與 skill 呼叫字串建構。
 *
 * 消費端（三處，皆為「指派 commit-review skill」的字串產生點）：
 * - scripts/post-commit-review.ts（PostToolUse：commit 後以 systemMessage 指派）
 * - hooks/stop-review-guard.ts（Stop：block 回合結束時以指令級注入指派，共兩處文案）
 *
 * 抽在此處的兩個理由：
 * 1. `Skill(commit-review) args: "..."` 的字串原本在上述三處各有一份 inline 複製，改 args 格式
 *    （例如本次新增 engine）必須三處同步改，漏一處就會有路徑走到舊行為且不會報錯
 *    （CLAUDE.md EXTRACT-SHARED-HELPER）。
 * 2. engine 的決策必須「一次決定、全程一致」：由 post-commit hook 在上鎖當下探測並寫入 marker，
 *    Stop gate 之後直接讀 marker，不重新探測。否則同一輪 review 可能因 codex 中途可用性變化
 *    而被指派成兩種引擎。這與 expectedAspects「把政策釘在上鎖時點」是同一個設計。
 */
import { execFileSync } from 'child_process';

/** 可用的 review 執行引擎 */
export type ReviewEngine = 'codex' | 'agent';

/**
 * 預設引擎。codex 路徑的結果以 schema 落檔、只把彙整帶進主 session context，
 * 面向失敗也是機械判定，故列為預設；agent 路徑保留為 fallback 與人工覆寫選項。
 */
export const DEFAULT_ENGINE: ReviewEngine = 'codex';

/**
 * 舊 marker（本功能上線前建立、無 engine 欄位）的引擎。
 * 取 agent 是還原這些 marker 建立當下的實際行為，不是「不知道就給個預設值」——
 * 它們是在 agent-only 時代上鎖的，該輪 review 本來就該走 agent 路徑。
 * marker 最多存活 MARKER_MAX_AGE_MS（4 小時），此路徑只在升級後的過渡期出現。
 */
export const LEGACY_MARKER_ENGINE: ReviewEngine = 'agent';

/** 人工覆寫用的環境變數名稱；設為 agent 或 codex 即跳過自動探測 */
export const ENGINE_ENV_VAR = 'CLAUDE_COMMIT_REVIEW_ENGINE';

/** codex 可用性探測的逾時（毫秒）。hook 在 commit 後同步執行，不能久等 */
const PROBE_TIMEOUT_MS = 5_000;

/** 引擎決策結果 */
export interface EngineDecision {
  /** 決定使用的引擎 */
  engine: ReviewEngine;
  /**
   * 決策理由。**只在非預設路徑（覆寫或降級）時有值**，供 hook 訊息如實告知使用者
   * 「這輪為什麼不是 codex」；走預設且探測通過時為 null，不產生噪音。
   */
  reason: string | null;
}

/**
 * 探測 codex CLI 是否真的可執行。
 *
 * 刻意執行 `codex --version` 而非只檢查 binary 是否存在：實測踩過 `which codex` 找得到、
 * 執行卻 ENOENT 的情況——npm 的 @openai/codex 是 JS wrapper，真正的執行檔在 vendor 目錄下，
 * 該檔案損壞（實測曾變成空目錄）時 wrapper 仍在 PATH 上，只有真的跑一次才知道壞了。
 * 「檔案存在」涵蓋不到「能執行」這個要判定的事實。
 *
 * @returns 可用時 reason 為 null；不可用時 reason 為精簡過的錯誤描述
 */
export function probeCodex(): { available: boolean; reason: string | null } {
  try {
    execFileSync('codex', ['--version'], { timeout: PROBE_TIMEOUT_MS, stdio: 'pipe' });
    return { available: true, reason: null };
  } catch (error) {
    // STEP 01: 取錯誤訊息首行——完整 stack 對 systemMessage 太長，且首行已足夠辨識成因
    const message = error instanceof Error ? error.message.split('\n')[0] : String(error);
    return { available: false, reason: message };
  }
}

/**
 * 決定本次 commit 的 review 引擎。
 *
 * 順序：環境變數覆寫 → 探測 codex → 探測失敗降級為 agent。
 * **降級一律在 reason 說明原因**，不靜默改走另一條路徑——使用者若不知道自己這輪跑的是
 * agent 而非 codex，就無從判斷「為什麼這次比較慢」或「為什麼結果沒落檔」。
 *
 * @returns 引擎與（非預設路徑時的）理由
 */
export function resolveEngine(): EngineDecision {
  // STEP 01: 環境變數覆寫優先，合法值（agent/codex）直接採用
  const override = process.env[ENGINE_ENV_VAR];
  if (override === 'agent' || override === 'codex') {
    return { engine: override, reason: `${ENGINE_ENV_VAR}=${override}（人工指定）` };
  }
  // 非法值視同未設定，繼續走 STEP 02 探測——「忽略」指的是不採用這個值本身，
  // 不是連探測都跳過直接給預設值；否則打錯字又剛好 codex 不可用時，會指派一個
  // 其實不可執行的引擎，而不是照原本無覆寫時該有的降級流程走到 agent。
  /** 非法覆寫值的說明；未設定或合法時為空字串，併入最終 reason 供使用者知道打錯了 */
  const invalidOverrideNote =
    override !== undefined && override !== ''
      ? `${ENGINE_ENV_VAR} 的值「${override}」非法（僅接受 agent / codex），已忽略；`
      : '';

  // STEP 02: 探測 codex，不可用則降級為 agent 並帶上實際錯誤
  const probe = probeCodex();
  if (!probe.available) {
    return { engine: 'agent', reason: `${invalidOverrideNote}codex 不可用，本次退回 agent 路徑：${probe.reason}` };
  }

  return {
    engine: DEFAULT_ENGINE,
    reason: invalidOverrideNote ? `${invalidOverrideNote}codex 探測可用，採用預設引擎` : null,
  };
}

/**
 * 組出指派 commit-review skill 的呼叫字串。
 * 三個消費端共用同一份，args 格式異動只需改這裡。
 *
 * @param tier 判定出的 Tier
 * @param target 審查目標 commit ref
 * @param engine 本輪使用的引擎
 * @returns 形如 `Skill(commit-review) args: "tier=2 target=HEAD engine=codex"` 的字串
 */
export function buildSkillInvocation(tier: number, target: string, engine: ReviewEngine): string {
  return `Skill(commit-review) args: "tier=${tier} target=${target} engine=${engine}"`;
}
