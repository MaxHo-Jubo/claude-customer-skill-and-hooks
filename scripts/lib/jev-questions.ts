import fs from 'fs';
import os from 'os';
import path from 'path';

/**
 * Jev（TypeSafe systemOne）題目定義
 *
 * 離線評估（scripts/jev-eval/run-eval.ts）與 hook 共用同一份題目，
 * 確保評估出來的準確率與門檻，對應的就是 hook 實際送出的題目。
 * 題目文字改動 → 必須重跑評估，舊門檻失效。
 */

/** systemOne 的單一題目，對應 HTTP payload `questions` 的值 */
export interface JevQuestion {
  /** 題型：choice 單選、noul 是非題（回傳為「是」的機率） */
  type: 'choice' | 'noul';
  /** 題目本身 */
  instructions: string;
  /** choice 的選項：標籤 → 說明；noul 不帶 */
  criteria?: Record<string, string>;
}

/** plugin／內建 skill 的說明：本機沒有 SKILL.md，取自 Claude Code 的 skill 清單原文 */
const EXTERNAL_SKILLS: Record<string, string> = {
  'code-review': 'Review the current diff, or a PR number/branch/path target, for correctness bugs.',
  simplify: 'Review the changed code for reuse, simplification, efficiency, and altitude cleanups, then apply the fixes. Quality only — it does not hunt for bugs; use /code-review for that.',
  'atlassian:search-company-knowledge': 'Search across company knowledge bases (Confluence, Jira, internal docs) to find and explain internal concepts, processes, and technical details.',
  'atlassian:triage-issue': 'Intelligently triage bug reports and error messages by searching for duplicates in Jira and offering to create new issues or add comments to existing ones.',
  'atlassian:generate-status-report': 'Generate project status reports from Jira issues and publish to Confluence.',
  'atlassian:capture-tasks-from-meeting-notes': 'Analyze meeting notes to find action items and create Jira tasks for assigned work.',
  'atlassian:spec-to-backlog': 'Automatically convert Confluence specification documents into structured Jira backlogs with Epics and implementation tickets.',
  'claude-mem:mem-search': 'Search claude-mem\'s persistent cross-session memory database. Use when user asks "did we already solve this?", "how did we do X last time?", or needs work from previous sessions.',
};

/** 「不需要任何 skill」的選項標籤 */
export const NO_SKILL = 'none';

/** Claude Code 設定根目錄 */
const CLAUDE_DIR = path.join(os.homedir(), '.claude');
/** 本機 skill 目錄 */
const SKILLS_DIR = path.join(CLAUDE_DIR, 'skills');
/**
 * skillOverrides 中對模型隱藏 skill 的值（Claude Code 2.1.278 原文：
 * "user-invocable-only" hides it from the model but keeps /name; "off" hides it from both；name-only 仍可被模型呼叫）
 */
const HIDDEN_OVERRIDES = new Set(['off', 'user-invocable-only']);

/** SKILL.md frontmatter 中本模組用到的欄位 */
interface SkillMeta {
  /** skill 說明，作為 Jev 的選項說明 */
  description?: unknown;
  /** 作者設為 true 時模型不能自動呼叫 */
  'disable-model-invocation'?: unknown;
}

/**
 * 依 user → 專案 → 專案 local 的順序合併各層 skillOverrides，後者覆蓋前者
 * @param projectDir - 專案根目錄；未提供時只讀 user 層
 * @returns skill 名稱 → override 值
 */
function readSkillOverrides(projectDir?: string): Record<string, string> {
  // STEP 01: 依優先序列出設定檔
  const files = [path.join(CLAUDE_DIR, 'settings.json')];
  if (projectDir) {
    files.push(path.join(projectDir, '.claude', 'settings.json'), path.join(projectDir, '.claude', 'settings.local.json'));
  }
  // STEP 02: 逐檔合併；專案層設定檔本來就可能不存在，存在但 JSON 壞掉則丟錯
  let merged: Record<string, string> = {};
  for (const f of files) {
    if (!fs.existsSync(f)) {
      continue;
    }
    const s = JSON.parse(fs.readFileSync(f, 'utf-8')) as { skillOverrides?: Record<string, string> };
    merged = { ...merged, ...s.skillOverrides };
  }
  return merged;
}

/**
 * 解析 SKILL.md 的 YAML frontmatter（description 有單行、引號、> 摺疊、| 區塊等寫法，不能用正則只抓單行）
 * @param name - skill 目錄名稱
 * @returns frontmatter 欄位
 */
function readSkillMeta(name: string): SkillMeta {
  // STEP 01: 取開頭兩個 --- 之間的內容；沒有 frontmatter 直接丟錯，不默默略過該 skill
  const text = fs.readFileSync(path.join(SKILLS_DIR, name, 'SKILL.md'), 'utf-8');
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!m) {
    throw new Error(`${name}/SKILL.md 沒有 frontmatter`);
  }
  // STEP 02: YAML 解析
  return Bun.YAML.parse(m[1]) as SkillMeta;
}

/**
 * 列出模型可自動呼叫的本機 skill，規則比照 Claude Code 的 skill 清單：
 * 有 SKILL.md、未被 skillOverrides 設為 off／user-invocable-only、未設 disable-model-invocation
 * @param projectDir - 專案根目錄，用來讀專案層 skillOverrides
 * @returns skill 名稱 → description
 */
function listLocalSkills(projectDir?: string): Record<string, string> {
  // STEP 01: 沒有 SKILL.md 的目錄（*-workspace 等）不是 skill；被 override 隱藏的不讀檔
  const overrides = readSkillOverrides(projectDir);
  const names = fs.readdirSync(SKILLS_DIR)
    .filter((n) => fs.existsSync(path.join(SKILLS_DIR, n, 'SKILL.md')) && !HIDDEN_OVERRIDES.has(overrides[n]))
    .sort();
  // STEP 02: 讀 frontmatter；作者自設 disable-model-invocation 的排除，缺 description 丟錯
  const skills: Record<string, string> = {};
  for (const n of names) {
    const meta = readSkillMeta(n);
    if (meta['disable-model-invocation'] === true) {
      continue;
    }
    if (typeof meta.description !== 'string' || !meta.description.trim()) {
      throw new Error(`${n}/SKILL.md 缺 description`);
    }
    skills[n] = meta.description.trim();
  }
  return skills;
}

/**
 * 路由三題：skill、是否糾正、任務類型（對應試用計畫掛載點 A）
 * @param projectDir - 專案根目錄（hook 傳 CLAUDE_PROJECT_DIR）；評估不傳，只套 user 層 skillOverrides
 * @returns 題目集合，state 應為 `{ user_message }`
 */
export function routingQuestions(projectDir?: string): Record<string, JevQuestion> {
  // STEP 01: 組 skill 選項（本機動態讀取＋外部常數＋none）
  const skills = listLocalSkills(projectDir);
  // STEP 02: 回傳三題
  return {
    skill: {
      type: 'choice',
      instructions: '這則開發者傳給 AI coding 助理的訊息，最適合用哪個 skill 處理',
      criteria: { ...skills, ...EXTERNAL_SKILLS, [NO_SKILL]: '沒有任何一個上列 skill 符合這則訊息的需求' },
    },
    correction: {
      type: 'noul',
      instructions: '使用者在這則訊息中表示 AI 助理前一個回答或動作錯了、或不是他要的。使用者回報程式或資料本身的異常不算',
    },
    task_type: {
      type: 'choice',
      instructions: '這則開發者傳給 AI coding 助理的訊息屬於哪一類任務',
      criteria: {
        question: '只要資訊或解釋，不要求改任何東西',
        small_change: '範圍明確的單點修改（單檔 bug、錯字、改數值、單一方法重構）',
        debug: '有異常但原因未知或待確認，要先查',
        multi_step: '新功能、跨檔／跨前後端修改、補整批測試',
        ops: '執行既有流程（跑 skill、review、同步、開單、產報告）',
      },
    },
  };
}

/** 完成宣告兩題（對應掛載點 B），state 應為 `{ assistant_message }` */
export const CLAIM_QUESTIONS: Record<string, JevQuestion> = {
  claims: {
    type: 'noul',
    instructions: '這則 AI 助理的回覆宣稱任務已完成、bug 已修好、或已找到根因',
  },
  evidence: {
    type: 'noul',
    instructions: '這則回覆附有具體驗證證據（指令輸出、測試結果、量測數字）。只說「已驗證」不算證據',
  },
};

/** 同錯判定一題（對應掛載點 C），state 應為 `{ previous_failure, current_failure }` */
export const REPEAT_QUESTIONS: Record<string, JevQuestion> = {
  same: {
    type: 'noul',
    instructions: '這次失敗跟上次是同一個問題（同一錯誤或同一個測試仍然失敗）。字面不同但根因相同也算',
  },
};
