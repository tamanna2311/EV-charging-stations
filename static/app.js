/* global L */
(() => {
  "use strict";

  const demoPlaces = {
    origin: { label: "India Gate, New Delhi", latitude: 28.6129, longitude: 77.2295 },
    destination: { label: "Qutub Minar, New Delhi", latitude: 28.5245, longitude: 77.1855 },
  };
  const state = {
    places: { ...demoPlaces },
    pickMode: null,
    markers: {},
    stationMarkers: [],
    routeLine: null,
    routePlans: [],
    selectedRouteIndex: 0,
  };

  const form = document.querySelector("#planner-form");
  const results = document.querySelector("#results");
  const planButton = document.querySelector("#plan-button");
  const formError = document.querySelector("#form-error");
  const mapStatus = document.querySelector("#map-status");
  const pickMessage = document.querySelector("#map-pick-message");

  const map = L.map("map", { zoomControl: false, preferCanvas: true }).setView([28.58, 77.205], 12);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const markerIcon = (kind) => L.divIcon({
    className: "",
    html: `<div class="route-marker ${kind}-marker"><span>${kind === "origin" ? "A" : "B"}</span></div>`,
    iconSize: [27, 27],
    iconAnchor: [8, 24],
  });

  function setMarker(kind, place) {
    if (state.markers[kind]) state.markers[kind].remove();
    state.markers[kind] = L.marker([place.latitude, place.longitude], { icon: markerIcon(kind) })
      .bindTooltip(place.label, { direction: "top", offset: [5, -20] })
      .addTo(map);
  }

  setMarker("origin", state.places.origin);
  setMarker("destination", state.places.destination);
  map.fitBounds([[demoPlaces.origin.latitude, demoPlaces.origin.longitude], [demoPlaces.destination.latitude, demoPlaces.destination.longitude]], { padding: [70, 70] });

  function updatePlace(kind, place, status = "Location selected") {
    state.places[kind] = place;
    document.querySelector(`#${kind}-input`).value = place.label;
    const statusNode = document.querySelector(`#${kind}-status`);
    statusNode.textContent = status;
    statusNode.className = "place-status";
    setMarker(kind, place);
  }

  ["origin", "destination"].forEach((kind) => {
    document.querySelector(`#${kind}-input`).addEventListener("input", () => {
      state.places[kind] = null;
      const status = document.querySelector(`#${kind}-status`);
      status.textContent = "We will find this place when you plan";
      status.className = "place-status";
    });
  });

  async function resolvePlace(kind) {
    if (state.places[kind]) return state.places[kind];
    const input = document.querySelector(`#${kind}-input`);
    const status = document.querySelector(`#${kind}-status`);
    const query = input.value.trim();
    if (query.length < 3) throw new Error(`Enter a valid ${kind === "origin" ? "starting point" : "destination"}.`);
    status.textContent = "Finding this place...";
    status.className = "place-status loading";
    const response = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Location search failed.");
    if (!data.results.length) throw new Error(`We couldn't find “${query}”. Try a city or more specific address.`);
    updatePlace(kind, data.results[0], "Place found");
    return data.results[0];
  }

  document.querySelectorAll(".pick-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.pickMode = button.dataset.place;
      document.querySelectorAll(".pick-button").forEach((item) => item.classList.toggle("active", item === button));
      pickMessage.hidden = false;
      map.getContainer().style.cursor = "crosshair";
    });
  });

  function cancelPick() {
    state.pickMode = null;
    pickMessage.hidden = true;
    map.getContainer().style.cursor = "";
    document.querySelectorAll(".pick-button").forEach((item) => item.classList.remove("active"));
  }
  document.querySelector("#cancel-pick").addEventListener("click", cancelPick);
  map.on("click", (event) => {
    if (!state.pickMode) return;
    const kind = state.pickMode;
    updatePlace(kind, {
      label: `${event.latlng.lat.toFixed(5)}, ${event.latlng.lng.toFixed(5)}`,
      latitude: event.latlng.lat,
      longitude: event.latlng.lng,
    }, "Map point selected");
    cancelPick();
  });

  document.querySelector(".locate-button").addEventListener("click", () => {
    const status = document.querySelector("#origin-status");
    if (!navigator.geolocation) {
      status.textContent = "Location access is not supported in this browser";
      status.className = "place-status error";
      return;
    }
    status.textContent = "Checking your current location...";
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const place = {
          label: "My current location",
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        updatePlace("origin", place, `Using your location, about ${Math.round(position.coords.accuracy)} m accuracy`);
        map.setView([place.latitude, place.longitude], 13);
      },
      () => {
        status.textContent = "Location permission was unavailable—search or use the map instead";
        status.className = "place-status error";
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  });

  document.querySelector("#swap-route").addEventListener("click", () => {
    const oldOrigin = state.places.origin;
    const oldDestination = state.places.destination;
    const originText = document.querySelector("#origin-input").value;
    const destinationText = document.querySelector("#destination-input").value;
    state.places.origin = oldDestination;
    state.places.destination = oldOrigin;
    document.querySelector("#origin-input").value = destinationText;
    document.querySelector("#destination-input").value = originText;
    if (state.places.origin) setMarker("origin", state.places.origin);
    if (state.places.destination) setMarker("destination", state.places.destination);
  });

  function numericValue(selector) {
    return Number(document.querySelector(selector).value);
  }

  function tripPayload(origin, destination) {
    return {
      origin,
      destination,
      vehicle: {
        battery_capacity_kwh: numericValue("#battery-capacity"),
        current_soc_percent: numericValue("#current-soc"),
        reserve_soc_percent: numericValue("#reserve-soc"),
        consumption_wh_per_km: numericValue("#consumption"),
        safety_buffer_percent: numericValue("#safety-buffer"),
        max_ac_kw: numericValue("#max-ac"),
        max_dc_kw: numericValue("#max-dc"),
        connector_types: [...document.querySelectorAll('input[name="connector"]:checked')].map((node) => node.value),
      },
      preferences: {
        mode: document.querySelector('input[name="priority"]:checked').value,
        max_detour_km: numericValue("#max-detour"),
        minimum_station_confidence: 40,
        allow_unverified_connectors: document.querySelector("#allow-unverified").checked,
        maximum_results: 5,
      },
    };
  }

  function setLoading(loading) {
    planButton.disabled = loading;
    planButton.classList.toggle("loading", loading);
    planButton.querySelector("span").textContent = loading ? "Checking your route and battery" : "Show my charging plan";
    if (loading) mapStatus.textContent = "Checking where you can safely stop";
  }

  function showError(message) {
    formError.textContent = message;
    formError.hidden = false;
    mapStatus.textContent = "Update the details to continue";
  }

  function clearMapResults() {
    if (state.routeLine) state.routeLine.remove();
    state.routeLine = null;
    state.stationMarkers.forEach((marker) => marker.remove());
    state.stationMarkers = [];
  }

  function drawPlan(data) {
    clearMapResults();
    const geometry = data.route.geometry;
    state.routeLine = L.polyline(geometry, { color: "#17e88f", weight: 6, opacity: .92, lineCap: "round", lineJoin: "round" }).addTo(map);
    setMarker("origin", data.origin);
    setMarker("destination", data.destination);

    data.recommendations.forEach((station, index) => {
      const marker = L.marker([station.location.latitude, station.location.longitude], {
        icon: L.divIcon({
          className: "",
          html: `<div class="station-marker ${station.connector_verified ? "" : "unverified"}">${index + 1}</div>`,
          iconSize: [31, 31], iconAnchor: [16, 16],
        }),
      }).bindPopup(`<p class="popup-title">${escapeHtml(station.name)}</p><div class="popup-meta">Arrive with ${station.arrival_soc_percent}% · ${station.estimated_total_detour_km} km detour</div>`).addTo(map);
      state.stationMarkers.push(marker);
    });
    const bounds = state.routeLine.getBounds();
    state.stationMarkers.forEach((marker) => bounds.extend(marker.getLatLng()));
    map.fitBounds(bounds, { padding: [65, 65] });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
  }

  function metric(value, label) {
    return `<div class="metric"><b>${escapeHtml(value)}</b><span>${escapeHtml(label)}</span></div>`;
  }

  function routeDuration(plan) {
    if (!plan.route.duration_minutes) return "Estimated time";
    return plan.route.duration_minutes < 60
      ? `${plan.route.duration_minutes} min`
      : `${Math.floor(plan.route.duration_minutes / 60)}h ${plan.route.duration_minutes % 60}m`;
  }

  function renderRouteOptions() {
    const container = document.querySelector("#route-options");
    if (state.routePlans.length <= 1) {
      const plan = state.routePlans[0];
      container.innerHTML = plan ? `
        <div class="single-route-note">
          <div>
            <h3>One practical route found</h3>
            <p>This trip has one clear road route. The charging stops below are matched to it.</p>
          </div>
          <span>${plan.route.distance_km} km · ${escapeHtml(routeDuration(plan))}</span>
        </div>` : "";
      return;
    }
    container.innerHTML = `
      <div class="route-options-heading">
        <h3>Choose your route</h3>
        <span>Charging stops update with the route</span>
      </div>
      <div class="route-option-list">
        ${state.routePlans.map((plan, index) => {
          const topStop = plan.recommendations[0]?.name || "No reachable stop";
          const stopText = plan.decision.status === "no_stop_needed" ? "No stop needed" : topStop;
          return `
            <button class="route-option ${index === state.selectedRouteIndex ? "active" : ""}" type="button" data-route-index="${index}">
              <span><b>${escapeHtml(plan.route.label || `Route ${index + 1}`)}</b><small>${escapeHtml(stopText)}</small></span>
              <span><b>${plan.route.distance_km} km</b><small>${escapeHtml(routeDuration(plan))}</small></span>
            </button>`;
        }).join("")}
      </div>`;
    container.querySelectorAll(".route-option").forEach((button) => {
      button.addEventListener("click", () => {
        const nextIndex = Number(button.dataset.routeIndex);
        const nextPlan = state.routePlans[nextIndex];
        if (!nextPlan) return;
        renderPlan(nextPlan, nextIndex, true);
      });
    });
  }

  function stationCard(station, index, chargingRequired) {
    const verifiedLabel = station.connector_verified
      ? `Fits your plug · ${station.matching_connectors.join(", ")}`
      : `Check plug before relying on this stop · ${station.connectors.join(", ")}`;
    const chargeText = chargingRequired
      ? station.can_finish_after_charge
        ? `Stop here with about <b>${station.arrival_soc_percent}%</b> battery. Charge to around <b>${station.suggested_target_soc_percent}%</b>${station.estimated_charge_minutes ? `, about ${station.estimated_charge_minutes} min` : ""}.`
        : "This stop may still leave you short of the destination. Choose another stop or start with more charge."
      : `You can finish without stopping. This is a backup option where you should arrive with about <b>${station.arrival_soc_percent}%</b>.`;
    return `
      <article class="station-card ${index === 0 ? "best" : ""}">
        <div class="station-top">
          <div class="station-name"><span class="station-rank">${index + 1}</span><h4>${escapeHtml(station.name)}</h4><p>${escapeHtml(station.operator_name)}</p></div>
          <span class="score">${index === 0 ? "Best fit" : "Option " + (index + 1)}</span>
        </div>
        <span class="verification-badge ${station.connector_verified ? "" : "unverified"}">${escapeHtml(verifiedLabel)}</span>
        <div class="station-facts">
          <div><b>${station.distance_from_start_km} km</b><span>after start</span></div>
          <div><b>${station.estimated_total_detour_km} km</b><span>detour</span></div>
          <div><b>${station.arrival_soc_percent}%</b><span>battery there</span></div>
          <div><b>${station.power_kw ? `${station.power_kw} kW` : "Check app"}</b><span>charger speed</span></div>
        </div>
        <div class="charge-instruction">${chargeText}</div>
        <div class="reason-list">${station.reasons.map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div>
      </article>`;
  }

  function renderPlan(data, selectedIndex = 0, keepRouteOptions = false) {
    if (!keepRouteOptions && Array.isArray(data.route_options) && data.route_options.length) {
      state.routePlans = data.route_options;
      data = state.routePlans[selectedIndex] || data;
    }
    state.selectedRouteIndex = selectedIndex;
    drawPlan(data);
    form.hidden = true;
    document.querySelector("#intro").hidden = true;
    results.hidden = false;
    document.querySelector("#decision-card").innerHTML = `
      <div class="decision-card ${data.decision.status}">
        <span class="decision-icon">${data.decision.status === "no_stop_needed" ? "✓" : data.decision.status === "stop_required" ? "⚡" : "!"}</span>
        <h3>${escapeHtml(data.decision.title)}</h3><p>${escapeHtml(data.decision.summary)}</p>
      </div>`;
    renderRouteOptions();
    const duration = data.route.duration_minutes
      ? data.route.duration_minutes < 60
        ? `${data.route.duration_minutes} min`
        : `${Math.floor(data.route.duration_minutes / 60)}h ${data.route.duration_minutes % 60}m`
      : "Estimated";
    document.querySelector("#metrics").innerHTML = [
      metric(`${data.route.distance_km} km`, "Trip distance"),
      metric(duration, "Drive time"),
      metric(`${data.battery.energy_needed_kwh} kWh`, "Energy needed"),
      metric(`${data.battery.safe_range_km} km`, "Range before reserve"),
      metric(`${data.battery.estimated_direct_arrival_soc_percent}%`, "Arrival without stop"),
      metric(`${data.battery.reserve_soc_percent}%`, "Battery to keep"),
    ].join("");
    const chargingRequired = data.decision.status !== "no_stop_needed";
    document.querySelector("#station-results").innerHTML = data.recommendations.length
      ? `<div class="station-section-title"><h3>${chargingRequired ? "Best places to stop" : "Good backups on your route"}</h3><span>${data.candidate_count} nearby options checked</span></div>${data.recommendations.map((station, index) => stationCard(station, index, chargingRequired)).join("")}`
      : `<div class="empty-box"><b>No reachable charging stop found.</b><br>Try starting with more battery, allowing a longer detour, or showing stations with missing plug details.</div>`;
    document.querySelector("#warnings").innerHTML = data.warnings.length
      ? `<div class="warning-box">${data.warnings.map((warning) => `• ${escapeHtml(warning)}`).join("<br>")}</div>` : "";
    mapStatus.textContent = data.route.source === "osrm" ? "Route ready with charging stops" : "Estimated route ready";
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    formError.hidden = true;
    if (!form.reportValidity()) return;
    setLoading(true);
    try {
      const [origin, destination] = await Promise.all([resolvePlace("origin"), resolvePlace("destination")]);
      const payload = tripPayload(origin, destination);
      if (!payload.vehicle.connector_types.length) throw new Error("Select at least one charging connector supported by your EV.");
      if (payload.vehicle.current_soc_percent < payload.vehicle.reserve_soc_percent) throw new Error("Current battery is below the selected reserve. Charge before starting or lower the reserve.");
      const response = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The trip could not be planned.");
      renderPlan(data);
    } catch (error) {
      showError(error.message || "The trip could not be planned.");
    } finally {
      setLoading(false);
    }
  });

  function editTrip() {
    results.hidden = true;
    form.hidden = false;
    document.querySelector("#intro").hidden = false;
    document.querySelector("#intro").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  document.querySelector("#edit-trip").addEventListener("click", editTrip);
  document.querySelector("#plan-another").addEventListener("click", editTrip);
})();
