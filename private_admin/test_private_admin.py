"""Private behavior checks; no production configuration or database is modified."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
from pathlib import Path
import json
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from flask import Flask
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

import private_admin
from private_admin import configure


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('test-password', method='pbkdf2:sha256:1000')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.route = '/_private-test-route'
        self.secret = 'test-only-signing-secret-' * 3
        (root / 'settings.json').write_text(json.dumps(dict(route=self.route, secret=self.secret, password_hash=self.password_hash)))
        for asset in ('panel.css', 'panel.js'):
            shutil.copyfile(private_admin.ROOT / asset, root / asset)
        self.root_patch = patch.object(private_admin, 'ROOT', root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.env_patch = patch.dict('os.environ', {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['ADMIN_TELEMETRY_DB'] = root / 'telemetry.sqlite3'
        self.app.config['ADMIN_LOCAL_TELEMETRY'] = True
        self.app.add_url_rule('/', 'home', lambda: '<html><body>Hello</body></html>')
        self.app.add_url_rule('/health', 'health', lambda: {'status': 'ok'})
        self.app.add_url_rule('/api/items/<item>', 'items', lambda item: {'item': item})
        self.app.add_url_rule('/api/error', 'error', lambda: ({'error': 'unavailable'}, 502))
        private_admin.init_app(self.app)
        self.addCleanup(self.app.extensions['telemetry'].close)
        self.store = self.app.extensions['private_admin']['store']
        self.client = self.app.test_client()

    def csrf(self, client=None):
        client = client or self.client
        client.get(self.route + '/login')
        return client.get_cookie(private_admin.CSRF_COOKIE, path=self.route).value

    def login(self, client=None):
        client = client or self.client
        return client.post(self.route + '/login', data={'csrf': self.csrf(client), 'password': 'test-password'})

    def test_panel_and_data_require_auth_and_are_never_cached(self):
        response = self.client.get(self.route)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, self.route + '/login')
        response = self.client.get(self.route + '/data')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('noindex', response.headers['X-Robots-Tag'])
        self.assertEqual(response.headers['Referrer-Policy'], 'same-origin')
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(self.client.get(self.route + '/panel.js').status_code, 401)
        self.assertEqual(self.client.get(self.route + '/panel.css').status_code, 200)

    def test_login_dashboard_logout(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', response.headers['Set-Cookie'])
        panel = self.client.get(self.route)
        self.assertEqual(panel.status_code, 200)
        self.assertIn(b'Operations overview', panel.data)
        self.assertEqual(self.client.get(self.route + '/data').status_code, 200)
        token = self.client.get_cookie(private_admin.CSRF_COOKIE, path=self.route).value
        self.assertEqual(self.client.post(self.route + '/logout', data={'csrf': token}).status_code, 302)
        self.assertEqual(self.client.get(self.route + '/data').status_code, 401)

    def test_login_and_logout_reject_missing_or_cross_site_csrf(self):
        self.assertEqual(self.client.post(self.route + '/login', data={'password': 'test-password'}).status_code, 400)
        self.assertEqual(self.client.post(self.route + '/login', data={'csrf': '♥', 'password': 'test-password'}).status_code, 400)
        token = self.csrf()
        response = self.client.post(self.route + '/login', data={'csrf': token, 'password': 'test-password'}, headers={'Origin': 'https://attacker.example'})
        self.assertEqual(response.status_code, 400)
        self.login()
        self.assertEqual(self.client.post(self.route + '/logout').status_code, 400)

    def test_password_and_cookie_tampering_do_not_authenticate(self):
        response = self.client.post(self.route + '/login', data={'csrf': self.csrf(), 'password': 'wrong'})
        self.assertEqual(response.status_code, 401)
        self.client.set_cookie(private_admin.ADMIN_COOKIE, 'administrator', path=self.route)
        self.assertEqual(self.client.get(self.route + '/data').status_code, 401)

    def test_expired_admin_token_is_rejected(self):
        serializer = URLSafeTimedSerializer(self.secret)
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp', return_value=1):
            token = serializer.dumps('administrator', salt='admin')
        self.client.set_cookie(private_admin.ADMIN_COOKIE, token, path=self.route)
        self.assertEqual(self.client.get(self.route + '/data').status_code, 401)

    def test_login_is_rate_limited(self):
        token = self.csrf()
        for _ in range(10):
            response = self.client.post(self.route + '/login', data={'csrf': token, 'password': 'wrong'})
            token = self.client.get_cookie(private_admin.CSRF_COOKIE, path=self.route).value
            self.assertEqual(response.status_code, 401)
        response = self.client.post(self.route + '/login', data={'csrf': token, 'password': 'test-password'})
        self.assertEqual(response.status_code, 429)

    def test_https_sets_secure_cookie(self):
        response = self.client.get(self.route + '/login', base_url='https://localhost')
        self.assertIn('Secure;', response.headers['Set-Cookie'])

    def test_secure_cookie_is_default_even_behind_http_proxy(self):
        response = self.client.get(self.route + '/login')
        self.assertIn('Secure;', response.headers['Set-Cookie'])

    def test_login_rejects_oversized_password_and_request(self):
        token = self.csrf()
        response = self.client.post(self.route + '/login', data={'csrf': token, 'password': 'x' * 1025})
        self.assertEqual(response.status_code, 401)
        response = self.client.post(self.route + '/login', data={'csrf': token, 'password': 'x' * 5000})
        self.assertEqual(response.status_code, 413)


    def test_browser_classification(self):
        self.assertEqual(private_admin.browser_info('Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36 Edg/130.0'), ('Edge 130', 'Windows', 'Desktop'))
        self.assertEqual(private_admin.browser_info('Mozilla/5.0 (iPhone; CPU iPhone OS 17) Version/17.1 Mobile Safari/604.1'), ('Safari 17', 'iOS', 'Mobile'))
        self.assertEqual(private_admin.browser_info('Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile Safari/537.36'), ('Chrome 130', 'Android', 'Mobile'))





    def test_time_range_validation(self):
        self.login()
        for value in ('0', '25', 'invalid', '-1'):
            self.assertEqual(self.client.get(self.route + '/data?hours=' + value).status_code, 400)
        for value in ('1', '24', '168'):
            self.assertEqual(self.client.get(self.route + '/data?hours=' + value).status_code, 200)

    def test_remote_source_does_not_collect_local_traffic_or_expose_database_errors(self):
        with patch.dict('os.environ', {'TELEMETRY_READ_DATABASE_URL': 'postgresql://reader@database/telemetry'}):
            with patch.object(private_admin, 'PostgresStore') as factory:
                remote_app = Flask('remote-panel')
                remote_app.config['TESTING'] = True
                remote_app.config['ADMIN_TELEMETRY_DB'] = Path(self.temp.name) / 'remote.sqlite3'
                private_admin.init_app(remote_app)
                self.assertNotIn('telemetry', remote_app.extensions)
                client = remote_app.test_client()
                self.login(client)
                factory.return_value.snapshot.return_value = {'source': 'production', 'totals': {'requests': 10}}
                response = client.get(self.route + '/data')
                self.assertEqual(response.json['source'], 'production')
                self.assertEqual(response.json['totals']['requests'], 10)
                factory.return_value.snapshot.assert_called_once_with(24)
                factory.return_value.snapshot.side_effect = RuntimeError('postgres://secret:password@host/db')
                response = client.get(self.route + '/data')
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(b'password', response.data)

    def test_cleanup_and_range_filters(self):
        now = time.time()
        self.store.record('/', 'GET', 200, 12)
        self.store.visit('expired', '/', ('Other', 'Other', 'Desktop'))
        with self.store.connect() as db:
            db.execute('UPDATE requests SET at=?', (now - 8 * 86400,))
            db.execute('UPDATE visitors SET last_seen=?', (now - 8 * 86400,))
            db.execute('UPDATE maintenance SET last_run=0')
        self.store.record('/new', 'GET', 200, 30)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM visitors').fetchone()[0], 0)
        self.assertEqual(self.store.snapshot(1)['totals']['p95_ms'], 30)

    def test_concurrent_storage_has_no_lost_requests(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.store.record('/api/test', 'GET', 200, 10), range(40)))
        self.assertEqual(self.store.snapshot(1)['totals']['requests'], 40)


class RuntimeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(private_admin, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.environment = patch.dict('os.environ', {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def application(self, **config):
        app = Flask('runtime-panel')
        app.config.update(TESTING=True, ADMIN_TELEMETRY_DB=self.root / 'auth.sqlite3', **config)
        return app

    def credentials(self):
        return patch.dict('os.environ', {
            'ADMIN_PANEL_SECRET': 'test-only-signing-secret-' * 3,
            'ADMIN_PANEL_PASSWORD_HASH': generate_password_hash('test-password', method='pbkdf2:sha256:1000'),
        })

    def test_clean_checkout_without_credentials_has_no_admin_routes_or_storage(self):
        app = self.application()
        with patch.object(private_admin, 'Store') as store:
            private_admin.init_app(app)
        store.assert_not_called()
        self.assertNotIn('private_admin', app.extensions)
        self.assertEqual(app.test_client().get('/admin').status_code, 404)

    def test_partial_credentials_leave_public_app_running_without_panel(self):
        for settings in ({'ADMIN_PANEL_PASSWORD': 'test-only-password'},
                         {'ADMIN_PANEL_SECRET': 'test-only-signing-secret-' * 3},
                         {'ADMIN_PANEL_SECRET': 'too-short', 'ADMIN_PANEL_PASSWORD': 'test-only-password'}):
            with self.subTest(settings=list(settings)), patch.dict('os.environ', settings, clear=True):
                app = self.application()
                private_admin.init_app(app)
                self.assertEqual(app.test_client().get('/admin').status_code, 404)

    def authenticate(self, app):
        client = app.test_client()
        client.get('/admin/login')
        token = client.get_cookie(private_admin.CSRF_COOKIE, path='/admin').value
        result = client.post('/admin/login', data={'csrf': token, 'password': 'test-password'})
        self.assertEqual(result.status_code, 302)
        return client

    def test_runtime_only_configuration_and_missing_database_are_explicit(self):
        with self.credentials():
            app = self.application()
            private_admin.init_app(app)
        self.assertEqual(app.extensions['private_admin']['route'], '/admin')
        self.assertNotIn('telemetry', app.extensions)
        client = self.authenticate(app)
        self.assertEqual(client.get('/admin').status_code, 200)
        response = client.get('/admin/data')
        self.assertEqual(response.status_code, 503)
        self.assertIn('not configured', response.json['error'])
        self.assertNotIn('postgresql://', response.get_data(as_text=True))

    def test_panel_reads_the_collector_database_without_a_settings_file(self):
        with self.credentials(), patch.dict('os.environ', {'TELEMETRY_DATABASE_URL': 'postgresql://test-db/telemetry'}):
            with patch.object(private_admin, 'PostgresStore') as source:
                app = self.application()
                private_admin.init_app(app)
                source.assert_called_once_with('postgresql://test-db/telemetry')
                source.return_value.snapshot.return_value = {'source': 'production', 'totals': {'requests': 42}}
                response = self.authenticate(app).get('/admin/data?hours=168')
                self.assertEqual(response.json['totals']['requests'], 42)
                source.return_value.snapshot.assert_called_once_with(168)

    def test_password_rotation_revokes_existing_sessions(self):
        with self.credentials():
            app = self.application()
            private_admin.init_app(app)
            first = self.authenticate(app)
            token = first.get_cookie(private_admin.ADMIN_COOKIE, path='/admin').value
            with patch.dict('os.environ', {'ADMIN_PANEL_PASSWORD': 'different-test-password'}):
                changed = self.application()
                private_admin.init_app(changed)
        client = changed.test_client()
        client.set_cookie(private_admin.ADMIN_COOKIE, token, path='/admin')
        self.assertEqual(client.get('/admin/data').status_code, 401)


class CredentialSetupTests(unittest.TestCase):
    def test_setup_keeps_generated_secrets_in_private_files_without_printing_them(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(configure, '__file__', str(Path(temp) / 'configure.py')):
            output = io.StringIO()
            with redirect_stdout(output):
                configure.main()
            root = Path(temp)
            values = json.loads((root / 'settings.json').read_text())
            password = next(line.split(': ', 1)[1] for line in (root / 'ACCESS.txt').read_text().splitlines() if line.startswith('Password: '))
            self.assertTrue(private_admin.check_password_hash(values['password_hash'], password))
            for value in (values['secret'], values['password_hash'], password):
                self.assertNotIn(value, output.getvalue())
            handoff = dict(line.split('=', 1) for line in (root / 'production-admin.env').read_text().splitlines())
            self.assertEqual(handoff['ADMIN_PANEL_SECRET'], values['secret'])
            self.assertEqual(handoff['ADMIN_PANEL_PASSWORD_HASH'], values['password_hash'])
            self.assertEqual(handoff['ADMIN_PANEL_PATH'], '/admin')
            for filename in ('settings.json', 'ACCESS.txt', 'production-admin.env'):
                self.assertEqual((root / filename).stat().st_mode & 0o777, 0o600)
            previous = {p.name: p.read_bytes() for p in root.iterdir()}
            with redirect_stdout(io.StringIO()):
                configure.main()
            self.assertEqual(previous, {p.name: p.read_bytes() for p in root.iterdir()})



if __name__ == '__main__':
    unittest.main()
