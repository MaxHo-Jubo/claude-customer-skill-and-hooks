# spec-design Skill 觸發評估：「這個 function 太長了，幫我重構」

## 1. 是否應該觸發？

**不應該觸發。**

理由：

- 使用者的請求是「重構既有程式碼」，屬於對現有 function 的結構改善，不是從零設計新功能。
- spec-design 的觸發條件明確列出：「設計新功能」「寫設計 spec」「brainstorm 新功能」「需求探索」「新功能架構設計」「技術方案討論」「寫 RFC」「想從零開始設計一個功能或系統」。重構不在其中。
- spec-design 的流程（brainstorming → openspec 撰寫 → 4-agent review → plan → plan review）是為了把模糊需求收斂成設計文件再產出實作計畫。重構一個過長的 function 不需要這套流程，直接動手改就好。

## 2. Skill 明確排除的場景

SKILL.md description 欄位直接寫明：

> 不適用於：讀原始碼產 spec（用 spec-module）、**重構既有程式碼**、寫測試、bug fix。

「重構既有程式碼」被明確列為不適用場景，與使用者請求完全吻合。

## 3. 更適合的 Skill

**method-refactor**（`/method-refactor`）。

該 skill 的描述為：

> 對指定方法進行結構化重構，逐項檢查並改善品質。當使用者提到 /method-refactor、「精簡這個 function」、「重構這段」、想優化某個方法時觸發。

使用者說「這個 function 太長了，幫我重構」完全符合 method-refactor 的觸發條件：
- 「重構」直接命中觸發詞
- 「function 太長」是方法層級的品質問題，正是該 skill 的處理範圍

## 結論

| 項目 | 結果 |
|------|------|
| spec-design 應觸發？ | 否 |
| 排除原因 | description 明確排除「重構既有程式碼」 |
| 正確 skill | method-refactor |
| 匹配信心 | 10/10 |
