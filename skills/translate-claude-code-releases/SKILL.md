---
name: translate-claude-code-releases
description: "翻譯 Claude Code GitHub releases 的更新內容為繁體中文。可帶版本號參數翻譯該版本起到最新版；不帶參數則從上次記錄的版本之後翻到最新。當使用者提到 /translate-claude-code-releases、「翻譯 release」、「翻譯更新內容」、「claude code 更新了什麼」、「翻譯 changelog」、想看 Claude Code 版本更新的中文說明時觸發。"
version: 1.0.0
---

# Translate Releases 翻譯版本更新

把 [anthropics/claude-code releases](https://github.com/anthropics/claude-code/releases) 的英文更新內容翻譯成繁體中文，並記錄翻譯到的最新版本，下次自動接續。

## 使用方式

- `/translate-claude-code-releases` — **自動模式**：從 `last-version.txt` 記錄的版本「之後（不含）」翻到最新；首次無紀錄時只翻最新一版
- `/translate-claude-code-releases 2.1.154` — **指定模式**：從 `2.1.154`「（含）」翻到最新（開頭 `v` 可省略）

範例：
- `/translate-claude-code-releases 2.1.154` → 翻譯 2.1.154、2.1.155 … 直到最新版
- `/translate-claude-code-releases` → 接續上次紀錄繼續翻最新的幾版

## 核心約束（必讀）

- **翻譯用 sonnet**：翻譯工作一律 dispatch 一個 `model: "sonnet"` 的 subagent 執行，主 agent 不自己翻（省 token、隔離大量原文）。
- **版本號比較用 semver**：`2.1.9 < 2.1.10`，已由 `fetch-range.sh` 內 `sort -V` 處理，不要自己用字串比大小。
- **記錄只在成功後寫入**：翻譯完成後才用 Write 更新 `last-version.txt`，避免翻譯失敗卻記錄、導致漏翻。
- **原文不灌進主 context**：原始 release notes 由 `fetch-range.sh` 寫進 `raw.md`，翻譯 subagent 直接讀檔，主 agent 只看範圍 metadata。

## 執行步驟

### STEP 01: 取得待翻譯範圍

執行 helper script（`$1` 為使用者帶入的版本號，沒帶就空著）：

```bash
~/.claude/skills/translate-claude-code-releases/fetch-range.sh "$1"
```

解析 stdout：
- `COUNT=0` → 沒有更新的版本，直接回報「目前已是最新（已翻到 vX.Y.Z），無新版本」並結束。
- 否則記下 `FROM` / `TO` / `COUNT` / `RAW`（`RAW` 為原始 notes 檔路徑）。

### STEP 02: Dispatch sonnet 翻譯 subagent

用 Agent tool 指定 `model: "sonnet"`：

```
Agent(
  description: "Translate claude-code releases to zh-TW",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: """
    讀取檔案 <RAW 路徑>，把裡面每個版本的 release notes 翻譯成繁體中文（正體中文用字）。

    翻譯規則：
    - 保留每個版本的 `## vX.Y.Z （發佈日：YYYY-MM-DD）` 標題不動。
    - 逐條（bullet）翻譯，維持原本的條列結構與順序。
    - 技術術語、程式碼識別符、檔名、旗標、環境變數、設定鍵、指令（如 `CLAUDE_CODE_ENABLE_AUTO_MODE`、`/model`、`EnterWorktree`、`settings.json`）保留原文不譯，用反引號標記。
    - 產品/平台名稱（Bedrock、Vertex、Foundry、VS Code、WSL、tmux 等）保留原文。
    - 用詞精準、口語自然，不要直譯腔；不要新增原文沒有的內容，不要省略任何一條。
    - 開頭加一行 `# Claude Code 版本更新（繁體中文）` 與一行範圍說明 `> 範圍：vFROM ～ vTO，共 N 版`。

    翻譯完成後，用 Write 工具把結果寫到：
      ~/.claude/skills/translate-claude-code-releases/output/releases-zh-<FROM>-to-<TO>.md
    （FROM/TO 去掉開頭 v，例如 releases-zh-2.1.156-to-2.1.158.md）

    回傳：輸出檔的絕對路徑 + 翻譯了哪幾個版本（版本號清單）。
  """
)
```

把 STEP 01 的 `RAW` / `FROM` / `TO` / `COUNT` 實際值填進 prompt。

### STEP 03: 更新版本紀錄

subagent 成功回傳後，用 Write 工具把**最新版本號**寫入紀錄檔（即 STEP 01 的 `TO`，含 `v`）：

```
Write(~/.claude/skills/translate-claude-code-releases/last-version.txt, "<TO>")
```

> 失敗（subagent 報錯或沒產出檔案）時**不要**更新紀錄，回報錯誤即可。

### STEP 04: 回報

向使用者回報：
- 翻譯範圍（FROM ～ TO，共 N 版）
- 輸出檔路徑
- 已將 `last-version.txt` 更新為 `<TO>`
- 翻譯內容摘要可附在訊息中（若版本多、內容長，以檔案為主，訊息只給重點）

## 檔案說明

| 檔案 | 用途 |
|------|------|
| `fetch-range.sh` | 抓取版本範圍、產生 `raw.md`、輸出範圍 metadata |
| `raw.md` | 原始英文 notes 暫存（每次執行覆寫，可不納版控） |
| `last-version.txt` | 上次翻譯到的最新版本號（跨 session 持久；不存在=首次） |
| `output/releases-zh-*.md` | 翻譯產出 |
