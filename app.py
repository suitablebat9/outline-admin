import functools
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import smtplib
import threading
import time
import uuid
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash

from manager import Manager
import metrics
import mailer
import native_accounts
import wg_accounts
from profile_qr import singbox_qr


def create_app(settings=None):
    if settings is None:
        settings = json.loads(Path(os.environ.get('OUTLINE_ADMIN_SETTINGS', '/etc/outline-admin/settings.json')).read_text())
    app = Flask(__name__)
    app.config.update(SECRET_KEY=settings['session_secret'], SESSION_COOKIE_NAME='outline_admin',
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=settings.get('secure_cookie',True),
        PERMANENT_SESSION_LIFETIME=28800, MAX_CONTENT_LENGTH=8192,
        SESSION_REFRESH_EACH_REQUEST=False)
    db_path = settings.get('database','/var/lib/outline-admin/history.sqlite3')
    metrics.initialize(db_path)
    manager = Manager(settings.get('config','/etc/outline-ws/config.yaml'),
        settings.get('registry','/etc/outline-ws/users.json'),
        settings.get('keydir','/var/lib/outline-ws/keys'),
        settings.get('lock','/run/lock/outline-user.lock'),settings.get('vpn_domain','vpn.example.com'),
        restart=settings.get('restart'), websocket_endpoint=settings.get('websocket_endpoint'))
    app.extensions['manager'] = manager
    metrics_url = settings.get('metrics_url','http://127.0.0.1:19090/metrics')
    scrape_lock = threading.Lock()
    smtp_path=settings.get('smtp_config',mailer.SMTP_SETTINGS)

    def poll():
        with scrape_lock:
            return metrics.scrape(db_path,metrics_url)
    app.extensions['poll'] = poll

    def audit(action, name):
        with metrics.connect(db_path) as db:
            db.execute('INSERT INTO audit VALUES (?,?,?)',(time.time(),action,name))

    def authenticated(handler):
        @functools.wraps(handler)
        def wrapped(*args,**kwargs):
            if not session.get('admin') or time.time()-session.get('issued',0) > 28800:
                return jsonify(error='Sign in to continue.'),401
            return handler(*args,**kwargs)
        return wrapped

    @app.before_request
    def protect():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        if request.method in {'POST','DELETE','PUT','PATCH'}:
            origin = request.headers.get('Origin')
            if origin and origin != settings['origin']:
                return jsonify(error='Invalid request origin.'),403
            token = request.headers.get('X-CSRF-Token','')
            if not hmac.compare_digest(token,session['csrf']):
                return jsonify(error='Session expired. Reload the page.'),403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        if settings.get('secure_cookie',True):
            response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.get('/')
    def index():
        return render_template('index.html',csrf=session['csrf'],preview=settings.get('preview',False))

    @app.get('/api/session')
    def state():
        return jsonify(authenticated=bool(session.get('admin')) and time.time()-session.get('issued',0)<28800,
                       csrf=session['csrf'],domain=settings.get('vpn_domain','vpn.example.com'))

    @app.post('/api/login')
    def login():
        now=time.time()
        with metrics.connect(db_path) as db:
            db.execute('DELETE FROM attempts WHERE at<?',(now-300,))
            if db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]>=10:
                return jsonify(error='Too many sign-in attempts. Try again in five minutes.'),429
            db.execute('INSERT INTO attempts VALUES (?)',(now,))
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):
            return jsonify(error='Invalid request.'),400
        password=data.get('password','')
        valid=check_password_hash(settings['password_hash'],password) if isinstance(password,str) else False
        if not valid or data.get('username') != settings.get('username','admin'):
            return jsonify(error='Incorrect username or password.'),401
        session.clear()
        session.update(admin=True,issued=now,csrf=secrets.token_urlsafe(32))
        session.permanent=True
        audit('Signed in','admin')
        return jsonify(csrf=session['csrf'])

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get('/api/dashboard')
    @authenticated
    def dashboard():
        now=time.time()
        users=manager.list()
        with metrics.connect(db_path) as db:
            meta={r['key']:r['value'] for r in db.execute('SELECT * FROM metadata')}
            last_ok=float(meta.get('last_ok',0))
            healthy=now-last_ok<10 and 'error' not in meta
            totals={r['key']:dict(r) for r in db.execute('SELECT * FROM totals')}
            today=time.strftime('%Y-%m-%d',time.gmtime(now))
            daily={r['key']:dict(r) for r in db.execute('SELECT * FROM daily WHERE day=?',(today,))}
            for user in users:
                row=totals.get(user['id'],{})
                user.update(upload=row.get('upload',0),download=row.get('download',0),
                    seconds=row.get('seconds',0),last_active=row.get('last_active'),
                    today=daily.get(user['id'],{}).get('upload',0)+daily.get(user['id'],{}).get('download',0))
                user['activity']='Unknown' if not healthy else ('Active recently' if row.get('last_active') and now-row['last_active']<10 else 'No recent activity')
            history=[dict(r) for r in db.execute("SELECT day,SUM(upload) upload,SUM(download) download FROM daily WHERE day>=date('now','-13 days') GROUP BY day ORDER BY day")]
            events=[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY at DESC LIMIT 12')]
            total=db.execute('SELECT COALESCE(SUM(upload),0),COALESCE(SUM(download),0) FROM totals').fetchone()
        return jsonify(users=users,healthy=healthy,last_ok=last_ok,started=float(meta['started']),
                       total_upload=total[0],total_download=total[1],history=history,events=events)

    @app.get('/api/wireguard')
    @authenticated
    def wireguard_list():
        if not wg_accounts.STATE.exists():
            return jsonify(installed=False, devices=[])
        return jsonify(installed=True, devices=sorted(wg_accounts.read()['devices']))

    @app.post('/api/wireguard')
    @authenticated
    def wireguard_add():
        data = request.get_json(silent=True)
        name = data.get('name') if isinstance(data, dict) else None
        wg_accounts.change(name)
        audit('Created WireGuard device', name)
        return jsonify(ok=True), 201

    @app.delete('/api/wireguard/<name>')
    @authenticated
    def wireguard_remove(name):
        wg_accounts.change(name, remove=True)
        audit('Revoked WireGuard device', name)
        return jsonify(ok=True)

    @app.get('/api/wireguard/<name>/sing-box-qr')
    @authenticated
    def wireguard_singbox_qr(name):
        data = wg_accounts.read()
        if name not in data['devices']:
            return jsonify(error='Unknown device.'), 404
        image = singbox_qr(name, wg_accounts.profile(data, name, wrapped=True))
        audit('Viewed sing-box QR code', name)
        return app.response_class(image, mimetype='image/png')

    @app.get('/api/wireguard/<name>/<kind>')
    @authenticated
    def wireguard_download(name, kind):
        data = wg_accounts.read()
        if name not in data['devices'] or kind not in {'conf', 'json'}:
            return jsonify(error='Unknown device or profile.'), 404
        audit('Downloaded WireGuard profile', name)
        response = app.response_class(wg_accounts.profile(data, name, kind == 'json'), mimetype='application/octet-stream')
        response.headers.set('Content-Disposition', 'attachment', filename=f'{name}.{kind}')
        return response

    @app.get('/api/native')
    @authenticated
    def native_list():
        return jsonify(native_accounts.listing())

    @app.post('/api/native')
    @authenticated
    def native_add():
        data = request.get_json(silent=True)
        name = data.get('name') if isinstance(data, dict) else None
        result = native_accounts.change(name)
        audit('Created native VPN account', name)
        return jsonify(result), 201

    @app.get('/api/native/<name>/password')
    @authenticated
    def native_password(name):
        account = native_accounts.load().get(name)
        if not account:
            return jsonify(error='Native VPN account not found.'), 404
        audit('Viewed native VPN password', name)
        return jsonify(password=account[1])

    @app.delete('/api/native/<name>')
    @authenticated
    def native_revoke(name):
        result = native_accounts.change(name, remove=True)
        audit('Revoked native VPN account', name)
        return jsonify(result)

    @app.post('/api/users')
    @authenticated
    def add():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict) or not isinstance(data.get('name'),str):
            return jsonify(error='Enter a username.'),400
        poll()  # Capture counters before restarting Outline.
        result=manager.add(data['name'].strip())
        audit('Created access',result['name'])
        return jsonify(result),201

    @app.get('/api/users/<key_id>/key')
    @authenticated
    def key(key_id):
        link=manager.key(key_id)
        audit('Viewed access key',key_id)
        return jsonify(key=link)

    @app.delete('/api/users/<key_id>')
    @authenticated
    def remove(key_id):
        poll()
        manager.remove(key_id)
        audit('Revoked access',key_id)
        return jsonify(ok=True)

    @app.get('/api/email/status')
    @authenticated
    def email_status():
        return jsonify(mailer.status(smtp_path))

    @app.post('/api/users/<key_id>/email')
    @authenticated
    def send_email(key_id):
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):
            raise ValueError('Invalid request.')
        recipient=mailer.email_address(data.get('email'))
        try:
            request_id=str(uuid.UUID(data.get('request_id','')))
        except (ValueError,TypeError,AttributeError):
            raise ValueError('Missing send request identifier. Reopen the Share panel.')
        fingerprint=hashlib.sha256(json.dumps([key_id,recipient]).encode()).hexdigest()
        config=mailer.load_config(smtp_path)
        user=next((u for u in manager.list() if u['id']==key_id),None)
        if not user:
            raise ValueError('Access key not found or revoked.')
        link=manager.key(key_id)
        msg=mailer.message(config['sender'],recipient,user['name'],link,
            domains=[manager.domain,urlsplit(settings['origin']).hostname])
        with metrics.connect(db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT * FROM email_jobs WHERE request_id=?',(request_id,)).fetchone()
            if previous:
                if previous['fingerprint']!=fingerprint:
                    return jsonify(error='This send request was already used for a different recipient. Reopen Share.'),409
                if previous['status']=='accepted':
                    return jsonify(ok=True,message=previous['message'])
                return jsonify(error=previous['message'] or 'Send already in progress or unconfirmed. Check the inbox before trying again.'),409
            count=db.execute('SELECT COUNT(*) FROM email_jobs WHERE at>?',(time.time()-3600,)).fetchone()[0]
            if count>=20:
                return jsonify(error='Email limit reached (20 requests per hour). Try again later.'),429
            db.execute('INSERT INTO email_jobs VALUES (?,?,?,?,?)',
                (request_id,fingerprint,time.time(),'sending','Send is in progress or unconfirmed. Check the recipient inbox before submitting again.'))
        status='accepted'
        detail='Gmail accepted the email with the profile attached. Ask the recipient to check their inbox or spam folder.'
        try:
            mailer.send(config,msg)
        except smtplib.SMTPAuthenticationError:
            status='failed';detail='Gmail rejected sign-in. Run outline-admin-email-setup to update the app password.'
        except smtplib.SMTPRecipientsRefused:
            status='failed';detail='The email provider rejected the recipient. Check the address.'
        except smtplib.SMTPDataError:
            status='failed';detail='The email provider rejected the message. Check account sending limits or attachment policies.'
        except (OSError,smtplib.SMTPException):
            status='unconfirmed';detail='Delivery could not be confirmed. Check the recipient inbox before reopening Share to try again.'
        with metrics.connect(db_path) as db:
            db.execute('UPDATE email_jobs SET status=?,message=? WHERE request_id=?',(status,detail,request_id))
        audit('Email accepted' if status=='accepted' else 'Email '+status,user['name'])
        if status!='accepted':
            return jsonify(error=detail),502
        return jsonify(ok=True,message=detail)

    @app.errorhandler(ValueError)
    def bad_request(error):
        return jsonify(error=str(error)),400

    @app.errorhandler(RuntimeError)
    def failure(error):
        return jsonify(error=str(error)),503

    @app.errorhandler(500)
    def internal(error):
        return jsonify(error='Server error. Check the outline-admin service logs.'),500

    return app


def start_collector(app):
    def worker():
        while True:
            app.extensions['poll']()
            time.sleep(2)
    threading.Thread(target=worker,daemon=True,name='outline-metrics').start()
