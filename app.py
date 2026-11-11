import functools
import hmac
import json
import os
from pathlib import Path
import secrets
import time

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash

import metrics
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
    app.config['USAGE_DATABASE'] = db_path

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
        return render_template('index.html',csrf=session['csrf'])

    @app.get('/api/session')
    def state():
        return jsonify(authenticated=bool(session.get('admin')) and time.time()-session.get('issued',0)<28800,
                       csrf=session['csrf'])

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

    @app.get('/api/wireguard')
    @authenticated
    def wireguard_list():
        if not wg_accounts.STATE.exists():
            return jsonify(installed=False, devices=[])
        data = wg_accounts.read()
        return jsonify(installed=True, devices=sorted(data['devices']), tcp=data['tcp'], udp=data['udp'],
                       **metrics.summary(db_path, data['devices']))

    def snapshot_before_restart():
        try:
            metrics.sample(db_path)
        except (metrics.grpc.RpcError, OSError, ValueError, StopIteration):
            pass

    @app.post('/api/wireguard')
    @authenticated
    def wireguard_add():
        data = request.get_json(silent=True)
        name = data.get('name') if isinstance(data, dict) else None
        snapshot_before_restart()
        wg_accounts.change(name)
        audit('Created WireGuard device', name)
        return jsonify(ok=True), 201

    @app.delete('/api/wireguard/<name>')
    @authenticated
    def wireguard_remove(name):
        snapshot_before_restart()
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
