#!/usr/bin/env bun
/**
 * 憑證 pre-commit 掃描：掃「這次 commit 會帶進去的新增行」，命中就 exit 1。
 *
 * 用途：`hooks/credential-commit-guard.ts` 在 PreToolUse 看到 git commit 時已自動掃描，但
 * `git add X && git commit` 寫在同一個 Bash 指令時，hook 觸發當下 add 還沒執行、暫存區看不到 X，
 * 掃不到（該 hook 檔頭「已知限制」）。這種寫法請把本腳本串在 add 與 commit 之間：
 *
 *   git add X && bun ~/.claude/scripts/credential-scan.ts && git commit -m "…"
 *
 * 命中時 exit 1，`&&` 會自動中止後面的 commit——不靠自覺（2026-10-09 有 session 手寫「掃描＋commit」
 * 少了 exit，含命中檔的 commit 73ffd95 被建出後才 soft reset）。
 *
 * pattern 與掃描邏輯不在這裡複製，直接 import credential-commit-guard.ts 匯出的 scanAdded
 * （單一來源 CREDENTIAL_PATTERN）：2026-10 週檢討 ae6c 手打 pattern 8 次有 5 次是縮水版
 * （缺 AIza／私鑰／github_pat_），所以不再提供「手打 pattern」的路徑。
 *
 * 用法：bun ~/.claude/scripts/credential-scan.ts [--all] [repo 路徑，預設 cwd]
 *   預設只掃暫存區（git diff --cached）；--all 另掃未暫存的已追蹤變更（對應 git commit -a）。
 * 輸出：只列命中的檔名，不印內容（LOG-SAFETY）。
 * 退出碼：0 沒有命中；1 有命中；2 掃描沒跑成（不是 git repo、git／grep 失敗）——
 *   掃描失敗與「沒命中」必須能區分，所以不 exit 0。
 */
import { scanAdded } from '../hooks/credential-commit-guard';
import { resolveRepoRoot } from './lib/review-marker';

/** 沒有命中 */
const EXIT_CLEAN = 0;
/** 有命中，應停止 commit */
const EXIT_HIT = 1;
/** 掃描沒跑成 */
const EXIT_ERROR = 2;

/**
 * 解析命令列：--all 旗標與可選的 repo 路徑。
 * @param argv process.argv 去掉前兩項後的參數
 * @returns 是否帶 --all，以及 repo 路徑（未給為 null）
 * @throws 出現未知旗標，或給了多個路徑
 */
export function parseArgs(argv: string[]): { all: boolean; repo: string | null } {
  // STEP 01: 初始化結果
  /** 是否帶 --all */
  let all = false;
  /** 指定的 repo 路徑 */
  let repo: string | null = null;
  // STEP 02: 逐個參數分類——--all、未知旗標（拋錯）、第一個路徑、多餘路徑（拋錯）
  for (const arg of argv) {
    if (arg === '--all') {
      all = true;
    } else if (arg.startsWith('-')) {
      throw new Error(`未知旗標：${arg}（只支援 --all）`);
    } else if (repo === null) {
      repo = arg;
    } else {
      throw new Error(`只能指定一個 repo 路徑，收到多個：${repo}、${arg}`);
    }
  }
  return { all, repo };
}

/**
 * 掃描並回報。
 * @param argv 命令列參數
 * @returns 退出碼（0／1／2）
 */
export function run(argv: string[]): number {
  try {
    // STEP 01: 解析參數與 repo 根目錄
    /** 解析後的參數 */
    const { all, repo } = parseArgs(argv);
    /** repo 根目錄；不是 git repo 為 null */
    const root = resolveRepoRoot(repo ?? process.cwd());
    if (root === null) {
      throw new Error(`找不到 git repo 根目錄：${repo ?? process.cwd()}`);
    }

    // STEP 02: 掃暫存區；--all 另掃未暫存的已追蹤變更，兩者命中合併去重
    /** 命中的檔名（去重） */
    const hits = new Set<string>(scanAdded(root, ['--cached']));
    if (all) {
      for (const f of scanAdded(root, [])) {
        hits.add(f);
      }
    }

    // STEP 03: 回報——只列檔名
    if (hits.size > 0) {
      console.log(`❌ 憑證掃描命中 ${hits.size} 個檔案，停止 commit（只列檔名，不印內容）：`);
      for (const f of hits) {
        console.log(`  ${f}`);
      }
      return EXIT_HIT;
    }
    console.log(`✅ 憑證掃描通過（${all ? '暫存區與未暫存的已追蹤變更' : '暫存區'}新增行）`);
    return EXIT_CLEAN;
  } catch (e: unknown) {
    console.error(`⚠️ 憑證掃描沒跑成（不是「沒命中」）：${e instanceof Error ? e.message : String(e)}`);
    return EXIT_ERROR;
  }
}

if (import.meta.main) {
  process.exit(run(process.argv.slice(2)));
}
