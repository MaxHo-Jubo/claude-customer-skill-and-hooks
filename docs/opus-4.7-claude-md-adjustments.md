# Claude Opus 4.7 — `~/.claude/CLAUDE.md` 增減建議

**分析日期**：2026-04-17
**對象檔案**：`~/.claude/CLAUDE.md`
**判斷依據**：[v2 驗證報告](./opus-4.7-claude-md-migration-verification-v2.md) + Anthropic 官方 4.7 行為變更
**信心度**：7/10（建議實驗性逐項調整，非一次砍多條）

---

## 摘要

| 類別 | 數量 | 說明 |
|------|------|------|
| 🔴 建議移除 | 1 | RLHF 已覆蓋的提醒 |
| 🟡 建議精簡 | 4 | 文字過長或重複 4.7 預設行為 |
| 🟢 必須保留 | 大部分 | 專案規約、流程閘門、領域邏輯 |
| ➕ 建議新增 | 2 | 因 4.7 行為變化需主動覆蓋的指令 |

---

## 🔴 建議移除（共 1 項）

### 1. `PERSONA: no-sycophancy`（line 63）

**現有內容**：
```yaml
no-sycophancy: 不用「你說得對！」開頭；要改方向就直接改，不需要先肯定對方
```

**移除理由**：
- Anthropic 官方系統卡確認 4.7 諂媚行為率持續低水準（與 4.6 持平偏低）
- RLHF 已覆蓋此類開場行為
- 4.7 預設「more direct, opinionated tone with less validation-forward phrasing」

**風險**：低。若移除後發現模型仍有諂媚開場，再加回。

**驗證方法**：移除後跑 5-10 個對話，觀察是否出現「你說得對！」「Great question」類開場。

---

## 🟡 建議精簡（共 4 項）

### 1. `PERSONA: tone`（line 58）

**現有內容**：
```yaml
tone: 直接/犀利/零廢話，簡潔回覆，不加解釋，除非我問「為什麼」，回覆不超過 5 行，除非任務本身需要：
```

**問題**：
- 「簡潔回覆」「回覆不超過 5 行」屬於 4.7 預設行為（response length calibrates to task complexity）
- 句尾冒號是 typo
- 「不加解釋，除非我問為什麼」與「除非任務本身需要」邏輯重疊

**建議改為**：
```yaml
tone: 直接/犀利/零廢話；任務不需要解釋就不解釋
```

**理由**：4.7 已會根據複雜度自動調整長度，不需要明確指定行數。

---

### 2. `GATE-1` 第 1 步「自問」（line 35）

**現有內容**：
```yaml
1. 自問「真問題？更簡方案？會破壞什麼？」
```

**問題**：
- 「自問」是內部反思腳手架，4.7 在 reasoning 階段會自然執行
- 屬於官方點名的 "scaffolding to force interim status messages" 類型

**建議**：保留但觀察。如果 4.7 在 GATE-1 觸發時已自然展現分析過程，可移除此步驟。

**理由**：GATE-1 整體流程要保留（領域 trigger），但內部「自問」步驟可能多餘。

---

### 3. `CORE-PRINCIPLES` 引用範例過長（line 78-80）

**現有內容**：
```yaml
taste: 消除邊界情況 > 增加條件判斷；重寫讓特殊情況消失；if 不是解法，if 是你還沒找到正確抽象的症狀（經典範例：linked list 用 pointer-to-pointer 消除 head 邊界情況）
data-struct-first: 先設計資料結構，程式碼自然簡單；"Bad programmers worry about the code. Good programmers worry about data structures and their relationships."
no-gratuitous-abstraction: 隱藏複雜度 ≠ 消除複雜度；不為抽象而抽象；typedef 藏型別、過度包裝的 class 都是反例
```

**問題**：每條引用範例佔 token 多。4.7 字面化遵循下，原則本身已足夠，範例可移到 `memory/anti-patterns.md`。

**建議改為**：
```yaml
taste: 消除邊界情況 > 增加條件判斷；if 是抽象未到位的症狀
data-struct-first: 資料結構優先於程式碼
no-gratuitous-abstraction: 不為抽象而抽象
```

**理由**：節省 token，範例移到 ref 檔案 on-demand 載入。

---

### 4. `LEARNING: on-session-start`（line 164）

**現有內容**：
```yaml
on-session-start: 讀取相關 feedback/user memories，避免重複犯錯
```

**問題**：
- SessionStart hook 已自動注入 memory（看 hook 設定）
- 重複規則 4.7 會嚴格執行，可能變成 hook + 規則雙重觸發

**建議**：確認 SessionStart hook 已包含 memory 載入後，移除此規則。

---

## 🟢 必須保留（不要動）

### 高度信賴項目

| 區塊 | 行數 | 保留理由 |
|------|------|----------|
| `<conn>` 連線資料 | 3-28 | 事實資料，明確標註禁止壓縮 |
| `GATE-1` trigger 與 action 主體 | 30-43 | 領域 trigger，4.7 字面化遵循需要明確流程 |
| `GATE-2` Plan Mode | 45-50 | 同上 |
| `PERSONA: integrity/criticism/no-hype/uncertainty/confidence/cite-source` | 60-68 | 工程紀律，非預設行為 |
| `LANG` 區塊 | 70-75 | 語言偏好需明確指定 |
| `CORE-PRINCIPLES` 原則本身 | 77-84 | 工程哲學 |
| `CODE-REVIEW-OUTPUT` | 86-93 | 輸出格式規約 |
| `COMMIT-MSG` | 95-106 | 專案規約，極其具體 |
| `CODE-STYLE` | 108-127 | 專案規約 + step-comments 編碼系統 |
| `BACKEND-TEST` | 140-144 | 工程紀律 |
| `TASK-MGMT` | 146-153 | 流程規約 |
| `LEARNING` 主體 | 160-167 | Memory 持久化機制 |
| `POST-COMMIT-REVIEW` | 181-195 | 5 步驟 mandatory 流程 |
| `<compact>` PRESERVE | 199-208 | 壓縮優先序 |
| `<ref>` 區塊 | 210-223 | 模組化載入索引 |

### 關鍵觀察

**4.7 字面化遵循反而強化了這些區塊的價值**：
- 「mandatory 五步驟」會被嚴格執行
- 「skip-when」條件會被精準判讀
- POST-COMMIT-REVIEW 的可靠性提升

---

## ➕ 建議新增（共 2 項）

### 1. `SUBAGENT-USAGE`（覆蓋 4.7 預設行為）

**理由**：4.7 「Fewer subagents spawned by default」，若你的工作流仰賴 subagent 平行處理，需主動指示。

**建議加入位置**：`<rhythm>` 區塊內

**內容**：
```yaml
SUBAGENT-USAGE:
  trigger: 多檔案探索 | 平行 review | 跨模組分析
  action: 主動 dispatch 多個 subagent，不要單線完成
  rationale: 4.7 預設較少 spawn，需明確指示
  exception: 單檔修改 | 簡單查詢 → 直接做
```

---

### 2. `TOOL-USAGE: aggressive-search`（依需求加）

**理由**：4.7 「fewer tool calls by default, using reasoning more」。若你常需要模型主動 grep/search 確認假設，需明確指示。

**建議加入位置**：`<rhythm>` 區塊內

**內容**：
```yaml
TOOL-USAGE:
  search-first: 涉及既有程式碼修改前，先 grep/Read 確認使用點，不要憑記憶
  rationale: 4.7 預設依賴 reasoning 較少呼叫工具，需明確要求
```

**注意**：你既有 `CODE-STYLE.global-mutation` 已涵蓋部分，可考慮整併。

---

## 📋 建議實施順序

### 第 1 週（風險最低）
1. ✅ 移除 `no-sycophancy`（line 63）
2. ✅ 修正 `tone` 句尾 typo + 精簡

### 第 2 週（觀察一週後）
3. ✅ 視情況精簡 `CORE-PRINCIPLES` 範例
4. ✅ 確認 SessionStart hook 後移除 `on-session-start`

### 第 3 週（依實際使用情況）
5. ✅ 新增 `SUBAGENT-USAGE`（如果你常用 subagent）
6. ✅ 新增 `TOOL-USAGE`（如果發現 4.7 不主動 grep）

### 不建議的做法
- ❌ 一次砍多條，無法定位 regression 來源
- ❌ 不做行為觀察就刪除
- ❌ 移除 `<conn>`、`GATE-1/2`、`COMMIT-MSG`、`CODE-STYLE`、`POST-COMMIT-REVIEW` 主體

---

## ⚠️ 重要前提

本建議基於：
1. Anthropic 官方 [What's new in Claude Opus 4.7](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7)
2. 系統卡公布的行為變化
3. 對你 CLAUDE.md 的純文件分析

**未驗證的部分**：
- 未實際對你的 CLAUDE.md 執行 A/B 測試
- 未跑過 regression 對比
- 「移除後行為不變差」是推論，不是實證

**建議做法**：每改一條就跑 5-10 個典型對話觀察，發現 regression 立刻復原並記錄到 feedback memory。

---

## 參考來源

- [v2 驗證報告](./opus-4.7-claude-md-migration-verification-v2.md)
- [What's new in Claude Opus 4.7 - Anthropic Docs](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7)
- [Claude Opus 4.7 makes a big leap in coding - The Decoder](https://the-decoder.com/anthropics-claude-opus-4-7-makes-a-big-leap-in-coding-while-deliberately-scaling-back-cyber-capabilities/)
