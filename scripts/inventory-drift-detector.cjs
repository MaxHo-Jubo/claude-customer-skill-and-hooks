/**
 * Inventory Drift Detector
 *
 * PostToolUse hook：偵測 skill / hook / plugin 相關檔案的變更，
 * 比對 inventory.md 和 skill-rules.json 是否需要同步更新。
 *
 * 觸發條件：Write 或 Edit 工具修改了以下路徑的檔案：
 * - ~/.claude/skills/
 * - ~/.claude/hooks/
 * - ~/.claude/plugins/
 * - ~/.claude/settings.json
 * - ~/.claude/scripts/*hook*.cjs
 *
 * 環境變數：
 * - CLAUDE_TOOL_NAME: 工具名稱（Write / Edit）
 * - CLAUDE_FILE_PATHS: 被修改的檔案路徑
 * - CLAUDE_TOOL_INPUT: 工具的輸入參數（JSON）
 */

const fs = require('fs');
const path = require('path');

const HOME = process.env.HOME || '';
const CLAUDE_DIR = path.join(HOME, '.claude');

// STEP 01: 取得被修改的檔案路徑
const toolName = process.env.CLAUDE_TOOL_NAME || '';
if (!['Write', 'Edit'].includes(toolName)) {
  process.exit(0);
}

let filePath = '';
try {
  const input = JSON.parse(process.env.CLAUDE_TOOL_INPUT || '{}');
  filePath = input.file_path || '';
} catch {
  process.exit(0);
}

if (!filePath) {
  process.exit(0);
}

// STEP 02: 判斷是否為 skill/hook/plugin 相關檔案
const watchPaths = [
  path.join(CLAUDE_DIR, 'skills'),
  path.join(CLAUDE_DIR, 'hooks'),
  path.join(CLAUDE_DIR, 'plugins'),
  path.join(CLAUDE_DIR, 'scripts'),
];
const watchFiles = [
  path.join(CLAUDE_DIR, 'settings.json'),
];

// 排除 inventory 和 skill-rules 自身的修改，避免無限迴圈
const selfFiles = [
  path.join(CLAUDE_DIR, 'skills', 'skill-rules.json'),
  path.join(CLAUDE_DIR, 'skills', 'recommendation-log.json'),
  path.join(HOME, '.claude', 'projects', '-Users-maxhero', 'memory', 'inventory.md'),
  path.join(HOME, '.claude', 'projects', '-Users-maxhero', 'memory', 'MEMORY.md'),
];

if (selfFiles.some(sf => filePath === sf)) {
  process.exit(0);
}

const isRelevant =
  watchPaths.some(wp => filePath.startsWith(wp)) ||
  watchFiles.some(wf => filePath === wf);

if (!isRelevant) {
  process.exit(0);
}

// STEP 03: 掃描目前的 skills
/**
 * 遞迴搜尋目錄下的 SKILL.md 檔案
 * @param {string} dir - 搜尋目錄
 * @returns {string[]} SKILL.md 檔案路徑列表
 */
function findSkillFiles(dir) {
  const results = [];
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        results.push(...findSkillFiles(fullPath));
      } else if (entry.name === 'SKILL.md' || entry.name.endsWith('.md')) {
        if (entry.name === 'SKILL.md') {
          results.push(fullPath);
        }
      }
    }
  } catch {
    // 目錄不存在或無權限
  }
  return results;
}

/** 從 SKILL.md 的父目錄名稱推導 skill 名稱 */
function getSkillName(skillMdPath) {
  return path.basename(path.dirname(skillMdPath));
}

// STEP 04: 掃描目前的自訂 skills
const userSkillsDir = path.join(CLAUDE_DIR, 'skills');
const currentUserSkills = findSkillFiles(userSkillsDir).map(getSkillName);

// STEP 05: 讀取 inventory.md 中已記錄的 skills
const inventoryPath = path.join(HOME, '.claude', 'projects', '-Users-maxhero', 'memory', 'inventory.md');
let inventoryContent = '';
try {
  inventoryContent = fs.readFileSync(inventoryPath, 'utf-8');
} catch {
  // 檔案不存在
}

// STEP 06: 讀取 skill-rules.json 中已有規則的 skills
const rulesPath = path.join(CLAUDE_DIR, 'skills', 'skill-rules.json');
let rulesContent = {};
try {
  rulesContent = JSON.parse(fs.readFileSync(rulesPath, 'utf-8'));
} catch {
  // 檔案不存在或損壞
}
const ruledSkills = Object.keys(rulesContent.skills || {});

// STEP 07: 比對差異
const drifts = [];

// STEP 07.01: 檢查有沒有新的自訂 skill 未被 inventory 記錄
for (const skill of currentUserSkills) {
  if (!inventoryContent.includes(skill)) {
    drifts.push(`[新增 Skill] "${skill}" 存在於 ~/.claude/skills/ 但未記錄在 inventory.md`);
  }
}

// STEP 07.02: 檢查有沒有自訂 skill 未被 skill-rules.json 涵蓋
for (const skill of currentUserSkills) {
  // 跳過純目錄結構的 skill（如 gitnexus 系列會用完整名稱）
  const matchesRule = ruledSkills.some(r =>
    r === skill || r.includes(skill) || skill.includes(r.split(':').pop())
  );
  if (!matchesRule) {
    drifts.push(`[缺少觸發規則] "${skill}" 沒有對應的 skill-rules.json 觸發規則`);
  }
}

// STEP 07.03: 檢查 settings.json hooks 的變更
if (filePath === path.join(CLAUDE_DIR, 'settings.json')) {
  drifts.push('[Hook 變更] settings.json 已修改，inventory.md 的 Hooks 區塊可能需要更新');
}

// STEP 07.04: 檢查 plugin 目錄變更
if (filePath.startsWith(path.join(CLAUDE_DIR, 'plugins'))) {
  drifts.push(`[Plugin 變更] ${path.basename(filePath)} 已修改，inventory.md 的 Plugins 區塊可能需要更新`);
}

// STEP 07.05: 檢查 hook 腳本變更
if (filePath.startsWith(path.join(CLAUDE_DIR, 'hooks')) ||
    filePath.startsWith(path.join(CLAUDE_DIR, 'scripts'))) {
  drifts.push(`[Hook 腳本變更] ${path.basename(filePath)} 已修改，inventory.md 的 Hooks 區塊可能需要更新`);
}

// STEP 08: 輸出結果
if (drifts.length > 0) {
  const message = [
    '',
    '📋 Inventory Drift Detection',
    '─'.repeat(40),
    ...drifts,
    '',
    '受影響的檔案：',
    `  - ${inventoryPath}`,
    `  - ${rulesPath}`,
    '',
    '請更新上述檔案以保持索引同步。',
  ].join('\n');

  console.log(message);
}
