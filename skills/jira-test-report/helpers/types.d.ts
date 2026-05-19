// CUP E2E Test Helper Types
// 集中 type aliases 供各 helper / 生成的 cjs require 使用
//
// 用法（在 cjs 內）：
//   /** @typedef {import('./types').StepResult} StepResult */
//   /** @typedef {import('./types').StepFn} StepFn */
//   /** @typedef {import('./types').EnvConfig} EnvConfig */
//
// 注意：
//   ambient module 'playwright' / 'fs' 等 stub 放在 stubs.d.ts（純 script 無 export）。
//   本檔有 `export type` 因此屬於 module scope，ambient declare 在此會被困住不 leak。

/** 單一測試步驟結果 */
export type StepResult = {
  /** 兩位數遞增序號（'01' 起算） */
  step: string;
  /** 測試案例編號（如 'A1.1'） */
  caseId: string;
  /** 步驟名稱（建議中文短名，如「結案頁載入」） */
  name: string;
  /** 步驟說明（中文長描述，給人看的） */
  description?: string;
  /** 執行狀態 */
  status: 'PASS' | 'FAIL' | 'SKIP';
  /** 截圖檔名（相對 SCREENSHOT_DIR） */
  screenshot?: string;
  /** 執行毫秒數 */
  ms: number;
  /** FAIL 時的錯誤訊息 */
  error?: string;
  /** SKIP 時的原因 */
  reason?: string;
};

/** 步驟內部執行函式（page 型別 lazy 引用 playwright） */
export type StepFn = (page: import('playwright').Page) => Promise<void>;

/** 解析後的環境變數設定 */
export type EnvConfig = {
  /** Jira issue key，例 'CUP-180' */
  issueKey: string;
  /** R15 / R18 variant */
  variant: VariantName;
  /** base URL（localhost 或正式環境） */
  baseUrl: string;
  /** Playwright headless mode */
  headless: boolean;
  /** 遇 FAIL 即停 */
  stopOnFail: boolean;
  /** ONLY filter prefix（如 'A1' 只跑 A1.x） */
  only: string;
  /** RESUME_FROM caseId（跨 session 續跑用） */
  resumeFrom: string;
  /** 截圖目錄 */
  screenshotDir: string;
  /** progress.md 路徑 */
  progressPath: string;
  /** API 登入參數（從 E2E_ACCOUNT / E2E_PASSWORD / E2E_TYPE 與 baseUrl 組成） */
  login: LoginParams;
  /** Playwright storageState 路徑（deprecated 後備路徑） */
  authPath: string;
  /** 解析後完整 ENTRY_PATH（已替換模板變數） */
  entryPath: string;
};

/** API 登入參數 */
export type LoginParams = {
  baseUrl: string;
  account: string;
  password: string;
  type: string;
  loginPath?: string;
};

/** R15 / R18 識別 */
export type VariantName = 'r15' | 'r18';

/** Bundle 偵測結果 */
export type BundleInfo = {
  /** 是否載入 react15 bundle */
  hasR15: boolean;
  /** 是否載入 react18 bundle */
  hasR18: boolean;
  /** 是否存在 .react-bs-table（R15 特徵） */
  hasReactBsTable: boolean;
  /** React fiber key 樣本（debug 用） */
  fiberKey: {
    hasInternalInstance: boolean;
    hasReactFiber: boolean;
    sample: string[];
  } | null;
};

/** Browser 啟動結果 */
export type BrowserBundle = {
  browser: import('playwright').Browser;
  context: import('playwright').BrowserContext;
  page: import('playwright').Page;
};

/** updateProgressMd 寫入欄位 */
export type ProgressFields = {
  status: string;
  screenshot: string;
  runAt: string;
};
