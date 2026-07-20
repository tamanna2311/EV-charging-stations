from ev_route.engine import Point, Route, Station, recommend_stations


def payload(current_soc=30, connector="ccs2"):
    return {
        "origin": {"label": "Start", "latitude": 28.60, "longitude": 77.20},
        "destination": {"label": "End", "latitude": 28.60, "longitude": 77.50},
        "vehicle": {
            "battery_capacity_kwh": 40,
            "current_soc_percent": current_soc,
            "reserve_soc_percent": 10,
            "consumption_wh_per_km": 150,
            "safety_buffer_percent": 0,
            "connector_types": [connector],
            "max_ac_kw": 7.2,
            "max_dc_kw": 50,
        },
        "preferences": {
            "max_detour_km": 10,
            "maximum_results": 5,
            "minimum_station_confidence": 40,
            "allow_unverified_connectors": False,
            "mode": "balanced",
        },
        "route": {
            "points": [
                {"latitude": 28.60, "longitude": 77.20},
                {"latitude": 28.60, "longitude": 77.50},
            ],
            "distance_km": 30,
            "duration_minutes": 45,
            "source": "osrm",
        },
    }


def station(station_id, longitude, connectors=None, power=50):
    return Station(
        station_id=station_id,
        name=f"Station {station_id}",
        latitude=28.60,
        longitude=longitude,
        connector_types=set(connectors or {"ccs2"}),
        power_kw=power,
        confidence_score=80,
        access_type="public",
        status="available",
    )


def test_no_stop_is_needed_when_safe_energy_covers_route():
    result = recommend_stations(payload(current_soc=40), [station("one", 77.35)])
    assert result["decision"]["status"] == "no_stop_needed"
    assert result["battery"]["estimated_direct_arrival_soc_percent"] > 10


def test_unreachable_station_is_not_recommended():
    result = recommend_stations(payload(current_soc=15), [station("late", 77.44)])
    assert result["decision"]["status"] == "charge_before_departure"
    assert result["recommendations"] == []
    assert result["rejected_counts"]["unreachable_before_reserve"] == 1


def test_reachable_compatible_station_has_charge_target():
    result = recommend_stations(payload(current_soc=20), [station("early", 77.25)])
    match = result["recommendations"][0]
    assert result["decision"]["status"] == "stop_required"
    assert match["connector_verified"] is True
    assert match["arrival_soc_percent"] >= 10
    assert match["suggested_target_soc_percent"] > match["arrival_soc_percent"]
    assert match["can_finish_after_charge"] is True


def test_incompatible_connector_is_rejected():
    result = recommend_stations(payload(current_soc=20), [station("wrong", 77.25, {"chademo"})])
    assert result["recommendations"] == []
    assert result["rejected_counts"]["incompatible_connector"] == 1


def test_unverified_station_can_be_included_as_marked_fallback():
    trip = payload(current_soc=20)
    trip["preferences"]["allow_unverified_connectors"] = True
    result = recommend_stations(trip, [station("lead", 77.25, {"unknown"}, None)])
    assert result["recommendations"][0]["connector_verified"] is False
    assert "confirm" in result["recommendations"][0]["verification_note"].lower()
