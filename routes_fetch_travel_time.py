import os, sqlite3
import requests
from dotenv import load_dotenv
import json, time

load_dotenv()

API_KEY = os.environ["GOOGLE_MAPS_API_KEY"]

ORIGIN_LABEL = os.environ["ORIGIN_LABEL"]
ORIGIN_ADDRESS = os.environ["ORIGIN_ADDRESS"]
DEST_LABEL = os.environ["DEST_LABEL"]
DEST_ADDRESS = os.environ["DEST_ADDRESS"]

DB = "commute.db"
PROVIDER = "google"

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
# Use the Google Routes API (computeRoutes)
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def get_db():
    return sqlite3.connect(DB)


def fetch_coords(label: str, address: str):
    """Resolve and cache lat/lon for a label+address using Google Geocoding."""
    con = get_db()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT lat, lon FROM locations WHERE label=?", (label,))
    row = cur.fetchone()
    if row and row["lat"] is not None and row["lon"] is not None:
        con.close()
        return row["lat"], row["lon"]

    r = requests.get(GEOCODE_URL, params={"address": address, "key": API_KEY}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK" or not data.get("results"):
        raise RuntimeError(f"Geocode failed for '{label}': {data.get('status')}")

    loc = data["results"][0]["geometry"]["location"]
    lat, lon = float(loc["lat"]), float(loc["lng"])

    cur.execute(
        """
        INSERT INTO locations(label, address, lat, lon)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(label) DO UPDATE SET address=excluded.address, lat=excluded.lat, lon=excluded.lon
        """,
        (label, address, lat, lon),
    )
    con.commit()
    con.close()
    return lat, lon


def _extract_route_info(route):

    description = route["description"]

    # distsance 
    meters = route.get("distanceMeters")
    miles = route['localizedValues']['distance']['text']  # e.g., "12.3 mi"

    # duration
    duration_seconds = route["duration"]
    duration_static = route["localizedValues"]["staticDuration"]["text"]  # e.g., "25 mins"
    duration_minutes = route["localizedValues"]["duration"]["text"]  # e.g., "25 mins"
    
    output = {
        "description": description,
        "meters": meters,
        "miles": float(miles.split(" ")[0]),
        "duration_seconds": int(duration_seconds[:-1]),
        "duration_static": int(duration_static.split(" ")[0]),
        "duration_minutes": int(duration_minutes.split(" ")[0]),
    }

    return output

def fetch_directions(o_lat, o_lon, d_lat, d_lon):
    """
    Use Google Routes API (computeRoutes). Try key in query param first,
    fall back to X-Goog-Api-Key header. On error include full response for
    diagnosis.
    """

    body = {
        "origin": {"location": {"latLng": {"latitude": float(o_lat), "longitude": float(o_lon)}}},
        "destination": {"location": {"latLng": {"latitude": float(d_lat), "longitude": float(d_lon)}}},
        "travelMode": "DRIVE",
        "units": "IMPERIAL",
        "computeAlternativeRoutes": True,
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
        # "departureTime": {"seconds": int(time.time())}
    }

    headers = {
        "X-Goog-Api-Key": API_KEY,
        "Content-Type": "application/json",
        # "X-Goog-FieldMask":  "*", #"routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.legs.durationSeconds,routes.legs.durationWithTrafficSeconds,routes.legs.distanceMeters,routes.travelAdvisory",
        "X-Goog-FieldMask":  "routes.duration,routes.distanceMeters,routes.localizedValues,routes.description",
    }

    r = requests.post(
        ROUTES_URL,
        params=None,
        headers=headers,
        json=body,
        timeout=25
        )

        # If 404/403/etc, surface full response for debugging
    if not r.ok:
        body_text = None
        try:
            body_text = r.json()
        except ValueError:
            body_text = r.text
        raise RuntimeError(
            f"Routes API returned {r.status_code}\nheaders: {dict(r.headers)}\nbody: {body_text}\n\n"
            "Check: Routes API enabled for the project, billing active, API key belongs to that project "
            "and has the Routes API enabled (or try a service account / OAuth)."
        )

    data = r.json()

    if not data.get("routes"):
        raise RuntimeError(f"Routes API failed: no routes returned - {data}")

    print(f"{len(data['routes']) = }")
    print(json.dumps(data, indent=2))
    # breakpoint()

    results = []
    for route in data['routes']:
        route_details = _extract_route_info(route)
        results.append({**route_details})

    return results


def main():
    o_lat, o_lon = fetch_coords(ORIGIN_LABEL, ORIGIN_ADDRESS)
    d_lat, d_lon = fetch_coords(DEST_LABEL, DEST_ADDRESS)


    results = fetch_directions(o_lat, o_lon, d_lat, d_lon)
    for result in results: 

        con = get_db()
        cur = con.cursor()
        
        cur.execute(
            """
            INSERT INTO travel_times(origin_label, dest_label, description, meters, miles, duration_seconds, duration_static, duration_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ORIGIN_LABEL, DEST_LABEL, result["description"], result["meters"], result["miles"], result["duration_seconds"], result["duration_static"], result["duration_minutes"]),
        )
        con.commit()
        con.close()

        # print(f"Logged: {ORIGIN_LABEL} → {DEST_LABEL} = {mins} min ({meters/1000:.1f} km) [{MODE}/{PROVIDER}]")
        print(f"Logged route: {result['description']} - {result['duration_minutes']} mins, {result['meters']/1000:.1f} km / {result['miles']} miles") 

if __name__ == "__main__":
    main()