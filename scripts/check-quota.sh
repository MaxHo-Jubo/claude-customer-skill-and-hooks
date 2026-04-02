#!/bin/bash
# 查 Claude Max 多帳號額度
# 用法: bash ~/.claude/scripts/check-quota.sh (或 cq)
# 帳號設定從 ~/.claude/quota-accounts.json 讀取

CONFIG="$HOME/.claude/quota-accounts.json"

# 如果設定檔不存在，自動偵測 keychain 中的 Claude Code 帳號
if [ ! -f "$CONFIG" ]; then
    python3 -c "
import subprocess, json

# 掃描 keychain 找所有 Claude Code credentials
result = subprocess.run(['security', 'dump-keychain'], capture_output=True, text=True)
svcs = []
for line in result.stdout.split('\n'):
    if 'Claude Code-credentials' in line and 'svce' in line:
        svc = line.split('\"')[1] if '\"' in line else ''
        if svc and svc not in svcs:
            svcs.append(svc)

# 取得每個帳號的 email
accounts = []
for i, svc in enumerate(svcs):
    try:
        r = subprocess.run(['security', 'find-generic-password', '-s', svc, '-w'],
                          capture_output=True, text=True, timeout=5)
        d = json.loads(r.stdout.strip())
        token = d.get('claudeAiOauth', {}).get('accessToken', '')
        if token:
            import urllib.request
            req = urllib.request.Request(
                'https://api.anthropic.com/api/oauth/usage',
                headers={'Authorization': f'Bearer {token}', 'anthropic-beta': 'oauth-2025-04-20'}
            )
            accounts.append({'svc': svc, 'label': f'c{i+1}'})
    except:
        pass

import os
with open('$CONFIG', 'w') as f:
    json.dump(accounts, f, indent=2)
os.chmod('$CONFIG', 0o600)
print(f'自動偵測到 {len(accounts)} 個帳號，已存到 $CONFIG（權限 600）')
" 2>/dev/null
fi

# 主程式（全部用 Python urllib，token 不進 process list）
python3 -c "
import json, subprocess, time, os
from datetime import datetime, timezone, timedelta

CONFIG = os.path.expanduser('~/.claude/quota-accounts.json')

# 讀設定
try:
    with open(CONFIG) as f:
        accounts = json.load(f)
except:
    print('設定檔不存在，請先設定帳號')
    exit(1)

G = '\033[32m'
Y = '\033[33m'
R = '\033[31m'
DIM = '\033[2m'
BOLD = '\033[1m'
RST = '\033[0m'
CST = timezone(timedelta(hours=8))

def bar(pct):
    filled = pct // 5
    empty = 20 - filled
    c = R if pct >= 80 else (Y if pct >= 50 else G)
    return f'{c}{chr(9608) * filled}{chr(9617) * empty}{RST}'

def get_token(svc):
    try:
        r = subprocess.run(['security', 'find-generic-password', '-s', svc, '-w'],
                          capture_output=True, text=True, timeout=5)
        d = json.loads(r.stdout.strip())
        return d.get('claudeAiOauth', {}).get('accessToken', '')
    except:
        return ''

def get_usage(token):
    try:
        import urllib.request
        req = urllib.request.Request(
            'https://api.anthropic.com/api/oauth/usage',
            headers={'Authorization': f'Bearer {token}', 'anthropic-beta': 'oauth-2025-04-20'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except:
        return {}

hour = int(time.strftime('%H'))
peak = '\U0001f319 離峰 x2' if 5 <= hour < 22 else '\u2600\ufe0f  尖峰'

print()
print(f'{BOLD}Claude Max 帳號額度{RST}  {DIM}{peak}{RST}')
print(f'{DIM}' + '\u2500' * 49 + f'{RST}')

best_week = 999
best_name = ''
reset_str = ''

for acct in accounts:
    svc = acct['svc']
    label = acct.get('label', '?')

    token = get_token(svc)
    if not token:
        print(f'  {label:<25} {DIM}無法取得 token{RST}')
        continue

    d = get_usage(token)
    if not d:
        print(f'  {label:<25} {DIM}查詢失敗{RST}')
        continue

    week = int(d.get('seven_day', {}).get('utilization', 0))
    five = int(d.get('five_hour', {}).get('utilization', 0))

    r = d.get('seven_day', {}).get('resets_at', '')
    if r and not reset_str:
        t = datetime.fromisoformat(r).astimezone(CST)
        reset_str = t.strftime('%m/%d %H:%M')

    print(f'  {BOLD}{label:<25}{RST} {bar(week)} 週:{week:>3}%  5h:{five:>3}%')

    if week < best_week:
        best_week = week
        best_name = label

print(f'{DIM}' + '\u2500' * 49 + f'{RST}')
if reset_str:
    print(f'  週重置: {reset_str} CST')
if best_name:
    print(f'  {G}\U0001f449 最空: {best_name}（週 {best_week}%）{RST}')
print()
"
