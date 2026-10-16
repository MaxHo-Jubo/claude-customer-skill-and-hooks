// 累計統計：交接、整理、離席選擇、攔下的訊息與守門命中都記進 stats:<工作區>，只記帳、不改行為
import { expect, test } from 'claude-code/testing'
import { HANDOFF_FILE, cmd, ctl, distillNow, endTurn, pushGuard, resume, runSave, say, startSession, stop, world } from './test-world'
import type { Stats } from './records'

const statsOf = (w: ReturnType<typeof world>) => w.get('stats:C--proj') as Stats | undefined

// 本機改版：在場交接改跑 save-progress 存檔回合（runSave 模擬），失敗用「交接紀錄沒寫」模擬
test('統計：在場交接成功與交接期間攔下的訊息', async ($, on) => {
  const w = world(on, 650_000, 1_000_000, {}, [], 5)
  await startSession($)
  await stop($)
  await w.clock.settle()
  await say($, '中途訊息')
  await runSave($, w)
  await w.clock.settle()
  // 交接前整理也會記一次 distill.ok
  expect(statsOf(w)?.counts).toEqual({ 'handoff.present.ok': 1, held: 1, 'distill.ok': 1 })
})

test('統計：交接失敗記次數與原因；攔下的訊息送回舊對話不算遺失', async ($, on) => {
  const w = world(on, 650_000, 1_000_000, {}, [], 5)
  await startSession($)
  await stop($)
  await w.clock.settle()
  await say($, '中途訊息')
  await runSave($, w, { write: false })
  await w.clock.settle()
  const s = statsOf(w)
  expect(s?.counts).toEqual({ 'handoff.present.fail': 1, held: 1, 'distill.ok': 1 })
  expect(s?.failures.map(f => f.what)).toEqual(['handoff.present.fail'])
})

test('統計：離席交接過時刪掉、選 continue、選 resume 各記一次', async ($, on) => {
  const w = world(on, 100_000, 1_000_000, { 'away:S1': { file: HANDOFF_FILE } })
  await endTurn($)
  w.put('away:S1', { file: HANDOFF_FILE, held: '我回來了' })
  await cmd($, 'continue')
  w.put('away:S1', { file: HANDOFF_FILE })
  await resume($)
  await w.clock.advance(0)
  expect(statsOf(w)?.counts).toEqual({ 'away.stale': 1, 'away.continue': 1, 'away.resume': 1 })
})

test('統計：整理成功與失敗分開記，失敗留原因', async ($, on) => {
  const w = world(on, 100_000, 1_000_000, {}, [], 5)
  // 失敗不推進進度，下一次整理同一段
  ctl.completeAborts = true
  await distillNow($)
  ctl.completeAborts = false
  await distillNow($)
  const s = statsOf(w)
  expect(s?.counts['distill.ok']).toBe(1)
  expect(s?.counts['distill.fail']).toBe(1)
  expect(s?.failures[0]?.detail).toContain('timeout')
})

test('統計：守門命中留下指令片段給評估判斷擋得對不對；疑似金鑰不記內容', async ($, on) => {
  const w = world(on, 1000, 1_000_000, { 'guards:C--proj': [pushGuard('on')] })
  await $.tool.call({ tool: 'Bash', command: 'git push origin main' })
  await $.tool.call({ tool: 'Bash', command: 'GH=ghp_abc git push' })
  const s = statsOf(w)
  expect(s?.counts['guard.hit.1']).toBe(2)
  expect(s?.hits.map(h => h.detail)).toEqual(['#1 Bash: git push origin main', '疑似金鑰'])
})
