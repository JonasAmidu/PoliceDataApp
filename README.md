# PoliceDataApp

A Flask web interface for the [UK Police Data API](https://data.police.uk/docs/), with an interactive crime map, police force directory, neighbourhood profiles, stop-and-search records, and crime analytics.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000. Python 3.10 or newer is supported. The web pages load Bootstrap, Leaflet, MarkerCluster and Chart.js from public CDNs, so an internet connection is required. `setup.py` is the original project generator and rewrites application files; use the commands above to run this version.

The map uses standard OpenStreetMap tiles, with visible attribution and no API key. Normal browser caching is preserved; see the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

## Deploy on DigitalOcean App Platform

Deploy the repository as a Python web service, with these component settings:

- **Run Command:** `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 --worker-tmp-dir /dev/shm --access-logfile - --error-logfile - app:app`
- **HTTP Port:** `8080`
- **HTTP health-check path:** `/health`

The checked-in `Procfile` supplies the same startup configuration for buildpacks. An example App Platform spec is in [.do/app.yaml](.do/app.yaml); when updating an existing app, retain its existing resource settings. Saving this file in GitHub does not change an existing app's component settings automatically. Set the Run Command, HTTP Port, and health check in DigitalOcean, then rebuild and deploy the latest commit. Do not use `python setup.py` as the build or run command; it generates and overwrites application files.

Gunicorn is installed by `requirements.txt`, listens on all interfaces using DigitalOcean's `PORT`, and uses `/dev/shm` for worker temporary files as recommended by the [Python buildpack documentation](https://docs.digitalocean.com/products/app-platform/reference/buildpacks/python/). A single worker keeps the in-memory cache and place-search rate limiter shared between request threads. The server timeout allows upstream requests to finish.

`GET /health` returns `200` with `{"status":"ok"}` and never contacts the police or geocoding APIs. Use it for platform probes so an upstream outage cannot make a running app appear unhealthy. `python app.py` also respects `PORT` when set and defaults to port 5000 for local development, with debugging disabled.

To reproduce the platform startup locally:

```bash
PORT=8080 sh -c "$(sed 's/^web: //' Procfile)"
# In another terminal:
curl --fail http://localhost:8080/health
```

## Browser views

- **Dashboard:** search UK postcodes or place names, jump to a city, use your location, or select coordinates on the map. Incidents cluster as you zoom; category filters and the inspector show street names and recorded outcomes.
- **Crimes:** use the same postcode/place lookup and location-selection form as Analytics and Stop & Search, then search a reporting month and read street names and outcomes. Coordinates can also be entered directly.
- **Forces:** search the directory, open a force's contact details in a modal, then follow its neighbourhood link.
- **Neighbourhoods:** browse and filter local areas, then inspect the overview, policing team, priorities, and events. Partial upstream failures appear as warnings.
- **Stop & Search:** choose a location or police force and reporting month. View summaries, filter by search object, and page through records, including records without published coordinates.
- **Analytics:** choose a location and reporting month to view category/outcome charts and the corresponding tables.

Month selectors use the latest published crime month. A blank month lets the upstream API choose its latest data. Coverage and publication dates vary by force and dataset; an empty response means no published records for that query. Crime coordinates are anonymised and approximate.

## Application API

All endpoints use GET. Successful list endpoints return arrays; details and summary endpoints return objects.

| Endpoint | Description |
| --- | --- |
| `/api/forces` | List police forces |
| `/api/force/<force_id>` | Force details |
| `/api/force/<force_id>/people` | Force personnel |
| `/api/crime-categories` | Published crime categories |
| `/api/crimes/last-updated` | Latest crime publication date, `{ "date": "YYYY-MM-DD" }` |
| `/api/crimes/street?lat=&lng=&date=YYYY-MM` | Street crimes near coordinates |
| `/api/geocode/postcode?q=SW1A%201AA` | Postcode lookup, `{ "success": true, "result": { "lat": ..., "lng": ... } }` |
| `/api/geocode/search?q=Leicester` | UK place matches with `display_name`, `lat`, and `lng` |
| `/api/neighbourhoods/<force_id>` | Force neighbourhood list |
| `/api/neighbourhood/<force_id>/<id>` | Composite `details`, `team`, `priorities`, `events`, and `warnings` |
| `/api/stop-search/street?lat=&lng=&date=YYYY-MM` | Stop-and-search records near coordinates |
| `/api/stop-search/street?force=leicestershire&date=YYYY-MM` | Force stop-and-search records, including those without locations |
| `/api/analytics/summary?lat=&lng=&date=YYYY-MM` | Total, category and outcome counts/percentages |

`date` is optional. Crime and analytics queries default to central London when no scope is supplied. Stop-and-search requires either both coordinates or a force; combining a force and coordinates returns 400. Invalid arguments return 400, an unknown postcode returns 404, and upstream failures return 502 with `{ "success": false, "error": "..." }`.

For API consumers, the analytics endpoint also accepts `force`, but this uses the upstream [crimes without a location](https://data.police.uk/docs/method/crimes-no-location/) dataset. Its `scope: "unmapped-crimes-only"` identifies that subset; it is not the total crime count for a force. The dashboard uses local street-level summaries.

## Caching and geocoding

Successful upstream responses, including empty lists, are cached in memory for 600 seconds by default, with at most 1,024 entries. Concurrent police-data queries share cached results. A 429 response receives one bounded retry; failed requests are not cached. Caching reduces repeated requests but cannot guarantee that upstream services will never rate-limit the app.

Postcodes use [Postcodes.io](https://postcodes.io/); place searches use [Nominatim](https://nominatim.org/) and are submitted explicitly, with OpenStreetMap attribution. Nominatim requests are cached and limited to one per second within the application process. For a deployment with multiple workers, coordinate rate limiting across processes or use a suitable geocoding provider. Set `NOMINATIM_SEARCH_URL` to switch to a compatible search service. Follow the provider's [usage policy](https://operations.osmfoundation.org/policies/nominatim/).

## Verification

Backend and JavaScript regression checks run without upstream network access:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/deployment_smoke.py
node --test tests/test_home_map.js tests/test_subpages.js
```

The deployment smoke check starts Gunicorn and the Python entrypoint on assigned ports and probes `/health` and `/`; it requires permission to bind local sockets. Node.js 22 or newer is required for the JavaScript tests. In restricted environments that prevent test subprocesses, add `--experimental-test-isolation=none` to the Node command.

Run the combined Chromium browser checks with real Bootstrap, Leaflet, MarkerCluster and Chart.js:

```bash
pip install -r requirements-dev.txt
python -m playwright install --with-deps chromium
python tests/browser_smoke.py
```

The browser suite starts its own Flask server and replaces only upstream HTTP transport with fixed responses. It exercises search, map clustering and filters, inspector escaping, force-to-neighbourhood navigation, profile tabs, stop-search pagination and force queries, analytics charts, empty/error states, and mobile navigation. CDN assets are downloaded once into a temporary cache; tile images are replaced with a fixed image. `POLICE_BROWSER_ASSET_DIR` overrides that cache location; `PLAYWRIGHT_CHROMIUM_EXECUTABLE` selects an existing Chromium executable. The browser checks do not establish current availability of public API or tile servers.

GitHub Actions runs backend tests on Python 3.10–3.12, the JavaScript regression tests, and the Chromium integration suite.

## Structure

```text
app.py                  Flask page and API routes
utils/police_api.py      Cached upstream client, geocoding and aggregation
config.py               Flask configuration
templates/              Jinja views and shared query form
static/                 CSS and browser scripts
tests/                  Backend, JavaScript and browser regression checks
```

Author: [Jonas Amidu](https://github.com/JonasAmidu). MIT License.
