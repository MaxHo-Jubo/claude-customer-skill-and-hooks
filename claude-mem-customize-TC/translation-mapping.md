# claude-mem 繁體中文化翻譯對照表

> 適用版本：claude-mem 11.0.0（thedotmack）
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
| `Tokens spent on work that produced this record (research, building, deciding)` | `研究、建構、決策所花費的 Token 數` | 欄位說明 |
| `This semantic index (titles, types, files, tokens) is usually sufficient to understand past work.` | `此語意索引（標題、類型、檔案、Token 數）通常足以理解過去的工作。` | 索引說明 |
| `tokens spent on research, building, and decisions` | `研究、建構與決策所花費的 Token 數` | 經濟性分析 |
| `tokens of past research & decisions for just` | `過去研究與決策的 Token，僅需` | 經濟性分析 |
| `tokens of past work via` | `過去工作的 Token，透過` | 經濟性分析 |

### worker-service.cjs 專用 — Session 摘要模板

#### 彩色/無色 Terminal 輸出（v11.0.0 改用 mf/ff）

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `mf("Investigated"` | `mf("已調查"` | 彩色 Terminal 標籤 |
| `mf("Completed"` | `mf("已完成"` | 彩色 Terminal 標籤 |
| `mf("Learned"` | `mf("已學習"` | 彩色 Terminal 標籤 |
| `mf("Next Steps"` | `mf("後續步驟"` | 彩色 Terminal 標籤 |
| `ff("Investigated"` | `ff("已調查"` | 無色 Terminal 標籤 |
| `ff("Completed"` | `ff("已完成"` | 無色 Terminal 標籤 |
| `ff("Learned"` | `ff("已學習"` | 無色 Terminal 標籤 |
| `ff("Next Steps"` | `ff("後續步驟"` | 無色 Terminal 標籤 |

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

#### Loading 訊息（變數名因檔案而異）

| 英文原文 | 繁體中文 | 所在檔案 |
|---------|---------|---------|
| `Loading: ${t.totalObservations}` | `載入：${t.totalObservations}` | worker-service.cjs |
| `Loading: ${r.totalObservations}` | `載入：${r.totalObservations}` | context-generator.cjs |

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
    sed -i '' 's/Tokens spent on work that produced this record (research, building, deciding)/研究、建構、決策所花費的 Token 數/g' "$F"
    sed -i '' 's/This semantic index (titles, types, files, tokens) is usually sufficient to understand past work\./此語意索引（標題、類型、檔案、Token 數）通常足以理解過去的工作。/g' "$F"
    sed -i '' 's/tokens spent on research, building, and decisions/研究、建構與決策所花費的 Token 數/g' "$F"
    sed -i '' 's/tokens of past research & decisions for just/過去研究與決策的 Token，僅需/g' "$F"
    sed -i '' 's/tokens of past work via/過去工作的 Token，透過/g' "$F"
    sed -i '' 's/Context Index/脈絡索引/g' "$F"
  done

  # ---- worker-service.cjs 專用 ----
  # v11.0.0: mf() = 彩色, ff() = 無色
  sed -i '' 's/mf("Investigated"/mf("已調查"/g' "$W"
  sed -i '' 's/mf("Completed"/mf("已完成"/g' "$W"
  sed -i '' 's/mf("Learned"/mf("已學習"/g' "$W"
  sed -i '' 's/mf("Next Steps"/mf("後續步驟"/g' "$W"
  sed -i '' 's/ff("Investigated"/ff("已調查"/g' "$W"
  sed -i '' 's/ff("Completed"/ff("已完成"/g' "$W"
  sed -i '' 's/ff("Learned"/ff("已學習"/g' "$W"
  sed -i '' 's/ff("Next Steps"/ff("後續步驟"/g' "$W"

  # Markdown 標籤（先長後短）
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

  # Loading 變數名因檔案而異
  sed -i '' 's/Loading: ${t\.totalObservations}/載入：${t.totalObservations}/g' "$W"
  sed -i '' 's/Loading: ${r\.totalObservations}/載入：${r.totalObservations}/g' "$C"
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
