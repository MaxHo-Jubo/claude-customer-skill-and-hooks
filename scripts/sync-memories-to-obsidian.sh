#!/bin/bash
# 將所有 Claude Code auto memory 檔案同步到 Obsidian vault
# 用途：方便在 Obsidian 中瀏覽所有專案的記憶檔
# 執行方式：bash scripts/sync-memories-to-obsidian.sh

set -euo pipefail

# STEP 01: 定義路徑
CLAUDE_PROJECTS="$HOME/.claude/projects"
OBSIDIAN_TARGET="$HOME/Documents/obsidian-claude-vault/claude-memories"

# STEP 02: 專案路徑到簡稱的對應表
get_short_name() {
  local proj="$1"
  case "$proj" in
    "-Users-maxhero") echo "_global" ;;
    *claude-customer-skill-and-hooks) echo "skills-hooks" ;;
    *luna-web) echo "luna-web" ;;
    *luna-web-frontend) echo "luna-FE" ;;
    *luna-web-frontend-react-18) echo "luna-FE-r18" ;;
    *luna-web-frontend-spec) echo "luna-FE-spec" ;;
    *luna-web-backend) echo "luna-BE" ;;
    *luna-RN-HomeCareStaff) echo "homecare" ;;
    *HomeCareStaffRN) echo "homecare-RN" ;;
    *luna-RN-DayCareStaff) echo "daycare" ;;
    *DayCareStaff) echo "daycare-app" ;;
    *FamilyMember) echo "family" ;;
    *erpv3-web-frontend) echo "v3-FE" ;;
    *erpv3-web-backend) echo "v3-BE" ;;
    *iCare-2-0-frontend) echo "icare-FE" ;;
    *renewContract) echo "renewContract" ;;
    *pr-watcher-MCP) echo "pr-watcher" ;;
    *pr-watcher) echo "pr-watcher-cli" ;;
    *process-moniter) echo "process-monitor" ;;
    *personal-wiki) echo "personal-wiki" ;;
    *onboard) echo "onboard" ;;
    *spec-presentation) echo "spec-presentation" ;;
    *spec-drift-checker) echo "spec-drift" ;;
    *care-mgt) echo "care-mgt" ;;
    *claude-team-config) echo "team-config" ;;
    *claude-mem-observer*) echo "mem-observer" ;;
    *phpciis) echo "phpciis" ;;
    # 未知專案：取最後一段
    *) echo "$proj" | sed 's/.*-//' ;;
  esac
}

# STEP 03: 建立目標目錄
mkdir -p "$OBSIDIAN_TARGET"

# STEP 04: 統計變數
copied=0
skipped=0

# STEP 05: 掃描並複製
for memory_dir in "$CLAUDE_PROJECTS"/*/memory; do
  [ -d "$memory_dir" ] || continue

  # 取得專案目錄名
  proj=$(basename "$(dirname "$memory_dir")")
  short=$(get_short_name "$proj")

  for md_file in "$memory_dir"/*.md; do
    [ -f "$md_file" ] || continue

    fname=$(basename "$md_file")

    # 跳過 MEMORY.md 索引檔
    if [ "$fname" = "MEMORY.md" ]; then
      skipped=$((skipped + 1))
      continue
    fi

    # 目標檔名：專案簡稱--原檔名
    target="$OBSIDIAN_TARGET/${short}--${fname}"
    cp "$md_file" "$target"
    copied=$((copied + 1))
  done
done

echo "同步完成：複製 $copied 筆，跳過 $skipped 筆 MEMORY.md"
echo "目標：$OBSIDIAN_TARGET"
