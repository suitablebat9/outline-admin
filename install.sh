#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo 'Run this installer as root inside the Outline LXC.' >&2
  exit 1
fi

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
outline_ports="18082 18083 19090"
if ! test -f /etc/outline-ws/config.yaml; then outline_ports="$outline_ports 18080 18081"; fi
for port in $outline_ports; do
  if ss -H -lnt "sport = :$port" | grep -q .; then
    if ! test -f /etc/outline-admin/settings.json; then
      echo "Port $port is already occupied. Resolve this before installing." >&2
      exit 1
    fi
  fi
done

apt-get update
apt-get install -y python3 python3-venv nginx ca-certificates curl
install -d -m 0755 /opt/outline-admin
install -d -m 0700 /etc/outline-admin /var/lib/outline-admin
install -d -m 0755 /var/lib/outline-ws/keys
cp "$source_dir/"*.py "$source_dir/requirements.txt" /opt/outline-admin/
cp -R "$source_dir/templates" "$source_dir/static" "$source_dir/client-profiles" /opt/outline-admin/
python3 -m venv /opt/outline-admin/venv
/opt/outline-admin/venv/bin/pip install -r /opt/outline-admin/requirements.txt

if ! id outline-ws >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin outline-ws
fi
install -d -m 0750 -o root -g outline-ws /etc/outline-ws
if ! test -x /usr/local/bin/outline-ws; then
  case "$(uname -m)" in
    x86_64) outline_arch=x86_64 ;;
    aarch64) outline_arch=arm64 ;;
    *) echo 'Unsupported architecture'; exit 1 ;;
  esac
  outline_temp="$(mktemp -d)"
  trap 'rm -rf "$outline_temp"' EXIT
  outline_archive="outline-ss-server_1.9.2_linux_${outline_arch}.tar.gz"
  outline_base='https://github.com/OutlineFoundation/tunnel-server/releases/download/v1.9.2'
  curl -fsSL "$outline_base/$outline_archive" -o "$outline_temp/$outline_archive"
  curl -fsSL "$outline_base/checksums.txt" -o "$outline_temp/checksums.txt"
  (cd "$outline_temp" && grep -F "$outline_archive" checksums.txt | sha256sum -c -)
  tar --no-same-owner -xzf "$outline_temp/$outline_archive" -C "$outline_temp"
  install -m 0755 "$outline_temp/outline-ss-server" /usr/local/bin/outline-ws
fi
/opt/outline-admin/venv/bin/python /opt/outline-admin/installer_config.py
if ! test -f /etc/systemd/system/outline-ws.service; then
cat > /etc/systemd/system/outline-ws.service <<'EOF'
[Unit]
Description=Outline WebSocket server
Wants=network-online.target
After=network-online.target
[Service]
User=outline-ws
Group=outline-ws
ExecStart=/usr/local/bin/outline-ws -config=/etc/outline-ws/config.yaml
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
[Install]
WantedBy=multi-user.target
EOF
fi

install -d -m 0755 /etc/systemd/system/outline-ws.service.d
cat > /etc/systemd/system/outline-ws.service.d/admin-metrics.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/local/bin/outline-ws -config=/etc/outline-ws/config.yaml -metrics=127.0.0.1:19090
EOF

cat > /etc/systemd/system/outline-admin.service <<'EOF'
[Unit]
Description=Outline Admin dashboard
Wants=network-online.target outline-ws.service
After=network-online.target outline-ws.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/outline-admin
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/outline-admin/venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:18083 --timeout 120 --access-logfile /dev/null wsgi:app
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=-/etc/swanctl/conf.d /etc/outline-ws /var/lib/outline-ws/keys /var/lib/outline-admin /run/lock

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/conf.d/outline-admin.conf <<'EOF'
server {
    listen 18082;
    server_name _;
    server_tokens off;
    access_log off;
    client_max_body_size 8k;
    location / {
        proxy_pass http://127.0.0.1:18083;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}
EOF

cat > /usr/local/bin/outline-admin-password <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
/opt/outline-admin/venv/bin/python /opt/outline-admin/reset_password.py
systemctl restart outline-admin
EOF
chmod 0755 /usr/local/bin/outline-admin-password

cat > /usr/local/bin/outline-admin-email-setup <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
/opt/outline-admin/venv/bin/python /opt/outline-admin/setup_email.py
EOF
chmod 0755 /usr/local/bin/outline-admin-email-setup

nginx -t
systemctl daemon-reload
systemctl enable outline-ws
systemctl restart outline-ws
systemctl enable outline-admin
systemctl restart outline-admin
systemctl enable --now nginx
systemctl reload nginx

/opt/outline-admin/venv/bin/python <<'PY'
import time
import urllib.request
for url in ['http://127.0.0.1:19090/metrics','http://127.0.0.1:18083/api/session']:
    for attempt in range(15):
        try:
            with urllib.request.urlopen(url,timeout=3) as response:
                assert response.status==200
            break
        except Exception:
            if attempt==14:
                raise SystemExit('Service startup check failed. Run journalctl -u outline-admin -u outline-ws -n 60')
            time.sleep(1)
print('Services are responding.')
PY

echo
echo 'Installation complete. Add a Cloudflare Tunnel public hostname:'
/opt/outline-admin/venv/bin/python -c 'import json; s=json.load(open("/etc/outline-admin/settings.json")); print("  "+s["origin"]+" -> HTTP -> YOUR_SERVER_IP:18082"); print("  https://"+s["vpn_domain"]+" -> HTTP -> YOUR_SERVER_IP:18081")'
echo 'Then sign in over HTTPS as admin with your chosen password.'
echo 'LXC addresses:'
hostname -I
