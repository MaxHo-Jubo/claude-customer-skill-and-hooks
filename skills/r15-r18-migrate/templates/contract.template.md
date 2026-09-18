<!-- 狀態檔：${MIGRATION_STATE_DIR}/<entry>-contract.md -->
# <entry> 合約表

entry: `<entry>` | R15 檔數 `<n>` / 總行數 `<n>` | 產出時間: `<YYYY-MM-DD HH:MM>`

> 表格格式定義見 `docs/contract-extraction.md`。
> Phase 1 產出前四欄（表格本身），Phase 3(c) 回填最後兩欄（`R18 對應` / `等價`）。
> **每一列都要有來源**：`來源` 欄填 `路徑:行號`（該行為最具代表性的一行：函式定義行、`dispatch(...)` 那一行等）；定位不到行號就整表退回重做，不要留空或寫「未找到行號」。
> Phase 1 的 subagent 產出是素材不是結論；`等價` 欄一律由主流程回填，subagent 不得填寫。

## 表一：逐函式表

| 函式 | 輸入（params / 讀取的 props·state·refs） | 輸出（return / setState 欄位 / dispatch / callback / DOM 副作用） | 呼叫者 | 來源 | R18 對應 | 等價 ✅/⚠️/❌ |
|---|---|---|---|---|---|---|
| | | | | | | |

## 表二：action 表

| type | url | method | data 形狀 | query | headers | file 欄位 | callback / dispatch / redirect / lastExcutionFunction | 來源 | R18 對應 | 等價 ✅/⚠️/❌ |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |

## 表三：reducer 表

| 欄位 | 型別 | 初始值 | 哪些 case 修改 | 來源 | R18 對應 | 等價 ✅/⚠️/❌ |
|---|---|---|---|---|---|---|
| | | | | | | |

## 表四：元件表

| props | state | lifecycle | handlers | refs | 第三方元件用法 | 來源 | R18 對應 | 等價 ✅/⚠️/❌ |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

## 表五：shared_deps 對照（Phase 3(c) 由主流程填；每個 `entry.shared_deps[]` 項目一列）

| r15_path | r18_equivalent | 本 entry 用到的 props／函式名 | R18 缺少的 | 等價 ✅/⚠️/❌ |
|---|---|---|---|---|
| | | | | |

- `r18_equivalent` 為 `null` 的列直接 ❌「無對應」；有缺少項的列標 ⚠️ 並同步進下方 ⚠ 清單，缺的名稱就是呼叫端要改的地方。

## 主流程核對結論（Phase 1 收尾）

- action 對應核對（URL / method / data 形狀逐一讀兩邊原文）：`<結論；不一致者列出表二列號>`
- success 副作用完整性核對（reducer 表每個 SUCCESS 分支的欄位變化）：`<結論；漏列者列出補上的欄位>`
- 其餘直接採信 subagent 的部分：URL 字串、HTTP method、action type 常數、import 來源

## ⚠ 清單（等價欄為 ⚠️ 或 ❌ 的列）

| 表 | 列（識別字） | 等價 | 原因 | 需要人工做什麼 |
|---|---|---|---|---|
| | | | | |

- ⚠️ 的定義是「需要人工複查」，不是「大概沒問題」；本清單的每一列都必須同步進 `<entry>-report.md`。
- ❌ 若已在 Phase 2 對應到 `blocked(no_mapping)`，在「原因」欄引用該 blocked 狀態，不重複判斷。
