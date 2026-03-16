# Sync My Claude Setting — 同步本機 Claude 設定到 Repo

自動比對 `~/.claude/` 與 `~/Documents/projects/claude-customer-skill-and-hooks` 的差異，以 `~/.claude/` 為主複製最新內容，自動更新文件，commit and push。

## 使用方式

- `/sync-my-claude-setting` — 完整四步驟同步

## 常數定義

```yaml
SOURCE: ~/.claude
TARGET: ~/Documents/projects/claude-customer-skill-and-hooks
```

## 同步清單

| 來源 (`~/.claude/`) | 目標 (repo) | 類型 |
|---------------------|-------------|------|
| `settings.json` | `settings.json` | 檔案 |
| `CLAUDE.md` | `CLAUDE.md.{YYYYMMDD}`（如 `CLAUDE.md.20260316`） | 檔案（日期後綴） |
| `skills/` | `skills/` | 目錄 |
| `hooks/` | `hooks/` | 目錄 |
| `scripts/` | `scripts/` | 目錄 |
| `rules/` | `rules/` | 目錄 |
| `statusline-command.sh` | `statusline/statusline-command.sh` | 檔案 |

## 執行步驟

### STEP 01: Diff — 細緻比對差異

對每個同步項目執行 `diff`，產出可讀的差異報告。

**檔案比對：**
```bash
diff -u "$SOURCE/settings.json" "$TARGET/settings.json" || true
# CLAUDE.md 比對最新的日期後綴版本
LATEST_CLAUDE=$(ls -1 "$TARGET"/CLAUDE.md.* 2>/dev/null | sort -r | head -1)
if [ -n "$LATEST_CLAUDE" ]; then
  diff -u "$SOURCE/CLAUDE.md" "$LATEST_CLAUDE" || true
else
  echo "尚無 CLAUDE.md 備份，將建立首份"
fi
diff -u "$SOURCE/statusline-command.sh" "$TARGET/statusline/statusline-command.sh" || true
```

**目錄比對：**
```bash
# 對每個目錄項目
diff -rq "$SOURCE/skills/" "$TARGET/skills/" || true
diff -rq "$SOURCE/hooks/" "$TARGET/hooks/" || true
diff -rq "$SOURCE/scripts/" "$TARGET/scripts/" || true
diff -rq "$SOURCE/rules/" "$TARGET/rules/" || true
```

對 `diff -rq` 回報有差異的檔案，逐一執行 `diff -u` 顯示具體內容差異。

**輸出格式：**

```
## 差異報告

### settings.json
（具體 diff 內容或「無差異」）

### CLAUDE.md
（具體 diff 內容或「無差異」）

### skills/
- 新增: skill-name/SKILL.md
- 修改: other-skill/SKILL.md（附 diff）
- 刪除: old-skill/（僅存在於 repo）

...依此類推
```

### STEP 02: Copy — 從本機複製到 Repo

直接以 `~/.claude/` 為準覆蓋 repo 內容。

**檔案複製：**
```bash
cp "$SOURCE/settings.json" "$TARGET/settings.json"
# CLAUDE.md：複製當日版本，移除 <conn> 區段（含個人資訊），再刪除先前日期備份
TODAY=$(date +%Y%m%d)
sed '/<conn /,/<\/conn>/d' "$SOURCE/CLAUDE.md" > "$TARGET/CLAUDE.md.$TODAY"
find "$TARGET" -maxdepth 1 -name "CLAUDE.md.*" ! -name "CLAUDE.md.$TODAY" -delete
cp "$SOURCE/statusline-command.sh" "$TARGET/statusline/statusline-command.sh"
```

> **安全規則**：CLAUDE.md 的 `<conn>` 區段包含個人連線資訊（Jira cloud-id、username、專案路徑），禁止同步到 repo。

**目錄同步（mirror 模式）：**
```bash
# rsync --delete 確保 repo 側多出的檔案也會被刪除
# -L: follow symlinks（部分 skill 是 symlink 指向 ~/.agents/skills/）
rsync -avL --delete "$SOURCE/skills/" "$TARGET/skills/"
rsync -avL --delete "$SOURCE/hooks/" "$TARGET/hooks/"
rsync -avL --delete "$SOURCE/scripts/" "$TARGET/scripts/"
rsync -avL --delete "$SOURCE/rules/" "$TARGET/rules/"
```

### STEP 03: Generate Docs — 自動產生 README.md 與 CATALOG.md

**禁止跳過此步驟。** 不論 STEP 01 的 diff 大小，都必須掃描 repo 完整狀態並比對現有文件。先前 session 的改動可能已存在 repo 但尚未反映到 README/CATALOG。

讀取同步後的 repo 內容，自動重新產生文件。

#### 3.1 掃描資料來源

| 資料 | 來源 | 擷取方式 |
|------|------|---------|
| Skills 清單 | `skills/*/SKILL.md` | 讀取每個 SKILL.md 的標題（`# ` 行）、第一段描述、用法區段 |
| Hooks 清單 | `settings.json` → `hooks` 區段 | 解析 JSON，擷取每個 hook 的 type、matcher、command |
| Scripts 清單 | `scripts/*.{sh,cjs}` | 讀取每個檔案的前 5 行註解 |
| Plugins 清單 | `settings.json` → `plugins` 區段 | 解析 JSON，擷取啟用/停用狀態 |
| StatusLine | `statusline/statusline-command.sh` | 讀取檔頭註解 |

#### 3.2 產生 README.md

保留現有結構，更新以下區段：
- **Skills 一覽**：表格（Skill | 指令 | 用途）
- **Hooks 一覽**：表格（Hook 類型 | 觸發時機 | 腳本 | 用途）
- **Plugins & MCP Servers**：表格（分類 | 數量 | 說明）
- **檔案位置**：確認路徑正確
- **變更紀錄**：如有新增/移除項目，追加紀錄

#### 3.3 產生 CATALOG.md

保留現有結構，更新以下區段：
- **Skills**：每個 skill 的完整說明（位置、用法、功能、依賴）
- **Hooks**：每個 hook 的表格
- **Scripts（輔助工具）**：每個 script 的表格
- **Plugins & MCP Servers**：啟用/停用清單
- **StatusLine**：確認描述正確
- **持續學習系統**：確認描述正確
- **依賴關係圖**：根據實際 skill 間的關係更新

### STEP 04: Commit & Push

```bash
cd "$TARGET"
git add -A
git status
```

根據 STEP 01 的差異報告產生 commit message：

```
chore: 同步本機設定，{變更摘要}

變更項目：
- {具體變更列表}
```

```bash
git commit -m "{message}"
git push
```

## 注意事項

- `~/.claude/` 永遠是 source of truth，repo 只是備份與版本追蹤
- `settings.local.json` 不同步（本機專屬設定）
- `CLAUDE.md` 的 `<conn>` 區段包含個人資訊，同步時自動移除，禁止出現在 repo
- 目錄同步用 `rsync --delete`，repo 側多出的檔案會被刪除
- 如果 `diff` 回報無任何差異，直接告知使用者「已同步，無需更新」並結束
