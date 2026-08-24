# 快速查詢目錄

> 所有自訂 skill、hook、script 的一頁式參考。
> 上次更新：2026-07-25（Skills 與 Plugins 清理——停用 9 個 skills、移除 `daily-review`、停用 6 個 plugins、新增 `ai-case-report` skill 與 `mcp-outline` plugin；前次 2026-07-24 新增 `stop-review-guard.ts` Stop hook）

---

## Skills

### Skill 載入狀態總覽

由 `settings.json` → `skillOverrides` 控制（v2.1.129+）。未列出者預設 `on`（描述會主動進入 system prompt）。

| Skill | 狀態 | 說明 |
|-------|------|------|
| `ai-md` | `user-invocable-only` | 僅手動 `/ai-md` 觸發；不主動推薦 |
| `humanizer-zh-tw` | `user-invocable-only` | 僅手動 `/humanizer-zh-tw` 觸發 |
| `upgrade-to-status` | `off` | 完全隱藏（2026-07-25 由 `user-invocable-only` 降級） |
| `method-refactor` | `off` | 完全隱藏（2026-07-25 清理） |
| `jira-acceptance` | `off` | 完全隱藏（2026-07-25 清理） |
| `claude-max-quota` | `off` | 完全隱藏（2026-07-25 清理） |
| `explore-report` | `off` | 完全隱藏（2026-07-25 清理） |
| `plan-and-execute` | `off` | 完全隱藏（2026-07-25 清理） |
| `spec-design` | `off` | 完全隱藏（2026-07-25 清理） |
| `spec-to-e2e-test` | `off` | 完全隱藏（2026-07-25 清理） |
| `test-module` | `off` | 完全隱藏（2026-07-25 清理） |

> `daily-review` 已於 2026-07-25 完全移除本機目錄（repo 端版控歷史保留，見 git log）。

**四種狀態**：`on`（完整載入）｜`name-only`（只載名稱省描述）｜`user-invocable-only`（保留指令但不主動推薦）｜`off`（完全隱藏）。Plugin 內的 skill 不受此設定控制，須用 `/plugin` 開關。

---

### 開發流程類

#### `/jira` — Jira Issue 管理（v1.1.0）

- **位置**：`~/.claude/skills/jira/SKILL.md`
- **用法**：`/jira`、`/jira fetch`、`/jira branch {ISSUE_ID}`
- **功能**：
  - 自動從 git branch 名稱識別 Jira issue
  - 抓取 issue 詳情（含 issuelinks，最多追蹤 2 層）
  - 建立開發筆記 `.claude/{ISSUE_ID}.md` 與原始資料 `.claude/{ISSUE_ID}-Jira.md`
  - 管理 branch 建立
- **依賴**：Atlassian MCP、`JIRA_CLOUD_ID`、`JIRA_USERNAME`（設定於 `~/.claude/CLAUDE.md`）
- **連動**：完成 fetch 或 branch 建立後，提示使用者呼叫 `/linus-requirements-analysis`

#### `/linus-requirements-analysis` — Linus Style 需求分析（v1.0.0）

- **位置**：`~/.claude/skills/linus-requirements-analysis/SKILL.md`
- **用法**：`/linus-requirements-analysis`、`/linus-requirements-analysis {需求描述}`
- **功能**：6 步結構化需求審查
  1. 這是真問題嗎？（法規/真實痛點/想像中的問題）
  2. Show me the case（要求具體案例，不憑空分析）
  3. 資料結構先行（先定義 data model）
  4. 有更簡單的方案嗎？（現有功能組合、改設定、最小改動量）
  5. 會破壞什麼？（資料相容性、其他模組影響、向後相容）
  6. 不要過度泛化（先解決眼前案例）
- **輸出**：【核心判斷】→【關鍵洞察】→【資料結構影響】→【方案】→【風險】→【不做的事】
- **Jira 回寫**：分析完成後可選擇將結論寫入 Jira issue comment
- **依賴**：Atlassian MCP（回寫時）

#### `/jira-acceptance` — Jira 需求驗收（v1.0.0）

- **位置**：`~/.claude/skills/jira-acceptance/SKILL.md`
- **用法**：`/jira-acceptance`、`/jira-acceptance {ISSUE_KEY}`
- **功能**：
  - 從 Jira 取得需求描述（summary、description、subtasks、acceptance criteria）
  - 分析 `git diff` 的實際改動
  - 逐條判定：✅ 已實作 / ⚠️ 部分實作 / ❌ 未實作
  - 產出結構化驗收報告
- **依賴**：Atlassian MCP、git repository

#### `/jira-test-report` — Jira issue Playwright 測試報告（v2.5.5）

- **位置**：`~/.claude/skills/jira-test-report/SKILL.md`（含 `helpers/`、`docs/`、`templates/` 子目錄；`CHANGELOG.md`）
- **用法**：`/jira-test-report`、`/jira-test-report {ISSUE_KEY}`、`/jira-test-report --resume`
- **功能**：
  - 對 Jira issue 跑 Playwright E2E 測試
  - 自動截圖並以 inline 形式上傳到 issue comment（直接顯示在留言中，非附件清單）
  - 支援 `progress.md` 機制：中斷後可 `--resume` 從上次斷點繼續
  - **v2.4.0**：落實「斷言截圖三合一規範」（程式斷言 throw / UI 視覺變更 / evidence overlay 注入結論，三者缺一不可）；`helpers/login.cjs::loginInContext` 保留 host-only cookies
  - **v2.5.x 結構重整**：SKILL.md 1415 → 821 行（-42%）；抽出 `docs/`（troubleshooting/wiki-markup/comment-template）與 `templates/`（env.local.example/progress.template.md/skeleton.cjs/snippets/）；新增 CHANGELOG.md
  - **v2.5.5**：套 AI.MD v4（attention splitting / zero-inference labels / semantic anchoring），5 個 prose 重災區轉 structured labels（共 29 個 label blocks）；行數 821 → 865（+44），token ~11733 → ~11513（**-220 / -1.9%**）；所有 H3/H4 anchor 保留以維持 cjs / snippets 跨段引用
  - **v2.2.0 起**：登入流程改用 API（`.env.local`），移除互動式 MCP 登入；步驟 8 可選 publish 到業務 repo `e2e/release-tests/`
- **與既有 skill 區隔**：對既有 test-plan 跑測試並上 Jira；`cup-build-test` 是從零產 test-plan + 自我驗證
- **依賴**：Atlassian MCP、Playwright MCP、git repository

#### `/weekly-review` — 每週工作回顧（v1.8.0）

- **位置**：`~/.claude/skills/weekly-review/SKILL.md`
- **用法**：`/weekly-review`、`/weekly-review --days 14`
- **功能**（8 步驟）：
  1. Git 工作摘要（按專案分組）— **v1.8.0 起改用 `multi-repo-commit-scanner` agent 平行掃描**（8 實體 repo / 9 entry，luna_web 用 pathspec 拆 FE/BE），主 agent 等聚合 JSON 後組裝週報
  2. 觀察記錄回顧（claude-mem timeline/search）
  3. Auto Memory 變動掃描
  4. 週報彙整與模式提取（含 Skill/Subagent/MCP Server 建議；MCP Server 建議判斷依據：ERRORS.jsonl 中跨 skill 的重複 API call pattern、觀察記錄中「每次都要重新查」的模式）
  5. 記憶整理（過期/重複/升級建議，需使用者確認）
  6. Skill 錯誤 Pattern 分析（Subagent A，與 STEP 08 平行）— 執行 `summarize_errors.py`，提取高頻 pattern（≥3 次）
  7. Skill 修補建議（依賴 STEP 06）— 讀取 SKILL.md，產出 before/after 建議，不自動修改
  8. Amendment 成效追蹤（Subagent B，與 STEP 06 平行）— 比對 `AMENDMENTS.md` 修補前後錯誤頻率
- **快捷觸發**：「整理記憶」→ 只執行 STEP 05；「review skill errors」→ 直接執行 STEP 06~08
- **依賴**：git、claude-mem MCP、auto memory、`post_tool_error.py` hook（ERRORS.jsonl）、`summarize_errors.py`

#### `/sync-my-claude-setting` — 同步本機 Claude 設定到 Repo（v1.8.2）

- **位置**：`~/.claude/skills/sync-my-claude-setting/SKILL.md`
- **用法**：`/sync-my-claude-setting`
- **功能**：
  1. Diff — 細緻比對 `~/.claude/` 與 repo 的差異（檔案用 `diff -u`，目錄用 `diff -rq` 再逐一展開）
  2. Copy — 從本機複製到 Repo（檔案用 `cp`，目錄用 `rsync -av --delete` mirror 模式）；CLAUDE.md 複製前以 `sed` 移除 `<conn>` 區段（含個人連線資訊），再儲存為日期後綴版本
  3. Generate Docs — 自動掃描 skills/hooks/scripts/plugins，重新產生 `README.md` 與 `CATALOG.md`；**STEP 03.0 載入 `skills-sources.json`**（read-only），在重新產生時自動為登錄的外部 skill 補上「來源」欄位
  4. Commit — 根據差異報告產生 commit message 並 commit（**不 push**）
  5. Review — 依 hook 判定的 Tier 跑 `commit-review` skill；Tier 0 只需通知
  6. Push — review 完成、修正 `--amend` 收進同一個 commit 後才推送，並驗證兩個 remote 對齊
- **push 移到 review 之後（v1.6.0 新增）**：舊制 STEP 04 是「Commit & Push」，review 在推送後才跑，修正只能另開 fix commit（2026-07-20 實際踩到）。改為 commit → review → push 三步分離後，review 修出的問題可直接 `--amend` 收進同一個 commit。同時新增兩條硬性規則：（1）**review 修正必須先落回本機 `~/.claude/` 再 rsync 到 repo**——只改 repo 端會被下次同步的本機舊版覆蓋掉，修正憑空消失；（2）**push 被 non-fast-forward 拒絕時先查成因再動作**，不反射性 force push（此 repo 曾因 `filter-repo` 清 secret 重寫歷史，只 force push 了一個 remote，另一個停在含明文 API key 的舊歷史達 4 天）
- **偵測回報完整性（v1.8.2 修正）**：`find_private_content()` 的 private-identifier 與 dash-encoded 偵測從 `.search()` 改為 `.finditer()`。`search` 每個字串只回報第一個命中——掃 JSON 時每個值是獨立節點故影響小，但 `check-private-content.py` 是把**整份檔案當單一字串**掃，一個檔案有 43 個私有識別符也只看得到 1 個，且清掉一個就遞補下一個、永遠見不到全貌（實測即為此：清掉 `CLAUDE.md` 的一個私有 repo 名後，才冒出同檔第二個識別符，其後還有兩個隱形）。修正後全 repo 去重命中從 91 筆增至 146 筆，新增 55 筆，全部為識別符級揭露（Jira 編號／私有 repo 名／內部域名），逐筆確認無 secret 或憑證後納入基線。注意此處的數字對本檔自身敏感——描述掃描結果的文字若直接寫出具體識別符，會讓下次掃描多出對應筆數，故一律以類別稱之。`test_mask_secrets.py` 新增 `COUNT_CASES` 測試組專測回報筆數——原有的 bool 案例抓不到這種缺陷（有命中就算過），已驗證改回 `search` 會令測試失敗
- **誤濾根治：過濾動作可見化（v1.8.1 修正）**：STEP 02 從只印「已過濾 N 條」改為**逐條印出被移除的 permission 內容**。誤濾（合法工具路徑被當私有內容刪除）與正常過濾在只印數量時完全無法區分，`~/Library` 的 Android SDK 兩條（commit df94390 手動補回）與 `~/.maestro` 的 maestro 兩條先後靜默消失，都是這樣漏掉的。同版把 `.maestro` 補進 `_ALLOWED_HOME_DIRS`
- **豁免判準維持具名 allowlist，不改規則判準（v1.8.1 決策記錄）**：本版曾試圖把 `_ALLOWED_HOME_DIRS` 換成「第一層是 dot-directory 一律豁免」以一勞永逸解掉誤濾，被 commit review 擋下並用程式碼實測證實是**偵測能力迴歸**：`~/.acme-internal-project`、`~/.secret-client-work` 這類未被 `_PRIVATE_ID_PATTERN` 收錄的私有路徑會被無條件放行（改動前攔截、改動後放行），denylist 是靜態硬編碼清單、對未收錄的新 repo 名同樣無效，等於兩層防線同時失守。這道防線守的是 **public repo**，失敗方向必須是「寧可誤濾也不漏放」——誤濾會被上一條的可見化當場抓到，漏放不會。`test_mask_secrets.py` 新增 3 條負向案例釘住此邊界，已驗證改回規則判準會令測試失敗
- **路徑 pattern 修正（v1.8.1）**：`_HOME_PATH_PATTERN` 的單層字元類抽為 `_PATH_SEGMENT` 具名常數（同時用於 `/Users/<user>` 段與被擷取的第一層目錄段，分開寫就是改一處漏一處），並排除反引號與逗號——說明文件寫 `` `~/Library` `` 時反引號會被吃進第一層目錄名（變成 ``Library` ``）而比對不到豁免清單，實測會令 `check-private-content.py` 誤報並擋下 commit
- **permissions 內容級過濾 + fail loud（v1.8.0 新增）**：`mask_secrets.py` 新增 `find_private_content()` 與 `strip_private_permissions()`。同步時移除 `permissions` 中含私有識別符（私有 repo 名／組織名／內部域名）或本機專案路徑（`~/Documents`、`~/Desktop`、`~/Downloads` 底下）的條目——這類多為一次性具體指令授權，還會夾帶 commit message（洩漏 Jira 編號與工作內容），在別台機器本來也無效。家目錄豁免判準見下方 v1.8.1 條目。過濾後再跑一次掃描，**仍有殘留即中止同步**。restore 端對稱加上 permissions 單向合併，避免從 repo 還原時撤銷本機授權。改動理由：v1.7.0 排除 `autoMode` 的宣稱理由是內容導向（私有 repo 名不該進 public repo），實作卻是 key 名導向，同類內容在 `permissions` 照樣進了公開 repo（實測 25 條命中）——是 per-incident patch 不是政策
- **本機專屬區段排除（v1.7.0 新增）**：`mask_secrets.py` 新增 `LOCAL_ONLY_KEYS`（目前為 `autoMode`）與 `strip_local_only()` / `--del-local`，`settings.json` 的 `autoMode` 區段**雙向排除**（同步不上傳、restore 不還原、本機原值保留）。原因：`autoMode.environment` 記錄公司內部 staging 域名、私有 repo 名稱（`<org>/<private-repo>` 形式）、本機絕對路徑、內部 npm registry，`autoMode.soft_deny` 記錄專案 deploy script 名稱——與 `CLAUDE.md` `<conn>` 同類的環境資訊，而**本 repo 為 public GitHub repo**。同版另修 `*.bak-*`（日期／版本後綴備份，如 `pr-reviewer.md.bak-20260813`）納入 diff/rsync 排除，原本只排除 `*.bak` 會讓這類備份進版控。新增本機專屬頂層欄位時一併加進 `LOCAL_ONLY_KEYS`
- **secret 遮罩與同步保護（v1.5.0 新增）**：三個結構性缺陷一次修掉 —（1）新增 `mask_secrets.py`，`settings.json` 複製與比對前遞迴遮罩 `permissions` 中的明文 secret（已知格式 `ctx7sk-`/`ghp_`/`glpat-`/`AKIA…`，以及 `--api-key`/`--token`/`--secret`/`--password` 後的值），修掉 repo 曾夾帶明文 context7 API key 的根因；（2）`rules/` 同步與還原都排除 repo 專屬 `README.md`，不再被 `--delete` 誤刪；（3）所有目錄 diff/rsync 排除 `*.bak` 臨時備份。正向同步與 restore 兩方向一致套用
- **harness 機器專屬檔排除（v1.4.0 新增）**：`harness/` 納入同步清單，但 `harness-diagnosis.md`（漏水診斷數據）與 `handover-letter.md`（交接信）為機器專屬檔案**雙向不同步**（rsync `--exclude`，同時保護 repo 側不被 `--delete` 清掉）——每台機器的診斷/交接不互相覆蓋；repo 現存兩檔為 M4 機器快照
- **model 欄位排除（v1.3.0 新增）**：`settings.json` 的 `model` 欄位為本機/repo 各自獨立設定，diff 比對用 `jq 'del(.model)'` 排除；正向複製與反向 restore 都改用 Python 合併寫入，保留目標端原本的 `model` 值，不被來源覆蓋。起因：本機依任務彈性切換 model（如 `opus[1m]` ↔ `sonnet`），不該被同步/還原動作洗掉。
- **source 標註機制（v1.2.0 新增）**：repo 根目錄 `skills-sources.json` 記錄外部 skill 出處（schema：`{"<skill>": {"source": URL, "installed": "YYYY-MM-DD", "note": ...}}`）。**由使用者手動維護，sync skill 永遠 read-only**（不寫入、不增刪、不修改）。3.4 一致性檢查只提示 sources.json 含已不存在 skill，不自動清理。
- **同步清單**：`settings.json`（排除 `model` 與 `autoMode`）、`mcp-servers.json`、`CLAUDE.md`（日期後綴 `CLAUDE.md.YYYYMMDD`，移除 `<conn>` 區段後儲存，自動清理舊備份）、`skills/`、`hooks/`、`scripts/`、`rules/`、`harness/`（排除機器專屬檔）、`statusline-command.sh`
- **MCP Server 同步**：支援 MCP Server 設定同步（過濾 env 敏感資料），新增 restore 反向同步模式（從 repo 還原到本機）
- **安全規則**：`CLAUDE.md` 的 `<conn>` 區段包含個人連線資訊（Jira cloud-id、username、專案路徑），同步時強制移除，禁止出現在 repo
- **依賴**：git、rsync、sed、jq、python3（`mask_secrets.py`）
- **注意**：`~/.claude/` 永遠是 source of truth，repo 只是備份與版本追蹤；`settings.local.json` 不同步；`model` 欄位、`autoMode` 區段、harness 機器專屬檔、`*.bak` / `*.bak-*` 與 `rules/README.md` 雙向排除

#### `/neat-freak` — 跨平台知識庫整理（潔癖級）

- **位置**：`~/.claude/skills/neat-freak/SKILL.md`（含 `references/agent-paths.md`、`references/sync-matrix.md`）
- **來源**：[KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills/)（neat-freak 子目錄，2026-04-30 安裝）
- **用法**：`/sync`、`/neat`、「整理一下」、「同步一下」、「整理文檔」、「更新記憶」、「收尾」、「這個階段做完了」
- **功能**：會話結束後三層知識同步（agent memory + 專案根 CLAUDE.md/AGENTS.md + docs/）對齊程式碼，避免文件腐爛
  1. 盤點現狀（強制機械式 ls + Read，不能跳過）
  2. 用「變更影響矩陣」識別波及哪些文件層級（跨項目影響檢查）
  3. 用 Edit/Write 實際修改（先 docs/ → 再 agent 文件 → 最後記憶）
  4. 自檢清單（含相對時間 `今天|最近|recently` 清零）
  5. 變更摘要（按項目分組列改動檔案）
- **跨平台**：Claude Code（`~/.claude/`）、Codex（`AGENTS.md`）、OpenCode（`.opencode/`）、OpenClaw（`~/.openclaw/`）
- **與既有 skills 區隔**：偏向 docs/ 三層整理（給下游、人類同事看）；weekly-review 偏個人記憶 hygiene；sync-my-claude-setting 是把 `.claude/` 推到 repo
- **依賴**：無外部依賴（純文件編輯）

#### `/spec-design` — 需求探索到設計 Spec + 實作計畫（v3.2.0）

- **位置**：`~/.claude/skills/spec-design/SKILL.md`
- **用法**：
  - `/spec-design` — 互動式需求探索
  - `/spec-design <需求描述>` — 帶初始需求直接開始
- **流程**：
  - Phase 0: openspec explore 自由探索問題空間（可跳過）
  - Phase 1-4: superpowers:brainstorming 結構化收斂
  - Phase 5: openspec CLI 建立 change，動態取 template 填入 artifact（proposal + specs + design + tasks）
  - Phase 6-7: 4-agent spec review + 迭代修正
  - Phase 8: plan mode 互動式規劃，產出 plan.md
  - Phase 9: 4-agent plan review + 迭代修正
  - Phase 10: 使用者最終確認
- **輸出**：`openspec/changes/<name>/`（含 proposal.md、specs/、design.md、tasks.md、plan.md）
- **依賴**：superpowers plugin（必要）、`@fission-ai/openspec` CLI（必要）
- **不適用於**：讀原始碼產 spec（用 spec-module）、重構既有程式碼、寫測試、bug fix

#### `/plan-and-execute` — 自動執行 openspec plan（v2.1.0）

- **位置**：`~/.claude/skills/plan-and-execute/SKILL.md`
- **用法**：
  - `/plan-and-execute <change-name>` — 指定 openspec change 自動執行
  - `/plan-and-execute` — 無參數時列出有 plan.md 的 change
  - `/plan-and-execute --resume <change-name>` — 從上次中斷處繼續
  - `/plan-and-execute --wave <N> <change-name>` — 只執行指定 Wave
  - `/loop 0 /plan-and-execute --resume <change-name>` — 全自動分批（推薦）
- **功能**：
  - 純自動 executor，讀取 plan.md 逐 Wave 執行 TDD
  - 先寫測試（RED）→ 派 subagent 實作（GREEN）→ review → commit
  - 同步更新 openspec tasks.md checkbox
  - context 不足時自動停止，用 `--resume` 跨 session 繼續
  - 最終調用 `test-module` 和 `spec-to-e2e-test` 做驗證
- **輸出**：完成的程式碼 + `openspec/changes/<name>/report.md`
- **依賴**：superpowers plugin（必要）、`@fission-ai/openspec` CLI（必要）、test-module skill、spec-to-e2e-test skill
- **不適用於**：簡單 bug fix 或單檔修改

---

### 程式碼品質類

#### `/spec-module <path>` — 模組 Spec 產生（v1.0.0）

- **位置**：`~/.claude/skills/spec-module/SKILL.md`
- **用法**：
  - `/spec-module <module-path>` — 快速模式，掃描結構產出概覽 spec
  - `/spec-module <path> --full` — 強制完整掃描，透過 `routes/index.js` 的 `CONTROLLER_ROUTING_MAPPING` 找出所有相關 controller，確保 API 列表 100% 完整
  - `/spec-module <path> --verify` — 驗證已存在 spec 的完整性，比對原始碼找出遺漏並補上
  - `/spec-module <path> --commit` — 完成後自動 commit（可與 `--full` / `--verify` 組合）
- **功能**：
  - 使用 Explore subagent 完整掃描模組
  - 產出結構化 spec：規模、入口架構、檔案一覽、品質觀察
  - 偵測 framework pattern、dead code
  - `--full`：讀取路由映射表，逐一掃描所有相關 controller 的 route 定義，附帶完整性驗證 section
  - `--verify`：三級優先序對應 spec 與原始碼（路由映射表 > Spec 內部標註 > 檔名推斷），找出遺漏 API 並補完，支援批次驗證整個目錄
- **輸出**：`spec/<module-name>/index.md` 或 `spec/<module-name>.md`

#### `/test-module <path>` — 批量測試產生（v2.0.0）

- **位置**：`~/.claude/skills/test-module/SKILL.md`
- **用法**：`/test-module <file-or-dir>`、`/test-module lib/services/session_service.dart`
- **功能**（5 階段）：
  - Phase 1：偵察與撰寫（偵測測試框架、分類函式、AAA pattern、Mock/斷言/邊界原則）
  - Phase 2：平行 Review（4 個 subagent — 覆蓋率 / Mock 正確性 / 斷言精確度 / 邊界案例）
  - Phase 3：迭代修正（🔴=0 且覆蓋率 ≥80% 才算通過）
  - Phase 4：執行驗證（失敗分類：測試寫錯→改測試、程式碼 bug→獨立 commit）
  - Phase 5：最終報告（`test/reports/<模組名>_report.md`）
- **框架無關**：Jest、Vitest、Mocha、flutter_test、pytest、go test 等
- **依賴**：依專案測試框架而定

#### `/spec-to-e2e-test <spec>` — Spec 轉 E2E 測試（v1.2.0）

- **位置**：`~/.claude/skills/spec-to-e2e-test/SKILL.md`
- **用法**：`/spec-to-e2e-test <spec路徑或模組名>`、`--with <其他spec>`、`--scan`
- **功能**（6 階段）：
  - Phase -1：跨模組依賴掃描（首次或批次作業時必做，產出 `DEPENDENCY_MAP.md`）
  - Phase 0：Spec 定位與偵察（讀取 spec、探索 UI 程式碼、產出 Widget/Element Finder 參考表）
  - Phase 1：撰寫測試（CRUD 合併流程、Finder 優先序、斷言強度、穩定性原則）
  - Phase 2：平行 Review（4 個 subagent — Spec 覆蓋率 / 語法正確性 / 測試品質 / 穩定性）
  - Phase 3：迭代修正（🔴=0 才算通過）
  - Phase 4：執行測試（失敗分類處理，spec 是 source of truth）
  - Phase 5：最終報告（`integration_test/reports/<模組名>_report.md`）
- **框架支援**：Flutter integration_test（完整）、React Testing Library / Playwright / Cypress（對照表）
- **依賴**：依專案 E2E 框架而定

#### `/explore-report <dir>` — 探索報告（v1.1.0）

- **位置**：`~/.claude/skills/explore-report/SKILL.md`
- **用法**：`/explore-report <directory>`、`--to-spec`
- **功能**：
  - 探索目錄結構並強制產出結構化報告
  - 報告含：規模、目錄結構、關鍵發現、架構模式、品質觀察
  - `--to-spec`：將探索報告轉換為正式 spec
- **輸出**：`spec/.exploration-log.md`（append 模式）

#### `/method-refactor <method>` — 方法重構（v1.0.0）

- **位置**：`~/.claude/skills/method-refactor/SKILL.md`
- **用法**：`/method-refactor <method-name or file:line>`
- **功能**：7 項順序檢查
  1. 常數掃描（抽取 magic number/string）
  2. 型別常數化（`as const`）
  3. 邏輯扁平化（early return、減少巢狀）
  4. Promise → async/await 轉換
  5. 重複碼提取
  6. 冗餘移除（含 NOTE 註解清理）
  7. 測試驗證（跑 test + lint + tsc）
- **輸出**：每項檢查的 ✅/⏭️/❌ 狀態表

#### `/health` — 設定健康度稽核（v1.5.0）

- **位置**：`~/.claude/skills/health/SKILL.md`
- **用法**：`/health`
- **功能**：六層架構健康度稽核
  - Step 0：評估專案 tier（Simple / Standard / Complex）
  - Step 1：單一 bash 區塊收集所有資料（CLAUDE.md、rules、skills、hooks、MCP、conversation files）
  - Step 2：啟動兩個平行診斷 subagent
    - Agent 1 — Context + Security Audit（context layer、skill security/quality/provenance）
    - Agent 2 — Control + Behavior Audit（hooks、allowedTools、cache hygiene、三層防禦一致性、行為 pattern）
  - Step 3：彙整報告（🔴 Critical / 🟡 Structural / 🟢 Incremental）
- **特性**：`disable-model-invocation: true`（不會被自動觸發，僅手動執行）
- **依賴**：無外部依賴

#### `/commit-review [target]` — Commit 後分級 review chain（v1.4.0）

- **位置**：`~/.claude/skills/commit-review/SKILL.md`
- **用法**：
  - 被動（hook 指派）：commit 後 `post-commit-review.ts` 已算好 Tier 與 engine，透過 systemMessage 下 `Skill(commit-review) args: "tier=N target=HEAD engine=<agent|codex>"`；**此模式 tier 與 engine 已知直接採用、不重算/不重探測**（判定單一來源）
  - 手動：`/commit-review`（對 HEAD，預設 `engine=codex`）、`/commit-review HEAD~3`、`/commit-review <hash>`、`/commit-review engine=agent`（強制走原 Claude agent 路徑，可與 target 併用）— 用於 marker 逾期補跑、想重跑、push 前主動 review、對舊 commit 補 review；手動模式自己跑 `bun ~/.claude/scripts/compute-tier.ts <target>` 算 tier
- **兩種 review 引擎（v1.4.0 新增）**：
  - `engine=agent`（原有路徑，降級與人工覆寫用）：Tier 2/3 面向由 Claude subagent（`Agent()`）逐一 spawn，結果經 task-notification 整份回流主 session；面向是否收齊靠 §3.1 fail loud 條款自律回報
  - `engine=codex`（**預設**）：面向由 `scripts/codex-review.ts` 平行發動 `codex exec` 子進程執行（六面向定義在 `scripts/lib/codex-aspects.ts`），輸出強制走 `scripts/schemas/codex-review-aspect.json` schema 落檔，主 session 只讀 runner 彙整的 CRITICAL/IMPORTANT；面向失敗用 exit code + 輸出檔非空 + schema shape guard 機械判定，不靠模型自律
  - 引擎由 `scripts/lib/review-engine.ts` 的 `resolveEngine()` 在 post-commit hook **上鎖當下**決定一次、寫入 marker 的 `engine` 欄位，Stop gate 之後只讀不重探測（同一輪 review 不換引擎）。決策順序：環境變數 `CLAUDE_COMMIT_REVIEW_ENGINE` 覆寫 → 實際執行 `codex --version` 探測（非只查 binary 是否存在，踩過 `which` 找得到但執行 ENOENT）→ 探測失敗降級 `agent` 並在 systemMessage 印出實際錯誤，不靜默改道
- **定位**：整套 pending-review 機制的**執行層**。分級判定由 hook 負責、強制力由 `commit-gate-guard.ts`（PreToolUse deny）提供，本 skill 只負責「跑對應 Tier 的步驟」
- **判準權威**：`~/.claude/harness/commit-review-policy.md`（分級判定表、免跑條件、Blast Radius 節、禁止事項）。skill 不重複判定表，只定義每個 Tier 的執行步驟——兩者職責切開，避免同一份步驟寫在 hook 字串／skill／policy 三處而分歧
- **Tier 對應 chain**：
  - Tier 0（純文件）→ 只發通知，不經 skill
  - **Tier 3 敏感路徑**（動到 `models/`、`lib/`、`shared/`、`routes/middlewares/`、`base{controller,bean,model}`）→ **不論改動大小，先於尺寸判定**
  - Tier 1（≤50 行且≤2 檔）→ eslint → 自查 judgment-matrix.md §2 DoD checklist → 通知，**不 spawn agent**
  - Tier 2（≤300 行且≤5 檔）→ eslint → `/simplify` → pr-reviewer agent（lite）→ **§3.1 確認結果回流** → 自動修 CRITICAL（amend）→ blast radius → 通知
  - Tier 3（超過 Tier 2 門檻）→ Tier 2 全部 ＋ **逐一明列的 5 個面向 agent**（`code-reviewer` / `silent-failure-hunter` / `comment-analyzer` / `pr-test-analyzer` / `type-design-analyzer`，同一則訊息平行發出、不帶 `name`）→ §3.1 收齊 → 修 Critical/Important
- **§3.1 fail loud（v1.1.0 新增，Tier 2/3 皆適用）**：收齊全部子 agent 結果前禁止宣告完成、禁止清 marker、禁止進入下一步。三種失敗態（agent 回報錯誤／回傳 `null`／結果沒回流）都不可當空結果放過；禁止自己重做該面向後照常輸出；降級須標在報告**最開頭**（`<未回傳數>/<應跑數>`，Tier 2 應跑 1、Tier 3 應跑 6），且**降級時不得清 marker**
- **為何不用 `/pr-review-toolkit:review-pr` 委派（v1.1.0 改動）**：該 command 有自己的 "Determine Applicable Reviews" 篩選（`commands/review-pr.md:36-43`），傳五個 aspect 參數不等於跑五個面向；且其 workflow 明定用於 commit **之前**，預設 scope 是 `git diff`（未 commit 變更），commit 後跑會是空的。實測 Tier 3 首次執行只 spawn 3 個 agent，SubagentStop debug log 五面向完成次數 15/14/13/11/10 亦不齊
- **marker 解鎖（v1.1.0 改動，v1.2.0 加上機械檢查）**：skill §5 是**唯一自動解鎖路徑**，前置條件為「面向結果收齊 + Critical 處理完」。SubagentStop hook 已停止清除職責（原本任一含 `review` 的 agent 完成就清，並行時第一個回來的即解鎖）
- **解鎖端機械閘門（v1.2.0 新增）**：marker 帶 `expectedAspects`（Tier 2 = 1、Tier 3 = 6，由 `post-commit-review.ts` 依 tier 機械填入），`clear-pending-review.ts` 要求 `--aspects-done=N` 且 `N >= expectedAspects`，不足則 exit 1 並印出缺口；降級時須 `--force "<理由>"` 且會在 `~/.claude/state/pending-review/unlock-audit.log` 標記 `FORCE=`。舊 marker 無此欄位時向後相容放行並提示。改動理由：此前 clear 腳本無條件 `unlink`，整套閘門是「上鎖機械、解鎖靠自覺」，而兩個閘門的攔阻訊息還直接把解鎖指令印給模型——等於在最想結束回合的時刻遞上鑰匙
- **依賴**：`scripts/compute-tier.ts`（手動模式算 tier）、`scripts/lib/tier.ts`（與 hook 共用的判定邏輯）、`scripts/lib/review-engine.ts`（引擎決策）、`scripts/codex-review.ts` + `scripts/lib/codex-aspects.ts` + `scripts/schemas/codex-review-aspect.json`（`engine=codex` 路徑）、`codex` CLI（需在 PATH 可執行）、pr-reviewer agent（lite，`engine=agent` 路徑用）、pr-review-toolkit 的 5 個面向 agent（`engine=agent` 路徑用）、codebase-memory-mcp（blast radius）

---

#### `/pr-reviewer <PR>` — PR full review（v2.0.0）

- **位置**：`~/.claude/skills/pr-reviewer/SKILL.md`；共用規範 `references/review-spec.md`
- **用法**：`/pr-reviewer 1134`、`/pr-reviewer <PR URL>`；亦可由 `~/.claude/scripts/review-pr.sh <PR>` 觸發
- **拓撲**：**主 session 直接 orchestrate**，不再包一層 pr-reviewer subagent（巢狀深度 2→1）。STEP 01/02/03/07 直接跑 Bash，STEP 04 在同一則訊息 spawn 5 個面向 agent，STEP 05 spawn 1-2 個 Haiku 批次評分 agent
- **5 個面向**：① CODE-REVIEW-RULE.md 逐條合規（17 條 + 慣例優先原則 + 新增檔案例外）② Shallow Bug Scan（只看 diff，聚焦邏輯錯誤／null／race／安全）③ Git Blame 歷史脈絡（`git log --follow -p`，找被移除的邏輯）④ 過去 PR 留言（`gh pr list --state merged --search`）⑤ 既有程式碼註解遵循（TODO/FIXME/HACK 指引）
- **兩條硬規則**：（1）所有 Agent call **不得帶 `name`**（帶了結果不回流，只能用 `description` 區分用途）（2）平行 = 多個 Agent call 放同一則訊息，發完該輪立即結束等 task-notification；**收齊全部結果前禁止產出報告**
- **fail loud**：有面向沒回來時，禁止自己重做後照常輸出，必須在報告**最開頭**標「Full 模式降級：N/5 個面向未回傳」
- **輸出**：terminal 結構化報告（品味評分 → Code Review Results → Quality Score 30 分 → 結論）＋ 自動 post 到 GitHub PR（summary review + inline Suggested Change；CRITICAL > 0 → `REQUEST_CHANGES`，否則 `COMMENT`，不自動 APPROVE）
- **v2.0.0 改動理由**：v1.x 把整套流程包在 subagent 內再 spawn 5 個子 agent，結果全押在 task-notification 跨兩層回流。三次實測三種結果（2026-08-07 PR 10953 全回流耗時 22 分鐘／08-06 PR 10949 繞道 team-lead 轉述／08-13 PR 10983 帶 `name` 全數落空後 parent 自行重做）。v1.3.0 要求一個不存在的參數（`run_in_background`）、v1.4.0 改成要求模型「該輪主動結束」，兩版都是拿 prompt 約定管非確定性的 harness 路由 → v2.0.0 改拓撲才解決
- **與 lite 的分工**：lite（`~/.claude/agents/pr-reviewer.md`）只審最近一次 commit、由 `commit-review` Tier 2/3 觸發、不產 inline comment 也不 post GitHub；full 審整個 PR diff。判定標準兩者共用 `references/review-spec.md`，不各自複製
- **實測價值（2026-08-17）**：PR 1134 在只有單一 commit 時跑 full review，比 commit 層的 Tier 3 chain 多抓出兩個 CRITICAL（`.then()` 缺 `.catch()` 造成連線洩漏／promise 永久 reject 需重啟 App），32 分鐘後由 `63bea9ec` 修掉。輸入相同而結果不同 → LLM 規則檢查是取樣不是判定，多視角交叉會抓到單 agent 漏掉的東西
- **依賴**：`gh` CLI（PR 查詢／diff／post review）、pr-review-toolkit 無關（本 skill 自帶 5 個面向定義）

---

### 文字品質類

#### `/humanizer-zh-tw` — 去除 AI 寫作痕跡

- **位置**：`~/.claude/skills/humanizer-zh-tw/SKILL.md`
- **用法**：`/humanizer-zh-tw`（提供需要人性化處理的文字）
- **功能**：
  - 辨識並修復 AI 生成文字的常見模式：誇大的象徵意義、宣傳性語言、以 -ing 結尾的膚淺分析、模糊的歸因、破折號過度使用、三段式法則、AI 詞彙、否定式排比、過多的連接性短語
  - 5 條核心原則：刪除填充短語、打破公式結構、變化節奏、信任讀者、刪除金句
  - 注入真實個性（有觀點、變化節奏、承認複雜性、適當使用第一人稱、允許混亂）
  - 品質評分系統（直接性/節奏/信任度/真實性/精煉度，滿分 50）
- **來源**：op7418/humanizer-zh 的分支，翻譯自 blader/humanizer，參考 hardikpandya/stop-slop
- **依賴**：無（純文字編輯）

#### `/ai-md` — CLAUDE.md AI-native 轉換（v4.0.0）

- **位置**：`~/.claude/skills/ai-md/SKILL.md`
- **用法**：`/ai-md`、「蒸餾」、「distill my CLAUDE.md」、「rewrite my MD for AI」
- **功能**：
  - 將 human-written CLAUDE.md 轉為 AI-native 結構化格式
  - 經 5 輪、4 模型（GPT-5.3、Gemini 2.5 Pro、Grok-4、Claude Opus 4.6）實戰測試
  - Structured-label 格式使 Codex compliance 從 6/8 提升至 8/8
  - 同樣規則、更少 token、更高精確度
- **依賴**：無

---

#### claude-max-quota — 多帳號額度管理

- **位置**：`~/.claude/skills/claude-max-quota/SKILL.md`
- **用法**：`/claude-max-quota`、`cq`、「額度」、「quota」、「換帳號」、「切帳號」
- **功能**：
  - 查詢所有 Claude Max 帳號的週額度與 5h 額度使用率
  - 自動推薦使用率最低的帳號
  - 提供多帳號設定流程指引（CLAUDE_CONFIG_DIR + zshrc alias + statusline）
- **依賴**：`scripts/check-quota.sh`、macOS Keychain 中的 Claude Code credentials

#### save-progress — 手動存檔工作進度

- **位置**：`~/.claude/skills/save-progress/SKILL.md`
- **用法**：`/save-progress`
- **功能**：
  - 有 TaskList 時：dump 完整任務狀態（status、描述、blockers）到 `tasks/todo.md`
  - 無 TaskList 時：回顧 session 對話，產出工作摘要 + 未完成事項到 `tasks/todo.md`
  - 檢查並保存未存的 auto memory（feedback/project/reference）
- **適用時機**：session 結束前、預感 rate limit、長時間離開前
- **錯誤追蹤**：失敗時記錄到 `~/.claude/.learnings/ERRORS.jsonl`

#### `/r15-r18-verify` — R15→R18 遷移驗證（v1.4.0）

- **位置**：`~/.claude/skills/r15-r18-verify/SKILL.md`
- **用法**：`/r15-r18-verify`、「驗證 r18」、「比對 r15 r18」、「遷移驗證」
- **功能**：
  - R15 到 R18 頁面遷移的功能等價性驗證
  - 逐層比對 Redux、元件行為、錯誤處理等
  - 產出結構化報告並修復發現的 bug
- **依賴**：git repository

#### `/cup-build-test` — CUP 項目測試建立（v1.3.0）

- **位置**：`~/.claude/skills/cup-build-test/SKILL.md`（含 `templates/spec-template.md`、`templates/test-cjs-template.cjs`）
- **用法**：`/cup-build-test`、「建立 CUP 測試」、「從 commit 反推測試」、「CUP 驗證腳本」
- **功能**（6 階段）：
  - **階段 0**：開場提醒 codebase-memory-mcp 可選增強（`--with-graph` 旗標，auto-sync 不需 staleness 檢查；`trace_path` 對 callback 參照傳遞/dispatch 間接呼叫有已知盲區）
  - **階段 1**：從當前 branch 抓 `CUP-\d+` → `git diff main...HEAD` → 平行 3 subagent 反推 API/UI/Redux → 產 `coverage.json`
  - **階段 2**：依 coverage 產出雙用途測試計劃 `.claude/CUP-XX-test-plan.md`（人 + Playwright 共讀），完成後刪除 coverage.json
  - **階段 3**：產 Playwright 腳本 `.claude/CUP-XX-test.cjs`，`node --check` 語法驗證
  - **階段 4**：正式環境半自動驗證 — dry-run 列計畫 → 三選一執行模式（一次跑 / 分輪跑 / 自訂 ONLY）→ `npx --yes -p playwright@latest node` 跑 R15 baseline
  - **階段 5**：根據 fail 結果分類修正 test-plan（測試項目錯 / selector 錯 / R15 bug），不自動 commit
  - **階段 6**：重產 cjs 腳本給 local/staging/R18 用；步驟 12 可選 publish 到業務 repo `e2e/release-tests/`
- **產物管理**：所有 `.claude/CUP-*-test-plan.md` / `-test.cjs` / `-temp/` / `-coverage.json` 進 `.gitignore`，不入 repo
- **不依賴 package.json**：執行時 `npx --yes -p playwright@latest node ...` 動態取得 Playwright，不污染專案依賴
- **v1.3.0（2026-07-01）**：GitNexus 淘汰改用 codebase-memory-mcp——`--with-gitnexus` 更名 `--with-graph`，`mcp__gitnexus__*` 呼叫全部換成 `mcp__codebase-memory-mcp__*`（`list_repos`→`list_projects`、`query`→`search_graph`、`context`/`impact`→`trace_path`、`cypher`→`query_graph`），移除 staleness 檢查，新增 callback/dispatch 間接呼叫盲區警告
- **v1.2.0 新增**：「斷言截圖三合一規範」— 每個 step 須同時具備 (1) 程式斷言 throw + 實測 vs 預期 (2) 真實頁面操作或視覺變更 (3) evidence overlay 注入結論；純資料比對 step 視為 anti-pattern，必須補 UI 證據（`select.size=N` 展開 / 逐一 selectOption / DOM highlight 三選一）；新增 `helpers/evidence.cjs`（封裝 `injectEvidence` / `clearEvidence` / `expandSelectAsListbox`）
- **v1.1.0 起**：登入流程改用 API（`.env.local` + `helpers/login.cjs`），移除互動式 MCP 登入；`browser.cjs` 支援 `{ login }` 主流程（v1.2.0 改為 `loginInContext` 保留 host-only cookies）
- **與既有 skill 區隔**：`/jira-test-report` 對既有 test-plan 跑測試並上 Jira；本 skill 是**從零產 test-plan + 自我驗證**；`/r15-r18-verify` 是程式碼層比對，本 skill 是行為驗證，互補
- **依賴**：git repository、cwd 在 luna_web/frontend（或結構相同 R15→R18 repo）、`.env.local` 含登入帳密

#### `/token-analyze` — Session Token 使用量分析（v1.0.0）

- **位置**：`~/.claude/skills/token-analyze/SKILL.md`
- **用法**：`/token-analyze [filename] [uuid]`、「分析 token」、「這個 session 花了多少」、「token 報表」
- **功能**：
  - 從 transcript JSONL 重建每個 assistant turn 的 token usage、工具呼叫、檔案存取
  - 自動歸納 session 工作摘要（用 cc 跳幅、工具序列、檔案主題切段，3-8 段）
  - 產出純 markdown 報表：Summary（含 Opus 4.x 成本）、Top 5 燒錢 turn、Per-turn 明細
  - 支援自訂檔名與跨 session 分析（指定 uuid）
- **bundled scripts**：`scripts/build-report.sh`（jq + awk 拼表，留 `__SUMMARY_PLACEHOLDER__` 給 Claude 填）
- **evals**：`evals/evals.json` 5 案例（slash 觸發、自然語、自訂檔名、負面、跨 session）
- **依賴**：jq、awk、本機 transcript JSONL（`~/.claude/projects/<escaped-cwd>/<uuid>.jsonl`）

#### `/translate-claude-code-releases` — Claude Code Release 翻譯（v1.0.0）

- **位置**：`~/.claude/skills/translate-claude-code-releases/SKILL.md`
- **用法**：`/translate-claude-code-releases [version]`、「翻譯 release」、「claude code 更新了什麼」、「翻譯 changelog」
- **功能**：
  - 帶版本號 → 翻該版起到最新；不帶 → 從 `last-version.txt` 記錄的版本之後續翻到最新
  - `fetch-range.sh` 用 `gh` API 抓 release notes 範圍（回傳 FROM/TO/COUNT/MODE/RAW 元資料），寫入 `raw.md`
  - dispatch sonnet subagent 翻譯：技術術語/產品名保留原文，用詞自然精準
  - 產出 `output/releases-zh-<from>-to-<to>.md`，更新 `last-version.txt`
- **bundled scripts**：`fetch-range.sh`（抓取 + 範圍計算，三種模式：指定版本 / 續翻 / 單版）
- **runtime 產物**（不進 repo）：`raw.md`、`last-version.txt`、`output/*.md`
- **依賴**：`gh` CLI（GitHub releases API）、sonnet subagent

#### `/ai-case-report` — AI 效益案例填報輔助（2026-07-25 新增）

- **位置**：`~/.claude/skills/ai-case-report/SKILL.md`
- **用法**：`/ai-case-report`；觸發語句：「要填 AI 案例」、「我有個 AI 工具用得很好」、「幫我整理 AI 效益」、「填報 AI 效益案例」
- **功能**：
  - 透過對話式訪談逐步收集填報表必要資訊，產出符合格式要求、具備量化數字的完整案例文件
  - Outline MCP 已連線 → 直接呼叫 `outline:create_document` 發佈至對應團隊的子文件集（6 個團隊節點：JEM 1 - Core/LTC/iCare、JEM 2 - Go、JEM 3 - DTC、JEM 4 - AI）
  - Outline MCP 未連線 → 產出 `.md` 檔案，並告知使用者手動上傳路徑
  - 內嵌填報表模板與空白模板/業界範例集 Outline 文件 ID，不依賴 Outline 連線即可套用結構
- **依賴**：Outline MCP（選用，未連線時降級為純檔案產出）

#### `/upgrade-to-status` — 專案升級為 status.md 架構（v1.1.0）

- **位置**：`~/.claude/skills/upgrade-to-status/SKILL.md`
- **用法**：`/upgrade-to-status`；觸發語句：「升級到 status.md」、「建立 status.md」、「這個專案弄 status」
- **功能**：
  - 在 `tasks/status.md` 建立共識文件，固定 6 個區段：Milestone / 北極星 / Insight / Current / Next / Frozen
  - 從既有 `tasks/todo.md`、`tasks/lessons.md`、README、git log 推斷初值，交使用者確認後才寫入
  - 推斷不到的欄位寫「待填」不亂湊；北極星指標一律由使用者自訂，不由 AI 代擬
  - `status.md` 已存在時只做檢查，不覆蓋
- **適用**：side project（自有 repo、無 Jira 或同類追蹤系統）
- **不適用**：公司專案（已有 Jira + `tasks/todo.md` 流程）、純設定檔/dotfile repo
- **依賴**：git repository

---

## Hooks

### SessionStart

| 腳本 | 用途 |
|------|------|
| `detect-jira-issue.sh` | 從 git branch 名稱偵測 Jira issue 編號，注入 session context |

### UserPromptSubmit

| 腳本 | 用途 |
|------|------|
| `skill-activation-hook.ts` | 分析使用者輸入，檢查是否觸發特定 skill |

### PreToolUse

| Matcher | 腳本 | 用途 |
|---------|------|------|
| `Write\|Edit\|MultiEdit` | `r15-syntax-guard.ts` | 擋下 luna_web `react_15/` 內 `?.` 與 `??`（babel 6 不支援 ES2020 語法），違規回傳 deny + 範例 |
| `Read` | `big-read-guard.sh` | 大檔（行數 ≥ 門檻）整檔 Read（無 offset/limit）時 deny 一次，提示先用 `smart_outline`；同檔每 session 只擋一次（再次送出即放行，等於減速丘）；fail-open 失敗不阻斷 |
| `Bash` | `commit-gate-guard.ts` | pending-review 閘門——該 repo 有 Tier 2/3 commit 的 review 尚未完成（`~/.claude/state/pending-review/<repo>.json` marker 存在）時，deny 開新 `git commit`；放行 `--amend`/`push`/commit message 含 `[skip-review]`；marker 逾 4 小時自動清除放行，避免永久 brick；失敗一律 fail-open |

### PostToolUse

| Matcher | 腳本 | 用途 |
|---------|------|------|
| `Write\|Edit` | `spec-section-validator.ts` | 驗證寫入的 spec 文件區段格式是否正確 |
| `Write\|Edit` | `inventory-drift-detector.ts` | 偵測 inventory 索引是否需要更新 |
| `Write\|Edit` | `skill-version-check.ts` | SKILL.md 被編輯時，若 version 未更新則提醒進版號 |
| `Bash` | `post-commit-review.ts` | git commit 成功後用 `git diff --numstat` 機械判定 Tier（0~3，邏輯在 `scripts/lib/tier.ts`），Tier ≥1 另以 `lib/review-engine.ts` 的 `resolveEngine()` 探測本輪 review 引擎（`codex`/`agent`，決策見下方 `commit-review` 章節），Tier 2/3 寫入 pending-review marker 含 `sessionId`/`engine`（供 `commit-gate-guard.ts` / `stop-review-guard.ts` 閘門讀取），並以 systemMessage 指派 `commit-review` skill 執行 `tier=N target=HEAD engine=<agent\|codex>` 的 chain（步驟明細在 skill，hook 不列舉） |
| —（catch-all） | `post_tool_error.py` | 所有 tool 失敗時自動記錄 JSONL 到 `~/.claude/.learnings/ERRORS.jsonl` |

> **HOOK-OUTPUT 限制**：PostToolUse 的 stdout 不注入 AI context，Claude 看不到。`systemMessage` JSON 僅顯示給使用者。需靠 CLAUDE.md 規則驅動 Claude 行為 + hook systemMessage 作為使用者端安全網。

> **hook-error-wrapper**：所有 hook（除 `post_tool_error.py` 和 Notification）皆透過 `hook-error-wrapper.sh` 包裝執行，失敗時自動記錄到 `ERRORS.jsonl`。

### PreCompact

| 腳本 | 用途 |
|------|------|
| `pre-compact-snapshot.ts` | Context 壓縮前提醒存重要決策/糾正到 auto memory + dump TaskList 到 tasks/todo.md |

### Stop

| Matcher | 腳本 | 用途 |
|---------|------|------|
| —（所有回合結束） | `stop-review-guard.ts` | pending-review 閘門的「回合結束」守門員——marker 未清時 block 回合結束，reason 以指令級注入（user role）指派 `commit-review` skill，補上「commit 後只打字回覆、systemMessage 被無視」的生命週期缺口。比對雙鍵：`marker.sessionId` 優先（本 session 欠的 review，不 spawn git）、cwd repoRoot 補位（跨 session 接手）。指派字串的 engine 直接讀 `marker.engine`（只讀不重探測，同一輪 review 不換引擎；舊 marker 無此欄位時以 `LEGACY_MARKER_ENGINE` 推導）。防 brick：per-session 有界計數（同 session 最多攔 3 次，達上限放行印警告）、plan mode 放行、逾期 marker 自動清除、計數寫回失敗放行；失敗一律 fail-open |

### SubagentStop

| Matcher | 腳本 | 用途 |
|---------|------|------|
| — | `subagent-review-clear.ts` | **只記錄 `agent_type` 到 `state/pending-review/subagent-stop-debug.log`，不清除 marker**（2026-08-17 移除清除職責）。舊行為「型別含 `review` 就清」的判定依據與待判定事實（review chain 是否跑完）不對應：Tier 3 並行 6 個 agent 時第一個完成的即解除閘門，full review 的面向 agent（`pr-1134-full-review`、`agent1-rules` 等）也誤命中。marker 改由 `commit-review` skill §5 顯式清除；debug log 保留作為 chain 完整度稽核與 `agent_type` 實際值的唯一實測來源（2026-08-17 統計 2724 筆：2118 筆型別為空、`pr-reviewer` 62 筆、五個 `pr-review-toolkit:*` 面向 15/14/13/11/10） |

### Notification

| Matcher | 腳本 | 用途 |
|---------|------|------|
| `*` | (inline printf) | 終端機通知 |

---

## Scripts（輔助工具）

| 腳本 | 用途 |
|------|------|
| `hook-error-wrapper.sh` | 包裝 hook 命令，失敗時記錄到 `ERRORS.jsonl`（所有 hook 的外層 wrapper） |
| `detect-jira-issue.sh` | 從 git branch 解析 Jira issue key |
| `generate-spec-mapping.ts` | 產生 `spec/file-mapping.json`（源碼↔spec 對照表） |
| `spec-section-validator.ts` | 驗證 spec 必要區段是否存在 |
| `inventory-drift-detector.ts` | 偵測 `memory/inventory.md` 與實際 skill/hook 的差異 |
| `skill-activation-hook.ts` | 分析輸入文字判斷是否要啟動 skill |
| `skill-version-check.ts` | PostToolUse hook — SKILL.md 被編輯時偵測 version 是否更新，未更新則提醒 |
| `lib/review-marker.ts` | pending-review marker 共用 lib — marker 路徑推導、`git -C`/`cd` 跨 repo 目標解析、`isGitCommitCommand` 指令偵測；被 `post-commit-review.ts`、`commit-gate-guard.ts`、`stop-review-guard.ts`、`subagent-review-clear.ts`、`clear-pending-review.ts` 共用；marker 另含 `sessionId`（Stop gate 第一比對鍵）、`stopBlockCounts`（per-session block 計數）與 `engine?`（本輪 review 引擎，選填以相容舊 marker）欄位 |
| `lib/tier.ts` | Tier 判定共用 lib — Tier 0 副檔名清單、日期後綴剝除 regex、Tier 1/2 行數與檔數門檻、敏感路徑 regex（`models`/`lib`/`shared`/`routes/middlewares`/`base(controller\|bean\|model)`）；主函式 `getTierStats(repoRoot, ref)` 回傳完整統計，`computeTier` 為只取 tier 數字的薄封裝。被 `post-commit-review.ts`（被動）與 `compute-tier.ts`（手動）共用，確保兩條路徑判定不分歧。查詢用 `git diff --numstat --no-renames`（不加 `--no-renames` 會漏判「搬檔進 `lib/`」這類高風險 rename） |
| `lib/review-engine.ts` | review 引擎決策共用 lib（v1.4.0 新增）— `resolveEngine()`：環境變數 `CLAUDE_COMMIT_REVIEW_ENGINE` 覆寫 → 實際執行 `codex --version` 探測（非只查 binary 存在）→ 失敗降級 `agent`；`buildSkillInvocation(tier, commitHash, engine)` 集中組出 `Skill(commit-review) args: "..."` 字串，取代原本分散在 `post-commit-review.ts`/`stop-review-guard.ts` 兩處各自組字串會分歧的寫法；`LEGACY_MARKER_ENGINE` 供舊 marker（無 `engine` 欄位）向後相容推導 |
| `lib/codex-aspects.ts` | codex review 六面向定義（v1.4.0 新增）— 對應原 Tier 3 的 5 個 subagent 面向 + Tier 2 的 lite 面向，每項含 prompt 與輸出對應的 schema key，供 `codex-review.ts` 逐一組 `codex exec` 呼叫 |
| `codex-review.ts` | codex review 平行 runner（v1.4.0 新增）— 依 `lib/codex-aspects.ts` 平行發動多個 `codex exec` 子進程，輸出強制驗證 `schemas/codex-review-aspect.json` schema 後落檔；exit code 非 0 或輸出檔缺漏/不合 schema 一律視為該面向失敗（機械判定，不靠模型自報） |
| `compute-tier.ts` | CLI 包裝 — `bun compute-tier.ts [target]`，輸出 `TIER=N` 與 `FILES=… LINES=… SENSITIVE=… COMMIT=…` 兩行，供 `commit-review` skill 手動模式取得 tier；ref 無效時印錯誤並 exit 1（skill 見非 0 exit 即停止，不得採用 TIER 值） |
| `post-commit-review.ts` | PostToolUse hook — git commit 後呼叫 `lib/tier.ts` 判定 Tier（0~3），Tier ≥1 另呼叫 `lib/review-engine.ts` 的 `resolveEngine()` 決定本輪 review 引擎，Tier 2/3 寫入 pending-review marker（含 `sessionId`/`engine`）供 `commit-gate-guard.ts` 阻擋下一個 commit、`stop-review-guard.ts` 阻擋回合結束，並以 systemMessage 指派 `commit-review` skill 跑對應 chain |
| `clear-pending-review.ts` | 手動清除 pending-review marker，解鎖該 repo 的 commit 閘門（Tier 2/3 review 完成、Critical 問題處理完後執行） |
| `pre-compact-snapshot.ts` | PreCompact hook — 壓縮前提醒存記憶 + dump TaskList 到 tasks/todo.md |
| `summarize_errors.py` | 讀取 `~/.claude/.learnings/ERRORS.jsonl`，按 skill/tool/pattern 分組統計錯誤，支援 `--days N`、`--min-count N` |
| `pr-watcher.sh` | 定期輪詢 GitHub PR，有新/更新的 PR 時發 macOS 通知，點擊觸發 review |
| `review-pr.sh` | 本機手動觸發 PR review，結果貼到 PR comment |
| `sync-obsidian-vault.sh` | 同步 auto memory 目錄到 Obsidian vault（symlink） |
| `add-obsidian-tags.ts` | 為 auto memory markdown 檔案補上 Obsidian tags |
| `check-quota.sh` | 多帳號額度查詢（Bash + Python），從 Keychain 讀 OAuth token 呼叫 Anthropic API，輸出彩色進度條與推薦帳號 |

---

## Agents

| Agent | 模型 | 版本 | 用途 |
|-------|------|------|------|
| pr-reviewer | sonnet | 2.0.0 | Code review agent — 逐條比對 CODE-REVIEW-RULE.md 並產出結構化報告；v1.3.0 新增「新增檔案例外」；v1.2.0 新增慣例優先原則 + full 模式自動 post GitHub PR review |
| multi-repo-commit-scanner | haiku | 1.1.0 | 多 repo 平行 commit 掃描器 — 內部用 Bash 背景作業同時掃 N 個 repo 的 git log，輸出每 repo commits、Jira IDs、統計；v1.1.0 支援 pathspec 物件形式拆 monorepo 子目錄 |

### pr-reviewer — Code Review Agent（v2.0.0，lite 模式專用）

- **位置**：`~/.claude/agents/pr-reviewer.md`
- **模型**：sonnet
- **工具**：Read、Grep、Glob、Bash、Agent
- **模式**：
  - **Lite（預設）**：單 agent 逐條比對 CODE-REVIEW-RULE.md（17 條規則）+ Haiku 信心評分 → 分類（CRITICAL/MINOR/INFO）+ 品質評分（30 分制）
  - ~~**Full**：指定 PR 時啟用，5 個平行 Sonnet agent~~ **已於 v2.0.0 移出本 agent** → `/pr-reviewer <PR>` skill（主 session orchestrate）。本 agent 收到 full 請求會直接導向該 skill，不自行執行
- **舊 Full 說明（僅供對照）**：5 個平行 Sonnet agent（規則合規 / Shallow Bug Scan / Git Blame 歷史 / PR Comments / Code Comments）+ Haiku 信心評分；**v1.2.0 起自動 post review 到 GitHub PR**（review event 依 CRITICAL 數量決定 REQUEST_CHANGES/COMMENT，不自動 APPROVE；inline comment 走 `gh api repos/.../pulls/<n>/reviews`，無權限或行號超出 hunk 時保留 terminal 輸出並印錯誤），terminal 結構化輸出仍保留供 debug
- **v1.3.0 新增「新增檔案例外」**：規則 9（變數/常數/React hook 變數/interface 成員註解）、規則 10（函式 JSDoc）、規則 11（STEP 格式註解）若命中本次 diff 中**全新建立的檔案**（`git diff` 標示 `new file mode`），跳過慣例檢查流程、直接依 CODE-REVIEW-RULE.md 字面判定，違反即記錄且不得因舊 codebase 採用率低而降評。起因：實測 `luna_web/frontend/react_18/src` 全庫 STEP 註解採用率僅 4.6%（48/1046 檔），慣例比對會把「大多數舊檔沒寫」誤判為主流，導致新規則對任何新檔案都罰不到（ERPD-11971 2026-07-15 首次 commit 即是實例）。規則 4（Magic Number）、Reducer/State 操作風格、規則 12 的 JSDoc 完整度面向**不在例外範圍**，新舊檔案一律照原慣例檢查流程
- **v1.2.0 新增「慣例優先原則」**：風格類規則（Magic Number / 變數常數註解 / 函式註解 / STEP 格式註解 / 部分註解正確性 / Reducer 慣例）標 issue 前，須先 `grep` 統計既有寫法（抽樣 3-5 檔），主流慣例（>50%）一致 → 不標；30-50% 並存 → 可放 INFO；<30% → 可標 MINOR；範本檔強訊號（新增 code 明顯複製既有檔）也視為主流慣例代表。安全性（hardcoded secrets、log 敏感資料）、null safety crash 風險、if 大括號、不可變性、全域變數修改、React/RN 規則等非風格類規則不適用此豁免
- **觸發方式**：`commit-review` skill 的 Tier 2/3 chain 自動呼叫（lite）或手動指定 PR（full）
- **檔案過濾**：排除 `*.md`、`*.json`、`*.yml`、`*.yaml`
- **依賴**：CODE-REVIEW-RULE.md（repo 根目錄或 `~/.claude/`）、gh CLI（full 模式）
- **說明文件**：`agents/README-pr-reviewer.md`（設計文件，非 agent；~~v1.2.0 起說明「不需外部 `review-pr.sh`」~~（已過時：`review-pr.sh` 仍在維護，提供 watchdog 逾時、進度心跳與 headless 觸發，見 `scripts/review-pr.sh`））

### multi-repo-commit-scanner — 多 Repo Commit 掃描器（v1.1.0）

- **位置**：`~/.claude/agents/multi-repo-commit-scanner.md`
- **模型**：haiku（輕量任務，Bash + jq 為主）
- **工具**：Bash、Read
- **輸入**：
  - `repos`（必填）：git repo 清單，每筆可為
    - 純路徑字串 → `name` = basename，掃整個 repo
    - 物件 `{path, label, pathspec}` → `label` 自訂顯示名、`pathspec` 限定子目錄（monorepo 拆 bucket 用）
  - `days`（必填）：往回掃幾天
  - `author`（選填）：commit 作者，預設每 repo 用 `git config user.name`
  - `parallel`（選填）：並行度，預設 8
- **輸出**：JSON 結構 — `repos[]`（每 repo/bucket 的 commits、jira_ids、by_type、total）+ `summary`（total_repos / total_commits / all_jira_ids / by_type_aggregate）
- **平行機制**：Bash `&` 背景 job + `wait -n` 控並發；單一 Bash call 內完成 N repo 掃描與 jq 聚合
- **pathspec 拆分（v1.1.0）**：物件帶 `pathspec` 時 `git log` append `-- <pathspec>`，把同一 git repo 依子目錄拆成多個 bucket（如 luna_web 的 `frontend/` 與 `backend/`）；橫跨多子目錄的 full-stack commit 同時計入各 bucket（不去重）
- **規則固化**：`--all` 必開（feature branch commit 不漏）/ `--no-merges` / Jira ID regex `\[([A-Z]+-[0-9]+)\]` / type 解析 conventional commit
- **故障隔離**：任一 repo 失敗寫 `error` 欄位、不中斷其他 repo
- **觸發方式**：weekly-review STEP 01 自動呼叫（取代過去主 agent 逐 repo 序列跑 `git log`）
- **不在範圍**：不解析 commit body / 不對 Jira API 查詢（那是 weekly-review STEP 01.5 做）/ 不寫週報（只回 JSON，主 agent 自己組裝）

---

## Plugins & MCP Servers

> 完整說明見 [`plugins/README.md`](plugins/README.md)

### 啟用的 Plugins（8）

| Plugin | 來源 | 用途 |
|--------|------|------|
| atlassian | claude-plugins-official | Jira & Confluence 整合 |
| frontend-design | claude-plugins-official | 前端設計輔助 |
| typescript-lsp | claude-plugins-official | TypeScript/JS Language Server |
| context7 | claude-plugins-official | 即時查詢函式庫最新文件 |
| claude-mem | thedotmack | 跨 session 持久記憶系統 |
| pr-review-toolkit | claude-plugins-official | PR Code Review 工具套件（/pr-review-toolkit:review-pr） |
| playwright | claude-plugins-official | 瀏覽器自動化（取代 agent-browser skill） |
| mcp-outline | mcp-outline | Outline 文件搜尋/讀取/建立/管理（2026-07-25 新增） |

### 停用的 Plugins（10）

| Plugin | 來源 | 理由 |
|--------|------|------|
| github | claude-plugins-official | 用 gh CLI 替代 |
| everything-claude-code | everything-claude-code | hooks 開銷大，有用功能已被其他工具覆蓋 |
| document-skills | anthropic-agent-skills | 文件處理套件，目前用不到 |
| superpowers | claude-plugins-official | 已分別啟用個別功能，不需整套 |
| code-simplifier | claude-plugins-official | 2026-07-25 停用；post-commit review 流程實際依賴 pr-review-toolkit 的 code-simplifier agent，與此獨立 plugin 無關；內建 `/code-review` 已取代其功能 |
| code-review | claude-plugins-official | 2026-07-25 停用；同上，內建 `/code-review`／`/review` 指令與 pr-review-toolkit 已取代 |
| claude-hud | claude-hud | 2026-07-25 停用；原用途僅為 statusline 概念參考，概念已被本機 `statusline-command.sh` 採納，不需持續啟用 plugin 本體 |
| claude-md-management | claude-plugins-official | 2026-07-25 停用；批次精簡插件清單（詳見 README.md 變更紀錄） |
| gopls-lsp | claude-plugins-official | 2026-07-25 停用；批次精簡插件清單（詳見 README.md 變更紀錄） |
| jdtls-lsp | claude-plugins-official | 2026-07-25 停用；批次精簡插件清單（詳見 README.md 變更紀錄） |

### MCP Servers

> 設定檔：[`mcp-servers.json`](mcp-servers.json)

#### 獨立設定的 MCP Servers（2 個）

| Server | 類型 | 用途 |
|--------|------|------|
| pr-watcher | stdio | PR 監控 MCP Server（`npx tsx pr-watcher-MCP/src/server.ts`） |
| codebase-memory-mcp | stdio | 程式碼知識圖譜／語意搜尋 MCP Server（取代 GitNexus）；`index_repository`/`search_graph`/`search_code`/`trace_path`/`query_graph`/`get_architecture` 等工具 |

> **已移除的 MCP Servers（2026-03-27）：**
> 以下 server 從 `mcp-servers.json` 移除，但本機仍有對應工具：
>
> | Server | 移除原因 | 本機現況 |
> |--------|---------|---------|
> | context7 | 改走 plugin 通道（`context7@claude-plugins-official`） | plugin 啟用中，不需獨立 MCP 設定 |
> | gitlab | 不再使用 | — |
>
> 其他電腦同步時無需重新加入這些 MCP Server。

#### Plugins 自動註冊的 MCP Servers

| Server | 來源 Plugin | 用途 |
|--------|------------|------|
| context7 | context7@claude-plugins-official | 取得最新函式庫文件與範例程式碼 |
| mcp-search | claude-mem@thedotmack | 持久記憶語意搜尋 |
| atlassian | atlassian@claude-plugins-official | Jira/Confluence CRUD |
| typescript-lsp | typescript-lsp@claude-plugins-official | TS/JS 型別檢查與導航 |
| mcp-outline | mcp-outline@mcp-outline | Outline 文件搜尋/讀取/建立/管理（2026-07-25 新增） |

---

## StatusLine 自訂狀態列

- **位置**：`~/.claude/statusline-command.sh`
- **來源**：合併自 [sd0xdev/sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow)（佈局）+ [@kamranahmedse/claude-statusline](https://github.com/kamranahmedse/claude-statusline)（rate limits）+ [jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud)（概念參考：transcript 解析）
- **設定**：`~/.claude/settings.json` → `statusLine.command`
- **顯示**：
  - 第一行：目錄 (branch*) │ Model │ ctx:N% │ ⏱ session │ thinking
  - 第二行：session name │ 工具統計（前 5 名×次數）│ agent 數量 │ todo 進度 │ config counts
  - 第三～五行：current / weekly / extra usage 進度條（需 OAuth）
- **快取**：rate limit 60 秒、transcript 3 秒、config 120 秒
- **詳細說明**：[`statusline/README.md`](statusline/README.md)

---

## 持續學習系統

> Homunculus 觀察系統已於 2026-03-13 移除（運行 10 天，0 產出）。
> 改用以下機制：

- **LEARNING 規則**（CLAUDE.md）：被糾正時存 feedback memory、發現偏好時存 user memory
- **PreCompact hook**：context 壓縮前提醒存重要決策
- **`/weekly-review` skill**：每週整理記憶、清理過期資訊、提取模式
- **Obsidian 整合**：symlink vault 瀏覽所有專案的 auto memory

---

## Rules（編碼規則）

> 規則分為 **common**（語言無關）與 **語言特定**（目前有 TypeScript）兩層。語言特定規則繼承 common 並補充框架細節。

### common/

| 規則檔 | 重點規則 |
|--------|---------|
| `coding-style.md` | IMMUTABILITY、FILE-ORG、ERROR-HANDLING、INPUT-VALIDATION、MAGIC-NUMBER、NULL-SAFETY、COMMENT-ACCURACY |
| `security.md` | SECRET-MGMT、LOG-SAFETY、SECURITY-INCIDENT；pre-commit checklist 9 項 |
| `testing.md` | 80% coverage、TDD（RED→GREEN→IMPROVE）、unit/integration/e2e |
| `git-workflow.md` | commit format、PR workflow |
| `performance.md` | model selection（haiku/sonnet/opus）、context window 管理、thinking 設定 |
| `patterns.md` | skeleton project、repository pattern、API response envelope |
| `hooks.md` | hook types（Pre/Post/Stop）、HOOK-OUTPUT（PostToolUse stdout 不注入 AI context）、auto-accept、TodoWrite |
| `agents.md` | agent registry（planner/architect/tdd-guide/code-reviewer…）、parallel execution |

### typescript/

| 規則檔 | 重點規則 |
|--------|---------|
| `coding-style.md` | IMMUTABILITY（spread）、ERROR-HANDLING（async/await）、INPUT-VALIDATION（Zod）、CONSOLE-LOG、REACT（re-render/useEffect cleanup）、REACT-NATIVE（FlatList/StyleSheet.create） |
| `testing.md` | E2E: Playwright |
| `patterns.md` | ApiResponse\<T\>、useDebounce hook、Repository\<T\> |
| `hooks.md` | PostToolUse: prettier/tsc/console-log-warn；Stop: console-log-audit |
| `security.md` | SECRET-MGMT: process.env + startup validation |

---

## 依賴關係圖

```
jira ←── jira-acceptance（取得需求資料）
  │
  ├── linus-requirements-analysis（需求分析，可回寫 Jira comment）
  │
  └── spec-module（--commit flag）
         ↑                ↓
      explore-report    spec-to-e2e-test（從 spec 產出 E2E 測試）
      （--to-spec flag）

spec-design ──→ plan-and-execute（openspec change + plan.md → 自動執行）
  spec-design:
    Phase 0: openspec explore（自由探索）
    Phase 1-4: superpowers:brainstorming（結構化收斂）
    Phase 5: openspec CLI → change artifacts（proposal + specs + design + tasks）
    Phase 6-7: 4-agent spec review
    Phase 8-9: plan mode → plan.md → 4-agent plan review
  plan-and-execute:
    讀取 plan.md → TDD 分 Wave 實作（subagent）
    支援 --resume / --wave / /loop 分批執行
    plan-and-execute ──→ test-module + spec-to-e2e-test（最終驗證）

auto memory ──→ weekly-review（整理 + skill 錯誤分析）
               Obsidian vault（瀏覽）

~/.claude/ ──→ sync-my-claude-setting（同步到 repo）

health（獨立稽核，無外部依賴）

post-commit-review hook ──→ commit-review skill（唯一執行層，2026-07-20 抽取）
  hook 只做：偵測 commit → lib/tier.ts 算 Tier → 上 marker → systemMessage 指派 skill
  skill 依 Tier 跑 chain：
    Tier 0: 只發通知（不經 skill）
    Tier 1: eslint → 自查 judgment-matrix.md §2 DoD → 通知（不 spawn agent）
    Tier 2: eslint → /simplify → pr-reviewer agent（lite）→ 修 CRITICAL（amend）→ blast radius → 通知
    Tier 3: Tier 2 全部 ＋ /pr-review-toolkit:review-pr code comments errors tests types → 修 Critical/Important
  分級判準權威：harness/commit-review-policy.md（skill 不重複判定表）
  blast radius：codebase-memory-mcp trace_path（inbound, risk_labels）；資訊性輸出不自動修改，未索引則跳過
post_tool_error hook ──→ ERRORS.jsonl ──→ weekly-review STEP 06-08（錯誤分析）

pending-review 閘門（2026-07-16 新增，取代舊版純提醒無強制力的做法）：
  post-commit-review.ts（PostToolUse Bash）
    → git diff --numstat 機械判定 Tier（0~3，邏輯在 scripts/lib/tier.ts）
    → Tier 2/3 寫入 marker（~/.claude/state/pending-review/<repo>.json）
       ↓ marker 存在
  commit-gate-guard.ts（PreToolUse Bash）
    → deny 該 repo 下一個 git commit（放行 --amend/push/[skip-review]；逾 4 小時自動清除放行）
       ↓ review 完成
       ↓ marker 未清時，回合也不得結束
  stop-review-guard.ts（Stop）
    → block 回合結束，以指令級注入指派 commit-review skill
    → sessionId 優先比對、cwd repoRoot 補位；per-session 最多攔 MAX_STOP_BLOCKS=3 次（保險絲）
       ↓ 所有面向結果收齊 + Critical 處理完（commit-review SKILL.md §3.1 / §5）
  clear-pending-review.ts（skill §5 呼叫，或手動執行）→ 唯一解鎖路徑

  subagent-review-clear.ts（SubagentStop）→ **只記 agent_type 到 debug log，不清 marker**
    （2026-08-17 移除清除職責：原本型別含 review 就清，Tier 3 並行 6 個 agent 時第一個回來的
     即解除閘門；full review 的面向 agent 也誤命中。詳見 harness/commit-review-policy.md）

  四者共用 scripts/lib/review-marker.ts（marker 路徑推導 / git -C·cd 跨 repo 解析 / isGitCommitCommand 判定）
    註：subagent-review-clear.ts 只借用其 MARKER_DIR 常數寫 debug log，不碰 marker
  Tier 判定共用 scripts/lib/tier.ts：hook（被動）與 compute-tier.ts（skill 手動模式）同一份，判定不分歧

pr-reviewer agent ──→ CODE-REVIEW-RULE.md（規則來源）
  lite: commit-review skill 的 Tier 2/3 chain 自動呼叫
  full: 手動指定 PR → 5 平行 Sonnet agents + Haiku 信心評分 → 自動 post GitHub PR review（v1.2.0）
  新增檔案例外（v1.3.0）：規則 9/10/11 命中 new file mode 的檔案 → 跳過慣例檢查、依規則字面判定

codebase-memory-mcp ──→ TOOL-USAGE graph-first 規則（已索引專案優先 search_graph/trace_path 取代 Grep/手動追呼叫鏈）
                      ──→ commit-review skill Tier 2/3 blast radius 分析
```
