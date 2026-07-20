"""Small clients for public OpenStreetMap geocoding and OSRM routing."""

from __future__ import annotations

import os
import threading
import time
from functools import lru_cache
from typing import Any

import requests

from .engine import Point


USER_AGENT = os.getenv(
    "EV_PLANNER_USER_AGENT",
    "EVRouteWise/1.0 (+https://github.com/tamanna2311/EV-charging-stations)",
)
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
_geocode_lock = threading.Lock()
_last_geocode_request = 0.0


class ExternalServiceError(RuntimeError):
    """Raised when a map provider is unavailable or returns unusable data."""


def _respect_nominatim_rate_limit() -> None:
    global _last_geocode_request
    with _geocode_lock:
        wait_for = 1.05 - (time.monotonic() - _last_geocode_request)
        if wait_for > 0:
            time.sleep(wait_for)
        _last_geocode_request = time.monotonic()


@lru_cache(maxsize=256)
def geocode(query: str) -> list[dict[str, Any]]:
    cleaned = " ".join(query.split())
    if len(cleaned) < 3:
        return []
    _respect_nominatim_rate_limit()
    try:
        response = _session.get(
            f"{NOMINATIM_URL.rstrip('/')}/search",
            params={"q": cleaned, "format": "jsonv2", "limit": 5, "countrycodes": "in", "addressdetails": 1},
            timeout=10,
        )
        response.raise_for_status()
        raw_results = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ExternalServiceError("Location search is temporarily unavailable") from exc

    results = []
    for item in raw_results:
        try:
            results.append(
                {
                    "label": item["display_name"],
                    "latitude": float(item["lat"]),
                    "longitude": float(item["lon"]),
                    "type": item.get("type", "place"),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return results


@lru_cache(maxsize=256)
def road_route(origin_lat: float, origin_lon: float, destination_lat: float, destination_lon: float) -> dict[str, Any]:
    coordinates = f"{origin_lon:.6f},{origin_lat:.6f};{destination_lon:.6f},{destination_lat:.6f}"
    try:
        response = _session.get(
            f"{OSRM_URL.rstrip('/')}/route/v1/driving/{coordinates}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=14,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            raise ExternalServiceError("No drivable route was found between these locations")
        best = data["routes"][0]
        coordinates = best["geometry"]["coordinates"]
        points = [
            {"latitude": float(latitude), "longitude": float(longitude), "label": ""}
            for longitude, latitude in coordinates
        ]
        return {
            "points": points,
            "distance_km": float(best["distance"]) / 1000,
            "duration_minutes": float(best["duration"]) / 60,
            "source": "osrm",
        }
    except ExternalServiceError:
        raise
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise ExternalServiceError("Live road routing is temporarily unavailable") from exc


def route_or_fallback(origin: Point, destination: Point) -> dict[str, Any]:
    try:
        return road_route(origin.latitude, origin.longitude, destination.latitude, destination.longitude)
    except ExternalServiceError:
        return {"points": [], "distance_km": None, "duration_minutes": None, "source": "estimated"}
