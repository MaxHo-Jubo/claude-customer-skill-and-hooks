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


def main():
    """跑完兩組案例，全數通過回 0，否則印出失敗項並回 1。"""
    # STEP 01: 私有內容偵測
    failures = []
    for text, should_hit, desc in CONTENT_CASES:
        if bool(find_private_content(text)) != should_hit:
            failures.append(f'[content] {desc}：預期{"命中" if should_hit else "豁免"}，實際相反 → {text!r}')

    # STEP 02: secret 遮罩
    for text, should_mask, desc in MASK_CASES:
        if (mask_secrets(text) != text) != should_mask:
            failures.append(f'[mask] {desc}：預期{"遮罩" if should_mask else "不變"}，實際相反 → {text!r}')

    # STEP 03: 回報
    if failures:
        print(f'❌ {len(failures)} 個 case 不符預期：')
        for f in failures:
            print(f'   {f}')
        return 1
    print(f'✅ 全部通過（內容偵測 {len(CONTENT_CASES)} 案 + secret 遮罩 {len(MASK_CASES)} 案）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
