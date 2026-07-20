#!/usr/bin/env python3
import csv
import datetime
import json
import logging
from pathlib import Path
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

OVERPASS_URL = "https://overpass.openstreetmap.fr/api/interpreter"
QUERY = """
[out:json][timeout:90];
area["ISO3166-1"="IN"][admin_level="2"]->.searchArea;
(
  node["amenity"="charging_station"](area.searchArea);
  way["amenity"="charging_station"](area.searchArea);
  relation["amenity"="charging_station"](area.searchArea);
);
out center;
"""

def positive_number(value):
    if value in (None, ""):
        return ""
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return ""
    if number <= 0:
        return ""
    return str(int(number)) if number.is_integer() else str(number)


def map_osm_connector(tags):
    # OSM often uses socket:<type> keys, e.g., socket:type2, socket:ccs
    # We will try to map to our known types
    connectors = []
    if tags.get("socket:type2") in ("yes", "1", "2", "3", "4"):
        connectors.append("type2")
    if (
        tags.get("socket:ccs") in ("yes", "1", "2", "3", "4")
        or tags.get("socket:ccs2") in ("yes", "1", "2", "3", "4")
        or tags.get("socket:type2_combo") in ("yes", "1", "2", "3", "4")
    ):
        connectors.append("ccs2")
    if tags.get("socket:chademo") in ("yes", "1", "2", "3", "4"):
        connectors.append("chademo")
    if tags.get("socket:tesla") in ("yes", "1", "2", "3", "4") or tags.get("brand") == "Tesla":
        connectors.append("tesla")
    # Indian standards
    if tags.get("socket:bharat_ac_001") in ("yes", "1", "2", "3", "4"):
        connectors.append("bharat_ac_001")
    if tags.get("socket:bharat_dc_001") in ("yes", "1", "2", "3", "4"):
        connectors.append("bharat_dc_001")
    
    # If no socket tags, try 'connector' or 'socket' tag
    if not connectors:
        socket_type = tags.get("socket") or tags.get("connector")
        if socket_type:
            sl = socket_type.lower()
            if "type2" in sl or "type 2" in sl: connectors.append("type2")
            if "ccs" in sl: connectors.append("ccs2")
            if "chademo" in sl: connectors.append("chademo")

    if not connectors:
        return "unknown"
    
    # If multiple connectors exist, we can just return one or comma-separated.
    # Our CSV parser in `engine.py` might only read one if we don't comma-separate?
    # Wait, the engine groups by station_id and aggregates connectors if there are multiple rows.
    # Alternatively, if we just want one connector per row, we can return the first. 
    # But wait! If we have multiple, the original CSV repeated the node with different connectors? No, the original CSV just had one connector_type field. It seemed to have duplicate rows or `unknown`.
    # Let's just output multiple rows per station if there are multiple connectors.
    # We'll return a list and handle it later.
    return connectors

import subprocess

def main():
    logging.info("Querying Overpass API via curl...")
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "-d", f"data={QUERY}", OVERPASS_URL],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Curl failed: {e.stderr}")
        return
    except json.JSONDecodeError:
        logging.error(f"Failed to parse JSON from Overpass. Output was: {result.stdout[:500]}")
        return
    
    elements = data.get("elements", [])
    logging.info(f"Retrieved {len(elements)} charging stations from OSM.")
    
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    csv_headers = [
        "station_id", "name", "latitude", "longitude", "address", "city",
        "state", "country", "operator_name", "network_name", "access_type",
        "opening_hours", "status", "connector_type", "power_kw", "current_type",
        "connector_count", "payment_modes", "amenities", "source_name",
        "source_external_id", "source_license", "confidence_score", "last_verified_at"
    ]
    
    output_path = Path(__file__).parent.parent / "data" / "charging_stations.csv"
    
    rows = []
    
    for el in elements:
        el_type = el["type"]
        el_id = el["id"]
        station_id = f"osm-{el_type}-{el_id}"
        tags = el.get("tags", {})
        
        # Geometry
        if el_type == "node":
            lat = el["lat"]
            lon = el["lon"]
        else:
            lat = el.get("center", {}).get("lat")
            lon = el.get("center", {}).get("lon")
            if lat is None or lon is None:
                continue
        
        # Tags parsing
        name = tags.get("name") or tags.get("brand") or "Unnamed charging station (India)"
        operator_name = tags.get("operator") or ""
        network_name = tags.get("network") or ""
        access_osm = tags.get("access", "yes")
        access_type = "public" if access_osm in ("yes", "public", "permissive") else "private" if access_osm == "private" else "unknown"
        
        # capacity -> power? or socket:<type>:output -> power?
        power_kw = ""
        capacity_tag = positive_number(tags.get("capacity"))
        # In OSM, capacity usually means number of vehicles. 
        # For power, usually socket:<type>:output or charging_station:output
        # Let's try charging_station:output
        output_str = tags.get("charging_station:output") or tags.get("socket:type2:output") or tags.get("socket:ccs2:output")
        if output_str:
            # e.g., '22 kW', '50kW', '22'
            try:
                # very rough parsing
                power_val = float(''.join(c for c in output_str if c.isdigit() or c == '.'))
                if "w" in output_str.lower() and "kw" not in output_str.lower() and power_val > 1000:
                    power_kw = power_val / 1000.0  # maybe it was in W
                else:
                    power_kw = power_val
            except Exception:
                pass

        connectors = map_osm_connector(tags)
        if isinstance(connectors, str):
            connectors = [connectors]
        
        for connector in connectors:
            rows.append({
                "station_id": station_id,
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "address": "",
                "city": "",
                "state": "",
                "country": "India",
                "operator_name": operator_name,
                "network_name": network_name,
                "access_type": access_type,
                "opening_hours": tags.get("opening_hours", ""),
                "status": "operational" if tags.get("operational_status") != "closed" else "closed",
                "connector_type": connector,
                "power_kw": power_kw,
                "current_type": "",
                "connector_count": capacity_tag or "1",
                "payment_modes": "",
                "amenities": "",
                "source_name": "openstreetmap",
                "source_external_id": f"{el_type}/{el_id}",
                "source_license": "ODbL",
                "confidence_score": 45 if connector == "unknown" else 60,
                "last_verified_at": now_str
            })
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        
    logging.info(f"Wrote {len(rows)} rows to {output_path}")

if __name__ == "__main__":
    main()
