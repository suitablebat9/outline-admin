#!/usr/bin/env bash
# Download the versioned application and launch its interactive LXC installer.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo 'Run this command as root inside your Debian/Ubuntu Outline LXC.' >&2
  exit 1
fi
command -v curl >/dev/null || { echo 'Install curl first: apt-get update && apt-get install -y curl'; exit 1; }


outline_release='v0.3.0'
outline_repository="${OUTLINE_ADMIN_REPOSITORY:-suitablebat9/outline-admin}"
outline_download="$(mktemp -d)"
trap 'rm -rf "$outline_download"' EXIT
curl --fail --show-error --silent --location --retry 3 \
  "https://github.com/${outline_repository}/archive/refs/tags/${outline_release}.tar.gz" \
  --output "$outline_download/source.tar.gz"
mkdir "$outline_download/source"
tar --no-same-owner -xzf "$outline_download/source.tar.gz" \
  --strip-components=1 -C "$outline_download/source"
bash "$outline_download/source/install.sh"
