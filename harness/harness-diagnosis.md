# A. Harness 漏水診斷書 | status: DONE

> 用途：指出當前工作流中最浪費 token、最易失焦、最常引發工具調用錯誤的前三痛點，附物理級阻斷方案。本檔是其他 harness 檔案的立論依據。
> 診斷：Fable 5，2026-07-03。資料來源：三路唯讀審計 subagent（全域設定 / ems_timer 專案層 / 記憶與外掛生態），各自信心 8/10。
> 「物理級阻斷」定義：改結構讓錯誤**做不出來**（刪死引用、加機械 gate、收斂入口），而不是寫一條「請注意」。

## 0. 診斷方法

- 審計一：`~/.claude/` 全域設定、hooks 接線、rules、破引用逐項驗證、settings.json。
- 審計二：ems_timer 專案層（tasks/、docs/、firmware/、spec/、git 近況 vs CLAUDE.md 宣稱）。
- 審計三：記憶系統×6、plugin×24、session 啟動注入量實測（bytes → 估 tokens）。
- 未量測到的以「動態、未計入」標示，不編造數字。

## 1. 痛點一：session 啟動注入過載＋多頭指令衝突（最浪費 token、最易失焦）

### 量化證據
每個 session 開始前，模型還沒做任何事就先吃掉：

| 注入源 | bytes | 估 tokens |
|---|---|---|
| ~/.claude/CLAUDE.md | 10,723 | ~3,574 |
| rules/ 實載 12 檔 | 8,890 | ~2,963 |
| ~/Documents/CLAUDE.md | 8,703 | ~2,901 |
| ems_timer/CLAUDE.md | 9,915 | ~3,305 |
| memory/MEMORY.md | 7,783 | ~2,594 |
| **靜態固定稅** | **46,014** | **~15,337** |
| context-mode routing 指令 | 3,455 | ~864 |
| superpowers using-superpowers（SessionStart 全文注入） | 3,063 | ~766 |
| claude-mem SessionStart observations | 動態 | 數百~數千（未計入） |

### 指令衝突對照（弱模型失焦的直接原因）
| 衝突 | A 方說 | B 方說 |
|---|---|---|
| 溝通風格 | context-mode：「Terse like caveman」 | 系統 prompt＋CLAUDE.md PERSONA：完整句、可讀性優先 |
| 開場動作 | superpowers：「回應任何訊息前必先 invoke skill」 | GATE-1：「先一句話重述需求請 user 確認」 |
| resume 後先查誰 | claude-mem：先查 observations | context-mode：先 ctx_search timeline |
| 教訓寫到哪 | CLAUDE.md LEARNING：feedback memory | claude-mem：hook 自動全收（三重冗餘） |
| 權限模式 | rules/hooks.md：banned dangerously-skip、exploratory 關 auto-accept | settings.json：defaultMode=acceptEdits＋skipDangerous/skipAuto 旗標 |

失焦機制：指令間**沒有優先權聲明**。Fable 等級能自行仲裁；Sonnet 會嘗試同時滿足全部或隨機挑一套服從，行為在 session 間抖動；Haiku 直接抓最後看到的那條。每次抖動 = 重試 = token 燒掉。

### 物理級阻斷方案
1. **✅ 本 session 已做**：全域 CLAUDE.md 重寫為路由中心（10.7KB → 目標 <5KB），細則抽到 `~/.claude/harness/`，頂部加「指令優先權聲明」（user 明示 > CLAUDE.md/rules > plugin 注入；衝突時取前者）。
2. **🔴 紅區建議（user 自行決定，模型不得代動）**：
   - claude-mem（182MB）與 context-mode（13MB＋SessionStart 已故障：better_sqlite3 NODE_MODULE_VERSION 115 vs 137，需 `npm rebuild`）功能高度撞車。建議**擇一**：保留原生 auto-memory 為記憶單一真相；claude-mem 降為唯讀歷史查詢或停用；context-mode 不修就停用（現在是「壞的還在注入指令」最差狀態）。
   - superpowers 的 SessionStart 全文注入若可改為 lazy（僅列 skill 清單），省 ~766 tokens/session。

## 2. 痛點二：引用腐化——規則指向不存在的資源（最常引發工具調用錯誤）

### 壞引用清單（審計逐項驗證）
| # | 引用處 | 指向 | 實際狀態 |
|---|---|---|---|
| 1 | rules/{git-workflow,testing,performance,security}.md | agents：planner / tdd-guide / e2e-runner / build-error-resolver / security-reviewer | 只存在於 **everything-claude-code plugin，且該 plugin 已停用** → 呼叫必失敗 |
| 2 | 全域 CLAUDE.md `<ref>`＋rules/README | rules/common/agents.md | **檔案遺失**，只剩 `.md.20260310` 備份 |
| 3 | ~/Documents/CLAUDE.md | `generate-spec-mapping.cjs` | 實際是 `.ts`，照抄指令必失敗 |
| 4 | ~/.claude/hooks.json | gitnexus-hook.cjs | Claude Code 只讀 settings.json，**hooks.json 整檔不生效**，且與 settings.json 的 gitnexus-hook.ts 重複 |
| 5 | settings.json permissions.allow | 5 條 `mcp__plugin_serena_*` | serena 未啟用，死條目 |
| 6 | 全域＋專案 CLAUDE.md workflow | `tasks/lessons.md` | ems_timer 內**不存在**（制度引用一個沒人建立的檔案） |
| 7 | memory/MEMORY.md 索引 | 43 個記憶檔 | **3 個孤兒**有檔沒索引 → 寫了召回不到 |
| 8 | rules/common/performance.md | 模型選單 haiku/sonnet/opus-4.5 | 過時（現為 Claude 5 家族＋Opus 4.8）；CLAUDE.md 兩處「4.7 預設」同病 |
| 9 | ems_timer/CLAUDE.md | 「ems_countdown / ems_vent 已廢止」 | ems_vent 的 source＋test＋build 產物都還在，宣稱不實 |
| 10 | ems_timer/CLAUDE.md 開發階段 | Dev-Phase 2/3 未勾 | git 顯示 BLE Phase F＋DS3231 已上機，勾選落後實際 |

### 弱模型的典型失敗模式
Sonnet 讀到「review: code-reviewer agent」→ 呼叫不存在的 agent → 錯誤 → 換個寫法再試 → 再錯 → 放棄改用自由發揮。每個死引用 = 一段必然失敗的重試迴圈＋一次無聲的規則失效。

### 物理級阻斷方案
1. **✅ 本 session 已做/將做**：重寫兩份 CLAUDE.md 時移除/修正 #2 #6 #8(CLAUDE.md 部分) #9 #10；修 rules 四檔的死 agent 引用（#1）改指向實際可用資源；補 MEMORY.md 孤兒索引（#7）；建立 tasks/lessons.md（#6）；修 Documents/CLAUDE.md 的 .cjs→.ts（#3）。
2. **🔴 紅區建議**：刪 `~/.claude/hooks.json`（#4）；清 settings.json serena 死條目（#5）；rules/ 內 13 個 `.md.20260310` 備份移出 rules/（混在規則目錄裡遲早被誤讀）。
3. **制度性預防**：knowledge-protocol.md §4 規定改 harness 檔後必跑 fresh-context read-back（含「引用路徑逐一存在」檢核）——讓死引用在誕生當下就被攔截。

## 3. 痛點三：POST-COMMIT-REVIEW 固定成本＋PostToolUse 五連發

### 成本量化
- 每次 git commit 強制五步：eslint → /simplify → pr-reviewer agent → review-pr（4 面向，pr-review-toolkit 多 agent）→ osascript 通知。單次 commit 可觸發 **6~10 個 agent、數萬 token**，與 diff 大小無關——改 3 行也全跑。
- 「純 docs commit 可跳過」的豁免存在於一條 feedback memory 裡，不在主規則——靠記憶補丁維持的規則，弱模型召回不到就照跑全套。
- 另外 settings.json 對 **每一次** Write/Edit/Bash 掛了 5 支 PostToolUse hook（spec-validator、inventory-drift、skill-version-check、post-commit-review、post_tool_error），高頻小額扣血。

### 物理級阻斷方案
✅ 本 session 已建 [commit-review-policy.md](commit-review-policy.md)：以 `git show --stat HEAD` 機械分級（Tier 0 純文件 → Tier 3 大改動全套），全域 CLAUDE.md 的 POST-COMMIT-REVIEW 段落改為指向該檔。豁免規則從 memory 升格為正式制度。
🔴 紅區建議:5 支 PostToolUse hook 逐支檢視是否仍需要（特別是 skill-version-check 與 inventory-drift 的觸發頻率 vs 產值）。

## 4. 次要漏水點（不進前三，記錄備查）

- ⚠ **安全**：settings.json permissions.allow 硬編 context7 API key（`ctx7sk-97b9...`），違反自訂 SECRET-MGMT 規則。建議 user rotate 並改環境變數。（紅區，僅通報）
- COMMIT-MSG 規則在全域 CLAUDE.md 與 Documents/CLAUDE.md 雙重維護（內容目前一致，遲早漂移）。本次不強行收斂（Documents 檔服務 Compal 工作流），記錄於交接信。
- 備份垃圾散落：~/.claude/ 頂層 4 個 CLAUDE.md/settings 舊備份共存，命名不一致（.bak / .20260303 / .bak.20260420）。
- ems_timer memory 188KB 為全機最大（次高 36KB），已觸發 knowledge-protocol.md §3 精簡門檻。
- 一個 memory 目錄誤掛在 plugin cache 路徑（skill-creator/memory，16KB），屬雜訊。
- ems_timer/CLAUDE.md「電源供應規劃」寫 Dev-Phase 2~3 用 USB 直供，但實際已在焊 LiPo＋TP4056 並 debug 電池白屏——階段敘述脫節。
- statusline-command.sh 39KB（單一 statusline 腳本，複雜度異常，可能藏維護成本）。
- spec/ Drift Detection 流程在 ems_timer 永不觸發（無 spec/ 目錄）——無害但屬死制度。

## 5. 誠實條款：這套 Harness 的能力極限

### 拆解＋隔離驗證能逼近高階品質的範圍
凡是**驗收條件可寫成機械判準**的任務（測試綠、路徑存在、行數下降、輸出匹配），Sonnet 級在本 harness 下可穩定產出，因為：判準外化在檔案裡（judgment-matrix.md）、驗證強制隔離（model-dispatch.md §5）、失敗有升級路徑（§4）。

### 弱模型注定失敗的領域與應對標準
**模糊的商業美感、品味決策**（「要有專業感」「這兩個方案哪個更優雅」「文案語氣」）——弱模型會產生**幻覺式審美**：自信地選一個並編造理由。拆解與驗證救不了這個，因為沒有可驗證的判準。

具體應對標準（judgment-matrix.md §4 的三選一，強制執行）：
1. 參照優先：照抄 user 已驗證的參照物（本專案 UI = docs/demo/index.html 美學）。
2. 候選展示：出 2-3 個差異明顯的候選＋tradeoff，讓 user 選，禁止自評「更具現代感」。
3. 標註跳過：列「品味決策點」清單留給 user，先做可量化的部分。

### 其他已知極限
- **跨 session 一致性**：制度只在被讀到時生效。弱模型可能不讀 harness 檔就開工——預防靠 CLAUDE.md 路由中心夠短（讀得完）＋關鍵規則放在 CLAUDE.md 本體（不能只放連結）。
- **量測不到的就別宣稱**：本診斷書中 claude-mem 動態注入量、5 支 PostToolUse hook 的實際延遲皆未實測，標示為未計入。後續模型引用本檔數字時，禁止把「估 tokens」升格為「實測 tokens」。
- **硬體專案特有**：模型永遠碰不到實體電路。任何「硬體上應該會動」都是推論，judgment-matrix.md §2 硬體條款強制標「⏳ 待實機驗證」。
