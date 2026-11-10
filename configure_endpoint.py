"""Pin the WebSocket dial address without changing TLS/HTTP hostnames or secrets."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
import yaml
from manager import atomic




def migrate(keydir, domain, endpoint):
    changed = 0
    for path in Path(keydir).glob('*.yaml'):
        if path.is_symlink():
            continue
        config = yaml.safe_load(path.read_text())
        if not isinstance(config, dict):
            continue
        transport = config.get('transport', {})
        if not isinstance(transport, dict):
            continue
        dirty = False
        for protocol in ('tcp', 'udp'):
            proxy = transport.get(protocol, {})
            if not isinstance(proxy, dict):
                continue
            websocket = proxy.get('endpoint', {})
            if not isinstance(websocket, dict) or websocket.get('$type') != 'websocket':
                continue
            url = urlsplit(websocket.get('url', ''))
            if url.scheme == 'wss' and url.hostname == domain and websocket.get('endpoint') != endpoint:
                websocket['endpoint'] = endpoint
                dirty = True
        if dirty:
            atomic(path, yaml.safe_dump(config, sort_keys=False))
            changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', help='Verified Cloudflare IPv4 address and port, e.g. 192.0.2.10:443')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run inside the Outline LXC as root.')
    settings_path = Path('/etc/outline-admin/settings.json')
    settings = json.loads(settings_path.read_text())
    endpoint = args.endpoint or settings.get('websocket_endpoint')
    if not endpoint:
        raise SystemExit('Supply --endpoint with your own verified server/CDN IPv4 address and port.')
    address, port = endpoint.rsplit(':', 1)
    ipaddress.IPv4Address(address)
    if port != '443':
        raise SystemExit('The Cloudflare HTTPS endpoint must use port 443.')
    domain = settings['vpn_domain']
    # A 404 is normal at the root; validate TLS and an HTTP response, not a secret URL.
    result = subprocess.run(['curl', '--silent', '--show-error', '--max-time', '15',
        '--resolve', f'{domain}:443:{address}', '--output', '/dev/null', '--write-out', '%{http_code}',
        f'https://{domain}/'], capture_output=True, text=True)
    if result.returncode or result.stdout.strip() not in {'200', '404'}:
        raise SystemExit('Endpoint verification failed; no DNS-bypass settings were changed. '
                         'Check Cloudflare connectivity before retrying.')
    with open('/run/lock/outline-user.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        settings['websocket_endpoint'] = endpoint
        count = migrate('/var/lib/outline-ws/keys', domain, endpoint)
        atomic(settings_path, json.dumps(settings, indent=2)+'\n', 0o600)
    print(f'Updated {count} hosted configurations. Future dashboard keys will use the same dial address.')
    print('Hostnames, HTTPS verification, access secrets, and access-link URLs are unchanged.')


if __name__ == '__main__':
    main()
