"""Per-device WireGuard keys and Shadowsocks transport for the local gateway."""
import base64
import contextlib
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile

STATE = Path('/etc/outline-wireguard/devices.json')
BINARY = '/usr/local/lib/outline-wireguard/sing-box'
SERVICE = 'outline-wireguard.service'
METHOD = '2022-blake3-aes-128-gcm'


def secret():
    return base64.b64encode(secrets.token_bytes(16)).decode()


def keypair():
    result = subprocess.run([BINARY, 'generate', 'wg-keypair'], check=True, capture_output=True, text=True)
    keys = dict(line.split(': ', 1) for line in result.stdout.splitlines())
    return {'private': keys['PrivateKey'], 'public': keys['PublicKey']}


def write(path, data, mode=0o600):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as temp:
        try:
            json.dump(data, temp, indent=2)
            temp.flush()
            os.fchmod(temp.fileno(), mode)
            os.fsync(temp.fileno())
            os.replace(temp.name, path)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def initialize(address, tcp):
    if STATE.exists():
        return
    address = str(ipaddress.IPv4Address(address))
    if not 1 <= tcp <= 65535:
        raise ValueError('Enter a TCP port from 1 to 65535.')
    write(STATE, dict(host=address, tcp=tcp, udp=51820, relay=secret(), server=keypair(), devices={}))


def endpoint(private, address, peers):
    return dict(type='wireguard', tag='wg', system=False, mtu=1280, address=[address],
                private_key=private, peers=peers)


def server(data):
    devices = data['devices']
    peers = [dict(public_key=d['public'], allowed_ips=[d['address']]) for d in devices.values()]
    wg = endpoint(data['server']['private'], '10.248.199.1/24', peers)
    wg['listen_port'] = data['udp']
    inbounds = []
    if devices:
        inbounds.append(dict(type='shadowsocks', tag='relay', listen='0.0.0.0', listen_port=data['tcp'],
            network='tcp', method=METHOD, password=data['relay'],
            users=[dict(name=n, password=d['relay']) for n, d in devices.items()]))
    rules = [
        dict(inbound='relay', network='udp', ip_cidr='127.0.0.1/32', port=data['udp'], action='route', outbound='internet'),
        dict(inbound='relay', action='reject'),
        dict(inbound='wg', ip_is_private=True, action='reject'),
    ]
    return dict(log={'level': 'warn'}, inbounds=inbounds, endpoints=[wg], outbounds=[dict(type='direct', tag='internet')],
                route=dict(rules=rules, final='internet'))


def profile(data, name, wrapped):
    device = data['devices'][name]
    key = data['server']['public']
    if not wrapped:
        return (f"[Interface]\nPrivateKey = {device['private']}\nAddress = {device['address']}\n"
                f"DNS = 1.1.1.1\nMTU = 1280\n\n[Peer]\nPublicKey = {key}\n"
                f"Endpoint = {data['host']}:{data['udp']}\nAllowedIPs = 0.0.0.0/0, ::/0\nPersistentKeepalive = 25\n")
    peer = dict(public_key=key, address='127.0.0.1', port=data['udp'], allowed_ips=['0.0.0.0/0','::/0'],
                persistent_keepalive_interval=25)
    wg = endpoint(device['private'], device['address'], [peer])
    wg['detour'] = 'relay'
    relay = dict(type='shadowsocks', tag='relay', server=data['host'], server_port=data['tcp'], method=METHOD,
                 password=data['relay'] + ':' + device['relay'], udp_over_tcp=True)
    tun = dict(type='tun', tag='tun', address=['172.27.249.1/30','fdc8:aeb0:ba00::1/126'], auto_route=True, mtu=1280)
    dns = dict(servers=[dict(type='udp', tag='resolver', server='1.1.1.1', detour='wg')], strategy='ipv4_only')
    return json.dumps(dict(inbounds=[tun], endpoints=[wg], outbounds=[relay], dns=dns,
        route=dict(auto_detect_interface=True, rules=[dict(port=53, action='hijack-dns')], final='wg')), indent=2)


def read():
    if not STATE.is_file():
        raise ValueError('Install the WireGuard gateway in this guest first.')
    return json.loads(STATE.read_text())


@contextlib.contextmanager
def locked():
    with open('/run/lock/outline-wireguard.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def change(name, remove=False):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,15}', name):
        raise ValueError('Use 1–15 letters, numbers, underscores or dashes for the device name.')
    with locked():
        data = read()
        previous = json.loads(json.dumps(data))
        devices = data['devices']
        if remove:
            if name not in devices:
                raise ValueError('Unknown device.')
            del devices[name]
        else:
            if name in devices:
                raise ValueError('That device name is already in use.')
            used = {d['address'] for d in devices.values()}
            address = next((f'10.248.199.{i}/32' for i in range(2,255) if f'10.248.199.{i}/32' not in used), None)
            if not address:
                raise ValueError('This gateway is full.')
            devices[name] = dict(**keypair(), address=address, relay=secret())
        write(STATE, data)
        try:
            subprocess.run(['systemctl', 'restart', SERVICE], check=True, timeout=40)
        except (OSError, subprocess.SubprocessError) as error:
            write(STATE, previous)
            subprocess.run(['systemctl', 'restart', SERVICE], timeout=40)
            raise RuntimeError('Gateway update failed. Check the outline-wireguard service log.') from error


if __name__ == '__main__':
    if sys.argv[1] == 'init':
        initialize(sys.argv[2], int(sys.argv[3]))
    elif sys.argv[1] == 'render':
        path = Path(sys.argv[2])
        write(path, server(read()), 0o644)  # Runtime directory is accessible only to the daemon and root.
    elif sys.argv[1] == 'ready':
        import time
        config = json.loads(Path(sys.argv[2]).read_text())
        listeners = [('udp', config['endpoints'][0]['listen_port'])]
        listeners.extend(('tcp', item['listen_port']) for item in config['inbounds'])
        for _ in range(80):
            if all('sing-box' in subprocess.check_output(
                    ['ss', '-Hlnp', '--' + protocol, 'sport', '=', ':' + str(port)], text=True)
                   for protocol, port in listeners):
                break
            time.sleep(0.1)
        else:
            sys.exit('WireGuard gateway failed to open its configured ports.')
