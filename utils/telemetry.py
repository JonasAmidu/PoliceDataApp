"""Optional first-party telemetry. Request handlers never contact the database."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import os
import queue
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

from flask import g, request


@dataclass(frozen=True)
class RequestMetric:
    at: float
    route: str
    method: str
    status: int
    ms: float
    pageview: bool


@dataclass(frozen=True)
class Presence:
    at: float
    sid: str
    page: str
    browser: str
    system: str
    device: str


def browser_info(agent):
    """Discard the raw UA; retain coarse categories and a bounded major version."""
    agent = agent[:512]
    browser = 'Other'
    for pattern, name in (
        (r'Edg(?:e|A|iOS)?/(\d{1,4})', 'Edge'), (r'(?:OPR|Opera)/(\d{1,4})', 'Opera'),
        (r'(?:Firefox|FxiOS)/(\d{1,4})', 'Firefox'),
        (r'(?:Chrome|CriOS)/(\d{1,4})', 'Chrome'),
        (r'Version/(\d{1,4})[\d.]*.*Safari/', 'Safari'),
    ):
        match = re.search(pattern, agent)
        if match:
            browser = name + ' ' + match.group(1)
            break
    system = next((name for marker, name in (
        ('Android', 'Android'), ('iPhone', 'iOS'), ('iPad', 'iPadOS'),
        ('Windows', 'Windows'), ('Macintosh', 'macOS'), ('Linux', 'Linux'),
    ) if marker in agent), 'Other')
    device = ('Tablet' if 'iPad' in agent or ('Android' in agent and 'Mobile' not in agent)
              else 'Mobile' if any(value in agent for value in ('Mobile', 'iPhone')) else 'Desktop')
    return browser, system, device


class Collector:
    """Bounded lossy queue, one background writer, backoff on storage outages."""
    def __init__(self, store, logger, capacity=2048, interval=2, batch_size=128):
        self.store, self.logger = store, logger
        self.events = queue.Queue(maxsize=capacity)
        self.interval, self.batch_size = interval, batch_size
        self.pid = os.getpid()
        self.started = time.time()
        self.worker_id = secrets.token_hex(12)
        self.thread = None
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.retry_at = 0
        self.failures = 0
        self.dropped = 0
        self.last_report = 0
        self.seen = OrderedDict()
        self.window_start = time.monotonic()
        self.window_count = 0

    def submit(self, event):
        # Gunicorn --preload must not reuse a parent's queue or thread in a child.
        if self.pid != os.getpid():
            self.__init__(self.store, self.logger, self.events.maxsize, self.interval, self.batch_size)
        now = time.monotonic()
        if now < self.retry_at:
            self.dropped += 1
            return False
        with self.lock:
            if now - self.window_start >= 1:
                self.window_start, self.window_count = now, 0
            if self.window_count >= 100:
                self.dropped += 1
                return False
            if isinstance(event, Presence):
                previous = self.seen.get(event.sid)
                if previous is not None and now - previous < 50:
                    return False
                self.seen[event.sid] = now
                self.seen.move_to_end(event.sid)
                while len(self.seen) > 4096:
                    self.seen.popitem(last=False)
            try:
                self.events.put_nowait(event)
            except queue.Full:
                self.dropped += 1
                return False
            self.window_count += 1
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='telemetry-writer', daemon=True)
                self.thread.start()
        return True

    def _run(self):
        while not self.stopped.wait(self.interval):
            self.flush()

    def flush(self):
        """Used only by the background thread (or controlled test/shutdown code)."""
        batch = []
        for _ in range(self.batch_size):
            try:
                batch.append(self.events.get_nowait())
            except queue.Empty:
                break
        now = time.time()
        report = now - self.last_report >= 60
        if not batch and (not report or not self.last_report):
            return
        if time.monotonic() < self.retry_at:
            self.dropped += len(batch)
            return
        worker = (self.worker_id, self.started, now, self.dropped) if report else None
        try:
            self.store.write_batch(batch, worker=worker)
            self.failures, self.retry_at = 0, 0
            if report:
                self.last_report = now
        except Exception:
            # Never log exception text: driver errors may contain connection credentials.
            self.dropped += len(batch)
            self.failures += 1
            self.retry_at = time.monotonic() + min(60, 5 * 2 ** min(self.failures - 1, 4))
            self.logger.warning('Telemetry storage unavailable; dropping metrics and backing off.')

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)


def init_app(app, store=None):
    """A missing URL or explicit disable switch leaves the public app untouched."""
    url = app.config.get('TELEMETRY_DATABASE_URL', os.environ.get('TELEMETRY_DATABASE_URL', ''))
    enabled = app.config.get('TELEMETRY_ENABLED', os.environ.get('TELEMETRY_ENABLED', '1'))
    if str(enabled).lower() in ('0', 'false', 'off') or (store is None and not url):
        return None
    if 'telemetry' in app.extensions:
        return app.extensions['telemetry']
    if store is None:
        from utils.telemetry_store import PostgresStore
        store = PostgresStore(url)
    collector = Collector(store, app.logger)
    app.extensions['telemetry'] = collector

    def opted_out():
        return request.headers.get('DNT') == '1' or request.headers.get('Sec-GPC') == '1'

    def private():
        return request.blueprint == 'private_admin'

    @app.context_processor
    def telemetry_context():
        return {'telemetry_enabled': not opted_out() and not private()}

    @app.before_request
    def start_timing():
        g.telemetry_start = time.perf_counter()

    @app.after_request
    def record_request(response):
        if (private() or request.endpoint in ('health', 'static', 'telemetry_presence')
                or request.method == 'OPTIONS'):
            return response
        try:
            route = str(request.url_rule) if request.url_rule else '(unmatched route)'
            collector.submit(RequestMetric(
                time.time(), route, request.method[:8], response.status_code,
                min(600000, max(0, (time.perf_counter() - g.telemetry_start) * 1000)),
                request.method == 'GET' and response.status_code == 200 and response.mimetype == 'text/html',
            ))
        except Exception:
            # Instrumentation must not change an application response, including during shutdown.
            pass
        return response

    @app.route('/api/telemetry/presence', methods=['POST'])
    def telemetry_presence():
        origin = request.headers.get('Origin')
        if (request.headers.get('Sec-Fetch-Site') == 'cross-site' or
                (origin and (urlsplit(origin).scheme not in ('http', 'https') or
                             urlsplit(origin).netloc != request.host))):
            return '', 403
        if opted_out():
            return '', 204
        if request.mimetype != 'application/json':
            return '', 415
        if request.content_length is None or request.content_length > 256:
            return '', 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('session'), str) or not re.fullmatch(r'[0-9a-f]{32}', body['session']):
            return '', 400
        pages = {str(rule) for rule in app.url_map.iter_rules() if 'GET' in rule.methods
                 and '<' not in str(rule) and rule.endpoint not in ('health', 'static')
                 and not rule.endpoint.startswith('private_admin.') and not str(rule).startswith('/api/')}
        if not isinstance(body.get('page'), str) or body['page'] not in pages:
            return '', 400
        try:
            collector.submit(Presence(time.time(), hashlib.sha256(body['session'].encode()).hexdigest(),
                                      body['page'], *browser_info(request.user_agent.string)))
        except Exception:
            pass
        return '', 204

    return collector
