# ctx-handoff（save-progress 改版）

[English](README.md)

> **原出處**：本 mod 修改自 [cablate/ctx-handoff-mod](https://github.com/cablate/ctx-handoff-mod)（作者 cablate，MIT 授權），基準版本為 commit [`f871109`](https://github.com/cablate/ctx-handoff-mod/commit/f871109)（2026-10-03）。原作者的版權聲明保留於 [LICENSE](LICENSE)。修改內容見下方[與原版的差異](#與原版的差異)。

一個 Claude Code mod，**自動**把太長的對話交接給新對話：主對話的 context 達到門檻時，它會讓 model 執行 `save-progress` skill，把交接紀錄寫進磁碟（有 Jira 票寫進 Jira 開發筆記，沒有就依 branch 名稱另存），確認檔案真的寫好後執行 `/clear`，再讓新對話讀那份交接紀錄接續。你離開時，它會幫你保溫 prompt 快取；到最後只存一份交接紀錄，不清除對話。正常使用時不必打任何指令。

**適合誰**：用 1M context 模型跑長時間 Claude Code session、用 Claude 訂閱登入（1 小時 prompt 快取），而且本機裝有 `save-progress` skill 的人。**狀態**：實驗性。它建立在 Claude Code 仍屬 early access 的 function hooks API 上，Claude Code 改版時可能需要跟著調整。依賴它之前，請先讀[限制](#限制)。

## 與原版的差異

| 項目 | 原版 | 本改版 |
|---|---|---|
| 交接內容怎麼產生 | `$.model.fork` 產生一份 ≤ 1500 字摘要 | 送出一個真的回合，讓 model 執行 `save-progress` skill（fork 不能用工具，所以跑不了 skill） |
| 交接存在哪 | mod 的 `$.store`（最近 5 份全文） | 磁碟上的交接紀錄：`{專案}/.claude/{Jira 編號}.md` 的 `## 交接紀錄` 段落，或 `{專案}/.claude/handoff-{branch}.md`；`$.store` 只留最近 5 筆的路徑 |
| 新對話收到什麼 | handoff 全文 | 交接紀錄的路徑，由新對話自己讀檔（`/jira` 也讀得到） |
| `/clear` 前的檢查 | fork 有回答就清 | 存檔回合要正常結束、回覆最後一行要有 `HANDOFF_FILE: <絕對路徑>`、檔案要存在且是這次存檔開始後才寫的；任一項不成立就**不** `/clear`，改用 toast 告知原因 |
| 存檔回合的辨識 | 不需要 | 存檔 prompt 帶 `[ctx-handoff:save]` 標記，`turn.start` 認出後記下 `turnId`；存檔中使用者插話的回合不會觸發交接；送出超過 10 分鐘仍未被認出時，在下一個主對話回合結束時解除存檔中狀態 |
| 離席交接 | fork 摘要存進 `$.store` | 跑 `save-progress` 存檔，不 `/clear`；已有離席交接時不再刷新或重存 |
| 非互動 session | 一樣會自動交接 | `session.start` 的 `isInteractive` 為 false（`claude -p`、SDK、排程 runner）時不做自動交接、不啟動閒置刷新，避免在呼叫端等結果時插入存檔回合並 `/clear`；`/handoff-now yes` 仍可手動用 |
| 失敗處理 | — | `prompt.submit` 被其他 plugin／settings hook 擋下（`{ drop }`）視為失敗；計時器啟動的工作失敗會 log + toast，不靜默；連續 2 次存檔驗證失敗就暫停該 session 的自動交接（`/handoff-now yes` 仍可用）；`/handoff-resume`／`/handoff-continue` 成功後才刪離席紀錄，送不出去時被攔下的訊息放回輸入框 |
| 測試 | 9 個 | 24 個（新增檔案不存在、舊檔、無路徑、多個路徑取最後、存檔被中斷、存檔中插話、存檔回合遺失、非互動 session、prompt 被攔下、失敗上限、離席攔截、`/handoff-continue`、`/handoff-now`、中斷的一般回合；並斷言先 `/clear` 再送出、交接後可再次觸發） |

門檻數值、閒置刷新節奏、背景工作偵測與原版相同；`/handoff-*` 指令名稱沿用原版，行為依上表調整。

**程式風格範圍**：本改版新增或改寫的函式與宣告，依 fork 者的程式規範補上 JSDoc、STEP 註解、變數註解與 if 大括號；原作者未改動的函式（`runningWork`、`isRefreshOn`、`tool.call`、`prompt.submit`、`/handoff-refresh`）維持原樣，方便對照上游。

原作者用 probe mod 實測過的基本元件（引自[原作者 README](https://github.com/cablate/ctx-handoff-mod)），本改版仍沿用：mod 可以執行 `/clear` 後接著 `prompt.submit`；對 102k token 的對話做 fork 時約 99.5% 的輸入 token 從快取讀取。

## 它會做什麼

三條路徑都只作用在主對話，子代理的回合一律略過。

| 什麼時候 | 會發生什麼 | 你要做什麼 |
|---|---|---|
| **回合結束，且 context ≥ 600k**（或視窗的 80%，取較小者） | 如果還有背景 shell、workflow 或子代理在跑，就先等。否則送出存檔 prompt，讓 model 執行 `save-progress`；確認交接紀錄寫好後 `/clear`，新對話讀交接紀錄、回報它理解的現況，然後等你指示。 | 不用 |
| **閒置 55 分鐘** | fork 一個很小的請求刷新快取，最多 3 次（約 3 小時 40 分後存離席交接）。到第 4 次改成執行 `save-progress` 存「離席交接」，而且**不** `/clear`：你不在，所以不替你換對話。 | 不用 |
| **離席交接存好後你回來** | 先攔下你的第一則訊息，請你選擇。 | `/handoff-resume` 開新對話讀交接紀錄，並帶上這則訊息；`/handoff-continue` 留在原本的對話。 |

### 交接紀錄寫到哪

由 `save-progress` skill 決定（規則在該 skill 的 STEP 01）。本 mod 在存檔 prompt 裡要求 model 於回覆最後一行寫 `HANDOFF_FILE: <絕對路徑>`，只讀回這一行：

| 目前 branch | 交接紀錄 |
|---|---|
| 含 Jira 編號（如 `<TICKET>/feat/<user>/測試`） | `{專案}/.claude/<TICKET>.md` 的 `## 交接紀錄` 段落 |
| 沒有 Jira 編號（如 `chore/sync-setting`） | `{專案}/.claude/handoff-chore-sync-setting.md` |
| 非 git repo 或 detached HEAD | `{專案}/.claude/handoff-{資料夾名}.md` |

## 快速開始

需要支援 function hooks（mod）的 Claude Code 版本，以及本機的 `save-progress` skill。開發與測試用的是 2.1.288。

```sh
claude --plugin-dir ~/.claude/mods/ctx-handoff
```

在 session 裡執行 `/handoff-status`，應該會看到類似：

```
[ctx-handoff] context 12034 / 門檻 600000（視窗 1000000）
自動交接：on
快取刷新 on，本次閒置已刷新 0/3，計時器未啟動
存檔回合：無
離席交接：無
最近一份交接：無
```

第一次使用建議先跑 `/handoff-now yes` 手動走一次完整流程，確認新對話有讀到交接紀錄。

想讓每個 session 都自動載入，在 `~/.claude/settings.json` 的 `env` 加上絕對路徑。有多個資料夾時，Windows 用 `;` 分隔，macOS/Linux 用 `:`：

```json
"env": { "CLAUDE_CODE_PLUGIN_DIRS": "/Users/you/.claude/mods/ctx-handoff" }
```

`claude plugin test` 若回報 `hooks modules are turned off in this process`，表示該帳號的 mod 功能還沒開放（伺服器端 feature flag `tengu_plugin_hooks_modules`），可用 `jq '.cachedGrowthBookFeatures.tengu_plugin_hooks_modules' ~/.claude.json` 查看。

## 指令

正常使用時用不到這些。

| 指令 | 用途 |
|---|---|
| `/handoff-status` | 查看 context 用量、門檻、刷新狀態、存檔回合、離席交接與最近一份交接紀錄路徑 |
| `/handoff-refresh on\|off` | 開關閒置時的快取刷新。關閉時，閒置 55 分鐘就直接存離席交接 |
| `/handoff-resume` | 使用離席交接：先 `/clear`，再讓新對話讀交接紀錄並回應剛才被攔下的訊息 |
| `/handoff-continue` | 放棄離席交接，在原本的對話送出被攔下的訊息 |
| `/handoff-now yes` | 立刻跑 `save-progress` 並交接（確認寫好後會清除目前對話） |

## 設定

數值是 [`hooks/register.ts`](hooks/register.ts) 開頭的常數，直接改那裡即可；資料夾有被監看時，存檔就會熱重載。

| 常數 | 預設 | 意義 |
|---|---|---|
| `THRESHOLD` | `600_000` | 觸發交接的 context token 數 |
| `WINDOW_RATIO` | `0.8` | 視窗較小時，門檻改成「視窗 × 這個比例」 |
| `IDLE_MS` | 55 分鐘 | 閒置多久後刷新（依 1 小時快取設定） |
| `MAX_REFRESH` | `3` | 存離席交接前最多刷新幾次 |
| `MIN_TOKENS` | `30_000` | context 低於這個值時，不刷新也不存離席交接 |
| `SAVE_LOST_MS` | 10 分鐘 | 存檔 prompt 送出超過這麼久仍未被認出，就在下一個主對話回合結束時放棄這次交接（不是計時器） |
| `MAX_SAVE_FAILURES` | `2` | 連續幾次存檔驗證失敗後暫停該 session 的自動交接 |

關於門檻（引自[原作者 README](https://github.com/cablate/ctx-handoff-mod)，本改版未另行查證）：社群回報和 Anthropic 自己公布的 MRCR 數據都顯示，品質大約在 200k–300k 左右開始下滑。設 600k 是原作者刻意的選擇，為了減少交接的次數。如果你發現還沒交接模型就開始變差，就把門檻調低。

## 限制

- **存檔回合的辨識尚未在真實 session 驗證。** 靠 `turn.start` 的文字含 `[ctx-handoff:save]` 認出存檔回合；mod 送出的 prompt 在真實引擎是否保留原文，測試環境模擬不出來。認不出時，送出超過 10 分鐘後的下一個主對話回合結束時會跳「存檔回合未被辨識，交接紀錄可能已寫入」，不會清掉對話；若你離席沒有新回合，存檔中狀態會維持到你回來。
- **存檔回合結束到 `/clear` 之間插話的那一輪會被清掉。** 存檔回合跑完後，`/clear` 會等 session 閒置才執行；這段時間你送出的訊息會在舊對話跑完再被清掉，交接紀錄不含它。
- **存檔是一個真的回合。** 在 600k context 跑 `save-progress` 會讀整段快取並呼叫工具；是否計入訂閱額度未確認。
- **離席存檔可能停在權限提示。** 如果 `save-progress` 寫檔需要你核准，這個回合會等你回來才繼續。
- **依賴 `save-progress` 回報路徑。** model 必須在回覆最後一行寫 `HANDOFF_FILE: <絕對路徑>`；沒寫、寫相對路徑、或檔案沒更新，都會取消交接。
- **5 分鐘快取的使用者應關閉刷新。** 用 API key、Bedrock、Vertex，或訂閱已超出額度、開始扣 usage credits 時，prompt 快取只有 5 分鐘。這時第 55 分鐘的刷新會發現快取早就過期，而且每次刷新都會重寫整段 context。請執行 `/handoff-refresh off`。mod 不會自動偵測 TTL。
- **閒置刷新還沒驗證。** 還不確定 fork 讀取快取時，能不能延長主對話那份 1 小時快取的時效。
- **背景工作只能偵測一部分。** 背景 Bash 的 task id 是從結構化欄位讀的；Workflow 和 Monitor 的 task id 是從工具輸出文字裡抓的，格式還沒驗證。永遠不會結束的工作（例如 dev server）會讓交接一直延後，直到它的紀錄在 12 小時後作廢。需要時可以用 `/handoff-now yes` 強制交接。
- **被攔下的訊息只保留文字。** 離席交接後的第一則訊息如果附了圖片，只會帶上文字。攔下訊息這個行為本身沒有自動測試，因為測試環境模擬不了「使用者親手輸入的訊息」。
- **熱重載會重置**計時器、存檔中狀態和背景工作的追蹤紀錄。
- **API 還在 early access。** Claude Code 更新後可能需要跟著修改。

## 開發

```sh
claude plugin validate .
claude plugin test .
tsc -p .   # mod 載入過一次、產生 .claude-plugin/types/ 之後才能跑
```

## 授權

[MIT](LICENSE)。原作 Copyright (c) 2026 cablate；本改版沿用相同授權。
