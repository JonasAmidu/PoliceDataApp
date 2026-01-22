import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-please-change-in-production'
    CACHE_TYPE = 'simple'
    CACHE_DEFAULT_TIMEOUT = 300
    JSON_SORT_KEYS = False
    
    # API Configuration
    POLICE_API_BASE_URL = 'https://data.police.uk/api'
    REQUEST_TIMEOUT = 30
    
    # Cache durations in seconds
    CACHE_DURATIONS = {
        'forces': 3600,
        'crime_categories': 86400,
        'neighbourhoods': 7200,
        'crimes': 1800,
        'stop_search': 1800,
        'locations': 3600
    }
