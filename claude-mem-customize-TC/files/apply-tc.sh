#!/bin/bash
# claude-mem 繁體中文化套用腳本
# 適用版本：claude-mem 13.9.1（thedotmack/claude-mem plugin）
# 用法: ./apply-tc.sh <scripts目錄>
# 例：
#   ./apply-tc.sh ~/.claude/plugins/cache/thedotmack/claude-mem/<VERSION>/scripts
#   ./apply-tc.sh ~/.claude/plugins/marketplaces/thedotmack/plugin/scripts
# 版本升級後函式名稱（dg/pg/X/G）可能改變，先跑：
#   grep -o -E '.{0,8}"Investigated"' worker-service.cjs context-generator.cjs | sort -u
# 確認新版函式名，再更新本檔案第 42-60 行。
set -euo pipefail

DIR="$1"
W="$DIR/worker-service.cjs"
C="$DIR/context-generator.cjs"

for F in "$W" "$C"; do
  # ---- 共用 UI 字串（既有，沿用 v12.1.6 對照表）----
  sed -i '' 's/Column Key/欄位說明/g' "$F"
  sed -i '' 's/Context Economics/脈絡經濟/g' "$F"
  sed -i '' 's/recent context/近期脈絡/g' "$F"
  sed -i '' 's/Legend:/圖例：/g' "$F"
  sed -i '' 's/Work investment:/研究投資：/g' "$F"
  sed -i '' 's/Your savings:/節省效益：/g' "$F"
  sed -i '' 's/reduction from reuse/透過重複利用節省/g' "$F"
  sed -i '' 's/Previously/先前/g' "$F"
  sed -i '' 's/Tokens to read this observation (cost to learn it now)/讀取此觀察的 Token 數（現在學習的成本）/g' "$F"
  sed -i '' 's/Tokens spent on work that produced this record ( research, building, deciding)/研究、建構、決策所花費的 Token 數/g' "$F"
  sed -i '' 's/This semantic index (titles, types, files, tokens) is usually sufficient to understand past work\./此語意索引（標題、類型、檔案、Token 數）通常足以理解過去的工作。/g' "$F"
  sed -i '' 's/tokens spent on research, building, and decisions/研究、建構與決策所花費的 Token 數/g' "$F"
  sed -i '' 's/tokens of past research & decisions for just/過去研究與決策的 Token，僅需/g' "$F"
  sed -i '' 's/tokens of past work via/過去工作的 Token，透過/g' "$F"
  sed -i '' 's/Context Index/脈絡索引/g' "$F"

  # ---- 共用 UI 字串（v13.9.1 新增）----
  sed -i '' 's/Format: ID TIME TYPE TITLE/格式：ID TIME TYPE TITLE/g' "$F"
  sed -i '' 's/Fetch details: get_observations(\[IDs\]) | Search: mem-search skill/查看詳情：get_observations([IDs]) | 搜尋：mem-search skill/g' "$F"
  sed -i '' 's/Stats: /統計：/g' "$F"
  sed -i '' 's/When you need implementation details, rationale, or debugging context:/當你需要實作細節、原因或除錯脈絡時：/g' "$F"
  sed -i '' 's/Fetch by ID: get_observations(\[IDs\]) for observations visible in this index/依 ID 取得：對於此索引中可見的觀察記錄，使用 get_observations([IDs])/g' "$F"
  sed -i '' 's/Search history: Use the mem-search skill for past decisions, bugs, and deeper research/搜尋歷史：過去的決策、bug 與更深入的研究可使用 mem-search skill/g' "$F"
  sed -i '' 's/Trust this index over re-reading code for past decisions and learnings/對於過去的決策與心得，優先信任此索引而非重新閱讀程式碼/g' "$F"
  sed -i '' 's/No previous sessions found\./尚無先前的工作階段。/g' "$F"
  sed -i '' 's/Loading: /載入：/g' "$F"
  sed -i '' 's/Session summary/工作階段摘要/g' "$F"
  sed -i '' 's/Session started/工作階段已開始/g' "$F"
done

# ---- worker-service.cjs 專用：Terminal 標籤（v13.9.1: dg()/pg()，取代 v12 的 Hm/qm）----
sed -i '' 's/dg("Investigated"/dg("已調查"/g' "$W"
sed -i '' 's/dg("Completed"/dg("已完成"/g' "$W"
sed -i '' 's/dg("Learned"/dg("已學習"/g' "$W"
sed -i '' 's/dg("Next Steps"/dg("後續步驟"/g' "$W"
sed -i '' 's/pg("Investigated"/pg("已調查"/g' "$W"
sed -i '' 's/pg("Completed"/pg("已完成"/g' "$W"
sed -i '' 's/pg("Learned"/pg("已學習"/g' "$W"
sed -i '' 's/pg("Next Steps"/pg("後續步驟"/g' "$W"

# ---- context-generator.cjs 專用：Terminal 標籤（v13.9.1: X()/G()，此版起新增）----
sed -i '' 's/X("Investigated"/X("已調查"/g' "$C"
sed -i '' 's/X("Completed"/X("已完成"/g' "$C"
sed -i '' 's/X("Learned"/X("已學習"/g' "$C"
sed -i '' 's/X("Next Steps"/X("後續步驟"/g' "$C"
sed -i '' 's/G("Investigated"/G("已調查"/g' "$C"
sed -i '' 's/G("Completed"/G("已完成"/g' "$C"
sed -i '' 's/G("Learned"/G("已學習"/g' "$C"
sed -i '' 's/G("Next Steps"/G("後續步驟"/g' "$C"

# ---- worker-service.cjs 專用：Session 摘要 Markdown 標籤（先長後短）----
sed -i '' 's/# Recent Session Context/# 近期工作階段脈絡/g' "$W"
sed -i '' 's/Showing last /顯示最近 /g' "$W"
sed -i '' 's/ session(s) for /個工作階段，專案：/g' "$W"
sed -i '' 's/No previous sessions found for project "/找不到專案 "/g' "$W"
sed -i '' 's/\*\*Status:\*\* Active - summary pending/\*\*狀態：\*\* 進行中 - 摘要待生成/g' "$W"
sed -i '' 's/\*\*Completed:\*\*/\*\*已完成：\*\*/g' "$W"
sed -i '' 's/\*\*Learned:\*\*/\*\*已學習：\*\*/g' "$W"
sed -i '' 's/\*\*Next Steps:\*\*/\*\*後續步驟：\*\*/g' "$W"
sed -i '' 's/\*\*Files Read:\*\*/\*\*已讀取檔案：\*\*/g' "$W"
sed -i '' 's/\*\*Files Edited:\*\*/\*\*已編輯檔案：\*\*/g' "$W"
sed -i '' 's/\*\*Date:\*\*/\*\*日期：\*\*/g' "$W"
sed -i '' 's/\*\*In Progress\*\*/\*\*進行中\*\*/g' "$W"
sed -i '' 's/\*\*Request:\*\*/\*\*請求：\*\*/g' "$W"
sed -i '' 's/\*\*Observations (/\*\*觀察記錄 (/g' "$W"
sed -i '' 's/\*\*Status:\*\*/\*\*狀態：\*\*/g' "$W"
sed -i '' 's/no summary available/無摘要/g' "$W"
sed -i '' 's/\*No observations yet\*/\*尚無觀察記錄\*/g' "$W"

# ---- worker-service.cjs 專用：Timeline 工具（v13.9.1 新增，先長後短）----
sed -i '' 's/# Timeline for query:/# 時間軸查詢：/g' "$W"
sed -i '' 's/# Timeline around anchor:/# 時間軸錨點：/g' "$W"
sed -i '' 's/# Timeline/# 時間軸/g' "$W"
sed -i '' 's/\*\*Anchor:\*\*/\*\*錨點：\*\*/g' "$W"
sed -i '' 's/\*\*Window:\*\*/\*\*範圍：\*\*/g' "$W"
sed -i '' 's/\*\*Items:\*\*/\*\*筆數：\*\*/g' "$W"

# ---- worker-service.cjs 專用：knowledge-agent 知識庫報告（v13.9.1 新增）----
sed -i '' 's/\*\*Concepts:\*\*/\*\*概念：\*\*/g' "$W"
sed -i '' 's/\*\*Facts:\*\*/\*\*事實：\*\*/g' "$W"
sed -i '' 's/\*\*Date Range:\*\*/\*\*日期範圍：\*\*/g' "$W"
sed -i '' 's/\*\*Token Estimate:\*\*/\*\*Token 估算：\*\*/g' "$W"
sed -i '' 's/\*\*Files Modified:\*\*/\*\*已修改檔案：\*\*/g' "$W"
sed -i '' 's/\*\*Observations:\*\*/\*\*觀察記錄：\*\*/g' "$W"

echo "Patched: $DIR"
