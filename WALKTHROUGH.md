# Technical walkthrough

## Request flow

1. The browser resolves the origin and destination through `/api/geocode` or records coordinates from a map click.
2. `/api/plan` fetches full road geometry, distance and duration from OSRM.
3. The engine calculates route energy with a configurable driving-condition buffer.
4. It subtracts the user's reserve from current battery energy to find safe range.
5. Each station is projected onto the road geometry to estimate route progress and deviation.
6. Stations outside the corridor, closed/private, incompatible or unreachable before reserve are rejected.
7. Remaining candidates are scored and returned with arrival SOC, charge target and charging-time estimate.
8. The browser draws the route and numbered recommendations on Leaflet.

## Main files

- `app.py` — FastAPI routes, OpenAPI docs and production entry point.
- `ev_route/engine.py` — validation, energy model, geospatial filtering and ranking.
- `ev_route/services.py` — cached geocoding and road-routing clients.
- `templates/index.html` — accessible planner markup.
- `static/app.js` — map interaction, API calls and result rendering.
- `static/styles.css` — responsive application design.
- `tests/` — engine and API checks.
- `render.yaml` — Render Blueprint.

## Current model boundary

This release recommends the best single reachable stop and identifies when that stop cannot complete the route on one full charge. A production long-distance release should model the trip as a graph and use label-setting/A* optimisation across multiple charging stops, accounting for each vehicle's charging curve and live station reliability.
