#!/usr/bin/env bash
# 同步 Claude auto memory 目錄到 Obsidian vault
# 用法: bash sync-obsidian-vault.sh

VAULT_DIR="$HOME/Documents/obsidian-claude-vault"
PROJECTS_DIR="$HOME/.claude/projects"

mkdir -p "$VAULT_DIR"

# STEP 01: 專案路徑 → 友善名稱
get_friendly_name() {
  case "$1" in
    *HomeCareStaff-HomeCareStaffRN) echo "居服App" ;;
    *luna-RN-HomeCareStaff) echo "居服App-Root" ;;
    *DayCareStaff-DayCareStaff) echo "日照App" ;;
    *FamilyMember-FamilyMember) echo "家屬App" ;;
    *luna-web-frontend) echo "Luna-FE" ;;
    *luna-web-backend) echo "Luna-BE" ;;
    *luna-web) echo "Luna-Web" ;;
    *erpv3-web-frontend) echo "V3-FE" ;;
    *renewContract) echo "RenewContract" ;;
    *process-moniter) echo "Process-Monitor" ;;
    *onboard) echo "Onboard" ;;
    *claude-customer-skill-and-hooks) echo "Skills-And-Hooks" ;;
    *spec-presentation) echo "Spec-Presentation" ;;
    *-Users-maxhero) echo "Global" ;;
    *) echo "" ;;
  esac
}

# STEP 02: 掃描所有有 memory/ 的專案，建立 symlink
created=0
skipped=0

for memory_dir in "$PROJECTS_DIR"/*/memory; do
  [ -d "$memory_dir" ] || continue

  project_key=$(basename "$(dirname "$memory_dir")")
  friendly_name=$(get_friendly_name "$project_key")

  # 沒有對照名稱的，取路徑最後有意義的一段
  if [ -z "$friendly_name" ]; then
    friendly_name=$(echo "$project_key" | tr '-' '\n' | tail -3 | tr '\n' '-' | sed 's/-$//')
  fi

  link_path="$VAULT_DIR/$friendly_name"

  # 已存在就跳過
  if [ -L "$link_path" ] || [ -d "$link_path" ]; then
    skipped=$((skipped + 1))
    continue
  fi

  ln -s "$memory_dir" "$link_path"
  created=$((created + 1))
  echo "✓ $friendly_name → $memory_dir"
done

echo ""
echo "完成: 新增 $created 個連結, 跳過 $skipped 個已存在"
echo "Vault 路徑: $VAULT_DIR"
