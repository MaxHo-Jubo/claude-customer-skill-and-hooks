---
name: sync-my-claude-setting
description: "Sync My Claude Setting — 同步本機 Claude 設定到 Repo。當使用者提到 /sync-my-claude-setting、想備份設定、說「同步設定」、「備份 claude 設定」、「把設定推上去」時使用此 skill。也支援 restore 反向同步（repo → 本機）。"
version: 1.5.0
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
| `settings.json` | `settings.json` | 檔案（遮罩 secret、`model` 欄位排除，見下方安全規則） |
| `CLAUDE.md` | `CLAUDE.md.{YYYYMMDD}`（如 `CLAUDE.md.20260316`） | 檔案（日期後綴） |
| `skills/` | `skills/` | 目錄（排除 `*.bak`） |
| `hooks/` | `hooks/` | 目錄（排除 `*.bak`） |
| `scripts/` | `scripts/` | 目錄（排除 `*.bak`） |
| `rules/` | `rules/` | 目錄（排除 `*.bak` 與 repo 專屬 `README.md`） |
| `harness/` | `harness/` | 目錄（排除機器專屬檔，見下方安全規則） |
| `statusline-command.sh` | `statusline/statusline-command.sh` | 檔案 |
| `~/.claude.json` → `mcpServers` | `mcp-servers.json` | 檔案（過濾 env） |

## 執行步驟

### STEP 01: Diff — 細緻比對差異

對每個同步項目執行 `diff`，產出可讀的差異報告。

**檔案比對：**
```bash
# settings.json：遮罩 secret（見 mask_secrets.py）並排除 model 欄位後比對
# SOURCE 是本機真值需遮罩；TARGET 已是遮罩過的備份，一併過濾以對齊比對，避免顯示明文或假差異
MASK_PY="$SOURCE/skills/sync-my-claude-setting/mask_secrets.py"
diff -u <(python3 "$MASK_PY" --del-model "$SOURCE/settings.json") <(python3 "$MASK_PY" --del-model "$TARGET/settings.json") || true
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
# 對每個目錄項目（一律排除 *.bak 臨時備份）
diff -rq -x '*.bak' "$SOURCE/skills/" "$TARGET/skills/" || true
diff -rq -x '*.bak' "$SOURCE/hooks/" "$TARGET/hooks/" || true
diff -rq -x '*.bak' "$SOURCE/scripts/" "$TARGET/scripts/" || true
# rules/ 額外排除 repo 專屬的 README.md（本機無此檔，不應列入差異或被刪）
diff -rq -x '*.bak' -x 'README.md' "$SOURCE/rules/" "$TARGET/rules/" || true
# harness/ 排除機器專屬檔（harness-diagnosis.md / handover-letter.md 不列入差異）
diff -rq -x '*.bak' -x 'harness-diagnosis.md' -x 'handover-letter.md' "$SOURCE/harness/" "$TARGET/harness/" || true
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
# settings.json：遮罩 secret 後複製本機內容，但 model 欄位保留 repo 原有值（不覆蓋）
python3 -c "
import json, sys
sys.path.insert(0, '$SOURCE/skills/sync-my-claude-setting')
from mask_secrets import mask_secrets
with open('$SOURCE/settings.json') as f:
    src = json.load(f)
# 遮罩 permissions allow-list 等處可能夾帶的明文 secret，避免洩漏進 repo
src = mask_secrets(src)
try:
    with open('$TARGET/settings.json') as f:
        tgt_model = json.load(f).get('model')
except FileNotFoundError:
    tgt_model = None
if tgt_model is not None:
    src['model'] = tgt_model
else:
    src.pop('model', None)
with open('$TARGET/settings.json', 'w') as f:
    json.dump(src, f, indent=2, ensure_ascii=False)
    f.write('\n')
"
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
> - `settings.json` 的 `permissions` allow-list 會記錄使用者執行過的 Bash 命令，可能夾帶帶明文 secret 的命令（如 `claude mcp add ... --api-key <key>`）。複製時一律經 `mask_secrets.py` 遞迴遮罩 secret（已知 key 格式如 `ctx7sk-`/`ghp_`/`glpat-`/`AKIA…`，以及 `--api-key`/`--token`/`--secret`/`--password` 後的值），禁止明文 secret 進 repo。
> - `mcp-servers.json` 會自動過濾 `env` 欄位並遮罩 `--api-key`/`--token`/`--secret`/`--password` 後的值。
> - `settings.json` 的 `model` 欄位為本機專屬設定（依機器/當下任務彈性切換），同步時排除、不覆蓋、不還原，repo 端維持自己原本的值。

**目錄同步（mirror 模式）：**
```bash
# rsync --delete 確保 repo 側多出的檔案也會被刪除
# -L: follow symlinks（部分 skill 是 symlink 指向 ~/.agents/skills/）
# --exclude='*.bak'：本機臨時備份不進 repo（同時保護 repo 側同名檔不被 --delete 清掉）
rsync -avL --delete --exclude='*.bak' "$SOURCE/skills/" "$TARGET/skills/"
rsync -avL --delete --exclude='*.bak' "$SOURCE/hooks/" "$TARGET/hooks/"
rsync -avL --delete --exclude='*.bak' "$SOURCE/scripts/" "$TARGET/scripts/"
# rules/ 額外保護 repo 專屬的 README.md（本機無此檔，--delete 會誤刪）
rsync -avL --delete --exclude='*.bak' --exclude='README.md' "$SOURCE/rules/" "$TARGET/rules/"
rsync -avL --delete --exclude='*.bak' "$SOURCE/agents/" "$TARGET/agents/"
# harness/ 排除機器專屬檔；--exclude 同時保護 repo 側該兩檔不被 --delete 清掉
rsync -avL --delete --exclude='*.bak' --exclude='harness-diagnosis.md' --exclude='handover-letter.md' "$SOURCE/harness/" "$TARGET/harness/"
```

> **harness 機器專屬檔規則**：`harness-diagnosis.md`（漏水診斷數據）與 `handover-letter.md`（交接信）為**機器專屬檔案，雙向不同步**——每台機器的診斷/交接只屬於那台機器，不互相覆蓋。repo main 現存的兩檔為 M4 機器快照，維持原樣；6 個通用制度檔（README、model-dispatch、judgment-matrix、delegation-templates、knowledge-protocol、commit-review-policy）正常同步。

### STEP 03: Generate Docs — 自動產生 README.md 與 CATALOG.md

**禁止跳過此步驟。** 不論 STEP 01 的 diff 大小，都必須掃描 repo 完整狀態並比對現有文件。先前 session 的改動可能已存在 repo 但尚未反映到 README/CATALOG。

讀取同步後的 repo 內容，自動重新產生文件。

#### 3.0 載入 source 標註索引（read-only）

讀取 `$TARGET/skills-sources.json` 取得**外部 skill 的出處資訊**。

```bash
SOURCES_FILE="$TARGET/skills-sources.json"
if [ -f "$SOURCES_FILE" ]; then
  # 讀進記憶體後續使用，但絕不修改此檔案
  cat "$SOURCES_FILE"
else
  echo "（無 skills-sources.json，跳過 source 標註）"
fi
```

> **不可變規則**：
> - 此檔案由使用者手動維護，sync skill **永遠不寫入、不修改、不增刪**。
> - 即使發現 `skills/` 多了未登錄的 skill，也只能在 commit message / 摘要中提示使用者，不可自動寫回 `skills-sources.json`。
> - 若檔案不存在，視為所有 skill 都是自家 skill，不顯示出處欄位。
> - **忽略 `_` 開頭的 key**（如 `_meta`、`_schema`、`_notes`）— 這些是文件區，不是 skill 條目。掃描與一致性檢查時都要排除。

Schema：
```json
{
  "_meta": { "...": "any documentation, ignored by sync skill" },
  "<skill-name>": {
    "source": "上游 URL",
    "installed": "YYYY-MM-DD（選填）",
    "note": "備註（選填）"
  }
}
```

#### 3.1 掃描資料來源

| 資料 | 來源 | 擷取方式 |
|------|------|---------|
| Skills 清單 | `skills/*/SKILL.md` | 讀取每個 SKILL.md 的標題（`# ` 行）、第一段描述、用法區段 |
| Skill 出處 | `skills-sources.json`（3.0 載入） | 以 skill 目錄名 join，取得 source / installed / note |
| Skill 載入狀態 | `settings.json` → `skillOverrides` | 解析 JSON，列出非 `on` 狀態的 skill（four states：on/name-only/user-invocable-only/off）|
| Hooks 清單 | `settings.json` → `hooks` 區段 | 解析 JSON，擷取每個 hook 的 type、matcher、command |
| Scripts 清單 | `scripts/*.{sh,cjs,ts}` | 讀取每個檔案的前 5 行註解 |
| Agents 清單 | `agents/*.md` | 讀取每個 agent 的 frontmatter（name、description、model、version） |
| Plugins 清單 | `settings.json` → `plugins` 區段 | 解析 JSON，擷取啟用/停用狀態 |
| StatusLine | `statusline/statusline-command.sh` | 讀取檔頭註解 |
| MCP Servers | `mcp-servers.json` | 解析 JSON，擷取每個 server 的 type、command、args |

#### 3.2 產生 README.md

保留現有結構，更新以下區段：
- **Skills 一覽**：表格（Skill | 指令 | 版本 | 用途）；用途欄位**末尾追加**「來源：[org/repo](URL)」當該 skill 在 `skills-sources.json` 有登錄
- **Hooks 一覽**：表格（Hook 類型 | 觸發時機 | 腳本 | 用途）
- **Plugins & MCP Servers**：表格（分類 | 數量 | 說明）
- **檔案位置**：確認路徑正確
- **變更紀錄**：如有新增/移除項目，追加紀錄

#### 3.3 產生 CATALOG.md

保留現有結構，更新以下區段：
- **Skill 載入狀態總覽**（`## Skills` 第一個子段）：表格列出所有 `skillOverrides` 中**非 `on`** 狀態的 skill（欄位：Skill / 狀態 / 說明）；若 `skillOverrides` 為空或全為 `on`，仍保留說明段但表格寫「目前所有 skill 皆為預設 `on` 狀態」；表格下方保留四種狀態與 plugin skill 限制的說明
- **Skills**：每個 skill 的完整說明（位置、用法、功能、依賴）；若該 skill 在 `skills-sources.json` 有登錄，**位置欄位下方**插入「**來源**：[<host>/<path>](URL)（installed: YYYY-MM-DD，note）」一行
- **Hooks**：每個 hook 的表格
- **Scripts（輔助工具）**：每個 script 的表格
- **Plugins & MCP Servers**：啟用/停用清單
- **StatusLine**：確認描述正確
- **持續學習系統**：確認描述正確
- **依賴關係圖**：根據實際 skill 間的關係更新

#### 3.4 一致性檢查（read-only 提示）

掃描 `skills/` 目錄與 `skills-sources.json` 的差集，**僅提示不修改**。

**比對前先過濾**：從 `skills-sources.json` 取 keys 時，**排除以底線（`_`）開頭的 key**（這些是文件區，例如 `_meta`、`_schema`、`_notes`）。

```bash
# 取出所有有效 skill 條目（過濾掉 _meta 等文件 key）
jq -r 'to_entries | map(select(.key | startswith("_") | not)) | .[].key' "$SOURCES_FILE"
```

- `skills/` 有但 `skills-sources.json` 沒有 → 視為「自家 skill」，不顯示出處（正常情況）
- `skills-sources.json` 有但 `skills/` 沒有 → 警告「source 索引含已不存在的 skill：<name>」，提示使用者清理

範例提示：
```
ℹ️  skills-sources.json 共登錄 N 個外部 skill，全部對應到 skills/ 目錄
⚠️  skills-sources.json 有 'old-skill' 但 skills/ 已無此目錄，請手動清理 sources 條目
```

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
# settings.json：遮罩 secret 並排除 model 欄位後比對（repo 已遮罩，本機端一併過濾以對齊）
MASK_PY="$SOURCE/skills/sync-my-claude-setting/mask_secrets.py"
diff -u <(python3 "$MASK_PY" --del-model "$TARGET/settings.json") <(python3 "$MASK_PY" --del-model "$SOURCE/settings.json") || true
diff -u "$TARGET/statusline/statusline-command.sh" "$SOURCE/statusline-command.sh" || true

# 目錄比對（排除 *.bak；rules 排除 repo 專屬 README.md）
diff -rq -x '*.bak' "$TARGET/skills/" "$SOURCE/skills/" || true
diff -rq -x '*.bak' "$TARGET/hooks/" "$SOURCE/hooks/" || true
diff -rq -x '*.bak' "$TARGET/scripts/" "$SOURCE/scripts/" || true
diff -rq -x '*.bak' -x 'README.md' "$TARGET/rules/" "$SOURCE/rules/" || true
diff -rq -x '*.bak' -x 'harness-diagnosis.md' -x 'handover-letter.md' "$TARGET/harness/" "$SOURCE/harness/" || true

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
# settings.json：還原 repo 內容，但 model 欄位保留本機原有值（不覆蓋）
python3 -c "
import json
with open('$TARGET/settings.json') as f:
    src = json.load(f)
try:
    with open('$SOURCE/settings.json') as f:
        local_model = json.load(f).get('model')
except FileNotFoundError:
    local_model = None
if local_model is not None:
    src['model'] = local_model
else:
    src.pop('model', None)
with open('$SOURCE/settings.json', 'w') as f:
    json.dump(src, f, indent=2, ensure_ascii=False)
    f.write('\n')
"
cp "$TARGET/statusline/statusline-command.sh" "$SOURCE/statusline-command.sh"

# CLAUDE.md 還原：從 repo 最新的日期後綴版本複製回本機
# 注意：repo 版本不含 <conn> 區段，還原後使用者需自行補回
LATEST_CLAUDE=$(ls -1 "$TARGET"/CLAUDE.md.* 2>/dev/null | sort -r | head -1)
if [ -n "$LATEST_CLAUDE" ]; then
  cp "$LATEST_CLAUDE" "$SOURCE/CLAUDE.md"
  echo "⚠️  CLAUDE.md 已還原，但不含 <conn> 區段，請手動補回個人連線資訊"
fi

# 目錄還原（排除 *.bak；rules 不還原 repo 專屬 README.md 到本機）
rsync -avL --delete --exclude='*.bak' "$TARGET/skills/" "$SOURCE/skills/"
rsync -avL --delete --exclude='*.bak' "$TARGET/hooks/" "$SOURCE/hooks/"
rsync -avL --delete --exclude='*.bak' "$TARGET/scripts/" "$SOURCE/scripts/"
rsync -avL --delete --exclude='*.bak' --exclude='README.md' "$TARGET/rules/" "$SOURCE/rules/"
# harness/ 還原同樣排除機器專屬檔（repo 的診斷/交接是別台機器的，不還原到本機）
rsync -avL --delete --exclude='*.bak' --exclude='harness-diagnosis.md' --exclude='handover-letter.md' "$TARGET/harness/" "$SOURCE/harness/"
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

> **安全規則**：restore 不會刪除本機已有但 repo 沒有的 MCP Server（單向新增）。兩邊都有的 server 保留本機版本（含完整 env）。`settings.json` 的 `model` 欄位同樣排除，還原後維持本機原本的值。

---

## 注意事項

- `~/.claude/` 永遠是 source of truth，repo 只是備份與版本追蹤
- `settings.local.json` 不同步（本機專屬設定）
- `settings.json` 的 `model` 欄位不同步、不還原（雙向排除），兩邊各自保留自己原本的值
- `harness/harness-diagnosis.md` 與 `harness/handover-letter.md` 為機器專屬檔案，雙向不同步（每台機器的診斷/交接不互相覆蓋）
- `CLAUDE.md` 的 `<conn>` 區段包含個人資訊，同步時自動移除，禁止出現在 repo
- 目錄同步用 `rsync --delete`，repo 側多出的檔案會被刪除（`*.bak` 與 `rules/README.md` 除外，見安全規則）
- `settings.json` 複製/還原都會經 `mask_secrets.py` 遮罩 `permissions` 中的明文 secret；restore 後本機原本夾帶 secret 的 permission 會變成 `***MASKED***`（該 permission 失效，需要時重新授權即可，本就不該把 secret 留在 allow-list）
- `*.bak` 臨時備份雙向不同步；`rules/README.md` 為 repo 專屬說明文件，正向同步不刪、restore 不還原到本機
- MCP Server 同步過濾 `env` 欄位與敏感 args 值，restore 時需手動補回
- 如果 `diff` 回報無任何差異，直接告知使用者「已同步，無需更新」並結束
