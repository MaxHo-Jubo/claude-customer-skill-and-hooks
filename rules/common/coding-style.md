# CODING-STYLE | for-AI-parsing

> 專案特定規則見 CLAUDE.md CODE-STYLE section，以該處為準。

<!-- 2026-08-04: 新增 ASYNC-INTERRUPT-EXITS 與對應 checklist 一行，來源為 ERPD-11967 的 fix commit 有 5/7 落在 async 中斷路徑；改前備份 coding-style.md.bak -->

<rules>

IMMUTABILITY:
  priority: critical
  action: 建新物件，禁止 mutate 原物件
  pattern: update(original, field, value) → return new copy
  banned: in-place modify

FILE-ORG:
  principle: many-small > few-large
  lines: 200-400 typical, 800 max
  cohesion: high cohesion, low coupling
  organize: by feature/domain, not by type
  large-module: extract utilities

ERROR-HANDLING:
  action: 每層明確處理 error
  ui-facing: user-friendly message
  server-side: log detailed context
  banned: silently swallow errors

ASYNC-INTERRUPT-EXITS:
  trigger: 實作「使用者觸發 → await 外部服務 → 寫回 UI/資料」的流程
  action: 成功路徑寫完後，逐格確認六個中斷點各有明確出口，不可靠預設值糊過去
  matrix: 使用者中途取消（含點背景關閉）| 元件卸載/頁面離開 | 重複觸發（連點、前一輪動畫未結束）| 上游回 200 但 0 筆可用 | 上游定義/組態缺失 | 前置步驟失敗後的降級（權限被拒、裝置不存在）
  cancel-token-timing: AbortController/取消旗標在「使用者按下按鈕當下」建立並往下傳參，不在 fetch 前才建立；否則涵蓋不到「已按下、請求尚未送出」的空窗，該空窗內取消會 abort 在 null 上
  abort-scope: abort signal 不涵蓋 setTimeout/setInterval 鏈；有排程鏈就必須在每個離開路徑一併清除（抽具名 helper，見 EXTRACT-SHARED-HELPER）
  zero-result: 「拿到回應但 0 筆可用」與「沒拿到回應」對使用者是同一件事，走同一個錯誤出口；禁止「已完成 0 筆」這類提示，它會把上下游 schema 不同步包裝成正常結果而永遠不被回報
  why: ERPD-11967 七個 fix commit 有五個落在這六格，且「取消後仍覆寫欄位」修了兩次才對（第一次 controller 建在 fetch 前，空窗沒蓋到）

INPUT-VALIDATION:
  scope: system boundaries only
  action: validate all user input before processing
  prefer: schema-based validation
  fail-fast: clear error message
  trust: never trust external data(API responses/user input/file content)

MAGIC-NUMBER:
  action: 數字常數抽出為具名常數並加用途註解

NULL-SAFETY:
  action: 空值/undefined 存取必須做防護
  patterns: optional chaining(?.) / guard clause / default value
  scope: 所有可能為 null/undefined 的變數存取

COMMENT-ACCURACY:
  rule: 程式邏輯與註解必須一致
  action: 修改程式碼時同步更新對應註解；刪除已無對應程式碼的舊註解；拼寫與邏輯一致

STEP-COMMENT-INSERT:
  rule: 既有 STEP 序列前/中插入新註解→整段往後 +1 重排；禁止用 STEP 00 規避重排；插入序列尾端則直接接續編號
  encoding: STEP 01 起算，最多4階(STEP 01.01.01.01)；禁止 STEP 00

WRITE-PRESERVE-COMMENTS:
  rule: Write 整檔重寫既有檔案時必須完整保留所有原註解（檔案層 JSDoc / 函式 JSDoc / @type / STEP 編號）
  action: 優先用 Edit 局部替換；必須 Write 時先 Read 完整檔案並用 `git show HEAD:path` 為 baseline；commit 前自己 grep `/\*\*` 數量與 `STEP 0` 出現次數是否與重寫前一致

EDIT-REPLACE-SCOPE:
  rule: Edit 的 `old_string` **不得包含任何你不打算刪除的宣告**。新增程式碼一律用「插入」而非「替換」——`old_string` 只取一個穩定錨點，`new_string` = 新內容 + 錨點原文；舊程式碼永遠不進 `old_string`，就不可能被吃掉
  anchor-must-include-jsdoc: 錨點若是一個函式，要取它的 **JSDoc 第一行（`/**`）**，不是 `function` 那行。取簽名行會把新內容插進 JSDoc 與函式之間——該函式從此沒有註解，而原本的 JSDoc 變成下一個函式的第二個註解（兩個 `/**` 相鄰）。這種錯位語法完全合法、測試全綠、宣告差集也查不到（宣告都還在），只有讀 diff 或掃「`*/` 後緊接 `/**`」才會發現
  anchor-check: 插入後掃一次錯位：`python3 -c "…"` 或最簡單的 `grep -n -A1 '^ \*/$' <file> | grep -B1 '/\*\*'`；另可驗「每個 `^function` 的前一行必須是 ` */` 或空行」
  anchor-why: 本規則寫進 rules 的同一個 session 內就被自己違反一次——iBee 的 `resetQuotaUiToIdle` 因此掉了 JSDoc，而它的註解跑去當 `isHandshakeTicketSpent` 的第二個 JSDoc。規則只寫「取簽名行」是不夠的
  when-really-replacing: 真要改寫既有函式時，`old_string` 從該函式 JSDoc 第一行到它的 `}` 為止。發現範圍會跨到前後其他的 `const`/`let`/`function` → 那是訊號，拆成兩次操作，不要一次替換
  self-check: 下 Edit 前問一句「old_string 裡有沒有我不打算刪掉的識別字？」有就重切範圍。這是**寫入時**的檢查，取代不了也不該退化成事後補救
  post-check: 用 Write 整檔重寫、或做了大段替換後，跑一次頂層宣告差集（不是只比對註解數量）——
    `git show HEAD:$f | grep -oE "^(const|let|var|function|async function) +[A-Za-z_$][A-Za-z0-9_$]*" | awk '{print $NF}' | sort -u > /tmp/o.txt`
    對新版做同樣的事存 /tmp/n.txt，然後 `comm -23 /tmp/o.txt /tmp/n.txt`；差集非空就逐個確認是刻意改名還是漏刪（用 grep 查使用點是否還在）
  why: iBee 1.0.15 新增 `sendCancelQuery` 時，把「舊函式 `resetQuotaUiAfterHandshakeFail` + 它前面兩個宣告」整段當 `old_string`、新函式當 `new_string`，等於用替換做插入的工作。三個宣告消失、8 處使用點全留著。語法合法（`node --check` 過），而且 diff 因新舊都是「JSDoc + function + STEP 註解 + addEventListener」的同構結構而被對齊成「函式被改寫了」，`/**`、`* @returns {void}`、`*/`、`}` 全成了無前綴的 context 行——**看 diff 完全看不出來**。執行期在 listener 內拋 ReferenceError 並靜默中斷，症狀是「按了查詢什麼都沒發生、連錯誤提示都沒有」，從 UI 完全反推不到原因
  why-post-check: 事後只有機械比對會告訴你「你不知道自己刪了什麼」。grep 單一識別字不夠——前提是你已經知道要找哪一個

GLOBAL-MUTATION:
  rule: 移除或修改全域變數/共用常數/共用函式時，必須搜尋該檔案中所有使用點，確認全部已處理

LOOP-EARLY-EXIT:
  rule: `return` 在 `forEach` callback 內只跳出當次迭代，迴圈與迴圈後的程式照跑；宣稱「已中止」前先確認 `return` 所在的 scope 是 callback 還是外層函式
  instead: 要真正中止就把檢查提到迴圈**之前**做整批檢查（`.find()` + reject + return），或改用 `for...of`
  why: LVB-8213 在 `serviceRecord.forEach(...)` 內 `reject(new Error(...)); return;`，commit message 寫「一併修正 forEach 會繼續跑完剩餘項目」，實際上整輪額度計算照跑（結果被丟棄，但會清空 instance 狀態）

EXTRACT-SHARED-HELPER:
  rule: 同一個概念性判斷/驗證邏輯出現在 2+ 個呼叫點（**含同一檔案內**）時，第一次就抽具名共用 helper（如 `isValidLocation`）放對應 utility 檔，所有呼叫點統一引用；不要「先 inline、之後再說」
  signals: 下列任一出現就是「該抽了」，不必等第 3 次——(a) 準備補第 2 份以上的 teardown/cleanup/guard inline 寫法（`clearTimeout`/`clearInterval`/`abort()`/`removeEventListener` 要加在新的離開路徑）；(b) 同檔的 sibling ref 已有同型具名 helper（如 `timerRef` 有 `stopTimer`）而你正要對另一個 ref 貼 inline；(c) 你在 N 個複製點各寫了一句同樣意思的警告註解（「漏帶會安靜退回預設值」）——那句註解是訊號不是解法，註解 enforce 不了任何事，加第 N+1 個複製點的人不會讀到它
  on-extract: 抽出前 grep 所有呼叫點，逐一列出各自的前置檢查與後置防護，確認新 helper 全部涵蓋（漏掉哪個就是把該處的防護悄悄拿掉）。補防護時不要照抄既有的 `? value : 0` 這類 silent fallback，依 no-fallback-after-root-cause 應該 throw。這是 dont-blindly-mirror 的反面——該鏡像的沒鏡像
  on-extract-why: LVB-8213 把「排除項目 + 取次數 + 算單價」抽成 `getSupportCostBasis()`，漏帶既有呼叫點對 `serviceItem.cost` 為 null 的防護（schema 是 `double?`）。`Math.floor(null / unit)` 靜默算出 0 → 該項目不佔補助額度 → 其他項目少轉自費 → 補助溢領。`getCurrentUsedValueForShift` 與 `ClockInPage` 都有 null 防護，新 helper 成了三處裡唯一沒有的
  guard-placement: 「把值傳給共用函式、由共用函式無條件寫入」等於要求每個 caller 都記得傳；只要一個 caller 不傳就會用空值覆寫既有資料且不報錯。守衛加在共用層（用一個保證有值的欄位當哨兵，沒帶就跳過整組），不是加在呼叫端的記憶力上
  why: Inline 重複是 fail-open 類 bug 的溫床，各處邏輯易分歧（一處檢查空值、另一處不檢查 → 行為不一致）。舊版判準只寫「2+ 個檔案」，同檔內第 3 份重複不觸發，ERPD-11967 因此漏掉第三個離開路徑且失敗是靜默的；LWM-2425 三處逐欄位複製各寫一句警告註解，仍被不帶 snapshot 的 caller 清成 null，要到月底對帳才會發現

</rules>

<checklist label="完工前檢查">

- [ ] readable + well-named
- [ ] functions <50 lines
- [ ] files <800 lines
- [ ] nesting ≤4 levels
- [ ] proper error handling
- [ ] no hardcoded values → constants/config
- [ ] no magic numbers → named constants with comments
- [ ] no mutation → immutable patterns
- [ ] null/undefined access guarded
- [ ] comments match actual logic (no stale/wrong comments, no typos)
- [ ] async 流程六個中斷點各有出口（取消/卸載/重複觸發/0 結果/組態缺失/降級）

</checklist>
