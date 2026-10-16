// 刪掉的記憶留墓碑，整理不再加回（純函式，不碰 $；讀寫 store 在 register.ts）
// 事故（2026-10-14，issue #3）：使用者把經驗檔從 100 條整理成 61 條，刪掉的多半已經寫進 repo；
// 整理只看得到現有條目，同一段對話還在談那些主題，下一次就可能把它們當成新記憶加回來。
// 刪除不只從面板：tools/notes.mjs 與直接改檔也算，所以不在刪除時記，而是比對「上次整理寫完時有的標題」和現在的檔案
import type { Notes } from './notes'

// known：上次整理結束時經驗檔裡的記憶標題；dead：被刪掉的標題與發現的時間
export type Tombstones = { known: string[]; dead: { title: string; at: number }[] }
export const tombKey = (projectKey: string) => `tombstones:${projectKey}`
// 只防無限長大：太舊的墓碑不再提，最多留這麼多條（新的優先）
export const TOMBSTONE_DAYS = 90
export const TOMBSTONE_MAX = 50

const norm = (s: string) => s.replace(/\s+/g, '').toLowerCase()
export const memTitles = (n: Notes) => n.memory.map(m => m.title)

// 整理開始時：上次有、現在沒有的標題記成墓碑；又出現在檔案裡的（使用者自己加回）拿掉；過期與超量的丟掉
export function buryMissing(prev: Tombstones | undefined, current: string[], now: number): Tombstones {
  const here = new Set(current.map(norm))
  const dead = (prev?.dead ?? []).filter(d => !here.has(norm(d.title)) && now - d.at < TOMBSTONE_DAYS * 86_400_000)
  const buried = new Set(dead.map(d => norm(d.title)))
  for (const title of prev?.known ?? []) {
    if (here.has(norm(title)) || buried.has(norm(title))) continue
    dead.push({ title, at: now })
    buried.add(norm(title))
  }
  return { known: current, dead: dead.slice(-TOMBSTONE_MAX) }
}

// 同標題的 add_memory 擋下，除非附上使用者在這段對話又說的原話（原話已由 parseActions 比對過）
export function isBuried(t: Tombstones | undefined, title: string, quoted: boolean) {
  return !quoted && (t?.dead ?? []).some(d => norm(d.title) === norm(title))
}
