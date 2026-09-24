"""可設定情境的假 gh：分辨 `pr create` 與 `pr list`，PR 清單存在狀態檔裡、兩個子命令共用（1.1.2 第五批階段二）。

`review_fixtures.write_fake_gh` 不分辨子命令、一律 exit 0；這支用在要造「PR 已存在／只有已關閉的 PR／查詢失敗／
create 失敗或空輸出」的情境。`pr list` 真的依 `--head`、`--base`、`--state`（省略時同 gh 預設 open）、`--limit` 過濾，
不是直接回空——「只有已關閉的舊 PR」要靠 `--state open` 才過濾得掉。`pr create` 遇到同 head／base 的 open PR 時
照真 gh 的樣子以非零退出、stderr 印既有連結。

`pr list` 每筆印 {url, isCrossRepository, headRefOid}（不看 --json 要了哪些欄位）；和真 gh 一樣 `--head` 只比分支名、不分 owner，
fork 上同名分支的 PR 也會列出（cross=true）。

狀態檔（JSON）欄位：
  prs          PR 清單，每筆 {url, head, base, state}；選填 cross（fork 開的，create 不把它算成「已存在」）、
               head_oid（headRefOid；不給就取 write_scripted_gh 的 remote 上 head 分支現在的 commit）
  list_mode    ok／fail（非零退出）／notjson（exit 0 但輸出不是 JSON）／badshape（exit 0、JSON 但不是陣列）／
               notdict（陣列元素是字串不是物件）／nocross／nohead（每筆缺 isCrossRepository／headRefOid）／
               ignorelimit（不理 --limit，符合的全部印出）
  create_mode  ok／fail（非零退出、沒建立）／empty（建立了、exit 0 但沒輸出）／fail_after_create（建立了、非零退出）
  next_number  下一個 PR 編號
呼叫紀錄檔一行一個 JSON：{cmd, head, base, state}。
"""

import json
import os
import stat
import sys

# 假 gh 新建 PR 時連結的前綴（.invalid 是保留網域）；編號接在後面
FAKE_PR_URL_PREFIX = "https://example.invalid/pull/"
# 新建 PR 的第一個編號：與 review_fixtures 的 FAKE_PR_URL（7）、EXISTING_PR_URL（3）錯開，斷言時分得出是哪一支開的
FIRST_PR_NUMBER = 100

# 假 gh 本體；三個 %r 依序是狀態檔、呼叫紀錄檔、bare 遠端路徑（None 表示沒有），%s 是 PR 連結前綴
SCRIPT_TEMPLATE = r'''
import json, subprocess, sys
STATE_PATH = %r
CALLS_PATH = %r
REMOTE_PATH = %r
args = sys.argv[1:]


def opt(name):
    """取 `--name value` 的值；沒有回 None。"""
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def head_oid(pr):
    """PR 的 headRefOid：有指定就用指定值，否則同 GitHub——遠端 head 分支現在的 commit（分支不存在或沒給遠端是空字串）。"""
    if pr.get("head_oid") is not None:
        return pr["head_oid"]
    if not REMOTE_PATH:
        return ""
    result = subprocess.run(["git", "--git-dir=" + REMOTE_PATH, "rev-parse", "--verify", "--quiet", "refs/heads/" + pr["head"]],
                            capture_output=True, text=True)
    return result.stdout.strip()


with open(STATE_PATH, encoding="utf-8") as handle:
    state = json.load(handle)
command = " ".join(args[:2])
head, base = opt("--head"), opt("--base")
with open(CALLS_PATH, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"cmd": command, "head": head, "base": base, "state": opt("--state")}) + "\n")
same_pair = [pr for pr in state["prs"] if pr["head"] == head and pr["base"] == base]
if command == "pr list":
    mode = state["list_mode"]
    if mode == "fail":
        sys.stderr.write("HTTP 502: Bad Gateway (https://api.github.invalid/graphql)\n")
        sys.exit(1)
    if mode == "notjson":
        print("Showing 1 of 1 open pull request")
        sys.exit(0)
    if mode == "badshape":
        print(json.dumps({"url": same_pair[0]["url"] if same_pair else ""}))
        sys.exit(0)
    wanted = opt("--state") or "open"
    # gh 的 --head 只比分支名、不分 owner：fork 上同名分支開往同一個 base 的 PR 也會列出來（isCrossRepository=true）
    hits = [
        {"url": pr["url"], "isCrossRepository": bool(pr.get("cross")), "headRefOid": head_oid(pr)}
        for pr in same_pair
        if wanted == "all" or pr["state"] == wanted
    ]
    if mode == "notdict":
        print(json.dumps([hit["url"] for hit in hits]))
        sys.exit(0)
    if mode in ("nocross", "nohead"):
        dropped = "isCrossRepository" if mode == "nocross" else "headRefOid"
        print(json.dumps([{key: value for key, value in hit.items() if key != dropped} for hit in hits]))
        sys.exit(0)
    print(json.dumps(hits if mode == "ignorelimit" else hits[: int(opt("--limit") or 30)]))
    sys.exit(0)
if command == "pr create":
    mode = state["create_mode"]
    if mode == "fail":
        sys.stderr.write("GraphQL: something went wrong\n")
        sys.exit(1)
    existing = [pr for pr in same_pair if pr["state"] == "open" and not pr.get("cross")]
    if existing:
        sys.stderr.write('a pull request for branch "%%s" into branch "%%s" already exists:\n%%s\n' %% (head, base, existing[0]["url"]))
        sys.exit(1)
    url = "%s%%d" %% state["next_number"]
    state["next_number"] += 1
    state["prs"].append({"url": url, "head": head, "base": base, "state": "open"})
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    if mode == "empty":
        sys.exit(0)
    if mode == "fail_after_create":
        sys.stderr.write("context deadline exceeded\n")
        sys.exit(1)
    print(url)
    sys.exit(0)
sys.stderr.write("fake gh: unsupported command %%r\n" %% (args,))
sys.exit(2)
'''


def write_scripted_gh(directory, prs=None, list_mode="ok", create_mode="ok", remote=None):
    """建立一支可設定情境的假 gh。

    @param directory 放腳本、狀態檔與紀錄檔的目錄
    @param prs 一開始就存在的 PR 清單（每筆 {url, head, base, state}，選填 cross、head_oid）；None 表示沒有
    @param list_mode `pr list` 的情境，見模組 docstring
    @param create_mode `pr create` 的情境，見模組 docstring
    @param remote bare 遠端路徑：沒指定 head_oid 的 PR，headRefOid 取遠端 head 分支現在的 commit；None 時是空字串
    @return dict：bin（腳本路徑）、state（狀態檔）、calls（呼叫紀錄檔）
    """
    # STEP 01: 狀態檔
    # 三個檔案的路徑
    paths = {
        "bin": os.path.join(directory, "scripted-gh"),
        "state": os.path.join(directory, "scripted-gh.state.json"),
        "calls": os.path.join(directory, "scripted-gh.calls"),
    }
    with open(paths["state"], "w", encoding="utf-8") as handle:
        json.dump({"prs": list(prs or []), "list_mode": list_mode, "create_mode": create_mode, "next_number": FIRST_PR_NUMBER}, handle)
    # STEP 02: 腳本（用跑測試的同一個直譯器，-B 不留 __pycache__）＋可執行權限
    with open(paths["bin"], "w", encoding="utf-8") as handle:
        handle.write("#!%s -B\n" % sys.executable)
        handle.write(SCRIPT_TEMPLATE % (paths["state"], paths["calls"], remote, FAKE_PR_URL_PREFIX))
    os.chmod(paths["bin"], os.stat(paths["bin"]).st_mode | stat.S_IXUSR)
    return paths


def set_gh_modes(gh, **modes):
    """改假 gh 的情境（list_mode／create_mode），PR 清單不動。

    @param gh write_scripted_gh 的回傳值
    @param modes 要改的欄位
    @return None
    """
    # STEP 01: 讀 → 合併 → 寫
    with open(gh["state"], encoding="utf-8") as handle:
        # 目前的狀態
        state = json.load(handle)
    with open(gh["state"], "w", encoding="utf-8") as handle:
        json.dump(dict(state, **modes), handle)


def gh_prs(gh):
    """假 gh 目前記得的 PR 清單。

    @param gh write_scripted_gh 的回傳值
    @return PR dict 清單
    """
    # STEP 01: 直接讀狀態檔
    with open(gh["state"], encoding="utf-8") as handle:
        return json.load(handle)["prs"]


def gh_commands(gh):
    """假 gh 被呼叫過的子命令（依序），例如 ["pr list", "pr create"]。

    @param gh write_scripted_gh 的回傳值
    @return 子命令字串清單；沒被呼叫過是空清單
    """
    # STEP 01: 紀錄檔不存在＝沒被呼叫過
    if not os.path.exists(gh["calls"]):
        return []
    with open(gh["calls"], encoding="utf-8") as handle:
        return [json.loads(line)["cmd"] for line in handle if line.strip()]
