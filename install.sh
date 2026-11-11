#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo 'Run this installer as root inside the VPN guest.' >&2
  exit 1
fi

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
apt-get update
apt-get install -y python3 python3-venv nginx ca-certificates curl
install -d -m 0755 /opt/outline-admin
install -d -m 0700 /etc/outline-admin /var/lib/outline-admin
cp "$source_dir/"*.py "$source_dir/requirements.txt" /opt/outline-admin/
cp -R "$source_dir/templates" "$source_dir/static" /opt/outline-admin/
python3 -m venv /opt/outline-admin/venv
/opt/outline-admin/venv/bin/pip install -r /opt/outline-admin/requirements.txt

/opt/outline-admin/venv/bin/python /opt/outline-admin/installer_config.py

cat > /etc/systemd/system/outline-admin.service <<'EOF'
[Unit]
Description=WireGuard device dashboard
Wants=network-online.target
After=network-online.target

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
ReadWritePaths=-/etc/outline-wireguard /var/lib/outline-admin /run/lock

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

nginx -t
systemctl daemon-reload
systemctl enable outline-admin
systemctl restart outline-admin
systemctl enable --now nginx
systemctl reload nginx

/opt/outline-admin/venv/bin/python <<'PY'
import time
import urllib.request
for url in ['http://127.0.0.1:18083/api/session']:
    for attempt in range(15):
        try:
            with urllib.request.urlopen(url,timeout=3) as response:
                assert response.status==200
            break
        except Exception:
            if attempt==14:
                raise SystemExit('Service startup check failed. Run journalctl -u outline-admin -n 60')
            time.sleep(1)
print('Services are responding.')
PY

echo
echo 'Dashboard ready on port 18082.'
