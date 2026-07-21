"""FastAPI application for the EV RouteWise planner."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Optional

from a2wsgi import ASGIMiddleware
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from ev_route.engine import InputError, load_stations, parse_point, recommend_stations
from ev_route.services import ExternalServiceError, geocode, route_options_or_fallback


ROOT = Path(__file__).resolve().parent
STATION_FILE = ROOT / "data" / "charging_stations.csv"
ASSET_VERSION = os.getenv("RENDER_GIT_COMMIT", "local")[:8]
MAX_BODY_BYTES = 128 * 1024

templates = Jinja2Templates(directory=str(ROOT / "templates"))
stations = load_stations(STATION_FILE)


class PointInput(BaseModel):
    """A map point selected by the user."""

    model_config = ConfigDict(extra="allow")

    latitude: float = Field(..., examples=[28.6129])
    longitude: float = Field(..., examples=[77.2295])
    label: Optional[str] = Field(default=None, examples=["India Gate"])


class VehicleInput(BaseModel):
    """EV battery, reserve and connector details."""

    model_config = ConfigDict(extra="allow")

    battery_capacity_kwh: float = Field(..., gt=0, examples=[40.5])
    current_soc_percent: float = Field(..., ge=0, le=100, examples=[25])
    reserve_soc_percent: float = Field(default=15, ge=0, le=80, examples=[15])
    consumption_wh_per_km: float = Field(default=145, gt=0, examples=[145])
    safety_buffer_percent: float = Field(default=10, ge=0, examples=[10])
    connector_types: list[str] = Field(default_factory=lambda: ["ccs2", "type2"], examples=[["ccs2", "type2"]])
    max_ac_kw: float = Field(default=7.2, gt=0, examples=[7.2])
    max_dc_kw: float = Field(default=50, gt=0, examples=[50])


class PreferencesInput(BaseModel):
    """How the recommendation engine should rank charging stops."""

    model_config = ConfigDict(extra="allow")

    mode: Literal["balanced", "fastest", "shortest_detour", "safest"] = "balanced"
    max_detour_km: float = Field(default=10, ge=0, examples=[10])
    minimum_station_confidence: float = Field(default=40, ge=0, le=100, examples=[40])
    allow_unverified_connectors: bool = Field(default=True, examples=[True])
    maximum_results: int = Field(default=5, ge=1, le=20, examples=[5])


class RouteInput(BaseModel):
    """Optional precomputed route supplied by a frontend or mobile client."""

    model_config = ConfigDict(extra="allow")

    points: list[PointInput] = Field(default_factory=list)
    distance_km: Optional[float] = Field(default=None, gt=0, examples=[13])
    duration_minutes: Optional[float] = Field(default=None, ge=0, examples=[35])
    source: Optional[str] = Field(default=None, examples=["osrm"])


class TripPlanRequest(BaseModel):
    """Trip request used by the charging-stop recommendation endpoint."""

    model_config = ConfigDict(extra="allow")

    origin: PointInput
    destination: PointInput
    vehicle: VehicleInput
    preferences: PreferencesInput = Field(default_factory=PreferencesInput)
    route: Optional[RouteInput] = None


TRIP_PLAN_EXAMPLE: dict[str, Any] = {
    "origin": {"latitude": 28.6129, "longitude": 77.2295, "label": "India Gate"},
    "destination": {"latitude": 28.5245, "longitude": 77.1855, "label": "Qutub Minar"},
    "vehicle": {
        "battery_capacity_kwh": 40.5,
        "current_soc_percent": 25,
        "reserve_soc_percent": 15,
        "consumption_wh_per_km": 145,
        "safety_buffer_percent": 10,
        "connector_types": ["ccs2", "type2"],
        "max_ac_kw": 7.2,
        "max_dc_kw": 50,
    },
    "preferences": {
        "mode": "balanced",
        "max_detour_km": 10,
        "minimum_station_confidence": 40,
        "allow_unverified_connectors": True,
        "maximum_results": 5,
    },
}


def _allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "*").strip()
    if raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(test_config: Optional[dict[str, Any]] = None) -> FastAPI:
    """Create the ASGI app.

    ``test_config`` is accepted to keep the existing test factory API stable.
    """

    app = FastAPI(
        title="EV RouteWise API",
        summary="EV route and charging-stop recommendation backend.",
        description=(
            "Plan EV trips, geocode Indian places, calculate route options, "
            "and recommend reachable charging stations using the app's station dataset."
        ),
        version=os.getenv("APP_VERSION", ASSET_VERSION),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.test_config = test_config or {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_BYTES:
            return JSONResponse({"error": "Trip request is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self)"
        return response

    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.get("/", include_in_schema=False)
    async def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"station_count": len(stations), "asset_version": ASSET_VERSION},
        )

    @app.get("/api/health", tags=["System"])
    async def health() -> dict[str, Any]:
        """Check whether the backend is alive and station data is loaded."""

        return {"status": "ok", "stations_loaded": len(stations)}

    @app.get("/api/geocode", tags=["Maps"])
    async def geocode_location(
        q: str = Query(..., min_length=3, description="Place name or address to search inside India.", examples=["India Gate"]),
    ) -> dict[str, Any]:
        """Search a place and return latitude/longitude candidates."""

        query = q.strip()
        if len(query) < 3:
            raise HTTPException(status_code=400, detail="Enter at least 3 characters to search for a location.")
        try:
            return {"results": geocode(query)}
        except ExternalServiceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/plan", tags=["Trip planning"])
    async def plan_trip(
        trip: TripPlanRequest = Body(..., examples=[TRIP_PLAN_EXAMPLE]),
    ) -> dict[str, Any]:
        """Recommend the best reachable charging stations for a trip."""

        payload = trip.model_dump(mode="json", exclude_none=True)
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
            return {**plans[0], "route_options": plans}
        except InputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    return app


asgi_app = create_app()
app = ASGIMiddleware(asgi_app)
