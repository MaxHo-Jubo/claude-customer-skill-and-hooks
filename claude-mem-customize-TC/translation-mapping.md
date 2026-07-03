# claude-mem 繁體中文化翻譯對照表

> 適用版本：claude-mem 13.9.3（thedotmack，前次為 13.2.0）
> 插件更新後 cache 及 marketplaces 都會被覆蓋，需重新套用。依此對照表搜尋替換即可。
> `code--zh-tw.json` mode 檔案也會在插件更新後消失（modes/ 目錄只剩原廠 `code--zh.json`），需重新複製。
>
> **重要：插件有兩個副本，兩邊都要 patch：**
> - `~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts/` — MCP server 使用
> - `~/.claude/plugins/marketplaces/thedotmack/plugin/scripts/` — worker daemon 可能使用
>
> Worker daemon 實際載入哪個路徑會隨版本變動（`ps aux | grep worker-service.cjs` 確認）：v13.2.0 時觀察到從 marketplaces 啟動，v13.9.3 時觀察到從 cache 啟動。不要假設固定路徑，兩邊都 patch 最保險。

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
| `Tokens spent on work that produced this record ( research, building, deciding)` | `研究、建構、決策所花費的 Token 數` | 欄位說明（v13.9.3 括號內多一個空格，先 grep 確認實際字元） |
| `This semantic index (titles, types, files, tokens) is usually sufficient to understand past work.` | `此語意索引（標題、類型、檔案、Token 數）通常足以理解過去的工作。` | 索引說明 |
| `tokens spent on research, building, and decisions` | `研究、建構與決策所花費的 Token 數` | 經濟性分析 |
| `tokens of past research & decisions for just` | `過去研究與決策的 Token，僅需` | 經濟性分析 |
| `tokens of past work via` | `過去工作的 Token，透過` | 經濟性分析 |

### worker-service.cjs 專用 — Session 摘要模板

#### 彩色/無色 Terminal 輸出（v13.9.3 改用 fh/ph）

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `fh("Investigated"` | `fh("已調查"` | 彩色 Terminal 標籤 |
| `fh("Completed"` | `fh("已完成"` | 彩色 Terminal 標籤 |
| `fh("Learned"` | `fh("已學習"` | 彩色 Terminal 標籤 |
| `fh("Next Steps"` | `fh("後續步驟"` | 彩色 Terminal 標籤 |
| `ph("Investigated"` | `ph("已調查"` | 無色 Terminal 標籤 |
| `ph("Completed"` | `ph("已完成"` | 無色 Terminal 標籤 |
| `ph("Learned"` | `ph("已學習"` | 無色 Terminal 標籤 |
| `ph("Next Steps"` | `ph("後續步驟"` | 無色 Terminal 標籤 |

> **歷次函式名變遷：** v10.6.2 `bp/_p` → v11.0.0 `mf/ff` → v13.2.0 `BA/zA` → v13.9.3 `fh/ph`。每次升級可能再改名，先 grep `Investigated` 找實際呼叫的函式名。

#### Markdown 摘要標籤

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `**Completed:**` | `**已完成：**` | Markdown 摘要 |
| `**Learned:**` | `**已學習：**` | Markdown 摘要 |
| `**Next Steps:**` | `**後續步驟：**` | Markdown 摘要 |
| `**Files Read:**` | `**已讀取檔案：**` | Markdown 摘要 |
| `**Files Edited:**` | `**已編輯檔案：**` | Markdown 摘要 |
| `**Files Modified:**` | `**已修改檔案：**` | Markdown 摘要（v13.2.0 新增） |
| `**Date:**` | `**日期：**` | Markdown 摘要 |
| `**In Progress**` | `**進行中**` | Session 狀態 |
| `**Request:**` | `**請求：**` | Session 請求 |
| `**Observations (` | `**觀察記錄 (` | 觀察記錄數量 |
| `**Status:** Active - summary pending` | `**狀態：** 進行中 - 摘要待生成` | 進行中狀態（先換這條） |
| `**Status:**` | `**狀態：**` | 通用狀態標籤（後換這條） |
| `no summary available` | `無摘要` | 無摘要時的說明 |
| `*No observations yet*` | `*尚無觀察記錄*` | 無觀察記錄 |

#### Loading 訊息（變數名因檔案而異，且每次 minify 可能改變，先 grep 確認）

| 英文原文 | 繁體中文 | 所在檔案 | 版本 |
|---------|---------|---------|------|
| `Loading: ${t.totalObservations}` | `載入：${t.totalObservations}` | worker-service.cjs | v13.2.0 / v13.9.3 不變 |
| `Loading: ${r.totalObservations}` | `載入：${r.totalObservations}` | context-generator.cjs | v13.2.0 |
| `Loading: ${n.totalObservations}` | `載入：${n.totalObservations}` | context-generator.cjs | v13.9.3 |

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

### v13.2.0 → v13.9.3 變更

- Terminal 輸出函式：`BA("X"` / `zA("X"` → `fh("X"` / `ph("X"`
- `context-generator.cjs` 的 Loading 變數名：`${r.totalObservations}` → `${n.totalObservations}`（`worker-service.cjs` 仍是 `${t.totalObservations}`）
- `Tokens spent on work that produced this record (research, building, deciding)` 括號內多了一個空格，變成 `( research, building, deciding)`
- `modes/code--zh-tw.json` 自訂檔案在插件更新後消失，需重新從 `files/code--zh-tw.json` 複製
- worker daemon 觀察到改從 cache 路徑啟動（v13.2.0 時是 marketplaces）
- 其餘共用 UI 字串與 Markdown 標籤無變化

### v11.0.0 → v13.2.0 變更

- Terminal 輸出函式：`mf("X"` / `ff("X"` → `BA("X"` / `zA("X"`
- 新增 `**Files Modified:**` Markdown 標籤（與 `**Files Read:**`、`**Files Edited:**` 並列）
- 其餘共用 UI 字串與 Markdown 標籤無變化

### v10.6.2 → v11.0.0 變更

- `bp("X"` / `_p("X"` → `mf("X"` / `ff("X"`（Terminal 輸出函式名稱改變）
- `**Investigated:**` Markdown 標籤已移除（僅保留 mf/ff 格式）
- 其餘 UI 字串無變化

## 替換方式

在 minified `.cjs` 檔案中使用 `sed` 全域取代。注意替換順序：先換長字串（如 `**Status:** Active - summary pending`），再換短字串（如 `**Status:**`），避免部分匹配。

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
  done

  # ---- worker-service.cjs 專用 ----
  # v13.9.3: fh() = 彩色, ph() = 無色（v13.2.0 為 BA/zA，v11.0.0 為 mf/ff）
  sed -i '' 's/fh("Investigated"/fh("已調查"/g' "$W"
  sed -i '' 's/fh("Completed"/fh("已完成"/g' "$W"
  sed -i '' 's/fh("Learned"/fh("已學習"/g' "$W"
  sed -i '' 's/fh("Next Steps"/fh("後續步驟"/g' "$W"
  sed -i '' 's/ph("Investigated"/ph("已調查"/g' "$W"
  sed -i '' 's/ph("Completed"/ph("已完成"/g' "$W"
  sed -i '' 's/ph("Learned"/ph("已學習"/g' "$W"
  sed -i '' 's/ph("Next Steps"/ph("後續步驟"/g' "$W"

  # Markdown 標籤（先長後短）
  sed -i '' 's/\*\*Status:\*\* Active - summary pending/\*\*狀態：\*\* 進行中 - 摘要待生成/g' "$W"
  sed -i '' 's/\*\*Completed:\*\*/\*\*已完成：\*\*/g' "$W"
  sed -i '' 's/\*\*Learned:\*\*/\*\*已學習：\*\*/g' "$W"
  sed -i '' 's/\*\*Next Steps:\*\*/\*\*後續步驟：\*\*/g' "$W"
  sed -i '' 's/\*\*Files Read:\*\*/\*\*已讀取檔案：\*\*/g' "$W"
  sed -i '' 's/\*\*Files Edited:\*\*/\*\*已編輯檔案：\*\*/g' "$W"
  sed -i '' 's/\*\*Files Modified:\*\*/\*\*已修改檔案：\*\*/g' "$W"
  sed -i '' 's/\*\*Date:\*\*/\*\*日期：\*\*/g' "$W"
  sed -i '' 's/\*\*In Progress\*\*/\*\*進行中\*\*/g' "$W"
  sed -i '' 's/\*\*Request:\*\*/\*\*請求：\*\*/g' "$W"
  sed -i '' 's/\*\*Observations (/\*\*觀察記錄 (/g' "$W"
  sed -i '' 's/\*\*Status:\*\*/\*\*狀態：\*\*/g' "$W"
  sed -i '' 's/no summary available/無摘要/g' "$W"
  sed -i '' 's/\*No observations yet\*/\*尚無觀察記錄\*/g' "$W"

  # Loading 變數名因檔案而異，且每次 minify 可能改變，先 grep 確認實際變數名
  sed -i '' 's/Loading: ${t\.totalObservations}/載入：${t.totalObservations}/g' "$W"
  sed -i '' 's/Loading: ${n\.totalObservations}/載入：${n.totalObservations}/g' "$C"
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
