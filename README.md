# EV RouteWise
https://ev-charging-stations-un5k.onrender.com/
EV RouteWise is a route-aware charging recommendation app for electric-vehicle trips. It answers three practical questions:

1. Can the vehicle complete the selected road route while keeping the driver's battery reserve?
2. If not, which compatible charging stations are reachable before that reserve is used?
3. At the best stop, how much energy should the driver add and roughly how long might that take?

The repository includes a responsive Flask web app, a reusable Python recommendation engine, a JSON CLI, tests, a Render Blueprint, and an OpenStreetMap-derived India charging-station seed.

## Why this is implementable

The problem can be modelled with ordinary route, battery and charger data:

```text
adjusted consumption = rated Wh/km × (1 + driving buffer)
trip energy = road distance × adjusted consumption
safe battery = current battery energy − reserve energy
safe range = safe battery ÷ adjusted consumption
```

A station becomes a recommendation candidate only when it is near the selected route, publicly accessible, connector-compatible (or explicitly marked as an unverified fallback), and reachable before the reserve is consumed. Candidates are scored by connector certainty, detour, station-data confidence, charging power, battery margin on arrival and placement on the route.

## Inputs the app needs

| Input | Why it matters | Source in a production app |
|---|---|---|
| Origin and destination | Builds the road route | User search, map tap or device location |
| Route geometry, distance and duration | Finds chargers along the actual roads | OSRM, Mapbox, Google Routes, HERE, or mobile map SDK |
| Battery capacity (kWh) | Converts percentage into usable energy | Vehicle profile / OEM API / user |
| Current state of charge (%) | Determines current usable energy | Vehicle API or dashboard input |
| Desired reserve (%) | Prevents planning down to 0% | User preference, typically 10–20% |
| Consumption (Wh/km) | Estimates route energy | Vehicle profile, recent telemetry or user |
| Driving-condition buffer (%) | Covers traffic, weather, elevation and AC | Model/telemetry; 10% demo default |
| Connector types | Removes incompatible stations | Vehicle profile |
| Max AC/DC rate | Makes charging-time estimates realistic | Vehicle profile |
| Maximum detour and priority | Personalises ranking | User preference |
| Station location, connector, power and access | Defines possible stops | CPO feeds, OCPI, verified database |
| Live status, price and availability | Makes recommendations operational | Charging-network/CPO APIs |

## What is working now

- Place search in India and click-to-select map locations.
- Real road distance, duration and geometry through the public OSRM demo endpoint.
- Automatic straight-line fallback if live routing is unavailable.
- Battery feasibility using current SOC, reserve, efficiency and a driving buffer.
- Reachability filtering: a stop after the safe-range point is rejected.
- Connector compatibility and clearly labelled unverified fallbacks.
- Balanced, fastest, shortest-detour and safest ranking modes.
- Arrival SOC, target SOC, energy-to-add and charging-time estimates.
- Responsive Leaflet map, route line and ranked station markers.
- Health endpoint and Render deployment configuration.
- CLI support for backend integration and offline experiments.

## Local setup

Python 3.11+ is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
flask --app app run --debug
```

Open <http://127.0.0.1:5000>.

Run the checks:

```bash
pytest -q
python tools/recommend_charging_stations.py
```

The CLI reads `input/trip_input.json` and writes `output/recommendation_output.json`.

## API

### `POST /api/plan`

Minimal request:

```json
{
  "origin": {"label": "India Gate", "latitude": 28.6129, "longitude": 77.2295},
  "destination": {"label": "Qutub Minar", "latitude": 28.5245, "longitude": 77.1855},
  "vehicle": {
    "battery_capacity_kwh": 40.5,
    "current_soc_percent": 20,
    "reserve_soc_percent": 15,
    "consumption_wh_per_km": 145,
    "connector_types": ["ccs2", "type2"]
  },
  "preferences": {"mode": "balanced", "max_detour_km": 10}
}
```

The server obtains the road route and returns the battery summary, decision, route geometry and ranked recommendations. A trusted client can instead supply `route.points`, `route.distance_km` and `route.duration_minutes`.

Other endpoints:

- `GET /api/geocode?q=...` — cached, rate-limited Nominatim place search.
- `GET /api/health` — Render health check.

## Deploy to Render

The included `render.yaml` follows Render's Python web-service Blueprint format.

1. Push this repository to GitHub.
2. In Render choose **New → Blueprint**.
3. Connect the repository and apply the `ev-routewise` service.
4. Render installs `requirements.txt`, runs Gunicorn and checks `/api/health`.

For sustained traffic, replace the public demo services with a commercial route/geocoding provider or self-hosted OSRM and Nominatim. Configure those endpoints with `OSRM_URL` and `NOMINATIM_URL`.

## Production architecture

```text
Web/mobile client
    ├── route + EV inputs
    ▼
Planner API (this Flask app / future service)
    ├── routing and elevation provider
    ├── energy model using weather + vehicle telemetry
    └── station query in PostgreSQL/PostGIS
            ├── verified station catalogue
            └── OCPI/CPO live availability and prices
```

The seed CSV currently contains 537 OpenStreetMap-derived charging-station rows across India. The app collapses nearby duplicate rows and multi-connector rows into 509 physical charging places at load time. Many OpenStreetMap entries still have missing plug, power, operator, and live-availability details, so this is useful for the proof of concept but not a complete production catalogue. Before real-world launch, ingest verified operator data, store route/station geometry in PostGIS, add live availability and pricing, model elevation/weather, and support multi-stop optimisation for trips longer than one full-charge range.

## Data and usage notes

- Map tiles and seed station data: © OpenStreetMap contributors, ODbL.
- Geocoding uses the public Nominatim endpoint with caching, an identifying user agent and a one-request-per-second application limit.
- Routing uses the public OSRM demo endpoint and gracefully falls back to an estimate.
- Results are estimates and should never replace checking the charging operator's live app.

## License

Application code is available under the [MIT License](LICENSE). OpenStreetMap-derived data remains subject to the ODbL and attribution requirements recorded in the CSV.
