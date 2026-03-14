# claude-mem 繁體中文化翻譯對照表

> 適用版本：claude-mem 10.3.1（thedotmack）
> 插件更新後 patch 可能失效，請依此對照表重新替換。

## UI 字串對照

### context-generator.cjs / worker-service.cjs 共用

| 英文原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `recent context` | `近期脈絡` | Session 載入時的標題 |
| `Legend:` | `圖例：` | 表格說明標題 |
| `Column Key` | `欄位說明` | 表格欄位說明標題 |
| `Read` | `讀取` | 操作類型 |
| `Work` | `研究` | 操作類型 |
| `Context Index` | `脈絡索引` | 索引區段標題 |
| `Context Economics` | `脈絡經濟` | 經濟性分析標題 |
| `Loading: X observations` | `載入：X 筆觀察` | 載入進度訊息 |
| `Untitled` | `無標題` | 無標題的 session |
| `Session started` | `工作階段開始` | Session 開始標記 |
| `Previously` | `先前` | 先前 session 區段 |
| `No previous sessions found` | `此專案尚未找到先前的工作階段記錄` | 無歷史 session |

### code--zh-tw.json（基於 code--zh.json）

| 簡體原文 | 繁體中文 | 備註 |
|---------|---------|------|
| `Code Development (Chinese)` | `Code Development (Traditional Chinese)` | mode 名稱 |
| `中文` | `繁體中文` | LANGUAGE REQUIREMENTS |
| `简洁` | `簡潔` | XML placeholder |
| `文件路径` | `檔案路徑` | XML placeholder |
| `会话` | `工作階段` | XML placeholder |

> 完整的簡繁對照請直接查看 `patches/code--zh-tw.patch`。

## 替換方式

在 minified `.cjs` 檔案中，直接用文字編輯器搜尋英文原文並替換為繁體中文。
由於是 minified 的單行檔案，建議使用 `sed` 或編輯器的全域取代功能。

```bash
# 範例：替換 context-generator.cjs 中的字串
sed -i '' 's/recent context/近期脈絡/g' scripts/context-generator.cjs
sed -i '' 's/Legend:/圖例：/g' scripts/context-generator.cjs
# ... 依對照表逐一替換
```
