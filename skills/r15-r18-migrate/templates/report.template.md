<!-- 狀態檔：${MIGRATION_STATE_DIR}/<entry>-report.md；runner 會把本檔內容貼進頁面 PR body -->
# <entry> 遷移報告

entry: `<entry>` | branch: `<JIRA-KEY>/refactor/<BRANCH_USER>/<entry>` | commit: `<hash>` | 完成時間: `<YYYY-MM-DD HH:MM>`

## 1. 合約回填摘要

| 表 | 列數 | ✅ | ⚠️ | ❌ |
|---|---|---|---|---|
| 表一 逐函式 | | | | |
| 表二 action | | | | |
| 表三 reducer | | | | |
| 表四 元件 | | | | |

- 合約表全文：`<entry>-contract.md`
- 三個 MUST-CHECK 標記：Modal 自動關閉 `<結論>` / 元件初始值 stale `<結論>` / cleanFail on hide `<結論>`
- feature flag 三層一致性：後端路徑前綴層 `<✅/❌>`、機構預設層 `<✅/❌>`、前端路由守衛層 `<✅/❌>`

## 2. ⚠ 清單（需人工複查）

| # | 表 / 列 | 等價 | 說明 | 建議動作 |
|---|---|---|---|---|
| | | | | |

總數：`<warnings_count>`（與結構化輸出的 `warnings_count` 必須一致）

## 3. unverified_items（本次未執行的驗證）

| # | 項目 | 未執行原因 |
|---|---|---|
| | | |

- 只列「沒做」，不得把沒做的項目寫成通過。

## 4. build 結果

- 指令：`<實際執行的建置指令原文>`
- 結果：`<pass / fail>`；重試次數 `<0-2>`
- 輸出末 5 行：

```
<build stdout/stderr 的最後 5 行>
```

## 5. 差異測試結果（Phase 3(a)）

| 通過 | 失敗 | 預期不同 |
|---|---|---|
| `<n>` | `<n>` | `<n>` |

- 測試檔位置：`${MIGRATION_STATE_DIR}/diff-tests/<entry>/`（不進 repo）
- 失敗項逐條：`<測試名 → 差異摘要 → 處置>`
- 「預期不同」指本次遷移規則允許的差異（機制層轉換造成的結構差異），逐條寫出理由；理由寫不出來的一律歸「失敗」。

## 6. 頁面 E2E

- 有無執行：`<是 / 否>`
- 執行條件偵測結果：`<.env.local 與 dev server 是否存在>`
- 執行了什麼：`<路由 / 斷言 / console error 數>`；未執行時本節只寫偵測結果，並在第 3 節列 unverified

## 7. 統計行（供 runner 貼進 PR body）

```
<entry> | 檔 <n> / 行 <n> | build <pass|fail> | ⚠ <n> | 未驗證 <n> | 差異測試 <通過>/<失敗>/<預期不同> | commit <hash>
```
