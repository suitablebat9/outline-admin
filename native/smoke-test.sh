#!/usr/bin/env bash
# Exercise setup on an ephemeral Ubuntu runner using a local test certificate.
set -euo pipefail
host=ike.test.invalid
state=/etc/apple-ikev2
install -d -m 700 "$state"
echo "$host" > "$state/hostname"
echo 'dns_cloudflare_api_token = test' > "$state/cloudflare.ini"
lineage=/etc/letsencrypt/live/$host
mkdir -p "$lineage"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$host" \
    -addext "subjectAltName=DNS:$host" -keyout "$lineage/privkey.pem" -out "$lineage/cert.pem"
cp "$lineage/cert.pem" "$lineage/chain.pem"
stub=$(mktemp -d)
printf '#!/bin/sh\nexit 0\n' > "$stub/certbot"
chmod 700 "$stub/certbot"
export PATH="$stub:$PATH"
# Supply a terminal to the interactive installer.
printf 'appletest\n' | script -qec 'bash native/install.sh' /dev/null
swanctl --list-conns | grep 'apple:'
swanctl --list-pools | grep apple4
swanctl --list-certs | grep "$host"
systemctl is-active apple-ikev2-network.service
# Exercise the dashboard's account backend against a live strongSwan daemon.
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
python3 -m venv "$stub/test-env"
"$stub/test-env/bin/pip" install -q vici==6.0.3
"$stub/test-env/bin/python" - <<'PY'
import subprocess
import native_accounts as accounts
assert accounts.listing()['online']
assert 'appletest' in accounts.load()
user = accounts.change('native-test')
section, password = accounts.load()['native-test']
assert user['password'] == password
with accounts.gateway() as client:
    assert section.encode() in client.get_shared()['keys']
subprocess.run(['systemctl', 'restart', 'strongswan'], check=True)
with accounts.gateway() as client:
    assert section.encode() in client.get_shared()['keys']
accounts.change('native-test', remove=True)
assert set(accounts.load()) == {'appletest'}
with accounts.gateway() as client:
    assert section.encode() not in client.get_shared()['keys']
PY
