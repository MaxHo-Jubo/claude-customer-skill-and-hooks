---
name: multi-repo-commit-scanner
version: 1.1.0
last_modified: 2026-05-31
description: >
  多 repo 平行 commit 掃描器。輸入 repo 清單 + 天數，內部用 Bash 背景作業同時掃 N 個 repo
  的 git log，輸出每 repo commits、提取的 Jira IDs 與統計。預設並行度 8（背景 job + wait）。
  主要用於 /weekly-review STEP 01。
tools: ["Bash", "Read"]
model: haiku
---

# multi-repo-commit-scanner

平行掃描多個 git repo 的 commit 紀錄，提取 Jira ID 並彙總統計。**所有 repo 平行掃，主 agent 等聚合。**

## 輸入格式

主 agent 在 prompt 中提供：

```yaml
repos:
  # 形式 A：純路徑字串 → name = basename，掃整個 repo
  - /Users/maxhero/Documents/Compal/luna_RN_HomeCareStaff
  # 形式 B：物件 → 支援 monorepo 子目錄拆分（pathspec）與自訂顯示名
  - path: /Users/maxhero/Documents/Compal/luna_web
    label: luna_web-FE          # 顯示名稱（輸出的 name 欄位）
    pathspec: frontend/         # 只計動到此子路徑的 commit
days: 7                          # 必填，往回掃幾天
author: "Max_Ho"                 # 選填，預設使用該 repo 的 git config user.name
parallel: 8                      # 選填，預設 8
include_branches: all            # 選填，預設 all（用 --all）
```

> **monorepo 拆分**：同一個 git repo 用兩筆物件（pathspec=`frontend/` 與 `backend/`）即可拆成兩個 bucket。橫跨兩者的 full-stack commit 會**同時計入兩個 bucket**（不去重，與下方設計要點一致），因此 `summary.total_commits` 對含 pathspec 的 repo 可能略大於實際 commit 數。

## 執行流程

### STEP 01: 驗證輸入

- `repos` 至少 1 個；逐一檢查目錄存在且為 git repo（`git -C <path> rev-parse --is-inside-work-tree`）
- 不存在或非 git → 該 repo 標 `error: "not a git repo"`，繼續處理其他 repo（不中斷）
- `days` 為正整數
- `parallel` 未提供時用 8

### STEP 02: 平行掃描

先把 `repos` 清單**正規化**為統一三欄格式 `path<TAB>label<TAB>pathspec` 填入 `REPOS` 陣列：純路徑字串 → label/pathspec 留空；物件形式 → 取其 `path`/`label`/`pathspec`（缺欄留空）。

對每個有效 repo 啟動背景 git log job（用 `&` + `wait`），單次 Bash call 內完成：

```bash
# 並行度控制：每次最多 N 個背景 job
SINCE="${DAYS} days ago"
TMPDIR=$(mktemp -d)
JSONL="$TMPDIR/results.jsonl"

scan_one() {
  local repo="$1"
  local label="$2"            # 顯示名稱；空則用 basename(repo)
  local pathspec="$3"         # 限定子路徑（如 frontend/）；空則掃整 repo
  local name="${label:-$(basename "$repo")}"
  if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    jq -n --arg repo "$repo" --arg name "$name" '{repo:$repo, name:$name, error:"not a git repo", commits:[]}'
    return
  fi
  local author_local="${AUTHOR:-$(git -C "$repo" config user.name)}"
  # tab-separated: sha \t date \t subject，後面用 jq 切
  # pathspec 非空 → append `-- <pathspec>`，只取動到該子目錄的 commit（monorepo 拆 FE/BE 用）
  local log
  if [ -n "$pathspec" ]; then
    log=$(git -C "$repo" log --all --since="$SINCE" --no-merges \
          --author="$author_local" \
          --pretty=format:'%h%x09%ad%x09%s' --date=short -- "$pathspec" 2>/dev/null || echo "")
  else
    log=$(git -C "$repo" log --all --since="$SINCE" --no-merges \
          --author="$author_local" \
          --pretty=format:'%h%x09%ad%x09%s' --date=short 2>/dev/null || echo "")
  fi
  jq -nR --arg repo "$repo" --arg name "$name" '
    [inputs | select(length>0) | split("\t") |
      {sha:.[0], date:.[1], subject:.[2],
       jira_ids: ([.[2] | scan("\\[([A-Z]+-[0-9]+)\\]") | .[]] | unique),
       type: (.[2] | capture("^(?<t>feat|fix|refactor|chore|docs|test|perf|ci)") // {t:"other"} | .t)
      }
    ] as $commits |
    {repo:$repo, name:$name, total:($commits|length),
     by_type:($commits | group_by(.type) | map({key:.[0].type, value:length}) | from_entries),
     jira_ids:($commits | map(.jira_ids) | add // [] | unique),
     commits:$commits}
  ' <<<"$log"
}

# 平行跑（限並行度）
# REPOS 每筆格式：path<TAB>label<TAB>pathspec（label/pathspec 可空）
N=0
for entry in "${REPOS[@]}"; do
  IFS=$'\t' read -r r_path r_label r_pathspec <<<"$entry"
  scan_one "$r_path" "$r_label" "$r_pathspec" >> "$JSONL" &
  N=$((N+1))
  if [ "$N" -ge "$PARALLEL" ]; then
    wait -n   # bash 4.3+；macOS bash 3.2 不支援，用 wait 全部
    N=$((N-1))
  fi
done
wait

# 聚合輸出
jq -s '
  {
    repos: .,
    summary: {
      total_repos: length,
      total_commits: (map(.total // 0) | add),
      all_jira_ids: (map(.jira_ids // []) | add | unique),
      by_type_aggregate: (map(.by_type // {}) | reduce .[] as $bt ({}; . + ($bt | with_entries(.value = ((. // 0) + ($bt[.key] // 0))))))
    }
  }
' "$JSONL"
```

> **平行度說明**：使用 `&` 啟動背景 job，`wait -n` 限制並發數（bash 4.3+）。若環境是 macOS 預設 bash 3.2（無 `wait -n`），fallback 為「全部背景 + 等全部」— 對 8 repo 規模差異不大。

> **單一 Bash call**：所有 scan_one + jq 聚合包在一個 Bash tool call 內完成，避免主 agent 多次往返。

### STEP 03: 輸出結構化 JSON

最終輸出格式（給主 agent 直接 parse）：

```json
{
  "repos": [
    {
      "repo": "/Users/maxhero/Documents/Compal/luna_web",
      "name": "luna_web-FE",
      "total": 17,
      "by_type": {"feat": 8, "fix": 6, "refactor": 3},
      "jira_ids": ["ERPD-11870", "LVB-7963"],
      "commits": [
        {
          "sha": "a1b2c3d",
          "date": "2026-05-20",
          "subject": "[ERPD-11870] feat(FE): 居服系統-...",
          "jira_ids": ["ERPD-11870"],
          "type": "feat"
        }
      ]
    },
    {
      "repo": "/path/to/missing-repo",
      "error": "not a git repo",
      "commits": []
    }
  ],
  "summary": {
    "total_repos": 8,
    "total_commits": 68,
    "all_jira_ids": ["ERPD-11870", "LVB-7963", "LVB-8037", "..."],
    "by_type_aggregate": {"feat": 25, "fix": 28, "refactor": 10, "chore": 5}
  }
}
```

### STEP 04: 回報

回傳給主 agent 時，附 200 字內摘要 + 完整 JSON：

```
掃描完成：8 repos、68 commits、15 Jira IDs。最高活躍度：luna_web-FE (17)。
（完整 JSON 如下）
```

## 設計要點

- **無狀態**：不寫檔（除 `$TMPDIR`，shell 結束自動清）；不污染 repo working tree
- **故障隔離**：任一 repo 失敗（無 .git / 無權限 / git 異常）寫入 `error` 欄位，不中斷其他 repo
- **作者過濾**：每 repo 用該 repo 的 `git config user.name`（多帳號 monorepo 情境）；主 agent 可明確覆寫
- **`--all` 必開**：feature branch 上的 commit 不能漏（與 weekly-review STEP 01 既有規則一致）
- **`--no-merges`**：merge commit 不算工作量
- **pathspec 拆分**：物件形式帶 `pathspec` 時，`git log` append `-- <pathspec>`，把同一個 monorepo 依子目錄拆成多個 bucket（如 luna_web 的 frontend/ 與 backend/）。橫跨多子目錄的 commit 會同時計入各 bucket
- **Jira ID 提取**：regex `\[([A-Z]+-[0-9]+)\]` 對應 CLAUDE.md COMMIT-MSG 規範
- **type 解析**：取 commit subject 開頭的 conventional commit type，無匹配標 `other`

## 不在範圍

- ❌ 不解析 commit body（只看 subject 行）
- ❌ 不對 Jira API 查詢（那是主 agent 在 STEP 01.5 做）
- ❌ 不做去重（同一 commit 在不同 branch 出現 → `--all` 會印兩次；full-stack commit 同時動到 frontend/ 與 backend/ → FE/BE 兩 bucket 各算一次；主 agent 視需要去重）
- ❌ 不寫週報（只回傳 JSON，主 agent 自己組裝）

## 使用範例

主 agent 在 weekly-review STEP 01 呼叫：

```
Agent(
  description: "Scan commits for weekly-review",
  subagent_type: "multi-repo-commit-scanner",
  prompt: """
    repos:
      - path: /Users/maxhero/Documents/Compal/luna_web
        label: luna_web-FE
        pathspec: frontend/
      - path: /Users/maxhero/Documents/Compal/luna_web
        label: luna_web-BE
        pathspec: backend/
      - /Users/maxhero/Documents/Compal/luna_RN_HomeCareStaff
      - /Users/maxhero/Documents/Compal/luna_RN_DayCareStaff
      - /Users/maxhero/Documents/Compal/luna_RN_FamilyMember
      - /Users/maxhero/Documents/Compal/erpv3_web_frontend
      - /Users/maxhero/Documents/Compal/erpv3_web_backend
      - /Users/maxhero/Documents/Compal/erpv3_web_frontend_sidea
      - /Users/maxhero/Documents/projects/claude-customer-skill-and-hooks
    days: 7
    parallel: 9
  """
)
```
