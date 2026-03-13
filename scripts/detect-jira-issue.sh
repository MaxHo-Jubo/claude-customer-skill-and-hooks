#!/bin/bash
# 從當前 branch 名稱提取 Jira issue 編號並檢查對應文件
# 全局腳本 - 適用於所有專案

# 切換到專案目錄
if [ -n "$CLAUDE_PROJECT_DIR" ]; then
  cd "$CLAUDE_PROJECT_DIR"
elif [ -n "$PWD" ]; then
  cd "$PWD"
fi

# 檢查是否為 git 專案
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

BRANCH=$(git branch --show-current 2>/dev/null)
if [ -z "$BRANCH" ]; then
  exit 0
fi

# 提取 issue 編號 (支援 LVB-1234, ERPD-5678 等格式)
ISSUE_ID=$(echo "$BRANCH" | grep -oE '[A-Z]+-[0-9]+' | head -1)

if [ -z "$ISSUE_ID" ]; then
  exit 0
fi

# 檢查對應文件（專案 .claude/ 目錄）
CLAUDE_DIR=".claude"
ISSUE_FILE="$CLAUDE_DIR/$ISSUE_ID.md"
JIRA_FILE="$CLAUDE_DIR/$ISSUE_ID-Jira.md"

CONTEXT="📋 當前 Branch Jira Issue: $ISSUE_ID"

if [ -f "$ISSUE_FILE" ]; then
  CONTEXT="$CONTEXT\n📄 Issue 文件: $ISSUE_FILE"
fi

if [ -f "$JIRA_FILE" ]; then
  CONTEXT="$CONTEXT\n📄 Jira 文件: $JIRA_FILE"
fi

# 如果沒有找到任何文件，提示可以建立
if [ ! -f "$ISSUE_FILE" ] && [ ! -f "$JIRA_FILE" ]; then
  CONTEXT="$CONTEXT\n💡 尚無對應文件，可用 /jira 建立"
fi

# 輸出上下文給 Claude
echo -e "$CONTEXT"

exit 0
