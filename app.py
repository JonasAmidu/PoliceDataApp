import math
import re
from datetime import date as calendar_date

from flask import Flask, jsonify, render_template, request

from config import Config
from utils.police_api import PoliceDataAPI, UpstreamAPIError

app = Flask(__name__)
app.config.from_object(Config)
police_api = PoliceDataAPI()


@app.errorhandler(UpstreamAPIError)
def upstream_error(error):
    return jsonify(success=False, error=str(error)), 502


class InvalidQueryError(ValueError):
    pass


@app.errorhandler(InvalidQueryError)
def invalid_query(error):
    return jsonify(success=False, error=str(error)), 400


def query_filters(default_location=False, allow_force=False):
    """Validate shared location/month arguments before making upstream requests."""
    lat = request.args.get('lat', '').strip()
    lng = request.args.get('lng', '').strip()
    force = request.args.get('force', '').strip() if allow_force else ''
    date = request.args.get('date', '').strip() or None
    if date and not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', date):
        raise InvalidQueryError('Date must use YYYY-MM with a valid month.')
    if date:
        try:
            calendar_date.fromisoformat(date + '-01')
        except ValueError:
            raise InvalidQueryError('Date must use YYYY-MM with a valid year and month.') from None
    if force and not re.fullmatch(r'[a-z0-9-]+', force):
        raise InvalidQueryError('Invalid police force identifier.')
    if bool(lat) != bool(lng):
        raise InvalidQueryError('Both lat and lng are required together.')
    if lat and lng:
        try:
            latitude, longitude = float(lat), float(lng)
        except ValueError:
            raise InvalidQueryError('Coordinates must be numbers.') from None
        if not (math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise InvalidQueryError('Coordinates are outside the valid range.')
        if force:
            raise InvalidQueryError('Choose either coordinates or a police force.')
    elif not force:
        if default_location:
            lat, lng = '51.5074', '-0.1278'
        else:
            raise InvalidQueryError('Provide lat and lng, or a police force.')
    return lat or None, lng or None, date, force or None


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


@app.route('/api/geocode/postcode')
def api_geocode_postcode():
    query = request.args.get('q', '').strip()
    if not query:
        raise InvalidQueryError("Query parameter 'q' is required.")
    if len(query) > 16:
        raise InvalidQueryError('Postcode is too long.')
    result = police_api.geocode_postcode(query)
    if result is not None:
        return jsonify(success=True, result=result)
    return jsonify(success=False, error=f"Postcode '{query}' not found"), 404


@app.route('/api/geocode/search')
def api_geocode_search():
    query = request.args.get('q', '').strip()
    if len(query) > 200:
        raise InvalidQueryError('Place search must be 200 characters or fewer.')
    return jsonify(police_api.search_places(query))


@app.route('/api/forces')
def api_forces():
    return jsonify(police_api.get_forces())


@app.route('/api/force/<force_id>')
def api_force_details(force_id):
    return jsonify(police_api.get_force_details(force_id))


@app.route('/api/force/<force_id>/people')
def api_force_people(force_id):
    return jsonify(police_api.get_force_people(force_id))


@app.route('/api/crime-categories')
def api_crime_categories():
    return jsonify(police_api.get_crime_categories())


@app.route('/api/crimes/last-updated')
def api_crime_last_updated():
    return jsonify(police_api.get_last_updated())


@app.route('/api/crimes/street')
def api_street_crimes():
    lat, lng, date, _ = query_filters(default_location=True)
    return jsonify(police_api.get_street_level_crimes(lat, lng, date))


@app.route('/api/neighbourhoods/<force_id>')
def api_neighbourhoods(force_id):
    return jsonify(police_api.get_neighbourhoods(force_id))


@app.route('/api/neighbourhood/<force_id>/<neighbourhood_id>')
def api_neighbourhood_combined(force_id, neighbourhood_id):
    return jsonify(police_api.get_neighbourhood_combined(force_id, neighbourhood_id))


@app.route('/api/stop-search/street')
def api_stop_search_street():
    lat, lng, date, force = query_filters(allow_force=True)
    return jsonify(police_api.get_stops_street(lat, lng, date, force))


@app.route('/api/analytics/summary')
def api_analytics_summary():
    lat, lng, date, force = query_filters(default_location=True, allow_force=True)
    return jsonify(police_api.get_crime_summary(lat=lat, lng=lng, date=date, force=force))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
