#!/bin/bash
set -euo pipefail
umask 077
[[ $EUID == 0 && ! -d /etc/pve ]] || { echo 'Use the root console of your dashboard LXC.' >&2; exit 1; }
repo=${OUTLINE_ADMIN_REPOSITORY:-suitablebat9/outline-admin}
version=v0.4.1
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL --retry 3 "https://github.com/$repo/archive/refs/tags/$version.tar.gz" -o "$tmp/app.tgz"
mkdir "$tmp/app"
tar --no-same-owner --strip-components=1 -xzf "$tmp/app.tgz" -C "$tmp/app"
bash "$tmp/app/wireguard/setup.sh"
