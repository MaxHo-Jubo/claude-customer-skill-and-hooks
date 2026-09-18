#!/bin/bash
#
# run-migration.sh [env 檔路徑]
#
# 無人看管批次遷移的啟動殼：
#   1. 載入 env 檔（所有設定的唯一來源，內含長效憑證，權限應為 600）
#   2. 切換到指定的 Node 版本（前端建置需要）
#   3. 用 caffeinate 讓機器在批次執行期間不睡眠
#   4. exec 進 runner.py 主迴圈
#
# env 檔路徑優先序：第一個參數 > R15_R18_MIGRATE_ENV > 家目錄下的預設位置。
# 慣例：只有環境變數用大寫，腳本內部變數一律小寫。

set -euo pipefail

# 本腳本所在目錄（用來定位 runner.py，不寫死絕對路徑）
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# runner 主程式
runner_path="$script_dir/runner.py"

# ---------------------------------------------------------------- 載入 env

# 預設 env 檔位置（與說明文件一致）
default_env_path="$HOME/.claude/r15-r18-migrate.env"
env_path="${1:-${R15_R18_MIGRATE_ENV:-$default_env_path}}"

if [ ! -f "$env_path" ]; then
  echo "錯誤：找不到 env 檔 $env_path" >&2
  echo "請複製 templates/r15-r18-migrate.env.example 後填值，並 chmod 600" >&2
  exit 2
fi

# 提醒權限過寬（檔內有長效憑證）
env_mode="$(stat -f '%Lp' "$env_path" 2>/dev/null || stat -c '%a' "$env_path" 2>/dev/null || echo "")"
if [ -n "$env_mode" ] && [ "$env_mode" != "600" ]; then
  echo "警告：$env_path 權限是 $env_mode，建議 chmod 600" >&2
fi

# set -a 讓 env 檔裡的賦值自動 export 給子行程
set -a
# shellcheck source=/dev/null
. "$env_path"
set +a

# ---------------------------------------------------------------- Node 版本

# nvm 的候選安裝位置（刻意不讀 NVM_DIR，讓本腳本讀到的環境變數集合與說明文件一致）
nvm_candidates=(
  "$HOME/.nvm/nvm.sh"
  "/opt/homebrew/opt/nvm/nvm.sh"
  "/usr/local/opt/nvm/nvm.sh"
)
nvm_loaded=0
for candidate in "${nvm_candidates[@]}"; do
  if [ -s "$candidate" ]; then
    # nvm 腳本內有未定義變數的用法，載入期間先關掉嚴格模式
    set +u
    # shellcheck source=/dev/null
    . "$candidate"
    set -u
    nvm_loaded=1
    break
  fi
done

node_version="${NODE_VERSION:-20}"
if [ "$nvm_loaded" -eq 1 ]; then
  set +u
  nvm use "$node_version" >/dev/null || {
    echo "錯誤：nvm use $node_version 失敗，請先安裝該版本" >&2
    exit 2
  }
  set -u
else
  echo "警告：找不到 nvm，將直接使用搜尋路徑上的 node" >&2
fi

# ---------------------------------------------------------------- 啟動

echo "env 檔: $env_path"
echo "node: $(node --version 2>/dev/null || echo 未安裝)"
echo "啟動 runner..."

# caffeinate -i 防閒置睡眠、-s 防系統睡眠；exec 讓 launchd 直接管到 runner 行程
if command -v caffeinate >/dev/null 2>&1; then
  exec caffeinate -is python3 "$runner_path" run
fi
exec python3 "$runner_path" run
