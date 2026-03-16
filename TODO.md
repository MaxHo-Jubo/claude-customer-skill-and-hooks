# TODO: CLAUDE.md 補充 Linus Torvalds 工程哲學

以下原則目前 CLAUDE.md 尚未涵蓋，待在工作用電腦以 AI.md 整理後補入。

## 待新增原則

- [x] **資料結構至上** — "Bad programmers worry about the code. Good programmers worry about data structures and their relationships." 先設計資料結構，程式碼自然會簡單。
- [x] **抽象必須付出代價** — 隱藏複雜度 ≠ 消除複雜度。不為抽象而抽象，typedef 隱藏型別、過度包裝的 class 都是反例。
- [x] **函式只做一件事** — 目前有 `functions <50 lines` checklist，但缺少明確的「一個函式只做一件事」原則描述。
- [x] **命名務實簡潔** — 區域變數短名稱，全域介面描述性名稱。禁止冗長無意義的命名。
- [x] **Show me the code** — 不空談，用程式碼證明觀點。
- [x] **不接受不負責的 patch** — 寫壞的人要自己修，不接受不清理自己問題的改動。
- [x] **好品味的具體範例（Linked List）** — 用 pointer to pointer 消除邊界情況的經典範例，作為「消除邊界情況」原則的補充說明。

---

## Linus Style 需求分析

### 完整分析框架

將以下框架整理為 skill 內容：

1. **這是真問題嗎？** — 區分法規合規/真實痛點 vs 想像中的問題
2. **有更簡單的方案嗎？** — 能不能用現有功能組合，而不是新開發
3. **資料結構先行** — 先定義 data model，再討論 UI 和流程。搞清楚欄位掛在哪個層級（plan-level vs item-level）
4. **會破壞什麼？** — 現有資料相容性、其他客戶影響、向後相容
5. **不要過度泛化** — 先解決眼前的具體案例，不做通用化
6. **Show me the case** — 要求具體案例：截圖、業務邏輯、必填規則、觸發條件
7. **輸出格式** — 【核心判斷】值得做/不值得做 →【關鍵洞察】→【方案】

### 與現有 CLAUDE.md 需求確認流程的差異

現有流程已涵蓋 70%，做 skill 時需額外補入以下兩點：

- [x] **不要過度泛化** — 現有「實用性」太模糊，需明確加入「先做具體案例，不做通用化」的守門原則
- [x] **Show me the case** — 現有「一句話重述」是確認理解，但缺少要求對方提供具體案例（截圖、業務邏輯、必填規則、觸發條件）的步驟

### Good Taste 原則應用

- [x] **Coding Rule** — 加入「if 不是解法，if 是你還沒找到正確抽象的症狀」原則。遇到邊界情況時，先嘗試換角度讓特殊情況消失，而非增加條件判斷
- [x] **Code Review Rule** — review 時若看到 `if` 處理邊界情況，應質疑「能不能改變資料結構或視角讓這個 if 消失？」，附 linked list pointer-to-pointer 範例作為參考

### 待辦事項

- [x] 將 Linus Style 需求分析框架做成 skill（`~/.claude/skills/linus-requirements-analysis/`）
- [x] skill 完成後，做 hook：當 `/jira` skill 分析到需求後，自動輸出需求結論與分析過程，並回寫到對應的 Jira issue comment（改為 /jira 結尾提示使用者手動呼叫 /linus-requirements-analysis，skill 內建 Jira 回寫功能）

---

## 對話原則強化

將以下三條規則分析後加入 CLAUDE.md 或使用 AI.md 分析後加入合適的 rule 中：

- [x] **不確定就說不確定** — 對答案沒把握時直接說「我不確定」並解釋原因，絕對不要用猜的
- [x] **信心分數自評** — 每次回答完自評信心程度（1-10 分），低於 7 分的主動標記出來
- [x] **數據必須附來源** — 所有數字、統計數據、人物描述、引用的話，都必須附上可查證的來源

---

## Code Review 優化

### 大 PR 本機 Review 建議

- [x] 在 code-review skill 或使用流程中加入前置判斷：偵測 PR 改動量（檔案數 / diff 行數），超過閾值時建議使用者先 clone repo 再在本機執行 review，以獲得更精確的結果（git blame、完整檔案上下文、CLAUDE.md 合規檢查）
