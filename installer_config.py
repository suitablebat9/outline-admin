import getpass
import json
from pathlib import Path
import re
import secrets
from werkzeug.security import generate_password_hash
from wg_accounts import write

def main():
    path = Path('/etc/outline-admin/settings.json')
    if path.exists():
        return
    with open('/dev/tty', 'r+') as tty:
        tty.write('Dashboard hostname: ')
        tty.flush()
        host = tty.readline().strip().lower()
    if not re.fullmatch(r'([a-z0-9][a-z0-9-]*\.)+[a-z]{2,}', host):
        raise SystemExit('Enter a DNS hostname.')
    while True:
        password = getpass.getpass('Choose an admin password (14+ characters): ')
        if len(password) >= 14 and password == getpass.getpass('Confirm password: '):
            break
        print('Use at least 14 characters and enter the same password twice.')
    write(path, dict(username='admin', password_hash=generate_password_hash(password),
                     session_secret=secrets.token_urlsafe(48), origin='https://' + host))

if __name__ == '__main__':
    main()
