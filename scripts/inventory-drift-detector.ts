#!/usr/bin/env bun
import fs from 'fs';
import path from 'path';

/**
 * Inventory Drift Detector
 *
 * 偵測 skill / hook / plugin 相關檔案的變更，
 * 比對 inventory.md 是否需要同步更新。
 * 由 ~/.claude/mods/tool-reminders 在 Write/Edit 後呼叫，stdout 經 tool.call 的 context 送給 model。
 *
 * 觸發條件：Write 或 Edit 工具修改了以下路徑的檔案：
 * - ~/.claude/skills/（不含 claude.ai 同步的 skills/synced/）
 * - ~/.claude/hooks/
 * - ~/.claude/plugins/
 * - ~/.claude/scripts/
 * - ~/.claude/settings.json
 *
 * 輸入：stdin 為 PostToolUse 輸入格式的子集（`tool_name`、`tool_input.file_path`）。
 * 輸出：有 drift 印純文字，無 drift 不輸出。
 * 失敗：輸入不符契約、HOME 未設定、路徑無法解析、skills 掃描或 inventory.md 讀取失敗 → stderr + exit 1，
 * 讓呼叫端回報「結果未知」，不與「沒有 drift」混為同一個 exit 0。
 */

/**
 * 以 stderr 回報失敗並 exit 1。
 * @param message - 失敗原因
 * @returns never（直接結束行程）
 */
function fail(message: string): never {
  console.error(`inventory-drift-detector: ${message}`);
  process.exit(1);
}

/**
 * 取得實體路徑（解開 symlink）；解析失敗即回報失敗。
 * @param p - 要解析的路徑
 * @returns 實體絕對路徑
 */
function realpathOrFail(p: string): string {
  try {
    return fs.realpathSync(p);
  } catch (err) {
    fail(`無法解析路徑 ${p}：${(err as Error).message}`);
  }
}

/**
 * 判斷路徑是否位於目錄之內（以路徑分隔符界定，避免 skills-old 這類同前綴目錄誤中）。
 * @param p - 要判斷的路徑
 * @param dir - 目錄
 * @returns 是否位於目錄內
 */
function isUnder(p: string, dir: string): boolean {
  return p.startsWith(dir + path.sep);
}

/** 使用者家目錄；未設定就無法定位 ~/.claude */
const HOME = process.env.HOME || fail('HOME 未設定');
/** ~/.claude 的實體路徑：多帳號下 ~/.claude-max-2/{skills,scripts,...} 是指向這裡的 symlink，比對前兩邊都取實體路徑 */
const CLAUDE_DIR = realpathOrFail(path.join(HOME, '.claude'));
/** claude.ai 同步下來的 skills（由平台管理、不進 inventory），掃描與觸發都排除 */
const SYNCED_SKILLS_DIR = path.join(CLAUDE_DIR, 'skills', 'synced');

// STEP 01: 從 stdin 取得工具名稱與被修改的檔案路徑；兩者缺一都是呼叫端的 bug
/** 工具名稱（Write / Edit） */
let toolName = '';
/** stdin 帶入的原始檔案路徑（可能經過 symlink） */
let rawPath = '';
try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  toolName = input.tool_name || '';
  rawPath = input.tool_input?.file_path || '';
} catch (err) {
  fail(`stdin 不是合法 JSON：${(err as Error).message}`);
}

if (!['Write', 'Edit'].includes(toolName)) {
  fail(`tool_name 應為 Write 或 Edit，收到 ${JSON.stringify(toolName)}`);
}

if (!rawPath) {
  fail('stdin 缺少 tool_input.file_path');
}

// STEP 02: 以實體路徑判斷是否為 skill/hook/plugin 相關檔案（工具成功寫入後才呼叫，檔案必定存在）
/** 被修改檔案的實體路徑 */
const filePath = realpathOrFail(rawPath);
/** 監看的目錄 */
const watchPaths = [
  path.join(CLAUDE_DIR, 'skills'),
  path.join(CLAUDE_DIR, 'hooks'),
  path.join(CLAUDE_DIR, 'plugins'),
  path.join(CLAUDE_DIR, 'scripts'),
];
/** 監看的單一檔案 */
const watchFiles = [
  path.join(CLAUDE_DIR, 'settings.json'),
];

if (isUnder(filePath, SYNCED_SKILLS_DIR)) {
  process.exit(0);
}

const isRelevant =
  watchPaths.some(wp => isUnder(filePath, wp)) ||
  watchFiles.includes(filePath);

if (!isRelevant) {
  process.exit(0);
}

// STEP 03: 掃描目前的 skills
/**
 * 遞迴搜尋目錄下的 SKILL.md 檔案
 * @param dir - 搜尋目錄
 * @returns SKILL.md 檔案路徑列表
 */
function findSkillFiles(dir: string): string[] {
  const results: string[] = [];
  // STEP 01: 讀取目錄；掃描期間被刪除的目錄（ENOENT）略過，其他錯誤往外拋，由呼叫端回報失敗
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
      return results;
    }
    throw err;
  }
  // STEP 02: 遞迴收集 SKILL.md
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    // 排除平台同步的 skills 與相依套件內附帶的 SKILL.md（如 playwright-core 的 trace/skill）
    if (fullPath === SYNCED_SKILLS_DIR || entry.name === 'node_modules') {
      continue;
    }
    if (entry.isDirectory()) {
      results.push(...findSkillFiles(fullPath));
    } else if (entry.name === 'SKILL.md') {
      results.push(fullPath);
    }
  }
  return results;
}

/** 從 SKILL.md 的父目錄名稱推導 skill 名稱 */
function getSkillName(skillMdPath: string): string {
  return path.basename(path.dirname(skillMdPath));
}

// STEP 04: 掃描目前的自訂 skills
const userSkillsDir = realpathOrFail(path.join(CLAUDE_DIR, 'skills'));
/** 目前存在的自訂 skill 名稱 */
let currentUserSkills: string[] = [];
try {
  currentUserSkills = findSkillFiles(userSkillsDir).map(getSkillName);
} catch (err) {
  fail(`掃描 ${userSkillsDir} 失敗：${(err as Error).message}`);
}

// STEP 05: 讀取 inventory.md 中已記錄的 skills；讀不到時不可當成空檔（會把每個 skill 都誤報為未記錄）
const inventoryPath = path.join(CLAUDE_DIR, 'projects', '-Users-maxhero', 'memory', 'inventory.md');
let inventoryContent = '';
try {
  inventoryContent = fs.readFileSync(inventoryPath, 'utf-8');
} catch (err) {
  fail(`讀取 ${inventoryPath} 失敗：${(err as Error).message}`);
}

// STEP 06: 比對差異
/** 偵測到的 drift 訊息 */
const drifts: string[] = [];

// STEP 06.01: 檢查有沒有新的自訂 skill 未被 inventory 記錄
for (const skill of currentUserSkills) {
  if (!inventoryContent.includes(skill)) {
    drifts.push(`[新增 Skill] "${skill}" 存在於 ~/.claude/skills/ 但未記錄在 inventory.md`);
  }
}

// STEP 06.02: 檢查 settings.json hooks 的變更
if (filePath === path.join(CLAUDE_DIR, 'settings.json')) {
  drifts.push('[Hook 變更] settings.json 已修改，inventory.md 的 Hooks 區塊可能需要更新');
}

// STEP 06.03: 檢查 plugin 目錄變更
if (isUnder(filePath, path.join(CLAUDE_DIR, 'plugins'))) {
  drifts.push(`[Plugin 變更] ${path.basename(filePath)} 已修改，inventory.md 的 Plugins 區塊可能需要更新`);
}

// STEP 06.04: 檢查 hook 腳本變更
if (isUnder(filePath, path.join(CLAUDE_DIR, 'hooks')) ||
    isUnder(filePath, path.join(CLAUDE_DIR, 'scripts'))) {
  drifts.push(`[Hook 腳本變更] ${path.basename(filePath)} 已修改，inventory.md 的 Hooks 區塊可能需要更新`);
}

// STEP 07: 輸出結果
if (drifts.length > 0) {
  const message = [
    '',
    '📋 Inventory Drift Detection',
    '─'.repeat(40),
    ...drifts,
    '',
    `受影響的檔案：${inventoryPath}`,
    '請更新上述檔案以保持索引同步。',
  ].join('\n');

  console.log(message);
}
