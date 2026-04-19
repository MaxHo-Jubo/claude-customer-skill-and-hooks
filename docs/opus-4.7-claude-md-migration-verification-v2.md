# Claude Opus 4.7 遷移驗證報告 v2

**驗證日期**：2026-04-17
**驗證對象**：討論群組文章關於「4.6 時代提示詞可以從 CLAUDE.md 移除」的聲明
**信心度**：8/10

---

## 整體判斷

**🟡 部分正確，但有誇大與不精準之處**

文章主軸（4.7 強化指令遵循、可移除部分腳手架）方向正確，與 Anthropic 官方建議一致，但對 hallucination 與 sycophancy 改善程度有過度推論。

---

## ✅ 正確的聲明

### 1. 「移除 scaffolding 提示詞」是官方建議

官方 [What's new in Claude Opus 4.7](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7) 明確寫：

> "If existing prompts have mitigations in these areas (e.g. 'double-check the slide layout before returning'), try removing that scaffolding and re-baselining."

> "If you've added scaffolding to force interim status messages, try removing it."

### 2. 「更字面化的指令遵循」屬實

官方原文：
> "More literal instruction following... will not silently generalize an instruction from one item to another, and will not infer requests you didn't make."

這支持文章「4.7 嚴格執行所有規則」的說法。

### 3. 「回應長度依任務複雜度自適應」屬實

官方：
> "Response length calibrates to perceived task complexity rather than defaulting to a fixed verbosity."

### 4. 「預設較少工具呼叫與子代理」屬實

官方明確說：
- "Fewer tool calls by default, using reasoning more"
- "Fewer subagents spawned by default"

---

## 🔴 有問題的聲明

### 1. 「hallucination rate 顯著低於 4.6」—— 部分誤導

**事實分布**：
- ✅ 系統卡記錄整體幻覺率下降約 20%
- ✅ 輸入幻覺（user 要求不存在工具時）4.7 是所有測試模型中最低
- ❌ 但「基於虛構事實的問題」上，4.7 與 4.6 持平，並未領先

**問題**：文章「4.7 敢說『不確定』」的具體機制無官方驗證來源，屬於推論而非事實。

### 2. 「不諂媚 RLHF 專門壓過」—— 過度樂觀

[The Decoder 報告](https://the-decoder.com/anthropics-claude-opus-4-7-makes-a-big-leap-in-coding-while-deliberately-scaling-back-cyber-capabilities/)：
> "4.7 安全 profile 與 4.6『相似』，諂媚等行為 rates 維持低"

不是「進一步壓過」，是「持平」。文章誇大了改善幅度。

### 3. 「對 Claude Code tool use 嚴格 → 通用提醒可全砍」—— 過度推論

官方未保證 Read-before-Edit、不 hallucinate path 等紀律是 4.7 內建。
- ✅ Claude Code harness 強制是事實
- ❌ 但這跟模型版本無關，4.6 時代就已強制
- 文章把 harness 行為歸功於 4.7 模型訓練，邏輯上不成立

---

## 💡 實務遷移建議

### 可實驗性移除（官方點名或合理推論）

1. ❌ 「請 double-check / 自我驗證」類腳手架
2. ❌ 強制「請每隔 N 步報告進度」類指令
3. ❌ 「不要 sycophantic」類提醒（已被訓練覆蓋）
4. ❌ 「不要 Great question 開場」類否定提醒
5. ❌ SessionStart hook 重複 CLAUDE.md 既有內容（如「5 個默念」「禁語清單」）

### 必須保留

1. ✅ 領域特定觸發（如 tkman「grep 上下游」、專案特定 FeaturePath 規則）
2. ✅ 需要更多工具/子代理的場景需明確說明（4.7 預設較少，要主動覆蓋）
3. ✅ 事實引用要求（4.7 在虛構事實題上仍會失誤）
4. ✅ COMMIT-MSG、CODE-STYLE 等格式規範（與模型行為無關，是專案規約）
5. ✅ 安全檢查清單（pre-commit mandatory checklist）
6. ✅ GATE-1/GATE-2 流程閘門（4.7 字面化遵循反而更需要明確 trigger）

### 本專案 CLAUDE.md 影響評估

| 區塊 | 建議 | 理由 |
|------|------|------|
| `<conn>` 連線資料 | 保留 | 事實資料，禁止壓縮 |
| `GATE-1` 需求確認 | 保留 | 流程性質，4.7 字面化遵循需要明確 trigger |
| `GATE-2` Plan Mode | 保留 | 同上 |
| `PERSONA: no-sycophancy` | **可移除** | RLHF 已覆蓋 |
| `PERSONA: no-hype` | 保留 | 仍有具體價值，4.7 對誇大表述未必自律 |
| `PERSONA: confidence` | 保留 | 自評信心是工程紀律，非預設行為 |
| `LANG` 區塊 | 保留 | 語言偏好需明確指定 |
| `CORE-PRINCIPLES` | 保留 | 工程哲學，與模型版本無關 |
| `COMMIT-MSG` | 保留 | 專案規約 |
| `CODE-STYLE` | 保留 | 專案規約 |
| `BACKEND-TEST` | 保留 | 工程紀律 |
| `LEARNING` 區塊 | 保留 | 跨 session memory 機制 |
| `POST-COMMIT-REVIEW` | 保留 | 5 步驟流程，4.7 字面化遵循反而更可靠 |

### 建議遷移做法

1. 先留著現有 CLAUDE.md 不動
2. 逐項移除腳手架後 A/B 測試行為
3. 優先移除官方明確點名的（double-check、interim status、no-sycophancy）
4. 觀察一週後再決定下一批

---

## 參考來源

- [What's new in Claude Opus 4.7 - Anthropic Docs](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7)
- [Claude Opus 4.7 makes a big leap in coding - The Decoder](https://the-decoder.com/anthropics-claude-opus-4-7-makes-a-big-leap-in-coding-while-deliberately-scaling-back-cyber-capabilities/)
- [Claude Opus 4.7 Benchmarks Explained - Vellum AI](https://www.vellum.ai/blog/claude-opus-4-7-benchmarks-explained)
- [Introducing Claude Opus 4.7 - Anthropic](https://www.anthropic.com/news/claude-opus-4-7)
- [Best practices for using Claude Opus 4.7 with Claude Code](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7)

---

## 與既有 v1 報告差異

v1 報告（`opus-4.7-claude-md-migration-verification.md`）聚焦於官方文件搜尋結果與翻譯整理。v2 報告新增：
- 對討論群組文章具體聲明的逐項真偽判斷
- 本專案 CLAUDE.md 各區塊的影響評估表
- 分階段遷移建議與優先順序
