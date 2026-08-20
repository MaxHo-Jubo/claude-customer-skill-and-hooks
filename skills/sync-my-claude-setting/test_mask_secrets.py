#!/usr/bin/env python3
"""
mask_secrets 的私有內容偵測回歸測試（無框架，`python3 test_mask_secrets.py` 直接跑，exit code 即結果）。

存在理由：`find_private_content` 是這個 **public** repo 的最後一道防線，而「跑完沒噴東西」的過濾器
與「跑完但濾網有洞」的過濾器輸出完全一樣——2026-08-19 就實測過一次：政策文字宣稱要擋 commit message
夾帶的 Jira 編號，三個 regex 卻沒有任何一個比對 Jira 編號，而掃描照樣回報乾淨。

**豁免案例與真陽性同等重要**：收緊 regex 時若把 `~/.claude/` 的 hook 路徑一起擋掉，同步會永久
fail loud——那比漏判更痛，因為它會逼人把整道防線關掉。
"""
import sys

from mask_secrets import find_private_content, mask_secrets

# 私有內容偵測案例：(輸入, 應否命中, 說明)
CONTENT_CASES = [
    ("Bash(git -C ~/Documents/Compal/x log)", True, "波浪號形式"),
    ("Bash(cd $HOME/Documents/y && npm test)", True, "$HOME 形式"),
    ("Bash(git -C /Users/maxhero/Projects/internal status)", True, "非白名單目錄"),
    ("Read(/users/maxhero/documents/private/x.ts)", True, "大小寫變體"),
    ('Bash(gh pr list --head "LVB-7762/fix/max_ho/修正畫面異常放大")', True, "Jira 編號 + 工作內容"),
    ('git commit -m "[ERPD-11967] fix(FE): 居服系統-個案"', True, "Jira commit message"),
    ("Bash(gh repo clone compal_swhq/foo)", True, "組織名底線變體"),
    ("cat ~/.claude/state/pending-review/-Users-maxhero-Documents-Compal-x.json", True, "dash-encoded 路徑"),
    ("Bash(git -C ~/work/erpv3_web_backend push)", True, "PROJECT-MAP 列的私有 repo"),
    ("bun /Users/maxhero/.claude/scripts/post-commit-review.ts", False, "豁免：hook 絕對路徑"),
    ("bash ~/.claude/hooks/hook-error-wrapper.sh SubagentStop", False, "豁免：hook 波浪號路徑"),
    ("cat /Users/maxhero/.claude-max-2/CLAUDE.md", False, "豁免：多帳號目錄"),
    ("/Users/maxhero/.nvm/versions/node/v20.20.0/bin/claude", False, "豁免：nvm 路徑"),
    ("Bash(~/.maestro/bin/maestro test:*)", False, "豁免：.maestro 已列入清單"),
    ('Bash(export PATH="$PATH":"$HOME/.maestro/bin")', False, "豁免：$HOME + 已列入的工具目錄"),
    ("Bash(ls ~/Library/Android/sdk/cmdline-tools)", False, "豁免：~/Library 已列入清單"),
    # 以下三條釘住「dot-directory 本身不構成豁免」——曾試過改成規則判準，實測為偵測能力迴歸
    ("Bash(git -C ~/.acme-internal-project push)", True, "未列入的 dot-directory 私有專案須命中"),
    ("Bash(cat ~/.secret-client-work/notes.md)", True, "未列入的 dot-directory 私有工作目錄須命中"),
    ("Bash(git -C /Users/maxhero/.new-private-repo status)", True, "絕對路徑形式的未知 dot-directory 須命中"),
    ("說明文件寫 `~/Library` 這種 markdown 形式", False, "豁免：反引號不得吃進目錄名"),
    ("清單含 `~/Library`, `~/.maestro` 兩處", False, "豁免：逗號不得吃進目錄名"),
    ("Bash(export NVM_DIR=$HOME/.nvm\\)", False, "豁免：反斜線不得吃進目錄名"),
    ("文件提到 `~/Documents/Compal/x` 路徑", True, "反引號包住的私有路徑仍須命中"),
    ("Bash(npx eslint src/)", False, "豁免：無路徑的一般指令"),
    ("Bash(gh pr view 1134 --json state)", False, "豁免：無私有內容"),
]

# secret 遮罩案例：(輸入, 應否被遮罩, 說明)
MASK_CASES = [
    ("claude mcp add ctx7 --api-key ctx7sk-abcd1234efgh", True, "--api-key 後接值"),
    ("claude mcp add ctx7 --apikey ctx7sk-abcd1234efgh", True, "--apikey 無連字號變體"),
    ("export TOKEN=ghp_abcdefghijklmnopqrstuvwxyz12", True, "裸露 GitHub token"),
    ("Bash(git -C /repo status)", False, "豁免：一般指令不應被遮罩"),
]


# 回報完整性案例：(輸入, 預期命中數, 說明)
# 存在理由：`find_private_content` 若對 denylist 用 `search` 而非 `finditer`，每個字串只回報第一個
# 命中。掃 JSON 時每個值是獨立節點故影響小，但 check-private-content.py 把整份檔案當單一字串掃，
# 實測因此漏報 84%（41 檔看得到 41 筆、實際 262 筆）。上面的 bool 案例抓不到這種缺陷——有命中就過。
COUNT_CASES = [
    ("luna_web 與 erpv3_web_backend 兩個 repo", 2, "同字串多個私有 repo 名須全數回報"),
    ("[ERPD-11696] 與 [LVB-7866] 兩個編號", 2, "同字串多個 Jira 編號須全數回報"),
    ("~/Documents/a 與 ~/Desktop/b", 2, "同字串多個本機專案路徑須全數回報"),
    # 下面這條專測 STEP 01.03（dash-encoded）。上面三條都測不到它：前兩條走 denylist、
    # 第三條走的 _HOME_PATH_PATTERN 本來就是 finditer，退回 search 也照樣通過。
    ("marker: -Users-maxhero-Documents-x.json 與 -Users-maxhero-Desktop-y.json", 2,
     "同字串多個 dash-encoded 路徑須全數回報"),
]


def main():
    """跑完三組案例，全數通過回 0，否則印出失敗項並回 1。"""
    # STEP 01: 私有內容偵測
    failures = []
    for text, should_hit, desc in CONTENT_CASES:
        if bool(find_private_content(text)) != should_hit:
            failures.append(f'[content] {desc}：預期{"命中" if should_hit else "豁免"}，實際相反 → {text!r}')

    # STEP 02: secret 遮罩
    for text, should_mask, desc in MASK_CASES:
        if (mask_secrets(text) != text) != should_mask:
            failures.append(f'[mask] {desc}：預期{"遮罩" if should_mask else "不變"}，實際相反 → {text!r}')

    # STEP 03: 回報完整性（同字串多命中須全數回報，非只回第一個）
    for text, expected, desc in COUNT_CASES:
        actual = len(find_private_content(text))
        if actual != expected:
            failures.append(f'[count] {desc}：預期 {expected} 筆，實際 {actual} 筆 → {text!r}')

    # STEP 04: 回報
    if failures:
        print(f'❌ {len(failures)} 個 case 不符預期：')
        for f in failures:
            print(f'   {f}')
        return 1
    print(f'✅ 全部通過（內容偵測 {len(CONTENT_CASES)} 案 + secret 遮罩 {len(MASK_CASES)} 案 '
          f'+ 回報完整性 {len(COUNT_CASES)} 案）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
