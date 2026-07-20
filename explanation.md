# EV RouteWise: Complete Project Explanation

## What we are trying to build

EV RouteWise is an EV trip-planning and charging-station recommendation app.

The user problem is simple: when someone is driving an electric vehicle, the nearest charger is not always the best charger. A useful recommendation depends on the actual route, current battery, desired reserve, plug type, charger location, charger reliability, and detour.

So our goal is not just to show charging pins on a map. Our goal is to answer:

1. Can the driver reach the destination with their current battery?
2. If not, where should they stop before the battery drops below their reserve?
3. Does that charging place fit their plug type?
4. How far off the route is it?
5. How much charge should they add there?
6. If there are multiple route options, does the best charging stop change by route?

This makes the app more useful than a basic charger locator because it connects charging recommendations directly to the user's journey.

## How the app works at a high level

The app has four main layers:

1. Frontend web app
2. Flask API server
3. EV route recommendation engine
4. Charging-station dataset

The user opens the web app, enters trip and EV details, and clicks "Show my charging plan." The browser sends those details to the Flask backend. The backend gets road route geometry, calculates battery feasibility, searches the local station dataset, ranks usable charging stops, and sends the plan back to the browser. The browser then draws the route and recommended stops on a Leaflet map.

## User inputs we collect

The app collects only trip-planning inputs, not personal account data.

The main inputs are:

| Input | Why we need it |
|---|---|
| Starting point | To know where the trip begins |
| Destination | To calculate the road route |
| Battery capacity in kWh | To convert battery percentage into real usable energy |
| Current battery percentage | To know how much energy the EV has right now |
| Reserve battery percentage | To avoid planning the user down to 0 percent |
| Energy use in Wh/km | To estimate how much energy the route will consume |
| Plug types, such as CCS2 or Type 2 | To avoid recommending incompatible stations |
| AC/DC charging limit | To avoid unrealistic charging-time estimates |
| Maximum detour | To avoid sending users too far away from their route |
| Priority mode | To rank stations differently for speed, safety, or smaller detours |

These inputs are useful because EV route planning is a constraint problem. A charger is only useful if the driver can reach it safely, it is close enough to the route, and it can work with the vehicle.

## Data we collect about charging stations

The main dataset is `data/charging_stations.csv`.

Each row follows the app's charging-station schema:

| Field | Meaning |
|---|---|
| `station_id` | Stable internal station ID, based on the OSM element ID |
| `name` | Station name or fallback name |
| `latitude`, `longitude` | Exact map location |
| `address`, `city`, `state`, `country` | Place metadata when available |
| `operator_name` | Operator such as Tata Power, Shell, KSEB, ChargeZone, etc. |
| `network_name` | Charging network, if listed |
| `access_type` | Whether the station appears public, private, or unknown |
| `opening_hours` | Opening hours when available |
| `status` | Operational/closed status when available |
| `connector_type` | Plug type such as `ccs2`, `type2`, `chademo`, or `unknown` |
| `power_kw` | Charger power when available |
| `current_type` | AC/DC details when available |
| `connector_count` | Number of charging points when available |
| `payment_modes` | Payment tags when available |
| `amenities` | Nearby or station amenities when available |
| `source_name` | Data source, currently `openstreetmap` |
| `source_external_id` | Original OSM ID, such as `node/763446417` |
| `source_license` | Data license, currently `ODbL` |
| `confidence_score` | Our trust score for how complete the row is |
| `last_verified_at` | Timestamp when the CSV was generated |

Current dataset status:

- CSV rows: 537
- Unique OSM station IDs: 526
- Physical charging places loaded by the app: 509
- Source: OpenStreetMap India extract
- License: ODbL
- Rows with known connector type: 36
- Rows with unknown connector type: 501
- Rows with known power: 13

The high number of unknown connectors is not a code failure. It reflects the current quality of OpenStreetMap India charging-station tags. Many OSM stations are mapped as `amenity=charging_station` but do not include socket tags like `socket:type2`, `socket:type2_combo`, or `socket:chademo`.

## Where the charging data comes from

The charging-station data comes from OpenStreetMap through Geofabrik's India extract.

The pipeline is:

1. Download the India OSM PBF file from Geofabrik.
2. Use `osmium` to filter OSM elements where `amenity=charging_station`.
3. Export the filtered data to GeoJSON while preserving OSM IDs.
4. Parse the GeoJSON with `tools/parse_geojson.py`.
5. Write the normalized output to `data/charging_stations.csv`.
6. The Flask app loads that CSV at startup.

The important technical detail is that the GeoJSON export must preserve OSM IDs:

```bash
osmium export charging_stations.osm.pbf --add-unique-id type_id -o charging_stations.geojson -O
```

Without `--add-unique-id type_id`, the GeoJSON features do not include IDs. If the parser cannot read real IDs, every row can accidentally become `osm-unknown-0`. The app de-duplicates by `station_id`, so that mistake collapses hundreds of rows into one station. This was found and fixed.

## Why we use OpenStreetMap

We use OpenStreetMap because it is open, accessible, and suitable for a proof-of-concept dataset.

Benefits:

- Free to use under the ODbL license with attribution
- Covers all of India instead of only one city
- Can be downloaded in bulk instead of calling an API for every user request
- Works offline once converted to CSV
- Easy to refresh from Geofabrik snapshots
- Easy to inspect and improve

Tradeoffs:

- Connector details are often missing
- Charger power is often missing
- Live availability is not included
- Prices are not included
- Some stations may be outdated
- Operator names may be incomplete or inconsistent

So OpenStreetMap is a good starting dataset, but not enough for production-grade EV navigation by itself.

## How the backend works

The Flask backend is defined in `app.py`.

Main endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /` | Serves the planner UI |
| `GET /api/health` | Returns how many charging places are loaded |
| `GET /api/geocode?q=...` | Searches places in India using Nominatim |
| `POST /api/plan` | Builds the EV charging plan |

At startup, the app loads the CSV:

```python
stations = load_stations(STATION_FILE)
```

That means the recommendation engine can search stations from memory. For the current dataset size, this is fast and simple. In a production system, this should eventually move to PostGIS or another spatial database.

## How place search works

Place search is handled in `ev_route/services.py` using Nominatim, the OpenStreetMap geocoder.

When a user types a place name, the frontend calls:

```text
GET /api/geocode?q=...
```

The backend sends a request to Nominatim with:

- India country filter
- JSON response format
- A custom user agent
- A one-request-per-second rate limit
- LRU caching

This lets users search places like "India Gate, New Delhi" instead of manually entering coordinates.

## How routing works

Routing is handled in `ev_route/services.py` using OSRM.

When the user plans a trip, the backend asks OSRM for:

- Road distance
- Estimated drive duration
- Full route geometry
- Alternative routes when OSRM returns them

The app currently asks OSRM for up to three route options. For each route option, the backend runs the recommendation engine separately. If OSRM returns only one practical route, the UI tells the user that one route was found instead of showing fake alternatives.

If OSRM is unavailable, the backend falls back to an estimated straight-line route so the app can still respond, but the UI warns that the route is estimated.

## How battery calculation works

The core battery formula is:

```text
adjusted consumption = Wh/km × (1 + safety buffer)
trip energy = route distance × adjusted consumption
current energy = battery capacity × current SOC
reserve energy = battery capacity × reserve SOC
usable safe energy = current energy - reserve energy
safe range = usable safe energy / adjusted consumption
```

Example:

If the vehicle has:

- 40.5 kWh battery
- 19 percent current charge
- 15 percent reserve
- 145 Wh/km consumption
- 10 percent safety buffer

Then the app estimates how much energy is available before reserve and whether the trip can be completed without charging.

We do this because EV range shown on dashboards can be optimistic. A reserve and safety buffer make recommendations more conservative and safer.

## How stations are filtered

The recommendation engine is in `ev_route/engine.py`.

For every station, the engine checks:

1. Is it public or usable?
2. Is it operational?
3. Is it close enough to the route corridor?
4. Does it match the user's plug type?
5. If plug data is missing, has the user allowed "check plug" suggestions?
6. Can the driver reach it before dropping below reserve?
7. After charging there, can the driver continue to the destination?

Stations that fail these checks are rejected before ranking.

This matters because a charger 2 km away but behind the user's safe battery range is not useful. A charger with the wrong plug is also not useful. A charger far from the road might technically be nearby on a map but bad for the actual trip.

## How station distance from route is calculated

The engine projects each station onto the route geometry.

It estimates:

- How far the station is from the route line
- How far along the trip the station appears
- How much detour it may add
- What the battery percentage may be when the user reaches it

The app uses this route-aware projection instead of simple "nearest charger by straight-line distance." That is one of the most important parts of the project.

## How stations are ranked

After filtering, stations are scored. The score uses:

- Plug certainty
- Detour distance
- Station data confidence
- Listed charger power
- Battery margin on arrival
- Placement along the route

Different priority modes change the weights:

| Mode | What it prefers |
|---|---|
| Best overall | Balanced mix of plug fit, detour, confidence, power, and battery margin |
| Charge faster | Higher-power chargers |
| Stay near route | Smaller detours |
| More battery cushion | Stations reached with more battery remaining |

The UI does not show raw technical scores anymore because users mainly care about the action: where to stop, how much charge to add, and whether they need to check the plug.

## How charge recommendation works

For each recommended station, the engine estimates:

- Battery percentage on arrival
- Remaining route distance after the station
- Energy needed to finish while keeping reserve
- Suggested target SOC at the station
- Energy to add in kWh
- Charging time if station power is known

If station power is missing, the UI says "Check app" instead of pretending to know the speed. Internally, the engine uses a conservative assumption only for ranking, not as a user-facing fact.

## How the frontend works

The frontend is built with:

- `templates/index.html`
- `static/styles.css`
- `static/app.js`
- Leaflet for maps
- OpenStreetMap map tiles

The UI lets the user:

- Search origin/destination
- Pick points on the map
- Use browser geolocation for starting point
- Enter battery details
- Choose plug types
- Choose route priority
- Set max detour
- Allow or hide stations with missing plug details
- See the route, battery summary, and station recommendations
- Switch route options when alternatives exist

The frontend is intentionally written with user-centric wording. Instead of saying "candidate scored" or "unverified connector fallback," it says things like:

- "Best places to stop"
- "Fits your plug"
- "Check plug before relying on this stop"
- "Battery there"
- "Charger speed"

This is because the user is not trying to debug the algorithm. The user is trying to decide whether they can safely drive.

## Why the app shows "check plug"

Many OSM stations do not include connector tags. Hiding all of those stations would remove most of the India dataset. Showing all of them as fully compatible would be unsafe.

So the app uses a middle path:

- If connector data matches the user's plug, the station is shown as "Fits your plug."
- If connector data is missing and the user allows it, the station is shown as "Check plug before relying on this stop."
- If connector data is known and incompatible, the station is rejected.

This keeps the app useful while still being honest about data quality.

## Why we do not always show multiple routes

The app asks OSRM for route alternatives. But OSRM does not always return multiple practical routes. For short or obvious trips, there may be only one sensible route.

In that case, the UI says "One practical route found." It does not create fake alternatives just to look like Google Maps. When real alternatives are returned, the UI shows route cards and updates charging recommendations for the selected route.

## What happens when the app starts

Startup flow:

1. `app.py` creates the Flask app.
2. `load_stations()` reads `data/charging_stations.csv`.
3. Rows with the same station ID are grouped together.
4. Multiple connector rows for the same OSM element become one station with multiple plug types.
5. Very nearby same-name OSM entries are collapsed into one physical charging place.
6. The server exposes `/api/health`, which reports the loaded station count.

Right now `/api/health` should report:

```json
{"stations_loaded":509,"status":"ok"}
```

## Why station rows and loaded station count differ

The CSV has 537 rows, but the app loads 509 physical charging places.

That difference is expected because:

- Some stations have multiple connector rows.
- Some OSM stations are represented by multiple nearby nodes.
- The app merges same-name stations that are extremely close together.

Users should not see duplicate cards for what is effectively the same charging place.

## Important files in the repository

| File | Purpose |
|---|---|
| `app.py` | Flask API, route planning endpoint, health endpoint, security headers |
| `ev_route/engine.py` | Main recommendation logic, battery math, station filtering, scoring |
| `ev_route/services.py` | Nominatim geocoding and OSRM route fetching |
| `data/charging_stations.csv` | Normalized India charging-station dataset |
| `tools/parse_geojson.py` | Converts filtered OSM GeoJSON into app CSV |
| `tools/fetch_osm_data.py` | Alternative Overpass-based data fetcher |
| `tools/recommend_charging_stations.py` | CLI runner for offline experiments |
| `templates/index.html` | Main HTML structure |
| `static/app.js` | Browser logic, API calls, map drawing, route option switching |
| `static/styles.css` | UI styling and responsive layout |
| `tests/test_app.py` | API tests |
| `tests/test_engine.py` | Battery and recommendation engine tests |
| `render.yaml` | Render deployment blueprint |
| `Procfile` | Gunicorn start command |

## Why this approach is useful

This approach is useful because it combines three things that are usually separate:

1. Route planning
2. EV battery feasibility
3. Charging-station suitability

A normal map can show chargers. But this app answers a more practical question: "Given my vehicle and this route, which stop should I actually consider?"

That is the core value.

## Current limitations

The app is a strong proof of concept, but it is not yet a production EV navigation system.

Current limitations:

- No live charger availability
- No real-time pricing
- No charger occupancy status
- Many OSM stations have missing plug details
- Many OSM stations have missing power details
- No vehicle-specific charging curves
- No weather, traffic, elevation, or load modelling
- No multi-stop optimization for very long trips
- Public OSRM/Nominatim demo services are not meant for heavy production traffic
- Data freshness depends on regenerating the CSV from OSM

## What production would need next

For a production-grade version, the next upgrades should be:

1. Verified charger feeds from operators or OCPI sources
2. Live availability, price, and operational status
3. PostGIS or another spatial database for faster route corridor queries
4. Vehicle profiles with battery size, plug type, max charge rate, and charge curves
5. Weather/elevation/traffic-aware energy model
6. Multi-stop planning for long trips
7. Better station names, city/state enrichment, and operator normalization
8. Scheduled OSM refresh jobs with validation reports
9. Monitoring for route/geocode API failures
10. Authentication and saved vehicle profiles if needed

## In one sentence

EV RouteWise uses open map data, real road routes, and EV battery math to recommend charging stops that are reachable, relevant to the route, and honest about plug-data quality.
