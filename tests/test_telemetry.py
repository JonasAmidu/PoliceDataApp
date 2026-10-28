"""Privacy and failure-isolation checks for the optional production collector."""
import logging
import threading
import time
import unittest
from unittest.mock import Mock, patch

from flask import Flask, Response, render_template_string

from utils.telemetry import Collector, Presence, RequestMetric, browser_info, init_app


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.collector = Collector(self.store, logging.getLogger('test-telemetry'), interval=3600)
        self.addCleanup(self.collector.close)

    def metric(self, route='/'):
        return RequestMetric(time.time(), route, 'GET', 200, 12, True)

    def test_submitting_never_waits_for_database_io(self):
        blocker = threading.Event()
        entered = threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            blocker.wait(timeout=5)
        self.store.write_batch.side_effect = slow
        self.collector.submit(self.metric())
        worker = threading.Thread(target=self.collector.flush)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(blocker.set)
        self.assertTrue(entered.wait(timeout=1))
        # The writer is blocked in storage; the request-side queue remains usable.
        self.assertTrue(self.collector.submit(self.metric('/another')))
        self.assertEqual(self.collector.events.qsize(), 1)

    def test_queue_is_bounded_and_excess_metrics_are_dropped(self):
        self.collector.events.maxsize = 2
        self.assertTrue(self.collector.submit(self.metric()))
        self.assertTrue(self.collector.submit(self.metric()))
        self.assertFalse(self.collector.submit(self.metric()))
        self.assertEqual(self.collector.dropped, 1)
        self.assertEqual(self.collector.events.qsize(), 2)

    def test_outage_drops_batch_and_opens_backoff_without_leaking_errors(self):
        self.store.write_batch.side_effect = RuntimeError('postgres://secret:password@host/db')
        self.collector.submit(self.metric())
        with self.assertLogs('test-telemetry', level='WARNING') as captured:
            self.collector.flush()
        self.assertNotIn('password', str(captured.output))
        self.assertFalse(self.collector.submit(self.metric()))
        self.assertEqual(self.collector.dropped, 2)
        self.assertEqual(self.collector.events.qsize(), 0)
        self.collector.retry_at = 0
        self.store.write_batch.side_effect = None
        self.collector.submit(self.metric())
        self.collector.flush()
        self.assertEqual(self.collector.failures, 0)

    def test_repeat_presence_and_total_submission_rate_are_capped(self):
        presence = Presence(time.time(), 'session', '/', 'Chrome 130', 'Windows', 'Desktop')
        self.assertTrue(self.collector.submit(presence))
        self.assertFalse(self.collector.submit(presence))
        for _ in range(110):
            self.collector.submit(self.metric())
        self.assertEqual(self.collector.events.qsize(), 100)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, TELEMETRY_ENABLED=True)
        self.app.add_url_rule('/', 'home', lambda: render_template_string('<body>{% if telemetry_enabled %}<script src="/static/js/telemetry.js" defer></script>{% endif %}</body>'))
        self.app.add_url_rule('/health', 'health', lambda: {'status': 'ok'})
        self.app.add_url_rule('/api/items/<item>', 'items', lambda item: {'item': item})
        self.app.add_url_rule('/api/error', 'error', lambda: ({'error': 'upstream failed'}, 502))
        self.store = Mock()
        self.collector = init_app(self.app, self.store)
        self.collector.interval = 3600
        self.addCleanup(self.collector.close)
        self.client = self.app.test_client()

    def events(self):
        result = []
        while not self.collector.events.empty():
            result.append(self.collector.events.get_nowait())
        return result

    def test_unconfigured_app_has_no_hooks_threads_or_presence_route(self):
        app = Flask('unconfigured')
        app.config['TELEMETRY_DATABASE_URL'] = ''
        self.assertIsNone(init_app(app))
        self.assertNotIn('telemetry', app.extensions)
        self.assertEqual(app.test_client().post('/api/telemetry/presence').status_code, 404)

    def test_explicit_disable_switch_overrides_a_configured_database(self):
        app = Flask('disabled')
        app.config.update(TELEMETRY_DATABASE_URL='postgres://unused', TELEMETRY_ENABLED='off')
        self.assertIsNone(init_app(app))

    def test_requests_retain_patterns_but_discard_queries_identifiers_ips_and_user_agents(self):
        self.client.get('/api/items/personal-identifier?q=secret-postcode', headers={'User-Agent': 'Secret browser fingerprint'})
        self.client.get('/sensitive-path?lat=51.5')
        self.client.get('/api/error')
        events = self.events()
        self.assertEqual([event.route for event in events], ['/api/items/<item>', '(unmatched route)', '/api/error'])
        self.assertEqual([event.status for event in events], [200, 404, 502])
        for value in ('personal-identifier', 'secret-postcode', 'sensitive-path', '51.5', 'fingerprint', '127.0.0.1'):
            self.assertNotIn(value, repr(events))
        self.store.write_batch.assert_not_called()

    def test_page_response_has_no_cookies_or_cache_changes(self):
        response = self.client.get('/')
        self.assertIn(b'telemetry.js', response.data)
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertNotIn('Cache-Control', response.headers)
        self.assertTrue(self.events()[0].pageview)

    def test_opt_out_skips_script_and_sessions_but_keeps_unidentified_request_counts(self):
        for headers in ({'DNT': '1'}, {'Sec-GPC': '1'}):
            self.assertNotIn(b'telemetry.js', self.client.get('/', headers=headers).data)
            response = self.client.post('/api/telemetry/presence', json={'session': 'a' * 32, 'page': '/'}, headers=headers)
            self.assertEqual(response.status_code, 204)
        self.assertTrue(all(isinstance(event, RequestMetric) for event in self.events()))

    def test_presence_is_small_same_origin_route_validated_and_coarsely_categorized(self):
        response = self.client.post('/api/telemetry/presence', json={'session': 'a' * 32, 'page': '/'}, headers={'Origin': 'http://localhost', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36'})
        self.assertEqual(response.status_code, 204)
        event, = self.events()
        self.assertIsInstance(event, Presence)
        self.assertEqual((event.browser, event.system, event.device), ('Chrome 130', 'Windows', 'Desktop'))
        self.assertNotEqual(event.sid, 'a' * 32)
        self.assertNotIn('Set-Cookie', response.headers)

    def test_presence_rejects_oversized_cross_origin_and_arbitrary_data(self):
        url = '/api/telemetry/presence'
        body = {'session': 'a' * 32, 'page': '/'}
        self.assertEqual(self.client.post(url, json=body, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post(url, json=body, headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
        self.assertEqual(self.client.post(url, json={**body, 'page': '/private-path?secret=x'}).status_code, 400)
        self.assertEqual(self.client.post(url, json={**body, 'session': 'not-valid'}).status_code, 400)
        self.assertEqual(self.client.post(url, json={**body, 'extra': 'x' * 300}).status_code, 413)
        self.assertEqual(self.client.post(url, data='{}', content_type='text/plain').status_code, 415)
        self.assertEqual(self.client.post(url, data='{', content_type='application/json').status_code, 400)
        self.assertEqual(self.events(), [])

    def test_health_static_and_heartbeats_are_excluded_from_request_counts(self):
        self.client.get('/health')
        self.client.get('/static/missing.css')
        self.client.post('/api/telemetry/presence', json={'session': 'a' * 32, 'page': '/'})
        self.assertTrue(all(isinstance(event, Presence) for event in self.events()))

    def test_collector_failure_does_not_change_the_app_response(self):
        with patch.object(self.collector, 'submit', side_effect=RuntimeError('broken instrumentation')):
            self.assertEqual(self.client.get('/').status_code, 200)
            self.assertEqual(self.client.get('/api/error').status_code, 502)
            self.assertEqual(self.client.post('/api/telemetry/presence', json={'session': 'a' * 32, 'page': '/'}).status_code, 204)

    def test_browser_categories(self):
        self.assertEqual(browser_info('Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Edg/130.0'), ('Edge 130', 'Windows', 'Desktop'))
        self.assertEqual(browser_info('Mozilla/5.0 (iPhone) Version/17.1 Mobile Safari/604.1'), ('Safari 17', 'iOS', 'Mobile'))


if __name__ == '__main__':
    unittest.main()
