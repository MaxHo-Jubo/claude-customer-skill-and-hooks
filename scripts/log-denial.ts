#!/usr/bin/env bun
/**
 * 給 bash guard 用的擋下紀錄 CLI：stdin 為 DenialInput JSON（見 lib/denial-log.ts），寫入 DENIALS.jsonl。
 * 輸入不合法或寫入失敗 → 另寫一筆到 ERRORS.jsonl、stderr + exit 1；由 bash guard 把失敗附在 deny 原因後，不影響 deny 本身。
 */
import { readFileSync } from 'fs';
import { logDenial, recordLogFailure } from './lib/denial-log';

/** stdin 原文（解析失敗時仍要能取出 guard 名稱留痕） */
let raw = '';
try {
  raw = readFileSync(0, 'utf8');
  logDenial(JSON.parse(raw));
} catch (err) {
  /** 失敗原因 */
  const message = err instanceof Error ? err.message : String(err);
  /** 盡量從原文取出 guard 名稱，取不到就標 unknown-guard */
  const guard = /"guard"\s*:\s*"([^"]+)"/.exec(raw)?.[1] ?? 'unknown-guard';
  recordLogFailure(guard, message);
  console.error(`log-denial: ${message}`);
  process.exit(1);
}
