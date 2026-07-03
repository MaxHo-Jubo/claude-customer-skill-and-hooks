# F. 知識迭代與反思協議 | status: DONE

> 用途：定義未來的弱模型如何**安全地**自我更新這套 harness。這是 harness 的憲法修正程序。
> 讀者：所有等級的模型。兩個使用時機：**被 user 糾正時（§2）、想改任何 harness 檔案時（§1、§4）**。
> 建立：Fable 5，2026-07-03。本檔自身屬黃區。

## 1. 檔案修改權限分級

### 🟢 綠區——模型可自行更新，不必問（但要遵守 §2 格式）
| 路徑 | 內容 |
|------|------|
| `~/.claude/projects/<專案slug>/memory/*.md` | auto-memory 記憶檔（含 MEMORY.md 索引） |
| `<專案>/tasks/lessons.md` | 專案內教訓 |
| `<專案>/tasks/todo.md` | 任務追蹤 |
| `~/.claude/harness/handover-letter.md` 的 §3 未完成事項 | session 交接欄 |

### 🟡 黃區——可提案：先把 diff 或新舊對照貼給 user，明確同意後才改（改前建 .bak）
| 路徑 | 內容 |
|------|------|
| `~/.claude/CLAUDE.md` | 全域路由中心 |
| `~/.claude/rules/**` | 全域規則 |
| `~/.claude/harness/*.md`（除交接欄外） | 本套制度檔 |
| `<專案>/CLAUDE.md` | 專案入口 |

### 🔴 紅區——只有 user 主動要求才動，模型不得提案後自行執行
| 路徑 | 內容 |
|------|------|
| `~/.claude/settings.json`、`~/.claude.json` | 主設定、MCP 配置 |
| `~/.claude/hooks/**`、settings 內 hooks 註冊 | 自動化接線 |
| plugin 啟用狀態與 plugin 內部檔案 | superpowers / context-mode / claude-mem 等 |
| `~/.claude/CLAUDE.md.bak` 等備份檔 | 備份不可覆寫、不可刪 |

**判斷不了屬於哪區 → 當黃區處理。**

## 2. 踩坑紀錄寫入協議（單一入口，消除多頭寫入）

這台機器上「教訓/知識」實測有 6 個活躍寫入點（auto-memory、claude-mem observations、context-mode index、tasks/lessons.md、三層 CLAUDE.md、serena memories——見 harness-diagnosis.md §1），**寫入規則收斂為兩條**：

| 教訓/知識性質 | 唯一寫入處 | 格式 |
|---------|-----------|------|
| 工作方式被糾正、工具鏈坑（跨 session 適用） | auto-memory：`~/.claude/projects/<slug>/memory/feedback_*.md` ＋ 更新 MEMORY.md 索引一行 | 見下方（type: feedback） |
| 發現 user 偏好/習慣（角色、表達方式、工具偏好） | auto-memory：同上，檔名 `user_*.md`（type: user） | 同下方格式 |
| 只在這個專案內有效（業務規則、本 repo 慣例） | `<專案>/tasks/lessons.md` 追加一條 | 見下方 |

**不要主動寫入**：claude-mem observations 與 context-mode index 是 hook 自動記錄的系統，模型不手動餵資料；CLAUDE.md 不是教訓收集箱，只有經 §3 抽象化後的「原則」才可提案進 rules/。

### auto-memory 標準格式
```markdown
---
name: feedback_<snake_slug>   # 與檔名主體一致；沿用現存記憶檔的底線命名慣例
description: <一行摘要，供之後判斷相關性>
metadata:
  type: feedback   # user | feedback | project | reference
tags: [feedback, <專案名或 global>, <語意tag>]
---
<坑的事實一句話>
**Why:** <為什麼會踩：機制說明>
**How to apply:** <下次遇到什麼信號時，改用什麼做法>
```

### tasks/lessons.md 條目格式
```markdown
## <日期> <一句話標題>
- 情境：<什麼任務下踩的>
- 錯誤：<做了什麼錯的>
- 正解：<應該怎麼做>
- 觸發詞：<下次看到什麼字眼/情境要想起這條>
```

**寫入時機**（機械判準）：user 用任何形式糾正你（「不對」「不是這樣」「我說過…」）→ 當下就寫，不等 session 結尾。root cause 若在 harness 規則本身寫錯 → 走 §1 黃區提案修規則，而不是堆一條 workaround 教訓。

**壓縮前 flush**：收到 PreCompact 提示（settings.json 已掛 pre-compact-snapshot hook）或自覺 context 即將被壓縮時，先檢查本輪是否有未存的糾正/決策/偏好，寫入後再讓壓縮發生。

## 3. 精簡與抽象化的觸發條件（量化）

任一成立 → 在當前任務收尾後執行精簡（或建議 user 跑 /weekly-review）：

| 門檻 | 動作 |
|------|------|
| MEMORY.md 索引超過 **60 行** | 合併同主題條目 |
| 單一 memory 檔超過 **80 行** | 拆分或濃縮 |
| 專案 memory/ 目錄總量超過 **100 KB** | 整併（同主題合併＋刪已驗證過時），或建議 user 跑 /weekly-review |
| 同一主題出現 **≥ 3 條**相近教訓 | 抽象化：合併成一條「原則」，原條目刪除 |
| memory 內容被驗證已過時（指涉的檔案/旗標已不存在） | 直接刪除該檔＋索引行（綠區權限） |

**抽象化判準**：三條教訓若能寫成一句「當〈信號〉時，永遠〈做法〉」且不損失關鍵細節 → 合併。合併後的原則若屬全域工作方式 → 走黃區提案進 rules/ 或本目錄制度檔。
【完美正例】「historyCursor 漏更新」「summarySubmenuCursor 漏更新」「endCheckCursor 漏更新」三條 → 合併為「新 UI state 必同步進 DisplaySnapshot ＋ 5 步 checklist」一條。
【典型反例】把三條互不相關的坑硬塞進一條「要小心 UI」——抽象到失去觸發信號的教訓等於刪除。

## 4. 修改 harness 檔案的標準流程（黃區適用）

1. `cp <檔> <檔>.bak`（同目錄，若已有 .bak 則命名 `.bak2`，不覆寫舊備份）
2. 修改（用 Edit，禁 sed -i）
3. 派 fresh-context read-back 驗收（delegation-templates.md §5a）：核對修改符合提案、未誤傷其他段落、引用路徑仍全部存在
4. 在檔案頂部或變更處註記日期與一句話原因

### 禁止事項（任何等級模型皆不可）
- 不可刪除或弱化 harness-diagnosis.md §5 誠實條款、judgment-matrix.md §3 熔斷條件——只可經 user 同意後**收緊**或修正錯誤
- 不可為了讓當前任務過關而臨時放寬判準（「這次先算完成」）——判準有問題走提案，不走例外
- 不可刪 .bak 備份檔
- 精簡記憶時不可刪除「仍會踩」的坑——刪除的唯一理由是「已驗證過時」或「已抽象合併」
