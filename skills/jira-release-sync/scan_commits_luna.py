#!/usr/bin/env python3
"""
掃描 luna_web repo 的 release 分支，找出「已隨版本 tag 上架」的 Jira issue 候選清單。

luna_web 的判定規則跟 App repo（scan_commits.py）結構不同，因此獨立成另一支腳本，
不共用同一份邏輯（依 max_ho 於 2026-09-04 確認）：

  0. 執行前一律先 `git fetch origin release:release`（fast-forward only），不信任
     本地 release 分支的既有狀態（2026-09-17 實測：本地落後 origin 158 個 commit，
     漏掉一次 master merge 進 release，導致 ERPD-12090 等 commit 完全沒進任何清單）。
  1. 只掃 release 分支（不是 master/main）的歷史。
  2. 只收 author 是 Max_Ho 的 commit（這個 repo 是多人協作，不像 App repo 那樣不限作者）。
     Max_Ho 在本 repo 的 git author 有多種變體（Max_Ho <max_ho@compal.com>／
     Max Ho <...@users.noreply.github.com>／Max Ho <maxho@ENG-Mac-Studio.local> 等），
     用大小寫不敏感的 "max[_ ]?ho" pattern 比對 author name+email，不寫死單一 email。
  3. 版本釋出點不是靠 merge commit subject 規則推導，而是 release 分支上實際打的
     git tag，格式 "frontend-vYYYY.MM.DD" 或 "backend-vYYYY.MM.DD"（只認這個精確格式，
     排除 "-test"／"-2"／"-fix-xxx"／".1" 這類非正式 tag，也排除 "frontend-v20260605"
     這種舊的無點分隔格式）。
  4. luna_web 是 frontend／backend 分開部署的 monorepo（實測：2026-08-19 只打了
     frontend tag、2026-08-20 只打了 backend tag，不能假設兩者同步上架），所以每個
     commit 要先判定它屬於哪個 component（用改動檔案路徑的頂層目錄
     frontend/ 或 backend/ 判斷，比 commit message 的 (FE)/(BE) 標籤可靠——
     並非每筆 commit 都有標，例如 "fix pr issues" 這類 follow-up commit 常常沒標）。
  5. 同一 Jira issue 若橫跨 frontend 與 backend 兩個 component（不論是單一 commit
     同時動到兩邊路徑，還是分成兩筆 commit 各自只動一邊），兩邊都要各自找到自己
     component 的 tag 才算「已上架」，日期取兩邊較晚的一個（依 max_ho 2026-09-04
     確認：沒有全部上架前，不算完成，避免其中一個 component 還沒真的上線就被標記
     為已上架/轉 Resolved）。只要有任一必要 component 的 tag 還沒出現，整個 issue
     這輪都不列入可執行候選，改列進 pending 給人看目前卡在哪個 component。

用法：
  python3 scan_commits_luna.py --weeks 2
  python3 scan_commits_luna.py --weeks 2 --json-out /path/to/out.json

輸出：JSON object：
  {
    "candidates": [ 已完全上架、可執行的候選（見下方單筆格式） ],
    "pending": [ 部分 component 尚未上架，本輪先跳過 ],
    "manual_review": [ commit 改動路徑判斷不出屬於 frontend 還是 backend，需人工確認 ]
  }

candidates 單筆格式：
  {
    "jira_id": "ERPD-12051",
    "release_version": "2026.09.03",            # 決定該 issue 最終上架時間的那個 tag 日期
    "release_date": "2026-09-03",
    "release_datetime_iso": "2026-09-03T15:12:36+08:00",
    "components": ["frontend"],                 # 這個 issue 橫跨的 component（可能兩者皆有）
    "commit_hash": "...",                       # 決定最終上架時間的那筆 commit
    "commit_subject": "...",
    "commit_date": "2026-09-02",
    "commits_detail": [ {component, commit_hash, commit_subject, commit_date,
                          release_tag, release_version, release_date}, ... ]
  }
"""

import argparse
import json
import re
import subprocess

RELEASE_BRANCH = "release"
AUTHOR_PATTERN = "max[_ ]?ho"  # 大小寫不敏感，涵蓋 max_ho / Max Ho / maxho 等變體
TAG_RE = re.compile(r"^(frontend|backend)-v([0-9]{4}\.[0-9]{2}\.[0-9]{2})$")
JIRA_RE = re.compile(r"^\[([A-Z]+-[0-9]+)\]")
FIELD_SEP = "\x1f"


def sync_release_branch() -> None:
    """
    執行掃描前先把本地 release 分支 fast-forward 到 origin/release。

    2026-09-17 實測踩過：本地 release 落後 origin 158 個 commit，其中一次
    "Merge pull request #11124 from compal-swhq/master" 只有 fetch 後才看得到，
    導致本輪掃描全部基於過期歷史跑 ancestry 判斷（ERPD-12090 等已 merge 進 release
    的 commit 因此被漏掉，完全沒出現在任何清單裡）。只接受 fast-forward；
    本地有 origin 沒有的 commit（non-fast-forward）代表分支已 diverge，這是需要
    人工排查的異常狀態，不可靜默覆蓋，直接中止讓使用者自行確認。
    """
    r = subprocess.run(
        ["git", "fetch", "origin", f"{RELEASE_BRANCH}:{RELEASE_BRANCH}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise SystemExit(
            f"git fetch origin {RELEASE_BRANCH} 失敗（可能是本地 {RELEASE_BRANCH} 已 diverge、"
            f"無網路，或不在 luna_web repo 內），請手動排查後再重跑本 skill：\n{r.stderr.strip()}"
        )


def verify_release_branch() -> None:
    """確認 release 分支存在，找不到就直接中止並提示，不猜測改用其他分支。"""
    r = subprocess.run(
        ["git", "rev-parse", "--verify", RELEASE_BRANCH],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise SystemExit(f"找不到 {RELEASE_BRANCH} 分支，請確認在 luna_web repo 內執行")


def load_author_commits(weeks: int):
    """撈出 release 分支上、指定週數內、作者是 Max_Ho 的 commit。"""
    r = subprocess.run(
        [
            "git", "log", RELEASE_BRANCH,
            f"--author={AUTHOR_PATTERN}", "-i", "--extended-regexp",
            f"--since={weeks} weeks ago",
            "--reverse",
            "--date=iso-strict",
            f"--format=%H{FIELD_SEP}%ct{FIELD_SEP}%cd{FIELD_SEP}%s",
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise SystemExit(f"git log 失敗: {r.stderr.strip()}")

    commits = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(FIELD_SEP, 3)
        if len(parts) != 4:
            continue
        h, ct, cd, subj = parts
        commits.append({"hash": h, "epoch": int(ct), "date_iso": cd, "subject": subj})
    return commits


def load_component_releases():
    """列出 release 分支上所有合法格式的 frontend-v*/backend-v* tag，依 component 分兩組。"""
    r = subprocess.run(
        ["git", "tag", "-l", "frontend-v*", "backend-v*"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise SystemExit(f"git tag 失敗: {r.stderr.strip()}")

    releases = {"frontend": [], "backend": []}
    for tag in r.stdout.splitlines():
        tag = tag.strip()
        m = TAG_RE.match(tag)
        if not m:
            continue  # 排除 -test/-2/-fix-xxx/.1 等非正式 tag，以及舊的無點分隔格式
        component, version = m.group(1), m.group(2)

        show = subprocess.run(
            ["git", "log", "-1", "--date=iso-strict", f"--format=%H{FIELD_SEP}%ct{FIELD_SEP}%cd", tag],
            capture_output=True, text=True,
        )
        if show.returncode != 0:
            continue
        h, ct, cd = show.stdout.strip().split(FIELD_SEP)

        # tag 指向的 commit 若不是 release 分支的祖先，代表是打在別的分支或已失效，跳過
        if not is_ancestor(h, RELEASE_BRANCH):
            continue

        releases[component].append({
            "version": version, "epoch": int(ct), "date_iso": cd, "hash": h, "tag": tag,
        })

    for component in releases:
        releases[component].sort(key=lambda rel: rel["epoch"])
    return releases


def is_ancestor(commit_hash: str, target_hash: str) -> bool:
    r = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit_hash, target_hash],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def detect_component(commit_hash: str) -> str:
    """依改動檔案的頂層目錄判斷 commit 屬於 frontend/backend/both/unknown。"""
    r = subprocess.run(
        ["git", "show", "--name-only", "--format=", commit_hash],
        capture_output=True, text=True,
    )
    paths = [p for p in r.stdout.splitlines() if p.strip()]
    has_frontend = any(p.startswith("frontend/") for p in paths)
    has_backend = any(p.startswith("backend/") for p in paths)
    if has_frontend and has_backend:
        return "both"
    if has_frontend:
        return "frontend"
    if has_backend:
        return "backend"
    return "unknown"


def release_for(commit_hash: str, component_releases: list):
    """依時間序找出「最早」把這個 commit 包進去的該 component tag（ancestry 判斷）。"""
    for rel in component_releases:
        if is_ancestor(commit_hash, rel["hash"]):
            return rel
    return None


def resolve_commit(commit: dict, releases: dict):
    """
    解析單筆 commit 的上架狀態。
    回傳 (component, resolved_entries, pending_entries)：
      resolved_entries: 該 commit 已確定上架的 component 明細列表（可能 1 或 2 筆，'both' 時最多 2 筆）
      pending_entries: 該 commit 還在等哪些 component 的 tag，附上 commit 本身資訊供人工判讀
    """
    component = detect_component(commit["hash"])
    if component == "unknown":
        return component, [], []

    needed = ["frontend", "backend"] if component == "both" else [component]
    resolved_entries = []
    pending_entries = []
    for comp in needed:
        rel = release_for(commit["hash"], releases[comp])
        if rel is None:
            pending_entries.append({
                "component": comp,
                "commit_hash": commit["hash"],
                "commit_subject": commit["subject"],
                "commit_date": commit["date_iso"][:10],
            })
            continue
        resolved_entries.append({
            "component": comp,
            "commit_hash": commit["hash"],
            "commit_subject": commit["subject"],
            "commit_date": commit["date_iso"][:10],
            "release_tag": rel["tag"],
            "release_version": rel["version"],
            "release_date": rel["date_iso"][:10],
            "release_datetime_iso": rel["date_iso"],
            "_release_epoch": rel["epoch"],
        })
    return component, resolved_entries, pending_entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    weeks = max(1, min(8, args.weeks))
    verify_release_branch()
    sync_release_branch()
    commits = load_author_commits(weeks)
    releases = load_component_releases()

    by_jira = {}
    for c in commits:
        m = JIRA_RE.match(c["subject"])
        if not m:
            continue
        by_jira.setdefault(m.group(1), []).append(c)

    candidates = []
    pending = []
    manual_review = []

    for jira_id, jira_commits in sorted(by_jira.items()):
        all_resolved = []
        all_pending = []
        unknown_commits = []

        for c in jira_commits:
            component, resolved_entries, pending_entries = resolve_commit(c, releases)
            if component == "unknown":
                unknown_commits.append(c)
                continue
            all_resolved.extend(resolved_entries)
            all_pending.extend(pending_entries)

        if unknown_commits:
            manual_review.append({
                "jira_id": jira_id,
                "reason": "commit 改動路徑未落在 frontend/ 或 backend/ 底下，component 無法判定",
                "commits": [
                    {"commit_hash": c["hash"], "commit_subject": c["subject"], "commit_date": c["date_iso"][:10]}
                    for c in unknown_commits
                ],
            })
            continue

        if all_pending:
            pending.append({
                "jira_id": jira_id,
                "resolved_components": sorted({e["component"] for e in all_resolved}),
                "pending_components": sorted({e["component"] for e in all_pending}),
                "resolved_detail": [
                    {k: v for k, v in e.items() if not k.startswith("_")} for e in all_resolved
                ],
                "pending_detail": all_pending,
            })
            continue

        final = max(all_resolved, key=lambda e: e["_release_epoch"])
        candidates.append({
            "jira_id": jira_id,
            "release_version": final["release_version"],
            "release_date": final["release_date"],
            "release_datetime_iso": final["release_datetime_iso"],
            "components": sorted({e["component"] for e in all_resolved}),
            "commit_hash": final["commit_hash"],
            "commit_subject": final["commit_subject"],
            "commit_date": final["commit_date"],
            "commits_detail": [
                {k: v for k, v in e.items() if not k.startswith("_")} for e in all_resolved
            ],
        })

    out = json.dumps(
        {"candidates": candidates, "pending": pending, "manual_review": manual_review},
        ensure_ascii=False, indent=2,
    )
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(out)
    print(out)


if __name__ == "__main__":
    main()
