#!/usr/bin/env bun
import fs from 'fs';
import path from 'path';

/**
 * Skill Activation Hook
 *
 * 攔截 UserPromptSubmit，根據 skill-rules.json 的關鍵字/意圖規則
 * 比對使用者 prompt，自動附加相關 skill 建議。
 *
 * 環境變數：
 * - CLAUDE_USER_CONTENT: 使用者的 prompt 內容
 *
 * 輸出 JSON:stdout:
 * - { "result": "append", "content": "..." } 附加建議
 * - { "result": "approve" } 無匹配時直接放行
 */

/** skill-rules.json 中每個 skill 的觸發設定 */
interface SkillConfig {
  promptTriggers: {
    keywords?: string[];
    intentPatterns?: string[];
  };
  priority?: 'critical' | 'high' | 'medium' | 'low';
}

/** skill-rules.json 的頂層結構 */
interface SkillRules {
  skills: Record<string, SkillConfig>;
}

/** 推薦紀錄，記錄每個 skill 被推薦的時間戳 */
interface RecommendationLog {
  recommended: Record<string, number>;
  sessionStart: number | null;
}

// STEP 01: 讀取使用者 prompt
const userPrompt = process.env.CLAUDE_USER_CONTENT || '';
if (!userPrompt.trim()) {
  console.log(JSON.stringify({ result: 'approve' }));
  process.exit(0);
}

// STEP 02: 讀取 skill-rules.json
const rulesPath = path.join(process.env.HOME!, '.claude', 'skills', 'skill-rules.json');
let rules: SkillRules;
try {
  rules = JSON.parse(fs.readFileSync(rulesPath, 'utf-8'));
} catch {
  // 規則檔不存在或損壞，直接放行
  console.log(JSON.stringify({ result: 'approve' }));
  process.exit(0);
}

// STEP 03: 讀取 session 推薦紀錄，避免重複建議
const logDir = path.join(process.env.HOME!, '.claude', 'skills');
const logPath = path.join(logDir, 'recommendation-log.json');
let recommendationLog: RecommendationLog = { recommended: {}, sessionStart: null };
try {
  recommendationLog = JSON.parse(fs.readFileSync(logPath, 'utf-8'));
  // STEP 03.01: 清除超過 7 天的紀錄
  const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  if (recommendationLog.sessionStart && recommendationLog.sessionStart < sevenDaysAgo) {
    recommendationLog = { recommended: {}, sessionStart: Date.now() };
  }
} catch {
  recommendationLog = { recommended: {}, sessionStart: Date.now() };
}

// STEP 04: 比對每個 skill 的觸發規則
/** 正規化 prompt：轉小寫，移除多餘空白 */
const normalizedPrompt = userPrompt.toLowerCase().replace(/\s+/g, ' ').trim();

/** 匹配結果，按 priority 分組 */
const matches: Record<string, string[]> = { critical: [], high: [], medium: [], low: [] };

for (const [skillName, config] of Object.entries(rules.skills)) {
  // STEP 04.01: 跳過此 session 已推薦過的 skill
  if (recommendationLog.recommended[skillName]) {
    continue;
  }

  const { promptTriggers, priority = 'medium' } = config;
  let matched = false;

  // STEP 04.02: 關鍵字比對
  if (promptTriggers.keywords) {
    for (const keyword of promptTriggers.keywords) {
      if (normalizedPrompt.includes(keyword.toLowerCase())) {
        matched = true;
        break;
      }
    }
  }

  // STEP 04.03: 意圖正則比對
  if (!matched && promptTriggers.intentPatterns) {
    for (const pattern of promptTriggers.intentPatterns) {
      try {
        const regex = new RegExp(pattern, 'i');
        if (regex.test(userPrompt)) {
          matched = true;
          break;
        }
      } catch {
        // 無效正則，跳過
      }
    }
  }

  // STEP 04.04: 記錄匹配
  if (matched) {
    matches[priority].push(skillName);
  }
}

// STEP 05: 組合建議訊息
const allMatches = [
  ...matches.critical,
  ...matches.high,
  ...matches.medium,
  ...matches.low
];

if (allMatches.length === 0) {
  console.log(JSON.stringify({ result: 'approve' }));
  process.exit(0);
}

// STEP 06: 建立建議文字
let suggestion = '\n\n---\nSKILL ACTIVATION CHECK\n';

if (matches.critical.length > 0) {
  suggestion += '\nCRITICAL SKILLS (REQUIRED):\n';
  for (const s of matches.critical) {
    suggestion += `  -> ${s}\n`;
  }
}

if (matches.high.length > 0) {
  suggestion += '\nRECOMMENDED SKILLS:\n';
  for (const s of matches.high) {
    suggestion += `  -> ${s}\n`;
  }
}

if (matches.medium.length > 0) {
  suggestion += '\nSUGGESTED SKILLS:\n';
  for (const s of matches.medium) {
    suggestion += `  -> ${s}\n`;
  }
}

if (matches.low.length > 0) {
  suggestion += '\nOPTIONAL SKILLS:\n';
  for (const s of matches.low) {
    suggestion += `  -> ${s}\n`;
  }
}

suggestion += '\nACTION: Consider using the Skill tool for the above skills if relevant to the task.\n';

// STEP 07: 更新推薦紀錄
for (const s of allMatches) {
  recommendationLog.recommended[s] = Date.now();
}
try {
  fs.writeFileSync(logPath, JSON.stringify(recommendationLog, null, 2));
} catch {
  // 寫入失敗不阻擋流程
}

// STEP 08: 輸出附加建議
console.log(JSON.stringify({
  result: 'append',
  content: suggestion
}));
