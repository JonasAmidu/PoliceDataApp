#!/usr/bin/env python3
"""
Police Data UK Web App - Auto Setup Script
Run this single script to create and launch the complete application
"""

import os
import sys
import subprocess
import webbrowser
from pathlib import Path

def create_directory_structure():
    """Create the required directory structure"""
    directories = [
        'static/css',
        'static/js', 
        'templates',
        'utils'
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✓ Created directory: {directory}")

def create_file(filepath, content):
    """Create a file with the given content"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✓ Created file: {filepath}")

def install_requirements():
    """Install required Python packages"""
    print("Installing requirements...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask==2.3.3", "requests==2.31.0"])
        print("✓ Requirements installed successfully")
    except subprocess.CalledProcessError:
        print("✗ Failed to install requirements. Please run: pip install flask==2.3.3 requests==2.31.0")
        return False
    return True

def setup_application():
    """Main setup function"""
    print("🚀 Setting up Police Data UK Web Application...")
    print("=" * 50)
    
    # Create directory structure
    create_directory_structure()
    
    # Create requirements.txt
    create_file('requirements.txt', """Flask==2.3.3
requests==2.31.0
python-dotenv==1.0.0
""")
    
    # Create config.py
    create_file('config.py', '''import os
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
''')
    
    # Create police_api.py
    create_file('utils/police_api.py', '''import requests
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
''')
    
    # Create app.py (main application)
    create_file('app.py', '''from flask import Flask, render_template, request, jsonify
from config import Config
from utils.police_api import PoliceDataAPI

app = Flask(__name__)
app.config.from_object(Config)
police_api = PoliceDataAPI()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/forces')
def forces():
    return render_template('forces.html')

@app.route('/crimes')
def crimes():
    return render_template('crimes.html')

@app.route('/neighbourhoods')
def neighbourhoods():
    return render_template('neighbourhoods.html')

@app.route('/stop-search')
def stop_search():
    return render_template('stop_search.html')

@app.route('/analytics')
def analytics():
    return render_template('analytics.html')

# API Routes
@app.route('/api/forces')
def api_forces():
    forces_data = police_api.get_forces()
    return jsonify(forces_data or [])

@app.route('/api/force/<force_id>')
def api_force_details(force_id):
    force_data = police_api.get_force_details(force_id)
    return jsonify(force_data or {})

@app.route('/api/force/<force_id>/people')
def api_force_people(force_id):
    people_data = police_api.get_force_people(force_id)
    return jsonify(people_data or [])

@app.route('/api/crime-categories')
def api_crime_categories():
    categories = police_api.get_crime_categories()
    return jsonify(categories or [])

@app.route('/api/crimes/street')
def api_street_crimes():
    lat = request.args.get('lat', '51.5074')
    lng = request.args.get('lng', '-0.1278')
    date = request.args.get('date', '2024-01')
    crimes_data = police_api.get_street_level_crimes(lat, lng, date)
    return jsonify(crimes_data or [])

@app.route('/api/neighbourhoods/<force_id>')
def api_neighbourhoods(force_id):
    neighbourhoods = police_api.get_neighbourhoods(force_id)
    return jsonify(neighbourhoods or [])

@app.route('/api/stop-search/street')
def api_stop_search_street():
    lat = request.args.get('lat')
    lng = request.args.get('lng')
    date = request.args.get('date')
    force = request.args.get('force')
    stops_data = police_api.get_stops_street(lat, lng, date, force)
    return jsonify(stops_data or [])

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
''')
    
    # Create base template
    create_file('templates/base.html', '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Police Data UK Portal{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link href="{{ url_for('static', filename='css/style.css') }}" rel="stylesheet">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('index') }}">
                <i class="fas fa-shield-alt"></i> Police Data UK
            </a>
            <div class="navbar-nav">
                <a class="nav-link" href="{{ url_for('index') }}"><i class="fas fa-home"></i> Dashboard</a>
                <a class="nav-link" href="{{ url_for('forces') }}"><i class="fas fa-building"></i> Forces</a>
                <a class="nav-link" href="{{ url_for('crimes') }}"><i class="fas fa-exclamation-triangle"></i> Crimes</a>
                <a class="nav-link" href="{{ url_for('neighbourhoods') }}"><i class="fas fa-users"></i> Neighbourhoods</a>
                <a class="nav-link" href="{{ url_for('stop_search') }}"><i class="fas fa-search"></i> Stop & Search</a>
            </div>
        </div>
    </nav>

    <main class="container mt-4">
        {% block content %}{% endblock %}
    </main>

    <footer class="bg-dark text-light mt-5 py-4">
        <div class="container text-center">
            <p>Police Data UK Portal &copy; 2024 | Data Source: <a href="https://data.police.uk" class="text-light">Police UK API</a></p>
        </div>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="{{ url_for('static', filename='js/app.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>''')
    
    # Create index.html
    create_file('templates/index.html', '''{% extends "base.html" %}

{% block content %}
<div class="row">
    <div class="col-12">
        <div class="jumbotron bg-primary text-white p-5 rounded">
            <h1 class="display-4"><i class="fas fa-shield-alt"></i> Police Data UK Portal</h1>
            <p class="lead">Access comprehensive police data from across the UK</p>
        </div>
    </div>
</div>

<div class="row mt-4">
    <div class="col-md-3 mb-4">
        <div class="card text-white bg-success h-100">
            <div class="card-body text-center">
                <h4><i class="fas fa-building"></i></h4>
                <h5>Police Forces</h5>
                <p>Explore all UK police forces</p>
                <a href="{{ url_for('forces') }}" class="btn btn-light">View Forces</a>
            </div>
        </div>
    </div>
    <div class="col-md-3 mb-4">
        <div class="card text-white bg-warning h-100">
            <div class="card-body text-center">
                <h4><i class="fas fa-exclamation-triangle"></i></h4>
                <h5>Crime Data</h5>
                <p>Street-level crime information</p>
                <a href="{{ url_for('crimes') }}" class="btn btn-light">Search Crimes</a>
            </div>
        </div>
    </div>
    <div class="col-md-3 mb-4">
        <div class="card text-white bg-info h-100">
            <div class="card-body text-center">
                <h4><i class="fas fa-users"></i></h4>
                <h5>Neighbourhoods</h5>
                <p>Local policing teams</p>
                <a href="{{ url_for('neighbourhoods') }}" class="btn btn-light">Explore</a>
            </div>
        </div>
    </div>
    <div class="col-md-3 mb-4">
        <div class="card text-white bg-dark h-100">
            <div class="card-body text-center">
                <h4><i class="fas fa-search"></i></h4>
                <h5>Stop & Search</h5>
                <p>Stop and search records</p>
                <a href="{{ url_for('stop_search') }}" class="btn btn-light">View Data</a>
            </div>
        </div>
    </div>
</div>

<div class="row mt-4">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5><i class="fas fa-search"></i> Quick Crime Search</h5>
            </div>
            <div class="card-body">
                <form id="quick-search">
                    <div class="row">
                        <div class="col-md-6">
                            <input type="text" class="form-control mb-2" id="lat" placeholder="Latitude" value="51.5074">
                        </div>
                        <div class="col-md-6">
                            <input type="text" class="form-control mb-2" id="lng" placeholder="Longitude" value="-0.1278">
                        </div>
                    </div>
                    <input type="month" class="form-control mb-2" id="date" value="2024-01">
                    <button type="submit" class="btn btn-primary w-100">Search Crimes</button>
                </form>
                <div id="results" class="mt-3"></div>
            </div>
        </div>
    </div>
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5><i class="fas fa-info-circle"></i> About</h5>
            </div>
            <div class="card-body">
                <p>This application provides easy access to official UK police data including:</p>
                <ul>
                    <li>Police force information</li>
                    <li>Street-level crime data</li>
                    <li>Neighbourhood policing</li>
                    <li>Stop and search records</li>
                </ul>
                <p class="mb-0">All data is sourced from the official Police UK API.</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
document.getElementById('quick-search').addEventListener('submit', function(e) {
    e.preventDefault();
    const lat = document.getElementById('lat').value;
    const lng = document.getElementById('lng').value;
    const date = document.getElementById('date').value;
    
    fetch(`/api/crimes/street?lat=${lat}&lng=${lng}&date=${date}`)
        .then(r => r.json())
        .then(crimes => {
            const results = document.getElementById('results');
            if (crimes.length > 0) {
                results.innerHTML = `<div class="alert alert-success">Found ${crimes.length} crimes</div>`;
            } else {
                results.innerHTML = '<div class="alert alert-warning">No crimes found</div>';
            }
        });
});
</script>
{% endblock %}''')
    
    # Create forces.html
    create_file('templates/forces.html', '''{% extends "base.html" %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h1><i class="fas fa-building"></i> Police Forces</h1>
        <p class="lead">Explore police forces across the UK</p>
    </div>
</div>

<div class="row mt-4">
    <div class="col-12">
        <div class="card">
            <div class="card-body">
                <div id="forces-container" class="row">
                    <div class="col-12 text-center">
                        <div class="spinner-border" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
fetch('/api/forces')
    .then(r => r.json())
    .then(forces => {
        const container = document.getElementById('forces-container');
        if (forces.length > 0) {
            container.innerHTML = forces.map(force => `
                <div class="col-md-4 mb-3">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title">${force.name}</h5>
                            <button class="btn btn-primary btn-sm" onclick="viewForce('${force.id}')">
                                View Details
                            </button>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<div class="alert alert-warning">No forces data available.</div>';
        }
    });

function viewForce(forceId) {
    fetch(`/api/force/${forceId}`)
        .then(r => r.json())
        .then(force => {
            alert(`Force: ${force.name}\\nWebsite: ${force.url || 'N/A'}\\nTel: ${force.telephone || 'N/A'}`);
        });
}
</script>
{% endblock %}''')
    
    # Create crimes.html
    create_file('templates/crimes.html', '''{% extends "base.html" %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h1><i class="fas fa-exclamation-triangle"></i> Crime Data</h1>
        <p class="lead">Search for street-level crimes</p>
    </div>
</div>

<div class="row mt-4">
    <div class="col-md-4">
        <div class="card">
            <div class="card-body">
                <form id="crime-search">
                    <div class="mb-3">
                        <label>Latitude</label>
                        <input type="text" class="form-control" id="lat" value="51.5074">
                    </div>
                    <div class="mb-3">
                        <label>Longitude</label>
                        <input type="text" class="form-control" id="lng" value="-0.1278">
                    </div>
                    <div class="mb-3">
                        <label>Date (YYYY-MM)</label>
                        <input type="month" class="form-control" id="date" value="2024-01">
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Search Crimes</button>
                </form>
            </div>
        </div>
    </div>
    <div class="col-md-8">
        <div class="card">
            <div class="card-body">
                <div id="crime-results">
                    <p class="text-muted">Enter search criteria to find crimes</p>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
document.getElementById('crime-search').addEventListener('submit', function(e) {
    e.preventDefault();
    const lat = document.getElementById('lat').value;
    const lng = document.getElementById('lng').value;
    const date = document.getElementById('date').value;
    const results = document.getElementById('crime-results');
    
    results.innerHTML = '<div class="text-center"><div class="spinner-border"></div></div>';
    
    fetch(`/api/crimes/street?lat=${lat}&lng=${lng}&date=${date}`)
        .then(r => r.json())
        .then(crimes => {
            if (crimes.length > 0) {
                results.innerHTML = `
                    <div class="alert alert-success">Found ${crimes.length} crimes</div>
                    <div class="small">
                        ${crimes.slice(0, 10).map(crime => `
                            <div class="border-start border-primary ps-2 mb-2">
                                <strong>${crime.category}</strong><br>
                                <small>${crime.location.street.name}</small>
                            </div>
                        `).join('')}
                    </div>
                `;
            } else {
                results.innerHTML = '<div class="alert alert-warning">No crimes found</div>';
            }
        });
});
</script>
{% endblock %}''')
    
    # Create placeholder pages
    create_file('templates/neighbourhoods.html', '''{% extends "base.html" %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h1><i class="fas fa-users"></i> Neighbourhood Policing</h1>
        <p class="lead">Local policing teams and information</p>
        <div class="alert alert-info">
            <h4>Coming Soon</h4>
            <p>Neighbourhood policing data will be available in the next update.</p>
        </div>
    </div>
</div>
{% endblock %}''')
    
    create_file('templates/stop_search.html', '''{% extends "base.html" %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h1><i class="fas fa-search"></i> Stop & Search</h1>
        <p class="lead">Stop and search records and statistics</p>
        <div class="alert alert-info">
            <h4>Coming Soon</h4>
            <p>Stop and search data will be available in the next update.</p>
        </div>
    </div>
</div>
{% endblock %}''')
    
    create_file('templates/analytics.html', '''{% extends "base.html" %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h1><i class="fas fa-chart-bar"></i> Analytics</h1>
        <p class="lead">Data analysis and visualization</p>
        <div class="alert alert-info">
            <h4>Coming Soon</h4>
            <p>Advanced analytics will be available in the next update.</p>
        </div>
    </div>
</div>
{% endblock %}''')
    
    # Create CSS
    create_file('static/css/style.css', '''body {
    background-color: #f8f9fa;
}
.jumbotron {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.card {
    transition: transform 0.2s;
}
.card:hover {
    transform: translateY(-2px);
}''')
    
    # Create JavaScript
    create_file('static/js/app.js', '''console.log('Police Data UK App Loaded');''')
    
    print("\\n" + "=" * 50)
    print("✅ Application setup complete!")
    print("📁 Project structure created")
    print("📄 All files generated")
    print("\\n🚀 Starting the application...")
    print("🌐 The app will open in your browser automatically")
    print("=" * 50)
    
    return True

def run_application():
    """Run the Flask application"""
    try:
        # Open browser after a short delay
        import threading
        import time
        
        def open_browser():
            time.sleep(2)
            webbrowser.open('http://localhost:5000')
        
        browser_thread = threading.Thread(target=open_browser)
        browser_thread.daemon = True
        browser_thread.start()
        
        # Run the application
        from app import app
        app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
        
    except Exception as e:
        print(f"✗ Error starting application: {e}")
        print("\\nYou can still run the application manually with: python app.py")

if __name__ == '__main__':
    # Install requirements first
    if install_requirements():
        # Setup application
        if setup_application():
            # Run application
            run_application()
