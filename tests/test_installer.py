import contextlib
import io
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import yaml
import installer_config


class InstallerTests(unittest.TestCase):
    def test_fresh_install_and_upgrade_preserve_runtime_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for folder in ['etc/outline-admin','etc/outline-ws','etc/nginx/conf.d','var/lib/outline-ws']:
                (root/folder).mkdir(parents=True,exist_ok=True)
            with patch('installer_config.Path',side_effect=lambda p:root/p.lstrip('/')), \
                 patch('installer_config.prompt',side_effect=['vpn.example.test','admin.example.test']), \
                 patch('installer_config.getpass.getpass',return_value='test-password-long-enough'), \
                 patch('installer_config.shutil.chown'),contextlib.redirect_stdout(io.StringIO()):
                installer_config.main()
            settings_path=root/'etc/outline-admin/settings.json'
            settings=json.loads(settings_path.read_text())
            self.assertEqual(settings['vpn_domain'],'vpn.example.test')
            self.assertEqual(settings['origin'],'https://admin.example.test')
            self.assertEqual(settings_path.stat().st_mode&0o777,0o600)
            config_path=root/'etc/outline-ws/config.yaml'
            config=yaml.safe_load(config_path.read_text())
            self.assertEqual(config['services'][0]['keys'][0]['id'],'_admin_reserved')
            self.assertIn('server_name vpn.example.test;', (root/'etc/nginx/conf.d/outline-ws.conf').read_text())
            profile=plistlib.loads((root/'var/lib/outline-ws/profiles/outline-dns.mobileconfig').read_bytes())
            self.assertEqual(profile['PayloadContent'][0]['DNSSettings']['SupplementalMatchDomains'],['admin.example.test','vpn.example.test'])
            before_config=config_path.read_bytes()
            settings['websocket_endpoint']='192.0.2.10:443'
            settings_path.write_text(json.dumps(settings))
            with patch('installer_config.Path',side_effect=lambda p:root/p.lstrip('/')), \
                 patch('installer_config.prompt') as prompt, contextlib.redirect_stdout(io.StringIO()):
                installer_config.main()
                prompt.assert_not_called()
            self.assertEqual(json.loads(settings_path.read_text()),settings)
            self.assertEqual(config_path.read_bytes(),before_config)
