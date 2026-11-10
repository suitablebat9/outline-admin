"""Interactive Gmail setup, executed on the LXC, never through the web UI."""
import getpass
import json
import os
import smtplib
from pathlib import Path
from manager import atomic
import mailer


def main():
    if os.geteuid()!=0:
        raise SystemExit('Run as root inside the Outline LXC.')
    print('Gmail / Google Workspace email setup')
    print('Enable Google 2-Step Verification and create an app password:')
    print('https://myaccount.google.com/apppasswords')
    print('Use an app password, not your normal Google password. No test email will be sent.')
    email=mailer.email_address(input('Sender Gmail / Workspace email address: ').strip())
    password=getpass.getpass('Google app password (hidden): ').replace(' ','')
    if not password:
        raise SystemExit('No password entered; configuration unchanged.')
    config={'host':'smtp.gmail.com','port':465,'security':'ssl','username':email,'sender':email,'password':password}
    try:
        client=mailer.connect(config)
        client.close()
    except smtplib.SMTPAuthenticationError:
        raise SystemExit('Google rejected sign-in. Check the app password and whether your account allows app passwords. Nothing was saved.')
    except (OSError,smtplib.SMTPException):
        raise SystemExit('Could not establish an authenticated TLS connection to Gmail. Check the LXC network. Nothing was saved.')
    path=Path('/etc/outline-admin/smtp.json')
    atomic(path,json.dumps(config,indent=2)+'\n',0o600)
    print('Gmail connected. Credentials saved privately on the LXC. No email was sent.')
    print('Reload the dashboard, click a user, enter a recipient, and click Send email.')


if __name__=='__main__':
    main()
