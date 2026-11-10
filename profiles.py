"""Generate a deployment-specific Apple DNS profile without publishing hostnames."""
import plistlib
import re
import uuid


def hostname(value):
    value=value.strip().lower().rstrip('.')
    if len(value)>253 or '.' not in value or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in value.split('.')):
        raise ValueError('Enter a hostname only, such as vpn.example.com (no URL or port).')
    return value


def generate(domains):
    domains=sorted(set(hostname(d) for d in domains))
    if not domains:
        raise ValueError('At least one domain is required.')
    identity=str(uuid.uuid5(uuid.NAMESPACE_DNS,','.join(domains))).upper()
    payload={
      'PayloadType':'Configuration','PayloadVersion':1,'PayloadIdentifier':'org.outlineadmin.dns.'+identity,
      'PayloadUUID':identity,'PayloadDisplayName':'Outline Admin — Encrypted DNS',
      'PayloadDescription':'Google encrypted DNS only for: '+', '.join(domains),
      'PayloadScope':'System','PayloadRemovalDisallowed':False,
      'PayloadContent':[{'PayloadType':'com.apple.dnsSettings.managed','PayloadVersion':1,
        'PayloadIdentifier':'org.outlineadmin.dns.settings.'+identity,
        'PayloadUUID':str(uuid.uuid5(uuid.NAMESPACE_DNS,identity+'.settings')).upper(),
        'PayloadDisplayName':'Outline Admin DNS via Google',
        'DNSSettings':{'DNSProtocol':'HTTPS','ServerURL':'https://dns.google/dns-query',
          'ServerAddresses':['8.8.8.8','8.8.4.4'],'SupplementalMatchDomains':domains}}]}
    return plistlib.dumps(payload,sort_keys=False)
