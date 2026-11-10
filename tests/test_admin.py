import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import yaml
from werkzeug.security import generate_password_hash
from app import create_app
from manager import Manager
import metrics


def configuration():
    return {'web':{'servers':[{'id':'ws','listen':['127.0.0.1:18080']}]},
      'services':[{'listeners':[{'type':'websocket-stream','web_server':'ws','path':'/tcp-secret'},
                               {'type':'websocket-packet','web_server':'ws','path':'/udp-secret'}],
                   'keys':[{'id':'personal','cipher':'chacha20-ietf-poly1305','secret':'old-secret'}]}]}


def sample(up, down, seconds, epoch=100):
    return f'''# TYPE process_start_time_seconds gauge
process_start_time_seconds {epoch}
# TYPE shadowsocks_data_bytes counter
shadowsocks_data_bytes{{access_key="personal",dir="c>p",proto="tcp"}} {up}
shadowsocks_data_bytes{{access_key="personal",dir="c<p",proto="tcp"}} {down}
shadowsocks_data_bytes{{access_key="personal",dir="p>t",proto="tcp"}} {up}
shadowsocks_data_bytes{{access_key="personal",dir="p<t",proto="tcp"}} {down}
# TYPE shadowsocks_tunnel_time_seconds counter
shadowsocks_tunnel_time_seconds{{access_key="personal"}} {seconds}
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config=self.root/'config.yaml'
        self.config.write_text(yaml.safe_dump(configuration()))
        self.state=self.root/'users.json'
        self.keydir=self.root/'keys';self.keydir.mkdir()
        self.restart_calls=[]
        self.manager=Manager(self.config,self.state,self.keydir,self.root/'lock','vpn.example.com',
                             restart=lambda:self.restart_calls.append(True))


class ManagerTests(Fixture):
    def test_add_view_remove_preserves_other_keys(self):
        result=self.manager.add('alice')
        self.assertEqual(len(self.manager.list()),2)
        self.assertEqual(self.manager.key(result['id']),result['key'])
        file=self.keydir/result['key'].split('/')[-1]
        client=yaml.safe_load(file.read_text())
        self.assertEqual(client['transport']['tcp']['endpoint']['url'],'wss://vpn.example.com/tcp-secret')
        self.manager.remove(result['id'])
        self.assertFalse(file.exists())
        self.assertEqual(self.manager.list()[0]['id'],'personal')
        self.assertEqual(len(self.restart_calls),2)

    def test_imports_existing_cli_registry(self):
        conf=configuration();conf['services'][0]['keys'].append({'id':'user-bob','cipher':'chacha20-ietf-poly1305','secret':'bob-secret'})
        self.config.write_text(yaml.safe_dump(conf))
        self.state.write_text(json.dumps({'bob':{'id':'user-bob','file':'existing.yaml'}}))
        self.assertEqual(self.manager.key('user-bob'),'ssconf://vpn.example.com/keys/existing.yaml')
        self.manager.remove('user-bob')
        self.assertEqual(json.loads(self.state.read_text()),{})

    def test_last_key_revocation_leaves_no_usable_public_key(self):
        self.manager.remove('personal')
        self.assertEqual(self.manager.list(),[])
        with self.assertRaises(ValueError): self.manager.key('_admin_reserved')
        self.manager.add('newperson')
        self.assertEqual(len(self.manager.list()),1)

    def test_restart_failure_rolls_back(self):
        old=self.config.read_text()
        def failed(): raise RuntimeError('simulated')
        self.manager.restart=failed
        with self.assertRaises(RuntimeError): self.manager.add('alice')
        self.assertEqual(self.config.read_text(),old)
        self.assertEqual(json.loads(self.state.read_text()),{})
        self.assertEqual(list(self.keydir.iterdir()),[])

    def test_invalid_usernames_and_duplicates(self):
        for value in ['../secret','x; touch /tmp/no','Alice','', 'a'*33]:
            with self.assertRaises(ValueError): self.manager.add(value)
        self.manager.add('alice')
        with self.assertRaises(ValueError): self.manager.add('alice')

    def test_recreated_user_gets_new_identity(self):
        one=self.manager.add('alice');self.manager.remove(one['id'])
        two=self.manager.add('alice')
        self.assertNotEqual(one['id'],two['id'])


class MetricsTests(Fixture):
    def setUp(self):
        super().setUp();self.db=self.root/'metrics.sqlite3';metrics.initialize(self.db)

    def totals(self):
        with metrics.connect(self.db) as db:
            return dict(db.execute('SELECT * FROM totals WHERE key="personal"').fetchone())

    def test_baseline_directions_and_no_double_count(self):
        metrics.record(self.db,sample(100,200,10),1000)
        self.assertEqual(self.totals()['upload'],0)
        metrics.record(self.db,sample(160,300,20),1010)
        self.assertEqual(self.totals()['upload'],60)
        self.assertEqual(self.totals()['download'],100)
        self.assertEqual(self.totals()['last_active'],1010)
        metrics.record(self.db,sample(160,300,20),1020)
        self.assertEqual(self.totals()['last_active'],1010)

    def test_restart_detected_even_if_new_counter_is_larger(self):
        metrics.record(self.db,sample(10,20,1),1000)
        metrics.record(self.db,sample(30,50,2),1010)
        metrics.record(self.db,sample(100,200,3,epoch=200),1020)
        self.assertEqual(self.totals()['upload'],120)
        self.assertEqual(self.totals()['download'],230)
        metrics.initialize(self.db)
        metrics.record(self.db,sample(110,220,4,epoch=200),1030)
        self.assertEqual(self.totals()['download'],250)

    def test_missing_metrics_not_silent_success(self):
        with self.assertRaises(ValueError): metrics.record(self.db,'')


class ApiTests(Fixture):
    def setUp(self):
        super().setUp()
        self.app=create_app({'session_secret':'test-secret','password_hash':generate_password_hash('test-password'),
            'origin':'https://admin-vpn.example.com','secure_cookie':False,
            'database':str(self.root/'db.sqlite3'),'config':str(self.config),'registry':str(self.state),
            'keydir':str(self.keydir),'lock':str(self.root/'lock'),'restart':lambda:None})
        self.app.testing=True;self.client=self.app.test_client()
        self.csrf=self.client.get('/api/session').json['csrf']
        self.mock=patch('metrics.scrape',return_value=True);self.mock.start();self.addCleanup(self.mock.stop)

    def headers(self): return {'X-CSRF-Token':self.csrf,'Origin':'https://admin-vpn.example.com'}

    def login(self):
        response=self.client.post('/api/login',json={'username':'admin','password':'test-password'},headers=self.headers())
        self.assertEqual(response.status_code,200);self.csrf=response.json['csrf']

    def test_auth_csrf_and_origin(self):
        self.assertEqual(self.client.get('/api/dashboard').status_code,401)
        self.assertEqual(self.client.get('/api/users/personal/key').status_code,401)
        self.login()
        self.assertEqual(self.client.post('/api/users',json={'name':'alice'}).status_code,403)
        bad=self.headers();bad['Origin']='https://evil.example'
        self.assertEqual(self.client.post('/api/users',json={'name':'alice'},headers=bad).status_code,403)

    def test_user_lifecycle_and_no_secrets_in_dashboard(self):
        self.login()
        response=self.client.post('/api/users',json={'name':'alice'},headers=self.headers())
        self.assertEqual(response.status_code,201)
        key_id=response.json['id']
        self.assertIn('ssconf://',response.json['key'])
        dash=self.client.get('/api/dashboard')
        self.assertNotIn('ssconf://',dash.text)
        self.assertNotIn('old-secret',dash.text)
        self.assertTrue(all(u['activity']=='Unknown' for u in dash.json['users']))
        self.assertEqual(self.client.get(f'/api/users/{key_id}/key').status_code,200)
        self.assertEqual(self.client.delete(f'/api/users/{key_id}',headers=self.headers()).status_code,200)
        self.assertEqual(self.client.get(f'/api/users/{key_id}/key').status_code,400)

    def test_expired_session_and_logout(self):
        self.login()
        with self.client.session_transaction() as s:s['issued']=time.time()-30000
        self.assertEqual(self.client.get('/api/dashboard').status_code,401)
        self.login()
        self.client.post('/api/logout',headers=self.headers())
        self.assertEqual(self.client.get('/api/dashboard').status_code,401)

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/api/login',json={'username':'admin','password':'wrong'},headers=self.headers()).status_code,401)
        self.assertEqual(self.client.post('/api/login',json={'username':'admin','password':'wrong'},headers=self.headers()).status_code,429)

    def test_security_headers(self):
        response=self.client.get('/')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        self.assertIn('HttpOnly',response.headers.get('Set-Cookie','') or 'HttpOnly')

    def test_metrics_become_unknown_after_ten_seconds(self):
        self.login()
        now=time.time()
        path=self.root/'db.sqlite3'
        metrics.record(path,sample(10,20,1),now-2)
        metrics.record(path,sample(20,40,2),now)
        with patch('app.time.time',return_value=now+9):
            response=self.client.get('/api/dashboard').json
            self.assertTrue(response['healthy'])
            self.assertEqual(response['users'][0]['activity'],'Active recently')
        with patch('app.time.time',return_value=now+11):
            response=self.client.get('/api/dashboard').json
            self.assertFalse(response['healthy'])
            self.assertEqual(response['users'][0]['activity'],'Unknown')
            self.assertEqual(response['total_download'],20)


if __name__=='__main__':unittest.main()
