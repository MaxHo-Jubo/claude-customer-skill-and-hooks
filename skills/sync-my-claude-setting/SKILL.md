---
name: sync-my-claude-setting
description: "Sync My Claude Setting — 同步本機 Claude 設定到 Repo。當使用者提到 /sync-my-claude-setting、想備份設定、說「同步設定」、「備份 claude 設定」、「把設定推上去」時使用此 skill。也支援 restore 反向同步（repo → 本機）。"
version: 1.1.0
---

# Sync My Claude Setting — 同步本機 Claude 設定到 Repo

自動比對 `~/.claude/` 與 `~/Documents/projects/claude-customer-skill-and-hooks` 的差異，以 `~/.claude/` 為主複製最新內容，自動更新文件，commit and push。

## 使用方式

- `/sync-my-claude-setting` — 完整四步驟同步（本機 → repo）
- `/sync-my-claude-setting restore` — 反向同步（repo → 本機），含完整設定與 MCP Server

## 常數定義

```yaml
SOURCE: ~/.claude
SOURCE_MCP: ~/.claude.json
TARGET: ~/Documents/projects/claude-customer-skill-and-hooks
TARGET_MCP: ~/Documents/projects/claude-customer-skill-and-hooks/mcp-servers.json
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
| `~/.claude.json` → `mcpServers` | `mcp-servers.json` | 檔案（過濾 env） |

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

**MCP Server 比對：**
```bash
# 從 ~/.claude.json 擷取 mcpServers，過濾 env 欄位，與 repo 的 mcp-servers.json 比對
python3 -c "
import json, sys, tempfile, subprocess
with open('$HOME/.claude.json') as f:
    d = json.load(f)
servers = d.get('mcpServers', {})
# 過濾 env 欄位，遮罩 args 中的敏感值（--api-key/--token/--secret/--password 後的值）
clean = {}
for name, cfg in servers.items():
    entry = {k: v for k, v in cfg.items() if k != 'env'}
    if 'args' in entry:
        masked, skip = [], False
        for arg in entry['args']:
            if skip:
                masked.append('***MASKED***')
                skip = False
            elif arg in ('--api-key', '--token', '--secret', '--password'):
                masked.append(arg)
                skip = True
            else:
                masked.append(arg)
        entry['args'] = masked
    clean[name] = entry
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
    json.dump(clean, tmp, indent=2, ensure_ascii=False)
    tmp.write('\n')
    print(tmp.name)
" | xargs -I{} diff -u "$TARGET_MCP" {} || true
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

**MCP Server 複製（過濾敏感資料）：**
```bash
# 從 ~/.claude.json 擷取 mcpServers，過濾 env 欄位，遮罩 args 中的敏感值
python3 -c "
import json
with open('$HOME/.claude.json') as f:
    d = json.load(f)
servers = d.get('mcpServers', {})
clean = {}
for name, cfg in servers.items():
    entry = {k: v for k, v in cfg.items() if k != 'env'}
    if 'args' in entry:
        masked, skip = [], False
        for arg in entry['args']:
            if skip:
                masked.append('***MASKED***')
                skip = False
            elif arg in ('--api-key', '--token', '--secret', '--password'):
                masked.append(arg)
                skip = True
            else:
                masked.append(arg)
        entry['args'] = masked
    clean[name] = entry
with open('$TARGET/mcp-servers.json', 'w') as f:
    json.dump(clean, f, indent=2, ensure_ascii=False)
    f.write('\n')
"
```

> **安全規則**：
> - CLAUDE.md 的 `<conn>` 區段包含個人連線資訊（Jira cloud-id、username、專案路徑），禁止同步到 repo。
> - `mcp-servers.json` 會自動過濾 `env` 欄位並遮罩 `--api-key`/`--token`/`--secret`/`--password` 後的值。

**目錄同步（mirror 模式）：**
```bash
# rsync --delete 確保 repo 側多出的檔案也會被刪除
# -L: follow symlinks（部分 skill 是 symlink 指向 ~/.agents/skills/）
rsync -avL --delete "$SOURCE/skills/" "$TARGET/skills/"
rsync -avL --delete "$SOURCE/hooks/" "$TARGET/hooks/"
rsync -avL --delete "$SOURCE/scripts/" "$TARGET/scripts/"
rsync -avL --delete "$SOURCE/rules/" "$TARGET/rules/"
rsync -avL --delete "$SOURCE/agents/" "$TARGET/agents/"
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
| Agents 清單 | `agents/*.md` | 讀取每個 agent 的 frontmatter（name、description、model、version） |
| Plugins 清單 | `settings.json` → `plugins` 區段 | 解析 JSON，擷取啟用/停用狀態 |
| StatusLine | `statusline/statusline-command.sh` | 讀取檔頭註解 |
| MCP Servers | `mcp-servers.json` | 解析 JSON，擷取每個 server 的 type、command、args |

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

---

## 反向同步模式（restore）

當使用者執行 `/sync-my-claude-setting restore` 時，將 repo 設定還原到本機。適用於換機、重灌、或從 repo 恢復設定。

### STEP R1: Diff — 比對 repo 與本機差異

方向相反：以 repo 為基準，比對本機現有狀態。

```bash
# 檔案比對（repo → 本機）
diff -u "$TARGET/settings.json" "$SOURCE/settings.json" || true
diff -u "$TARGET/statusline/statusline-command.sh" "$SOURCE/statusline-command.sh" || true

# 目錄比對
diff -rq "$TARGET/skills/" "$SOURCE/skills/" || true
diff -rq "$TARGET/hooks/" "$SOURCE/hooks/" || true
diff -rq "$TARGET/scripts/" "$SOURCE/scripts/" || true
diff -rq "$TARGET/rules/" "$SOURCE/rules/" || true

# MCP Server 比對
# 從 repo 的 mcp-servers.json 與本機 ~/.claude.json 的 mcpServers 比對
# 列出：repo 有但本機沒有的 server、本機有但 repo 沒有的 server、兩邊都有但設定不同的 server
python3 -c "
import json
with open('$TARGET/mcp-servers.json') as f:
    repo = json.load(f)
with open('$HOME/.claude.json') as f:
    local_servers = json.load(f).get('mcpServers', {})
# 過濾 local 的 env 欄位以便比對
local_clean = {}
for name, cfg in local_servers.items():
    local_clean[name] = {k: v for k, v in cfg.items() if k != 'env'}
repo_names = set(repo.keys())
local_names = set(local_clean.keys())
for name in repo_names - local_names:
    print(f'  缺少（需安裝）: {name} → {repo[name].get(\"command\",\"\")} {\" \".join(repo[name].get(\"args\",[]))}')
for name in local_names - repo_names:
    print(f'  多出（僅本機）: {name}')
for name in repo_names & local_names:
    if repo[name].get('command') != local_clean[name].get('command') or repo[name].get('args') != local_clean[name].get('args'):
        print(f'  設定不同: {name}')
if not (repo_names - local_names) and not (local_names - repo_names):
    print('  MCP Servers 一致')
"
```

**輸出差異報告後，等待使用者確認才執行還原。**

### STEP R2: Restore — 從 Repo 複製到本機

```bash
# 檔案還原
cp "$TARGET/settings.json" "$SOURCE/settings.json"
cp "$TARGET/statusline/statusline-command.sh" "$SOURCE/statusline-command.sh"

# CLAUDE.md 還原：從 repo 最新的日期後綴版本複製回本機
# 注意：repo 版本不含 <conn> 區段，還原後使用者需自行補回
LATEST_CLAUDE=$(ls -1 "$TARGET"/CLAUDE.md.* 2>/dev/null | sort -r | head -1)
if [ -n "$LATEST_CLAUDE" ]; then
  cp "$LATEST_CLAUDE" "$SOURCE/CLAUDE.md"
  echo "⚠️  CLAUDE.md 已還原，但不含 <conn> 區段，請手動補回個人連線資訊"
fi

# 目錄還原
rsync -avL --delete "$TARGET/skills/" "$SOURCE/skills/"
rsync -avL --delete "$TARGET/hooks/" "$SOURCE/hooks/"
rsync -avL --delete "$TARGET/scripts/" "$SOURCE/scripts/"
rsync -avL --delete "$TARGET/rules/" "$SOURCE/rules/"
```

### STEP R3: Restore MCP Servers

MCP Server 還原需要特殊處理，因為 `mcp-servers.json` 是過濾後的備份。

```bash
# 讀取 repo 的 mcp-servers.json，與本機 ~/.claude.json 合併
# 策略：repo 有但本機沒有的 server → 加入本機（不含 env，使用者需自行補上）
#        本機有但 repo 沒有的 server → 保留（不刪除）
#        兩邊都有的 server → 以本機為準（保留完整的 env 設定）
python3 -c "
import json
with open('$TARGET/mcp-servers.json') as f:
    repo = json.load(f)
with open('$HOME/.claude.json') as f:
    local = json.load(f)
local_servers = local.get('mcpServers', {})
added = []
for name, cfg in repo.items():
    if name not in local_servers:
        # 新增缺少的 server，加空 env
        local_servers[name] = {**cfg, 'env': {}}
        added.append(name)
if added:
    local['mcpServers'] = local_servers
    with open('$HOME/.claude.json', 'w') as f:
        json.dump(local, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f'已新增 MCP Servers: {\", \".join(added)}')
    print('⚠️  新增的 server env 欄位為空，如有 API key 需求請手動設定')
else:
    print('MCP Servers 無需更新')
"
```

> **安全規則**：restore 不會刪除本機已有但 repo 沒有的 MCP Server（單向新增）。兩邊都有的 server 保留本機版本（含完整 env）。

---

## 注意事項

- `~/.claude/` 永遠是 source of truth，repo 只是備份與版本追蹤
- `settings.local.json` 不同步（本機專屬設定）
- `CLAUDE.md` 的 `<conn>` 區段包含個人資訊，同步時自動移除，禁止出現在 repo
- 目錄同步用 `rsync --delete`，repo 側多出的檔案會被刪除
- MCP Server 同步過濾 `env` 欄位與敏感 args 值，restore 時需手動補回
- 如果 `diff` 回報無任何差異，直接告知使用者「已同步，無需更新」並結束
