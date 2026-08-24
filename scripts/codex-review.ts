#!/usr/bin/env bun
/**
 * codex review 引擎：用平行的 `codex exec` 子進程執行 commit-review 的各個面向。
 *
 * 定位：commit-review skill 的 Tier 2/3 執行層**選項之一**，與現行的 Claude agent 路徑並存。
 * 兩條路徑跑同一組面向（見 lib/codex-aspects.ts），差別在誰執行、結果怎麼交回：
 * - agent 路徑：subagent 的回覆全文經 task-notification 回流，整份進主 session context
 * - codex 路徑：結果以 schema 強制成 JSON 落檔，主 session 只讀本腳本彙整出的 CRITICAL/IMPORTANT
 *
 * 【為何面向由本腳本的迴圈發動，而不是讓一個 codex 自己 spawn 六個 subagent】
 * codex 的 collaboration.spawn_agent 實測可用，但那樣面向數就交回模型手上。SKILL.md §3 已記錄過
 * 同型的坑：委派給會自行篩選面向的一方時，「傳五個 aspect 參數不等於跑五個面向」（實測只 spawn 3 個）。
 * 由本腳本逐一 spawn 則面向數是迴圈長度，缺檔即失敗，無從偽裝——這也讓解鎖用的 --aspects-done=N
 * 從自報數字變成可稽核的事實（成功面向數 = 通過驗證的輸出檔數）。
 *
 * 【三個實測踩過的 codex 陷阱，本腳本以程式規避，勿在後續修改中拿掉】
 * 1. stdin 是 pipe 時 codex exec 會等輸入而 hang（stdout 停在 "Reading additional input from stdin..."）
 *    → 必須 stdio stdin: 'ignore'
 * 2. `--ephemeral` 會讓 collaboration.spawn_agent 失敗（collab spawn failed: no thread with id）
 *    → 不使用該旗標；面向內部若要自行分工才有 thread 可掛
 * 3. codex 的 stdout 會出現「中間態」的半成品 JSON（欄位齊全但值是空的），只有 `-o` 寫出的
 *    最後一則 message 才是最終結果 → 一律讀 -o 的檔案，永遠不要解析 stdout
 *
 * 另外 `codex exec review` 子指令預設 sandbox=workspace-write（review 有權改 code）
 * 且 reasoning effort=none（等於沒認真審），故本腳本改用通用的 `codex exec`，顯式指定唯讀與推理強度。
 *
 * 用法：
 *   bun ~/.claude/scripts/codex-review.ts --tier=3
 *   bun ~/.claude/scripts/codex-review.ts --tier=2 --target=HEAD~1 --repo=/path/to/repo
 *   bun ~/.claude/scripts/codex-review.ts --tier=3 --aspects=rules,tests --show-minor
 *
 * exit code：0 = 全部面向通過驗證；1 = 有面向失敗（降級，不得清 marker）；2 = 用法或前置條件錯誤
 */
import { spawn } from 'child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync, openSync, closeSync, unlinkSync } from 'fs';
import { join, basename, dirname } from 'path';
import { execFileSync } from 'child_process';
import { homedir } from 'os';
import {
  REVIEW_ASPECTS, aspectsForTierKeys, buildAspectPrompt,
  type ReviewAspect, type AspectPromptContext,
} from './lib/codex-aspects';
import { aspectsForTier, repoRootToken, resolveRepoRoot } from './lib/review-marker';

/** codex 輸出 schema 檔路徑；以本腳本位置推導，避免相依於呼叫端的 cwd */
const SCHEMA_PATH = join(dirname(import.meta.path), 'schemas', 'codex-review-aspect.json');

/** 規則檔絕對路徑；codex 在 read-only sandbox 下可讀取 repo 以外的路徑（已實測） */
const RULE_FILE_PATH = join(homedir(), '.claude', 'CODE-REVIEW-RULE.md');

/** 報告輸出根目錄；每個 commit 一個子目錄，保留供事後查閱與對帳 */
const OUTPUT_ROOT = join(homedir(), '.claude', 'state', 'codex-review');

/** 單一面向的預設逾時（毫秒）。實測 effort=none 的單次 review 約 66s，effort=high 需更久，故給足裕度 */
const DEFAULT_TIMEOUT_MS = 900_000;

/** 預設推理強度。codex 預設是 none，對 code review 等於沒審，故本腳本一律顯式指定 */
const DEFAULT_EFFORT = 'high';

/** 嚴重度顯示順序，同時決定彙整輸出的分組順序 */
const SEVERITY_ORDER = ['CRITICAL', 'IMPORTANT', 'MINOR'] as const;

/** 狀態表中面向代號欄位的對齊寬度；取自最長面向代號（'silent-failure'，15 字）+ 0 */
const ASPECT_KEY_DISPLAY_WIDTH = 15;

/** 非法 JSON 輸出的預覽長度；夠辨識成因、不至於灌爆錯誤訊息 */
const INVALID_JSON_PREVIEW_LENGTH = 120;

/** 單一 finding 的嚴重度 */
type Severity = (typeof SEVERITY_ORDER)[number];

/** codex 依 schema 產出的單一問題項 */
interface Finding {
  /** 嚴重度 */
  severity: Severity;
  /** 相對 repo root 的檔案路徑 */
  file: string;
  /** 問題所在行號 */
  line: number;
  /** 問題描述 */
  problem: string;
  /** 修正方向 */
  suggestion: string;
}

/** codex 依 schema 產出的單一面向報告 */
interface AspectReport {
  /** 面向代號，須與請求的 key 一致 */
  aspect: string;
  /** 本面向的一句話結論 */
  summary: string;
  /** 發現的問題清單 */
  findings: Finding[];
}

/** 單一面向的執行結果（含失敗情形） */
interface AspectResult {
  /** 面向定義 */
  aspect: ReviewAspect;
  /** 是否通過三層驗證（exit code + 檔案非空 + schema shape） */
  ok: boolean;
  /** 失敗原因；成功時為 null。**失敗一律有原因，不以空結果代替** */
  reason: string | null;
  /** 驗證通過的報告；失敗時為 null */
  report: AspectReport | null;
  /** 子進程 exit code；逾時或無法啟動為 null */
  exitCode: number | null;
  /** 耗時（毫秒） */
  elapsedMs: number;
  /** 該面向的 codex stdout/stderr log 檔路徑，供失敗時人工追查 */
  logPath: string;
}

/**
 * 印出錯誤與用法後以 exit 2 結束。
 * 用法錯誤與面向失敗刻意用不同 exit code：前者是呼叫方寫錯，後者是 review 降級，處理方式不同。
 * @param message 錯誤訊息
 */
function usageFail(message: string): never {
  console.error(`❌ ${message}`);
  console.error('');
  console.error('用法：bun ~/.claude/scripts/codex-review.ts --tier=<2|3> [--target=<ref>] [--repo=<path>]');
  console.error('      選項：--aspects=<key,key> --effort=<none|low|medium|high> --model=<name>');
  console.error('            --timeout=<秒> --show-minor');
  console.error(`      面向代號：${REVIEW_ASPECTS.map((a) => a.key).join(' / ')}`);
  process.exit(2);
}

// STEP 01: 嚴格解析引數——未知 flag、重複給值、缺值一律拒絕，不靜默曲解
/** 原始引數（去掉 bun 與腳本路徑） */
const argv = process.argv.slice(2);
/** 目標 Tier；未帶為 null（必填） */
let tier: number | null = null;
/** 審查目標 commit ref */
let target = 'HEAD';
/** 目標 repo 路徑；未帶為 null，改用 cwd 推導 */
let argRepo: string | null = null;
/** 使用者指定的面向代號清單；未帶為 null，改由 tier 推導 */
let argAspectKeys: string[] | null = null;
/** 推理強度 */
let effort = DEFAULT_EFFORT;
/** 指定模型；未帶為 null，用 codex 預設 */
let model: string | null = null;
/** 單一面向逾時（毫秒） */
let timeoutMs = DEFAULT_TIMEOUT_MS;
/** 是否在彙整輸出印出 MINOR 明細；預設只計數，避免灌爆呼叫端的 context */
let showMinor = false;

for (const arg of argv) {
  if (arg.startsWith('--tier=')) {
    if (tier !== null) {
      usageFail('--tier 重複給值');
    }
    const parsed = Number(arg.slice('--tier='.length));
    if (!Number.isInteger(parsed)) {
      usageFail(`--tier 必須是整數，收到 ${arg}`);
    }
    tier = parsed;
  } else if (arg.startsWith('--target=')) {
    target = arg.slice('--target='.length);
    if (target === '') {
      usageFail('--target 不可為空');
    }
  } else if (arg.startsWith('--repo=')) {
    argRepo = arg.slice('--repo='.length);
    if (argRepo === '') {
      usageFail('--repo 不可為空');
    }
  } else if (arg.startsWith('--aspects=')) {
    const raw = arg.slice('--aspects='.length);
    if (raw === '') {
      usageFail('--aspects 不可為空');
    }
    const keys = raw.split(',').map((key) => key.trim()).filter((key) => key !== '');
    if (keys.length === 0) {
      usageFail(`--aspects 解析後沒有有效面向代號：${raw}`);
    }
    if (new Set(keys).size !== keys.length) {
      usageFail(`--aspects 含重複代號：${keys.join(',')}（每個面向只能列一次，重複會讓輸出檔互相覆寫）`);
    }
    argAspectKeys = keys;
  } else if (arg.startsWith('--effort=')) {
    effort = arg.slice('--effort='.length);
    if (effort === '') {
      usageFail('--effort 不可為空');
    }
  } else if (arg.startsWith('--model=')) {
    model = arg.slice('--model='.length);
    if (model === '') {
      usageFail('--model 不可為空');
    }
  } else if (arg.startsWith('--timeout=')) {
    const seconds = Number(arg.slice('--timeout='.length));
    if (!Number.isFinite(seconds) || seconds <= 0) {
      usageFail(`--timeout 必須是正數（秒），收到 ${arg}`);
    }
    timeoutMs = seconds * 1000;
  } else if (arg === '--show-minor') {
    showMinor = true;
  } else {
    usageFail(`未知引數：${arg}`);
  }
}

if (tier === null) {
  usageFail('缺少必填的 --tier=<2|3>');
}
if (tier < 2) {
  usageFail(`Tier ${tier} 不跑面向 review（Tier 0 只通知、Tier 1 不 spawn agent），本腳本不適用`);
}

// STEP 02: 解析 repo 與 commit 上下文，任一步失敗即中止——寧可不跑，不要對著錯的目標跑完
/** repo 根目錄絕對路徑 */
const repoRoot = resolveRepoRoot(argRepo ?? process.cwd());
if (!repoRoot || !existsSync(join(repoRoot, '.git'))) {
  usageFail(`不是 git repo：${argRepo ?? process.cwd()}`);
}
if (!existsSync(SCHEMA_PATH)) {
  usageFail(`找不到輸出 schema：${SCHEMA_PATH}`);
}
if (!existsSync(RULE_FILE_PATH)) {
  usageFail(`找不到規則檔：${RULE_FILE_PATH}`);
}

/**
 * 在目標 repo 執行 git 並取回 trim 過的 stdout。
 * @param args git 引數
 * @returns stdout 內容
 * @throws git 失敗時原樣拋出，由呼叫端決定如何中止
 */
function git(args: string[]): string {
  return execFileSync('git', args, { cwd: repoRoot, encoding: 'utf8' }).trim();
}

/** 目標 commit 的短 hash；同時作為「target 解析得到」的驗證 */
let shortSha: string;
/** 目標 commit 的 subject 行 */
let commitSubject: string;
try {
  shortSha = git(['rev-parse', '--short', target]);
  commitSubject = git(['log', '-1', '--format=%s', target]);
} catch {
  usageFail(`無法解析 target ref：${target}`);
}

// STEP 03: 決定面向清單，並與 marker 的 expectedAspects 交叉比對
/** 本次要執行的面向清單 */
let aspects: ReviewAspect[];
if (argAspectKeys) {
  aspects = argAspectKeys.map((key) => {
    const found = REVIEW_ASPECTS.find((aspect) => aspect.key === key);
    if (!found) {
      usageFail(`未知面向代號：${key}`);
    }
    return found;
  });
} else {
  aspects = aspectsForTierKeys(tier);
}

// STEP 03.01: 不論來源（預設或 --aspects），面向清單一律不得有重複代號。
// --aspects 的重複已在 STEP 01 攔截，這裡是給預設路徑的防呆——REVIEW_ASPECTS 未來若被
// 改壞出現重複 key，同一個 aspect 會被跑兩次、共用同一份輸出檔互相覆寫，但 aspects.length
// 仍等於 expectedAspects 而不會被下面的數量檢查發現，形成「跑了 N 次同一面向」卻被誤判
// 成「跑滿 N 個不同面向」進而允許解鎖的漏洞。
if (new Set(aspects.map((aspect) => aspect.key)).size !== aspects.length) {
  usageFail(`面向清單含重複代號：${aspects.map((aspect) => aspect.key).join(',')}`);
}

/** 該 Tier 的 marker 要求完成的面向數；本次面向數少於它時解鎖會被拒絕 */
const expectedAspects = aspectsForTier(tier);
if (!argAspectKeys && aspects.length !== expectedAspects) {
  // 未帶 --aspects 時用的是 aspectsForTierKeys(tier) 的預設清單，其長度依 contract
  // （lib/codex-aspects.ts 檔頭）必須永遠等於 aspectsForTier(tier)；不相等代表這兩個
  //「同一政策的兩種表述」已經分歧，是需要修 lib 程式碼的缺陷，不是可以帶過的執行期狀況。
  usageFail(
    `Tier ${tier} 的面向定義已分歧：aspectsForTierKeys() 回傳 ${aspects.length} 個，` +
    `aspectsForTier() 認為應為 ${expectedAspects} 個。兩者定義於 lib/codex-aspects.ts 與 ` +
    'lib/review-marker.ts，必須同步修正。',
  );
}

// STEP 04: 建立輸出目錄。用 repoRootToken()（與 marker 路徑同一份正規化規則）而非
// basename(repoRoot)：只取 basename 會讓兩個 basename 相同、絕對路徑不同的 repo
// （同名專案放在不同父目錄下的常見情形）共用同一個輸出位置並互相覆寫報告。
/** 本次 commit 的報告目錄 */
const outputDir = join(OUTPUT_ROOT, repoRootToken(repoRoot), shortSha);
mkdirSync(outputDir, { recursive: true });

/**
 * 驗證單一面向的輸出檔是否為可用結果。
 *
 * 三層硬證據，任一層不過即判定該面向失敗——**不得把驗證失敗當成「該面向沒發現問題」**。
 * 這正是 SKILL.md §3.1 的核心：面向靜默消失與「沒發現問題」在輸出上完全無法區分，
 * 而在 agent 路徑上這件事只能靠自律，在本路徑上它是可以機械判定的。
 *
 * @param outFile codex -o 寫出的檔案路徑
 * @param expectedKey 請求的面向代號，用於交叉比對是否審錯目標
 * @returns 驗證結果；失敗時 reason 說明是哪一層不過
 */
function validateOutput(outFile: string, expectedKey: string): { report: AspectReport | null; reason: string | null } {
  // STEP 01: 檔案存在且非空
  if (!existsSync(outFile)) {
    return { report: null, reason: '未產生輸出檔（codex 未寫出最後訊息）' };
  }
  const raw = readFileSync(outFile, 'utf8').trim();
  if (raw === '') {
    return { report: null, reason: '輸出檔為空' };
  }

  // STEP 02: 可解析為 JSON
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { report: null, reason: `輸出非合法 JSON（前 ${INVALID_JSON_PREVIEW_LENGTH} 字：${raw.slice(0, INVALID_JSON_PREVIEW_LENGTH)}）` };
  }

  // STEP 03: shape guard——逐欄檢查，缺欄即失敗，不補預設值
  if (typeof parsed !== 'object' || parsed === null) {
    return { report: null, reason: '輸出不是 JSON 物件' };
  }
  const candidate = parsed as Record<string, unknown>;
  if (candidate.aspect !== expectedKey) {
    return { report: null, reason: `面向代號不符：預期 ${expectedKey}，實際 ${String(candidate.aspect)}` };
  }
  if (typeof candidate.summary !== 'string' || candidate.summary.trim() === '') {
    return { report: null, reason: 'summary 缺失或為空' };
  }
  if (!Array.isArray(candidate.findings)) {
    return { report: null, reason: 'findings 不是陣列' };
  }
  for (const [index, item] of candidate.findings.entries()) {
    if (typeof item !== 'object' || item === null) {
      return { report: null, reason: `findings[${index}] 不是物件` };
    }
    const finding = item as Record<string, unknown>;
    if (!SEVERITY_ORDER.includes(finding.severity as Severity)) {
      return { report: null, reason: `findings[${index}].severity 非法：${String(finding.severity)}` };
    }
    // file/problem/suggestion 驗型別後還要驗非空白——欄位齊全但值是空字串，跟欄位缺漏
    // 一樣是「沒有可定位、可處理的內容」，若只驗型別會被當成正常 finding 收進報告與
    // passedAspects，卻是一則沒人能用的空殼。line 額外驗證為正整數：0 或負數指不到任何
    // 實際行號，同樣是內容無效而非「型別對但值怪」可以放行的情況。
    if (typeof finding.file !== 'string' || finding.file.trim() === '') {
      return { report: null, reason: `findings[${index}].file 缺失或為空` };
    }
    if (typeof finding.problem !== 'string' || finding.problem.trim() === '') {
      return { report: null, reason: `findings[${index}].problem 缺失或為空` };
    }
    if (typeof finding.suggestion !== 'string' || finding.suggestion.trim() === '') {
      return { report: null, reason: `findings[${index}].suggestion 缺失或為空` };
    }
    if (typeof finding.line !== 'number' || !Number.isInteger(finding.line) || finding.line < 1) {
      return { report: null, reason: `findings[${index}].line 缺失或非正整數：${String(finding.line)}` };
    }
  }

  return { report: candidate as unknown as AspectReport, reason: null };
}

/**
 * 執行單一面向的 codex review 子進程。
 *
 * 不 reject——面向失敗是預期內的結果之一，要能與其他面向一起被彙整與回報；
 * 讓它 reject 會使 Promise.all 短路，把「某個面向失敗」升級成「整輪沒有結果」。
 *
 * @param aspect 面向定義
 * @param ctx prompt 上下文
 * @returns 該面向的執行結果
 */
function runAspect(aspect: ReviewAspect, ctx: AspectPromptContext): Promise<AspectResult> {
  return new Promise((resolve) => {
    // STEP 01: 準備輸出路徑與 codex 引數（用展開而非 push 組陣列，不原地修改）
    const outFile = join(outputDir, `aspect-${aspect.key}.json`);
    const logPath = join(outputDir, `aspect-${aspect.key}.log`);
    const args = [
      'exec',
      '-s', 'read-only',
      '-C', repoRoot,
      '--color', 'never',
      '-c', `model_reasoning_effort="${effort}"`,
      '--output-schema', SCHEMA_PATH,
      '-o', outFile,
      ...(model ? ['-m', model] : []),
      buildAspectPrompt(aspect, ctx),
    ];
    /** 執行起始時間，供各失敗分支計算耗時 */
    const startedAt = Date.now();

    // STEP 02: 刪除同 commit 前一輪殘留的輸出檔。
    // 缺這步會造成 fail-open：重跑時本輪 codex 若失敗未寫檔，validateOutput 會讀到上一輪的舊檔
    // 而判定本輪成功——「這輪跑出來的結果」與「上輪留下的檔案」在檔案系統上無法區分。
    // 本函式承諾「不 reject」（見上方 JSDoc），故這裡的同步檔案操作必須自己接住例外，
    // 不能讓它們原樣往外拋——那會讓 Promise 建構子把整個 Promise 轉成 rejected，
    // 使 Promise.all 短路成「整輪沒有結果」，而不是「這個面向失敗」。
    try {
      if (existsSync(outFile)) {
        unlinkSync(outFile);
      }
    } catch (error) {
      resolve({
        aspect, ok: false, reason: `清除舊輸出檔失敗：${error instanceof Error ? error.message : String(error)}`,
        report: null, exitCode: null, elapsedMs: Date.now() - startedAt, logPath,
      });
      return;
    }

    // STEP 03: 開 log 檔承接 stdout/stderr——codex stdout 含中間態 JSON，只留存不解析
    let logFd: number;
    try {
      logFd = openSync(logPath, 'w');
    } catch (error) {
      resolve({
        aspect, ok: false, reason: `開啟 log 檔失敗：${error instanceof Error ? error.message : String(error)}`,
        report: null, exitCode: null, elapsedMs: Date.now() - startedAt, logPath,
      });
      return;
    }

    // STEP 04: 啟動子進程。stdin 必須 ignore，否則 codex 會等 stdin 而永遠不結束
    const child = spawn('codex', args, {
      cwd: repoRoot,
      stdio: ['ignore', logFd, logFd],
    });

    // STEP 05: 自管逾時旗標，不依賴 spawn 的 timeout 選項與 close 事件的 signal 參數
    // 實測：codex 收到 SIGTERM 後會優雅退出並回 exit 0、signal 為 null，用 signal 判逾時抓不到，
    // 會把逾時誤報成「未產生輸出檔」；若它在被砍前剛好寫出半成品，更會被判成功。逾時是本進程
    // 自己造成的事實，就由本進程自己記，不透過子進程的退出方式間接推測。
    let timedOut = false;
    const timeoutTimer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, timeoutMs);

    // STEP 06: 'error' 與 'close' 都可能對同一個子進程觸發（例如 spawn 失敗時兩者依序都會來），
    // 用 settled 旗標確保收尾動作（clearTimeout / closeSync / resolve）只執行一次——重複
    // closeSync 同一個 fd 會拋 EBADF，讓一個「該面向失敗」的可預期情形變成未捕捉例外。
    let settled = false;
    /**
     * 收尾：清 timer、關 log fd、resolve 一次。
     * @param result 該面向的最終結果
     */
    function finish(result: AspectResult): void {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeoutTimer);
      try {
        closeSync(logFd);
      } catch {
        // fd 可能已被系統關閉（如子進程異常終止），非本次要判定的失敗原因，略過即可
      }
      resolve(result);
    }

    child.on('error', (error) => {
      finish({
        aspect, ok: false, reason: `無法啟動 codex：${error.message}`,
        report: null, exitCode: null, elapsedMs: Date.now() - startedAt, logPath,
      });
    });

    child.on('close', (code) => {
      const elapsedMs = Date.now() - startedAt;

      // STEP 06.01: 逾時一律判失敗，且不看輸出檔——被砍斷的 review 不論寫出什麼都不可信
      if (timedOut) {
        finish({
          aspect, ok: false, reason: `逾時未完成（超過 ${Math.round(timeoutMs / 1000)}s 已強制中止）`,
          report: null, exitCode: null, elapsedMs, logPath,
        });
        return;
      }

      // STEP 06.02: exit code 非 0 直接判失敗，不再看輸出檔——半途中止的輸出不可信
      if (code !== 0) {
        finish({
          aspect, ok: false, reason: `codex 以 exit ${code} 結束（詳見 ${basename(logPath)}）`,
          report: null, exitCode: code, elapsedMs, logPath,
        });
        return;
      }

      // STEP 06.03: exit 0 仍要驗輸出——exit 0 只代表進程正常結束，不代表產出可用
      const { report, reason } = validateOutput(outFile, aspect.key);
      finish({
        aspect, ok: report !== null, reason,
        report, exitCode: code, elapsedMs, logPath,
      });
    });
  });
}

/**
 * 把單一 finding 格式化成一行（含建議另起一行）。
 * @param finding 問題項
 * @param aspectKey 來源面向代號
 * @returns 格式化字串
 */
function formatFinding(finding: Finding, aspectKey: string): string {
  return `  - ${finding.file}:${finding.line} [${aspectKey}] ${finding.problem}\n    → ${finding.suggestion}`;
}

// STEP 05: 平行執行全部面向並彙整
/** prompt 共用上下文 */
const promptContext: AspectPromptContext = {
  repoRoot,
  target,
  commitSubject,
  ruleFilePath: RULE_FILE_PATH,
};

console.log(`▶ codex review：${basename(repoRoot)} @ ${shortSha}（Tier ${tier}，${aspects.length} 個面向平行執行）`);
console.log(`  target: ${target} — ${commitSubject}`);
console.log(`  effort: ${effort}${model ? `｜model: ${model}` : ''}｜timeout: ${Math.round(timeoutMs / 1000)}s`);
console.log('');

// runAspect() 承諾不 reject（同步檔案操作已各自接住例外，見該函式 STEP 02/03），
// 這裡的 try-catch 是最後一道防線：往後若有人改動 runAspect 而不小心破壞這個保證，
// 至少能把它轉成有訊息的 exit 2，而不是讓使用者看到裸露的 unhandled rejection stack trace。
let results: AspectResult[];
try {
  results = await Promise.all(aspects.map((aspect) => runAspect(aspect, promptContext)));
} catch (error) {
  usageFail(`面向執行時發生未預期例外（runAspect 不應 reject，這代表其保證被破壞）：${error instanceof Error ? error.message : String(error)}`);
}

/** 通過驗證的面向 */
const passed = results.filter((result) => result.ok);
/** 失敗的面向 */
const failed = results.filter((result) => !result.ok);

// STEP 06: 輸出面向狀態表——每個面向都要有一行，成功與失敗都看得見
console.log(`面向結果：${passed.length}/${results.length} 通過`);
for (const result of results) {
  const seconds = `${Math.round(result.elapsedMs / 1000)}s`;
  if (!result.ok) {
    console.log(`  ❌ ${result.aspect.key.padEnd(ASPECT_KEY_DISPLAY_WIDTH)} 失敗：${result.reason}（${seconds}）`);
    continue;
  }
  const counts = SEVERITY_ORDER.map((severity) => {
    const total = result.report!.findings.filter((finding) => finding.severity === severity).length;
    return `${total} ${severity}`;
  }).join(' / ');
  console.log(`  ✅ ${result.aspect.key.padEnd(ASPECT_KEY_DISPLAY_WIDTH)} ${counts}（${seconds}）`);
}
console.log('');

// STEP 07: 依嚴重度分組輸出問題明細；MINOR 預設只計數，避免無謂地灌爆呼叫端 context
for (const severity of SEVERITY_ORDER) {
  const lines: string[] = [];
  for (const result of passed) {
    for (const finding of result.report!.findings) {
      if (finding.severity === severity) {
        lines.push(formatFinding(finding, result.aspect.key));
      }
    }
  }
  if (lines.length === 0) {
    continue;
  }
  if (severity === 'MINOR' && !showMinor) {
    console.log(`MINOR（${lines.length}）：省略明細，加 --show-minor 或讀報告目錄查看`);
    console.log('');
    continue;
  }
  console.log(`${severity}（${lines.length}）：`);
  console.log(lines.join('\n'));
  console.log('');
}

// STEP 08: 各面向的 summary——沒有 findings 時，這是判斷「檢查過」與「沒檢查到」的唯一依據
console.log('各面向結論：');
for (const result of passed) {
  console.log(`  [${result.aspect.key}] ${result.report!.summary}`);
}
console.log('');

// STEP 09: 落一份彙整檔，供事後對帳與其他程式讀取
/** 彙整檔路徑 */
const summaryPath = join(outputDir, 'summary.json');
writeFileSync(summaryPath, JSON.stringify({
  repoRoot,
  target,
  shortSha,
  commitSubject,
  tier,
  expectedAspects,
  requestedAspects: aspects.map((aspect) => aspect.key),
  passedAspects: passed.map((result) => result.aspect.key),
  failedAspects: failed.map((result) => ({ aspect: result.aspect.key, reason: result.reason })),
  findings: passed.flatMap((result) => result.report!.findings.map((finding) => ({
    ...finding,
    aspect: result.aspect.key,
  }))),
}, null, 2), 'utf8');

console.log(`完整報告：${outputDir}`);

// STEP 10: 依是否有面向失敗決定 exit code 與後續指示
if (failed.length > 0) {
  console.log('');
  console.log(`⚠️  Tier ${tier} 降級：${failed.length}/${results.length} 個面向未取得有效結果`);
  console.log(`   未回傳面向：${failed.map((result) => result.aspect.key).join('、')}`);
  console.log('   依 SKILL.md §3.1，此情形不得清 marker，須先向使用者回報並取得同意後才 --force 解鎖。');
  process.exit(1);
}

console.log('');
console.log(`解鎖指令：bun ~/.claude/scripts/clear-pending-review.ts --aspects-done=${passed.length}`);
process.exit(0);
