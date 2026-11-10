"""Interactive deployment settings and initial Outline configuration."""
import getpass
import json
from pathlib import Path
import secrets
import shutil
from urllib.parse import urlsplit
import yaml
from werkzeug.security import generate_password_hash
from manager import atomic
from profiles import hostname, generate


def prompt(label):
    # Works when the bootstrap is piped to bash: input comes from the terminal.
    with open('/dev/tty','r+') as terminal:
        terminal.write(label);terminal.flush()
        return terminal.readline().strip()


def main():
    path=Path('/etc/outline-admin/settings.json')
    if path.exists():
        settings=json.loads(path.read_text())
        print('Preserving existing domain settings, credentials, and history.')
    else:
        vpn=hostname(prompt('VPN hostname (for example vpn.example.com): '))
        admin=hostname(prompt('Admin hostname (for example admin.example.com): '))
        if vpn==admin:
            raise SystemExit('Use different hostnames for VPN and administration.')
        while True:
            password=getpass.getpass('Choose an admin password (14+ characters): ')
            if len(password)>=14 and password==getpass.getpass('Confirm password: '):break
            print('Password too short or confirmation did not match.')
        settings={'username':'admin','password_hash':generate_password_hash(password),
          'session_secret':secrets.token_urlsafe(48),'origin':'https://'+admin,
          'vpn_domain':vpn,'secure_cookie':True}
        atomic(path,json.dumps(settings,indent=2)+'\n',0o600)
    vpn=hostname(settings['vpn_domain'])
    admin=hostname(urlsplit(settings['origin']).hostname or '')
    config_path=Path('/etc/outline-ws/config.yaml')
    if not config_path.exists():
        config={'web':{'servers':[{'id':'websocket','listen':['127.0.0.1:18080']}]},
          'services':[{'listeners':[
            {'type':'websocket-stream','web_server':'websocket','path':'/'+secrets.token_hex(24)},
            {'type':'websocket-packet','web_server':'websocket','path':'/'+secrets.token_hex(24)}],
            'keys':[{'id':'_admin_reserved','cipher':'chacha20-ietf-poly1305','secret':secrets.token_urlsafe(48)}]}]}
        atomic(config_path,yaml.safe_dump(config,sort_keys=False),0o640)
        shutil.chown(config_path,user='root',group='outline-ws')
    config=yaml.safe_load(config_path.read_text())
    services=[s for s in config.get('services',[]) if {'websocket-stream','websocket-packet'}<={x.get('type') for x in s.get('listeners',[])}]
    if len(services)!=1:
        raise SystemExit('Expected exactly one WebSocket service in config.yaml.')
    profile_dir=Path('/var/lib/outline-ws/profiles');profile_dir.mkdir(mode=0o755,exist_ok=True)
    profile=profile_dir/'outline-dns.mobileconfig'
    profile.write_bytes(generate([vpn,admin]));profile.chmod(0o644)
    # The installer owns these listeners; existing VPN keys and paths are retained.
    web_server=next(s for s in config['web']['servers'] if s['id']==services[0]['listeners'][0]['web_server'])
    upstream=web_server['listen'][0]
    if not isinstance(upstream,str) or not __import__('re').fullmatch(r'127\.0\.0\.1:\d{1,5}',upstream):
        raise SystemExit('This installer supports an Outline WebSocket listener on 127.0.0.1:<port>.')
    Path('/etc/nginx/conf.d/outline-ws.conf').write_text('''server {
    listen 18081;
    server_name '''+vpn+''';
    server_tokens off;
    access_log off;
    location /keys/ {
        root /var/lib/outline-ws;
        autoindex off;
        default_type text/plain;
        add_header Cache-Control "no-store" always;
        try_files $uri =404;
    }
    location /profiles/ {
        root /var/lib/outline-ws;
        autoindex off;
        default_type application/x-apple-aspen-config;
        add_header Content-Disposition 'attachment; filename="outline-dns.mobileconfig"';
        try_files $uri =404;
    }
    location / {
        proxy_pass http://'''+upstream+''';
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
    }
}
''')
    print('Cloudflare routes:')
    print(f'  {vpn} -> HTTP -> YOUR_SERVER_IP:18081')
    print(f'  {admin} -> HTTP -> YOUR_SERVER_IP:18082')


if __name__=='__main__':main()
