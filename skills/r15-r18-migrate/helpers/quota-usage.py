#!/usr/bin/env python3
"""查詢目前帳號的用量額度，供 runner 判斷「現在該不該取下一個模組」。

輸出一律是單行 JSON 到 stdout，只含使用率與重置時間，**絕不印出 token**。
token 來源優先序：環境變數 CLAUDE_CODE_OAUTH_TOKEN → macOS Keychain（含 hash 後綴的項目）。

exit code：
  0 = 查得到用量（stdout 的 available 為 true）
  3 = 查不到（沒有 token、或 API 不可用；stdout 的 available 為 false、error 為原因）
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# 用量查詢端點與必要的 beta 標頭（OAuth token 專用）
USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"

# Keychain 中憑證項目的服務名前綴；同一台機器可能有多個（不同設定目錄各自一份，帶 hash 後綴）
KEYCHAIN_SERVICE_PREFIX = "Claude Code-credentials"

# 外部指令與網路呼叫的逾時秒數（避免 runner 主迴圈被卡住）
KEYCHAIN_TIMEOUT_SECONDS = 5
DUMP_KEYCHAIN_TIMEOUT_SECONDS = 20
HTTP_TIMEOUT_SECONDS = 10

# exit code 常數
EXIT_OK = 0
EXIT_UNAVAILABLE = 3


def token_from_env():
    """從環境變數取 OAuth token。

    回傳 (token, source)；取不到時 token 為空字串。
    """
    # STEP 01: 直接讀環境變數，空白字元去掉後才判斷是否有值
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if token:
        return token, "env"
    return "", ""


def keychain_service_names():
    """列出 Keychain 中所有 Claude Code 憑證項目的服務名。

    回傳服務名清單（可能為空）；dump-keychain 失敗時回空清單，由呼叫端處理。
    """
    names = []
    # STEP 01: dump-keychain 只列出項目屬性，不含密碼本體，不會洩漏 token
    try:
        result = subprocess.run(
            ["security", "dump-keychain"],
            capture_output=True,
            text=True,
            timeout=DUMP_KEYCHAIN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            json.dumps({"available": False, "error": "dump-keychain 失敗: %s" % type(exc).__name__}),
            file=sys.stderr,
        )
        return names

    # STEP 02: 逐行找 svce 屬性中含憑證前綴的項目，取雙引號內的服務名
    for line in result.stdout.splitlines():
        if KEYCHAIN_SERVICE_PREFIX not in line or "svce" not in line:
            continue
        parts = line.split('"')
        if len(parts) < 2:
            continue
        service = parts[1]
        if service and service not in names:
            names.append(service)
    return names


def token_from_keychain():
    """從 Keychain 逐一嘗試取出可用的 OAuth token。

    回傳 (token, source)；全部取不到時 token 為空字串。
    """
    # STEP 01: 先列出候選服務名，沒有就直接回空
    for service in keychain_service_names():
        # STEP 02: 逐個讀出憑證 JSON，解析 accessToken；失敗就換下一個，不中斷
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True,
                text=True,
                timeout=KEYCHAIN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        try:
            payload = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            continue
        token = payload.get("claudeAiOauth", {}).get("accessToken", "")
        if token:
            return token, "keychain"
    return "", ""


def fetch_usage(token):
    """呼叫用量 API。

    回傳 (data, error)：成功時 data 是解析後的 dict、error 為 None；
    失敗時 data 為 None、error 是**不含 token 的**原因字串。
    """
    request = urllib.request.Request(
        USAGE_API_URL,
        headers={
            "Authorization": "Bearer %s" % token,
            "anthropic-beta": OAUTH_BETA_HEADER,
        },
    )
    # STEP 01: 例外訊息只取狀態碼與類型名，避免把帶 token 的 request 內容印出來
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read()), None
    except urllib.error.HTTPError as exc:
        return None, "HTTP %s" % exc.code
    except urllib.error.URLError:
        return None, "網路不可用"
    except (json.JSONDecodeError, ValueError):
        return None, "回應不是合法 JSON"
    except OSError as exc:
        return None, "連線失敗: %s" % type(exc).__name__


def window_summary(data, key):
    """把單一額度視窗（five_hour / seven_day）整理成只含使用率與重置時間的 dict。"""
    window = data.get(key) or {}
    # STEP 01: utilization 有可能是字串或缺漏，一律轉成 int，轉不動就當 0
    try:
        utilization = int(float(window.get("utilization", 0)))
    except (TypeError, ValueError):
        utilization = 0
    return {"utilization": utilization, "resets_at": window.get("resets_at")}


def main():
    """主流程：取 token → 查 API → 印出精簡結果。"""
    # STEP 01: 依優先序取 token，兩個來源都沒有就直接回報不可用
    token, source = token_from_env()
    if not token:
        token, source = token_from_keychain()
    if not token:
        print(json.dumps({"available": False, "error": "找不到可用的 token（環境變數與 Keychain 皆無）"}))
        return EXIT_UNAVAILABLE

    # STEP 02: 查 API；失敗時回報不可用，runner 會依決策把它當成「額度 API 不可用」處理
    data, error = fetch_usage(token)
    if data is None:
        print(json.dumps({"available": False, "source": source, "error": error}))
        return EXIT_UNAVAILABLE

    # STEP 03: 只輸出使用率與重置時間兩個欄位，其他原始欄位一律丟棄
    print(
        json.dumps(
            {
                "available": True,
                "source": source,
                "five_hour": window_summary(data, "five_hour"),
                "seven_day": window_summary(data, "seven_day"),
            }
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
