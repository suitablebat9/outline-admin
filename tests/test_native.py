import unittest
from unittest.mock import Mock

from native_accounts import sessions


class SessionTests(unittest.TestCase):
    def test_eap_owner_in_both_strongswan_encodings(self):
        client = Mock()
        client.list_sas.return_value = [
            {'apple': {'state': b'ESTABLISHED', 'remote-id': b'alice'}},
            {'apple': {'state': b'ESTABLISHED', 'remote-id': b'device', 'remote-eap-id': b'bob'}},
            {'apple': {'state': b'CONNECTING', 'remote-id': b'carol'}},
        ]
        self.assertEqual([name for name, _ in sessions(client)], ['alice', 'bob'])
