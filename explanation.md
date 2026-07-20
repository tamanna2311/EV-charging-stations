# EV RouteWise: Project & Data Explanation

This document provides a comprehensive overview of how the **EV RouteWise** application works, the problem it solves, our data collection strategy, and why we made specific technical decisions regarding charging station data in India.

---

## 1. What Are We Trying to Do?
**The Problem:** Driving an Electric Vehicle (EV) on long-distance trips causes "range anxiety." Unlike petrol pumps, which are everywhere and take minutes to use, EV chargers are scattered, take longer to charge, and have different connector types (CCS2, Type 2, CHAdeMO, etc.). 

**The Solution:** We are building a "route-aware" EV charging recommendation engine. Instead of just showing a map full of chargers, the application:
1. Calculates the exact road route between an origin and destination.
2. Checks if the vehicle can make the trip on its current battery level.
3. If not, it specifically recommends the *best* compatible charging stations along that specific route, ensuring the driver reaches the charger before their battery falls below a safe reserve.

## 2. How Is It Working? (The Technical Flow)
The application is a Python web service built with Flask (`app.py`). Here is the step-by-step workflow of the engine (`ev_route/engine.py`):
1. **User Input:** The user provides an origin, destination, vehicle battery capacity, current state of charge (%), consumption rate (Wh/km), and plug type.
2. **Routing:** The app calls an external service (OSRM - Open Source Routing Machine) to get the real road distance and the geographical shape of the route.
3. **Energy Calculation:** It calculates the total energy required to drive that route, factoring in a safety buffer.
4. **Filtering:** It scans our local database of charging stations. It rejects stations that are too far off the route (too much detour), have incompatible plugs, or are further away than the car's current range can reach.
5. **Ranking:** The remaining feasible stations are ranked based on a scoring system (detour distance, charger power speed, data confidence, and arrival battery margin).
6. **Output:** The frontend displays the route and the top-ranked chargers to the driver.

## 3. What Kind of Data Are We Collecting?
To make this work, the engine requires a highly structured database of charging stations. For each station, we need:
- **Location:** Exact Latitude and Longitude.
- **Hardware:** Connector Types (e.g., ccs2, type2) and Power Output in kW (to estimate charging time).
- **Access Details:** Operator name, network name, and public accessibility.
- **Verification:** A confidence score to warn users if the data might be outdated or unverified.

## 4. From Where Are We Getting This Data?
Currently, our source of truth is **OpenStreetMap (OSM)**, the world's largest open-source geographic database.

Initially, the app shipped with a tiny, static CSV file containing about ~150 charging stations limited to the Delhi-NCR region. To scale the application to cover all of India, we did the following:
1. We bypassed rate-limited or paid APIs (like OpenChargeMap or PlugShare).
2. We downloaded a massive **1.6 GB raw database export (`india-latest.osm.pbf`)** directly from Geofabrik (a server that provides daily OSM snapshots).
3. We used a low-level C++ tool called `osmium` to scan through millions of map nodes in India and filter out only the elements tagged with `amenity=charging_station`.
4. We parsed the resulting geographical data (GeoJSON) using a custom Python script (`tools/parse_geojson.py`) and converted it into our application's native CSV format (`data/charging_stations.csv`).

## 5. Why Are We Doing It This Way?
- **Cost and Independence:** Commercial APIs (like EcoMovement or PlugShare) charge thousands of dollars for Enterprise API access. Official Indian government sources (like E-Amrit) don't always provide clean, machine-readable CSVs with exact geographic coordinates. Pulling raw OpenStreetMap data is 100% free, legally open (ODbL license), and highly scalable.
- **Performance:** Relying on a third-party API every time a user searches for a route is slow and introduces points of failure. By downloading the dataset and converting it into a local CSV file, our Flask application loads all ~530+ stations into server memory when it starts up. This allows our recommendation engine to calculate complex spatial math (like route projections) in milliseconds.

## 6. How Are We Using This Data?
The parsed data lives in `data/charging_stations.csv`. 

When the Flask server starts (`flask run`), the `load_stations()` function reads this CSV file and groups identical physical stations together (collapsing multiple plugs at the same location into a single physical site).

During a route request, the application loops through this in-memory list, uses the Haversine formula to find stations near the road corridor, and serves the results to the web UI so the driver knows exactly where to stop.
