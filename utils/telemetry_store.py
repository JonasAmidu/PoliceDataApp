"""PostgreSQL telemetry storage; minute aggregates bound request-history growth."""
import math
import os
import time

from utils.telemetry import Presence, RequestMetric

LATENCY_BOUNDS = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, float('inf'))
RETENTION_SECONDS = 7 * 86400
SCHEMA = '''
CREATE TABLE IF NOT EXISTS telemetry_requests (
    minute BIGINT NOT NULL, route TEXT NOT NULL, method TEXT NOT NULL, status SMALLINT NOT NULL,
    count BIGINT NOT NULL, total_ms DOUBLE PRECISION NOT NULL, max_ms DOUBLE PRECISION NOT NULL,
    pageviews BIGINT NOT NULL, buckets BIGINT[] NOT NULL,
    PRIMARY KEY(minute, route, method, status));
CREATE TABLE IF NOT EXISTS telemetry_sessions (
    sid TEXT PRIMARY KEY, first_seen DOUBLE PRECISION NOT NULL, last_seen DOUBLE PRECISION NOT NULL,
    page TEXT NOT NULL, browser TEXT NOT NULL, system TEXT NOT NULL, device TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS telemetry_sessions_seen ON telemetry_sessions(last_seen);
CREATE TABLE IF NOT EXISTS telemetry_workers (
    worker TEXT PRIMARY KEY, started DOUBLE PRECISION NOT NULL, last_seen DOUBLE PRECISION NOT NULL,
    dropped BIGINT NOT NULL);
'''


def connect(url, read_only=False):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.rows import dict_row
    parameters = conninfo_to_dict(url)
    parameters.setdefault('sslmode', 'require')
    if parameters['sslmode'] not in ('require', 'verify-ca', 'verify-full') and parameters.get('host') not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Remote telemetry databases require TLS.')
    # The caller cannot accidentally remove bounded operation timeouts in its DSN.
    parameters.update(connect_timeout=3, options='-c statement_timeout=2000 -c lock_timeout=250 -c idle_in_transaction_session_timeout=3000',
                      application_name='policedata-telemetry', tcp_user_timeout=3000,
                      keepalives_idle=5, keepalives_interval=2, keepalives_count=1)
    if read_only:
        parameters['options'] += ' -c default_transaction_read_only=on'
    return psycopg.connect(**parameters, row_factory=dict_row)


class PostgresStore:
    def __init__(self, url):
        self.url = url
        self.last_cleanup = 0

    def initialize(self):
        """Explicit setup only. Never called from import, startup, or a request."""
        with connect(self.url) as db:
            db.execute(SCHEMA)

    def write_batch(self, events, worker=None):
        metrics = {}
        sessions = {}
        for event in events:
            if isinstance(event, RequestMetric):
                key = (math.floor(event.at / 60) * 60, event.route, event.method, event.status)
                aggregate = metrics.setdefault(key, [0, 0., 0., 0, [0] * len(LATENCY_BOUNDS)])
                aggregate[0] += 1
                aggregate[1] += event.ms
                aggregate[2] = max(aggregate[2], event.ms)
                aggregate[3] += int(event.pageview)
                aggregate[4][next(i for i, bound in enumerate(LATENCY_BOUNDS) if event.ms <= bound)] += 1
            elif isinstance(event, Presence):
                previous = sessions.get(event.sid)
                latest = event if previous is None or event.at >= previous[0].at else previous[0]
                sessions[event.sid] = (latest, min(previous[1], event.at) if previous else event.at)
        with connect(self.url) as db:
            with db.cursor() as cursor:
                if metrics:
                    cursor.executemany('''INSERT INTO telemetry_requests AS t VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(minute,route,method,status) DO UPDATE SET count=t.count+excluded.count,
                        total_ms=t.total_ms+excluded.total_ms, max_ms=greatest(t.max_ms,excluded.max_ms),
                        pageviews=t.pageviews+excluded.pageviews,
                        buckets=ARRAY(SELECT a+b FROM unnest(t.buckets,excluded.buckets) AS x(a,b))''',
                                       [(*key, *value) for key, value in metrics.items()])
                if sessions:
                    cursor.executemany('''INSERT INTO telemetry_sessions AS t VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(sid) DO UPDATE SET first_seen=least(t.first_seen,excluded.first_seen),
                        last_seen=greatest(t.last_seen,excluded.last_seen),
                        page=CASE WHEN excluded.last_seen>=t.last_seen THEN excluded.page ELSE t.page END,
                        browser=CASE WHEN excluded.last_seen>=t.last_seen THEN excluded.browser ELSE t.browser END,
                        system=CASE WHEN excluded.last_seen>=t.last_seen THEN excluded.system ELSE t.system END,
                        device=CASE WHEN excluded.last_seen>=t.last_seen THEN excluded.device ELSE t.device END''',
                                       [(e.sid, first, e.at, e.page, e.browser, e.system, e.device) for e, first in sessions.values()])
                if worker:
                    cursor.execute('''INSERT INTO telemetry_workers VALUES (%s,%s,%s,%s)
                        ON CONFLICT(worker) DO UPDATE SET last_seen=excluded.last_seen,dropped=excluded.dropped''', worker)
                now = time.time()
                if now - self.last_cleanup >= 60:
                    cursor.execute('SELECT pg_try_advisory_xact_lock(19847261) AS acquired')
                    if cursor.fetchone()['acquired']:
                        for table, field in (('telemetry_requests', 'minute'), ('telemetry_sessions', 'last_seen'), ('telemetry_workers', 'last_seen')):
                            # Identifiers are fixed constants. Deletes are capped to limit lock duration.
                            cursor.execute(f'DELETE FROM {table} WHERE ctid IN (SELECT ctid FROM {table} WHERE {field}<%s LIMIT 10000)', (now - RETENTION_SECONDS,))
                    self.last_cleanup = now

    def snapshot(self, hours):
        if hours not in (1, 24, 168):
            raise ValueError('Unsupported telemetry time range.')
        now = time.time()
        since = math.floor((now - hours * 3600) / 60) * 60
        with connect(self.url, read_only=True) as db:
            def rows(sql, values=()):
                return db.execute(sql, values).fetchall()
            totals = rows('''SELECT coalesce(sum(count),0)::bigint requests,
                coalesce(sum(count) FILTER(WHERE status>=400),0)::bigint errors,
                coalesce(sum(count) FILTER(WHERE status>=500),0)::bigint server_errors,
                coalesce(sum(total_ms)/nullif(sum(count),0),0)::float avg_ms,
                coalesce(sum(pageviews),0)::bigint pageviews, coalesce(max(max_ms),0)::float max_ms
                FROM telemetry_requests WHERE minute>=%s''', (since,))[0]
            session_counts = rows('''SELECT count(*) FILTER(WHERE last_seen>=%s)::bigint visitors,
                count(*) FILTER(WHERE last_seen>=%s)::bigint active FROM telemetry_sessions''', (since, now - 300))[0]
            totals.update(session_counts)
            histogram = rows('''SELECT n, sum(value)::bigint count FROM telemetry_requests,
                unnest(buckets) WITH ORDINALITY AS b(value,n) WHERE minute>=%s GROUP BY n ORDER BY n''', (since,))
            target, cumulative = math.ceil(totals['requests'] * .95), 0
            totals['p95_ms'] = 0
            for bucket in histogram:
                cumulative += bucket['count']
                if target and cumulative >= target:
                    bound = LATENCY_BOUNDS[bucket['n'] - 1]
                    totals['p95_ms'] = totals['max_ms'] if math.isinf(bound) else bound
                    break
            series = rows('''SELECT (minute/3600)*3600 AS at, sum(count)::bigint requests,
                coalesce(sum(count) FILTER(WHERE status>=400),0)::bigint errors
                FROM telemetry_requests WHERE minute>=%s GROUP BY minute/3600 ORDER BY at''', (since,))
            breakdowns = {}
            for field in ('browser', 'system', 'device'):
                breakdowns[field] = rows(f'''SELECT {field} name,count(*)::bigint count FROM telemetry_sessions
                    WHERE last_seen>=%s GROUP BY {field} ORDER BY count DESC''', (since,))
            active = rows('''SELECT substr(sid,1,8) visitor,page,browser,system,device,first_seen,last_seen
                FROM telemetry_sessions WHERE last_seen>=%s ORDER BY last_seen DESC LIMIT 100''', (now - 300,))
            routes = rows('''SELECT route,sum(count)::bigint requests,
                coalesce(sum(count) FILTER(WHERE status>=400),0)::bigint errors,
                (sum(total_ms)/sum(count))::float avg_ms FROM telemetry_requests WHERE minute>=%s
                GROUP BY route ORDER BY requests DESC LIMIT 20''', (since,))
            errors = rows('''SELECT minute AS at,route,status,max_ms AS ms,count FROM telemetry_requests
                WHERE minute>=%s AND status>=400 ORDER BY minute DESC,route,status LIMIT 30''', (since,))
            workers = rows('''SELECT count(*)::bigint count,min(started) started,coalesce(sum(dropped),0)::bigint dropped
                FROM telemetry_workers WHERE last_seen>=%s''', (now - 120,))[0]
            storage = rows("SELECT sum(pg_table_size(oid))::bigint bytes FROM pg_class WHERE oid IN ('telemetry_requests'::regclass,'telemetry_sessions'::regclass,'telemetry_workers'::regclass)")[0]['bytes']
        return dict(generated_at=now, hours=hours, totals=totals, series=series, breakdowns=breakdowns,
                    active=active, routes=routes, errors=errors, source='production',
                    uptime_seconds=round(now - workers['started']) if workers['started'] else 0,
                    storage_bytes=storage or 0, workers=workers['count'], dropped_events=workers['dropped'])


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    PostgresStore(os.environ['TELEMETRY_DATABASE_URL']).initialize()
    print('Telemetry tables initialized.')
