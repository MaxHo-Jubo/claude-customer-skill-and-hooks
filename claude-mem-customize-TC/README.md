# claude-mem 繁體中文化客製

> 適用版本：claude-mem 13.9.1（thedotmack/claude-mem plugin）

## 說明

claude-mem 插件的 UI 輸出預設為英文。此資料夾保存了將 UI 字串繁體中文化的改動，
包含修改後的完整檔案、patch 檔、以及翻譯對照表。

## 資料夾結構

```
claude-mem-customize-TC/
├── README.md                # 本文件
├── translation-mapping.md   # 翻譯對照表（最重要，更新後靠這份重新替換）
├── files/                   # 修改後的完整檔案（可直接覆蓋）
│   ├── apply-tc.sh               # 一鍵套用腳本（依 translation-mapping.md 的 sed 規則）
│   ├── code--zh-tw.json          # 繁體中文 mode 設定（新增）
│   ├── context-generator.cjs     # UI 字串繁中化
│   └── worker-service.cjs        # UI 字串繁中化
└── patches/                 # diff patch 檔
    ├── code--zh-tw.patch        # code--zh.json → code--zh-tw.json
    ├── context-generator.patch  # 原版 → 繁中版
    └── worker-service.patch     # 原版 → 繁中版
```

## 套用方式

### 方法 1：直接覆蓋檔案（最簡單）

```bash
CACHE_DIR=~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>

cp files/context-generator.cjs "$CACHE_DIR/scripts/"
cp files/worker-service.cjs "$CACHE_DIR/scripts/"
cp files/code--zh-tw.json "$CACHE_DIR/modes/"
```

### 方法 2：套用 patch

```bash
CACHE_DIR=~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>

patch "$CACHE_DIR/scripts/context-generator.cjs" patches/context-generator.patch
patch "$CACHE_DIR/scripts/worker-service.cjs" patches/worker-service.patch
# code--zh-tw.json 是新增檔案，直接複製
cp files/code--zh-tw.json "$CACHE_DIR/modes/"
```

### 方法 3：依翻譯對照表手動替換（插件更新後使用）

見 [translation-mapping.md](translation-mapping.md)。可直接執行 [files/apply-tc.sh](files/apply-tc.sh)：

```bash
CACHE=~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts
MARKET=~/.claude/plugins/marketplaces/thedotmack/plugin/scripts

files/apply-tc.sh "$CACHE"
files/apply-tc.sh "$MARKET"
cp files/code--zh-tw.json "$CACHE/../modes/"
cp files/code--zh-tw.json "$MARKET/../modes/"

# 重啟 worker daemon 讓翻譯生效
pkill -f 'worker-service.cjs.*--daemon'
```

**注意：Terminal 標籤函式名稱（`dg`/`pg`/`X`/`G`）每次發版幾乎都會變。套用前先跑：**
```bash
grep -o -E '.{0,8}"Investigated"' "$CACHE/worker-service.cjs" "$CACHE/context-generator.cjs" | sort -u
```
**確認新函式名，若不同需先更新 apply-tc.sh 與 translation-mapping.md。**

## 插件更新後的處理

**重要：插件更新會同時覆蓋 cache 與 marketplaces 兩處目錄，所有改動會遺失（包含 `modes/` 下的 `code--zh-tw.json`）。**

- **方法 1（直接覆蓋）**：版本差異小時可能仍然可用，但有風險
- **方法 2（patch）**：minified bundle 的行號和內容會變，**幾乎一定失敗**
- **方法 3（翻譯對照表 / apply-tc.sh）**：**最可靠**，不依賴檔案結構，只要 UI 字串沒改就能用；每次大版本升級（如 v12→v13）通常會新增 UI 字串，需要重新枚舉補齊

建議更新後的流程：
1. 確認新版本號與函式名稱（`grep -o -E '.{0,8}"Investigated"'`）
2. 執行方法 3（`files/apply-tc.sh`），對 cache 與 marketplaces 兩處都套用
3. 用 `node -c` 檢查語法、比對翻譯後字串是否符合預期，再重啟 worker daemon
4. 若有新增/變動的 UI 字串，更新 translation-mapping.md、apply-tc.sh，並重新產生 files/ 和 patches/

## 原始檔案位置

| 檔案 | 路徑 |
|------|------|
| `context-generator.cjs` | `~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts/`（MCP server 使用） |
| `worker-service.cjs` | `~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts/`（MCP server 使用） |
| `context-generator.cjs` / `worker-service.cjs` | `~/.claude/plugins/marketplaces/thedotmack/plugin/scripts/`（**Worker daemon 使用，實際產生 session 輸出**） |
| `code--zh-tw.json` | `<CACHE>/modes/` 與 `<MARKET>/modes/` 兩處都要放 |
| `code--zh.json`（原版簡體） | `~/.claude/plugins/marketplaces/thedotmack/plugin/modes/` |

## 版本差異記錄

### v10.6.2 → v11.0.0

- Terminal 輸出函式名稱改變：`bp("X")` / `_p("X")` → `mf("X")` / `ff("X")`
- `**Investigated:**` Markdown 標籤已移除（僅保留 mf/ff 格式）
- 其餘 UI 字串無變化

### v11.0.0 → v12.1.6

- Terminal 輸出函式名稱再次改變：`mf("X")` / `ff("X")` → `Hm("X")` / `qm("X")`
- 欄位說明字串微調：`Tokens spent on work that produced this record (research, building, deciding)` → `Tokens spent on work that produced this record ( research, building, deciding)`（`(` 後多一個空格）
- 其餘 UI 字串無變化

### v12.1.6 → v13.9.1

- Terminal 輸出函式名稱再次改變：`Hm("X")` / `qm("X")` → `worker-service.cjs`: `dg("X")` / `pg("X")`；`context-generator.cjs`: `X("X")` / `G("X")`
- 新增大量 UI 字串（詳見 translation-mapping.md）：
  - Session context 標頭區塊新增 `Format:` / `Fetch details:` / `Stats:` / `Fetch by ID:` / `Search history:` / `Trust this index...` 等說明列
  - 新增 `# Recent Session Context` / `Showing last N session(s) for` 等多工作階段摘要標題
  - 新增 Timeline 工具（`mem-search` timeline 功能）的 `**Anchor:**` / `**Window:**` / `**Items:**` 等欄位
  - 新增 knowledge-agent 知識庫報告的 `**Concepts:**` / `**Facts:**` / `**Date Range:**` / `**Token Estimate:**` / `**Files Modified:**` / `**Observations:**` 等欄位
- 既有 UI 字串（recent context/Legend/Column Key/Context Index/Context Economics/Tokens...等）文字內容無變化，僅函式名稱改變
- **注意：plugin 更新會同時清空 `modes/` 目錄下的 `code--zh-tw.json`，需重新複製**
