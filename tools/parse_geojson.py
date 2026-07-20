#!/usr/bin/env python3
import csv
import datetime
import json
from pathlib import Path

def map_osm_connector(tags):
    connectors = []
    if tags.get("socket:type2") in ("yes", "1", "2", "3", "4"):
        connectors.append("type2")
    if tags.get("socket:ccs") in ("yes", "1", "2", "3", "4") or tags.get("socket:ccs2") in ("yes", "1", "2", "3", "4"):
        connectors.append("ccs2")
    if tags.get("socket:chademo") in ("yes", "1", "2", "3", "4"):
        connectors.append("chademo")
    if tags.get("socket:tesla") in ("yes", "1", "2", "3", "4") or tags.get("brand") == "Tesla":
        connectors.append("tesla")
    if tags.get("socket:bharat_ac_001") in ("yes", "1", "2", "3", "4"):
        connectors.append("bharat_ac_001")
    if tags.get("socket:bharat_dc_001") in ("yes", "1", "2", "3", "4"):
        connectors.append("bharat_dc_001")
    
    if not connectors:
        socket_type = tags.get("socket") or tags.get("connector")
        if socket_type:
            sl = socket_type.lower()
            if "type2" in sl or "type 2" in sl: connectors.append("type2")
            if "ccs" in sl: connectors.append("ccs2")
            if "chademo" in sl: connectors.append("chademo")

    if not connectors:
        return ["unknown"]
    return connectors

def main():
    root = Path(__file__).parent.parent
    geojson_path = root.parent / "charging_stations.geojson"
    csv_path = root / "data" / "charging_stations.csv"
    
    if not geojson_path.exists():
        print(f"File not found: {geojson_path}")
        return
        
    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    features = data.get("features", [])
    print(f"Loaded {len(features)} charging stations from GeoJSON.")
    
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    csv_headers = [
        "station_id", "name", "latitude", "longitude", "address", "city",
        "state", "country", "operator_name", "network_name", "access_type",
        "opening_hours", "status", "connector_type", "power_kw", "current_type",
        "connector_count", "payment_modes", "amenities", "source_name",
        "source_external_id", "source_license", "confidence_score", "last_verified_at"
    ]
    
    rows = []
    
    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        
        # In osmium export, 'id' is sometimes in the feature itself, e.g., "id": "node/123"
        el_id = feat.get("id") or props.get("id", "unknown/0")
        if "/" in str(el_id):
            el_type, numeric_id = str(el_id).split("/", 1)
        else:
            el_type, numeric_id = "node", str(el_id)
            
        station_id = f"osm-{el_type}-{numeric_id}"
        
        if geom.get("type") == "Point":
            lon, lat = geom["coordinates"]
        elif geom.get("type") == "Polygon":
            # Just take the first coordinate of the exterior ring
            lon, lat = geom["coordinates"][0][0]
        elif geom.get("type") == "LineString":
            lon, lat = geom["coordinates"][0]
        else:
            continue
            
        name = props.get("name") or props.get("brand") or "Unnamed charging station (India)"
        operator_name = props.get("operator") or ""
        network_name = props.get("network") or ""
        access_osm = props.get("access", "yes")
        access_type = "public" if access_osm in ("yes", "public", "permissive") else "private" if access_osm == "private" else "unknown"
        
        power_kw = ""
        output_str = props.get("charging_station:output") or props.get("socket:type2:output") or props.get("socket:ccs2:output")
        if output_str:
            try:
                power_val = float(''.join(c for c in output_str if c.isdigit() or c == '.'))
                if "w" in output_str.lower() and "kw" not in output_str.lower() and power_val > 1000:
                    power_kw = power_val / 1000.0
                else:
                    power_kw = power_val
            except Exception:
                pass

        connectors = map_osm_connector(props)
        capacity_tag = props.get("capacity") or "1"
        
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
                "opening_hours": props.get("opening_hours", ""),
                "status": "operational" if props.get("operational_status") != "closed" else "closed",
                "connector_type": connector,
                "power_kw": power_kw,
                "current_type": "",
                "connector_count": capacity_tag,
                "payment_modes": "",
                "amenities": "",
                "source_name": "openstreetmap",
                "source_external_id": f"{el_type}/{numeric_id}",
                "source_license": "ODbL",
                "confidence_score": 45 if connector == "unknown" else 60,
                "last_verified_at": now_str
            })
            
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()
        writer.writerows(rows)
        
    print(f"Wrote {len(rows)} real stations rows to {csv_path}")

if __name__ == "__main__":
    main()
