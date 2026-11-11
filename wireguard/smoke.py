"""Run on a disposable Linux guest with the gateway and dashboard installed."""
import http.client
import json
from pathlib import Path
import subprocess
import tempfile
import time

cookie = ''
csrf = ''


def api(method, path, payload=None):
    global cookie
    connection = http.client.HTTPConnection('127.0.0.1', 18083, timeout=50)
    headers = {'Content-Type': 'application/json', 'Cookie': cookie, 'X-CSRF-Token': csrf}
    connection.request(method, path, json.dumps(payload), headers)
    response = connection.getresponse()
    if response.getheader('Set-Cookie'):
        cookie = response.getheader('Set-Cookie').split(';')[0]
    body = response.read()
    connection.close()
    assert response.status < 300, (response.status, body)
    return body


def wait_for_usage(previous_up, previous_down):
    for _ in range(20):
        data = json.loads(api('GET', '/api/wireguard'))
        row = next(r for r in data['rows'] if r['name'] == 'phone')
        if row['up'] > previous_up and row['down'] > previous_down:
            return row
        time.sleep(0.5)
    raise AssertionError('No bidirectional usage recorded for the device')


csrf = json.loads(api('GET', '/api/session'))['csrf']
csrf = json.loads(api('POST', '/api/login', {'username':'admin', 'password':'ci-only-example'}))['csrf']
api('POST', '/api/wireguard', {'name':'phone'})
assert 'phone' in json.loads(api('GET', '/api/wireguard'))['devices']
plain = api('GET', '/api/wireguard/phone/conf')
profile = json.loads(api('GET', '/api/wireguard/phone/json'))
binary = '/usr/local/lib/outline-wireguard/sing-box'
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'profile.json'
    path.write_text(json.dumps(profile))
    subprocess.run([binary, 'check', '-c', path], check=True)
    # Use a local SOCKS entry to test transport without taking over the runner's network.
    profile['inbounds'] = [dict(type='mixed', listen='127.0.0.1', listen_port=35432)]
    path.write_text(json.dumps(profile))
    client = subprocess.Popen([binary, 'run', '-c', path], stderr=subprocess.DEVNULL)
    try:
        subprocess.run(['curl','-fsS','--noproxy','','--proxy','socks5://127.0.0.1:35432',
                        '--retry','5','--retry-connrefused','--max-time','12',
                        'http://198.18.1.1:35801/probe'], check=True)
    finally:
        client.terminate()
        client.wait(timeout=5)
    wrapped = wait_for_usage(0, 0)
    # Use Linux WireGuard to exercise the same .conf that the official apps import.
    conf = Path(temp) / 'phone.conf'
    conf.write_bytes(plain)
    stripped = Path(temp) / 'wg.conf'
    stripped.write_bytes(subprocess.check_output(['wg-quick', 'strip', conf]))
    subnet = next(line.split('=', 1)[1].strip() for line in plain.decode().splitlines()
                  if line.startswith('Address ='))
    namespace = 'outline-wg-test'
    subprocess.run(['ip', 'netns', 'add', namespace], check=True)
    try:
        subprocess.run(['ip', 'link', 'add', 'wgtest', 'type', 'wireguard'], check=True)
        subprocess.run(['ip', 'link', 'set', 'wgtest', 'netns', namespace], check=True)
        ns = ['ip', 'netns', 'exec', namespace]
        subprocess.run(ns + ['wg', 'setconf', 'wgtest', stripped], check=True)
        for address in subnet.split(', '):
            subprocess.run(ns + ['ip', 'address', 'add', address, 'dev', 'wgtest'], check=True)
        subprocess.run(ns + ['ip', 'link', 'set', 'wgtest', 'up'], check=True)
        subprocess.run(ns + ['ip', 'route', 'add', 'default', 'dev', 'wgtest'], check=True)
        subprocess.run(ns + ['curl', '-fsS', '--noproxy', '*', '--max-time', '12',
                             'http://198.18.1.1:35801/probe'], check=True)
    finally:
        subprocess.run(['ip', 'netns', 'del', namespace], check=True)
direct = wait_for_usage(wrapped['up'], wrapped['down'])
assert api('GET', '/api/wireguard/phone/sing-box-qr').startswith(b'\x89PNG')
subprocess.run(['systemctl', 'restart', 'outline-admin'], check=True)
time.sleep(1)
reported = json.loads(api('GET', '/api/wireguard'))
assert reported['down'] >= direct['down']
api('DELETE', '/api/wireguard/phone')
assert 'phone' not in json.loads(api('GET', '/api/wireguard'))['devices']
