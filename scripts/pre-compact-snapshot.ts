#!/usr/bin/env bun

/**
 * PreCompact hook: 壓縮前遞增計數，並以 systemMessage 顯示觸發資訊與保留規則給使用者。
 * 合併原 compact-counter.sh 功能。
 *
 * 觸發條件: Claude Code 即將壓縮 context window
 * 輸出: JSON systemMessage（plain stdout 不進 Claude context，故用此格式）
 *       計數檔寫入 ~/.claude/compact-counts/<sessionId>.count
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";

// STEP 01: 讀取 hook input
const raw = await Bun.stdin.text();
const input = raw ? JSON.parse(raw) : {};

/** session 識別碼，供計數用 */
const sessionId: string = input.session_id ?? input.sessionId ?? "";
/** 觸發來源：manual（/compact）或 auto（context 將滿） */
const trigger: string = input.trigger ?? "unknown";
/** 使用者在 /compact 後輸入的自訂指令（auto 時為空） */
const customInstructions: string = input.custom_instructions ?? "";

// STEP 02: 遞增 compact count
let compactCount = 0;
if (sessionId) {
  const countDir = join(homedir(), ".claude", "compact-counts");
  mkdirSync(countDir, { recursive: true });
  const countFile = join(countDir, `${sessionId}.count`);
  if (existsSync(countFile)) {
    compactCount = parseInt(readFileSync(countFile, "utf8").trim() || "0", 10);
  }
  compactCount += 1;
  writeFileSync(countFile, String(compactCount));
}

// STEP 03: 從 CLAUDE.md 擷取 <compact> 區段
function extractCompactSection(claudeMdPath: string): string {
  if (!existsSync(claudeMdPath)) { return ""; }
  const content = readFileSync(claudeMdPath, "utf8");
  const match = content.match(/<compact[\s\S]*?>([\s\S]*?)<\/compact>/);
  return match ? match[1].trim() : "";
}

const claudeMdPath = join(homedir(), ".claude", "CLAUDE.md");
const compactSection = extractCompactSection(claudeMdPath);

// STEP 04: 組合 systemMessage
const triggerLabel = trigger === "manual" ? "手動 /compact" : "自動（context 將滿）";
const lines: string[] = [
  `⚠️ Context 即將壓縮 [${triggerLabel}]${sessionId ? ` — 第 ${compactCount} 次` : ""}`,
];
if (customInstructions) {
  lines.push(`  自訂指令: ${customInstructions}`);
}
if (compactSection) {
  lines.push("", compactSection);
}

console.log(JSON.stringify({ systemMessage: lines.join("\n") }));
