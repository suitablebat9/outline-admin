"""Manage the existing WebSocket config and outline-user registry under its lock."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import yaml


def atomic(path, content, mode=None):
    path = Path(path)
    info = path.stat() if path.exists() else None
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, mode if mode is not None else (info.st_mode & 0o777 if info else 0o600))
        if info and os.geteuid() == 0:
            os.chown(temporary, info.st_uid, info.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Manager:
    def __init__(self, config, state, keydir, lock, domain, restart=None, websocket_endpoint=None):
        self.config, self.state, self.keydir = Path(config), Path(state), Path(keydir)
        self.lock, self.domain = lock, domain
        self.restart = restart or self._restart
        self.websocket_endpoint = websocket_endpoint

    @staticmethod
    def _restart():
        subprocess.run(['systemctl','restart','outline-ws'], check=True, timeout=30, capture_output=True)
        time.sleep(.5)
        subprocess.run(['systemctl','is-active','--quiet','outline-ws'], check=True, timeout=5)

    @contextlib.contextmanager
    def locked(self):
        with open(self.lock, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def load(self):
        config = yaml.safe_load(self.config.read_text())
        registry = json.loads(self.state.read_text()) if self.state.exists() else {}
        services = [s for s in config.get('services', []) if
                    {'websocket-stream','websocket-packet'} <= {l.get('type') for l in s.get('listeners',[])}]
        if len(services) != 1:
            raise ValueError('Expected exactly one WebSocket service in config.yaml.')
        return config, registry, services[0]

    def list(self):
        with self.locked():
            _, registry, service = self.load()
            by_id = {str(v['id']): name for name,v in registry.items()}
            return [{'id':str(k['id']), 'name':by_id.get(str(k['id']), str(k['id'])),
                     'legacy': str(k['id']) not in by_id}
                    for k in service.get('keys',[]) if str(k['id']) != '_admin_reserved']

    def client(self, key, service):
        listeners = {l['type']:l['path'] for l in service['listeners'] if l.get('path')}
        transport = {'$type':'tcpudp'}
        for proto, kind in [('tcp','websocket-stream'), ('udp','websocket-packet')]:
            transport[proto] = {'$type':'shadowsocks', 'endpoint':{'$type':'websocket',
                'url':f'wss://{self.domain}{listeners[kind]}'}, 'cipher':key['cipher'], 'secret':key['secret']}
            if self.websocket_endpoint:
                transport[proto]['endpoint']['endpoint'] = self.websocket_endpoint
        return yaml.safe_dump({'transport':transport}, sort_keys=False)

    def key(self, key_id):
        with self.locked():
            _, registry, service = self.load()
            key = next((k for k in service['keys'] if str(k['id']) == key_id and key_id != '_admin_reserved'), None)
            if not key:
                raise ValueError('Access key not found.')
            record = next((v for v in registry.values() if str(v['id']) == key_id), None)
            filename = record['file'] if record else secrets.token_hex(32)+'.yaml'
            if not re.fullmatch(r'[A-Za-z0-9_-]+\.yaml', filename):
                raise ValueError('Invalid key filename in users.json.')
            if not record:
                name = key_id
                while name in registry:
                    name += '-legacy'
                registry[name] = {'id':key_id, 'file':filename}
            atomic(self.keydir / filename, self.client(key,service), 0o644)
            atomic(self.state,json.dumps(registry,indent=2)+'\n',0o600)
            return f'ssconf://{self.domain}/keys/{filename}'

    def commit(self, config, registry):
        old_config = self.config.read_text()
        old_state = self.state.read_text() if self.state.exists() else '{}'
        atomic(self.config.with_name('config.yaml.admin-backup'), old_config, 0o600)
        atomic(self.config, yaml.safe_dump(config,sort_keys=False))
        atomic(self.state,json.dumps(registry,indent=2)+'\n',0o600)
        try:
            self.restart()
        except Exception as error:
            atomic(self.config,old_config)
            atomic(self.state,old_state,0o600)
            try:
                self.restart()
            except Exception:
                raise RuntimeError('Change rolled back, but Outline failed to restart. Check journalctl -u outline-ws.') from error
            raise RuntimeError('Outline failed to restart. The previous configuration was restored.') from error

    def add(self, name):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',name):
            raise ValueError('Use 1–32 lowercase letters, digits, _ or -; start with a letter.')
        with self.locked():
            config, registry, service = self.load()
            if name in registry or any(str(k['id']) == name for k in service['keys']):
                raise ValueError('That username already exists.')
            key_id = 'user-'+name+'-'+secrets.token_hex(4)
            key = {'id':key_id, 'cipher':'chacha20-ietf-poly1305', 'secret':secrets.token_urlsafe(32)}
            service['keys'].append(key)
            filename = secrets.token_hex(32)+'.yaml'
            registry[name] = {'id':key_id,'file':filename}
            atomic(self.keydir/filename,self.client(key,service),0o644)
            try:
                self.commit(config,registry)
            except Exception:
                (self.keydir/filename).unlink(missing_ok=True)
                raise
            return {'id':key_id,'name':name,'key':f'ssconf://{self.domain}/keys/{filename}'}

    def remove(self, key_id):
        with self.locked():
            config, registry, service = self.load()
            if key_id == '_admin_reserved' or not any(str(k['id']) == key_id for k in service['keys']):
                raise ValueError('Access key not found.')
            removed = [v for v in registry.values() if str(v['id']) == key_id]
            service['keys'] = [k for k in service['keys'] if str(k['id']) != key_id]
            # A never-distributed credential keeps an empty server config valid.
            if not service['keys']:
                service['keys'] = [{'id':'_admin_reserved','cipher':'chacha20-ietf-poly1305',
                                    'secret':secrets.token_urlsafe(48)}]
            registry = {n:v for n,v in registry.items() if str(v['id']) != key_id}
            self.commit(config,registry)
            for record in removed:
                filename = record['file']
                if re.fullmatch(r'[A-Za-z0-9_-]+\.yaml',filename):
                    (self.keydir/filename).unlink(missing_ok=True)
