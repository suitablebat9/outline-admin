import tempfile
import unittest
from pathlib import Path
import yaml
from configure_endpoint import migrate
from manager import Manager


class EndpointTests(unittest.TestCase):
    def test_generation_keeps_hostname_and_pins_both_protocols(self):
        manager = Manager('unused','unused','unused','unused','vpn.example.com',
                          websocket_endpoint='192.0.2.10:443')
        key = {'cipher':'chacha20-ietf-poly1305','secret':'test-only'}
        service = {'listeners':[{'type':'websocket-stream','path':'/tcp'},
                                {'type':'websocket-packet','path':'/udp'}]}
        config = yaml.safe_load(manager.client(key,service))
        for protocol in ('tcp','udp'):
            proxy = config['transport'][protocol]
            self.assertEqual(proxy['secret'],'test-only')
            self.assertEqual(proxy['endpoint']['endpoint'],'192.0.2.10:443')
            self.assertEqual(proxy['endpoint']['url'],f'wss://vpn.example.com/{protocol}')

    def test_migration_preserves_secrets_urls_other_hosts_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'existing.yaml'
            conf={'transport':{'tcp':{'secret':'existing-secret','endpoint':{'$type':'websocket',
                  'url':'wss://vpn.example.com/path'}},'udp':{'endpoint':{'$type':'websocket',
                  'url':'wss://another.example/path'}}}}
            path.write_text(yaml.safe_dump(conf))
            path.chmod(0o644)
            self.assertEqual(migrate(directory,'vpn.example.com','192.0.2.10:443'),1)
            result=yaml.safe_load(path.read_text())
            self.assertEqual(result['transport']['tcp']['secret'],'existing-secret')
            self.assertEqual(result['transport']['tcp']['endpoint']['url'],'wss://vpn.example.com/path')
            self.assertEqual(result['transport']['udp'],conf['transport']['udp'])
            self.assertEqual(path.stat().st_mode & 0o777,0o644)
            self.assertEqual(migrate(directory,'vpn.example.com','192.0.2.10:443'),0)
