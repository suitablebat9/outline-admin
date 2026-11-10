"""Keep the optional Apple profile scoped to this deployment's DNS names."""
from pathlib import Path
import plistlib
import unittest
import uuid
from profiles import generate, hostname


class ProfileTests(unittest.TestCase):
    def test_profile_contains_only_scoped_encrypted_dns(self):
        profile = plistlib.loads(generate(['example.com']))
        self.assertEqual(profile['PayloadType'], 'Configuration')
        self.assertEqual(profile['PayloadScope'], 'System')
        self.assertFalse(profile['PayloadRemovalDisallowed'])
        uuid.UUID(profile['PayloadUUID'])
        self.assertEqual(len(profile['PayloadContent']), 1)
        dns = profile['PayloadContent'][0]
        uuid.UUID(dns['PayloadUUID'])
        self.assertEqual(dns['PayloadType'], 'com.apple.dnsSettings.managed')
        self.assertEqual(dns['DNSSettings'], {
            'DNSProtocol': 'HTTPS',
            'ServerURL': 'https://dns.google/dns-query',
            'ServerAddresses': ['8.8.8.8', '8.8.4.4'],
            'SupplementalMatchDomains': ['example.com'],
        })


if __name__ == '__main__':
    unittest.main()

class HostnameTests(unittest.TestCase):
    def test_rejects_config_injection(self):
        for value in ['vpn.example.com; evil','https://example.com','example.com/path','example.com:443','localhost','example.com\nproxy_pass evil']:
            with self.assertRaises(ValueError): hostname(value)

    def test_profiles_are_specific_to_each_installation(self):
        a=plistlib.loads(generate(['vpn.example.com','admin.example.com']))
        b=plistlib.loads(generate(['vpn.other.test','admin.other.test']))
        self.assertNotEqual(a['PayloadUUID'],b['PayloadUUID'])
        self.assertEqual(a['PayloadContent'][0]['DNSSettings']['SupplementalMatchDomains'],['admin.example.com','vpn.example.com'])
