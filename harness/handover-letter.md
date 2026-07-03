# G. 給未來 Session 的交接信 | status: DONE

> Fable 5 離場前寫給接手模型（Sonnet / Opus / Haiku）與 user 本人。
> 建立：2026-07-03。§3 未完成事項欄為綠區（後續 session 可自行更新），其餘為黃區。

## 1. 三件沒被問到、但對這個環境最關鍵的事

### 1-1. settings.json 裡有一把硬編的 API key，且權限模式與自訂規則對著幹
`~/.claude/settings.json` 的 permissions.allow 內硬編了 context7 API key（`ctx7sk-97b9...`），直接違反 user 自己的 SECRET-MGMT 規則；同檔 `defaultMode=acceptEdits`＋skipDangerous/skipAuto 兩旗標，與 rules/hooks.md「banned dangerously-skip、exploratory 要關 auto-accept」矛盾。
**為什麼關鍵**：key 外洩風險是即時的；權限矛盾則讓「規則說不行、環境說可以」成為常態，弱模型會學到「規則可以不算數」。
**建議動作（user 本人，紅區）**：rotate context7 key 改走環境變數；二選一——把旗標拿掉，或把 rules/hooks.md 的 AUTO-ACCEPT 段改成與實際一致。

### 1-2. 兩套自動記憶外掛平行運作，其中一套已半故障，每個 session 都在扣稅
claude-mem（182MB）與 context-mode（13MB）都掛 SessionStart/PostToolUse/PreToolUse/UserPromptSubmit hooks、都注入指令、功能高度撞車。context-mode 的 SessionStart DB 載入**目前是壞的**（better_sqlite3 NODE_MODULE_VERSION 115 vs 137，需 `npm rebuild`），但 routing 指令照常注入——「壞的還在發號施令」是最差狀態。
**為什麼關鍵**：這是全機最大的固定 token 漏水源（見 harness-diagnosis.md §1），而且兩套系統對「resume 後先查誰」互搶主導，弱模型會抖動。
**建議動作（user 本人，紅區）**：擇一保留。無論留誰，記憶的**手動寫入**單一真相已定為 auto-memory＋tasks/lessons.md（knowledge-protocol.md §2），自動系統降級為唯讀查詢。

### 1-3. ems_timer 的記憶已達精簡門檻，且「待實機驗證」的球最容易掉
專案 memory 188KB、索引 41 條，是全機次高的 5 倍，已觸發 knowledge-protocol.md §3 門檻（memory/ 總量 188 KB > 100 KB）。同時有三顆「待實機」的球懸著：電池白屏修復（根因 2026-06-14 已定位，只修地線接點）、ems_vent 去留、INMP441 換料重試——這類球在 session 交接時最容易無聲消失，因為沒有任何機制會主動提起它們。
**建議動作**：下次進 ems_timer 先跑 /weekly-review 精簡記憶；把「待實機驗證」清單固定放在 tasks/todo.md 最頂（焦點標題日期已過時，2026-05-25 → 現在）。

## 2. 這套制度在弱模型長期運作下的腐化方式與預防

### 腐化一：例外堆積（最快發生）
弱模型為了讓當前任務過關，逐次放寬判準——「這次先算 Tier 1」「這次先不派驗證」，例外三次就成慣例。
**可觀測信號**：commit 全是 Tier 0/1、驗收 agent spawn 次數趨近零、judgment-matrix 從未被引用。
**預防**：knowledge-protocol.md §4 已明文「判準有問題走提案，不走例外」；commit-review-policy 已明文「有疑義向上取嚴」。user 端抽查法：隔週問一句「最近十次 commit 的 Tier 分布？」——答不出來就是制度已死。

### 腐化二：路由失讀（最隱蔽）
CLAUDE.md 是路由中心，但弱模型可能永遠不點開 harness 檔，只憑路由行的一句摘要自由發揮——制度淪為裝飾。
**可觀測信號**：派工 prompt 沒有三件套結構、完成宣告沒有 DoD checklist、熔斷提問不是標準格式。
**預防**：關鍵觸發時機已直接寫在 CLAUDE.md `<harness>` 段（讀得到路由就讀得到時機）；user 端一句「照 harness 做」即可拉回；大任務開場多加一句「先讀 ~/.claude/harness/README.md」成本最低。

### 腐化三：引用再腐化（最必然）
檔案搬移、plugin 更換、模型換代後，制度檔內路徑與 agent 名再度失效——這正是本次診斷出 10 條壞引用的成因，沒有理由不再發生。
**可觀測信號**：agent 呼叫失敗後改用自由發揮、規則被無聲跳過。
**預防**：knowledge-protocol.md §4 的 read-back 驗收含「引用路徑逐一存在」檢核；建議每 1-2 個月派一次 Explore agent 跑壞引用掃描（delegation-templates.md §1 模板，驗收條件填「CLAUDE.md/harness/rules 引用的路徑、agent、skill 逐一存在」）。

### 腐化四：記憶通脹（最慢但複利）
教訓越寫越多 → 索引超過弱模型願意讀的長度 → 召回率下降 → 重複踩坑 → 寫更多教訓。ems_timer 已在這條曲線上（41 條）。
**預防**：knowledge-protocol.md §3 的量化門檻與「三條合一原則」抽象化；精簡時禁刪「仍會踩」的坑。

## 3. 未完成事項交接（綠區，後續 session 可更新）

本 session（2026-07-03）交付清單 A~G 全部完成。留給 user 的紅區待辦（模型不得代動）：
- [x] context7 key 明文洩漏**結案**（2026-07-03）：user 已上 dashboard revoke 舊 key；已清除全部設定層明文——settings.json:91 死白名單、3 份 .bak 備份、~/.claude.json 內掛在 /Users/maxhero/.claude 專案的帶 key stdio server 配置（全部 JSON 驗證通過）。現行 context7 = plugin 匿名模式。惰性殘影（key 已 revoke 故無害）：本 session 的 file-history 快照與 session 轉錄檔，會隨清理週期消失。日後若需高速限：免費申請新 key，走 `export CONTEXT7_API_KEY` 環境變數，不進任何 json 設定檔（§1-1）
- [x] 決定 claude-mem / context-mode 去留 → 2026-07-03 user 拍板：**停用 context-mode、保留 claude-mem**（settings.json 已改，備份 settings.json.bak.20260703）。殘留清理見下：
  - [x] SessionStart hook `context-mode-cache-heal.mjs` 已移除（2026-07-03，JSON 驗證通過；腳本檔本體仍在 ~/.claude/hooks/ 未刪）
  - [x] permissions.allow 死條目已清（2026-07-03）：context-mode 5 條＋serena **16** 條（審計原報 5 條為低估），JSON 驗證通過
  - [ ] `~/.claude/context-mode/` 資料目錄 13MB，確定不回頭後可刪
- [x] `~/.claude/hooks.json` 死檔＋rules/ 內 13 個 `.md.20260310` 備份已清（2026-07-03）：全部搬至 `~/.claude/backups/cleanup-20260703/`（可還原；含已遺失 agents.md 的唯一殘本 agents.md.20260310）
- [x] 5 支 PostToolUse hook 檢視（2026-07-03 分析完成，部分已處置）：
  - [x] spec-section-validator **修好**：輸出改 systemMessage JSON（原純 stdout 警告蒸發），兩測資實跑通過（.bak 在 scripts/）
  - [x] inventory-drift-detector **砍掉**：搬 backups/cleanup-20260703/（職責已由 knowledge-protocol read-back 接手，索引檔停更於 3 月）
  - [x] skill-version-check：KEEP（設計正確）
  - [x] post-commit-review **改造完成**（2026-07-03）：移除內建 eslint 段（原最多同步阻塞 30s）、systemMessage 改為指向 commit-review-policy.md 分級制＋內嵌 Tier 速查；三測資實跑通過（.bak 在 scripts/）
  - [x] post_tool_error **matcher 已縮**（2026-07-03）：空 matcher（全匹配）→ `Bash`，砍掉最高頻 python3 冷啟；ERRORS.jsonl 消費者（weekly-review / save-progress）不受影響
  - [ ] 觀察名單：SessionStart 的 detect-jira-issue.sh 在 ERRORS.jsonl 累積 519 筆失敗（非 Jira 專案每次開 session 都失敗？值得查）

## 4. 啟動指南：明天怎麼開始用這套 Harness（user 視角）

1. **什麼都不用設定**——新 session 自動載入重寫後的 CLAUDE.md 路由中心，弱模型會在對應時機被導向 harness 檔。
2. **開大任務時**加一句：「先讀 `~/.claude/harness/README.md` 再開工」——這是對抗「路由失讀」最便宜的保險。
3. **四句糾正咒語**（看到症狀就唸）：
   - 模型自己下場掃 repo →「照 model-dispatch 派工」
   - 宣告完成沒證據 →「過 judgment-matrix §2」
   - 原地重試第三次 →「看 judgment-matrix §1」
   - commit 後跑全套 review →「照 commit-review-policy 分級」
4. **驗收別人的實作**時說：「派 fresh-context 驗收，用 delegation-templates §5」。
5. 隔週抽查一次腐化信號（§2 各條的「可觀測信號」）。
