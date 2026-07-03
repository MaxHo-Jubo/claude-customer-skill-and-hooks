# Harness 制度目錄 | 索引與讀取順序

> 本目錄是這台機器的開發 Harness（工作流防閉環迭代機制）制度中心。
> 由 Fable 5 於 2026-07-03 建立，供後續模型（Sonnet / Opus / Haiku）長期沿用。
> 全域 `~/.claude/CLAUDE.md` 是路由中心，指向本目錄各檔。

## 檔案清單與讀取時機

| 檔案 | 用途 | 何時讀 |
|------|------|--------|
| [harness-diagnosis.md](harness-diagnosis.md) | Harness 漏水診斷書：三大痛點 + 物理級阻斷方案 + 能力極限誠實條款 | 想理解「為什麼制度長這樣」時 |
| [model-dispatch.md](model-dispatch.md) | 模型調度與動態升降級守則：指揮官不下場、派工三件套、升降級路徑、隔離驗證 | 每次要 spawn subagent 前 |
| [judgment-matrix.md](judgment-matrix.md) | 判斷力外化矩陣：換路徑信號、完成判準、熔斷條件（每條附正例/反例） | 卡關時、宣告完成前、想問 user 前 |
| [delegation-templates.md](delegation-templates.md) | 標準化派工 Prompt 模板：搜尋研究 / 功能實作 / 代碼重構 / 代碼審查 / 隔離驗收 / 失敗升級 | 派工時直接複製填空 |
| [commit-review-policy.md](commit-review-policy.md) | Commit 後審查分級制（Tier 0~3，取代舊「強制五步」） | 每次 git commit 成功後 |
| [knowledge-protocol.md](knowledge-protocol.md) | 知識迭代與反思協議：哪些檔可自改、踩坑格式、精簡觸發條件 | 被糾正時、想改 harness 檔案時 |
| [handover-letter.md](handover-letter.md) | Fable 5 給未來 session 的交接信：三件關鍵事 + 制度腐化預防 | 新 session 接手大型任務前 |

## 維護規則（摘要，完整版見 knowledge-protocol.md）

- 本目錄檔案的「修改權限分級」定義在 knowledge-protocol.md，動手前先讀。
- 修改任何既有檔案前先建 `.bak` 副本。
- 除本 README 外，每檔頂部有 `status:` 欄位：`SKELETON`（僅結構）→ `DONE`（內容完整）。若看到 SKELETON，代表建立它的 session 中斷了，依該檔內的節次說明補完。
