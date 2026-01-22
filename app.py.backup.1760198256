from flask import Flask, render_template, request, jsonify
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
