# Jira Inline Comment 結構範本

> 由 jira-test-report skill S7「發 inline comment」用（v2.5.3+ 從 SKILL.md 抽出）。
> 此範本決定 Jira issue comment 的版面與閱讀體驗 — stakeholder 看 comment 就能掌握測試結果與斷言依據。

## 標準結構

```
h2. 自動化測試結果（環境/方法）
摘要一行：環境 + 結果 + 模式（互動/腳本）

----

h3. 1. {步驟標題}
{說明 + 預期行為}
!{螢幕截圖}|width=900!

h3. 2. {下一步}
...

----

h3. 邏輯驗證表
|| 條件 || 預期 || 實測 ||
| ... | ... | ✅ |

----

h3. 結論
通過/失敗 + 重點觀察
```

## 區塊說明

- **h2 標題**：固定「自動化測試結果（環境/方法）」
- **摘要一行**：環境（local / staging）+ 結果（N/N PASS / FAIL）+ 模式（互動 / 腳本）
- **分隔線 `----`**：區隔測試步驟區與驗證表區與結論區
- **每個 step**：`h3. N. 步驟標題` + 說明 + inline 截圖；圖片 `!filename|width=900!`
- **邏輯驗證表**：純資料斷言整合 — 條件 / 預期 / 實測 / ✅❌；可選
- **結論**：通過 / 失敗 + 重點觀察（regression 風險、發現的衍生問題等）

## 腳本模式建議補充

- 執行時間 / variant（r15 vs r18）
- console error 數量（從 `_results.json.consoleErrors.length`）
- fail step 的 error 訊息（含「實測 vs 預期」對比）

## 範例（簡化版）

```
h2. 自動化測試結果（staging）
*環境*：staging / 帳號 adm_max_ho　|　*結果*：9/9 PASS　|　*模式*：腳本（45s）

----

h3. 1. 結案頁載入
進入個案結案頁，等歷史紀錄區塊載入
!01-結案頁載入.png|width=900!

h3. 2. 結案原因下拉完整 14 項
將 select 強制展開為 listbox 視覺呈現
!02-結案原因下拉完整-14-項.png|width=900!

----

h3. 結論
通過 — 14 項結案原因 enum 完整補齊，UI 可選驗證通過
```
