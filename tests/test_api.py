"""Offline regressions for request caching, API contracts and upstream failures."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import requests

import app as application
from utils.police_api import PoliceDataAPI, SimpleCache, UpstreamAPIError


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


class CacheTests(unittest.TestCase):
    def test_empty_results_are_cached_and_expire_at_ttl(self):
        cache = SimpleCache(default_ttl=10)
        with patch('utils.police_api.time.monotonic', return_value=100):
            cache.set('empty', [])
        with patch('utils.police_api.time.monotonic', return_value=109):
            self.assertEqual(cache.get('empty'), [])
        with patch('utils.police_api.time.monotonic', return_value=110):
            self.assertIsNone(cache.get('empty'))

    def test_cache_is_bounded_and_overwrites_existing_keys(self):
        cache = SimpleCache(max_entries=2)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('b', 3)
        self.assertEqual(cache.get('a'), 1)
        cache.set('c', 4)
        self.assertIsNone(cache.get('a'))
        self.assertEqual(cache.get('b'), 3)
        self.assertEqual(cache.get('c'), 4)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.api = PoliceDataAPI()
        self.api.session = Mock()

    def test_concurrent_queries_share_one_upstream_request_and_cache_empty_result(self):
        self.api.session.get.return_value = response([])
        gate = threading.Barrier(4)
        def query():
            gate.wait(timeout=2)
            return self.api.get_street_level_crimes('51', '-1', '2025-01')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: query(), range(4)))
        self.assertEqual(results, [[], [], [], []])
        self.api.session.get.assert_called_once()

    def test_rate_limit_retries_once_and_caches_success(self):
        self.api.session.get.side_effect = [response({}, 429), response([])]
        with patch('utils.police_api.time.sleep') as sleep:
            self.assertEqual(self.api.get_forces(), [])
            self.assertEqual(self.api.get_forces(), [])
        self.assertEqual(self.api.session.get.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_upstream_failure_and_bad_json_are_not_cached(self):
        for failure in (requests.Timeout(), ValueError('not JSON')):
            self.api.session.get.side_effect = failure if isinstance(failure, requests.Timeout) else None
            malformed = response([])
            malformed.json.side_effect = failure
            self.api.session.get.return_value = malformed
            with self.assertRaises(UpstreamAPIError):
                self.api.get_forces()
        self.api.session.get.side_effect = None
        self.api.session.get.return_value = response([])
        self.assertEqual(self.api.get_forces(), [])
        self.assertEqual(self.api.session.get.call_count, 3)

    def test_unexpected_data_shape_is_an_upstream_error(self):
        for payload in ({'error': 'unavailable'}, [None]):
            self.api.session.get.return_value = response(payload)
            with self.assertRaises(UpstreamAPIError):
                self.api.get_forces()

    def test_repeated_rate_limit_is_bounded_and_failure_is_not_cached(self):
        self.api.session.get.side_effect = [response({}, 429), response({}, 429), response([])]
        with patch('utils.police_api.time.sleep') as sleep:
            with self.assertRaises(UpstreamAPIError):
                self.api.get_forces()
            self.assertEqual(self.api.get_forces(), [])
        self.assertEqual(self.api.session.get.call_count, 3)
        sleep.assert_called_once_with(1)

    def test_malformed_crime_fields_fail_before_caching_and_can_recover(self):
        malformed = [
            {'category': {'name': 'burglary'}},
            {'category': 42},
            {'outcome_status': 'unexpected'},
            {'outcome_status': {'category': ['unexpected']}},
        ]
        for crime in malformed:
            with self.subTest(crime=crime):
                self.api.session.get.return_value = response([crime])
                with self.assertRaises(UpstreamAPIError):
                    self.api.get_crime_summary(lat='51', lng='0')
        self.api.session.get.return_value = response([{'category': 'burglary'}])
        self.assertEqual(self.api.get_crime_summary(lat='51', lng='0')['total'], 1)
        self.assertEqual(self.api.session.get.call_count, 5)

    def test_invalid_latest_date_is_not_cached(self):
        for payload in ({}, {'date': '2025-13-01'}, {'date': 2025}):
            self.api.session.get.return_value = response(payload)
            with self.assertRaises(UpstreamAPIError):
                self.api.get_last_updated()
        self.api.session.get.return_value = response({'date': '2025-01-01'})
        self.assertEqual(self.api.get_last_updated(), {'date': '2025-01-01'})
        self.assertEqual(self.api.session.get.call_count, 4)

    def test_invalid_geocoder_coordinates_are_not_cached_as_no_matches(self):
        self.api.session.get.return_value = response([{'lat': '999', 'lon': '0'}])
        with patch('utils.police_api.time.sleep'):
            with self.assertRaises(UpstreamAPIError):
                self.api.search_places('London')
            self.api.session.get.return_value = response([{'lat': '51', 'lon': '0'}])
            self.assertEqual(len(self.api.search_places('London')), 1)
        self.assertEqual(self.api.session.get.call_count, 2)
        self.api.session.get.return_value = response({'result': {'latitude': 999, 'longitude': 0}})
        with self.assertRaises(UpstreamAPIError):
            self.api.geocode_postcode('SW1A 1AA')

    def test_force_stops_use_stops_force_and_zero_coordinates_are_preserved(self):
        self.api.session.get.return_value = response([])
        self.api.get_stops_street(force='leicestershire', date='2025-01')
        self.api.session.get.assert_called_with(
            'https://data.police.uk/api/stops-force',
            params={'force': 'leicestershire', 'date': '2025-01'}, timeout=30)
        self.api.get_stops_street(lat=0, lng=0)
        self.api.session.get.assert_called_with(
            'https://data.police.uk/api/stops-street', params={'lat': 0, 'lng': 0}, timeout=30)

    def test_postcode_normalization_caches_and_not_found_differs_from_outage(self):
        self.api.session.get.return_value = response({'result': {
            'postcode': 'SW1A 1AA', 'latitude': 51.5, 'longitude': -0.1}})
        first = self.api.geocode_postcode(' sw1a 1aa ')
        self.assertEqual(first['lat'], 51.5)
        self.assertEqual(self.api.geocode_postcode('SW1A1AA'), first)
        self.api.session.get.assert_called_once()
        self.api.session.get.return_value = response({}, 404)
        self.assertIsNone(self.api.geocode_postcode('ZZ99 9ZZ'))
        self.api.session.get.side_effect = requests.Timeout()
        with self.assertRaises(UpstreamAPIError):
            self.api.geocode_postcode('W1A 1AA')

    def test_place_search_converts_coordinates_caches_and_throttles(self):
        self.api.session.get.return_value = response([
            {'display_name': 'London', 'lat': '51.5', 'lon': '-0.1'},
            {'display_name': 'Invalid', 'lat': 'nan', 'lon': '0'},
        ])
        with patch('utils.police_api.time.monotonic', return_value=100), patch('utils.police_api.time.sleep') as sleep:
            self.assertEqual(self.api.search_places(' London ')[0]['lng'], -0.1)
            self.assertEqual(len(self.api.search_places('london')), 1)
            self.api.search_places('Leicester')
        self.assertEqual(self.api.session.get.call_count, 2)
        sleep.assert_called_once_with(1)
        self.assertEqual(self.api.session.get.call_args.kwargs['params']['countrycodes'], 'gb')

    def test_neighbourhood_lists_and_details_have_correct_shapes(self):
        self.api.session.get.side_effect = [response([{'id': 'C01'}]), response({'id': 'C01'}),
                                             response([]), response([]), response([])]
        self.assertEqual(self.api.get_neighbourhoods('leicestershire'), [{'id': 'C01'}])
        result = self.api.get_neighbourhood_combined('leicestershire', 'C01')
        self.assertEqual(result['details'], {'id': 'C01'})
        self.assertEqual(result['priorities'], [])
        self.assertEqual(result['warnings'], [])

    def test_neighbourhood_optional_failure_is_reported(self):
        with patch.object(self.api, 'get_neighbourhood_details', return_value={'id': 'C01'}), \
             patch.object(self.api, 'get_neighbourhood_team', side_effect=UpstreamAPIError()), \
             patch.object(self.api, 'get_neighbourhood_events', return_value=[]), \
             patch.object(self.api, 'get_neighbourhood_priorities', return_value=[]):
            result = self.api.get_neighbourhood_combined('leicestershire', 'C01')
        self.assertEqual(result['team'], [])
        self.assertEqual(len(result['warnings']), 1)

    def test_summary_counts_outcomes_and_labels_unmapped_scope(self):
        records = [
            {'category': 'burglary', 'outcome_status': {'category': 'Under investigation'}},
            {'category': 'burglary', 'outcome_status': None},
            {'category': None, 'outcome_status': {'category': None}},
        ]
        self.api.session.get.return_value = response(records)
        result = self.api.get_crime_summary(force='leicestershire', date='2025-01')
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['scope'], 'unmapped-crimes-only')
        self.assertEqual(result['categories'], {'burglary': 2, 'other-crime': 1})
        self.assertEqual(result['category_breakdown'][0]['percentage'], 66.67)
        self.assertEqual(result['outcomes']['No outcome recorded'], 1)
        self.assertEqual(result['outcomes']['Status update unavailable'], 1)

    def test_summary_empty_data_has_empty_breakdowns(self):
        self.api.session.get.return_value = response([])
        result = self.api.get_crime_summary()
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['category_breakdown'], [])
        self.assertEqual(result['lat'], '51.5074')
        self.assertEqual(result['scope'], 'street-level')


class RouteTests(unittest.TestCase):
    def setUp(self):
        application.app.config['TESTING'] = True
        self.client = application.app.test_client()
        self.mock_api = Mock()
        self.patcher = patch.object(application, 'police_api', self.mock_api)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_coordinate_and_month_validation_prevents_upstream_calls(self):
        invalid = ['lat=51', 'lat=nan&lng=0', 'lat=91&lng=0', 'lat=0&lng=181',
                   'lat=abc&lng=0', 'date=2025-13', 'date=25-01', 'date=0000-01']
        for query in invalid:
            with self.subTest(query=query):
                result = self.client.get('/api/crimes/street?' + query)
                self.assertEqual(result.status_code, 400)
                self.assertFalse(result.json['success'])
        self.mock_api.get_street_level_crimes.assert_not_called()

    def test_street_default_uses_latest_month_and_zero_coordinates(self):
        self.mock_api.get_street_level_crimes.return_value = []
        self.assertEqual(self.client.get('/api/crimes/street').json, [])
        self.mock_api.get_street_level_crimes.assert_called_with('51.5074', '-0.1278', None)
        self.client.get('/api/crimes/street?lat=0&lng=0&date=2025-01')
        self.mock_api.get_street_level_crimes.assert_called_with('0', '0', '2025-01')

    def test_stops_force_contract_and_ambiguous_or_missing_scope_validation(self):
        self.mock_api.get_stops_street.return_value = []
        result = self.client.get('/api/stop-search/street?force=leicestershire&date=2025-01')
        self.assertEqual(result.status_code, 200)
        self.mock_api.get_stops_street.assert_called_with(None, None, '2025-01', 'leicestershire')
        for query in ('', 'lat=51&lng=0&force=leicestershire', 'force=bad_force'):
            self.assertEqual(self.client.get('/api/stop-search/street?' + query).status_code, 400)

    def test_upstream_error_is_502_not_empty_success(self):
        for endpoint, method in (('/api/forces', 'get_forces'),
                                 ('/api/crimes/street', 'get_street_level_crimes'),
                                 ('/api/analytics/summary', 'get_crime_summary'),
                                 ('/api/geocode/search?q=London', 'search_places')):
            getattr(self.mock_api, method).side_effect = UpstreamAPIError('Unavailable')
            result = self.client.get(endpoint)
            self.assertEqual(result.status_code, 502)
            self.assertEqual(result.json, {'success': False, 'error': 'Unavailable'})

    def test_malformed_upstream_record_returns_502_and_next_request_recovers(self):
        api = PoliceDataAPI()
        api.session = Mock()
        api.session.get.side_effect = [response([{'category': {'bad': 'shape'}}]), response([])]
        with patch.object(application, 'police_api', api):
            failed = self.client.get('/api/analytics/summary?lat=51&lng=0')
            self.assertEqual(failed.status_code, 502)
            self.assertFalse(failed.json['success'])
            recovered = self.client.get('/api/analytics/summary?lat=51&lng=0')
            self.assertEqual(recovered.status_code, 200)
            self.assertEqual(recovered.json['total'], 0)
        self.assertEqual(api.session.get.call_count, 2)

    def test_postcode_success_not_found_and_failure(self):
        self.mock_api.geocode_postcode.return_value = {'lat': 51.5, 'lng': -0.1}
        result = self.client.get('/api/geocode/postcode?q=SW1A1AA')
        self.assertEqual(result.json['result']['lat'], 51.5)
        self.mock_api.geocode_postcode.return_value = None
        self.assertEqual(self.client.get('/api/geocode/postcode?q=SW1A1AA').status_code, 404)
        self.mock_api.geocode_postcode.side_effect = UpstreamAPIError('Unavailable')
        self.assertEqual(self.client.get('/api/geocode/postcode?q=SW1A1AA').status_code, 502)
        self.assertEqual(self.client.get('/api/geocode/postcode').status_code, 400)

    def test_last_updated_returns_upstream_metadata(self):
        self.mock_api.get_last_updated.return_value = {'date': '2025-01-01'}
        self.assertEqual(self.client.get('/api/crimes/last-updated').json, {'date': '2025-01-01'})

    def test_summary_passes_validated_scope(self):
        self.mock_api.get_crime_summary.return_value = {'total': 0}
        self.assertEqual(self.client.get('/api/analytics/summary?lat=0&lng=0').status_code, 200)
        self.mock_api.get_crime_summary.assert_called_with(lat='0', lng='0', date=None, force=None)
        self.assertEqual(self.client.get('/api/analytics/summary?force=leicestershire').status_code, 200)
        self.mock_api.get_crime_summary.assert_called_with(lat=None, lng=None, date=None, force='leicestershire')


if __name__ == '__main__':
    unittest.main()
