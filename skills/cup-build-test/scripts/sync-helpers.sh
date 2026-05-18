#!/usr/bin/env bash
# sync-helpers.sh
#
# 把 cup-build-test/helpers/ 同步到 jira-test-report/helpers/（與未來其他 mirror skills）。
# cup-build-test 是 single source of truth；其他 skill 跟著它走。
#
# 用法：
#   ~/.claude/skills/cup-build-test/scripts/sync-helpers.sh           # diff preview + 確認後 sync
#   ~/.claude/skills/cup-build-test/scripts/sync-helpers.sh --check   # 只看 diff 不執行
#   ~/.claude/skills/cup-build-test/scripts/sync-helpers.sh --force   # 跳過確認直接 sync
#
# 設計：
#   - 每次更新 cup-build-test/helpers/ 後執行一次
#   - 保留各 skill 自己的 node_modules/ 與 package-lock.json（同步只動 source code）
#   - 比對版本號避免 downgrade（mirror version 不能高於 master）
#
# Playwright 安裝策略（dual install）：
#   - node_modules/playwright：每個 helpers/ 各裝一份（~17MB），跑 npm install 即可
#   - chromium binary：裝在 ~/Library/Caches/ms-playwright/（user-global cache），跨 skill 共用
#     →  mirror 首次 setup 不需 `npx playwright install chromium`（除非 user cache 不存在）
#   sync 結束時會偵測 user-global cache 狀態，給出精準提醒。

set -euo pipefail

MASTER_DIR="$HOME/.claude/skills/cup-build-test/helpers"
declare -a MIRRORS=(
  "$HOME/.claude/skills/jira-test-report/helpers"
)

# Optional mirror: business repo 的 e2e/release-tests/_helpers/
# 預設指向 luna_web monorepo 根目錄（frontend 與 backend 同層的 e2e/）；
# 可由 RELEASE_TESTS_HELPERS env var 覆寫。
# 父目錄存在時自動加入 mirror 清單，缺則 skip（避免在沒設定的環境噴錯）。
RELEASE_TESTS_HELPERS="${RELEASE_TESTS_HELPERS:-$HOME/Documents/Compal/luna_web/e2e/release-tests/_helpers}"
if [[ -d "$(dirname "$RELEASE_TESTS_HELPERS")" ]]; then
  MIRRORS+=("$RELEASE_TESTS_HELPERS")
  echo "ℹ️  偵測到業務 repo release-tests，加入 mirror：$RELEASE_TESTS_HELPERS"
  echo ""
fi

EXCLUDE_PATTERNS=(
  "--exclude=node_modules/"
  "--exclude=package-lock.json"
  "--exclude=.DS_Store"
)

# 解析 flag
MODE="interactive"
for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    --force) MODE="force" ;;
    -h|--help)
      head -25 "$0" | tail -23
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 2
      ;;
  esac
done

# STEP 01: 驗證 master 存在
if [[ ! -d "$MASTER_DIR" ]]; then
  echo "ERROR: master 目錄不存在: $MASTER_DIR" >&2
  exit 1
fi

# STEP 02: 抓 master 版本號（package.json 內 "version"）
MASTER_VERSION=$(grep -oE '"version"[[:space:]]*:[[:space:]]*"[^"]+"' "$MASTER_DIR/package.json" \
  | head -1 | grep -oE '"[0-9]+\.[0-9]+\.[0-9]+"' | tr -d '"')
if [[ -z "$MASTER_VERSION" ]]; then
  echo "ERROR: 抓不到 master version" >&2
  exit 1
fi
echo "📦 Master version: $MASTER_VERSION  ($MASTER_DIR)"
echo ""

# STEP 03: 對每個 mirror 做 diff + 同步
for mirror in "${MIRRORS[@]}"; do
  echo "=========================================="
  echo "🎯 Mirror: $mirror"
  echo "=========================================="

  # STEP 03.01: mirror 不存在則建立
  if [[ ! -d "$mirror" ]]; then
    echo "⚠️  Mirror 不存在，將建立目錄"
    if [[ "$MODE" == "check" ]]; then
      echo "   (--check 模式跳過實際建立)"
      continue
    fi
    mkdir -p "$mirror"
  else
    # STEP 03.02: 抓 mirror 版本號比對
    if [[ -f "$mirror/package.json" ]]; then
      MIRROR_VERSION=$(grep -oE '"version"[[:space:]]*:[[:space:]]*"[^"]+"' "$mirror/package.json" \
        | head -1 | grep -oE '"[0-9]+\.[0-9]+\.[0-9]+"' | tr -d '"' || echo "unknown")
      echo "📋 Mirror version: $MIRROR_VERSION"

      # 簡易比對：mirror version 不能高於 master
      if [[ "$MIRROR_VERSION" != "unknown" && "$MIRROR_VERSION" != "$MASTER_VERSION" ]]; then
        # 用 sort -V 排版本號
        higher=$(printf '%s\n%s\n' "$MASTER_VERSION" "$MIRROR_VERSION" | sort -V | tail -1)
        if [[ "$higher" == "$MIRROR_VERSION" ]]; then
          echo "⚠️  WARN: mirror version ($MIRROR_VERSION) > master ($MASTER_VERSION)"
          echo "       此操作會把 mirror 降級。確認 master 是 SSOT 才繼續。"
        fi
      fi
    fi

    # STEP 03.03: diff 預覽
    echo ""
    echo "📊 Diff preview (mirror ← master)："
    if rsync -av --dry-run "${EXCLUDE_PATTERNS[@]}" "$MASTER_DIR/" "$mirror/" \
        | grep -vE '^(sending|sent |total |building|^$)' | head -30; then
      :
    fi
  fi

  echo ""

  # STEP 03.04: check 模式只顯示不執行（仍跑 STEP 03.07 提醒）
  if [[ "$MODE" == "check" ]]; then
    echo "   (--check 模式跳過實際同步)"
    echo ""
    # 不 continue，往下印 STEP 03.07 提醒（純資訊性）
  else
    # STEP 03.05: interactive 模式問確認
    if [[ "$MODE" == "interactive" ]]; then
      read -r -p "確認同步到 $mirror? [y/N] " confirm
      if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "   跳過"
        continue
      fi
    fi

    # STEP 03.06: 執行 rsync
    rsync -av --delete "${EXCLUDE_PATTERNS[@]}" "$MASTER_DIR/" "$mirror/"
    echo "✅ 同步完成: $mirror"
    echo ""
  fi

  # STEP 03.07: 偵測 mirror node_modules 與 user-global chromium cache 狀態
  #   - node_modules：mirror 自己的 playwright npm package
  #   - chromium cache：~/Library/Caches/ms-playwright/ user-global，跨 skill 共用
  CHROMIUM_CACHE_DIR="$HOME/Library/Caches/ms-playwright"
  HAS_CHROMIUM_CACHE=false
  if compgen -G "${CHROMIUM_CACHE_DIR}/chromium*" > /dev/null 2>&1; then
    HAS_CHROMIUM_CACHE=true
  fi

  if [[ -d "$mirror/node_modules" ]]; then
    # mirror 已 setup 過
    if [[ "$mirror/package.json" -nt "$mirror/node_modules" ]]; then
      echo "💡 提醒：mirror package.json 比 node_modules 新，dependencies 可能變更："
      echo "   cd $mirror && npm install"
    else
      echo "✨ mirror node_modules 已存在且看似最新，不需動作"
    fi
  else
    # mirror 首次 setup
    echo "💡 mirror 首次 setup，需跑："
    echo "   cd $mirror && npm install   # 拉 playwright npm package (~17MB)"
    if [[ "$HAS_CHROMIUM_CACHE" == true ]]; then
      echo ""
      echo "   ✅ 偵測到 user-global chromium cache 已存在（${CHROMIUM_CACHE_DIR}）："
      echo "      $(ls -d "${CHROMIUM_CACHE_DIR}"/chromium-* 2>/dev/null | head -3 | sed 's|.*/||' | tr '\n' ' ')"
      echo "      跨 skill 共用，**不需要**再跑 'npx playwright install chromium'"
    else
      echo "   ⚠️  user-global chromium cache 不存在，需額外跑："
      echo "      cd $mirror && npx playwright install chromium  # ~92MB，一次性，之後跨 skill 共用"
    fi
  fi
done

echo ""
echo "🎉 全部完成"
