"""Real PostgreSQL contract tests; CI supplies an isolated test database."""
import os
import time
import unittest

from utils.telemetry import Presence, RequestMetric
from utils.telemetry_store import PostgresStore, connect


@unittest.skipUnless(os.environ.get('TELEMETRY_TEST_DATABASE_URL'), 'Set TELEMETRY_TEST_DATABASE_URL to an isolated test database')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from psycopg.conninfo import conninfo_to_dict
        cls.url = os.environ['TELEMETRY_TEST_DATABASE_URL']
        if conninfo_to_dict(cls.url).get('dbname') != 'police_telemetry_test':
            raise RuntimeError('These tests require a dedicated police_telemetry_test database.')
        cls.store = PostgresStore(cls.url)
        cls.store.initialize()

    def setUp(self):
        with connect(self.url) as db:
            db.execute('TRUNCATE telemetry_requests, telemetry_sessions, telemetry_workers')
        self.store.last_cleanup = 0
        self.now = time.time()

    def test_batches_merge_minute_counts_latency_buckets_and_errors(self):
        events = [RequestMetric(self.now, '/', 'GET', 200, 10, True) for _ in range(90)]
        events += [RequestMetric(self.now, '/', 'GET', 200, 300, True) for _ in range(10)]
        self.store.write_batch(events[:50])
        self.store.write_batch(events[50:])
        self.store.write_batch([RequestMetric(self.now, '/api/forces', 'GET', 502, 20, False)])
        data = self.store.snapshot(1)
        self.assertEqual(data['totals']['requests'], 101)
        self.assertEqual(data['totals']['pageviews'], 100)
        self.assertEqual(data['totals']['server_errors'], 1)
        self.assertEqual(data['totals']['p95_ms'], 500)
        self.assertAlmostEqual(data['totals']['avg_ms'], 3920 / 101)
        with connect(self.url) as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM telemetry_requests').fetchone()['n'], 2)
        self.assertEqual(len(data['errors']), 1)
        self.assertEqual(sum(item['requests'] for item in data['series']), 101)

    def test_session_upserts_preserve_first_seen_and_latest_page_across_ordering(self):
        first = Presence(self.now - 20, 'a' * 64, '/', 'Chrome 130', 'Windows', 'Desktop')
        latest = Presence(self.now, 'a' * 64, '/forces', 'Chrome 130', 'Windows', 'Desktop')
        older = Presence(self.now - 40, 'a' * 64, '/crimes', 'Other', 'Other', 'Mobile')
        self.store.write_batch([latest, first])
        self.store.write_batch([older])
        data = self.store.snapshot(1)
        self.assertEqual(data['totals']['active'], 1)
        self.assertEqual(data['active'][0]['page'], '/forces')
        self.assertEqual(data['active'][0]['first_seen'], older.at)
        self.assertEqual(data['breakdowns']['browser'][0]['name'], 'Chrome 130')

    def test_time_ranges_active_window_retention_and_workers(self):
        self.store.write_batch([
            RequestMetric(self.now - 7200, '/', 'GET', 200, 1, True),
            RequestMetric(self.now - 8 * 86400, '/', 'GET', 200, 1, True),
            Presence(self.now - 301, 'a', '/', 'Other', 'Other', 'Desktop'),
            Presence(self.now, 'b', '/', 'Firefox 140', 'Linux', 'Desktop'),
            Presence(self.now - 8 * 86400, 'expired', '/', 'Other', 'Other', 'Desktop'),
        ], worker=('worker', self.now - 120, self.now, 4))
        self.assertEqual(self.store.snapshot(1)['totals']['requests'], 0)
        self.assertEqual(self.store.snapshot(24)['totals']['requests'], 1)
        data = self.store.snapshot(24)
        self.assertEqual(data['totals']['active'], 1)
        self.assertEqual(data['totals']['visitors'], 2)
        self.assertEqual(data['workers'], 1)
        self.assertEqual(data['dropped_events'], 4)
        self.assertGreater(data['storage_bytes'], 0)
        with connect(self.url) as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM telemetry_sessions').fetchone()['n'], 2)

    def test_readonly_connection_can_read_and_cannot_write(self):
        import psycopg
        with connect(self.url, read_only=True) as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM telemetry_requests').fetchone()['n'], 0)
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                db.execute('DELETE FROM telemetry_requests')

    def test_remote_connections_reject_plaintext_and_keep_timeout_bounds(self):
        with self.assertRaises(ValueError):
            connect('postgresql://user:password@db.example.com/db?sslmode=disable')


if __name__ == '__main__':
    unittest.main()
