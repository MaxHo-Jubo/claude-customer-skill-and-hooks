#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

/**
 * 為 auto memory markdown 檔案補上 Obsidian tags。
 * - 已有 frontmatter 的：加 tags 欄位
 * - 沒有 frontmatter 的：根據內容推斷 type 並加完整 frontmatter
 * - MEMORY.md 跳過（索引檔）
 */

// STEP 01: 專案路徑 → 專案標籤
function getProjectTag(filePath) {
  const map = {
    'HomeCareStaff-HomeCareStaffRN': '居服App',
    'luna-RN-HomeCareStaff': '居服App',
    'DayCareStaff-DayCareStaff': '日照App',
    'FamilyMember-FamilyMember': '家屬App',
    'luna-web-frontend': 'Luna-FE',
    'luna-web-backend': 'Luna-BE',
    'luna-web': 'Luna-Web',
    'erpv3-web-frontend': 'V3-FE',
    'renewContract': 'RenewContract',
    'process-moniter': 'Process-Monitor',
    'claude-usage': 'Claude-Usage',
    'onboard': 'Onboard',
    'claude-customer-skill-and-hooks': 'Skills-And-Hooks',
    'flutter-freelance-PT': 'Flutter-PT',
    'spec-presentation': 'Spec-Presentation',
  };

  for (const [key, tag] of Object.entries(map)) {
    if (filePath.includes(key)) {
      return tag;
    }
  }

  if (filePath.includes('-Users-maxhero/memory/')) {
    return 'Global';
  }

  return 'other';
}

// STEP 02: 根據內容推斷 type
function inferType(content, fileName) {
  const lower = content.toLowerCase();
  if (fileName.includes('lesson') || lower.includes('教訓') || lower.includes('lessons learned')) {
    return 'feedback';
  }
  if (lower.includes('踩過的坑') || lower.includes('pitfall') || lower.includes('踩坑')) {
    return 'feedback';
  }
  if (lower.includes('反思') || lower.includes('anti-pattern') || lower.includes('過度設計')) {
    return 'feedback';
  }
  if (lower.includes('進度') || lower.includes('branch') || lower.includes('erpd-') || lower.includes('lvb-')) {
    return 'project';
  }
  if (lower.includes('索引') || lower.includes('inventory') || lower.includes('待辦')) {
    return 'reference';
  }
  if (lower.includes('流程') || lower.includes('workflow') || lower.includes('指南')) {
    return 'reference';
  }
  return 'project';
}

// STEP 03: 根據 type 產生 tags
function buildTags(type, projectTag, content) {
  const tags = [type, projectTag];

  // 額外語意 tags
  if (content.includes('CI/CD') || content.includes('cicd') || content.includes('fastlane')) {
    tags.push('cicd');
  }
  if (content.includes('spec') || content.includes('Spec')) {
    tags.push('spec');
  }
  if (content.includes('test') || content.includes('測試') || content.includes('Maestro')) {
    tags.push('testing');
  }
  if (content.includes('重構') || content.includes('refactor')) {
    tags.push('refactor');
  }

  return [...new Set(tags)];
}

// STEP 04: 處理所有檔案
const projectsDir = path.join(process.env.HOME, '.claude/projects');
const files = execSync(`find "${projectsDir}" -path "*/memory/*.md" -not -name "MEMORY.md" -type f`, { encoding: 'utf8' })
  .trim()
  .split('\n')
  .filter(Boolean);

let updated = 0;
let skipped = 0;

for (const filePath of files) {
  const content = fs.readFileSync(filePath, 'utf8');
  const fileName = path.basename(filePath);
  const projectTag = getProjectTag(filePath);

  // 已有 tags 的跳過
  if (content.match(/^tags:/m) && content.startsWith('---')) {
    skipped++;
    continue;
  }

  let newContent;

  if (content.startsWith('---')) {
    // 有 frontmatter 但沒 tags，在第二個 --- 前插入 tags
    const endIndex = content.indexOf('---', 3);
    if (endIndex === -1) {
      skipped++;
      continue;
    }

    const frontmatter = content.slice(3, endIndex).trim();
    const body = content.slice(endIndex + 3);

    // 從 frontmatter 取 type
    const typeMatch = frontmatter.match(/type:\s*(\w+)/);
    const type = typeMatch ? typeMatch[1] : inferType(content, fileName);
    const tags = buildTags(type, projectTag, content);

    newContent = `---\n${frontmatter}\ntags: [${tags.join(', ')}]\n---${body}`;
  } else {
    // 沒有 frontmatter，加完整的
    const type = inferType(content, fileName);
    const tags = buildTags(type, projectTag, content);
    const name = fileName.replace('.md', '').replace(/-/g, ' ');

    newContent = `---\nname: ${name}\ntype: ${type}\ntags: [${tags.join(', ')}]\n---\n\n${content}`;
  }

  fs.writeFileSync(filePath, newContent, 'utf8');
  updated++;
  console.log(`✓ ${projectTag}/${fileName} [${inferType(content, fileName)}]`);
}

console.log(`\n完成: 更新 ${updated} 個, 跳過 ${skipped} 個`);
