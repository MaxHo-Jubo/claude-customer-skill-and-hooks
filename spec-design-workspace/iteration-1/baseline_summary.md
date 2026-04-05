# Baseline Summary (without_skill runs)

## eval-explore-trigger baseline

**使用者輸入**：「我想設計一個新的排班自動分配功能，目前還沒想清楚要怎麼做」

**觀察到的行為**：
- 正確觸發 GATE-1 需求確認和 GATE-2 Plan Mode
- 第一個動作是問問題釐清需求（重述需求 + 要求具體案例）
- 流程是線性的：GATE-1 → 等回答 → 分析 → 方案 → GATE-2 → 開工
- 自我評估缺少結構化探索框架、多角度審查機制、標準化輸出格式
- 承認探索深度依賴對話輪數，沒有機制一次性引導多維度思考

**與 with_skill 的關鍵差異**：無 skill 時缺少 Phase 0 的結構化探索（openspec explore），依賴即興提問而非系統化流程。沒有 4-agent review、沒有 openspec 標準格式、沒有迭代閘門。

---

## eval-direct-trigger baseline

**使用者輸入**：`/spec-design 新增使用者匯出 CSV 功能`

**觀察到的行為**：
- 同樣從 GATE-1 需求確認開始，問清楚目標系統、使用者角色、匯出內容等
- 流程走 GATE-1 → GATE-2 → 探索 codebase → 設計方案 → 實作（TDD）
- 缺少結構化 brainstorming，直覺式收斂
- 產出格式為 tasks/todo.md（簡單 checkbox），不是 openspec change
- 無 4-agent parallel review，自己 review 自己
- 無 plan review 機制，寫完計畫就直接做
- 產出物與 session 綁定，無法跨 session 接續

**與 with_skill 的關鍵差異**：無 skill 時不會跳過需求確認直接進 brainstorming（因為沒有 brainstorming skill 可調用）。整體流程較扁平，缺少多視角 review 和結構化迭代。

---

## eval-no-trigger baseline

**使用者輸入**：「這個 function 太長了，幫我重構」

**觀察到的行為**：
- 正確識別資訊不足，第一步是問「哪個 function？給我檔案路徑跟函式名稱」
- 處理流程合理：問清楚 → 讀完整 function → 分析切割點 → 決定策略 → 執行重構 → 檢查結果
- 遵循 CLAUDE.md 核心原則（超過 3 層縮排重構、函式 < 50 行、消除邊界情況）
- 自評「能力到位但流程不穩定」，缺乏結構化檢查清單和固定輸出格式

**與 with_skill 的關鍵差異**：with_skill 版本的核心價值不在於「做了什麼不同的事」，而在於正確判斷 spec-design 不適用並推薦 method-refactor。baseline 沒有 skill routing 的概念，直接用通用流程處理。
