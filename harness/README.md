# Harness 制度目錄 | 索引與讀取順序

> 本目錄是這台機器的開發 Harness（工作流防閉環迭代機制）制度中心。
> 制度架構由 Fable 5 於 2026-07-03 在 M4 Pro 機器建立，同日由 Sonnet 5 本機化移植到本機（React Native / Web 開發機）。
> 全域 `~/.claude/CLAUDE.md` 是路由中心，指向本目錄各檔。

## 檔案清單與讀取時機

| 檔案 | 用途 | 何時讀 |
|------|------|--------|
| [model-dispatch.md](model-dispatch.md) | 模型調度與動態升降級守則：指揮官不下場、派工三件套、升降級路徑、隔離驗證、本機工具鏈守則 | 每次要 spawn subagent 前；用搜尋/追蹤工具前 |
| [judgment-matrix.md](judgment-matrix.md) | 判斷力外化矩陣：換路徑信號、完成判準、熔斷條件（每條附正例/反例） | 卡關時、宣告完成前、想問 user 前 |
| [delegation-templates.md](delegation-templates.md) | 標準化派工 Prompt 模板：搜尋研究 / 功能實作 / 代碼重構 / 代碼審查 / 隔離驗收 / 失敗升級 | 派工時直接複製填空 |
| [commit-review-policy.md](commit-review-policy.md) | Commit 後審查分級制（Tier 0~3，取代舊「強制六步」） | 每次 git commit 成功後 |
| [knowledge-protocol.md](knowledge-protocol.md) | 知識迭代與反思協議：哪些檔可自改、踩坑格式、精簡觸發條件 | 被糾正時、想改 harness 檔案時 |
| [harness-diagnosis.md](harness-diagnosis.md) | 本機漏水診斷書：session 注入稅實測、claude-mem/context-mode 去留評估、壞引用清單（機器專屬，不隨 sync 移植） | 質疑注入成本、評估 plugin 去留、清理死引用時 |

> 本機漏水診斷已於 2026-07-03 執行（Fable 5，三路唯讀審計 subagent：全域設定 / 專案層 / 記憶與外掛生態），方法論沿用 repo `max-m4pro-setting` 分支的 M4 版本。`handover-letter.md` 為 M4 機器專屬，本機無對應檔。

## 維護規則（摘要，完整版見 knowledge-protocol.md）

- 本目錄檔案的「修改權限分級」定義在 knowledge-protocol.md，動手前先讀。
- 修改任何既有檔案前先建 `.bak` 副本。
- 除本 README 外，每檔頂部有 `status:` 欄位：`SKELETON`（僅結構）→ `DONE`（內容完整）。若看到 SKELETON，代表建立它的 session 中斷了，依該檔內的節次說明補完。
