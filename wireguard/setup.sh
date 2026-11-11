#!/bin/bash
set -euo pipefail
umask 077
[[ $EUID == 0 && ! -d /etc/pve ]] || { echo 'Run in the dashboard guest as root.' >&2; exit 1; }
source_dir=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
case "$(dpkg --print-architecture)" in
  amd64) arch=amd64; digest=699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968 ;;
  arm64) arch=arm64; digest=436441f76ee2f7fe21b5b2d426d3cb261a480455a704865789ad533e4273ec26 ;;
  *) echo 'Requires an amd64 or arm64 guest.' >&2; exit 1 ;;
esac
if [[ ! -f /etc/outline-wireguard/devices.json ]]; then
  read -rp 'Working home public IPv4: ' address </dev/tty
  read -rp 'External TCP port forwarded to this LXC (default 443): ' port </dev/tty
  port=${port:-443}
  python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1]); assert 0 < int(sys.argv[2]) < 65536' "$address" "$port"
  if [[ -n $(ss -H -lnt "sport = :$port") || -n $(ss -H -lun 'sport = :51820') ]]; then
    echo 'Selected TCP port or UDP 51820 is already occupied in the LXC.' >&2; exit 1
  fi
fi
archive="sing-box-1.14.4-linux-$arch"
curl -fsSL --retry 3 "https://github.com/SagerNet/sing-box/releases/download/v1.14.4/$archive.tar.gz" -o "$tmp/box.tgz"
(cd "$tmp" && echo "$digest  box.tgz" | sha256sum -c -)
tar --no-same-owner -xzf "$tmp/box.tgz" -C "$tmp" "$archive/sing-box"
install -d -m 0755 /usr/local/lib/outline-wireguard
install -m 0755 "$tmp/$archive/sing-box" /usr/local/lib/outline-wireguard/sing-box
install -d -m 0700 /etc/outline-wireguard
if [[ ! -f /etc/outline-wireguard/devices.json ]]; then
  python3 "$source_dir/wg_accounts.py" init "$address" "$port"
fi
(umask 022; bash "$source_dir/install.sh")
install -m 0644 "$source_dir/wg_accounts.py" /usr/local/lib/outline-wireguard/gateway.py
if ! id outline-wireguard >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin outline-wireguard
fi
cat >/etc/systemd/system/outline-wireguard.service <<'UNIT'
[Unit]
Description=WireGuard and Shadowsocks gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=outline-wireguard
RuntimeDirectory=outline-wireguard
RuntimeDirectoryMode=0700
WorkingDirectory=/run/outline-wireguard
ExecStartPre=+/usr/bin/python3 /usr/local/lib/outline-wireguard/gateway.py render /run/outline-wireguard/server.json
ExecStartPre=/usr/local/lib/outline-wireguard/sing-box check -c /run/outline-wireguard/server.json
ExecStart=/usr/local/lib/outline-wireguard/sing-box run -c /run/outline-wireguard/server.json
ExecStartPost=/usr/bin/python3 /usr/local/lib/outline-wireguard/gateway.py ready /run/outline-wireguard/server.json
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable outline-wireguard.service
systemctl restart outline-wireguard.service
# Retire the old listeners only after the replacement gateway and dashboard are running.
bash "$source_dir/wireguard/retire-legacy.sh"
echo 'Open the dashboard to manage devices and view network usage.'
