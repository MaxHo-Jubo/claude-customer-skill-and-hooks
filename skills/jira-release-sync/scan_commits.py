#!/usr/bin/env python3
"""
掃描 git 歷史，找出「期間內已隨版本 merge 進 master 而釋出」的 Jira issue 候選清單。

判定規則（依 max_ho 於 2026-09-03 確認並調整）：
  一個「版本 merge commit」定義為 subject 符合
  "Merge pull request #N from {org}/{X.Y.Z}"（分支名稱純粹是版本號本身）的 commit，
  其 committer date 即為該版本的釋出（上架）日期，release_version 取自分支名稱。

  一個 [ISSUE-ID] commit 若是某個版本 merge commit 的祖先（用
  `git merge-base --is-ancestor` 判斷，而非單純比日期——同一 commit 的 author/
  committer timestamp 可能早於它實際被 merge 進 master 的時間，尤其長壽命
  feature branch），即視為該 issue 已隨該版本上架。取「時間序上最早」符合此條件
  的版本 merge commit 為其釋出版本／結案日來源。

  若同一 issue 對應多個 commit（例如先修正後又補一個 amendment commit），且它們
  被不同版本 merge commit 包含，取版本較晚（release merge 時間較晚）的一筆，
  代表該 issue 最終完整修正被包進去的版本。

只掃 master（或 main）分支的祖先歷史（不含尚未合併的 feature branch），
因為未合併進 master 的 commit 一定還沒上架。

用法：
  python3 scan_commits.py --weeks 2
  python3 scan_commits.py --weeks 2 --json-out /path/to/out.json

輸出：JSON array，每筆元素：
  {
    "jira_id": "LVB-8340",
    "release_version": "1.50.34",
    "release_date": "2026-09-03",              # 版本 merge commit 的 committer date（YYYY-MM-DD）
    "release_datetime_iso": "2026-09-03T10:55:17+08:00",
    "release_merge_hash": "...",
    "commit_hash": "...",
    "commit_subject": "[LVB-8340] fix(App): ...",
    "commit_date": "2026-08-31"
  }
"""

import argparse
import json
import re
import subprocess
import sys

RELEASE_MERGE_RE = re.compile(r"^Merge pull request #\d+ from \S+/([0-9]+\.[0-9]+\.[0-9]+)\s*$")
JIRA_RE = re.compile(r"^\[([A-Z]+-[0-9]+)\]")
FIELD_SEP = "\x1f"


def detect_main_branch() -> str:
    for candidate in ("master", "main"):
        r = subprocess.run(
            ["git", "rev-parse", "--verify", candidate],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return candidate
    raise SystemExit("找不到 master 或 main 分支，請確認在正確的 repo 內執行")


def load_commits(branch: str, weeks: int):
    r = subprocess.run(
        [
            "git", "log", branch,
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


def is_ancestor(commit_hash: str, target_hash: str) -> bool:
    r = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit_hash, target_hash],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    weeks = max(1, min(8, args.weeks))
    branch = detect_main_branch()
    commits = load_commits(branch, weeks)

    releases = []
    for c in commits:
        m = RELEASE_MERGE_RE.match(c["subject"])
        if m:
            releases.append({
                "version": m.group(1),
                "epoch": c["epoch"],
                "date_iso": c["date_iso"],
                "hash": c["hash"],
            })
    releases.sort(key=lambda r: r["epoch"])  # 時間序最早的版本 merge 排最前面

    def release_for(fix_hash: str):
        # 依時間序找「最早」把這個 commit 包進去的版本 merge，
        # 用 ancestry（真的被 merge 進去）而非日期比較，避免
        # 長壽命 feature branch 的 commit timestamp 早於實際 merge 時間造成誤判。
        for rel in releases:
            if is_ancestor(fix_hash, rel["hash"]):
                return rel
        return None

    candidates = {}
    for c in commits:
        m = JIRA_RE.match(c["subject"])
        if not m:
            continue
        jira_id = m.group(1)
        rel = release_for(c["hash"])
        if rel is None:
            continue  # 尚未隨任何版本 merge 進 master，跳過

        prev = candidates.get(jira_id)
        if prev is None or rel["epoch"] > prev["_release_epoch"]:
            candidates[jira_id] = {
                "jira_id": jira_id,
                "release_version": rel["version"],
                "release_date": rel["date_iso"][:10],
                "release_datetime_iso": rel["date_iso"],
                "release_merge_hash": rel["hash"],
                "commit_hash": c["hash"],
                "commit_subject": c["subject"],
                "commit_date": c["date_iso"][:10],
                "_release_epoch": rel["epoch"],
            }

    result = []
    for v in candidates.values():
        v.pop("_release_epoch", None)
        result.append(v)
    result.sort(key=lambda x: x["jira_id"])

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(out)
    print(out)


if __name__ == "__main__":
    main()
