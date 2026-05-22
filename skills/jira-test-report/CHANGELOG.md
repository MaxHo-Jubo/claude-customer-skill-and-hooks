# jira-test-report Changelog

版本號採 [Semver](https://semver.org/lang/zh-TW/)。MAJOR=破壞既有 cjs / 流程行為、MINOR=新增 helper / 模式 / 階段步驟、PATCH=修 bug 或文件更新。

## v2.5.5 — 2026-05-22（PATCH：剩餘 prose 段落 AI.MD v4 結構化，token -220）

**變更**：5 個 prose 重災區轉 structured labels（套 AI.MD v4：attention splitting / zero-inference labels / semantic anchoring）。

| Priority | 段落 | 改造 |
|---|---|---|
| P1 | S8.1-S8.5 publish 流程 | `PATCH-LIST` / `PUBLISH-VERIFY-GREP` / `DUAL-ENV-URLS` / `FIXTURE-STRATEGY` / `HARDCODE-DEFAULT` / `JSON-MAP-FALLBACK` / `MISSING-ENV-GUARD` / `PUBLISH-PIPELINE`（10 step inline） |
| P2 | 進度紀錄機制 | `RATE-LIMIT-STRATEGY` / `PROGRESS-WRITE` / `RESUME-FSM` / `PROGRESS-WRITER` / `EXPLICIT-RESUME` |
| P3 | 模式 1 步驟 5 | `SCREENSHOT-TEMP` / `INTERACTIVE-TOKEN-RULE` / `INTERACTIVE-PROGRESS-WRITE` |
| P4 | 步驟 0.5 進度檔偵測 | `RESUME-DETECT-FSM`（decision tree + prompt-block） |
| P5 | 步驟 6 / 7 共用後段 | `UPLOAD-FLOW` / `COMMENT-FLOW` |

**成果**：

- 行數 821 → 865（+44）— structured「一規則一行」必然展開
- **Bytes 46935 → 46052（-883），Token ~11733 → ~11513（-220，-1.9%）** — 移除 prose 冗餘（人類解釋「為什麼/避免」）抵銷行數增長
- 共 29 個 structured label blocks（v2.4.7 既有 + v2.5.5 新增）

**設計取捨**：

- AI.MD v4 的核心 paradox：行數 up（每規則拿完整 attention）+ token down（短英文 label + 刪 prose 冗餘）
- S8.5 PUBLISH-PIPELINE 第一版用子欄展開（41 行）→ 壓回 inline 風格（16 行），每 step 仍獨立 line 保 attention，子欄只在 step-3 多細節時保留

**anchor 保護紀律**（避免破壞既有 cjs 對 SKILL.md 的引用）：

- 所有 H3 步驟標題（`### 步驟 S3` / `S3.5` / `S3.6`）保留 — templates/skeleton.cjs 5 處 + snippets 3 檔頭引用
- 所有 H4 子標題（`#### S8.1` ~ `#### S8.5`）保留 — SKILL.md 自己跨段引用（PATCH-LIST.patch-1、publish-前/後 等）
- structured label 名稱加在 H3/H4 標題下面，不取代標題
- 驗證：S3 / S3.5 / S3.6 / S8.1 / S8.5 / 共用後段 cross-ref 全部命中

**未做**：multi-model 驗證（AI.MD v4 Phase 6）— 此次屬 PATCH 局部 reformat，未跑 8 道測題 multi-model 驗證；下次跑 cjs 時實測 compliance 即可（同 v2.4.7 做法）

## v2.5.4 — 2026-05-22（PATCH：失敗處理抽到 docs/troubleshooting.md，SKILL.md 再瘦 -35 行）

**變更**：

- 新增 `docs/troubleshooting.md`（63 行）— 11 個失敗 symptom 完整結構（含 `cause` / `why` / `banned` / `note` 細節）
- SKILL.md「失敗處理」段（原 54 行 structured labels）→ 改為短指針 + 11 行 symptom→action 速查表 + 標題（共 19 行）
- SKILL.md 856 → 821 行

**速查表設計**：

- SKILL.md 留 11 個 symptom「symptom → 一行 action」速查表，AI 80% 場景遇錯掃 SKILL.md 即可解
- 完整 structured label（含 `cause` / `why` / `banned` 等診斷依據）放 docs/troubleshooting.md，遇 COMMENT-ATTACHMENT-VALIDATION / SCREENSHOT-ACCESS-DENIED / RATE-LIMIT 等有 banned 反模式的 case 才 Read 細節

**設計動機**：

- 失敗處理是「字典型」內容（symptom 命中後查 action），不是「規則判斷依據」
- 留 11 行速查表保住「遇錯 1 秒掃到 action」的體驗，砍掉 35 行細節給 docs/
- 與 #4 Wiki Markup / Comment 範本同思路：SKILL.md 留最常用，docs/ 放完整細節

**累計拆分進度（v2.5.0 ~ v2.5.4）**：SKILL.md 1415 → 821 行（**-594，42% 瘦身**）

## v2.5.3 — 2026-05-22（PATCH：Wiki Markup 速查 + Comment 範本抽到 docs/，SKILL.md 再瘦 -20 行）

**變更**：

- 新增 `docs/wiki-markup.md`（37 行）— Jira Wiki Markup 完整語法表 + 關鍵紀律（v2 vs v3、空格要求、code block 不解析）+ 為什麼不用 ADF v3
- 新增 `docs/comment-template.md`（68 行）— Comment 結構範本 + 區塊說明 + 腳本模式建議補充 + 簡化範例
- SKILL.md「Wiki Markup 速查」段（原 18 行表）→ 改為短指針 + 3 條最常用 + 3 條關鍵紀律（共 8 行）
- SKILL.md「Comment 結構建議」段（原 27 行 code block）→ 改為短指針 + 7 點骨架摘要（共 13 行）
- SKILL.md 876 → 856 行

**保留不動**：

- S7「發 inline comment」核心 know-how 文字（為什麼 v2 不 v3、attachment id 不能直接當 media id）
- Comment 上傳的 javascript 範例（11 行 code，這是 AI 看了直接寫的）

**設計動機**：

- Wiki Markup 速查表是「字典型」內容（查得到語法即可），AI 寫 wiki 時 Read 一次即可
- Comment 範本是「模板素材」（複製改填），inline 在 SKILL.md 每次載入吃 token 沒收益
- docs/ 與 templates/ 區分：templates/ 放可直接複製為運行檔的範本（cjs / progress.md / env），docs/ 放純文件性質的參考（語法字典 / 範本說明）

**累計拆分進度（v2.5.0 ~ v2.5.3）**：SKILL.md 1415 → 856 行（**-559，39.5% 瘦身**）

## v2.5.2 — 2026-05-22（PATCH：S3.5 / S3.6 範例 cjs 抽到 templates/snippets/，SKILL.md 再瘦 -115 行）

**變更**：

- 新增 `templates/snippets/three-in-one.cjs`（67 行）— S3.5 三合一規範 LVB-7963 A3.2 / A3.3 範例（純資料斷言用 (b) selectOption 逐一 + (a) expandSelectAsListbox 兩種補 UI 證據方式）
- 新增 `templates/snippets/cleanup-evidence.cjs`（37 行）— S3.5 Cleanup 鐵則範例（case 1 closeModal / case 2 cancel modal）
- 新增 `templates/snippets/org-switch.cjs`（77 行）— S3.6 機構切換 cjs 範本（推薦版 A0/Z9 step 結構 + 簡化版前後切換）
- SKILL.md 三段 cjs code block 共 113 行 → 改為短指針 + 重點摘要 7 行，淨砍 -115
- SKILL.md 991 → 876 行

**保留不動**（這些是 AI 寫 cjs 的判斷依據，留 inline）：

- 三合一三要素表（程式邏輯 / UI 操作 / evidence overlay 三點 + 失敗例）
- 純資料斷言補 UI 證據 (a)/(b)/(c) 三種方式說明
- `CLEANUP-EVIDENCE-BEFORE-UI` structured label（rule / triggers / why / case / inverse-evidence）
- `USE-WHEN` / `SKIP-WHEN` / `SWITCH-ORG-PIPELINE` structured labels
- Code review grep 指令、自我檢核清單

**設計動機**：

- 範例 cjs 是「Write cjs 時 Read 一次的素材」，不是「規則判斷依據」；inline 在 SKILL.md 每次載入吃 token 沒收益
- 規則本身（三要素表、structured labels、checklist）才是 AI 判斷依據，必須留 inline
- snippet 檔加 `// @ts-nocheck` 避免「片段非完整 cjs」觸發 TS diagnostic

**snippet 檔注意**：

- 都是「片段」不是完整 cjs，缺 require / launchBrowser / finally 包裝
- 寫 cjs 時可直接複製 + 改 selector / 預期值 / fixture
- placeholder 用 `/* ... */` 註解形式（非 ES spread）以通過 TS parser

**累計拆分進度（v2.5.0 ~ v2.5.2）**：SKILL.md 1415 → 876 行（**-539，38% 瘦身**）

## v2.5.1 — 2026-05-22（PATCH：progress.md 範本 + .env.local 範例抽到 templates/，SKILL.md 再瘦 -35 行）

**變更**：

- 新增 `templates/progress.template.md`（49 行）— skill 跑測試前建檔的標準範本，含 Phase A/B/C 三段結構
- 新增 `templates/env.local.example`（28 行）— `.env.local` 完整範本，三組必要 keys（E2E 登入 / Jira API / 業務 fixture）
- SKILL.md「progress.md 結構」段（原 33 行）→ 改為短指針 + 4 行結構摘要 = 淨砍 -24 行
- SKILL.md「`.env.local` 完整範例」段（原 19 行）→ 改為短指針 + 3 行 keys 摘要 = 淨砍 -12 行
- SKILL.md 1026 → 991 行（-35）

**設計動機**：

- progress.md 範本與 .env.local 範例皆屬「死範本」性質：AI 寫入時 Read 一次即可，沒必要 inline 在 SKILL.md 每次載入時都讀
- 抽到 templates/ 後維護單純：未來改範本只動 templates，SKILL.md 不需動
- 與 #2 拆 cjs 骨架同思路，完成 templates/ 目錄三件套（cjs 骨架 / progress 範本 / env 範例）

**累計拆分進度（v2.5.0 + v2.5.1）**：SKILL.md 1415 → 991 行（**-424，30% 瘦身**）

## v2.5.0 — 2026-05-22（MINOR：S3 cjs 骨架抽到 templates/skeleton.cjs，SKILL.md 瘦身 -128 行）

**變更**：

- 新增 `~/.claude/skills/jira-test-report/templates/skeleton.cjs`，內含 v2.4.4 風格完整骨架 170 行（含 placeholder 字串）
- SKILL.md L283-453 原 inline 170 行 cjs code block → 改為「`GEN-CJS-PIPELINE` 結構化流程 + PLACEHOLDER 替換清單表 + 維護注意事項」共 ~42 行
- SKILL.md 1415 → 1287 行（-128，9% 瘦身）

**設計動機**：

- SKILL.md 內 170 行 cjs 骨架對 AI 寫腳本沒有「判斷依據」價值，純屬「Write 時複製貼上」的素材；放 inline 每次載入 skill 都吃 token，且 AI 容易直接憑記憶寫骨架（漏 helpers require / parseEnv / finally 等）
- 抽到 templates/ 後流程改成「mandatory Read → 套 placeholder → 填 step → Write」，並加 `banned: 從記憶寫骨架` 強制 AI 走 Read 路徑
- 為後續 #3 拆 S3.5/S3.6 範例 cjs / #5 拆 progress.md + .env.local 範本鋪路（templates/ 目錄已建立）

**使用變化（給 AI 看的）**：

- 產 cjs 流程：S3 階段先 `Read ~/.claude/skills/jira-test-report/templates/skeleton.cjs` → 套 PLACEHOLDER 清單替換 → 在 try{} 加 step() → `Write` 到 `.claude/{ISSUE_KEY}-test.cjs`
- verify 兩條 grep：高風險（`<paste-staging-case-id>` / `{ISSUE_KEY}`）必 0 命中；低風險中文 placeholder `\{[一-龥]` 必 0 命中
- `{caseId}` runtime 佔位**不需替換**（parseEnv 自動代入）

**維護紀律**：

- 修 `templates/skeleton.cjs` 必須同步更新 SKILL.md「PLACEHOLDER 替換清單」表
- 新增 placeholder 一律 `{ }` 包起或 `<…>` 形式，讓 grep 可命中未替換位置
- helpers/ 維護機制（cup-build-test sync-helpers.sh）不影響本 templates/，**templates/ 為本 skill 內專用，不 sync 到 release-tests**

## v2.4.7 — 2026-05-20（PATCH：規則性段落 AI.MD v4 結構化，prose bullets → structured labels）

**變更**（局部 reformat，無新規則 / 新 helper / 流程行為變更）：

四個規則性段落從 prose bullets 改為 AI-parsing structured labels（套 AI.MD v4 方法論：每條 rule + why + how/banned，attention 不被 dense prose 切散；歷史 context 保留作 `why` / `case` 子欄）。Code 範例、changelog、API 速查表、Wiki Markup 速查、共用先決條件等其他段落**原樣保留**。

| 段落 | 行為 |
|---|---|
| S3「寫腳本準則」12 條 | prose bullets → 12 個 structured rule blocks（STEP-PER-ASSERTION / SELECTOR-PRIORITY / LOCATOR-CHAIN / WAIT-STRATEGY / MUTATION-SAFETY / EDIT-STATE-DETECTION / THIRD-PARTY-SELECTOR / LOGIN / GOTO-WAIT / STEP-CHINESE / ASSERTION-EVIDENCE / HELPERS-ONLY） |
| S3.5「Cleanup 鐵則」prose | 改 `CLEANUP-EVIDENCE-BEFORE-UI` block（rule / triggers / why / case / inverse-evidence）；code 範例 + grep + 自我檢核 checklist 保留 |
| S3.6「何時用 + 切換邏輯」 | `USE-WHEN` / `SKIP-WHEN` + `SWITCH-ORG-PIPELINE`（step-1 ~ step-6）；cjs 整合範本 code + 自我檢核 checklist 保留 |
| 失敗處理 11 條 | prose bullets → 11 個 symptom/action/why block（LOGIN-4xx / LOGIN-5xx / UPLOAD-401 / COMMENT-ATTACHMENT-VALIDATION / SCREENSHOT-ACCESS-DENIED / SESSION-EXPIRED / PLAYWRIGHT-MODULE-MISSING / SELECTOR-NOT-FOUND / RATE-LIMIT / RESUME-NO-PROGRESS / PROGRESS-ISSUE-MISMATCH） |

**設計動機**（AI.MD v4 理論支撐）：

- **Attention splitting**：dense prose 多條規則用 `|` / 句號黏在一行時，模型 attention 分散，部分規則 weight 降到近零。獨立 line + label 讓每條規則拿到完整 attention
- **Zero-inference labels**：`rule:` / `why:` / `banned:` / `how:` 等 label 直接宣告語意，免去模型從 prose context 推論
- **Semantic anchoring**：`LOGIN:` / `GOTO-WAIT:` / `CLEANUP-EVIDENCE-BEFORE-UI:` 等 ALL-CAPS 標題 = 可被 user prompt 直接 hash 命中的 anchor

**範圍邊界**（沒做的部分）：

- code 範例（S3 骨架、S3.5/S3.6 cjs 範本、wiki markup 範例）：完整 copy-paste 可執行，不該結構化打散
- API 速查表 / Wiki Markup 速查 / 共用先決條件：已是 structured table，AI.MD 化反而冗餘
- Changelog（v2.4.6 以前歷史）：時序紀錄，給人讀的
- multi-model 完整驗證（AI.MD v4 Phase 6）：此次屬 PATCH 局部 reformat，未跑 8 道測題 multi-model 驗證；下次跑 cjs 時實測 compliance 即可

**影響範圍**：

- 既有 cjs：不受影響（rule 內容未變，只變呈現形式）
- 新產出 cjs：AI 跟 skill 時規則命中率預期提升（特別是長對話 / 多輪 context 場景）
- 同步：cup-build-test SKILL.md 對應段落可比照 reformat（後續另起 PR）

## v2.4.6 — 2026-05-20（新增 orgGuard.cjs helper：機構切換 + 例外 case 支援）

**新增**：

- **新 helper `orgGuard.cjs`**：提供 `switchOrg(page, { keyword, expectedDisplay, waitMs })` / `currentOrg(page)` / `DEFAULT_ORG` 三個 API。jira-test-report 例外 case 屬於非預設機構（如豐原醫院、台南御宇）時，A1 前切過去、finally 切回 `compal`（仁寶長照機構），避免污染後續測試
- **新增步驟 S3.6「機構切換」段**：何時要用、helper API、切換邏輯、cjs 整合範本（A0 / Z9 step 結構 + 簡化版）、自我檢核 5 點
- **Helpers 速查表加 `orgGuard.cjs` 一行**
- **S8.2 範本 require 區塊加註解**：例外 case 才 require `orgGuard`，多數 cjs 不需要

**設計動機**：

- 帳號 `adm_max_ho` 為通用最高權限可切換機構帳號，預設機構 `仁寶長照機構` (internal code `compal`)；少部分 bug 只在特定機構特定 case_id 可重現
- 之前若手動切換到別機構後忘了切回，下次跑 LVB-7977 / ERPD-11841 等預設機構 cjs 會撈不到 case 或撈到別機構的 case，產生誤判
- helper 強制切後斷言 `expectedDisplay`，比手動點 dropdown 穩定；切後自動 `goto /case/` 避踩到 `/` 路由的 SSO redirect 雪坑

**切換邏輯關鍵設計**（解決兩個雪坑）：

1. **dropdown 顯示文字與右上角顯示文字是兩套 mapping**：dropdown 選項 `仁寶躍虎 (compal)`，但切後右上角顯示 `仁寶長照機構`。helper 不靠 substring 比對 dropdown text，而是優先用「endsWith `(${keyword})`」精準匹配 internal code（多筆過濾結果也能挑對）；fallback 才是「過濾結果唯一」分支（支援 `keyword='豐原'` 這種顯示名片段）
2. **切換後預設導向 `/` 會 SSO redirect 到 icaretest115**：helper 切後強制 `goto /case/` protected route，前端讀 token cookie 正常通過

**Smoke 驗證**：

`/tmp/orgguard-smoke.cjs` round-trip 全綠：
- Smoke 1 `currentOrg` → `仁寶長照機構`
- Smoke 2 `switchOrg(DEFAULT_ORG)` 已在預設 → noop（`switched: false`）
- Smoke 3 `switchOrg({ keyword: '豐原', ... })` → 切換成功（唯一過濾分支）
- Smoke 4 `switchOrg(DEFAULT_ORG)` → 切回成功（endsWith `(compal)` 多筆分支）

**影響範圍**：

- 新產出 cjs：屬於非預設機構的 issue 強制套用 S3.6（A0 切換 / Z9 切回）
- 既有 cjs（LVB-7977 / ERPD-11841 等預設機構 case）：不受影響，繼續用 `compal` 機構跑
- 對應 memory 候選：可加 `feedback_org_switch_required_for_non_compal_cases.md` 記錄機構切換時機（後續）

## v2.4.5 — 2026-05-20（ERPD-11841 staging 實戰回饋：injectEvidence 後 UI 互動前必須 clearEvidence）

**新增**：

- **S3.5 Cleanup 鐵則升級**：同一 step 內 `injectEvidence` 之後若還有任何 UI 互動（closeModal / .click / .fill / .selectOption 等），動作前必須 `await clearEvidence(p);`。從「下個 step 開頭 / cancel modal 前」軟性建議升級為硬性規則
- 加 ERPD-11841 A8 實戰範例：原 step 結尾 `injectEvidence → closeModal` 順序在 staging 100% 重現 `Timeout 30000ms exceeded`，error log `<div>… from <div id="e2e-evidence-panel">… subtree intercepts pointer events`；同 cjs A4 / A7 PASS 因 closeModal 在 injectEvidence「之前」
- 加 Code review grep 指令：`grep -A 20 'injectEvidence' <cjs> | grep -E 'closeModal|\.click\(|\.fill\(|\.selectOption\('`
- 自我檢核清單加一條（v2.4.5+ 鐵則）：「同 step 內 injectEvidence 之後若還有 UI 動作，動作前有 clearEvidence」

**設計動機**：

`#e2e-evidence-panel` 由 `evidence.cjs::injectEvidence` 注入 viewport 右上角 `position: fixed`，Modal 寬度大時會剛好覆蓋 modal-header 右上角的 close button，Playwright 60 次 retry 全被 pointer-events 攔截。功能本身沒 bug（人工點得下去），但腳本自己擋自己，是「腳本 bug 看起來像功能 bug」的典型雪坑。

ERPD-11841 staging 跑 A8 9 step 中 1 個 FAIL 30 秒就是這個原因。修法是 `closeModal` 前一行加 `await clearEvidence(p);`，從 47s elapsed FAIL 變 16s 全 PASS。

**影響範圍**：

- 已修：`e2e/release-tests/ERPD-11841.cjs:529` + `.claude/ERPD-11841-test.cjs:534`
- 新產 cjs：強制套用 S3.5 Cleanup 鐵則
- 既有 cjs：grep `injectEvidence` 後緊接 UI 動作但中間沒 clearEvidence 的 step，回頭補上
- 對應 memory：`feedback_clear_evidence_before_ui_action.md`

## v2.4.4 — 2026-05-19（LVB-7963 風格 codify + helpers 全面化 + 雙 skill 獨立）

**新增**：

- **S3 腳本骨架全面 helpers 化**：require 整套 `env.cjs` / `step.cjs` / `modal.cjs` / `browser.cjs` / `report.cjs` / `evidence.cjs`，cjs 主體只放測試 step 邏輯。不再 inline 寫 `step()` runner、`updateProgressMd`、`injectEvidence`、`writeResultsJson`、`fs.writeFileSync(_results.json)`、console error 收集等已有 helper 的程式碼
- **檔頭格式對齊 LVB-7963 6 段**：(1) 一句話描述 (2) Root cause (3) 修正 (4) 驗證情境 (5) 用法 / 環境變數 / 前置 (6) Exit codes（0/1/3/4）
- **S3.5 evidence overlay 改 require `evidence.cjs`**：不再 inline 30+ 行 `injectEvidence` 函式；列出 `injectEvidence` / `clearEvidence` / `expandSelectAsListbox` 三個 API 用途
- **S3 寫腳本準則加「helpers 全面化禁止 inline 重複」條**：明確禁止在 cjs 重複實作已 helper 化的功能
- **進階用法段重寫為「Helpers 架構與 API 速查」**：列出 7 個 helper 的 API 簽名與用途；標註修 helper 走 master + sync-helpers.sh
- **S8.1 機械改動從 7 點縮為 1 點**：只剩 `HELPERS_DIR` fallback 從 `~/.claude/skills/jira-test-report/helpers` 改 `path.join(__dirname, '_helpers')`；附表列出原 6 點為何不再需要
- **S8.2 require 區塊對齊 S3 完整 helpers 列表**：6 個 require 一次補齊
- **S8.5 機械步驟對齊新流程**：第 3 點 helpers 完整性檢查改為跑 `sync-helpers.sh --force` 一次性同步；第 5 點改動量從 6 點縮為 1 點；第 7 點新增 `grep injectEvidence` 自我檢查
- **失敗處理段 npm install 路徑**：從 `cup-build-test/helpers` 改為 `jira-test-report/helpers`（兩個 skill 獨立可運作）

**helpers 變化（反向同步補齊 master）**：

- `cup-build-test/helpers/evidence.cjs` 新增（先前只在 `e2e/release-tests/_helpers/`，回灌 master）：提供 `injectEvidence` / `clearEvidence` / `expandSelectAsListbox` 三個三合一規範必備 API
- `cup-build-test/helpers/env.cjs` 更新到 release-tests 端 v0.4.0：新增 `SCREENSHOT_BASE_DIR` env var（給 CI 設 `.` 避開 hidden dir glob）、`SCREENSHOT_DIR` 完全覆寫、拿掉冗餘 variant 子目錄層
- `cup-build-test/helpers/step.cjs` 更新到 release-tests 端 v0.4.0：`createStepRunner` 5 參數中文簽名 + `sanitizeForFilename` helper（保留 unicode 中文檔名）
- `cup-build-test/helpers/types.d.ts` 更新：`StepResult` 加 `description?: string`
- `sync-helpers.sh --force` 已把上述 4 個檔案推到 jira-test-report mirror 與 release-tests vendor，三邊一致

**設計動機**：

- LVB-7963 是 release-tests 第一個完整 helpers 化的腳本（520 行，cjs 主體只剩測試邏輯），但即將被刪除。先前 skill 範本仍是 v2.0 inline 寫法（LVB-7977 為證，562 行內含 100+ 行重複 helper 邏輯），新產出的 cjs 都未對齊 LVB-7963 風格
- evidence.cjs 只在 release-tests/_helpers/ 沒同步回 master，導致 .claude/ 階段腳本無法 require → 每個 cjs 都得 inline 30+ 行 injectEvidence，違反 v2.4.0 三合一規範要求
- 使用者明確要求「兩個 skill（cup-build-test / jira-test-report）獨立不互相依賴」：兩邊各自完整 helpers，透過 sync-helpers.sh 保持同步

**影響範圍**：

- **新產出 cjs**：強制套用新骨架（S3 + S3.5 + S8.1/S8.2/S8.5），平均行數從 ~560 行縮到 ~280 行
- **既有 cjs**（v2.4.3 以前）：LVB-7977 / ERPD-11841 等下次回歸時建議改寫對齊；LVB-7963 即將刪除，其風格已 codify
- **helpers master 版本建議 bump 0.3.0 → 0.4.0**：因新增 evidence.cjs + env.cjs 行為變更（破壞性需 caller 對齊新 SCREENSHOT_BASE_DIR 預設）

## v2.4.3 — 2026-05-19（ERPD-11841 實戰回饋第 2 輪：禁用 authStateFromApi，登入改 launchBrowser({ login })）

**新增**：

- S3 寫腳本準則加「**登入用 `launchBrowser({ login: loginParamsFromEnv() })`，禁止 `authStateFromApi` + `storageState`**」：luna staging `token` cookie 是 host-only，storageState 序列化會漏，且 `authStateFromApi` 沒帶 `x-request-from: web` header，後端根本不發 token cookie
- S3 骨架範本（main 開場 + S8.2 require 區塊）改用 `launchBrowser` + `loginParamsFromEnv`，移除手動 `chromium.launch` + `newContext({ storageState })` + 拋棄 `authStateFromApi`
- 本機驗證指標：腳本啟動第一行應印出 `[login] OK 200 — N cookies: token,lunastaging.sid`，**`token` 必須在 cookie 列表中**，否則進頁面後會被 SSO redirect 到 `icaretest*`

**設計動機**：ERPD-11841 在 GitHub Actions 跑 staging timeout 後本機重現，瀏覽器 `title="Loading https://icaretest115.compal-health.com/?q=ic"` 揭露真因 — 不是 wait condition，是 token cookie 沒拿到 → SSO redirect 卡死。v2.4.2 改 `domcontentloaded` 治標、v2.4.3 改 `launchBrowser({ login })` 治本。

**影響範圍**：

- 新產出 cjs 強制套用（S3 骨架已改）
- 既有 cjs `grep authStateFromApi` 應全清為 `launchBrowser({ login })`：ERPD-11841（已修）；LVB-7963 / LVB-7977 早就用 `launchBrowser` 不需動
- skill 互動模式段（約 193 行）的 `helpers/login.cjs::authStateFromApi` 引用建議下個版本一併更新為 `loginInContext`

## v2.4.2 — 2026-05-19（ERPD-11841 實戰回饋：禁用 networkidle + AUTH_EXPIRED fail-fast）

**新增**：

- S3 寫腳本準則加「**`page.goto` waitUntil 一律用 `'domcontentloaded'`，禁止 `'networkidle'`**」：luna staging R18 SPA 背景 GA4/polling 持續，networkidle 30 秒 timeout
- S3 骨架範本第 440 行同步改 `domcontentloaded`，並補上 `AUTH_EXPIRED` fail-fast block（對齊 LVB-7963.cjs 既有慣例）

**設計動機**：ERPD-11841 在 GitHub Actions release-tests workflow 跑 staging 時 `page.goto('/supervisorVisitRecord', { waitUntil: 'networkidle' })` 30 秒 timeout 直接 fail。同寫法 LVB-7963 `/homecareCaseClose` 過得了是因為該頁 polling 較少，networkidle 在 SPA 上行為不穩定不可靠。

**影響範圍**：

- 新產出 cjs 強制套用（S3 骨架已改）
- 既有 cjs 應逐步回頭把 `networkidle` 換成 `domcontentloaded`：ERPD-11841（已修）、LVB-7963（暫時還能過但建議下次回歸時換掉）

## v2.4.1 — 2026-05-19（LVB-7977 實戰回饋：DOM-driven 判斷 + _helpers 完整性檢查 + 跑前清空 temp）

**新增**：

- S3 寫腳本準則加「**判斷進入子頁/編輯狀態預設 DOM-driven**」：SPA inline 編輯 URL 通常不變，靠 URL diff 判斷會永遠 false。改靠 DOM 訊號（表單欄位 / 按鈕 / typeahead mount）。luna FE r15/r18 多數頁面屬此模式但少數會 push history state，第一次寫腳本時 `HEADLESS=false` 觀察一次再決定
- S3 寫腳本準則加「**第三方元件 selector 寫前先 grep 實際版本**」：react-bootstrap-typeahead v1.x 用 `.bootstrap-typeahead`，v4+ 改 `.rbt-`，差異大；寫死 selector 前先查 `node_modules/<lib>/lib/*.js` 或 `package.json`
- S8.5 機械步驟第 3 點：**確認 `_helpers/` 內必要 cjs 完整**，缺則自動 cp from `~/.claude/skills/cup-build-test/helpers/`。空 `_helpers/`（只含 node_modules）為首次 publish 常見狀態，不應中止流程
- 步驟 5 / S4 開頭加 `rm -rf .claude/{ISSUE_KEY}-temp` 跑前清空（`--resume` 模式例外）：避免 step 改名留下 stale 截圖污染 Phase B 上傳

**設計動機**：LVB-7977 實戰踩到三個坑 — (1) A2 用 `url !== originalUrl` 判斷進入編輯頁永遠 false（luna 點編輯 URL 不變）；(2) TYPEAHEAD selector 用 v4+ `.rbt-*` 但 react_15 是 v1.x `.bootstrap-typeahead`，找不到任何元素；(3) Phase B 上傳前 temp dir 留有「A4 鄧 → 改成 A4 陳」兩個版本的截圖，未手動刪會混淆 Jira inline comment。

## v2.4.0 — 2026-05-19（斷言截圖三合一規範：程式邏輯 + 真實頁面操作 + evidence overlay）

**變更**：

- 新增 **S3.5 斷言截圖三合一規範**（強制）：每個 step 必須同時具備
  1. 程式邏輯斷言（throw new Error 含實測 vs 預期對比）
  2. 真實頁面操作或視覺變更（DOM 至少一處可截圖識別的變化）
  3. 斷言結論可視化（evidence overlay 注入右上角）
- 純資料比對 step（截圖前後雷同）視為 anti-pattern，強制用以下方式之一補回頁面證據：
  - (a) 強制 native 元素展開呈現（如 `<select>.size = N` 變 listbox）
  - (b) 逐項真實 UI 互動（如 `selectLocator.selectOption()` 逐選驗證）
  - (c) DOM highlight + 標號 outline / badge
- 提供 `injectEvidence(p, {...})` 標準格式 helper 範例（inline 在 cjs，可選擇抽到 _helpers/evidence.cjs）
- 提供 LVB-7963 A3.2 / A3.3 範本重構（必要選項用 (b) 逐一 selectOption、完整 14 項用 (a) listbox 展開）
- 提供 cleanup pattern（cancel modal 前移除 evidence overlay）
- 提供 self-check 5 點清單（每個 step throw / UI 證據 / evidence / cleanup / 對比訊息）

**設計動機**：LVB-7963 實戰發現 A3.2~A3.4 三步截圖完全雷同（純對 JS 陣列做 includes 比對 + 順序比對），非工程 stakeholder 看 Jira inline comment 與 GitHub Actions artifact 無法判讀斷言依據，等同沒測。三合一規範強制每個斷言 step 都同時驗證程式邏輯與 UI 行為，截圖內可見斷言結論。

**影響範圍**：

- 新產出 cjs 強制套用（S3 寫腳本準則 + S3.5 規範）
- 既有 cjs（LVB-7963 / CUP-180 / ERPD-11841）建議下次回歸時逐步補上 evidence overlay；LVB-7963 為首要範例改造目標
- S8.5 機械步驟可加第 9 點：grep `injectEvidence` 確認斷言 step 都有注入（未來版本補）

## v2.3.2 — 2026-05-19（產出 release-tests cjs 強制中文化 step 呼叫）

**變更**：

- S3「寫腳本準則」加一條「step 呼叫中文化」：所有產出 cjs 一律用 5 參數中文版簽名 `step(page, caseId, '中文短名', '中文長描述', async (p) => {...})`
- S3 腳本骨架的 `step()` inline 函式改為支援 4 參數新版 + 2 參數 legacy 向後相容；截圖檔名改為 `{idx}-{caseId}-{中文短名}.png`，sanitize 改保留 unicode（中文不被替換成 `-`）
- S3 腳本骨架的「測試步驟區塊」範例改用 5 參數中文版示範
- S8.1 機械改動清單加第 7 點：publish 到 release-tests 時 grep `step(page,` 確認所有呼叫已中文化，未中文化要補
- 設計動機：release-e2e workflow 跑完後，使用者在 GitHub Actions Job summary / artifact `_results.json` / 截圖檔名 / Jira inline comment 都吃 `name` / `description`，中文化讓非技術 stakeholder 看 workflow 結果就能理解每步在做什麼；對齊 LVB-7963 已落地的 `_helpers/step.cjs createStepRunner` 5 參數簽名規範

**helpers 變化**：

- `e2e/release-tests/_helpers/step.cjs` `createStepRunner` 已於 LVB-7963 commit 提供 5 參數簽名向後相容（typeof 判斷第 4 個 arg 是 function 或 string）
- `e2e/release-tests/_helpers/types.d.ts` `StepResult` 加 `description?: string`
- jira-test-report skill helpers/ 透過 `~/.claude/skills/cup-build-test/scripts/sync-helpers.sh` 同步即跟進

## v2.3.1 — 2026-05-18（fixture 管理改推 hardcode default）

**變更**：

- S8.4 fixture 管理主推方案改為 **hardcode staging default + `process.env` 覆寫**（JSON map 移至 Fallback 段）
- 設計動機：luna 個案 uuid 不含個資，hardcode 進 cjs 比 GitHub Variables 設定簡單、新增 cjs 不需要二段 PR、cjs 自帶測試規格不必跨檔 trace
- JSON map 保留作為「公司政策禁止個案 id 進 git」時的 fallback 方案

## v2.3.0 — 2026-05-18（步驟 8 publish 到 release-tests 強制 + 雙環境驗證 + fixture 管理）

**變更**：

- 步驟 8「publish 到 release-tests」從「選用」改強制執行（只腳本模式適用）
- 新增 **S8.1 機械改動清單**：6 點對齊（HELPERS_DIR、chromium 路徑、SCREENSHOT_DIR、env.local 載入、progress.md silent、檔頭註解）
- 新增 **S8.2 範本 require 區塊**：可直接複製對齊 LVB-7963 風格
- 新增 **S8.3 驗證時機**：Local + Staging 雙環境
  - `.env.local` 同時宣告 `BASE_URL`（dev）與 `STAGING_URL`（staging）
  - 切換靠 `BASE_URL=$STAGING_URL` 前綴，不需改 cjs
  - 對齊 CI `secrets.E2E_STAGING_URL` 語義
- 新增 **S8.4 fixture 管理**：CASE_ID / DAYCARE_CASE_ID 等業務輸入
  - 推薦 GitHub Variables 用 **JSON map `RELEASE_TEST_FIXTURES`**（key=issue, value=env map）
  - workflow matrix step 用 `jq` export 為 env，cjs 完全不知 issue key
  - 缺 fixture exit code 4（MISSING_ENV，對齊 LVB-7963）
- 新增 **S8.5 機械步驟**：8 步驟清單從偵測 repo root 到提示使用者觸發 workflow

**設計動機**：先前 release-tests publish 是選用、僅留指針到 cup-build-test，導致 ERPD-11841 手動補 6 點機械改動才能上 release-tests。把這些抽出來、加上雙環境驗證紀律與 fixture 統一管理規範

## v2.2.0 — 2026-05-18（Atlassian credentials 改存 .env.local）

**變更**：

- Atlassian email / API token / site 一律改存 `.env.local`（keys：`ATLASSIAN_EMAIL` / `ATLASSIAN_API_TOKEN` / `ATLASSIAN_SITE`），**不再從對話索取**
- 新增「`.env.local` 完整範例」段，列出 E2E + Atlassian 兩組必要 keys
- 步驟 2 / 步驟 S2 / 步驟 6 / 步驟 7 / 步驟 10 全部改為從 `process.env` 讀
- 步驟 10「撤銷 token」改為選用 — token 持續複用，rotate 時才撤銷
- `.gitignore` 必含 `.env.local`（之前已有，文字加強）

**設計動機**：避免每次跑都要使用者貼 token，省 round trip；同時把 secret 集中在 gitignored 檔，降低不小心 commit 風險

## v2.1.0 — 2026-05-14（與 cup-build-test 共用 helpers）

**新增**：

- 引入 cup-build-test helpers 共用機制：`~/.claude/skills/jira-test-report/helpers/` 從 cup-build-test sync 而來（用 `~/.claude/skills/cup-build-test/scripts/sync-helpers.sh`）
- 步驟 S3 加「進階用法：引用 cup-build-test helpers」段，建議 cjs 引用：
  - `waitAndDismissOnEntry / dismissAnnouncement`（公告 modal 集中處理）
  - `ensureCleanState`（mutation step 入口防禦性 cleanup）
  - `confirmYes / confirmNo`（「是/否」「確認/取消」二次確認對話統一處理）
- 既有 cjs 不強制升級，新產 cjs 推薦用 helpers

**設計動機**：cup-build-test v1.1.0 累積的 luna 系統 modal handling 修正（CUP-179 / CUP-180 實戰），抽 helper 共用避免兩個 skill 重複維護。修一處兩個 skill 受益。

**helpers/ 版本**：跟 cup-build-test/helpers/ 0.2.0 一致（透過 sync-helpers.sh 同步）

## v2.0.0 — 2026-05-08（progress.md cross-session resume）

**新增**：

- 模式 1 互動模式（Playwright MCP）+ 模式 2 腳本模式（生成 .cjs + node 執行）並存
- progress.md 跨 session resume 機制（rate limit 預備）
- `--resume` 旗標 + 顯式要求機制
- Phase A/B/C 分段紀錄（跑測試 / Jira 上傳 / inline comment）
- Wiki Markup inline 截圖機制（comment 要用 v2 wiki 才能 inline，v3 ADF 不行）
- attachment 上傳走 v3 endpoint
- 互動模式截圖必指定 filename（避免 base64 入 context）

**首發案例**：ERPD-11841（2026-05-04，互動模式）、CUP-80（2026-05-07，腳本模式首發）
