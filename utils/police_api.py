import logging
import math
import os
import threading
import time
from collections import Counter
from datetime import date as calendar_date
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)


class UpstreamAPIError(RuntimeError):
    """An upstream service did not return usable data."""


class SimpleCache:
    """Thread-safe, bounded in-memory cache with monotonic TTL expiration."""

    def __init__(self, default_ttl=600, max_entries=1024):
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if time.monotonic() >= expiry:
                del self._cache[key]
                return None
            return value

    def set(self, key, value, ttl=None):
        if value is None:
            return
        ttl = self.default_ttl if ttl is None else ttl
        now = time.monotonic()
        with self._lock:
            for stale in [key for key, (_, expiry) in self._cache.items() if expiry <= now]:
                del self._cache[stale]
            if key not in self._cache and len(self._cache) >= self.max_entries:
                del self._cache[next(iter(self._cache))]
            self._cache[key] = (value, now + ttl)

    def delete(self, key):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def __contains__(self, key):
        return self.get(key) is not None


class PoliceDataAPI:
    def __init__(self, cache_ttl=600):
        self.base_url = 'https://data.police.uk/api'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'PoliceDataUK-WebApp/1.0',
            'Accept': 'application/json',
        })
        self.cache = SimpleCache(default_ttl=cache_ttl)
        # Recheck the cache while holding the lock to coalesce concurrent requests.
        self._request_lock = threading.Lock()
        self._geocode_lock = threading.Lock()
        self._last_place_request = None
        self.nominatim_url = os.environ.get(
            'NOMINATIM_SEARCH_URL', 'https://nominatim.openstreetmap.org/search'
        )

    def _make_request(self, endpoint, params=None, use_cache=True, ttl=None, expected_type=list):
        """Cache successful requests, with one bounded retry for rate limiting."""
        cache_key = ('police', endpoint, tuple(sorted((params or {}).items())))
        with self._request_lock:
            if use_cache:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    return cached
            for attempt in range(2):
                try:
                    response = self.session.get(
                        f'{self.base_url}/{endpoint}', params=params, timeout=30
                    )
                    if response.status_code == 429 and attempt == 0:
                        time.sleep(1)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, expected_type) or (
                        isinstance(data, list) and not all(isinstance(item, dict) for item in data)
                    ):
                        raise ValueError('Unexpected response format')
                    if endpoint == 'crime-last-updated':
                        updated = data.get('date')
                        if not isinstance(updated, str) or len(updated) != 10:
                            raise ValueError('Missing latest crime date')
                        calendar_date.fromisoformat(updated)
                    if endpoint in ('crimes-street/all-crime', 'crimes-no-location'):
                        for crime in data:
                            category, outcome = crime.get('category'), crime.get('outcome_status')
                            if category is not None and not isinstance(category, str):
                                raise ValueError('Unexpected crime category')
                            if outcome is not None and not isinstance(outcome, dict):
                                raise ValueError('Unexpected crime outcome')
                            status = outcome.get('category') if outcome is not None else None
                            if status is not None and not isinstance(status, str):
                                raise ValueError('Unexpected crime outcome category')
                    if use_cache:
                        self.cache.set(cache_key, data, ttl=ttl)
                    return data
                except (requests.exceptions.RequestException, ValueError) as exc:
                    logger.warning('Police API request failed for %s: %s', endpoint, exc)
                    raise UpstreamAPIError('Police data is temporarily unavailable. Please try again.') from exc

    def geocode_postcode(self, postcode):
        if not isinstance(postcode, str) or not postcode.strip():
            return None
        cleaned = postcode.strip().upper().replace(' ', '')
        cache_key = ('postcode', cleaned)
        with self._geocode_lock:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
            try:
                response = self.session.get(
                    f'https://api.postcodes.io/postcodes/{quote(cleaned, safe="")}', timeout=15
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                result = response.json().get('result')
                if not isinstance(result, dict):
                    raise ValueError('Missing postcode result')
                lat, lng = float(result['latitude']), float(result['longitude'])
                if not (math.isfinite(lat) and math.isfinite(lng)
                        and -90 <= lat <= 90 and -180 <= lng <= 180):
                    raise ValueError('Invalid postcode coordinates')
                output = dict(result, lat=lat, lng=lng)
                self.cache.set(cache_key, output)
                return output
            except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
                logger.warning('Postcode geocoding failed: %s', exc)
                raise UpstreamAPIError('Postcode lookup is temporarily unavailable. Please try again.') from exc

    def search_places(self, query):
        if not isinstance(query, str) or not query.strip():
            return []
        cleaned = query.strip()
        cache_key = ('place', cleaned.casefold())
        # Public Nominatim permits at most one request/second across this process.
        with self._geocode_lock:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
            if self._last_place_request is not None:
                remaining = 1 - (time.monotonic() - self._last_place_request)
                if remaining > 0:
                    time.sleep(remaining)
            self._last_place_request = time.monotonic()
            try:
                response = self.session.get(self.nominatim_url, params={
                    'q': cleaned, 'format': 'json', 'countrycodes': 'gb', 'limit': 5,
                }, timeout=15)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError('Unexpected place search response')
                results = []
                for item in data:
                    try:
                        lat, lng = float(item['lat']), float(item['lon'])
                        if not (math.isfinite(lat) and math.isfinite(lng)
                                and -90 <= lat <= 90 and -180 <= lng <= 180):
                            continue
                        results.append({
                            'display_name': item.get('display_name', cleaned),
                            'lat': lat, 'lng': lng,
                            'place_id': item.get('place_id'), 'type': item.get('type'),
                            'class': item.get('class'), 'importance': item.get('importance'),
                        })
                    except (ValueError, KeyError, TypeError):
                        continue
                if data and not results:
                    raise ValueError('Place search returned invalid coordinates')
                self.cache.set(cache_key, results)
                return results
            except (requests.exceptions.RequestException, ValueError) as exc:
                logger.warning('Place geocoding failed: %s', exc)
                raise UpstreamAPIError('Place search is temporarily unavailable. Please try again.') from exc

    def get_forces(self):
        return self._make_request('forces')

    def get_force_details(self, force_id):
        return self._make_request(f'forces/{force_id}', expected_type=dict)

    def get_force_people(self, force_id):
        return self._make_request(f'forces/{force_id}/people')

    def get_crime_categories(self):
        return self._make_request('crime-categories')

    def get_last_updated(self):
        return self._make_request('crime-last-updated', expected_type=dict)

    def get_street_level_crimes(self, lat, lng, date=None):
        params = {'lat': lat, 'lng': lng}
        if date:
            params['date'] = date
        return self._make_request('crimes-street/all-crime', params)

    def get_neighbourhoods(self, force_id):
        return self._make_request(f'{force_id}/neighbourhoods')

    def get_neighbourhood_details(self, force_id, neighbourhood_id):
        return self._make_request(f'{force_id}/{neighbourhood_id}', expected_type=dict)

    def get_neighbourhood_team(self, force_id, neighbourhood_id):
        return self._make_request(f'{force_id}/{neighbourhood_id}/people')

    def get_neighbourhood_events(self, force_id, neighbourhood_id):
        return self._make_request(f'{force_id}/{neighbourhood_id}/events')

    def get_neighbourhood_priorities(self, force_id, neighbourhood_id):
        return self._make_request(f'{force_id}/{neighbourhood_id}/priorities')

    def get_neighbourhood_combined(self, force_id, neighbourhood_id):
        details = self.get_neighbourhood_details(force_id, neighbourhood_id)
        combined = {
            'force_id': force_id, 'neighbourhood_id': neighbourhood_id,
            'details': details, 'warnings': [],
        }
        for name, fetch in (
            ('team', self.get_neighbourhood_team),
            ('events', self.get_neighbourhood_events),
            ('priorities', self.get_neighbourhood_priorities),
        ):
            try:
                combined[name] = fetch(force_id, neighbourhood_id)
            except UpstreamAPIError:
                combined[name] = []
                combined['warnings'].append(f'Neighbourhood {name} could not be loaded.')
        return combined

    def get_stops_street(self, lat=None, lng=None, date=None, force=None):
        if force and lat is None and lng is None:
            return self.get_stops_force(force, date)
        params = {'lat': lat, 'lng': lng}
        if date:
            params['date'] = date
        return self._make_request('stops-street', params)

    def get_stops_force(self, force, date=None):
        params = {'force': force}
        if date:
            params['date'] = date
        return self._make_request('stops-force', params)

    def get_crime_summary(self, lat=None, lng=None, date=None, force=None):
        """Aggregate a local area, or explicitly scoped unmapped force records."""
        if lat is None and lng is None and not force:
            lat, lng = '51.5074', '-0.1278'
        if lat is not None and lng is not None:
            crimes = self.get_street_level_crimes(lat, lng, date)
            scope = 'street-level'
        else:
            params = {'category': 'all-crime', 'force': force}
            if date:
                params['date'] = date
            crimes = self._make_request('crimes-no-location', params)
            scope = 'unmapped-crimes-only'
        category_counter, outcome_counter = Counter(), Counter()
        for crime in crimes:
            category_counter[crime.get('category') or 'other-crime'] += 1
            outcome = crime.get('outcome_status')
            status = (outcome.get('category') or 'Status update unavailable') if isinstance(outcome, dict) else 'No outcome recorded'
            outcome_counter[status] += 1
        total = len(crimes)
        return {
            'total': total, 'total_crimes': total,
            'categories': dict(category_counter),
            'category_breakdown': [
                {'category': category, 'name': category.replace('-', ' ').title(),
                 'count': count, 'percentage': round(count / total * 100, 2)}
                for category, count in category_counter.most_common()
            ],
            'outcomes': dict(outcome_counter),
            'outcome_breakdown': [
                {'status': status, 'count': count, 'percentage': round(count / total * 100, 2)}
                for status, count in outcome_counter.most_common()
            ],
            'lat': lat, 'lng': lng, 'date': date, 'force': force, 'scope': scope,
        }
