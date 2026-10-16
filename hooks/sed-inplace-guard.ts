#!/usr/bin/env bun
/**
 * PreToolUse hook：禁用 `sed -i`（原地修改）。
 *
 * 把 CLAUDE.md code-style 的「banned: sed -i（跨平台行為不一致）」從文字規則變成機械強制。
 * 文字規則擋不住：2026-10 週檢討有 2 個 session 共用了 4 次 `sed -i`，沒有任何東西攔下。
 * macOS（BSD）的 `-i` 必須帶備份副檔名參數（`-i ''`），GNU 版則是選用的黏著後綴，
 * 同一條指令在兩邊行為不同，會失敗或悄悄改錯檔。
 *
 * 判定（isSedInPlace）：
 * - 先去除引號與 heredoc 內的文字，`grep "sed -i"`、commit message 裡寫到 sed -i 都不算
 * - 以 shell 分隔符切段，段內找 sed 指令（允許前面接 sudo／env／xargs 等包裝與環境變數）
 * - sed 之後出現 `-i`、`-i<後綴>`、含 i 的合併短旗標（`-ni`、`-Ei`、`-ie`）或 `--in-place[=後綴]` 即命中
 *
 * 放行條件：非 Bash 工具、沒有命中、指令任何位置含 `[allow-sed-i]`（明確逃生門，用於確需原地修改的少數情境）。
 * 失敗一律 fail-open（exit 0）：hook 自身的錯誤不應擋掉正常指令。
 * 擋下時寫一筆到 DENIALS.jsonl（scripts/lib/denial-log.ts，於擋下當下才動態載入，模組壞掉不致使整支 guard 失效）。
 *
 * 已知限制（命中範圍是對 shell 的近似，不是完整 parser，漏判方向都是放行）：
 * - `bash -c "sed -i …"`、`eval`、別名、變數展開出來的指令不會命中
 * - sed 之前的詞若不是包裝指令（如 `echo sed -i x`）視為普通引數，不命中
 */
import { stripQuotedText } from '../scripts/lib/shell-text';

/** 明確逃生門：指令字串任何位置出現即放行 */
const ALLOW_MARKER = /\[allow-sed-i\]/i;

/** 可以接在 sed 前面的包裝指令 */
const WRAPPERS = new Set(['sudo', 'env', 'xargs', 'command', 'time', 'nohup', 'exec', 'nice', 'builtin']);

/** shell 控制結構的關鍵字：其後的第一個詞仍是指令（`for …; do sed -i …; done`、`if sed -i …; then`） */
const CONTROL_WORDS = new Set(['do', 'then', 'else', 'elif', 'if', 'while', 'until', '!', '{']);

/** stdin 讀取逾時（毫秒）：超過靜默放行 */
const STDIN_TIMEOUT_MS = 2000;

/**
 * 判斷一個 token 是否是 sed 指令本身（含路徑前綴與 GNU 的 gsed 別名）。
 * @param token 以空白切出的 token
 * @returns 是否為 sed 指令
 */
function isSedToken(token: string): boolean {
  // STEP 01: 比對 sed／gsed，允許絕對或相對路徑前綴（/usr/bin/sed、./gsed）
  return /^(?:\S*\/)?g?sed$/.test(token);
}

/**
 * sed 之前的 token 是否都只是包裝（包裝指令、環境變數賦值、旗標與其數值引數、xargs 的 `{}`），
 * 即 sed 確實在「指令位置」而不是別的指令的引數。
 * @param before sed 之前、同一段內的 token
 * @returns 是否在指令位置
 */
function isCommandPosition(before: string[]): boolean {
  // STEP 01: sed 之前的每個 token 都必須是包裝、控制關鍵字、環境變數賦值、旗標、數值引數或 `{}`
  return before.every((t) => WRAPPERS.has(t) || CONTROL_WORDS.has(t) || /^\w+=/.test(t) || /^-/.test(t) || /^\d+$/.test(t) || t === '{}');
}

/**
 * 判斷 sed 之後的 token 是否含原地修改旗標。
 * @param args sed 之後、同一段內的 token
 * @returns 是否命中 -i／--in-place
 */
function hasInPlaceFlag(args: string[]): boolean {
  // STEP 01: 逐個 token 檢查，遇到旗標結束符就停
  for (const t of args) {
    // STEP 01.01: `--` 之後都是檔名引數，不再有旗標
    if (t === '--') {
      return false;
    }
    // STEP 01.02: 長旗標 --in-place（可帶 =後綴）
    if (/^--in-place(?:=.*)?$/.test(t)) {
      return true;
    }
    // STEP 01.03: 短旗標群：-i、-i.bak、-ni、-Ei、-ie；前面只能是字母，避免把 -5 之類的數值引數誤判
    if (/^-(?!-)[A-Za-z]*i/.test(t)) {
      return true;
    }
  }
  return false;
}

/**
 * 判斷 Bash 指令是否含 sed 原地修改。
 * @param command Bash 指令字串
 * @returns 是否命中 sed -i／--in-place（含逃生門時為 false）
 */
export function isSedInPlace(command: string): boolean {
  // STEP 01: 逃生門
  if (ALLOW_MARKER.test(command)) {
    return false;
  }

  // STEP 02: 去除引號與 heredoc 內容；括號與反引號換成分隔符，讓 `echo $(sed -i …)`、`(cd x && sed -i …)`
  // 裡的 sed 各自落在指令位置（子殼層與指令替換內的第一個詞就是指令）
  /** 前處理後的指令 */
  const stripped = stripQuotedText(command).replace(/[`()]/g, ';');

  // STEP 03: 以 shell 分隔符切段，逐段找 sed 指令
  for (const seg of stripped.split(/&&|\|\||;|\n|\|/)) {
    /** 段內 token */
    const tokens = seg.trim().split(/\s+/).filter(Boolean);
    /** 段內第一個 sed token 的位置；沒有為 -1 */
    const at = tokens.findIndex(isSedToken);
    if (at < 0 || !isCommandPosition(tokens.slice(0, at))) {
      continue;
    }
    if (hasInPlaceFlag(tokens.slice(at + 1))) {
      return true;
    }
  }
  return false;
}

/** deny 原因（送給 model） */
const DENY_REASON = [
  '🚫 禁用 `sed -i`：macOS（BSD）的 -i 必須帶備份副檔名參數（`-i \'\'`），GNU 版是選用後綴，同一條指令在兩邊行為不同，會失敗或悄悄改錯檔。',
  '改用：單檔 → Edit 工具；多檔批次 → python 腳本讀寫，或 `sed \'s/…/…/\' 檔案 > 暫存檔`，確認輸出後再 `cp` 回去。',
  '確需原地修改（例如操作 scratchpad 的生成檔）時，在指令中加上 `[allow-sed-i]` 即可略過本檢查。',
].join('\n');

if (import.meta.main) {
  /** hook 的 stdin JSON 資料 */
  let input = '';
  process.stdin.setEncoding('utf8');

  /** stdin 超時防呆：時限內未收到 end 靜默放行 */
  const stdinTimeout = setTimeout(() => { process.exit(0); }, STDIN_TIMEOUT_MS);

  process.stdin.on('data', (chunk: string) => { input += chunk; });
  process.stdin.on('end', async () => {
    clearTimeout(stdinTimeout);
    try {
      /** 本次 PreToolUse 事件 */
      const data = JSON.parse(input);

      // STEP 01: 只處理 Bash 工具，且指令命中 sed -i
      if (data.tool_name !== 'Bash' || typeof data.tool_input?.command !== 'string') {
        process.exit(0);
      }
      if (!isSedInPlace(data.tool_input.command)) {
        process.exit(0);
      }

      // STEP 02: 記錄這次擋下（失敗時附註隨 deny 原因送出，不影響 deny）。
      //   記錄模組在這一步才動態載入：放在檔頭 import 會先於 try 執行，模組壞掉時整支 guard 失效、改成全部放行
      /** 記錄失敗（含模組載入失敗）時的附註；成功為空字串 */
      const logNote = await import('../scripts/lib/denial-log')
        .then((m) => m.tryLogDenial({ guard: 'sed-inplace-guard', tool_name: data.tool_name, tool_input: data.tool_input, reason: DENY_REASON, session_id: data.session_id, cwd: data.cwd }))
        .catch((err: unknown) => `\n\n（附註：擋下紀錄模組載入失敗，本次未記錄：${err instanceof Error ? err.message : String(err)}）`);

      // STEP 03: deny
      console.log(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: DENY_REASON + logNote,
        },
      }));
      process.exit(0);
    } catch {
      process.exit(0);
    }
  });
}
