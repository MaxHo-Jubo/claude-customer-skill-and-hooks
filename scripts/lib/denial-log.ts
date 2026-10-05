/**
 * guard 擋下工具呼叫時的紀錄（唯一定義紀錄格式的地方）。
 *
 * 被 PreToolUse guard 擋下的呼叫不會觸發 PostToolUseFailure，ERRORS.jsonl 記不到；
 * TS guard 在送出 deny 前呼叫 tryLogDenial()，bash guard 走 scripts/log-denial.ts CLI（內部呼叫 logDenial()）。
 * 紀錄寫到 ~/.claude/.learnings/DENIALS.jsonl（與 ERRORS.jsonl 分開，避免灌大錯誤統計）。
 *
 * 記錄失敗的兩條出口（都不影響 deny 本身）：
 * - 附註隨 deny 原因送給 model（當下可見）
 * - 另寫一筆 `context: "hook:denial-log"` 到 ERRORS.jsonl（事後可查，讓 DENIALS 的「0 筆」分得出「沒擋過」與「記錄壞了」）
 */
import { appendFileSync, mkdirSync } from 'fs';
import { basename, dirname, join } from 'path';

/** 單筆紀錄裡命令／路徑摘錄的最大字數 */
const TARGET_MAX = 300;
/** 單筆紀錄裡擋下原因的最大字數 */
const REASON_MAX = 500;
/** 遮罩後的替代字串 */
const MASK = '***MASKED***';
/**
 * 寫入前要遮罩的憑證樣式（與 rules/common/security.md pre-commit-scan 同一組）：
 * 連線字串內嵌密碼、GitHub token、OpenAI 類 key、Google API key、PEM 私鑰標頭
 */
const SECRET_PATTERNS: readonly RegExp[] = [
  /(:\/\/[^/:@\s]+:)[^@/\s]+@/g,
  /ghp_[A-Za-z0-9]{30,}/g,
  /github_pat_[A-Za-z0-9_]{30,}/g,
  /sk-[A-Za-z0-9_-]{20,}/g,
  /AIza[0-9A-Za-z_-]{30,}/g,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/g,
];

/** guard 傳入的擋下資訊（欄位名沿用 PreToolUse hook 輸入） */
export interface DenialInput {
  /** guard 名稱（如 big-read-guard） */
  guard: string;
  /** 被擋下的工具名稱 */
  tool_name: string;
  /** 被擋下的工具參數；只取 file_path（Read/Write/Edit）或 command（Bash）當 target，其餘欄位（如 content）不記錄 */
  tool_input?: { file_path?: string; command?: string };
  /** 擋下原因（即 permissionDecisionReason） */
  reason: string;
  /** session id */
  session_id?: string;
  /** hook 輸入的工作目錄 */
  cwd?: string;
}

/** DENIALS.jsonl 的單行格式（weekly-review STEP 06 依 guard／cwd_name／target 統計） */
export interface DenialRow {
  /** 寫入時間（ISO 8601） */
  ts: string;
  /** 紀錄種類，固定 denied */
  kind: 'denied';
  /** guard 名稱 */
  guard: string;
  /** 被擋下的工具名稱 */
  tool: string;
  /** 被擋下的目標（檔案路徑或指令，已遮罩憑證、截斷） */
  target: string;
  /** session 工作目錄的資料夾名稱（不一定是目標 repo，例如 `git -C <repo>` 或讀別的 repo 的檔案） */
  cwd_name: string | null;
  /** session id */
  session: string | null;
  /** 擋下原因（已截斷） */
  reason: string;
}

/**
 * 遮罩字串中的憑證。
 * @param text - 原始字串
 * @returns 遮罩後字串
 */
function maskSecrets(text: string): string {
  return SECRET_PATTERNS.reduce((s, re) => s.replace(re, (m, prefix?: string) => (typeof prefix === 'string' ? `${prefix}${MASK}@` : MASK)), text);
}

/**
 * 取得 ~/.claude/.learnings 底下的紀錄檔路徑。
 * @param name - 檔名
 * @returns 紀錄檔絕對路徑
 */
function learningsPath(name: string): string {
  // STEP 01: HOME 未設定就無法定位紀錄檔，直接拋錯由呼叫端回報
  /** 使用者家目錄 */
  const home = process.env.HOME;
  if (!home) {
    throw new Error('HOME 未設定，無法定位 ~/.claude/.learnings');
  }
  return join(home, '.claude', '.learnings', name);
}

/**
 * 附加一筆擋下紀錄；輸入不合法或寫入失敗直接拋錯（由呼叫端決定如何回報，不得影響 deny 本身）。
 * @param input - guard 傳入的擋下資訊（CLI 路徑下來自 JSON.parse，型別未經保證，故逐欄驗證）
 * @returns void
 */
export function logDenial(input: DenialInput): void {
  // STEP 01: 驗證必要欄位型別，不符是呼叫端的 bug
  for (const key of ['guard', 'tool_name', 'reason'] as const) {
    if (typeof input?.[key] !== 'string' || input[key] === '') {
      throw new Error(`logDenial 的 ${key} 必須是非空字串`);
    }
  }
  // STEP 02: 組出紀錄（target 遮罩憑證後截斷）
  /** 被擋下的目標：有 file_path 取路徑（Read/Write/Edit），否則取 command（Bash） */
  const target = input.tool_input?.file_path ?? input.tool_input?.command ?? '';
  /** 單行紀錄 */
  const row: DenialRow = {
    ts: new Date().toISOString(),
    kind: 'denied',
    guard: input.guard,
    tool: input.tool_name,
    target: maskSecrets(String(target)).slice(0, TARGET_MAX),
    cwd_name: typeof input.cwd === 'string' && input.cwd ? basename(input.cwd) : null,
    session: typeof input.session_id === 'string' ? input.session_id : null,
    reason: maskSecrets(input.reason).slice(0, REASON_MAX),
  };
  // STEP 03: 附加寫入
  /** DENIALS.jsonl 路徑 */
  const file = learningsPath('DENIALS.jsonl');
  mkdirSync(dirname(file), { recursive: true });
  appendFileSync(file, JSON.stringify(row) + '\n');
}

/**
 * 記錄失敗的第二條出口：另寫一筆到 ERRORS.jsonl（格式同 post_tool_error.py，weekly-review 會讀到）。
 * 這條也失敗時不再往外拋：第一條出口（deny 原因附註）已讓 model 看到，再拋只會讓 guard 本身失效。
 * @param guard - guard 名稱
 * @param message - 記錄失敗的原因
 * @returns void
 */
export function recordLogFailure(guard: string, message: string): void {
  try {
    appendFileSync(learningsPath('ERRORS.jsonl'), JSON.stringify({
      ts: new Date().toISOString(),
      context: 'hook:denial-log',
      tool: guard,
      exit_code: null,
      cmd: '',
      error: `擋下紀錄寫入失敗：${message}`,
    }) + '\n');
  } catch {
    // 第二條出口也失敗（通常是 HOME 或整個 .learnings 不可寫）：附註已送達 model，此處不再拋
  }
}

/**
 * 給 TS guard 用的包裝：嘗試記錄，失敗時另寫 ERRORS.jsonl，並回傳要附在 deny 原因後的附註（成功回傳空字串）。
 * 記錄失敗不得讓 guard 放行，也不得靜默。
 * @param input - guard 傳入的擋下資訊
 * @returns 失敗附註或空字串
 */
export function tryLogDenial(input: DenialInput): string {
  try {
    // STEP 01: 寫入擋下紀錄
    logDenial(input);
    return '';
  } catch (err) {
    // STEP 02: 失敗走兩條出口：ERRORS.jsonl 留痕 + 附註隨 deny 送出
    /** 失敗原因 */
    const message = err instanceof Error ? err.message : String(err);
    recordLogFailure(input?.guard || 'unknown-guard', message);
    return `\n\n（附註：擋下紀錄寫入失敗：${message}）`;
  }
}
