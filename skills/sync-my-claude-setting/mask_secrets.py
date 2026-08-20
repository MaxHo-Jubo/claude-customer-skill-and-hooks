#!/usr/bin/env python3
"""
遮罩 JSON 結構中所有字串裡的 secret（API key / token 等），供 sync skill 複製或比對 settings.json 時使用。

背景：settings.json 的 permissions allow-list 會記錄使用者執行過的 Bash 命令，
其中可能含 `claude mcp add ... --api-key <secret>` 這類帶明文 secret 的命令。
若原封複製進 repo 會造成 secret 洩漏（曾發生 context7 API key 被同步進版控的事故）。
本模組遞迴遮罩所有已知格式的 secret，是「複製前一律先過濾」的單一權威來源。

用法（CLI）：python3 mask_secrets.py [--del-model] [--del-local] <file.json>  → stdout 輸出遮罩後 JSON
用法（import）：見 SKILL.md STEP 02 / STEP R2 的實際用法；公開符號為
              mask_secrets / strip_local_only / strip_private_permissions / find_private_content / LOCAL_ONLY_KEYS
"""
import json
import re
import sys

# 已知 secret token 格式：前綴夠 specific，不會誤傷路徑/domain/command 等正常內容
_KEY_PATTERN = re.compile(
    r'(sk-[A-Za-z0-9_-]{8,}'          # OpenAI / Anthropic 類
    r'|ctx7sk-[A-Za-z0-9_-]{8,}'      # context7
    r'|ghp_[A-Za-z0-9]{20,}'          # GitHub personal token
    r'|gho_[A-Za-z0-9]{20,}'          # GitHub OAuth token
    r'|github_pat_[A-Za-z0-9_]{20,}'  # GitHub fine-grained PAT
    r'|glpat-[A-Za-z0-9_-]{16,}'      # GitLab personal token
    r'|AKIA[A-Z0-9]{16}'              # AWS access key id
    r'|xox[baprs]-[A-Za-z0-9-]{10,})'  # Slack token
)
# 帶 secret 的 flag：遮罩其後緊接的值（--api-key xxx → --api-key ***MASKED***）
# 值捕獲排除 )、引號、反斜線與空白，避免吃掉 permission 命令字串結尾的 ) 等結構字元
_FLAG_PATTERN = re.compile(
    r"""(--api-key|--apikey|--token|--secret|--password)(\s*=?\s*)([^\s)"'\\]+)"""
)
# 遮罩後的佔位字串，與 mcp-servers.json 過濾邏輯保持一致
MASK = '***MASKED***'
# 本機專屬、一律不進 repo 的頂層 key（雙向排除，換機也不還原）
# autoMode.environment 記錄公司內部域名、私有 repo 名稱、本機絕對路徑，
# autoMode.soft_deny 記錄專案 deploy script 名稱——與 CLAUDE.md <conn> 同類的環境資訊，
# 而 repo 是 public，故整段排除（2026-08-17 使用者裁示）。
LOCAL_ONLY_KEYS = ('autoMode',)

# 私有識別符黑名單：組織名／私有 repo 名／內部域名／Jira 編號。
# **這是 denylist，本質不可能完備**——未列入的私有名稱會靜默放行，`find_private_content` 回空
# 只能證明「不含以下 pattern」，不能證明「無私有內容」。新增私有 repo／組織／域名時必須同步更新。
_PRIVATE_ID_PATTERN = re.compile(
    r'luna_RN_HomeCareStaff'          # 私有 repo（居服 App）
    r'|luna_web'                      # 私有 repo（luna 網站）
    r'|DayCareStaff|FamilyMember'     # 私有 repo（日照 App／家屬 App）
    r'|erpv3_web_(?:frontend|backend)'  # 私有 repo（v3 前後端）
    r'|compal[-_]swhq'                # GitHub 組織名（含底線變體）
    r'|compal-health\.com'            # 公司內部域名（含 staging）
    r'|\b(?:ERPD|LVB|LWM)-\d+',       # Jira 編號——常隨 commit message 夾帶工作內容外洩
    re.IGNORECASE,
)
# 家目錄路徑採 **allowlist 反轉**：`/Users/<user>/` 底下一律視為私有，除非第一層目錄在豁免清單。
# 改用反轉的理由：原本是 denylist（只認 Documents/Desktop/Downloads），`~/Projects`、`~/work`、
# `~/src` 等全部靜默放行，且失敗方向是「漏判即通過」。實測本機 settings.json 只有三類 home 路徑
# （Documents 26 / .claude 16 / .nvm 1），反轉的落地成本就是豁免清單這一行。
# 路徑單層片段：**正向白名單**（字母數字底線 + 點 + 連字號，\w 含 unicode 故涵蓋中文目錄名）。
# 不用「排除已知壞字元」的黑名單寫法：那要逐個補，而每漏一個就是一次靜默誤判——實測連中三次，
# 反引號（markdown 的 `~/Library`）、逗號（`~/Library`, `~/.maestro` 並列）、反斜線（settings.json
# 裡的 `$HOME/.nvm\`）都曾把目錄名污染成 "Library`" / ".nvm\" 而比對不到豁免清單。白名單的失敗
# 方向也是安全的：遇到非法字元就在該處截斷，截斷後的值同樣不在豁免清單，仍會被攔截。
# 抽成具名常數而非在 pattern 內重複寫兩次：同時用於 /Users/<user> 段與被擷取的第一層目錄段，
# 兩處必須一致；分開寫就是「改一處漏一處」等著發生。
_PATH_SEGMENT = r'[\w.-]+'
_HOME_PATH_PATTERN = re.compile(
    rf'(?:/Users/{_PATH_SEGMENT}|~|\$HOME)/({_PATH_SEGMENT})', re.IGNORECASE
)
# 豁免：hook / statusline 指令必須寫絕對路徑指向這些目錄，屬必要而非洩漏。
# **必須維持具名 allowlist，不可改成「dot-directory 一律豁免」的規則判準。** 曾試過後者（想一併解掉
# 下面 why-visible 說的誤濾復發），實測是偵測能力迴歸：`~/.acme-internal-project`、`~/.secret-client-work`
# 這類尚未被 _PRIVATE_ID_PATTERN 收錄的私有路徑會被無條件放行，兩層防線同時失守。這道防線守的是
# public repo，失敗方向必須是「寧可誤濾也不漏放」——誤濾會被下面的可見化立刻抓到，漏放不會。
# why-visible: 誤濾能復發三次（`~/Library` 見 df94390、`~/.maestro` 見 v1.8.1）的根因不是清單不夠長，
# 是**過濾動作不可見**——條目靜默消失、無任何警告。根治在 SKILL.md STEP 02 逐條印出被移除的內容，
# 不是把 allowlist 換成猜得到未來的規則。新工具目錄被誤濾時，當場就會在同步輸出看到，補一行即可。
_ALLOWED_HOME_DIRS = (
    '.claude', '.claude-max-2', '.claude-review', '.agents',  # Claude 設定與隔離帳號目錄
    '.nvm', '.npm', '.cache', '.config', '.local', '.ssh',    # 標準工具目錄（路徑本身不含專案資訊）
    '.maestro',                                               # Maestro 行動 App UI 測試工具（v1.8.1 補）
    'library',                                                # macOS ~/Library（系統路徑）
)
# marker 檔名等 dash-encoded 路徑（scripts/lib/review-marker.ts 的 markerPathForRepo 產物），
# 斜線被換成 dash 後上面的路徑 pattern 認不出來，需單獨比對
_DASH_PATH_PATTERN = re.compile(r'-Users-[^-\s]+-(?!claude|nvm|agents)[A-Za-z]', re.IGNORECASE)


def _mask_str(text):
    """遮罩單一字串中的 secret，回傳遮罩後字串。"""
    # STEP 01: 先遮罩 flag 後的值（--api-key <值> 這類）
    text = _FLAG_PATTERN.sub(lambda m: m.group(1) + m.group(2) + MASK, text)
    # STEP 02: 再遮罩裸露的已知格式 token
    text = _KEY_PATTERN.sub(MASK, text)
    return text


def mask_secrets(obj):
    """遞迴遮罩 JSON 結構（dict/list/str）中所有字串裡的 secret，回傳新結構（不 mutate 原物件）。"""
    # STEP 01: 字串直接遮罩
    if isinstance(obj, str):
        return _mask_str(obj)
    # STEP 02: list 逐項遞迴
    if isinstance(obj, list):
        return [mask_secrets(item) for item in obj]
    # STEP 03: dict 逐值遞迴（key 不含 secret，保留原順序）
    if isinstance(obj, dict):
        return {key: mask_secrets(value) for key, value in obj.items()}
    # STEP 04: 其餘型別（number/bool/null）原樣回傳
    return obj


def strip_local_only(obj):
    """
    移除本機專屬、不得進 repo 的頂層 key（LOCAL_ONLY_KEYS），回傳新 dict（不 mutate 原物件）。
    非 dict 原樣回傳。
    """
    # STEP 01: 非 dict 無 key 可移除，原樣回傳
    if not isinstance(obj, dict):
        return obj
    # STEP 02: 濾掉本機專屬 key，保留其餘原順序
    return {key: value for key, value in obj.items() if key not in LOCAL_ONLY_KEYS}


def find_private_content(obj, path='$'):
    """
    遞迴掃描 JSON 結構，找出仍殘留的私有內容（組織名／私有 repo／內部域名／本機專案路徑）。
    家目錄路徑僅在第一層目錄列於 `_ALLOWED_HOME_DIRS` 時豁免（hook / statusline 指令與標準工具目錄
    必需）；未列入者一律命中，包含 `~/.<未知>/` 形式——dot-directory 不構成豁免理由。
    @param obj 待掃描的 JSON 結構
    @param path 目前節點的 JSONPath，供回報定位
    @return list of (path, 命中的字串片段, 觸發原因)
    """
    hits = []
    # STEP 01: 字串節點才需比對
    if isinstance(obj, str):
        # STEP 01.01: 私有識別符（denylist）
        m = _PRIVATE_ID_PATTERN.search(obj)
        if m:
            hits.append((path, m.group(0), 'private-identifier'))
        # STEP 01.02: 家目錄路徑（allowlist 反轉）——逐一檢查每個命中的第一層目錄是否在豁免清單。
        # 不用「先 sub 掉豁免片段再比對」的寫法：那會讓 `~/.claude/state/.../-Users-x-Documents-y.json`
        # 這種夾帶在豁免路徑後方的內容整段漏網（實測過）。
        for match in _HOME_PATH_PATTERN.finditer(obj):
            # 第一層目錄不在具名豁免清單即視為本機專案路徑（未知一律攔截，見 _ALLOWED_HOME_DIRS 檔頭）
            if match.group(1).lower() not in _ALLOWED_HOME_DIRS:
                hits.append((path, match.group(0), 'local-project-path'))
        # STEP 01.03: dash-encoded 路徑（marker 檔名形式，斜線已被換成 dash）
        m = _DASH_PATH_PATTERN.search(obj)
        if m:
            hits.append((path, m.group(0), 'dash-encoded-path'))
        return hits
    # STEP 02: list 逐項遞迴
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            hits.extend(find_private_content(item, f'{path}[{i}]'))
        return hits
    # STEP 03: dict 逐值遞迴
    if isinstance(obj, dict):
        for key, value in obj.items():
            hits.extend(find_private_content(value, f'{path}.{key}'))
    return hits


def strip_private_permissions(obj):
    """
    從 permissions 的各個清單移除含私有內容的條目（如 `Bash(git -C /Users/<user>/Documents/<專案>/<repo> ...)`，
    波浪號與 $HOME 形式亦涵蓋）。
    這些條目在別台機器上本來就無效，且會把私有 repo 名、本機路徑、commit message 帶進 public repo。
    @param obj settings.json 的完整結構
    @return (新結構, 被移除的條目 list)
    """
    # STEP 01: 無 permissions 區段就原樣回傳
    if not isinstance(obj, dict) or not isinstance(obj.get('permissions'), dict):
        return obj, []
    removed = []
    new_perms = {}
    # STEP 02: 逐區段過濾，非 list 的設定值（如 defaultMode）原樣保留
    for section, items in obj['permissions'].items():
        if not isinstance(items, list):
            new_perms[section] = items
            continue
        kept = []
        for item in items:
            if find_private_content(item):
                removed.append(f'{section}: {item}')
            else:
                kept.append(item)
        new_perms[section] = kept
    # STEP 03: 回傳新結構，不 mutate 原物件
    return {**obj, 'permissions': new_perms}, removed


def main():
    """CLI 入口：讀取檔案 → 遮罩（可選刪除本機專屬欄位）→ stdout 輸出 JSON。"""
    # STEP 01: 解析參數（--del-model 排除 model 欄位、--del-local 排除 LOCAL_ONLY_KEYS，皆供 diff 對齊用）
    args = sys.argv[1:]
    del_model = '--del-model' in args
    del_local = '--del-local' in args
    args = [a for a in args if a not in ('--del-model', '--del-local')]
    if len(args) != 1:
        sys.stderr.write('用法：python3 mask_secrets.py [--del-model] [--del-local] <file.json>\n')
        sys.exit(2)
    # STEP 02: 讀取並遮罩
    with open(args[0]) as f:
        data = json.load(f)
    data = mask_secrets(data)
    # STEP 03: 選擇性刪除本機專屬欄位（model 供 diff 對齊；autoMode 等為雙向排除項）
    if del_model and isinstance(data, dict):
        data.pop('model', None)
    if del_local:
        data = strip_local_only(data)
    # STEP 04: 輸出（保留 key 原順序，避免造成假差異）
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
