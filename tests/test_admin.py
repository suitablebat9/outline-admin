import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from app import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = create_app(dict(session_secret='test-secret', password_hash=generate_password_hash('test-password'),
                              origin='https://admin.example.com', secure_cookie=False, database=str(Path(temp.name)/'db')))
        self.client = self.app.test_client()

    def login(self):
        csrf = self.client.get('/api/session').json['csrf']
        result = self.client.post('/api/login', json={'username':'admin','password':'test-password'},
                                  headers={'X-CSRF-Token':csrf})
        self.assertEqual(result.status_code, 200)

    def test_removed_routes_and_csrf(self):
        self.login()
        for url in ['/api/dashboard','/api/native','/api/users/test/key']:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post('/api/wireguard', json={'name':'test'}).status_code, 403)

    def test_private_singbox_qr(self):
        path = '/api/wireguard/phone/sing-box-qr'
        self.assertEqual(self.client.get(path).status_code, 401)
        self.login()
        with patch('wg_accounts.read', return_value={'devices': {'phone': {}}}), \
                patch('wg_accounts.profile', return_value='{"log":{"level":"warn"}}') as profile:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/png')
            self.assertTrue(response.data.startswith(b'\x89PNG'))
            self.assertTrue(response.cache_control.no_store)
            self.assertEqual(self.client.get(path.replace('phone', 'removed')).status_code, 404)
            profile.assert_called_once_with({'devices': {'phone': {}}}, 'phone', wrapped=True)
