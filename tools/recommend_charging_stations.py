#!/usr/bin/env python3
"""Run the EV recommendation engine from a JSON file."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ev_route.engine import InputError, load_stations, recommend_stations  # noqa: E402


DEFAULT_INPUT = ROOT / "input" / "trip_input.json"
DEFAULT_OUTPUT = ROOT / "output" / "recommendation_output.json"
DEFAULT_STATIONS = ROOT / "data" / "charging_stations.csv"


def normalize_legacy_input(trip: dict) -> dict:
    """Keep the original prototype input compatible with the web engine."""

    preferences = trip.setdefault("preferences", {})
    if "allow_unverified_connectors" not in preferences:
        preferences["allow_unverified_connectors"] = bool(
            preferences.pop("allow_unknown_connectors_as_leads", True)
        )
    route = trip.setdefault("route", {})
    if "points" not in route and route.get("selected_route_points"):
        route["points"] = route.pop("selected_route_points")
    return trip


def main() -> int:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    try:
        trip = normalize_legacy_input(json.loads(input_path.read_text(encoding="utf-8")))
        result = recommend_stations(trip, load_stations(DEFAULT_STATIONS))
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print(f"Could not plan trip: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Decision: {result['decision']['title']}")
    print(f"Route: {result['route']['distance_km']} km")
    for index, station in enumerate(result["recommendations"], start=1):
        verification = "verified" if station["connector_verified"] else "verify connector"
        print(
            f"{index}. {station['name']} — score {station['score']}, "
            f"arrive {station['arrival_soc_percent']}%, {verification}"
        )
    print(f"Full result written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
