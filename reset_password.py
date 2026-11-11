import getpass
import json
import os
from pathlib import Path
import secrets
from werkzeug.security import generate_password_hash
from wg_accounts import write

if os.geteuid()!=0:
    raise SystemExit('Run as root.')
path=Path('/etc/outline-admin/settings.json')
settings=json.loads(path.read_text())
password=getpass.getpass('New admin password (14+ characters): ')
if len(password)<14 or password!=getpass.getpass('Confirm password: '):
    raise SystemExit('Password too short or confirmation did not match.')
settings['password_hash']=generate_password_hash(password)
settings['session_secret']=secrets.token_urlsafe(48)
write(path, settings)
print('Password changed. Existing admin sessions will be signed out after restart.')
