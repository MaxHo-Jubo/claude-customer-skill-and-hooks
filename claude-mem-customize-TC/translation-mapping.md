# claude-mem 繁體中文化翻譯對照表

> 適用版本：claude-mem 13.9.3（thedotmack）
> 插件更新後 cache 及 marketplaces 都會被覆蓋，需重新套用。完整可執行腳本見 [files/apply-tc.sh](files/apply-tc.sh)。
> `code--zh-tw.json` mode 檔案也會在插件更新後消失（modes/ 目錄只剩原廠 `code--zh.json`），需重新複製。
>
> **重要：插件有兩個副本，兩邊都要 patch：**
> - `~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts/` — MCP server 使用
> - `~/.claude/plugins/marketplaces/thedotmack/plugin/scripts/` — worker daemon 可能使用
>
> Worker daemon 實際載入哪個路徑會隨版本變動（`ps aux | grep worker-service.cjs` 確認）：v13.2.0 時觀察到從 marketplaces 啟動，v13.9.3 時觀察到從 cache 啟動（hook 的路徑解析邏輯是 cache 最新版本目錄優先，fallback 到 marketplaces）。不要假設固定路徑，兩邊都 patch 最保險。

## UI 字串對照

### context-generator.cjs / worker-service.cjs 共用

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `recent context` | `近期脈絡` | Session 載入時的標題 |
| `Legend:` | `圖例：` | 表格說明標題 |
| `Column Key` | `欄位說明` | 表格欄位說明標題 |
| `Context Index` | `脈絡索引` | 索引區段標題 |
| `Context Economics` | `脈絡經濟` | 經濟性分析標題 |
| `Previously` | `先前` | 先前 session 區段 |
| `Work investment:` | `研究投資：` | 經濟性分析 |
| `Your savings:` | `節省效益：` | 經濟性分析 |
| `reduction from reuse` | `透過重複利用節省` | 經濟性分析 |
| `Tokens to read this observation (cost to learn it now)` | `讀取此觀察的 Token 數（現在學習的成本）` | 欄位說明 |
| `Tokens spent on work that produced this record ( research, building, deciding)` | `研究、建構、決策所花費的 Token 數` | 欄位說明（v12 起 `(` 後多一個空格，先 grep 確認實際字元） |
| `This semantic index (titles, types, files, tokens) is usually sufficient to understand past work.` | `此語意索引（標題、類型、檔案、Token 數）通常足以理解過去的工作。` | 索引說明 |
| `tokens spent on research, building, and decisions` | `研究、建構與決策所花費的 Token 數` | 經濟性分析 |
| `tokens of past research & decisions for just` | `過去研究與決策的 Token，僅需` | 經濟性分析 |
| `tokens of past work via` | `過去工作的 Token，透過` | 經濟性分析 |
| `Format: ID TIME TYPE TITLE` | `格式：ID TIME TYPE TITLE` | 索引欄位格式說明（v13 新增，`ID TIME TYPE TITLE` 保留英文） |
| `Fetch details: get_observations([IDs]) \| Search: mem-search skill` | `查看詳情：get_observations([IDs]) \| 搜尋：mem-search skill` | 索引說明（v13 新增，函式/skill 名稱保留原文） |
| `Stats: ` | `統計：` | 統計列前綴（v13 新增） |
| `When you need implementation details, rationale, or debugging context:` | `當你需要實作細節、原因或除錯脈絡時：` | 索引說明（v13 新增） |
| `Fetch by ID: get_observations([IDs]) for observations visible in this index` | `依 ID 取得：對於此索引中可見的觀察記錄，使用 get_observations([IDs])` | 索引說明（v13 新增） |
| `Search history: Use the mem-search skill for past decisions, bugs, and deeper research` | `搜尋歷史：過去的決策、bug 與更深入的研究可使用 mem-search skill` | 索引說明（v13 新增） |
| `Trust this index over re-reading code for past decisions and learnings` | `對於過去的決策與心得，優先信任此索引而非重新閱讀程式碼` | 索引說明（v13 新增） |
| `No previous sessions found.` | `尚無先前的工作階段。` | 空狀態訊息 |
| `Loading: ` | `載入：` | 經濟性分析前綴 |
| `Session summary` | `工作階段摘要` | Session 標題預設文字 |
| `Session started` | `工作階段已開始` | Session 標題預設文字 |

### Terminal 標籤（minified 函式名每版必變，先 grep 確認）

v13.9.3 實測：`worker-service.cjs` 用 `fh`/`ph`，`context-generator.cjs` 用 `H`/`X`（v13 起 context-generator.cjs 也有獨立的 Terminal 標籤函式對，改版時兩個檔案都要檢查）。

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `fh("Investigated"` | `fh("已調查"` | worker-service.cjs（v13.9.3） |
| `fh("Completed"` | `fh("已完成"` | worker-service.cjs |
| `fh("Learned"` | `fh("已學習"` | worker-service.cjs |
| `fh("Next Steps"` | `fh("後續步驟"` | worker-service.cjs |
| `ph("Investigated"` | `ph("已調查"` | worker-service.cjs（v13.9.3） |
| `ph("Completed"` | `ph("已完成"` | worker-service.cjs |
| `ph("Learned"` | `ph("已學習"` | worker-service.cjs |
| `ph("Next Steps"` | `ph("後續步驟"` | worker-service.cjs |
| `H("Investigated"` | `H("已調查"` | context-generator.cjs（v13.9.3） |
| `H("Completed"` | `H("已完成"` | context-generator.cjs |
| `H("Learned"` | `H("已學習"` | context-generator.cjs |
| `H("Next Steps"` | `H("後續步驟"` | context-generator.cjs |
| `X("Investigated"` | `X("已調查"` | context-generator.cjs（v13.9.3） |
| `X("Completed"` | `X("已完成"` | context-generator.cjs |
| `X("Learned"` | `X("已學習"` | context-generator.cjs |
| `X("Next Steps"` | `X("後續步驟"` | context-generator.cjs |

> 確認新版函式名的方法：
> `grep -o -E '.{0,8}"Investigated"' worker-service.cjs context-generator.cjs | sort -u`
>
> 歷次函式名變遷（各機器/各版本觀察值不同，minify 產物不穩定）：v10.6.2 `bp/_p` → v11.0.0 `mf/ff` → v12.1.6 `Hm/qm` → v13.2.0 `BA/zA` → v13.9.1 worker `dg/pg`、ctx `X/G` → v13.9.3 worker `fh/ph`、ctx `H/X`。

### worker-service.cjs 專用 — Session 摘要模板

#### Session 標題區塊（v13 新增）

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `# Recent Session Context` | `# 近期工作階段脈絡` | 多工作階段摘要標題 |
| `Showing last ` | `顯示最近 ` | 搭配下一條使用 |
| ` session(s) for ` | `個工作階段，專案：` | 與上一條合併：`Showing last N session(s) for **X**:` → `顯示最近 N 個工作階段，專案：**X**:` |
| `No previous sessions found for project "` | `找不到專案 "` | 空狀態訊息 |

#### Timeline 工具（`mem-search` timeline 功能，v13 新增）

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `# Timeline for query:` | `# 時間軸查詢：` | 標題（需先於 `# Timeline` 替換） |
| `# Timeline around anchor:` | `# 時間軸錨點：` | 標題（需先於 `# Timeline` 替換） |
| `# Timeline` | `# 時間軸` | 無查詢/錨點時的預設標題（需最後替換，避免污染上兩條） |
| `**Anchor:**` | `**錨點：**` | 欄位 |
| `**Window:**` | `**範圍：**` | 欄位 |
| `**Items:**` | `**筆數：**` | 欄位 |

> Timeline 的表格欄位 `ID \| Time \| T \| Title \| Tokens` 與空狀態的詳細錯誤訊息（含 records before/after 計數）維持英文，未列入翻譯範圍（低使用頻率、內嵌變數位置複雜，翻譯風險大於效益）。

#### knowledge-agent 知識庫報告（v13 新增）

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `**Concepts:**` | `**概念：**` | 欄位 |
| `**Facts:**` | `**事實：**` | 欄位 |
| `**Date Range:**` | `**日期範圍：**` | 欄位 |
| `**Token Estimate:**` | `**Token 估算：**` | 欄位 |
| `**Files Modified:**` | `**已修改檔案：**` | 欄位 |
| `**Observations:**` | `**觀察記錄：**` | 欄位（注意與 `**Observations (` 不同，後者用於 session 摘要） |

#### Markdown 摘要標籤

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `**Completed:**` | `**已完成：**` | Markdown 摘要 |
| `**Learned:**` | `**已學習：**` | Markdown 摘要 |
| `**Next Steps:**` | `**後續步驟：**` | Markdown 摘要 |
| `**Files Read:**` | `**已讀取檔案：**` | Markdown 摘要 |
| `**Files Edited:**` | `**已編輯檔案：**` | Markdown 摘要 |
| `**Date:**` | `**日期：**` | Markdown 摘要 |
| `**In Progress**` | `**進行中**` | Session 狀態 |
| `**Request:**` | `**請求：**` | Session 請求 |
| `**Observations (` | `**觀察記錄 (` | 觀察記錄數量 |
| `**Status:** Active - summary pending` | `**狀態：** 進行中 - 摘要待生成` | 進行中狀態（先換這條） |
| `**Status:**` | `**狀態：**` | 通用狀態標籤（後換這條） |
| `no summary available` | `無摘要` | 無摘要時的說明 |
| `*No observations yet*` | `*尚無觀察記錄*` | 無觀察記錄 |

#### Loading 訊息

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `Loading: ` | `載入：` | v13 起兩檔案變數名不同（`n`/`t` 等），改用純前綴比對，不綁定變數名 |

### code--zh-tw.json（基於 code--zh.json）

| 簡體原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `Code Development (Chinese)` | `Code Development (Traditional Chinese)` | mode 名稱 |
| `中文` | `繁體中文` | LANGUAGE REQUIREMENTS |
| `简洁` → `簡潔` | 簡繁轉換 | XML placeholder |
| `文件路径` → `檔案路徑` | 簡繁轉換 | XML placeholder |
| `会话` → `工作階段` | 語意調整 | XML placeholder |

> 完整簡繁對照請直接比較 `files/code--zh-tw.json` 與原版 `code--zh.json`。

## 版本差異記錄

### v13.9.1 → v13.9.3 變更

- Terminal 函式名稱再次改變：worker `dg/pg` → `fh/ph`；context-generator `X/G` → `H/X`
- 其餘 UI 字串文字內容無變化（v13 新增字串全數沿用）
- worker daemon 觀察到從 cache 路徑啟動（hook 路徑解析：cache 最新版本優先，fallback marketplaces）

### v12.1.6 → v13.9.1 變更

- Terminal 函式名稱改變：`Hm/qm` → worker `dg/pg`；context-generator `X/G`（**v13 起 context-generator.cjs 也有獨立的 Terminal 標籤函式對，過去版本沒有**）
- 新增 Session context 標頭說明列：`Format:` / `Fetch details:` / `Stats:` / `Fetch by ID:` / `Search history:` / `Trust this index...`
- 新增多工作階段摘要標題：`# Recent Session Context` / `Showing last N session(s) for`
- 新增 Timeline 工具字串（`**Anchor:**` / `**Window:**` / `**Items:**` / `# Timeline...`）
- 新增 knowledge-agent 知識庫報告字串（`**Concepts:**` / `**Facts:**` / `**Date Range:**` / `**Token Estimate:**` / `**Observations:**`）
- **plugin 更新會清空 `modes/` 目錄，`code--zh-tw.json` 需重新複製**
- 既有 UI 字串文字內容無變化

### v11.0.0 → v12.1.6 變更

- `mf("X"` / `ff("X"` → `Hm("X"` / `qm("X"`（Terminal 函式名稱再次改變）
- 欄位說明 `(research, building, deciding)` → `( research, building, deciding)`（`(` 後多一個空格）
- 其餘 UI 字串無變化

### v10.6.2 → v11.0.0 變更

- `bp("X"` / `_p("X"` → `mf("X"` / `ff("X"`（Terminal 輸出函式名稱改變）
- `**Investigated:**` Markdown 標籤已移除
- 其餘 UI 字串無變化

## 替換方式

完整可執行腳本：[files/apply-tc.sh](files/apply-tc.sh)（單一資料來源，本文件不再重複內嵌 sed 清單）。替換順序原則：先換長字串（如 `**Status:** Active - summary pending`、`# Timeline for query:`），再換短字串（如 `**Status:**`、`# Timeline`），避免部分匹配。

```bash
# === 對兩個路徑都執行 ===
REPO=~/Documents/projects/claude-customer-skill-and-hooks
CACHE=~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts
MARKET=~/.claude/plugins/marketplaces/thedotmack/plugin/scripts

# STEP 01: 版本升級時先確認 Terminal 函式名，有變則更新 apply-tc.sh
grep -o -E '.{0,8}"Investigated"' "$CACHE/worker-service.cjs" "$CACHE/context-generator.cjs" | sort -u

# STEP 02: 兩個路徑都套用
"$REPO/claude-mem-customize-TC/files/apply-tc.sh" "$CACHE"
"$REPO/claude-mem-customize-TC/files/apply-tc.sh" "$MARKET"

# STEP 03: 重新複製 code--zh-tw.json（插件更新會清空 modes/）
cp "$REPO/claude-mem-customize-TC/files/code--zh-tw.json" "$CACHE/../modes/"
cp "$REPO/claude-mem-customize-TC/files/code--zh-tw.json" "$MARKET/../modes/"

# STEP 04: 重啟 worker daemon
pkill -f 'worker-service.cjs.*--daemon' 2>/dev/null
echo "Patch complete. Worker will auto-restart on next session."
```

驗證方式：
1. 兩邊路徑分別 `grep -rlP '[\x{4e00}-\x{9fff}]'` 確認含中文
2. grep 幾條英文原文（如 `Column Key`、`recent context`）確認無殘留
3. `ps aux | grep worker-service.cjs` 確認 daemon 已重啟且指向預期路徑

## 觀察標題語言

觀察標題（observation title）由主 Claude 模型生成，語言取決於 CLAUDE.md 的 `LANG.output` 設定和 mode 配置，非 UI 字串。若標題出現英文，確認 code--zh-tw.json mode 已啟用。
