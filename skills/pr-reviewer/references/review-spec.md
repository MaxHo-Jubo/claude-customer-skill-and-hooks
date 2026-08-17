# Review 共用規範

lite 模式（`~/.claude/agents/pr-reviewer.md`）與 full 模式（`~/.claude/skills/pr-reviewer/SKILL.md`）共用本檔。
**唯一出處：判定標準、信心評分、輸出格式只寫在這裡，兩邊都 Read 本檔，不得各自複製一份。**

## 載入規範文件

依序尋找 CODE-REVIEW-RULE.md：

1. 當前 repo 根目錄（`git rev-parse --show-toplevel`）的 `CODE-REVIEW-RULE.md`
2. `~/.claude/CODE-REVIEW-RULE.md`（全域 fallback）

找到後用 Read tool 讀取完整內容，作為後續逐條比對的規範來源。

找不到 → 輸出錯誤並終止：「找不到 CODE-REVIEW-RULE.md，請在 repo 根目錄或 ~/.claude/ 放置規範文件」

## 檔案過濾

從 diff 中排除以下檔案類型，不進行 review：

- `*.md`（Markdown 文件）
- `*.json`（JSON 設定檔）
- `*.yml` / `*.yaml`（YAML 設定檔）

若過濾後無剩餘程式碼檔案 → 輸出「無需 review 的程式碼改動」並提前退出。

## 必查規則清單（17 條，不可跳過任何一條）

對 diff 中所有新增/修改的行逐一檢查：

1. **if 語句大括號** — 所有 if 語句必須有 `{}`，禁止單行 if
2. **不可變性** — 禁止 mutation（`obj.field = value`），必須用 spread operator 建新物件
3. **禁止 console.log** — 正式程式碼不得殘留 console.log
4. **禁止 Magic Number** — 未經解釋的數字常數必須抽出為具名常數並加註解
5. **安全性：禁止 hardcoded secrets** — 不得有 hardcoded API key、token、密碼
6. **安全性：禁止 log 敏感資料** — log 中不得印出 token、password、API key、session
7. **錯誤處理：async/await + try-catch** — async/await 必須搭配 try-catch
8. **錯誤處理：null safety** — 空值/undefined 存取必須做防護（optional chaining、guard clause、default value）
9. **變數與常數註解** — 所有變數與常數必須加上用途註解（含 React hook 變數如 `useState`/`useRef`、TypeScript `interface`/`type` 本身與其成員欄位）
10. **函式與方法註解** — 所有函式必須有 JSDoc 格式註解（用途、參數、回傳值）
11. **STEP 格式註解** — 函式內部須有 STEP 01 起算的執行步驟註解（functional component 內部例外）
12. **註解正確性** — 程式邏輯與註解必須一致，不得有過時/錯誤註解或錯字
13. **全域變數修改** — 移除或修改全域變數/共用常數/共用函式時，必須搜尋所有使用點確認已處理
14. **React：避免不必要 re-render** — 適當使用 React.memo、useCallback、useMemo
15. **React：useEffect cleanup** — useEffect 有訂閱或計時器必須有 cleanup function
16. **React Native：大列表** — 必須用 FlatList/SectionList，禁止 ScrollView + map
17. **React Native：靜態樣式** — 用 StyleSheet.create() 抽出

對每條規則：

1. 理解規則要求
2. 掃描 diff 中所有新增/修改的行
3. 判斷是否有違反
4. 若該規則屬「風格類」（見下節清單）→ 執行慣例檢查 → 與主流慣例一致則不記錄；但規則 9/10/11 命中全新建立的檔案時套用「新增檔案例外」，跳過慣例檢查、違反即記錄
5. 若違反且非主流慣例：記錄 issue — 問題描述 + 違反的規則名稱 + 檔案路徑:行號 + 慣例統計結果（grep 指令 + 比例）

注意：React/React Native 規則只在 diff 包含 `.jsx`、`.tsx`、`.js`、`.ts` 檔案時檢查。

## 慣例優先原則（強制；lite / full 皆適用）

CODE-REVIEW-RULE.md 的 17 條規則中，**風格類規則必須先比對既有慣例再決定是否標 issue**。新增 code 與「主流慣例」一致時，不應標為 CRITICAL/MINOR。

### 風格類規則清單（必須先做慣例檢查）

- Magic Number（規則 4）
- 變數與常數註解（規則 9，含 React hook 變數如 `useState`/`useRef`、interface/type 成員）
- 函式與方法註解 / JSDoc（規則 10）
- STEP 格式註解（規則 11）— React functional component 內部已有例外
- 註解正確性（規則 12）中的「JSDoc 完整度」面向
- Reducer/State 操作風格（如 BASE case 是否清空、FAILURE 是否用 optional chaining 取 errors）

### 新增檔案例外（2026-07-16；僅適用規則 9/10/11）

規則 9（變數/常數/hook 變數/interface 註解）、規則 10（函式 JSDoc）、規則 11（STEP 格式註解）若命中的程式碼位於本次 diff 中**全新建立的檔案**（`git diff` 該檔案標示 `new file mode`），**一律跳過下方「慣例檢查流程」，直接依 CODE-REVIEW-RULE.md 規則字面判斷是否違反**，不受慣例統計影響。

原因：實測 `luna_web/frontend/react_18/src` 全庫 STEP 註解採用率僅 4.6%（48/1046 檔）。若對新檔案也套用「跟全 repo 歷史比對、>50% 一致就不標」的邏輯，會把「大多數舊檔案沒寫」誤判為主流慣例，導致新規則對任何新檔案都罰不到（ERPD-11971 2026-07-15 第一次 commit 即是實例）。慣例比對的本意是避免對「修改既有檔案、有多種正確寫法擇一」的情境過度苛求（如規則 4 的 Magic Number、Reducer state 操作風格），不是用來豁免「新檔案要不要寫這個完整性標記」這種是非題。

規則 4（Magic Number）、Reducer/State 操作風格、規則 12 的 JSDoc 完整度面向不在此例外範圍內，新檔案與既有檔案一律照原「慣例檢查流程」處理。

### 非風格類規則（不適用此豁免，照樣標）

- 安全性：hardcoded secrets（規則 5）
- 安全性：log 敏感資料（規則 6）
- 錯誤處理：null safety crash 風險（規則 8）— 注意：對「來源就是可能 null/undefined」的值要標；對「治本後 shape 已收斂」的值符合慣例即可不標
- if 大括號（規則 1）、不可變性（規則 2）、console.log（規則 3）— 這些是硬性禁止
- 全域變數修改（規則 13）
- React 規則 14-15、React Native 規則 16-17

### 慣例檢查流程

對風格類規則的每個候選 issue：

0. **先判斷是否適用「新增檔案例外」**：候選 issue 屬規則 9/10/11 且命中檔案為本次 diff 全新建立（`new file mode`）→ 跳過以下 1-4 步，直接依規則字面判斷、違反即記錄。其餘情況（規則 4/Reducer 風格/規則 12，或規則 9/10/11 命中的是修改既有檔案）才繼續下方步驟。
1. **執行 grep 統計**（必須有具體指令與行數，不可憑印象）：
   ```bash
   # 範例：檢查 reducer FAILURE case 是否慣例使用 optional chaining
   grep -rn "action.response.errors\|action.response?.errors" frontend/react_18/src/redux/reducers/
   ```
2. **抽樣 3-5 個檔案**實際看寫法
3. **判定主流慣例**：
   - 同寫法 >50% → **主流慣例**，新增 code 一致 → **不標**（連 INFO 都不放）
   - 同寫法 30-50% → 並存慣例 → 可放 INFO，附「主流慣例為 X」
   - 同寫法 <30% → 少數寫法 → 可標 MINOR
4. **範本檔強訊號**：若新增 code 明顯複製某既有檔（如 `iotRecordsReducer` 抄 `caseListReducer` 結構），該範本即為「主流慣例」的代表，新增 code 與範本一致 → **不標**

### 業務決策說明的判定

新增常數**不強求業務決策說明**：

- CLAUDE.md MAGIC-NUMBER 規則只要求「抽具名常數 + 用途註解」
- 已具名（如 `DEFAULT_RANGE_MONTHS_BACK`）+ 已有用途註解（如「往前 3 個月」）= 達標
- **禁止**要求解釋「為什麼是 3 不是 6」這種 PM 預設值層級的決定
- 例外：值來自法規 / 政策 / 外部 API 限制時，才該補來源註解（如「保留 30 天，依個資法第 X 條」）

### 慣例違反時的處理

若以上規則被忽略誤標：

1. 該 issue 必須降為 INFO 或刪除
2. 不可因「是 CODE-REVIEW-RULE.md 明文規則」就強標 75+
3. 信心評分中此類項目強制歸 30 以下

## 信心評分

對找到的 issue 啟動 Haiku agent 評分。可把 3-5 個 issue 併入同一個 agent 批次評分以減少往返；issue 少於 3 個時單次評完即可。

### Haiku agent prompt

```
你是 code review 信心評分員。根據以下資訊，評估這些 issue 是真問題還是 false positive，各給出 0-100 的信心分數。

量尺：
- 0: 完全不可信，false positive 或既有問題
- 1-39: 低信心，可能是 false positive
- 40-59: 中等信心，可能是真問題但也可能是 nitpick
- 60-79: 高信心，很可能是真問題
- 80-89: 非常高信心，已驗證的真問題
- 90-100: 確定，確認的真問題

以下情況應給低分（≤30）：
- 既有問題（非本次 diff 引入）
- Linter/typechecker/compiler 會抓的
- 明顯有意為之的功能變更
- 非修改行的問題
- **新增 code 與同 repo 主流慣例一致**（grep 同類檔案 >50% 寫法相同；範本檔對範本檔複製）——**此項不適用於全新建立檔案的規則 9/10/11（變數/hook/interface 註解、函式 JSDoc、STEP 格式註解）**，新檔案沒有「既有慣例」可比對，不得因舊 codebase 採用率低而降評
- **要求解釋「業務決策」但常數已具名且已有用途註解**（如 `DEFAULT_X_MONTHS = 3` 已備註「往前 3 個月」即達標，不需解釋為何是 3）

以下情況必須給 75 分以上（不得降級）：
- 安全性問題：hardcoded secrets、log 敏感資料、SQL injection、XSS
- crash 風險：實際會 null pointer 的存取（不是 shape 已收斂後的多餘 optional chaining）
- if 大括號、不可變性、console.log、全域變數修改 等硬性禁止
- **以上規則被違反，且 grep 統計確認該寫法非主流慣例**（同類檔案 <30% 採用此寫法）
- **全新建立的檔案中，規則 9/10/11 要求的變數/hook/interface 註解、函式 JSDoc、STEP 註解完全缺漏**——不論舊 codebase 全庫採用率高低，一律視同違反硬性規則

風格類規則（magic number、JSDoc、變數註解、STEP 註解、reducer state 操作）的評分必須先看慣例：
- 主流慣例一致 → 強制 ≤30（歸 INFO 或不報）
- 並存慣例（30-50%）→ 40-60（INFO 為主）
- 違反主流慣例（>50% code 不這樣寫）→ 才可給 75+
- **例外：JSDoc / 變數註解 / STEP 註解命中全新建立的檔案 → 不看慣例，直接依規則 75+**

diff context:
{相關 diff 片段}

issues:
{issue 清單，每個含編號}

違反規則:
{CODE-REVIEW-RULE.md 相關條目}

只回傳一個 JSON array: [{"id": <issue 編號>, "score": <0-100>, "reason": "<一句話說明>"}]
```

若 Haiku agent 失敗或 timeout → 該 issue 歸入 INFO 類別，附註「信心評分失敗」。

## 分類

根據信心分數分類：

- ≥90 → **CRITICAL**（必須修正）
- 80-89 → **MINOR**（建議修正）
- <80 → **INFO**（僅供參考）

## 品質評分

對 diff 整體進行 6 項品質評分（每項 1-5 分，滿分 30）：

| 項目 | 檢查重點 |
|------|----------|
| Magic Number | 未經解釋的數字常數 |
| 邏輯與註解一致性 | 程式邏輯與註解是否相符 |
| 函式註解 | JSDoc 完整度 |
| 變數/常數/props/state 註解 | 用途說明 |
| 註解錯字 | 有無錯字 |
| 系統穩定性 | crash 風險 |

分數意義：5=完美 4=不錯 3=還可以 2=不好 1=拒絕接受

## 輸出格式

所有輸出必須使用以下模板格式。禁止在報告開頭加入 **PR**、**PR URL**、**Review 模式** 等 metadata 欄位，直接從品味評分開始。

### 品味評分

| 評級 | 評語 |
|------|------|
| 🟢/🟡/🔴 | <一句話整體程式碼品味評語> |

評級標準：

- 🟢 資料結構設計良好，邊界情況自然消失，抽象恰當
- 🟡 部分邊界情況用條件判斷處理，有改進空間
- 🔴 過多 if 處理邊界情況、過度/不足抽象、資料結構設計不當

### Code Review Results (供參考)

**嚴重 CRITICAL**（必須修正）

1. <問題描述>（原因：CODE-REVIEW-RULE.md 規定「<規則摘要>」/ 因 <上下文> 導致的 bug）（信心：XX/100）
   `<檔案路徑>:<行號>`

**次要 MINOR**（建議修正）

1. <問題描述>（原因：<說明>）（信心：XX/100）
   `<檔案路徑>:<行號>`

**參考 INFO**（僅供參考）

1. <問題描述>（原因：<說明>）（信心：XX/100）
   `<檔案路徑>:<行號>`

若該分類無問題，顯示「無」。

### Quality Score

**此表格為必要輸出，禁止省略。不可只列總分，必須逐項列出。**

| 項目 | 分數 | 說明 |
|------|------|------|
| Magic Number | X/5 | ≤3 分時必填說明 |
| 邏輯與註解一致性 | X/5 | ≤3 分時必填說明 |
| 函式註解 | X/5 | ≤3 分時必填說明 |
| 變數/常數/props/state 註解 | X/5 | ≤3 分時必填說明 |
| 註解錯字 | X/5 | ≤3 分時必填說明 |
| 系統穩定性 | X/5 | ≤3 分時必填說明 |
| **總分** | **XX/30** | |

> 5=完美 4=不錯 3=還可以 2=不好 1=拒絕接受
>
> 分數 ≤3 的項目必須在說明欄簡述扣分原因（例：`第 42 行有未命名常數 3000`）；4-5 分可留空。

### 結論

**此區段為必要輸出，禁止省略。** 內容必須涵蓋以下三段：

1. **完整總評（含品味分析）** — 段落式陳述，從資料結構設計、邊界情況處理、抽象選擇、與既有慣例的契合度等面向綜合評論。指出做得好的地方與需要警惕的設計傾向（如：過度抽象、if 處理邊界過多、shape 不一致等）。
2. **主要風險點** — 列出 1-3 個對系統穩定性 / 維護性影響最大的點（從 CRITICAL/MINOR 中提煉，不重複列舉）。
3. **合併建議** — 三選一，須與 CRITICAL/MINOR 數量一致：
   - 🟢 **可直接合併** — 0 CRITICAL，MINOR ≤ 2 且非阻斷性
   - 🟡 **建議修正 MINOR 後合併** — 0 CRITICAL，MINOR > 2 或含阻斷性
   - 🔴 **不可合併，需修正 CRITICAL** — CRITICAL > 0

範本：

```
此 PR 整體品味 🟢/🟡/🔴，<段落式總評，2-4 句話，涵蓋資料結構、抽象、慣例契合度>。

**主要風險**：
- <風險點 1>
- <風險點 2>

**合併建議**：🟢/🟡/🔴 <一句話建議>。
```

## Inline Review Comments（full 模式限定）

full 模式下，對每個 CRITICAL 或 MINOR issue，**若能提出具體程式碼修正建議，必須產出 inline review comment**（含 GitHub Suggested Change）。

**建議修正程式碼一律走 inline comment，不要放在 Code Review Results / 結論 區段的文字描述裡** — 上方 summary 只描述問題本身，具體 diff 修法交給行級留言展示。

**產生規則：**

- 從 diff 中定位該 issue 對應的新增/修改行的確切內容與行號
- 撰寫修正後的完整替換程式碼（保持原始縮排）
- 無法提出具體程式碼修正的 issue（如架構建議、缺少測試、需更多上下文）不產生 inline comment，僅留在上方 summary

**行號規則：**

- `line`：PR diff 中新檔案側（RIGHT side）的結束行號
- `start_line`：多行建議時的起始行號；單行建議省略此欄位
- 行號必須落在 PR diff 的 hunk 範圍內，否則 GitHub API 會拒絕

**格式：**

在報告最末尾（Quality Score 之後），用 HTML comment delimiter 包裹 JSON array：

    <!-- INLINE_REVIEW_COMMENTS
    [
      {
        "path": "src/middlewares/reduxAjaxMiddleware.js",
        "line": 134,
        "start_line": 132,
        "side": "RIGHT",
        "body": "🔴 Critical — `typeof` 檢查對 FormData 也為 true（信心：95/100）\n\n```suggestion\n            if (data && data.constructor === Object) {\n                data = { ...data, interactionName: currentActionName };\n            }\n```"
      }
    ]
    INLINE_REVIEW_COMMENTS -->

**body 格式：**

- CRITICAL：前綴 `🔴 Critical — ` + 問題描述 +（信心：XX/100）+ 換行 + suggestion block
- MINOR：前綴 `🟡 Minor — ` + 問題描述 +（信心：XX/100）+ 換行 + suggestion block
- suggestion block 內的程式碼必須是完整的替換內容（取代 start_line 到 line 的所有行），保持原始縮排

**無 inline comments 時：** 省略整個 `<!-- INLINE_REVIEW_COMMENTS ... -->` 區塊。

## 語言規則

- 內部運算（agent 之間溝通、工具呼叫參數）使用英文
- **所有最終輸出必須使用繁體中文**
- 檔案路徑、code identifier、技術術語維持英文
- sub-agent 回傳英文結果時，主 agent 必須翻譯為繁體中文後再輸出
