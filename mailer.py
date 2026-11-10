"""Authenticated SMTP delivery. Secrets are read locally and never returned to the UI."""
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import json
from pathlib import Path
import re
import smtplib
import ssl
from urllib.parse import urlsplit
from profiles import generate

SMTP_SETTINGS = Path('/etc/outline-admin/smtp.json')



def email_address(value):
    if not isinstance(value,str) or len(value)>254 or not value.isascii() or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}",value):
        raise ValueError('Enter one valid email address.')
    return value


def load_config(path=SMTP_SETTINGS):
    path = Path(path)
    if not path.exists():
        raise RuntimeError('Email is not configured. Run outline-admin-email-setup inside the LXC first.')
    config = json.loads(path.read_text())
    email_address(config.get('sender'))
    if not config.get('username') or not config.get('password') or config.get('security') not in {'ssl','starttls'}:
        raise RuntimeError('Email configuration is incomplete. Run outline-admin-email-setup again.')
    return config


def status(path=SMTP_SETTINGS):
    try:
        config = load_config(path)
        return {'ready':True,'sender':config['sender']}
    except (OSError,ValueError,RuntimeError):
        return {'ready':False,'sender':None}


def connect(config):
    context=ssl.create_default_context()
    client=None
    try:
        if config['security']=='ssl':
            client=smtplib.SMTP_SSL(config['host'],int(config['port']),timeout=15,context=context)
        else:
            client=smtplib.SMTP(config['host'],int(config['port']),timeout=15)
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        client.login(config['username'],config['password'])
        return client
    except Exception:
        if client:
            client.close()
        raise


def message(sender, recipient, name, key, domains=None):
    email_address(sender)
    email_address(recipient)
    if not key.startswith('ssconf://') or any(c.isspace() for c in key):
        raise ValueError('Invalid access link.')
    domain=urlsplit(key.replace('ssconf://','https://',1)).hostname
    profile=generate(domains or [domain])
    domain_list=', '.join(sorted(set(domains or [domain])))
    msg=EmailMessage()
    msg['From']=sender
    msg['To']=recipient
    msg['Subject']='Your Outline Admin VPN access'
    msg['Date']=formatdate(localtime=False)
    msg['Message-ID']=make_msgid()
    msg.set_content(f'''Hi {name},

Here is your personal Outline Admin VPN access.

1. Install the official Outline Client (1.15.0 or newer):
https://getoutline.org/get-started/

2. In Outline, choose Add server and paste this entire access code:
{key}

3. The attached outline-dns.mobileconfig is the optional Mac/iPhone DNS profile. Install it if your network cannot resolve our VPN hostname.

Mac: open the attachment, then install Outline Admin — Encrypted DNS in System Settings > General > Device Management (or search for Profiles).
iPhone: save/open the attachment, then install Outline Admin — Encrypted DNS in Settings > General > VPN & Device Management. If your mail app cannot open the profile, download it with Safari using the link below.

The profile uses Google encrypted DNS only for {domain_list} and their subdomains. It is unsigned, contains no VPN key or device-management enrollment, and can be removed from the same settings screen.

Profile download, if your mail app cannot open the attachment:
https://{domain}/profiles/outline-dns.mobileconfig

4. Disconnect other VPNs and connect in Outline.

Keep your access code private: anyone with it can use your access. Reply if you need help or want it revoked.

Outline Admin
''')
    msg.add_attachment(profile,maintype='application',subtype='x-apple-aspen-config',
                       filename='outline-dns.mobileconfig')
    return msg


def send(config, msg):
    client=connect(config)
    try:
        refused=client.send_message(msg,from_addr=config['sender'],to_addrs=[str(msg['To'])])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    finally:
        client.close()
