"""Run on a disposable Linux guest with the gateway and dashboard installed."""
import http.client
import json
from pathlib import Path
import subprocess
import tempfile

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


csrf = json.loads(api('GET', '/api/session'))['csrf']
csrf = json.loads(api('POST', '/api/login', {'username':'admin', 'password':'ci-only-example'}))['csrf']
api('POST', '/api/wireguard', {'name':'phone'})
assert 'phone' in json.loads(api('GET', '/api/wireguard'))['devices']
assert b'[Peer]' in api('GET', '/api/wireguard/phone/conf')
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
api('DELETE', '/api/wireguard/phone')
assert json.loads(api('GET', '/api/wireguard'))['devices'] == []
