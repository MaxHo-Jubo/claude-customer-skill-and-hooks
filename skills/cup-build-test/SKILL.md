---
name: cup-build-test
description: >
  CUP 項目從 commit 反推測試項目 → 產雙用途測試計劃 → 產 Playwright 腳本
  → 正式環境半自動驗證 → 修正並重產腳本。當使用者提到 /cup-build-test、
  「建立 CUP 測試」、「從 commit 反推測試」、「CUP 驗證腳本」、想為 CUP
  項目建立完整測試流程時觸發。不適用於：單一 issue 跑既有測試（用
  /jira-test-report）、純 R15/R18 程式碼比對（用 /r15-r18-verify）。
version: 1.1.0
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

skill 共 6 階段（外加階段 0、0.5），每階段結束會 checkpoint 讓使用者 review：
- 階段 1 → coverage.json review（漏什麼補什麼）
- 階段 2 → test-plan.md review
- 階段 3 → cjs 語法檢查 + 可選 review
- 階段 4 → dry-run 計畫表 + 每 case 寫入 progress.md + 跑完 summary
- 階段 5 → test-plan 修正 diff + progress.md 狀態更新
- 階段 6 → 印用法

### 進度紀錄機制（cross-session resume）

階段 4 跑測試時 token 燒得快，**遇到 rate limit 時若閒置等待 reset 反而最貴** — Anthropic 是 5 小時滾動視窗，session 閒置會讓 prompt cache（5 分鐘 TTL）過期，恢復時整個 SKILL.md / test-plan.md / cjs 都得重讀，瞬間燒掉幾萬 token 重建 cache。

正確策略：**rate limit 一到就 `/clear` 開新 session**，下次用 `--resume` 旗標續跑。

#### progress.md 結構

`.claude/{ISSUE_KEY}-progress.md`，每跑完一個 case 立刻寫入：

```markdown
## Test Run Progress — CUP-XX

Variant: r15
Started: 2026-05-08 14:00
Last update: 2026-05-08 14:45

### [x] A1.1 修改照顧計畫並儲存 [read-only]
- Status: PASS (一次過)
- Screenshot: .claude/CUP-XX-temp/r15/01-A1.1.png
- Run at: 2026-05-08 14:23

### [x] A1.2 刪除照顧計畫 [mutation]
- Status: FAIL → FIX → PASS
- Attempts: 2
- Failure type: #4 環境前置不足（公告 modal 蓋住刪除鈕）
- Fix applied: cjs STEP 05.02 dismiss block
- Screenshots: .claude/CUP-XX-temp/r15/02a-fail.png, 02b-pass.png

### [x] B1.1 新增評估表單 [mutation]
- Status: FAIL (R15 真實 bug, 不修 test-plan)
- Failure type: #3 R15 bug
- Note: 已加 KNOWN-R15-BUG 註記到 test-plan
- Screenshot: .claude/CUP-XX-temp/r15/03-bug.png

### [ ] B1.2 編輯班表 [mutation]   ← 下次 --resume 從這裡接
### [ ] B1.3 ...
```

#### 寫入時機

- **階段 4a dry-run 完成**：建檔，所有 case 列為 `[ ]` 未勾選
- **階段 4c 每跑完一個 case**：cjs 內 `step()` wrapper 結束時 Edit progress.md，對應 case 從 `[ ]` 改 `[x]` 並填 status / screenshot / run at
- **階段 5 修正後**：Edit progress.md 對應 case，status 從 `FAIL` 改 `FAIL → FIX (待重跑)`，加 `Failure type` / `Fix applied`
- **階段 6 重產 cjs 完成**：不動 progress.md（保留歷史），下一輪重跑時 attempt 計數 +1

#### 續跑模式（`--resume`）

新 session 帶 `--resume` 旗標啟動時：
1. 階段 0 跑完後進**階段 0.5**：讀 `.claude/{ISSUE_KEY}-progress.md`
2. 找第一個 `[ ]` 未勾選 case → 設 `RESUME_FROM={caseId}`
3. **跳過階段 1、2、3**（test-plan.md 與 cjs 已存在，不重產 — 這是省 token 的關鍵）
4. 直接進階段 4 dry-run，4c 跑時 cjs 帶 `RESUME_FROM` env var → 跳過所有編號 ≤ RESUME_FROM 的 case
5. 新結果 append 到既有 progress.md

#### 為什麼要顯式 `--resume` 旗標

避免兩種誤觸發：
1. **舊 progress.md 殘留** — 上次失敗忘了清，新需求被誤判為續跑
2. **同 JIRA 不同 commit 範圍** — 反推範圍變了，progress.md 已過時但被沿用

無 `--resume` 旗標但偵測到 progress.md 存在時，**階段 0.5 問使用者**（不自動決定）。

### 產物 git 政策

**所有產物不入 repo**。skill 會自動檢查 frontend/.gitignore 是否包含以下規則，缺則 append：

```
.claude/CUP-*-test-plan.md
.claude/CUP-*-test.cjs
.claude/CUP-*-temp/
.claude/CUP-*-coverage.json
.claude/CUP-*-progress.md
.claude/CUP-*-verification-report.md
```

### Playwright runtime：helpers/ user-level 安裝（**target 專案 0 dep**）

CUP-179 實戰糾正（之前寫「不依賴 package.json，用 npx -p playwright@latest 動態取得」是**錯的假設**）：
- `npx -p playwright@latest node script.js` **不會**讓 script 能 require playwright（NODE_PATH 沒被設）
- 即使解決 module 解析，chromium 二進制檔還是要 `playwright install chromium` 才有

正確設計：playwright 裝在 helpers/ 自己的 `node_modules`（user-level），target 專案保持 0 dep，跨專案共用。

**首次 setup（一次性，user 機器）**：

```bash
cd ~/.claude/skills/cup-build-test/helpers
npm install                          # ~17MB module
npx playwright install chromium      # ~92MB chromium driver to ~/Library/Caches/ms-playwright/
```

**browser.cjs 多層 fallback**（已實作）：
1. cwd node_modules — 專案剛好已裝（如 luna frontend）
2. helpers/ user-level node_modules — 主要路徑
3. `~/.npm/_npx/<hash>/node_modules/playwright` — emergency fallback

任一找到就用。全失敗時印 setup 指南並 throw。

## 前置條件

- cwd 在 luna_web/frontend（或結構相同的 R15→R18 repo）
- 當前 branch 名含 `CUP-\d+`（例：`CUP-80/refactor/max_ho/...`）
- branch 已 commit 過完成的功能（`git diff <default-branch>...HEAD` 非空）
- **default branch 自動偵測**：skill 用 `git symbolic-ref refs/remotes/origin/HEAD` 取得（luna 是 `master`、其他 repo 可能是 `main`），偵測失敗 fallback `main`
- **helpers/ user-level setup 已跑過**（見上段；首次跑前一次性安裝；之後跨專案共用）
- **需 `jq`**：macOS 多數已有，沒裝跑 `brew install jq`（階段 4c 用 jq 從 _results.json 提 summary）

## 觸發旗標

| 旗標 | 用途 |
|---|---|
| `--from-stage N` | 從第 N 階段開始（1-6），跳過前面 |
| `--issue CUP-XX` | 手動指定 issue（branch 名解析失敗時） |
| `--with-gitnexus` | 階段 1 加碼用 GitNexus 分析間接依賴 |
| `--focus auto\|equivalence` | 階段 2 test-plan 產出 focus；預設 `auto`（全功能列舉），`equivalence` 專注 R15/R18 行為差異（從 commit 訊息抽取「修正/修復 R18 升級」類字眼） |
| `--only A1` | 階段 4 只跑特定 prefix |
| `--resume` | 從 `.claude/{ISSUE_KEY}-progress.md` 第一個未勾選 case 續跑（跳過階段 1-3，省 token） |

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

## 階段 0.5：進度檔偵測（cross-session resume）

每次啟動都跑，**決定走完整流程還是續跑模式**：

1. 解析 `ISSUE_KEY`（從 branch 名或 `--issue` 旗標，邏輯與階段 1 步驟 1 同）
2. 檢查 `.claude/{ISSUE_KEY}-progress.md` 是否存在
3. **不存在** → 走完整流程（階段 1 → 6）
4. **存在 + 帶 `--resume` 旗標** → 進入續跑：
   - 讀 progress.md，找第一個 `[ ]` 未勾選 case → 設 `RESUME_FROM={caseId}` 環境變數
   - **跳過階段 1、2、3**（test-plan.md 與 cjs 已存在）
   - 直接進階段 4 dry-run，4c 跑時帶 `RESUME_FROM`
5. **存在但無 `--resume` 旗標** → **問使用者**（不自動決定）：

   ```
   ⚠️  偵測到既有進度檔：.claude/CUP-XX-progress.md
       最後更新：2026-05-08 14:45
       已跑：12 / 25 case（PASS: 8, FAIL→FIX: 4）
       下一個未跑：B1.2 編輯班表

   選擇：
     [1] 續跑（等同 --resume）
     [2] 刪除舊檔，重跑完整流程
     [3] 中止，我要手動檢查
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

   **若主流程帶 `--with-gitnexus`，每個 subagent prompt 必須加入以下段落**（CUP-179 實戰糾正：原本只有主 context 跑 impact，subagent 用 grep 反推效率低、漏抓 caller）：

   ```
   **可用工具**：mcp__gitnexus__query / mcp__gitnexus__context / mcp__gitnexus__impact / mcp__gitnexus__cypher
   **使用時機**：
     - query(goal="<本 feature 中文名>", query="<關鍵字>") — 找執行流程與相關 symbol，比 grep 涵蓋多
     - context(name="<symbol>") — 取得單一 symbol 的 360 度視圖（callers/callees/processes）
     - impact(target="<symbol or file>", direction="upstream") — 找呼叫此 symbol 的所有地方（取代 LSP findReferences）
   **省 token 紀律**：impact / query 都會列大量項目，**摘要後回報**，不要把 raw JSON 貼回。
   ```

   - **API agent**：
     - 讀 diff 暫存檔抓 `axios.{get|post|put|delete}` / `fetch(` / `createApi` / RTK Query / `apiSlice`
     - **額外**讀改動 `.tsx`/`.jsx` 中 `import` 的 service 檔（往上追 1 層）→ 列出該 service 的所有 method
     - **額外**主動 ls `frontend/src/apiServer/`、`frontend/src/services/`、`frontend/src/api/` 目錄，找與改動 feature 相關的服務檔讀 → 列出全部 endpoint
     - 對改動檔案的 export function 用 LSP `findReferences` 找呼叫端（**有 gitnexus 時改用 `impact(target=funcName, direction=upstream)`**，覆蓋率與信心分數都更高）
   - **UI agent**：
     - 對 `.tsx`/`.jsx` 改動檔案讀檔 → 列出元件、按鈕、表單欄位、modal、tab、route entry
     - **元件 regex 排除**：全大寫常數（`^[A-Z][A-Z_0-9]+$`、長度 > 3 視為 SCREAMING constant，不是元件）
     - 對改動 `pages/` 檔案，讀其 import 找出 entry path（route）
     - **有 gitnexus 時**：對主元件用 `query(goal="<feature 名>", query="route entry")` 找 React Router 註冊位置
   - **Redux agent**：
     - 對 `actions/` `reducers/` `sagas/` `store/` 改動檔案讀檔 → 列出 action type 與副作用、saga effect
     - **luna 慣例**：action type 多為 camelCase 字串如 `'fetchActivityList'`，不是 SCREAMING_SNAKE。subagent 提示要同時抓 camelCase 與 SCREAMING_SNAKE_CASE 兩種
     - 抓 saga 的 `takeLatest(actionType, worker)` 與 `put({ type: ... })` 列副作用流程
     - **有 gitnexus 時**：對 action creator 函式名用 `context(name="actionName")` 找所有 dispatch 位置
5. **若 `--with-gitnexus`**：對改動檔案**逐一**收集 importer / caller，併入 coverage。
   - **檔案分類**（CUP-179 實戰新增）：用 `git cat-file -e $(git merge-base master HEAD):<file>` 判斷新增 vs 修改。
   - **工具選擇**（CUP-179 實戰糾正）：
     - **React 元件 / TS interface 檔（.tsx / .ts / .jsx）**：`impact(target=<name>)` 對 React 元件多半回 `impactedCount: 0`（CALLS edge 不抓 JSX 元素使用）。**改用 cypher 一次批次查 IMPORTS**：
       ```cypher
       MATCH (caller:File)-[:CodeRelation {type: 'IMPORTS'}]->(f:File)
       WHERE f.filePath IN [<改動檔案清單>]
       RETURN f.filePath AS target, caller.filePath AS importer
       ORDER BY f.filePath, caller.filePath
       ```
       一次 query 拿到全部 18 檔的 importers，比逐檔 impact() 快、覆蓋率高。
     - **純函式 / class（.js / saga / reducer）**：用 `impact(target=<funcName>, direction=upstream, maxDepth=2)` 找 CALLS chain。
     - **SCSS / JSON / .d.ts**：跳過（gitnexus 多半不索引 IMPORTS）。
   - **批次 cypher 範例輸出**：每個改動檔列出 importer 清單；某 file 沒出現在結果代表「無人 import」（可能是 entry point 或新檔未被引用）。
   - 對 importer 數量極多的 type 檔（CUP-179 的 `IReducerState.tsx` 130+ importer），標 `riskLevel: HIGH`，但同步評估「**本次 diff 是新增還是修改既有欄位**」決定 `actualRisk`。純新增 slice → actualRisk: LOW。
   - **逐檔輸出格式**（每個檔案一條，併入 `coverage.indirectDeps`）：
     ```json
     {
       "file": "frontend/.../X.tsx",
       "kind": "modified|added",
       "impacted": [
         {"name": "Y", "filePath": "...", "depth": 1, "edgeType": "CALLS|IMPORTS", "confidence": 0.9}
       ]
     }
     ```
   - **省 token**：每檔 impact 結果只保留 d=1（WILL BREAK），d=2 限 3 個樣本；超過寫 `"...and N more"`。
   - **失敗處置**：`impact` 回 `Target not found`（symbol 名沒命中）改用 file path 當 target 重試；仍失敗則跳過該檔，**不阻擋**主流程。
   - 18 檔案逐一跑可能耗 30-60s，但比漏 caller 安全。本步驟設計為**完整覆蓋優先**。
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
2. **先 grep `~/.claude/skills/cup-build-test/helpers/` 目錄看有什麼可用** —— template 內已 require 7 個 helper 模組（env / step / modal / browser / bundle / report / types）。Helper API 速查見「速查表 > Helper API 速查」段。**新功能優先擴充 helper 而非 inline 寫進 cjs**：例如新發現的公告 modal selector 應加進 `helpers/modal.cjs` 的 `DEFAULT_ANNOUNCEMENT_SELECTORS`，而不是寫死在 cjs 內 evaluate。
3. 替換 placeholder：
   - `{{ISSUE_KEY}}`
   - `{{FEATURE_TITLE}}`
   - `{{ENTRY_PATH}}` ← 從 test-plan 推（看主流程第一個導航步驟）
4. 把 test-plan 中每個 case 的「操作步驟」轉成 step 函式呼叫：
   - 移除 `// === 測試步驟區塊 ...` 之間（含 `void step; void skipStep; void waitStable;`）的範例與佔位行
   - 對每個 test-plan case，按操作步驟順序產 `await step(page, 'A1.1', 'descriptive-name', async (p) => { ... });`
   - selector 優先序：`data-testid` > `getByRole` > 文字 > class
   - 不確定的 selector 用註解標 `// TODO: 階段 4 跑完後補正`
   - navigate 到其他頁面後重新呼叫 `await dismissAnnouncement(p);`（helper 已 import）
   - C 群 bundle / variant 驗證直接用 `await assertVariant(p, env.variant);`，不 inline 寫 srcs.some 判斷
5. 寫 `.claude/{ISSUE_KEY}-test.cjs`

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
3. **偵測可選 case id env var**（CUP-180 實戰新增 — 避免大量假 SKIP）：
   - grep cjs 找所有 `process.env.XXX_CASE_ID || ''` 或 `process.env.XXX || ''` 模式
   - 列出讓使用者**一併提供**（不是必填、跳過會 SKIP 對應 case）：
     ```
     偵測到選填 env var（提供後該 step 才會跑，否則 SKIP）：
       - EMPTY_CASE_ID  : 無資料邊界（A1.2 empty-data）
       - DAYCARE_CASE_ID: 日照系統 case id（C2.2 居服日照同 flag）
     ```
   - 若使用者無法提供任一項，標註該 step 將 SKIP 並繼續，不擋整輪執行
   - **目標：每次跑都帶滿所有可選 env var，最小化 SKIP 數量**（CUP-180 baseline 不帶這兩個會多出 2 SKIP）
4. 印計畫表：

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
6. **建立 progress.md**（cross-session resume 用）：把所有 case 列為 `[ ]` 未勾選狀態，寫到 `.claude/{ISSUE_KEY}-progress.md`，並寫入 `Variant` / `Started` 欄位。若帶 `--resume` 旗標跳過此步（檔案已存在，append 模式）。

### 4b. 取得登入態（API 模式，無人為介入）

local dev (localhost:3000) 與 CI / staging URL 都統一走 API 登入，**完全不走互動式 Playwright MCP**。

1. **檢查 `.env.local` 是否存在**（在 frontend 根目錄）：
   - 內容範例：
     ```
     BASE_URL=http://localhost:3000              # 或 https://staging.example.com
     E2E_ACCOUNT=<帳號>
     E2E_PASSWORD=<密碼>
     E2E_TYPE=e
     ```
   - **必填**：`BASE_URL` / `E2E_ACCOUNT` / `E2E_PASSWORD`。`E2E_TYPE` 預設 `e`
   - 缺檔則提示使用者建立並列出範例內容，**但 skill 自己絕不索取密碼、不寫入密碼**
2. **檢查 `.gitignore` 含 `.env.local`**，缺則 append 並提示
3. **檢查 `.gitignore` 含 `.playwright-auth/`**（舊互動模式產物，向後相容）
4. **不需要手動登入**：cjs 透過 `helpers/login.cjs::authStateFromApi` 直接呼叫 `/account/login` 取得 cookies，每次跑 cjs 都即時拿 storageState，**不再依賴 `.playwright-auth/auth.json`**
5. **跑 cjs 前先驗證等價**（首次或登入 API 變動時）：
   ```bash
   cd <frontend>
   set -a; source .env.local; set +a
   node ~/.claude/skills/cup-build-test/scripts/diagnose-auth.cjs
   ```
   - ✅ cookies / localStorage 等價 → cjs 直接用 `launchBrowser({ login: ... })`
   - ⚠️ 有差異 → 依輸出提示在 cjs 加 `context.addInitScript` 補塞必要 localStorage key
6. **安全紀律**（絕對遵守）：
   - **任何時候 skill 自己看到帳號或密碼字串都立即中止**並提示「密碼只能放 `.env.local` 或 Keychain，不可在對話中分享」
   - 不在對話中索取密碼、不暫存密碼於非 gitignored 檔案、不把密碼寫進 cjs source
   - 密碼來源：`.env.local`（local）/ GitHub Secrets（CI）/ macOS Keychain（最佳）

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
      node .claude/{ISSUE_KEY}-test.cjs 2>&1 | tail -3
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

### 每 case 寫入 progress.md（cross-session resume）

cjs 內 `step()` wrapper 每跑完一個 case **立即寫檔**，不等整輪結束：

```js
// cjs 內，每個 case 結束後（pseudo-code）
const fs = require('fs');
const progressPath = `.claude/${ISSUE_KEY}-progress.md`;
const status = result.status === 'PASS' ? 'PASS' : `FAIL: ${result.error}`;
const screenshot = `.claude/${ISSUE_KEY}-temp/${VARIANT}/${caseId}.png`;
// 用 regex 替換 progress.md 內對應 case 的 [ ] → [x] 並填欄位
updateProgressMd(progressPath, caseId, {
  status,
  screenshot,
  runAt: new Date().toISOString(),
});
```

寫檔頻率高但每次只動一段（< 200 bytes），相比 cache rebuild（重讀整個 SKILL.md + test-plan.md + cjs ≈ 30k+ tokens）便宜兩個數量級。

**為何在 cjs 內寫而非主 context Edit**：cjs 在 ctx_execute sandbox 內跑，主 context 只看到 summary。若改由主 context 每 case Edit 一次，反而把 case-by-case 進度全部拉進主 context，違反 token 紀律。

**RESUME_FROM 處理**：cjs 開頭讀 `process.env.RESUME_FROM`，若有值則 step() wrapper 內判斷 `caseIdLessThanOrEqual(caseId, RESUME_FROM)` 直接 return。

### 結果處理（token 紀律）

- 主 context 只保留：`summary`（pass / fail / total / consoleErrors 數量）+ fail 的 caseId、name、error 訊息
- 完整 `_results.json` 留在磁碟，需要時再 `ctx_execute` 跑 `jq` 提特定欄位
- **不要 `Read` 整個 _results.json**（>200 行常見）
- 讀截圖用 subagent 隔離 token：spawn 一個 Explore agent 讀截圖檔，回報「畫面看到什麼、跟 test-plan 預期差在哪」（< 200 字 / fail），主 context 只保留結論

### 4d. 不可在正式環境帶的 env var（safety guard，CUP-180 實戰新增）

⚠️ cjs 若實作「臨時改 server state」的測試（toggle feature flag、建立測試資料、改使用者設定…），必須加 `ENABLE_*_TEST=true` 之類的 GUARD，且 **GUARD 預設 false（`!== 'true'` 才跑）**。正式環境執行時**絕對不可帶**這類 env var：

| GUARD | 用途 | 正式可帶? |
|---|---|---|
| `ENABLE_TOGGLE_TEST=true` | 臨時 toggle feature flag（CUP-180 C2.2 flag-toggle-no-redeploy） | 🚫 **不可**（會影響真實使用者） |

dry-run 階段印 env var 清單時要分兩欄：「正式可帶」/「local 限定」。

```
env var 用途分類：
  正式可帶  : CASE_ID, EMPTY_CASE_ID, DAYCARE_CASE_ID, ...
  local 限定: ENABLE_TOGGLE_TEST, ...
```

跑正式 baseline 時：
- 自動排除「local 限定」env var（即使使用者帶了也忽略 + 警告）
- 對應 step 標 SKIP，reason 為「`ENABLE_TOGGLE_TEST=true` 不可在正式跑」

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

### baseline FAIL 第一反應決策樹（CUP-180 實戰新增）

進入五類分類前，**先用 error 訊息特徵快速排除最常見的 cjs 缺陷**：

1. error 含 `intercepts pointer events` / `subtree intercepts pointer events`
   → **修 dismissAnnouncement helper** 補上漏處理的 modal selector，重跑（多 step 同時 fail 多半屬此類）
2. error 含 `locator.click: Timeout` 且 selector 是 row 上按鈕（編輯/刪除）
   → 多半是 R15/R18 元件差異 → 加 selector fallback（例 `.btn-warning.btn-sm`）
3. error 含 `locator.fill: Timeout` 且 selector 是 input
   → 多半 selector 過時或被 modal 蓋住 → 第 2 類或第 4 類
4. 以上皆非 → 才進入下方五類詳細分類（真實 bug 罕見，因為 R15 已上線過）

⚠️ **不要看到 baseline FAIL 就先判 R15 bug**：先檢查 cjs 是否漏處理 modal/selector 才能下結論（CUP-180 重跑出 16 FAIL，根因全是 cjs dismissAnnouncement helper 漏覆蓋 `.FeatureTermsOfUseModal`，跟 R15 行為無關）。

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

### 更新 progress.md

每筆修正後**也更新 progress.md 對應 case 條目**：
- Status: `FAIL` → `FAIL → FIX (待重跑)`（重跑 PASS 後階段 4c 會再改 `FAIL → FIX → PASS`）
- 加 `Failure type: #N {說明}`（對應五類分類）
- 加 `Fix applied: {test-plan 改了哪、cjs 改了哪}`
- Attempts +1

階段 6 重產 cjs 後**不動** progress.md，下一輪階段 4c 重跑該 case 才會更新最終狀態。

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
5. 移除測試步驟區塊上方的 `void step; void skipStep; void waitStable;`（此時已有實際 step 呼叫，不需佔位）
6. **失敗源於共用邏輯時優先修 helpers/，不要 inline patch 在 cjs**：
   - 「intercepts pointer events / 公告 modal 攔截」→ 改 `helpers/modal.cjs` 的 `DEFAULT_ANNOUNCEMENT_SELECTORS` 或 `waitAndDismissOnEntry`
   - 「react-bs-table filter / sort wait 時間不夠」→ 改 `helpers/step.cjs` 的 `waitStable` 預設值或加新 helper
   - 「bundle 判斷 / R15 vs R18 selector 切換」→ 改 `helpers/bundle.cjs` 的 `assertVariant`
   - 「console.error / pageerror 收集邏輯」→ 改 `helpers/browser.cjs` 的 `attachConsoleCollector`
   - Helper 修完後不需動 cjs，重跑階段 4c 即可驗證
7. 寫回 `.claude/{ISSUE_KEY}-test.cjs`，跑 `node --check` 驗證
8. **重跑驗證**（CUP-180 實戰新增 — 不重跑會把 iter 1 的修錯帶進 iter 2 test-plan）：
   - 對 R15 baseline 重跑修正版 cjs（同階段 4c 命令）
   - 比對前後：原 fail 是否變 PASS？有沒有新 fail？
9. **依重跑結果決定是否回階段 5**：
   - 全 PASS → 進步驟 10 印用法
   - 新 fail 為「環境前置不足」殘留 → 改 `helpers/modal.cjs` 補 selector（**不要** inline patch 在 cjs），留階段 6 不回階段 5
   - 新 fail 是嚴 assertion 暴露的真問題（第 5 類「assertion 太鬆」之前漏抓）→ **回階段 5 重新分類**，改 test-plan 加前後比對描述，再重跑 6→7
   - 新 fail 為時間有限 / 偶發 → 列 backlog，**不回階段 5**，繼續步驟 10 印用法但提醒使用者
   - 連續兩次 6→5 循環無減少 fail → 中止並回報，避免無限循環
10. 印用法給使用者：

```
本地（R18）：
  node .claude/{ISSUE_KEY}-test.cjs

Staging（R18）：
  BASE_URL=https://staging.example.com \
    node .claude/{ISSUE_KEY}-test.cjs

R15 重跑驗證：
  VARIANT=r15 BASE_URL=https://luna.compal-health.com \
    node .claude/{ISSUE_KEY}-test.cjs

只跑某 prefix：
  ONLY=A1 node .claude/{ISSUE_KEY}-test.cjs

第一個 fail 就停：
  STOP_ON_FAIL=true node .claude/{ISSUE_KEY}-test.cjs
```

（playwright module 由 helpers/ user-level 安裝提供，target 專案 0 dep；首次 setup 見「Playwright runtime」段）

### 步驟 11：產 verification report（CUP-179 實戰新增）

**輸入**：`.claude/{ISSUE_KEY}-temp/r15/_results.json`（必要）+ `.claude/{ISSUE_KEY}-temp/r18/_results.json`（若有）
**輸出**：`.claude/{ISSUE_KEY}-verification-report.md`

**觸發時機**：R15 baseline + R18 local 雙 variant 都跑完整套後（或使用者明確要求收尾）。**Staging 跑完後也應重產一次**併入 Staging 欄。

**為何要做**：CUP-180 是手寫 verification report、CUP-179 是口頭產，沒檔留紀錄。skill 應該自動產 markdown 草稿給人工 sign-off 用，這是 PR review / 移交時的關鍵文件。

#### 機械步驟

1. 檢查 `.claude/{ISSUE_KEY}-temp/r15/_results.json` 是否存在 — 不存在則跳過此步驟（提示「無 R15 baseline 結果，跳過 verification report」）
2. 用 `jq` 從各 variant `_results.json` 抓：
   - `summary`（total / pass / fail / skip）
   - `results` 陣列（每 case 的 caseId / name / status / error）
3. 組合 markdown report（schema 見下）：
   - 標題 + Issue / Branch / 日期（`date -u +%Y-%m-%d`）
   - **總覽表**：每 variant 一列（pass / fail / skip / 總計）
   - **Case 對照表**：每 case 一列，欄位 = R15 / R18 local / Staging（沒跑的標 `—`）
   - **FAIL 詳情**：列出所有 fail case 的 error message（從 \_results.json `error` 欄）
   - **SKIP 原因**：列出所有 skip case 的 reason
   - **結論段**：根據 PASS/FAIL 數量自動推導（全綠→等價性驗證 PASS、有 fail→列出待修）
4. 用 `Write` tool 寫入 `.claude/{ISSUE_KEY}-verification-report.md`
5. **不自動 commit**（同 test-plan/cjs 政策，全部在 `.claude/` 內已 gitignore）
6. 確認 `.gitignore` 含 `.claude/CUP-*-verification-report.md`，缺則 append

#### Report markdown schema

```markdown
# 📊 {{ISSUE_KEY}} 測試驗收報告

**Branch**: {{BRANCH_NAME}}
**Issue**: {{ISSUE_KEY}}（含關聯 issue 如 CUP-182）
**測試日期**: {{YYYY-MM-DD}}

## 1. 總覽

| 環境 | URL | PASS | FAIL | SKIP | 總計 |
|---|---|---|---|---|---|
| R15 線上 baseline | {{R15_URL}} | x | x | x | x |
| R18 local | http://localhost:3000 | x | x | x | x |
| Staging | {{STAGING_URL or '—'}} | — | — | — | — |

## 2. Case 對照表

| Case | 類型 | R15 | R18 local | Staging | 備註 |
|---|---|---|---|---|---|
| A1.1 ... | read-only | ✅ | ✅ | — | |

## 3. FAIL 詳情

（自動產：列出 fail case + error）

## 4. SKIP 原因

（自動產：列出 skip case + reason）

## 5. 結論

✅ 全綠 / ⚠️ 部分 fail / ❌ 多 fail 待修
```

#### 不自動觸發的情境

- R15 baseline 沒跑完 → 不產（沒對照基準）
- 使用者明確說「Staging 跑完再產」→ 跳過此步驟，留下提示

---

## 失敗處理

| 情境 | 處置 |
|---|---|
| Branch 名沒有 CUP-XX | 提示使用者 `--issue CUP-XX` 或切 branch |
| 不在 luna frontend cwd | 中止，要求 `cd ~/Documents/Compal/luna_web/frontend` |
| `git diff main...HEAD` 為空 | 中止，提示先 commit |
| `.env.local` 不存在 | 階段 4b 提示使用者建立並列出範例 |
| 登入 API 回 4xx（密碼錯/account 鎖） | 印錯誤訊息，要求使用者驗證 `.env.local` 內容；不自動 retry |
| 登入 API 回 5xx | retry 一次；仍失敗則中止 |
| cjs exit 2（舊互動模式 auth.json 缺） | 提示改走 API 模式（建 `.env.local`） |
| test-plan 已存在 | 問使用者：覆蓋 / 合併 / 中止 |
| cjs 已存在 | 同上 |
| `node --check` 失敗 | 印錯誤，回階段 3 修，不前進 |
| mutation case 跑完造成資料污染 | 階段 4 結束時提醒「請手動清理：刪除 N 筆測試活動」（具體清單由 mutation case 對應的 ID 推） |
| 缺 playwright module / chromium driver（首次跑或 helpers/ 沒 setup）| browser.cjs requirePlaywright 會印 setup 指南並 throw：`cd ~/.claude/skills/cup-build-test/helpers && npm install && npx playwright install chromium`（一次性，跨專案共用，~110MB） |
| 階段 4 跑到一半 rate limit | **不要閒置等待**（5 分鐘 prompt cache 會過期，恢復時瞬間燒幾萬 token 重建 cache）。建議：當前 case 跑完後 `/clear` 開新 session，下次用 `/cup-build-test CUP-XX --resume` 從 progress.md 接續 |
| `--resume` 但 progress.md 不存在 | 提示使用者：尚未跑過階段 4，無進度可續，請去掉 `--resume` 旗標 |
| 偵測到 progress.md 但 test-plan.md 缺 | 中止，提示「進度檔孤立，可能是 test-plan 被誤刪」，要求人工檢查 |
| **單跑 PASS / 全跑 FAIL**（CUP-179 實戰）| 多為 case 順序污染：前面 case 留下 modal 殘留 + Redux state 不同步。修法：在 fail 的 mutation step 入口加 `await ensureCleanState(p)`（`helpers/modal.cjs` 提供）。symptom：等開 modal timeout、modal 開了讀不到 input value、selector 抓到 2 個 modal |
| 「改動此日期...」「確認要刪除嗎?」二次確認對話 | 用 `confirmYes(p)`（接受）/ `confirmNo(p, { scope })`（拒絕），不要 inline 寫 `button:has-text("是")` selector |

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
| `.claude/CUP-XX-progress.md` | 跨 session 進度紀錄（`--resume` 用） | 否 |
| `.claude/CUP-XX-verification-report.md` | 階段 6 步驟 11 自動產出的驗收對照表 | 否 |
| `.env.local` | API 登入帳密（BASE_URL/E2E_ACCOUNT/E2E_PASSWORD/E2E_TYPE）| 否 |
| `.playwright-auth/auth.json` | 舊互動模式 storageState（deprecated，僅向後相容）| 否 |

### Common selectors（luna 前端）

依 token SOP + CUP-80 + CUP-180 實戰經驗：

- 行事曆：`.fc-toolbar`、`.fc-event`、`.fc-time-grid-event`
- Bootstrap modal：`.modal.in`（R15）、`.modal.show`（R18）、`[role="dialog"]`（兩者皆吃）
- 等動畫：`waitStable(page, 300-500)`
- React-select：focus input → `ArrowDown` → `Enter`
- 按鈕文字：`button:has-text("儲存")`、`button:has-text("取消")`、`button:has-text("確認")`
- 圖示按鈕：`.glyphicon-plus`、`.glyphicon-remove`

### 環境級彈窗（**進頁面後必 dismiss**）

luna 正式環境登入後常跳「**兩種**」公告 modal，皆會攔截 pointer events，**讓後續 step 全 fail**：

- `.latest-release-rote-modal`：最新發布規則（登入後固定跳，按確認 + 勾「下次提醒」也不一定永久關閉，session-level）
- `.FeatureTermsOfUseModal`：功能使用條款（feature 上線時跳，**可能在 B/C 群操作中途才跳出**，不是只有登入後）

處理機制由 `helpers/modal.cjs` 提供（template 內已 require）：

- `DEFAULT_ANNOUNCEMENT_SELECTORS` = `['.latest-release-rote-modal', '.FeatureTermsOfUseModal']` —— 新發現的公告 modal 直接 push 進此陣列
- `waitAndDismissOnEntry(page)`：進入頁面後完整流程（等 modal 出現 → click 確認 → nuclear DOM remove）；template STEP 06.02 已呼叫
- `dismissAnnouncement(page, extraSelectors?)`：navigate 到其他 case 後重複呼叫的精簡版（純 DOM remove）
- 通用清理 selectors（內建於 helper）：`.modal-backdrop`、`.popover`、`.tooltip`
- 雙保險：先 click 「確認」/「同意」/「我知道了」/「關閉」，再 nuclear DOM remove（click 因 fade-in 不一定生效）
- 解鎖 body：移除 `modal-open` class、清 `overflow` 與 `paddingRight`（已內建）
- **每次 navigate 後重新呼叫 `dismissAnnouncement(p)`**（不是只在登入後一次），因為 FeatureTermsOfUseModal 可能在進入特定 feature 頁面才跳
- 不希望被 dismiss 的 modal（測試本身要驗的）加 `data-keep` 屬性

⚠️ **baseline 跑出 FAIL 不要急著判 R15 bug**：先看 error 訊息是否含 `intercepts pointer events`，若有 → 改 `helpers/modal.cjs` 的 `DEFAULT_ANNOUNCEMENT_SELECTORS` 加上漏處理的 selector 再重跑（CUP-180 實戰：A 群全 PASS、B 群 16/16 FAIL，根因是 FeatureTermsOfUseModal 在 B 群跳出而 helper 只覆蓋一種 modal）。**修 helper 一處，所有 CUP 測試共用該修正**。

⚠️ **mutation step 入口必加 `await ensureCleanState(p)`**（CUP-179 實戰新增）：公告 modal 之外，前面 case 開過的「**編輯 / 確認 / 檢視 modal**」也可能殘留並破壞 React/Redux state 與 DOM 的同步（直接 DOM nuke 但 Redux state.modal 還是 true → 下次 dispatch show 沒重 render → modal 不顯示）。`ensureCleanState` 會：先點殘留 modal 的「取消/否」讓 Redux 同步、再 nuke DOM、清 body.modal-open。read-only step 不用加（不開 modal 無殘留問題）。

### Token 節省鐵則（沿用 jira-test-report v2.0）

- 截圖一律寫檔，不入 context（`page.screenshot({ path: ... })`）
- console error 收集到陣列，最後寫進 `_results.json`，不 console.log 到主 stdout
- 每 step 結束統一截圖 1 張，不在 step 中間多截
- 跑完只讀 `_results.json` summary，fail 才看細節
- 看截圖用 subagent 隔離 token

### Helper API 速查

template 已 require 以下模組，**修改測試共用邏輯（modal / waitStable / bundle 判斷等）優先改 helper，不要 inline patch 在 cjs**。

| Module | 匯出 | 用途 |
|---|---|---|
| `helpers/env.cjs` | `parseEnv({ issueKey, entryPath, defaults? })` | 解析 process.env → frozen EnvConfig；缺 ISSUE_KEY / 動態參數 env var 直接 exit 4 |
| `helpers/env.cjs` | `resolveEntryPath(template)` | 把 `/case/list/{caseId}` 換成 `/case/list/abc123`（camelCase → SNAKE_CASE env） |
| `helpers/step.cjs` | `createStepRunner({ screenshotDir, progressPath?, only?, resumeFrom?, stopOnFail? })` | 工廠：回傳 `{ step, skipStep, waitStable, getResults }`，已含 ONLY/RESUME_FROM filter + 自動截圖 + progress.md 寫入 |
| `helpers/step.cjs` | `caseIdCompare(a, b)` | caseId 大小比較（A1.1 < A1.2 < A2.1） |
| `helpers/step.cjs` | `updateProgressMd(path, caseId, fields)` | 寫 progress.md 對應 case 區塊（失敗 silent） |
| `helpers/modal.cjs` | `DEFAULT_ANNOUNCEMENT_SELECTORS` | 已知 luna 公告 modal class 陣列。**發現新公告直接 push 進此陣列** |
| `helpers/modal.cjs` | `DEFAULT_APP_MODAL_SEL` | 「真正的」編輯/確認/檢視 modal 預設 selector（排除公告 modal，R15 `.modal.in` + R18 `.modal.show` 皆覆蓋） |
| `helpers/modal.cjs` | `waitAndDismissOnEntry(page, { timeout?, extraSelectors?, waitMs? })` | 進入頁面後完整 dismiss 流程（等 → click → nuke） |
| `helpers/modal.cjs` | `dismissAnnouncement(page, extraSelectors?)` | navigate 後重複呼叫用的精簡版（純 DOM remove） |
| `helpers/modal.cjs` | `ensureCleanState(page, { appModalSel?, extraAnnouncementSelectors?, waitMs? })` | **mutation step 入口必呼叫**：dismiss 公告 + 點取消殘留 modal 讓 Redux 同步 + nuke DOM。解決連跑時前 case modal 殘留導致新 modal 開不起來（CUP-179 實戰） |
| `helpers/confirmDialog.cjs` | `confirmYes(page, { timeout?, scope?, extraButtonTexts?, strategy? })` | 點二次確認對話「是 / 確認 / 確定 / 刪除 / 同意」（接受）。預設 strategy=last 抓最新跳出的 modal |
| `helpers/confirmDialog.cjs` | `confirmNo(page, { ... })` | 點二次確認對話「否 / 取消 / 關閉」（拒絕）。參數同 confirmYes |
| `helpers/confirmDialog.cjs` | `DEFAULT_YES_BUTTON_TEXTS` / `DEFAULT_NO_BUTTON_TEXTS` | 預設按鈕文字清單，發現新文字直接 push |
| `helpers/login.cjs` | `authStateFromApi({ baseUrl, account, password, type?, loginPath? })` | API 登入取 storageState（cookies）；失敗 throw |
| `helpers/login.cjs` | `loginParamsFromEnv()` | 從 `BASE_URL`/`E2E_ACCOUNT`/`E2E_PASSWORD`/`E2E_TYPE` env 組登入參數；缺必填 throw |
| `helpers/browser.cjs` | `launchBrowser({ headless, login?, authPath?, viewport?, locale? })` | chromium.launch + newContext + newPage；`login` 為主流程（API 登入），`authPath` 為 deprecated 後備 |
| `helpers/browser.cjs` | `attachConsoleCollector(page, errors)` | 註冊 console.error / pageerror handler，append 到傳入陣列 |
| `helpers/bundle.cjs` | `detectBundle(page)` → `BundleInfo` | 回傳 `{ hasR15, hasR18, hasReactBsTable, fiberKey }` |
| `helpers/bundle.cjs` | `assertVariant(page, 'r15' \| 'r18')` | 驗證 bundle path + react-bs-table 存在性 + fiber key，不符 throw |
| `helpers/report.cjs` | `writeResultsJson(dir, { issueKey, variant, baseUrl, results, consoleErrors })` | 寫 `_results.json`（含自動算 summary） |
| `helpers/report.cjs` | `printSummary(results, consoleErrors)` | stdout 印一行 `DONE: x/y PASS ...` |
| `helpers/report.cjs` | `exitCodeForResults(results)` → 0 \| 1 | 有 FAIL 回 1 |
| `helpers/types.d.ts` | `StepResult` / `StepFn` / `EnvConfig` / `VariantName` / `BundleInfo` | 集中 typedef，用 `/** @typedef {import('./types').StepResult} StepResult */` |
| `helpers/stubs.d.ts` | (ambient) | playwright / fs / path / os / process 最小 stub，讓 helpers/ 不裝 npm 套件也能 type check |

**CUP_HELPERS_DIR 環境變數**：template 預設從 `~/.claude/skills/cup-build-test/helpers/` require，CI / 鏡像位置可用此 env var 覆寫。

**型別檢查**：在 `~/.claude/skills/cup-build-test/helpers/` 跑 `npx --yes -p typescript tsc --project tsconfig.json`，零輸出代表通過。

### 參考檔案

- Helper library：`~/.claude/skills/cup-build-test/helpers/`（env / step / modal / confirmDialog / browser / bundle / report / types / stubs）
- 模板：`~/.claude/skills/cup-build-test/templates/`
- 抽出計畫：`~/.claude/plans/ticklish-forging-jellyfish.md`
- Token SOP：`~/.claude/projects/-Users-maxhero-Documents-Compal-luna-web/memory/reference_playwright_token_sop.md`
- 首發案例：`~/Documents/Compal/luna_web/frontend/.claude/CUP-80-test-plan.md` 與 `CUP-80-test.cjs`
- 第二案例：`~/Documents/Compal/luna_web/frontend/.claude/CUP-180-test.cjs`（**保留現狀不動**，作為 helper 抽出來源樣本）
- 第三案例：`~/Documents/Compal/luna_web/frontend/.claude/CUP-179-test.cjs`（R18 mutation step 完整範例：confirmYes / ensureCleanState 實戰用法、F3 整 modal 簽名比對、D1.1 DELETE_TEST_NOTE_KEY 安全機制）

---

## Changelog

版本號採 [Semver](https://semver.org/lang/zh-TW/)。MAJOR=破壞既有 cjs / API 行為、MINOR=新增 helper 或階段步驟、PATCH=修 bug 或文件更新。

### v1.1.0 — 2026-05-14（CUP-179 實戰新增）

**新增**：

- `helpers/modal.cjs` 新增 `ensureCleanState(page, options?)` — mutation step 入口防禦性 cleanup。解決連跑時前 case modal 殘留導致 React/Redux state 不同步，下次 dispatch show 不重 render 的問題（CUP-179 C2.1 / F3 連跑撞牆而抽出）
- `helpers/modal.cjs` 新增 `DEFAULT_APP_MODAL_SEL` — 排除公告 modal 的 `.modal.in`/`.modal.show` 統一 selector
- `helpers/confirmDialog.cjs`（新檔）提供 `confirmYes(page, opts?)` / `confirmNo(page, opts?)` 與 `DEFAULT_YES_BUTTON_TEXTS` / `DEFAULT_NO_BUTTON_TEXTS` — 統一處理「是/否」「確認/取消」二次確認對話 modal，預設 strategy=last 抓 DOM 後出現的最新 modal
- 階段 6 步驟 11：自動產 verification report — 從 `_results.json` 比對 R15 baseline / R18 local / Staging，產出對照表 markdown 寫到 `.claude/CUP-XX-verification-report.md`
- `templates/test-cjs-template.cjs` 加 mutation step 範例（含 `ensureCleanState` + `confirmYes` 用法）
- `helpers/stubs.d.ts` 補 `Locator.last()` 型別定義
- SKILL.md「失敗處理」表新增 2 條（單跑 PASS / 全跑 FAIL、二次確認對話）
- 命名慣例表加 `.claude/CUP-*-verification-report.md`
- 產物 git 政策段加 `.claude/CUP-*-verification-report.md`

**helpers/ 版本**：0.1.0 → 0.2.0

**實戰學到的坑**（驅動本版本演進）：

- 連跑時 case 順序污染（前面 case 留下 modal 殘留導致新 modal 開不起來）
- R18 點儲存後跳「改動此日期...」二次確認對話，cjs 原本沒處理
- 刪除確認對話按鈕是「是/否」非「確認/確定」
- F3 兩 row 生效日恰好相同無法驗 modal remount → 改用整 modal 簽名比對
- R15 ExpandTable sub-tr 與主 row 交錯，`nth(1)` 抓到沒按鈕的 sub-tr

### v1.0.0 — 2026-05-13（CUP-180 實戰固化）

**初版抽出**：

- 6 階段流程定型（commit 反推 → test-plan → cjs → R15 baseline → 修正 → 重產）
- `helpers/` user-level Playwright 架構（取代失敗的 `npx -p playwright@latest` 動態取得）
- `progress.md` cross-session resume 機制 + `--resume` 旗標
- `helpers/modal.cjs` 公告 modal 集中管理（`DEFAULT_ANNOUNCEMENT_SELECTORS` / `dismissAnnouncement` / `waitAndDismissOnEntry`）
- `helpers/step.cjs` 工廠模式（`createStepRunner` 含 ONLY/RESUME_FROM filter + 自動截圖 + progress.md 寫入）
- `helpers/browser.cjs` 多層 Playwright module 解析 fallback
- `helpers/bundle.cjs` R15/R18 bundle 偵測與 assertVariant
- `helpers/report.cjs` _results.json 寫入 + summary 印出
- env var safety guard（如 `ENABLE_TOGGLE_TEST` 不可在正式環境帶）
- Console errors unique pattern 分析（去 React lifecycle warning noise）
- subagent verbosity 限制（階段 1 反推節省 token）
- CASE_ID dynamic ENTRY_PATH 機制
- `mutationStep()` wrapper — VARIANT=r15 自動 SKIP

**首發案例**：CUP-80（手工建檔），CUP-180 (機械化 + helper 抽出來源)
