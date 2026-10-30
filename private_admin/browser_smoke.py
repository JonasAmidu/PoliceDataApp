"""Exercise the real local extension in Chromium against a temporary database."""
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
        'ADMIN_PANEL_PATH': '/admin', 'ADMIN_PANEL_SECRET': secrets.token_urlsafe(48),
        'ADMIN_PANEL_PASSWORD': password, 'ADMIN_PANEL_PASSWORD_HASH': '',
        'TELEMETRY_ENABLED': '1', 'TELEMETRY_DATABASE_URL': '', 'TELEMETRY_READ_DATABASE_URL': '',
    }):
        from config import Config
        Config.ADMIN_TELEMETRY_DB = Path(temp) / 'browser.sqlite3'
        Config.ADMIN_LOCAL_TELEMETRY = True
        Config.ADMIN_COOKIE_SECURE = False  # This test server runs on loopback HTTP.
        if os.environ.get('TELEMETRY_TEST_DATABASE_URL'):
            from psycopg.conninfo import conninfo_to_dict
            from utils.telemetry_store import connect
            from private_admin.provision_database import provision
            test_url = os.environ['TELEMETRY_TEST_DATABASE_URL']
            assert conninfo_to_dict(test_url).get('dbname') == 'police_telemetry_test'
            credentials = provision(test_url, Path(temp))
            with connect(test_url) as db:
                db.execute('TRUNCATE telemetry_requests,telemetry_sessions,telemetry_workers')
            os.environ['TELEMETRY_DATABASE_URL'] = credentials['writer']
            os.environ['TELEMETRY_READ_DATABASE_URL'] = credentials['reader']
            os.environ['TELEMETRY_ENABLED'] = '1'
        from app import app
        from flask import render_template_string
        app.add_url_rule('/presence-check', 'presence_check', lambda: render_template_string('<html><body>Presence check{% if telemetry_enabled %}<script src="/static/js/telemetry.js" defer></script>{% endif %}</body></html>'))
        route = app.extensions['private_admin']['route']
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        server = make_server('127.0.0.1', 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as playwright:
                options = {'headless': True}
                if os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'):
                    options['executable_path'] = os.environ['PLAYWRIGHT_CHROMIUM_EXECUTABLE']
                browser = playwright.chromium.launch(**options)
                context = browser.new_context(viewport={'width': 1440, 'height': 1080})
                errors = []
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
                with page.expect_response('**/api/telemetry/presence') as heartbeat:
                    page.goto(url + '/presence-check')
                assert heartbeat.value.status == 204
                app.extensions['telemetry'].flush()
                page.goto(url + route)
                expect(page.get_by_label('Admin password')).to_be_visible()
                page.get_by_label('Admin password').fill(password)
                page.get_by_role('button', name='Open operations panel').click()
                expect(page.locator('#active-count')).to_have_text('1')
                expect(page.locator('#request-count')).to_have_text('1')
                expect(page.locator('#sessions-body')).to_contain_text('/presence-check')
                expect(page.locator('#browser-breakdown')).to_contain_text('Chrome')
                expect(page.locator('#chart svg')).to_be_visible()
                assert context.request.get(url + route + '/data').status == 200
                for value in ('1', '168', '24'):
                    with page.expect_response('**/data?hours=' + value):
                        page.locator('#range').select_option(value)
                output = Path(os.environ.get('POLICE_ADMIN_BROWSER_ARTIFACTS', temp))
                output.mkdir(parents=True, exist_ok=True)
                desktop = output / 'preview-desktop.png'
                page.screenshot(path=str(desktop), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                expect(page.locator('#active-count')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile page overflows horizontally'
                page.screenshot(path=str(output / 'preview-mobile.png'), full_page=True)
                page.get_by_role('button', name='Sign out').click()
                expect(page.get_by_label('Admin password')).to_be_visible()
                assert context.request.get(url + route + '/data').status == 401
                assert not errors, errors
                if os.environ.get('TELEMETRY_TEST_DATABASE_URL'):
                    import psycopg
                    with connect(credentials['reader']) as db:
                        assert db.execute('SELECT count(*) n FROM telemetry_sessions').fetchone()['n'] == 1
                        try:
                            db.execute('DELETE FROM telemetry_sessions')
                        except psycopg.errors.ReadOnlySqlTransaction:
                            pass
                        else:
                            raise AssertionError('Reader account was allowed to delete telemetry')
                    with connect(credentials['writer']) as db:
                        try:
                            db.execute('CREATE TABLE unwanted_table (id integer)')
                        except psycopg.errors.InsufficientPrivilege:
                            pass
                        else:
                            raise AssertionError('Writer account was allowed to create tables')
                context.close()
                browser.close()
                print('Browser smoke passed: login, session presence, chart, time ranges, mobile layout, logout; no JS or CSP errors.')
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            app.extensions['telemetry'].close()


if __name__ == '__main__':
    main()
