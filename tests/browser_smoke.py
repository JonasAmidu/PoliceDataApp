"""Browser integration checks with real JS libraries and fixed upstream HTTP data.

Run: python tests/browser_smoke.py
Requires Playwright and its Chromium browser; see README.md for setup.
"""
import base64
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import requests
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app, police_api


ASSETS = {
    'https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css': 'bootstrap.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js': 'bootstrap.js',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css': 'leaflet.css',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js': 'leaflet.js',
    'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css': 'cluster.css',
    'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css': 'cluster-default.css',
    'https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js': 'cluster.js',
    'https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js': 'chart.js',
}
INJECTION = '<img src=x onerror="window.injected=true">'
CRIMES = [
    {'id': i, 'category': category, 'month': '2026-08',
     'location': {'latitude': str(51.5074 + i * .0001), 'longitude': '-0.1278',
                  'street': {'name': INJECTION if i == 1 else 'On or near High Street'}},
     'outcome_status': {'category': 'Under investigation'} if i == 1 else None}
    for i, category in enumerate(['burglary', 'anti-social-behaviour', 'burglary'], 1)
]
STOPS = [
    {'datetime': '2026-08-01T12:00:00+00:00', 'type': 'Person search',
     'object_of_search': 'Controlled drugs' if i % 2 else 'Stolen goods',
     'outcome': 'A no further action disposal', 'outcome_linked_to_object_of_search': False,
     'location': {'street': {'name': 'On or near High Street'}} if i % 3 else None}
    for i in range(65)
]


def upstream(url, params=None, **kwargs):
    """Replace only upstream transport, exercising the real API/cache/routes."""
    path = urlparse(url).path.removeprefix('/api/').strip('/')
    data = {
        'forces': [{'id': 'leicestershire', 'name': 'Leicestershire Police'},
                   {'id': 'metropolitan', 'name': 'Metropolitan Police'}],
        'forces/leicestershire': {'id': 'leicestershire', 'name': 'Leicestershire Police',
                                 'description': '<p>Serving local communities.</p>',
                                 'url': 'https://example.org', 'telephone': '101'},
        'forces/leicestershire/people': [{'name': 'Alex Smith', 'rank': 'Inspector'}],
        'crime-last-updated': {'date': '2026-08-01'},
        'crime-categories': [{'url': 'burglary', 'name': 'Burglary'},
                             {'url': 'anti-social-behaviour', 'name': 'Anti-social behaviour'}],
        'crimes-street/all-crime': CRIMES,
        'crimes-no-location': CRIMES,
        'stops-street': STOPS,
        'stops-force': STOPS,
        'leicestershire/neighbourhoods': [{'id': 'NC04', 'name': 'City Centre'},
                                        {'id': 'NC05', 'name': 'Riverside'}],
        'leicestershire/NC04': {'id': 'NC04', 'name': 'City Centre',
                               'description': '<p>Our local community.</p>',
                               'contact_details': {'telephone': '101'}},
        'leicestershire/NC04/people': [{'name': 'Alex Smith', 'rank': 'Inspector',
                                       'bio': '<p>Your neighbourhood officer.</p>'}],
        'leicestershire/NC04/events': [{'title': 'Community meeting', 'start_date': '2026-09-01',
                                       'description': '<p>Meet your local team.</p>'}],
        'leicestershire/NC04/priorities': [{'issue': '<p>Vehicle theft</p>', 'action': '<p>Extra patrols</p>'}],
        'leicestershire/NC05': {'id': 'NC05', 'name': 'Riverside'},
        'leicestershire/NC05/people': [],
        'leicestershire/NC05/events': [],
        'leicestershire/NC05/priorities': [],
        'search': [{'lat': '52.6369', 'lon': '-1.1398', 'display_name': 'Leicester, England, United Kingdom'}],
        'postcodes/SW1A1AA': {'result': {'postcode': 'SW1A 1AA', 'latitude': 51.501,
                                       'longitude': -.141, 'admin_district': 'Westminster'}},
    }
    response = requests.Response()
    response.status_code = 200 if path in data else 404
    response._content = json.dumps(data.get(path, {'error': 'Fixture not found'})).encode()
    response.url = url
    return response


class BrowserFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.asset_dir = Path(os.environ.get('POLICE_BROWSER_ASSET_DIR',
                                            Path(tempfile.gettempdir()) / 'police-browser-assets'))
        cls.asset_dir.mkdir(parents=True, exist_ok=True)
        for url, filename in ASSETS.items():
            target = cls.asset_dir / filename
            if not target.exists():
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                target.write_bytes(response.content)
        cls.transport = patch.object(police_api.session, 'get', side_effect=upstream)
        cls.transport.start()
        cls.addClassCleanup(cls.transport.stop)
        police_api.cache.clear()
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        cls.server = make_server('127.0.0.1', 0, app, threaded=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        options = {}
        if os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['PLAYWRIGHT_CHROMIUM_EXECUTABLE']
        cls.browser = cls.pw.chromium.launch(**options)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1100})
        self.addCleanup(self.context.close)
        self.context.route('**/*', self.route)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(error.stack or str(error)))

    def tearDown(self):
        self.assertEqual(self.errors, [], 'Unhandled browser JavaScript error')

    def route(self, route):
        url = route.request.url
        if url.startswith(self.url):
            return route.continue_()
        if url in ASSETS:
            filename = ASSETS[url]
            return route.fulfill(path=str(self.asset_dir / filename),
                                 content_type='text/css' if filename.endswith('.css') else 'application/javascript')
        if route.request.resource_type == 'image':
            return route.fulfill(content_type='image/png', body=base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII='))
        return route.fulfill(body='', content_type='text/css' if route.request.resource_type == 'stylesheet' else 'text/plain')

    def visit(self, path):
        self.page.goto(self.url + path)

    def test_home_map_filters_inspector_and_postcode(self):
        self.visit('/')
        expect(self.page.locator('#stat-total-crimes')).to_have_text('3')
        expect(self.page.locator('#date-select')).to_have_value('2026-08')
        expect(self.page.locator('.marker-cluster-custom')).to_have_count(1)
        self.page.locator('[data-cat="burglary"]').click()
        expect(self.page.locator('#results-status')).to_contain_text('2 selected incidents')
        self.page.locator('.inspector-crime-item').first.click()
        expect(self.page.locator('#inspector-body')).to_contain_text(INJECTION)
        expect(self.page.locator('#inspector-body img')).to_have_count(0)
        self.assertFalse(self.page.evaluate('Boolean(window.injected)'))
        self.page.locator('#location-search-input').fill('SW1A 1AA')
        with self.page.expect_response('**/api/crimes/street?**') as response:
            self.page.locator('#btn-search-crimes').click()
        self.assertIn('51.501', response.value.url)
        expect(self.page.locator('#stat-area-name')).to_contain_text('SW1A 1AA')
        # Let both the interrupted street focus and cluster animation callbacks settle.
        self.page.wait_for_timeout(1200)
        self.assertEqual(self.errors, [], 'Changing area during inspector focus must cancel stale cluster work')

    def test_home_map_clusters_thousands_and_filters_category(self):
        incidents = [
            {**CRIMES[0], 'id': index, 'category': 'burglary' if index % 2 else 'shoplifting',
             'location': {'latitude': '51.4998', 'longitude': '-0.1246',
                          'street': {'name': 'On or near Westminster'}}}
            for index in range(2000)
        ]
        self.page.route('**/api/crimes/street?**', lambda route: route.fulfill(json=incidents))
        self.visit('/')
        expect(self.page.locator('#stat-total-crimes')).to_have_text('2,000')
        expect(self.page.locator('.marker-cluster-custom')).to_have_count(1)
        expect(self.page.locator('.marker-cluster-custom')).to_have_text('2000')
        self.page.locator('[data-cat="burglary"]').click()
        expect(self.page.locator('#results-status')).to_contain_text('1,000 selected incidents')
        expect(self.page.locator('.marker-cluster-custom')).to_have_count(1)
        expect(self.page.locator('.marker-cluster-custom')).to_have_text('1000')
        self.page.locator('[data-cat="all"]').click()
        expect(self.page.locator('.marker-cluster-custom')).to_have_text('2000')

    def test_home_map_place_quick_jump_and_map_click(self):
        self.visit('/')
        expect(self.page.locator('#stat-total-crimes')).to_have_text('3')
        self.page.locator('#location-search-input').fill('Leicester')
        with self.page.expect_response('**/api/crimes/street?**') as response:
            self.page.locator('#btn-search-crimes').click()
        self.assertIn('52.6369', response.value.url)
        self.page.locator('[data-preset="manchester"]').click()
        expect(self.page.locator('#stat-area-name')).to_contain_text('Manchester')
        expect(self.page.locator('#map-loader')).not_to_have_class('map-loading-overlay active')
        with self.page.expect_response('**/api/crimes/street?**') as response:
            self.page.locator('#crime-map').click(position={'x': 100, 'y': 350})
        self.assertIn('lat=', response.value.url)
        expect(self.page.locator('#location-search-input')).to_have_value(re.compile(r'Selected point \(-?\d+\.\d+, -?\d+\.\d+\)'))

    def test_home_map_empty_and_upstream_error(self):
        self.visit('/')
        expect(self.page.locator('#stat-total-crimes')).to_have_text('3')
        self.page.route('**/api/crimes/street?**', lambda route: route.fulfill(json=[]))
        self.page.locator('[data-preset="bristol"]').click()
        expect(self.page.locator('#stat-total-crimes')).to_have_text('0')
        expect(self.page.locator('#inspector-body')).to_contain_text('No Crime Data Recorded')
        self.page.unroute('**/api/crimes/street?**')
        self.page.route('**/api/crimes/street?**', lambda route: route.fulfill(status=502, json={'error': 'Police data temporarily unavailable'}))
        self.page.locator('[data-preset="leeds"]').click()
        expect(self.page.locator('#map-feedback')).to_contain_text('temporarily unavailable')

    def test_force_modal_links_to_neighbourhood_profile_and_tabs(self):
        self.visit('/forces')
        self.page.locator('#forceSearchInput').fill('Leicestershire')
        expect(self.page.locator('.force-details')).to_have_count(1)
        self.page.locator('.force-details').click()
        expect(self.page.locator('#forceModal')).to_be_visible()
        expect(self.page.locator('#modalForceName')).to_have_text('Leicestershire Police')
        self.page.locator('#modalNeighbourhoodsBtn').click()
        expect(self.page.locator('#neighbourhoodDetail')).to_contain_text('City Centre')
        self.page.locator('#neighbourhood-tab-1').click()
        expect(self.page.locator('#neighbourhood-panel-1')).to_be_visible()
        expect(self.page.locator('#neighbourhood-panel-1')).to_contain_text('Alex Smith')
        self.page.locator('#neighbourhood-tab-3').click()
        expect(self.page.locator('#neighbourhood-panel-3')).to_contain_text('Community meeting')
        self.page.locator('#neighbourhoodFilter').fill('Riverside')
        self.page.locator('.neighbourhood-item').click()
        expect(self.page.locator('#neighbourhoodDetail')).to_contain_text('Riverside')

    def test_stop_search_location_pagination_filter_and_force(self):
        self.visit('/stop-search')
        expect(self.page.locator('#queryMonth')).to_have_value('2026-08')
        self.page.locator('#loadData').click()
        expect(self.page.locator('#stopRows tr')).to_have_count(50)
        self.page.locator('#nextPage').click()
        expect(self.page.locator('#stopRows tr')).to_have_count(15)
        self.page.locator('#stopFilter').select_option('Controlled drugs')
        expect(self.page.locator('#stopRows tr')).to_have_count(32)
        self.page.locator('#queryMode').select_option('force')
        self.page.locator('#queryForce').select_option('leicestershire')
        with self.page.expect_response('**/api/stop-search/street?**') as response:
            self.page.locator('#loadData').click()
        self.assertIn('force=leicestershire', response.value.url)
        self.assertNotIn('lat=', response.value.url)
        expect(self.page.locator('#resultsStatus')).to_contain_text('65 published records')

    def test_analytics_geocoding_charts_and_empty(self):
        self.visit('/analytics')
        expect(self.page.locator('#queryMonth')).to_have_value('2026-08')
        self.page.locator('#locationQuery').fill('SW1A 1AA')
        self.page.locator('#findLocation').click()
        self.page.locator('#locationMatches button').click()
        expect(self.page.locator('#queryLat')).to_have_value('51.501')
        self.page.locator('#loadData').click()
        expect(self.page.locator('#categoryRows tr')).to_have_count(2)
        expect(self.page.locator('#outcomeRows tr')).to_have_count(2)
        self.page.wait_for_function("Chart.getChart('categoryChart')?.data.datasets[0].data[0] === 2")
        self.page.wait_for_function("Chart.getChart('outcomeChart')?.data.datasets[0].data.reduce((a,b)=>a+b,0) === 3")
        self.page.route('**/api/analytics/summary?**', lambda route: route.fulfill(json={
            'total': 0, 'category_breakdown': [], 'outcome_breakdown': []}))
        self.page.locator('#loadData').click()
        expect(self.page.locator('#resultsStatus')).to_contain_text('0 crimes')
        expect(self.page.locator('#analyticsResults')).to_be_hidden()

    def test_crime_search_escaping_and_error_feedback(self):
        self.visit('/crimes')
        expect(self.page.locator('#date')).to_have_value('2026-08')
        self.page.locator('#crime-search button').click()
        expect(self.page.locator('#crime-results')).to_contain_text('Found 3 crimes')
        expect(self.page.locator('#crime-results')).to_contain_text(INJECTION)
        expect(self.page.locator('#crime-results img')).to_have_count(0)
        self.page.route('**/api/crimes/street?**', lambda route: route.fulfill(status=502, json={'error': 'Service unavailable'}))
        self.page.locator('#crime-search button').click()
        expect(self.page.locator('#crime-results .alert-danger')).to_have_text('Service unavailable')

    def test_mobile_navigation_and_layout(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.visit('/')
        expect(self.page.locator('#stat-total-crimes')).to_have_text('3')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.page.locator('.navbar-toggler').click()
        self.page.locator('.navbar-nav a[href="/analytics"]').click()
        expect(self.page.locator('a[aria-current="page"]')).to_have_attribute('href', '/analytics')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)


if __name__ == '__main__':
    unittest.main(verbosity=2)
