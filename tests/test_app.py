from app import create_app


def test_health_endpoint_reports_loaded_station_count():
    client = create_app({"TESTING": True}).test_client()
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["stations_loaded"] > 0


def test_plan_endpoint_accepts_supplied_route_without_external_call():
    client = create_app({"TESTING": True}).test_client()
    response = client.post(
        "/api/plan",
        json={
            "origin": {"latitude": 28.6129, "longitude": 77.2295, "label": "India Gate"},
            "destination": {"latitude": 28.5245, "longitude": 77.1855, "label": "Qutub Minar"},
            "vehicle": {
                "battery_capacity_kwh": 40.5,
                "current_soc_percent": 25,
                "reserve_soc_percent": 15,
                "consumption_wh_per_km": 145,
                "connector_types": ["ccs2", "type2"],
            },
            "preferences": {"allow_unverified_connectors": True},
            "route": {
                "points": [
                    {"latitude": 28.6129, "longitude": 77.2295},
                    {"latitude": 28.5245, "longitude": 77.1855},
                ],
                "distance_km": 13,
                "duration_minutes": 35,
                "source": "osrm",
            },
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["route"]["distance_km"] == 13
    assert data["station_count"] > 0


def test_plan_endpoint_returns_useful_validation_error():
    client = create_app({"TESTING": True}).test_client()
    response = client.post("/api/plan", json={"origin": {}})
    assert response.status_code == 400
    assert "latitude" in response.get_json()["error"]
