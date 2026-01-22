import requests
from flask import current_app

class PoliceDataAPI:
    def __init__(self):
        self.base_url = 'https://data.police.uk/api'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'PoliceDataUK-WebApp/1.0',
            'Accept': 'application/json'
        })
    
    def _make_request(self, endpoint, params=None):
        """Make API request with error handling"""
        url = f"{self.base_url}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"API request failed: {e}")
            return None
    
    # Force methods
    def get_forces(self):
        return self._make_request("forces")
    
    def get_force_details(self, force_id):
        return self._make_request(f"forces/{force_id}")
    
    def get_force_people(self, force_id):
        return self._make_request(f"forces/{force_id}/people")
    
    # Crime methods
    def get_crime_categories(self):
        return self._make_request("crime-categories")
    
    def get_street_level_crimes(self, lat, lng, date=None):
        params = {'lat': lat, 'lng': lng}
        if date:
            params['date'] = date
        return self._make_request("crimes-street/all-crime", params)
    
    # Neighbourhood methods
    def get_neighbourhoods(self, force_id):
        return self._make_request(f"{force_id}/neighbourhoods")
    
    def get_neighbourhood_details(self, force_id, neighbourhood_id):
        return self._make_request(f"{force_id}/{neighbourhood_id}")
    
    def get_neighbourhood_team(self, force_id, neighbourhood_id):
        return self._make_request(f"{force_id}/{neighbourhood_id}/people")
    
    def get_neighbourhood_events(self, force_id, neighbourhood_id):
        return self._make_request(f"{force_id}/{neighbourhood_id}/events")
    
    # Stop and search methods
    def get_stops_street(self, lat=None, lng=None, date=None, force=None):
        params = {}
        if lat and lng:
            params['lat'] = lat
            params['lng'] = lng
        if date:
            params['date'] = date
        if force:
            params['force'] = force
        return self._make_request("stops-street", params)
    
    def get_stops_force(self, force, date=None):
        params = {'force': force}
        if date:
            params['date'] = date
        return self._make_request("stops-force", params)
