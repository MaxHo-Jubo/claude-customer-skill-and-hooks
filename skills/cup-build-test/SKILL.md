---
name: cup-build-test
description: >
  CUP 項目從 commit 反推測試項目 → 產雙用途測試計劃 → 產 Playwright 腳本
  → 正式環境半自動驗證 → 修正並重產腳本。當使用者提到 /cup-build-test、
  「建立 CUP 測試」、「從 commit 反推測試」、「CUP 驗證腳本」、想為 CUP
  項目建立完整測試流程時觸發。不適用於：單一 issue 跑既有測試（用
  /jira-test-report）、純 R15/R18 程式碼比對（用 /r15-r18-verify）。
version: 1.0.0
---

# CUP 測試建立 skill

## 為什麼這件事重要

CUP 項目是日照系統 R15→R18 升級的單元工作。每個 CUP 都需要：

1. 從 commit 反推「我這次到底改了哪些 API、哪些 UI、哪些 state」
2. 產出**人機共用**的測試文件 — 人工逐項驗收與 Playwright 自動化共讀同一份
3. 在 R15 正式環境（仍未升級）跑測試，這是「正確答案」 baseline
4. 跑完發現測試項目本身有錯（描述不符、selector 找不到、預期錯）→ 修正
5. 修正後的腳本給 local / staging / R18 用

之前 CUP-80 是手工建檔（test-plan + cjs），可重用但無流程固化。本 skill 把這一整套變成可重複呼叫的工具。

## 關鍵概念

### 雙用途文件

`.claude/{ISSUE_KEY}-test-plan.md` 同時被人讀（手動驗收）與被 skill/腳本參考（產 cjs）。
規則：
- 每個 case 用 `[read-only]` 或 `[mutation]` 標記類型
- 操作步驟用 markdown checkbox（人能勾、AI 能 parse）
- 預期結果用 **粗體** 「預期」開頭

### Case 編號

- 大功能：`A`、`B`、`C`...（大寫字母）
- 子功能：`A1`、`A2`...
- 主流程：`A1.1`
- 邊界：`A1.2`

### 階段 checkpoint

skill 共 6 階段（外加階段 0），每階段結束會 checkpoint 讓使用者 review：
- 階段 1 → coverage.json review（漏什麼補什麼）
- 階段 2 → test-plan.md review
- 階段 3 → cjs 語法檢查 + 可選 review
- 階段 4 → dry-run 計畫表 + 跑完 summary
- 階段 5 → test-plan 修正 diff
- 階段 6 → 印用法

### 產物 git 政策

**所有產物不入 repo**。skill 會自動檢查 frontend/.gitignore 是否包含以下規則，缺則 append：

```
.claude/CUP-*-test-plan.md
.claude/CUP-*-test.cjs
.claude/CUP-*-temp/
.claude/CUP-*-coverage.json
```

### 不依賴 package.json

執行 Playwright 用 `npx --yes -p playwright@latest node ...`，不寫入 package.json。
第一次跑會下載 chromium driver（~150MB），有快取，後續快。

## 前置條件

- cwd 在 luna_web/frontend（或結構相同的 R15→R18 repo）
- 當前 branch 名含 `CUP-\d+`（例：`CUP-80/refactor/max_ho/...`）
- branch 已 commit 過完成的功能（`git diff <default-branch>...HEAD` 非空）
- **default branch 自動偵測**：skill 用 `git symbolic-ref refs/remotes/origin/HEAD` 取得（luna 是 `master`、其他 repo 可能是 `main`），偵測失敗 fallback `main`
- 不需預裝 playwright（執行時 `npx --yes -p playwright@latest node ...` 動態取得）
- **需 `jq`**：macOS 多數已有，沒裝跑 `brew install jq`（階段 4c 用 jq 從 _results.json 提 summary）
- **第一次跑階段 4c**：npx 會下載 ~150MB chromium driver，可預先 `npx --yes playwright@latest install chromium` 暖快取

## 觸發旗標

| 旗標 | 用途 |
|---|---|
| `--from-stage N` | 從第 N 階段開始（1-6），跳過前面 |
| `--issue CUP-XX` | 手動指定 issue（branch 名解析失敗時） |
| `--with-gitnexus` | 階段 1 加碼用 GitNexus 分析間接依賴 |
| `--focus auto\|equivalence` | 階段 2 test-plan 產出 focus；預設 `auto`（全功能列舉），`equivalence` 專注 R15/R18 行為差異（從 commit 訊息抽取「修正/修復 R18 升級」類字眼） |
| `--only A1` | 階段 4 只跑特定 prefix |

---

## 階段 0：開場提醒（每次必跑）

每次啟動做以下兩件事，**不阻塞流程**：

1. **GitNexus 偵測（用 MCP tool 不是 file system）**：

   GitNexus 是中央化 DB，**不在 repo 內**。用 `test -d .gitnexus/` 是錯的（CUP-180 實戰糾正）。正確流程：

   ```
   呼叫 mcp__gitnexus__list_repos → 看當前 repo（如 luna_web）是否在清單
   若有 → 讀 gitnexus://repo/{repo_name}/context → 抓 indexed_at 時間戳
   ```

2. **印提醒**：

   ```
   ⚙️  GitNexus 可選增強
      - {repo} 已 index（最後更新 YYYY-MM-DD，距今 N 天）
        ⚠️ N > 7 天視為 stale，建議重新 index 後再用 --with-gitnexus
        （CUP-180 實戰：luna_web index 4/29，commits 5/7，stale 8 天）
      - 或：{repo} 未 index，--with-gitnexus 無法用
      - 啟用：對 skill 加 --with-gitnexus
      - 不啟用：純 grep 反推，間接依賴需手動補
   ```

---

## 階段 1：從 commit 反推測試項目

**輸入**：當前 branch
**輸出**：`.claude/{ISSUE_KEY}-coverage.json`

### 機械步驟

1. `git branch --show-current` → regex `CUP-\d+` → `ISSUE_KEY`
   - 解析失敗（含 detached HEAD）→ 要求使用者 `--issue CUP-XX` 或先 checkout branch
2. `git diff --name-only main...HEAD` → 改動檔案清單（若空則中止）
3. **將 diff 輸出寫到暫存檔**（避免 diff 入 context、subagent 讀檔比讀 stdout 容易）：
   ```bash
   git diff main...HEAD > .claude/{ISSUE_KEY}-diff.tmp.txt
   ```
4. **平行**啟動 3 個 Explore subagent，**讀暫存檔 + 直接讀改動檔案 + 追周邊結構**做反推。**純看 diff 不夠** — luna 把 URL 寫在常數檔、Redux action 用 camelCase 字串、saga 是行為主體 — 需明確要求 subagent 同時做以下動作：

   **每個 subagent prompt 必含 verbosity 限制**（CUP-180 實戰：3 agent 共回 25k token 進主 context，太多）：
   - 報告**結構化欄位限長**（每欄不超過 30 字 / 行）
   - **不要 echo source code**，只列結果（endpoint URL、action 名稱、元件名稱）
   - **不列**：i18n key 完整清單、Bootstrap variant 列舉、reducer initState 完整結構、props type interfaces、CSS class 列表
   - 每個 agent 報告**總長 < 1500 字**，超出要先精簡再回

   - **API agent**：
     - 讀 diff 暫存檔抓 `axios.{get|post|put|delete}` / `fetch(` / `createApi` / RTK Query / `apiSlice`
     - **額外**讀改動 `.tsx`/`.jsx` 中 `import` 的 service 檔（往上追 1 層）→ 列出該 service 的所有 method
     - **額外**主動 ls `frontend/src/apiServer/`、`frontend/src/services/`、`frontend/src/api/` 目錄，找與改動 feature 相關的服務檔讀 → 列出全部 endpoint
     - 對改動檔案的 export function 用 LSP `findReferences` 找呼叫端
   - **UI agent**：
     - 對 `.tsx`/`.jsx` 改動檔案讀檔 → 列出元件、按鈕、表單欄位、modal、tab、route entry
     - **元件 regex 排除**：全大寫常數（`^[A-Z][A-Z_0-9]+$`、長度 > 3 視為 SCREAMING constant，不是元件）
     - 對改動 `pages/` 檔案，讀其 import 找出 entry path（route）
   - **Redux agent**：
     - 對 `actions/` `reducers/` `sagas/` `store/` 改動檔案讀檔 → 列出 action type 與副作用、saga effect
     - **luna 慣例**：action type 多為 camelCase 字串如 `'fetchActivityList'`，不是 SCREAMING_SNAKE。subagent 提示要同時抓 camelCase 與 SCREAMING_SNAKE_CASE 兩種
     - 抓 saga 的 `takeLatest(actionType, worker)` 與 `put({ type: ... })` 列副作用流程
5. **若 `--with-gitnexus`**：對改動檔案做 `gitnexus_impact_analysis`，列出間接受影響的 page/元件，併入 coverage
6. **刪除 diff 暫存檔** `.claude/{ISSUE_KEY}-diff.tmp.txt`（已被 subagent 消化）
7. 合併輸出 `coverage.json`：

```json
{
  "issueKey": "CUP-XX",
  "branch": "...",
  "filesChanged": ["src/.../activityCalendar.tsx", "..."],
  "apiEndpoints": [{"method": "POST", "url": "/api/...", "calledFrom": "src/.../*.tsx"}],
  "components": [{"name": "ActivityModal", "changes": "modal close logic"}],
  "reduxActions": [{"type": "STORE_ACTIVITY", "saga": "src/.../sagas.ts"}],
  "indirectDeps": [],
  "inferredFeatures": ["新增活動", "編輯活動", "刪除活動"]
}
```

### Checkpoint 1

印 coverage 摘要：「找到 N 個 API、M 個元件、K 個 Redux action，推出 X 個 inferredFeatures」。問使用者：

- 漏了什麼功能要補？
- 哪個 inferredFeature 範圍太大要拆？

使用者補充後寫回 coverage.json。

> coverage.json 是中繼檔，**階段 2 完成後自動刪除**。

---

## 階段 2：產出測試計劃

**輸入**：`coverage.json` + 使用者補充
**輸出**：`.claude/{ISSUE_KEY}-test-plan.md`

### 機械步驟

1. 讀 `~/.claude/skills/cup-build-test/templates/spec-template.md`
2. **完整 placeholder 對應表**（缺一不可，剩任何 `{{...}}` 即視為產出失敗）：

   | placeholder | 來源 |
   |---|---|
   | `{{ISSUE_KEY}}` | `coverage.issueKey` |
   | `{{FEATURE_TITLE}}` | 從 `coverage.inferredFeatures` 第一條推（如「活動行事曆」）|
   | `{{FEATURE_PATH}}` | 從改動檔案路徑推（如 `日照系統 → 活動管理 → 活動行事曆`）|
   | `{{PURPOSE}}` | 從 Jira issue 標題或 commit 訊息提煉一句話目的 |
   | `{{STATUS}}` | 寫 `初版擬定中` |
   | `{{YYYY-MM-DD}}` | 今日日期（`date -u +%Y-%m-%d`） |
   | `{{ENTRY_PATH}}` | 從 coverage.components 對應的 route / 改動檔案推（例 `/activityManager/activityCalendar`）|
   | `{{ENTRY_PATH_DESCRIPTION}}` | 中文描述「進入 XX 頁面」 |
   | `{{REQUIRED_ROLE}}` | 從 coverage 對應頁面的權限推；不確定就寫 `須有「{{FEATURE_TITLE}}」相關權限` |
   | `{{REQUIRED_TEST_DATA}}` | 從 mutation API 推（例：「至少 1 筆既有活動排程」）|
   | `{{LARGE_FEATURE_A_TITLE}}` 等 | 從 inferredFeatures 拆組分配 |
   | `{{SUB_FEATURE_A1_TITLE}}` 等 | 同上，下一層細分 |

3. **依 `--focus` 旗標決定 test-plan 範圍**：
   - `auto`（預設）：依 inferredFeatures 拆大功能段（A、B、C），列舉全功能
   - `equivalence`：只圈出 commit 訊息中含「修正/修復/解決 R18」類字眼的範圍。例：`fix(FE): ...修正 R18 升級後 modal 不會自動關閉` → test-plan 大功能段聚焦「modal 自動關閉」這一點，其他功能放「附錄：未列入測試（已驗證等價）」
4. **TEMPLATE-CASE-BLOCK 處理（核心步驟，不可跳過）**：
   - template 中所有被 `<!-- TEMPLATE-CASE-BLOCK ... -->` 與 `<!-- /TEMPLATE-CASE-BLOCK -->` 包夾的區塊，**整段重寫**，不是替換 placeholder
   - 重寫時依 coverage 推導實際操作步驟，例：
     - coverage 有 `POST /api/activity` → 主流程「填表 → 點儲存 → API call → modal 關閉 → 行事曆出現新項目」
     - coverage 有 `DELETE /api/activity/:id` → 主流程「找既有 item → 點刪除 → 確認 → API call → 從行事曆消失」
   - 重寫後**不應**保留任何 `操作步驟 1` `預期 UI 結果 1` 等教學佔位符
   - 重寫後**移除**該區塊的 `<!-- TEMPLATE-CASE-BLOCK -->` 與 `<!-- /TEMPLATE-CASE-BLOCK -->` 標記
5. 每個 sub-feature 必含：
   - **Ax.1 主流程**：從 coverage 對應的 API 流程推導 happy path
   - **Ax.2 邊界情況**：通用模板（必填漏填、重複送出、取消、Esc、背景點擊）+ 該功能特有邊界
6. 在每個 case 標記 `[read-only]` 或 `[mutation]`（**二擇一，不可同時標**）：
   - `GET` API → `[read-only]`
   - `POST/PUT/DELETE` API → `[mutation]`
   - 混合：以最危險為準（建立後又讀 → `[mutation]`）
   - 純 UI 互動（開 modal 不送出）→ `[read-only]`
7. 同步「執行紀錄表」的「類型」欄位（與 case heading 標記必須一致）
8. 填「附錄：API 覆蓋率追蹤」表
9. 寫 `.claude/{ISSUE_KEY}-test-plan.md`
10. **驗證**（兩項都要過）：
    - `grep -n '{{[^}]*}}' .claude/{ISSUE_KEY}-test-plan.md` 應回 0 行（無未替換 placeholder；template 註解中的 `‹...›` 不會匹配）
    - `grep -n 'TEMPLATE-CASE-BLOCK' .claude/{ISSUE_KEY}-test-plan.md` 應回 0 行（所有教學區塊已被重寫並移除標記）
    - 任何剩餘都要回頭補才視為階段 2 完成

### Checkpoint 2

提示使用者讀 test-plan.md，可手動補/刪 case 後再進階段 3。

### 收尾

- 階段 2 結束**刪除 coverage.json**
- 確認 `.claude/CUP-XX-test-plan.md` 已被 git ignore：`cd frontend && git check-ignore -v .claude/CUP-XX-test-plan.md`，回 0 略過；非 0 才 append `.claude/CUP-*-test-plan.md` 到 frontend/.gitignore

---

## 階段 3：產出 Playwright 腳本

**輸入**：test-plan.md
**輸出**：`.claude/{ISSUE_KEY}-test.cjs`

### 機械步驟

1. 讀 `~/.claude/skills/cup-build-test/templates/test-cjs-template.cjs`
2. 替換 placeholder：
   - `{{ISSUE_KEY}}`
   - `{{FEATURE_TITLE}}`
   - `{{ENTRY_PATH}}` ← 從 test-plan 推（看主流程第一個導航步驟）
3. 把 test-plan 中每個 case 的「操作步驟」轉成 step 函式呼叫：
   - 移除 `// === 測試步驟區塊 ...` 之間（含 `void step; void waitStable;`）的範例與佔位行
   - 對每個 test-plan case，按操作步驟順序產 `await step(page, 'A1.1', 'descriptive-name', async (p) => { ... });`
   - selector 優先序：`data-testid` > `getByRole` > 文字 > class
   - 不確定的 selector 用註解標 `// TODO: 階段 4 跑完後補正`
4. 寫 `.claude/{ISSUE_KEY}-test.cjs`

### Checkpoint 3

執行 `node --check .claude/{ISSUE_KEY}-test.cjs` → 確認語法可解析。
失敗則回階段 3 修。
成功則告知使用者可進階段 4。

### 收尾

- 確認 `.claude/CUP-XX-test.cjs` 已被 git ignore：先跑 `cd frontend && git check-ignore -v .claude/CUP-XX-test.cjs`，回 0 表示已 cover（可能是全域 `~/.gitignore_global` 或 frontend `.gitignore`）→ 略過；非 0 才 append `.claude/CUP-*-test.cjs` 到 frontend/.gitignore

---

## 階段 4：正式環境半自動驗證

**輸入**：test-plan.md + test.cjs
**輸出**：`.claude/{ISSUE_KEY}-temp/r15/_results.json` + 截圖

### 4a. Dry-run（無瀏覽器）

1. parse test-plan.md，列出所有 case 與類型
2. **偵測 ENTRY_PATH 動態參數**（CUP-180 實戰新增）：
   - 從 test-plan 環境資訊表抓 `Entry path` 欄位
   - regex `/{[^}]+}/` 找模板變數（例 `{caseId}`、`{orderId}`）
   - 若有，**列出必填 env vars 並中止**直到使用者提供：
     ```
     Entry path 含動態參數: /case/list/{caseId}/yearlyQuotaSetting
     需要 env var: CASE_ID
     範例執行：CASE_ID=68xxxxxx VARIANT=r15 ... node .claude/CUP-XX-test.cjs
     請先提供 CASE_ID 後再進階段 4c
     ```
   - cjs 跑時用 `ENTRY_PATH.replace(/{(\w+)}/g, (_, k) => process.env[k.toUpperCase()] || '')`
3. 印計畫表：

```
=== 將執行的測試 ===
URL: https://luna.compal-health.com
總 case: 15（read-only: 5、mutation: 10 ⚠️）
預估時間: ~12 分鐘

A. 新增單次活動排程
  - A1.1 主流程 [mutation] ⚠️
  - A1.2 必填漏填 [mutation] ⚠️
  ...

⚠️ Mutation case 會在正式環境真的建立/修改/刪除資料。
   跑完後請手動清理測試資料。
```

3. **問使用者執行模式**（三選一）：
   - **一次跑完**（test-plan 穩定、case 少 < 10、mutation 不互相污染）
   - **分輪跑**（按大功能 A→B→C，每輪結束 checkpoint，適合第一次跑）
   - **自訂 ONLY**（指定 prefix 例如 `A1`）
4. **R15 baseline 自動排除 mutation**（CUP-180 實戰新增 — 正式環境跑 mutation 會污染資料）：
   - `VARIANT=r15` + `BASE_URL=https://luna.compal-health.com` 模式跑時，自動把 `[mutation]` case 標 `🚫 N/A (R15-baseline)` 並排除
   - mutation case 移到 R18 staging / local 跑（VARIANT=r18）
   - cjs 內 `step()` 包一層：`if (VARIANT === 'r15' && /mutation/i.test(caseTag)) return;`（test-plan 的 case 標記寫進 step 第三參數時觸發）
5. 等使用者確認

### 4b. 取得登入態

1. 檢查 `.playwright-auth/auth.json` 是否存在且未過期（簡單方式：跑 cjs，若 exit 2 → 缺、exit 3 → 過期）
2. 缺/過期則互動式登入（**透過 Playwright MCP，由使用者親自輸入密碼**）：
   - skill 不在對話中索取密碼、不暫存密碼於檔案、不寫 prompt 要求使用者「貼進來」
   - 流程：
     1. 用 `mcp__plugin_playwright_playwright__browser_navigate` 開 `https://luna.compal-health.com/login`
     2. 告知使用者：「**請在剛開啟的瀏覽器視窗手動輸入帳號密碼並登入**」
     3. 用 `browser_wait_for` 等使用者完成（例：等 dashboard 元素出現，或等 url 變為 dashboard）
     4. 用 `browser_run_code_unsafe` 跑 `await context.storageState({ path: '.playwright-auth/auth.json' })` 存登入態
     5. `browser_close` 關閉
3. 確認 frontend `.gitignore` 含 `.playwright-auth/`，缺則 append 並提示
4. **任何時候 skill 自己看到帳號或密碼字串都立即中止**，提示使用者：密碼只能在瀏覽器視窗輸入，不可在對話中分享

### 4c. 自動跑

**用 `ctx_execute(language: "shell", intent: "...")` 包裝執行**，避免 cjs 一行一個 JSON 全部入 context（cjs 內每個 step 都呼叫 `console.log(JSON.stringify(...))`，幾十行就吃掉幾千 tokens）。範例：

```
ctx_execute({
  language: "shell",
  intent: "test failures, console errors and summary",
  timeout: 1800000,  // 30 分鐘上限，依 case 數調
  code: `
    cd ~/Documents/Compal/luna_web/frontend
    VARIANT=r15 BASE_URL=https://luna.compal-health.com \\
      npx --yes -p playwright@latest node .claude/{ISSUE_KEY}-test.cjs 2>&1 | tail -3
    echo "=== SUMMARY ==="
    jq '.summary' .claude/{ISSUE_KEY}-temp/r15/_results.json
    echo "=== FAILS ==="
    jq '[.results[] | select(.status=="FAIL") | {caseId, name, error}]' \\
      .claude/{ISSUE_KEY}-temp/r15/_results.json
  `
})
```

`intent` 設定後 ctx 會把大量輸出建索引，回主 context 的只有 summary 與 fail 細節。

### 執行模式對應

- **一次跑完**：上述 ctx_execute call
- **分輪跑**：每輪一個 ctx_execute call（加 `ONLY=A` / `ONLY=B` / ...），每輪後問使用者「繼續/修正/中止」
- **自訂 ONLY**：加 `ONLY={prefix}` 環境變數

### 結果處理（token 紀律）

- 主 context 只保留：`summary`（pass / fail / total / consoleErrors 數量）+ fail 的 caseId、name、error 訊息
- 完整 `_results.json` 留在磁碟，需要時再 `ctx_execute` 跑 `jq` 提特定欄位
- **不要 `Read` 整個 _results.json**（>200 行常見）
- 讀截圖用 subagent 隔離 token：spawn 一個 Explore agent 讀截圖檔，回報「畫面看到什麼、跟 test-plan 預期差在哪」（< 200 字 / fail），主 context 只保留結論

### Console errors 分類（CUP-180 實戰新增）

raw consoleErrors 數量直接看會誤判 — 同一個 React lifecycle warning 可能重複幾百次。改用 unique pattern：

```bash
jq -r '.consoleErrors[]' .claude/{ISSUE_KEY}-temp/r15/_results.json \
  | sed -E 's/[0-9a-f]{24}/<id>/g; s|https?://[^ ]+|<url>|g; s/[0-9]+/<n>/g' \
  | sort -u
```

**判斷規則**：
- React lifecycle warning（`Warning: ...`）/ deprecation 訊息 → **baseline noise**，不警示
- 自寫的錯誤訊息（含中文、含 `Error:`、含應用 domain 字串如 `activity`、`patient`）→ **警示**
- HTTP 4xx/5xx → 看 caseId 對應，預期內的權限錯誤是 baseline、非預期是警示
- unique pattern 種類**新增**才警示，**不**用「總數」判斷

---

## 階段 5：根據結果修正 test-plan

**輸入**：`_results.json` + fail case 截圖摘要
**輸出**：更新後的 `.claude/{ISSUE_KEY}-test-plan.md`

### 機械步驟

對每個 fail，判斷**五類原因之一**（CUP-180 實戰擴增第 4、5 類，純三類覆蓋不夠）：

1. **測試項目錯**（test-plan 描述不符正式環境）→ 改 test-plan 操作描述/預期結果
2. **selector 錯**（test-plan 對但 cjs 寫錯）→ 階段 6 改 cjs，本階段不改 test-plan
3. **真的是 R15 bug**（正式環境就有問題）→ test-plan 加註 `<!-- KNOWN-R15-BUG: ... -->`，**不改 test-plan 主體**，並回報使用者
4. **環境前置不足**（進頁面後彈出公告 modal、引導 tooltip、權限 onboarding 攔截 pointer events，多 step 同時 fail 且 error 訊息類似 "click intercepted" / "element not visible"）→ 階段 6 改 cjs 補強 dismiss block（cjs template STEP 05.02 已是基礎），**不改 test-plan**。識別線索：≥3 step 同時 fail 且時序集中
5. **assertion 太鬆假 PASS**（cjs 有寫 step 但 selector 太通用，沒抓到實際失敗。例：點刪除後 test-plan 預期「row 從 N 變 N-1」但 cjs 只 `await waitForSelector('.table')`，永遠 PASS）→ **改 test-plan**：操作步驟補「記下變化前 N → 操作後應 < N → 清空後應 = 0」這類前後比對，再進階段 6 重產 cjs 帶 assertion

**選擇規則**：
- 多 step 集體 fail → 先疑第 4 類
- 單一 step fail + selector 找不到 → 第 2 類
- 單一 step fail + 預期不符 → 第 1 類或第 3 類（看 R15 行為對不對）
- step 顯示 PASS 但實際 UI 沒變 → 第 5 類（最容易漏）

每筆修正在對應 case 末端加：

```html
<!-- 修正紀錄 YYYY-MM-DD：原因類別 + 簡述 -->
```

更新「執行紀錄表」R15 Baseline 欄位（✅/⚠️/❌）。

### 不自動 commit

所有檔案在 `.claude/` 內、已被 .gitignore 過濾，純本地工作檔案。**skill 不執行 git add / git commit**。

### Checkpoint 5

讀 test-plan.md 改前/改後內容，產出簡短 diff 摘要給使用者確認。

---

## 階段 6：重新產出 Playwright 腳本

**輸入**：修正後 test-plan.md
**輸出**：覆蓋 `.claude/{ISSUE_KEY}-test.cjs`

### 機械步驟

**不是「整檔重產」**，是「以階段 3 cjs 為基礎做最小修改」 — 階段 4c 跑過、selector 已被驗證可用的 case 不要動，只改階段 5 標為「selector 錯」的部分。

1. 讀現有 `.claude/{ISSUE_KEY}-test.cjs`（階段 3 產出，階段 4c 已驗證部分為可用）
2. 對應階段 5 的 `_results.json`，分類每個 step：
   - `PASS` 的 step → **不動**
   - `FAIL` 但屬「測試項目錯」 → test-plan 已改，按新 test-plan 重產對應 step（換 selector / 換 step name）
   - `FAIL` 但屬「selector 錯」 → 按階段 5 學到的 selector 改寫該 step
   - `FAIL` 但屬「R15 bug」 → 該 step 加 `// KNOWN-R15-BUG: ...` 註解；保留原寫法供 R18 驗證
3. **保留 cjs 中所有 PASS step 的原始寫法**（避免「重產」誤改可用的 selector）
4. 移除階段 3 留下的 `// TODO: 階段 4 跑完後補正` 註解（已 PASS 的）
5. 移除測試步驟區塊上方的 `void step; void waitStable;`（此時已有實際 step 呼叫，不需佔位）
6. 寫回 `.claude/{ISSUE_KEY}-test.cjs`，跑 `node --check` 驗證
7. **重跑驗證**（CUP-180 實戰新增 — 不重跑會把 iter 1 的修錯帶進 iter 2 test-plan）：
   - 對 R15 baseline 重跑修正版 cjs（同階段 4c 命令）
   - 比對前後：原 fail 是否變 PASS？有沒有新 fail？
8. **依重跑結果決定是否回階段 5**：
   - 全 PASS → 進步驟 9 印用法
   - 新 fail 為「環境前置不足」殘留 → 改 cjs dismiss block，留階段 6 不回階段 5
   - 新 fail 是嚴 assertion 暴露的真問題（第 5 類「assertion 太鬆」之前漏抓）→ **回階段 5 重新分類**，改 test-plan 加前後比對描述，再重跑 6→7
   - 新 fail 為時間有限 / 偶發 → 列 backlog，**不回階段 5**，繼續步驟 9 印用法但提醒使用者
   - 連續兩次 6→5 循環無減少 fail → 中止並回報，避免無限循環
9. 印用法給使用者：

```
本地（R18）：
  npx --yes -p playwright@latest node .claude/{ISSUE_KEY}-test.cjs

Staging（R18）：
  BASE_URL=https://staging.example.com \
    npx --yes -p playwright@latest node .claude/{ISSUE_KEY}-test.cjs

R15 重跑驗證：
  VARIANT=r15 BASE_URL=https://luna.compal-health.com \
    npx --yes -p playwright@latest node .claude/{ISSUE_KEY}-test.cjs

只跑某 prefix：
  ONLY=A1 npx --yes -p playwright@latest node .claude/{ISSUE_KEY}-test.cjs

第一個 fail 就停：
  STOP_ON_FAIL=true npx --yes -p playwright@latest node .claude/{ISSUE_KEY}-test.cjs
```

---

## 失敗處理

| 情境 | 處置 |
|---|---|
| Branch 名沒有 CUP-XX | 提示使用者 `--issue CUP-XX` 或切 branch |
| 不在 luna frontend cwd | 中止，要求 `cd ~/Documents/Compal/luna_web/frontend` |
| `git diff main...HEAD` 為空 | 中止，提示先 commit |
| auth.json 過期（cjs exit 3） | 自動回階段 4b 重登 |
| auth.json 缺（cjs exit 2） | 自動回階段 4b 互動登入 |
| test-plan 已存在 | 問使用者：覆蓋 / 合併 / 中止 |
| cjs 已存在 | 同上 |
| `node --check` 失敗 | 印錯誤，回階段 3 修，不前進 |
| mutation case 跑完造成資料污染 | 階段 4 結束時提醒「請手動清理：刪除 N 筆測試活動」（具體清單由 mutation case 對應的 ID 推） |
| `npx playwright` 第一次下載慢 | 提示使用者「第一次需 ~150MB 下載，可預先 `npx --yes playwright@latest install chromium`」 |

---

## 速查表

### 與既有 skill 區隔

| Skill | 範圍 | 與本 skill 區隔 |
|---|---|---|
| `/jira-test-report` | 對單一 issue 跑既有測試 + 上 Jira | 預設用既有 test-plan；本 skill 是**從零產 test-plan**，產出可被 jira-test-report 消費 |
| `/r15-r18-verify` | 程式碼層比對 R15→R18 等價性 | 純程式碼分析，不跑瀏覽器；本 skill 是行為驗證，互補 |
| `/jira` | Jira issue 管理（建 branch、抓詳情） | 上游：本 skill 可呼叫此 skill 抓 Jira 描述補充 test-plan 前言 |

### 命名慣例

| 檔案 | 用途 | 入 git？ |
|---|---|---|
| `.claude/CUP-XX-coverage.json` | 階段 1 中繼檔 | 否（階段 2 後刪） |
| `.claude/CUP-XX-test-plan.md` | 雙用途測試文件 | 否 |
| `.claude/CUP-XX-test.cjs` | Playwright 腳本 | 否 |
| `.claude/CUP-XX-temp/<variant>/_results.json` | 跑測試結果 | 否 |
| `.claude/CUP-XX-temp/<variant>/NN-*.png` | 步驟截圖 | 否 |
| `.playwright-auth/auth.json` | 登入 storageState | 否 |

### Common selectors（luna 前端）

依 token SOP + CUP-80 + CUP-180 實戰經驗：

- 行事曆：`.fc-toolbar`、`.fc-event`、`.fc-time-grid-event`
- Bootstrap modal：`.modal.in`（R15）、`.modal.show`（R18）、`[role="dialog"]`（兩者皆吃）
- 等動畫：`waitStable(page, 300-500)`
- React-select：focus input → `ArrowDown` → `Enter`
- 按鈕文字：`button:has-text("儲存")`、`button:has-text("取消")`、`button:has-text("確認")`
- 圖示按鈕：`.glyphicon-plus`、`.glyphicon-remove`

### 環境級彈窗（**進頁面後必 dismiss**）

luna 正式環境登入後常跳「最新發布規則」公告 modal，按確認 + 勾「下次提醒」也不一定永久關閉（session-level）。**攔截 pointer events 會讓後續 step 全 fail**，cjs template 已內建 dismiss block（STEP 05.02），實作要點：

- 已知公告 modal class：`.latest-release-rote-modal`
- 通用清理 selectors：`.modal-backdrop`、`.modal.in:not([data-keep])`、`.modal.show:not([data-keep])`、`[role="dialog"]:not([data-keep])`、`.popover`、`.tooltip`
- 雙保險：先 click 「確認」/「我知道了」/「關閉」，再 nuclear DOM remove（click 因 fade-in 不一定生效）
- 解鎖 body：移除 `modal-open` class、清 `overflow` 與 `paddingRight`
- 不希望被 dismiss 的 modal（測試本身要驗的）加 `data-keep` 屬性

### Token 節省鐵則（沿用 jira-test-report v2.0）

- 截圖一律寫檔，不入 context（`page.screenshot({ path: ... })`）
- console error 收集到陣列，最後寫進 `_results.json`，不 console.log 到主 stdout
- 每 step 結束統一截圖 1 張，不在 step 中間多截
- 跑完只讀 `_results.json` summary，fail 才看細節
- 看截圖用 subagent 隔離 token

### 參考檔案

- 模板：`~/.claude/skills/cup-build-test/templates/`
- Token SOP：`~/.claude/projects/-Users-maxhero-Documents-Compal-luna-web/memory/reference_playwright_token_sop.md`
- 首發案例：`~/Documents/Compal/luna_web/frontend/.claude/CUP-80-test-plan.md` 與 `CUP-80-test.cjs`
