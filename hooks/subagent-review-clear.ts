#!/usr/bin/env bun
/**
 * SubagentStop hook：記錄子 agent 的 agent_type，供型別比對與長期趨勢佐證。
 *
 * **不能用於單輪 chain 完整度判定**——本 log 無 session_id，無法把任一行歸屬到某一輪 Tier 3。
 *
 * 【2026-08-17 職責變更】本 hook 已**停止清除** pending-review marker，只保留 debug log。
 *
 * 移除原因：舊行為是「agent_type 含 review → 清 marker」，在 Tier 3 並行多面向時會提前解除閘門。
 * Tier 3 同時 spawn pr-reviewer lite 與 5 個 pr-review-toolkit:* agent，這些型別全部命中 /review/i，
 * **第一個完成的就把 marker 清掉**——其餘面向回不回來、Critical 有沒有修，PreToolUse 的 commit deny
 * 與 Stop 的回合攔截都已放行。full review 的面向 agent（如 pr-1134-full-review、pr-review-10829）同樣
 * 命中該 pattern，會誤清當前 repo 的 commit marker。判定依據（型別含 review）與待判定的事實
 * （review chain 是否跑完）根本不對應，故整個移除而非調整 pattern。
 *
 * 改由 skills/commit-review/SKILL.md §5 在「所有面向結果收齊 + Critical 處理完」後顯式清除。
 * 防 brick 仍由既有三層負責：marker 逾 4 小時自動清除（scripts/lib/review-marker.ts 的 readValidMarker，兩個閘門共用）、Stop hook per-session
 * 有界計數（MAX_STOP_BLOCKS=3）、手動 `bun ~/.claude/scripts/clear-pending-review.ts --force="<理由>"`（權威解鎖方式；
 * 自 2026-08-19 起裸執行會因缺 --aspects-done 而拒絕，這是刻意的）。
 *
 * 保留 debug log 的理由：這是 agent_type 實際值的唯一實測來源。
 *
 * 【觀測盲區，勿再拿本 log 當量化證據】2026-08-17 統計 2724 筆中 **2118 筆（78%）型別為空**，
 * 且每行只有 `timestamp \t agent_type`——沒有 session_id，無法把任何一行歸屬到某一輪 Tier 3。
 * 因此五個面向的完成次數（15/14/13/11/10）只能當**佐證**，證明不了「某一輪縮水」：
 * 落差同樣可以只是「部分 stop 記成空」，也無法區分「一輪少 5 個」與「五輪各少 1 個」。
 * 面向縮水的**主證據**是 claude-mem observation 13128（Tier 3 首次實戰明確記錄只 spawn 3 個
 * agent 並列出是哪三個），不是本 log。
 *
 * 78% 空值率同時也是「不改用 hook 計數遞減解鎖」的真正理由：以 agent_type 計數的閘門在多數
 * 情境根本認不出 agent 是誰，fail-closed 會 brick、fail-open 等於沒有。
 *
 * 失敗一律 fail-open（exit 0），絕不影響子 agent 或主流程。
 */
import { appendFileSync, mkdirSync } from 'fs';
import { join } from 'path';
import { MARKER_DIR } from '../scripts/lib/review-marker';

let input = '';
process.stdin.setEncoding('utf8');

const stdinTimeout = setTimeout(() => { process.exit(0); }, 2000);

process.stdin.on('data', (chunk: string) => { input += chunk; });
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);
    /** SubagentStop payload 的 agent 型別（不同版本可能用 agent_type 或 subagent_type） */
    const agentType: string = data.agent_type || data.subagent_type || '';

    // STEP 01: 記錄本次 agent_type，供型別比對與趨勢佐證
    logDebug(agentType);
    process.exit(0);
  } catch {
    // 記錄「payload 解析失敗」而非讓該行消失——分不清「型別是空的」與「根本沒 parse 成功」
    // 正是造成本檔 78% 空值率無法解讀的來源之一
    logDebug('(parse-error)');
    process.exit(0);
  }
});

/**
 * 把 SubagentStop 的 agent_type 記入 debug log，供型別值實測與趨勢佐證。
 * @param agentType 本次子 agent 的型別
 */
function logDebug(agentType: string): void {
  try {
    mkdirSync(MARKER_DIR, { recursive: true });
    const logPath = join(MARKER_DIR, 'subagent-stop-debug.log');
    appendFileSync(logPath, `${new Date().toISOString()}\t${agentType || '(empty)'}\n`, 'utf8');
  } catch {
    // debug log 失敗不影響主流程
  }
}
