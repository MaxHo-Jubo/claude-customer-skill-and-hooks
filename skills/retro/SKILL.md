---
name: retro
description: "對 coding session 做環境檢討（retrospective）：產出改善 agent 工作環境的建議，不改程式碼。手動 /retro [session 路徑或 uuid]；weekly-review STEP 09 也會派 subagent 照本檔執行。"
disable-model-invocation: true
---

<!-- 上游 mattpocock/skills@49dd158d skills/engineering/retro/SKILL.md，本機化改寫：繁中、補證據門檻、對應本機檔案、移除 openai.yaml -->

使用者要求 **retrospective**。你要建議的是 coding agent **環境**的改善，讓未來的 run 更順；不是評論這次的程式碼。

只讀不改：本 skill 產出候選清單，所有變更由使用者逐項確認後另行執行（改 CLAUDE.md / rules / harness 走 `~/.claude/harness/knowledge-protocol.md`）。

## Steps

1. 讀 `references/writing-for-agents.md`（本 skill 目錄下）取得寫作風格指南。

2. 讀使用者指定 session 的原始來源。可能要搜尋本機 session log（`~/.claude/projects/<專案>/<uuid>.jsonl`）；沒指定就讀當前 session。jsonl 動輒數 MB，不整檔 Read：用 `jq` 抽 `type=="user"` 的訊息、`tool_use` 的工具名與參數、`is_error` 為 true 的 `tool_result`，再依線索局部展開。

3. 依下列面向找改善候選。**每個候選必附證據**：session 檔路徑＋行號（或引用的原句）；沒有證據的候選不列。斷言「某檢查／文件不存在」前，先實際查 repo（`package.json` scripts、CI workflow、hooks 設定）。

- **Navigation**：agent 找對檔案容易嗎？檔案間有沒有隱藏依賴？加一個 **navigation pointer** 會更好嗎？_適用時機_：session 花很久才找到某個資訊。
- **Automated checks**：有沒有自動檢查能抓到 agent 犯的錯？linting、typing、tests、filesystem linters。先讀 repo 自己的 check 指令（`package.json`／build tool 的 `lint`／`check` script、CI workflow），所以「已存在但沒接上或壞掉」的檢查才是 finding，不要重新發明。repo 完全沒有 **guardrail**（沒有 pre-commit hook 也沒有跑 lint/typecheck/test 的 CI job）本身就是 finding：沒 lint 的 repo 是持續存在的機會損失，不是中性預設。_適用時機_：agent 犯了自動檢查抓得到的錯，或 repo 完全沒有 guardrail。
- **Coding standards**：**reviewer agent** 該新增規則嗎？既有規則該刪除或釐清嗎？先分類違規：**mechanical**（固定語法模式、禁用 API、import 形狀、檔案位置規則）一律做 deterministic check——repo 自己 linter 的 custom rule、新的 pre-commit hook 或新的 CI job，挑該語言與既有 guardrail 下最便宜的；預設是建檢查，不是寫規則。`~/.claude/CODE-REVIEW-RULE.md` 只留給真正的 **judgement call**（跨檔一致性、「符合周圍風格」、任何 guardrail 都無法取代的）。_適用時機_：reviewer agent 沒抓到錯。
- **Global CLAUDE.md**：有沒有 steering 指令該搬到 coding standards（或自動檢查）？_適用時機_：`CLAUDE.md` 特別肥——repo 內或使用者全域（`~/.claude/CLAUDE.md`、`rules/`）。
- **Tool economy**：agent 有沒有做昂貴、可精簡的 tool call？自製工具（CLI、MCP）有沒有特別耗 token 的？_適用時機_：agent 做了昂貴的 tool call。
- **No-ops**：找 steering 檔裡不改變 agent 行為的指令。_適用時機_：steering 檔肥大難管。
- **Information access**：有沒有機會增加 agent 的資訊存取？tee dev server log、第三方服務唯讀存取。_適用時機_：關鍵資訊 agent 拿不到。

4. 依嚴重度排序，把候選呈現給使用者。每筆：面向、一句話問題、證據、建議的具體變更（哪個檔、改什麼）。

## Reference

### Implementation vs Review

所有工作都走兩階段：implementation 與 review。implementation agent 的 **context pressure** 最大——負責探索、寫 code、debug 失敗。

review agent 的 context pressure 最小——它收到的是 diff，不需探索，通常也不需寫 code 或 debug。

所以 coding standards 該由 review agent 執行，不是 implementation agent。

### Files

- `CLAUDE.md`／`AGENTS.md`：會推進任何在該 repo 工作的 agent 的 context window。極度節制使用，通常只放指向其他檔案的 **navigation pointer**。
- `~/.claude/CODE-REVIEW-RULE.md`：review 階段讀，implementation 階段不讀。檔案超過 1,000 行就加 **navigation pointer** 指向 docs 資料夾。
- Docs：當作被其他檔指到的參考檔；寫新 doc 前先找既有的。
- Skills：description 會進 agent 的 context window，適合拿來裝 docs 或使用者手動觸發的指令；寫法依 `references/writing-for-agents.md`。
