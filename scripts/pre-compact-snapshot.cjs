#!/usr/bin/env node
'use strict';

/**
 * PreCompact hook: context 壓縮前自動提醒 Claude 存重要資訊到 auto memory。
 *
 * 觸發條件: Claude Code 即將壓縮 context window
 * 輸出: 提醒訊息，讓 Claude 在壓縮前把關鍵決策/糾正存到 auto memory
 */

const msg = `
⚠️ Context 即將壓縮 — 請在壓縮前檢查是否有以下資訊需要存到 auto memory：
- 使用者的糾正或偏好（→ feedback memory）
- 重要的架構決策或技術選擇（→ project memory）
- 本次 session 發現的關鍵資訊（→ reference memory）

若無需保存則忽略此提醒。
`.trim();

console.log(msg);
