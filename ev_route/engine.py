"""Battery-aware EV charging-station recommendation engine.

The engine is deliberately independent from Flask so it can also be reused by a
mobile backend, a scheduled job, or the command-line helper.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


EARTH_RADIUS_KM = 6371.0088
KNOWN_CONNECTORS = {"ccs2", "type2", "chademo", "gbt", "tesla", "bharat_ac_001", "bharat_dc_001"}


class InputError(ValueError):
    """Raised when a trip cannot be planned from the supplied input."""


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"latitude": self.latitude, "longitude": self.longitude, "label": self.label}


@dataclass
class Station:
    station_id: str
    name: str
    latitude: float
    longitude: float
    city: str = ""
    operator_name: str = ""
    access_type: str = "public"
    status: str = "unknown"
    connector_types: set[str] = field(default_factory=set)
    power_kw: float | None = None
    confidence_score: float = 0
    source_name: str = ""
    source_external_id: str = ""
    last_verified_at: str = ""


@dataclass(frozen=True)
class Route:
    points: tuple[Point, ...]
    distance_km: float
    duration_minutes: float | None
    source: str


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise InputError(f"{name} must be between {minimum:g} and {maximum:g}")
    return parsed


def parse_point(raw: Any, name: str) -> Point:
    if not isinstance(raw, dict):
        raise InputError(f"{name} is required")
    latitude = _number(raw.get("latitude"), f"{name} latitude", -90, 90)
    longitude = _number(raw.get("longitude"), f"{name} longitude", -180, 180)
    return Point(latitude, longitude, str(raw.get("label") or name.title()))


def haversine_km(a: Point, b: Point) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _project_to_segment(point: Point, start: Point, end: Point) -> tuple[float, float]:
    """Return perpendicular distance and clamped progress for a short segment."""

    mean_lat = math.radians((start.latitude + end.latitude + point.latitude) / 3)

    def xy(item: Point) -> tuple[float, float]:
        return (
            EARTH_RADIUS_KM * math.radians(item.longitude) * math.cos(mean_lat),
            EARTH_RADIUS_KM * math.radians(item.latitude),
        )

    x1, y1 = xy(start)
    x2, y2 = xy(end)
    xp, yp = xy(point)
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return haversine_km(point, start), 0.0
    ratio = max(0.0, min(1.0, ((xp - x1) * dx + (yp - y1) * dy) / length_sq))
    closest_x, closest_y = x1 + ratio * dx, y1 + ratio * dy
    return math.hypot(xp - closest_x, yp - closest_y), ratio


def _cumulative_distances(points: tuple[Point, ...]) -> tuple[list[float], float]:
    cumulative = [0.0]
    for start, end in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + haversine_km(start, end))
    return cumulative, cumulative[-1]


def project_to_route(point: Point, route: Route) -> tuple[float, float, float]:
    """Return one-way corridor distance, progress ratio, and route km at projection."""

    cumulative, geometry_length = _cumulative_distances(route.points)
    best: tuple[float, float] | None = None
    for index, (start, end) in enumerate(zip(route.points, route.points[1:])):
        distance, segment_ratio = _project_to_segment(point, start, end)
        segment_length = cumulative[index + 1] - cumulative[index]
        geometry_km = cumulative[index] + segment_length * segment_ratio
        if best is None or distance < best[0]:
            best = (distance, geometry_km)
    if best is None:
        return haversine_km(point, route.points[0]), 0.0, 0.0
    ratio = best[1] / geometry_length if geometry_length else 0.0
    route_km = route.distance_km * ratio
    return best[0], ratio, route_km


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def load_stations(path: Path) -> list[Station]:
    """Load and de-duplicate station rows, combining connector variants."""

    grouped: dict[str, Station] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                station_id = row["station_id"].strip()
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            connector = (row.get("connector_type") or "unknown").strip().lower()
            if station_id not in grouped:
                grouped[station_id] = Station(
                    station_id=station_id,
                    name=(row.get("name") or "EV charging station").strip(),
                    latitude=latitude,
                    longitude=longitude,
                    city=(row.get("city") or "").strip(),
                    operator_name=(row.get("operator_name") or "").strip(),
                    access_type=(row.get("access_type") or "public").strip().lower(),
                    status=(row.get("status") or "unknown").strip().lower(),
                    confidence_score=_safe_float(row.get("confidence_score")) or 0,
                    source_name=(row.get("source_name") or "").strip(),
                    source_external_id=(row.get("source_external_id") or "").strip(),
                    last_verified_at=(row.get("last_verified_at") or "").strip(),
                )
            station = grouped[station_id]
            station.connector_types.add(connector)
            power = _safe_float(row.get("power_kw"))
            if power is not None and (station.power_kw is None or power > station.power_kw):
                station.power_kw = power
    # OpenStreetMap sometimes models each connector/parking bay as a separate
    # node. Collapse same-name nodes within roughly 10 metres so users do not
    # see duplicate recommendations for one physical charging site.
    sites: dict[tuple[str, float, float], Station] = {}
    for station in grouped.values():
        site_key = (station.name.casefold(), round(station.latitude, 4), round(station.longitude, 4))
        if site_key not in sites:
            sites[site_key] = station
            continue
        existing = sites[site_key]
        existing.connector_types.update(station.connector_types)
        existing.confidence_score = max(existing.confidence_score, station.confidence_score)
        if station.power_kw is not None and (existing.power_kw is None or station.power_kw > existing.power_kw):
            existing.power_kw = station.power_kw
    return list(sites.values())


def build_route(
    origin: Point,
    destination: Point,
    route_points: Iterable[dict[str, Any]] | None = None,
    distance_km: float | None = None,
    duration_minutes: float | None = None,
    source: str = "estimated",
) -> Route:
    points = tuple(parse_point(item, "route point") for item in (route_points or []))
    if len(points) < 2:
        points = (origin, destination)
    if distance_km is None:
        distance_km = haversine_km(origin, destination) * 1.25
        source = "estimated"
    parsed_distance = _number(distance_km, "route distance", 0.05, 10000)
    parsed_duration = None
    if duration_minutes is not None:
        parsed_duration = _number(duration_minutes, "route duration", 0.1, 20000)
    return Route(points, parsed_distance, parsed_duration, source)


def _display_connector(connector: str) -> str:
    labels = {
        "ccs2": "CCS2",
        "type2": "Type 2",
        "chademo": "CHAdeMO",
        "gbt": "GB/T",
        "tesla": "Tesla",
        "bharat_ac_001": "Bharat AC-001",
        "bharat_dc_001": "Bharat DC-001",
        "unknown": "Unverified",
    }
    return labels.get(connector, connector.upper())


def _station_reasons(
    verified_match: bool,
    corridor_distance: float,
    arrival_soc: float,
    reserve_soc: float,
    power_kw: float | None,
    confidence: float,
) -> list[str]:
    reasons = ["Verified compatible connector" if verified_match else "Connector requires verification"]
    if corridor_distance <= 1:
        reasons.append("Less than 1 km from the route")
    elif corridor_distance <= 3:
        reasons.append("Low route deviation")
    if arrival_soc >= reserve_soc + 5:
        reasons.append("Comfortable arrival battery")
    else:
        reasons.append("Reachable before reserve is used")
    if power_kw and power_kw >= 25:
        reasons.append("DC fast-charging power listed")
    if confidence >= 60:
        reasons.append("Higher-confidence station data")
    return reasons


def recommend_stations(payload: dict[str, Any], stations: list[Station], route_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Plan a trip and rank feasible charging stops.

    `route_data` may contain a real route returned by OSRM. If omitted, the
    payload may include route geometry; otherwise a conservative estimate is used.
    """

    origin = parse_point(payload.get("origin"), "origin")
    destination = parse_point(payload.get("destination"), "destination")
    vehicle = payload.get("vehicle") if isinstance(payload.get("vehicle"), dict) else {}
    preferences = payload.get("preferences") if isinstance(payload.get("preferences"), dict) else {}

    capacity = _number(vehicle.get("battery_capacity_kwh"), "battery capacity", 5, 250)
    current_soc = _number(vehicle.get("current_soc_percent"), "current battery", 0, 100)
    reserve_soc = _number(vehicle.get("reserve_soc_percent", 15), "reserve battery", 0, 50)
    consumption = _number(vehicle.get("consumption_wh_per_km"), "energy consumption", 60, 500)
    safety_buffer = _number(vehicle.get("safety_buffer_percent", 10), "safety buffer", 0, 40)
    max_ac_kw = _number(vehicle.get("max_ac_kw", 7.2), "maximum AC rate", 1, 50)
    max_dc_kw = _number(vehicle.get("max_dc_kw", 50), "maximum DC rate", 1, 500)
    if reserve_soc >= 100:
        raise InputError("reserve battery must be below 100%")

    raw_connectors = vehicle.get("connector_types") or []
    connectors = {str(item).strip().lower() for item in raw_connectors if str(item).strip()}
    if not connectors:
        raise InputError("select at least one connector supported by the vehicle")

    max_detour_km = _number(preferences.get("max_detour_km", 8), "maximum detour", 0.5, 50)
    maximum_results = int(_number(preferences.get("maximum_results", 5), "maximum results", 1, 10))
    minimum_confidence = _number(preferences.get("minimum_station_confidence", 40), "minimum confidence", 0, 100)
    allow_unverified = bool(preferences.get("allow_unverified_connectors", True))
    mode = str(preferences.get("mode", "balanced")).lower()
    if mode not in {"balanced", "fastest", "shortest_detour", "safest"}:
        raise InputError("preference mode is not supported")

    route_data = route_data or {}
    route_payload = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    route = build_route(
        origin,
        destination,
        route_data.get("points") or route_payload.get("points"),
        route_data.get("distance_km") or route_payload.get("distance_km"),
        route_data.get("duration_minutes") or route_payload.get("duration_minutes"),
        str(route_data.get("source") or route_payload.get("source") or "estimated"),
    )

    adjusted_consumption = consumption * (1 + safety_buffer / 100)
    usable_now_kwh = capacity * current_soc / 100
    reserve_kwh = capacity * reserve_soc / 100
    safe_available_kwh = max(0.0, usable_now_kwh - reserve_kwh)
    energy_needed_kwh = route.distance_km * adjusted_consumption / 1000
    direct_arrival_soc = max(0.0, (usable_now_kwh - energy_needed_kwh) / capacity * 100)
    charging_required = energy_needed_kwh > safe_available_kwh
    safe_range_km = safe_available_kwh * 1000 / adjusted_consumption
    energy_shortfall_kwh = max(0.0, energy_needed_kwh - safe_available_kwh)

    rejected = {
        "outside_route_corridor": 0,
        "incompatible_connector": 0,
        "unreachable_before_reserve": 0,
        "unverified_or_low_confidence": 0,
        "not_public_or_closed": 0,
    }
    candidates: list[dict[str, Any]] = []

    for station in stations:
        if station.access_type not in {"", "public", "public_paid"} or station.status in {"closed", "unavailable"}:
            rejected["not_public_or_closed"] += 1
            continue
        if station.confidence_score < minimum_confidence:
            rejected["unverified_or_low_confidence"] += 1
            continue

        station_point = Point(station.latitude, station.longitude, station.name)
        corridor_distance, progress, route_km = project_to_route(station_point, route)
        estimated_total_detour = corridor_distance * 2.4
        if estimated_total_detour > max_detour_km:
            rejected["outside_route_corridor"] += 1
            continue

        known_station_connectors = station.connector_types - {"unknown", ""}
        matching_connectors = connectors & known_station_connectors
        verified_match = bool(matching_connectors)
        unverified_candidate = not known_station_connectors and allow_unverified
        if not verified_match and not unverified_candidate:
            rejected["incompatible_connector"] += 1
            continue

        distance_to_station = route_km + corridor_distance * 1.2
        energy_to_station = distance_to_station * adjusted_consumption / 1000
        arrival_energy = usable_now_kwh - energy_to_station
        arrival_soc = arrival_energy / capacity * 100
        if arrival_soc + 0.05 < reserve_soc:
            rejected["unreachable_before_reserve"] += 1
            continue

        remaining_distance = max(0.0, route.distance_km - route_km) + corridor_distance * 1.2
        destination_energy_with_reserve = remaining_distance * adjusted_consumption / 1000 + reserve_kwh
        charge_needed = max(0.0, destination_energy_with_reserve - max(0.0, arrival_energy))
        target_energy = min(capacity, max(0.0, arrival_energy) + charge_needed)
        target_soc = target_energy / capacity * 100
        can_finish_after_charge = destination_energy_with_reserve <= capacity + 1e-6

        # Never present the vehicle's maximum rate as if it were a station fact.
        # Unknown-power sites get a conservative AC-rate assumption for ranking,
        # while their user-facing charge-time estimate stays unavailable.
        assumed_power = station.power_kw or min(max_ac_kw, 7.2)
        vehicle_limit = max_dc_kw if any(item in {"ccs2", "chademo", "gbt", "bharat_dc_001"} for item in matching_connectors) else max_ac_kw
        effective_power = max(1.0, min(assumed_power, vehicle_limit))
        charge_minutes = charge_needed / (effective_power * 0.90) * 60 if charge_needed else 0.0

        detour_score = max(0.0, 1 - estimated_total_detour / max_detour_km)
        connector_score = 1.0 if verified_match else 0.35
        confidence_score = station.confidence_score / 100
        power_score = min(effective_power / max(max_dc_kw, 1), 1.0)
        arrival_margin_score = min(max((arrival_soc - reserve_soc) / 15, 0.0), 1.0)
        ideal_progress = min(0.65, max(0.12, (safe_range_km / max(route.distance_km, 0.1)) * 0.72)) if charging_required else 0.75
        placement_score = max(0.0, 1 - abs(progress - ideal_progress))

        weights = {
            "balanced": (0.24, 0.20, 0.16, 0.13, 0.15, 0.12),
            "fastest": (0.23, 0.12, 0.13, 0.30, 0.12, 0.10),
            "shortest_detour": (0.22, 0.36, 0.13, 0.08, 0.11, 0.10),
            "safest": (0.24, 0.12, 0.21, 0.08, 0.25, 0.10),
        }[mode]
        score = 100 * sum(
            value * weight
            for value, weight in zip(
                (connector_score, detour_score, confidence_score, power_score, arrival_margin_score, placement_score),
                weights,
            )
        )
        if not can_finish_after_charge:
            score *= 0.75

        available_connectors = sorted(station.connector_types - {"", "unknown"}) or ["unknown"]
        candidates.append(
            {
                "station_id": station.station_id,
                "name": station.name,
                "operator_name": station.operator_name or "Operator not listed",
                "location": {"latitude": station.latitude, "longitude": station.longitude},
                "connectors": [_display_connector(item) for item in available_connectors],
                "matching_connectors": [_display_connector(item) for item in sorted(matching_connectors)],
                "connector_verified": verified_match,
                "power_kw": station.power_kw,
                "estimated_effective_power_kw": round(effective_power, 1),
                "route_progress_percent": round(progress * 100, 1),
                "distance_from_start_km": round(distance_to_station, 1),
                "route_deviation_km": round(corridor_distance, 1),
                "estimated_total_detour_km": round(estimated_total_detour, 1),
                "arrival_soc_percent": round(arrival_soc, 1),
                "suggested_target_soc_percent": round(min(100.0, target_soc), 1),
                "energy_to_add_kwh": round(charge_needed, 1),
                "estimated_charge_minutes": round(charge_minutes) if station.power_kw is not None else None,
                "can_finish_after_charge": can_finish_after_charge,
                "score": round(score, 1),
                "confidence_score": station.confidence_score,
                "reasons": _station_reasons(
                    verified_match, corridor_distance, arrival_soc, reserve_soc, station.power_kw, station.confidence_score
                ),
                "verification_note": (
                    "Connector is listed in the station data. Live availability still needs operator verification."
                    if verified_match
                    else "Connector type is missing in OpenStreetMap; confirm compatibility before relying on this stop."
                ),
                "source": {
                    "name": station.source_name,
                    "external_id": station.source_external_id,
                    "last_verified_at": station.last_verified_at,
                },
            }
        )

    candidates.sort(
        key=lambda item: (
            item["connector_verified"],
            item["can_finish_after_charge"],
            item["score"],
            -item["estimated_total_detour_km"],
        ),
        reverse=True,
    )
    recommendations = candidates[:maximum_results]

    warnings: list[str] = []
    if route.source != "osrm":
        warnings.append("Live road routing was unavailable, so distance and route geometry are estimated.")
    if any(not item["connector_verified"] for item in recommendations):
        warnings.append("Some fallback stations have unverified connector data; confirm in the operator app before departure.")
    if charging_required and not recommendations:
        warnings.append("No reachable compatible station was found within the selected detour. Start with more charge or widen the search.")
    if not charging_required:
        warnings.append("No charging stop is required; shown stations are optional backups.")

    decision = (
        "Charge before departure"
        if charging_required and not recommendations
        else "Charging stop required"
        if charging_required
        else "No charging stop needed"
    )
    return {
        "decision": {
            "status": "charge_before_departure" if charging_required and not recommendations else "stop_required" if charging_required else "no_stop_needed",
            "title": decision,
            "summary": (
                f"The trip needs about {energy_needed_kwh:.1f} kWh including the {safety_buffer:.0f}% driving buffer, "
                f"while {safe_available_kwh:.1f} kWh is available above your reserve."
            ),
        },
        "origin": origin.as_dict(),
        "destination": destination.as_dict(),
        "route": {
            "distance_km": round(route.distance_km, 1),
            "duration_minutes": round(route.duration_minutes) if route.duration_minutes else None,
            "source": route.source,
            "geometry": [[point.latitude, point.longitude] for point in route.points],
        },
        "battery": {
            "capacity_kwh": capacity,
            "current_soc_percent": current_soc,
            "reserve_soc_percent": reserve_soc,
            "adjusted_consumption_wh_per_km": round(adjusted_consumption),
            "energy_needed_kwh": round(energy_needed_kwh, 1),
            "safe_available_energy_kwh": round(safe_available_kwh, 1),
            "safe_range_km": round(safe_range_km, 1),
            "estimated_direct_arrival_soc_percent": round(direct_arrival_soc, 1),
            "energy_shortfall_kwh": round(energy_shortfall_kwh, 1),
        },
        "recommendations": recommendations,
        "candidate_count": len(candidates),
        "station_count": len(stations),
        "rejected_counts": rejected,
        "warnings": warnings,
        "assumptions": [
            "Energy use includes the selected driving-condition buffer.",
            "Route deviation and charging time are estimates, not live navigation or charger availability.",
            "Station data is an OpenStreetMap-derived seed and must be refreshed and verified for production use.",
        ],
    }
