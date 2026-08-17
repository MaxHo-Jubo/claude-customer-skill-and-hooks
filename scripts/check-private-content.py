#!/usr/bin/env python3
"""
全 repo 私有內容掃描器——只擋「新增」的命中，現存命中由基線檔凍結。

存在理由：`mask_secrets.py` 的過濾原本只作用於 `settings.json`，而 sync 流程有 7 個同步目標，
其餘 6 個目錄（skills/ hooks/ scripts/ rules/ agents/ harness/）是 `rsync` 原封鏡像、零掃描。
「最後一道防線」的守備範圍是 1/7，而且失效方式比靜默更糟——它根本沒被呼叫到那些路徑上，
所以永遠不會回報失敗。

為何用基線而非一律阻擋：現存命中約 190 處，多數是有工程價值的內容（踩坑教訓引用的 Jira 編號、
commit message 範例、實測輸出）。一律阻擋會逼人直接關掉這道防線；凍結現狀 + 只擋新增，
才能在不阻斷日常工作的前提下保證「不再變差」。

用法：
  python3 check-private-content.py                 # 掃描並比對基線，有新增命中則 exit 1
  python3 check-private-content.py --write-baseline # 重建基線（清理過現存命中後執行）
  python3 check-private-content.py --repo /path     # 指定 repo（預設為當前工作目錄）
"""
import subprocess
import sys
from pathlib import Path

# 過濾器自身：pattern 定義與測試 fixture 必然命中自己的規則，永久豁免
SELF_EXEMPT_FILES = frozenset({
    'skills/sync-my-claude-setting/mask_secrets.py',
    'skills/sync-my-claude-setting/test_mask_secrets.py',
    'scripts/check-private-content.py',
    # 基線檔記錄的就是命中片段本身，掃描它會無限自我觸發
    '.private-content-baseline.tsv',
})
# 基線檔名（放 repo 根目錄，納入版控以便追蹤清理進度）
BASELINE_NAME = '.private-content-baseline.tsv'


def load_detector(repo: Path):
    """
    從 repo 內的 sync skill 載入 find_private_content，確保掃描器與同步流程用同一份判定。
    @param repo repo 根目錄
    @return find_private_content 函式
    """
    # STEP 01: 優先用 repo 內的版本（本機與 repo 應一致，但以受檢 repo 為準）
    skill_dir = repo / 'skills' / 'sync-my-claude-setting'
    if not (skill_dir / 'mask_secrets.py').exists():
        skill_dir = Path.home() / '.claude' / 'skills' / 'sync-my-claude-setting'
    sys.path.insert(0, str(skill_dir))
    from mask_secrets import find_private_content
    return find_private_content


def scan(repo: Path):
    """
    掃描 repo 內所有受版控檔案，回傳命中集合。
    @param repo repo 根目錄
    @return set of (相對路徑, 命中片段, 原因)
    """
    find_private_content = load_detector(repo)
    # STEP 01: 取受版控檔案清單
    files = subprocess.run(
        ['git', '-C', str(repo), 'ls-files'],
        capture_output=True, text=True, check=True,
    ).stdout.split('\n')

    hits = set()
    # STEP 02: 逐檔掃描，跳過過濾器自身與讀不到的二進位檔
    for rel in files:
        if not rel or rel in SELF_EXEMPT_FILES:
            continue
        try:
            text = (repo / rel).read_text()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for _, fragment, reason in find_private_content(text):
            hits.add((rel, fragment, reason))
    return hits


def read_baseline(path: Path):
    """
    讀取基線檔。
    @param path 基線檔路徑
    @return set of (檔案, 片段, 原因)；檔案不存在回空集合
    """
    if not path.exists():
        return set()
    entries = set()
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) == 3:
            entries.add(tuple(parts))
    return entries


def main():
    """CLI 入口：掃描 → 與基線比對 → 有新增命中則 exit 1。"""
    # STEP 01: 解析參數
    args = sys.argv[1:]
    write_baseline = '--write-baseline' in args
    repo = Path.cwd()
    if '--repo' in args:
        repo = Path(args[args.index('--repo') + 1]).resolve()

    baseline_path = repo / BASELINE_NAME

    # STEP 02: 掃描
    hits = scan(repo)

    # STEP 03: 重建基線模式
    if write_baseline:
        lines = [
            '# 私有內容掃描基線——記錄「已知且暫時接受」的命中，只有新增命中會被擋下。',
            '# 重建：python3 ~/.claude/scripts/check-private-content.py --write-baseline',
            '# 格式：相對路徑 \\t 命中片段 \\t 原因',
        ]
        lines += ['\t'.join(h) for h in sorted(hits)]
        baseline_path.write_text('\n'.join(lines) + '\n')
        print(f'✅ 已寫入基線：{len(hits)} 筆 → {baseline_path.name}')
        return 0

    # STEP 04: 比對基線，只看新增
    baseline = read_baseline(baseline_path)
    added = hits - baseline
    removed = baseline - hits

    if removed:
        print(f'ℹ️  基線中有 {len(removed)} 筆命中已消失（清理進度），可執行 --write-baseline 更新基線')

    if not added:
        print(f'✅ 無新增私有內容（現存 {len(hits)} 筆已在基線內）')
        return 0

    # STEP 05: 有新增 → 列出並拒絕
    print(f'❌ 發現 {len(added)} 筆**新增**的私有內容：\n')
    by_file = {}
    for rel, fragment, reason in sorted(added):
        by_file.setdefault(rel, []).append((fragment, reason))
    for rel, items in by_file.items():
        print(f'  {rel}')
        for fragment, reason in items[:5]:
            print(f'     [{reason}] {fragment[:70]}')
        if len(items) > 5:
            print(f'     ...另 {len(items) - 5} 筆')
    print('\n處理方式：')
    print('  1. 內容可改寫 → 改成佔位符（<org>/<repo>、<TICKET>）後重跑')
    print('  2. 確認可公開 → python3 ~/.claude/scripts/check-private-content.py --write-baseline')
    return 1


if __name__ == '__main__':
    sys.exit(main())
