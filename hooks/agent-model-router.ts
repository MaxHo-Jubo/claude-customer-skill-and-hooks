#!/usr/bin/env bun
import fs from 'fs';
import os from 'os';
import path from 'path';
import { askJev, type JevAnswer, jevDisabled, logDecision, maskSecrets, readAnswer, topChoices, truncateMiddle } from '../scripts/lib/jev-client';
import { type Tier, TIER_LABELS, TIER_QUESTIONS } from '../scripts/lib/jev-questions';

/**
 * 派工模型路由 Hook（PreToolUse，matcher 應為 Agent）— Jev 版，對應 tasks/jev-trial-plan.md 掛載點 D
 *
 * 主模型派 subagent 時沒寫 `model`，子代理會繼承主 session 的模型。
 * 本 hook 用 Jev 問一題「這個任務最低需要哪一級模型」（light／small／mid／top），
 * confidence 達 ROUTE_CONF_MIN 且不是 top 時查 TIER_MODEL 得出候選 model，以 updatedInput 改寫工具輸入。
 * 只降不升由執行期判斷保證（capByParent）：從 transcript 讀出父模型（readParentModel），
 * 候選 model 在 MODEL_RANK 上必須嚴格低於父模型才填，否則不填（would_upgrade）；
 * 父模型讀不到或不在等級表內一律不填（parent_unknown），失敗方向是「不改寫」。
 * 父模型取 transcript 中「位置最新」的 assistant 記錄 model 或 identity attachment 的 modelId（兩者都看，誰在後面取誰）；
 * 尾端視窗找不到（第一回合 assistant 記錄還沒落盤）就從檔頭倍增掃描到 HEAD_MAX_BYTES 為止。
 * 已知限制：session 中途 /model 換成較便宜的模型後，新模型的 identity 或第一則 assistant 記錄落盤前，
 * 該回合的派工仍以舊模型為上限，可能填出比目前主模型貴的 model（2026-10-11 實測近 30 天 1,861 個 transcript 中 2 個 session 中途換過模型家族）。
 * 已寫 model、fork、或子代理定義檔自帶固定 model 的派工都不碰。
 *
 * 錯誤處理：
 * - Jev 呼叫失敗（逾時、HTTP 錯誤、回應缺 answers）fail-open：不輸出、exit 0，錯誤由 askJev 寫入 ~/.claude/state/jev/decisions.jsonl（與 A/B/C 一致）
 * - stdin 欄位不合法：視為不可路由，不輸出、exit 0，log skip=invalid_input
 * - 其他未預期錯誤：不輸出，寫 decisions.jsonl，stderr 印錯誤並 exit 1——PreToolUse 非 2 的非零 exit 不阻擋工具，
 *   hook-error-wrapper.sh 會記入 ~/.claude/.learnings/ERRORS.jsonl
 * kill switch：環境變數 JEV_HOOKS_DISABLED=1。
 *
 * 門檻來源：scripts/jev-eval/run-eval-d.ts 離線評估（jev-1.13.0，近 30 天主模型明寫 model 的派工）。
 * 題目、MAX_BRIEF_CHARS 或門檻改動 → 重抽資料集（extract-d-route.ts）並重跑 run-eval-d.ts。
 */

/** hook 名稱，寫入決策 log 用 */
const HOOK_NAME = 'D-route';
/** 本 hook 處理的工具名稱 */
const AGENT_TOOL = 'Agent';
/** stdin 的檔案描述元 */
const STDIN_FD = 0;
/** 未預期錯誤的 exit code：非 0、非 2（2 會阻擋工具） */
const EXIT_UNEXPECTED = 1;
/**
 * 路由的 confidence 下限：低於此值不填 model（維持繼承）。
 * 來源：run-eval-d.ts 2026-10-11（results-d-2026-10-11T15-22-38-568Z.json，n=256，評估時父模型固定視為 fable）。事先寫死的規則
 * 「路由 ≥ 20 筆且比主模型更便宜 ≤ 10% 的最低門檻」選出 0.3：路由 96.5%、更便宜 4.9%；更便宜比例在各門檻都 3.7–4.9%，提高門檻只少路由、不降風險。
 * 看完結果才找到的保守替代值 0.6：[0.3, 0.6) 區段 57 筆一致率僅 16.7–45.8%，0.6 以上 74.2% 路由、更便宜 3.7%
 */
export const ROUTE_CONF_MIN = 0.3;
/**
 * 送給 Jev 的 prompt 最大字元數（先遮罩再截斷，保留頭尾）。
 * A 截 user prompt 用 2000；brief 較長（近 30 天 p50 2,172／p90 4,554 字），取 B 長文評估驗過的級距（最長 3,876 字仍準確）。
 * 改動此值須重抽評估資料集，資料集存的是截斷後文字
 */
export const MAX_BRIEF_CHARS = 4000;
/**
 * 本 hook 的 Jev 逾時（毫秒）：共用 HOOK_TIMEOUT_MS 的 2 倍。
 * 逾時＝fail-open＝派工繼承主模型，正是本 hook 要避免的最貴結果；而派工本身動輒數分鐘，多等幾秒無感。
 * 送出文字是 A 的 2 倍，且 2026-10-11 單次冷啟動實測 2017ms 剛好超過 2000。settings.json 的 hook timeout（秒）須大於此值
 */
export const ROUTE_TIMEOUT_MS = 4000;

/** 本 hook 會填入的 model（Agent 工具的 model 參數值） */
export type RoutedModel = 'haiku' | 'sonnet' | 'opus';
/** 等級 → 要填的 model；null 表示不填（維持繼承主 session 模型） */
export const TIER_MODEL: Record<Tier, RoutedModel | null> = { light: 'haiku', small: 'sonnet', mid: 'opus', top: null };
/**
 * 模型家族由便宜到貴的等級，只降不升判斷用（capByParent）。
 * 新的模型家族要補進來；不在表內的父模型一律 parent_unknown（不改寫）
 */
export const MODEL_RANK = { haiku: 0, sonnet: 1, opus: 2, fable: 3 } as const;
/** MODEL_RANK 認得的模型家族 */
export type ModelFamily = keyof typeof MODEL_RANK;
/** 完整模型 ID（claude-<family>-…）取 family 的樣式 */
const MODEL_ID_RE = /^claude-([a-z]+)-/;
/** transcript 中非模型產生的 assistant 記錄（中斷、錯誤訊息等）的 model 值，讀父模型時跳過 */
const SYNTHETIC_MODEL = '<synthetic>';
/** 1 KiB 的位元組數 */
const KIB = 1024;
/** 讀父模型時從 transcript 尾端讀取的位元組數：找位置最新的 assistant 記錄或 identity attachment */
export const TAIL_BYTES = 512 * KIB;
/**
 * 讀父模型時從 transcript 開頭掃描的起始視窗：尾端找不到（第一回合 assistant 記錄還沒落盤）時，
 * 從這個大小起每次加倍重讀檔頭，直到找到 identity attachment 或達 HEAD_MAX_BYTES。
 * 2026-10-11 實測近 30 天 1,827 個 transcript，identity 偏移量 p50 43KB／p90 107KB／p99 505KB／最大 1.3MB，
 * 固定 64KB 單次讀取會讓 476 個（26%）的 session 第一回合判 parent_unknown
 */
export const HEAD_BYTES = 64 * KIB;
/** 檔頭倍增掃描的上限：實測最大偏移 1.3MB 的 6 倍，超過就放棄（parent_unknown，fail-safe） */
export const HEAD_MAX_BYTES = 8 * KIB * KIB;
/** transcript 行的粗篩字串：assistant 記錄 */
const ASSISTANT_MARK = '"type":"assistant"';
/** transcript 行的粗篩字串：模型 identity attachment */
const IDENTITY_MARK = '"identity"';

/** 內建、且不帶固定 model 的 subagent_type（2.1.296 binary：Explore／Plan 為 model:"inherit"） */
const BUILTIN_ROUTABLE = new Set(['general-purpose', 'claude', 'Explore', 'Plan']);
/** subagent_type 未指定（缺省或空字串）時實際使用的類型 */
const DEFAULT_TYPE = 'general-purpose';
/** fork 型派工：一律沿用主模型，model 參數會被忽略 */
const FORK_TYPE = 'fork';
/** frontmatter 中表示繼承主模型的值 */
const INHERIT_MODEL = 'inherit';
/** frontmatter 中頂層（不縮排）的 model 行；縮排的多行 description 內容不會命中 */
const MODEL_LINE_RE = /^model:[ \t]*(.*)$/m;
/** 合法的 agent／plugin 名稱：拼進路徑前檢查，避免跳出目錄 */
const NAME_RE = /^[A-Za-z0-9_.-]{1,128}$/;
/** Claude Code 設定根目錄 */
const CLAUDE_DIR = path.join(os.homedir(), '.claude');

/** 不填 model 的原因 */
export type SkipReason =
  | 'invalid_input' | 'model_set' | 'no_prompt' | 'fork' | 'no_def' | 'fixed_model'
  | 'low_conf' | 'top' | 'parent_unknown' | 'would_upgrade';
/** 呼叫 Jev 前就能判定的略過原因 */
export type PreSkipReason = Extract<SkipReason, 'model_set' | 'no_prompt' | 'fork' | 'no_def' | 'fixed_model'>;
/** 路由結果：要填的 model 與不填的原因恰有一個成立 */
export type RouteResult = { model: RoutedModel; skip: null } | { model: null; skip: SkipReason };

/** 子代理定義檔的查找位置（測試時可指向暫存目錄） */
export interface AgentDirs {
  /** 專案層 agent 目錄：<cwd>/.claude/agents/<type>.md；stdin 沒帶 cwd 時為 null */
  projectAgentsDir: string | null;
  /** 使用者層 agent 目錄：<dir>/<type>.md */
  userAgentsDir: string;
  /** plugin 安裝清單：plugin key → installPath，agent 在 <installPath>/agents/<name>.md */
  pluginsFile: string;
}

/** Agent 工具輸入中本 hook 用到的欄位；其餘欄位原樣保留在 updatedInput */
export interface AgentInput {
  /** 子代理類型；未指定為 general-purpose */
  subagent_type?: string;
  /** 主模型寫的 3-5 字摘要 */
  description: string;
  /** 派工 brief 全文 */
  prompt: string;
  /** 主模型明寫的 model；有值就不路由 */
  model?: string;
  /** 其他欄位（isolation、name 等），輸出時原樣帶回 */
  [key: string]: unknown;
}

/** installed_plugins.json 中單筆安裝紀錄用到的欄位 */
interface PluginInstall {
  /** plugin 安裝目錄；agent 定義檔在其下的 agents/ */
  installPath?: string;
}

/** Jev tier 題讀出的等級與前兩名 */
export interface TierReading {
  /** Jev 判定的等級 */
  tier: Tier;
  /** 等級的 confidence */
  conf: number;
  /** 次高等級 */
  second: string;
  /** 次高等級的機率 */
  secondP: number;
}

/** 單次路由決策：tier 讀數加上路由結果 */
export type RouteDecision = TierReading & RouteResult;

/**
 * 是否為非 null、非陣列的物件
 * @param v - 任意值
 * @returns true 表示可當成 Record 讀欄位
 */
function isRecord(v: unknown): v is Record<string, unknown> {
  // STEP 01: 排除 null 與陣列
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * 是否為缺省或字串（可選字串欄位的驗證）
 * @param v - 欄位值
 * @returns true 表示合法
 */
function isOptionalString(v: unknown): v is string | undefined {
  // STEP 01: undefined 或字串
  return v === undefined || typeof v === 'string';
}

/**
 * 取字串欄位；不是字串回 null
 * @param v - 欄位值
 * @returns 字串或 null
 */
function stringOrNull(v: unknown): string | null {
  // STEP 01: 只接受字串
  return typeof v === 'string' ? v : null;
}

/**
 * 是否為字串（filter／find 回呼）
 * @param v - 任意值
 * @returns true 表示是字串
 */
function isString(v: unknown): v is string {
  // STEP 01: 型別判斷
  return typeof v === 'string';
}

/**
 * 驗證 stdin 的 tool_input 並轉型
 * @param raw - stdin 的 tool_input 原始值
 * @returns 合法時回 AgentInput；不是物件、prompt／description 不是字串、subagent_type／model 不是字串或缺省時回 null
 */
export function parseAgentInput(raw: unknown): AgentInput | null {
  // STEP 01: 必填字串與可選字串欄位
  if (!isRecord(raw) || typeof raw.prompt !== 'string' || typeof raw.description !== 'string') {
    return null;
  }
  if (!isOptionalString(raw.subagent_type) || !isOptionalString(raw.model)) {
    return null;
  }
  // STEP 02: 欄位已驗證，轉型
  return raw as AgentInput;
}

/**
 * 依 stdin 的 cwd 組出定義檔查找位置
 * @param cwd - stdin 的 cwd；沒帶時不查專案層
 * @returns 查找位置
 */
export function dirsFor(cwd: string | null): AgentDirs {
  // STEP 01: 專案層 <cwd>/.claude/agents，使用者層與 plugin 清單在 ~/.claude 下
  return {
    projectAgentsDir: cwd ? path.join(cwd, '.claude', 'agents') : null,
    userAgentsDir: path.join(CLAUDE_DIR, 'agents'),
    pluginsFile: path.join(CLAUDE_DIR, 'plugins', 'installed_plugins.json'),
  };
}

/**
 * 子代理定義檔的 frontmatter 是否表示繼承主模型（model 缺省或為 inherit）
 * @param text - 定義檔全文
 * @returns true 表示可路由；沒有 frontmatter 或帶固定 model 回 false
 */
export function inheritsModel(text: string): boolean {
  // STEP 01: 取開頭兩個 --- 之間的內容（換行統一為 \n）；沒有 frontmatter 不是合法定義檔，不路由
  /** frontmatter 比對結果（m[1] 為兩個 --- 之間的內容） */
  const m = text.replace(/\r\n/g, '\n').match(/^---\n([\s\S]*?)\n---/);
  if (!m) {
    return false;
  }
  // STEP 02: 只抓頂層 model 行，不整段 YAML 解析——plugin 的 description 常含未加引號的冒號
  // （pr-review-toolkit:silent-failure-hunter 實測 Bun.YAML.parse 丟錯），Claude Code 本身照樣載入
  /** 頂層 model 行的比對結果 */
  const line = m[1].match(MODEL_LINE_RE);
  /** frontmatter 的 model 值（去引號；缺省為空字串） */
  const model = line ? line[1].trim().replace(/^(['"])(.*)\1$/, '$2') : '';
  return model === '' || model === INHERIT_MODEL;
}

/**
 * 是否為一串合法的安裝紀錄（陣列，元素為物件且 installPath 缺省或為字串）
 * @param v - installed_plugins.json 中某個 plugin key 的值
 * @returns true 表示格式合法
 */
function isInstallList(v: unknown): v is PluginInstall[] {
  // STEP 01: 陣列且每個元素都合法
  return Array.isArray(v) && v.every(isPluginInstall);
}

/**
 * 是否為合法的單筆安裝紀錄（every 回呼）
 * @param e - 陣列元素
 * @returns true 表示是物件且 installPath 缺省或為字串
 */
function isPluginInstall(e: unknown): e is PluginInstall {
  // STEP 01: 非 null 物件，installPath 可選字串
  return isRecord(e) && isOptionalString(e.installPath);
}

/**
 * 讀 installed_plugins.json 並驗證格式；格式不符直接丟錯（不默默當成沒有 plugin）
 * @param file - 檔案路徑
 * @returns plugin key（name@marketplace）→ 安裝紀錄
 */
function readInstalledPlugins(file: string): Record<string, PluginInstall[]> {
  // STEP 01: 頂層必須是物件；沒有 plugins 欄位代表沒有安裝任何 plugin
  /** installed_plugins.json 解析結果（驗證前） */
  const raw: unknown = JSON.parse(fs.readFileSync(file, 'utf-8'));
  if (!isRecord(raw)) {
    throw new Error(`${file} 不是 JSON 物件`);
  }
  if (raw.plugins === undefined) {
    return {};
  }
  // STEP 02: plugins 為物件，每個值都是安裝紀錄陣列
  if (!isRecord(raw.plugins) || !Object.values(raw.plugins).every(isInstallList)) {
    throw new Error(`${file} 的 plugins 欄位格式不符`);
  }
  return raw.plugins as Record<string, PluginInstall[]>;
}

/**
 * 檔案是否存在（filter 回呼；不直接傳 fs.existsSync，避免陣列索引被當成第二個參數）
 * @param file - 檔案路徑
 * @returns true 表示存在
 */
function fileExists(file: string): boolean {
  // STEP 01: 查檔
  return fs.existsSync(file);
}

/**
 * 安裝紀錄是否帶 installPath（filter 回呼）
 * @param e - 安裝紀錄
 * @returns true 表示有非空 installPath
 */
function hasInstallPath(e: PluginInstall): e is PluginInstall & { installPath: string } {
  // STEP 01: installPath 非空字串
  return typeof e.installPath === 'string' && e.installPath !== '';
}

/**
 * 找 subagent_type 的定義檔：plugin agent（plugin:name）查 installed_plugins.json；
 * 其餘依序查專案層 <cwd>/.claude/agents、使用者層 ~/.claude/agents（同名時專案層優先）
 * @param type - subagent_type
 * @param dirs - 查找位置
 * @returns 定義檔路徑；找不到、名稱不合法或同名 plugin 對到多個檔時回 null
 */
export function resolveAgentFile(type: string, dirs: AgentDirs): string | null {
  // STEP 01: 專案層／使用者層 agent，先找到的為準
  /** plugin 名稱與 agent 名稱的分隔位置；沒有冒號為 -1 */
  const sep = type.indexOf(':');
  if (sep < 0) {
    if (!NAME_RE.test(type)) {
      return null;
    }
    for (const dir of [dirs.projectAgentsDir, dirs.userAgentsDir].filter(isString)) {
      /** 此目錄下的定義檔路徑 */
      const file = path.join(dir, `${type}.md`);
      if (fs.existsSync(file)) {
        return file;
      }
    }
    return null;
  }
  // STEP 02: plugin agent；名稱不合法或沒有安裝清單就不路由
  /** plugin 名稱（冒號前） */
  const plugin = type.slice(0, sep);
  /** plugin 內的 agent 名稱（冒號後） */
  const name = type.slice(sep + 1);
  if (!NAME_RE.test(plugin) || !NAME_RE.test(name) || !fs.existsSync(dirs.pluginsFile)) {
    return null;
  }
  /**
   * 是否為目標 plugin 的安裝清單項（filter 回呼）
   * @param entry - [plugin key, 安裝紀錄]
   * @returns true 表示 key 的 plugin 名稱等於目標
   */
  const isTargetPlugin = (entry: [string, PluginInstall[]]): boolean => entry[0].split('@')[0] === plugin;
  /**
   * 安裝紀錄 → 該安裝目錄下的定義檔路徑（map 回呼）
   * @param e - 帶 installPath 的安裝紀錄
   * @returns 定義檔路徑
   */
  const toAgentFile = (e: { installPath: string }): string => path.join(e.installPath, 'agents', `${name}.md`);
  /**
   * 取安裝清單項的紀錄陣列（flatMap 回呼）
   * @param entry - [plugin key, 安裝紀錄]
   * @returns 安裝紀錄
   */
  const installsOf = (entry: [string, PluginInstall[]]): PluginInstall[] => entry[1];
  // STEP 03: 依安裝紀錄的 installPath 找檔（快取目錄有多個舊版本，不能用 find）；對到多個不同檔視為不明確
  /** 目標 plugin 各安裝目錄下實際存在的定義檔路徑 */
  const files = Object.entries(readInstalledPlugins(dirs.pluginsFile))
    .filter(isTargetPlugin)
    .flatMap(installsOf)
    .filter(hasInstallPath)
    .map(toAgentFile)
    .filter(fileExists);
  /** 去重後的定義檔路徑（同一 installPath 可能出現在多個 marketplace key） */
  const unique = [...new Set(files)];
  return unique.length === 1 ? unique[0] : null;
}

/**
 * 呼叫 Jev 前的略過判斷（已確認是 Agent 工具、輸入合法、kill switch 未開）。
 * 定義檔優先：內建名稱若專案層或使用者層有同名定義檔，以定義檔的 model 為準；沒有才當內建類型路由
 * @param ti - Agent 工具輸入
 * @param dirs - 子代理定義檔查找位置
 * @returns 略過原因；可路由回 null
 */
export function preSkipReason(ti: AgentInput, dirs: AgentDirs): PreSkipReason | null {
  // STEP 01: 主模型已明寫 model、或沒有 brief 可判斷
  if (ti.model) {
    return 'model_set';
  }
  if (!ti.prompt.trim()) {
    return 'no_prompt';
  }
  // STEP 02: fork（未指定類型＝general-purpose）
  /** 實際的子代理類型（未指定為 general-purpose） */
  const type = ti.subagent_type || DEFAULT_TYPE;
  if (type === FORK_TYPE) {
    return 'fork';
  }
  // STEP 03: 找定義檔；找不到時只有內建類型可路由
  /** 子代理定義檔路徑；找不到為 null */
  const file = resolveAgentFile(type, dirs);
  if (!file) {
    return BUILTIN_ROUTABLE.has(type) ? null : 'no_def';
  }
  // STEP 04: 定義檔帶固定 model 不路由
  return inheritsModel(fs.readFileSync(file, 'utf-8')) ? null : 'fixed_model';
}

/**
 * 組送給 Jev 的 state：prompt 先遮罩憑證再截斷（先截斷可能把憑證切成遮罩樣式認不出的片段）
 * @param ti - Agent 工具輸入；prompt 必須是非空白字串、description 必須是字串，否則丟錯（不補空字串）
 * @returns `{ subagent_type, description, prompt }`
 */
export function buildState(ti: Pick<AgentInput, 'subagent_type' | 'description' | 'prompt'>) {
  // STEP 01: 驗證欄位；hook 端已由 preSkipReason 擋下 no_prompt，走到這裡代表呼叫端漏檢
  if (typeof ti.prompt !== 'string' || !ti.prompt.trim()) {
    throw new Error('buildState：prompt 缺漏或為空白，沒有可判斷的 brief');
  }
  if (typeof ti.description !== 'string') {
    throw new Error('buildState：description 不是字串');
  }
  // STEP 02: 遮罩後截斷
  return {
    subagent_type: ti.subagent_type ?? '',
    description: maskSecrets(ti.description),
    prompt: truncateMiddle(maskSecrets(ti.prompt), MAX_BRIEF_CHARS),
  };
}

/**
 * 模型字串 → 模型家族
 * @param model - 完整模型 ID（claude-<family>-…）或裸名（haiku／sonnet／opus／fable）
 * @returns 模型家族；不在 MODEL_RANK 內回 null
 */
export function modelFamily(model: string): ModelFamily | null {
  // STEP 01: 完整 ID 取 family，否則當裸名
  /** 完整模型 ID 的比對結果 */
  const m = model.match(MODEL_ID_RE);
  /** 模型家族候選（完整 ID 取 claude- 後一段，否則當裸名） */
  const family = m ? m[1] : model;
  // STEP 02: 只認等級表內的家族
  return Object.hasOwn(MODEL_RANK, family) ? (family as ModelFamily) : null;
}

/**
 * 讀檔案某個位元組區間內的完整行：區間起點不在檔頭時第一段可能是半行，最後一段可能是寫到一半的半行，兩者都丟掉
 * @param file - 檔案路徑
 * @param start - 起始位元組
 * @param length - 讀取長度
 * @returns 完整行（不含換行）
 */
function readCompleteLines(file: string, start: number, length: number): string[] {
  // STEP 01: 讀出區間位元組
  /** 讀取緩衝區 */
  const buf = Buffer.alloc(length);
  /** 檔案描述元 */
  const fd = fs.openSync(file, 'r');
  try {
    /** 實際讀到的位元組數（檔案比區間短時小於 length） */
    const n = fs.readSync(fd, buf, 0, length, start);
    // STEP 01.01: 換行字元不會出現在 UTF-8 多位元組序列中，先解碼再切行安全
    /** 以換行切開的各段 */
    const segs = buf.subarray(0, n).toString('utf-8').split('\n');
    // STEP 01.02: 丟掉可能不完整的頭尾段
    return segs.slice(start > 0 ? 1 : 0, -1);
  } finally {
    fs.closeSync(fd);
  }
}

/**
 * 解析 transcript 一行；區間邊界或正在寫入的半行解析失敗屬預期，回 null
 * @param line - 一行文字
 * @returns 解析結果；失敗回 null
 */
function parseLineOrNull(line: string): unknown {
  // STEP 01: 容忍解析失敗（只用於讀父模型的視窗，不用於評估資料抽取）
  try {
    return JSON.parse(line);
  } catch {
    return null;
  }
}

/**
 * 行內是否可能是 assistant 記錄（解析前粗篩的 filter 回呼）
 * @param line - 一行文字
 * @returns true 表示含 ASSISTANT_MARK
 */
function hasAssistantMark(line: string): boolean {
  // STEP 01: 字串比對
  return line.includes(ASSISTANT_MARK);
}

/**
 * 行內是否可能是 identity attachment（解析前粗篩的 filter 回呼）
 * @param line - 一行文字
 * @returns true 表示含 IDENTITY_MARK
 */
function hasIdentityMark(line: string): boolean {
  // STEP 01: 字串比對
  return line.includes(IDENTITY_MARK);
}

/**
 * 從 transcript 一行取 assistant 記錄的 model（map 回呼）
 * @param line - 一行文字
 * @returns 模型 ID；不是 assistant 記錄、沒有 model 或為 <synthetic> 時回 null
 */
function assistantModel(line: string): string | null {
  // STEP 01: type=assistant 且 message.model 為字串
  /** 解析後的記錄；解析失敗為 null */
  const rec = parseLineOrNull(line);
  if (!isRecord(rec) || rec.type !== 'assistant' || !isRecord(rec.message)) {
    return null;
  }
  // STEP 02: 跳過非模型產生的記錄
  /** assistant 記錄的 model 欄位 */
  const model = rec.message.model;
  return typeof model === 'string' && model !== SYNTHETIC_MODEL ? model : null;
}

/**
 * 從 transcript 一行取 identity attachment 的 modelId（map 回呼）
 * @param line - 一行文字
 * @returns 模型 ID；不是 identity attachment 回 null
 */
function identityModel(line: string): string | null {
  // STEP 01: attachment.identity.modelId 為字串
  /** 解析後的記錄；解析失敗為 null */
  const rec = parseLineOrNull(line);
  if (!isRecord(rec) || !isRecord(rec.attachment) || !isRecord(rec.attachment.identity)) {
    return null;
  }
  return stringOrNull(rec.attachment.identity.modelId);
}

/**
 * 行內是否可能帶模型資訊（assistant 記錄或 identity attachment；解析前粗篩的 filter 回呼）
 * @param line - 一行文字
 * @returns true 表示含 ASSISTANT_MARK 或 IDENTITY_MARK
 */
function hasModelMark(line: string): boolean {
  // STEP 01: 兩種粗篩字串任一命中
  return hasAssistantMark(line) || hasIdentityMark(line);
}

/**
 * 從 transcript 一行取模型 ID：assistant 記錄的 model 或 identity attachment 的 modelId（map 回呼）
 * @param line - 一行文字
 * @returns 模型 ID；兩者皆非時回 null
 */
function lineModel(line: string): string | null {
  // STEP 01: 先當 assistant 記錄讀，不是再當 identity 讀
  return assistantModel(line) ?? identityModel(line);
}

/**
 * 從 transcript 讀主 session（父）模型：取位置最新的 assistant 記錄 model 或 identity attachment 的 modelId。
 * 先讀尾端 TAIL_BYTES；找不到（第一回合 assistant 記錄還沒落盤、identity 又被擠出尾端）就從檔頭以 HEAD_BYTES 起倍增重讀，
 * 直到找到或達 HEAD_MAX_BYTES
 * @param transcriptPath - stdin 的 transcript_path；沒帶時回 null
 * @returns 模型 ID；沒帶路徑、檔案不存在或掃完都找不到時回 null
 */
export function readParentModel(transcriptPath: string | null): string | null {
  // STEP 01: 沒帶路徑或檔案不存在
  if (!transcriptPath || !fs.existsSync(transcriptPath)) {
    return null;
  }
  // STEP 02: 尾端視窗取位置最新的一筆（assistant 與 identity 一起看，才能反映中途 /model 切換）
  /** transcript 目前的位元組數 */
  const size = fs.statSync(transcriptPath).size;
  /** 尾端視窗的起始位元組 */
  const tailStart = Math.max(0, size - TAIL_BYTES);
  /** 尾端視窗內位置最新的模型 ID */
  const fromTail = readCompleteLines(transcriptPath, tailStart, size - tailStart)
    .filter(hasModelMark)
    .map(lineModel)
    .findLast(isString);
  if (fromTail) {
    return fromTail;
  }
  // STEP 03: 檔頭倍增掃描：每輪從 0 重讀（避免行跨越區間邊界被兩邊丟掉），視窗蓋過尾端起點或達上限就停
  /** 本輪檔頭視窗的長度 */
  let headLen = HEAD_BYTES;
  while (true) {
    // STEP 03.01: 讀本輪視窗，取第一筆模型 ID
    /** 本輪視窗內第一筆模型 ID */
    const fromHead = readCompleteLines(transcriptPath, 0, Math.min(size, headLen))
      .filter(hasModelMark)
      .map(lineModel)
      .find(isString);
    if (fromHead) {
      return fromHead;
    }
    // STEP 03.02: 視窗已涵蓋尾端掃過的起點、或達上限 → 放棄
    if (headLen >= tailStart || headLen >= HEAD_MAX_BYTES) {
      return null;
    }
    headLen = Math.min(headLen * 2, HEAD_MAX_BYTES);
  }
}

/**
 * 只降不升：候選 model 必須在 MODEL_RANK 上嚴格低於父模型才填
 * @param model - 由等級查出的候選 model
 * @param parentModel - 父模型 ID 或裸名；null 表示讀不到
 * @returns 路由結果；父模型不明 → parent_unknown，候選不比父模型便宜 → would_upgrade
 */
export function capByParent(model: RoutedModel, parentModel: string | null): RouteResult {
  // STEP 01: 父模型不明時不改寫
  /** 父模型的家族；讀不到或不在等級表為 null */
  const family = parentModel ? modelFamily(parentModel) : null;
  if (!family) {
    return { model: null, skip: 'parent_unknown' };
  }
  // STEP 02: 比等級
  return MODEL_RANK[model] < MODEL_RANK[family] ? { model, skip: null } : { model: null, skip: 'would_upgrade' };
}

/**
 * 依等級、confidence 與父模型決定填哪個 model（評估腳本共用，確保評估的就是 hook 的決策）
 * @param tier - Jev 判定的等級
 * @param conf - confidence
 * @param min - confidence 下限；hook 用 ROUTE_CONF_MIN，評估掃多個門檻
 * @param parentModel - 父模型 ID 或裸名；null 表示讀不到
 * @returns 路由結果
 */
export function routeModel(tier: Tier, conf: number, min: number, parentModel: string | null): RouteResult {
  // STEP 01: confidence 不足
  if (conf < min) {
    return { model: null, skip: 'low_conf' };
  }
  // STEP 02: 查表；top 不填
  /** 等級對應的候選 model；top 為 null */
  const model = TIER_MODEL[tier];
  if (!model) {
    return { model: null, skip: 'top' };
  }
  // STEP 03: 只降不升
  return capByParent(model, parentModel);
}

/**
 * 讀 Jev 的 tier 答案（hook 與評估腳本共用）
 * @param a - tier 題的原始答案；缺欄位或標籤不在 TIER_LABELS 時丟錯
 * @returns 等級、confidence 與次高等級
 */
export function readTier(a: JevAnswer | undefined): TierReading {
  // STEP 01: 讀預測與前兩名
  /** 預測標籤與 confidence */
  const { pred, conf } = readAnswer(a);
  /** 機率次高的選項 */
  const [, second] = topChoices(a);
  // STEP 02: 標籤必須在選項內
  if (!(TIER_LABELS as readonly unknown[]).includes(pred)) {
    throw new Error(`tier 答案不在選項內：${String(pred)}`);
  }
  return { tier: pred as Tier, conf, second: second.label, secondP: second.p };
}

/**
 * 讀 Jev 的 tier 答案並決定路由
 * @param a - tier 題的原始答案（不合法時丟錯）
 * @param parentModel - 父模型 ID；null 表示讀不到
 * @returns 路由決策
 */
export function decideRoute(a: JevAnswer | undefined, parentModel: string | null): RouteDecision {
  // STEP 01: 讀答案後套門檻、對照表與只降不升
  /** tier 讀數 */
  const t = readTier(a);
  return { ...t, ...routeModel(t.tier, t.conf, ROUTE_CONF_MIN, parentModel) };
}

/**
 * 組 PreToolUse 輸出：以填好 model 的工具輸入取代原輸入。
 * 契約（2026-10-11 以 2.1.296 `claude -p` 實測，tasks/jev-trial-plan.md 4.0）：updatedInput 整包取代、不合併，
 * 缺必填欄位會被 schema 驗證 deny，所以必須展開整個原輸入；不帶 permissionDecision 也生效，
 * 刻意不帶，避免替 Agent 工具自動放行、動到權限語意
 * @param ti - 原工具輸入
 * @param model - 要填的 model
 * @returns 要寫到 stdout 的物件
 */
export function buildOutput(ti: AgentInput, model: RoutedModel) {
  // STEP 01: 展開原輸入並填 model
  return {
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      updatedInput: { ...ti, model },
    },
  };
}

/**
 * 主流程：讀 stdin → 驗證 → 略過判斷 → 讀父模型 → 問 Jev → 達門檻且比父模型便宜時改寫 model
 * @returns 完成時 resolve；未預期錯誤往外丟
 */
async function main(): Promise<void> {
  // STEP 01: kill switch 與工具檢查；不是 Agent 工具不寫 log（matcher 設寬時每次工具呼叫都會進來）
  /** stdin 事件（驗證前） */
  const raw: unknown = JSON.parse(fs.readFileSync(STDIN_FD, 'utf-8'));
  if (jevDisabled()) {
    return;
  }
  /** 所有決策 log 共用的欄位 */
  const base = { hook: HOOK_NAME, session: isRecord(raw) ? stringOrNull(raw.session_id) : null };
  if (!isRecord(raw)) {
    logDecision({ ...base, skip: 'invalid_input' satisfies SkipReason });
    return;
  }
  if (raw.tool_name !== AGENT_TOOL) {
    return;
  }
  // STEP 02: 驗證工具輸入；不合法視為不可路由
  /** 驗證後的 Agent 工具輸入；不合法為 null */
  const ti = parseAgentInput(raw.tool_input);
  if (!ti) {
    logDecision({ ...base, skip: 'invalid_input' satisfies SkipReason });
    return;
  }
  /** Agent 派工決策 log 共用的欄位 */
  const agentBase = { ...base, subagent_type: ti.subagent_type ?? null };
  // STEP 03: 呼叫 Jev 前的略過條件
  /** 呼叫 Jev 前就能判定的略過原因 */
  const skip = preSkipReason(ti, dirsFor(stringOrNull(raw.cwd)));
  if (skip) {
    logDecision({ ...agentBase, skip });
    return;
  }
  // STEP 04: 讀父模型、問 Jev；Jev 失敗已在 askJev 內寫 log，直接放行
  /** 父模型 ID；讀不到為 null */
  const parent = readParentModel(stringOrNull(raw.transcript_path));
  /** Jev 回應；呼叫失敗為 null（已寫 log） */
  const res = await askJev(HOOK_NAME, buildState(ti), TIER_QUESTIONS, ROUTE_TIMEOUT_MS);
  if (!res) {
    return;
  }
  // STEP 05: 決策、寫 log（不含 brief 原文）、有填 model 時輸出
  /** 路由決策 */
  const d = decideRoute(res.answers.tier, parent);
  logDecision({
    ...agentBase, parent_model: parent, ms: Math.round(res.ms), tier: d.tier, tier_conf: d.conf,
    tier_2nd: d.second, tier_2nd_p: d.secondP, model_out: d.model, skip: d.skip,
  });
  if (d.model) {
    process.stdout.write(JSON.stringify(buildOutput(ti, d.model)));
  }
}

if (import.meta.main) {
  try {
    await main();
  } catch (err) {
    // 未預期錯誤：決策 log 照寫；stderr＋exit 1 讓 hook-error-wrapper 記入 ERRORS.jsonl（PreToolUse 非 2 的非零 exit 不阻擋工具）
    logDecision({ hook: HOOK_NAME, error: String(err) });
    process.stderr.write(`agent-model-router 未預期錯誤：${String(err)}\n`);
    process.exit(EXIT_UNEXPECTED);
  }
}
