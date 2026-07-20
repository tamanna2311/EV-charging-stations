"""Flask application for the EV RouteWise planner."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from ev_route.engine import InputError, load_stations, parse_point, recommend_stations
from ev_route.services import ExternalServiceError, geocode, route_options_or_fallback


ROOT = Path(__file__).resolve().parent
STATION_FILE = ROOT / "data" / "charging_stations.csv"
ASSET_VERSION = os.getenv("RENDER_GIT_COMMIT", "local")[:8]


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(JSON_SORT_KEYS=False, MAX_CONTENT_LENGTH=128 * 1024)
    if test_config:
        app.config.update(test_config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[method-assign]
    stations = load_stations(STATION_FILE)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self)"
        return response

    @app.get("/")
    def index():
        return render_template("index.html", station_count=len(stations), asset_version=ASSET_VERSION)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "stations_loaded": len(stations)})

    @app.get("/api/geocode")
    def geocode_location():
        query = request.args.get("q", "").strip()
        if len(query) < 3:
            return jsonify({"error": "Enter at least 3 characters to search for a location."}), 400
        try:
            return jsonify({"results": geocode(query)})
        except ExternalServiceError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.post("/api/plan")
    def plan_trip():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "A JSON trip request is required."}), 400
        try:
            origin = parse_point(payload.get("origin"), "origin")
            destination = parse_point(payload.get("destination"), "destination")
            supplied_route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
            if supplied_route.get("points") and supplied_route.get("distance_km"):
                route_options = [supplied_route]
            else:
                route_options = route_options_or_fallback(origin, destination)
            plans = [recommend_stations(payload, stations, route_data) for route_data in route_options]
            for index, plan in enumerate(plans):
                plan["route"]["option_index"] = index
                plan["route"]["label"] = "Fastest route" if index == 0 else f"Route {index + 1}"
            result = {**plans[0], "route_options": plans}
            return jsonify(result)
        except InputError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"error": "Trip request is too large."}), 413

    @app.errorhandler(500)
    def internal_error(_error):
        return jsonify({"error": "The planner encountered an unexpected error."}), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
