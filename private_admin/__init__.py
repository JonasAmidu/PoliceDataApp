"""Authenticated operations panel. Credentials and telemetry stay outside Git."""
import functools
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from flask import Blueprint, Response, abort, g, jsonify, redirect, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

from utils.telemetry import Presence, RequestMetric, browser_info, init_app as init_telemetry
from utils.telemetry_store import PostgresStore

ROOT = Path(__file__).resolve().parent
ACTIVE_SECONDS = 300
RETENTION_SECONDS = 7 * 86400
ADMIN_COOKIE = 'police_admin'
CSRF_COOKIE = 'police_admin_csrf'


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS visitors (
                    sid TEXT PRIMARY KEY, first_seen REAL, last_seen REAL,
                    page TEXT, browser TEXT, system TEXT, device TEXT);
                CREATE INDEX IF NOT EXISTS visitors_seen ON visitors(last_seen);
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY, at REAL, route TEXT,
                    method TEXT, status INTEGER, ms REAL);
                CREATE INDEX IF NOT EXISTS requests_at ON requests(at);
                CREATE TABLE IF NOT EXISTS logins (key TEXT PRIMARY KEY, attempts INTEGER, until REAL);
                CREATE TABLE IF NOT EXISTS maintenance (id INTEGER PRIMARY KEY, last_run REAL);
                INSERT OR IGNORE INTO maintenance VALUES (1, 0);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, route, method, status, ms):
        now = time.time()
        with self.connect() as db:
            db.execute('INSERT INTO requests(at,route,method,status,ms) VALUES (?,?,?,?,?)',
                       (now, route, method, status, ms))
            updated = db.execute('UPDATE maintenance SET last_run=? WHERE id=1 AND last_run<?',
                                 (now, now - 3600)).rowcount
            if updated:
                db.execute('DELETE FROM requests WHERE at<?', (now - RETENTION_SECONDS,))
                db.execute('DELETE FROM visitors WHERE last_seen<?', (now - RETENTION_SECONDS,))
                db.execute('DELETE FROM logins WHERE until<?', (now,))

    def visit(self, sid, page, info):
        now = time.time()
        with self.connect() as db:
            db.execute('''INSERT INTO visitors VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(sid) DO UPDATE SET last_seen=excluded.last_seen,
                page=excluded.page, browser=excluded.browser, system=excluded.system,
                device=excluded.device''', (sid, now, now, page, *info))

    def login_attempt(self, key):
        now = time.time()
        with self.connect() as db:
            db.execute('''INSERT INTO logins VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET
                attempts=CASE WHEN until<? THEN 1 ELSE attempts+1 END,
                until=CASE WHEN until<? THEN excluded.until ELSE until END''',
                       (key, now + 900, now, now))
            return db.execute('SELECT attempts FROM logins WHERE key=?', (key,)).fetchone()[0] <= 10

    def snapshot(self, hours):
        now = time.time()
        since = now - hours * 3600
        with self.connect() as db:
            def rows(sql, params=()):
                return [dict(row) for row in db.execute(sql, params)]
            totals = dict(db.execute('''SELECT count(*) requests,
                coalesce(sum(status>=400),0) errors, coalesce(sum(status>=500),0) server_errors,
                coalesce(avg(ms),0) avg_ms FROM requests WHERE at>=?''', (since,)).fetchone())
            totals['visitors'] = db.execute('SELECT count(*) FROM visitors WHERE last_seen>=?', (since,)).fetchone()[0]
            totals['active'] = db.execute('SELECT count(*) FROM visitors WHERE last_seen>=?', (now - ACTIVE_SECONDS,)).fetchone()[0]
            latency = db.execute('SELECT ms FROM requests WHERE at>=? ORDER BY ms LIMIT 1 OFFSET ?',
                                 (since, max(0, int(totals['requests'] * .95 + .999) - 1))).fetchone()
            totals['p95_ms'] = latency[0] if latency else 0
            totals['pageviews'] = db.execute("SELECT count(*) FROM requests WHERE at>=? AND method='GET' AND status=200 AND route NOT LIKE '/api/%'", (since,)).fetchone()[0]
            series = rows('''SELECT cast(at/3600 AS INTEGER)*3600 at, count(*) requests,
                sum(status>=400) errors FROM requests WHERE at>=? GROUP BY cast(at/3600 AS INTEGER)
                ORDER BY at''', (since,))
            breakdowns = {}
            for field in ('browser', 'system', 'device'):
                breakdowns[field] = rows(f'''SELECT {field} name, count(*) count FROM visitors
                    WHERE last_seen>=? GROUP BY {field} ORDER BY count DESC LIMIT 12''', (since,))
            active = rows('''SELECT substr(sid,1,8) visitor, page, browser, system, device,
                first_seen, last_seen FROM visitors WHERE last_seen>=? ORDER BY last_seen DESC LIMIT 100''',
                          (now - ACTIVE_SECONDS,))
            routes = rows('''SELECT route, count(*) requests, sum(status>=400) errors, avg(ms) avg_ms
                FROM requests WHERE at>=? GROUP BY route ORDER BY requests DESC LIMIT 20''', (since,))
            errors = rows('''SELECT at, route, status, ms FROM requests WHERE at>=? AND status>=400
                ORDER BY at DESC LIMIT 30''', (since,))
        return dict(generated_at=now, hours=hours, totals=totals, series=series,
                    breakdowns=breakdowns, active=active, routes=routes, errors=errors)


    def write_batch(self, events, worker=None):
        now = time.time()
        with self.connect() as db:
            for event in events:
                if isinstance(event, RequestMetric):
                    db.execute('INSERT INTO requests(at,route,method,status,ms) VALUES (?,?,?,?,?)',
                               (event.at, event.route, event.method, event.status, event.ms))
                elif isinstance(event, Presence):
                    db.execute('''INSERT INTO visitors VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(sid) DO UPDATE SET last_seen=excluded.last_seen,page=excluded.page,
                        browser=excluded.browser,system=excluded.system,device=excluded.device''',
                               (event.sid, event.at, event.at, event.page, event.browser, event.system, event.device))
            if db.execute('UPDATE maintenance SET last_run=? WHERE id=1 AND last_run<?', (now, now - 3600)).rowcount:
                db.execute('DELETE FROM requests WHERE at<?', (now - RETENTION_SECONDS,))
                db.execute('DELETE FROM visitors WHERE last_seen<?', (now - RETENTION_SECONDS,))
                db.execute('DELETE FROM logins WHERE until<?', (now,))


def init_app(app):
    # Legacy local configuration remains supported, but is never needed on a deployment.
    settings_path = ROOT / 'settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    secret = os.environ.get('ADMIN_PANEL_SECRET', settings.get('secret', ''))
    password_hash = os.environ.get('ADMIN_PANEL_PASSWORD_HASH', settings.get('password_hash', ''))
    configured_password = os.environ.get('ADMIN_PANEL_PASSWORD', '')
    if not secret and not password_hash and not configured_password:
        return None
    if len(secret) < 32 or not (password_hash or len(configured_password) >= 16):
        app.logger.warning('Admin panel disabled: configure a strong signing secret and password or password hash.')
        return None
    route = os.environ.get('ADMIN_PANEL_PATH', settings.get('route', '/admin')).rstrip('/')
    if not re.fullmatch(r'/[a-zA-Z0-9_-]{1,100}', route):
        raise ValueError('ADMIN_PANEL_PATH must be one path segment of 1–100 letters, numbers, underscores or hyphens.')
    serializer = URLSafeTimedSerializer(secret)
    # Password changes invalidate sessions even if the signing secret is unchanged.
    identity = 'administrator:' + hmac.new(secret.encode(), (configured_password or password_hash).encode(), hashlib.sha256).hexdigest()
    local_database = app.config.get('ADMIN_TELEMETRY_DB')
    if not local_database:
        Path(app.instance_path).mkdir(parents=True, exist_ok=True, mode=0o700)
        local_database = Path(app.instance_path) / 'admin.sqlite3'
    store = Store(local_database)
    read_url = app.config.get('TELEMETRY_READ_DATABASE_URL', os.environ.get('TELEMETRY_READ_DATABASE_URL', ''))
    read_url = read_url or app.config.get('TELEMETRY_DATABASE_URL', os.environ.get('TELEMETRY_DATABASE_URL', ''))
    # Local telemetry is an explicit development option, never a production fallback.
    local_telemetry = app.config.get('ADMIN_LOCAL_TELEMETRY', False)
    source = PostgresStore(read_url) if read_url else store if local_telemetry else None
    if local_telemetry and not read_url:
        init_telemetry(app, store=store)
    app.extensions['private_admin'] = {'store': store, 'source': source, 'route': route}
    started = time.time()
    panel = Blueprint('private_admin', __name__, template_folder='templates')

    def sign(value, salt):
        return serializer.dumps(value, salt=salt)

    def load(value, salt, age):
        try:
            return serializer.loads(value or '', salt=salt, max_age=age)
        except (BadSignature, SignatureExpired):
            return None

    def cookie(response, name, value, age, path='/'):
        response.set_cookie(name, value, max_age=age, httponly=True,
                            secure=app.config.get('ADMIN_COOKIE_SECURE', True),
                            samesite='Strict', path=path)

    def same_origin():
        origin = request.headers.get('Origin')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            return False
        return not origin or (urlsplit(origin).scheme in ('http', 'https') and
                              urlsplit(origin).netloc == request.host)

    def csrf_valid():
        token = request.form.get('csrf', '')
        return (same_origin() and hmac.compare_digest(token.encode(), request.cookies.get(CSRF_COOKIE, '').encode())
                and isinstance(load(token, 'csrf', 3600), str))

    def authenticated():
        return load(request.cookies.get(ADMIN_COOKIE), 'admin', 3600) == identity

    def protected(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not authenticated():
                if request.path.endswith('/data'):
                    return jsonify(error='Authentication required.'), 401
                return redirect(route + '/login')
            return view(*args, **kwargs)
        return wrapped

    @panel.route(route + '/login', methods=['GET', 'POST'])
    def login():
        error, status = '', 200
        if request.method == 'POST':
            if request.content_length is None or request.content_length > 4096:
                abort(413)
            if not csrf_valid():
                abort(400)
            key = hmac.new(secret.encode(), (request.remote_addr or 'unknown').encode(), hashlib.sha256).hexdigest()
            if not store.login_attempt(key):
                error, status = 'Too many attempts. Try again in 15 minutes.', 429
            else:
                password = request.form.get('password', '')
                valid = False
                if len(password) <= 1024:
                    try:
                        valid = (hmac.compare_digest(password.encode(), configured_password.encode())
                                 if configured_password else check_password_hash(password_hash, password))
                    except ValueError:
                        pass
                if valid:
                    response = redirect(route)
                    cookie(response, ADMIN_COOKIE, sign(identity, 'admin'), 3600, route)
                    return response
                error, status = 'Incorrect password.', 401
        csrf = sign(secrets.token_urlsafe(24), 'csrf')
        response = Response(render_template('private_login.html', error=error, csrf=csrf), status=status)
        cookie(response, CSRF_COOKIE, csrf, 3600, route)
        return response

    @panel.route(route)
    @protected
    def dashboard():
        csrf = sign(secrets.token_urlsafe(24), 'csrf')
        response = Response(render_template('private_dashboard.html', base=route, csrf=csrf))
        cookie(response, CSRF_COOKIE, csrf, 3600, route)
        return response

    @panel.route(route + '/logout', methods=['POST'])
    @protected
    def logout():
        if not csrf_valid():
            abort(400)
        response = redirect(route + '/login')
        response.delete_cookie(ADMIN_COOKIE, path=route)
        response.delete_cookie(CSRF_COOKIE, path=route)
        return response

    @panel.route(route + '/data')
    @protected
    def data():
        try:
            hours = int(request.args.get('hours', '24'))
        except ValueError:
            abort(400)
        if hours not in (1, 24, 168):
            abort(400)
        if source is None:
            return jsonify(error='Telemetry is not configured. Connect the app’s PostgreSQL database to view activity.'), 503
        try:
            result = source.snapshot(hours)
        except Exception:
            return jsonify(error='Telemetry database unavailable. Check the private connection settings.'), 503
        if source is store:
            result['source'] = 'local'
            result['uptime_seconds'] = round(time.time() - started)
            result['storage_bytes'] = sum(path.stat().st_size for path in Path(store.path).parent.glob(Path(store.path).name + '*'))
        return jsonify(result)

    @panel.route(route + '/<asset>')
    def asset(asset):
        if asset not in ('panel.css', 'panel.js'):
            abort(404)
        if asset == 'panel.js' and not authenticated():
            abort(401)
        return Response((ROOT / asset).read_text(), mimetype='text/css' if asset.endswith('.css') else 'text/javascript')

    app.register_blueprint(panel)

    @app.after_request
    def private_headers(response):
        if request.blueprint == 'private_admin':
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
            response.headers['Referrer-Policy'] = 'same-origin'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        return response
