#!/bin/bash
set -euo pipefail
install -d -m 0700 /etc/outline-admin
python3 - <<'PY'
import hashlib,json,secrets
digest = hashlib.pbkdf2_hmac('sha256',b'ci-only-example',b'test',10000).hex()
json.dump(dict(session_secret=secrets.token_hex(32),password_hash='pbkdf2:sha256:10000$test$'+digest,
               origin='https://admin.example.com',vpn_domain='vpn.example.com'),open('/etc/outline-admin/settings.json','w'))
PY
printf '127.0.0.1\n35443\n' | script -qec 'bash wireguard/setup.sh' /dev/null
ip address add 198.18.1.1/32 dev lo
temp=$(mktemp -d)
echo 'WireGuard over Shadowsocks verified' > "$temp/probe"
python3 -m http.server 35801 --bind 198.18.1.1 --directory "$temp" >/dev/null 2>&1 &
web=$!
trap 'kill "$web"; rm -rf "$temp"; ip address del 198.18.1.1/32 dev lo' EXIT
python3 wireguard/smoke.py
