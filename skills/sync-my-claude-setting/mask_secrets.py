#!/usr/bin/env python3
"""
遮罩 JSON 結構中所有字串裡的 secret（API key / token 等），供 sync skill 複製或比對 settings.json 時使用。

背景：settings.json 的 permissions allow-list 會記錄使用者執行過的 Bash 命令，
其中可能含 `claude mcp add ... --api-key <secret>` 這類帶明文 secret 的命令。
若原封複製進 repo 會造成 secret 洩漏（曾發生 context7 API key 被同步進版控的事故）。
本模組遞迴遮罩所有已知格式的 secret，是「複製前一律先過濾」的單一權威來源。

用法（CLI）：python3 mask_secrets.py [--del-model] <file.json>  → stdout 輸出遮罩後 JSON
用法（import）：from mask_secrets import mask_secrets; masked = mask_secrets(obj)
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


def main():
    """CLI 入口：讀取檔案 → 遮罩（可選刪除 model）→ stdout 輸出 JSON。"""
    # STEP 01: 解析參數（--del-model 供 diff 對齊時排除本機專屬 model 欄位）
    args = sys.argv[1:]
    del_model = False
    if '--del-model' in args:
        del_model = True
        args.remove('--del-model')
    if len(args) != 1:
        sys.stderr.write('用法：python3 mask_secrets.py [--del-model] <file.json>\n')
        sys.exit(2)
    # STEP 02: 讀取並遮罩
    with open(args[0]) as f:
        data = json.load(f)
    data = mask_secrets(data)
    # STEP 03: 選擇性刪除 model 欄位（僅供 diff，不影響實際複製流程）
    if del_model and isinstance(data, dict):
        data.pop('model', None)
    # STEP 04: 輸出（保留 key 原順序，避免造成假差異）
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
