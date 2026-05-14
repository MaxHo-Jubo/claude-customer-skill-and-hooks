// CUP E2E Test - Ambient module / global stubs
//
// 為什麼這個檔案存在：
//   helpers/ 是 user-level skill 目錄，不裝 npm 套件（playwright / @types/node）。
//   ambient declarations 必須放在「無 export 的 script」檔內才會 leak 成 global，
//   types.d.ts 有 export type 已成 module scope，ambient declare 在內部會被困住。
//
// 此檔提供：
//   - `import('playwright').XXX` 型別契約（最小子集，runtime 由呼叫端 require 真實套件）
//   - Node.js 內建 process / fs / path / os 型別契約（不裝 @types/node）
//
// runtime 行為完全不受此檔影響；它只是讓 tsc / IDE 通過型別檢查。

// ---- playwright 最小契約 ----
// 完整 API 請參考 https://playwright.dev/docs/api/class-page

declare module 'playwright' {
  export interface Locator {
    count(): Promise<number>;
    click(options?: unknown): Promise<void>;
    check(options?: unknown): Promise<void>;
    isChecked(): Promise<boolean>;
    isVisible(options?: unknown): Promise<boolean>;
    fill(value: string): Promise<void>;
    selectOption(value: string | string[]): Promise<string[]>;
    inputValue(): Promise<string>;
    innerText(): Promise<string>;
    first(): Locator;
    last(): Locator;
    nth(index: number): Locator;
    locator(selector: string): Locator;
  }
  export interface ConsoleMessage {
    type(): string;
    text(): string;
  }
  export interface Page {
    goto(url: string, options?: unknown): Promise<unknown>;
    waitForSelector(selector: string, options?: unknown): Promise<unknown>;
    waitForLoadState(state?: string): Promise<void>;
    waitForTimeout(ms: number): Promise<void>;
    screenshot(options: { path: string; fullPage?: boolean }): Promise<unknown>;
    locator(selector: string): Locator;
    evaluate<T = unknown, A = unknown>(fn: (arg: A) => T, arg?: A): Promise<T>;
    url(): string;
    keyboard: { press(key: string): Promise<void> };
    on(event: 'console', handler: (msg: ConsoleMessage) => void): void;
    on(event: 'pageerror', handler: (err: Error) => void): void;
    on(event: string, handler: (...args: unknown[]) => void): void;
  }
  export interface BrowserContext {
    newPage(): Promise<Page>;
  }
  export interface Browser {
    newContext(options?: unknown): Promise<BrowserContext>;
    close(): Promise<void>;
  }
  export const chromium: {
    launch(options?: { headless?: boolean }): Promise<Browser>;
  };
}

// ---- Node.js 內建 module ----

declare module 'fs' {
  export function existsSync(p: string): boolean;
  export function readFileSync(p: string, encoding: string): string;
  export function writeFileSync(p: string, content: string): void;
  export function mkdirSync(p: string, options?: { recursive?: boolean }): void;
  export function readdirSync(p: string): string[];
}

declare module 'path' {
  export function join(...segments: string[]): string;
}

declare module 'os' {
  export function homedir(): string;
}

declare module 'module' {
  export function createRequire(filename: string): {
    (id: string): any;
    resolve(id: string, options?: { paths?: string[] }): string;
  };
}

// ---- 全域 process ----

declare const process: {
  env: { [key: string]: string | undefined };
  exit(code: number): never;
  cwd(): string;
};

// ---- CommonJS module-scope globals ----

declare const __dirname: string;
declare const __filename: string;

