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
