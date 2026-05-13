# claude-mem 繁體中文化客製

> 適用版本：claude-mem 13.2.0（thedotmack/claude-mem plugin）

## 說明

claude-mem 插件的 UI 輸出預設為英文。此資料夾保存了將 UI 字串繁體中文化的改動，
包含修改後的完整檔案、patch 檔、以及翻譯對照表。

## 資料夾結構

```
claude-mem-customize-TC/
├── README.md                # 本文件
├── translation-mapping.md   # 翻譯對照表（最重要，更新後靠這份重新替換）
├── files/                   # 修改後的完整檔案（可直接覆蓋）
│   ├── code--zh-tw.json         # 繁體中文 mode 設定（新增）
│   ├── context-generator.cjs    # UI 字串繁中化
│   └── worker-service.cjs       # UI 字串繁中化
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

見 [translation-mapping.md](translation-mapping.md)。

## 插件更新後的處理

**重要：插件更新會覆蓋 cache 目錄，所有改動會遺失。**

- **方法 1（直接覆蓋）**：版本差異小時可能仍然可用，但有風險
- **方法 2（patch）**：minified bundle 的行號和內容會變，**幾乎一定失敗**
- **方法 3（翻譯對照表）**：**最可靠**，不依賴檔案結構，只要 UI 字串沒改就能用

建議更新後的流程：
1. 先嘗試方法 1（直接覆蓋），測試是否正常運作
2. 若異常，改用方法 3 依對照表在新版 bundle 中搜尋替換
3. 替換完成後，更新此資料夾的 files/ 和 patches/

## 原始檔案位置

| 檔案 | Plugin Cache 路徑 |
|------|-------------------|
| `context-generator.cjs` | `~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts/` |
| `worker-service.cjs` | `~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts/` |
| `code--zh-tw.json` | `~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/modes/` |
| `code--zh.json`（原版簡體） | `~/.claude/plugins/marketplaces/thedotmack/plugin/modes/` |

## 版本差異記錄

### v11.0.0 → v13.2.0

- Terminal 輸出函式名稱改變：`mf("X")` / `ff("X")` → `BA("X")` / `zA("X")`
- 新增 `**Files Modified:**` Markdown 標籤
- 其餘共用 UI 字串與 Markdown 標籤無變化
- **已知 bug（[issue #2437](https://github.com/thedotmack/claude-mem/issues/2437)）**：plugin 發佈缺少 runtime dependency `zod`，worker 啟動會炸 `Cannot find module 'zod/v3'`。
  Workaround（**每次升級都要重做**，因為新版本另一個 cache 目錄）：

  ```bash
  VERSION=13.2.0  # 改成當前版本
  CACHE=~/.claude/plugins/cache/thedotmack/claude-mem/${VERSION}
  MARKET=~/.claude/plugins/marketplaces/thedotmack/plugin

  # 只裝 zod，不要做完整 npm install（會觸發 tree-sitter native 編譯）
  (cd "$CACHE" && npm install --no-save --no-package-lock --no-audit --no-fund zod@4.3.6)

  # marketplaces 端 symlink 到 cache，省一次安裝
  [ -e "$MARKET/node_modules" ] || ln -s "$CACHE/node_modules" "$MARKET/node_modules"

  pkill -f 'worker-service.cjs.*--daemon' 2>/dev/null
  ```

### v10.6.2 → v11.0.0

- Terminal 輸出函式名稱改變：`bp("X")` / `_p("X")` → `mf("X")` / `ff("X")`
- `**Investigated:**` Markdown 標籤已移除（僅保留 mf/ff 格式）
- 其餘 UI 字串無變化
