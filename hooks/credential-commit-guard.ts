#!/usr/bin/env bun
/**
 * PreToolUse hook：git commit 前的憑證掃描閘門。
 *
 * 把 rules/common/security.md SECRET-MGMT 的 pre-commit-scan 從「靠自律去跑」變成機械強制：
 * 只在 Bash 指令含 git commit 時觸發，掃「這次 commit 會帶進去的新增行」，命中就 deny，
 * reason 只列檔名、不印內容（LOG-SAFETY）。
 *
 * 掃描範圍：
 * - 暫存區（git diff --cached）
 * - 帶 -a／--all：另掃未暫存的已追蹤變更（git diff）
 * - 帶 pathspec（git commit -m x -- file，或省略 -- 的 git commit -m x file）：該些路徑的工作目錄內容
 *   （git diff HEAD -- paths），因為指定路徑時 git 直接提交工作目錄版本
 * 只看**新增行**：移除憑證、或把憑證換成環境變數的 commit 不會被擋，否則清理外洩的 commit 自己會被卡住。
 *
 * 觸發範圍刻意限定在 commit 指令：若對每個 Bash 呼叫都掃，暫存區一有命中，連修復用的
 * `git restore --staged` 也會被擋，變成死鎖。
 *
 * 放行條件（任一成立即不阻擋）：
 * - 非 Bash 工具、或指令不含 git commit
 * - Bash 指令字串任何位置含 [skip-credential-scan]（明確逃生門，用於測試 fixture 內的假憑證）
 * - 無法解析 repo 根目錄（exit 0：此時 git commit 本身也會失敗）
 * - 掃描沒有命中
 *
 * 失敗處理：hook 自身的錯誤——stdin 讀取逾時、JSON 解析失敗、事件欄位型別不符、git 掃描失敗——
 * 在「沒有任何命中」時一律不擋 commit（避免 brick），但以 exit 1 + stderr 回報，由 hook-error-wrapper 記進 ERRORS.jsonl：
 * 掃描沒跑成不能與「沒命中」長得一樣。唯一的 exit 0 例外是上面「無法解析 repo 根目錄」。
 * 例外：已有掃描命中、另一個掃描失敗時，命中優先——照常 deny（exit 0），失敗訊息附註在 deny 原因裡，
 * 不能讓後續的掃描失敗把已確認的憑證命中吃掉。
 *
 * 已知限制（第二輪 review 確認、決定不修，漏掃時是「沒掃到」而非誤放行已命中的結果）：
 * - `git add X && git commit` 寫在同一個 Bash 指令時，hook 觸發當下 add 尚未執行，暫存區看不到 X，掃不到。
 *   add 與 commit 分成兩次呼叫才完整涵蓋。
 * - 指令解析是對 shell 的近似（去除引號與 heredoc 內容後以分隔符切段），不是完整的 shell parser。由此衍生：
 *   (a) pathspec 加了引號（`git commit -m x "f.env"`）會被當成空引號佔位符而漏掃；
 *   (b) pathspec 相對於指令的實際工作目錄，但 diff 以 repo 根目錄執行，子目錄下的相對路徑與 `~/` 開頭路徑漏掃；
 *   (c) 只認指令開頭的 `cd` 與第一個 `-C` 來決定 repo，`git status && cd R && git commit` 會掃錯 repo；
 *   (d) `VAR=1 git commit`、`env`／`sudo` 包裝、alias（`git ci`）、反引號、`bash -c "…"` 不會觸發本 hook
 *       （isGitCommitCommand 與 commit-gate-guard 共用，不在此單獨改）。
 * - 掃描走 `git diff` 文字輸出：binary 檔（含 .gitattributes 標 binary、含 NUL）不掃；
 *   沒有 HEAD 的初始 commit 帶 pathspec 時，只掃暫存區。
 *
 * 擋下時寫一筆到 DENIALS.jsonl（scripts/lib/denial-log.ts，於擋下當下才動態載入）。
 */
import { spawnSync } from 'child_process';
import { isGitCommitCommand, resolveRepoRootFromCommand } from '../scripts/lib/review-marker';

/**
 * 疑似憑證的 ERE pattern。與 rules/common/security.md 的 pre-commit-scan、
 * skills/sync-my-claude-setting/SKILL.md STEP 04 逐字相同；三處一致由 credential-commit-guard.test.ts
 * 的「pattern 一致性」測試機械檢查，改一處漏改其他兩處會讓測試變紅。
 * 兩處刻意收斂以降低誤擋：`sk-` 前不得緊接英數字／`_`／`-`（長名稱如 task-xxx 不是金鑰）；
 * URL 內嵌帳密那條規則的密碼位置不得以 `$` 開頭（變數展開 `${TOKEN}` 不是明文）。理由與代價見 security.md。
 */
export const CREDENTIAL_PATTERN = '://[^/:@[:space:]]+:[^$@/[:space:]][^@/[:space:]]*@|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|(^|[^A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY';

/** 單次 git／grep 子行程的逾時（毫秒）。這只限制單次呼叫，hook 整體沒有固定上限（repo 解析、HEAD 檢查、最多 3 次 git diff、整批與逐檔 grep 的次數都會疊加）；
 * 一般情況在 1 秒內完成，settings.json 為本 hook 設的 timeout（單位是秒，目前 30）是整體保險，逾時時 PreToolUse 會放行 */
const SCAN_TIMEOUT_MS = 3000;

/** stdin 讀取逾時（毫秒）：超過視為輸入讀取失敗 */
const STDIN_TIMEOUT_MS = 2000;

/** git diff 輸出上限（位元組）：超過即掃描失敗而非靜默截斷 */
const MAX_DIFF_BYTES = 64 * 1024 * 1024;

/** git commit 的長選項中，值在下一個 token 的那些（pathspec 解析時要連值一起跳過） */
const LONG_OPTIONS_WITH_VALUE = new Set(['--message', '--file', '--reuse-message', '--reedit-message', '--author', '--date', '--template', '--cleanup']);

/** git commit 的短選項字母中，後面帶值的那些（-m msg、-F file、-C commit、-c commit、-t file） */
const SHORT_OPTION_VALUE_LETTERS = new Set(['m', 'F', 'C', 'c', 't']);

/** 從 commit 指令解析出的、會影響「這次 commit 實際帶進去什麼」的資訊 */
export interface CommitInfo {
  /** 帶 -a／--all：未暫存的已追蹤變更也會進這個 commit */
  all: boolean;
  /** 指定的 pathspec：這些路徑直接提交工作目錄版本 */
  paths: string[];
}

/**
 * 去除引號內文字與 heredoc 內容，避免 commit message 裡的 `;`、`&&`、`-a` 干擾旗標解析。
 * @param command Bash 指令字串
 * @returns 去除後的字串（引號內文字以空引號取代）
 */
function stripQuotedText(command: string): string {
  return command
    .replace(/<<-?\s*['"]?(\w+)['"]?[\s\S]*?\n\s*\1\b/g, ' ')
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'[^']*'/g, "''");
}

/**
 * 解析 git commit 指令，取得 -a／--all 與 pathspec。指令中有多個 git commit 時合併各段的結果。
 * @param command Bash 指令字串
 * @returns 解析結果；指令中沒有 git commit 時為 { all: false, paths: [] }
 */
export function parseCommit(command: string): CommitInfo {
  // STEP 01: 去除引號與 heredoc 內容後，以 shell 分隔符切段，每個 git commit 段各自解析再合併
  //   （`git commit -m a && git commit -am b`：第二段的 -a 也會把未暫存的變更帶進去）
  const stripped = stripQuotedText(command);
  /** 含 git commit 的各段指令 */
  const segs = stripped.split(/&&|\|\||;|\n|\|/).filter(s => isGitCommitCommand(s));
  /** 各段解析結果 */
  const infos = segs.map(parseCommitSegment);
  return {
    all: infos.some(i => i.all),
    paths: infos.flatMap(i => i.paths),
  };
}

/**
 * 解析單一 git commit 指令段（已去引號、已切段），取得 -a／--all 與 pathspec。
 * @param seg 含 git commit 的單一指令段
 * @returns 解析結果
 */
function parseCommitSegment(seg: string): CommitInfo {
  // STEP 01: 取 commit 子指令之後的 token（用與 isGitCommitCommand 相同的前綴規則定位，避開 `-c commit.x=y` 這類誤命中）
  /** commit 子指令前綴的比對結果 */
  const prefix = /git\s+(?:-C\s+\S+\s+|-c\s+\S+\s+|--[\w-]+(?:=\S+)?\s+)*commit(?![\w-])/.exec(seg);
  /** 去掉 shell 重導向（`> /dev/null`、`2>&1`、`< in`）與背景符號後，commit 之後的 token 清單；重導向目標不是 pathspec */
  const tokens = seg
    .slice((prefix?.index ?? 0) + (prefix?.[0].length ?? 0))
    .replace(/\d*[<>]+&?\s*\S+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(t => t && t !== '&');

  // STEP 02: 逐 token 解析旗標與 pathspec
  let all = false;
  /** 蒐集到的 pathspec */
  const paths: string[] = [];
  /** 是否已遇到 `--`（其後全是路徑） */
  let afterDashDash = false;
  for (let i = 0; i < tokens.length; i++) {
    /** 目前處理的 token */
    const tok = tokens[i];
    if (afterDashDash) {
      paths.push(tok);
      continue;
    }
    if (tok === '--') {
      afterDashDash = true;
      continue;
    }
    if (tok.startsWith('--')) {
      if (tok === '--all') {
        all = true;
      }
      // STEP 02.01: `--message foo` 這種值在下一個 token 的長選項，連值一起跳過
      if (!tok.includes('=') && LONG_OPTIONS_WITH_VALUE.has(tok)) {
        i++;
      }
      continue;
    }
    if (tok.startsWith('-') && tok.length > 1) {
      // STEP 02.02: 短選項（可合併，如 -am）：逐字母看，遇到帶值的字母就停（值是同 token 剩餘部分或下一個 token）
      for (let k = 1; k < tok.length; k++) {
        /** 目前的短選項字母 */
        const letter = tok[k];
        if (letter === 'a') {
          all = true;
        }
        if (SHORT_OPTION_VALUE_LETTERS.has(letter)) {
          if (k === tok.length - 1) {
            i++;
          }
          break;
        }
      }
      continue;
    }
    // STEP 02.03: 其餘 token 是 pathspec（空引號佔位符是被去除的 message 值，不算路徑）
    if (tok !== '""' && tok !== "''") {
      paths.push(tok);
    }
  }
  return { all, paths };
}

/**
 * 判斷 repo 是否已有至少一個 commit（initial commit 時 git diff HEAD 會失敗）。
 * @param repoRoot repo 根目錄
 * @returns 是否有 HEAD
 */
function hasHead(repoRoot: string): boolean {
  return spawnSync('git', ['-C', repoRoot, 'rev-parse', '--verify', '-q', 'HEAD'], { timeout: SCAN_TIMEOUT_MS }).status === 0;
}

/**
 * 判斷一段文字是否命中憑證 pattern（交給 grep -E，與 security.md 的 git -E 同一套 POSIX ERE）。
 * @param text 要檢查的文字
 * @returns 是否命中
 * @throws grep 執行失敗（exit 2 或啟動錯誤）
 */
function matchesCredential(text: string): boolean {
  const r = spawnSync('grep', ['-E', '-q', '-e', CREDENTIAL_PATTERN], { input: text, timeout: SCAN_TIMEOUT_MS });
  if (r.error || (r.status !== 0 && r.status !== 1)) {
    throw new Error(`grep 掃描失敗：${r.error ? r.error.message : `exit ${r.status}`}`);
  }
  return r.status === 0;
}

/**
 * 掃描 git diff 的**新增行**，回傳命中憑證 pattern 的檔名（不含內容）。
 * 只看新增行：刪除或替換憑證的變更不算命中，清理外洩的 commit 才不會被自己的閘門擋住。
 * @param repoRoot repo 根目錄
 * @param diffArgs 傳給 git diff 的參數（如 ['--cached']）
 * @returns 命中的檔名清單
 * @throws git 執行失敗、輸出超過上限或逾時
 */
export function scanAdded(repoRoot: string, diffArgs: string[]): string[] {
  // STEP 01: 取 -U0 的 diff
  const r = spawnSync('git', ['-C', repoRoot, 'diff', ...diffArgs, '-U0', '--no-color', '--no-ext-diff'], { encoding: 'utf8', timeout: SCAN_TIMEOUT_MS, maxBuffer: MAX_DIFF_BYTES });
  if (r.error || r.status !== 0) {
    throw new Error(`git diff 掃描失敗：${r.error ? r.error.message : `exit ${r.status} ${(r.stderr || '').trim()}`}`);
  }

  // STEP 02: 依檔案收集新增行（`+++ b/path` 標檔名；`+++ /dev/null` 是刪除，沒有新增行）
  /** 檔名 → 該檔新增行 */
  const added = new Map<string, string[]>();
  /** 目前所在檔案；null 表示不收集 */
  let current: string | null = null;
  for (const line of r.stdout.split('\n')) {
    if (line.startsWith('+++ ')) {
      /** 去掉 b/ 前綴與 git 對特殊字元加的引號後的檔名 */
      const name = line.slice(4).replace(/^"?b\//, '').replace(/"$/, '');
      current = line.startsWith('+++ /dev/null') ? null : name;
      if (current && !added.has(current)) {
        added.set(current, []);
      }
    } else if (current && line.startsWith('+')) {
      added.get(current)?.push(line.slice(1));
    }
  }

  // STEP 03: 先整批檢查（絕大多數 commit 無命中，只花一次 grep），有命中才逐檔定位
  /** 所有新增行合併 */
  const all = Array.from(added.values()).flat().join('\n');
  if (!all || !matchesCredential(all)) {
    return [];
  }
  return Array.from(added.entries()).filter(([, lines]) => matchesCredential(lines.join('\n'))).map(([file]) => file);
}

/**
 * 驗證並取出 Bash 事件的 command 與 cwd；欄位型別不符視為契約錯誤並拋出。
 * @param data JSON.parse 的結果（未驗證）
 * @returns tool_name 不是 Bash 時為 null；否則為 command 與 cwd
 * @throws 事件不是物件、tool_name／command／cwd 型別不符
 */
function readBashEvent(data: unknown): { command: string; cwd: string } | null {
  if (typeof data !== 'object' || data === null) {
    throw new Error('hook 輸入不是 JSON 物件');
  }
  /** 事件欄位（已確認是物件） */
  const ev = data as Record<string, unknown>;
  if (typeof ev.tool_name !== 'string') {
    throw new Error('hook 輸入的 tool_name 不是字串');
  }
  if (ev.tool_name !== 'Bash') {
    return null;
  }
  /** tool_input 內容 */
  const input = ev.tool_input as Record<string, unknown> | undefined;
  if (typeof input?.command !== 'string') {
    throw new Error('Bash 事件的 tool_input.command 不是字串');
  }
  if (ev.cwd !== undefined && typeof ev.cwd !== 'string') {
    throw new Error('hook 輸入的 cwd 不是字串');
  }
  return { command: input.command, cwd: ev.cwd ?? process.cwd() };
}

/** 直接執行（非被 import）時才讀 stdin；測試 import 本檔的純函式時不啟動 hook 流程 */
if (import.meta.main) {
  let input = '';
  process.stdin.setEncoding('utf8');

  /** stdin 讀取逾時計時器：逾時代表沒拿到完整事件、沒有執行掃描，必須回報 */
  const stdinTimeout = setTimeout(() => {
    console.error(`credential-commit-guard 讀取 stdin 逾時（${STDIN_TIMEOUT_MS}ms），本次 commit 未經憑證掃描`);
    process.exit(1);
  }, STDIN_TIMEOUT_MS);

  process.stdin.on('data', (chunk: string) => { input += chunk; });
  process.stdin.on('end', async () => {
    clearTimeout(stdinTimeout);
    try {
      // STEP 01: 解析並驗證事件；非 Bash 工具放行
      const ev = readBashEvent(JSON.parse(input));
      if (!ev) {
        process.exit(0);
      }
      const { command, cwd } = ev;

      // STEP 02: 非 git commit 指令 → 放行（含 git -C <path> commit 等全域選項在前的形式）
      if (!isGitCommitCommand(command)) {
        process.exit(0);
      }

      // STEP 03: 明確逃生門
      if (/\[skip-credential-scan\]/i.test(command)) {
        process.exit(0);
      }

      // STEP 04: 解析 commit 實際目標 repo（只認開頭的 cd 與第一個 git -C，見檔頭已知限制）；解析不出來 → 放行（多半是 git commit 本身也會失敗）
      const repoRoot = resolveRepoRootFromCommand(command, cwd);
      if (!repoRoot) {
        process.exit(0);
      }

      // STEP 05: 掃描——暫存區必掃；-a／--all 加掃未暫存的已追蹤變更；指定 pathspec 加掃該些路徑的工作目錄內容
      //   每個掃描各自 try：某一個掃描失敗（例如 pathspec 指到 repo 外）不能丟掉其他掃描已確認的命中
      /** 這次 commit 的旗標與 pathspec */
      const info = parseCommit(command);
      /** 要跑的 git diff 參數清單：暫存區必掃；-a 加掃未暫存；有 pathspec 且有 HEAD 時加掃該些路徑 */
      const plans: string[][] = [
        ['--cached'],
        ...(info.all ? [[]] : []),
        ...(info.paths.length > 0 && hasHead(repoRoot) ? [['HEAD', '--', ...info.paths]] : []),
      ];
      /** 命中的檔名（去重前） */
      let found: string[] = [];
      /** 第一個掃描失敗的訊息；null 表示全部掃描成功 */
      let scanError: string | null = null;
      for (const args of plans) { // args：單次 git diff 的參數
        try {
          found = found.concat(scanAdded(repoRoot, args));
        } catch (err) {
          scanError ??= err instanceof Error ? err.message : String(err);
        }
      }
      /** 命中的檔名（去重） */
      const hits = Array.from(new Set(found));

      // STEP 06: 無命中 → 放行；但有掃描失敗時不能靜默放行——exit 1 讓 hook-error-wrapper 記進 ERRORS.jsonl（不擋 commit，避免 brick）
      if (hits.length === 0) {
        if (scanError !== null) {
          console.error(`credential-commit-guard 掃描失敗，本次 commit 未經完整憑證掃描：${scanError}`);
          process.exit(1);
        }
        process.exit(0);
      }

      // STEP 07: 組出 deny 原因（只列檔名，不印內容）
      /** deny 原因（送給 model） */
      const reason = [
        '🔒 憑證掃描：本次 commit 有疑似憑證的新增內容，已停止。命中檔案：',
        ...hits.map(f => `  - ${f}`),
        '',
        '（只列檔名；pattern 見 rules/common/security.md pre-commit-scan）',
        '處理方式：',
        '  1. 是真憑證 → 改成環境變數（process.env／${VAR}）後重新 add。若憑證已進過 git 歷史或 log，視為外洩，依 security.md SECURITY-INCIDENT 撤銷並輪換。',
        '  2. 是測試 fixture 的假憑證 → 在 commit 指令加上 [skip-credential-scan]。',
        '  3. 不確定 → 先停下來問 user，不要為了通過而放寬 pattern。',
      ].join('\n');

      // STEP 08: 記錄這次擋下（失敗時附註隨 deny 原因送出，不影響 deny）
      //   記錄模組在這一步才動態載入：放在檔頭 import 會先於本檔的 try 執行，模組壞掉時整支 guard 失效、改成全部放行
      /** 記錄失敗（含模組載入失敗）時的附註；成功為空字串 */
      const logNote = await import('../scripts/lib/denial-log')
        .then(m => m.tryLogDenial({ guard: 'credential-commit-guard', tool_name: 'Bash', tool_input: { command }, reason, session_id: (JSON.parse(input) as { session_id?: string }).session_id, cwd }))
        .catch((err: unknown) => `\n\n（附註：擋下紀錄模組載入失敗，本次未記錄：${err instanceof Error ? err.message : String(err)}）`);

      // STEP 09: deny 這次 commit
      /** 有命中同時另有掃描失敗時的附註：命中照擋，但提醒掃描不完整 */
      const scanNote = scanError === null ? '' : `\n\n（附註：另有掃描失敗，結果可能不完整：${scanError}）`;
      console.log(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: reason + scanNote + logNote,
        },
      }));
      process.exit(0);
    } catch (err) {
      // 事件解析／欄位型別／其他未預期錯誤：不擋 commit，但以 exit 1 回報，不得與正常放行長得一樣
      console.error(`credential-commit-guard 內部錯誤，本次 commit 未經憑證掃描：${err instanceof Error ? err.message : String(err)}`);
      process.exit(1);
    }
  });
}
