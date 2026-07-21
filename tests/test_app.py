from app import create_app
from fastapi.testclient import TestClient


def test_health_endpoint_reports_loaded_station_count():
    client = TestClient(create_app({"TESTING": True}))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["stations_loaded"] > 0


def test_openapi_docs_are_available():
    client = TestClient(create_app({"TESTING": True}))
    docs_response = client.get("/docs")
    schema_response = client.get("/openapi.json")
    assert docs_response.status_code == 200
    assert schema_response.status_code == 200
    assert schema_response.json()["info"]["title"] == "EV RouteWise API"


def test_plan_endpoint_accepts_supplied_route_without_external_call():
    client = TestClient(create_app({"TESTING": True}))
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
    data = response.json()
    assert data["route"]["distance_km"] == 13
    assert len(data["route_options"]) == 1
    assert data["route_options"][0]["route"]["label"] == "Fastest route"
    assert data["station_count"] > 0


def test_plan_endpoint_returns_useful_validation_error():
    client = TestClient(create_app({"TESTING": True}))
    response = client.post("/api/plan", json={"origin": {}})
    assert response.status_code == 422
    assert "destination" in response.text
