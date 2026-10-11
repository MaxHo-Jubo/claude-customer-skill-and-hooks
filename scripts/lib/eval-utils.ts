import fs from 'fs';

/**
 * 離線評估腳本共用工具（scripts/jev-eval/run-eval.ts、run-eval-d.ts）
 */

/** 百分位的滿分（p 以 0-100 表示） */
const PERCENT_SCALE = 100;
/** 行號從 1 起算的位移 */
const LINE_BASE = 1;

/** jsonl 的一行（保留原始行號） */
interface NumberedLine {
  /** 該行文字 */
  text: string;
  /** 行號（1 起算） */
  no: number;
}

/**
 * 數值遞增比較（toSorted 回呼）
 * @param a - 前一個值
 * @param b - 後一個值
 * @returns 負數表示 a 在前
 */
function ascending(a: number, b: number): number {
  // STEP 01: 相減
  return a - b;
}

/**
 * 取百分位數（nearest-rank）
 * @param xs - 數列（不修改原陣列）
 * @param p - 百分位（0-100）
 * @returns 該百分位的值
 */
export function pct(xs: number[], p: number): number {
  // STEP 01: 排序副本後取 nearest-rank 位置
  /** 遞增排序後的副本 */
  const s = xs.toSorted(ascending);
  return s[Math.min(s.length - 1, Math.ceil((p / PERCENT_SCALE) * s.length) - 1)];
}

/**
 * 替一行文字加上行號（loadJsonl 的 map 回呼）
 * @param text - 該行文字
 * @param i - 陣列索引（0 起算）
 * @returns 帶行號的一行
 */
function numberLine(text: string, i: number): NumberedLine {
  // STEP 01: 索引轉成 1 起算的行號
  return { text, no: i + LINE_BASE };
}

/**
 * 是否為非空白行（loadJsonl 的 filter 回呼）
 * @param l - 帶行號的一行
 * @returns true 表示該行有內容
 */
function isNonBlankLine(l: NumberedLine): boolean {
  // STEP 01: 去空白後仍有字元
  return l.text.trim() !== '';
}

/**
 * 讀 jsonl 檔：略過空白行，逐行 JSON 解析後交給 parse 驗證；解析或驗證失敗帶「檔名:行號」丟錯
 * @param absPath - 檔案絕對路徑
 * @param parse - 驗證並轉型單行資料的函式，收原始值與行號（1 起算），不合法時應丟錯
 * @returns 每個非空白行的轉型結果
 */
export function loadJsonl<T>(absPath: string, parse: (raw: unknown, line: number) => T): T[] {
  /**
   * 解析單行並補上位置資訊（map 回呼）
   * @param l - 帶行號的一行
   * @returns parse 的轉型結果
   */
  const parseLine = (l: NumberedLine): T => {
    // STEP 01: JSON 解析＋驗證；錯誤訊息補上「檔名:行號」方便定位壞資料
    try {
      return parse(JSON.parse(l.text), l.no);
    } catch (err) {
      throw new Error(`${absPath}:${l.no} ${String(err)}`);
    }
  };
  // STEP 01: 保留原始行號、濾掉空白行後逐行解析
  return fs.readFileSync(absPath, 'utf-8').split('\n').map(numberLine).filter(isNonBlankLine).map(parseLine);
}
