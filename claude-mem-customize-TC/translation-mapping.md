# claude-mem 繁體中文化翻譯對照表

> 適用版本：claude-mem 13.9.1（thedotmack）
> 插件更新後 cache 及 marketplaces 都會被覆蓋，需重新套用。依此對照表搜尋替換即可。
>
> **重要：插件有兩個副本，兩邊都要 patch：**
> - `~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts/` — MCP server 使用
> - `~/.claude/plugins/marketplaces/thedotmack/plugin/scripts/` — **Worker daemon 使用（實際產生 session 輸出）**

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
| `Tokens spent on work that produced this record ( research, building, deciding)` | `研究、建構、決策所花費的 Token 數` | 欄位說明（v12: `(` 後多一個空格） |
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

### worker-service.cjs 專用 — Session 摘要模板

#### Terminal 輸出（v13.9.1 改用 dg/pg，函式名稱每版必變）

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `dg("Investigated"` | `dg("已調查"` | Terminal 標籤（worker-service.cjs，v13 取代 v12 的 Hm） |
| `dg("Completed"` | `dg("已完成"` | Terminal 標籤 |
| `dg("Learned"` | `dg("已學習"` | Terminal 標籤 |
| `dg("Next Steps"` | `dg("後續步驟"` | Terminal 標籤 |
| `pg("Investigated"` | `pg("已調查"` | Terminal 標籤（worker-service.cjs，v13 取代 v12 的 qm） |
| `pg("Completed"` | `pg("已完成"` | Terminal 標籤 |
| `pg("Learned"` | `pg("已學習"` | Terminal 標籤 |
| `pg("Next Steps"` | `pg("後續步驟"` | Terminal 標籤 |
| `X("Investigated"` | `X("已調查"` | Terminal 標籤（**context-generator.cjs 專用**，v13 新增此函式對） |
| `X("Completed"` | `X("已完成"` | Terminal 標籤（context-generator.cjs） |
| `X("Learned"` | `X("已學習"` | Terminal 標籤（context-generator.cjs） |
| `X("Next Steps"` | `X("後續步驟"` | Terminal 標籤（context-generator.cjs） |
| `G("Investigated"` | `G("已調查"` | Terminal 標籤（context-generator.cjs） |
| `G("Completed"` | `G("已完成"` | Terminal 標籤（context-generator.cjs） |
| `G("Learned"` | `G("已學習"` | Terminal 標籤（context-generator.cjs） |
| `G("Next Steps"` | `G("後續步驟"` | Terminal 標籤（context-generator.cjs） |

> 註：minified bundle 的函式名稱每次發版可能變動。確認新版函式名的方法：
> `grep -o -E '.{0,8}"Investigated"' worker-service.cjs context-generator.cjs | sort -u`
>
> v13.9.1 起，`context-generator.cjs` 也出現了獨立的 Terminal 標籤函式對（`X`/`G`），過去版本只有 `worker-service.cjs` 有此區塊，改版時兩個檔案都要檢查。

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

### v10.6.2 → v11.0.0 變更

- `bp("X"` / `_p("X"` → `mf("X"` / `ff("X"`（Terminal 輸出函式名稱改變）
- `**Investigated:**` Markdown 標籤已移除（僅保留 mf/ff 格式）
- 其餘 UI 字串無變化

### v11.0.0 → v12.1.6 變更

- `mf("X"` / `ff("X"` → `Hm("X"` / `qm("X"`（Terminal 函式名稱再次改變）
- 欄位說明 `(research, building, deciding)` → `( research, building, deciding)`（`(` 後多一個空格）
- 其餘 UI 字串無變化

### v12.1.6 → v13.9.1 變更

- Terminal 函式名稱再次改變：`Hm("X"` / `qm("X"` → `worker-service.cjs`: `dg("X"` / `pg("X"`；`context-generator.cjs`: `X("X"` / `G("X"`（**v13 起 context-generator.cjs 也有獨立的 Terminal 標籤函式對，過去版本沒有**）
- 新增 Session context 標頭說明列：`Format:` / `Fetch details:` / `Stats:` / `Fetch by ID:` / `Search history:` / `Trust this index...`
- 新增多工作階段摘要標題：`# Recent Session Context` / `Showing last N session(s) for`
- 新增 Timeline 工具字串（`**Anchor:**` / `**Window:**` / `**Items:**` / `# Timeline...`）
- 新增 knowledge-agent 知識庫報告字串（`**Concepts:**` / `**Facts:**` / `**Date Range:**` / `**Token Estimate:**` / `**Files Modified:**` / `**Observations:**`）
- **plugin 更新會清空 `modes/` 目錄，`code--zh-tw.json` 需重新複製**
- 既有 UI 字串文字內容無變化

## 替換方式

在 minified `.cjs` 檔案中使用 `sed` 全域取代。注意替換順序：先換長字串（如 `**Status:** Active - summary pending`、`# Timeline for query:`），再換短字串（如 `**Status:**`、`# Timeline`），避免部分匹配。完整可執行腳本見 [files/apply-tc.sh](files/apply-tc.sh)。

```bash
# === 對兩個路徑都執行 ===
CACHE=~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts
MARKET=~/.claude/plugins/marketplaces/thedotmack/plugin/scripts

for DIR in "$CACHE" "$MARKET"; do
  W="$DIR/worker-service.cjs"
  C="$DIR/context-generator.cjs"

  # ---- 共用 UI 字串 ----
  for F in "$W" "$C"; do
    sed -i '' 's/Column Key/欄位說明/g' "$F"
    sed -i '' 's/Context Economics/脈絡經濟/g' "$F"
    sed -i '' 's/recent context/近期脈絡/g' "$F"
    sed -i '' 's/Legend:/圖例：/g' "$F"
    sed -i '' 's/Work investment:/研究投資：/g' "$F"
    sed -i '' 's/Your savings:/節省效益：/g' "$F"
    sed -i '' 's/reduction from reuse/透過重複利用節省/g' "$F"
    sed -i '' 's/Previously/先前/g' "$F"
    sed -i '' 's/Tokens to read this observation (cost to learn it now)/讀取此觀察的 Token 數（現在學習的成本）/g' "$F"
    sed -i '' 's/Tokens spent on work that produced this record ( research, building, deciding)/研究、建構、決策所花費的 Token 數/g' "$F"
    sed -i '' 's/This semantic index (titles, types, files, tokens) is usually sufficient to understand past work\./此語意索引（標題、類型、檔案、Token 數）通常足以理解過去的工作。/g' "$F"
    sed -i '' 's/tokens spent on research, building, and decisions/研究、建構與決策所花費的 Token 數/g' "$F"
    sed -i '' 's/tokens of past research & decisions for just/過去研究與決策的 Token，僅需/g' "$F"
    sed -i '' 's/tokens of past work via/過去工作的 Token，透過/g' "$F"
    sed -i '' 's/Context Index/脈絡索引/g' "$F"
    sed -i '' 's/Format: ID TIME TYPE TITLE/格式：ID TIME TYPE TITLE/g' "$F"
    sed -i '' 's/Fetch details: get_observations(\[IDs\]) | Search: mem-search skill/查看詳情：get_observations([IDs]) | 搜尋：mem-search skill/g' "$F"
    sed -i '' 's/Stats: /統計：/g' "$F"
    sed -i '' 's/When you need implementation details, rationale, or debugging context:/當你需要實作細節、原因或除錯脈絡時：/g' "$F"
    sed -i '' 's/Fetch by ID: get_observations(\[IDs\]) for observations visible in this index/依 ID 取得：對於此索引中可見的觀察記錄，使用 get_observations([IDs])/g' "$F"
    sed -i '' 's/Search history: Use the mem-search skill for past decisions, bugs, and deeper research/搜尋歷史：過去的決策、bug 與更深入的研究可使用 mem-search skill/g' "$F"
    sed -i '' 's/Trust this index over re-reading code for past decisions and learnings/對於過去的決策與心得，優先信任此索引而非重新閱讀程式碼/g' "$F"
    sed -i '' 's/No previous sessions found\./尚無先前的工作階段。/g' "$F"
    sed -i '' 's/Loading: /載入：/g' "$F"
    sed -i '' 's/Session summary/工作階段摘要/g' "$F"
    sed -i '' 's/Session started/工作階段已開始/g' "$F"
  done

  # ---- worker-service.cjs 專用：Terminal 標籤（每版函式名不同，先用 grep 確認）----
  sed -i '' 's/dg("Investigated"/dg("已調查"/g' "$W"
  sed -i '' 's/dg("Completed"/dg("已完成"/g' "$W"
  sed -i '' 's/dg("Learned"/dg("已學習"/g' "$W"
  sed -i '' 's/dg("Next Steps"/dg("後續步驟"/g' "$W"
  sed -i '' 's/pg("Investigated"/pg("已調查"/g' "$W"
  sed -i '' 's/pg("Completed"/pg("已完成"/g' "$W"
  sed -i '' 's/pg("Learned"/pg("已學習"/g' "$W"
  sed -i '' 's/pg("Next Steps"/pg("後續步驟"/g' "$W"

  # ---- context-generator.cjs 專用：Terminal 標籤（v13 新增此區塊）----
  sed -i '' 's/X("Investigated"/X("已調查"/g' "$C"
  sed -i '' 's/X("Completed"/X("已完成"/g' "$C"
  sed -i '' 's/X("Learned"/X("已學習"/g' "$C"
  sed -i '' 's/X("Next Steps"/X("後續步驟"/g' "$C"
  sed -i '' 's/G("Investigated"/G("已調查"/g' "$C"
  sed -i '' 's/G("Completed"/G("已完成"/g' "$C"
  sed -i '' 's/G("Learned"/G("已學習"/g' "$C"
  sed -i '' 's/G("Next Steps"/G("後續步驟"/g' "$C"

  # ---- worker-service.cjs 專用：Session 摘要 Markdown 標籤（先長後短）----
  sed -i '' 's/# Recent Session Context/# 近期工作階段脈絡/g' "$W"
  sed -i '' 's/Showing last /顯示最近 /g' "$W"
  sed -i '' 's/ session(s) for /個工作階段，專案：/g' "$W"
  sed -i '' 's/No previous sessions found for project "/找不到專案 "/g' "$W"
  sed -i '' 's/\*\*Status:\*\* Active - summary pending/\*\*狀態：\*\* 進行中 - 摘要待生成/g' "$W"
  sed -i '' 's/\*\*Completed:\*\*/\*\*已完成：\*\*/g' "$W"
  sed -i '' 's/\*\*Learned:\*\*/\*\*已學習：\*\*/g' "$W"
  sed -i '' 's/\*\*Next Steps:\*\*/\*\*後續步驟：\*\*/g' "$W"
  sed -i '' 's/\*\*Files Read:\*\*/\*\*已讀取檔案：\*\*/g' "$W"
  sed -i '' 's/\*\*Files Edited:\*\*/\*\*已編輯檔案：\*\*/g' "$W"
  sed -i '' 's/\*\*Date:\*\*/\*\*日期：\*\*/g' "$W"
  sed -i '' 's/\*\*In Progress\*\*/\*\*進行中\*\*/g' "$W"
  sed -i '' 's/\*\*Request:\*\*/\*\*請求：\*\*/g' "$W"
  sed -i '' 's/\*\*Observations (/\*\*觀察記錄 (/g' "$W"
  sed -i '' 's/\*\*Status:\*\*/\*\*狀態：\*\*/g' "$W"
  sed -i '' 's/no summary available/無摘要/g' "$W"
  sed -i '' 's/\*No observations yet\*/\*尚無觀察記錄\*/g' "$W"

  # ---- worker-service.cjs 專用：Timeline 工具（先長後短，避免 # Timeline 污染前兩條）----
  sed -i '' 's/# Timeline for query:/# 時間軸查詢：/g' "$W"
  sed -i '' 's/# Timeline around anchor:/# 時間軸錨點：/g' "$W"
  sed -i '' 's/# Timeline/# 時間軸/g' "$W"
  sed -i '' 's/\*\*Anchor:\*\*/\*\*錨點：\*\*/g' "$W"
  sed -i '' 's/\*\*Window:\*\*/\*\*範圍：\*\*/g' "$W"
  sed -i '' 's/\*\*Items:\*\*/\*\*筆數：\*\*/g' "$W"

  # ---- worker-service.cjs 專用：knowledge-agent 知識庫報告 ----
  sed -i '' 's/\*\*Concepts:\*\*/\*\*概念：\*\*/g' "$W"
  sed -i '' 's/\*\*Facts:\*\*/\*\*事實：\*\*/g' "$W"
  sed -i '' 's/\*\*Date Range:\*\*/\*\*日期範圍：\*\*/g' "$W"
  sed -i '' 's/\*\*Token Estimate:\*\*/\*\*Token 估算：\*\*/g' "$W"
  sed -i '' 's/\*\*Files Modified:\*\*/\*\*已修改檔案：\*\*/g' "$W"
  sed -i '' 's/\*\*Observations:\*\*/\*\*觀察記錄：\*\*/g' "$W"
done

# 複製 code--zh-tw.json
for DIR in "$CACHE/../modes" "$MARKET/../modes"; do
  cp <repo>/claude-mem-customize-TC/files/code--zh-tw.json "$DIR/"
done

# 重啟 worker
pkill -f 'worker-service.cjs.*--daemon' 2>/dev/null
echo "Patch complete. Worker will auto-restart on next session."
```

## 觀察標題語言

觀察標題（observation title）由主 Claude 模型生成，語言取決於 CLAUDE.md 的 `LANG.output` 設定和 mode 配置，非 UI 字串。若標題出現英文，確認 code--zh-tw.json mode 已啟用。
