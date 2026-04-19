# Opus 4.7 CLAUDE.md 遷移建議驗證報告

驗證日期：2026-04-17
驗證對象：討論群組流傳的「4.6 時代的 CLAUDE.md 規則哪些可以砍」文章
驗證依據：Anthropic 官方文件（platform.claude.com、claude.com/blog、anthropic.com/news）

---

## 【核心判斷】🔴 這篇文章不要信

文章論點：「4.7 RLHF 覆蓋 99%+，CLAUDE.md 重複規則反而打架，應該大砍通用提醒」。

官方實際說法：4.7 **更字面化地執行指令**，**不會從一個項目推論到另一個**，**不會推論你沒提的需求**。砍掉規則=失去規則，不是「反而更好」。

**方向剛好反了。**

---

## 逐項對照表

| 文章論點 | 官方實際說法 | 判決 |
|---|---|---|
| 4.7 已 RLHF 壓過「溝通風格」，CLAUDE.md 不用再寫 | 官方反而建議「用正面範例寫你要的聲音，比負面『Don't do this』有效」— 是要**改寫法**，不是**刪掉** | ❌ 錯 |
| 不諂媚 / no sycophancy 可砍（RLHF 專門壓過） | 4.7 sycophancy 分數「與 4.6 相似」，不是顯著改善，沒有「RLHF 專門壓過」這回事 | ❌ 錯 |
| 4.7 hallucination rate 顯著低於 4.6 | 官方：input hallucination（請求不存在的工具）最低；**factual hallucination 僅「better than or on par with 4.6」，還輸給 Mythos Preview** | ⚠️ 誇大 |
| 4.7 主動標註不確定性 | 官方沒有這個承諾 | ❌ 無來源 |
| 重複規則會「跟其他 MD 區塊打架」 | 官方直接打臉：「**更字面化，不會 silently generalize，不會 infer 你沒提的需求**」。規則越明確越好 | ❌ 錯反 |
| Response length 不用寫 | 官方：「**如果你的使用情境依賴特定長度或風格，明確寫在 prompt 裡**」 | ❌ 錯 |
| Claude Code harness 已強制 Read-before-Edit、不亂 grep | 這部分**對**，屬 harness 層 | ✅ 對 |
| Security（XSS/SQL injection 等）可砍 | 官方沒說。4.7 **加了** cybersecurity safeguards 但那是外部拒絕層，不是「內建懂怎麼寫安全程式」 | ❌ 無來源 |
| 「不要編 context 藉口」可砍 | 官方沒說 | ❌ 無來源 |
| 「不捏造、不猜、不誇大」可砍 | 官方只說 input hallucination 顯著改善；factual 僅略好 | ❌ 部分錯 |
| <gates> SCOPE 區段基本可全砍 | 官方沒有這個建議，反而強調「first turn 就把 task 講清楚」需要完整 context | ❌ 錯 |

---

## 官方真正建議刪的東西（文章完全沒提到）

### 1. 自我檢查類 scaffolding
官方原文：
> If existing prompts have mitigations in these areas (e.g. "double-check the slide layout before returning"), try removing that scaffolding and re-baselining.

原因：4.7 在 knowledge work（.docx redlining、.pptx editing、charts analysis）會自己 visually verify outputs。

### 2. 過於詳細的逐步引導
官方原文：
> it's helpful to treat Claude more like a capable engineer you're delegating to than a pair programmer you're guiding line by line

原因：4.7 在互動式 session 裡會 reason more after user turns，但 ambiguous prompts conveyed progressively 反而降低品質。

### 3. Subagent 行為需要更明確
官方原文：
> It spawns fewer subagents by default... If your use case benefits from parallel subagents... we recommend spelling that out.

範例（官方提供）：
> Do not spawn a subagent for work you can complete directly in a single response (e.g., refactoring a function you can already see). Spawn multiple subagents in the same turn when fanning out across items or reading multiple files.

---

## 官方 Behavior Changes 完整清單

來源：https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7

> These are not API breaking changes but may require prompt updates.
>
> - **More literal instruction following**, particularly at lower effort levels. The model will not silently generalize an instruction from one item to another, and will not infer requests you didn't make.
> - **Response length calibrates to perceived task complexity** rather than defaulting to a fixed verbosity.
> - **Fewer tool calls by default,** using reasoning more. Raising effort increases tool usage.

---

## 結論

### 1. CLAUDE.md 規則不要砍

- 4.7 字面執行指令，規則寫越明確越有效
- 砍掉 = 失去執行保證，不是「反而不打架」

### 2. 要改的是「寫法」不是「刪除」

- 負面禁令（Don't do X）→ 改寫正面範例（The voice I want is: ...）
- 具體範例 > 抽象原則

### 3. 文章唯一對的部分

- Claude Code harness 強制的規則（Read-before-Edit、禁用 find/grep/cat、不編造 file path）確實可以從 CLAUDE.md 砍掉，因為 harness 層已保證

### 4. 文章完全漏掉的重點

- 4.7 互動模式會用更多 token（reason more after user turns）→ 要在 first turn 給足 context
- 4.7 預設 effort level 是 xhigh（新增於 high 和 max 之間）
- 4.7 少 spawn subagents → 需要平行時要明確指示
- 4.7 response length 不再固定 verbose → 需要特定格式要寫清楚

### 5. 建議做法

不要大砍 CLAUDE.md。改做：
1. 把負面禁令改寫成正面範例
2. 移除自我檢查 scaffolding（"double-check X before returning"）
3. 移除 harness 已保證的低層 tool use 規則
4. 保留所有業務規則、commit 格式、專案路徑、coding style、security checklist

**信心：9/10**（基於官方文件直接佐證，僅「廣泛的 user 測試報告」這部分未取得）

---

## Sources

- [What's new in Claude Opus 4.7](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7)
- [Best practices for using Claude Opus 4.7 with Claude Code](https://claude.com/blog/best-practices-for-using-claude-opus-4-7-with-claude-code)
- [Introducing Claude Opus 4.7](https://www.anthropic.com/news/claude-opus-4-7)
